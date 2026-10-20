"""Fixed synthetic proof for reviewed defaults, clean HOME/preferences and one pane.

Callers must establish those conditions before calling. This is not a probe for
arbitrary existing sessions. Only fixed record-producer nonces and the native
C-x+d UI detach sequence enter an owned PTY. Detach requires the fresh reviewed
managed configuration (C-x prefix, prefix+d detach); these bytes must never be
sent to a shell. Only the fixed readiness marker is matched in transient PTY
output; no other terminal content, clipboard or shell commands are inspected.
"""
import json
import fcntl
import signal
import struct
import termios
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid


class GeometryError(Exception):
  def __init__(self, reason):
    self.reason = reason
    super().__init__(reason)


def _require(condition, reason="invalid_geometry"):
  if not condition:
    raise GeometryError(reason)


def _keys(value, keys):
  _require(type(value) is dict and set(value) == set(keys), "invalid_fields")


def _integer(value, minimum=1):
  _require(type(value) is int and value >= minimum, "invalid_integer")


def _identity(value, pattern):
  _require(type(value) is str and re.fullmatch(pattern, value) is not None, "invalid_identity")


def _verify_frame(frame):
  """Recompute all fixed-default relationships; unknown fields fail closed."""
  _keys(frame, {"run_id", "pane_id", "nonce", "client", "outer", "layout", "input", "phase", "begin", "end"})
  for key in ("run_id", "nonce"):
    _identity(frame[key], r"[a-f0-9]{32}")
  _identity(frame["pane_id"], r"[A-Za-z0-9_:-]{1,128}")
  _require(frame["phase"] in ("waiting", "warmup", "measure", "record"), "invalid_phase")
  _keys(frame["client"], {"pid", "starttime"})
  for value in frame["client"].values(): _integer(value)
  _keys(frame["outer"], {"cols", "rows"})
  cols, rows = frame["outer"]["cols"], frame["outer"]["rows"]
  _integer(cols, 65); _integer(rows, 2)
  _require(cols <= 65535 and rows <= 65535)
  for key in ("begin", "end"):
    value = frame[key]
    _require(type(value) in (float, int) and math.isfinite(value) and value >= 0, "invalid_clock")
  _require(frame["end"] >= frame["begin"], "invalid_clock")
  response = frame["layout"]
  _keys(response, {"type", "layout"})
  _require(response["type"] == "pane_layout")
  layout = response["layout"]
  _keys(layout, {"workspace_id", "tab_id", "zoomed", "area", "focused_pane_id", "panes", "splits"})
  for key in ("workspace_id", "tab_id"):
    _identity(layout[key], r"[A-Za-z0-9_:-]{1,128}")
  _require(layout["zoomed"] is False and layout["focused_pane_id"] == frame["pane_id"])
  area = {"x": 0, "y": 0, "width": cols - 26, "height": rows - 1}
  _keys(layout["area"], area)
  for key in area: _integer(layout["area"][key], 0)
  _require(layout["area"] == area and type(layout["splits"]) is list and not layout["splits"])
  _require(type(layout["panes"]) is list and len(layout["panes"]) == 1)
  pane = layout["panes"][0]
  _keys(pane, {"pane_id", "focused", "rect"})
  _keys(pane["rect"], area)
  for key in area: _integer(pane["rect"][key], 0)
  _require(pane["pane_id"] == frame["pane_id"] and pane["focused"] is True and pane["rect"] == area)
  receipt = frame["input"]
  _keys(receipt, {"run_id", "pane_id", "nonce", "size", "phase"})
  for key in ("run_id", "pane_id", "nonce", "phase"):
    _require(receipt[key] == frame[key], "receipt_identity_mismatch")
  _keys(receipt["size"], {"cols", "rows"})
  for value in receipt["size"].values(): _integer(value)
  _require(receipt["size"] == {"cols": area["width"] - 1, "rows": area["height"]}, "producer_size_mismatch")
  return frame


def verify_frame(frame):
  """Validate strict structure and geometry without any I/O."""
  try:
    return _verify_frame(frame)
  except GeometryError:
    raise
  except Exception:
    raise GeometryError("invalid_geometry") from None


def _process_start(pid):
  raw = (Path("/proc") / str(pid) / "stat").read_text()
  # comm can contain spaces and parentheses; fields after final ')' begin at 3.
  return int(raw[raw.rindex(")") + 2:].split()[19])


def _fingerprint(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_receipt(directory, name):
  fd = None
  try:
    before = os.stat(name, dir_fd=directory, follow_symlinks=False)
    _require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600 and
      before.st_uid == os.getuid() and before.st_nlink == 1 and before.st_size <= 4096, "unsafe_receipt")
    # publisher 的 O_EXCL 创建先于首次写入；空文件仍属于有界等待期。
    if before.st_size == 0:
      raise FileNotFoundError
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    _require(_fingerprint(os.fstat(fd)) == _fingerprint(before), "receipt_replaced")
    raw = os.read(fd, 4097)
    _require(len(raw) == before.st_size, "receipt_changed")
    _require(_fingerprint(os.fstat(fd)) == _fingerprint(before) ==
      _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)), "receipt_changed")
    def unique(pairs):
      value = {}
      for key, item in pairs:
        _require(key not in value, "duplicate_field")
        value[key] = item
      return value
    return json.loads(raw, object_pairs_hook=unique,
      parse_constant=lambda _: (_ for _ in ()).throw(GeometryError("invalid_number")))
  finally:
    if fd is not None: os.close(fd)


def probe_record_client(process, master, *, run_id, pane_id, control_dir, cols, rows,
                        layout, pump, phase="measure", timeout=5):
  """Prove a single owned UI input path and exact default-desktop geometry."""
  directory = None
  was_blocking = None
  try:
    _identity(run_id, r"[a-f0-9]{32}")
    _identity(pane_id, r"[A-Za-z0-9_:-]{1,128}")
    _require(phase in ("waiting", "warmup", "measure", "record"), "invalid_phase")
    _integer(cols, 65); _integer(rows, 2); _integer(process.pid)
    _require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 5, "invalid_timeout")
    begin = time.monotonic(); deadline = begin + timeout
    _require(process.poll() is None, "client_exited")
    starttime = _process_start(process.pid)
    def source():
      _require(process.poll() is None and _process_start(process.pid) == starttime, "client_replaced")
      size = os.get_terminal_size(master)
      _require((size.columns, size.lines) == (cols, rows), "outer_size_mismatch")
    source()
    path = Path(control_dir)
    before = path.lstat()
    _require(stat.S_ISDIR(before.st_mode) and before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o700, "unsafe_control")
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    identity = (before.st_dev, before.st_ino)
    _require((os.fstat(directory).st_dev, os.fstat(directory).st_ino) == identity, "control_replaced")
    nonce = uuid.uuid4().hex
    was_blocking = os.get_blocking(master)
    os.set_blocking(master, False)
    payload = ("RB:" + run_id + ":" + nonce + "\n").encode("ascii")
    def step():
      _require(time.monotonic() < deadline, "geometry_timeout")
      pump()
    # Crossterm 切换 raw mode 时会清空输入；必须在它完成后才发送样本。
    while termios.tcgetattr(master)[3] & (termios.ICANON | termios.ECHO):
      source()
      step()
      time.sleep(0.005)
    while payload:
      step()
      try:
        count = os.write(master, payload)
      except BlockingIOError:
        time.sleep(0.005)
        continue
      _require(type(count) is int and 0 < count <= len(payload), "input_write_failed")
      payload = payload[count:]
    name = pane_id + ".input-" + nonce + ".json"
    while True:
      step()
      try:
        receipt = _read_receipt(directory, name)
        break
      except FileNotFoundError:
        time.sleep(0.005)
    response = layout()
    source()
    after = path.lstat()
    _require((after.st_dev, after.st_ino) == identity and stat.S_ISDIR(after.st_mode) and
      after.st_uid == os.getuid() and stat.S_IMODE(after.st_mode) == 0o700, "control_replaced")
    end = time.monotonic()
    _require(end <= deadline, "geometry_timeout")
    return verify_frame({"run_id": run_id, "pane_id": pane_id, "nonce": nonce,
      "client": {"pid": process.pid, "starttime": starttime}, "outer": {"cols": cols, "rows": rows},
      "layout": response, "input": receipt, "phase": phase, "begin": begin, "end": end})
  except GeometryError:
    raise
  except Exception:
    raise GeometryError("geometry_probe_failed") from None
  finally:
    try:
      if directory is not None: os.close(directory)
    finally:
      if was_blocking is not None:
        try:
          os.set_blocking(master, was_blocking)
        except OSError:
          raise GeometryError("descriptor_restore_failed") from None


def resize_owned_client(process, master, cols, rows):
  """Notify only the pinned owned UI; unavailable pidfd support fails closed."""
  pidfd = None
  try:
    _integer(cols); _integer(rows); _integer(process.pid)
    _require(cols <= 65535 and rows <= 65535, "invalid_outer_size")
    _require(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "pidfd_unavailable")
    _require(process.poll() is None, "client_exited")
    start = _process_start(process.pid)
    pidfd = os.pidfd_open(process.pid, 0)
    def source():
      _require(process.poll() is None and _process_start(process.pid) == start, "client_replaced")
    source()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    source()
    signal.pidfd_send_signal(pidfd, signal.SIGWINCH, None, 0)
    source()
  except GeometryError:
    raise
  except Exception:
    raise GeometryError("owned_client_resize_failed") from None
  finally:
    if pidfd is not None:
      os.close(pidfd)


def detach_owned_client(process, master, *, pump, timeout=5):
  """Detach one fresh managed UI through fixed keys, then require its actual exit 0."""
  pinned = None
  was_blocking = None
  succeeded = False
  try:
    _require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 5, "invalid_timeout")
    deadline = time.monotonic() + timeout
    _integer(master, 0); _integer(process.pid)
    pid = process.pid
    def identity(info):
      return (info.st_dev, info.st_ino, info.st_rdev, stat.S_IFMT(info.st_mode))
    before = os.fstat(master)
    pinned = os.dup(master)
    os.set_inheritable(pinned, False)
    original = identity(before)
    _require(identity(os.fstat(pinned)) == original and stat.S_ISCHR(before.st_mode) and os.isatty(pinned),
      "owned_client_detach_pty_unverified")
    _require(process.poll() is None, "owned_client_detach_client_exited")
    start = _process_start(pid)
    _integer(start)
    was_blocking = os.get_blocking(pinned)
    os.set_blocking(pinned, False)
    def live(allow_exit=False):
      _require(time.monotonic() < deadline, "owned_client_detach_timeout")
      _require(process.pid == pid and identity(os.fstat(pinned)) == original, "owned_client_detach_identity_changed")
      code = process.poll()
      if code is not None:
        _require(allow_exit, "owned_client_detach_client_exited")
        _require(type(code) is int and code == 0, "owned_client_detach_nonzero_exit")
        return False
      _require(_process_start(pid) == start, "owned_client_detach_identity_changed")
      return True
    def drain():
      _require(time.monotonic() < deadline, "owned_client_detach_timeout")
      pump()
      _require(time.monotonic() < deadline, "owned_client_detach_timeout")
    def pause():
      remaining = deadline - time.monotonic()
      _require(remaining > 0, "owned_client_detach_timeout")
      time.sleep(min(0.005, remaining))
    raw_flags = termios.ICANON | termios.ECHO
    while True:
      live()
      if not termios.tcgetattr(pinned)[3] & raw_flags:
        break
      drain()
      pause()
    payload = b"\x18d"
    while payload:
      drain()
      live()
      _require(not termios.tcgetattr(pinned)[3] & raw_flags, "owned_client_detach_not_raw")
      try:
        count = os.write(pinned, payload)
      except BlockingIOError:
        pause()
        continue
      _require(type(count) is int and 0 < count <= len(payload), "owned_client_detach_write_failed")
      payload = payload[count:]
    while live(allow_exit=True):
      drain()
      if live(allow_exit=True):
        pause()
    succeeded = True
  except GeometryError:
    raise
  except Exception:
    raise GeometryError("owned_client_detach_failed") from None
  finally:
    cleanup_failed = False
    if pinned is not None:
      if was_blocking is not None:
        try:
          os.set_blocking(pinned, was_blocking)
        except OSError:
          cleanup_failed = True
      try:
        os.close(pinned)
      except OSError:
        cleanup_failed = True
    if cleanup_failed and succeeded:
      raise GeometryError("owned_client_detach_descriptor_cleanup_failed") from None


def wait_owned_client_marker(process, master, *, run_id, pump, timeout=5):
  """Require the fixed run marker from a fresh owned UI; keep at most 39 tail bytes."""
  pinned = None
  succeeded = False
  try:
    _require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 5, "invalid_timeout")
    deadline = time.monotonic() + timeout
    _identity(run_id, r"[a-f0-9]{32}")
    _integer(master, 0); _integer(process.pid)
    pid = process.pid
    def identity(info):
      return (info.st_dev, info.st_ino, info.st_rdev, stat.S_IFMT(info.st_mode))
    before = os.fstat(master)
    pinned = os.dup(master)
    os.set_inheritable(pinned, False)
    original = identity(before)
    _require(identity(os.fstat(pinned)) == original and stat.S_ISCHR(before.st_mode) and os.isatty(pinned),
      "owned_client_marker_pty_unverified")
    _require(process.poll() is None, "owned_client_marker_client_exited")
    start = _process_start(pid)
    _integer(start)
    def source():
      _require(time.monotonic() < deadline, "owned_client_marker_timeout")
      _require(process.pid == pid and identity(os.fstat(pinned)) == original and
        process.poll() is None and _process_start(pid) == start, "owned_client_marker_identity_changed")
    marker = b"RBREADY:" + run_id.encode("ascii")
    tail = b""
    found = False
    def observe(fd, chunk):
      nonlocal tail, found
      if fd != master or found:
        return
      combined = tail + chunk
      found = marker in combined
      tail = b"" if found else combined[-(len(marker) - 1):]
    while not found:
      source()
      pump(observe)
      source()
      if not found:
        time.sleep(min(0.005, max(0, deadline - time.monotonic())))
    succeeded = True
  except GeometryError:
    raise
  except Exception:
    raise GeometryError("owned_client_marker_failed") from None
  finally:
    if pinned is not None:
      try:
        os.close(pinned)
      except OSError:
        if succeeded:
          raise GeometryError("owned_client_marker_descriptor_cleanup_failed") from None
