"""整体 review 的正式回归：断言修复后的行为，全部隔离且不启动宿主。"""

import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from agentcfg import cli, commands, dependencies as dep, profile_runtime, runtime, runtime_packages
from agentcfg.config import read_local_document
from agentcfg.deployment import json_bytes
from agentcfg.schema import ConfigError
from agentcfg.secrets import CredentialError, SecretStore, credential_id
from agentcfg.adapter import SecretRef
from agentcfg.storage import Conflict, Tree, ensure_private, instance_lock
from agentcfg.workspace import load_workspace


REPO = Path(__file__).resolve().parents[1]


def local(tmp_path, extra=""):
  path = tmp_path / "local.toml"
  path.write_text('schema_version=1\n[machine]\nid="review"\n' + extra)
  path.chmod(0o600)
  return path


@pytest.mark.parametrize("kind", ["mode", "symlink", "directory-link", "hardlink", "fifo", "parent-mode"])
def test_private_input_rejected_before_read(tmp_path, monkeypatch, kind):
  path = local(tmp_path)
  if kind == "mode":
    path.chmod(0o644)
  elif kind == "symlink":
    link = tmp_path / "link.toml"
    link.symlink_to(path)
    path = link
  elif kind == "directory-link":
    folder = tmp_path / "link"
    folder.symlink_to(tmp_path, target_is_directory=True)
    path = folder / "local.toml"
  elif kind == "hardlink":
    os.link(path, tmp_path / "alias")
  elif kind == "fifo":
    path.unlink()
    os.mkfifo(path)
  else:
    tmp_path.chmod(0o755)
  def no_body(*args, **kwargs):
    pytest.fail("must reject before reading body")
  monkeypatch.setattr("agentcfg.paths.os.fdopen", no_body)
  assert cli.main(["--local", str(path), "validate"]) == 4


def test_private_file_identity_race(tmp_path, monkeypatch):
  path = local(tmp_path)
  original = os.open
  def race(name, flags, *args, **kwargs):
    fd = original(name, flags, *args, **kwargs)
    if name == "local.toml":
      path.write_text("synthetic changed before reading")
    return fd
  monkeypatch.setattr("agentcfg.paths.os.open", race)
  with pytest.raises(Conflict):
    read_local_document(path)


@pytest.mark.parametrize("failure", ["prepare-owner", "package", "link", "commit-owner"])
def test_profile_first_preparation_recovers(tmp_path, monkeypatch, failure):
  w = load_workspace(local(tmp_path))
  root = w.instance / "runtimes/fixture"
  ensure_private(root)
  write, mkdir = Tree.write_state, os.mkdir
  calls = 0
  def failing_write(self, name, data):
    nonlocal calls
    if name == ".agentcfg-package-owner.json":
      calls += 1
      if (failure == "prepare-owner" and calls == 1) or (failure == "commit-owner" and calls == 2):
        raise OSError("synthetic interruption")
    if name == "package.json" and failure == "package":
      raise OSError("synthetic interruption")
    return write(self, name, data)
  def failing_mkdir(name, *args, **kwargs):
    if name == "node_modules" and kwargs.get("dir_fd") is not None and failure == "link":
      raise OSError("synthetic interruption")
    return mkdir(name, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", failing_write)
    patch.setattr(os, "mkdir", failing_mkdir)
    with pytest.raises(OSError):
      profile_runtime.prepare(w, root)
  profile = profile_runtime.prepare(w, root)
  assert (profile / "node_modules").is_dir()
  assert not (profile / "node_modules").is_symlink()
  for package in profile_runtime.PROFILE_PROJECTIONS:
    assert os.readlink(profile / "node_modules" / package) == str(root / "node_modules" / package)
  assert "pending_runtime" not in json.loads((profile / ".agentcfg-package-owner.json").read_text())


def test_profile_migrates_owned_runtime_link_to_isolated_directory(tmp_path):
  w = load_workspace(local(tmp_path))
  root = w.instance / "runtimes/fixture"
  ensure_private(root / "node_modules")
  profile = w.instance / "dsh-home/profiles/agentcfg"
  ensure_private(profile)
  manifest = {"name": "agentcfg-managed-profile", "version": "1.0.0", "private": True,
    "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-harness-tui/dsh-tui"]}}}
  destination = str(root / "node_modules")
  (profile / "package.json").write_bytes(json_bytes(manifest))
  owner = profile / ".agentcfg-package-owner.json"
  owner.write_bytes(json_bytes({"binding": w.binding, "runtime": destination}))
  owner.chmod(0o600)
  (profile / "node_modules").symlink_to(destination)
  profile_runtime.prepare(w, root)
  assert (profile / "node_modules").is_dir()
  assert not (profile / "node_modules").is_symlink()
  assert json.loads((profile / ".agentcfg-package-owner.json").read_text()) == {
    "binding": w.binding, "modules": "isolated",
    "projections": {package: str(root / "node_modules" / package)
                    for package in profile_runtime.PROFILE_PROJECTIONS}}


def test_profile_upgrade_recovers_and_unknown_files_still_conflict(tmp_path, monkeypatch):
  w = load_workspace(local(tmp_path))
  a, b = w.instance / "runtimes/a", w.instance / "runtimes/b"
  profile = profile_runtime.prepare(w, a)
  original = Tree.write_state
  calls = 0
  def fail_final(self, name, data):
    nonlocal calls
    if name == ".agentcfg-package-owner.json":
      calls += 1
      if calls == 2:
        raise OSError("synthetic interruption")
    return original(self, name, data)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", fail_final)
    with pytest.raises(OSError):
      profile_runtime.prepare(w, b)
  profile_runtime.prepare(w, a)
  assert (profile / "node_modules").is_dir()
  assert not (profile / "node_modules").is_symlink()
  (profile / "package.json").write_text("unknown edit")
  with pytest.raises(Conflict):
    profile_runtime.prepare(w, a)


@pytest.mark.parametrize("name", runtime_packages.REQUIRED_FILES)
def test_runtime_receipt_detects_missing_or_changed_entry(tmp_path, prepared_runtime, name):
  w = load_workspace(local(tmp_path))
  lock = dep.read_lock(REPO)
  root = prepared_runtime(w, lock)
  assert dep.installed(w, lock)
  (root / name).write_bytes(b"corrupted")
  assert w.backend.status(w, lock.identity) == "damaged"
  (root / name).unlink()
  assert not dep.installed(w, lock)


def test_profile_fallback_writes_cannot_mutate_runtime(tmp_path):
  w = load_workspace(local(tmp_path))
  root = w.instance / "runtimes/fixture"
  ensure_private(root / "node_modules")
  profile = profile_runtime.prepare(w, root)
  fallback = profile / "node_modules/react-reconciler"
  fallback.symlink_to(profile / ".dsh-module-fallback/node_modules/react-reconciler")
  assert fallback.is_symlink()
  assert not (root / "node_modules/react-reconciler").exists()


def test_runtime_receipt_detects_dependency_topology_pollution(tmp_path, prepared_runtime):
  w = load_workspace(local(tmp_path))
  lock = dep.read_lock(REPO)
  root = prepared_runtime(w, lock)
  assert dep.installed(w, lock)
  (root / "node_modules/injected-package").symlink_to(root / "node_modules/react")
  assert not dep.installed(w, lock)


def installer(monkeypatch, lock):
  calls = []
  helper = b"synthetic audited helper"
  monkeypatch.setattr(dep, "AUDITED_HELPER_SHA256", hashlib.sha256(helper).hexdigest())
  def checked(argv, *, cwd, env):
    calls.append(argv)
    if argv == ["node", "--version"]:
      return lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return lock.metadata["npm"]
    if argv[:2] == ["npm", "ci"]:
      for name in runtime_packages.REQUIRED_FILES:
        if name in ("package.json", "package-lock.json"):
          continue
        path = cwd / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(helper if name.endswith("ensure-spawn-helper.mjs") else b"synthetic artifact")
    return ""
  monkeypatch.setattr(dep, "checked", checked)
  return calls


def test_sync_repairs_damaged_package_and_preserves_session(tmp_path, prepared_runtime, monkeypatch):
  w = load_workspace(local(tmp_path))
  lock = dep.read_lock(REPO)
  root = prepared_runtime(w, lock)
  (root / runtime_packages.REQUIRED_FILES[2]).unlink()
  session = w.instance / "session"
  session.write_text("keep native session")
  calls = installer(monkeypatch, lock)
  assert dep.sync(w, lock)["changed"]
  assert dep.installed(w, lock)
  assert session.read_text() == "keep native session"
  calls.clear()
  assert not dep.sync(w, lock)["changed"]
  assert not calls


def test_failed_repair_and_interrupted_activation_keep_old_package(tmp_path, prepared_runtime, monkeypatch):
  w = load_workspace(local(tmp_path))
  lock = dep.read_lock(REPO)
  final = prepared_runtime(w, lock)
  (final / runtime_packages.REQUIRED_FILES[2]).unlink()
  (final / "keep").write_text("old package")
  installer(monkeypatch, lock)
  rename = os.rename
  def fail_stage(source, target, **kwargs):
    if Path(source).name.startswith(".stage-"):
      raise OSError("synthetic activation failure")
    return rename(source, target, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(runtime_packages.os, "rename", fail_stage)
    with pytest.raises(OSError):
      dep.sync(w, lock)
  assert (final / "keep").read_text() == "old package"
  backup = final.parent / (".repair-" + lock.identity)
  os.rename(final, backup)
  assert dep.sync(w, lock)["changed"]
  assert dep.installed(w, lock)
  assert not backup.exists()


def test_pending_and_active_lock_prevent_sync_before_process(tmp_path, monkeypatch):
  w = load_workspace(local(tmp_path))
  lock = dep.read_lock(REPO)
  ensure_private(w.state_root)
  pending = w.state_root / "pending.json"
  pending.write_text("{}")
  monkeypatch.setattr(dep, "checked", lambda *args, **kwargs: pytest.fail("no install before recovery"))
  with pytest.raises(Conflict, match="恢复"):
    dep.sync(w, lock)
  assert not w.instance.exists()
  pending.unlink()
  with Tree(w.state_root) as state, instance_lock(state), pytest.raises(Conflict):
    dep.sync(w, lock)


def test_oauth_options_are_rejected_not_ignored(tmp_path):
  path = local(tmp_path, '[overrides.profiles.dsh-default.agent_options.provider_options.codex]\nreasoning="medium"\n')
  with pytest.raises(ConfigError, match="oauth-provider-options-not-supported"):
    load_workspace(path)


@pytest.mark.parametrize("field", ["platforms", "adapter_version", "upstream", "version"])
def test_lock_rejects_consistent_but_incompatible_metadata(tmp_path, field):
  repository = tmp_path / "repository"
  shutil.copytree(REPO / "locks", repository / "locks")
  shutil.copytree(REPO / "agents", repository / "agents")
  path = repository / "locks/dsh/manifest.json"
  metadata = json.loads(path.read_text())
  metadata[field] = {"unavailable": "not-smoked"} if field in ("platforms", "upstream") else "incompatible"
  metadata["identity"] = dep.lock_identity((repository / "locks/dsh/package.json").read_bytes(), (repository / "locks/dsh/package-lock.json").read_bytes(), metadata)
  path.write_text(json.dumps(metadata))
  with pytest.raises(ConfigError):
    dep.read_lock(repository)


def test_runtime_failure_identifies_secret_without_printing_reference():
  reference = "secret:private-name"
  with pytest.raises(CredentialError) as caught:
    SecretStore({}).resolve(SecretRef(reference))
  assert credential_id(reference) in str(caught.value)
  assert "private-name" not in str(caught.value)


def test_capture_preferences_generate_valid_private_proposal(tmp_path, capsys):
  from test_runtime import local_file
  path = tmp_path / "local.toml"
  local_file(path)
  w = load_workspace(path)
  ensure_private(w.instance / "user-home/.dsh-tui")
  (w.instance / "user-home/.dsh-tui/theme.json").write_text('{"theme":"dark","unknown":"not exported"}')
  (w.instance / "user-home/.dsh-tui/model.json").write_text('{"provider":"agentcfg-one","model":"fictional-model"}')
  assert cli.main(["--local", str(path), "capture"]) == 0
  result = json.loads(capsys.readouterr().out)
  proposal = json.loads(Path(result["proposal"]).read_text())
  assert proposal["overrides"]["profiles"]["dsh-default"] == {"agent_options": {"theme": "dark"}, "roles": {"main": "one"}}
  assert "fictional-model" not in json.dumps(result)
  assert "not exported" not in json.dumps(proposal)
  (w.instance / "user-home/.dsh-tui/model.json").write_text('{"provider":"oauth-cursor","model":"unknown-dynamic"}')
  assert cli.main(["--local", str(path), "capture"]) == 2
  assert "unknown-dynamic" not in capsys.readouterr().err


def test_plan_private_locations_and_deployed_credentials(tmp_path, capsys):
  from test_runtime import local_file, CANARY
  path = tmp_path / "local.toml"
  local_file(path)
  assert cli.main(["--local", str(path), "plan"]) == 0
  public = capsys.readouterr().out
  result = json.loads(public)
  location = Path(result["diagnostics"])
  detail = json.loads(location.read_text())
  assert {item["id"] for item in detail["targets"]} == {item["id"] for item in result["diff"]}
  assert any("agentcfg-one" in (item["selector"] or "") for item in detail["targets"])
  assert "agentcfg-one" not in public and CANARY not in public + location.read_text()
  assert location.stat().st_mode & 0o777 == 0o600
  assert detail["credentials"] == [{"id": credential_id("secret:one"), "reference": "secret:one"}]
