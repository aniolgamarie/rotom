"""已有私人路径祖先同步；仅临时目录、真实 fsync 和故障注入。"""

import os
from pathlib import Path

import pytest

from agentcfg.storage import Conflict, sync_directory_ancestors


def test_syncs_every_existing_ancestor_bottom_up_without_changing_files(tmp_path, monkeypatch):
  root = tmp_path / "parent" / "child"
  root.mkdir(parents=True, mode=0o700)
  sentinel = root / "synthetic-sentinel"
  sentinel.write_bytes(b"unchanged")
  chain = [root, *root.parents]
  expected = [(path.stat().st_dev, path.stat().st_ino) for path in chain]
  seen = []; fsync = os.fsync
  def sync(fd):
    info = os.fstat(fd); seen.append((info.st_dev, info.st_ino))
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  sync_directory_ancestors(root)
  assert seen == expected and sentinel.read_bytes() == b"unchanged"


@pytest.mark.parametrize("case", ["relative", "escape", "double-root", "missing", "symlink", "file"])
def test_invalid_or_missing_path_is_never_created_or_followed(tmp_path, monkeypatch, case):
  destination = tmp_path / "destination"; destination.mkdir(mode=0o700)
  candidate = tmp_path / "candidate"
  if case == "relative": candidate = Path("synthetic-relative")
  elif case == "escape": candidate = tmp_path / ".." / "escape"
  elif case == "double-root": candidate = Path("//synthetic-invalid")
  elif case == "symlink": candidate.symlink_to(destination, target_is_directory=True)
  elif case == "file": candidate.write_bytes(b"synthetic-file")
  calls = []
  monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))
  with pytest.raises(Conflict): sync_directory_ancestors(candidate)
  assert calls == [] and list(destination.iterdir()) == []
  if case == "missing": assert not candidate.exists()


@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_sync_failure_stops_traversal_without_leaking_handles(tmp_path, monkeypatch, kind):
  root = tmp_path / "root"; root.mkdir(mode=0o700)
  error = kind("synthetic-private-canary"); opened = []
  def failed(fd):
    opened.append(fd)
    raise error
  monkeypatch.setattr(os, "fsync", failed)
  with pytest.raises(Conflict if kind is OSError else kind) as caught:
    sync_directory_ancestors(root)
  if kind is OSError: assert "synthetic-private-canary" not in str(caught.value)
  else: assert caught.value is error
  assert len(opened) == 1
  with pytest.raises(OSError): os.fstat(opened[0])
  assert root.is_dir() and list(root.iterdir()) == []
