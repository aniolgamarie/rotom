"""探针报告的纯数据oracle；不代表真实执行证据。"""

from copy import deepcopy
import importlib

import pytest

from agentcfg.schema import ConfigError


NONCE = "a" * 32
OBS = ("project_write", "project_read", "readonly_read", "readonly_write_blocked", "outside_read_blocked",
  "outside_write_blocked", "deny_read_blocked", "deny_write_blocked", "git_read_blocked", "git_write_blocked",
  "private_home_write", "private_tmp_write", "env_clean", "fds_only_stdio", "inet_socket_denied",
  "inet6_socket_denied", "unix_socket_denied", "socketpair_works", "system_readonly")
NS = ("pid", "net", "user", "mnt", "ipc", "uts")


def protocol():
  return importlib.import_module("agentcfg.pi_shell_probe_protocol")


def fixture(case="boundary"):
  outer = {key: key + ":[100]" for key in NS}
  inner = {key: key + ":[200]" for key in NS}
  prepared = {"schema_version": 1, "phase": "prepared", "case_id": case, "nonce": NONCE,
    "helper_identity": "b" * 64, "plan_digest": "c" * 64, "namespaces": outer}
  payload = {"schema_version": 1, "phase": "payload", "nonce": NONCE,
    "observations": {name: True for name in OBS}, "namespaces": inner}
  facts = {"exit_code": 0, "terminated": True, "positive": True, "canaries_unchanged": True,
    "blocked_files_absent": True, "heartbeat_before": 0, "heartbeat_after": 0,
    "namespace": outer["pid"], "helper_identity": "b" * 64, "stop_elapsed_ms": 0, "plan_digest": "c" * 64}
  events = [prepared, payload]
  if case == "helper-mismatch":
    facts["positive"] = False
    events = [{"schema_version": 1, "phase": "helper-rejected", "case_id": case, "nonce": NONCE, "code": "pi-shell-handoff"}]
  elif case == "descendants":
    facts.update(exit_code=5, heartbeat_before=3, heartbeat_after=3, stop_elapsed_ms=500)
    events.append({"schema_version": 1, "phase": "heartbeat", "nonce": NONCE, "pid": 20, "namespaces": deepcopy(inner)})
  return events, facts


@pytest.mark.parametrize("case", ["boundary", "helper-mismatch", "descendants"])
def test_valid_cases_are_pure_and_return_only_fixed_summary(case):
  events, facts = fixture(case); before = deepcopy((events, facts))
  assert protocol().CASES == ("boundary", "helper-mismatch", "descendants")
  assert protocol().verify_case(case, NONCE, events, facts) == {
    "case_id": case, "outcome": "observed", "checks": 0 if case == "helper-mismatch" else 19, "termination_observed": True}
  assert (events, facts) == before


def test_descendant_payload_and_heartbeat_can_arrive_either_order():
  events, facts = fixture("descendants"); events[1:] = events[:0:-1]
  assert protocol().verify_case("descendants", NONCE, events, facts)["checks"] == 19


def refused(case, events, facts, nonce=NONCE):
  with pytest.raises(ConfigError) as caught: protocol().verify_case(case, nonce, events, facts)
  assert str(caught.value) == "配置校验失败: pi-shell-probe-observation"


@pytest.mark.parametrize("name", OBS)
def test_every_observation_is_required_true(name):
  events, facts = fixture(); events[1]["observations"][name] = False
  refused("boundary", events, facts)


@pytest.mark.parametrize("key", ["terminated", "positive", "canaries_unchanged", "blocked_files_absent"])
def test_parent_positive_and_termination_evidence_required(key):
  events, facts = fixture(); facts[key] = False; refused("boundary", events, facts)


@pytest.mark.parametrize("fault", ["case", "nonce", "nonce-uppercase", "events-type", "events-size", "missing", "duplicate", "order",
  "extra-event", "extra-fact", "extra-prepared", "extra-payload", "extra-observation", "missing-observation", "nonbool-observation",
  "schema-bool", "schema-version", "event-nonce", "event-case", "helper", "plan", "exit", "exit-bool", "heartbeat-bool",
  "heartbeat-negative", "heartbeat-before", "heartbeat-after", "fact-namespace", "helper-fact"])
def test_malformed_boundary_reports_are_fixed_refusals(fault):
  events, facts = fixture(); case = "boundary"; nonce = NONCE
  if fault == "case": case = "private-case"
  elif fault == "nonce": nonce = "private-nonce"
  elif fault == "nonce-uppercase": nonce = "A" * 32
  elif fault == "events-type": events = tuple(events)
  elif fault == "events-size": events *= 3
  elif fault == "missing": events.pop()
  elif fault == "duplicate": events.append(deepcopy(events[1]))
  elif fault == "order": events.reverse()
  elif fault == "extra-event": events.append({"private-field": "secret"})
  elif fault == "extra-fact": facts["private-field"] = "secret"
  elif fault == "extra-prepared": events[0]["private-field"] = "secret"
  elif fault == "extra-payload": events[1]["private-field"] = "secret"
  elif fault == "extra-observation": events[1]["observations"]["private-field"] = True
  elif fault == "missing-observation": del events[1]["observations"][OBS[0]]
  elif fault == "nonbool-observation": events[1]["observations"][OBS[0]] = 1
  elif fault == "schema-bool": events[0]["schema_version"] = True
  elif fault == "schema-version": events[1]["schema_version"] = 2
  elif fault == "event-nonce": events[1]["nonce"] = "d" * 32
  elif fault == "event-case": events[0]["case_id"] = "descendants"
  elif fault == "helper": events[0]["helper_identity"] = "d" * 64
  elif fault == "plan": events[0]["plan_digest"] = "private-digest"
  elif fault == "exit": facts["exit_code"] = 1
  elif fault == "exit-bool": facts["exit_code"] = False
  elif fault == "heartbeat-bool": facts["heartbeat_before"] = False
  elif fault == "heartbeat-negative": facts["heartbeat_after"] = -1
  elif fault == "heartbeat-before": facts["heartbeat_before"] = 1
  elif fault == "heartbeat-after": facts["heartbeat_after"] = 1
  elif fault == "fact-namespace": facts["namespace"] = "pid:[999]"
  else: facts["helper_identity"] = "private-hash"
  refused(case, events, facts, nonce)


@pytest.mark.parametrize("key", NS)
@pytest.mark.parametrize("fault", ["same", "format", "extra", "missing"])
def test_each_inner_namespace_must_be_strict_and_different(key, fault):
  events, facts = fixture()
  if fault == "same": events[1]["namespaces"][key] = events[0]["namespaces"][key]
  elif fault == "format": events[1]["namespaces"][key] = "private-target"
  elif fault == "extra": events[1]["namespaces"]["private"] = "pid:[1]"
  else: del events[1]["namespaces"][key]
  refused("boundary", events, facts)


@pytest.mark.parametrize("fault", ["no-heartbeat", "duplicate", "first", "ns", "pid-bool", "pid-one", "zero-before", "increasing", "exit-zero", "extra-field"])
def test_descendant_termination_and_heartbeat_are_exact(fault):
  events, facts = fixture("descendants")
  if fault == "no-heartbeat": events.pop()
  elif fault == "duplicate": events.append(deepcopy(events[2]))
  elif fault == "first": events.reverse()
  elif fault == "ns": events[2]["namespaces"]["net"] = "net:[300]"
  elif fault == "pid-bool": events[2]["pid"] = True
  elif fault == "pid-one": events[2]["pid"] = 1
  elif fault == "zero-before": facts.update(heartbeat_before=0, heartbeat_after=0)
  elif fault == "increasing": facts["heartbeat_after"] += 1
  elif fault == "exit-zero": facts["exit_code"] = 0
  else: events[2]["extra"] = "secret"
  refused("descendants", events, facts)


@pytest.mark.parametrize("fault", ["positive", "exit", "heartbeat", "code", "case", "nonce", "extra", "duplicate"])
def test_helper_mismatch_is_only_a_fixed_rejection(fault):
  events, facts = fixture("helper-mismatch")
  if fault == "positive": facts["positive"] = True
  elif fault == "exit": facts["exit_code"] = 5
  elif fault == "heartbeat": facts["heartbeat_before"] = 1
  elif fault == "code": events[0]["code"] = "private-error"
  elif fault == "case": events[0]["case_id"] = "boundary"
  elif fault == "nonce": events[0]["nonce"] = "d" * 32
  elif fault == "extra": events[0]["private"] = "secret"
  else: events *= 2
  refused("helper-mismatch", events, facts)


@pytest.mark.parametrize("key", ["terminated", "positive", "canaries_unchanged", "blocked_files_absent"])
@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_parent_booleans_do_not_accept_coercions(key, value):
  events, facts = fixture(); facts[key] = value
  refused("boundary", events, facts)


@pytest.mark.parametrize("fault", ["facts-list", "fact-missing", "events-null", "events-empty", "event-null", "event-list",
  "phase-missing", "phase-list", "observations-list", "namespaces-null", "outer-namespace", "receipt-hash-type", "nonce-type"])
def test_non_json_shaped_or_incomplete_input_is_fixed_refusal(fault):
  events, facts = fixture(); nonce = NONCE
  if fault == "facts-list": facts = []
  elif fault == "fact-missing": del facts["positive"]
  elif fault == "events-null": events = None
  elif fault == "events-empty": events = []
  elif fault == "event-null": events[0] = None
  elif fault == "event-list": events[0] = []
  elif fault == "phase-missing": del events[0]["phase"]
  elif fault == "phase-list": events[0]["phase"] = []
  elif fault == "observations-list": events[1]["observations"] = []
  elif fault == "namespaces-null": events[0]["namespaces"] = None
  elif fault == "outer-namespace": events[0]["namespaces"]["user"] = "net:[100]"
  elif fault == "receipt-hash-type": facts["helper_identity"] = 1
  else: nonce = None
  refused("boundary", events, facts, nonce)


@pytest.mark.parametrize("case", ["boundary", "helper-mismatch", "descendants"])
@pytest.mark.parametrize("timing", ["missing", True, -1, 10000])
def test_stop_timing_is_required_and_strictly_bounded(case, timing):
  events, facts = fixture(case)
  if timing == "missing": del facts["stop_elapsed_ms"]
  else: facts["stop_elapsed_ms"] = timing
  refused(case, events, facts)


@pytest.mark.parametrize("case", ["boundary", "helper-mismatch"])
def test_non_descendant_case_requires_zero_stop_timing(case):
  events, facts = fixture(case); facts["stop_elapsed_ms"] = 1
  refused(case, events, facts)


@pytest.mark.parametrize("timing", [0, 9999])
def test_descendant_stop_before_ten_seconds_is_accepted(timing):
  events, facts = fixture("descendants"); facts["stop_elapsed_ms"] = timing
  assert protocol().verify_case("descendants", NONCE, events, facts)["termination_observed"] is True


@pytest.mark.parametrize("value", ["d" * 64, True, "private-invalid"])
def test_parent_plan_digest_must_match_prepared_event(value):
  events, facts = fixture(); facts["plan_digest"] = value
  refused("boundary", events, facts)
