"""普通 cache-only sync 消费已有新资源归属；不采用旧包、不启动宿主。"""
import fcntl
import os

import pytest

from agentcfg.omp_dependencies import OmpBackend
from agentcfg.resource_coordination import enroll_runtime, initialize_domain
from agentcfg.storage import Conflict
from test_omp_resource_coordination import workspace
from test_omp_dependencies_foundation import locked


@pytest.fixture
def prepared(tmp_path):
  ws = workspace(tmp_path / "cache", tmp_path / "state")
  domain = initialize_domain(tmp_path / "state/lifecycle")
  anchor = enroll_runtime(domain, ws.cache, "synthetic-runtime")
  return ws, domain, anchor


def test_exact_new_runtime_allows_cache_only_ex_and_preserves_domain(prepared):
  ws, domain, anchor = prepared
  before = domain.snapshot()
  with OmpBackend().runtime_guard(ws, "synthetic-runtime", exclusive=True) as fd:
    assert os.fstat(fd).st_ino == anchor["resource_key"]["inode"]
    other = os.open(ws.cache / "leases/synthetic-runtime.lock", os.O_RDONLY)
    try:
      with pytest.raises(BlockingIOError):
        fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)
    finally:
      os.close(other)
  assert domain.snapshot() == before
  assert not ws.state_root.exists() and not ws.instance.exists()


@pytest.mark.parametrize("phase", ["reserved", "unknown"])
def test_reference_from_another_empty_registry_still_blocks(prepared, phase):
  ws, domain, anchor = prepared
  domain.reserve(run_id="a" * 32, op_id="b" * 32, resources=[anchor["resource_id"]],
    owner_ref={"state_root": str(ws.state_root.parent / "other"), "binding": {
      "machine": "synthetic", "local": str(ws.instance.parent / "local.toml"), "profile": "other"}})
  if phase == "unknown":
    domain.mark_unknown("a" * 32)
  before = domain.snapshot()
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, "synthetic-runtime", exclusive=True):
    pytest.fail("active/unknown resource must remain blocked")
  assert domain.snapshot() == before and not ws.state_root.exists()


def test_accepted_intent_blocks_even_with_no_runs(prepared):
  ws, domain, anchor = prepared
  domain.accept_intent(batch_id="a" * 32, generation=1, operation="setup",
    expected_revision=domain.snapshot()["revision"], resources=[anchor["resource_id"]], selected_runs=[])
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, "synthetic-runtime", exclusive=True):
    pytest.fail("intent is not ordinary sync permission")


@pytest.mark.parametrize("damage", ["missing-lease", "empty-lease", "claim", "symlink", "cross-domain", "scope-claim"])
def test_incomplete_or_foreign_provenance_never_creates_replacement(prepared, damage):
  ws, domain, _ = prepared
  lease = ws.cache / "leases/synthetic-runtime.lock"
  if damage == "missing-lease":
    lease.unlink()
  elif damage == "empty-lease":
    lease.write_bytes(b"")
  elif damage == "claim":
    (ws.cache / "runtime-claims/synthetic-runtime.json").write_bytes(b"{}")
  elif damage == "symlink":
    target = lease.with_suffix(".moved")
    lease.rename(target)
    lease.symlink_to(target)
  elif damage == "scope-claim":
    import hashlib
    path = ws.instance.parent / ".rotom-scope-claims"
    path.mkdir(mode=0o700)
    (path / (hashlib.sha256(ws.instance.name.encode()).hexdigest() + ".json")).write_bytes(b"{}")
  else:
    ws.resolved.data["machine"]["paths"]["state_root"] = str(domain.root.parent.with_name("foreign"))
  before = domain.snapshot()
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, "synthetic-runtime", exclusive=True):
    pytest.fail("unverified provenance must fail closed")
  assert domain.snapshot() == before and not ws.state_root.exists()
  if damage == "missing-lease":
    assert not lease.exists()
  if damage == "cross-domain":
    assert not domain.root.parent.with_name("foreign").exists()


def test_shared_guard_still_cannot_bypass_launch_registration(prepared):
  ws, _, _ = prepared
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, "synthetic-runtime"):
    pytest.fail("sync admission does not grant a new run")


def test_sync_holds_exact_ex_at_first_recovery_side_effect(locked, monkeypatch):
  original, _, _, _ = locked
  ws = workspace(original.cache, original.state_root.parent / "coordination-state")
  ws.repository = original.repository
  backend = OmpBackend()
  lock = backend.read_lock(ws.repository)
  identity = backend.runtime_identity(ws, lock)
  domain = initialize_domain(ws.state_root.parents[1] / "lifecycle")
  enroll_runtime(domain, ws.cache, identity)
  calls = []
  def recover(selected, selected_lock, selected_identity):
    assert selected is ws and selected_lock == lock and selected_identity == identity
    fd = os.open(ws.cache / "leases" / (identity + ".lock"), os.O_RDONLY)
    try:
      with pytest.raises(BlockingIOError):
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    finally:
      os.close(fd)
    calls.append("recover")
  monkeypatch.setattr(backend, "_recover_activation", recover)
  monkeypatch.setattr(backend, "status", lambda *a: "installed")
  before = domain.snapshot()
  assert backend.sync(ws, lock) == {"status": "installed", "identity": identity}
  assert calls == ["recover"] and domain.snapshot() == before
  assert not ws.state_root.exists() and not ws.instance.exists()


def test_coordination_lock_is_released_before_sync_body(prepared):
  ws, domain, _ = prepared
  with OmpBackend().runtime_guard(ws, "synthetic-runtime", exclusive=True):
    # EX 短事务成功，证明同步期间没有继续持协调 SH/EX；包 EX 仍由外层持有。
    with domain._transaction(write=True):
      pass


def test_operation_error_is_not_rewritten_as_admission_failure(prepared):
  from agentcfg.process import DependencyError
  ws, _, _ = prepared
  failure = DependencyError("synthetic-operation-failure")
  with pytest.raises(DependencyError) as error:
    with OmpBackend().runtime_guard(ws, "synthetic-runtime", exclusive=True):
      raise failure
  assert error.value is failure
