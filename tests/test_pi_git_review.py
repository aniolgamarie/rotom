"""审查查询只在临时 Git 元数据和假监督者上验证，不执行 Git。"""
import pytest
from agentcfg.pi_git_review import query, prepare_review
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_commands import fixture


@pytest.mark.parametrize("argv", [
  ["diff", "--find-renames", "-M", "--raw", "-z", "HEAD", "--"],
  ["diff-tree", "--root", "--find-renames", "-M", "--numstat", "--no-commit-id", "-r", "HEAD"],
  ["show", "HEAD^:src/中文 name.ts"],
  ["rev-parse", "--verify", "--quiet", "origin/main"],
  ["ls-files", "--others", "--exclude-standard"],
])
def test_review_queries_preserve_arguments_and_disable_git_helpers(argv):
  result = query(argv)
  assert result[0] == "--no-pager" and "core.fsmonitor=false" in result
  if argv[0] in ("diff", "diff-tree", "show"):
    assert "--no-ext-diff" in result and "--no-textconv" in result
  assert result[-len(argv[1:]):] == argv[1:]


@pytest.mark.parametrize("argv", [["checkout", "main"], ["diff", "--ext-diff"], ["show", "HEAD:../secret"],
  ["show", "HEAD:.git/config"], ["-c", "alias.x=!bad", "x"], ["rev-parse", "--verify", "--quiet", "--option"]])
def test_review_cannot_expand_into_commands_paths_or_unsafe_options(argv):
  from agentcfg.paths import PathError
  with pytest.raises((ConfigError, PathError)):
    query(argv)


def test_review_uses_workspace_reservation_and_replay_binds_actual_query(tmp_path):
  commands, host, args, principal = fixture(tmp_path)
  manifest = host.manifest(); manifest["plugins"] = ["pi-slopchop"]
  manifest["options"]["slopchop"] = {"git_tool_ref": "build"}
  manifest["options"]["external_tools"]["build"]["args"] = []
  request = {"operation_id": "review", "cwd": args["cwd"], "argv": ["ls-files", "--cached"]}
  result = prepare_review(commands, principal, request)
  assert host.store.read(result["lease_id"])["planned_workspaces"]
  assert prepare_review(commands, principal, request) == result
  with pytest.raises(Conflict, match="ORDINARY_OPERATION_CONFLICT"):
    prepare_review(commands, principal, {**request, "argv": ["ls-files", "--deleted"]})
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    prepare_review(commands, principal, {**request, "operation_id": "second"})


def test_submodule_metadata_is_parent_bound_and_marker_changes_block_execution(tmp_path):
  from pathlib import Path
  commands, host, args, principal = fixture(tmp_path)
  root = Path(args["cwd"]); child = root / "nested"; child.mkdir()
  metadata = root / ".git/modules/nested"; metadata.mkdir(parents=True)
  (metadata / "HEAD").write_text("ref: refs/heads/main\n")
  (child / ".git").write_text("gitdir: ../.git/modules/nested\n")
  manifest = host.manifest(); manifest["plugins"] = ["pi-slopchop"]
  manifest["options"]["slopchop"] = {"git_tool_ref": "build"}
  manifest["options"]["external_tools"]["build"]["args"] = []
  ticket = prepare_review(commands, principal, {"operation_id": "submodule", "cwd": str(child), "argv": ["ls-files", "--cached"]})
  lease = host.store.read(ticket["lease_id"])
  assert lease["planned_workspaces"][0]["worktree_path"] == str(root)
  assert str(metadata) in commands.records[ticket["operation_id"]]["check"]["read_roots"]
  (child / ".git").write_text("gitdir: ../.git/modules/other\n")
  with pytest.raises(Conflict, match="ROOT_IDENTITY"):
    commands.command(lease, {"operation_id": ticket["operation_id"]})
