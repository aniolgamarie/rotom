"""导出受限私有副本，不执行原生工具或读取实际 HOME。"""
from pathlib import Path
import pytest
from agentcfg.pi_readseek_snapshot import export_snapshot, verify_snapshot_source
from agentcfg.storage import Conflict
from test_pi_guarded_files import fixture


def test_snapshot_contains_only_authorized_bytes_and_reports_incomplete_scope(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  outside = tmp_path / "outside"; outside.write_text("synthetic private sentinel")
  (root / "src/link").symlink_to(outside)
  # 扫描只选已授权 src 子树；符号链接不跟随。
  snapshot = export_snapshot(files, "read", root / "src", tmp_path / "snapshot")
  assert [row["path"] for row in snapshot["entries"]] == ["a.txt"]
  assert snapshot["scope_complete"] is False and snapshot["skipped"] == 1
  assert (tmp_path / "snapshot/a.txt").read_bytes() == b"original"
  assert not (tmp_path / "snapshot/link").exists()
  verify_snapshot_source(files, "read", snapshot)
  (root / "src/a.txt").write_text("external changed")
  with pytest.raises(Conflict, match="SOURCE_CHANGED"): verify_snapshot_source(files, "read", snapshot)


def test_explicit_git_selection_is_not_expanded_by_filesystem_fallback(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  (root / "src/unselected.txt").write_text("must not be exported")
  snapshot = export_snapshot(files, "read", root, tmp_path / "snapshot", selected_paths=["src/a.txt"])
  assert snapshot["scope_complete"] is True
  assert [row["path"] for row in snapshot["entries"]] == ["src/a.txt"]
  assert not (tmp_path / "snapshot/src/unselected.txt").exists()
  assert not (tmp_path / "snapshot/.env").exists()


def test_denials_limits_and_nonempty_snapshot_are_never_silently_accepted(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  restricted = export_snapshot(files, "read", root, tmp_path / "restricted", selected_paths=["src/a.txt", ".env"])
  assert restricted["scope_complete"] is False and restricted["skipped"] == 1
  with pytest.raises(Conflict, match="NOT_EMPTY"):
    export_snapshot(files, "read", root, tmp_path / "restricted", selected_paths=["src/a.txt"])
  with pytest.raises(Conflict, match="LIMIT"):
    export_snapshot(files, "read", root, tmp_path / "too-small", selected_paths=["src/a.txt"], max_bytes=1)
  with pytest.raises(Conflict, match="OVERLAP"):
    export_snapshot(files, "read", root, root / "snapshot", selected_paths=["src/a.txt"])


def test_revocation_stops_before_exporting_any_file(tmp_path):
  root, files, state, _ = fixture(tmp_path); state["valid"] = False
  with pytest.raises(Conflict, match="GRANT_STALE"):
    export_snapshot(files, "read", root, tmp_path / "snapshot", selected_paths=["src/a.txt"])
  assert not (tmp_path / "snapshot").exists()


def test_filesystem_fallback_skips_native_exclusions_but_explicit_git_selection_keeps_tracked_files(tmp_path):
  root, files, _, _ = fixture(tmp_path)
  for directory in ("node_modules", "target"):
    (root / "src" / directory).mkdir()
    (root / "src" / directory / "tracked.txt").write_text("tracked content")
  ordinary = export_snapshot(files, "read", root / "src", tmp_path / "fallback")
  assert [row["path"] for row in ordinary["entries"]] == ["a.txt"]
  explicit = export_snapshot(files, "read", root / "src", tmp_path / "git-selection",
    selected_paths=["target/tracked.txt", "node_modules/tracked.txt"])
  assert [row["path"] for row in explicit["entries"]] == ["node_modules/tracked.txt", "target/tracked.txt"]
