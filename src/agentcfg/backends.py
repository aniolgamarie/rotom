"""依赖后端契约；命令和启动不推断工具的包管理器或目录布局。"""

from pathlib import Path
from typing import Protocol


class DependencyBackend(Protocol):
  def read_lock(self, repository): ...
  def resolve_lock(self, repository): ...
  def sync(self, workspace, lock): ...
  def root(self, workspace, identity: str) -> Path: ...
  def status(self, workspace, identity: str) -> str: ...
  def executable_paths(self, root: Path) -> tuple[Path, ...]: ...
  def toolchain(self, lock) -> dict: ...


class DshBackend:
  def read_lock(self, repository):
    from .dependencies import read_lock
    return read_lock(repository)

  def resolve_lock(self, repository):
    from .dependencies import resolve_lock
    return resolve_lock(repository)

  def sync(self, workspace, lock):
    from .dependencies import sync
    return sync(workspace, lock)

  def root(self, workspace, identity):
    from .paths import safe_id
    return workspace.instance / "runtimes" / safe_id(identity)

  def status(self, workspace, identity):
    from .runtime_packages import status
    return status(self.root(workspace, identity), identity)

  def executable_paths(self, root):
    return (root / "node_modules/.bin",)

  def toolchain(self, lock):
    return {key: lock.metadata[key] for key in ("node", "npm")}

  def openspec_argv(self, workspace, lock):
    return ["node", str(self.root(workspace, lock.identity) / "node_modules/@fission-ai/openspec/bin/openspec.js")]
