"""同adapter不同profile的闭合策略投影；只做真实离线解析。"""

from copy import deepcopy
from dataclasses import replace

import pytest

from agentcfg import config, schema
from test_config_resolution import resolution_inputs, resolve


def fixture(tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  first = catalog.profiles["fixture-default"]
  first.pop("agent_options"); first.pop("plugins")
  second = deepcopy(first); second["id"] = "fixture-second"
  catalog.profiles[second["id"]] = second
  local.data["overrides"] = {}
  return catalog, local


def profile_policy(documents, profile_id):
  defaults = deepcopy(documents["agent"]["defaults"])
  plugin = "alpha" if profile_id == "fixture-default" else "beta"
  defaults.update(plugins=[plugin], agent_options={"terminal_images": plugin == "alpha", "caption": plugin})
  return schema.AdapterPolicy(defaults=defaults, plugins={plugin: {"package": "fixture-package"}},
    credential_targets=frozenset({"FIXTURE_KEY"}), reserved_environment=frozenset({"FIXTURE_RESERVED"}))


def install(catalog, callback, *, policy=None):
  original = catalog.adapter_schemas.bundles["fixture-json"]
  catalog.adapter_schemas.bundles["fixture-json"] = replace(original, profile_policy=callback,
    policy=original.policy if policy is None else policy)
  return catalog.adapter_schemas.bundles["fixture-json"]


def test_each_profile_has_independent_defaults_and_plugin_catalog_without_legacy_fallback(tmp_path):
  catalog, local = fixture(tmp_path); seen = []
  def aware(documents, profile_id):
    seen.append(profile_id); return profile_policy(documents, profile_id)
  def legacy(_): raise AssertionError("legacy policy must not run")
  install(catalog, aware, policy=legacy)
  first = resolve(catalog, local)
  second = resolve(catalog, local, profile_id="fixture-second")
  assert first.validated_profiles == second.validated_profiles == 2
  assert first.data["profile"]["agent_options"] == {"terminal_images": True, "caption": "alpha"}
  assert second.data["profile"]["agent_options"] == {"terminal_images": False, "caption": "beta"}
  assert set(first.data["plugins"]) == {"alpha"} and set(second.data["plugins"]) == {"beta"}
  assert seen == ["fixture-default", "fixture-second"] * 2


def test_profile_then_local_override_still_take_priority_over_profile_policy_defaults(tmp_path):
  catalog, local = fixture(tmp_path); install(catalog, profile_policy)
  catalog.profiles["fixture-default"]["agent_options"] = {"caption": "profile"}
  local.data["overrides"] = {"profiles": {"fixture-default": {"agent_options": {"caption": "", "terminal_images": False}, "plugins": []}}}
  result = resolve(catalog, local)
  assert result.data["profile"]["agent_options"] == {"caption": "", "terminal_images": False}
  assert result.data["plugins"] == {}
  assert result.provenance[("profile", "agent_options", "caption")] == "local"
  assert result.provenance[("profile", "plugins")] == "local"
  second = resolve(catalog, local, profile_id="fixture-second")
  assert second.data["profile"]["agent_options"]["caption"] == "beta"


@pytest.mark.parametrize("fault", ["unknown-default", "unknown-options", "wrong-options-type", "dict-result", "null-result", "plugin-type", "plugin-id", "credential-type", "environment-name", "noncallable", "exception"])
def test_invalid_profile_policy_never_falls_back_or_echoes_callback_private_values(tmp_path, fault):
  catalog, local = fixture(tmp_path); fallback = []
  marker = "synthetic-private-policy-marker"
  def legacy(documents):
    fallback.append(True); return schema.AdapterPolicy(defaults=documents["agent"]["defaults"])
  def invalid(documents, profile_id):
    result = profile_policy(documents, profile_id)
    if fault == "unknown-default": result.defaults["unexpected"] = marker
    elif fault == "unknown-options": result.defaults["agent_options"]["unexpected"] = marker
    elif fault == "wrong-options-type": result.defaults["agent_options"]["terminal_images"] = marker
    elif fault == "dict-result": return {"defaults": result.defaults}
    elif fault == "null-result": return None
    elif fault == "plugin-type": return replace(result, plugins={"alpha": marker})
    elif fault == "plugin-id": return replace(result, plugins={"../escape": {"package": "fixture-package"}})
    elif fault == "credential-type": return replace(result, credential_targets=["FIXTURE_KEY"])
    elif fault == "environment-name": return replace(result, reserved_environment=frozenset({"BAD-NAME"}))
    elif fault == "exception": raise RuntimeError(marker)
    return result
  install(catalog, object() if fault == "noncallable" else invalid, policy=legacy)
  with pytest.raises(schema.ConfigError) as error: resolve(catalog, local)
  assert error.value.exit_code == 2 and marker not in str(error.value)
  assert fallback == []


def test_unselected_profile_policy_is_validated_and_cannot_hide_unknown_fields(tmp_path):
  catalog, local = fixture(tmp_path)
  def aware(documents, profile_id):
    result = profile_policy(documents, profile_id)
    if profile_id == "fixture-second": result.defaults["agent_options"]["unrecognized"] = True
    return result
  install(catalog, aware)
  with pytest.raises(schema.ConfigError): resolve(catalog, local, profile_id="fixture-default")


def test_hook_receives_independent_documents_and_returned_policy_is_deeply_copied(tmp_path):
  catalog, local = fixture(tmp_path)
  before = deepcopy(catalog.adapter_documents)
  returned = profile_policy(catalog.adapter_documents["fixture-json"], "fixture-default")
  def mutating(documents, profile_id):
    documents["agent"]["defaults"].clear()
    return returned
  bundle = install(catalog, mutating)
  context = schema.AdapterSchemas(catalog.adapter_schemas.bundles, {key: "fixture-json" for key in catalog.profiles})
  result = config._adapter_policy(bundle, catalog.adapter_documents["fixture-json"], context, "fixture-default")
  result.defaults["agent_options"]["caption"] = "modified"
  result.plugins["alpha"]["package"] = "modified"
  assert returned.defaults["agent_options"]["caption"] == "alpha"
  assert returned.plugins["alpha"]["package"] == "fixture-package"
  assert catalog.adapter_documents == before


def test_resolved_projection_does_not_mutate_shared_hook_result_or_later_profile(tmp_path):
  catalog, local = fixture(tmp_path); returned = {}
  def aware(documents, profile_id):
    returned.setdefault(profile_id, profile_policy(documents, profile_id))
    return returned[profile_id]
  install(catalog, aware)
  first = resolve(catalog, local)
  first.data["profile"]["agent_options"]["caption"] = "mutated"
  first.data["plugins"]["alpha"]["package"] = "mutated"
  assert resolve(catalog, local).data["profile"]["agent_options"]["caption"] == "alpha"
  assert resolve(catalog, local, profile_id="fixture-second").data["profile"]["agent_options"]["caption"] == "beta"
  assert returned["fixture-default"].plugins["alpha"]["package"] == "fixture-package"


def test_no_hook_preserves_original_policy_and_old_positional_bundle_constructor(tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  original = catalog.adapter_schemas.bundles["fixture-json"]
  bundle = schema.AdapterSchemaBundle(original.declaration, original.documents, original.agent_options, original.validate,
    original.policy, original.authentication_claims, original.validate_selected)
  assert bundle.profile_policy is None
  calls = []
  def legacy(documents):
    calls.append(deepcopy(documents)); return original.policy(documents)
  catalog.adapter_schemas.bundles["fixture-json"] = replace(bundle, policy=legacy)
  result = resolve(catalog, local)
  assert len(calls) == 1
  assert result.data["profile"]["agent_options"] == {"terminal_images": False, "caption": ""}
  assert set(result.data["plugins"]) == {"optional"}


def test_profile_hook_can_replace_an_absent_legacy_policy(tmp_path):
  catalog, local = fixture(tmp_path)
  bundle = catalog.adapter_schemas.bundles["fixture-json"]
  catalog.adapter_schemas.bundles["fixture-json"] = replace(bundle, policy=None, profile_policy=profile_policy)
  assert resolve(catalog, local).data["profile"]["agent_options"]["caption"] == "alpha"
  catalog.adapter_schemas.bundles["fixture-json"] = replace(bundle, policy=None)
  with pytest.raises(schema.ConfigError): resolve(catalog, local)
