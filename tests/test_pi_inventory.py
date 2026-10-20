"""运行包inventory保持内容和路径身份校验，默认无宿主。"""
import hashlib
import os
from pathlib import Path

import pytest

from agentcfg import pi_runtime_packages as runtime
from agentcfg.storage import Conflict, Tree


def fixture(tmp_path):
  holder = tmp_path / "holder"
  holder.mkdir(mode=0o700)
  root = holder / "runtime"
  root.mkdir(mode=0o700)
  (root / "sub").mkdir(mode=0o700)
  (root / "sub/data").write_bytes(b"original")
  (root / "sub/data").chmod(0o600)
  return root


def test_inventory_opens_one_pinned_tree_and_hashes_every_file(tmp_path, monkeypatch):
  root = fixture(tmp_path)
  (root / "link").symlink_to("sub/data")
  opened = []
  class Counted(Tree):
    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      opened.append(self)
  monkeypatch.setattr(runtime, "Tree", Counted)
  result = runtime.inventory(root)
  assert result["sub/data"]["sha256"] == hashlib.sha256(b"original").hexdigest()
  assert result["link"] == {"kind": "link", "target": "sub/data"}
  assert len(opened) <= 2
  assert all(tree.fd is None for tree in opened)


@pytest.mark.parametrize("change", ["same_length", "replace", "directory", "root", "ancestor", "hardlink"])
def test_inventory_rejects_mutation_during_fd_read(tmp_path, monkeypatch, change):
  root = fixture(tmp_path)
  real_read = os.read
  changed = []
  def read(fd, count):
    data = real_read(fd, count)
    if data == b"original" and not changed:
      changed.append(True)
      target = root / "sub/data"
      if change == "same_length":
        before = target.stat()
        target.write_bytes(b"modified")
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
      elif change == "replace":
        target.rename(root / "sub/old")
        target.write_bytes(b"original")
      elif change == "directory":
        (root / "sub").rename(root / "moved")
        (root / "sub").mkdir(mode=0o700)
      elif change == "root":
        root.rename(tmp_path / "old-root")
        root.mkdir(mode=0o700)
      elif change == "ancestor":
        root.parent.rename(root.parent.with_name(root.parent.name + "-moved"))
      else:
        os.link(target, root / "duplicate")
    return data
  monkeypatch.setattr(runtime.os, "read", read)
  before = len(os.listdir("/proc/self/fd"))
  with pytest.raises(Conflict):
    runtime.inventory(root)
  assert changed
  assert len(os.listdir("/proc/self/fd")) == before


@pytest.mark.parametrize("target", ["../outside", "/etc/passwd", "loop"])
def test_inventory_rejects_escaping_or_cyclic_links(tmp_path, target):
  root = fixture(tmp_path)
  (root / "loop").symlink_to(target)
  with pytest.raises(Conflict):
    runtime.inventory(root)


def test_inventory_closes_all_descriptors_when_file_open_fails(tmp_path, monkeypatch):
  root = fixture(tmp_path)
  original = os.open
  def fail(path, flags, *args, **kwargs):
    if path == "data":
      raise PermissionError("synthetic read failure")
    return original(path, flags, *args, **kwargs)
  monkeypatch.setattr(runtime.os, "open", fail)
  before = len(os.listdir("/proc/self/fd"))
  with pytest.raises(Conflict):
    runtime.inventory(root)
  assert len(os.listdir("/proc/self/fd")) == before


def test_inventory_preserves_internal_chained_and_absolute_links(tmp_path):
  root = fixture(tmp_path)
  (root / "sub/relative").symlink_to("../alias")
  (root / "alias").symlink_to("sub/data")
  (root / "absolute").symlink_to(root / "sub/data")
  result = runtime.inventory(root)
  assert result["sub/relative"]["target"] == "../alias"
  assert result["absolute"]["target"] == str(root / "sub/data")


def test_inventory_rejects_link_replacement_during_resolution(tmp_path, monkeypatch):
  root = fixture(tmp_path)
  link = root / "alias"
  link.symlink_to("sub/data")
  original = os.readlink
  def replace(name, *args, **kwargs):
    target = original(name, *args, **kwargs)
    if name == "alias":
      link.unlink()
      link.symlink_to("sub/data")
    return target
  monkeypatch.setattr(runtime.os, "readlink", replace)
  before = len(os.listdir("/proc/self/fd"))
  with pytest.raises(Conflict):
    runtime.inventory(root)
  assert len(os.listdir("/proc/self/fd")) == before
