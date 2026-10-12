"""私有监督协议的认证/权限与幂等；进程创建只调用显式替身。"""

from pathlib import Path
import os
import pytest

from agentcfg.pi_supervisor import SupervisorService, SpawnCommand
from test_pi_activity import make_store, identity


def request(method, args):
  return {"schema_version": 1, "request_id": "request", "method": method, "args": args}


def fixture(tmp_path):
  store, processes = make_store(tmp_path)
  calls = []
  def command(lease, program, payload):
    assert program == "worker"
    return SpawnCommand(("synthetic-worker",), tmp_path, {"SELECTED_SECRET": "synthetic-secret"})
  def spawn(command, lease):
    calls.append((command, lease))
    worker = identity(201)
    processes.current[201] = worker
    return worker
  # 显式声明本机械测试的合成执行器；不代表产品 Task Keeper 准入。
  def worker_operation(*args, **kwargs):
    raise AssertionError("lease mechanics must not execute Worker file operations")
  service = SupervisorService(store, command, spawn, worker_operation=worker_operation)
  host_identity = identity(111)
  processes.current[111] = host_identity
  host = store.begin(kind="host", execution_id="host", task_id=None, attempt_id="host-attempt", lock_identity="a" * 64,
    slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None, planned_workspaces=[], spawn=lambda _: host_identity)
  token = service.issue_capability("manager", host["lease_id"])
  args = {"kind": "worker", "execution_id": "execution", "task_id": "task", "attempt_id": "attempt", "lock_identity": "a" * 64,
    "slice_identity": "b" * 64, "policy_digest": "c" * 64, "candidate_digest": "d" * 64, "planned_workspaces": []}
  return service, token, args, calls


def test_authentication_unknown_fields_and_worker_dispatch_are_rejected(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  assert service.reply(token, os.geteuid() + 1, request("allocate", args))["ok"] is False
  assert service.reply("foreign-token", os.geteuid(), request("allocate", args))["ok"] is False
  assert service.reply(token, os.geteuid(), {**request("allocate", args), "role": "user"})["exit_code"] == 2
  allocation = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  worker = service.issue_capability("worker", allocation["lease_id"])
  assert service.reply(worker, os.geteuid(), request("allocate", args))["exit_code"] == 4
  assert service.reply(worker, os.geteuid(), request("recover_stop", {"lease_id": allocation["lease_id"], "plan_digest": "a" * 64}))["exit_code"] == 4
  assert calls == []


@pytest.mark.parametrize("reason", ["PERMISSION_DENIED", "PERMISSION_DENIED private synthetic marker", "private synthetic marker"])
def test_policy_deny_has_one_fixed_public_code_without_exposing_other_failures(tmp_path, reason):
  from agentcfg.storage import Conflict
  service, token, _, calls = fixture(tmp_path)
  def deny(*_args): raise Conflict(reason)
  service.ordinary_handler = deny
  response = service.reply(token, os.geteuid(), request("ordinary_admission_prepare", {}))
  assert response == {"schema_version": 1, "ok": False, "exit_code": 4,
    "error": "PERMISSION_DENIED" if reason == "PERMISSION_DENIED" else "PI_CONTROL_REJECTED"}
  assert "private synthetic marker" not in str(response) and calls == []


def test_allocate_and_start_retries_never_duplicate_execution_or_persist_secrets(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  allocation = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  assert service.reply(token, os.geteuid(), request("allocate", args))["result"] == allocation
  command = request("start", {"lease_id": allocation["lease_id"], "program": "worker", "payload": {"descriptor": "nonsecret"}})
  first = service.reply(token, os.geteuid(), command)
  assert first["result"]["state"] == "running"
  assert service.reply(token, os.geteuid(), command) == first
  assert len(calls) == 1
  assert all(b"synthetic-secret" not in file.read_bytes() for file in service.store.root.rglob("*.json"))


def test_revocation_blocks_old_worker_capability_and_read_only_inspection_remains(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  allocated = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  lease = allocated["lease_id"]
  service.reply(token, os.geteuid(), request("start", {"lease_id": lease, "program": "worker", "payload": {}}))
  worker = service.issue_capability("worker", lease)
  assert service.reply(worker, os.geteuid(), request("authorize", {"lease_id": lease, "grant_generation": 1}))["result"]["valid"] is True
  assert service.reply(token, os.geteuid(), request("cancel", {"lease_id": lease}))["result"]["termination_confirmed"] is False
  assert service.reply(worker, os.geteuid(), request("authorize", {"lease_id": lease, "grant_generation": 1}))["exit_code"] == 4
  assert service.reply(worker, os.geteuid(), request("inspect", {"lease_id": lease}))["result"]["protected"] is True


@pytest.mark.parametrize("method", ("inspect", "reconcile"))
def test_readonly_inspection_reports_persisted_spawn_commit_for_safe_cleanup(tmp_path, method):
  service, token, args, calls = fixture(tmp_path)
  lease = service.reply(token, os.geteuid(), request("allocate", args))["result"]["lease_id"]
  def inspect():
    return service.reply(token, os.geteuid(), request(method, {"lease_id": lease}))["result"]
  before = inspect()
  assert before["state"] == "allocating" and before["spawn_committed"] is False and calls == []
  service.reply(token, os.geteuid(), request("start", {"lease_id": lease, "program": "worker", "payload": {}}))
  after = inspect()
  assert after["state"] == "running" and after["spawn_committed"] is True and len(calls) == 1
  service.reply(token, os.geteuid(), request("cancel", {"lease_id": lease}))
  canceled = inspect()
  assert canceled["spawn_committed"] is True and canceled["protected"] is True
  assert service.reply(token, os.geteuid(), request("abort_allocation", {"lease_id": lease}))["ok"] is False


def test_queued_allocations_share_one_physical_start_capacity(tmp_path):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  service, token, args, calls = fixture(tmp_path)
  gate = Barrier(3)
  def allocate(index):
    gate.wait()
    return service.reply(token, os.geteuid(), request("allocate", {**args, "execution_id": "execution-" + str(index), "attempt_id": "attempt-" + str(index)}))
  with ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(allocate, range(3)))
  assert all(item["ok"] for item in results)
  assert calls == []
  gate = Barrier(3)
  def start(item):
    gate.wait()
    return service.reply(token, os.geteuid(), request("start", {"lease_id": item["result"]["lease_id"], "program": "worker", "payload": {}}))
  with ThreadPoolExecutor(max_workers=3) as pool:
    started = list(pool.map(start, results))
  assert sum(item["ok"] for item in started) == 2
  assert [item["exit_code"] for item in started if not item["ok"]] == [4]
  assert len(calls) == 2
  # 满容量时重复已提交的 start 仍只读取原执行。
  successful = next(item["result"]["lease_id"] for item in started if item["ok"])
  assert service.reply(token, os.geteuid(), request("start", {"lease_id": successful, "program": "worker", "payload": {}}))["ok"]
  assert len(calls) == 2


def test_user_recovery_capability_cannot_create_or_resume_execution(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  user = service.issue_capability("user")
  assert service.reply(user, os.geteuid(), request("allocate", args))["exit_code"] == 4
  allocation = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  assert service.reply(user, os.geteuid(), request("start", {"lease_id": allocation["lease_id"], "program": "worker", "payload": {}}))["exit_code"] == 4
  assert service.reply(user, os.geteuid(), request("abort_allocation", {"lease_id": allocation["lease_id"]}))["ok"]
  assert calls == []


def test_activity_summary_includes_unspawned_allocations_and_closing_blocks_ordinary_admission(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  assert service.reply(token, os.geteuid(), request("activity_summary", {}))["result"] == {"active_count": 0, "unknown_count": 0}
  allocated = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  assert service.reply(token, os.geteuid(), request("activity_summary", {}))["result"]["active_count"] == 1
  worker = service.issue_capability("worker", allocated["lease_id"])
  assert service.reply(worker, os.geteuid(), request("activity_summary", {}))["exit_code"] == 4
  invocations = []
  service.ordinary_handler = lambda *values: invocations.append(values)
  service.closing = True
  for method in ("ordinary_prepare", "ordinary_command_prepare"):
    assert service.reply(token, os.geteuid(), request(method, {}))["exit_code"] == 4
  assert not invocations and not calls


def test_force_cancel_is_explicit_and_worker_cannot_escalate_to_controller(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  lease = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  service.reply(token, os.geteuid(), request("start", {"lease_id": lease["lease_id"], "program": "worker", "payload": {}}))
  worker = service.issue_capability("worker", lease["lease_id"])
  assert service.reply(worker, os.geteuid(), request("cancel", {"lease_id": lease["lease_id"], "force": True}))["exit_code"] == 4
  reply = service.reply(token, os.geteuid(), request("cancel", {"lease_id": lease["lease_id"], "force": True}))["result"]
  assert reply["grant_generation"] == 2 and reply["termination_confirmed"] is False
  assert lease["lease_id"] in service.force_stop_ids


def test_registered_services_keep_their_own_limit_without_consuming_task_capacity(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  leases = []
  for index in range(5):
    value = service.reply(token, os.geteuid(), request("allocate", {**args, "kind": "external", "execution_id": "service-test-" + str(index), "attempt_id": "attempt-" + str(index)}))["result"]
    leases.append(value["lease_id"])
  for lease in leases[:2]: service.register_service_lease(lease)
  for lease in leases[:4]:
    result = service.reply(token, os.geteuid(), request("start", {"lease_id": lease, "program": "worker", "payload": {}}))
    assert result["ok"]
  assert len(service.execution_children()) == 2 and len(calls) == 4
  assert service.reply(token, os.geteuid(), request("start", {"lease_id": leases[4], "program": "worker", "payload": {}}))["exit_code"] == 4
  service.active_services = 2
  import pytest
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict, match="SERVICE_CAPACITY_BUSY"): service.register_service_lease(leases[4])


def test_unselected_optional_error_and_invalid_rpc_do_not_import_codex(tmp_path, monkeypatch):
  import builtins
  from agentcfg import pi_supervisor
  service, token, _args, calls = fixture(tmp_path)
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if name == "pi_codex_admission" or name.startswith("agentcfg.pi_codex_admission"):
      raise AssertionError("unselected Codex formatter imported")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  # 普通参数错误也不能让Base为格式化错误而导入委派实现。
  reply = service.reply(token, os.geteuid(), request("missing-method", {}))
  assert reply == {"schema_version": 1, "ok": False, "exit_code": 2, "error": "PI_CONTROL_REJECTED"}
  def unavailable(*args): raise pi_supervisor.OrdinaryCapabilityUnavailable()
  service.ordinary_handler = unavailable
  reply = service.reply(token, os.geteuid(), request("ordinary_web_file_prepare", {}))
  assert reply == {"schema_version": 1, "ok": False, "exit_code": 5, "error": "ORDINARY_CAPABILITY_UNAVAILABLE"}
  assert calls == []


def test_selected_delegate_preserves_fixed_public_error_codes(tmp_path):
  from agentcfg.pi_codex_admission import CodexAdmissionError
  service, token, _args, calls = fixture(tmp_path)
  def denied(*args): raise CodexAdmissionError("CODEX_SYSTEM_CONFIG_PRESENT")
  service.delegate_handler = denied
  reply = service.reply(token, os.geteuid(), request("delegate_prepare", {}))
  assert reply == {"schema_version": 1, "ok": False, "exit_code": 5, "error": "CODEX_SYSTEM_CONFIG_PRESENT"}
  assert calls == []


def test_unselected_worker_admission_both_purposes_reject_before_import(tmp_path, monkeypatch):
  import builtins
  service, token, _, calls = fixture(tmp_path)
  service.worker_operation = None
  original = builtins.__import__
  imports = []
  def guarded(name, *args, **kwargs):
    if any(part in name for part in ("pi_worker_files", "pi_worker_protocol")):
      imports.append(name); raise AssertionError("unselected worker protocol imported")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  before = service.store.records()
  for purpose in ("admission", "result"):
    reply = service.reply(token, os.geteuid(), request("worker_admission", {"descriptor": {}, "purpose": purpose}))
    assert reply["exit_code"] == 5 and reply["error"] == "ORDINARY_CAPABILITY_UNAVAILABLE"
  assert imports == [] and calls == [] and service.store.records() == before


def test_unselected_worker_allocate_has_no_execution_or_writer_side_effect(tmp_path):
  from test_pi_workspace_leases import worktree
  from agentcfg.workspace_leases import WorkspaceLeases
  service, token, args, calls = fixture(tmp_path); service.worker_operation = None
  service.store.workspaces = WorkspaceLeases("fixture-boot")
  root = worktree(tmp_path / "project")
  planned = service.store.workspaces.identify(root)
  before = service.store.records()
  reply = service.reply(token, os.geteuid(), request("allocate", {**args, "planned_workspaces": [planned]}))
  assert reply["exit_code"] == 5 and reply["error"] == "ORDINARY_CAPABILITY_UNAVAILABLE"
  assert service.store.records() == before and service.store.workspaces.read(planned) is None and calls == []


def test_unselected_old_worker_start_preserves_reserved_writer_and_recovery(tmp_path):
  from test_pi_workspace_leases import worktree
  from agentcfg.workspace_leases import WorkspaceLeases
  service, token, args, calls = fixture(tmp_path)
  service.store.workspaces = WorkspaceLeases("fixture-boot")
  root = worktree(tmp_path / "project"); planned = service.store.workspaces.identify(root)
  lease = service.store.allocate(**{**args, "planned_workspaces": [planned]})
  service.worker_operation = None
  before = {path.relative_to(service.store.root): path.read_bytes() for path in service.store.root.rglob("*.json")}
  marker = service.store.workspaces.read(planned)
  reply = service.reply(token, os.geteuid(), request("start", {"lease_id": lease["lease_id"], "program": "worker", "payload": {}}))
  assert reply["exit_code"] == 5 and reply["error"] == "ORDINARY_CAPABILITY_UNAVAILABLE"
  assert {path.relative_to(service.store.root): path.read_bytes() for path in service.store.root.rglob("*.json")} == before
  assert service.store.workspaces.read(planned) == marker and calls == []
  inspected = service.reply(token, os.geteuid(), request("inspect", {"lease_id": lease["lease_id"]}))
  assert inspected["ok"] and inspected["result"]["protected"] is True
  canceled = service.reply(token, os.geteuid(), request("cancel", {"lease_id": lease["lease_id"]}))
  # 未启动分配没有进程身份，原普通取消仍拒绝；显式 never-started 恢复保持可用。
  assert canceled["exit_code"] == 4
  assert service.store.workspaces.read(planned) == marker
  assert service.reply(token, os.geteuid(), request("abort_allocation", {"lease_id": lease["lease_id"]}))["ok"]
  assert service.store.reconcile(lease["lease_id"])["protected"] is False


def test_unselected_running_worker_inspection_and_cancellation_remain_available(tmp_path):
  service, manager, args, calls = fixture(tmp_path)
  lease = service.store.allocate(**args)
  def spawn(_):
    value = identity(301); service.store.processes.current[301] = value
    return value
  lease = service.store.start(lease["lease_id"], service.store.owner, spawn=spawn)
  service.worker_operation = None
  inspected = service.reply(manager, os.geteuid(), request("inspect", {"lease_id": lease["lease_id"]}))
  assert inspected["ok"] and inspected["result"]["protected"] is True
  canceled = service.reply(manager, os.geteuid(), request("cancel", {"lease_id": lease["lease_id"]}))
  assert canceled["ok"] and canceled["result"]["termination_confirmed"] is False
  assert service.store.read(lease["lease_id"])["state"] == "cancel_requested"
  assert service.store.reconcile(lease["lease_id"])["protected"] is True and calls == []


@pytest.mark.parametrize("kind", ["worker", "external"])
def test_unselected_old_worker_authorize_is_revoked_but_external_worker_role_remains(tmp_path, kind):
  service, _, args, calls = fixture(tmp_path)
  lease = service.store.allocate(**{**args, "kind": kind, "execution_id": kind, "attempt_id": kind})
  def spawn(_):
    value = identity(301 if kind == "worker" else 302)
    service.store.processes.current[value["pid"]] = value
    return value
  lease = service.store.start(lease["lease_id"], service.store.owner, spawn=spawn)
  token = service.issue_capability("worker", lease["lease_id"])
  service.worker_operation = None
  reply = service.reply(token, os.geteuid(), request("authorize", {"lease_id": lease["lease_id"], "grant_generation": 1}))
  if kind == "worker":
    assert reply["exit_code"] == 5 and reply["error"] == "ORDINARY_CAPABILITY_UNAVAILABLE"
  else:
    assert reply["ok"] and reply["result"] == {"valid": True, "grant_generation": 1}
  assert calls == []
