"""本地构建资产的闭合provenance校验；摘要不是外部attestation或执行许可。"""
import hashlib
import io
import json
import re
import tarfile
import zlib

from . import pi_bwrap_build as build
from .paths import relative_path
from .pi_lock_layout import dependency_layout
from .schema import ConfigError
from .storage import Tree


LICENSE_DIGESTS = {
  "bubblewrap-COPYING": "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551",
  "libcap-License": "68467e731f4744bd6e0bb69e8df9c3a994e09cd6b203d0c41327ac6d079c581d",
}
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
RECORD_FIELDS = {"schema_version", "inputs", "build_script_sha256", "bootstrap", "observation", "status",
  "archive", "archive_sha256", "binary_sha256"}


def _sha(value):
  if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value): raise ValueError()
  return value


def validate_reference(source):
  """只校验引用；不读盘，不下载，不允许同时声明二进制URL。"""
  try:
    if type(source) is not dict or set(source) != {"kind", "format", "platform", "target", "archive_member",
      "archive_digest", "vendor_path", "build_record", "license_files"}: raise ValueError()
    ref = source["build_record"]
    if (type(ref) is not dict or set(ref) != {"recipe", "path", "digest"} or ref["recipe"] != "bubblewrap-v1"
        or ref["path"] != "build-records/" + _sha(ref["digest"]) + ".json"
        or source["kind"] != "asset" or source["format"] != "tar.gz" or source["platform"] != "linux-x86_64"
        or source["target"] != "bin/pi-bwrap" or source["archive_member"] != "bin/pi-bwrap"):
      raise ValueError()
    relative_path(source["vendor_path"])
    _sha(source["archive_digest"])
    licenses = source["license_files"]
    if type(licenses) is not list or len(licenses) != 2 or len(set(licenses)) != 2: raise ValueError()
    for path in licenses:
      if relative_path(path).is_absolute() or not path.startswith("agents/pi/build/licenses/"): raise ValueError()
    if relative_path(source["vendor_path"]).is_absolute(): raise ValueError()
  except Exception:
    raise ConfigError("pi-built-asset-reference") from None


def _record(source, record):
  if (type(record) is not dict or set(record) != RECORD_FIELDS or type(record["schema_version"]) is not int
      or record["schema_version"] != 1 or record["status"] != "built-not-executed"
      or record["archive"] != "pi-bwrap-linux-x86_64.tar.gz" or record["inputs"] != build.INPUTS
      or record["build_script_sha256"] != hashlib.sha256(build.BUILD_SCRIPT.encode()).hexdigest()
      or _sha(record["archive_sha256"]) != source["archive_digest"]):
    raise ValueError()
  _sha(record["binary_sha256"])
  bootstrap = record["bootstrap"]
  if type(bootstrap) is not dict or set(bootstrap) != {"path", "sha256"} or bootstrap["path"] != "/usr/bin/bwrap": raise ValueError()
  _sha(bootstrap["sha256"])
  build._observation(build._json(record["observation"]))


def _object(pairs):
  result = {}
  for key, value in pairs:
    if key in result: raise ValueError()
    result[key] = value
  return result


def _constant(value):
  raise ValueError()


def parse_record(raw, source):
  """纯校验：绑定原始记录摘要、闭合JSON和固定构建契约。"""
  validate_reference(source)
  try:
    if type(raw) is not bytes or len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != source["build_record"]["digest"]:
      raise ValueError()
    value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    _record(source, value)
    return value
  except Exception:
    raise ConfigError("pi-built-asset-record") from None


def load_record(repository, layout, source):
  """只读取所选家族记录、固定输入和仓库许可，缺失不向另一家族补齐。"""
  validate_reference(source)
  try:
    if layout.family != "modern" or layout.schema_version != 2 or layout != dependency_layout(family="modern"): raise ValueError()
    with Tree(repository, private=False) as tree:
      record = tree.read(layout.lock_directory + "/" + source["build_record"]["path"], max_bytes=1024 * 1024)
      if record is None or hashlib.sha256(record[0]).hexdigest() != source["build_record"]["digest"]: raise ValueError()
      value = parse_record(record[0], source)
      for item in build.INPUTS.values():
        path = layout.lock_directory + "/build-inputs/" + item["sha256"] + "/" + item["name"]
        content = tree.read(path, max_bytes=build.MAX_ARCHIVE)
        if content is None or hashlib.sha256(content[0]).hexdigest() != item["sha256"]: raise ValueError()
      licenses = []
      for path in source["license_files"]:
        content = tree.read(path, max_bytes=1024 * 1024)
        if content is None: raise ValueError()
        licenses.append(hashlib.sha256(content[0]).hexdigest())
      if sorted(licenses) != sorted(LICENSE_DIGESTS.values()): raise ValueError()
    return value
  except Exception:
    raise ConfigError("pi-built-asset-record") from None


def archive_contents(raw, source, record):
  """绑定完整四条目与内嵌记录；仅静态检查ELF，不执行二进制。"""
  validate_reference(source)
  try:
    _record(source, record)
    if type(raw) is not bytes or not raw or len(raw) > MAX_ARCHIVE or hashlib.sha256(raw).hexdigest() != source["archive_digest"]:
      raise ValueError()
    decoder = zlib.decompressobj(wbits=31)
    expanded = decoder.decompress(raw, MAX_EXPANDED + 1)
    if len(expanded) > MAX_EXPANDED or not decoder.eof or decoder.unused_data: raise ValueError()
    expected = {"bin/pi-bwrap": 0o755, "licenses/bubblewrap-COPYING": 0o644,
      "licenses/libcap-License": 0o644, "build/source-record.json": 0o644}
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
      count, end = 0, 0
      for item in archive:
        count += 1
        if (count > 8 or item.name not in expected or item.name in contents or item.type != tarfile.REGTYPE
            or item.issparse() or item.mode != expected[item.name] or item.uid != 0 or item.gid != 0 or item.mtime != 0
            or item.uname or item.gname or item.pax_headers or item.size < 0
            or item.offset != end or item.offset_data != item.offset + 512):
          raise ValueError()
        with archive.extractfile(item) as stream: content = stream.read(item.size + 1)
        if len(content) != item.size: raise ValueError()
        contents[item.name] = content
        end = item.offset_data + ((item.size + 511) // 512) * 512
      if len(expanded) < end + 1024 or any(expanded[end:]): raise ValueError()
    if set(contents) != set(expected): raise ValueError()
    from .pi_assets import binary_platform
    binary = contents["bin/pi-bwrap"]
    if binary_platform(binary) != "linux-x86_64" or hashlib.sha256(binary).hexdigest() != record["binary_sha256"]: raise ValueError()
    for name, digest in LICENSE_DIGESTS.items():
      if hashlib.sha256(contents["licenses/" + name]).hexdigest() != digest: raise ValueError()
    provenance = {key: value for key, value in record.items() if key not in {"status", "archive", "archive_sha256", "binary_sha256"}}
    if contents["build/source-record.json"] != build._json(provenance): raise ValueError()
    return contents
  except Exception:
    raise ConfigError("pi-built-asset-archive") from None


def verify_archive(raw, source, record):
  """兼容既有接口；完整校验后仅返回二进制。"""
  return archive_contents(raw, source, record)["bin/pi-bwrap"]
