"""只用合成账户路径和 fake spawn 验证 OMP 执行环境契约。"""

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import deployment, runtime
from agentcfg.adapter import SecretRef
from agentcfg.omp import CALLER_IDENTITY_ENV, OmpAdapter
from agentcfg.omp_execution_environment import XDG_KEYS
from agentcfg.omp_identity import native_identity
from agentcfg.render import RenderCandidate
from agentcfg.schema import ConfigError
from agentcfg.secrets import SecretStore
from agentcfg.storage import Conflict, Tree


REPO = Path(__file__).resolve().parents[1]
_OLD_SOURCE_DIGEST = "4b181b2b4f3dd6e440f1052446e25dabc0ea47fead656c56e243872fee5c221b"


class ContractBackend:
  def runtime_identity(self, workspace, lock):
    return lock.identity

  def root(self, workspace, identity):
    return workspace.cache / "runtimes" / identity

  def status(self, workspace, identity):
    return "installed"

  @contextmanager
  def runtime_guard(self, workspace, identity):
    root = self.root(workspace, identity)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root / ".package.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
      fcntl.flock(fd, fcntl.LOCK_SH)
      yield fd
    finally:
      os.close(fd)

  def executable_paths(self, root):
    return (root / "bin",)


@pytest.fixture
def contract_workspace(tmp_path, isolated_environment, monkeypatch):
  for name in CALLER_IDENTITY_ENV:
    monkeypatch.delenv(name, raising=False)
  tool_home = isolated_environment.home
  monkeypatch.setenv("XDG_RUNTIME_DIR", str(tool_home / "runtime"))
  (tool_home / "runtime").mkdir()
  user_bin = tool_home / "user-bin"
  user_bin.mkdir()
  (user_bin / "fixture-command").write_text("#!/bin/sh\nexit 0\n")
  monkeypatch.setenv("PATH", str(user_bin))
  global_config = tool_home / "global.gitconfig"
  global_config.write_text("[user]\n  name = Synthetic User\n")
  (tool_home / ".gitconfig").write_text("[core]\n  editor = synthetic-editor\n")
  zdotdir = tool_home / "zdotdir"
  zdotdir.mkdir()
  (zdotdir / ".zshrc").write_text("# synthetic shell config\n")
  library = tool_home / "libraries"
  library.mkdir()
  public = {"GIT_CONFIG_GLOBAL": str(global_config), "ZDOTDIR": str(zdotdir),
    "LD_LIBRARY_PATH": str(library), "TERM": "synthetic-terminal"}
  for name, value in public.items():
    monkeypatch.setenv(name, value)
  monkeypatch.setenv("API_KEY", "synthetic-ambient-must-not-forward")
  monkeypatch.setenv("ENV_CANARY", "synthetic-unknown-must-not-forward")
  caller = {name: os.environ.get(name) for name in ("HOME", *XDG_KEYS)}
  profile = "execution-contract"
  data = {
    "machine": {"id": "fixture", "paths": {"instances_root": str(tmp_path / "instances"),
      "state_root": str(tmp_path / "state"), "cache_root": str(tmp_path / "cache")},
      "environment": {"inherit": [], "values": {}}},
    "profile": {"id": profile, "agent": "omp", "providers": ["fixture-provider"],
      "models": [], "rules": [], "skills": [], "plugins": [], "mcp": [], "roles": {},
      "agent_options": {"discovery": {"project_resources": False, "project_roots": []},
        "resources": {"prompts": [], "themes": []}}},
    "providers": {"fixture-provider": {"protocol": "openai-compatible", "auth_kind": "api-key",
      "base_url": "https://fixture.invalid/v1", "credential_ref": "secret:fixture-key"}},
    "models": {}, "mcp": {},
  }
  adapter = OmpAdapter(REPO)
  workspace = SimpleNamespace(profile=profile, instance=tmp_path / "instances/omp" / profile,
    state_root=tmp_path / "state/omp" / profile, cache=tmp_path / "cache/omp" / profile,
    binding={"machine": "fixture", "local": str(tmp_path / "local.toml"), "profile": profile},
    resolved=SimpleNamespace(data=data), adapter=adapter, backend=ContractBackend(),
    secret_store=SecretStore({"fixture-key": "synthetic-resolved-internally"}),
    repository=REPO, local_path=tmp_path / "local.toml")
  lock = SimpleNamespace(identity="d" * 64)
  cwd = tmp_path / "project"
  cwd.mkdir()
  # 只排除测试编排器在 /tmp 等真实祖先中的来源，保留合成项目门禁。
  monkeypatch.setattr("agentcfg.omp_discovery.source_present", lambda path:
    path.is_relative_to(tmp_path) and (path.exists() or path.is_symlink()))
  return SimpleNamespace(workspace=workspace, lock=lock, cwd=cwd, caller=caller,
    public=public, user_bin=user_bin, tool_home=tool_home)


def _apply(fixture, *, contract=None, generation="fixture"):
  workspace = fixture.workspace
  contract = runtime.record(workspace, fixture.lock) if contract is None else contract
  candidate = RenderCandidate(generation, workspace.adapter.render(workspace.resolved.data))
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, contract)
  return contract


def _saved(workspace):
  with Tree(workspace.state_root) as tree:
    return tree.read("deployment.json")[0]


def _legacy(fixture, *, old_source_digest=False):
  contract = deepcopy(runtime.record(fixture.workspace, fixture.lock))
  for name in ("environment_version", "environment_policy", "caller_paths"):
    contract.pop(name, None)
  contract["adapter_binding"].pop("execution_environment", None)
  if old_source_digest:
    contract["adapter_binding"]["source_policy"]["manifest_sha256"] = _OLD_SOURCE_DIGEST
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  old_paths = {"HOME": identity.home, "XDG_CONFIG_HOME": identity.xdg_config,
    "XDG_DATA_HOME": identity.xdg_data, "XDG_STATE_HOME": identity.xdg_state,
    "XDG_CACHE_HOME": identity.xdg_cache}
  contract["environment"] = [item for item in contract["environment"]
    if item["name"] not in {"HOME", *XDG_KEYS, "PI_CONFIG_DIR"}]
  contract["environment"] += [{"name": name, "required": True, "literal": str(path)}
    for name, path in old_paths.items()]
  return contract


def _native_sentinels(fixture):
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  identity.agent_dir.mkdir(parents=True, exist_ok=True)
  paths = [identity.agent_dir / name for name in
    ("agent.db", "history.db", "models.db", "secret-placeholder.key")]
  paths.append(identity.agent_dir / "sessions/existing-session.jsonl")
  for path in paths:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-native-private-body")
  return identity, paths


@contextmanager
def _forbid_native_reads(monkeypatch, paths):
  original = os.open
  original_path_open = Path.open
  basenames = {path.name for path in paths}

  def guarded(path, flags, *args, **kwargs):
    if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).name in basenames:
      raise AssertionError("native account/session body must not be opened")
    return original(path, flags, *args, **kwargs)

  def guarded_path_open(path, *args, **kwargs):
    if path.name in basenames:
      raise AssertionError("native account/session body must not be opened")
    return original_path_open(path, *args, **kwargs)

  with monkeypatch.context() as patch:
    patch.setattr(os, "open", guarded)
    patch.setattr(Path, "open", guarded_path_open)
    yield


def test_current_contract_preserves_tool_home_xdg_and_public_shell_policy(contract_workspace, fake_subprocess):
  fixture = contract_workspace
  contract = _apply(fixture)
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  binding = contract["adapter_binding"]["execution_environment"]
  assert binding["home"] == str(fixture.tool_home)
  assert binding["native_paths"]["agent_dir"] == str(identity.agent_dir)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(fixture.workspace, cwd=fixture.cwd) == 0
  env = fake_subprocess.calls[-1]["env"]
  for name, value in fixture.caller.items():
    assert env.get(name) == value
  assert env["PI_CONFIG_DIR"] == binding["config_dir"]
  assert os.path.normpath(os.path.join(env["HOME"], env["PI_CONFIG_DIR"])) == str(identity.home / ".omp")
  for name, value in fixture.public.items():
    assert env[name] == value
  assert str(fixture.user_bin) in env["PATH"].split(os.pathsep)
  assert "API_KEY" not in env and "ENV_CANARY" not in env
  secret_bindings = [item for item in contract["environment"] if "secret_ref" in item]
  assert secret_bindings
  for item in secret_bindings:
    assert env[item["name"]] == fixture.workspace.secret_store.resolve(SecretRef(item["secret_ref"]))


def test_current_contract_keeps_unset_xdg_unset(contract_workspace, fake_subprocess, monkeypatch):
  fixture = contract_workspace
  for name in XDG_KEYS:
    monkeypatch.delenv(name, raising=False)
  contract = _apply(fixture)
  assert contract["adapter_binding"]["execution_environment"]["xdg"] == {name: None for name in XDG_KEYS}
  fake_subprocess.queue(returncode=0)
  assert runtime.run(fixture.workspace, cwd=fixture.cwd) == 0
  env = fake_subprocess.calls[-1]["env"]
  assert env["HOME"] == str(fixture.tool_home)
  assert not set(XDG_KEYS) & env.keys()


def test_unrelated_tool_home_omp_installation_does_not_block_managed_launch(contract_workspace, fake_subprocess):
  fixture = contract_workspace
  unrelated = fixture.tool_home / ".omp"
  (unrelated / "agent").mkdir(parents=True)
  (unrelated / ".env").write_text("SYNTHETIC=unrelated\n")
  (unrelated / "agent/config.yml").write_text("unrelated: true\n")
  _apply(fixture)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(fixture.workspace, cwd=fixture.cwd) == 0
  assert fake_subprocess.calls[-1]["env"]["HOME"] == str(fixture.tool_home)


def test_old_state_home_dotenv_is_not_a_new_session_source(contract_workspace, fake_subprocess):
  fixture = contract_workspace
  _apply(fixture)
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  (identity.home / ".env").write_text("SYNTHETIC=unused-old-home\n")
  fake_subprocess.queue(returncode=0)
  assert runtime.run(fixture.workspace, cwd=fixture.cwd) == 0


@pytest.mark.parametrize("after_prepare", [False, True])
def test_neutral_operation_rejects_its_actual_cwd_dotenv(contract_workspace, fake_subprocess, monkeypatch, after_prepare):
  fixture = contract_workspace
  _apply(fixture)
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  def introduce():
    (identity.home / ".env.development.local").write_text("SYNTHETIC=must-not-load\n")
  if after_prepare:
    original = fixture.workspace.adapter.validate_runtime
    def prepare(workspace, root):
      original(workspace, root)
      introduce()
    monkeypatch.setattr(fixture.workspace.adapter, "validate_runtime", prepare)
  else:
    introduce()
  with pytest.raises(Conflict, match="dotenv"):
    runtime.run(fixture.workspace, cwd=fixture.cwd, arguments=["usage"])
  assert not fake_subprocess.calls


@pytest.mark.parametrize("binding_is_current", [False, True])
def test_mixed_legacy_and_current_launch_contract_is_rejected(contract_workspace, fake_subprocess, binding_is_current):
  fixture = contract_workspace
  current = runtime.record(fixture.workspace, fixture.lock)
  legacy = _legacy(fixture)
  contract = deepcopy(current if binding_is_current else legacy)
  contract["environment"] = (legacy if binding_is_current else current)["environment"]
  _apply(fixture, contract=contract)
  with pytest.raises(ConfigError, match="environment-mismatch"):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


def test_identity_diagnostics_distinguishes_tool_home_from_native_storage(contract_workspace):
  fixture = contract_workspace
  report = fixture.workspace.adapter.identity_diagnostics(fixture.workspace)
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  assert report["home"] == report["state_home"] == str(identity.home)
  assert report["planned_execution_environment"]["home"] == str(fixture.tool_home)
  assert report["planned_execution_environment"]["scope"] == "planned-not-deployed"
  assert "synthetic-ambient" not in str(report)


@pytest.mark.parametrize("name", ["HOME", *XDG_KEYS])
def test_saved_environment_drift_rejects_spawn(contract_workspace, fake_subprocess, monkeypatch, name):
  fixture = contract_workspace
  _apply(fixture)
  before = _saved(fixture.workspace)
  monkeypatch.setenv(name, str(fixture.tool_home / (name.lower() + "-changed")))
  with pytest.raises(Conflict):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls
  assert _saved(fixture.workspace) == before


@pytest.mark.parametrize("category", ["DATA", "STATE", "CACHE"])
@pytest.mark.parametrize("profile", [False, True])
def test_new_xdg_redirection_rejects_spawn(contract_workspace, fake_subprocess, category, profile):
  fixture = contract_workspace
  _apply(fixture)
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  root = Path(fixture.caller["XDG_" + category + "_HOME"]) / "omp"
  if profile:
    root = root / "profiles" / identity.native_name
  root.mkdir(parents=True)
  with pytest.raises(Conflict):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


def test_caller_pi_config_injection_remains_forbidden(contract_workspace, fake_subprocess, monkeypatch):
  fixture = contract_workspace
  _apply(fixture)
  monkeypatch.setenv("PI_CONFIG_DIR", ".synthetic-injected")
  with pytest.raises(ConfigError):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


def test_final_environment_pi_config_injection_rejected(contract_workspace, fake_subprocess, monkeypatch):
  fixture = contract_workspace
  _apply(fixture)
  original = runtime.prepare_environment

  def injected(*args, **kwargs):
    env, report = original(*args, **kwargs)
    env["PI_CONFIG_DIR"] = ".synthetic-injected"
    return env, report

  monkeypatch.setattr(runtime, "prepare_environment", injected)
  with pytest.raises((ConfigError, Conflict)):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


@pytest.mark.parametrize("location", ["profile", "project"])
@pytest.mark.parametrize("after_prepare", [False, True])
def test_declared_staging_mode_is_checked_before_spawn_and_after_prepare(
    contract_workspace, fake_subprocess, monkeypatch, location, after_prepare):
  fixture = contract_workspace
  fixture.workspace.resolved.data["machine"]["environment"]["values"]["NODE_ENV"] = "staging"
  _apply(fixture)
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  source = (identity.agent_dir.parent if location == "profile" else fixture.cwd) / ".env.staging.local"

  def introduce():
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("SYNTHETIC_PRIVATE_BODY=must-not-read\n")

  if after_prepare:
    original = fixture.workspace.adapter.validate_runtime

    def prepare(workspace, root):
      original(workspace, root)
      introduce()

    monkeypatch.setattr(fixture.workspace.adapter, "validate_runtime", prepare)
  else:
    introduce()
  with pytest.raises(Conflict, match="dotenv"):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


def test_symlink_introduced_after_apply_rejects_spawn(contract_workspace, fake_subprocess):
  fixture = contract_workspace
  _apply(fixture)
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  (identity.agent_dir / "history.db").symlink_to(identity.agent_dir / "missing-history")
  with pytest.raises(Conflict):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


@pytest.mark.parametrize("old_source_digest", [False, True])
def test_legacy_run_keeps_isolated_environment_and_does_not_upgrade_saved_binding(
    contract_workspace, fake_subprocess, old_source_digest):
  fixture = contract_workspace
  contract = _legacy(fixture, old_source_digest=old_source_digest)
  _apply(fixture, contract=contract)
  before = _saved(fixture.workspace)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(fixture.workspace, cwd=fixture.cwd) == 0
  env = fake_subprocess.calls[-1]["env"]
  identity = native_identity(fixture.workspace.profile, fixture.workspace.instance)
  assert env["HOME"] == str(identity.home)
  assert env["XDG_CONFIG_HOME"] == str(identity.xdg_config)
  assert env["XDG_DATA_HOME"] == str(identity.xdg_data)
  assert env["XDG_STATE_HOME"] == str(identity.xdg_state)
  assert env["XDG_CACHE_HOME"] == str(identity.xdg_cache)
  assert "XDG_RUNTIME_DIR" not in env and "PI_CONFIG_DIR" not in env
  assert _saved(fixture.workspace) == before


@pytest.mark.parametrize("damage", ["unknown-manifest", "project-roots", "storage"])
def test_legacy_compatibility_does_not_relax_saved_scope(contract_workspace, fake_subprocess, damage):
  fixture = contract_workspace
  contract = _legacy(fixture, old_source_digest=True)
  saved = contract["adapter_binding"]
  if damage == "unknown-manifest":
    saved["source_policy"]["manifest_sha256"] = "e" * 64
  elif damage == "project-roots":
    saved["source_policy"]["project_resources"] = True
    saved["source_policy"]["project_roots"] = [str(fixture.cwd)]
  else:
    saved["storage"]["state_root"] += "-foreign"
  _apply(fixture, contract=contract)
  with pytest.raises(Conflict):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


def test_environment_only_apply_rollback_preserves_account_session_and_owner(
    contract_workspace, fake_subprocess, monkeypatch, sentinel_factory):
  fixture = contract_workspace
  legacy = _legacy(fixture)
  _apply(fixture, contract=legacy, generation="legacy")
  identity, native_paths = _native_sentinels(fixture)
  sentinels = [sentinel_factory(path) for path in native_paths]
  owner = sentinel_factory(fixture.workspace.instance / ".agentcfg-omp-owner.json")
  current = runtime.record(fixture.workspace, fixture.lock)
  assert "execution_environment" in current["adapter_binding"]
  with _forbid_native_reads(monkeypatch, native_paths):
    _apply(fixture, contract=current, generation="current")
    with fixture.workspace.adapter.apply_lifecycle_guard(fixture.workspace):
      deployment.rollback(fixture.workspace.instance, fixture.workspace.state_root, fixture.workspace.binding)
    fake_subprocess.queue(returncode=0)
    assert runtime.run(fixture.workspace, cwd=fixture.cwd) == 0
  assert fake_subprocess.calls[-1]["env"]["HOME"] == str(identity.home)
  for sentinel in (*sentinels, owner):
    sentinel.assert_unchanged()
