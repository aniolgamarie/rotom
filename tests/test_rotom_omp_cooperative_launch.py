"""完整内部候选链路；真实临时fd/锁与ledger，观察器和子进程为合成替身。"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import importlib
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import deployment, resource_coordination as core, resource_owners as owners, run_owners, runtime
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree, instance_lock
from test_omp_runtime_foundation import runtime_workspace, clear_omp_identity_environment, isolate_runtime_discovery
from test_rotom_resource_owners import MANAGER, owner_path, metadata
from test_rotom_resource_scopes import scopes


@pytest.fixture
def case(tmp_path, monkeypatch):
  module = importlib.import_module("agentcfg.omp_lifecycle")
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  seed = tmp_path / "seed"
  seed.mkdir(mode=0o700)
  ws, lock = runtime_workspace(seed)
  paths = ws.resolved.data["machine"]["paths"]
  paths.update(instances_root=str(tmp_path / "instances"), state_root=str(tmp_path / "states"), cache_root=str(tmp_path / "cache"))
  ws.agent = "omp"
  ws.instance = tmp_path / "instances/omp" / ws.profile
  ws.state_root = tmp_path / "states/omp" / ws.profile
  ws.cache = tmp_path / "cache/omp" / ws.profile
  domain = core.initialize_domain(tmp_path / "states/lifecycle")
  scope = scopes().enroll_scope(domain, ws)
  package = core.enroll_runtime(domain, ws.cache, lock.identity)
  candidate = RenderCandidate("d" * 64, ws.adapter.render(ws.resolved.data))
  deployment.apply(ws.instance, ws.state_root, candidate, ws.binding, runtime.record(ws, lock))
  ws.backend.root(ws, lock.identity).mkdir(mode=0o700, parents=True)
  cwd = tmp_path / "work"
  cwd.mkdir(mode=0o700)
  trace, control = [], {"complete": True}
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  class Observer:
    def __init__(self, manager):
      assert manager == MANAGER
    def __enter__(self):
      trace.append("observer-enter")
      return self
    def observe(self, run_id):
      trace.append("observe")
      if control.get("observe_error"):
        raise OSError("synthetic-private-observer")
      return run_owners.ReleaseObservation(run_id, deepcopy(MANAGER), True, True) if control["complete"] else None
    def __exit__(self, *args):
      trace.append("observer-exit")
  monkeypatch.setattr(module, "DescendantScope", Observer)
  return SimpleNamespace(module=module, ws=ws, lock=lock, domain=domain, package=package,
    scope=scope, cwd=cwd, trace=trace, control=control)


def install(case, monkeypatch):
  monkeypatch.setattr(case.ws.adapter, "run_lifecycle_guard", lambda selected: case.module.cooperative_run(selected, case.lock.identity))
  monkeypatch.setattr(case.ws.backend, "runtime_guard", lambda *a: pytest.fail("不可回退旧包guard"))


def package_path(case):
  return case.ws.cache / "leases" / (case.lock.identity + ".lock")


def busy(path):
  fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
  try:
    with pytest.raises(BlockingIOError):
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  finally:
    os.close(fd)


@pytest.mark.parametrize("complete,phase", [(True, "released"), (False, "unknown")])
def test_runtime_full_chain_holds_three_sh_through_release_or_unknown(case, monkeypatch, fake_subprocess, complete, phase):
  case.control["complete"] = complete
  install(case, monkeypatch)
  original_reserve = case.module.reserve_omp_launch
  original_attach, original_dispatch = owners.attach_owner, owners.dispatch_owner
  original_finish, original_unknown = owners.finish_owner, owners.mark_owner_unknown
  tokens = []
  def reserve(*args):
    case.trace.append("reserve")
    token = original_reserve(*args)
    tokens.append(token)
    return token
  def attach(domain, run_id, **kwargs):
    assert kwargs["expected_reservation"] is tokens[0]
    assert kwargs["metadata"]["start_cwd"]["path"] == str(case.cwd)
    case.trace.append("attach")
    return original_attach(domain, run_id, **kwargs)
  def dispatch(domain, run_id, **kwargs):
    assert kwargs["expected_reservation"] is tokens[0]
    case.trace.append("dispatch")
    return original_dispatch(domain, run_id, **kwargs)
  def finishing(original, domain, run_id, **kwargs):
    for path in (case.ws.instance / ".agentcfg-omp.lock", case.ws.state_root / "instance.lock", package_path(case)):
      busy(path)
    assert run_id == tokens[0].run_id
    case.trace.append("record-exit")
    return original(domain, run_id, **kwargs)
  monkeypatch.setattr(case.module, "reserve_omp_launch", reserve)
  monkeypatch.setattr(owners, "attach_owner", attach)
  monkeypatch.setattr(owners, "dispatch_owner", dispatch)
  monkeypatch.setattr(owners, "finish_owner", lambda *a, **k: finishing(original_finish, *a, **k))
  monkeypatch.setattr(owners, "mark_owner_unknown", lambda *a, **k: finishing(original_unknown, *a, **k))
  fake_subprocess.queue(returncode=37)
  assert runtime.run(case.ws, cwd=case.cwd) == 37
  assert case.trace == ["reserve", "observer-enter", "attach", "dispatch", "observe", "record-exit", "observer-exit"]
  token = tokens[0]
  assert case.domain.snapshot()["reservations"][token.run_id]["phase"] == phase
  record = run_owners.Registry(case.ws.state_root / "run-owners", case.ws.binding).snapshot()[token.run_id]
  assert run_owners.record_state(record) == ("idle_confirmed" if complete else "unknown")
  assert len(fake_subprocess.calls) == 1 and len(fake_subprocess.calls[0]["pass_fds"]) == 3


@pytest.mark.parametrize("resource", ["instance", "package"])
def test_busy_physical_lock_only_cancels_definitely_unowned_reservation(case, monkeypatch, fake_subprocess, resource):
  install(case, monkeypatch)
  path = case.ws.instance / ".agentcfg-omp.lock" if resource == "instance" else package_path(case)
  fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      runtime.run(case.ws, cwd=case.cwd)
  finally:
    os.close(fd)
  entries = case.domain.snapshot()["reservations"]
  assert len(entries) == 1 and next(iter(entries.values()))["phase"] == "cancelled"
  assert not (case.ws.state_root / "run-owners").exists() and fake_subprocess.calls == []


@pytest.mark.parametrize("phase", ["owner_attached", "dispatched"])
def test_committed_attach_or_dispatch_response_loss_never_cancels_or_finishes(case, monkeypatch, fake_subprocess, phase):
  install(case, monkeypatch)
  original = Tree.replace
  fired = []
  def lost(tree, name, data, *args, **kwargs):
    result = original(tree, name, data, *args, **kwargs)
    if name == "coordination.json" and any(row["phase"] == phase for row in json.loads(data)["reservations"].values()) and not fired:
      fired.append(True)
      raise OSError("synthetic-private-response-lost")
    return result
  monkeypatch.setattr(Tree, "replace", lost)
  with pytest.raises(Conflict):
    runtime.run(case.ws, cwd=case.cwd)
  assert fired and fake_subprocess.calls == [] and "observe" not in case.trace
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == phase and owner_path(case.ws, entry["run_id"]).exists()


@pytest.mark.parametrize("fault", ["finish", "unknown", "observer"])
def test_exit_observation_or_recording_failure_never_overwrites_native_exit(case, monkeypatch, fake_subprocess, capsys, fault):
  install(case, monkeypatch)
  if fault == "observer":
    case.control["observe_error"] = True
  else:
    case.control["complete"] = fault == "finish"
    target = "release_pending" if fault == "finish" else "unknown"
    original = Tree.replace
    writes = []
    def fail(tree, name, data, *args, **kwargs):
      result = original(tree, name, data, *args, **kwargs)
      if name == "coordination.json" and any(row["phase"] == target for row in json.loads(data)["reservations"].values()):
        writes.append(True)
        raise OSError("synthetic-private-exit-error")
      return result
    monkeypatch.setattr(Tree, "replace", fail)
  fake_subprocess.queue(returncode=29)
  assert runtime.run(case.ws, cwd=case.cwd) == 29
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == {"finish": "release_pending", "unknown": "unknown", "observer": "dispatched"}[fault]
  assert "synthetic-private" not in capsys.readouterr().err
  if fault != "observer":
    assert len(writes) == 1


@contextmanager
def manual_owner(case, lease, **change):
  with Tree(case.ws.state_root) as state, instance_lock(state, shared=True) as state_fd:
    with lease.package_guard(case.ws, case.lock.identity) as package_fd:
      supplied = metadata(case.ws)
      supplied["deployed_identity"]["runtime"] = case.lock.identity
      args = dict(metadata=supplied, lifecycle_fd=lease.physical_fd, state_fd=state_fd, package_fd=package_fd)
      if change.pop("closed_state", False):
        closed = os.dup(state_fd)
        os.close(closed)
        args["state_fd"] = closed
      before_owner = change.pop("before_owner", None)
      if before_owner:
        before_owner()
      args.update(change)
      with lease.owner_guard(case.ws, **args) as run_id:
        yield run_id


@pytest.mark.parametrize("wrong", ["physical", "package", "state", "closed-state", "replaced-state"])
def test_wrong_or_replaced_lease_fd_never_attempts_owner(case, wrong):
  with case.module.cooperative_run(case.ws, case.lock.identity) as lease:
    if wrong == "replaced-state":
      # 保留旧 fd，但换掉命名 state lock；不能拿旧身份关联 owner。
      with Tree(case.ws.state_root) as state, instance_lock(state, shared=True) as state_fd:
        path = case.ws.state_root / "instance.lock"
        path.rename(path.with_name("retired.lock"))
        path.write_bytes(b"")
        path.chmod(0o600)
        with lease.package_guard(case.ws, case.lock.identity) as package_fd, pytest.raises(Conflict):
          with lease.owner_guard(case.ws, metadata=metadata(case.ws), lifecycle_fd=lease.physical_fd,
              state_fd=state_fd, package_fd=package_fd):
            pytest.fail("替换锁不得关联owner")
    else:
      changes = ({"lifecycle_fd": -1} if wrong == "physical" else {"package_fd": -1} if wrong == "package"
        else {"closed_state": True} if wrong == "closed-state" else {"state_fd": -1})
      with pytest.raises(Conflict), manual_owner(case, lease, **changes):
        pass
  assert not (case.ws.state_root / "run-owners").exists()
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "cancelled"


def test_package_and_owner_closures_are_single_use_and_expire(case):
  with case.module.cooperative_run(case.ws, case.lock.identity) as lease:
    with manual_owner(case, lease):
      pass
    with pytest.raises(Conflict):
      with lease.package_guard(case.ws, case.lock.identity):
        pass
  with pytest.raises(Conflict):
    with lease.package_guard(case.ws, case.lock.identity):
      pass
  with pytest.raises(Conflict):
    with lease.owner_guard(case.ws, metadata={}, lifecycle_fd=lease.physical_fd, state_fd=-1, package_fd=-1):
      pass


@pytest.mark.parametrize("fault", ["identity", "workspace", "claim"])
def test_changed_package_scope_or_missing_claim_is_not_adopted(case, fault):
  if fault == "claim":
    (case.ws.cache / "runtime-claims" / (case.lock.identity + ".json")).unlink()
    with pytest.raises(Conflict):
      with case.module.cooperative_run(case.ws, case.lock.identity):
        pass
    assert case.domain.snapshot()["reservations"] == {}
    return
  with case.module.cooperative_run(case.ws, case.lock.identity) as lease:
    selected = SimpleNamespace(**vars(case.ws)) if fault == "workspace" else case.ws
    identity = "e" * 64 if fault == "identity" else case.lock.identity
    with pytest.raises(Conflict):
      with lease.package_guard(selected, identity):
        pass


def test_workspace_change_during_reserve_does_not_open_physical_resources(case, monkeypatch):
  original = case.module.reserve_omp_launch
  def changed(*args):
    token = original(*args)
    case.ws.cache = case.ws.cache.with_name("changed-cache")
    return token
  monkeypatch.setattr(case.module, "reserve_omp_launch", changed)
  monkeypatch.setattr(case.module, "_shared_file", lambda *a: pytest.fail("预留后目标变化不得打开物理资源"))
  with pytest.raises(Conflict):
    with case.module.cooperative_run(case.ws, case.lock.identity):
      pass
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == "reserved"


def test_cancel_failure_does_not_replace_lock_conflict_or_retry(case, monkeypatch, capsys):
  calls = []
  def fail(*args):
    calls.append(True)
    raise OSError("synthetic-private-cancel-error")
  monkeypatch.setattr(case.module, "cancel_omp_launch", fail)
  fd = os.open(case.ws.instance / ".agentcfg-omp.lock", os.O_RDWR | os.O_NOFOLLOW)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      with case.module.cooperative_run(case.ws, case.lock.identity):
        pass
  finally:
    os.close(fd)
  assert calls == [True] and "synthetic-private" not in capsys.readouterr().err
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "reserved"


def test_owner_error_does_not_replace_child_exception(case, monkeypatch):
  install(case, monkeypatch)
  import subprocess
  def child(*args, **kwargs):
    raise ValueError("synthetic-child-error")
  def observer_error(self, run_id):
    raise OSError("synthetic-private-observer-error")
  monkeypatch.setattr(subprocess, "run", child)
  monkeypatch.setattr(case.module.DescendantScope, "observe", observer_error)
  with pytest.raises(ValueError, match="synthetic-child-error"):
    runtime.run(case.ws, cwd=case.cwd)
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "dispatched"


@pytest.mark.parametrize("which", ["instance", "package"])
def test_replaced_lock_after_sh_before_owner_does_not_attach(case, which):
  path = case.ws.instance / ".agentcfg-omp.lock" if which == "instance" else package_path(case)
  def replace_lock():
    raw = path.read_bytes()
    path.rename(path.with_name(path.name + ".retired"))
    path.write_bytes(raw)
    path.chmod(0o600)
  with case.module.cooperative_run(case.ws, case.lock.identity) as lease:
    with pytest.raises(Conflict), manual_owner(case, lease, before_owner=replace_lock):
      pass
  assert not (case.ws.state_root / "run-owners").exists()
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "cancelled"


def test_owner_closure_cannot_be_reentered_while_package_is_still_live(case):
  with case.module.cooperative_run(case.ws, case.lock.identity) as lease:
    with Tree(case.ws.state_root) as state, instance_lock(state, shared=True) as state_fd:
      with lease.package_guard(case.ws, case.lock.identity) as package_fd:
        supplied = metadata(case.ws)
        supplied["deployed_identity"]["runtime"] = case.lock.identity
        kwargs = dict(metadata=supplied, lifecycle_fd=lease.physical_fd, state_fd=state_fd, package_fd=package_fd)
        with lease.owner_guard(case.ws, **kwargs) as run_id:
          pass
        before = owner_path(case.ws, run_id).read_bytes()
        with pytest.raises(Conflict):
          with lease.owner_guard(case.ws, **kwargs):
            pass
        assert owner_path(case.ws, run_id).read_bytes() == before and case.trace.count("observe") == 1


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "permissions"])
def test_existing_instance_lock_must_be_single_link_private_nofollow(case, kind):
  path = case.ws.instance / ".agentcfg-omp.lock"
  if kind == "permissions":
    path.chmod(0o644)
  elif kind == "hardlink":
    os.link(path, path.with_name("extra-link"))
  else:
    target = path.with_name("retired-real-lock")
    path.rename(target)
    path.symlink_to(target)
  with pytest.raises(Conflict):
    with case.module.cooperative_run(case.ws, case.lock.identity):
      pass
  assert not (case.ws.state_root / "run-owners").exists()


def test_acquired_fds_are_nofollow_cloexec_nonblocking_and_sh(case):
  with case.module.cooperative_run(case.ws, case.lock.identity) as lease:
    assert os.get_inheritable(lease.physical_fd) is False and os.get_blocking(lease.physical_fd) is False
    busy(case.ws.instance / ".agentcfg-omp.lock")
    with lease.package_guard(case.ws, case.lock.identity) as fd:
      assert os.get_inheritable(fd) is False and os.get_blocking(fd) is False
      busy(package_path(case))


def test_one_owner_finishes_without_mutating_other_owner_sharing_package(case, monkeypatch, fake_subprocess):
  from agentcfg.storage import ensure_private
  other = SimpleNamespace(**vars(case.ws))
  other.profile = "omp-other"
  other.binding = {**case.ws.binding, "profile": other.profile}
  other.instance = case.ws.instance.parent / other.profile
  other.state_root = case.ws.state_root.parent / other.profile
  other.resolved = SimpleNamespace(data=deepcopy(case.ws.resolved.data))
  other.resolved.data["profile"]["id"] = other.profile
  scopes().enroll_scope(case.domain, other)
  ensure_private(other.state_root)
  with case.module.cooperative_run(other, case.lock.identity) as lease:
    with Tree(other.state_root) as state, instance_lock(state, shared=True) as state_fd:
      with lease.package_guard(other, case.lock.identity) as package_fd:
        supplied = metadata(other)
        supplied["deployed_identity"]["runtime"] = case.lock.identity
        with lease.owner_guard(other, metadata=supplied, lifecycle_fd=lease.physical_fd,
            state_fd=state_fd, package_fd=package_fd) as other_run:
          entry_before = deepcopy(case.domain.snapshot()["reservations"][other_run])
          owner_before = owner_path(other, other_run).read_bytes()
          install(case, monkeypatch)
          fake_subprocess.queue(returncode=17)
          assert runtime.run(case.ws, cwd=case.cwd) == 17
          assert case.domain.snapshot()["reservations"][other_run] == entry_before
          assert owner_path(other, other_run).read_bytes() == owner_before


def test_legacy_instance_is_not_automatically_enrolled(tmp_path):
  module = importlib.import_module("agentcfg.omp_lifecycle")
  ws, lock = runtime_workspace(tmp_path)
  ws.agent = "omp"
  domain = core.initialize_domain(tmp_path / "state-root/lifecycle")
  core.enroll_runtime(domain, ws.cache, lock.identity)
  before = {str(path.relative_to(ws.instance)): path.read_bytes() for path in ws.instance.rglob("*") if path.is_file()}
  with pytest.raises(Conflict):
    with module.cooperative_run(ws, lock.identity):
      pass
  assert domain.snapshot()["reservations"] == {}
  assert {str(path.relative_to(ws.instance)): path.read_bytes() for path in ws.instance.rglob("*") if path.is_file()} == before


def test_reserve_commits_and_releases_coordination_before_opening_physical_sh(case, monkeypatch):
  original = case.module._shared_file
  checked = []
  def shared(root, name):
    if name == ".agentcfg-omp.lock":
      with Tree(case.domain.root) as coordination:
        fcntl.flock(coordination.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        saved = json.loads((case.domain.root / "coordination.json").read_bytes())
        assert len(saved["reservations"]) == 1
        assert next(iter(saved["reservations"].values()))["phase"] == "reserved"
        fcntl.flock(coordination.fd, fcntl.LOCK_UN)
      checked.append(True)
    return original(root, name)
  monkeypatch.setattr(case.module, "_shared_file", shared)
  with case.module.cooperative_run(case.ws, case.lock.identity):
    assert checked == [True]


def test_lost_reservation_response_never_cancels_without_returned_token(case, monkeypatch):
  original = case.module.reserve_omp_launch
  def lost(*args):
    original(*args)
    raise Conflict("synthetic-reservation-response-lost")
  monkeypatch.setattr(case.module, "reserve_omp_launch", lost)
  monkeypatch.setattr(case.module, "cancel_omp_launch", lambda *a: pytest.fail("没有token不能取消"))
  monkeypatch.setattr(case.module, "_shared_file", lambda *a: pytest.fail("没有token不能打开物理租约"))
  with pytest.raises(Conflict):
    with case.module.cooperative_run(case.ws, case.lock.identity):
      pass
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == "reserved"


@pytest.mark.parametrize("phase", ["attach", "dispatch"])
@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_committed_owner_interrupt_closes_observer_once_and_preserves_original(case, monkeypatch, fake_subprocess, phase, exception_type):
  install(case, monkeypatch)
  original = getattr(owners, phase + "_owner")
  interruption = exception_type("synthetic-interruption")
  def interrupted(*args, **kwargs):
    original(*args, **kwargs)
    raise interruption
  monkeypatch.setattr(owners, phase + "_owner", interrupted)
  with pytest.raises(exception_type) as caught:
    runtime.run(case.ws, cwd=case.cwd)
  assert caught.value is interruption
  assert case.trace.count("observer-exit") == 1 and "observe" not in case.trace
  assert fake_subprocess.calls == []
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == ("owner_attached" if phase == "attach" else "dispatched")
  assert owner_path(case.ws, entry["run_id"]).exists()


@pytest.mark.parametrize("point", ["initially-empty", "get-subreaper"])
@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_real_observer_partial_enter_interrupt_releases_scope_without_prctl(case, monkeypatch, fake_subprocess, point, exception_type):
  from agentcfg import descendants
  install(case, monkeypatch)
  manager = {"pid": os.getpid(), "birth_id": "synthetic-current-manager"}
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: manager.copy())
  monkeypatch.setattr(case.module, "DescendantScope", descendants.DescendantScope)
  monkeypatch.setattr(descendants.threading, "active_count", lambda: 1)
  monkeypatch.setattr(descendants.signal, "getsignal", lambda *a: descendants.signal.SIG_DFL)
  monkeypatch.setattr(descendants, "_prctl", lambda *a: pytest.fail("本测试不得调用prctl"))
  interruption = exception_type("synthetic-enter-interruption")
  def interrupted():
    raise interruption
  monkeypatch.setattr(descendants, "_initially_empty", interrupted if point == "initially-empty" else lambda: True)
  if point == "get-subreaper":
    monkeypatch.setattr(descendants, "_get_subreaper", interrupted)
  assert descendants._SCOPE.acquire(blocking=False)
  descendants._SCOPE.release()
  free_after = False
  try:
    with pytest.raises(exception_type) as caught:
      runtime.run(case.ws, cwd=case.cwd)
    assert caught.value is interruption
    free_after = descendants._SCOPE.acquire(blocking=False)
    assert free_after, "部分enter后必须释放本次_SCOPE"
  finally:
    # RED 也清理本测试自己拿到却泄漏的锁，不能污染后续用例。
    descendants._SCOPE.release()
  assert fake_subprocess.calls == [] and not (case.ws.state_root / "run-owners").exists()
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == "cancelled"


@pytest.mark.parametrize("stage", ["observe", "finish", "unknown", "observer-exit"])
@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("body", ["return", "exception", "keyboard", "system-exit"])
def test_cleanup_control_exception_cannot_replace_body_result_or_exception(case, monkeypatch, fake_subprocess, capsys, stage, exception_type, body):
  install(case, monkeypatch)
  interruption = exception_type("synthetic-private-cleanup-interruption")
  calls = []
  def interrupted(*args, **kwargs):
    calls.append(True)
    raise interruption
  if stage == "observe":
    monkeypatch.setattr(case.module.DescendantScope, "observe", interrupted)
  elif stage == "observer-exit":
    monkeypatch.setattr(case.module.DescendantScope, "__exit__", interrupted)
  else:
    case.control["complete"] = stage == "finish"
    original = owners.finish_owner if stage == "finish" else owners.mark_owner_unknown
    def committed_then_interrupted(*args, **kwargs):
      original(*args, **kwargs)
      interrupted()
    monkeypatch.setattr(owners, "finish_owner" if stage == "finish" else "mark_owner_unknown", committed_then_interrupted)
  body_error = {"exception": ValueError, "keyboard": KeyboardInterrupt,
    "system-exit": SystemExit}.get(body, ValueError)("synthetic-body-error")
  if body == "return":
    fake_subprocess.queue(returncode=39)
    assert runtime.run(case.ws, cwd=case.cwd) == 39
  else:
    import subprocess
    def child(*args, **kwargs):
      raise body_error
    monkeypatch.setattr(subprocess, "run", child)
    with pytest.raises(type(body_error)) as caught:
      runtime.run(case.ws, cwd=case.cwd)
    assert caught.value is body_error
  assert calls == [True]
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == {"observe": "dispatched", "finish": "released", "unknown": "unknown", "observer-exit": "released"}[stage]
  assert "synthetic-private" not in capsys.readouterr().err


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_cancel_cleanup_control_exception_preserves_original_lock_refusal(case, monkeypatch, exception_type):
  original = case.module.cancel_omp_launch
  calls = []
  def interrupted(*args):
    original(*args)
    calls.append(True)
    raise exception_type("synthetic-private-cancel-control")
  monkeypatch.setattr(case.module, "cancel_omp_launch", interrupted)
  fd = os.open(case.ws.instance / ".agentcfg-omp.lock", os.O_RDWR | os.O_NOFOLLOW)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      with case.module.cooperative_run(case.ws, case.lock.identity):
        pass
  finally:
    os.close(fd)
  assert calls == [True]
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "cancelled"


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_private_fd_close_control_exception_cannot_override_body_return(case, monkeypatch, fake_subprocess, exception_type):
  import subprocess
  install(case, monkeypatch)
  original_child, original_close = subprocess.run, os.close
  target, calls = [], []
  def child(*args, **kwargs):
    target.append(kwargs["pass_fds"][0])
    return original_child(*args, **kwargs)
  def close(fd):
    result = original_close(fd)
    if target and fd == target[0] and not calls:
      calls.append(True)
      raise exception_type("synthetic-private-close-control")
    return result
  monkeypatch.setattr(subprocess, "run", child)
  monkeypatch.setattr(case.module.os, "close", close)
  fake_subprocess.queue(returncode=43)
  assert runtime.run(case.ws, cwd=case.cwd) == 43 and calls == [True]


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_cleanup_warning_and_stack_close_swallow_only_their_own_control_errors(case, monkeypatch, exception_type):
  class BrokenStream:
    def write(self, *args):
      raise exception_type("synthetic-private-warning-control")
  class BrokenStack:
    def close(self):
      raise exception_type("synthetic-private-stack-control")
  with monkeypatch.context() as patch:
    patch.setattr(case.module.sys, "stderr", BrokenStream())
    case.module._warn()
    case.module._close(BrokenStack())
