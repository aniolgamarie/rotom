"""序列化能力锁只使用虚构来源与假安装器。"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import pytest

from agentcfg.pi_dependencies import PiBackend, PiLock, digest
from agentcfg.pi_capabilities import source_identity, acceptance_context_identity
from agentcfg.schema import ConfigError
from agentcfg.process import DependencyError
from test_pi_dependencies import ready_sync_fixture, payload, _write_manifest as _write_selected_manifest, fake_installer, synthetic_runtime_sources


def runtime_declarations(platform="linux-x86_64"):
  rows = [{"source": "agents/pi/runtime/official-launch.ts", "path": "runtime/official-launch.mjs", "transform": "ts-module"}]
  rows.extend({"source": name, "path": "supervisor/" + name, "transform": "copy"} for name in (
    "scripts/pi-supervisor.py", "scripts/pi-control.py", "scripts/pi-exec.py", "scripts/pi-file-operation.py",
    "scripts/pi-project-check", "scripts/pi-shell.py", "src/agentcfg/pi_host.py"))
  rows.extend({"source": "agents/pi/schemas/" + name + ".schema.json",
    "path": "supervisor/agents/pi/schemas/" + name + ".schema.json", "transform": "copy"} for name in (
      "process-identity", "execution-lease", "workspace-write-lease", "termination-evidence", "stop-recovery-plan", "stop-recovery", "permission-policy", "operation-grant", "options"))
  if platform.startswith("linux-"):
    rows.extend({"source": name, "path": "supervisor/" + name, "transform": "copy"} for name in (
      "scripts/pi-namespace-exec.py", "src/agentcfg/pi_pid_namespace.py", "src/agentcfg/pi_assets.py"))
  rows.append({"source": "agents/pi/build/licenses/pi-modern/REGISTRY.json", "path": "licenses/pi-modern/REGISTRY.json", "transform": "copy"})
  return rows


def _write_manifest(root, manifest):
  _write_selected_manifest(root, manifest, family="modern")


def binding_repository(tmp_path):
  workspace, manifest = ready_sync_fixture(tmp_path)
  root = workspace.repository; lock_root = root / "locks/pi-modern"
  import shutil
  shutil.copytree(root / "locks/pi", lock_root)
  shutil.copyfile(root / "agents/pi/dependencies.json", root / "agents/pi/dependencies-modern.json")
  from agentcfg.pi_dependencies import recipe_digest
  (lock_root / "pi-fixture").rename(lock_root / "pi-base")
  piece = manifest["profile_slices"].pop("pi-fixture")
  for key in ("package_path", "lock_path", "entrypoint"): piece[key] = piece[key].replace("pi-fixture/", "pi-base/")
  piece["source_ids"] = ["pi-host"]; piece["capability_ids"] = ["native"]
  # 仅测试安装清单：虚构入口不执行，也不代表真实Python/SDK传递闭包已验收。
  (root / "agents/pi/runtime/official-launch.ts").write_text("// synthetic modern launcher, never executed\n")
  from agentcfg.pi_runtime_files import lock_files
  declarations = runtime_declarations()
  synthetic_runtime_sources(root, declarations)
  piece.update(runtime_files=lock_files(root, declarations), ai_package="synthetic-ai")
  import json
  resolution_path = lock_root / piece["lock_path"]
  resolution = json.loads(resolution_path.read_bytes())
  resolution["packages"]["node_modules/synthetic-ai"] = {"version": "1.0.2", "resolved": "https://example.invalid/ai.tgz", "integrity": manifest["sources"]["host"]["integrity"]}
  resolution_path.write_bytes(payload(resolution)); piece["package_lock_digest"] = digest(payload(resolution))
  from agentcfg.pi_license_bundle import projection
  import hashlib
  registry_rows = []
  for row in projection(resolution):
    raw = ('{"name":"%s","version":"%s","license":"MIT"}' % (row["name"], row["version"])).encode()
    registry_rows.append({**row, "package_json_sha256": hashlib.sha256(raw).hexdigest(), "declared_license": "MIT",
      "status": "archive-body", "archive_files": [{"path": "LICENSE", "sha256": hashlib.sha256(b"synthetic original MIT body\n").hexdigest()}],
      "supplemental_files": [], "evidence_files": []})
  (root / "agents/pi/build/licenses/pi-modern/REGISTRY.json").write_bytes(payload({"schema_version": 1, "platform": "linux-x86_64", "packages": registry_rows}))
  piece["runtime_files"] = lock_files(root, declarations)
  manifest["sources"]["pi-host"] = manifest["sources"].pop("host")
  full = deepcopy(piece)
  for key in ("package_path", "lock_path", "entrypoint"): full[key] = full[key].replace("pi-base/", "pi-full/")
  import shutil
  shutil.copytree(lock_root / "pi-base", lock_root / "pi-full")
  full["source_ids"].append("full-feature"); full["capability_ids"].append("extra")
  vendor = lock_root / "vendor/full.tgz"; vendor.parent.mkdir(); vendor.write_bytes(b"synthetic full-only archive")
  manifest["sources"]["full-feature"] = {"kind": "local", "package": "synthetic-full", "version": "1.0.0", "vendor_path": "vendor/full.tgz",
    "archive_digest": digest(vendor.read_bytes()), "source_path": "agents/pi/packages/fixture", "source_tree_digest": "a" * 64, "license_files": []}
  import json
  full_package = json.loads((lock_root / full["package_path"]).read_bytes())
  full_package["dependencies"]["synthetic-full"] = "file:../vendor/full.tgz"
  full_resolution = json.loads((lock_root / full["lock_path"]).read_bytes())
  full_resolution["packages"][""]["dependencies"] = full_package["dependencies"]
  full_resolution["packages"]["node_modules/synthetic-full"] = {"version": "1.0.0", "resolved": "file:../vendor/full.tgz", "integrity": manifest["sources"]["pi-host"]["integrity"]}
  for key, value in (("package_path", full_package), ("lock_path", full_resolution)):
    (lock_root / full[key]).write_bytes(payload(value))
  full["package_json_digest"] = digest(payload(full_package)); full["package_lock_digest"] = digest(payload(full_resolution))
  manifest["profile_slices"] = {"pi-base": piece, "pi-full": full}
  capability = {"profiles": ["pi-base", "pi-full"], "required": True, "contract_version": "1", "owner_domain": "native", "single_owner": True,
    "config_fields": [], "state_owners": [], "source_ids": ["pi-host"], "resource_ids": []}
  catalog = {"schema_version": 1, "revision": 1, "capabilities": {"native": capability}, "source_profiles": {"pi-host": ["pi-base", "pi-full"]}, "resource_profiles": {}}
  provider = {"provider_id": "native-provider", "capability_id": "native", "source_id": "pi-host", "source_version": "1.0.0",
    "source_identity": source_identity(manifest["sources"]["pi-host"]), "contract_version": "1", "verified_host_versions": ["1.0.0"], "engines": ["node"],
    "requires": [], "conflicts": [], "public_entrypoints": ["native/sdk"], "config_fields": [], "state_owners": [], "resource_ids": [],
    "migration_refs": ["docs/fake.md"], "uninstall_refs": ["docs/fake.md"], "rollback_refs": ["docs/fake.md"]}
  extra_capability = deepcopy(capability); extra_capability.update(profiles=["pi-full"], owner_domain="extra", source_ids=["full-feature"])
  catalog["capabilities"]["extra"] = extra_capability; catalog["source_profiles"]["full-feature"] = ["pi-full"]
  extra_provider = deepcopy(provider); extra_provider.update(provider_id="extra-provider", capability_id="extra", source_id="full-feature",
    source_identity=source_identity(manifest["sources"]["full-feature"]))
  selections = {name: {"schema_version": 1, "profile": name, "revision": 1, "source_revision": 1, "state": "current",
    "bindings": [{"capability_id": "native", "provider_id": "native-provider"}]} for name in manifest["profile_slices"]}
  selections["pi-full"]["bindings"].append({"capability_id": "extra", "provider_id": "extra-provider"})
  manifest.update(schema_version=2, capability_bindings={"schema_version": 1, "catalog": catalog, "providers": {"native-provider": provider, "extra-provider": extra_provider}, "selections": selections})
  manifest["recipe_digest"] = recipe_digest(root, family="modern")
  # 现代测试源码也进入旧配方的宽摘要；同步测试用旧锁，保持独立家族正例有效。
  legacy = json.loads((root / "locks/pi/manifest.json").read_bytes())
  legacy["recipe_digest"] = recipe_digest(root)
  _write_selected_manifest(root, legacy)
  workspace.profile = "pi-base"; _write_manifest(root, manifest)
  return workspace, manifest


def proof(manifest, profile="pi-base"):
  values = manifest["capability_bindings"]
  return acceptance_context_identity(values["catalog"], values["providers"], values["selections"][profile], PiLock(manifest["identity"], manifest, {}), host_version="1.0.0", engine="node")


def test_current_v2_consumed_and_base_does_not_read_full_bodies(tmp_path, monkeypatch):
  workspace, manifest = binding_repository(tmp_path)
  for name in ("package_path", "lock_path"): (workspace.repository / "locks/pi-modern" / manifest["profile_slices"]["pi-full"][name]).unlink()
  (workspace.repository / "locks/pi-modern/vendor/full.tgz").unlink()
  manifest["capability_bindings"]["selections"]["pi-full"]["state"] = "accepted"
  _write_manifest(workspace.repository, manifest)
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  assert set(lock.validated_bindings) == {"pi-base"}
  assert lock.validated_bindings["pi-base"].state == "current"
  calls = []; monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls))
  assert backend.sync(workspace, lock)["installed"] is True and len(calls) == 3
  with pytest.raises(ConfigError): PiBackend(family="modern").read_lock(workspace.repository)


@pytest.mark.parametrize("fault", ["missing", "unknown", "provider-unknown", "selection-unknown", "keys", "profile", "bool", "float", "capabilities", "host", "full-source", "accepted", "v1-binding", "v1-reserved"])
def test_binding_manifest_fails_closed(tmp_path, fault):
  workspace, manifest = binding_repository(tmp_path); bindings = manifest["capability_bindings"]
  if fault == "missing": del manifest["capability_bindings"]
  if fault == "unknown": bindings["authorization"] = "synthetic-secret"
  if fault == "provider-unknown": bindings["providers"]["native-provider"]["auth"] = "synthetic-secret"
  if fault == "selection-unknown": bindings["selections"]["pi-full"]["auth"] = "synthetic-secret"
  if fault == "keys": del bindings["selections"]["pi-full"]
  if fault == "profile": bindings["selections"]["pi-base"]["profile"] = "pi-full"
  if fault == "bool": bindings["schema_version"] = True
  if fault == "float": manifest["schema_version"] = 2.0
  if fault == "capabilities": manifest["profile_slices"]["pi-base"]["capability_ids"] = ["extra"]
  if fault == "host": bindings["providers"]["native-provider"]["verified_host_versions"] = ["1.0.1"]
  if fault == "full-source": bindings["catalog"]["source_profiles"]["pi-host"] = ["pi-full"]
  if fault == "accepted": bindings["selections"]["pi-base"]["state"] = "accepted"
  if fault.startswith("v1"): manifest["schema_version"] = 1
  if fault == "v1-reserved": del manifest["capability_bindings"]
  _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError) as error: PiBackend(profile="pi-base").read_lock(workspace.repository)
  assert error.value.exit_code == 2 and "synthetic-secret" not in str(error.value)


def test_accepted_requires_exact_external_proof(tmp_path):
  workspace, manifest = binding_repository(tmp_path)
  manifest["capability_bindings"]["selections"]["pi-base"]["state"] = "accepted"; _write_manifest(workspace.repository, manifest)
  backend = PiBackend(profile="pi-base")
  with pytest.raises(ConfigError): backend.read_lock(workspace.repository, accepted_binding_digests={"pi-base": "a" * 64})
  lock = backend.read_lock(workspace.repository, accepted_binding_digests={"pi-base": proof(manifest)})
  assert lock.validated_bindings["pi-base"].state == "accepted"
  assert backend.runtime_identity(workspace, lock)


@pytest.mark.parametrize("fault", ["selection", "provider", "slice", "identity", "cache", "pair", "downgrade"])
def test_runtime_rechecks_bound_context(tmp_path, fault):
  workspace, manifest = binding_repository(tmp_path); backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  if fault == "selection": lock.metadata["capability_bindings"]["selections"]["pi-base"]["revision"] += 1
  if fault == "provider": lock.metadata["capability_bindings"]["providers"]["native-provider"]["public_entrypoints"] = ["another/sdk"]
  if fault == "slice": lock.metadata["profile_slices"]["pi-base"]["entrypoint"] = "pi-base/other.js"
  if fault == "identity": lock = replace(lock, identity="a" * 64)
  if fault == "cache": lock = replace(lock, validated_bindings={})
  if fault == "pair": lock = replace(lock, pairs={"pi-base": (b"{}", lock.pairs["pi-base"][1])})
  if fault == "downgrade": lock.metadata["schema_version"] = 1
  with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)


def test_candidate_cannot_activate_before_any_write(tmp_path, monkeypatch):
  workspace, manifest = binding_repository(tmp_path); manifest["capability_bindings"]["selections"]["pi-base"]["state"] = "candidate"; _write_manifest(workspace.repository, manifest)
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  assert backend.runtime_identity(workspace, lock)
  calls = []; monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls))
  monkeypatch.setattr("agentcfg.pi_lifecycle.guard", lambda *_: pytest.fail("candidate must fail before guard"))
  with pytest.raises(DependencyError) as error: backend.sync(workspace, lock)
  assert error.value.exit_code == 5 and calls == []


def test_lock_pairs_and_binding_snapshots_cannot_be_injected(tmp_path):
  workspace, _ = binding_repository(tmp_path)
  lock = PiBackend(profile="pi-base").read_lock(workspace.repository)
  with pytest.raises(TypeError): lock.pairs["pi-full"] = lock.pairs["pi-base"]
  with pytest.raises(TypeError): lock.validated_bindings["pi-full"] = lock.validated_bindings["pi-base"]
  workspace.profile = "pi-full"
  with pytest.raises(ConfigError): PiBackend(family="modern").runtime_identity(workspace, lock)
  pairs = dict(lock.pairs); bindings = dict(lock.validated_bindings)
  snapshot = PiLock(lock.identity, lock.metadata, pairs, bindings)
  pairs["pi-full"] = pairs["pi-base"]; bindings.clear()
  assert set(snapshot.pairs) == {"pi-base"} and set(snapshot.validated_bindings) == {"pi-base"}


@pytest.mark.parametrize("fault", ["missing", "downgrade", "unknown", "profile", "selection", "catalog", "bindings", "lock", "slice", "binding_context", "runtime", "adapter_version", "platform", "float"])
def test_v2_sealed_receipt_detects_binding_drift(tmp_path, monkeypatch, fault):
  import json
  from agentcfg.storage import Tree
  workspace, _ = binding_repository(tmp_path); backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer([]))
  result = backend.sync(workspace, lock); root = backend.root(workspace, result["identity"])
  assert backend.status(workspace, result["identity"]) == "installed"
  receipt = json.loads((root / ".agentcfg-receipt.json").read_bytes())
  assert receipt["schema_version"] == 2
  if fault == "missing": del receipt["binding_identity"]
  elif fault == "downgrade": receipt["schema_version"] = 1; del receipt["binding_identity"]
  elif fault == "unknown": receipt["binding_identity"]["approval"] = True
  elif fault == "float": receipt["schema_version"] = 2.0
  else: receipt["binding_identity"][fault] = "pi-full" if fault == "profile" else "darwin-arm64" if fault == "platform" else "a" * 64
  with Tree(root) as tree: tree.write_state(".agentcfg-receipt.json", payload(receipt))
  assert backend.status(workspace, result["identity"]) == "damaged"



def test_global_v2_verifies_both_selected_bindings(tmp_path):
  workspace, _ = binding_repository(tmp_path)
  lock = PiBackend(family="modern").read_lock(workspace.repository)
  assert set(lock.pairs) == set(lock.validated_bindings) == {"pi-base", "pi-full"}
  workspace.profile = "pi-full"
  assert PiBackend(family="modern").runtime_identity(workspace, lock)


@pytest.mark.parametrize("fault", ["source", "provider", "state"])
def test_old_proof_cannot_accept_new_context(tmp_path, fault):
  workspace, manifest = binding_repository(tmp_path); bindings = manifest["capability_bindings"]
  bindings["selections"]["pi-base"]["state"] = "candidate" if fault == "state" else "accepted"; _write_manifest(workspace.repository, manifest)
  old = proof(manifest)
  if fault == "source":
    manifest["sources"]["pi-host"]["version"] = "1.0.1"
    provider = bindings["providers"]["native-provider"]
    provider.update(source_version="1.0.1", source_identity=source_identity(manifest["sources"]["pi-host"]), verified_host_versions=["1.0.1"])
  if fault == "provider": bindings["providers"]["native-provider"]["public_entrypoints"] = ["other/sdk"]
  if fault == "state": bindings["selections"]["pi-base"]["state"] = "accepted"
  _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(workspace.repository, accepted_binding_digests={"pi-base": old})


def test_reread_changed_current_context_has_new_identity(tmp_path):
  workspace, manifest = binding_repository(tmp_path); backend = PiBackend(profile="pi-base")
  old = backend.runtime_identity(workspace, backend.read_lock(workspace.repository))
  manifest["capability_bindings"]["providers"]["native-provider"]["public_entrypoints"] = ["other/sdk"]
  _write_manifest(workspace.repository, manifest)
  assert backend.runtime_identity(workspace, backend.read_lock(workspace.repository)) != old


def test_missing_host_and_workspace_capability_mismatch_rejected(tmp_path):
  workspace, manifest = binding_repository(tmp_path); backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  workspace.resolved = SimpleNamespace(data={"profile": {"plugins": ["extra"], "agent_options": {}}})
  with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)
  del workspace.resolved
  manifest["sources"]["not-host"] = manifest["sources"].pop("pi-host")
  manifest["profile_slices"]["pi-base"]["source_ids"] = ["not-host"]
  manifest["profile_slices"]["pi-full"]["source_ids"] = ["not-host", "full-feature"]
  _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError): backend.read_lock(workspace.repository)


# 保留既有迁移和已发布配置的回归约束。

import json
from pathlib import Path
import tomllib

from agentcfg.pi_catalog import validate_catalog


ROOT = Path(__file__).resolve().parents[1]


def test_migration_catalog_has_explicit_source_and_disposition_for_every_capability():
  path = ROOT / "agents/pi/migration/capabilities.toml"
  assert path.is_file(), "migration capability decisions must be recorded before importing resources"
  value = tomllib.loads(path.read_text())
  catalog = {"schema_version": value["schema_version"], "sources": value["sources"],
    "capabilities": [{key: row[key] for key in ("id", "kind", "source_id", "entrypoints", "requires", "conflicts", "control_domain", "supported_engines", "evidence_cases")} for row in value["capabilities"]]}
  items = validate_catalog(catalog)
  assert {"task-keeper", "model-delegate", "pi-subagents"} <= items.keys()
  assert all(row["disposition"] in {"keep", "adapt", "merge", "replace", "optional", "exclude"} and row["reason"] for row in value["capabilities"])
  assert not any("run-codex.sh" in row.get("target_path", "") for row in value["capabilities"])


def test_seven_codex_roles_map_to_new_presets():
  path = ROOT / "agents/pi/migration/role-map.json"
  assert path.is_file(), "role migration mapping missing"
  value = json.loads(path.read_text())
  assert len(value["roles"]) == 7
  assert {row["preset"] for row in value["roles"].values()} == {"general", "context", "challenge", "plan", "research", "review", "scout"}
  assert all(row["tool"] == "model_delegate" and row["backend"] == "codex" and row["register_legacy_role"] is False for row in value["roles"].values())


def test_ordinary_profiles_select_the_promised_todo_loop_guard_and_footer_baseline():
  import tomllib
  from pathlib import Path
  root = Path(__file__).resolve().parents[1]
  for profile in ("pi-default", "pi-codex", "pi-cursor"):
    value = tomllib.loads((root / "profiles" / (profile + ".toml")).read_text())
    assert {"pi-subagents", "pi-permissions", "model-delegate", "pi-todo", "loop-guard", "colorful-footer"} <= set(value["plugins"])
    assert "task-keeper" not in value["plugins"]


def test_all_published_plugin_catalog_entries_have_real_dependency_and_resource_sources():
  catalog = tomllib.loads((ROOT / "agents/pi/plugins.toml").read_text())["plugins"]
  sources = json.loads((ROOT / "agents/pi/dependencies.json").read_text())["sources"]
  assert set(catalog) <= set(sources)
  for key in catalog:
    assert any(sources[key]["resources"].values()), key


@pytest.mark.parametrize("fault", ["declared-version", "installed-version", "resolved", "integrity"])
def test_bound_npm_source_must_match_the_actual_direct_resolution(tmp_path, fault):
  import base64
  workspace, manifest = binding_repository(tmp_path)
  piece = manifest["profile_slices"]["pi-base"]
  root = workspace.repository / "locks/pi-modern"
  package = json.loads((root / piece["package_path"]).read_bytes())
  resolution = json.loads((root / piece["lock_path"]).read_bytes())
  name = manifest["sources"]["pi-host"]["package"]
  actual = resolution["packages"]["node_modules/" + name]
  if fault == "declared-version":
    package["dependencies"][name] = "1.0.9"
    resolution["packages"][""]["dependencies"][name] = "1.0.9"
  if fault == "installed-version": actual["version"] = "1.0.9"
  if fault == "resolved": actual["resolved"] = "https://example.invalid/unselected-source.tgz"
  if fault == "integrity": actual["integrity"] = "sha512-" + base64.b64encode(b"z" * 64).decode()
  for path_key, digest_key, value in (("package_path", "package_json_digest", package), ("lock_path", "package_lock_digest", resolution)):
    raw = payload(value); (root / piece[path_key]).write_bytes(raw); piece[digest_key] = digest(raw)
  _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(workspace.repository)


def test_bound_local_source_cannot_resolve_to_another_profiles_archive(tmp_path):
  workspace, manifest = binding_repository(tmp_path)
  root = workspace.repository / "locks/pi-modern"
  other = deepcopy(manifest["sources"]["full-feature"])
  other.update(package="synthetic-other", vendor_path="vendor/other.tgz")
  (root / other["vendor_path"]).write_bytes(b"unselected archive")
  other["archive_digest"] = digest(b"unselected archive")
  manifest["sources"]["unselected-source"] = other
  piece = manifest["profile_slices"]["pi-full"]
  package = json.loads((root / piece["package_path"]).read_bytes())
  resolution = json.loads((root / piece["lock_path"]).read_bytes())
  package["dependencies"]["synthetic-full"] = "file:../vendor/other.tgz"
  resolution["packages"][""]["dependencies"] = package["dependencies"]
  resolution["packages"]["node_modules/synthetic-full"]["resolved"] = "file:../vendor/other.tgz"
  for path_key, digest_key, value in (("package_path", "package_json_digest", package), ("lock_path", "package_lock_digest", resolution)):
    raw = payload(value); (root / piece[path_key]).write_bytes(raw); piece[digest_key] = digest(raw)
  _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError): PiBackend(profile="pi-full").read_lock(workspace.repository)


def real_base_plugin_workspace(tmp_path):
  """真实Workspace/原resolved Base声明，搭配原校验的纯合成运行锁。"""
  from pathlib import Path
  from agentcfg.workspace import load_workspace
  from agentcfg.pi import PiAdapter
  synthetic, manifest = binding_repository(tmp_path)
  root = Path(__file__).resolve().parents[1]
  local = tmp_path / "local-base.toml"
  local.write_text('schema_version=1\n[machine]\nid="plugin-mapping-test"\n')
  local.chmod(0o600)
  workspace = load_workspace(local, "pi-base", repository=root)
  workspace.repository = synthetic.repository
  workspace.adapter = PiAdapter(synthetic.repository)
  bindings = manifest["capability_bindings"]
  for cap in ("todo", "loop-protection", "footer"):
    declaration = deepcopy(bindings["catalog"]["capabilities"]["native"])
    declaration["owner_domain"] = cap
    bindings["catalog"]["capabilities"][cap] = declaration
    provider = deepcopy(bindings["providers"]["native-provider"])
    provider.update(provider_id="mapped-" + cap, capability_id=cap)
    bindings["providers"][provider["provider_id"]] = provider
    for profile in ("pi-base", "pi-full"):
      manifest["profile_slices"][profile]["capability_ids"].append(cap)
      bindings["selections"][profile]["bindings"].append({"capability_id": cap, "provider_id": provider["provider_id"]})
  _write_manifest(workspace.repository, manifest)
  return workspace


def test_runtime_identity_accepts_real_base_workspace_explicit_three_plugin_capabilities(tmp_path):
  from agentcfg.workspace import Workspace
  workspace = real_base_plugin_workspace(tmp_path)
  assert type(workspace) is Workspace
  assert workspace.resolved.data["profile"]["plugins"] == ["pi-todo", "loop-guard", "colorful-footer"]
  backend = PiBackend(profile="pi-base")
  lock = backend.read_lock(workspace.repository)
  assert backend.runtime_identity(workspace, lock)


@pytest.mark.parametrize("fault", ["missing", "wrong", "duplicate-owner", "extra", "row-type", "cap-type", "cap-id"])
def test_runtime_identity_rejects_invalid_modern_plugin_capability_projection(tmp_path, fault):
  workspace = real_base_plugin_workspace(tmp_path)
  rows = workspace.resolved.data["plugins"]
  if fault == "missing": rows["pi-todo"].pop("capability_id")
  if fault == "wrong": rows["pi-todo"]["capability_id"] = "unselected"
  if fault == "duplicate-owner": rows["loop-guard"]["capability_id"] = "todo"
  if fault == "extra": rows["not-selected"] = deepcopy(rows["pi-todo"])
  if fault == "row-type": rows["pi-todo"] = []
  if fault == "cap-type": rows["pi-todo"]["capability_id"] = True
  if fault == "cap-id": rows["pi-todo"]["capability_id"] = "bad/id"
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  with pytest.raises(ConfigError) as error: backend.runtime_identity(workspace, lock)
  assert error.value.code == "pi-lock-capabilities"


def test_legacy_runtime_identity_keeps_plugin_id_coverage_without_modern_mapping(tmp_path):
  from test_pi_dependencies import fixture_repository
  root, _ = fixture_repository(tmp_path)
  backend = PiBackend(profile="pi-fixture"); lock = backend.read_lock(root)
  workspace = SimpleNamespace(profile="pi-fixture", repository=root,
    resolved=SimpleNamespace(data={"profile": {"plugins": ["pi-host"], "agent_options": {}}}))
  assert backend.runtime_identity(workspace, lock)
  workspace.resolved.data["profile"]["plugins"] = ["unselected"]
  with pytest.raises(ConfigError) as error: backend.runtime_identity(workspace, lock)
  assert error.value.code == "pi-lock-capabilities"


@pytest.mark.parametrize("field,value", [("package", []), ("version", 1), ("enabled", "yes"),
  ("requires", [False]), ("conflicts", "pi-todo"), ("engines", ["unknown-engine"])])
def test_mutating_effective_and_policy_plugin_rows_together_cannot_bypass_types(tmp_path, field, value):
  workspace = real_base_plugin_workspace(tmp_path)
  data = workspace.resolved.data
  for rows in (data["plugins"], data["adapter_documents"]["plugins"]["profile_plugins"]["pi-base"]):
    rows["pi-todo"][field] = deepcopy(value)
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  with pytest.raises(ConfigError) as error: backend.runtime_identity(workspace, lock)
  assert error.value.code == "pi-lock-capabilities"
