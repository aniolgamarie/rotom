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
  if isinstance(scope, dict) and scope.get("schema_version") == 2:
    return _validate_scope_v2(scope)
  if isinstance(scope, dict) and scope.get("scope_id") == "005-pi-two-profiles":
    raise ConfigError("pi-two-profiles-scope-version")
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
  if before["schema_version"] != after["schema_version"]: raise ConfigError("pi-scope-revision")
  if before["schema_version"] == 2:
    if before["scope_id"] != after["scope_id"] or after["revision"] != before["revision"] + 1 or before["stop_hook_selected"] and not after["stop_hook_selected"]:
      raise ConfigError("pi-scope-revision")
    if before["whole_process_isolation_decision"] != "undecided" and after["whole_process_isolation_decision"] != before["whole_process_isolation_decision"] and after["whole_process_isolation_decision"] != "supported":
      raise ConfigError("pi-scope-reduction-requires-specification-change")
    return
  if before["scope_id"] != after["scope_id"] or after["revision"] != before["revision"] + 1:
    raise ConfigError("pi-scope-revision")
  following = {item_key(item): item for item in after["items"]}
  for item in before["items"]:
    new = following.get(item_key(item))
    if item["applicability"] != "not_selected" and (not new or new["applicability"] != item["applicability"] or not set(item["levels"]) <= set(new["levels"])):
      raise ConfigError("pi-scope-reduction-requires-specification-change")


def report(scope, evidence_root):
  validate_scope(scope)
  if scope["schema_version"] == 2: return _report_v2(scope, evidence_root)
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


RESULTS_V2 = ("passed", "failed", "not-run", "needs-login", "unsupported")
EXECUTION_V2 = ("pending", "running", "blocked", "stalled", "finished")


def _fields(value, expected):
  if not isinstance(value, dict) or set(value) != set(expected): raise ConfigError("pi-two-profiles-fields")


def _identity_v2(value):
  _fields(value, ("runtime_digest", "config_digest", "input_snapshot_digest"))
  import re
  if any(not isinstance(part, str) or not re.fullmatch("[0-9a-f]{64}", part) for part in value.values()):
    raise ConfigError("pi-two-profiles-identity")


def _checker_v2(value):
  import re
  _fields(value, ("checker_id", "implementation_digest"))
  if not isinstance(value["checker_id"], str) or not re.fullmatch("[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value["checker_id"]) or not isinstance(value["implementation_digest"], str) or not re.fullmatch("[0-9a-f]{64}", value["implementation_digest"]):
    raise ConfigError("pi-two-profiles-checker")


def _platform_v2(value):
  _fields(value, ("os", "architecture", "engine"))
  if any(not isinstance(part, str) for part in value.values()) or value["os"] not in ("linux", "darwin") or value["architecture"] not in ("x86_64", "arm64") or value["engine"] not in ("node", "bun"):
    raise ConfigError("pi-two-profiles-platform")


def _tests_v2(value):
  _fields(value, ("discovered", "passed", "failed", "skipped"))
  if any(type(number) is not int or number < 0 for number in value.values()) or value["discovered"] != sum(value[key] for key in ("passed", "failed", "skipped")):
    raise ConfigError("pi-two-profiles-test-counts")


def _key_v2(item):
  if any(not isinstance(item[key], str) for key in ("check_id", "profile", "subitem_id")):
    raise ConfigError("pi-two-profiles-fields")
  return item["check_id"], item["profile"], item["subitem_id"]


def _validate_scope_v2(scope):
  from .pi_scope import TWO_PROFILES_SCOPE, two_profiles_items
  _fields(scope, ("schema_version", "scope_id", "revision", "created_at", "scope_digest", "stop_hook_selected", "serious_review_findings", "whole_process_isolation_decision", "items"))
  if type(scope["schema_version"]) is not int or scope["schema_version"] != 2 or scope["scope_id"] != TWO_PROFILES_SCOPE or type(scope["revision"]) is not int or scope["revision"] < 1:
    raise ConfigError("pi-two-profiles-scope")
  if type(scope["stop_hook_selected"]) is not bool or scope["serious_review_findings"] is not None and (type(scope["serious_review_findings"]) is not int or scope["serious_review_findings"] < 0):
    raise ConfigError("pi-two-profiles-scope")
  timestamp(scope["created_at"])
  if scope["scope_digest"] != digest({key: value for key, value in scope.items() if key != "scope_digest"}): raise ConfigError("pi-scope-digest")
  if scope["whole_process_isolation_decision"] not in ("undecided", "supported", "unsupported"): raise ConfigError("pi-two-profiles-isolation-decision")
  expected = {_key_v2(item): item for item in two_profiles_items(stop_hook_selected=scope["stop_hook_selected"], whole_process_isolation_decision=scope["whole_process_isolation_decision"])}
  if not isinstance(scope["items"], list) or len(scope["items"]) != len(expected): raise ConfigError("pi-two-profiles-scope-reduction")
  seen = set()
  for item in scope["items"]:
    _fields(item, next(iter(expected.values())).keys())
    key = _key_v2(item)
    if key not in expected or key in seen: raise ConfigError("pi-two-profiles-scope-reduction")
    seen.add(key)
    if any(item[field] != expected[key][field] for field in item if field not in ("identity", "checker", "evidence_paths")):
      raise ConfigError("pi-two-profiles-applicability")
    if item["identity"] is not None: _identity_v2(item["identity"])
    if item["checker"] is not None: _checker_v2(item["checker"])
    _platform_v2(item["platform"])
    if not isinstance(item["evidence_paths"], list) or any(not isinstance(path, str) for path in item["evidence_paths"]): raise ConfigError("pi-evidence-path")
    if len(set(item["evidence_paths"])) != len(item["evidence_paths"]): raise ConfigError("pi-evidence-path")
    for path in item["evidence_paths"]: evidence_path(path)
  return scope


def _read_v2(root, path):
  with Tree(root, private=False) as tree: raw = tree.read(evidence_path(path), max_bytes=1024 * 1024)
  if raw is None: return None
  if raw[1] & 0o022: raise Conflict("PI_EVIDENCE_WRITABLE_BY_OTHERS")
  try: return json.loads(raw[0])
  except (ValueError, UnicodeError): raise ConfigError("pi-evidence-json") from None


def _validate_evidence_v2(value, root, inputs):
  _fields(value, ("schema_version", "check_id", "profile", "subitem_id", "identity", "checker", "platform", "level", "result", "execution_state", "validity",
    "started_at", "finished_at", "command", "cwd", "exit_code", "termination_confirmed", "tests", "oracle", "artifacts", "reason"))
  if type(value["schema_version"]) is not int or value["schema_version"] != 2 or value["result"] not in RESULTS_V2 or value["execution_state"] not in EXECUTION_V2 or value["validity"] not in ("current", "stale", "invalid") or value["level"] not in ("U", "O", "P", "L", "V"):
    raise ConfigError("pi-two-profiles-evidence")
  _identity_v2(value["identity"])
  _checker_v2(value["checker"])
  _platform_v2(value["platform"])
  _tests_v2(value["tests"])
  tests = value["tests"]
  if value["exit_code"] is not None and type(value["exit_code"]) is not int or type(value["termination_confirmed"]) is not bool:
    raise ConfigError("pi-two-profiles-execution")
  if not isinstance(value["reason"], str) or not isinstance(value["command"], list) or any(not isinstance(part, str) or not part for part in value["command"]) or not isinstance(value["cwd"], str):
    raise ConfigError("pi-two-profiles-execution")
  if value["finished_at"] is not None:
    if timestamp(value["finished_at"]) < timestamp(value["started_at"]): raise ConfigError("pi-evidence-execution")
  elif value["started_at"] is not None: timestamp(value["started_at"])
  if not isinstance(value["artifacts"], dict) or not isinstance(value["oracle"], str): raise ConfigError("pi-two-profiles-artifacts")
  import hashlib
  import re
  intact = True
  oracle_raw = None
  for path, expected in value["artifacts"].items():
    if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected): raise ConfigError("pi-two-profiles-artifacts")
    with Tree(root, private=False) as tree: raw = tree.read(evidence_path(path), max_bytes=8 * 1024 * 1024)
    if raw is not None and raw[1] & 0o022: raise Conflict("PI_EVIDENCE_WRITABLE_BY_OTHERS")
    actual = hashlib.sha256(raw[0]).hexdigest() if raw else None
    inputs[path] = actual
    if actual != expected: intact = False
    if path == value["oracle"] and raw is not None: oracle_raw = raw[0]
  failed = value["result"] == "failed" or value["finished_at"] is not None and (value["exit_code"] not in (None, 0) or tests["failed"] or tests["discovered"] == 0 or tests["passed"] == 0)
  if not intact: return "invalid", "failed" if failed else "artifact-mismatch"
  # 非零、零测试、全跳过保持失败；不能靠 validity 字段掩盖真实失败。
  if failed:
    return "current", "failed"
  if value["result"] in ("passed", "unsupported"):
    if value["execution_state"] != "finished" or not value["finished_at"] or value["exit_code"] != 0 or not value["termination_confirmed"] or not value["command"] or not value["cwd"] or not value["artifacts"] or value["oracle"] not in value["artifacts"]:
      return "invalid", "proof-missing"
    return _validate_oracle_v2(oracle_raw, value)
  return value["validity"], value["result"]


def _validate_oracle_v2(raw, record):
  # 工件由 scope 选择的独立 checker 产生；散列只绑定内容，不能证明生产者权限。
  keys = ("schema_version", "check_id", "profile", "subitem_id", "identity", "checker", "platform", "level", "result", "execution_state", "exit_code", "termination_confirmed", "tests")
  try:
    oracle = json.loads(raw)
    _fields(oracle, (*keys, "assertions"))
    if type(oracle["schema_version"]) is not int or oracle["schema_version"] != 2: raise ConfigError("pi-two-profiles-oracle")
    _key_v2(oracle); _identity_v2(oracle["identity"]); _checker_v2(oracle["checker"])
    _platform_v2(oracle["platform"]); _tests_v2(oracle["tests"])
    _fields(oracle["assertions"], ("semantics_verified", "stopped"))
    if any(type(assertion) is not bool for assertion in oracle["assertions"].values()) or type(oracle["termination_confirmed"]) is not bool or type(oracle["exit_code"]) is not int:
      raise ConfigError("pi-two-profiles-oracle")
    if oracle["result"] not in RESULTS_V2 or oracle["level"] not in ("U", "O", "P", "L", "V") or oracle["execution_state"] not in EXECUTION_V2:
      raise ConfigError("pi-two-profiles-oracle")
  except (ConfigError, ValueError, UnicodeError, TypeError):
    return "invalid", "oracle-invalid"
  failed = oracle["result"] == "failed" or oracle["tests"]["failed"] or oracle["tests"]["passed"] == 0 or oracle["exit_code"] != 0 or not oracle["assertions"]["semantics_verified"]
  if any(oracle[key] != record[key] for key in keys): return "invalid", "failed" if failed else "oracle-mismatch"
  if oracle["execution_state"] != "finished" or not oracle["termination_confirmed"] or not oracle["assertions"]["stopped"]:
    return "invalid", "termination-unconfirmed"
  if failed: return "current", "failed"
  return record["validity"], record["result"]


def _report_v2(scope, evidence_root):
  rows = []; inputs = {}
  for item in scope["items"]:
    records = []
    for path in item["evidence_paths"]:
      value = _read_v2(evidence_root, path); inputs[path] = digest(value) if value else None
      if value is None: continue
      validity, result = _validate_evidence_v2(value, evidence_root, inputs)
      if _key_v2(value) != _key_v2(item): raise ConfigError("pi-evidence-reference")
      if value["identity"] != item["identity"] or value["platform"] != item["platform"]: validity = "stale"
      if item["checker"] is None or value["checker"] != item["checker"]:
        validity = "invalid"
        if result != "failed": result = "checker-unbound"
      records.append((value, validity, result))
    levels = {}
    for level in item["levels"]:
      candidates = [record for record in records if record[0]["level"] == level]
      matching = [record for record in candidates if record[0]["identity"] == item["identity"] and record[0]["platform"] == item["platform"]]
      result, validity, execution, reason = "not-run", "invalid", "pending", "evidence-missing"
      if matching:
        def observed_at(record):
          value = record[0]["finished_at"] or record[0]["started_at"]
          return timestamp(value).timestamp() if value else float("-inf")
        latest = max(observed_at(record) for record in matching)
        current = [record for record in matching if observed_at(record) == latest]
        if len({digest(record[0]) for record in current}) > 1: raise ConfigError("pi-evidence-ambiguous")
        value, validity, observed = current[0]; execution = value["execution_state"]
        result = observed if observed in RESULTS_V2 else "not-run"; reason = observed
      elif candidates: validity, reason = "stale", "identity-mismatch"
      if item["identity"] is None: result, validity, reason = "not-run", "invalid", "candidate-identity-unfrozen"
      if any(inputs[path] is None for path in item["evidence_paths"]): result, reason = "not-run", "evidence-missing"
      levels[level] = {"result": result, "validity": validity, "execution_state": execution, "reason": reason}
    result = next((status for status in ("failed", "needs-login", "unsupported", "not-run") if any(row["result"] == status for row in levels.values())), "passed")
    validity = next((state for state in ("invalid", "stale") if any(row["validity"] == state for row in levels.values())), "current")
    rows.append({**deepcopy(item), "result": result, "validity": validity,
      "execution_state": next((state for state in ("stalled", "blocked", "running", "pending") if any(row["execution_state"] == state for row in levels.values())), "finished"), "level_results": levels})
  def passed(selected):
    return bool(selected) and all(row["result"] == "passed" and row["validity"] == "current" and row["execution_state"] == "finished" for row in selected)
  required = [row for row in rows if row["applicability"] == "required"]
  feasibility = [row for row in required if row["check_id"] == "P05" and row["subitem_id"] == "feasibility"]
  decision = scope["whole_process_isolation_decision"]
  def investigation_closed(selected):
    expected = "passed" if decision == "supported" else "unsupported"
    return decision != "undecided" and bool(selected) and all(row["result"] == expected and row["validity"] == "current" and row["execution_state"] == "finished" and all(level["result"] == expected and level["validity"] == "current" for level in row["level_results"].values()) for row in selected)
  product = [row for row in required if row not in feasibility]
  profiles = {profile: passed([row for row in product if row["profile"] == profile and not row["check_id"].startswith("W")]) and investigation_closed([row for row in feasibility if row["profile"] == profile]) for profile in ("pi-base", "pi-full")}
  gates = {"base": profiles["pi-base"], "full": profiles["pi-base"] and profiles["pi-full"],
    "isolation": passed([row for row in product if row["check_id"] in ("P03", "P04", "P05")]) and investigation_closed(feasibility),
    "whole-process-feasibility": investigation_closed(feasibility),
    "maintenance": passed([row for row in required if row["check_id"].startswith("M")]),
    "linux-x86_64": passed(product) and investigation_closed(feasibility), "accounts": passed([row for row in required if row["check_id"] in ("S04", "S13", "F02", "F03")]),
    "experience": passed([row for row in required if row["check_id"] in ("S06", "S07", "S14", "F09", "M03", "M04")])}
  result = {"schema_version": 2, "scope_id": scope["scope_id"], "scope_revision": scope["revision"], "scope_digest": scope["scope_digest"],
    "input_digest": digest({"scope": scope, "evidence": inputs}), "report_generated": True, "candidate_frozen": all(row["identity"] is not None and row["checker"] is not None for row in required),
    "release_approved": all(gates.values()) and passed(product) and scope["serious_review_findings"] == 0,
    "whole_process_isolation_decision": decision,
    "profiles": profiles, "gates": gates, "counts": {status: sum(row["result"] == status for row in required) for status in RESULTS_V2}, "items": rows}
  result["report_digest"] = digest(result)
  return result
