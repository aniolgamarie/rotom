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
  # 幂等保证是第二次apply不重写文件；atime会因内容比对读取而合法变化，不能纳入比较。
  before = (skill.stat().st_mtime_ns, skill.stat().st_ctime_ns, skill.stat().st_size, skill.read_bytes())
  for _ in range(3):
    assert apply_generated(target, stage)["changed"] == 0
    assert (skill.stat().st_mtime_ns, skill.stat().st_ctime_ns, skill.stat().st_size, skill.read_bytes()) == before
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


def test_partial_project_generation_retries_the_same_intent_without_claiming_foreign_files(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  stage = generated(tmp_path); target = tmp_path / "project"; target.mkdir()
  original = Tree.replace; calls = []
  def fail_once(tree, path, data, *args, **kwargs):
    if tree.root == target and data is not None and path != ".agentcfg-openspec-pending.json":
      calls.append(path)
      if len(calls) == 2: raise OSError("fixture disk failure")
    return original(tree, path, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", fail_once)
  with pytest.raises(OSError): apply_generated(target, stage)
  assert (target / ".agentcfg-openspec-pending.json").is_file()
  monkeypatch.setattr(Tree, "replace", original)
  assert apply_generated(target, stage)["changed"] == 2
  assert not (target / ".agentcfg-openspec-pending.json").exists()
  assert apply_generated(target, stage)["changed"] == 0


def test_project_recovery_refuses_user_edits_after_partial_failure(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  stage = generated(tmp_path); target = tmp_path / "project"; target.mkdir()
  original = Tree.replace; count = [0]
  def fail(tree, path, data, *args, **kwargs):
    if tree.root == target and data is not None:
      count[0] += 1
      if count[0] == 2: raise OSError("fixture")
    return original(tree, path, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", fail)
  with pytest.raises(OSError): apply_generated(target, stage)
  monkeypatch.setattr(Tree, "replace", original)
  edited = target / ".agents/skills/openspec-propose/SKILL.md"; edited.write_text("user edit")
  with pytest.raises(Conflict, match="用户修改"): apply_generated(target, stage)
  assert edited.read_text() == "user edit" and (target / ".agentcfg-openspec-pending.json").exists()


def test_pi_project_ownership_uses_protected_git_metadata_and_ignores_forged_public_marker(tmp_path):
  import hashlib
  import json
  stage = generated(tmp_path); target = tmp_path / "project"; target.mkdir()
  metadata = target / ".git/agentcfg-project"
  user_file = target / ".agents/skills/openspec-propose/SKILL.md"; user_file.parent.mkdir(parents=True); user_file.write_text("user content")
  (target / ".agentcfg-openspec.json").write_text(json.dumps({"version": 1, "files": {".agents/skills/openspec-propose/SKILL.md": hashlib.sha256(user_file.read_bytes()).hexdigest()}}))
  with pytest.raises(Conflict): apply_generated(target, stage, metadata_root=metadata)
  assert user_file.read_text() == "user content"
  user_file.unlink()
  assert apply_generated(target, stage, metadata_root=metadata)["changed"] == 2
  assert (metadata / ".agentcfg-openspec.json").is_file()
  assert apply_generated(target, stage, metadata_root=metadata)["changed"] == 0
