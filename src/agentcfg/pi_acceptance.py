"""固定验收范围的汇总；报告成功与发布批准是两件事。"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from .activity import digest
from .deployment import json_bytes
from .pi_catalog import validate
from .pi_evidence import EvidenceStore, evidence_path, timestamp
from .schema import ConfigError
from .storage import Tree, Conflict


STATUSES = ("passed", "failed", "not-run", "stale", "not-selected")


def item_key(item):
  return (item["capability_id"], item["scenario_id"], *[item["platform"][key] for key in ("os", "architecture", "engine")])


def validate_scope(scope):
  validate("acceptance-scope", scope)
  timestamp(scope["created_at"])
  if scope["scope_digest"] != digest({key: value for key, value in scope.items() if key != "scope_digest"}):
    raise ConfigError("pi-scope-digest")
  keys = [item_key(item) for item in scope["items"]]
  if len(set(keys)) != len(keys): raise ConfigError("pi-scope-duplicate")
  for item in scope["items"]:
    if item["applicability"] == "not_selected" and item["levels"] != ["live"]:
      raise ConfigError("pi-scope-required-software")
    for path in item["evidence_paths"]: evidence_path(path)
  return scope


def read_scope(path):
  path = Path(path).absolute()
  with Tree(path.parent, private=False) as tree: raw = tree.read(path.name, max_bytes=8 * 1024 * 1024)
  if raw is None: raise ConfigError("pi-scope-missing")
  if raw[1] & 0o022: raise Conflict("PI_SCOPE_WRITABLE_BY_OTHERS")
  try: scope = json.loads(raw[0])
  except (ValueError, UnicodeError): raise ConfigError("pi-scope-json") from None
  return validate_scope(scope)


def validate_revision(before, after):
  validate_scope(before); validate_scope(after)
  if before["scope_id"] != after["scope_id"] or after["revision"] != before["revision"] + 1:
    raise ConfigError("pi-scope-revision")
  following = {item_key(item): item for item in after["items"]}
  for item in before["items"]:
    new = following.get(item_key(item))
    if item["applicability"] != "not_selected" and (not new or new["applicability"] != item["applicability"] or not set(item["levels"]) <= set(new["levels"])):
      raise ConfigError("pi-scope-reduction-requires-specification-change")


def report(scope, evidence_root):
  validate_scope(scope)
  store = EvidenceStore(evidence_root); rows = []; inputs = {}
  for item in scope["items"]:
    records = []
    for path in item["evidence_paths"]:
      value = store.read(path)
      inputs[path] = digest(value) if value else None
      if value is not None:
        if value["capability_id"] != item["capability_id"] or value["test_case_id"] != item["scenario_id"]:
          raise ConfigError("pi-evidence-reference")
        records.append(value)
    levels = {}
    for level in item["levels"]:
      status, reason = "not-run", "evidence-missing"
      candidates = [value for value in records if value["level"] == level]
      matching = [value for value in candidates if value["identity"] == item["identity"] and value["platform"] == item["platform"]]
      if matching:
        executed = [value for value in matching if value["finished_at"]]
        latest = max(timestamp(value["finished_at"]) for value in executed) if executed else None
        current = [value for value in matching if (timestamp(value["finished_at"]) if value["finished_at"] else None) == latest]
        if len({digest(value) for value in current}) > 1: raise ConfigError("pi-evidence-ambiguous")
        status = current[0]["status"]; reason = "matching-evidence" if status != "not-run" else "execution-not-run"
      elif candidates: status, reason = "stale", "identity-mismatch"
      if any(inputs[path] is None for path in item["evidence_paths"]): status, reason = "not-run", "evidence-missing"
      if item["identity"] is None: status, reason = "not-run", "candidate-identity-unfrozen"
      levels[level] = {"status": status, "reason": reason}
    statuses = {row["status"] for row in levels.values()}
    status = next((value for value in ("failed", "stale", "not-run") if value in statuses), "passed")
    if item["applicability"] == "not_selected": status = "not-selected"
    rows.append({"capability_id": item["capability_id"], "scenario_id": item["scenario_id"], "platform": deepcopy(item["platform"]),
      "applicability": item["applicability"], "selection_reason": item["selection_reason"], "status": status, "levels": levels, "evidence_paths": list(item["evidence_paths"])})
  counts = Counter(row["status"] for row in rows)
  applicable = len(rows) - counts["not-selected"]
  result = {"schema_version": 1, "scope_id": scope["scope_id"], "scope_revision": scope["revision"], "scope_digest": scope["scope_digest"],
    "input_digest": digest({"scope": scope, "evidence": inputs}), "report_generated": True,
    "candidate_frozen": all(item["identity"] is not None for item in scope["items"] if item["applicability"] != "not_selected"),
    "release_approved": applicable > 0 and counts["passed"] == applicable, "applicable_items": applicable,
    "counts": {key: counts[key] for key in STATUSES}, "items": rows}
  result["report_digest"] = digest(result)
  return result


def approval_matches(approved, scope, evidence_root):
  current = report(scope, evidence_root)
  return current["release_approved"] and approved == current


def write_report(path, value):
  from .storage import create_new_private_file
  create_new_private_file(path, json_bytes(value))
