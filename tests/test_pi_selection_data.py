"""显式选择数据与固定旧resolver/proof基线；默认合成fixture无宿主。"""

import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import agentcfg.pi_capabilities as capabilities
from agentcfg.pi_lock_resolution import VERSION
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from test_pi_provider_bindings import fixture
from test_pi_capability_manifest import binding_repository, _write_manifest
from test_pi_dependencies import fixture_repository


# 原完整resolver/context helper/public proof前像fbe45b1c.../22024。
# 这里的旧函数没有新data函数或新private桥，不用双新路径冒充旧行为。
LEGACY_SELECTION = (
  "def _resolve_selection(catalog, providers, selection, lock, *, host_version, engine):\n"
  "  \"\"\"只验证闭合上下文；内部计算不判定其是否通过外部验收。\"\"\"\n"
  "  _catalog(catalog); _providers(providers, catalog); pairs = _selection(selection); _version(host_version)\n"
  "  identity = selection_identity(selection); profile = selection[\"profile\"]\n"
  "  if selection[\"source_revision\"] != catalog[\"revision\"]: _fail()\n"
  "  chosen = {capability for capability, _ in pairs}\n"
  "  required = {name for name, capability in catalog[\"capabilities\"].items() if capability[\"required\"] and profile in capability[\"profiles\"]}\n"
  "  if required - chosen: _fail()\n"
  "  domains = {}; fields = []; owners = set(); resources = {}; sources = {}; selected = []\n"
  "  metadata = lock.metadata\n"
  "  for capability_id, provider_id in pairs:\n"
  "    if capability_id not in catalog[\"capabilities\"] or provider_id not in providers: _fail()\n"
  "    capability = catalog[\"capabilities\"][capability_id]; provider = providers[provider_id]\n"
  "    host_versions = provider[\"verified_host_versions\"]\n"
  "    if selection[\"state\"] == \"candidate\": host_versions = [*host_versions, *provider.get(\"candidate_host_versions\", [])]\n"
  "    if provider[\"capability_id\"] != capability_id or profile not in capability[\"profiles\"] or provider[\"contract_version\"] != capability[\"contract_version\"] or host_version not in host_versions or engine not in provider[\"engines\"]: _fail()\n"
  "    domain = capability[\"owner_domain\"]\n"
  "    domain_rows = domains.setdefault(domain, [])\n"
  "    if domain_rows and (capability[\"single_owner\"] or any(row[\"single_owner\"] for row in domain_rows)): _fail()\n"
  "    domain_rows.append(capability)\n"
  "    if set(provider[\"requires\"]) - chosen or set(provider[\"conflicts\"]) & chosen: _fail()\n"
  "    allowed = _pointers(capability[\"config_fields\"])\n"
  "    for path in _pointers(provider[\"config_fields\"]):\n"
  "      if not any(_prefix(parent, path) for parent in allowed) or any(_prefix(path, other) or _prefix(other, path) for other in fields): _fail()\n"
  "      fields.append(path)\n"
  "    if set(provider[\"state_owners\"]) - set(capability[\"state_owners\"]) or owners & set(provider[\"state_owners\"]): _fail()\n"
  "    owners.update(provider[\"state_owners\"])\n"
  "    for resource in provider[\"resource_ids\"]:\n"
  "      if resource not in capability[\"resource_ids\"] or profile not in catalog[\"resource_profiles\"][resource] or resource in resources: _fail()\n"
  "      resources[resource] = capability_id\n"
  "    # 辅助包/二进制同样进入选择和安装身份，不能伪造新能力或绕过来源闭包。\n"
  "    for declared in [provider, *provider.get(\"support_sources\", [])]:\n"
  "      source_id = declared[\"source_id\"]\n"
  "      if source_id not in capability[\"source_ids\"] or profile not in catalog[\"source_profiles\"][source_id]: _fail()\n"
  "      source = metadata[\"sources\"].get(source_id)\n"
  "      if source is None: raise DependencyError(\"Pi绑定来源尚未锁定\")\n"
  "      actual = source_identity(source)\n"
  "      if declared[\"source_version\"] != source.get(\"version\") or declared[\"source_identity\"] != actual: _fail()\n"
  "      sources[source_id] = (source_id, source.get(\"version\"), actual)\n"
  "    selected.append(deepcopy(provider))\n"
  "  piece = metadata[\"profile_slices\"].get(profile)\n"
  "  if piece is None or piece[\"engine\"] != engine or len(set(piece[\"source_ids\"])) != len(piece[\"source_ids\"]) or set(piece[\"source_ids\"]) != set(sources):\n"
  "    raise DependencyError(\"Pi绑定与依赖切片不匹配\")\n"
  "  loaded = {}; seen = set()\n"
  "  if set(piece[\"resource_manifest\"]) - set(RESOURCE_KINDS): raise DependencyError(\"Pi资源切片不匹配\")\n"
  "  for kind in RESOURCE_KINDS:\n"
  "    entries = piece[\"resource_manifest\"].get(kind, [])\n"
  "    for entry in entries:\n"
  "      if entry[\"id\"] in seen or resources.get(entry[\"id\"]) != entry[\"capability_id\"]: raise DependencyError(\"Pi资源切片不匹配\")\n"
  "      seen.add(entry[\"id\"])\n"
  "    loaded[kind] = tuple(sorted(entry[\"id\"] for entry in entries))\n"
  "  if seen != set(resources): raise DependencyError(\"Pi资源切片不匹配\")\n"
  "  _hex(lock.identity)\n"
  "  catalog_digest, binding_digest, slice_digest = digest(catalog), digest(selected), digest(piece)\n"
  "  source_expectations, resource_expectations = tuple(sorted(sources.values())), tuple(loaded.items())\n"
  "  # 不包含外部证明或自身摘要，避免自引用；状态与实际兼容环境均须精确绑定。\n"
  "  context = digest({\"selection_digest\": identity, \"catalog_digest\": catalog_digest, \"binding_digest\": binding_digest,\n"
  "    \"lock_identity\": lock.identity, \"slice_digest\": slice_digest, \"sources\": source_expectations,\n"
  "    \"resources\": resource_expectations, \"host_version\": host_version, \"engine\": engine})\n"
  "  return ValidatedSelection(profile, selection[\"state\"], identity, catalog_digest, binding_digest, lock.identity,\n"
  "    slice_digest, source_expectations, resource_expectations, context)\n"
  "\n"
  "\n"
  "def acceptance_context_identity(catalog, providers, selection, lock, *, host_version, engine):\n"
  "  \"\"\"生成严格验证后的完整非秘密上下文身份；可计算摘要本身不证明验收或提供授权。\"\"\"\n"
  "  return _resolve_selection(catalog, providers, selection, lock, host_version=host_version, engine=engine).acceptance_context_digest\n"
  "\n"
  "\n"
  "def validate_selection(catalog, providers, selection, lock, *, host_version, engine, accepted_binding_digest=None):\n"
  "  \"\"\"消费已校验 PiLock；accepted 的上下文证明仅能来自可信验收控制面，不产生激活授权。\"\"\"\n"
  "  result = _resolve_selection(catalog, providers, selection, lock, host_version=host_version, engine=engine)\n"
  "  if accepted_binding_digest is not None: _hex(accepted_binding_digest)\n"
  "  if result.state == \"accepted\" and accepted_binding_digest != result.acceptance_context_digest: _fail()\n"
  "  return result\n"
  "\n"
  "\n"
)


@pytest.fixture
def old_selection():
  namespace = vars(capabilities).copy()
  exec(compile(LEGACY_SELECTION, "<fixed-before-selection-data>", "exec"), namespace)
  return namespace


def data_arguments(values):
  catalog, providers, selection, lock = values
  return (catalog, providers, selection, lock.metadata), {"lock_identity": lock.identity, "host_version": "1.0.1", "engine": "node"}


def compare(values, old_selection, *, host_version="1.0.1", engine="node", accepted_binding_digest=None):
  before = deepcopy(values)
  kwargs = {"host_version": host_version, "engine": engine, "accepted_binding_digest": accepted_binding_digest}
  # 此旧baseline源码没有新API引用，旧公共proof函数调用其独立namespace内原resolver。
  expected = old_selection["validate_selection"](*values, **kwargs)
  actual = capabilities.validate_selection(*values, **kwargs)
  args, identity = data_arguments(values)
  identity.update(kwargs)
  result = capabilities.validate_selection_data(*args, **identity)
  assert result == actual == expected
  assert len(fields(result)) == 10
  assert capabilities.runtime_identity(result, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64") == capabilities.runtime_identity(expected, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64")
  assert values == before
  return result


def full(values):
  values[2]["profile"] = "pi-full"
  values[2]["bindings"].append({"capability_id": "delegate", "provider_id": "delegate-provider"})


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
@pytest.mark.parametrize("state", ["current", "candidate", "accepted"])
@pytest.mark.parametrize("metadata_identity", ["absent", "different"])
def test_minimal_old_metadata_domain_and_all_fields_remain_exact(profile, state, metadata_identity, old_selection):
  values = fixture()
  if profile == "pi-full": full(values)
  values[2]["state"] = state
  if metadata_identity == "different": values[3].metadata["identity"] = "f" * 64
  else: assert "identity" not in values[3].metadata
  proof = old_selection["acceptance_context_identity"](*values, host_version="1.0.1", engine="node") if state == "accepted" else None
  compare(values, old_selection, accepted_binding_digest=proof)


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
@pytest.mark.parametrize("state", ["current", "candidate", "accepted"])
def test_formal_v2_metadata_and_context_matches_frozen_original(tmp_path, profile, state, old_selection):
  from agentcfg.pi_dependencies import PiBackend
  workspace, manifest = binding_repository(tmp_path)
  for selection in manifest["capability_bindings"]["selections"].values(): selection["state"] = state
  _write_manifest(workspace.repository, manifest)
  binding = manifest["capability_bindings"]
  # 仅旧接口独立基线的稳定数据fixture，不伪造PiLock或 installed 来源。
  old_lock = SimpleNamespace(identity=manifest["identity"], metadata=manifest)
  values = (binding["catalog"], binding["providers"], binding["selections"][profile], old_lock)
  proof = old_selection["acceptance_context_identity"](*values, host_version="1.0.0", engine="node") if state == "accepted" else None
  # 显式data入口直接消费metadata，没有为它构造锁对象。
  args = (values[0], values[1], values[2], manifest)
  before = deepcopy(args)
  expected = old_selection["validate_selection"](*values, host_version="1.0.0", engine="node", accepted_binding_digest=proof)
  actual = capabilities.validate_selection_data(*args, lock_identity=manifest["identity"], host_version="1.0.0", engine="node", accepted_binding_digest=proof)
  assert actual == expected and args == before
  accepted = {name: old_selection["acceptance_context_identity"](binding["catalog"], binding["providers"], selection, old_lock, host_version="1.0.0", engine="node") for name, selection in binding["selections"].items()} if state == "accepted" else None
  lock = PiBackend(family="modern").read_lock(workspace.repository, accepted_binding_digests=accepted)
  assert lock.validated_bindings[profile] == actual
  assert capabilities.runtime_identity(actual, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64") == capabilities.runtime_identity(expected, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64")


def test_actual_formal_v1_has_no_legal_modern_selection_and_keeps_old_rejection(tmp_path, old_selection):
  _, manifest = fixture_repository(tmp_path)
  catalog, providers, selection, _ = fixture()
  # formal v1不能含pi-base/pi-full，也没有现代bindings；不伪造其合法选择。
  values = (catalog, providers, selection, SimpleNamespace(identity=manifest["identity"], metadata=manifest))
  with pytest.raises(DependencyError) as old:
    old_selection["validate_selection"](*values, host_version="1.0.1", engine="node")
  with pytest.raises(DependencyError) as new:
    capabilities.validate_selection_data(catalog, providers, selection, manifest, lock_identity=manifest["identity"], host_version="1.0.1", engine="node")
  assert new.value.args == old.value.args


def add_support(values, source):
  catalog, providers, _, lock = values
  catalog["capabilities"]["compression"]["source_ids"].append("helper")
  catalog["source_profiles"]["helper"] = ["pi-base", "pi-full"]
  providers["compression-provider"]["support_sources"] = [{"source_id": "helper", "source_version": source.get("version"), "source_identity": capabilities.source_identity(source)}]
  lock.metadata["sources"]["helper"] = source
  lock.metadata["profile_slices"]["pi-base"]["source_ids"].append("helper")


@pytest.mark.parametrize("kind", ["local", "node", "build"])
def test_existing_legal_support_source_checks_remain_real_and_equivalent(tmp_path, monkeypatch, kind, old_selection):
  values = fixture()
  if kind == "local": source = deepcopy(values[3].metadata["sources"]["delegate-source"])
  elif kind == "node":
    from test_pi_node_asset import source as node_source, archive_fixture
    source = node_source(archive_fixture())
  else:
    from test_pi_built_assets import built_fixture
    source, _, _ = built_fixture(tmp_path / "built", monkeypatch)
  add_support(values, source)
  result = compare(values, old_selection)
  assert ("helper", source.get("version"), capabilities.source_identity(source)) in result.source_expectations
  values[1]["compression-provider"]["support_sources"][0]["source_identity"] = "0" * 64
  with pytest.raises(ConfigError) as old: old_selection["validate_selection"](*values, host_version="1.0.1", engine="node")
  args, kwargs = data_arguments(values)
  with pytest.raises(ConfigError) as new: capabilities.validate_selection_data(*args, **kwargs)
  assert new.value.args == old.value.args


@pytest.mark.parametrize("state", ["current", "candidate"])
def test_nonaccepted_supplied_valid_arbitrary_proof_stays_legal(state, old_selection):
  values = fixture(); values[2]["state"] = state
  compare(values, old_selection, accepted_binding_digest="f" * 64)


@pytest.mark.parametrize("proof_kind", ["missing", "candidate", "bad-hex", "exact"])
def test_accepted_context_helper_no_proof_and_public_proof_controls(proof_kind, old_selection):
  values = fixture()
  candidate = old_selection["acceptance_context_identity"](*values, host_version="1.0.1", engine="node")
  values[2]["state"] = "accepted"
  context = capabilities.acceptance_context_identity(*values, host_version="1.0.1", engine="node")
  assert context == old_selection["acceptance_context_identity"](*values, host_version="1.0.1", engine="node") and context != candidate
  proof = {"missing": None, "candidate": candidate, "bad-hex": "synthetic bad proof", "exact": context}[proof_kind]
  if proof_kind == "exact": compare(values, old_selection, accepted_binding_digest=proof)
  else:
    with pytest.raises(ConfigError) as old: old_selection["validate_selection"](*values, host_version="1.0.1", engine="node", accepted_binding_digest=proof)
    args, kwargs = data_arguments(values)
    with pytest.raises(ConfigError) as new: capabilities.validate_selection_data(*args, **kwargs, accepted_binding_digest=proof)
    assert new.value.args == old.value.args


@pytest.mark.parametrize("fault", ["source", "missing-source", "resource", "identity", "late-identity", "host", "engine"])
def test_existing_error_categories_and_identity_check_order(fault, old_selection):
  values = fixture(); host, engine = "1.0.1", "node"
  if fault == "source": values[3].metadata["sources"]["pi-host"]["version"] = "1.0.2"
  if fault in ("missing-source", "late-identity"): del values[3].metadata["sources"]["pi-host"]
  if fault == "resource": values[3].metadata["profile_slices"]["pi-base"]["resource_manifest"] = {}
  if fault in ("identity", "late-identity"): values[3].identity = "not-hex"
  if fault == "host": host = "1.0.2"
  if fault == "engine": engine = "bun"
  with pytest.raises((ConfigError, DependencyError)) as old: old_selection["validate_selection"](*values, host_version=host, engine=engine)
  args, kwargs = data_arguments(values); kwargs.update(host_version=host, engine=engine)
  with pytest.raises(type(old.value)) as new: capabilities.validate_selection_data(*args, **kwargs)
  assert new.value.args == old.value.args
  with pytest.raises(type(old.value)) as wrapper: capabilities.validate_selection(*values, host_version=host, engine=engine)
  assert wrapper.value.args == old.value.args


def test_selection_output_frozen_and_independent_after_input_changes(old_selection):
  values = fixture(); result = compare(values, old_selection)
  identity = capabilities.runtime_identity(result, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64")
  values[1]["compression-provider"]["public_entrypoints"].append("native/new")
  values[3].metadata["profile_slices"]["pi-base"]["resource_manifest"]["extensions"][0]["id"] = "changed"
  assert capabilities.runtime_identity(result, runtime_digest="d" * 64, adapter_version="pi-2", platform="linux-x86_64") == identity
  with pytest.raises(FrozenInstanceError): result.state = "accepted"


@pytest.mark.parametrize("change", ["lock", "host", "engine"])
def test_valid_context_change_rejects_old_proof_but_accepts_exact_new_proof(change, old_selection):
  values = fixture()
  values[1]["compression-provider"].update(verified_host_versions=["1.0.1", "1.0.2"], engines=["node", "bun"])
  values[2]["state"] = "accepted"
  stale = old_selection["acceptance_context_identity"](*values, host_version="1.0.1", engine="node")
  host, engine = "1.0.1", "node"
  if change == "lock": values[3].identity = "d" * 64
  if change == "host": host = "1.0.2"
  if change == "engine":
    engine = "bun"
    values[3].metadata["profile_slices"]["pi-base"]["engine"] = engine
  with pytest.raises(ConfigError) as old:
    old_selection["validate_selection"](*values, host_version=host, engine=engine, accepted_binding_digest=stale)
  args, kwargs = data_arguments(values)
  kwargs.update(host_version=host, engine=engine)
  with pytest.raises(ConfigError) as new:
    capabilities.validate_selection_data(*args, **kwargs, accepted_binding_digest=stale)
  assert new.value.args == old.value.args
  current = old_selection["acceptance_context_identity"](*values, host_version=host, engine=engine)
  assert current != stale
  compare(values, old_selection, host_version=host, engine=engine, accepted_binding_digest=current)


def test_version_is_original_shared_regex_without_backend_import(monkeypatch):
  observed = []
  original = builtins.__import__
  def imports(name, *args, **kwargs):
    if name == "pi_dependencies": raise AssertionError("version imported backend")
    result = original(name, *args, **kwargs)
    if name == "pi_lock_resolution": observed.append(result.VERSION)
    return result
  with monkeypatch.context() as guard:
    guard.setattr(builtins, "__import__", imports)
    capabilities._version("1.2.3-beta.1+build")
    with pytest.raises(ConfigError): capabilities._version("latest")
  assert observed == [VERSION, VERSION]


def test_pure_data_invocation_no_io_environment_process_or_factory(monkeypatch, old_selection):
  values = fixture(); args, kwargs = data_arguments(values)
  expected = old_selection["validate_selection"](*values, host_version="1.0.1", engine="node")
  calls = []
  def forbidden(*args, **kwargs):
    calls.append("forbidden access")
    raise AssertionError("selection data accessed IO or old lock path")
  class NoEnvironment(dict):
    def __getitem__(self, key): return forbidden()
    def get(self, *args): return forbidden()
    def __iter__(self): return forbidden()
  with monkeypatch.context() as guard:
    guard.setattr(capabilities, "_resolve_selection", forbidden)
    guard.setattr(capabilities, "validate_selection", forbidden)
    guard.setattr(builtins, "open", forbidden)
    for name in ("open", "read_bytes", "read_text", "stat", "lstat", "resolve", "iterdir"): guard.setattr(Path, name, forbidden)
    for name in ("open", "stat", "lstat", "scandir", "listdir", "getenv", "system"): guard.setattr(os, name, forbidden)
    guard.setattr(os, "environ", NoEnvironment())
    guard.setattr(subprocess, "run", forbidden); guard.setattr(subprocess, "Popen", forbidden)
    assert capabilities.validate_selection_data(*args, **kwargs) == expected
  assert calls == []


def test_frozen_original_baseline_cannot_call_new_kernel_or_public_data(monkeypatch, old_selection):
  values = fixture()
  def forbidden(*args, **kwargs): raise AssertionError("old baseline called new data path")
  monkeypatch.setattr(capabilities, "_resolve_selection_data", forbidden)
  monkeypatch.setattr(capabilities, "validate_selection_data", forbidden)
  assert old_selection["validate_selection"](*values, host_version="1.0.1", engine="node").state == "candidate"
