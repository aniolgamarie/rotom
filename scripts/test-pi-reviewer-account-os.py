"""自有账户账本OS探针。默认仅静态prepare；run需独立source验收。

固定schema1/no-claims树与18模块顶层闭包；不是产品全依赖或断电恢复证明。
"""
from copy import deepcopy
import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/usr/bin/python3.11")
BWRAP = Path("/usr/bin/bwrap")
PURELIB = Path("/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/lib/python3.11/site-packages")
DEPENDENCIES = ("yaml", "jsonschema", "referencing", "rpds", "attrs", "attr", "jsonschema_specifications", "typing_extensions.py")
CASES = ("concurrent-claim", "updating-before-ledger", "claimed-before-ready", "ready-before-replace", "ready-after-replace", "unknown-then-deny")
CODE = "PI_REVIEWER_ACCOUNT_OS_FAILED"
MAX_OUTPUT = 65536
PROBE_ID = "reviewer-account-os-v1"

class ProbeError(Exception):
  def __init__(self): super().__init__(CODE)


def require(value):
  if not value: raise ProbeError()


def closed(value, keys): require(type(value) is dict and set(value) == set(keys))


def encode(value): return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def pairs(items):
  result = {}
  for key, value in items:
    require(key not in result); result[key] = value
  return result


def decode(value):
  try: return json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: require(False))
  except (ValueError, UnicodeError, RecursionError): raise ProbeError() from None


def canonical(value):
  path = Path(value)
  require(path.is_absolute() and str(path) == str(value) and ".." not in path.parts)
  for parent in reversed((path, *path.parents)):
    info = parent.lstat(); require(not stat.S_ISLNK(info.st_mode))
  return path


def snapshot(info):
  return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode),
    "size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def file_record(path, *, max_bytes=134217728):
  path = canonical(path); before = path.lstat()
  require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid in (0, os.geteuid()) and before.st_size <= max_bytes)
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
  try:
    require(snapshot(os.fstat(fd)) == snapshot(before)); total = 0; sha = hashlib.sha256()
    while True:
      chunk = os.read(fd, 65536)
      if not chunk: break
      total += len(chunk); require(total <= max_bytes); sha.update(chunk)
    require(snapshot(os.fstat(fd)) == snapshot(before) == snapshot(path.lstat()))
  finally: os.close(fd)
  return {**snapshot(before), "sha256": sha.hexdigest()}


def source_bytes(path, expected):
  path = canonical(path); before = path.lstat()
  require(snapshot(before) == {key: expected[key] for key in snapshot(before)} and stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 33554432)
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
  try:
    require(snapshot(os.fstat(fd)) == snapshot(before)); data = bytearray()
    while len(data) <= 33554432:
      chunk = os.read(fd, min(65536, 33554433 - len(data)))
      if not chunk: break
      data.extend(chunk)
    require(len(data) <= 33554432 and snapshot(os.fstat(fd)) == snapshot(before) == snapshot(path.lstat())
      and hashlib.sha256(data).hexdigest() == expected["sha256"])
    return bytes(data)
  finally: os.close(fd)


def read(path, *, maximum=MAX_OUTPUT):
  path = canonical(path); before = path.lstat()
  require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.geteuid()
    and stat.S_IMODE(before.st_mode) == 0o600 and before.st_size <= maximum)
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
  try:
    require(snapshot(os.fstat(fd)) == snapshot(before)); value = bytearray()
    while len(value) <= maximum:
      chunk = os.read(fd, min(65536, maximum + 1 - len(value)))
      if not chunk: break
      value.extend(chunk)
    require(len(value) <= maximum and snapshot(os.fstat(fd)) == snapshot(before) == snapshot(path.lstat()))
    return bytes(value)
  finally: os.close(fd)


def write_new(path, value):
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
  try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb", closefd=False) as stream: stream.write(value); stream.flush(); os.fsync(fd)
  finally: os.close(fd)



def inventory(root):
  files, directories = {}, {}
  require(root.lstat().st_mode & 0o777 == 0o700)
  def visit(path):
    require(path.lstat().st_mode & 0o777 == 0o700)
    for item in sorted(path.iterdir()):
      info = item.lstat(); name = item.relative_to(root).as_posix()
      require(info.st_uid == os.geteuid() and not stat.S_ISLNK(info.st_mode))
      if stat.S_ISDIR(info.st_mode):
        require(stat.S_IMODE(info.st_mode) == 0o700)
        directories[name] = {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid, "mode": 0o700}; visit(item)
      else:
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600); files[name] = file_record(item, max_bytes=33554432)
  visit(root)
  return files, directories



def capture(argv):
  child = subprocess.Popen(argv, env={}, cwd="/tmp", stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
  counts = {"stdout_bytes": 0, "stderr_bytes": 0}; output = bytearray(); failed = False
  try:
    with selectors.DefaultSelector() as selector:
      for name, stream in (("stdout_bytes", child.stdout), ("stderr_bytes", child.stderr)):
        os.set_blocking(stream.fileno(), False); selector.register(stream, selectors.EVENT_READ, name)
      deadline = time.monotonic() + 25
      while selector.get_map():
        if time.monotonic() >= deadline: failed = True; break
        for key, _ in selector.select(0.1):
          chunk = os.read(key.fileobj.fileno(), 8192)
          if not chunk: selector.unregister(key.fileobj); continue
          counts[key.data] += len(chunk)
          if counts[key.data] > MAX_OUTPUT: failed = True; break
          if key.data == "stdout_bytes": output.extend(chunk)
        if failed: break
      if failed: return {**counts, "exit_code": None, "capture_failed": True}, bytes(output)
      exit_code = child.wait(timeout=max(0.001, deadline - time.monotonic()))
      return {**counts, "exit_code": exit_code, "capture_failed": False}, bytes(output)
  finally:
    # 每次capture仅一个清理尾窗：TERM+5秒，必要KILL+5秒；不凭leader退出宣称scope终止。
    try:
      if child.poll() is None:
        try: os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          try: os.killpg(child.pid, signal.SIGKILL)
          except ProcessLookupError: pass
          child.wait(timeout=5)
    finally:
      child.stdout.close(); child.stderr.close()


def closure(root):
  """仅固定调用路径的顶层import closure；不复制未调用adapter/claims分支。"""
  pending = ["pi_reviewer_account"]; found = {"__init__"}
  while pending:
    name = pending.pop()
    if name in found: continue
    require(name.isidentifier()); found.add(name)
    path = root / "src/agentcfg" / (name + ".py")
    pinned = file_record(path, max_bytes=524288)
    tree = ast.parse(source_bytes(path, pinned))
    for node in tree.body:
      if isinstance(node, ast.ImportFrom) and node.level:
        require(node.level == 1 and node.module is not None and "." not in node.module)
        pending.append(node.module)
  require(len(found) <= 30)
  return sorted(found)


def sources(root):
  return {name: file_record(root / "src/agentcfg" / (name + ".py"), max_bytes=524288) for name in closure(root)}


def dependency_directories():
  result = {}
  for name in DEPENDENCIES:
    root = canonical(PURELIB / name)
    if not root.is_dir(): continue
    stack = [root]
    while stack:
      path = stack.pop(); info = path.lstat()
      require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.geteuid()) and not info.st_mode & 0o022)
      members = []
      for child in sorted(path.iterdir()):
        if child.name == "__pycache__": continue
        current = child.lstat(); require(not stat.S_ISLNK(current.st_mode))
        require(stat.S_ISDIR(current.st_mode) or stat.S_ISREG(current.st_mode))
        members.append(child.name)
        if stat.S_ISDIR(current.st_mode): stack.append(child)
      result[path.relative_to(PURELIB).as_posix()] = {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode), "members": members}
      require(len(result) <= 4096)
  return result


def dependencies():
  output = {}; directories = dependency_directories()
  for name, row in directories.items():
    for member in row["members"]:
      item = PURELIB / name / member
      if item.is_file(): output[item.relative_to(PURELIB).as_posix()] = file_record(item, max_bytes=33554432)
  for name in DEPENDENCIES:
    path = canonical(PURELIB / name)
    if path.is_file(): output[name] = file_record(path, max_bytes=33554432)
  require(len(output) <= 4096 and dependency_directories() == directories)
  return output


def binaries():
  values = {"python": file_record(PYTHON), "bwrap": file_record(BWRAP)}
  for row in values.values(): require(row["mode"] & 0o111 and not row["mode"] & 0o6022)
  return values


def worker(root): return root / "tests/fixtures/pi/reviewer-account-os/worker.py"


def put(path, body, base):
  parents = []; current = path.parent
  while current != base:
    require(base in current.parents); parents.append(current); current = current.parent
  for parent in reversed(parents): parent.mkdir(mode=0o700, exist_ok=True)
  write_new(path, body)


def prepare(root=ROOT, tmp_parent=Path("/tmp")):
  try:
    require(sys.platform == "linux")
    root, parent = canonical(root), canonical(tmp_parent)
    require(parent == Path("/tmp") or Path("/tmp") in parent.parents)
    src, deps, binary = sources(root), dependencies(), binaries()
    dep_dirs = dependency_directories()
    worker_pin = file_record(worker(root), max_bytes=524288)
    directory = Path(tempfile.mkdtemp(prefix="agentcfg-reviewer-account-os-", dir=parent)); directory.chmod(0o700)
    bundle, work = directory / "bundle", directory / "work"
    for path in (bundle, work, work / "home", work / "tmp"): path.mkdir(mode=0o700)
    for name, row in src.items(): put(bundle / "src/agentcfg" / (name + ".py"), source_bytes(root / "src/agentcfg" / (name + ".py"), row), bundle)
    for name, row in deps.items(): put(bundle / "deps" / name, source_bytes(PURELIB / name, row), bundle)
    write_new(bundle / "worker.py", source_bytes(worker(root), worker_pin))
    # Third-party extension modules must remain readable; no executable code is run in prepare.
    require(sources(root) == src and dependencies() == deps and dependency_directories() == dep_dirs and binaries() == binary and file_record(worker(root), max_bytes=524288) == worker_pin)
    files, dirs = inventory(bundle)
    manifest = {"schema_version": 1, "probe_id": PROBE_ID, "root": str(root), "sources": src, "dependencies": deps, "dependency_directories": dep_dirs,
      "worker": worker_pin, "controller": file_record(root / "scripts/test-pi-reviewer-account-os.py", max_bytes=524288), "binaries": binary, "files": files, "directories": dirs, "schemas": {}, "self_worker_started": False}
    write_new(directory / "manifest.json", encode(manifest))
    return {"directory": str(directory), "manifest": deepcopy(manifest)}
  except Exception: raise ProbeError() from None


def preflight(prepared, *, after=False):
  try:
    closed(prepared, ("directory", "manifest")); directory = canonical(prepared["directory"])
    require(Path("/tmp") in directory.parents and directory.name.startswith("agentcfg-reviewer-account-os-"))
    require(directory.lstat().st_uid == os.geteuid() and stat.S_IMODE(directory.lstat().st_mode) == 0o700)
    require({p.name for p in directory.iterdir()} == ({"bundle", "work", "manifest.json", "started.json"} if after else {"bundle", "work", "manifest.json"}))
    saved = decode(read(directory / "manifest.json", maximum=4194304)); require(saved == prepared["manifest"])
    closed(saved, ("schema_version", "probe_id", "root", "sources", "dependencies", "dependency_directories", "worker", "controller", "binaries", "files", "directories", "schemas", "self_worker_started"))
    require(type(saved["schema_version"]) is int and saved["schema_version"] == 1 and saved["probe_id"] == PROBE_ID and saved["schemas"] == {} and saved["self_worker_started"] is False)
    root = canonical(saved["root"])
    require(file_record(root / "scripts/test-pi-reviewer-account-os.py", max_bytes=524288) == saved["controller"])
    require(sources(root) == saved["sources"] and dependencies() == saved["dependencies"] and dependency_directories() == saved["dependency_directories"] and binaries() == saved["binaries"] and file_record(worker(root), max_bytes=524288) == saved["worker"])
    files, dirs = inventory(directory / "bundle"); require(files == saved["files"] and dirs == saved["directories"])
    expected = {"src/agentcfg/" + name + ".py" for name in saved["sources"]} | {"deps/" + name for name in saved["dependencies"]} | {"worker.py"}
    require(set(files) == expected)
    work_files, work_dirs = inventory(directory / "work")
    if not after: require(not work_files and set(work_dirs) == {"home", "tmp"})
    else:
      require(set(work_dirs) == {"home", "tmp", "cases"} | {"cases/" + case + suffix for case in CASES for suffix in ("", "/account", "/account/.agentcfg-workspaces", "/account/.agentcfg-workspaces/reviewer-budget")})
      expected_files = {"result.json"}
      for i, case in enumerate(CASES):
        base = "cases/" + case + "/"
        expected_files |= {base + "account/.agentcfg-workspaces/" + leaf for leaf in ("registry.json", "reviewer-budget.json", "reviewer-budget/reviewer-ledger.json", "reviewer-budget/instance.lock")}
        expected_files |= {base + leaf for leaf in (("ready-0", "ready-1", "go", "claim-0.json", "claim-1.json", "fake-dispatch", "reopen.json") if i == 0 else ("reopen.json", "cut.json") if i < 5 else ("deny-check.json", "unknown.json"))}
      require(set(work_files) == expected_files)
    return directory
  except Exception: raise ProbeError() from None


def verify_result(value):
  try:
    closed(value, ("schema_version", "status", "cases", "scope_termination", "product_gate"))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["status"] == "observed" and value["product_gate"] is False)
    require(value["scope_termination"] == "not-independently-observed" and type(value["cases"]) is list and len(value["cases"]) == 6)
    for i, (name, row) in enumerate(zip(CASES, value["cases"])):
      closed(row, ("case", "status", "claim_returns", "fake_dispatches", "attempt_claimed", "sentinel_state", "reopen", "synthetic_requests", "actual_http_requests", "actual_model_requests"))
      require(row["case"] == name and row["status"] == "observed" and row["attempt_claimed"] is (i != 1))
      require(row["sentinel_state"] == ("updating" if i in (1, 2, 3) else "ready"))
      require(row["reopen"] == ("conflict" if i in (0, 4) else "recovery-required" if i in (1, 2, 3) else "deny-locked"))
      for key, count in (("claim_returns", int(i == 0)), ("fake_dispatches", int(i == 0)), ("synthetic_requests", int(i == 5)), ("actual_http_requests", 0), ("actual_model_requests", 0)):
        require(type(row[key]) is int and row[key] == count)
    return deepcopy(value)
  except Exception: raise ProbeError() from None


def verify_artifacts(directory, result):
  for i, (case, report) in enumerate(zip(CASES, result["cases"])):
    base = directory / "work/cases" / case; anchor = base / "account/.agentcfg-workspaces"
    registry = decode(read(anchor / "registry.json"))
    closed(registry, ("schema_version", "coordinator", "roots")); require(type(registry["schema_version"]) is int and registry["schema_version"] == 1 and registry["roots"] == [])
    def physical(path):
      info = path.lstat(); return {"dev": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}
    account_identity, anchor_identity, budget_identity = physical(base / "account"), physical(anchor), physical(anchor / "reviewer-budget")
    require(registry["coordinator"] == {"canonical_path": "/work/cases/" + case + "/account", "account_identity": account_identity, "registry_identity": anchor_identity})
    state = decode(read(anchor / "reviewer-budget.json"))
    closed(state, ("schema_version", "state", "account_identity", "registry_identity", "budget_identity", "ledger_identity", "ledger_sha256"))
    require(type(state["schema_version"]) is int and state["schema_version"] == 1 and state["state"] == report["sentinel_state"])
    require(state["account_identity"] == account_identity and state["registry_identity"] == anchor_identity and state["budget_identity"] == budget_identity)
    require(type(state["ledger_identity"]) is list and len(state["ledger_identity"]) == 6 and all(type(n) is int and n >= 0 for n in state["ledger_identity"]))
    ledger = decode(read(anchor / "reviewer-budget/reviewer-ledger.json", maximum=8388608))
    closed(ledger, ("schema_version", "limits", "rows")); require(set(ledger["rows"]) == {"0" * 31 + "1"})
    require(type(ledger["schema_version"]) is int and ledger["schema_version"] == 1 and ledger["limits"] == {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000})
    ledger_path = anchor / "reviewer-budget/reviewer-ledger.json"
    if state["state"] == "ready" or i == 1:
      info = ledger_path.lstat()
      require(state["ledger_identity"] == [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns])
      require(state["ledger_sha256"] == hashlib.sha256(read(ledger_path)).hexdigest())
    else:
      old = deepcopy(ledger); old["rows"]["0" * 31 + "1"]["attempt_claimed"] = False
      require(state["ledger_sha256"] == hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest())
    row = ledger["rows"]["0" * 31 + "1"]
    closed(row, ("binding", "scope", "pricing", "token_limits", "reservation_units", "attempt_claimed", "send_state", "requests", "outcome", "decision", "reason_code", "usage", "final_usage", "process_terminated", "settled_units"))
    require(row["attempt_claimed"] is report["attempt_claimed"] and row["requests"] == (1 if i == 5 else 0) and type(row["requests"]) is int)
    expected_request = {"binding": {"operation_id": "0" * 31 + "1", "request_id": f"{101:032x}", "operation_digest": "a" * 64, "context_digest": "b" * 64, "reviewer_identity": "c" * 64},
      "scope": {"session_scope": "d" * 32, "intent_ref": "e" * 32},
      "pricing": {"identity": "f" * 64, "currency": "USD", "input_units_per_million": 1000000, "output_units_per_million": 2000000, "cache_read_units_per_million": 500000, "cache_write_units_per_million": 3000000},
      "token_limits": {"input_tokens": 100, "output_tokens": 10}}
    for key, expected in expected_request.items(): require(row[key] == expected)
    require(row["decision"] == ("deny" if i == 5 else None) and row["outcome"] == ("valid" if i == 5 else None))
    require(row["reason_code"] == ("outside-user-scope" if i == 5 else None))
    require(row["send_state"] == ("committed" if i == 5 else "reserved") and row["reservation_units"] == 320)
    require(row["usage"] is None and row["final_usage"] is False and row["process_terminated"] is False and row["settled_units"] is None)
    if i in (1, 2, 3, 4):
      marker = decode(read(base / "cut.json")); closed(marker, ("case", "exit_code"))
      require(marker["case"] == case and type(marker["exit_code"]) is int and marker["exit_code"] == 70 + i)
    if i == 5:
      unknown = decode(read(base / "unknown.json")); closed(unknown, ("row", "snapshot"))
      expected_unknown = {**row, "requests": None, "outcome": None, "decision": None, "reason_code": None}
      require(unknown["row"] == expected_unknown)
      snapshot = unknown["snapshot"]
      closed(snapshot, ("schema_version", "limits", "record_count", "committed_calls", "reserved_calls", "observed_requests", "unknown_requests", "reserved_cost_units", "reported_estimated_cost_units", "charged_cost_units", "over_budget", "cost_scope", "product_gate"))
      for key, count in (("record_count", 1), ("committed_calls", 1), ("reserved_calls", 0), ("observed_requests", 0), ("unknown_requests", 1), ("reserved_cost_units", 320), ("reported_estimated_cost_units", 0), ("charged_cost_units", 320)):
        require(type(snapshot[key]) is int and snapshot[key] == count)
      require(snapshot["over_budget"] is False and snapshot["product_gate"] is False and snapshot["cost_scope"] == "reported-estimate-or-conservative-reservation")
      require(type(snapshot["schema_version"]) is int and snapshot["schema_version"] == 1 and snapshot["limits"] == ledger["limits"])
    if i == 0:
      for name in ("ready-0", "ready-1", "go"):
        require(decode(read(base / name)) == {"go" if name == "go" else "ready": True})
      claims = [decode(read(base / ("claim-" + str(j) + ".json"))) for j in (0, 1)]
      for claim in claims:
        closed(claim, ("claimed", "conflict")); require(type(claim["claimed"]) is bool)
        require(claim["conflict"] is None if claim["claimed"] else claim["conflict"] in ("REVIEW_ACCOUNT_BUSY", "REVIEW_ATTEMPT_ALREADY_CLAIMED"))
      require(sum(claim["claimed"] for claim in claims) == 1)
      require(decode(read(base / "fake-dispatch")) == {"synthetic": True, "actual_http_requests": 0, "actual_model_requests": 0})
    reopened = decode(read(base / ("deny-check.json" if i == 5 else "reopen.json")))
    closed(reopened, ("reopen",)); require(reopened["reopen"] == report["reopen"])


def invocation(directory):
  argv = [str(BWRAP), "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
  for path in ("/usr", "/lib", "/lib64"):
    if Path(path).exists(): argv += ["--ro-bind", path, path]
  argv += ["--ro-bind", str(directory / "bundle"), "/probe", "--ro-bind", str(directory / "bundle/deps"), "/python-deps", "--bind", str(directory / "work"), "/work", "--chdir", "/work"]
  env = {"HOME": "/work/home", "TMPDIR": "/work/tmp", "PATH": "/nonexistent", "PWD": "/work", "LC_ALL": "C.UTF-8", "XDG_CONFIG_HOME": "/work/home/config", "XDG_STATE_HOME": "/work/home/state", "XDG_DATA_HOME": "/work/home/data", "XDG_CACHE_HOME": "/work/home/cache"}
  for key, value in env.items(): argv += ["--setenv", key, value]
  return argv + ["--", "/usr/bin/python3.11", "-I", "-B", "-S", "/probe/worker.py"]


def verify_diagnostic(value):
  closed(value, ("schema_version", "status", "phase", "environment_keys", "environment_keys_truncated", "environment_matches", "pwd_present", "pwd_matches_chdir", "argv", "product_gate"))
  require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["status"] == "failed" and value["product_gate"] is False)
  require(value["phase"] in ("environment", "argv", "imports", "initialization", "concurrent-ready", "claim", "reopen", "cut", "unknown", "deny", "deny-check", "observe", "cleanup"))
  names = value["environment_keys"]
  require(type(names) is list and len(names) <= 32 and all(type(name) is str and re.fullmatch("[A-Za-z_][A-Za-z0-9_]{0,63}", name) for name in names))
  require(names == sorted(set(names)))
  for name in ("environment_keys_truncated", "environment_matches", "pwd_present", "pwd_matches_chdir"): require(type(value[name]) is bool)
  argv = value["argv"]; closed(argv, ("count", "count_truncated", "entry_matches", "role_shape"))
  require(type(argv["count"]) is int and 0 <= argv["count"] <= 16)
  for name in ("count_truncated", "entry_matches", "role_shape"): require(type(argv[name]) is bool)
  return deepcopy(value)


def run(prepared):
  directory = preflight(prepared)
  write_new(directory / "started.json", encode({"schema_version": 1, "launch_requested": True}))
  execution = {"schema_version": 1, "probe_id": PROBE_ID, "status": "failed", "exit_code": None, "stdout_bytes": None, "stderr_bytes": None,
    "capture_failed": True, "self_worker_started": None, "scope_termination": "not-independently-observed", "product_gate": False, "failure_code": CODE, "diagnostic": None}
  result = None
  try:
    facts, stdout = capture(invocation(directory)); execution.update(facts)
    require(facts["exit_code"] == 0 and facts["capture_failed"] is False)
    summary = decode(stdout); closed(summary, ("schema_version", "status", "cases", "product_gate"))
    require(type(summary["schema_version"]) is int and summary["schema_version"] == 1 and type(summary["cases"]) is int and summary["cases"] == 6 and summary["status"] == "observed" and summary["product_gate"] is False)
    result = verify_result(decode(read(directory / "work/result.json")))
    preflight(prepared, after=True); verify_artifacts(directory, result)
    execution.update(status="observed", self_worker_started=True, failure_code=None)
  except Exception:
    result = None
    try:
      if os.path.lexists(directory / "work/failure.json"):
        execution["diagnostic"] = verify_diagnostic(decode(read(directory / "work/failure.json", maximum=8192)))
    except Exception: pass
  write_new(directory / "execution.json", encode(execution)); require(result is not None)
  return result


def main(argv=None):
  parser = argparse.ArgumentParser()
  action = parser.add_mutually_exclusive_group(required=True)
  action.add_argument("--prepare-only", action="store_true"); action.add_argument("--run-account-os", action="store_true")
  args = parser.parse_args(argv)
  try:
    prepared = prepare()
    if args.prepare_only: print(encode({"schema_version": 1, "status": "prepared", "directory": prepared["directory"], "self_worker_started": False, "product_gate": False}).decode().strip())
    else: print(encode({"schema_version": 1, "status": run(prepared)["status"], "cases": 6, "product_gate": False}).decode().strip())
    return 0
  except Exception:
    print(encode({"schema_version": 1, "status": "failed", "code": CODE, "product_gate": False}).decode().strip()); return 5


if __name__ == "__main__": raise SystemExit(main())
