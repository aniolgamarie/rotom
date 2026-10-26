"""共享包协调迁移门禁；只操作合成包、临时文件和本进程租约。"""

import fcntl
import os
from types import SimpleNamespace

import pytest

from agentcfg.omp_dependencies import OmpBackend
from agentcfg.resource_coordination import Domain, enroll_runtime, initialize_domain
from agentcfg.storage import Conflict
from test_omp_dependencies_foundation import locked


def workspace(cache, state):
  return SimpleNamespace(cache=cache, state_root=state / "omp/profile",
    instance=state.parent / (state.name + "-instance"),
    resolved=SimpleNamespace(data={"machine": {"paths": {"state_root": str(state)}}, "profile": {}}))


@pytest.mark.parametrize("exclusive", [True, False])
@pytest.mark.parametrize("same_domain", [True, False])
def test_anchored_package_sync_requires_same_domain_and_shared_launch_stays_closed(tmp_path, exclusive, same_domain):
  owner = workspace(tmp_path / "cache", tmp_path / "state-a")
  other = workspace(owner.cache, tmp_path / ("state-a" if same_domain else "state-b"))
  domain = initialize_domain(owner.state_root.parents[1] / "lifecycle")
  enroll_runtime(domain, owner.cache, "synthetic-runtime")
  before = domain.snapshot()
  if exclusive and same_domain:
    with OmpBackend().runtime_guard(other, "synthetic-runtime", exclusive=True):
      pass
  else:
    with pytest.raises(Conflict), OmpBackend().runtime_guard(other, "synthetic-runtime", exclusive=exclusive):
      pytest.fail("anchored runtime must not bypass cooperative admission")
  assert domain.snapshot() == before
  assert not other.state_root.exists() and not other.instance.exists()
  if not same_domain:
    assert not other.state_root.parents[1].exists()


def test_unknown_reference_blocks_other_owner_after_physical_release(tmp_path):
  first = workspace(tmp_path / "cache", tmp_path / "state-a")
  second = workspace(first.cache, tmp_path / "state-a")
  domain = initialize_domain(tmp_path / "state-a/lifecycle")
  anchor = enroll_runtime(domain, first.cache, "synthetic-runtime")
  run = "a" * 32
  domain.reserve(run_id=run, op_id="b" * 32, resources=[anchor["resource_id"]], owner_ref={
    "state_root": str(first.state_root), "binding": {
      "machine": "synthetic-machine", "local": str(tmp_path / "local.toml"), "profile": "first"}})
  domain.mark_unknown(run)
  path = first.cache / "leases/synthetic-runtime.lock"
  fd = os.open(path, os.O_RDWR)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      domain.check_runtime(second.cache, "synthetic-runtime", lease_fd=fd, idle=True)
  finally:
    os.close(fd)
  with pytest.raises(Conflict):
    with OmpBackend().runtime_guard(second, "synthetic-runtime", exclusive=True):
      pytest.fail("empty owner registry cannot clear another owner's unknown")
  assert domain.snapshot()["reservations"][run]["phase"] == "unknown"


@pytest.mark.parametrize("raw", [b"{", b" ", b"{\"kind\":\"runtime-anchor\"}"])
def test_nonempty_broken_anchor_never_falls_back_to_legacy(tmp_path, raw):
  target = workspace(tmp_path / "cache", tmp_path / "state")
  lease = target.cache / "leases/synthetic-runtime.lock"
  lease.parent.mkdir(parents=True, mode=0o700)
  lease.write_bytes(raw)
  with pytest.raises(Conflict):
    with OmpBackend().runtime_guard(target, "synthetic-runtime", exclusive=True):
      pytest.fail("corrupt nonempty anchor must block")
  assert lease.read_bytes() == raw
  assert not target.state_root.parents[1].exists()


def test_sync_fails_before_assembly_and_preserves_cache_only_contract(locked, monkeypatch):
  original, _, _, _ = locked
  target = workspace(original.cache, original.state_root.parent / "coordination-state")
  target.repository = original.repository
  backend = OmpBackend()
  lock = backend.read_lock(target.repository)
  runtime_identity = backend.runtime_identity(target, lock)
  domain = initialize_domain(target.state_root.parents[1] / "lifecycle")
  anchor = enroll_runtime(domain, target.cache, runtime_identity)
  domain.reserve(run_id="a" * 32, op_id="b" * 32, resources=[anchor["resource_id"]], owner_ref={
    "state_root": str(target.state_root), "binding": {"machine": "synthetic", "local": str(target.instance.parent / "local.toml"), "profile": "profile"}})
  domain.mark_unknown("a" * 32)
  monkeypatch.setattr(backend, "_recover_activation", lambda *args: pytest.fail("must stop before activation recovery"))
  before = domain.snapshot()
  with pytest.raises(Conflict):
    backend.sync(target, lock)
  assert domain.snapshot() == before
  assert not target.state_root.exists() and not target.instance.exists()
  assert not backend.root(target, runtime_identity).exists()


def test_empty_legacy_guard_does_not_initialize_domain(tmp_path):
  target = workspace(tmp_path / "cache", tmp_path / "state")
  with OmpBackend().runtime_guard(target, "synthetic-runtime", exclusive=True):
    pass
  assert (target.cache / "leases/synthetic-runtime.lock").read_bytes() == b""
  assert not target.state_root.parents[1].exists() and not target.instance.exists()
  with pytest.raises(Conflict):
    Domain(target.state_root.parents[1] / "lifecycle").snapshot()
