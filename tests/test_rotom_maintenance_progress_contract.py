"""维护进展与原接受清单的持久关联；只使用临时文件和虚构进程。"""
from copy import deepcopy
import json

import pytest

from agentcfg import maintenance, maintenance_store as store
from agentcfg.resource_protocol import decode, encode
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance import acceptance, group
from test_rotom_maintenance_recovery import BATCH, RUNS, ledger


def accepted(case):
  value = acceptance(case)
  store.accept_stop_snapshot(case.domain, value)
  return value


def test_progress_and_intent_are_published_in_the_same_atomic_commit(group, monkeypatch):
  case = group(); value = acceptance(case)
  replace, committed = Tree.replace, []
  def capture(tree, name, raw, *args, **kwargs):
    if name == "coordination.json":
      intent = json.loads(raw)["intents"][BATCH]
      committed.append(deepcopy(intent))
      assert intent["progress"] == value["batch"]
      saved = maintenance.decode_stop_acceptance((tree.root / ("stop-acceptance-" + BATCH + ".json")).read_bytes())
      assert saved == value
    return replace(tree, name, raw, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", capture)
  store.accept_stop_snapshot(case.domain, value)
  assert len(committed) == 1
  assert store.read_stop_snapshot(case.domain, BATCH)["intent"]["progress"] == value["batch"]


@pytest.mark.parametrize("damage", ["unknown-field", "bool-revision", "batch-id", "operation", "selection", "missing-acceptance", "unknown-without-protection"])
def test_progress_cannot_expand_or_detach_from_original_intent(group, damage):
  case = group(); accepted(case)
  state = case.domain.snapshot(); intent = state["intents"][BATCH]; progress = intent["progress"]
  if damage == "unknown-field": progress["untrusted"] = True
  elif damage == "bool-revision": progress["revision"] = True
  elif damage == "batch-id": progress["batch_id"] = "f" * 32
  elif damage == "operation": intent["operation"] = "setup"
  elif damage == "selection": intent["selected_runs"] = [RUNS[0]]
  elif damage == "missing-acceptance": intent.pop("acceptance_digest")
  else: progress.update(phase="unknown", review_required=True)
  with pytest.raises(Conflict): encode(state)


@pytest.mark.parametrize("operation", ["read", "cancel", "unknown", "dispatch"])
def test_valid_but_changed_plan_cannot_replace_saved_acceptance(group, operation):
  case = group(); accepted(case)
  state = case.domain.snapshot(); progress = state["intents"][BATCH]["progress"]
  progress["plan"]["runs"][0]["restore"]["capability"] = "unavailable"
  progress["plan"] = maintenance._plan(progress["plan"], verify=False)
  with Tree(case.domain.root) as tree:
    tree.write_state("coordination.json", encode(state))
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    if operation == "read": store.read_stop_snapshot(case.domain, BATCH)
    elif operation == "cancel": case.domain.cancel_intent(BATCH)
    elif operation == "unknown": case.domain.mark_intent_unknown(BATCH)
    else: case.domain.dispatch_intent(BATCH)
  assert ledger(case.domain) == before


def requested(case):
  with case.domain._transaction(write=True) as state:
    batch = state["intents"][BATCH]["progress"]
    batch.update(revision=1, phase="stop_requested")
    batch["items"][0]["facts"]["stop_requested"] = True
    batch["items"][0]["stop_phase"] = "stop_requested"


def test_legacy_cancel_cannot_clear_batch_with_requested_stop(group):
  case = group(); accepted(case); requested(case)
  before = ledger(case.domain)
  with pytest.raises(Conflict): case.domain.cancel_intent(BATCH)
  assert ledger(case.domain) == before


def test_legacy_unknown_preserves_facts_and_advances_batch_revision(group):
  case = group(); accepted(case); requested(case)
  before = deepcopy(case.domain.snapshot()["intents"][BATCH]["progress"])
  case.domain.mark_intent_unknown(BATCH)
  intent = store.read_stop_snapshot(case.domain, BATCH)["intent"]
  assert intent["phase"] == "unknown"
  assert intent["progress"] == {**before, "revision": 2, "phase": "unknown", "review_required": True}
  with pytest.raises(Conflict): case.domain.cancel_intent(BATCH)


def test_old_snapshot_without_progress_remains_readable(group):
  case = group(); value = accepted(case)
  with case.domain._transaction(write=True) as state:
    state["intents"][BATCH].pop("progress")
  result = store.read_stop_snapshot(case.domain, BATCH)
  assert result["acceptance"] == value and "progress" not in result["intent"]
  assert decode(encode(case.domain.snapshot()), kind="domain") == case.domain.snapshot()
