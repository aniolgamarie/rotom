"""显式来源加载与离线解析；秘密、部署和宿主运行不属于解析输入。"""

from copy import deepcopy
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import parse_qsl, urlsplit

from .merge import Provenance, merge_layers
from .paths import PathError, configured_path, relative_path, safe_id
from .schema import (AdapterPolicy, AdapterSchemas, AuthenticationClaim, ConfigError,
                     _bundle, separate_local, validate_document)
from .secrets import SecretStore


@dataclass(frozen=True)
class LocalConfig:
  data: dict = field(repr=False)


@dataclass(frozen=True)
class AdapterSources:
  agent: Path = field(repr=False)
  bindings: Path = field(repr=False)
  plugins: Path = field(repr=False)


@dataclass(frozen=True)
class SourceInputs:
  registries: tuple[Path, ...] = field(default=(), repr=False)
  profiles: tuple[Path, ...] = field(default=(), repr=False)
  adapters: dict[str, AdapterSources] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Catalog:
  registry: dict[str, dict] = field(repr=False)
  profiles: dict[str, dict] = field(repr=False)
  adapter_documents: dict[str, dict[str, dict]] = field(repr=False)
  adapter_schemas: AdapterSchemas = field(repr=False)


def _read_toml(path: Path) -> dict:
  code = None
  data = None
  try:
    with path.open("rb") as source:
      data = tomllib.load(source)
  except (tomllib.TOMLDecodeError, UnicodeError):
    code = "parse"
  except (OSError, ValueError):
    code = "read"
  if code:
    raise ConfigError(code)
  return data


def load_local(path: Path, *, adapter_schemas: AdapterSchemas | None = None) -> tuple[LocalConfig, SecretStore]:
  missing = False
  try:
    document = read_local_document(path)
  except FileNotFoundError:
    missing = True
  if missing:
    raise ConfigError("read")
  ordinary, store = separate_local(document)
  validate_document("local", ordinary, adapter_schemas=adapter_schemas)
  return LocalConfig(ordinary), store


def read_local_document(path):
  from .paths import read_private_file
  from .storage import Conflict
  error = None
  try:
    content = read_private_file(path)
  except FileNotFoundError:
    error = "missing"
  except (OSError, PathError):
    error = "unsafe"
  if error == "missing":
    raise FileNotFoundError()
  if error:
    raise Conflict("本地配置读取不安全；检查访问权限、路径无链接、属主为当前用户、文件 0600、私人父目录 0700")
  try:
    return tomllib.loads(content.decode("utf-8"))
  except (tomllib.TOMLDecodeError, UnicodeError):
    pass
  raise ConfigError("parse", ("local", "TOML"))


def load_sources(explicit_sources: SourceInputs, *, adapter_schemas: AdapterSchemas) -> Catalog:
  """不发现目录、不加载秘密；仅技能允许精确指向旧 path 的一次显式整包替换。"""
  registry = {kind: {} for kind in ("providers", "models", "mcp", "rules", "skills")}
  profiles = {}
  adapter_documents = {}
  for path in explicit_sources.registries:
    data = _read_toml(path)
    validate_document("registry", data)
    for kind, entities in registry.items():
      additions = data.get(kind, {})
      if kind == "skills":
        for key, skill in additions.items():
          invalid = False
          try:
            relative_path(skill["path"])
            if "override" in skill:
              relative_path(skill["override"])
          except PathError:
            invalid = True
          if invalid:
            raise ConfigError("path", ("registry", "skills", "<key>"))
          previous = entities.get(key)
          if previous is None:
            if "override" in skill:
              raise ConfigError("reference", ("registry", "skills", "<key>", "override"))
          elif (skill.get("override") != previous["path"] or skill["path"] == previous["path"]
                or "override" in previous):
            raise ConfigError("duplicate", ("registry", "skills", "<key>"))
      elif entities.keys() & additions.keys():
        raise ConfigError("duplicate", ("registry", kind, "<key>"))
      entities.update(additions)
  for path in explicit_sources.profiles:
    data = _read_toml(path)
    validate_document("profile", data, adapter_schemas=adapter_schemas, partial_options=True)
    if data["id"] in profiles:
      raise ConfigError("duplicate", ("profile", "<key>"))
    profiles[data["id"]] = data
  for adapter_id, sources in explicit_sources.adapters.items():
    documents = {}
    for kind in ("agent", "bindings", "plugins"):
      data = _read_toml(getattr(sources, kind))
      validate_document(kind, data, adapter_schemas=adapter_schemas, adapter_id=adapter_id)
      documents[kind] = data
    adapter_documents[adapter_id] = documents
  # profile 身份只来自已校验公共来源，不接受 local 指定 adapter。
  context = AdapterSchemas(bundles=dict(adapter_schemas.bundles),
                           profile_agents={key: value["agent"] for key, value in profiles.items()})
  return Catalog(registry, profiles, adapter_documents, context)


@dataclass(frozen=True)
class ResolvedConfig:
  data: dict = field(repr=False)
  provenance: Provenance = field(repr=False)
  validated_profiles: int


_SELECTIONS = ("providers", "models", "rules", "skills", "plugins", "mcp")
_RESERVED_ENVIRONMENT = frozenset({
  "HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
  "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
  "NODE_OPTIONS", "NODE_PATH", "npm_config_userconfig", "npm_config_globalconfig",
  "NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG",
})
_CREDENTIAL_NAMES = frozenset({
  "API_KEY", "APIKEY", "ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN", "PASSWORD",
  "PASSWD", "SECRET", "CLIENT_SECRET", "AUTHORIZATION", "CREDENTIAL", "CREDENTIAL_REF",
})


def _credential_name(name: str) -> bool:
  normalized = name.upper().replace("-", "_")
  return normalized in _CREDENTIAL_NAMES or any(
    normalized.endswith("_" + suffix) for suffix in _CREDENTIAL_NAMES)


def _credential_url(value: str) -> bool:
  # 仅检查明确凭据通道；普通 opaque 字符串不可能被证明绝不含秘密。
  invalid = False
  try:
    parsed = urlsplit(value)
    if parsed.netloc:
      invalid = (parsed.username is not None or parsed.password is not None
                 or any(_credential_name(key) for key, _ in parse_qsl(parsed.query)))
  except ValueError:
    invalid = True
  return invalid


def _path(value: str, location: tuple[str, ...]) -> str:
  result = None
  try:
    result = str(configured_path(value))
  except PathError:
    pass
  if result is None:
    raise ConfigError("path", location)
  return result


def _machine_layers(machine: dict, credential_targets: set[str]) -> tuple[dict, dict]:
  defaults = {"paths": {}, "environment": {"inherit": [], "values": {}}}
  local = deepcopy(machine)
  paths = local.get("paths", {})
  for field_name, variable, fallback, suffix in (
    ("instances_root", "XDG_DATA_HOME", "~/.local/share", "agentcfg/instances"),
    ("state_root", "XDG_STATE_HOME", "~/.local/state", "agentcfg"),
    ("cache_root", "XDG_CACHE_HOME", "~/.cache", "agentcfg"),
  ):
    location = ("machine", "paths", field_name)
    if field_name in paths:
      paths[field_name] = _path(paths[field_name], location)
    else:
      base = _path(os.environ.get(variable, fallback), location)
      defaults["paths"][field_name] = str(Path(base) / suffix)
  if "editor" in local:
    editor = local["editor"]
    if editor.startswith(("/", "~/")):
      local["editor"] = _path(editor, ("machine", "editor"))
    elif not re.fullmatch(r"[\w.+-]+", editor) or editor in (".", ".."):
      raise ConfigError("editor", ("machine", "editor"))
  environment = local.get("environment", {})
  reserved = _RESERVED_ENVIRONMENT | credential_targets
  for channel in ("inherit", "values"):
    for name in environment.get(channel, {}):
      location = ("machine", "environment", channel, "<key>")
      if name in reserved or name.startswith(("AGENTCFG_", "DSH_")) or _credential_name(name):
        raise ConfigError("environment", location)
      if channel == "values":
        value = environment[channel][name]
        if "\0" in value or value.startswith("secret:") or _credential_url(value):
          raise ConfigError("environment", location)
  return defaults, local


def _callback(callback, *args):
  failed = False
  result = None
  try:
    result = callback(*(deepcopy(arg) for arg in args))
  except ConfigError as error:
    if error.code == "oauth-provider-options-not-supported":
      result = "oauth-provider-options-not-supported"
    failed = True
  except Exception:
    failed = True
  if failed:
    if result == "oauth-provider-options-not-supported":
      raise ConfigError("oauth-provider-options-not-supported", ("profile", "agent_options", "provider_options"))
    raise ConfigError("adapter", ("adapter",))
  return result


def _adapter_policy(bundle, documents: dict, context: AdapterSchemas, profile_id: str) -> AdapterPolicy:
  policy = _callback(bundle.policy, documents)
  valid = False
  try:
    valid = (isinstance(policy, AdapterPolicy) and isinstance(policy.defaults, dict)
             and isinstance(policy.plugins, dict) and isinstance(policy.credential_targets, frozenset)
             and all(isinstance(value, dict) and safe_id(key) for key, value in policy.plugins.items())
             and all(isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                     for name in policy.credential_targets))
  except Exception:
    valid = False
  if not valid:
    raise ConfigError("adapter", ("adapter",))
  validate_document("local", {"schema_version": 1, "machine": {"id": "adapter"},
                    "overrides": {"profiles": {profile_id: policy.defaults}}}, adapter_schemas=context)
  return deepcopy(policy)


def _authentication(bundle, data: dict) -> None:
  claims = _callback(bundle.authentication_claims, data)
  valid = False
  try:
    if isinstance(claims, tuple) and all(isinstance(claim, AuthenticationClaim) for claim in claims):
      providers = [safe_id(claim.provider) for claim in claims]
      owners = [safe_id(claim.owner) for claim in claims]
      # 同 owner 重复也是竞争声明；不同 profile/实例之间不做全局认证推断。
      valid = (len(providers) == len(set(providers)) and set(providers) == set(data["providers"])
               and len(owners) == len(providers))
  except Exception:
    valid = False
  if not valid:
    raise ConfigError("authentication-owner", ("providers", "<key>"))


def _selected(data: dict, profile: dict) -> dict:
  result = deepcopy(data)
  for kind in _SELECTIONS:
    if any(entity_id not in data[kind] for entity_id in profile[kind]):
      raise ConfigError("reference", ("profile", kind, "<item>"))
    result[kind] = {entity_id: deepcopy(data[kind][entity_id]) for entity_id in profile[kind]}
  for model in result["models"].values():
    if model["provider"] not in result["providers"]:
      raise ConfigError("reference", ("models", "<key>", "provider"))
  if any(model_id not in result["models"] for model_id in profile["roles"].values()):
    raise ConfigError("reference", ("profile", "roles", "<key>"))
  return result


def _selected_provenance(data: dict, sources: Provenance) -> Provenance:
  result = {}

  def visit(value, path):
    if isinstance(value, dict) and value:
      for key, child in value.items():
        visit(child, path + (key,))
    else:
      if len(path) == 1 and path[0] in _SELECTIONS:
        source = sources[("profile", path[0])]
      else:
        source = sources.get(path)
      if source is not None:
        result[path] = source

  visit(data, ())
  return Provenance(result)


def resolve_config(catalog: Catalog, local: LocalConfig, *, profile_id: str | None = None,
                   request_overrides: dict | None = None, adapter_schemas: AdapterSchemas) -> ResolvedConfig:
  """校验全部 profile，返回单一选择；不写文件，不接收 SecretStore 或运行请求参数。"""
  if request_overrides is not None and (not isinstance(request_overrides, dict) or request_overrides):
    raise ConfigError("request")
  if not isinstance(catalog, Catalog) or not isinstance(local, LocalConfig) or "secrets" in local.data:
    raise ConfigError("schema", ("local",))
  context = AdapterSchemas(dict(adapter_schemas.bundles), {
    key: value.get("agent") for key, value in catalog.profiles.items()})
  validate_document("local", local.data, adapter_schemas=context)
  overrides = local.data.get("overrides", {})
  if set(overrides.get("profiles", {})) - set(catalog.profiles):
    raise ConfigError("reference", ("local", "overrides", "profiles", "<key>"))
  if ("default_profile" in local.data["machine"]
      and local.data["machine"]["default_profile"] not in catalog.profiles):
    raise ConfigError("reference", ("machine", "default_profile"))
  selected_id = profile_id if profile_id is not None else local.data["machine"].get("default_profile", "dsh-default")
  if not isinstance(selected_id, str) or selected_id not in catalog.profiles:
    raise ConfigError("reference", ("profile",))

  registry_layers = [("registry", catalog.registry), ("local", {
    key: overrides[key] for key in ("providers", "models", "mcp") if key in overrides})]
  registry = merge_layers(registry_layers).data
  validate_document("registry", {"schema_version": 1, **registry})
  for model in registry["models"].values():
    if model["provider"] not in registry["providers"]:
      raise ConfigError("reference", ("models", "<key>", "provider"))
  for kind, name in (("providers", "base_url"), ("mcp", "url")):
    for entity in registry[kind].values():
      if name in entity and _credential_url(entity[name]):
        raise ConfigError("credential-channel", (kind, "<key>", name))

  policies = {}
  credentials = set()
  for key, profile in catalog.profiles.items():
    validate_document("profile", profile, adapter_schemas=context, partial_options=True)
    bundle = _bundle(context, profile.get("agent"))
    documents = catalog.adapter_documents.get(profile["agent"])
    if not isinstance(documents, dict) or set(documents) != {"agent", "bindings", "plugins"}:
      raise ConfigError("adapter", ("adapter",))
    for kind, document in documents.items():
      validate_document(kind, document, adapter_schemas=context, adapter_id=profile["agent"])
    policy = _adapter_policy(bundle, documents, context, key)
    policies[key] = policy
    credentials.update(policy.credential_targets)
  machine_defaults, machine = _machine_layers(local.data["machine"], credentials)

  selected = None
  for key, profile in catalog.profiles.items():
    bundle = _bundle(context, profile["agent"])
    policy = policies[key]
    defaults = {kind: [] for kind in _SELECTIONS}
    defaults.update(roles={}, agent_options={})
    profile_layers = [("defaults", defaults), ("defaults", policy.defaults), ("profile", profile),
                      ("local", overrides.get("profiles", {}).get(key, {}))]
    merged_profile = merge_layers(profile_layers).data
    # 必须调用原始完整 schema；partial 投影丢掉的逻辑/完整性谓词在此执行。
    validate_document("profile", merged_profile, adapter_schemas=context)
    if merged_profile["id"] != key:
      raise ConfigError("reference", ("profile", "id"))
    combined = merge_layers([
      registry_layers[0],
      ("registry", {"plugins": policy.plugins, "adapter_documents": catalog.adapter_documents[profile["agent"]]}),
      ("defaults", {"machine": machine_defaults}),
      *((layer, {"profile": value}) for layer, value in profile_layers),
      registry_layers[1], ("local", {"machine": machine}),
    ])
    data = _selected(combined.data, merged_profile)
    _callback(bundle.validate, "resolved", data)
    _authentication(bundle, data)
    if key == selected_id:
      selected = ResolvedConfig(data, _selected_provenance(data, combined.provenance), len(catalog.profiles))
  return selected


def public_diagnostics(resolved: ResolvedConfig) -> tuple[tuple[tuple[str, ...], str], ...]:
  """只显示位置及公开层名；动态 ID、原生选项键与原始来源树不公开。"""
  locations = set()
  for path, layer in resolved.provenance.items():
    root, *parts = path
    if root in _SELECTIONS:
      parts = ["<key>", *parts[1:]] if parts else []
      if root == "plugins":
        parts = ["<key>"] + ["<field>"] * max(0, len(parts) - 1) if parts else []
    elif root == "adapter_documents":
      parts = ["<field>"] * len(parts)
    elif root == "profile" and parts:
      if parts[0] == "roles":
        parts = ["roles"] + ["<key>"] * (len(parts) - 1)
      elif parts[0] == "agent_options":
        parts = ["agent_options"] + ["<field>"] * (len(parts) - 1)
    elif root == "machine" and parts[:2] == ["environment", "values"]:
      parts = parts[:2] + ["<key>"] * (len(parts) - 2)
    locations.add(((root, *parts), layer))
  return tuple(sorted(locations))
