"""从管理仓库显式构建当前选中配置；不改 cwd，不读取其他工具账号。"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat

from .config import AdapterSources, SourceInputs, LocalConfig, load_local, load_sources, resolve_config
from .dsh import DshAdapter
from .pi import PiAdapter
from .omp import OmpAdapter
from .model_defaults import model_default_selection
from .paths import PathError, safe_id, trusted_source_directory
from .render import render_candidate
from .schema import AdapterSchemas, ConfigError, validate_profile_sources
from .storage import Conflict, identity


ADAPTER_TYPES = {"dsh": DshAdapter, "pi": PiAdapter, "omp": OmpAdapter}


def load_public_catalog(*, repository=None):
  """只加载仓库公开声明；初始化可据此推导引用而不触碰私人秘密。"""
  repository = repository or Path(__file__).resolve().parents[2]
  adapters = {name: kind(repository) for name, kind in ADAPTER_TYPES.items()}
  schemas = AdapterSchemas({name: adapter.schemas().bundles[name] for name, adapter in adapters.items()})
  registries = tuple(sorted((repository / "shared").glob("*.toml")))
  for name in adapters:
    specific = repository / "agents" / name / "content.toml"
    if specific.exists():
      registries += (specific,)
  defaults_path = repository / "shared" / "defaults" / "models.toml"
  sources = SourceInputs(registries, tuple(sorted((repository / "profiles").glob("*.toml"))),
    {name: AdapterSources(*(repository / "agents" / name / (kind + ".toml")
      for kind in ("agent", "bindings", "plugins"))) for name in adapters}, defaults_path)
  return load_sources(sources, adapter_schemas=schemas), adapters


@dataclass
class Workspace:
  repository: Path
  local_path: Path = field(repr=False)
  resolved: object = field(repr=False)
  adapter: object = field(repr=False)
  schemas: object = field(repr=False)
  secret_store: object = field(repr=False)
  global_model_defaults: dict = field(default_factory=dict, repr=False)

  @property
  def default_providers(self):
    return tuple(self.global_model_defaults.get("providers", ()))

  @property
  def default_models(self):
    return tuple(self.global_model_defaults.get("models", ()))

  @property
  def backend(self):
    return self.adapter.dependency_backend()

  @property
  def profile(self):
    return self.resolved.data["profile"]["id"]

  @property
  def agent(self):
    return self.resolved.data["profile"]["agent"]

  @property
  def instance(self):
    return Path(self.resolved.data["machine"]["paths"]["instances_root"]) / self.agent / self.profile

  @property
  def state_root(self):
    return Path(self.resolved.data["machine"]["paths"]["state_root"]) / self.agent / self.profile

  @property
  def cache(self):
    return Path(self.resolved.data["machine"]["paths"]["cache_root"]) / self.agent / self.profile

  @property
  def binding(self):
    return {"machine": self.resolved.data["machine"]["id"], "local": str(self.local_path), "profile": self.profile}

  def candidate(self, lock_identity):
    if self.resolved.missing_local_values:
      raise ValueError("本地 URL 尚未配置")
    scopes = [target.path for target in self.adapter.managed_targets(self.resolved.data)
              if target.serialization == "skill-directory"]
    skills = {"skill_root": self.repository, "skill_target_root": scopes[0]} if len(scopes) == 1 else {}
    context = None
    required = self.adapter.requires_render_context or getattr(self.adapter, "render_context_required", lambda data: False)(self.resolved.data)
    if required:
      from .adapter import RenderContext
      from .runtime import runtime_identity
      lock = self.backend.read_lock(self.repository)
      if lock.identity != lock_identity:
        raise ValueError("候选锁身份与仓库锁不一致")
      identity = runtime_identity(self, lock)
      context = RenderContext(lock.identity, self.backend.root(self, identity))
    return render_candidate(self.resolved, adapter=self.adapter, adapter_schemas=self.schemas,
      lock_identity=lock_identity, context=context, **skills)


def load_workspace(local, profile=None, *, repository=None, proposal=None,
                   allow_missing_local_values=False):
  repository = repository or Path(__file__).resolve().parents[2]
  catalog, adapters = load_public_catalog(repository=repository)
  config, store = load_local(local, adapter_schemas=catalog.adapter_schemas,
    load_credentials=False)
  if proposal is not None:
    from .merge import merge_layers
    from .schema import validate_document
    config = LocalConfig(merge_layers((("local", config.data), ("request", proposal))).data)
    validate_document("local", config.data, adapter_schemas=catalog.adapter_schemas)
  return _resolved_workspace(repository, local, catalog, adapters, config, store, profile,
    allow_missing_local_values=allow_missing_local_values)


@dataclass(frozen=True)
class InstanceWorkspace:
  """只含实例观察所需归属；不能作为启动、渲染或维护工作区使用。"""
  agent: str
  profile: str
  local_path: Path = field(repr=False)
  machine_id: str = field(repr=False)
  instance: Path = field(repr=False)
  state_root: Path = field(repr=False)
  global_state_root: str | Path | None = field(default=None, repr=False)
  cache: Path | None = field(default=None, repr=False)

  @property
  def binding(self):
    return {"machine": self.machine_id, "local": str(self.local_path), "profile": self.profile}


def _public_profile_sources(repository):
  from .config import _parse_toml
  documents = []
  try:
    with trusted_source_directory(repository / "profiles") as parent:
      for name in sorted(os.listdir(parent)):
        if not name.endswith(".toml"):
          continue
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
          before = os.fstat(stream.fileno())
          if (not stat.S_ISREG(before.st_mode) or before.st_uid not in (0, os.geteuid())
              or before.st_nlink != 1 or before.st_mode & 0o022):
            raise Conflict("公开配方来源不安全")
          content = stream.read()
          after = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if identity(before) != identity(after) or identity(before) != identity(current):
          raise Conflict("公开配方来源在读取期间变化")
        document = _parse_toml(content, ("profile", str(len(documents) + 1)))
        try:
          json.dumps(document, allow_nan=False)
        except (TypeError, ValueError):
          raise ConfigError("schema", ("profile",)) from None
        documents.append((Path(name).stem, document))
  except (OSError, PathError):
    raise Conflict("无法安全读取公开配方来源") from None
  return documents


def load_instance_workspaces(local, profiles, *, repository=None):
  """一次严格读取配方和机器；观察不依赖模型目录或启动就绪解析。"""
  from .config import _machine_layers
  repository = repository or Path(__file__).resolve().parents[2]
  documents = _public_profile_sources(repository)
  agents = {document.get("agent") for _, document in documents if type(document.get("agent")) is str}
  if any(type(document.get("agent")) is not str or document["agent"] not in ADAPTER_TYPES
      for _, document in documents):
    raise ConfigError("adapter-schema", ("profile", "agent"))
  if "pi" in agents:
    try:
      with trusted_source_directory(repository / "agents/pi/schemas") as parent:
        for name in os.listdir(parent):
          if name.endswith(".json"):
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid())
                or info.st_nlink != 1 or info.st_mode & 0o022):
              raise Conflict("公开适配器 schema 来源不安全")
    except (OSError, PathError):
      raise Conflict("无法安全读取公开适配器 schema 来源") from None
  bundles = {agent: ADAPTER_TYPES[agent](repository).schemas().bundles[agent] for agent in sorted(agents)}
  context = AdapterSchemas(bundles)
  validate_profile_sources([document for _, document in documents], adapter_schemas=context)
  available = {}
  for stem, document in documents:
    identifier = safe_id(document["id"])
    if identifier != stem or identifier in available:
      raise ConfigError("reference", ("profile", "id"))
    available[identifier] = document["agent"]
  context = AdapterSchemas(bundles, available)
  config, _ = load_local(local, adapter_schemas=context, load_credentials=False)
  requested = set(profiles) | set(config.data.get("overrides", {}).get("profiles", {}))
  default = config.data["machine"].get("default_profile")
  if default is not None:
    requested.add(default)
  if requested - available.keys():
    raise ConfigError("reference", ("profile",))
  defaults, machine = _machine_layers(config.data["machine"], frozenset())
  paths = {**defaults["paths"], **machine.get("paths", {})}
  return tuple(InstanceWorkspace(available[profile], profile, local.absolute(), machine["id"],
    Path(paths["instances_root"]) / available[profile] / profile,
    Path(paths["state_root"]) / available[profile] / profile,
    global_state_root=paths["state_root"],
    cache=Path(paths["cache_root"]) / available[profile] / profile) for profile in profiles)


def _resolved_workspace(repository, local, catalog, adapters, config, store, profile, *,
    allow_missing_local_values):
  resolved = resolve_config(catalog, config, profile_id=profile,
    adapter_schemas=catalog.adapter_schemas,
    allow_missing_local_values=allow_missing_local_values)
  safe_id(resolved.data["profile"]["id"])
  defaults = model_default_selection(catalog.model_defaults, resolved.data["profile"]["agent"])
  return Workspace(repository, local.absolute(), resolved, adapters[resolved.data["profile"]["agent"]],
    catalog.adapter_schemas, store, defaults)
