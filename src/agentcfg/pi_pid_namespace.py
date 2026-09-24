"""Linux 宿主与 Codex 的内核进程范围；PID 1 退出后内核终止该命名空间全部后代。"""
import json
import os
from pathlib import Path
import selectors
import secrets
import signal
import socket
import struct
import subprocess
import sys
import time

from .deployment import json_bytes
from .pi_catalog import validate
from .storage import Conflict, Tree


def namespace_record(processes, expected):
  with Tree(processes.record_root) as tree: raw = tree.read(processes._path(expected))
  if raw is None: return None
  try: value = json.loads(raw[0])
  except (ValueError, UnicodeError): raise Conflict("PID命名空间记录无效") from None
  if not isinstance(value, dict) or value.get("schema_version") != 3: return None
  try:
    if (len(raw[0]) > 65536 or raw[1] != 0o600 or type(value["schema_version"]) is not int or set(value) != {"schema_version", "mode", "leader", "wrapper", "terminated"}
        or value["mode"] != "pid-namespace" or value["leader"] != expected or type(value["terminated"]) is not bool): raise ValueError()
    validate("process-identity", value["leader"]); validate("process-identity", value["wrapper"])
    wrapper = value["wrapper"]
    if (expected["platform"] != "linux" or wrapper["platform"] != "linux" or expected["namespace"] == wrapper["namespace"]
        or expected["boot_id"] != wrapper["boot_id"] or expected["uid"] != wrapper["uid"] or expected["uid"] != os.geteuid()
        or expected["ppid"] != wrapper["pid"] or expected["pid"] == wrapper["pid"] or wrapper["pid"] != wrapper["pgid"]): raise ValueError()
  except Exception: raise Conflict("PID命名空间记录无效") from None
  return value


def register_namespace(processes, expected, wrapper):
  validate("process-identity", expected); validate("process-identity", wrapper)
  if (expected["platform"] != "linux" or wrapper["platform"] != "linux" or expected["namespace"] == wrapper["namespace"]
      or expected["ppid"] != wrapper["pid"] or expected["uid"] != os.geteuid() or wrapper["uid"] != os.geteuid()
      or expected["boot_id"] != wrapper["boot_id"] or wrapper["pid"] != wrapper["pgid"]
      or processes.observe(expected) != "alive" or processes.observe(wrapper) != "alive"):
    raise Conflict("PID命名空间启动身份不匹配")
  status = (processes.proc_root / str(expected["pid"]) / "status").read_text()
  rows = [line.split()[1:] for line in status.splitlines() if line.startswith("NSpid:")]
  if len(rows) != 1 or len(rows[0]) < 2 or rows[0][0] != str(expected["pid"]) or rows[0][-1] != "1":
    raise Conflict("执行不是新PID命名空间的初始化进程")
  record = {"schema_version": 3, "mode": "pid-namespace", "leader": expected, "wrapper": wrapper, "terminated": False}
  with Tree(processes.record_root, create=True) as tree:
    if tree.read(processes._path(expected)) is not None: raise Conflict("PID命名空间记录已经存在")
    tree.write_new(processes._path(expected), json_bytes(record))
  namespace_record(processes, expected)


def namespace_process_status(processes, expected):
  state = processes.observe(expected)
  if state == "dead": return state
  # /proc中的僵尸已退出，但ns链接可能先消失；出生时间/UID/boot仍能证明这是已退出的原进程。
  directory = processes.proc_root / str(expected["pid"])
  try:
    raw = (directory / "stat").read_text(); tail = raw[raw.rfind(")") + 2:].split()
    if (raw.startswith(str(expected["pid"]) + " (") and len(tail) >= 20 and tail[0] == "Z"
        and str(int(tail[19])) == expected["start_time"] and directory.stat().st_uid == expected["uid"]
        and (processes.proc_root / "sys/kernel/random/boot_id").read_text().strip() == expected["boot_id"]
        and (directory / "stat").read_text() == raw): return "dead"
  except (OSError, ValueError): pass
  return state


def namespace_status(processes, expected, record):
  if record["terminated"]: return "terminated"
  states = [namespace_process_status(processes, record[key]) for key in ("leader", "wrapper")]
  if "unknown" in states: return "unknown"
  if states != ["dead", "dead"]: return "active"
  # 已观察到原PID 1与外层包装进程退出；保留证明，不因后来的无关PID复用撤销它。
  with Tree(processes.record_root) as tree:
    tree.write_state(processes._path(expected), json_bytes({**record, "terminated": True}))
  return "terminated"


def stop_namespace(processes, expected, record, *, grace_seconds):
  if namespace_status(processes, expected, record) == "terminated": return
  # PID 1可能忽略TERM；明确撤销整个委托时直接停止命名空间，不逐个追赶短命孙进程。
  for key in ("leader", "wrapper"):
    status = namespace_process_status(processes, record[key])
    if status == "unknown": raise Conflict("PID命名空间停止目标身份未知")
    if status == "alive": processes.send_signal(record[key], signal.SIGKILL)
    deadline = processes.clock() + grace_seconds
    while processes.clock() < deadline:
      status = namespace_status(processes, expected, record)
      if status == "terminated": return
      if status == "unknown": raise Conflict("PID命名空间终止尚未确认")
      processes.pause(min(0.05, max(0, deadline - processes.clock())))
  raise Conflict("PID命名空间尚有活动，保留保护")


def read_namespace_info(fd, *, timeout=10):
  deadline = time.monotonic() + timeout; body = b""
  with selectors.DefaultSelector() as poll:
    poll.register(fd, selectors.EVENT_READ)
    while time.monotonic() < deadline:
      if not poll.select(max(0, deadline - time.monotonic())): break
      chunk = os.read(fd, 65536 - len(body))
      if not chunk: break
      body += chunk
      if len(body) >= 65536: break
      try: value = json.loads(body)
      except (ValueError, UnicodeError): continue
      if (not isinstance(value, dict) or set(value) != {"child-pid", "mnt-namespace", "pid-namespace"}
          or any(type(item) is not int or item <= 0 for item in value.values())): break
      return value
  raise Conflict("PID命名空间握手不完整")


def namespace_argv(host, command, info_fd):
  binary = host.runtime_root / "bin/codex-resources/bwrap"
  gate = host.repository / "scripts/pi-namespace-exec.py"
  if binary.is_symlink() or not binary.is_file() or gate.is_symlink() or not gate.is_file(): raise Conflict("PID命名空间固定入口缺失")
  paths = {Path(name): False for name in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc") if Path(name).exists()}
  paths.update({Path(sys.prefix): False, Path(sys.base_prefix): False, host.runtime_root: False})
  paths.update({Path(host.config["instance_root"]): True, host.root: True, Path(command.cwd): True})
  # 已声明额外根和Git元数据保持可见；实际模型文件权限仍由冻结的Codex原生策略约束。
  for row in host.manifest()["options"].get("paths", {}).get("roots", {}).values():
    paths.setdefault(Path(row["path"]), row["purpose"] == "write")
  workspace = host.store.workspaces.identify(command.cwd)
  git = Path(workspace["git_dir_path"])
  paths.setdefault(git, False)
  with Tree(git, private=False) as tree: common = tree.read("commondir")
  if common: paths.setdefault((git / common[0].decode().strip()).resolve(strict=True), False)
  paths[host.runtime_root] = False
  if Path("/") in paths: raise Conflict("PID命名空间根绑定过宽")
  argv = [str(binary), "--unshare-pid", "--as-pid-1", "--die-with-parent", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
  for path, writable in sorted(paths.items(), key=lambda pair: (len(pair[0].parts), str(pair[0]))):
    argv += ["--bind" if writable else "--ro-bind", str(path), str(path)]
  return [*argv, "--chdir", str(command.cwd), "--info-fd", str(info_fd), "--", sys.executable, "-B", "-I", str(gate), "--", *command.argv]


def spawn_namespace(host, command, environment, streams):
  if command.stdin_pipe or command.terminal_size is not None: raise Conflict("PID命名空间委托不接受外部交互输入")
  info_read, info_write = os.pipe(); gate_read, gate_write = os.pipe(); child = None
  try:
    argv = namespace_argv(host, command, info_write)
    child = subprocess.Popen(argv, cwd=command.cwd, env=environment, pass_fds=(info_write,), start_new_session=True,
      **{**streams, "stdin": gate_read})
    os.close(info_write); info_write = None
    os.close(gate_read); gate_read = None
    info = read_namespace_info(info_read)
    identity = host.processes.identity(info["child-pid"]); wrapper = host.processes.identity(child.pid)
    if identity["namespace"] != "pid:[" + str(info["pid-namespace"]) + "]": raise Conflict("PID命名空间身份不匹配握手")
    host.processes.register_namespace(identity, wrapper)
    return child, identity, gate_write
  except BaseException:
    os.close(gate_write)
    if child is not None:
      try: child.wait(timeout=5)
      except subprocess.TimeoutExpired:
        child.kill()
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired: pass
    raise
  finally:
    for fd in (info_read, info_write, gate_read):
      if fd is not None: os.close(fd)


def host_namespace_argv(host, command, info_fd, token):
  binary = host.runtime_root / "bin/codex-resources/bwrap"
  gate = host.repository / "scripts/pi-namespace-exec.py"
  if binary.is_symlink() or not binary.is_file() or gate.is_symlink() or not gate.is_file():
    raise Conflict("PID命名空间固定入口缺失")
  # 这里只增加内核进程范围，完整继承调用者已有挂载权限；不改变宿主的原有文件授权。
  return [str(binary), "--unshare-pid", "--as-pid-1", "--die-with-parent", "--cap-drop", "ALL",
    "--bind", "/", "/", "--proc", "/proc", "--dev", "/dev", "--chdir", str(command.cwd), "--info-fd", str(info_fd),
    "--", sys.executable, "-B", "-I", str(gate), "--host-gate", token, "--", *command.argv]


def verify_host_gate(connection, identity, info):
  pid, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
  if (pid != identity["pid"] or uid != identity["uid"] or connection.recv(1) != b"R"
      or identity["namespace"] != "pid:[" + str(info["pid-namespace"]) + "]"):
    raise Conflict("宿主PID命名空间门控身份不匹配")


def spawn_host_namespace(host, command, environment, streams):
  """宿主含短命控制客户端；用内核范围覆盖父退出时尚未被轮询发现的后代。"""
  token = secrets.token_hex(32)
  listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
  listener.settimeout(10)
  info_read, info_write = os.pipe()
  child = connection = None
  try:
    listener.bind("\0agentcfg-host-gate-" + token); listener.listen(1)
    child = subprocess.Popen(host_namespace_argv(host, command, info_write, token), cwd=command.cwd,
      env=environment, pass_fds=(info_write,), start_new_session=True, **streams)
    os.close(info_write); info_write = None
    info = read_namespace_info(info_read)
    # 子入口先成为独立session再连接；此后PGID不再改变，登记的出生身份稳定。
    connection, _ = listener.accept(); connection.settimeout(10)
    identity = host.processes.identity(info["child-pid"]); wrapper = host.processes.identity(child.pid)
    verify_host_gate(connection, identity, info)
    host.processes.register_namespace(identity, wrapper)
    connection.settimeout(None)
    descriptor = connection.detach(); connection = None
    return child, identity, descriptor
  except BaseException:
    if connection is not None: connection.close(); connection = None
    if child is not None:
      child.kill()
      try: child.wait(timeout=5)
      except subprocess.TimeoutExpired: pass
    raise
  finally:
    listener.close()
    if connection is not None: connection.close()
    for descriptor in (info_read, info_write):
      if descriptor is not None: os.close(descriptor)


def same_namespace_process(expected, actual):
  return (actual.get("platform") == expected.get("platform") == "linux" and type(actual.get("pid")) is int and actual["pid"] == 1
    and all(isinstance(expected.get(key), str) and expected[key] for key in ("boot_id", "start_time", "namespace"))
    and type(actual.get("uid")) is int and type(expected.get("uid")) is int and expected["uid"] >= 0
    and all(actual.get(key) == expected.get(key) for key in ("boot_id", "start_time", "namespace", "uid")))


def local_namespace_identity(proc_root=Path("/proc"), *, pid=None):
  # 内部PGID可能显示为0（组长在父命名空间）；握手只比较不可变出生身份。
  pid = os.getpid() if pid is None else pid
  directory = Path(proc_root) / str(pid)
  raw = (directory / "stat").read_text(); tail = raw[raw.rfind(")") + 2:].split()
  if len(tail) < 20 or not raw.startswith(str(pid) + " ("): raise Conflict("PID命名空间本地身份无效")
  result = {"platform": "linux", "pid": pid, "boot_id": (Path(proc_root) / "sys/kernel/random/boot_id").read_text().strip(),
    "start_time": str(int(tail[19])), "uid": directory.stat().st_uid, "namespace": os.readlink(directory / "ns/pid")}
  if (directory / "stat").read_text().split(")")[-1].split()[19] != result["start_time"]: raise Conflict("PID命名空间本地身份变化")
  return result


def namespace_lease_proof(state_root, leases):
  from .activity_linux import LinuxProcesses
  selected = [row for row in leases if row["kind"] == "codex"]
  if not selected: return False
  processes = LinuxProcesses(Path(state_root) / "activity/processes")
  try:
    for lease in selected:
      if not lease.get("process_identity"): return False
      record = namespace_record(processes, lease["process_identity"])
      if record is None or record["terminated"] is not True: return False
    return True
  except (OSError, ValueError, Conflict): return False
