"""独立的小型内存发行物，不运行二进制。"""

import dataclasses
import gzip
import hashlib
import io
import tarfile
import traceback

import pytest

from agentcfg import pi_node_archive as codec
from agentcfg.process import DependencyError


ROOT = "node-v24.14.0-linux-x64"
LINKS = {"npm": "../lib/node_modules/npm/bin/npm-cli.js", "npx": "../lib/node_modules/npm/bin/npx-cli.js", "corepack": "../lib/node_modules/corepack/dist/corepack.js"}
BINARY = b"\x7fELF\x02\x01" + bytes(10) + b"\x02\x00\x3e\x00" + bytes(44)
LICENSE = b"original\r\n\xff LICENSE\n"


def fixture(change=None, long=False):
  entries = [(ROOT, b"", tarfile.DIRTYPE, 0o755, ""),
    (ROOT + "/bin/node", BINARY, tarfile.REGTYPE, 0o755, ""),
    (ROOT + "/LICENSE", LICENSE, tarfile.REGTYPE, 0o644, "")]
  entries += [(ROOT + "/bin/" + key, b"", tarfile.SYMTYPE, 0o777, value) for key, value in LINKS.items()]
  if long: entries.append((ROOT + "/" + "a" * 110, b"unused", tarfile.REGTYPE, 0o644, ""))
  if change: entries = change(entries)
  out = io.BytesIO()
  with tarfile.open(fileobj=out, mode="w", format=tarfile.GNU_FORMAT) as archive:
    for name, body, kind, mode, link in entries:
      info = tarfile.TarInfo(name)
      info.type, info.mode, info.linkname = kind, mode, link
      info.size = len(body) if kind == tarfile.REGTYPE else 0
      archive.addfile(info, io.BytesIO(body) if info.size else None)
  return gzip.compress(out.getvalue(), mtime=0)


def declaration(raw):
  return {"schema": 1, "release": "v24.14.0", "platform": "linux-x86_64", "archive_sha256": hashlib.sha256(raw).hexdigest(), "binary_sha256": hashlib.sha256(BINARY).hexdigest(), "license_sha256": hashlib.sha256(LICENSE).hexdigest()}


def select(raw):
  return codec.select_node_archive(raw, codec.capture_node_archive_selection(declaration(raw)))


def invalid(action):
  try:
    raise RuntimeError("SYNTHETIC_SECRET")
  except RuntimeError:
    with pytest.raises(DependencyError) as caught: action()
  error = caught.value
  assert type(error) is DependencyError
  assert error.args == ("Pi Node发行物无效",)
  assert error.__context__ is None and error.__cause__ is None
  assert "SYNTHETIC_SECRET" not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize("long", [False, True])
def test_original_payload_and_independent_frozen_selection(long):
  raw = fixture(long=long)
  data = declaration(raw)
  selection = codec.capture_node_archive_selection(data)
  data["release"] = "v0.0.0"
  result = codec.select_node_archive(raw, selection)
  assert result.binary == BINARY and result.license == LICENSE
  assert result.selection == selection and result.selection is not selection
  assert not result.writer_lock_verified and not result.database_allowed and not result.can_take_over
  assert "original" not in repr(result) and "ELF" not in repr(result)
  with pytest.raises(dataclasses.FrozenInstanceError): result.binary = b"changed"
  with pytest.raises(dataclasses.FrozenInstanceError): selection.schema = 2


@pytest.mark.parametrize("field,value", [("schema", True), ("schema", 2), ("release", "v01.0.0"), ("release", "v2147483648.0.0"), ("release", "v1.2.3-beta"), ("release", "v١.2.3"), ("platform", "darwin-arm64"), ("archive_sha256", "A" * 64), ("binary_sha256", None), ("license_sha256", "0" * 63)])
def test_closed_declaration(field, value):
  data = declaration(fixture()); data[field] = value
  invalid(lambda: codec.capture_node_archive_selection(data))


def test_exact_types_before_foreign_hooks():
  calls = []
  armed = False
  class Poison(str):
    def __hash__(self):
      if armed: calls.append("hash"); raise AssertionError()
      return str.__hash__(self)
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
  class Dict(dict):
    def items(self): calls.append("items"); raise AssertionError()
  key = Poison("schema")
  data = {key: 1}; calls.clear(); armed = True
  invalid(lambda: codec.capture_node_archive_selection(data))
  invalid(lambda: codec.capture_node_archive_selection(Dict()))
  invalid(lambda: codec.capture_node_archive_selection({**declaration(fixture()), "release": Poison("v1.2.3")}))
  invalid(lambda: codec.select_node_archive(bytearray(fixture()), object()))
  assert calls == []


@pytest.mark.parametrize("mutation", ["extra", "missing", "uninitialized", "subclass", "reflect"])
def test_selection_revalidation(mutation):
  raw = fixture(); data = declaration(raw)
  if mutation == "extra": data["extra"] = 1
  if mutation == "missing": del data["schema"]
  if mutation in ("extra", "missing"):
    invalid(lambda: codec.capture_node_archive_selection(data)); return
  selection = codec.capture_node_archive_selection(data)
  if mutation == "uninitialized": selection = object.__new__(codec.NodeArchiveSelection)
  if mutation == "subclass":
    class Child(codec.NodeArchiveSelection): pass
    selection = Child(**data)
  if mutation == "reflect": object.__setattr__(selection, "schema", True)
  invalid(lambda: codec.select_node_archive(raw, selection))


@pytest.mark.parametrize("field", ["archive_sha256", "binary_sha256", "license_sha256"])
def test_hashes(field):
  raw = fixture(); data = declaration(raw); data[field] = "0" * 64
  invalid(lambda: codec.select_node_archive(raw, codec.capture_node_archive_selection(data)))


@pytest.mark.parametrize("kind", ["duplicate", "outside", "dot", "backslash", "control", "surrogate", "rootfile", "hardlink", "missinglink", "extralink", "wronglink", "node_mode", "license_mode", "node_small", "license_empty", "wrong_elf"])
def test_member_contract(kind):
  def change(rows):
    rows = list(rows)
    if kind == "duplicate": rows.append(rows[1])
    elif kind in ("outside", "dot", "backslash", "control", "surrogate"):
      name = {"outside": "outside/a", "dot": ROOT + "/../a", "backslash": ROOT + "/a\\b", "control": ROOT + "/a\x7fb", "surrogate": ROOT + "/\udcff"}[kind]
      rows.append((name, b"x", tarfile.REGTYPE, 0o644, ""))
    elif kind == "rootfile": rows[0] = (ROOT, b"x", tarfile.REGTYPE, 0o644, "")
    elif kind == "hardlink": rows.append((ROOT + "/hard", b"", tarfile.LNKTYPE, 0o644, "x"))
    elif kind == "missinglink": rows.pop()
    elif kind == "extralink": rows.append((ROOT + "/other", b"", tarfile.SYMTYPE, 0o777, "x"))
    elif kind == "wronglink": rows[-1] = (*rows[-1][:4], "wrong")
    elif kind == "node_mode": rows[1] = (*rows[1][:3], 0o700, "")
    elif kind == "license_mode": rows[2] = (*rows[2][:3], 0o600, "")
    elif kind == "node_small": rows[1] = (rows[1][0], b"small", *rows[1][2:])
    elif kind == "license_empty": rows[2] = (rows[2][0], b"", *rows[2][2:])
    elif kind == "wrong_elf": rows[1] = (rows[1][0], bytes(64), *rows[1][2:])
    return rows
  invalid(lambda: select(fixture(change)))


@pytest.mark.parametrize("kind", ["empty", "plain", "truncated", "crc", "concat", "rawtail", "tartail", "secondtar", "shortpadding", "headergap", "pax", "gnu_twice", "sparse"])
def test_whole_gzip_tar_shape(kind):
  raw = fixture()
  if kind == "empty": raw = b""
  elif kind == "plain": raw = gzip.decompress(raw)
  elif kind == "truncated": raw = raw[:-3]
  elif kind == "crc": raw = raw[:-8] + bytes([raw[-8] ^ 1]) + raw[-7:]
  elif kind == "concat": raw += raw
  elif kind == "rawtail": raw += b"secret"
  else:
    tar = gzip.decompress(raw)
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive: members = list(archive)
    end = members[-1].offset_data + ((members[-1].size + 511) // 512) * 512
    if kind == "tartail": tar = tar[:end] + b"\0" * 1024 + b"secret"
    elif kind == "secondtar": tar = tar[:end] + b"\0" * 1024 + tar
    elif kind == "shortpadding": tar = tar[:end] + b"\0" * 512
    elif kind == "headergap": tar = tar[:512] + b"\0" * 512 + tar[512:]
    elif kind in ("pax", "gnu_twice"):
      info = tarfile.TarInfo("ignored"); info.type = tarfile.XHDTYPE if kind == "pax" else tarfile.GNUTYPE_LONGNAME
      body = b"12 path=abc\n" if kind == "pax" else (ROOT + "/bin/node\0").encode()
      info.size = len(body)
      prefix = info.tobuf(format=tarfile.GNU_FORMAT) + body + b"\0" * (512-len(body))
      tar = prefix + (prefix if kind == "gnu_twice" else b"") + tar
    elif kind == "sparse":
      info = tarfile.TarInfo(ROOT + "/sparse"); info.type = tarfile.GNUTYPE_SPARSE
      tar = info.tobuf(format=tarfile.GNU_FORMAT) + tar
    raw = gzip.compress(tar)
  invalid(lambda: select(raw))


@pytest.mark.parametrize("cap", ["MAX_ARCHIVE", "MAX_EXPANDED", "MAX_MEMBERS", "MAX_BINARY", "MAX_LICENSE"])
def test_budgets_only_lowered(monkeypatch, cap):
  raw = fixture(); monkeypatch.setattr(codec, cap, 1)
  invalid(lambda: select(raw))


def test_no_selected_payload_or_header_is_in_fixed_error():
  raw = b"SYNTHETIC_SECRET"
  invalid(lambda: select(raw))


def test_foreign_failure_does_not_escape_or_get_mutated(monkeypatch):
  foreign = ValueError("SYNTHETIC_SECRET")
  def fail(raw): raise foreign
  monkeypatch.setattr(codec, "binary_platform", fail)
  invalid(lambda: select(fixture()))
  assert foreign.args == ("SYNTHETIC_SECRET",) and foreign.__cause__ is None


@pytest.mark.parametrize("value", [None, [], True, 1, 1.0, "path", memoryview(b"x")])
def test_raw_native_bytes_only(value):
  invalid(lambda: codec.select_node_archive(value, object()))


@pytest.mark.parametrize("name", [ROOT + "/a\x1fb", ROOT + "/a\x9fb", ROOT + "//a", ROOT + "/./a", ROOT + "-other/a", "/" + ROOT + "/a", ROOT + "/" + "a" * 256])
def test_complete_literal_name_domain(name):
  raw = fixture(lambda rows: rows + [(name, b"x", tarfile.REGTYPE, 0o644, "")])
  invalid(lambda: select(raw))


@pytest.mark.parametrize("index", [1, 2])
def test_both_selected_members_required(index):
  raw = fixture(lambda rows: rows[:index] + rows[index+1:])
  invalid(lambda: select(raw))


def test_selection_fields_with_native_subclasses_never_compare():
  calls = []
  class Number(int):
    def __eq__(self, value): calls.append("eq"); raise AssertionError()
  raw = fixture(); data = declaration(raw); data["schema"] = Number(1)
  invalid(lambda: codec.capture_node_archive_selection(data))
  selection = codec.capture_node_archive_selection(declaration(raw))
  object.__setattr__(selection, "schema", Number(1))
  invalid(lambda: codec.select_node_archive(raw, selection))
  assert calls == []
