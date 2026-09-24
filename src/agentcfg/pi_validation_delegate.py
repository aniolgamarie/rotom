"""在真实部署的私人实例上验收用户委托 CLI；不把 probe 当执行证明。"""
import json
from pathlib import Path
import subprocess
import sys
import time

from .activity import protected
from .deployment import json_bytes
from .model_delegate import DelegationRuns
from .model_delegate_cli import endpoint_call
from .pi_lifecycle import assert_inactive, guard
from .storage import Conflict, Tree, ensure_private, instance_lock


def run_delegate_control(fixture, runtime, document, path, provider):
  workspace = fixture["workspace"]
  codex = document["scenario"] == "codex-native-control"
  proxy = document["scenario"] == "delegate-proxy-control"
  backend = "codex" if codex else "pi"
  if codex:
    with Tree(workspace.instance) as tree:
      tree.write_new("codex-home/auth.json", json_bytes({"auth_mode": "apikey", "OPENAI_API_KEY": "synthetic-native-key"}))
  output = path.parent / "delegate-cli"; ensure_private(output)
  with Tree(path.parent) as tree: tree.write_new("delegate-task.txt", b"Read code.txt and report its content. Do not modify files.\n")
  prompt = str(path.parent / "delegate-task.txt")
  calls, runs, finished = [], [], False
  def invoke(action, *args):
    number = str(len(calls)); calls.append(action)
    command = [sys.executable, "-B", "-I", str(runtime.root / "supervisor/scripts/model-delegate.py"), action,
      "--instance", str(workspace.instance), *args]
    result = subprocess.run(command, cwd=fixture["project"], env=fixture["environment"], capture_output=True, timeout=180)
    with Tree(output) as tree:
      tree.write_new(number + ".stdout", result.stdout); tree.write_new(number + ".stderr", result.stderr)
    if result.returncode != 0: raise Conflict("PI_NATIVE_DELEGATE_CLI_FAILED")
    value = json.loads(result.stdout)
    if not isinstance(value, dict): raise Conflict("PI_NATIVE_DELEGATE_CLI_RESPONSE")
    return value
  def wait_ended(run_id, wanted):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
      result = invoke("wait", "--run-id", run_id, "--wait-seconds", "1")
      if result["state"] in ("completed", "failed", "canceled", "timeout"):
        if result["state"] != wanted: raise Conflict("PI_NATIVE_DELEGATE_TERMINAL")
        return result
    raise Conflict("PI_NATIVE_DELEGATE_TIMEOUT")
  def wait_inactive():
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
      try:
        with guard(workspace, create=False), Tree(workspace.state_root) as tree, instance_lock(tree):
          assert_inactive(workspace.state_root)
        return
      except Conflict: time.sleep(0.1)
    raise Conflict("PI_NATIVE_DELEGATE_ACTIVITY")
  try:
    probe = invoke("probe", "--backend", backend)
    if any(row["execution"] != "not-run" for row in probe.get("capabilities", [])) or not probe.get("capabilities"):
      raise Conflict("PI_NATIVE_PROBE_IS_NOT_EXECUTION")
    start = ("--backend", backend, "--mode", "investigate", "--preset", "scout", "--provider", "openai" if codex else "agentcfg-native-fixture",
      "--model", "agentcfg-native-codex" if codex else "agentcfg-native-reader",
      "--cwd", str(fixture["project"]), "--prompt-file", prompt, "--timeout-seconds", "120", "--detach")
    first = invoke("start", *start); runs.append(first["run_id"])
    invoke("status", "--run-id", runs[-1])
    complete = wait_ended(runs[-1], "completed")
    if complete["verification"] != "verified-execution": raise Conflict("PI_NATIVE_DELEGATE_RECEIPT")
    events = invoke("poll", "--run-id", runs[-1], "--wait-seconds", "0")
    if not events.get("events"): raise Conflict("PI_NATIVE_DELEGATE_EVENTS")
    artifact = invoke("result", "--run-id", runs[-1])
    if not artifact.get("content", "").strip(): raise Conflict("PI_NATIVE_DELEGATE_ARTIFACT")
    wait_inactive()
    resumed = invoke("resume", "--run-id", runs[-1], "--prompt-file", prompt, "--timeout-seconds", "120", "--detach")
    if resumed["run_id"] in runs: raise Conflict("PI_NATIVE_DELEGATE_RESUME_IDENTITY")
    runs.append(resumed["run_id"])
    repeated = wait_ended(runs[-1], "completed")
    if repeated["verification"] != "verified-execution": raise Conflict("PI_NATIVE_DELEGATE_RECEIPT")
    if not invoke("result", "--run-id", runs[-1]).get("content", "").strip(): raise Conflict("PI_NATIVE_DELEGATE_ARTIFACT")
    wait_inactive()
    history = DelegationRuns(workspace.instance / "pi-home/model-delegate/runs")
    if history.read(runs[-1])["request"]["continuation_of"] != runs[0]: raise Conflict("PI_NATIVE_DELEGATE_CONTINUATION")
    before = provider.snapshot()["requests"]
    if codex: provider.delay = 12
    canceled = invoke("start", *start); runs.append(canceled["run_id"])
    deadline = time.monotonic() + 30
    while provider.snapshot()["requests"] <= before and time.monotonic() < deadline: time.sleep(0.05)
    if provider.snapshot()["requests"] <= before: raise Conflict("PI_NATIVE_DELEGATE_NOT_STARTED")
    stopped = invoke("cancel", "--run-id", runs[-1])
    if stopped.get("accepted") is not True: raise Conflict("PI_NATIVE_DELEGATE_CANCEL")
    wait_ended(runs[-1], "canceled"); wait_inactive()
    finished = True
  finally:
    if not finished:
      for run_id in runs:
        try: endpoint_call(workspace.instance, "delegate_cancel", {"run_id": run_id})
        except Exception: pass
  wait_inactive()
  with Tree(workspace.state_root / "activity/leases") as tree:
    import os
    records = [json.loads(tree.read(name)[0]) for name in os.listdir(tree.fd) if name.endswith(".json")]
  ended = bool(records) and not any(protected(row) for row in records)
  preserved = (fixture["project"] / "code.txt").read_text() == "original\n"
  facts = {"real_account_used": False, "standalone_delegate_sdk": not codex, "user_cli_operations": sorted(set(calls)),
    "transport": "proxy" if proxy else "direct",
    "fresh_resume_verified": True, "cancel_after_request_verified": True, "source_preserved": preserved,
    "probe_metadata_only": True, "verified_results": 2, "activity_drained": ended}
  if codex:
    facts.update(official_codex_cli=True, sdk_session=False)
    if runtime.platform.startswith("linux-"):
      from .pi_pid_namespace import namespace_lease_proof
      facts["kernel_namespace_verified"] = namespace_lease_proof(workspace.state_root, records)
      ended = ended and facts["kernel_namespace_verified"]
  if proxy:
    observed = provider.snapshot()
    if not observed["requests"] or observed["proxy_requests"] != observed["requests"]: raise Conflict("PI_NATIVE_PROXY_UNVERIFIED")
    facts["proxy_authentication_verified"] = True
  with Tree(path.parent) as tree: tree.write_new("controller-result.json", json_bytes({"schema_version": 1, "nonce": document["nonce"], "scenario": document["scenario"],
    "runtime_identity": runtime.identity, "status": "passed" if ended and preserved else "failed", "host_exit_code": 0,
    "termination_confirmed": ended, "executions": len(records), "worker_executions": 0, "provider": provider.snapshot(), "facts": facts}))
  return 0 if ended and preserved else 5
