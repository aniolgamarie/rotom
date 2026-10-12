"""完整锁的有界数据组合；仅固定 header schema IO，不授予来源或运行资格。"""

import base64
import hashlib
import json
import math
import re


def _digest(value):
  from .deployment import json_bytes
  return hashlib.sha256(value if isinstance(value, bytes) else json_bytes(value)).hexdigest()


def _validate_source_prefix(source):
  from .pi_vendor import validate_license_sources
  validate_license_sources(source)
  from .pi_lock_resolution import VERSION
  if source["kind"] == "npm":
    from .config import _credential_url
    if not {"package", "version", "resolved", "integrity"} <= source.keys():
      raise ValueError()
    if not VERSION.fullmatch(source["version"]) or not source["resolved"].startswith("https://") or _credential_url(source["resolved"]):
      raise ValueError()
    if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", source["integrity"]) or len(base64.b64decode(source["integrity"][7:], validate=True)) != 64:
      raise ValueError()
  elif source["kind"] == "wheel":
    from .pi_wheel_sources import validate_wheel_source
    validate_wheel_source(source, locked=True)
  elif source["kind"] == "asset":
    from .pi_assets import validate_asset
    validate_asset(source)
  else:
    if not {"package", "version", "vendor_path", "archive_digest"} <= source.keys() or not VERSION.fullmatch(source["version"]):
      raise ValueError()


def _validate_source_suffix(source):
  if source["kind"] == "git" and not re.fullmatch(r"[0-9a-f]{40}", source.get("commit", "")):
    raise ValueError()
  if source["kind"] == "local" and not {"source_path", "source_tree_digest"} <= source.keys():
    raise ValueError()


def _validate_slice(name, piece, manifest):
  if set(piece["source_ids"]) - manifest["sources"].keys():
    raise ValueError()
  from .pi_assets import validate_asset_platforms
  validate_asset_platforms(piece, manifest)
  if manifest["schema_version"] == 2:
    from .pi_wheel_sources import validate_python_bundle_reference
    validate_python_bundle_reference(name, piece, manifest["sources"], locked=True)
    from .pi_modern_launcher import validate_destinations
    validate_destinations(piece, manifest)
  if _digest({k: v for k, v in piece.items() if k != "identity"}) != piece["identity"]:
    raise ValueError()
  if _digest(piece["resource_manifest"]) != piece["resource_manifest_digest"]:
    raise ValueError()
  for entries in piece["resource_manifest"].values():
    for entry in entries:
      if entry["capability_id"] not in piece["capability_ids"]:
        raise ValueError()


def _validate_build_step(step, sources):
  from .paths import relative_path
  if (set(step["source_ids"]) - sources.keys()
      or set(step["expected_outputs"]) != set(step["output_digests"])):
    raise ValueError()
  for path in (*step["input_digests"], *step["output_digests"]):
    relative_path(path)


def _fail():
  raise ValueError()


def _text(value):
  if type(value) is not str or len(value) > 4096:
    _fail()
  return len(value.encode("utf-8", "strict"))


def _pairs(value, cap, *, text_bounds=True):
  if type(value) is not dict or len(value) > cap:
    _fail()
  pairs = tuple(dict.items(value))
  # 全部原键先核型，再建立本次自有 map；不二次读取 caller 字典。
  for key, _ in pairs:
    if type(key) is not str:
      _fail()
    if text_bounds:
      _text(key)
  return pairs


class _Capture:
  """每原容器一次捕获；alias 按展开成本计费，保留原引用阻止 id 重用。"""

  def __init__(self):
    self.memo = {}
    self.active = set()
    self.nodes = 0
    self.utf8 = 0

  def _limits(self, nodes, utf8, height, depth):
    if nodes > 100000 or utf8 > 8388608 or depth + height > 16:
      _fail()

  def _walk(self, value, depth):
    if depth > 16:
      _fail()
    kind = type(value)
    if kind is str:
      return value, 1, _text(value), 0
    if kind is int:
      if not -(2 ** 63) <= value < 2 ** 63:
        _fail()
      return value, 1, 0, 0
    if kind is float:
      if not math.isfinite(value):
        _fail()
      return value, 1, 0, 0
    if kind in (bool, type(None)):
      return value, 1, 0, 0
    if kind not in (dict, list) or len(value) > 100000:
      _fail()
    identity = id(value)
    if identity in self.active:
      _fail()
    if identity in self.memo:
      original, captured, nodes, utf8, height = self.memo[identity]
      if original is not value:
        _fail()
      self._limits(nodes, utf8, height, depth)
      return captured, nodes, utf8, height
    references = _pairs(value, 100000) if kind is dict else tuple(value)
    self.active.add(identity)
    try:
      result = {} if kind is dict else []
      nodes, utf8, height = 1, 0, 0
      for reference in references:
        if kind is dict:
          key, child = reference
          copied_key, key_nodes, key_utf8, key_height = self._walk(key, depth + 1)
          nodes += key_nodes
          utf8 += key_utf8
          height = max(height, key_height + 1)
        else:
          child = reference
        copied, child_nodes, child_utf8, child_height = self._walk(child, depth + 1)
        nodes += child_nodes
        utf8 += child_utf8
        height = max(height, child_height + 1)
        self._limits(nodes, utf8, height, depth)
        if kind is dict:
          result[copied_key] = copied
        else:
          result.append(copied)
      self.memo[identity] = (value, result, nodes, utf8, height)
      return result, nodes, utf8, height
    finally:
      self.active.remove(identity)

  def capture(self, value):
    result, nodes, utf8, height = self._walk(value, 0)
    self.nodes += nodes
    self.utf8 += utf8
    self._limits(self.nodes, self.utf8, height, 0)
    return result


def _blobs(profile_inputs):
  pairs = _pairs(profile_inputs, 64, text_bounds=False)
  if not pairs:
    _fail()
  result, memo = {}, {}
  total = 0
  for profile, record in pairs:
    if type(record) is not dict:
      _fail()
    identity = id(record)
    if identity in memo:
      original, captured = memo[identity]
      if original is not record:
        _fail()
    else:
      captured = dict(_pairs(record, 3, text_bounds=False))
      if (not {"package_json", "package_lock_json"} <= captured.keys()
          or set(captured) - {"package_json", "package_lock_json", "python_bundle_json"}):
        _fail()
      for key, raw in captured.items():
        cap = 8388608 if key == "python_bundle_json" else 1048576
        if type(raw) is not bytes or len(raw) > cap:
          _fail()
      memo[identity] = record, captured
    # 相同 bytes/record alias 也按每次出现收费。
    total += sum(len(raw) for raw in captured.values())
    if total > 16777216:
      _fail()
    result[profile] = captured
  return result


def _object(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      _fail()
    result[key] = value
  return result


def _constant(value):
  _fail()


def _decode(raw):
  value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_object, parse_constant=_constant)
  return _Capture().capture(value)


def _capture(manifest, profile_inputs, schema_version, accepted_binding_digests):
  if type(schema_version) is not int or schema_version not in (1, 2):
    _fail()
  if type(manifest) is not dict or accepted_binding_digests is not None and type(accepted_binding_digests) is not dict:
    _fail()
  capture = _Capture()
  manifest = capture.capture(manifest)
  accepted = capture.capture(accepted_binding_digests) if accepted_binding_digests is not None else None
  inputs = _blobs(profile_inputs)
  if accepted is not None:
    if any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in accepted.values()):
      _fail()
  # 所有入参捕获完成，才允许固定自有 schema IO 与原数据 helper 导入。
  from .pi_lock_header import validate_lock_header
  validate_lock_header(manifest, schema_version=schema_version)
  if manifest["schema_version"] == 2:
    from .pi_capabilities import validate_manifest_bindings
    validate_manifest_bindings(manifest["capability_bindings"], manifest["profile_slices"], sources=manifest["sources"])
  if accepted is not None and set(accepted) - manifest["profile_slices"].keys():
    _fail()
  if set(inputs) - manifest["profile_slices"].keys():
    _fail()
  for source in manifest["sources"].values():
    _validate_source_prefix(source)
    _validate_source_suffix(source)
  for name, piece in manifest["profile_slices"].items():
    _validate_slice(name, piece, manifest)
  from .pi_lock_resolution import validate_lock_resolution
  for name, record in inputs.items():
    piece = manifest["profile_slices"][name]
    package, lock = record["package_json"], record["package_lock_json"]
    if hashlib.sha256(package).hexdigest() != piece["package_json_digest"] or hashlib.sha256(lock).hexdigest() != piece["package_lock_digest"]:
      _fail()
    validate_lock_resolution(_decode(package), _decode(lock), piece, manifest)
    if "python_bundle" in piece:
      if "python_bundle_json" not in record:
        _fail()
      from .pi_wheel_sources import validate_selected_python_bundle
      validate_selected_python_bundle(record["python_bundle_json"], piece, manifest["sources"])
    elif "python_bundle_json" in record:
      _fail()
  for step in manifest["build_steps"]:
    _validate_build_step(step, manifest["sources"])
  if manifest["schema_version"] == 2:
    from .pi_capabilities import validate_selection_data
    bindings = manifest["capability_bindings"]
    for name in inputs:
      piece = manifest["profile_slices"][name]
      host = manifest["sources"].get("pi-host")
      if host is None or "pi-host" not in piece["source_ids"] or "version" not in host:
        _fail()
      validate_selection_data(bindings["catalog"], bindings["providers"], bindings["selections"][name], manifest,
        lock_identity=manifest["identity"], host_version=host["version"], engine=piece["engine"], accepted_binding_digest=(accepted or {}).get(name))
  return {"metadata": manifest, "profile_inputs": inputs}


def capture_pi_lock_metadata_data(manifest, profile_inputs, *, schema_version, accepted_binding_digests=None):
  """返回本次完整数据副本；唯一 IO 是原固定 header schema，不证明来源或资格。"""
  failed = False
  try:
    result = _capture(manifest, profile_inputs, schema_version, accepted_binding_digests)
  except Exception:
    failed = True
  if failed:
    try:
      raise ValueError("pi-lock-metadata")
    except ValueError as error:
      error.__cause__ = None
      error.__context__ = None
      raise
  return result
