"""仅核已保存现代安装描述；不加载资源、不遍历包、不签持续SourceHold。"""
import json
import math
from pathlib import Path
import re

from .pi_capabilities import RESOURCE_KINDS
from .storage import Tree


FILE_LIMIT = 128 * 1024
RESOURCE_LIMIT = 4096
OUTPUT_LIMIT = 65536
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_HEX = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
_PACKAGE = re.compile(r"(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9_.-]+")
_FIELDS = {"schema_version", "profile_id", "package_path", "engine", "entrypoint", "resources", "lock_identity",
  "sdk_package", "sdk_version", "ai_package", "ai_version", "slice_identity", "toolchains", "platform", "runtime_identity"}


def _closed(value, fields):
  if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != set(fields):
    raise ValueError()


def _text(value, limit=4096):
  if (type(value) is not str or not value or len(value.encode("utf8")) > limit
      or any(ord(char) < 32 or ord(char) == 127 for char in value)):
    raise ValueError()
  return value


def _path(value):
  _text(value)
  if value.startswith("/") or "\\" in value or ":" in value or any(part in ("", ".", "..") for part in value.split("/")):
    raise ValueError()


def _identity(value):
  if type(value) is not str or not _HEX.fullmatch(value): raise ValueError()


def _resources(value):
  _closed(value, RESOURCE_KINDS)
  total = 0; seen = set(); public = []
  for kind in RESOURCE_KINDS:
    entries = value[kind]
    if type(entries) is not list or len(entries) > RESOURCE_LIMIT: raise ValueError()
    total += len(entries)
    if total > RESOURCE_LIMIT: raise ValueError()
    for row in entries:
      _closed(row, ("id", "capability_id", "path"))
      for key in ("id", "capability_id"):
        if type(row[key]) is not str or not _ID.fullmatch(row[key]): raise ValueError()
      if row["id"] in seen: raise ValueError()
      seen.add(row["id"]); _path(row["path"])
      public.append({"kind":kind, "id":row["id"], "capability_id":row["capability_id"]})
  return sorted(public, key=lambda row: (row["kind"], row["id"]))


def _document(raw):
  def pairs(items):
    value = {}
    for key,item in items:
      if key in value: raise ValueError()
      value[key] = item
    return value
  def nonfinite(_): raise ValueError()
  def finite(value):
    result = float(value)
    if not math.isfinite(result): raise ValueError()
    return result
  value = json.loads(raw.decode("utf8"), object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite)
  _closed(value, _FIELDS)
  if type(value["schema_version"]) is not int or value["schema_version"] != 2 or value["engine"] != "node": raise ValueError()
  if type(value["profile_id"]) is not str or value["profile_id"] not in ("pi-base", "pi-full"): raise ValueError()
  for key in ("lock_identity", "runtime_identity", "slice_identity"): _identity(value[key])
  _path(value["package_path"]); _path(value["entrypoint"])
  if not value["package_path"].endswith("/package.json"): raise ValueError()
  prefix = value["package_path"].rsplit("/", 1)[0]
  if not value["entrypoint"].startswith(prefix + "/node_modules/"): raise ValueError()
  for key in ("sdk_package", "ai_package"):
    if not _PACKAGE.fullmatch(_text(value[key], 214)): raise ValueError()
  for key in ("sdk_version", "ai_version"):
    if not _VERSION.fullmatch(_text(value[key], 128)): raise ValueError()
  _closed(value["toolchains"], ("node", "npm", "bun"))
  if any(not _VERSION.fullmatch(_text(version, 128)) for version in value["toolchains"].values()): raise ValueError()
  if not _ID.fullmatch(_text(value["platform"], 64)): raise ValueError()
  public = _resources(value["resources"])
  return value, public


def _result(status, reason, resources=()):
  counts = {kind:sum(row["kind"] == kind for row in resources) for kind in RESOURCE_KINDS}
  counts["total"] = len(resources)
  value = {"status":status, "reason_code":reason, "scope":"saved-installed-descriptor-only",
    "resources":list(resources), "counts":counts, "load_evidence":"not-run", "source_hold":"not-qualified"}
  if len(json.dumps(value, ensure_ascii=False).encode("utf8")) > OUTPUT_LIMIT: raise ValueError()
  return value


def installed_resource_inventory(*, context=None, dependencies, profile_id):
  """仅受信doctor传入context；失败不输出部分字段、路径或异常正文。"""
  if type(dependencies) is not str or dependencies != "installed": return _result("not-inspected", "PI_INSTALLED_RESOURCE_DEPENDENCIES_UNAVAILABLE")
  if context is None: return _result("not-inspected", "PI_INSTALLED_RESOURCE_CONTEXT_UNAVAILABLE")
  try:
    if type(profile_id) is not str or profile_id not in ("pi-base", "pi-full"): raise ValueError()
    _closed(context, ("profile_id", "runtime_root", "lock_identity", "runtime_identity", "slice_identity", "expected_resources"))
    if type(context["profile_id"]) is not str or context["profile_id"] not in ("pi-base", "pi-full"): raise ValueError()
    for key in ("lock_identity", "runtime_identity", "slice_identity"): _identity(context[key])
    expected_public = _resources(context["expected_resources"])
    # ctx本身也不得制造超限输出；不必为此探测任何文件。
    _result("matched", "PI_INSTALLED_RESOURCE_MATCHED", expected_public)
    if context["profile_id"] != profile_id: return _result("stale", "PI_INSTALLED_RESOURCE_PROFILE_MISMATCH")
    root = context["runtime_root"]
    if type(root) is not type(Path()) or not root.is_absolute() or ".." in root.parts: raise ValueError()
    if len(str(root).encode("utf8")) > 4096: raise ValueError()
    with Tree(root) as tree:
      raw = tree.read("runtime/profile.json", max_bytes=FILE_LIMIT)
    if raw is None: return _result("missing", "PI_INSTALLED_RESOURCE_DESCRIPTOR_MISSING")
    document, public = _document(raw[0])
    if any(document[key] != context[key] for key in ("profile_id", "lock_identity", "runtime_identity", "slice_identity")):
      return _result("stale", "PI_INSTALLED_RESOURCE_IDENTITY_MISMATCH")
    if document["resources"] != context["expected_resources"]:
      return _result("stale", "PI_INSTALLED_RESOURCE_INVENTORY_MISMATCH")
    return _result("matched", "PI_INSTALLED_RESOURCE_MATCHED", public)
  except Exception:
    return _result("invalid", "PI_INSTALLED_RESOURCE_INVALID")
