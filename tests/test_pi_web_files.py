"""本地媒体输入走已有权限；真实 FFmpeg 和模型不在默认测试中运行。"""
from pathlib import Path
import pytest
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict
from test_pi_operations import setup


def fixture(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["plugins"] = ["pi-web"]
  host.manifest()["options"]["web"] = {"media": {"max_file_bytes": 32 * 1024 * 1024}}
  return operations, host, cwd, principal


def test_large_media_is_streamed_to_a_readonly_private_snapshot_with_existing_read_permission(tmp_path):
  operations, host, cwd, principal = fixture(tmp_path)
  source = Path(cwd) / "video.mp4"; source.write_bytes(b"v" * (17 * 1024 * 1024))
  args = {"operation_id": "media", "cwd": cwd, "path": "video.mp4"}
  result = operations.handle(principal, "ordinary_web_file_prepare", args)
  assert result["size"] == source.stat().st_size
  copied = Path(result["directory"]) / "input"
  assert copied.read_bytes() == source.read_bytes() and copied.stat().st_mode & 0o777 == 0o400
  assert operations.handle(principal, "ordinary_web_file_prepare", args) == result
  assert operations.inputs == {}
  operations.handle(principal, "ordinary_web_file_finish", {"file_id": result["file_id"]})
  assert not copied.exists() and source.exists()


@pytest.mark.parametrize("kind", ["outside", "denied", "symlink", "worker", "size"])
def test_local_media_cannot_bypass_common_file_scope(tmp_path, kind):
  operations, host, cwd, principal = fixture(tmp_path)
  path = Path(cwd) / "video.mp4"; path.write_bytes(b"fixture video")
  if kind == "outside": path = tmp_path / "outside.mp4"; path.write_bytes(b"outside")
  if kind == "denied": host.manifest()["permission_policy"]["rules"][0]["effect"] = "deny"
  if kind == "symlink": path.unlink(); path.symlink_to(Path(cwd) / "code.txt")
  if kind == "worker": principal = Principal("worker")
  if kind == "size": host.manifest()["options"]["web"]["media"]["max_file_bytes"] = 1
  with pytest.raises(Conflict): operations.handle(principal, "ordinary_web_file_prepare", {"operation_id": "media", "cwd": cwd, "path": str(path)})
  assert operations.web_files.records == {}


def test_expired_media_is_reclaimed_after_restart_but_unknown_directories_remain(tmp_path):
  from datetime import datetime, timedelta, timezone
  from agentcfg.pi_web_files import WebFiles
  operations, host, cwd, principal = fixture(tmp_path)
  now = datetime.now(timezone.utc)
  operations.web_files.now = lambda: now
  (Path(cwd) / "movie.mp4").write_bytes(b"synthetic")
  args = {"operation_id": "media", "cwd": cwd, "path": "movie.mp4"}
  result = operations.handle(principal, "ordinary_web_file_prepare", args)
  root = operations.web_files.root
  unknown = root / ("f" * 32); unknown.mkdir(); (unknown / "input").write_bytes(b"keep")
  now += timedelta(seconds=301)
  recovered = WebFiles(operations, now=lambda: now)
  recovered.tick()
  assert Path(result["directory"]).exists()
  recovered.tick(scan=True)
  assert not Path(result["directory"]).exists() and (unknown / "input").read_bytes() == b"keep"
