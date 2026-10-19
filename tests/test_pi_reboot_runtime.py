"""官方Pi CLI薄适配边界；不启动CLI、不解析npm、不访问网络或真实状态。"""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace
from test_pi_reboot_configuration import local, REPOSITORY


@pytest.fixture
def selected(tmp_path):
  return load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)


def launch(workspace, tmp_path):
  return workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path,
    runtime_root=tmp_path / "locked-runtime", instance_root=workspace.instance, lock_identity="synthetic-lock")


def test_launch_uses_official_cli_stable_home_and_explicit_resource_flags(selected, tmp_path):
  spec = launch(selected, tmp_path)
  assert spec.argv[:2] == ("node", str(tmp_path / "locked-runtime/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"))
  for flag in ("--no-approve", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-mcp"):
    assert flag in spec.argv
  assert "--no-context-files" not in spec.argv
  assert spec.argv[spec.argv.index("--session-dir") + 1] == str(selected.instance / "pi-home/sessions")
  assert spec.argv[spec.argv.index("--use-theme") + 1] == "catppuccin-mocha"
  themes = [spec.argv[index + 1] for index, value in enumerate(spec.argv) if value == "--theme"]
  assert str(tmp_path / "locked-runtime/node_modules/catppuccin-pi-theme/themes/catppuccin-mocha.json") in themes
  env = {item.name: item.value for item in spec.environment}
  assert env["PI_OFFLINE"] == "1"
  assert env["PI_CODING_AGENT_DIR"] == str(selected.instance / "pi-home")
  assert env["PI_CODING_AGENT_SESSION_DIR"] == str(selected.instance / "pi-home/sessions")
  assert any(isinstance(item.value, SecretRef) for item in spec.environment)
  assert not any(name in env for name in ("CODEX_HOME", "AGENTCFG_PI_EXECUTION_HOME", "BUN_OPTIONS"))
  assert not hasattr(selected.adapter, "launch_executor")


@pytest.mark.parametrize("inherited", [None, "", "0"])
def test_old_deployment_cannot_reenable_implicit_host_downloads(selected, tmp_path, monkeypatch, inherited):
  from agentcfg.runtime import prepare_environment
  if inherited is None:
    monkeypatch.delenv("PI_OFFLINE", raising=False)
  else:
    monkeypatch.setenv("PI_OFFLINE", inherited)
  spec = launch(selected, tmp_path)
  # 模拟尚未重新apply、不含新字面量声明的旧部署；不运行任何第三方宿主。
  previous = replace(spec, environment=tuple(item for item in spec.environment if item.name != "PI_OFFLINE"))
  env, _ = prepare_environment(selected, {"machine": selected.resolved.data["machine"]}, previous)
  assert env["PI_OFFLINE"] == "1"


@pytest.mark.parametrize("setting", ["inherit", "unset"])
def test_runtime_override_cannot_remove_official_startup_download_policy(selected, tmp_path, setting):
  from agentcfg.runtime import prepare_environment
  with pytest.raises(ConfigError):
    prepare_environment(selected, {"machine": selected.resolved.data["machine"]}, launch(selected, tmp_path),
      **{setting: ("PI_OFFLINE",)})


def test_api_key_is_a_guarded_environment_reference_and_secret_is_not_rendered(selected):
  artifacts = selected.adapter.render(selected.resolved.data)
  keys = [artifact for artifact in artifacts if artifact.target.selector and artifact.target.selector.endswith("/apiKey")]
  assert keys and all(artifact.target.reference_tokens == (json.loads(artifact.content),) for artifact in keys)
  assert all(json.loads(artifact.content).startswith("$AGENTCFG_PI_") for artifact in keys)
  assert all(b"SYNTHETIC_REBOOT_SENTINEL" not in artifact.content for artifact in artifacts)


@pytest.mark.parametrize("packages", [["npm:unapproved@1.0.0"], [{"source": "npm:unapproved@1.0.0"}], {"source": "npm:unapproved@1.0.0"}])
def test_preflight_rejects_global_packages_without_deleting_user_settings(selected, tmp_path, packages):
  settings = selected.instance / "pi-home/settings.json"
  settings.parent.mkdir(parents=True)
  settings.write_text(json.dumps({"packages": packages, "unmanaged": "keep"}))
  before = settings.read_bytes()
  with pytest.raises(Conflict):
    selected.adapter.validate_runtime(selected, tmp_path / "locked-runtime")
  assert settings.read_bytes() == before


def test_preflight_only_reads_allowed_nonsecret_native_files(selected, tmp_path):
  home = selected.instance / "pi-home"
  home.mkdir(parents=True)
  (home / "settings.json").write_text('{"packages":[],"unmanaged":true}')
  (home / "auth.json").mkdir()
  (home / "sessions").mkdir()
  selected.adapter.validate_runtime(selected, tmp_path / "locked-runtime")


def test_settings_symlink_is_rejected_without_following_it(selected, tmp_path):
  home = selected.instance / "pi-home"
  home.mkdir(parents=True)
  source = tmp_path / "synthetic-settings"
  source.write_text('{"packages":[]}')
  (home / "settings.json").symlink_to(source)
  with pytest.raises(Conflict):
    selected.adapter.validate_runtime(selected, tmp_path / "runtime")


@pytest.mark.parametrize("provider,model", [("agentcfg-example", "fictional-chat"),
  (None, "agentcfg-example/fictional-chat")])
def test_spawn_allows_selected_native_model_routes(selected, tmp_path, provider, model):
  arguments = (*(("--provider", provider) if provider else ()), "--model", model)
  selected.adapter.validate_before_spawn(selected, tmp_path, arguments, {})


@pytest.mark.parametrize("arguments", [("--provider", "unselected"), ("--model", "unselected"),
  ("--provider", "agentcfg-example", "--model", "unselected")])
def test_spawn_rejects_unselected_model_routes(selected, tmp_path, arguments):
  with pytest.raises(ConfigError):
    selected.adapter.validate_before_spawn(selected, tmp_path, arguments, {})


@pytest.mark.parametrize("arguments", [
  ("--session-dir", "/unmanaged"), ("--session-dir=/unmanaged",), ("-e", "npm:unapproved"),
  ("--extension=unapproved",), ("--skill", "unapproved"), ("--theme", "unapproved"),
  ("--prompt-template", "unapproved"), ("--approve",), ("--no-approve",), ("--agent-dir", "unmanaged"),
  ("install", "npm:unapproved"), ("update",), ("--tools", "all"), ("--api-key", "unmanaged"),
  ("--thinking",), ("--continue=unexpected",), ("--provider",),
  ("--no-tools=value",), ("--tools", "read"), ("--tools/read",),
])
def test_passthrough_cannot_replace_managed_loading_or_install_boundaries(arguments):
  with pytest.raises(ConfigError):
    PiAdapter(REPOSITORY).validate_arguments(arguments)


@pytest.mark.parametrize("arguments", [(), ("--continue",), ("--resume", "synthetic-session"),
  ("--session", "synthetic-session"), ("--fork", "synthetic-session"), ("--model", "synthetic-model"),
  ("--provider", "synthetic-provider"), ("--thinking", "high"), ("--print", "ordinary prompt"),
  ("--", "install", "--session-dir", "ordinary prompt"), ("--verbose",),
  ("--no-tools",), ("--no-tools", "--print", "synthetic request"),
  ("--no-tools", "--provider", "synthetic-provider", "--model", "synthetic-model")])
def test_passthrough_preserves_supported_native_session_model_and_effort_uses(arguments):
  PiAdapter(REPOSITORY).validate_arguments(arguments)


@pytest.mark.parametrize("arguments", [
  ("--fork",), ("--fork=synthetic-session",), ("--fork", "../private-session"),
  ("--fork", "private/session"), ("--fork", "private\\session"),
  ("--fork", "external.jsonl"), ("--session", "external.jsonl"),
  ("--resume", "external.jsonl"), ("-r", "external.jsonl"),
])
def test_native_session_operations_cannot_select_external_files(arguments):
  with pytest.raises(ConfigError):
    PiAdapter(REPOSITORY).validate_arguments(arguments)


def test_builtin_selection_is_explicit_and_does_not_enable_external_plugins(selected, tmp_path):
  data = deepcopy(selected.resolved.data)
  data["profile"]["agent_options"]["resources"]["extensions"] = ["builtin:codemode", "builtin:tool-search"]
  spec = selected.adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime",
    instance_root=selected.instance, lock_identity="synthetic-lock")
  extensions = [spec.argv[index + 1] for index, arg in enumerate(spec.argv) if arg == "-e"]
  assert extensions == ["builtin:codemode", "builtin:tool-search"]
  assert "--no-mcp" in spec.argv and "builtin:mcp" not in extensions


def test_selected_mcp_is_explicitly_not_admitted_instead_of_fake_loading(selected):
  data = deepcopy(selected.resolved.data)
  data["profile"]["mcp"] = ["synthetic-service"]
  data["mcp"] = {"synthetic-service": {"transport": "stdio", "command": "/synthetic/server", "args": []}}
  with pytest.raises(ConfigError, match="pi-mcp-module-not-admitted"):
    selected.adapter.validate(data)


@pytest.mark.parametrize("theme", ["catppuccin-frappe", "catppuccin-latte", "catppuccin-macchiato"])
def test_current_ui_theme_preference_changes_only_validated_use_theme(selected, tmp_path, theme):
  spec = launch(selected, tmp_path)
  settings = selected.instance / "pi-home/settings.json"
  settings.parent.mkdir(parents=True)
  settings.write_text(json.dumps({"theme": theme, "packages": []}))
  before = settings.read_bytes()
  actual = selected.adapter.operation_environment(spec, ())
  assert actual.argv[actual.argv.index("--use-theme") + 1] == theme
  assert actual.environment == spec.environment and actual.lock_identity == spec.lock_identity
  assert settings.read_bytes() == before
  themes = [actual.argv[index + 1] for index, arg in enumerate(actual.argv) if arg == "--theme"]
  assert len(themes) == 4
  assert all(Path(path).name in {"catppuccin-" + flavor + ".json"
    for flavor in ("latte", "frappe", "macchiato", "mocha")} for path in themes)


def test_unregistered_native_theme_is_conflict_and_never_rewritten(selected, tmp_path):
  spec = launch(selected, tmp_path)
  settings = selected.instance / "pi-home/settings.json"
  settings.parent.mkdir(parents=True)
  settings.write_text('{"theme":"unregistered-theme","packages":[]}')
  before = settings.read_bytes()
  with pytest.raises(Conflict):
    selected.adapter.operation_environment(spec, ())
  assert settings.read_bytes() == before


def test_preflight_uses_new_backend_node_contract_without_legacy_slice_metadata(selected):
  checks = selected.adapter.launch_preflight_for(selected.resolved.data,
    SimpleNamespace(metadata={"node": "v22.19.0"}))
  assert checks and checks[0]["argv"] == ["node", "--version"]
  assert checks[0]["version"] == "v22.19.0" and checks[0]["match"] == "minimum"


def test_runtime_binding_rejects_source_selection_changes_without_relocking_implicitly(selected):
  saved = selected.adapter.runtime_binding(selected.resolved.data, selected.instance)
  changed = deepcopy(selected.resolved.data)
  changed["profile"]["agent_options"]["resources"]["prompts"] = []
  workspace = SimpleNamespace(resolved=SimpleNamespace(data=changed), instance=selected.instance)
  with pytest.raises(Conflict):
    selected.adapter.validate_runtime_binding(workspace, saved)


def test_selected_resources_only_use_explicit_local_skill_and_prompt_paths(selected, tmp_path):
  spec = launch(selected, tmp_path)
  skills = [spec.argv[index + 1] for index, arg in enumerate(spec.argv) if arg == "--skill"]
  assert skills == [str(selected.instance / "pi-home/skills" / identity)
    for identity in selected.resolved.data["profile"]["skills"]]
  prompts = [spec.argv[index + 1] for index, arg in enumerate(spec.argv) if arg == "--prompt-template"]
  assert prompts and all(Path(value).is_relative_to(selected.instance / "pi-home/prompts") for value in prompts)
  assert all("npm:" not in arg and "starter" not in arg for arg in spec.argv)
