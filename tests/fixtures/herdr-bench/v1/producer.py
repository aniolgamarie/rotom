#!/usr/bin/env python3
"""固定合成编辑器；只接受 checkout 配置和两阶段时钟 barrier。"""
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import stat
import sys
import time
import uuid


def canonical(value):
  return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def load_private(path):
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
    raise ValueError("unsafe fixture file")
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
  try:
    checked = os.fstat(fd)
    if (checked.st_dev, checked.st_ino) != (info.st_dev, info.st_ino):
      raise ValueError("fixture file replaced")
    def unique(pairs):
      result = {}
      for key, value in pairs:
        if key in result:
          raise ValueError("duplicate fixture field")
        result[key] = value
      return result
    value = json.loads(os.read(fd, 65537), object_pairs_hook=unique, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("invalid number")))
  finally:
    os.close(fd)
  return value


def _rename_noreplace(directory, temporary, destination):
  """只接受 Linux 原子不覆盖发布；缺能力时不尝试其他发布方式。"""
  if sys.platform != "linux":
    raise OSError(errno.ENOSYS, "atomic_publish_unavailable")
  try:
    rename = ctypes.CDLL(None, use_errno=True).renameat2
  except (AttributeError, OSError):
    raise OSError(errno.ENOSYS, "atomic_publish_unavailable") from None
  rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
  rename.restype = ctypes.c_int
  if rename(directory, os.fsencode(temporary), directory, os.fsencode(destination), 1) != 0:
    raise OSError(ctypes.get_errno(), "atomic_publish_failed")


def write_new(path, value):
  """完整写入/fsync 临时文件，再原子发布单链接新名，绝不覆盖。"""
  path = Path(path)
  directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  temporary = ".herdr-bench-" + uuid.uuid4().hex
  staged = False
  try:
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
      0o600, dir_fd=directory)
    staged = True
    with os.fdopen(fd, "wb") as stream:
      os.fchmod(stream.fileno(), 0o600)
      stream.write(canonical(value) + b"\n")
      stream.flush()
      os.fsync(stream.fileno())
    try:
      _rename_noreplace(directory, temporary, path.name)
    except OSError as error:
      if error.errno in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        raise ValueError("atomic_publish_unavailable") from None
      raise
    staged = False
    os.fsync(directory)
  finally:
    try:
      if staged:
        try:
          os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
          pass
    finally:
      os.close(directory)


def config(checkout, pane):
  value = load_private(checkout / ".rotom-bench-v1.json")
  required = {"version", "run_id", "mode", "seed", "control_dir", "config_digest"}
  if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - {"cpuacct_receipt"} or value["version"] != 1:
    raise ValueError("invalid fixture configuration")
  if (not isinstance(value["run_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", value["run_id"]) or
      value["mode"] not in {"idle", "output", "record"} or type(value["seed"]) is not int or not 0 <= value["seed"] < 2**64 or
      not re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", pane)):
    raise ValueError("invalid fixture identity")
  if "cpuacct_receipt" in value:
    receipt = value["cpuacct_receipt"]
    if not isinstance(receipt, str) or not Path(receipt).is_absolute():
      raise ValueError("invalid fixture configuration")
  expected = hashlib.sha256(canonical({k: v for k, v in value.items() if k != "config_digest"})).hexdigest()
  if value["config_digest"] != expected:
    raise ValueError("fixture configuration digest mismatch")
  control = Path(value["control_dir"])
  if not control.is_absolute() or control.is_symlink() or control.resolve() != control:
    raise ValueError("invalid fixture control path")
  info = control.lstat()
  if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
    raise ValueError("unsafe fixture control directory")
  return value, control


class RecordReader:
  """只读取固定合成协议；每次泵有界，避免输入淹没计量时钟。"""
  def __init__(self, control, run_id, pane):
    self.control, self.run_id, self.pane = control, run_id, pane
    self.pending = bytearray()
    self.seen = set()
    os.set_blocking(0, False)
    self.poller = select.poll()
    self.poller.register(0, select.POLLIN | select.POLLHUP | select.POLLERR)
    self.marker()

  def marker(self):
    # 只由 record reader 输出；刷新底部可见标记，不改变负载写入路径。
    remaining = b"RBREADY:" + self.run_id.encode("ascii") + b"\n"
    for _ in range(len(remaining)):
      written = os.write(1, remaining)
      if type(written) is not int or not 0 < written <= len(remaining):
        raise ValueError("fixture output closed")
      remaining = remaining[written:]
      if not remaining:
        return
    raise ValueError("fixture output closed")

  def pump(self, phase):
    if phase not in {"waiting", "warmup", "measure", "record"}:
      raise ValueError("invalid fixture input phase")
    for _ in range(16):
      if not self.poller.poll(0):
        return
      try:
        chunk = os.read(0, 4096)
      except BlockingIOError:
        return
      if not chunk:
        raise ValueError("fixture input closed")
      self.pending.extend(chunk)
      while b"\n" in self.pending:
        line, _, tail = self.pending.partition(b"\n")
        self.pending = bytearray(tail)
        matched = re.fullmatch(rb"RB:([a-f0-9]{32}):([a-f0-9]{32})", line)
        if not matched or matched[1].decode("ascii") != self.run_id:
          raise ValueError("unexpected synthetic input")
        nonce = matched[2].decode("ascii")
        if nonce in self.seen or len(self.seen) >= 4096:
          raise ValueError("unexpected synthetic input")
        size = os.get_terminal_size(1)
        if size.columns <= 0 or size.lines <= 0:
          raise ValueError("invalid fixture terminal size")
        write_new(self.control / (self.pane + ".input-" + nonce + ".json"),
                  {"run_id": self.run_id, "pane_id": self.pane, "nonce": nonce,
                   "size": {"cols": size.columns, "rows": size.lines}, "phase": phase})
        self.seen.add(nonce)
        self.marker()
      if len(self.pending) > 68:
        raise ValueError("unexpected synthetic input")


def wait_file(path, timeout=900, *, pump=None):
  end = time.monotonic() + timeout
  while not path.exists():
    if pump is not None:
      pump("waiting")
    if time.monotonic() >= end:
      raise ValueError("fixture barrier timeout")
    time.sleep(0.02)
  return load_private(path)


def barrier(control, run_id, phase, *, pump=None):
  value = wait_file(control / (phase + ".json"), pump=pump)
  if (set(value) != {"run_id", "phase", "start_ns"} or value["run_id"] != run_id or value["phase"] != phase or
      type(value["start_ns"]) is not int or value["start_ns"] <= 0):
    raise ValueError("invalid fixture barrier")
  return value["start_ns"]


def sleep_until(deadline_ns, interval, clock, sleep, pump=None):
  while True:
    if pump is not None:
      pump()
    remaining = deadline_ns - clock()
    if remaining <= 0:
      return
    sleep(min(interval, remaining / 1_000_000_000))


def window(mode, seed, phase, start_ns, *, clock=time.monotonic_ns, sleep=time.sleep, write=os.write, pump=None):
  seconds = 60 if phase == "warmup" else 300
  end_ns = start_ns + seconds * 1_000_000_000
  sleep_until(start_ns, 0.02, clock, sleep, (lambda: pump("waiting")) if pump else None)
  active_pump = (lambda: pump(phase)) if pump else None
  cpu = time.process_time()
  lines = count = 0
  blocked = 0
  if mode == "output":
    for tick in range(seconds * 512):
      due = start_ns + tick * 1_000_000_000 // 512
      now = clock()
      if due > now:
        sleep((due - now) / 1_000_000_000)
      if clock() >= end_ns:
        break
      prefix = f"{seed:016x}:{tick:016x}:".encode()
      line = prefix + b"x" * (127 - len(prefix)) + b"\n"
      begin = clock()
      remaining = line
      while remaining:
        written = write(1, remaining)
        if written <= 0:
          raise ValueError("fixture output closed")
        remaining = remaining[written:]
      completed = clock()
      blocked += max(0, completed - begin)
      if completed > end_ns:
        break
      lines += 1
      count += len(line)
  else:
    sleep_until(end_ns, 0.05, clock, sleep, active_pump)
  sleep_until(end_ns, 0.02, clock, sleep, active_pump)
  return {"phase": phase, "start_ns": start_ns, "end_ns": clock(), "lines": lines, "bytes": count,
          "cpu_seconds": time.process_time() - cpu, "backpressure_seconds": blocked / 1_000_000_000}


def main():
  value = control = None
  phase = "configuration"
  try:
    pane = os.environ.get("HERDR_PANE_ID", "")
    value, control = config(Path.cwd(), pane)
    cpuacct = None
    if "cpuacct_receipt" in value:
      phase = "cpuacct"
      # 只从固定仓库路径加载自有模块，不接受配置指定模块或指令。
      import importlib.util
      module_path = Path(__file__).resolve().parents[4] / "tools/bench/cpuacct.py"
      spec = importlib.util.spec_from_file_location("rotom_fixture_cpuacct", module_path)
      module = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(module)
      try:
        cpuacct = module.join_producer(value["cpuacct_receipt"])
      except module.CpuacctError:
        raise ValueError("fixture cpuacct failed") from None
    phase = "expected"
    reader = RecordReader(control, value["run_id"], pane) if value["mode"] == "record" else None
    pump = reader.pump if reader else None
    expected = wait_file(control / "expected.json", **({"pump": pump} if pump else {}))
    if (set(expected) != {"run_id", "panes"} or expected["run_id"] != value["run_id"] or
        not isinstance(expected["panes"], list) or len(set(expected["panes"])) != len(expected["panes"]) or pane not in expected["panes"]):
      raise ValueError("unexpected fixture pane")
    ready = {"run_id": value["run_id"], "pane_id": pane, "pid": os.getpid(), "config_digest": value["config_digest"]}
    if cpuacct is not None:
      ready["cpuacct"] = cpuacct
    write_new(control / (pane + ".ready.json"), ready)
    for phase in ("warmup", "measure"):
      start_ns = barrier(control, value["run_id"], phase, **({"pump": pump} if pump else {}))
      result = window(value["mode"], value["seed"], phase, start_ns, **({"pump": pump} if pump else {}))
      write_new(control / (pane + "." + phase + ".json"), {"run_id": value["run_id"], "pane_id": pane, "mode": value["mode"], **result})
    # record仅接受合成本轮nonce，不执行命令，不保存任意stdin。
    phase = "record" if value["mode"] == "record" else "idle"
    if reader is not None:
      while True:
        reader.pump("record")
        time.sleep(0.02)
    while True:
      time.sleep(60)
  except (OSError, ValueError, TypeError, KeyError) as error:
    if control is not None and value is not None:
      # 只记录固定错误类别，不保存异常正文或路径。
      known = {"sleep length must be non-negative": "negative_sleep", "fixture output closed": "output_closed",
               "unsafe fixture file": "unsafe_file", "fixture barrier timeout": "barrier_timeout",
               "invalid fixture barrier": "invalid_barrier", "atomic_publish_unavailable": "atomic_publish_unavailable"}
      code = "os_error" if isinstance(error, OSError) else known.get(str(error), "fixture_validation")
      try:
        write_new(control / (pane + ".failure.json"), {"run_id": value["run_id"], "pane_id": pane, "phase": phase, "error_code": code})
      except (OSError, ValueError, TypeError, KeyError):
        pass
    os.write(2, b"synthetic_fixture_failed\n")
    return 5


if __name__ == "__main__":
  raise SystemExit(main())
