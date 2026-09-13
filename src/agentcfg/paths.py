"""私人路径原语；不提供部署所有权证明、覆盖、删除或事务。"""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import re
import stat


class PathError(Exception):
  """只包含固定说明，不携带私有路径或底层文件系统异常正文。"""


def _text(value: str) -> str:
  if (not isinstance(value, str) or not value or "\\" in value
      or any(ord(char) < 32 or ord(char) == 127 for char in value)):
    raise PathError("路径必须为非空字面字符串，不得包含控制字符或反斜线")
  return value


def safe_id(value: str) -> str:
  text = _text(value)
  if text in (".", "..") or "/" in text:
    raise PathError("ID 必须为单一路径段，不得逃逸")
  return text


def relative_path(value: str) -> Path:
  text = _text(value)
  if any(part in ("", ".", "..") for part in text.split("/")):
    raise PathError("产物路径必须为非空相对路径，不得逃逸")
  return Path(text)


def _absolute_path(value: str) -> Path:
  text = _text(value)
  if not text.startswith("/") or ".." in text.split("/"):
    raise PathError("需要不含逃逸段的绝对路径")
  # 不调用 resolve，保留符号链接供文件系统边界拒绝。
  return Path(text)


def configured_path(value: str) -> Path:
  """仅用于框架 TOML 路径字段，不替代 CLI --local 的相对路径规则。"""
  text = _text(value)
  if re.search(r"\$(?:[A-Za-z_({])|`", text):
    raise PathError("配置路径不得包含变量插值或命令替换")
  if text.startswith("~/"):
    home = _absolute_path(os.environ.get("HOME", ""))
    text = str(home) + "/" + text[2:]
  return _absolute_path(text)


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _check_private(fd: int) -> None:
  info = os.fstat(fd)
  if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
    raise PathError("受管目录必须属于当前用户且权限为 0700")


def _check_ancestor(fd: int) -> None:
  info = os.fstat(fd)
  if info.st_uid not in (0, os.geteuid()):
    raise PathError("路径祖先不属于可信用户")
  # 系统临时目录可有 sticky 位；最终创建父目录另行要求当前用户独占写入。
  if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
    raise PathError("路径祖先允许其他用户写入")


def _open_directory(parent: int, name: str) -> int:
  before = os.stat(name, dir_fd=parent, follow_symlinks=False)
  if not stat.S_ISDIR(before.st_mode):
    raise PathError("路径必须为真实目录，不得穿透符号链接")
  fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
  try:
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
      raise PathError("目录身份已变化，请重新检查")
    return fd
  except BaseException:
    os.close(fd)
    raise


@contextmanager
def _absolute_directory(path: Path):
  fd = os.open("/", _DIRECTORY_FLAGS)
  try:
    _check_ancestor(fd)
    for name in path.parts[1:]:
      child = _open_directory(fd, name)
      os.close(fd)
      fd = child
      _check_ancestor(fd)
    yield fd
  finally:
    os.close(fd)


@contextmanager
def trusted_source_directory(path: Path):
  """只读、显式信任的配置来源；不授予任何部署写入权限。

  逐段 no-follow 固定目录身份，检查仓库自身的属主与写权限，允许共享挂载祖先。
  信任选择发生于打开时；不承诺防御同用户篡改可信源代码。
  私人目标仍使用 _absolute_directory 的严格祖先规则。
  """
  path = _absolute_path(os.fspath(path))
  fd = os.open("/", _DIRECTORY_FLAGS)
  try:
    for name in path.parts[1:]:
      child = _open_directory(fd, name)
      os.close(fd)
      fd = child
    info = os.fstat(fd)
    if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
      raise PathError("可信源目录属主或写权限不安全")
    yield fd
  finally:
    os.close(fd)


def _create_directory(parent: int, name: str) -> int:
  os.mkdir(name, 0o700, dir_fd=parent)
  # 独占 mkdir 后仅对 no-follow 打开的新目录句柄设置权限。
  fd = _open_directory(parent, name)
  try:
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & ~0o700:
      raise PathError("新目录属主或权限异常")
    os.fchmod(fd, 0o700)
    _check_private(fd)
    return fd
  except BaseException:
    os.close(fd)
    raise


def read_private_file(path: Path) -> bytes:
  """私人输入在读正文前检查；不 resolve 链接，不修正用户权限。"""
  path = _absolute_path(os.fspath(path.absolute()))
  def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)
  with _absolute_directory(path.parent) as parent:
    _check_private(parent)
    before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
        or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600):
      raise PathError("本地文件必须为当前用户的普通单链接 0600 文件；私人父目录需为 0700")
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
      if identity(os.fstat(stream.fileno())) != identity(before):
        raise PathError("本地文件在读取前变化")
      data = stream.read()
      if identity(os.fstat(stream.fileno())) != identity(before):
        raise PathError("本地文件在读取期间变化")
    if identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != identity(before):
      raise PathError("本地文件路径在读取期间变化")
    with _absolute_directory(path.parent) as current:
      if identity(os.fstat(current)) != identity(os.fstat(parent)):
        raise PathError("本地文件父目录在读取期间变化")
    return data


class InitializationError(Exception):
  """初始化专用的固定脱敏错误；不携带路径或底层异常正文。"""

  def __init__(self, exit_code: int):
    self.exit_code = exit_code
    super().__init__({
      2: "初始化参数无效；请检查机器 ID、HOME 和配置路径",
      4: "初始化冲突；目标已存在、位于仓库内或目录不安全，请检查路径及权限",
      6: "初始化文件系统操作失败；请检查访问权限和可用空间",
    }[exit_code])


def _check_initialization_parent(fd: int) -> None:
  info = os.fstat(fd)
  if info.st_uid != os.geteuid() or info.st_mode & 0o022:
    raise PathError("初始化父目录必须由当前用户安全控制")


def create_initial_local(config_home: Path, machine_id: str, data: bytes) -> None:
  """仅供已校验的 init-local：遍历配置容器，不证明或接管部署所有权。

  仅创建目的路径必要的 0700 目录及独占 0600 文件；既有 namespace 必须安全，
  可复用于第二台机器但不修改权限。不读取目标，不删除，不承诺失败回滚。
  """
  try:
    fd = os.open("/", _DIRECTORY_FLAGS)
    try:
      _check_ancestor(fd)
      for name in config_home.parts[1:]:
        try:
          child = _open_directory(fd, name)
        except FileNotFoundError:
          _check_initialization_parent(fd)
          child = _create_directory(fd, name)
        parent, fd = fd, child
        os.close(parent)
        _check_ancestor(fd)
      _check_initialization_parent(fd)
      for name in ("agentcfg", "machines"):
        try:
          child = _open_directory(fd, name)
        except FileNotFoundError:
          child = _create_directory(fd, name)
        parent, fd = fd, child
        os.close(parent)
        _check_private(fd)
      file_fd = os.open(f"{machine_id}.toml", os.O_WRONLY | os.O_CREAT | os.O_EXCL
                        | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
      try:
        os.fchmod(file_fd, 0o600)
        remaining = memoryview(data)
        while remaining:
          written = os.write(file_fd, remaining)
          if written == 0:
            raise OSError(errno.EIO, "incomplete write")
          remaining = remaining[written:]
      finally:
        os.close(file_fd)
    finally:
      os.close(fd)
  except PathError:
    raise InitializationError(4) from None
  except OSError as error:
    code = 4 if error.errno in (errno.EEXIST, errno.ELOOP, errno.ENOTDIR) else 6
    raise InitializationError(code) from None


class PrivateDirectory:
  """固定目录句柄的显式受管边界，使用 with 关闭。

  open_owned 的框架所有权必须由调用方证明；属主/权限并不是所有权证明。
  句柄阻止符号链接重定向，但不能阻止同用户进程重命名已打开的目录。
  创建失败可能留下新建的私人目录或部分文件；不自动删除或声称事务回滚。
  """

  def __init__(self, fd: int):
    self._fd = fd

  @classmethod
  def create(cls, path: Path) -> "PrivateDirectory":
    """独占创建最后一层目录；其父目录必须已存在且由当前用户安全控制。"""
    target = _absolute_path(os.fspath(path))
    if target == Path("/"):
      raise PathError("不能创建文件系统根目录")
    try:
      with _absolute_directory(target.parent) as parent:
        info = os.fstat(parent)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
          raise PathError("创建父目录必须属于当前用户且不允许其他用户写入")
        return cls(_create_directory(parent, target.name))
    except OSError:
      raise PathError("无法独占创建私人目录；请检查存在状态、路径和权限") from None

  @classmethod
  def open_owned(cls, path: Path) -> "PrivateDirectory":
    """调用方已确认框架所有权时使用；不创建、不接管、不修改现有目录。"""
    target = _absolute_path(os.fspath(path))
    try:
      with _absolute_directory(target) as fd:
        _check_private(fd)
        return cls(os.dup(fd))
    except OSError:
      raise PathError("无法打开已受管目录；请检查路径和权限") from None

  def __enter__(self) -> "PrivateDirectory":
    if self._fd is None:
      raise PathError("私人目录句柄已关闭")
    return self

  def __exit__(self, *exc) -> None:
    if self._fd is not None:
      fd, self._fd = self._fd, None
      try:
        os.close(fd)
      except OSError:
        raise PathError("无法关闭私人目录句柄") from None

  @contextmanager
  def _parent(self, relative: Path):
    if self._fd is None:
      raise PathError("私人目录句柄已关闭")
    fd = os.dup(self._fd)
    try:
      _check_private(fd)
      for name in relative.parts[:-1]:
        child = _open_directory(fd, name)
        os.close(fd)
        fd = child
        _check_private(fd)
      yield fd
    finally:
      os.close(fd)

  def create_directory(self, relative: str) -> None:
    """独占创建相对目录，不自动创建中间层或复用现有目标。"""
    path = relative_path(relative)
    try:
      with self._parent(path) as parent:
        os.close(_create_directory(parent, path.name))
    except OSError:
      raise PathError("无法独占创建受管目录；请检查存在状态、路径和权限") from None

  def create_file(self, relative: str, data: bytes) -> None:
    """独占创建 0600 文件；无覆盖、符号链接跟随或失败自动清理。"""
    path = relative_path(relative)
    if not isinstance(data, bytes):
      raise PathError("文件内容必须为字节")
    try:
      with self._parent(path) as parent:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        try:
          os.fchmod(fd, 0o600)
          remaining = memoryview(data)
          while remaining:
            written = os.write(fd, remaining)
            if written == 0:
              raise PathError("文件写入未完成")
            remaining = remaining[written:]
        finally:
          os.close(fd)
    except OSError:
      raise PathError("无法独占创建私人文件；请检查存在状态、路径和权限") from None
