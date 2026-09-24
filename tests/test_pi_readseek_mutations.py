"""多文件结果只作用于真实临时文件；不启动 ReadSeek 或其他宿主。"""
import json
from pathlib import Path
import pytest

from agentcfg.pi_guarded_files import GuardedFiles
from agentcfg.pi_readseek_mutations import commit_changes, inspect_changes
from agentcfg.storage import Conflict
from test_pi_guarded_files import fixture


def test_all_targets_are_checked_before_first_business_write(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  changes = [{"path": "src/a.txt", "before": b"original", "after": b"changed"},
    {"path": "src2/a.txt", "before": b"outside rule", "after": b"forbidden"}]
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    commit_changes(files, "edit", changes, tmp_path / "journal", "operation")
  assert (root / "src/a.txt").read_bytes() == b"original"
  assert not list((tmp_path / "journal").glob("*/plan.json"))


def test_multi_file_commit_is_replayable_only_for_matching_current_results(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  changes = [{"path": "src/a.txt", "before": b"original", "after": b"renamed"},
    {"path": "src/new.txt", "before": None, "after": b"new"}]
  result = commit_changes(files, "edit", changes, tmp_path / "journal", "operation")
  assert result["changed_files"] == 2 and result["replayed"] is False
  assert commit_changes(files, "edit", changes, tmp_path / "journal", "operation")["replayed"] is True
  report = inspect_changes(files, "read", tmp_path / "journal", result["journal_id"])
  assert [row["state"] for row in report["files"]] == ["after", "after"]
  assert "renamed" not in json.dumps(report)
  (root / "src/a.txt").write_text("external modification")
  with pytest.raises(Conflict, match="RESULT_STALE"):
    commit_changes(files, "edit", changes, tmp_path / "journal", "operation")


def test_revoked_mid_commit_keeps_partial_journal_and_never_reapplies_prefix(tmp_path, monkeypatch):
  root, files, state, _ = fixture(tmp_path)
  (root / "src/b.txt").write_text("second")
  changes = [{"path": "src/a.txt", "before": b"original", "after": b"first changed"},
    {"path": "src/b.txt", "before": b"second", "after": b"second changed"}]
  write = GuardedFiles.write
  def revoke_after_first(self, *args, **kwargs):
    result = write(self, *args, **kwargs); state["valid"] = False; return result
  monkeypatch.setattr(GuardedFiles, "write", revoke_after_first)
  with pytest.raises(Conflict, match="MUTATION_INCOMPLETE"):
    commit_changes(files, "edit", changes, tmp_path / "journal", "operation")
  assert (root / "src/a.txt").read_text() == "first changed"
  assert (root / "src/b.txt").read_text() == "second"
  state["valid"] = True
  with pytest.raises(Conflict, match="MUTATION_INCOMPLETE"):
    commit_changes(files, "edit", changes, tmp_path / "journal", "operation")
  journal = next((tmp_path / "journal").iterdir())
  state["writer"] = False
  assert [row["state"] for row in inspect_changes(files, "read", tmp_path / "journal", journal.name)["files"]] == ["after", "before"]


def test_creation_race_cannot_overwrite_a_file_that_appeared_after_preflight(tmp_path, monkeypatch):
  root, files, _, _ = fixture(tmp_path)
  write = GuardedFiles.write
  def create_before_write(self, *args, **kwargs):
    (root / "src/new.txt").write_text("outside writer")
    return write(self, *args, **kwargs)
  monkeypatch.setattr(GuardedFiles, "write", create_before_write)
  with pytest.raises(Conflict, match="MUTATION_INCOMPLETE"):
    commit_changes(files, "write", [{"path": "src/new.txt", "before": None, "after": b"ours"}], tmp_path / "journal", "operation")
  assert (root / "src/new.txt").read_text() == "outside writer"


def test_stale_baseline_rejects_whole_plan_before_any_write(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  (root / "src/b.txt").write_text("external newer version")
  with pytest.raises(Conflict, match="FILE_CHANGED"):
    commit_changes(files, "edit", [{"path": "src/a.txt", "before": b"original", "after": b"first"},
      {"path": "src/b.txt", "before": b"old version", "after": b"second"}], tmp_path / "journal", "operation")
  assert (root / "src/a.txt").read_text() == "original"


def test_noop_write_still_checks_the_original_baseline(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  (root / "src/a.txt").write_text("external newer version")
  with pytest.raises(Conflict, match="FILE_CHANGED"):
    commit_changes(files, "edit", [{"path": "src/a.txt", "before": b"original", "after": b"original"}], tmp_path / "journal", "noop")
  assert (root / "src/a.txt").read_text() == "external newer version"
