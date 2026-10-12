"""RPC准备工件、固定launcher及负向oracle；默认不启动bwrap/SDK。"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rpc_probe", ROOT / "scripts/pi-probe-official-rpc.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def observed(case):
  state = {"schema_version": 1, "case_id": case, "versions": {"pi": "1.0.1", "pi_ai": "1.0.2", "node": "24.14.0"},
    "phase": "shutdown", "native_started": True, "has_ui": True, "mode": "rpc", "tool_starts": 1, "tool_ends": 1,
    "tool_error": case != "confirmed", "confirm_result": case == "confirmed", "signal_aborted": case == "abort-late",
    "body_count": int(case == "confirmed"), "settled": True, "shutdown_seen": True, "extension_errors": 0,
    "credentials_empty": True, "active_tools_exact": True}
  data = {"isStreaming": False, "isCompacting": False, "pendingMessageCount": 0,
          "model": {"provider": "synthetic-rpc-probe", "id": "synthetic-model"}}
  events = [{"type": "response", "id": "ready", "command": "get_state", "success": True, "data": data},
    {"type": "response", "id": "prompt", "command": "prompt", "success": True, "data": {"disposition": "started"}},
    {"type": "tool_execution_start", "toolName": "probe_confirmed_body", "toolCallId": "synthetic-call-1"},
    {"type": "extension_ui_request", "id": "dialog-1", "method": "confirm", "title": "Synthetic permission", "message": "Allow synthetic sentinel only?", "timeout": 1000},
    {"type": "tool_execution_end", "toolName": "probe_confirmed_body", "toolCallId": "synthetic-call-1", "isError": case != "confirmed"},
    {"type": "agent_settled"}]
  commands = [{"type": "get_state", "id": "ready"}, {"type": "prompt", "id": "prompt", "message": "Synthetic permission probe"}]
  if case == "cancelled": commands.append({"type": "extension_ui_response", "id": "dialog-1", "cancelled": True})
  if case == "wrong-id": commands.append({"type": "extension_ui_response", "id": "dialog-1-wrong", "confirmed": True})
  if case == "confirmed": commands.append({"type": "extension_ui_response", "id": "dialog-1", "confirmed": True})
  if case == "abort-late":
    commands.append({"type": "abort", "id": "abort"})
    events.append({"type": "response", "id": "abort", "command": "abort", "success": True})
    commands.append({"type": "extension_ui_response", "id": "dialog-1", "confirmed": True})
  commands.append({"type": "get_state", "id": "settled"})
  events.append({"type": "response", "id": "settled", "command": "get_state", "success": True, "data": data})
  indices = [0, 1]
  if case in ("cancelled", "wrong-id", "confirmed"): indices.append(4)
  if case == "abort-late": indices.extend([4, 7])
  indices.append(7 if case == "abort-late" else 6)
  commands = [{"command": command, "after_events": index} for command, index in zip(commands, indices)]
  return events, state, b"synthetic body\n" if case == "confirmed" else None, commands


@pytest.mark.parametrize("case", ["timeout", "cancelled", "wrong-id", "abort-late", "confirmed"])
def test_closed_oracle_requires_host_lifecycle_and_independent_sentinel(case):
  events, state, marker, commands = observed(case)
  assert probe.verify_case(case, events, state, marker, 0, commands)["body_count"] == int(case == "confirmed")


@pytest.mark.parametrize("fault", ["exit-only", "body", "marker", "has-ui", "mode", "tool-error", "settled", "shutdown", "credentials", "tools", "version", "unknown", "prompt", "wrong-response", "generation"])
def test_oracle_rejects_false_positive_without_executing_sdk(fault):
  case = "timeout"
  events, state, marker, commands = observed(case)
  if fault == "exit-only": events = []; state = {}
  if fault == "body": state["body_count"] = 1
  if fault == "marker": marker = b"synthetic body\n"
  if fault == "has-ui": state["has_ui"] = False
  if fault == "mode": state["mode"] = "json"
  if fault == "tool-error": events[4]["isError"] = False
  if fault == "settled": events = [event for event in events if event["type"] != "agent_settled"]
  if fault == "shutdown": state["shutdown_seen"] = False
  if fault == "credentials": state["credentials_empty"] = False
  if fault == "tools": state["active_tools_exact"] = False
  if fault == "version": state["versions"]["pi"] = "other"
  if fault == "unknown": state["passed"] = True
  if fault == "prompt": events[1]["success"] = False
  if fault == "wrong-response": commands.insert(2, {"type": "extension_ui_response", "id": "dialog-1", "confirmed": True})
  if fault == "generation": state["tool_starts"] = True
  with pytest.raises(probe.ProbeError): probe.verify_case(case, events, state, marker, 0, commands)


def test_jsonl_reader_splits_only_lf_and_bounds_bytes():
  reader = probe.JsonLines()
  payload = json.dumps({"type": "synthetic", "text": "a\u2028b\u2029c"}, ensure_ascii=False).encode() + b"\n"
  assert reader.feed(payload[:19]) == []
  assert reader.feed(payload[19:]) == [{"type": "synthetic", "text": "a\u2028b\u2029c"}]
  with pytest.raises(probe.ProbeError): reader.feed(b"x" * (probe.MAX_LINE + 1))


@pytest.mark.parametrize("payload", [b'{"type":"a","type":"b"}\n', b'[]\n', b'NaN\n', b'{bad}\n', b'\xff\n'])
def test_jsonl_rejects_ambiguous_or_nonobject_frames(payload):
  with pytest.raises(probe.ProbeError): probe.JsonLines().feed(payload)


@pytest.mark.parametrize("case", ["timeout", "cancelled", "wrong-id", "abort-late", "confirmed"])
def test_launcher_is_fixed_and_has_no_inherited_account_routes(tmp_path, case):
  argv, env = probe.build_invocation(case, tmp_path / case)
  assert env == {}
  assert argv[0] == "/bin/bwrap" and "--clearenv" not in argv
  assert "--unshare-all" in argv and "--new-session" in argv
  assert argv[argv.index("--cap-drop") + 1] == "ALL"
  binds = [(argv[i + 1], argv[i + 2]) for i, value in enumerate(argv) if value in ("--bind", "--ro-bind")]
  assert (str(tmp_path / case), "/work") in binds
  assert not any(target.startswith("/home") for _, target in binds)
  assert len([value for value in argv if value == "--bind"]) == 1
  assert argv[-3:] == ["/probe/worker.mjs", "--native-rpc-worker", case]
  assert "PI_OFFLINE" in argv and "OTEL_SDK_DISABLED" in argv
  with pytest.raises(probe.ProbeError): probe.build_invocation("shell", tmp_path / case)
  with pytest.raises(probe.ProbeError): probe.build_invocation(case, Path("relative"))


def test_default_entry_does_not_launch_or_import_sdk(monkeypatch):
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("native process started"))
  assert probe.main([]) == 2


def test_abort_late_actions_wait_for_tool_settled_and_abort_ack():
  events, _, _, _ = observed("abort-late")
  conversation = probe.Conversation("abort-late")
  assert conversation.start() == [{"type": "get_state", "id": "ready"}]
  assert conversation.feed(events[0])[0]["type"] == "prompt"
  assert conversation.feed(events[1]) == []
  assert conversation.feed(events[2]) == []
  assert conversation.feed(events[3]) == [{"type": "abort", "id": "abort"}]
  assert conversation.feed(events[4]) == []
  assert conversation.feed(events[5]) == []
  actions = conversation.feed(events[6])
  assert actions == [{"type": "extension_ui_response", "id": "dialog-1", "confirmed": True}, {"type": "get_state", "id": "settled"}]
  assert not conversation.done
  assert conversation.feed(events[7]) == []
  assert conversation.done


def test_prepared_fixture_is_closed_and_binds_exact_self_owned_sources():
  import hashlib
  from jsonschema import Draft202012Validator
  fixture = ROOT / "tests/fixtures/pi/official-rpc-probe"
  plan = json.loads((fixture / "plan.json").read_bytes())
  assert probe.validate_plan(plan) == plan
  Draft202012Validator(json.loads((fixture / "plan.schema.json").read_bytes())).validate(plan)
  assert {path.name for path in fixture.iterdir()} == {"extension.mjs", "plan.json", "plan.schema.json", "result.schema.json"}
  assert plan["files"] == {"worker.mjs": hashlib.sha256((ROOT / "scripts/pi-probe-official-rpc.mjs").read_bytes()).hexdigest(),
                          "extension.mjs": hashlib.sha256((fixture / "extension.mjs").read_bytes()).hexdigest()}


@pytest.mark.parametrize("fault", ["provider", "account", "unknown", "version", "lock", "case", "bool", "timeout"])
def test_plan_rejects_nonfixed_external_routes_and_identity_drift(fault):
  plan = json.loads((ROOT / "tests/fixtures/pi/official-rpc-probe/plan.json").read_bytes())
  if fault == "provider": plan["provider"]["base_url"] = "https://api.openai.com/v1"
  if fault == "account": plan["provider"]["api_key"] = "$ACCOUNT_TOKEN"
  if fault == "unknown": plan["provider"]["oauth"] = True
  if fault == "version": plan["versions"]["pi"] = "latest"
  if fault == "lock": plan["lock_sha256"] = "f" * 64
  if fault == "case": plan["cases"].append("shell")
  if fault == "bool": plan["schema_version"] = True
  if fault == "timeout": plan["confirmation_timeout_ms"] = 0
  with pytest.raises(probe.ProbeError): probe.validate_plan(plan)


def test_late_confirmation_before_abort_settle_is_not_evidence():
  events, state, marker, commands = observed("abort-late")
  commands[3]["after_events"] = 4
  with pytest.raises(probe.ProbeError): probe.verify_case("abort-late", events, state, marker, 0, commands)


def test_confirmed_but_aborted_cannot_authorize_body():
  events, state, marker, commands = observed("confirmed")
  state["signal_aborted"] = True
  with pytest.raises(probe.ProbeError): probe.verify_case("confirmed", events, state, marker, 0, commands)


@pytest.mark.parametrize("fault", ["passed", "authorization", "secret", "unknown-case"])
def test_public_result_never_issues_acceptance(fault):
  from jsonschema import Draft202012Validator
  schema = json.loads((ROOT / "tests/fixtures/pi/official-rpc-probe/result.schema.json").read_bytes())
  result = {"schema_version": 1, "probe_id": "official-rpc-1.0.1", "expected_versions": probe.VERSIONS, "lock_sha256": probe.LOCK_SHA,
    "status": "failed", "cases": [{"case_id": case, "outcome": "not-run", "execution": {"started": False, "exit_code": None, "timed_out": False}, "observations": {}} for case in probe.CASES], "limitations": ["No native execution"]}
  validator = Draft202012Validator(schema); assert validator.is_valid(result)
  if fault == "passed": result["status"] = "passed"
  if fault == "authorization": result["accepted"] = True
  if fault == "secret": result["credentials"] = {"account": "forbidden"}
  if fault == "unknown-case": result["cases"][0]["case_id"] = "shell"
  assert not validator.is_valid(result)


@pytest.mark.parametrize("bad_frame", [False, True])
def test_driver_uses_fixed_fake_process_and_never_promotes_exit_zero(tmp_path, monkeypatch, bad_frame):
  from types import SimpleNamespace
  events, state, marker, _ = observed("confirmed")
  directory = tmp_path / "synthetic-case"; directory.mkdir(mode=0o700)
  queue = []
  instances = []
  class Output:
    def __init__(self, fd): self.fd = fd; self.closed = False
    def fileno(self): return self.fd
    def close(self): self.closed = True
  class Input:
    closed = False
    def write(self, payload):
      command = json.loads(payload)
      if bad_frame:
        queue.append(b'{"type":"extension_error","error":"synthetic"}\n')
      elif command == {"type": "get_state", "id": "ready"}: enqueue(events[:1])
      elif command.get("type") == "prompt": enqueue(events[1:4])
      elif command.get("type") == "extension_ui_response": enqueue(events[4:6])
      elif command == {"type": "get_state", "id": "settled"}: enqueue(events[6:])
      else: pytest.fail("unexpected outbound command")
      return len(payload)
    def flush(self): pass
    def close(self):
      self.closed = True; instances[0].returncode = 0
      work = directory / "work"
      (work / "state.json").write_text(json.dumps(state)); (work / "state.json").chmod(0o600)
      if marker is not None:
        (work / "body-sentinel").write_bytes(marker); (work / "body-sentinel").chmod(0o600)
  def enqueue(values):
    queue.extend(json.dumps(value).encode() + b"\n" for value in values)
  class Process:
    def __init__(self, argv, **kwargs):
      assert argv == probe.build_invocation("confirmed", directory / "work")[0]
      assert kwargs["env"] == {} and kwargs["shell"] is False and kwargs["close_fds"] is True
      self.stdin = Input(); self.stdout = Output(10001); self.stderr = Output(10002); self.returncode = None
      instances.append(self)
    def poll(self): return self.returncode
    def wait(self, timeout):
      assert 0 < timeout <= 1
      if self.returncode is None: raise probe.subprocess.TimeoutExpired("synthetic", timeout)
      return self.returncode
    def terminate(self): self.returncode = -15
    def kill(self): self.returncode = -9
  class Selector:
    def __init__(self): self.keys = {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def register(self, stream, _events, label): self.keys[stream.fd] = SimpleNamespace(fileobj=stream, data=label)
    def unregister(self, stream): self.keys.pop(stream.fd)
    def get_map(self): return self.keys
    def select(self, timeout): return [(key, 1) for key in list(self.keys.values())]
  original_read = probe.os.read
  def read(fd, limit):
    if fd == 10002: return b""
    if fd == 10001: return queue.pop(0) if queue else b""
    return original_read(fd, limit)
  monkeypatch.setattr(probe.subprocess, "Popen", Process)
  monkeypatch.setattr(probe.selectors, "DefaultSelector", Selector)
  monkeypatch.setattr(probe.os, "read", read)
  result = probe.run_case("confirmed", directory, probe.time.monotonic() + 60)
  assert len(instances) == 1 and instances[0].poll() == 0
  assert instances[0].stdin.closed and instances[0].stdout.closed and instances[0].stderr.closed
  assert result["outcome"] == ("failed" if bad_frame else "observed")
  assert result["execution"] == {"started": True, "exit_code": 0, "timed_out": False}
  assert (directory / "case-result.json").stat().st_mode & 0o777 == 0o600
  if bad_frame: assert result["observations"] == {}


def test_existing_output_refused_before_any_native_process(tmp_path, monkeypatch):
  output = tmp_path / "existing"; output.mkdir(mode=0o700)
  monkeypatch.setattr(probe, "preflight", lambda: None)
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("native process started"))
  assert probe.main(["--run-native-rpc-probe", "--output-dir", str(output)]) == 2
  assert list(output.iterdir()) == []


def test_step_timeout_closes_only_the_registered_fake_process(tmp_path, monkeypatch):
  directory = tmp_path / "synthetic-timeout"; directory.mkdir(mode=0o700)
  clock = [0.0]; saved = []
  class Stream:
    closed = False
    def write(self, data): return len(data)
    def flush(self): pass
    def close(self): self.closed = True
  class Process:
    def __init__(self, argv, **kwargs):
      assert argv == probe.build_invocation("timeout", directory / "work")[0]
      assert kwargs["env"] == {} and kwargs["shell"] is False
      self.stdin, self.stdout, self.stderr = Stream(), Stream(), Stream()
      self.returncode = None; self.terminated = self.killed = 0
      saved.append(self)
    def poll(self): return self.returncode
    def wait(self, timeout):
      assert 0 < timeout <= 1
      if self.returncode is None: raise probe.subprocess.TimeoutExpired("synthetic", timeout)
      return self.returncode
    def terminate(self): self.terminated += 1; self.returncode = -15
    def kill(self): self.killed += 1; self.returncode = -9
  class Selector:
    def __init__(self): self.keys = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def register(self, stream, _events, label): self.keys.append((stream, label))
    def get_map(self): return self.keys
    def select(self, timeout): clock[0] += 2; return []
  monkeypatch.setattr(probe.subprocess, "Popen", Process)
  monkeypatch.setattr(probe.selectors, "DefaultSelector", Selector)
  monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
  result = probe.run_case("timeout", directory, 60)
  assert len(saved) == 1 and saved[0].terminated == 1 and saved[0].killed == 0
  assert all(stream.closed for stream in (saved[0].stdin, saved[0].stdout, saved[0].stderr))
  assert result["outcome"] == "failed"
  assert result["execution"] == {"started": True, "exit_code": -15, "timed_out": True}
  assert not (directory / "work/body-sentinel").exists()
