"""成功维护明确交接人工恢复：原物理门禁、完整现场复核与单次元数据收尾。"""
from contextlib import ExitStack
from copy import deepcopy
import fcntl
import json

import pytest

from agentcfg import commands, deployment, maintenance_handoff as handoff, maintenance_progress as progress
from agentcfg import runtime
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_execution import case, change_evidence, execute, probe
from test_rotom_maintenance_observation import state_bytes
from test_rotom_maintenance_recovery import BATCH, RUNS, OPS, ledger


def complete(case, monkeypatch, approve=lambda view: True, *, revision=None):
  monkeypatch.setattr(commands, "workspace", lambda args: case.workspace)
  if revision is None: revision = progress.read_batch(case.domain, BATCH)["revision"]
  return handoff.complete_setup_manual(case.domain, BATCH, expected_revision=revision,
    args=case.args, approve=approve)


def assert_no_locks(case):
  ws = case.workspace
  for path in (ws.instance / ".agentcfg-omp.lock", ws.state_root / "instance.lock",
      ws.cache / "leases" / (case.identity + ".lock")):
    probe(path, fcntl.LOCK_EX, blocked=False)
  for root in (case.domain.root, ws.state_root / "run-owners"):
    with Tree(root) as tree: fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_successful_manual_handoff_retains_history_and_allows_new_reservation(case, monkeypatch):
  result = execute(case)
  before = case.domain.snapshot()
  files = state_bytes(case)
  resources = set(before["intents"][BATCH]["resources"])
  with pytest.raises(Conflict): case.domain._idle(before, resources)
  views = []
  def approve(view):
    assert_no_locks(case)
    views.append(deepcopy(view))
    view["batch"]["operation_result"]["exit_code"] = 99
    return True
  actual = complete(case, monkeypatch, approve)
  after = case.domain.snapshot()
  expected = deepcopy(result.batch)
  expected["revision"] += 1
  for item in expected["items"]: item["restore_phase"] = "manual"
  assert actual == expected and views[0]["batch"] == result.batch
  assert views[0]["action"] == "complete-setup-manual"
  assert after["intents"][BATCH]["phase"] == "completed"
  assert after["intents"][BATCH]["generation"] == before["intents"][BATCH]["generation"]
  assert after["reservations"] == before["reservations"]
  assert after["resources"] == before["resources"]
  assert {p: b for p, b in state_bytes(case).items() if not p.endswith("/coordination.json")} == {
    p: b for p, b in files.items() if not p.endswith("/coordination.json")}
  case.domain._idle(after, resources)
  case.domain.reserve(run_id=RUNS[2], op_id=OPS[2], resources=sorted(resources),
    owner_ref={"state_root": str(case.workspace.state_root), "binding": case.workspace.binding})
  assert_no_locks(case)
  frozen = ledger(case.domain)
  with pytest.raises(Conflict): complete(case, monkeypatch)
  with pytest.raises(Conflict): case.domain.cancel_intent(BATCH)
  with pytest.raises(Conflict): case.domain.mark_intent_unknown(BATCH)
  assert ledger(case.domain) == frozen


@pytest.mark.parametrize("answer", [False, None, 1, "yes"])
def test_only_exact_approval_can_finish_known_success(case, monkeypatch, answer):
  execute(case)
  before = state_bytes(case)
  calls = []
  with pytest.raises(Conflict): complete(case, monkeypatch, lambda view: calls.append(view) or answer)
  assert len(calls) == 1 and state_bytes(case) == before


@pytest.mark.parametrize("interrupt", [False, True])
def test_approval_exception_is_preserved_and_writes_nothing(case, monkeypatch, interrupt):
  execute(case)
  before = state_bytes(case)
  failure = KeyboardInterrupt() if interrupt else ValueError("synthetic-private-canary")
  def approve(view):
    assert_no_locks(case)
    raise failure
  with pytest.raises(type(failure)) as caught: complete(case, monkeypatch, approve)
  assert caught.value is failure and state_bytes(case) == before


@pytest.mark.parametrize("kind", ["not-dispatched", "unknown", "partial", "running-with-target"])
def test_incomplete_or_unknown_execution_never_offers_handoff(case, monkeypatch, kind):
  if kind == "unknown":
    def fail(): raise RuntimeError("synthetic")
    case.sync_hook = fail
    with pytest.raises(RuntimeError): execute(case)
  elif kind == "partial":
    case.sync_hook = lambda: change_evidence(case, "source")
    assert execute(case).operation.code == 4
  elif kind == "running-with-target":
    original, writes = Tree.replace, []
    def fail(tree, name, data, *args, **kwargs):
      if name == "coordination.json":
        writes.append(True)
        if len(writes) == 2: raise OSError("synthetic")
      return original(tree, name, data, *args, **kwargs)
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "replace", fail)
      with pytest.raises(Conflict): execute(case)
    assert (case.workspace.instance / "managed.txt").read_bytes() == b"new\n"
  before = state_bytes(case)
  def approve(view): pytest.fail("uncertain execution must not offer completion")
  with pytest.raises(Conflict): complete(case, monkeypatch, approve)
  assert state_bytes(case) == before


@pytest.mark.parametrize("change", ["cas", "owner", "resources", "unknown", "intent", "projection", "pending", "target", "local"])
def test_changes_during_approval_cannot_clear_protection(case, monkeypatch, change):
  execute(case)
  snapshots = []
  def approve(view):
    if change == "projection":
      (case.workspace.instance / "managed.txt").write_bytes(b"changed\n")
    elif change == "pending":
      (case.workspace.state_root / "pending.json").write_bytes(b"synthetic\n")
    elif change == "target":
      with Tree(case.workspace.state_root) as tree:
        saved = deployment.read_state(tree)
        saved["current"]["generation"] = "f" * 64
        tree.write_state("deployment.json", deployment.json_bytes(saved))
    elif change == "local":
      case.workspace.binding = {**case.workspace.binding, "local": "/example/changed.toml"}
    else: change_evidence(case, change)
    snapshots.append(state_bytes(case))
    return True
  with pytest.raises(Conflict): complete(case, monkeypatch, approve)
  assert len(snapshots) == 1 and state_bytes(case) == snapshots[0]


@pytest.mark.parametrize("change", ["instance", "state", "package", "owner"])
def test_busy_physical_or_owner_lock_refuses_before_approval(case, monkeypatch, change):
  execute(case)
  ws = case.workspace
  with ExitStack() as stack:
    if change == "owner":
      tree = stack.enter_context(Tree(ws.state_root / "run-owners"))
      fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
      root, name = {"instance": (ws.instance, ".agentcfg-omp.lock"),
        "state": (ws.state_root, "instance.lock"),
        "package": (ws.cache, "leases/" + case.identity + ".lock")}[change]
      stack.enter_context(_shared_file(root, name))
    before = state_bytes(case)
    def approve(view): pytest.fail("busy resources must not offer completion")
    with pytest.raises(Conflict): complete(case, monkeypatch, approve)
    assert state_bytes(case) == before


@pytest.mark.parametrize("after", [False, True])
def test_completion_commit_failure_keeps_possible_facts_without_retry(case, monkeypatch, after):
  result = execute(case)
  original, writes = Tree.replace, []
  before = case.domain.snapshot()
  def commit(tree, name, data, *args, **kwargs):
    if name != "coordination.json": return original(tree, name, data, *args, **kwargs)
    writes.append(json.loads(data))
    ws = case.workspace
    for path in (ws.instance / ".agentcfg-omp.lock", ws.state_root / "instance.lock",
        ws.cache / "leases" / (case.identity + ".lock")):
      probe(path, fcntl.LOCK_SH, blocked=True)
    with Tree(ws.state_root / "run-owners") as owners:
      with pytest.raises(BlockingIOError): fcntl.flock(owners.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if after: original(tree, name, data, *args, **kwargs)
    raise OSError("synthetic-private-canary")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", commit)
    with pytest.raises(Conflict): complete(case, patch)
  saved = case.domain.snapshot()
  assert len(writes) == 1
  assert saved["intents"][BATCH]["phase"] == ("completed" if after else before["intents"][BATCH]["phase"])
  assert saved["reservations"] == before["reservations"]
  assert saved["intents"][BATCH]["progress"]["operation_result"] == result.batch["operation_result"]
  assert_no_locks(case)


def test_handoff_never_runs_setup_recovery_or_resume(case, monkeypatch):
  execute(case)
  def forbidden(*args, **kwargs): pytest.fail("completion attempted host or deployment action")
  with monkeypatch.context() as patch:
    for name in ("prepared", "current_plan", "sync_backend", "apply_candidate"):
      patch.setattr(commands, name, forbidden)
    patch.setattr(deployment, "recover", forbidden)
    patch.setattr(runtime, "record", forbidden)
    actual = complete(case, patch)
  assert actual["phase"] == "maintenance_succeeded"
  assert all(item["restore_phase"] == "manual" and item["launch_dispatch"]["state"] == "not_dispatched"
    for item in actual["items"])
