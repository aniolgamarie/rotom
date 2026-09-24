"""原生Codex路线的替身验收：允许候选结果变化，不要求MCP日志，不启动真实CLI。"""

import json
from pathlib import Path
import pytest

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.model_delegate_backends import codex_permissions
from agentcfg.pi_delegate_policy import record_native_authorization, verify_execution_policy
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict, Tree
from test_pi_delegate_files import writer


def native_run(tmp_path):
  def configure(host):
    instance = Path(host.config["instance_root"])
    binding = {"machine": "fixture", "local": str(tmp_path / "local.toml"), "profile": "pi-fixture"}
    host.store.owner["instance_id"] = digest({"instance": str(instance), "binding": binding})
    with Tree(instance, create=True) as tree:
      tree.write_state(".agentcfg-instance.json", json_bytes({"schema_version": 1, "binding": binding, "state_root": str(host.root)}))
    rule = host.manifest()["permission_policy"]["rules"][0]
    rule["operations"] = ["read", "list", "search", "write", "create", "delete", "rename"]
  controller, host, source, candidate, request, _ = writer(tmp_path, configure=configure)
  home = tmp_path / "native-home"; home.mkdir(mode=0o700)
  scratch = tmp_path / "scratch"; scratch.mkdir(mode=0o700)
  value = controller.input(request["run_id"])
  permissions = codex_permissions(host.manifest()["permission_policy"], value["grant"], runtime_root=host.runtime_root,
    codex_home=home, scratch=scratch, native=value["execution_policy"]["native_execution"], root_limits=value["execution_policy"]["root_limits"])
  record_native_authorization(controller.root, request, permissions)
  return controller, host, source, candidate, request


def complete(controller, host, request):
  lease = host.store.read(request["lease_id"])
  with Tree(controller.root) as tree:
    prefix = "reports/" + request["run_id"] + "/"
    tree.write_state(prefix + "ready.json", json_bytes({"ready": True, **{key: request[key] for key in ("run_id", "lease_id", "request_digest")}}))
    tree.write_state(prefix + "event-000000000001.json", json_bytes({"schema_version": 2, "run_id": request["run_id"], "seq": 1,
      "timestamp": "2026-09-17T00:00:00Z", "kind": "completed", "phase": "turn-completed", "artifact_id": None}))
    tree.write_state(prefix + "final.md", b"fixture implementation result")
    tree.write_state(prefix + "result.json", json_bytes({"schema_version": 2, "run_id": request["run_id"], "attempt_id": request["attempt_id"],
      "request_digest": request["request_digest"], "process_identity": lease["process_identity"], "host_completed": True,
      "observed_model": None, "resume_token": "native-session", "usage": {"input_tokens": None, "output_tokens": None, "cost": None}, "feedback_dispositions": []}))
  with Tree(host.root) as tree:
    tree.write_state("activity/exits/" + lease["lease_id"] + ".json", json_bytes({"schema_version": 1, "lease_id": lease["lease_id"], "process_identity": lease["process_identity"], "exit_code": 0}))
  host.store.processes.current.pop(201)
  host.store.finish(lease["lease_id"], host.store.owner)
  return controller.refresh(request["run_id"])


def test_native_candidate_write_has_its_own_authorization_and_result_proof(tmp_path):
  controller, host, source, candidate, request = native_run(tmp_path)
  (candidate / "code.txt").write_text("fake native edit")
  assert not (controller.root / "mutations").exists()
  assert complete(controller, host, request)["verification"] == "verified-execution"
  assert (source / "code.txt").read_text() == "source"
  reply = controller.handle(Principal("delegate"), "delegate_result", {"run_id": request["run_id"]})
  assert reply["receipt"]["execution_boundary"] == "native-sandbox"
  assert reply["receipt"]["execution_policy_digest"] == request["execution_policy_digest"]
  from agentcfg.model_delegate_cli import saved_status
  assert saved_status(Path(host.config["instance_root"]), request["run_id"])["verification"] == "verified-execution"
  # CLI模式的结果不依赖控制层变更日志；仍独立检查授权和当前候选。
  proof = controller.root / "native-authorizations" / (request["run_id"] + ".json")
  proof.unlink()
  with pytest.raises(Conflict, match="POLICY_UNVERIFIED"):
    saved_status(Path(host.config["instance_root"]), request["run_id"])
  with pytest.raises(Conflict, match="POLICY_UNVERIFIED"):
    controller.handle(Principal("delegate"), "delegate_result", {"run_id": request["run_id"]})


def test_native_result_without_launch_authorization_is_not_success(tmp_path):
  controller, host, _, candidate, request = native_run(tmp_path)
  (candidate / "code.txt").write_text("fake native edit")
  (controller.root / "native-authorizations" / (request["run_id"] + ".json")).unlink()
  result = complete(controller, host, request)
  assert result["state"] == "failed" and result["verification"] == "unverified"


def test_native_grant_cannot_use_controlled_file_rpc_or_prototype_command_routes(tmp_path):
  from agentcfg.schema import ConfigError
  controller, host, _, _, request = native_run(tmp_path)
  principal = Principal("worker", request["lease_id"], request["grant_generation"])
  with pytest.raises(Conflict, match="EXECUTION_BOUNDARY"):
    controller.handle(principal, "delegate_file_action", {"run_id": request["run_id"]})
  for method in ("delegate_command_start", "delegate_command_status", "delegate_command_list"):
    with pytest.raises((ConfigError, Conflict)): controller.handle(principal, method, {"run_id": request["run_id"]})
  assert "bash" not in controller.input(request["run_id"])["grant"]["allowed_tools"]


def test_native_policy_change_revokes_whole_execution_but_keeps_writer_protected(tmp_path):
  controller, host, _, candidate, request = native_run(tmp_path)
  host.manifest()["options"]["model_delegate"]["codex"]["native_execution"]["allow_shell"] = False
  controller.tick()
  lease = host.store.read(request["lease_id"])
  assert lease["state"] == "cancel_requested" and lease["grant_generation"] > request["grant_generation"]
  assert host.store.workspaces.read(host.store.workspaces.identify(candidate))["state"] != "released"
  assert host.store.reconcile(lease["lease_id"])["protected"] is True


def test_native_authorization_digest_cannot_be_reused_for_other_run_or_policy(tmp_path):
  controller, _, _, _, request = native_run(tmp_path)
  path = "native-authorizations/" + request["run_id"] + ".json"
  with Tree(controller.root) as tree:
    value = json.loads(tree.read(path)[0]); value["execution_policy_digest"] = "0" * 64
    value["authorization_digest"] = digest({key: item for key, item in value.items() if key != "authorization_digest"})
    tree.write_state(path, json_bytes(value))
  with pytest.raises(Conflict, match="POLICY_UNVERIFIED"): verify_execution_policy(controller.root, request)


def test_native_request_must_bind_the_current_configuration_admission_policy(tmp_path):
  from agentcfg.pi_delegate_policy import validate_policy_binding
  controller, _, _, _, request = native_run(tmp_path)
  value = controller.input(request["run_id"])
  assert value["execution_policy"]["configuration_admission"] == "official-cli-restricted-v1"
  value["execution_policy"]["configuration_admission"] = "old-unchecked-policy"
  value["request"]["execution_policy_digest"] = digest(value["execution_policy"])
  with pytest.raises(Conflict, match="CONFIGURATION_POLICY_MISMATCH"):
    validate_policy_binding(value)
