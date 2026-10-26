"""v1/v2主运行记账；只用合成身份和临时私人目录，不探测PID或执行宿主。"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agentcfg import run_owners as owners
from agentcfg.storage import Conflict, Tree


FIXTURES = Path(__file__).parent / "fixtures/rotom"
MANAGER = {"pid": 13371337, "birth_id": "linux:00000000-0000-4000-8000-000000000001:111"}
REUSED = {**MANAGER, "birth_id": "linux:00000000-0000-4000-8000-000000000001:222"}
RUN_ID = "a" * 32
V2_KEYS = {"schema_version", "binding_digest", "run_id", "manager_identity", "host_identity", "agent",
  "backend", "profile", "machine_ref", "start_cwd", "session_cwd", "native_home_ref", "deployed_identity",
  "lifecycle_state", "affected_resources", "process_observation", "session_observation", "terminal_ref", "protocol",
  "coordination_domain"}


def forbidden(*args, **kwargs):
  pytest.fail("real process identity probing is forbidden")


@pytest.fixture(autouse=True)
def no_process_identity_probe(monkeypatch):
  monkeypatch.setattr(owners, "current_process_identity", forbidden)


@pytest.fixture
def frozen_reader(monkeypatch):
  name = "agentcfg._frozen_run_owners_v1"
  spec = importlib.util.spec_from_file_location(name, FIXTURES / "run-record-v1.py")
  module = importlib.util.module_from_spec(spec)
  monkeypatch.setitem(sys.modules, name, module)
  spec.loader.exec_module(module)
  monkeypatch.setattr(module, "current_process_identity", forbidden)
  return module


@pytest.fixture
def store(tmp_path):
  local = tmp_path / "machine.toml"
  native = tmp_path / "native-home"
  cwd = tmp_path / "project"
  native.mkdir(mode=0o700)
  cwd.mkdir(mode=0o700)
  binding = {"machine": "workstation", "local": str(local), "profile": "dsh-default"}
  registry = owners.Registry(tmp_path / "run-owners", binding)
  metadata = {"agent": "dsh", "backend": "managed", "profile": "dsh-default",
    "machine_ref": {"machine": "workstation", "local": str(local)},
    "start_cwd": {"path": str(cwd), "source": "launch-spec", "confirmation": "confirmed", "observed_at_ns": 1},
    "native_home_ref": {"kind": "dsh-home", "path": str(native), "source": "deployed-contract", "confirmation": "confirmed"},
    "deployed_identity": {"deployment": "b" * 64, "runtime": "c" * 64}, "coordination_domain": None}
  return SimpleNamespace(registry=registry, metadata=metadata, binding=binding, native=native, cwd=cwd)


def v2_record(store):
  return {"schema_version": 2, "binding_digest": store.registry.binding_digest, "run_id": RUN_ID,
    "manager_identity": deepcopy(MANAGER), "host_identity": None, **deepcopy(store.metadata),
    "session_cwd": None, "lifecycle_state": "active", "affected_resources": ["instance", "runtime", "native-home"],
    "process_observation": {"kind": "manager_registered", "coverage": "unknown", "source": "manager-registration",
      "observed_at_ns": 2, "manager_identity": deepcopy(MANAGER), "host_identity": None},
    "session_observation": None, "terminal_ref": None, "protocol": {"registration": 2, "control": None}}


def write_record(store, record=None, *, payload=None):
  store.registry.root.mkdir(mode=0o700, exist_ok=True)
  path = store.registry.root / (RUN_ID + ".json")
  path.write_text(payload if payload is not None else json.dumps(record), encoding="utf-8")
  path.chmod(0o600)
  return path


def state(record):
  return record["lifecycle_state" if record["schema_version"] == 2 else "state"]


def register(store, version):
  if version == 1:
    return store.registry.register(deepcopy(MANAGER), session_ref="opaque-synthetic-session")
  return store.registry.register_v2(deepcopy(MANAGER), deepcopy(store.metadata))


def release(run_id, **changes):
  values = {"run_id": run_id, "manager_identity": deepcopy(MANAGER), "all_related_exited": True, "complete": True}
  values.update(changes)
  return owners.ReleaseObservation(**values)


def record_bytes(store):
  return {path.name: path.read_bytes() for path in store.registry.root.glob("*.json")}


def test_frozen_reader_is_exact_pre_v2_source_snapshot():
  metadata = json.loads((FIXTURES / "run-record-v1-source.json").read_text())
  assert metadata["source"] == "src/agentcfg/run_owners.py"
  assert hashlib.sha256((FIXTURES / "run-record-v1.py").read_bytes()).hexdigest() == metadata["sha256"]


def test_valid_v1_is_read_by_current_and_actual_old_reader_without_rewrite(store, frozen_reader, sentinel_factory):
  old = frozen_reader.Registry(store.registry.root, store.binding)
  run_id = old.register(deepcopy(MANAGER), session_ref="opaque-synthetic-session")
  snapshot = sentinel_factory(store.registry.root)
  assert store.registry.snapshot() == old.snapshot()
  assert store.registry.snapshot()[run_id]["schema_version"] == 1
  snapshot.assert_unchanged()


def test_mixed_v1_v2_snapshot_is_strict_readonly_and_old_reader_rejects_v2(store, frozen_reader, sentinel_factory):
  legacy = store.registry.register(deepcopy(MANAGER))
  write_record(store, v2_record(store))
  snapshot = sentinel_factory(store.registry.root)
  records = store.registry.snapshot()
  assert set(records) == {legacy, RUN_ID}
  assert records[legacy]["schema_version"] == 1 and records[RUN_ID] == v2_record(store)
  with pytest.raises(Conflict):
    frozen_reader.Registry(store.registry.root, store.binding).snapshot()
  snapshot.assert_unchanged()


def test_frozen_v1_reader_rejects_a_v2_file_without_modifying_it(store, frozen_reader, sentinel_factory):
  write_record(store, v2_record(store))
  snapshot = sentinel_factory(store.registry.root)
  with pytest.raises(Conflict):
    frozen_reader.Registry(store.registry.root, store.binding).snapshot()
  snapshot.assert_unchanged()


def test_register_v2_records_only_supplied_metadata_and_unknown_native_facts(store):
  metadata = deepcopy(store.metadata)
  run_id = store.registry.register_v2(deepcopy(MANAGER), metadata)
  assert len(run_id) == 32 and all(char in "0123456789abcdef" for char in run_id)
  record = store.registry.snapshot()[run_id]
  assert set(record) == V2_KEYS and record["schema_version"] == 2
  assert record["run_id"] == run_id and record["binding_digest"] == store.registry.binding_digest
  assert record["manager_identity"] == MANAGER and record["host_identity"] is None
  assert record["session_cwd"] is record["session_observation"] is record["terminal_ref"] is None
  assert record["coordination_domain"] is None and record["protocol"] == {"registration": 2, "control": None}
  assert record["lifecycle_state"] == "active" and record["affected_resources"] == ["instance", "runtime", "native-home"]
  observation = record["process_observation"]
  assert set(observation) == {"kind", "coverage", "source", "observed_at_ns", "manager_identity", "host_identity"}
  assert observation["kind"] == "manager_registered" and observation["coverage"] == "unknown"
  assert observation["source"] == "manager-registration" and observation["manager_identity"] == MANAGER
  assert observation["host_identity"] is None and type(observation["observed_at_ns"]) is int and observation["observed_at_ns"] > 0
  for key, value in store.metadata.items():
    assert record[key] == value
  metadata["start_cwd"]["path"] = "/not-the-recorded-cwd"
  assert record["start_cwd"] == store.metadata["start_cwd"]
  assert not Path(record["machine_ref"]["local"]).exists()


def at(value, keys):
  for key in keys:
    value = value[key]
  return value


LEVELS = [(), ("manager_identity",), ("machine_ref",), ("start_cwd",), ("native_home_ref",),
  ("deployed_identity",), ("process_observation",), ("process_observation", "manager_identity"), ("protocol",)]


@pytest.mark.parametrize("keys", LEVELS)
def test_unknown_fields_at_every_v2_object_level_fail_without_rewrite(store, keys, sentinel_factory):
  record = v2_record(store)
  at(record, keys)["unknown"] = "rejected"
  write_record(store, record)
  snapshot = sentinel_factory(store.registry.root)
  with pytest.raises(Conflict):
    store.registry.snapshot()
  snapshot.assert_unchanged()


@pytest.mark.parametrize("keys", LEVELS)
def test_duplicate_fields_at_every_v2_object_level_rejected(store, keys):
  record = v2_record(store)
  target = at(record, keys)
  key = next(iter(target))
  encoded = json.dumps(record, separators=(",", ":"))
  fragment = json.dumps(target, separators=(",", ":"))
  duplicate = "{" + json.dumps(key) + ":" + json.dumps(target[key], separators=(",", ":")) + "," + fragment[1:]
  write_record(store, payload=encoded.replace(fragment, duplicate, 1))
  with pytest.raises(Conflict):
    store.registry.snapshot()


@pytest.mark.parametrize("version", [0, 3, True, 2.0, "2", None])
def test_unknown_and_inexact_record_versions_rejected(store, version):
  record = v2_record(store)
  record["schema_version"] = version
  write_record(store, record)
  with pytest.raises(Conflict):
    store.registry.snapshot()


@pytest.mark.parametrize("keys", [("manager_identity", "pid"), ("start_cwd", "observed_at_ns"),
  ("process_observation", "observed_at_ns"), ("protocol", "registration")])
@pytest.mark.parametrize("value", [True, 2.0, float("nan"), float("inf"), float("-inf")])
def test_v2_integer_fields_reject_bool_float_and_nonfinite(store, keys, value):
  record = v2_record(store)
  at(record, keys[:-1])[keys[-1]] = value
  write_record(store, record)
  with pytest.raises(Conflict):
    store.registry.snapshot()


@pytest.mark.parametrize("damage", ["file-mode", "file-link", "hardlink", "root-mode", "root-link"])
def test_record_source_requires_private_regular_owned_files(store, tmp_path, damage):
  path = write_record(store, v2_record(store))
  if damage == "file-mode":
    path.chmod(0o644)
  elif damage in ("file-link", "hardlink"):
    target = tmp_path / "record.json"
    path.rename(target)
    path.symlink_to(target) if damage == "file-link" else path.hardlink_to(target)
  elif damage == "root-mode":
    store.registry.root.chmod(0o755)
  else:
    target = tmp_path / "moved-records"
    store.registry.root.rename(target)
    store.registry.root.symlink_to(target, target_is_directory=True)
  with pytest.raises(Conflict):
    store.registry.snapshot()


def test_historical_record_read_does_not_require_old_cwd_or_native_home_to_exist(store, sentinel_factory):
  write_record(store, v2_record(store))
  store.native.rmdir()
  store.cwd.rmdir()
  snapshot = sentinel_factory(store.registry.root)
  assert store.registry.snapshot()[RUN_ID]["native_home_ref"]["path"] == str(store.native)
  snapshot.assert_unchanged()


@pytest.mark.parametrize("field,bad", [
  ("agent", "dsh;unsafe"), ("backend", "managed\ncommand"), ("profile", "x" * 512),
  ("coordination_domain", {"control": "forged"}), ("extra", "unknown"),
])
def test_registration_rejects_invalid_metadata_without_erasing_old_owner(store, field, bad):
  old = store.registry.register(deepcopy(MANAGER))
  before = record_bytes(store)
  metadata = deepcopy(store.metadata)
  metadata[field] = bad
  with pytest.raises(Conflict):
    store.registry.register_v2(deepcopy(MANAGER), metadata)
  assert record_bytes(store) == before and store.registry.snapshot()[old]["state"] == "active"


@pytest.mark.parametrize("key", ["agent", "backend", "profile", "machine_ref", "start_cwd", "native_home_ref", "deployed_identity", "coordination_domain"])
def test_registration_cannot_guess_missing_metadata(store, key):
  metadata = deepcopy(store.metadata)
  del metadata[key]
  with pytest.raises(Conflict):
    store.registry.register_v2(deepcopy(MANAGER), metadata)


@pytest.mark.parametrize("damage", ["relative", "kind", "link", "permissions", "absent"])
def test_registration_checks_safe_existing_native_home_without_following_links(store, tmp_path, damage):
  metadata = deepcopy(store.metadata)
  if damage == "relative": metadata["native_home_ref"]["path"] = "relative/native-home"
  elif damage == "kind": metadata["native_home_ref"]["kind"] = "generic-home"
  elif damage == "link":
    link = tmp_path / "native-link"
    link.symlink_to(store.native, target_is_directory=True)
    metadata["native_home_ref"]["path"] = str(link)
  elif damage == "permissions": store.native.chmod(0o755)
  else: store.native.rmdir()
  with pytest.raises(Conflict):
    store.registry.register_v2(deepcopy(MANAGER), metadata)


@pytest.mark.parametrize("version", [1, 2])
def test_unknown_manager_scope_is_not_host_exit_or_automatic_idle(store, version, sentinel_factory):
  run_id = register(store, version)
  store.registry.mark_unknown(run_id, deepcopy(MANAGER))
  snapshot = sentinel_factory(store.registry.root)
  records = store.registry.snapshot()
  assert state(records[run_id]) == "unknown"
  if version == 2:
    assert records[run_id]["host_identity"] is None
    assert records[run_id]["process_observation"]["coverage"] == "unknown"
  with pytest.raises(Conflict): store.registry.assert_inactive()
  snapshot.assert_unchanged()


@pytest.mark.parametrize("version", [1, 2])
def test_pid_reuse_birth_mismatch_cannot_mark_or_finish_another_owner(store, version):
  run_id = register(store, version)
  before = record_bytes(store)
  with pytest.raises(Conflict): store.registry.mark_unknown(run_id, deepcopy(REUSED))
  with pytest.raises(Conflict): store.registry.finish_current(run_id, deepcopy(REUSED), release(run_id, manager_identity=REUSED))
  assert record_bytes(store) == before and state(store.registry.snapshot()[run_id]) == "active"


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("invalid", ["dict", "namespace", "subclass", "incomplete", "not-exited", "truthy", "wrong-run", "wrong-birth"])
def test_finish_requires_exact_complete_same_identity_release_observation(store, version, invalid):
  run_id = register(store, version)
  before = record_bytes(store)
  observation = release(run_id)
  if invalid == "dict": observation = dict(vars(observation))
  elif invalid == "namespace": observation = SimpleNamespace(**vars(observation))
  elif invalid == "subclass":
    class Untrusted(owners.ReleaseObservation): pass
    observation = Untrusted(**vars(observation))
  elif invalid == "incomplete": observation = release(run_id, complete=False)
  elif invalid == "not-exited": observation = release(run_id, all_related_exited=False)
  elif invalid == "truthy": observation = release(run_id, all_related_exited=1, complete=1)
  elif invalid == "wrong-run": observation = release("f" * 32)
  else: observation = release(run_id, manager_identity=REUSED)
  with pytest.raises(Conflict): store.registry.finish_current(run_id, deepcopy(MANAGER), observation)
  assert record_bytes(store) == before


@pytest.mark.parametrize("version", [1, 2])
def test_complete_release_only_finishes_current_active_owner_and_keeps_version(store, version):
  old = store.registry.register(deepcopy(MANAGER))
  store.registry.mark_unknown(old, deepcopy(MANAGER))
  old_bytes = record_bytes(store)[old + ".json"]
  current = register(store, version)
  store.registry.finish_current(current, deepcopy(MANAGER), release(current))
  records = store.registry.snapshot()
  assert state(records[current]) == "idle_confirmed" and records[current]["schema_version"] == version
  assert state(records[old]) == "unknown" and record_bytes(store)[old + ".json"] == old_bytes
  with pytest.raises(Conflict): store.registry.assert_inactive()
  with pytest.raises(Conflict): store.registry.finish_current(old, deepcopy(MANAGER), release(old))


@pytest.mark.parametrize("version", [1, 2])
def test_reconcile_requires_explicit_physical_ex_and_complete_same_identity_proof(store, version):
  run_id = register(store, version)
  store.registry.mark_unknown(run_id, deepcopy(MANAGER))
  events = []
  @contextmanager
  def physical_ex():
    events.append("physical-ex")
    yield
    events.append("released")
  def observe(record):
    assert events == ["physical-ex"] and state(record) == "unknown"
    return release(run_id)
  with pytest.raises(Conflict): store.registry.reconcile(run_id, maintenance_guard=None, observe=observe)
  result = store.registry.reconcile(run_id, maintenance_guard=physical_ex(), observe=observe)
  assert state(result) == "idle_confirmed" and result["schema_version"] == version
  assert events == ["physical-ex", "released"]
  store.registry.assert_inactive()


@pytest.mark.parametrize("operation", ["register", "mark-unknown", "finish"])
def test_failed_v2_accounting_preserves_old_active_unknown_records(store, monkeypatch, operation):
  old = store.registry.register(deepcopy(MANAGER))
  store.registry.mark_unknown(old, deepcopy(MANAGER))
  current = register(store, 2)
  before = record_bytes(store)
  def fail(*args, **kwargs): raise OSError("synthetic accounting failure")
  if operation == "register":
    monkeypatch.setattr(Tree, "write_new", fail)
    invoke = lambda: register(store, 2)
  else:
    monkeypatch.setattr(Tree, "replace", fail)
    invoke = (lambda: store.registry.mark_unknown(current, deepcopy(MANAGER))) if operation == "mark-unknown" else (
      lambda: store.registry.finish_current(current, deepcopy(MANAGER), release(current)))
  with pytest.raises(Conflict): invoke()
  assert record_bytes(store) == before
  records = store.registry.snapshot()
  assert state(records[old]) == "unknown" and state(records[current]) == "active"


@pytest.mark.parametrize("keys,bad", [
  (("protocol", "control"), {"stop": True}),
  (("coordination_domain",), {"id": "forged-capability"}),
  (("deployed_identity", "runtime"), "not-a-digest"),
  (("machine_ref", "machine"), "unsafe;machine"),
  (("machine_ref", "local"), "relative.toml"),
  (("start_cwd", "path"), "relative/project"),
  (("start_cwd", "source"), None),
  (("start_cwd", "confirmation"), True),
  (("start_cwd", "observed_at_ns"), 0),
  (("native_home_ref", "kind"), "generic-home"),
  (("native_home_ref", "source"), None),
  (("process_observation", "coverage"), "complete"),
  (("process_observation", "manager_identity"), REUSED),
  (("host_identity",), True),
  (("manager_identity", "birth_id"), ""),
  (("manager_identity", "birth_id"), "unsafe\0birth"),
  (("affected_resources",), ["instance"]),
])
def test_serialized_v2_cannot_forge_capabilities_identity_or_guessed_sources(store, keys, bad):
  record = v2_record(store)
  at(record, keys[:-1])[keys[-1]] = deepcopy(bad)
  write_record(store, record)
  with pytest.raises(Conflict):
    store.registry.snapshot()


@pytest.mark.parametrize("keys", [("start_cwd", "source"), ("start_cwd", "confirmation"),
  ("start_cwd", "observed_at_ns"), ("native_home_ref", "source"),
  ("native_home_ref", "confirmation"), ("deployed_identity", "runtime")])
def test_registration_requires_nested_source_identity_without_guessing(store, keys):
  metadata = deepcopy(store.metadata)
  del at(metadata, keys[:-1])[keys[-1]]
  with pytest.raises(Conflict):
    store.registry.register_v2(deepcopy(MANAGER), metadata)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("invalid", ["untyped", "incomplete", "wrong-birth"])
def test_reconcile_incomplete_observation_cannot_clear_unknown_owner(store, version, invalid):
  run_id = register(store, version)
  store.registry.mark_unknown(run_id, deepcopy(MANAGER))
  before = record_bytes(store)
  result = (SimpleNamespace(**vars(release(run_id))) if invalid == "untyped" else
    release(run_id, complete=False) if invalid == "incomplete" else release(run_id, manager_identity=REUSED))
  @contextmanager
  def physical_ex():
    yield
  with pytest.raises(Conflict):
    store.registry.reconcile(run_id, maintenance_guard=physical_ex(), observe=lambda record: result)
  assert record_bytes(store) == before and state(store.registry.snapshot()[run_id]) == "unknown"


def public_record_validator():
  from jsonschema import Draft202012Validator
  path = Path(__file__).resolve().parents[1] / "schemas/rotom/run-record.schema.json"
  return Draft202012Validator(json.loads(path.read_text()))


@pytest.mark.parametrize("legacy_fields", ["extra", "long-birth", "both"])
def test_v1_extra_identity_and_long_birth_remain_valid_in_public_schema_and_both_readers(store, frozen_reader, sentinel_factory, legacy_fields):
  manager = deepcopy(MANAGER)
  if legacy_fields in ("extra", "both"):
    manager["namespace"] = 1
  if legacy_fields in ("long-birth", "both"):
    manager["birth_id"] += "x" * 600
  run_id = store.registry.register(manager)
  snapshot = sentinel_factory(store.registry.root)
  record = store.registry.snapshot()[run_id]
  assert record["schema_version"] == 1 and record["manager_identity"] == manager
  old = frozen_reader.Registry(store.registry.root, store.binding)
  assert old.snapshot()[run_id] == record
  public_record_validator().validate(record)
  snapshot.assert_unchanged()


def final_session_record(store, lifecycle):
  record = v2_record(store)
  record["lifecycle_state"] = lifecycle
  kind, coverage, source = {"active": ("manager_registered", "unknown", "manager-registration"),
    "unknown": ("manager_scope_ended", "unknown", "manager-scope-end"),
    "idle_confirmed": ("complete_release", "complete", "kernel-release")}[lifecycle]
  record["process_observation"].update(kind=kind, coverage=coverage, source=source)
  record["session_observation"] = {"session": {"agent": record["agent"], "backend": record["backend"],
    "native_home_ref": owners.native_home_key(record["native_home_ref"]), "native_ref": "synthetic-session"},
    "run_id": record["run_id"], "emitter_epoch": "synthetic-emitter", "sequence": 1,
    "confirmation": "final", "source": "synthetic-final-observation", "observed_at_ns": 3}
  return record


@pytest.mark.parametrize("lifecycle", ["active", "unknown"])
@pytest.mark.parametrize("reader", ["registry", "schema"])
def test_active_or_unknown_cannot_claim_final_session_even_with_matching_scope(store, lifecycle, reader, sentinel_factory):
  from jsonschema.exceptions import ValidationError
  record = final_session_record(store, lifecycle)
  write_record(store, record)
  snapshot = sentinel_factory(store.registry.root)
  if reader == "registry":
    with pytest.raises(Conflict):
      store.registry.snapshot()
  else:
    with pytest.raises(ValidationError):
      public_record_validator().validate(record)
  snapshot.assert_unchanged()


def test_idle_complete_release_final_session_is_structurally_readable_without_native_acceptance_claim(store, sentinel_factory):
  # 合成历史元数据只证明结构可读，不证明任何真实会话已停止/切换/恢复。
  record = final_session_record(store, "idle_confirmed")
  write_record(store, record)
  snapshot = sentinel_factory(store.registry.root)
  public_record_validator().validate(record)
  assert store.registry.snapshot()[RUN_ID] == record
  assert record["host_identity"] is record["terminal_ref"] is record["coordination_domain"] is None
  assert record["protocol"]["control"] is None
  snapshot.assert_unchanged()


def test_expanded_v2_validator_matches_public_schema_for_nested_valid_and_invalid_data(store):
  public = public_record_validator()
  optimized = owners._record_validator(2)
  final = final_session_record(store, "idle_confirmed")
  hosted = deepcopy(final)
  hosted["host_identity"] = {"identity": {"pid": 5678, "birth_id": "synthetic-host"},
    "manager_identity": deepcopy(MANAGER), "source": "synthetic-public-event",
    "relationship": "reported-by-current-run"}
  hosted["process_observation"]["host_identity"] = deepcopy(hosted["host_identity"])
  def paths(value, prefix=()):
    if isinstance(value, dict):
      for key, child in value.items():
        yield (*prefix, key)
        yield from paths(child, (*prefix, key))
  for base in (v2_record(store), final, hosted):
    assert public.is_valid(base) and optimized.is_valid(base)
    for path in paths(base):
      for value in (None, False, 0, 1, {}, [], "invalid"):
        changed = deepcopy(base)
        parent = changed
        for key in path[:-1]:
          parent = parent[key]
        parent[path[-1]] = value
        assert optimized.is_valid(changed) == public.is_valid(changed), path
