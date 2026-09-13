"""真实文件上的 OpenSpec 生成产物接管；CLI 本身由假进程隔离。"""

import pytest

from agentcfg.project import apply_generated
from agentcfg.project import validate_project_root
from agentcfg.storage import Conflict


def generated(tmp_path):
  stage = tmp_path / "stage"
  stage.mkdir(mode=0o700)
  skill = stage / ".agents/skills/openspec-propose/SKILL.md"
  skill.parent.mkdir(parents=True)
  skill.write_text("---\nname: openspec-propose\ndescription: fixture\n---\n")
  (stage / "openspec").mkdir()
  (stage / "openspec/config.yaml").write_text("schema: spec-driven\n")
  return stage


def test_project_target_only_idempotent_and_conflicts(tmp_path):
  stage = generated(tmp_path)
  target = tmp_path / "项目 空格"
  target.mkdir()
  (target / "business.txt").write_text("keep")
  assert apply_generated(target, stage)["changed"] == 2
  skill = target / ".agents/skills/openspec-propose/SKILL.md"
  before = skill.stat()
  assert apply_generated(target, stage)["changed"] == 0
  assert skill.stat() == before
  skill.write_text("user modified")
  with pytest.raises(Conflict):
    apply_generated(target, stage)
  assert (target / "business.txt").read_text() == "keep"
  assert skill.read_text() == "user modified"


def test_project_rejects_symlink_target_and_unexpected_output(tmp_path):
  stage = generated(tmp_path)
  target = tmp_path / "target"
  target.mkdir()
  (stage / "outside.txt").write_text("unexpected")
  with pytest.raises(Conflict):
    apply_generated(target, stage)
  assert not list(target.iterdir())


def test_nested_git_project_is_rejected_before_generating_files(tmp_path):
  parent = tmp_path / "repo"
  parent.mkdir()
  (parent / ".git").mkdir()
  child = parent / "component"
  child.mkdir()
  validate_project_root(parent)
  with pytest.raises(Conflict):
    validate_project_root(child)
  assert not list(child.iterdir())
  (child / ".git").write_text("gitdir: /synthetic/worktree\n")
  validate_project_root(child)
