"""完整合法快照的纯关系验证；不使用实际账户、磁盘或授权来源。"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
import traceback

import pytest

from agentcfg import pi_durable_service_index_transitions as transitions
from agentcfg import pi_durable_service_index as codec
from agentcfg import pi_durable_registration_record as records
from agentcfg.storage import Conflict
from test_pi_durable_service_index import wire, registration, association, snapshot_from_complete_wire


SECRET = "SYNTHETIC_PRIVATE_SOURCE"
U64 = 2**64 - 1


def invalid(action):
  try: raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Conflict) as caught: action()
  error = caught.value
  assert type(error) is Conflict and error.args == ("Durable服务索引变更无效",)
  assert error.__cause__ is None and error.__context__ is None
  assert SECRET not in "".join(traceback.format_exception(error))
  return error


def snapshot(value):
  captured = codec.capture_service_index(value)
  assert codec.decode_service_index(codec.encode_service_index(captured)) == captured
  return captured


def reserve(before, number=3):
  after = deepcopy(before); after["generation"] += 1
  entry = wire(number)["services"][-1]
  after["services"].append(entry)
  after["associations"].append(association(entry["registration"]))
  return after


def register(before, index=0):
  after = deepcopy(before); after["generation"] += 1
  after["services"][index]["registration"].update(stage="registered", storage_identity={"device": 0, "inode": 17})
  return after


def associate(before):
  after = deepcopy(before); after["generation"] += 1
  after["associations"].append(association(after["services"][0]["registration"], "/new-alias"))
  return after


def relationship_rejected(before, after, operation):
  # 先独立核两份原codec完整合法，再证明纯后继关系拒绝。
  old = snapshot(before); new = snapshot(after)
  invalid(lambda: transitions.capture_service_index_transition(old, new, operation))


@pytest.mark.parametrize("operation,stage,index", [("reserve-service", "reserved", 0),
  ("register-storage", "reserved", 0), ("register-storage", "reserved", 1),
  ("associate-instance", "reserved", 0), ("associate-instance", "registered", 0)])
def test_exact_positive_delta_independent_full_clone_and_false_facade(operation, stage, index):
  before = wire(2, stage, aliases=1)
  after = reserve(before) if operation == "reserve-service" else register(before, index) if operation == "register-storage" else associate(before)
  expected = after["services"][-1 if operation == "reserve-service" else index if operation == "register-storage" else 0]["registration"]["service_id"]
  old, new = snapshot(before), snapshot(after)
  old_bytes, new_bytes = codec.encode_service_index(old), codec.encode_service_index(new)
  old_wire, new_wire = deepcopy(before), deepcopy(after)
  captured = transitions.capture_service_index_transition(old, new, operation)
  assert captured.service_id == expected and captured.operation == operation
  assert captured.previous == old and captured.following == new
  assert captured.previous is not old and captured.following is not new
  assert captured.previous.services[0] is not old.services[0]
  assert captured.following.associations[0] is not new.associations[0]
  assert codec.encode_service_index(old) == old_bytes and codec.encode_service_index(new) == new_bytes
  assert before == old_wire and after == new_wire
  assert [field.name for field in fields(captured)] == ["previous", "following", "operation", "service_id"]
  assert not hasattr(captured, "__dict__")
  with pytest.raises(FrozenInstanceError): captured.operation = "reserve-service"
  for target in (captured, captured.previous, captured.following):
    assert all(getattr(target, flag) is False for flag in ("writer_lock_verified", "database_allowed", "can_take_over"))
  object.__setattr__(old, "generation", 90)
  object.__setattr__(new.services[0].registration, "initial_deployment_identity", "f" * 64)
  assert codec.encode_service_index(captured.previous) == old_bytes
  assert codec.encode_service_index(captured.following) == new_bytes


def test_initial_independent_reserved_generation_one_and_flags():
  original = snapshot(wire())
  captured = transitions.capture_initial_service_index(original)
  assert captured == original and captured is not original
  assert captured.services[0].registration is not original.services[0].registration
  assert captured.associations[0].binding is not original.associations[0].binding
  assert captured.writer_lock_verified is False and captured.database_allowed is False and captured.can_take_over is False
  object.__setattr__(original, "generation", 2)
  assert captured.generation == 1
  forged = transitions.ServiceIndexTransition(None, None, "forged", SECRET)
  assert forged.writer_lock_verified is False and forged.database_allowed is False and forged.can_take_over is False


@pytest.mark.parametrize("case", ["generation", "services", "stage", "aliases"])
def test_initial_legally_encoded_but_wrong_initial_shape(case):
  value = wire()
  if case == "generation": value["generation"] = 2
  elif case == "services": value = wire(2)
  elif case == "stage": value = wire(stage="registered")
  else: value = wire(aliases=1)
  captured = snapshot(value)
  invalid(lambda: transitions.capture_initial_service_index(captured))


@pytest.mark.parametrize("field", ["account_home", "account_identity", "index_identity"])
@pytest.mark.parametrize("operation", ["reserve-service", "register-storage", "associate-instance"])
def test_common_original_account_and_index_boundaries_are_relations(field, operation):
  before = wire(2, aliases=1)
  after = reserve(before) if operation == "reserve-service" else register(before) if operation == "register-storage" else associate(before)
  if field == "account_home": after[field] = "/other-account"
  else: after[field]["inode"] += 1
  for entry in after["services"]: entry["registration"][field] = deepcopy(after[field])
  relationship_rejected(before, after, operation)


@pytest.mark.parametrize("operation", ["reserve-service", "register-storage", "associate-instance"])
@pytest.mark.parametrize("generation", [1, 3, 17])
def test_generation_same_or_jump_with_legal_snapshots(operation, generation):
  before = wire(2)
  after = reserve(before) if operation == "reserve-service" else register(before) if operation == "register-storage" else associate(before)
  after["generation"] = generation
  relationship_rejected(before, after, operation)


def test_uint64_maximum_predecessor_and_legally_encoded_wrap_refusal():
  before = wire(2); before["generation"] = U64 - 1
  result = transitions.capture_service_index_transition(snapshot(before), snapshot(register(before)), "register-storage")
  assert result.following.generation == U64
  before["generation"] = U64
  after = register(before); after["generation"] = 1
  relationship_rejected(before, after, "register-storage")


@pytest.mark.parametrize("operation", ["reserve-service", "register-storage", "associate-instance"])
def test_generation_bump_without_delta_rejected(operation):
  before = wire(2); after = deepcopy(before); after["generation"] += 1
  relationship_rejected(before, after, operation)


@pytest.mark.parametrize("case", ["registerednew", "two_new_services", "new_service_extra_alias", "old_service_extra_alias",
  "old_entry_deleted", "old_entry_replaced", "old_request_changed", "old_identity_changed", "old_deployment_changed", "old_alias_retargeted"])
def test_reserve_legal_successors_require_exact_one_new_and_all_history(case):
  before = wire(2, aliases=1); after = reserve(before)
  if case == "registerednew": after["services"][-1]["registration"].update(stage="registered", storage_identity={"device": 0, "inode": 1})
  elif case == "two_new_services":
    extra = wire(4)["services"][-1]; after["services"].append(extra); after["associations"].append(association(extra["registration"]))
  elif case == "new_service_extra_alias": after["associations"].append(association(after["services"][-1]["registration"], "/extra"))
  elif case == "old_service_extra_alias": after["associations"].append(association(after["services"][0]["registration"], "/extra"))
  elif case == "old_entry_deleted":
    old_id = after["services"].pop(1)["registration"]["service_id"]
    after["associations"] = [item for item in after["associations"] if item["service_id"] != old_id]
  elif case == "old_entry_replaced":
    old_id = after["services"][1]["registration"]["service_id"]; extra = wire(4)["services"][-1]
    after["services"][1] = extra
    after["associations"] = [item for item in after["associations"] if item["service_id"] != old_id]
    after["associations"].append(association(extra["registration"]))
  elif case == "old_request_changed": after["services"][0]["initialization_request_id"] = "e" * 64
  elif case == "old_identity_changed": after["services"][0]["initialization_identity"] = "e" * 64
  elif case == "old_deployment_changed": after["services"][0]["registration"]["initial_deployment_identity"] = "e" * 64
  else: after["associations"][2]["service_id"] = after["services"][1]["registration"]["service_id"]
  relationship_rejected(before, after, "reserve-service")


@pytest.mark.parametrize("case", ["same_stage", "reverse_stage", "two_changed", "deployment", "request", "identity", "binding", "instance", "state_root", "service_id", "new_alias", "retarget_alias", "delete_alias"])
def test_register_legal_snapshots_preserve_full_entry_and_every_association(case):
  before = wire(2, aliases=1)
  if case in ("same_stage", "reverse_stage"): before = wire(2, stage="registered", aliases=1)
  if case in ("binding", "instance", "state_root"):
    # before预放目标alias；after只改首次登记，关联全集不变。
    target = deepcopy(before["services"][0]["registration"])
    if case == "binding": target["initial_binding"]["machine"] = "other"
    elif case == "instance": target["initial_instance"] = "/other-instance"
    else:
      target["initial_state_root"] = "/other-state"
      target["storage_path"] = "/other-state/durable/storage"
    before["associations"].append(association(target))
  after = register(before)
  record = after["services"][0]["registration"]
  if case == "reverse_stage": record.update(stage="reserved", storage_identity=None)
  elif case == "two_changed": after["services"][1]["registration"].update(stage="registered", storage_identity={"device": 0, "inode": 2})
  elif case == "deployment": record["initial_deployment_identity"] = "f" * 64
  elif case == "request": after["services"][0]["initialization_request_id"] = "f" * 64
  elif case == "identity": after["services"][0]["initialization_identity"] = "f" * 64
  elif case in ("binding", "instance", "state_root"):
    if case == "binding": record["initial_binding"]["machine"] = "other"
    elif case == "instance": record["initial_instance"] = "/other-instance"
    else: record["initial_state_root"] = "/other-state"; record["storage_path"] = "/other-state/durable/storage"
    # state_root与派生storage_path是一项耦合约束，涉及两个字段。
    assert before["associations"] == after["associations"]
    expected = register(before)["services"][0]["registration"]
    changed = {name for name in record if record[name] != expected[name]}
    assert changed == ({"initial_binding"} if case == "binding" else {"initial_instance"} if case == "instance" else {"initial_state_root", "storage_path"})
  elif case == "service_id":
    old_id = record["service_id"]; record["service_id"] = "f" * 64
    for item in after["associations"]:
      if item["service_id"] == old_id: item["service_id"] = record["service_id"]
  elif case == "new_alias": after["associations"].append(association(record, "/extra"))
  elif case == "retarget_alias": after["associations"][2]["service_id"] = after["services"][1]["registration"]["service_id"]
  elif case == "delete_alias": after["associations"].pop(2)
  relationship_rejected(before, after, "register-storage")


@pytest.mark.parametrize("case", ["delete_old_alias", "retarget_old_alias", "two_new_aliases", "change_entry", "new_service"])
def test_associate_legal_successors_keep_all_original_data(case):
  before = wire(2, aliases=1); after = associate(before)
  if case == "delete_old_alias": after["associations"].pop(2)
  elif case == "retarget_old_alias": after["associations"][2]["service_id"] = after["services"][1]["registration"]["service_id"]
  elif case == "two_new_aliases": after["associations"].append(association(after["services"][1]["registration"], "/extra"))
  elif case == "change_entry": after["services"][0]["initialization_identity"] = "f" * 64
  else:
    extra = wire(3)["services"][-1]; after["services"].append(extra); after["associations"].append(association(extra["registration"]))
  relationship_rejected(before, after, "associate-instance")


def test_capacity_valid_controls_and_codec_layer_refusals():
  before = wire(63)
  captured = transitions.capture_service_index_transition(snapshot(before), snapshot(reserve(before, 64)), "reserve-service")
  assert len(captured.following.services) == 64
  before = wire(2, aliases=509)
  captured = transitions.capture_service_index_transition(snapshot(before), snapshot(associate(before)), "associate-instance")
  assert len(captured.following.associations) == 512
  for before, after, operation in [(wire(64), reserve(wire(64), 65), "reserve-service"),
    (wire(2, aliases=510), associate(wire(2, aliases=510)), "associate-instance")]:
    old = snapshot(before); forged = snapshot_from_complete_wire(after)
    with pytest.raises(Conflict) as old_error: codec.encode_service_index(forged)
    assert old_error.value.args == ("Durable服务索引无效",)
    invalid(lambda: transitions.capture_service_index_transition(old, forged, operation))


@pytest.mark.parametrize("case", ["missing_initial", "duplicate_request", "wrong_schema", "wrong_platform", "generation_overflow"])
def test_invalid_wire_is_explicitly_old_codec_layer(case):
  before = wire(2); after = reserve(before)
  if case == "missing_initial": after["associations"].pop()
  elif case == "duplicate_request": after["services"][-1]["initialization_request_id"] = after["services"][0]["initialization_request_id"]
  elif case == "wrong_schema": after["schema"] = 2
  elif case == "wrong_platform": after["platform"] = "darwin"
  else: after["generation"] = 2**64
  with pytest.raises(Conflict): codec.capture_service_index(after)
  # 不把以上旧wire失败计为可达的合法快照关系反例。


def test_original_registration_byte_limit_rechecked_by_public_clone():
  before = snapshot(wire(2)); value = registration(); path = "/" + '"' * 4079
  for name in ("account_home", "initial_instance", "initial_state_root"): value[name] = path
  value["initial_binding"]["local"] = path; value["storage_path"] = path + "/durable/storage"
  oversized = records.capture_service_registration(value)
  with pytest.raises(Conflict): records.encode_service_registration(oversized)
  forged = replace(before, services=(replace(before.services[0], registration=oversized), before.services[1]))
  invalid(lambda: transitions.capture_initial_service_index(forged))
  invalid(lambda: transitions.capture_service_index_transition(forged, before, "register-storage"))


def test_public_encoder_decoder_forwarding_controls_and_complete_typecuts(monkeypatch):
  calls = []; hooks = []
  original_encode, original_decode = codec.encode_service_index, codec.decode_service_index
  def encode(value): calls.append("encode"); return original_encode(value)
  def decode(value): calls.append("decode"); return original_decode(value)
  monkeypatch.setattr(transitions, "encode_service_index", encode)
  monkeypatch.setattr(transitions, "decode_service_index", decode)
  before = snapshot(wire(2)); after = snapshot(register(wire(2)))
  assert transitions.capture_service_index_transition(before, after, "register-storage").following == after
  assert calls == ["encode", "decode", "encode", "decode"]
  calls.clear()
  assert transitions.capture_initial_service_index(snapshot(wire())).generation == 1
  assert calls == ["encode", "decode"]
  class Text(str):
    def __eq__(self, other): hooks.append("eq"); raise AssertionError()
    def __hash__(self): hooks.append("hash"); raise AssertionError()
  class Foreign:
    def __getattribute__(self, name): hooks.append(name); raise AssertionError()
  class Child(codec.ServiceIndexSnapshot): pass
  child = Child(**{field.name: getattr(before, field.name) for field in fields(before)})
  for old, new, operation in [(before, after, "unknown"), (before, after, Text("register-storage")),
    (before, after, Foreign()), (Foreign(), after, "register-storage"), (before, Foreign(), "register-storage"),
    (child, after, "register-storage"), (before, child, "register-storage")]:
    calls.clear()
    invalid(lambda: transitions.capture_service_index_transition(old, new, operation))
    assert calls == []
  for value in (Foreign(), child):
    calls.clear(); invalid(lambda: transitions.capture_initial_service_index(value)); assert calls == []
  assert hooks == []


@pytest.mark.parametrize("field", ["snapshot", "entry", "association", "binding", "registration", "directory"])
def test_uninitialized_exact_slots_fail_at_original_encoder_layer(field, monkeypatch):
  before = snapshot(wire(2)); after = snapshot(register(wire(2)))
  if field == "snapshot": forged = object.__new__(codec.ServiceIndexSnapshot)
  elif field == "entry": forged = replace(before, services=(object.__new__(codec.ServiceIndexEntry), before.services[1]))
  elif field == "association": forged = replace(before, associations=(object.__new__(codec.ServiceAssociation), before.associations[1]))
  elif field == "binding": forged = replace(before, associations=(replace(before.associations[0], binding=object.__new__(records.InitialBinding)), before.associations[1]))
  elif field == "registration": forged = replace(before, services=(replace(before.services[0], registration=object.__new__(records.ServiceRegistration)), before.services[1]))
  else: forged = replace(before, account_identity=object.__new__(records.DirectoryIdentity))
  with pytest.raises(Conflict): codec.encode_service_index(forged)
  calls = []; original = codec.encode_service_index
  def encode(value): calls.append(value); return original(value)
  monkeypatch.setattr(transitions, "encode_service_index", encode)
  invalid(lambda: transitions.capture_initial_service_index(forged)); assert len(calls) == 1
  calls.clear(); invalid(lambda: transitions.capture_service_index_transition(forged, after, "register-storage")); assert len(calls) == 1


@pytest.mark.parametrize("field", ["directory", "registration", "binding", "scalar"])
def test_forged_nested_types_do_not_execute_foreign_hooks(field):
  calls = []
  class Foreign:
    def __getattribute__(self, name): calls.append(name); raise AssertionError()
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
  class Number(int):
    def __le__(self, other): calls.append("le"); raise AssertionError()
  before = snapshot(wire(2)); after = snapshot(register(wire(2)))
  if field == "directory": forged = replace(before, account_identity=Foreign())
  elif field == "registration": forged = replace(before, services=(replace(before.services[0], registration=Foreign()), before.services[1]))
  elif field == "binding": forged = replace(before, associations=(replace(before.associations[0], binding=Foreign()), before.associations[1]))
  else: forged = replace(before, generation=Number(1))
  invalid(lambda: transitions.capture_service_index_transition(forged, after, "register-storage"))
  assert calls == []


@pytest.mark.parametrize("boundary", ["encode", "decode"])
@pytest.mark.parametrize("initial", [False, True])
def test_foreign_exceptions_unchanged_and_fresh_actual_chain(monkeypatch, boundary, initial):
  before = snapshot(wire()); after = snapshot(register(wire()))
  cause = ValueError("foreign cause"); context = RuntimeError("foreign context")
  foreign = RuntimeError(SECRET)
  def fail(value):
    try: raise foreign
    except RuntimeError:
      foreign.__cause__ = cause; foreign.__context__ = context
      raise
  monkeypatch.setattr(transitions, "encode_service_index" if boundary == "encode" else "decode_service_index", fail)
  action = (lambda: transitions.capture_initial_service_index(before)) if initial else (lambda: transitions.capture_service_index_transition(before, after, "register-storage"))
  first = invalid(action); second = invalid(action)
  assert first is not second and first is not foreign
  assert foreign.args == (SECRET,) and foreign.__cause__ is cause and foreign.__context__ is context
