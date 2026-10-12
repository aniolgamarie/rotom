"""manager确定性签发入口；真实临时原账本与假进程，无UI/SDK/模型。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_admission_control import fixture, opened, prepare, issued


def classified(tmp_path, mode="deterministic-policy"):
  f = fixture(tmp_path)
  f[2].manifest()["permission_policy"]["rules"][0]["approval"] = mode
  opened(f)
  return f, prepare(f)


def deterministic(f, p, **extra):
  return f[5]("issue_deterministic", {"operation_id": p["operation_id"], "context": f[4], **extra})


def test_fixed_deterministic_source_uses_original_bridge_once_without_writer_until_consume(tmp_path):
  f, p = classified(tmp_path)
  permit = deterministic(f, p)
  assert permit["source"] == "deterministic-policy" and permit["reviewer_identity"] is None
  assert f[0].bridge.permits[permit["permit_id"]] == p["operation_id"]
  assert [r for r in f[2].store.records() if r["kind"] == "external"] == []
  ticket = f[5]("consume", {"permit": permit, "context": f[4]})
  assert ticket["state"] == "consumed"
  assert len([r for r in f[2].store.records() if r["kind"] == "external"]) == 1
  with pytest.raises(Conflict): deterministic(f, p)
  with pytest.raises(Conflict): f[5]("consume", {"permit": permit, "context": f[4]})


@pytest.mark.parametrize("mode", ["human", "reviewer", None])
def test_other_modes_cannot_use_deterministic_rpc_and_can_still_choose_human(tmp_path, mode):
  f = fixture(tmp_path)
  if mode is not None: f[2].manifest()["permission_policy"]["rules"][0]["approval"] = mode
  opened(f); p = prepare(f)
  with pytest.raises(Conflict, match="OPERATION_APPROVAL_SOURCE_MISMATCH"): deterministic(f, p)
  assert f[0].bridge.ledger.status(p["operation_id"])["state"] == "prepared"
  assert issued(f, p)["source"] == "human"


@pytest.mark.parametrize("field,value", [("source", "human"), ("reviewer_identity", "9" * 64), ("approval", "deterministic-policy")])
def test_rpc_does_not_accept_caller_authority_fields(tmp_path, field, value):
  f, p = classified(tmp_path)
  with pytest.raises(ConfigError): deterministic(f, p, **{field: value})
  assert f[0].bridge.ledger.status(p["operation_id"])["state"] == "prepared"


def test_worker_and_closing_supervisor_cannot_issue(tmp_path):
  f, p = classified(tmp_path); args = {"operation_id": p["operation_id"], "context": f[4]}
  with pytest.raises(Conflict): f[5]("issue_deterministic", args, caller=Principal("worker", f[3].lease_id, f[3].grant_generation))
  f[2].service.closing = True
  with pytest.raises(Conflict, match="监督者正在关闭"): deterministic(f, p)
  assert f[0].bridge.ledger.status(p["operation_id"])["state"] == "prepared"


def test_policy_change_before_issue_never_allocates_or_reuses_old_prepared(tmp_path):
  f, p = classified(tmp_path)
  f[2].manifest()["permission_policy"]["rules"][0]["approval"] = "human"
  with pytest.raises(Conflict): deterministic(f, p)
  assert f[0].bridge.ledger.status(p["operation_id"])["state"] == "revoked"
  assert [r for r in f[2].store.records() if r["kind"] == "external"] == []


def test_reply_lost_after_original_issue_retains_map_and_revokes_without_retry(tmp_path, monkeypatch):
  f, p = classified(tmp_path); original = f[0].bridge.issue; calls = []
  def lost(*args, **kwargs):
    result = original(*args, **kwargs); calls.append(result); raise OSError("SYNTHETIC_PRIVATE")
  monkeypatch.setattr(f[0].bridge, "issue", lost)
  with pytest.raises(Conflict, match="OPERATION_DETERMINISTIC_ISSUE_UNKNOWN") as error: deterministic(f, p)
  assert "SYNTHETIC_PRIVATE" not in str(error.value)
  assert len(calls) == 1 and calls[0]["permit_id"] in f[0].bridge.permits
  assert f[0].bridge.ledger.status(p["operation_id"])["state"] == "revoked"
  with pytest.raises(Conflict): deterministic(f, p)
  assert len(calls) == 1 and [r for r in f[2].store.records() if r["kind"] == "external"] == []


def test_two_deterministic_issuers_get_one_original_permit(tmp_path):
  f, p = classified(tmp_path); barrier = Barrier(2)
  def run(_):
    barrier.wait(timeout=5)
    try: return deterministic(f, p)
    except Conflict: return None
  with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(run, range(2)))
  assert sum(type(result) is dict for result in results) == 1
  assert len(f[0].bridge.permits) == 1


@pytest.mark.parametrize("retired", [False, True])
def test_scoped_deterministic_issue_uses_original_scope_and_never_reviewer_qualification(tmp_path, retired):
  from test_pi_scoped_admission_control import fixture as scoped_fixture, arguments, prepare as scoped_prepare, consume, external
  f = scoped_fixture(tmp_path)
  for rule in f["host"].manifest()["permission_policy"]["rules"]:
    if rule["kind"] == "file" and rule["effect"] == "allow": rule["approval"] = "deterministic-policy"
  p = scoped_prepare(f, arguments(f)); row = f["control"].operation_requests[p["operation_id"]]
  assert p["resolution"]["policy"]["approval"] == "deterministic-policy"
  assert f["shared"]._reviewer_current is None
  if retired:
    f["store"].retire_intent(row["scope_refs"]["session_scope"], f["current"]["user_intent_ref"])
    with pytest.raises(Conflict): f["call"]("issue_deterministic", {"operation_id": p["operation_id"], "context": f["current"]})
    assert external(f) == [] and f["shared"].status(p["operation_id"])["state"] == "revoked"
  else:
    permit = f["call"]("issue_deterministic", {"operation_id": p["operation_id"], "context": f["current"]})
    assert permit["source"] == "deterministic-policy" and consume(f, permit)["state"] == "consumed"
    assert len(external(f)) == 1
