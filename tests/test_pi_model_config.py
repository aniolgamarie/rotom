"""模型声明投影只使用部署配置；不读取原生账户或模型环境秘密。"""
from copy import deepcopy
import hashlib
import json

import pytest

from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from test_pi_adapter import ROOT, pi_data


def fixture(tmp_path, profile="pi-base"):
  data = pi_data(tmp_path); data["profile"]["id"] = profile
  if profile in ("pi-base", "pi-full"):
    # 这里只测试虚构模型投影，不从旧fixture继承Full插件或关闭态选项。
    data["profile"]["plugins"], data["plugins"] = [], {}
    data["profile"]["agent_options"].pop("task_keeper")
    if profile == "pi-full":
      # 未发布的合成Full声明仅供模型测试；不表示正式配方、安装或能力已可运行。
      documents = data["adapter_documents"]
      documents["agent"]["profile_defaults"]["pi-full"] = deepcopy(documents["agent"]["profile_defaults"]["pi-base"])
      documents["plugins"]["profile_plugins"]["pi-full"] = deepcopy(documents["plugins"]["profile_plugins"]["pi-base"])
  return data


def rendered(data):
  artifacts = PiAdapter(ROOT).render(data)
  manifest = next(json.loads(item.content) for item in artifacts if item.target.path == "pi-home/agentcfg-manifest.json")
  fields = {item.target.selector.rsplit("/", 1)[-1]: json.loads(item.content) for item in artifacts if item.target.path == "pi-home/models.json"}
  return artifacts, manifest, fields


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_projection_and_native_models_have_the_exact_same_source(tmp_path, profile):
  data = fixture(tmp_path, profile)
  data["models"]["main"].update(name="Fictional", reasoning=False, context_window=12345, max_output_tokens=123,
    native={"pi": {"compat": {"thinkingFormat": "deepseek", "requiresReasoningContentOnAssistantMessages": True, "reasoningEffortMap": {"medium": "high"}}}})
  data["profile"]["agent_options"]["model_settings"] = {"main": {"reasoning": True, "thinking_level_map": {"max": "xhigh"}, "disabled_thinking_levels": ["off"]}}
  artifacts, manifest, fields = rendered(data)
  entry = manifest["model_configuration"]["providers"]["agentcfg-fictional"]
  assert entry == {"logical_id": "fictional", "auth_kind": "api-key", "owner": "pi-environment", "credential_ref": "secret:fixture",
    "config": {key: fields[key] for key in ("api", "baseUrl", "models")}}
  assert entry["config"]["models"] == [{"id": "fictional-chat", "input": ["text"], "name": "Fictional", "reasoning": True,
    "contextWindow": 12345, "maxTokens": 123, "compat": {"thinkingFormat": "deepseek", "requiresReasoningContentOnAssistantMessages": True},
    "thinkingLevelMap": {"medium": "high", "max": "xhigh", "off": None}}]
  assert manifest["model_configuration"]["schema_version"] == 1
  assert entry["owner"] == manifest["provider_bindings"]["agentcfg-fictional"]["owner"]
  token = next(item for item in artifacts if item.target.selector and item.target.selector.endswith("/apiKey"))
  assert token.target.reference_tokens == (fields["apiKey"],)
  assert "apiKey" not in entry["config"]


def test_projection_has_independent_copies_of_inputs_and_other_calls(tmp_path):
  from agentcfg.pi_model_config import model_configuration
  data = fixture(tmp_path); data["models"]["main"]["native"] = {"pi": {"compat": {"thinkingFormat": "deepseek"}}}
  adapter = PiAdapter(ROOT); original = deepcopy(data)
  first = model_configuration(data, adapter.route)
  first["providers"]["agentcfg-fictional"]["config"]["models"][0]["input"].append("image")
  first["providers"]["agentcfg-fictional"]["config"]["models"][0]["compat"]["thinkingFormat"] = "mutated"
  assert data == original
  assert model_configuration(data, adapter.route)["providers"]["agentcfg-fictional"]["config"]["models"][0]["input"] == ["text"]


@pytest.mark.parametrize("mutation", ["api", "endpoint", "compat", "reasoning", "thinking", "credential"])
def test_nonsecret_effective_configuration_changes_projection(tmp_path, mutation):
  data = fixture(tmp_path); before = rendered(data)[1]["model_configuration"]
  if mutation == "api": data["providers"]["fictional"]["protocol"] = "openai-responses"
  if mutation == "endpoint": data["providers"]["fictional"]["base_url"] = "https://other.invalid:8443/v2"
  if mutation == "compat": data["models"]["main"]["native"] = {"pi": {"compat": {"thinkingFormat": "deepseek"}}}
  if mutation == "reasoning": data["profile"]["agent_options"]["model_settings"] = {"main": {"reasoning": True}}
  if mutation == "thinking": data["profile"]["agent_options"]["model_settings"] = {"main": {"thinking_level_map": {"high": "max"}}}
  if mutation == "credential": data["providers"]["fictional"]["credential_ref"] = "secret:different"
  assert rendered(data)[1]["model_configuration"] != before


def test_secret_values_and_environment_contents_do_not_affect_projection(tmp_path, monkeypatch):
  from agentcfg.secrets import SecretStore
  from agentcfg.pi import key_variable
  data = fixture(tmp_path); before = rendered(data)[1]["model_configuration"]
  monkeypatch.setattr(SecretStore, "resolve", lambda *_args, **_kwargs: pytest.fail("secret read"))
  canary = "synthetic-private-model-token"
  monkeypatch.setenv(key_variable("fictional"), canary)
  monkeypatch.setenv("OPENAI_API_KEY", canary)
  after = rendered(data)[1]["model_configuration"]
  assert after == before
  serialized = json.dumps(after)
  assert canary not in serialized and hashlib.sha256(canary.encode()).hexdigest() not in serialized


def test_oauth_projection_records_owner_and_route_without_fabricated_native_configuration(tmp_path):
  data = fixture(tmp_path)
  data["providers"]["codex"] = {"protocol": "oauth-dynamic", "auth_kind": "oauth"}
  data["profile"]["providers"].append("codex")
  data["models"]["oauth"] = {"provider": "codex", "remote_id": "native-dynamic", "input": ["text"]}
  data["profile"]["models"].append("oauth")
  _, manifest, _ = rendered(data)
  projection = manifest["model_configuration"]
  assert set(projection["providers"]) == set(manifest["provider_bindings"])
  assert projection["providers"]["openai-codex"] == {"logical_id": "codex", "auth_kind": "oauth", "owner": "pi-native", "credential_ref": None, "config": None}


@pytest.mark.parametrize("endpoint", ["https://synthetic-secret@host.invalid/v1", "https://host.invalid?", "https://host.invalid#",
  "https://host.invalid/?token=synthetic-secret", "https://host.invalid:99999", "https://host.invalid:wrong", "https:///v1", "//host.invalid/v1", "file:///tmp/token",
  "https://host.invalid\\v1", "https://host.invalid/ white", "https://host.invalid/\nsecret", "https://host.invalid/\0secret", "https://host.invalid/\u0080secret", "$ENV", "!echo synthetic-secret"])
def test_new_projection_refuses_unsafe_endpoint_without_echoing_input(tmp_path, endpoint):
  data = fixture(tmp_path); data["providers"]["fictional"]["base_url"] = endpoint
  with pytest.raises(ConfigError) as error: rendered(data)
  assert error.value.code == "pi-model-config-endpoint"
  assert endpoint not in str(error.value) and "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("native", [{"apiKey": "synthetic-secret"}, {"headers": {"Authorization": "synthetic-secret"}},
  {"compat": {"token": "synthetic-secret"}}])
def test_unknown_native_fields_cannot_enter_manifest_or_error(tmp_path, native):
  data = fixture(tmp_path); data["models"]["main"]["native"] = {"pi": native}
  with pytest.raises(ConfigError) as error: rendered(data)
  assert "synthetic-secret" not in str(error.value)


def test_new_projection_rejects_duplicate_native_routes(tmp_path):
  data = fixture(tmp_path)
  data["providers"]["codex"] = {"protocol": "oauth-dynamic", "auth_kind": "oauth"}
  data["adapter_documents"]["bindings"]["oauth"]["codex"]["route"] = "agentcfg-fictional"
  data["profile"]["providers"].append("codex")
  with pytest.raises(ConfigError): rendered(data)


def test_old_profile_has_no_projection_and_preserves_previous_field_bytes(tmp_path):
  data = fixture(tmp_path, "pi-fixture")
  data["providers"]["fictional"]["base_url"] = "https://user@legacy.invalid/v1?old=permitted"
  artifacts, manifest, fields = rendered(data)
  assert "model_configuration" not in manifest
  assert fields["baseUrl"] == "https://user@legacy.invalid/v1?old=permitted"
  assert fields["models"] == [{"id": "fictional-chat", "input": ["text"]}]
  base = fixture(tmp_path)
  old_fields = {item.target: item.content for item in PiAdapter(ROOT).render(fixture(tmp_path, "pi-fixture")) if item.target.path == "pi-home/models.json"}
  new_fields = {item.target: item.content for item in PiAdapter(ROOT).render(base) if item.target.path == "pi-home/models.json"}
  assert new_fields == old_fields


@pytest.mark.parametrize("target", ["provider", "model", "native", "compat", "settings"])
def test_pure_helper_fixed_allowlist_independently_rejects_future_secret_fields(tmp_path, target):
  from agentcfg.pi_model_config import model_configuration
  data = fixture(tmp_path)
  if target == "provider": data["providers"]["fictional"]["headers"] = {"Authorization": "synthetic-secret"}
  if target == "model": data["models"]["main"]["apiKey"] = "synthetic-secret"
  if target == "native": data["models"]["main"]["native"] = {"pi": {"token": "synthetic-secret"}}
  if target == "compat": data["models"]["main"]["native"] = {"pi": {"compat": {"headers": "synthetic-secret"}}}
  if target == "settings": data["profile"]["agent_options"]["model_settings"] = {"main": {"apiKey": "synthetic-secret"}}
  with pytest.raises(ConfigError) as error: model_configuration(data, PiAdapter(ROOT).route)
  assert error.value.code == "pi-model-config-fields" and "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("providers", [["synthetic-secret"], "synthetic-secret", None, {"fictional": ["synthetic-secret"]}, {"fictional": "synthetic-secret"}])
def test_malformed_providers_keep_fixed_schema_failure_without_precheck_exception(tmp_path, providers):
  data = fixture(tmp_path); data["providers"] = providers
  with pytest.raises(ConfigError) as error: rendered(data)
  assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_modern_legacy_map_migrates_into_effective_native_field_with_explicit_override_and_disabled_null(tmp_path, profile):
  data = fixture(tmp_path, profile)
  data["models"]["main"]["native"] = {"pi": {"compat": {"reasoningEffortMap": {"low": "high", "medium": "max", "high": "max"}}}}
  data["profile"]["agent_options"]["model_settings"] = {"main": {"thinking_level_map": {"medium": "low", "max": "xhigh"}, "disabled_thinking_levels": ["high"]}}
  original = deepcopy(data)
  _, manifest, fields = rendered(data)
  model = fields["models"][0]
  assert model["thinkingLevelMap"] == {"low": "high", "medium": "low", "high": None, "max": "xhigh"}
  assert "compat" not in model
  assert manifest["model_configuration"]["providers"]["agentcfg-fictional"]["config"]["models"] == fields["models"]
  assert data == original


def test_legacy_profile_preserves_old_compat_map_and_existing_explicit_map_semantics(tmp_path):
  data = fixture(tmp_path, "pi-fixture")
  data["models"]["main"]["native"] = {"pi": {"compat": {"reasoningEffortMap": {"medium": "high", "high": "max"}}}}
  data["profile"]["agent_options"]["model_settings"] = {"main": {"thinking_level_map": {"medium": "low"}, "disabled_thinking_levels": ["high"]}}
  _, manifest, fields = rendered(data)
  assert fields["models"][0]["compat"] == {"reasoningEffortMap": {"medium": "high", "high": "max"}}
  assert fields["models"][0]["thinkingLevelMap"] == {"medium": "low", "high": None}
  assert "model_configuration" not in manifest


def test_modern_explicit_and_disabled_collision_still_fails_without_silent_precedence(tmp_path):
  data = fixture(tmp_path)
  data["models"]["main"]["native"] = {"pi": {"compat": {"reasoningEffortMap": {"medium": "high"}}}}
  data["profile"]["agent_options"]["model_settings"] = {"main": {"thinking_level_map": {"medium": "low"}, "disabled_thinking_levels": ["medium"]}}
  with pytest.raises(ConfigError) as error: rendered(data)
  assert error.value.code == "pi-thinking-level-conflict"
