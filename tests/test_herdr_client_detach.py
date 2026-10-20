"""只测本轮 UI 的固定原生 detach；不启动宿主或发送真实信号。"""
import stat
from types import SimpleNamespace

import pytest

from test_herdr_geometry import geometry


@pytest.fixture
def client(geometry, monkeypatch):
  master, pinned = 90001, 90002
  state = {"clock": 0.0, "start": 456, "raw_after": 3, "attrs": 0, "last_flags": None,
    "writes": bytearray(), "events": [], "write_size": 1, "blocked_writes": 0, "exit_code": 0}
  events = state["events"]
  class Process:
    pid = 123
    returncode = None
    def poll(self):
      events.append(("poll", self.returncode))
      return self.returncode
  process = Process()
  original = {name: getattr(geometry.os, name) for name in ("dup", "close", "fstat", "set_inheritable", "get_blocking", "set_blocking", "isatty", "write")}
  def dup(fd):
    if fd == master:
      events.append(("dup", fd))
      return pinned
    return original["dup"](fd)
  def close(fd):
    if fd in (master, pinned):
      events.append(("close", fd))
      return
    return original["close"](fd)
  def fstat(fd):
    if fd in (master, pinned):
      return SimpleNamespace(st_dev=3, st_ino=4, st_rdev=128, st_mode=state.get("mode", stat.S_IFCHR))
    return original["fstat"](fd)
  def inheritable(fd, value):
    if fd == pinned:
      events.append(("inheritable", fd, value))
      return
    return original["set_inheritable"](fd, value)
  def blocking(fd, value):
    if fd == pinned:
      events.append(("blocking", fd, value))
      return
    return original["set_blocking"](fd, value)
  def attrs(fd):
    assert fd == pinned
    state["attrs"] += 1
    flags = geometry.termios.ICANON | geometry.termios.ECHO if state["attrs"] < state["raw_after"] else 0
    state["last_flags"] = flags
    events.append(("attrs", flags))
    return [0, 0, 0, flags, 0, 0, []]
  def write(fd, data):
    assert fd == pinned and state["last_flags"] == 0
    if state["blocked_writes"]:
      state["blocked_writes"] -= 1
      raise BlockingIOError
    count = min(state["write_size"], len(data))
    state["writes"].extend(data[:count])
    events.append(("write", fd, data[:count]))
    return count
  def pump():
    events.append(("pump",))
    state["clock"] += 0.001
    if state["writes"] == b"\x18d":
      process.returncode = state["exit_code"]
  monkeypatch.setattr(geometry.os, "dup", dup)
  monkeypatch.setattr(geometry.os, "close", close)
  monkeypatch.setattr(geometry.os, "fstat", fstat)
  monkeypatch.setattr(geometry.os, "set_inheritable", inheritable)
  monkeypatch.setattr(geometry.os, "get_blocking", lambda fd: True if fd == pinned else original["get_blocking"](fd))
  monkeypatch.setattr(geometry.os, "set_blocking", blocking)
  monkeypatch.setattr(geometry.os, "isatty", lambda fd: state.get("tty", True) if fd == pinned else original["isatty"](fd))
  monkeypatch.setattr(geometry.os, "write", write)
  monkeypatch.setattr(geometry.termios, "tcgetattr", attrs)
  monkeypatch.setattr(geometry, "_process_start", lambda pid: state["start"])
  monkeypatch.setattr(geometry.time, "monotonic", lambda: state["clock"])
  monkeypatch.setattr(geometry.time, "sleep", lambda seconds: state.__setitem__("clock", state["clock"] + seconds))
  monkeypatch.setattr(geometry.os, "kill", lambda *args: pytest.fail("detach cannot signal"))
  return process, master, pinned, state, pump


def test_detach_waits_raw_writes_only_fixed_bytes_and_exits_before_close(geometry, client):
  process, master, pinned, state, pump = client
  state["blocked_writes"] = 1
  assert geometry.detach_owned_client(process, master, pump=pump) is None
  events = state["events"]
  assert state["writes"] == b"\x18d" and process.returncode == 0
  assert [(item[1], item[2]) for item in events if item[0] == "write"] == [(pinned, b"\x18"), (pinned, b"d")]
  assert ("inheritable", pinned, False) in events
  assert events.index(("attrs", 0)) < next(index for index, item in enumerate(events) if item[0] == "write")
  assert events.index(("poll", 0)) < events.index(("close", pinned))
  assert [item for item in events if item[0] == "close"] == [("close", pinned)]
  assert ("blocking", pinned, True) in events
  geometry.os.close(master)
  assert events.index(("close", pinned)) < events.index(("close", master))


@pytest.mark.parametrize("kind", ["dead", "reused", "unknown_pty", "fd_mismatch", "not_raw", "nonzero", "timeout", "pump_timeout", "invalid_write"])
def test_detach_refuses_uncertain_source_or_exit_without_kill(geometry, client, monkeypatch, kind):
  process, master, pinned, state, pump = client
  if kind == "dead":
    process.returncode = 0
  elif kind == "reused":
    starts = iter([456, 457])
    monkeypatch.setattr(geometry, "_process_start", lambda pid: next(starts))
  elif kind == "unknown_pty":
    state["mode"] = stat.S_IFREG
    state["tty"] = False
  elif kind == "fd_mismatch":
    actual = geometry.os.fstat
    def fstat(fd):
      value = actual(fd)
      if fd == pinned:
        value.st_rdev += 1
      return value
    monkeypatch.setattr(geometry.os, "fstat", fstat)
  elif kind == "not_raw":
    state["raw_after"] = 1_000_000
  elif kind == "nonzero":
    state["exit_code"] = 1
  elif kind == "timeout":
    state["exit_code"] = None
  elif kind == "pump_timeout":
    def pump():
      state["clock"] += 6
  else:
    monkeypatch.setattr(geometry.os, "write", lambda *args: 0)
  with pytest.raises(geometry.GeometryError):
    geometry.detach_owned_client(process, master, pump=pump, timeout=0.05)
  assert [item for item in state["events"] if item[0] == "close"] == [("close", pinned)]
  if kind in {"dead", "reused", "unknown_pty", "fd_mismatch", "not_raw", "pump_timeout"}:
    assert not state["writes"]
  if kind == "nonzero":
    assert process.returncode == 1
  assert state["clock"] <= 6.01


def test_detach_keeps_pinned_ofd_when_original_number_changes(geometry, client, monkeypatch):
  process, master, pinned, state, original_pump = client
  changed = []
  original_stat = geometry.os.fstat
  def fstat(fd):
    value = original_stat(fd)
    if fd == master and changed:
      value.st_rdev += 1
    return value
  monkeypatch.setattr(geometry.os, "fstat", fstat)
  def pump():
    changed.append(master)
    original_pump()
  geometry.detach_owned_client(process, master, pump=pump)
  assert geometry.os.fstat(master).st_rdev != geometry.os.fstat(pinned).st_rdev
  assert changed and all(item[1] == pinned for item in state["events"] if item[0] == "write")
  assert ("close", master) not in state["events"]


@pytest.mark.parametrize("timeout", [0, -1, 6, True, float("inf")])
def test_detach_invalid_deadline_never_writes(geometry, client, timeout):
  process, master, pinned, state, pump = client
  with pytest.raises(geometry.GeometryError):
    geometry.detach_owned_client(process, master, pump=pump, timeout=timeout)
  assert not state["writes"]
