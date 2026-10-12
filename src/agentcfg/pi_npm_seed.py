"""构建时固定npm输入；不属于runtime/read_lock或来源资格接口。"""

import base64
import hashlib
import json
import re

from .paths import relative_path, safe_id
from .schema import ConfigError
from .storage import Tree


MAX_SEED = 16 * 1024 * 1024


def _boundary(code, function, *args):
  failed = False
  try:
    result = function(*args)
  except Exception:
    failed = True
  if failed:
    try: raise ConfigError(code)
    except ConfigError as error:
      error.__cause__ = None; error.__context__ = None
      raise
  return result


def _reference(profile, reference):
  if type(profile) is not str or type(reference) is not dict or any(type(key) is not str for key in reference):
    raise ValueError()
  safe_id(profile)
  if (set(reference) != {"source", "sha256"} or type(reference["source"]) is not str
      or reference["source"] != "agents/pi/build/resolutions/" + profile + ".package-lock.json"
      or type(reference["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])):
    raise ValueError()


def validate_reference(profile, reference):
  return _boundary("pi-build-resolution-seed-invalid", _reference, profile, reference)


def _package_name(value):
  if (type(value) is not str or not 1 <= len(value) <= 214
      or not re.fullmatch(r"(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9_.-]+", value)):
    raise ValueError()


def _exact_version(value):
  if type(value) is not str or not 1 <= len(value) <= 128: raise ValueError()
  match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", value)
  if match is None: raise ValueError()
  if match[4] and any(part.isdecimal() and len(part) > 1 and part.startswith("0") for part in match[4].split(".")):
    raise ValueError()


def _selector(value):
  if type(value) is not str or not 1 <= len(value) <= 343: raise ValueError()
  package, version = value.rsplit("@", 1)
  _package_name(package); _exact_version(version)
  return package, version


def _native_pairs(value, maximum=None):
  if type(value) is not dict or (maximum is not None and not 1 <= len(value) <= maximum): raise ValueError()
  pairs = []
  for key, item in value.items():
    if type(key) is not str: raise ValueError()
    pairs.append((key, item))
  return pairs


def _dependency_overrides(value, selected):
  # 先捕获全部typed pairs，外来键不能进入哈希表/字段比较。
  parents = _native_pairs(value, 16); captured = []; count = 0
  for parent, children in parents:
    pairs = _native_pairs(children, 32); count += len(pairs)
    if count > 32 or any(type(replacement) is not str for _, replacement in pairs): raise ValueError()
    captured.append((parent, pairs))
  roots = set(); allowed = set()
  for _, source in _native_pairs(selected):
    record = dict(_native_pairs(source))
    kind = record["kind"]
    if type(kind) is not str or kind not in ("npm", "local", "git"): raise ValueError()
    package = record["package"]; _package_name(package); roots.add(package)
    if kind == "npm":
      version = record["version"]; _exact_version(version)
      allowed.add(package + "@" + version)
  result = {}
  for parent, children in captured:
    _selector(parent)
    if parent not in allowed: raise ValueError()
    row = {}
    for child, replacement in children:
      package, _ = _selector(child); _exact_version(replacement)
      if package in roots: raise ValueError()
      row[child] = replacement
    result[parent] = row
  return result


def validate_dependency_overrides(value, selected):
  return _boundary("pi-build-dependency-overrides-invalid", _dependency_overrides, value, selected)


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result: raise ValueError()
    result[key] = value
  return result


def _sri(value):
  if type(value) is not str or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", value): raise ValueError()
  digest = base64.b64decode(value[7:], validate=True)
  if len(digest) != 64 or base64.b64encode(digest).decode() != value[7:]: raise ValueError()
  return digest


def _load(repository, profile, reference, package, selected, sources, archives):
  _reference(profile, reference)
  with Tree(repository, private=False) as tree:
    raw = tree.read(reference["source"], max_bytes=MAX_SEED)
  if raw is None or hashlib.sha256(raw[0]).hexdigest() != reference["sha256"]: raise ValueError()
  seed = json.loads(raw[0], object_pairs_hook=_pairs)
  if (type(seed) is not dict or set(seed) != {"name", "version", "lockfileVersion", "requires", "packages"}
      or type(seed["name"]) is not str or seed["name"] != package["name"]
      or type(seed["version"]) is not str or seed["version"] != package["version"]
      or type(seed["lockfileVersion"]) is not int or seed["lockfileVersion"] != 3 or seed["requires"] is not True
      or type(seed["packages"]) is not dict): raise ValueError()
  rows = seed["packages"]; root = rows.get("")
  if (type(root) is not dict or set(root) != {"name", "version", "dependencies"}
      or type(root["name"]) is not str or root["name"] != package["name"]
      or type(root["version"]) is not str or root["version"] != package["version"]
      or type(root["dependencies"]) is not dict or root["dependencies"] != package["dependencies"]): raise ValueError()
  expected_file = {}
  for source_id, source in selected.items():
    path = "node_modules/" + source["package"]
    if relative_path(path).as_posix() != path: raise ValueError()
    record = rows.get(path)
    if (type(record) is not dict or type(record.get("version")) is not str or record["version"] != source["version"]
        or record.get("name", source["package"]) != source["package"]): raise ValueError()
    if source["kind"] in ("local", "git"):
      vendor = sources[source_id]["vendor_path"]
      if record.get("resolved") != "file:../" + vendor: raise ValueError()
      if _sri(record.get("integrity")) != hashlib.sha512(archives[vendor]).digest(): raise ValueError()
      expected_file[path] = record
  actual_file = {}
  for path, record in rows.items():
    if type(record) is not dict or "link" in record: raise ValueError()
    if not path: continue
    resolved = record.get("resolved")
    if type(resolved) is not str: raise ValueError()
    if resolved.startswith("file:"):
      actual_file[path] = record
    _sri(record.get("integrity"))
  if actual_file != expected_file: raise ValueError()
  from .pi_license_bundle import projection
  identity = projection(seed)
  return raw[0], identity


def load_seed(repository, profile, reference, package, selected, sources, archives):
  return _boundary("pi-build-resolution-seed-invalid", _load, repository, profile, reference, package, selected, sources, archives)


def _compare(expected, resolution):
  from .pi_license_bundle import projection
  if projection(resolution) != expected: raise ValueError()


def validate_seed_result(expected, resolution):
  return _boundary("pi-build-resolution-seed-drift", _compare, expected, resolution)
