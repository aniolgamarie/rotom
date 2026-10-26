"""临时真实私人目录与短NB锁；不启动host/pidfd/信号。"""
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path

import pytest

from agentcfg import run_owners, stop_inbox as inbox, stop_requests
from agentcfg.storage import Conflict, Tree
from test_rotom_stop_requests import request as make_request


BINDING = {"machine": "synthetic", "local": "/synthetic/local.toml", "profile": "dsh"}
MANAGER = {"pid": 101, "birth_id": "synthetic-manager"}
HOST = {"pid": 202, "birth_id": "synthetic-host"}
RUN = "c" * 32


@pytest.fixture
def case(tmp_path, monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  root = tmp_path / "inbox"
  return inbox.StopInbox(root, BINDING)


def create(case): return case.create(run_id=RUN, manager_identity=MANAGER, host_identity=HOST)


def snapshot(root):
  if not root.exists(): return None
  return {entry.name: (entry.read_bytes(), entry.stat().st_mode & 0o777) for entry in root.iterdir() if entry.is_file()}


def change_endpoint(case, change):
  path = case.root / "endpoint.json"; value = json.loads(path.read_bytes()); change(value)
  path.write_bytes(run_owners._encode(value))


def test_constructor_describe_and_missing_operations_create_nothing(case):
  assert not case.root.exists() and case.describe() is None
  with pytest.raises(Conflict): case.submit(make_request(), expected={})
  with pytest.raises(Conflict): case.pending(expected={})
  assert not case.root.exists()


def test_create_exact_metadata_and_readonly_independent_results(case):
  endpoint = create(case)
  info = case.root.stat()
  assert endpoint == {"schema_version": 1, "kind": "stop-inbox", "binding_digest": hashlib.sha256(run_owners._encode(BINDING)).hexdigest(),
    "run_id": RUN, "manager_identity": MANAGER, "host_identity": HOST, "nonce": endpoint["nonce"],
    "physical": {"device": info.st_dev, "inode": info.st_ino}}
  assert len(endpoint["nonce"]) == 32 and int(endpoint["nonce"], 16) >= 0
  assert info.st_mode & 0o777 == 0o700
  assert (case.root / "endpoint.json").stat().st_mode & 0o777 == 0o600
  before = snapshot(case.root)
  assert case.describe() == endpoint and case.pending(expected=endpoint) == []
  endpoint["manager_identity"]["pid"] = 999
  assert case.describe()["manager_identity"] == MANAGER
  assert snapshot(case.root) == before


def test_submit_canonical_envelope_pending_sorted_no_deletion_or_shared_data(case):
  endpoint = create(case)
  for identifier in ("e" * 32, "a" * 32):
    request = make_request(); request["request_id"] = identifier
    assert case.submit(request, expected=endpoint) is None
    request["manager_identity"]["pid"] = 999
  before = snapshot(case.root)
  values = case.pending(expected=endpoint)
  assert [value["request_id"] for value in values] == ["a" * 32, "e" * 32]
  values[0]["host_identity"]["pid"] = 999
  assert case.pending(expected=endpoint)[0]["host_identity"] == HOST
  assert snapshot(case.root) == before
  envelope = json.loads((case.root / ("request-" + "a" * 32 + ".json")).read_bytes())
  assert envelope == {"schema_version": 1, "kind": "stop-inbox-request", "endpoint_digest": hashlib.sha256(run_owners._encode(endpoint)).hexdigest(),
    "request": {**make_request(), "request_id": "a" * 32}}


@pytest.mark.parametrize("damage", ["run", "manager", "manager-extra", "manager-bool", "host-same", "host-extra"])
def test_create_invalid_metadata_rejects_before_root_creation(case, damage):
  run, manager, host = RUN, deepcopy(MANAGER), deepcopy(HOST)
  if damage == "run": run = "bad"
  elif damage == "manager": manager["birth_id"] = "other"
  elif damage == "manager-extra": manager["extra"] = True
  elif damage == "manager-bool": manager["pid"] = True
  elif damage == "host-same": host["pid"] = manager["pid"]
  else: host["extra"] = "synthetic-private-canary"
  with pytest.raises(Conflict) as caught: case.create(run_id=run, manager_identity=manager, host_identity=host)
  assert not case.root.exists() and "synthetic-private-canary" not in str(caught.value)


def test_empty_existing_root_is_allowed_but_nonempty_and_endpoint_are_never_overwritten(case):
  case.root.mkdir(mode=0o700)
  endpoint = create(case); before = snapshot(case.root)
  with pytest.raises(Conflict): create(case)
  assert case.describe() == endpoint and snapshot(case.root) == before


def test_nonempty_root_without_endpoint_refuses_all_operations_without_cleanup(case):
  case.root.mkdir(mode=0o700); path = case.root / "synthetic-private-canary"; path.write_bytes(b"preserve"); path.chmod(0o600)
  for action in (lambda: create(case), case.describe, lambda: case.pending(expected={}), lambda: case.submit(make_request(), expected={})):
    with pytest.raises(Conflict) as caught: action()
    assert "synthetic-private-canary" not in str(caught.value)
  assert path.read_bytes() == b"preserve"


@pytest.mark.parametrize("operation", ["submit", "pending"])
@pytest.mark.parametrize("damage", ["nonce", "physical", "run", "host", "binding", "extra", "type"])
def test_expected_endpoint_is_exact_binding_not_authorization(case, operation, damage):
  endpoint = create(case); expected = deepcopy(endpoint)
  if damage == "nonce": expected["nonce"] = "f" * 32
  elif damage == "physical": expected["physical"]["inode"] += 1
  elif damage == "run": expected["run_id"] = "f" * 32
  elif damage == "host": expected["host_identity"]["birth_id"] = "other"
  elif damage == "binding": expected["binding_digest"] = "0" * 64
  elif damage == "extra": expected["text"] = "synthetic-private-canary"
  else: expected = True
  before = snapshot(case.root)
  with pytest.raises(Conflict):
    case.submit(make_request(), expected=expected) if operation == "submit" else case.pending(expected=expected)
  assert snapshot(case.root) == before


@pytest.mark.parametrize("field", ["run_id", "manager_identity", "host_identity"])
def test_request_target_must_match_endpoint(case, field):
  endpoint = create(case); request = make_request()
  if field == "run_id": request[field] = "f" * 32
  else: request[field]["birth_id"] = "other"
  before = snapshot(case.root)
  with pytest.raises(Conflict): case.submit(request, expected=endpoint)
  assert snapshot(case.root) == before


def test_pending_only_current_manager_but_submit_is_metadata_only(case, monkeypatch):
  endpoint = create(case)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: {**MANAGER, "birth_id": "other"})
  case.submit(make_request(), expected=endpoint)
  assert case.describe() == endpoint
  with pytest.raises(Conflict): case.pending(expected=endpoint)


def test_duplicate_request_never_overwrites_even_same_body(case):
  endpoint = create(case); case.submit(make_request(), expected=endpoint); before = snapshot(case.root)
  for request in (make_request(), {**make_request(), "batch_id": "f" * 32}):
    with pytest.raises(Conflict): case.submit(request, expected=endpoint)
  assert snapshot(case.root) == before


@pytest.mark.parametrize("damage", ["unknown", "directory", "symlink", "hardlink", "mode", "oversize", "json", "duplicate", "nonce", "physical", "endpoint-extra", "request-extra", "digest", "filename", "request-host"])
def test_corrupt_files_fail_closed_readonly(case, damage, tmp_path):
  endpoint = create(case); case.submit(make_request(), expected=endpoint)
  path = case.root / ("request-" + "a" * 32 + ".json")
  if damage == "unknown": path.rename(case.root / "unknown")
  elif damage == "directory": path.unlink(); path.mkdir()
  elif damage == "symlink": data = path.read_bytes(); path.unlink(); outside = tmp_path / "outside"; outside.write_bytes(data); path.symlink_to(outside)
  elif damage == "hardlink": os.link(path, tmp_path / "alias")
  elif damage == "mode": path.chmod(0o644)
  elif damage == "oversize": path.write_bytes(b"x" * 20481)
  elif damage == "json": path.write_bytes(b"synthetic-private-canary")
  elif damage == "duplicate": path.write_bytes(path.read_bytes().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'))
  elif damage == "nonce": change_endpoint(case, lambda value: value.update(nonce="f" * 32))
  elif damage == "physical": change_endpoint(case, lambda value: value["physical"].update(inode=value["physical"]["inode"] + 1))
  elif damage == "endpoint-extra": change_endpoint(case, lambda value: value.update(text="synthetic-private-canary"))
  else:
    value = json.loads(path.read_bytes())
    if damage == "request-extra": value["text"] = "synthetic-private-canary"
    elif damage == "digest": value["endpoint_digest"] = "0" * 64
    elif damage == "filename": value["request"]["request_id"] = "e" * 32
    else: value["request"]["host_identity"]["birth_id"] = "other"
    path.write_bytes(run_owners._encode(value))
  before = {entry.name: entry.lstat() for entry in case.root.iterdir()}
  for action in (case.describe, lambda: case.pending(expected=endpoint), lambda: case.submit(make_request(), expected=endpoint)):
    with pytest.raises(Conflict) as caught: action()
    assert "synthetic-private-canary" not in str(caught.value)
  assert {entry.name: entry.lstat() for entry in case.root.iterdir()} == before


def test_endpoint_size_limit_and_partial_presence_no_creation(case):
  endpoint = create(case); (case.root / "endpoint.json").write_bytes(b"x" * 16385)
  with pytest.raises(Conflict): case.describe()
  assert (case.root / "endpoint.json").stat().st_size == 16385


def test_128_request_capacity_is_strict_and_preserves_existing(case):
  endpoint = create(case)
  for number in range(128):
    request = make_request(); request["request_id"] = format(number, "032x")
    case.submit(request, expected=endpoint)
  assert len(case.pending(expected=endpoint)) == 128
  request = make_request(); request["request_id"] = "f" * 32
  with pytest.raises(Conflict): case.submit(request, expected=endpoint)
  # 固定fd遍历对外部注入的第129项同样拒绝。
  path = case.root / ("request-" + request["request_id"] + ".json")
  path.write_bytes(b"{}"); path.chmod(0o600)
  with pytest.raises(Conflict): case.describe()


@pytest.mark.parametrize("operation", ["create", "describe", "submit", "pending"])
def test_metadata_lock_contention_is_nonblocking(case, operation):
  endpoint = None if operation == "create" else create(case)
  case.root.mkdir(mode=0o700, exist_ok=True)
  with Tree(case.root) as tree:
    fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
      with pytest.raises(Conflict):
        {"create": lambda: create(case), "describe": case.describe,
          "submit": lambda: case.submit(make_request(), expected=endpoint), "pending": lambda: case.pending(expected=endpoint)}[operation]()
    finally: fcntl.flock(tree.fd, fcntl.LOCK_UN)
  assert len(list(case.root.iterdir())) == (0 if endpoint is None else 1)


@pytest.mark.parametrize("operation", ["create", "submit"])
@pytest.mark.parametrize("stage", ["before", "after"])
@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_write_fault_never_retries_or_cleans_published_data(case, monkeypatch, operation, stage, kind):
  endpoint = None if operation == "create" else create(case)
  original = Tree.write_new; error = kind("synthetic-private-canary"); calls = []
  def write(tree, name, data):
    calls.append(name)
    if stage == "after": original(tree, name, data)
    raise error
  monkeypatch.setattr(Tree, "write_new", write)
  with pytest.raises(Conflict if kind is OSError else kind) as caught:
    create(case) if operation == "create" else case.submit(make_request(), expected=endpoint)
  if kind is not OSError: assert caught.value is error
  assert len(calls) == 1
  assert (case.root / calls[0]).exists() is (stage == "after")
  assert case.root.exists()


def test_root_replaced_after_publish_is_rejected_and_original_file_retained(case, monkeypatch, tmp_path):
  original = Tree.write_new; moved = tmp_path / "old-inbox"
  def write(tree, name, data):
    original(tree, name, data)
    case.root.rename(moved); case.root.mkdir(mode=0o700)
  monkeypatch.setattr(Tree, "write_new", write)
  with pytest.raises(Conflict): create(case)
  assert (moved / "endpoint.json").exists() and not list(case.root.iterdir())


@pytest.mark.parametrize("operation", ["create", "submit"])
def test_directory_fsync_response_loss_retains_published_file_without_retry(case, monkeypatch, operation):
  endpoint = None if operation == "create" else create(case)
  original = os.fsync; calls = []
  def fsync(fd):
    original(fd); calls.append(fd)
    if len(calls) == 2: raise OSError("synthetic-private-canary")
  monkeypatch.setattr(os, "fsync", fsync)
  with pytest.raises(Conflict):
    create(case) if operation == "create" else case.submit(make_request(), expected=endpoint)
  assert len(calls) == 2
  assert case.describe() is not None
  if operation == "submit": assert len(case.pending(expected=endpoint)) == 1
  assert not any(entry.name.startswith(".agentcfg-") for entry in case.root.iterdir())


def test_readonly_root_replacement_during_scandir_refuses_without_creating_data(case, monkeypatch, tmp_path):
  create(case); original = os.scandir; moved = tmp_path / "old-inbox"; calls = []
  def scan(fd):
    assert type(fd) is int
    result = original(fd)
    if not calls:
      calls.append(True); case.root.rename(moved); case.root.mkdir(mode=0o700)
    return result
  monkeypatch.setattr(os, "scandir", scan)
  with pytest.raises(Conflict): case.describe()
  assert (moved / "endpoint.json").exists() and list(case.root.iterdir()) == []


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_read_control_exception_is_original_and_releases_metadata_lock(case, monkeypatch, kind):
  endpoint = create(case); original = Tree.read; error = kind("synthetic-control")
  def fail(*args, **kwargs): raise error
  with monkeypatch.context() as changed:
    changed.setattr(Tree, "read", fail)
    with pytest.raises(kind) as caught: case.describe()
    assert caught.value is error
  assert case.describe() == endpoint


@pytest.mark.parametrize("operation", ["create", "submit"])
def test_parent_directory_sync_follows_publish_before_readback(case, monkeypatch, operation):
  from agentcfg import storage
  endpoint = None if operation == "create" else create(case)
  trace = []; write, read = Tree.write_new, Tree.read
  def published(tree, name, data):
    write(tree, name, data); trace.append("publish")
  def synced(path):
    assert path == case.root.parent
    trace.append("parent-sync")
  def readback(*args, **kwargs): trace.append("read"); return read(*args, **kwargs)
  monkeypatch.setattr(Tree, "write_new", published)
  monkeypatch.setattr(Tree, "read", readback)
  monkeypatch.setattr(storage, "sync_directory_ancestors", synced, raising=False)
  create(case) if operation == "create" else case.submit(make_request(), expected=endpoint)
  index = trace.index("publish")
  assert trace[index:index + 3] == ["publish", "parent-sync", "read"]
  assert trace.count("parent-sync") == 1


@pytest.mark.parametrize("operation", ["create", "submit"])
@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_parent_directory_sync_failure_retains_file_and_returns_no_success(case, monkeypatch, operation, kind):
  from agentcfg import storage
  endpoint = None if operation == "create" else create(case)
  error = kind("synthetic-private-canary"); calls = []
  def failed(path): calls.append(path); raise error
  monkeypatch.setattr(storage, "sync_directory_ancestors", failed, raising=False)
  with pytest.raises(Conflict if kind is OSError else kind) as caught:
    create(case) if operation == "create" else case.submit(make_request(), expected=endpoint)
  if kind is not OSError: assert caught.value is error
  else: assert "synthetic-private-canary" not in str(caught.value)
  assert calls == [case.root.parent]
  name = "endpoint.json" if operation == "create" else "request-" + "a" * 32 + ".json"
  assert (case.root / name).exists()


@pytest.mark.parametrize("operation", ["create", "submit"])
def test_root_replaced_during_parent_sync_is_rechecked_before_success(case, monkeypatch, tmp_path, operation):
  from agentcfg import storage
  endpoint = None if operation == "create" else create(case)
  original = storage.sync_directory_ancestors; moved = tmp_path / "sync-old-inbox"
  def synced(path):
    original(path)
    case.root.rename(moved); case.root.mkdir(mode=0o700)
  monkeypatch.setattr(storage, "sync_directory_ancestors", synced)
  with pytest.raises(Conflict):
    create(case) if operation == "create" else case.submit(make_request(), expected=endpoint)
  name = "endpoint.json" if operation == "create" else "request-" + "a" * 32 + ".json"
  assert (moved / name).exists() and not list(case.root.iterdir())
