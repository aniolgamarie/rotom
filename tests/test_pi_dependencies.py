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
  package.write_text('{"name":"synthetic-host","version":"1.0.0"}')
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
      (package / "package.json").write_text('{"name":"synthetic-host","version":"1.0.0"}')
      (package / "index.js").write_text("synthetic host; never execute")
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
  package.write_text('{"name":"synthetic-host","version":"1.0.0"}')
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
