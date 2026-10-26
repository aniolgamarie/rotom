"""真实临时两 SH 与私人 owner 元数据；不启动宿主。"""
from copy import deepcopy
import os

import pytest

from agentcfg import deployment, dsh_stop_scope, lifecycle, run_owners, runtime, run_stop_fence
from agentcfg.backends import DshBackend
from agentcfg.storage import Conflict, Tree, instance_lock
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import MANAGER, observation


@pytest.fixture
def prepared(managed, tmp_path, monkeypatch):
  ws, lock, package, observed = managed
  monkeypatch.delattr(DshBackend, "runtime_guard")
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  with lifecycle.guard(ws, shared=True, create=False) as physical, Tree(ws.state_root) as state, instance_lock(state, shared=True) as state_fd:
    current = deployment.read_state(state)["current"]
    metadata = runtime.run_metadata(ws, current, runtime.decode(current["launch"], tmp_path, ()))
    runs = [registry.register_v2(MANAGER, metadata) for _ in range(3)]
    records = registry.snapshot()
    layout = dsh_stop_scope.inspect_deployment(ws, records[runs[0]], instance_fd=physical, state_fd=state_fd)
    args = dict(instance_fd=physical, state_fd=state_fd, expected_records=records,
      selected_runs=runs[:2], expected_layout=layout, batch_id="a" * 32, plan_id="b" * 64)
    yield ws, registry, args, runs


def invoke(prepared, **changes):
  ws, registry, args, runs = prepared
  return dsh_stop_scope.save_manual_snapshot(ws, **(args | changes))


def absent(prepared):
  ws, registry, args, runs = prepared
  assert run_stop_fence.read(registry) is None
  assert run_stop_fence.read_snapshot(registry, args["batch_id"]) is None


def test_selected_snapshot_and_locks(prepared):
  ws, registry, args, runs = prepared
  original = deepcopy(args)
  def before():
    assert_exclusive_busy(ws.instance)
    assert_exclusive_busy(ws.state_root / "instance.lock")
    with pytest.raises(Conflict):
      with registry._locked(nonblocking=True): pass
  assert invoke(prepared, before_publish=before) is None
  saved = run_stop_fence.read_snapshot(registry, args["batch_id"])
  assert saved["records"] == {run: original["expected_records"][run] for run in runs[:2]}
  assert saved["selected_runs"] == sorted(runs[:2])
  assert registry.snapshot() == original["expected_records"]
  assert args == original
  for run in runs[:2]:
    assert saved["records"][run]["session_cwd"] is None
    assert saved["records"][run]["session_observation"] is None
  os.fstat(args["instance_fd"]); os.fstat(args["state_fd"])


@pytest.mark.parametrize("damage", ["layout", "selected", "records", "float", "callback"])
def test_bad_inputs_no_publish(prepared, damage):
  ws, registry, args, runs = prepared
  changes = {}
  if damage == "layout": changes["expected_layout"] = args["expected_layout"] | {"extra": True}
  elif damage == "selected": changes["selected_runs"] = [runs[0], runs[0]]
  elif damage == "records": changes["expected_records"] = {}
  elif damage == "float": changes["expected_layout"] = {"canary": 1.0}
  else: changes["before_publish"] = False
  with pytest.raises(Conflict): invoke(prepared, **changes)
  absent(prepared)


@pytest.mark.parametrize("inside", [False, True])
def test_layout_drift_no_publish(prepared, monkeypatch, inside):
  ws, registry, args, runs = prepared
  real = dsh_stop_scope.inspect_deployment
  calls = []
  def inspect(*a, **kw):
    calls.append(1)
    if inside and len(calls) == 3: (ws.instance / "launch.mjs").write_text("private-canary")
    return real(*a, **kw)
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", inspect)
  if not inside: (ws.instance / "launch.mjs").write_text("private-canary")
  with pytest.raises(Conflict) as caught: invoke(prepared)
  assert "private-canary" not in str(caught.value)
  absent(prepared)


def test_new_owner_rejected(prepared):
  ws, registry, args, runs = prepared
  record = deepcopy(args["expected_records"][runs[0]])
  record["run_id"] = "f" * 32
  with registry._locked(nonblocking=True) as tree: registry._publish_record(tree, record)
  with pytest.raises(Conflict): invoke(prepared)
  absent(prepared)


@pytest.mark.parametrize("error", [KeyboardInterrupt(), ValueError("private-canary")])
def test_callback_failure_and_control(prepared, error):
  def fail(): raise error
  with pytest.raises(type(error) if isinstance(error, KeyboardInterrupt) else Conflict) as caught:
    invoke(prepared, before_publish=fail)
  if isinstance(error, KeyboardInterrupt): assert caught.value is error
  assert "private-canary" not in str(caught.value)
  absent(prepared)


def test_callback_changes_owner_cas(prepared):
  ws, registry, args, runs = prepared
  def change():
    path = registry.root / (runs[0] + ".json")
    value = deepcopy(args["expected_records"][runs[0]])
    value["start_cwd"] = "/changed"
    path.write_bytes(run_owners._encode(value))
  with pytest.raises(Conflict): invoke(prepared, before_publish=change)
  absent(prepared)


def test_closed_fd_before_open(prepared, monkeypatch):
  ws, registry, args, runs = prepared
  fd = os.dup(args["state_fd"]); os.close(fd)
  def forbidden(*a, **kw): pytest.fail("closed fd must fail before schema/Tree opens")
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", forbidden)
  with pytest.raises(Conflict): invoke(prepared, state_fd=fd)
  absent(prepared)


def test_response_lost_does_not_retry_or_clean(prepared, monkeypatch):
  ws, registry, args, runs = prepared
  original = Tree.write_new
  calls = []
  def write(tree, name, raw, *a, **kw):
    result = original(tree, name, raw, *a, **kw)
    if ".stop-snapshot-" in name:
      calls.append(name)
      raise OSError("private-canary")
    return result
  monkeypatch.setattr(Tree, "write_new", write)
  with pytest.raises(Conflict) as caught: invoke(prepared)
  assert "private-canary" not in str(caught.value)
  assert len(calls) == 1
  assert run_stop_fence.read(registry) is None
  assert run_stop_fence.read_snapshot(registry, args["batch_id"])["selected_runs"] == sorted(runs[:2])


def test_wrong_record_binding_rejected(prepared):
  ws, registry, args, runs = prepared
  records = deepcopy(args["expected_records"])
  records[runs[0]]["profile"] = "different"
  with pytest.raises(Conflict): invoke(prepared, expected_records=records)
  absent(prepared)


def test_inputs_frozen_before_trusted_callback(prepared):
  ws, registry, args, runs = prepared
  expected = deepcopy(args["expected_records"])
  def before():
    args["expected_records"].clear()
    args["selected_runs"].clear()
    args["expected_layout"].clear()
  invoke(prepared, before_publish=before)
  snapshot = run_stop_fence.read_snapshot(registry, args["batch_id"])
  assert snapshot["records"] == {run: expected[run] for run in runs[:2]}


def test_unselected_legacy_unknown_and_selected_history_preserved(prepared):
  ws, registry, args, runs = prepared
  historical = deepcopy(args["expected_records"][runs[1]])
  historical["session_cwd"] = {"path": "/synthetic-history", "source": "synthetic-event",
    "confirmation": "historical", "observed_at_ns": 2}
  historical["session_observation"] = {"session": {"agent": "dsh", "backend": "managed",
    "native_home_ref": run_owners.native_home_key(historical["native_home_ref"]), "native_ref": "synthetic-session"},
    "run_id": runs[1], "emitter_epoch": "synthetic-emitter", "sequence": 1,
    "confirmation": "historical", "source": "synthetic-event", "observed_at_ns": 2}
  legacy = {"schema_version": 1, "binding_digest": registry.binding_digest, "run_id": runs[2],
    "manager_identity": deepcopy(MANAGER), "session_ref": None, "state": "unknown",
    "affected_resources": ["instance", "runtime", "native-home"],
    "observation": {"kind": "manager_scope_ended", "observed_at_ns": 3, "coverage": "unknown"}}
  for record in (historical, legacy):
    (registry.root / (record["run_id"] + ".json")).write_bytes(run_owners._encode(record))
  args["expected_records"] = registry.snapshot()
  before = (registry.root / (runs[2] + ".json")).read_bytes()
  invoke(prepared)
  saved = run_stop_fence.read_snapshot(registry, args["batch_id"])
  assert saved["records"][runs[1]] == historical
  assert runs[2] not in saved["records"]
  assert (registry.root / (runs[2] + ".json")).read_bytes() == before
