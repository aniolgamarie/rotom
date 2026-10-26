"""停止审阅到完整计划快照的内部保存；假能力，绝不授予进程控制。"""
from copy import deepcopy

import pytest

from agentcfg import dsh_stop, dsh_stop_plan, dsh_stop_scope, run_owners, run_stop_fence, stop_review
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import MANAGER, observation
from test_rotom_dsh_stop_request_scope import HOST


@pytest.fixture
def candidate(prepared):
  ws, registry, args, runs = prepared
  for run in runs[:2]:
    record = args["expected_records"][run]
    record["host_identity"] = deepcopy(HOST)
    record["process_observation"]["host_identity"] = deepcopy(HOST)
    (registry.root / (run + ".json")).write_bytes(run_owners._encode(record))
  plan = dsh_stop.preview_stop(ws, selected_runs=runs[:2])["plan"]
  # 明确的测试能力声明；生产预览始终 unavailable/unknown。
  plan["control_capability"] = "supported"
  for resource in plan["resources"]: resource["coverage"] = "complete"
  plan = dsh_stop_plan.normalize(plan, verify=False)
  review = stop_review.review_stop_plan(plan, scope=plan["scope"], operation=plan["operation"],
    selected_runs=plan["selected_runs"], plan_id=plan["plan_id"], batch_id=args["batch_id"], approve=lambda _: True)
  return prepared, plan, review


def save(candidate, **changes):
  (ws, registry, args, runs), plan, review = candidate
  values = {key: args[key] for key in ("instance_fd", "state_fd", "expected_records", "expected_layout", "batch_id")}
  return dsh_stop_scope.save_reviewed_snapshot(ws, **(values | {"plan": plan, "review": review} | changes))


def consume(candidate):
  (_, _, args, _), plan, review = candidate
  stop_review.consume_stop_review(review, plan=plan, batch_id=args["batch_id"])


def test_full_plan_saved_before_fence_review_consumed_once(candidate, monkeypatch):
  (ws, registry, args, runs), plan, review = candidate
  writes = []; original = Tree.write_new
  def write(tree, name, data):
    assert_exclusive_busy(ws.instance)
    assert_exclusive_busy(ws.state_root / "instance.lock")
    with pytest.raises(Conflict):
      with registry._locked(nonblocking=True): pass
    with pytest.raises(Conflict): consume(candidate)
    writes.append(name)
    return original(tree, name, data)
  monkeypatch.setattr(Tree, "write_new", write)
  assert save(candidate) is None
  snapshot = run_stop_fence.read_snapshot(registry, args["batch_id"])
  assert snapshot["schema_version"] == 2 and snapshot["plan"] == plan
  assert snapshot["selected_runs"] == sorted(runs[:2]) and runs[2] not in snapshot["records"]
  assert writes == [run_stop_fence._snapshot_name(registry, args["batch_id"]), run_stop_fence._name(registry)]
  assert run_stop_fence.read(registry)["plan_id"] == plan["plan_id"]
  assert registry.snapshot() == args["expected_records"]
  with pytest.raises(Conflict): save(candidate)


@pytest.mark.parametrize("drift", ["records", "layout", "plan-resource"])
def test_drift_before_publication_preserves_unused_review(candidate, drift):
  (ws, registry, args, runs), plan, review = candidate
  changes = {}
  if drift == "records": registry.mark_unknown(runs[2], MANAGER)
  elif drift == "layout": changes["expected_layout"] = args["expected_layout"] | {"extra": True}
  else:
    changed = deepcopy(plan)
    from agentcfg.resource_keys import ResourceKey
    old = changed["resources"][0]["key"]
    changed["resources"][0]["key"] = ResourceKey(old["kind"], old["device"], old["inode"] + 1).as_dict()
    changed = dsh_stop_plan.normalize(changed, verify=False)
    changes["plan"] = changed
  with pytest.raises(Conflict): save(candidate, **changes)
  assert run_stop_fence.read(registry) is None
  assert run_stop_fence.read_snapshot(registry, args["batch_id"]) is None
  consume(candidate)


@pytest.mark.parametrize("failure", ["snapshot", "fence"])
def test_partial_publication_keeps_orphan_and_consumed_review(candidate, monkeypatch, failure):
  (ws, registry, args, runs), plan, review = candidate
  original = Tree.write_new
  def fail(tree, name, data):
    if failure == "snapshot" or name == run_stop_fence._name(registry): raise OSError("synthetic-private-error")
    return original(tree, name, data)
  monkeypatch.setattr(Tree, "write_new", fail)
  with pytest.raises(Conflict) as caught: save(candidate)
  assert "synthetic-private-error" not in str(caught.value)
  assert run_stop_fence.read(registry) is None
  saved = run_stop_fence.read_snapshot(registry, args["batch_id"])
  assert saved is None if failure == "snapshot" else saved["plan"] == plan
  with pytest.raises(Conflict): consume(candidate)
  with pytest.raises(Conflict): save(candidate)


@pytest.mark.parametrize("failure", ["blocked", "no-review", "used", "wrong-batch"])
def test_requires_ready_plan_and_exact_unused_review(candidate, failure):
  (ws, registry, args, runs), plan, review = candidate
  changes = {}
  if failure == "blocked":
    changed = deepcopy(plan); changed["control_capability"] = "unavailable"
    changes["plan"] = dsh_stop_plan.normalize(changed, verify=False)
  elif failure == "no-review": changes["review"] = None
  elif failure == "used": consume(candidate)
  else: changes["batch_id"] = "c" * 32
  with pytest.raises(Conflict): save(candidate, **changes)
  assert run_stop_fence.read(registry) is None
  assert run_stop_fence.read_snapshot(registry, args["batch_id"]) is None
  if failure != "used": consume(candidate)


def test_owner_drift_after_consumption_rejects_without_restoring_review(candidate, monkeypatch):
  (ws, registry, args, runs), plan, review = candidate
  original = stop_review.consume_stop_review
  def consume_and_change(*a, **kw):
    original(*a, **kw)
    record = deepcopy(args["expected_records"][runs[2]])
    record["start_cwd"]["path"] = "/synthetic-change"
    (registry.root / (runs[2] + ".json")).write_bytes(run_owners._encode(record))
  monkeypatch.setattr(stop_review, "consume_stop_review", consume_and_change)
  with pytest.raises(Conflict): save(candidate)
  assert run_stop_fence.read(registry) is None
  assert run_stop_fence.read_snapshot(registry, args["batch_id"]) is None
  with pytest.raises(Conflict): original(review, plan=plan, batch_id=args["batch_id"])


def test_current_request_can_read_full_plan_snapshot_after_another_target_exits(candidate, monkeypatch):
  (ws, registry, args, runs), plan, review = candidate
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  save(candidate)
  registry.finish_current(runs[0], MANAGER, run_owners.ReleaseObservation(runs[0], MANAGER, True, True))
  request = {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop", "request_id": "d" * 32,
    "batch_id": args["batch_id"], "plan_id": plan["plan_id"], "run_id": runs[1],
    "manager_identity": deepcopy(MANAGER), "host_identity": deepcopy(HOST["identity"]), "deadline_ns": 1}
  actual = dsh_stop_scope.inspect_stop_request(ws, request, instance_fd=args["instance_fd"],
    state_fd=args["state_fd"], expected_layout=args["expected_layout"])
  assert actual == args["expected_records"][runs[1]]
  assert run_stop_fence.read_snapshot(registry, args["batch_id"])["plan"] == plan
