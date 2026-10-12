"""两代锁可共存；只用虚构来源和假 npm，不启动宿主或联网。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg.pi_dependencies import PiBackend
from agentcfg.pi_vendor import read_inputs
from agentcfg.schema import ConfigError
from agentcfg.process import DependencyError
from test_pi_capability_manifest import binding_repository, runtime_declarations
from test_pi_dependencies import payload


def test_two_families_are_read_independently_and_wrong_schema_never_falls_back(tmp_path):
  workspace, _ = binding_repository(tmp_path); root = workspace.repository
  legacy = PiBackend(profile="pi-fixture").read_lock(root)
  modern = PiBackend(profile="pi-base").read_lock(root)
  assert set(legacy.pairs) == {"pi-fixture"} and set(modern.pairs) == {"pi-base"}
  assert legacy.metadata["schema_version"] == 1 and modern.metadata["schema_version"] == 2
  path = root / "locks/pi-modern/manifest.json"
  path.unlink()
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(root)
  path.write_bytes((root / "locks/pi/manifest.json").read_bytes())
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(root)
  assert PiBackend(profile="pi-fixture").read_lock(root).identity == legacy.identity


def test_modern_reader_does_not_consult_broken_legacy_manifest(tmp_path):
  workspace, _ = binding_repository(tmp_path); root = workspace.repository
  expected = PiBackend(profile="pi-base").read_lock(root).identity
  (root / "locks/pi/manifest.json").write_bytes(b"unselected invalid bytes")
  assert PiBackend(profile="pi-base").read_lock(root).identity == expected
  with pytest.raises(ConfigError): PiBackend(profile="pi-fixture").read_lock(root)


def test_lock_from_other_family_cannot_reach_sync_guard_or_installer(tmp_path, monkeypatch):
  workspace, _ = binding_repository(tmp_path)
  lock = PiBackend(profile="pi-base").read_lock(workspace.repository)
  monkeypatch.setattr("agentcfg.pi_lifecycle.guard", lambda *_: pytest.fail("wrong family must fail before guard"))
  with pytest.raises(ConfigError, match="pi-lock-family"):
    PiBackend().sync(workspace, lock)


def generator_fixture(tmp_path, monkeypatch):
  workspace, manifest = binding_repository(tmp_path); root = workspace.repository
  source = manifest["sources"]["pi-host"]
  bindings = deepcopy(manifest["capability_bindings"])
  bindings["selections"] = {"pi-base": bindings["selections"]["pi-base"]}
  bindings["selections"]["pi-base"]["state"] = "candidate"
  bindings["catalog"]["capabilities"]["native"]["resource_ids"] = ["pi-host"]
  bindings["catalog"]["resource_profiles"]["pi-host"] = ["pi-base"]
  bindings["providers"]["native-provider"]["resource_ids"] = ["pi-host"]
  inputs = {"schema_version": 2, "toolchains": manifest["toolchains"], "platforms": ["linux-x86_64"],
    "sources": {"pi-host": {key: source[key] for key in ("kind", "package", "version", "license_files")}},
    "profiles": {"pi-base": {"engine": "node", "source_ids": ["pi-host"], "entrypoint": "node_modules/synthetic-host/index.js",
      "runtime_files": runtime_declarations(), "ai_package": "synthetic-ai"}},
    "build_steps": [], "capability_bindings": bindings}
  inputs["sources"]["pi-host"]["resources"] = {"extensions": ["extension.js"], "skills": [], "prompts": [], "themes": []}
  (root / "agents/pi/build").mkdir(exist_ok=True)
  (root / "agents/pi/build/recipes-modern.json").write_bytes(payload({"schema_version": 1, "sources": {}}))
  path = root / "agents/pi/dependencies-modern.json"; path.write_bytes(payload(inputs))
  resolution = (root / "locks/pi-modern/pi-base/package-lock.json").read_bytes()
  calls = []
  def resolver(argv, *, cwd, env):
    calls.append(argv)
    if argv == ["node", "--version"]: return manifest["toolchains"]["node"]
    if argv == ["npm", "--version"]: return manifest["toolchains"]["npm"]
    assert argv == ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"]
    (cwd / "package-lock.json").write_bytes(resolution)
    return ""
  monkeypatch.setattr("agentcfg.pi_vendor.checked", resolver)
  return workspace, inputs, path, calls


def test_modern_generation_publishes_only_v2_candidate_with_exact_resource_owner(tmp_path, monkeypatch):
  workspace, _, _, calls = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  sentinel = (root / "locks/pi/manifest.json").read_bytes()
  lock = PiBackend(profile="pi-base").resolve_lock(root)
  assert (root / "locks/pi/manifest.json").read_bytes() == sentinel
  assert set(lock.pairs) == {"pi-base"} and lock.metadata["schema_version"] == 2
  assert lock.validated_bindings["pi-base"].state == "candidate"
  piece = lock.metadata["profile_slices"]["pi-base"]
  assert piece["capability_ids"] == ["native"]
  prefix = str(Path(piece["package_path"]).parent)
  assert prefix.startswith("pi-base-") and len(prefix.removeprefix("pi-base-")) == 64
  assert piece["resource_manifest"]["extensions"] == [{"id": "pi-host", "capability_id": "native",
    "path": prefix + "/node_modules/synthetic-host/extension.js"}]
  assert len(calls) == 3
  monkeypatch.setattr("agentcfg.pi_lifecycle.guard", lambda *_: pytest.fail("candidate cannot activate"))
  with pytest.raises(DependencyError): PiBackend(profile="pi-base").sync(workspace, lock)


@pytest.mark.parametrize("groups,expected", [
  ({"extensions": ["extension.js"], "skills": ["skills/fixture"]}, {"extensions": ["pi-host"], "skills": ["pi-host-skill"]}),
  ({"skills": ["skills/fixture"], "prompts": ["prompt.md"]}, {"skills": ["pi-host"], "prompts": ["pi-host-prompt"]}),
  ({"extensions": ["a.js", "b.js"], "skills": ["skills/fixture"]}, {"extensions": ["pi-host-0", "pi-host-1"], "skills": ["pi-host"]}),
])
def test_modern_producer_single_path_kinds_have_distinct_owned_ids(tmp_path, monkeypatch, groups, expected):
  workspace, inputs, path, _ = generator_fixture(tmp_path, monkeypatch)
  resources = {kind: groups.get(kind, []) for kind in ("extensions", "skills", "prompts", "themes")}
  inputs["sources"]["pi-host"]["resources"] = resources
  names = [name for values in expected.values() for name in values]
  bindings = inputs["capability_bindings"]
  bindings["catalog"]["capabilities"]["native"]["resource_ids"] = names
  bindings["catalog"]["resource_profiles"] = {name: ["pi-base"] for name in names}
  bindings["providers"]["native-provider"]["resource_ids"] = names
  path.write_bytes(payload(inputs))
  lock = PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  rows = lock.metadata["profile_slices"]["pi-base"]["resource_manifest"]
  assert {kind: [row["id"] for row in rows[kind]] for kind in expected} == expected
  assert all(row["capability_id"] == "native" for values in rows.values() for row in values)


def test_modern_producer_keeps_global_duplicate_rejection_for_multi_path_ids(tmp_path, monkeypatch):
  workspace, inputs, path, _ = generator_fixture(tmp_path, monkeypatch)
  inputs["sources"]["pi-host"]["resources"].update(extensions=["a.js", "b.js"], skills=["skills/a", "skills/b"])
  names = ["pi-host-0", "pi-host-1"]
  bindings = inputs["capability_bindings"]
  bindings["catalog"]["capabilities"]["native"]["resource_ids"] = names
  bindings["catalog"]["resource_profiles"] = {name: ["pi-base"] for name in names}
  bindings["providers"]["native-provider"]["resource_ids"] = names
  path.write_bytes(payload(inputs))
  with pytest.raises((ConfigError, DependencyError)):
    PiBackend(profile="pi-base").resolve_lock(workspace.repository)


def test_explicit_current_generation_serializes_and_strictly_rereads_current(tmp_path, monkeypatch):
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  inputs["capability_bindings"]["selections"]["pi-base"]["state"] = "current"
  path.write_bytes(payload(inputs))
  backend = PiBackend(profile="pi-base")
  legacy = (root / "locks/pi/manifest.json").read_bytes()
  lock = backend.resolve_lock(root, current_profiles=("pi-base",))
  published = json.loads((root / "locks/pi-modern/manifest.json").read_bytes())
  assert published["capability_bindings"]["selections"]["pi-base"]["state"] == "current"
  assert lock.validated_bindings["pi-base"].state == "current"
  reread = backend.read_lock(root)
  assert reread.identity == lock.identity and reread.pairs == lock.pairs
  assert reread.validated_bindings["pi-base"].state == "current"
  assert (root / "locks/pi/manifest.json").read_bytes() == legacy and len(calls) == 3
  assert json.loads(path.read_bytes()) == inputs


class CurrentTupleSubclass(tuple): pass
class CurrentStringSubclass(str): pass


@pytest.mark.parametrize("selected", [None, True, "pi-base", ["pi-base"], ("pi-base", "pi-base"),
  ("synthetic-private-argument",), (CurrentStringSubclass("pi-base"),), CurrentTupleSubclass(("pi-base",)), ("pi-full",)])
def test_current_profile_parameter_rejects_before_any_resolver(tmp_path, monkeypatch, selected):
  workspace, _, _, calls = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  with pytest.raises(ConfigError, match="pi-build-current-profiles-invalid") as error:
    PiBackend(profile="pi-base").resolve_lock(root, current_profiles=selected)
  assert "synthetic-private-argument" not in str(error.value) and calls == []
  assert (root / "locks/pi-modern/manifest.json").read_bytes() == before


def test_current_profile_parameter_rejects_legacy_family_before_any_resolver(tmp_path, monkeypatch):
  workspace, _, _, calls = generator_fixture(tmp_path, monkeypatch)
  with pytest.raises(ConfigError, match="pi-build-current-profiles-invalid"):
    PiBackend(profile="pi-fixture").resolve_lock(workspace.repository, current_profiles=("pi-base",))
  assert calls == []


@pytest.mark.parametrize("fault", ["selected-candidate", "unselected-current", "accepted-selected", "accepted-unselected", "unverified", "wrong-engine"])
def test_current_compatibility_and_state_fail_before_tools_or_npm(tmp_path, monkeypatch, fault):
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  selection = inputs["capability_bindings"]["selections"]["pi-base"]
  selection["state"] = "current"
  selected = ("pi-base",)
  if fault == "selected-candidate": selection["state"] = "candidate"
  if fault == "unselected-current": selected = ()
  if fault.startswith("accepted"):
    selection["state"] = "accepted"
    if fault == "accepted-unselected": selected = ()
  provider = inputs["capability_bindings"]["providers"]["native-provider"]
  if fault == "unverified":
    provider["candidate_host_versions"] = provider["verified_host_versions"]
    provider["verified_host_versions"] = []
  if fault == "wrong-engine": provider["engines"] = ["bun"]
  path.write_bytes(payload(inputs))
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  with pytest.raises(ConfigError, match="pi-build-bindings-invalid"):
    PiBackend(profile="pi-base").resolve_lock(root, current_profiles=selected)
  assert calls == [] and (root / "locks/pi-modern/manifest.json").read_bytes() == before


def test_current_license_failure_preserves_all_old_lock_bytes_and_readback(tmp_path, monkeypatch):
  from agentcfg.pi_dependencies import digest
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  backend = PiBackend(profile="pi-base"); old = backend.resolve_lock(root)
  original_inputs = path.read_bytes()
  lock_root = root / "locks/pi-modern"
  before = {str(p.relative_to(lock_root)): p.read_bytes() for p in lock_root.rglob("*") if p.is_file()}
  profile = inputs["profiles"]["pi-base"]
  registry_name = "agents/pi/build/licenses/pi-modern/REGISTRY-current.json"
  registry = json.loads((root / "agents/pi/build/licenses/pi-modern/REGISTRY.json").read_bytes())
  evidence_name = "agents/pi/build/licenses/pi-modern/current-unresolved.txt"
  evidence = b"Synthetic missing upstream license body\n"
  (root / evidence_name).write_bytes(evidence)
  registry["packages"][0].update(status="body-scope-unresolved", archive_files=[], supplemental_files=[],
    evidence_files=[{"path": "licenses/pi-modern/current-unresolved.txt", "sha256": digest(evidence)}])
  (root / registry_name).write_bytes(payload(registry))
  for row in profile["runtime_files"]:
    if row["path"] == "licenses/pi-modern/REGISTRY.json":
      row.update(source=registry_name, path="licenses/pi-modern/REGISTRY-current.json")
  profile["runtime_files"].append({"source": evidence_name, "path": "licenses/pi-modern/current-unresolved.txt", "transform": "copy"})
  inputs["capability_bindings"]["selections"]["pi-base"]["state"] = "current"
  path.write_bytes(payload(inputs)); calls.clear()
  with pytest.raises(ConfigError, match="pi-license-bundle-invalid"):
    backend.resolve_lock(root, current_profiles=("pi-base",))
  assert len(calls) == 3
  assert {str(p.relative_to(lock_root)): p.read_bytes() for p in lock_root.rglob("*") if p.is_file()} == before
  # 新声明及新增build材料使旧recipe过期；测试恢复原输入后再证明旧发布锁可读。
  with pytest.raises(ConfigError): backend.read_lock(root)
  path.write_bytes(original_inputs)
  (root / registry_name).unlink()
  (root / evidence_name).unlink()
  reread = backend.read_lock(root)
  assert reread.identity == old.identity and reread.pairs == old.pairs
  assert reread.validated_bindings["pi-base"].state == "candidate"


@pytest.mark.parametrize("fault", ["current", "accepted", "unknown", "wrong-profile", "missing-input", "missing-recipe"])
def test_modern_inputs_fail_before_resolver_without_falling_back(tmp_path, monkeypatch, fault):
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  if fault in ("current", "accepted"):
    inputs["capability_bindings"]["selections"]["pi-base"]["state"] = fault
  if fault == "unknown": inputs["capability_bindings"]["providers"]["native-provider"]["raw_token"] = "synthetic-secret"
  if fault == "wrong-profile": inputs["profiles"]["pi-fixture"] = inputs["profiles"].pop("pi-base")
  path.write_bytes(payload(inputs))
  if fault == "missing-input": path.unlink()
  if fault == "missing-recipe": (root / "agents/pi/build/recipes-modern.json").unlink()
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  with pytest.raises(ConfigError) as error: PiBackend(profile="pi-base").resolve_lock(root)
  assert "synthetic-secret" not in str(error.value) and calls == []
  assert (root / "locks/pi-modern/manifest.json").read_bytes() == before


@pytest.mark.parametrize("fault", ["source-identity", "resource-owner"])
def test_resolved_source_or_resource_mismatch_preserves_published_lock(tmp_path, monkeypatch, fault):
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  provider = inputs["capability_bindings"]["providers"]["native-provider"]
  if fault == "source-identity": provider["source_identity"] = "a" * 64
  if fault == "resource-owner": provider["resource_ids"] = []
  path.write_bytes(payload(inputs))
  old = (root / "locks/pi-modern/manifest.json").read_bytes()
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").resolve_lock(root)
  assert len(calls) == 3 and (root / "locks/pi-modern/manifest.json").read_bytes() == old


def test_interrupted_modern_publish_keeps_previous_pairs_readable(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  workspace, _, _, _ = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  backend = PiBackend(profile="pi-base")
  first = backend.resolve_lock(root)
  old_manifest = (root / "locks/pi-modern/manifest.json").read_bytes()
  old_pair = first.pairs["pi-base"]
  original_resolver = __import__("agentcfg.pi_vendor", fromlist=["checked"]).checked
  def changed_resolver(argv, *, cwd, env):
    result = original_resolver(argv, cwd=cwd, env=env)
    if argv[0:2] == ["npm", "install"]:
      path = cwd / "package-lock.json"; document = json.loads(path.read_bytes())
      document["name"] = "synthetic-new-resolution"
      path.write_bytes(payload(document))
    return result
  monkeypatch.setattr("agentcfg.pi_vendor.checked", changed_resolver)
  original_write = Tree.write_state
  def fail_manifest(tree, name, content, *args, **kwargs):
    if name == "manifest.json": raise OSError("synthetic publish interruption")
    return original_write(tree, name, content, *args, **kwargs)
  monkeypatch.setattr(Tree, "write_state", fail_manifest)
  with pytest.raises(OSError): backend.resolve_lock(root)
  assert (root / "locks/pi-modern/manifest.json").read_bytes() == old_manifest
  reread = backend.read_lock(root)
  assert reread.identity == first.identity and reread.pairs["pi-base"] == old_pair


def test_changed_recipe_during_resolution_cannot_be_published_as_the_old_selection(tmp_path, monkeypatch):
  import agentcfg.pi_vendor as vendor
  workspace, inputs, path, _ = generator_fixture(tmp_path, monkeypatch); root = workspace.repository
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  original = vendor.checked
  def changing(argv, *, cwd, env):
    result = original(argv, cwd=cwd, env=env)
    if argv[0:2] == ["npm", "install"]:
      inputs["toolchains"]["npm"] = "99.0.0"
      path.write_bytes(payload(inputs))
    return result
  monkeypatch.setattr(vendor, "checked", changing)
  with pytest.raises(ConfigError, match="pi-build-input-changed"):
    PiBackend(profile="pi-base").resolve_lock(root)
  assert (root / "locks/pi-modern/manifest.json").read_bytes() == before


def asset_generator_fixture(tmp_path, monkeypatch):
  from agentcfg.pi_dependencies import digest
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  root = workspace.repository
  raw = b"synthetic vendored raw asset\n"
  asset = root / "locks/pi-modern/vendor/fixture.data"
  asset.write_bytes(raw)
  license_path = "agents/pi/build/licenses/fixture-asset/LICENSE"
  (root / license_path).parent.mkdir(parents=True)
  (root / license_path).write_text("Synthetic asset license\n")
  # 未选资产也属于 aggregate read_lock 的声明闭包；host 绑定保持真实完整校验。
  inputs["sources"]["fixture-asset"] = {"kind": "asset", "format": "raw", "platform": "all",
    "url": "https://example.invalid/fixture.data", "target": "data/fixture.data", "size": len(raw),
    "archive_digest": digest(raw), "vendor_path": "vendor/fixture.data", "license_files": [license_path]}
  path.write_bytes(payload(inputs))
  return workspace, inputs, path, calls, asset, raw


@pytest.mark.parametrize("fault", ["missing", "digest", "size", "declared-size", "other-family"])
def test_bad_declared_asset_preserves_published_candidate_before_any_npm(tmp_path, monkeypatch, fault):
  workspace, inputs, path, calls, asset, raw = asset_generator_fixture(tmp_path, monkeypatch)
  backend = PiBackend(profile="pi-base"); root = workspace.repository
  first = backend.resolve_lock(root)
  manifest = (root / "locks/pi-modern/manifest.json").read_bytes()
  old_pair = first.pairs["pi-base"]
  calls.clear()
  if fault in ("missing", "other-family"): asset.unlink()
  if fault == "digest": asset.write_bytes(b"X" * len(raw))
  if fault == "size": asset.write_bytes(raw + b"X")
  if fault == "declared-size":
    inputs["sources"]["fixture-asset"]["size"] += 1
    path.write_bytes(payload(inputs))
  if fault == "other-family":
    legacy_asset = root / "locks/pi/vendor/fixture.data"
    legacy_asset.parent.mkdir(exist_ok=True); legacy_asset.write_bytes(raw)
  with pytest.raises(ConfigError, match="^配置校验失败: pi-build-asset-input$"):
    backend.resolve_lock(root)
  assert calls == []
  assert (root / "locks/pi-modern/manifest.json").read_bytes() == manifest
  for key, expected in zip(("package_path", "lock_path"), old_pair):
    assert (root / "locks/pi-modern" / first.metadata["profile_slices"]["pi-base"][key]).read_bytes() == expected
  with pytest.raises(ConfigError, match="pi-lock-missing-or-stale"):
    PiBackend(family="modern").read_lock(root)
  # 损坏的资产使旧锁暂不可读；只恢复本测试破坏的输入后再核验旧身份。
  asset.write_bytes(raw)
  if fault == "declared-size":
    inputs["sources"]["fixture-asset"]["size"] = len(raw)
    path.write_bytes(payload(inputs))
  reread = PiBackend(family="modern").read_lock(root)
  assert reread.identity == first.identity and reread.pairs["pi-base"] == old_pair


def test_asset_changed_during_npm_cannot_publish_manifest_or_pairs(tmp_path, monkeypatch):
  import agentcfg.pi_vendor as vendor
  workspace, _, _, calls, asset, raw = asset_generator_fixture(tmp_path, monkeypatch)
  root = workspace.repository; backend = PiBackend(profile="pi-base")
  first = backend.resolve_lock(root)
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  published = {item.relative_to(root / "locks/pi-modern").as_posix(): item.read_bytes()
    for item in (root / "locks/pi-modern").rglob("*") if item.is_file()}
  pair = first.pairs["pi-base"]
  original = vendor.checked; calls.clear()
  def changing(argv, *, cwd, env):
    result = original(argv, cwd=cwd, env=env)
    if argv[:2] == ["npm", "install"]:
      asset.write_bytes(b"X" * len(raw))
      lock_path = cwd / "package-lock.json"
      resolution = json.loads(lock_path.read_bytes()); resolution["name"] = "changed-asset-resolution"
      lock_path.write_bytes(payload(resolution))
    return result
  monkeypatch.setattr(vendor, "checked", changing)
  with pytest.raises(ConfigError, match="^配置校验失败: pi-build-asset-input$"): backend.resolve_lock(root)
  assert len(calls) == 3
  assert (root / "locks/pi-modern/manifest.json").read_bytes() == before
  assert {item.relative_to(root / "locks/pi-modern").as_posix(): item.read_bytes()
    for item in (root / "locks/pi-modern").rglob("*") if item.is_file() and item != asset} == {
      name: content for name, content in published.items() if name != "vendor/fixture.data"}
  for key, expected in zip(("package_path", "lock_path"), pair):
    assert (root / "locks/pi-modern" / first.metadata["profile_slices"]["pi-base"][key]).read_bytes() == expected
  with pytest.raises(ConfigError, match="pi-lock-missing-or-stale"):
    PiBackend(family="modern").read_lock(root)
  asset.write_bytes(raw)
  reread = PiBackend(family="modern").read_lock(root)
  assert reread.identity == first.identity and reread.pairs["pi-base"] == pair
