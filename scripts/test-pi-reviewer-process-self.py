"""自有假SDK进程探针：静态prepare默认无spawn，run须独立显式调用。

不挂仓库/官方candidate/账号，结果不证明产品预算或整个进程域终止。
"""
from copy import deepcopy
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
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
NODE = Path("/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node")
BWRAP = Path("/usr/bin/bwrap")
SOURCES = ("protocol", "wire-fetch", "request-wire", "transport", "sdk-worker", "sdk-worker-entry", "request-headers", "process-frames", "sdk-process", "sdk-process-entry", "shared-model", "shared-sdk-contract", "shared-request-wire")
FIXTURES = ("probe", "provider", "transcript")
CODE = "PI_REVIEWER_SELF_PROCESS_FAILED"
MAX_OUTPUT = 65536
PROBE_ID = "reviewer-process-self-shared-v2"


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
  require(snapshot(before) == {key: expected[key] for key in snapshot(before)} and stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 524288)
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
  try:
    require(snapshot(os.fstat(fd)) == snapshot(before)); data = bytearray()
    while len(data) <= 524288:
      chunk = os.read(fd, min(65536, 524289 - len(data)))
      if not chunk: break
      data.extend(chunk)
    require(len(data) <= 524288 and snapshot(os.fstat(fd)) == snapshot(before) == snapshot(path.lstat())
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


def templates():
  return {"package.json": encode({"type": "module"}), "sdk/package.json": encode({"type": "module"}),
    "sdk/node_modules/@earendil-works/pi-ai/package.json": encode({"name": "@earendil-works/pi-ai", "version": "0.0.0-self-owned",
      "type": "module", "exports": {"./api/openai-completions": {"import": "./provider.mjs"}, "./utils/transcript": {"import": "./transcript.mjs"}}})}


def sources(root):
  return {"sources": {name: file_record(root / "agents/pi/packages/risk-review/src" / (name + ".ts"), max_bytes=524288) for name in SOURCES},
    "fixtures": {name: file_record(root / "tests/fixtures/pi/reviewer-process-self-probe" / (name + ".mjs"), max_bytes=524288) for name in FIXTURES}}


def binaries():
  values = {"node": file_record(NODE), "bwrap": file_record(BWRAP)}
  for value in values.values(): require(value["mode"] & 0o111 and not value["mode"] & 0o6022)
  return values


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
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600); files[name] = file_record(item, max_bytes=524288)
  visit(root)
  return files, directories


def prepare(root=ROOT, tmp_parent=Path("/tmp")):
  try:
    require(sys.platform == "linux")
    root, parent = canonical(root), canonical(tmp_parent)
    require(parent == Path("/tmp") or Path("/tmp") in parent.parents)
    pinned = sources(root); binary = binaries()
    directory = Path(tempfile.mkdtemp(prefix="agentcfg-reviewer-self-process-", dir=parent)); directory.chmod(0o700)
    bundle, work = directory / "bundle", directory / "work"
    for path in (bundle, work, work / "home", work / "tmp"): path.mkdir(mode=0o700)
    for name in SOURCES:
      target = bundle / "src" / (name + ".ts"); target.parent.mkdir(mode=0o700, exist_ok=True)
      original = root / "agents/pi/packages/risk-review/src" / (name + ".ts")
      data = source_bytes(original, pinned["sources"][name]); write_new(target, data)
    targets = {"probe": "probe.mjs", "provider": "sdk/node_modules/@earendil-works/pi-ai/provider.mjs", "transcript": "sdk/node_modules/@earendil-works/pi-ai/transcript.mjs"}
    for name, destination in targets.items():
      target = bundle / destination
      for path in reversed(target.parent.parents):
        if bundle in path.parents: path.mkdir(mode=0o700, exist_ok=True)
      target.parent.mkdir(mode=0o700, exist_ok=True)
      data = source_bytes(root / "tests/fixtures/pi/reviewer-process-self-probe" / (name + ".mjs"), pinned["fixtures"][name]); write_new(target, data)
    for name, body in templates().items(): write_new(bundle / name, body)
    require(sources(root) == pinned and binaries() == binary)
    files, directories = inventory(bundle)
    manifest = {"schema_version": 1, "probe_id": PROBE_ID, "root": str(root), **pinned, "binaries": binary, "files": files, "directories": directories}
    write_new(directory / "manifest.json", encode(manifest))
    return {"directory": str(directory), "manifest": deepcopy(manifest)}
  except Exception: raise ProbeError() from None


def preflight(prepared, *, after=False):
  closed(prepared, ("directory", "manifest")); directory = canonical(prepared["directory"])
  require(Path("/tmp") in directory.parents and directory.name.startswith("agentcfg-reviewer-self-process-"))
  require(directory.lstat().st_mode & 0o777 == 0o700)
  require({item.name for item in directory.iterdir()} == ({"bundle", "work", "manifest.json", "started.json"} if after else {"bundle", "work", "manifest.json"}))
  value = decode(read(directory / "manifest.json", maximum=1048576)); require(value == prepared["manifest"])
  closed(value, ("schema_version", "probe_id", "root", "sources", "fixtures", "binaries", "files", "directories"))
  require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["probe_id"] == PROBE_ID)
  pinned = sources(canonical(value["root"])); require(pinned["sources"] == value["sources"] and pinned["fixtures"] == value["fixtures"] and binaries() == value["binaries"])
  files, dirs = inventory(directory / "bundle"); require(files == value["files"] and dirs == value["directories"])
  expected = {"src/" + name + ".ts" for name in SOURCES} | set(templates()) | {"probe.mjs", "sdk/node_modules/@earendil-works/pi-ai/provider.mjs", "sdk/node_modules/@earendil-works/pi-ai/transcript.mjs"}
  require(set(files) == expected)
  for name, body in templates().items(): require(read(directory / "bundle" / name) == body)
  work_files, work_dirs = inventory(directory / "work"); require(set(work_dirs) == {"home", "tmp"})
  require(set(work_files) == ({"result.json", *("sdk-observation-" + identifier + ".json" for identifier in ALLOW_IDS)} if after else set()))
  return directory


ALLOW_IDS = ("self-model", "shared-deepseek", "shared-text")
CASES = (("allow", "valid"), ("base", "not-called"), ("off", "not-called"), ("hard", "policy-blocked"),
  ("human", "human-required"), ("shared-deepseek-allow", "valid"), ("shared-text-allow", "valid"),
  ("shared-input-unqualified", "transport-failure"))


def expected_model(identifier):
  shared = identifier != "self-model"
  value = {"id": identifier, "provider": "self-provider", "api": "openai-completions",
    "name": ("Actual Synthetic DeepSeek" if identifier == "shared-deepseek" else "Actual Synthetic Text") if shared else "self-model",
    "baseUrl": "https://self.invalid/v1", "reasoning": identifier == "shared-deepseek", "input": ["text", "image"] if shared else ["text"],
    "cost": {"input": 1, "output": 2, "cacheRead": 0.1 if shared else 1, "cacheWrite": 0 if shared else 1},
    "contextWindow": 1000000 if shared else 32000, "maxTokens": 384000 if shared else 1024,
    "compat": {"supportsStore": False, "supportsDeveloperRole": False, "supportsUsageInStreaming": True, "maxTokensField": "max_tokens"}}
  if shared:
    value["compat"].update(requiresReasoningContentOnAssistantMessages=True, thinkingFormat="deepseek")
    value["thinkingLevelMap"] = {"low": "low", "medium": "high", "high": "high"}
  return value


def expected_identity(identifier):
  model = expected_model(identifier); base = deepcopy(model)
  for key in ("supportsStore", "supportsDeveloperRole", "supportsUsageInStreaming", "maxTokensField"): del base["compat"][key]
  document = {"base_model": base, "sdk_model": model, "request_policy": {"schema_version": 1, "purpose": "risk-review", "input_mode": "single-text", "reasoning_mode": "off", "max_retries": 0, "temperature": 0, "stream": True, "include_usage": True, "input_tokens": 12000, "output_tokens": 4096},
    "route": {"logical_provider": "self-provider", "native_route": "self-provider", "model_id": identifier, "auth_kind": "api-key", "owner": "pi-environment", "api": "openai-completions", "base_url": "https://self.invalid/v1"}, "configuration_identity": "e" * 64}
  return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def verify_observation(value, identifier):
  expected = {"schema_version": 1, "is_worker": True, "ambient_key_absent": True, "environment_data_absent": True,
    "environment_keys": ["OPENAI_LOG"], "log_off": True, "key_not_in_argv": True, "injected_node_options_absent": True}
  closed(value, (*expected, "model", "options", "wire")); require(type(value["schema_version"]) is int and value["schema_version"] == 1)
  for key in expected:
    if key not in ("schema_version", "environment_keys"): require(value[key] is True)
  require(type(value["environment_keys"]) is list and value["environment_keys"] == ["OPENAI_LOG"])
  # canonical JSON比较保持bool/int区别并拒绝额外safe字段；预期不来自被测程序的自报pass。
  shared = identifier != "self-model"
  for key, wanted in (("model", expected_model(identifier)), ("options", {"maxRetries": 0, "maxTokens": 4096 if shared else 1024, "temperature": 0, "reasoning": "off" if shared else None}),
      ("wire", {"model": identifier, "max_tokens": 4096 if shared else 1024, "thinking": {"type": "disabled"} if identifier == "shared-deepseek" else None})):
    require(encode(value[key]) == encode(wanted))


def verify_result(value):
  try:
    closed(value, ("schema_version", "status", "sdk", "cases", "observations", "child_close_observed", "child_stdout_bytes", "child_stderr_bytes", "real_model_requests", "product_gate"))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["status"] == "observed" and value["sdk"] == "self-owned-fake-only")
    require(value["product_gate"] is False and value["child_close_observed"] is True)
    for key in ("child_stdout_bytes", "child_stderr_bytes", "real_model_requests"): require(type(value[key]) is int and value[key] == 0)
    closed(value["observations"], ALLOW_IDS)
    for identifier in ALLOW_IDS: verify_observation(value["observations"][identifier], identifier)
    require(type(value["cases"]) is list and len(value["cases"]) == 8)
    for row, (name, outcome) in zip(value["cases"], CASES):
      closed(row, ("case", "outcome", "requests", "processes", "raw_events", "usage", "model_identity", "scope_termination"))
      require(row["case"] == name and row["outcome"] == outcome and row["scope_termination"] == "not-independently-observed")
      called = outcome == "valid"
      identity = expected_identity("shared-text" if name == "shared-text-allow" else "shared-deepseek") if name.startswith("shared-") else None
      require(row["model_identity"] == identity)
      for key, count in (("requests", int(called)), ("processes", int(called)), ("raw_events", 2 if called else 0)): require(type(row[key]) is int and row[key] == count)
      usage = row["usage"]; closed(usage, ("status", "input_tokens", "output_tokens", "total_tokens")); require(usage["status"] == ("reported" if called else "not-sent"))
      for key, count in (("input_tokens", 5), ("output_tokens", 3), ("total_tokens", 8)): require(type(usage[key]) is int and usage[key] == (count if called else 0))
    return deepcopy(value)
  except Exception: raise ProbeError() from None


def invocation(directory):
  args = [str(BWRAP), "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
  for path in ("/usr", "/lib", "/lib64"):
    if Path(path).exists(): args.extend(("--ro-bind", path, path))
  args.extend(("--dir", "/node", "--dir", "/node/bin", "--ro-bind", str(NODE), "/node/bin/node", "--ro-bind", str(directory / "bundle"), "/probe", "--bind", str(directory / "work"), "/work",
    "--chdir", "/work", "--setenv", "HOME", "/work/home", "--setenv", "TMPDIR", "/work/tmp", "--setenv", "PATH", "/nonexistent", "--setenv", "OPENAI_LOG", "off",
    "--", "/node/bin/node", "--experimental-import-meta-resolve", "/probe/probe.mjs"))
  return args


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
      if failed:
        try: os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          try: os.killpg(child.pid, signal.SIGKILL)
          except ProcessLookupError: pass
      exit_code = child.wait(timeout=max(0.001, min(5, deadline - time.monotonic()))) if not failed else child.wait(timeout=5)
    return {**counts, "exit_code": exit_code, "capture_failed": failed}, bytes(output)
  finally:
    try:
      if child.poll() is None:
        try: os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        child.wait(timeout=5)
    finally:
      child.stdout.close(); child.stderr.close()


def run(prepared):
  try: directory = preflight(prepared)
  except Exception: raise ProbeError() from None
  require(not (directory / "started.json").exists())
  write_new(directory / "started.json", encode({"schema_version": 1, "launch_requested": True}))
  execution = {"schema_version": 1, "probe_id": PROBE_ID, "status": "failed", "exit_code": None, "stdout_bytes": None, "stderr_bytes": None,
    "capture_failed": True, "scope_termination": "not-independently-observed", "product_gate": False, "failure_code": CODE}
  try:
    facts, output = capture(invocation(directory)); execution.update(facts)
    require(facts["exit_code"] == 0 and facts["capture_failed"] is False)
    summary = decode(output); closed(summary, ("schema_version", "status", "cases", "product_gate"))
    require(type(summary["schema_version"]) is int and summary["schema_version"] == 1 and summary["status"] == "observed" and type(summary["cases"]) is int and summary["cases"] == 8 and summary["product_gate"] is False)
    result = verify_result(decode(read(directory / "work/result.json")))
    for identifier in ALLOW_IDS:
      observation = decode(read(directory / "work" / ("sdk-observation-" + identifier + ".json")))
      verify_observation(observation, identifier); require(observation == result["observations"][identifier])
    preflight(prepared, after=True)
    execution.update(status="observed", failure_code=None)
  except Exception: result = None
  write_new(directory / "execution.json", encode(execution))
  require(result is not None)
  return result


def main(argv=None):
  parser = argparse.ArgumentParser(description="Self-owned SDK process probe only")
  action = parser.add_mutually_exclusive_group(required=True)
  action.add_argument("--prepare-only", action="store_true"); action.add_argument("--run-self-process", action="store_true")
  args = parser.parse_args(argv)
  try:
    prepared = prepare()
    if args.prepare_only: print(encode({"schema_version": 1, "status": "prepared", "directory": prepared["directory"], "product_gate": False}).decode().strip())
    else: print(encode({"schema_version": 1, "status": run(prepared)["status"], "cases": 8, "product_gate": False}).decode().strip())
    return 0
  except Exception:
    print(encode({"schema_version": 1, "status": "failed", "product_gate": False, "code": CODE}).decode().strip()); return 5


if __name__ == "__main__": raise SystemExit(main())
