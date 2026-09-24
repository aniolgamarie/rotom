"""私有监督协议的认证/权限与幂等；进程创建只调用显式替身。"""

from pathlib import Path
import os

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
  service = SupervisorService(store, command, spawn)
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
