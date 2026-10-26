"""临时文件系统与真实 flock 的协调核心验收；不运行宿主或授予维护许可。"""

from contextlib import contextmanager, ExitStack
import fcntl
import os
from pathlib import Path
import shutil
import stat

import pytest

from agentcfg import resource_coordination as core
from agentcfg.resource_keys import resource_key
from agentcfg.resource_protocol import encode
from agentcfg.storage import Conflict, Tree


IDENTITY = "synthetic-runtime"
RUN_A = "1" * 32
RUN_B = "2" * 32
BATCH_A = "3" * 32
BATCH_B = "4" * 32
OP_A = "5" * 32
OP_B = "6" * 32


def rejected(call):
  with pytest.raises(Conflict) as caught:
    call()
  assert caught.value.exit_code == 4
  assert "synthetic-private" not in str(caught.value)
  assert caught.value.__cause__ is None


def owner(tmp_path, name="owner-a"):
  state = tmp_path / name
  state.mkdir(mode=0o700, exist_ok=True)
  return {"state_root": str(state), "binding": {"machine": "synthetic-machine",
    "local": str(tmp_path / "synthetic-local.toml"), "profile": "synthetic-profile"}}


def enrolled(tmp_path, *, domain=None, name="cache-a", identity=IDENTITY):
  domain = domain or core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / name
  anchor = core.enroll_runtime(domain, cache, identity)
  return domain, cache, anchor


@contextmanager
def locked(cache, identity=IDENTITY, *, exclusive=False):
  fd = os.open(cache / "leases" / (identity + ".lock"), os.O_RDWR | os.O_NOFOLLOW)
  try:
    fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    yield fd
  finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def check(domain, cache, *, idle=False, identity=IDENTITY):
  with locked(cache, identity, exclusive=idle) as fd:
    return domain.check_runtime(cache, identity, lease_fd=fd, idle=idle)


def dispatch(domain, run_id):
  state = domain.snapshot()
  with ExitStack() as stack:
    fds = {rid: stack.enter_context(locked(
      Path(state["resources"][rid]["cache"]), state["resources"][rid]["runtime_identity"]))
      for rid in state["reservations"][run_id]["resources"]}
    domain.dispatch(run_id, lease_fds=fds)


def reserve(domain, tmp_path, rid, *, run_id=RUN_A, op_id=OP_A, owner_name="owner-a"):
  domain.reserve(run_id=run_id, op_id=op_id, owner_ref=owner(tmp_path, owner_name), resources=[rid])


def intent(domain, resources, selected_runs, *, batch_id=BATCH_A, revision=None, operation="setup"):
  domain.accept_intent(batch_id=batch_id, generation=1, operation=operation,
    expected_revision=domain.snapshot()["revision"] if revision is None else revision,
    resources=resources, selected_runs=selected_runs)


def write_state(domain, value):
  (domain.root / "coordination.json").write_bytes(encode(value))


def test_missing_domain_read_does_not_create_anything(tmp_path):
  root = tmp_path / "missing"
  rejected(lambda: core.Domain(root).snapshot())
  assert not root.exists()


def test_initialization_is_explicit_idempotent_and_physically_bound(tmp_path):
  root = tmp_path / "domain"
  first = core.initialize_domain(root)
  before = first.snapshot()
  raw = (root / "coordination.json").read_bytes()
  assert core.initialize_domain(root).snapshot() == before
  assert (root / "coordination.json").read_bytes() == raw
  assert before["physical"] == {"device": root.stat().st_dev, "inode": root.stat().st_ino}
  assert before["revision"] == 0 and before["resources"] == before["reservations"] == before["intents"] == {}


def test_unknown_nonempty_directory_is_never_initialized(tmp_path):
  root = tmp_path / "unknown"
  root.mkdir(mode=0o700)
  sentinel = root / "synthetic-private-unowned"
  sentinel.write_bytes(b"synthetic-sentinel")
  rejected(lambda: core.initialize_domain(root))
  assert sentinel.read_bytes() == b"synthetic-sentinel"
  assert not (root / "coordination.json").exists()


@pytest.mark.parametrize("existing", [False, True])
def test_initialization_confirms_parent_sync_before_return(tmp_path, monkeypatch, existing):
  root = tmp_path / "domain"
  if existing: core.initialize_domain(root)
  parent = root.parent.stat(); fsync = os.fsync; seen = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
      assert (root / "coordination.json").is_file()
      seen.append(True)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  core.initialize_domain(root)
  assert seen == [True]


@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_initialization_parent_sync_failure_preserves_published_domain(tmp_path, monkeypatch, kind):
  root = tmp_path / "domain"; parent = root.parent.stat(); fsync = os.fsync
  error = kind("synthetic-private-canary")
  def failed(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino): raise error
    return fsync(fd)
  with monkeypatch.context() as patch:
    patch.setattr(os, "fsync", failed)
    with pytest.raises(Conflict if kind is OSError else kind) as caught: core.initialize_domain(root)
  if kind is OSError: assert "synthetic-private-canary" not in str(caught.value)
  else: assert caught.value is error
  raw = (root / "coordination.json").read_bytes()
  # 显式重新核验同步已有域，不重新生成域身份或覆写未知事实。
  core.initialize_domain(root)
  assert (root / "coordination.json").read_bytes() == raw


def test_initialization_rechecks_named_root_after_parent_sync(tmp_path, monkeypatch):
  root = tmp_path / "domain"; parent = root.parent.stat(); fsync = os.fsync; changed = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino) and not changed:
      changed.append(True); root.rename(tmp_path / "saved-domain"); root.mkdir(mode=0o700)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  with pytest.raises(Conflict): core.initialize_domain(root)
  assert changed and list(root.iterdir()) == []


def test_existing_domain_rechecks_its_own_directory_durability(tmp_path, monkeypatch):
  root = tmp_path / "domain"; core.initialize_domain(root)
  original = root.stat(); fsync = os.fsync; seen = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (original.st_dev, original.st_ino): seen.append(True)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  core.initialize_domain(root)
  assert seen == [True]


@pytest.mark.parametrize("fault", ["none", "error", "root-replacement"])
def test_reopened_domain_commit_confirms_ancestors_before_return(tmp_path, monkeypatch, fault):
  root = tmp_path / "domain"; core.initialize_domain(root)
  domain = core.Domain(root); parent = root.parent.stat(); fsync = os.fsync; seen = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino) and not seen:
      # 测试直接读取已发布字节，不在持锁时重入 Domain。
      state = core.decode((root / "coordination.json").read_bytes(), kind="domain")
      assert state["revision"] == 1
      seen.append(True)
      if fault == "error": raise OSError("synthetic-private-canary")
      if fault == "root-replacement":
        root.rename(tmp_path / "saved-domain"); root.mkdir(mode=0o700)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  def commit():
    with domain._transaction(write=True): pass
  if fault == "none": commit()
  else:
    with pytest.raises(Conflict): commit()
  assert seen == [True]
  saved = root if fault != "root-replacement" else tmp_path / "saved-domain"
  assert core.decode((saved / "coordination.json").read_bytes(), kind="domain")["revision"] == 1


def test_copying_ledger_does_not_copy_physical_domain(tmp_path):
  domain = core.initialize_domain(tmp_path / "original")
  copied = tmp_path / "copied"
  shutil.copytree(domain.root, copied)
  raw = (copied / "coordination.json").read_bytes()
  rejected(lambda: core.Domain(copied).snapshot())
  rejected(lambda: core.initialize_domain(copied))
  assert (copied / "coordination.json").read_bytes() == raw


def test_fresh_enrollment_publishes_nonempty_single_inode_anchor(tmp_path):
  domain, cache, anchor = enrolled(tmp_path)
  path = cache / "leases" / (IDENTITY + ".lock")
  info = path.stat()
  assert info.st_size > 0 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
  assert (anchor["resource_key"]["device"], anchor["resource_key"]["inode"]) == (info.st_dev, info.st_ino)
  with locked(cache) as fd:
    assert core.read_runtime_anchor(fd) == anchor
    assert domain.check_runtime(cache, IDENTITY, lease_fd=fd) == anchor["resource_id"]
    assert os.fstat(fd).st_ino == info.st_ino
  record = domain.snapshot()["resources"][anchor["resource_id"]]
  assert record["status"] == "ready" and record["key"] == anchor["resource_key"]
  assert check(domain, cache, idle=True) == anchor["resource_id"]


@pytest.mark.parametrize("existing", ["empty-lease", "old-runtime"])
def test_existing_unregistered_resources_are_not_adopted(tmp_path, existing):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  cache.mkdir(mode=0o700)
  if existing == "empty-lease":
    (cache / "leases").mkdir(mode=0o700)
    path = cache / "leases" / (IDENTITY + ".lock")
    path.write_bytes(b"")
  else:
    (cache / "runtimes").mkdir(mode=0o700)
    path = cache / "runtimes" / IDENTITY
    path.mkdir(mode=0o700)
  before = path.stat()
  rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert (path.stat().st_dev, path.stat().st_ino) == (before.st_dev, before.st_ino)
  assert domain.snapshot()["resources"] == {}
  if existing == "empty-lease":
    with locked(cache) as fd:
      assert core.read_runtime_anchor(fd) is None
    assert path.read_bytes() == b""


def test_two_domains_never_overwrite_same_target_or_accept_foreign_anchor(tmp_path):
  first, cache, anchor = enrolled(tmp_path)
  second = core.initialize_domain(tmp_path / "other-domain")
  path = cache / "leases" / (IDENTITY + ".lock")
  raw, inode = path.read_bytes(), path.stat().st_ino
  rejected(lambda: core.enroll_runtime(second, cache, IDENTITY))
  with locked(cache, exclusive=True) as fd:
    rejected(lambda: second.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True))
  assert path.read_bytes() == raw and path.stat().st_ino == inode
  assert second.snapshot()["resources"] == {}
  assert check(first, cache) == anchor["resource_id"]


def test_published_anchor_survives_failed_ledger_write_and_never_becomes_legacy(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  original = Tree.replace
  def fail_ledger(tree, path, *args, **kwargs):
    if tree.root == domain.root and path == "coordination.json":
      raise OSError("synthetic-private-write-failure")
    return original(tree, path, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", fail_ledger)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  path = cache / "leases" / (IDENTITY + ".lock")
  raw = path.read_bytes()
  assert raw and stat.S_IMODE(path.stat().st_mode) == 0o600
  with locked(cache, exclusive=True) as fd:
    assert core.read_runtime_anchor(fd) is not None
    rejected(lambda: domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True))
  assert domain.snapshot()["resources"] == {}
  rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert path.read_bytes() == raw


@pytest.mark.parametrize("status", ["missing", "preparing", "unknown"])
def test_anchor_without_ready_ledger_never_passes(tmp_path, status):
  domain, cache, anchor = enrolled(tmp_path)
  state = domain.snapshot()
  if status == "missing":
    del state["resources"][anchor["resource_id"]]
  else:
    state["resources"][anchor["resource_id"]]["status"] = status
  write_state(domain, state)
  with locked(cache, exclusive=True) as fd:
    assert core.read_runtime_anchor(fd) is not None
    rejected(lambda: domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True))


def test_reserve_then_dispatch_are_persistent_and_failed_dispatch_stays_reserved(tmp_path, monkeypatch):
  domain, cache, anchor = enrolled(tmp_path)
  rid = anchor["resource_id"]
  reserve(domain, tmp_path, rid)
  state = core.Domain(domain.root).snapshot()
  assert state["reservations"][RUN_A]["phase"] == "reserved"
  revision = state["revision"]
  original = Tree.replace
  def fail(tree, path, *args, **kwargs):
    if tree.root == domain.root:
      raise OSError("synthetic-private-dispatch-write")
    return original(tree, path, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", fail)
    rejected(lambda: dispatch(domain, RUN_A))
  after = core.Domain(domain.root).snapshot()
  assert after["revision"] == revision and after["reservations"][RUN_A]["phase"] == "reserved"
  dispatch(domain, RUN_A)
  assert core.Domain(domain.root).snapshot()["reservations"][RUN_A]["phase"] == "dispatched"
  assert domain.snapshot()["revision"] == revision + 1


def test_wrong_physical_fd_cannot_dispatch_another_resource(tmp_path):
  domain, first, anchor = enrolled(tmp_path)
  _, second, _ = enrolled(tmp_path, domain=domain, name="cache-b")
  reserve(domain, tmp_path, anchor["resource_id"])
  with locked(second) as wrong:
    rejected(lambda: domain.dispatch(RUN_A, lease_fds={anchor["resource_id"]: wrong}))
  assert domain.snapshot()["reservations"][RUN_A]["phase"] == "reserved"
  assert check(domain, first) == anchor["resource_id"]


def test_unknown_survives_free_ex_and_another_owners_empty_state(tmp_path):
  domain, cache, anchor = enrolled(tmp_path)
  reserve(domain, tmp_path, anchor["resource_id"])
  dispatch(domain, RUN_A)
  domain.mark_unknown(RUN_A)
  assert list(Path(owner(tmp_path, "owner-b")["state_root"]).iterdir()) == []
  # A 的测试 fd 已关闭；B 确实取得 EX，也不能把空 owner 状态当作完整域空闲证明。
  with locked(cache, exclusive=True) as fd:
    rejected(lambda: domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True))
  domain.mark_unknown(RUN_A)
  rejected(lambda: domain.cancel_reserved(RUN_A))
  assert core.Domain(domain.root).snapshot()["reservations"][RUN_A]["phase"] == "unknown"


@pytest.mark.parametrize("phase", ["reserved", "dispatched", "unknown"])
def test_reservation_cancellation_only_applies_before_dispatch(tmp_path, phase):
  domain, cache, anchor = enrolled(tmp_path)
  reserve(domain, tmp_path, anchor["resource_id"])
  if phase == "dispatched":
    dispatch(domain, RUN_A)
  elif phase == "unknown":
    domain.mark_unknown(RUN_A)
  if phase == "reserved":
    domain.cancel_reserved(RUN_A)
    assert domain.snapshot()["reservations"][RUN_A]["phase"] == "cancelled"
    assert check(domain, cache, idle=True) == anchor["resource_id"]
  else:
    rejected(lambda: domain.cancel_reserved(RUN_A))
    assert domain.snapshot()["reservations"][RUN_A]["phase"] == phase


def test_intent_revision_cas_is_exact_and_failure_does_not_mutate(tmp_path):
  domain, _, anchor = enrolled(tmp_path)
  before = domain.snapshot()
  for stale in (before["revision"] - 1, True):
    rejected(lambda: intent(domain, [anchor["resource_id"]], [], revision=stale))
    assert domain.snapshot() == before
  intent(domain, [anchor["resource_id"]], [], revision=before["revision"])
  assert domain.snapshot()["intents"][BATCH_A]["phase"] == "active"


@pytest.mark.parametrize("selection", [[], [RUN_A], [RUN_A, RUN_B, "f" * 32]])
def test_intent_requires_complete_exact_intersecting_run_selection(tmp_path, selection):
  domain, _, anchor = enrolled(tmp_path)
  reserve(domain, tmp_path, anchor["resource_id"])
  reserve(domain, tmp_path, anchor["resource_id"], run_id=RUN_B, op_id=OP_B, owner_name="owner-b")
  dispatch(domain, RUN_A); dispatch(domain, RUN_B)
  before = domain.snapshot()
  rejected(lambda: intent(domain, [anchor["resource_id"]], selection))
  assert domain.snapshot() == before
  intent(domain, [anchor["resource_id"]], [RUN_A, RUN_B])


@pytest.mark.parametrize("phase", ["reserved", "unknown"])
def test_intent_refuses_reserved_or_unknown_runs_even_when_selected(tmp_path, phase):
  domain, _, anchor = enrolled(tmp_path)
  reserve(domain, tmp_path, anchor["resource_id"])
  if phase == "unknown":
    domain.mark_unknown(RUN_A)
  rejected(lambda: intent(domain, [anchor["resource_id"]], [RUN_A]))
  assert domain.snapshot()["intents"] == {}


def test_intent_overlap_and_reserve_fence_leave_disjoint_resources_usable(tmp_path):
  domain, _, anchor = enrolled(tmp_path)
  rid = anchor["resource_id"]
  intent(domain, [rid], [])
  rejected(lambda: intent(domain, [rid], [], batch_id=BATCH_B))
  rejected(lambda: reserve(domain, tmp_path, rid))
  _, other_cache, other = enrolled(tmp_path, domain=domain, name="cache-b")
  reserve(domain, tmp_path, other["resource_id"], run_id=RUN_B, op_id=OP_B)
  dispatch(domain, RUN_B)
  assert check(domain, other_cache) == other["resource_id"]
  domain.cancel_intent(BATCH_A)
  reserve(domain, tmp_path, rid)


@pytest.mark.parametrize("phase", ["active", "dispatched", "unknown"])
def test_intent_cancel_only_active_and_unknown_is_not_cleared(tmp_path, phase):
  domain, cache, anchor = enrolled(tmp_path)
  intent(domain, [anchor["resource_id"]], [])
  if phase == "dispatched":
    with locked(cache):
      domain.dispatch_intent(BATCH_A)
  elif phase == "unknown":
    domain.mark_intent_unknown(BATCH_A)
  if phase == "active":
    domain.cancel_intent(BATCH_A)
    assert domain.snapshot()["intents"][BATCH_A]["phase"] == "cancelled"
  else:
    rejected(lambda: domain.cancel_intent(BATCH_A))
    assert domain.snapshot()["intents"][BATCH_A]["phase"] == phase
    rejected(lambda: check(domain, cache, idle=True))


def test_dispatch_intent_then_unknown_stays_blocking_with_free_physical_ex(tmp_path):
  domain, cache, anchor = enrolled(tmp_path)
  intent(domain, [anchor["resource_id"]], [])
  with locked(cache):
    domain.dispatch_intent(BATCH_A)
  domain.mark_intent_unknown(BATCH_A)
  domain.mark_intent_unknown(BATCH_A)
  rejected(lambda: domain.cancel_intent(BATCH_A))
  rejected(lambda: check(domain, cache, idle=True))
  assert domain.snapshot()["intents"][BATCH_A]["phase"] == "unknown"


def test_busy_domain_exclusive_lock_is_nonblocking_and_never_writes(tmp_path, monkeypatch):
  domain, _, anchor = enrolled(tmp_path)
  reference = owner(tmp_path)
  state_file = domain.root / "coordination.json"
  before = state_file.read_bytes()
  original = fcntl.flock
  with Tree(domain.root) as held:
    original(held.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def nonblocking(fd, flags):
      if not flags & fcntl.LOCK_UN:
        assert flags & fcntl.LOCK_NB, "coordination must never wait on its short metadata lock"
      return original(fd, flags)
    try:
      with monkeypatch.context() as patch:
        patch.setattr(fcntl, "flock", nonblocking)
        rejected(lambda: domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=reference,
          resources=[anchor["resource_id"]]))
    finally:
      original(held.fd, fcntl.LOCK_UN)
  assert state_file.read_bytes() == before


def test_domain_named_root_replaced_after_read_is_rejected(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  original = Tree.read
  replaced = False
  def read_then_replace(tree, path, *args, **kwargs):
    nonlocal replaced
    result = original(tree, path, *args, **kwargs)
    if tree.root == domain.root and path == "coordination.json" and not replaced:
      replaced = True
      tree.root.rename(tmp_path / "previous-domain")
      tree.root.mkdir(mode=0o700)
      (tree.root / "coordination.json").write_bytes(result[0])
    return result
  monkeypatch.setattr(Tree, "read", read_then_replace)
  rejected(domain.snapshot)
  assert replaced


def test_dispatch_commit_then_response_loss_retains_dispatched_not_cancellable(tmp_path, monkeypatch):
  domain, cache, anchor = enrolled(tmp_path)
  reserve(domain, tmp_path, anchor["resource_id"])
  original = Tree.replace
  committed = False
  def commit_then_fail(tree, path, *args, **kwargs):
    nonlocal committed
    result = original(tree, path, *args, **kwargs)
    if tree.root == domain.root and path == "coordination.json" and not committed:
      committed = True
      raise OSError("synthetic-private-response-loss")
    return result
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", commit_then_fail)
    rejected(lambda: dispatch(domain, RUN_A))
  assert committed
  assert core.Domain(domain.root).snapshot()["reservations"][RUN_A]["phase"] == "dispatched"
  rejected(lambda: domain.cancel_reserved(RUN_A))
  rejected(lambda: check(domain, cache, idle=True))


def test_intent_dispatch_rechecks_run_that_became_unknown_after_acceptance(tmp_path):
  domain, cache, anchor = enrolled(tmp_path)
  reserve(domain, tmp_path, anchor["resource_id"])
  dispatch(domain, RUN_A)
  intent(domain, [anchor["resource_id"]], [RUN_A])
  domain.mark_unknown(RUN_A)
  before = domain.snapshot()
  with locked(cache):
    rejected(lambda: domain.dispatch_intent(BATCH_A))
  assert domain.snapshot() == before
  assert before["intents"][BATCH_A]["phase"] == "active"


def test_failure_after_claim_before_lease_link_keeps_claim_and_blocks_retry(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  original = os.link
  def fail_publication(source, target, *args, **kwargs):
    if target == IDENTITY + ".lock":
      raise OSError("synthetic-private-before-publication")
    return original(source, target, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(core.os, "link", fail_publication)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert not (cache / "leases" / (IDENTITY + ".lock")).exists()
  assert list((cache / "leases").iterdir()) == []
  assert domain.snapshot()["resources"] == {}
  claim = cache / "runtime-claims" / (IDENTITY + ".json")
  raw = claim.read_bytes()
  assert raw
  rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert claim.read_bytes() == raw


def test_missing_domain_ledger_does_not_turn_existing_anchor_legacy(tmp_path):
  domain, cache, _ = enrolled(tmp_path)
  path = cache / "leases" / (IDENTITY + ".lock")
  raw = path.read_bytes()
  (domain.root / "coordination.json").unlink()
  with locked(cache, exclusive=True) as fd:
    assert core.read_runtime_anchor(fd) is not None
    rejected(lambda: domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True))
  assert not (domain.root / "coordination.json").exists()
  assert path.read_bytes() == raw


def test_competing_empty_final_before_link_is_preserved_without_registration(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  original = os.link
  competitor = None
  def compete_before_link(source, target, *args, **kwargs):
    nonlocal competitor
    if target == IDENTITY + ".lock" and competitor is None:
      fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600, dir_fd=kwargs["dst_dir_fd"])
      try:
        info = os.fstat(fd)
        competitor = (info.st_dev, info.st_ino)
      finally:
        os.close(fd)
    return original(source, target, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(core.os, "link", compete_before_link)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  path = cache / "leases" / (IDENTITY + ".lock")
  assert competitor == (path.stat().st_dev, path.stat().st_ino)
  assert path.read_bytes() == b""
  assert path.stat().st_nlink == 1
  assert list(path.parent.iterdir()) == [path]
  assert domain.snapshot()["resources"] == {}


def test_unlink_failure_after_link_retains_nonempty_double_link_and_blocks_reenrollment(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  original_link, original_unlink = os.link, os.unlink
  temporary = None
  parent_fd = None
  failures = 0
  def record_publication(source, target, *args, **kwargs):
    nonlocal temporary, parent_fd
    result = original_link(source, target, *args, **kwargs)
    if target == IDENTITY + ".lock":
      temporary, parent_fd = source, kwargs["src_dir_fd"]
    return result
  def fail_only_this_temporary(name, *args, **kwargs):
    nonlocal failures
    if temporary is not None and name == temporary and kwargs.get("dir_fd") == parent_fd:
      failures += 1
      raise OSError("synthetic-private-temporary-unlink-failure")
    return original_unlink(name, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(core.os, "link", record_publication)
    patch.setattr(core.os, "unlink", fail_only_this_temporary)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert failures >= 2
  path = cache / "leases" / (IDENTITY + ".lock")
  pending = path.parent / temporary
  raw = path.read_bytes()
  assert raw and path.stat().st_nlink == pending.stat().st_nlink == 2
  assert path.stat().st_ino == pending.stat().st_ino
  with locked(cache, exclusive=True) as fd:
    rejected(lambda: core.read_runtime_anchor(fd))
    rejected(lambda: resource_key("runtime", path, lease_fd=fd))
    rejected(lambda: domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True))
  assert domain.snapshot()["resources"] == {}
  before = set(path.parent.iterdir())
  rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert set(path.parent.iterdir()) == before
  assert path.read_bytes() == raw and path.stat().st_nlink == pending.stat().st_nlink == 2


@pytest.mark.parametrize("runtime_identity", [None, True, 1, "", ".", "..", "../escape", "a/b",
  "has space", "runtime\n", "中文", "a" * 193])
def test_invalid_runtime_identity_is_rejected_before_creating_cache(tmp_path, runtime_identity):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "must-not-be-created"
  before = domain.snapshot()
  rejected(lambda: core.enroll_runtime(domain, cache, runtime_identity))
  assert not cache.exists()
  assert domain.snapshot() == before


def test_new_reservations_canonicalize_valid_sets_without_input_aliases(tmp_path, monkeypatch):
  domain, _, first = enrolled(tmp_path)
  _, _, second = enrolled(tmp_path, domain=domain, name="cache-b")
  ordered = sorted([first["resource_id"], second["resource_id"]])
  resources = list(reversed(ordered))
  captured = []
  original = core.encode
  def observe(value):
    if "reservations" in value:
      captured.extend(entry["resources"] for entry in value["reservations"].values())
    return original(value)
  monkeypatch.setattr(core, "encode", observe)
  reference = owner(tmp_path)
  domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=reference, resources=resources)
  domain.reserve(run_id=RUN_B, op_id=OP_B, owner_ref=reference, resources=ordered)
  snapshot = domain.snapshot()
  assert snapshot["reservations"][RUN_A]["resources"] == ordered
  assert snapshot["reservations"][RUN_B]["resources"] == ordered
  assert resources == list(reversed(ordered))
  assert all(saved is not resources and saved is not ordered for saved in captured)


def test_new_intents_canonicalize_both_sets_without_mutating_or_aliasing_inputs(tmp_path, monkeypatch):
  domain, _, first = enrolled(tmp_path)
  _, _, second = enrolled(tmp_path, domain=domain, name="cache-b")
  ordered = sorted([first["resource_id"], second["resource_id"]])
  reserve(domain, tmp_path, first["resource_id"])
  reserve(domain, tmp_path, second["resource_id"], run_id=RUN_B, op_id=OP_B, owner_name="owner-b")
  dispatch(domain, RUN_A)
  dispatch(domain, RUN_B)
  resources, runs = list(reversed(ordered)), [RUN_B, RUN_A]
  captured = []
  original = core.encode
  def observe(value):
    if "intents" in value:
      captured.extend((entry["resources"], entry["selected_runs"]) for entry in value["intents"].values())
    return original(value)
  monkeypatch.setattr(core, "encode", observe)
  intent(domain, resources, runs)
  first_entry = domain.snapshot()["intents"][BATCH_A]
  domain.cancel_intent(BATCH_A)
  ascending_runs = [RUN_A, RUN_B]
  intent(domain, ordered, ascending_runs, batch_id=BATCH_B)
  second_entry = domain.snapshot()["intents"][BATCH_B]
  assert first_entry["resources"] == second_entry["resources"] == ordered
  assert first_entry["selected_runs"] == second_entry["selected_runs"] == [RUN_A, RUN_B]
  assert resources == list(reversed(ordered)) and runs == [RUN_B, RUN_A]
  assert all(saved_resources is not resources and saved_resources is not ordered
    and saved_runs is not runs and saved_runs is not ascending_runs for saved_resources, saved_runs in captured)


@pytest.mark.parametrize("operation", ["reserve", "intent-resources", "intent-runs"])
def test_duplicate_set_inputs_still_fail_without_any_ledger_write(tmp_path, operation):
  domain, _, anchor = enrolled(tmp_path)
  rid = anchor["resource_id"]
  if operation != "reserve":
    reserve(domain, tmp_path, rid)
    dispatch(domain, RUN_A)
  reference = owner(tmp_path)
  before = (domain.root / "coordination.json").read_bytes()
  if operation == "reserve":
    rejected(lambda: domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=reference, resources=[rid, rid]))
  else:
    rejected(lambda: intent(domain, [rid, rid] if operation == "intent-resources" else [rid],
      [RUN_A, RUN_A] if operation == "intent-runs" else [RUN_A]))
  assert (domain.root / "coordination.json").read_bytes() == before


@pytest.mark.parametrize("third", ["unselected", "unknown"])
def test_canonicalization_never_omits_a_third_intersecting_or_unknown_run(tmp_path, third):
  domain, _, first = enrolled(tmp_path)
  _, _, second = enrolled(tmp_path, domain=domain, name="cache-b")
  third_run = "7" * 32
  reserve(domain, tmp_path, first["resource_id"])
  reserve(domain, tmp_path, second["resource_id"], run_id=RUN_B, op_id=OP_B, owner_name="owner-b")
  reserve(domain, tmp_path, second["resource_id"], run_id=third_run, op_id="8" * 32, owner_name="owner-c")
  for run in (RUN_A, RUN_B, third_run):
    dispatch(domain, run)
  selected = [RUN_B, RUN_A]
  if third == "unknown":
    domain.mark_unknown(third_run)
    selected.insert(0, third_run)
  before = (domain.root / "coordination.json").read_bytes()
  rejected(lambda: intent(domain, sorted([first["resource_id"], second["resource_id"]], reverse=True), selected))
  assert (domain.root / "coordination.json").read_bytes() == before


def test_legacy_unsorted_lists_remain_readable_without_rewriting(tmp_path):
  domain, _, first = enrolled(tmp_path)
  _, _, second = enrolled(tmp_path, domain=domain, name="cache-b")
  ordered = sorted([first["resource_id"], second["resource_id"]])
  domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=owner(tmp_path), resources=ordered)
  reserve(domain, tmp_path, first["resource_id"], run_id=RUN_B, op_id=OP_B, owner_name="owner-b")
  dispatch(domain, RUN_A)
  dispatch(domain, RUN_B)
  intent(domain, ordered, [RUN_A, RUN_B])
  state = domain.snapshot()
  state["reservations"][RUN_A]["resources"] = list(reversed(ordered))
  state["intents"][BATCH_A]["resources"] = list(reversed(ordered))
  state["intents"][BATCH_A]["selected_runs"] = [RUN_B, RUN_A]
  write_state(domain, state)
  before = (domain.root / "coordination.json").read_bytes()
  snapshot = domain.snapshot()
  assert snapshot == state
  assert (domain.root / "coordination.json").read_bytes() == before
