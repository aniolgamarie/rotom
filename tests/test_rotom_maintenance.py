"""真实临时文件的停止接受事务；没有宿主、信号或恢复执行器。"""

from copy import deepcopy
import fcntl
import hashlib
import json
import os
import stat

import pytest

from agentcfg import maintenance, maintenance_store as store, run_owners
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_recovery import BATCH, RUNS, group, ledger
from test_rotom_resource_owners import owner_path


def digest(value):
  return hashlib.sha256(run_owners._encode(value)).hexdigest()


def acceptance(case, *, operation="stop_only", chosen=None, batch_id=BATCH):
  chosen = RUNS[:2] if chosen is None else chosen
  # 模拟未来已核验的 host 绑定；不猜测或探测任何真实 PID。
  records = {}
  with case.domain._transaction(write=True) as state:
    for index, row in enumerate(case.rows):
      record = json.loads(owner_path(row.workspace, row.run).read_bytes())
      host = {"identity": {"pid": 800000 + index, "birth_id": "synthetic-host-" + str(index)},
        "manager_identity": deepcopy(record["manager_identity"]), "source": "synthetic-host-binding",
        "relationship": "reported-by-current-run"}
      record["host_identity"] = host
      record["process_observation"]["host_identity"] = deepcopy(host)
      registry = run_owners.Registry(row.workspace.state_root / "run-owners", row.workspace.binding)
      registry._validate_record(row.run + ".json", record)
      with Tree(registry.root) as tree:
        tree.write_state(row.run + ".json", run_owners._encode(record))
      state["reservations"][row.run]["owner_link"]["record_digest"] = digest(record)
      records[row.run] = record
  state = case.domain.snapshot()
  resources = [{"resource_id": rid, "domain_id": state["domain_id"], "domain_physical": state["physical"],
    "generation": state["revision"], "key": resource["key"], "coverage": "complete",
    "reference_runs": sorted(run for run, entry in state["reservations"].items()
      if rid in entry["resources"] and entry["phase"] not in ("released", "cancelled"))}
    for rid, resource in state["resources"].items()]
  runs = []
  for row in case.rows:
    record = records[row.run]
    runs.append({"run_id": row.run, "scope": {**row.workspace.binding, "agent": "omp"},
      "observation": {"state": "active", "manager_identity": record["manager_identity"],
        "host_identity": {name: record["host_identity"]["identity"][name] for name in ("pid", "birth_id")},
        "record_digest": digest(record)}, "deployment_digest": digest(record["deployed_identity"]),
      "resource_ids": sorted(row.resources),
      "restore": {"mode": "manual", "capability": "unknown", "session_status": "unknown", "target_digest": None}})
  scope = {name: case.rows[0].workspace.binding[name] for name in ("machine", "local")}
  plan = maintenance.build_stop_plan(scope=scope, operation=operation, selected_runs=list(chosen), runs=runs, resources=resources)
  return maintenance.build_stop_acceptance(batch_id=batch_id, plan=plan,
    records={run: records[run] for run in chosen}, expected_revision=state["revision"])


def checkpoint(case, batch_id=BATCH):
  return case.domain.root / ("stop-acceptance-" + batch_id + ".json")


def test_recovery_snapshot_is_durable_before_intent_commit_and_dispatch(group, monkeypatch):
  case = group(); value = acceptance(case)
  before_owners = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  third = deepcopy(case.domain.snapshot()["reservations"][RUNS[2]])
  replace = Tree.replace
  events = []
  def observe(tree, name, data, *args, **kwargs):
    if name == "coordination.json" and BATCH in json.loads(data)["intents"]:
      saved = maintenance.decode_stop_acceptance(checkpoint(case).read_bytes())
      assert saved == value
      events.append(json.loads(data)["intents"][BATCH]["phase"])
      # 协调锁必须仍被持有，不允许其它合作启动穿过发布间隙。
      with Tree(case.domain.root) as independent:
        with pytest.raises(BlockingIOError):
          fcntl.flock(independent.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return replace(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", observe)
  assert store.accept_stop_snapshot(case.domain, value) is None
  assert stat.S_IMODE(checkpoint(case).stat().st_mode) == 0o600
  read = store.read_stop_snapshot(case.domain, BATCH)
  assert read["acceptance"] == value and read["intent"]["phase"] == "active"
  case.domain.dispatch_intent(BATCH)
  assert events == ["active", "dispatched"]
  state = case.domain.snapshot()
  assert state["reservations"][RUNS[2]] == third
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == before_owners
  assert state["intents"][BATCH]["selected_runs"] == list(RUNS[:2])
  assert set(value["records"]) == set(RUNS[:2])


@pytest.mark.parametrize("damage", ["revision", "resource-key", "resource-generation", "references", "owner-digest", "owner-scope", "owner-link", "domain", "unknown-third", "new-run"])
def test_stale_snapshot_cannot_create_checkpoint_or_intent(group, damage):
  case = group(); value = acceptance(case)
  if damage in ("revision", "unknown-third", "new-run"):
    with case.domain._transaction(write=True) as state:
      if damage == "unknown-third": state["reservations"][RUNS[2]]["phase"] = "unknown"
      if damage == "new-run":
        entry = deepcopy(state["reservations"][RUNS[2]])
        entry.update(run_id="8" * 32, op_id="9" * 32, phase="reserved")
        entry.pop("owner_link")
        state["reservations"][entry["run_id"]] = entry
  else:
    # 模拟合法格式的同代元数据损坏；应核对字段，不能只比较 revision。
    path = case.domain.root / "coordination.json"
    state = json.loads(path.read_bytes())
    rid = case.runtime["resource_id"]
    if damage == "resource-key":
      from agentcfg.resource_keys import ResourceKey
      old = state["resources"][rid]["key"]
      state["resources"][rid]["key"] = ResourceKey(old["kind"], old["device"], old["inode"] + 1).as_dict()
    elif damage == "resource-generation":
      value["batch"]["plan"]["resources"][0]["generation"] += 1
      value["batch"]["plan"]["plan_id"] = maintenance._digest({key: item for key, item in value["batch"]["plan"].items() if key != "plan_id"})
    elif damage == "references": state["reservations"][RUNS[2]]["resources"].remove(case.runtime["resource_id"])
    elif damage == "owner-digest": state["reservations"][RUNS[0]]["owner_link"]["record_digest"] = "a" * 64
    elif damage == "owner-scope": state["reservations"][RUNS[0]]["owner_ref"]["binding"]["profile"] = "other"
    elif damage == "owner-link": state["reservations"][RUNS[0]].pop("owner_link")
    elif damage == "domain": state["domain_id"] = "f" * 32
    with Tree(case.domain.root) as tree:
      tree.write_state("coordination.json", (json.dumps(state) + "\n").encode())
  before = ledger(case.domain)
  with pytest.raises(Conflict): store.accept_stop_snapshot(case.domain, value)
  assert ledger(case.domain) == before and not checkpoint(case).exists()


@pytest.mark.parametrize("stage", ["checkpoint-before", "checkpoint-after", "coordination-before", "coordination-after"])
def test_partial_commit_or_lost_response_never_replays_or_deletes_evidence(group, monkeypatch, stage):
  case = group(); value = acceptance(case)
  write, replace = Tree.write_new, Tree.replace
  def publish(tree, name, data, *args, **kwargs):
    if name.startswith("stop-acceptance-"):
      if stage == "checkpoint-before": raise OSError("synthetic-private-value")
      result = write(tree, name, data, *args, **kwargs)
      if stage == "checkpoint-after": raise OSError("synthetic-private-value")
      return result
    return write(tree, name, data, *args, **kwargs)
  def commit(tree, name, data, *args, **kwargs):
    if name == "coordination.json":
      if stage == "coordination-before": raise OSError("synthetic-private-value")
      result = replace(tree, name, data, *args, **kwargs)
      if stage == "coordination-after": raise OSError("synthetic-private-value")
      return result
    return replace(tree, name, data, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", publish); patch.setattr(Tree, "replace", commit)
    with pytest.raises(Conflict) as caught: store.accept_stop_snapshot(case.domain, value)
  assert "synthetic-private-value" not in str(caught.value)
  state = case.domain.snapshot()
  assert (BATCH in state["intents"]) == (stage == "coordination-after")
  assert checkpoint(case).exists() == (stage != "checkpoint-before")
  if stage != "checkpoint-before":
    before = checkpoint(case).read_bytes(), ledger(case.domain)
    with pytest.raises(Conflict): store.accept_stop_snapshot(case.domain, value)
    assert before == (checkpoint(case).read_bytes(), ledger(case.domain))
  if stage in ("checkpoint-after", "coordination-before"):
    with pytest.raises(Conflict): store.read_stop_snapshot(case.domain, BATCH)
  if stage == "coordination-after":
    assert store.read_stop_snapshot(case.domain, BATCH)["intent"]["phase"] == "active"


@pytest.mark.parametrize("damage", ["missing", "mode", "symlink", "hardlink", "contents"])
def test_dispatch_refuses_missing_or_changed_recovery_checkpoint(group, tmp_path, damage):
  case = group(); value = acceptance(case)
  store.accept_stop_snapshot(case.domain, value)
  path = checkpoint(case)
  if damage == "missing": path.unlink()
  elif damage == "mode": path.chmod(0o644)
  elif damage == "symlink":
    replacement = tmp_path / "alternate.json"; path.rename(replacement); path.symlink_to(replacement)
  elif damage == "hardlink": os.link(path, tmp_path / "second-link.json")
  else: path.write_bytes(b"{}\n")
  before = ledger(case.domain)
  with pytest.raises(Conflict): case.domain.dispatch_intent(BATCH)
  with pytest.raises(Conflict): store.read_stop_snapshot(case.domain, BATCH)
  assert ledger(case.domain) == before


def test_conflicting_acceptance_keeps_original_recovery_facts(group):
  case = group(); value = acceptance(case)
  store.accept_stop_snapshot(case.domain, value)
  original = checkpoint(case).read_bytes()
  other = deepcopy(value); other["batch"]["batch_id"] = "9" * 32
  other["expected_revision"] = case.domain.snapshot()["revision"]
  # 即使更新 revision，已有资源意图也必须先阻断。
  with pytest.raises(Conflict): store.accept_stop_snapshot(case.domain, other)
  assert checkpoint(case).read_bytes() == original and not checkpoint(case, "9" * 32).exists()


def test_read_is_historical_independent_and_never_creates_absent_snapshot(group):
  case = group(); value = acceptance(case)
  before = ledger(case.domain)
  assert store.read_stop_snapshot(case.domain, BATCH) is None
  assert ledger(case.domain) == before and not checkpoint(case).exists()
  store.accept_stop_snapshot(case.domain, value)
  saved = store.read_stop_snapshot(case.domain, BATCH)
  saved["acceptance"]["records"][RUNS[0]]["start_cwd"]["path"] = "/synthetic/mutated"
  assert store.read_stop_snapshot(case.domain, BATCH)["acceptance"] == value
  case.domain.mark_intent_unknown(BATCH)
  assert store.read_stop_snapshot(case.domain, BATCH)["intent"]["phase"] == "unknown"
  assert store.read_stop_snapshot(case.domain, BATCH)["acceptance"] == value


def test_setup_snapshot_requires_the_full_shared_reference_set(group):
  case = group(); value = acceptance(case, operation="setup", chosen=RUNS)
  store.accept_stop_snapshot(case.domain, value)
  saved = store.read_stop_snapshot(case.domain, BATCH)
  assert saved["intent"]["operation"] == "setup" and saved["intent"]["selected_runs"] == list(RUNS)
  assert saved["acceptance"]["batch"]["maintenance_dispatch"]["state"] == "not_dispatched"
  assert saved["acceptance"]["batch"]["operation_result"] is None


@pytest.mark.parametrize("failure", [1, 2, 3, 4])
def test_each_fsync_failure_stops_before_any_control_and_keeps_possible_publication(group, monkeypatch, failure):
  case = group(); value = acceptance(case)
  sync = os.fsync; calls = []
  def fail(fd):
    calls.append(stat.S_ISDIR(os.fstat(fd).st_mode))
    if len(calls) == failure: raise OSError("synthetic-private-sync")
    return sync(fd)
  with monkeypatch.context() as patch:
    patch.setattr(os, "fsync", fail)
    with pytest.raises(Conflict) as caught: store.accept_stop_snapshot(case.domain, value)
  assert "synthetic-private-sync" not in str(caught.value)
  # 文件同步失败时，底层仍同步临时名清理；它不会发布恢复清单。
  assert calls == ([False, True] if failure == 1 else [False, True, False, True][:failure])
  assert checkpoint(case).exists() == (failure > 1)
  assert (BATCH in case.domain.snapshot()["intents"]) == (failure == 4)


@pytest.mark.parametrize("control", [KeyboardInterrupt, SystemExit])
def test_control_exception_is_not_converted_or_followed_by_cleanup(group, monkeypatch, control):
  case = group(); value = acceptance(case)
  replace = Tree.replace
  def interrupted(tree, name, data, *args, **kwargs):
    if name == "coordination.json": raise control()
    return replace(tree, name, data, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", interrupted)
    with pytest.raises(control): store.accept_stop_snapshot(case.domain, value)
  assert checkpoint(case).exists() and BATCH not in case.domain.snapshot()["intents"]


@pytest.mark.parametrize("legacy", [False, True])
def test_removing_intent_digest_does_not_downgrade_a_saved_acceptance(group, legacy):
  case = group(); value = acceptance(case)
  store.accept_stop_snapshot(case.domain, value)
  # 正常协调提交已拒绝缺摘要的新进展；这里直接模拟磁盘损坏，并保留旧格式负例。
  state = case.domain.snapshot()
  if legacy:
    state["intents"][BATCH].pop("progress")
  del state["intents"][BATCH]["acceptance_digest"]
  with Tree(case.domain.root) as tree:
    tree.write_state("coordination.json", run_owners._encode(state))
  before = ledger(case.domain)
  with pytest.raises(Conflict): case.domain.dispatch_intent(BATCH)
  assert ledger(case.domain) == before


@pytest.mark.parametrize("change", ["root", "contents"])
def test_publication_rechecks_named_root_and_file_before_registering_intent(group, monkeypatch, change):
  case = group(); value = acceptance(case)
  write = Tree.write_new
  original_root = case.domain.root.with_name("original-domain")
  def changed(tree, name, data, *args, **kwargs):
    result = write(tree, name, data, *args, **kwargs)
    if name.startswith("stop-acceptance-"):
      if change == "root":
        case.domain.root.rename(original_root)
        case.domain.root.mkdir(mode=0o700)
      else:
        checkpoint(case).write_bytes(b"{}\n")
    return result
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", changed)
    with pytest.raises(Conflict): store.accept_stop_snapshot(case.domain, value)
  stored_root = original_root if change == "root" else case.domain.root
  assert BATCH not in json.loads((stored_root / "coordination.json").read_bytes())["intents"]
  assert (stored_root / checkpoint(case).name).exists()


def test_dispatch_rechecks_selected_record_digest_without_mutating_acceptance(group):
  case = group(); value = acceptance(case)
  store.accept_stop_snapshot(case.domain, value)
  original = checkpoint(case).read_bytes()
  with case.domain._transaction(write=True) as state:
    state["reservations"][RUNS[0]]["owner_link"]["record_digest"] = "0" * 64
  before = ledger(case.domain)
  with pytest.raises(Conflict): case.domain.dispatch_intent(BATCH)
  assert ledger(case.domain) == before and checkpoint(case).read_bytes() == original
  # 历史查询仍可展示原始清单；不能把当前记录变化抹进旧批准。
  assert store.read_stop_snapshot(case.domain, BATCH)["acceptance"] == value
