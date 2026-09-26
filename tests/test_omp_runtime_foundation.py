from pathlib import Path
from types import SimpleNamespace
import stat
from contextlib import contextmanager
import fcntl
import json
import os

import pytest
import yaml

from agentcfg.omp import validate_managed_argv, validate_model_selection
from agentcfg.omp_discovery import DISABLED_PROVIDERS, NATIVE_ROOT_PATTERNS, SourcePolicy, assert_clean_sources, assert_native_sources, discovery_manifest, manifest_digest
from agentcfg.omp_identity import native_identity
from agentcfg.omp_identity import lifecycle_guard
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from agentcfg.omp import OmpAdapter, CALLER_IDENTITY_ENV
from agentcfg.render import RenderCandidate
from agentcfg.secrets import SecretStore, CredentialError
from agentcfg import deployment, runtime
from agentcfg.process import DependencyError
from agentcfg import cli, commands


@pytest.mark.parametrize("args", [
  ["--profile", "other"], ["--profile=other"], ["--alias=x"], ["--config", "x"],
  ["--session-dir=x"], ["--extension=x"], ["-e", "x"], ["--trusted-extension=x"],
  ["--hook=x"], ["--plugin-dir=x"], ["--cwd=x"], ["--from-claude"], ["--from-codex"],
  ["--add-dir=x"], ["--api-key=x"], ["--auth-broker=x"], ["install"], ["update"],
  ["--continue"], ["--continue=session"], ["-c", "session"], ["--resume=x"], ["-r", "x"],
  ["--session=x"], ["--fork"], ["--fork=x"],
  ["--unknown-worker=x"], ["--system-prompt=x"], ["--tools=x"], ["--models=x"],
  ["__omp_worker_computer"], ["__omp_worker_blob_broker"],
  ["daemon"], ["serve"], ["commit"], ["plugin"], ["launch"], ["help"],
])
def test_token_aware_parser_rejects_managed_boundary(args):
  with pytest.raises(ConfigError):
    validate_managed_argv(args)


def test_token_aware_parser_does_not_scan_prompt_after_separator():
  validate_managed_argv(["--", "--profile=ordinary prompt", "install"])
  validate_managed_argv(["login", "openai-codex"])
  validate_managed_argv(["usage", "--", "daemon", "serve"])


def test_model_selector_is_exact_declared_remote_id_and_not_repeated():
  data = {"providers": {"p": {}}, "models": {"m": {"provider": "p", "remote_id": "exact"}}}
  validate_managed_argv(["--provider=p", "--model", "p/exact", "-p"])
  validate_model_selection(data, ["--provider=p", "--model", "p/exact"])
  with pytest.raises(ConfigError):
    validate_model_selection(data, ["--model", "other"])
  with pytest.raises(ConfigError):
    validate_model_selection(data, ["--model=p/exact", "--model", "p/exact"])
  with pytest.raises(ConfigError):
    validate_managed_argv(["-m", "p/exact"])


def test_default_discovery_rejects_ancestor_sources(tmp_path):
  root = tmp_path / "project"
  cwd = root / "nested"
  cwd.mkdir(parents=True)
  (root / ".env").write_text("SENTINEL=secret")
  with pytest.raises(Conflict):
    assert_clean_sources(cwd)


def test_discovery_manifest_has_exact_disabled_count():
  assert len(DISABLED_PROVIDERS) == 18
  assert len(set(DISABLED_PROVIDERS)) == 18
  assert DISABLED_PROVIDERS[0] == "agent-plugins"
  assert DISABLED_PROVIDERS[-1] == "windsurf"
  repository = Path(__file__).resolve().parents[1]
  manifest = json.loads((repository / "agents/omp/discovery-manifest.json").read_bytes())
  assert len(NATIVE_ROOT_PATTERNS) == 53
  assert manifest == discovery_manifest()
  for required in ("$ACTIVE_AGENT/SYSTEM.md", "$DEFAULT_AGENT/SYSTEM_TEMPLATE.md",
      "$ACTIVE_AGENT/PERSONALITY.md", "$DEFAULT_AGENT/PERSONALITY.md",
      "$ACTIVE_AGENT/.mcp.json", "$DEFAULT_AGENT/config.yml", "$ACTIVE_AGENT/models.yml"):
    assert required in NATIVE_ROOT_PATTERNS
  assert set(manifest["nativeControls"]["configExact"]) >= {"/extensions", "/skills/enablePiProject"}
  assert set(manifest["nativeControls"]["configForbidden"]) >= {"/skills/customDirectories", "/auth/broker"}
  assert manifest["ignoredProviderSources"]["reason"] == "all-loading-providers-disabled-before-discovery"
  assert manifest_digest() == "02346cb407b1c92e534fa28d73ce262aa5b65dd7722b610110b6ed7580659324"


def test_source_policy_rejects_roots_when_project_resources_are_off(tmp_path):
  with pytest.raises(ConfigError):
    SourcePolicy.from_options({"project_resources": False, "project_roots": [str(tmp_path)]})
  with pytest.raises(ConfigError):
    SourcePolicy.from_options({"project_resources": True, "project_roots": []})
  with pytest.raises(ConfigError):
    SourcePolicy.from_options({"project_resources": True, "project_roots": ["relative"]})


def test_profile_dotenv_and_auth_broker_are_rejected_without_reading_values(tmp_path):
  identity = native_identity("omp-test", tmp_path / "instance")
  identity.agent_dir.mkdir(parents=True)
  (identity.agent_dir / ".env").write_text("SENTINEL_SECRET=value")
  with pytest.raises(Conflict, match="dotenv") as caught:
    assert_native_sources(identity)
  assert "SENTINEL_SECRET" not in str(caught.value)
  (identity.agent_dir / ".env").unlink()
  (identity.agent_dir / "config.yml").write_text("auth:\n  broker:\n    url: https://broker.invalid\n")
  with pytest.raises(Conflict, match="认证"):
    assert_native_sources(identity)


@pytest.mark.parametrize("relative", [
  ".omp/.env", ".omp/agent/RULES.md", ".omp/agent/AGENTS.md", ".omp/agent/TITLE_SYSTEM.md",
  ".omp/plugins/installed_plugins.json", ".omp/marketplaces.json",
])
def test_native_home_direct_sources_are_rejected(tmp_path, relative):
  identity = native_identity("omp-test", tmp_path / "instance")
  path = identity.home / relative
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text("synthetic")
  with pytest.raises(Conflict):
    assert_native_sources(identity)


@pytest.mark.parametrize("unsafe", [
  {"memory": {"enabled": False, "backend": "mnemopi"}},
  {"eval": {"enabled": False, "autoProvision": True}},
  {"providers": {"tinyModel": "local/model"}},
  {"providers.tinyModelDevice": "cuda"},
])
def test_native_config_rejects_disabled_feature_bypass(tmp_path, unsafe):
  identity = native_identity("omp-test", tmp_path / "instance")
  identity.agent_dir.mkdir(parents=True)
  protected = {
    "skills": {"enablePiUser": True, "enablePiProject": False},
    "mcp": {"enableProjectConfig": False}, "startup": {"checkUpdate": False},
    "marketplace": {"autoUpdate": "off"}, "autolearn": {"enabled": False},
    "auth": {}, "enabledProviders": [], "disabledProviders": list(DISABLED_PROVIDERS),
  }
  protected.update(unsafe)
  (identity.agent_dir / "config.yml").write_text(yaml.safe_dump(protected))
  with pytest.raises(Conflict):
    assert_native_sources(identity)


def test_native_mcp_rejects_undeclared_server_even_when_file_is_managed(tmp_path):
  identity = native_identity("omp-test", tmp_path / "instance")
  identity.agent_dir.mkdir(parents=True)
  mcp = identity.agent_dir / "mcp.json"
  mcp.write_text(json.dumps({"mcpServers": {"echo": {"type": "stdio", "command": "/python", "args": []},
    "foreign": {"type": "stdio", "command": "/foreign", "args": []}}}))
  with pytest.raises(Conflict, match="未声明"):
    assert_native_sources(identity, (mcp,), {"echo": {"type": None, "command": None, "args": None}})


def workspace_for(tmp_path):
  return SimpleNamespace(profile="omp-test", instance=tmp_path / "instance", state_root=tmp_path / "state",
    cache=tmp_path / "cache", binding={"machine": "test", "local": str(tmp_path / "local.toml"), "profile": "omp-test"})


def test_physical_owner_is_created_only_by_apply_guard_and_binds_state(tmp_path):
  workspace = workspace_for(tmp_path)
  with pytest.raises(Conflict):
    with lifecycle_guard(workspace):
      pass
  assert not workspace.instance.exists()
  with lifecycle_guard(workspace, create=True):
    owner = workspace.instance / ".agentcfg-omp-owner.json"
    assert stat.S_IMODE(owner.stat().st_mode) == 0o600
    with pytest.raises(Conflict, match="活动"):
      with lifecycle_guard(workspace):
        pass
  other = workspace_for(tmp_path)
  other.state_root = tmp_path / "other-state"
  with pytest.raises(Conflict):
    with lifecycle_guard(other, create=True):
      pass


def test_physical_lock_mode_is_checked_before_owner(tmp_path):
  workspace = workspace_for(tmp_path)
  with lifecycle_guard(workspace, create=True):
    pass
  (workspace.instance / ".agentcfg-omp.lock").chmod(0o644)
  with pytest.raises(Conflict, match="权限"):
    with lifecycle_guard(workspace):
      pass


def test_unowned_nonempty_instance_is_unchanged_by_apply_guard(tmp_path):
  workspace = workspace_for(tmp_path)
  workspace.instance.mkdir(mode=0o700)
  sentinel = workspace.instance / "foreign.txt"
  sentinel.write_bytes(b"do-not-touch")
  before_entries = tuple(workspace.instance.iterdir())
  before_directory = workspace.instance.stat()
  before_sentinel = sentinel.stat()

  with pytest.raises(Conflict, match="非空"):
    with lifecycle_guard(workspace, create=True):
      pass

  after_directory = workspace.instance.stat()
  after_sentinel = sentinel.stat()
  assert tuple(workspace.instance.iterdir()) == before_entries
  assert sentinel.read_bytes() == b"do-not-touch"
  assert after_directory.st_mtime_ns == before_directory.st_mtime_ns
  assert after_sentinel.st_mtime_ns == before_sentinel.st_mtime_ns


class RuntimeBackend:
  def __init__(self, *, status="installed", mutate=None):
    self.result = status
    self.mutate = mutate

  def runtime_identity(self, workspace, lock):
    return lock.identity

  def root(self, workspace, identity):
    return workspace.cache / "runtimes" / identity

  def status(self, workspace, identity):
    if self.mutate:
      mutate, self.mutate = self.mutate, None
      mutate()
    return self.result

  @contextmanager
  def runtime_guard(self, workspace, identity):
    root = self.root(workspace, identity)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".package.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_SH)
    try:
      yield fd
    finally:
      os.close(fd)

  def executable_paths(self, root):
    return (root / "bin",)


def runtime_workspace(tmp_path, backend=None):
  instance = tmp_path / "private/omp/omp-test"
  machine = {"id": "runtime", "paths": {"instances_root": str(tmp_path / "private"),
    "state_root": str(tmp_path / "state-root"), "cache_root": str(tmp_path / "cache-root")},
    "environment": {"inherit": [], "values": {}}}
  profile = {"id": "omp-test", "agent": "omp", "providers": [], "models": [], "rules": [], "skills": [],
    "plugins": [], "mcp": [], "roles": {}, "agent_options": {"discovery": {"project_resources": False, "project_roots": []},
      "resources": {"prompts": [], "themes": []}}}
  data = {"machine": machine, "profile": profile, "providers": {}, "models": {}, "mcp": {}}
  adapter = OmpAdapter(Path(__file__).resolve().parents[1])
  workspace = SimpleNamespace(profile="omp-test", instance=instance, state_root=tmp_path / "state-root/omp/omp-test",
    cache=tmp_path / "cache-root/omp/omp-test", binding={"machine": "runtime", "local": str(tmp_path / "local.toml"), "profile": "omp-test"},
    resolved=SimpleNamespace(data=data), adapter=adapter, backend=backend or RuntimeBackend(), secret_store=SecretStore({}),
    repository=Path(__file__).resolve().parents[1], local_path=tmp_path / "local.toml")
  lock = SimpleNamespace(identity="f" * 64)
  candidate = RenderCandidate("generation", adapter.render(data))
  with adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, runtime.record(workspace, lock))
  return workspace, lock


def clear_omp_identity_environment(monkeypatch):
  for name in CALLER_IDENTITY_ENV:
    monkeypatch.delenv(name, raising=False)


def isolate_runtime_discovery(monkeypatch):
  # 宿主 /tmp 有测试编排器自己的 .omp/.agents/.codex；此批只观测合成 .env 漂移。
  monkeypatch.setattr("agentcfg.omp_discovery.DISCOVERY_NAMES", (".env",))


def test_runtime_integration_holds_three_leases_and_preserves_exit(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  cwd = tmp_path / "work"
  cwd.mkdir()
  fake_subprocess.queue(returncode=37)
  assert runtime.run(workspace, cwd=cwd) == 37
  assert len(fake_subprocess.calls[0]["pass_fds"]) == 3
  assert fake_subprocess.calls[0]["argv"][-1] == "--no-title"
  fake_subprocess.queue(returncode=-9)
  assert runtime.run(workspace, cwd=cwd) == 137


def test_runtime_rejects_missing_owner_pending_package_and_secret(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  cwd = tmp_path / "work"
  cwd.mkdir()
  empty, _ = runtime_workspace(tmp_path / "prepared")
  no_owner = SimpleNamespace(**vars(empty))
  no_owner.instance = tmp_path / "absent-instance"
  no_owner.state_root = tmp_path / "absent-state"
  with pytest.raises(Conflict):
    runtime.run(no_owner, cwd=cwd)
  assert not no_owner.instance.exists() and not no_owner.state_root.exists()

  with open(empty.state_root / "pending.json", "wb") as file:
    file.write(b"{}")
  os.chmod(empty.state_root / "pending.json", 0o600)
  with pytest.raises(Conflict):
    runtime.run(empty, cwd=cwd)
  (empty.state_root / "pending.json").unlink()

  empty.backend.result = "missing"
  with pytest.raises(DependencyError) as missing:
    runtime.run(empty, cwd=cwd)
  assert missing.value.exit_code == 5
  empty.backend.result = "installed"

  state = json.loads((empty.state_root / "deployment.json").read_bytes())
  state["current"]["launch"]["environment"].append({"name": "AGENTCFG_OMP_TEST", "required": True, "secret_ref": "secret:missing"})
  (empty.state_root / "deployment.json").write_bytes(deployment.json_bytes(state))
  os.chmod(empty.state_root / "deployment.json", 0o600)
  with pytest.raises(CredentialError) as secret:
    runtime.run(empty, cwd=cwd)
  assert secret.value.exit_code == 3
  assert not fake_subprocess.calls


def test_runtime_rechecks_sources_immediately_before_spawn(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  cwd = tmp_path / "work"
  cwd.mkdir()
  workspace.backend.mutate = lambda: (cwd / ".env").write_text("SENTINEL=private")
  with pytest.raises(Conflict, match="项目配置来源"):
    runtime.run(workspace, cwd=cwd)
  assert not fake_subprocess.calls


def test_runtime_rejects_actual_caller_identity_environment(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  cwd = tmp_path / "work"
  cwd.mkdir()
  monkeypatch.setenv("OMP_PROFILE", "foreign")
  with pytest.raises(ConfigError):
    runtime.run(workspace, cwd=cwd)
  assert not fake_subprocess.calls


def test_runtime_rejects_cache_root_changed_since_apply(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  cwd = tmp_path / "work"
  cwd.mkdir()
  workspace.cache = tmp_path / "moved-cache/omp/omp-test"
  workspace.resolved.data["machine"]["paths"]["cache_root"] = str(tmp_path / "moved-cache")
  with pytest.raises(Conflict, match="重新plan/apply"):
    runtime.run(workspace, cwd=cwd)
  assert not fake_subprocess.calls


def test_omp_lock_dispatches_before_local_workspace_or_secret_loading(monkeypatch, capsys):
  calls = []
  monkeypatch.setattr("agentcfg.omp_dependencies.OmpBackend.resolve_lock", lambda self, repository: calls.append(repository))
  monkeypatch.setattr(commands, "workspace", lambda args: (_ for _ in ()).throw(AssertionError("workspace must not load")))
  monkeypatch.setattr(cli, "resolve_selection", lambda args: (_ for _ in ()).throw(AssertionError("local selection must not run")))
  assert cli.main(["lock", "--agent", "omp"]) == 0
  assert len(calls) == 1 and calls[0].name == "rotom"
  assert json.loads(capsys.readouterr().out) == {"agent": "omp", "command": "lock", "locked": True}
