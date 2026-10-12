"""普通操作只构造所选控制器；真实构造链配合假进程和临时文件哨兵。"""
import builtins
import importlib
import json
import os
from pathlib import Path

import pytest

from agentcfg import pi_host
from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.process import DependencyError
from test_pi_host_capabilities import configured
from test_pi_supervisor import request


OPTIONAL_MODULES = ("pi_readseek", "pi_web", "pi_checkpoints", "pi_mcp_stdio", "pi_mcp_script",
  "pi_editor", "pi_git_review", "pi_git_status", "pi_services", "pi_codex_admission")
OPTIONAL_METHODS = ("ordinary_readseek_prepare", "ordinary_readseek_result", "ordinary_readseek_discard",
  "ordinary_web_media_prepare", "ordinary_web_cli_prepare", "ordinary_web_cli_authorize", "ordinary_web_git_content",
  "ordinary_web_file_prepare", "ordinary_web_file_finish", "ordinary_web_browser_prepare", "ordinary_web_browser_finish",
  "ordinary_checkpoint_prepare", "ordinary_checkpoint_perform", "ordinary_checkpoint_preview", "ordinary_checkpoint_list",
  "ordinary_mcp_stdio_prepare", "ordinary_mcp_script_prepare", "ordinary_editor_prepare", "ordinary_git_review_prepare",
  "ordinary_git_status_prepare", "ordinary_service_prepare")


def block_optional_imports(monkeypatch):
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    leaf = name.removeprefix("agentcfg.")
    if any(leaf == prefix or leaf.startswith(prefix + "_") for prefix in OPTIONAL_MODULES):
      raise AssertionError("unselected optional implementation imported: " + leaf)
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)


def select_resource(config, manifest_file, resource):
  manifest = json.loads(manifest_file.read_bytes())
  manifest["resource_ids"] = {"extensions": {resource: "synthetic-selected-path"}}
  manifest_file.write_bytes(json_bytes(manifest))
  config["manifest_digest"] = digest(manifest)


def test_unselected_constructor_poll_and_rejections_do_not_import_optional_modules(tmp_path, monkeypatch):
  config, _ = configured(tmp_path, monkeypatch, [])
  sentinels = [Path(config["state_root"]) / "activity/readseek-operations/old.json",
    Path(config["state_root"]) / "activity/web-files/old/owner.json",
    Path(config["state_root"]) / "credential-cache/web-browser/old/owner.json",
    Path(config["instance_root"]) / "pi-home/checkpoints/objects/old.json"]
  for path in sentinels:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(b"old ownership/recovery sentinel"); path.chmod(0o600)
  block_optional_imports(monkeypatch)
  host = pi_host.HostSupervisor(config, lease_fd=None)
  assert all(getattr(host.operations, key) is None for key in ("readseek", "web_browser", "web_files", "checkpoints"))
  assert host.operations.commands is not None
  host.poll()
  token = host.service.issue_capability("user")
  for method in OPTIONAL_METHODS:
    result = host.service.reply(token, os.geteuid(), request(method, {}))
    assert result == {"schema_version": 1, "ok": False, "exit_code": 5, "error": "ORDINARY_CAPABILITY_UNAVAILABLE"}, method
  assert host.children == {} and host.store.records() == []
  assert all(path.read_bytes() == b"old ownership/recovery sentinel" for path in sentinels)


@pytest.mark.parametrize("plugin,resource,module,controller,attribute", [
  ("pi-readseek", None, "pi_readseek", "ReadseekController", "readseek"),
  ("pi-web", None, "pi_web_browser", "BrowserSnapshots", "web_browser"),
  ("pi-web", None, "pi_web_files", "WebFiles", "web_files"),
  (None, "git-checkpoint", "pi_checkpoints", "Checkpoints", "checkpoints"),
])
def test_selected_controllers_construct_once_and_keep_tick(tmp_path, monkeypatch, plugin, resource, module, controller, attribute):
  config, file = configured(tmp_path, monkeypatch, [plugin] if plugin else [])
  if resource: select_resource(config, file, resource)
  source = importlib.import_module("agentcfg." + module)
  original = getattr(source, controller); calls = []
  class Selected(original):
    def __init__(self, *args, **kwargs):
      calls.append("construct"); super().__init__(*args, **kwargs)
    def tick(self): calls.append("tick")
  monkeypatch.setattr(source, controller, Selected)
  host = pi_host.HostSupervisor(config, lease_fd=None)
  assert isinstance(getattr(host.operations, attribute), Selected)
  host.poll()
  assert calls == ["construct", "tick"]


def test_unselected_checkpoint_command_reports_fixed_dependency_error(tmp_path, monkeypatch):
  config, _ = configured(tmp_path, monkeypatch, [])
  host = pi_host.HostSupervisor(config, lease_fd=None)
  with pytest.raises(DependencyError, match="^ORDINARY_CAPABILITY_UNAVAILABLE$") as error:
    host.resolve_command({}, "checkpoint", {})
  assert error.value.exit_code == 5
  assert host.store.records() == [] and host.children == {}


def test_selected_broken_optional_controller_is_not_silently_disabled(tmp_path, monkeypatch):
  from agentcfg import pi_readseek
  config, _ = configured(tmp_path, monkeypatch, ["pi-readseek"])
  def broken(*_args): raise DependencyError("synthetic selected controller failure")
  monkeypatch.setattr(pi_readseek, "ReadseekController", broken)
  with pytest.raises(DependencyError, match="synthetic selected controller failure"):
    pi_host.HostSupervisor(config, lease_fd=None)


@pytest.mark.parametrize("change", [
  {"plugins": None}, {"plugins": "pi-web"}, {"plugins": [""]}, {"plugins": [1]},
  {"plugins": ["pi-web", "pi-web"]}, {"resource_ids": []}, {"resource_ids": {"extensions": []}},
])
def test_capability_selection_structure_is_strict(tmp_path, change):
  from agentcfg.pi_operations import OrdinaryOperations
  from agentcfg.schema import ConfigError
  from test_pi_operations import setup
  _, host, _, _ = setup(tmp_path)
  host.manifest().update(change)
  with pytest.raises(ConfigError): OrdinaryOperations(host)


def test_missing_plugins_cannot_mean_all_selected(tmp_path):
  from agentcfg.pi_operations import OrdinaryOperations
  from agentcfg.schema import ConfigError
  from test_pi_operations import setup
  _, host, _, _ = setup(tmp_path)
  del host.manifest()["plugins"]
  with pytest.raises(ConfigError): OrdinaryOperations(host)


def test_selection_is_frozen_for_this_activation_and_later_manifest_does_not_enable_routes(tmp_path, monkeypatch):
  from test_pi_operations import setup
  operations, host, _, principal = setup(tmp_path)
  host.manifest()["plugins"].extend(["pi-web", "pi-readseek", "pi-mcp", "pi-slopchop"])
  host.manifest()["resource_ids"]["extensions"].update({name: "selected-later" for name in ("git-checkpoint", "dirty-repo-guard", "gentle-agent-state")})
  block_optional_imports(monkeypatch)
  for method in OPTIONAL_METHODS:
    with pytest.raises(DependencyError, match="^ORDINARY_CAPABILITY_UNAVAILABLE$"):
      operations.handle(principal, method, {})
  operations.tick()
  assert all(getattr(operations, name) is None for name in ("readseek", "web_browser", "web_files", "checkpoints"))


@pytest.mark.parametrize("plugin,resource,method,module,function", [
  ("pi-mcp", None, "ordinary_mcp_stdio_prepare", "pi_mcp_stdio", "prepare_stdio"),
  ("pi-mcp", None, "ordinary_mcp_script_prepare", "pi_mcp_script", "prepare_script"),
  ("pi-web", None, "ordinary_web_media_prepare", "pi_web_media", "prepare_media"),
  ("pi-web", None, "ordinary_web_cli_prepare", "pi_web_cli", "prepare"),
  ("pi-web", None, "ordinary_web_cli_authorize", "pi_web_cli", "authorize"),
  ("pi-web", None, "ordinary_web_git_content", "pi_web_git", "content"),
  ("pi-slopchop", None, "ordinary_editor_prepare", "pi_editor", "prepare_editor"),
  ("pi-slopchop", None, "ordinary_git_review_prepare", "pi_git_review", "prepare_review"),
  (None, "dirty-repo-guard", "ordinary_git_status_prepare", "pi_git_status", "prepare_status"),
  (None, "gentle-agent-state", "ordinary_service_prepare", "pi_services", "prepare_report"),
])
def test_selected_optional_rpc_dispatches_to_its_existing_helper(tmp_path, monkeypatch, plugin, resource, method, module, function):
  from test_pi_operations import setup
  operations, host, _, principal = setup(tmp_path, plugins=[plugin] if plugin else [], resources=[resource] if resource else [])
  calls = []
  def selected(*args): calls.append(args); return {"selected": True}
  monkeypatch.setattr(importlib.import_module("agentcfg." + module), function, selected)
  assert operations.handle(principal, method, {"fixture": "request"}) == {"selected": True}
  assert len(calls) == 1 and calls[0][1] is principal


def test_selected_tick_order_is_unchanged(tmp_path, monkeypatch):
  from test_pi_operations import setup
  operations, _, _, _ = setup(tmp_path, plugins=["pi-web", "pi-readseek"], resources=["git-checkpoint"])
  calls = []
  for name in ("readseek", "web_browser", "web_files", "commands", "checkpoints"):
    monkeypatch.setattr(getattr(operations, name), "tick", lambda name=name: calls.append(name))
  operations.tick()
  assert calls == ["readseek", "web_browser", "web_files", "commands", "checkpoints"]


def test_web_file_command_cannot_dereference_an_unselected_controller(tmp_path):
  from types import SimpleNamespace
  from test_pi_commands import fixture
  commands, host, args, principal = fixture(tmp_path)
  host.operations = SimpleNamespace(web_files=None)
  ticket = commands.prepare(principal, args)
  commands.records[ticket["operation_id"]]["web_file_id"] = "old-protected-input"
  with pytest.raises(DependencyError, match="^ORDINARY_CAPABILITY_UNAVAILABLE$") as error:
    commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})
  assert error.value.exit_code == 5


@pytest.mark.parametrize("program", ["codex-login", "delegate-pi", "delegate-codex"])
def test_unselected_delegate_programs_reject_before_importing_or_probing(tmp_path, monkeypatch, program):
  config, _ = configured(tmp_path, monkeypatch, [])
  host = pi_host.HostSupervisor(config, lease_fd=None)
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if name.removeprefix("agentcfg.") in ("pi_login", "pi_delegate_spawn"):
      raise AssertionError("unselected delegate program imported")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  with pytest.raises(DependencyError, match="^DELEGATE_CAPABILITY_UNAVAILABLE$") as error:
    host.resolve_command({}, program, {})
  assert error.value.exit_code == 5
  assert host.store.records() == [] and host.children == {}


@pytest.mark.parametrize("program,module,function", [
  ("codex-login", "pi_login", "resolve_login"),
  ("delegate-pi", "pi_delegate_spawn", "resolve_delegate"),
  ("delegate-codex", "pi_delegate_spawn", "resolve_delegate"),
])
def test_selected_delegate_program_keeps_its_original_resolver(tmp_path, monkeypatch, program, module, function):
  config, _ = configured(tmp_path, monkeypatch, ["model-delegate"])
  host = pi_host.HostSupervisor(config, lease_fd=None)
  calls = []
  def selected(*args): calls.append(args); return "synthetic-command"
  monkeypatch.setattr(importlib.import_module("agentcfg." + module), function, selected)
  assert host.resolve_command({}, program, {}) == "synthetic-command"
  assert len(calls) == 1 and calls[0][0] is host


@pytest.mark.parametrize("program", ["workspace", "check"])
def test_unselected_task_keeper_programs_reject_before_import(tmp_path, monkeypatch, program):
  config, _ = configured(tmp_path, monkeypatch, [])
  host = pi_host.HostSupervisor(config, lease_fd=None)
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if name.removeprefix("agentcfg.") == "pi_auxiliary":
      raise AssertionError("unselected Task Keeper implementation imported")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  with pytest.raises(DependencyError, match="^ORDINARY_CAPABILITY_UNAVAILABLE$") as error:
    host.resolve_command({}, program, {})
  assert error.value.exit_code == 5
  assert host.store.records() == [] and host.children == {}


@pytest.mark.parametrize("program", ["workspace", "check"])
def test_selected_task_keeper_program_keeps_its_original_resolver(tmp_path, monkeypatch, program):
  from agentcfg import pi_auxiliary
  config, _ = configured(tmp_path, monkeypatch, ["task-keeper"])
  host = pi_host.HostSupervisor(config, lease_fd=None)
  calls = []
  def selected(*args): calls.append(args); return "synthetic-command"
  monkeypatch.setattr(pi_auxiliary, "resolve_auxiliary", selected)
  assert host.resolve_command({}, program, {}) == "synthetic-command"
  assert calls == [(host, {}, program, {})]


def test_missing_future_account_anchor_keeps_auxiliary_check_denial(tmp_path):
  from types import SimpleNamespace
  from agentcfg.pi_auxiliary import resolve_auxiliary
  from agentcfg.storage import Tree
  source = tmp_path / "project"; source.mkdir()
  instance = tmp_path / "instance"; candidate = instance / "pi-home/task-keeper/worktrees/task"
  candidate.mkdir(parents=True)
  executable = tmp_path / "check"; executable.write_text("inert fixture"); executable.chmod(0o700)
  repository = tmp_path / "repository"; (repository / "scripts").mkdir(parents=True)
  (repository / "scripts/pi-project-check").write_text("inert entry")
  runtime = tmp_path / "runtime"; root = tmp_path / "state"
  runtime.mkdir(mode=0o700); root.mkdir(mode=0o700)
  with Tree(runtime) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"programs": {"check": {"kind": "check"}}}))
  anchor = tmp_path / "future-account/.agentcfg-workspaces"
  manifest = {"options": {"task_keeper": {"enabled": True, "project_root": "project", "check_ids": ["test"]},
    "paths": {"roots": {"project": {"path": str(source)}}},
    "checks": {"test": {"project_root": "project", "executable": str(executable), "args": ["--fixed"], "timeout_seconds": 5, "foreground": True}}},
    "permission_policy": {"rules": []}}
  host = SimpleNamespace(runtime_root=runtime, repository=repository, root=root, manifest=lambda: manifest,
    config={"instance_root": str(instance), "protected_roots": [str(anchor)]},
    server=SimpleNamespace(endpoint=tmp_path / "endpoint"), service=SimpleNamespace(issue_capability=lambda *_: "synthetic"),
    store=SimpleNamespace(workspaces=SimpleNamespace(identify=lambda _: {"workspace_key": "fixture"})))
  lease = {"lease_id": "a" * 32, "kind": "check", "task_id": "task", "grant_generation": 1,
    "planned_workspaces": [{"workspace_key": "fixture"}]}
  command = resolve_auxiliary(host, lease, "check", {"check_id": "test", "cwd": str(candidate), "task_id": "task"})
  with Tree(root) as tree:
    value = json.loads(tree.read("activity/auxiliary-inputs/" + lease["lease_id"] + ".json")[0])
  assert str(anchor) in value["denied_paths"] and value["check"]["argv"][1:] == ["--fixed"]
  assert command.cwd == candidate and not anchor.exists()
