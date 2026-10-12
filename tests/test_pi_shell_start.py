"""真实准入/租约/FD作用域，假helper与进程；绝不启动第三方宿主。"""

from contextlib import contextmanager
from dataclasses import replace
from copy import deepcopy
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import pi_shell_start as start
from agentcfg import pi_host
from agentcfg import pi_shell_mounts
from agentcfg.activity import protected
from agentcfg.activity import digest
from agentcfg.pi_supervisor import SpawnCommand
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_activity import identity
from test_pi_shell_launch import configured, launched


def fixture(tmp_path, monkeypatch, *, physical=False):
  f = configured(tmp_path)
  if physical:
    original_preflight = f[0].backend_preflight
    def preflight(public):
      backend = original_preflight(public)
      backend["mount_plan"] = pi_shell_mounts.compile_mount_plan(public, system_roots=())
      backend["plan_digest"] = digest(backend["mount_plan"])
      return backend
    f[0].backend_preflight = preflight
  prepared, ticket, lease, command = launched(f)
  bridge, host, launch = f[0], f[2], command.launch
  state = SimpleNamespace(f=f, command=command, launch=launch, lease=lease, events=[],
    parent_fds=[], gate_read=None, process=None, fault=None, handoffs=[], stopped=[])
  host.processes = host.store.processes
  host.children = {}
  host.spawn = lambda selected, row: pi_host.HostSupervisor._spawn(host, selected, row)
  host.activate = lambda row: pi_host.HostSupervisor.activate(host, row)
  host.service.activate = host.activate
  host.service.command_resolver = lambda row, program, payload: bridge.command(row, payload)
  # 固定使用被观察的描述；再次请求仍由真实bridge拒绝正文重取。
  def resolve(row, program, payload):
    if launch.attempted: return bridge.command(row, payload)
    assert row == lease and payload == {"operation_id": prepared["operation_id"]}
    return command
  host.service.command_resolver = resolve
  monkeypatch.setattr(start, "host_namespace_binary", lambda current: tmp_path / "fake-helper")
  @contextmanager
  def preparation(public, private, **kwargs):
    assert "private-script-sentinel" in private and bridge.records[prepared["operation_id"]]["private"] is None
    state.events.append("prepare")
    if state.fault == "prepare": raise Conflict("fixture-prepare")
    fd = os.memfd_create("synthetic-parent-source", os.MFD_CLOEXEC)
    source = os.memfd_create("synthetic-separate-source", os.MFD_CLOEXEC)
    state.parent_fds.extend((fd, source))
    try:
      yield SimpleNamespace(helper_fd=fd, pass_fds=(source,), snapshots=(),
        argv=(str(tmp_path / "fake-helper"), "--ro-bind-fd", str(source), "/usr", "--chdir", str(command.cwd)))
    finally:
      state.events.append("close-preparation"); os.close(source); os.close(fd)
  monkeypatch.setattr(start, "prepare_shell_execution", preparation)
  deps = tmp_path / "dependencies"; deps.mkdir()
  monkeypatch.setattr(start.sysconfig, "get_paths", lambda: {"purelib": str(deps)})
  monkeypatch.setattr(start, "sys", SimpleNamespace(executable="/usr/bin/python3.11"))
  monkeypatch.setattr(start, "identity_projection", lambda *args, **kwargs: {
    "worker_user_namespace": "user:[321]", "uid_projection": [{"host_uid": os.geteuid(), "visible_uid": os.geteuid()}]})
  def seal(fd, execution, binding):
    state.events.append("seal"); state.handoffs.append(deepcopy(binding))
    row = host.store.read(lease["lease_id"])
    assert row["state"] == "running"
    assert host.store.workspaces.read(row["planned_workspaces"][0])["state"] == "active"
    if state.fault == "seal": raise ConfigError("fixture-seal")
  monkeypatch.setattr(start, "seal_handoff", seal)
  class Process:
    pid = 204
    stdin = None
    def __init__(self):
      self.stdout = open(os.devnull, "rb"); self.stderr = open(os.devnull, "rb")
      self.returncode = None
    def poll(self): return self.returncode
    def wait(self, **kwargs): self.returncode = 0; return 0
    def kill(self): self.returncode = -9
  def popen(argv, **kwargs):
    state.events.append("spawn")
    assert host.store.read(lease["lease_id"])["state"] == "starting"
    if state.fault == "spawn": raise OSError("fixture-spawn")
    assert kwargs["env"] == {} and kwargs["shell"] is False
    assert kwargs["executable"] == "/proc/self/fd/" + str(launch.execution.helper_fd)
    assert not {"AGENTCFG_SUPERVISOR_ENDPOINT", "AGENTCFG_SUPERVISOR_CAPABILITY"} & set(command.environment)
    assert "private-script-sentinel" not in repr(argv) + repr(kwargs)
    state.argv = argv; state.kwargs = kwargs
    state.parent_fds.extend(fd for fd in kwargs["pass_fds"] if fd not in state.parent_fds)
    state.gate_read = os.dup(kwargs["stdin"])
    state.process = Process()
    return state.process
  monkeypatch.setattr(start.subprocess, "Popen", popen)
  monkeypatch.setattr(start, "read_namespace_info", lambda fd: {"child-pid": 203, "pid-namespace": 123})
  def ready(stream):
    state.events.append("ready")
    if state.fault == "ready": raise Conflict("fixture-ready")
  monkeypatch.setattr(start, "_ready", ready)
  born = {**identity(203), "namespace": "pid:[123]"}
  host.processes.identity = lambda pid: born if pid == 203 else identity(pid)
  def register(leader, wrapper):
    state.events.append("register")
    assert state.events.index("ready") < state.events.index("register")
    if state.fault == "register": raise Conflict("fixture-register")
    host.processes.current[203] = leader
  host.processes.register_namespace = register
  def stop(leader, **kwargs):
    state.stopped.append(leader); host.processes.current.pop(leader["pid"], None)
  host.processes.stop = stop
  class Capture:
    def __init__(self, root): self.root = root
    def attach(self, child):
      state.events.append("attach")
      if state.fault == "capture": raise OSError("fixture-capture")
    def complete(self): return True
  monkeypatch.setattr(pi_host, "OutputCapture", Capture)
  state.message = {"schema_version": 1, "request_id": "start-shell", "method": "start", "args": {
    "lease_id": lease["lease_id"], "program": "ordinary-shell", "payload": {"operation_id": prepared["operation_id"]}}}
  state.invoke = lambda: host.service.handle(f[3], state.message)
  return state


def cleanup(state):
  if state.gate_read is not None: os.close(state.gate_read)
  if state.process is not None:
    state.process.stdout.close(); state.process.stderr.close()


def closed_fds(state):
  for fd in state.parent_fds:
    with pytest.raises(OSError): os.fstat(fd)


def test_running_writer_precedes_sealing_and_single_gate_release(tmp_path, monkeypatch):
  state = fixture(tmp_path, monkeypatch)
  try:
    result = state.invoke()
    assert result["state"] == "running" and state.launch.released
    assert os.read(state.gate_read, 2) == b"G"
    assert state.events == ["prepare", "spawn", "ready", "register", "attach", "seal", "close-preparation"]
    closed_fds(state)
    host = state.f[2]
    entry = state.launch.entry
    assert entry["private"] is None and entry["input_taken"] and state.launch.private is None
    assert host.children[state.lease["lease_id"]]["gate"] is None
    assert state.handoffs[0]["authorization"]["lease_id"] == state.lease["lease_id"]
    saved = json.loads((host.root / "activity/ordinary-shell-handoffs" / (state.lease["lease_id"] + ".json")).read_bytes())
    assert saved["binding"] == state.handoffs[0]
    assert "private-script-sentinel" not in b"\n".join(path.read_bytes() for path in host.root.rglob("*") if path.is_file()).decode()
    with pytest.raises(Conflict): state.invoke()
    assert state.events.count("spawn") == 1 and state.stopped == []
  finally: cleanup(state)


def test_start_reuses_semantic_checks_but_scans_once_before_gate(tmp_path, monkeypatch):
  state = fixture(tmp_path, monkeypatch)
  try:
    before = len(state.f[5])
    state.invoke()
    # command的完整复核已在fixture构造时完成；start末端仍需一次完整后端复核。
    assert len(state.f[5]) - before == 1
    assert state.launch.released and os.read(state.gate_read, 2) == b"G"
  finally: cleanup(state)


def test_private_script_change_after_pin_refuses_gate_and_keeps_writer(tmp_path, monkeypatch):
  state = fixture(tmp_path, monkeypatch); host = state.f[2]
  original = host.service.activate
  def activate(lease):
    state.launch.private["command"] += "\nprintf 'changed'\n"
    original(lease)
  host.service.activate = activate
  try:
    with pytest.raises(Conflict): state.invoke()
    assert os.read(state.gate_read, 2) == b"" and not state.handoffs
    assert protected(host.store.read(state.lease["lease_id"]))
    closed_fds(state)
  finally: cleanup(state)


def test_deadline_expires_during_final_scan_without_gate(tmp_path, monkeypatch):
  state = fixture(tmp_path, monkeypatch); bridge = state.f[0]
  original_preflight = bridge.backend_preflight
  def preflight(public):
    result = original_preflight(public)
    monkeypatch.setattr(bridge, "_now_ms", lambda: state.launch.entry["prepared"]["context"]["deadline_ms"])
    return result
  bridge.backend_preflight = preflight
  try:
    with pytest.raises(Conflict): state.invoke()
    assert os.read(state.gate_read, 2) == b"" and len(state.handoffs) == 1
    assert not state.launch.released
    assert protected(state.f[2].store.read(state.lease["lease_id"]))
    closed_fds(state)
  finally: cleanup(state)


@pytest.mark.parametrize("change", ["nested-git", "git-alias", "socket-stat", "policy", "held-fd"])
def test_post_pin_changes_are_rechecked_before_gate(tmp_path, monkeypatch, change):
  state = fixture(tmp_path, monkeypatch, physical=True); host = state.f[2]
  project = Path(state.launch.entry["physical"]["cwd"])
  # 子目录在初始计划之后出现是安全普通目录；新增.git必须由最后整树扫描发现。
  nested = project / "nested"; nested.mkdir()
  original_activate = host.service.activate
  original_preparation = start.prepare_shell_execution
  @contextmanager
  def preparation(public, private, **kwargs):
    with pi_shell_mounts.pin_mount_plan(public, system_roots=()) as pinned:
      with original_preparation(public, private, **kwargs) as execution:
        execution.snapshots = tuple((fd, start._snapshot(os.fstat(fd)))
          for fd in pinned["source_fds"].values())
        execution.snapshots += ((execution.helper_fd, start._snapshot(os.fstat(execution.helper_fd))),)
        yield execution
  monkeypatch.setattr(start, "prepare_shell_execution", preparation)
  def activate(lease):
    if change == "nested-git": (nested / ".git").mkdir()
    if change == "git-alias": (nested / ".git").symlink_to(project)
    if change == "socket-stat":
      os.mkfifo(nested / "socket-new")
      original_stat = os.stat
      def info(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path == "socket-new" and kwargs.get("dir_fd") is not None:
          values = list(value); values[0] = stat.S_IFSOCK | 0o600
          return os.stat_result(values)
        return value
      monkeypatch.setattr(os, "stat", info)
    if change == "policy": host.manifest()["permission_policy"]["rules"][-1]["effect"] = "deny"
    if change == "held-fd": os.write(state.launch.execution.helper_fd, b"changed")
    original_activate(lease)
  host.service.activate = activate
  try:
    with pytest.raises((Conflict, ConfigError)): state.invoke()
    assert os.read(state.gate_read, 2) == b"" and not state.launch.released
    assert len(state.handoffs) == (1 if change in ("nested-git", "git-alias", "socket-stat") else 0)
    assert protected(host.store.read(state.lease["lease_id"]))
    assert host.store.workspaces.read(state.lease["planned_workspaces"][0])["state"] != "released"
    with pytest.raises(Conflict): state.invoke()
    closed_fds(state)
  finally: cleanup(state)


@pytest.mark.parametrize("fault,expected", [("prepare", "allocating"), ("binding", "allocating"),
  ("starting", "starting"), ("spawn", "unknown"), ("ready", "unknown"), ("register", "unknown"),
  ("capture", "unknown"), ("workspace", "unknown"), ("seal", "running"), ("handoff-record", "running"),
  ("gate", "running")])
def test_failures_close_parent_scope_keep_writer_and_never_retry(tmp_path, monkeypatch, fault, expected):
  state = fixture(tmp_path, monkeypatch); state.fault = fault
  host = state.f[2]
  original = Tree.write_immutable
  def write(self, path, data, *args, **kwargs):
    if fault == "binding" and str(path).startswith("activity/commands/"): raise OSError("fixture-binding")
    if fault == "handoff-record" and str(path).startswith("activity/ordinary-shell-handoffs/"): raise OSError("fixture-record")
    return original(self, path, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "write_immutable", write)
  if fault == "starting":
    host.store.fault = lambda point, row: (_ for _ in ()).throw(OSError("fixture-starting")) if point == "starting" else None
  if fault == "workspace":
    monkeypatch.setattr(host.store.workspaces, "activate", lambda *args: (_ for _ in ()).throw(OSError("fixture-workspace")))
  real_write = os.write
  def fd_write(fd, body):
    if body == b"G": raise OSError("fixture-gate")
    return real_write(fd, body)
  if fault == "gate": monkeypatch.setattr(start, "os", SimpleNamespace(**{**vars(os), "write": fd_write}))
  try:
    with pytest.raises((OSError, Conflict, ConfigError)): state.invoke()
    closed_fds(state)
    assert not state.launch.released and state.launch.private is None and not state.launch.active
    row = host.store.read(state.lease["lease_id"])
    assert row["state"] == expected and protected(row)
    assert host.store.workspaces.read(row["planned_workspaces"][0])["state"] != "released"
    assert state.launch.entry["private"] is None and state.launch.entry["input_taken"]
    if state.gate_read is not None: assert os.read(state.gate_read, 2) == b""
    with pytest.raises(Conflict): state.invoke()
    assert state.events.count("spawn") <= 1
  finally: cleanup(state)


@pytest.mark.parametrize("fault", ["revoke", "deadline", "parent", "backend", "grant", "lock", "slice", "profile"])
def test_authority_change_between_running_and_gate_refuses(tmp_path, monkeypatch, fault):
  state = fixture(tmp_path, monkeypatch); host = state.f[2]
  original = host.service.activate
  def activate(lease):
    if fault == "revoke": state.launch.entry["input_revoked"] = True
    if fault == "deadline": state.launch.entry["run_deadline_ms"] = 0
    if fault == "parent": host.processes.current.pop(202)
    if fault == "backend": state.f[6]["helper_identity"] = "9" * 64
    if fault == "grant": host.store.request_cancel(lease["lease_id"], host.store.owner)
    if fault == "lock": host.config["lock_identity"] = "9" * 64
    if fault == "slice": host.config["slice_identity"] = "9" * 64
    if fault == "profile": host.manifest()["profile_id"] = "pi-full"
    original(lease)
  host.service.activate = activate
  try:
    with pytest.raises(Conflict): state.invoke()
    assert os.read(state.gate_read, 2) == b"" and not state.launch.released
    # synthetic后端元数据漂移由最终full核拒绝，已有记录不等于G授权。
    assert len(state.handoffs) == (1 if fault == "backend" else 0)
    closed_fds(state)
    assert protected(host.store.read(state.lease["lease_id"]))
  finally: cleanup(state)


def test_reused_gate_number_is_not_closed_or_written(tmp_path, monkeypatch):
  state = fixture(tmp_path, monkeypatch); host = state.f[2]; reused = []
  original = host.service.activate
  def activate(lease):
    gate = state.launch.gate
    os.close(gate)
    foreign = os.open(os.devnull, os.O_WRONLY)
    if foreign != gate: os.dup2(foreign, gate); os.close(foreign)
    reused.append(gate)
    original(lease)
  host.service.activate = activate
  try:
    with pytest.raises(Conflict): state.invoke()
    assert os.read(state.gate_read, 2) == b""
    assert os.fstat(reused[0])
    assert host.children[state.lease["lease_id"]]["gate"] is None
  finally:
    for fd in reused: os.close(fd)
    cleanup(state)


@pytest.mark.parametrize("fields", [{"process_scope": "linux-shell"}, {"launch": object()},
  {"process_scope": "linux-shell", "launch": object()}])
def test_only_internal_launch_type_can_select_product_scope(tmp_path, fields):
  with pytest.raises(ConfigError): SpawnCommand(("fake",), tmp_path, {}, **fields)


@pytest.mark.parametrize("fault,abortable", [("prepare", True), ("spawn", False), ("seal", False)])
def test_only_uncommitted_failure_allows_explicit_abort(tmp_path, monkeypatch, fault, abortable):
  state = fixture(tmp_path, monkeypatch); state.fault = fault; host = state.f[2]
  try:
    with pytest.raises((Conflict, ConfigError)): state.invoke()
    if abortable:
      row = host.store.abort_allocation(state.lease["lease_id"], host.store.owner)
      assert not protected(row)
      assert host.store.workspaces.read(row["planned_workspaces"][0])["state"] == "released"
    else:
      with pytest.raises(Conflict): host.store.abort_allocation(state.lease["lease_id"], host.store.owner)
      assert protected(host.store.read(state.lease["lease_id"]))
  finally: cleanup(state)


def test_finished_output_and_authoritative_termination_both_precede_writer_release(tmp_path, monkeypatch):
  state = fixture(tmp_path, monkeypatch); host = state.f[2]
  host.host_lease_id, host.host_exit = state.f[3].lease_id, None
  try:
    state.invoke()
    row = host.store.read(state.lease["lease_id"])
    child = host.children[row["lease_id"]]
    # wrapper先退出不能证明PID范围已终止；即使capture已完毕，也必须保持Writer。
    state.process.returncode = 0
    pi_host.HostSupervisor.poll(host)
    assert protected(host.store.read(row["lease_id"]))
    host.processes.current.pop(203)
    monkeypatch.setattr(child["capture"], "complete", lambda: False)
    pi_host.HostSupervisor.poll(host)
    assert protected(host.store.read(row["lease_id"]))
    monkeypatch.setattr(child["capture"], "complete", lambda: True)
    pi_host.HostSupervisor.poll(host)
    assert not protected(host.store.read(row["lease_id"]))
    assert host.store.workspaces.read(row["planned_workspaces"][0])["state"] == "released"
  finally: cleanup(state)


@pytest.mark.parametrize("change", ["nested-git", "policy"])
def test_change_after_persisted_handoff_is_rejected_before_gate(tmp_path, monkeypatch, change):
  state = fixture(tmp_path, monkeypatch, physical=True); host = state.f[2]
  project = Path(state.launch.entry["physical"]["cwd"])
  nested = project / "already-present"; nested.mkdir()
  original = Tree.write_immutable
  written = []
  def write(self, key, value, *args, **kwargs):
    result = original(self, key, value, *args, **kwargs)
    if key == "activity/ordinary-shell-handoffs/" + state.lease["lease_id"] + ".json":
      written.append(key)
      before = project.stat().st_mtime_ns
      if change == "nested-git": (nested / ".git").mkdir()
      else: host.manifest()["permission_policy"]["rules"][-1]["effect"] = "deny"
      assert project.stat().st_mtime_ns == before
    return result
  monkeypatch.setattr(Tree, "write_immutable", write)
  try:
    with pytest.raises((Conflict, ConfigError)): state.invoke()
    assert len(written) == 1 and len(state.handoffs) == 1
    with Tree(host.root) as tree: assert tree.read(written[0]) is not None
    assert os.read(state.gate_read, 2) == b"" and not state.launch.released
    row = host.store.read(state.lease["lease_id"])
    assert protected(row)
    assert host.store.workspaces.read(row["planned_workspaces"][0])["state"] != "released"
    closed_fds(state)
  finally: cleanup(state)
