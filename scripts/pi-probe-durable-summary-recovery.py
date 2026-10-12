#!/usr/bin/env python3
"""默认仅准备；原生执行需新授权和显式 flag，不在导入时运行 SDK。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/pi/durable-summary-recovery-probe"
DURABLE = ROOT / ".cache/pi-two-profiles/candidates/pi-durable-1.0.1"
CANDIDATE = ROOT / ".cache/pi-two-profiles/candidates/pi-1.0.1/closure"
NODE = Path("/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node")
BWRAP = Path("/bin/bwrap")
CASES = ("summarize-before-send-fresh-bounded-authority", "summarize-before-send-denied", "summarize-unknown-sending-denied")
VERSIONS = {"durable": "1.0.1", "chord": "1.0.2", "pi_ai": "1.0.2", "node": "24.14.0"}
MODULES = ("agents/pi/packages/durable-service/src/storage.ts", "agents/pi/packages/durable-service/src/model-attempts.ts", "agents/pi/packages/durable-service/src/registry.ts", "agents/pi/packages/durable-service/src/provider.ts", "agents/pi/packages/durable-service/src/phase-tasks.ts", "agents/pi/packages/durable-service/src/phase-reader.ts", "agents/pi/packages/durable-service/src/call-identity.ts")
SOURCES = ("scripts/pi-probe-durable-summary-recovery.py", "scripts/pi-probe-durable-summary-recovery.mjs", "scripts/pi-probe-json.mjs", *MODULES, "tests/fixtures/pi/durable-summary-recovery-probe/manifest.json", "tests/fixtures/pi/durable-summary-recovery-probe/oracle.json")
ENV = {"HOME": "/work/home", "XDG_CONFIG_HOME": "/work/config", "XDG_DATA_HOME": "/work/data", "XDG_CACHE_HOME": "/work/cache", "XDG_STATE_HOME": "/work/state", "TMPDIR": "/work/tmp", "PATH": "/work/empty-bin", "LC_ALL": "C.UTF-8", "PI_DURABLE_SUMMARY_RECOVERY_NATIVE": "1", "OTEL_SDK_DISABLED": "true"}
MAX_BYTES = 1024 * 1024
MAX_LINE = 65536
MAX_PLAN = 16 * 1024 * 1024
SOURCE_CHAIN = (".cache/pi-two-profiles/candidates/pi-durable-1.0.1/SOURCE.json", ".cache/pi-two-profiles/run-20261004/rpc-current-material-review02/plan.json")

class ProbeError(Exception):
  pass

def require(value):
  if not value: raise ProbeError("durable summary recovery probe invalid")

def pairs(items):
  value = {}
  for key, child in items:
    require(key not in value); value[key] = child
  return value

def decode(raw):
  try:
    value = json.loads(raw.decode("utf-8", "strict") if type(raw) in (bytes, bytearray) else raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ProbeError("nonfinite JSON")))
    require(isinstance(value, dict)); return value
  except (ValueError, UnicodeError, RecursionError): raise ProbeError("invalid JSON") from None

def sha(raw): return hashlib.sha256(raw).hexdigest()

def strict_equal(left, right):
  return json.dumps(left, sort_keys=True, separators=(",", ":"), allow_nan=False) == json.dumps(right, sort_keys=True, separators=(",", ":"), allow_nan=False)

def exact_integer(value, minimum=0): return type(value) is int and minimum <= value <= 2**53 - 1

def record(path):
  info = path.lstat()
  if stat.S_ISDIR(info.st_mode): return {"kind": "directory"}
  if stat.S_ISLNK(info.st_mode): return {"kind": "symlink", "target": os.readlink(path)}
  require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
  return {"kind": "file", "sha256": sha(path.read_bytes()), "bytes": info.st_size}

def inventory(path):
  require(path.is_dir() and not path.is_symlink())
  result = {".": record(path)}
  def visit(directory):
    for child in sorted(directory.iterdir()):
      name = child.relative_to(path).as_posix(); result[name] = record(child)
      if result[name]["kind"] == "directory": visit(child)
  visit(path); return result

def validate_inventory(values):
  require(isinstance(values, dict) and values.get(".") == {"kind": "directory"})
  for name, value in values.items():
    require(isinstance(name, str) and (name == "." or name and not name.startswith("/") and ".." not in Path(name).parts and Path(name).as_posix() == name))
    require(isinstance(value, dict))
    if value.get("kind") == "directory": require(set(value) == {"kind"})
    elif value.get("kind") == "file":
      require(set(value) == {"kind", "sha256", "bytes"} and exact_integer(value["bytes"]))
      require(isinstance(value["sha256"], str) and len(value["sha256"]) == 64 and set(value["sha256"]) <= set("0123456789abcdef"))
    elif value.get("kind") == "symlink": require(set(value) == {"kind", "target"} and isinstance(value["target"], str))
    else: require(False)
  return values

def manifest():
  value = decode((FIXTURE / "manifest.json").read_bytes())
  require(set(value) == {"schema", "versions", "source_chain", "durable", "candidate"} and type(value["schema"]) is int and value["schema"] == 1 and strict_equal(value["versions"], VERSIONS))
  for key in ("durable", "candidate"): validate_inventory(value[key])
  require(isinstance(value["source_chain"], dict) and set(value["source_chain"]) == set(SOURCE_CHAIN))
  for name, expected in value["source_chain"].items():
    require(name in (".cache/pi-two-profiles/candidates/pi-durable-1.0.1/SOURCE.json", ".cache/pi-two-profiles/run-20261004/rpc-current-material-review02/plan.json"))
    require(strict_equal(record(ROOT / name), expected))
  return value

def material():
  require({child.name for child in FIXTURE.iterdir()} == {"manifest.json", "oracle.json"})
  fixed = manifest()
  require(strict_equal(inventory(DURABLE), fixed["durable"]) and strict_equal(inventory(CANDIDATE), fixed["candidate"]))
  for base, entries in ((DURABLE, fixed["durable"]), (CANDIDATE, fixed["candidate"])):
    for name, value in entries.items():
      if value["kind"] == "symlink": require((base / name).resolve(strict=True).is_relative_to(base.resolve(strict=True)))
  selected_sources = {name: record(ROOT / name) for name in SOURCES}
  require(all(value["kind"] == "file" for value in selected_sources.values()))
  return {"manifest": fixed, "sources": selected_sources, "system": system()}

def executable(path):
  actual = path.resolve(strict=True); info = actual.stat()
  value = record(actual); require(value["kind"] == "file" and info.st_mode & 0o111)
  return {"path": str(actual), "file": value, "stat": [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}

def system():
  values = {"node": executable(NODE), "bwrap": executable(BWRAP)}
  for name in ("/usr", "/lib", "/lib64"):
    info = Path(name).stat(); require(stat.S_ISDIR(info.st_mode))
    values[name] = {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode, "uid": info.st_uid}
  return values

def invocation(case, work):
  require(case in CASES); require(work.is_absolute() and ".." not in work.parts)
  argv = [str(BWRAP), "--unshare-all", "--cap-drop", "ALL", "--die-with-parent", "--new-session",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
    "--ro-bind", str(NODE), "/node", "--ro-bind", str(DURABLE / "package"), "/durable", "--ro-bind", str(CANDIDATE), "/candidate",
    "--dir", "/probe", "--dir", "/node_modules", "--dir", "/node_modules/@earendil-works",
    "--symlink", "/durable", "/node_modules/@earendil-works/pi-durable", "--symlink", "/candidate/node_modules/@earendil-works/chord", "/node_modules/@earendil-works/chord",
    "--symlink", "/candidate/node_modules/@earendil-works/pi-ai", "/node_modules/@earendil-works/pi-ai",
    "--symlink", "/candidate/node_modules/diff", "/node_modules/diff", "--symlink", "/candidate/node_modules/typebox", "/node_modules/typebox",
    "--ro-bind", str(ROOT / "scripts/pi-probe-durable-summary-recovery.mjs"), "/probe/worker.mjs",
    "--ro-bind", str(ROOT / "scripts/pi-probe-json.mjs"), "/probe/json.mjs",
    "--ro-bind", str(ROOT / "agents/pi/packages/durable-service/src/storage.ts"), "/probe/storage.ts",
    *[part for name in MODULES if not name.endswith("/storage.ts") for part in ("--ro-bind", str(ROOT / name), "/probe/" + Path(name).name)],
    "--ro-bind", str(FIXTURE), "/probe/fixture", "--bind", str(work), "/work", "--remount-ro", "/", "--chdir", "/work"]
  for key, value in ENV.items(): argv.extend(["--setenv", key, value])
  argv.extend(["/node", "--disable-warning=ExperimentalWarning", "--max-old-space-size=512", "/probe/worker.mjs", "--native-durable-summary-recovery-worker", case])
  return {"argv": argv, "env": {}}

def private_directory(path):
  require(path.is_absolute() and ".." not in path.parts and path.resolve(strict=True) == path)
  info = path.lstat(); require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.geteuid())

def read_private(path, maximum=MAX_PLAN):
  info = path.lstat()
  require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= maximum)
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    opened = os.fstat(fd); require((info.st_dev, info.st_ino, info.st_size) == (opened.st_dev, opened.st_ino, opened.st_size))
    with os.fdopen(fd, "rb", closefd=False) as stream: return stream.read(maximum + 1)
  finally: os.close(fd)

def write_new(path, value):
  raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
  fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
  try:
    os.fchmod(fd, 0o600); require(os.write(fd, raw) == len(raw)); os.fsync(fd)
  finally: os.close(fd)

def validate_plan(value, directory):
  require(set(value) == {"schema", "probe", "cases", "nativeAuthorized", "nativeStarted", "material", "invocations", "limits", "scope"})
  require(type(value["schema"]) is int and value["schema"] == 1 and value["probe"] == "durable-summary-recovery-1.0.1" and value["cases"] == list(CASES))
  require(value["nativeAuthorized"] is False and value["nativeStarted"] is False)
  require(strict_equal(value["limits"], {"case_seconds": 30, "total_seconds": 90, "stdout_line_bytes": MAX_LINE, "combined_output_bytes": MAX_BYTES}))
  require(value["scope"] == "synthetic-public-summarize-orderly-close-reopen-only; no real model/account/owner; namespace and physical termination unqualified")
  require(strict_equal(value["invocations"], {case: invocation(case, directory / case / "work") for case in CASES}))
  require(strict_equal(value["material"], material()))
  return value

def prepare(directory):
  private_directory(directory); require(list(directory.iterdir()) == [])
  fixed = material()
  value = {"schema": 1, "probe": "durable-summary-recovery-1.0.1", "cases": list(CASES), "nativeAuthorized": False, "nativeStarted": False,
    "material": fixed, "invocations": {case: invocation(case, directory / case / "work") for case in CASES},
    "limits": {"case_seconds": 30, "total_seconds": 90, "stdout_line_bytes": MAX_LINE, "combined_output_bytes": MAX_BYTES},
    "scope": "synthetic-public-summarize-orderly-close-reopen-only; no real model/account/owner; namespace and physical termination unqualified"}
  write_new(directory / "plan.json", value); return value

def oracle(case, value, exit_code):
  fixed = decode((FIXTURE / "oracle.json").read_bytes())
  require(type(fixed["schema"]) is int and fixed["schema"] == 1 and set(fixed) == {"schema", "cases", "intents"} and set(fixed["cases"]) == set(CASES) and set(fixed["intents"]) == set(CASES))
  require(case in CASES and type(exit_code) is int and exit_code == 0)
  expected = fixed["cases"][case]
  dynamic = {"nativeTaskId", "nativeConversationId", "firstKeptEntryId", "historyEntryIds", "summarySubmissionId", "summaryEntryId", "summaryHeadEntryId", "metadataGetModel"}
  require(type(value) is dict and set(value) == set(expected) | dynamic)
  for name, child in expected.items(): require(strict_equal(value[name], child))
  require(exact_integer(value["nativeTaskId"], 1) and exact_integer(value["nativeConversationId"], 1) and value["nativeTaskId"] != value["nativeConversationId"])
  require(type(value["historyEntryIds"]) is list and len(value["historyEntryIds"]) == 2 and all(exact_integer(item, 1) for item in value["historyEntryIds"]) and value["historyEntryIds"][0] != value["historyEntryIds"][1])
  require(type(value["firstKeptEntryId"]) is int and value["firstKeptEntryId"] == value["historyEntryIds"][1])
  counts = value["metadataGetModel"]; require(type(counts) is dict and set(counts) == {"old", "fresh"} and all(exact_integer(item, 1) and item <= 32 for item in counts.values()))
  if case == CASES[0]:
    require(exact_integer(value["summarySubmissionId"], 1) and exact_integer(value["summaryEntryId"], 1) and type(value["summaryHeadEntryId"]) is int and value["summaryHeadEntryId"] == value["firstKeptEntryId"])
  else: require(all(value[name] is None for name in ("summarySubmissionId", "summaryEntryId", "summaryHeadEntryId")))
  return value


def post_work(work):
  private_directory(work)
  directories = {"home", "config", "data", "cache", "state", "tmp", "empty-bin"}
  files = {"database.sqlite", "database.sqlite-wal", "database.sqlite-shm", "state.json"}
  names = {child.name for child in work.iterdir()}
  require(directories | {"database.sqlite", "state.json"} <= names and names <= directories | files)
  for child in work.iterdir():
    if child.name in directories:
      private_directory(child); require(not list(child.iterdir()))
    else:
      require(child.name in files); read_private(child, MAX_PLAN)
  require((work / "state.json").is_file() and (work / "database.sqlite").is_file())

def post_case(directory, result_file=True):
  private_directory(directory)
  names = {"work", "invocation.json", "stdout.raw", "stderr.raw"}
  if result_file: names.add("case-result.json")
  require({child.name for child in directory.iterdir()} == names)
  for name in names - {"work"}: read_private(directory / name)
  post_work(directory / "work")

def case_result(case):
  return {"case": case, "started": False, "exitCode": None, "outcome": "not-run", "phase": "setup", "namespaceTermination": "unknown"}

def run_case(case, directory, deadline, result=None):
  if result is None: result = case_result(case)
  private_directory(directory); require(not list(directory.iterdir()))
  work = directory / "work"; work.mkdir(mode=0o700)
  for name in ("home", "config", "data", "cache", "state", "tmp", "empty-bin"): (work / name).mkdir(mode=0o700)
  selected = invocation(case, work); write_new(directory / "invocation.json", selected)
  result["phase"] = "launch"
  process = None; output = {"stdout": bytearray(), "stderr": bytearray()}; fds = {}
  until = min(deadline, time.monotonic() + 30)
  try:
    for name in output: fds[name] = os.open(directory / (name + ".raw"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    process = subprocess.Popen(selected["argv"], cwd=directory, env=selected["env"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, shell=False, start_new_session=True)
    result["started"] = True; result["phase"] = "capture"
    with selectors.DefaultSelector() as selector:
      selector.register(process.stdout, selectors.EVENT_READ, "stdout"); selector.register(process.stderr, selectors.EVENT_READ, "stderr")
      while selector.get_map():
        require(time.monotonic() < until)
        for key, _ in selector.select(0.1):
          chunk = os.read(key.fileobj.fileno(), 65536)
          if not chunk: selector.unregister(key.fileobj); continue
          require(sum(map(len, output.values())) + len(chunk) <= MAX_BYTES)
          output[key.data].extend(chunk); require(os.write(fds[key.data], chunk) == len(chunk))
          if key.data == "stdout": require(len(output[key.data]) <= MAX_LINE)
    process.wait(timeout=max(0.01, min(1, until - time.monotonic()))); result["exitCode"] = process.returncode; result["phase"] = "oracle"
    require(not output["stderr"])
    require(output["stdout"].endswith(b"\n") and output["stdout"].count(b"\n") == 1)
    value = decode(output["stdout"])
    state = decode(read_private(work / "state.json", MAX_LINE))
    require(strict_equal(value, state))
    oracle(case, value, process.returncode); oracle(case, state, process.returncode); post_work(work)
    result["outcome"] = "observed"; result["phase"] = "complete"
  except (Exception, KeyboardInterrupt): result["outcome"] = "failed" if result["started"] else "not-run"
  finally:
    persistence_failed = False
    def persistence_failure():
      nonlocal persistence_failed
      persistence_failed = True
      result["outcome"] = "failed" if result["started"] else "not-run"
      result["phase"] = "persistence"
    try:
      if process is not None:
        if process.poll() is None:
          # 仅本次保存的 processgroup；不是整个 namespace/后代停止资格。
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
          if stream:
            try: stream.close()
            except OSError: persistence_failure()
    except OSError: persistence_failure()
    for fd in fds.values():
      try: os.fsync(fd)
      except OSError: persistence_failure()
      finally:
        try: os.close(fd)
        except OSError: persistence_failure()
    try: post_case(directory, result_file=False)
    except OSError: persistence_failure()
    except ProbeError:
      if result["outcome"] == "observed": result["outcome"] = "failed"; result["phase"] = "post-inventory"
    try: write_new(directory / "case-result.json", result)
    except (OSError, ProbeError): persistence_failure()
    try: post_case(directory)
    except OSError: persistence_failure()
    except ProbeError:
      if result["outcome"] == "observed": result["outcome"] = "failed"; result["phase"] = "post-inventory"
    # 父级持有同一 mutable row；原始 IO 故障不能变为 not-run 或被算作成功。
    if persistence_failed: raise ProbeError("capture persistence unknown")
  return result

class Parser(argparse.ArgumentParser):
  def error(self, _): raise ProbeError("invalid arguments")

def main(argv=None):
  parser = Parser(allow_abbrev=False)
  parser.add_argument("action", choices=("prepare", "run-native")); parser.add_argument("--directory", required=True)
  parser.add_argument("--native-durable-summary-recovery-probe", action="store_true")
  try:
    args = parser.parse_args(argv); directory = Path(args.directory); private_directory(directory)
    if args.action == "prepare":
      require(not args.native_durable_summary_recovery_probe); prepare(directory); print("durable summary recovery prepared; nativeStarted=false; nativeAuthorized=false"); return 0
    require(args.native_durable_summary_recovery_probe)
    require({child.name for child in directory.iterdir()} == {"plan.json"})
    plan = validate_plan(decode(read_private(directory / "plan.json")), directory)
    write_new(directory / "started.json", {"schema": 1, "planSha256": sha(read_private(directory / "plan.json")), "nativeRequested": True})
    deadline = time.monotonic() + 90; results = []; parent_failed = False; intact = False
    try:
      for case in CASES:
        stopped = bool(results and results[-1]["outcome"] != "observed")
        current = case_result(case); results.append(current)
        child = directory / case; child.mkdir(mode=0o700)
        if stopped: current["phase"] = "not-run"
        else: run_case(case, child, deadline, result=current)
    except (Exception, KeyboardInterrupt):
      parent_failed = True
      if results and results[-1]["started"]:
        results[-1]["outcome"] = "failed"
        if results[-1]["phase"] == "complete": results[-1]["phase"] = "persistence"
    finally:
      # 后续目录/父级异常不能抹去此前已执行的原始捕获与身份。
      for case in CASES[len(results):]: results.append(case_result(case))
      try: intact = strict_equal(plan["material"], material())
      except (ProbeError, OSError): pass
      write_new(directory / "execution.json", {"schema": 1, "cases": results, "parentFailed": parent_failed, "materialIntact": intact, "namespaceTermination": "unknown"})
    require({child.name for child in directory.iterdir()} == {"plan.json", "started.json", "execution.json", *CASES})
    for item in results:
      child = directory / item["case"]; private_directory(child)
      if item["started"]: post_case(child)
      else: require(not list(child.iterdir()))
    for name in ("plan.json", "started.json", "execution.json"): read_private(directory / name)
    return 0 if not parent_failed and intact and all(case["outcome"] == "observed" for case in results) else 1
  except (ProbeError, OSError, ValueError): print("durable summary recovery preparation/execution or aggregate persistence unknown", file=sys.stderr); return 2

if __name__ == "__main__": raise SystemExit(main())
