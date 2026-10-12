"""公开SDK用户意图合成探针；准备不加载SDK，运行需要独立明确授权。"""

import argparse
import hashlib
import os
from pathlib import Path
import stat

from .paths import _absolute_directory
from .storage import Tree
from .pi_reviewer_sdk_probe import (ROOT, CANDIDATE, NODE, BWRAP, TIMEOUT, MAX_OUTPUT, MAX_PLAN,
  directory, encode, decode, source_records, candidate_records, system_records, tree_records, capture)
from .schema import ConfigError


PROBE_ID = "confirmed-intent-public-sdk-async-v2"
CASES = ("confirmed-idle", "declined", "no-ui", "base", "off", "unrelated-input",
  "nested-follow-up", "handled-input", "canceled", "settling-deferred", "async-confirmed", "async-late-resolve", "async-late-reject")
SOURCES = ("scripts/pi-probe-intent-scope.mjs", "agents/pi/runtime/confirmed-intent-scope.ts")
# 固定当前AST可达自有父Python闭包；依赖文件漂移同样使准备失效。
# Python解释器/stdlib/jsonschema/referencing属于受信父环境，不宣称完整系统闭包。
CONTROLLERS = ("scripts/pi-probe-intent-scope.py", "src/agentcfg/__init__.py", "src/agentcfg/adapter.py",
  "src/agentcfg/omp_env.py", "src/agentcfg/paths.py", "src/agentcfg/pi_intent_scope_probe.py",
  "src/agentcfg/pi_reviewer_sdk_probe.py", "src/agentcfg/schema.py", "src/agentcfg/secrets.py", "src/agentcfg/storage.py")
ENV = {"HOME": "/work/home", "PWD": "/work", "PATH": "/work/empty-bin", "TMPDIR": "/work/tmp",
  "XDG_CONFIG_HOME": "/work/config", "XDG_DATA_HOME": "/work/data", "XDG_CACHE_HOME": "/work/cache",
  "XDG_STATE_HOME": "/work/state", "LC_ALL": "C.UTF-8", "PI_PROBE_NATIVE": "1", "PI_OFFLINE": "1",
  "PI_SKIP_VERSION_CHECK": "1", "OTEL_SDK_DISABLED": "true"}
PLAN_KEYS = {"schema_version", "probe_id", "cases", "sources", "controllers", "candidate", "system", "environment", "invocation"}
RESULT_KEYS = {"schema_version", "probe_id", "status", "cases", "product_gate"}
CASE_KEYS = {"case_id", "outcome", "confirm_calls", "intent_allocations", "request_allocations", "model_requests",
  "scoped_tool_calls", "unscoped_tool_calls", "command_status", "extension_errors", "async_binding_waits", "async_late_results"}
WORK_DIRECTORIES = {"home", "tmp", "empty-bin", "config", "data", "cache", "state"}
EXPECTED = {
  "confirmed-idle": (1, 1, 1, 2, 1, 0, "settled"),
  "declined": (1, 0, 0, 0, 0, 0, "declined"),
  "no-ui": (0, 0, 0, 0, 0, 0, "unavailable"),
  "base": (0, 0, 0, 0, 0, 0, "not-called"),
  "off": (0, 0, 0, 0, 0, 0, "not-called"),
  "unrelated-input": (0, 0, 0, 2, 0, 1, None),
  # tool continuation先走nested/leaf/stop，之后drain已排follow-up，再调用一次合成模型。
  "nested-follow-up": (1, 1, 1, 4, 1, 1, "retired"),
  "handled-input": (1, 1, 0, 0, 0, 0, "not-started"),
  "canceled": (1, 1, 1, 1, 1, 0, "retired"),
  "settling-deferred": (1, 1, 0, 3, 0, 1, "not-started"),
  "async-confirmed": (1, 1, 1, 2, 1, 0, "settled"),
  "async-late-resolve": (1, 1, 1, 2, 0, 1, "retired"),
  "async-late-reject": (1, 1, 1, 2, 0, 1, "retired"),
}


def require(value):
  if not value: raise ConfigError("pi-intent-scope-probe")


def build_invocation(path):
  path = directory(path)
  argv = [str(TIMEOUT), "--signal=TERM", "--kill-after=5s", "95s", str(BWRAP), "--die-with-parent", "--unshare-all",
    "--new-session", "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
    "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--ro-bind", str(CANDIDATE), "/candidate", "--ro-bind", str(NODE), "/node",
    "--ro-bind", str(path / "bundle"), "/probe", "--bind", str(path / "work"), "/work"]
  for name, value in ENV.items(): argv.extend(["--setenv", name, value])
  argv.extend(["--chdir", "/work", "/node/bin/node", "--experimental-import-meta-resolve", "--max-old-space-size=512",
    "/probe/scripts/pi-probe-intent-scope.mjs", "--native-intent-scope-probe"])
  return argv


def prepare(value):
  path = directory(value)
  with _absolute_directory(path.parent) as parent: os.mkdir(path.name, 0o700, dir_fd=parent)
  sources = source_records(SOURCES)
  with Tree(path) as tree, Tree(ROOT, private=False) as source:
    for name, record in sources.items():
      raw = source.read(name, max_bytes=MAX_OUTPUT)[0]
      require(hashlib.sha256(raw).hexdigest() == record["sha256"])
      tree.write_new("bundle/" + name, raw)
    os.mkdir(path / "work", 0o700)
    for name in ("home", "tmp", "empty-bin", "config", "data", "cache", "state"):
      os.mkdir(path / "work" / name, 0o700)
    plan = {"schema_version": 1, "probe_id": PROBE_ID, "cases": list(CASES), "sources": sources,
      "controllers": source_records(CONTROLLERS), "candidate": candidate_records(), "system": system_records(),
      "environment": ENV, "invocation": build_invocation(path)}
    require(len(encode(plan)) <= MAX_PLAN)
    tree.write_new("plan.json", encode(plan))
  return preflight(path)


def verify_bundle(path, plan):
  bundle = tree_records(path / "bundle")
  directories = {"."} | {p.as_posix() for name in SOURCES for p in Path(name).parents if str(p) != "."}
  require({name for name, record in bundle.items() if record["kind"] == "directory"} == directories)
  require({name for name, record in bundle.items() if record["kind"] != "directory"} == set(SOURCES))
  require(all(record["uid"] == os.geteuid() and stat.S_IMODE(record["identity"][2]) == 0o700
    for record in bundle.values() if record["kind"] == "directory"))
  with Tree(path / "bundle") as frozen:
    for name in SOURCES:
      record = bundle[name]
      require(record["kind"] == "file" and stat.S_IMODE(record["identity"][2]) == 0o600
        and record["sha256"] == plan["sources"][name]["sha256"])
      # Tree同时验证单链接、私有属主和固定句柄；仅相同内容不足以认可危险别名。
      item = frozen.read(name, max_bytes=MAX_OUTPUT)
      require(item is not None and item[1] == 0o600 and hashlib.sha256(item[0]).hexdigest() == record["sha256"])


def verify_work(path, *, after=False):
  # 固定 MJS 每场景只建立 cwd/agent 空目录；其他认证/cache/session 工件不得成功留存。
  cases = {"case-" + case for case in CASES} if after else set()
  with Tree(path / "work") as work:
    require(work.fd is not None and set(os.listdir(work.fd)) == WORK_DIRECTORIES | cases | ({"intent-scope-result.json"} if after else set()))
    for name in WORK_DIRECTORIES:
      with Tree(path / "work" / name) as child:
        require(child.fd is not None and not os.listdir(child.fd))
    for name in cases:
      with Tree(path / "work" / name) as case:
        require(case.fd is not None and set(os.listdir(case.fd)) == {"agent"})
      with Tree(path / "work" / name / "agent") as agent:
        require(agent.fd is not None and not os.listdir(agent.fd))
    if after:
      item = work.read("intent-scope-result.json", max_bytes=MAX_OUTPUT)
      require(item is not None and item[1] == 0o600)


def preflight(value):
  path = directory(value)
  with Tree(path) as tree:
    require(set(os.listdir(tree.fd)) == {"plan.json", "bundle", "work"})
    item = tree.read("plan.json", max_bytes=MAX_PLAN)
    require(item is not None and item[1] == 0o600 and tree.read("started.json", max_bytes=MAX_OUTPUT) is None)
    plan = decode(item[0])
    require(type(plan) is dict and set(plan) == PLAN_KEYS and type(plan["schema_version"]) is int
      and plan["schema_version"] == 1 and plan["probe_id"] == PROBE_ID and plan["cases"] == list(CASES))
    require(plan["sources"] == source_records(SOURCES) and plan["controllers"] == source_records(CONTROLLERS)
      and plan["candidate"] == candidate_records() and plan["system"] == system_records()
      and plan["environment"] == ENV and plan["invocation"] == build_invocation(path))
    verify_bundle(path, plan)
    # 私有目录句柄拒绝work/子目录链接、外部属主及非0700；仅对空目录准备运行。
    verify_work(path)
  return {"schema_version": 1, "status": "prepared", "probe_id": PROBE_ID,
    "native_started": False, "cases": len(CASES), "product_gate": False}


def verify_result(value):
  require(type(value) is dict and set(value) == RESULT_KEYS and type(value["schema_version"]) is int
    and value["schema_version"] == 1 and value["probe_id"] == PROBE_ID and value["status"] == "observed"
    and value["product_gate"] is False and type(value["cases"]) is list and len(value["cases"]) == len(CASES))
  counters = ("confirm_calls", "intent_allocations", "request_allocations", "model_requests", "scoped_tool_calls", "unscoped_tool_calls")
  for case, row in zip(CASES, value["cases"]):
    require(type(row) is dict and set(row) == CASE_KEYS and row["case_id"] == case and row["outcome"] == "observed")
    expected = EXPECTED[case]
    require(all(type(row[key]) is int and row[key] == count for key, count in zip(counters, expected[:6])))
    require(type(row["async_binding_waits"]) is int and row["async_binding_waits"] == (2 if case == "async-confirmed" else 1 if case.startswith("async-") else 0))
    require(type(row["async_late_results"]) is int and row["async_late_results"] == (1 if case in ("async-late-resolve", "async-late-reject") else 0))
    require(row["command_status"] == expected[6] and type(row["extension_errors"]) is int and row["extension_errors"] == 0)
  return value


def run_native(value):
  path = directory(value)
  preflight(path)
  with Tree(path) as tree:
    tree.write_new("started.json", encode({"schema_version": 1, "probe_id": PROBE_ID, "native_launch_requested": True}))
  try:
    execution, stdout = capture(build_invocation(path))
  except Exception:
    execution = {"probe_id": PROBE_ID, "verification": "failed", "native_started": None, "exit_code": None,
      "stdout_bytes": None, "stderr_bytes": None, "capture_failed": True, "product_gate": False,
      "namespace_termination": "not-independently-observed", "failure_code": "PI_INTENT_SCOPE_PROBE_CAPTURE_FAILED"}
    with Tree(path) as tree: tree.write_new("execution.json", encode(execution))
    raise ConfigError("pi-intent-scope-probe") from None
  result = None
  try:
    require(execution["exit_code"] == 0 and execution["capture_failed"] is False)
    with Tree(path / "work") as tree:
      item = tree.read("intent-scope-result.json", max_bytes=MAX_OUTPUT)
      require(item is not None and item[1] == 0o600)
    result = verify_result(decode(item[0]))
    summary = decode(stdout)
    require(type(summary) is dict and set(summary) == {"schema_version", "status", "cases", "product_gate"}
      and type(summary["schema_version"]) is int and summary["schema_version"] == 1 and summary["status"] == "observed"
      and type(summary["cases"]) is int and summary["cases"] == len(CASES) and summary["product_gate"] is False)
    with Tree(path) as tree: plan = decode(tree.read("plan.json", max_bytes=MAX_PLAN)[0])
    require(plan["candidate"] == candidate_records() and plan["sources"] == source_records(SOURCES)
      and plan["controllers"] == source_records(CONTROLLERS) and plan["system"] == system_records())
    verify_bundle(path, plan)
    verify_work(path, after=True)
    with Tree(path) as tree:
      require(set(os.listdir(tree.fd)) == {"plan.json", "bundle", "work", "started.json"})
  except Exception:
    execution["verification"] = "failed"
  else:
    execution["verification"] = "observed"
  execution.update(probe_id=PROBE_ID, native_started=True, product_gate=False,
    namespace_termination="not-independently-observed")
  with Tree(path) as tree: tree.write_new("execution.json", encode(execution))
  require(execution["verification"] == "observed")
  return {"schema_version": 1, "status": "observed", "cases": len(result["cases"]), "product_gate": False}


def main(argv=None):
  parser = argparse.ArgumentParser(description="Private public-SDK intent-scope synthetic probe")
  parser.add_argument("mode", choices=("prepare", "preflight", "run"))
  parser.add_argument("--directory", required=True)
  parser.add_argument("--native-intent-scope-probe", action="store_true")
  args = parser.parse_args(argv)
  try:
    require(args.native_intent_scope_probe is (args.mode == "run"))
    result = {"prepare": prepare, "preflight": preflight, "run": run_native}[args.mode](args.directory)
    print(encode(result).decode().strip())
    return 0
  except Exception:
    print('{"status":"failed","error_code":"PI_INTENT_SCOPE_PROBE_FAILED","product_gate":false}')
    return 5
