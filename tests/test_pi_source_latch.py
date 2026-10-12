"""仅当前 pytest 进程的普通文件 latch，不证明持续 SourceHold。"""

import errno
import fcntl
import os
from pathlib import Path
from types import SimpleNamespace
import traceback

import pytest

from agentcfg.pi_source_latch import source_latch
from agentcfg.storage import Conflict


@pytest.fixture
def workspace(tmp_path):
  instance = tmp_path / "instance"
  instance.mkdir(mode=0o700)
  for name in ("lifecycle.lock", "state.json"):
    (instance / name).write_bytes(b"original sentinel")
  return SimpleNamespace(instance=instance)


def test_shared_exclusive_yield_and_anchor_preservation(workspace):
  with source_latch(workspace, shared=True, create=True) as value:
    assert value is None
    before = (workspace.instance / "source.lock").stat()
    with source_latch(workspace, shared=True):
      with pytest.raises(Conflict):
        with source_latch(workspace):
          pytest.fail("exclusive acquired")
  with source_latch(workspace):
    for shared in (False, True):
      with pytest.raises(Conflict):
        with source_latch(workspace, shared=shared):
          pytest.fail("second acquired")
  with source_latch(workspace, create=True):
    after = (workspace.instance / "source.lock").stat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    assert after.st_size == 0 and after.st_nlink == 1
    assert after.st_mode & 0o777 == 0o600
  for name in ("lifecycle.lock", "state.json"):
    assert (workspace.instance / name).read_bytes() == b"original sentinel"


@pytest.mark.parametrize("shared", [False, True])
def test_directory_metadata_changes_preserve_same_root(workspace, shared):
  """SH 不是写授权；这里只核同一目录对象不受普通元数据变化影响。"""
  with source_latch(workspace, shared=shared, create=True):
    before = workspace.instance.stat()
    (workspace.instance / ".agentcfg-instance.json").write_bytes(b"synthetic metadata")
    (workspace.instance / "metadata-directory").mkdir(mode=0o700)
    after = workspace.instance.stat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    assert after.st_nlink != before.st_nlink
  with source_latch(workspace, shared=shared):
    (workspace.instance / ".agentcfg-instance.json").unlink()
    (workspace.instance / "metadata-directory").rmdir()
  with source_latch(workspace):
    pass


@pytest.mark.parametrize("field,value", [("shared", 1), ("create", None), ("shared", "yes"), ("create", [])])
def test_flags_are_exact_bool(workspace, field, value):
  with pytest.raises(Conflict):
    with source_latch(workspace, **{field: value}):
      pytest.fail("bad flag accepted")
  assert not (workspace.instance / "source.lock").exists()


@pytest.mark.parametrize("kind", ["relative", "string", "missing", "instance-symlink", "instance-mode"])
def test_invalid_instance_does_not_create(tmp_path, workspace, kind):
  if kind == "relative":
    workspace.instance = Path("relative")
  elif kind == "string":
    workspace.instance = str(workspace.instance)
  elif kind == "missing":
    workspace.instance = tmp_path / "missing"
  elif kind == "instance-symlink":
    link = tmp_path / "instance-link"
    link.symlink_to(workspace.instance, target_is_directory=True)
    workspace.instance = link
  else:
    workspace.instance.chmod(0o755)
  with pytest.raises(Conflict):
    with source_latch(workspace, create=True):
      pytest.fail("bad instance accepted")
  assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("kind", ["missing", "symlink", "directory", "fifo", "hardlink", "mode", "content", "owner"])
def test_invalid_anchor(workspace, kind, monkeypatch):
  anchor = workspace.instance / "source.lock"
  if kind == "symlink":
    anchor.symlink_to("state.json")
  elif kind == "directory":
    anchor.mkdir(mode=0o700)
  elif kind == "fifo":
    os.mkfifo(anchor, 0o600)
  elif kind != "missing":
    anchor.write_bytes(b"secret body" if kind == "content" else b"")
    anchor.chmod(0o644 if kind == "mode" else 0o600)
    if kind == "hardlink":
      os.link(anchor, workspace.instance / "other")
    if kind == "owner":
      import agentcfg.pi_source_latch as module
      real_stat = module.os.stat
      def foreign_stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == "source.lock":
          values = list(info)
          values[4] += 1
          return os.stat_result(values)
        return info
      monkeypatch.setattr(module.os, "stat", foreign_stat)
  with pytest.raises(Conflict) as caught:
    with source_latch(workspace):
      pytest.fail("bad anchor accepted")
  assert str(workspace.instance) not in str(caught.value)
  assert "secret body" not in str(caught.value)


def watch_latch(monkeypatch):
  import agentcfg.pi_source_latch as module
  real_flock, real_close = module.fcntl.flock, module.os.close
  state = {"fd": None, "closes": 0, "operations": []}
  def flock(fd, operation):
    state["fd"] = fd
    state["operations"].append(operation)
    assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    assert flags & os.O_NONBLOCK and flags & os.O_ACCMODE == os.O_RDWR
    return real_flock(fd, operation)
  def close(fd):
    if fd == state["fd"]:
      state["closes"] += 1
    return real_close(fd)
  monkeypatch.setattr(module.fcntl, "flock", flock)
  monkeypatch.setattr(module.os, "close", close)
  return state, real_close


def test_body_failure_close_once_without_unlock(workspace, monkeypatch):
  state, _ = watch_latch(monkeypatch)
  with pytest.raises(ValueError, match="own body"):
    with source_latch(workspace, create=True):
      raise ValueError("own body")
  assert state["closes"] == 1
  assert state["operations"] == [fcntl.LOCK_EX | fcntl.LOCK_NB]
  with source_latch(workspace):
    pass


@pytest.mark.parametrize("error", [errno.EAGAIN, errno.EACCES, errno.EIO])
def test_acquisition_error_is_fixed_and_closes(workspace, monkeypatch, error):
  import agentcfg.pi_source_latch as module
  state, _ = watch_latch(monkeypatch)
  def fail(fd, operation):
    state["fd"] = fd
    raise OSError(error, "foreign detail /private")
  monkeypatch.setattr(module.fcntl, "flock", fail)
  with pytest.raises(Conflict) as caught:
    with source_latch(workspace, create=True):
      pytest.fail("error ignored")
  assert state["closes"] == 1
  assert "foreign" not in str(caught.value)


@pytest.mark.parametrize("change", ["replace", "unlink", "content", "mode", "hardlink", "root", "root-mode"])
def test_exit_rechecks_original_named_anchor_and_root(workspace, change):
  with pytest.raises(Conflict):
    with source_latch(workspace, create=True):
      anchor = workspace.instance / "source.lock"
      if change == "replace":
        replacement = workspace.instance / "replacement"
        replacement.write_bytes(b"")
        replacement.chmod(0o600)
        replacement.replace(anchor)
      elif change == "unlink":
        anchor.unlink()
      elif change == "content":
        anchor.write_bytes(b"changed")
      elif change == "mode":
        anchor.chmod(0o644)
      elif change == "hardlink":
        os.link(anchor, workspace.instance / "other")
      elif change == "root-mode":
        workspace.instance.chmod(0o755)
      else:
        workspace.instance.rename(workspace.instance.with_name("old-instance"))
        workspace.instance.mkdir(mode=0o700)


@pytest.mark.parametrize("target", ["root", "anchor"])
def test_gid_change_is_rejected(workspace, monkeypatch, target):
  import agentcfg.pi_source_latch as module
  real_fstat = module.os.fstat
  with pytest.raises(Conflict):
    with source_latch(workspace, create=True):
      inode = (workspace.instance if target == "root" else workspace.instance / "source.lock").stat().st_ino
      def changed(fd):
        info = real_fstat(fd)
        if info.st_ino == inode:
          values = list(info)
          values[5] += 1
          return os.stat_result(values)
        return info
      monkeypatch.setattr(module.os, "fstat", changed)


def test_close_failure_is_fixed_and_not_retried(workspace, monkeypatch):
  import agentcfg.pi_source_latch as module
  state, real_close = watch_latch(monkeypatch)
  def close(fd):
    if fd == state["fd"]:
      state["closes"] += 1
      real_close(fd)
      raise OSError(errno.EIO, "foreign close detail")
    return real_close(fd)
  monkeypatch.setattr(module.os, "close", close)
  with pytest.raises(Conflict) as caught:
    with source_latch(workspace, create=True):
      pass
  assert state["closes"] == 1
  assert "foreign" not in str(caught.value)


@pytest.mark.parametrize("target", ["named", "root"])
def test_combined_error_body_and_endpoint_drift(workspace, monkeypatch, target):
  state, _ = watch_latch(monkeypatch)
  sentinel = "synthetic body secret /private-path"
  with pytest.raises(Conflict) as caught:
    with source_latch(workspace, create=True):
      if target == "named":
        (workspace.instance / "source.lock").unlink()
      else:
        workspace.instance.rename(workspace.instance.with_name("old-instance"))
        workspace.instance.mkdir(mode=0o700)
      raise ValueError(sentinel)
  assert state["closes"] == 1
  assert state["operations"] == [fcntl.LOCK_EX | fcntl.LOCK_NB]
  assert sentinel not in "".join(traceback.format_exception(caught.value))


def test_combined_error_body_and_owned_close_failure(workspace, monkeypatch):
  import agentcfg.pi_source_latch as module
  state, real_close = watch_latch(monkeypatch)
  def close(fd):
    if fd == state["fd"]:
      state["closes"] += 1
      real_close(fd)
      raise OSError(errno.EIO, "synthetic close secret")
    return real_close(fd)
  monkeypatch.setattr(module.os, "close", close)
  sentinel = "synthetic body secret /private-path"
  with pytest.raises(Conflict) as caught:
    with source_latch(workspace, create=True):
      raise ValueError(sentinel)
  assert state["closes"] == 1
  assert state["operations"] == [fcntl.LOCK_EX | fcntl.LOCK_NB]
  rendered = "".join(traceback.format_exception(caught.value))
  assert sentinel not in rendered
  assert "synthetic close secret" not in rendered
