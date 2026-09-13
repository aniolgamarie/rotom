"""从管理仓库显式构建当前选中配置；不改 cwd，不读取其他工具账号。"""

from dataclasses import dataclass, field
from pathlib import Path

from .config import AdapterSources, SourceInputs, load_local, load_sources, resolve_config
from .dsh import DshAdapter
from .paths import safe_id
from .render import render_candidate
from .schema import AdapterSchemas


ADAPTER_TYPES = {"dsh": DshAdapter}


@dataclass
class Workspace:
  repository: Path
  local_path: Path = field(repr=False)
  resolved: object = field(repr=False)
  adapter: object = field(repr=False)
  schemas: object = field(repr=False)
  secret_store: object = field(repr=False)

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
    scopes = [target.path for target in self.adapter.managed_targets(self.resolved.data)
              if target.serialization == "skill-directory"]
    skills = {"skill_root": self.repository, "skill_target_root": scopes[0]} if len(scopes) == 1 else {}
    return render_candidate(self.resolved, adapter=self.adapter, adapter_schemas=self.schemas,
      lock_identity=lock_identity, **skills)


def load_workspace(local, profile=None, *, repository=None):
  repository = repository or Path(__file__).resolve().parents[2]
  adapters = {name: kind(repository) for name, kind in ADAPTER_TYPES.items()}
  schemas = AdapterSchemas({name: adapter.schemas().bundles[name] for name, adapter in adapters.items()})
  registries = tuple(sorted((repository / "shared").glob("*.toml")))
  for name in adapters:
    specific = repository / "agents" / name / "content.toml"
    if specific.exists():
      registries += (specific,)
  sources = SourceInputs(registries, tuple(sorted((repository / "profiles").glob("*.toml"))),
    {name: AdapterSources(*(repository / "agents" / name / (kind + ".toml") for kind in ("agent", "bindings", "plugins"))) for name in adapters})
  catalog = load_sources(sources, adapter_schemas=schemas)
  config, store = load_local(local, adapter_schemas=catalog.adapter_schemas)
  resolved = resolve_config(catalog, config, profile_id=profile, adapter_schemas=catalog.adapter_schemas)
  safe_id(resolved.data["profile"]["id"])
  return Workspace(repository, local.absolute(), resolved, adapters[resolved.data["profile"]["agent"]], catalog.adapter_schemas, store)
