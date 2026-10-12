"""真实RPC调度串行一次消费；线程、临时树及假进程，不启动宿主。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict
from test_pi_activity import identity
from test_pi_operations import setup
from test_pi_supervisor import request


def fixture(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  service = host.service
  service.ordinary_handler = operations.handle
  args = {"operation_id": "approval", "role_id": "main", "cwd": cwd,
    "tool_name": "write", "input": {"path": "new.txt", "content": "synthetic body"}}
  return service, operations, host, cwd, principal, args


def external_records(host):
  return [row for row in host.store.records() if row["kind"] == "external"]


def assert_no_writer(host, cwd):
  assert external_records(host) == []
  assert not (Path(cwd) / ".git/agentcfg/write-lease.json").exists()
  assert not list((host.root / "activity/ordinary-operations").glob("*.json"))
  assert not (Path(cwd) / "new.txt").exists()


def test_two_concurrent_authenticated_consumers_create_exactly_one_writer(tmp_path, monkeypatch):
  service, operations, host, cwd, principal, args = fixture(tmp_path)
  prepared = service.handle(principal, request("ordinary_prepare_deferred", args))
  assert prepared["state"] == "prepared" and prepared["lease_id"] is None
  assert_no_writer(host, cwd)
  allocation_calls = []
  allocate = host.store.allocate
  def counted(**kwargs):
    allocation_calls.append(deepcopy(kwargs))
    return allocate(**kwargs)
  monkeypatch.setattr(host.store, "allocate", counted)
  gate = Barrier(3)

  def consume(index):
    gate.wait(timeout=5)
    try:
      return {"result": service.handle(principal, {**request("ordinary_consume", {"operation_id": prepared["operation_id"]}), "request_id": "consume-" + str(index)})}
    except Conflict as error:
      return {"rejected": str(error)}

  with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(consume, index) for index in range(2)]
    gate.wait(timeout=5)
    outcomes = [future.result(timeout=5) for future in futures]
  successful = [row["result"] for row in outcomes if "result" in row]
  rejected = [row["rejected"] for row in outcomes if "rejected" in row]
  assert len(successful) == len(rejected) == 1
  assert rejected == ["ORDINARY_OPERATION_ALREADY_CONSUMED"]
  consumed = successful[0]
  assert consumed["state"] == "consumed" and isinstance(consumed["lease_id"], str) and consumed["lease_id"]
  assert {key: consumed[key] for key in ("operation_id", "write", "path", "request_digest")} == {
    key: prepared[key] for key in ("operation_id", "write", "path", "request_digest")}
  assert len(allocation_calls) == 1 and allocation_calls[0]["kind"] == "external"
  leases = external_records(host)
  assert len(leases) == 1 and leases[0]["lease_id"] == consumed["lease_id"]
  assert leases[0]["state"] == "allocating" and leases[0]["spawn_committed"] is False
  planned = leases[0]["planned_workspaces"]
  assert len(planned) == 1
  assert host.store.workspaces.read(planned[0])["state"] == "reserved"
  assert service.handle(principal, request("ordinary_status", {"operation_id": consumed["operation_id"]})) == consumed
  assert len(list((host.root / "activity/ordinary-operations").glob("*.json"))) == 1
  assert not (Path(cwd) / "new.txt").exists()
  # 已消费Writer不能以普通finish丢弃未知保护，查询始终不重新消费。
  with pytest.raises(Conflict, match="TERMINATION_UNKNOWN"):
    service.handle(principal, request("ordinary_finish", {"operation_id": consumed["operation_id"]}))
  assert service.handle(principal, request("ordinary_status", {"operation_id": consumed["operation_id"]})) == consumed
  assert len(external_records(host)) == 1


def test_closing_rejects_preparation_and_consumption_but_allows_readonly_status_and_drop(tmp_path):
  service, operations, host, cwd, principal, args = fixture(tmp_path)
  prepared = service.handle(principal, request("ordinary_prepare_deferred", args))
  before = deepcopy(host.store.records())
  service.closing = True
  with pytest.raises(Conflict, match="关闭"):
    service.handle(principal, request("ordinary_prepare_deferred", {**args, "operation_id": "later"}))
  with pytest.raises(Conflict, match="关闭"):
    service.handle(principal, request("ordinary_consume", {"operation_id": prepared["operation_id"]}))
  assert service.handle(principal, request("ordinary_status", {"operation_id": prepared["operation_id"]})) == prepared
  assert service.handle(principal, request("ordinary_finish", {"operation_id": prepared["operation_id"]})) == {"finished": True}
  finished = service.handle(principal, request("ordinary_status", {"operation_id": prepared["operation_id"]}))
  assert finished == {**prepared, "state": "finished"}
  assert host.store.records() == before
  assert_no_writer(host, cwd)


@pytest.mark.parametrize("role", ["worker", "another-manager", "another-generation"])
@pytest.mark.parametrize("method", ["ordinary_consume", "ordinary_status", "ordinary_finish"])
def test_rpc_prepared_ticket_is_bound_to_exact_manager_and_generation(tmp_path, role, method):
  service, operations, host, cwd, principal, args = fixture(tmp_path)
  prepared = service.handle(principal, request("ordinary_prepare_deferred", args))
  if role == "another-manager":
    another = host.store.allocate(kind="host", execution_id="other-parent", task_id=None, attempt_id="other-parent",
      lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None, planned_workspaces=[])
    host.store.processes.current[203] = identity(203)
    host.store.start(another["lease_id"], host.store.owner, spawn=lambda _: identity(203))
    caller = Principal("manager", another["lease_id"], another["grant_generation"])
  elif role == "worker":
    caller = Principal("worker", principal.lease_id, principal.grant_generation)
  else:
    caller = Principal("manager", principal.lease_id, principal.grant_generation + 1)
  before = deepcopy(host.store.records())
  with pytest.raises(Conflict, match="ORDINARY_OPERATION_MANAGER_REQUIRED"):
    service.handle(caller, request(method, {"operation_id": prepared["operation_id"]}))
  assert service.handle(principal, request("ordinary_status", {"operation_id": prepared["operation_id"]})) == prepared
  assert host.store.records() == before
  assert_no_writer(host, cwd)
  # 外来调用没有消费或删除真正manager的票据。
  consumed = service.handle(principal, request("ordinary_consume", {"operation_id": prepared["operation_id"]}))
  assert consumed["state"] == "consumed" and consumed["lease_id"]
  assert len(external_records(host)) == 1
