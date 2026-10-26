"""永久 runtime claim 的离线回归；仅合成缓存/记录，不运行宿主或发信号。"""

from contextlib import contextmanager
import fcntl
import os
import stat
from types import SimpleNamespace

import pytest

from agentcfg import resource_coordination as core
from agentcfg.omp_dependencies import OmpBackend
from agentcfg.resource_keys import ResourceKey
from agentcfg.resource_protocol import decode, encode
from agentcfg.storage import Conflict, Tree


IDENTITY = "synthetic-runtime"


def workspace(cache, state):
  return SimpleNamespace(cache=cache, state_root=state / "omp/profile", instance=state.parent / (state.name + "-instance"),
    resolved=SimpleNamespace(data={"machine": {"paths": {"state_root": str(state)}}, "profile": {}}))


def enrolled(tmp_path):
  original = workspace(tmp_path / "cache", tmp_path / "state-a")
  domain = core.initialize_domain(tmp_path / "state-a/lifecycle")
  anchor = core.enroll_runtime(domain, original.cache, IDENTITY)
  lease = original.cache / "leases" / (IDENTITY + ".lock")
  claim = original.cache / "runtime-claims" / (IDENTITY + ".json")
  return original, domain, anchor, lease, claim


@pytest.mark.parametrize("exclusive", [False, True])
@pytest.mark.parametrize("same_domain", [False, True])
@pytest.mark.parametrize("mutation", ["truncate", "delete", "recreate", "replace-leases"])
def test_existing_guard_cannot_downgrade_enrolled_runtime_after_lease_damage(tmp_path, exclusive, same_domain, mutation):
  original, domain, _, lease, _ = enrolled(tmp_path)
  other = workspace(original.cache, tmp_path / ("state-a" if same_domain else "state-b"))
  before = domain.snapshot()
  if mutation == "truncate":
    lease.write_bytes(b"")
  elif mutation == "delete":
    lease.unlink()
  elif mutation == "recreate":
    lease.rename(lease.with_suffix(".old"))
    lease.write_bytes(b"")
    assert lease.stat().st_ino != lease.with_suffix(".old").stat().st_ino
  else:
    lease.parent.rename(lease.parent.with_name("previous-leases"))
    lease.parent.mkdir(mode=0o700)
  with pytest.raises(Conflict):
    with OmpBackend().runtime_guard(other, IDENTITY, exclusive=exclusive):
      pass
  if mutation in ("delete", "replace-leases"):
    assert not lease.exists(), "guard must refuse before recreating a missing claimed lease"
  assert domain.snapshot() == before
  assert not other.state_root.exists() and not other.instance.exists()
  if not same_domain:
    assert not other.state_root.parents[1].exists()


def rejected(call):
  with pytest.raises(Conflict) as caught:
    call()
  assert caught.value.exit_code == 4
  assert "synthetic-private" not in str(caught.value)
  assert caught.value.__cause__ is None


@contextmanager
def locked(lease, *, exclusive=False):
  fd = os.open(lease, os.O_RDWR | os.O_NOFOLLOW)
  try:
    fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    yield fd
  finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def test_claim_bytes_equal_original_anchor_and_are_not_separate_authority(tmp_path):
  original, domain, anchor, lease, claim = enrolled(tmp_path)
  assert claim.read_bytes() == lease.read_bytes()
  assert decode(claim.read_bytes(), kind="runtime-anchor") == anchor
  assert claim.stat().st_size > 0 and claim.stat().st_nlink == 1
  assert stat.S_IMODE(claim.stat().st_mode) == 0o600
  assert core.runtime_claim_exists(original.cache, IDENTITY) is True
  with locked(lease, exclusive=True) as fd:
    assert domain.check_runtime(original.cache, IDENTITY, lease_fd=fd, idle=True) == anchor["resource_id"]
  enter_guard(original, exclusive=True)
  rejected(lambda: enter_guard(original))
  # 声明和租约逐字相同也不能独立授权；缺失域内登记时 EX 同步仍拒绝。
  state = domain.snapshot()
  del state["resources"][anchor["resource_id"]]
  (domain.root / "coordination.json").write_bytes(encode(state))
  rejected(lambda: enter_guard(original, exclusive=True))


def enter_guard(target, *, exclusive=False):
  with OmpBackend().runtime_guard(target, IDENTITY, exclusive=exclusive):
    pass


@pytest.mark.parametrize("cache_exists", [False, True])
def test_claim_lookup_missing_is_metadata_only_and_creates_nothing(tmp_path, cache_exists):
  cache = tmp_path / "cache"
  if cache_exists:
    cache.mkdir(mode=0o700)
  assert core.runtime_claim_exists(cache, IDENTITY) is False
  if cache_exists:
    assert list(cache.iterdir()) == []
  else:
    assert not cache.exists()


@pytest.mark.parametrize("raw", [b"", b"{synthetic-private-invalid", b"untrusted-declaration"])
def test_presence_does_not_read_or_parse_claim_or_lease_body(tmp_path, monkeypatch, raw):
  target = workspace(tmp_path / "cache", tmp_path / "state")
  claims = target.cache / "runtime-claims"
  claims.mkdir(mode=0o700, parents=True)
  claim = claims / (IDENTITY + ".json")
  claim.write_bytes(raw)
  def forbidden(*args, **kwargs):
    pytest.fail("metadata presence must not read any claim, lease, domain or native body")
  monkeypatch.setattr(Tree, "read", forbidden)
  monkeypatch.setattr(Tree, "open_read", forbidden)
  monkeypatch.setattr(core, "read_runtime_anchor", forbidden)
  monkeypatch.setattr(core.os, "read", forbidden)
  monkeypatch.setattr(core.os, "pread", forbidden)
  assert core.runtime_claim_exists(target.cache, IDENTITY) is True
  rejected(lambda: enter_guard(target))
  assert not (target.cache / "leases").exists()
  assert not target.state_root.parents[1].exists() and not target.instance.exists()


@pytest.mark.parametrize("damage", ["empty", "corrupt", "unsafe-mode", "symlink", "hardlink", "directory"])
@pytest.mark.parametrize("exclusive", [False, True])
def test_any_claim_presence_blocks_even_when_claim_is_unreadable_or_untrusted(tmp_path, damage, exclusive):
  target, _, _, lease, claim = enrolled(tmp_path)
  lease.unlink()
  if damage == "empty":
    claim.write_bytes(b"")
  elif damage == "corrupt":
    claim.write_bytes(b"synthetic-private-broken")
  elif damage == "unsafe-mode":
    claim.chmod(0o644)
  elif damage == "symlink":
    claim.rename(claim.with_suffix(".saved"))
    claim.symlink_to(claim.with_suffix(".saved"))
  elif damage == "hardlink":
    os.link(claim, claim.with_suffix(".alias"))
  else:
    claim.unlink(); claim.mkdir(mode=0o700)
  before = claim.lstat()
  assert core.runtime_claim_exists(target.cache, IDENTITY) is True
  rejected(lambda: enter_guard(target, exclusive=exclusive))
  after = claim.lstat()
  assert (before.st_ino, before.st_mode, before.st_nlink, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
    after.st_ino, after.st_mode, after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
  assert not lease.exists()
  assert not target.state_root.exists() and not target.instance.exists()


@pytest.mark.parametrize("damage", ["symlink-parent", "unsafe-parent", "file-parent"])
def test_claim_parent_anomaly_cannot_downgrade_to_legacy(tmp_path, damage):
  target, _, _, lease, claim = enrolled(tmp_path)
  lease.unlink()
  parent = claim.parent
  if damage == "unsafe-parent":
    parent.chmod(0o755)
  else:
    parent.rename(parent.with_name("saved-claims"))
    if damage == "symlink-parent":
      parent.symlink_to(parent.with_name("saved-claims"), target_is_directory=True)
    else:
      parent.write_bytes(b"synthetic-not-directory")
  rejected(lambda: core.runtime_claim_exists(target.cache, IDENTITY))
  rejected(lambda: enter_guard(target, exclusive=True))
  assert not lease.exists()
  assert not target.state_root.exists() and not target.instance.exists()


@pytest.mark.parametrize("exclusive", [False, True])
def test_missing_claim_alone_does_not_admit_existing_anchor(tmp_path, exclusive):
  target, _, _, lease, claim = enrolled(tmp_path)
  raw = lease.read_bytes()
  claim.unlink()
  rejected(lambda: enter_guard(target, exclusive=exclusive))
  assert lease.read_bytes() == raw
  assert not claim.exists()


@pytest.mark.parametrize("damage", ["missing", "mismatch", "corrupt"])
def test_domain_check_and_dispatch_require_matching_claim(tmp_path, damage):
  target, domain, anchor, lease, claim = enrolled(tmp_path)
  run = "a" * 32
  domain.reserve(run_id=run, op_id="b" * 32, resources=[anchor["resource_id"]], owner_ref={
    "state_root": str(target.state_root), "binding": {"machine": "synthetic", "local": str(tmp_path / "local.toml"), "profile": "synthetic"}})
  if damage == "missing":
    claim.unlink()
  elif damage == "mismatch":
    wrong = dict(anchor); wrong["domain_id"] = "f" * 32
    claim.write_bytes(encode(wrong))
  else:
    claim.write_bytes(b"synthetic-private-broken")
  before = domain.snapshot()
  with locked(lease) as fd:
    rejected(lambda: domain.check_runtime(target.cache, IDENTITY, lease_fd=fd))
    rejected(lambda: domain.dispatch(run, lease_fds={anchor["resource_id"]: fd}))
  assert domain.snapshot() == before
  assert before["reservations"][run]["phase"] == "reserved"


def test_failure_before_claim_publication_has_no_named_claim_or_lease_and_can_retry(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  claim = cache / "runtime-claims" / (IDENTITY + ".json")
  original = Tree.write_new
  injected = False
  def fail_before_claim(tree, name, *args, **kwargs):
    nonlocal injected
    if tree.root / name == claim:
      injected = True
      raise OSError("synthetic-private-before-claim")
    return original(tree, name, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", fail_before_claim)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert injected
  assert not claim.exists() and not (cache / "leases" / (IDENTITY + ".lock")).exists()
  assert domain.snapshot()["resources"] == {}
  anchor = core.enroll_runtime(domain, cache, IDENTITY)
  assert decode(claim.read_bytes(), kind="runtime-anchor") == anchor


@pytest.mark.parametrize("failure", ["claim-response-loss", "lease-publication", "ledger-write"])
def test_failure_after_claim_publication_preserves_claim_and_never_reenrolls(tmp_path, monkeypatch, failure):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  claim = cache / "runtime-claims" / (IDENTITY + ".json")
  lease = cache / "leases" / (IDENTITY + ".lock")
  write_new, link, replace = Tree.write_new, os.link, Tree.replace
  injected = False
  def fail_claim_response(tree, name, *args, **kwargs):
    nonlocal injected
    result = write_new(tree, name, *args, **kwargs)
    if tree.root / name == claim:
      injected = True
      raise OSError("synthetic-private-claim-response")
    return result
  def fail_lease(source, destination, *args, **kwargs):
    nonlocal injected
    if destination == IDENTITY + ".lock":
      injected = True
      raise OSError("synthetic-private-lease-publication")
    return link(source, destination, *args, **kwargs)
  def fail_ledger(tree, name, *args, **kwargs):
    nonlocal injected
    if tree.root == domain.root and name == "coordination.json":
      injected = True
      raise OSError("synthetic-private-ledger-write")
    return replace(tree, name, *args, **kwargs)
  with monkeypatch.context() as patch:
    if failure == "claim-response-loss": patch.setattr(Tree, "write_new", fail_claim_response)
    elif failure == "lease-publication": patch.setattr(core.os, "link", fail_lease)
    else: patch.setattr(Tree, "replace", fail_ledger)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert injected
  raw, inode = claim.read_bytes(), claim.stat().st_ino
  assert raw and decode(raw, kind="runtime-anchor")["kind"] == "runtime-anchor"
  assert domain.snapshot()["resources"] == {}
  if failure != "ledger-write": assert not lease.exists()
  else: assert lease.read_bytes() == raw
  rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert claim.read_bytes() == raw and claim.stat().st_ino == inode
  assert domain.snapshot()["resources"] == {}


@pytest.mark.parametrize("existing", ["empty-lease", "old-runtime"])
def test_old_resources_are_not_read_or_adopted_and_create_no_claim(tmp_path, monkeypatch, existing):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  cache.mkdir(mode=0o700)
  path = cache / ("leases" if existing == "empty-lease" else "runtimes") / (IDENTITY + ".lock" if existing == "empty-lease" else IDENTITY)
  path.parent.mkdir(mode=0o700)
  if existing == "empty-lease": path.write_bytes(b"")
  else: path.mkdir(mode=0o700); (path / "synthetic-private-body").write_bytes(b"must-not-read")
  original = Tree.read
  def no_old_body(tree, name, *args, **kwargs):
    if tree.root / name == path:
      pytest.fail("enrollment must not read existing lease/runtime body to decide freshness")
    return original(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", no_old_body)
  rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert not (cache / "runtime-claims" / (IDENTITY + ".json")).exists()
  assert domain.snapshot()["resources"] == {}


@pytest.mark.parametrize("exclusive", [False, True])
def test_empty_legacy_runtime_without_claim_retains_guard_compatibility(tmp_path, exclusive):
  target = workspace(tmp_path / "cache", tmp_path / "state")
  enter_guard(target, exclusive=exclusive)
  assert (target.cache / "leases" / (IDENTITY + ".lock")).read_bytes() == b""
  assert not (target.cache / "runtime-claims").exists()
  assert not target.state_root.parents[1].exists() and not target.instance.exists()


def test_declaration_is_not_first_adoption_or_domain_authorization(tmp_path):
  target = workspace(tmp_path / "cache", tmp_path / "state")
  domain = core.initialize_domain(tmp_path / "state/lifecycle")
  state = domain.snapshot()
  claim = target.cache / "runtime-claims" / (IDENTITY + ".json")
  claim.parent.mkdir(mode=0o700, parents=True)
  raw = encode({"schema_version": 1, "kind": "runtime-anchor", "protocol": "rotom-resource-v1",
    "domain_id": state["domain_id"], "domain_physical": state["physical"], "resource_id": "e" * 32,
    "resource_key": ResourceKey("runtime", 0, 999).as_dict()})
  claim.write_bytes(raw)
  assert core.runtime_claim_exists(target.cache, IDENTITY) is True
  rejected(lambda: core.enroll_runtime(domain, target.cache, IDENTITY))
  rejected(lambda: enter_guard(target, exclusive=True))
  assert domain.snapshot() == state
  assert not (target.cache / "leases" / (IDENTITY + ".lock")).exists()
  assert claim.read_bytes() == raw


def test_cache_parent_fsync_failure_retains_claim_and_blocks_final_publication(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  claim = cache / "runtime-claims" / (IDENTITY + ".json")
  parent_identity = (cache.parent.stat().st_dev, cache.parent.stat().st_ino)
  original = os.fsync
  injected = False
  def fail_cache_parent(fd):
    nonlocal injected
    info = os.fstat(fd)
    if claim.exists() and (info.st_dev, info.st_ino) == parent_identity:
      injected = True
      raise OSError("synthetic-private-cache-parent-fsync")
    return original(fd)
  with monkeypatch.context() as patch:
    patch.setattr(core.os, "fsync", fail_cache_parent)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert injected
  raw = claim.read_bytes()
  assert raw and not (cache / "leases" / (IDENTITY + ".lock")).exists()
  assert domain.snapshot()["resources"] == {}
  rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert claim.read_bytes() == raw


def test_claim_file_directory_cache_and_parent_are_fsynced_before_final_lease_link(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  claim = cache / "runtime-claims" / (IDENTITY + ".json")
  synced = set()
  final_link_observed = False
  original_sync, original_link = os.fsync, os.link
  def record_sync(fd):
    result = original_sync(fd)
    info = os.fstat(fd)
    synced.add((info.st_dev, info.st_ino))
    return result
  def require_claim_durability(source, destination, *args, **kwargs):
    nonlocal final_link_observed
    if destination == IDENTITY + ".lock":
      required = [(path.stat().st_dev, path.stat().st_ino) for path in (claim, claim.parent, cache, cache.parent)]
      assert set(required).issubset(synced)
      final_link_observed = True
    return original_link(source, destination, *args, **kwargs)
  monkeypatch.setattr(core.os, "fsync", record_sync)
  monkeypatch.setattr(core.os, "link", require_claim_durability)
  anchor = core.enroll_runtime(domain, cache, IDENTITY)
  assert final_link_observed
  assert decode(claim.read_bytes(), kind="runtime-anchor") == anchor


@pytest.mark.parametrize("exclusive", [False, True])
def test_claim_appearing_after_flock_is_rechecked_before_guard_yields(tmp_path, monkeypatch, exclusive):
  target = workspace(tmp_path / "cache", tmp_path / "state")
  claim = target.cache / "runtime-claims" / (IDENTITY + ".json")
  original = fcntl.flock
  injected = False
  def publish_after_flock(fd, flags):
    nonlocal injected
    result = original(fd, flags)
    if not flags & fcntl.LOCK_UN and not injected:
      injected = True
      claim.parent.mkdir(mode=0o700)
      claim.write_bytes(b"synthetic-private-untrusted-declaration")
    return result
  monkeypatch.setattr(fcntl, "flock", publish_after_flock)
  rejected(lambda: enter_guard(target, exclusive=exclusive))
  assert injected
  assert not target.state_root.parents[1].exists() and not target.instance.exists()


@pytest.mark.parametrize("mutation", ["replace-claims-directory", "unlink-claim"])
def test_named_claim_must_still_exist_after_parent_fsync_before_final_lease_publication(tmp_path, monkeypatch, mutation):
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  claim = cache / "runtime-claims" / (IDENTITY + ".json")
  lease = cache / "leases" / (IDENTITY + ".lock")
  old_claim = cache / "old-claims" / claim.name
  parent_identity = (cache.parent.stat().st_dev, cache.parent.stat().st_ino)
  original = os.fsync
  injected = False
  saved_raw = None
  def mutate_during_cache_parent_sync(fd):
    nonlocal injected, saved_raw
    result = original(fd)
    info = os.fstat(fd)
    if not injected and claim.exists() and (info.st_dev, info.st_ino) == parent_identity:
      injected = True
      saved_raw = claim.read_bytes()
      if mutation == "replace-claims-directory":
        claim.parent.rename(old_claim.parent)
        claim.parent.mkdir(mode=0o700)
      else:
        claim.unlink()
    return result
  with monkeypatch.context() as patch:
    patch.setattr(core.os, "fsync", mutate_during_cache_parent_sync)
    rejected(lambda: core.enroll_runtime(domain, cache, IDENTITY))
  assert injected and saved_raw
  assert domain.snapshot()["resources"] == {}
  assert not claim.exists()
  if mutation == "replace-claims-directory":
    assert old_claim.read_bytes() == saved_raw
  assert not lease.exists(), "lost/replaced named claim must refuse before publishing the final lease"
