"""唯一实例域登记的离线验收；合成 fd 不授予真实宿主启动许可。"""

from contextlib import contextmanager, ExitStack
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import omp_identity, resource_coordination as core, resource_owners as owners, run_owners
from agentcfg.storage import Conflict, Tree, ensure_private, instance_lock
from test_rotom_resource_owners import IDENTITY, MANAGER, RUN, attach, make_workspace, owner_path, reserve


def workspace(root, profile="omp-a"):
  return SimpleNamespace(agent="omp", profile=profile, instance=root / "instances" / profile,
    state_root=root / "states" / profile,
    binding={"machine": "synthetic-machine", "local": str(root / "local.toml"), "profile": profile})


def claim_path(ws):
  name = hashlib.sha256(ws.instance.name.encode("utf-8")).hexdigest() + ".json"
  return ws.instance.parent / ".rotom-scope-claims" / name


@pytest.mark.parametrize("damage", ["claim", "lock"])
def test_damaged_claim_blocks_legacy_guard_without_rewriting_instance(tmp_path, damage):
  ws = make_workspace(tmp_path)
  if damage == "claim":
    claim = claim_path(ws)
    claim.parent.mkdir(mode=0o700)
    claim.write_bytes(b"{damaged")
    claim.chmod(0o600)
  else:
    (ws.instance / ".agentcfg-omp.lock").write_bytes(b"synthetic-coordination-anchor")
  before = {path.name: path.read_bytes() for path in ws.instance.iterdir() if path.is_file()}
  with pytest.raises(Conflict), omp_identity.lifecycle_guard(ws, shared=True):
    pass
  assert {path.name: path.read_bytes() for path in ws.instance.iterdir() if path.is_file()} == before


def scopes():
  from agentcfg import resource_scopes
  return resource_scopes


def enrolled(root):
  ws = workspace(root)
  domain = core.initialize_domain(root / "domain")
  anchor = scopes().enroll_scope(domain, ws)
  return ws, domain, anchor


@contextmanager
def held_scope(ws, cache=None, runtime=None):
  # scope 实例尚未开放 production guard；仅在合成测试中直接持有物理 fd。
  with ExitStack() as stack:
    stack.enter_context(Tree(ws.instance))
    instance_fd = os.open(ws.instance / ".agentcfg-omp.lock", os.O_RDWR | os.O_NOFOLLOW)
    stack.callback(os.close, instance_fd)
    fcntl.flock(instance_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    home = stack.enter_context(Tree(ws.instance / "user-home"))
    args = {"workspace": ws, "instance_fd": instance_fd, "native_home_fd": home.fd}
    if runtime is not None:
      ensure_private(ws.state_root)
      state = stack.enter_context(Tree(ws.state_root))
      stack.enter_context(instance_lock(state, shared=True))
      fd = os.open(cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR | os.O_NOFOLLOW)
      stack.callback(os.close, fd)
      fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
      args["runtime_fds"] = {runtime["resource_id"]: fd}
    yield args


def check(domain, args):
  return scopes().check_scope(domain, args["workspace"], instance_fd=args["instance_fd"],
    native_home_fd=args["native_home_fd"])


def scope_ids(anchor):
  return {anchor[key]["resource_id"] for key in ("instance", "native_home")}


def test_fresh_scope_has_matching_anchors_ready_resources_and_readonly_roundtrip(tmp_path):
  ws, domain, anchor = enrolled(tmp_path)
  assert anchor["schema_version"] == 1
  assert anchor["kind"] == "scope-anchor"
  assert anchor["protocol"] == "rotom-scope-v1"
  assert anchor["domain_id"] == domain.snapshot()["domain_id"]
  assert anchor["owner_ref"] == {"state_root": str(ws.state_root), "binding": ws.binding}
  assert len(anchor["claim_digest"]) == 64
  for path in (ws.instance / ".rotom-resource.json", ws.instance / "user-home/.rotom-resource.json",
      ws.instance / ".agentcfg-omp.lock"):
    assert json.loads(path.read_bytes()) == anchor
    assert path.stat().st_mode & 0o777 == 0o600
  assert claim_path(ws).is_file()
  assert (ws.instance / ".agentcfg-omp-owner.json").is_file()
  state = domain.snapshot()
  assert len(state["resources"]) == 2
  assert {state["resources"][rid]["key"]["kind"] for rid in scope_ids(anchor)} == {"instance", "native-home"}
  assert all(state["resources"][rid]["status"] == "ready" for rid in scope_ids(anchor))
  before = domain.snapshot()
  with held_scope(ws) as args:
    assert check(domain, args) == scope_ids(anchor)
  assert domain.snapshot() == before


@pytest.mark.parametrize("operation", ["exclusive", "shared", "create", "preflight"])
def test_scope_is_closed_to_ordinary_omp_operations(tmp_path, operation):
  ws, domain, anchor = enrolled(tmp_path)
  before = domain.snapshot()
  with pytest.raises(Conflict):
    if operation == "preflight":
      omp_identity.preflight_setup(ws)
    else:
      with omp_identity.lifecycle_guard(ws, shared=operation == "shared", create=operation == "create"):
        pass
  assert domain.snapshot() == before
  assert json.loads((ws.instance / ".agentcfg-omp.lock").read_bytes()) == anchor


@pytest.mark.parametrize("existing", ["empty", "legacy", "symlink"])
def test_enrollment_never_adopts_existing_instance(tmp_path, existing):
  ws = make_workspace(tmp_path) if existing == "legacy" else workspace(tmp_path)
  if existing == "empty":
    ws.instance.mkdir(mode=0o700, parents=True)
  elif existing == "symlink":
    target = tmp_path / "unrelated"
    target.mkdir(mode=0o700)
    ws.instance.parent.mkdir(mode=0o700)
    ws.instance.symlink_to(target, target_is_directory=True)
  before = sorted((str(p.relative_to(ws.instance)), p.read_bytes())
    for p in ws.instance.rglob("*") if p.is_file())
  domain = core.initialize_domain(tmp_path / "domain")
  with pytest.raises(Conflict):
    scopes().enroll_scope(domain, ws)
  assert sorted((str(p.relative_to(ws.instance)), p.read_bytes())
    for p in ws.instance.rglob("*") if p.is_file()) == before
  assert domain.snapshot()["resources"] == {}
  assert not claim_path(ws).exists()


def test_cross_domain_and_wrong_workspace_are_rejected_without_mutation(tmp_path):
  ws, domain, anchor = enrolled(tmp_path)
  other = core.initialize_domain(tmp_path / "other-domain")
  with held_scope(ws) as args:
    with pytest.raises(Conflict):
      check(other, args)
    wrong = deepcopy(ws)
    wrong.binding["machine"] = "another-machine"
    with pytest.raises(Conflict):
      check(domain, {**args, "workspace": wrong})
  saved = claim_path(ws).read_bytes()
  with pytest.raises(Conflict):
    scopes().enroll_scope(other, ws)
  assert claim_path(ws).read_bytes() == saved
  assert other.snapshot()["resources"] == {}


@pytest.mark.parametrize("target", ["claim", "instance-anchor", "home-anchor", "lock", "owner"])
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_scope_evidence_never_repairs_itself(tmp_path, target, damage):
  ws, domain, anchor = enrolled(tmp_path)
  paths = {"claim": claim_path(ws), "instance-anchor": ws.instance / ".rotom-resource.json",
    "home-anchor": ws.instance / "user-home/.rotom-resource.json",
    "lock": ws.instance / ".agentcfg-omp.lock", "owner": ws.instance / ".agentcfg-omp-owner.json"}
  with held_scope(ws) as args:
    path = paths[target]
    if damage == "missing":
      path.unlink()
    else:
      path.write_bytes(b"{damaged")
    with pytest.raises(Conflict):
      check(domain, args)
    if damage == "missing":
      assert not path.exists()
    else:
      assert path.read_bytes() == b"{damaged"
  with pytest.raises(Conflict), omp_identity.lifecycle_guard(ws, create=True):
    pass


@pytest.mark.parametrize("target", ["lock", "home"])
def test_identical_bytes_do_not_hide_replaced_physical_resources(tmp_path, target):
  ws, domain, anchor = enrolled(tmp_path)
  with held_scope(ws) as args:
    path = ws.instance / (".agentcfg-omp.lock" if target == "lock" else "user-home")
    old = path.with_name(path.name + "-saved")
    path.rename(old)
    if target == "lock":
      path.write_bytes(old.read_bytes())
      path.chmod(0o600)
    else:
      path.mkdir(mode=0o700)
      (path / ".rotom-resource.json").write_bytes((old / ".rotom-resource.json").read_bytes())
      (path / ".rotom-resource.json").chmod(0o600)
    with pytest.raises(Conflict):
      check(domain, args)


def test_missing_ready_domain_record_blocks_scope(tmp_path):
  from agentcfg.resource_protocol import encode
  ws, domain, anchor = enrolled(tmp_path)
  state = domain.snapshot()
  del state["resources"][anchor["native_home"]["resource_id"]]
  with Tree(domain.root) as tree:
    tree.replace("coordination.json", encode(state), expected=tree.read("coordination.json")[2])
  with held_scope(ws) as args, pytest.raises(Conflict):
    check(domain, args)


def test_claim_probe_is_readonly_and_treats_damaged_claim_as_occupied(tmp_path, monkeypatch):
  ws = workspace(tmp_path)
  assert scopes().scope_claim_exists(ws.instance) is False
  assert not ws.instance.parent.exists()
  claim = claim_path(ws)
  claim.parent.mkdir(mode=0o700, parents=True)
  claim.write_bytes(b"{damaged")
  claim.chmod(0o600)
  original = Tree.read
  def no_claim_body(tree, name, *args, **kwargs):
    assert tree.root != claim.parent, "存在性探测不得读取声明正文"
    return original(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", no_claim_body)
  assert scopes().scope_claim_exists(ws.instance) is True
  assert not ws.instance.exists()


@pytest.mark.parametrize("committed", [False, True])
def test_failed_anchor_publication_keeps_claim_and_blocks_retry(tmp_path, monkeypatch, committed):
  ws = workspace(tmp_path)
  domain = core.initialize_domain(tmp_path / "domain")
  original = Tree.write_new
  fired = []
  def inject(tree, name, data, *args, **kwargs):
    if name == ".rotom-resource.json" and not fired:
      assert claim_path(ws).exists(), "必须先持久化不可覆盖声明"
      fired.append(True)
      if committed:
        original(tree, name, data, *args, **kwargs)
      raise OSError("synthetic-anchor-publication-failure")
    return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "write_new", inject)
  with pytest.raises(Conflict):
    scopes().enroll_scope(domain, ws)
  assert fired and claim_path(ws).exists()
  saved = claim_path(ws).read_bytes()
  monkeypatch.setattr(Tree, "write_new", original)
  with pytest.raises(Conflict):
    scopes().enroll_scope(domain, ws)
  with pytest.raises(Conflict), omp_identity.lifecycle_guard(ws, create=True):
    pass
  assert claim_path(ws).read_bytes() == saved


def test_normal_legacy_instance_retains_lifecycle_compatibility(tmp_path):
  ws = make_workspace(tmp_path)
  assert scopes().scope_claim_exists(ws.instance) is False
  omp_identity.preflight_setup(ws)
  for flags in ({}, {"shared": True}, {"create": True}):
    with omp_identity.lifecycle_guard(ws, **flags):
      pass


def scoped_owner_case(root, selection=None):
  ws, domain, anchor = enrolled(root)
  cache = root / "cache"
  runtime = core.enroll_runtime(domain, cache, IDENTITY)
  resources = scope_ids(anchor) | {runtime["resource_id"]}
  reserve(domain, ws, sorted(resources if selection is None else selection(anchor, runtime)))
  return ws, domain, anchor, cache, runtime


def test_scope_three_resource_owner_attach_dispatch_release_chain(tmp_path, monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  ws, domain, anchor, cache, runtime = scoped_owner_case(tmp_path)
  with held_scope(ws, cache, runtime) as args:
    assert attach(domain, args) == RUN
    assert set(domain.snapshot()["reservations"][RUN]["resources"]) == scope_ids(anchor) | {runtime["resource_id"]}
    owners.dispatch_owner(domain, RUN, **args)
    observation = run_owners.ReleaseObservation(RUN, deepcopy(MANAGER), True, True)
    owners.finish_owner(domain, RUN, observation=observation, **args)
    assert check(domain, args) == scope_ids(anchor)
  assert domain.snapshot()["reservations"][RUN]["phase"] == "released"
  assert run_owners.Registry(ws.state_root / "run-owners", ws.binding).snapshot()[RUN]["lifecycle_state"] == "idle_confirmed"


@pytest.mark.parametrize("selection", ["runtime-only", "missing-home", "scope-only", "other-scope", "extra-scope"])
def test_owner_requires_exact_runtime_and_own_scope_without_owner_write(tmp_path, selection):
  ws, domain, anchor = enrolled(tmp_path)
  other = workspace(tmp_path, "omp-other")
  other_anchor = scopes().enroll_scope(domain, other)
  cache = tmp_path / "cache"
  runtime = core.enroll_runtime(domain, cache, IDENTITY)
  own = scope_ids(anchor)
  selected = {"runtime-only": {runtime["resource_id"]},
    "missing-home": {runtime["resource_id"], anchor["instance"]["resource_id"]},
    "scope-only": own,
    "other-scope": scope_ids(other_anchor) | {runtime["resource_id"]},
    "extra-scope": own | scope_ids(other_anchor) | {runtime["resource_id"]}}[selection]
  reserve(domain, ws, sorted(selected))
  before = domain.snapshot()
  with held_scope(ws, cache, runtime) as args, pytest.raises(Conflict):
    attach(domain, args)
  assert not owner_path(ws).exists()
  assert domain.snapshot() == before


@pytest.mark.parametrize("phase", ["dispatch", "release"])
def test_owner_operations_recheck_scope_evidence_before_mutation(tmp_path, monkeypatch, phase):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  ws, domain, anchor, cache, runtime = scoped_owner_case(tmp_path)
  with held_scope(ws, cache, runtime) as args:
    attach(domain, args)
    if phase == "release":
      owners.dispatch_owner(domain, RUN, **args)
    before, owner_before = domain.snapshot(), owner_path(ws).read_bytes()
    (ws.instance / "user-home/.rotom-resource.json").unlink()
    with pytest.raises(Conflict):
      if phase == "dispatch":
        owners.dispatch_owner(domain, RUN, **args)
      else:
        observed = run_owners.ReleaseObservation(RUN, deepcopy(MANAGER), True, True)
        owners.finish_owner(domain, RUN, observation=observed, **args)
    assert domain.snapshot() == before
    assert owner_path(ws).read_bytes() == owner_before


def test_claim_parent_chain_is_synced_before_resource_publication(tmp_path, monkeypatch):
  ws = workspace(tmp_path)
  domain = core.initialize_domain(tmp_path / "domain")
  original_sync, original_write = os.fsync, Tree.write_new
  synced, published = set(), []
  def fsync(fd):
    info = os.fstat(fd)
    synced.add((info.st_dev, info.st_ino))
    return original_sync(fd)
  def publish(tree, name, data, *args, **kwargs):
    if name == ".rotom-resource.json":
      assert claim_path(ws).exists()
      ancestor = ws.instance.parent
      while True:
        info = ancestor.stat()
        assert (info.st_dev, info.st_ino) in synced
        if ancestor == ancestor.parent:
          break
        ancestor = ancestor.parent
      published.append(name)
    return original_write(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(os, "fsync", fsync)
  monkeypatch.setattr(Tree, "write_new", publish)
  scopes().enroll_scope(domain, ws)
  assert len(published) == 2


@pytest.mark.parametrize("fault", ["directory-sync", "response-lost"])
def test_claim_publication_failure_keeps_claim_before_instance_creation(tmp_path, monkeypatch, fault):
  ws = workspace(tmp_path)
  domain = core.initialize_domain(tmp_path / "domain")
  original_write, original_sync = Tree.write_new, os.fsync
  fired = []
  def write_new(tree, name, data, *args, **kwargs):
    result = original_write(tree, name, data, *args, **kwargs)
    if fault == "response-lost" and tree.root == claim_path(ws).parent and not fired:
      fired.append(True)
      raise OSError("synthetic-claim-response-lost")
    return result
  def fsync(fd):
    if fault == "directory-sync" and claim_path(ws).exists() and not fired:
      info, parent = os.fstat(fd), claim_path(ws).parent.stat()
      if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
        fired.append(True)
        raise OSError("synthetic-claim-directory-sync-failure")
    return original_sync(fd)
  monkeypatch.setattr(Tree, "write_new", write_new)
  monkeypatch.setattr(os, "fsync", fsync)
  with pytest.raises(Conflict):
    scopes().enroll_scope(domain, ws)
  assert fired and claim_path(ws).is_file()
  assert not ws.instance.exists()
  saved = claim_path(ws).read_bytes()
  monkeypatch.setattr(Tree, "write_new", original_write)
  monkeypatch.setattr(os, "fsync", original_sync)
  with pytest.raises(Conflict):
    scopes().enroll_scope(domain, ws)
  with pytest.raises(Conflict), omp_identity.lifecycle_guard(ws, create=True):
    pass
  assert not ws.instance.exists()
  assert claim_path(ws).read_bytes() == saved
  assert domain.snapshot()["resources"] == {}


@pytest.mark.parametrize("committed", [False, True])
def test_final_domain_publication_failure_never_retries_or_overwrites_scope(tmp_path, monkeypatch, committed):
  ws = workspace(tmp_path)
  domain = core.initialize_domain(tmp_path / "domain")
  original = Tree.replace
  attempts = []
  def replace(tree, name, data, *args, **kwargs):
    if tree.root == domain.root and name == "coordination.json":
      attempts.append(name)
      if committed:
        original(tree, name, data, *args, **kwargs)
      raise OSError("synthetic-domain-publication-failure")
    return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict):
    scopes().enroll_scope(domain, ws)
  assert attempts == ["coordination.json"]
  paths = [claim_path(ws), ws.instance / ".rotom-resource.json",
    ws.instance / "user-home/.rotom-resource.json", ws.instance / ".agentcfg-omp.lock",
    ws.instance / ".agentcfg-omp-owner.json", domain.root / "coordination.json"]
  saved = {path: path.read_bytes() for path in paths}
  monkeypatch.setattr(Tree, "replace", original)
  with pytest.raises(Conflict):
    scopes().enroll_scope(domain, ws)
  with pytest.raises(Conflict), omp_identity.lifecycle_guard(ws, create=True):
    pass
  assert {path: path.read_bytes() for path in paths} == saved
  anchor = json.loads(saved[ws.instance / ".rotom-resource.json"])
  with held_scope(ws) as args:
    if committed:
      assert check(domain, args) == scope_ids(anchor)
    else:
      with pytest.raises(Conflict):
        check(domain, args)
  assert len(domain.snapshot()["resources"]) == (2 if committed else 0)
  assert {path: path.read_bytes() for path in paths} == saved


def test_guard_rechecks_claim_after_acquiring_instance_flock(tmp_path, monkeypatch):
  ws = make_workspace(tmp_path)
  original_flock, original_probe = fcntl.flock, scopes().scope_claim_exists
  lock_info = (ws.instance / ".agentcfg-omp.lock").stat()
  probes, injected = [], []
  before = (ws.instance / ".agentcfg-omp-owner.json").read_bytes()
  def probe(instance):
    result = original_probe(instance)
    probes.append(result)
    return result
  def flock(fd, operation):
    result = original_flock(fd, operation)
    info = os.fstat(fd)
    if not injected and (info.st_dev, info.st_ino) == (lock_info.st_dev, lock_info.st_ino):
      assert probes == [False], "首次存在性检查应早于实例锁"
      claim = claim_path(ws)
      claim.parent.mkdir(mode=0o700)
      claim.write_bytes(b"synthetic-concurrent-claim")
      claim.chmod(0o600)
      injected.append(True)
    return result
  monkeypatch.setattr(scopes(), "scope_claim_exists", probe)
  monkeypatch.setattr(fcntl, "flock", flock)
  with pytest.raises(Conflict), omp_identity.lifecycle_guard(ws, shared=True):
    pytest.fail("新增声明后不得向调用方交出旧实例租约")
  assert injected and probes == [False, True]
  assert (ws.instance / ".agentcfg-omp-owner.json").read_bytes() == before


@pytest.mark.parametrize("kind,damage", [("scope-claim", "bool"), ("scope-claim", "unknown"),
  ("scope-anchor", "bool"), ("scope-anchor", "unknown"), ("scope-anchor", "physical-digest")])
def test_scope_codec_rejects_ambiguous_or_forged_protocol_data(tmp_path, kind, damage):
  from agentcfg import resource_protocol
  ws, domain, anchor = enrolled(tmp_path)
  value = json.loads(claim_path(ws).read_bytes()) if kind == "scope-claim" else deepcopy(anchor)
  if damage == "bool":
    value["parent_physical"]["device"] = True
  elif damage == "unknown":
    value["synthetic_untrusted"] = "unrecognized"
  else:
    value["instance"]["key"]["key_id"] = "0" * 64
  if damage != "physical-digest":
    assert not resource_protocol._validators()[kind].is_valid(value)
  with pytest.raises(Conflict):
    resource_protocol.encode(value)
  with pytest.raises(Conflict):
    resource_protocol.decode(json.dumps(value).encode("utf8"), kind=kind)


def test_directory_anchors_block_legacy_downgrade_without_claim_or_nonempty_lock(tmp_path):
  ws, domain, anchor = enrolled(tmp_path)
  claim_path(ws).unlink()
  (ws.instance / ".agentcfg-omp.lock").write_bytes(b"")
  assert scopes().scope_claim_exists(ws.instance) is True
  for operation in ("preflight", "shared", "create"):
    with pytest.raises(Conflict):
      if operation == "preflight":
        omp_identity.preflight_setup(ws)
      else:
        with omp_identity.lifecycle_guard(ws, shared=operation == "shared", create=operation == "create"):
          pass
  for path in (ws.instance / ".rotom-resource.json", ws.instance / "user-home/.rotom-resource.json"):
    assert json.loads(path.read_bytes()) == anchor
  assert (ws.instance / ".agentcfg-omp.lock").read_bytes() == b""


@pytest.mark.parametrize("exclusive", [False, True])
def test_ordinary_runtime_guard_rejects_scoped_instance_before_creating_cache(tmp_path, exclusive):
  from agentcfg.omp_dependencies import OmpBackend
  ws, domain, anchor = enrolled(tmp_path)
  ws.cache = tmp_path / "legacy-cache"
  before = domain.snapshot()
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, IDENTITY, exclusive=exclusive):
    pass
  assert not ws.cache.exists()
  assert domain.snapshot() == before


@pytest.mark.parametrize("exclusive", [False, True])
def test_runtime_guard_rechecks_scope_claim_after_package_flock(tmp_path, monkeypatch, exclusive):
  from agentcfg.omp_dependencies import OmpBackend
  ws = make_workspace(tmp_path)
  ws.cache = tmp_path / "legacy-cache"
  original_flock, original_probe = fcntl.flock, scopes().scope_claim_exists
  probes, injected = [], []
  assert original_probe(ws.instance) is False
  before = (ws.instance / ".agentcfg-omp-owner.json").read_bytes()
  def probe(instance):
    result = original_probe(instance)
    probes.append(result)
    return result
  def flock(fd, operation):
    result = original_flock(fd, operation)
    lock = ws.cache / "leases" / (IDENTITY + ".lock")
    info, named = os.fstat(fd), lock.stat()
    if not injected and (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino):
      claim = claim_path(ws)
      claim.parent.mkdir(mode=0o700)
      claim.write_bytes(b"synthetic-claim-after-package-lock")
      claim.chmod(0o600)
      injected.append(True)
    return result
  monkeypatch.setattr(scopes(), "scope_claim_exists", probe)
  monkeypatch.setattr(fcntl, "flock", flock)
  yielded = False
  with pytest.raises(Conflict):
    with OmpBackend().runtime_guard(ws, IDENTITY, exclusive=exclusive):
      yielded = True
  assert not yielded and injected
  assert probes == [False, True]
  assert (ws.instance / ".agentcfg-omp-owner.json").read_bytes() == before


def test_scope_rechecks_owner_receipt_after_final_home_anchor_read(tmp_path, monkeypatch):
  ws, domain, anchor = enrolled(tmp_path)
  original = Tree.read
  checked, replaced = [], []
  owner = ws.instance / ".agentcfg-omp-owner.json"
  def read(tree, name, *args, **kwargs):
    result = original(tree, name, *args, **kwargs)
    if tree.root == ws.instance and name == ".agentcfg-omp-owner.json":
      checked.append(True)
    elif tree.root == ws.instance / "user-home" and name == ".rotom-resource.json" and checked and not replaced:
      receipt = json.loads(owner.read_bytes())
      receipt["owner_nonce"] = ("0" if receipt["owner_nonce"][0] != "0" else "1") + receipt["owner_nonce"][1:]
      owner.write_text(json.dumps(receipt))
      assert owner.stat().st_mode & 0o777 == 0o600
      replaced.append(True)
    return result
  with held_scope(ws) as args:
    monkeypatch.setattr(Tree, "read", read)
    with pytest.raises(Conflict):
      check(domain, args)
  assert checked and replaced
