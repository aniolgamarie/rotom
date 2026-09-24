"""脚本解释器准入和沙箱意图使用临时文件；不运行 Node、脚本或宿主。"""
from pathlib import Path
import pytest
from agentcfg.pi_mcp_script import prepare_script
from agentcfg.pi_checks import linux_verifier_argv, check_environment
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree, Conflict
from agentcfg.deployment import json_bytes
from agentcfg.process import DependencyError
from test_pi_commands import fixture


def setup(tmp_path):
  commands, host, _, principal = fixture(tmp_path)
  manifest = host.manifest(); manifest["plugins"] = ["pi-mcp"]
  manifest["options"]["mcp"] = {"scripting": {"enabled": True, "tool_ref": "build", "max_seconds": 30}}
  manifest["options"]["external_tools"]["build"].update(args=[], version="v24.14.0")
  manifest["permission_policy"]["rules"][-1]["tool_ids"] = ["bash"]
  with Tree(host.runtime_root) as tree:
    original = __import__("json").loads(tree.read("runtime/commands.json")[0])
    original["programs"]["mcp-script"] = {"entrypoint": "runtime/mcp-script-process.mjs", "kind": "external", "engine": "node"}
    tree.write_state("runtime/commands.json", json_bytes(original))
    tree.write_state("runtime/mcp-script-process.mjs", b"synthetic worker; never execute")
    tree.write_state("runtime/profile.json", json_bytes({"toolchains": {"node": "v24.14.0"}}))
  return commands, host, principal, {"operation_id": "script", "timeout_seconds": 10}


def test_script_has_only_private_cwd_and_no_business_or_credential_environment(tmp_path, monkeypatch):
  commands, host, principal, args = setup(tmp_path)
  monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-token")
  ticket = prepare_script(commands, principal, args)
  record = commands.records[ticket["operation_id"]]; check = record["check"]
  assert Path(check["cwd"]).is_relative_to(host.root / "activity/mcp-script-homes")
  assert check["write_roots"] == [check["cwd"]] and check["network"] == "none"
  assert len(check["read_roots"]) == 2
  argv = linux_verifier_argv(check, temporary=tmp_path / "scratch", system_roots=())
  business = host.manifest()["options"]["paths"]["roots"]["project"]["path"]
  assert business not in argv and "--unshare-all" in argv
  assert "OPENAI_API_KEY" not in check_environment(check, tmp_path / "scratch")
  lease = host.store.read(ticket["lease_id"])
  assert lease["planned_workspaces"] == []
  assert commands.command(lease, {"operation_id": ticket["operation_id"]}).stdin_pipe
  assert prepare_script(commands, principal, args) == ticket


@pytest.mark.parametrize("kind", ["worker", "unselected", "disabled", "timeout", "denied", "arguments", "version", "missing"])
def test_script_invalid_inputs_fail_before_allocation(tmp_path, kind):
  commands, host, principal, args = setup(tmp_path)
  manifest = host.manifest()
  if kind == "worker": principal = Principal("worker")
  if kind == "unselected": manifest["plugins"] = []
  if kind == "disabled": manifest["options"]["mcp"]["scripting"]["enabled"] = False
  if kind == "timeout": args["timeout_seconds"] = 31
  if kind == "denied": manifest["permission_policy"]["rules"][-1]["effect"] = "deny"
  if kind == "arguments": manifest["options"]["external_tools"]["build"]["args"] = ["--unapproved"]
  if kind == "version": manifest["options"]["external_tools"]["build"]["version"] = "v99.0.0"
  if kind == "missing": (host.runtime_root / "runtime/mcp-script-process.mjs").unlink()
  before = len(host.store.records())
  with pytest.raises((ConfigError, Conflict, DependencyError, OSError)): prepare_script(commands, principal, args)
  assert len(host.store.records()) == before


def test_changed_script_cannot_start_an_already_queued_operation(tmp_path):
  commands, host, principal, args = setup(tmp_path)
  ticket = prepare_script(commands, principal, args)
  (host.runtime_root / "runtime/mcp-script-process.mjs").write_text("changed after admission")
  with pytest.raises(Conflict, match="SERVICE_FILE_CHANGED"):
    commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})
