#!/usr/bin/env python3
"""自有 fd 基础探针；prepare 不启动进程，native 必须另有授权。"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import selectors
import signal
import stat
import subprocess
import sys
import time

# 只作字面路径组合，controller 预留3以前不作自有路径解析。
ROOT = Path(__file__).parents[1]
NODE = Path("/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node")
PYTHON = Path("/usr/bin/python3.11")
BWRAP = Path("/bin/bwrap")
FIXTURE = ROOT / "tests/fixtures/pi/owner-fd-probe"
CASES = ("entry-and-node-exit", "controller-exit", "controller-kill", "node-kill", "wrong-fd", "high-fd-rejected")
MODULES = ("src/agentcfg/__init__.py", "src/agentcfg/storage.py", "src/agentcfg/paths.py")
SOURCES = ("scripts/pi-probe-owner-fd.py", "scripts/pi-probe-owner-fd.mjs", "scripts/pi-probe-owner-fd-facts.mjs", *MODULES, "tests/fixtures/pi/owner-fd-probe/manifest.json", "tests/fixtures/pi/owner-fd-probe/oracle.json")
ENV = {"HOME": "/work/home", "XDG_CONFIG_HOME": "/work/config", "XDG_DATA_HOME": "/work/data", "XDG_CACHE_HOME": "/work/cache", "XDG_STATE_HOME": "/work/state", "TMPDIR": "/work/tmp", "PATH": "/work/empty-bin", "LC_ALL": "C.UTF-8", "OWNER_FD_GUEST": "1"}
DIRECTORIES = {"home", "config", "data", "cache", "state", "tmp", "empty-bin", "lock-state"}
WORK_FILES = {"controller-info.json", "controller-result.json", "node-entry.json", "node.stdout", "node.stderr", "node-command", "controller-command", "state.json"}
MAX_LINE, MAX_BYTES, MAX_PLAN = 65536, 1024 * 1024, 1024 * 1024
SCOPE = "own-only-fd3/OFD; no SDK/DB/models/owner admission; namespace termination unknown"


class ProbeError(Exception): pass


def require(value):
  if not value: raise ProbeError("owner fd probe invalid")


def pairs(items):
  result = {}
  for key, value in items:
    require(key not in result); result[key] = value
  return result


def decode(raw):
  try:
    value = json.loads(raw.decode("utf8", "strict"), object_pairs_hook=pairs,
      parse_constant=lambda _: (_ for _ in ()).throw(ProbeError("owner fd JSON invalid")))
    require(type(value) is dict); return value
  except (UnicodeError, ValueError, RecursionError): raise ProbeError("owner fd JSON invalid") from None


def raw_json(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def equal(a, b): return raw_json(a) == raw_json(b)


def integer(value, minimum=0): return type(value) is int and minimum <= value <= 2**31 - 1


def private(path):
  info = path.lstat()
  require(path.is_absolute() and path.resolve(strict=True) == path and stat.S_ISDIR(info.st_mode)
    and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700)


def read(path, maximum=MAX_LINE):
  info = path.lstat()
  require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= maximum)
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
  try:
    opened = os.fstat(fd)
    require((info.st_dev, info.st_ino, info.st_size) == (opened.st_dev, opened.st_ino, opened.st_size))
    data = os.read(fd, maximum + 1); require(len(data) <= maximum)
    require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) ==
      (os.fstat(fd).st_dev, os.fstat(fd).st_ino, os.fstat(fd).st_size, os.fstat(fd).st_mtime_ns))
    current = path.lstat(); require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino))
    return data
  finally: os.close(fd)


def write_bytes(path, raw):
  require(type(raw) is bytes and len(raw) <= MAX_PLAN)
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
  try:
    os.fchmod(fd, 0o600); require(os.write(fd, raw) == len(raw)); os.fsync(fd)
  finally: os.close(fd)
  directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
  try: os.fsync(directory)
  finally: os.close(directory)


def write(path, value): write_bytes(path, raw_json(value))


def record(path):
  info = path.lstat(); require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
  return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": info.st_size}


def system():
  result = {}
  for name, path in (("python", PYTHON), ("node", NODE), ("bwrap", BWRAP)):
    actual = path.resolve(strict=True); info = actual.stat(); require(info.st_mode & 0o111)
    result[name] = {"path": str(actual), "file": record(actual), "stat": [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_mtime_ns, info.st_ctime_ns]}
  for path in ("/usr", "/lib", "/lib64"):
    info = Path(path).stat(); require(stat.S_ISDIR(info.st_mode))
    result[path] = [info.st_dev, info.st_ino, info.st_mode, info.st_uid]
  return result


def material():
  require({p.name for p in FIXTURE.iterdir()} == {"manifest.json", "oracle.json"})
  manifest = decode((FIXTURE / "manifest.json").read_bytes())
  require(equal(manifest, {"schema": 1, "probe": "owner-fd-linux-x64", "python": "3.11", "node": "24.14.0", "sources": list(SOURCES)}))
  return {"sources": {name: record(ROOT / name) for name in SOURCES}, "system": system()}


def invocation(case, work):
  require(case in CASES and work.is_absolute())
  argv = [str(BWRAP), "--unshare-all", "--cap-drop", "ALL", "--die-with-parent", "--new-session",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
    "--ro-bind", str(PYTHON), "/usr/bin/python3.11", "--ro-bind", str(NODE), "/node", "--dir", "/probe", "--dir", "/probe/modules", "--dir", "/probe/modules/agentcfg",
    "--ro-bind", str(ROOT / "scripts/pi-probe-owner-fd.py"), "/probe/worker.py",
    "--ro-bind", str(ROOT / "scripts/pi-probe-owner-fd.mjs"), "/probe/worker.mjs",
    "--ro-bind", str(ROOT / "scripts/pi-probe-owner-fd-facts.mjs"), "/probe/facts.mjs"]
  for name in MODULES: argv.extend(["--ro-bind", str(ROOT / name), "/probe/modules/agentcfg/" + Path(name).name])
  argv.extend(["--bind", str(work), "/work", "--remount-ro", "/", "--chdir", "/work"])
  for key, value in ENV.items(): argv.extend(["--setenv", key, value])
  argv.extend([str(PYTHON), "-I", "-S", "-B", "/probe/worker.py", "guest-driver", "--case", case])
  return {"argv": argv, "env": {}}


def plan(directory):
  return {"schema": 1, "probe": "owner-fd-linux-x64", "cases": list(CASES), "nativeAuthorized": False, "nativeStarted": False,
    "material": material(), "invocations": {case: invocation(case, directory / case / "work") for case in CASES},
    "limits": {"caseSeconds": 15, "totalSeconds": 120, "stdoutBytes": MAX_LINE, "combinedBytes": MAX_BYTES}, "scope": SCOPE}


def prepare(directory):
  private(directory); require(not list(directory.iterdir())); value = plan(directory); write(directory / "plan.json", value); return value


def binding(info):
  require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)
  return {"device": str(info.st_dev), "inode": str(info.st_ino), "uid": info.st_uid, "mode": 0o600, "nlink": 1}


def validate_binding(value):
  require(type(value) is dict and set(value) == {"device", "inode", "uid", "mode", "nlink"})
  for field in ("device", "inode"):
    text = value[field]; require(type(text) is str and text.isascii() and text.isdecimal() and str(int(text)) == text and int(text) <= 2**64 - 1)
  require(int(value["inode"]) > 0 and integer(value["uid"]) and type(value["mode"]) is int and value["mode"] == 0o600 and type(value["nlink"]) is int and value["nlink"] == 1)


def proc_stat(base):
  fd = os.open(base / "stat", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
  try:
    raw = os.read(fd, 4097); require(len(raw) <= 4096)
    return raw.decode("utf8", "strict")
  finally: os.close(fd)


def proc(pid):
  require(integer(pid, 1)); base = Path("/proc") / str(pid)
  raw = proc_stat(base); split = raw.rfind(")"); fields = raw[split + 2:].split()
  require(raw.startswith(str(pid) + " (") and len(fields) >= 20)
  return {"pid": pid, "start": fields[19], "uid": base.stat().st_uid, "state": fields[0],
    "namespace": os.readlink(base / "ns/pid"), "exe": os.readlink(base / "exe")}


def birth(pid):
  value = proc(pid); require(value["state"] not in ("Z", "X")); value.pop("state"); return value


def validate_birth(value):
  require(type(value) is dict and set(value) == {"pid", "start", "uid", "namespace", "exe"})
  require(integer(value["pid"], 1) and integer(value["uid"]) and type(value["start"]) is str and value["start"].isascii() and value["start"].isdecimal())
  require(type(value["namespace"]) is str and value["namespace"].startswith("pid:[") and value["namespace"].endswith("]")
    and value["namespace"][5:-1].isascii() and value["namespace"][5:-1].isdecimal())
  require(type(value["exe"]) is str and value["exe"] in (str(PYTHON), "/node"))


def ready(fd):
  poll = select.poll(); poll.register(fd, select.POLLIN); events = poll.poll(0)
  require(all(not mask & (select.POLLERR | select.POLLNVAL) for _, mask in events))
  return any(mask & (select.POLLIN | select.POLLHUP) for _, mask in events)


def target(pid):
  before = birth(pid); fd = os.pidfd_open(pid, 0)
  try: require(equal(before, birth(pid)) and not ready(fd)); return before, fd
  except BaseException: os.close(fd); raise


def alive(expected, fd):
  return not ready(fd) and equal(birth(expected["pid"]), expected)


def exit_seen(expected, fd):
  if not ready(fd): return False
  base = Path("/proc") / str(expected["pid"])
  try:
    # Z 阶段不补造不可读的 exe/ns；两次 birth stat 与中间 uid 必须一致。
    first = proc_stat(base); uid = base.stat().st_uid
    second = proc_stat(base); second_uid = base.stat().st_uid
  except FileNotFoundError: return not base.exists()
  def zombie(raw):
    tail = raw[raw.rfind(")") + 2:].split()
    return raw.startswith(str(expected["pid"]) + " (") and len(tail) >= 20 and tail[0] == "Z" and tail[19] == expected["start"]
  return uid == second_uid == expected["uid"] and zombie(first) and zombie(second)


def wait_for(call, deadline):
  while time.monotonic() < deadline:
    result = call()
    if result: return result
    time.sleep(0.01)
  raise ProbeError("owner fd deadline unknown")


def load_when(path, deadline):
  def current():
    try: return decode(read(path))
    except FileNotFoundError: return None
  return wait_for(current, deadline)


def reserve_decision(fd): return type(fd) is int and fd == 3


def high_decision(fd): return type(fd) is int and fd == 64


def guest_environment():
  require(sys.platform == "linux" and sys.version_info[:2] == (3, 11) and platform.machine() == "x86_64" and os.O_CLOEXEC == 0o2000000)
  pieces = platform.release().split("."); require(len(pieces) >= 2 and tuple(int(p) for p in pieces[:2]) >= (5, 3))
  require(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal") and os.environ.get("OWNER_FD_GUEST") == "1")
  require(all(os.environ.get(k) == v for k, v in ENV.items()))
  require(str(Path(__file__)) == "/probe/worker.py" and sys.flags.isolated == 1 and sys.flags.no_site == 1 and sys.flags.dont_write_bytecode == 1)


def private_output(path):
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
  try: os.fchmod(fd, 0o600); return os.fdopen(fd, "wb", buffering=0)
  except BaseException: os.close(fd); raise


def guest_controller(case):
  # 先预留低槽；未知3不可关闭/覆盖。此函数默认测试不执行。
  slot = os.open("/dev/null", os.O_RDWR | os.O_CLOEXEC)
  if not reserve_decision(slot): os.close(slot); raise ProbeError("owner fd slot unavailable")
  high = None
  try:
    guest_environment(); sys.path.insert(0, "/probe/modules")
    from agentcfg.storage import Tree, instance_lock
    require(case in CASES and os.getpid() != 1)
    with Tree(Path("/work/lock-state"), create=False) as tree, instance_lock(tree) as lock:
      original = binding(os.fstat(lock)); require(equal(original, binding(os.stat("/work/lock-state/instance.lock", follow_symlinks=False))))
      if case == "high-fd-rejected":
        high = fcntl.fcntl(lock, fcntl.F_DUPFD_CLOEXEC, 64)
        if not high_decision(high): os.close(high); high = None; raise ProbeError("owner fd high slot unavailable")
        passed = (64,)
      else:
        if case != "wrong-fd": os.dup2(lock, 3, inheritable=False)
        passed = (3,)
      with private_output("/work/node.stdout") as stdout, private_output("/work/node.stderr") as stderr:
        launches = 0
        child = subprocess.Popen(["/node", "/probe/worker.mjs", "--entry", json.dumps(original, separators=(",", ":"))],
          stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=ENV, close_fds=True, pass_fds=passed, shell=False)
        launches += 1
        write(Path("/work/controller-info.json"), {"schema": 1, "nodePid": child.pid, "nodeLaunches": launches, "lock": original})
        end = time.monotonic() + 14; status = None
        while time.monotonic() < end:
          if child.poll() is not None and status is None:
            status = child.wait(); write(Path("/work/controller-result.json"), {"schema": 1, "nodeExitCode": status})
          try:
            command = read(Path("/work/controller-command"), 16); require(command == b"exit\n"); break
          except FileNotFoundError: time.sleep(0.01)
        else: raise ProbeError("owner fd controller timeout")
        require(equal(original, binding(os.fstat(lock))) and equal(original, binding(os.stat("/work/lock-state/instance.lock", follow_symlinks=False))))
  finally:
    if high is not None: os.close(high)
    os.close(slot)


def compete(expected):
  path = Path("/work/lock-state/instance.lock")
  require(equal(binding(path.lstat()), expected))
  fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
  try:
    require(equal(binding(os.fstat(fd)), expected))
    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); result = "free"
    except OSError as error:
      if error.errno not in (errno.EAGAIN, errno.EACCES): raise
      result = "busy"
    require(equal(binding(os.fstat(fd)), expected) and equal(binding(path.lstat()), expected)); return result
  finally: os.close(fd)


def guest_driver(case):
  guest_environment(); require(case in CASES); end = time.monotonic() + 14
  driver_birth = birth(os.getpid()); validate_birth(driver_birth)
  require(driver_birth["pid"] == os.getpid() and driver_birth["exe"] == str(PYTHON))
  controller = subprocess.Popen([str(PYTHON), "-I", "-S", "-B", "/probe/worker.py", "guest-controller", "--case", case],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=ENV, close_fds=True, shell=False)
  controller_fd = node_fd = None
  try:
    controller_birth, controller_fd = target(controller.pid)
    def qualify(value, pid, executable):
      validate_birth(value)
      require(value["pid"] == pid and value["pid"] != driver_birth["pid"]
        and value["exe"] == executable and value["uid"] == driver_birth["uid"] and value["namespace"] == driver_birth["namespace"])
    qualify(controller_birth, controller.pid, str(PYTHON)); require(controller.pid != 1)
    info = load_when(Path("/work/controller-info.json"), end)
    require(set(info) == {"schema", "nodePid", "nodeLaunches", "lock"} and type(info["schema"]) is int and info["schema"] == 1 and type(info["nodeLaunches"]) is int and info["nodeLaunches"] == 1)
    validate_binding(info["lock"]); require(integer(info["nodePid"], 1))
    node_birth, node_fd = target(info["nodePid"])
    qualify(node_birth, info["nodePid"], "/node"); require(node_birth["pid"] != controller_birth["pid"])
    def chain():
      require(equal(birth(driver_birth["pid"]), driver_birth))
      qualify(controller_birth, controller.pid, str(PYTHON)); require(controller.pid != 1)
      qualify(node_birth, info["nodePid"], "/node"); require(node_birth["pid"] != controller_birth["pid"])
    chain()
    entry = load_when(Path("/work/node-entry.json"), end); cuts = []
    def cut(name, expected_controller, expected_node, controller_exit=False, node_exit=False):
      chain()
      controller_alive = alive(controller_birth, controller_fd) if expected_controller else False
      node_alive = alive(node_birth, node_fd) if expected_node else False
      ce = exit_seen(controller_birth, controller_fd) if controller_exit else False
      ne = exit_seen(node_birth, node_fd) if node_exit else False
      require(controller_alive == expected_controller and node_alive == expected_node and ce == controller_exit and ne == node_exit)
      locked = compete(info["lock"]); require(locked == ("free" if name == "last-exit" else "busy"))
      cuts.append({"name": name, "lock": locked, "controllerAlive": controller_alive, "nodeAlive": node_alive, "controllerExit": ce, "nodeExit": ne})
    cut("entry", True, True)
    node_status = None
    if case in ("controller-exit", "controller-kill"):
      require(alive(controller_birth, controller_fd) and alive(node_birth, node_fd)); chain()
      if case == "controller-kill": signal.pidfd_send_signal(controller_fd, signal.SIGKILL)
      else: write_bytes(Path("/work/controller-command"), b"exit\n")
      controller.wait(timeout=max(0.01, end - time.monotonic()))
      wait_for(lambda: exit_seen(controller_birth, controller_fd), end)
      cut("controller-exit-node-alive", False, True, controller_exit=True)
      write_bytes(Path("/work/node-command"), b"exit\n")
      wait_for(lambda: exit_seen(node_birth, node_fd), end)
      cut("last-exit", False, False, controller_exit=True, node_exit=True)
    else:
      require(alive(controller_birth, controller_fd) and alive(node_birth, node_fd)); chain()
      if case == "node-kill": signal.pidfd_send_signal(node_fd, signal.SIGKILL)
      else: write_bytes(Path("/work/node-command"), b"exit\n")
      status = load_when(Path("/work/controller-result.json"), end)
      require(set(status) == {"schema", "nodeExitCode"} and type(status["schema"]) is int and status["schema"] == 1 and type(status["nodeExitCode"]) is int)
      node_status = status["nodeExitCode"]; wait_for(lambda: exit_seen(node_birth, node_fd), end)
      cut("node-exit-controller-alive", True, False, node_exit=True)
      write_bytes(Path("/work/controller-command"), b"exit\n")
      controller.wait(timeout=max(0.01, end - time.monotonic()))
      wait_for(lambda: exit_seen(controller_birth, controller_fd), end)
      cut("last-exit", False, False, controller_exit=True, node_exit=True)
    errors = controller.stderr.read(MAX_LINE + 1); require(not errors)
    require(not read(Path("/work/node.stderr"), MAX_LINE))
    node_output = read(Path("/work/node.stdout")); require(node_output.count(b"\n") == 1 and node_output.endswith(b"\n") and equal(decode(node_output), entry))
    chain()
    frame = {"schema": 1, "case": case, "driver": driver_birth, "controller": controller_birth, "node": node_birth,
      "lock": info["lock"], "nodeLaunches": info["nodeLaunches"], "entry": entry, "cuts": cuts,
      "controllerExitCode": controller.returncode, "nodeExitCode": node_status}
    write(Path("/work/state.json"), frame); sys.stdout.buffer.write(raw_json(frame)); sys.stdout.buffer.flush()
  finally:
    if controller_fd is not None: os.close(controller_fd)
    if node_fd is not None: os.close(node_fd)
    if controller.stderr: controller.stderr.close()


def oracle(case, value, exit_code):
  expected = decode((FIXTURE / "oracle.json").read_bytes()); require(set(expected) == {"schema", "cases"} and type(expected["schema"]) is int and expected["schema"] == 1 and set(expected["cases"]) == set(CASES))
  require(type(value) is dict and set(value) == {"schema", "case", "driver", "controller", "node", "lock", "nodeLaunches", "entry", "cuts", "controllerExitCode", "nodeExitCode"})
  require(type(exit_code) is int and exit_code == 0 and type(value["schema"]) is int and value["schema"] == 1 and value["case"] == case)
  for name in ("driver", "controller", "node"): validate_birth(value[name])
  require(value["controller"]["pid"] != 1 and len({value[n]["pid"] for n in ("driver", "controller", "node")}) == 3)
  require(value["driver"]["exe"] == value["controller"]["exe"] == str(PYTHON) and value["node"]["exe"] == "/node")
  require(len({value[n]["namespace"] for n in ("driver", "controller", "node")}) == 1 and len({value[n]["uid"] for n in ("driver", "controller", "node")}) == 1)
  validate_binding(value["lock"]); require(value["lock"]["uid"] == value["driver"]["uid"])
  entry = value["entry"]; require(type(entry) is dict and set(entry) == {"schema", "kind", "accepted", "cloexec", "flags", "descendantSpawns", "descendantMatches", "descendantExitCode"})
  fixed = expected["cases"][case]
  for key in ("nodeLaunches", "cuts", "controllerExitCode", "nodeExitCode"): require(equal(value[key], fixed[key]))
  require(type(entry["schema"]) is int and entry["schema"] == 1 and entry["kind"] == "entry")
  for key, wanted in fixed["entry"].items(): require(equal(entry[key], wanted))
  if entry["accepted"]:
    flags = entry["flags"]; require(type(flags) is str and flags and len(flags) <= 22 and all(c in "01234567" for c in flags) and int(flags, 8) <= 2**64 - 1 and int(flags, 8) & 0o2000000)
  else: require(entry["flags"] is None)
  return value


def post_work(work, case):
  private(work); names = {p.name for p in work.iterdir()}
  optional = {"controller-result.json", "node-command", "controller-command"}
  selected = {"node-command"} if case == "controller-kill" else {"controller-command"}
  if case == "controller-exit": selected.add("node-command")
  if case not in ("controller-exit", "controller-kill"):
    selected.add("controller-result.json")
    if case != "node-kill": selected.add("node-command")
  require(names == DIRECTORIES | (WORK_FILES - optional) | selected)
  total = 0
  for p in work.iterdir():
    if p.name in DIRECTORIES:
      private(p)
      if p.name == "lock-state":
        require({q.name for q in p.iterdir()} == {"instance.lock"}); binding((p / "instance.lock").lstat())
      else: require(not list(p.iterdir()))
    else:
      data = read(p, MAX_LINE if p.suffix == ".json" else MAX_BYTES); total += len(data)
      if p.name.endswith("command"): require(data == b"exit\n")
  require(total <= MAX_BYTES)
  value = decode(read(work / "state.json")); oracle(case, value, 0)
  require(equal(decode(read(work / "node-entry.json")), value["entry"]))
  require(equal(binding((work / "lock-state/instance.lock").lstat()), value["lock"]))
  require(equal(decode(read(work / "controller-info.json")), {"schema": 1, "nodePid": value["node"]["pid"], "nodeLaunches": value["nodeLaunches"], "lock": value["lock"]}))
  require(not read(work / "node.stderr", MAX_LINE))
  node_raw = read(work / "node.stdout")
  require(node_raw.endswith(b"\n") and node_raw.count(b"\n") == 1 and equal(decode(node_raw), value["entry"]))
  if "controller-result.json" in selected:
    require(equal(decode(read(work / "controller-result.json")), {"schema": 1, "nodeExitCode": value["nodeExitCode"]}))


def post_case(directory, case, result_file=True):
  private(directory); names = {"work", "invocation.json", "stdout.raw", "stderr.raw"} | ({"case-result.json"} if result_file else set())
  require({p.name for p in directory.iterdir()} == names)
  for name in names - {"work"}: read(directory / name, MAX_BYTES)
  post_work(directory / "work", case)


def row(case): return {"case": case, "started": False, "pid": None, "exitCode": None, "outcome": "not-run", "phase": "setup", "namespaceTermination": "unknown"}


def run_case(case, directory, deadline, result):
  until = min(deadline, time.monotonic() + 15)
  private(directory); require(not list(directory.iterdir())); work = directory / "work"; work.mkdir(mode=0o700)
  for name in DIRECTORIES: (work / name).mkdir(mode=0o700)
  selected = invocation(case, work); write(directory / "invocation.json", selected)
  process = None; files = {}; output = {"stdout": bytearray(), "stderr": bytearray()}; result["phase"] = "launch"
  try:
    for name in output: files[name] = os.open(directory / (name + ".raw"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    process = subprocess.Popen(selected["argv"], env={}, cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, shell=False, start_new_session=True)
    result.update(started=True, pid=process.pid, phase="capture")
    with selectors.DefaultSelector() as selector:
      selector.register(process.stdout, selectors.EVENT_READ, "stdout"); selector.register(process.stderr, selectors.EVENT_READ, "stderr")
      while selector.get_map():
        require(time.monotonic() < until)
        for key, _ in selector.select(0.1):
          chunk = os.read(key.fileobj.fileno(), 65536)
          if not chunk: selector.unregister(key.fileobj); continue
          require(sum(map(len, output.values())) + len(chunk) <= MAX_BYTES); output[key.data].extend(chunk)
          require(os.write(files[key.data], chunk) == len(chunk))
          if key.data == "stdout": require(len(output[key.data]) <= MAX_LINE)
    process.wait(timeout=max(0.01, min(1, until - time.monotonic()))); result.update(exitCode=process.returncode, phase="oracle")
    require(not output["stderr"] and output["stdout"].endswith(b"\n") and output["stdout"].count(b"\n") == 1)
    value = decode(bytes(output["stdout"])); state = decode(read(work / "state.json")); require(equal(value, state))
    oracle(case, value, process.returncode); oracle(case, state, process.returncode); post_work(work, case)
    result.update(outcome="observed", phase="complete")
  except (Exception, KeyboardInterrupt): result["outcome"] = "failed" if result["started"] else "not-run"
  finally:
    failure = False
    try:
      if process is not None:
        if process.poll() is None:
          try: os.killpg(process.pid, signal.SIGTERM)
          except ProcessLookupError: pass
          try: process.wait(timeout=1)
          except subprocess.TimeoutExpired:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
        result["exitCode"] = process.poll()
        for stream in (process.stdout, process.stderr):
          if stream: stream.close()
    except OSError: failure = True
    for fd in files.values():
      try: os.fsync(fd)
      except OSError: failure = True
      finally:
        try: os.close(fd)
        except OSError: failure = True
    try: post_case(directory, case, False)
    except (OSError, ProbeError): failure = True
    if failure: result.update(outcome="failed" if result["started"] else "not-run", phase="persistence")
    try: write(directory / "case-result.json", result); post_case(directory, case)
    except (OSError, ProbeError): failure = True; result.update(outcome="failed" if result["started"] else "not-run", phase="persistence")
    if failure: raise ProbeError("owner fd capture persistence unknown")
  return result


def run(directory):
  private(directory); require({p.name for p in directory.iterdir()} == {"plan.json"})
  prepared = decode(read(directory / "plan.json", MAX_PLAN)); require(equal(prepared, plan(directory)))
  write(directory / "started.json", {"schema": 1, "planSha256": hashlib.sha256(read(directory / "plan.json", MAX_PLAN)).hexdigest(), "nativeRequested": True})
  results = []; failed = False; intact = False; end = time.monotonic() + 120
  try:
    for case in CASES:
      current = row(case); results.append(current); child = directory / case; child.mkdir(mode=0o700)
      if any(v["outcome"] != "observed" for v in results[:-1]): current["phase"] = "not-run"
      else:
        require(equal(prepared["material"], material()) and equal(prepared["invocations"][case], invocation(case, child / "work")))
        run_case(case, child, end, current)
        current["phase"] = "material"
        require(equal(prepared["material"], material()))
        if current["outcome"] == "observed": current["phase"] = "complete"
  except (Exception, KeyboardInterrupt):
    failed = True
    if results and results[-1]["started"]: results[-1].update(outcome="failed")
  finally:
    for case in CASES[len(results):]: results.append(row(case))
    try: intact = equal(prepared["material"], material())
    except Exception: pass
    write(directory / "execution.json", {"schema": 1, "cases": results, "parentFailed": failed, "materialIntact": intact, "namespaceTermination": "unknown"})
  require({p.name for p in directory.iterdir()} == {"plan.json", "started.json", "execution.json", *CASES})
  for result in results:
    private(directory / result["case"])
    if result["started"]: post_case(directory / result["case"], result["case"])
    else: require(not list((directory / result["case"]).iterdir()))
  return 0 if not failed and intact and all(v["outcome"] == "observed" for v in results) else 1


class Parser(argparse.ArgumentParser):
  def error(self, _): raise ProbeError("owner fd arguments invalid")


def main(argv=None):
  parser = Parser(allow_abbrev=False); parser.add_argument("action", choices=("prepare", "run-native", "guest-driver", "guest-controller"))
  parser.add_argument("--directory"); parser.add_argument("--case", choices=CASES); parser.add_argument("--native-owner-fd-probe", action="store_true")
  try:
    args = parser.parse_args(argv)
    if args.action.startswith("guest-"):
      require(args.directory is None and args.case is not None and not args.native_owner_fd_probe)
      if args.action == "guest-driver": guest_driver(args.case)
      else: guest_controller(args.case)
      return 0
    require(args.directory is not None and args.case is None); directory = Path(args.directory)
    if args.action == "prepare": require(not args.native_owner_fd_probe); prepare(directory); return 0
    require(args.native_owner_fd_probe); return run(directory)
  except (Exception, KeyboardInterrupt): print("owner fd probe execution or persistence unknown", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
