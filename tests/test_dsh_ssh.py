"""SSH headless 配置契约的离线验收；不启动宿主或远程连接。"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from agentcfg import native, profile_runtime
from agentcfg.dependencies import recipe_digest
from agentcfg.dsh_ssh import SSH_BUNDLES, SSH_PROJECTIONS, validate_ssh
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from agentcfg.workspace import load_public_catalog, load_workspace


REMOTE = {"host": "fixture-server", "workspace": "/srv/fixture/project",
  "helper": "/opt/fixture/bin/dsh-ssh-helper", "helper_hash": "a" * 64}


def machine(tmp_path, remote=None, *, extra=""):
  local = tmp_path / "machine.toml"
  document = 'schema_version=1\n[machine]\nid="ssh-fixture"\n'
  if remote is not None:
    document += "\n[overrides.profiles.dsh-ssh.agent_options.ssh]\n"
    document += "".join(key + "=" + json.dumps(value) + "\n" for key, value in remote.items())
  local.write_text(document + extra)
  local.chmod(0o600)
  return local


@pytest.fixture
def workspace(tmp_path):
  return load_workspace(machine(tmp_path, REMOTE), "dsh-ssh")


def test_public_catalog_and_unselected_ssh_preserve_local_defaults(tmp_path):
  catalog, _ = load_public_catalog()
  assert {"dsh-default", "dsh-ssh"} <= catalog.profiles.keys()
  assert catalog.profiles["dsh-default"]["providers"] == ["codex", "cursor"]
  assert catalog.profiles["dsh-ssh"]["plugins"] == []
  assert catalog.profiles["dsh-ssh"]["mcp"] == []
  local = machine(tmp_path)
  default = load_workspace(local)
  assert default.profile == "dsh-default"
  assert default.resolved.data["profile"]["roles"]["main"] == "kimi_code_openai"
  assert {"codex", "cursor"} <= default.resolved.data["providers"].keys()
  assert {"tui", "tmux-context", "git-worktrees"} <= default.resolved.data["plugins"].keys()
  with pytest.raises(ConfigError) as caught:
    load_workspace(local, "dsh-ssh")
  # 解析框架统一脱敏 adapter 回调错误，不向外透传其内部代码。
  assert caught.value.code == "adapter"
  assert caught.value.path == ("adapter",)


def test_direct_selected_ssh_validation_reports_missing_configuration():
  data = {"profile": {"agent_options": {"execution": "ssh", "auto_review": False}},
    "plugins": {}, "mcp": {}, "providers": {}}
  validate_ssh(data)
  with pytest.raises(ConfigError) as caught:
    validate_ssh(data, selected=True)
  assert caught.value.code == "dsh-ssh-not-configured"


def test_filled_ssh_resolves_global_api_models_and_renders_headless(workspace):
  data = workspace.resolved.data
  assert data["profile"]["roles"]["main"] == "kimi_code_openai"
  assert data["models"] and data["providers"]
  assert all(provider["auth_kind"] == "api-key" for provider in data["providers"].values())
  assert data["plugins"] == data["mcp"] == {}
  artifacts = workspace.adapter.render(data)
  assert all(".dsh-tui" not in artifact.target.path for artifact in artifacts)
  assert all(not (artifact.target.selector or "").startswith("/dsh-tui/") for artifact in artifacts)
  patch = native.load(next(artifact.content for artifact in artifacts
    if artifact.target.path == "dsh-home/agentcfg.patch.yml"))
  rows = {row["id"]: row for row in patch if "id" in row}
  inserted = [row for operation in patch for row in operation.get("insert", [])]
  assert rows["fs-sandbox"]["disabled"] is True
  assert rows["subprocess"]["name"] == "@deepseek-ai/dsh-subprocess-ssh"
  assert rows["subprocess"]["config"] == {}
  assert rows["subprocess"]["disabled"] is False
  assert rows["sandbox"]["name"] == "@deepseek-ai/dsh-sandbox-ssh"
  assert rows["sandbox"]["config"] == {}
  assert rows["sandbox-policy"]["config"] == {"mode": "read-only", "workspaceRoot": REMOTE["workspace"]}
  assert rows["shell-env"] == {"id": "shell-env", "name": "rotom-dsh-ssh-shell-env", "config": {}}
  assert rows["ptc-runtime"]["inject"] == ["ssh"]
  assert rows["ptc-runtime"]["config"] == {"launch": native.JS("ctx.ssh.ptcLaunch")}
  assert rows["tool-bash"]["config"] == {"enableRunInBackground": False, "promoteOnTimeout": False}
  for key in ("jobs", "tool-jobs", "spill-local", "spill-policy"):
    assert rows[key]["disabled"] is True
  assert inserted == [
    {"id": "ssh", "name": "@deepseek-ai/dsh-ssh", "config": {
      "host": REMOTE["host"], "launch": {"kind": "executable"}, "helper": REMOTE["helper"],
      "helperHash": REMOTE["helper_hash"], "workspace": REMOTE["workspace"]}},
    {"id": "fs", "name": "@deepseek-ai/dsh-fs-ssh"},
  ]
  packages, bundles = profile_runtime.profile_layout(workspace)
  assert packages == SSH_PROJECTIONS
  assert bundles == SSH_BUNDLES == ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]
  assert not any("tui" in name or "execution-environment" in name for name in packages)


@pytest.mark.parametrize("permission", [None, "workspace-write"])
def test_launch_binds_remote_workspace_and_permission_without_tui(workspace, tmp_path, permission):
  data = deepcopy(workspace.resolved.data)
  if permission is not None:
    data["profile"]["agent_options"]["ssh"]["permission_mode"] = permission
  spec = workspace.adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime",
    instance_root=tmp_path / "instance", lock_identity="fixture-lock")
  environment = {binding.name: binding.value for binding in spec.environment}
  assert environment["AGENTCFG_DSH_EXECUTION"] == "ssh"
  assert environment["AGENTCFG_DSH_REMOTE_WORKSPACE"] == REMOTE["workspace"]
  assert environment["DSH_PERMISSION_MODE"] == (permission or "read-only")
  assert "DSH_TUI_PRESET" not in environment
  assert "DSH_TUI_NO_LAUNCHPAD" not in environment
  assert spec.environment_policy == "isolated"


@pytest.mark.parametrize("plugin", ["tui", "tmux-context", "git-worktrees", "auto-review", "review-context"])
def test_ssh_rejects_all_plugin_consumers(workspace, plugin):
  data = deepcopy(workspace.resolved.data)
  data["plugins"][plugin] = {}
  with pytest.raises(ConfigError) as caught:
    workspace.adapter.validate(data)
  assert caught.value.code == "dsh-ssh-headless-only"


@pytest.mark.parametrize("kind", ["mcp", "oauth", "auto-review"])
def test_ssh_rejects_unverified_execution_routes(workspace, kind):
  data = deepcopy(workspace.resolved.data)
  if kind == "mcp":
    data["mcp"] = {"fixture": {"transport": "stdio", "command": "fixture-command"}}
  elif kind == "oauth":
    data["providers"] = {"fixture": {"auth_kind": "oauth"}}
  else:
    data["profile"]["agent_options"]["auto_review"] = True
  with pytest.raises(ConfigError) as caught:
    workspace.adapter.validate(data)
  assert caught.value.code == ("dsh-ssh-api-provider-required" if kind == "oauth" else "dsh-ssh-headless-only")


@pytest.mark.parametrize(("key", "value", "code"), [
  ("workspace", "relative", "dsh-ssh-path"),
  ("workspace", "/srv/../project", "dsh-ssh-path"),
  ("workspace", "/srv//project", "dsh-ssh-path"),
  ("workspace", "/srv/project/", "dsh-ssh-path"),
  ("workspace", "//srv/project", "dsh-ssh-path"),
  ("workspace", "/srv/fixture\nproject", "dsh-ssh-path"),
  ("workspace", "/", "dsh-ssh-helper-location"),
  ("helper", "/opt/../helper", "dsh-ssh-path"),
  ("helper", "/opt/./helper", "dsh-ssh-path"),
  ("helper", "/tmp/helper", "dsh-ssh-helper-location"),
  ("helper", "/var/tmp/helper", "dsh-ssh-helper-location"),
  ("helper", "/srv/fixture/project", "dsh-ssh-helper-location"),
  ("helper", "/srv/fixture/project/helper", "dsh-ssh-helper-location"),
])
def test_remote_paths_fail_without_disclosing_values(workspace, key, value, code):
  data = deepcopy(workspace.resolved.data)
  data["profile"]["agent_options"]["ssh"][key] = value
  with pytest.raises(ConfigError) as caught:
    validate_ssh(data, selected=True)
  assert caught.value.code == code
  assert value not in str(caught.value)


@pytest.mark.parametrize(("key", "value"), [
  ("unknown", "SYNTHETIC-PRIVATE-CANARY"),
  ("host", "fixture@private.invalid"),
  ("helper_hash", "SYNTHETIC-PRIVATE-CANARY"),
  ("permission_mode", "danger-full-access"),
])
def test_ssh_schema_rejects_unknown_and_invalid_values_with_redacted_errors(tmp_path, key, value):
  with pytest.raises(ConfigError) as caught:
    load_workspace(machine(tmp_path, {**REMOTE, key: value}), "dsh-ssh")
  assert caught.value.exit_code == 2
  assert value not in str(caught.value)
  assert key != "unknown" or key not in str(caught.value)


def test_missing_required_ssh_field_fails_schema(tmp_path):
  with pytest.raises(ConfigError):
    load_workspace(machine(tmp_path, {key: value for key, value in REMOTE.items() if key != "helper_hash"}), "dsh-ssh")


def test_local_execution_rejects_remote_options(workspace):
  data = deepcopy(workspace.resolved.data)
  data["profile"]["agent_options"]["execution"] = "local"
  with pytest.raises(ConfigError) as caught:
    validate_ssh(data)
  assert caught.value.code == "dsh-ssh-options-require-ssh-execution"


def test_native_ptc_expression_is_data_only_and_limited_to_launch():
  allowed = [{"id": "ptc-runtime", "inject": ["ssh"], "config": {"launch": native.JS("ctx.ssh.ptcLaunch")}}]
  assert native.load(native.dump(allowed)) == allowed
  for expression in ("ctx.ssh.ptcLaunch()", "ctx.ssh.connection", "process.exit()"):
    with pytest.raises(Conflict):
      native.dump({"launch": native.JS(expression)})
  with pytest.raises(Conflict):
    native.dump({"command": native.JS("ctx.ssh.ptcLaunch")})


def test_prepare_and_verify_use_only_headless_projections(tmp_path):
  workspace = SimpleNamespace(instance=tmp_path / "instance", binding={"profile": "dsh-ssh", "machine": "fixture"},
    resolved=SimpleNamespace(data={"profile": {"agent_options": {"execution": "ssh"}}}))
  runtime = tmp_path / "runtime"
  for package in SSH_PROJECTIONS:
    (runtime / "node_modules" / package).mkdir(parents=True)
  profile = profile_runtime.prepare(workspace, runtime)
  assert profile_runtime.verify(workspace, runtime) == profile
  assert json.loads((profile / "package.json").read_text())["dsh"]["profile"]["bundles"] == SSH_BUNDLES
  assert not (profile / "node_modules/@deepseek-harness-tui").exists()
  for package in SSH_PROJECTIONS:
    assert (profile / "node_modules" / package).readlink() == runtime / "node_modules" / package
  (profile / "package.json").write_text("{}")
  with pytest.raises(Conflict):
    profile_runtime.verify(workspace, runtime)


def test_ssh_shell_env_archive_rejects_unpacked_filter_change(tmp_path):
  root = Path(__file__).resolve().parents[1]
  repository = tmp_path / "repo"
  for relative in ("agents/dsh", "locks/dsh/vendor"):
    shutil.copytree(root / relative, repository / relative)
  assert recipe_digest(repository)
  source = repository / "agents/dsh/packages/ssh-shell-env/filter.mjs"
  source.write_bytes(source.read_bytes() + b"\n// unpacked fixture change\n")
  with pytest.raises(DependencyError, match="本地包源码与固定 vendor 归档不一致"):
    recipe_digest(repository)
