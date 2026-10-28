"""锁消费失败不激活；真实包安装另由显式集成验收记录。"""

from pathlib import Path
from types import SimpleNamespace
import base64
import hashlib
import io
import json
import shutil
import tarfile
import tomllib
import yaml

import pytest

from agentcfg import dependencies as dep
from agentcfg.process import DependencyError, checked
from agentcfg.schema import ConfigError
from agentcfg.storage import ensure_private


REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", ["install", "changed-lock", "changed-installer-lock", "runtime-check", "missing-helper"])
def test_failed_sync_keeps_old_runtime_and_repository_lock(tmp_path, monkeypatch, failure):
  w = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    cache=tmp_path / "cache", repository=REPO, profile="dsh-default", binding={"profile": "dsh-default"},
    resolved=SimpleNamespace(data={"machine": {}}))
  lock = dep.read_lock(REPO)
  previous = w.instance / "runtimes/previous"
  ensure_private(previous)
  (previous / "keep").write_text("working runtime")
  before = (REPO / "locks/dsh/pnpm-lock.yaml").read_bytes()
  def fake(argv, *, cwd, env):
    assert "API_KEY" not in env
    if argv == ["node", "--version"]:
      return lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return lock.metadata["npm"]
    if argv[-1] == "--version" and argv[0] == "node":
      return lock.metadata["pnpm"]
    if "--frozen-lockfile" in argv:
      assert "--ignore-scripts" in argv and "--node-linker=hoisted" in argv and "--package-import-method=copy" in argv
      assert "--force" not in argv and "--legacy-peer-deps" not in argv
      assert yaml.safe_load((cwd / "pnpm-workspace.yaml").read_bytes())["minimumReleaseAgeExclude"] == lock.metadata["minimum_release_age_exclude"]
      (cwd / "partial").write_text("partial installation")
      if failure == "install":
        raise DependencyError("合成安装失败")
      if failure == "changed-lock":
        (cwd / "package-lock.json").write_text("changed")
      if failure == "changed-installer-lock":
        (cwd / "pnpm-lock.yaml").write_text("changed")
    if failure == "runtime-check" and argv[1].endswith("check-runtime.mjs"):
      raise DependencyError("合成模块身份不一致")
    return ""
  monkeypatch.setattr(dep, "checked", fake)
  with pytest.raises(DependencyError):
    dep.sync(w, lock)
  assert (previous / "keep").read_text() == "working runtime"
  assert not dep.runtime_root(w, lock).exists()
  assert not list((w.instance / "runtimes").glob(".stage-*"))
  assert (REPO / "locks/dsh/pnpm-lock.yaml").read_bytes() == before


@pytest.mark.parametrize(("tool", "actual"), [("node", "v25.0.0"), ("npm", "12.0.0"), ("node", "v24.1.0")])
def test_sync_rejects_incompatible_toolchain_version(tmp_path, monkeypatch, tool, actual):
  w = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    cache=tmp_path / "cache", repository=REPO, agent="dsh", profile="dsh-default", binding={"profile": "dsh-default"},
    resolved=SimpleNamespace(data={"machine": {}}))
  lock = dep.read_lock(REPO)
  def fake(argv, *, cwd, env):
    if argv == ["node", "--version"]:
      return actual if tool == "node" else lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return actual if tool == "npm" else lock.metadata["npm"]
    pytest.fail("版本不匹配后不应开始安装")
  monkeypatch.setattr(dep, "checked", fake)
  with pytest.raises(DependencyError, match=f"期望 .*实际 {actual}"):
    dep.sync(w, lock)


@pytest.mark.parametrize(("tool", "actual", "locked"),
  [("Node", "v24.2.0", "v24.14.0"), ("Node", "v24.14.1", "v24.14.0"),
   ("npm", "11.0.0", "11.19.1")])
def test_toolchain_accepts_same_major_version(tool, actual, locked):
  from agentcfg.toolchain import compatible_toolchain
  assert compatible_toolchain(tool, actual, locked)


@pytest.mark.parametrize(("tool", "actual", "locked"), [
  ("Node", "v024.1.0", "v24.14.0"), ("Node", "v24.1.0\nprivate-token", "v24.14.0"),
  ("npm", "011.0.0", "11.19.1"), ("npm", "１１.0.0", "11.19.1"),
])
def test_toolchain_rejects_and_hides_malformed_output(tool, actual, locked):
  from agentcfg.toolchain import ensure_compatible_toolchain
  with pytest.raises(DependencyError) as caught:
    ensure_compatible_toolchain(tool, locked, actual)
  assert actual not in str(caught.value)
  assert "已隐藏" in str(caught.value)


@pytest.mark.parametrize(("tool", "actual"), [
  ("node", "v24.14.1"), ("npm", "11.19.2"), ("node", "v24.14.0\nsynthetic-private-token"),
])
def test_resolve_lock_requires_exact_toolchain_before_install(tmp_path, monkeypatch, tool, actual):
  repository = lock_repository(tmp_path)
  lock = dep.read_lock(repository)
  before = {name: (repository / "locks/dsh" / name).read_bytes()
            for name in ("package.json", "pnpm-lock.yaml", "manifest.json")}

  def fake(argv, *, cwd, env):
    if argv == ["node", "--version"]:
      return actual if tool == "node" else lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return actual if tool == "npm" else lock.metadata["npm"]
    pytest.fail("精确版本不匹配后不应解析锁")

  monkeypatch.setattr(dep, "checked", fake)
  with pytest.raises(DependencyError) as caught:
    dep.resolve_lock(repository)
  assert "期望" in str(caught.value) and "实际" in str(caught.value)
  assert "synthetic-private-token" not in str(caught.value)
  assert all((repository / "locks/dsh" / name).read_bytes() == raw for name, raw in before.items())


def test_lock_rejects_adapter_declaration_drift(monkeypatch):
  from agentcfg.adapter import AdapterDeclaration
  from agentcfg.backends import DshBackend
  from agentcfg.dsh import DshAdapter
  monkeypatch.setattr(DshAdapter, "declaration", AdapterDeclaration("dsh", 1, "dsh-2"))
  with pytest.raises(ConfigError):
    DshBackend().read_lock(REPO)


def test_missing_and_stale_lock_do_not_resolve_dependencies(tmp_path, monkeypatch):
  with pytest.raises(ConfigError):
    dep.read_lock(tmp_path)
  monkeypatch.setattr(dep, "recipe_digest", lambda repository, adapter_id="dsh": "changed")
  with pytest.raises(ConfigError):
    dep.read_lock(REPO)


def test_child_failure_does_not_expose_native_output(tmp_path, fake_subprocess, capsys):
  canary = "synthetic-private-child-error"
  fake_subprocess.queue(returncode=9, stdout=canary, stderr=canary)
  with pytest.raises(DependencyError) as caught:
    checked(["npm", "ci"], cwd=tmp_path, env={"PATH": "/synthetic"})
  assert canary not in str(caught.value)
  assert "npm" in str(caught.value) and "退出码 9" in str(caught.value)
  assert capsys.readouterr() == ("", "")


def lock_repository(tmp_path):
  repository = tmp_path / "repository"
  shutil.copytree(REPO / "agents/dsh", repository / "agents/dsh")
  shutil.copytree(REPO / "locks/dsh", repository / "locks/dsh")
  return repository


def test_frozen_installer_lock_and_tool_version_change_identity():
  lock = dep.read_lock(REPO)
  assert lock.installer_resolution
  assert dep.lock_identity(lock.package, lock.resolution, lock.metadata, lock.installer_resolution) == lock.identity
  assert dep.lock_identity(lock.package, lock.resolution, lock.metadata, lock.installer_resolution + b"\n") != lock.identity
  changed = {**lock.metadata, "pnpm": "11.19.1"}
  assert dep.lock_identity(lock.package, lock.resolution, changed, lock.installer_resolution) != lock.identity
  assert dep.Lock("fixture", {}, b"{}", b"{}").installer_resolution == b""


def test_pnpm_only_lock_rejects_unexpected_npm_lock_and_plugin_drift(tmp_path):
  repository = lock_repository(tmp_path)
  lock = dep.read_lock(repository)
  assert lock.metadata["version"] == 2 and lock.metadata["resolution_kind"] == "pnpm"
  assert lock.resolution == b""
  unexpected = repository / "locks/dsh/package-lock.json"
  unexpected.write_text('{}')
  with pytest.raises(ConfigError):
    dep.read_lock(repository)
  unexpected.unlink()
  document = yaml.safe_load(lock.installer_resolution)
  document["packages"].pop("dsh-auto-review@0.15.0")
  with pytest.raises(DependencyError):
    dep.validate_installer_plugin_versions(repository, yaml.safe_dump(document).encode())


def test_legacy_runtime_receipt_remains_readable(tmp_path):
  from agentcfg import runtime_packages
  from agentcfg.deployment import json_bytes
  from agentcfg.storage import Tree
  root = tmp_path / "legacy-runtime"
  ensure_private(root)
  for name in runtime_packages.LEGACY_REQUIRED_FILES:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'synthetic legacy entry')
  (root / "package.json").write_bytes(b'{"dependencies":{"fixture":"1.0.0"}}')
  (root / "package-lock.json").write_bytes(b'{"packages":{"":{"dependencies":{"fixture":"1.0.0"}}}}')
  files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in runtime_packages.LEGACY_REQUIRED_FILES}
  with Tree(root) as tree:
    tree.write_state(".agentcfg-ready", b"legacy\n")
    tree.write_state(".agentcfg-receipt.json", json_bytes({"version": 2, "identity": "legacy", "files": files,
      "topology": runtime_packages.topology_digest(root)}))
  assert runtime_packages.status(root, "legacy") == "installed"
  (root / "node_modules/rotom-dsh-cursor-terminal/index.mjs").write_bytes(b"drift")
  assert runtime_packages.status(root, "legacy") == "damaged"


@pytest.mark.parametrize("change", ["installer-lock", "unknown-metadata", "source"])
def test_read_lock_rejects_changed_installer_unknown_metadata_and_unpacked_source(tmp_path, change):
  repository = lock_repository(tmp_path)
  if change == "installer-lock":
    path = repository / "locks/dsh/pnpm-lock.yaml"
    path.write_bytes(path.read_bytes() + b"\n")
  elif change == "unknown-metadata":
    path = repository / "locks/dsh/manifest.json"
    metadata = json.loads(path.read_bytes())
    metadata["unknown"] = True
    path.write_text(json.dumps(metadata))
  else:
    path = repository / "agents/dsh/packages/cursor-terminal/index.mjs"
    path.write_bytes(path.read_bytes() + b"\n// source changed without packing\n")
  with pytest.raises(ConfigError):
    dep.read_lock(repository)


def test_recipe_ignores_undeclared_historical_vendor(tmp_path):
  repository = lock_repository(tmp_path)
  before = dep.recipe_digest(repository)
  (repository / "locks/dsh/vendor/retired-unused.tgz").write_bytes(b"historical archive")
  assert dep.recipe_digest(repository) == before


def test_recipe_refuses_changed_local_source_without_repacking(tmp_path):
  repository = lock_repository(tmp_path)
  path = repository / "agents/dsh/packages/cursor-terminal/index.mjs"
  path.write_bytes(path.read_bytes() + b"\n// unpacked change\n")
  with pytest.raises(DependencyError, match="重新打包"):
    dep.recipe_digest(repository)


def test_pnpm_original_archive_integrity_checked_before_extraction(tmp_path):
  lock = dep.read_lock(REPO)
  metadata = {**lock.metadata, "pnpm_integrity": "sha512-incorrect"}
  with pytest.raises(DependencyError, match="完整性"):
    dep.prepare_pnpm(REPO, tmp_path, metadata)
  assert not (tmp_path / ".tooling").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "escape"])
def test_pnpm_archive_rejects_links_and_path_escape(tmp_path, kind):
  repository = tmp_path / "repository"
  archive = repository / "locks/dsh/vendor/pnpm-11.19.0.tgz"
  archive.parent.mkdir(parents=True)
  content = io.BytesIO()
  with tarfile.open(fileobj=content, mode="w:gz") as bundle:
    member = tarfile.TarInfo("../outside" if kind == "escape" else "package/unsafe")
    if kind != "escape":
      member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
      member.linkname = "../../outside"
    bundle.addfile(member)
  archive.write_bytes(content.getvalue())
  metadata = {"pnpm": "11.19.0", "pnpm_integrity": "sha512-" + base64.b64encode(hashlib.sha512(content.getvalue()).digest()).decode()}
  stage = tmp_path / "stage"
  stage.mkdir()
  with pytest.raises(DependencyError, match="结构不安全"):
    dep.prepare_pnpm(repository, stage, metadata)
  assert not (tmp_path / "outside").exists()


def test_installer_resolution_requires_exact_declared_specs():
  lock = dep.read_lock(REPO)
  package = json.loads(lock.package)
  package["dependencies"]["@deepseek-ai/dsh"] = "0.2.0-rc.3"
  with pytest.raises(ValueError):
    dep.validate_installer_resolution(json.dumps(package).encode(), lock.installer_resolution)


@pytest.mark.parametrize("location", [
  "package", "package-dependencies", "package-entry", "installer", "importers",
  "root-importer", "importer-dependencies", "importer-entry",
])
@pytest.mark.parametrize("invalid", [None, [], "broken"])
def test_malformed_installer_structure_is_value_error_and_read_lock_config_error(tmp_path, location, invalid):
  repository = lock_repository(tmp_path)
  root = repository / "locks/dsh"
  package = json.loads((root / "package.json").read_bytes())
  installer = yaml.safe_load((root / "pnpm-lock.yaml").read_bytes())
  name = next(iter(package["dependencies"]))
  if location == "package":
    package = invalid
  elif location == "package-dependencies":
    package["dependencies"] = invalid
  elif location == "package-entry":
    package["dependencies"][name] = invalid
  elif location == "installer":
    installer = invalid
  elif location == "importers":
    installer["importers"] = invalid
  elif location == "root-importer":
    installer["importers"]["."] = invalid
  elif location == "importer-dependencies":
    installer["importers"]["."]["dependencies"] = invalid
  else:
    installer["importers"]["."]["dependencies"][name] = invalid
  package_bytes = json.dumps(package).encode()
  installer_bytes = yaml.safe_dump(installer).encode()
  with pytest.raises(ValueError):
    dep.validate_installer_resolution(package_bytes, installer_bytes)
  (root / "package.json").write_bytes(package_bytes)
  (root / "pnpm-lock.yaml").write_bytes(installer_bytes)
  with pytest.raises(ConfigError, match="lock-missing-or-stale"):
    dep.read_lock(repository)


@pytest.mark.parametrize("invalid", [123, None])
def test_installer_package_keys_are_strings_and_read_lock_config_error(tmp_path, invalid):
  repository = lock_repository(tmp_path)
  root = repository / "locks/dsh"
  package_bytes = (root / "package.json").read_bytes()
  installer = yaml.safe_load((root / "pnpm-lock.yaml").read_bytes())
  name = next(iter(installer["packages"]))
  installer["packages"][invalid] = installer["packages"].pop(name)
  installer_bytes = yaml.safe_dump(installer).encode()
  with pytest.raises(ValueError, match="invalid frozen installer package name"):
    dep.validate_installer_resolution(package_bytes, installer_bytes)
  (root / "pnpm-lock.yaml").write_bytes(installer_bytes)
  with pytest.raises(ConfigError, match="lock-missing-or-stale"):
    dep.read_lock(repository)


def test_read_lock_rejects_missing_pnpm_integrity_even_with_recomputed_identity(tmp_path):
  repository = lock_repository(tmp_path)
  root = repository / "locks/dsh"
  installer = yaml.safe_load((root / "pnpm-lock.yaml").read_bytes())
  next(iter(installer["packages"].values()))["resolution"].pop("integrity")
  data = yaml.safe_dump(installer).encode()
  (root / "pnpm-lock.yaml").write_bytes(data)
  metadata = json.loads((root / "manifest.json").read_bytes())
  metadata["identity"] = dep.lock_identity((root / "package.json").read_bytes(), b"", metadata, data)
  (root / "manifest.json").write_text(json.dumps(metadata))
  with pytest.raises(ConfigError):
    dep.read_lock(repository)


@pytest.mark.parametrize("spec", ["*", "execa@10.1.1", "@deepseek-harness-tui/dsh-tui@latest", "@deepseek-harness-tui/dsh-tui@0.14.0"])
def test_release_age_exception_rejects_unselected_or_unbounded_versions(tmp_path, spec):
  repository = lock_repository(tmp_path)
  path = repository / "agents/dsh/lock-policy.json"
  policy = json.loads(path.read_bytes())
  policy["minimum_release_age_exclude"] = [spec]
  path.write_text(json.dumps(policy))
  with pytest.raises(ValueError):
    dep.lock_policy(repository)


def test_release_age_exception_is_locked_and_cannot_drift(tmp_path):
  repository = lock_repository(tmp_path)
  lock = dep.read_lock(repository)
  dep.prepare_pnpm_policy(tmp_path, lock.metadata)
  assert yaml.safe_load((tmp_path / "pnpm-workspace.yaml").read_bytes()) == {
    "minimumReleaseAgeStrict": True,
    "minimumReleaseAgeExclude": lock.metadata["minimum_release_age_exclude"],
  }
  changed = {**lock.metadata, "minimum_release_age_exclude": []}
  assert dep.lock_identity(lock.package, lock.resolution, changed, lock.installer_resolution) != lock.identity
  path = repository / "locks/dsh/manifest.json"
  path.write_text(json.dumps(changed))
  with pytest.raises(ConfigError):
    dep.read_lock(repository)


@pytest.mark.parametrize("version", ["*", "latest"])
def test_release_age_exception_rejects_mutable_input_before_resolution(tmp_path, version):
  repository = lock_repository(tmp_path)
  path = repository / "agents/dsh/dependencies.json"
  package = json.loads(path.read_bytes())
  package["dependencies"]["@deepseek-harness-tui/dsh-tui"] = version
  path.write_text(json.dumps(package))
  path = repository / "agents/dsh/lock-policy.json"
  policy = json.loads(path.read_bytes())
  policy["packages"] = package["dependencies"]
  policy["minimum_release_age_exclude"] = ["@deepseek-harness-tui/dsh-tui@" + version]
  path.write_text(json.dumps(policy))
  with pytest.raises(ValueError):
    dep.lock_policy(repository)


@pytest.mark.parametrize("spec", ["@deepseek-ai/dsh-agent@0.2.1-rc.1", "@deepseek-ai/dsh-*@0.2.1-rc.2",
  "@deepseek-ai/cordis@4.0.5", "@deepseek-ai/dsh-agent@latest"])
def test_core_release_age_exceptions_must_name_exact_selected_release(spec):
  packages = {"@deepseek-ai/dsh": "0.2.1-rc.2", "@deepseek-harness-tui/dsh-tui": "file:vendor/tui.tgz"}
  assert not dep.valid_release_age_exceptions({"minimum_release_age_exclude": [spec]}, packages)
  assert dep.valid_release_age_exceptions({"minimum_release_age_exclude": ["@deepseek-ai/dsh-agent@0.2.1-rc.2"]}, packages)


@pytest.mark.parametrize("version, spec, accepted", [
  ("0.15.0", "dsh-auto-review@0.15.0", True),
  ("0.15.0", "dsh-auto-review@0.14.0", False),
  ("0.15.0", "dsh-auto-review@latest", False),
  ("0.15.0", "dsh-auto-review@*", False),
  ("0.15.0", "dsh-auto-review@^0.15.0", False),
  ("latest", "dsh-auto-review@latest", False),
  ("*", "dsh-auto-review@*", False),
  ("^0.15.0", "dsh-auto-review@^0.15.0", False),
  ("0.15.0-rc.1", "dsh-auto-review@0.15.0-rc.1", False),
  ("0.15.0", "other-review@0.15.0", False),
])
def test_perry_release_age_exception_requires_exact_selected_stable_version(version, spec, accepted):
  assert dep.valid_release_age_exceptions({"minimum_release_age_exclude": [spec]},
    {"dsh-auto-review": version}) is accepted


@pytest.mark.parametrize("spec", ["@deepseek-ai/dsh-agent@0.2.1-rc.2", "dsh-auto-review@0.15.0"])
def test_release_age_exception_requires_package_in_complete_lock(spec):
  policy = {"minimum_release_age_exclude": [spec]}
  with pytest.raises(ValueError, match="absent"):
    dep.validate_release_age_resolution(policy, yaml.safe_dump({"packages": {"fixture@1.0.0": {}}}))
  dep.validate_release_age_resolution(policy, yaml.safe_dump({"packages": {spec: {}}}))


@pytest.mark.parametrize("change", ["commit", "archive-content", "modified-source", "unknown-field", "build-commit", "build-repository", "build-patch"])
def test_tui_source_archive_requires_matching_immutable_receipt(tmp_path, change):
  vendor = tmp_path / "locks/dsh/vendor"
  vendor.mkdir(parents=True)
  archive = vendor / "tui.tgz"
  package = json.dumps({"name": "@deepseek-harness-tui/dsh-tui", "version": "0.15.0"}).encode()
  with tarfile.open(archive, "w:gz") as bundle:
    member = tarfile.TarInfo("package/package.json")
    member.size = len(package)
    bundle.addfile(member, io.BytesIO(package))
  document = {"schema_version": 1, "package": "@deepseek-harness-tui/dsh-tui", "version": "0.15.0",
    "repository": "https://github.com/ccch1mneyyy/dsh-TUI", "commit": "a" * 40,
    "archive": "vendor/tui.tgz", "integrity": "sha512-" + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode(),
    "source_modified": False, "build": {"commands": ["upstream build"], "source": {
      "commit": "a" * 40, "url": "https://github.com/ccch1mneyyy/dsh-TUI.git",
      "tracked_diff_clean": True, "patches_applied": False}}}
  receipt = vendor / "tui-main-provenance.json"
  receipt.write_text(json.dumps(document))
  policy = {"packages": {document["package"]: "file:vendor/tui.tgz"}, "upstream": {"tui": "a" * 40}}
  assert dep.tui_source_receipt(tmp_path, policy)
  if change == "commit":
    document["commit"] = "b" * 40
  elif change == "archive-content":
    archive.write_bytes(archive.read_bytes() + b"drift")
  elif change == "modified-source":
    document["source_modified"] = True
  elif change == "build-commit":
    document["build"]["source"]["commit"] = "b" * 40
  elif change == "build-repository":
    document["build"]["source"]["url"] = "https://example.invalid/other.git"
  elif change == "build-patch":
    document["build"]["source"]["patches_applied"] = True
  else:
    document["unknown"] = True
  receipt.write_text(json.dumps(document))
  with pytest.raises(DependencyError, match="来源收据"):
    dep.tui_source_receipt(tmp_path, policy)


def test_current_recipe_uses_official_tui_and_opt_in_agent_teams():
  policy = dep.lock_policy(REPO)
  plugins = tomllib.loads((REPO / "agents/dsh/plugins.toml").read_text())["plugins"]
  agent = tomllib.loads((REPO / "agents/dsh/agent.toml").read_text())
  assert policy["packages"]["@deepseek-harness-tui/dsh-tui"] == "0.17.0"
  assert policy["upstream"]["tui"] == agent["tui_commit"] == "103834cb1000a84569a71646fec7162f18a058c8"
  assert plugins["tui"]["version"] == plugins["codex-auth"]["version"] == "0.17.0"
  assert dep.tui_source_receipt(REPO, policy) == b""
  assert "agent-teams" not in agent["defaults"]["plugins"]
  assert plugins["agent-teams"] == {"package": "@deepseek-ai/dsh-experimental-agent-team-profile",
    "version": "0.2.1-rc.3", "bundled": False, "enabled": True, "requires": ["tui"], "conflicts": []}
  for name in ("dsh-experimental-agent-team-profile", "dsh-experimental-agent-team",
      "dsh-experimental-tool-agent-team", "dsh-experimental-client-ui-agent-team"):
    assert policy["packages"]["@deepseek-ai/" + name] == "0.2.1-rc.3"
    assert "@deepseek-ai/" + name + "@0.2.1-rc.3" in policy["minimum_release_age_exclude"]


@pytest.mark.parametrize("directory, version", [("cursor-terminal", "0.1.4"), ("ssh-subscription-auth", "0.1.2")])
def test_declared_wrapper_metadata_requires_matching_archive(tmp_path, directory, version):
  repository = lock_repository(tmp_path)
  path = repository / "agents/dsh/packages" / directory / "package.json"
  metadata = json.loads(path.read_bytes())
  assert metadata["version"] == version
  assert metadata["peerDependencies"]["@deepseek-harness-tui/dsh-tui"] == "0.17.0"
  dep.recipe_digest(repository)
  metadata["peerDependencies"]["@deepseek-harness-tui/dsh-tui"] = "0.0.0"
  path.write_text(json.dumps(metadata))
  with pytest.raises(DependencyError, match="重新打包"):
    dep.recipe_digest(repository)
