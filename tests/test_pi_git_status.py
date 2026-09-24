"""Git 检查只用磁盘夹具和假进程，不运行 Git、Pi 或操作系统沙箱。"""
from pathlib import Path
import pytest

from agentcfg.pi_checks import check_environment, linux_verifier_argv, macos_verifier_policy
from agentcfg.pi_git_status import prepare_status, STATUS_ARGS
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict
from agentcfg.schema import ConfigError
from test_pi_commands import fixture


def setup(tmp_path):
  commands, host, args, principal = fixture(tmp_path)
  manifest = host.manifest()
  manifest["resource_ids"] = {"extensions": {"dirty-repo-guard": "entry"}}
  manifest["options"]["dirty_repo_guard"] = {"tool_ref": "build"}
  manifest["options"]["external_tools"]["build"]["args"] = []
  return commands, host, {"cwd": args["cwd"], "operation_id": "status"}, principal


def test_status_has_readonly_git_metadata_and_exclusive_workspace_without_broadening_other_commands(tmp_path):
  commands, host, args, principal = setup(tmp_path)
  ticket = prepare_status(commands, principal, args)
  record = commands.records[ticket["operation_id"]]; check = record["check"]
  assert check["argv"][1:] == STATUS_ARGS and check["write_roots"] == []
  assert str(Path(args["cwd"]) / ".git") in check["read_roots"]
  lease = host.store.read(ticket["lease_id"])
  assert lease["planned_workspaces"] and host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  argv = linux_verifier_argv(check, temporary=tmp_path / "sandbox", system_roots=())
  assert ("--ro-bind", args["cwd"], args["cwd"]) in tuple(zip(argv, argv[1:], argv[2:]))
  assert '(allow file-write* (subpath "' + args["cwd"] + '"))' not in macos_verifier_policy(check, temporary=tmp_path / "sandbox")
  env = check_environment(check, tmp_path / "sandbox")
  assert env["GIT_CONFIG_GLOBAL"] == "/dev/null" and env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_NO_LAZY_FETCH"] == "1"
  assert prepare_status(commands, principal, args) == ticket
  ordinary = commands.prepare(principal, {**args, "operation_id": "ordinary", "role_id": "main", "tool_name": "bash", "input": {"command": "agentcfg:build"}})
  assert str(Path(args["cwd"]) / ".git") in commands.records[ordinary["operation_id"]]["denied_paths"]
  with pytest.raises(Conflict, match="ORDINARY_OPERATION_CONFLICT"):
    commands.prepare(principal, {**args, "role_id": "main", "tool_name": "bash", "input": {"command": "agentcfg:build"}})
  commands.command(lease, {"operation_id": ticket["operation_id"]})


def test_status_conflicts_with_writer_and_keeps_lease_until_physical_termination(tmp_path):
  commands, host, args, principal = setup(tmp_path)
  ticket = prepare_status(commands, principal, args)
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    prepare_status(commands, principal, {**args, "operation_id": "other"})
  with pytest.raises(Conflict, match="TERMINATION_UNKNOWN"):
    commands.finish(principal, {"operation_id": ticket["operation_id"]})
  host.manifest()["permission_policy"]["rules"] = []
  with pytest.raises(Conflict, match="ORDINARY_COMMAND_STALE"):
    commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})


@pytest.mark.parametrize("change", ["unselected", "worker", "deny-command", "deny-file", "denied-root", "write", "args", "interactive"])
def test_invalid_or_incomplete_scope_rejects_before_process_allocation(tmp_path, change):
  commands, host, args, principal = setup(tmp_path)
  manifest = host.manifest(); options = manifest["options"]
  if change == "unselected": manifest["resource_ids"] = {}
  if change == "worker": principal = Principal("worker")
  if change == "deny-command": manifest["permission_policy"]["rules"][-1]["effect"] = "deny"
  if change == "deny-file": manifest["permission_policy"]["rules"].append({"kind": "file", "effect": "deny", "root_ref": "project", "relative_path": "private"})
  if change == "denied-root":
    private = Path(args["cwd"]) / "private"; private.mkdir()
    options["paths"]["roots"]["private"] = {"path": str(private), "purpose": "read"}
    options["permissions"] = {"denied_roots": ["private"]}
  if change == "write": options["external_tools"]["build"]["write_roots"] = ["project"]
  if change == "args": options["external_tools"]["build"]["args"] = ["arbitrary"]
  if change == "interactive": options["external_tools"]["build"]["interactive"] = True
  before = len(host.store.records())
  with pytest.raises((ConfigError, Conflict)): prepare_status(commands, principal, args)
  assert len(host.store.records()) == before


def test_non_repository_is_distinct_from_broken_git_marker(tmp_path, monkeypatch):
  commands, host, args, principal = setup(tmp_path)
  original_lstat = Path.lstat
  def isolated_lstat(path, *args, **kwargs):
    if path.name == ".git" and not path.is_relative_to(tmp_path): raise FileNotFoundError()
    return original_lstat(path, *args, **kwargs)
  monkeypatch.setattr(Path, "lstat", isolated_lstat)
  empty = tmp_path / "empty"; empty.mkdir()
  host.manifest()["options"]["paths"]["roots"]["project"]["path"] = str(empty)
  args["cwd"] = str(empty)
  assert prepare_status(commands, principal, args) == {"status": "not-repository"}
  (empty / ".git").write_text("broken")
  with pytest.raises(Conflict): prepare_status(commands, principal, args)


def test_linked_worktree_mounts_common_metadata_readonly_and_rejects_changed_git_anchor(tmp_path):
  commands, host, args, principal = setup(tmp_path)
  project = Path(args["cwd"])
  # 将夹具改为独立 worktree 的标准指针；不执行 Git。
  gitdir = tmp_path / "metadata"; (project / ".git").rename(gitdir)
  common = tmp_path / "common"; common.mkdir()
  (gitdir / "commondir").write_text(str(common))
  (gitdir / "gitdir").write_text(str(project / ".git"))
  (project / ".git").write_text("gitdir: " + str(gitdir))
  ticket = prepare_status(commands, principal, args)
  record = commands.records[ticket["operation_id"]]
  assert str(common) in record["check"]["read_roots"]
  assert str(gitdir) in record["check"]["read_roots"]
  replacement = tmp_path / "replacement"; replacement.mkdir(); (replacement / "HEAD").write_text("ref: refs/heads/other")
  (replacement / "gitdir").write_text(str(project / ".git")); (replacement / "commondir").write_text(str(common))
  (project / ".git").write_text("gitdir: " + str(replacement))
  with pytest.raises(Conflict, match="ROOT_IDENTITY"):
    commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})


def test_metadata_binding_does_not_overwrite_a_similarly_named_project(tmp_path):
  commands, host, args, principal = setup(tmp_path)
  options = host.manifest()["options"]
  options["paths"]["roots"]["git-metadata-0"] = options["paths"]["roots"].pop("project")
  options["external_tools"]["build"].update(project_root="git-metadata-0", read_roots=["git-metadata-0"])
  ticket = prepare_status(commands, principal, args)
  record = commands.records[ticket["operation_id"]]
  assert record["roots"]["git-metadata-0"]["path"] == args["cwd"]
  assert args["cwd"] in record["check"]["read_roots"]
