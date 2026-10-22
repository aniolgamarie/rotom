"""pi-footer候选的按选锁与初始化契约；不加载宿主或社区代码。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg import commands, runtime
from agentcfg.adapter import Ownership
from agentcfg.pi_dependencies import dependency_selection, recipe_inputs
from agentcfg.schema import ConfigError
from test_pi_optional_modules import module_workspace, selected_local
from test_pi_reboot_configuration import local, REPOSITORY
from test_pi_reboot_dependencies import fake_npm, recipe_repository, synthetic_workspace
from agentcfg.workspace import load_workspace


FOOTER = "pi-home/extensions/pi-footer.json"


@pytest.mark.parametrize("invalid", [
  "unknown-root", "unknown-widget", "unknown-option", "widget-id", "widget-type", "missing-widget-id",
])
def test_footer_template_schema_rejects_unknown_fields_and_unapproved_widgets(invalid):
  from jsonschema import Draft202012Validator, ValidationError
  value = json.loads((REPOSITORY / "agents/pi/templates/pi-footer.json").read_text())
  schema = json.loads((REPOSITORY / "agents/pi/schemas/footer.schema.json").read_text())
  validator = Draft202012Validator(schema)
  validator.validate(value)
  widget = value["lines"][0][0]
  if invalid == "unknown-root": value["script"] = "synthetic-command"
  elif invalid == "unknown-widget": widget["script"] = "synthetic-command"
  elif invalid == "unknown-option": widget["options"]["script"] = "synthetic-command"
  elif invalid == "widget-id": widget["options"]["widgetId"] = "unapproved-widget"
  elif invalid == "widget-type": widget["type"] = "script"
  else: del widget["options"]["widgetId"]
  with pytest.raises(ValidationError): validator.validate(value)


def test_explicit_footer_candidate_has_two_ordered_entries_and_preserves_preferences(module_workspace, tmp_path):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(plugins=["pi-footer"])
  from jsonschema import Draft202012Validator
  Draft202012Validator(json.loads((REPOSITORY / "schemas/pi-lock.schema.json").read_text())).validate(lock.metadata)
  piece = lock.metadata["profiles"]["pi-base"]
  assert piece["dependencies"]["pi-footer"] == "0.5.1"
  supports = [item for item in piece["recipe_inputs"]["resources"] if item["kind"] == "module-support"]
  assert {item["id"] for item in supports} == {"pi-command-aliases", "pi-status-observer", "pi-footer-config"}
  root = backend.root(workspace, backend.runtime_identity(workspace, lock))
  for item in supports:
    assert (root / item["target"]).read_bytes() == (workspace.repository / item["path"]).read_bytes()
    assert (root / item["target"]).stat().st_mode & 0o777 == 0o600
  native = workspace.instance / FOOTER
  value = json.loads(native.read_text())
  assert value["separator"] == "none" and value["iconMode"] == "text" and value["terminal"]["widthMode"] == "full"
  assert value["minimalist"] is False
  assert len(value["lines"]) == 3
  assert [item["options"]["widgetId"] for row in value["lines"] for item in row if item["type"] == "event"] == [
    "agentcfg-selection", "agentcfg-provider", "agentcfg-activity", "agentcfg-context", "agentcfg-meter",
    "agentcfg-tools", "agentcfg-statistics", "agentcfg-timing"]
  assert [[item["type"] for item in row if item["type"] not in ("separator", "flex-separator")] for row in value["lines"]] == [
    ["event", "thinking-level", "event", "event", "cwd-basename", "git-branch"],
    ["event", "event", "event"], ["event", "event"]]
  value["separator"] = "dot"
  value["enabled"] = False
  native.write_text(json.dumps(value))
  before = native.read_bytes(), native.stat().st_ino
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  assert (native.read_bytes(), native.stat().st_ino) == before
  assert runtime.run(workspace, cwd=tmp_path) == 19
  argv, kwargs = launched[0]
  extensions = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"]
  assert extensions[:2] == [str(root / "support/command-aliases.mjs"), str(root / "node_modules/pi-footer/src/index.ts")]
  assert extensions[-2:] == ["builtin:codemode", str(root / "support/status-observer.mjs")]
  assert kwargs["env"]["PI_FOOTER_CONFIG"] == str(native)
  assert workspace.adapter.feature_readiness(workspace.resolved.data)["status_bar"]["information_parity"] == "not_verified"
  target = next(target for target in workspace.adapter.managed_targets(workspace.resolved.data) if target.path == FOOTER)
  assert target.ownership == Ownership.INITIALIZE


def test_explicitly_unselected_footer_has_no_template_binding_loading_or_external_override(tmp_path):
  workspace = load_workspace(selected_local(tmp_path / "local.toml", plugins=[]), repository=REPOSITORY)
  inputs = recipe_inputs(REPOSITORY, "pi-base", dependency_selection(workspace.resolved.data))
  assert "pi-footer" not in inputs["modules"]
  assert not any(item.get("id") in ("pi-status-observer", "pi-footer-config") for item in inputs["resources"])
  assert not any(target.path == FOOTER for target in workspace.adapter.managed_targets(workspace.resolved.data))
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path, runtime_root=tmp_path / "runtime",
    instance_root=workspace.instance, lock_identity="synthetic")
  assert not any("pi-footer" in arg or "status-observer" in arg for arg in spec.argv)
  env = {"PATH": "synthetic", "PI_FOOTER_CONFIG": "/synthetic/external.json"}
  assert "PI_FOOTER_CONFIG" not in workspace.adapter.adjust_launch_environment(workspace, spec, env, None)


@pytest.mark.parametrize("source", ["agents/pi/support/status-observer.mjs", "agents/pi/templates/pi-footer.json"])
def test_footer_sources_are_selected_only_dependency_inputs(module_workspace, tmp_path, source):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(plugins=["pi-footer"])
  pro = synthetic_workspace(workspace.repository, tmp_path, profile="pi-pro")
  before = backend.runtime_identity(pro, lock)
  path = workspace.repository / source
  path.write_bytes(path.read_bytes() + b"\n")
  assert backend.read_lock(workspace.repository) == lock
  with pytest.raises(ConfigError): backend.runtime_identity(pro, lock)
  with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)


@pytest.mark.parametrize("extra", [
  '[overrides.profiles.pi-base.agent_options.footer]\nseparator="arbitrary"\n',
  '[overrides.profiles.pi-base.agent_options.ui]\nfooter="arbitrary"\n',
])
def test_unknown_footer_options_are_rejected(tmp_path, extra):
  with pytest.raises(ConfigError): load_workspace(local(tmp_path / "local.toml", extra=extra), repository=REPOSITORY)


def test_unselected_footer_source_changes_do_not_invalidate_current_slices(module_workspace):
  make, backend, calls, launched = module_workspace
  workspace, lock = make()
  identity = backend.runtime_identity(workspace, lock)
  for source in ("agents/pi/support/status-observer.mjs", "agents/pi/templates/pi-footer.json"):
    path = workspace.repository / source
    path.write_bytes(path.read_bytes() + b"\n")
  assert backend.read_lock(workspace.repository) == lock
  assert backend.runtime_identity(workspace, lock) == identity


def test_footer_observer_is_last_with_mcp_and_other_admitted_plugin(module_workspace, tmp_path):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(plugins=["pi-footer", "cache-hit-monitor"], mcp=["pi-context7"])
  assert runtime.run(workspace, cwd=tmp_path) == 19
  argv, kwargs = launched[0]
  extensions = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"]
  assert extensions[0] == "builtin:mcp"
  assert extensions[-1].endswith("/support/status-observer.mjs")
  assert sum(entry.endswith("/node_modules/pi-footer/src/index.ts") for entry in extensions) == 1
  assert sum(entry.endswith("/support/status-observer.mjs") for entry in extensions) == 1
