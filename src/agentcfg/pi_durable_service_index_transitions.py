"""索引完整快照的纯后继关系；合法变更不授予任何写入或运行权限。"""

from dataclasses import dataclass, replace
from functools import wraps

from .pi_durable_service_index import ServiceIndexSnapshot, encode_service_index, decode_service_index
from .storage import Conflict


_U64 = 2**64 - 1
_OPERATIONS = ("reserve-service", "register-storage", "associate-instance")


@dataclass(frozen=True, slots=True)
class ServiceIndexTransition:
  previous: ServiceIndexSnapshot
  following: ServiceIndexSnapshot
  operation: str
  service_id: str

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


def _invalid():
  raise ValueError("invalid service index transition")


def _reject():
  error = Conflict("Durable服务索引变更无效")
  try:
    raise error
  except Conflict:
    error.__cause__ = None
    error.__context__ = None
    raise


def _boundary(action):
  @wraps(action)
  def checked(*args, **kwargs):
    failed = False
    try:
      result = action(*args, **kwargs)
    except Exception:
      failed = True
    if failed: _reject()
    return result
  return checked


def _clone(snapshot):
  return decode_service_index(encode_service_index(snapshot))


def _initial(association, registration):
  return (association.service_id == registration.service_id
    and association.binding == registration.initial_binding
    and association.instance == registration.initial_instance
    and association.state_root == registration.initial_state_root)


@_boundary
def capture_initial_service_index(snapshot):
  if type(snapshot) is not ServiceIndexSnapshot: _invalid()
  captured = _clone(snapshot)
  if captured.generation != 1 or len(captured.services) != 1 or len(captured.associations) != 1: _invalid()
  record = captured.services[0].registration
  if record.stage != "reserved" or not _initial(captured.associations[0], record): _invalid()
  return captured


def _added_association(previous, following):
  if len(following) != len(previous) + 1: _invalid()
  if any(following.get(key) != value for key, value in previous.items()): _invalid()
  return following[next(iter(following.keys() - previous.keys()))]


@_boundary
def capture_service_index_transition(previous, following, operation):
  # 所有入口类型一次核完，再接触属性或调用原公开encoder。
  if type(operation) is not str or operation not in _OPERATIONS: _invalid()
  if type(previous) is not ServiceIndexSnapshot or type(following) is not ServiceIndexSnapshot: _invalid()
  before = _clone(previous)
  after = _clone(following)
  if (before.schema != after.schema or before.platform != after.platform
      or before.account_home != after.account_home or before.account_identity != after.account_identity
      or before.index_identity != after.index_identity): _invalid()
  if before.generation >= _U64 or after.generation != before.generation + 1: _invalid()
  old_entries = {entry.registration.service_id: entry for entry in before.services}
  new_entries = {entry.registration.service_id: entry for entry in after.services}
  old_associations = {association.association_id: association for association in before.associations}
  new_associations = {association.association_id: association for association in after.associations}
  if operation == "reserve-service":
    if len(new_entries) != len(old_entries) + 1: _invalid()
    if any(new_entries.get(key) != value for key, value in old_entries.items()): _invalid()
    service = next(iter(new_entries.keys() - old_entries.keys()))
    registration = new_entries[service].registration
    if registration.stage != "reserved": _invalid()
    association = _added_association(old_associations, new_associations)
    if not _initial(association, registration): _invalid()
  elif operation == "register-storage":
    if old_entries.keys() != new_entries.keys() or old_associations != new_associations: _invalid()
    changed = [key for key, value in old_entries.items() if value != new_entries[key]]
    if len(changed) != 1: _invalid()
    service = changed[0]
    old_entry, new_entry = old_entries[service], new_entries[service]
    if old_entry.registration.stage != "reserved" or new_entry.registration.stage != "registered": _invalid()
    # replace只修改两字段，完整Entry比较保留原11登记字段与2初始化字段。
    expected_record = replace(old_entry.registration, stage="registered", storage_identity=new_entry.registration.storage_identity)
    if replace(old_entry, registration=expected_record) != new_entry: _invalid()
  else:
    if old_entries != new_entries: _invalid()
    association = _added_association(old_associations, new_associations)
    service = association.service_id
    if service not in old_entries: _invalid()
  return ServiceIndexTransition(before, after, operation, service)
