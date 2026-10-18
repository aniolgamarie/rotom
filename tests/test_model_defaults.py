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
  future["providers"] = ["glm_coding_openai", "deepseek_openai"]
  future["models"] = ["glm_coding_53_openai", "deepseek_flash_openai"]
  future["roles"] = {"main": "glm_coding_53_openai"}
  profiles = {**loaded.profiles, "dsh-future": future}
  context = AdapterSchemas(dict(loaded.adapter_schemas.bundles),
    {**loaded.adapter_schemas.profile_agents, "dsh-future": "dsh"})
  loaded = type(loaded)(loaded.registry, profiles, loaded.adapter_documents, context,
                        loaded.model_defaults)
  local = LocalConfig({"schema_version": 1, "machine": {"id": "fixture"}, "overrides": {
    "profiles": {"dsh-future": {"roles": {"main": "glm_coding_53_openai"},
                                  "models": ["kimi_code_openai", "glm_coding_53_openai"],
                                  "providers": ["kimi_code_openai", "glm_coding_openai"]}}}})
  resolved = resolve_config(loaded, local, profile_id="dsh-future",
                            adapter_schemas=context)
  profile = resolved.data["profile"]
  # 本例重设了 future 配方自身的 providers；OAuth 不再从 adapter 默认层追加。
  assert profile["providers"] == ["kimi_code_openai", "glm_coding_openai", "deepseek_openai"]
  assert profile["models"] == ["kimi_code_openai", "kimi_code_k3_openai", "kimi_code_k3_256k_openai", "kimi_code_highspeed_openai",
    "glm_coding_53_openai", "glm_coding_53_flash_openai", "deepseek_flash_openai", "deepseek_pro_openai"]
  assert profile["roles"]["main"] == "glm_coding_53_openai"
  assert resolved.provenance[("profile", "providers")] == "local"
  assert resolved.provenance[("profile", "models")] == "local"


@pytest.mark.parametrize("profile_id, selection, oauth", [
  ("dsh-default", None, ["codex", "cursor"]),
  ("dsh-future", None, ["codex", "cursor"]),
  ("dsh-future", [], []),
  ("dsh-future", ["codex", "cursor"], ["codex", "cursor"]),
  ("dsh-future", ["cursor"], ["cursor"]),
])
def test_oauth_providers_remain_explicit_profile_choices(profile_id, selection, oauth):
  loaded = catalog()
  profiles = deepcopy(loaded.profiles)
  profile = deepcopy(profiles["dsh-default"])
  profile["id"] = profile_id
  # None 保留复制配方的显式选择；空列表才移除该配方层的 OAuth 选择。
  if selection is not None:
    profile["providers"] = selection
  profiles[profile_id] = profile
  context = AdapterSchemas(dict(loaded.adapter_schemas.bundles),
    {**loaded.adapter_schemas.profile_agents, profile_id: "dsh"})
  loaded = type(loaded)(loaded.registry, profiles, loaded.adapter_documents, context,
                        loaded.model_defaults)
  # 局部 API-only 列表仍按层追加，不会删除配方显式选中的 OAuth。
  local = LocalConfig({"schema_version": 1, "machine": {"id": "fixture"}, "overrides": {
    "profiles": {profile_id: {"providers": ["kimi_code_openai"]}}}})
  resolved = resolve_config(loaded, local, profile_id=profile_id, adapter_schemas=context)
  expected = ["kimi_code_openai", "glm_coding_openai", "deepseek_openai", *oauth]
  assert resolved.data["profile"]["providers"] == expected
  assert set(resolved.data["providers"]) == set(expected)


def test_synthetic_catalog_without_global_defaults_keeps_empty_local_selection_provenance():
  loaded = catalog()
  # 本例只声明 DSH；生产 OMP bootstrap 依赖公共默认模型池。
  loaded = type(loaded)(loaded.registry, {"dsh-default": loaded.profiles["dsh-default"]},
                        loaded.adapter_documents, loaded.adapter_schemas)
  local = LocalConfig({"schema_version": 1, "machine": {"id": "fixture"}, "overrides": {
    "profiles": {"dsh-default": {"providers": [], "models": []}}}})
  resolved = resolve_config(loaded, local, profile_id="dsh-default",
                            adapter_schemas=loaded.adapter_schemas)
  assert resolved.data["profile"]["providers"] == []
  assert resolved.data["profile"]["models"] == []
  assert resolved.provenance[("profile", "providers")] == "local"
  assert resolved.provenance[("profile", "models")] == "local"


@pytest.mark.parametrize("profile,protocol,model", [
  ("dsh-default", "openai-compatible", "kimi_code_openai"),
  ("pi-default", "openai-compatible", "kimi_code_openai"),
  ("omp-default", "anthropic-messages", "kimi_code_anthropic"),
])
def test_each_adapter_resolves_and_renders_defaults_without_keys(tmp_path, profile, protocol, model):
  workspace = load_workspace(local_file(tmp_path), profile, repository=REPO)
  data = workspace.resolved.data
  assert data["profile"]["roles"]["main"] == model
  suffix = "anthropic" if workspace.agent == "omp" else "openai"
  assert set(workspace.default_providers) == {"kimi_code_" + suffix, "glm_coding_" + suffix, "deepseek_" + suffix}
  assert {data["models"][mid]["remote_id"] for mid in workspace.default_models} == {
    "kimi-for-coding", "k3", "k3-256k", "kimi-for-coding-highspeed",
    "glm-5.3", "glm-5.3-flash", "deepseek-flash", "deepseek-v4-pro"}
  assert all("pricing" not in data["models"][mid] for mid in workspace.default_models if not mid.startswith("deepseek"))
  assert data["providers"][data["models"][model]["provider"]]["protocol"] == protocol
  assert workspace.default_models == tuple(
    model_default_selection(catalog().model_defaults, workspace.agent)["models"])
  for provider in data["providers"].values():
    if provider["auth_kind"] == "api-key":
      assert workspace.secret_store.resolve(SecretRef(provider["credential_ref"]), required=False) is None
  artifacts = workspace.adapter.render(data)
  expected_urls = {
    "openai": {"kimi_code": "https://api.kimi.com/coding/v1",
      "glm_coding": "https://open.bigmodel.cn/api/coding/paas/v4"},
    "anthropic": {"kimi_code": "https://api.kimi.com/coding/",
      "glm_coding": "https://open.bigmodel.cn/api/anthropic"},
  }[suffix]
  for stem, url in expected_urls.items():
    provider = data["providers"][stem + "_" + suffix]
    assert provider["base_url"] == url
    assert provider["credential_ref"] == "secret:" + stem + "_key"
    assert any(url.encode() in artifact.content for artifact in artifacts)
  assert artifacts
  assert any(data["models"][model]["remote_id"].encode() in artifact.content
             for artifact in artifacts)
  spec = workspace.adapter.launch_spec(data, cwd=tmp_path.absolute(),
    runtime_root=(tmp_path / "runtime").absolute(), instance_root=workspace.instance,
    lock_identity="a" * 64)
  optional = [binding for binding in spec.environment
              if isinstance(binding.value, SecretRef) and not binding.required]
  assert {binding.value.reference for binding in optional} == {"secret:kimi_code_key", "secret:glm_coding_key", "secret:deepseek_key"}


def test_pi_default_fills_selected_resource_roles_from_main(tmp_path):
  workspace = load_workspace(local_file(tmp_path), "pi-default", repository=REPO)
  roles = workspace.resolved.data["profile"]["roles"]
  assert roles == {"main": "kimi_code_openai", "reviewer": "kimi_code_openai",
                   "scout": "kimi_code_openai"}
  workspace.adapter.validate_selected(workspace.resolved.data)


@pytest.mark.parametrize("profile", ["pi-codex", "pi-cursor"])
def test_unbound_pi_profile_inherits_subscription_main(tmp_path, profile):
  workspace = load_workspace(local_file(tmp_path), profile, repository=REPO)
  assert workspace.resolved.data["profile"]["roles"]["main"] == "kimi_code_openai"


def test_pi_managed_still_requires_explicit_project_checks(tmp_path):
  # 订阅默认不解除 managed 配方已有的项目和检查绑定要求。
  with pytest.raises(ConfigError):
    load_workspace(local_file(tmp_path), "pi-managed", repository=REPO)


def test_explicit_cursor_model_binding_wins_over_subscription_default(tmp_path):
  workspace = load_workspace(local_file(tmp_path, '''
[overrides.models.fixture_cursor]
provider = "cursor"
remote_id = "fixture-cursor"
input = ["text"]
[overrides.profiles.pi-cursor]
models = ["fixture_cursor"]
[overrides.profiles.pi-cursor.roles]
main = "fixture_cursor"
'''), "pi-cursor", repository=REPO)
  assert workspace.resolved.data["profile"]["roles"]["main"] == "fixture_cursor"
  workspace.adapter.validate_selected(workspace.resolved.data)
  assert workspace.adapter.render(workspace.resolved.data)


def test_omp_kernel_keeps_profile_roles_and_adds_global_catalog(tmp_path):
  workspace = load_workspace(local_file(tmp_path), "omp-kernel", repository=REPO,
    proposal={"local_values": {"tf_openai_url": "https://tf-gateway.example.invalid/v1",
      "tf_anthropic_url": "https://tf-gateway.example.invalid/anthropic"}})
  profile = workspace.resolved.data["profile"]
  assert profile["roles"]["main"] == "omp-kimi_tf-kimi-for-coding"
  assert profile["roles"]["smol"] == "omp-zhipu_tf-glm-5.3-flash"
  assert profile["providers"][:2] == ["kimi_code_anthropic", "glm_coding_anthropic"]


@pytest.mark.parametrize("profile", ["dsh-default", "pi-default", "omp-default"])
def test_subscription_defaults_do_not_reuse_legacy_keys(tmp_path, profile):
  workspace = load_workspace(local_file(tmp_path, '\n[secrets]\nkimi_key = "OLD-KIMI-CANARY"\nglm_key = "OLD-GLM-CANARY"\n'),
    profile, repository=REPO)
  for name in ("kimi_code_key", "glm_coding_key"):
    assert workspace.secret_store.resolve(SecretRef("secret:" + name), required=False) is None
  artifacts = workspace.adapter.render(workspace.resolved.data)
  assert all(b"OLD-KIMI-CANARY" not in item.content and b"OLD-GLM-CANARY" not in item.content for item in artifacts)


def test_pi_subscription_models_render_explicit_wire_compatibility(tmp_path):
  import json
  workspace = load_workspace(local_file(tmp_path), "pi-default", repository=REPO)
  artifacts = workspace.adapter.render(workspace.resolved.data)
  groups = [json.loads(artifact.content) for artifact in artifacts
    if artifact.target.path == "pi-home/models.json" and artifact.target.selector.endswith("/models")]
  models = {model["id"]: model for group in groups for model in group}
  assert set(models) == {"kimi-for-coding", "k3", "k3-256k", "kimi-for-coding-highspeed",
    "glm-5.3", "glm-5.3-flash", "deepseek-flash", "deepseek-v4-pro"}
  for model_id in ("kimi-for-coding", "glm-5.3", "glm-5.3-flash"):
    assert models[model_id]["compat"] == {
      "supportsDeveloperRole": False,
      "supportsReasoningEffort": True,
      "maxTokensField": "max_tokens",
      "thinkingFormat": "zai",
      "supportsStrictMode": False,
    }
    expected_levels = {"minimal": "low", "low": "low", "medium": "high", "high": "high", "xhigh": "max", "max": "max"}
    if model_id.startswith("glm"):
      expected_levels["off"] = None
    assert models[model_id]["thinkingLevelMap"] == expected_levels


@pytest.mark.parametrize("native", [
  {"compat": {"supportsDevelopRole": False}},
  {"compat": {"supportsStrictModes": False}},
  {"compat": {"maxTokensField": "max_completion_tokens"}},
  {"compat": {"thinkingFormat": "za"}},
  {"compat": {"reasoningEffortMap": {"low": "low"}}},
  {"thinkingLevelMaps": {"low": "low"}},
  {"thinkingLevelMap": {"hig": "high"}},
  {"thinkingLevelMap": {"off": "low"}},
  {"thinkingLevelMap": {"high": "hig"}},
])
def test_pi_subscription_native_schema_rejects_unknown_fields_and_levels(native):
  from agentcfg.schema import validate_document
  document = {"schema_version": 1, "models": {"model": {
    "provider": "provider", "remote_id": "model", "input": ["text"], "native": {"pi": native}}}}
  with pytest.raises(ConfigError) as error:
    validate_document("registry", document)
  assert error.value.code == "schema"


def test_public_pool_removes_obsolete_routes_and_keeps_deepseek_specifications():
  loaded = catalog()
  assert {"kimi_openai", "kimi_anthropic", "glm_openai", "glm_anthropic"}.isdisjoint(loaded.registry["providers"])
  assert {"kimi_k3_openai", "kimi_k3_anthropic", "glm_53_openai", "glm_53_anthropic"}.isdisjoint(loaded.registry["models"])
  expected_map = {"minimal": "low", "low": "low", "medium": "high", "high": "high", "xhigh": "high", "max": "max"}
  for suffix in ("openai", "anthropic"):
    model = loaded.registry["models"]["deepseek_flash_" + suffix]
    assert model["context_window"] == 1048576
    assert model["max_output_tokens"] == 393216
    assert model["input"] == ["text", "image"]
    assert model["reasoning_efforts"] == ["low", "high", "max"]
    assert model["source"] == "https://api-docs.deepseek.com/api/list-models/"
    assert model["pricing"]["checked_on"] == "2026-10-06"
  native = loaded.registry["models"]["deepseek_flash_openai"]["native"]
  assert native["pi"]["thinkingLevelMap"] == expected_map
  assert "reasoningEffortMap" not in native["pi"]["compat"]
  assert native["pi"]["compat"]["requiresReasoningContentOnAssistantMessages"] is True
  assert native["omp"]["thinking"] == {"minLevel": "low", "maxLevel": "max", "mode": "effort"}
  assert native["omp"]["compat"]["reasoningEffortMap"] == expected_map
  assert native["omp"]["compat"]["extraBody"] == {"thinking": {"type": "enabled"}}


def test_glm_mandatory_reasoning_controls_render_as_public_sdk_metadata(tmp_path):
  import json
  workspace = load_workspace(local_file(tmp_path), "pi-default", repository=REPO)
  artifacts = workspace.adapter.render(workspace.resolved.data)
  groups = [json.loads(artifact.content) for artifact in artifacts
    if artifact.target.path == "pi-home/models.json" and artifact.target.selector.endswith("/models")]
  models = {model["id"]: model for group in groups for model in group}
  for remote in ("glm-5.3", "glm-5.3-flash"):
    assert models[remote]["thinkingLevelMap"]["off"] is None
    assert "disabled_thinking_levels" not in models[remote]
  registry = catalog().registry
  for model in registry["models"].values():
    if model["remote_id"] in ("glm-5.3", "glm-5.3-flash"):
      if "omp" in model["native"]:
        assert model["native"]["omp"]["thinking"] == {
          "minLevel": "low", "maxLevel": "max", "mode": "effort", "requiresEffort": True}
      if "dsh" in model["native"]:
        assert model["native"]["dsh"]["compat"]["forceAdaptiveThinking"] is True


def test_deepseek_tf_reuses_url_but_requires_its_independent_key(tmp_path):
  workspace = load_workspace(local_file(tmp_path, '\n[secrets]\ndeepseek_key = "OFFICIAL-KEY-CANARY"\n'),
    "omp-kernel", repository=REPO, proposal={"local_values": {
      "tf_openai_url": "https://gateway.example.invalid/v1", "tf_anthropic_url": "https://gateway.example.invalid/anthropic"}})
  data = workspace.resolved.data
  assert data["providers"]["deepseek_tf"]["base_url"] == data["providers"]["kimi_tf"]["base_url"]
  assert workspace.secret_store.resolve(SecretRef("secret:omp_deepseek_tf_key"), required=False) is None
  assert data["profile"]["roles"]["main"] == "omp-kimi_tf-kimi-for-coding"
  assert data["profile"]["agent_options"]["permission_control"]["remote_fallback_model"] == "omp-kimi_tf-kimi-for-coding"
  lock = workspace.backend.read_lock(workspace.repository)
  assert all(b"OFFICIAL-KEY-CANARY" not in artifact.content for artifact in workspace.candidate(lock.identity).artifacts)
