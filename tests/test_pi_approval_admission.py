"""可信prepared的审批模式与许可来源；不启动宿主、进程或模型。"""
from copy import deepcopy

import pytest

from agentcfg.pi_operation_admission import resolution
from agentcfg.pi_reviewer_decision import ReviewerDecisionControl
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_operation_admission import fixture, prepare, issue
from test_pi_reviewer_decision import fixture as decision_fixture, dispatch, conclude


MODES = ("human", "reviewer", "deterministic-policy")


def classified(mode):
  calls = []
  f = fixture(reviewer_current=lambda p, c: calls.append(p["operation_id"]) or True)
  f[1].update(profile="pi-full", reviewer_identity="1" * 64)
  f[2]["policy"].update(approval=mode, requires_human=mode == "human")
  return f, calls


@pytest.mark.parametrize("mode", MODES)
def test_resolution_accepts_consistent_native_mode_without_rewriting(mode):
  f, _ = classified(mode); before = deepcopy(f[2])
  assert resolution(f[2]) == before and f[2] == before
  assert prepare(f)["resolution"]["policy"]["approval"] == mode


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("source", MODES)
def test_permit_source_obeys_original_prepared_mode(mode, source):
  f, calls = classified(mode); p = prepare(f)
  allowed = source == "human" or source == mode
  if allowed:
    permit = issue(f, p, source=source, reviewer_identity="1" * 64 if source == "reviewer" else None)
    assert permit["source"] == source
    assert f[0].consume(permit, current=f[1], resolved=f[2])["prepared"] == p
    assert len(calls) == (2 if source == "reviewer" else 0)
  else:
    error = "OPERATION_HUMAN_REQUIRED" if mode == "human" else "OPERATION_APPROVAL_SOURCE_MISMATCH"
    with pytest.raises(Conflict, match=error):
      issue(f, p, source=source, reviewer_identity="1" * 64 if source == "reviewer" else None)
    assert calls == [] and f[0].status(p["operation_id"])["state"] == "prepared"
    assert issue(f, p, source="human")["source"] == "human"


class StringSubclass(str):
  pass


@pytest.mark.parametrize("mode", [None, True, 1, {}, [], "SYNTHETIC_PRIVATE", StringSubclass("human")])
def test_invalid_mode_is_a_fixed_error_and_never_prepared(mode):
  f = fixture(); f[2]["policy"]["approval"] = mode
  with pytest.raises(ConfigError) as error: prepare(f)
  assert error.value.code == "pi-operation-admission"
  assert "SYNTHETIC_PRIVATE" not in str(error.value)


@pytest.mark.parametrize("mode", MODES)
def test_mode_and_human_flag_cannot_disagree(mode):
  f, _ = classified(mode); f[2]["policy"]["requires_human"] = mode != "human"
  with pytest.raises(ConfigError): prepare(f)


@pytest.mark.parametrize("mode", MODES)
def test_reclassification_cannot_rebind_request_or_revive_consumed_permit(mode):
  f, _ = classified(mode); p = prepare(f); permit = issue(f, p, source="human")
  changed = "reviewer" if mode == "deterministic-policy" else "deterministic-policy"
  f[2]["policy"].update(approval=changed, requires_human=False)
  with pytest.raises(Conflict, match="OPERATION_IDEMPOTENCY_CONFLICT"): prepare(f)
  with pytest.raises(Conflict, match="OPERATION_RESOLUTION_STALE"):
    f[0].consume(permit, current=f[1], resolved=f[2])
  f[2]["policy"].update(approval=mode, requires_human=mode == "human")
  with pytest.raises(Conflict, match="OPERATION_PERMIT_USED"):
    f[0].consume(permit, current=f[1], resolved=f[2])


@pytest.mark.parametrize("mode", MODES)
def test_hard_deny_still_prevents_preparation(mode):
  f, _ = classified(mode); f[2]["policy"]["hard_policy"] = "deny"
  with pytest.raises(Conflict, match="OPERATION_HARD_DENIED"): prepare(f)


def test_legacy_mode_absence_keeps_explicit_trusted_component_behavior():
  for source in ("reviewer", "deterministic-policy", "human"):
    f, calls = classified("reviewer"); del f[2]["policy"]["approval"]
    p = prepare(f)
    permit = issue(f, p, source=source, reviewer_identity="1" * 64 if source == "reviewer" else None)
    assert "approval" not in p["resolution"]["policy"] and permit["source"] == source
    assert len(calls) == (1 if source == "reviewer" else 0)


def test_deterministic_mode_never_enters_qualification_scope_or_ledger():
  f, _ = classified("deterministic-policy"); p = prepare(f); touched = []
  def forbidden(*args, **kwargs):
    touched.append("external"); raise AssertionError("deterministic review path touched")
  class NoLedger:
    reserve = claim_attempt = forbidden
  control = ReviewerDecisionControl(f[0], NoLedger(), current_provider=lambda _: deepcopy(f[1]),
    resolution_provider=lambda _: deepcopy(f[2]), qualification_provider=forbidden, scope_provider=forbidden,
    route_identity="1" * 64, pricing={}, token_limits={})
  assert control.begin(p["operation_id"]) == {"status": "not-called", "operation_id": p["operation_id"],
    "ticket": None, "binding": None}
  assert touched == [] and control.tickets == {}
  assert issue(f, p)["source"] == "deterministic-policy"


def test_explicit_reviewer_mode_uses_existing_once_model_decision_fixture(tmp_path):
  f = decision_fixture(tmp_path)
  f["resolved"]["policy"]["approval"] = "reviewer"
  f["prepared"] = f["admissions"].prepare("classified-sdk-call", current=f["current"],
    resolved=f["resolved"], private_input=f["private"])
  begin = dispatch(f); result = conclude(f, begin)
  assert result["status"] == "permitted" and result["permit"]["source"] == "reviewer"
  assert f["ledger"].snapshot()["committed_calls"] == 1
  assert f["admissions"].consume(result["permit"], current=f["current"], resolved=f["resolved"])["prepared"] == f["prepared"]
