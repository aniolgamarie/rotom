"""候选普通 OMP setup/apply/run 连通；合成包和子进程，不启动官方宿主。"""
from copy import deepcopy
import fcntl
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import commands, deployment, omp_dependencies, omp_lifecycle, resource_coordination as core
from agentcfg import resource_scopes, run_owners, runtime
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict, Tree
from test_omp_pipeline import full_workspace
from test_omp_runtime_foundation import clear_omp_identity_environment, isolate_runtime_discovery
from test_rotom_resource_owners import MANAGER


@pytest.fixture
def fresh(tmp_path, monkeypatch):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  ws = full_workspace(tmp_path)
  content = b"synthetic standalone asset, never executed\n"
  assets = {name: {"url": "https://example.invalid/" + name, "sha256": omp_dependencies.sha(content)}
    for name in omp_dependencies.ASSETS}
  monkeypatch.setattr(omp_dependencies, "ASSETS", assets)
  path = ws.repository / "locks/omp/manifest.json"
  body = json.loads(path.read_bytes())
  body.pop("identity")
  body["assets"] = assets
  path.write_bytes(deployment.json_bytes({"identity": omp_dependencies.sha(deployment.json_bytes(body)), **body}))
  lock = ws.backend.read_lock(ws.repository)
  with Tree(ws.cache / "downloads", create=True) as cache:
    cache.write_new(omp_dependencies.sha(content), content)
  monkeypatch.setattr(commands, "workspace", lambda _: ws)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  control = {"complete": True}
  class Observer:
    def __init__(self, manager):
      assert manager == MANAGER
    def __enter__(self):
      return self
    def __exit__(self, *args):
      pass
    def observe(self, run_id):
      return run_owners.ReleaseObservation(run_id, deepcopy(MANAGER), True, True) if control["complete"] else None
  monkeypatch.setattr(omp_lifecycle, "DescendantScope", Observer)
  cwd = tmp_path / "work"
  cwd.mkdir(mode=0o700)
  return SimpleNamespace(ws=ws, lock=lock, identity=runtime.runtime_identity(ws, lock), cwd=cwd,
    domain=core.Domain(ws.state_root.parent.parent / "lifecycle"), control=control)


def busy(path):
  fd = os.open(path, os.O_RDONLY)
  try:
    with pytest.raises(BlockingIOError):
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  finally:
    os.close(fd)


def test_fresh_setup_preserves_preview_then_default_run_registers_before_spawn(fresh, monkeypatch, fake_subprocess):
  ws = fresh.ws
  candidate = ws.candidate(fresh.lock.identity)
  preview = commands.current_plan(ws, fresh.lock, candidate).public()
  recovery = omp_dependencies.OmpBackend._recover_activation
  calls = []
  def first_effect(backend, selected, lock, identity):
    assert selected is ws and identity == fresh.identity
    assert core.runtime_claim_exists(ws.cache, identity)
    assert not ws.instance.exists() and not ws.state_root.exists()
    busy(ws.cache / "leases" / (identity + ".lock"))
    calls.append("sync")
    return recovery(backend, selected, lock, identity)
  monkeypatch.setattr(omp_dependencies.OmpBackend, "_recover_activation", first_effect)
  assert commands.cmd_setup(SimpleNamespace(command="setup")) == 0
  assert calls == ["sync"] and resource_scopes.scope_claim_exists(ws.instance)
  state = fresh.domain.snapshot()
  assert len(state["resources"]) == 3 and not state["reservations"]
  assert preview["changes"] > 0
  monkeypatch.setattr(omp_dependencies.OmpBackend, "_recover_activation", recovery)
  before = (ws.state_root / "deployment.json").read_bytes()
  assert commands.cmd_setup(SimpleNamespace(command="setup")) == 0
  assert (ws.state_root / "deployment.json").read_bytes() == before
  import subprocess
  original = subprocess.run
  def child(*args, **kwargs):
    entry, = fresh.domain.snapshot()["reservations"].values()
    assert entry["phase"] == "dispatched" and len(entry["resources"]) == 3
    assert len(kwargs["pass_fds"]) == 3 and len(set(kwargs["pass_fds"])) == 3
    for path in (ws.instance / ".agentcfg-omp.lock", ws.state_root / "instance.lock",
        ws.cache / "leases" / (fresh.identity + ".lock")):
      busy(path)
    return original(*args, **kwargs)
  monkeypatch.setattr(subprocess, "run", child)
  fake_subprocess.queue(returncode=37)
  assert runtime.run(ws, cwd=fresh.cwd) == 37
  entry, = fresh.domain.snapshot()["reservations"].values()
  assert entry["phase"] == "released"
  assert fake_subprocess.calls[0]["argv"][-1] == "--no-title"


def test_unknown_exit_preserves_result_and_blocks_setup_before_sync(fresh, monkeypatch, fake_subprocess):
  assert commands.cmd_setup(SimpleNamespace(command="setup")) == 0
  fresh.control["complete"] = False
  fake_subprocess.queue(returncode=27)
  assert runtime.run(fresh.ws, cwd=fresh.cwd) == 27
  entry, = fresh.domain.snapshot()["reservations"].values()
  assert entry["phase"] == "unknown"
  before = (fresh.ws.state_root / "deployment.json").read_bytes()
  monkeypatch.setattr(commands, "sync_backend", lambda *a: pytest.fail("unknown must stop before sync"))
  with pytest.raises(Conflict):
    commands.cmd_setup(SimpleNamespace(command="setup"))
  assert (fresh.ws.state_root / "deployment.json").read_bytes() == before
  assert fresh.domain.snapshot()["reservations"][entry["run_id"]]["phase"] == "unknown"


def test_sync_failure_retains_runtime_only_registration_and_explicit_retry(fresh, monkeypatch):
  backend = omp_dependencies.OmpBackend
  original = backend._recover_activation
  calls = []
  failure = DependencyError("synthetic-download-failure")
  def fail(*args):
    calls.append(True)
    raise failure
  monkeypatch.setattr(backend, "_recover_activation", fail)
  with pytest.raises(DependencyError) as caught:
    commands.cmd_setup(SimpleNamespace(command="setup"))
  assert caught.value is failure and calls == [True]
  ws = fresh.ws
  assert core.runtime_claim_exists(ws.cache, fresh.identity)
  assert not ws.instance.exists() and not ws.state_root.exists()
  assert len(fresh.domain.snapshot()["resources"]) == 1
  monkeypatch.setattr(backend, "_recover_activation", original)
  assert commands.cmd_setup(SimpleNamespace(command="setup")) == 0
  assert len(fresh.domain.snapshot()["resources"]) == 3


def test_partial_deployment_keeps_journal_and_scope_until_explicit_apply(fresh, monkeypatch, fake_subprocess):
  original_prepare, original_recover = commands.prepare_launch, deployment.recover
  failure = OSError("synthetic-write-failure")
  def fail_prepare(*args):
    raise failure
  def keep_pending(target, state, *, prepare=None):
    if state.read("pending.json"):
      raise Conflict("synthetic-recovery-conflict")
    return original_recover(target, state, prepare=prepare)
  monkeypatch.setattr(commands, "prepare_launch", fail_prepare)
  monkeypatch.setattr(deployment, "recover", keep_pending)
  with pytest.raises(Conflict):
    commands.cmd_setup(SimpleNamespace(command="setup"))
  ws = fresh.ws
  assert resource_scopes.scope_claim_exists(ws.instance)
  assert (ws.state_root / "pending.json").exists()
  before = fresh.domain.snapshot()
  with pytest.raises(Conflict):
    runtime.run(ws, cwd=fresh.cwd)
  assert fake_subprocess.calls == [] and fresh.domain.snapshot() == before
  monkeypatch.setattr(commands, "prepare_launch", original_prepare)
  monkeypatch.setattr(deployment, "recover", original_recover)
  assert commands.cmd_apply(SimpleNamespace(command="apply")) == 0
  assert not (ws.state_root / "pending.json").exists()
  assert fresh.domain.snapshot()["resources"] == before["resources"]
  fake_subprocess.queue(returncode=0)
  assert runtime.run(ws, cwd=fresh.cwd) == 0


def test_standalone_sync_keeps_legacy_and_later_setup_does_not_adopt(fresh, fake_subprocess):
  ws = fresh.ws
  assert commands.cmd_sync(SimpleNamespace(command="sync")) == 0
  assert not ws.instance.exists() and not ws.state_root.exists()
  assert not core.runtime_claim_exists(ws.cache, fresh.identity)
  assert commands.cmd_setup(SimpleNamespace(command="setup")) == 0
  assert not resource_scopes.scope_claim_exists(ws.instance) and not fresh.domain.root.exists()
  fake_subprocess.queue(returncode=0)
  assert runtime.run(ws, cwd=fresh.cwd) == 0


def test_unsafe_preview_stops_before_any_resource_enrollment(fresh, monkeypatch):
  class Preview:
    conflicts, drift = ["synthetic"], []
    def public(self):
      return {"changes": 1, "drift": 0, "conflicts": 1}
  monkeypatch.setattr(commands, "current_plan", lambda *a: Preview())
  monkeypatch.setattr(commands, "sync_backend", lambda *a: pytest.fail("preview refused"))
  assert commands.cmd_setup(SimpleNamespace(command="setup")) == 4
  assert not fresh.domain.root.exists() and not fresh.ws.instance.exists()
  assert not core.runtime_claim_exists(fresh.ws.cache, fresh.identity)


def test_concurrent_mixed_legacy_instance_and_runtime_claim_never_launches(fresh, fake_subprocess):
  from agentcfg.omp_identity import lifecycle_guard
  ws = fresh.ws
  # 模拟明确记录的跨资源部分现场；不是可自动采用的已登记 scope。
  with lifecycle_guard(ws, create=True):
    pass
  core.enroll_runtime(core.initialize_domain(fresh.domain.root), ws.cache, fresh.identity)
  before = fresh.domain.snapshot()
  with pytest.raises(Conflict):
    runtime.run(ws, cwd=fresh.cwd)
  assert fake_subprocess.calls == [] and fresh.domain.snapshot() == before
  assert not resource_scopes.scope_claim_exists(ws.instance)
  assert core.runtime_claim_exists(ws.cache, fresh.identity)
