"""媒体命令用假程序，核验 argv、无网络沙箱和终止前输入保护。"""
from pathlib import Path
import pytest
from agentcfg.storage import Conflict
from agentcfg.schema import ConfigError
from test_pi_web_files import fixture


def setup(tmp_path):
  operations, host, cwd, principal = fixture(tmp_path); host.operations = operations
  executable = tmp_path / "ffmpeg-fixture"; executable.write_text("#!/bin/sh\nexit 0\n"); executable.chmod(0o700)
  options = host.manifest()["options"]
  options["external_tools"] = {"ffmpeg": {"executable": str(executable), "version": "fixture"}}
  options["web"]["media"].update(ffmpeg_tool_ref="ffmpeg", ffprobe_tool_ref="ffmpeg")
  host.manifest()["permission_policy"]["rules"].append({"id": "media", "kind": "command", "effect": "allow", "command_ref": "tool:ffmpeg", "tool_ids": ["bash"], "operations": ["execute"]})
  source = Path(cwd) / "movie.mp4"; source.write_bytes(b"fixture video")
  staged = operations.handle(principal, "ordinary_web_file_prepare", {"operation_id": "media", "cwd": cwd, "path": str(source)})
  return operations, host, cwd, principal, staged


def test_media_commands_use_only_snapshot_paths_and_hold_inputs_until_termination(tmp_path):
  operations, host, cwd, principal, staged = setup(tmp_path)
  args = {"operation_id": "frame", "operation": "frame", "file_id": staged["file_id"], "seconds": 1.5}
  ticket = operations.handle(principal, "ordinary_web_media_prepare", args)
  value = operations.commands.records[ticket["operation_id"]]
  assert value["check"]["network"] == "none" and value["check"]["write_roots"] == []
  assert str(Path(staged["directory"]) / "input") in value["check"]["argv"]
  assert cwd not in value["check"]["read_roots"]
  assert "-protocol_whitelist" in value["check"]["argv"] and "-nostdin" in value["check"]["argv"]
  assert operations.handle(principal, "ordinary_web_media_prepare", args) == ticket
  with pytest.raises(Conflict, match="EXECUTION_PROTECTED"):
    operations.handle(principal, "ordinary_web_file_finish", {"file_id": staged["file_id"]})
  host.store.abort_allocation(ticket["lease_id"], host.store.owner)
  operations.handle(principal, "ordinary_web_file_finish", {"file_id": staged["file_id"]})
  assert not Path(staged["directory"]).exists()


@pytest.mark.parametrize("seconds", [True, -1, float("inf"), "1; unsafe"])
def test_media_positions_are_data_and_cannot_inject_command_flags(tmp_path, seconds):
  operations, host, cwd, principal, staged = setup(tmp_path)
  with pytest.raises(ConfigError):
    operations.handle(principal, "ordinary_web_media_prepare", {"operation_id": "frame", "operation": "frame", "file_id": staged["file_id"], "seconds": seconds})


def test_changed_media_snapshot_is_rejected_before_executable_dispatch(tmp_path):
  operations, host, cwd, principal, staged = setup(tmp_path)
  path = Path(staged["directory"]) / "input"; path.chmod(0o600); path.write_bytes(b"changed video")
  with pytest.raises(Conflict, match="CHANGED"):
    operations.handle(principal, "ordinary_web_media_prepare", {"operation_id": "duration", "operation": "duration", "file_id": staged["file_id"]})
  assert operations.commands.records == {}


def test_restart_cleanup_preserves_media_with_a_protected_command_lease(tmp_path):
  from datetime import datetime, timedelta, timezone
  from agentcfg.pi_web_files import WebFiles
  operations, host, cwd, principal, staged = setup(tmp_path)
  ticket = operations.handle(principal, "ordinary_web_media_prepare", {"operation_id": "duration", "operation": "duration", "file_id": staged["file_id"]})
  recovered = WebFiles(operations, now=lambda: datetime.now(timezone.utc) + timedelta(seconds=301))
  recovered.tick(scan=True)
  assert Path(staged["directory"]).exists()
  host.store.abort_allocation(ticket["lease_id"], host.store.owner)
  recovered.tick(scan=True)
  assert not Path(staged["directory"]).exists()
