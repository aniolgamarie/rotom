"""编辑器测试只检查准入与原始 argv，不运行编辑器或终端。"""
from pathlib import Path
import pytest
from agentcfg.pi_editor import prepare_editor
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_commands import fixture


def setup(tmp_path):
  commands, host, args, principal = fixture(tmp_path)
  manifest = host.manifest(); manifest["plugins"] = ["pi-slopchop"]
  manifest["options"]["slopchop"] = {"editor_tool_ref": "build"}
  binding = manifest["options"]["external_tools"]["build"]
  binding.update(args=["+{line}", "--", "{path}"], write_roots=["project"])
  manifest["permission_policy"]["rules"][-1]["tool_ids"] = ["editor"]
  path = Path(args["cwd"]) / "中文 ; literal.txt"; path.write_text("original")
  request = {"operation_id": "edit", "cwd": args["cwd"], "path": str(path), "line": 12}
  return commands, host, request, principal


def test_editor_uses_literal_file_operand_and_reserves_workspace_before_execution(tmp_path):
  commands, host, request, principal = setup(tmp_path)
  ticket = prepare_editor(commands, principal, request)
  value = commands.records[ticket["operation_id"]]
  assert value["check"]["argv"][1:] == ["+12", "--", request["path"]]
  assert host.store.read(ticket["lease_id"])["planned_workspaces"]
  assert Path(request["path"]).read_text() == "original"
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    prepare_editor(commands, principal, {**request, "operation_id": "second"})


def test_interactive_editor_carries_only_explicit_private_terminal_geometry(tmp_path):
  commands, host, request, principal = setup(tmp_path)
  host.manifest()["options"]["external_tools"]["build"]["interactive"] = True
  ticket = prepare_editor(commands, principal, {**request, "rows": 24, "columns": 80})
  assert ticket["terminal_size"] == [24, 80]
  command = commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})
  assert command.terminal_size == (24, 80) and command.stdin_pipe is True


@pytest.mark.parametrize("invalid", ["terminal", "template", "symlink", "escape", "line"])
def test_editor_rejects_unbound_or_unrepresentable_requests_before_allocating(tmp_path, invalid):
  commands, host, request, principal = setup(tmp_path)
  binding = host.manifest()["options"]["external_tools"]["build"]
  if invalid == "terminal": binding["interactive"] = True
  if invalid == "template": binding["args"] = ["-c", "execute {path}"]
  if invalid == "line": request["line"] = True
  if invalid in ("symlink", "escape"):
    outside = tmp_path / "outside"; outside.write_text("untouched")
    if invalid == "symlink":
      target = Path(request["path"]); target.unlink(); target.symlink_to(outside)
    else: request["path"] = str(outside)
  before = len(host.store.records())
  with pytest.raises((ConfigError, Conflict)):
    prepare_editor(commands, principal, request)
  assert len(host.store.records()) == before
