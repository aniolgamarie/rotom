"""停止客户端隔离契约：真实临时快照/inbox，fake manager 与共享时钟。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agentcfg import dsh_stop, dsh_stop_client as client, dsh_stop_completion as completion
from agentcfg import dsh_stop_control, run_owners, run_stop_fence
from agentcfg.control_deadline import ControlDeadline
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.stop_inbox import StopInbox
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_stop_completion import accepted, request, finish
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_dsh_stop_request_scope import HOST
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import MANAGER, observation


_REAL_AVAILABLE = dsh_stop_control.available_locked


@pytest.fixture
def clock(monkeypatch):
  state = SimpleNamespace(now=0.0, sleeps=[], captures=[], closed=[], exited=False, capture_error=None)
  monkeypatch.setattr(client.time, "monotonic_ns", lambda: int(state.now * 1000000000))
  monkeypatch.setattr(client, "ControlDeadline", lambda seconds: ControlDeadline(seconds, clock=lambda: state.now))
  def sleep(seconds): state.sleeps.append(seconds); state.now += max(seconds, 0.05)
  monkeypatch.setattr(client.time, "sleep", sleep)
  class Exit:
    def __init__(self, identity):
      state.captures.append(deepcopy(identity))
      if state.capture_error is not None: raise state.capture_error
    def __enter__(self): return self
    def exited(self): return state.exited
    def __exit__(self, *args): state.closed.append(True)
  monkeypatch.setattr(client, "ManagerExit", Exit)
  monkeypatch.setattr(dsh_stop_control, "available_locked", lambda *a, **kw: True)
  return state


@pytest.fixture
def fresh(prepared, monkeypatch, clock):
  ws, registry, args, runs = prepared
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  for run in runs[:2]:
    inbox = StopInbox(ws.state_root / "stop-inboxes" / run, ws.binding)
    endpoint = inbox.create(run_id=run, manager_identity=MANAGER, host_identity=HOST["identity"])
    row = args["expected_records"][run]
    row["host_identity"] = deepcopy(HOST)
    row["process_observation"]["host_identity"] = deepcopy(HOST)
    row["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": endpoint}
    (registry.root / (run + ".json")).write_bytes(run_owners._encode(row))
  plan = dsh_stop.preview_stop(ws, selected_runs=runs[:2])["plan"]
  assert plan["readiness"] == "ready"
  return ws, registry, args, runs, plan


def execute(fresh, **kwargs):
  return client.execute_stop(fresh[0], expected_plan=fresh[4], approve=kwargs.pop("approve", lambda _: True),
    wait_seconds=kwargs.pop("wait_seconds", 1), **kwargs)


def inbox_for(value, run=None):
  ws, registry, args, runs, plan = value
  return StopInbox(ws.state_root / "stop-inboxes" / (run or runs[0]), ws.binding)


def metadata(ws):
  return {p.relative_to(ws.state_root): p.read_bytes() for p in ws.state_root.rglob("*") if p.is_file()}


def test_publish_is_owner_serialized_with_cancel_and_posts_only_once(accepted, clock, monkeypatch):
  ws, registry, args, runs, plan = accepted
  original = StopInbox.submit
  calls = []
  def submit(inbox, value, **kwargs):
    calls.append(value)
    with pytest.raises(Conflict):
      with registry._locked(nonblocking=True): pass
    with pytest.raises(Conflict):
      completion.close_stop(ws, batch_id=args["batch_id"], plan_id=plan["plan_id"], reason="cancelled")
    return original(inbox, value, **kwargs)
  monkeypatch.setattr(StopInbox, "submit", submit)
  row = registry.snapshot()[runs[0]]
  monkeypatch.setattr(dsh_stop_control, "available_locked", _REAL_AVAILABLE)
  monkeypatch.setattr(run_owners, "observed_process_identity", lambda pid: deepcopy(MANAGER if pid == MANAGER["pid"] else HOST["identity"]))
  assert dsh_stop_control.available(ws, row) is True
  client.publish_request(ws, request(accepted), expected_record=row)
  # 实际 available_locked 在请求存在后拒绝，不替换这项单次判断。
  with pytest.raises(Conflict): client.publish_request(ws, request(accepted), expected_record=row)
  assert len(calls) == 1 and len(inbox_for(accepted).pending(expected=inbox_for(accepted).describe())) == 1
  with pytest.raises(Conflict):
    completion.close_stop(ws, batch_id=args["batch_id"], plan_id=plan["plan_id"], reason="cancelled")


def test_close_marker_blocks_publication_even_with_fence_present(accepted, clock, monkeypatch):
  ws, registry, args, runs, plan = accepted
  original = Tree.replace
  def replace(tree, name, data, **kwargs):
    if data is None: raise OSError("synthetic-private-canary")
    return original(tree, name, data, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict): completion.close_stop(ws, batch_id=args["batch_id"], plan_id=plan["plan_id"], reason="cancelled")
  assert run_stop_fence.read(registry) is not None
  assert completion.read_close(registry, args["batch_id"]) is not None
  with pytest.raises(Conflict): client.publish_request(ws, request(accepted), expected_record=registry.snapshot()[runs[0]])
  assert inbox_for(accepted).pending(expected=inbox_for(accepted).describe()) == []


@pytest.mark.parametrize("fact", ["posted", "dispatch"])
def test_status_possible_dispatch_is_pending_not_exit_and_read_only(accepted, clock, fact):
  ws, registry, args, runs, plan = accepted
  inbox = inbox_for(accepted)
  inbox.submit(request(accepted), expected=inbox.describe())
  if fact == "dispatch": StopDispatches(ws.state_root / "stop-dispatches", ws.binding).begin(request(accepted))
  before = metadata(ws)
  result = client.status_stop(ws, batch_id=args["batch_id"])
  assert result["status"] == "pending" and result["protected"] is True
  assert result["close_reason"] is None
  row = next(row for row in result["targets"] if row["run_id"] == runs[0])
  assert row["lifecycle_state"] == "active"
  assert row["request"] == "posted"
  assert row["dispatch"] == ("unknown" if fact == "dispatch" else "not_observed")
  assert result["continue_status"] == "not_sent" and result["resource_coverage"] == "unknown"
  assert metadata(ws) == before


@pytest.mark.parametrize("cause", ["no-approve", "decline", "drift", "capture"])
def test_before_acceptance_failure_saves_no_snapshot(fresh, clock, monkeypatch, cause):
  ws, registry, args, runs, plan = fresh
  before = metadata(ws)
  approve = None if cause == "no-approve" else lambda _: cause != "decline"
  if cause == "drift":
    row = registry.snapshot()[runs[0]]; row["start_cwd"]["observed_at_ns"] += 1
    (registry.root / (runs[0] + ".json")).write_bytes(run_owners._encode(row))
    before = metadata(ws)
  if cause == "capture": clock.capture_error = Conflict("synthetic-private-canary")
  with pytest.raises(Conflict): execute(fresh, approve=approve)
  assert metadata(ws) == before and run_stop_fence.read(registry) is None


def test_shared_deadline_two_selected_no_third_post_or_owner_change(fresh, clock, monkeypatch):
  ws, registry, args, runs, plan = fresh
  third = (registry.root / (runs[2] + ".json")).read_bytes()
  original = client.publish_request; posted = []
  def publish(workspace, value, **kwargs):
    posted.append(deepcopy(value))
    original(workspace, value, **kwargs)
    clock.now += 0.6
  monkeypatch.setattr(client, "publish_request", publish)
  result = execute(fresh)
  assert result["status"] == "pending" and result["protected"] is True
  assert len(posted) == 2 and len({item["deadline_ns"] for item in posted}) == 1
  assert {item["run_id"] for item in posted} == set(runs[:2])
  assert not (ws.state_root / "stop-inboxes" / runs[2]).exists()
  assert (registry.root / (runs[2] + ".json")).read_bytes() == third
  assert clock.now == 1.2 and not clock.sleeps
  assert len(clock.closed) == 2


def test_owner_idle_but_manager_alive_does_not_close(fresh, clock, monkeypatch):
  ws, registry, args, runs, plan = fresh
  original = client.publish_request
  def publish(workspace, value, **kwargs):
    original(workspace, value, **kwargs)
    registry.finish_current(value["run_id"], MANAGER, run_owners.ReleaseObservation(value["run_id"], MANAGER, True, True))
  monkeypatch.setattr(client, "publish_request", publish)
  monkeypatch.setattr(completion, "close_stop", lambda *a, **kw: pytest.fail("alive manager cannot close"))
  result = execute(fresh)
  assert result["status"] == "pending" and result["protected"] is True
  assert all(row["lifecycle_state"] == "idle_confirmed" for row in result["targets"])
  assert clock.sleeps and len(clock.closed) == 2


@pytest.mark.parametrize("response_loss", [False, True])
def test_exit_closes_once_response_loss_does_not_retry(fresh, clock, monkeypatch, response_loss):
  ws, registry, args, runs, plan = fresh
  original_publish, original_close = client.publish_request, completion.close_stop
  calls = []
  clock.exited = True
  def publish(workspace, value, **kwargs):
    original_publish(workspace, value, **kwargs)
    registry.finish_current(value["run_id"], MANAGER, run_owners.ReleaseObservation(value["run_id"], MANAGER, True, True))
  def close(*a, **kw):
    calls.append(kw)
    value = original_close(*a, **kw)
    if response_loss: raise OSError("synthetic-private-canary")
    return value
  monkeypatch.setattr(client, "publish_request", publish)
  monkeypatch.setattr(completion, "close_stop", close)
  third = (registry.root / (runs[2] + ".json")).read_bytes()
  result = execute(fresh)
  assert result["status"] == "stopped" and result["protected"] is False
  assert result["close_reason"] == "stopped"
  assert len(calls) == 1 and len(clock.closed) == 2 and not clock.sleeps
  assert (registry.root / (runs[2] + ".json")).read_bytes() == third


def test_submit_response_loss_never_reposts_or_moves_to_next_target(fresh, clock, monkeypatch):
  ws, registry, args, runs, plan = fresh
  original = StopInbox.submit; calls = []
  def submit(inbox, value, **kwargs):
    calls.append(deepcopy(value))
    original(inbox, value, **kwargs)
    raise OSError("synthetic-private-canary")
  monkeypatch.setattr(StopInbox, "submit", submit)
  result = execute(fresh)
  assert result["status"] == "pending" and result["protected"] is True
  assert len(calls) == 1
  rows = {row["run_id"]: row for row in result["targets"]}
  assert rows[calls[0]["run_id"]]["request"] == "posted"
  assert sum(row["request"] == "posted" for row in rows.values()) == 1
  assert not clock.sleeps


@pytest.mark.parametrize("change", ["expired", "owner", "plan"])
def test_publish_rechecks_deadline_and_saved_owner_before_post(accepted, clock, change):
  ws, registry, args, runs, plan = accepted
  value = request(accepted); record = registry.snapshot()[runs[0]]
  if change == "expired": clock.now = 1
  elif change == "plan": value["plan_id"] = "f" * 64
  else:
    current = deepcopy(record); current["start_cwd"]["observed_at_ns"] += 1
    (registry.root / (runs[0] + ".json")).write_bytes(run_owners._encode(current))
  before = metadata(ws)
  with pytest.raises(Conflict): client.publish_request(ws, value, expected_record=record)
  assert metadata(ws) == before


@pytest.mark.parametrize("confirmation,display", [("confirmed", "historical"),
  ("historical", "historical"), ("unknown", "unknown")])
def test_status_preserves_saved_session_as_history_and_never_uses_new_current_target(fresh, clock, confirmation, display):
  ws, registry, args, runs, plan = fresh
  record = registry.snapshot()[runs[0]]
  record["session_observation"] = {"session": {"agent": "dsh", "backend": "managed",
    "native_home_ref": run_owners.native_home_key(record["native_home_ref"]), "native_ref": "saved-session"},
    "run_id": runs[0], "emitter_epoch": "synthetic-emitter", "sequence": 1,
    "confirmation": confirmation, "source": "synthetic-observer", "observed_at_ns": 3}
  record["session_cwd"] = {"path": str(ws.instance / "saved-project"), "source": "synthetic-observer",
    "confirmation": "historical", "observed_at_ns": 3}
  registry._validate_record(runs[0] + ".json", record)
  (registry.root / (runs[0] + ".json")).write_bytes(run_owners._encode(record))
  current_plan = dsh_stop.preview_stop(ws, selected_runs=runs[:2])["plan"]
  result = execute((*fresh[:4], current_plan))
  row = next(row for row in result["targets"] if row["run_id"] == runs[0])
  target = row["target"]
  assert target["session_status"] == display and target["session_ref"]["native_ref"] == "saved-session"
  assert target["session_cwd"] == record["session_cwd"] and target["start_cwd"] == record["start_cwd"]
  assert target["manager_identity"] == record["manager_identity"] and target["host_identity"] == record["host_identity"]
  assert target["deployed_identity"] == record["deployed_identity"]
  assert result["continue_status"] == "not_sent" and result["resource_coverage"] == "unknown"
  # 当前 owner 后来变成另一目标时，只降低当前观察，不能改写原人工参考快照。
  changed = deepcopy(record); changed["session_observation"]["session"]["native_ref"] = "new-current-session"
  (registry.root / (runs[0] + ".json")).write_bytes(run_owners._encode(changed))
  before = metadata(ws)
  again = client.status_stop(ws, batch_id=result["batch_id"])
  again_row = next(row for row in again["targets"] if row["run_id"] == runs[0])
  assert again_row["lifecycle_state"] == "unknown" and again_row["target"] == target
  target["session_ref"]["native_ref"] = "external-mutation"
  assert next(row for row in client.status_stop(ws, batch_id=result["batch_id"])["targets"]
    if row["run_id"] == runs[0])["target"]["session_ref"]["native_ref"] == "saved-session"
  assert metadata(ws) == before
