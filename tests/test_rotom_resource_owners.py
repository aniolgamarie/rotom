"""内部关联机制的离线模型；真实临时 fd，不启动 OMP 或提供维护许可。"""

from contextlib import contextmanager, ExitStack
from copy import deepcopy
import fcntl
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import omp_identity, resource_coordination as core, resource_owners as owners
from agentcfg.run_owners import Registry
from agentcfg.storage import Conflict, Tree, ensure_private, instance_lock


RUN = "a" * 32
OP = "b" * 32
IDENTITY = "c" * 64
MANAGER = {"pid": 3133713, "birth_id": "synthetic-boot-birth"}


def make_workspace(root, profile="omp-a"):
  ws = SimpleNamespace(agent="omp", profile=profile, instance=root / "instances" / profile,
    state_root=root / "states" / profile,
    binding={"machine": "synthetic-machine", "local": str(root / "local.toml"), "profile": profile})
  with omp_identity.lifecycle_guard(ws, create=True):
    pass
  home = omp_identity.native_identity(profile, ws.instance).home
  home.mkdir(mode=0o700)
  return ws


def metadata(ws):
  return {"agent": "omp", "backend": "managed", "profile": ws.profile,
    "machine_ref": {key: ws.binding[key] for key in ("machine", "local")},
    "start_cwd": {"path": str(ws.instance.parent), "source": "launch-spec",
      "confirmation": "confirmed", "observed_at_ns": 1},
    "native_home_ref": {"kind": "omp-managed-home", "path": str(ws.instance / "user-home"),
      "source": "deployed-contract", "confirmation": "confirmed"},
    "deployed_identity": {"deployment": "d" * 64, "runtime": IDENTITY}, "coordination_domain": None}


def setup_case(root):
  ws = make_workspace(root)
  domain = core.initialize_domain(root / "domain")
  cache = root / "cache"
  anchor = core.enroll_runtime(domain, cache, IDENTITY)
  reserve(domain, ws, [anchor["resource_id"]])
  return ws, domain, cache, anchor


def reserve(domain, ws, resources, run=RUN, op=OP):
  domain.reserve(run_id=run, op_id=op,
    owner_ref={"state_root": str(ws.state_root), "binding": deepcopy(ws.binding)}, resources=resources)


@contextmanager
def held(ws, cache, anchor):
  with ExitStack() as stack:
    instance_fd = stack.enter_context(omp_identity.lifecycle_guard(ws, shared=True))
    ensure_private(ws.state_root)
    state = stack.enter_context(Tree(ws.state_root))
    stack.enter_context(instance_lock(state, shared=True))
    home = stack.enter_context(Tree(ws.instance / "user-home"))
    fd = os.open(cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR | os.O_NOFOLLOW)
    stack.callback(os.close, fd)
    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    yield {"workspace": ws, "instance_fd": instance_fd, "native_home_fd": home.fd,
      "runtime_fds": {anchor["resource_id"]: fd}}


def attach(domain, args, *, supplied=None, run=RUN):
  return owners.attach_owner(domain, run, manager_identity=MANAGER,
    metadata=metadata(args["workspace"]) if supplied is None else supplied, **args)


def owner_path(ws, run=RUN):
  return ws.state_root / "run-owners" / (run + ".json")


@pytest.mark.parametrize("mismatch", ["backend", "runtime"])
def test_attach_rejects_metadata_not_matching_selected_managed_runtime(tmp_path, mismatch):
  ws, domain, cache, anchor = setup_case(tmp_path)
  supplied = metadata(ws)
  if mismatch == "backend":
    supplied["backend"] = "unmanaged"
  else:
    supplied["deployed_identity"]["runtime"] = "f" * 64
  with held(ws, cache, anchor) as args, pytest.raises(Conflict):
    attach(domain, args, supplied=supplied)
  assert not owner_path(ws).exists()
  assert domain.snapshot()["reservations"][RUN]["phase"] == "reserved"


def test_same_run_bidirectional_binding_and_dispatch(tmp_path, monkeypatch):
  ws, domain, cache, anchor = setup_case(tmp_path)
  stages = []
  original = Tree.replace
  def replace(tree, name, data, *args, **kwargs):
    if name == "coordination.json":
      phase = json.loads(data)["reservations"].get(RUN, {}).get("phase")
      if phase in ("owner_pending", "owner_attached", "dispatched"):
        with Tree(ws.state_root / "run-owners") as independent:
          with pytest.raises(BlockingIOError):
            fcntl.flock(independent.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stages.append(phase)
    return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace)
  with held(ws, cache, anchor) as args:
    assert attach(domain, args) == RUN
    entry = domain.snapshot()["reservations"][RUN]
    record = Registry(ws.state_root / "run-owners", ws.binding).snapshot()[RUN]
    assert entry["phase"] == "owner_attached"
    assert entry["resources"] == [anchor["resource_id"]]
    assert record["run_id"] == entry["run_id"] == RUN
    assert record["protocol"]["control"] is None
    assert record["coordination_domain"]["op_id"] == OP
    assert record["coordination_domain"]["domain_id"] == domain.snapshot()["domain_id"]
    assert entry["owner_link"]["instance"]["path"] == str(ws.instance / ".agentcfg-omp.lock")
    assert entry["owner_link"]["native_home"]["path"] == str(ws.instance / "user-home")
    assert len(entry["owner_link"]["record_digest"]) == 64
    with pytest.raises(Conflict):
      domain.dispatch(RUN, lease_fds=args["runtime_fds"])
    with pytest.raises(Conflict):
      domain.cancel_reserved(RUN)
    owners.dispatch_owner(domain, RUN, **args)
  assert stages == ["owner_pending", "owner_attached", "dispatched"]
  assert domain.snapshot()["reservations"][RUN]["phase"] == "dispatched"


@pytest.mark.parametrize("fault", ["instance-missing", "home-missing", "instance-directory", "home-file", "runtime-missing", "runtime-extra", "runtime-wrong", "runtime-closed"])
def test_invalid_fds_do_not_write_owner(tmp_path, fault):
  ws, domain, cache, anchor = setup_case(tmp_path)
  with held(ws, cache, anchor) as args:
    bad = {**args, "runtime_fds": dict(args["runtime_fds"])}
    if fault == "instance-missing":
      bad["instance_fd"] = None
    elif fault == "home-missing":
      bad["native_home_fd"] = None
    elif fault == "instance-directory":
      bad["instance_fd"] = args["native_home_fd"]
    elif fault == "home-file":
      bad["native_home_fd"] = args["instance_fd"]
    elif fault == "runtime-missing":
      bad["runtime_fds"] = {}
    elif fault == "runtime-extra":
      bad["runtime_fds"]["e" * 32] = args["instance_fd"]
    elif fault == "runtime-wrong":
      bad["runtime_fds"][anchor["resource_id"]] = args["instance_fd"]
    else:
      closed = os.dup(next(iter(args["runtime_fds"].values())))
      os.close(closed)
      bad["runtime_fds"][anchor["resource_id"]] = closed
    with pytest.raises(Conflict):
      attach(domain, bad)
  assert not owner_path(ws).exists()
  assert domain.snapshot()["reservations"][RUN]["phase"] == "reserved"


@pytest.mark.parametrize("fault", ["profile", "machine", "local", "native-kind", "native-path", "agent", "coordination"])
def test_metadata_scope_mismatch_has_no_owner_write(tmp_path, fault):
  ws, domain, cache, anchor = setup_case(tmp_path)
  supplied = metadata(ws)
  if fault == "profile":
    supplied["profile"] = "omp-other"
  elif fault in ("machine", "local"):
    supplied["machine_ref"][fault] = "other" if fault == "machine" else str(tmp_path / "other.toml")
  elif fault == "native-kind":
    supplied["native_home_ref"]["kind"] = "dsh-home"
  elif fault == "native-path":
    supplied["native_home_ref"]["path"] = str(tmp_path / "other-home")
  elif fault == "agent":
    supplied["agent"] = "dsh"
  else:
    supplied["coordination_domain"] = {}
  with held(ws, cache, anchor) as args, pytest.raises(Conflict):
    attach(domain, args, supplied=supplied)
  assert not owner_path(ws).exists()
  assert domain.snapshot()["reservations"][RUN]["phase"] == "reserved"


@pytest.mark.parametrize("target", ["pending", "owner", "attached", "dispatch"])
@pytest.mark.parametrize("committed", [False, True])
def test_partial_publication_keeps_durable_blocking_phase(tmp_path, monkeypatch, target, committed):
  ws, domain, cache, anchor = setup_case(tmp_path)
  original_replace, original_write = Tree.replace, Tree.write_new
  fired = []
  phase_target = {"pending": "owner_pending", "attached": "owner_attached", "dispatch": "dispatched"}
  def inject(original, tree, name, data, *args, **kwargs):
    matches = (target == "owner" and name == RUN + ".json") or (
      target != "owner" and name == "coordination.json" and
      json.loads(data)["reservations"].get(RUN, {}).get("phase") == phase_target[target])
    if matches and not fired:
      fired.append(True)
      if committed:
        original(tree, name, data, *args, **kwargs)
      raise OSError("synthetic-private-write-failure")
    return original(tree, name, data, *args, **kwargs)
  with held(ws, cache, anchor) as args:
    if target == "dispatch":
      attach(domain, args)
    monkeypatch.setattr(Tree, "replace", lambda tree, name, data, *a, **kw: inject(original_replace, tree, name, data, *a, **kw))
    monkeypatch.setattr(Tree, "write_new", lambda tree, name, data, *a, **kw: inject(original_write, tree, name, data, *a, **kw))
    with pytest.raises(Conflict):
      if target == "dispatch":
        owners.dispatch_owner(domain, RUN, **args)
      else:
        attach(domain, args)
  assert fired
  expected = {"pending": "owner_pending" if committed else "reserved",
    "owner": "owner_pending", "attached": "owner_attached" if committed else "owner_pending",
    "dispatch": "dispatched" if committed else "owner_attached"}[target]
  assert domain.snapshot()["reservations"][RUN]["phase"] == expected
  assert owner_path(ws).exists() == (target in ("attached", "dispatch") or (target == "owner" and committed))
  if expected != "reserved":
    with pytest.raises(Conflict):
      domain.cancel_reserved(RUN)
  fd = os.open(cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True)
  finally:
    os.close(fd)


@pytest.mark.parametrize("replacement", ["lock", "home", "instance", "registry", "receipt", "runtime"])
def test_dispatch_rechecks_named_physical_and_ownership_evidence(tmp_path, replacement):
  ws, domain, cache, anchor = setup_case(tmp_path)
  with held(ws, cache, anchor) as args:
    attach(domain, args)
    if replacement == "receipt":
      path = ws.instance / ".agentcfg-omp-owner.json"
      value = json.loads(path.read_bytes())
      value["owner_nonce"] = "e" * 32
      path.write_text(json.dumps(value))
    else:
      path = {"lock": ws.instance / ".agentcfg-omp.lock", "home": ws.instance / "user-home",
        "instance": ws.instance, "registry": ws.state_root / "run-owners",
        "runtime": cache / "leases" / (IDENTITY + ".lock")}[replacement]
      old = path.with_name(path.name + "-old")
      path.rename(old)
      if replacement in ("lock", "runtime"):
        path.write_bytes(old.read_bytes())
        path.chmod(0o600)
      else:
        path.mkdir(mode=0o700)
        if replacement == "registry":
          (path / (RUN + ".json")).write_bytes((old / (RUN + ".json")).read_bytes())
        elif replacement == "instance":
          for name in (".agentcfg-omp.lock", ".agentcfg-omp-owner.json"):
            (path / name).write_bytes((old / name).read_bytes())
          (path / "user-home").mkdir(mode=0o700)
    with pytest.raises(Conflict):
      owners.dispatch_owner(domain, RUN, **args)
  assert domain.snapshot()["reservations"][RUN]["phase"] == "owner_attached"


def test_shared_runtime_retains_separate_instance_owners_and_unknown_blocks_empty_registry(tmp_path):
  ws, domain, cache, anchor = setup_case(tmp_path)
  other = make_workspace(tmp_path, "omp-b")
  second_run = "e" * 32
  reserve(domain, other, [anchor["resource_id"]], run=second_run, op="f" * 32)
  for workspace, run in ((ws, RUN), (other, second_run)):
    with held(workspace, cache, anchor) as args:
      attach(domain, args, run=run)
  one, two = (domain.snapshot()["reservations"][run] for run in (RUN, second_run))
  assert one["resources"] == two["resources"]
  assert one["owner_link"]["instance"]["key"] != two["owner_link"]["instance"]["key"]
  assert set(Registry(ws.state_root / "run-owners", ws.binding).snapshot()) == {RUN}
  assert set(Registry(other.state_root / "run-owners", other.binding).snapshot()) == {second_run}
  domain.mark_unknown(RUN)
  empty = make_workspace(tmp_path, "omp-empty")
  assert Registry(empty.state_root / "run-owners", empty.binding).snapshot() == {}
  fd = os.open(cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True)
  finally:
    os.close(fd)
  with pytest.raises(Conflict):
    domain.cancel_reserved(RUN)


def test_existing_owner_id_is_never_overwritten(tmp_path, monkeypatch):
  ws, domain, cache, anchor = setup_case(tmp_path)
  from agentcfg import run_owners
  monkeypatch.setattr(run_owners.uuid, "uuid4", lambda: SimpleNamespace(hex=RUN))
  Registry(ws.state_root / "run-owners", ws.binding).register_v2(MANAGER, metadata(ws))
  before = owner_path(ws).read_bytes()
  with held(ws, cache, anchor) as args, pytest.raises(Conflict):
    attach(domain, args)
  assert owner_path(ws).read_bytes() == before
  assert domain.snapshot()["reservations"][RUN]["phase"] == "reserved"


def test_ordinary_register_cannot_forge_coordination_domain(tmp_path):
  ws, domain, cache, anchor = setup_case(tmp_path)
  with held(ws, cache, anchor) as args:
    attach(domain, args)
  record = Registry(ws.state_root / "run-owners", ws.binding).snapshot()[RUN]
  supplied = metadata(ws)
  supplied["coordination_domain"] = record["coordination_domain"]
  with pytest.raises(Conflict):
    Registry(ws.state_root / "run-owners", ws.binding).register_v2(MANAGER, supplied)
  assert set(Registry(ws.state_root / "run-owners", ws.binding).snapshot()) == {RUN}


def test_owner_lock_busy_is_nonblocking_and_has_no_publication(tmp_path, monkeypatch):
  ws, domain, cache, anchor = setup_case(tmp_path)
  registry = Registry(ws.state_root / "run-owners", ws.binding)
  with registry._locked(create=True):
    pass
  original = fcntl.flock
  attempts = []
  with held(ws, cache, anchor) as args, Tree(registry.root) as busy:
    original(busy.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    physical = os.fstat(busy.fd)
    def flock(fd, operation):
      info = os.fstat(fd)
      if (info.st_dev, info.st_ino) == (physical.st_dev, physical.st_ino) and fd != busy.fd:
        assert operation & fcntl.LOCK_NB, "owner contender must never wait under coordination EX"
        attempts.append(operation)
      return original(fd, operation)
    monkeypatch.setattr(fcntl, "flock", flock)
    with pytest.raises(Conflict):
      attach(domain, args)
  assert attempts and not owner_path(ws).exists()


def test_omp_owner_rejects_multiple_runtime_resources(tmp_path):
  ws, domain, cache, anchor = setup_case(tmp_path)
  other_cache = tmp_path / "other-cache"
  other = core.enroll_runtime(domain, other_cache, IDENTITY)
  run = "e" * 32
  reserve(domain, ws, [anchor["resource_id"], other["resource_id"]], run=run, op="f" * 32)
  with held(ws, cache, anchor) as args:
    fd = os.open(other_cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR)
    try:
      fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
      args["runtime_fds"][other["resource_id"]] = fd
      with pytest.raises(Conflict):
        attach(domain, args, run=run)
    finally:
      os.close(fd)
  assert not owner_path(ws, run).exists()


@pytest.mark.parametrize("field", ["state_root", "machine", "local", "profile"])
def test_reservation_owner_scope_must_match_workspace(tmp_path, field):
  ws = make_workspace(tmp_path)
  domain = core.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  anchor = core.enroll_runtime(domain, cache, IDENTITY)
  reference = {"state_root": str(ws.state_root), "binding": deepcopy(ws.binding)}
  if field == "state_root":
    reference[field] = str(tmp_path / "other-state")
  else:
    reference["binding"][field] = str(tmp_path / "other-local") if field == "local" else "other"
  domain.reserve(run_id=RUN, op_id=OP, owner_ref=reference, resources=[anchor["resource_id"]])
  with held(ws, cache, anchor) as args, pytest.raises(Conflict):
    attach(domain, args)
  assert not owner_path(ws).exists()


@pytest.mark.parametrize("damage", ["unknown-field", "record-digest", "ownership-digest", "key-digest", "missing-link", "reserved-link", "cancelled-link"])
def test_malformed_or_inconsistent_owner_link_cannot_authorize_dispatch(tmp_path, damage):
  from agentcfg.resource_protocol import encode
  ws, domain, cache, anchor = setup_case(tmp_path)
  with held(ws, cache, anchor) as args:
    attach(domain, args)
    state = domain.snapshot()
    entry = state["reservations"][RUN]
    if damage == "unknown-field":
      entry["owner_link"]["synthetic_untrusted"] = True
    elif damage == "record-digest":
      entry["owner_link"]["record_digest"] = "e" * 64
    elif damage == "ownership-digest":
      entry["owner_link"]["ownership_digest"] = "e" * 64
    elif damage == "key-digest":
      entry["owner_link"]["instance"]["key"]["key_id"] = "e" * 64
    elif damage == "missing-link":
      del entry["owner_link"]
    else:
      entry["phase"] = damage.split("-")[0]
    if damage in ("record-digest", "ownership-digest"):
      # 结构合法的伪造摘要仍须被双向证据复核拒绝。
      with Tree(tmp_path / "domain") as tree:
        tree.replace("coordination.json", encode(state), expected=tree.read("coordination.json")[2])
      with pytest.raises(Conflict):
        owners.dispatch_owner(domain, RUN, **args)
    else:
      with pytest.raises(Conflict):
        encode(state)


def test_owner_idle_alone_never_releases_domain_reservation(tmp_path):
  from agentcfg.run_owners import ReleaseObservation
  ws, domain, cache, anchor = setup_case(tmp_path)
  registry = Registry(ws.state_root / "run-owners", ws.binding)
  with held(ws, cache, anchor) as args:
    attach(domain, args)
    # 仅合成完整观察测试单边记录变化；没有真实 native/core 释放证据。
    registry.finish_current(RUN, MANAGER, ReleaseObservation(RUN, deepcopy(MANAGER), True, True))
    assert registry.snapshot()[RUN]["lifecycle_state"] == "idle_confirmed"
    with pytest.raises(Conflict):
      owners.dispatch_owner(domain, RUN, **args)
  fd = os.open(cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True)
  finally:
    os.close(fd)
  assert domain.snapshot()["reservations"][RUN]["phase"] == "owner_attached"
