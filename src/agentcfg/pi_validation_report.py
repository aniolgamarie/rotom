"""执行报告的闭合结构和状态一致性；它不是固定 scope 的发布证据。"""
from .pi_catalog import validate
from .pi_evidence import timestamp
from .schema import ConfigError


def validate_run_report(value, *, tier, case):
  validate("validation-run", value)
  if type(value["schema_version"]) is not int or value["tier"] != tier or value["case"] != case:
    raise ConfigError("pi-run-report-identity")
  rows = value["results"]
  if not rows:
    if value["status"] != "not-run" or not value.get("reason"): raise ConfigError("pi-run-report-empty")
    return value
  if timestamp(value.get("finished_at")) < timestamp(value.get("started_at")): raise ConfigError("pi-run-report-time")
  if tier == "mock":
    if len({row["runner"] for row in rows}) != len(rows): raise ConfigError("pi-run-report-duplicate")
    expected = "passed" if all(type(row["exit_code"]) is int and row["exit_code"] == 0 for row in rows) else "failed"
  elif tier == "native":
    from .pi_validation_native import scenarios
    if not value.get("source_digest") or [row["scenario_id"] for row in rows] != list(scenarios(case, value["runtime"]["profile"])):
      raise ConfigError("pi-run-report-scenarios")
    for row in rows:
      if row["status"] != "passed": continue
      if row["scenario_id"] == "cold-rebuild":
        targets = row.get("targets", [])
        if ([target.get("target") for target in targets] != ["first", "第二组 空格路径"]
            or any(target.get("installation") != "verified" or target.get("native_execution") != "passed" for target in targets)):
          raise ConfigError("pi-run-report-cold-incomplete")
      else:
        execution = row.get("execution", {})
        if (execution.get("exit_code") != 0 or execution.get("termination_confirmed") is not True or execution.get("timed_out") or execution.get("interrupted")
            or not row.get("facts")):
          raise ConfigError("pi-run-report-native-incomplete")
    expected = "failed" if any(row["status"] == "failed" for row in rows) else "not-run" if any(row["status"] == "not-run" for row in rows) else "passed"
  else:
    if len(rows) != 1 or not all(key in value for key in ("scope_digest", "native_report_digest", "identity", "runtime")):
      raise ConfigError("pi-run-report-live-unverified")
    if (value["identity"]["lock_digest"] != value["runtime"]["lock_identity"]
        or value["identity"]["runtime_digest"] != value["runtime"]["runtime_identity"]): raise ConfigError("pi-run-report-live-identity")
    from .pi_validation_live import CASE_CAPABILITIES, SCENARIOS
    row = rows[0]
    profile = value["runtime"]["profile"]
    capabilities = CASE_CAPABILITIES.get(case, set())
    matches = [name for name in capabilities if row["scenario_id"] in {profile + "." + suffix for suffix in SCENARIOS[name]}]
    if len(matches) != 1: raise ConfigError("pi-run-report-live-selection")
    if row["status"] == "passed":
      facts = row.get("facts", {})
      if matches[0] in ("mcp", "web", "terminal", "task-keeper"):
        from .pi_validation_live_services import service_facts_valid
        count = facts.get("mcp_servers_verified") if matches[0] == "mcp" else facts.get("web_providers_verified") if matches[0] == "web" else 3
        narrowed = {key: item for key, item in facts.items() if key not in ("scope_restricted", "termination_confirmed")}
        if (type(count) is not int or facts.get("scope_restricted") is not True or facts.get("termination_confirmed") is not True
            or not service_facts_valid(narrowed, matches[0], count)): raise ConfigError("pi-run-report-live-unverified")
        if matches[0] == "task-keeper" and row["scenario_id"].endswith(".second-view") and facts.get("second_view_verified") is not True:
          raise ConfigError("pi-run-report-live-unverified")
      elif (matches[0] not in ("codex", "cursor", "proxy")
          or not all(facts.get(key) is True for key in ("service_response_verified", "fresh_resume_verified", "cancellation_verified", "source_preserved", "termination_confirmed"))
          or facts.get("user_cli_operations") != ["cancel", "poll", "probe", "result", "resume", "start", "status", "wait"]
          or len(row.get("run_ids", [])) < (4 if matches[0] == "codex" else 3)
          or matches[0] == "codex" and facts.get("write_verified") is not True):
        raise ConfigError("pi-run-report-live-unverified")
    expected = row["status"]
  if value["status"] != expected: raise ConfigError("pi-run-report-status")
  return value
