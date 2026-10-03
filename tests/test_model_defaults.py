"""公共模型默认值：纯解析、优先级、原生渲染与无凭据启动边界。"""

from copy import deepcopy
from pathlib import Path

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.config import (AdapterSources, LocalConfig, SourceInputs, load_sources,
                             resolve_config)
from agentcfg.dsh import DshAdapter
from agentcfg.model_defaults import model_default_selection, validate_model_defaults
from agentcfg.omp import OmpAdapter
from agentcfg.pi import PiAdapter
from agentcfg.schema import AdapterSchemas, ConfigError
from agentcfg.workspace import load_workspace


REPO = Path(__file__).resolve().parents[1]


def local_file(tmp_path, extra=""):
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  path = private / "local.toml"
  path.write_text('schema_version = 1\n[machine]\nid = "defaults-test"\n' + extra)
  path.chmod(0o600)
  return path


def catalog():
  adapters = {"dsh": DshAdapter(REPO), "pi": PiAdapter(REPO), "omp": OmpAdapter(REPO)}
  schemas = AdapterSchemas({name: adapter.schemas().bundles[name]
                            for name, adapter in adapters.items()})
  registries = tuple(sorted((REPO / "shared").glob("*.toml")))
  for name in adapters:
    content = REPO / "agents" / name / "content.toml"
    if content.exists():
      registries += (content,)
  sources = SourceInputs(registries, tuple(sorted((REPO / "profiles").glob("*.toml"))), {
    name: AdapterSources(*(REPO / "agents" / name / f"{kind}.toml"
      for kind in ("agent", "bindings", "plugins"))) for name in adapters},
    REPO / "shared/defaults/models.toml")
  return load_sources(sources, adapter_schemas=schemas)


def test_defaults_schema_is_closed_and_accessor_returns_copy():
  document = {
    "schema_version": 1,
    "adapters": {name: {"providers": [f"{name}-provider"], "models": [f"{name}-model"],
                        "roles": {"main": f"{name}-model"}}
                 for name in ("dsh", "pi", "omp")},
  }
  validate_model_defaults(document)
  selected = model_default_selection(document, "dsh")
  selected["models"].append("changed")
  assert document["adapters"]["dsh"]["models"] == ["dsh-model"]
  invalid = deepcopy(document)
  invalid["adapters"]["dsh"]["unknown"] = True
  with pytest.raises(ConfigError) as error:
    validate_model_defaults(invalid)
  assert error.value.code == "schema"


def test_explicit_defaults_source_must_exist(tmp_path):
  with pytest.raises(ConfigError) as error:
    load_sources(SourceInputs(model_defaults=tmp_path / "missing.toml"),
                 adapter_schemas=AdapterSchemas())
  assert error.value.code == "read"


def test_defaults_apply_to_future_profile_and_profile_local_roles_win():
  loaded = catalog()
  future = deepcopy(loaded.profiles["dsh-default"])
  future["id"] = "dsh-future"
  future["providers"] = ["glm_openai", "deepseek_openai"]
  future["models"] = ["glm_53_openai", "deepseek_flash_openai"]
  future["roles"] = {"main": "glm_53_openai"}
  profiles = {**loaded.profiles, "dsh-future": future}
  context = AdapterSchemas(dict(loaded.adapter_schemas.bundles),
    {**loaded.adapter_schemas.profile_agents, "dsh-future": "dsh"})
  loaded = type(loaded)(loaded.registry, profiles, loaded.adapter_documents, context,
                        loaded.model_defaults)
  local = LocalConfig({"schema_version": 1, "machine": {"id": "fixture"}, "overrides": {
    "profiles": {"dsh-future": {"roles": {"main": "kimi_k3_openai"},
                                  "models": ["kimi_k3_openai", "glm_53_openai"],
                                  "providers": ["kimi_openai", "glm_openai"]}}}})
  resolved = resolve_config(loaded, local, profile_id="dsh-future",
                            adapter_schemas=context)
  profile = resolved.data["profile"]
  assert profile["providers"] == ["deepseek_openai", "kimi_openai", "glm_openai", "codex", "cursor"]
  assert profile["models"] == ["deepseek_flash_openai", "kimi_k3_openai", "glm_53_openai"]
  assert profile["roles"]["main"] == "kimi_k3_openai"
  assert resolved.provenance[("profile", "providers")] == "local"
  assert resolved.provenance[("profile", "models")] == "local"


def test_synthetic_catalog_without_global_defaults_keeps_empty_local_selection_provenance():
  loaded = catalog()
  loaded = type(loaded)(loaded.registry, loaded.profiles, loaded.adapter_documents,
                        loaded.adapter_schemas)
  local = LocalConfig({"schema_version": 1, "machine": {"id": "fixture"}, "overrides": {
    "profiles": {"dsh-default": {"providers": [], "models": []}}}})
  resolved = resolve_config(loaded, local, profile_id="dsh-default",
                            adapter_schemas=loaded.adapter_schemas)
  assert resolved.data["profile"]["providers"] == []
  assert resolved.data["profile"]["models"] == []
  assert resolved.provenance[("profile", "providers")] == "local"
  assert resolved.provenance[("profile", "models")] == "local"


@pytest.mark.parametrize("profile,protocol,model", [
  ("dsh-default", "openai-compatible", "deepseek_flash_openai"),
  ("pi-default", "openai-compatible", "deepseek_flash_openai"),
  ("omp-default", "anthropic-messages", "deepseek_flash_anthropic"),
])
def test_each_adapter_resolves_and_renders_defaults_without_keys(tmp_path, profile, protocol, model):
  workspace = load_workspace(local_file(tmp_path), profile, repository=REPO)
  data = workspace.resolved.data
  assert data["profile"]["roles"]["main"] == model
  assert data["providers"][data["models"][model]["provider"]]["protocol"] == protocol
  assert workspace.default_models == tuple(
    model_default_selection(catalog().model_defaults, workspace.agent)["models"])
  for provider in data["providers"].values():
    if provider["auth_kind"] == "api-key":
      assert workspace.secret_store.resolve(SecretRef(provider["credential_ref"]), required=False) is None
  artifacts = workspace.adapter.render(data)
  assert artifacts
  assert any(data["models"][model]["remote_id"].encode() in artifact.content
             for artifact in artifacts)
  spec = workspace.adapter.launch_spec(data, cwd=tmp_path.absolute(),
    runtime_root=(tmp_path / "runtime").absolute(), instance_root=workspace.instance,
    lock_identity="a" * 64)
  optional = [binding for binding in spec.environment
              if isinstance(binding.value, SecretRef) and not binding.required]
  assert len(optional) == 3


def test_pi_default_fills_selected_resource_roles_from_main(tmp_path):
  workspace = load_workspace(local_file(tmp_path), "pi-default", repository=REPO)
  roles = workspace.resolved.data["profile"]["roles"]
  assert roles == {"main": "deepseek_flash_openai", "reviewer": "deepseek_flash_openai",
                   "scout": "deepseek_flash_openai"}
  workspace.adapter.validate_selected(workspace.resolved.data)


def test_omp_kernel_keeps_profile_roles_and_adds_global_catalog(tmp_path):
  workspace = load_workspace(local_file(tmp_path), "omp-kernel", repository=REPO,
    proposal={"local_values": {"tf_openai_url": "https://tf-gateway.example.invalid/v1",
      "tf_anthropic_url": "https://tf-gateway.example.invalid/anthropic"}})
  profile = workspace.resolved.data["profile"]
  assert profile["roles"]["main"] == "omp-kimi_tf-kimi-for-coding"
  assert profile["roles"]["smol"] == "omp-zhipu_tf-glm-5.3-flash"
  assert profile["providers"][:3] == ["deepseek_anthropic", "kimi_anthropic", "glm_anthropic"]
