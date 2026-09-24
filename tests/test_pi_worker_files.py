"""私有 RPC 到真实临时工作树的完整 IO 链，进程与模型均为替身。"""

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.pi_guarded_files import root_identity
from agentcfg.pi_worker_files import WorkerFiles, snapshot
from agentcfg.storage import Tree
from agentcfg.workspace_leases import WorkspaceLeases
from test_pi_supervisor import fixture, request
from test_pi_workspace_leases import worktree


def worker(tmp_path):
  service, manager, args, calls = fixture(tmp_path)
  root = worktree(tmp_path)
  (root / "a.txt").write_text("original")
  source = tmp_path / "source"
  source.mkdir()
  (source / "sentinel").write_text("source untouched")
  instance = tmp_path / "instance"
  instance.mkdir(mode=0o700)
  service.store.workspaces = WorkspaceLeases("fixture-boot")
  tools = ["tk_read", "tk_write", "tk_edit", "tk_ls"]
  policy = {"schema_version": 1, "default": "deny", "rules": [{"id": "project", "kind": "file", "effect": "allow",
    "tool_ids": tools, "operations": ["read", "list", "write", "create", "rename"], "root_ref": "project", "relative_path": ".", "match": "subtree"}]}
  args.update(policy_digest=digest(policy), candidate_digest=snapshot(root), planned_workspaces=[service.store.workspaces.identify(root)])
  lease_id = service.reply(manager, os.geteuid(), request("allocate", args))["result"]["lease_id"]
  service.reply(manager, os.geteuid(), request("start", {"lease_id": lease_id, "program": "worker", "payload": {}}))
  lease = service.store.read(lease_id)
  role = {"managed": True, "tools": tools, "read_roots": ["project"], "write_roots": ["project"], "model": {"provider": "fake", "model": "fake-model"}}
  descriptor = {"role_id": "task-keeper-writer", "policy_digest": args["policy_digest"], "grant_generation": 1,
    "allocation_id": lease_id, "attempt_id": "attempt", "allowed_tools": tools, "provider_id": "fake", "model_id": "fake-model",
    "cwd": str(root), "source_cwd": str(source), "read_roots": ["project"], "write_roots": ["project"], "inherited_denials": [],
    "executor": "managed-process", "context_mode": "fresh", "nested": False, "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
  context = {"root_bindings": {"project": {"path": str(root), "identity": root_identity(root)}}}
  with Tree(service.store.root) as tree:
    tree.write_state("activity/inputs/" + lease_id + ".json", json_bytes({"descriptor": descriptor, "context": context}))
  manifest = {"permission_policy": policy, "role_bindings": {"task-keeper-writer": role}, "options": {}}
  service.worker_operation = WorkerFiles(service.store, lambda: manifest, instance)
  token = service.issue_capability("worker", lease_id)
  def action(operation_id, value, token_override=None):
    return service.reply(token_override or token, os.geteuid(), request("file_action", {
      "lease_id": lease_id, "grant_generation": 1, "operation_id": operation_id, "action": value}))
  return service, root, action, manager, lease_id


def test_private_worker_rpc_records_mutation_then_returns_idempotent_result(tmp_path):
  service, root, action, manager, lease = worker(tmp_path)
  read = {"tool_id": "tk_read", "operation": "read", "path": "a.txt", "offset": 0, "limit": 65536}
  assert base64.b64decode(action("read", read)["result"]["data_b64"]) == b"original"
  write = {"tool_id": "tk_write", "operation": "write", "path": "a.txt", "data_b64": base64.b64encode(b"changed").decode(), "expected_digest": None}
  first = action("write-one", write)
  assert first["ok"] is True
  assert action("write-one", write) == first
  assert (root / "a.txt").read_bytes() == b"changed"
  record = json.loads((service.store.root / "activity/file-actions" / lease / "write-one.json").read_text())
  assert record["state"] == "settled"
  assert record["before_snapshot"] != record["after_snapshot"]
  assert action("write-one", {**write, "data_b64": base64.b64encode(b"different").decode()})["exit_code"] == 4
  assert action("manager-write", write, manager)["exit_code"] == 4


def test_worker_rpc_generation_and_candidate_source_boundaries(tmp_path):
  service, root, action, manager, lease = worker(tmp_path)
  write = {"tool_id": "tk_write", "operation": "write", "path": "a.txt", "data_b64": base64.b64encode(b"changed").decode(), "expected_digest": None}
  assert action("git", {**write, "path": ".git/HEAD"})["exit_code"] == 4
  assert action("escape", {**write, "path": "../source/sentinel"})["exit_code"] == 4
  assert action("mode", {**write, "execution_mode": "ordinary"})["exit_code"] == 2
  service.reply(manager, os.geteuid(), request("cancel", {"lease_id": lease}))
  assert action("revoked", write)["exit_code"] == 4
  assert (root / "a.txt").read_text() == "original"
  assert (tmp_path / "source/sentinel").read_text() == "source untouched"


def test_candidate_mutations_form_one_durable_chain_and_external_drift_invalidates_it(tmp_path):
  import pytest
  from agentcfg.pi_worker_files import mutation_chain
  from agentcfg.storage import Conflict
  service, root, action, manager, lease_id = worker(tmp_path)
  lease = service.store.read(lease_id)
  assert mutation_chain(service.store, lease, root)["mutations"] == 0
  for index in range(2):
    write = {"tool_id": "tk_write", "operation": "write", "path": "a.txt", "data_b64": base64.b64encode(str(index).encode()).decode(), "expected_digest": None}
    assert action("operation-" + str(index), write)["ok"]
  assert mutation_chain(service.store, lease, root)["mutations"] == 2
  (root / "a.txt").write_text("external change")
  with pytest.raises(Conflict, match="SNAPSHOT_STALE"):
    mutation_chain(service.store, lease, root)
  assert action("operation-3", write)["exit_code"] == 4
  assert (root / "a.txt").read_text() == "external change"


def test_candidate_snapshot_never_hashes_known_credential_files(tmp_path):
  root = worktree(tmp_path)
  secret = root / "local.toml"
  secret.write_text("synthetic first credential")
  (root / "source.txt").write_text("business source")
  before = snapshot(root, protected_roots=[secret])
  secret.write_text("synthetic changed credential")
  assert snapshot(root, protected_roots=[secret]) == before
  (root / "source.txt").write_text("changed source")
  assert snapshot(root, protected_roots=[secret]) != before


def test_snapshot_of_owned_candidate_inside_private_state_hashes_business_content(tmp_path):
  state = tmp_path / "state"
  state.mkdir()
  candidate = worktree(state)
  (candidate / "source.txt").write_text("before")
  before = snapshot(candidate, protected_roots=[state])
  (candidate / "source.txt").write_text("after")
  assert snapshot(candidate, protected_roots=[state]) != before


def test_source_scope_ignores_build_output_but_includes_explicit_model_mutations(tmp_path):
  root = worktree(tmp_path)
  (root / "code.txt").write_text("source")
  (root / "build").mkdir()
  (root / "build/output").write_text("first build")
  before = snapshot(root, source_paths=["code.txt"])
  (root / "build/output").write_text("second build")
  assert snapshot(root, source_paths=["code.txt"]) == before
  (root / "build/generated-code").write_text("explicit model output")
  assert snapshot(root, source_paths=["code.txt", "build/generated-code"]) != before
