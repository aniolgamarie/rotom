"""Pi/OMP 精确停止：真实临时部署与账本，只替换进程身份和原 pidfd。"""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import json
import os
import time

import pytest

from agentcfg import deployment, dsh_stop, dsh_stop_client as client, dsh_stop_completion as completion
from agentcfg import dsh_stop_control as control, dsh_stop_scope, lifecycle, maintenance
from agentcfg import run_owners, run_stop_fence, runtime, spawned_host
from agentcfg.storage import Conflict, Tree, instance_lock
from test_pi_reboot_dependencies import fake_npm, recipe_repository
from test_pi_reboot_pipeline import pipeline, prepare
from test_rotom_omp_cooperative_launch import case, manual_owner, install
from test_rotom_cooperative_runtime import cooperative
from test_rotom_resume_dispatch import fake_popen
from test_rotom_resource_owners import MANAGER


@pytest.fixture
def pi_workspace(pipeline):
  ws, backend, lock, _, _ = pipeline
  prepare(ws, backend, lock)
  return SimpleNamespace(ws=ws, lock=lock, domain=None)


@pytest.fixture
def omp_workspace(case):
  return case


@pytest.fixture(params=["pi", "omp"])
def tool(request, monkeypatch):
  source = request.getfixturevalue(request.param + "_workspace")
  ws = source.ws
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  handles, identities, signals, bundles = {}, {}, [], []
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  monkeypatch.setattr(run_owners, "observed_process_identity", lambda pid: deepcopy(MANAGER if pid == MANAGER["pid"] else identities.get(pid)))
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", lambda self: deepcopy(handles[id(self)]))
  def send(self):
    assert self in [row.host for row in bundles]
    signals.append(self)
  monkeypatch.setattr(spawned_host.SpawnedHost, "send_sigterm_once", send)
  with ExitStack() as all_leases:
    def add():
      owner_stack = ExitStack()
      all_leases.callback(owner_stack.close)
      if request.param == "omp":
        lease = all_leases.enter_context(source.module.cooperative_run(ws, source.lock.identity))
        run = owner_stack.enter_context(manual_owner(source, lease))
        instance_fd = lease.physical_fd
        # owner context retains the original state fd; factory uses a second SH on the same named lock.
        state = all_leases.enter_context(Tree(ws.state_root))
        state_fd = all_leases.enter_context(instance_lock(state, shared=True, create=False))
        observer = lease.observer_factory(run)
      else:
        instance_fd = all_leases.enter_context(lifecycle.guard(ws, shared=True, create=False))
        state = all_leases.enter_context(Tree(ws.state_root))
        state_fd = all_leases.enter_context(instance_lock(state, shared=True, create=False))
        current = deployment.read_state(state)["current"]
        metadata = runtime.run_metadata(ws, current, runtime.decode(current["launch"], ws.local_path.parent, ()))
        run = registry.register_v2(MANAGER, metadata)
        observer = registry
      host = object.__new__(spawned_host.SpawnedHost)
      identity = {"pid": 3133800 + len(bundles), "birth_id": "synthetic-child-" + str(len(bundles))}
      identities[identity["pid"]] = identity
      handles[id(host)] = {"identity": identity, "manager_identity": deepcopy(MANAGER),
        "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}
      observer.bind_current_host(run, host)
      def finish(complete=True):
        if request.param == "omp":
          source.control["complete"] = complete
          owner_stack.close()
        elif complete:
          registry.finish_current(run, MANAGER, run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True))
        else:
          registry.mark_unknown(run, MANAGER)
      bundle = SimpleNamespace(run=run, host=host, instance_fd=instance_fd, state_fd=state_fd, finish=finish)
      bundles.append(bundle)
      return bundle
    value = SimpleNamespace(ws=ws, registry=registry, source=source, signals=signals, add=add,
      bundles=bundles, handles=handles, identities=identities, release_leases=all_leases.close)
    value.first = add()
    yield value


def service(tool, bundle=None):
  bundle = bundle or tool.first
  return control.default_factory(tool.ws, tool.registry.snapshot()[bundle.run],
    instance_fd=bundle.instance_fd, state_fd=bundle.state_fd)(run_id=bundle.run, host=bundle.host)


def accept(tool, selected=None):
  from agentcfg.stop_review import review_stop_plan
  selected = selected or [tool.first.run]
  observed, records, layout = dsh_stop.capture_stop(tool.ws, selected_runs=selected)
  plan = observed["plan"]
  assert plan["readiness"] == "ready"
  batch = "b" * 32
  review = review_stop_plan(plan, scope=plan["scope"], operation="stop_only", selected_runs=selected,
    plan_id=plan["plan_id"], batch_id=batch, approve=lambda _: True)
  dsh_stop_scope.save_reviewed_snapshot(tool.ws, instance_fd=tool.first.instance_fd,
    state_fd=tool.first.state_fd, expected_records=records, expected_layout=layout,
    plan=plan, batch_id=batch, review=review)
  return batch, plan


def post(tool, batch, plan, bundle=None):
  bundle = bundle or tool.first
  row = tool.registry.snapshot()[bundle.run]
  request = {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop",
    "request_id": ("a" if bundle is tool.first else "c") * 32, "batch_id": batch,
    "plan_id": plan["plan_id"], "run_id": bundle.run, "manager_identity": deepcopy(MANAGER),
    "host_identity": deepcopy(row["host_identity"]["identity"]), "deadline_ns": time.monotonic_ns()+1000000000}
  client.publish_request(tool.ws, request, expected_record=row)
  return request


def test_exact_stop_service_to_confirmed_close_preserves_owner_contract(tool):
  before = tool.registry.snapshot()
  domain_before = tool.source.domain.snapshot() if tool.source.domain is not None else None
  current = service(tool)
  assert tool.registry.snapshot() == before
  if domain_before is not None: assert tool.source.domain.snapshot() == domain_before
  batch, plan = accept(tool)
  assert plan["coordinator"]["kind"] == tool.ws.agent + "-instance-registry"
  assert plan["scope"]["agent"] == tool.ws.agent
  if tool.ws.agent == "omp":
    keys = {item["key"]["kind"]: item["key"] for item in plan["resources"]}
    assert keys["instance"]["inode"] == (tool.ws.instance / ".agentcfg-omp.lock").stat().st_ino
    package = tool.ws.cache / "runtimes" / tool.source.lock.identity
    assert keys["runtime"]["inode"] == package.stat().st_ino
    # 精确停止的本地包目录不是 Domain 的共享包租约文件，也不证明全局覆盖。
    assert all(item["key"] != keys["runtime"] for item in domain_before["resources"].values()
      if item["key"]["kind"] == "runtime")
  assert tool.registry.snapshot()[tool.first.run]["protocol"]["control"] is None
  post(tool, batch, plan)
  assert current()["dispatch"] == "signal_sent" and current() is None
  assert tool.signals == [tool.first.host]
  assert client.status_stop(tool.ws, batch_id=batch)["protected"] is True
  tool.first.finish()
  closed = completion.close_stop(tool.ws, batch_id=batch, plan_id=plan["plan_id"], reason="stopped")
  assert closed["reason"] == "stopped"
  status = client.status_stop(tool.ws, batch_id=batch)
  assert status["status"] == "stopped" and status["protected"] is False
  assert status["resource_coverage"] == "unknown" and status["continue_status"] == "not_sent"
  assert run_stop_fence.read_snapshot(tool.registry, batch)["plan"] == plan
  if domain_before is not None:
    entry = tool.source.domain.snapshot()["reservations"][tool.first.run]
    assert entry["phase"] == "released" and entry["release_receipt"]
  current.close()


def test_missing_channel_blocks_stop_and_setup_is_still_blocked(tool):
  for operation in ("stop_only", "setup"):
    plan = dsh_stop.preview_stop(tool.ws, selected_runs=[tool.first.run], operation=operation)["plan"]
    assert plan["readiness"] == "blocked" and "stop-capability-unavailable" in plan["blockers"]
    if operation == "setup": assert "resource-coverage-unknown" in plan["blockers"]
  assert tool.signals == [] and run_stop_fence.read(tool.registry) is None


@pytest.mark.parametrize("damage", ["wrong-run", "json-host"])
def test_factory_requires_original_run_and_live_host(tool, damage):
  original = tool.registry.snapshot()
  callback = control.factory_for(tool.ws, instance_fd=tool.first.instance_fd, state_fd=tool.first.state_fd)
  with pytest.raises(Conflict):
    callback(run_id="f" * 32 if damage == "wrong-run" else tool.first.run,
      host=deepcopy(tool.handles[id(tool.first.host)]) if damage == "json-host" else tool.first.host)
  assert tool.registry.snapshot() == original
  assert not (tool.ws.state_root / "stop-inboxes").exists() and tool.signals == []


@pytest.mark.parametrize("damage", ["run", "manager", "host", "binding", "nonce"])
def test_changed_endpoint_never_controls_original_child(tool, damage):
  current = service(tool)
  batch, plan = accept(tool)
  post(tool, batch, plan)
  path = current._inbox.root / "endpoint.json"
  endpoint = json.loads(path.read_bytes())
  if damage == "run": endpoint["run_id"] = "f" * 32
  elif damage == "manager": endpoint["manager_identity"]["birth_id"] = "synthetic-other"
  elif damage == "host": endpoint["host_identity"]["birth_id"] = "synthetic-other"
  elif damage == "binding": endpoint["binding_digest"] = "f" * 64
  else: endpoint["nonce"] = "f" * 32
  path.write_bytes(run_owners._encode(endpoint))
  with pytest.raises(Conflict): current()
  with pytest.raises(Conflict): current()
  assert tool.signals == [] and run_stop_fence.read(tool.registry)["batch_id"] == batch


@pytest.mark.parametrize("stage", ["before-preview", "after-request"])
def test_managed_projection_drift_never_dispatches(tool, stage):
  current = service(tool)
  if stage == "after-request":
    batch, plan = accept(tool)
    post(tool, batch, plan)
  with Tree(tool.ws.state_root) as state:
    deployed = deployment.read_state(state)["current"]
  target = next(item for item in deployed["items"].values() if item["baseline"].get("present") is True)
  (tool.ws.instance / target["path"]).write_bytes(b"synthetic-changed-managed-file\n")
  with pytest.raises(Conflict):
    if stage == "before-preview": dsh_stop.preview_stop(tool.ws, selected_runs=[tool.first.run])
    else: current()
  assert tool.signals == []
  assert (run_stop_fence.read(tool.registry) is not None) is (stage == "after-request")


def test_unselected_run_is_unchanged_and_cannot_receive_this_request(tool):
  other = tool.add()
  first_service, other_service = service(tool), service(tool, other)
  original = (tool.registry.root / (other.run + ".json")).read_bytes()
  entry = deepcopy(tool.source.domain.snapshot()["reservations"][other.run]) if tool.source.domain is not None else None
  batch, plan = accept(tool)
  assert all(other.run in row["reference_runs"] for row in plan["resources"])
  with pytest.raises(Conflict): post(tool, batch, plan, other)
  post(tool, batch, plan)
  assert first_service()["dispatch"] == "signal_sent"
  assert other_service() is None and tool.signals == [tool.first.host]
  tool.first.finish()
  completion.close_stop(tool.ws, batch_id=batch, plan_id=plan["plan_id"], reason="stopped")
  assert (tool.registry.root / (other.run + ".json")).read_bytes() == original
  if entry is not None: assert tool.source.domain.snapshot()["reservations"][other.run] == entry
  first_service.close(); other_service.close()


def test_partial_selected_exit_keeps_fence_and_other_run_protection(tool):
  other = tool.add()
  first_service, other_service = service(tool), service(tool, other)
  batch, plan = accept(tool, sorted([tool.first.run, other.run]))
  post(tool, batch, plan)
  assert first_service()["dispatch"] == "signal_sent"
  tool.first.finish()
  post(tool, batch, plan, other)
  for reason in ("stopped", "cancelled"):
    with pytest.raises(Conflict): completion.close_stop(tool.ws, batch_id=batch, plan_id=plan["plan_id"], reason=reason)
  status = client.status_stop(tool.ws, batch_id=batch)
  assert status["protected"] is True and status["status"] == "pending"
  assert {row["lifecycle_state"] for row in status["targets"]} == {"idle_confirmed", "active"}
  assert tool.signals == [tool.first.host] and run_stop_fence.read(tool.registry) is not None
  first_service.close(); other_service.close()


def test_control_availability_never_enables_setup_or_other_coordinator(tool):
  current = service(tool)
  plan = dsh_stop.preview_stop(tool.ws, selected_runs=[tool.first.run], operation="setup")["plan"]
  assert plan["control_capability"] == "supported" and plan["readiness"] == "blocked"
  assert "resource-coverage-unknown" in plan["blockers"]
  malformed = deepcopy(plan)
  malformed["coordinator"]["kind"] = "dsh-instance-registry"
  with pytest.raises(Conflict): maintenance.encode_stop_plan(malformed)
  current.close()


@pytest.fixture
def stop_clock(monkeypatch):
  from agentcfg.control_deadline import ControlDeadline
  state = SimpleNamespace(now=0.0, exited=False, action=lambda: None)
  monkeypatch.setattr(client.time, "monotonic_ns", lambda: int(state.now * 1000000000))
  monkeypatch.setattr(client, "ControlDeadline", lambda seconds: ControlDeadline(seconds, clock=lambda: state.now))
  def sleep(seconds):
    state.action()
    state.now += max(seconds, 0.05)
  monkeypatch.setattr(client.time, "sleep", sleep)
  class Exit:
    def __init__(self, identity): assert identity == MANAGER
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def exited(self): return state.exited
  monkeypatch.setattr(client, "ManagerExit", Exit)
  return state


def test_execute_accepts_same_workflow_batch_once(tool, stop_clock):
  current = service(tool)
  plan = dsh_stop.preview_stop(tool.ws, selected_runs=[tool.first.run])["plan"]
  fixed = "d" * 32
  result = client.execute_stop(tool.ws, expected_plan=plan, approve=lambda _: True, wait_seconds=1, batch_id=fixed)
  assert result["batch_id"] == fixed and result["protected"] is True
  assert run_stop_fence.read_snapshot(tool.registry, fixed)["plan"] == plan
  before = {path: path.read_bytes() for path in tool.ws.state_root.rglob("*") if path.is_file()}
  with pytest.raises(Conflict):
    client.execute_stop(tool.ws, expected_plan=plan, approve=lambda _: pytest.fail("不能重复审阅"), wait_seconds=1, batch_id=fixed)
  assert before == {path: path.read_bytes() for path in tool.ws.state_root.rglob("*") if path.is_file()}
  assert tool.signals == []
  current.close()


@pytest.mark.parametrize("batch", ["", "invalid", "D" * 32, True, 1])
def test_invalid_workflow_batch_fails_before_observation_or_approval(tool, monkeypatch, batch):
  monkeypatch.setattr(dsh_stop, "capture_stop", lambda *a, **kw: pytest.fail("非法batch不能读取现场"))
  with pytest.raises(Conflict):
    client.execute_stop(tool.ws, expected_plan={}, approve=lambda _: pytest.fail("非法batch不能审阅"), batch_id=batch)
  assert run_stop_fence.read(tool.registry) is None and tool.signals == []


def test_execute_full_chain_closes_same_workflow_batch(tool, stop_clock):
  current = service(tool)
  plan = dsh_stop.preview_stop(tool.ws, selected_runs=[tool.first.run])["plan"]
  calls = []
  def act():
    if calls: return
    calls.append(current())
    tool.first.finish()
    stop_clock.exited = True
  stop_clock.action = act
  result = client.execute_stop(tool.ws, expected_plan=plan, approve=lambda _: True, wait_seconds=1, batch_id="e" * 32)
  assert result["batch_id"] == "e" * 32 and result["status"] == "stopped" and result["protected"] is False
  assert len(calls) == 1 and calls[0]["dispatch"] == "signal_sent" and tool.signals == [tool.first.host]
  assert run_stop_fence.read(tool.registry) is None
  assert run_stop_fence.read_snapshot(tool.registry, "e" * 32)["plan"] == plan
  current.close()


def test_scope_discovery_uses_actual_tool_workspace_and_selected_run(tool, monkeypatch):
  from agentcfg import local, workspace
  current = service(tool)
  calls = []
  monkeypatch.setattr(local, "available_profiles", lambda: [(tool.ws.profile, tool.ws.agent)])
  def load(path, profiles):
    assert str(path) == tool.ws.binding["local"] and profiles == [tool.ws.profile]
    calls.append(True)
    return [tool.ws]
  monkeypatch.setattr(workspace, "load_instance_workspaces", load)
  result = dsh_stop.preview_for_scope(tool.ws.local_path, selected_runs=[tool.first.run])
  assert result["plan"]["scope"] == {**tool.ws.binding, "agent": tool.ws.agent}
  assert result["plan"]["readiness"] == "ready" and calls == [True]
  current.close()


def test_idle_owners_remain_fenced_until_explicit_close(tool):
  current = service(tool)
  batch, plan = accept(tool)
  post(tool, batch, plan)
  current()
  tool.first.finish()
  current.close()
  tool.release_leases()
  guard = lifecycle.omp_scope_write_guard if tool.ws.agent == "omp" else lifecycle.inactive_guard
  assert all(row["lifecycle_state"] == "idle_confirmed" for row in tool.registry.snapshot().values())
  with pytest.raises(Conflict):
    with guard(tool.ws): pytest.fail("idle owner不能越过未close的stop fence")
  completion.close_stop(tool.ws, batch_id=batch, plan_id=plan["plan_id"], reason="stopped")
  with guard(tool.ws) as fd: os.fstat(fd)


@pytest.mark.parametrize("tool", ["omp"], indirect=True)
def test_cooperative_resume_receives_only_original_live_observer(tool, monkeypatch):
  from contextlib import contextmanager
  original = tool.source.module.cooperative_run
  calls, observers = [], []
  @contextmanager
  def admission(selected):
    with original(selected, tool.source.lock.identity) as lease:
      def factory(run):
        calls.append(run)
        observer = lease.observer_factory(run)
        observers.append(observer)
        return observer
      yield lifecycle.CooperativeRunLease(lease.physical_fd, lease.package_guard, lease.owner_guard, factory)
  monkeypatch.setattr(tool.ws.adapter, "run_lifecycle_guard", admission)
  def callback(ws, spec, env, state_fd, contract, *, run_id, lifecycle_fd, package_fd, owner_registry):
    assert ws is tool.ws and calls == [run_id] and owner_registry is observers[0]
    assert owner_registry.snapshot()[run_id]["agent"] == "omp"
    for fd in (state_fd, lifecycle_fd, package_fd): os.fstat(fd)
    return 27
  assert runtime.run(tool.ws, cwd=tool.source.cwd, resume_operation=callback) == 27
  assert len(calls) == 1
  with pytest.raises(Conflict): observers[0].snapshot()


def test_historical_cooperative_resume_keeps_narrow_callback(cooperative):
  ws, cwd, _, _, _, alive = cooperative
  def callback(selected, spec, env, state_fd, contract, *, run_id, lifecycle_fd, package_fd):
    assert selected is ws and run_id == "a" * 32
    alive()
    return 19
  assert runtime.run(ws, cwd=cwd, resume_operation=callback) == 19


_REAL_CHILD = runtime._run_dsh_child


def test_runtime_installs_actual_sidecar_factory_on_original_child(tool, fake_popen, monkeypatch):
  from agentcfg import descendants, managed_wait
  if tool.ws.agent == "omp": install(tool.source, monkeypatch)
  class Scope:
    def __init__(self, manager): assert manager == MANAGER
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def observe(self, run): return run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True)
  monkeypatch.setattr(descendants, "DescendantScope", Scope)
  monkeypatch.setattr(runtime, "_run_dsh_child", _REAL_CHILD)
  captured, services, closed = [], [], []
  def take(child, manager):
    assert child.returncode is None and child.wait_calls == 0 and manager == MANAGER
    host = object.__new__(spawned_host.SpawnedHost)
    identity = {"pid": 3133999, "birth_id": "synthetic-runtime-child"}
    tool.identities[identity["pid"]] = identity
    tool.handles[id(host)] = {"identity": identity, "manager_identity": deepcopy(manager),
      "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}
    captured.append(host)
    return host
  monkeypatch.setattr(spawned_host, "capture_spawned_host", take)
  monkeypatch.setattr(spawned_host.SpawnedHost, "close", lambda self: closed.append(self))
  def wait(child, *, service, unavailable):
    services.append(service)
    run = service.describe()["run_id"]
    row = tool.registry.snapshot()[run]
    assert row["protocol"]["control"] is None and row["host_identity"] == tool.handles[id(captured[0])]
    assert service.belongs_to(run, captured[0]) and control.available(tool.ws, row)
    plan = dsh_stop.preview_stop(tool.ws, selected_runs=[run])["plan"]
    assert plan["readiness"] == "ready" and plan["coordinator"]["kind"] == tool.ws.agent + "-instance-registry"
    return child.wait()
  monkeypatch.setattr(managed_wait, "wait_with_service", wait)
  fake_popen.queue(returncode=33)
  cwd = tool.source.cwd if tool.ws.agent == "omp" else tool.ws.local_path.parent
  assert runtime.run(tool.ws, cwd=cwd) == 33
  assert len(fake_popen.calls) == len(captured) == len(services) == 1
  assert closed == captured and fake_popen.children[0].wait_calls == 1
  assert services[0].belongs_to(services[0]._run, captured[0]) is False
  assert tool.signals == []
