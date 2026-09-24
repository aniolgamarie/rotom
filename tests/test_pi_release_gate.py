"""固定范围的汇总和批准，不启动宿主或读取未列出的文件。"""
from copy import deepcopy
import json
import pytest

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree, Conflict
from test_pi_evidence_schema import evidence


def scope(*, optional=False):
  row = evidence()
  item = {"capability_id": row["capability_id"], "scenario_id": row["test_case_id"], "identity": row["identity"],
    "platform": row["platform"], "applicability": "required", "levels": ["mock", "native"], "evidence_paths": [], "selection_reason": "specification"}
  value = {"schema_version": 1, "scope_id": "fixture", "revision": 1, "created_at": "2026-09-17T00:00:00Z", "items": [item]}
  if optional: value["items"].append({**deepcopy(item), "capability_id": "optional-login", "applicability": "not_selected", "levels": ["live"], "selection_reason": "user did not select"})
  return seal(value)


def seal(value):
  value["scope_digest"] = digest({key: item for key, item in value.items() if key != "scope_digest"})
  return value


def passed(level="mock", **patch):
  return {**evidence(), "level": level, "status": "passed", "started_at": "2026-09-17T00:00:01Z", "finished_at": "2026-09-17T00:00:02Z", "command": ["fixture-test"], **patch}


def save(root, name, value):
  with Tree(root, create=True) as tree: tree.write_immutable(name, json_bytes(value))


def test_zero_evidence_report_is_successful_but_release_is_blocked(tmp_path):
  from agentcfg.pi_acceptance import report
  result = report(scope(optional=True), tmp_path / "missing")
  assert result["report_generated"] and not result["release_approved"]
  assert result["counts"] == {"passed": 0, "failed": 0, "not-run": 1, "stale": 0, "not-selected": 1}
  assert result["applicable_items"] == 1
  assert result["items"][0]["levels"]["native"]["status"] == "not-run"


def test_latest_matching_failure_wins_over_old_success_and_identity_changes_are_stale(tmp_path):
  from agentcfg.pi_acceptance import report
  value = scope(); item = value["items"][0]
  item["evidence_paths"] = ["mock.json", "native.json", "failed.json"]
  save(tmp_path, "mock.json", passed()); save(tmp_path, "native.json", passed("native"))
  save(tmp_path, "failed.json", passed("native", status="failed", finished_at="2026-09-17T00:00:03Z"))
  assert report(seal(value), tmp_path)["items"][0]["status"] == "failed"
  item["identity"]["policy_digest"] = "b" * 64
  result = report(seal(value), tmp_path)
  assert result["items"][0]["status"] == "stale" and not result["release_approved"]


def test_selected_optional_missing_authorization_blocks_and_scope_changes_invalidate_approval(tmp_path):
  from agentcfg.pi_acceptance import report, approval_matches
  value = scope(optional=True); value["items"][0]["evidence_paths"] = ["mock.json", "native.json"]
  save(tmp_path, "mock.json", passed()); save(tmp_path, "native.json", passed("native"))
  seal(value); approved = report(value, tmp_path)
  assert approved["release_approved"] and approval_matches(approved, value, tmp_path)
  value["items"][1]["applicability"] = "selected_optional"; value["revision"] += 1; seal(value)
  assert not approval_matches(approved, value, tmp_path)
  assert not report(value, tmp_path)["release_approved"]


@pytest.mark.parametrize("bad", ["schema", "identity", "reference", "symlink", "duplicate", "timestamp", "empty-proof"])
def test_corrupt_or_ambiguous_inputs_are_errors_and_never_silently_ignored(tmp_path, bad):
  from agentcfg.pi_acceptance import report
  value = scope(); value["items"][0]["levels"] = ["mock"]; value["items"][0]["evidence_paths"] = ["result.json"]
  record = passed()
  if bad == "schema": record["unknown"] = "synthetic secret never shown"
  if bad == "identity": value["scope_digest"] = "0" * 64
  if bad == "reference": record["capability_id"] = "another-capability"
  if bad == "timestamp": record["finished_at"] = "2026-02-31T00:00:00Z"
  if bad == "empty-proof": record.update(started_at=None, finished_at=None)
  if bad == "duplicate": value["items"].append(deepcopy(value["items"][0]))
  if bad == "symlink":
    save(tmp_path, "outside.json", record); (tmp_path / "result.json").symlink_to(tmp_path / "outside.json")
  else: save(tmp_path, "result.json", record)
  if bad != "identity": seal(value)
  with pytest.raises((ConfigError, Conflict)): report(value, tmp_path)


def test_reader_only_reads_explicit_paths_and_storage_refuses_overwrite(tmp_path):
  from agentcfg.pi_evidence import EvidenceStore
  from agentcfg.pi_acceptance import report
  store = EvidenceStore(tmp_path)
  store.write("mock.json", passed())
  assert (tmp_path / "mock.json").stat().st_mode & 0o777 == 0o600
  with pytest.raises(Conflict): store.write("mock.json", passed())
  (tmp_path / "unlisted-auth.json").write_text("not JSON, must not read")
  value = scope(); value["items"][0].update(levels=["mock"], evidence_paths=["mock.json"])
  assert report(seal(value), tmp_path)["release_approved"]
  for path in ("../mock.json", "/mock.json", "*.json"):
    with pytest.raises(ConfigError): store.read(path)


def test_scope_revision_cannot_automatically_remove_required_platforms(tmp_path):
  from agentcfg.pi_acceptance import validate_revision
  before = scope(optional=True); after = deepcopy(before)
  after["revision"] += 1; after["items"] = after["items"][1:]; seal(after)
  with pytest.raises(ConfigError, match="scope-reduction"): validate_revision(before, after)


def test_mixed_matrix_preserves_all_five_states_and_selection_reason(tmp_path):
  from agentcfg.pi_acceptance import report
  value = scope(); template = value["items"][0]; value["items"] = []
  for index, status in enumerate(("passed", "failed", "not-run", "stale", "not-selected")):
    item = {**deepcopy(template), "capability_id": "cap-" + str(index), "levels": ["live"]}
    item["evidence_paths"] = [str(index) + ".json"] if status in ("passed", "failed", "stale") else []
    if status == "not-selected": item.update(applicability="not_selected", selection_reason="explicitly unselected")
    if item["evidence_paths"]:
      record = passed("live", capability_id=item["capability_id"], status="failed" if status == "failed" else "passed")
      if status == "stale": record["identity"] = {**record["identity"], "runtime_digest": "b" * 64}
      save(tmp_path, item["evidence_paths"][0], record)
    value["items"].append(item)
  result = report(seal(value), tmp_path)
  assert result["counts"] == {key: 1 for key in ("passed", "failed", "not-run", "stale", "not-selected")}
  assert result["applicable_items"] == 4 and not result["release_approved"]
  assert result["items"][-1]["selection_reason"] == "explicitly unselected"


def test_unfrozen_scope_never_uses_placeholder_identity_or_approves(tmp_path):
  from agentcfg.pi_acceptance import report
  from agentcfg.pi_scope import initial_scope, OPTIONAL, support_markdown
  value = initial_scope(optional_selected={key: True for key in OPTIONAL}, created_at="2026-09-17T00:00:00Z")
  assert all(item["identity"] is None for item in value["items"])
  assert {tuple(item["platform"][key] for key in ("os", "architecture")) for item in value["items"]} == {
    ("linux", "x86_64"), ("linux", "arm64"), ("darwin", "arm64"), ("darwin", "x86_64")}
  result = report(value, tmp_path)
  assert not result["candidate_frozen"] and not result["release_approved"]
  assert result["counts"]["not-selected"] == 0 and result["counts"]["passed"] == 0
  assert "尚未冻结" in support_markdown(result)
