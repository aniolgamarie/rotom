"""schema 3 持久登记语义与真实文件故障切点；不执行宿主、租约或预算动作。"""

import json
import stat

import pytest

from agentcfg.model_delegate import DelegationRuns
from agentcfg.model_delegate_actions import capture_delegate_action, delegate_action_identity
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


ORIGIN = {"instance_id": "instance-1", "host": "pi", "source_id": "parent-session:1", "task_id": "task-1", "step_id": None}
BINDING = {"runtime_identity_digest": "1" * 64, "capability_binding_digest": "2" * 64,
  "config_identity_digest": "3" * 64, "policy_digest": "4" * 64, "workspace_identity_digest": "5" * 64,
  "account_scope_id": "account-1", "budget_scope_id": "budget-1"}


def submit(**patch):
  return {"schema_version": 3, "action": "submit", "request_id": "父提交-😀", "backend": "pi", "mode": "review", "preset": "review",
    "task": " /literal task\0 ", "model": {"provider_id": "provider", "model_id": "model"}, "cwd": "/fictional/project", "timeout_seconds": 30, **patch}


def follow(kind, run_id, request_id, **patch):
  result = {"schema_version": 3, "action": kind, "request_id": request_id, "run_id": run_id}
  if kind != "cancel": result["text"] = " /literal next\0 "
  if kind == "continue": result["timeout_seconds"] = 40
  return {**result, **patch}


def files(root):
  return {str(path.relative_to(root)): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in root.rglob("*.json")}


def read_json(path):
  return json.loads(path.read_bytes())


def overwrite(path, value):
  # 只修改临时 HOME 中自有测试对象，不改变生产权限或上游。
  path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))


def conflict(call, code=None):
  with pytest.raises(Conflict) as failure: call()
  message = str(failure.value)
  assert "synthetic-secret" not in message
  if code is not None: assert message == code
  return message


def assert_prepared(result, value, *, run_id=None):
  identity = delegate_action_identity(ORIGIN, value)
  assert result == {"schema_version": 3, "run_id": run_id or "run-" + identity["key"],
    "action_key": identity["key"], "request_digest": identity["request_digest"], "registration": "prepared"}


def test_repeated_submit_and_three_actions_register_in_order_on_same_logical_run(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root); value = submit()
  result = runs.prepare_modern_intent(ORIGIN, value, BINDING); assert_prepared(result, value)
  stored = read_json(root / "intents-v3" / (result["action_key"] + ".json"))
  assert stored["kind"] == "action-intent" and stored["action"] == capture_delegate_action(value)
  assert stored["origin"] == ORIGIN and stored["key"] == result["action_key"]
  baseline = files(root)
  assert runs.prepare_modern_intent(ORIGIN, value, BINDING) == result
  assert files(root) == baseline
  results = [result]
  for kind in ["message", "continue", "cancel"]:
    request = follow(kind, result["run_id"], "request-" + kind)
    next_result = runs.prepare_modern_intent(ORIGIN, request, BINDING)
    assert_prepared(next_result, request, run_id=result["run_id"])
    assert runs.prepare_modern_intent(ORIGIN, request, BINDING) == next_result
    results.append(next_result)
  run = read_json(root / (result["run_id"] + ".json"))
  assert run["schema_version"] == 3 and run["kind"] == "logical-run-intents"
  assert run["origin"] == ORIGIN and run["binding"] == BINDING
  assert run["submit_key"] == result["action_key"] and run["submit_request_digest"] == result["request_digest"]
  assert run["action_keys"] == [item["action_key"] for item in results]
  assert len(list(root.glob("run-*.json"))) == 1 and len(list((root / "intents-v3").glob("*.json"))) == 4
  assert not (root / "prepare-v3.pending.json").exists()


def test_replay_content_action_and_nonexistent_target_conflicts_before_target_lookup(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root); original = submit(); result = runs.prepare_modern_intent(ORIGIN, original, BINDING)
  for changed in [submit(task="synthetic-secret changed"), follow("cancel", "nonexistent-run", original["request_id"]),
      submit(model={"provider_id": "provider", "model_id": "other"})]:
    before = files(root); conflict(lambda: runs.prepare_modern_intent(ORIGIN, changed, BINDING), "DELEGATE_INTENT_CONFLICT"); assert files(root) == before
  message = follow("message", result["run_id"], "message-id"); runs.prepare_modern_intent(ORIGIN, message, BINDING)
  for changed in [{**message, "text": "different"}, {**message, "run_id": "nonexistent-run"}, follow("cancel", result["run_id"], "message-id")]:
    before = files(root); conflict(lambda: runs.prepare_modern_intent(ORIGIN, changed, BINDING), "DELEGATE_INTENT_CONFLICT"); assert files(root) == before


def test_reopen_replay_ignores_activation_environment_and_query_has_no_side_effect(tmp_path, monkeypatch):
  root = tmp_path / "runs"; value = submit(); first = DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING)
  before = files(root); monkeypatch.setenv("ACTIVATION_ID", "new-owner"); monkeypatch.setenv("OWNER_NONCE", "new-random")
  reopened = DelegationRuns(root)
  assert reopened.prepare_modern_intent(ORIGIN, value, BINDING) == first
  observed = reopened.read_modern_intent(ORIGIN, value["request_id"])
  assert observed == first
  assert files(root) == before


def test_cross_origin_cannot_read_or_append_to_existing_run(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root); value = submit(); result = runs.prepare_modern_intent(ORIGIN, value, BINDING)
  for field, changed in [("instance_id", "other-instance"), ("host", "codex"), ("source_id", "other-source"), ("task_id", None), ("step_id", "step-2")]:
    other = {**ORIGIN, field: changed}; before = files(root)
    conflict(lambda: runs.read_modern_intent(other, value["request_id"]), "DELEGATE_INTENT_NOT_FOUND")
    conflict(lambda: runs.prepare_modern_intent(other, follow("message", result["run_id"], "other-id"), BINDING), "DELEGATE_INTENT_ORIGIN_CONFLICT")
    assert files(root) == before


def test_all_binding_identity_and_account_budget_drift_conflicts_without_rebinding(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root); value = submit(); result = runs.prepare_modern_intent(ORIGIN, value, BINDING)
  for field in BINDING:
    other = {**BINDING, field: "f" * 64 if field.endswith("_digest") else "other-scope"}; before = files(root)
    conflict(lambda: runs.prepare_modern_intent(ORIGIN, value, other), "DELEGATE_INTENT_BINDING_CONFLICT")
    conflict(lambda: runs.prepare_modern_intent(ORIGIN, follow("continue", result["run_id"], "new-round"), other), "DELEGATE_INTENT_BINDING_CONFLICT")
    assert files(root) == before


def test_private_storage_and_v2_reader_reject_modern_record(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root); result = runs.prepare_modern_intent(ORIGIN, submit(), BINDING)
  assert stat.S_IMODE(root.stat().st_mode) == 0o700
  assert stat.S_IMODE((root / "intents-v3").stat().st_mode) == 0o700
  assert all(mode == 0o600 for _contents, mode in files(root).values())
  before = files(root); conflict(lambda: runs.read(result["run_id"]), "DELEGATE_STATE_INVALID"); assert files(root) == before


@pytest.mark.parametrize("phase", ["pending", "intent", "run", "clear"])
def test_four_durable_cut_points_reopen_to_one_registration_without_external_actions(tmp_path, monkeypatch, phase):
  import agentcfg.model_delegate_v3_intents as modern
  root = tmp_path / "runs"; value = submit(); identity = delegate_action_identity(ORIGIN, value)
  def cut(actual):
    if actual == phase: raise RuntimeError("synthetic registration cut")
  monkeypatch.setattr(modern, "_checkpoint", cut)
  with pytest.raises(RuntimeError, match="synthetic registration cut"):
    DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING)
  pending = root / "prepare-v3.pending.json"
  assert pending.exists() is (phase != "clear")
  assert (root / "intents-v3" / (identity["key"] + ".json")).exists() is (phase != "pending")
  assert (root / ("run-" + identity["key"] + ".json")).exists() is (phase in {"run", "clear"})
  before = files(root)
  if pending.exists():
    conflict(lambda: DelegationRuns(root).read_modern_intent(ORIGIN, value["request_id"]), "DELEGATE_INTENT_RECOVERY_PENDING")
    assert files(root) == before
  monkeypatch.setattr(modern, "_checkpoint", lambda _phase: None)
  reopened = DelegationRuns(root); result = reopened.prepare_modern_intent(ORIGIN, value, BINDING); assert_prepared(result, value)
  assert not pending.exists()
  assert read_json(root / (result["run_id"] + ".json"))["action_keys"] == [identity["key"]]
  assert len(list((root / "intents-v3").glob("*.json"))) == 1
  stable = files(root); assert DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING) == result; assert files(root) == stable


def interrupted(root, monkeypatch, phase="intent"):
  import agentcfg.model_delegate_v3_intents as modern
  value = submit()
  def cut(actual):
    if actual == phase: raise RuntimeError("synthetic cut")
  monkeypatch.setattr(modern, "_checkpoint", cut)
  with pytest.raises(RuntimeError): DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING)
  monkeypatch.setattr(modern, "_checkpoint", lambda _phase: None)
  identity = delegate_action_identity(ORIGIN, value)
  return value, root / ("run-" + identity["key"] + ".json"), root / "intents-v3" / (identity["key"] + ".json")


def test_recovery_rejects_mismatched_intent_before_publishing_run(tmp_path, monkeypatch):
  root = tmp_path / "runs"; value, run_path, intent_path = interrupted(root, monkeypatch)
  intent = read_json(intent_path); intent["unexpected"] = "synthetic-secret"; overwrite(intent_path, intent)
  before = files(root); conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING))
  assert files(root) == before and not run_path.exists()
  assert (root / "prepare-v3.pending.json").exists()


def test_recovery_preserves_unexpected_current_run_instead_of_overwriting(tmp_path, monkeypatch):
  root = tmp_path / "runs"; value, run_path, _intent_path = interrupted(root, monkeypatch, "run")
  run = read_json(run_path); run["unexpected"] = "synthetic-secret"; overwrite(run_path, run)
  before = files(root); conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING))
  assert files(root) == before and (root / "prepare-v3.pending.json").exists()


@pytest.mark.parametrize("target", ["run", "intent", "pending"])
def test_unknown_extra_or_schema_in_stored_objects_fails_without_silent_repair(tmp_path, monkeypatch, target):
  root = tmp_path / "runs"; value, run_path, intent_path = interrupted(root, monkeypatch, "run")
  path = {"run": run_path, "intent": intent_path, "pending": root / "prepare-v3.pending.json"}[target]
  row = read_json(path); row["schema_version"] = True; row["unexpected"] = "synthetic-secret"; overwrite(path, row)
  before = files(root); conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING)); assert files(root) == before


@pytest.mark.parametrize("target", ["intent", "run", "pending"])
def test_unsafe_file_modes_preserve_pending_and_all_targets(tmp_path, monkeypatch, target):
  root = tmp_path / "runs"; value, run_path, intent_path = interrupted(root, monkeypatch, "run")
  path = {"run": run_path, "intent": intent_path, "pending": root / "prepare-v3.pending.json"}[target]
  path.chmod(0o644); before = files(root)
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING)); assert files(root) == before


def test_bad_native_capture_creates_no_storage_and_executes_no_hooks(tmp_path):
  hooks = []
  class DictHook(dict):
    def keys(self): hooks.append("keys"); raise AssertionError
    def __iter__(self): hooks.append("iter"); raise AssertionError
    def __deepcopy__(self, memo): hooks.append("deepcopy"); raise AssertionError
  class StrHook(str):
    def encode(self, *args, **kwargs): hooks.append("encode"); raise AssertionError
    def __str__(self): hooks.append("str"); raise AssertionError
  cases = [(DictHook(ORIGIN), submit(), BINDING), (ORIGIN, DictHook(submit()), BINDING), (ORIGIN, submit(), DictHook(BINDING)),
    (ORIGIN, submit(task=StrHook("task")), BINDING), (ORIGIN, submit(), {**BINDING, "policy_digest": StrHook("4" * 64)}),
    (ORIGIN, submit(approved=True), BINDING), (ORIGIN, submit(), {**BINDING, "runtime_identity_digest": "bad-synthetic-secret"})]
  for index, (origin, value, binding) in enumerate(cases):
    root = tmp_path / ("invalid-" + str(index))
    with pytest.raises(ConfigError): DelegationRuns(root).prepare_modern_intent(origin, value, binding)
    assert not root.exists()
  assert hooks == []


@pytest.mark.parametrize("phase", ["pending", "intent", "run", "clear"])
def test_new_message_transaction_recovers_against_original_run_before_image(tmp_path, monkeypatch, phase):
  import agentcfg.model_delegate_v3_intents as modern
  root = tmp_path / "runs"; initial = DelegationRuns(root).prepare_modern_intent(ORIGIN, submit(), BINDING)
  request = follow("message", initial["run_id"], "message-after-existing-run")
  run_path = root / (initial["run_id"] + ".json"); before_run = run_path.read_bytes()
  def cut(actual):
    if actual == phase: raise RuntimeError("synthetic append cut")
  monkeypatch.setattr(modern, "_checkpoint", cut)
  with pytest.raises(RuntimeError): DelegationRuns(root).prepare_modern_intent(ORIGIN, request, BINDING)
  if phase in {"pending", "intent"}: assert run_path.read_bytes() == before_run
  monkeypatch.setattr(modern, "_checkpoint", lambda _phase: None)
  result = DelegationRuns(root).prepare_modern_intent(ORIGIN, request, BINDING)
  assert_prepared(result, request, run_id=initial["run_id"])
  assert read_json(run_path)["action_keys"] == [initial["action_key"], result["action_key"]]
  assert len(list((root / "intents-v3").glob("*.json"))) == 2


@pytest.mark.parametrize("tamper", ["before", "after", "intent"])
def test_pending_metadata_mismatch_is_not_used_to_overwrite_targets(tmp_path, monkeypatch, tamper):
  root = tmp_path / "runs"; value, _run_path, _intent_path = interrupted(root, monkeypatch, "intent")
  path = root / "prepare-v3.pending.json"; pending = read_json(path)
  if tamper == "before": pending["before_run_digest"] = "a" * 64
  elif tamper == "after": pending["run_record"]["action_keys"].append("b" * 64)
  else: pending["intent"]["action"]["task"] = "synthetic-secret changed"
  overwrite(path, pending); before = files(root)
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING))
  assert files(root) == before
  conflict(lambda: DelegationRuns(root).read_modern_intent(ORIGIN, value["request_id"]), "DELEGATE_INTENT_RECOVERY_PENDING")
  assert files(root) == before


def test_modern_action_rejects_explicit_legacy_format_without_migration(tmp_path):
  root = tmp_path / "runs"; root.mkdir(mode=0o700)
  path = root / "legacy-run.json"; path.write_text('{"schema_version":2}'); path.chmod(0o600)
  before = files(root)
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, follow("cancel", "legacy-run", "legacy-target"), BINDING), "DELEGATE_INTENT_FORMAT_UNSUPPORTED")
  assert files(root) == before


def test_valid_but_different_current_run_does_not_match_pending_before_or_after(tmp_path, monkeypatch):
  root = tmp_path / "runs"; value, run_path, _intent_path = interrupted(root, monkeypatch, "run")
  run = read_json(run_path); run["binding"]["budget_scope_id"] = "different-budget"
  overwrite(run_path, run); before = files(root)
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, value, BINDING))
  assert files(root) == before


def test_deleted_registered_intent_cannot_retarget_same_request_id_to_other_run(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root)
  first = runs.prepare_modern_intent(ORIGIN, submit(request_id="first-run"), BINDING)
  second = runs.prepare_modern_intent(ORIGIN, submit(request_id="second-run"), BINDING)
  message = follow("message", first["run_id"], "same-message-id")
  intent = runs.prepare_modern_intent(ORIGIN, message, BINDING)
  missing_path = root / "intents-v3" / (intent["action_key"] + ".json"); missing_path.unlink()
  before = files(root)
  changed = {**message, "run_id": second["run_id"]}
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, changed, BINDING), "DELEGATE_INTENT_STATE_INVALID")
  assert files(root) == before and not missing_path.exists()
  assert read_json(root / (first["run_id"] + ".json"))["action_keys"] == [first["action_key"], intent["action_key"]]
  assert read_json(root / (second["run_id"] + ".json"))["action_keys"] == [second["action_key"]]


def test_missing_historical_message_intent_blocks_distinct_new_request_on_same_run(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root)
  initial = runs.prepare_modern_intent(ORIGIN, submit(), BINDING)
  old_message = runs.prepare_modern_intent(ORIGIN, follow("message", initial["run_id"], "old-message"), BINDING)
  (root / "intents-v3" / (old_message["action_key"] + ".json")).unlink()
  before = files(root)
  request = follow("message", initial["run_id"], "new-message")
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, request, BINDING), "DELEGATE_INTENT_STATE_INVALID")
  assert files(root) == before
  assert not (root / "intents-v3" / (delegate_action_identity(ORIGIN, request)["key"] + ".json")).exists()


def test_other_run_self_consistent_historical_intent_cannot_replace_chain_member(tmp_path):
  root = tmp_path / "runs"; runs = DelegationRuns(root)
  first = runs.prepare_modern_intent(ORIGIN, submit(request_id="first-chain"), BINDING)
  second = runs.prepare_modern_intent(ORIGIN, submit(request_id="second-chain"), BINDING)
  first_message = runs.prepare_modern_intent(ORIGIN, follow("message", first["run_id"], "first-message"), BINDING)
  second_message = runs.prepare_modern_intent(ORIGIN, follow("message", second["run_id"], "second-message"), BINDING)
  missing_path = root / "intents-v3" / (first_message["action_key"] + ".json"); missing_path.unlink()
  # 原样复制另一个完整合法意图；自洽 JSON 仍不能替代此 run 的历史成员。
  other_path = root / "intents-v3" / (second_message["action_key"] + ".json")
  missing_path.write_bytes(other_path.read_bytes()); missing_path.chmod(0o600)
  before = files(root)
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, follow("message", first["run_id"], "third-message"), BINDING), "DELEGATE_INTENT_STATE_INVALID")
  assert files(root) == before


def test_pending_append_cannot_skip_missing_historical_intent_or_write_new_leaf(tmp_path, monkeypatch):
  import agentcfg.model_delegate_v3_intents as modern
  root = tmp_path / "runs"; runs = DelegationRuns(root)
  initial = runs.prepare_modern_intent(ORIGIN, submit(), BINDING)
  historical = runs.prepare_modern_intent(ORIGIN, follow("message", initial["run_id"], "history-message"), BINDING)
  new_request = follow("message", initial["run_id"], "pending-message")
  def cut(phase):
    if phase == "pending": raise RuntimeError("synthetic pending append cut")
  monkeypatch.setattr(modern, "_checkpoint", cut)
  with pytest.raises(RuntimeError): runs.prepare_modern_intent(ORIGIN, new_request, BINDING)
  monkeypatch.setattr(modern, "_checkpoint", lambda _phase: None)
  (root / "intents-v3" / (historical["action_key"] + ".json")).unlink()
  new_path = root / "intents-v3" / (delegate_action_identity(ORIGIN, new_request)["key"] + ".json")
  assert not new_path.exists()
  before = files(root)
  conflict(lambda: DelegationRuns(root).prepare_modern_intent(ORIGIN, new_request, BINDING))
  assert files(root) == before and (root / "prepare-v3.pending.json").exists() and not new_path.exists()


def test_pending_after_image_can_restore_only_its_missing_new_leaf(tmp_path, monkeypatch):
  import agentcfg.model_delegate_v3_intents as modern
  root = tmp_path / "runs"; runs = DelegationRuns(root)
  initial = runs.prepare_modern_intent(ORIGIN, submit(), BINDING)
  historical = runs.prepare_modern_intent(ORIGIN, follow("message", initial["run_id"], "history-message"), BINDING)
  new_request = follow("message", initial["run_id"], "pending-message")
  def cut(phase):
    if phase == "run": raise RuntimeError("synthetic run append cut")
  monkeypatch.setattr(modern, "_checkpoint", cut)
  with pytest.raises(RuntimeError): runs.prepare_modern_intent(ORIGIN, new_request, BINDING)
  monkeypatch.setattr(modern, "_checkpoint", lambda _phase: None)
  identity = delegate_action_identity(ORIGIN, new_request)
  new_path = root / "intents-v3" / (identity["key"] + ".json")
  postimage = read_json(root / "prepare-v3.pending.json")["intent"]
  new_path.unlink()
  run_path = root / (initial["run_id"] + ".json"); run_before = run_path.read_bytes()
  result = DelegationRuns(root).prepare_modern_intent(ORIGIN, new_request, BINDING)
  assert_prepared(result, new_request, run_id=initial["run_id"])
  assert read_json(new_path) == postimage and run_path.read_bytes() == run_before
  assert read_json(run_path)["action_keys"] == [initial["action_key"], historical["action_key"], identity["key"]]
  assert len(list(root.glob("run-*.json"))) == 1 and len(list((root / "intents-v3").glob("*.json"))) == 3
  assert not (root / "prepare-v3.pending.json").exists()
  before = files(root); assert DelegationRuns(root).prepare_modern_intent(ORIGIN, new_request, BINDING) == result; assert files(root) == before
