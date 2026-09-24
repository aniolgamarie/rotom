"""从用户 CLI 到官方 Codex、原生工具与核验收据的隔离执行。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .activity import protected
from .deployment import json_bytes
from .model_delegate_cli import endpoint_call
from .pi_lifecycle import assert_inactive, guard
from .process import checked
from .storage import Conflict, Tree, instance_lock


def run_codex_case(fixture, runtime, document, path, provider):
  workspace = fixture["workspace"]
  write = document["scenario"] == "codex-native-write"
  project = fixture["project"]
  cwd = fixture["fixture_root"] / "candidate" if write else project
  if write:
    checked([document["programs"]["git"], "worktree", "add", "--detach", str(cwd), "HEAD"], cwd=project, env=fixture["environment"])
  with Tree(workspace.instance, create=True) as tree:
    tree.write_new("codex-home/auth.json", json_bytes({"auth_mode": "apikey", "OPENAI_API_KEY": "synthetic-native-key"}))
  prompt = path.parent / "codex-task.txt"
  with Tree(path.parent) as tree:
    tree.write_new(prompt.name, b"Read code.txt, attempt to change it to changed, and report the native tool result.\n")
  calls = []
  def invoke(action, *extra):
    index = len(calls); calls.append(action)
    result = subprocess.run([sys.executable, "-B", "-I", str(runtime.root / "supervisor/scripts/model-delegate.py"), action,
      "--instance", str(workspace.instance), *extra], cwd=project, env=fixture["environment"], capture_output=True, timeout=180)
    with Tree(path.parent) as tree:
      tree.write_new("codex-cli-" + str(index) + ".stdout", result.stdout)
      tree.write_new("codex-cli-" + str(index) + ".stderr", result.stderr)
    if result.returncode: raise Conflict("PI_NATIVE_CODEX_CLI_FAILED")
    return json.loads(result.stdout)
  run_id = None
  try:
    start = invoke("start", "--backend", "codex", "--mode", "implement" if write else "investigate", "--preset", "general",
      "--provider", "openai", "--model", "agentcfg-native-codex", "--cwd", str(cwd), "--prompt-file", str(prompt),
      "--timeout-seconds", "120", "--detach", *(["--allow-workspace-write", "--worktree-root", str(cwd)] if write else []))
    run_id = start["run_id"]
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
      status = invoke("wait", "--run-id", run_id, "--wait-seconds", "1")
      if status["state"] in ("completed", "failed", "canceled", "timeout"):
        if status["state"] != "completed" or status["verification"] != "verified-execution": raise Conflict("PI_NATIVE_CODEX_RECEIPT")
        break
    else: raise Conflict("PI_NATIVE_CODEX_TIMEOUT")
    result = invoke("result", "--run-id", run_id)
    if result.get("content", "").strip() != "Synthetic Codex native validation complete.": raise Conflict("PI_NATIVE_CODEX_RESULT")
    deadline = time.monotonic() + 15
    while True:
      try:
        with guard(workspace, create=False), Tree(workspace.state_root) as tree, instance_lock(tree): assert_inactive(workspace.state_root)
        break
      except Conflict:
        if time.monotonic() >= deadline: raise
        time.sleep(0.1)
  except Exception:
    if run_id:
      try: endpoint_call(workspace.instance, "delegate_cancel", {"run_id": run_id})
      except Exception: pass
    raise
  with Tree(workspace.state_root / "activity/leases") as tree:
    leases = [json.loads(tree.read(name)[0]) for name in os.listdir(tree.fd) if name.endswith(".json")]
  ended = bool(leases) and not any(protected(row) for row in leases)
  preserved = (project / "code.txt").read_text() == "original\n"
  expected = "changed\n" if write else "original\n"
  changed_correctly = (cwd / "code.txt").read_text() == expected
  observed = provider.snapshot()
  facts = {"sdk_session": False, "real_account_used": False, "official_codex_cli": True, "verified_execution": True,
    "transport": "direct",
    "native_tools_observed": observed["native_read_observed"] and observed["native_mutation_result_observed"],
    "privacy_denial_verified": observed["privacy_denial_observed"],
    "readonly_write_denied": not write and observed["native_write_denied"],
    "write_mode": write, "candidate_result_verified": changed_correctly, "source_preserved": preserved, "activity_drained": ended}
  if runtime.platform.startswith("linux-"):
    from .pi_pid_namespace import namespace_lease_proof
    facts["kernel_namespace_verified"] = namespace_lease_proof(workspace.state_root, leases)
    ended = ended and facts["kernel_namespace_verified"]
  passed = (ended and preserved and changed_correctly and facts["native_tools_observed"] and facts["privacy_denial_verified"]
    and (write or facts["readonly_write_denied"]))
  with Tree(path.parent) as tree:
    tree.write_new("controller-result.json", json_bytes({"schema_version": 1, "nonce": document["nonce"], "scenario": document["scenario"],
      "runtime_identity": runtime.identity, "status": "passed" if passed else "failed", "host_exit_code": 0,
      "termination_confirmed": ended, "executions": len(leases), "worker_executions": 0, "provider": observed, "facts": facts}))
  return 0 if passed else 5
