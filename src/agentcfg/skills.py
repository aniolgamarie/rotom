"""可信仓库的完整技能包 -> 私人 Artifact 意图；不写文件、不求值、不运行脚本。

调用者须先 load_sources/resolve_config；override 是已校验的旧来源身份，不是待读取的包。
只收集选中路径，目标按 registry 稳定 ID 命名；不存在原生 DSH 路径或安装默认值。
目录句柄/no-follow 和身份复查防止路径重定向，不是对恶意同用户进程的 OS 沙箱。
"""

import os
from pathlib import Path
import stat

from .adapter import Artifact, ManagedTarget, Ownership
from .paths import trusted_source_directory, _open_directory, relative_path, safe_id


class SkillError(Exception):
  """固定错误，不保留资源正文、私有路径或原始异常。"""

  exit_code = 2

  def __init__(self):
    super().__init__("技能包收集失败；请检查显式来源、普通文件及安全相对路径")


def _identity(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
          info.st_mtime_ns, info.st_ctime_ns)


def _walk(directory: int, target: str) -> list[Artifact]:
  before = os.fstat(directory)
  artifacts = []
  for name in sorted(os.listdir(directory)):
    safe_id(name)
    path = f"{target}/{name}"
    relative_path(path)
    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
      child = _open_directory(directory, name)
      try:
        artifacts.extend(_walk(child, path))
      finally:
        os.close(child)
    elif stat.S_ISREG(info.st_mode):
      fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                   dir_fd=directory)
      with os.fdopen(fd, "rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or _identity(info) != _identity(opened):
          raise ValueError()
        content = source.read()
        if (_identity(opened) != _identity(os.fstat(source.fileno()))
            or _identity(opened) != _identity(os.stat(name, dir_fd=directory, follow_symlinks=False))):
          raise ValueError()
      artifacts.append(Artifact(ManagedTarget(path, Ownership.FILE, "bytes"), content,
                                0o700 if opened.st_mode & 0o111 else 0o600))
    else:
      # 拒绝符号链接（包括断链）、FIFO、socket、设备；不先打开再判断。
      raise ValueError()
  if _identity(before) != _identity(os.fstat(directory)):
    raise ValueError()
  return artifacts


def _collect(trusted_root: Path, selected: dict, target_root: str) -> tuple[Artifact, ...]:
  if (not isinstance(trusted_root, Path) or not trusted_root.is_absolute()
      or ".." in trusted_root.parts or type(selected) is not dict or type(target_root) is not str):
    raise ValueError()
  relative_path(target_root)
  sources = {}
  for key, definition in selected.items():
    if (type(key) is not str or type(definition) is not dict
        or not {"path"} <= set(definition) <= {"path", "override"}
        or any(type(value) is not str for value in definition.values())):
      raise ValueError()
    safe_id(key)
    path = relative_path(definition["path"])
    if "override" in definition:
      old = relative_path(definition["override"])
      if path == old:
        raise ValueError()
    if any(path.is_relative_to(other) or other.is_relative_to(path) for other in sources.values()):
      raise ValueError()
    sources[key] = path
  artifacts = []
  if not sources:
    return ()
  with trusted_source_directory(trusted_root) as root:
    for key in sorted(sources):
      directory = os.dup(root)
      try:
        for name in sources[key].parts:
          child = _open_directory(directory, name)
          os.close(directory)
          directory = child
        if not stat.S_ISREG(os.stat("SKILL.md", dir_fd=directory, follow_symlinks=False).st_mode):
          raise ValueError()
        artifacts.extend(_walk(directory, f"{target_root}/{key}"))
      finally:
        os.close(directory)
  return tuple(sorted(artifacts, key=lambda artifact: artifact.target.path))


def collect_skills(trusted_root: Path, selected: dict, *, target_root: str) -> tuple[Artifact, ...]:
  """递归保留全部普通文件（包括隐藏文件）、相对布局及 0700/0600 执行意图。

  selected 为 resolver 的 skills 表；不发现同名包、不自动覆盖、不读取被替换来源。
  空目录无文件意图；未来写入层按文件路径建立必要 0700 父目录。此 API 不授予目标所有权，
  render_candidate 还须验证 adapter 的 FILE/skill-directory 显式目录作用域。
  """
  failed = False
  result = None
  try:
    result = _collect(trusted_root, selected, target_root)
  except Exception:
    failed = True
  if failed:
    raise SkillError()
  return result
