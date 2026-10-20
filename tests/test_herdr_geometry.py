import importlib.util
import json
import os
from pathlib import Path
import pytest


@pytest.fixture
def geometry():
  path = Path(__file__).parents[1] / "tools/bench/client_geometry.py"
  spec = importlib.util.spec_from_file_location("herdr_geometry_test", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def layout():
  rect = {"x": 0, "y": 0, "width": 94, "height": 39}
  return {"type": "pane_layout", "layout": {"workspace_id": "w1", "tab_id": "t1", "zoomed": False,
    "area": rect, "focused_pane_id": "w1:p1", "panes": [{"pane_id": "w1:p1", "focused": True, "rect": dict(rect)}], "splits": []}}


@pytest.fixture
def probe(geometry, tmp_path, monkeypatch):
  control = tmp_path / "control"
  control.mkdir(mode=0o700)
  class Process:
    pid = 123
    def poll(self):
      return None
  monkeypatch.setattr(geometry, "_process_start", lambda pid: 456)
  monkeypatch.setattr(geometry.os, "get_blocking", lambda fd: True)
  monkeypatch.setattr(geometry.os, "set_blocking", lambda fd, value: None)
  monkeypatch.setattr(geometry.os, "get_terminal_size", lambda fd: os.terminal_size((120, 40)))
  monkeypatch.setattr(geometry.termios, "tcgetattr", lambda fd: [0] * 7)
  buffer = bytearray()
  def write(fd, data):
    count = min(len(data), 7)
    buffer.extend(data[:count])
    if buffer.endswith(b"\n"):
      _, run, nonce = buffer.decode().strip().split(":")
      path = control / ("w1:p1.input-" + nonce + ".json")
      path.write_text(json.dumps({"run_id": run, "pane_id": "w1:p1", "nonce": nonce,
        "size": {"cols": 93, "rows": 39}, "phase": "measure"}))
      path.chmod(0o600)
    return count
  monkeypatch.setattr(geometry.os, "write", write)
  def invoke(**kwargs):
    args = dict(run_id="a" * 32, pane_id="w1:p1", control_dir=control, cols=120, rows=40,
      layout=layout, pump=lambda: None)
    args.update(kwargs)
    return geometry.probe_record_client(Process(), 11, **args)
  return invoke, control


def test_valid_partial_writes_and_pure_verify(geometry, probe):
  invoke, _ = probe
  frame = invoke()
  assert frame["client"] == {"pid": 123, "starttime": 456}
  assert geometry.verify_frame(frame) == frame


def test_probe_waits_for_raw_mode_before_sending_input(geometry, probe, monkeypatch):
  states = iter([geometry.termios.ICANON | geometry.termios.ECHO, geometry.termios.ECHO, 0])
  checks = []
  def attrs(fd):
    value = next(states)
    checks.append(value)
    return [0, 0, 0, value, 0, 0, []]
  monkeypatch.setattr(geometry.termios, "tcgetattr", attrs)
  write = geometry.os.write
  def checked_write(fd, data):
    assert checks[-1] == 0
    return write(fd, data)
  monkeypatch.setattr(geometry.os, "write", checked_write)
  assert probe[0]()["client"]["pid"] == 123
  assert len(checks) == 3


def test_non_raw_client_times_out_without_input(geometry, probe, monkeypatch):
  monkeypatch.setattr(geometry.termios, "tcgetattr", lambda fd: [0, 0, 0, geometry.termios.ICANON, 0, 0, []])
  monkeypatch.setattr(geometry.os, "write", lambda *args: pytest.fail("input before raw mode"))
  clock = iter([0, 0.1, 6])
  monkeypatch.setattr(geometry.time, "monotonic", lambda: next(clock))
  with pytest.raises(geometry.GeometryError, match="timeout"):
    probe[0]()


def test_empty_receipt_waits_for_first_write_but_bad_content_fails(geometry, tmp_path):
  path = tmp_path / "receipt.json"
  path.touch(mode=0o600)
  directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
  try:
    with pytest.raises(FileNotFoundError):
      geometry._read_receipt(directory, path.name)
    path.write_text('{"ready":true}')
    assert geometry._read_receipt(directory, path.name) == {"ready": True}
    path.write_text("broken")
    with pytest.raises(json.JSONDecodeError):
      geometry._read_receipt(directory, path.name)
    path.write_text("")
    path.chmod(0o644)
    with pytest.raises(geometry.GeometryError, match="unsafe_receipt"):
      geometry._read_receipt(directory, path.name)
  finally:
    os.close(directory)


@pytest.mark.parametrize("change", ["outer", "layout", "phase", "unknown", "nonce", "size", "clock"])
def test_frame_rejects_mismatch(geometry, probe, change):
  frame = probe[0]()
  if change == "outer": frame["outer"]["cols"] = 119
  if change == "layout": frame["layout"]["layout"]["zoomed"] = True
  if change == "phase": frame["input"]["phase"] = "warmup"
  if change == "unknown": frame["extra"] = True
  if change == "nonce": frame["input"]["nonce"] = "b" * 32
  if change == "size": frame["input"]["size"]["cols"] = 94
  if change == "clock": frame["end"] = frame["begin"] - 1
  with pytest.raises(geometry.GeometryError): geometry.verify_frame(frame)


def test_pid_reuse_and_dead_process(geometry, probe, monkeypatch):
  calls = iter([456, 456, 457])
  monkeypatch.setattr(geometry, "_process_start", lambda pid: next(calls))
  with pytest.raises(geometry.GeometryError): probe[0]()


def test_layout_failure_sanitized(geometry, probe):
  def fail(): raise OSError("private body")
  with pytest.raises(geometry.GeometryError) as error: probe[0](layout=fail)
  assert "private body" not in str(error.value)


@pytest.mark.parametrize("kind", ["mode", "replacement", "malformed", "phase"])
def test_receipt_failure(geometry, probe, monkeypatch, kind):
  invoke, control = probe
  write = geometry.os.write
  def changed(fd, data):
    n = write(fd, data)
    for path in control.glob("*.json"):
      if kind == "mode": path.chmod(0o644)
      if kind == "replacement":
        path.unlink(); path.symlink_to(control / "missing")
      if kind == "malformed": path.write_text('{"nonce": 1, "nonce": 2}')
      if kind == "phase":
        row = json.loads(path.read_text()); row["phase"] = "record"; path.write_text(json.dumps(row))
    return n
  monkeypatch.setattr(geometry.os, "write", changed)
  with pytest.raises(geometry.GeometryError): invoke()


def test_fake_clock_timeout_and_fd_restore(geometry, probe, monkeypatch):
  state = []
  clock = iter([0, 0.1, 6])
  monkeypatch.setattr(geometry.time, "monotonic", lambda: next(clock))
  monkeypatch.setattr(geometry.os, "set_blocking", lambda fd, value: state.append(value))
  with pytest.raises(geometry.GeometryError, match="timeout"):
    probe[0]()
  assert state == [False, True]


def test_outer_and_process_rejected_before_input(geometry, probe, monkeypatch):
  monkeypatch.setattr(geometry.os, "write", lambda *args: pytest.fail("unexpected input"))
  with pytest.raises(geometry.GeometryError, match="outer"):
    probe[0](cols=119)


def test_verify_malformed_structures_always_controlled(geometry):
  for frame in (None, [], {"phase": []}):
    with pytest.raises(geometry.GeometryError): geometry.verify_frame(frame)


def test_directory_and_receipt_descriptors_close_on_success(geometry, probe, monkeypatch):
  real_open, real_close = geometry.os.open, geometry.os.close
  opened, closed = [], []
  def track_open(*args, **kwargs):
    fd = real_open(*args, **kwargs); opened.append(fd); return fd
  def track_close(fd):
    closed.append(fd); return real_close(fd)
  monkeypatch.setattr(geometry.os, "open", track_open)
  monkeypatch.setattr(geometry.os, "close", track_close)
  probe[0]()
  assert len(opened) == 2 and sorted(opened) == sorted(closed)


def test_resize_owned_ui_pidfd_signal_and_close(geometry, monkeypatch):
  events = []
  class Process:
    pid = 123
    def poll(self): return None
  monkeypatch.setattr(geometry, "_process_start", lambda pid: 456)
  monkeypatch.setattr(geometry.os, "pidfd_open", lambda pid, flags: events.append(("open", pid, flags)) or 99)
  monkeypatch.setattr(geometry.os, "close", lambda fd: events.append(("close", fd)))
  monkeypatch.setattr(geometry.fcntl, "ioctl", lambda master, command, size: events.append(("resize", master, command, size)))
  monkeypatch.setattr(geometry.signal, "pidfd_send_signal", lambda *args: events.append(("signal",) + args))
  geometry.resize_owned_client(Process(), 11, 120, 40)
  assert events == [("open", 123, 0), ("resize", 11, geometry.termios.TIOCSWINSZ, geometry.struct.pack("HHHH", 40, 120, 0, 0)),
    ("signal", 99, geometry.signal.SIGWINCH, None, 0), ("close", 99)]


@pytest.mark.parametrize("kind", ["reused", "exited", "unsupported"])
def test_resize_refuses_uncertain_identity_no_signal(geometry, monkeypatch, kind):
  closed = []
  class Process:
    pid = 123
    def poll(self): return 0 if kind == "exited" else None
  starts = iter([456, 457])
  monkeypatch.setattr(geometry, "_process_start", lambda pid: next(starts))
  monkeypatch.setattr(geometry.os, "pidfd_open", lambda *args: 99)
  monkeypatch.setattr(geometry.os, "close", lambda fd: closed.append(fd))
  monkeypatch.setattr(geometry.signal, "pidfd_send_signal", lambda *args: pytest.fail("uncertain signal"))
  monkeypatch.setattr(geometry.fcntl, "ioctl", lambda *args: pytest.fail("uncertain resize"))
  if kind == "unsupported": monkeypatch.delattr(geometry.os, "pidfd_open")
  with pytest.raises(geometry.GeometryError): geometry.resize_owned_client(Process(), 11, 120, 40)
  assert closed == ([99] if kind == "reused" else [])
