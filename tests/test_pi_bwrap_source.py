"""固定源码归档解析与私人准备；只用合成tar，不联网/编译/执行。"""

import hashlib
import io
import os
from pathlib import Path
import tarfile

import pytest

from agentcfg import pi_bwrap_source as source
from agentcfg.schema import ConfigError


ROOT = "bubblewrap-0.13.0/"


def archive(monkeypatch, rows=None):
  rows = rows if rows is not None else [("COPYING", b"synthetic license", 0o644), ("meson.build", b"root build", 0o644),
    ("tests/meson.build", b"nested build", 0o644), ("ci/check.sh", b"synthetic executable", 0o755),
    ("COPYING.LIB", "COPYING", tarfile.SYMTYPE), ("LICENSE", "COPYING", tarfile.SYMTYPE)]
  stream = io.BytesIO()
  with tarfile.open(fileobj=stream, mode="w:xz") as output:
    for name, value, mode in rows:
      member = tarfile.TarInfo(ROOT + name)
      if isinstance(mode, bytes):
        member.type = mode; member.mode = 0o755
        if mode in (tarfile.SYMTYPE, tarfile.LNKTYPE): member.linkname = value
        output.addfile(member)
      else:
        member.mode = mode; member.size = len(value)
        output.addfile(member, io.BytesIO(value))
  raw = stream.getvalue()
  monkeypatch.setattr(source, "ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())
  return raw


def test_fixed_identity_constants():
  assert source.VERSION == "0.13.0"
  assert source.ARCHIVE_SHA256 == "4734237473c0e5d695e4e9034a34e43b2dbf5164655bd13fa59ae376b2b7a765"
  assert source.SOURCE_URL == "https://github.com/containers/bubblewrap/releases/download/v0.13.0/bubblewrap-0.13.0.tar.xz"


def test_nested_names_and_exact_license_aliases_are_preserved(monkeypatch):
  entries = source.source_entries(archive(monkeypatch))
  assert [name for name, _, _ in entries] == sorted(name for name, _, _ in entries)
  files = {name: (data, mode) for name, data, mode in entries}
  assert files["meson.build"] == (b"root build", 0o644)
  assert files["tests/meson.build"] == (b"nested build", 0o644)
  assert files["COPYING.LIB"] == files["LICENSE"] == files["COPYING"]
  assert files["ci/check.sh"][1] == 0o755


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../escape", "a//file", "./file", "a\\file", "bad\nfile", "a/./file"])
def test_nonstandard_or_escaping_paths_are_rejected(monkeypatch, name):
  with pytest.raises(ConfigError): source.source_entries(archive(monkeypatch, [(name, b"synthetic", 0o644)]))


@pytest.mark.parametrize("rows", [
  [("file", b"one", 0o644), ("file", b"two", 0o644)],
  [("dir", b"file", 0o644), ("dir/nested", b"nested", 0o644)],
  [("dir/nested", b"nested", 0o644), ("dir", b"file", 0o644)],
  [("file", "", tarfile.DIRTYPE), ("file", b"body", 0o644)],
  [("file", b"body", 0o644), ("file", "", tarfile.DIRTYPE)],
  [("other", "COPYING", tarfile.SYMTYPE)],
  [("LICENSE", "../COPYING", tarfile.SYMTYPE)],
  [("COPYING.LIB", "/COPYING", tarfile.SYMTYPE)],
  [("LICENSE", "COPYING", tarfile.SYMTYPE)],
  [("COPYING", "LICENSE", tarfile.SYMTYPE)],
  [("COPYING", b"license", 0o644), ("LICENSE", "COPYING", tarfile.LNKTYPE)],
  [("device", "", tarfile.CHRTYPE)],
  [("fifo", "", tarfile.FIFOTYPE)],
  [("special", b"body", 0o4644)],
  [("special", b"body", 0o2644)],
  [("special", b"body", 0o1644)],
])
def test_duplicates_conflicts_links_devices_and_special_modes_fail(monkeypatch, rows):
  with pytest.raises(ConfigError): source.source_entries(archive(monkeypatch, rows))


def test_directory_entries_and_normal_permissions_are_normalized(monkeypatch):
  rows = [("src", "", tarfile.DIRTYPE), ("src/file", b"source", 0o664), ("script", b"script", 0o775)]
  assert source.source_entries(archive(monkeypatch, rows)) == (("script", b"script", 0o755), ("src/file", b"source", 0o644))


def test_materialized_license_aliases_also_obey_regular_byte_budget(monkeypatch):
  rows = [("COPYING", b"X" * (2 * 1024 * 1024), 0o644), ("COPYING.LIB", "COPYING", tarfile.SYMTYPE), ("LICENSE", "COPYING", tarfile.SYMTYPE)]
  with pytest.raises(ConfigError): source.source_entries(archive(monkeypatch, rows))


@pytest.mark.parametrize("kind", ["compressed", "regular", "entries", "hash", "format", "wrong-root"])
def test_limits_format_and_fixed_digest_cannot_be_bypassed(monkeypatch, kind):
  if kind == "regular": raw = archive(monkeypatch, [("big", b"X" * (4 * 1024 * 1024 + 1), 0o644)])
  elif kind == "entries": raw = archive(monkeypatch, [("file-" + str(i), b"", 0o644) for i in range(257)])
  else: raw = archive(monkeypatch)
  if kind == "compressed": raw = b"X" * (2 * 1024 * 1024 + 1)
  if kind == "format": raw = b"synthetic-private-marker"
  if kind == "wrong-root":
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:xz") as output:
      member = tarfile.TarInfo("other-version/file"); member.size = 1; output.addfile(member, io.BytesIO(b"x"))
    raw = stream.getvalue()
  if kind == "hash": monkeypatch.setattr(source, "ARCHIVE_SHA256", "0" * 64)
  else: monkeypatch.setattr(source, "ARCHIVE_SHA256", hashlib.sha256(raw).hexdigest())
  with pytest.raises(ConfigError) as error: source.source_entries(raw)
  assert "synthetic-private-marker" not in str(error.value)


def test_prepare_preserves_nested_files_and_private_execution_bits(tmp_path, monkeypatch):
  raw = archive(monkeypatch); target = tmp_path / "source"
  names = source.prepare_source(raw, target)
  assert names == tuple(name for name, _, _ in source.source_entries(raw))
  assert (target / "meson.build").read_bytes() == b"root build"
  assert (target / "tests/meson.build").read_bytes() == b"nested build"
  assert (target / "COPYING.LIB").is_file() and not (target / "COPYING.LIB").is_symlink()
  assert (target / "LICENSE").read_bytes() == b"synthetic license"
  assert target.stat().st_mode & 0o777 == 0o700
  assert (target / "meson.build").stat().st_mode & 0o777 == 0o600
  assert (target / "ci/check.sh").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "mode"])
def test_existing_targets_are_never_overwritten_or_deleted(tmp_path, monkeypatch, kind):
  raw = archive(monkeypatch); target = tmp_path / "source"
  if kind == "symlink":
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir(mode=0o700); target.symlink_to(elsewhere)
  else:
    target.mkdir(mode=0o700)
    if kind == "file": (target / "sentinel").write_bytes(b"untouched")
    if kind == "directory": (target / "sentinel").mkdir()
    if kind == "mode": target.chmod(0o755)
  with pytest.raises(ConfigError): source.prepare_source(raw, target)
  if kind == "file": assert (target / "sentinel").read_bytes() == b"untouched"
  if kind == "directory": assert (target / "sentinel").is_dir()
  if kind == "symlink": assert target.is_symlink() and list(elsewhere.iterdir()) == []
  if kind == "mode": assert target.stat().st_mode & 0o777 == 0o755


def test_bad_input_never_creates_target_and_empty_owned_directory_is_allowed(tmp_path, monkeypatch):
  raw = archive(monkeypatch); target = tmp_path / "source"
  with pytest.raises(ConfigError): source.prepare_source(raw + b"invalid", target)
  assert not target.exists()
  target.mkdir(mode=0o700)
  assert source.prepare_source(raw, target)


def test_partial_write_failure_never_removes_or_overwrites_created_files(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  raw = archive(monkeypatch); target = tmp_path / "source"; original = Tree.write_new
  calls = []
  def fail_after_one(tree, name, data):
    calls.append(name)
    if len(calls) == 2: raise OSError("synthetic-private-marker")
    return original(tree, name, data)
  monkeypatch.setattr(Tree, "write_new", fail_after_one)
  with pytest.raises(ConfigError) as error: source.prepare_source(raw, target)
  assert "synthetic-private-marker" not in str(error.value)
  assert (target / calls[0]).read_bytes() == b"synthetic license"
  with pytest.raises(ConfigError): source.prepare_source(raw, target)
