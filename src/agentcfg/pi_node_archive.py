"""纯字节发行物选择；元数据一致不授予来源或执行资格。"""

import hashlib
import io
import re
import tarfile
import zlib
from dataclasses import dataclass, field

from .pi_assets import binary_platform
from .process import DependencyError


MAX_ARCHIVE = 128 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MEMBERS = 8192
MAX_BINARY = 128 * 1024 * 1024
MAX_LICENSE = 1024 * 1024
_FIELDS = ("schema", "release", "platform", "archive_sha256", "binary_sha256", "license_sha256")


@dataclass(frozen=True, slots=True)
class NodeArchiveSelection:
  schema: int
  release: str
  platform: str
  archive_sha256: str
  binary_sha256: str
  license_sha256: str


@dataclass(frozen=True, slots=True)
class NodeArchiveFiles:
  selection: NodeArchiveSelection
  binary: bytes = field(repr=False)
  license: bytes = field(repr=False)

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


def _invalid():
  # bare raise 保留自身错误，清除包括调用方正在处理的异常链。
  try:
    raise DependencyError("Pi Node发行物无效")
  except DependencyError as error:
    error.__context__ = None
    error.__cause__ = None
    raise


def capture_node_archive_selection(value):
  if type(value) is not dict: _invalid()
  items = tuple(value.items())
  if any(type(key) is not str for key, _ in items): _invalid()
  data = dict(items)
  if set(data) != set(_FIELDS): _invalid()
  if type(data["schema"]) is not int or data["schema"] != 1: _invalid()
  release = data["release"]
  if type(release) is not str or len(release) > 32 or not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", release): _invalid()
  if any(int(part) > 2**31 - 1 for part in release[1:].split(".")): _invalid()
  platform = data["platform"]
  if type(platform) is not str or platform != "linux-x86_64": _invalid()
  for name in _FIELDS[3:]:
    digest = data[name]
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest): _invalid()
  return NodeArchiveSelection(**data)


def _name(name, root):
  if type(name) is not str or not name or len(name) > 256 or "\\" in name: _invalid()
  if any(ord(char) < 32 or 0x7f <= ord(char) <= 0x9f or 0xd800 <= ord(char) <= 0xdfff for char in name): _invalid()
  if any(part in ("", ".", "..") for part in name.split("/")): _invalid()
  if name != root and not name.startswith(root + "/"): _invalid()


def _select(raw, selection):
  if hashlib.sha256(raw).hexdigest() != selection.archive_sha256: _invalid()
  decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
  expanded = decoder.decompress(raw, MAX_EXPANDED + 1)
  if len(expanded) > MAX_EXPANDED or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data: _invalid()
  root = "node-" + selection.release + "-linux-x64"
  links = {root + "/bin/npm": "../lib/node_modules/npm/bin/npm-cli.js", root + "/bin/npx": "../lib/node_modules/npm/bin/npx-cli.js", root + "/bin/corepack": "../lib/node_modules/corepack/dist/corepack.js"}
  seen, observed = set(), {}
  payloads = {}
  end = 0
  with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
    for member in archive:
      if len(seen) >= MAX_MEMBERS: _invalid()
      if member.offset != end or member.size < 0 or member.pax_headers or member.sparse is not None: _invalid()
      gap = member.offset_data - member.offset
      if gap not in (512, 1536) or member.type not in (tarfile.REGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE): _invalid()
      if member.offset < 0 or member.offset_data > len(expanded): _invalid()
      if expanded[member.offset_data - 512 + 156:member.offset_data - 512 + 157] != member.type: _invalid()
      if gap == 1536 and expanded[member.offset + 156:member.offset + 157] != tarfile.GNUTYPE_LONGNAME: _invalid()
      _name(member.name, root)
      if member.name in seen or member.name == root and member.type != tarfile.DIRTYPE: _invalid()
      seen.add(member.name)
      end = member.offset_data + ((member.size + 511) // 512) * 512
      if end > len(expanded): _invalid()
      if member.type == tarfile.SYMTYPE:
        if member.name not in links or member.linkname != links[member.name]: _invalid()
        observed[member.name] = member.linkname
      if member.name in (root + "/bin/node", root + "/LICENSE"):
        binary = member.name.endswith("/bin/node")
        if member.type != tarfile.REGTYPE or member.mode != (0o755 if binary else 0o644): _invalid()
        if not (64 if binary else 1) <= member.size <= (MAX_BINARY if binary else MAX_LICENSE): _invalid()
        payloads["binary" if binary else "license"] = expanded[member.offset_data:member.offset_data + member.size]
  if not seen or len(expanded) - end < 1024 or any(expanded[end:]): _invalid()
  if observed != links or set(payloads) != {"binary", "license"}: _invalid()
  binary, license = payloads["binary"], payloads["license"]
  if binary_platform(binary) != selection.platform or hashlib.sha256(binary).hexdigest() != selection.binary_sha256 or hashlib.sha256(license).hexdigest() != selection.license_sha256: _invalid()
  return NodeArchiveFiles(selection, binary, license)


def select_node_archive(raw, selection):
  if type(raw) is not bytes or not raw or len(raw) > MAX_ARCHIVE: _invalid()
  if type(selection) is not NodeArchiveSelection: _invalid()
  failed = False
  try:
    snapshot = capture_node_archive_selection({name: getattr(selection, name) for name in _FIELDS})
    result = _select(raw, snapshot)
  except Exception:
    failed = True
  if failed: _invalid()
  return result
