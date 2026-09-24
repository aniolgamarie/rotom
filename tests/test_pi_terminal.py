"""PTY 的 IO/关闭协议使用假设备和临时文件；不打开真实终端或启动程序。"""
import errno
import io
import os
from types import SimpleNamespace
import pytest
from agentcfg import pi_terminal
from agentcfg.pi_supervisor import SpawnCommand
from agentcfg.schema import ConfigError


def test_terminal_channels_transfer_only_owned_descriptors_and_resize(tmp_path, monkeypatch):
  master = os.open(tmp_path / "master", os.O_CREAT | os.O_RDWR, 0o600)
  slave = os.open(tmp_path / "slave", os.O_CREAT | os.O_RDWR, 0o600)
  slave_identity = os.fstat(slave).st_ino
  calls = []
  monkeypatch.setattr(pi_terminal.os, "openpty", lambda: (master, slave))
  monkeypatch.setattr(pi_terminal.fcntl, "ioctl", lambda *args: calls.append(args))
  terminal = pi_terminal.TerminalChannels(24, 80)
  assert terminal.streams() == {"stdin": slave, "stdout": slave, "stderr": slave}
  child = SimpleNamespace(); terminal.attach(child)
  assert terminal.slave is None
  assert os.fstat(child.stdin.fileno()).st_ino != slave_identity
  terminal.resize(40, 120)
  assert calls[1][0] == child.stdin.fileno()
  assert calls[1][2] == pi_terminal.dimensions(40, 120)
  child.stdin.close(); child.stdout.close(); child.stderr.close(); terminal.close()


def test_terminal_reader_waits_through_backpressure_and_treats_only_eio_as_eof(monkeypatch):
  values = iter([None, BlockingIOError(), b"frame", OSError(errno.EIO, "EOF")])
  class Stream:
    def read(self, count):
      value = next(values)
      if isinstance(value, Exception): raise value
      return value
    def fileno(self): return 123
  waits = []
  monkeypatch.setattr(pi_terminal.select, "select", lambda *args: waits.append(args))
  reader = pi_terminal.TerminalReader(Stream())
  assert reader.read(100) == b"frame" and len(waits) == 2
  assert reader.read(100) == b""


@pytest.mark.parametrize("size", [(0, 80), (24, True), (24, 1001)])
def test_terminal_size_fails_before_device_allocation(tmp_path, monkeypatch, size):
  monkeypatch.setattr(pi_terminal.os, "openpty", lambda: pytest.fail("no device allocation"))
  with pytest.raises(ConfigError): pi_terminal.TerminalChannels(*size)
  with pytest.raises(ConfigError): SpawnCommand(("fixture",), tmp_path, {}, terminal_size=size)
