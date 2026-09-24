"""PID命名空间证明使用进程身份/信号替身；默认测试不创建命名空间或真实子进程。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import shutil
import struct
from types import SimpleNamespace
import pytest

from agentcfg.activity_linux import LinuxProcesses
from agentcfg.deployment import json_bytes
from agentcfg.pi_pid_namespace import namespace_argv, same_namespace_process
from agentcfg.storage import Conflict, Tree, ensure_private
from test_pi_activity import identity


@pytest.mark.parametrize("fault", [None, "pid", "uid", "namespace", "eof", "unexpected-byte"])
def test_host_gate_accepts_only_namespace_init_kernel_peer(fault):
  from agentcfg.pi_pid_namespace import verify_host_gate
  expected = {**identity(211), "namespace": "pid:[200]"}
  peer = (212 if fault == "pid" else 211, expected["uid"] + (fault == "uid"), 1)
  reply = b"" if fault == "eof" else b"G" if fault == "unexpected-byte" else b"R"
  connection = SimpleNamespace(getsockopt=lambda *args: struct.pack("3i", *peer), recv=lambda _: reply)
  info = {"pid-namespace": 201 if fault == "namespace" else 200}
  if fault:
    with pytest.raises(Conflict): verify_host_gate(connection, expected, info)
  else:
    verify_host_gate(connection, expected, info)


def test_host_namespace_retains_existing_filesystem_and_separate_input_gate(tmp_path):
  from agentcfg.pi_pid_namespace import host_namespace_argv
  runtime = tmp_path / "runtime"
  with Tree(runtime, create=True) as tree:
    tree.write_new("bin/codex-resources/bwrap", b"fixture")
    tree.write_new("supervisor/scripts/pi-namespace-exec.py", b"fixture")
  host = SimpleNamespace(runtime_root=runtime, repository=runtime / "supervisor")
  command = SimpleNamespace(cwd=tmp_path, argv=("fixture-host", "--interactive"))
  argv = host_namespace_argv(host, command, 42, "a" * 64)
  assert "--unshare-pid" in argv and "--as-pid-1" in argv and "--cap-drop" in argv
  at = argv.index("--bind")
  assert argv[at:at + 3] == ["--bind", "/", "/"]
  assert argv[-5:] == ["--host-gate", "a" * 64, "--", "fixture-host", "--interactive"]


def test_every_profile_locks_both_linux_host_namespace_helpers():
  root = Path(__file__).resolve().parents[1]
  requirements = json.loads((root / "agents/pi/dependencies.json").read_text())
  for profile in requirements["profiles"].values():
    for platform in ("linux-arm64", "linux-x86_64"):
      name = "codex-bwrap-" + platform
      assert name in profile["source_ids"]
      source = requirements["sources"][name]
      assert source["target"] == "bin/codex-resources/bwrap" and source["platform"] == platform


def setup(tmp_path):
  processes = LinuxProcesses(tmp_path / "records", proc_root=tmp_path / "proc", clock=lambda: 0, pause=lambda _: None)
  wrapper = {**identity(210), "pgid": 210, "namespace": "pid:[100]"}
  init = {**identity(211), "ppid": 210, "pgid": 210, "namespace": "pid:[200]"}
  current = {210: deepcopy(wrapper), 211: deepcopy(init)}
  processes.identity = lambda pid: current[pid] if pid in current else (_ for _ in ()).throw(FileNotFoundError())
  status = processes.proc_root / "211"; status.mkdir(parents=True)
  (status / "status").write_text("Name:\tfixture\nNSpid:\t211\t1\n")
  signals = []
  def send(expected, number):
    signals.append((expected["pid"], number)); current.pop(expected["pid"], None)
    if expected["pid"] == 211:
      shutil.rmtree(processes.proc_root / "211")
      current.pop(210, None)  # 内核收束后包装进程wait返回。
  processes.send_signal = send
  return processes, current, wrapper, init, signals


def test_namespace_tracks_init_and_wrapper_without_polling_short_lived_groups(tmp_path):
  p, current, wrapper, init, signals = setup(tmp_path)
  p.register_namespace(init, wrapper)
  p._scan = lambda: pytest.fail("namespace proof must not depend on descendant polling")
  assert p.termination_status(init) == "active"
  p.stop(init)
  assert signals == [(211, signal.SIGKILL)]
  assert p.termination_status(init) == "terminated"
  current[211] = {**init, "start_time": "999999", "namespace": "pid:[999]"}
  assert p.termination_status(init) == "terminated"  # 已证明结束的旧命名空间不被复用PID复活。


@pytest.mark.parametrize("fault", ["same-namespace", "foreign-user", "wrong-parent", "not-init", "boot"])
def test_namespace_registration_rejects_unproven_scope(tmp_path, fault):
  p, current, wrapper, init, _ = setup(tmp_path)
  if fault == "same-namespace": init["namespace"] = wrapper["namespace"]
  if fault == "foreign-user": init["uid"] = os.geteuid() + 1
  if fault == "wrong-parent": init["ppid"] += 10
  if fault == "boot": init["boot_id"] = "other-boot"
  if fault == "not-init": (p.proc_root / "211/status").write_text("NSpid:\t211\t2\n")
  current[211] = deepcopy(init)
  with pytest.raises(Conflict): p.register_namespace(init, wrapper)
  assert not p.record_root.exists()


def test_changed_birth_identity_never_receives_a_signal_or_clears_protection(tmp_path):
  p, current, wrapper, init, signals = setup(tmp_path); p.register_namespace(init, wrapper)
  current[211]["start_time"] = "999999"
  assert p.termination_status(init) == "unknown"
  with pytest.raises(Conflict): p.stop(init)
  assert not signals


def test_namespace_worker_matches_immutable_birth_not_namespace_local_pid_numbers():
  expected = {**identity(211), "namespace": "pid:[200]"}
  actual = {**expected, "pid": 1, "ppid": 0, "pgid": 0}
  assert same_namespace_process(expected, actual)
  assert not same_namespace_process({"platform": "linux"}, {"platform": "linux", "pid": 1})
  assert not same_namespace_process(expected, {**actual, "pid": True})
  for key, value in (("start_time", "different"), ("namespace", "pid:[201]"), ("uid", expected["uid"] + 1), ("pid", 2)):
    assert not same_namespace_process(expected, {**actual, key: value})


def test_namespace_argv_binds_private_paths_and_keeps_runtime_readonly(tmp_path):
  runtime, state, instance, project, python_root = (tmp_path / name for name in ("runtime", "state", "instance", "project", "python"))
  for path in (runtime, state, instance, project, python_root): ensure_private(path)
  with Tree(runtime) as tree:
    tree.write_new("bin/codex-resources/bwrap", b"fixture, never execute")
    tree.write_new("supervisor/scripts/pi-namespace-exec.py", b"fixture")
  with Tree(project) as tree: tree.write_new(".git/HEAD", b"fixture")
  host = SimpleNamespace(runtime_root=runtime, root=state, repository=runtime / "supervisor", config={"instance_root": str(instance)},
    manifest=lambda: {"options": {"paths": {"roots": {"project": {"path": str(project), "purpose": "project"}}}}},
    store=SimpleNamespace(workspaces=SimpleNamespace(identify=lambda _: {"git_dir_path": str(project / ".git")})))
  command = SimpleNamespace(cwd=project, argv=("/fixture/python", "/fixture/worker"))
  argv = namespace_argv(host, command, 42)
  assert "--as-pid-1" in argv and "--unshare-pid" in argv and "--unshare-net" not in argv
  mounts = list(zip(argv, argv[1:], argv[2:]))
  assert ("--bind", str(instance), str(instance)) in mounts
  assert ("--ro-bind", str(runtime), str(runtime)) in mounts
  assert ("--bind", "/", "/") not in mounts
  assert argv[-2:] == list(command.argv)


def test_namespace_zombie_is_dead_even_if_its_namespace_link_is_still_readable(tmp_path):
  from agentcfg.pi_pid_namespace import namespace_process_status
  p, current, wrapper, init, _ = setup(tmp_path)
  boot = p.proc_root / "sys/kernel/random"; boot.mkdir(parents=True); (boot / "boot_id").write_text(init["boot_id"])
  tail = ["Z", "210", "210", *(["0"] * 16), init["start_time"]]
  (p.proc_root / "211/stat").write_text("211 (fixture) " + " ".join(tail))
  assert p.observe(init) == "alive"  # 替身模拟仍能读取ns链接的僵尸。
  assert namespace_process_status(p, init) == "dead"
  tail[19] = "999999"; (p.proc_root / "211/stat").write_text("211 (fixture) " + " ".join(tail))
  p.observe = lambda _: "unknown"
  assert namespace_process_status(p, init) == "unknown"


def test_local_namespace_birth_handles_an_outside_process_group_leader(tmp_path):
  from agentcfg.pi_pid_namespace import local_namespace_identity
  root = tmp_path / "proc"; child = root / "1"; (child / "ns").mkdir(parents=True)
  (child / "ns/pid").symlink_to("pid:[200]")
  tail = ["S", "0", "0", *(["0"] * 16), "123"]
  (child / "stat").write_text("1 (fixture) " + " ".join(tail))
  boot = root / "sys/kernel/random"; boot.mkdir(parents=True); (boot / "boot_id").write_text("fixture-boot")
  actual = local_namespace_identity(root, pid=1)
  assert actual["start_time"] == "123" and actual["namespace"] == "pid:[200]" and actual["pid"] == 1


@pytest.mark.parametrize("fault", [None, "unknown", "boolean", "partial"])
def test_namespace_handshake_is_closed_and_complete(fault):
  from agentcfg.pi_pid_namespace import read_namespace_info
  value = {"child-pid": 2, "mnt-namespace": 3, "pid-namespace": 4}
  if fault == "unknown": value["unselected"] = "synthetic-private"
  if fault == "boolean": value["child-pid"] = True
  raw = json.dumps(value).encode()
  if fault == "partial": raw = raw[:-1]
  read, write = os.pipe()
  try:
    os.write(write, raw); os.close(write); write = None
    if fault:
      with pytest.raises(Conflict): read_namespace_info(read)
    else: assert read_namespace_info(read) == value
  finally:
    os.close(read)
    if write is not None: os.close(write)


def test_legacy_long_running_host_record_does_not_inherit_the_namespace_size_limit(tmp_path):
  from agentcfg.pi_pid_namespace import namespace_record
  p, current, wrapper, init, _ = setup(tmp_path)
  leader = wrapper
  members = {str(leader["pid"]): leader}
  for pid in range(1000, 1500): members[str(pid)] = {**identity(pid), "ppid": leader["pid"], "pgid": leader["pgid"], "namespace": leader["namespace"]}
  with Tree(p.record_root, create=True) as tree:
    raw = json_bytes({"schema_version": 1, "leader": leader, "members": members, "escaped": False})
    assert len(raw) > 65536
    tree.write_new(p._path(leader), raw)
  p._scan = lambda: {str(leader["pid"]): leader}
  assert namespace_record(p, leader) is None
  assert p.termination_status(leader) == "active"
