"""独立reviewer SDK合成探针；准备只读来源，原生运行必须另获明确授权。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

from .paths import _absolute_directory
from .schema import ConfigError
from .storage import Tree, identity


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / ".cache/pi-two-profiles/candidates/pi-1.0.1/closure"
NODE = Path("/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0")
BWRAP = Path("/usr/bin/bwrap")
TIMEOUT = Path("/usr/bin/timeout")
LOCK_SHA = "f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac"
PROBE_ID = "reviewer-sdk-offline-v1"
CASES = ("allow", "ask", "deny", "missing-usage", "wrong-model", "canceled", "response-limit", "hard-deny", "human-required")
SOURCES = ("scripts/pi-probe-reviewer-sdk.mjs", "agents/pi/packages/risk-review/package.json",
  *("agents/pi/packages/risk-review/src/" + name + ".ts" for name in
    ("protocol", "wire-fetch", "request-wire", "transport", "sdk-worker", "sdk-worker-entry", "request-headers")))
CONTROLLERS = ("src/agentcfg/pi_reviewer_sdk_probe.py", "scripts/pi-probe-reviewer-sdk.py")
ENV = {"HOME": "/work/home", "PWD": "/work", "PATH": "/work/empty-bin", "TMPDIR": "/work/tmp",
  "XDG_CONFIG_HOME": "/work/config", "XDG_DATA_HOME": "/work/data", "XDG_CACHE_HOME": "/work/cache",
  "XDG_STATE_HOME": "/work/state", "LC_ALL": "C.UTF-8", "PI_PROBE_NATIVE": "1", "PI_OFFLINE": "1", "OTEL_SDK_DISABLED": "true",
  "OPENAI_LOG": "debug", "OPENAI_API_KEY": "SYNTHETIC_AMBIENT_AUTH", "OPENAI_ADMIN_KEY": "SYNTHETIC_AMBIENT_ADMIN",
  "OPENAI_WEBHOOK_SECRET": "SYNTHETIC_AMBIENT_WEBHOOK", "OPENAI_ORG_ID": "SYNTHETIC_AMBIENT_ORG",
  "OPENAI_CUSTOM_HEADERS": "X-Review-Sentinel: SYNTHETIC_AMBIENT_HEADER"}
MAX_FILE = 256 * 1024 * 1024
MAX_TREE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 30000
MAX_PLAN = 16 * 1024 * 1024
MAX_OUTPUT = 65536
PLAN_KEYS = {"schema_version", "probe_id", "cases", "candidate", "sources", "controllers", "system", "environment", "invocation"}
RESULT_KEYS = {"schema_version", "probe_id", "status", "cases", "product_gate"}
CASE_KEYS = {"case_id", "outcome", "transport_outcome", "decision", "requests", "usage", "worker_started", "worker_terminated"}


def require(value):
  if not value: raise ConfigError("pi-reviewer-sdk-probe")


def encode(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def decode(raw):
  require(type(raw) is bytes and len(raw) <= MAX_PLAN)
  def pairs(items):
    result = {}
    for key, value in items:
      require(key not in result); result[key] = value
    return result
  def invalid(_): raise ConfigError("pi-reviewer-sdk-probe")
  try: return json.loads(raw.decode("utf8"), object_pairs_hook=pairs, parse_constant=invalid)
  except (ValueError, UnicodeError): raise ConfigError("pi-reviewer-sdk-probe") from None


def directory(value):
  require(type(value) in (str, Path) or isinstance(value, Path))
  name = os.fspath(value); path = Path(name)
  require(path.is_absolute() and path != Path("/tmp") and path.is_relative_to("/tmp")
    and str(path) == name and ".." not in path.parts and not any(ord(c) < 32 or ord(c) == 127 for c in name))
  return path


def file_record(path):
  # NONBLOCK避免被替换成FIFO后等待；打开后再检查普通文件与大小。
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
  try:
    before = os.fstat(fd)
    require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE and not before.st_mode & 0o022 and before.st_uid in (0, os.geteuid()))
    digest = hashlib.sha256(); size = 0
    while data := os.read(fd, 1024 * 1024):
      size += len(data); require(size <= MAX_FILE); digest.update(data)
    require(identity(os.fstat(fd)) == identity(before) and identity(os.lstat(path)) == identity(before))
    return {"kind": "file", "identity": list(identity(before)), "uid": before.st_uid, "sha256": digest.hexdigest()}
  finally: os.close(fd)


def tree_records(root):
  require(root.is_absolute() and root.resolve() == root and root.is_dir())
  records = {}; total = 0
  pending = [root]
  while pending:
    path = pending.pop(); info = os.lstat(path); relative = path.relative_to(root).as_posix()
    require(len(records) < MAX_ENTRIES and (stat.S_ISLNK(info.st_mode) or not info.st_mode & 0o022) and info.st_uid in (0, os.geteuid()))
    if stat.S_ISDIR(info.st_mode):
      records[relative] = {"kind": "directory", "identity": [info.st_dev, info.st_ino, info.st_mode], "uid": info.st_uid}
      with os.scandir(path) as entries: pending.extend(sorted((Path(entry.path) for entry in entries), reverse=True))
    elif stat.S_ISREG(info.st_mode):
      record = file_record(path); total += info.st_size; require(total <= MAX_TREE_BYTES); records[relative] = record
    else:
      require(stat.S_ISLNK(info.st_mode))
      target = os.readlink(path); resolved = path.resolve(strict=True)
      require(resolved.is_relative_to(root) and resolved.is_file())
      records[relative] = {"kind": "symlink", "target": target, "identity": list(identity(info)), "uid": info.st_uid}
  return dict(sorted(records.items()))


def candidate_records():
  records = tree_records(CANDIDATE)
  require(records["package-lock.json"]["sha256"] == LOCK_SHA)
  for package, version in (("@earendil-works/pi-coding-agent", "1.0.1"), ("@earendil-works/pi-ai", "1.0.2"), ("openai", "7.19.0")):
    with Tree(CANDIDATE, private=False) as tree:
      item = tree.read("node_modules/" + package + "/package.json", max_bytes=MAX_OUTPUT); require(item is not None)
    manifest = decode(item[0])
    require(manifest.get("name") == package and manifest.get("version") == version)
  return records


def source_records(names):
  with Tree(ROOT, private=False) as tree:
    records = {}
    for name in names:
      item = tree.read(name, max_bytes=MAX_OUTPUT)
      require(item is not None)
      record = file_record(ROOT / name); require(hashlib.sha256(item[0]).hexdigest() == record["sha256"])
      records[name] = record
    return records


def system_records():
  records = {"node": file_record(NODE / "bin/node"), "bwrap": file_record(BWRAP), "timeout": file_record(TIMEOUT)}
  require(all(record["identity"][2] & 0o111 for record in records.values()))
  return records


def build_invocation(work):
  work = directory(work)
  argv = [str(TIMEOUT), "--signal=TERM", "--kill-after=5s", "95s", str(BWRAP), "--die-with-parent", "--unshare-all",
    "--new-session", "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
    "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--ro-bind", str(CANDIDATE), "/candidate", "--ro-bind", str(NODE), "/node",
    "--ro-bind", str(work / "bundle"), "/probe", "--bind", str(work / "work"), "/work"]
  for key, value in ENV.items(): argv.extend(["--setenv", key, value])
  argv.extend(["--chdir", "/work", "/node/bin/node", "--experimental-import-meta-resolve", "--max-old-space-size=512",
    "/probe/scripts/pi-probe-reviewer-sdk.mjs", "--native-reviewer-sdk-probe"])
  return argv, {}


def prepare(value):
  path = directory(value)
  with _absolute_directory(path.parent) as parent:
    os.mkdir(path.name, 0o700, dir_fd=parent)
  # 失败也不删除或覆盖旧材料；该目录必须是本次新建，不接受重复准备。
  sources = source_records(SOURCES)
  with Tree(path) as tree, Tree(ROOT, private=False) as source:
    for name, record in sources.items():
      raw = source.read(name, max_bytes=MAX_OUTPUT)[0]
      require(hashlib.sha256(raw).hexdigest() == record["sha256"])
      tree.write_new("bundle/" + name, raw)
    os.mkdir(path / "work", 0o700)
    for name in ("home", "tmp", "empty-bin", "config", "data", "cache", "state"): os.mkdir(path / "work" / name, 0o700)
    plan = {"schema_version": 1, "probe_id": PROBE_ID, "cases": list(CASES), "candidate": candidate_records(),
      "sources": sources, "controllers": source_records(CONTROLLERS), "system": system_records(), "environment": ENV,
      "invocation": build_invocation(path)[0]}
    require(len(encode(plan)) <= MAX_PLAN); tree.write_new("plan.json", encode(plan))
  preflight(path)
  return {"status": "prepared", "probe_id": PROBE_ID, "native_started": False, "source_files": len(sources), "candidate_entries": len(plan["candidate"]), "product_gate": False}


def preflight(value):
  path = directory(value)
  with Tree(path) as tree:
    item = tree.read("plan.json", max_bytes=MAX_PLAN); require(item is not None and item[1] == 0o600)
    require(tree.read("started.json", max_bytes=MAX_OUTPUT) is None)
    plan = decode(item[0]); require(type(plan) is dict and set(plan) == PLAN_KEYS)
    require(type(plan["schema_version"]) is int and plan["schema_version"] == 1 and plan["probe_id"] == PROBE_ID and plan["cases"] == list(CASES))
    require(plan["sources"] == source_records(SOURCES) and plan["controllers"] == source_records(CONTROLLERS))
    require(plan["system"] == system_records() and plan["candidate"] == candidate_records())
    require(plan["environment"] == ENV and plan["invocation"] == build_invocation(path)[0])
    bundle = tree_records(path / "bundle")
    directories = {"."} | {parent.as_posix() for name in SOURCES for parent in Path(name).parents if str(parent) != "."}
    require({name for name, record in bundle.items() if record["kind"] == "directory"} == directories)
    require({name for name, record in bundle.items() if record["kind"] != "directory"} == set(SOURCES))
    for name in SOURCES:
      record = bundle[name]; require(record["kind"] == "file" and stat.S_IMODE(record["identity"][2]) == 0o600 and record["sha256"] == plan["sources"][name]["sha256"])
    # 工作目录不能夹带账号、已有输出或额外文件；所有写入只在显式run后发生。
    with _absolute_directory(path / "work"):
      require(set(os.listdir(path / "work")) == {"home", "tmp", "empty-bin", "config", "data", "cache", "state"})
      for child in (path / "work").iterdir():
        require(not child.is_symlink() and child.is_dir() and stat.S_IMODE(child.stat().st_mode) == 0o700 and not list(child.iterdir()))
  return {"status": "prepared", "probe_id": PROBE_ID, "native_started": False, "product_gate": False}


def verify_result(value):
  require(type(value) is dict and set(value) == RESULT_KEYS and type(value["schema_version"]) is int and value["schema_version"] == 1
    and value["probe_id"] == PROBE_ID and value["status"] == "observed" and value["product_gate"] is False)
  require(type(value["cases"]) is list and len(value["cases"]) == len(CASES))
  outcomes = {"wrong-model": "transport-failure", "canceled": "canceled", "response-limit": "transport-failure", "hard-deny": "policy-blocked", "human-required": "human-required"}
  for case, row in zip(CASES, value["cases"]):
    require(type(row) is dict and set(row) == CASE_KEYS and row["case_id"] == case and row["outcome"] == "observed")
    require(row["transport_outcome"] == outcomes.get(case, "valid"))
    require(row["decision"] == (case if case in ("allow", "ask", "deny") else "allow" if case == "missing-usage" else None))
    started = case not in ("hard-deny", "human-required")
    require(type(row["requests"]) is int and row["requests"] == int(started)
      and row["worker_started"] is started and row["worker_terminated"] is started)
    usage = row["usage"]; require(type(usage) is dict and set(usage) == {"status", "input_tokens", "output_tokens", "total_tokens"})
    reported = case in ("allow", "ask", "deny")
    require(usage["status"] == ("reported" if reported else "unknown" if started else "not-sent"))
    for key, count in (("input_tokens", 5), ("output_tokens", 3), ("total_tokens", 8)):
      expected = count if reported else None if started else 0
      require(usage[key] is None if expected is None else type(usage[key]) is int and usage[key] == expected)
  return value


def capture(argv):
  """有界drain；stderr丢弃不摘要，stdout仅保留最多64KiB待闭合验证。"""
  process = subprocess.Popen(argv, env={}, cwd="/tmp", stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
  counts = {"stdout": 0, "stderr": 0}; output = bytearray(); failure = False
  try:
    with selectors.DefaultSelector() as selector:
      for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        os.set_blocking(stream.fileno(), False); selector.register(stream, selectors.EVENT_READ, name)
      deadline = time.monotonic() + 100
      while selector.get_map():
        if time.monotonic() >= deadline: failure = True; break
        for key, _ in selector.select(0.1):
          chunk = os.read(key.fileobj.fileno(), 8192)
          if not chunk: selector.unregister(key.fileobj); continue
          name = key.data; counts[name] += len(chunk)
          if counts[name] > MAX_OUTPUT: failure = True; break
          if name == "stdout": output.extend(chunk)
        if failure: break
    if failure:
      try: os.killpg(process.pid, signal.SIGTERM)
      except ProcessLookupError: pass
      try: process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    exit_code = process.wait(timeout=5)
  finally:
    try:
      # 普通异常同样回收本启动器的进程组；不触碰其它活动实例。
      if process.poll() is None:
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait(timeout=5)
    finally:
      try: process.stdout.close()
      finally: process.stderr.close()
  return {"exit_code": exit_code, "stdout_bytes": counts["stdout"], "stderr_bytes": counts["stderr"], "capture_failed": failure}, bytes(output)


def run_native(value):
  path = directory(value); preflight(path)
  with Tree(path) as tree:
    tree.write_new("started.json", encode({"schema_version": 1, "probe_id": PROBE_ID, "native_launch_requested": True}))
  try: execution, stdout = capture(build_invocation(path)[0])
  except Exception:
    # 可能已经启动，状态不明不能记成未运行或已终止；同一目录仍不可重放。
    execution = {"probe_id": PROBE_ID, "verification": "failed", "native_started": None, "exit_code": None,
      "stdout_bytes": None, "stderr_bytes": None, "capture_failed": True, "product_gate": False,
      "namespace_termination": "not-independently-observed", "failure_code": "PI_REVIEWER_SDK_PROBE_CAPTURE_FAILED"}
    with Tree(path) as tree: tree.write_new("execution.json", encode(execution))
    require(False)
  result = None
  try:
    require(execution["exit_code"] == 0 and execution["capture_failed"] is False)
    with Tree(path / "work") as tree:
      item = tree.read("reviewer-result.json", max_bytes=MAX_OUTPUT); require(item is not None and item[1] == 0o600)
    result = verify_result(decode(item[0])); summary = decode(stdout)
    require(type(summary) is dict and set(summary) == {"schema_version", "status", "cases", "product_gate"}
      and type(summary["schema_version"]) is int and summary["schema_version"] == 1 and summary["status"] == "observed"
      and type(summary["cases"]) is int and summary["cases"] == len(CASES) and summary["product_gate"] is False)
    # 运行后来源也不能漂移；只证明已观察的固定来源，非防同UID加载竞态的原子pin。
    with Tree(path) as tree: plan = decode(tree.read("plan.json", max_bytes=MAX_PLAN)[0])
    require(plan["candidate"] == candidate_records() and plan["sources"] == source_records(SOURCES)
      and plan["controllers"] == source_records(CONTROLLERS) and plan["system"] == system_records())
  except Exception: execution["verification"] = "failed"
  else: execution["verification"] = "observed"
  execution.update(probe_id=PROBE_ID, native_started=True, product_gate=False, namespace_termination="not-independently-observed")
  with Tree(path) as tree: tree.write_new("execution.json", encode(execution))
  require(execution["verification"] == "observed")
  return result


def main(argv=None):
  parser = argparse.ArgumentParser(description="Private reviewer SDK synthetic probe")
  parser.add_argument("mode", choices=("prepare", "preflight", "run")); parser.add_argument("--directory", required=True)
  parser.add_argument("--native-reviewer-sdk-probe", action="store_true")
  args = parser.parse_args(argv)
  try:
    require(args.native_reviewer_sdk_probe is (args.mode == "run"))
    result = {"prepare": prepare, "preflight": preflight, "run": run_native}[args.mode](args.directory)
    print(encode(result).decode().strip()); return 0
  except Exception:
    print('{"status":"failed","error_code":"PI_REVIEWER_SDK_PROBE_FAILED","product_gate":false}'); return 5
