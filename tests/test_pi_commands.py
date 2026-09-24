"""普通命令仅检查准入和沙箱argv，所有子进程为替身。"""
from pathlib import Path
from types import SimpleNamespace
import pytest

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.pi_catalog import validate
from agentcfg.pi_checks import linux_verifier_argv, macos_verifier_policy
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_operations import setup


def fixture(tmp_path, writable=False):
  operations, host, cwd, principal = setup(tmp_path)
  executable = tmp_path / "fixture-command"; executable.write_text("fake command, never execute"); executable.chmod(0o700)
  binding = {"executable": str(executable), "version": "fixture", "args": ["--literal", "a b"], "project_root": "project",
    "read_roots": ["project"], "write_roots": ["project"] if writable else [], "timeout_seconds": 20}
  host.manifest()["options"]["external_tools"] = {"build": binding}
  host.manifest()["permission_policy"]["rules"].append({"id": "bound-build", "kind": "command", "effect": "allow", "tool_ids": ["bash"], "operations": ["execute"], "command_ref": "tool:build"})
  host.server = SimpleNamespace(endpoint=tmp_path / "endpoint")
  host.service.issue_capability = lambda *args: "fixture-worker-token"
  with Tree(host.runtime_root) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"ordinary-command": {"entrypoint": "supervisor/scripts/pi-project-check", "kind": "external", "engine": "python"}}}))
    tree.write_state("supervisor/scripts/pi-project-check", b"fixture, never execute")
  args = {"operation_id": "command", "role_id": "main", "cwd": cwd, "tool_name": "bash", "input": {"command": "agentcfg:build"}}
  return operations.commands, host, args, principal


def test_bound_readonly_command_keeps_literal_argv_and_readonly_namespace(tmp_path):
  commands, host, args, principal = fixture(tmp_path)
  ticket = commands.prepare(principal, args)
  lease = host.store.read(ticket["lease_id"])
  assert lease["planned_workspaces"] == [] and ticket["write"] is False
  value = commands.records[ticket["operation_id"]]; validate("operation-grant", value["grant"])
  compiled = value["check"]
  argv = linux_verifier_argv(compiled, temporary=tmp_path / "sandbox", system_roots=())
  assert ("--ro-bind", args["cwd"], args["cwd"]) in tuple(zip(argv, argv[1:], argv[2:]))
  assert argv[-3:] == (str(tmp_path / "fixture-command"), "--literal", "a b")
  policy = macos_verifier_policy(compiled, temporary=tmp_path / "sandbox")
  assert '(allow file-write* (subpath "' + args["cwd"] + '"))' not in policy
  command = commands.command(lease, {"operation_id": ticket["operation_id"]})
  assert "-I" in command.argv and "-B" in command.argv
  assert command.capture_root == host.root / "activity/outputs" / lease["lease_id"]


def test_writable_command_conflicts_with_an_ordinary_file_writer_and_policy_change_revokes_it(tmp_path):
  commands, host, args, principal = fixture(tmp_path, writable=True)
  ticket = commands.prepare(principal, args)
  lease = host.store.read(ticket["lease_id"])
  assert lease["planned_workspaces"] and host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  from agentcfg.pi_operations import OrdinaryOperations
  with pytest.raises(Conflict):
    OrdinaryOperations(host).prepare(principal, {**args, "operation_id": "other", "tool_name": "write", "input": {"path": "code.txt", "content": "must not write"}})
  host.manifest()["permission_policy"]["rules"] = []
  with pytest.raises(Conflict, match="ORDINARY_COMMAND_STALE"):
    commands.command(lease, {"operation_id": ticket["operation_id"]})
  assert (Path(args["cwd"]) / "code.txt").read_text() == "source"


@pytest.mark.parametrize("change", [
  {"input": {"command": "agentcfg:build; unsafe"}}, {"input": {"command": "agentcfg:build", "timeout": 21}},
  {"role_id": "scout"}, {"input": {"command": "agentcfg:build", "cwd": "/"}},
])
def test_unbound_shell_scope_or_timeout_rejects_before_allocation(tmp_path, change):
  commands, host, args, principal = fixture(tmp_path)
  before = len(host.store.records())
  with pytest.raises((Conflict, ConfigError)):
    commands.prepare(principal, {**args, **change})
  assert len(host.store.records()) == before


def test_interactive_stdin_requires_current_binding_and_accepts_only_atomic_bounded_chunks(tmp_path):
  import os
  from test_pi_activity import identity
  commands, host, args, principal = fixture(tmp_path)
  host.manifest()["options"]["external_tools"]["build"]["interactive"] = True
  ticket = commands.prepare(principal, args)
  host.store.processes.current[203] = identity(203)
  host.store.start(ticket["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  read_fd, write_fd = os.pipe()
  stream = os.fdopen(write_fd, "wb", buffering=0)
  host.children = {ticket["lease_id"]: {"process": SimpleNamespace(stdin=stream)}}
  try:
    result = commands.write_stdin(principal, {"operation_id": ticket["operation_id"], "data": "中文\n", "end": False})
    assert result == {"accepted_bytes": 7, "stdin_closed": False}
    assert os.read(read_fd, 7) == "中文\n".encode()
    with pytest.raises(ConfigError): commands.write_stdin(principal, {"operation_id": ticket["operation_id"], "data": "x" * 5000, "end": False})
    host.store.request_cancel(ticket["lease_id"], host.store.owner)
    with pytest.raises(Conflict, match="ORDINARY_COMMAND_STALE"):
      commands.write_stdin(principal, {"operation_id": ticket["operation_id"], "data": "must not send", "end": False})
  finally:
    stream.close(); os.close(read_fd)
