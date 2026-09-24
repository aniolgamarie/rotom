"""终端服务只验证声明与假进程；不连接真实 tmux/Zellij 或执行脚本。"""
from pathlib import Path
import pytest
from agentcfg.pi_services import prepare_report
from agentcfg.pi_checks import linux_verifier_argv, macos_verifier_policy, check_environment
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_commands import fixture


def setup(tmp_path):
  commands, host, _, principal = fixture(tmp_path)
  script = tmp_path / "agent-report.sh"; script.write_text("fixture notifier, never execute"); script.chmod(0o600)
  host.manifest()["resource_ids"] = {"extensions": {"gentle-agent-state": "entry"}}
  host.manifest()["options"]["agent_state"] = {"mode": "service", "executable": str(tmp_path / "fixture-command"), "version": "fixture",
    "args": [str(script)], "files": [str(script)], "socket_paths": [], "environment": {}, "pane": "%9", "timeout_seconds": 5}
  return commands, host, principal, {"operation_id": "report", "state": "working"}, script


def test_reporter_only_writes_instance_state_and_uses_existing_supervised_command(tmp_path):
  commands, host, principal, args, script = setup(tmp_path)
  ticket = prepare_report(commands, principal, args)
  value = commands.records[ticket["operation_id"]]; check = value["check"]
  state = str(Path(host.config["instance_root"]) / "pi-home/service-state/agent-report")
  assert check["cwd"] == state and check["write_roots"] == [state]
  assert check["argv"][-2:] == ["%9", "working"]
  assert str(script) in check["read_roots"] and host.store.read(ticket["lease_id"])["planned_workspaces"] == []
  argv = linux_verifier_argv(check, temporary=tmp_path / "temporary", system_roots=())
  assert "--unshare-all" in argv and host.manifest()["options"]["paths"]["roots"]["project"]["path"] not in argv
  assert check_environment(check, tmp_path / "temporary")["XDG_RUNTIME_DIR"] == state
  launch = commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})
  assert launch.capture_root and not launch.stdin_pipe
  assert prepare_report(commands, principal, args) == ticket
  with pytest.raises(Conflict, match="SERVICE_BUSY"):
    prepare_report(commands, principal, {**args, "operation_id": "second"})


@pytest.mark.parametrize("kind", ["unselected", "worker", "state", "environment", "outside-pane", "project-script", "symlink", "missing"])
def test_service_invalid_bindings_fail_before_allocation(tmp_path, kind):
  commands, host, principal, args, script = setup(tmp_path)
  binding = host.manifest()["options"]["agent_state"]
  if kind == "unselected": host.manifest()["resource_ids"] = {}
  if kind == "worker": principal = Principal("worker")
  if kind == "state": args["state"] = "arbitrary command"
  if kind == "environment": binding["environment"] = {"BASH_ENV": "/script"}
  if kind == "outside-pane": binding.pop("pane"); binding["pane_env"] = "TMUX_PANE"
  if kind == "project-script":
    inside = Path(host.manifest()["options"]["paths"]["roots"]["project"]["path"]) / "script.sh"
    inside.write_text("business script"); binding["files"] = [str(inside)]
  if kind == "symlink":
    link = tmp_path / "link.sh"; link.symlink_to(script); binding["files"] = [str(link)]
  if kind == "missing": binding["files"] = [str(tmp_path / "missing.sh")]
  before = len(host.store.records())
  with pytest.raises((ConfigError, Conflict, OSError)): prepare_report(commands, principal, args)
  assert len(host.store.records()) == before


def test_service_changed_script_or_manifest_cannot_start_a_queued_job(tmp_path):
  commands, host, principal, args, script = setup(tmp_path)
  ticket = prepare_report(commands, principal, args)
  script.write_text("changed after allocation")
  with pytest.raises(Conflict, match="SERVICE_FILE_CHANGED"):
    commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})
  host.manifest()["options"]["agent_state"]["pane"] = "%10"
  with pytest.raises(Conflict, match="ORDINARY_COMMAND_STALE"):
    commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})


def test_socket_policy_opens_only_declared_unix_endpoint(tmp_path):
  from agentcfg.activity import digest
  commands, host, principal, args, _ = setup(tmp_path)
  ticket = prepare_report(commands, principal, args)
  check = commands.records[ticket["operation_id"]]["check"]
  check["socket_paths"] = [str(tmp_path / "terminal.sock")]
  check["binding_digest"] = digest({key: value for key, value in check.items() if key != "binding_digest"})
  policy = macos_verifier_policy(check, temporary=tmp_path / "temporary")
  assert '(deny default)' in policy and '(remote unix-socket (literal "' in policy
  assert '(remote ip ' not in policy and '(allow network-outbound)' not in policy


def test_service_keeps_parent_file_denials_and_never_opens_other_instance_state(tmp_path):
  commands, host, principal, args, script = setup(tmp_path)
  instance = Path(host.config["instance_root"]); instance.mkdir(mode=0o700)
  host.config["protected_roots"] = [str(instance), str(host.root)]
  ticket = prepare_report(commands, principal, args)
  check = commands.records[ticket["operation_id"]]["check"]
  assert str(instance) not in check["read_roots"]
  assert str(instance / "pi-home/service-state/agent-report") in check["write_roots"]
  # 新请求不能越过父 deny 去读取指定脚本。
  host.store.abort_allocation(ticket["lease_id"], host.store.owner)
  host.manifest()["options"]["paths"]["roots"]["scripts"] = {"path": str(tmp_path), "purpose": "read"}
  host.manifest()["permission_policy"]["rules"].append({"kind": "file", "effect": "deny", "root_ref": "scripts", "relative_path": script.name})
  with pytest.raises(Conflict): prepare_report(commands, principal, {**args, "operation_id": "denied"})
