"""能力选择只消费虚构锁与独立观测，不安装或启动宿主。"""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from agentcfg.activity import digest
from agentcfg.schema import ConfigError
from agentcfg.process import DependencyError
from agentcfg.pi_capabilities import (validate_selection, check_installed, check_loaded,
  selection_identity, source_identity, runtime_identity, config_identity, acceptance_context_identity)


def fixture():
  source = {"kind": "npm", "package": "@fixture/pi", "version": "1.0.1", "integrity": "sha512-" + "A" * 86 + "=="}
  extra = {"kind": "local", "package": "fixture-delegate", "version": "1.0.0", "archive_digest": "a" * 64, "source_tree_digest": "b" * 64}
  catalog = {"schema_version": 1, "revision": 3, "capabilities": {
    "compression": {"profiles": ["pi-base", "pi-full"], "required": True, "contract_version": "1", "owner_domain": "compression", "single_owner": True,
      "config_fields": ["/settings/compaction"], "state_owners": ["native-sessions"], "source_ids": ["pi-host"], "resource_ids": ["compact"]},
    "delegate": {"profiles": ["pi-full"], "required": True, "contract_version": "1", "owner_domain": "delegation", "single_owner": True,
      "config_fields": ["/settings/delegate"], "state_owners": ["delegate-runs"], "source_ids": ["delegate-source"], "resource_ids": ["delegate-skill"]}},
    "source_profiles": {"pi-host": ["pi-base", "pi-full"], "delegate-source": ["pi-full"]},
    "resource_profiles": {"compact": ["pi-base", "pi-full"], "delegate-skill": ["pi-full"]}}
  def provider(capability, source_id, source_value, resource, state, field, entry):
    return {"provider_id": capability + "-provider", "capability_id": capability, "source_id": source_id,
      "source_version": source_value["version"], "source_identity": source_identity(source_value), "contract_version": "1",
      "verified_host_versions": ["1.0.1"], "engines": ["node"], "requires": [], "conflicts": [], "public_entrypoints": [entry],
      "config_fields": [field], "state_owners": [state], "resource_ids": [resource],
      "migration_refs": ["docs/fixture/migration.md"], "uninstall_refs": ["docs/fixture/uninstall.md"], "rollback_refs": ["docs/fixture/rollback.md"]}
  providers = {"compression-provider": provider("compression", "pi-host", source, "compact", "native-sessions", "/settings/compaction", "native/compact"),
    "delegate-provider": provider("delegate", "delegate-source", extra, "delegate-skill", "delegate-runs", "/settings/delegate", "delegate/cli")}
  selection = {"schema_version": 1, "profile": "pi-base", "revision": 1, "source_revision": 3, "state": "candidate",
    "bindings": [{"capability_id": "compression", "provider_id": "compression-provider"}]}
  lock = SimpleNamespace(identity="c" * 64, metadata={"sources": {"pi-host": source, "delegate-source": extra}, "profile_slices": {
    "pi-base": {"engine": "node", "source_ids": ["pi-host"], "resource_manifest": {"extensions": [{"id": "compact", "capability_id": "compression", "path": "pi-base/native/compact"}]}},
    "pi-full": {"engine": "node", "source_ids": ["pi-host", "delegate-source"], "resource_manifest": {"extensions": [{"id": "compact", "capability_id": "compression", "path": "pi-full/native/compact"}],
      "skills": [{"id": "delegate-skill", "capability_id": "delegate", "path": "pi-full/delegate/skill"}]}}}})
  return catalog, providers, selection, lock


def resolve(values, **kwargs):
  return validate_selection(*values, host_version="1.0.1", engine="node", **kwargs)


def observed_sources(lock, profile):
  return [{"source_id": source_id, "version": lock.metadata["sources"][source_id]["version"], "source_identity": source_identity(lock.metadata["sources"][source_id])}
    for source_id in lock.metadata["profile_slices"][profile]["source_ids"]]


def test_candidate_selection_is_valid_without_becoming_accepted_and_observations_are_independent():
  values = fixture(); result = resolve(values)
  assert result.state == "candidate" and values[2]["state"] == "candidate"
  assert check_installed(result, observed_sources(values[3], "pi-base")) is True
  assert check_loaded(result, {"extensions": ["compact"], "skills": [], "prompts": [], "themes": []}) is True
  with pytest.raises(DependencyError): check_loaded(result, {"extensions": [], "skills": [], "prompts": [], "themes": []})
  with pytest.raises(DependencyError): check_installed(result, [])


def test_unverified_host_version_can_only_form_explicit_candidate():
  values = fixture(); provider = values[1]["compression-provider"]
  provider["verified_host_versions"] = []
  provider["candidate_host_versions"] = ["1.0.1"]
  candidate = resolve(values)
  assert candidate.state == "candidate" and provider["verified_host_versions"] == []
  for state in ("current", "accepted"):
    values[2]["state"] = state
    with pytest.raises(ConfigError): resolve(values, accepted_binding_digest=candidate.acceptance_context_digest)


def test_verifying_candidate_version_changes_binding_identity_and_needs_new_acceptance():
  values = fixture(); provider = values[1]["compression-provider"]
  provider.update(verified_host_versions=[], candidate_host_versions=["1.0.1"])
  candidate = resolve(values)
  provider["verified_host_versions"] = ["1.0.1"]
  verified_candidate = resolve(values)
  assert candidate.binding_digest != verified_candidate.binding_digest
  assert candidate.acceptance_context_digest != verified_candidate.acceptance_context_digest
  values[2]["state"] = "accepted"
  with pytest.raises(ConfigError): resolve(values, accepted_binding_digest=candidate.acceptance_context_digest)
  proof = acceptance_context_identity(*values, host_version="1.0.1", engine="node")
  assert resolve(values, accepted_binding_digest=proof).state == "accepted"


@pytest.mark.parametrize("versions", [None, "1.0.1", ["latest"], [True], ["1.0.1", "1.0.1"], []])
def test_candidate_host_versions_are_closed_and_cannot_replace_empty_compatibility(versions):
  values = fixture(); provider = values[1]["compression-provider"]
  provider.update(verified_host_versions=[], candidate_host_versions=versions)
  with pytest.raises(ConfigError): resolve(values)


@pytest.mark.parametrize("fault", ["unknown-provider", "unknown-capability", "unknown-field", "provider-field", "catalog-field", "host", "engine", "contract", "version", "source-swap", "source-revision", "dual-owner", "config-excess", "state-excess", "conflict", "requires", "accepted", "base-capability", "base-source", "base-resource"])
def test_binding_rejects_invalid_or_unauthorized_candidates(fault):
  values = fixture(); catalog, providers, selection, lock = values
  provider = providers["compression-provider"]
  if fault == "unknown-provider": selection["bindings"][0]["provider_id"] = "unknown"
  if fault == "unknown-capability": selection["bindings"][0]["capability_id"] = "unknown"
  if fault == "unknown-field": selection["auth"] = "synthetic-secret"
  if fault == "provider-field": provider["single_owner"] = False
  if fault == "catalog-field": catalog["credentials"] = "synthetic-secret"
  if fault == "host": provider["verified_host_versions"] = ["0.84.4"]
  if fault == "engine": provider["engines"] = ["bun"]
  if fault == "contract": provider["contract_version"] = "2"
  if fault == "version": provider["source_version"] = "latest"
  if fault == "source-swap": provider["source_identity"] = "d" * 64
  if fault == "source-revision": selection["source_revision"] += 1
  if fault == "dual-owner":
    other = deepcopy(provider); other["provider_id"] = "second-compressor"; providers[other["provider_id"]] = other
    selection["bindings"].append({"capability_id": "compression", "provider_id": other["provider_id"]})
  if fault == "config-excess": provider["config_fields"] = ["/settings"]
  if fault == "state-excess": provider["state_owners"] = ["user-auth"]
  if fault == "conflict": provider["conflicts"] = ["compression"]
  if fault == "requires": provider["requires"] = ["delegate"]
  if fault == "accepted": selection["state"] = "accepted"
  if fault == "base-capability": selection["bindings"].append({"capability_id": "delegate", "provider_id": "delegate-provider"})
  if fault == "base-source":
    catalog["capabilities"]["compression"]["source_ids"].append("delegate-source")
    provider.update(source_id="delegate-source", source_version="1.0.0", source_identity=source_identity(lock.metadata["sources"]["delegate-source"]))
  if fault == "base-resource":
    catalog["capabilities"]["compression"]["resource_ids"].append("delegate-skill"); provider["resource_ids"] = ["delegate-skill"]
  with pytest.raises(ConfigError) as failure: resolve(values)
  assert failure.value.exit_code == 2 and "synthetic-secret" not in str(failure.value)


def test_accepted_selection_needs_an_exact_external_acceptance_identity_and_never_mutates():
  values = fixture(); values[2]["state"] = "accepted"
  accepted = acceptance_context_identity(*values, host_version="1.0.1", engine="node")
  result = resolve(values, accepted_binding_digest=accepted)
  assert result.state == "accepted"
  values[2]["revision"] += 1
  with pytest.raises(ConfigError): resolve(values, accepted_binding_digest=accepted)


@pytest.mark.parametrize("fault", ["missing-source", "slice-source", "slice-resource", "slice-engine", "slice-full-source", "slice-full-resource"])
def test_declared_but_missing_or_contaminated_lock_slice_fails_with_dependency_code(fault):
  values = fixture(); piece = values[3].metadata["profile_slices"]["pi-base"]
  if fault == "missing-source": values[3].metadata["sources"].pop("pi-host")
  if fault == "slice-source": piece["source_ids"] = []
  if fault == "slice-resource": piece["resource_manifest"] = {}
  if fault == "slice-engine": piece["engine"] = "bun"
  if fault == "slice-full-source": piece["source_ids"].append("delegate-source")
  if fault == "slice-full-resource": piece["resource_manifest"]["skills"] = [{"id": "delegate-skill", "capability_id": "delegate", "path": "bad"}]
  with pytest.raises(DependencyError) as failure: resolve(values)
  assert failure.value.exit_code == 5


@pytest.mark.parametrize("kind,fault", [("installed", "missing"), ("installed", "extra"), ("installed", "duplicate"), ("installed", "identity"), ("loaded", "missing"), ("loaded", "extra"), ("loaded", "duplicate")])
def test_installed_and_loaded_facts_reject_missing_extra_duplicate_or_changed_identity(kind, fault):
  values = fixture(); result = resolve(values)
  if kind == "installed":
    observed = observed_sources(values[3], "pi-base")
    if fault == "missing": observed = []
    if fault == "extra": observed.extend(observed_sources(values[3], "pi-full")[1:])
    if fault == "duplicate": observed *= 2
    if fault == "identity": observed[0]["source_identity"] = "d" * 64
    with pytest.raises(DependencyError): check_installed(result, observed)
  else:
    observed = {"extensions": ["compact"], "skills": [], "prompts": [], "themes": []}
    if fault == "missing": observed["extensions"] = []
    if fault == "extra": observed["skills"].append("delegate-skill")
    if fault == "duplicate": observed["extensions"] *= 2
    with pytest.raises(DependencyError): check_loaded(result, observed)


def test_full_selection_uses_shared_contracts_and_configuration_prefixes_cannot_overlap():
  values = fixture(); catalog, providers, selection, lock = values
  selection["profile"] = "pi-full"; selection["bindings"].append({"capability_id": "delegate", "provider_id": "delegate-provider"})
  result = resolve(values)
  assert check_installed(result, observed_sources(lock, "pi-full"))
  assert check_loaded(result, {"extensions": ["compact"], "skills": ["delegate-skill"], "prompts": [], "themes": []})
  catalog["capabilities"]["delegate"]["config_fields"] = ["/settings/compaction/limit"]
  providers["delegate-provider"]["config_fields"] = ["/settings/compaction/limit"]
  with pytest.raises(ConfigError): resolve(values)


def test_identity_inputs_are_closed_and_do_not_hash_arbitrary_authentication(monkeypatch):
  values = fixture(); result = resolve(values)
  monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")
  runtime = runtime_identity(result, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64")
  config = config_identity(profile="pi-base", effective_config_digest="a" * 64, policy_digest="b" * 64, project_constraints_digest="c" * 64)
  assert len(runtime) == len(config) == 64
  with pytest.raises(TypeError): config_identity(profile="pi-base", effective_config_digest="a" * 64, policy_digest="b" * 64, project_constraints_digest="c" * 64, auth={"token": "synthetic-secret"})
  with pytest.raises(ConfigError): selection_identity({**values[2], "token_digest": digest("synthetic-secret")})
  changed = runtime_identity(result, runtime_digest="e" * 64, adapter_version="pi-2", platform="linux-x86_64")
  assert changed != runtime
  values[3].metadata["sources"]["pi-host"]["auth"] = {"token": "synthetic-secret"}
  with pytest.raises(ConfigError): source_identity(values[3].metadata["sources"]["pi-host"])


@pytest.mark.parametrize("left,right,conflict", [("/settings/foo", "/settings/foobar", False), ("/settings/a~1b", "/settings/a~1b/limit", True), ("/settings/a~01b", "/settings/a~1b", False), ("/settings/foo", "/settings/foo", True)])
def test_configuration_ownership_uses_decoded_json_pointer_tokens(left, right, conflict):
  values = fixture(); catalog, providers, selection, lock = values
  selection["profile"] = "pi-full"; selection["bindings"].append({"capability_id": "delegate", "provider_id": "delegate-provider"})
  for capability, path in (("compression", left), ("delegate", right)):
    catalog["capabilities"][capability]["config_fields"] = [path]
    providers[capability + "-provider"]["config_fields"] = [path]
  if conflict:
    with pytest.raises(ConfigError): resolve(values)
  else: assert resolve(values).profile == "pi-full"


@pytest.mark.parametrize("pointer", ["", "/", "settings/foo", "/foo~2bar", "/foo~", "/foo\0bar"])
def test_malformed_or_root_configuration_pointer_is_rejected(pointer):
  values = fixture(); values[1]["compression-provider"]["config_fields"] = [pointer]
  with pytest.raises(ConfigError): resolve(values)


def test_native_provider_needs_no_fake_extension_registration():
  values = fixture(); catalog, providers, selection, lock = values
  catalog["capabilities"]["compression"]["resource_ids"] = []
  providers["compression-provider"]["resource_ids"] = []
  lock.metadata["profile_slices"]["pi-base"]["resource_manifest"] = {}
  result = resolve(values)
  assert check_loaded(result, {"extensions": [], "skills": [], "prompts": [], "themes": []})
  assert providers["compression-provider"]["public_entrypoints"] == ["native/compact"]


def test_old_binding_identity_and_expectations_remain_frozen_after_input_changes():
  values = fixture(); result = resolve(values)
  before = runtime_identity(result, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64")
  installed = observed_sources(values[3], "pi-base")
  values[1]["compression-provider"]["public_entrypoints"] = ["changed/entry"]
  values[2]["revision"] += 1
  values[3].metadata["profile_slices"]["pi-base"]["source_ids"].append("delegate-source")
  assert runtime_identity(result, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64") == before
  assert check_installed(result, installed)


def test_candidate_acceptance_digest_cannot_be_reused_for_accepted_state():
  values = fixture(); candidate = selection_identity(values[2])
  values[2]["state"] = "accepted"
  with pytest.raises(ConfigError): resolve(values, accepted_binding_digest=candidate)
  values[2]["state"] = "current"
  assert resolve(values).state == "current"


def test_source_version_change_cannot_keep_old_content_identity():
  values = fixture()
  original = source_identity(values[3].metadata["sources"]["pi-host"])
  values[3].metadata["sources"]["pi-host"]["version"] = "1.0.2"
  values[1]["compression-provider"]["source_version"] = "1.0.2"
  assert source_identity(values[3].metadata["sources"]["pi-host"]) != original
  with pytest.raises(ConfigError): resolve(values)


@pytest.mark.parametrize("fault", ["unknown-required", "unknown-source", "unknown-resource", "float-schema", "boolean-revision", "auth-acceptance-field"])
def test_all_reference_and_selection_shapes_are_closed(fault):
  values = fixture()
  if fault == "unknown-required": values[1]["compression-provider"]["requires"] = ["unknown"]
  if fault == "unknown-source": values[1]["compression-provider"]["source_id"] = "unknown"
  if fault == "unknown-resource": values[1]["compression-provider"]["resource_ids"] = ["unknown"]
  if fault == "float-schema": values[2]["schema_version"] = 1.0
  if fault == "boolean-revision": values[2]["revision"] = True
  if fault == "auth-acceptance-field": values[2]["accepted_binding_digest"] = selection_identity(values[2])
  with pytest.raises(ConfigError): resolve(values)


def test_distinct_capabilities_cannot_supply_two_owners_for_one_catalog_domain():
  values = fixture(); catalog, providers, selection, lock = values
  selection["profile"] = "pi-full"; selection["bindings"].append({"capability_id": "delegate", "provider_id": "delegate-provider"})
  catalog["capabilities"]["delegate"]["owner_domain"] = "compression"
  with pytest.raises(ConfigError): resolve(values)


@pytest.mark.parametrize("source", [{"kind": "git", "package": "fixture-git", "version": "1.0.0", "archive_digest": "a" * 64, "source_tree_digest": "b" * 64, "commit": "c" * 40},
  {"kind": "asset", "archive_digest": "a" * 64, "target": "bin/helper", "archive_member": "helper", "platform": "linux-x86_64"},
  {"kind": "asset", "archive_digest": "a" * 64, "target": "data/model", "format": "raw", "size": 16, "platform": "all"}])
def test_existing_source_kinds_have_content_bound_non_secret_identity(source):
  original = source_identity(source)
  changed = deepcopy(source); changed["archive_digest"] = "d" * 64
  assert source_identity(changed) != original


@pytest.mark.parametrize("secret_field", ["api_key", "token_digest", "auth"])
def test_unknown_secret_channels_are_rejected_before_source_hashing(secret_field, monkeypatch):
  import agentcfg.pi_capabilities as module
  source = fixture()[3].metadata["sources"]["pi-host"]
  source[secret_field] = "synthetic-secret"
  monkeypatch.setattr(module, "digest", lambda *_: pytest.fail("must not hash an unprojected secret input"))
  with pytest.raises(ConfigError): module.source_identity(source)


def test_explicit_source_url_credentials_are_rejected_without_exposing_value():
  source = fixture()[3].metadata["sources"]["pi-host"]
  source["resolved"] = "https://fixture.invalid/package?token=synthetic-secret"
  with pytest.raises(ConfigError) as failure: source_identity(source)
  assert "synthetic-secret" not in str(failure.value)


def test_provider_compatibility_and_ownership_changes_change_runtime_binding_identity():
  values = fixture(); before = resolve(values)
  values[1]["compression-provider"]["verified_host_versions"].append("1.0.2")
  after = resolve(values)
  assert before.binding_digest != after.binding_digest
  assert runtime_identity(before, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64") != runtime_identity(after, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64")


@pytest.mark.parametrize("change", ["source", "entrypoint", "config", "catalog", "slice", "lock", "host", "engine"])
def test_accepted_proof_cannot_be_reused_when_effective_binding_context_changes(change):
  values = fixture(); catalog, providers, selection, lock = values
  provider = providers["compression-provider"]
  provider["verified_host_versions"] = ["1.0.1", "1.0.2"]; provider["engines"] = ["node", "bun"]
  selection["state"] = "accepted"
  accepted = acceptance_context_identity(*values, host_version="1.0.1", engine="node")
  host, engine = "1.0.1", "node"
  if change == "source":
    lock.metadata["sources"]["pi-host"]["version"] = "1.0.2"
    provider.update(source_version="1.0.2", source_identity=source_identity(lock.metadata["sources"]["pi-host"]))
  if change == "entrypoint": provider["public_entrypoints"] = ["native/new-compact"]
  if change == "config": provider["config_fields"] = ["/settings/compaction/limit"]
  if change == "catalog": catalog["capabilities"]["compression"]["config_fields"].append("/settings/extra")
  if change == "slice": lock.metadata["profile_slices"]["pi-base"]["resource_manifest"]["extensions"][0]["path"] = "pi-base/new/compact"
  if change == "lock": lock.identity = "d" * 64
  if change == "host": host = "1.0.2"
  if change == "engine": engine = "bun"; lock.metadata["profile_slices"]["pi-base"]["engine"] = engine
  with pytest.raises(ConfigError):
    validate_selection(*values, host_version=host, engine=engine, accepted_binding_digest=accepted)


def test_computable_acceptance_context_is_not_itself_acceptance_or_activation():
  values = fixture()
  candidate_context = acceptance_context_identity(*values, host_version="1.0.1", engine="node")
  assert resolve(values, accepted_binding_digest=candidate_context).state == "candidate"
  values[2]["state"] = "accepted"
  accepted_context = acceptance_context_identity(*values, host_version="1.0.1", engine="node")
  assert accepted_context != candidate_context
  with pytest.raises(ConfigError): resolve(values)
  with pytest.raises(ConfigError): resolve(values, accepted_binding_digest=candidate_context)
  assert resolve(values, accepted_binding_digest=accepted_context).acceptance_context_digest == accepted_context


def test_acceptance_context_helper_cannot_digest_an_invalid_combination():
  values = fixture(); values[1]["compression-provider"]["config_fields"] = ["/settings"]
  with pytest.raises(ConfigError): acceptance_context_identity(*values, host_version="1.0.1", engine="node")


def test_effective_host_compatibility_context_is_also_part_of_runtime_identity():
  values = fixture(); values[1]["compression-provider"]["verified_host_versions"].append("1.0.2")
  before = resolve(values)
  after = validate_selection(*values, host_version="1.0.2", engine="node")
  assert before.acceptance_context_digest != after.acceptance_context_digest
  assert runtime_identity(before, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64") != runtime_identity(after, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64")
