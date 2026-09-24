"""两 backend 共用 V2 凭证；全部使用本地字典与替身，不执行宿主。"""

from copy import deepcopy
import pytest

from agentcfg.model_delegate import validate_record, verify_receipt, control_envelope, cursor, parse_cursor
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def request(backend="pi"):
  value = {"schema_version": 2, "run_id": "run-fixture", "attempt_id": "attempt-fixture", "backend": backend,
    "execution_boundary": "native-sandbox" if backend == "codex" else "agentcfg-tools", "execution_policy_digest": "9" * 64,
    "mode": "review", "preset": "review", "requested_model": {"provider_id": "fictional", "model_id": "fixture-model"},
    "cwd": "/fixture/project", "worktree_identity": "a" * 64, "execution_mode": "delegate-readonly",
    "policy_digest": "b" * 64, "runtime_identity": "c" * 64, "parent_task_id": None, "lease_id": "lease",
    "context_artifact_id": None, "workspace_write_lease_ids": [], "workspace_identity_digest": "a" * 64,
    "grant_generation": 1, "request_digest": "d" * 64, "instance_id": "fixture", "owner_nonce": "private-fixture",
    "timeout_seconds": 30, "continuation_of": None, "feedback_required": False, "candidate_digest": "f" * 64}
  return value


def receipt(value):
  return {**deepcopy(value), "terminal_status": "completed", "backend_resume_token": "session-fixture", "event_sequence_complete": True,
    "final_artifact_id": "final-fixture", "final_artifact_digest": "e" * 64, "process_terminated": True, "resources_reclaimed": True,
    "usage": {"input_tokens": None, "output_tokens": None, "cost": None}, "feedback_dispositions": [], "observed_model": None}


def proof(backend="pi"):
  return {"execution_boundary": "native-sandbox" if backend == "codex" else "agentcfg-tools", "execution_policy_digest": "9" * 64, "execution_policy_verified": True, "lease_id": "lease", "termination_verified": True, "resources_reclaimed": True, "exit_code": 0,
    "final_artifact_digest": "e" * 64, "final_nonempty": True, "sequence_complete": True, "host_completed": True,
    "candidate_digest": "f" * 64}


@pytest.mark.parametrize("backend", ["pi", "codex"])
def test_v2_current_receipt_requires_identity_nonempty_final_and_physical_evidence(backend):
  value = request(backend)
  assert verify_receipt(value, receipt(value), proof(backend))["verification"] == "verified-execution"
  for field, replacement in (("run_id", "old-run"), ("cwd", "/wrong"), ("runtime_identity", "a" * 64),
      ("observed_model", {"provider_id": "wrong", "model_id": "other"}), ("process_terminated", False),
      ("event_sequence_complete", False), ("schema_version", 1)):
    damaged = receipt(value); damaged[field] = replacement
    with pytest.raises((ConfigError, Conflict)):
      verify_receipt(value, damaged, proof(backend))
  for field in ("final_nonempty", "termination_verified", "host_completed", "sequence_complete"):
    with pytest.raises(Conflict):
      verify_receipt(value, receipt(value), {**proof(backend), field: False})


def test_request_unknown_fields_write_mode_and_cursor_are_closed():
  validate_record("request-v2", request())
  with pytest.raises(ConfigError):
    validate_record("request-v2", {**request(), "bypassQueue": True})
  with pytest.raises(ConfigError):
    validate_record("request-v2", {**request(), "mode": "implement"})
  assert parse_cursor("run", cursor("run", 7), 7) == 7
  for invalid in (cursor("other", 2), cursor("run", 8), "run:-1"):
    with pytest.raises(ConfigError):
      parse_cursor("run", invalid, 7)


def test_control_envelope_has_fixed_utf8_byte_limit_and_no_raw_result():
  value = control_envelope({"schema_version": 2, "run_id": "run", "state": "running", "artifact_ref": "a" * 20000})
  assert len(value) <= 4096
  assert b"a" * 5000 not in value
  with pytest.raises(ConfigError):
    control_envelope({"run_id": "run", "raw_error": "private fixture"})


def test_execution_boundary_is_backend_bound_and_cannot_be_changed_in_receipt_or_proof():
  value = request("codex")
  for key, bad in (("execution_boundary", "agentcfg-tools"), ("execution_policy_digest", "1" * 64)):
    with pytest.raises((ConfigError, Conflict)): verify_receipt(value, {**receipt(value), key: bad}, proof("codex"))
  with pytest.raises(Conflict): verify_receipt(value, receipt(value), {**proof("codex"), "execution_policy_verified": False})
  for key in ("execution_boundary", "execution_policy_digest"):
    old = dict(value); old.pop(key)
    with pytest.raises(ConfigError): validate_record("request-v2", old)
