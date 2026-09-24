"""V2 用户 CLI；只访问指定实例，模型工具另走同一管理者的 external RPC。"""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import uuid

from .activity import digest
from .deployment import json_bytes, read_state
from .model_delegate import DelegationRuns, control_envelope, selected_route, saved_termination, verify_receipt
from .pi import key_variable, route_key_variable
from .pi_control import read_frame, request as control_request
from .process import DependencyError
from .schema import ConfigError
from .storage import Conflict, Tree


class DelegateFailure(Exception):
  def __init__(self, code, reason=None):
    from .pi_codex_admission import REASONS
    self.exit_code = code if code in (2, 3, 4, 5, 6) else 6
    self.error_code = reason if isinstance(reason, str) and reason in REASONS else "DELEGATE_CONTROL_REJECTED"
    super().__init__(self.error_code)


class Arguments(argparse.ArgumentParser):
  def error(self, message):
    self.exit(2, "DELEGATE_ARGUMENT_INVALID\n")


def instance_binding(instance):
  instance = Path(instance).absolute()
  with Tree(instance) as tree:
    raw = tree.read(".agentcfg-instance.json")
  if raw is None or raw[1] != 0o600:
    raise Conflict("DELEGATE_INSTANCE_UNBOUND")
  value = json.loads(raw[0])
  if set(value) != {"schema_version", "state_root", "binding"} or value["schema_version"] != 1:
    raise Conflict("DELEGATE_INSTANCE_UNBOUND")
  return instance, value


def endpoint_call(instance, method, args):
  instance, binding = instance_binding(instance)
  endpoint = Path(binding["state_root"]) / "activity/control/control.json"
  with Tree(endpoint.parent) as tree:
    raw = tree.read(endpoint.name)
  if raw is None:
    raise Conflict("DELEGATE_SUPERVISOR_UNAVAILABLE")
  record = json.loads(raw[0])
  reply = control_request(endpoint, record["user_capability"], {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": method, "args": args})
  if reply.get("ok") is not True:
    raise DelegateFailure(reply.get("exit_code"), reply.get("error"))
  return reply["result"]


def saved_status(instance, run_id):
  instance, binding = instance_binding(instance)
  runs = DelegationRuns(instance / "pi-home/model-delegate/runs")
  row = runs.read(run_id)
  if row["request"]["instance_id"] != digest({"instance": str(instance), "binding": binding["binding"]}):
    raise Conflict("DELEGATE_INSTANCE_MISMATCH")
  # 停止后的历史状态可以只读展示；没有在线监督者时绝不据此 resume 或改租约。
  value = runs.status(run_id)
  value["verification"] = "unverified"
  if row["receipt"] and row["receipt"]["terminal_status"] == "completed":
    import hashlib
    from .pi_worker_files import snapshot
    proof = saved_termination(binding["state_root"], row["request"])
    with Tree(Path(binding["state_root"])) as tree:
      exit_record = json.loads(tree.read("activity/exits/" + row["request"]["lease_id"] + ".json")[0])
    with Tree(instance / "pi-home/model-delegate/reports" / run_id) as tree:
      artifact = tree.read("final.md", max_bytes=16 * 1024 * 1024)
      report = json.loads(tree.read("result.json")[0])
    if (exit_record["process_identity"] != proof["process_identity"] or report["process_identity"] != proof["process_identity"]
        or any(report[key] != row["request"][key] for key in ("run_id", "attempt_id", "request_digest"))):
      raise Conflict("DELEGATE_RESULT_IDENTITY")
    proof.update(exit_code=exit_record["exit_code"], final_artifact_digest=hashlib.sha256(artifact[0]).hexdigest() if artifact else None,
      final_nonempty=bool(artifact and artifact[0].strip()), host_completed=report["host_completed"],
      sequence_complete=bool(row["events"] and row["events"][-1]["kind"] == "completed"),
      candidate_digest=snapshot(row["request"]["cwd"], protected_roots=[binding["binding"]["local"], instance, binding["state_root"]]))
    from .pi_delegate_policy import verify_execution_policy
    proof.update(verify_execution_policy(instance / "pi-home/model-delegate", row["request"]))
    value["verification"] = verify_receipt(row["request"], row["receipt"], proof)["verification"]
    from .model_delegate_context import verify_saved_feedback
    verify_saved_feedback(instance / "pi-home/model-delegate", row["request"], row["receipt"], artifact[0])
    value["artifact_ref"] = row["receipt"]["final_artifact_id"]
  return value


def launch_single(workspace, request):
  from .runtime import run
  with Tree(workspace.instance) as tree:
    manifest = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])
  route_id, _ = selected_route(manifest, request["backend"], request["model"])
  allowed = {route_key_variable(route_id)}
  if request["backend"] == "pi":
    allowed.add(key_variable(request["model"]["provider_id"].removeprefix("agentcfg-")))
  reply = None
  def execute(w, spec, env, lease_fd, saved, *, lifecycle_fd):
    nonlocal reply
    runtime_root = w.backend.root(w, saved.get("runtime_identity", saved["lock_identity"]))
    with Tree(runtime_root) as tree:
      receipt = json.loads(tree.read(".agentcfg-receipt.json")[0])
    frozen = runtime_root / "supervisor"
    config = {"state_root": str(w.state_root), "instance_root": str(w.instance), "repository": str(frozen), "runtime_root": str(runtime_root),
      "instance_id": digest({"instance": str(w.instance), "binding": w.binding}), "lock_identity": saved["lock_identity"],
      "slice_identity": receipt["slice_identity"], "policy_digest": digest(manifest["permission_policy"]), "manifest_digest": digest(manifest),
      "cwd": str(spec.cwd), "engine": manifest["engine"], "argv": list(spec.argv), "delegate_request": request,
      "protected_roots": [str(w.local_path), str(w.instance), str(w.state_root)]}
    read_fd, write_fd = os.pipe()
    try:
      with tempfile.TemporaryFile(dir=w.state_root) as bootstrap:
        bootstrap.write(json_bytes(config)); bootstrap.flush(); bootstrap.seek(0)
        child = subprocess.Popen([sys.executable, "-I", str(frozen / "scripts/pi-supervisor.py"), "--bootstrap-fd", str(bootstrap.fileno()),
          "--lease-fd", str(lease_fd), "--instance-fd", str(lifecycle_fd), "--ready-fd", str(write_fd), "--", *spec.argv],
          cwd=spec.cwd, env=env, pass_fds=(bootstrap.fileno(), lease_fd, lifecycle_fd, write_fd), start_new_session=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      os.close(write_fd); write_fd = None
      with selectors.DefaultSelector() as selector:
        selector.register(read_fd, selectors.EVENT_READ)
        if not selector.select(10):
          raise Conflict("DELEGATE_START_UNKNOWN")
      with os.fdopen(read_fd, "rb") as channel:
        read_fd = None; reply = read_frame(channel)
      if reply.get("ok") is not True:
        raise DelegateFailure(reply.get("exit_code"), reply.get("error_code"))
      return 0
    finally:
      if read_fd is not None: os.close(read_fd)
      if write_fd is not None: os.close(write_fd)
  run(workspace, cwd=Path(request["cwd"]), launch_operation=execute,
    select_environment=lambda item: not hasattr(item.value, "reference") or item.name in allowed)
  return reply["result"]


def parser():
  value = Arguments(prog="run-model", allow_abbrev=False)
  value.add_argument("action", choices=("start", "resume", "status", "cancel", "poll", "wait", "probe", "result"))
  value.add_argument("--instance", type=Path, required=True)
  value.add_argument("--backend", choices=("pi", "codex"))
  value.add_argument("--mode", choices=("review", "investigate", "implement"))
  value.add_argument("--preset", default="general")
  value.add_argument("--provider")
  value.add_argument("--model")
  value.add_argument("--cwd", type=Path)
  value.add_argument("--prompt-file", type=Path)
  contexts = value.add_mutually_exclusive_group()
  contexts.add_argument("--context-artifact")
  contexts.add_argument("--context-file", type=Path)
  contexts.add_argument("--memory-file", type=Path)
  value.add_argument("--feedback-required", action="store_true")
  value.add_argument("--run-id")
  value.add_argument("--idempotency-key")
  value.add_argument("--timeout-seconds", type=int, default=1800)
  value.add_argument("--allow-workspace-write", action="store_true")
  value.add_argument("--worktree-root", type=Path)
  value.add_argument("--after")
  value.add_argument("--offset", type=int, default=0)
  value.add_argument("--limit", type=int, default=2048)
  value.add_argument("--wait-seconds", type=float, default=30)
  display = value.add_mutually_exclusive_group()
  display.add_argument("--detach", action="store_true")
  display.add_argument("--observe", action="store_true")
  return value


def main(argv=None):
  arguments = list(sys.argv[1:] if argv is None else argv)
  args = parser().parse_args(arguments)
  supplied = {value.split("=", 1)[0] for value in arguments if value.startswith("--")}
  execution = {"--backend", "--mode", "--preset", "--provider", "--model", "--cwd", "--prompt-file", "--context-artifact", "--context-file",
    "--memory-file", "--feedback-required", "--idempotency-key", "--timeout-seconds", "--allow-workspace-write", "--worktree-root", "--detach", "--observe"}
  allowed = {"start": execution, "resume": execution | {"--run-id"}, "probe": {"--backend"}, "status": {"--run-id"}, "cancel": {"--run-id"},
    "poll": {"--run-id", "--after", "--wait-seconds"}, "wait": {"--run-id", "--wait-seconds"}, "result": {"--run-id", "--offset", "--limit"}}
  if supplied - allowed[args.action] - {"--instance"}:
    raise ConfigError("delegate-action-option")
  if args.timeout_seconds <= 0 or args.offset < 0 or not 1 <= args.limit <= 2048:
    raise ConfigError("delegate-argument-range")
  instance, bound = instance_binding(args.instance)
  if not 0 <= args.wait_seconds <= 60:
    raise ConfigError("delegate-wait-seconds")
  if args.action in {"start", "resume", "probe"}:
    from .workspace import load_workspace
    with Tree(Path(bound["state_root"])) as tree:
      current = read_state(tree)["current"]
    if not current or current["binding"] != bound["binding"]:
      raise Conflict("DELEGATE_DEPLOYMENT_MISMATCH")
    locations = {item["name"]: item["literal"] for item in current["launch"]["environment"] if "literal" in item}
    workspace = load_workspace(Path(bound["binding"]["local"]), bound["binding"]["profile"], repository=Path(locations["AGENTCFG_REPOSITORY"]))
    if workspace.agent != "pi" or workspace.instance != instance:
      raise ConfigError("delegate-instance-agent")
    with Tree(instance) as tree:
      deployed_options = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])["options"].get("model_delegate", {})
    if args.action in {"start", "resume"} and "--timeout-seconds" not in supplied:
      args.timeout_seconds = deployed_options.get("max_run_seconds", 1800)
    if args.action == "probe":
      # probe 只看已部署声明/完整收据；版本/登录不冒充模型调用证据。
      identity = current["launch"].get("runtime_identity", current["launch"]["lock_identity"])
      if workspace.backend.status(workspace, identity) != "installed":
        raise DependencyError("委托运行包未就绪")
      with Tree(instance) as tree:
        options = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])["options"].get("model_delegate", {})
      backends = options.get("backends", [])
      if not options.get("enabled") or args.backend is not None and args.backend not in backends:
        raise ConfigError("delegate-backend-unbound")
      with Tree(workspace.backend.root(workspace, identity)) as tree:
        commands = json.loads(tree.read("runtime/commands.json")[0])["programs"]
        capabilities = []
        for backend in ([args.backend] if args.backend else backends):
          command = commands.get("delegate-" + backend)
          if not command or tree.read(command["entrypoint"]) is None or backend == "codex" and (
              not command.get("backend_entrypoint") or tree.read(command["backend_entrypoint"]) is None):
            raise DependencyError("所选委托后端入口缺失")
          capabilities.append({"backend": backend, "configured": True, "dependencies": "installed", "native_load": "not-run",
            "authentication": "unknown", "execution": "not-run", "supports_write": backend == "codex" and options["codex"]["mode"] == "explicit-write"})
      result = {"schema_version": 2, "state": "completed", "verification": "unverified", "capabilities": capabilities}
    else:
      if args.action == "resume":
        if not args.run_id:
          raise ConfigError("delegate-resume-id-required")
        old = DelegationRuns(instance / "pi-home/model-delegate/runs").read(args.run_id)["request"]
        proof = saved_termination(bound["state_root"], old)
        if not proof["termination_verified"] or not proof["resources_reclaimed"]:
          raise Conflict("DELEGATE_TERMINATION_UNKNOWN")
        values = {"backend": old["backend"], "mode": old["mode"], "provider": old["requested_model"]["provider_id"],
          "model": old["requested_model"]["model_id"], "cwd": Path(old["cwd"])}
        for key, value in values.items():
          if getattr(args, key) is not None and getattr(args, key) != value:
            raise ConfigError("delegate-resume-identity")
          setattr(args, key, value)
        if "--preset" in supplied and args.preset != old["preset"]:
          raise ConfigError("delegate-resume-identity")
        args.preset = old["preset"]
      if not all((args.backend, args.mode, args.model, args.provider, args.cwd, args.prompt_file)):
        raise ConfigError("delegate-explicit-request-required")
      with Tree(args.prompt_file.absolute().parent, private=False) as tree:
        prompt = tree.read(args.prompt_file.name, max_bytes=65536)
      if prompt is None:
        raise ConfigError("delegate-prompt-missing")
      request = {"idempotency_key": args.idempotency_key or "cli-" + uuid.uuid4().hex, "backend": args.backend, "mode": args.mode,
        "preset": args.preset, "task": prompt[0].decode("utf8"), "cwd": str(args.cwd.resolve(strict=True)),
        "model": {"provider_id": args.provider, "model_id": args.model}, "timeout_seconds": args.timeout_seconds,
        "feedback_required": args.feedback_required, "allow_workspace_write": args.allow_workspace_write,
        "worktree_root": str(args.worktree_root.resolve(strict=True)) if args.worktree_root else None}
      if args.context_file or args.memory_file:
        from .model_delegate_context import import_context, memory_context
        from .pi_worker_files import snapshot
        source = (args.context_file or args.memory_file).absolute()
        with Tree(source.parent, private=False) as tree:
          document = json.loads(tree.read(source.name, max_bytes=4 * 1024 * 1024)[0])
        if args.memory_file:
          with Tree(instance) as tree:
            manifest = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])
          document = memory_context(document, task=request["task"], cwd=request["cwd"], candidate_digest=snapshot(request["cwd"],
            protected_roots=[workspace.local_path, instance, workspace.state_root]), limit=manifest["options"]["model_delegate"]["context_budget_tokens"])
        args.context_artifact = import_context(instance / "pi-home/model-delegate", document)
      if args.context_artifact: request["context_artifact"] = args.context_artifact
      if args.action == "resume": request["continuation_of"] = args.run_id
      result = launch_single(workspace, request)
      deadline = time.monotonic() + (10 if args.detach else args.timeout_seconds + 10)
      after = None
      while result["state"] in {"starting", "running", "start_unknown"} and time.monotonic() < deadline:
        time.sleep(0.25)
        try:
          if args.observe:
            update = endpoint_call(instance, "delegate_poll", {"run_id": result["run_id"], "after": after})
            after = update["next_cursor"]
            if update["events"]:
              sys.stdout.buffer.write(control_envelope(update)); sys.stdout.buffer.flush()
          result = endpoint_call(instance, "delegate_status", {"run_id": result["run_id"]})
        except (Conflict, OSError): result = saved_status(instance, result["run_id"])
        if args.detach and result["state"] == "running": break
      if result["state"] == "completed": result = saved_status(instance, result["run_id"])
  else:
    if not args.run_id:
      raise ConfigError("delegate-run-id-required")
    if args.action == "result":
      from .model_delegate import artifact_chunk
      checked = saved_status(instance, args.run_id)
      if checked["verification"] != "verified-execution":
        raise Conflict("DELEGATE_RESULT_UNVERIFIED")
      runs = DelegationRuns(instance / "pi-home/model-delegate/runs")
      result = artifact_chunk(instance / "pi-home/model-delegate", runs.read(args.run_id)["receipt"], offset=args.offset, limit=args.limit)
    elif args.action == "cancel": result = endpoint_call(instance, "delegate_cancel", {"run_id": args.run_id})
    elif args.action == "poll":
      end = time.monotonic() + args.wait_seconds
      while True:
        try: result = endpoint_call(instance, "delegate_poll", {"run_id": args.run_id, "after": args.after})
        except (Conflict, OSError):
          saved_status(instance, args.run_id)
          result = DelegationRuns(instance / "pi-home/model-delegate/runs").poll(args.run_id, args.after)
        if result["events"] or result["state"] in {"completed", "failed", "canceled", "timeout"} or time.monotonic() >= end:
          break
        time.sleep(0.25)
    else:
      end = time.monotonic() + (args.wait_seconds if args.action == "wait" else 0)
      while True:
        try: result = endpoint_call(instance, "delegate_status", {"run_id": args.run_id})
        except (Conflict, OSError): result = saved_status(instance, args.run_id)
        terminal = result["state"] in {"completed", "failed", "canceled", "timeout"}
        if terminal or time.monotonic() >= end:
          if args.action == "wait": result["timed_out"] = not terminal
          break
        time.sleep(0.1)
  sys.stdout.buffer.write(control_envelope(result))
  if args.action in {"start", "resume"} and result.get("state") in {"failed", "canceled", "timeout"}:
    return 5
  return 4 if result.get("state") in {"unknown", "start_unknown", "starting"} else 0
