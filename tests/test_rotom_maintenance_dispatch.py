"""setup 派发前的真实临时锁与持久记账；不执行 setup、宿主或信号。"""
from copy import deepcopy
import json

import pytest

from agentcfg import maintenance_progress as progress, maintenance_release as release, run_owners
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_recovery import BATCH, RUNS, group, ledger
from test_rotom_maintenance_release import build_stopped, assert_locks
from test_rotom_resource_owners import owner_path
from test_rotom_resource_coordination import locked
from test_rotom_resource_owners import IDENTITY


DIGEST = "8" * 64


@pytest.fixture
def released(group):
  case, workspaces = build_stopped(group)
  batch = release.confirm_setup_release(case.domain, BATCH, expected_revision=2, workspaces=workspaces)
  return case, workspaces, batch


def reviewed(value):
  from agentcfg.maintenance_permit import review_setup
  case, _, batch = value
  generation = case.domain.snapshot()["intents"][BATCH]["generation"]
  return review_setup(batch, intent_generation=generation, setup_plan_digest=DIGEST, approve=lambda preview: True)


def dispatch(value, *, review=None, revision=3, workspaces=None, digest=DIGEST):
  from agentcfg.maintenance_dispatch import record_setup_dispatch
  case, selected, _ = value
  return record_setup_dispatch(case.domain, BATCH, expected_revision=revision,
    workspaces=selected if workspaces is None else workspaces,
    review=reviewed(value) if review is None else review, setup_plan_digest=digest)


def test_durable_intent_then_permit_without_setup_or_clearing_protection(released):
  from agentcfg.maintenance_permit import BatchPermit, consume_batch_permit
  case, workspaces, before = released
  original = case.domain.snapshot()
  owners = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  result = dispatch(released)
  saved = progress.read_batch(case.domain, BATCH)
  assert result.batch == saved and type(result.permit) is BatchPermit
  assert saved["revision"] == 4 and saved["phase"] == "maintenance_dispatch_intent"
  assert saved["maintenance_dispatch"]["state"] == "dispatch_intent"
  assert len(saved["maintenance_dispatch"]["dispatch_id"]) == 32
  assert saved["items"] == before["items"] and saved["operation_result"] is None
  after = case.domain.snapshot()
  assert after["reservations"] == original["reservations"]
  assert after["intents"][BATCH]["phase"] == original["intents"][BATCH]["phase"]
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == owners
  assert_locks(case, workspaces, held=False)
  consume_batch_permit(result.permit, batch=saved,
    intent_generation=after["intents"][BATCH]["generation"], setup_plan_digest=DIGEST)
  with pytest.raises(Conflict):
    dispatch(released, revision=4)
  with pytest.raises(Conflict):
    case.domain.cancel_intent(BATCH)


@pytest.mark.parametrize("fault", [None, "before", "after"])
def test_commit_holds_physical_and_owner_locks_response_loss_never_issues_permit(released, monkeypatch, fault):
  from agentcfg import maintenance_permit as permit
  case, workspaces, batch = released
  review = reviewed(released)
  replace, issue = Tree.replace, permit._issue_batch_permit
  writes, issued = [], []
  def commit(tree, name, data, *args, **kwargs):
    if name != "coordination.json":
      return replace(tree, name, data, *args, **kwargs)
    writes.append(json.loads(data))
    assert_locks(case, workspaces, held=True)
    if fault == "before":
      raise OSError("synthetic-private-canary")
    value = replace(tree, name, data, *args, **kwargs)
    assert_locks(case, workspaces, held=True)
    if fault == "after":
      raise OSError("synthetic-private-canary")
    return value
  def issuance(*args, **kwargs):
    assert_locks(case, workspaces, held=False)
    assert progress.read_batch(case.domain, BATCH)["phase"] == "maintenance_dispatch_intent"
    issued.append(True)
    return issue(*args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", commit)
    patch.setattr(permit, "_issue_batch_permit", issuance)
    if fault:
      with pytest.raises(Conflict) as caught:
        dispatch(released, review=review)
      assert "canary" not in str(caught.value)
    else:
      dispatch(released, review=review)
  assert len(writes) == 1 and issued == ([] if fault else [True])
  assert_locks(case, workspaces, held=False)
  saved = progress.read_batch(case.domain, BATCH)
  assert saved["revision"] == (3 if fault == "before" else 4)
  # 首次写入前即消费批准；响应失败后不归还，不重新签发。
  before_retry = ledger(case.domain)
  with pytest.raises(Conflict):
    dispatch(released, review=review, revision=saved["revision"])
  assert ledger(case.domain) == before_retry
  if fault == "after":
    # 旧快照重新取得一份显式审阅，也不能越过已经持久化的派发状态。
    with pytest.raises(Conflict):
      dispatch(released, review=reviewed(released), revision=4)
    assert ledger(case.domain) == before_retry


@pytest.mark.parametrize("change", ["owner-unknown", "deployment", "shared-third"])
def test_release_fact_is_not_enough_when_live_evidence_changes(released, change):
  case, workspaces, _ = released
  review = reviewed(released)
  ws = workspaces[RUNS[0]]
  if change == "owner-unknown":
    path = owner_path(ws, RUNS[0]); record = json.loads(path.read_bytes())
    run_owners._set_state(record, "unknown")
    with Tree(ws.state_root / "run-owners") as tree:
      tree.write_state(RUNS[0] + ".json", run_owners._encode(record))
  elif change == "deployment":
    (ws.instance / "managed.txt").write_bytes(b"synthetic-private-canary")
  else:
    # 合法编码的竞争现场不能因先前的释放事实而被忽略。
    with case.domain._transaction(write=True) as state:
      third = state["reservations"][RUNS[2]]
      third["resources"] = sorted(set(third["resources"]) | {case.runtime["resource_id"]})
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    dispatch(released, review=review)
  assert ledger(case.domain) == before
  assert_locks(case, workspaces, held=False)


def test_dispatch_codec_retains_reviewed_setup_digest_and_legacy_history():
  from agentcfg import maintenance
  from test_rotom_maintenance_codec import batch
  value = batch("maintenance_dispatch_intent", operation="setup")
  assert maintenance.decode_batch(maintenance.encode_batch(value)) == value
  value["maintenance_dispatch"]["setup_plan_digest"] = DIGEST
  assert maintenance.decode_batch(maintenance.encode_batch(value)) == value


@pytest.mark.parametrize("digest", [None, True, "8" * 63, "G" * 64, {"private-canary": True}])
def test_dispatch_codec_rejects_invalid_setup_digest(digest):
  from agentcfg import maintenance
  from test_rotom_maintenance_codec import batch
  value = batch("maintenance_dispatch_intent", operation="setup")
  value["maintenance_dispatch"]["setup_plan_digest"] = digest
  with pytest.raises(Conflict):
    maintenance.encode_batch(value)


def test_no_dispatch_cannot_claim_reviewed_setup_digest():
  from agentcfg import maintenance
  from test_rotom_maintenance_codec import batch
  value = batch("stopped_confirmed", operation="setup")
  value["maintenance_dispatch"]["setup_plan_digest"] = DIGEST
  with pytest.raises(Conflict):
    maintenance.encode_batch(value)


@pytest.mark.parametrize("revision", [True, -1, 2, 4])
def test_revision_mismatch_never_changes_durable_state(released, revision):
  case, workspaces, _ = released; before = ledger(case.domain)
  with pytest.raises(Conflict):
    dispatch(released, revision=revision)
  assert ledger(case.domain) == before
  assert_locks(case, workspaces, held=False)


@pytest.mark.parametrize("kind", ["instance", "state", "runtime"])
def test_original_physical_guards_are_still_required_after_release_fact(released, kind):
  case, workspaces, _ = released; ws = workspaces[RUNS[0]]
  review = reviewed(released); before = ledger(case.domain)
  guard = (locked(case.cache, IDENTITY) if kind == "runtime" else
    _shared_file(ws.instance, ".agentcfg-omp.lock") if kind == "instance" else
    _shared_file(ws.state_root, "instance.lock"))
  with guard, pytest.raises(Conflict):
    dispatch(released, review=review)
  assert ledger(case.domain) == before
  # 没有进入写入门禁的失败没有消费原审阅。
  assert dispatch(released, review=review).batch["phase"] == "maintenance_dispatch_intent"


@pytest.mark.parametrize("change", ["missing", "extra", "wrong", "not-dict"])
def test_exact_trusted_workspace_scope_is_required(released, change):
  case, workspaces, _ = released; chosen = dict(workspaces)
  if change == "missing": del chosen[RUNS[0]]
  elif change == "extra": chosen[RUNS[2]] = case.rows[2].workspace
  elif change == "wrong": chosen[RUNS[0]] = case.rows[2].workspace
  else: chosen = tuple(chosen.items())
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    dispatch(released, workspaces=chosen)
  assert ledger(case.domain) == before
  assert_locks(case, workspaces, held=False)


@pytest.mark.parametrize("digest", ["9" * 64, None, "private-canary"])
def test_setup_approval_cannot_be_retargeted(released, digest):
  case, workspaces, _ = released; before = ledger(case.domain)
  with pytest.raises(Conflict):
    dispatch(released, digest=digest)
  assert ledger(case.domain) == before
  assert_locks(case, workspaces, held=False)


def test_revision_race_under_physical_guards_does_not_resign_cas(released, monkeypatch):
  from agentcfg import maintenance_dispatch as core
  case, workspaces, _ = released; review = reviewed(released)
  original = core.check_stop_deployment; changed = []
  def race(*args, **kwargs):
    original(*args, **kwargs)
    if not changed:
      with case.domain._transaction(write=True) as state:
        state["intents"][BATCH]["progress"]["revision"] += 1
      changed.append(ledger(case.domain))
  monkeypatch.setattr(core, "check_stop_deployment", race)
  with pytest.raises(Conflict):
    dispatch(released, review=review)
  assert len(changed) == 1 and ledger(case.domain) == changed[0]
  assert_locks(case, workspaces, held=False)


def test_permit_issue_failure_after_commit_cannot_be_replayed(released, monkeypatch):
  from agentcfg import maintenance_permit as permit
  case, workspaces, _ = released; calls = []
  def fail(*args, **kwargs):
    calls.append(True)
    raise OSError("synthetic-private-canary")
  monkeypatch.setattr(permit, "_issue_batch_permit", fail)
  with pytest.raises(Conflict):
    dispatch(released)
  saved = ledger(case.domain)
  assert progress.read_batch(case.domain, BATCH)["phase"] == "maintenance_dispatch_intent"
  with pytest.raises(Conflict):
    dispatch(released, revision=4)
  assert calls == [True] and ledger(case.domain) == saved
  assert_locks(case, workspaces, held=False)


def test_durable_dispatch_does_not_relax_ordinary_writes_or_start_reservations(released):
  case, workspaces, _ = released
  dispatch(released)
  before = ledger(case.domain)
  with locked(case.cache, IDENTITY, exclusive=True) as fd, pytest.raises(Conflict):
    case.domain.check_runtime(case.cache, IDENTITY, lease_fd=fd, idle=True)
  with case.domain._transaction() as state, pytest.raises(Conflict):
    case.domain._unfenced(state, case.rows[0].resources)
  with pytest.raises(Conflict):
    case.domain.reserve(run_id="d" * 32, op_id="e" * 32,
      owner_ref=case.domain.snapshot()["reservations"][RUNS[0]]["owner_ref"],
      resources=sorted(case.rows[0].resources))
  assert ledger(case.domain) == before


def test_stop_approval_is_not_setup_approval(released):
  from agentcfg.stop_review import review_stop_plan
  case, _, batch = released; plan = batch["plan"]
  review = review_stop_plan(plan, scope=plan["scope"], operation=plan["operation"],
    selected_runs=plan["selected_runs"], plan_id=plan["plan_id"], batch_id=BATCH, approve=lambda value: True)
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    dispatch(released, review=review)
  assert ledger(case.domain) == before


@pytest.mark.parametrize("source", ["maintenance", "restore"])
def test_dispatch_id_does_not_reuse_prior_operation_identifier(source):
  from agentcfg.maintenance_dispatch import _unused_dispatch_id
  from test_rotom_maintenance_codec import batch
  # 此检查只读域内已解码事实，涵盖已结束批次，不依赖随机碰撞概率。
  previous = batch("maintenance_dispatch_intent", operation="setup") if source == "maintenance" else batch("restored")
  collision = (previous["maintenance_dispatch"]["dispatch_id"] if source == "maintenance"
    else previous["items"][0]["launch_dispatch"]["dispatch_id"])
  state = {"intents": {previous["batch_id"]: {"progress": previous}}}
  before = deepcopy(state)
  with pytest.raises(ValueError):
    _unused_dispatch_id(state, collision)
  _unused_dispatch_id(state, "f" * 32)
  assert state == before
