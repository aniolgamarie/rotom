"""单次受管命令的私人 PTY；创建终端不启动进程，所有关闭均保留已有执行证明边界。"""
import errno
import fcntl
import io
import os
import struct
import termios
import select

from .schema import ConfigError


def dimensions(rows, columns):
  if any(type(value) is not int or not 1 <= value <= 1000 for value in (rows, columns)):
    raise ConfigError("pi-terminal-size")
  return struct.pack("HHHH", rows, columns, 0, 0)


class TerminalReader:
  def __init__(self, stream):
    self.stream = stream

  def read(self, count):
    while True:
      try:
        value = self.stream.read(count)
        if value is not None:
          return value
      except BlockingIOError:
        pass
      except OSError as error:
        # Linux 的 PTY 在最后一个 slave 关闭后以 EIO 表达 EOF。
        if error.errno == errno.EIO:
          return b""
        raise
      # stdin 的 dup 与 master 共用 O_NONBLOCK；暂无屏幕数据不等于 EOF。
      select.select([self.stream.fileno()], [], [], 1)

  def close(self):
    self.stream.close()


class TerminalChannels:
  def __init__(self, rows, columns):
    size = dimensions(rows, columns)
    self.master, self.slave = os.openpty()
    try:
      fcntl.ioctl(self.master, termios.TIOCSWINSZ, size)
    except BaseException:
      self.close()
      raise

  def streams(self):
    return {"stdin": self.slave, "stdout": self.slave, "stderr": self.slave}

  def attach(self, child):
    os.close(self.slave)
    self.slave = None
    child.stdin = os.fdopen(os.dup(self.master), "wb", buffering=0)
    child.stdout = TerminalReader(os.fdopen(self.master, "rb", buffering=0))
    child.stderr = io.BytesIO()
    self.master = None
    self.writer = child.stdin

  def resize(self, rows, columns):
    fcntl.ioctl(self.writer.fileno(), termios.TIOCSWINSZ, dimensions(rows, columns))

  def close(self):
    for name in ("master", "slave"):
      descriptor = getattr(self, name, None)
      if descriptor is not None:
        os.close(descriptor)
        setattr(self, name, None)
