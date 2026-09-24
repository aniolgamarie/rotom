"""假libproc响应和控制客户端；不会启动C helper、宿主或发信号。"""

from copy import deepcopy
import hashlib
import json
import os

import pytest

from agentcfg.activity_macos import MacProcesses
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict


def fixture(tmp_path):
  helper = tmp_path / "helper"
  helper.write_bytes(b"synthetic helper, never execute")
  identities = {}
  def identity(pid):
    value = {"platform": "darwin", "boot_id": "fixture-mac-boot", "pid": pid, "ppid": 1,
      "pgid": pid, "uid": os.geteuid(), "namespace": None, "start_time": "1789516800.000001"}
    identities[pid] = value
    return deepcopy(value)
  worker, parent = identity(201), identity(301)
  worker["ppid"] = current_parent = parent["pid"]
  identities[201]["ppid"] = current_parent
  def runner(argv, *, cwd, env):
    if argv[1] == "inspect":
      return json.dumps(identities.get(int(argv[2]), {"status": "absent"}))
    assert argv[1] == "list"
    return json.dumps(list(identities.values()))
  backend = MacProcesses(helper, tmp_path / "records", helper_digest=hashlib.sha256(helper.read_bytes()).hexdigest(), runner=runner, platform="darwin")
  backend.register(worker)
  backend.bind_control(worker, helper_identity=parent, control_path=backend.record_root / "control.sock", nonce="a" * 64)
  return backend, identities, worker, parent


def terminal(backend, worker, generation=2):
  control = backend._control(worker)
  from agentcfg.storage import Tree
  from agentcfg.deployment import json_bytes
  with Tree(backend.record_root) as tree:
    tree.write_state("control.sock.receipt.json", json_bytes({"schema_version": 1, "worker": worker,
      "nonce": control["nonce"], "state": "terminated", "exit_code": 143, "grant_generation": generation}))


def test_macos_never_falls_back_to_linux_proc(tmp_path):
  with pytest.raises(DependencyError):
    MacProcesses(tmp_path / "helper", tmp_path / "records", helper_digest="a" * 64, platform="linux")


def test_libproc_start_time_and_missing_terminal_receipt_are_independent(tmp_path):
  backend, current, worker, _ = fixture(tmp_path)
  current[201]["ppid"] = 999
  assert backend.observe(worker) == "alive"
  current[201]["start_time"] = "1789516801.000001"
  assert backend.observe(worker) == "unknown"
  current.pop(201)
  assert backend.observe(worker) == "dead"
  assert backend.termination_status(worker) == "unknown"


def test_stop_requires_live_original_helper_nonce_and_revoked_generation(tmp_path):
  backend, current, worker, parent = fixture(tmp_path)
  calls = []
  def stop(control, generation):
    calls.append((control["worker"], generation))
    current.pop(201)
    terminal(backend, worker, generation)
  backend.stop_client = stop
  with pytest.raises(Conflict):
    backend.stop(worker, grant_generation=1)
  assert calls == []
  backend.stop(worker, grant_generation=2)
  assert calls == [(worker, 2)]
  assert backend.termination_status(worker) == "terminated"


def test_lost_helper_cannot_be_replaced_by_bare_pid_signal(tmp_path):
  backend, current, worker, parent = fixture(tmp_path)
  calls = []
  backend.stop_client = lambda *args: calls.append(args)
  current.pop(parent["pid"])
  with pytest.raises(Conflict):
    backend.stop(worker, grant_generation=2)
  assert calls == []
  assert backend.termination_status(worker) == "active"


def test_parent_loss_style_bare_pid_signal_is_refused_by_contract(tmp_path):
  """父丢失场景在darwin只能等平台契约设计；直接向身份/裸PID发信号必须显式拒绝。"""
  backend, _, worker, _ = fixture(tmp_path)
  with pytest.raises(Conflict):
    backend.send_signal(worker, 9)
  with pytest.raises(Conflict):
    backend.send_signal({"pid": 12345}, 9)


def test_changed_helper_binary_is_rejected_before_query(tmp_path):
  backend, _, worker, _ = fixture(tmp_path)
  backend.helper.write_bytes(b"modified helper")
  assert backend.observe(worker) == "unknown"
  with pytest.raises(DependencyError):
    backend.identity(worker["pid"])


def test_force_still_requires_owned_helper_nonce_and_revoked_generation(tmp_path):
  backend, current, worker, parent = fixture(tmp_path)
  calls = []
  def stop(control, generation, *, force=False):
    calls.append((control["nonce"], generation, force)); current.pop(201); terminal(backend, worker, generation)
  backend.stop_client = stop
  backend.stop(worker, grant_generation=2, force=True)
  assert calls == [("a" * 64, 2, True)] and backend.termination_status(worker) == "terminated"
