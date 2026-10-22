"""恢复显式 Pi 配置和仓库命令别名；不启动第三方宿主。"""

from copy import deepcopy
import json

import pytest

from agentcfg import deployment
from agentcfg.pi_dependencies import PiBackend, dependency_selection, digest, recipe_inputs
from agentcfg.schema import ConfigError
from agentcfg.workspace import load_workspace
from test_pi_optional_modules import module_workspace
from test_pi_reboot_configuration import local, REPOSITORY, settings_fields
from test_pi_reboot_dependencies import fake_npm, recipe_repository


TOOLS = ["read", "bash", "edit", "write", "codemode"]
ALIAS = "support/command-aliases.mjs"


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_explicit_codemode_and_default_tools_survive_native_projection(tmp_path, profile):
  extra = (f"[overrides.profiles.{profile}.agent_options.resources]\n"
    'extensions=["builtin:codemode"]\n'
    f"[overrides.profiles.{profile}.agent_options.settings]\n"
    "defaultTools=" + json.dumps(TOOLS) + "\n"
    f"[overrides.profiles.{profile}.agent_options.settings.codemode]\n"
    'mode="on"\ninlineBudget=3000\n')
  workspace = load_workspace(local(tmp_path / "local.toml", profile=profile, extra=extra), repository=REPOSITORY)
  fields = settings_fields(workspace)
  assert fields["/defaultTools"][1] == TOOLS
  assert fields["/codemode/mode"][1] == "on"
  assert fields["/codemode/inlineBudget"][1] == 3000
  candidate = workspace.candidate("synthetic-preserved-config")
  contract = {"shared_files": list(workspace.adapter.shared_files)}
  deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, contract)
  native = json.loads((workspace.instance / "pi-home/settings.json").read_bytes())
  assert native["defaultTools"] == TOOLS
  assert native["codemode"] == {"mode": "on", "inlineBudget": 3000}
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path,
    runtime_root=tmp_path / "runtime", instance_root=workspace.instance, lock_identity="synthetic")
  assert [spec.argv[i + 1] for i, arg in enumerate(spec.argv) if arg == "-e"] == [
    str(tmp_path / "runtime" / ALIAS), str(tmp_path / "runtime/node_modules/pi-footer/src/index.ts"),
    "builtin:codemode", str(tmp_path / "runtime/support/status-observer.mjs")]


@pytest.mark.parametrize("setting", [
  'defaultTools=["read","read"]', 'defaultTools=[""]', "defaultTools=[1]",
  'defaultTools="read"', 'unknownSetting=true',
])
def test_invalid_native_settings_still_fail_closed(tmp_path, setting):
  extra = "[overrides.profiles.pi-base.agent_options.settings]\n" + setting + "\n"
  with pytest.raises(ConfigError):
    load_workspace(local(tmp_path / "local.toml", extra=extra), repository=REPOSITORY)


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_alias_is_always_a_hashed_recipe_input(tmp_path, profile):
  workspace = load_workspace(local(tmp_path / "local.toml", profile=profile), repository=REPOSITORY)
  inputs = recipe_inputs(REPOSITORY, profile, dependency_selection(workspace.resolved.data))
  support = next(item for item in inputs["resources"] if item.get("id") == "pi-command-aliases")
  assert support == {"kind": "module-support", "id": "pi-command-aliases",
    "path": "agents/pi/" + ALIAS, "target": ALIAS,
    "content_identity": digest((REPOSITORY / "agents/pi" / ALIAS).read_bytes())}


def test_alias_is_required_sealed_source_and_loaded_before_plugins(module_workspace, tmp_path):
  make, backend, _, _ = module_workspace
  workspace, lock = make(plugins=["cache-hit-monitor"])
  for profile in ("pi-base", "pi-pro"):
    assert ALIAS in lock.metadata["profiles"][profile]["required_files"]
  root = backend.root(workspace, backend.runtime_identity(workspace, lock))
  source = workspace.repository / "agents/pi" / ALIAS
  assert (root / ALIAS).read_bytes() == source.read_bytes()
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path, runtime_root=root,
    instance_root=workspace.instance, lock_identity=lock.identity)
  extensions = [spec.argv[i + 1] for i, arg in enumerate(spec.argv) if arg == "-e"]
  assert extensions == [str(root / ALIAS),
    str(root / "node_modules/@narumitw/pi-cache-hit-monitor/src/index.ts"), "builtin:codemode"]
  source.write_bytes(source.read_bytes() + b"\n")
  with pytest.raises(ConfigError):
    backend.runtime_identity(workspace, lock)


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_native_project_trust_restores_pi_decision_without_approval_flags(tmp_path, profile):
  deny = f'[overrides.profiles.{profile}.agent_options.discovery]\nproject_trust="deny"\n'
  default = load_workspace(local(tmp_path / "deny.toml", profile=profile, extra=deny), repository=REPOSITORY)
  extra = f'[overrides.profiles.{profile}.agent_options.discovery]\nproject_trust="native"\n'
  native = load_workspace(local(tmp_path / "native.toml", profile=profile, extra=extra), repository=REPOSITORY)
  def spec(workspace):
    return workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path,
      runtime_root=tmp_path / "runtime", instance_root=workspace.instance, lock_identity="synthetic")
  assert "--no-approve" in spec(default).argv
  argv = spec(native).argv
  assert "--approve" not in argv and "--no-approve" not in argv
  for flag in ("--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-mcp"):
    assert flag in argv
  assert next(item.value for item in spec(native).environment if item.name == "PI_OFFLINE") == "1"
  assert native.resolved.data["profile"]["agent_options"]["discovery"]["project_resources"] is False
  denied_binding = default.adapter.runtime_binding(default.resolved.data, default.instance)
  native_binding = native.adapter.runtime_binding(native.resolved.data, default.instance)
  assert denied_binding["project_trust"] == "deny"
  assert native_binding["project_trust"] == "native"
  assert {key: value for key, value in denied_binding.items() if key != "project_trust"} == {
    key: value for key, value in native_binding.items() if key != "project_trust"}


def machine_profiles(path):
  extra = ('[overrides.profiles.pi-base.agent_options.resources]\n'
    'extensions=["builtin:codemode"]\n'
    '[overrides.profiles.pi-pro]\nproviders=["example"]\nmodels=["example-main"]\n'
    'plugins=["pi-footer"]\n'
    '[overrides.profiles.pi-pro.roles]\nmain="example-main"\n'
    '[overrides.profiles.pi-pro.agent_options.resources]\nextensions=["builtin:tool-search"]\n')
  local(path, extra=extra)
  path.write_text(path.read_text().replace('models=["example-main"]\n',
    'models=["example-main"]\nplugins=["cache-hit-monitor"]\n', 1))
  return path


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_machine_lock_keeps_both_profiles_without_resolving_secrets(tmp_path, monkeypatch, profile):
  path = machine_profiles(tmp_path / "local.toml")
  workspace = load_workspace(path, profile, repository=REPOSITORY)
  monkeypatch.setattr("agentcfg.secrets.SecretStore.resolve", lambda *a, **kw: pytest.fail("lock不得解析秘密"))
  captured = []
  def capture(repository, selections):
    captured.append(selections)
    return {name: recipe_inputs(repository, name, selections[name]) for name in ("pi-base", "pi-pro")}
  backend = PiBackend()
  monkeypatch.setattr(backend, "_resolve_lock", capture)
  inputs = backend.resolve_lock_for(workspace)
  assert len(captured) == 1
  assert captured[0][profile] == dependency_selection(workspace.resolved.data)
  assert set(inputs["pi-base"]["modules"]) == {"catppuccin", "cache-hit-monitor"}
  assert set(inputs["pi-pro"]["modules"]) == {"catppuccin", "pi-footer"}
  assert inputs["pi-base"]["selection"]["resources"]["extensions"] == ["builtin:codemode"]
  assert inputs["pi-pro"]["selection"]["resources"]["extensions"] == ["builtin:tool-search"]


def test_public_lock_still_uses_only_public_selections(tmp_path, monkeypatch):
  machine_profiles(tmp_path / "local.toml")
  def no_workspace(*args, **kwargs):
    pytest.fail("公开锁不得读取机器配置")
  monkeypatch.setattr("agentcfg.workspace.load_workspace", no_workspace)
  backend = PiBackend()
  def capture(repository, selections):
    assert selections == {}
    return {profile: recipe_inputs(repository, profile) for profile in ("pi-base", "pi-pro")}
  monkeypatch.setattr(backend, "_resolve_lock", capture)
  inputs = backend.resolve_lock(REPOSITORY)
  assert all(set(piece["modules"]) == {"catppuccin", "pi-footer"} for piece in inputs.values())


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_public_defaults_restore_footer_codemode_and_native_trust(tmp_path, profile):
  workspace = load_workspace(local(tmp_path / "local.toml", profile=profile), repository=REPOSITORY)
  data = workspace.resolved.data
  assert data["profile"]["plugins"] == ["pi-footer"]
  assert data["profile"]["agent_options"]["resources"]["extensions"] == ["builtin:codemode"]
  assert data["profile"]["agent_options"]["discovery"]["project_trust"] == "native"
  fields = settings_fields(workspace)
  assert fields["/defaultTools"][1] == TOOLS
  assert fields["/codemode/mode"][1] == "on"
  assert fields["/codemode/inlineBudget"][1] == 3000


@pytest.mark.parametrize("extensions,expected", [
  ([], ["read", "bash", "edit", "write"]),
  (["builtin:codemode"], TOOLS),
  (["builtin:tool-search"], ["read", "bash", "edit", "write", "tool_search"]),
  (["builtin:tool-search", "builtin:codemode"], [*TOOLS, "tool_search"]),
])
@pytest.mark.parametrize("explicit", [None, [], ["read"]])
def test_tool_derivation_only_fills_absent_explicit_settings(tmp_path, extensions, expected, explicit):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  data = deepcopy(workspace.resolved.data)
  data["profile"]["agent_options"]["resources"]["extensions"] = extensions
  if explicit is not None:
    data["profile"]["agent_options"]["settings"]["defaultTools"] = explicit
  fields = {artifact.target.selector: json.loads(artifact.content) for artifact in workspace.adapter.render(data)
    if artifact.target.path == "pi-home/settings.json"}
  assert fields["/defaultTools"] == (expected if explicit is None else explicit)
  assert ("/codemode/mode" in fields) == ("builtin:codemode" in extensions)


@pytest.mark.parametrize("section,setting", [
  ("ui", "editorPaddingX=4"), ("ui", "outputPad=2"),
  ("ui", "autocompleteMaxVisible=2"), ("ui", "autocompleteMaxVisible=21"),
  ("settings.codemode", 'mode="off"'),
])
def test_official_setting_limits_fail_before_silent_host_normalization(tmp_path, section, setting):
  extra = f"[overrides.profiles.pi-base.agent_options.{section}]\n{setting}\n"
  with pytest.raises(ConfigError):
    load_workspace(local(tmp_path / "local.toml", extra=extra), repository=REPOSITORY)


def test_static_agent_options_match_active_schema_and_accept_official_boundaries(tmp_path):
  options = json.loads((REPOSITORY / "agents/pi/schemas/options.schema.json").read_text())
  options.pop("$schema")
  agent = json.loads((REPOSITORY / "agents/pi/schemas/agent.schema.json").read_text())
  assert agent["properties"]["defaults"]["properties"]["agent_options"] == options
  extra = ('[overrides.profiles.pi-base.agent_options.ui]\neditorPaddingX=3\noutputPad=0\n'
    'autocompleteMaxVisible=20\n[overrides.profiles.pi-base.agent_options.settings.codemode]\nmode="only"\n')
  workspace = load_workspace(local(tmp_path / "local.toml", extra=extra), repository=REPOSITORY)
  fields = settings_fields(workspace)
  assert fields["/editorPaddingX"][1] == 3
  assert fields["/outputPad"][1] == 0
  assert fields["/autocompleteMaxVisible"][1] == 20
  assert fields["/codemode/mode"][1] == "only"


def test_invalid_other_profile_fails_before_lock_publication(tmp_path, monkeypatch):
  path = machine_profiles(tmp_path / "local.toml")
  workspace = load_workspace(path, "pi-base", repository=REPOSITORY)
  path.write_text(path.read_text().replace('plugins=["pi-footer"]', 'plugins=["unadmitted-module"]'))
  backend = PiBackend()
  monkeypatch.setattr(backend, "_resolve_lock", lambda *a: pytest.fail("无效配置不得发布锁"))
  with pytest.raises(ConfigError):
    backend.resolve_lock_for(workspace)
