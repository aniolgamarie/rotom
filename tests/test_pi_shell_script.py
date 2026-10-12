"""本进程 Linux memfd/seal 证据；不启动进程、不执行脚本、不落盘。"""

import errno
import fcntl
import os
import stat

import pytest

from agentcfg.pi_shell_script import sealed_data, sealed_script
from agentcfg.schema import ConfigError


SCRIPT = "printf '%s' '私有脚本' | cat > output\nvalue=$(cat output)\nprintf '%s' \"$value\""


def assert_closed(fd):
  with pytest.raises(OSError) as caught: os.fstat(fd)
  assert caught.value.errno == errno.EBADF


def test_real_memfd_is_private_complete_cloexec_and_permanently_sealed(tmp_path, sentinel_factory):
  sentinel = sentinel_factory(tmp_path)
  required = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
  with sealed_script(SCRIPT) as fd:
    info = os.fstat(fd)
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    assert fcntl.fcntl(fd, fcntl.F_GET_SEALS) & required == required
    assert os.lseek(fd, 0, os.SEEK_CUR) == 0
    assert os.read(fd, 65537) == SCRIPT.encode("utf-8")
    assert os.read(fd, 1) == b""
    with pytest.raises(OSError) as caught: os.write(fd, b"changed")
    assert caught.value.errno == errno.EPERM
    for size in (0, info.st_size + 1):
      with pytest.raises(OSError) as caught: os.ftruncate(fd, size)
      assert caught.value.errno == errno.EPERM
    with pytest.raises(OSError) as caught: fcntl.fcntl(fd, fcntl.F_ADD_SEALS, 0)
    assert caught.value.errno == errno.EPERM
  assert_closed(fd)
  sentinel.assert_unchanged()


@pytest.mark.parametrize("command", ["", "a\0b", "\ud800", "界" * 21846, "a" * 65537, None],
  ids=["empty", "nul", "surrogate", "utf8-overflow", "ascii-overflow", "non-string"])
def test_invalid_input_fails_before_creating_fd(command, monkeypatch):
  def forbidden(*args, **kwargs): raise AssertionError("invalid input must not create an fd")
  monkeypatch.setattr(os, "memfd_create", forbidden)
  with pytest.raises(ConfigError) as caught:
    with sealed_script(command): pytest.fail("invalid command yielded an fd")
  assert caught.value.code == "pi-shell-command"


def test_exact_utf8_byte_ceiling_is_preserved():
  command = "界" * 21845 + "a"
  with sealed_script(command) as fd:
    assert os.read(fd, 65537) == command.encode("utf-8")
    assert os.fstat(fd).st_size == 65536


@pytest.mark.parametrize("unsupported", ["missing", "failure"])
def test_unavailable_has_no_disk_fallback(unsupported, monkeypatch, tmp_path, sentinel_factory):
  sentinel = sentinel_factory(tmp_path)
  if unsupported == "missing": monkeypatch.delattr(os, "memfd_create")
  else:
    def unavailable(*args, **kwargs): raise OSError(errno.ENOSYS, SCRIPT)
    monkeypatch.setattr(os, "memfd_create", unavailable)
  with pytest.raises(ConfigError) as caught:
    with sealed_script(SCRIPT): pytest.fail("unavailable memfd yielded")
  assert caught.value.code == "pi-shell-script-unavailable"
  assert "私有脚本" not in str(caught.value)
  sentinel.assert_unchanged()


def test_short_writes_and_interruption_preserve_all_bytes(monkeypatch):
  original = os.write
  calls = []
  def short_write(fd, data):
    calls.append(len(data))
    if len(calls) == 1: raise InterruptedError(errno.EINTR, "synthetic interrupted write")
    return original(fd, data[:3])
  monkeypatch.setattr(os, "write", short_write)
  with sealed_script(SCRIPT) as fd:
    assert os.read(fd, 65537) == SCRIPT.encode("utf-8")
  assert len(calls) > 2
  assert_closed(fd)


@pytest.mark.parametrize("failure", ["chmod", "write", "zero-write", "add-seals", "verify-seals", "seek"])
def test_setup_failure_is_fixed_and_closes_created_fd(failure, monkeypatch):
  original_create = os.memfd_create
  created = []
  def create(name, flags):
    assert name == "agentcfg-shell-script"
    assert flags == os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    fd = original_create(name, flags)
    created.append(fd)
    return fd
  monkeypatch.setattr(os, "memfd_create", create)
  def failed(*args, **kwargs): raise OSError(errno.EIO, SCRIPT)
  if failure == "chmod": monkeypatch.setattr(os, "fchmod", failed)
  elif failure == "write": monkeypatch.setattr(os, "write", failed)
  elif failure == "zero-write": monkeypatch.setattr(os, "write", lambda *args: 0)
  elif failure == "seek": monkeypatch.setattr(os, "lseek", failed)
  else:
    original_fcntl = fcntl.fcntl
    def faulty_fcntl(fd, operation, *args):
      if failure == "add-seals" and operation == fcntl.F_ADD_SEALS: failed()
      if failure == "verify-seals" and operation == fcntl.F_GET_SEALS: return 0
      return original_fcntl(fd, operation, *args)
    monkeypatch.setattr(fcntl, "fcntl", faulty_fcntl)
  with pytest.raises(ConfigError) as caught:
    with sealed_script(SCRIPT): pytest.fail("failed setup yielded an fd")
  assert caught.value.code == "pi-shell-script-unavailable"
  assert "私有脚本" not in str(caught.value)
  fd, = created
  assert_closed(fd)


def test_body_exception_preserves_original_and_closes_fd():
  error = RuntimeError("synthetic caller failure")
  with pytest.raises(RuntimeError) as caught:
    with sealed_script(SCRIPT) as fd: raise error
  assert caught.value is error
  assert_closed(fd)


def test_caller_closed_fd_cleanup_is_safe():
  with sealed_script(SCRIPT) as fd: os.close(fd)
  assert_closed(fd)


def test_reused_fd_does_not_close_foreign_inode():
  foreign = os.memfd_create("synthetic-foreign", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
  try:
    with sealed_script(SCRIPT) as fd:
      os.close(fd)
      assert os.dup2(foreign, fd, inheritable=False) == fd
      os.write(fd, b"foreign contents")
    assert os.fstat(fd).st_ino == os.fstat(foreign).st_ino
    os.lseek(fd, 0, os.SEEK_SET)
    assert os.read(fd, 100) == b"foreign contents"
  finally:
    os.close(foreign)
    os.close(fd)


@pytest.mark.parametrize("data", [b"\0\xff\x80\x01binary\n", b"", b"x" * 65536],
  ids=["binary", "empty-mask", "byte-ceiling"])
def test_sealed_data_is_complete_private_cloexec_rewound_and_sealed(data):
  required = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
  with sealed_data(data) as fd:
    info = os.fstat(fd)
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert os.get_inheritable(fd) is False
    assert fcntl.fcntl(fd, fcntl.F_GET_SEALS) & required == required
    assert os.lseek(fd, 0, os.SEEK_CUR) == 0
    assert os.read(fd, 65537) == data and os.read(fd, 1) == b""
    with pytest.raises(OSError) as caught: os.write(fd, b"changed")
    assert caught.value.errno == errno.EPERM
    with pytest.raises(OSError) as caught: os.ftruncate(fd, len(data) + 1)
    assert caught.value.errno == errno.EPERM
  assert_closed(fd)


@pytest.mark.parametrize("data", [b"x" * 65537, "text", bytearray(b"bytes"), memoryview(b"bytes"), None, 1],
  ids=["overflow", "text", "bytearray", "memoryview", "none", "integer"])
def test_invalid_data_fails_before_memfd_create(data, monkeypatch):
  def forbidden(*args, **kwargs): raise AssertionError("invalid data must not create an fd")
  monkeypatch.setattr(os, "memfd_create", forbidden)
  with pytest.raises(ConfigError) as caught:
    with sealed_data(data): pytest.fail("invalid data yielded")
  assert caught.value.code == "pi-shell-data"


def test_data_uses_fixed_name_and_separate_fd_from_script(monkeypatch):
  original = os.memfd_create
  names = []
  def create(name, flags):
    names.append(name)
    assert flags == os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    return original(name, flags)
  monkeypatch.setattr(os, "memfd_create", create)
  with sealed_script(SCRIPT) as script_fd, sealed_data(b"\0\xff") as data_fd:
    assert script_fd != data_fd
    assert os.read(data_fd, 10) == b"\0\xff"
  assert names == ["agentcfg-shell-script", "agentcfg-shell-data"]
  assert_closed(script_fd); assert_closed(data_fd)


@pytest.mark.parametrize("failure", ["missing", "write", "seal"])
def test_data_setup_failure_uses_own_error_and_closes_fd(failure, monkeypatch):
  created = []
  original = os.memfd_create
  def create(name, flags):
    fd = original(name, flags)
    created.append(fd)
    return fd
  if failure == "missing": monkeypatch.delattr(os, "memfd_create")
  else:
    monkeypatch.setattr(os, "memfd_create", create)
    def failed(*args, **kwargs): raise OSError(errno.EIO, "synthetic private binary error")
    if failure == "write": monkeypatch.setattr(os, "write", failed)
    else: monkeypatch.setattr(fcntl, "fcntl", failed)
  with pytest.raises(ConfigError) as caught:
    with sealed_data(b"\0\xff"): pytest.fail("failed setup yielded")
  assert caught.value.code == "pi-shell-data-unavailable"
  assert "synthetic private binary error" not in str(caught.value)
  for fd in created: assert_closed(fd)


def test_data_body_exception_is_preserved_and_fd_closed():
  error = ValueError("synthetic body failure")
  with pytest.raises(ValueError) as caught:
    with sealed_data(b"\0\xff") as fd: raise error
  assert caught.value is error
  assert_closed(fd)


def test_data_reused_fd_does_not_close_foreign_inode():
  foreign = os.memfd_create("synthetic-foreign", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
  try:
    with sealed_data(b"") as fd:
      os.close(fd)
      os.dup2(foreign, fd, inheritable=False)
    assert os.fstat(fd).st_ino == os.fstat(foreign).st_ino
  finally:
    os.close(foreign); os.close(fd)
