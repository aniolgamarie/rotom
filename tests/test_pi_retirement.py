"""旧平台退出后的来源与历史所有者保护；只用临时合成状态。"""

import ast
import json
from pathlib import Path

import pytest

from agentcfg.storage import Conflict


REPOSITORY = Path(__file__).resolve().parents[1]


def test_lifecycle_does_not_import_retired_execution_protocol():
  tree = ast.parse((REPOSITORY / "src/agentcfg/pi_lifecycle.py").read_text())
  imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
  assert not imported & {"activity", "pi_catalog", "workspace_leases", "process_tracking"}


def test_any_legacy_execution_owner_is_preserved_and_blocks_maintenance(tmp_path, sentinel_factory):
  from agentcfg.pi_lifecycle import assert_inactive
  directory = tmp_path / "activity/leases"
  directory.mkdir(parents=True, mode=0o700)
  (directory / "synthetic-owner.json").write_text('{"state":"unknown","sentinel":"preserve"}')
  before = sentinel_factory(tmp_path)
  with pytest.raises(Conflict): assert_inactive(tmp_path)
  before.assert_unchanged()


@pytest.mark.parametrize("linked", [False, True])
def test_legacy_git_owner_blocks_new_start_without_parsing_or_removing_it(tmp_path, sentinel_factory, linked):
  from agentcfg.pi_lifecycle import assert_no_legacy_workspace_owner
  work = tmp_path / "work"
  work.mkdir()
  git = tmp_path / "git-metadata" if linked else work / ".git"
  git.mkdir(mode=0o700)
  if linked: (work / ".git").write_text("gitdir: ../git-metadata\n")
  private = git / "agentcfg"
  private.mkdir(mode=0o700)
  (private / "write-lease.json").write_text("synthetic opaque historic owner")
  before = sentinel_factory(tmp_path)
  with pytest.raises(Conflict): assert_no_legacy_workspace_owner(work)
  before.assert_unchanged()


def test_no_legacy_owner_has_no_write_side_effects(tmp_path, sentinel_factory):
  from agentcfg.pi_lifecycle import assert_inactive, assert_no_legacy_workspace_owner
  (tmp_path / ".git").mkdir()
  before = sentinel_factory(tmp_path)
  assert_inactive(tmp_path / "absent-state")
  assert_no_legacy_workspace_owner(tmp_path)
  before.assert_unchanged()


def test_new_entrypoints_do_not_import_old_execution_or_vendor_code():
  retired = {"activity", "activity_linux", "activity_macos", "workspace_leases", "process_tracking", "pi_recovery",
    "pi_host", "pi_supervisor", "pi_control", "pi_vendor", "model_delegate", "pi_catalog"}
  for filename in ("pi.py", "pi_dependencies.py", "pi_runtime_packages.py", "pi_lifecycle.py", "runtime.py", "run_owners.py"):
    tree = ast.parse((REPOSITORY / "src/agentcfg" / filename).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not imports & retired, filename


def test_legacy_inventory_is_metadata_only_and_never_copies_models_credentials_or_sessions(tmp_path, sentinel_factory, monkeypatch):
  from agentcfg.pi_inventory import build_inventory
  from agentcfg.storage import Tree
  old = tmp_path / "old-home"
  old.mkdir()
  (old / "settings.json").write_text('{"theme":"catppuccin-frappe","packages":["npm:retired@1.0.0"]}')
  (old / "models.json").write_text('{"apiKey":"SYNTHETIC_PRIVATE_SENTINEL"}')
  (old / "auth.json").write_text("SYNTHETIC_PRIVATE_SENTINEL")
  (old / "sessions").mkdir()
  (old / "sessions/history.jsonl").write_text("SYNTHETIC_PRIVATE_SENTINEL")
  before = sentinel_factory(old)
  read = Tree.read
  def nonsecret_only(tree, name, *args, **kwargs):
    assert name not in ("auth.json", "models.json") and not name.startswith("sessions/")
    return read(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", nonsecret_only)
  report = build_inventory(old, repository=REPOSITORY, profile="pi-base")
  assert report["schema_version"] == 2
  assert report["proposed_overrides"] == {}
  assert report["ready_to_deploy"] is False
  assert "SYNTHETIC_PRIVATE_SENTINEL" not in json.dumps(report)
  assert "pi-default" not in json.dumps(report)
  assert report["blockers"]
  before.assert_unchanged()


@pytest.mark.parametrize("profile", ["pi-default", "pi-managed", "pi-cursor", "pi-codex"])
def test_inventory_does_not_route_retired_target_profiles(tmp_path, profile):
  from agentcfg.pi_inventory import build_inventory
  from agentcfg.schema import ConfigError
  with pytest.raises(ConfigError): build_inventory(tmp_path, repository=REPOSITORY, profile=profile)


RETIRED_MODULES = (
  "model_delegate",
  "model_delegate_backends",
  "model_delegate_batch",
  "model_delegate_cli",
  "model_delegate_context",
  "pi_acceptance",
  "pi_assets",
  "pi_auxiliary",
  "pi_catalog",
  "pi_checkpoints",
  "pi_checks",
  "pi_codex_admission",
  "pi_cold_rebuild",
  "pi_cold_sandbox",
  "pi_commands",
  "pi_control",
  "pi_delegate",
  "pi_delegate_commands",
  "pi_delegate_files",
  "pi_delegate_mcp",
  "pi_delegate_policy",
  "pi_delegate_spawn",
  "pi_diagnostics",
  "pi_editor",
  "pi_evidence",
  "pi_extension_bridge",
  "pi_git_review",
  "pi_git_status",
  "pi_guarded_files",
  "pi_host",
  "pi_live_project",
  "pi_login",
  "pi_mcp",
  "pi_mcp_script",
  "pi_mcp_stdio",
  "pi_native_build",
  "pi_native_roots",
  "pi_operations",
  "pi_output",
  "pi_pid_namespace",
  "pi_readseek",
  "pi_readseek_mutations",
  "pi_readseek_native",
  "pi_readseek_prepare",
  "pi_readseek_results",
  "pi_readseek_select",
  "pi_readseek_selection",
  "pi_readseek_snapshot",
  "pi_readseek_source",
  "pi_readseek_vision",
  "pi_resource_reads",
  "pi_rules",
  "pi_scope",
  "pi_services",
  "pi_supervisor",
  "pi_terminal",
  "pi_upgrade",
  "pi_validation",
  "pi_validation_codex",
  "pi_validation_codex_provider",
  "pi_validation_delegate",
  "pi_validation_fixture",
  "pi_validation_live",
  "pi_validation_live_delegate",
  "pi_validation_live_services",
  "pi_validation_migration",
  "pi_validation_native",
  "pi_validation_parent_loss",
  "pi_validation_provider",
  "pi_validation_recovery",
  "pi_validation_report",
  "pi_validation_runtime",
  "pi_validation_sandbox",
  "pi_validation_service_provider",
  "pi_vendor",
  "pi_verification",
  "pi_web",
  "pi_web_browser",
  "pi_web_cli",
  "pi_web_files",
  "pi_web_git",
  "pi_web_media",
  "pi_web_relay",
  "pi_worker_files",
  "pi_worker_protocol",
  "activity",
  "activity_linux",
  "activity_macos",
  "pi_recovery",
  "process_tracking",
  "workspace_leases",
)


def test_explicit_retired_execution_modules_and_distribution_are_absent():
  for name in RETIRED_MODULES:
    assert not (REPOSITORY / "src/agentcfg" / (name + ".py")).exists(), name
  roots = ["agents/pi/packages/btw-vendor", "agents/pi/packages/colorful-footer", "agents/pi/packages/loop-guard", "agents/pi/packages/mcp-vendor", "agents/pi/packages/model-delegate", "agents/pi/packages/openai-proxy", "agents/pi/packages/openspec-resources", "agents/pi/packages/permission-system-vendor", "agents/pi/packages/processes-vendor", "agents/pi/packages/readseek-vendor", "agents/pi/packages/rules-vendor", "agents/pi/packages/session-yolo", "agents/pi/packages/slopchop-vendor", "agents/pi/packages/smart-compact-vendor", "agents/pi/packages/subagents-patch", "agents/pi/packages/subagents-vendor", "agents/pi/packages/superpowers-vendor", "agents/pi/packages/task-keeper", "agents/pi/packages/todo-vendor", "agents/pi/packages/web-vendor", "agents/pi/runtime", "agents/pi/roles", "agents/pi/extensions", "agents/pi/themes", "locks/pi/pi-default", "locks/pi/pi-managed", "locks/pi/pi-cursor", "locks/pi/pi-codex", "locks/pi/vendor", "shared/skills/model-delegate", "tests/fixtures/pi"]
  for name in roots:
    assert not (REPOSITORY / name).exists(), name
  for name in ("manifest.json", "pi-base/package.json", "pi-base/package-lock.json", "pi-pro/package.json", "pi-pro/package-lock.json"):
    assert (REPOSITORY / "locks/pi" / name).is_file()
  assert (REPOSITORY / "agents/pi/licenses/pi-coding-agent.LICENSE").is_file()


def test_surviving_production_imports_and_literal_dynamic_imports_do_not_reach_old_modules():
  retired = set(RETIRED_MODULES)
  for path in (REPOSITORY / "src").rglob("*.py"):
    for node in ast.walk(ast.parse(path.read_text())):
      names = []
      if isinstance(node, ast.Import):
        names = [item.name for item in node.names]
      elif isinstance(node, ast.ImportFrom):
        names = [node.module] if node.module != "agentcfg" else [item.name for item in node.names]
      elif isinstance(node, ast.Call) and node.args:
        function = node.func
        dynamic = (isinstance(function, ast.Name) and function.id == "__import__"
          or isinstance(function, ast.Attribute) and function.attr == "import_module")
        if dynamic and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
          names = [node.args[0].value]
      assert not {name.rsplit(".", 1)[-1] for name in names if name} & retired, path.name


def test_old_recover_project_and_starter_routes_are_not_registered():
  from agentcfg.cli import build_parser
  parser = build_parser()
  subparsers = next(action for action in parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict))
  assert "recover" not in subparsers.choices and "project" not in subparsers.choices
  plan = subparsers.choices["plan"]
  assert all("--from-starter" not in action.option_strings for action in plan._actions)
