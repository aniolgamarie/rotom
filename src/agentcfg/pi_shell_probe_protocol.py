"""自有Shell探针的纯数据oracle；报告校验本身不能证明真实执行或隔离。"""

import re

from .schema import ConfigError


CASES = ("boundary", "helper-mismatch", "descendants")
NAMESPACES = ("pid", "net", "user", "mnt", "ipc", "uts")
OBSERVATIONS = ("project_write", "project_read", "readonly_read", "readonly_write_blocked", "outside_read_blocked",
  "outside_write_blocked", "deny_read_blocked", "deny_write_blocked", "git_read_blocked", "git_write_blocked",
  "private_home_write", "private_tmp_write", "env_clean", "fds_only_stdio", "inet_socket_denied",
  "inet6_socket_denied", "unix_socket_denied", "socketpair_works", "system_readonly")
FACTS = ("exit_code", "terminated", "positive", "canaries_unchanged", "blocked_files_absent", "heartbeat_before",
  "heartbeat_after", "namespace", "helper_identity", "stop_elapsed_ms", "plan_digest")


def _check(valid):
  if not valid: raise ConfigError("pi-shell-probe-observation")


def _closed(value, fields):
  _check(type(value) is dict and set(value) == set(fields))


def _hex(value, length):
  _check(type(value) is str and re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None)


def _namespace(value, name):
  _check(type(value) is str and re.fullmatch(name + r":\[[0-9]+\]", value) is not None)


def _namespaces(value):
  _closed(value, NAMESPACES)
  for name in NAMESPACES: _namespace(value[name], name)


def verify_case(case, nonce, events, facts):
  """只返回固定结论，任何失败均不携带原始输入或底层异常。"""
  _check(type(case) is str and case in CASES)
  _hex(nonce, 32)
  _check(type(events) is list and len(events) <= 4)
  _closed(facts, FACTS)
  _check(type(facts["exit_code"]) is int)
  for name in ("terminated", "positive", "canaries_unchanged", "blocked_files_absent"):
    _check(type(facts[name]) is bool)
  for name in ("heartbeat_before", "heartbeat_after", "stop_elapsed_ms"):
    _check(type(facts[name]) is int and facts[name] >= 0)
  _namespace(facts["namespace"], "pid")
  _hex(facts["helper_identity"], 64); _hex(facts["plan_digest"], 64)
  _check(facts["terminated"] and facts["canaries_unchanged"] and facts["blocked_files_absent"])
  for event in events:
    _check(type(event) is dict)
    phase = event.get("phase")
    _check(type(phase) is str)
    if phase == "prepared":
      _closed(event, ("schema_version", "phase", "case_id", "nonce", "helper_identity", "plan_digest", "namespaces"))
      _check(type(event["case_id"]) is str and event["case_id"] == case)
      _hex(event["helper_identity"], 64); _hex(event["plan_digest"], 64)
      _namespaces(event["namespaces"])
    elif phase == "payload":
      _closed(event, ("schema_version", "phase", "nonce", "observations", "namespaces"))
      _closed(event["observations"], OBSERVATIONS)
      _check(all(type(value) is bool and value for value in event["observations"].values()))
      _namespaces(event["namespaces"])
    elif phase == "heartbeat":
      _closed(event, ("schema_version", "phase", "nonce", "pid", "namespaces"))
      _check(type(event["pid"]) is int and event["pid"] > 1)
      _namespaces(event["namespaces"])
    elif phase == "helper-rejected":
      _closed(event, ("schema_version", "phase", "case_id", "nonce", "code"))
      _check(type(event["case_id"]) is str and event["case_id"] == "helper-mismatch"
        and type(event["code"]) is str and event["code"] == "pi-shell-handoff")
    else: _check(False)
    _check(type(event["schema_version"]) is int and event["schema_version"] == 1)
    _hex(event["nonce"], 32)
    _check(event["nonce"] == nonce)
  phases = [event["phase"] for event in events]
  if case == "helper-mismatch":
    _check(phases == ["helper-rejected"] and facts["exit_code"] == 0 and not facts["positive"]
      and facts["heartbeat_before"] == 0 and facts["heartbeat_after"] == 0 and facts["stop_elapsed_ms"] == 0)
    checks = 0
  else:
    _check(facts["positive"])
    if case == "boundary":
      _check(phases == ["prepared", "payload"] and facts["exit_code"] == 0
        and facts["heartbeat_before"] == 0 and facts["heartbeat_after"] == 0 and facts["stop_elapsed_ms"] == 0)
    else:
      _check(len(phases) == 3 and phases[0] == "prepared" and set(phases[1:]) == {"payload", "heartbeat"}
        and facts["exit_code"] != 0 and facts["heartbeat_before"] > 0
        and facts["heartbeat_after"] == facts["heartbeat_before"] and facts["stop_elapsed_ms"] < 10000)
    prepared = events[0]
    payload = next(event for event in events if event["phase"] == "payload")
    _check(prepared["helper_identity"] == facts["helper_identity"] and prepared["plan_digest"] == facts["plan_digest"] and prepared["namespaces"]["pid"] == facts["namespace"])
    _check(all(payload["namespaces"][name] != prepared["namespaces"][name] for name in NAMESPACES))
    if case == "descendants":
      heartbeat = next(event for event in events if event["phase"] == "heartbeat")
      _check(heartbeat["namespaces"] == payload["namespaces"])
    checks = len(OBSERVATIONS)
  return {"case_id": case, "outcome": "observed", "checks": checks, "termination_observed": True}
