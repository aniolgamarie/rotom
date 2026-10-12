"""Linux 本进程私有脚本/二进制数据的密封 FD；不执行、不落盘、无文件回退。

只保证内容密封和显式 FD 继承边界，不保证不可 swap 或进程隔离。
调用者负责受信 worker 的 FD 交接；这里不启动 helper。
"""

from contextlib import contextmanager
import fcntl
import os
import sys

from .schema import ConfigError


def _bytes(command):
  if type(command) is not str or not command or "\0" in command or len(command) > 65536:
    raise ConfigError("pi-shell-command")
  try: data = command.encode("utf-8")
  except UnicodeError: raise ConfigError("pi-shell-command") from None
  if len(data) > 65536: raise ConfigError("pi-shell-command")
  return data


def _identity(fd):
  info = os.fstat(fd)
  return (info.st_dev, info.st_ino)


def _close_owned(fd, identity):
  # 调用者可能误关并复用同一整数；只关自己的 inode，不重试 close。
  try:
    if identity is None or _identity(fd) == identity: os.close(fd)
  except OSError:
    pass


@contextmanager
def _sealed(data, *, name, error_code):
  fd, identity = None, None
  try:
    try:
      if sys.platform != "linux": raise OSError()
      fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
      identity = _identity(fd)
      os.fchmod(fd, 0o600)
      remaining = memoryview(data)
      while remaining:
        try: count = os.write(fd, remaining)
        except InterruptedError: continue
        if count <= 0: raise OSError()
        remaining = remaining[count:]
      seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
      fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
      if fcntl.fcntl(fd, fcntl.F_GET_SEALS) & seals != seals: raise OSError()
      if os.lseek(fd, 0, os.SEEK_SET) != 0: raise OSError()
    except (AttributeError, OSError, ValueError, TypeError):
      raise ConfigError(error_code) from None
    # yield 位于 setup 异常转换之外，保留调用者原异常。
    yield fd
  finally:
    if fd is not None: _close_owned(fd, identity)


@contextmanager
def sealed_script(command):
  """校验脚本后创建密封、CLOEXEC、0600 的 memfd；退出时关闭自身 FD。"""
  data = _bytes(command)
  with _sealed(data, name="agentcfg-shell-script", error_code="pi-shell-script-unavailable") as fd:
    yield fd


@contextmanager
def sealed_data(data):
  """接收至多 64KiB 的 exact bytes；允许空遮罩或任意二进制数据。"""
  if type(data) is not bytes or len(data) > 65536: raise ConfigError("pi-shell-data")
  with _sealed(data, name="agentcfg-shell-data", error_code="pi-shell-data-unavailable") as fd:
    yield fd
