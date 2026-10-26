"""DSH 快照关联到候选停止服务；批准/通道为 fake，不控制真实进程。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agentcfg import dsh_stop_scope, run_owners, run_stop_fence, spawned_host
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.stop_inbox import StopInbox
from agentcfg.stop_service import StopService
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_stop_request_scope import HOST, saved
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


@pytest.fixture
def controlled(saved, monkeypatch):
  ws, registry, args, runs, request = saved
  case = SimpleNamespace(workspace=ws, registry=registry, args=args, request=deepcopy(request),
    signals=[], approved=True, checks=[])
  monkeypatch.setattr("agentcfg.stop_locks.time.monotonic_ns", lambda: 1000000000)
  case.request["deadline_ns"] = 2000000000
  case.journal = StopDispatches(ws.state_root / "test-dispatches", ws.binding)
  case.inbox = StopInbox(ws.state_root / "test-inbox", ws.binding)
  case.host = object.__new__(spawned_host.SpawnedHost)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", lambda self: deepcopy(HOST))
  def send(host):
    assert host is case.host
    assert case.journal.read(request["run_id"])["dispatch"] == "unknown"
    assert run_stop_fence.read_snapshot(registry, args["batch_id"])["records"]
    case.signals.append(host)
  monkeypatch.setattr(spawned_host.SpawnedHost, "send_sigterm_once", send)
  def verify(value):
    record = dsh_stop_scope.inspect_stop_request(ws, value, instance_fd=args["instance_fd"],
      state_fd=args["state_fd"], expected_layout=args["expected_layout"])
    case.checks.append(record)
    # 仅模型化独立批准；历史记录副本不是批准，也没有完整资源准入。
    return case.approved is True
  case.verify = verify
  return case


def build(case, verify=None):
  service = StopService(case.request["run_id"], case.host, inbox=case.inbox, journal=case.journal,
    verify=case.verify if verify is None else verify, clock=lambda: 1000000000)
  case.inbox.submit(case.request, expected=case.inbox.describe())
  return service


def test_matching_reference_precedes_one_fake_send_without_claiming_release(controlled):
  case = controlled; before = case.registry.snapshot(); service = build(case)
  assert service()["dispatch"] == "signal_sent"
  assert service() is None
  assert case.signals == [case.host] and len(case.checks) == 2
  assert case.registry.snapshot() == before
  assert case.checks[0]["session_observation"] is None
  assert case.checks[0]["lifecycle_state"] == "active"
  assert case.journal.read(case.request["run_id"])["dispatch"] == "signal_sent"


def test_valid_snapshot_cannot_substitute_for_independent_approval(controlled):
  case = controlled; case.approved = False; service = build(case)
  with pytest.raises(Conflict): service()
  assert len(case.checks) == 1 and case.signals == []
  assert not case.journal.root.exists()
  with pytest.raises(Conflict): service()
  assert len(case.checks) == 1


def test_record_return_is_not_a_true_authorization_result(controlled):
  case = controlled
  def verify(request):
    case.verify(request)
    return case.checks[-1]
  service = build(case, verify)
  with pytest.raises(Conflict): service()
  assert case.signals == [] and not case.journal.root.exists()


@pytest.mark.parametrize("damage", ["owner", "fence", "snapshot"])
def test_change_after_dispatch_intent_preserves_unknown_without_send_or_retry(controlled, monkeypatch, damage):
  case = controlled; service = build(case); write = Tree.write_new
  run = case.request["run_id"]
  def changed(tree, name, *args, **kwargs):
    result = write(tree, name, *args, **kwargs)
    if tree.root == case.journal.root and name == run + ".json":
      if damage == "owner":
        path = case.registry.root / name
        record = deepcopy(case.args["expected_records"][run])
        record["start_cwd"]["path"] = "/synthetic-changed"
        path.write_bytes(run_owners._encode(record))
      elif damage == "fence":
        path = case.registry.root.parent / run_stop_fence._name(case.registry)
        path.write_bytes(b"synthetic-private-canary")
      else:
        path = case.registry.root.parent / run_stop_fence._snapshot_name(case.registry, case.args["batch_id"])
        path.unlink()
    return result
  monkeypatch.setattr(Tree, "write_new", changed)
  with pytest.raises(Conflict) as caught: service()
  assert "synthetic-private-canary" not in str(caught.value)
  assert len(case.checks) == 1 and case.signals == []
  assert case.journal.read(run)["dispatch"] == "unknown"
  with pytest.raises(Conflict): service()
  assert len(case.checks) == 1 and case.signals == []
