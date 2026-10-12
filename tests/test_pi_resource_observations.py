"""认证manager的历史加载报告；默认只假store/process/RPC与自有临时文件。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.activity import OWNER_KEYS
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict
from agentcfg.pi_resource_observations import ResourceObservations, read_resource_observation


def fixture(tmp_path):
  state = tmp_path / "state"; state.mkdir(mode=0o700)
  runtime = tmp_path / ("c" * 64); (runtime / "runtime").mkdir(parents=True, mode=0o700)
  installed = {"schema_version": 2, "profile_id": "pi-base", "resources": {"extensions": [{"id": "todo", "capability_id": "todo", "path": "own/index.mjs"}], "skills": [], "prompts": [], "themes": [], "roles": []}}
  (runtime / "runtime/profile.json").write_text(json.dumps(installed))
  manifest = {"profile_id": "pi-base", "plugins": ["pi-todo"], "plugin_capabilities": {"pi-todo": {"capability_id": "todo", "model_tools": ["todo"]}},
    "resource_ids": {kind: {} for kind in ("extensions", "skills", "prompts", "themes", "roles")}, "resources": {},
    "options": {"discovery": {"project_resources": False}}, "bootstrap": False}
  owner = {key: "owned-" + key for key in OWNER_KEYS}; owner["instance_id"] = "f" * 64
  lease = {**owner, "lease_id": "lease", "kind": "host", "state": "running", "spawn_committed": True,
    "grant_generation": 1, "process_identity": {"pid": 42}}
  store = SimpleNamespace(owner=owner, read=lambda identity: deepcopy(lease))
  host = SimpleNamespace(root=state, runtime_root=runtime, store=store, config={"instance_id": owner["instance_id"],
    "lock_identity": "a" * 64, "slice_identity": "b" * 64, "manifest_digest": "d" * 64},
    manifest=lambda: deepcopy(manifest), processes=SimpleNamespace(observe=lambda identity: "alive"), service=SimpleNamespace(closing=False))
  observer = ResourceObservations(host)
  snap = {"schemaVersion": 1, "profileId": "pi-base", "lockIdentity": "a" * 64, "sliceIdentity": "b" * 64,
    "runtimeIdentity": "c" * 64, "configIdentity": "e" * 64, "resourcesDigest": "f" * 64,
    "observation": {"schemaVersion": 1, "scope": "in-memory-public-sdk-load", "resourcesDigest": "f" * 64,
      "resources": {"extensions": [{"id": "todo", "scope": "runtime"}], "skills": [], "prompts": [], "themes": []},
      "inlineExtensions": ["rotom-command-boundary"], "selectedRoles": [], "rolesEvidence": "selection-only"}}
  ctx = {"profile_id": "pi-base", "lock_identity": "a" * 64, "slice_identity": "b" * 64, "runtime_identity": "c" * 64, "manifest_digest": "d" * 64}
  request = {"kind": "loaded", "session_id": "session-one", "generation": 1, "snapshot": snap}
  return host, observer, Principal("manager", "lease", 1), request, ctx


def test_publish_update_retire_and_offline_metadata_only(tmp_path):
  host, observer, principal, request, ctx = fixture(tmp_path)
  observer.publish(principal, request)
  assert observer.publish(principal, request)["accepted"] is True
  result = read_resource_observation(host.root, context=ctx)
  assert result["status"] == "last-observed"
  assert result["liveness"] == "last-observed-not-live"
  assert result["config_identity_evidence"] == "runtime-observed"
  assert "owned-owner_nonce" not in json.dumps(result)
  next_request = deepcopy(request); next_request["generation"] = 2
  next_request["snapshot"]["configIdentity"] = "1" * 64
  observer.publish(principal, next_request)
  with pytest.raises(Conflict):
    observer.publish(principal, {"kind": "retired", "session_id": "session-one", "generation": 1})
  observer.publish(principal, {"kind": "retired", "session_id": "session-one", "generation": 2})
  assert read_resource_observation(host.root, context=ctx)["status"] == "stale"
  with pytest.raises(Conflict): observer.publish(principal, next_request)


@pytest.mark.parametrize("fault", ["wrong-role", "wrong-lease", "wrong-generation", "identity", "unknown", "too-long", "secret-field", "unselected-id", "closing"])
def test_publication_rejection_does_not_write(tmp_path, fault):
  host, observer, principal, request, _ = fixture(tmp_path)
  if fault == "wrong-role": principal = Principal("user")
  elif fault == "wrong-lease": principal = Principal("manager", "foreign", 1)
  elif fault == "wrong-generation": principal = Principal("manager", "lease", 2)
  elif fault == "identity": request["snapshot"]["runtimeIdentity"] = "0" * 64
  elif fault == "unknown": request["unknown"] = True
  elif fault == "too-long": request["snapshot"]["observation"]["inlineExtensions"] = ["x" * 65536]
  elif fault == "secret-field": request["snapshot"]["authorization"] = "OWN-SYNTHETIC-NOT-CREDENTIAL"
  elif fault == "unselected-id": request["snapshot"]["observation"]["resources"]["extensions"][0]["id"] = "unselected"
  else: host.service.closing = True
  with pytest.raises(Conflict): observer.publish(principal, request)
  assert not (host.root / "diagnostics/resource-observation.json").exists()


def test_offline_identity_manifest_changes_and_channel_close_are_stale(tmp_path):
  host, observer, principal, request, ctx = fixture(tmp_path)
  observer.publish(principal, request)
  wrong = {**ctx, "manifest_digest": "0" * 64}
  assert read_resource_observation(host.root, context=wrong)["status"] == "stale"
  observer.close()
  assert read_resource_observation(host.root, context=ctx)["status"] == "stale"


def test_unknown_or_corrupt_saved_fields_do_not_echo_partial_data(tmp_path):
  host, observer, principal, request, ctx = fixture(tmp_path)
  observer.publish(principal, request)
  path = host.root / "diagnostics/resource-observation.json"
  data = json.loads(path.read_text()); data["unknown"] = "OWN-NOT-A-CREDENTIAL"
  path.write_text(json.dumps(data))
  result = read_resource_observation(host.root, context=ctx)
  assert result["status"] == "unavailable"
  assert "OWN-NOT-A-CREDENTIAL" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["duplicate-generation", "duplicate-scope", "nonfinite-generation"])
def test_duplicate_saved_metadata_is_not_a_valid_observation(tmp_path, fault):
  host, observer, principal, request, ctx = fixture(tmp_path)
  observer.publish(principal, request)
  path = host.root / "diagnostics/resource-observation.json"
  raw = path.read_text()
  if fault == "duplicate-generation":
    raw = raw.replace('"generation":1', '"generation":999,"generation":1').replace('"generation": 1', '"generation": 999, "generation": 1')
  elif fault == "duplicate-scope":
    raw = raw.replace('"scope":"runtime"', '"scope":"external","scope":"runtime"').replace('"scope": "runtime"', '"scope": "external", "scope": "runtime"')
  else:
    raw = raw.replace('"generation":1', '"generation":NaN').replace('"generation": 1', '"generation": NaN')
  path.write_text(raw)
  assert read_resource_observation(host.root, context=ctx)["status"] == "unavailable"


def test_observed_selection_boundary_is_historical_contract_not_filesystem_discovery(tmp_path):
  host, observer, principal, request, ctx = fixture(tmp_path)
  observer.publish(principal, request)
  observer.close()
  report = read_resource_observation(host.root, context=ctx)
  boundary = report["selection_boundary"]
  assert report["status"] == "stale"
  assert boundary == {"evidence": "last-observed-selection-contract",
    "implicit_global": "disabled-by-managed-loader", "implicit_ancestor": "disabled-by-managed-loader",
    "project": "explicit-selected-only", "package": "explicit-selected-only",
    "loaded_package_resources": [{"kind": "extensions", "id": "todo"}],
    "loaded_project_resources": [], "filesystem_scan": "not-performed", "isolation": "unverified"}
  assert "path" not in json.dumps(boundary)
