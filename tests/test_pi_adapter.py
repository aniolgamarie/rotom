"""Pi原生意图测试不执行原生SDK。"""

from copy import deepcopy
import json
from pathlib import Path
import tomllib

import pytest

from agentcfg.adapter import SecretRef
from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError


ROOT = Path(__file__).resolve().parents[1]


def pi_data(tmp_path):
  documents = {name: tomllib.loads((ROOT / "agents/pi" / (name + ".toml")).read_text()) for name in ("agent", "bindings", "plugins")}
  profile = {"schema_version": 1, "id": "pi-fixture", "agent": "pi", "providers": ["fictional"],
    "models": ["main"], "rules": [], "skills": [], "plugins": ["pi-subagents"], "mcp": [],
    "roles": {"main": "main"}, "agent_options": {"runtime": {"engine": "node"}, "resources": {"roles": [], "prompts": [], "themes": [], "extensions": []},
      "discovery": {"project_resources": False, "external_skills": []}, "task_keeper": {"enabled": False}}}
  return {"profile": profile, "adapter_documents": documents,
    "machine": {"id": "fixture", "paths": {key: str(tmp_path / key) for key in ("instances_root", "state_root", "cache_root")},
      "environment": {"inherit": [], "values": {}}},
    "providers": {"fictional": {"protocol": "openai-compatible", "base_url": "https://example.invalid/v1", "auth_kind": "api-key", "credential_ref": "secret:fixture"}},
    "models": {"main": {"provider": "fictional", "remote_id": "fictional-chat", "input": ["text"]}},
    "rules": {}, "skills": {}, "mcp": {}, "plugins": {"pi-subagents": documents["plugins"]["plugins"]["pi-subagents"]}}


def test_pi_emits_guarded_environment_references_not_secret_values(tmp_path):
  adapter = PiAdapter(ROOT)
  data = pi_data(tmp_path)
  adapter.validate(data)
  artifacts = adapter.render(data)
  key_fields = [a for a in artifacts if a.target.selector and a.target.selector.endswith("/apiKey")]
  assert len(key_fields) == 1
  value = json.loads(key_fields[0].content)
  assert value.startswith("$AGENTCFG_PI_")
  assert key_fields[0].target.reference_tokens == (value,)
  assert not any(a.target.path.endswith("auth.json") for a in artifacts)
  launch = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=tmp_path / "instance", lock_identity="fixture-lock")
  assert any(isinstance(binding.value, SecretRef) for binding in launch.environment)
  assert any(binding.name == "PI_CODING_AGENT_DIR" for binding in launch.environment)


def test_unbound_bootstrap_is_valid_but_managed_readiness_fails(tmp_path):
  data = pi_data(tmp_path)
  data["profile"].update(providers=[], models=[], roles={})
  data["providers"], data["models"] = {}, {}
  adapter = PiAdapter(ROOT)
  adapter.validate(data)
  manifest = next(a for a in adapter.render(data) if a.target.path.endswith("agentcfg-manifest.json"))
  assert json.loads(manifest.content)["bootstrap"] is True
  data["profile"]["agent_options"]["task_keeper"]["enabled"] = True
  with pytest.raises(ConfigError):
    adapter.validate_selected(data)


def test_cursor_and_unknown_model_references_are_rejected(tmp_path):
  adapter = PiAdapter(ROOT)
  data = pi_data(tmp_path)
  data["profile"]["plugins"].append("pi-cursor")
  data["plugins"]["pi-cursor"] = data["adapter_documents"]["plugins"]["plugins"]["pi-cursor"]
  with pytest.raises(ConfigError):
    adapter.validate(data)
  data = pi_data(tmp_path)
  data["profile"]["roles"]["main"] = "unknown"
  with pytest.raises(ConfigError):
    adapter.validate(data)


def test_unknown_framework_option_does_not_silently_disappear(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["raw_native_config"] = {"secret": "synthetic"}
  with pytest.raises(ConfigError):
    PiAdapter(ROOT).validate(data)


def test_false_empty_values_and_five_ownership_domains_are_preserved(tmp_path):
  from agentcfg.adapter import Ownership
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["ui"] = {"quiet_startup": False, "hide_thinking": False}
  adapter = PiAdapter(ROOT)
  artifacts = adapter.render(data)
  settings = {a.target.selector: json.loads(a.content) for a in artifacts if a.target.path == "pi-home/settings.json"}
  assert settings["/quietStartup"] is False and settings["/packages"] == []
  assert {target.ownership for target in adapter.managed_targets(data)} == set(Ownership)
  assert not any(a.target.path == "pi-home/auth.json" for a in artifacts)


def test_duplicate_native_mapping_unknown_roles_and_resource_collisions_fail(tmp_path):
  for mutation in ("native", "role", "resource"):
    data = pi_data(tmp_path)
    if mutation == "native":
      data["models"]["duplicate"] = deepcopy(data["models"]["main"])
      data["profile"]["models"].append("duplicate")
    elif mutation == "role":
      data["profile"]["roles"]["unknown"] = "main"
    else:
      resources = data["adapter_documents"]["agent"]["resources"]
      resources["duplicate"] = deepcopy(resources["scout"])
      data["profile"]["agent_options"]["resources"]["roles"] = ["scout", "duplicate"]
    with pytest.raises(ConfigError):
      PiAdapter(ROOT).validate(data)


def test_external_catalog_requires_explicit_machine_binding(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["discovery"]["external_skills"] = ["superpowers"]
  adapter = PiAdapter(ROOT)
  with pytest.raises(ConfigError):
    adapter.validate_selected(data)


@pytest.mark.parametrize("argv", [["-e", "npm:undeclared"], ["--model=x"], ["--tools", "all"], ["--mode", "rpc"], ["--thinking"]])
def test_native_arguments_cannot_replace_managed_launch_contract(argv):
  with pytest.raises(ConfigError):
    PiAdapter(ROOT).validate_arguments(argv)


def test_declared_domain_resources_keep_provenance_and_complete_skill_files():
  manifest = json.loads((ROOT / "agents/pi/migration/resource-manifest.json").read_bytes())
  import hashlib
  for item in manifest["files"]:
    assert hashlib.sha256((ROOT / item["target_path"]).read_bytes()).hexdigest() == item["target_sha256"]
  assert len(list((ROOT / "agents/pi/themes").glob("*.json"))) == 11
  assert len(list((ROOT / "agents/pi/prompts").glob("*.md"))) == 12
  for name in ("cpp-database-kernel", "neovim-plugin-development", "safe-linux-scripting"):
    assert (ROOT / "shared/skills" / name / "LICENSE").is_file()
  text = (ROOT / "agents/pi/prompts/implement.md").read_text()
  assert all(name in text for name in ("kernel_task", "fresh reviewer", "model_delegate"))


def test_bun_launch_disables_implicit_install_env_preload_and_project_transpiler_config(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["runtime"]["engine"] = "bun"
  launch = PiAdapter(ROOT).launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=tmp_path / "instance", lock_identity="fixture")
  assert launch.argv[0] == "bun"
  assert all(flag in launch.argv for flag in ("--no-install", "--no-env-file", "--no-macros"))
  assert "--config=" + str(tmp_path / "runtime/runtime/bunfig.locked.toml") in launch.argv
  assert "--tsconfig-override=" + str(tmp_path / "runtime/runtime/tsconfig.locked.json") in launch.argv
  env = {item.name: item.value for item in launch.environment}
  assert env["BUN_OPTIONS"] == "" and env["BUN_RUNTIME_TRANSPILER_CACHE_PATH"] == "0"


def test_pi_specific_reasoning_settings_project_without_changing_shared_model_schema(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["model_settings"] = {"main": {"reasoning": True, "thinking_level_map": {"medium": "medium", "max": "xhigh"}, "disabled_thinking_levels": ["off"]}}
  artifacts = PiAdapter(ROOT).render(data)
  native = next(json.loads(item.content) for item in artifacts if item.target.path == "pi-home/models.json" and item.target.selector.endswith("/models"))
  assert native[0]["reasoning"] is True
  assert native[0]["thinkingLevelMap"] == {"medium": "medium", "max": "xhigh", "off": None}
  data["profile"]["agent_options"]["model_settings"]["not-selected"] = {"reasoning": False}
  with pytest.raises(ConfigError, match="pi-model-settings-reference"):
    PiAdapter(ROOT).validate(data)


def test_second_view_compiles_separate_explicit_model_binding_from_reviewer_source(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["roles"].update(task_keeper_reader="main", task_keeper_writer="main", task_keeper_reviewer="main", second_view="second")
  data["models"]["second"] = {"provider": "fictional", "remote_id": "fictional-second", "input": ["text"]}
  data["profile"]["models"].append("second")
  data["profile"]["agent_options"]["resources"]["roles"] = ["task-keeper-reader", "task-keeper-writer", "task-keeper-reviewer"]
  data["profile"]["agent_options"]["task_keeper"].update(second_view_enabled=True)
  artifacts = PiAdapter(ROOT).render(data)
  manifest = next(json.loads(item.content) for item in artifacts if item.target.path == "pi-home/agentcfg-manifest.json")
  assert manifest["role_bindings"]["task-keeper-reviewer"]["model"]["model"] == "fictional-chat"
  assert manifest["role_bindings"]["task-keeper-second-view"]["model"]["model"] == "fictional-second"
  assert manifest["role_bindings"]["task-keeper-second-view"]["write_roots"] == []
  assert any(item.target.path == "pi-home/agents/task-keeper-second-view.md" for item in artifacts)


def test_helper_model_configuration_uses_only_the_same_explicit_model_registry(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["btw"] = {"model": "agentcfg-fictional/fictional-chat", "thinkingLevel": "low"}
  PiAdapter(ROOT).validate(data)
  data["profile"]["agent_options"]["smart_compact"] = {"summaryModel": "unselected/model"}
  with pytest.raises(ConfigError, match="pi-helper-model-unbound"):
    PiAdapter(ROOT).validate(data)
  data["profile"]["agent_options"]["smart_compact"] = {"maxLlmCalls": 200}
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)


def test_checkpoint_extension_requires_scope_and_existing_manager(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["resources"]["extensions"] = ["git-checkpoint"]
  with pytest.raises(ConfigError, match="checkpoint-binding-required"): PiAdapter(ROOT).validate(data)
  data["profile"]["agent_options"]["checkpoints"] = {"paths": ["src"]}
  PiAdapter(ROOT).validate(data)
  data["profile"]["plugins"] = []; data["plugins"] = {}
  with pytest.raises(ConfigError, match="checkpoint-binding-required"): PiAdapter(ROOT).validate(data)


def test_selected_permission_policy_references_must_be_declared(tmp_path):
  data = pi_data(tmp_path)
  options = data["profile"]["agent_options"]
  options["permissions"] = {"policy_ref": "custom"}
  policy = {"schema_version": 1, "default": "deny", "rules": [{"id": "private", "kind": "file", "effect": "deny", "tool_ids": ["read"],
    "operations": ["read"], "root_ref": "unknown", "relative_path": ".", "match": "subtree"}]}
  data["adapter_documents"]["agent"]["policies"]["custom"] = policy
  with pytest.raises(ConfigError, match="permission-root-reference"): PiAdapter(ROOT).validate(data)
  policy["rules"] = [{"id": "command", "kind": "command", "effect": "deny", "tool_ids": ["editor"], "operations": ["execute"], "command_ref": "tool:missing"}]
  with pytest.raises(ConfigError, match="permission-command-reference"): PiAdapter(ROOT).validate(data)


def test_git_status_extension_requires_explicit_readonly_tool_and_manager(tmp_path):
  data = pi_data(tmp_path)
  options = data["profile"]["agent_options"]
  options["resources"]["extensions"] = ["dirty-repo-guard"]
  with pytest.raises(ConfigError, match="git-status-binding-required"): PiAdapter(ROOT).validate(data)
  options["dirty_repo_guard"] = {"tool_ref": "git"}
  options["paths"] = {"roots": {"project": {"path": str(tmp_path), "purpose": "project"}}}
  options["external_tools"] = {"git": {"executable": str(tmp_path / "fake-git"), "version": "fixture", "args": [],
    "project_root": "project", "read_roots": ["project"], "write_roots": [], "timeout_seconds": 10}}
  PiAdapter(ROOT).validate(data)
  options["external_tools"]["git"]["write_roots"] = ["project"]
  with pytest.raises(ConfigError, match="git-status-readonly-binding"): PiAdapter(ROOT).validate(data)
  options["external_tools"]["git"]["write_roots"] = []
  data["profile"]["plugins"] = []; data["plugins"] = {}
  with pytest.raises(ConfigError, match="git-status-manager-required"): PiAdapter(ROOT).validate(data)


def test_terminal_service_is_explicit_and_osc_does_not_require_external_processes(tmp_path):
  data = pi_data(tmp_path); options = data["profile"]["agent_options"]
  options["resources"]["extensions"] = ["gentle-agent-state"]
  with pytest.raises(ConfigError, match="agent-state-binding-required"): PiAdapter(ROOT).validate(data)
  options["agent_state"] = {"mode": "osc", "title": "Pi project"}
  PiAdapter(ROOT).validate(data)
  options["agent_state"]["title"] = "unsafe\x1b]2;title"
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)
  options["agent_state"] = {"mode": "service", "executable": "/absolute/bash", "version": "fixture", "args": [], "files": [],
    "socket_paths": [], "environment": {"BASH_ENV": "/unbound"}, "pane": "%1", "timeout_seconds": 5}
  with pytest.raises(ConfigError, match="agent-state-environment"): PiAdapter(ROOT).validate(data)


@pytest.mark.parametrize("shortcut,valid", [("ctrl+shift+t", True), ("alt+/", True), ("off", True), ("ctrl+ctrl+t", False), ("unknown+t", False), (" Ctrl+T ", False)])
def test_todo_shortcuts_are_explicit_and_not_silently_repaired(tmp_path, shortcut, valid):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["todo"] = {"collapseKey": shortcut, "locale": "zh", "guidance": {"promptSnippet": "", "promptGuidelines": []}}
  if valid: PiAdapter(ROOT).validate(data)
  else:
    with pytest.raises(ConfigError, match="todo-shortcut"): PiAdapter(ROOT).validate(data)
