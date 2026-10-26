"""已保存人工快照的当前目标关联；两 SH、假身份，无宿主或控制动作。"""
from copy import deepcopy
import json
import os

import pytest

from agentcfg import dsh_stop_scope, run_owners, run_stop_fence
from agentcfg.storage import Conflict
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import MANAGER, observation


HOST = {"identity": {"pid": MANAGER["pid"] + 1, "birth_id": "synthetic-host"},
  "manager_identity": MANAGER, "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}


def publish(prepared, monkeypatch, *, known_host=True):
  ws, registry, args, runs = prepared
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  for run in runs[:2]:
    record = args["expected_records"][run]
    record["host_identity"] = deepcopy(HOST) if known_host else None
    record["process_observation"]["host_identity"] = deepcopy(record["host_identity"])
    registry._validate_record(run + ".json", record)
    (registry.root / (run + ".json")).write_bytes(run_owners._encode(record))
  dsh_stop_scope.save_manual_snapshot(ws, **args)
  request = {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop", "request_id": "d" * 32,
    "batch_id": args["batch_id"], "plan_id": args["plan_id"], "run_id": runs[1],
    "manager_identity": deepcopy(MANAGER), "host_identity": deepcopy(HOST["identity"]), "deadline_ns": 1}
  return ws, registry, args, runs, request


@pytest.fixture
def saved(prepared, monkeypatch):
  return publish(prepared, monkeypatch)


def inspect(saved, **changes):
  ws, registry, args, runs, request = saved
  return dsh_stop_scope.inspect_stop_request(ws, changes.pop("request", request),
    **({"instance_fd": args["instance_fd"], "state_fd": args["state_fd"],
      "expected_layout": args["expected_layout"]} | changes))


def metadata(saved):
  ws, registry, args, runs, request = saved
  return {path.relative_to(ws.state_root): (path.read_bytes(), path.stat().st_mode)
    for path in ws.state_root.rglob("*") if path.is_file()}


def files(saved):
  ws, registry, args, runs, request = saved
  return (registry.root / (request["run_id"] + ".json"),
    registry.root.parent / run_stop_fence._name(registry),
    registry.root.parent / run_stop_fence._snapshot_name(registry, args["batch_id"]))


def write(path, value):
  path.write_bytes(run_owners._encode(value))


def test_known_host_unknown_session_returns_detached_without_writes(saved, monkeypatch):
  ws, registry, args, runs, request = saved
  before = metadata(saved)
  def forbidden(*a, **kw): pytest.fail("query cannot signal")
  monkeypatch.setattr(os, "kill", forbidden)
  original = dsh_stop_scope.inspect_deployment
  def checked(*a, **kw):
    # 布局复核必须仍处于同一 owner 短锁，两把借入 SH 仍由调用方持有。
    with pytest.raises(Conflict):
      with registry._locked(nonblocking=True): pass
    assert_exclusive_busy(ws.instance)
    assert_exclusive_busy(ws.state_root / "instance.lock")
    return original(*a, **kw)
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", checked)
  result = inspect(saved)
  assert result == args["expected_records"][request["run_id"]]
  assert result["session_observation"] is None and result["session_cwd"] is None
  result["host_identity"]["identity"]["birth_id"] = "external-change"
  assert inspect(saved) == args["expected_records"][request["run_id"]]
  assert metadata(saved) == before
  os.fstat(args["instance_fd"]); os.fstat(args["state_fd"])
  assert_exclusive_busy(ws.instance)
  assert_exclusive_busy(ws.state_root / "instance.lock")


@pytest.mark.parametrize("field,value", [("batch_id", "e" * 32), ("plan_id", "e" * 64),
  ("run_id", "f" * 32), ("manager_identity", {"pid": MANAGER["pid"], "birth_id": "different"}),
  ("host_identity", {"pid": HOST["identity"]["pid"], "birth_id": "different"})])
def test_request_does_not_match_saved_target(saved, field, value):
  request = deepcopy(saved[4]); request[field] = value
  before = metadata(saved)
  with pytest.raises(Conflict): inspect(saved, request=request)
  assert metadata(saved) == before


def test_unselected_existing_run_is_not_target(saved):
  request = deepcopy(saved[4]); request["run_id"] = saved[3][2]
  with pytest.raises(Conflict): inspect(saved, request=request)


def test_current_manager_must_be_same(saved, monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": MANAGER["pid"], "birth_id": "other"})
  with pytest.raises(Conflict): inspect(saved)


@pytest.mark.parametrize("damage", ["host-none", "unknown", "idle", "field", "missing"])
def test_current_owner_must_remain_exact_active_snapshot(saved, damage):
  owner, fence, snapshot = files(saved)
  record = json.loads(owner.read_bytes())
  if damage == "host-none":
    record["host_identity"] = record["process_observation"]["host_identity"] = None
  elif damage in ("unknown", "idle"):
    run_owners._set_state(record, "unknown" if damage == "unknown" else "idle_confirmed")
  elif damage == "field": record["start_cwd"]["path"] = "/changed"
  if damage == "missing": owner.unlink()
  else: write(owner, record)
  before = metadata(saved)
  with pytest.raises(Conflict): inspect(saved)
  assert metadata(saved) == before


@pytest.mark.parametrize("damage", ["v1", "orphan", "missing-snapshot", "corrupt-fence", "corrupt-snapshot", "digest"])
def test_requires_complete_v2_link(saved, damage):
  owner, fence, snapshot = files(saved)
  if damage == "v1":
    value = json.loads(fence.read_bytes()); value["schema_version"] = 1; del value["snapshot_digest"]
    write(fence, value)
  elif damage == "orphan": fence.unlink()
  elif damage == "missing-snapshot": snapshot.unlink()
  elif damage == "digest":
    value = json.loads(fence.read_bytes()); value["snapshot_digest"] = "0" * 64; write(fence, value)
  else: (fence if damage == "corrupt-fence" else snapshot).write_bytes(b"private-canary")
  before = metadata(saved)
  with pytest.raises(Conflict) as caught: inspect(saved)
  assert "private-canary" not in str(caught.value)
  assert metadata(saved) == before


def test_owner_nb_lock_busy(saved):
  registry = saved[1]
  with registry._locked(nonblocking=True):
    with pytest.raises(Conflict): inspect(saved)


def test_layout_drift_and_wrong_expected_layout(saved):
  with pytest.raises(Conflict): inspect(saved, expected_layout=saved[2]["expected_layout"] | {"extra": 1})
  (saved[0].instance / "launch.mjs").write_bytes(b"private-canary")
  with pytest.raises(Conflict) as caught: inspect(saved)
  assert "private-canary" not in str(caught.value)


@pytest.mark.parametrize("name", ["instance_fd", "state_fd"])
def test_closed_fd_rejected_before_tree(saved, monkeypatch, name):
  fd = os.dup(saved[2][name]); os.close(fd)
  def forbidden(*a, **kw): pytest.fail("closed fd must fail before Tree opens")
  monkeypatch.setattr(dsh_stop_scope, "Tree", forbidden)
  with pytest.raises(Conflict): inspect(saved, **{name: fd})


@pytest.mark.parametrize("changed", ["owner", "fence", "snapshot"])
@pytest.mark.parametrize("replace", [False, True], ids=["content", "same-content-new-inode"])
def test_link_or_owner_changes_during_deployment_check(saved, monkeypatch, changed, replace):
  owner, fence, snapshot = files(saved)
  original = dsh_stop_scope.inspect_deployment
  def check(*a, **kw):
    result = original(*a, **kw)
    path = {"owner": owner, "fence": fence, "snapshot": snapshot}[changed]
    value = json.loads(path.read_bytes())
    if replace:
      path.rename(saved[0].instance / ("synthetic-old-" + changed))
      write(path, value); path.chmod(0o600)
    else:
      if changed == "owner": value["start_cwd"]["path"] = "/changed"
      else: value["plan_id"] = "f" * 64
      write(path, value)
    return result
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", check)
  with pytest.raises(Conflict): inspect(saved)


def test_other_selected_owner_can_already_be_idle(saved):
  ws, registry, args, runs, request = saved
  registry.finish_current(runs[0], MANAGER, run_owners.ReleaseObservation(runs[0], deepcopy(MANAGER), True, True))
  before = metadata(saved)
  assert inspect(saved) == args["expected_records"][runs[1]]
  assert metadata(saved) == before


@pytest.mark.parametrize("error", [ValueError("private-canary"), KeyboardInterrupt(), SystemExit(7)])
def test_errors_sanitized_controls_original(saved, monkeypatch, error):
  def fail(*a, **kw): raise error
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", fail)
  before = metadata(saved)
  with pytest.raises(Conflict if isinstance(error, Exception) else type(error)) as caught: inspect(saved)
  if not isinstance(error, Exception): assert caught.value is error
  assert "private-canary" not in str(caught.value)
  assert metadata(saved) == before


def test_saved_unknown_host_never_becomes_control_target(prepared, monkeypatch):
  saved = publish(prepared, monkeypatch, known_host=False)
  before = metadata(saved)
  with pytest.raises(Conflict): inspect(saved)
  assert metadata(saved) == before


def test_saved_historical_session_stays_historical(prepared, monkeypatch):
  ws, registry, args, runs = prepared
  record = args["expected_records"][runs[1]]
  record["session_cwd"] = {"path": "/synthetic-historical-cwd", "source": "synthetic-event",
    "confirmation": "historical", "observed_at_ns": 2}
  record["session_observation"] = {"session": {"agent": "dsh", "backend": "managed",
    "native_home_ref": run_owners.native_home_key(record["native_home_ref"]), "native_ref": "synthetic-session"},
    "run_id": runs[1], "emitter_epoch": "synthetic-emitter", "sequence": 1,
    "confirmation": "historical", "source": "synthetic-event", "observed_at_ns": 2}
  saved = publish(prepared, monkeypatch)
  result = inspect(saved)
  assert result == record
  assert result["session_cwd"]["confirmation"] == result["session_observation"]["confirmation"] == "historical"
