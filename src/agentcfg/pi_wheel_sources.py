"""Wheel 来源与固定 Full 引用的纯数据规则；不授予来源或安装资格。"""

import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit


_FIELDS = set("kind package version url wheel_filename archive_digest size license_files".split())
_NAMES = {"attrs", "jsonschema", "jsonschema-specifications", "pyyaml", "referencing", "rpds-py", "typing-extensions"}
_SOURCE = "agents/pi/runtime/durable-python-bundle.json"
_PATH = "runtime/durable-python-bundle.json"
_HEX = r"[0-9a-f]{64}"
_ID = r"[a-z][a-z0-9_-]{0,63}"


def _fail():
  raise ValueError()


def _boundary(function, *args):
  failed = False
  try:
    result = function(*args)
  except Exception:
    failed = True
  if failed:
    # 新建固定错误，清理外层活跃异常；控制类异常保持原对象。
    try:
      raise ValueError("pi-wheel-source")
    except ValueError as error:
      error.__cause__ = None
      error.__context__ = None
      raise
  return result


class _Snapshot:
  """在任何哈希或外来方法前限制原生树，且只复制所选字段。"""

  def __init__(self):
    self.nodes = 0
    self.active = set()

  def walk(self, value, depth=0):
    self.nodes += 1
    if self.nodes > 100000 or depth > 16:
      _fail()
    kind = type(value)
    if kind is str:
      if len(value) > 4096:
        _fail()
      value.encode("utf-8", "strict")
    elif kind is int:
      if not -(2 ** 63) <= value <= 2 ** 63 - 1:
        _fail()
    elif kind in (dict, list):
      if len(value) > 100000 or id(value) in self.active:
        _fail()
      self.active.add(id(value))
      if kind is dict:
        result = {}
        for key, child in value.items():
          if type(key) is not str:
            _fail()
          key = self.walk(key, depth + 1)
          result[key] = self.walk(child, depth + 1)
      else:
        result = [self.walk(child, depth + 1) for child in value]
      self.active.remove(id(value))
      return result
    elif kind not in (bool, type(None)):
      _fail()
    return value

  def keys(self, value, cap):
    if type(value) is not dict or len(value) > cap:
      _fail()
    # 单遍捕获已验证的键值对；后续不再查找或遍历 caller 字典。
    pairs = []
    for key, child in value.items():
      if type(key) is not str:
        _fail()
      self.walk(key)
      pairs.append((key, child))
    return pairs


def _text(value, cap, *, ascii_only=False):
  if type(value) is not str or not 1 <= len(value) <= cap:
    _fail()
  if len(value.encode("ascii" if ascii_only else "utf-8", "strict")) > cap:
    _fail()
  return value


def _match(value, pattern):
  if type(value) is not str or re.fullmatch(pattern, value) is None:
    _fail()


def _integer(value, low, high):
  if type(value) is not int or not low <= value <= high:
    _fail()


def _locked(value):
  if type(value) is not bool:
    _fail()


def _clean_path(value):
  if ("\\" in value or any(ord(c) < 33 or ord(c) == 127 or c.isspace() for c in value)
      or any(part in ("", ".", "..") for part in value.split("/"))):
    _fail()


def _wheel(source, locked):
  expected = _FIELDS | ({"vendor_path"} if locked else set())
  if type(source) is not dict or set(source) != expected or source["kind"] != "wheel":
    _fail()
  package = _text(source["package"], 96, ascii_only=True)
  _match(package, r"[a-z0-9]+(?:-[a-z0-9]+)*")
  version = _text(source["version"], 64, ascii_only=True)
  _match(version, r"(?:0|[1-9][0-9]{0,7})(?:\.(?:0|[1-9][0-9]{0,7})){0,2}")
  filename = _text(source["wheel_filename"], 256, ascii_only=True)
  tag = r"[a-z0-9_]+(?:\.[a-z0-9_]+)*"
  _match(filename, re.escape(package.replace("-", "_") + "-" + version + "-") + tag + "-" + tag + "-" + tag + r"\.whl")
  _match(source["archive_digest"], _HEX)
  _integer(source["size"], 1, 2097152)
  url = _text(source["url"], 4096)
  if (any(ord(c) < 33 or 127 <= ord(c) <= 159 or c.isspace() for c in url)
      or any(c in url for c in ("\\", "%", "?", "#"))):
    _fail()
  parsed = urlsplit(url)
  # hostname 会先做 Unicode lower；必须先拒绝原 netloc 的非 ASCII 字符。
  parsed.netloc.encode("ascii", "strict")
  if (parsed.scheme != "https" or not parsed.netloc or parsed.username is not None
      or parsed.password is not None or ":" in parsed.netloc or parsed.query or parsed.fragment):
    _fail()
  host = parsed.hostname
  if host is None or len(host) > 253:
    _fail()
  labels = host.split(".")
  if len(labels) < 2:
    _fail()
  for label in labels:
    _match(label, r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
  if re.search(r"[a-z]", labels[-1]) is None:
    _fail()
  try:
    ipaddress.ip_address(host)
  except ValueError:
    pass
  else:
    _fail()
  if not parsed.path.startswith("/"):
    _fail()
  _clean_path(parsed.path[1:])
  if parsed.path.rsplit("/", 1)[-1] != filename:
    _fail()
  licenses = source["license_files"]
  if type(licenses) is not list or not 1 <= len(licenses) <= 16:
    _fail()
  prefix = package.replace("-", "_") + "-" + version + ".dist-info/licenses/"
  for path in licenses:
    _text(path, 512, ascii_only=True)
    _clean_path(path)
    if not path.startswith(prefix) or not path[len(prefix):]:
      _fail()
  if licenses != sorted(set(licenses)):
    _fail()
  if locked and source["vendor_path"] != "vendor/wheels/" + source["archive_digest"] + "/" + filename:
    _fail()


def _validate_source(source, locked):
  _locked(locked)
  _wheel(_Snapshot().walk(source), locked)


def validate_wheel_source(source, *, locked):
  """只校验声明或锁的 wheel 记录。"""
  return _boundary(_validate_source, source, locked)


def _identity(source):
  source = _Snapshot().walk(source)
  _wheel(source, True)
  projection = {key: value for key, value in source.items() if key not in ("url", "vendor_path")}
  raw = json.dumps(projection, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
  return hashlib.sha256(raw).hexdigest()


def wheel_source_identity(source):
  """合法锁记录的非秘密投影 SHA256；不签发来源引用。"""
  return _boundary(_identity, source)


def _inputs(piece, sources):
  snapshot = _Snapshot()
  piece_pairs = snapshot.keys(piece, 100000)
  selected = {key: snapshot.walk(value, 1) for key, value in piece_pairs
              if key in ("source_ids", "runtime_files", "python_bundle")}
  source_pairs = snapshot.keys(sources, 4096)
  records = {}
  for key, record in source_pairs:
    _match(key, _ID)
    captured = dict(snapshot.keys(record, 100000))
    kind = snapshot.walk(captured.get("kind"), 2)
    if type(kind) is not str:
      _fail()
    records[key] = snapshot.walk(captured, 1) if kind == "wheel" else {"kind": kind}
  return selected, records


def _reference(profile_id, piece, sources, locked):
  _locked(locked)
  if type(profile_id) is not str or profile_id not in ("pi-base", "pi-full"):
    _fail()
  ids = piece.get("source_ids")
  if type(ids) is not list or len(ids) > 4096:
    _fail()
  for identity in ids:
    _match(identity, _ID)
    if identity not in sources:
      _fail()
  if len(set(ids)) != len(ids):
    _fail()
  for identity, record in sources.items():
    if record["kind"] == "wheel":
      _wheel(record, locked)
      if record["package"] not in _NAMES or identity != "durable-python-" + record["package"]:
        _fail()
  chosen = {identity for identity in ids if sources[identity]["kind"] == "wheel"}
  # 保留的七个 ID 不得以其它来源种类伪装。
  reserved = {"durable-python-" + name for name in _NAMES}
  if (set(ids) & reserved) != chosen:
    _fail()
  present = "python_bundle" in piece
  if profile_id == "pi-base" and (present or chosen):
    _fail()
  if chosen or present:
    if not present or chosen != reserved:
      _fail()
    ref = piece["python_bundle"]
    if type(ref) is not dict or set(ref) != {"schema_version", "source", "path", "sha256", "size"}:
      _fail()
    _integer(ref["schema_version"], 1, 1)
    _integer(ref["size"], 1, 8388608)
    _match(ref["sha256"], _HEX)
    if ref["source"] != _SOURCE or ref["path"] != _PATH:
      _fail()
  rows = piece.get("runtime_files")
  if type(rows) is not list or not 1 <= len(rows) <= 2048:
    _fail()
  matches = 0
  for row in rows:
    if type(row) is not dict or type(row.get("source")) is not str or type(row.get("path")) is not str:
      _fail()
    if row["source"] != _SOURCE and row["path"] != _PATH:
      continue
    matches += 1
    if not present:
      _fail()
    expected = {"source": _SOURCE, "path": _PATH, "transform": "copy"}
    if locked:
      expected.update(input_digest=ref["sha256"], digest=ref["sha256"], mode=384)
      _integer(row.get("mode"), 384, 384)
    if row != expected:
      _fail()
  if matches != int(present):
    _fail()


def _validate_reference(profile_id, piece, sources, locked):
  _locked(locked)
  if type(profile_id) is not str:
    _fail()
  piece, sources = _inputs(piece, sources)
  _reference(profile_id, piece, sources, locked)


def validate_python_bundle_reference(profile_id, piece, sources, *, locked):
  """通用锁的来源与引用配对；Base 不读取正文或导入 core。"""
  return _boundary(_validate_reference, profile_id, piece, sources, locked)


def _object(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      _fail()
    result[key] = value
  return result


def _constant(value):
  _fail()


def _selected(raw, piece, sources):
  piece, sources = _inputs(piece, sources)
  _reference("pi-full", piece, sources, True)
  if "python_bundle" not in piece:
    _fail()
  if type(raw) is not bytes or not 1 <= len(raw) <= 8388608:
    _fail()
  ref = piece["python_bundle"]
  if len(raw) != ref["size"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
    _fail()
  declaration = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_object, parse_constant=_constant)
  declaration = _Snapshot().walk(declaration)
  from .pi_python_bundle import validate_python_bundle_declaration
  validate_python_bundle_declaration(declaration)
  for row in declaration["wheels"]:
    source = sources[row["source_id"]]
    for row_key, source_key in (("name", "package"), ("version", "version"), ("wheel_filename", "wheel_filename"),
                                ("archive_sha256", "archive_digest"), ("archive_size", "size")):
      if row[row_key] != source[source_key]:
        _fail()
    licenses = sorted(row["dist_info"] + "/licenses/" + path for path in row["metadata"]["license_files"])
    if source["license_files"] != licenses:
      _fail()
  return declaration


def validate_selected_python_bundle(declaration_bytes, piece, sources):
  """只核所选 Full 的已取得原字节；返回 detached 原生 JSON。"""
  return _boundary(_selected, declaration_bytes, piece, sources)
