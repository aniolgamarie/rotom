"""容器记录 codec 与私人 CAS；无宿主、终端或现场能力推断。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import subprocess

import pytest

from agentcfg.pane_records import ContainerStore
from agentcfg import pane_records, storage
from agentcfg.storage import Conflict, StateError, Tree


CONTAINER = "a" * 32
RUN = "b" * 32
REQUEST = "c" * 32


def record():
  return {"schema_version": 1, "container_id": CONTAINER, "generation": 1,
    "manager_identity": {"pid": 123, "birth_id": "synthetic-manager"},
    "terminal_ref": {"socket_path": "/tmp/synthetic-herdr.sock", "server_identity": [0, 2],
      "workspace_id": "workspace-a", "tab_id": "tab-a", "pane_id": "pane-a", "terminal_id": "terminal-a",
      "cwd": "/tmp/synthetic-cwd"},
    "manager_code_identity": "d" * 64, "control_protocol": 1,
    "endpoint_identity": {"path": "/tmp/synthetic-control.sock", "device": 0, "inode": 3},
    "scope": {"local": "/tmp/synthetic-machine.toml", "profile": "pi-pro", "agent": "pi"},
    "state": "running", "run_id": RUN, "child_identity": {"pid": 456, "birth_id": "synthetic-child"},
    "consumed_request_ids": [], "last_request_id": None}


@pytest.fixture
def store(tmp_path):
  return ContainerStore(tmp_path / "containers" / CONTAINER, CONTAINER)


def test_read_absent_does_not_create_root(store):
  assert store.read() is None
  assert not store.root.exists()


def test_create_roundtrip_and_update_are_private_detached_cas(store):
  original = record()
  saved = store.create(original)
  assert saved == original == store.read()
  assert store.root.stat().st_mode & 0o777 == 0o700
  assert (store.root / "container.json").stat().st_mode & 0o777 == 0o600
  original["manager_identity"]["birth_id"] = "changed-in-caller"
  assert store.read()["manager_identity"]["birth_id"] == "synthetic-manager"
  replacement = deepcopy(saved)
  replacement.update(state="parked", child_identity=None)
  assert store.update(saved, replacement) == replacement == store.read()
  with pytest.raises(Conflict):
    store.update(saved, replacement)
  with pytest.raises(Conflict):
    store.create(record())
  assert store.read() == replacement


def changed(path, value):
  result = record()
  target = result
  for part in path[:-1]:
    target = target[part]
  target[path[-1]] = value
  return result


@pytest.mark.parametrize("path,value", [
  (("schema_version",), True), (("schema_version",), 2), (("generation",), False),
  (("generation",), 0), (("generation",), 1.0), (("generation",), 2 ** 64),
  (("container_id",), "e" * 32), (("run_id",), "B" * 32), (("state",), "ready"),
  (("manager_code_identity",), "d" * 63), (("control_protocol",), True), (("control_protocol",), 2),
  (("manager_identity", "pid"), True), (("manager_identity", "pid"), -1),
  (("manager_identity", "birth_id"), ""), (("manager_identity", "birth_id"), "x" * 256),
  (("manager_identity", "birth_id"), "synthetic\0secret"), (("manager_identity", "extra"), "synthetic-secret"),
  (("terminal_ref", "server_identity"), [0, True]), (("terminal_ref", "server_identity"), [0, -1]),
  (("terminal_ref", "server_identity"), [0, 2 ** 64]), (("terminal_ref", "server_identity"), [0]),
  (("terminal_ref", "server_identity"), (0, 2)), (("terminal_ref", "pane_id"), ""),
  (("terminal_ref", "terminal_id"), "x" * 256), (("terminal_ref", "extra"), "synthetic-secret"),
  (("terminal_ref", "cwd"), "relative"), (("terminal_ref", "cwd"), "/tmp/../secret"),
  (("terminal_ref", "cwd"), "//tmp/secret"), (("terminal_ref", "cwd"), "/tmp/./secret"),
  (("terminal_ref", "socket_path"), "/" + "x" * 8192),
  (("endpoint_identity", "path"), "relative"), (("endpoint_identity", "inode"), 0),
  (("endpoint_identity", "device"), 0.0), (("endpoint_identity", "extra"), "synthetic-secret"),
  (("scope", "local"), "/tmp//secret"), (("scope", "profile"), "../secret"),
  (("scope", "profile"), "a\n"), (("scope", "agent"), "codex"),
  (("scope", "extra"), "synthetic-secret"), (("consumed_request_ids",), [REQUEST, REQUEST]),
  (("consumed_request_ids",), [f"{number:032x}" for number in range(4097)]),
  (("last_request_id",), REQUEST), (("extra",), "synthetic-secret"),
  (("child_identity", "pid"), float("nan")), (("child_identity", "pid"), float("inf")),
  (("child_identity", "pid"), 1.0), (("child_identity", "pid"), 2 ** 64),
  (("child_identity", "extra"), "synthetic-secret"),
])
def test_invalid_input_never_creates_files_and_errors_are_redacted(store, path, value):
  with pytest.raises(Conflict) as caught:
    store.create(changed(path, value))
  assert "synthetic-secret" not in str(caught.value)
  assert "secret" not in str(caught.value)
  assert not store.root.exists()


@pytest.mark.parametrize("state", ["parked", "closed"])
def test_quiescent_states_reject_child_but_do_not_require_a_run_id(store, state):
  value = record()
  value["state"] = state
  with pytest.raises(Conflict):
    store.create(value)
  value.update(child_identity=None, run_id=None)
  assert store.create(value) == value


@pytest.mark.parametrize("state", ["running", "parking", "parked", "resume_pending", "unknown", "closed"])
def test_codec_does_not_invent_control_transition_eligibility(store, state):
  initial = store.create(record())
  following = deepcopy(initial)
  following.update(state=state, child_identity=None)
  assert store.update(initial, following) == following


@pytest.mark.parametrize("field,value", [
  ("generation", 2), ("manager_identity", {"pid": 124, "birth_id": "other"}),
  ("terminal_ref", {**record()["terminal_ref"], "pane_id": "other"}),
  ("manager_code_identity", "e" * 64),
  ("endpoint_identity", {**record()["endpoint_identity"], "inode": 4}),
  ("scope", {**record()["scope"], "profile": "pi-base"}),
  ("scope", {**record()["scope"], "agent": "dsh"}),
])
def test_immutable_fields_cannot_change(store, field, value):
  initial = store.create(record())
  before = (store.root / "container.json").read_bytes()
  following = {**initial, field: value}
  with pytest.raises(Conflict):
    store.update(initial, following)
  assert (store.root / "container.json").read_bytes() == before


def test_consumed_requests_append_exactly_one_and_last_refers_to_consumed(store):
  initial = store.create(record())
  following = {**initial, "consumed_request_ids": [REQUEST], "last_request_id": REQUEST}
  assert store.update(initial, following) == following
  for ids in ([], ["e" * 32], [REQUEST, "e" * 32, "f" * 32]):
    with pytest.raises(Conflict):
      store.update(following, {**following, "consumed_request_ids": ids, "last_request_id": None})
  assert store.read() == following
  assert store.update(following, {**following, "last_request_id": None})["last_request_id"] is None


def test_consumed_request_order_cannot_be_rewritten(store):
  initial = record()
  initial.update(consumed_request_ids=[REQUEST, "e" * 32], last_request_id=REQUEST)
  saved = store.create(initial)
  with pytest.raises(Conflict):
    store.update(saved, {**saved, "consumed_request_ids": ["e" * 32, REQUEST]})
  assert store.read() == saved


def test_maximum_requests_and_numeric_identity_bounds_roundtrip(store):
  value = record()
  value["generation"] = 2 ** 64 - 1
  value["manager_identity"]["pid"] = 2 ** 64 - 1
  value["terminal_ref"]["server_identity"] = [0, 2 ** 64 - 1]
  value["endpoint_identity"].update(device=2 ** 64 - 1, inode=2 ** 64 - 1)
  value["consumed_request_ids"] = [f"{number:032x}" for number in range(4096)]
  value["last_request_id"] = value["consumed_request_ids"][-1]
  assert store.create(value) == value


@pytest.mark.parametrize("damage", ["duplicate", "nested-duplicate", "nan", "infinity", "float", "unicode", "json", "oversize", "mode", "hardlink", "symlink"])
def test_corrupt_existing_file_is_not_repaired_or_overwritten(store, damage):
  expected = store.create(record())
  path = store.root / "container.json"
  raw = path.read_bytes()
  if damage == "duplicate": raw = b'{"schema_version":1,' + raw[1:]
  elif damage == "nested-duplicate": raw = raw.replace(b'"pid":123', b'"pid":123,"pid":123')
  elif damage == "nan": raw = raw.replace(b'"generation":1', b'"generation":NaN')
  elif damage == "infinity": raw = raw.replace(b'"generation":1', b'"generation":Infinity')
  elif damage == "float": raw = raw.replace(b'"generation":1', b'"generation":1.0')
  elif damage == "unicode": raw = b"\xff"
  elif damage == "json": raw = b'{"synthetic-secret":'
  elif damage == "oversize": raw = b" " * (1024 * 1024 + 1)
  path.write_bytes(raw)
  if damage == "mode": path.chmod(0o644)
  elif damage == "hardlink": os.link(path, store.root / "retained.json")
  elif damage == "symlink":
    path.rename(store.root / "retained.json")
    path.symlink_to("retained.json")
  for operation in (store.read, lambda: store.update(expected, expected), lambda: store.create(record())):
    with pytest.raises(Conflict) as caught:
      operation()
    assert "synthetic-secret" not in str(caught.value)
  assert path.read_bytes() == raw
  assert path.is_symlink() == (damage == "symlink")


def test_noncanonical_record_is_readable_but_raw_byte_cas_rejects_it(store):
  expected = store.create(record())
  path = store.root / "container.json"
  noncanonical = json.dumps(expected, indent=2).encode()
  path.write_bytes(noncanonical)
  assert store.read() == expected
  with pytest.raises(Conflict):
    store.update(store.read(), {**expected, "state": "unknown"})
  assert path.read_bytes() == noncanonical


@pytest.mark.parametrize("damage", ["mode", "symlink", "replacement", "missing"])
def test_existing_root_identity_and_privacy_are_preserved(store, damage):
  expected = store.create(record())
  original_root = store.root
  if damage == "mode": original_root.chmod(0o755)
  else:
    retained = original_root.with_name("retained-container")
    original_root.rename(retained)
    if damage == "symlink": original_root.symlink_to(retained, target_is_directory=True)
    elif damage == "replacement":
      original_root.mkdir(mode=0o700)
      (original_root / "container.json").write_bytes((retained / "container.json").read_bytes())
  for operation in (store.read, lambda: store.update(expected, expected), lambda: store.create(expected)):
    with pytest.raises(Conflict):
      operation()
  preserved = original_root if damage == "mode" else retained
  assert json.loads((preserved / "container.json").read_bytes()) == expected
  if damage == "missing":
    assert not original_root.exists()


def test_root_replacement_while_waiting_for_metadata_lock_is_rejected(store, monkeypatch):
  expected = store.create(record())
  original = fcntl.flock
  retained = store.root.with_name("retained-container")
  def replace_after_lock(fd, operation):
    original(fd, operation)
    if operation == fcntl.LOCK_EX:
      store.root.rename(retained)
      store.root.mkdir(mode=0o700)
  with monkeypatch.context() as patch:
    patch.setattr(fcntl, "flock", replace_after_lock)
    with pytest.raises(Conflict):
      store.update(expected, expected)
  assert json.loads((retained / "container.json").read_bytes()) == expected
  assert not (store.root / "container.json").exists()


@pytest.mark.parametrize("after_write", [False, True])
def test_atomic_write_failure_keeps_before_or_after_evidence(store, monkeypatch, after_write):
  expected = store.create(record())
  following = {**expected, "state": "unknown"}
  original = Tree.replace
  def fail(tree, *args, **kwargs):
    if after_write:
      original(tree, *args, **kwargs)
    raise StateError("synthetic-secret")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", fail)
    with pytest.raises(Conflict) as caught:
      store.update(expected, following)
  assert "synthetic-secret" not in str(caught.value)
  assert store.read() == (following if after_write else expected)
  assert sorted(path.name for path in store.root.iterdir()) == ["container.json"]


def test_create_fsync_failure_retains_publication_without_retry_overwrite(store, monkeypatch):
  def fail(*args):
    raise Conflict("synthetic-secret")
  with monkeypatch.context() as patch:
    patch.setattr(storage, "sync_directory_ancestors", fail)
    with pytest.raises(Conflict) as caught:
      store.create(record())
  assert "synthetic-secret" not in str(caught.value)
  assert store.read() == record()
  with pytest.raises(Conflict):
    store.create(record())


def test_readback_detects_post_write_drift_without_erasing_it(store, monkeypatch):
  expected = store.create(record())
  following = {**expected, "state": "unknown"}
  original = Tree.replace
  def drift(tree, *args, **kwargs):
    original(tree, *args, **kwargs)
    (store.root / "container.json").write_bytes(b"synthetic-evidence")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", drift)
    with pytest.raises(Conflict):
      store.update(expected, following)
  assert (store.root / "container.json").read_bytes() == b"synthetic-evidence"


def test_parallel_stale_updates_allow_only_one_commit(store):
  expected = store.create(record())
  def update(state):
    concurrent_store = ContainerStore(store.root, CONTAINER)
    try:
      concurrent_store.update(expected, {**expected, "state": state})
      return state
    except Conflict:
      return None
  with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(update, ("parking", "unknown")))
  assert sum(result is not None for result in results) == 1
  assert store.read()["state"] == next(result for result in results if result is not None)


def test_operations_never_invoke_process_or_endpoint_control(store, monkeypatch):
  def forbidden(*args, **kwargs):
    pytest.fail("container metadata cannot control or observe native processes")
  monkeypatch.setattr(subprocess, "Popen", forbidden)
  monkeypatch.setattr(pane_records.run_owners, "current_process_identity", forbidden)
  monkeypatch.setattr(pane_records.run_owners, "observed_process_identity", forbidden)
  expected = store.create(record())
  assert store.update(expected, {**expected, "state": "unknown"})["state"] == "unknown"


@pytest.mark.parametrize("root,container_id", [(Path("relative"), CONTAINER), (Path("/"), CONTAINER),
  (Path("/tmp/../synthetic"), CONTAINER), ("/tmp/synthetic", CONTAINER), (Path("/tmp/synthetic"), "A" * 32),
  (Path("/tmp/synthetic"), True)])
def test_invalid_store_binding_is_rejected(root, container_id):
  with pytest.raises(Conflict):
    ContainerStore(root, container_id)
