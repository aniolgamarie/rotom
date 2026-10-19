"""官方Pi npm后端：显式完整锁、按锁暂存核验和既有发布事务。"""

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass, field
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit

from .deployment import json_bytes
from .merge import merge_layers
from .pi_modules import MODULES, PLUGINS, SUPPORTS, selected_modules, selected_supports
from .paths import PathError, relative_path, safe_id
from .process import DependencyError, checked, environment
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private, instance_lock
from .toolchain import ensure_exact_toolchain, ensure_minimum_toolchain


PROFILES = ("pi-base", "pi-pro")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*")
SHA256 = re.compile(r"[a-f0-9]{64}")
LIFECYCLE = frozenset({"preinstall", "install", "postinstall", "prepare"})
SOURCE_KEYS = {"package", "version", "resolved", "integrity", "license", "source_commit", "license_files", "license_notices", "entries"}
PIECE_KEYS = {"profile", "identity", "recipe_digest", "recipe_inputs", "closure_digest", "package_path", "lock_path",
  "package_json_digest", "package_lock_digest", "dependencies", "required_files", "script_audits"}


def digest(value):
  return hashlib.sha256(value if isinstance(value, bytes) else json_bytes(value)).hexdigest()


def platform_id():
  machine = platform.machine().lower()
  return sys.platform + "-" + {"aarch64": "arm64", "amd64": "x86_64"}.get(machine, machine)


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result:
      raise ValueError()
    result[key] = value
  return result


def _constant(value):
  raise ValueError()


def _json(raw):
  return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)


def _text(value):
  return type(value) is str and bool(value) and "\0" not in value


def _public_url(value):
  if not _text(value):
    return False
  try:
    url = urlsplit(value)
    return (url.scheme == "https" and url.hostname == "registry.npmjs.org" and url.port is None
      and url.username is None and url.password is None and not url.query and not url.fragment
      and bool(url.path) and ".." not in unquote(url.path).split("/") and "\\" not in unquote(url.path))
  except ValueError:
    return False


def _sri(value):
  if not _text(value) or not value.startswith("sha512-"):
    return False
  try:
    return len(base64.b64decode(value[7:], validate=True)) == 64
  except ValueError:
    return False


def _path(value):
  if not _text(value):
    raise ValueError()
  return relative_path(value).as_posix()


def _package_name(path):
  parts, position, name = path.split("/"), 0, None
  while position < len(parts):
    if parts[position] != "node_modules" or position + 1 >= len(parts):
      raise ValueError()
    position += 1
    name = parts[position]
    position += 1
    if name.startswith("@"):
      if position >= len(parts):
        raise ValueError()
      name += "/" + parts[position]
      position += 1
    if not NAME.fullmatch(name):
      raise ValueError()
  return name


def _audits(value):
  if type(value) is not dict:
    raise ValueError()
  for path, audit in value.items():
    _package_name(path)
    if (type(audit) is not dict or set(audit) not in ({"package_json_digest", "lifecycle", "decision"},
          {"package_json_digest", "lifecycle", "decision", "package", "version"})
        or not isinstance(audit["package_json_digest"], str) or not SHA256.fullmatch(audit["package_json_digest"])
        or audit["decision"] != "ignored_not_required" or type(audit["lifecycle"]) is not dict
        or set(audit["lifecycle"]) - LIFECYCLE or any(not _text(v) for v in audit["lifecycle"].values())):
      raise ValueError()
    if "package" in audit and (not _text(audit["package"]) or not NAME.fullmatch(audit["package"])
        or not _text(audit["version"]) or not VERSION.fullmatch(audit["version"])):
      raise ValueError()


def _resolution_audits(catalog, resolution):
  """限定审计按已验证闭包落位，仍逐字保留实际manifest摘要与生命周期。"""
  _audits(catalog)
  result = {path: deepcopy(audit) for path, audit in catalog.items() if "package" not in audit}
  for audit in catalog.values():
    if "package" not in audit:
      continue
    projected = {key: deepcopy(audit[key]) for key in ("package_json_digest", "lifecycle", "decision")}
    for path, record in resolution["packages"].items():
      if (not path or record.get("name", _package_name(path)) != audit["package"]
          or record["version"] != audit["version"]):
        continue
      if path in result and result[path] != projected:
        raise ConfigError("pi-module-script-audit-conflict")
      result[path] = deepcopy(projected)
  return result


def _source(value):
  if (type(value) is not dict or set(value) != SOURCE_KEYS or not _text(value["package"])
      or not NAME.fullmatch(value["package"]) or not _text(value["version"]) or not VERSION.fullmatch(value["version"])
      or not _public_url(value["resolved"]) or not _sri(value["integrity"]) or not _text(value["license"])
      or (value["source_commit"] is not None and (not isinstance(value["source_commit"], str)
        or not re.fullmatch(r"[a-f0-9]{40}", value["source_commit"])) )):
    raise ValueError()
  for key in ("license_files", "entries"):
    if (type(value[key]) is not list or key == "entries" and not value[key]
        or len(value[key]) != len(set(value[key]))):
      raise ValueError()
    for path in value[key]:
      _path(path)
  notices = value["license_notices"]
  if type(notices) is not list or not (value["license_files"] or notices):
    raise ValueError()
  targets = set()
  for notice in notices:
    if (type(notice) is not dict or set(notice) != {"source_path", "target_path", "source_uri", "sha256"}
        or not _path(notice["source_path"]).startswith("agents/pi/licenses/")
        or not _path(notice["target_path"]).startswith("licenses/")
        or not _text(notice["source_uri"])
        or not re.fullmatch(r"https://raw\.githubusercontent\.com/earendil-works/pi/[a-f0-9]{40}/LICENSE", notice["source_uri"])
        or not _text(notice["sha256"]) or not SHA256.fullmatch(notice["sha256"])
        or notice["target_path"] in targets):
      raise ValueError()
    targets.add(notice["target_path"])


def _notice_body(tree, notice):
  raw = tree.read(notice["source_path"])
  if raw is None or digest(raw[0]) != notice["sha256"]:
    raise ConfigError("pi-license-notice-invalid")
  return raw[0]


def _license_notices(inputs):
  notices = [notice for source in [inputs["host"], *inputs["modules"].values()] for notice in source["license_notices"]]
  if len({notice["target_path"] for notice in notices}) != len(notices):
    raise ValueError()
  return notices


def read_recipe(repository):
  try:
    with Tree(Path(repository), private=False) as tree:
      raw = tree.read("agents/pi/dependencies.json")
    if raw is None:
      raise ValueError()
    value = _json(raw[0])
    if (type(value) is not dict or set(value) != {"schema_version", "host", "modules", "toolchains", "platforms", "profiles", "script_audits", "module_script_audits"}
        or type(value["schema_version"]) is not int or value["schema_version"] != 2
        or type(value["modules"]) is not dict or set(value["modules"]) != set(MODULES)
        or type(value["profiles"]) is not dict or set(value["profiles"]) != set(PROFILES)
        or value["toolchains"] != {"node": "v22.19.0", "npm": "11.9.0"}
        or value["platforms"] != ["linux-x86_64"]):
      raise ValueError()
    _source(value["host"])
    if value["host"]["package"] != "@earendil-works/pi-coding-agent":
      raise ValueError()
    for name, source in value["modules"].items():
      _source(source)
      if ((source["package"], source["version"]) != MODULES[name]
          or name != "catppuccin" and source["entries"] != ([PLUGINS[name]["entry"]] if name in PLUGINS else ["playwright-cli.js"] if name == "playwright-cli" else ["dist/index.js"])):
        raise ValueError()
    if value["modules"]["catppuccin"]["package"] != "catppuccin-pi-theme":
      raise ValueError()
    for piece in value["profiles"].values():
      if type(piece) is not dict or set(piece) != {"modules"} or piece["modules"] != ["catppuccin"]:
        raise ValueError()
    _audits(value["script_audits"])
    if type(value["module_script_audits"]) is not dict or set(value["module_script_audits"]) != set(MODULES):
      raise ValueError()
    for audits in value["module_script_audits"].values():
      _audits(audits)
    with Tree(Path(repository), private=False) as tree:
      for notice in _license_notices(value):
        _notice_body(tree, notice)
    return value
  except (OSError, ValueError, TypeError, KeyError, PathError, RecursionError):
    raise ConfigError("pi-recipe-invalid") from None


def _selection(value):
  if type(value) is not dict or set(value) != {"rules", "skills", "plugins", "mcp", "resources"}:
    raise ValueError()
  result = deepcopy(value)
  for key in ("rules", "skills", "plugins", "mcp"):
    if type(result[key]) is not list or len(result[key]) != len(set(result[key])):
      raise ValueError()
    for name in result[key]:
      safe_id(name)
  resources = result["resources"]
  if type(resources) is not dict or set(resources) - {"prompts", "themes", "extensions"}:
    raise ValueError()
  result["resources"] = {key: resources.get(key, []) for key in ("prompts", "themes", "extensions")}
  for key, names in result["resources"].items():
    if type(names) is not list or len(names) != len(set(names)):
      raise ValueError()
    for name in names:
      safe_id(name)
  if (set(result["plugins"]) - set(PLUGINS) or set(result["mcp"]) - {"pi-context7", "pi-brave"} or set(result["resources"]["themes"]) - {"catppuccin"}
      or set(result["resources"]["extensions"]) - {"builtin:codemode", "builtin:tool-search"}):
    raise ValueError()
  return result


def dependency_selection(data):
  try:
    profile = data["profile"]
    return _selection({**{key: profile.get(key, []) for key in ("rules", "skills", "plugins", "mcp")},
      "resources": profile.get("agent_options", {}).get("resources", {})})
  except (ValueError, TypeError, KeyError, PathError, RecursionError):
    raise ConfigError("pi-dependency-selection-invalid") from None


def recipe_inputs(repository, profile, selection=None):
  repository = Path(repository)
  recipe = read_recipe(repository)
  if profile not in recipe["profiles"]:
    raise ConfigError("pi-lock-profile")
  try:
    with Tree(repository, private=False) as tree:
      def read_toml(path):
        raw = tree.read(path)
        if raw is None:
          raise ValueError()
        return tomllib.loads(raw[0].decode("utf-8"))
      agent = read_toml("agents/pi/agent.toml")
      public = read_toml("profiles/" + profile + ".toml")
      selected = merge_layers((("defaults", agent["defaults"]), ("profile", public))).data
      registry = {"rules": {}, "skills": {}}
      paths = sorted((repository / "shared").glob("*.toml")) + [repository / "agents/pi/content.toml"]
      for path in paths:
        document = read_toml(path.relative_to(repository).as_posix())
        for kind in registry:
          for name, definition in document.get(kind, {}).items():
            previous = registry[kind].get(name)
            if previous is not None and not (kind == "skills" and definition.get("override") == previous["path"]):
              raise ValueError()
            registry[kind][name] = definition
      projection = _selection(selection) if selection is not None else dependency_selection({"profile": selected})
      resources = []
      for kind in ("rules",):
        for name in projection[kind]:
          definition = registry[kind][name]
          raw = tree.read(_path(definition["path"]))
          if raw is None:
            raise ValueError()
          resources.append({"kind": kind, "id": name, "source": definition, "content_identity": digest(raw[0])})
      for name in projection["resources"].get("prompts", []):
        definition = agent["resources"][name]
        raw = tree.read(_path(definition["path"]))
        if raw is None:
          raise ValueError()
        resources.append({"kind": "prompt", "id": name, "source": definition, "content_identity": digest(raw[0])})
    from .skills import collect_skills
    skills = {name: registry["skills"][name] for name in projection["skills"]}
    for artifact in collect_skills(repository, skills, target_root="skills"):
      skill_id = artifact.target.path.split("/")[1]
      resources.append({"kind": "skill-file", "path": artifact.target.path, "source": skills[skill_id], "mode": artifact.mode,
        "content_identity": digest(artifact.content)})
    chosen = selected_modules(projection)
    for support in selected_supports(projection):
      with Tree(repository, private=False) as tree:
        raw = tree.read(support["path"])
      if raw is None:
        raise ValueError()
      resources.append({**support, "content_identity": digest(raw[0])})
    sources = {name: recipe["modules"][name] for name in chosen}
    return {"profile": profile, "host": recipe["host"], "modules": sources, "selection": projection,
      "resources": resources, "toolchains": recipe["toolchains"], "platforms": recipe["platforms"], "script_audits": _selected_audits(recipe, chosen)}
  except (OSError, ValueError, TypeError, KeyError, PathError, RecursionError):
    raise ConfigError("pi-recipe-inputs-invalid") from None


def recipe_digest(repository, profile):
  return digest(recipe_inputs(repository, profile))


def _selected_audits(recipe, chosen):
  result = deepcopy(recipe["script_audits"])
  for name in chosen:
    for path, audit in recipe["module_script_audits"][name].items():
      if path in result and result[path] != audit:
        raise ConfigError("pi-module-script-audit-conflict")
      result[path] = audit
  return result


def _validate_inputs(inputs, profile, recipe):
  if type(inputs) is not dict or set(inputs) != {"profile", "host", "modules", "selection", "resources", "toolchains", "platforms", "script_audits"}:
    raise ValueError()
  selection = _selection(inputs["selection"])
  modules = {name: recipe["modules"][name] for name in selected_modules(selection)}
  if (inputs["selection"] != selection or inputs["profile"] != profile or inputs["host"] != recipe["host"] or inputs["modules"] != modules
      or inputs["toolchains"] != recipe["toolchains"] or inputs["platforms"] != recipe["platforms"]
      or inputs["script_audits"] != _selected_audits(recipe, selected_modules(selection)) or type(inputs["resources"]) is not list):
    raise ValueError()
  rules, prompts, skills, seen = set(), set(), set(), set()
  supports = set()
  for item in inputs["resources"]:
    if type(item) is not dict or not isinstance(item.get("content_identity"), str) or not SHA256.fullmatch(item["content_identity"]):
      raise ValueError()
    kind = item.get("kind")
    if kind in ("rules", "prompt"):
      if set(item) != {"kind", "id", "source", "content_identity"}:
        raise ValueError()
      name = safe_id(item["id"])
      allowed = selection["rules"] if kind == "rules" else selection["resources"]["prompts"]
      if name not in allowed or (kind, name) in seen:
        raise ValueError()
      seen.add((kind, name))
      (rules if kind == "rules" else prompts).add(name)
      allowed_source = {"path", "template"} if kind == "rules" else {"path", "kind", "scope"}
      if type(item["source"]) is not dict or set(item["source"]) - allowed_source:
        raise ValueError()
      _path(item["source"]["path"])
      if kind == "prompt" and (item["source"].get("kind") != "prompt" or item["source"].get("scope") != "global"):
        raise ValueError()
    elif kind == "skill-file":
      if set(item) != {"kind", "path", "source", "mode", "content_identity"} or type(item["mode"]) is not int or item["mode"] not in (0o600, 0o700):
        raise ValueError()
      path = _path(item["path"])
      parts = path.split("/")
      if len(parts) < 3 or parts[0] != "skills" or parts[1] not in selection["skills"] or path in seen:
        raise ValueError()
      seen.add(path)
      if parts[2:] == ["SKILL.md"]:
        skills.add(parts[1])
      source = item["source"]
      if type(source) is not dict or set(source) - {"path", "override"}:
        raise ValueError()
      _path(source["path"])
      if "override" in source:
        _path(source["override"])
    elif kind == "module-support":
      support = SUPPORTS.get(item.get("id"))
      if (support is None or item["id"] in supports or set(item) != {*support, "content_identity"}
          or any(item[k] != v for k, v in support.items())):
        raise ValueError()
      supports.add(item["id"])
    else:
      raise ValueError()
  if supports != {item["id"] for item in selected_supports(selection)}:
    raise ValueError()
  if rules != set(selection["rules"]) or prompts != set(selection["resources"]["prompts"]) or skills != set(selection["skills"]):
    raise ValueError()


def _resolve(packages, parent, name):
  parts = parent.split("/") if parent else []
  while True:
    candidate = "/".join([*parts, "node_modules", name])
    if candidate in packages:
      return candidate
    if not parts:
      return None
    parts.pop()


def validate_package_lock(resolution, dependencies):
  """核对固定发布物、可达闭包与Node祖先解析；npm ls另核实际peer范围。"""
  try:
    if (type(resolution) is not dict or set(resolution) - {"name", "version", "lockfileVersion", "requires", "packages"}
        or type(resolution.get("lockfileVersion")) is not int or resolution["lockfileVersion"] != 3
        or type(resolution.get("packages")) is not dict or "" not in resolution["packages"]
        or type(dependencies) is not dict or not dependencies):
      raise ValueError()
    packages = resolution["packages"]
    root = packages[""]
    if (type(root) is not dict or set(root) - {"name", "version", "dependencies", "license", "engines"}
        or root.get("dependencies") != dependencies):
      raise ValueError()
    for name, version in dependencies.items():
      if not NAME.fullmatch(name) or not _text(version) or not VERSION.fullmatch(version):
        raise ValueError()
      if packages.get("node_modules/" + name, {}).get("version") != version:
        raise ValueError()
    allowed = {"name", "version", "resolved", "integrity", "license", "dependencies", "optionalDependencies", "peerDependencies",
      "peerDependenciesMeta", "engines", "os", "cpu", "libc", "bin", "hasInstallScript", "inBundle", "dev", "optional",
      "devOptional", "peer", "funding", "deprecated", "bundleDependencies", "hasShrinkwrap"}
    for path, package in packages.items():
      if not path:
        continue
      _package_name(path)
      if (type(package) is not dict or set(package) - allowed or not _text(package.get("version"))
          or not VERSION.fullmatch(package["version"]) or not _text(package.get("license"))):
        raise ValueError()
      if ("inBundle" in package and type(package["inBundle"]) is not bool
          or not _public_url(package.get("resolved")) or not _sri(package.get("integrity"))):
        raise ValueError()
      for kind in ("dependencies", "optionalDependencies", "peerDependencies"):
        values = package.get(kind, {})
        if type(values) is not dict or any(not NAME.fullmatch(k) or not _text(v) for k, v in values.items()):
          raise ValueError()
      peers = package.get("peerDependenciesMeta", {})
      if type(peers) is not dict:
        raise ValueError()
      for name, value in peers.items():
        if (not NAME.fullmatch(name) or type(value) is not dict or set(value) - {"optional"}
            or "optional" in value and type(value["optional"]) is not bool
            or name not in package.get("peerDependencies", {}) and value != {"optional": True}):
          raise ValueError()
    reached, queue = set(), ["node_modules/" + name for name in dependencies]
    while queue:
      path = queue.pop()
      if path in reached:
        continue
      reached.add(path)
      package = packages[path]
      optional = package.get("optionalDependencies", {})
      for kind in ("dependencies", "optionalDependencies", "peerDependencies"):
        for name in package.get(kind, {}):
          target = _resolve(packages, path, name)
          may_miss = (kind == "optionalDependencies" or name in optional
            or kind == "peerDependencies" and package.get("peerDependenciesMeta", {}).get(name, {}).get("optional") is True)
          if target is None:
            if not may_miss:
              raise ValueError()
          else:
            queue.append(target)
    if reached != set(packages) - {""}:
      raise ValueError()
  except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
    raise ConfigError("pi-package-lock-invalid") from None


def validate_installed_packages(root, resolution, audits):
  try:
    _audits(audits)
    with Tree(Path(root)) as tree:
      for path, record in resolution["packages"].items():
        if not path:
          continue
        name = _package_name(path)
        raw = tree.read(path + "/package.json")
        if raw is None and record.get("optional") is True:
          continue
        if raw is None:
          raise ValueError()
        package = _json(raw[0])
        if type(package) is not dict or package.get("name") != record.get("name", name) or package.get("version") != record["version"]:
          raise ValueError()
        scripts = package.get("scripts", {})
        if type(scripts) is not dict:
          raise ValueError()
        lifecycle = {key: value for key, value in scripts.items() if key in LIFECYCLE}
        if tree.read(path + "/binding.gyp") is not None and not any(key in scripts for key in ("install", "preinstall")):
          lifecycle["install"] = "node-gyp rebuild"
        audit = audits.get(path)
        if lifecycle or audit is not None:
          expected = {"package_json_digest": digest(raw[0]), "lifecycle": lifecycle, "decision": "ignored_not_required"}
          if audit != expected:
            raise ConfigError("pi-install-script-not-audited")
  except ConfigError:
    raise
  except (OSError, ValueError, TypeError, KeyError, PathError, RecursionError):
    raise ConfigError("pi-installed-packages-invalid") from None


def npm_environment(home):
  home = Path(home)
  ensure_private(home)
  with Tree(home) as tree:
    for name in ("user.npmrc", "global.npmrc"):
      tree.write_immutable(name, b"")
  result = environment(home=home)
  result.update(npm_config_registry="https://registry.npmjs.org/", npm_config_userconfig=str(home / "user.npmrc"),
    npm_config_globalconfig=str(home / "global.npmrc"), npm_config_cache=str(home / "npm-cache"),
    npm_config_ignore_scripts="true", npm_config_audit="false", npm_config_fund="false", npm_config_update_notifier="false")
  return result


@dataclass(frozen=True)
class PiLock:
  identity: str
  metadata: dict = field(repr=False)
  pairs: dict = field(repr=False)


def _dependencies(inputs):
  return {source["package"]: source["version"] for source in [inputs["host"], *inputs["modules"].values()]}


def _required(inputs):
  return sorted(["node_modules/" + source["package"] + "/" + name
    for source in [inputs["host"], *inputs["modules"].values()] for name in source["entries"] + source["license_files"]]
    + [notice["target_path"] for notice in _license_notices(inputs)]
    + [item["target"] for item in inputs["resources"] if item["kind"] == "module-support"])


class PiBackend:
  adapter_id = "pi"
  adapter_version = "pi-2"

  def read_lock(self, repository):
    from .publication import reader_lease
    try:
      with reader_lease(repository, "pi") as tree:
        return self._read_lock_unlocked(repository, lock_tree=tree)
    except FileNotFoundError:
      raise ConfigError("pi-lock-missing-or-stale") from None

  def _read_lock_unlocked(self, repository, *, lock_tree=None):
    try:
      recipe = read_recipe(repository)
      with (nullcontext(lock_tree) if lock_tree is not None else Tree(Path(repository) / "locks/pi", private=False)) as tree:
        raw = tree.read("manifest.json")
        if raw is None:
          raise ValueError()
        metadata = _json(raw[0])
        if (set(metadata) != {"schema_version", "adapter_version", "identity", "host", "modules", "toolchains", "platforms", "profiles"}
            or type(metadata["schema_version"]) is not int or metadata["schema_version"] != 2
            or metadata["adapter_version"] != self.adapter_version
            or metadata["identity"] != digest({k: v for k, v in metadata.items() if k != "identity"})
            or any(metadata[key] != recipe[key] for key in ("host", "toolchains", "platforms"))
            or set(metadata["profiles"]) != set(PROFILES)):
          raise ValueError()
        pairs = {}
        for profile in PROFILES:
          piece = metadata["profiles"][profile]
          inputs = piece["recipe_inputs"]
          _validate_inputs(inputs, profile, recipe)
          if (set(piece) != PIECE_KEYS or piece["profile"] != profile
              or piece["identity"] != digest({k: v for k, v in piece.items() if k != "identity"})
              or piece["recipe_digest"] != digest(inputs)
              or piece["dependencies"] != _dependencies(inputs) or piece["required_files"] != _required(inputs)
              or piece["package_path"] != profile + "/package.json" or piece["lock_path"] != profile + "/package-lock.json"):
            raise ValueError()
          package, locked = tree.read(piece["package_path"]), tree.read(piece["lock_path"])
          if package is None or locked is None or digest(package[0]) != piece["package_json_digest"] or digest(locked[0]) != piece["package_lock_digest"]:
            raise ValueError()
          if _json(package[0]) != {"name": "rotom-" + profile, "version": "1.0.0", "private": True, "dependencies": piece["dependencies"]}:
            raise ValueError()
          resolution = _json(locked[0])
          validate_package_lock(resolution, piece["dependencies"])
          if piece["script_audits"] != _resolution_audits(inputs["script_audits"], resolution):
            raise ValueError()
          for source in [inputs["host"], *inputs["modules"].values()]:
            actual = resolution["packages"]["node_modules/" + source["package"]]
            if any(actual.get(key) != source[key] for key in ("version", "resolved", "integrity", "license")):
              raise ValueError()
          if piece["closure_digest"] != digest({"resolution": resolution, "resources": inputs["resources"], "license_notices": _license_notices(inputs)}):
            raise ValueError()
          pairs[profile] = (package[0], locked[0])
      if metadata["modules"] != {name: source for piece in metadata["profiles"].values() for name, source in piece["recipe_inputs"]["modules"].items()}:
        raise ValueError()
      return PiLock(metadata["identity"], metadata, pairs)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, PathError, RecursionError, ConfigError):
      raise ConfigError("pi-lock-missing-or-stale") from None

  def runtime_identity(self, workspace, lock):
    profile = workspace.profile
    if profile not in lock.metadata["profiles"]:
      raise ConfigError("pi-lock-profile")
    piece = lock.metadata["profiles"][profile]
    if piece["profile"] != profile or piece["identity"] != digest({k: v for k, v in piece.items() if k != "identity"}):
      raise ConfigError("pi-lock-profile-identity")
    selection = dependency_selection(workspace.resolved.data) if hasattr(workspace, "resolved") else None
    if piece["recipe_inputs"] != recipe_inputs(workspace.repository, profile, selection):
      raise ConfigError("pi-lock-missing-or-stale")
    return digest({"profile_identity": piece["identity"], "platform": platform_id(), "toolchains": lock.metadata["toolchains"]})

  def root(self, workspace, identity):
    return workspace.instance / "runtimes" / safe_id(identity)

  def status(self, workspace, identity):
    from .pi_runtime_packages import status
    return status(self.root(workspace, identity), identity)

  def executable_paths(self, root):
    return (root / "node_modules/.bin",)

  def toolchain(self, lock):
    return dict(lock.metadata["toolchains"])

  def resolve_lock(self, repository):
    return self._resolve_lock(Path(repository), {})

  def resolve_lock_for(self, workspace):
    if workspace.profile not in PROFILES:
      raise ConfigError("pi-lock-profile")
    return self._resolve_lock(Path(workspace.repository), {workspace.profile: dependency_selection(workspace.resolved.data)})

  def _resolve_lock(self, repository, selections):
    from .publication import publisher_lease
    repository = Path(repository)
    with publisher_lease(repository, "pi") as publisher:
      recipe = read_recipe(repository)
      captured = {profile: recipe_inputs(repository, profile, selections.get(profile)) for profile in PROFILES}
      metadata = {"schema_version": 2, "adapter_version": self.adapter_version,
        **{key: deepcopy(recipe[key]) for key in ("host", "toolchains", "platforms")},
        "modules": {name: source for inputs in captured.values() for name, source in inputs["modules"].items()}, "profiles": {}}
      files = {}
      with tempfile.TemporaryDirectory(prefix="agentcfg-pi-lock-") as directory:
        staging = Path(directory)
        home = staging / "home"
        env = npm_environment(home)
        ensure_minimum_toolchain("Node", recipe["toolchains"]["node"], checked(["node", "--version"], cwd=staging, env=env))
        ensure_exact_toolchain("npm", recipe["toolchains"]["npm"], checked(["npm", "--version"], cwd=staging, env=env))
        for profile, inputs in captured.items():
          root = staging / profile
          ensure_private(root)
          deps = _dependencies(inputs)
          package = json_bytes({"name": "rotom-" + profile, "version": "1.0.0", "private": True, "dependencies": deps})
          with Tree(root) as tree:
            tree.write_new("package.json", package)
          checked(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root, env=env)
          with Tree(root) as tree:
            locked = tree.read("package-lock.json")
            original = tree.read("package.json")
          if not locked or not original or original[0] != package:
            raise ConfigError("pi-lock-resolution-modified-input")
          resolution = _json(locked[0])
          validate_package_lock(resolution, deps)
          piece = {"profile": profile, "recipe_digest": digest(inputs), "recipe_inputs": inputs,
            "closure_digest": digest({"resolution": resolution, "resources": inputs["resources"], "license_notices": _license_notices(inputs)}),
            "package_path": profile + "/package.json", "lock_path": profile + "/package-lock.json",
            "package_json_digest": digest(package), "package_lock_digest": digest(locked[0]), "dependencies": deps,
            "required_files": _required(inputs), "script_audits": _resolution_audits(inputs["script_audits"], resolution)}
          piece["identity"] = digest(piece)
          metadata["profiles"][profile] = piece
          files[piece["package_path"]], files[piece["lock_path"]] = package, locked[0]
      if any(recipe_inputs(repository, profile, selections.get(profile)) != inputs for profile, inputs in captured.items()):
        raise Conflict("Pi实际依赖输入在解析期间发生变化；未发布新锁")
      metadata["identity"] = digest(metadata)
      files["manifest.json"] = json_bytes(metadata)
      return publisher.publish(files, validate=lambda: self._read_lock_unlocked(repository, lock_tree=publisher.tree))

  def sync(self, workspace, lock, *, progress=None):
    from .publication import reader_lease
    with reader_lease(workspace.repository, "pi") as tree:
      current = self._read_lock_unlocked(workspace.repository, lock_tree=tree)
      if current != lock:
        raise ConfigError("pi-lock-missing-or-stale")
      return self._sync(workspace, lock, progress=progress)

  def _sync(self, workspace, lock, *, progress=None):
    from .pi_lifecycle import guard
    from .pi_runtime_packages import activate, recover_repair, seal
    announce = progress or (lambda stage: None)
    identity = self.runtime_identity(workspace, lock)
    if platform_id() not in lock.metadata["platforms"]:
      raise DependencyError("Pi所选平台尚未声明支持")
    piece = lock.metadata["profiles"][workspace.profile]
    final = self.root(workspace, identity)
    with guard(workspace), Tree(workspace.state_root, create=True) as state, instance_lock(state):
      if state.read("pending.json"):
        raise Conflict("存在配置恢复待处理，不能安装依赖")
      ensure_private(final.parent)
      recover_repair(final, identity)
      if self.status(workspace, identity) == "installed":
        return {"installed": False, "identity": identity}
      announce("按现有完整锁暂存安装")
      with tempfile.TemporaryDirectory(prefix=".pi-stage-", dir=final.parent) as directory:
        stage = Path(directory)
        with Tree(stage) as tree:
          tree.write_new("package.json", lock.pairs[workspace.profile][0])
          tree.write_new("package-lock.json", lock.pairs[workspace.profile][1])
        home = stage / "install-home"
        env = npm_environment(home)
        ensure_minimum_toolchain("Node", lock.metadata["toolchains"]["node"], checked(["node", "--version"], cwd=stage, env=env))
        ensure_exact_toolchain("npm", lock.metadata["toolchains"]["npm"], checked(["npm", "--version"], cwd=stage, env=env))
        checked(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=stage, env=env)
        inspected = checked(["npm", "ls", "--all", "--json", "--offline"], cwd=stage, env=env)
        try:
          report = _json(inspected)
          if type(report) is not dict or report.get("problems"):
            raise ValueError()
        except (ValueError, TypeError, RecursionError):
          raise DependencyError("Pi安装依赖或peer检查失败；暂存包未激活") from None
        selection = dependency_selection(workspace.resolved.data) if hasattr(workspace, "resolved") else None
        if recipe_inputs(workspace.repository, workspace.profile, selection) != piece["recipe_inputs"]:
          raise ConfigError("pi-lock-missing-or-stale")
        announce("核验暂存正文与入口")
        try:
          validate_installed_packages(stage, _json(lock.pairs[workspace.profile][1]), piece["script_audits"])
          with Tree(workspace.repository, private=False) as sources, Tree(stage) as destination:
            for item in piece["recipe_inputs"]["resources"]:
              if item["kind"] == "module-support":
                raw = sources.read(item["path"])
                if raw is None or digest(raw[0]) != item["content_identity"]:
                  raise ConfigError("pi-module-support-invalid")
                destination.write_new(item["target"], raw[0])
            for notice in _license_notices(piece["recipe_inputs"]):
              destination.write_new(notice["target_path"], _notice_body(sources, notice))
          shutil.rmtree(home)
          seal(stage, identity, lock.identity, piece, toolchains=lock.metadata["toolchains"])
        except (ConfigError, Conflict, ValueError, KeyError, PathError, RecursionError):
          raise DependencyError("Pi暂存安装内容核验失败；有效运行包及账号保持不变") from None
        activate(stage, final, identity)
      return {"installed": True, "identity": identity}
