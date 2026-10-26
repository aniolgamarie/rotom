"""明确停止审阅与实际接受事务的顺序；只用临时资源和合成身份。"""

from copy import deepcopy
import fcntl

import pytest

from agentcfg import maintenance, maintenance_deployment, maintenance_live
from agentcfg import maintenance_store as store, stop_review
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance import checkpoint
from test_rotom_maintenance_live_store import acceptance, leases_for, owners_locked
from test_rotom_maintenance_recovery import BATCH, RUNS, group, ledger
from test_rotom_resource_owners import owner_path


def reviewed(value, approve=lambda plan: True):
  plan = value["batch"]["plan"]
  return stop_review.review_stop_plan(plan, scope=plan["scope"], operation=plan["operation"],
    selected_runs=list(reversed(plan["selected_runs"])), plan_id=plan["plan_id"],
    batch_id=value["batch"]["batch_id"], approve=approve)


def assert_consumed(review, value):
  with pytest.raises(Conflict):
    stop_review.consume_stop_review(review, plan=value["batch"]["plan"], batch_id=value["batch"]["batch_id"])


def test_review_precedes_locks_and_consumption_follows_live_checks_before_first_write(group, monkeypatch):
  case = group(); value = acceptance(case)
  before = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  events = []
  def approve(plan):
    assert plan == value["batch"]["plan"]
    with Tree(case.domain.root) as tree:
      fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    owners_locked(case, held=False)
    events.append("review")
    return True
  review = reviewed(value, approve)
  consume, publish = stop_review.consume_stop_review, Tree.write_new
  def observed_consume(received, **kwargs):
    assert received is review and not checkpoint(case).exists()
    with Tree(case.domain.root) as tree:
      with pytest.raises(BlockingIOError):
        fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    owners_locked(case, held=True)
    events.append("consume")
    return consume(received, **kwargs)
  def observed_publish(tree, name, *args, **kwargs):
    assert events == ["review", "consume"]
    with pytest.raises(Conflict):
      consume(review, plan=value["batch"]["plan"], batch_id=BATCH)
    events.append("snapshot")
    return publish(tree, name, *args, **kwargs)
  with leases_for(case) as leases, monkeypatch.context() as patch:
    patch.setattr(stop_review, "consume_stop_review", observed_consume)
    patch.setattr(Tree, "write_new", observed_publish)
    assert store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review) is None
  assert events == ["review", "consume", "snapshot"]
  assert store.read_stop_snapshot(case.domain, BATCH)["acceptance"] == value
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == before
  assert_consumed(review, value)


@pytest.mark.parametrize("review", [None, True, {}, {"approved": True}])
def test_json_or_boolean_review_never_publishes(group, review):
  case = group(); value = acceptance(case); before = ledger(case.domain)
  with leases_for(case) as leases, pytest.raises(Conflict):
    store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review)
  assert ledger(case.domain) == before and not checkpoint(case).exists()
  owners_locked(case, held=False)


@pytest.mark.parametrize("change", ["batch", "plan"])
def test_changed_request_does_not_consume_original_review(group, change):
  case = group(); value = acceptance(case); review = reviewed(value)
  changed = deepcopy(value)
  if change == "batch":
    changed["batch"]["batch_id"] = "9" * 32
  else:
    plan = changed["batch"]["plan"]
    snapshots = [{key: item for key, item in run.items() if key != "observation_digest"}
      for run in plan["runs"]]
    plan = maintenance.build_stop_plan(scope={**plan["scope"], "agent": "omp"},
      operation=plan["operation"], selected_runs=plan["selected_runs"], runs=snapshots, resources=plan["resources"])
    changed = maintenance.build_stop_acceptance(batch_id=BATCH, plan=plan,
      records=value["records"], expected_revision=value["expected_revision"])
  before = ledger(case.domain)
  with leases_for(case) as leases:
    with pytest.raises(Conflict):
      store.accept_reviewed_stop_snapshot_live(case.domain, changed, leases=leases, review=review)
    assert ledger(case.domain) == before
    assert not checkpoint(case, changed["batch"]["batch_id"]).exists()
    store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review)
  assert_consumed(review, value)


@pytest.mark.parametrize("boundary", ["deployment", "owners"])
def test_live_check_failure_precedes_review_consumption(group, monkeypatch, boundary):
  case = group(); value = acceptance(case); review = reviewed(value); before = ledger(case.domain)
  def reject(*args, **kwargs):
    raise Conflict("synthetic-private-value")
  with leases_for(case) as leases:
    with monkeypatch.context() as patch:
      module, name = ((maintenance_deployment, "check_stop_deployment") if boundary == "deployment"
        else (maintenance_live, "hold_stop_owners"))
      patch.setattr(module, name, reject)
      with pytest.raises(Conflict) as caught:
        store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review)
      assert "synthetic-private-value" not in str(caught.value)
    assert ledger(case.domain) == before and not checkpoint(case).exists()
    store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review)
  assert_consumed(review, value)


@pytest.mark.parametrize("stage", ["snapshot-before", "snapshot-after", "commit-before", "commit-after"])
def test_failed_publication_never_restores_review_or_retries(group, monkeypatch, stage):
  case = group(); value = acceptance(case); review = reviewed(value)
  write, replace = Tree.write_new, Tree.replace
  calls = []
  def publish(tree, name, *args, **kwargs):
    calls.append("snapshot")
    assert_consumed(review, value)
    if stage == "snapshot-before":
      raise OSError("synthetic-private-value")
    result = write(tree, name, *args, **kwargs)
    if stage == "snapshot-after":
      raise OSError("synthetic-private-value")
    return result
  def commit(tree, name, *args, **kwargs):
    calls.append("commit")
    assert_consumed(review, value)
    if stage == "commit-before":
      raise OSError("synthetic-private-value")
    result = replace(tree, name, *args, **kwargs)
    if stage == "commit-after":
      raise OSError("synthetic-private-value")
    return result
  with leases_for(case) as leases:
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "write_new", publish); patch.setattr(Tree, "replace", commit)
      with pytest.raises(Conflict) as caught:
        store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review)
      assert "synthetic-private-value" not in str(caught.value)
    assert_consumed(review, value)
    # 即使第一次写入尚未发生，重用批准也不能重新发布。
    before = ledger(case.domain), checkpoint(case).read_bytes() if checkpoint(case).exists() else None
    with pytest.raises(Conflict):
      store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review)
    assert before == (ledger(case.domain), checkpoint(case).read_bytes() if checkpoint(case).exists() else None)
  assert calls == (["snapshot"] if stage.startswith("snapshot") else ["snapshot", "commit"])
  assert checkpoint(case).exists() == (stage != "snapshot-before")
  assert (BATCH in case.domain.snapshot()["intents"]) == (stage == "commit-after")
  owners_locked(case, held=False)


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_control_exception_keeps_consumption_and_existing_evidence(group, monkeypatch, error):
  case = group(); value = acceptance(case); review = reviewed(value)
  write = Tree.write_new
  def interrupt(tree, name, *args, **kwargs):
    write(tree, name, *args, **kwargs)
    raise error()
  with leases_for(case) as leases, monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", interrupt)
    with pytest.raises(error):
      store.accept_reviewed_stop_snapshot_live(case.domain, value, leases=leases, review=review)
  assert_consumed(review, value)
  owners_locked(case, held=False)
  assert checkpoint(case).exists() and BATCH not in case.domain.snapshot()["intents"]
