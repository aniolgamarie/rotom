"""展示启动时已登记的版本；不从当前配置推造历史版本或控制资格。"""
import json

import pytest

from agentcfg import lifecycle, run_owners as owners, workspace
from rotom import cli
from test_rotom_instances import machine, register


def test_runs_keep_their_saved_deployment_and_runtime_versions(machine, monkeypatch):
  registry, first = register(machine)
  _, second = register(machine)
  record = registry.snapshot()[second]
  record["deployed_identity"] = {"deployment": "d" * 64, "runtime": "e" * 64}
  (registry.root / (second + ".json")).write_bytes(owners._encode(record))
  def forbidden(*a, **kw): pytest.fail("cannot resolve current config to label historical runs")
  monkeypatch.setattr(workspace, "load_workspace", forbidden)
  rows = {row["run_id"]: row for row in owners.instances(machine.local, profile="dsh-default")["instances"]}
  assert rows[first]["deployed_identity"] == {"deployment": "b" * 64, "runtime": "c" * 64}
  assert rows[second]["deployed_identity"] == record["deployed_identity"]
  rows[first]["deployed_identity"]["deployment"] = "f" * 64
  assert registry.snapshot()[first]["deployed_identity"]["deployment"] == "b" * 64


@pytest.mark.parametrize("kind", ["legacy", "unregistered"])
def test_unknown_versions_remain_unknown(machine, kind):
  if kind == "legacy":
    register(machine, legacy=True)
    result = owners.instances(machine.local, profile="dsh-default")
  else:
    with lifecycle.guard(machine.workspaces["dsh-default"], shared=True, create=False):
      result = owners.instances(machine.local, profile="dsh-default")
  assert result["instances"][0]["deployed_identity"] is None


@pytest.mark.parametrize("format", ["json", "human"])
def test_cli_displays_full_saved_versions(machine, capsys, format):
  register(machine)
  assert cli.main(["--no-input", "agent", "--local", str(machine.local), "instances", "list",
    "--agent", "dsh", "--format", format]) == 0
  text = capsys.readouterr().out
  if format == "json":
    assert json.loads(text)["instances"][0]["deployed_identity"] == {"deployment": "b" * 64, "runtime": "c" * 64}
  else:
    assert "deployment=" + "b" * 64 in text and "runtime=" + "c" * 64 in text


@pytest.mark.parametrize("command", [["instances", "list"], ["instances", "stop"], ["maintenance", "plan"]])
def test_version_help_is_static(command, monkeypatch, capsys):
  from rotom import preferences
  def forbidden(*a, **kw): pytest.fail("help cannot read runtime or preferences")
  monkeypatch.setattr(preferences, "load_preferences", forbidden)
  monkeypatch.setattr(workspace, "load_instance_workspaces", forbidden)
  assert cli.main(["agent", *command, "--help"]) == 0
  text = capsys.readouterr().out
  assert "deployment" in text and "runtime" in text and "unknown" in text
