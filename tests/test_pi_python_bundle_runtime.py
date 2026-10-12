"""B2 临时 scratch/FD 和完整物理集合；不执行七个合成 wheel 正文。"""

import builtins
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from agentcfg import pi_python_bundle_runtime as runtime


_OWNER = (os.getuid(), os.geteuid(), os.getgid(), os.getegid())
_CALLS = []


@pytest.fixture(autouse=True)
def original_owner_and_callbacks(offline_guards, isolated_environment):
  assert _OWNER[0] != 0 and _OWNER[0] == _OWNER[1]
  assert (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) == _OWNER
  assert Path(os.environ["HOME"]).is_relative_to(isolated_environment.root)
  _CALLS.clear()
  yield
  assert _CALLS == []


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path, *, large=False, empty=True):
  from test_pi_python_bundle import _fixture as synthetic, _rebuild
  declaration, archives, originals = synthetic()
  if empty:
    declaration["wheels"][0]["explicit_directories"].append("attr/empty")
    declaration["wheels"][0]["explicit_directories"].sort()
    _rebuild(declaration, archives, originals, 0)
  if large:
    payload = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(33000))
    def change(files, row):
      files[next(name for name in files if name.endswith(".so"))] = payload
    _rebuild(declaration, archives, originals, 3, transform=change)
  raw = json.dumps(declaration, ensure_ascii=False).encode()
  root = tmp_path / "scratch"
  root.mkdir(mode=0o700)
  (root / "supervisor").mkdir(mode=0o750)
  (root / "supervisor").chmod(0o750)
  (root / "runtime").mkdir(mode=0o700)
  (root / "runtime/durable-python-bundle.json").write_bytes(raw)
  sources = {}
  for row in declaration["wheels"]:
    source = {"kind": "wheel", "package": row["name"], "version": row["version"], "wheel_filename": row["wheel_filename"],
      "url": "https://files.example.test/" + row["wheel_filename"], "archive_digest": row["archive_sha256"], "size": row["archive_size"],
      "license_files": sorted(row["dist_info"] + "/licenses/" + path for path in row["metadata"]["license_files"]),
      "vendor_path": "vendor/wheels/" + row["archive_sha256"] + "/" + row["wheel_filename"]}
    sources[row["source_id"]] = source
    path = root / source["vendor_path"]; path.parent.mkdir(parents=True, mode=0o700); path.write_bytes(archives[row["source_id"]])
  reference = {"schema_version": 1, "source": "agents/pi/runtime/durable-python-bundle.json", "path": "runtime/durable-python-bundle.json", "sha256": _sha(raw), "size": len(raw)}
  piece = {"source_ids": list(sources), "python_bundle": reference, "package_path": "pi-full-nested/package.json",
    "runtime_files": [{"source": reference["source"], "path": reference["path"], "transform": "copy", "input_digest": reference["sha256"], "digest": reference["sha256"], "mode": 384}]}
  return root, piece, sources, declaration, archives, originals


def _reject(function, *args):
  with pytest.raises(ValueError) as caught: function(*args)
  assert type(caught.value) is ValueError
  assert str(caught.value) == "pi-python-bundle-runtime"
  assert caught.value.__cause__ is None and caught.value.__context__ is None


def _install(values):
  assert runtime.install_locked_python_bundle_stage(*values[:3]) is None
  return runtime.validate_installed_python_bundle(values[0], values[1]["python_bundle"])


@pytest.mark.parametrize("large", [False, True])
def test_original_bytes_complete_empty_dirs_supervisor750_detached_no_loader(tmp_path, monkeypatch, large):
  values = _fixture(tmp_path, large=large)
  root, piece, sources, declaration, archives, originals = values
  before = deepcopy((piece, sources))
  original_import = builtins.__import__
  imports = []
  def guarded(name, *args, **kwargs):
    assert name.split(".")[0] not in ("attr", "attrs", "jsonschema", "yaml", "referencing", "rpds", "typing_extensions", "sitecustomize", "usercustomize")
    imports.append(name)
    return original_import(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  layout = _install(values)
  assert set(layout) == {"files", "directories"}
  assert layout["files"] == sorted(layout["files"], key=lambda row: row["path"])
  assert all(set(row) == {"path", "sha256", "size", "mode"} and row["mode"] == 384 for row in layout["files"])
  assert layout["directories"] == sorted(set(layout["directories"]))
  assert "supervisor/python-bundle/site-packages/attr/empty" in layout["directories"]
  assert (root / "supervisor").stat().st_mode & 0o777 == 0o750
  for row in declaration["wheels"]:
    for member in row["members"]:
      assert (root / "supervisor/python-bundle/site-packages" / member["path"]).read_bytes() == originals[row["name"]][member["path"]]
    assert (root / sources[row["source_id"]]["vendor_path"]).read_bytes() == archives[row["source_id"]]
  if large: assert max(row["size"] for row in layout["files"]) > 1048576
  layout["directories"].append("changed")
  layout["files"][0]["path"] = "changed"
  assert runtime.validate_installed_python_bundle(root, piece["python_bundle"])["files"][0]["path"] != "changed"
  assert (piece, sources) == before


@pytest.mark.parametrize("fault", ["missing-root-vendor", "wrong-root-vendor", "vendor-link", "vendor-hardlink", "body-link", "body-sha", "body-size", "ref", "record-size", "record-hash"])
def test_fixed_stage_root_no_package_relative_fallback_and_raw_pairing(tmp_path, fault):
  values = _fixture(tmp_path); root, piece, sources, _, archives, _ = values
  key = next(iter(sources)); source = sources[key]; path = root / source["vendor_path"]
  wrong_place = root / Path(piece["package_path"]).parent / source["vendor_path"]
  wrong_place.parent.mkdir(parents=True); wrong_place.write_bytes(archives[key])
  if fault == "missing-root-vendor": path.unlink()
  if fault == "wrong-root-vendor": path.write_bytes(b"x" * source["size"])
  if fault == "vendor-link": path.unlink(); path.symlink_to(wrong_place)
  if fault == "vendor-hardlink": os.link(path, root / "vendor-hardlink")
  if fault == "body-link":
    body = root / piece["python_bundle"]["path"]; body.rename(root / "original-body"); body.symlink_to(root / "original-body")
  if fault == "body-sha": (root / piece["python_bundle"]["path"]).write_bytes(b"broken")
  if fault == "body-size": piece["python_bundle"]["size"] += 1
  if fault == "ref": piece["python_bundle"]["path"] = "overlay.json"
  if fault == "record-size": source["size"] += 1
  if fault == "record-hash": source["archive_digest"] = "b" * 64
  _reject(runtime.install_locked_python_bundle_stage, root, piece, sources)
  assert not (root / "supervisor/python-bundle").exists()


@pytest.mark.parametrize("fault", ["hash", "size", "missing", "extra-file", "extra-empty", "link", "hardlink", "file-mode", "dir-mode", "supervisor-mode", "root-mode", "inventory-canonical", "inventory-key", "inventory-duplicate", "inventory-nan", "inventory-oversize"])
def test_installed_precise_files_directories_hash_modes_json_and_links(tmp_path, fault):
  values = _fixture(tmp_path); layout = _install(values); root, piece = values[:2]
  path = root / layout["files"][0]["path"]; prefix = root / "supervisor/python-bundle"; inventory = prefix / "inventory.json"
  if fault == "hash": path.write_bytes(b"x" * path.stat().st_size)
  if fault == "size": path.write_bytes(path.read_bytes() + b"x")
  if fault == "missing": path.unlink()
  if fault == "extra-file": (prefix / "extra").write_bytes(b"unexpected")
  if fault == "extra-empty": (prefix / "extra").mkdir(mode=0o700)
  if fault == "link": path.unlink(); path.symlink_to(root / "runtime/durable-python-bundle.json")
  if fault == "hardlink": os.link(path, root / "outside-bundle-link")
  if fault == "file-mode": path.chmod(0o644)
  if fault == "dir-mode": prefix.chmod(0o750)
  if fault == "supervisor-mode": (root / "supervisor").chmod(0o770)
  if fault == "root-mode": root.chmod(0o750)
  if fault == "inventory-canonical": inventory.write_bytes(inventory.read_bytes() + b"\n")
  if fault == "inventory-key":
    data = json.loads(inventory.read_bytes()); data["unknown"] = 1; inventory.write_bytes(json.dumps(data).encode())
  if fault == "inventory-duplicate": inventory.write_bytes(b'{"schema_version":1,"schema_version":1}')
  if fault == "inventory-nan": inventory.write_bytes(b'{"value":NaN}')
  if fault == "inventory-oversize": inventory.write_bytes(b" " * 16777217)
  _reject(runtime.validate_installed_python_bundle, root, piece["python_bundle"])


@pytest.mark.parametrize("fault", ["prefix-empty", "prefix-file", "prefix-link", "ancestor-file", "ancestor-link", "ancestor-case", "prefix-case", "marker-fifo", "unknown-sibling"])
def test_complete_occupied_scan_rejects_reserved_prefix_and_unknown_nodes(tmp_path, fault):
  values = _fixture(tmp_path); root = values[0]; prefix = root / "supervisor/python-bundle"
  if fault == "prefix-empty": prefix.mkdir(mode=0o700)
  if fault == "prefix-file": prefix.write_bytes(b"blocker")
  if fault == "prefix-link": prefix.symlink_to(root / "runtime")
  if fault == "ancestor-file": (root / "supervisor").rmdir(); (root / "supervisor").write_bytes(b"blocker")
  if fault == "ancestor-link": (root / "supervisor").rmdir(); (root / "supervisor").symlink_to(root / "runtime")
  if fault == "ancestor-case": (root / "supervisor").rename(root / "SUPERVISOR")
  if fault == "prefix-case": (root / "supervisor/PYTHON-BUNDLE").mkdir(mode=0o700)
  if fault == "marker-fifo": os.mkfifo(root / ".agentcfg-ready", 0o600)
  if fault == "unknown-sibling": os.mkfifo(root / "supervisor/unknown", 0o600)
  _reject(runtime.install_locked_python_bundle_stage, *values[:3])


def test_unrelated_case_aliases_and_opaque_in_tree_links_are_not_planner_collisions(tmp_path):
  values = _fixture(tmp_path); root = values[0]
  (root / "A").write_bytes(b"original A"); (root / "a").write_bytes(b"original a")
  (root / "opaque-link").symlink_to(root / "runtime")
  _install(values)
  assert (root / "A").read_bytes() == b"original A" and (root / "a").read_bytes() == b"original a"


class _Foreign:
  def __getattribute__(self, name): _CALLS.append("attribute"); raise AssertionError("foreign callback")
  def __fspath__(self): _CALLS.append("fspath"); raise AssertionError("foreign callback")
  def __repr__(self): _CALLS.append("repr"); raise AssertionError("foreign callback")
  def __deepcopy__(self, memo): _CALLS.append("deepcopy"); raise AssertionError("foreign callback")


@pytest.mark.parametrize("fault", ["piece", "sources", "unused-piece", "unused-source", "pathlike", "path-subclass", "nonstring-key", "cycle", "float", "integer", "string", "utf8", "depth", "nodes"])
def test_entire_native_snapshot_and_path_before_any_io_or_field_selection(tmp_path, monkeypatch, fault):
  values = _fixture(tmp_path); root, piece, sources = values[:3]
  if fault == "piece": piece = _Foreign()
  if fault == "sources": sources = _Foreign()
  if fault == "unused-piece": piece["unused"] = _Foreign()
  if fault == "unused-source": sources["unselected"] = {"kind": "npm", "foreign": _Foreign()}
  if fault == "pathlike": root = _Foreign()
  if fault == "path-subclass":
    class ForeignPath(type(Path())):
      def __fspath__(self): _CALLS.append("fspath"); raise AssertionError("foreign path")
    root = ForeignPath(root)
  if fault == "nonstring-key": piece[1] = None
  if fault == "cycle": piece["cycle"] = piece
  if fault == "float": piece["unused"] = 1.5
  if fault == "integer": piece["unused"] = 2 ** 63
  if fault == "string": piece["unused"] = "x" * 4097
  if fault == "utf8": piece["unused"] = "\ud800"
  if fault == "depth":
    value = None
    for _ in range(18): value = [value]
    piece["unused"] = value
  if fault == "nodes": piece["unused"] = [None] * 100001
  io = []
  def forbidden(*args, **kwargs): io.append("open"); raise AssertionError("IO before snapshot")
  monkeypatch.setattr(runtime.os, "open", forbidden)
  _reject(runtime.install_locked_python_bundle_stage, root, piece, sources)
  assert io == [] and _CALLS == []


@pytest.mark.parametrize("fault", ["schema-bool", "size-bool", "unknown", "null", "foreign", "pathlike"])
def test_validator_snapshot_and_exact_reference_before_io(tmp_path, monkeypatch, fault):
  values = _fixture(tmp_path); root, reference = values[0], deepcopy(values[1]["python_bundle"])
  if fault == "schema-bool": reference["schema_version"] = True
  if fault == "size-bool": reference["size"] = True
  if fault == "unknown": reference["extra"] = None
  if fault == "null": reference = None
  if fault == "foreign": reference = _Foreign()
  if fault == "pathlike": root = _Foreign()
  io = []
  def forbidden(*args, **kwargs): io.append("open"); raise AssertionError("IO before snapshot")
  monkeypatch.setattr(runtime.os, "open", forbidden)
  _reject(runtime.validate_installed_python_bundle, root, reference)
  assert io == [] and _CALLS == []


@pytest.mark.parametrize("fault", ["owner", "device", "named-inode"])
def test_actual_fstat_owner_device_and_named_relationship_reject(tmp_path, monkeypatch, fault):
  values = _fixture(tmp_path); original = os.fstat
  calls = []
  def changed(fd):
    info = original(fd)
    fields = list(info)
    if fault == "owner": fields[4] = os.geteuid() + 1
    if fault == "device" and stat.S_ISREG(info.st_mode): fields[2] += 1
    if fault == "named-inode": fields[1] += 1
    calls.append(fd)
    return os.stat_result(fields)
  monkeypatch.setattr(runtime.os, "fstat", changed)
  _reject(runtime.install_locked_python_bundle_stage, *values[:3])
  assert calls


@pytest.mark.parametrize("control", ["body", "cleanup", "both", "ordinary-cleanup"])
def test_owned_fd_once_cleanup_and_body_control_precedence(tmp_path, monkeypatch, control):
  values = _fixture(tmp_path); root = values[0]
  from agentcfg import pi_python_bundle_stage as stage
  actual_open, actual_close, actual_fstat = os.open, os.close, os.fstat
  root_fd, closes = [], []
  body_control = KeyboardInterrupt("body control")
  cleanup_control = SystemExit(8)
  def opened(path, flags, *args, **kwargs):
    fd = actual_open(path, flags, *args, **kwargs)
    if path == str(root): root_fd.append(fd)
    return fd
  def closed(fd):
    actual_close(fd)
    if root_fd and fd == root_fd[0]:
      closes.append(fd)
      if control in ("cleanup", "both"): raise cleanup_control
      if control == "ordinary-cleanup": raise OSError("synthetic cleanup")
  if control in ("body", "both"):
    def body(*args, **kwargs): raise body_control
    monkeypatch.setattr(stage, "install_python_bundle_stage", body)
  monkeypatch.setattr(runtime.os, "open", opened)
  monkeypatch.setattr(runtime.os, "close", closed)
  if control == "ordinary-cleanup": _reject(runtime.install_locked_python_bundle_stage, *values[:3])
  else:
    with pytest.raises(BaseException) as caught: runtime.install_locked_python_bundle_stage(*values[:3])
    assert caught.value is (body_control if control in ("body", "both") else cleanup_control)
  assert len(root_fd) == 1 and closes == root_fd
  with pytest.raises(OSError): actual_fstat(root_fd[0])


def test_all_successfully_acquired_fds_closed_on_read_failure(tmp_path, monkeypatch):
  values = _fixture(tmp_path); opened = []; actual_open, actual_dup, actual_fstat = os.open, os.dup, os.fstat
  def record_open(*args, **kwargs):
    fd = actual_open(*args, **kwargs); opened.append(fd); return fd
  def record_dup(*args, **kwargs):
    fd = actual_dup(*args, **kwargs); opened.append(fd); return fd
  def failure(fd, count): raise OSError("synthetic member read failure")
  monkeypatch.setattr(runtime.os, "open", record_open); monkeypatch.setattr(runtime.os, "dup", record_dup); monkeypatch.setattr(runtime.os, "read", failure)
  _reject(runtime.install_locked_python_bundle_stage, *values[:3])
  assert opened
  for fd in set(opened):
    with pytest.raises(OSError): actual_fstat(fd)


def test_late_member_name_replacement_even_identical_bytes_rejected(tmp_path, monkeypatch):
  values = _fixture(tmp_path); layout = _install(values); root, piece = values[:2]
  target = root / next(row["path"] for row in layout["files"] if row["path"].endswith("__init__.py"))
  inode = target.stat().st_ino; original = os.read; changed = []
  def read(fd, count):
    raw = original(fd, count)
    if not changed and os.fstat(fd).st_ino == inode:
      body = target.read_bytes(); target.unlink(); target.write_bytes(body); changed.append(True)
    return raw
  monkeypatch.setattr(runtime.os, "read", read)
  _reject(runtime.validate_installed_python_bundle, root, piece["python_bundle"])
  assert changed == [True]


def test_late_root_entry_replacement_after_borrowed_stage_rejected(tmp_path, monkeypatch):
  values = _fixture(tmp_path); root = values[0]
  from agentcfg import pi_python_bundle_stage as stage
  original = stage.install_python_bundle_stage
  def install(fd, *args, **kwargs):
    original(fd, *args, **kwargs)
    assert os.fstat(fd).st_ino == root.stat().st_ino
    root.rename(root.with_name("held-original")); root.mkdir(mode=0o700)
  monkeypatch.setattr(stage, "install_python_bundle_stage", install)
  _reject(runtime.install_locked_python_bundle_stage, *values[:3])
  assert (root.with_name("held-original") / "supervisor/python-bundle/inventory.json").exists()


def test_complete_scan_depth_cap_without_following_unrelated_links(tmp_path):
  values = _fixture(tmp_path); current = values[0] / "unrelated"
  current.mkdir(mode=0o700)
  for _ in range(256): current = current / "d"; current.mkdir(mode=0o700)
  _reject(runtime.install_locked_python_bundle_stage, *values[:3])
