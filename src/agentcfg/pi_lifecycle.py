"""Pi 稳定实例准入：锁绑定实例目录，不能通过换 state_root 绕过运行保护。"""

from contextlib import contextmanager
import os
from pathlib import Path
import stat

from .storage import Conflict, Tree


def assert_inactive(state_root):
  # 旧记录只作为不透明的所有权阻断；不继续分发旧任务协议来解释或清除它。
  directory = Path(state_root) / "activity/leases"
  with Tree(directory) as tree:
    if tree.fd is not None and os.listdir(tree.fd):
      raise Conflict("实例保留旧执行归属，须先人工核实；不会清除或继续旧任务")


def assert_no_legacy_workspace_owner(cwd):
  """旧 Git 所有权仍阻止新启动；不解析任务正文、认领标记或建立新工作区协议。"""
  root = Path(cwd).absolute()
  while True:
    marker = root / ".git"
    try:
      info = marker.lstat()
      break
    except FileNotFoundError:
      if root == root.parent: return
      root = root.parent
  if stat.S_ISDIR(info.st_mode):
    git_dir = marker
  elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
    try:
      with Tree(root, private=False) as tree:
        raw = tree.read(".git", max_bytes=4096)
      line = raw[0].decode().strip()
      if not line.startswith("gitdir: ") or "\n" in line or "\r" in line: raise ValueError()
      git_dir = (root / line[8:]).resolve(strict=True)
    except (OSError, ValueError, UnicodeError):
      raise Conflict("Git所有权目录无法核实，拒绝启动") from None
  else:
    raise Conflict("Git所有权目录无法核实，拒绝启动")
  with Tree(git_dir / "agentcfg") as tree:
    if tree.fd is not None and os.listdir(tree.fd):
      raise Conflict("工作区保留旧Pi写入归属，须先人工核实；不会自动删除或接管")


@contextmanager
def guard(workspace, *, allow_active=False, create=True, shared=False):
  from .lifecycle import guard as physical_guard
  with physical_guard(workspace, shared=shared, create=create) as fd:
    if not allow_active:
      assert_inactive(workspace.state_root)
      from .run_owners import Registry
      Registry(workspace.state_root / "run-owners",
        getattr(workspace, "binding", {"profile": workspace.profile})).assert_inactive()
    yield fd
