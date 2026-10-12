"""已选择的指令资源可以只读；不把整个实例或相邻账号目录开放给文件工具。"""

import hashlib
import json
from pathlib import Path
import re
import stat
from copy import deepcopy
from functools import lru_cache

from .paths import relative_path
from .storage import Conflict, Tree


@lru_cache(maxsize=4)
def _receipt_validators(schema_text):
  from jsonschema import Draft202012Validator
  from referencing import Registry
  schema = json.loads(schema_text)
  full = Draft202012Validator(schema, registry=Registry())
  try:
    files = schema["properties"]["files"]
    if ("files" not in schema.get("required", []) or set(files) != {"type", "propertyNames", "additionalProperties"}
        or files["type"] != "object"): raise ValueError()
    union = files["additionalProperties"]
    if set(union) != {"oneOf"} or type(union["oneOf"]) is not list or not union["oneOf"]: raise ValueError()
    # 分离schema不能改变相对$ref解析；遇到新结构完整fallback。
    def refs(value):
      if isinstance(value, dict): return "$ref" in value or any(refs(item) for item in value.values())
      return isinstance(value, list) and any(refs(item) for item in value)
    if refs(files): raise ValueError()
    branches = {}
    for branch in union["oneOf"]:
      if (set(branch) != {"type", "properties", "required", "additionalProperties"} or branch["type"] != "object"
          or branch["additionalProperties"] is not False or "kind" not in branch["required"]): raise ValueError()
      discriminator = branch["properties"]["kind"]
      if set(discriminator) != {"const"} or type(discriminator["const"]) is not str or discriminator["const"] in branches: raise ValueError()
      branches[discriminator["const"]] = Draft202012Validator(branch, registry=Registry())
    envelope = deepcopy(schema); envelope["properties"]["files"] = {"type": "object"}
    return full, Draft202012Validator(envelope, registry=Registry()), Draft202012Validator(files["propertyNames"], registry=Registry()), branches
  except (KeyError, TypeError, ValueError):
    return full, None, None, None


def _valid_receipt(receipt, schema):
  full, envelope, names, branches = _receipt_validators(json.dumps(schema, sort_keys=True, separators=(",", ":")))
  if envelope is None: return full.is_valid(receipt)
  if not envelope.is_valid(receipt): return False
  for name, row in receipt["files"].items():
    if not names.is_valid(name) or not isinstance(row, dict) or not isinstance(row.get("kind"), str): return False
    branch = branches.get(row["kind"])
    if branch is None or not branch.is_valid(row): return False
  return True


def tree_digest(root):
  root = Path(root)
  entries = []
  def walk(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode): raise Conflict("RESOURCE_LINK_REJECTED")
    if stat.S_ISDIR(info.st_mode):
      for child in sorted(path.iterdir(), key=lambda p: p.name.encode("utf-16-be")): walk(child)
    elif stat.S_ISREG(info.st_mode):
      with Tree(root if root.is_dir() else root.parent, private=False) as tree:
        name = path.relative_to(root).as_posix() if root.is_dir() else root.name
        raw = tree.read(name)
      if raw is None: raise Conflict("RESOURCE_CHANGED")
      entries.append([path.relative_to(root).as_posix() if path != root else "", info.st_mode & 0o111, hashlib.sha256(raw[0]).hexdigest()])
    else: raise Conflict("RESOURCE_TYPE_REJECTED")
  walk(root)
  return hashlib.sha256(json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def selected_resource(host, manifest, path):
  if manifest.get("profile_id") in ("pi-base", "pi-full"):
    return _modern_selected_resource(host, manifest, path)
  instance = Path(host.config["instance_root"])
  with Tree(instance) as tree:
    raw = tree.read("pi-home/loaded-manifest.json")
  if raw is None: return None
  loaded = json.loads(raw[0])
  allowed = [instance / relative_path(value) for value in manifest.get("resources", {}).get("skills", [])]
  with Tree(host.runtime_root) as tree:
    profile = tree.read("runtime/profile.json")
  if profile:
    installed = json.loads(profile[0])
    capabilities = _selected_capabilities(manifest)
    allowed += [host.runtime_root / relative_path(row["path"]) for row in installed.get("resources", {}).get("skills", [])
      if row["capability_id"] in capabilities]
  allowed += [Path(row["root"]) / relative_path(row["path"]) for row in manifest.get("external_skills", [])]
  matches = [row for row in loaded.get("resources", {}).get("skills", []) if Path(row["path"]) in allowed and (
    path == Path(row["path"]) or Path(row["path"]).is_dir() and path.is_relative_to(Path(row["path"])))]
  if len(matches) != 1: return None
  selected = matches[0]
  root = Path(selected["path"])
  # 资源入口须是真正的技能目录/文件；auth.json不能伪装成技能入口。
  if root.is_file() and root.name != "SKILL.md" or root.is_dir() and not (root / "SKILL.md").is_file():
    raise Conflict("RESOURCE_SKILL_ENTRY")
  if tree_digest(root) != selected["digest"]: raise Conflict("RESOURCE_CHANGED")
  return {"path": str(root), "digest": selected["digest"]}


def _modern_selected_resource(host, manifest, path):
  """部署显式选择的指令资源；不要求/伪造SDK loaded证明。"""
  instance = Path(host.config["instance_root"])
  paths = manifest.get("resources", {}).get("skills", [])
  ids = manifest.get("resource_ids", {}).get("skills", {})
  if (type(paths) is not list or any(type(value) is not str for value in paths)
      or type(ids) is not dict or any(type(key) is not str or type(value) is not str for key, value in ids.items())
      or len(set(paths)) != len(paths) or len(set(ids.values())) != len(ids) or set(paths) != set(ids.values())):
    raise Conflict("RESOURCE_CAPABILITY_INVALID")
  allowed = [instance / relative_path(value) for value in paths]
  capabilities = _selected_capabilities(manifest)
  # 普通项目路径没有资源授权分支；所选实例/外部Skill及runtime路径才核原slice。
  external = [Path(row["root"]) / relative_path(row["path"]) for row in manifest.get("external_skills", [])]
  if not path.is_relative_to(host.runtime_root) and not any(path == root or path.is_relative_to(root) for root in (*allowed, *external)):
    return None
  piece = _bound_resource_slice(host, manifest)
  if piece is not None:
    resources = piece["resource_manifest"]
    if type(resources) is not dict or type(resources.get("skills", [])) is not list:
      raise Conflict("RESOURCE_RUNTIME_INVALID")
    for row in resources.get("skills", []):
      if (type(row) is not dict or set(row) != {"id", "capability_id", "path"}
          or any(type(value) is not str for value in row.values())):
        raise Conflict("RESOURCE_RUNTIME_INVALID")
      if row["capability_id"] in capabilities:
        allowed.append(host.runtime_root / relative_path(row["path"]))
  allowed += external
  matches = [root for root in allowed if path == root or root.is_dir() and path.is_relative_to(root)]
  if len(matches) != 1: return None
  root = matches[0]
  if root.is_file() and root.name != "SKILL.md" or root.is_dir() and not (root / "SKILL.md").is_file():
    raise Conflict("RESOURCE_SKILL_ENTRY")
  return {"path": str(root), "digest": tree_digest(root)}


def _bound_resource_slice(host, manifest):
  """当前声明绑定重验，不枚举整个安装树，也不是SourceHold。"""
  from .pi_catalog import read_schema
  from .pi_dependencies import digest, platform_id
  from .pi_modern_launcher import validate_profile
  from .pi_runtime_packages import MAX_RECEIPT
  def pairs(items):
    result = {}
    for key, value in items:
      if key in result: raise ValueError()
      result[key] = value
    return result
  def nonfinite(_value): raise ValueError()
  try:
    with Tree(host.runtime_root) as tree:
      receipt_raw = tree.read(".agentcfg-receipt.json", max_bytes=MAX_RECEIPT)
      profile_raw = tree.read("runtime/profile.json", max_bytes=16 * 1024 * 1024)
    if receipt_raw is None or profile_raw is None or receipt_raw[1] != 0o600 or profile_raw[1] != 0o600: raise ValueError()
    receipt = json.loads(receipt_raw[0], object_pairs_hook=pairs, parse_constant=nonfinite)
    profile = json.loads(profile_raw[0], object_pairs_hook=pairs, parse_constant=nonfinite)
    if not _valid_receipt(receipt, read_schema("runtime-receipt")): raise ValueError()
    identity = host.runtime_root.name; piece = receipt["slice"]; binding = receipt["binding_identity"]
    base = digest({"lock_identity": receipt["lock_identity"], "slice_identity": receipt["slice_identity"],
      "platform": receipt["platform"], "toolchain_identity": receipt["toolchain_identity"]})
    if (receipt["schema_version"] != 2 or receipt["identity"] != identity or receipt["lock_identity"] != host.config["lock_identity"]
        or receipt["slice_identity"] != host.config["slice_identity"] or piece["identity"] != receipt["slice_identity"]
        or digest({key: value for key, value in piece.items() if key != "identity"}) != receipt["slice_identity"]
        or receipt["platform"] != platform_id() or digest(receipt["toolchains"]) != receipt["toolchain_identity"]
        or binding["runtime"] != base or binding["lock"] != receipt["lock_identity"] or binding["slice"] != digest(piece)
        or binding["platform"] != receipt["platform"] or binding["profile"] != manifest["profile_id"]
        or binding["adapter_version"] != "pi-1" or digest(binding) != identity): raise ValueError()
    validate_profile(host.runtime_root, piece, identity=identity, lock_identity=host.config["lock_identity"],
      toolchains=receipt["toolchains"], profile_id=manifest["profile_id"])
    # validator会fresh-read；再次核本次严格解析的profile仍同一声明，拒绝重复键/漂移。
    with Tree(host.runtime_root) as tree: latest = tree.read("runtime/profile.json", max_bytes=16 * 1024 * 1024)
    if latest is None or latest[1] != 0o600 or latest[0] != profile_raw[0] or profile["resources"] != piece["resource_manifest"]: raise ValueError()
    return piece
  except Exception:
    raise Conflict("RESOURCE_RUNTIME_INVALID") from None


def _selected_capabilities(manifest):
  if manifest.get("profile_id") not in ("pi-base", "pi-full"):
    return manifest.get("plugins", [])
  plugins = manifest.get("plugins", [])
  mapping = manifest.get("plugin_capabilities", {} if plugins == [] else None)
  if (type(plugins) is not list or any(type(name) is not str for name in plugins)
      or len(set(plugins)) != len(plugins) or type(mapping) is not dict
      or any(type(key) is not str for key in mapping) or set(mapping) != set(plugins)):
    raise Conflict("RESOURCE_CAPABILITY_INVALID")
  capabilities = set(); tools = set()
  for row in mapping.values():
    if (type(row) is not dict or set(row) != {"capability_id", "model_tools"}
        or type(row["capability_id"]) is not str or re.fullmatch("[a-z][a-z0-9_-]{0,63}", row["capability_id"]) is None
        or row["capability_id"] in capabilities or type(row["model_tools"]) is not list or len(row["model_tools"]) > 64):
      raise Conflict("RESOURCE_CAPABILITY_INVALID")
    capabilities.add(row["capability_id"])
    for name in row["model_tools"]:
      if type(name) is not str or re.fullmatch("[a-zA-Z][a-zA-Z0-9_-]{0,63}", name) is None or name in tools:
        raise Conflict("RESOURCE_CAPABILITY_INVALID")
      tools.add(name)
  return capabilities


def read_resource(host, record):
  resource = record["resource"]
  root = Path(resource["path"])
  if tree_digest(root) != resource["digest"]: raise Conflict("RESOURCE_CHANGED")
  path = Path(record["path"])
  with Tree(root if root.is_dir() else root.parent, private=False) as tree:
    name = path.relative_to(root).as_posix() if root.is_dir() else root.name
    raw = tree.read(name, max_bytes=16 * 1024 * 1024)
  if raw is None: raise Conflict("RESOURCE_MISSING")
  return raw[0]
