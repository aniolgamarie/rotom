"""真实执行状态与验收选择必须在 schema 层分开。"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry


ROOT = Path(__file__).resolve().parents[1] / "agents/pi/schemas"


def validator(name):
  schema = json.loads((ROOT / name).read_text())
  Draft202012Validator.check_schema(schema)
  return Draft202012Validator(schema, registry=Registry(), format_checker=Draft202012Validator.FORMAT_CHECKER)


def evidence():
  return {
    "schema_version": 1, "capability_id": "pi-read", "test_case_id": "V01",
    "level": "mock", "identity": {key: "a" * 64 for key in (
      "lock_digest", "runtime_digest", "policy_digest", "resource_digest", "machine_contract_digest")},
    "platform": {"os": "linux", "architecture": "x86_64", "engine": "node"},
    "started_at": None, "finished_at": None, "status": "not-run",
    "command": [], "artifact_refs": [], "limitations": [], "reason": "not authorized",
  }


def test_evidence_accepts_unexecuted_record_without_claiming_success():
  validator("evidence.schema.json").validate(evidence())


@pytest.mark.parametrize("patch", [
  {"schema_version": 2}, {"status": "not-selected"}, {"status": "stale"},
  {"raw_secret": "synthetic"}, {"level": "production"}, {"finished_at": "yesterday"},
])
def test_evidence_rejects_unknown_versions_fields_and_pseudo_execution_states(patch):
  with pytest.raises(ValidationError):
    validator("evidence.schema.json").validate({**evidence(), **patch})


def test_selection_is_independent_from_evidence():
  record = evidence()
  item = {"capability_id": "codex", "scenario_id": "V16", "identity": record["identity"],
    "platform": record["platform"], "applicability": "not_selected", "levels": ["live"],
    "evidence_paths": [], "selection_reason": "explicitly not selected"}
  validator("acceptance-item.schema.json").validate(item)
  for path in ("../auth.json", "/auth.json", "dir/../auth.json"):
    with pytest.raises(ValidationError):
      validator("acceptance-item.schema.json").validate({**item, "evidence_paths": [path]})
