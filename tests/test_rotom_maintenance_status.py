"""OMP 维护状态的只读作用域桥；真实临时记录，保持原结果与未知边界。"""
import json
from types import SimpleNamespace

import pytest

from agentcfg import commands, deployment, maintenance_handoff, maintenance_status as status
from agentcfg import maintenance_observation as observation
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_execution import case, change_evidence, execute
from test_rotom_maintenance_observation import state_bytes
from test_rotom_maintenance_recovery import BATCH
from test_rotom_maintenance_codec import batch as initial_batch
from test_rotom_interaction import Stream
from rotom import cli, preferences
from rotom.context import InputGateway


def query(case, monkeypatch):
  monkeypatch.setattr(commands, "workspace", lambda args: case.workspace)
  return status.status_setup(case.args, BATCH)


def test_success_is_pending_handoff_without_overwriting_original_result(case, monkeypatch):
  result = execute(case)
  before = state_bytes(case)
  actual = query(case, monkeypatch)
  assert actual["readonly"] and actual["kind"] == "setup-maintenance-status"
  assert actual["batch_id"] == BATCH and actual["revision"] == result.batch["revision"]
  assert actual["scope"] == {"agent": "omp", **case.workspace.binding}
  assert actual["phase"] == "maintenance_succeeded" and actual["protected"]
  assert actual["exit_code"] == 4 and actual["operation_result"] == result.batch["operation_result"]
  assert actual["observation"] == {"target_state": "target-matches", "resources_checked": True,
    "pending_journal": False, "reason": None}
  assert actual["continue_status"] == "not_sent" and state_bytes(case) == before
  actual["items"][0]["restore_phase"] = "changed"
  assert query(case, monkeypatch)["items"] == result.batch["items"]


def test_completed_manual_history_is_readable_and_does_not_claim_restored(case, monkeypatch):
  result = execute(case)
  monkeypatch.setattr(commands, "workspace", lambda args: case.workspace)
  completed = maintenance_handoff.complete_setup_manual(case.domain, BATCH,
    expected_revision=result.batch["revision"], args=case.args, approve=lambda view: True)
  before = state_bytes(case)
  actual = query(case, monkeypatch)
  assert actual["intent_phase"] == "completed" and not actual["protected"] and actual["exit_code"] == 0
  assert actual["items"] == completed["items"]
  assert all(row["restore_phase"] == "manual" for row in actual["items"])
  assert actual["operation_result"] == result.batch["operation_result"]
  assert state_bytes(case) == before


@pytest.mark.parametrize("kind", ["undispatched", "unknown", "partial"])
def test_uncertain_or_incomplete_state_remains_readonly_pending(case, monkeypatch, kind):
  if kind == "unknown":
    def fail(): raise RuntimeError("synthetic")
    case.sync_hook = fail
    with pytest.raises(RuntimeError): execute(case)
  elif kind == "partial":
    case.sync_hook = lambda: change_evidence(case, "source")
    assert execute(case).operation.code == 4
  before = state_bytes(case)
  actual = query(case, monkeypatch)
  assert actual["exit_code"] == 4 and actual["protected"]
  assert actual["phase"] == {"undispatched": "maintenance_dispatch_intent", "unknown": "unknown", "partial": "partial"}[kind]
  assert state_bytes(case) == before


@pytest.mark.parametrize("code", [2, 3, 5, 6])
def test_saved_explicit_failure_code_is_preserved(case, monkeypatch, code):
  execute(case)
  with case.domain._transaction(write=True) as state:
    intent = state["intents"][BATCH]
    intent["phase"] = "unknown"
    batch = intent["progress"]
    batch.update(phase="partial", review_required=True)
    batch["operation_result"].update(status="partial", exit_code=code)
  before = state_bytes(case)
  actual = query(case, monkeypatch)
  assert actual["exit_code"] == code and actual["operation_result"]["exit_code"] == code
  assert actual["observation"]["target_state"] == "target-matches"
  assert actual["phase"] == "partial" and actual["protected"]
  assert state_bytes(case) == before


@pytest.mark.parametrize("change", ["pending", "projection", "target", "owner"])
def test_live_issues_do_not_replace_saved_success_or_clear_protection(case, monkeypatch, change):
  result = execute(case)
  if change == "pending": (case.workspace.state_root / "pending.json").write_bytes(b"synthetic\n")
  elif change == "projection": (case.workspace.instance / "managed.txt").write_bytes(b"changed\n")
  elif change == "owner": change_evidence(case, "owner")
  else:
    with Tree(case.workspace.state_root) as tree:
      saved = deployment.read_state(tree)
      saved["current"]["generation"] = "f" * 64
      tree.write_state("deployment.json", deployment.json_bytes(saved))
  before = state_bytes(case)
  actual = query(case, monkeypatch)
  assert actual["exit_code"] == 4 and actual["operation_result"] == result.batch["operation_result"]
  assert actual["observation"]["target_state"] == {
    "pending": "journal-pending", "target": "target-differs", "projection": "unconfirmed", "owner": "unconfirmed"}[change]
  assert state_bytes(case) == before


@pytest.mark.parametrize("change", ["profile", "local", "agent", "batch-scope"])
def test_explicit_scope_mismatch_fails_without_output_or_observation(case, monkeypatch, capsys, change):
  if change == "profile": case.args.profile = None
  elif change == "local": case.args.local = None
  elif change == "agent": case.workspace.agent = "pi"
  else: case.workspace.binding = {**case.workspace.binding, "machine": "another-machine"}
  def forbidden(*args, **kwargs): pytest.fail("mismatched scope must not reach observation")
  monkeypatch.setattr(observation, "observe_setup", forbidden)
  before = state_bytes(case)
  with pytest.raises(Conflict): query(case, monkeypatch)
  assert state_bytes(case) == before and capsys.readouterr() == ("", "")


def test_readonly_query_never_prepares_or_writes(case, monkeypatch):
  execute(case)
  before = state_bytes(case)
  def forbidden(*args, **kwargs): pytest.fail("query attempted a write or preparation")
  with monkeypatch.context() as patch:
    for name in ("prepared", "current_plan", "sync_backend", "apply_candidate"):
      patch.setattr(commands, name, forbidden)
    for name in ("write_state", "replace", "write_new", "write_immutable"):
      patch.setattr(Tree, name, forbidden)
    patch.setattr(deployment, "recover", forbidden)
    assert query(case, patch)["observation"]["target_state"] == "target-matches"
  assert state_bytes(case) == before


def test_config_error_is_preserved(case, monkeypatch):
  failure = ValueError("synthetic-private-canary")
  def fail(args): raise failure
  monkeypatch.setattr(commands, "workspace", fail)
  with pytest.raises(ValueError) as caught: status.status_setup(case.args, BATCH)
  assert caught.value is failure


def test_concurrent_batch_change_is_not_reported_as_fresh_success(case, monkeypatch):
  execute(case)
  original = observation.observe_setup
  captured = []
  def observe(*args, **kwargs):
    change_evidence(case, "cas")
    captured.append(state_bytes(case))
    return original(*args, **kwargs)
  monkeypatch.setattr(observation, "observe_setup", observe)
  with pytest.raises(Conflict): query(case, monkeypatch)
  assert len(captured) == 1 and state_bytes(case) == captured[0]


@pytest.mark.parametrize("target,checked,pending,reason,code", [
  ("target-unavailable", False, None, "no-saved-target", 0),
  ("unconfirmed", False, None, "live-state-unconfirmed", 4),
  ("journal-pending", True, True, None, 4),
  ("target-matches", True, False, None, 4),
])
def test_initial_cancelled_query_only_confirms_cancellation(target, checked, pending, reason, code):
  from agentcfg.maintenance import decode_batch, encode_batch
  batch = decode_batch(encode_batch(initial_batch(operation="setup")))
  observed = observation.SetupObservation(batch, target, checked, pending, reason)
  assert status._exit_code(batch, {"phase": "cancelled"}, observed) == code


@pytest.mark.parametrize("completed", [False, True])
def test_cli_reads_real_batch_and_target_without_mutating_or_claiming_restore(case, monkeypatch, capsys, completed):
  result = execute(case)
  monkeypatch.setattr(commands, "workspace", lambda args: case.workspace)
  if completed:
    maintenance_handoff.complete_setup_manual(case.domain, BATCH,
      expected_revision=result.batch["revision"], args=case.args, approve=lambda view: True)
  streams = InputGateway(Stream(tty=False), Stream(tty=False), Stream(tty=False))
  monkeypatch.setattr(cli, "InputGateway", lambda: streams)
  monkeypatch.setattr(preferences, "load_preferences", lambda: SimpleNamespace(get=lambda key: None))
  monkeypatch.setattr(cli, "_profile_tool", lambda profile: "omp")
  before = state_bytes(case)
  def forbidden(*args, **kwargs): pytest.fail("status CLI attempted mutation or preparation")
  for name in ("prepared", "current_plan", "sync_backend", "apply_candidate"):
    monkeypatch.setattr(commands, name, forbidden)
  for name in ("write_state", "replace", "write_new", "write_immutable"):
    monkeypatch.setattr(Tree, name, forbidden)
  monkeypatch.setattr(deployment, "recover", forbidden)
  code = cli.main(["--no-input", "agent", "--local", str(case.args.local), "--profile", case.workspace.profile,
    "maintenance", "status", "--batch", BATCH, "--format", "json"])
  actual = json.loads(capsys.readouterr().out)
  assert code == actual["exit_code"] == (0 if completed else 4)
  assert actual["readonly"] and actual["protected"] is not completed
  assert actual["operation_result"] == result.batch["operation_result"]
  assert actual["observation"]["target_state"] == "target-matches"
  assert actual["continue_status"] == "not_sent"
  assert all(row["restore_phase"] != "restored" for row in actual["items"])
  assert set(actual["next_commands"]) == {"status"}
  assert streams.stdin.reads == 0 and state_bytes(case) == before
