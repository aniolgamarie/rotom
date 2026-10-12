"""产品探针生命周期的真实租约/Writer与替身进程；不启动任何程序或发信号。"""

import base64
from copy import deepcopy
from types import SimpleNamespace
import json
import time

import pytest

from agentcfg import pi_shell_product_probe as module
from agentcfg import pi_shell_product_probe_bundle as bundles
from agentcfg.activity import protected
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_activity import identity
from test_pi_shell_product_probe import bundle, events
from test_pi_shell_product_probe_bundle import bundle as prepared_bundle


class Process:
  def __init__(self): self.returncode = None; self.waits = []
  def poll(self): return self.returncode
  def wait(self, **kwargs):
    self.waits.append(kwargs)
    if self.returncode is None: self.returncode = -15
    return self.returncode


class Capture:
  def __init__(self, body=b"", complete=True): self.body, self.done, self.sent = body, complete, False
  def complete(self): return self.done
  def since(self, cursor):
    rows = [] if self.sent or not self.body else [{"stream": "stdout", "data_b64": base64.b64encode(self.body).decode()}]
    self.sent = True
    return {"dropped": False, "next_cursor": cursor + len(rows), "events": rows, "has_more": False}


def host_fixture(tmp_path, monkeypatch, case="allowed"):
  directory, plan = bundle(tmp_path, monkeypatch)
  host = module.ProbeHost(directory, plan, case)
  monkeypatch.setattr(host.store, "abort_allocation", lambda *args, **kwargs: pytest.fail("failure cleanup must not abort or release Writer"))
  host.bridge.backend_preflight = lambda public: {"runtime_identity": plan["runtime_identity"],
    "helper_identity": plan["helper_identity"], "plan_digest": "e" * 64}
  state = SimpleNamespace(host=host, directory=directory, plan=plan, process=Process(), stopped=[], gates=[], calls=[],
    capture=Capture(), unknown=False, spawn_error=False)
  original_call = host.call
  def stop(expected, **kwargs):
    state.stopped.append(deepcopy(expected))
    assert expected == identity(703) and expected != host.store.owner["supervisor_process_identity"]
    if state.unknown: raise Conflict("synthetic-unknown-stop")
    host.processes.current.pop(703, None); state.process.returncode = -15
  host.processes.stop = stop
  original_status = host.processes.termination_status
  host.processes.termination_status = lambda expected: "unknown" if state.unknown and expected["pid"] == 703 else original_status(expected)
  def start(lease_id):
    def spawn(lease):
      if state.spawn_error: raise OSError("synthetic-spawn-unconfirmed")
      born = identity(703); host.processes.current[703] = born
      host.children[lease_id] = {"identity": born, "process": state.process, "capture": state.capture,
        "launch": SimpleNamespace(close_gate=lambda: state.gates.append("closed")), "gate": None}
      return born
    lease = host.store.start(lease_id, host.store.owner, spawn=spawn)
    host.activated = {"lease": lease}; host.release_started = 0
    return {"state": lease["state"], "lease_id": lease_id}
  def call(method, args):
    state.calls.append(method)
    if method == "start": return start(args["lease_id"])
    return original_call(method, args)
  host.call = call
  monkeypatch.setattr(module, "ProbeHost", lambda *args: host)
  return state


def consumed(state):
  host = state.host
  prepared = host.bridge.prepare(host.principal, "direct", "bash", {"command": "synthetic script, never execute"})
  permit = host.bridge.issue(host.principal, prepared["operation_id"], operation_digest=prepared["operation_digest"], source="human")
  ticket = host.bridge.consume(host.principal, permit)
  return ticket["lease_id"]


@pytest.mark.parametrize("unknown", [False, True])
def test_run_case_cleanup_stops_only_registered_external_and_keeps_writer_without_finish(tmp_path, monkeypatch, unknown):
  state = host_fixture(tmp_path, monkeypatch); state.unknown = unknown
  monkeypatch.setattr(module, "collect", lambda *args: (_ for _ in ()).throw(ConfigError("synthetic-output-failure")))
  result = module.run_case(state.directory, state.plan, "allowed")
  assert result["outcome"] == ("termination-unknown" if unknown else "unavailable")
  assert result["checks"] == 0
  assert state.calls == ["start"] and state.stopped == [identity(703)] and state.gates == ["closed"]
  external = [row for row in state.host.store.records() if row["kind"] == "external"]
  assert len(external) == 1 and external[0]["state"] == "running" and protected(external[0])
  assert state.host.store.workspaces.read(external[0]["planned_workspaces"][0])["state"] == "active"
  manager = state.host.store.read(state.host.principal.lease_id)
  assert manager["state"] == "running" and state.host.processes.observe(manager["process_identity"]) == "alive"
  assert state.process.waits == ([] if unknown else [{"timeout": 2}])


def test_unconfirmed_start_without_child_never_stops_manager_or_aborts_allocation(tmp_path, monkeypatch):
  state = host_fixture(tmp_path, monkeypatch); state.spawn_error = True
  result = module.run_case(state.directory, state.plan, "allowed")
  assert result["outcome"] == "unavailable" and result["stage"] == "start"
  assert not state.stopped and not state.host.children and state.calls == ["start"]
  external = [row for row in state.host.store.records() if row["kind"] == "external"]
  assert len(external) == 1 and external[0]["state"] == "unknown" and external[0]["spawn_committed"]
  assert external[0]["process_identity"] is None and protected(external[0])
  assert state.host.store.workspaces.read(external[0]["planned_workspaces"][0])["state"] == "reserved"


def clock(monkeypatch, *, step=0.01):
  ticks = [0]
  def now(): ticks[0] += step; return ticks[0]
  monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=now, sleep=lambda duration: None, time=time.time))


def test_collect_cancel_uses_real_service_before_poll_and_real_writer_release(tmp_path, monkeypatch):
  state = host_fixture(tmp_path, monkeypatch, "background")
  nonce = state.plan["nonces"]["background"]
  state.capture = Capture(b"".join(module.json_bytes(value) for value in events("background")))
  lease_id = consumed(state); state.host.call("start", {"lease_id": lease_id})
  (state.host.work / "project/heartbeat").write_bytes((nonce + "\n").encode())
  initial = state.host.snapshot(lease_id)
  order = []
  real_call, real_poll = state.host.call, state.host.poll
  def call(method, args):
    order.append(method)
    reply = real_call(method, args)
    row = state.host.snapshot(lease_id)
    assert method == "cancel" and row["lease"]["grant_generation"] == initial["lease"]["grant_generation"] + 1
    assert row["lease"]["state"] == "cancel_requested" and protected(row["lease"])
    assert row["writers"][0]["state"] == "active"
    return reply
  def poll(): order.append("poll"); return real_poll()
  state.host.call, state.host.poll = call, poll
  clock(monkeypatch)
  received, timing = module.collect(state.host, lease_id, nonce)
  assert received == events("background") and order[:3] == ["poll", "cancel", "poll"]
  assert state.stopped == [identity(703)]
  final = state.host.snapshot(lease_id)
  assert final["lease"]["state"] == "reclaimed" and not protected(final["lease"])
  assert final["writers"][0]["state"] == "released" and final["lease"]["termination_evidence"] is not None
  assert timing["heartbeat_before"] == timing["heartbeat_after"] == 1 and 0 <= timing["stop_elapsed_ms"] < 10000
  saved = json.loads((state.directory / "cases/background/observations/cancel-before-poll.json").read_bytes())
  assert saved["lease"]["state"] == "cancel_requested" and saved["writers"][0]["state"] == "active"


def test_collect_does_not_accept_wrapper_exit_and_capture_complete_without_namespace_termination(tmp_path, monkeypatch):
  state = host_fixture(tmp_path, monkeypatch)
  lease_id = consumed(state); state.host.call("start", {"lease_id": lease_id})
  state.process.returncode = 0
  assert state.capture.complete() and state.host.processes.termination_status(identity(703)) == "active"
  clock(monkeypatch, step=10)
  with pytest.raises(ConfigError, match="pi-shell-product-probe-timeout"):
    module.collect(state.host, lease_id, state.plan["nonces"]["allowed"])
  snapshot = state.host.snapshot(lease_id)
  assert snapshot["lease"]["state"] == "running" and protected(snapshot["lease"])
  assert snapshot["writers"][0]["state"] == "active" and not state.stopped


def test_run_stops_after_first_failure_and_once_marker_blocks_replay(prepared_bundle, monkeypatch):
  directory, plan, _ = prepared_bundle
  calls = []
  def failed(directory, selected, case):
    assert selected == plan; calls.append(case)
    return {"case_id": case, "outcome": "unavailable"}
  monkeypatch.setattr(module, "run_case", failed)
  result = module.run(directory)
  assert calls == ["allowed"] and result["observed"] is False and len(result["cases"]) == 1
  assert (directory / "execution-started.json").is_file()
  with pytest.raises(ConfigError): module.run(directory)
  assert calls == ["allowed"]


@pytest.mark.parametrize("actions", [[], ["--prepare", "--run-native-shell-product-probe"]])
def test_main_actions_are_required_and_mutually_exclusive(tmp_path, monkeypatch, actions):
  monkeypatch.setattr(module, "run", lambda *args: pytest.fail("invalid CLI must not run"))
  monkeypatch.setattr(bundles, "prepare", lambda *args: pytest.fail("invalid CLI must not prepare"))
  with pytest.raises(SystemExit) as error: module.main([*actions, "--directory", str(tmp_path / "bundle")])
  assert error.value.code == 2


def test_main_default_prepare_never_calls_native_run(tmp_path, monkeypatch):
  calls = []
  monkeypatch.setattr(bundles, "prepare", lambda path: calls.append(path))
  monkeypatch.setattr(module, "run", lambda *args: pytest.fail("prepare must not run"))
  target = tmp_path / "bundle"
  assert module.main(["--prepare", "--directory", str(target)]) == 0 and calls == [target]
