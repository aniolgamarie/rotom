"""不同 Git 身份仍可能覆盖同一物理目录；租约按覆盖范围互斥。"""

from copy import deepcopy

import pytest

from agentcfg.storage import Conflict
from agentcfg.workspace_leases import WorkspaceLeases
from test_pi_workspace_leases import allocation, worktree


def nested_worktree(tmp_path, kind):
  parent = worktree(tmp_path, "parent")
  if kind == "nested-git":
    child = worktree(parent, "nested")
  else:
    child = parent / "nested"
    child.mkdir()
    git_dir = parent / ".git/worktrees/nested"
    git_dir.mkdir(parents=True)
    (child / ".git").write_text("gitdir: " + str(git_dir) + "\n")
    (git_dir / "HEAD").write_text("ref: refs/heads/nested\n")
    (git_dir / "commondir").write_text("../..\n")
    (git_dir / "gitdir").write_text(str(child / ".git") + "\n")
  return parent, child


@pytest.mark.parametrize("kind", ["nested-git", "linked-worktree"])
@pytest.mark.parametrize("child_first", [False, True])
def test_physical_parent_and_child_cannot_admit_different_writers(tmp_path, kind, child_first):
  parent, child = nested_worktree(tmp_path, kind)
  first, second = WorkspaceLeases("fixture-boot"), WorkspaceLeases("fixture-boot")
  paths = [child, parent] if child_first else [parent, child]
  held, candidate = first.identify(paths[0]), second.identify(paths[1])
  assert held["git_dir_identity"] != candidate["git_dir_identity"]
  saved = first.reserve(held, allocation(held))
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    second.reserve(candidate, allocation(candidate, "two"))
  assert first.read(held) == saved


@pytest.mark.parametrize("kind", ["nested-git", "linked-worktree"])
def test_one_execution_may_cover_its_own_overlapping_roots(tmp_path, kind):
  parent, child = nested_worktree(tmp_path, kind)
  manager = WorkspaceLeases("fixture-boot")
  outer, inner = manager.identify(parent), manager.identify(child)
  lease = allocation(outer)
  lease["planned_workspaces"] = [outer, inner]
  saved = [manager.reserve(planned, deepcopy(lease)) for planned in (outer, inner)]
  assert {record["execution_lease_id"] for record in saved} == {lease["lease_id"]}
  assert len({record["workspace_lease_id"] for record in saved}) == 2
