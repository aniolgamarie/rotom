"""明确fake编译器/资格，组合真实临时账本；没有provider、SDK或私有输入读取。"""
from copy import deepcopy
from hashlib import sha256
import json
from types import MappingProxyType
from unittest.mock import patch

import pytest

from agentcfg.pi_reviewer_decision import ReviewerDecisionControl
from agentcfg.pi_reviewer_prompt import MAX_PROMPT_BYTES, SYSTEM_PROMPT
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_reviewer_decision import fixture


def fake_compiler(prepared):
  return {"schema_version": 1, "operation_id": prepared["operation_id"],
    "operation_digest": prepared["operation_digest"], "eligible": True,
    "source_binding": {"kind": "selected-inputs-v1", "identity": "6" * 64},
    "facts": {"operation_kind": "file", "action": "write", "target_class": "selected-workspace-object",
      "access_effect": "write", "network_class": "none", "content_evaluated": False}}


def setup(tmp_path, provider=fake_compiler):
  f = fixture(tmp_path)
  f["config"]["human_available"] = None
  f["control"] = ReviewerDecisionControl(f["admissions"], f["ledger"],
    **f["config"], projection_provider=provider)
  f["begin"] = f["control"].begin(f["prepared"]["operation_id"])
  return f


def prepare(f):
  return f["control"].prepare_wire(f["begin"]["ticket"])


def response(payload, decision="allow"):
  return json.dumps({"schema_version": 1, **payload["binding"], "decision": decision,
    "reason_code": {"allow": "authorized-in-scope", "deny": "outside-user-scope", "ask": "needs-human"}[decision]})


def sent(f):
  payload = prepare(f)["payload"]
  f["control"].commit_send(f["begin"]["ticket"])
  f["control"].mark_sent(f["begin"]["ticket"])
  return payload


def finish(f, raw, *, outcome="valid", requests=1):
  return f["control"].conclude_wire(f["begin"]["ticket"],
    {"outcome": outcome, "requests": requests, "response": raw})


def test_original_allow_and_exactly_once_private_consumption(tmp_path):
  f = setup(tmp_path)
  # prepare不调用consume来取正文；fake compiler仅获得原prepared投影。
  with patch.object(f["admissions"], "consume", side_effect=AssertionError("private getter called")):
    payload = sent(f)
    result = finish(f, response(payload))
  assert result["status"] == "permitted"
  assert result["permit"]["operation_digest"] == f["prepared"]["operation_digest"]
  assert result["permit"]["reviewer_identity"] == f["current"]["reviewer_identity"]
  consumed = f["admissions"].consume(result["permit"], current=f["current"], resolved=f["resolved"])
  assert consumed["private_input"] == f["private"]
  with pytest.raises(Conflict):
    f["admissions"].consume(result["permit"], current=f["current"], resolved=f["resolved"])
  with pytest.raises(Conflict, match="ALREADY_SETTLED"): finish(f, response(payload))
  assert f["ledger"].snapshot()["observed_requests"] == 1


def test_outbound_has_closed_nonempty_facts_and_no_private_values_or_hashes(tmp_path):
  f = setup(tmp_path); payload = prepare(f)["payload"]
  outbound = (payload["system_prompt"] + payload["user_prompt"]).encode("utf8")
  assert len(outbound) <= MAX_PROMPT_BYTES and payload["system_prompt"] == SYSTEM_PROMPT
  document = json.loads(payload["user_prompt"])
  assert set(document) == {"schema_version", "binding", "facts"}
  assert document["facts"] == fake_compiler(f["prepared"])["facts"]
  assert document["binding"] == payload["binding"]
  values = [f["private"]["content"], f["resolved"]["target"]["path"], f["current"]["cwd"],
    f["prepared"]["operation_id"], *f["begin"]["binding"].values(), "6" * 64]
  for value in values:
    assert value.encode() not in outbound
    assert sha256(value.encode()).hexdigest().encode() not in outbound
  snapshot = deepcopy(payload); payload["binding"]["request_id"] = "0" * 32
  assert prepare(f)["payload"] == snapshot
  assert f["ledger"].snapshot()["committed_calls"] == 0


def test_all_four_aliases_fresh_per_attempt(tmp_path):
  first = setup(tmp_path / "one"); second = setup(tmp_path / "two")
  a, b = prepare(first)["payload"], prepare(second)["payload"]
  assert a == prepare(first)["payload"]
  for key in a["binding"]:
    assert a["binding"][key] != b["binding"][key]
    assert a["binding"][key] != first["begin"]["binding"][key]
    assert len(a["binding"][key]) == (32 if key == "request_id" else 64)


@pytest.mark.parametrize("decision,status", [("deny", "blocked"), ("ask", "blocked")])
def test_wire_deny_and_ask_without_ui_use_original_decisions(tmp_path, decision, status):
  f = setup(tmp_path); payload = sent(f)
  result = finish(f, response(payload, decision))
  assert result["status"] == status and result["permit"] is None and result["source"] == "reviewer"
  row = f["ledger"].get(f["prepared"]["operation_id"])
  assert row["decision"] == decision and row["binding"]["request_id"] == f["begin"]["binding"]["request_id"]


@pytest.mark.parametrize("key", ["request_id", "operation_digest", "context_digest", "reviewer_identity"])
def test_wrong_alias_is_protocol_failure(tmp_path, key):
  f = setup(tmp_path); payload = sent(f); bad = deepcopy(payload)
  bad["binding"][key] = "0" * len(bad["binding"][key])
  result = finish(f, response(bad))
  assert result["permit"] is None and result["reason_code"] == "protocol-failure"
  assert f["ledger"].snapshot()["reserved_cost_units"] == 120


def test_cross_ticket_and_internal_binding_cannot_select_operation(tmp_path):
  for name in ("cross", "internal"):
    f = setup(tmp_path / name); sent(f)
    other = setup(tmp_path / (name + "other"))
    raw = response(prepare(other)["payload"]) if name == "cross" else response({"binding": f["begin"]["binding"]})
    assert finish(f, raw)["reason_code"] == "protocol-failure"


@pytest.mark.parametrize("raw", ["{", "{}", "NaN", '{"schema_version":1,"schema_version":1}',
  "x" * 8193, "é" * 4097, "[]"])
def test_malformed_wire_never_permits(tmp_path, raw):
  f = setup(tmp_path); sent(f)
  assert finish(f, raw)["reason_code"] == "protocol-failure"


@pytest.mark.parametrize("field,value", [("schema_version", True), ("reason_code", []), ("decision", float("nan")),
  ("extra", "secret"), ("request_id", None)])
def test_closed_response_and_nonfinite_values(tmp_path, field, value):
  f = setup(tmp_path); payload = sent(f); raw = json.loads(response(payload)); raw[field] = value
  assert finish(f, json.dumps(raw))["permit"] is None


@pytest.mark.parametrize("provider", [None, lambda p: {**fake_compiler(p), "eligible": False},
  lambda p: {**fake_compiler(p), "facts": {**fake_compiler(p)["facts"], "operation_kind": "shell"}},
  lambda p: {**fake_compiler(p), "facts": {**fake_compiler(p)["facts"], "action": "dynamicShell"}},
  lambda p: {**fake_compiler(p), "facts": {**fake_compiler(p)["facts"], "target_class": "selected-resource"}},
  lambda p: {**fake_compiler(p), "facts": {**fake_compiler(p)["facts"], "network_class": "unknown"}}])
def test_ineligible_zero_outbound_no_implicit_settlement(tmp_path, provider):
  f = setup(tmp_path, provider)
  assert prepare(f) == {"status": "privacy-ineligible", "payload": None}
  assert f["ledger"].snapshot()["reserved_calls"] == 1
  result = f["control"].conclude(f["begin"]["ticket"], {"outcome": "not-called", "requests": 0, "response": None})
  assert result["permit"] is None
  assert f["ledger"].snapshot()["charged_cost_units"] == 0


@pytest.mark.parametrize("provider", [lambda p: {**fake_compiler(p), "extra": "PRIVATE_BODY"},
  lambda p: {**fake_compiler(p), "operation_digest": "0" * 64},
  lambda p: {**fake_compiler(p), "facts": {**fake_compiler(p)["facts"], "action": float("nan")}},
  lambda p: MappingProxyType(fake_compiler(p)),
  lambda p: {**fake_compiler(p), "eligible": 1}])
def test_invalid_projection_is_fixed_error_zero_send(tmp_path, provider):
  f = setup(tmp_path, provider)
  with pytest.raises(ConfigError) as error: prepare(f)
  assert error.value.code == "PI_RISK_REVIEW_PROJECTION_INVALID" and error.value.path == ()
  assert f["ledger"].snapshot()["committed_calls"] == 0


def test_proxy_and_coroutine_are_not_evaluated(tmp_path):
  getter_calls = []
  class Proxy:
    def __getattribute__(self, name):
      getter_calls.append(name)
      raise AssertionError("getter evaluated")
  f = setup(tmp_path / "proxy", lambda p: Proxy())
  with pytest.raises(ConfigError): prepare(f)
  assert getter_calls == []
  async def callback(p): return fake_compiler(p)
  f = fixture(tmp_path / "async")
  with pytest.raises(ConfigError):
    ReviewerDecisionControl(f["admissions"], f["ledger"], **f["config"], projection_provider=callback)
  f = setup(tmp_path / "returned-coroutine", lambda p: callback(p))
  with pytest.raises(ConfigError): prepare(f)


def test_total_prompt_bytes_guard(tmp_path):
  f = setup(tmp_path)
  with patch("agentcfg.pi_reviewer_prompt.SYSTEM_PROMPT", "é" * MAX_PROMPT_BYTES):
    with pytest.raises(ConfigError, match="PROJECTION_INVALID"): prepare(f)
  assert f["ledger"].snapshot()["committed_calls"] == 0


@pytest.mark.parametrize("field", ["cancel_epoch", "policy_generation"])
def test_current_change_before_send_and_restoration_never_revives_aliases(tmp_path, field):
  f = setup(tmp_path); payload = prepare(f)["payload"]; f["current"][field] += 1
  with pytest.raises(Conflict): f["control"].commit_send(f["begin"]["ticket"])
  f["current"][field] -= 1
  with pytest.raises(Conflict): prepare(f)
  assert f["ledger"].snapshot()["committed_calls"] == 0
  assert finish(f, None, outcome="canceled", requests=0)["permit"] is None


def test_changed_compiler_facts_before_send_or_response(tmp_path):
  eligible = [True]
  def callback(p): return {**fake_compiler(p), "eligible": eligible[0]}
  f = setup(tmp_path / "before", callback); prepare(f); eligible[0] = False
  with pytest.raises(Conflict, match="PROJECTION_STALE"): f["control"].commit_send(f["begin"]["ticket"])
  assert f["ledger"].snapshot()["committed_calls"] == 0
  eligible[0] = True
  f = setup(tmp_path / "after", callback); payload = sent(f); eligible[0] = False
  assert finish(f, response(payload))["permit"] is None
  assert f["ledger"].snapshot()["observed_requests"] == 1


def test_cancel_late_and_unknown_failure_preserve_original_meter(tmp_path):
  f = setup(tmp_path / "cancel"); payload = sent(f)
  assert finish(f, None, outcome="canceled")["permit"] is None
  with pytest.raises(Conflict, match="ALREADY_SETTLED"): finish(f, response(payload))
  f = setup(tmp_path / "unknown"); prepare(f); f["control"].commit_send(f["begin"]["ticket"])
  assert finish(f, None, outcome="transport-failure", requests=None)["permit"] is None
  snapshot = f["ledger"].snapshot()
  assert snapshot["unknown_requests"] == 1 and snapshot["reserved_cost_units"] == 120


def test_fake_facts_do_not_override_original_automatic_qualification(tmp_path):
  f = setup(tmp_path); prepare(f); f["qualify"]["automatic_risk_allowed"] = False
  with pytest.raises(Conflict): f["control"].commit_send(f["begin"]["ticket"])
  assert f["ledger"].snapshot()["committed_calls"] == 0


def test_valid_candidate_without_prepared_wire_is_protocol_failure(tmp_path):
  f = setup(tmp_path)
  with pytest.raises(Conflict, match="WIRE_NOT_PREPARED"):
    f["control"].commit_send(f["begin"]["ticket"])
  assert finish(f, response({"binding": f["begin"]["binding"]}), requests=0)["reason_code"] in ("protocol-failure", "discarded")


def test_callback_failure_never_echoes_private_error(tmp_path):
  def fail(p): raise ValueError("SYNTHETIC_PRIVATE_BODY /project/file " + p["operation_digest"])
  f = setup(tmp_path, fail)
  with pytest.raises(ConfigError) as error: prepare(f)
  assert error.value.code == "PI_RISK_REVIEW_PROJECTION_INVALID"
  assert "SYNTHETIC_PRIVATE_BODY" not in str(error.value) and "/project/file" not in str(error.value)
  assert f["prepared"]["operation_digest"] not in str(error.value)
  assert f["ledger"].snapshot()["committed_calls"] == 0


def test_changed_original_resolution_and_same_request_params_zero_send(tmp_path):
  f = setup(tmp_path); prepare(f)
  changed = deepcopy(f["private"]); changed["content"] = "changed private body"
  with pytest.raises(Conflict, match="IDEMPOTENCY_CONFLICT"):
    f["admissions"].prepare("sdk-call", current=f["current"], resolved=f["resolved"], private_input=changed)
  f["resolved"]["target"]["path"] = "/project/changed"
  with pytest.raises(Conflict, match="RESOLUTION_STALE"):
    f["control"].commit_send(f["begin"]["ticket"])
  assert f["ledger"].snapshot()["committed_calls"] == 0


@pytest.mark.parametrize("field", ["cancel_epoch", "policy_generation"])
def test_current_change_after_send_discards_allow(tmp_path, field):
  f = setup(tmp_path); payload = sent(f); f["current"][field] += 1
  assert finish(f, response(payload))["permit"] is None
  assert f["ledger"].snapshot()["observed_requests"] == 1


def test_closed_enum_actions_and_access_roots(tmp_path):
  from agentcfg.pi_reviewer_prompt import EFFECTS
  for action, effect in EFFECTS.items():
    f = fixture(tmp_path / action)
    f["resolved"]["tool_name"] = action
    f["resolved"]["read_roots"] = deepcopy(f["resolved"]["write_roots"])
    if effect == "read":
      f["resolved"]["write_roots"] = []
      f["resolved"]["workspace_keys"] = []
    if action == "rename": f["resolved"]["target"]["destination"] = "/project/destination"
    f["prepared"] = f["admissions"].prepare("classified-" + action,
      current=f["current"], resolved=f["resolved"], private_input=f["private"])
    def callback(p):
      value = fake_compiler(p)
      value["facts"].update(action=action, access_effect=effect)
      return value
    f["control"] = ReviewerDecisionControl(f["admissions"], f["ledger"], **f["config"], projection_provider=callback)
    f["begin"] = f["control"].begin(f["prepared"]["operation_id"])
    assert prepare(f)["status"] == "prepared"
    if effect in ("read", "read-and-write"): f["resolved"]["read_roots"] = []
    else: f["resolved"]["write_roots"] = []
    with pytest.raises((Conflict, ConfigError)): f["control"].commit_send(f["begin"]["ticket"])
    assert f["ledger"].snapshot()["committed_calls"] == 0
    assert f["admissions"].status(f["prepared"]["operation_id"])["state"] == "revoked"


def test_maximum_total_bytes_is_aggregate_boundary(tmp_path):
  f = setup(tmp_path); payload = prepare(f)["payload"]
  from agentcfg.pi_reviewer_prompt import prompt_payload
  user_bytes = len(payload["user_prompt"].encode("utf8"))
  facts = json.loads(payload["user_prompt"])["facts"]
  with patch("agentcfg.pi_reviewer_prompt.SYSTEM_PROMPT", "x" * (MAX_PROMPT_BYTES - user_bytes)):
    assert prompt_payload(payload["binding"], facts)["user_prompt"] == payload["user_prompt"]
  with patch("agentcfg.pi_reviewer_prompt.SYSTEM_PROMPT", "x" * (MAX_PROMPT_BYTES - user_bytes + 1)):
    with pytest.raises(ConfigError): prompt_payload(payload["binding"], facts)


@pytest.mark.parametrize("entrypoint", ["conclude", "conclude_transport"])
def test_wire_ticket_cannot_use_legacy_internal_binding_to_bypass_aliases(tmp_path, entrypoint):
  f = wire_entry_fixture(tmp_path, entrypoint); sent(f)
  raw = response({"binding": f["begin"]["binding"]})
  if entrypoint == "conclude":
    result = f["control"].conclude(f["begin"]["ticket"], {"outcome": "valid", "requests": 1, "response": raw})
  else:
    result = f["control"].conclude_transport(f["begin"]["ticket"], {"outcome": "valid", "platform_requests": 1,
      "response": raw, "gate_attempted": True, "gate_acknowledged": True})
  assert result["permit"] is None and result["reason_code"] == "protocol-failure"
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"] == "revoked"


@pytest.mark.parametrize("entrypoint", ["conclude", "conclude_transport"])
def test_wire_ticket_checks_changed_projection_on_every_success_entrypoint(tmp_path, entrypoint):
  eligible = [True]
  f = wire_entry_fixture(tmp_path, entrypoint, lambda p: {**fake_compiler(p), "eligible": eligible[0]})
  payload = sent(f); eligible[0] = False
  raw = response(payload)
  if entrypoint == "conclude":
    result = f["control"].conclude(f["begin"]["ticket"], {"outcome": "valid", "requests": 1, "response": raw})
  else:
    result = f["control"].conclude_transport(f["begin"]["ticket"], {"outcome": "valid", "platform_requests": 1,
      "response": raw, "gate_attempted": True, "gate_acknowledged": True})
  assert result["permit"] is None and result["reason_code"] == "discarded"


def wire_entry_fixture(tmp_path, entrypoint, provider=fake_compiler):
  if entrypoint != "conclude_transport": return setup(tmp_path, provider)
  from test_pi_reviewer_transport_settlement import fixture as transport_fixture
  # 原账户scope adapter有observe；只在fixture构造时安装明确fakeprovider。
  def construct(*args, **kwargs):
    return ReviewerDecisionControl(*args, **kwargs, projection_provider=provider)
  with patch("test_pi_reviewer_transport_settlement.ReviewerDecisionControl", side_effect=construct):
    f = transport_fixture(tmp_path)
  return f


@pytest.mark.parametrize("phase", ["before-send", "conclude_wire", "conclude", "conclude_transport"])
def test_same_facts_changed_selected_source_binding_never_permits(tmp_path, phase):
  source = ["6" * 64]
  def callback(p):
    value = fake_compiler(p)
    value["source_binding"]["identity"] = source[0]
    return value
  f = wire_entry_fixture(tmp_path, phase, callback)
  payload = prepare(f)["payload"]
  if phase != "before-send":
    f["control"].commit_send(f["begin"]["ticket"])
    f["control"].mark_sent(f["begin"]["ticket"])
  source[0] = "7" * 64
  if phase == "before-send":
    with pytest.raises(Conflict, match="PROJECTION_STALE"): f["control"].commit_send(f["begin"]["ticket"])
    assert f["ledger"].snapshot()["committed_calls"] == 0
  elif phase == "conclude_transport":
    result = f["control"].conclude_transport(f["begin"]["ticket"], {"outcome": "valid", "platform_requests": 1,
      "response": response(payload), "gate_attempted": True, "gate_acknowledged": True})
    assert result["permit"] is None and result["reason_code"] == "discarded"
  else:
    result = getattr(f["control"], phase)(f["begin"]["ticket"],
      {"outcome": "valid", "requests": 1, "response": response(payload)})
    assert result["permit"] is None and result["reason_code"] == "discarded"
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"] == "revoked"


@pytest.mark.parametrize("source", [None, {}, {"kind": "selected-inputs-v1", "identity": "secret"},
  {"kind": "caller-hash", "identity": "6" * 64}, {"kind": "selected-inputs-v1", "identity": "6" * 64, "extra": True}])
def test_source_binding_must_be_closed_valid_private_compiler_fact(tmp_path, source):
  f = setup(tmp_path, lambda p: {**fake_compiler(p), "source_binding": source})
  with pytest.raises(ConfigError) as error: prepare(f)
  assert error.value.code == "PI_RISK_REVIEW_PROJECTION_INVALID"
  assert f["ledger"].snapshot()["committed_calls"] == 0


@pytest.mark.parametrize("entrypoint", ["conclude", "conclude_transport"])
def test_legacy_entrypoints_accept_matching_wire_aliases_using_original_once_issuer(tmp_path, entrypoint):
  f = wire_entry_fixture(tmp_path, entrypoint); payload = sent(f)
  if entrypoint == "conclude":
    result = f["control"].conclude(f["begin"]["ticket"], {"outcome": "valid", "requests": 1, "response": response(payload)})
  else:
    result = f["control"].conclude_transport(f["begin"]["ticket"], {"outcome": "valid", "platform_requests": 1,
      "response": response(payload), "gate_attempted": True, "gate_acknowledged": True})
  assert result["permit"]["operation_digest"] == f["prepared"]["operation_digest"]
  f["admissions"].consume(result["permit"], current=f["current"], resolved=f["resolved"])
  with pytest.raises(Conflict): f["admissions"].consume(result["permit"], current=f["current"], resolved=f["resolved"])


@pytest.mark.parametrize("prepared", [False, True])
def test_projection_enabled_ticket_without_eligible_wire_cannot_send_or_accept(tmp_path, prepared):
  f = setup(tmp_path, lambda p: {**fake_compiler(p), "eligible": False})
  if prepared: assert prepare(f) == {"status": "privacy-ineligible", "payload": None}
  with pytest.raises(Conflict, match="WIRE_NOT_PREPARED"): f["control"].commit_send(f["begin"]["ticket"])
  assert f["ledger"].snapshot()["committed_calls"] == 0
  result = f["control"].conclude(f["begin"]["ticket"], {"outcome": "valid", "requests": 0,
    "response": response({"binding": f["begin"]["binding"]})})
  assert result["permit"] is None and result["reason_code"] in ("protocol-failure", "discarded")


def test_wire_required_mode_is_captured_with_original_ticket(tmp_path):
  f = setup(tmp_path)
  f["control"]._projection_provider = None
  with pytest.raises(Conflict, match="WIRE_NOT_PREPARED"): f["control"].commit_send(f["begin"]["ticket"])
  assert f["ledger"].snapshot()["committed_calls"] == 0


@pytest.mark.parametrize("entrypoint", ["conclude", "conclude_transport"])
def test_no_wire_internal_candidate_direct_settlement_cannot_bypass_required_mode(tmp_path, entrypoint):
  f = wire_entry_fixture(tmp_path, entrypoint)
  raw = response({"binding": f["begin"]["binding"]})
  if entrypoint == "conclude":
    result = f["control"].conclude(f["begin"]["ticket"], {"outcome": "valid", "requests": 0, "response": raw})
  else:
    result = f["control"].conclude_transport(f["begin"]["ticket"], {"outcome": "valid", "platform_requests": 0,
      "response": raw, "gate_attempted": False, "gate_acknowledged": False})
  assert result["permit"] is None and result["reason_code"] == "protocol-failure"
  assert f["ledger"].snapshot()["committed_calls"] == 0
