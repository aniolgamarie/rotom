"""驻留核心的离线能力边界；假子进程不证明真实 Herdr/Agent 准入。"""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import stat
import struct
from types import SimpleNamespace

import pytest

from agentcfg import run_owners
from agentcfg.pane_records import ContainerStore
from agentcfg.restore_locations import LocationStore
from agentcfg.storage import Conflict, LockBusy, Tree, advisory_lock, ensure_private
from rotom import resident


MANAGER = {"pid": 100, "birth_id": "synthetic-parent"}
CHILD = {"pid": 200, "birth_id": "synthetic-child"}
RUN = "a" * 32
CODE = "b" * 64
REQUEST = "c" * 32
BATCH = "d" * 32
CONTAINER = "e" * 32


def terminal():
  return {"socket_path": "/tmp/synthetic-herdr.sock", "server_identity": [0, 1],
    "workspace_id": "workspace-a", "tab_id": "tab-a", "pane_id": "pane-a", "terminal_id": "terminal-a",
    "cwd": "/tmp/synthetic-work"}


def owner(state="idle_confirmed", coverage="complete", *, identity=CHILD, run_id=RUN):
  return {"schema_version": 2, "backend": "managed", "run_id": run_id, "manager_identity": deepcopy(identity),
    "lifecycle_state": state, "process_observation": {"kind": "complete_release", "coverage": coverage}}


class Child:
  pid = CHILD["pid"]
  code = None

  def poll(self):
    assert self.identity_observed, "birth identity must be captured before poll/reap"
    return self.code


class Listener:
  def bind(self, path):
    Path(path).write_bytes(b"fake endpoint; no native socket")

  def listen(self, backlog):
    pass

  def close(self):
    pass


@pytest.fixture
def core(tmp_path, monkeypatch):
  root = tmp_path / "pane"
  ensure_private(root)
  (root / "control.sock").write_bytes(b"fake endpoint")
  (root / "control.sock").chmod(0o600)
  store = ContainerStore(root, CONTAINER)
  workspace = SimpleNamespace(agent="pi", profile="pi-pro", local_path=tmp_path / "machine.toml",
    state_root=tmp_path / "state", binding={"machine": "synthetic", "local": str(tmp_path / "machine.toml"), "profile": "pi-pro"})
  events = []
  child = Child()
  child.identity_observed = False
  rows = {RUN: owner()}
  code = [CODE]
  verify = [True]
  real_endpoint_info = resident._endpoint_info
  def endpoint_info(path):
    value = real_endpoint_info(path)
    return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino, st_uid=value.st_uid,
      st_mode=stat.S_IFSOCK | stat.S_IMODE(value.st_mode))
  monkeypatch.setattr(resident, "_endpoint_info", endpoint_info)
  endpoint = endpoint_info(root)
  saved = store.create({"schema_version": 1, "container_id": CONTAINER, "generation": 1,
    "manager_identity": MANAGER, "terminal_ref": terminal(), "manager_code_identity": CODE,
    "control_protocol": 1, "endpoint_identity": {"path": str(root / "control.sock"), "device": endpoint.st_dev, "inode": endpoint.st_ino},
    "scope": {"local": str(workspace.local_path), "profile": workspace.profile, "agent": workspace.agent},
    "state": "parked", "run_id": RUN, "child_identity": None, "consumed_request_ids": [], "last_request_id": None})
  @contextmanager
  def observation(workspace):
    events.append("observation-enter")
    yield
    events.append("observation-exit")
  monkeypatch.setattr(resident, "observation_guard", observation)
  monkeypatch.setattr(run_owners.Registry, "snapshot", lambda registry: deepcopy(rows))
  def identity(pid):
    if pid == CHILD["pid"]:
      events.append("child-birth")
      child.identity_observed = True
      return deepcopy(CHILD)
    return deepcopy(MANAGER) if pid == MANAGER["pid"] else None
  monkeypatch.setattr(run_owners, "observed_process_identity", identity)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  def spawn(argv, **kwargs):
    assert not events or events[-1] != "observation-enter"
    events.append((argv, kwargs))
    return child
  def verify_terminal(ref):
    assert ref == terminal()
    return verify[0]
  launcher = resident._Resident(workspace, store, Listener(), saved, spawn, verify_terminal, lambda: code[0])
  return SimpleNamespace(launcher=launcher, workspace=workspace, store=store, child=child, events=events,
    rows=rows, code=code, verify=verify, spawn=spawn, endpoint_info=endpoint_info)


def request(core, *, changes=None):
  root = core.workspace.state_root / "restore-locations" / BATCH / RUN
  value = {"schema_version": 1, "request_id": REQUEST, "mode": "original",
    "scope": {**core.workspace.binding, "agent": core.workspace.agent}, "batch_id": BATCH, "run_id": RUN,
    "session_ref": {"agent": "pi", "backend": "managed", "native_home_ref": "synthetic-home", "native_ref": "synthetic-session"},
    "cwd": terminal()["cwd"], "deployment_digest": "f" * 64, "workflow_revision": 1,
    "workflow_digest": "0" * 64, "manager_code_identity": CODE, "terminal_ref": terminal(), "rotom_root": str(resident.ROOT)}
  value.update(changes or {})
  location = LocationStore(root)
  location.create(value)
  initial = location.read_receipt()
  location.transition(initial, {**initial, "phase": "dispatched"})
  wire = {"schema_version": 1, "container_id": CONTAINER, "generation": 1, "request_root": str(root)}
  return location, wire


def test_park_requires_full_release_instead_of_only_child_exit():
  record = {"schema_version": 2, "backend": "managed", "lifecycle_state": "idle_confirmed",
    "process_observation": {"kind": "complete_release", "coverage": "complete"}}
  assert resident._released(record)
  assert not resident._released({**record, "lifecycle_state": "unknown"})
  assert not resident._released({**record, "backend": "ssh"})
  assert not resident._released({key: value for key, value in record.items() if key != "backend"})
  assert not resident._released({**record, "process_observation": {"kind": "complete_release", "coverage": "unknown"}})


def test_start_inherits_same_terminal_without_input_or_held_observation(core, monkeypatch):
  monkeypatch.setenv("ROTOM_WORK_LAUNCH_V1", "synthetic-payload")
  monkeypatch.setenv("ROTOM_WORK_LAUNCH_V2", "synthetic-payload")
  monkeypatch.setenv("ROTOM_RESTORE_LAUNCH_V1", "synthetic-payload")
  core.launcher._start(["fixed-rotom-cli"])
  argv, kwargs = core.events[0]
  assert argv == ["fixed-rotom-cli"]
  assert kwargs["cwd"] == terminal()["cwd"] and kwargs["close_fds"] is True
  assert "stdin" not in kwargs and "stdout" not in kwargs and "stderr" not in kwargs
  assert not any(key in kwargs["env"] for key in resident._PAYLOADS)
  assert core.events[1] == "child-birth"
  assert core.store.read()["child_identity"] == CHILD


@pytest.mark.parametrize("state,coverage,count,expected", [
  ("idle_confirmed", "complete", 1, "parked"), ("idle_confirmed", "unknown", 1, "unknown"),
  ("active", "complete", 1, "unknown"), ("unknown", "complete", 1, "unknown"),
  ("idle_confirmed", "complete", 0, "unknown"), ("idle_confirmed", "complete", 2, "unknown"),
])
def test_child_exit_requires_unique_exact_birth_and_complete_release(core, state, coverage, count, expected):
  core.rows.clear()
  for number in range(count):
    run_id = f"{number:032x}"
    core.rows[run_id] = owner(state, coverage, run_id=run_id)
  core.launcher._start(["fixed-cli"])
  core.child.code = 0
  core.launcher._poll()
  assert core.store.read()["state"] == expected
  if expected == "parked":
    assert core.store.read()["child_identity"] is None
  assert core.events[-2:] == ["observation-enter", "observation-exit"]


def test_reused_pid_or_unobserved_birth_never_parks(core, monkeypatch):
  monkeypatch.setattr(run_owners, "observed_process_identity", lambda pid: None if pid == CHILD["pid"] else MANAGER)
  core.launcher._start(["fixed-cli"])
  core.child.identity_observed = True
  core.child.code = 0
  core.launcher._poll()
  assert core.store.read()["state"] == "unknown"


def test_active_child_never_reads_owner_or_coordination_domain(core, monkeypatch):
  core.launcher._start(["fixed-cli"])
  monkeypatch.setattr(resident, "observation_guard", lambda ws: pytest.fail("live child must not compete for launch metadata"))
  monkeypatch.setattr(run_owners.Registry, "snapshot", lambda registry: pytest.fail("live child must not poll owner records"))
  core.launcher._poll()
  core.launcher._poll()
  assert core.launcher.child is core.child and core.store.read()["state"] == "running"
  assert core.store.read()["run_id"] is None and core.store.read()["child_identity"] == CHILD


def test_physical_lease_busy_defers_exit_observation_without_losing_child(core, monkeypatch):
  core.launcher._start(["fixed-cli"])
  core.child.code = 0
  @contextmanager
  def busy(workspace):
    raise LockBusy("synthetic maintenance EX")
    yield
  monkeypatch.setattr(resident, "observation_guard", busy)
  core.launcher._poll()
  core.launcher._poll()
  assert core.launcher.child is core.child
  assert core.store.read()["state"] == "parking"
  @contextmanager
  def released(workspace):
    yield
  monkeypatch.setattr(resident, "observation_guard", released)
  core.child.code = 0
  core.launcher._poll()
  assert core.store.read()["state"] == "parked"
  assert core.launcher.child is None


def test_physical_identity_conflict_stays_unknown(core, monkeypatch):
  core.launcher._start(["fixed-cli"])
  core.child.code = 0
  @contextmanager
  def changed(workspace):
    raise Conflict("synthetic wrong inode or owner")
    yield
  monkeypatch.setattr(resident, "observation_guard", changed)
  core.launcher._poll()
  assert core.store.read()["state"] == "unknown"
  assert core.launcher.child is None


def test_real_physical_lock_contention_is_typed_and_does_not_hide_other_errors(tmp_path, monkeypatch):
  import errno
  import fcntl
  target = tmp_path / "physical.lock"
  target.touch(mode=0o600)
  with target.open("rb") as holder, target.open("rb") as observer:
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(LockBusy):
      with advisory_lock(observer.fileno(), shared=True):
        pytest.fail("cannot acquire SH while EX is held")
    def invalid(*args):
      raise OSError(errno.EBADF, "synthetic invalid descriptor")
    monkeypatch.setattr(fcntl, "flock", invalid)
    with pytest.raises(Conflict) as error:
      with advisory_lock(observer.fileno(), shared=True):
        pytest.fail("invalid descriptor must fail closed")
    assert not isinstance(error.value, LockBusy)


def test_original_request_is_consumed_before_handoff_and_fixed_child_spawn(core):
  location, wire = request(core)
  def spawn(argv, **kwargs):
    assert core.store.read()["consumed_request_ids"] == [REQUEST]
    assert location.read_receipt()["phase"] == "handoff"
    return core.spawn(argv, **kwargs)
  core.launcher.spawn = spawn
  assert core.launcher._request(wire) == {"status": "accepted", "request_id": REQUEST}
  assert core.events[0][0] == [str(resident.ROOT / ".venv/bin/python"), "-B", str(resident.ROOT / "src/rotom/restore_child.py"),
    "--request-root", wire["request_root"]]
  assert core.store.read()["last_request_id"] == REQUEST
  assert core.launcher._request(wire)["status"] == "busy"
  core.child.code = 0
  core.launcher._poll()
  assert core.store.read()["state"] == "parked"
  assert core.launcher._request(wire)["status"] == "rejected"
  assert sum(isinstance(event, tuple) for event in core.events) == 1


def test_delayed_request_for_prior_run_is_rejected_before_consumption(core):
  location, wire = request(core)
  core.launcher._save(run_id="f" * 32)
  assert core.launcher._request(wire)["status"] == "rejected"
  assert core.store.read()["consumed_request_ids"] == []
  assert core.store.read()["run_id"] == "f" * 32
  assert location.read_receipt()["phase"] == "dispatched"
  assert not any(isinstance(event, tuple) for event in core.events)


@pytest.mark.parametrize("changed", ["code", "pane", "manager", "endpoint", "generation", "root", "scope", "mode", "terminal", "receipt", "request-code", "request-root", "batch"])
def test_mismatched_source_endpoint_scope_or_position_never_spawns(core, monkeypatch, changed):
  changes = {}
  if changed == "scope": changes["scope"] = {**core.workspace.binding, "agent": "pi", "profile": "pi-base"}
  if changed == "mode": changes["mode"] = "new-tab"
  if changed == "terminal": changes["terminal_ref"] = {**terminal(), "pane_id": "other"}
  if changed == "request-code": changes["manager_code_identity"] = "1" * 64
  if changed == "request-root": changes["rotom_root"] = "/tmp/other-source"
  if changed == "batch": changes["batch_id"] = "f" * 32
  location, wire = request(core, changes=changes)
  if changed == "code": core.code[0] = "1" * 64
  elif changed == "pane": core.verify[0] = False
  elif changed == "manager": monkeypatch.setattr(run_owners, "observed_process_identity", lambda pid: {**MANAGER, "birth_id": "reused"})
  elif changed == "endpoint": (core.store.root / "control.sock").chmod(0o644)
  elif changed == "generation": wire["generation"] = 2
  elif changed == "root": wire["request_root"] = str(core.workspace.state_root / "untrusted")
  elif changed == "receipt":
    receipt = location.read_receipt()
    location.transition(receipt, {**receipt, "phase": "unknown"})
  assert core.launcher._request(wire)["status"] == "rejected"
  assert core.store.read()["consumed_request_ids"] == []
  assert not any(isinstance(event, tuple) for event in core.events)


@pytest.mark.parametrize("failure", ["container-before", "container-after", "handoff-before", "handoff-after", "spawn"])
def test_consumption_or_handoff_ambiguity_is_unknown_and_never_replayed(core, monkeypatch, failure):
  location, wire = request(core)
  if failure.startswith("container"):
    original = ContainerStore.update
    def update(store, expected, replacement):
      if replacement["state"] == "resume_pending":
        if failure.endswith("after"): original(store, expected, replacement)
        raise Conflict("synthetic write uncertainty")
      return original(store, expected, replacement)
    monkeypatch.setattr(ContainerStore, "update", update)
  elif failure.startswith("handoff"):
    original = LocationStore.transition
    def transition(store, expected, replacement):
      if replacement["phase"] == "handoff":
        if failure.endswith("after"): original(store, expected, replacement)
        raise Conflict("synthetic write uncertainty")
      return original(store, expected, replacement)
    monkeypatch.setattr(LocationStore, "transition", transition)
  else:
    def spawn(*args, **kwargs):
      raise OSError("synthetic spawn uncertainty")
    core.launcher.spawn = spawn
  assert core.launcher._request(wire)["status"] == "unknown"
  assert core.store.read()["state"] == "unknown"
  assert core.launcher._request(wire)["status"] == "rejected"
  assert not any(isinstance(event, tuple) for event in core.events)


class Connection:
  def __init__(self, data, uid=None, lost=False):
    self.data, self.uid, self.lost = data, os.geteuid() if uid is None else uid, lost
    self.reply = None

  def settimeout(self, value):
    assert 0 < value <= 2

  def getsockopt(self, *args):
    return struct.pack("3i", 1, self.uid, 1)

  def recv(self, size):
    result, self.data = self.data[:size], self.data[size:]
    return result

  def sendall(self, data):
    self.reply = json.loads(data)
    if self.lost:
      raise OSError("synthetic response loss")


@pytest.mark.parametrize("damage", ["uid", "duplicate", "unknown", "bool", "float", "huge", "extra-line", "json"])
def test_control_protocol_is_bounded_same_uid_and_strict(core, damage):
  location, wire = request(core)
  data = json.dumps(wire).encode() + b"\n"
  uid = None
  if damage == "uid": uid = os.geteuid() + 1
  elif damage == "duplicate": data = b'{"generation":1,' + data[1:]
  elif damage == "unknown": data = json.dumps({**wire, "argv": ["not-allowed"]}).encode()
  elif damage == "bool": data = json.dumps({**wire, "generation": True}).encode()
  elif damage == "float": data = json.dumps({**wire, "generation": 1.0}).encode()
  elif damage == "huge": data = b"x" * 8193
  elif damage == "extra-line": data += b"{}\n"
  elif damage == "json": data = b"{broken\n"
  connection = Connection(data, uid)
  core.launcher._connection(connection)
  assert connection.reply["status"] == "rejected"
  assert core.store.read()["consumed_request_ids"] == []


def test_response_loss_does_not_authorize_repeat_spawn(core):
  location, wire = request(core)
  connection = Connection(json.dumps(wire).encode() + b"\n", lost=True)
  core.launcher._connection(connection)
  assert connection.reply["status"] == "accepted"
  core.child.code = 0
  core.launcher._poll()
  core.launcher._connection(Connection(json.dumps(wire).encode() + b"\n"))
  assert sum(isinstance(event, tuple) for event in core.events) == 1


def test_sigint_never_forwards_or_kills_and_only_parked_launcher_closes(core, monkeypatch):
  core.launcher._start(["fixed-cli"])
  assert core.launcher._interrupt(signal.SIGINT, None) is None
  core.child.code = 0
  core.launcher._poll()
  with pytest.raises(resident._Close):
    core.launcher._interrupt(signal.SIGINT, None)


def test_event_loop_initial_argv_and_parked_close(core, monkeypatch):
  def stop(*args):
    raise resident._Close()
  core.child.code = 0
  monkeypatch.setattr(resident.select, "select", stop)
  assert core.launcher.run(0.05) == 0
  assert core.store.read()["state"] == "closed"
  assert core.events[0][0] == [str(resident.ROOT / "rotom"), "--no-input", "run", "pi", "--local",
    str(core.workspace.local_path), "--profile", "pi-pro", "--cwd", terminal()["cwd"]]


def test_overlong_unix_control_path_never_spawns(core):
  root = core.workspace.state_root / ("x" * 108)
  assert resident.run_resident(core.workspace, terminal(), store_root=root, spawn=core.spawn,
    verify_terminal=lambda reference: True, code_identity=lambda: CODE) == 4
  assert not root.exists()
  assert not any(isinstance(event, tuple) for event in core.events)


def test_public_api_uses_fake_socket_and_does_not_hold_runtime_leases(core, tmp_path, monkeypatch):
  root = tmp_path / "new-pane"
  monkeypatch.setattr(resident.socket, "socket", lambda *args: Listener())
  def stop(*args):
    raise resident._Close()
  monkeypatch.setattr(resident.select, "select", stop)
  core.child.code = 0
  assert resident.run_resident(core.workspace, terminal(), store_root=root, spawn=core.spawn,
    verify_terminal=lambda reference: True, code_identity=lambda: CODE) == 0
  saved = json.loads((root / "container.json").read_bytes())
  assert saved["state"] == "closed" and saved["child_identity"] is None
  assert (root / "control.sock").stat().st_mode & 0o777 == 0o600


def test_ordinary_run_keeps_native_exit_and_never_invokes_resident(monkeypatch):
  from agentcfg import cli as legacy
  from rotom import cli
  calls = []
  def forbidden(*args, **kwargs):
    pytest.fail("ordinary run must never enable resident mode")
  monkeypatch.setattr(resident, "run_resident", forbidden)
  monkeypatch.setattr(legacy, "main", lambda argv, **kwargs: calls.append(argv) or 17)
  assert cli.main(["--no-input", "run", "pi", "--profile", "pi-pro"]) == 17
  assert "run" in calls[0] and "pi-pro" in calls[0]


def test_non_tty_never_reads_or_flushes_terminal_attributes(core, monkeypatch):
  def forbidden(*args, **kwargs):
    pytest.fail("non-TTY resident must not touch termios")
  assert core.launcher.tty_fd is None
  monkeypatch.setattr(resident.termios, "tcgetattr", forbidden)
  monkeypatch.setattr(resident.termios, "tcflush", forbidden)
  monkeypatch.setattr(resident.termios, "tcsetattr", forbidden)
  core.launcher._start(["fixed-cli"])
  core.child.code = 0
  core.launcher._poll()
  assert core.store.read()["state"] == "parked"


def test_tty_pending_keys_are_discarded_before_spawn_and_attributes_restored_after_exit(core, monkeypatch):
  events = []
  core.launcher.tty_fd = 9
  core.launcher.tty_attributes = ["synthetic-original-attributes"]
  monkeypatch.setattr(resident.termios, "tcflush", lambda fd, mode: events.append(("flush", fd, mode)))
  monkeypatch.setattr(resident.termios, "tcsetattr", lambda fd, mode, value: events.append(("restore", fd, mode, value)))
  def spawn(*args, **kwargs):
    assert events == [("flush", 9, resident.termios.TCIFLUSH)]
    return core.spawn(*args, **kwargs)
  core.launcher.spawn = spawn
  core.launcher._start(["fixed-cli"])
  core.child.code = 0
  core.launcher._poll()
  assert events[-1] == ("restore", 9, resident.termios.TCSANOW, ["synthetic-original-attributes"])


@pytest.mark.parametrize("cwd", [None, "/tmp/other-directory"])
def test_live_terminal_verification_requires_all_ids_but_cwd_is_optional(monkeypatch, cwd):
  from termcfg import herdr
  calls = []
  class Client:
    def __init__(self, path, deadline, expected_identity):
      assert path == terminal()["socket_path"] and expected_identity == terminal()["server_identity"]
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def request(self, method, params):
      calls.append((method, params))
      pane = {key: terminal()[key] for key in resident._IDS}
      if cwd is not None: pane["foreground_cwd"] = cwd
      return {"pane": pane}
  monkeypatch.setattr(herdr, "HerdrClient", Client)
  if cwd is None:
    assert resident._verify_terminal(terminal()) is True
  else:
    with pytest.raises(Conflict): resident._verify_terminal(terminal())
  assert calls == [("pane.get", {"pane_id": "pane-a"})]


@pytest.mark.parametrize("damage", [None, "duplicate", "unknown", "pane", "cwd", "bool"])
def test_main_uses_explicit_terminal_reference_without_default_termcfg_scope(core, monkeypatch, damage):
  from agentcfg import workspace
  from termcfg import work_config
  monkeypatch.setattr(workspace, "load_workspace", lambda *args, **kwargs: pytest.fail("resident must not retain full credential workspace"))
  monkeypatch.setattr(workspace, "load_instance_workspaces", lambda *args, **kwargs: (core.workspace,))
  monkeypatch.setattr(work_config, "read_settings", lambda *args, **kwargs: pytest.fail("do not guess default Herdr scope"))
  monkeypatch.setenv("HERDR_PANE_ID", terminal()["pane_id"])
  calls = []
  monkeypatch.setattr(resident, "_verify_terminal", lambda ref: calls.append(ref) or True)
  monkeypatch.setattr(resident, "run_resident", lambda ws, ref, **kwargs: 19)
  value = terminal()
  if damage == "unknown": value["argv"] = ["not-allowed"]
  elif damage == "pane": value["pane_id"] = "other"
  elif damage == "cwd": value["cwd"] = "/tmp/other"
  elif damage == "bool": value["server_identity"] = [False, 1]
  text = json.dumps(value)
  if damage == "duplicate": text = '{"pane_id":"pane-a",' + text[1:]
  result = resident.main(["--local", str(core.workspace.local_path), "--profile", "pi-pro",
    "--cwd", terminal()["cwd"], "--terminal-ref", text])
  assert result == (19 if damage is None else 4)
  assert bool(calls) == (damage is None)


def test_resident_rejects_full_workspace_before_parking_or_spawning(core, tmp_path):
  core.workspace.secret_store = object()
  destination = tmp_path / "must-not-create"
  assert resident.run_resident(core.workspace, terminal(), store_root=destination,
    spawn=lambda *args, **kwargs: pytest.fail("credential workspace spawned")) == 4
  assert not destination.exists()


def new_tab_request(core):
  location, wire = request(core, changes={"mode": "new-tab", "terminal_ref": None})
  receipt = location.read_receipt()
  receipt = location.transition(receipt, {**receipt, "phase": "ready", "terminal_ref": terminal()})
  receipt = location.transition(receipt, {**receipt, "phase": "committed"})
  location.transition(receipt, {**receipt, "phase": "handoff"})
  return location, wire


def test_new_tab_handoff_initial_spawn_is_fixed_child_and_then_parks(core, monkeypatch):
  location, wire = new_tab_request(core)
  core.child.code = 0
  def stop(*args):
    raise resident._Close()
  monkeypatch.setattr(resident.select, "select", stop)
  assert core.launcher.run(0.05, Path(wire["request_root"])) == 0
  assert core.events[0][0] == [str(resident.ROOT / ".venv/bin/python"), "-B",
    str(resident.ROOT / "src/rotom/restore_child.py"), "--request-root", wire["request_root"]]
  assert core.store.read()["state"] == "closed"
  assert core.store.read()["consumed_request_ids"] == []
  assert location.read_receipt()["phase"] == "handoff"


@pytest.mark.parametrize("damage", ["original", "phase", "scope", "terminal", "source", "root"])
def test_new_tab_initial_handoff_requires_exact_scope_phase_and_terminal(core, monkeypatch, damage):
  location, wire = new_tab_request(core)
  if damage == "original":
    value = location.read_request()
    value.update(mode="original", terminal_ref=terminal())
    (location.root / "request.json").write_bytes(run_owners._encode(value))
  elif damage == "phase":
    receipt = location.read_receipt()
    location.transition(receipt, {**receipt, "phase": "executing"})
  elif damage in ("scope", "source"):
    value = location.read_request()
    if damage == "scope": value["scope"]["profile"] = "pi-base"
    else: value["manager_code_identity"] = "1" * 64
    (location.root / "request.json").write_bytes(run_owners._encode(value))
  elif damage == "terminal":
    value = location.read_receipt()
    value["terminal_ref"]["pane_id"] = "other"
    (location.root / "receipt.json").write_bytes(run_owners._encode(value))
  elif damage == "root": wire["request_root"] = str(core.workspace.state_root / "outside")
  assert core.launcher.run(0.05, Path(wire["request_root"])) == 4
  assert core.store.read()["state"] == "unknown"
  assert not any(isinstance(event, tuple) for event in core.events)


def test_terminal_setup_failure_after_container_publication_is_unknown(core, tmp_path, monkeypatch):
  root = tmp_path / "new-pane"
  monkeypatch.setattr(resident.socket, "socket", lambda *args: Listener())
  monkeypatch.setattr(resident, "_tty_fd", lambda: 9)
  def fail(fd):
    raise resident.termios.error("synthetic terminal setup failure")
  monkeypatch.setattr(resident.termios, "tcgetattr", fail)
  assert resident.run_resident(core.workspace, terminal(), store_root=root, spawn=core.spawn,
    verify_terminal=lambda ref: True, code_identity=lambda: CODE) == 4
  assert json.loads((root / "container.json").read_bytes())["state"] == "unknown"
  assert not any(isinstance(event, tuple) for event in core.events)
