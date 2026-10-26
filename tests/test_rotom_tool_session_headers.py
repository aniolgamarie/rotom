"""只用临时 HOME 会话头，不启动宿主，不读取正文。"""

from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import run_owners, tool_session_headers as headers
from agentcfg.omp_identity import native_identity
from agentcfg.sessions import SessionError


SESSION = "12345678-1234-4234-8234-123456789abc"
OTHER = "87654321-4321-4321-8321-cba987654321"


def title_slot(title="fixture-private-title", source=None, **changes):
  """固定公开 OMP serializeTitleSlot 格式，使用合成标题和时间，不执行上游代码。"""
  value = {"type": "title", "v": 1, "title": title}
  if source is not None:
    value["source"] = source
  value.update(updatedAt="2026-01-01T00:00:00.000Z", pad="")
  value.update(changes)
  def encode():
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
  value["pad"] = " " * (256 - len(encode()))
  return encode()


def _native(tmp_path, agent):
  workspace = SimpleNamespace(agent=agent, profile=agent + "-test",
    instance=tmp_path / "instance", binding={"machine": "fixture", "local": str(tmp_path / "local")})
  cwd = tmp_path / "project"
  cwd.mkdir()
  root = (workspace.instance / "pi-home/sessions" if workspace.agent == "pi"
    else native_identity(workspace.profile, workspace.instance).agent_dir / "sessions")
  directory = root if workspace.agent == "pi" else root / "cwd-bucket"
  directory.mkdir(parents=True)
  value = {"type": "session", "id": SESSION, "cwd": str(cwd), "timestamp": "2026-01-01T00:00:00.000Z",
    "version": 3, "parentSession": None}
  path = directory / "unrelated-filename.jsonl"
  prefix = b"" if agent == "pi" else title_slot()
  path.write_bytes(prefix + (json.dumps(value) + "\nBODY-CANARY\n").encode())
  return workspace, root, path, value


@pytest.fixture(params=["pi", "omp"])
def native(tmp_path, request):
  return _native(tmp_path, request.param)


@pytest.fixture
def omp_native(tmp_path):
  return _native(tmp_path, "omp")


def fails(code, function, *args):
  with pytest.raises(SessionError) as error:
    function(*args)
  assert error.value.code == code


def test_exact_projection_read_only_and_no_body_access(native, monkeypatch):
  workspace, root, path, value = native
  original = headers.os.read
  consumed = []

  def read(fd, size):
    assert size == 1
    byte = original(fd, size)
    consumed.append(byte)
    return byte

  monkeypatch.setattr(headers.os, "read", read)
  before = sorted(str(item.relative_to(root)) for item in root.rglob("*"))
  target = headers.lookup(workspace, SESSION)
  prefix = b"" if workspace.agent == "pi" else title_slot()
  assert b"".join(consumed) == prefix + (json.dumps(value) + "\n").encode()
  assert target.path == path
  assert target.known.cwd == value["cwd"]
  assert target.known.confirmation == target.known.cwd_status == "historical"
  home = workspace.instance / ("pi-home" if workspace.agent == "pi" else "user-home")
  kind = "pi-home" if workspace.agent == "pi" else "omp-managed-home"
  assert target.known.ref.native_home_ref == run_owners.native_home_key({"kind": kind, "path": str(home)})
  assert target.file_identity == (path.stat().st_dev, path.stat().st_ino)
  assert sorted(str(item.relative_to(root)) for item in root.rglob("*")) == before


def test_native_public_modes_and_append_allowed(native):
  workspace, root, path, _ = native
  root.chmod(0o755)
  path.parent.chmod(0o755)
  path.chmod(0o644)
  target = headers.lookup(workspace, SESSION)
  with path.open("a") as stream:
    stream.write("ADDED-BODY\n")
  assert headers.recheck(workspace, target).header_digest == target.header_digest


def test_missing_prefix_and_cross_scope(native, tmp_path):
  workspace, _, _, _ = native
  fails(5, headers.lookup, workspace, OTHER)
  for value in (SESSION[:8], "latest", "/tmp/fictional.jsonl"):
    fails(2, headers.lookup, workspace, value)
  assert headers.candidates(replace_workspace(workspace, instance=tmp_path / "another")) == ()
  target = headers.lookup(workspace, SESSION)
  fails(4, headers.recheck, workspace, replace(target, known=replace(target.known, profile="another")))


def replace_workspace(workspace, **values):
  return SimpleNamespace(**{**vars(workspace), **values})


def test_duplicate_id_fail_closed(native):
  workspace, root, path, _ = native
  duplicate = root / "duplicate.jsonl"
  duplicate.write_bytes(path.read_bytes())
  fails(4, headers.lookup, workspace, SESSION)
  fails(4, headers.candidates, workspace)


@pytest.mark.parametrize("change", ["id", "cwd", "timestamp", "version", "duplicate-key", "oversized", "invalid-json"])
def test_malformed_header_fail_closed(native, change):
  workspace, _, path, value = native
  value.update({"id": "prefix"} if change == "id" else {})
  value.update({"cwd": "relative"} if change == "cwd" else {})
  value.update({"timestamp": "bad"} if change == "timestamp" else {})
  value.update({"version": True} if change == "version" else {})
  raw = json.dumps(value)
  if change == "duplicate-key":
    raw = raw[:-1] + ', "id": "' + SESSION + '"}'
  if change == "oversized":
    raw = " " * (headers._HEADER_LIMIT + 1)
  if change == "invalid-json":
    raw = "{bad"
  path.write_text(raw + "\n")
  fails(5, headers.lookup, workspace, SESSION)


def test_recheck_changed_header_and_inode(native):
  workspace, _, path, value = native
  target = headers.lookup(workspace, SESSION)
  value["parentSession"] = "changed"
  path.write_text(json.dumps(value) + "\n")
  fails(4, headers.recheck, workspace, target)
  target = headers.lookup(workspace, SESSION)
  replacement = path.with_suffix(".tmp")
  replacement.write_bytes(path.read_bytes())
  replacement.replace(path)
  fails(4, headers.recheck, workspace, target)


def test_cwd_missing_at_recheck(native):
  workspace, _, _, value = native
  target = headers.lookup(workspace, SESSION)
  Path(value["cwd"]).rmdir()
  fails(5, headers.recheck, workspace, target)


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "writable-file", "writable-directory", "root-symlink"])
def test_unsafe_native_paths(native, unsafe):
  workspace, root, path, _ = native
  if unsafe == "symlink":
    moved = path.with_suffix(".data")
    path.rename(moved)
    path.symlink_to(moved)
  elif unsafe == "hardlink":
    os.link(path, path.with_suffix(".data"))
  elif unsafe == "writable-file":
    path.chmod(0o666)
  elif unsafe == "writable-directory":
    path.parent.chmod(0o777)
  else:
    moved = root.with_name("moved-sessions")
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
  fails(4, headers.lookup, workspace, SESSION)


def test_scan_budget_and_fixed_depth(native, monkeypatch):
  workspace, root, path, value = native
  deep = path.parent / "deeper"
  deep.mkdir()
  value["id"] = OTHER
  (deep / "not-in-layout.jsonl").write_text(json.dumps(value) + "\n")
  fails(5, headers.lookup, workspace, OTHER)
  monkeypatch.setattr(headers, "_SCAN_LIMIT", 1)
  fails(5, headers.candidates, workspace)


def test_dangling_native_ancestor_is_conflict(native):
  workspace, root, _, _ = native
  moved = root.parent.with_name("original-native-parent")
  root.parent.rename(moved)
  root.parent.symlink_to(root.parent.with_name("missing-native-parent"), target_is_directory=True)
  fails(4, headers.lookup, workspace, SESSION)


@pytest.mark.parametrize("source", [None, "auto", "user"])
def test_omp_fixed_256_byte_utf8_slot_with_current_v3_header_is_not_transcript(omp_native, monkeypatch, source):
  workspace, root, path, value = omp_native
  slot = title_slot("合成标题 🌱", source=source)
  assert len(slot) == 256 and slot.endswith(b"}\n")
  value.update(additionalDirectories=[], title="legacy-private-title", providerPromptCacheKey="synthetic-private-key")
  header = (json.dumps(value) + "\n").encode()
  path.write_bytes(slot + header + b"BODY-CANARY-NEVER-READ\n")
  original = headers.os.read
  consumed = []
  def read(fd, size):
    assert size == 1
    assert sum(map(len, consumed)) < len(slot + header), "transcript read attempted"
    byte = original(fd, size)
    consumed.append(byte)
    return byte
  before = tuple(root.rglob("*"))
  monkeypatch.setattr(headers.os, "read", read)
  target = headers.lookup(workspace, SESSION)
  assert b"".join(consumed) == slot + header
  assert target.known.ref.native_ref == SESSION and target.known.cwd == value["cwd"]
  assert "private" not in repr(target)
  assert tuple(root.rglob("*")) == before


def test_omp_title_change_preserves_header_digest_and_target_identity(omp_native):
  workspace, _, path, value = omp_native
  target = headers.lookup(workspace, SESSION)
  header = (json.dumps(value) + "\n").encode()
  with path.open("r+b") as stream:
    stream.write(title_slot("a new title", source="user"))
  current = headers.recheck(workspace, target)
  assert current.header_digest == target.header_digest
  import hashlib
  assert current.header_digest == hashlib.sha256(header[:-1]).hexdigest()
  assert current.file_identity == target.file_identity


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
@pytest.mark.parametrize("agent,line_kind", [("pi", "header"), ("omp", "header"), ("omp", "title")])
def test_non_utf8_metadata_is_rejected_without_reading_body(tmp_path, monkeypatch, encoding, agent, line_kind):
  workspace, root, path, value = _native(tmp_path, agent)
  if line_kind == "title":
    prefix = b""
    metadata = title_slot()[:-1].decode("utf-8")
    suffix = (json.dumps(value) + "\nBODY-CANARY-NEVER-READ\n").encode()
  else:
    prefix = title_slot() if agent == "omp" else b""
    metadata = json.dumps(value)
    suffix = b"BODY-CANARY-NEVER-READ\n"
  # bytes 的 json.loads 会自动侦测这些编码；原生只接受 UTF-8 JSONL。
  line = metadata.encode(encoding) + b"\n"
  path.write_bytes(prefix + line + suffix)
  original = headers.os.read
  consumed = []
  boundary = len(prefix + line)
  def read(fd, size):
    assert size == 1
    assert len(consumed) < boundary, "metadata rejection read into the next line"
    byte = original(fd, size)
    consumed.append(byte)
    return byte
  before = tuple(root.rglob("*"))
  monkeypatch.setattr(headers.os, "read", read)
  fails(5, headers.lookup, workspace, SESSION)
  assert b"".join(consumed) == prefix + line
  assert tuple(root.rglob("*")) == before


@pytest.mark.parametrize("damage", ["short", "long", "unknown-field", "duplicate-key", "wrong-version", "bool-version",
  "title-type", "timestamp-type", "pad-tab", "pad-null", "bad-source", "missing-pad", "crlf", "unterminated",
  "bom", "leading-space"])
def test_malformed_omp_slot_never_unlocks_a_second_line(omp_native, monkeypatch, damage):
  workspace, _, path, value = omp_native
  if damage == "unknown-field": slot = title_slot(extra=True)
  elif damage == "wrong-version": slot = title_slot(v=2)
  elif damage == "bool-version": slot = title_slot(v=True)
  elif damage == "title-type": slot = title_slot(title=23)
  elif damage == "timestamp-type": slot = title_slot(updatedAt=23)
  elif damage == "bad-source": slot = title_slot(source="other")
  else: slot = title_slot()
  if damage == "short": slot = slot.replace(b" ", b"", 1)
  elif damage == "long": slot = slot[:-1] + b" \n"
  elif damage == "duplicate-key":
    slot = slot.replace(b'"v":1,', b'"v":1,"v":1,', 1).replace(b" " * 6, b"", 1)
  elif damage == "pad-tab": slot = slot.replace(b"  ", b"\\t", 1)
  elif damage == "pad-null": slot = slot.replace(b" " * 6, b"\\u0000", 1)
  elif damage == "missing-pad":
    decoded = json.loads(slot)
    del decoded["pad"]
    slot = (json.dumps(decoded, separators=(",", ":")) + "\n").encode()
  elif damage == "crlf": slot = slot.replace(b" ", b"", 1)[:-1] + b"\r\n"
  elif damage == "bom": slot = b"\xef\xbb\xbf" + slot.replace(b" " * 3, b"", 1)
  elif damage == "leading-space": slot = b" " + slot.replace(b" ", b"", 1)
  elif damage == "unterminated": slot = slot[:-1]
  payload = slot if damage == "unterminated" else slot + (json.dumps(value) + "\nBODY-CANARY\n").encode()
  path.write_bytes(payload)
  original = headers.os.read
  consumed = []
  def read(fd, size):
    byte = original(fd, size)
    consumed.append(byte)
    return byte
  monkeypatch.setattr(headers.os, "read", read)
  fails(5, headers.lookup, workspace, SESSION)
  assert b"".join(consumed) == slot


def test_two_slots_are_not_skipped_recursively(omp_native, monkeypatch):
  workspace, _, path, value = omp_native
  prefix = title_slot() * 2
  path.write_bytes(prefix + (json.dumps(value) + "\nBODY-CANARY\n").encode())
  original = headers.os.read
  consumed = []
  def read(fd, size):
    byte = original(fd, size)
    consumed.append(byte)
    return byte
  monkeypatch.setattr(headers.os, "read", read)
  fails(5, headers.lookup, workspace, SESSION)
  assert b"".join(consumed) == prefix


def test_pi_never_skips_even_valid_omp_slot(tmp_path, monkeypatch):
  workspace, _, path, value = _native(tmp_path, "pi")
  slot = title_slot()
  path.write_bytes(slot + (json.dumps(value) + "\nBODY-CANARY\n").encode())
  original = headers.os.read
  consumed = []
  def read(fd, size):
    byte = original(fd, size)
    consumed.append(byte)
    return byte
  monkeypatch.setattr(headers.os, "read", read)
  fails(5, headers.lookup, workspace, SESSION)
  assert b"".join(consumed) == slot


@pytest.mark.parametrize("version", [None, 1, 2, 3])
def test_omp_legacy_single_header_remains_supported(omp_native, version):
  workspace, _, path, value = omp_native
  if version is None:
    value.pop("version")
  else:
    value["version"] = version
  path.write_text(json.dumps(value) + "\nBODY-CANARY\n")
  assert headers.lookup(workspace, SESSION).known.ref.native_ref == SESSION
