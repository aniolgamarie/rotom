"""真实临时authority/account作为live permit hook；无SDK/模型/OS进程。"""
from copy import deepcopy
import json

import pytest

from agentcfg.activity import digest
from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.pi_reviewer_authority import ReviewerAuthorityStore
from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.storage import Conflict, Tree
from test_pi_operation_admission import fixture as admission_fixture, prepare, issue
from test_pi_reviewer_account_authority import document, request


FILE = "reviewer-authority.json"


def fixture(tmp_path, *, account_row=False):
  home = tmp_path / "synthetic-account"; home.mkdir(mode=0o700)
  store = ReviewerAuthorityStore(account_home=home); saved = store.create(document()); clock = [150]
  observations = []; account = None; row_id = None
  def current(prepared, context):
    # 只读live授权，绝不重入Admission；原context未变不能代替物理文件核验。
    observations.append(prepared["operation_id"])
    store.verify_current(saved["identity"], now=clock[0])
    if account is not None:
      row = account.get(row_id)
      assert row["binding"]["operation_id"] == prepared["operation_id"] and row["send_state"] == "committed"
      assert row["binding"]["operation_digest"] == prepared["operation_digest"]
      assert row["binding"]["context_digest"] == digest(context)
      assert row["binding"]["reviewer_identity"] == context["reviewer_identity"]
    return True
  f = admission_fixture(reviewer_current=current)
  f[1].update(profile="pi-full", reviewer_identity="1" * 64)
  operation = prepare(f)
  if account_row:
    account = ReviewerAccountLedger(account_home=home, authority_identity=saved["identity"], now=lambda: clock[0])
    value = request(); value["binding"].update(operation_id=operation["operation_id"], operation_digest=operation["operation_digest"],
      context_digest=digest(f[1]), reviewer_identity=f[1]["reviewer_identity"])
    row_id = account.reserve(**value)["binding"]["operation_id"]
    account.claim_attempt(row_id); account.commit_send(row_id)
  return {"f": f, "operation": operation, "home": home, "store": store, "saved": saved, "clock": clock,
    "calls": observations, "account": account, "path": home / ".agentcfg-workspaces" / FILE}


def permit(f):
  return issue(f["f"], f["operation"], source="reviewer", reviewer_identity="1" * 64)


def consume(f, value):
  return f["f"][0].consume(value, current=f["f"][1], resolved=f["f"][2])


def disturb(f, fault):
  path = f["path"]; original = path.read_bytes()
  if fault == "update":
    changed = document(); changed["generation"] = 2; changed["limits"]["max_calls"] = 1
    f["store"].update(changed, expected_identity=f["saved"]["identity"])
  elif fault == "replace":
    with Tree(path.parent) as tree:
      raw = tree.read(FILE); tree.replace(FILE, raw[0], expected=raw[2])
    assert path.read_bytes() == original
  elif fault == "missing": path.unlink()
  elif fault == "corrupt": path.write_bytes(b'{"SYNTHETIC_PRIVATE":invalid}')
  elif fault == "permission": path.chmod(0o000)
  elif fault == "mode": path.chmod(0o644)
  elif fault == "expired": f["clock"][0] = 200
  else: raise AssertionError("unknown test fault")
  return original


def restore(f, original):
  f["clock"][0] = 150
  # 恢复合法正文不能复活旧permit；同正文新物理身份也不能复活旧authority。
  if f["path"].exists(): f["path"].chmod(0o600)
  f["path"].write_bytes(original); f["path"].chmod(0o600)


def test_real_live_store_issue_and_consume_return_private_once(tmp_path):
  f = fixture(tmp_path); value = permit(f)
  assert f["calls"] == [f["operation"]["operation_id"]]
  assert consume(f, value) == {"prepared": f["operation"], "private_input": f["f"][3]}
  assert len(f["calls"]) == 2
  with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, value)
  assert len(f["calls"]) == 2


@pytest.mark.parametrize("fault", ["update", "replace", "missing", "corrupt", "expired", "permission", "mode"])
def test_actual_authority_exit_before_issue_blocks_without_execution(tmp_path, fault):
  f = fixture(tmp_path); original = deepcopy(f["f"][1]); disturb(f, fault); executions = []
  with pytest.raises(Conflict) as error: executions.append(permit(f))
  assert str(error.value) == "OPERATION_REVIEWER_UNQUALIFIED" and "SYNTHETIC_PRIVATE" not in str(error.value)
  assert f["f"][1] == original and executions == []
  assert f["f"][0].status(f["operation"]["operation_id"])["state"] == "prepared"


@pytest.mark.parametrize("fault", ["update", "replace", "missing", "corrupt", "expired", "permission", "mode"])
def test_actual_authority_exit_after_issue_burns_before_returning_input(tmp_path, fault):
  f = fixture(tmp_path); value = permit(f); context = deepcopy(f["f"][1]); original = disturb(f, fault); executions = []
  with pytest.raises(Conflict) as error: executions.append(consume(f, value))
  assert str(error.value) == "OPERATION_REVIEWER_UNQUALIFIED" and error.value.__cause__ is None
  assert "SYNTHETIC_PRIVATE" not in str(error.value)
  assert executions == [] and f["f"][1] == context
  assert f["f"][0].status(f["operation"]["operation_id"])["state"] == "revoked"
  assert len(f["calls"]) == 2
  if fault == "expired":
    f["clock"][0] = 150
    # 此项真正恢复原live身份+窗口，仍须原permit永久烧毁。
    f["store"].verify_current(f["saved"]["identity"], now=150)
  else: restore(f, original)
  with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, value)
  with pytest.raises(Conflict, match="NOT_PENDING"): permit(f)
  assert len(f["calls"]) == 2 and executions == []


@pytest.mark.parametrize("source", ["human", "deterministic-policy"])
def test_non_reviewer_issue_and_consume_do_not_read_live_authority(tmp_path, source):
  f = fixture(tmp_path); f["path"].unlink()
  value = issue(f["f"], f["operation"], source=source)
  assert consume(f, value)["private_input"] == f["f"][3]
  assert f["calls"] == []


@pytest.mark.parametrize("phase", ["issue", "consume"])
def test_busy_real_account_lock_is_fixed_rejection_and_no_input(tmp_path, phase):
  f = fixture(tmp_path); value = permit(f) if phase == "consume" else None; executions = []
  roots = RegisteredRoots(account_home=f["home"])
  with roots._locked(write=True):
    with pytest.raises(Conflict) as error:
      executions.append(permit(f) if phase == "issue" else consume(f, value))
  assert str(error.value) == "OPERATION_REVIEWER_UNQUALIFIED" and executions == []
  if phase == "consume":
    # 锁已释放、实际authority仍可核验，旧permit仍不可用。
    f["store"].verify_current(f["saved"]["identity"], now=150)
    with pytest.raises(Conflict, match="PERMIT_USED"): consume(f, value)
    with pytest.raises(Conflict, match="NOT_PENDING"): permit(f)


def test_hook_reads_real_bound_account_row_under_admission_then_account_then_ledger(tmp_path, monkeypatch):
  from agentcfg import pi_reviewer_account as module
  f = fixture(tmp_path, account_row=True); observed = []; original = module.ReviewerLedger.get
  def read(inner, operation_id):
    assert f["f"][0]._lock.locked()
    # account短锁已经持有：真实竞争账户update应busy，不重入Admission。
    changed = document(); changed["generation"] = 2; changed["limits"]["max_calls"] = 1
    with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"):
      f["store"].update(changed, expected_identity=f["saved"]["identity"])
    observed.append(operation_id)
    return original(inner, operation_id)
  with monkeypatch.context() as patch:
    patch.setattr(module.ReviewerLedger, "get", read)
    value = permit(f)
    result = consume(f, value)
  assert result["private_input"] == f["f"][3] and observed == [f["operation"]["operation_id"]] * 2
  row = f["account"].get(f["operation"]["operation_id"])
  assert row["send_state"] == "committed" and row["requests"] is None
  facts = f["account"].snapshot()
  assert facts["committed_calls"] == 1 and facts["unknown_requests"] == 1 and facts["reserved_cost_units"] == 320
  assert "synthetic private token" not in json.dumps(facts)
