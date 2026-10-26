"""目标部署摘要只绑定已批准目标；真实临时门禁核验落盘结果，不执行宿主。"""
import builtins
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from agentcfg import commands, deployment, maintenance, maintenance_progress as progress, runtime, setup_preview
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_codec import PHASES, batch
from test_rotom_maintenance_execution import case, execute, assert_body_locks, change_evidence
from test_rotom_maintenance_recovery import BATCH, ledger


def target_digest(current):
  return setup_preview.setup_deployment_digest(current)


def test_deployment_digest_covers_full_current_canonically_without_io(monkeypatch, capsys):
  current = {"generation": "synthetic", "binding": {"profile": "example"},
    "launch": {"unknown": {"synthetic-private-canary": [1, True, None, 1.5]}}, "items": {}}
  expected = hashlib.sha256(deployment.json_bytes({"version": 1, "current": current})).hexdigest()
  def forbidden(*args, **kwargs): pytest.fail("unexpected filesystem or runtime access")
  with monkeypatch.context() as patch:
    patch.setattr(builtins, "open", forbidden)
    for name in ("open", "read_bytes", "read_text", "stat", "resolve"):
      patch.setattr(Path, name, forbidden)
    patch.setattr(runtime, "record", forbidden)
    assert target_digest(current) == expected
    assert target_digest(dict(reversed(list(current.items())))) == expected
    for field in current:
      changed = deepcopy(current)
      changed[field] = {"different": True}
      assert target_digest(changed) != expected
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("invalid", [None, [], True, {1: "synthetic-private-canary"},
  {"private": object()}, {"private": (1,)}, {"private": float("nan")}, {"private": float("inf")}])
def test_deployment_digest_invalid_input_has_fixed_private_safe_error(invalid):
  with pytest.raises(Conflict) as caught: target_digest(invalid)
  assert str(caught.value) == "setup 目标部署无法生成摘要；请重新运行 setup。"
  assert caught.value.__suppress_context__


def test_same_public_summary_does_not_identify_same_deployment(case):
  first = commands.current_plan(case.workspace, case.lock, case.proposed)
  second = deepcopy(first)
  second.current["launch"]["lock_identity"] = "f" * 64
  assert first.public() == second.public()
  assert target_digest(first.current) != target_digest(second.current)


def test_running_target_is_durable_before_body_and_equals_final_contract(case):
  expected = target_digest(commands.current_plan(case.workspace, case.lock, case.proposed).current)
  seen = []
  def observe():
    assert_body_locks(case, stage="sync")
    saved = progress.read_batch(case.domain, BATCH)
    assert saved["phase"] == "maintenance_running"
    seen.append(saved["maintenance_dispatch"]["target_deployment_digest"])
  case.sync_hook = observe
  result = execute(case)
  assert seen == [expected] and result.operation.code == 0
  assert result.batch["maintenance_dispatch"]["target_deployment_digest"] == expected
  with Tree(case.workspace.state_root) as state:
    assert target_digest(deployment.read_state(state)["current"]) == expected


def test_running_commit_response_loss_keeps_possible_target_without_body_or_retry(case, monkeypatch):
  expected = target_digest(commands.current_plan(case.workspace, case.lock, case.proposed).current)
  original, writes = Tree.replace, []
  def commit(tree, name, data, *args, **kwargs):
    value = original(tree, name, data, *args, **kwargs)
    if name == "coordination.json":
      writes.append(json.loads(data))
      raise OSError("synthetic-response-loss")
    return value
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", commit)
    with pytest.raises(Conflict): execute(case)
  saved = progress.read_batch(case.domain, BATCH)
  assert saved["phase"] == "maintenance_running"
  assert saved["maintenance_dispatch"]["target_deployment_digest"] == expected
  assert len(writes) == 1 and case.events == [] and case.dispatch.permit._used
  before = ledger(case.domain)
  with pytest.raises(Conflict): execute(case)
  assert ledger(case.domain) == before and case.events == []


@pytest.mark.parametrize("change", ["projection", "manifest", "state-lock", "pending"])
def test_post_apply_live_change_cannot_be_saved_as_success(case, monkeypatch, change):
  original = deployment.transact
  changed = []
  def transact(target, state, *args, **kwargs):
    original(target, state, *args, **kwargs)
    assert_body_locks(case, stage="apply")
    if change == "projection":
      target.replace("managed.txt", b"changed\n", 0o600, expected=target.read("managed.txt")[2])
    elif change == "manifest":
      saved = deployment.read_state(state)
      saved["current"]["generation"] = "f" * 64
      state.write_state("deployment.json", deployment.json_bytes(saved))
    elif change == "state-lock":
      state.replace("instance.lock", b"", 0o600, expected=state.read("instance.lock")[2])
    else:
      state.write_state("pending.json", b"{}\n")
    changed.append(True)
  monkeypatch.setattr(deployment, "transact", transact)
  before = case.domain.snapshot()
  with pytest.raises(Conflict): execute(case)
  saved = progress.read_batch(case.domain, BATCH)
  assert changed == [True] and saved["phase"] == "unknown"
  assert saved["operation_result"]["status"] == "unknown"
  assert case.domain.snapshot()["intents"][BATCH]["phase"] == "unknown"
  assert case.domain.snapshot()["reservations"] == before["reservations"]
  assert case.dispatch.permit._used and case.events == ["sync-body", "apply-body", "apply-body"]


@pytest.mark.parametrize("boundary", ["before-content", "after-content"])
@pytest.mark.parametrize("change", ["instance-lock", "package-lock", "native-home", "owner", "resources"])
def test_post_apply_release_checks_reject_replaced_identity_or_metadata(case, monkeypatch, boundary, change):
  original_transact, original_check = deployment.transact, runtime.check_deployed_resources
  ready, changed = [], []
  def mutate():
    assert_body_locks(case, stage="apply")
    if change in ("instance-lock", "package-lock"):
      root, name = ((case.workspace.instance, ".agentcfg-omp.lock") if change == "instance-lock"
        else (case.workspace.cache, "leases/" + case.identity + ".lock"))
      with Tree(root) as tree:
        raw = tree.read(name)
        tree.replace(name, raw[0], raw[1], expected=raw[2])
    elif change == "native-home":
      home = case.workspace.instance / "user-home"
      retained = case.workspace.instance / "retained-home"
      home.rename(retained)
      shutil.copytree(retained, home)
    else:
      change_evidence(case, change)
    changed.append(True)
  def transact(*args, **kwargs):
    original_transact(*args, **kwargs)
    ready.append(True)
    if boundary == "before-content": mutate()
  def check(*args, **kwargs):
    original_check(*args, **kwargs)
    if ready and not changed and boundary == "after-content": mutate()
  monkeypatch.setattr(deployment, "transact", transact)
  monkeypatch.setattr(runtime, "check_deployed_resources", check)
  reservations = case.domain.snapshot()["reservations"]
  with pytest.raises(Conflict): execute(case)
  saved = progress.read_batch(case.domain, BATCH)
  assert changed == [True] and saved["phase"] == "unknown"
  assert saved["operation_result"]["status"] == "unknown"
  assert case.domain.snapshot()["intents"][BATCH]["phase"] == "unknown"
  assert case.domain.snapshot()["reservations"] == reservations
  assert case.dispatch.permit._used and case.events == ["sync-body", "apply-body", "apply-body"]
  assert (case.workspace.instance / "managed.txt").read_bytes() == b"new\n"
  before = ledger(case.domain)
  with pytest.raises(Conflict): execute(case)
  assert ledger(case.domain) == before


@pytest.mark.parametrize("phase", PHASES)
def test_legacy_batch_without_target_remains_readable_without_backfill(phase):
  value = batch(phase, operation="setup" if phase.startswith("maintenance_") else "stop_only")
  restored = maintenance.decode_batch(maintenance.encode_batch(value))
  assert restored == value and "target_deployment_digest" not in restored["maintenance_dispatch"]


@pytest.mark.parametrize("state", ["dispatched", "confirmed", "unknown"])
def test_target_digest_roundtrips_only_as_observation_after_consumption(state):
  value = batch("maintenance_succeeded" if state == "confirmed" else "maintenance_running", operation="setup")
  value["maintenance_dispatch"].update(setup_plan_digest="8" * 64, target_deployment_digest="9" * 64)
  if state == "unknown":
    value["maintenance_dispatch"]["state"] = "unknown"
    value.update(phase="unknown", review_required=True)
  assert maintenance.decode_batch(maintenance.encode_batch(value)) == value


@pytest.mark.parametrize("invalid", [None, True, 9, [], {}, "9" * 63, "G" * 64, "9" * 64 + "\n"])
def test_target_digest_rejects_invalid_types_and_shape(invalid):
  value = batch("maintenance_running", operation="setup")
  value["maintenance_dispatch"].update(setup_plan_digest="8" * 64, target_deployment_digest=invalid)
  with pytest.raises(Conflict): maintenance.encode_batch(value)
  with pytest.raises(Conflict): maintenance.decode_batch(json.dumps(value).encode())


@pytest.mark.parametrize("phase", ["accepted", "maintenance_dispatch_intent", "missing-plan"])
def test_target_digest_requires_consumed_stage_and_original_plan_digest(phase):
  value = batch("maintenance_running" if phase == "missing-plan" else phase, operation="setup")
  value["maintenance_dispatch"]["target_deployment_digest"] = "9" * 64
  if phase != "missing-plan": value["maintenance_dispatch"]["setup_plan_digest"] = "8" * 64
  with pytest.raises(Conflict): maintenance.encode_batch(value)
  with pytest.raises(Conflict): maintenance.decode_batch(json.dumps(value).encode())
