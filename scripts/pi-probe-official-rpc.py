#!/usr/bin/env python3
"""固定RPC沙箱探针；显式运行仍需用户另行授权，导入不启动任何进程。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/pi/official-rpc-probe"
WORKER = ROOT / "scripts/pi-probe-official-rpc.mjs"
CANDIDATE = ROOT / ".cache/pi-two-profiles/candidates/pi-1.0.1/closure"
NODE = Path("/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0")
CASES = ("timeout", "cancelled", "wrong-id", "abort-late", "confirmed")
VERSIONS = {"pi": "1.0.1", "pi_ai": "1.0.2", "node": "24.14.0"}
LOCK_SHA = "f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac"
MAX_LINE = 65536
MAX_BYTES = 1024 * 1024
STATE_KEYS = {"schema_version", "case_id", "versions", "phase", "native_started", "has_ui", "mode", "tool_starts",
  "tool_ends", "tool_error", "confirm_result", "signal_aborted", "body_count", "settled", "shutdown_seen", "extension_errors",
  "credentials_empty", "active_tools_exact"}
ENV = {"HOME": "/work/home", "PWD": "/work", "PATH": "/work/empty-bin", "PI_PROBE_NATIVE": "1", "PI_OFFLINE": "1",
  "OTEL_SDK_DISABLED": "true", "TMPDIR": "/work/tmp", "XDG_CONFIG_HOME": "/work/config", "XDG_DATA_HOME": "/work/data",
  "XDG_CACHE_HOME": "/work/cache", "XDG_STATE_HOME": "/work/state", "LC_ALL": "C.UTF-8"}


class ProbeError(Exception):
  """固定阶段身份，不保存输入、环境、RPC正文或底层异常。"""


class ProbeInterrupted(ProbeError):
  def __init__(self, result):
    self.result = result
    super().__init__("interrupted")


def require(condition):
  if not condition: raise ProbeError("probe assertion failed")


def pairs(items):
  result = {}
  for key, value in items:
    require(key not in result); result[key] = value
  return result


def decode(data):
  try:
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ProbeError("nonfinite JSON")))
    require(isinstance(value, dict)); return value
  except (ValueError, UnicodeError): raise ProbeError("invalid JSON") from None


class JsonLines:
  def __init__(self):
    self.buffer = b""
    self.total = 0

  def feed(self, data):
    require(isinstance(data, bytes))
    self.total += len(data); require(self.total <= MAX_BYTES)
    self.buffer += data
    values = []
    while b"\n" in self.buffer:
      line, self.buffer = self.buffer.split(b"\n", 1)
      require(0 < len(line) <= MAX_LINE)
      values.append(decode(line.removesuffix(b"\r")))
    require(len(self.buffer) <= MAX_LINE)
    return values

  def finish(self):
    require(not self.buffer)


def build_invocation(case, work):
  work = Path(work)
  require(case in CASES and work.is_absolute() and ".." not in work.parts and not any(ord(char) < 32 or ord(char) == 127 for char in str(work)))
  argv = ["/bin/bwrap", "--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
    "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--ro-bind", str(CANDIDATE), "/candidate",
    "--ro-bind", str(NODE), "/node", "--dir", "/probe", "--ro-bind", str(WORKER), "/probe/worker.mjs",
    "--ro-bind", str(FIXTURE), "/probe/fixture", "--symlink", "/candidate/node_modules", "/probe/node_modules",
    "--bind", str(work), "/work"]
  for name, value in ENV.items(): argv.extend(["--setenv", name, value])
  argv.extend(["--chdir", "/work", "/node/bin/node", "--max-old-space-size=512", "/probe/worker.mjs", "--native-rpc-worker", case])
  return argv, {}


def successful_response(event, command, request_id):
  return event.get("type") == "response" and event.get("command") == command and event.get("id") == request_id and event.get("success") is True


def idle(event):
  data = event.get("data", {})
  return (isinstance(data, dict) and data.get("isStreaming") is False and data.get("isCompacting") is False
    and type(data.get("pendingMessageCount")) is int and data["pendingMessageCount"] == 0)


class Conversation:
  def __init__(self, case):
    require(case in CASES)
    self.case = case
    self.prompt_sent = self.query_sent = self.done = False
    self.tool_end = self.settled = self.abort_ack = False
    self.ui_id = None

  def start(self):
    return [{"type": "get_state", "id": "ready"}]

  def feed(self, event):
    actions = []
    if event.get("type") == "response": require(event.get("success") is True)
    require(event.get("type") != "extension_error")
    if successful_response(event, "get_state", "ready"):
      require(not self.prompt_sent and idle(event)); self.prompt_sent = True
      actions.append({"type": "prompt", "id": "prompt", "message": "Synthetic permission probe"})
    if event.get("type") == "extension_ui_request":
      require(self.prompt_sent and self.ui_id is None and event.get("method") == "confirm")
      require(event.get("title") == "Synthetic permission" and event.get("message") == "Allow synthetic sentinel only?"
        and type(event.get("timeout")) is int and event["timeout"] == 1000)
      request_id = event.get("id"); require(isinstance(request_id, str) and 0 < len(request_id) <= 128)
      self.ui_id = request_id
      if self.case == "cancelled": actions.append({"type": "extension_ui_response", "id": request_id, "cancelled": True})
      if self.case == "wrong-id": actions.append({"type": "extension_ui_response", "id": request_id + "-wrong", "confirmed": True})
      if self.case == "confirmed": actions.append({"type": "extension_ui_response", "id": request_id, "confirmed": True})
      if self.case == "abort-late": actions.append({"type": "abort", "id": "abort"})
    if event.get("type") == "tool_execution_end" and event.get("toolName") == "probe_confirmed_body": self.tool_end = True
    if event.get("type") == "agent_settled": self.settled = True
    if successful_response(event, "abort", "abort"): self.abort_ack = True
    if self.ui_id and self.tool_end and self.settled and (self.case != "abort-late" or self.abort_ack) and not self.query_sent:
      self.query_sent = True
      if self.case == "abort-late": actions.append({"type": "extension_ui_response", "id": self.ui_id, "confirmed": True})
      actions.append({"type": "get_state", "id": "settled"})
    if successful_response(event, "get_state", "settled"):
      require(self.query_sent and idle(event)); self.done = True
    return actions


def verify_case(case, events, state, marker, exit_code, commands):
  require(case in CASES and type(exit_code) is int and exit_code == 0)
  require(isinstance(state, dict) and set(state) == STATE_KEYS)
  require(type(state["schema_version"]) is int and state["schema_version"] == 1 and state["case_id"] == case)
  require(state["versions"] == VERSIONS and state["phase"] == "shutdown")
  for key in ("native_started", "has_ui", "settled", "shutdown_seen", "credentials_empty", "active_tools_exact"):
    require(state[key] is True)
  require(state["mode"] == "rpc")
  for key in ("tool_starts", "tool_ends"): require(type(state[key]) is int and state[key] == 1)
  require(type(state["extension_errors"]) is int and state["extension_errors"] == 0)
  expected_body = int(case == "confirmed")
  require(type(state["body_count"]) is int and state["body_count"] == expected_body)
  require(state["confirm_result"] is (case == "confirmed") and state["signal_aborted"] is (case == "abort-late"))
  require(state["tool_error"] is (case != "confirmed"))
  require(marker == (b"synthetic body\n" if expected_body else None))
  conversation = Conversation(case)
  expected_commands = [{"command": command, "after_events": 0} for command in conversation.start()]
  for index, event in enumerate(events, 1):
    require(isinstance(event, dict))
    expected_commands.extend({"command": command, "after_events": index} for command in conversation.feed(event))
  require(conversation.done and commands == expected_commands)
  ready = [event for event in events if successful_response(event, "get_state", "ready")]
  prompts = [event for event in events if successful_response(event, "prompt", "prompt")]
  require(len(ready) == len(prompts) == 1 and isinstance(prompts[0].get("data"), dict) and prompts[0]["data"].get("disposition") == "started")
  require(isinstance(ready[0]["data"].get("model"), dict))
  require(ready[0]["data"]["model"].get("provider") == "synthetic-rpc-probe" and ready[0]["data"]["model"].get("id") == "synthetic-model")
  starts = [event for event in events if event.get("type") == "tool_execution_start"]
  ends = [event for event in events if event.get("type") == "tool_execution_end"]
  require(len(starts) == len(ends) == 1 and starts[0].get("toolName") == ends[0].get("toolName") == "probe_confirmed_body")
  require(starts[0].get("toolCallId") == ends[0].get("toolCallId") == "synthetic-call-1")
  require(ends[0].get("isError") is (case != "confirmed"))
  require(events.index(starts[0]) < events.index(ends[0]) < next(index for index, event in enumerate(events) if event.get("type") == "agent_settled"))
  return {"versions": dict(state["versions"]), "body_count": expected_body, "body_marker": marker is not None, "has_ui": True, "mode": "rpc", "tool_error": case != "confirmed",
    "signal_aborted": case == "abort-late", "ready": True, "prompt_accepted": True, "settled": True, "shutdown_seen": True,
    "abort_acknowledged": conversation.abort_ack, "late_confirm_after_settled": case == "abort-late", "credentials_empty": True, "active_tools_exact": True}


def read_private(path):
  info = path.lstat()
  require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= MAX_BYTES)
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    opened = os.fstat(fd); require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino))
    with os.fdopen(fd, "rb", closefd=False) as stream: return stream.read(MAX_BYTES + 1)
  finally: os.close(fd)


def write_new(path, value):
  fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb", closefd=False) as stream:
      stream.write(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n")
      stream.flush(); os.fsync(fd)
  finally: os.close(fd)


def validate_plan(plan):
  require(isinstance(plan, dict))
  require(set(plan) == {"schema_version", "probe_id", "versions", "lock_sha256", "provider", "cases", "confirmation_timeout_ms", "files"})
  require(type(plan["schema_version"]) is int and plan["schema_version"] == 1 and plan["probe_id"] == "official-rpc-1.0.1")
  require(plan["versions"] == VERSIONS and plan["lock_sha256"] == LOCK_SHA and plan["cases"] == list(CASES))
  require(type(plan["confirmation_timeout_ms"]) is int and plan["confirmation_timeout_ms"] == 1000)
  require(plan["provider"] == {"id": "synthetic-rpc-probe", "api": "synthetic-rpc-probe", "model": "synthetic-model",
    "base_url": "https://synthetic.invalid/unused", "api_key": "synthetic-no-account"})
  require(isinstance(plan["files"], dict) and set(plan["files"]) == {"worker.mjs", "extension.mjs"})
  require(all(isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value) for value in plan["files"].values()))
  return plan


def preflight():
  plan = validate_plan(decode((FIXTURE / "plan.json").read_bytes()))
  for name, path in (("worker.mjs", WORKER), ("extension.mjs", FIXTURE / "extension.mjs")):
    require(not path.is_symlink() and path.resolve(strict=True) == path)
    require(hashlib.sha256(path.read_bytes()).hexdigest() == plan["files"][name])
  require(hashlib.sha256((CANDIDATE / "package-lock.json").read_bytes()).hexdigest() == LOCK_SHA)
  require((NODE / "bin/node").is_file() and Path("/bin/bwrap").is_file())
  return plan


def run_case(case, directory, overall_deadline):
  work = directory / "work"; work.mkdir(mode=0o700)
  argv, env = build_invocation(case, work)
  write_new(directory / "invocation.json", {"argv": argv, "launcher_environment": env, "worker_sha256": hashlib.sha256(WORKER.read_bytes()).hexdigest()})
  value = {"case_id": case, "outcome": "not-run", "execution": {"started": False, "exit_code": None, "timed_out": False}, "observations": {}}
  process = None; events = []; commands = []; conversation = Conversation(case); reader = JsonLines()
  deadline = min(overall_deadline, time.monotonic() + 10)
  step_deadline = min(deadline, time.monotonic() + 5)
  phase = "launch"; output_size = 0; interrupted = False
  try:
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      cwd=directory, env=env, shell=False, close_fds=True)
    value["execution"]["started"] = True
    def send(command):
      process.stdin.write(json.dumps(command, separators=(",", ":")).encode() + b"\n"); process.stdin.flush()
      commands.append({"command": command, "after_events": len(events)})
    for command in conversation.start(): send(command)
    phase = "rpc"
    with selectors.DefaultSelector() as selector:
      selector.register(process.stdout, selectors.EVENT_READ, "stdout")
      selector.register(process.stderr, selectors.EVENT_READ, "stderr")
      logs = {}
      for stream in ("stdout", "stderr"):
        logs[stream] = os.open(directory / (stream + ".jsonl"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
      try:
        while selector.get_map():
          require(time.monotonic() < min(deadline, step_deadline))
          for key, _ in selector.select(timeout=min(0.1, max(0, deadline - time.monotonic()))):
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk: selector.unregister(key.fileobj); continue
            output_size += len(chunk); require(output_size <= MAX_BYTES)
            require(os.write(logs[key.data], chunk) == len(chunk))
            if key.data == "stdout":
              for event in reader.feed(chunk):
                events.append(event)
                actions = conversation.feed(event)
                for command in actions: send(command)
                if actions or event.get("type") == "extension_ui_request":
                  step_deadline = min(deadline, time.monotonic() + 3)
                if conversation.done and not process.stdin.closed:
                  phase = "dispose"; process.stdin.close()
                  step_deadline = min(deadline, time.monotonic() + 2)
          if process.poll() is not None and not selector.get_map(): break
        reader.finish(); process.wait(timeout=min(1, max(0.01, deadline - time.monotonic())))
      finally:
        for fd in logs.values(): os.fsync(fd); os.close(fd)
    value["execution"]["exit_code"] = process.returncode
    phase = "oracle"
    state = decode(read_private(work / "state.json"))
    marker = read_private(work / "body-sentinel") if os.path.lexists(work / "body-sentinel") else None
    value["observations"] = verify_case(case, events, state, marker, process.returncode, commands)
    value["outcome"] = "observed"
  except KeyboardInterrupt:
    interrupted = True; phase = "interrupted"
    value["outcome"] = "failed" if value["execution"]["started"] else "not-run"
  except Exception:
    value["outcome"] = "failed" if value["execution"]["started"] else "not-run"
    value["execution"]["timed_out"] = time.monotonic() >= min(deadline, step_deadline)
  finally:
    # 仅关闭本函数保存的固定bwrap进程句柄；从不操作其他PID/宿主。
    if process is not None:
      if process.poll() is None:
        if process.stdin and not process.stdin.closed:
          try: process.stdin.close()
          except OSError: pass
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired:
          if process.poll() is None: process.terminate()
          try: process.wait(timeout=1)
          except subprocess.TimeoutExpired:
            if process.poll() is None: process.kill()
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
      value["execution"]["exit_code"] = process.poll()
      for stream in (process.stdout, process.stderr):
        if stream: stream.close()
    write_new(directory / "commands.json", {"commands": commands})
    write_new(directory / "case-result.json", {**value, "phase": "complete" if value["outcome"] == "observed" else phase})
  if interrupted: raise ProbeInterrupted(value)
  return value


class Parser(argparse.ArgumentParser):
  def error(self, _message): raise ProbeError("invalid arguments")


def main(argv=None):
  parser = Parser(description="Prepare-only by default; native RPC execution requires separate authorization", allow_abbrev=False)
  parser.add_argument("--run-native-rpc-probe", action="store_true")
  parser.add_argument("--output-dir", required=True)
  try:
    args = parser.parse_args(argv)
    require(args.run_native_rpc_probe)
    output = Path(args.output_dir)
    require(output.is_absolute() and ".." not in output.parts and not any(ord(char) < 32 or ord(char) == 127 for char in str(output)))
    require(output.parent.resolve(strict=True) == output.parent)
    info = output.parent.stat(); require(info.st_uid == os.geteuid() and not info.st_mode & 0o022)
    preflight()
    output.mkdir(mode=0o700)
  except (ProbeError, OSError, ValueError):
    print("RPC probe arguments or preparation invalid", file=sys.stderr); return 2
  deadline = time.monotonic() + 60
  result = {"schema_version": 1, "probe_id": "official-rpc-1.0.1", "expected_versions": VERSIONS, "lock_sha256": LOCK_SHA,
    "status": "failed", "cases": [], "limitations": ["Prepared public SDK RPC mode, not CLI/all factories/product acceptance",
      "Synthetic model/credentials only; no real account or model evidence", "Mount and network isolation rely on the externally reviewed bwrap invocation"]}
  try:
    return collect_cases(output, deadline, result)
  except (ProbeError, OSError, ValueError):
    print("RPC probe output failed", file=sys.stderr); return 6


def collect_cases(output, deadline, result):
  stopped = False
  for case in CASES:
    directory = output / case; directory.mkdir(mode=0o700)
    if stopped or time.monotonic() >= deadline:
      value = {"case_id": case, "outcome": "not-run", "execution": {"started": False, "exit_code": None, "timed_out": not stopped}, "observations": {}}
    else:
      try: value = run_case(case, directory, deadline)
      except ProbeInterrupted as error:
        value = error.result; stopped = True
    result["cases"].append(value)
  if all(item["outcome"] == "observed" for item in result["cases"]): result["status"] = "observed"
  write_new(output / "result.json", result)
  print(json.dumps(result, sort_keys=True, separators=(",", ":")))
  return 130 if stopped else (0 if result["status"] == "observed" else 1)


if __name__ == "__main__":
  raise SystemExit(main())
