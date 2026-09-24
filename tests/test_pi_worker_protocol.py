"""worker 投影仅携带所选模型及环境引用；不读取账号或返回凭据摘要。"""

from copy import deepcopy
from pathlib import Path

import pytest

from agentcfg.pi_worker_protocol import scoped_models
from agentcfg.schema import ConfigError
from agentcfg.secrets import CredentialError


def fixture():
  descriptor = {"provider_id": "agentcfg-fake", "model_id": "selected", "role_id": "task-keeper-reader", "allowed_tools": ["tk_read"]}
  provider = {"baseUrl": "https://fixture.invalid/v1", "api": "openai-completions", "apiKey": "$AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA",
    "models": [{"id": "selected", "input": ["text"]}, {"id": "other", "input": ["text"]}]}
  models = {"providers": {"agentcfg-fake": provider, "unselected": {"apiKey": "unread private sentinel"}}}
  manifest = {"role_bindings": {"task-keeper-reader": {"managed": True, "tools": ["tk_read"], "model": {"provider": "agentcfg-fake", "model": "selected"}}}}
  return descriptor, models, manifest


def test_scoped_provider_projection_keeps_one_model_and_only_selected_credential():
  descriptor, models, manifest = fixture()
  before = deepcopy(models)
  result, env = scoped_models(models, descriptor, manifest, {"AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA": "selected secret",
    "AGENTCFG_PI_CREDENTIAL_BBBBBBBBBBBBBBBB": "other secret", "SSH_AUTH_SOCK": "/unselected/socket"})
  assert result["providers"]["agentcfg-fake"]["models"] == [{"id": "selected", "input": ["text"]}]
  assert list(result["providers"]) == ["agentcfg-fake"]
  assert env == {"AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA": "selected secret"}
  assert "selected secret" not in str(result)
  assert models == before


def test_literal_key_unknown_selected_fields_and_missing_key_refuse_worker():
  descriptor, models, manifest = fixture()
  with pytest.raises(CredentialError):
    scoped_models(models, descriptor, manifest, {})
  models["providers"]["agentcfg-fake"]["apiKey"] = "synthetic literal secret"
  with pytest.raises(ConfigError) as caught:
    scoped_models(models, descriptor, manifest, {})
  assert "synthetic literal secret" not in str(caught.value)
  descriptor, models, manifest = fixture()
  models["providers"]["agentcfg-fake"]["headers"] = {"authorization": "synthetic unselected"}
  with pytest.raises(ConfigError):
    scoped_models(models, descriptor, manifest, {})


def test_supervisor_resolves_worker_with_closed_input_and_selected_environment(tmp_path, monkeypatch):
  import hashlib
  import json
  from types import SimpleNamespace
  from agentcfg.activity import digest
  from agentcfg.deployment import json_bytes
  from agentcfg.pi_guarded_files import root_identity
  from agentcfg.pi_host import HostSupervisor
  from agentcfg.pi_worker_files import snapshot
  from agentcfg.storage import Tree, ensure_private
  from test_pi_activity import make_store
  from test_pi_workspace_leases import worktree
  store, _ = make_store(tmp_path)
  root = worktree(tmp_path)
  runtime = tmp_path / ("b" * 64)
  instance = tmp_path / "instance"
  ensure_private(instance)
  ensure_private(runtime)
  definition = "Read the selected project."
  policy = {"schema_version": 1, "default": "deny", "rules": []}
  manifest = {"permission_policy": policy, "role_bindings": {"task-keeper-reader": {"managed": True,
    "tools": ["tk_read"], "read_roots": ["project"], "write_roots": [], "model": {"provider": "agentcfg-fake", "model": "selected"}}},
    "options": {"task_keeper": {"enabled": True}, "network": {"routes": {"direct": {"mode": "direct", "provider_ids": ["fake"]}}}}}
  _, models, _ = fixture()
  with Tree(instance) as tree:
    tree.write_state("pi-home/models.json", json_bytes(models))
    tree.write_state("pi-home/agentcfg-manifest.json", json_bytes(manifest))
    tree.write_state("pi-home/generated-roles/task-keeper-reader.md", definition.encode())
    tree.write_state("pi-home/auth.json", b"synthetic account sentinel")
  with Tree(runtime) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"worker": {"entrypoint": "runtime/worker.mjs", "kind": "worker", "engine": "node"}}}))
    tree.write_state("runtime/worker.mjs", b"// synthetic entry, never executed")
  lease = store.allocate(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt", lock_identity="a" * 64,
    slice_identity="c" * 64, policy_digest=digest(policy), candidate_digest=snapshot(root), planned_workspaces=[])
  descriptor = {**{key: store.owner[key] for key in ("instance_id", "manager_activation_id", "owner_nonce")},
    "protocol_version": 1, "request_id": "request", "task_id": "task", "step_id": "step", "attempt_id": "attempt", "continuation_of": None,
    "budget_scope_id": "budget", "role_id": "task-keeper-reader", "role_digest": hashlib.sha256(definition.encode()).hexdigest(),
    "runtime_digest": runtime.name, "policy_digest": digest(policy), "candidate_id": "candidate", "snapshot_digest": snapshot(root),
    "cwd": str(root), "source_cwd": str(root), "allowed_tools": ["tk_read"], "read_roots": ["project"], "write_roots": [], "inherited_denials": [],
    "context_mode": "fresh", "nested": False, "executor": "managed-process", "provider_id": "agentcfg-fake", "model_id": "selected", "model_digest": "d" * 64,
    "route_id": "direct", "thinking": "medium", "request_ceiling": 2, "turn_ceiling": 2, "deadline": "2099-01-01T00:00:00Z",
    "result_schema_digest": digest({}), "allowed_artifact_ids": [], "workspace_write_lease_ids": [], "workspace_identity_digest": "e" * 64,
    "grant_generation": 1, "allocation_id": lease["lease_id"]}
  context = {"schema_version": 1, "manager_run_id": "run", "lease_id": lease["lease_id"], "prompt": "fixture prompt",
    "role": {"id": descriptor["role_id"], "digest": descriptor["role_digest"], "definition": definition, "system_prompt": definition, "tools": ["tk_read"]},
    "model": {"provider_id": descriptor["provider_id"], "model_id": "selected", "model_digest": "d" * 64, "api": "openai-completions"},
    "route": {"id": "direct", "type": "direct", "base_url": "https://fixture.invalid/v1", "proxy_url": None},
    "root_bindings": {"project": {"path": str(root), "identity": root_identity(root)}}, "artifacts": {}, "result_schema": {}, "minimum_remaining": 0,
    "database": {"root": str(instance / "pi-home/task-keeper"), "filename": "runtime.db", "owner": {"scopeId": "scope", "token": "owner", "epoch": 1}}}
  host = object.__new__(HostSupervisor)
  host.store, host.root, host.runtime_root, host.repository = store, store.root, runtime, tmp_path
  host.config = {"instance_root": str(instance), "engine": "node", "policy_digest": digest(policy), "manifest_digest": digest(manifest)}
  host.server = SimpleNamespace(endpoint=tmp_path / "control.json")
  host.service = SimpleNamespace(issue_capability=lambda *args: "synthetic private capability")
  monkeypatch.setenv("AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA", "selected secret")
  monkeypatch.setenv("AGENTCFG_PI_CREDENTIAL_BBBBBBBBBBBBBBBB", "unselected secret")
  monkeypatch.setenv("SSH_AUTH_SOCK", "/synthetic/unselected/socket")
  from jsonschema import Draft202012Validator
  from agentcfg.pi_catalog import read_schema
  errors = list(Draft202012Validator(read_schema("managed-descriptor")).iter_errors(descriptor))
  assert not errors, [(list(error.path), error.message) for error in errors]
  command = host.resolve_command(lease, "worker", {"descriptor": descriptor, "context": context})
  assert command.cwd == root
  input_path = Path(command.argv[command.argv.index("--input") + 1])
  assert input_path == store.root / "activity/inputs" / (lease["lease_id"] + ".json")
  assert json.loads(input_path.read_bytes()) == {"descriptor": descriptor, "context": context}
  assert command.environment["AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA"] == "selected secret"
  assert "AGENTCFG_PI_CREDENTIAL_BBBBBBBBBBBBBBBB" not in command.environment
  assert "SSH_AUTH_SOCK" not in command.environment
  worker_home = store.root / "activity/worker-homes" / lease["lease_id"]
  assert not (worker_home / "pi-home/auth.json").exists()
  assert (instance / "pi-home/auth.json").read_bytes() == b"synthetic account sentinel"
  assert all(b"selected secret" not in file.read_bytes() for file in worker_home.rglob("*.json"))
