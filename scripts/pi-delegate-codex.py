#!/usr/bin/env python3
"""固定 Codex 委托入口；只汇报观察事实，物理终止由父 supervisor 独立证明。"""

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

# 已密封运行包不能在导入时生成 __pycache__。
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.model_delegate import validate_record
from agentcfg.model_delegate_backends import CodexEvents, codex_command
from agentcfg.pi_control import request as control_request
from agentcfg.pi_codex_admission import CodexAdmissionError, admit_codex_execution, admit_codex_endpoint
from agentcfg.pi_delegate_policy import validate_policy_binding
from agentcfg.pi_supervisor import closed
from agentcfg.storage import Conflict, Tree, ensure_private


def rejected_event(error, event):
  """只保留本地枚举和解析阶段；不记录原始事件、工具参数或错误正文。"""
  kinds = {"thread.started", "turn.started", "turn.completed", "turn.failed", "item.started", "item.updated", "item.completed", "error"}
  names = {"agent_message", "reasoning", "command_execution", "file_change", "web_search", "todo_list", "error", "mcp_tool_call", "collab_tool_call"}
  codes = {"delegate-codex-event", "delegate-codex-item", "delegate-codex-item-type", "delegate-codex-event-type", "delegate-codex-message", "delegate-codex-thread", "delegate-codex-usage"}
  kind = event.get("type") if isinstance(event, dict) else None
  item = event.get("item") if isinstance(event, dict) else None
  name = item.get("type") if isinstance(item, dict) else None
  code = getattr(error, "code", None)
  return {"schema_version": 1, "event_type": kind if isinstance(kind, str) and kind in kinds else "unrecognized",
    "item_type": name if isinstance(name, str) and name in names else "unrecognized",
    "failure_code": code if isinstance(code, str) and code in codes else "DELEGATE_CODEX_STREAM_INVALID"}


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--input", type=Path, required=True)
  args = parser.parse_args()
  with Tree(args.input.parent) as tree:
    raw = tree.read(args.input.name)
  worker = json.loads(raw[0])
  closed(worker, ("schema_version", "input", "reports", "runtime_root", "instance_root", "temporary", "backend_executable", "native_permissions"), ("resume_token",))
  value = worker["input"]; request = value["request"]
  validate_record("request-v2", request)
  policy = validate_policy_binding(value)
  if worker["schema_version"] != 2 or request["backend"] != "codex" or request["cwd"] != os.getcwd():
    raise Conflict("DELEGATE_WORKER_IDENTITY")
  if value["definition_digest"] != digest({key: item for key, item in value.items() if key != "definition_digest"}):
    raise Conflict("DELEGATE_WORKER_IDENTITY")
  endpoint, capability = os.environ["AGENTCFG_SUPERVISOR_ENDPOINT"], os.environ.pop("AGENTCFG_SUPERVISOR_CAPABILITY")
  def control(method, body):
    result = control_request(endpoint, capability, {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": method, "args": body})
    if result.get("ok") is not True:
      raise Conflict("DELEGATE_CONTROL_UNAVAILABLE")
    return result["result"]
  owner = control("handshake", {})
  process_matches = owner["process_identity"]["pid"] == os.getpid()
  if not process_matches and sys.platform == "linux" and os.getpid() == 1:
    from agentcfg.pi_pid_namespace import same_namespace_process, local_namespace_identity
    process_matches = same_namespace_process(owner["process_identity"], local_namespace_identity())
  if (owner["role"] != "worker" or owner["lease_id"] != request["lease_id"] or not process_matches
      or owner["runtime_identity"] != request["runtime_identity"]):
    raise Conflict("DELEGATE_WORKER_IDENTITY")
  if not control("authorize", {"lease_id": request["lease_id"], "grant_generation": request["grant_generation"]})["valid"]:
    raise Conflict("DELEGATE_GRANT_REVOKED")
  reports = Path(worker["reports"])
  ensure_private(reports)
  native_final = Path(worker["temporary"]) / "native-final.md"
  if native_final.exists() or native_final.is_symlink():
    raise Conflict("DELEGATE_FINAL_ALREADY_EXISTS")
  argv = codex_command(worker["backend_executable"], request, native_final, permissions=worker["native_permissions"], resume_token=worker.get("resume_token"), retry_limit=value.get("retry_limit", 0), native=policy["native_execution"], api_base_url=policy.get("api_base_url"))
  child_env = {key: value for key, value in os.environ.items() if key in {"HOME", "TMPDIR", "PATH", "LANG", "CODEX_HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"}}
  if child_env.get("CODEX_HOME") != str(Path(worker["instance_root"]) / "codex-home"):
    raise Conflict("DELEGATE_AUTH_HOME")
  admission = admit_codex_execution(child_env["CODEX_HOME"])
  admit_codex_endpoint(admission, policy.get("api_base_url"))
  with Tree(reports) as tree:
    tree.write_state("configuration-admission.json", json_bytes({**admission,
      **{key: request[key] for key in ("run_id", "lease_id", "request_digest", "execution_policy_digest")}}))
  if not control("authorize", {"lease_id": request["lease_id"], "grant_generation": request["grant_generation"]})["valid"]:
    raise Conflict("DELEGATE_GRANT_REVOKED")
  child = subprocess.Popen(argv, cwd=request["cwd"], env=child_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=False)
  # 原始stderr仅排空，不进入公开日志/进度或凭证。错误通过稳定状态和退出码表达。
  def drain():
    while child.stderr.read(65536):
      pass
  drainer = threading.Thread(target=drain, daemon=True); drainer.start()
  with Tree(reports) as tree:
    tree.write_state("ready.json", json_bytes({"ready": True, **{key: request[key] for key in ("run_id", "lease_id", "request_digest")}}))
  child.stdin.write(value["prompt"].encode()); child.stdin.close()
  decoder = CodexEvents(); sequence = 0; invalid = False
  for line in iter(lambda: child.stdout.readline(1024 * 1024 + 1), b""):
    if invalid:
      continue
    event = None
    try:
      if len(line) > 1024 * 1024 or not line.endswith(b"\n"):
        raise ValueError()
      event = json.loads(line)
      semantic = decoder.accept(event)
      if semantic:
        sequence += 1
        event = {"schema_version": 2, "run_id": request["run_id"], "seq": sequence, "timestamp": datetime.now(timezone.utc).isoformat(),
          "kind": semantic[0], "phase": semantic[1], "artifact_id": None}
        with Tree(reports) as tree:
          tree.write_state("event-" + str(sequence).zfill(12) + ".json", json_bytes(event))
    except Exception as error:
      invalid = True
      with Tree(reports) as tree: tree.write_state("rejected-event.json", json_bytes(rejected_event(error, event)))
      control("delegate_abort", {"run_id": request["run_id"], "lease_id": request["lease_id"]})
  status = child.wait(); drainer.join(timeout=2)
  final = b""
  with Tree(Path(worker["temporary"])) as tree:
    raw = tree.read("native-final.md", max_bytes=16 * 1024 * 1024)
  if raw:
    final = raw[0]
  successful = status == 0 and not invalid and decoder.completed and not decoder.active and bool(final.strip())
  successful &= decoder.last_message is not None and final.decode("utf8").strip() == decoder.last_message.strip()
  with Tree(reports) as tree:
    if successful:
      tree.write_state("final.md", final)
    tree.write_state("result.json", json_bytes({"schema_version": 2, "run_id": request["run_id"], "attempt_id": request["attempt_id"],
      "request_digest": request["request_digest"], "process_identity": owner["process_identity"], "host_completed": successful,
      "observed_model": None, "resume_token": decoder.thread, "usage": decoder.usage, "feedback_dispositions": []}))
  return 0 if successful else 5


if __name__ == "__main__":
  try:
    sys.exit(main())
  except CodexAdmissionError as error:
    sys.stderr.write(str(error) + "\n")
    sys.exit(error.exit_code)
  except Exception:
    sys.stderr.write("DELEGATE_CODEX_FAILED\n")
    sys.exit(5)
