"""文件工具从正式 RPC 准入到隔离命令意图；原生程序/Node 都是不可执行的夹具。"""
import json
from pathlib import Path

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_checks import check_environment, linux_verifier_argv
from agentcfg.pi_supervisor import Principal
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_commands import fixture


def setup(tmp_path):
  commands, host, args, principal = fixture(tmp_path)
  from agentcfg.pi_operations import OrdinaryOperations
  operations = OrdinaryOperations(host)
  manifest = host.manifest(); manifest["plugins"] = ["pi-readseek"]
  manifest["options"]["readseek"] = {"node_tool_ref": "build", "max_seconds": 60, "settings": {"syntaxValidation": "warn"}}
  manifest["options"]["external_tools"]["build"].update(args=[], version="v24.14.0")
  root = Path(__file__).parents[1]
  with Tree(host.runtime_root) as tree:
    registry = json.loads(tree.read("runtime/commands.json")[0])
    registry["programs"]["readseek"] = {"entrypoint": "runtime/readseek-process.mjs", "kind": "external", "engine": "node"}
    registry["programs"]["readseek-driver"] = {"entrypoint": "supervisor/scripts/pi-readseek.py", "kind": "external", "engine": "python"}
    tree.write_state("runtime/commands.json", json_bytes(registry))
    tree.write_state("runtime/profile.json", json_bytes({"toolchains": {"node": "v24.14.0"}}))
    tree.write_state("runtime/readseek-process.mjs", b"fixture, never execute")
    tree.write_state("supervisor/scripts/pi-readseek.py", b"fixture, never execute")
    tree.write_state("runtime/readseek-tool-contracts.json", (root / "agents/pi/runtime/readseek-tool-contracts.json").read_bytes())
    tree.write_state("bin/readseek", b"fixture, never execute")
  request = {"operation_id": "readseek", "session_id": "fixture-session", "cwd": args["cwd"],
    "tool_name": "readSeek_write", "input": {"path": "code.txt", "content": "updated"}}
  return operations, host, principal, request


def test_preflight_reserves_writer_and_stage_exports_only_authorized_file(tmp_path, monkeypatch):
  operations, host, principal, request = setup(tmp_path)
  monkeypatch.setenv("OPENAI_API_KEY", "synthetic private value")
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  assert ticket["kind"] == "readseek"
  assert not (host.root / "activity/readseek-homes").exists()
  assert operations.handle(principal, "ordinary_readseek_prepare", request) == ticket
  staged = operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})
  assert staged["kind"] == "command" and staged["lease_id"] == ticket["lease_id"]
  value = operations.commands.records[ticket["operation_id"]]; check = value["check"]
  home = Path(check["cwd"])
  # driver脚本按closed()要求顶层temporary；缺失会让第一方驱动一启动即退出5。
  scratch = Path(value["temporary"])
  assert scratch.is_absolute() and scratch.is_relative_to(Path(host.root))
  assert scratch != home and not scratch.is_relative_to(home) and not home.is_relative_to(scratch)
  snapshot = Path(operations.readseek.pending[ticket["operation_id"]]["snapshot_root"])
  assert (snapshot / "code.txt").read_text() == "source"
  assert not (snapshot / ".git").exists()
  document = json.loads((home / "request.json").read_text())
  assert document["params"]["path"] == str(snapshot / "code.txt")
  assert document["settings"] == {"syntaxValidation": "warn"}
  assert check["write_roots"] == [str(home), str(snapshot), document["cache_root"]] and check["network"] == "none"
  env = check_environment(check, tmp_path / "scratch")
  assert env["PI_OFFLINE"] == "1" and "OPENAI_API_KEY" not in env
  argv = linux_verifier_argv(check, temporary=tmp_path / "scratch", system_roots=(), denied_paths=value["denied_paths"])
  assert str(Path(request["cwd"])) not in argv
  assert operations.commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]}).stdin_pipe
  with pytest.raises(Conflict, match="ALREADY_STAGED"):
    operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})


def test_readonly_compute_has_its_own_lease_without_a_writer_reservation(tmp_path):
  operations, host, principal, request = setup(tmp_path)
  request.update(tool_name="readSeek_digest", input={"path": "code.txt"})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  assert ticket["lease_id"] != principal.lease_id and ticket["write"] is False
  assert host.store.read(ticket["lease_id"])["planned_workspaces"] == []
  operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})


@pytest.mark.parametrize("kind", ["worker", "unselected", "unknown-param", "version", "missing-native", "command-denied"])
def test_invalid_bindings_fail_before_an_execution_lease_is_created(tmp_path, kind):
  operations, host, principal, request = setup(tmp_path)
  if kind == "worker": principal = Principal("worker")
  if kind == "unselected": host.manifest()["plugins"] = []
  if kind == "unknown-param": request["input"]["shell"] = "forbidden"
  if kind == "version": host.manifest()["options"]["external_tools"]["build"]["version"] = "v99"
  if kind == "missing-native": (host.runtime_root / "bin/readseek").unlink()
  if kind == "command-denied": host.manifest()["permission_policy"]["rules"][-1]["effect"] = "deny"
  before = len(host.store.records())
  with pytest.raises((Conflict, ConfigError, DependencyError)):
    operations.handle(principal, "ordinary_readseek_prepare", request)
  assert len(host.store.records()) == before


def test_unbound_directory_selection_is_not_silently_treated_as_a_complete_scan(tmp_path):
  operations, host, principal, request = setup(tmp_path)
  request.update(tool_name="readSeek_rename", input={"path": "code.txt", "line": 1, "to": "renamed", "workspace": True})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  with pytest.raises(ConfigError, match="selection-tool-required"):
    operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})
  assert ticket["operation_id"] not in operations.commands.records
  assert (Path(request["cwd"]) / "code.txt").read_text() == "source"


def test_workspace_selection_and_export_share_the_original_writer_lease(tmp_path):
  from test_pi_activity import identity
  operations, host, principal, request = setup(tmp_path)
  host.manifest()["options"]["readseek"]["git_tool_ref"] = "build"
  (Path(request["cwd"]) / "second.txt").write_text("reference")
  request.update(tool_name="readSeek_rename", input={"path": "code.txt", "line": 1, "to": "renamed", "workspace": True})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  staged = operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})
  command = operations.commands.records[ticket["operation_id"]]
  assert len(command["readseek_driver"]["jobs"]) == 2
  assert all(job["check"]["write_roots"] == [] for job in command["readseek_driver"]["jobs"])
  assert len(host.store.records()) == 2  # 宿主和本次执行，没有另一个选择任务。
  native = operations.commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})
  assert native.argv[3].endswith("pi-readseek.py")
  home = Path(command["check"]["cwd"])
  snapshot = Path(operations.readseek.pending[ticket["operation_id"]]["snapshot_root"])
  assert not list(snapshot.iterdir())
  with Tree(home) as tree:
    tree.write_new("selection-0.stdout", b"code.txt\0second.txt\0")
    tree.write_new("selection-1.stdout", b"")
  host.store.processes.current[203] = identity(203)
  host.store.start(ticket["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  worker = Principal("worker", ticket["lease_id"], 1)
  assert operations.handle(worker, "ordinary_readseek_export", {"operation_id": ticket["operation_id"]}) == {"exported": True}
  assert (snapshot / "second.txt").read_text() == "reference"
  assert operations.readseek.records[ticket["operation_id"]]["lease_id"] == staged["lease_id"]
  assert json.loads((home / "selection.json").read_text())["categories"]["cached"] == ["code.txt", "second.txt"]
  with pytest.raises(Conflict, match="DRIVER_IDENTITY"):
    operations.handle(principal, "ordinary_readseek_export", {"operation_id": ticket["operation_id"]})


def test_expired_readonly_preflight_reclaims_its_unstarted_compute_lease(tmp_path):
  from datetime import timedelta
  operations, host, principal, request = setup(tmp_path)
  request.update(tool_name="readSeek_digest", input={"path": "code.txt"})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  now = operations.now(); operations.now = lambda: now + timedelta(seconds=361)
  operations.tick()
  assert host.store.read(ticket["lease_id"])["termination_evidence"]["verified"]
  assert ticket["operation_id"] not in operations.readseek.pending


def test_readseek_settings_schema_retains_original_settings_and_rejects_override_tools():
  from agentcfg.pi_catalog import validate
  settings = {"readseek": {"node_tool_ref": "node", "git_tool_ref": "git", "rg_tool_ref": "rg", "max_seconds": 300,
    "settings": {"syntaxValidation": "block", "imageMode": "auto", "grep": {"maxLines": 100}, "display": {"edit": "expanded"}}}}
  validate("options", settings)
  settings["readseek"]["settings"]["overrideTools"] = ["write"]
  with pytest.raises(ConfigError): validate("options", settings)


def test_subdirectory_session_keeps_workspace_rename_inside_its_original_cwd(tmp_path):
  from test_pi_activity import identity
  operations, host, principal, request = setup(tmp_path)
  project = Path(request["cwd"]); sub = project / "sub"; sub.mkdir(); (sub / "code.txt").write_text("sub source")
  host.manifest()["options"]["readseek"]["git_tool_ref"] = "build"
  request.update(cwd=str(sub), tool_name="readSeek_rename", input={"path": "code.txt", "line": 1, "to": "renamed", "workspace": True})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})
  command = operations.commands.records[ticket["operation_id"]]; home = Path(command["check"]["cwd"])
  assert all(job["search_root"] == str(sub) for job in command["readseek_driver"]["jobs"])
  with Tree(home) as tree:
    tree.write_new("selection-0.stdout", b"code.txt\0"); tree.write_new("selection-1.stdout", b"")
  host.store.processes.current[203] = identity(203)
  host.store.start(ticket["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  operations.handle(Principal("worker", ticket["lease_id"], 1), "ordinary_readseek_export", {"operation_id": ticket["operation_id"]})
  worker = json.loads((home / "request.json").read_text())
  snapshot = Path(worker["snapshot_root"])
  assert worker["working_directory"] == str(snapshot / "sub")
  assert worker["params"]["path"] == str(snapshot / "sub/code.txt")
  assert not (snapshot / "code.txt").exists()


def test_grep_requires_explicit_rg_and_installs_a_private_no_download_entry(tmp_path):
  operations, host, principal, request = setup(tmp_path)
  rule = host.manifest()["permission_policy"]["rules"][0]
  rule["tool_ids"].append("grep"); rule["operations"].append("search")
  host.manifest()["options"]["readseek"]["rg_tool_ref"] = "build"
  request.update(tool_name="readSeek_grep", input={"path": "code.txt", "pattern": "source"})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})
  command = operations.commands.records[ticket["operation_id"]]; home = Path(command["check"]["cwd"])
  assert (home / "pi/bin/rg").stat().st_mode & 0o777 == 0o700
  assert "readseek-rg-main.mjs" in (home / "pi/bin/rg").read_text()
  assert command["check"]["service_environment"]["AGENTCFG_READSEEK_RG"].endswith("fixture-command")
  Path(command["readseek_auxiliary_checks"][0]["argv"][0]).write_text("changed after admission")
  with pytest.raises(Conflict): operations.commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})


def test_readonly_media_export_uses_the_same_sixteen_mebibyte_ceiling_as_ordinary_read(tmp_path):
  operations, host, principal, request = setup(tmp_path)
  body = b"synthetic document body " * 60000
  (Path(request["cwd"]) / "document.pdf").write_bytes(body)
  request.update(tool_name="readSeek_view", input={"path": "document.pdf"})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})
  home = Path(operations.commands.records[ticket["operation_id"]]["check"]["cwd"])
  snapshot = Path(json.loads((home / "request.json").read_text())["snapshot_root"])
  assert (snapshot / "document.pdf").read_bytes() == body


def test_session_cache_and_file_stamp_are_stable_but_old_private_scope_is_removed_only_after_termination(tmp_path):
  operations, host, principal, request = setup(tmp_path)
  request.update(tool_name="readSeek_digest", input={"path": "code.txt"})
  first = operations.handle(principal, "ordinary_readseek_prepare", request)
  operations.handle(principal, "ordinary_readseek_stage", {"operation_id": first["operation_id"]})
  before = dict(operations.readseek.pending[first["operation_id"]])
  snapshot, cache = Path(before["snapshot_root"]), Path(before["cache_root"])
  (cache / "node-reference").write_text("synthetic native cache")
  (snapshot / "stale.txt").write_text("old private scope")
  outside = tmp_path / "outside"; outside.mkdir(); (outside / "sentinel").write_text("unchanged")
  (snapshot / "link").symlink_to(outside, target_is_directory=True)
  original_stamp = (Path(request["cwd"]) / "code.txt").stat().st_mtime_ns
  assert (snapshot / "code.txt").stat().st_mtime_ns == original_stamp
  request["operation_id"] = "next"
  with pytest.raises(Conflict, match="SESSION_BUSY"):
    operations.handle(principal, "ordinary_readseek_prepare", request)
  assert (snapshot / "stale.txt").exists()
  host.store.abort_allocation(first["lease_id"], host.store.owner)
  operations.commands.finish(principal, {"operation_id": first["operation_id"]})
  operations.readseek.discard(principal, {"operation_id": first["operation_id"]})
  # 上次拒绝的准入 ID 已留下证据，重开一次明确的新调用。
  request["operation_id"] = "after-termination"
  second = operations.handle(principal, "ordinary_readseek_prepare", request)
  operations.handle(principal, "ordinary_readseek_stage", {"operation_id": second["operation_id"]})
  current = operations.readseek.pending[second["operation_id"]]
  assert current["snapshot_root"] == str(snapshot) and current["cache_root"] == str(cache)
  assert (cache / "node-reference").read_text() == "synthetic native cache"
  assert (snapshot / "code.txt").stat().st_mtime_ns == original_stamp
  assert not (snapshot / "stale.txt").exists() and not (snapshot / "link").exists()
  assert (outside / "sentinel").read_text() == "unchanged"
