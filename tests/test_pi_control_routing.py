"""控制端点仅按完整执行归属定位，不扫描或借用其他运行。"""

from copy import deepcopy

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_control import endpoint_for_owner
from agentcfg.storage import Conflict, Tree
from test_pi_activity import make_store


def endpoint_record(owner, capability="synthetic-user"):
  return {"schema_version": 1, "owner": owner, "socket_name": "control.sock",
    "socket_identity": {}, "user_capability": capability}


def write_endpoint(state, owner, *, legacy=False, record=None):
  path = "activity/control/" + ("" if legacy else owner["supervisor_activation_id"] + "/") + "control.json"
  with Tree(state, create=True) as tree:
    tree.write_state(path, json_bytes(record or endpoint_record(owner)))
  return state / path


def test_endpoint_routes_two_owners_without_directory_scan(tmp_path, monkeypatch):
  first, _ = make_store(tmp_path)
  second, _ = make_store(tmp_path, activation="supervisor-two")
  paths = [write_endpoint(store.root, store.owner) for store in (first, second)]
  with monkeypatch.context() as guarded:
    guarded.setattr("os.listdir", lambda *_: pytest.fail("endpoint selection must not scan"))
    for store, expected in zip((first, second), paths):
      endpoint, record = endpoint_for_owner(store.root, store.owner)
      assert endpoint == expected and record["owner"] == store.owner


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("field", ["owner_nonce", "manager_activation_id", "instance_id", "supervisor_process_identity"])
def test_endpoint_rejects_any_wrong_owner_field(tmp_path, legacy, field):
  store, _ = make_store(tmp_path)
  record = endpoint_record(deepcopy(store.owner))
  if field == "supervisor_process_identity": record["owner"][field]["start_time"] = "stale"
  else: record["owner"][field] += "-stale"
  write_endpoint(store.root, store.owner, legacy=legacy, record=record)
  with pytest.raises(Conflict): endpoint_for_owner(store.root, store.owner)


def test_legacy_endpoint_requires_exact_owner_and_wrong_new_endpoint_does_not_fallback(tmp_path):
  store, _ = make_store(tmp_path)
  legacy = write_endpoint(store.root, store.owner, legacy=True)
  assert endpoint_for_owner(store.root, store.owner)[0] == legacy
  record = endpoint_record({**store.owner, "owner_nonce": "other"})
  write_endpoint(store.root, store.owner, record=record)
  with pytest.raises(Conflict): endpoint_for_owner(store.root, store.owner)


@pytest.mark.parametrize("damage", ["mode", "symlink", "malformed"])
def test_endpoint_unsafe_or_malformed_record_never_falls_back(tmp_path, damage):
  store, _ = make_store(tmp_path)
  write_endpoint(store.root, store.owner, legacy=True)
  endpoint = write_endpoint(store.root, store.owner)
  if damage == "mode": endpoint.chmod(0o644)
  elif damage == "malformed": endpoint.write_bytes(b"{synthetic-invalid")
  else:
    target = endpoint.with_name("synthetic-target")
    endpoint.rename(target)
    endpoint.symlink_to(target)
  with pytest.raises(Conflict): endpoint_for_owner(store.root, store.owner)
