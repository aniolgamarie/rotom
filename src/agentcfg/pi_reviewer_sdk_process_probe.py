"""官方SDK/fresh-process共享模型十一场景组合探针；准备不加载SDK，运行需要独立明确授权。"""

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


PROBE_ID = "reviewer-sdk-process-shared-v2"
CASES = ("allow", "ask", "deny", "missing-usage", "wrong-model", "canceled", "response-limit", "hard-deny", "human-required", "text-allow", "input-unqualified")
SOURCES = ("scripts/pi-probe-reviewer-sdk-process.mjs", "agents/pi/packages/risk-review/package.json",
  *("agents/pi/packages/risk-review/src/" + name + ".ts" for name in
    ("protocol", "wire-fetch", "request-wire", "transport", "sdk-worker", "sdk-worker-entry", "request-headers", "process-frames", "sdk-process", "sdk-process-entry", "shared-model", "shared-sdk-contract", "shared-request-wire")))
# 固定当前AST可达自有父Python闭包；依赖文件漂移同样使准备失效。
# Python解释器/stdlib/jsonschema/referencing属于受信父环境，不宣称完整系统闭包。
CONTROLLERS = ("scripts/pi-probe-reviewer-sdk-process.py", "src/agentcfg/__init__.py", "src/agentcfg/adapter.py",
  "src/agentcfg/omp_env.py", "src/agentcfg/paths.py", "src/agentcfg/pi_reviewer_sdk_process_probe.py",
  "src/agentcfg/pi_reviewer_sdk_probe.py", "src/agentcfg/schema.py", "src/agentcfg/secrets.py", "src/agentcfg/storage.py")
# 固定环境与原SDK9污染负控相同；fresh child仅接OPENAI_LOG=off。
from .pi_reviewer_sdk_probe import ENV
PLAN_KEYS = {"schema_version", "probe_id", "cases", "sources", "controllers", "candidate", "system", "environment", "invocation"}
RESULT_KEYS = {"schema_version", "probe_id", "status", "cases", "product_gate"}
CASE_KEYS = {"case_id", "outcome", "transport_outcome", "decision", "requests", "usage", "child_started",
  "child_close_observed", "child_stdout_bytes", "child_stderr_bytes", "scope_termination", "model_identity", "wire"}
WORK_DIRECTORIES = {"home", "tmp", "empty-bin", "config", "data", "cache", "state"}


def require(value):
  if not value: raise ConfigError("pi-reviewer-sdk-process-probe")


def build_invocation(path):
  path = directory(path)
  argv = [str(TIMEOUT), "--signal=TERM", "--kill-after=5s", "95s", str(BWRAP), "--die-with-parent", "--unshare-all",
    "--new-session", "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
    "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--ro-bind", str(CANDIDATE), "/candidate", "--ro-bind", str(NODE), "/node",
    "--ro-bind", str(path / "bundle"), "/probe", "--bind", str(path / "work"), "/work"]
  for name, value in ENV.items(): argv.extend(["--setenv", name, value])
  argv.extend(["--chdir", "/work", "/node/bin/node", "--experimental-import-meta-resolve", "--max-old-space-size=512",
    "/probe/scripts/pi-probe-reviewer-sdk-process.mjs", "--native-reviewer-sdk-process-probe"])
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
  # 成功输出仅一个声明文件；不得把额外认证/cache/session工件留存当成功。
  with Tree(path / "work") as work:
    require(work.fd is not None and set(os.listdir(work.fd)) == WORK_DIRECTORIES | ({"reviewer-process-result.json"} if after else set()))
    for name in WORK_DIRECTORIES:
      with Tree(path / "work" / name) as child:
        require(child.fd is not None and not os.listdir(child.fd))
    if after:
      saved = work.read("reviewer-process-result.json", max_bytes=MAX_OUTPUT)
      require(saved is not None and saved[1] == 0o600)


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


def shared_identity(case):
  # 非秘密固定模板独立重算variant；不是信任子进程自报身份。
  import json
  text = case == "text-allow"; identifier = "synthetic-text" if text else "synthetic-reviewer"
  base = {"id": identifier, "provider": "synthetic-provider", "api": "openai-completions", "name": "Actual Synthetic Text" if text else "Actual Synthetic DeepSeek", "baseUrl": "https://synthetic-review.invalid/v1", "reasoning": not text, "input": ["text", "image"], "cost": {"input": 1, "output": 2, "cacheRead": 0.1, "cacheWrite": 0}, "contextWindow": 1000000, "maxTokens": 384000, "compat": {"requiresReasoningContentOnAssistantMessages": True, "thinkingFormat": "deepseek"}, "thinkingLevelMap": {"low": "low", "medium": "high", "high": "high"}}
  model = {**base, "compat": {**base["compat"], "supportsStore": False, "supportsDeveloperRole": False, "supportsUsageInStreaming": True, "maxTokensField": "max_tokens"}}
  packet = {"base_model": base, "sdk_model": model, "request_policy": {"schema_version": 1, "purpose": "risk-review", "input_mode": "single-text", "reasoning_mode": "off", "max_retries": 0, "temperature": 0, "stream": True, "include_usage": True, "input_tokens": 12000, "output_tokens": 4096}, "route": {"logical_provider": "synthetic-provider", "native_route": "synthetic-provider", "model_id": identifier, "auth_kind": "api-key", "owner": "pi-environment", "api": "openai-completions", "base_url": "https://synthetic-review.invalid/v1"}, "configuration_identity": "e" * 64}
  return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def verify_result(value):
  require(type(value) is dict and set(value) == RESULT_KEYS and type(value["schema_version"]) is int
    and value["schema_version"] == 1 and value["probe_id"] == PROBE_ID and value["status"] == "observed"
    and value["product_gate"] is False and type(value["cases"]) is list and len(value["cases"]) == len(CASES))
  outcomes = {"wrong-model": "transport-failure", "canceled": "canceled", "response-limit": "transport-failure", "hard-deny": "policy-blocked", "human-required": "human-required", "input-unqualified": "transport-failure"}
  for case, row in zip(CASES, value["cases"]):
    require(type(row) is dict and set(row) == CASE_KEYS and row["case_id"] == case and row["outcome"] == "observed")
    require(row["transport_outcome"] == outcomes.get(case, "valid"))
    require(row["decision"] == (case if case in ("allow", "ask", "deny") else "allow" if case in ("missing-usage", "text-allow") else None))
    started = case not in ("hard-deny", "human-required", "input-unqualified")
    require(type(row["requests"]) is int and row["requests"] == int(started)
      and row["child_started"] is started and row["child_close_observed"] is started
      and row["scope_termination"] == "not-independently-observed")
    for key in ("child_stdout_bytes", "child_stderr_bytes"):
      require(type(row[key]) is int and row[key] == 0)
    require(row["model_identity"] == shared_identity(case))
    wire = row["wire"]
    if not started: require(wire is None)
    else:
      require(type(wire) is dict and set(wire) == {"shape", "model", "max_tokens", "thinking"})
      require(wire["shape"] == ("openai-chat-text" if case == "text-allow" else "deepseek-chat-text-disabled") and wire["model"] == ("synthetic-text" if case == "text-allow" else "synthetic-reviewer") and type(wire["max_tokens"]) is int and wire["max_tokens"] == 4096)
      if case == "text-allow": require(wire["thinking"] is None)
      else: require(type(wire["thinking"]) is dict and set(wire["thinking"]) == {"type"} and wire["thinking"]["type"] == "disabled")
    usage = row["usage"]; require(type(usage) is dict and set(usage) == {"status", "input_tokens", "output_tokens", "total_tokens"})
    reported = case in ("allow", "ask", "deny", "text-allow")
    require(usage["status"] == ("reported" if reported else "unknown" if started else "not-sent"))
    for key, count in (("input_tokens", 5), ("output_tokens", 3), ("total_tokens", 8)):
      expected = count if reported else None if started else 0
      require(usage[key] is None if expected is None else type(usage[key]) is int and usage[key] == expected)
  return value


def run_native(value):
  path = directory(value)
  preflight(path)
  with Tree(path) as tree:
    tree.write_new("started.json", encode({"schema_version": 1, "probe_id": PROBE_ID, "native_launch_requested": True}))
  try:
    execution, stdout = capture(build_invocation(path))
  except Exception:
    execution = {"probe_id": PROBE_ID, "verification": "failed", "outer_launcher_started": None,
      "sdk_execution_observed": False, "exit_code": None,
      "stdout_bytes": None, "stderr_bytes": None, "capture_failed": True, "product_gate": False,
      "namespace_termination": "not-independently-observed", "failure_code": "PI_REVIEWER_SDK_PROCESS_PROBE_CAPTURE_FAILED"}
    with Tree(path) as tree: tree.write_new("execution.json", encode(execution))
    raise ConfigError("pi-reviewer-sdk-process-probe") from None
  result = None
  try:
    require(execution["exit_code"] == 0 and execution["capture_failed"] is False)
    with Tree(path / "work") as tree:
      item = tree.read("reviewer-process-result.json", max_bytes=MAX_OUTPUT)
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
  execution.update(probe_id=PROBE_ID, outer_launcher_started=True,
    sdk_execution_observed=execution["verification"] == "observed", product_gate=False,
    namespace_termination="not-independently-observed")
  with Tree(path) as tree: tree.write_new("execution.json", encode(execution))
  require(execution["verification"] == "observed")
  return {"schema_version": 1, "status": "observed", "cases": len(result["cases"]), "product_gate": False}


def main(argv=None):
  parser = argparse.ArgumentParser(description="Private offline public-SDK fresh-process probe")
  parser.add_argument("mode", choices=("prepare", "preflight", "run"))
  parser.add_argument("--directory", required=True)
  parser.add_argument("--native-reviewer-sdk-process-probe", action="store_true")
  args = parser.parse_args(argv)
  try:
    require(args.native_reviewer_sdk_process_probe is (args.mode == "run"))
    result = {"prepare": prepare, "preflight": preflight, "run": run_native}[args.mode](args.directory)
    print(encode(result).decode().strip())
    return 0
  except Exception:
    print('{"status":"failed","error_code":"PI_REVIEWER_SDK_PROCESS_PROBE_FAILED","product_gate":false}')
    return 5
