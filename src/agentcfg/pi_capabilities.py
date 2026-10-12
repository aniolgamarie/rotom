"""离线能力绑定投影；不安装、激活、读取秘密或签发产品验收。"""
from copy import deepcopy
from dataclasses import dataclass
import re

from .activity import digest
from .paths import relative_path
from .process import DependencyError
from .schema import ConfigError


PROFILES = ("pi-base", "pi-full")
RESOURCE_KINDS = ("extensions", "skills", "prompts", "themes")
ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")
HEX = re.compile(r"[0-9a-f]{64}")


def _fail():
  raise ConfigError("pi-provider-binding")


def _fields(value, keys):
  if not isinstance(value, dict) or set(value) != set(keys): _fail()


def _id(value):
  if not isinstance(value, str) or not ID.fullmatch(value): _fail()


def _hex(value):
  if not isinstance(value, str) or not HEX.fullmatch(value): _fail()


def _ids(value, *, nonempty=False):
  if not isinstance(value, list) or nonempty and not value: _fail()
  for item in value: _id(item)
  if len(set(value)) != len(value): _fail()


def _profiles(value):
  if not isinstance(value, list) or not value or any(profile not in PROFILES for profile in value) or len(set(value)) != len(value): _fail()


def _version(value):
  from .pi_lock_resolution import VERSION
  if not isinstance(value, str) or not VERSION.fullmatch(value): _fail()


def _pointer(value):
  # RFC 6901 转义按 token 解码；字段名前缀不能误当成路径祖先。
  if not isinstance(value, str) or not value.startswith("/") or value == "/" or "\0" in value or re.search(r"~(?:[^01]|$)", value): _fail()
  return tuple(token.replace("~1", "/").replace("~0", "~") for token in value[1:].split("/"))


def _pointers(value):
  if not isinstance(value, list): _fail()
  tokens = [_pointer(item) for item in value]
  if len(set(tokens)) != len(tokens): _fail()
  return tokens


def _prefix(before, after):
  return before == after[:len(before)]


def _refs(value):
  if not isinstance(value, list) or not value or any(not isinstance(path, str) for path in value) or len(set(value)) != len(value): _fail()
  for path in value:
    try: relative_path(path)
    except Exception: _fail()


def _node_identity_fail():
  error = ConfigError("pi-provider-binding")
  try:
    raise error
  except ConfigError:
    # 只清理新边界自有错误，不修改依赖或调用方的异常。
    error.__cause__ = None
    error.__context__ = None
    raise


def _node_source_identity(snapshot):
  failed = False
  try:
    from .pi_node_asset import capture_node_asset
    reference = capture_node_asset(snapshot)
    selection = reference.selection
    metadata = {name: getattr(selection, name) for name in ("schema", "release", "platform", "archive_sha256", "binary_sha256", "license_sha256")}
    projection = {"kind": "asset", "archive_digest": selection.archive_sha256,
      "archive_member": "node-" + selection.release + "-linux-x64/bin/node", "target": "bin/pi-node",
      "platform": selection.platform, "format": "node.tar.gz", "node_archive": metadata}
    result = digest(projection)
  except Exception:
    failed = True
  if failed: _node_identity_fail()
  return result


def source_identity(source):
  """只投影已由 PiLock 校验的非秘密来源字段；认证、URL 与机器状态不进入摘要。"""
  if type(source) is not dict: _node_identity_fail()
  items = tuple(dict.items(source))
  if any(type(key) is not str for key, _ in items): _node_identity_fail()
  snapshot = dict(items)
  if type(snapshot.get("kind")) is str and snapshot["kind"] == "wheel":
    failed = False
    try:
      from .pi_wheel_sources import wheel_source_identity
      result = wheel_source_identity(snapshot)
    except Exception:
      failed = True
    if failed: _node_identity_fail()
    return result
  if "node_archive" in snapshot or type(snapshot.get("format")) is str and snapshot["format"] == "node.tar.gz":
    return _node_source_identity(snapshot)
  if not isinstance(source, dict) or source.get("kind") not in ("npm", "git", "local", "asset"): _fail()
  allowed = {"kind", "package", "version", "resolved", "integrity", "commit", "source_path", "source_tree_digest",
    "archive_digest", "vendor_path", "license_files", "license_sources", "platform", "url", "archive_member", "target", "format", "size", "build_record"}
  if set(source) - allowed: _fail()
  if "build_record" in source and source["kind"] != "asset": _fail()
  from .config import _credential_url
  for field in ("url", "resolved"):
    if field in source and (not isinstance(source[field], str) or _credential_url(source[field])): _fail()
  projection = {"kind": source["kind"]}
  if source["kind"] != "asset":
    _version(source.get("version"))
    package = source.get("package")
    if not isinstance(package, str) or not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", package): _fail()
    projection.update(package=package, version=source["version"])
  if source["kind"] == "npm":
    import base64
    integrity = source.get("integrity")
    try:
      if not isinstance(integrity, str) or not integrity.startswith("sha512-") or len(base64.b64decode(integrity[7:], validate=True)) != 64: _fail()
    except ValueError: _fail()
    projection["integrity"] = integrity
  else:
    for key in ("archive_digest", "source_tree_digest"):
      if key == "archive_digest" or key in source:
        _hex(source.get(key)); projection[key] = source[key]
    if source["kind"] == "git":
      commit = source.get("commit")
      if not isinstance(commit, str) or not re.fullmatch("[0-9a-f]{40}", commit): _fail()
      projection["commit"] = commit
    if source["kind"] == "asset":
      if "build_record" in source:
        from .pi_built_assets import validate_reference
        try: validate_reference(source)
        except Exception: _fail()
        projection["build_record"] = {key: source["build_record"][key] for key in ("recipe", "digest")}
      if "version" in source:
        _version(source["version"]); projection["version"] = source["version"]
      for key in ("archive_member", "target"):
        if key in source:
          try: relative_path(source[key])
          except Exception: _fail()
          projection[key] = source[key]
      if "platform" in source:
        if source["platform"] not in ("linux-x86_64", "linux-arm64", "darwin-x86_64", "darwin-arm64", "all"): _fail()
        projection["platform"] = source["platform"]
      if "format" in source:
        if source["format"] not in ("raw", "tar.gz"): _fail()
        projection["format"] = source["format"]
      if "size" in source:
        if type(source["size"]) is not int or source["size"] < 1: _fail()
        projection["size"] = source["size"]
  return digest(projection)


def _selection(selection):
  _fields(selection, ("schema_version", "profile", "revision", "source_revision", "state", "bindings"))
  if type(selection["schema_version"]) is not int or selection["schema_version"] != 1 or selection["profile"] not in PROFILES or selection["state"] not in ("current", "candidate", "accepted"): _fail()
  for field in ("revision", "source_revision"):
    if type(selection[field]) is not int or selection[field] < 1: _fail()
  if not isinstance(selection["bindings"], list) or not selection["bindings"]: _fail()
  pairs = []
  for binding in selection["bindings"]:
    _fields(binding, ("capability_id", "provider_id"))
    _id(binding["capability_id"]); _id(binding["provider_id"])
    pairs.append((binding["capability_id"], binding["provider_id"]))
  if len(set(pairs)) != len(pairs): _fail()
  return tuple(sorted(pairs))


def selection_identity(selection):
  """包括 state/revision 的闭合规范输入；不含自身 digest 或外部验收身份。"""
  pairs = _selection(selection)
  return digest({**selection, "bindings": [{"capability_id": capability, "provider_id": provider} for capability, provider in pairs]})


def _catalog(catalog):
  _fields(catalog, ("schema_version", "revision", "capabilities", "source_profiles", "resource_profiles"))
  if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1 or type(catalog["revision"]) is not int or catalog["revision"] < 1: _fail()
  for table in ("source_profiles", "resource_profiles"):
    if not isinstance(catalog[table], dict): _fail()
    for name, profiles in catalog[table].items(): _id(name); _profiles(profiles)
  if not isinstance(catalog["capabilities"], dict): _fail()
  for name, capability in catalog["capabilities"].items():
    _id(name)
    _fields(capability, ("profiles", "required", "contract_version", "owner_domain", "single_owner", "config_fields", "state_owners", "source_ids", "resource_ids"))
    _profiles(capability["profiles"]); _id(capability["owner_domain"])
    if type(capability["required"]) is not bool or type(capability["single_owner"]) is not bool or not isinstance(capability["contract_version"], str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", capability["contract_version"]): _fail()
    _pointers(capability["config_fields"]); _ids(capability["state_owners"]); _ids(capability["source_ids"], nonempty=True); _ids(capability["resource_ids"])
    if set(capability["source_ids"]) - catalog["source_profiles"].keys() or set(capability["resource_ids"]) - catalog["resource_profiles"].keys(): _fail()


def _source_version(declared, sources):
  source = sources.get(declared["source_id"]) if sources is not None else None
  if isinstance(source, dict) and source.get("kind") == "wheel":
    failed = False
    try:
      from .pi_wheel_sources import validate_wheel_source
      validate_wheel_source(source, locked="vendor_path" in source)
      if type(declared["source_version"]) is not str or declared["source_version"] != source["version"]:
        raise ValueError()
    except Exception:
      failed = True
    if failed: _node_identity_fail()
  elif declared["source_version"] is not None:
    _version(declared["source_version"])


def _providers(providers, catalog, *, sources=None):
  if not isinstance(providers, dict): _fail()
  for name, provider in providers.items():
    _id(name)
    fields = ("provider_id", "capability_id", "source_id", "source_version", "source_identity", "contract_version", "verified_host_versions", "engines", "requires", "conflicts", "public_entrypoints", "config_fields", "state_owners", "resource_ids", "migration_refs", "uninstall_refs", "rollback_refs")
    optional = tuple(key for key in ("support_sources", "candidate_host_versions") if isinstance(provider, dict) and key in provider)
    _fields(provider, (*fields, *optional))
    for field in ("provider_id", "capability_id", "source_id"): _id(provider[field])
    if name != provider["provider_id"] or provider["capability_id"] not in catalog["capabilities"] or provider["source_id"] not in catalog["source_profiles"]: _fail()
    _hex(provider["source_identity"])
    _source_version(provider, sources)
    supporting = provider.get("support_sources", [])
    if not isinstance(supporting, list): _fail()
    seen = {provider["source_id"]}
    for source in supporting:
      _fields(source, ("source_id", "source_version", "source_identity"))
      _id(source["source_id"]); _hex(source["source_identity"])
      _source_version(source, sources)
      if source["source_id"] in seen or source["source_id"] not in catalog["source_profiles"]: _fail()
      seen.add(source["source_id"])
    if not isinstance(provider["contract_version"], str): _fail()
    verified = provider["verified_host_versions"]
    candidates = provider.get("candidate_host_versions", [])
    if not isinstance(verified, list) or not isinstance(candidates, list) or not (verified or candidates): _fail()
    if "candidate_host_versions" in provider and not candidates: _fail()
    for versions in (verified, candidates):
      for version in versions: _version(version)
      if len(set(versions)) != len(versions): _fail()
    if not isinstance(provider["engines"], list) or not provider["engines"] or any(engine not in ("node", "bun") for engine in provider["engines"]) or len(set(provider["engines"])) != len(provider["engines"]): _fail()
    for field in ("requires", "conflicts", "state_owners", "resource_ids"): _ids(provider[field])
    if (set(provider["requires"]) | set(provider["conflicts"])) - catalog["capabilities"].keys(): _fail()
    _pointers(provider["config_fields"])
    if not isinstance(provider["public_entrypoints"], list) or not provider["public_entrypoints"]: _fail()
    for entry in provider["public_entrypoints"]:
      if not isinstance(entry, str) or not re.fullmatch(r"[A-Za-z0-9@_./:#-]+", entry) or entry.startswith("/") or ".." in entry.split("/"): _fail()
    if len(set(provider["public_entrypoints"])) != len(provider["public_entrypoints"]): _fail()
    for field in ("migration_refs", "uninstall_refs", "rollback_refs"): _refs(provider[field])


def validate_manifest_bindings(bindings, profile_slices, *, sources=None):
  """校验全锁结构与引用，不读取正文、不验证未选择 profile 的验收证明。"""
  _fields(bindings, ("schema_version", "catalog", "providers", "selections"))
  if type(bindings["schema_version"]) is not int or bindings["schema_version"] != 1: _fail()
  _catalog(bindings["catalog"]); _providers(bindings["providers"], bindings["catalog"], sources=sources)
  selections = bindings["selections"]
  if not isinstance(selections, dict) or not selections or set(selections) != set(profile_slices): _fail()
  for profile, selection in selections.items():
    pairs = _selection(selection)
    if selection["profile"] != profile or profile not in PROFILES: _fail()
    if set(profile_slices[profile]["capability_ids"]) != {capability for capability, _ in pairs}: _fail()
    if selection["source_revision"] != bindings["catalog"]["revision"]: _fail()
    for capability, provider in pairs:
      if capability not in bindings["catalog"]["capabilities"] or provider not in bindings["providers"]: _fail()
      if bindings["providers"][provider]["capability_id"] != capability: _fail()


@dataclass(frozen=True)
class ValidatedSelection:
  profile: str
  state: str
  selection_digest: str
  catalog_digest: str
  binding_digest: str
  lock_identity: str
  slice_digest: str
  source_expectations: tuple
  resource_expectations: tuple
  acceptance_context_digest: str


def _resolve_selection_data(catalog, providers, selection, metadata, *, lock_identity, host_version, engine):
  """只验证闭合上下文；内部计算不判定其是否通过外部验收。"""
  _catalog(catalog); _providers(providers, catalog, sources=metadata["sources"]); pairs = _selection(selection); _version(host_version)
  identity = selection_identity(selection); profile = selection["profile"]
  if selection["source_revision"] != catalog["revision"]: _fail()
  chosen = {capability for capability, _ in pairs}
  required = {name for name, capability in catalog["capabilities"].items() if capability["required"] and profile in capability["profiles"]}
  if required - chosen: _fail()
  domains = {}; fields = []; owners = set(); resources = {}; sources = {}; selected = []
  for capability_id, provider_id in pairs:
    if capability_id not in catalog["capabilities"] or provider_id not in providers: _fail()
    capability = catalog["capabilities"][capability_id]; provider = providers[provider_id]
    host_versions = provider["verified_host_versions"]
    if selection["state"] == "candidate": host_versions = [*host_versions, *provider.get("candidate_host_versions", [])]
    if provider["capability_id"] != capability_id or profile not in capability["profiles"] or provider["contract_version"] != capability["contract_version"] or host_version not in host_versions or engine not in provider["engines"]: _fail()
    domain = capability["owner_domain"]
    domain_rows = domains.setdefault(domain, [])
    if domain_rows and (capability["single_owner"] or any(row["single_owner"] for row in domain_rows)): _fail()
    domain_rows.append(capability)
    if set(provider["requires"]) - chosen or set(provider["conflicts"]) & chosen: _fail()
    allowed = _pointers(capability["config_fields"])
    for path in _pointers(provider["config_fields"]):
      if not any(_prefix(parent, path) for parent in allowed) or any(_prefix(path, other) or _prefix(other, path) for other in fields): _fail()
      fields.append(path)
    if set(provider["state_owners"]) - set(capability["state_owners"]) or owners & set(provider["state_owners"]): _fail()
    owners.update(provider["state_owners"])
    for resource in provider["resource_ids"]:
      if resource not in capability["resource_ids"] or profile not in catalog["resource_profiles"][resource] or resource in resources: _fail()
      resources[resource] = capability_id
    # 辅助包/二进制同样进入选择和安装身份，不能伪造新能力或绕过来源闭包。
    for declared in [provider, *provider.get("support_sources", [])]:
      source_id = declared["source_id"]
      if source_id not in capability["source_ids"] or profile not in catalog["source_profiles"][source_id]: _fail()
      source = metadata["sources"].get(source_id)
      if source is None: raise DependencyError("Pi绑定来源尚未锁定")
      actual = source_identity(source)
      if declared["source_version"] != source.get("version") or declared["source_identity"] != actual: _fail()
      sources[source_id] = (source_id, source.get("version"), actual)
    selected.append(deepcopy(provider))
  piece = metadata["profile_slices"].get(profile)
  if piece is None or piece["engine"] != engine or len(set(piece["source_ids"])) != len(piece["source_ids"]) or set(piece["source_ids"]) != set(sources):
    raise DependencyError("Pi绑定与依赖切片不匹配")
  loaded = {}; seen = set()
  if set(piece["resource_manifest"]) - set(RESOURCE_KINDS): raise DependencyError("Pi资源切片不匹配")
  for kind in RESOURCE_KINDS:
    entries = piece["resource_manifest"].get(kind, [])
    for entry in entries:
      if entry["id"] in seen or resources.get(entry["id"]) != entry["capability_id"]: raise DependencyError("Pi资源切片不匹配")
      seen.add(entry["id"])
    loaded[kind] = tuple(sorted(entry["id"] for entry in entries))
  if seen != set(resources): raise DependencyError("Pi资源切片不匹配")
  _hex(lock_identity)
  catalog_digest, binding_digest, slice_digest = digest(catalog), digest(selected), digest(piece)
  source_expectations, resource_expectations = tuple(sorted(sources.values())), tuple(loaded.items())
  # 不包含外部证明或自身摘要，避免自引用；状态与实际兼容环境均须精确绑定。
  context = digest({"selection_digest": identity, "catalog_digest": catalog_digest, "binding_digest": binding_digest,
    "lock_identity": lock_identity, "slice_digest": slice_digest, "sources": source_expectations,
    "resources": resource_expectations, "host_version": host_version, "engine": engine})
  return ValidatedSelection(profile, selection["state"], identity, catalog_digest, binding_digest, lock_identity,
    slice_digest, source_expectations, resource_expectations, context)


def _resolve_selection(catalog, providers, selection, lock, *, host_version, engine):
  return _resolve_selection_data(catalog, providers, selection, lock.metadata,
    lock_identity=lock.identity, host_version=host_version, engine=engine)


def acceptance_context_identity(catalog, providers, selection, lock, *, host_version, engine):
  """生成严格验证后的完整非秘密上下文身份；可计算摘要本身不证明验收或提供授权。"""
  return _resolve_selection(catalog, providers, selection, lock, host_version=host_version, engine=engine).acceptance_context_digest


def validate_selection_data(catalog, providers, selection, metadata, *, lock_identity, host_version, engine, accepted_binding_digest=None):
  """校验显式选择数据；结果与可计算proof均不认证来源或提供激活授权。"""
  result = _resolve_selection_data(catalog, providers, selection, metadata,
    lock_identity=lock_identity, host_version=host_version, engine=engine)
  if accepted_binding_digest is not None: _hex(accepted_binding_digest)
  if result.state == "accepted" and accepted_binding_digest != result.acceptance_context_digest: _fail()
  return result


def validate_selection(catalog, providers, selection, lock, *, host_version, engine, accepted_binding_digest=None):
  """消费已校验 PiLock；accepted 的上下文证明仅能来自可信验收控制面，不产生激活授权。"""
  return validate_selection_data(catalog, providers, selection, lock.metadata,
    lock_identity=lock.identity, host_version=host_version, engine=engine, accepted_binding_digest=accepted_binding_digest)


def check_installed(selection, observed):
  """消费可信 inventory 的完整来源观测；调用方须先闭合整个安装树及传递依赖。

  本函数不扫描文件；筛选过的来源子集不能证明树中没有夹带，也不能证明实际加载。
  """
  if not isinstance(observed, list): _fail()
  actual = []
  for source in observed:
    _fields(source, ("source_id", "version", "source_identity")); _id(source["source_id"]); _hex(source["source_identity"])
    if source["version"] is not None: _version(source["version"])
    actual.append((source["source_id"], source["version"], source["source_identity"]))
  if len({row[0] for row in actual}) != len(actual) or tuple(sorted(actual)) != selection.source_expectations:
    raise DependencyError("Pi实际安装来源与绑定不匹配")
  return True


def check_loaded(selection, observed):
  """核对实际扩展/Skill/prompt/theme发现结果；原生公开入口不伪造成扩展注册。"""
  _fields(observed, RESOURCE_KINDS)
  actual = []
  for kind in RESOURCE_KINDS:
    values = observed[kind]
    if not isinstance(values, list): _fail()
    for value in values: _id(value)
    if len(set(values)) != len(values): raise DependencyError("Pi实际加载资源重复")
    actual.append((kind, tuple(sorted(values))))
  if tuple(actual) != selection.resource_expectations: raise DependencyError("Pi实际加载资源与绑定不匹配")
  return True


def runtime_identity_payload(selection, *, runtime_digest, adapter_version, platform):
  """绑定验证过的选择和不可变依赖快照；变化检测摘要不是激活授权。"""
  _hex(runtime_digest)
  if not isinstance(adapter_version, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", adapter_version) or platform not in ("linux-x86_64", "linux-arm64", "darwin-x86_64", "darwin-arm64"): _fail()
  return {"profile": selection.profile, "selection": selection.selection_digest, "catalog": selection.catalog_digest,
    "bindings": selection.binding_digest, "lock": selection.lock_identity, "slice": selection.slice_digest,
    "binding_context": selection.acceptance_context_digest,
    "runtime": runtime_digest, "adapter_version": adapter_version, "platform": platform}


def runtime_identity(selection, *, runtime_digest, adapter_version, platform):
  """规范投影摘要仅用于身份绑定；不代表验收或激活授权。"""
  return digest(runtime_identity_payload(selection, runtime_digest=runtime_digest, adapter_version=adapter_version, platform=platform))


def config_identity(*, profile, effective_config_digest, policy_digest, project_constraints_digest):
  """仅接收读取秘密前已冻结的非秘密投影身份；hex 校验不能识别秘密散列。"""
  if profile not in PROFILES: _fail()
  for value in (effective_config_digest, policy_digest, project_constraints_digest): _hex(value)
  return digest({"profile": profile, "effective_config": effective_config_digest, "policy": policy_digest, "project_constraints": project_constraints_digest})
