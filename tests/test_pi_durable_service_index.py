"""离线原生数据索引边界；不构造初始化或持锁能力。"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import traceback

import pytest

from agentcfg import pi_durable_service_index as codec
from agentcfg import pi_durable_registration_record as records
from agentcfg.deployment import json_bytes
from agentcfg.pi_durable_owner_record import StorageIdentity
from agentcfg.storage import Conflict


SECRET = "SYNTHETIC_PRIVATE_SOURCE"


def registration(number=1, stage="reserved"):
  return {"schema": 1, "platform": "linux", "service_id": f"{number:064x}", "stage": stage,
    "account_home": "/synthetic/账户", "account_identity": {"device": 0, "inode": 1, "uid": 1000},
    "index_identity": {"device": 2, "inode": 3, "uid": 1000},
    "initial_binding": {"machine": "fixture", "local": "/synthetic/local.toml", "profile": "pi-full"},
    "initial_instance": f"/synthetic/instance{number}", "initial_state_root": f"/synthetic/state{number}",
    "storage_path": f"/synthetic/state{number}/durable/storage",
    "storage_identity": None if stage == "reserved" else {"device": 0, "inode": 1},
    "initial_deployment_identity": "b" * 64}


def association(record, suffix=""):
  binding = deepcopy(record["initial_binding"])
  instance = record["initial_instance"] + suffix
  state = record["initial_state_root"] + suffix
  # 独立投影不使用被测 identity helper，也不包含 service_id。
  projection = {"schema": 1, "kind": "pi-durable-service-association", "binding": binding,
    "instance": instance, "state_root": state}
  return {"association_id": hashlib.sha256(json_bytes(projection)).hexdigest(), "binding": binding,
    "instance": instance, "state_root": state, "service_id": record["service_id"]}


def wire(count=1, stage="reserved", aliases=0):
  first = registration(stage=stage)
  result = {"schema": 1, "platform": "linux", "account_home": first["account_home"],
    "account_identity": deepcopy(first["account_identity"]), "index_identity": deepcopy(first["index_identity"]),
    "generation": 1, "services": [], "associations": []}
  for number in range(1, count + 1):
    record = registration(number, stage)
    result["services"].append({"registration": record, "initialization_request_id": f"{number:064x}", "initialization_identity": "d" * 64})
    result["associations"].append(association(record))
  result["associations"].extend(association(first, f"/alias{number}") for number in range(aliases))
  return result


def invalid(action):
  try: raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Conflict) as caught: action()
  error = caught.value
  assert type(error) is Conflict and error.args == ("Durable服务索引无效",)
  assert error.__cause__ is None and error.__context__ is None
  assert SECRET not in "".join(traceback.format_exception(error))
  return error


def reject_mutation(mutation):
  value = wire(2, aliases=1)
  codec.capture_service_index(value)
  mutation(value)
  invalid(lambda: codec.capture_service_index(value))


@pytest.mark.parametrize("stage", ["reserved", "registered"])
def test_canonical_roundtrip_independent_immutable_and_no_authority(stage):
  value = wire(2, stage, 2)
  expected = deepcopy(value)
  expected["services"].sort(key=lambda entry: entry["registration"]["service_id"])
  expected["associations"].sort(key=lambda item: item["association_id"])
  value["services"].reverse(); value["associations"].reverse()
  snapshot = codec.capture_service_index(value)
  encoded = codec.encode_service_index(snapshot)
  assert encoded == json_bytes(expected)
  assert codec.decode_service_index(encoded) == snapshot
  assert all(getattr(snapshot, flag) is False for flag in ("writer_lock_verified", "database_allowed", "can_take_over"))
  value["account_identity"]["inode"] = 90
  value["services"][0]["registration"]["initial_binding"]["machine"] = "changed"
  value["associations"][0]["binding"]["local"] = "/changed"
  assert codec.encode_service_index(snapshot) == encoded
  for target, name in [(snapshot, "generation"), (snapshot.services[0], "initialization_identity"),
      (snapshot.associations[0], "instance"), (snapshot.associations[0].binding, "local")]:
    assert not hasattr(target, "__dict__")
    with pytest.raises(FrozenInstanceError): setattr(target, name, None)


def test_identity_projection_service_independent_and_literal_alias():
  record = registration()
  item = association(record)
  assert codec.service_association_identity(item["binding"], item["instance"], item["state_root"]) == item["association_id"]
  record["service_id"] = "e" * 64
  assert association(record)["association_id"] == item["association_id"]
  alias = association(record, "/alias")
  assert alias["association_id"] != item["association_id"]


@pytest.mark.parametrize("field", list(wire()))
def test_required_top_fields(field):
  reject_mutation(lambda value: value.pop(field))


@pytest.mark.parametrize("field,bad", [("schema", True), ("schema", 2), ("platform", "darwin"),
  ("generation", True), ("generation", 0), ("generation", 2**64), ("generation", 1.0), ("extra", SECRET)])
def test_top_types_versions_ranges(field, bad):
  reject_mutation(lambda value: value.__setitem__(field, bad))


@pytest.mark.parametrize("name", ["account_identity", "index_identity"])
@pytest.mark.parametrize("field,bad", [("device", True), ("device", -1), ("device", 2**64),
  ("inode", 0), ("inode", 2**64), ("uid", True), ("uid", -1), ("uid", 2**32-1), ("extra", 1)])
def test_directory_limits(name, field, bad):
  reject_mutation(lambda value: value[name].__setitem__(field, bad))


@pytest.mark.parametrize("field", ["account_home", "account_identity", "index_identity"])
def test_registration_original_account_matches(field):
  def mutate(value):
    record = value["services"][0]["registration"]
    if field == "account_home": record[field] = "/other"
    else: record[field]["inode"] += 1
  reject_mutation(mutate)


@pytest.mark.parametrize("case", ["service", "request", "association", "missingref", "wrongref", "missinginitial", "derived", "unknownentry", "unknownassociation", "unknownbinding", "badrequest", "badidentity"])
def test_relationships_and_exact_nested_schema(case):
  def mutate(value):
    services, items = value["services"], value["associations"]
    if case == "service": services.append(deepcopy(services[0]))
    elif case == "request": services[1]["initialization_request_id"] = services[0]["initialization_request_id"]
    elif case == "association": items.append(deepcopy(items[0]))
    elif case == "missingref": items[0]["service_id"] = "f" * 64
    elif case == "wrongref": items[0]["service_id"] = services[1]["registration"]["service_id"]
    elif case == "missinginitial": items.pop(0)
    elif case == "derived": items[0]["association_id"] = "f" * 64
    elif case == "unknownentry": services[0]["extra"] = SECRET
    elif case == "unknownassociation": items[0]["extra"] = SECRET
    elif case == "unknownbinding": items[0]["binding"]["extra"] = SECRET
    elif case == "badrequest": services[0]["initialization_request_id"] = "A" * 64
    else: services[0]["initialization_identity"] = "a" * 63
  reject_mutation(mutate)


@pytest.mark.parametrize("path", ["/", "relative", "//root/a", "/a/", "/a//b", "/a/./b", "/a/../b", "/a\\b", "/a\x00b", "/a\x7fb", "/a\x9fb", "/a\ud800b", "/" + "界" * 1366, True])
@pytest.mark.parametrize("field", ["instance", "state_root", "local"])
def test_identity_path_boundary(path, field):
  item = association(registration())
  assert codec.service_association_identity(item["binding"], item["instance"], item["state_root"]) == item["association_id"]
  if field == "local": item["binding"][field] = path
  else: item[field] = path
  invalid(lambda: codec.service_association_identity(item["binding"], item["instance"], item["state_root"]))


@pytest.mark.parametrize("field,bad", [("machine", "Upper"), ("machine", "a" * 65), ("machine", True), ("profile", "pi-base")])
def test_binding_rules(field, bad):
  item = association(registration()); item["binding"][field] = bad
  invalid(lambda: codec.service_association_identity(item["binding"], item["instance"], item["state_root"]))


def test_maximum_capacities_generation_and_empty_rejection():
  value = wire(64, aliases=448); value["generation"] = 2**64-1
  assert len(codec.decode_service_index(codec.encode_service_index(codec.capture_service_index(value))).associations) == 512
  # 每个超容量负例保留唯一 ID、请求及完整初始关联，单独保护数量边界。
  for data in (wire(65), wire(64, aliases=449)):
    invalid(lambda: codec.capture_service_index(data))
  for field in ("services", "associations"):
    data = deepcopy(value); data[field] = []
    invalid(lambda: codec.capture_service_index(data))


def snapshot_from_complete_wire(value):
  """仅用公开 DTO 与登记捕获构造数据，容许测试构造超容量元组。"""
  baseline = codec.capture_service_index(wire())
  entries = tuple(codec.ServiceIndexEntry(records.capture_service_registration(entry["registration"]),
    entry["initialization_request_id"], entry["initialization_identity"]) for entry in value["services"])
  associations = []
  for item in value["associations"]:
    assert codec.service_association_identity(item["binding"], item["instance"], item["state_root"]) == item["association_id"]
    associations.append(codec.ServiceAssociation(item["association_id"], records.InitialBinding(**item["binding"]),
      item["instance"], item["state_root"], item["service_id"]))
  return replace(baseline, services=entries, associations=tuple(associations))


@pytest.mark.parametrize("count,aliases", [(65, 0), (64, 449)])
def test_encoder_capacity_refused_before_original_encoder_calls(count, aliases, monkeypatch):
  legal = codec.capture_service_index(wire(64, aliases=448))
  oversized = snapshot_from_complete_wire(wire(count, aliases=aliases))
  calls = []
  original = codec.encode_service_registration
  def spy(record):
    calls.append(record)
    return original(record)
  monkeypatch.setattr(codec, "encode_service_registration", spy)
  assert codec.decode_service_index(codec.encode_service_index(legal)) == legal
  assert calls and all(type(record) is records.ServiceRegistration for record in calls)
  calls.clear()
  invalid(lambda: codec.encode_service_index(oversized))
  assert calls == []


def test_registration_capture_retains_original_byte_limit():
  data = wire(); record = data["services"][0]["registration"]; path = "/" + '"' * 4079
  for name in ("account_home", "initial_instance", "initial_state_root"): record[name] = path
  record["initial_binding"]["local"] = path; record["storage_path"] = path + "/durable/storage"
  data["account_home"] = path; data["associations"] = [association(record)]
  assert type(records.capture_service_registration(record)) is records.ServiceRegistration
  with pytest.raises(Conflict): records.encode_service_registration(records.capture_service_registration(record))
  invalid(lambda: codec.capture_service_index(data))


@pytest.mark.parametrize("raw", [b"", b"\xff", b"\xef\xbb\xbf{}", b'{"schema":1,"schema":1}',
  b'{"schema":1,"\\u0073chema":1}', b'{"x":{"a":1,"a":2}}', b'{"x":NaN}', b'{"x":Infinity}',
  b'{"x":-Infinity}', b'{"x":1e999}', b"[" * 2000 + b"0" + b"]" * 2000,
  bytearray(b"{}"), "{}"])
def test_json_boundary(raw):
  invalid(lambda: codec.decode_service_index(raw))


def test_json_size_exact_native_bytes_and_noncanonical_order():
  value = wire(); raw = json.dumps(dict(reversed(list(value.items()))), ensure_ascii=False).encode()
  expected = codec.capture_service_index(value)
  assert codec.decode_service_index(raw) == expected
  padded = raw + b" " * (16 * 1024 * 1024 - len(raw))
  assert codec.decode_service_index(padded) == expected
  invalid(lambda: codec.decode_service_index(padded + b" "))


def test_type_first_foreign_hooks_zero_across_public_boundaries():
  calls = []; armed = False
  class String(str):
    def __hash__(self):
      if armed: calls.append("hash"); raise AssertionError()
      return str.__hash__(self)
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
  class Number(int):
    def __le__(self, other): calls.append("le"); raise AssertionError()
  class Dict(dict):
    def items(self): calls.append("items"); raise AssertionError()
  class List(list):
    def __iter__(self): calls.append("iter"); raise AssertionError()
  class Foreign:
    def __getattribute__(self, name): calls.append("attribute"); raise AssertionError()
  keyed = {String("schema"): 1}; armed = True
  invalid(lambda: codec.capture_service_index(keyed))
  invalid(lambda: codec.capture_service_index(Dict()))
  invalid(lambda: codec.encode_service_index(Foreign()))
  invalid(lambda: codec.service_association_identity(Foreign(), "/i", "/s"))
  snapshot = codec.capture_service_index(wire())
  for field, bad in [("generation", Number(1)), ("account_home", String("/home")), ("services", List()), ("associations", List())]:
    data = wire(); data[field] = bad; invalid(lambda: codec.capture_service_index(data))
  data = wire(); data["associations"][0]["service_id"] = String("a" * 64)
  invalid(lambda: codec.capture_service_index(data))
  for field in ("account_identity", "index_identity", "services", "associations"):
    invalid(lambda: codec.encode_service_index(replace(snapshot, **{field: Foreign()})))
  invalid(lambda: codec.encode_service_index(replace(snapshot, services=(Foreign(),))))
  invalid(lambda: codec.encode_service_index(replace(snapshot, associations=(Foreign(),))))
  assert calls == []


@pytest.mark.parametrize("target", ["snapshot", "entry", "association", "account", "index", "binding", "registration", "storage"])
def test_uninitialized_slots_rejected(target):
  snapshot = codec.capture_service_index(wire(stage="registered"))
  if target == "snapshot": snapshot = object.__new__(codec.ServiceIndexSnapshot)
  elif target == "entry": snapshot = replace(snapshot, services=(object.__new__(codec.ServiceIndexEntry),))
  elif target == "association": snapshot = replace(snapshot, associations=(object.__new__(codec.ServiceAssociation),))
  elif target in ("account", "index"): snapshot = replace(snapshot, **{target + "_identity": object.__new__(records.DirectoryIdentity)})
  elif target == "binding": snapshot = replace(snapshot, associations=(replace(snapshot.associations[0], binding=object.__new__(records.InitialBinding)),))
  else:
    record = object.__new__(records.ServiceRegistration) if target == "registration" else replace(snapshot.services[0].registration, storage_identity=object.__new__(StorageIdentity))
    snapshot = replace(snapshot, services=(replace(snapshot.services[0], registration=record),))
  invalid(lambda: codec.encode_service_index(snapshot))


@pytest.mark.parametrize("target", ["snapshot", "entry", "association", "binding", "registration", "directory"])
def test_nested_foreign_attributes_never_accessed(target):
  calls = []
  class Foreign:
    def __getattribute__(self, name): calls.append(name); raise AssertionError()
  snapshot = codec.capture_service_index(wire())
  if target == "snapshot": snapshot = Foreign()
  elif target == "entry": snapshot = replace(snapshot, services=(Foreign(),))
  elif target == "association": snapshot = replace(snapshot, associations=(Foreign(),))
  elif target == "binding": snapshot = replace(snapshot, associations=(replace(snapshot.associations[0], binding=Foreign()),))
  elif target == "registration": snapshot = replace(snapshot, services=(replace(snapshot.services[0], registration=Foreign()),))
  else: snapshot = replace(snapshot, account_identity=Foreign())
  invalid(lambda: codec.encode_service_index(snapshot)); assert calls == []


def test_constructor_forgery_revalidation_and_exact_classes():
  snapshot = codec.capture_service_index(wire())
  invalid(lambda: codec.encode_service_index(replace(snapshot, schema=True)))
  invalid(lambda: codec.encode_service_index(replace(snapshot, services=list(snapshot.services))))
  bad = replace(snapshot.associations[0], association_id="f" * 64)
  invalid(lambda: codec.encode_service_index(replace(snapshot, associations=(bad,))))
  class Child(codec.ServiceIndexSnapshot): pass
  invalid(lambda: codec.encode_service_index(Child(**{field: getattr(snapshot, field) for field in wire()})))


def test_foreign_exception_unchanged_and_fresh_boundary_errors(monkeypatch):
  cause = ValueError("foreign cause"); context = RuntimeError("foreign context")
  foreign = Conflict(SECRET); foreign.__cause__ = cause; foreign.__context__ = context
  def fail(_value):
    try: raise foreign
    except Conflict:
      foreign.__cause__ = cause; foreign.__context__ = context
      raise
  monkeypatch.setattr(codec, "capture_service_registration", fail)
  first = invalid(lambda: codec.capture_service_index(wire()))
  second = invalid(lambda: codec.capture_service_index(wire()))
  assert first is not second and first is not foreign
  assert foreign.args == (SECRET,) and foreign.__cause__ is cause
  assert foreign.__context__ is context


def test_native_extremes_and_maximum_utf8_paths():
  value = wire(stage="registered"); value["generation"] = 2**64-1
  for name in ("account_identity", "index_identity"):
    identity = {"device": 2**64-1, "inode": 2**64-1, "uid": 2**32-2}
    value[name] = identity
    value["services"][0]["registration"][name] = deepcopy(identity)
  snapshot = codec.capture_service_index(value)
  assert codec.decode_service_index(codec.encode_service_index(snapshot)) == snapshot
  item = association(registration()); item["instance"] = "/" + "a" * 4095
  assert len(codec.service_association_identity(item["binding"], item["instance"], item["state_root"])) == 64
  item["instance"] += "a"
  invalid(lambda: codec.service_association_identity(item["binding"], item["instance"], item["state_root"]))


@pytest.mark.parametrize("location", ["entry", "association", "binding", "directory", "registration"])
def test_nested_foreign_key_never_hashed_or_compared(location):
  calls = []; armed = False
  class Key(str):
    def __hash__(self):
      if armed: calls.append("hash"); raise AssertionError()
      return str.__hash__(self)
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
  keyed = {Key("extra"): SECRET}; armed = True
  value = wire()
  if location == "entry": value["services"][0] = keyed
  elif location == "association": value["associations"][0] = keyed
  elif location == "binding": value["associations"][0]["binding"] = keyed
  elif location == "directory": value["account_identity"] = keyed
  else: value["services"][0]["registration"] = keyed
  invalid(lambda: codec.capture_service_index(value)); assert calls == []


@pytest.mark.parametrize("field,cls", [("account_identity", records.DirectoryIdentity),
  ("index_identity", records.DirectoryIdentity), ("initial_binding", records.InitialBinding), ("storage_identity", StorageIdentity)])
def test_registration_nested_uninitialized_stays_own_error(field, cls):
  snapshot = codec.capture_service_index(wire(stage="registered"))
  record = replace(snapshot.services[0].registration, **{field: object.__new__(cls)})
  snapshot = replace(snapshot, services=(replace(snapshot.services[0], registration=record),))
  invalid(lambda: codec.encode_service_index(snapshot))


def test_original_encoder_foreign_failure_remains_unchanged(monkeypatch):
  snapshot = codec.capture_service_index(wire())
  cause = ValueError("cause"); context = RuntimeError("context")
  foreign = RuntimeError(SECRET)
  def fail(_value):
    try: raise foreign
    except RuntimeError:
      foreign.__cause__ = cause; foreign.__context__ = context
      raise
  monkeypatch.setattr(codec, "encode_service_registration", fail)
  invalid(lambda: codec.encode_service_index(snapshot))
  assert foreign.args == (SECRET,) and foreign.__cause__ is cause and foreign.__context__ is context


@pytest.mark.parametrize("location", ["entry", "association", "binding", "directory"])
def test_each_required_nested_field(location):
  value = wire()
  if location == "entry": target = value["services"][0]
  elif location == "association": target = value["associations"][0]
  elif location == "binding": target = value["associations"][0]["binding"]
  else: target = value["account_identity"]
  codec.capture_service_index(value)
  for field in tuple(target):
    prior = target.pop(field)
    invalid(lambda: codec.capture_service_index(value))
    target[field] = prior
