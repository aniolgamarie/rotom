"""有效ask的人机可用性投影：默认只用真实临时账本和同步fake UI。"""
import inspect
from copy import deepcopy
from unittest.mock import patch

import pytest

from agentcfg.pi_reviewer_decision import ReviewerDecisionControl
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_reviewer_decision import fixture, dispatch, conclude, wire


def configured(tmp_path, human_available=None, *, missing=False, **kwargs):
  f = fixture(tmp_path, **kwargs)
  config = dict(f["config"])
  config.pop("human_available", None)
  if not missing:
    config["human_available"] = human_available
  f["control"] = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  return f


def test_valid_ask_without_ui_is_blocked_and_keeps_real_ask_lock(tmp_path):
  f = configured(tmp_path, missing=True)
  result = conclude(f, dispatch(f), "ask")
  assert result["status"] == "blocked"
  assert result["source"] == "reviewer"
  assert result["reason_code"] == "needs-human"
  assert result["permit"] is None
  row = f["ledger"].get(f["prepared"]["operation_id"])
  assert row["outcome"] == "valid" and row["decision"] == "ask"
  assert row["reason_code"] == "needs-human"
  f["scope"]["request_ref"] = "4" * 32
  new = f["admissions"].prepare("new-call", current=f["current"], resolved=f["resolved"], private_input=f["private"])
  with pytest.raises(Conflict, match="REVIEW_INTENT_BLOCKED"):
    f["control"].begin(new["operation_id"])


@pytest.mark.parametrize("value", [None, False, 0, 1, "true", {}, [], object()])
def test_ui_answer_must_be_exact_true(tmp_path, value):
  calls = []
  f = configured(tmp_path, lambda prepared: calls.append(prepared) or value)
  result = conclude(f, dispatch(f), "ask")
  assert result["status"] == "blocked" and result["source"] == "reviewer"
  assert result["reason_code"] == "needs-human" and result["permit"] is None
  assert len(calls) == 1
  assert f["ledger"].get(f["prepared"]["operation_id"])["decision"] == "ask"


def test_ui_available_called_after_ask_is_durable_with_only_prepared_copy(tmp_path):
  seen = []
  f = None
  # predicate不应重入ledger；此测试观察通过包装finish记录持久化完成。
  durable = []
  def safe_available(prepared):
    seen.append(deepcopy(prepared))
    assert durable == [True]
    assert "SYNTHETIC_PRIVATE_BODY" not in str(prepared)
    assert "private_input" not in prepared
    prepared["context"]["cancel_epoch"] = 999
    prepared["resolution"]["target"]["path"] = "/changed"
    return True
  f = configured(tmp_path, safe_available)
  original = deepcopy(f["prepared"])
  finish = f["ledger"].finish
  def finished(*args, **kwargs):
    value = finish(*args, **kwargs)
    durable.append(True)
    return value
  begin = dispatch(f)
  with patch.object(f["ledger"], "finish", finished): result = conclude(f, begin, "ask")
  assert result["status"] == "awaiting-human" and result["permit"] is None
  assert seen == [original]
  assert f["admissions"].prepared(original["operation_id"]) == original
  assert f["prepared"] == original


def test_ui_disappears_after_dispatch_does_not_reclassify_valid_ask(tmp_path):
  live = [True]
  f = configured(tmp_path, lambda prepared: live[0])
  begin = dispatch(f)
  live[0] = False
  result = conclude(f, begin, "ask")
  assert result["status"] == "blocked" and result["source"] == "reviewer"
  assert f["ledger"].get(f["prepared"]["operation_id"])["outcome"] == "valid"
  assert f["admissions"].prepared(f["prepared"]["operation_id"]) == f["prepared"]


def test_ui_exception_is_swallowed_without_private_text(tmp_path):
  marker = "SYNTHETIC_PRIVATE_UI"
  def unavailable(prepared): raise RuntimeError(marker)
  f = configured(tmp_path, unavailable)
  result = conclude(f, dispatch(f), "ask")
  assert result["status"] == "blocked" and result["source"] == "reviewer"
  assert marker not in str(result)
  assert result["permit"] is None


@pytest.mark.parametrize("kind", ["coroutine", "asyncgen"])
def test_async_ui_function_configuration_rejected_before_any_ledger_call(tmp_path, kind):
  async def coroutine(prepared): return True
  async def asyncgen(prepared): yield True
  f = fixture(tmp_path)
  config = dict(f["config"], human_available=coroutine if kind == "coroutine" else asyncgen)
  with pytest.raises(ConfigError) as caught:
    ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  assert caught.value.code == "PI_RISK_REVIEW_DECISION_INVALID"
  assert f["ledger"].snapshot()["record_count"] == 0


def test_sync_callback_coroutine_return_closed_without_execution_or_warning(tmp_path, recwarn):
  ran = []
  returned = []
  async def coroutine():
    ran.append(True)
    raise RuntimeError("SYNTHETIC_PRIVATE_UI")
  def unavailable(prepared):
    value = coroutine(); returned.append(value); return value
  f = configured(tmp_path, unavailable)
  assert conclude(f, dispatch(f), "ask")["status"] == "blocked"
  assert inspect.getcoroutinestate(returned[0]) == inspect.CORO_CLOSED
  assert ran == [] and list(recwarn) == []


def test_awaitable_future_or_thenable_not_observed_as_ui(tmp_path):
  class Awaitable:
    def __await__(self): pytest.fail("must not await UI")
    @property
    def then(self): pytest.fail("must not read then")
  f = configured(tmp_path, lambda prepared: Awaitable())
  assert conclude(f, dispatch(f), "ask")["status"] == "blocked"


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_other_valid_decisions_never_query_ui(tmp_path, decision):
  calls = []
  f = configured(tmp_path, lambda prepared: calls.append(prepared) or True)
  result = conclude(f, dispatch(f), decision)
  assert calls == []
  assert (result["permit"] is not None) == (decision == "allow")


@pytest.mark.parametrize("mode", ["discarded", "protocol", "fault", "scope-retired"])
def test_nonvalid_ask_never_queries_ui(tmp_path, mode):
  calls = []
  f = configured(tmp_path, lambda prepared: calls.append(prepared) or True)
  begin = dispatch(f)
  response = wire(begin, "ask")
  outcome = "valid"
  if mode == "discarded": f["current"]["cancel_epoch"] += 1
  if mode == "protocol": response = "bad JSON"
  if mode == "fault": outcome, response = "transport-failure", None
  if mode == "scope-retired": f["control"].scope_current = lambda prepared, scopes: False
  result = f["control"].conclude(begin["ticket"], {"outcome": outcome, "requests": 1, "response": response})
  assert calls == [] and result["status"] == "blocked" and result["permit"] is None


@pytest.mark.parametrize("mode", ["base", "off", "hard", "role", "human"])
def test_early_policy_gates_never_query_ui(tmp_path, mode):
  calls = []
  f = configured(tmp_path, lambda prepared: calls.append(prepared) or True,
    profile="pi-base" if mode == "base" else "pi-full", enabled=mode != "off", requires_human=mode == "human")
  if mode == "hard": f["resolved"]["policy"]["hard_policy"] = "deny"
  if mode == "role": f["qualify"]["role_allows"] = False
  try: f["control"].begin(f["prepared"]["operation_id"])
  except Conflict: assert mode == "hard"
  assert calls == [] and f["ledger"].snapshot()["record_count"] == 0


def test_noncallable_ui_configuration_rejected(tmp_path):
  f = fixture(tmp_path)
  with pytest.raises(ConfigError) as caught:
    ReviewerDecisionControl(f["admissions"], f["ledger"], **dict(f["config"], human_available=True))
  assert caught.value.code == "PI_RISK_REVIEW_DECISION_INVALID"


def test_truthy_ui_object_does_not_run_bool_coercion(tmp_path):
  class Truthy:
    def __bool__(self): pytest.fail("must not coerce UI result")
  f = configured(tmp_path, lambda prepared: Truthy())
  assert conclude(f, dispatch(f), "ask")["status"] == "blocked"


def test_native_future_return_is_not_awaited_or_treated_as_ui(tmp_path):
  from concurrent.futures import Future
  future = Future()
  f = configured(tmp_path, lambda prepared: future)
  assert conclude(f, dispatch(f), "ask")["status"] == "blocked"
  assert not future.done()
