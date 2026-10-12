"""独立built-helper探针编排；默认只准备，原生运行需要另行明确授权。"""

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import select
import selectors
import stat
import subprocess
import sysconfig
import time
import uuid

from .activity_linux import LinuxProcesses
from .deployment import json_bytes
from .paths import _absolute_directory, trusted_source_directory
from .pi_built_assets import load_record, verify_archive
from .pi_lock_layout import dependency_layout
from .pi_shell_probe_info import read_namespace_info
from .pi_shell_probe_binding import prepare_execution, bind_worker
from .pi_shell_handoff import handoff_channel, seal_handoff
from .pi_runtime_files import lock_files, install_files, validate_files
from .pi_shell_probe_protocol import CASES, verify_case
from .schema import ConfigError
from .storage import Tree


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/pi/shell-helper-probe"
BOOTSTRAP = Path("/usr/bin/bwrap")
PYTHON = Path("/usr/bin/python3.11")
MAX_BYTES = 1024 * 1024
CASE_SECONDS = 45
SYSTEM_ROOTS = ("/usr", "/bin", "/lib", "/lib64")
CANARIES = {"readonly/canary": b"probe-readonly\n", "outside/canary": b"probe-outside\n",
  "project/private/canary": b"probe-denied\n", "project/nested/.git/canary": b"probe-git\n"}
BLOCKED = ("readonly/blocked-write", "outside/blocked-write", "project/private/blocked-write", "project/nested/.git/blocked-write")
ENV = {"HOME": "/work/home", "PATH": "/usr/bin:/bin", "TMPDIR": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
  "AGENTCFG_SUPERVISOR_ENDPOINT": "/synthetic-never-a-control-socket", "AGENTCFG_SUPERVISOR_CAPABILITY": "synthetic-not-a-capability",
  "ROTOM_PROBE_POISON": "synthetic-env-canary"}
CONTROLLERS = ("scripts/pi-probe-shell.py", "src/agentcfg/pi_shell_probe.py", "src/agentcfg/pi_shell_probe_protocol.py", "src/agentcfg/pi_shell_probe_info.py", "src/agentcfg/pi_shell_probe_binding.py", "src/agentcfg/pi_shell_identity.py")


def require(value):
  if not value: raise ConfigError("pi-shell-probe")


def _object(items):
  value = {}
  for key, item in items:
    require(key not in value); value[key] = item
  return value


def decode(raw):
  def constant(_): raise ConfigError("pi-shell-probe")
  try: return json.loads(raw, object_pairs_hook=_object, parse_constant=constant)
  except (ValueError, UnicodeError): raise ConfigError("pi-shell-probe") from None


def sha(data):
  return hashlib.sha256(data).hexdigest()


def file_identity(path):
  with trusted_source_directory(path.parent) as directory:
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    try:
      before = os.fstat(fd)
      require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid in (0, os.geteuid())
        and not before.st_mode & 0o6022 and before.st_size <= 64 * 1024 * 1024)
      value, count = hashlib.sha256(), 0
      while block := os.read(fd, 1024 * 1024):
        count += len(block); require(count <= 64 * 1024 * 1024); value.update(block)
      after = os.fstat(fd)
      require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns))
      return {"path": str(path), "sha256": value.hexdigest(), "device": before.st_dev, "inode": before.st_ino}
    finally: os.close(fd)


def dependencies():
  path = Path(sysconfig.get_paths()["purelib"])
  with trusted_source_directory(path) as fd:
    info = os.fstat(fd)
    for name in ("jsonschema", "referencing", "rpds", "yaml", "jinja2"):
      require(stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode))
  # 此路径仅供可信Python引导；不宣称整个venv内容已完整冻结。
  return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def sources():
  layout = dependency_layout(family="modern")
  with Tree(ROOT, private=False) as tree:
    raw = tree.read("agents/pi/dependencies-modern.json")
    require(raw is not None)
    document = decode(raw[0]); source = document["sources"]["pi-bwrap-linux-x86_64"]
    record = load_record(ROOT, layout, source)
    archive = tree.read(layout.lock_directory + "/" + source["vendor_path"], max_bytes=16 * 1024 * 1024)
    require(archive is not None)
    binary = verify_archive(archive[0], source, record)
  require(file_identity(BOOTSTRAP)["sha256"] == record["bootstrap"]["sha256"])
  declarations = [row for row in document["profiles"]["pi-base"]["runtime_files"] if row["path"].startswith("supervisor/")]
  # 使用Base显式声明的同一闭包；probe控制器仍独立记录来源，不隐式追加产品依赖。
  rows = lock_files(ROOT, declarations)
  return binary, rows


def inventory(directory):
  files, directories = {}, []
  def walk(path):
    for item in os.scandir(path):
      name = Path(item.path).relative_to(directory).as_posix()
      info = item.stat(follow_symlinks=False)
      require(info.st_uid == os.geteuid())
      if stat.S_ISDIR(info.st_mode):
        require(stat.S_IMODE(info.st_mode) == 0o700); directories.append(name); walk(Path(item.path))
      else:
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == (0o700 if name == "inputs/helper" else 0o600))
        if name == "plan.json": continue
        with Tree(directory) as tree: raw = tree.read(name, max_bytes=16 * 1024 * 1024)
        require(raw is not None); files[name] = {"sha256": sha(raw[0]), "mode": raw[1]}
  walk(directory)
  return files, sorted(directories)


def check_layout(files, directories, rows):
  expected = {"inputs/" + row["path"] for row in rows}
  expected.update("inputs/" + name for name in ("helper", "passwd", "group", "worker.py"))
  for case in CASES:
    prefix = "cases/" + case + "/work/"
    expected.update(prefix + name for name in CANARIES)
    expected.update(prefix + "readonly/" + name for name in ("payload.py", "heartbeat.py"))
  parents = {parent.as_posix() for name in expected for parent in Path(name).parents if parent != Path(".")}
  parents.update("cases/" + case + "/work/home" for case in CASES)
  # 包内清单只能证明一致性；固定目录集合由当前源声明和探针契约独立派生。
  require(set(files) == expected and set(directories) == parents)


def prepare(directory):
  directory = Path(directory)
  require(directory.is_absolute() and ".." not in directory.parts and not os.path.lexists(directory))
  binary, rows = sources()
  system = {"bootstrap": file_identity(BOOTSTRAP), "python": file_identity(PYTHON), "bash": file_identity(Path("/usr/bin/bash")), "dependencies": dependencies()}
  with _absolute_directory(directory.parent) as parent: os.mkdir(directory.name, 0o700, dir_fd=parent)
  with Tree(directory) as tree:
    tree.write_new("inputs/helper", binary)
    with tree.parent("inputs/helper") as (parent, name):
      fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
      try: os.fchmod(fd, 0o700)
      finally: os.close(fd)
    tree.write_new("inputs/passwd", f"probe:x:{os.geteuid()}:{os.getegid()}:synthetic:/nonexistent:/bin/false\n".encode())
    tree.write_new("inputs/group", f"probe:x:{os.getegid()}:\n".encode())
    with Tree(FIXTURE, private=False) as fixtures:
      templates = {}
      for name in ("worker.py", "payload.py", "heartbeat.py"):
        item = fixtures.read(name); require(item is not None); templates[name] = item[0]
    tree.write_new("inputs/worker.py", templates["worker.py"])
    nonces = {case: uuid.uuid4().hex for case in CASES}
    for case in CASES:
      for name, data in CANARIES.items(): tree.write_new("cases/" + case + "/work/" + name, data)
      for name in ("payload.py", "heartbeat.py"):
        tree.write_new("cases/" + case + "/work/readonly/" + name, templates[name])
      with tree.parent("cases/" + case + "/work/home/.unused", create=True): pass
  install_files(ROOT, directory / "inputs", rows)
  validate_files(directory / "inputs", rows, generated=())
  files, dirs = inventory(directory)
  check_layout(files, dirs, rows)
  controller_files = {name: file_identity(ROOT / name)["sha256"] for name in CONTROLLERS}
  plan = {"schema_version": 1, "probe_id": "shell-helper-linux-x86_64-v1", "cases": list(CASES), "nonces": nonces,
    "helper_identity": sha(binary), "system": system, "files": files, "directories": dirs, "controllers": controller_files}
  with Tree(directory) as tree: tree.write_new("plan.json", json_bytes(plan))
  return plan


def preflight(directory):
  directory = Path(directory)
  require(directory.is_absolute() and ".." not in directory.parts)
  with Tree(directory) as tree:
    item = tree.read("plan.json"); require(item is not None and item[1] == 0o600)
    plan = decode(item[0])
  require(type(plan) is dict and set(plan) == {"schema_version", "probe_id", "cases", "nonces", "helper_identity", "system", "files", "directories", "controllers"})
  require(type(plan["schema_version"]) is int and plan["schema_version"] == 1 and plan["probe_id"] == "shell-helper-linux-x86_64-v1" and plan["cases"] == list(CASES))
  import re
  require(type(plan["nonces"]) is dict and set(plan["nonces"]) == set(CASES)
    and all(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) for value in plan["nonces"].values()))
  binary, rows = sources()
  require(plan["helper_identity"] == sha(binary))
  require(plan["system"] == {"bootstrap": file_identity(BOOTSTRAP), "python": file_identity(PYTHON),
    "bash": file_identity(Path("/usr/bin/bash")), "dependencies": dependencies()})
  require(plan["controllers"] == {name: file_identity(ROOT / name)["sha256"] for name in CONTROLLERS})
  files, dirs = inventory(directory)
  check_layout(files, dirs, rows)
  require(files == plan["files"] and dirs == plan["directories"])
  # 再对当前声明核验裁剪源，避免只重算一份可同时改写的包内清单。
  validate_files(directory / "inputs", rows, generated=())
  require(files["inputs/helper"]["sha256"] == sha(binary))
  with Tree(directory) as tree, Tree(FIXTURE, private=False) as source:
    for name in ("worker.py", "payload.py", "heartbeat.py"):
      original = source.read(name); require(original is not None)
      targets = ["inputs/worker.py"] if name == "worker.py" else ["cases/" + case + "/work/readonly/" + name for case in CASES]
      for target in targets: require(tree.read(target)[0] == original[0])
    for case in CASES:
      for name, data in CANARIES.items(): require(tree.read("cases/" + case + "/work/" + name)[0] == data)
    require(tree.read("inputs/passwd")[0] == f"probe:x:{os.geteuid()}:{os.getegid()}:synthetic:/nonexistent:/bin/false\n".encode())
    require(tree.read("inputs/group")[0] == f"probe:x:{os.getegid()}:\n".encode())
  return plan


def invocation(directory, plan, case, info_fd, handoff_fd, plan_digest):
  require(case in CASES and all(type(fd) is int and fd > 2 for fd in (info_fd, handoff_fd))
    and info_fd != handoff_fd and type(plan_digest) is str and re.fullmatch(r"[0-9a-f]{64}", plan_digest))
  root = str(directory / "cases" / case / "work")
  argv = [str(BOOTSTRAP), "--unshare-all", "--as-pid-1", "--new-session", "--die-with-parent", "--cap-drop", "ALL"]
  for path in SYSTEM_ROOTS: argv.extend(("--ro-bind", path, path))
  argv.extend(("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--ro-bind", str(directory / "inputs"), "/probe", "--ro-bind", plan["system"]["dependencies"]["path"], "/python-deps",
    "--ro-bind", str(directory / "inputs/passwd"), "/etc/passwd", "--ro-bind", str(directory / "inputs/group"), "/etc/group",
    "--bind", root, root))
  for key, value in {**ENV, "HOME": root + "/home"}.items(): argv.extend(("--setenv", key, value))
  argv.extend(("--info-fd", str(info_fd), "--chdir", root + "/project", "--", str(PYTHON), "-I", "-B", "-S", "/probe/worker.py",
    "--probe-worker", case, "--nonce", plan["nonces"][case], "--helper-identity", plan["helper_identity"],
    "--handoff-fd", str(handoff_fd), "--plan-digest", plan_digest, "--work-root", root))
  return argv, {}


def read_file(root, path):
  with Tree(root) as tree:
    item = tree.read(path, max_bytes=65536)
    return None if item is None else item[0]


def heartbeat(root, nonce):
  body = read_file(root, "project/heartbeat")
  if body is None: return 0
  require(body and len(body) % 33 == 0 and body == (nonce + "\n").encode() * (len(body) // 33))
  return len(body) // 33


def read_bootstrap(stream, case, nonce):
  data = b""; deadline = time.monotonic() + 10
  while not data.endswith(b"\n"):
    remaining = deadline - time.monotonic(); require(remaining > 0)
    ready, _, _ = select.select([stream], [], [], remaining); require(ready)
    block = os.read(stream.fileno(), 16385); require(block)
    data += block; require(len(data) <= 16384 and data.count(b"\n") <= 1)
  value = decode(data)
  require(type(value) is dict and set(value) == {"schema_version", "phase", "case_id", "nonce", "uid", "owners", "user_namespace", "uid_map"})
  require(type(value["schema_version"]) is int and value["schema_version"] == 1
    and value["phase"] == "bootstrap" and value["case_id"] == case and value["nonce"] == nonce)
  require(type(value["owners"]) is dict and set(value["owners"]) == {"root", "usr", "bash"})
  require(all(type(uid) is int and 0 <= uid < 2**32 for uid in (value["uid"], *value["owners"].values())))
  require(type(value["user_namespace"]) is str and re.fullmatch(r"user:\[[0-9]+\]", value["user_namespace"]))
  require(type(value["uid_map"]) is str and value["uid_map"].isascii() and 0 < len(value["uid_map"]) <= 16384)
  return value


def collect(process, processes, leader, root, case, nonce, started):
  events, buffer, count, before, stopped, stop_elapsed_ms = [], b"", 0, 0, False, 0
  deadline = started + CASE_SECONDS
  with selectors.DefaultSelector() as poll:
    for name in ("stdout", "stderr"): poll.register(getattr(process, name), selectors.EVENT_READ, name)
    while poll.get_map():
      require(time.monotonic() < deadline)
      for key, _ in poll.select(timeout=0.05):
        data = os.read(key.fileobj.fileno(), 65536)
        if not data: poll.unregister(key.fileobj); continue
        count += len(data); require(count <= MAX_BYTES)
        # 自有固定worker不应产生诊断；不能把后台异常退出误判为主动停止。
        require(key.data == "stdout")
        if key.data == "stdout":
          buffer += data
          while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            require(0 < len(line) <= 65536 and len(events) < 4)
            event = decode(line); require(type(event) is dict); events.append(event)
          require(len(buffer) <= 65536)
      if case == "descendants" and not stopped and {event.get("phase") for event in events} >= {"payload", "heartbeat"}:
        before = heartbeat(root, nonce)
        if before > 0:
          require(0 <= time.monotonic() - started < 10)
          processes.stop(leader, grace_seconds=2); stopped = True
          elapsed = time.monotonic() - started
          require(0 <= elapsed < 10)
          stop_elapsed_ms = int(elapsed * 1000)
          # 停止前已见活跃写入；稳定性样本从确认停止后开始，容许信号送达期间最后一次写入。
          before = heartbeat(root, nonce)
    require(not buffer)
  process.wait(timeout=2)
  return events, before, stop_elapsed_ms


def run_case(directory, plan, case):
  info_read, info_write, gate_read, gate_write = None, None, None, None
  process, leader, registered, events, before = None, None, False, [], 0
  stage, outcome, summary = "prepare", "unavailable", None
  resources = ExitStack()
  processes = LinuxProcesses(directory / "observations" / case / "processes")
  root = directory / "cases" / case / "work"
  try:
    execution, plan_digest = resources.enter_context(prepare_execution(directory, plan, case))
    handoff_fd = resources.enter_context(handoff_channel())
    stage = "launch"
    info_read, info_write = os.pipe(); gate_read, gate_write = os.pipe()
    argv, env = invocation(directory, plan, case, info_write, handoff_fd, plan_digest)
    with Tree(directory) as tree: tree.write_new("observations/" + case + "/invocation.json", json_bytes({"argv": argv, "parent_environment": env}))
    process = subprocess.Popen(argv, cwd=root, env=env, shell=False, close_fds=True,
      stdin=gate_read, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      pass_fds=(info_write, handoff_fd, execution.helper_fd, *execution.pass_fds), start_new_session=True)
    os.close(info_write); info_write = None
    os.close(gate_read); gate_read = None
    stage = "namespace-info"
    info = read_namespace_info(info_read)
    with Tree(directory) as tree: tree.write_new("observations/" + case + "/namespace-info.json", json_bytes(info))
    # info早于bwrap子进程setsid；等可信worker就绪后再固定出生身份，仍不发送G。
    stage = "bootstrap"
    bootstrap = read_bootstrap(process.stdout, case, plan["nonces"][case])
    with Tree(directory) as tree: tree.write_new("observations/" + case + "/bootstrap.json", json_bytes(bootstrap))
    stage = "identify"
    leader = processes.identity(info["child-pid"]); wrapper = processes.identity(process.pid)
    with Tree(directory) as tree:
      tree.write_new("observations/" + case + "/identities.json", json_bytes({"leader": leader, "wrapper": wrapper}))
    stage = "register"
    require(leader["namespace"] == "pid:[" + str(info["pid-namespace"]) + "]")
    processes.register_namespace(leader, wrapper); registered = True
    stage = "identity-map"
    binding, mapping = bind_worker(execution, processes=processes, leader=leader, bootstrap=bootstrap,
      nonce=plan["nonces"][case], helper_identity=plan["helper_identity"], plan_digest=plan_digest)
    with Tree(directory) as tree: tree.write_new("observations/" + case + "/identity-map.json", json_bytes(mapping))
    stage = "handoff"
    seal_handoff(handoff_fd, execution, binding)
    started = time.monotonic()
    require(os.write(gate_write, b"G") == 1)
    os.close(gate_write); gate_write = None
    stage = "observe"
    events, before, stop_elapsed_ms = collect(process, processes, leader, root, case, plan["nonces"][case], started)
    stage = "verify"
    terminated = processes.termination_status(leader) == "terminated"
    # PID1终止证据之外，再由父侧观察后台文件不继续变化。
    if case == "descendants": time.sleep(0.15)
    facts = {"exit_code": process.returncode, "terminated": terminated,
      "positive": read_file(root, "project/positive") == (plan["nonces"][case] + "\n").encode(),
      "canaries_unchanged": all(read_file(root, name) == value for name, value in CANARIES.items()),
      "blocked_files_absent": all(not os.path.lexists(root / name) for name in BLOCKED),
      "heartbeat_before": before, "heartbeat_after": heartbeat(root, plan["nonces"][case]),
      "stop_elapsed_ms": stop_elapsed_ms,
      "namespace": leader["namespace"], "helper_identity": plan["helper_identity"], "plan_digest": plan_digest}
    summary = verify_case(case, plan["nonces"][case], events, facts)
    with Tree(directory) as tree:
      tree.write_new("observations/" + case + "/observed.json", json_bytes({"events": events, "facts": facts}))
    outcome = "observed"
  except KeyboardInterrupt:
    outcome = "interrupted"
  except Exception:
    outcome = "failed" if stage == "verify" else "unavailable"
  finally:
    # gate关闭使未获准worker失败退出；登记未知时不删除可能已落盘的记录。
    for fd in (info_read, info_write, gate_read, gate_write):
      if fd is not None:
        try: os.close(fd)
        except OSError: pass
    if process is not None:
      if registered:
        try:
          if processes.termination_status(leader) != "terminated": processes.stop(leader, grace_seconds=2)
        except Exception: outcome = "termination-unknown"
      try:
        if process.poll() is None:
          try: process.wait(timeout=1)
          except subprocess.TimeoutExpired:
            # 仅本次保存的wrapper句柄；不能把它退出当作整个namespace已终止。
            process.kill(); process.wait(timeout=2)
      except Exception: outcome = "termination-unknown"
      for stream in (process.stdout, process.stderr):
        if stream is not None: stream.close()
      if registered:
        try:
          if processes.termination_status(leader) != "terminated": outcome = "termination-unknown"
        except Exception: outcome = "termination-unknown"
    if not registered and leader is not None: outcome = "termination-unknown"
    resources.close()
  result = {"case_id": case, "outcome": outcome, "stage": stage, "exit_code": None if process is None else process.returncode,
    "registered": registered, "summary": summary if outcome == "observed" else None}
  with Tree(directory) as tree: tree.write_new("observations/" + case + "/result.json", json_bytes(result))
  return result


def run_native(directory):
  directory = Path(directory); plan = preflight(directory)
  with Tree(directory) as tree: tree.write_new("execution-started.json", json_bytes({"schema_version": 1, "plan_digest": sha(json_bytes(plan))}))
  cases = []
  for case in CASES:
    result = run_case(directory, plan, case); cases.append(result)
    if result["outcome"] != "observed": break
  value = {"schema_version": 1, "probe_id": plan["probe_id"], "helper_identity": plan["helper_identity"],
    "status": "observed" if len(cases) == len(CASES) and all(case["outcome"] == "observed" for case in cases) else "failed",
    "cases": cases, "product_gate": False}
  with Tree(directory) as tree: tree.write_new("result.json", json_bytes(value))
  return value


class Parser(argparse.ArgumentParser):
  def error(self, _message): raise ConfigError("pi-shell-probe-arguments")


def main(argv=None):
  parser = Parser(allow_abbrev=False)
  mode = parser.add_mutually_exclusive_group(required=True)
  mode.add_argument("--prepare", action="store_true")
  mode.add_argument("--run-native-shell-probe", action="store_true")
  parser.add_argument("--directory", type=Path, required=True)
  try:
    args = parser.parse_args(argv)
    if args.prepare:
      prepare(args.directory); print("Shell probe prepared; no native execution."); return 0
    value = run_native(args.directory)
    print("Shell probe observations recorded; product gates unchanged.")
    return 0 if value["status"] == "observed" else 5
  except Exception:
    print("Shell probe unavailable or failed; no host fallback.")
    return 5
