"""只读维护现场观察：真实临时锁与记录，禁止恢复、写入和宿主调用。"""
from contextlib import ExitStack
from copy import deepcopy
import fcntl

import pytest

from agentcfg import commands, deployment, maintenance_observation as observation, maintenance_progress as progress
from agentcfg import runtime
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_execution import case, change_evidence, execute, probe
from test_rotom_maintenance_recovery import BATCH, RUNS, OPS, ledger


def observe(case, monkeypatch, **kwargs):
  monkeypatch.setattr(commands, "workspace", lambda args: case.workspace)
  revision = progress.read_batch(case.domain, BATCH)["revision"]
  return observation.observe_setup(case.domain, BATCH, expected_revision=revision, args=case.args, **kwargs)


def state_bytes(case):
  ws = case.workspace
  roots = (case.domain.root, ws.state_root, ws.instance, ws.cache)
  return {str(path): path.read_bytes() for root in roots for path in root.rglob("*") if path.is_file()}


def forbidden(*args, **kwargs):
  pytest.fail("observation attempted a write, preparation, recovery or execution")


def test_successful_target_is_observed_without_any_write_or_recovery(case, monkeypatch):
  result = execute(case)
  before = state_bytes(case)
  events = list(case.events)
  with monkeypatch.context() as patch:
    for name in ("write_state", "replace"):
      patch.setattr(Tree, name, forbidden)
    for name in ("prepared", "current_plan", "sync_backend", "apply_candidate"):
      patch.setattr(commands, name, forbidden)
    patch.setattr(deployment, "recover", forbidden)
    actual = observe(case, patch)
  assert actual.batch == result.batch
  assert actual.target_state == "target-matches" and actual.resources_checked
  assert actual.pending_journal is False and actual.reason is None
  assert state_bytes(case) == before and case.events == events
  actual.batch["revision"] += 1
  assert progress.read_batch(case.domain, BATCH) == result.batch
  ws = case.workspace
  for path in (ws.instance / ".agentcfg-omp.lock", ws.state_root / "instance.lock",
      ws.cache / "leases" / (case.identity + ".lock")):
    probe(path, fcntl.LOCK_EX, blocked=False)
  for root in (case.domain.root, ws.state_root / "run-owners"):
    with Tree(root) as tree:
      fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_no_saved_target_does_not_guess_or_open_physical_paths(case, monkeypatch):
  before = state_bytes(case)
  with monkeypatch.context() as patch:
    patch.setattr(observation.maintenance_release, "_leases", forbidden)
    patch.setattr(deployment, "read_state", forbidden)
    actual = observe(case, patch)
  assert actual.target_state == "target-unavailable" and not actual.resources_checked
  assert actual.pending_journal is None and actual.reason == "no-saved-target"
  assert "target_deployment_digest" not in actual.batch["maintenance_dispatch"]
  assert state_bytes(case) == before and case.events == []


@pytest.mark.parametrize("kind", ["unknown", "partial", "running-with-applied-target"])
def test_observation_never_promotes_historical_result_or_clears_intent(case, monkeypatch, kind):
  if kind == "unknown":
    def fail(): raise RuntimeError("synthetic-private-canary")
    case.sync_hook = fail
    with pytest.raises(RuntimeError): execute(case)
    phase, target = "unknown", "target-differs"
  elif kind == "partial":
    case.sync_hook = lambda: change_evidence(case, "source")
    assert execute(case).operation.code == 4
    phase, target = "partial", "target-differs"
  else:
    original = Tree.replace
    writes = []
    def fail_completion(tree, name, data, *args, **kwargs):
      if name == "coordination.json":
        writes.append(True)
        if len(writes) == 2: raise OSError("synthetic-private-canary")
      return original(tree, name, data, *args, **kwargs)
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "replace", fail_completion)
      with pytest.raises(Conflict): execute(case)
    assert len(writes) == 2
    phase, target = "maintenance_running", "target-matches"
  before = state_bytes(case)
  events = list(case.events)
  actual = observe(case, monkeypatch)
  assert actual.batch["phase"] == phase and actual.target_state == target
  assert actual.resources_checked and actual.pending_journal is False
  assert state_bytes(case) == before and case.events == events


def test_pending_journal_is_only_reported_not_parsed_or_recovered(case, monkeypatch):
  execute(case)
  path = case.workspace.state_root / "pending.json"
  path.write_bytes(b"synthetic incomplete private journal\n")
  before = state_bytes(case)
  with monkeypatch.context() as patch:
    patch.setattr(deployment, "read_state", forbidden)
    patch.setattr(deployment, "recover", forbidden)
    actual = observe(case, patch)
  assert actual.target_state == "journal-pending" and actual.pending_journal is True
  assert actual.resources_checked and state_bytes(case) == before


@pytest.mark.parametrize("change", ["manifest", "projection", "missing-manifest"])
def test_changed_current_state_is_not_a_matching_target(case, monkeypatch, change):
  execute(case)
  if change == "projection":
    (case.workspace.instance / "managed.txt").write_bytes(b"changed\n")
  elif change == "missing-manifest":
    (case.workspace.state_root / "deployment.json").unlink()
  else:
    with Tree(case.workspace.state_root) as tree:
      saved = deployment.read_state(tree)
      saved["current"]["generation"] = "f" * 64
      tree.write_state("deployment.json", deployment.json_bytes(saved))
  before = state_bytes(case)
  actual = observe(case, monkeypatch)
  assert actual.target_state == ("unconfirmed" if change == "projection" else "target-differs")
  assert state_bytes(case) == before


@pytest.mark.parametrize("lock", ["instance", "state", "package", "owner"])
def test_busy_original_locks_leave_observation_unconfirmed(case, monkeypatch, lock):
  execute(case)
  ws = case.workspace
  with ExitStack() as stack:
    if lock == "owner":
      tree = stack.enter_context(Tree(ws.state_root / "run-owners"))
      fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
      root, name = {"instance": (ws.instance, ".agentcfg-omp.lock"),
        "state": (ws.state_root, "instance.lock"),
        "package": (ws.cache, "leases/" + case.identity + ".lock")}[lock]
      stack.enter_context(_shared_file(root, name))
    before = state_bytes(case)
    actual = observe(case, monkeypatch)
    assert actual.target_state == "unconfirmed" and not actual.resources_checked
    assert actual.pending_journal is None and actual.reason == "live-state-unconfirmed"
    assert state_bytes(case) == before


@pytest.mark.parametrize("change", ["owner", "unknown", "intent", "resources", "shared-unknown"])
def test_unknown_or_uncovered_shared_users_block_observation(case, monkeypatch, change):
  execute(case)
  if change == "shared-unknown":
    with case.domain._transaction(write=True) as state:
      other = deepcopy(state["reservations"][RUNS[0]])
      other.update(run_id=RUNS[2], op_id=OPS[2], phase="unknown", resources=[case.runtime["resource_id"]])
      other.pop("owner_link", None)
      other.pop("release_receipt", None)
      state["reservations"][RUNS[2]] = other
  else:
    change_evidence(case, change)
  before = state_bytes(case)
  actual = observe(case, monkeypatch)
  assert actual.target_state == "unconfirmed" and not actual.resources_checked
  assert state_bytes(case) == before


@pytest.mark.parametrize("change", ["cas", "owner", "resources", "instance-lock", "state-lock", "package-lock"])
def test_second_check_rejects_changes_during_content_read(case, monkeypatch, change):
  execute(case)
  original = deployment.read_state
  snapshots = []
  def read(tree):
    result = original(tree)
    if change.endswith("-lock"):
      ws = case.workspace
      root, name = {"instance-lock": (ws.instance, ".agentcfg-omp.lock"),
        "state-lock": (ws.state_root, "instance.lock"),
        "package-lock": (ws.cache, "leases/" + case.identity + ".lock")}[change]
      with Tree(root) as changed:
        changed.replace(name, b"", 0o600, expected=changed.read(name)[2])
    else:
      change_evidence(case, change)
    snapshots.append(state_bytes(case))
    return result
  monkeypatch.setattr(deployment, "read_state", read)
  actual = observe(case, monkeypatch)
  assert actual.target_state == "unconfirmed" and not actual.resources_checked
  assert len(snapshots) == 1 and state_bytes(case) == snapshots[0]


@pytest.mark.parametrize("invalid", [True, None, -1, "0", 1000])
def test_revision_is_strict_and_stale_revision_rejected(case, monkeypatch, invalid):
  before = ledger(case.domain)
  monkeypatch.setattr(commands, "workspace", forbidden)
  with pytest.raises(Conflict):
    observation.observe_setup(case.domain, BATCH, expected_revision=invalid, args=case.args)
  assert ledger(case.domain) == before


@pytest.mark.parametrize("field", ["local", "profile", "agent", "binding", "platform"])
def test_only_explicit_matching_original_scope_is_allowed(case, monkeypatch, field):
  before = state_bytes(case)
  if field == "local": case.args.local = None
  elif field == "profile": case.args.profile = "another-profile"
  elif field == "platform": monkeypatch.setattr(observation.sys, "platform", "darwin")
  elif field == "agent": case.workspace.agent = "pi"
  else: case.workspace.binding = {**case.workspace.binding, "machine": "another-machine"}
  with pytest.raises(Conflict): observe(case, monkeypatch)
  assert state_bytes(case) == before


def test_original_workspace_errors_are_preserved(case, monkeypatch):
  failure = ValueError("synthetic-private-canary")
  def fail(args): raise failure
  monkeypatch.setattr(commands, "workspace", fail)
  before = ledger(case.domain)
  with pytest.raises(ValueError) as caught:
    observation.observe_setup(case.domain, BATCH,
      expected_revision=case.dispatch.batch["revision"], args=case.args)
  assert caught.value is failure and ledger(case.domain) == before


@pytest.mark.parametrize("interrupt", [False, True])
def test_live_failures_are_private_safe_and_interrupts_preserved(case, monkeypatch, capsys, interrupt):
  execute(case)
  before = state_bytes(case)
  failure = KeyboardInterrupt() if interrupt else ValueError("synthetic-private-canary")
  def fail(*args): raise failure
  monkeypatch.setattr(runtime, "check_deployed_resources", fail)
  if interrupt:
    with pytest.raises(KeyboardInterrupt) as caught: observe(case, monkeypatch)
    assert caught.value is failure
  else:
    actual = observe(case, monkeypatch)
    assert actual.target_state == "unconfirmed" and actual.reason == "live-state-unconfirmed"
    assert "synthetic-private-canary" not in repr(actual)
  assert capsys.readouterr() == ("", "") and state_bytes(case) == before
