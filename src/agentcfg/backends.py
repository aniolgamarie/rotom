"""依赖后端契约；命令和启动不推断工具的包管理器或目录布局。"""

from pathlib import Path
from typing import Protocol


class DependencyBackend(Protocol):
  def runtime_identity(self, workspace, lock):
    """默认沿用旧锁身份；按平台/配方分包的后端显式覆盖。"""
    return lock.identity

  def read_lock(self, repository): ...
  def resolve_lock(self, repository): ...
  def sync(self, workspace, lock): ...
  def root(self, workspace, identity: str) -> Path: ...
  def status(self, workspace, identity: str) -> str: ...
  def executable_paths(self, root: Path) -> tuple[Path, ...]: ...
  def toolchain(self, lock) -> dict: ...


class DshBackend:
  adapter_id = "dsh"

  @property
  def adapter_version(self):
    from .dsh import DshAdapter
    return DshAdapter.declaration.adapter_version

  def read_lock(self, repository):
    from .dependencies import read_lock
    return read_lock(repository, self.adapter_id, self.adapter_version)

  def resolve_lock(self, repository):
    from .dependencies import resolve_lock
    return resolve_lock(repository, adapter_id=self.adapter_id,
                        expected_adapter_version=self.adapter_version)

  def sync(self, workspace, lock):
    from .dependencies import sync
    return sync(workspace, lock, self.adapter_id)

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
