"""Pi 直接 child 复用原等待与租约；只运行合成 npm/进程，不准入控制或恢复。"""
from contextlib import nullcontext
from copy import deepcopy
import os
from pathlib import Path

import pytest

from agentcfg import lifecycle, run_owners, runtime, spawned_host
from agentcfg.process import DependencyError
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.stop_inbox import StopInbox
from agentcfg.stop_service import StopService
from agentcfg.storage import Conflict
from test_pi_reboot_dependencies import fake_npm, recipe_repository
from test_pi_reboot_pipeline import pipeline, prepare
from test_rotom_host_registration import HOST as BOUND_HOST, handle
from test_rotom_resume_dispatch import fake_popen
from test_rotom_resume_host import HOST, capture, owner
from test_rotom_resume_runtime import assert_exclusive_busy
from test_rotom_run_records import MANAGER as RECORD_MANAGER, RUN_ID, store, v2_record, write_record
from test_rotom_runtime_observation import MANAGER, observation


_REAL_CHILD = runtime._run_dsh_child


@pytest.fixture
def pi(pipeline, observation, fake_popen, capture, monkeypatch):
  workspace, backend, lock, calls, legacy_launches = pipeline
  prepare(workspace, backend, lock)
  monkeypatch.setattr(runtime, "_run_dsh_child", _REAL_CHILD)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  # 本模块隔离原 host 捕获；实际控制工厂由 tool_stop 集成测试覆盖。
  monkeypatch.setattr("agentcfg.dsh_stop_control.default_factory", lambda *args, **kwargs: None)
  return workspace, observation, legacy_launches


@pytest.mark.parametrize("code,complete", [(0, True), (17, False), (-15, False)])
def test_pi_binds_original_child_before_wait_and_preserves_native_contract(pi, fake_popen, capture, tmp_path, code, complete):
  workspace, observation, legacy = pi
  observation["value"] = complete
  seen = []
  def wait():
    record = owner(workspace)
    assert record["agent"] == "pi" and record["backend"] == "managed"
    assert record["host_identity"] == HOST and record["manager_identity"] == MANAGER
    assert record["coordination_domain"] is record["protocol"]["control"] is None
    assert record["session_observation"] is None and record["lifecycle_state"] == "active"
    assert capture["closed"] == 0
    assert len(fake_popen.calls[0]["pass_fds"]) == 2
    for fd in fake_popen.calls[0]["pass_fds"]: os.fstat(fd)
    for path in (workspace.instance, workspace.state_root / "instance.lock"):
      assert_exclusive_busy(path)
    seen.append(record)
  fake_popen.queue(returncode=code, on_wait=wait)
  assert runtime.run(workspace, cwd=tmp_path, arguments=("--thinking", "minimal")) == (code if code >= 0 else 128-code)
  assert len(seen) == len(fake_popen.calls) == 1 and legacy == []
  call = fake_popen.calls[0]
  extension = str(Path(runtime.__file__).resolve().parents[2] / "agents/pi/templates/session-control.mjs")
  assert call["argv"][0] == "node" and call["cwd"] == tmp_path
  assert call["argv"][-4:] == ["--thinking", "minimal", "-e", extension]
  assert call["env"]["PI_CODING_AGENT_DIR"] == str(workspace.instance / "pi-home")
  assert len(call["pass_fds"]) == 2
  assert fake_popen.children[0].wait_calls == 1 and capture["closed"] == 1
  saved = owner(workspace)
  assert saved["host_identity"] == HOST and saved["lifecycle_state"] == ("idle_confirmed" if complete else "unknown")
  assert not (workspace.state_root / "resume-attempts").exists()


@pytest.mark.parametrize("failure", ["capture", "attach"])
def test_pi_optional_capture_failure_keeps_wait_and_native_exit(pi, fake_popen, capture, monkeypatch, tmp_path, failure):
  workspace, _, legacy = pi
  if failure == "capture":
    monkeypatch.setattr(spawned_host, "capture_spawned_host", lambda *args: None)
  else:
    def fail(*args): raise Conflict("synthetic-private-canary")
    monkeypatch.setattr(run_owners.Registry, "bind_current_host", fail)
  fake_popen.queue(returncode=23)
  assert runtime.run(workspace, cwd=tmp_path) == 23
  assert legacy == [] and fake_popen.children[0].wait_calls == 1
  assert owner(workspace)["host_identity"] is None
  assert capture["closed"] == (0 if failure == "capture" else 1)


@pytest.mark.parametrize("kind", [ValueError, OSError, KeyboardInterrupt, SystemExit])
def test_pi_uncertain_wait_never_restarts_or_claims_release(pi, fake_popen, capture, tmp_path, kind):
  workspace, _, legacy = pi
  problem = kind("synthetic-private-canary")
  fake_popen.queue(returncode=0, wait_error=problem)
  expected = Conflict if kind in (ValueError, OSError) else kind
  with pytest.raises(expected) as caught: runtime.run(workspace, cwd=tmp_path)
  if expected is not Conflict: assert caught.value is problem
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1 and legacy == []
  assert capture["closed"] == 1 and owner(workspace)["lifecycle_state"] == "unknown"


def test_pi_spawn_failure_preserves_dependency_error_without_host(pi, fake_popen, capture, tmp_path):
  workspace, _, legacy = pi
  fake_popen.queue(spawn_error=OSError("synthetic-private-canary"))
  with pytest.raises(DependencyError): runtime.run(workspace, cwd=tmp_path)
  assert len(fake_popen.calls) == 1 and fake_popen.children == [] and legacy == []
  assert capture["captured"] == 0 and owner(workspace)["host_identity"] is None


@pytest.mark.parametrize("route", ["ssh", "unregistered", "unsupported-platform"])
def test_pi_ineligible_capture_routes_keep_original_execution(pi, fake_popen, capture, monkeypatch, tmp_path, route):
  workspace, _, legacy = pi
  if route == "ssh":
    original = runtime.run_metadata
    monkeypatch.setattr(runtime, "run_metadata", lambda *args: {**original(*args), "backend": "ssh"})
  elif route == "unregistered":
    monkeypatch.setattr(workspace.adapter, "run_owner_guard", lambda *args, **kwargs: nullcontext())
  else:
    monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
  assert runtime.run(workspace, cwd=tmp_path) == 17
  assert len(legacy) == 1 and fake_popen.calls == [] and capture["captured"] == 0


@pytest.fixture
def pi_record(store):
  record = v2_record(store)
  record["agent"] = "pi"
  record["native_home_ref"]["kind"] = "pi-home"
  return store, record


def test_pi_registry_binds_only_original_current_host(pi_record, handle):
  store, record = pi_record
  write_record(store, record)
  store.registry.bind_current_host(RUN_ID, handle)
  saved = store.registry.snapshot()[RUN_ID]
  assert saved["host_identity"] == BOUND_HOST and saved["protocol"]["control"] is None
  assert saved["session_observation"] is None and saved["coordination_domain"] is None


@pytest.mark.parametrize("damage", ["json", "current-manager", "source", "relationship"])
def test_pi_registry_rejects_untrusted_or_stale_host(pi_record, handle, monkeypatch, damage):
  store, record = pi_record
  path = write_record(store, record)
  before = path.read_bytes()
  selected = handle
  if damage == "json": selected = deepcopy(BOUND_HOST)
  elif damage == "current-manager":
    monkeypatch.setattr(run_owners, "current_process_identity", lambda: {**RECORD_MANAGER, "birth_id": "other"})
  else:
    observed = deepcopy(BOUND_HOST)
    observed[damage] = "unconfirmed"
    monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", lambda self: observed)
  with pytest.raises(Conflict): store.registry.bind_current_host(RUN_ID, selected)
  assert path.read_bytes() == before


def test_pi_registry_can_record_original_service_without_control_dispatch(pi_record, handle, tmp_path):
  store, record = pi_record
  record["host_identity"] = deepcopy(BOUND_HOST)
  record["process_observation"]["host_identity"] = deepcopy(BOUND_HOST)
  write_record(store, record)
  inbox = StopInbox(tmp_path / "inbox", store.binding)
  journal = StopDispatches(tmp_path / "journal", store.binding)
  service = StopService(RUN_ID, handle, inbox=inbox, journal=journal,
    verify=lambda request: pytest.fail("registration must not dispatch control"))
  store.registry.bind_current_control(RUN_ID, handle, service)
  saved = store.registry.snapshot()[RUN_ID]
  assert saved["protocol"]["control"]["endpoint"] == inbox.describe()
  assert saved["session_observation"] is None and not journal.root.exists()


@pytest.mark.parametrize("damage", ["host-json", "service-json", "current-manager"])
def test_pi_control_registration_still_requires_live_objects_and_current_manager(pi_record, handle, tmp_path, monkeypatch, damage):
  store, record = pi_record
  record["host_identity"] = deepcopy(BOUND_HOST)
  record["process_observation"]["host_identity"] = deepcopy(BOUND_HOST)
  path = write_record(store, record)
  inbox = StopInbox(tmp_path / "inbox", store.binding)
  service = StopService(RUN_ID, handle, inbox=inbox, journal=StopDispatches(tmp_path / "journal", store.binding),
    verify=lambda request: pytest.fail("registration must not dispatch control"))
  selected_host, selected_service = handle, service
  if damage == "host-json": selected_host = deepcopy(BOUND_HOST)
  elif damage == "service-json": selected_service = service.describe()
  else:
    monkeypatch.setattr(run_owners, "current_process_identity", lambda: {**RECORD_MANAGER, "birth_id": "other"})
  before = path.read_bytes()
  with pytest.raises(Conflict): store.registry.bind_current_control(RUN_ID, selected_host, selected_service)
  assert path.read_bytes() == before
