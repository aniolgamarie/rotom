"""已准入实例的实网委托验收；只调用正式用户 CLI，正文留在实例私人结果中。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from .deployment import json_bytes
from .model_delegate import DelegationRuns, selected_route
from .model_delegate_cli import endpoint_call
from .pi_lifecycle import assert_inactive, guard
from .pi_worker_files import snapshot
from .storage import Conflict, Tree, ensure_private, instance_lock
from .schema import ConfigError


class LiveCLIError(Exception):
  def __init__(self, code):
    self.exit_code = code
    super().__init__("PI_LIVE_CLI_FAILED")


def selection(context):
  workspace = context["workspace"]
  with Tree(workspace.instance) as tree: manifest = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])
  options = manifest["options"].get("model_delegate", {})
  capability = context["item"]["capability_id"]
  if not options.get("enabled"): return None, "live-delegate-not-selected"
  modes = options.get("allowed_modes", [])
  readonly = next((mode for mode in ("investigate", "review") if mode in modes), None)
  presets = options.get("presets", [])
  if not readonly or not presets: return None, "live-readonly-delegate-binding-required"
  if capability == "codex":
    bound = options.get("codex", {})
    if bound.get("mode") != "explicit-write" or "implement" not in options.get("allowed_modes", []) or not bound.get("model"):
      return None, "live-codex-explicit-write-binding-required"
    if not shutil.which("git"): return None, "live-git-required"
    backend, model = "codex", {"provider_id": "openai", "model_id": bound["model"]}
  else:
    roles = options.get("pi", {}).get("model_roles", [])
    models = [manifest.get("model_bindings", {}).get(role) for role in roles]
    models = [value for value in models if value and (capability != "cursor" or value["provider"] == "cursor")]
    if not models: return None, "live-delegate-model-binding-required"
    backend, model = "pi", {"provider_id": models[0]["provider"], "model_id": models[0]["model"]}
  try: _, route = selected_route(manifest, backend, model)
  except ConfigError: return None, "live-delegate-route-binding-required"
  if route["mode"] not in context.get("native_transports", []): return None, "live-native-transport-not-covered"
  if route["mode"] == "proxy" and route.get("credential_ref") and context.get("native_proxy_authentication") is not True:
    return None, "live-native-proxy-authentication-not-covered"
  if capability == "proxy" and route["mode"] != "proxy": return None, "live-proxy-route-required"
  if capability == "cursor" and (route["mode"] != "direct" or context["runtime"].engine != "bun"):
    return None, "live-cursor-direct-bun-required"
  if model["model_id"].startswith("agentcfg-native-"): return None, "live-synthetic-model-rejected"
  return {"backend": backend, "model": model, "timeout": min(120, options["max_run_seconds"]), "mode": readonly,
    "preset": "general" if "general" in presets else presets[0]}, None


def execute_delegate(context, *, recheck, run=subprocess.run):
  selected, reason = selection(context)
  if reason: return {"scenario_id": context["item"]["scenario_id"], "status": "not-run", "reason": reason}
  workspace, runtime, project = context["workspace"], context["runtime"], context["project"]
  directory = workspace.state_root / "live-validation" / uuid.uuid4().hex
  ensure_private(directory)
  marker = "AGENTCFG_LIVE_" + uuid.uuid4().hex
  prompt = directory / "prompt.txt"
  with Tree(directory) as tree:
    tree.write_new(prompt.name, ("Return the exact marker " + marker + ". Do not use tools or inspect or modify files.\n").encode())
  env = {"HOME": str(workspace.instance / "user-home"), "PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
  calls, runs = [], []
  facts = {"service_response_verified": False, "fresh_resume_verified": False, "cancellation_verified": False,
    "write_verified": False, "source_preserved": False, "termination_confirmed": False}
  before = snapshot(project, protected_roots=[workspace.local_path, workspace.instance, workspace.state_root])

  def invoke(action, *extra):
    if action in ("start", "resume"):
      current = recheck()
      if current.get("reason") or current["identity"] != context["identity"] or current["scope_digest"] != context["scope_digest"]:
        raise Conflict("PI_LIVE_CONTEXT_CHANGED")
    result = run([sys.executable, "-B", "-I", str(runtime.root / "supervisor/scripts/model-delegate.py"), action,
      "--instance", str(workspace.instance), *extra], cwd=project, env=env, capture_output=True, timeout=240)
    calls.append(action)
    try: value = json.loads(result.stdout)
    except (ValueError, UnicodeError): raise Conflict("PI_LIVE_CLI_RESPONSE") from None
    if isinstance(value, dict) and action in ("start", "resume") and isinstance(value.get("run_id"), str) and value["run_id"] not in runs:
      runs.append(value["run_id"])
    # 不落盘 stdout/stderr；错误正文和模型文本不能进入通用验收报告。
    if result.returncode: raise LiveCLIError(result.returncode)
    if not isinstance(value, dict): raise Conflict("PI_LIVE_CLI_FAILED")
    return value

  def idle():
    deadline = time.monotonic() + 15
    while True:
      try:
        with guard(workspace, create=False), Tree(workspace.state_root) as tree, instance_lock(tree): assert_inactive(workspace.state_root)
        return
      except Conflict:
        if time.monotonic() >= deadline: raise
        time.sleep(0.1)

  def wait(run_id, terminal):
    deadline = time.monotonic() + selected["timeout"] + 30
    while time.monotonic() < deadline:
      value = invoke("wait", "--run-id", run_id, "--wait-seconds", "1")
      if value["state"] in ("completed", "failed", "canceled", "timeout"):
        if value["state"] != terminal or terminal == "completed" and value["verification"] != "verified-execution":
          raise Conflict("PI_LIVE_TERMINAL_UNVERIFIED")
        return value
    raise Conflict("PI_LIVE_TIMEOUT")

  def start(cwd, *, write=False, worktree=None):
    return invoke("start", "--backend", selected["backend"], "--provider", selected["model"]["provider_id"], "--model", selected["model"]["model_id"],
      "--mode", "implement" if write else selected["mode"], "--preset", selected["preset"], "--cwd", str(cwd), "--prompt-file", str(prompt),
      "--timeout-seconds", str(selected["timeout"]), "--detach", *(["--allow-workspace-write", "--worktree-root", str(worktree)] if write else []))

  failure = None
  not_run = False
  finished = False
  candidate = None
  try:
    probe = invoke("probe", "--backend", selected["backend"])
    if not probe.get("capabilities") or any(row.get("execution") != "not-run" for row in probe["capabilities"]): raise Conflict("PI_LIVE_PROBE_IS_NOT_EXECUTION")
    first = start(project)["run_id"]
    invoke("status", "--run-id", first)
    wait(first, "completed")
    if not invoke("poll", "--run-id", first, "--wait-seconds", "0").get("events"): raise Conflict("PI_LIVE_EVENTS_MISSING")
    if marker not in invoke("result", "--run-id", first).get("content", ""): raise Conflict("PI_LIVE_RESPONSE_UNVERIFIED")
    facts["service_response_verified"] = True; idle()
    resumed = invoke("resume", "--run-id", first, "--prompt-file", str(prompt), "--timeout-seconds", str(selected["timeout"]), "--detach")["run_id"]
    if resumed == first: raise Conflict("PI_LIVE_RESUME_IDENTITY")
    wait(resumed, "completed")
    if marker not in invoke("result", "--run-id", resumed).get("content", ""): raise Conflict("PI_LIVE_RESPONSE_UNVERIFIED")
    history = DelegationRuns(workspace.instance / "pi-home/model-delegate/runs")
    if history.read(resumed)["request"]["continuation_of"] != first: raise Conflict("PI_LIVE_RESUME_IDENTITY")
    facts["fresh_resume_verified"] = True; idle()
    canceled = start(project)["run_id"]
    if invoke("cancel", "--run-id", canceled).get("accepted") is not True: raise Conflict("PI_LIVE_CANCEL_UNVERIFIED")
    wait(canceled, "canceled"); idle(); facts["cancellation_verified"] = True
    if selected["backend"] == "codex":
      git = shutil.which("git")
      if not git: raise Conflict("PI_LIVE_GIT_REQUIRED")
      git_env = {**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
      git_args = [git, "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
      located = run([*git_args, "rev-parse", "--show-toplevel"], cwd=project, env=git_env, capture_output=True, timeout=30)
      if located.returncode: raise Conflict("PI_LIVE_GIT_ROOT")
      source = Path(located.stdout.decode().strip()).resolve(strict=True)
      base = Path(tempfile.mkdtemp(prefix="agentcfg-live-worktree-")); candidate = base / "candidate"
      # 不 checkout，避免触发仓库的 smudge/filter；只放本次合成探测文件，不提交或合并。
      created = run([*git_args, "worktree", "add", "--detach", "--no-checkout", str(candidate), "HEAD"], cwd=project, env=git_env, capture_output=True, timeout=60)
      if created.returncode: raise Conflict("PI_LIVE_WORKTREE_CREATE")
      cwd = candidate / project.relative_to(source); cwd.mkdir(parents=True, exist_ok=True, mode=0o700)
      filename = "agentcfg-live-probe.txt"
      with Tree(cwd, private=False) as tree: tree.write_new(filename, b"initial\n")
      candidate_before = snapshot(candidate, protected_roots=[cwd / filename])
      expected = marker + "_WRITTEN\n"
      with Tree(directory) as tree: tree.write_state(prompt.name, ("Change only " + filename + " to the exact text " + json.dumps(expected) + ". Do not modify other files or Git metadata. Report the marker " + marker + ".\n").encode())
      written = start(cwd, write=True, worktree=candidate)["run_id"]; wait(written, "completed")
      with Tree(cwd, private=False) as tree: raw = tree.read(filename, max_bytes=4096)
      if (raw is None or raw[0] != expected.encode() or raw[1] & 0o111
          or snapshot(candidate, protected_roots=[cwd / filename]) != candidate_before): raise Conflict("PI_LIVE_WRITE_UNVERIFIED")
      facts["write_verified"] = True; idle()
    finished = True
  except (Exception, KeyboardInterrupt) as error:
    not_run = isinstance(error, LiveCLIError) and error.exit_code in (2, 3, 5) and not runs
    failure = ("live-credentials-missing" if error.exit_code == 3 else "live-prerequisite-unavailable") if not_run else "live-delegation-not-verified"
  finally:
    if not finished:
      for run_id in runs:
        try: endpoint_call(workspace.instance, "delegate_cancel", {"run_id": run_id})
        except Exception: pass
      try: idle()
      except Exception: pass
  try: idle(); facts["termination_confirmed"] = True
  except Exception: failure = "live-termination-unverified"; not_run = False
  try: facts["source_preserved"] = before == snapshot(project, protected_roots=[workspace.local_path, workspace.instance, workspace.state_root])
  except Exception: facts["source_preserved"] = False
  if not facts["source_preserved"]: failure = "live-source-changed"; not_run = False
  facts["user_cli_operations"] = sorted(set(calls))
  value = {"scenario_id": context["item"]["scenario_id"], "status": "not-run" if not_run else "failed" if failure else "passed", "facts": facts, "run_ids": runs,
    "artifact_directory": str(directory), **({"reason": failure} if failure else {}), **({"candidate_directory": str(candidate)} if candidate else {})}
  with Tree(directory) as tree: tree.write_new("summary.json", json_bytes(value))
  return value
