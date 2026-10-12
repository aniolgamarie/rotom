"""合成声明/安全Model投影，只测试纯匹配，不调用SDK/IO/账户。"""
from copy import deepcopy
import json

import pytest

from agentcfg.pi_reviewer_route import match_reviewer_route
from agentcfg.pi_reviewer_authority_protocol import authority_identity, price_identity
from agentcfg.schema import ConfigError
from test_pi_reviewer_authority import authority


def fixture():
  value = authority(); route = value["route"]; provider = route["native_route"]; remote = route["model_id"]
  binding = {"logical_id": route["logical_provider"], "auth_kind": "api-key", "owner": "pi-environment"}
  manifest = {"profile_id": "pi-full", "options": {"reviewer": {"untrusted_cost": "ignored"}},
    "model_bindings": {"main": {"provider": provider, "model": remote}},
    "provider_bindings": {provider: binding}, "allowed_models": [{"provider": provider, "model": remote}],
    "model_configuration": {"schema_version": 1, "providers": {provider: {**binding, "credential_ref": "secret:SYNTHETIC_REFERENCE",
      "config": {"api": route["api"], "baseUrl": route["base_url"], "models": [{"id": remote, "input": ["text"]}]}}}},
    "plugins": [], "bootstrap_plugins": []}
  model = {"provider": provider, "id": remote, "api": route["api"], "baseUrl": route["base_url"], "input": ["text"],
    "contextWindow": 128000, "maxTokens": 16384, "configuration_identity": "c" * 64}
  return value, manifest, model


def match(value, manifest, model, role="main"):
  return match_reviewer_route(value, manifest=manifest, role=role, model=model)


def test_explicit_route_projection_complete_independent_and_no_secrets():
  value, manifest, model = fixture(); originals = deepcopy((value, manifest, model))
  result = match(value, manifest, model)
  assert set(result) == {"route", "model_identity", "authority_document_identity", "pricing", "limits", "token_limits", "categories"}
  assert result["route"] == value["route"] and result["authority_document_identity"] == authority_identity(value)
  assert result["pricing"]["identity"] == price_identity(value) and result["limits"] == value["limits"]
  raw = json.dumps(result)
  assert "SYNTHETIC_REFERENCE" not in raw and "credential_ref" not in raw and "untrusted_cost" not in raw
  result["limits"]["max_calls"] = 999; result["categories"].clear(); result["route"]["model_id"] = "changed"
  assert (value, manifest, model) == originals


def test_role_is_explicit_and_never_main_or_other_fallback():
  value, manifest, model = fixture(); manifest["model_bindings"]["review"] = deepcopy(manifest["model_bindings"]["main"])
  assert match(value, manifest, model, role="review")["route"] == value["route"]
  for role in ("missing", None, True):
    with pytest.raises(ConfigError): match(value, manifest, model, role=role)


@pytest.mark.parametrize("field,changed", [("provider", "other"), ("id", "other"), ("api", "openai-responses"),
  ("baseUrl", "https://other.invalid/v1"), ("input", ["image"]), ("input", ["text", "text"]),
  ("input", ("text",)), ("contextWindow", True), ("contextWindow", 0), ("contextWindow", 2**53),
  ("maxTokens", 1.0), ("maxTokens", 0), ("configuration_identity", "A" * 64), ("configuration_identity", None)])
def test_wrong_safe_model_projection_fails_fixed(field, changed):
  value, manifest, model = fixture(); model[field] = changed
  with pytest.raises(ConfigError) as error: match(value, manifest, model)
  assert error.value.code == "PI_RISK_REVIEW_ROUTE_INVALID"


@pytest.mark.parametrize("field", ["headers", "token", "apiKey", "credential_ref", "cost", "name"])
def test_safe_projection_unknown_secret_or_sdk_fields_rejected(field):
  value, manifest, model = fixture(); model[field] = "SYNTHETIC_PRIVATE"
  with pytest.raises(ConfigError) as error: match(value, manifest, model)
  assert error.value.code == "PI_RISK_REVIEW_ROUTE_INVALID" and "SYNTHETIC_PRIVATE" not in str(error.value)


@pytest.mark.parametrize("kind", ["allowed-duplicate", "allowed-missing", "role-extra", "role-model", "binding-extra", "binding-logical", "binding-owner", "config-extra", "config-version", "provider-extra", "provider-owner", "provider-missing", "row-duplicate", "row-extra", "row-missing", "credential-path", "credential-control", "credential-dotdot", "credential-empty", "config-api", "config-endpoint", "authority-route"])
def test_manifest_or_authority_bindings_do_not_fallback(kind):
  value, manifest, model = fixture(); native = model["provider"]; provider = manifest["model_configuration"]["providers"][native]; config = provider["config"]
  if kind == "allowed-duplicate": manifest["allowed_models"].append(deepcopy(manifest["allowed_models"][0]))
  if kind == "allowed-missing": manifest["allowed_models"] = []
  if kind == "role-extra": manifest["model_bindings"]["main"]["source"] = "human"
  if kind == "role-model": manifest["model_bindings"]["main"]["model"] = "other"
  if kind == "binding-extra": manifest["provider_bindings"][native]["credential_ref"] = "SYNTHETIC_PRIVATE"
  if kind == "binding-logical": manifest["provider_bindings"][native]["logical_id"] = "other"
  if kind == "binding-owner": manifest["provider_bindings"][native]["owner"] = "other"
  if kind == "config-extra": config["headers"] = "SYNTHETIC_PRIVATE"
  if kind == "config-version": manifest["model_configuration"]["schema_version"] = True
  if kind == "provider-extra": provider["headers"] = "SYNTHETIC_PRIVATE"
  if kind == "provider-owner": provider["owner"] = "other"
  if kind == "provider-missing": del manifest["model_configuration"]["providers"][native]
  if kind == "row-duplicate": config["models"].append(deepcopy(config["models"][0]))
  if kind == "row-extra": config["models"][0]["cost"] = {"input": 0}
  if kind == "row-missing": config["models"] = []
  if kind == "credential-path": provider["credential_ref"] = "secret:account/token"
  if kind == "credential-control": provider["credential_ref"] = "secret:private\nvalue"
  if kind == "credential-dotdot": provider["credential_ref"] = "secret:.."
  if kind == "credential-empty": provider["credential_ref"] = "secret:"
  if kind == "config-api": config["api"] = "openai-responses"
  if kind == "config-endpoint": config["baseUrl"] = "https://other.invalid/v1"
  if kind == "authority-route": value["route"]["logical_provider"] = "other"
  with pytest.raises(ConfigError) as error: match(value, manifest, model)
  assert error.value.code == "PI_RISK_REVIEW_ROUTE_INVALID" and "SYNTHETIC_PRIVATE" not in str(error.value)


def test_declared_caps_defaults_and_input_must_match_observed_exactly():
  value, manifest, model = fixture(); config = manifest["model_configuration"]["providers"][model["provider"]]["config"]
  row = config["models"][0]; row.update(contextWindow=110, maxTokens=10, input=["text", "image"], reasoning=True, name="Synthetic")
  model.update(contextWindow=110, maxTokens=10, input=["text", "image"])
  assert match(value, manifest, model)["token_limits"] == value["token_limits"]
  model["contextWindow"] = 109
  with pytest.raises(ConfigError): match(value, manifest, model)
  model["contextWindow"] = 110; value["token_limits"]["output_tokens"] = 11
  with pytest.raises(ConfigError): match(value, manifest, model)


def test_authority_and_model_identity_drift_are_separate_from_price():
  value, manifest, model = fixture(); first = match(value, manifest, model)
  model["configuration_identity"] = "d" * 64
  second = match(value, manifest, model)
  assert first["model_identity"] != second["model_identity"] and first["pricing"] == second["pricing"]
  value["generation"] += 1
  third = match(value, manifest, model)
  assert second["model_identity"] == third["model_identity"] and second["authority_document_identity"] != third["authority_document_identity"]


def test_explicit_free_price_not_model_cost_or_profile_default():
  value, manifest, model = fixture()
  for name in ("input_units_per_million", "output_units_per_million", "cache_read_units_per_million", "cache_write_units_per_million"): value["pricing"][name] = 0
  assert match(value, manifest, model)["pricing"]["input_units_per_million"] == 0
  value.pop("pricing")
  with pytest.raises(ConfigError): match(value, manifest, model)


@pytest.mark.parametrize("owner", ["pi-native", "pi-cursor"])
def test_oauth_uses_explicit_observation_no_endpoint_invention(owner):
  value, manifest, model = fixture(); native = model["provider"]
  value["route"].update(auth_kind="oauth", owner=owner)
  manifest["provider_bindings"][native].update(auth_kind="oauth", owner=owner)
  manifest["model_configuration"]["providers"][native].update(auth_kind="oauth", owner=owner, credential_ref=None, config=None)
  if owner != "pi-native": manifest["plugins"] = manifest["bootstrap_plugins"] = [owner]
  assert match(value, manifest, model)["route"] == value["route"]
  with pytest.raises(ConfigError): match(value, manifest, None)
  model["baseUrl"] = None
  with pytest.raises(ConfigError): match(value, manifest, model)


@pytest.mark.parametrize("kind", ["plugin", "bootstrap", "credential", "config"])
def test_oauth_owner_needs_selected_bootstrap_and_null_secret_config(kind):
  value, manifest, model = fixture(); native = model["provider"]
  value["route"].update(auth_kind="oauth", owner="pi-cursor")
  manifest["provider_bindings"][native].update(auth_kind="oauth", owner="pi-cursor")
  provider = manifest["model_configuration"]["providers"][native]
  provider.update(auth_kind="oauth", owner="pi-cursor", credential_ref=None, config=None)
  manifest["plugins"] = ["pi-cursor"]; manifest["bootstrap_plugins"] = ["pi-cursor"]
  if kind == "plugin": manifest["plugins"] = []
  if kind == "bootstrap": manifest["bootstrap_plugins"] = []
  if kind == "credential": provider["credential_ref"] = "secret:SYNTHETIC_REFERENCE"
  if kind == "config": provider["config"] = {}
  with pytest.raises(ConfigError): match(value, manifest, model)


@pytest.mark.parametrize("kind", ["model", "manifest", "binding", "provider", "row"])
def test_mapping_subtypes_fail_closed(kind):
  class Derived(dict): pass
  value, manifest, model = fixture(); native = model["provider"]
  if kind == "model": model = Derived(model)
  if kind == "manifest": manifest = Derived(manifest)
  if kind == "binding": manifest["provider_bindings"][native] = Derived(manifest["provider_bindings"][native])
  if kind == "provider": manifest["model_configuration"]["providers"][native] = Derived(manifest["model_configuration"]["providers"][native])
  if kind == "row": manifest["model_configuration"]["providers"][native]["config"]["models"][0] = Derived({"id": model["id"], "input": ["text"]})
  with pytest.raises(ConfigError): match(value, manifest, model)


def test_supported_generated_compat_and_disabled_thinking_map():
  value, manifest, model = fixture()
  row = manifest["model_configuration"]["providers"][model["provider"]]["config"]["models"][0]
  row.update(compat={"requiresReasoningContentOnAssistantMessages": True, "thinkingFormat": "deepseek"}, thinkingLevelMap={"off": None, "medium": "high"})
  assert match(value, manifest, model)["route"] == value["route"]


@pytest.mark.parametrize("field,value", [
  ("compat", {"unknown": True}), ("compat", {"thinkingFormat": "other"}),
  ("compat", {"requiresReasoningContentOnAssistantMessages": 1}),
  ("thinkingLevelMap", {"unknown": "high"}), ("thinkingLevelMap", {"high": True}),
  ("thinkingLevelMap", {"high": "x" * 4097}), ("name", "bad\ud800"),
])
def test_generated_optional_fields_remain_closed(field, value):
  authority_value, manifest, model = fixture()
  manifest["model_configuration"]["providers"][model["provider"]]["config"]["models"][0][field] = value
  with pytest.raises(ConfigError): match(authority_value, manifest, model)


def test_token_total_exceeds_context_without_clamping():
  value, manifest, model = fixture()
  row = manifest["model_configuration"]["providers"][model["provider"]]["config"]["models"][0]
  row["contextWindow"] = model["contextWindow"] = 109
  with pytest.raises(ConfigError): match(value, manifest, model)
  assert value["token_limits"] == {"input_tokens": 100, "output_tokens": 10}


def test_secret_reference_does_not_enter_identity_or_return_value():
  value, manifest, model = fixture(); first = match(value, manifest, model)
  manifest["model_configuration"]["providers"][model["provider"]]["credential_ref"] = "secret:DIFFERENT_SYNTHETIC_REFERENCE"
  assert match(value, manifest, model) == first


def test_non_data_binding_does_not_invoke_custom_equality():
  class Unsafe:
    def __eq__(self, other): raise AssertionError("must not execute")
  value, manifest, model = fixture()
  manifest["model_configuration"]["providers"][model["provider"]]["owner"] = Unsafe()
  with pytest.raises(ConfigError) as error: match(value, manifest, model)
  assert error.value.code == "PI_RISK_REVIEW_ROUTE_INVALID"
