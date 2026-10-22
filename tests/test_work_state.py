"""v2 最小绑定与不可变意图；不访问原生端点。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import stat

import pytest

from termcfg.errors import TermcfgError


def state(tmp_path, *, identity=(7, 11), create=True, socket=None):
  from termcfg.work_state import WorkState
  return WorkState(socket or str(tmp_path / "native" / "api.sock"), identity,
    root=tmp_path / "private-state", create=create)


def binding(store, tmp_path):
  from termcfg.work_state import context_owner, launch_digest
  context = {"kind": "named", "key": "case-a"}
  launch = {"launcher": "shell", "argv": ["/bin/sh"], "runtime": None, "paths": {"HOME": str(tmp_path)}}
  return {"version": 2, "owner": context_owner(store.socket_path, **context),
    "endpoint": store.socket_path, "generation": list(store.identity),
    "epoch": "a" * 32, "context": context, "workspace_start": str(tmp_path),
    "captured_home": str(tmp_path), "workspace_id": None, "template": "development",
    "origin": "explicit", "types": {"shell": {"cwd": str(tmp_path), "captured_home": str(tmp_path),
      "launch": launch, "digest": launch_digest(tmp_path, tmp_path, launch),
      "default": None, "sequence": 0, "instances": {}}}}


def publish(store, value, op="b" * 32):
  return store.publish_intent(op, value, action="workspace-initial", payload_digest="c" * 64,
    type_key="shell", instance="f" * 32, kind="default")


def test_read_only_missing_state_creates_nothing(tmp_path, sentinel_factory):
  before = sentinel_factory(tmp_path)
  with state(tmp_path, create=False) as store:
    assert store.bindings() == [] and store.intents() == []
  before.assert_unchanged()


def test_private_modes_endpoint_alias_and_generation(tmp_path):
  from termcfg.work_state import context_owner
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    value["workspace_id"] = "workspace-1"
    store.save_binding(value)
    assert store.load_binding(value["owner"]) == value
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE((store.root / "bindings" / (value["owner"] + ".json")).stat().st_mode) == 0o600
    root = store.base
  with state(tmp_path, create=False, identity=(7, 12)) as changed:
    with pytest.raises(TermcfgError) as error:
      changed.load_binding(value["owner"])
    assert error.value.code == 4
  alias = tmp_path / "alias"
  alias.symlink_to(tmp_path, target_is_directory=True)
  assert context_owner(str(alias / "native" / "api.sock"), "named", "case-a") == value["owner"]
  assert root == tmp_path / "private-state"


@pytest.mark.parametrize("change", [
  lambda v: v.update(extra="unknown"),
  lambda v: v["context"].update(title="not an identity"),
  lambda v: v.update(owner="d" * 64),
  lambda v: v.update(epoch="wrong"),
  lambda v: v.update(workspace_start="relative"),
  lambda v: v.update(captured_home="/bad\npath"),
  lambda v: v.update(generation=[True, 11]),
])
def test_conflicting_or_unknown_binding_fields_fail(tmp_path, change):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    value["workspace_id"] = "workspace-1"
    change(value)
    with pytest.raises(TermcfgError) as error:
      store.save_binding(value)
    assert error.value.code == 4
    assert store.bindings() == []


def test_immutable_intent_one_pending_per_owner_without_expiry_cleanup(tmp_path):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    intent = publish(store, value)
    assert intent["payload_digest"] == "c" * 64
    assert store.pending(value["owner"])[0]["op"] == "b" * 32
    with pytest.raises(TermcfgError) as error:
      publish(store, value, "d" * 32)
    assert error.value.code == 4
    with pytest.raises(TermcfgError):
      store.publish_intent("b" * 32, value, action="workspace-initial", payload_digest="d" * 64,
        type_key="shell", instance="f" * 32, kind="default")
    assert len(store.intents()) == 1
    assert store.read_intent("b" * 32) == intent


def test_same_start_named_and_project_contexts_do_not_share_owner(tmp_path):
  from termcfg.work_state import context_owner
  endpoint = str(tmp_path / "api.sock")
  values = {context_owner(endpoint, "named", "case-a"),
    context_owner(endpoint, "named", "case-b"),
    context_owner(endpoint, "project", str(tmp_path)),
    context_owner(str(tmp_path / "other.sock"), "named", "case-a")}
  assert len(values) == 4


def test_receipt_cannot_skip_commit_or_change_known_native_ids(tmp_path):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    publish(store, value)
    with pytest.raises(TermcfgError):
      store.update_receipt("b" * 32, "accepted")
    store.update_receipt("b" * 32, "dispatched", workspace_id="workspace-1")
    with pytest.raises(TermcfgError):
      store.update_receipt("b" * 32, "commit-issued", workspace_id="workspace-2")
    store.update_receipt("b" * 32, "commit-issued", pane_id="pane-1",
      terminal_id="terminal-1", tab_id="tab-1")
    store.update_receipt("b" * 32, "accepted")
    with pytest.raises(TermcfgError):
      store.compact("b" * 32)
    assert store.pending(value["owner"])


def test_receipt_compacts_only_after_matching_durable_instance(tmp_path):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    publish(store, value)
    ids = {"workspace_id": "workspace-1", "pane_id": "pane-1",
      "terminal_id": "terminal-1", "tab_id": "tab-1"}
    store.update_receipt("b" * 32, "dispatched", **ids)
    store.update_receipt("b" * 32, "commit-issued")
    store.update_receipt("b" * 32, "accepted")
    value["workspace_id"] = ids["workspace_id"]
    launch = {"launcher": "shell", "argv": ["/bin/sh"], "runtime": None,
      "paths": {"HOME": str(tmp_path)}}
    from termcfg.work_state import launch_digest
    value["types"]["shell"] = {"cwd": str(tmp_path), "captured_home": str(tmp_path),
      "launch": launch, "digest": launch_digest(tmp_path, tmp_path, launch), "default": "f" * 32, "sequence": 1,
      "instances": {"f" * 32: {"op": "b" * 32, "kind": "default", **ids}}}
    store.save_binding(value)
    store.compact("b" * 32)
    assert store.pending(value["owner"]) == [] and store.intents() == []
    assert store.load_binding(value["owner"]) == value


def test_orphan_intent_and_malformed_private_files_are_unknown(tmp_path):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    publish(store, value)
    receipt = store.root / "receipts" / ("b" * 32 + ".json")
    receipt.unlink()
    assert store.pending(value["owner"])[0]["phase"] == "unknown"
    receipt.write_text('{"version":2,"version":2}')
    receipt.chmod(0o600)
    with pytest.raises(TermcfgError) as error:
      store.pending(value["owner"])
    assert error.value.code == 4


def test_read_only_reports_do_not_change_receipt_bytes(tmp_path, sentinel_factory):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    publish(store, value)
    root = store.root
  before = sentinel_factory(root)
  with state(tmp_path, create=False) as store:
    assert len(store.pending(value["owner"])) == 1
    assert len(store.intents()) == 1
  before.assert_unchanged()


def test_state_symlink_mode_and_oversized_records_are_rejected(tmp_path):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    value["workspace_id"] = "workspace-1"
    store.save_binding(value)
    path = store.root / "bindings" / (value["owner"] + ".json")
    original = path.read_bytes()
    path.chmod(0o644)
    with pytest.raises(TermcfgError):
      store.load_binding(value["owner"])
    path.chmod(0o600)
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(TermcfgError):
      store.load_binding(value["owner"])
    path.unlink()
    target = tmp_path / "target"
    target.write_bytes(original)
    path.symlink_to(target)
    with pytest.raises(TermcfgError):
      store.load_binding(value["owner"])


def test_existing_type_contract_cannot_be_changed_or_removed(tmp_path):
  from termcfg.work_state import launch_digest
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    value["workspace_id"] = "workspace-1"
    launch = {"launcher": "shell", "argv": ["/bin/sh"], "runtime": None,
      "paths": {"HOME": str(tmp_path)}}
    value["types"]["shell"] = {"cwd": str(tmp_path), "captured_home": str(tmp_path),
      "launch": launch, "digest": launch_digest(tmp_path, tmp_path, launch),
      "default": None, "sequence": 0, "instances": {}}
    store.save_binding(value)
    changed = deepcopy(value)
    changed["types"]["shell"]["cwd"] = "/other-start"
    changed["types"]["shell"]["digest"] = launch_digest("/other-start", tmp_path, launch)
    with pytest.raises(TermcfgError):
      store.save_binding(changed)
    changed["types"] = {}
    with pytest.raises(TermcfgError):
      store.save_binding(changed)


@pytest.mark.parametrize("key,changed", [("owner", "d" * 64), ("epoch", "d" * 32), ("action", "tab")])
def test_receipt_identity_must_agree_with_immutable_intent(tmp_path, key, changed):
  from termcfg.work_state import json_bytes
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    publish(store, value)
    ids = {"workspace_id": "workspace-1", "pane_id": "pane-1",
      "terminal_id": "terminal-1", "tab_id": "tab-1"}
    store.update_receipt("b" * 32, "dispatched", **ids)
    receipt = store.update_receipt("b" * 32, "commit-issued")
    receipt[key] = changed
    store.tree.write_state("receipts/" + "b" * 32 + ".json", json_bytes(receipt))
    with pytest.raises(TermcfgError):
      store.update_receipt("b" * 32, "accepted")


def test_deep_corrupted_json_is_state_conflict(tmp_path):
  with state(tmp_path) as store:
    value = binding(store, tmp_path)
    publish(store, value)
    path = store.root / "receipts" / ("b" * 32 + ".json")
    path.write_bytes(b'{"x":' * 2000 + b"0" + b"}" * 2000)
    with pytest.raises(TermcfgError) as error:
      store.pending(value["owner"])
    assert error.value.code == 4
