"""合成manager驱动真实产品Shell启动链；不部署、不开默认factory、不启动Pi/模型。"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import re
import shlex
import time
from types import SimpleNamespace
import uuid

from .activity import ExecutionStore, digest, protected
from .activity_linux import LinuxProcesses
from .deployment import json_bytes
from .pi_admitted_shell import ShellOperationAdmissions
from .pi_host import HostSupervisor
from .pi_operations import OrdinaryOperations
from .pi_shell_mounts import compile_mount_plan
from .pi_shell_probe import CANARIES, BLOCKED, decode, heartbeat, read_file
from .pi_shell_probe_protocol import NAMESPACES, OBSERVATIONS
from .pi_supervisor import Principal, SupervisorService
from .schema import ConfigError
from .storage import Conflict, Tree
from .workspace_leases import WorkspaceLeases


CASE_SECONDS = 45
MAX_BYTES = 1024 * 1024
FAILURE_CODES = frozenset(("SHELL_START_STALE", "SHELL_RUNTIME_UNAVAILABLE", "SHELL_BACKEND_UNAVAILABLE",
  "OPERATION_RESOLUTION_STALE", "OPERATION_CONTEXT_STALE", "GRANT_STALE", "ROOT_IDENTITY",
  "SHELL_MOUNT_DEVICE", "SHELL_MOUNT_AMBIGUOUS", "SHELL_MOUNT_SUBMOUNT", "SHELL_MOUNT_SCOPE",
  "SHELL_MOUNT_MASK", "SHELL_MOUNT_OBJECT", "pi-shell-execution", "pi-shell-exec-unavailable",
  "pi-shell-handoff", "pi-shell-identity", "pi-shell-probe-info", "pi-shell-mounts",
  "pi-shell-product-probe-timeout", "pi-shell-product-probe"))


def require(value):
  if not value: raise ConfigError("pi-shell-product-probe")


def manifest(work, *, denied=False):
  policy = {"schema_version": 1, "default": "deny", "rules": [
    {"id": "shell", "kind": "command", "effect": "deny" if denied else "allow", "command_ref": "tool:shell",
      "tool_ids": ["bash"], "operations": ["execute"]},
    {"id": "private", "kind": "file", "effect": "deny", "root_ref": "project", "relative_path": "private",
      "match": "subtree", "tool_ids": ["read", "write"], "operations": ["read", "write", "create"]}]}
  return {"profile_id": "pi-base", "plugins": [], "resource_ids": {"extensions": {}}, "role_bindings": {},
    "permission_policy": policy, "options": {"paths": {"roots": {
      key: {"path": str(work / key), "purpose": "project" if key == "project" else "read"}
      for key in ("project", "readonly")}}, "permissions": {"readonly_roots": ["readonly"]},
      "external_tools": {"shell": {"executable": "/usr/bin/bash", "version": "synthetic-probe",
        "project_root": "project", "read_roots": ["project", "readonly"], "write_roots": ["project"], "timeout_seconds": 30}}}}


class ProbeHost(HostSupervisor):
  def __init__(self, directory, plan, case):
    """显式依赖组装仅供探针；账户锚始终为合成目录，不调用产品默认构造器。"""
    self.directory, self.case = directory, case
    base = directory / "cases" / case
    self.work = base / "work"
    self.root, self.runtime_root = base / "state", directory / "inputs" / plan["runtime_identity"]
    self.repository = self.runtime_root / "supervisor"
    self.children, self.host_exit, self.delegates = {}, None, None
    self.activated = None
    self.release_started = None
    doc = manifest(self.work, denied=case == "denied")
    self.config = {"instance_root": str(base / "instance"), "lock_identity": plan["lock_identity"],
      "slice_identity": plan["slice_identity"], "manifest_digest": digest(doc), "policy_digest": digest(doc["permission_policy"]),
      "protected_roots": [str(base / name) for name in ("private-account-home", "observations")]
        + [str(self.work / "outside"), str(self.work / "home"), plan["system"]["dependencies"]["path"]]}
    with Tree(base / "instance") as tree: tree.write_new("pi-home/agentcfg-manifest.json", json_bytes(doc))
    self.processes = LinuxProcesses(self.root / "activity/processes")
    parent = self.processes.identity(os.getpid())
    owner = {"instance_id": "synthetic-shell-product-" + case, "supervisor_activation_id": uuid.uuid4().hex,
      "manager_activation_id": uuid.uuid4().hex, "owner_nonce": uuid.uuid4().hex, "supervisor_process_identity": parent}
    self.store = ExecutionStore(self.root, owner, self.processes,
      workspaces=WorkspaceLeases(parent["boot_id"], account_home=base / "private-account-home"))
    self.service = SupervisorService(self.store, self.resolve_command, self.spawn, activate=self.activate,
      runtime_identity=self.runtime_root.name, slice_identity=plan["slice_identity"])
    self.operations = OrdinaryOperations(self)
    parent_lease = self.store.allocate(kind="host", execution_id="synthetic-manager-" + case, task_id=None,
      attempt_id=uuid.uuid4().hex, lock_identity=plan["lock_identity"], slice_identity=plan["slice_identity"],
      policy_digest=self.config["policy_digest"], candidate_digest=None, planned_workspaces=[])
    # 自控进程的真实出生身份只模拟manager存活，不表示真实Pi宿主已经验收。
    parent_lease = self.store.start(parent_lease["lease_id"], owner, spawn=lambda _: parent)
    self.host_lease_id = parent_lease["lease_id"]
    self.principal = Principal("manager", self.host_lease_id, parent_lease["grant_generation"])
    current = {"activation_id": owner["manager_activation_id"], "profile": "pi-base", "session_id": "synthetic-session",
      "role_id": "main", "cwd": str(self.work / "project"), "user_intent_ref": "synthetic-reviewed-probe",
      "restrictions_digest": digest({"probe": plan["probe_id"]}), "policy_generation": 1, "cancel_epoch": 0,
      "runtime_identity": plan["runtime_identity"], "config_identity": self.config["manifest_digest"],
      "reviewer_identity": None, "deadline_ms": int(time.time() * 1000) + 300000}
    def backend(public):
      return {"runtime_identity": plan["runtime_identity"], "helper_identity": plan["helper_identity"],
        "plan_digest": digest(compile_mount_plan(public))}
    self.bridge = ShellOperationAdmissions(self.operations, context_provider=lambda _: deepcopy(current),
      binding_name="shell", backend_preflight=backend)
    self.operations.admission_control = SimpleNamespace(shell_bridge=self.bridge)
    self._spawn_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pi-host-spawn")

  def save(self, name, value):
    with Tree(self.directory / "cases" / self.case / "observations") as tree:
      tree.write_new(name + ".json", json_bytes(value))

  def snapshot(self, lease_id):
    lease = self.store.read(lease_id)
    return {"lease": lease, "writers": [self.store.workspaces.read(row) for row in lease["planned_workspaces"]]}

  def activate(self, lease):
    before = self.snapshot(lease["lease_id"])
    require(before["lease"] == lease and lease["state"] == "running"
      and before["writers"] and all(row["state"] == "active" for row in before["writers"]))
    leader = lease["process_identity"]
    require(self.processes.observe(leader) == "alive")
    namespaces = {name: os.readlink("/proc/" + str(leader["pid"]) + "/ns/" + name) for name in NAMESPACES}
    require(self.processes.observe(leader) == "alive" and namespaces["pid"] == leader["namespace"])
    self.activated = {**before, "namespaces": namespaces}
    self.save("active-before-gate", self.activated)
    self.release_started = time.monotonic()
    super().activate(lease)

  def call(self, method, args):
    return self.service.handle(self.principal, {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": method, "args": args})


def command(work, nonce, case):
  require(re.fullmatch(r"[0-9a-f]{32}", nonce) and case in ("allowed", "denied", "background"))
  body = "/usr/bin/python3.11 -I -B -S " + shlex.quote(str(work / "readonly/payload.py")) + " --payload " + nonce + "\n"
  if case == "background":
    body = "/usr/bin/python3.11 -I -B -S " + shlex.quote(str(work / "readonly/heartbeat.py")) + " " + nonce + " &\n" + body + "wait\n"
  return body


def _events(buffer, events):
  while b"\n" in buffer:
    line, _, remainder = buffer.partition(b"\n")
    require(0 < len(line) <= 65536 and len(events) < 2)
    event = decode(line)
    require(type(event) is dict)
    events.append(event); buffer = bytearray(remainder)
  require(len(buffer) <= 65536)
  return buffer


def collect(host, lease_id, nonce):
  child = host.children[lease_id]
  capture = child["capture"]
  require(host.release_started is not None and host.activated is not None)
  deadline = host.release_started + CASE_SECONDS
  cursor, byte_count, buffer, events = 0, 0, bytearray(), []
  canceled, stop_ms, before, after = False, 0, 0, 0
  while time.monotonic() < deadline:
    host.poll()
    chunks = capture.since(cursor)
    require(not chunks["dropped"])
    cursor = chunks["next_cursor"]
    for row in chunks["events"]:
      data = base64.b64decode(row["data_b64"], validate=True)
      byte_count += len(data); require(byte_count <= MAX_BYTES)
      require(row["stream"] == "stdout" or not data)
      if row["stream"] == "stdout": buffer.extend(data); buffer = _events(buffer, events)
    if host.case == "background" and not canceled:
      require(time.monotonic() - host.release_started < 10)
      if {event.get("phase") for event in events} == {"payload", "heartbeat"} and heartbeat(host.work, nonce) > 0:
        original = host.store.read(lease_id)
        reply = host.call("cancel", {"lease_id": lease_id})
        current = host.snapshot(lease_id)
        require(reply["accepted"] and not reply["termination_confirmed"]
          and current["lease"]["state"] == "cancel_requested" and protected(current["lease"])
          and current["lease"]["grant_generation"] == original["grant_generation"] + 1
          and all(row["state"] != "released" for row in current["writers"]))
        host.save("cancel-before-poll", current)
        canceled = True
        host.poll()
        require(host.processes.termination_status(original["process_identity"]) == "terminated")
        stop_ms = int((time.monotonic() - host.release_started) * 1000)
        require(stop_ms < 10000)
        before = heartbeat(host.work, nonce)
    current = host.store.read(lease_id)
    if not protected(current) and capture.complete() and not chunks["has_more"]:
      require(child["process"].poll() is not None and not buffer)
      if host.case == "background":
        require(canceled and before > 0)
        time.sleep(0.15); after = heartbeat(host.work, nonce)
      return events, {"stop_elapsed_ms": stop_ms, "heartbeat_before": before, "heartbeat_after": after}
    time.sleep(0.01)
  raise ConfigError("pi-shell-product-probe-timeout")


def verify_events(case, nonce, events, namespaces):
  require(type(events) is list and len(events) == (2 if case == "background" else 1))
  phases = []
  for event in events:
    require(type(event) is dict and type(event.get("schema_version")) is int and event["schema_version"] == 1
      and event.get("nonce") == nonce and type(event.get("phase")) is str)
    phase = event["phase"]; phases.append(phase)
    require(phase in ("payload", "heartbeat"))
    expected = {"schema_version", "phase", "nonce", "namespaces", "observations" if phase == "payload" else "pid"}
    require(set(event) == expected and type(event["namespaces"]) is dict and set(event["namespaces"]) == set(NAMESPACES))
    for name in NAMESPACES:
      value = event["namespaces"][name]
      require(type(value) is str and re.fullmatch(name + r":\[[0-9]+\]", value) and value != namespaces[name])
    if phase == "payload":
      require(type(event["observations"]) is dict and set(event["observations"]) == set(OBSERVATIONS)
        and all(type(value) is bool and value for value in event["observations"].values()))
    else: require(type(event["pid"]) is int and event["pid"] > 1)
  if case == "background":
    require(sorted(phases) == ["heartbeat", "payload"] and events[0]["namespaces"] == events[1]["namespaces"])
  else: require(phases == ["payload"])


def verify_execution(host, plan, nonce, prepared, lease_id, events, timing):
  child = host.children[lease_id]
  snapshot = host.snapshot(lease_id); lease = snapshot["lease"]
  require(lease["state"] == "reclaimed" and not protected(lease) and lease["termination_evidence"] is not None
    and snapshot["writers"] and all(row["state"] == "released" for row in snapshot["writers"]))
  require(host.processes.termination_status(lease["process_identity"]) == "terminated" and child["capture"].complete())
  with Tree(host.root) as tree:
    raw = tree.read("activity/outputs/" + lease_id + "/capture.json")
    require(raw is not None)
    captured = decode(raw[0]); require(captured["complete"] is True and captured["truncated"] is False)
    require(captured["streams"]["stderr"]["bytes"] == 0)
    raw = tree.read("activity/ordinary-shell-handoffs/" + lease_id + ".json"); require(raw is not None)
    handoff = decode(raw[0])
  binding = handoff["binding"]; auth = binding["authorization"]
  require(binding["purpose"] == "shell-execution" and binding["worker_identity"] == lease["process_identity"]
    and binding["helper_identity"] == plan["helper_identity"] and auth["operation_id"] == prepared["operation_id"]
    and auth["operation_digest"] == prepared["operation_digest"] and auth["lease_id"] == lease_id
    and auth["runtime_identity"] == plan["runtime_identity"] and auth["lock_identity"] == plan["lock_identity"]
    and auth["slice_identity"] == plan["slice_identity"] and auth["grant_generation"] == 1
    and auth["profile_id"] == "pi-base")
  entry = host.bridge.records[prepared["operation_id"]]
  require(auth["allocation_digest"] == digest(entry["allocation"])
    and auth["context_digest"] == digest(prepared["context"]) and binding["plan_digest"] == entry["backend"]["plan_digest"])
  verify_events(host.case, nonce, events, host.activated["namespaces"])
  require(read_file(host.work, "project/positive") == (nonce + "\n").encode())
  require(all(read_file(host.work, path) == value for path, value in CANARIES.items())
    and all(not os.path.lexists(host.work / path) for path in BLOCKED))
  status = child["process"].returncode
  if host.case == "allowed": require(status == 0 and timing == {"stop_elapsed_ms": 0, "heartbeat_before": 0, "heartbeat_after": 0})
  else: require(type(status) is int and status != 0 and 0 <= timing["stop_elapsed_ms"] < 10000
    and timing["heartbeat_before"] > 0 and timing["heartbeat_before"] == timing["heartbeat_after"])
  host.save("reclaimed", snapshot)
  host.save("observed", {"events": events, "timing": timing, "exit_code": status, "handoff": handoff})


def run_case(directory, plan, case):
  host, lease_id, stage, outcome = None, None, "setup", "unavailable"
  failure = None
  try:
    host = ProbeHost(directory, plan, case)
    nonce = plan["nonces"][case]
    stage = "admission"
    try: prepared = host.bridge.prepare(host.principal, "synthetic-" + case, "bash", {"command": command(host.work, nonce, case)})
    except Conflict as error:
      if case != "denied" or str(error) != "PERMISSION_DENIED": raise
      require(not host.children and not [row for row in host.store.records() if row["kind"] != "host"]
        and not (host.work / "project/.git/agentcfg").exists() and read_file(host.work, "project/positive") is None
        and all(read_file(host.work, path) == value for path, value in CANARIES.items())
        and all(not os.path.lexists(host.work / path) for path in BLOCKED))
      host.save("denied", {"reason": "PERMISSION_DENIED", "external_leases": 0, "writer_created": False, "child_count": 0})
      outcome = "observed"
    else:
      require(case != "denied")
      permit = host.bridge.issue(host.principal, prepared["operation_id"], operation_digest=prepared["operation_digest"], source="human")
      ticket = host.bridge.consume(host.principal, permit); lease_id = ticket["lease_id"]
      initial = host.snapshot(lease_id)
      require(initial["lease"]["state"] == "allocating" and all(row["state"] == "reserved" for row in initial["writers"]))
      host.save("reserved", initial)
      stage = "start"
      started = host.call("start", {"lease_id": lease_id, "program": "ordinary-shell", "payload": {"operation_id": prepared["operation_id"]}})
      require(started["state"] == "running")
      stage = "collect"
      events, timing = collect(host, lease_id, nonce)
      stage = "verify"
      verify_execution(host, plan, nonce, prepared, lease_id, events, timing)
      outcome = "observed"
  except KeyboardInterrupt: outcome = "interrupted"
  except Exception as error:
    outcome = "failed" if stage == "verify" else "unavailable"
    # 仅固定错误类别/纯代码，无路径、正文或底层异常文本。
    raw = str(error)
    failure = {"kind": "conflict" if isinstance(error, Conflict) else "config" if isinstance(error, ConfigError) else "internal",
      "code": raw if raw in FAILURE_CODES else "PROBE_STAGE_FAILED"}
  finally:
    if host is not None:
      try:
        with host.service.mutex: host.service.closing = True
        # 失败也只停止本次已登记目标；unknown/未启动分配不强制abort或释放Writer。
        for child in host.children.values():
          if child.get("launch") is not None: child["launch"].close_gate()
          try:
            if host.processes.termination_status(child["identity"]) != "terminated": host.processes.stop(child["identity"], grace_seconds=2)
            child["process"].wait(timeout=2)
            if host.processes.termination_status(child["identity"]) != "terminated": outcome = "termination-unknown"
          except Exception: outcome = "termination-unknown"
        # 正常路径已poll回收，失败只保留最后原始租约事实，不额外制造成功证据。
        if lease_id is not None: host.save("final-lease", host.snapshot(lease_id))
        if failure is not None: host.save("failure", failure)
      finally:
        host._spawn_executor.shutdown(wait=True, cancel_futures=True)
  result = {"case_id": case, "outcome": outcome, "stage": stage,
    "checks": 0 if case == "denied" or outcome != "observed" else len(OBSERVATIONS),
    "synthetic_manager": True, "frontend_verified": False, "default_factory_enabled": False, "product_gate": False}
  with Tree(directory / "cases" / case / "observations") as tree: tree.write_new("result.json", json_bytes(result))
  return result


def run(directory):
  from .pi_shell_product_probe_bundle import preflight, CASES
  directory = Path(directory); plan = preflight(directory)
  with Tree(directory) as tree: tree.write_new("execution-started.json", json_bytes({"schema_version": 1, "probe_id": plan["probe_id"]}))
  results = []
  for case in CASES:
    result = run_case(directory, plan, case); results.append(result)
    if result["outcome"] != "observed": break
  summary = {"schema_version": 1, "cases": results, "observed": len(results) == len(CASES)
    and all(row["outcome"] == "observed" for row in results), "synthetic_manager": True,
    "frontend_verified": False, "default_factory_enabled": False, "product_gate": False}
  with Tree(directory) as tree: tree.write_new("result.json", json_bytes(summary))
  return summary


def main(argv=None):
  parser = argparse.ArgumentParser(allow_abbrev=False)
  action = parser.add_mutually_exclusive_group(required=True)
  action.add_argument("--prepare", action="store_true")
  action.add_argument("--run-native-shell-product-probe", action="store_true")
  parser.add_argument("--directory", required=True)
  args = parser.parse_args(argv)
  try:
    if args.prepare:
      from .pi_shell_product_probe_bundle import prepare
      prepare(Path(args.directory)); return 0
    return 0 if run(Path(args.directory))["observed"] else 5
  except Exception:
    return 5
