"""真实内存许可与显式fake live qualifier；无SDK/IO/账号/执行。"""
from copy import deepcopy
import json

import pytest

from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_operation_admission import fixture as base_fixture, prepare, issue


def fixture(hook=None):
  options = {} if hook is None else {"reviewer_current": hook}
  f = base_fixture(**options)
  f[1].update(profile="pi-full", reviewer_identity="1" * 64)
  return f


def reviewer_issue(f, operation):
  return issue(f, operation, source="reviewer", reviewer_identity=f[1]["reviewer_identity"])


def consume(f, permit):
  return f[0].consume(permit, current=f[1], resolved=f[2])


def test_missing_hook_cannot_issue_reviewer_permit():
  f = fixture(); operation = prepare(f)
  with pytest.raises(Conflict, match="OPERATION_REVIEWER_UNQUALIFIED"): reviewer_issue(f, operation)
  assert f[0].status(operation["operation_id"])["state"] == "prepared"


@pytest.mark.parametrize("result", [None, False, 0, 1, "true", [], {}, object()])
def test_only_exact_true_qualifies_issue(result):
  calls = []; f = fixture(lambda prepared, current: calls.append((prepared, current)) or result); operation = prepare(f)
  with pytest.raises(Conflict, match="OPERATION_REVIEWER_UNQUALIFIED"): reviewer_issue(f, operation)
  assert len(calls) == 1 and f[0].status(operation["operation_id"])["state"] == "prepared"


@pytest.mark.parametrize("phase", ["issue", "consume"])
def test_callback_exception_is_fixed_without_raw_or_private_return(phase):
  state = [True]; calls = []
  def hook(prepared, current):
    calls.append((prepared, current))
    if not state[0]: raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION")
    return True
  f = fixture(hook); operation = prepare(f)
  if phase == "consume": permit = reviewer_issue(f, operation)
  state[0] = False
  with pytest.raises(Conflict) as error:
    reviewer_issue(f, operation) if phase == "issue" else consume(f, permit)
  assert str(error.value) == "OPERATION_REVIEWER_UNQUALIFIED" and error.value.__cause__ is None
  assert "SYNTHETIC_PRIVATE" not in str(error.value)
  if phase == "consume":
    assert f[0].status(operation["operation_id"])["state"] == "revoked"
    with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, permit)
    with pytest.raises(Conflict, match="NOT_PENDING"): reviewer_issue(f, operation)


@pytest.mark.parametrize("dimension", ["scope", "authority", "quality"])
def test_same_context_live_qualification_exit_burns_permit(dimension):
  live = {"scope": True, "authority": True, "quality": True}; calls = []; executions = []
  def hook(prepared, current):
    calls.append((prepared, current)); return all(live.values())
  f = fixture(hook); operation = prepare(f); original = deepcopy(f[1]); permit = reviewer_issue(f, operation)
  live[dimension] = False
  with pytest.raises(Conflict, match="OPERATION_REVIEWER_UNQUALIFIED"): executions.append(consume(f, permit))
  assert f[1] == original and executions == [] and len(calls) == 2
  live[dimension] = True
  with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, permit)
  with pytest.raises(Conflict, match="NOT_PENDING"): reviewer_issue(f, operation)
  assert len(calls) == 2 and executions == []


@pytest.mark.parametrize("source", ["human", "deterministic-policy"])
def test_other_sources_never_invoke_hook_even_on_consume(source):
  f = fixture(lambda *_: pytest.fail("human/rule invoked reviewer hook")); operation = prepare(f)
  permit = issue(f, operation, source=source)
  assert consume(f, permit)["private_input"] == f[3]


def test_callback_receives_isolated_original_prepared_and_validated_context_without_body():
  snapshots = []
  def hook(prepared, current):
    snapshots.append(deepcopy((prepared, current)))
    assert "private_input" not in prepared and f[3]["content"] not in json.dumps(prepared)
    prepared["context"]["cwd"] = "/escape"; prepared["resolution"]["target"]["path"] = "/escape"
    current["deadline_ms"] = 1
    return True
  f = fixture(hook); operation = prepare(f); original = deepcopy(f[1]); permit = reviewer_issue(f, operation)
  value = consume(f, permit)
  assert snapshots == [(operation, original), (operation, original)]
  assert value == {"prepared": operation, "private_input": f[3]} and f[1] == original
  with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, permit)
  assert len(snapshots) == 2


@pytest.mark.parametrize("fault,expected", [("wrong-permit", "PERMIT_MISMATCH"), ("revoked", "PERMIT_USED"),
  ("expired", "EXPIRED"), ("context", "CONTEXT_STALE"), ("resolution", "RESOLUTION_STALE")])
def test_original_consume_checks_precede_live_hook(fault, expected):
  calls = []; f = fixture(lambda *_: calls.append(True) or True); operation = prepare(f); permit = reviewer_issue(f, operation)
  if fault == "wrong-permit": permit["source"] = "human"
  if fault == "revoked": f[0].revoke(operation["operation_id"])
  if fault == "expired": f[4][0] = 5000
  if fault == "context": f[1]["session_id"] = "other"
  if fault == "resolution": f[2]["read_roots"] = [{"path": "/project", "identity": "9" * 64}]
  with pytest.raises(Conflict, match=expected): consume(f, permit)
  assert len(calls) == 1
  if fault == "context": f[1]["session_id"] = "session"
  with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, permit)
  assert len(calls) == 1


@pytest.mark.parametrize("fault,expected", [("identity", "REVIEWER_MISMATCH"), ("human", "HUMAN_REQUIRED"), ("deadline", "EXPIRED")])
def test_policy_identity_and_deadline_reject_before_issue_hook(fault, expected):
  calls = []; f = fixture(lambda *_: calls.append(True) or True)
  if fault == "human": f[2]["policy"]["requires_human"] = True
  operation = prepare(f)
  if fault == "deadline": f[4][0] = 5000
  identity = "2" * 64 if fault == "identity" else f[1]["reviewer_identity"]
  with pytest.raises(Conflict, match=expected): issue(f, operation, source="reviewer", reviewer_identity=identity)
  assert calls == []


@pytest.mark.parametrize("invalid", [True, 1, "callable", {}, []])
def test_invalid_hook_rejected_at_constructor_without_clock_or_io(invalid):
  with pytest.raises(ConfigError) as error:
    OperationAdmissions("activation", reviewer_current=invalid, now_ms=lambda: pytest.fail("constructor queried clock"))
  assert error.value.code == "pi-operation-admission"


@pytest.mark.parametrize("result", [None, False, 0, 1, "true", [], {}, object()])
def test_only_exact_true_qualifies_consume_and_failure_is_irreversible(result):
  answer = [True]; calls = []
  def hook(prepared, current):
    calls.append(True); return answer[0]
  f = fixture(hook); operation = prepare(f); permit = reviewer_issue(f, operation)
  answer[0] = result
  with pytest.raises(Conflict, match="OPERATION_REVIEWER_UNQUALIFIED"): consume(f, permit)
  assert f[0].status(operation["operation_id"])["state"] == "revoked"
  answer[0] = True
  with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, permit)
  with pytest.raises(Conflict, match="NOT_PENDING"): reviewer_issue(f, operation)
  assert calls == [True, True]


def test_hook_observes_original_lock_held_at_both_boundaries():
  held = []
  def hook(prepared, current):
    held.append(f[0]._lock.locked()); return True
  f = fixture(hook); operation = prepare(f); permit = reviewer_issue(f, operation)
  consume(f, permit)
  assert held == [True, True]


def test_unknown_permit_never_calls_qualifier_or_changes_real_permit():
  calls = []; f = fixture(lambda *_: calls.append(True) or True); operation = prepare(f); permit = reviewer_issue(f, operation)
  unknown = deepcopy(permit); unknown["permit_id"] = "not-found"
  with pytest.raises(Conflict, match="PERMIT_UNKNOWN"): consume(f, unknown)
  assert calls == [True]
  assert consume(f, permit)["prepared"] == operation
  assert calls == [True, True]
