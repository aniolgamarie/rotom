"""普通覆盖、删除及诊断用合成环境；不执行宿主或读取账号。"""

import json
import os
from pathlib import Path

import pytest

from agentcfg.adapter import EnvironmentBinding, LaunchSpec
from agentcfg.execution_environment import (apply_bindings, capture_caller, declarations,
  differences, prepare, restricted_environment, warn)
from agentcfg.schema import ConfigError, validate_document
from agentcfg.storage import Conflict


def spec(bindings=(), policy="caller"):
  return LaunchSpec(("fixture-host",), Path("/fixture/workspace"), "fixture-lock", tuple(bindings), environment_policy=policy)


def test_schema_accepts_unset_and_rejects_unknown_environment_field():
  base = {"schema_version": 1, "machine": {"id": "fixture", "environment": {"unset": ["VIRTUAL_ENV"]}}}
  validate_document("local", base)
  base["machine"]["environment"]["unknown"] = []
  with pytest.raises(ConfigError):
    validate_document("local", base)


def test_persistent_unset_renders_through_real_dsh_workspace(tmp_path):
  from agentcfg.workspace import load_workspace
  local = tmp_path / "machine.toml"
  local.write_text('schema_version=1\n[machine]\nid="fixture"\n[machine.environment]\nunset=["VIRTUAL_ENV"]\n')
  workspace = load_workspace(local, "dsh-default")
  assert workspace.candidate("fixture-lock").artifacts


@pytest.mark.parametrize("path", ["PATH", "CUSTOM_PATH"])
def test_isolated_rebinding_preserves_nonidentity_values_and_tombstones(path):
  selected = spec((EnvironmentBinding("HOME", "/fixture/instance/user-home"),), "isolated")
  machine = {"environment": {"values": {path: "/fixture/chosen"}}}
  result = prepare(selected, machine, caller={"HOME": "/fixture/caller", "PATH": "/fixture/bin"})
  assert apply_bindings(result, selected)[path] == "/fixture/chosen"
  result = prepare(selected, {}, caller={"HOME": "/fixture/caller", path: "/fixture/bin"}, unset=(path,))
  assert path not in apply_bindings(result, selected)


def test_overrides_and_deletions_have_one_order():
  caller = {"HOME": "/fixture/home", "EDITOR": "caller-editor", "FOO": "caller-value", "PATH": "/fixture/bin"}
  machine = {"editor": "machine-editor", "environment": {"values": {"FOO": "machine-value", "EMPTY": ""}, "unset": ["EDITOR"]}}
  result = prepare(spec(), machine, caller=caller, inherit=("FOO",), unset=("PATH",))
  assert result.values["FOO"] == "caller-value"
  assert "EMPTY" in result.values and result.values["EMPTY"] == ""
  assert "EDITOR" not in result.values and result.values["VISUAL"] == "machine-editor"
  assert "PATH" not in result.values and result.removed == {"EDITOR", "PATH"}


def test_one_shot_inherit_clears_persistent_tombstone():
  result = prepare(spec(), {"environment": {"unset": ["FOO"]}}, caller={"FOO": "", "HOME": "/fixture/home"}, inherit=("FOO",))
  assert result.values["FOO"] == "" and "FOO" not in result.removed


def test_optional_missing_inheritance_differs_from_explicit_request():
  assert "FOO" not in prepare(spec(), {"environment": {"inherit": ["FOO"]}}, caller={}).values
  with pytest.raises(ConfigError, match="environment-explicit-inherit-missing"):
    prepare(spec(), {}, caller={}, inherit=("FOO",))


@pytest.mark.parametrize("inherit,unset", [(("FOO", "FOO"), ()), ((), ("FOO", "FOO")), (("FOO",), ("FOO",))])
def test_one_shot_conflicts_fail(inherit, unset):
  with pytest.raises(ConfigError):
    prepare(spec(), {}, caller={"FOO": "synthetic"}, inherit=inherit, unset=unset)


@pytest.mark.parametrize("name", ["HOME", "XDG_CONFIG_HOME", "API_KEY", "NODE_OPTIONS", "BASH_ENV", "AGENTCFG_CAPABILITY", "DSH_HOME", "BAD=VALUE", "BAD\n"])
def test_protected_or_invalid_one_shot_names_fail_without_echo(name):
  with pytest.raises(ConfigError) as caught:
    prepare(spec(), {}, caller={name: "SYNTHETIC_PRIVATE_VALUE"}, inherit=(name,))
  assert "SYNTHETIC_PRIVATE_VALUE" not in str(caught.value)


def test_adapter_cannot_silently_undo_explicit_override():
  bindings = (EnvironmentBinding("HTTP_PROXY", ""),)
  with pytest.raises(ConfigError, match="environment-adapter-override-unsupported"):
    prepare(spec(bindings), {"environment": {"values": {"HTTP_PROXY": "http://proxy.example.invalid:8080"}}}, caller={})


def test_legacy_one_shot_requires_apply():
  with pytest.raises(Conflict):
    prepare(spec(policy="legacy"), {}, caller={}, unset=("FOO",))


def test_caller_home_and_xdg_are_not_implicitly_replaced():
  caller = {"HOME": "/fixture/home", "XDG_CONFIG_HOME": "/fixture/config", "XDG_RUNTIME_DIR": "/fixture/runtime"}
  result = prepare(spec(), {}, caller=caller)
  assert apply_bindings(result, spec()) == caller
  assert "XDG_DATA_HOME" not in result.values


def test_isolated_host_can_keep_separate_development_environment():
  selected = spec((EnvironmentBinding("HOME", "/fixture/instance/user-home"),), "isolated")
  result = prepare(selected, {}, caller={"HOME": "/fixture/caller", "PATH": "/fixture/bin"})
  assert result.values["HOME"] == "/fixture/caller"
  assert apply_bindings(result, selected)["HOME"] == "/fixture/instance/user-home"


def test_warning_reports_intentional_changes_without_values(capsys):
  caller = {"HOME": "SYNTHETIC_CALLER", "FOO": "SYNTHETIC_VALUE", "SAME": "", "EMPTY": "", "API_KEY": "SYNTHETIC_SECRET"}
  effective = {"HOME": "SYNTHETIC_INSTANCE", "SAME": ""}
  report = differences(caller, effective, sources={"HOME": "adapter-policy", "FOO": "one-shot-unset"})
  warn(report)
  output = capsys.readouterr().err
  assert "environment warning" in output and "HOME" in output and "FOO" in output
  assert "SAME" not in output and "EMPTY" in output
  assert "API_KEY" not in output and "SYNTHETIC" not in output
  assert report["sensitive_excluded"] == 1
  assert {item["name"] for item in report["variables"]} == {"HOME", "FOO", "EMPTY"}


def test_no_warning_for_equal_values_or_source_only_change(capsys):
  warn(differences({"FOO": ""}, {"FOO": ""}, sources={"FOO": "machine-value"}))
  assert capsys.readouterr().err == ""


def test_original_names_can_be_reported_without_reading_secret_values(monkeypatch):
  monkeypatch.setenv("UNRELATED_TOKEN", "SYNTHETIC_SECRET")
  monkeypatch.setenv("UNKNOWN_PUBLIC_NAME", "SYNTHETIC_UNKNOWN")
  names, caller = capture_caller({})
  assert "UNRELATED_TOKEN" in names and "UNRELATED_TOKEN" not in caller
  assert "UNKNOWN_PUBLIC_NAME" in names and "UNKNOWN_PUBLIC_NAME" not in caller
  report = differences(caller, caller, names=names)
  assert "SYNTHETIC" not in json.dumps(report)


def test_protected_inputs_are_summarized_even_when_adapter_rebinds_them():
  report = differences({}, {"AGENTCFG_PROFILE": "selected", "API_KEY": "synthetic-new"},
    names=("AGENTCFG_PROFILE", "API_KEY"))
  assert report["sensitive_excluded"] == 2 and report["variables"] == []
  assert "synthetic-new" not in json.dumps(report)


def test_mcp_argument_expression_is_inert_and_accepts_only_string_argv():
  from agentcfg import native
  expression = 'JSON.parse(process.env.AGENTCFG_MCP_ENV_ARGS).concat(["fixture-server", "$(literal)"])'
  rows = [{"id": "fixture", "config": {"args": native.JS(expression)}}]
  assert native.load(native.dump(rows)) == rows
  for invalid in ('JSON.parse(process.env.AGENTCFG_MCP_ENV_ARGS).concat([null])',
      'JSON.parse(process.env.AGENTCFG_MCP_ENV_ARGS).concat([])',
      'JSON.parse(process.env.AGENTCFG_MCP_ENV_ARGS).concat(["MODE=assignment"])',
      'JSON.parse(process.env.AGENTCFG_MCP_ENV_ARGS).concat(["x"]);process.exit()'):
    with pytest.raises(Conflict):
      native.dump([{"id": "fixture", "config": {"args": native.JS(invalid)}}])
  with pytest.raises(Conflict):
    native.dump([{"id": "fixture", "config": {"command": native.JS(expression)}}])


def test_dsh_bare_mcp_command_requires_selected_path_before_credentials(tmp_path):
  from agentcfg.dsh import DshAdapter
  selected = spec()
  with pytest.raises(ConfigError, match="mcp-stdio-path-required"):
    DshAdapter(tmp_path).validate_operation_environment(None, spec=selected,
      env={"AGENTCFG_MCP_REQUIRES_PATH": "1"})
  DshAdapter(tmp_path).validate_operation_environment(None, spec=selected,
    env={"AGENTCFG_MCP_REQUIRES_PATH": "0"})


def test_restricted_environment_does_not_copy_ordinary_overlays(tmp_path, monkeypatch):
  monkeypatch.setenv("PATH", "/fixture/ordinary-injected")
  monkeypatch.setenv("LD_LIBRARY_PATH", "/fixture/ordinary-library")
  monkeypatch.setenv("SSH_AUTH_SOCK", "/fixture/ordinary-socket")
  child = restricted_environment(tmp_path, "/fixture/locked/bin/node")
  assert child["PATH"].split(os.pathsep)[0] == "/fixture/locked/bin"
  assert "ordinary" not in json.dumps(child)
  assert "LD_LIBRARY_PATH" not in child and "SSH_AUTH_SOCK" not in child


def test_declared_inputs_do_not_capture_dynamic_values(monkeypatch):
  machine = {"environment": {"inherit": ["FOO"]}}
  monkeypatch.setenv("FOO", "SYNTHETIC_PRIVATE_VALUE")
  assert "SYNTHETIC_PRIVATE_VALUE" not in repr(declarations(machine))
