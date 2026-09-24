"""原生调度器使用替身控制者；空结果、错身份或未确认终止不能变成通过。"""
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import pytest
import io
import subprocess

from agentcfg.deployment import json_bytes
from agentcfg.pi_validation_runtime import ValidationRuntime
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
import agentcfg.pi_validation_native as native


def fixture(tmp_path, monkeypatch):
  root = tmp_path / ("a" * 64)
  with Tree(root, create=True) as tree:
    tree.write_new("runtime/native-validation.mjs", b"synthetic runner, never execute")
    tree.write_new("supervisor/scripts/pi-native-scenario.py", b"synthetic controller, never execute")
  runtime = ValidationRuntime(root, "pi-default", "node", "linux-x86_64", "a" * 64, "b" * 64, "c" * 64,
    "pi-default/node_modules/@earendil-works/pi-coding-agent/dist/index.js", {"node": "v24.14.0"})
  monkeypatch.setattr(native, "inspect_runtime", lambda _: runtime)
  monkeypatch.setattr(native.PiBackend, "read_lock", lambda *_: SimpleNamespace(identity="b" * 64, metadata={"profile_slices": {"pi-default": {"identity": "c" * 64}}}))
  monkeypatch.setattr(native, "program_bindings", lambda _: {"engine": "/fixtures/node", "git": "/fixtures/git", "python": "/fixtures/python"})
  def copy(_source, destination): destination.mkdir(mode=0o700); return "d" * 64
  monkeypatch.setattr(native, "copy_source", copy)
  monkeypatch.setattr(native, "checked", lambda *_args, **_kwargs: "v24.14.0")
  monkeypatch.setattr(native, "sandbox_argv", lambda *_args, **_kwargs: ("/fixtures/sandbox",))
  args = SimpleNamespace(allow_host=True, allow_live=False, runtime=root, case="host-resources")
  return runtime, args


@pytest.mark.parametrize("fault", [None, "nonce", "physical", "exit", "empty", "missing", "deadline", "version-only"])
def test_native_result_requires_matching_scenario_and_two_physical_termination_checks(tmp_path, monkeypatch, fault):
  runtime, args = fixture(tmp_path, monkeypatch)
  monkeypatch.setenv("OPENAI_API_KEY", "never-forward")
  def supervise(_runtime, directory, argv, environment):
    assert "OPENAI_API_KEY" not in environment and environment["HOME"] != str(Path.home())
    input = json.loads((directory / "input.json").read_text())
    facts = {"sdk_session": True, "manager_limit": 2, "real_account_used": False, "model_roundtrip": True, "guarded_read": True, "source_preserved": True}
    if fault == "version-only": facts.pop("guarded_read")
    result = {"schema_version": 1, "nonce": "wrong" if fault == "nonce" else input["nonce"], "scenario": input["scenario"], "runtime_identity": runtime.identity,
      "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 1, "worker_executions": 0,
      "provider": {"requests": 2}, "facts": None if fault == "empty" else facts}
    if fault != "missing":
      with Tree(directory) as tree: tree.write_new("controller-result.json", json_bytes(result))
    return {"exit_code": 5 if fault == "exit" else 0, "termination_confirmed": fault != "physical", "timed_out": fault == "deadline"}
  monkeypatch.setattr(native, "supervise", supervise)
  result = native.execute(args)
  assert result["status"] == ("passed" if fault is None else "failed")
  assert result["limitations"] == ["synthetic-loopback-models; no real accounts"]


def test_native_dispatch_authorization_and_missing_packaged_entry_do_not_start_a_process(tmp_path, monkeypatch):
  _, args = fixture(tmp_path, monkeypatch)
  monkeypatch.setattr(native, "supervise", lambda *_args: pytest.fail("must not run"))
  args.allow_host = False
  with pytest.raises(ConfigError): native.execute(args)
  args.allow_host = True
  (args.runtime / "runtime/native-validation.mjs").unlink()
  assert native.execute(args)["reason"] == "native-scenario-entrypoint-missing"


def test_all_does_not_drop_unimplemented_scenarios_or_borrow_taskkeeper_from_another_profile():
  default = native.scenarios("all", "pi-default")
  assert "delegate-presets" in default and "permission-denials" in default and "cold-rebuild" in default
  assert "migration-runtime-conflicts" in default and "ordinary-cancel" in default
  assert "taskkeeper-inspect" not in default
  assert set(native.TASKKEEPER) <= set(native.scenarios("all", "pi-managed"))


def test_unverified_termination_keeps_every_remaining_case_without_starting_it(tmp_path, monkeypatch):
  _, args = fixture(tmp_path, monkeypatch)
  args.case = "all"
  calls = []
  def unknown(_runtime, directory, *_args):
    calls.append(directory.name)
    return {"exit_code": 0, "termination_confirmed": False}
  monkeypatch.setattr(native, "supervise", unknown)
  result = native.execute(args)
  assert result["status"] == "failed" and calls == ["host-resources"]
  assert [row["scenario_id"] for row in result["results"]] == list(native.scenarios("all", "pi-default"))
  assert all(row["status"] == "not-run" and row["reason"] == "previous-scenario-termination-unverified" for row in result["results"][1:])


def test_unknown_scenario_cannot_reuse_generic_taskkeeper_success():
  runtime = SimpleNamespace(identity="a" * 64)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "invented", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 2, "worker_executions": 1,
    "provider": {"requests": 1}, "facts": {"sdk_session": True, "manager_limit": 2, "real_account_used": False,
      "activity_drained": True, "job_status": "COMPLETED", "receipt_observed": True, "source_preserved": True}}
  assert native.verified_result(value, nonce="fixture", scenario="invented", runtime=runtime) is False


@pytest.mark.parametrize("missing", [None, "ordinary_session_started", "cancel_after_request_verified", "sdk_stream_settled", "manager_stopped", "source_preserved"])
def test_ordinary_cancel_requires_running_sdk_request_and_async_settlement(missing):
  runtime = SimpleNamespace(identity="a" * 64)
  facts = {"sdk_session": True, "manager_limit": 2, "real_account_used": False, "activity_drained": True,
    **dict.fromkeys(("ordinary_session_started", "cancel_after_request_verified", "sdk_stream_settled", "manager_stopped", "source_preserved"), True)}
  if missing: facts.pop(missing)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "ordinary-cancel", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 1, "worker_executions": 0,
    "provider": {"requests": 1}, "facts": facts}
  assert native.verified_result(value, nonce="fixture", scenario="ordinary-cancel", runtime=runtime) is (missing is None)
  value["provider"]["requests"] = 0
  assert native.verified_result(value, nonce="fixture", scenario="ordinary-cancel", runtime=runtime) is False


@pytest.mark.parametrize("missing", [None, "active_mutations_rejected", "unowned_file_preserved", "old_home_preserved", "legacy_marker_detected", "apply_idempotent", "credentials_not_imported"])
def test_migration_requires_runtime_conflicts_and_preservation_proof(missing):
  runtime = SimpleNamespace(identity="a" * 64)
  facts = {"sdk_session": True, "manager_limit": 2, "real_account_used": False,
    **dict.fromkeys(("model_roundtrip", "guarded_read", "source_preserved", "active_mutations_rejected", "unowned_file_preserved", "old_home_preserved", "legacy_marker_detected", "apply_idempotent", "credentials_not_imported"), True)}
  if missing: facts.pop(missing)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "migration-runtime-conflicts", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 1, "worker_executions": 0,
    "provider": {"requests": 2}, "facts": facts}
  assert native.verified_result(value, nonce="fixture", scenario="migration-runtime-conflicts", runtime=runtime) is (missing is None)


@pytest.mark.parametrize("write", [False, True])
@pytest.mark.parametrize("missing", [None, "official_codex_cli", "verified_execution", "native_tools_observed", "privacy_denial_verified", "candidate_result_verified", "source_preserved", "activity_drained", "kernel_namespace_verified"])
def test_codex_native_requires_full_cli_tools_receipt_and_workspace_proof(write, missing):
  runtime = SimpleNamespace(identity="a" * 64)
  scenario = "codex-native-write" if write else "codex-native-readonly"
  facts = {"sdk_session": False, "real_account_used": False, "write_mode": write,
    "readonly_write_denied": not write,
    **dict.fromkeys(("official_codex_cli", "verified_execution", "native_tools_observed", "privacy_denial_verified", "candidate_result_verified", "source_preserved", "activity_drained", "kernel_namespace_verified"), True)}
  if missing: facts.pop(missing)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": scenario, "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 1, "worker_executions": 0,
    "provider": {"requests": 3}, "facts": facts}
  assert native.verified_result(value, nonce="fixture", scenario=scenario, runtime=runtime) is (missing is None)
  value["provider"]["requests"] = 0
  assert native.verified_result(value, nonce="fixture", scenario=scenario, runtime=runtime) is False


@pytest.mark.parametrize("timeout", [False, True, "interrupt"])
def test_controller_owns_only_its_sandbox_handle_and_never_inherits_parent_environment(tmp_path, monkeypatch, timeout):
  calls = []
  class Process:
    stdout = io.BytesIO(b"synthetic output")
    stderr = io.BytesIO(b"")
    attempts = 0
    def wait(self, **kwargs):
      self.attempts += 1
      if timeout == "interrupt" and self.attempts == 1: raise KeyboardInterrupt()
      if timeout is True and self.attempts == 1: raise subprocess.TimeoutExpired("fixture", 1)
      return 0
    def poll(self): return 0
  def popen(argv, **kwargs):
    assert kwargs["env"] == {"HOME": "/private/native-home"}
    assert kwargs["stdin"] == subprocess.DEVNULL
    calls.append("spawn"); return Process()
  def cancel(state): calls.append("cancel"); return True
  runtime = SimpleNamespace(profile="pi-managed")
  monkeypatch.setenv("OPENAI_API_KEY", "never-forward")
  result = native.supervise(runtime, tmp_path, ("/fixture/sandbox",), {"HOME": "/private/native-home"}, popen=popen, cancel=cancel, timeout=0.001)
  assert calls == (["spawn", "cancel"] if timeout else ["spawn"])
  assert result["termination_confirmed"] is True and bool(result.get("timed_out")) == (timeout is True)
  assert bool(result.get("interrupted")) == (timeout == "interrupt")


def test_controller_exit_cannot_clear_unknown_inner_activity(tmp_path, monkeypatch):
  from agentcfg.storage import Conflict
  class Process:
    stdout = io.BytesIO(b""); stderr = io.BytesIO(b"")
    def wait(self, **kwargs): return 0
    def poll(self): return 0
  def unknown(_state): raise Conflict("fixture unknown lease")
  monkeypatch.setattr(native, "assert_inactive", unknown)
  result = native.supervise(SimpleNamespace(profile="pi-managed"), tmp_path, ("/fixture/sandbox",), {}, popen=lambda *a, **k: Process())
  assert result["exit_code"] == 0 and result["termination_confirmed"] is False


def test_timeout_cancel_uses_only_fixture_user_capability_and_preserves_unknown_leases(tmp_path, monkeypatch):
  state = tmp_path / "state"
  rows = [
    {"lease_id": "host", "kind": "host", "state": "running", "spawn_committed": True},
    {"lease_id": "waiting", "kind": "worker", "state": "allocating", "spawn_committed": False},
    {"lease_id": "unknown", "kind": "worker", "state": "unknown", "spawn_committed": True},
  ]
  with Tree(state, create=True) as tree:
    tree.write_new("activity/control/control.json", json_bytes({"user_capability": "synthetic-user"}))
    for row in rows: tree.write_new("activity/leases/" + row["lease_id"] + ".json", json_bytes(row))
  monkeypatch.setattr(native, "protected", lambda row: True)
  calls = []
  def send(endpoint, capability, message):
    assert endpoint == state / "activity/control/control.json" and capability == "synthetic-user"
    calls.append(message)
    return {"ok": message["args"]["lease_id"] != "unknown"}
  assert native.cancel_fixture(state, send=send) is False
  assert calls[-1]["args"]["lease_id"] == "host"
  assert next(row for row in calls if row["args"]["lease_id"] == "waiting")["method"] == "abort_allocation"
  assert (state / "activity/leases/unknown.json").exists()


def test_unresponsive_sandbox_is_stopped_only_through_its_owned_child_handle(tmp_path):
  calls = []
  class Process:
    stdout = io.BytesIO(b""); stderr = io.BytesIO(b"")
    killed = False
    def wait(self, **kwargs):
      if not self.killed: raise subprocess.TimeoutExpired("fixture", 1)
      return -9
    def poll(self): return -9 if self.killed else None
    def terminate(self): calls.append("terminate")
    def kill(self): calls.append("kill"); self.killed = True
  result = native.supervise(SimpleNamespace(profile="pi-managed"), tmp_path, ("/fixture/sandbox",), {},
    popen=lambda *a, **k: Process(), cancel=lambda _: False, timeout=0.001)
  assert calls == ["terminate", "kill"]
  assert result["timed_out"] is True and result["cancel_accepted"] is False and result["exit_code"] == -9


@pytest.mark.parametrize("missing", [None, "guarded_denial", "no_file_admission", "source_preserved"])
def test_permission_failure_requires_actual_denial_and_no_file_admission(missing):
  runtime = SimpleNamespace(identity="a" * 64)
  facts = {"sdk_session": True, "manager_limit": 2, "real_account_used": False,
    "model_roundtrip": True, "guarded_denial": True, "no_file_admission": True, "source_preserved": True}
  if missing: facts.pop(missing)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "permission-denials", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 1, "worker_executions": 0,
    "provider": {"requests": 2}, "facts": facts}
  assert native.verified_result(value, nonce="fixture", scenario="permission-denials", runtime=runtime) is (missing is None)


@pytest.mark.parametrize("denial,requests,passed", [(True, 2, True), (False, 2, False), (True, 0, False), (True, 3, False)])
def test_budget_case_cannot_pass_from_an_unrelated_blocked_state(denial, requests, passed):
  runtime = SimpleNamespace(identity="a" * 64)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "taskkeeper-budget", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 2, "worker_executions": 1,
    "provider": {"requests": requests}, "facts": {"sdk_session": True, "manager_limit": 2, "real_account_used": False,
      "activity_drained": True, "job_status": "BLOCKED", "budget_denial_observed": denial}}
  assert native.verified_result(value, nonce="fixture", scenario="taskkeeper-budget", runtime=runtime) is passed


@pytest.mark.parametrize("started", [False, True])
def test_stop_case_requires_a_physically_started_worker(started):
  runtime = SimpleNamespace(identity="a" * 64)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "taskkeeper-stop", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 2, "worker_executions": 1,
    "provider": {"requests": 0}, "facts": {"sdk_session": True, "manager_limit": 2, "real_account_used": False,
      "activity_drained": True, "stop_requested": True, "worker_started_before_control": started}}
  assert native.verified_result(value, nonce="fixture", scenario="taskkeeper-stop", runtime=runtime) is started


def test_parent_loss_host_termination_dispatches_by_platform(tmp_path):
  """darwin撤权后经helper控制通道强停宿主；linux保持pidfd身份信号，均不向裸PID发信号。"""
  from agentcfg.pi_validation_parent_loss import ParentLossSupervisor
  calls = []
  class Store:
    owner = object()
    def request_cancel(self, lease_id, owner):
      calls.append(("request_cancel", lease_id)); return {"process_identity": {"pid": 11}, "grant_generation": 3}
    def read(self, lease_id): calls.append(("read", lease_id)); return {"process_identity": {"pid": 11}}
  class Processes:
    def stop(self, identity, *, grant_generation, force=False): calls.append(("helper_stop", identity["pid"], grant_generation, force))
    def send_signal(self, identity, number): calls.append(("pidfd_signal", identity["pid"], number))
  supervisor = ParentLossSupervisor({"state_root": str(tmp_path), "instance_root": str(tmp_path), "repository": str(tmp_path),
    "runtime_root": str(tmp_path), "instance_id": "i", "lock_identity": "l", "slice_identity": "s", "policy_digest": "p",
    "cwd": str(tmp_path), "engine": "node", "argv": []}, lease_fd=tmp_path / "lease", readiness=tmp_path / "ready",
    nonce="n", model_started=lambda: False, kill_platform="darwin")
  supervisor.store = Store(); supervisor.processes = Processes()
  supervisor.terminate_parent_host("host-lease")
  assert calls == [("request_cancel", "host-lease"), ("helper_stop", 11, 3, True)]
  calls.clear()
  supervisor.kill_platform = "linux"
  supervisor.terminate_parent_host("host-lease")
  assert calls == [("read", "host-lease"), ("pidfd_signal", 11, 9)]


@pytest.mark.parametrize("revoked,code,passed", [(True, 137, True), (False, 137, False), (True, 0, False)])
@pytest.mark.parametrize("kind", ["worker", "external"])
def test_parent_loss_requires_observed_kill_and_worker_revocation(revoked, code, passed, kind):
  runtime = SimpleNamespace(identity="a" * 64)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "parent-loss", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": code, "termination_confirmed": True, "executions": 2, "worker_executions": 1 if kind == "worker" else 0,
    "provider": {"requests": 1}, "facts": {"sdk_session": True, "manager_limit": 2, "real_account_used": False,
      "activity_drained": True, "child_execution_kind": kind, "parent_exit_observed": True, "worker_revocation_observed": revoked, "source_preserved": True}}
  assert native.verified_result(value, nonce="fixture", scenario="parent-loss", runtime=runtime) is passed


@pytest.mark.parametrize("missing", [None, "live_owner_rejected", "wrong_plan_rejected", "stop_only_recovery", "target_terminated"])
def test_recovery_proof_reports_first_party_processes_without_claiming_sdk_execution(missing):
  runtime = SimpleNamespace(identity="a" * 64)
  facts = {"sdk_session": False, "real_account_used": False, **dict.fromkeys(("first_party_processes", "live_owner_rejected", "old_owner_dead",
    "wrong_plan_rejected", "stop_only_recovery", "target_terminated", "source_preserved"), True)}
  if missing: facts.pop(missing)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "recovery-grants", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 1, "worker_executions": 0, "provider": {"requests": 0}, "facts": facts}
  assert native.verified_result(value, nonce="fixture", scenario="recovery-grants", runtime=runtime) is (missing is None)


def test_platform_limitation_keeps_linux_only_runners_and_derives_reasons_per_platform(tmp_path, monkeypatch):
  runtime, _ = fixture(tmp_path, monkeypatch)
  linux = replace(runtime, platform="linux-x86_64")
  darwin = replace(runtime, platform="darwin-arm64")
  other = replace(runtime, platform="unknown-platform")
  assert native.platform_limitation("recovery-grants", linux) is None
  assert native.platform_limitation("recovery-grants", darwin) == "recovery-runner-requires-macos-sealed-helper"
  assert native.platform_limitation("parent-loss", darwin) == "parent-loss-runner-requires-macos-sealed-helper"
  assert native.platform_limitation("delegate-control", darwin) == "standalone-control-runner-requires-macos-sealed-helper"
  assert native.platform_limitation("migration-runtime-conflicts", darwin) == "migration-runtime-mount-requires-macos-sealed-helper"
  assert native.platform_limitation("codex-native-write", darwin) == "migration-runtime-mount-requires-macos-sealed-helper"
  assert native.platform_limitation("host-resources", darwin) is None
  assert native.platform_limitation("delegate-control", other) == "scenario-not-implemented"
  assert native.platform_limitation("recovery-grants", other) == "recovery-runner-requires-linux"


def test_darwin_sealed_helper_opens_recovery_and_parent_loss_execution_entry(tmp_path, monkeypatch):
  runtime, _ = fixture(tmp_path, monkeypatch)
  darwin = replace(runtime, platform="darwin-arm64")
  with Tree(runtime.root) as tree:
    tree.write_new(".agentcfg-receipt.json", json_bytes({"files": {"bin/pi-supervisor-macos": {"sha256": "synthetic"}}}))
  for scenario in ("recovery-grants", "parent-loss", "delegate-control", "migration-runtime-conflicts", "codex-native-control"):
    assert native.platform_limitation(scenario, darwin) is None


def test_darwin_without_sealed_helper_has_no_standalone_or_mount_execution_entry(tmp_path, monkeypatch):
  runtime, args = fixture(tmp_path, monkeypatch)
  darwin = replace(runtime, platform="darwin-arm64")
  monkeypatch.setattr(native, "inspect_runtime", lambda _: darwin)
  monkeypatch.setattr(native, "supervise", lambda *_: pytest.fail("helper未密封时不得启动场景"))
  args.case = "migration-conflicts"
  result = native.execute(args)
  assert result["status"] == "not-run"
  assert result["results"] == [{"scenario_id": "migration-runtime-conflicts", "status": "not-run",
    "reason": "migration-runtime-mount-requires-macos-sealed-helper"}]


def test_capable_darwin_runtime_runs_helper_gated_scenarios_but_keeps_gates_for_linux_only_dispatch(tmp_path, monkeypatch):
  runtime, args = fixture(tmp_path, monkeypatch)
  darwin = replace(runtime, platform="darwin-arm64")
  monkeypatch.setattr(native, "inspect_runtime", lambda _: darwin)
  with Tree(runtime.root) as tree:
    tree.write_new(".agentcfg-receipt.json", json_bytes({"files": {"bin/pi-supervisor-macos": {"sha256": "synthetic"}}}))
  args.case = "all"
  from agentcfg import pi_cold_rebuild
  monkeypatch.setattr(pi_cold_rebuild, "cold_rebuild", lambda *args, **kwargs: {"status": "not-run", "targets": []})
  seen = []
  def supervise(_runtime, directory, argv, environment):
    value = json.loads((directory / "input.json").read_text())
    seen.append(value["scenario"])
    return {"exit_code": 0, "termination_confirmed": True}
  monkeypatch.setattr(native, "supervise", supervise)
  result = native.execute(args)
  by_id = {row["scenario_id"]: row for row in result["results"]}
  # 门控只负责真实执行入口；场景内部结果契约由各自验证覆盖。
  for scenario in ("delegate-control", "delegate-proxy-control", "migration-runtime-conflicts", "recovery-grants", "parent-loss"):
    assert scenario in seen and by_id[scenario]["status"] != "not-run"


def test_all_includes_readseek_tools_for_supported_profiles():
  # pi-default, pi-codex, pi-cursor 都支持 readseek-tools（cursor 使用独立 Node worker）
  for profile in ("pi-default", "pi-codex", "pi-cursor"):
    assert "readseek-tools" in native.scenarios("all", profile)
    assert native.scenarios("readseek-tools", profile) == ("readseek-tools",)
  # pi-managed 不支持（使用 Task Keeper 工具）
  assert "readseek-tools" not in native.scenarios("all", "pi-managed")
  assert native.scenarios("readseek-tools", "pi-managed") == ("readseek-profile-required",)


@pytest.mark.parametrize("missing", [None, "grep_verified", "search_verified", "def_verified", "refs_verified", "view_verified",
  "read_verified", "write_verified", "edit_verified", "rename_verified", "denied_write_rejected", "source_preserved", "activity_drained"])
def test_readseek_tools_requires_full_tool_flow_with_denial_and_clean_project(missing):
  runtime = SimpleNamespace(identity="a" * 64)
  facts = {"sdk_session": True, "manager_limit": 2, "real_account_used": False, "activity_drained": True,
    **dict.fromkeys(("grep_verified", "search_verified", "def_verified", "refs_verified", "view_verified",
      "read_verified", "write_verified", "edit_verified", "rename_verified",
      "denied_write_rejected", "source_preserved", "activity_drained"), True)}
  if missing: facts.pop(missing)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "readseek-tools", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 1, "worker_executions": 0,
    "provider": {"requests": 11}, "facts": facts}
  assert native.verified_result(value, nonce="fixture", scenario="readseek-tools", runtime=runtime) is (missing is None)
  value["provider"]["requests"] = 9
  assert native.verified_result(value, nonce="fixture", scenario="readseek-tools", runtime=runtime) is False


def test_readseek_provider_scripts_full_tool_sequence_and_denial():
  from agentcfg.pi_validation_provider import ScriptedProvider
  import json as jsonlib
  models = ["agentcfg-native-main"]
  provider = ScriptedProvider(models, scenario="readseek", denied_path="/fixture/forbidden.toml")
  tools = [{"type": "function", "function": {"name": name, "parameters": {}}}
    for name in ("readSeek_grep", "readSeek_digest", "readSeek_write", "readSeek_edit", "readSeek_rename")]
  prompts = ["warmup: acknowledge readiness without tools",
    "use readSeek_grep to find 'original'", "use readSeek_digest to read code.txt",
    "use readSeek_write to create notes.py", "use readSeek_edit to replace draft one",
    "use readSeek_rename to rename symbol", "attempt readSeek_write on the denied local.toml"]
  messages = []
  seen = []
  for prompt in prompts:
    messages.append({"role": "user", "content": prompt})
    status, body, _ = provider.response({"model": "agentcfg-native-main", "tools": tools, "messages": messages})
    assert status == 200
    choice = body["choices"][0]["message"]
    if not choice.get("tool_calls"):
      seen.append((None, None)); continue
    call = choice["tool_calls"][0]["function"]
    arguments = jsonlib.loads(call["arguments"])
    seen.append((call["name"], arguments))
    messages.append({"role": "assistant", "tool_calls": [{"function": {"name": call["name"], "arguments": call["arguments"]}}]})
  assert seen[0] == (None, None)
  names = [name for name, _ in seen[1:]]
  assert names == ["readSeek_grep", "readSeek_digest", "readSeek_write", "readSeek_edit", "readSeek_rename", "readSeek_write"]
  assert seen[-1][1]["path"] == "/fixture/forbidden.toml"
  assert seen[3][1] == {"path": "notes.py", "content": "draft one\nvalue = 1\nprint(value)\ndef helper():\n  return value\n"}
  assert seen[5][1]["to"] == "renamed"


def test_cold_dispatch_rebuilds_from_source_without_passing_a_reference_runtime_to_the_builder(tmp_path, monkeypatch):
  from agentcfg import pi_cold_rebuild
  runtime, args = fixture(tmp_path, monkeypatch)
  args.case = "cold-rebuild"
  calls = []
  def rebuild(repository, profile, destination, *, allow_host):
    calls.append((repository, profile, destination, allow_host))
    assert not destination.exists() and destination != runtime.root
    return {"status": "not-run", "targets": [{"installation": "verified", "native_execution": "not-run"}]}
  monkeypatch.setattr(pi_cold_rebuild, "cold_rebuild", rebuild)
  monkeypatch.setattr(native, "supervise", lambda *_: pytest.fail("cold builder owns fresh-target validation"))
  result = native.execute(args)
  assert result["status"] == "not-run" and len(calls) == 1 and calls[0][1] == runtime.profile and calls[0][3] is True


@pytest.mark.parametrize("fault", [None, "preset", "count", "acceptance", "source"])
def test_all_seven_delegate_presets_need_distinct_verified_executions(fault):
  runtime = SimpleNamespace(identity="a" * 64)
  presets = ["general", "context", "challenge", "plan", "research", "review", "scout"]
  facts = {"sdk_session": True, "manager_limit": 2, "real_account_used": False, "activity_drained": True,
    "source_preserved": fault != "source", "verified_execution_only": fault != "acceptance", "delegate_runs": 6 if fault == "count" else 7,
    "presets_verified": presets[:-1] if fault == "preset" else presets}
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "delegate-presets", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 8, "worker_executions": 0,
    "provider": {"requests": 28, "delivered_presets": sorted(presets)}, "facts": facts}
  assert native.verified_result(value, nonce="fixture", scenario="delegate-presets", runtime=runtime) is (fault is None)


@pytest.mark.parametrize("concurrency,passed", [(1, False), (2, True), (3, False)])
def test_batch_requires_observed_bounded_parallel_requests_and_verified_result_count(concurrency, passed):
  runtime = SimpleNamespace(identity="a" * 64)
  value = {"schema_version": 1, "nonce": "fixture", "scenario": "delegate-batch", "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 4, "worker_executions": 0,
    "provider": {"requests": 6, "max_inflight": concurrency}, "facts": {"sdk_session": True, "manager_limit": 2, "real_account_used": False,
      "activity_drained": True, "source_preserved": True, "batch_results": 3, "batch_idempotency_verified": True,
      "user_cli_verified": True, "peak_manager_running": 2}}
  assert native.verified_result(value, nonce="fixture", scenario="delegate-batch", runtime=runtime) is passed


@pytest.mark.parametrize("missing", [None, "resume", "probe"])
@pytest.mark.parametrize("codex", [False, True])
def test_standalone_cli_requires_every_control_operation_and_verified_resume(missing, codex):
  runtime = SimpleNamespace(identity="a" * 64)
  actions = ["cancel", "poll", "probe", "result", "resume", "start", "status", "wait"]
  if missing: actions.remove(missing)
  scenario = "codex-native-control" if codex else "delegate-control"
  value = {"schema_version": 1, "nonce": "fixture", "scenario": scenario, "runtime_identity": runtime.identity,
    "status": "passed", "host_exit_code": 0, "termination_confirmed": True, "executions": 3, "worker_executions": 0,
    "provider": {"requests": 5}, "facts": {"real_account_used": False, "standalone_delegate_sdk": not codex, "user_cli_operations": actions,
      "official_codex_cli": codex, "sdk_session": not codex, "kernel_namespace_verified": codex,
      "fresh_resume_verified": True, "cancel_after_request_verified": True, "source_preserved": True, "probe_metadata_only": True,
      "activity_drained": True, "verified_results": 2}}
  assert native.verified_result(value, nonce="fixture", scenario=scenario, runtime=runtime) is (missing is None)
