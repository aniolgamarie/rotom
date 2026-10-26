"""只用临时锁和协调元数据；不接默认 setup/apply 或第三方宿主。"""
import fcntl
import os
from types import SimpleNamespace

import pytest

from agentcfg import lifecycle, omp_identity, omp_setup as setup, resource_coordination as core
from agentcfg.storage import Conflict
from test_rotom_resource_owners import IDENTITY
from test_rotom_resource_scopes import claim_path, scopes, workspace


@pytest.fixture
def fresh(tmp_path):
  ws = workspace(tmp_path)
  root = tmp_path / "global-state"
  ws.state_root = root / "omp" / ws.profile
  ws.resolved = SimpleNamespace(data={"machine": {"paths": {"state_root": str(root)}}})
  ws.cache = tmp_path / "cache"
  return ws


def domain(ws):
  return core.Domain(ws.state_root.parent.parent / "lifecycle")


def contents(root):
  return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def test_fresh_prepare_only_enrolls_global_runtime(fresh):
  setup.prepare_setup(fresh, IDENTITY)
  state = domain(fresh).snapshot()
  record, = state["resources"].values()
  assert record["runtime_identity"] == IDENTITY and record["status"] == "ready"
  assert core.runtime_claim_exists(fresh.cache, IDENTITY)
  assert not fresh.instance.exists() and not fresh.state_root.exists()
  assert not claim_path(fresh).exists()


def test_second_fresh_profile_reuses_same_domain_runtime_without_changes(fresh):
  setup.prepare_setup(fresh, IDENTITY)
  before = contents(fresh.cache), domain(fresh).snapshot()
  other = SimpleNamespace(**vars(fresh))
  other.profile = "omp-b"
  other.binding = {**fresh.binding, "profile": other.profile}
  other.instance = fresh.instance.parent / other.profile
  other.state_root = fresh.state_root.parent / other.profile
  setup.prepare_setup(other, IDENTITY)
  assert (contents(fresh.cache), domain(fresh).snapshot()) == before
  assert not other.instance.exists() and not other.state_root.exists()


@pytest.mark.parametrize("existing", ["instance", "lease", "runtime"])
def test_legacy_resources_stay_untouched_without_domain_or_claim(fresh, existing):
  if existing == "instance":
    with omp_identity.lifecycle_guard(fresh, create=True):
      pass
  else:
    path = fresh.cache / ("leases/" + IDENTITY + ".lock" if existing == "lease" else "runtimes/" + IDENTITY)
    path.parent.mkdir(parents=True, mode=0o700)
    if existing == "lease":
      path.write_bytes(b"synthetic-old-lease")
      path.chmod(0o600)
    else:
      path.mkdir(mode=0o700)
      (path / "sentinel").write_bytes(b"synthetic-old-package")
  before = contents(fresh.cache.parent)
  setup.prepare_setup(fresh, IDENTITY)
  assert contents(fresh.cache.parent) == before
  assert not domain(fresh).root.exists() and not claim_path(fresh).exists()


def cooperative(ws):
  d = core.initialize_domain(domain(ws).root)
  scopes().enroll_scope(d, ws)
  return d


def test_existing_cooperative_scope_can_enroll_new_runtime(fresh):
  d = cooperative(fresh)
  setup.prepare_setup(fresh, IDENTITY)
  assert core.runtime_claim_exists(fresh.cache, IDENTITY)
  assert len(d.snapshot()["resources"]) == 3 and not fresh.state_root.exists()


def test_cooperative_scope_cannot_downgrade_to_legacy_package(fresh):
  cooperative(fresh)
  old = fresh.cache / "runtimes" / IDENTITY
  old.mkdir(parents=True, mode=0o700)
  before = domain(fresh).snapshot()
  with pytest.raises(Conflict):
    setup.prepare_setup(fresh, IDENTITY)
  assert domain(fresh).snapshot() == before and not core.runtime_claim_exists(fresh.cache, IDENTITY)


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_legacy_instance_cannot_mix_with_cooperative_runtime(fresh, action):
  with omp_identity.lifecycle_guard(fresh, create=True):
    pass
  core.enroll_runtime(core.initialize_domain(domain(fresh).root), fresh.cache, IDENTITY)
  before = contents(fresh.cache.parent)
  with pytest.raises(Conflict):
    if action == "prepare":
      setup.prepare_setup(fresh, IDENTITY)
    else:
      with setup.apply_guard(fresh, IDENTITY):
        pytest.fail("legacy instance is not automatically adopted")
  assert contents(fresh.cache.parent) == before


@pytest.mark.parametrize("damage", ["claim", "anchor", "domain", "record", "cross-domain"])
def test_claimed_runtime_must_have_complete_same_domain_provenance(fresh, damage):
  d = core.initialize_domain(domain(fresh).root)
  core.enroll_runtime(d, fresh.cache, IDENTITY)
  if damage == "claim":
    (fresh.cache / "runtime-claims" / (IDENTITY + ".json")).write_bytes(b"{synthetic-broken")
  elif damage == "anchor":
    (fresh.cache / "leases" / (IDENTITY + ".lock")).write_bytes(b"{synthetic-broken")
  elif damage == "domain":
    (d.root / "coordination.json").unlink()
  elif damage == "record":
    with d._transaction(write=True) as state:
      state["resources"].clear()
  else:
    fresh.resolved.data["machine"]["paths"]["state_root"] = str(fresh.cache.parent / "other-state")
    fresh.state_root = fresh.cache.parent / "other-state/omp" / fresh.profile
    core.initialize_domain(domain(fresh).root)
  before = contents(fresh.cache.parent)
  with pytest.raises(Conflict):
    setup.prepare_setup(fresh, IDENTITY)
  assert contents(fresh.cache.parent) == before and not fresh.instance.exists()


@pytest.mark.parametrize("state", ["active", "unknown", "partial"])
def test_cooperative_scope_preflight_refuses_durable_or_partial_protection(fresh, state):
  cooperative(fresh)
  core.enroll_runtime(domain(fresh), fresh.cache, IDENTITY)
  if state == "partial":
    (fresh.instance / "user-home/.rotom-resource.json").unlink()
  else:
    token = lifecycle.reserve_omp_launch(fresh, IDENTITY)
    if state == "unknown":
      domain(fresh).mark_unknown(token.run_id)
  before = contents(fresh.cache.parent)
  with pytest.raises(Conflict):
    setup.prepare_setup(fresh, IDENTITY)
  assert contents(fresh.cache.parent) == before


def test_apply_releases_package_sh_before_scope_enrollment_then_holds_physical_ex(fresh, monkeypatch):
  setup.prepare_setup(fresh, IDENTITY)
  original = scopes().enroll_scope
  calls = []
  def enroll(d, ws):
    fd = os.open(ws.cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR)
    try:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      calls.append("package-released")
    finally:
      os.close(fd)
    return original(d, ws)
  monkeypatch.setattr(scopes(), "enroll_scope", enroll)
  with setup.apply_guard(fresh, IDENTITY) as fd:
    assert type(fd) is int and os.fstat(fd).st_ino == os.stat(fresh.instance / ".agentcfg-omp.lock").st_ino
    other = os.open(fresh.instance / ".agentcfg-omp.lock", os.O_RDONLY)
    try:
      with pytest.raises(BlockingIOError):
        fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)
    finally:
      os.close(other)
  assert calls == ["package-released"] and claim_path(fresh).exists()
  assert not fresh.state_root.exists()


def test_apply_without_prepare_keeps_legacy_guard(fresh):
  with setup.apply_guard(fresh, IDENTITY) as fd:
    assert os.fstat(fd).st_ino == os.stat(fresh.instance / ".agentcfg-omp.lock").st_ino
  assert not claim_path(fresh).exists() and not domain(fresh).root.exists()
  with setup.apply_guard(fresh, IDENTITY):
    pass


@pytest.mark.parametrize("operation", ["prepare", "apply"])
def test_cooperative_scope_existing_package_rechecks_without_reenrollment(fresh, monkeypatch, operation):
  cooperative(fresh)
  core.enroll_runtime(domain(fresh), fresh.cache, IDENTITY)
  monkeypatch.setattr(scopes(), "enroll_scope", lambda *a: pytest.fail("existing scope must not reenroll"))
  monkeypatch.setattr(core, "enroll_runtime", lambda *a: pytest.fail("existing runtime must not reenroll"))
  if operation == "prepare":
    setup.prepare_setup(fresh, IDENTITY)
  else:
    with setup.apply_guard(fresh, IDENTITY):
      pass


@pytest.mark.parametrize("identity", ["../invalid", "", "invalid/value", "a" * 193, None, True])
def test_invalid_identity_is_fixed_conflict_without_writes(fresh, identity):
  before = contents(fresh.cache.parent)
  with pytest.raises(Conflict) as caught:
    setup.prepare_setup(fresh, identity)
  assert "invalid/value" not in str(caught.value)
  assert contents(fresh.cache.parent) == before


@pytest.mark.parametrize("stage", ["claim", "record"])
def test_runtime_enrollment_response_loss_retains_protection_without_retry(fresh, monkeypatch, stage):
  calls = []
  if stage == "claim":
    original = core._publish_runtime_claim
    def interrupted(*args):
      original(*args)
      calls.append(True)
      raise OSError("synthetic-private-runtime-response-loss")
    monkeypatch.setattr(core, "_publish_runtime_claim", interrupted)
  else:
    original = core.enroll_runtime
    def interrupted(*args):
      original(*args)
      calls.append(True)
      raise OSError("synthetic-private-runtime-response-loss")
    monkeypatch.setattr(core, "enroll_runtime", interrupted)
  with pytest.raises(Conflict) as caught:
    setup.prepare_setup(fresh, IDENTITY)
  assert "synthetic-private" not in str(caught.value) and calls == [True]
  assert core.runtime_claim_exists(fresh.cache, IDENTITY)
  assert not fresh.instance.exists() and not fresh.state_root.exists()
  before = contents(fresh.cache.parent)
  if stage == "claim":
    with pytest.raises(Conflict):
      setup.prepare_setup(fresh, IDENTITY)
    assert contents(fresh.cache.parent) == before
  else:
    # 已完整提交的包可在下一次显式请求中只读核验，不再调用登记。
    setup.prepare_setup(fresh, IDENTITY)
    assert calls == [True] and contents(fresh.cache.parent) == before


@pytest.mark.parametrize("stage", ["claim", "record"])
def test_scope_enrollment_response_loss_never_cleans_or_reenrolls(fresh, monkeypatch, stage):
  from agentcfg.storage import Tree
  setup.prepare_setup(fresh, IDENTITY)
  calls = []
  if stage == "claim":
    original = Tree.write_new
    def interrupted(tree, name, data):
      original(tree, name, data)
      if tree.root == claim_path(fresh).parent:
        calls.append(True)
        raise OSError("synthetic-private-scope-response-loss")
    monkeypatch.setattr(Tree, "write_new", interrupted)
  else:
    original = scopes().enroll_scope
    def interrupted(*args):
      original(*args)
      calls.append(True)
      raise OSError("synthetic-private-scope-response-loss")
    monkeypatch.setattr(scopes(), "enroll_scope", interrupted)
  with pytest.raises(Conflict) as caught, setup.apply_guard(fresh, IDENTITY):
    pytest.fail("no deploy after lost enrollment response")
  assert "synthetic-private" not in str(caught.value)
  assert calls == [True] and claim_path(fresh).exists()
  before = contents(fresh.cache.parent)
  if stage == "claim":
    with pytest.raises(Conflict), setup.apply_guard(fresh, IDENTITY):
      pytest.fail("partial claim cannot become legacy")
  else:
    with setup.apply_guard(fresh, IDENTITY):
      pass
  assert calls == [True] and contents(fresh.cache.parent) == before


def test_apply_body_failure_keeps_scope_and_uses_existing_guard_on_next_explicit_apply(fresh):
  setup.prepare_setup(fresh, IDENTITY)
  error = ValueError("synthetic-deployment-failure")
  with pytest.raises(ValueError) as caught, setup.apply_guard(fresh, IDENTITY):
    raise error
  assert caught.value is error and claim_path(fresh).exists()
  before = contents(fresh.cache.parent)
  with setup.apply_guard(fresh, IDENTITY):
    pass
  assert contents(fresh.cache.parent) == before


@pytest.mark.parametrize("place", ["cache", "leases", "runtimes", "runtime", "instance"])
def test_unsafe_probe_directories_refuse_without_new_metadata(fresh, tmp_path, place):
  target = tmp_path / "synthetic-target"
  target.mkdir(mode=0o700)
  path = {"cache": fresh.cache, "leases": fresh.cache / "leases",
    "runtimes": fresh.cache / "runtimes", "runtime": fresh.cache / "runtimes" / IDENTITY,
    "instance": fresh.instance}[place]
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  path.symlink_to(target, target_is_directory=True)
  before = contents(tmp_path)
  with pytest.raises(Conflict):
    setup.prepare_setup(fresh, IDENTITY)
  assert contents(tmp_path) == before and not domain(fresh).root.exists()


def test_existing_claimed_package_exclusive_lock_refuses_without_repair(fresh):
  core.enroll_runtime(core.initialize_domain(domain(fresh).root), fresh.cache, IDENTITY)
  fd = os.open(fresh.cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = contents(fresh.cache.parent)
    with pytest.raises(Conflict):
      setup.prepare_setup(fresh, IDENTITY)
    with pytest.raises(Conflict), setup.apply_guard(fresh, IDENTITY):
      pytest.fail("package proof must precede scope enrollment")
    assert contents(fresh.cache.parent) == before and not fresh.instance.exists()
  finally:
    os.close(fd)


def test_missing_existing_cooperative_domain_is_not_initialized(fresh, monkeypatch):
  cooperative(fresh)
  (domain(fresh).root / "coordination.json").unlink()
  monkeypatch.setattr(core, "initialize_domain", lambda *a: pytest.fail("must not repair cooperative domain"))
  before = contents(fresh.cache.parent)
  with pytest.raises(Conflict):
    setup.prepare_setup(fresh, IDENTITY)
  assert contents(fresh.cache.parent) == before


@pytest.mark.parametrize("operation", ["prepare", "apply"])
def test_workspace_global_root_validation_precedes_any_writes(fresh, operation):
  fresh.resolved.data["machine"]["paths"]["state_root"] += "/../invalid"
  before = contents(fresh.cache.parent)
  with pytest.raises(Conflict):
    if operation == "prepare":
      setup.prepare_setup(fresh, IDENTITY)
    else:
      with setup.apply_guard(fresh, IDENTITY):
        pytest.fail("invalid trusted workspace")
  assert contents(fresh.cache.parent) == before


@pytest.mark.parametrize("existing_instance", [False, True])
def test_visible_concurrent_runtime_claim_refuses_legacy_body_and_preserves_mixed_facts(fresh, monkeypatch, existing_instance):
  from contextlib import contextmanager
  if existing_instance:
    with omp_identity.lifecycle_guard(fresh, create=True):
      pass
  original_guard = omp_identity.lifecycle_guard
  calls = []
  @contextmanager
  def concurrent_guard(workspace, *, create=False):
    # 初次 claim 探测已选 legacy；另一准备请求在物理 EX 进入前提交真实包声明。
    assert not core.runtime_claim_exists(fresh.cache, IDENTITY)
    core.enroll_runtime(core.initialize_domain(domain(fresh).root), fresh.cache, IDENTITY)
    calls.append("runtime-enrolled")
    with original_guard(workspace, create=create) as fd:
      yield fd
  monkeypatch.setattr(omp_identity, "lifecycle_guard", concurrent_guard)
  body = []
  with pytest.raises(Conflict):
    with setup.apply_guard(fresh, IDENTITY):
      body.append("must-not-deploy")
  assert body == [] and calls == ["runtime-enrolled"]
  assert core.runtime_claim_exists(fresh.cache, IDENTITY)
  assert (fresh.instance / ".agentcfg-omp-owner.json").exists()
  assert not claim_path(fresh).exists()
  before = contents(fresh.cache.parent)
  with pytest.raises(Conflict), setup.apply_guard(fresh, IDENTITY):
    pytest.fail("mixed legacy instance and claimed runtime cannot become cooperative")
  assert contents(fresh.cache.parent) == before and calls == ["runtime-enrolled"]
  # 此重核只捕获已经可见的 claim；不证明跨资源全有或全无，也不消除后续窗口。
  # 运行入口仍须以包 claim/anchor 的物理复核作为最终保护。
