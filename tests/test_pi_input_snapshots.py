import hashlib
from types import SimpleNamespace

import pytest

from agentcfg.activity import digest
from agentcfg.pi_input_snapshots import canonical, semantic_digest, host_scope, scope_policy, validate_semantic_source
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def source():
  return {"schema_version": 1, "workspace_identity": "a" * 64, "scope": {"relative_roots": ["."], "explicit_inputs": [], "artifact_exclusions": [], "outside_exclusions": []}, "files": [], "sensitive_inputs": []}


def test_utf8_shared_vector():
  value = {"😀": "x", "\ue000": "y", "a": 1}
  assert canonical(value) == '{"a":1,"\ue000":"y","😀":"x"}'
  assert semantic_digest(value) == hashlib.sha256(canonical(value).encode()).hexdigest()


@pytest.mark.parametrize("value", [{"approved": True}, {"relative_roots": ["src"]}, {"explicit_inputs": ["../secret"]}, {"explicit_inputs": ["a", "a"]}, {"artifact_exclusions": [{"relative_path": "a", "kind": "file", "safe": True}]}])
def test_closed_host_policy_rejects_model_scope(value):
  with pytest.raises(ConfigError): scope_policy(value)


def test_current_manifest_secret_classification_without_open(tmp_path, monkeypatch):
  candidate = tmp_path / "pi-home/task-keeper/worktrees/job";candidate.mkdir(parents=True)
  secret = candidate / ".env";secret.write_text("never hash this synthetic credential")
  manifest = {"options": {"paths": {"roots": {"project": {"path": str(candidate)}}}, "task_keeper": {"project_root": "project"}}, "permission_policy": {"rules": [{"kind": "file", "effect": "deny", "root_ref": "project", "relative_path": ".env"}]}}
  host = SimpleNamespace(config={"manifest_digest": digest(manifest), "protected_roots": [str(tmp_path)], "instance_root": str(tmp_path), "state_root": str(tmp_path / "state")}, store=SimpleNamespace(workspaces=SimpleNamespace(identify=lambda _path: None)))
  original = type(secret).read_bytes
  def reject_secret(self):
    assert self != secret
    return original(self)
  monkeypatch.setattr(type(secret), "read_bytes", reject_secret)
  context = host_scope(host, manifest, source=candidate, candidate=candidate, creating=False)
  assert context["protected_inputs"][0]["reference"] == "file:project:.env"
  assert "never hash" not in canonical(context)
  manifest["permission_policy"]["rules"][0]["relative_path"] = ".";host.config["manifest_digest"] = digest(manifest)
  with pytest.raises(Conflict, match="ROOT_DENIED"): host_scope(host, manifest, source=candidate, candidate=candidate, creating=True)


def test_closed_semantic_source():
  body = source();assert validate_semantic_source(body) == body
  body["heartbeat"] = 100
  with pytest.raises(ConfigError): validate_semantic_source(body)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 9007199254740992])
def test_non_json_lossy_values(value):
  with pytest.raises(ConfigError): semantic_digest({"value": value})


def test_full_compose_and_identity_changes():
  from agentcfg.pi_input_snapshots import IDENTITY_FIELDS, compile_input_snapshot
  hash_value = "a" * 64
  identities = {key: hash_value for key in IDENTITY_FIELDS}
  identities.update(model_routes=[], checker_contracts=[], environment={"platform": "linux", "architecture": "x64", "node_version": "v24.14.0", "sdk_version": "1.0.1", "declared_nonsecret_variables": [{"name": "LANG", "value": "C.UTF-8"}]})
  first = compile_input_snapshot(source(), identities)
  for name, value in identities.items():
    if type(value) is str:
      assert compile_input_snapshot(source(), {**identities, name: "b" * 64})["digest"] != first["digest"]
  with pytest.raises(ConfigError): compile_input_snapshot(source(), {**identities, "Authorization": "secret body"})


def test_caps_and_link_coverage():
  body = source();body["files"] = [{"relative_path": "link", "kind": "symlink", "target": "not-selected"}]
  with pytest.raises(ConfigError): validate_semantic_source(body)
  with pytest.raises(ConfigError): semantic_digest({"x": "x" * (1024 * 1024)})
  with pytest.raises(ConfigError): scope_policy({"explicit_inputs": ["file" + str(x) for x in range(10001)]})


def test_integral_json_numbers_match_node_and_secret_shape_rejects_body():
  body = source();body["schema_version"] = 1.0
  assert canonical(validate_semantic_source(body)) == canonical(source())
  body["sensitive_inputs"] = [{"reference": "secret:fixture", "category": "credential-file", "owner": None, "provider": None, "actor": "candidate", "state": "present", "body": "must not serialize"}]
  with pytest.raises(ConfigError): validate_semantic_source(body)


def test_shared_full_dto_vector():
  import json
  from pathlib import Path
  from agentcfg.pi_input_snapshots import compile_input_snapshot
  vector = json.loads((Path(__file__).parents[1] / "agents/pi/packages/task-keeper/tests/fixtures/input-snapshot-vector.json").read_text())
  assert compile_input_snapshot(vector["source"], vector["identities"])["digest"] == vector["expected_digest"]


def test_real_optional_schema_and_adapter_wrong_route(tmp_path):
  from agentcfg.pi_catalog import validate
  from agentcfg.pi import PiAdapter
  from test_pi_adapter import ROOT, pi_data
  validate("options", {"input_snapshot": {"explicit_inputs": ["source.txt", "unicode/😀.txt", "build/0.js"], "artifact_exclusions": [{"relative_path": "output", "kind": "directory"}]}})
  with pytest.raises(ConfigError): validate("options", {"input_snapshot": {"approved": True}})
  data = pi_data(tmp_path);data["profile"]["agent_options"]["input_snapshot"] = {}
  PiAdapter(ROOT).validate(data)
  data["profile"]["agent_options"]["input_snapshot"] = {"explicit_inputs": ["source.txt"]}
  with pytest.raises(ConfigError, match="INPUT_SNAPSHOT_CONTEXT_REQUIRED"): PiAdapter(ROOT).validate(data)


@pytest.mark.parametrize("creating", [True, False])
def test_protected_ancestor_never_implicitly_authorizes_source_or_candidate(tmp_path, creating):
  root = tmp_path / "protected" / "workspace";root.mkdir(parents=True)
  manifest = {"options": {"paths": {"roots": {"project": {"path": str(root)}}}, "task_keeper": {"project_root": "project"}}, "permission_policy": {"rules": []}}
  host = SimpleNamespace(config={"manifest_digest": digest(manifest), "protected_roots": [str(root.parent)], "instance_root": str(tmp_path / "other-instance"), "state_root": str(tmp_path / "other-state")}, store=SimpleNamespace(workspaces=SimpleNamespace(identify=lambda _path: None)))
  with pytest.raises(Conflict, match="INPUT_SNAPSHOT_ROOT_DENIED"):
    host_scope(host, manifest, source=root, candidate=root, creating=creating)


def test_explicit_deny_ancestor_is_not_private_instance_exemption(tmp_path):
  candidate = tmp_path / "pi-home/task-keeper/worktrees/job";candidate.mkdir(parents=True)
  manifest = {"options": {"paths": {"roots": {"project": {"path": str(candidate)}, "denied": {"path": str(tmp_path)}}}, "task_keeper": {"project_root": "project"}, "permissions": {"denied_roots": ["denied"]}}, "permission_policy": {"rules": []}}
  host = SimpleNamespace(config={"manifest_digest": digest(manifest), "protected_roots": [str(tmp_path)], "instance_root": str(tmp_path), "state_root": str(tmp_path / "state")}, store=SimpleNamespace(workspaces=SimpleNamespace(identify=lambda _path: None)))
  with pytest.raises(Conflict, match="ROOT_DENIED"): host_scope(host, manifest, source=candidate, candidate=candidate, creating=False)


def test_original_physical_root_identity_tempfile_and_observed_shared_vector(tmp_path):
  import json
  from pathlib import Path
  from agentcfg.pi_guarded_files import root_identity
  from agentcfg.deployment import json_bytes
  info = tmp_path.stat()
  tuple_value = {"device": str(info.st_dev), "inode": str(info.st_ino), "uid": str(info.st_uid)}
  assert root_identity(tmp_path) == hashlib.sha256(json_bytes(tuple_value)).hexdigest()
  vector = json.loads((Path(__file__).parents[1] / "agents/pi/packages/task-keeper/tests/fixtures/workspace-physical-identity-vector.json").read_text())
  assert hashlib.sha256(json_bytes({key: vector[key] for key in ("device", "inode", "uid")})).hexdigest() == vector["root_identity"]


def test_original_private_scope_categories_stable_between_source_create_and_candidate_snapshot(tmp_path):
  project = tmp_path / "project";project.mkdir()
  instance = tmp_path / "instance";candidate = instance / "pi-home/task-keeper/worktrees/job";candidate.mkdir(parents=True)
  state = tmp_path / "state";state.mkdir()
  manifest = {"options": {"paths": {"roots": {"project": {"path": str(project)}}}, "task_keeper": {"project_root": "project"}}, "permission_policy": {"rules": [{"kind": "file", "effect": "deny", "root_ref": "project", "relative_path": ".env"}]}}
  host = SimpleNamespace(config={"manifest_digest": digest(manifest), "instance_root": str(instance), "state_root": str(state), "protected_roots": [str(instance), str(state)]}, store=SimpleNamespace(workspaces=SimpleNamespace(identify=lambda _path: None)))
  creating = host_scope(host, manifest, source=project, candidate=candidate, creating=True)
  snapshot = host_scope(host, manifest, source=project, candidate=candidate, creating=False)
  assert creating["outside_exclusions"] == snapshot["outside_exclusions"]
  assert creating["protected_inputs"] == snapshot["protected_inputs"]
  assert creating["root_identity"] is None and snapshot["root_identity"] is not None
  # 私有祖先其余域的类别不授candidate外读取权；source创建仍不得进入该祖先。
  with pytest.raises(Conflict, match="ROOT_DENIED"):
    host_scope(host, manifest, source=candidate, candidate=candidate, creating=True)
