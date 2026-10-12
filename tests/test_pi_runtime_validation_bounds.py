"""受管校验固定资源边界；自有临时文件与旧 fake installer，不启动宿主。"""

import builtins
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import pi_dependencies as dependencies
from agentcfg import pi_runtime_packages as packages
from agentcfg.storage import Conflict, Tree
from test_pi_dependencies import ready_sync_fixture, fake_installer, installed_graph_fixture


@pytest.fixture
def runtime(tmp_path):
  root = tmp_path / "bounded-runtime"
  root.mkdir(mode=0o700)
  return root


def limit(monkeypatch, name, value):
  # 私有默认测试接缝；不是生产入口选项。
  monkeypatch.setattr(packages, name, value, raising=False)


def write(root, name, raw=b"x"):
  path = root / name
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  path.write_bytes(raw)
  path.chmod(0o600)
  return path


def io_spy(monkeypatch):
  opened = []
  hashed = []
  original = Tree.open_read
  @contextmanager
  def open_read(tree, name, *, max_bytes=None):
    opened.append((name, max_bytes))
    with original(tree, name, max_bytes=max_bytes) as result:
      yield result
  def sha(*args, **kwargs):
    hashed.append(True)
    return hashlib.sha256(*args, **kwargs)
  monkeypatch.setattr(Tree, "open_read", open_read)
  monkeypatch.setattr(packages, "hashlib", SimpleNamespace(sha256=sha))
  return opened, hashed


class TrackedScan:
  def __init__(self, directory, state):
    self.iterator = os.scandir(directory)
    self.state = state
    self.state["created"] += 1
  def __enter__(self): return self
  def __iter__(self): return self
  def __next__(self):
    entry = next(self.iterator)
    self.state["consumed"] += 1
    return entry
  def __exit__(self, *args):
    self.iterator.close()
    self.state["closed"] += 1


def scan_spy(monkeypatch):
  state = {"created": 0, "consumed": 0, "closed": 0, "sorted": 0}
  def scan(path): return TrackedScan(path, state)
  def sorting(*args, **kwargs):
    state["sorted"] += 1
    return builtins.sorted(*args, **kwargs)
  monkeypatch.setattr(packages, "os", SimpleNamespace(scandir=scan, fsencode=os.fsencode,
    geteuid=os.geteuid, readlink=os.readlink))
  monkeypatch.setattr(packages, "sorted", sorting, raising=False)
  return state


def test_real_owned_tree_positive_inventory_exact_file_and_total_caps(runtime, monkeypatch):
  write(runtime, "a", b"abc")
  limit(monkeypatch, "MAX_FILE", 3); limit(monkeypatch, "MAX_TOTAL", 3)
  opened, hashed = io_spy(monkeypatch)
  result = packages.inventory(runtime)
  assert result["a"]["sha256"] == hashlib.sha256(b"abc").hexdigest()
  assert opened == [("a", 3)] and hashed == [True]


@pytest.mark.parametrize("cap", ["MAX_FILE", "MAX_TOTAL"])
def test_oversized_stat_rejects_before_any_file_open_or_hash(runtime, monkeypatch, cap):
  write(runtime, "a", b"abc")
  assert packages.inventory(runtime)["a"]["kind"] == "file"
  limit(monkeypatch, cap, 2)
  opened, hashed = io_spy(monkeypatch)
  with pytest.raises(Conflict): packages.inventory(runtime)
  assert opened == [] and hashed == []


def test_total_reservation_is_cumulative_and_second_file_is_not_opened(runtime, monkeypatch):
  write(runtime, "a", b"ab"); write(runtime, "b", b"cd")
  limit(monkeypatch, "MAX_TOTAL", 4)
  assert len(packages.inventory(runtime)) == 2
  limit(monkeypatch, "MAX_TOTAL", 3)
  opened, hashed = io_spy(monkeypatch)
  with pytest.raises(Conflict): packages.inventory(runtime)
  assert [name for name, cap in opened] == ["a"] and hashed == [True]


@pytest.mark.parametrize("fault", ["growth", "short"])
def test_stream_increment_and_final_size_use_reserved_stat(runtime, monkeypatch, fault):
  write(runtime, "a", b"abc")
  assert packages.inventory(runtime)["a"]["kind"] == "file"
  original = Tree.open_read
  @contextmanager
  def injected(tree, name, *, max_bytes=None):
    with original(tree, name, max_bytes=max_bytes) as (stream, opened):
      class ChangedStream:
        def __init__(self): self.once = False
        def read(self, count):
          if self.once: return b""
          self.once = True
          return b"abcd" if fault == "growth" else b"ab"
      yield ChangedStream(), opened
  monkeypatch.setattr(Tree, "open_read", injected)
  with pytest.raises(Conflict): packages.inventory(runtime)


def test_inventory_budget_is_checked_before_sort_append_and_closes_iterator(runtime, monkeypatch):
  for name in ("a", "b", "c", "d"): write(runtime, name)
  limit(monkeypatch, "MAX_ENTRIES", 2)
  state = scan_spy(monkeypatch)
  opened, hashed = io_spy(monkeypatch)
  with pytest.raises(Conflict): packages.inventory(runtime)
  assert state == {"created": 1, "consumed": 3, "closed": 1, "sorted": 0}
  assert opened == [] and hashed == []


def test_global_entry_budget_and_root_markers_preserve_exact_boundary(runtime, monkeypatch):
  write(runtime, "dir/a")
  write(runtime, ".agentcfg-ready", b"marker")
  write(runtime, ".agentcfg-receipt.json", b"marker")
  limit(monkeypatch, "MAX_ENTRIES", 2)
  result = packages.inventory(runtime)
  assert list(result) == ["dir", "dir/a"]
  limit(monkeypatch, "MAX_ENTRIES", 1)
  with pytest.raises(Conflict): packages.inventory(runtime)


@pytest.mark.parametrize("validator", ["inventory", "_package_graph"])
def test_directory_depth_exact_cap_and_next_directory_rejected(runtime, monkeypatch, validator):
  write(runtime, "a/b/c/body")
  function = getattr(packages, validator)
  limit(monkeypatch, "MAX_DEPTH", 3)
  function(runtime)
  limit(monkeypatch, "MAX_DEPTH", 2)
  with pytest.raises(Conflict): function(runtime)


@pytest.mark.parametrize("validator", ["inventory", "_package_graph"])
def test_utf8_relative_path_byte_cap_equal_then_one_less(runtime, monkeypatch, validator):
  name = "中文"
  write(runtime, name)
  function = getattr(packages, validator)
  limit(monkeypatch, "MAX_PATH", len(name.encode("utf-8")))
  function(runtime)
  limit(monkeypatch, "MAX_PATH", len(name.encode("utf-8")) - 1)
  with pytest.raises(Conflict): function(runtime)


@pytest.mark.parametrize("kind,visits", [("walk", 1), ("modules", 3), ("scope", 5)])
def test_graph_global_visit_cap_covers_each_enumeration_and_closes_iterators(runtime, monkeypatch, kind, visits):
  if kind == "walk": write(runtime, "a")
  if kind == "modules": (runtime / "node_modules/pkg").mkdir(mode=0o700, parents=True)
  if kind == "scope": (runtime / "node_modules/@scope/pkg").mkdir(mode=0o700, parents=True)
  limit(monkeypatch, "MAX_GRAPH_VISITS", visits)
  expected = packages._package_graph(runtime)
  assert expected == (set() if kind == "walk" else {"node_modules/pkg"} if kind == "modules" else {"node_modules/@scope/pkg"})
  limit(monkeypatch, "MAX_GRAPH_VISITS", visits - 1)
  state = scan_spy(monkeypatch)
  with pytest.raises(Conflict): packages._package_graph(runtime)
  assert state["consumed"] == visits
  assert state["created"] == state["closed"]


def test_graph_modules_budget_is_checked_before_sorting_children(runtime, monkeypatch):
  for name in ("a", "b", "c"): (runtime / "node_modules" / name).mkdir(mode=0o700, parents=True)
  limit(monkeypatch, "MAX_GRAPH_VISITS", 2)
  state = scan_spy(monkeypatch)
  with pytest.raises(Conflict): packages._package_graph(runtime)
  assert state["consumed"] == 3 and state["sorted"] == 0
  assert state["created"] == state["closed"]


@pytest.fixture
def installed(tmp_path, monkeypatch):
  workspace, manifest = ready_sync_fixture(tmp_path)
  monkeypatch.setattr(dependencies, "checked", fake_installer([]))
  backend = dependencies.PiBackend(profile="pi-fixture")
  result = backend._sync(workspace, backend.read_lock(workspace.repository))
  root = backend.root(workspace, result["identity"])
  assert packages.status(root, result["identity"]) == "installed"
  return root, result["identity"], manifest["profile_slices"][workspace.profile]


def test_receipt_cap_equal_allows_status_and_plus_one_rejects_before_json(installed, monkeypatch):
  root, identity, piece = installed
  size = (root / ".agentcfg-receipt.json").stat().st_size
  limit(monkeypatch, "MAX_RECEIPT", size)
  assert packages.status(root, identity) == "installed"
  limit(monkeypatch, "MAX_RECEIPT", size - 1)
  calls = []
  def forbidden(raw): calls.append(True); raise AssertionError("receipt decoded before cap")
  monkeypatch.setattr(packages, "json", SimpleNamespace(loads=forbidden))
  with pytest.raises(Conflict): packages._validated_receipt(root, identity)
  assert calls == []
  assert packages.status(root, identity) == "damaged" and calls == []


@pytest.mark.parametrize("cap", ["MAX_ENTRIES", "MAX_FILE", "MAX_TOTAL", "MAX_DEPTH", "MAX_PATH", "MAX_GRAPH_VISITS", "MAX_PACKAGE_DOCUMENT"])
def test_each_fixed_bound_turns_previously_installed_status_damaged(installed, monkeypatch, cap):
  root, identity, piece = installed
  limit(monkeypatch, cap, 0)
  assert packages.status(root, identity) == "damaged"


@pytest.mark.parametrize("field", ["package_path", "lock_path", "installed"])
def test_each_package_document_tree_read_has_same_closed_cap(tmp_path, monkeypatch, field):
  root, piece = installed_graph_fixture(tmp_path)
  target = (piece[field] if field != "installed" else
    str(Path(piece["package_path"]).parent / "node_modules/synthetic-host/package.json"))
  if field != "lock_path":
    document = json.loads((root / target).read_bytes())
    document["padding"] = "x" * 4096
    raw = json.dumps(document).encode()
    (root / target).write_bytes(raw)
    if field == "package_path": piece["package_json_digest"] = hashlib.sha256(raw).hexdigest()
  size = (root / target).stat().st_size
  calls = []
  original = Tree.read
  def tracked(tree, path, *, max_bytes=None):
    if path == target: calls.append(max_bytes)
    return original(tree, path, max_bytes=max_bytes)
  monkeypatch.setattr(Tree, "read", tracked)
  limit(monkeypatch, "MAX_PACKAGE_DOCUMENT", size)
  packages.validate_installed(root, piece)
  assert calls and all(cap == packages.MAX_PACKAGE_DOCUMENT for cap in calls)
  calls.clear()
  limit(monkeypatch, "MAX_PACKAGE_DOCUMENT", size - 1)
  with pytest.raises(Conflict): packages.validate_installed(root, piece)
  assert calls and all(cap == size - 1 for cap in calls)


def test_real_file_growth_read_stops_after_reserved_size_plus_one(runtime, monkeypatch):
  target = write(runtime, "a", b"abc")
  reserved = target.stat().st_size
  assert packages.inventory(runtime)["a"]["kind"] == "file"
  original = Tree.open_read
  returned = []
  requested = []
  @contextmanager
  def growth_after_open_stat(tree, name, *, max_bytes=None):
    with original(tree, name, max_bytes=max_bytes) as (stream, opened):
      assert opened.st_size == reserved
      with target.open("ab") as writer:
        writer.write(b"x" * 32)
      class ObservedRealStream:
        def read(self, count):
          requested.append(count)
          chunk = stream.read(count)
          returned.append(len(chunk))
          return chunk
      yield ObservedRealStream(), opened
  monkeypatch.setattr(Tree, "open_read", growth_after_open_stat)
  with pytest.raises(Conflict): packages.inventory(runtime)
  assert target.stat().st_size == reserved + 32
  assert sum(returned) <= reserved + 1
  assert requested == [reserved + 1]
