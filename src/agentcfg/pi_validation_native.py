"""显式原生场景调度；宿主外层监督负责超时撤销，模型只在隔离回环中运行。"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import subprocess
import time

from .activity import protected
from .deployment import json_bytes
from .pi_cold_rebuild import copy_source
from .pi_dependencies import PiBackend
from .pi_control import request
from .pi_lifecycle import assert_inactive
from .pi_output import OutputCapture
from .pi_validation_runtime import inspect_runtime
from .pi_validation_sandbox import sandbox_argv
from .process import DependencyError, checked
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private

ROOT = Path(__file__).resolve().parents[2]
TASKKEEPER = tuple("taskkeeper-" + name for name in ("inspect", "fix", "second-view", "budget", "quota", "missing-result", "pause-resume", "stop", "schedule", "proxy-fix", "proxy-second-view"))
IMPLEMENTED = frozenset(("delegate-proxy-control", "mcp-service", "web-service", "terminal-service", "codex-native-readonly", "codex-native-write", "codex-native-control", "host-resources", "migration-runtime-conflicts", "permission-denials", "ordinary-cancel", "parent-loss", "recovery-grants", "cold-rebuild", "delegate-presets", "delegate-batch", "delegate-control", "readseek-tools", *TASKKEEPER))
LINUX_ONLY_RUNNERS = {"recovery-grants": "recovery-runner-requires-linux", "parent-loss": "parent-loss-runner-requires-linux"}
STANDALONE_SCENARIOS = frozenset(("delegate-control", "delegate-proxy-control"))
MOUNT_SCENARIOS = frozenset(("migration-runtime-conflicts", "codex-native-readonly", "codex-native-write", "codex-native-control"))
HELPER_GATED_REASONS = {**{name: "standalone-control-runner-requires-macos-sealed-helper" for name in STANDALONE_SCENARIOS},
  **{name: "migration-runtime-mount-requires-macos-sealed-helper" for name in MOUNT_SCENARIOS},
  "recovery-grants": "recovery-runner-requires-macos-sealed-helper", "parent-loss": "parent-loss-runner-requires-macos-sealed-helper"}


def macos_helper_sealed(runtime):
  """darwin监督helper已进入密封运行包时，平台专用场景才有真实执行入口。"""
  with Tree(runtime.root) as tree: raw = tree.read(".agentcfg-receipt.json", max_bytes=64 * 1024 * 1024)
  try: return raw is not None and "bin/pi-supervisor-macos" in json.loads(raw[0])["files"]
  except (ValueError, TypeError, KeyError): return False


def platform_limitation(scenario, runtime):
  """按平台能力推导not-run原因；darwin经密封helper放行（执行器已实现、待实机验证），不对裸PID发信号。"""
  platform = getattr(runtime, "platform", "linux-x86_64")
  if platform.startswith("linux-"): return None
  if platform.startswith("darwin-"):
    if scenario not in HELPER_GATED_REASONS: return None
    return None if macos_helper_sealed(runtime) else HELPER_GATED_REASONS[scenario]
  return LINUX_ONLY_RUNNERS.get(scenario, "scenario-not-implemented")


def scenarios(case, profile):
  managed = profile == "pi-managed"
  mapping = {"host-resources": ("host-resources",), "taskkeeper-lifecycle": TASKKEEPER if managed else ("taskkeeper-profile-required",),
    "budget-permissions": ("permission-denials", *(("taskkeeper-budget",) if managed else ())),
    "termination-recovery": ("parent-loss", "recovery-grants", *(("taskkeeper-stop",) if managed else ("ordinary-cancel",))),
    "codex-receipts": ("codex-native-readonly", "codex-native-write", "codex-native-control") if profile == "pi-codex" else ("codex-profile-required",),
    "model-delegate-replacement": ("delegate-presets", "delegate-control", "delegate-batch", *(("delegate-proxy-control",) if profile == "pi-default" else ())) if not managed else ("delegate-profile-required",),
    "optional-services": ("mcp-service", "web-service", "terminal-service") if profile == "pi-default" else ("service-profile-required",),
    "migration-conflicts": ("migration-runtime-conflicts",), "dsh-compatibility": ("mock-tier-required",),
    "readseek-tools": ("readseek-tools",) if profile in ("pi-default", "pi-codex", "pi-cursor") else ("readseek-profile-required",), "cold-rebuild": ("cold-rebuild",)}
  if case == "all":
    return ("host-resources", "migration-runtime-conflicts", *(TASKKEEPER if managed else mapping["model-delegate-replacement"]), "permission-denials",
      *mapping["termination-recovery"][:2], *(("ordinary-cancel",) if not managed else ()), "cold-rebuild",
      *(("readseek-tools",) if profile in ("pi-default", "pi-codex", "pi-cursor") else ()),
      *(mapping["optional-services"] if profile == "pi-default" else ()),
      *(mapping["codex-receipts"] if profile == "pi-codex" else ()))
  if case not in mapping: raise ConfigError("pi-native-case")
  return mapping[case]


def program_bindings(runtime):
  import pytest
  values = {name: shutil.which(name) for name in (runtime.engine, "git", "node")}
  if not all(values[name] for name in (runtime.engine, "git")): raise DependencyError("原生验收缺少明确解释器或Git前提")
  # ReadSeek worker 需要锁定 Node 版本，即使宿主是 Bun 也需要独立的 Node 绑定
  result = {"engine": str(Path(values[runtime.engine]).resolve(strict=True)), "git": str(Path(values["git"]).resolve(strict=True)),
    "python": str(Path(sys.executable).resolve(strict=True)), "python_runtime": str(Path(sys.base_prefix).resolve(strict=True)),
    "python_packages": str(Path(pytest.__file__).resolve().parents[1])}
  if values.get("node"):
    result["node"] = str(Path(values["node"]).resolve(strict=True))
  return result


def cancel_fixture(state, *, send=request):
  """只向本次临时实例的已认证控制通道请求停止，不操作外部 PID。"""
  endpoint = state / "activity/control/control.json"
  with Tree(endpoint.parent) as tree: raw = tree.read(endpoint.name)
  if raw is None: return False
  capability = json.loads(raw[0])["user_capability"]
  leases = state / "activity/leases"
  with Tree(leases) as tree:
    records = [json.loads(tree.read(name)[0]) for name in sorted(os.listdir(tree.fd)) if name.endswith(".json")]
  accepted = True
  # 先撤销子任务，再停止宿主；保留所有未知记录供恢复核验。
  for lease in sorted(records, key=lambda row: row["kind"] == "host"):
    if not protected(lease): continue
    allocating = lease["state"] == "allocating" and not lease["spawn_committed"]
    reply = send(endpoint, capability, {"schema_version": 1, "request_id": secrets.token_hex(16),
      "method": "abort_allocation" if allocating else "cancel",
      "args": {"lease_id": lease["lease_id"], **({} if allocating else {"force": True})}})
    accepted &= reply.get("ok") is True
  return accepted


def supervise(runtime, directory, argv, environment, *, popen=subprocess.Popen, cancel=cancel_fixture, timeout=900):
  """外层仅持有沙箱进程句柄；真实应用执行归内层唯一监督者管理。"""
  state = directory / "fixture/state_root/pi" / runtime.profile
  capture = OutputCapture(directory / "controller-output")
  process = popen(list(argv), cwd=directory, env=dict(environment), stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
  capture.attach(process)
  outcome = {}
  try:
    outcome["exit_code"] = process.wait(timeout=timeout)
  except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
    outcome["timed_out" if isinstance(error, subprocess.TimeoutExpired) else "interrupted"] = True
    try: outcome["cancel_accepted"] = cancel(state)
    except Exception: outcome["cancel_accepted"] = False
    try: outcome["exit_code"] = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
      process.terminate()
      try: outcome["exit_code"] = process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        process.kill()
        try: outcome["exit_code"] = process.wait(timeout=5)
        except subprocess.TimeoutExpired: outcome["stop_unverified"] = True
  deadline = time.monotonic() + 5
  for thread in capture.threads: thread.join(max(0, deadline - time.monotonic()))
  ended = process.poll() is not None and capture.complete() and len(capture.results) == 2 and not any(row["failed"] for row in capture.results.values())
  try: assert_inactive(state)
  except Exception: ended = False
  return {**outcome, "termination_confirmed": ended}


def verified_result(value, *, nonce, scenario, runtime):
  if scenario not in IMPLEMENTED or scenario == "cold-rebuild": return False
  required = {"schema_version", "nonce", "scenario", "runtime_identity", "status", "host_exit_code", "termination_confirmed",
    "executions", "worker_executions", "provider", "facts"}
  if (not isinstance(value, dict) or set(value) != required or type(value["schema_version"]) is not int or value["schema_version"] != 1
      or value["nonce"] != nonce or value["scenario"] != scenario or value["runtime_identity"] != runtime.identity
      or value["status"] != "passed" or type(value["host_exit_code"]) is not int or value["host_exit_code"] != (137 if scenario == "parent-loss" else 0) or value["termination_confirmed"] is not True
      or type(value["executions"]) is not int or value["executions"] < 1 or type(value["worker_executions"]) is not int
      or not 0 <= value["worker_executions"] <= value["executions"]
      or not isinstance(value["facts"], dict) or not isinstance(value["provider"], dict)):
    return False
  facts = value["facts"]
  if type(value["provider"].get("requests")) is not int or value["provider"]["requests"] < 0: return False
  if scenario in ("mcp-service", "web-service", "terminal-service"):
    from .pi_validation_live_services import service_facts_valid
    capability = scenario.removesuffix("-service")
    narrowed = {key: item for key, item in facts.items() if key not in ("real_account_used", "service_request_observed", "source_preserved")}
    return (facts.get("real_account_used") is False and facts.get("service_request_observed") is True and facts.get("source_preserved") is True
      and service_facts_valid(narrowed, capability, 1))
  if scenario.startswith("codex-native-") and getattr(runtime, "platform", "linux-x86_64").startswith("linux-") and facts.get("kernel_namespace_verified") is not True: return False
  if scenario in ("codex-native-readonly", "codex-native-write"):
    return (facts.get("sdk_session") is False and facts.get("real_account_used") is False and value["provider"]["requests"] >= 3
      and (scenario == "codex-native-write" or facts.get("readonly_write_denied") is True)
      and facts.get("write_mode") is (scenario == "codex-native-write") and all(facts.get(key) is True for key in
        ("official_codex_cli", "verified_execution", "native_tools_observed", "privacy_denial_verified", "candidate_result_verified", "source_preserved", "activity_drained")))
  if scenario == "recovery-grants":
    return (facts.get("sdk_session") is False and facts.get("real_account_used") is False and value["provider"].get("requests") == 0
      and all(facts.get(key) is True for key in ("first_party_processes", "live_owner_rejected", "old_owner_dead", "wrong_plan_rejected", "stop_only_recovery", "target_terminated", "source_preserved")))
  if scenario.startswith("taskkeeper-proxy-") and (facts.get("transport") != "proxy" or facts.get("proxy_authentication_verified") is not True
      or value["provider"].get("proxy_requests") != value["provider"].get("requests") or not value["provider"].get("requests")): return False
  if scenario in ("delegate-control", "codex-native-control", "delegate-proxy-control"):
    codex = scenario == "codex-native-control"
    if scenario == "delegate-proxy-control" and (facts.get("transport") != "proxy" or facts.get("proxy_authentication_verified") is not True
        or value["provider"].get("proxy_requests") != value["provider"]["requests"]): return False
    return (facts.get("real_account_used") is False and facts.get("standalone_delegate_sdk") is (not codex)
      and (not codex or facts.get("official_codex_cli") is True and facts.get("sdk_session") is False)
      and facts.get("user_cli_operations") == ["cancel", "poll", "probe", "result", "resume", "start", "status", "wait"]
      and all(facts.get(key) is True for key in ("fresh_resume_verified", "cancel_after_request_verified", "source_preserved", "probe_metadata_only", "activity_drained"))
      and type(facts.get("verified_results")) is int and facts["verified_results"] == 2 and value["provider"]["requests"] >= 3 and value["executions"] >= 3)
  if facts.get("sdk_session") is not True or type(facts.get("manager_limit")) is not int or facts.get("manager_limit") != 2 or facts.get("real_account_used") is not False: return False
  if scenario == "host-resources":
    return all(facts.get(key) is True for key in ("model_roundtrip", "guarded_read", "source_preserved")) and value["provider"].get("requests", 0) >= 2
  if scenario == "readseek-tools":
    # ReadSeek九工具真实流程：检索/搜索/定义/引用/视图/读取/写入/编辑/符号重命名经监督控制器完成，越界写入被拒，源项目无残留。
    return (all(facts.get(key) is True for key in ("grep_verified", "search_verified", "def_verified", "refs_verified", "view_verified",
      "read_verified", "write_verified", "edit_verified", "rename_verified", "denied_write_rejected", "source_preserved", "activity_drained"))
      and value["provider"].get("requests", 0) >= 10)
  if scenario == "migration-runtime-conflicts":
    return value["provider"]["requests"] >= 2 and all(facts.get(key) is True for key in ("model_roundtrip", "guarded_read", "source_preserved",
      "active_mutations_rejected", "unowned_file_preserved", "old_home_preserved", "legacy_marker_detected", "apply_idempotent", "credentials_not_imported"))
  if scenario == "permission-denials":
    return all(facts.get(key) is True for key in ("model_roundtrip", "guarded_denial", "no_file_admission", "source_preserved")) and value["provider"].get("requests", 0) >= 2
  if facts.get("activity_drained") is not True: return False
  if scenario == "ordinary-cancel":
    return value["provider"]["requests"] > 0 and all(facts.get(key) is True for key in
      ("ordinary_session_started", "cancel_after_request_verified", "sdk_stream_settled", "manager_stopped", "source_preserved"))
  if scenario == "delegate-presets":
    return (facts.get("presets_verified") == ["general", "context", "challenge", "plan", "research", "review", "scout"]
      and type(facts.get("delegate_runs")) is int and facts["delegate_runs"] == 7 and facts.get("verified_execution_only") is True
      and facts.get("source_preserved") is True and value["executions"] >= 8 and value["provider"]["requests"] >= 14
      and value["provider"].get("delivered_presets") == sorted(facts["presets_verified"]))
  if scenario == "delegate-batch":
    return (type(facts.get("batch_results")) is int and facts["batch_results"] == 3 and facts.get("batch_idempotency_verified") is True
      and facts.get("user_cli_verified") is True and facts.get("source_preserved") is True
      and type(facts.get("peak_manager_running")) is int and 0 < facts["peak_manager_running"] <= 2
      and type(value["provider"].get("max_inflight")) is int and value["provider"]["max_inflight"] == 2 and value["provider"]["requests"] >= 6 and value["executions"] >= 4)
  if scenario == "parent-loss":
    child = facts.get("child_execution_kind", "worker")
    return (child in ("worker", "external") and value["executions"] >= 2 and (child == "external" or value["worker_executions"] >= 1)
      and all(facts.get(key) is True for key in ("parent_exit_observed", "worker_revocation_observed", "source_preserved")) and value["provider"]["requests"] > 0)
  if scenario != "taskkeeper-budget" and value["worker_executions"] < 1: return False
  if scenario == "taskkeeper-stop": return facts.get("stop_requested") is True and facts.get("worker_started_before_control") is True
  if scenario == "taskkeeper-quota": return facts.get("quota_wait_observed") is True
  if scenario == "taskkeeper-budget": return facts.get("job_status") == "BLOCKED" and facts.get("budget_denial_observed") is True and 0 < value["provider"]["requests"] <= 2
  if scenario == "taskkeeper-missing-result": return facts.get("job_status") == "BLOCKED" and facts.get("missing_final_rejected") is True and value["provider"]["requests"] > 0
  if scenario in ("taskkeeper-fix", "taskkeeper-proxy-fix") and (type(facts.get("checks")) is not int or facts["checks"] < 1): return False
  if scenario in ("taskkeeper-second-view", "taskkeeper-proxy-second-view") and facts.get("second_view_verified") is not True: return False
  if scenario == "taskkeeper-pause-resume" and (facts.get("resumed") is not True or facts.get("worker_started_before_control") is not True): return False
  if scenario == "taskkeeper-schedule" and facts.get("scheduled_timestamp_verified") is not True: return False
  return facts.get("job_status") == "COMPLETED" and facts.get("receipt_observed") is True and facts.get("source_preserved") is True


def execute(args):
  if getattr(args, "allow_host", False) is not True or getattr(args, "allow_live", False): raise ConfigError("pi-native-authorization")
  runtime = inspect_runtime(args.runtime)
  selected = scenarios(args.case, runtime.profile)
  base = {"schema_version": 1, "tier": "native", "case": args.case, "runtime": runtime.public_identity(),
    "command": [sys.executable, *sys.argv]}
  with Tree(runtime.root) as tree:
    ready = tree.read("runtime/native-validation.mjs") is not None and tree.read("supervisor/scripts/pi-native-scenario.py") is not None
  if not ready: return {**base, "status": "not-run", "reason": "native-scenario-entrypoint-missing", "results": []}
  lock = PiBackend().read_lock(ROOT)
  if lock.identity != runtime.lock_identity or lock.metadata["profile_slices"].get(runtime.profile, {}).get("identity") != runtime.slice_identity:
    raise Conflict("PI_NATIVE_SOURCE_RUNTIME_MISMATCH")
  programs = program_bindings(runtime)
  started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
  root = Path(tempfile.mkdtemp(prefix="agentcfg-native-")).resolve(strict=True)
  source_digest = copy_source(ROOT, root / "source")
  home = root / "home"; ensure_private(home)
  # 系统 bin 目录只读绑定在沙箱内已存在；PATH 补上它们才能命中 rg 等只读前提。
  environment = {"HOME": str(home), "PATH": os.pathsep.join(dict.fromkeys(str(Path(programs[name]).parent) for name in ("engine", "git", "python"))) + os.pathsep + "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "AGENTCFG_NATIVE_VALIDATION": "1"}
  actual = checked([programs["engine"], "--version"], cwd=root, env=environment)
  if actual != runtime.toolchains[runtime.engine]: raise DependencyError("原生验收解释器不匹配运行包")
  results = []
  unsafe_to_continue = False
  continuation_reason = "previous-scenario-termination-unverified"
  for scenario in selected:
    if unsafe_to_continue:
      results.append({"scenario_id": scenario, "status": "not-run", "reason": continuation_reason})
      continue
    if scenario == "cold-rebuild":
      from .pi_cold_rebuild import cold_rebuild
      destination = root / "cold-rebuild"
      rebuilt = cold_rebuild(ROOT, runtime.profile, destination, allow_host=True)
      results.append({"scenario_id": scenario, "status": rebuilt["status"], "targets": rebuilt["targets"], "artifact_directory": str(destination)})
      continue
    limitation = platform_limitation(scenario, runtime)
    if limitation is not None:
      results.append({"scenario_id": scenario, "status": "not-run", "reason": limitation}); continue
    if scenario not in IMPLEMENTED:
      results.append({"scenario_id": scenario, "status": "not-run", "reason": "scenario-not-implemented"}); continue
    directory = root / "cases" / scenario; ensure_private(directory)
    nonce = secrets.token_hex(32); port = 20000 + secrets.randbelow(40000)
    document = {"schema_version": 1, "nonce": nonce, "scenario": scenario, "runtime_root": str(runtime.root), "source_root": str(root / "source"),
      "fixture_root": str(directory / "fixture"), "programs": programs, "provider_port": port}
    path = directory / "input.json"
    with Tree(directory) as tree: tree.write_new(path.name, json_bytes(document))
    argv = sandbox_argv(runtime, root, path, programs, port, local_runtime=scenario in ("delegate-control", "delegate-proxy-control", "migration-runtime-conflicts", "codex-native-readonly", "codex-native-write", "codex-native-control"))
    execution = supervise(runtime, directory, argv, environment)
    with Tree(directory) as tree: raw = tree.read("controller-result.json", max_bytes=1024 * 1024)
    try: value = json.loads(raw[0]) if raw else None
    except (ValueError, UnicodeError): value = None
    valid = verified_result(value, nonce=nonce, scenario=scenario, runtime=runtime)
    passed = execution.get("exit_code") == 0 and execution.get("termination_confirmed") is True and not execution.get("timed_out") and not execution.get("interrupted") and valid
    results.append({"scenario_id": scenario, "status": "passed" if passed else "failed", "execution": execution,
      "facts": value.get("facts") if valid else None, "artifact_directory": str(directory)})
    if execution.get("termination_confirmed") is not True: unsafe_to_continue = True
    if execution.get("interrupted"):
      unsafe_to_continue = True; continuation_reason = "previous-scenario-interrupted"
  state = "failed" if any(row["status"] == "failed" for row in results) else "not-run" if any(row["status"] == "not-run" for row in results) else "passed"
  return {**base, "status": state, "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "source_digest": source_digest, "work_root": str(root), "results": results, "limitations": ["synthetic-loopback-models; no real accounts"]}
