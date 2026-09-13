"""DEP-01/DEP-08/CFG-03：私人路径原语，不执行部署事务。"""

import os
from pathlib import Path
import stat
import traceback

import pytest

from agentcfg.paths import (
  PathError, PrivateDirectory, configured_path, relative_path, safe_id,
)


@pytest.mark.parametrize("value", ["", ".", "..", "/absolute", "a/b", "a\\b", "x\x00", "x\n", "x\x7f"])
def test_safe_id_rejects_escape(value):
  with pytest.raises(PathError):
    safe_id(value)


@pytest.mark.parametrize("value", ["dsh-default", "中文 空格", "name.with.dots"])
def test_safe_id_preserves_literal_segment(value):
  assert safe_id(value) == value


@pytest.mark.parametrize("value", ["", ".", "..", "../escape", "a/../escape", "/escape", "a\\b", "x\x00"])
def test_relative_path_rejects_escape(value):
  with pytest.raises(PathError):
    relative_path(value)


def test_relative_path_preserves_nested_names():
  assert relative_path("技能/中文 文件") == Path("技能/中文 文件")


@pytest.mark.parametrize("value", [
  "", "relative", "~", "~another/path", "/a/../b", "~/../b",
  "/$HOME/path", "/${HOME}/path", "/$(touch forbidden)", "/`touch forbidden`", "/bad\x00",
])
def test_configured_path_rejects_nonliteral_or_escape(value):
  with pytest.raises(PathError):
    configured_path(value)


def test_configured_path_expands_home_once_without_resolving_links(isolated_environment):
  home = isolated_environment.home
  (home / "link").symlink_to(isolated_environment.root)
  assert configured_path("~/中文 空格") == home / "中文 空格"
  assert configured_path(str(home / "link/new")) == home / "link/new"


def test_configured_path_requires_absolute_home(monkeypatch):
  monkeypatch.setenv("HOME", "relative-home")
  with pytest.raises(PathError):
    configured_path("~/private")


@pytest.fixture
def private_parent(isolated_environment):
  # pytest 的可信临时根在 macOS 可能已规范化；不能规范化业务输入来绕过检查。
  parent = isolated_environment.root / "private-parent"
  parent.mkdir(mode=0o700)
  return parent


@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077])
def test_create_private_tree_modes_and_literal_bytes(private_parent, mask):
  parent_mode = private_parent.stat().st_mode
  previous = os.umask(mask)
  try:
    with PrivateDirectory.create(private_parent / "中文 根") as root:
      root.create_directory("技能")
      root.create_directory("技能/资源")
      root.create_file("技能/资源/settings.toml", b"synthetic-private\n$()`false`\n")
  finally:
    os.umask(previous)
  target = private_parent / "中文 根"
  for directory in (target, target / "技能", target / "技能/资源"):
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
  file = target / "技能/资源/settings.toml"
  assert stat.S_IMODE(file.stat().st_mode) == 0o600
  assert file.read_bytes() == b"synthetic-private\n$()`false`\n"
  assert private_parent.stat().st_mode == parent_mode


def test_open_owned_checks_but_does_not_modify_existing_root(private_parent, sentinel_factory):
  root = private_parent / "known-owned"
  root.mkdir(mode=0o700)
  before = sentinel_factory(root)
  with PrivateDirectory.open_owned(root):
    pass
  before.assert_unchanged()


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o750, 0o1700])
def test_existing_nonprivate_root_not_chmodded(private_parent, mode, sentinel_factory):
  root = private_parent / "unowned"
  root.mkdir(mode=mode)
  root.chmod(mode)
  before = sentinel_factory(root)
  with pytest.raises(PathError):
    PrivateDirectory.open_owned(root)
  before.assert_unchanged()


def test_existing_root_is_never_adopted_by_create(private_parent, sentinel_factory):
  root = private_parent / "unowned"
  root.mkdir(mode=0o700)
  (root / "sentinel").write_bytes(b"unowned-content")
  before = sentinel_factory(root)
  with pytest.raises(PathError):
    PrivateDirectory.create(root)
  before.assert_unchanged()


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling", "hardlink", "fifo"])
def test_existing_target_is_not_overwritten(private_parent, kind, sentinel_factory):
  outside = private_parent / "outside"
  outside.write_bytes(b"outside-synthetic")
  with PrivateDirectory.create(private_parent / "owned") as root:
    target = private_parent / "owned/target"
    if kind == "file":
      target.write_bytes(b"existing")
    elif kind == "directory":
      target.mkdir()
    elif kind == "symlink":
      target.symlink_to(outside)
    elif kind == "dangling":
      target.symlink_to(private_parent / "missing")
    elif kind == "hardlink":
      os.link(outside, target)
    else:
      os.mkfifo(target)
    target_before = target.lstat()
    before = sentinel_factory(outside)
    for action in (lambda: root.create_file("target", b"new"), lambda: root.create_directory("target")):
      with pytest.raises(PathError):
        action()
      assert target.lstat() == target_before
      before.assert_unchanged()


@pytest.mark.parametrize("operation", ["create", "open_owned"])
@pytest.mark.parametrize("position", ["ancestor", "root"])
def test_absolute_symlinks_are_rejected(private_parent, operation, position, sentinel_factory):
  outside = private_parent / "outside"
  outside.mkdir(mode=0o700)
  (outside / "owned").mkdir(mode=0o700)
  link = private_parent / "link"
  link.symlink_to(outside, target_is_directory=True)
  path = link / "owned" if position == "ancestor" else link
  before = sentinel_factory(outside)
  with pytest.raises(PathError):
    getattr(PrivateDirectory, operation)(path)
  before.assert_unchanged()


@pytest.mark.parametrize("value", ["../outside/new", "/absolute/new", "good/../../new", "good/../new"])
def test_unsafe_relative_paths_rejected_before_mutation(private_parent, value, sentinel_factory):
  with PrivateDirectory.create(private_parent / "owned") as root:
    before = sentinel_factory(private_parent / "owned")
    for action in (lambda: root.create_directory(value), lambda: root.create_file(value, b"new")):
      with pytest.raises(PathError):
        action()
      before.assert_unchanged()


@pytest.mark.parametrize("kind", ["symlink", "nonprivate", "missing"])
def test_intermediate_directory_must_be_existing_private_and_nofollow(private_parent, kind, sentinel_factory):
  outside = private_parent / "outside"
  outside.mkdir(mode=0o700)
  before = sentinel_factory(outside)
  with PrivateDirectory.create(private_parent / "owned") as root:
    middle = private_parent / "owned/middle"
    if kind == "symlink":
      middle.symlink_to(outside, target_is_directory=True)
    elif kind == "nonprivate":
      middle.mkdir(mode=0o755)
      middle.chmod(0o755)
    for action in (lambda: root.create_file("middle/new", b"new"), lambda: root.create_directory("middle/new")):
      with pytest.raises(PathError):
        action()
      before.assert_unchanged()
    assert not (private_parent / "owned/middle/new").exists()


def test_parent_permissions_are_not_taken_over(private_parent, sentinel_factory):
  private_parent.chmod(0o777)
  before = sentinel_factory(private_parent)
  with pytest.raises(PathError):
    PrivateDirectory.create(private_parent / "new")
  before.assert_unchanged()


def test_nonprivate_but_safe_parent_is_not_chmodded(private_parent):
  private_parent.chmod(0o755)
  with PrivateDirectory.create(private_parent / "new"):
    pass
  assert stat.S_IMODE(private_parent.stat().st_mode) == 0o755


def test_foreign_owner_rejected(private_parent, monkeypatch, sentinel_factory):
  before = sentinel_factory(private_parent)
  monkeypatch.setattr(os, "geteuid", lambda: private_parent.stat().st_uid + 1)
  with pytest.raises(PathError):
    PrivateDirectory.open_owned(private_parent)
  with pytest.raises(PathError):
    PrivateDirectory.create(private_parent / "new")
  before.assert_unchanged()


def test_target_symlink_injected_at_open_is_not_followed(private_parent, monkeypatch, sentinel_factory):
  outside = private_parent / "outside"
  outside.write_bytes(b"outside")
  before = sentinel_factory(outside)
  with PrivateDirectory.create(private_parent / "owned") as root:
    real_open = os.open
    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
      if path == "new" and flags & os.O_CREAT:
        os.symlink(outside, "new", dir_fd=dir_fd)
      return real_open(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(PathError):
      root.create_file("new", b"overwrite")
  before.assert_unchanged()


def test_intermediate_symlink_injected_at_open_is_not_followed(private_parent, monkeypatch, sentinel_factory):
  outside = private_parent / "outside"
  outside.mkdir(mode=0o700)
  before = sentinel_factory(outside)
  with PrivateDirectory.create(private_parent / "owned") as root:
    root.create_directory("middle")
    real_open = os.open
    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
      if path == "middle":
        os.rename("middle", "old-middle", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.symlink(outside, "middle", dir_fd=dir_fd)
      return real_open(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(PathError):
      root.create_file("middle/new", b"overwrite")
  before.assert_unchanged()


def test_new_directory_replaced_with_symlink_is_not_chmodded(private_parent, monkeypatch, sentinel_factory):
  outside = private_parent / "outside"
  outside.mkdir(mode=0o755)
  before = sentinel_factory(outside)
  real_mkdir = os.mkdir
  def racing_mkdir(path, mode=0o777, *, dir_fd=None):
    real_mkdir(path, mode, dir_fd=dir_fd)
    if path == "new":
      os.rmdir(path, dir_fd=dir_fd)
      os.symlink(outside, path, dir_fd=dir_fd)
  with PrivateDirectory.create(private_parent / "owned") as root:
    monkeypatch.setattr(os, "mkdir", racing_mkdir)
    with pytest.raises(PathError):
      root.create_directory("new")
  before.assert_unchanged()


def test_pinned_root_does_not_follow_replacement_symlink(private_parent, sentinel_factory):
  outside = private_parent / "outside"
  outside.mkdir(mode=0o700)
  before = sentinel_factory(outside)
  path = private_parent / "owned"
  with PrivateDirectory.create(path) as root:
    path.rename(private_parent / "moved-owned")
    path.symlink_to(outside, target_is_directory=True)
    # 句柄指向原目录，不能被新符号链接重定向；这不是阻止外部重命名的沙箱。
    root.create_file("new", b"pinned")
  before.assert_unchanged()
  assert (private_parent / "moved-owned/new").read_bytes() == b"pinned"


def test_file_creation_handles_short_writes(private_parent, monkeypatch):
  real_write = os.write
  def short_write(fd, value):
    return real_write(fd, value[:2])
  with PrivateDirectory.create(private_parent / "owned") as root:
    monkeypatch.setattr(os, "write", short_write)
    root.create_file("new", b"abcdefg")
  assert (private_parent / "owned/new").read_bytes() == b"abcdefg"


def test_file_mode_is_exact_under_restrictive_umask(private_parent):
  with PrivateDirectory.create(private_parent / "owned") as root:
    previous = os.umask(0o777)
    try:
      root.create_file("new", b"private")
    finally:
      os.umask(previous)
  assert stat.S_IMODE((private_parent / "owned/new").stat().st_mode) == 0o600


def test_errors_do_not_echo_private_paths_or_low_level_messages(private_parent, monkeypatch):
  canary = "private-path-canary"
  def denied(*args, **kwargs):
    raise PermissionError(canary)
  with PrivateDirectory.create(private_parent / "owned") as root:
    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(PathError) as caught:
      root.create_file(canary, b"secret")
  assert canary not in str(caught.value)
  assert canary not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("method", ["create", "open_owned"])
@pytest.mark.parametrize("path", ["relative/private", "/a/../private"])
def test_absolute_boundary_rejects_unsafe_path_before_mutation(private_parent, method, path, sentinel_factory):
  before = sentinel_factory(private_parent)
  with pytest.raises(PathError):
    getattr(PrivateDirectory, method)(Path(path))
  before.assert_unchanged()


def test_missing_parent_is_not_created_implicitly(private_parent, sentinel_factory):
  before = sentinel_factory(private_parent)
  with pytest.raises(PathError):
    PrivateDirectory.create(private_parent / "missing/new")
  before.assert_unchanged()


def test_regular_file_ancestor_is_rejected(private_parent, sentinel_factory):
  file = private_parent / "file"
  file.write_bytes(b"not-a-directory")
  before = sentinel_factory(private_parent)
  with pytest.raises(PathError):
    PrivateDirectory.create(file / "new")
  before.assert_unchanged()


def test_independent_boundaries_do_not_write_each_other(private_parent, sentinel_factory):
  with PrivateDirectory.create(private_parent / "first") as first:
    with PrivateDirectory.create(private_parent / "second") as second:
      second.create_file("settings", b"second")
      before = sentinel_factory(private_parent / "second")
      first.create_file("settings", b"first")
      before.assert_unchanged()


def test_directory_identity_replacement_between_stat_and_open_fails(private_parent, monkeypatch):
  with PrivateDirectory.create(private_parent / "owned") as root:
    root.create_directory("middle")
    real_open = os.open
    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
      if path == "middle":
        os.rename("middle", "old", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.mkdir("middle", 0o700, dir_fd=dir_fd)
      return real_open(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(PathError, match="身份"):
      root.create_file("middle/new", b"new")
  assert not (private_parent / "owned/middle/new").exists()
  assert not (private_parent / "owned/old/new").exists()


def test_write_failure_is_private_and_not_reported_as_success(private_parent, monkeypatch):
  def denied(fd, value):
    raise OSError("synthetic-private-write-error")
  with PrivateDirectory.create(private_parent / "owned") as root:
    monkeypatch.setattr(os, "write", denied)
    with pytest.raises(PathError) as caught:
      root.create_file("new", b"private")
  assert "synthetic-private-write-error" not in str(caught.value)
  # 不是事务：失败可能留下新文件，但它仍是私人文件，不能自动清理未知对象。
  file = private_parent / "owned/new"
  assert file.read_bytes() == b""
  assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_directory_owner_bits_masked_off_fail_without_loosening_permissions(private_parent):
  if os.geteuid() == 0:
    pytest.skip("root 可绕过目录访问权限，不能验证普通用户的拒绝分支")
  previous = os.umask(0o777)
  try:
    with pytest.raises(PathError):
      PrivateDirectory.create(private_parent / "inaccessible")
  finally:
    os.umask(previous)
    target = private_parent / "inaccessible"
    actual_mode = stat.S_IMODE(target.stat().st_mode)
    # 仅恢复本测试创建的目录供 pytest 清理，不是生产路径修复。
    target.chmod(0o700)
  assert actual_mode == 0


def test_closed_boundary_cannot_be_reused(private_parent):
  with PrivateDirectory.create(private_parent / "owned") as root:
    pass
  with pytest.raises(PathError):
    root.create_file("new", b"new")
