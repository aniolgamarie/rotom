"""每个配方消费独立完整锁，不调用真实安装器。"""

import base64
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.pi_dependencies import PiBackend
from agentcfg.schema import ConfigError


def payload(value):
  return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value):
  return hashlib.sha256(value if isinstance(value, bytes) else payload(value)).hexdigest()


def fixture_repository(tmp_path):
  root = tmp_path / "repo"
  production = Path(__file__).resolve().parents[1]
  for directory in ("src/agentcfg", "schemas", "agents/pi/schemas"):
    shutil.copytree(production / directory, root / directory, ignore=shutil.ignore_patterns("__pycache__"))
  (root / "scripts").mkdir()
  for name in ("pi-supervisor-macos.c", "pi-supervisor.py", "pi-control.py", "pi-exec.py", "pi-namespace-exec.py", "pi-project-check", "pi-delegate-codex.py", "model-delegate.py", "model-delegate-batch.py", "pi-file-operation.py", "pi-checkpoint.py", "pi-native-scenario.py", "pi-native-recovery.py"):
    shutil.copyfile(production / "scripts" / name, root / "scripts" / name)
  lock_root = root / "locks/pi"
  pair = lock_root / "pi-fixture"
  pair.mkdir(parents=True)
  recipe = root / "agents/pi"
  recipe.mkdir(parents=True, exist_ok=True)
  (recipe / "dependencies.json").write_bytes(payload({"schema_version": 1, "profile_inputs": {}}))
  (recipe / "agent.toml").write_text('schema_version=1\nadapter_version="pi-1"\n')
  (recipe / "plugins.toml").write_text('schema_version=1\n')
  package = payload({"name": "fixture-runtime", "version": "1.0.0", "private": True, "dependencies": {"synthetic-host": "1.0.0"}})
  integrity = "sha512-" + base64.b64encode(hashlib.sha512(b"fictional package").digest()).decode()
  resolution = payload({"lockfileVersion": 3, "packages": {"": {"dependencies": {"synthetic-host": "1.0.0"}},
    "node_modules/synthetic-host": {"version": "1.0.0", "resolved": "https://example.invalid/pkg.tgz", "integrity": integrity}}})
  (pair / "package.json").write_bytes(package)
  (pair / "package-lock.json").write_bytes(resolution)
  resources = {"extensions": [], "skills": [], "prompts": [], "themes": []}
  piece = {"engine": "node", "source_ids": ["host"], "package_path": "pi-fixture/package.json",
    "lock_path": "pi-fixture/package-lock.json", "package_json_digest": digest(package),
    "package_lock_digest": digest(resolution), "entrypoint": "pi-fixture/node_modules/synthetic-host/index.js",
    "resource_manifest": resources, "resource_manifest_digest": digest(resources), "capability_ids": ["pi-host"]}
  piece["identity"] = digest(piece)
  from agentcfg.pi_dependencies import recipe_digest
  manifest = {"schema_version": 1, "adapter_version": "pi-1", "recipe_digest": recipe_digest(root),
    "toolchains": {"node": "v24.14.0", "npm": "11.19.1", "bun": "1.4.0"},
    "platforms": ["linux-x86_64", "linux-arm64", "darwin-x86_64", "darwin-arm64"],
    "sources": {"host": {"kind": "npm", "package": "synthetic-host", "version": "1.0.0",
      "resolved": "https://example.invalid/pkg.tgz", "integrity": integrity, "license_files": []}},
    "profile_slices": {"pi-fixture": piece}, "build_steps": [], "compatibility": {"bridge_version": 1}}
  manifest["identity"] = digest(manifest)
  (lock_root / "manifest.json").write_bytes(payload(manifest))
  return root, manifest


def test_full_slice_is_validated_and_runtime_identity_is_profile_specific(tmp_path):
  root, manifest = fixture_repository(tmp_path)
  backend = PiBackend()
  lock = backend.read_lock(root)
  assert lock.identity == manifest["identity"]
  workspace = SimpleNamespace(profile="pi-fixture")
  identity = backend.runtime_identity(workspace, lock)
  assert identity != lock.identity and len(identity) == 64
  (root / "locks/pi/pi-fixture/package-lock.json").write_text('{}')
  with pytest.raises(ConfigError):
    backend.read_lock(root)


def test_unknown_manifest_field_is_rejected_even_with_recomputed_hash(tmp_path):
  root, manifest = fixture_repository(tmp_path)
  manifest["untrusted"] = "synthetic"
  manifest.pop("identity")
  manifest["identity"] = digest(manifest)
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  with pytest.raises(ConfigError):
    PiBackend().read_lock(root)


def test_dependency_lock_cannot_omit_transitive_integrity(tmp_path):
  root, manifest = fixture_repository(tmp_path)
  lock_file = root / "locks/pi/pi-fixture/package-lock.json"
  resolution = json.loads(lock_file.read_bytes())
  resolution["packages"]["node_modules/synthetic-host"].pop("integrity")
  lock_file.write_bytes(payload(resolution))
  piece = manifest["profile_slices"]["pi-fixture"]
  piece["package_lock_digest"] = digest(lock_file.read_bytes())
  piece.pop("identity")
  piece["identity"] = digest(piece)
  manifest.pop("identity")
  manifest["identity"] = digest(manifest)
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  with pytest.raises(ConfigError):
    PiBackend().read_lock(root)


def test_runtime_receipt_detects_same_length_tampering(tmp_path):
  from agentcfg.pi_runtime_packages import seal, status
  from agentcfg.storage import ensure_private
  root, manifest = fixture_repository(tmp_path)
  runtime = tmp_path / "runtime"
  ensure_private(runtime)
  piece = manifest["profile_slices"]["pi-fixture"]
  for name in (piece["package_path"], piece["lock_path"]):
    target = runtime / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((root / "locks/pi" / name).read_bytes())
  package = runtime / "pi-fixture/node_modules/synthetic-host/package.json"
  package.parent.mkdir(parents=True)
  package.write_text('{"name":"synthetic-host","version":"1.0.0","license":"MIT"}')
  for name in (piece["entrypoint"], "runtime/launch.mjs", "runtime/resource-loader.mjs", "runtime/profile.json"):
    path = runtime / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture-code")
  from agentcfg.pi_vendor import install_launcher
  install_launcher(Path(__file__).resolve().parents[1], runtime, piece, manifest)
  backend = PiBackend()
  runtime_identity = backend.runtime_identity(SimpleNamespace(profile="pi-fixture"), backend.read_lock(root))
  seal(runtime, runtime_identity, manifest["identity"], piece, toolchains=manifest["toolchains"])
  assert status(runtime, runtime_identity) == "installed"
  (runtime / piece["entrypoint"]).write_text("altered-code")
  assert status(runtime, runtime_identity) == "damaged"


def synthetic_runtime_sources(root, declarations):
  """现代安装fixture只承载占位源文件；不复制真实执行或恢复逻辑。"""
  for row in declarations:
    path = root / row["source"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n" if path.suffix == ".json" else
      "// synthetic runtime, never executed\n" if row["transform"] == "ts-module" else
      "# synthetic runtime, never executed\n")


def ready_sync_fixture(tmp_path):
  from agentcfg.pi_dependencies import recipe_digest
  from agentcfg.storage import ensure_private
  root, manifest = fixture_repository(tmp_path)
  runtime_sources = root / "agents/pi/runtime"
  runtime_sources.mkdir()
  for name in ("launch", "resource-loader"):
    (runtime_sources / (name + ".ts")).write_text("// fixture source, never executed\n")
  shutil.copyfile(Path(__file__).resolve().parents[1] / "agents/pi/runtime/sandbox-macos.sb", runtime_sources / "sandbox-macos.sb")
  manifest["recipe_digest"] = recipe_digest(root)
  manifest.pop("identity")
  manifest["identity"] = digest(manifest)
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  instance, state = tmp_path / "instance", tmp_path / "state"
  ensure_private(instance)
  ensure_private(state)
  return SimpleNamespace(repository=root, profile="pi-fixture", instance=instance, state_root=state), manifest


def fake_installer(calls, *, omit=False, fail=False):
  def checked(argv, *, cwd, env):
    calls.append((list(argv), Path(cwd), dict(env)))
    if argv == ["node", "--version"]:
      return "v24.14.0"
    if argv == ["npm", "--version"]:
      return "11.19.1"
    assert argv == ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]
    if fail:
      from agentcfg.process import DependencyError
      raise DependencyError("synthetic installer failure")
    if not omit:
      package = Path(cwd) / "node_modules/synthetic-host"
      package.mkdir(parents=True)
      (package / "package.json").write_text('{"name":"synthetic-host","version":"1.0.0","license":"MIT"}')
      (package / "LICENSE").write_bytes(b"synthetic original MIT body\n")
      (package / "index.js").write_text("synthetic host; never execute")
      locked = json.loads((Path(cwd) / "package-lock.json").read_bytes())["packages"]
      if "node_modules/synthetic-ai" in locked:
        ai = Path(cwd) / "node_modules/synthetic-ai"; ai.mkdir()
        (ai / "package.json").write_text('{"name":"synthetic-ai","version":"1.0.2","license":"MIT"}')
        (ai / "LICENSE").write_bytes(b"synthetic original MIT body\n")
        (ai / "index.js").write_text("synthetic AI; never execute")
      bin_dir = Path(cwd) / "node_modules/.bin"
      bin_dir.mkdir()
      (bin_dir / "synthetic-host").symlink_to("../synthetic-host/index.js")
    return ""
  return checked


def test_bun_slice_refuses_wrong_engine_before_npm_install(tmp_path, monkeypatch):
  import agentcfg.pi_dependencies as dependencies
  from agentcfg.process import DependencyError
  workspace, manifest = ready_sync_fixture(tmp_path)
  piece = manifest["profile_slices"][workspace.profile]
  piece["engine"] = "bun"
  piece["identity"] = digest({key: value for key, value in piece.items() if key != "identity"})
  manifest["identity"] = digest({key: value for key, value in manifest.items() if key != "identity"})
  (workspace.repository / "locks/pi/manifest.json").write_bytes(payload(manifest))
  calls = []
  def checked(argv, **kwargs):
    calls.append(argv)
    return {"node": "v24.14.0", "npm": "11.19.1", "bun": "1.3.0"}[argv[0]]
  monkeypatch.setattr(dependencies, "checked", checked)
  backend = PiBackend()
  with pytest.raises(DependencyError, match="精确工具链"):
    backend.sync(workspace, backend.read_lock(workspace.repository))
  assert calls == [["node", "--version"], ["npm", "--version"], ["bun", "--version"]]


def test_sync_keeps_complete_pair_and_repairs_content_without_touching_auth(tmp_path, monkeypatch):
  import agentcfg.pi_dependencies as dependencies
  workspace, manifest = ready_sync_fixture(tmp_path)
  auth = workspace.instance / "synthetic-auth-sentinel"
  auth.write_text("must stay unchanged")
  calls = []
  monkeypatch.setattr(dependencies, "checked", fake_installer(calls))
  backend = PiBackend()
  lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock)
  assert result["installed"] is True
  root = backend.root(workspace, result["identity"])
  for name in ("supervisor/scripts/pi-delegate-mcp.py", "supervisor/src/agentcfg/pi_delegate_mcp.py", "supervisor/src/agentcfg/pi_delegate_commands.py"):
    assert not (root / name).exists()
  assert (root / "supervisor/src/agentcfg/pi_delegate_policy.py").is_file()
  piece = manifest["profile_slices"][workspace.profile]
  assert (root / piece["package_path"]).read_bytes() == lock.pairs[workspace.profile][0]
  assert (root / piece["lock_path"]).read_bytes() == lock.pairs[workspace.profile][1]
  assert backend.status(workspace, result["identity"]) == "installed"
  assert backend.sync(workspace, lock)["installed"] is False
  assert len(calls) == 3
  assert "install-home" in calls[2][2]["HOME"]
  assert not (root / "install-home").exists()
  (root / piece["entrypoint"]).write_text("damaged")
  assert backend.status(workspace, result["identity"]) == "damaged"
  assert backend.sync(workspace, lock)["installed"] is True
  assert backend.status(workspace, result["identity"]) == "installed"
  assert auth.read_text() == "must stay unchanged"


def test_missing_required_entry_does_not_activate_successful_installer(tmp_path, monkeypatch):
  import agentcfg.pi_dependencies as dependencies
  from agentcfg.process import DependencyError
  workspace, _ = ready_sync_fixture(tmp_path)
  monkeypatch.setattr(dependencies, "checked", fake_installer([], omit=True))
  backend = PiBackend()
  lock = backend.read_lock(workspace.repository)
  with pytest.raises(DependencyError) as caught:
    backend.sync(workspace, lock)
  assert caught.value.exit_code == 5
  assert backend.status(workspace, backend.runtime_identity(workspace, lock)) == "missing"


def test_failed_repair_preserves_old_runtime_until_valid_new_stage(tmp_path, monkeypatch):
  import agentcfg.pi_dependencies as dependencies
  from agentcfg.process import DependencyError
  workspace, manifest = ready_sync_fixture(tmp_path)
  monkeypatch.setattr(dependencies, "checked", fake_installer([]))
  backend = PiBackend()
  lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock)
  root = backend.root(workspace, result["identity"])
  target = root / manifest["profile_slices"][workspace.profile]["entrypoint"]
  target.write_text("old damaged artifact")
  monkeypatch.setattr(dependencies, "checked", fake_installer([], fail=True))
  with pytest.raises(DependencyError):
    backend.sync(workspace, lock)
  assert target.read_text() == "old damaged artifact"
  assert not list(root.parent.glob(".repair-*"))


def test_explicit_lock_generates_independent_complete_pairs_with_fake_resolver(tmp_path, monkeypatch):
  import agentcfg.pi_vendor as vendor
  workspace, original = ready_sync_fixture(tmp_path)
  root = workspace.repository
  build = root / "agents/pi/build"
  build.mkdir()
  (build / "recipes.json").write_bytes(payload({"schema_version": 1, "sources": {}}))
  inputs = {"schema_version": 1, "toolchains": original["toolchains"], "platforms": original["platforms"],
    "sources": {"host": {"kind": "npm", "package": "synthetic-host", "version": "1.0.0", "license_files": [],
      "resources": {"extensions": [], "skills": [], "prompts": [], "themes": []}}},
    "profiles": {name: {"engine": "node", "source_ids": ["host"], "entrypoint": "node_modules/synthetic-host/index.js"} for name in ("pi-fixture", "pi-another")}, "build_steps": []}
  (root / "agents/pi/dependencies.json").write_bytes(payload(inputs))
  locked = (root / "locks/pi/pi-fixture/package-lock.json").read_bytes()
  calls = []
  def resolve(argv, *, cwd, env):
    calls.append((argv, cwd, env))
    if argv == ["node", "--version"]:
      return "v24.14.0"
    if argv == ["npm", "--version"]:
      return "11.19.1"
    assert argv == ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"]
    (cwd / "package-lock.json").write_bytes(locked)
    return ""
  monkeypatch.setattr(vendor, "checked", resolve)
  lock = vendor.resolve_lock(root)
  assert set(lock.pairs) == {"pi-fixture", "pi-another"}
  assert lock.metadata["profile_slices"]["pi-fixture"]["identity"] != lock.metadata["profile_slices"]["pi-another"]["identity"]
  assert len(calls) == 4
  assert lock.pairs["pi-fixture"][1] == lock.pairs["pi-another"][1] == locked


def test_native_required_resource_missing_is_not_a_ready_receipt(tmp_path):
  from agentcfg.pi_runtime_packages import validate_installed
  from agentcfg.storage import Conflict, ensure_private
  root, manifest = fixture_repository(tmp_path)
  runtime = tmp_path / "installed"
  ensure_private(runtime)
  piece = manifest["profile_slices"]["pi-fixture"]
  for name in (piece["package_path"], piece["lock_path"]):
    target = runtime / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((root / "locks/pi" / name).read_bytes())
  package = runtime / "pi-fixture/node_modules/synthetic-host/package.json"
  package.parent.mkdir(parents=True)
  package.write_text('{"name":"synthetic-host","version":"1.0.0","license":"MIT"}')
  for name in (piece["entrypoint"], "runtime/launch.mjs", "runtime/resource-loader.mjs", "runtime/profile.json"):
    target = runtime / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fixture")
  from agentcfg.pi_vendor import install_launcher
  install_launcher(Path(__file__).resolve().parents[1], runtime, piece, manifest)
  piece["resource_manifest"]["extensions"] = [{"id": "host", "capability_id": "pi-host", "path": "missing/required.wasm"}]
  with pytest.raises(Conflict):
    validate_installed(runtime, piece)


def test_runtime_receipt_cannot_be_reused_on_a_different_platform(tmp_path, monkeypatch):
  import agentcfg.pi_dependencies as dependencies
  workspace, _ = ready_sync_fixture(tmp_path)
  monkeypatch.setattr(dependencies, "checked", fake_installer([]))
  backend = PiBackend()
  lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock)
  assert backend.status(workspace, result["identity"]) == "installed"
  monkeypatch.setattr(dependencies, "platform_id", lambda: "darwin-arm64")
  assert backend.status(workspace, result["identity"]) == "damaged"


def _write_manifest(root, manifest, *, family=None):
  from agentcfg.pi_lock_layout import dependency_layout
  for piece in manifest["profile_slices"].values():
    piece["identity"] = digest({key: value for key, value in piece.items() if key != "identity"})
  manifest["identity"] = digest({key: value for key, value in manifest.items() if key != "identity"})
  (root / dependency_layout(family=family).lock_directory / "manifest.json").write_bytes(payload(manifest))


def two_profiles_repository(tmp_path):
  from copy import deepcopy
  workspace, manifest = ready_sync_fixture(tmp_path)
  root = workspace.repository; lock_root = root / "locks/pi"
  (lock_root / "pi-fixture").rename(lock_root / "pi-test-base")
  base = manifest["profile_slices"].pop("pi-fixture")
  for field in ("package_path", "lock_path", "entrypoint"): base[field] = base[field].replace("pi-fixture/", "pi-test-base/")
  full = deepcopy(base)
  for field in ("package_path", "lock_path", "entrypoint"): full[field] = full[field].replace("pi-test-base/", "pi-test-full/")
  full["source_ids"] = ["full-feature"]; full["capability_ids"] = ["full-feature"]
  archive = lock_root / "vendor/full.tgz"; archive.parent.mkdir(); archive.write_bytes(b"synthetic archive, never executed")
  manifest["sources"]["full-feature"] = {"kind": "local", "package": "synthetic-host", "version": "1.0.0", "vendor_path": "vendor/full.tgz",
    "archive_digest": digest(archive.read_bytes()), "source_path": "agents/pi/packages/full", "source_tree_digest": "a" * 64, "license_files": []}
  (lock_root / "pi-test-full").mkdir()
  package = payload({"name": "full-fixture", "version": "1.0.0", "private": True, "dependencies": {"synthetic-host": "file:../vendor/full.tgz"}})
  resolution = json.loads((lock_root / base["lock_path"]).read_bytes())
  resolution["packages"][""]["dependencies"] = {"synthetic-host": "file:../vendor/full.tgz"}
  resolution["packages"]["node_modules/synthetic-host"]["resolved"] = "file:../vendor/full.tgz"
  (lock_root / full["package_path"]).write_bytes(package); (lock_root / full["lock_path"]).write_bytes(payload(resolution))
  full["package_json_digest"] = digest(package); full["package_lock_digest"] = digest(payload(resolution))
  manifest["profile_slices"] = {"pi-test-base": base, "pi-test-full": full}
  workspace.profile = "pi-test-base"
  _write_manifest(root, manifest)
  return workspace, manifest


@pytest.mark.parametrize("missing", ["package", "lock", "vendor", "all"])
def test_selected_base_reads_and_fake_syncs_without_full_profile_bodies(tmp_path, monkeypatch, missing):
  import agentcfg.pi_dependencies as dependencies
  workspace, manifest = two_profiles_repository(tmp_path)
  full = manifest["profile_slices"]["pi-test-full"]
  targets = {"package": full["package_path"], "lock": full["lock_path"], "vendor": "vendor/full.tgz"}
  for name, path in targets.items():
    if missing in (name, "all"): (workspace.repository / "locks/pi" / path).unlink()
  calls = []; monkeypatch.setattr(dependencies, "checked", fake_installer(calls))
  backend = PiBackend(profile="pi-test-base")
  lock = backend.read_lock(workspace.repository)
  assert set(lock.pairs) == {"pi-test-base"}
  assert backend.sync(workspace, lock)["installed"] is True
  assert len(calls) == 3
  for other in (PiBackend(), PiBackend(profile="pi-test-full")):
    with pytest.raises(ConfigError): other.read_lock(workspace.repository)


@pytest.mark.parametrize("fault", ["missing", "tamper", "full-metadata", "full-slice-identity"])
def test_selected_base_still_rejects_own_damage_and_all_global_metadata_damage(tmp_path, fault):
  workspace, manifest = two_profiles_repository(tmp_path)
  path = workspace.repository / "locks/pi" / manifest["profile_slices"]["pi-test-base"]["lock_path"]
  if fault == "missing": path.unlink()
  if fault == "tamper": path.write_text("{}")
  if fault == "full-metadata":
    manifest["sources"]["full-feature"]["version"] = "latest"; _write_manifest(workspace.repository, manifest)
  if fault == "full-slice-identity":
    manifest["profile_slices"]["pi-test-full"]["identity"] = "b" * 64
    manifest["identity"] = digest({key: value for key, value in manifest.items() if key != "identity"})
    (workspace.repository / "locks/pi/manifest.json").write_bytes(payload(manifest))
  with pytest.raises(ConfigError): PiBackend(profile="pi-test-base").read_lock(workspace.repository)


def test_base_only_verified_lock_cannot_query_or_write_full_runtime(tmp_path, monkeypatch):
  import agentcfg.pi_dependencies as dependencies
  workspace, _ = two_profiles_repository(tmp_path)
  base = PiBackend(profile="pi-test-base"); lock = base.read_lock(workspace.repository)
  workspace.profile = "pi-test-full"
  calls = []; monkeypatch.setattr(dependencies, "checked", fake_installer(calls))
  monkeypatch.setattr("agentcfg.pi_lifecycle.guard", lambda *_: pytest.fail("unverified profile must fail before acquiring write guard"))
  for backend in (base, PiBackend(profile="pi-test-full"), PiBackend()):
    with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)
    with pytest.raises(ConfigError): backend.sync(workspace, lock)
  assert calls == []


def installed_graph_fixture(tmp_path, *, extra_records=None):
  workspace, manifest = ready_sync_fixture(tmp_path)
  piece = manifest["profile_slices"][workspace.profile]
  resolution_path = workspace.repository / "locks/pi" / piece["lock_path"]
  resolution = json.loads(resolution_path.read_bytes())
  resolution["packages"].update(extra_records or {})
  resolution_path.write_bytes(payload(resolution)); piece["package_lock_digest"] = digest(payload(resolution))
  _write_manifest(workspace.repository, manifest)
  runtime = tmp_path / "installed-graph"; runtime.mkdir(mode=0o700)
  for field in ("package_path", "lock_path"):
    path = runtime / piece[field]; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes((workspace.repository / "locks/pi" / piece[field]).read_bytes())
  for name, record in resolution["packages"].items():
    if not name or record.get("optional"): continue
    path = runtime / Path(piece["package_path"]).parent / name; path.mkdir(parents=True, exist_ok=True)
    package_name = record.get("name", name.rsplit("node_modules/", 1)[-1])
    (path / "package.json").write_bytes(payload({"name": package_name, "version": record["version"]}))
  for name in (piece["entrypoint"], "runtime/launch.mjs", "runtime/resource-loader.mjs", "runtime/profile.json"):
    path = runtime / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("synthetic code, never executed")
  from agentcfg.pi_vendor import install_launcher
  install_launcher(Path(__file__).resolve().parents[1], runtime, piece, manifest)
  return runtime, piece


@pytest.mark.parametrize("extra", ["top", "nested", "deep", "scoped", "outside-slice"])
def test_installed_graph_rejects_every_unlocked_package_without_deleting_it(tmp_path, extra):
  from agentcfg.pi_runtime_packages import validate_installed
  from agentcfg.storage import Conflict
  runtime, piece = installed_graph_fixture(tmp_path)
  prefix = Path(piece["package_path"]).parent
  relative = {"top": prefix / "node_modules/full-only", "nested": prefix / "node_modules/synthetic-host/node_modules/full-only",
    "deep": prefix / "node_modules/synthetic-host/dist/node_modules/full-only", "scoped": prefix / "node_modules/@full/worker",
    "outside-slice": Path("runtime/node_modules/full-only")}[extra]
  path = runtime / relative; path.mkdir(parents=True); sentinel = path / "package.json"; sentinel.write_text('{"name":"full-only","version":"1.0.0"}')
  with pytest.raises(Conflict): validate_installed(runtime, piece)
  assert sentinel.read_text() == '{"name":"full-only","version":"1.0.0"}'


@pytest.mark.parametrize("fault", ["name", "version", "extra-file", "missing-manifest"])
def test_installed_graph_rejects_package_identity_confusion_and_direct_module_files(tmp_path, fault):
  from agentcfg.pi_runtime_packages import validate_installed
  from agentcfg.storage import Conflict
  runtime, piece = installed_graph_fixture(tmp_path)
  package = runtime / Path(piece["package_path"]).parent / "node_modules/synthetic-host/package.json"
  if fault == "name": package.write_text('{"name":"full-only","version":"1.0.0"}')
  if fault == "version": package.write_text('{"name":"synthetic-host","version":"2.0.0"}')
  if fault == "missing-manifest": package.unlink()
  if fault == "extra-file": (package.parent.parent / "full-only.js").write_text("must not load")
  with pytest.raises(Conflict): validate_installed(runtime, piece)


def test_installed_graph_accepts_complete_scoped_nested_bundled_alias_and_missing_optional_packages(tmp_path):
  from agentcfg.pi_runtime_packages import validate_installed
  records = {"node_modules/@fixture/core": {"version": "1.0.0"},
    "node_modules/synthetic-host/node_modules/bundled": {"version": "2.0.0", "inBundle": True},
    "node_modules/synthetic-host/node_modules/alias": {"name": "actual-name", "version": "3.0.0"},
    "node_modules/optional-platform": {"version": "1.0.0", "optional": True}}
  runtime, piece = installed_graph_fixture(tmp_path, extra_records=records)
  prefix = runtime / Path(piece["package_path"]).parent
  (prefix / "node_modules/.bin").mkdir()
  (prefix / "node_modules/.bin/synthetic-host").symlink_to("../synthetic-host/index.js")
  (prefix / "node_modules/.package-lock.json").write_text("{}")
  validate_installed(runtime, piece)


def test_workspace_supplies_profile_through_generic_dependency_backend_hook(tmp_path):
  from agentcfg.workspace import Workspace
  calls = []
  class AdapterFixture:
    def dependency_backend(self, *, profile=None): calls.append(profile); return "synthetic-backend"
  workspace = Workspace(tmp_path, tmp_path / "local.toml", SimpleNamespace(data={"profile": {"id": "pi-test-base"}}), AdapterFixture(), None, None)
  assert workspace.backend == "synthetic-backend" and calls == ["pi-test-base"]


def test_real_adapters_accept_generic_optional_profile_without_changing_dsh_omp_backends(tmp_path):
  from agentcfg.dsh import DshAdapter
  from agentcfg.omp import OmpAdapter
  from agentcfg.pi import PiAdapter
  from agentcfg.backends import DshBackend
  from agentcfg.omp_dependencies import OmpBackend
  assert isinstance(DshAdapter(tmp_path).dependency_backend(profile="dsh-fixture"), DshBackend)
  assert isinstance(OmpAdapter(tmp_path).dependency_backend(profile="omp-fixture"), OmpBackend)
  assert PiAdapter(tmp_path).dependency_backend(profile="pi-test-base").profile == "pi-test-base"


@pytest.mark.parametrize("fault", ["missing", "tamper"])
def test_selected_base_own_vendor_body_is_required_and_integrity_checked(tmp_path, fault):
  workspace, manifest = two_profiles_repository(tmp_path)
  lock_root = workspace.repository / "locks/pi"; piece = manifest["profile_slices"]["pi-test-base"]
  archive = lock_root / "vendor/base.tgz"; archive.write_bytes(b"synthetic Base archive")
  manifest["sources"]["host"] = {"kind": "local", "package": "synthetic-host", "version": "1.0.0", "vendor_path": "vendor/base.tgz",
    "archive_digest": digest(archive.read_bytes()), "source_path": "agents/pi/packages/base", "source_tree_digest": "a" * 64, "license_files": []}
  package = json.loads((lock_root / piece["package_path"]).read_bytes()); package["dependencies"]["synthetic-host"] = "file:../vendor/base.tgz"
  resolution = json.loads((lock_root / piece["lock_path"]).read_bytes()); resolution["packages"][""]["dependencies"] = package["dependencies"]
  resolution["packages"]["node_modules/synthetic-host"]["resolved"] = "file:../vendor/base.tgz"
  (lock_root / piece["package_path"]).write_bytes(payload(package)); (lock_root / piece["lock_path"]).write_bytes(payload(resolution))
  piece["package_json_digest"] = digest(payload(package)); piece["package_lock_digest"] = digest(payload(resolution))
  _write_manifest(workspace.repository, manifest)
  assert set(PiBackend(profile="pi-test-base").read_lock(workspace.repository).pairs) == {"pi-test-base"}
  if fault == "missing": archive.unlink()
  else: archive.write_bytes(b"tampered Base archive")
  with pytest.raises(ConfigError): PiBackend(profile="pi-test-base").read_lock(workspace.repository)


@pytest.mark.parametrize("fault", ["alias-name", "optional-manifest", "package-json"])
def test_installed_graph_does_not_confuse_aliases_or_ignore_present_broken_optional_packages(tmp_path, fault):
  from agentcfg.pi_runtime_packages import validate_installed
  from agentcfg.storage import Conflict
  records = {"node_modules/alias": {"name": "actual-name", "version": "1.0.0"}, "node_modules/optional": {"version": "1.0.0", "optional": True}}
  runtime, piece = installed_graph_fixture(tmp_path, extra_records=records)
  prefix = runtime / Path(piece["package_path"]).parent
  if fault == "alias-name": (prefix / "node_modules/alias/package.json").write_text('{"name":"alias","version":"1.0.0"}')
  if fault == "optional-manifest": (prefix / "node_modules/optional").mkdir()
  if fault == "package-json": (prefix / "node_modules/alias/package.json").write_text("invalid JSON")
  with pytest.raises(Conflict): validate_installed(runtime, piece)


def test_default_global_lock_validation_keeps_checking_unreferenced_vendor_bodies(tmp_path):
  from copy import deepcopy
  workspace, manifest = two_profiles_repository(tmp_path)
  source = deepcopy(manifest["sources"]["full-feature"]); source["vendor_path"] = "vendor/unused.tgz"
  manifest["sources"]["unused-source"] = source; _write_manifest(workspace.repository, manifest)
  assert set(PiBackend(profile="pi-test-base").read_lock(workspace.repository).pairs) == {"pi-test-base"}
  with pytest.raises(ConfigError): PiBackend().read_lock(workspace.repository)


def test_installed_graph_preserves_legal_bin_link_even_when_command_name_is_node_modules(tmp_path):
  from agentcfg.pi_runtime_packages import validate_installed, inventory
  runtime, piece = installed_graph_fixture(tmp_path)
  prefix = runtime / Path(piece["package_path"]).parent
  directory = prefix / "node_modules/.bin"; directory.mkdir()
  (directory / "node_modules").symlink_to("../synthetic-host/index.js")
  validate_installed(runtime, piece)
  assert inventory(runtime)[(directory / "node_modules").relative_to(runtime).as_posix()]["kind"] == "link"
