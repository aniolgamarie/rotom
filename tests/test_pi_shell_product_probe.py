"""产品探针oracle、合成父控制器与编排故障；不启动helper/宿主/真实子进程。"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import pi_shell_product_probe as probe
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_activity import FakeProcesses, identity


def events(case="allowed"):
  namespaces = {name: name + ":[200]" for name in probe.NAMESPACES}
  value = [{"schema_version": 1, "phase": "payload", "nonce": "a" * 32,
    "namespaces": namespaces, "observations": {key: True for key in probe.OBSERVATIONS}}]
  if case == "background": value.append({"schema_version": 1, "phase": "heartbeat", "nonce": "a" * 32,
    "pid": 2, "namespaces": deepcopy(namespaces)})
  return value


def outer(): return {name: name + ":[100]" for name in probe.NAMESPACES}


@pytest.mark.parametrize("case", ["allowed", "background"])
def test_event_oracle_requires_positive_controls_and_namespace_separation(case):
  probe.verify_events(case, "a" * 32, events(case), outer())


@pytest.mark.parametrize("fault", ["nonce", "bool-version", "extra", "missing-check", "false-check", "int-check",
  "namespace", "namespace-type", "outer-namespace", "phase", "duplicate", "bool-pid", "zero-pid", "different-heartbeat-ns"])
def test_event_oracle_rejects_wrong_or_ambiguous_evidence(fault):
  value = events("background")
  if fault == "nonce": value[0]["nonce"] = "b" * 32
  if fault == "bool-version": value[0]["schema_version"] = True
  if fault == "extra": value[0]["extra"] = True
  if fault == "missing-check": value[0]["observations"].pop("project_write")
  if fault == "false-check": value[0]["observations"]["project_write"] = False
  if fault == "int-check": value[0]["observations"]["project_write"] = 1
  if fault == "namespace": value[0]["namespaces"].pop("pid")
  if fault == "namespace-type": value[0]["namespaces"]["pid"] = 1
  if fault == "outer-namespace": value[0]["namespaces"]["pid"] = outer()["pid"]
  if fault == "phase": value[0]["phase"] = "prepared"
  if fault == "duplicate": value[1] = deepcopy(value[0])
  if fault == "bool-pid": value[1]["pid"] = True
  if fault == "zero-pid": value[1]["pid"] = 0
  if fault == "different-heartbeat-ns": value[1]["namespaces"]["mnt"] = "mnt:[300]"
  with pytest.raises(ConfigError): probe.verify_events("background", "a" * 32, value, outer())


def test_partial_frame_and_limits_remain_bounded():
  value = []
  buffer = probe._events(bytearray(b'{"phase":'), value)
  assert not value
  assert probe._events(buffer + b'"payload"}\n', value) == bytearray()
  assert value == [{"phase": "payload"}]
  for raw in (b"x" * 65537, b"\n", b'{"a":1,"a":2}\n'):
    with pytest.raises(ConfigError): probe._events(bytearray(raw), [])
  with pytest.raises(ConfigError): probe._events(bytearray(b'{}\n{}\n{}\n'), [])


def test_fixed_command_quotes_only_local_fixture_path_and_nonce(tmp_path):
  import shlex
  work = tmp_path / "quote ' space"
  body = probe.command(work, "a" * 32, "background")
  lines = body.splitlines()
  assert shlex.split(lines[0]) == ["/usr/bin/python3.11", "-I", "-B", "-S", str(work / "readonly/heartbeat.py"), "a" * 32, "&"]
  assert shlex.split(lines[1]) == ["/usr/bin/python3.11", "-I", "-B", "-S", str(work / "readonly/payload.py"), "--payload", "a" * 32]
  assert lines[2] == "wait"
  with pytest.raises(ConfigError): probe.command(work, "$(forbidden)", "allowed")


def bundle(tmp_path, monkeypatch):
  directory = tmp_path / "bundle"
  for case in ("allowed", "denied", "background"):
    base = directory / "cases" / case
    for name in ("state", "instance", "private-account-home", "observations", "work/home", "work/project/.git"):
      (base / name).mkdir(parents=True, mode=0o700, exist_ok=True)
    (base / "work/project/.git/HEAD").write_text("ref: refs/heads/fixture\n")
    for name, data in probe.CANARIES.items():
      target = base / "work" / name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
  runtime = directory / "inputs" / ("c" * 64); runtime.mkdir(parents=True)
  executable = directory / "synthetic-bash"; executable.write_bytes(b"never execute"); executable.chmod(0o700)
  original = probe.manifest
  def manifest(work, **kwargs):
    value = original(work, **kwargs); value["options"]["external_tools"]["shell"]["executable"] = str(executable); return value
  monkeypatch.setattr(probe, "manifest", manifest)
  class Processes(FakeProcesses):
    def __init__(self, root):
      super().__init__(); self.record_root = root; self.current[501] = identity(501)
    def identity(self, pid): return identity(501)
  monkeypatch.setattr(probe, "LinuxProcesses", Processes)
  plan = {"probe_id": "synthetic-test", "runtime_identity": "c" * 64, "lock_identity": "a" * 64,
    "slice_identity": "b" * 64, "helper_identity": "d" * 64, "system": {"dependencies": {"path": str(directory / "deps")}},
    "nonces": {case: "a" * 32 for case in ("allowed", "denied", "background")}}
  return directory, plan


def test_synthetic_parent_uses_private_account_and_actual_deny_without_spawn(tmp_path, monkeypatch):
  directory, plan = bundle(tmp_path, monkeypatch)
  observed = []
  original = probe.ProbeHost
  class Host(original):
    def __init__(self, *args): super().__init__(*args); observed.append(self)
  monkeypatch.setattr(probe, "ProbeHost", Host)
  def forbidden(*args, **kwargs): pytest.fail("deny must not spawn")
  monkeypatch.setattr(Host, "spawn", forbidden)
  result = probe.run_case(directory, plan, "denied")
  assert result == {"case_id": "denied", "outcome": "observed", "stage": "admission", "checks": 0,
    "synthetic_manager": True, "frontend_verified": False, "default_factory_enabled": False, "product_gate": False}
  host, = observed
  assert host.store.owner["supervisor_process_identity"] == identity(501)
  assert host.store.records()[0]["kind"] == "host"
  assert not (directory / "cases/denied/work/project/.git/agentcfg").exists()
  assert not host.children
  with pytest.raises(RuntimeError): host._spawn_executor.submit(lambda: None)
  assert (directory / "cases/denied/observations/denied.json").is_file()


@pytest.mark.parametrize("point", ["setup", "admission", "consume"])
def test_failure_does_not_claim_observed_or_start_another_child(tmp_path, monkeypatch, point):
  directory, plan = bundle(tmp_path, monkeypatch)
  host = probe.ProbeHost(directory, plan, "allowed")
  # 已构造对象替换factory，避免重复写合成manifest；仍用真实store作为不变哨兵。
  def factory(*args):
    if point == "setup": raise Conflict("synthetic-setup")
    return host
  monkeypatch.setattr(probe, "ProbeHost", factory)
  monkeypatch.setattr(host.bridge, "prepare", lambda *args: (_ for _ in ()).throw(Conflict("synthetic-admission")) if point == "admission" else {"operation_id": "a" * 32, "operation_digest": "b" * 64})
  monkeypatch.setattr(host.bridge, "issue", lambda *args, **kwargs: {})
  monkeypatch.setattr(host.bridge, "consume", lambda *args: (_ for _ in ()).throw(Conflict("synthetic-consume")))
  before = host.store.records()
  result = probe.run_case(directory, plan, "allowed")
  assert result["outcome"] == "unavailable" and result["checks"] == 0 and not result["product_gate"]
  assert host.store.records() == before and not host.children
  if point != "setup":
    failure = json.loads((directory / "cases/allowed/observations/failure.json").read_bytes())
    assert failure == {"kind": "conflict", "code": "PROBE_STAGE_FAILED"}


def test_probe_failure_closes_explicit_spawn_owner_without_refunding_parent(tmp_path, monkeypatch):
  import threading
  directory, plan = bundle(tmp_path, monkeypatch)
  host = probe.ProbeHost(directory, plan, "allowed")
  owner = host._spawn_executor.submit(threading.current_thread).result()
  monkeypatch.setattr(probe, "ProbeHost", lambda *args: host)
  monkeypatch.setattr(host.bridge, "prepare", lambda *args: (_ for _ in ()).throw(Conflict("synthetic failure")))
  result = probe.run_case(directory, plan, "allowed")
  assert result["outcome"] != "observed" and not owner.is_alive()
  assert host.service.closing
  assert host.store.records()[0]["state"] == "running"
  with pytest.raises(RuntimeError): host.spawn(None, None)
