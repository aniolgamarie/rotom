"""现代 registry 完整图的许可正文与来源绑定；不改写上游包。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .paths import relative_path
from .schema import ConfigError
from .storage import Tree


OWN = "licenses/pi-modern/"
SOURCE = "agents/pi/build/" + OWN
HEX = re.compile(r"[0-9a-f]{64}")
PACKAGE = re.compile(r"node_modules/(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+(?:/node_modules/(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+)*")
REGISTRY = re.compile(r"licenses/pi-modern/REGISTRY(?:-[a-zA-Z0-9_-]+)?\.json")
IDENTITY = ("path", "name", "version", "resolved", "integrity", "optional", "os", "cpu", "libc")
FIELDS = set(IDENTITY) | {"package_json_sha256", "declared_license", "status", "archive_files", "supplemental_files", "evidence_files"}
STATUSES = {"archive-body", "fixed-source-body", "declared-license-with-canonical-supplement", "body-scope-unresolved", "optional-platform-excluded"}


def _pairs(rows):
  result = {}
  for key, value in rows:
    if key in result: raise ValueError()
    result[key] = value
  return result


def document(raw):
  value = json.loads(raw, object_pairs_hook=_pairs)
  if not isinstance(value, dict): raise ValueError()
  return value


def excluded(record):
  """仅 OS/CPU 的明确不匹配证明排除；libc 不作平台推断。"""
  def mismatch(values, current):
    if values is None: return False
    positive = [value for value in values if not value.startswith("!")]
    return "!" + current in values or bool(positive) and current not in positive and "any" not in positive
  return record["optional"] is True and (mismatch(record["os"], "linux") or mismatch(record["cpu"], "x64"))


def projection(resolution):
  result = []
  for path, row in sorted(resolution["packages"].items()):
    if not path: continue
    resolved = row.get("resolved", "")
    if isinstance(resolved, str) and resolved.startswith("file:"): continue
    if not isinstance(path, str) or not PACKAGE.fullmatch(path) or relative_path(path).as_posix() != path: raise ValueError()
    url = urlsplit(resolved)
    if url.scheme != "https" or not url.netloc or url.username or url.password or url.fragment: raise ValueError()
    value = {"path": path, "name": row.get("name", path.rsplit("node_modules/", 1)[-1]),
      "version": row.get("version"), "resolved": resolved, "integrity": row.get("integrity"),
      "optional": row.get("optional", False), **{key: row.get(key) for key in ("os", "cpu", "libc")}}
    if type(value["optional"]) is not bool: raise ValueError()
    if any(not isinstance(value[key], str) or not value[key] for key in ("name", "version", "integrity")): raise ValueError()
    if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", value["integrity"]): raise ValueError()
    for key in ("os", "cpu", "libc"):
      constraints = value[key]
      if constraints is not None and (not isinstance(constraints, list) or not constraints
          or any(not isinstance(item, str) or not item for item in constraints)): raise ValueError()
    result.append(value)
  return result


def _read(tree, path, sha):
  raw = tree.read(path, max_bytes=16 * 1024 * 1024)
  if raw is None or not raw[0] or hashlib.sha256(raw[0]).hexdigest() != sha: raise ValueError()
  return raw[0]


def _bundle(tree, piece, resolution, *, installed, allow_unresolved):
  from .pi_runtime_files import validate_manifest
  validate_manifest(piece["runtime_files"])
  pins = {row["path"]: row for row in piece["runtime_files"] if row["path"].startswith(OWN)}
  registries = [path for path in pins if REGISTRY.fullmatch(path)]
  if len(registries) != 1: raise ValueError()
  def own(path, sha=None):
    if path not in pins: raise ValueError()
    pin = pins[path]
    if sha is not None and sha != pin["digest"]: raise ValueError()
    return _read(tree, path if installed else pin["source"], pin["digest"] if installed else pin["input_digest"])
  from .pi_dependencies import platform_id
  if platform_id() != "linux-x86_64": raise ValueError()
  registry = document(own(registries[0]))
  if (set(registry) != {"schema_version", "platform", "packages"} or type(registry["schema_version"]) is not int
      or registry["schema_version"] != 1 or registry["platform"] != "linux-x86_64" or not isinstance(registry["packages"], list)):
    raise ValueError()
  graph = projection(resolution)
  rows = registry["packages"]
  if len(rows) != len(graph): raise ValueError()
  for row, locked in zip(rows, graph):
    if not isinstance(row, dict) or set(row) != FIELDS or any(row[key] != locked[key] for key in IDENTITY): raise ValueError()
    if type(row["optional"]) is not bool or row["status"] not in STATUSES: raise ValueError()
    refs = set()
    for kind in ("archive_files", "supplemental_files", "evidence_files"):
      if not isinstance(row[kind], list): raise ValueError()
      for ref in row[kind]:
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}: raise ValueError()
        path, sha = ref["path"], ref["sha256"]
        if not isinstance(path, str) or relative_path(path).as_posix() != path or not isinstance(sha, str) or not HEX.fullmatch(sha): raise ValueError()
        if path in refs: raise ValueError()
        refs.add(path)
        if kind != "archive_files":
          if not path.startswith(OWN) or REGISTRY.fullmatch(path): raise ValueError()
          own(path, sha)
        elif path.startswith(("node_modules/", OWN)): raise ValueError()
    status = row["status"]
    archives, supplement, evidence = (bool(row[key]) for key in ("archive_files", "supplemental_files", "evidence_files"))
    if status == "optional-platform-excluded":
      if not excluded(row) or row["package_json_sha256"] is not None or row["declared_license"] is not None or refs: raise ValueError()
      continue
    if (not isinstance(row["package_json_sha256"], str) or not HEX.fullmatch(row["package_json_sha256"])
        or not isinstance(row["declared_license"], str) or not row["declared_license"]): raise ValueError()
    if status == "archive-body" and (not archives or supplement): raise ValueError()
    if status in ("fixed-source-body", "declared-license-with-canonical-supplement") and (not supplement or not evidence): raise ValueError()
    if status == "declared-license-with-canonical-supplement" and (row["declared_license"] != "Apache-2.0" or row["name"] not in (
        "@aws-sdk/credential-provider-http", "@aws-sdk/credential-provider-login", "@aws-sdk/nested-clients")): raise ValueError()
    if status == "body-scope-unresolved" and (archives or supplement or not evidence or not allow_unresolved): raise ValueError()
  return registry


def validate_source(repository, piece, resolution, *, allow_unresolved):
  try:
    from .pi_runtime_files import verify_sources
    verify_sources(repository, piece["runtime_files"])
    with Tree(Path(repository), private=False) as tree:
      return _bundle(tree, piece, resolution, installed=False, allow_unresolved=allow_unresolved)
  except Exception:
    raise ConfigError("pi-license-bundle-invalid") from None


def validate_packages(tree, prefix, registry):
  for row in registry["packages"]:
    path = (Path(prefix) / row["path"]).as_posix()
    raw = tree.read(path + "/package.json", max_bytes=16 * 1024 * 1024)
    if row["status"] == "optional-platform-excluded":
      directory = tree.root / path
      if raw is not None or directory.exists() or directory.is_symlink(): raise ValueError()
      continue
    if raw is None or hashlib.sha256(raw[0]).hexdigest() != row["package_json_sha256"]: raise ValueError()
    package = document(raw[0])
    if any(package.get(key) != row[key] for key in ("name", "version")) or package.get("license") != row["declared_license"]: raise ValueError()
    for ref in row["archive_files"]: _read(tree, path + "/" + ref["path"], ref["sha256"])


def validate_installed(root, piece, resolution):
  try:
    with Tree(Path(root)) as tree:
      registry = _bundle(tree, piece, resolution, installed=True, allow_unresolved=False)
      validate_packages(tree, Path(piece["package_path"]).parent, registry)
    return registry
  except Exception:
    from .storage import Conflict
    raise Conflict("Pi许可正文或来源与完整锁不一致") from None
