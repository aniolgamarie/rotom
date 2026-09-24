"""预算裁剪与反馈关联不等于事实验证。"""

from copy import deepcopy
import pytest
from agentcfg.model_delegate_context import trim_context, validate_feedback, memory_context
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def context():
  return {"schema_version": 2, "artifact_id": "context", "task": "required task", "scope": ["src"], "constraints": ["keep required constraint"],
    "workspace": {"cwd": "/fixture/project", "candidate_digest": "a" * 64}, "facts": [{"id": "known", "text": "fact", "source": "user evidence", "status": "verified"}],
    "decisions": [], "hypotheses": [{"id": "guess", "text": "中文" * 1000, "source": "unverified", "status": "provisional"}], "references": [], "turn": 3,
    "budget": {"max_input_tokens": 2000}, "truncated": []}


def test_trim_keeps_authoritative_constraints_and_records_removed_material():
  value = context(); trimmed = trim_context(value, 1000)
  assert trimmed["task"] == value["task"] and trimmed["constraints"] == value["constraints"]
  assert trimmed["facts"] == value["facts"] and trimmed["hypotheses"] == []
  assert trimmed["truncated"] == ["hypotheses:1"] and value["hypotheses"]
  with pytest.raises(ConfigError): trim_context(value, 10)


def test_feedback_wrong_turn_candidate_or_artifact_fails_and_claimed_verified_is_not_promoted():
  value = context(); request = {"run_id": "run", "candidate_digest": "a" * 64}
  feedback = {"schema_version": 2, "artifact_id": "feedback-run", "run_id": "run", "context_artifact_id": "context", "turn": 3,
    "candidate_digest": "a" * 64, "facts": [{"id": "new", "text": "model claim", "source": "model", "status": "verified"}], "conflicts": [], "summary": "review"}
  checked, dispositions = validate_feedback(feedback, value, request)
  assert checked["facts"][0]["status"] == "unverified" and dispositions[0]["status"] == "provisional"
  for field, replacement in (("turn", 2), ("candidate_digest", "b" * 64), ("context_artifact_id", "old"), ("artifact_id", "wrong")):
    with pytest.raises(Conflict): validate_feedback({**feedback, field: replacement}, value, request)


def test_existing_memory_claim_revision_evidence_and_disputes_are_preserved_without_auto_verification():
  memory = {"revision": "42", "entries": [
    {"id": "decision", "kind": "decision", "claim": "use a local index", "status": "confirmed", "evidence": ["user decision"]},
    {"id": "dispute", "kind": "disputed", "claim": "requires followup", "status": "active"}]}
  value = memory_context(memory, task="inspect", cwd="/fixture/project", candidate_digest="a" * 64, limit=2000)
  assert value["references"] == ["memory-revision:42"]
  assert value["decisions"][0]["status"] == "provisional"
  assert value["decisions"][0]["source"] == "user decision"
  assert value["facts"][0]["status"] == "disputed"
  with pytest.raises(ConfigError): memory_context({**memory, "apiKey": "synthetic-private"}, task="inspect", cwd="/fixture/project", candidate_digest="a" * 64, limit=2000)
