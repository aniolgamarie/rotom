"""停止收尾仅处理测试元数据；不启动宿主、不发送信号、不改变运行观察。"""
from copy import deepcopy

import pytest

from agentcfg import dsh_stop, dsh_stop_plan, dsh_stop_scope, run_owners, run_stop_fence, stop_review
from agentcfg.stop_inbox import StopInbox
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_dsh_stop_request_scope import HOST
from test_rotom_runtime_observation import MANAGER, observation


@pytest.fixture
def accepted(prepared, monkeypatch):
  ws, registry, args, runs = prepared
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  for run in runs[:2]:
    inbox = StopInbox(ws.state_root / "stop-inboxes" / run, ws.binding)
    endpoint = inbox.create(run_id=run, manager_identity=MANAGER, host_identity=HOST["identity"])
    record = args["expected_records"][run]
    record["host_identity"] = deepcopy(HOST)
    record["process_observation"]["host_identity"] = deepcopy(HOST)
    record["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": endpoint}
    (registry.root / (run + ".json")).write_bytes(run_owners._encode(record))
  plan = dsh_stop.preview_stop(ws, selected_runs=runs[:2])["plan"]
  plan["control_capability"] = "supported"
  plan = dsh_stop_plan.normalize(plan, verify=False)
  review = stop_review.review_stop_plan(plan, scope=plan["scope"], operation="stop_only",
    selected_runs=plan["selected_runs"], plan_id=plan["plan_id"], batch_id=args["batch_id"], approve=lambda _: True)
  dsh_stop_scope.save_reviewed_snapshot(ws, **{k: args[k] for k in
    ("instance_fd", "state_fd", "expected_records", "expected_layout", "batch_id")}, plan=plan, review=review)
  return ws, registry, args, runs, plan


def finish(accepted, count=2):
  ws, registry, args, runs, plan = accepted
  for run in runs[:count]:
    registry.finish_current(run, MANAGER, run_owners.ReleaseObservation(run, MANAGER, True, True))


def close(accepted, reason="stopped", **changes):
  from agentcfg import dsh_stop_completion
  ws, registry, args, runs, plan = accepted
  return dsh_stop_completion.close_stop(ws, **({"batch_id": args["batch_id"],
    "plan_id": plan["plan_id"], "reason": reason} | changes))


def request(accepted, run=None):
  ws, registry, args, runs, plan = accepted
  return {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop", "request_id": "d" * 32,
    "batch_id": args["batch_id"], "plan_id": plan["plan_id"], "run_id": run or runs[0],
    "manager_identity": MANAGER, "host_identity": HOST["identity"], "deadline_ns": 100}


def test_finish_preserves_unselected_owner_and_history_releases_only_matching_fence(accepted, monkeypatch):
  from agentcfg import dsh_stop_completion
  ws, registry, args, runs, plan = accepted
  finish(accepted)
  before = registry.snapshot()
  writes = []; real = Tree.write_new
  def write(tree, name, data):
    assert_exclusive_busy(ws.instance)
    assert_exclusive_busy(ws.state_root / "instance.lock")
    with pytest.raises(Conflict):
      with registry._locked(nonblocking=True): pass
    assert (ws.state_root / run_stop_fence._name(registry)).exists()
    writes.append(name)
    return real(tree, name, data)
  monkeypatch.setattr(Tree, "write_new", write)
  result = close(accepted)
  assert result["reason"] == "stopped" and set(result["records"]) == set(runs[:2])
  assert len(writes) == 1 and run_stop_fence.read(registry) is None
  assert registry.snapshot() == before and before[runs[2]]["lifecycle_state"] == "active"
  assert run_stop_fence.read_snapshot(registry, args["batch_id"])["plan"] == plan
  assert dsh_stop_completion.read_close(registry, args["batch_id"]) == result
  assert close(accepted) == result
  with pytest.raises(Conflict): registry.assert_inactive()


@pytest.mark.parametrize("state", ["active", "partial", "unknown"])
def test_incomplete_exit_never_removes_protection(accepted, state):
  ws, registry, args, runs, plan = accepted
  if state == "partial": finish(accepted, 1)
  if state == "unknown": registry.mark_unknown(runs[0], MANAGER)
  before = registry.snapshot()
  with pytest.raises(Conflict): close(accepted)
  assert run_stop_fence.read(registry) is not None and registry.snapshot() == before


def test_cancel_only_unposted_active_items_without_changing_owners(accepted):
  ws, registry, args, runs, plan = accepted
  finish(accepted, 1)
  before = registry.snapshot()
  result = close(accepted, "cancelled")
  assert result["reason"] == "cancelled" and registry.snapshot() == before
  assert result["records"][runs[1]]["lifecycle_state"] == "active"
  assert run_stop_fence.read(registry) is None
  with pytest.raises(Conflict): registry.assert_inactive()


@pytest.mark.parametrize("fact", ["posted", "dispatch", "unknown", "endpoint"])
def test_cancel_refuses_possible_dispatch_unknown_or_replaced_channel(accepted, fact):
  ws, registry, args, runs, plan = accepted
  inbox = StopInbox(ws.state_root / "stop-inboxes" / runs[0], ws.binding)
  if fact == "posted": inbox.submit(request(accepted), expected=inbox.describe())
  elif fact == "dispatch": StopDispatches(ws.state_root / "stop-dispatches", ws.binding).begin(request(accepted))
  elif fact == "unknown": registry.mark_unknown(runs[0], MANAGER)
  else:
    value = inbox.describe(); value["nonce"] = "e" * 32
    (inbox.root / "endpoint.json").write_bytes(run_owners._encode(value))
  before = registry.snapshot()
  with pytest.raises(Conflict): close(accepted, "cancelled")
  assert run_stop_fence.read(registry) is not None and registry.snapshot() == before


@pytest.mark.parametrize("change", ["batch_id", "plan_id", "reason", "record", "snapshot", "fence"])
def test_mismatch_fails_without_clearing_fence(accepted, change):
  ws, registry, args, runs, plan = accepted
  finish(accepted)
  values = {}
  if change == "batch_id": values[change] = "e" * 32
  elif change == "plan_id": values[change] = "e" * 64
  elif change == "reason": values[change] = "timeout"
  elif change == "record":
    row = registry.snapshot()[runs[0]]; row["start_cwd"]["path"] = "/synthetic-other"
    (registry.root / (runs[0] + ".json")).write_bytes(run_owners._encode(row))
  else:
    name = run_stop_fence._snapshot_name(registry, args["batch_id"]) if change == "snapshot" else run_stop_fence._name(registry)
    (ws.state_root / name).write_text("synthetic-private-canary")
  with pytest.raises(Conflict) as caught: close(accepted, **values)
  assert "synthetic-private-canary" not in str(caught.value)
  assert (ws.state_root / run_stop_fence._name(registry)).exists()


@pytest.mark.parametrize("stage", ["close-write", "before-unlink", "after-unlink"])
def test_partial_close_keeps_durable_facts_and_explicit_reconciliation_is_not_dispatch(accepted, monkeypatch, stage):
  from agentcfg import dsh_stop_completion
  ws, registry, args, runs, plan = accepted
  finish(accepted)
  real_write, real_replace = Tree.write_new, Tree.replace
  def write(tree, name, data):
    if stage == "close-write": raise OSError("synthetic-private-canary")
    return real_write(tree, name, data)
  def replace(tree, name, data, **kwargs):
    if data is None:
      if stage == "before-unlink": raise OSError("synthetic-private-canary")
      real_replace(tree, name, data, **kwargs)
      raise OSError("synthetic-private-canary")
    return real_replace(tree, name, data, **kwargs)
  monkeypatch.setattr(Tree, "write_new", write); monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict): close(accepted)
  saved = dsh_stop_completion.read_close(registry, args["batch_id"])
  assert (saved is None) == (stage == "close-write")
  assert (run_stop_fence.read(registry) is None) == (stage == "after-unlink")
  monkeypatch.setattr(Tree, "write_new", real_write); monkeypatch.setattr(Tree, "replace", real_replace)
  assert close(accepted)["reason"] == "stopped"
  assert run_stop_fence.read(registry) is None


def test_finished_operation_cannot_remove_another_fence(accepted):
  ws, registry, args, runs, plan = accepted
  finish(accepted); prior = close(accepted)
  records = registry.snapshot()
  run_stop_fence.install(registry, batch_id="e" * 32, plan_id="f" * 64, expected_records=records)
  before = run_stop_fence.read(registry)
  assert close(accepted) == prior
  assert run_stop_fence.read(registry) == before
