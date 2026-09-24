"""Linux /proc 与信号均用临时文件/回调替身；不执行原生监督或bwrap。"""

from pathlib import Path
import shutil
import signal

import pytest

from agentcfg.activity_linux import LinuxProcesses
from agentcfg.storage import Conflict


def proc_fixture(tmp_path):
  root = tmp_path / "proc"
  (root / "sys/kernel/random").mkdir(parents=True)
  (root / "sys/kernel/random/boot_id").write_text("fixture-boot")
  def put(pid, *, ppid=1, pgid=None, start=100):
    path = root / str(pid)
    path.mkdir(exist_ok=True)
    fields = ["S", str(ppid), str(pgid or pid)] + ["0"] * 16 + [str(start)]
    (path / "stat").write_text(str(pid) + " (fixture name) " + " ".join(fields))
    (path / "ns").mkdir(exist_ok=True)
    for name, target in (("pid", "pid:[fixture]"), ("mnt", "mnt:[fixture]")):
      link = path / "ns" / name
      if not link.is_symlink():
        link.symlink_to(target)
  return root, put


def test_identity_uses_boot_start_namespace_and_accepts_reparenting(tmp_path):
  root, put = proc_fixture(tmp_path)
  put(201, ppid=101)
  backend = LinuxProcesses(tmp_path / "records", proc_root=root)
  expected = backend.identity(201)
  assert expected["start_time"] == "100"
  put(201, ppid=1)
  assert backend.observe(expected) == "alive"
  put(201, ppid=1, start=101)
  assert backend.observe(expected) == "unknown"


def test_parent_exit_does_not_hide_known_child_and_stop_uses_owned_identity(tmp_path):
  root, put = proc_fixture(tmp_path)
  put(201)
  calls = []
  def send(expected, number):
    calls.append((expected["pid"], number))
    shutil.rmtree(root / str(expected["pid"]))
  backend = LinuxProcesses(tmp_path / "records", proc_root=root, send_signal=send)
  expected = backend.identity(201)
  backend.register(expected)
  put(202, ppid=201, pgid=201, start=110)
  assert backend.termination_status(expected) == "active"
  shutil.rmtree(root / "201")
  put(202, ppid=1, pgid=201, start=110)
  assert backend.termination_status(expected) == "active"
  backend.stop(expected)
  assert calls == [(202, signal.SIGTERM)]
  assert backend.termination_status(expected) == "terminated"


def test_escaped_or_reused_process_remains_unknown_without_signals(tmp_path):
  root, put = proc_fixture(tmp_path)
  put(201)
  calls = []
  backend = LinuxProcesses(tmp_path / "records", proc_root=root, send_signal=lambda *args: calls.append(args))
  expected = backend.identity(201)
  backend.register(expected)
  put(202, ppid=201, pgid=202, start=110)
  assert backend.termination_status(expected) == "unknown"
  with pytest.raises(Conflict):
    backend.stop(expected)
  assert calls == []


def test_explicit_codex_child_groups_are_stopped_by_verified_member_identity(tmp_path):
  root, put = proc_fixture(tmp_path); put(201)
  calls = []
  def send(expected, number):
    calls.append((expected["pid"], number)); shutil.rmtree(root / str(expected["pid"]))
  backend = LinuxProcesses(tmp_path / "records", proc_root=root, send_signal=send)
  expected = backend.identity(201); backend.register(expected, child_groups=True)
  put(202, ppid=201, pgid=202, start=110)
  put(203, ppid=202, pgid=202, start=120)
  assert backend.termination_status(expected) == "active"
  shutil.rmtree(root / "201"); put(202, ppid=1, pgid=202, start=110)
  backend.stop(expected)
  assert calls == [(203, signal.SIGTERM), (202, signal.SIGTERM)]
  assert backend.termination_status(expected) == "terminated"


@pytest.mark.parametrize("fault", ["group-change", "unknown-member", "registration-change"])
def test_codex_subgroups_do_not_allow_identity_changes_or_unowned_group_members(tmp_path, fault):
  root, put = proc_fixture(tmp_path); put(201)
  calls = []
  backend = LinuxProcesses(tmp_path / "records", proc_root=root, send_signal=lambda *args: calls.append(args))
  expected = backend.identity(201); backend.register(expected, child_groups=True)
  put(202, ppid=201, pgid=202, start=110)
  assert backend.termination_status(expected) == "active"
  if fault == "registration-change":
    with pytest.raises(Conflict): backend.register(expected)
  else:
    if fault == "group-change": put(202, ppid=201, pgid=203, start=110)
    else: put(203, ppid=1, pgid=202, start=120)
    assert backend.termination_status(expected) == "unknown"
    with pytest.raises(Conflict): backend.stop(expected)
  assert calls == []


def test_kill_follows_term_and_complete_observation_is_required(tmp_path):
  root, put = proc_fixture(tmp_path)
  put(201)
  calls, clock = [], [0.0]
  def send(expected, number):
    calls.append(number)
    if number == signal.SIGKILL:
      shutil.rmtree(root / str(expected["pid"]))
  def pause(seconds):
    clock[0] += seconds
  backend = LinuxProcesses(tmp_path / "records", proc_root=root, send_signal=send, clock=lambda: clock[0], pause=pause)
  expected = backend.identity(201)
  backend.register(expected)
  backend.stop(expected, grace_seconds=0.1)
  assert calls == [signal.SIGTERM, signal.SIGKILL]
  assert backend.termination_status(expected) == "terminated"


def test_lost_containment_record_is_not_proof_of_termination(tmp_path):
  root, put = proc_fixture(tmp_path)
  put(201)
  backend = LinuxProcesses(tmp_path / "records", proc_root=root)
  expected = backend.identity(201)
  shutil.rmtree(root / "201")
  assert backend.observe(expected) == "dead"
  assert backend.termination_status(expected) == "unknown"


@pytest.mark.parametrize("child_groups", [False, True])
def test_missing_leader_from_persistent_members_cannot_prove_termination(tmp_path, child_groups):
  import json
  from agentcfg.storage import Tree
  from agentcfg.deployment import json_bytes
  root, put = proc_fixture(tmp_path); put(201)
  backend = LinuxProcesses(tmp_path / "records", proc_root=root)
  expected = backend.identity(201); backend.register(expected, child_groups=child_groups)
  with Tree(backend.record_root) as tree:
    name = backend._path(expected); record = json.loads(tree.read(name)[0]); record["members"] = {}
    tree.write_state(name, json_bytes(record))
  shutil.rmtree(root / "201")
  assert backend.termination_status(expected) == "unknown"


def test_explicit_force_uses_only_owned_pidfds_without_a_term_grace(tmp_path):
  root, put = proc_fixture(tmp_path); put(201)
  calls = []
  def send(expected, number):
    calls.append((expected["pid"], number)); shutil.rmtree(root / str(expected["pid"]))
  backend = LinuxProcesses(tmp_path / "records", proc_root=root, send_signal=send)
  expected = backend.identity(201); backend.register(expected)
  backend.stop(expected, force=True)
  assert calls == [(201, signal.SIGKILL)] and backend.termination_status(expected) == "terminated"


def test_unrelated_namespace_permission_failure_does_not_block_owned_process_registration(tmp_path, monkeypatch):
  root, put = proc_fixture(tmp_path); put(201); put(301)
  backend = LinuxProcesses(tmp_path / "records", proc_root=root)
  expected = backend.identity(201)
  original = backend.identity
  def restricted(pid):
    if pid == 301: raise PermissionError("synthetic inaccessible namespace")
    return original(pid)
  monkeypatch.setattr(backend, "identity", restricted)
  backend.register(expected)
  assert backend.termination_status(expected) == "active"
  put(301, ppid=201, pgid=201)
  assert backend.termination_status(expected) == "unknown"
  with pytest.raises(Conflict): backend.stop(expected)


@pytest.mark.parametrize("settles", [True, False])
def test_stop_observes_transient_exit_uncertainty_without_signaling_unknown_identity(tmp_path, settles):
  root, put = proc_fixture(tmp_path); put(201)
  calls, now = [], [0.0]
  def send(expected, number):
    calls.append((expected["pid"], number))
    (root / "201/ns/pid").unlink()  # 退出期间ns链接先消失，stat目录仍存在。
  def pause(seconds):
    now[0] += seconds
    if settles and (root / "201").exists(): shutil.rmtree(root / "201")
  backend = LinuxProcesses(tmp_path / "records", proc_root=root, send_signal=send, clock=lambda: now[0], pause=pause)
  expected = backend.identity(201); backend.register(expected)
  if settles:
    backend.stop(expected, grace_seconds=.1)
    assert backend.termination_status(expected) == "terminated"
  else:
    with pytest.raises(Conflict): backend.stop(expected, grace_seconds=.1)
    assert backend.termination_status(expected) == "unknown"
  assert calls == [(201, signal.SIGTERM)]
