"""维护编排隔离测试：真实临时部署/短锁；宿主、停止和会话观察使用合成替身。"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import commands, deployment, dsh_stop, dsh_stop_client, dsh_stop_plan, lifecycle
from agentcfg import run_owners, runtime, tool_maintenance as flow
from agentcfg.render import RenderCandidate
from agentcfg.sessions import KnownSession, SessionRef
from agentcfg.storage import Conflict, Tree
from test_deployment import candidate
from test_rotom_maintenance_plan import RUNS, snapshots
from test_rotom_runtime_observation import MANAGER, observation
from test_rotom_resume_runtime import managed
from test_pi_reboot_dependencies import fake_npm, recipe_repository
from test_pi_reboot_pipeline import pipeline, prepare
from test_rotom_omp_cooperative_launch import case, manual_owner


_STATUS_STOP = dsh_stop_client.status_stop
_REQUIRE_HANDOFF = flow._require_handoff


BATCH = "e" * 32
SESSION = "12345678-1234-4234-8234-123456789abc"
SECOND = "87654321-4321-4321-8321-cba987654321"


class Progress:
  def stage(self, *args, **kwargs):
    pass

  def sync_stage(self, *args, **kwargs):
    pass

  @contextmanager
  def heartbeat(self):
    yield


def stop_plan(ws):
  runs, resources = snapshots()
  resources = [{key: row[key] for key in ("resource_id", "key", "reference_runs", "coverage")} for row in resources]
  scope = {**ws.binding, "agent": ws.agent}
  for row in runs:
    row["scope"] = deepcopy(scope)
  coordinator = {"kind": ws.agent + "-instance-registry",
    "binding_digest": run_owners.Registry(Path("/unused"), ws.binding).binding_digest,
    "registry_physical": {"device": 1, "inode": 2}, "records_digest": "f" * 64}
  return dsh_stop_plan.build(scope=scope, operation="stop_only", selected_runs=RUNS[:2],
    runs=runs, resources=resources, coordinator=coordinator, control_capability="supported")


def known(ws, identifier, cwd):
  from agentcfg.dsh_sessions import scope_key
  relative, kind = {"dsh": ("dsh-home", "dsh-home"), "pi": ("pi-home", "pi-home"),
    "omp": ("user-home", "omp-managed-home")}[ws.agent]
  return KnownSession(SessionRef(ws.agent, "managed", run_owners.native_home_key(
    {"kind": kind, "path": str(ws.instance / relative)}), identifier), scope_key(ws.binding),
    ws.profile, str(cwd), "historical", "historical", 100, None)


def patch_observations(ws, cwd, monkeypatch):
  state = SimpleNamespace(ws=ws, stop_plan=stop_plan(ws),
    records={run: {"session_observation": None} for run in RUNS},
    sessions={SESSION: known(ws, SESSION, cwd), SECOND: known(ws, SECOND, cwd)},
    stop_result={"status": "stopped", "targets": [{"run_id": RUNS[0], "lifecycle_state": "idle_confirmed"}]},
    launches=[], approvals=[], syncs=[])
  monkeypatch.setattr(dsh_stop, "capture_stop", lambda *args, **kwargs:
    ({"plan": deepcopy(state.stop_plan)}, deepcopy(state.records), {}))
  monkeypatch.setattr(flow, "lookup_session", lambda workspace, identifier: state.sessions[identifier])
  monkeypatch.setattr(dsh_stop_client, "status_stop", lambda *args, **kwargs: deepcopy(state.stop_result))
  return state


@pytest.fixture(params=["dsh", "pi", "omp"])
def workflow(tmp_path, monkeypatch, request):
  # 合成 lock 不是静态准入材料；真实能力表由专项负例直接核验。
  monkeypatch.setattr(flow, "_require_handoff", lambda *args: None)
  ws = SimpleNamespace(agent=request.param, profile=request.param + "-test", instance=tmp_path / "instance",
    state_root=tmp_path / "state", cache=tmp_path / "cache", local_path=tmp_path / "local.toml",
    binding={"machine": "fixture", "local": str(tmp_path / "local.toml"), "profile": request.param + "-test"})
  state = patch_observations(ws, tmp_path, monkeypatch)
  state.lock = SimpleNamespace(identity="fixture")
  state.candidate = RenderCandidate("b" * 64, candidate("B").artifacts)
  state.launch = {"lock_identity": "fixture", "secrets": []}
  ws.adapter = SimpleNamespace(lifecycle_guard=lifecycle.inactive_guard, prepare_runtime=lambda *args: None)
  # 双参数旧后端：普通 setup 必须继续不传 proxy/maintenance。
  def sync(selected, lock):
    assert selected is ws and lock is state.lock
    state.syncs.append(True)
  ws.backend = SimpleNamespace(sync=sync, root=lambda *args: tmp_path / "package")
  monkeypatch.setattr(runtime, "record", lambda *args: deepcopy(state.launch))
  commands.apply_candidate(ws, state.lock, RenderCandidate("a" * 64, candidate("A").artifacts))
  monkeypatch.setattr(commands, "prepared", lambda args: (ws, state.lock, state.candidate))
  state.mapping = dict(zip(RUNS[:2], (SESSION, SECOND)))
  state.plan = flow.plan(ws, selected_runs=RUNS[:2], sessions=state.mapping)
  assert state.plan["readiness"] == "ready"
  return state


def begin(state):
  return flow.Store(state.ws, BATCH).begin(state.plan)


def execute(state, approve=None):
  def review(value):
    state.approvals.append(deepcopy(value))
    return True
  return flow.execute(state.ws, BATCH, approve=approve or review, progress=Progress(), preview=lambda *args: None)


def update(state):
  begin(state)
  code, result = execute(state)
  assert code == 0 and result["status"] == "updated"
  return result


def payloads(root):
  return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def rehash(value):
  value["plan_id"] = flow._plan_digest(value)
  return value


def test_plan_timestamp_stability_exact_targets_and_no_persistence(workflow):
  state = workflow
  before = payloads(state.ws.state_root)
  state.sessions = {key: replace(value, observed_at_ns=999) for key, value in state.sessions.items()}
  fresh = flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping)
  assert fresh["plan_id"] == state.plan["plan_id"]
  assert fresh["targets"] != state.plan["targets"]
  assert payloads(state.ws.state_root) == before


def test_missing_and_duplicate_session_block_plan(workflow):
  state = workflow
  missing = flow.plan(state.ws, selected_runs=RUNS[:2], sessions={})
  assert missing["blockers"] == ["session-required:" + run for run in RUNS[:2]]
  duplicate = flow.plan(state.ws, selected_runs=RUNS[:2], sessions={run: SESSION for run in RUNS[:2]})
  assert duplicate["blockers"] == ["duplicate-restore-session"]
  for bad in (missing, duplicate):
    with pytest.raises(Conflict):
      flow.Store(state.ws, BATCH).begin(bad)
  assert not (state.ws.state_root / "maintenance-workflows").exists()
  with pytest.raises(ValueError):
    flow.plan(state.ws, selected_runs=RUNS[:2], sessions={RUNS[2]: SESSION})


@pytest.mark.parametrize("field", ["agent", "backend", "native_home_ref", "scope", "profile", "cwd", "confirmation"])
def test_lookup_scope_is_checked_before_plan_and_restore(workflow, field):
  state = workflow
  value = state.sessions[SESSION]
  if field in ("agent", "backend", "native_home_ref"):
    bad = replace(value, ref=replace(value.ref, **{field: "omp" if value.ref.agent != "omp" and field == "agent" else "dsh" if field == "agent" else "other"}))
  else:
    bad = replace(value, **{field: "unknown" if field == "confirmation" else None if field == "cwd" else "other"},
      **({"cwd_status": "unknown"} if field == "cwd" else {}))
  state.sessions[SESSION] = bad
  with pytest.raises(Conflict):
    flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping)
  state.sessions[SESSION] = value
  update(state)
  state.sessions[SESSION] = bad
  with pytest.raises(Conflict):
    flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda target, **kwargs: pytest.fail("scope mismatch launched"))
  assert flow.Store(state.ws, BATCH).read()["revision"] == 2


def test_historical_fallback_requires_complete_matching_ref(workflow):
  state = workflow
  state.records[RUNS[0]]["session_observation"] = {"confirmation": "historical", "session": asdict(state.sessions[SESSION].ref)}
  planned = flow.plan(state.ws, selected_runs=RUNS[:2], sessions={RUNS[1]: SECOND})
  assert planned["readiness"] == "ready"
  state.records[RUNS[0]]["session_observation"]["session"]["native_home_ref"] = "other"
  with pytest.raises(Conflict):
    flow.plan(state.ws, selected_runs=RUNS[:2], sessions={RUNS[1]: SECOND})
  state.records[RUNS[0]]["session_observation"]["confirmation"] = "unknown"
  assert flow.plan(state.ws, selected_runs=RUNS[:2], sessions={RUNS[1]: SECOND})["readiness"] == "blocked"


@pytest.mark.parametrize("damage", ["setup-extra", "summary", "generation", "schema-bool", "scope", "home", "duplicate", "stop-operation"])
def test_manifest_invalid_rehashed_substructure_never_written(workflow, damage):
  state = workflow
  value = deepcopy(state.plan)
  if damage == "setup-extra": value["setup"]["extra"] = True
  elif damage == "summary": value["setup"]["summary"]["changes"] = True
  elif damage == "generation": value["setup"]["target_generation"] = "bad"
  elif damage == "schema-bool": value["schema_version"] = True
  elif damage == "scope": value["targets"][RUNS[0]]["scope"] = "other"
  elif damage == "home": value["targets"][RUNS[0]]["ref"]["native_home_ref"] = "other"
  elif damage == "duplicate": value["targets"][RUNS[1]] = deepcopy(value["targets"][RUNS[0]])
  else: value["stop_plan"]["operation"] = "setup"
  with pytest.raises(Conflict):
    flow.Store(state.ws, BATCH).begin(rehash(value))
  assert not (state.ws.state_root / "maintenance-workflows").exists()


def test_manifest_no_overwrite_event_cas_and_invalid_append_no_artifacts(workflow):
  state = workflow
  store = flow.Store(state.ws, BATCH)
  initial = begin(state)
  before = payloads(store.registry.root)
  with pytest.raises(Conflict): store.begin(state.plan)
  for action, fields in (("setup-result", {"exit_code": 0}), ("restore-intent", {"run_id": RUNS[0]}),
      ("cancel", {"plan_id": "a" * 64}), ("setup-intent", {"plan_id": "bad"}), ("bogus", {})):
    with pytest.raises(Conflict): store.append(initial, action, **fields)
    assert payloads(store.registry.root) == before
  intent = store.append(initial, "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  with pytest.raises(Conflict): store.append(initial, "cancel")
  assert store.read() == intent
  assert (store.registry.root / "manifest.json").read_bytes() == before["manifest.json"]


@pytest.mark.parametrize("damage", ["action", "code", "plan", "deployment", "run", "unknown", "order"])
def test_invalid_action_fields_or_order_rejected_before_write(workflow, damage):
  state = workflow
  store = flow.Store(state.ws, BATCH)
  initial = begin(state)
  intent = store.append(initial, "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  event = dict(run_id=None, plan_id="a" * 64, exit_code=0, deployment="b" * 64)
  action = "setup-result"
  if damage == "action": action = "setup-intent"
  elif damage == "code": event["exit_code"] = True
  elif damage == "plan": event["plan_id"] = "c" * 64
  elif damage == "deployment": event["deployment"] = None
  elif damage == "run": event["run_id"] = RUNS[0]
  elif damage == "unknown": action = "unknown-result"
  else:
    event["exit_code"], event["deployment"] = 4, "b" * 64
  before = payloads(store.registry.root)
  with pytest.raises(Conflict): store.append(intent, action, **event)
  assert payloads(store.registry.root) == before


def test_reader_checks_tampered_manifest_and_chained_event_semantics(workflow):
  state = workflow
  store = flow.Store(state.ws, BATCH)
  initial = begin(state)
  intent = store.append(initial, "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  event_path = store.registry.root / "event-0001.json"
  event = deepcopy(intent["events"][0])
  event["run_id"] = RUNS[0]
  # 这是显式损坏 fixture，正常 append 已由前面的用例证明写前拒绝。
  event_path.write_bytes(run_owners._encode(event))
  with pytest.raises(Conflict): store.read()
  event_path.write_bytes(run_owners._encode(intent["events"][0]))
  manifest_path = store.registry.root / "manifest.json"
  manifest = deepcopy(initial["manifest"])
  manifest["plan"]["setup"]["extra"] = True
  rehash(manifest["plan"])
  manifest_path.write_bytes(run_owners._encode(manifest))
  with pytest.raises(Conflict): store.read()


def test_stop_approval_partial_result_and_no_setup_bypass(workflow, monkeypatch):
  state = workflow
  stopped = []
  state.sessions = {key: replace(value, observed_at_ns=999) for key, value in state.sessions.items()}
  state.stop_result = {"status": "pending", "protected": True,
    "targets": [{"run_id": RUNS[0], "lifecycle_state": "idle_confirmed"}, {"run_id": RUNS[1], "lifecycle_state": "active"}]}
  def stop(ws, *, expected_plan, batch_id, approve, wait_seconds):
    assert approve(expected_plan) is True
    assert expected_plan == state.plan["stop_plan"]
    stopped.append((batch_id, wait_seconds))
  monkeypatch.setattr(dsh_stop_client, "execute_stop", stop)
  result = flow.stop(state.ws, expected_plan=state.plan, approve=lambda value: True, wait_seconds=2)
  assert result["stop"] == state.stop_result and result["stop_status"] == "pending"
  assert stopped == [(result["batch_id"], 2)]
  with pytest.raises(Conflict):
    flow.execute(state.ws, result["batch_id"], approve=lambda _: True, progress=Progress(), preview=lambda *a: None)
  assert state.syncs == []


def test_stop_declined_or_stale_has_no_manifest(workflow, monkeypatch):
  state = workflow
  monkeypatch.setattr(dsh_stop_client, "execute_stop", lambda *a, **kw: pytest.fail("stop dispatched"))
  with pytest.raises(Conflict): flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: False)
  state.sessions[SESSION] = replace(state.sessions[SESSION], cwd=str(state.ws.instance))
  with pytest.raises(Conflict): flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: True)
  assert not (state.ws.state_root / "maintenance-workflows").exists()


def test_success_ordinary_setup_legacy_backend_and_restore_once(workflow):
  state = workflow
  result = update(state)
  assert (state.ws.instance / "rules.md").read_text() == "B"
  assert len(state.syncs) == len(state.approvals) == 1
  assert result["setup"]["deployment"] is not None
  with pytest.raises(Conflict): execute(state)
  def launch(target, *, expected_deployment):
    assert expected_deployment == result["setup"]["deployment"]
    state.launches.append(target)
    return 17
  code, restored = flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=launch)
  assert code == 17 and restored["restores"][RUNS[0]]["exit_code"] == 17
  assert restored["restores"][RUNS[1]] is None
  assert restored["load_confirmation"] == "unknown" and restored["continue_status"] == "not_sent"
  assert state.launches == [state.sessions[SESSION]]
  with pytest.raises(Conflict): flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=launch)
  assert len(state.launches) == 1


def test_known_failure_preserved_and_retry_requires_new_approval(workflow):
  state = workflow
  begin(state)
  original = state.ws.backend.sync
  def mutate(ws, lock):
    original(ws, lock)
    state.candidate = replace(state.candidate, generation="c" * 64)
  state.ws.backend.sync = mutate
  code, result = execute(state)
  assert code == 4 and result["status"] == "setup-failed"
  assert result["setup"]["exit_code"] == 4 and result["setup"]["deployment"] is None
  assert (state.ws.instance / "rules.md").read_text() == "A"
  state.ws.backend.sync = original
  assert execute(state)[0] == 0
  assert len(state.approvals) == 2
  assert state.approvals[0]["plan_id"] != state.approvals[1]["plan_id"]


def test_unknown_setup_exception_is_not_retried_or_restored(workflow):
  state = workflow
  begin(state)
  calls = []
  def unknown(ws, lock):
    calls.append(True)
    raise ValueError("synthetic-private-canary")
  state.ws.backend.sync = unknown
  with pytest.raises(ValueError): execute(state)
  result = flow.status(state.ws, BATCH)
  assert result["status"] == "setup-unknown" and result["setup"]["action"] == "setup-intent"
  with pytest.raises(Conflict): execute(state)
  with pytest.raises(Conflict): flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda _, **kwargs: pytest.fail("unknown launched"))
  assert calls == [True]
  cancelled = flow.cancel(state.ws, BATCH)
  assert cancelled["cancelled"] is True and cancelled["setup"] == result["setup"]


def test_setup_decline_and_preview_conflict_remain_undispatched(workflow):
  state = workflow
  begin(state)
  with pytest.raises(Conflict): execute(state, approve=lambda _: False)
  assert flow.Store(state.ws, BATCH).read()["revision"] == 0
  (state.ws.instance / "rules.md").write_text("DRIFT")
  code, result = execute(state)
  assert code == 4 and result["setup"] is None and not state.syncs


def test_ordinary_setup_real_physical_and_owner_guards_block_new_run(workflow):
  state = workflow
  begin(state)
  with lifecycle.guard(state.ws, shared=True, create=False):
    with pytest.raises(Conflict): execute(state)
  assert flow.status(state.ws, BATCH)["status"] == "setup-unknown"
  assert (state.ws.instance / "rules.md").read_text() == "A"


def test_parallel_restore_results_survive_other_target_and_cancel(workflow):
  state = workflow
  update(state)
  def first_launch(target, *, expected_deployment):
    def second_launch(other, *, expected_deployment):
      assert other == state.sessions[SECOND]
      flow.cancel(state.ws, BATCH)
      return 23
    assert flow.restore(state.ws, BATCH, run_id=RUNS[1], launch=second_launch)[0] == 23
    return 17
  code, result = flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=first_launch)
  assert code == 17 and result["status"] == "cancelled"
  assert result["restores"][RUNS[0]]["exit_code"] == 17
  assert result["restores"][RUNS[1]]["exit_code"] == 23
  actions = [event["action"] for event in flow.Store(state.ws, BATCH).read()["events"]]
  assert actions == ["setup-intent", "setup-result", "restore-intent", "restore-intent", "cancel", "restore-result", "restore-result"]


def test_unknown_restore_does_not_block_different_target(workflow):
  state = workflow
  update(state)
  def lost(target, *, expected_deployment):
    raise OSError("synthetic-lost-receipt")
  with pytest.raises(OSError): flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lost)
  with pytest.raises(Conflict): flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lost)
  assert flow.restore(state.ws, BATCH, run_id=RUNS[1], launch=lambda _, **kwargs: 0)[0] == 0
  assert flow.status(state.ws, BATCH)["restores"][RUNS[0]]["action"] == "restore-intent"


@pytest.mark.parametrize("damage", ["manifest", "prefix", "digest", "revision", "other-intent"])
def test_completion_rejects_forged_or_replaced_intent_prefix(workflow, damage):
  state = workflow
  update(state)
  store = flow.Store(state.ws, BATCH)
  intent = store.append(store.read(), "restore-intent", run_id=RUNS[0])
  second = store.append(intent, "restore-intent", run_id=RUNS[1])
  forged = deepcopy(intent)
  if damage == "manifest": forged["manifest"]["batch_id"] = "f" * 32
  elif damage == "prefix": forged["events"][0]["plan_id"] = "f" * 64
  elif damage == "digest": forged["digest"] = "f" * 64
  elif damage == "revision": forged["revision"] = 2
  else: forged = second
  before = payloads(store.registry.root)
  with pytest.raises(Conflict): store.complete_restore(forged, RUNS[0], 0)
  assert payloads(store.registry.root) == before
  completed = store.complete_restore(intent, RUNS[0], 0)
  assert completed["events"][-1]["run_id"] == RUNS[0]
  with pytest.raises(Conflict): store.complete_restore(intent, RUNS[0], 0)


def test_cancel_during_setup_records_result_without_restore_or_undo(workflow):
  state = workflow
  begin(state)
  original = state.ws.backend.sync
  def cancel_during_sync(ws, lock):
    original(ws, lock)
    flow.cancel(ws, BATCH)
  state.ws.backend.sync = cancel_during_sync
  code, result = execute(state)
  assert code == 0 and result["cancelled"] is True
  assert result["setup"]["action"] == "setup-result"
  assert (state.ws.instance / "rules.md").read_text() == "B"
  before = payloads(state.ws.state_root)
  assert flow.cancel(state.ws, BATCH)["cancelled"] is True
  assert payloads(state.ws.state_root) == before
  with pytest.raises(Conflict): execute(state)
  with pytest.raises(Conflict): flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda _, **kwargs: pytest.fail("cancelled launched"))


@pytest.fixture(params=["dsh", "pi", "omp"])
def native_workflow(request, monkeypatch, tmp_path):
  # 此 fixture 只验证原部署/owner 门禁，不把假包声明为真实准入组合。
  monkeypatch.setattr(flow, "_require_handoff", lambda *args: None)
  if request.param == "dsh":
    ws, lock, _, _ = request.getfixturevalue("managed")
    proposed = ws.candidate(lock.identity)
    source = None
  elif request.param == "pi":
    ws, backend, lock, _, _ = request.getfixturevalue("pipeline")
    prepare(ws, backend, lock)
    proposed = ws.candidate(lock.identity)
    source = None
  else:
    source = request.getfixturevalue("case")
    ws, lock = source.ws, source.lock
    proposed = RenderCandidate("c" * 64, ws.adapter.render(ws.resolved.data))
  state = patch_observations(ws, tmp_path, monkeypatch)
  state.lock, state.source = lock, source
  # 只替换业务依赖安装；真实 adapter 的 preflight/resource/apply guards 全部保留。
  def legacy_sync(selected, actual_lock):
    assert selected is ws and actual_lock is lock
    state.syncs.append(True)
  monkeypatch.setattr(type(ws.backend), "sync", lambda self, selected, actual_lock: legacy_sync(selected, actual_lock), raising=False)
  monkeypatch.setattr(commands, "prepared", lambda args: (ws, lock, proposed))
  state.mapping = dict(zip(RUNS[:2], (SESSION, SECOND)))
  state.plan = flow.plan(ws, selected_runs=RUNS[:2], sessions=state.mapping)
  assert state.plan["readiness"] == "ready"
  return state


def test_native_adapter_ordinary_setup_and_exact_restore(native_workflow):
  state = native_workflow
  result = update(state)
  assert result["setup"]["exit_code"] == 0
  assert len(state.syncs) == 1
  code, result = flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda target, **kwargs: 19)
  assert code == 19 and result["restores"][RUNS[1]] is None
  assert result["load_confirmation"] == "unknown"


def test_native_adapter_new_run_original_guards_reject_setup(native_workflow):
  state = native_workflow
  begin(state)
  if state.source is None:
    registry = run_owners.Registry(state.ws.state_root / "run-owners", state.ws.binding)
    with lifecycle.guard(state.ws, shared=True, create=False):
      registry.register(MANAGER)
      with pytest.raises(Conflict): execute(state)
  else:
    with state.source.module.cooperative_run(state.ws, state.lock.identity) as lease:
      with manual_owner(state.source, lease):
        with pytest.raises(Conflict): execute(state)
  result = flow.status(state.ws, BATCH)
  assert result["setup"]["action"] == "setup-intent" and result["status"] == "setup-unknown"
  assert result["restores"] == {run: None for run in RUNS[:2]}


def test_old_setup_receipt_cannot_complete_later_same_digest_attempt(workflow):
  state = workflow
  store = flow.Store(state.ws, BATCH)
  original = store.append(begin(state), "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  failed = store.complete_setup(original, 4)
  fresh = store.append(failed, "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  with pytest.raises(Conflict): store.complete_setup(original, 0, deployment="b" * 64)
  assert store.read() == fresh
  assert store.complete_setup(fresh, 0, deployment="b" * 64)["events"][-1]["exit_code"] == 0


def test_later_ordinary_setup_does_not_replace_original_success_target(workflow, monkeypatch):
  state = workflow
  begin(state)
  ordinary = commands._setup_operation
  target = commands.current_plan(state.ws, state.lock, state.candidate).current
  expected = flow.setup_deployment_digest(target)
  def advance_after_apply(*args, **kwargs):
    outcome = ordinary(*args, **kwargs)
    commands.apply_candidate(state.ws, state.lock, RenderCandidate("d" * 64, candidate("LATER").artifacts))
    return outcome
  monkeypatch.setattr(commands, "_setup_operation", advance_after_apply)
  code, result = execute(state)
  assert code == 0 and result["setup"]["exit_code"] == 0
  assert result["setup"]["deployment"] == expected
  assert result["current_deployment_match"] is False
  assert (state.ws.instance / "rules.md").read_text() == "LATER"
  with pytest.raises(Conflict):
    flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda _, **kwargs: pytest.fail("changed deployment launched"))
  assert flow.Store(state.ws, BATCH).read()["revision"] == 2


@pytest.mark.parametrize("damage", ["pending", "changed"])
def test_restore_checks_current_deployment_before_intent(workflow, damage):
  state = workflow
  update(state)
  if damage == "pending":
    with Tree(state.ws.state_root) as tree:
      tree.write_state("pending.json", b"{}\n")
  else:
    commands.apply_candidate(state.ws, state.lock, RenderCandidate("d" * 64, candidate("OTHER").artifacts))
  with pytest.raises(Conflict):
    flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda _, **kwargs: pytest.fail("unverified deployment launched"))
  assert flow.Store(state.ws, BATCH).read()["revision"] == 2


def test_setup_success_result_cannot_claim_different_deployment(workflow):
  state = workflow
  store = flow.Store(state.ws, BATCH)
  intent = store.append(begin(state), "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  before = payloads(store.registry.root)
  with pytest.raises(Conflict): store.complete_setup(intent, 0, deployment="c" * 64)
  assert payloads(store.registry.root) == before


def test_snapshot_before_manager_capture_failure_returns_original_batch(workflow, monkeypatch):
  state = workflow
  calls = []
  original_stop = dsh_stop_client.execute_stop
  for record in state.records.values():
    record["manager_identity"] = deepcopy(MANAGER)
  def fail_capture(identity):
    calls.append(identity)
    raise OSError("synthetic-manager-capture-failure")
  monkeypatch.setattr(dsh_stop_client, "ManagerExit", fail_capture)
  def no_snapshot(*args, **kwargs):
    raise Conflict("synthetic-no-snapshot")
  monkeypatch.setattr(dsh_stop_client, "status_stop", no_snapshot)
  result = flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: True)
  assert result["status"] == result["stop_status"] == "unknown"
  assert result["continue_status"] == "not_sent" and len(calls) == 1
  assert flow.Store(state.ws, result["batch_id"]).read()["revision"] == 0
  assert original_stop is dsh_stop_client.execute_stop


def test_manifest_write_response_loss_returns_original_batch_without_stop(workflow, monkeypatch):
  state = workflow
  saved = []
  original = flow.sync_directory_ancestors
  def response_lost(root):
    original(root)
    saved.append(root.name)
    raise OSError("synthetic-manifest-written-response-lost")
  monkeypatch.setattr(flow, "sync_directory_ancestors", response_lost)
  monkeypatch.setattr(dsh_stop_client, "execute_stop", lambda *a, **kw: pytest.fail("stop after failed manifest response"))
  monkeypatch.setattr(dsh_stop_client, "status_stop", lambda *a, **kw: (_ for _ in ()).throw(Conflict("synthetic-no-snapshot")))
  result = flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: True)
  assert saved == [result["batch_id"]]
  assert result["status"] == result["stop_status"] == "unknown"
  assert flow.Store(state.ws, result["batch_id"]).read()["revision"] == 0


def test_manifest_absent_failure_returns_only_unknown_batch(workflow, monkeypatch):
  state = workflow
  ids = []
  def failed_begin(store, value):
    ids.append(store.batch_id)
    raise OSError("synthetic-before-manifest-write")
  monkeypatch.setattr(flow.Store, "begin", failed_begin)
  monkeypatch.setattr(dsh_stop_client, "execute_stop", lambda *a, **kw: pytest.fail("stop without manifest"))
  result = flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: True)
  assert result == {"batch_id": ids[0], "scope": {**state.ws.binding, "agent": state.ws.agent},
    "status": "unknown", "stop_status": "unknown", "continue_status": "not_sent"}
  assert len(ids) == 1 and flow.Store(state.ws, ids[0]).read() is None


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_stop_control_interrupt_is_not_hidden(workflow, monkeypatch, error_type):
  state = workflow
  error = error_type("synthetic-interrupt")
  def interrupted(*args, **kwargs):
    raise error
  monkeypatch.setattr(dsh_stop_client, "execute_stop", interrupted)
  with pytest.raises(error_type) as caught:
    flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: True)
  assert caught.value is error


@pytest.mark.parametrize("stop_state", ["unknown", "missing"])
def test_cancel_is_durable_independently_of_stop_cleanup(workflow, monkeypatch, stop_state):
  from agentcfg import run_stop_fence
  state = workflow
  begin(state)
  registry = run_owners.Registry(state.ws.state_root / "run-owners", state.ws.binding)
  fence = registry.root.parent / (registry.root.name + ".stop-fence.json")
  # 未确认的原保护哨兵：不能因后续取消清掉，损坏/孤立保护同样阻挡。
  fence.write_bytes(b"synthetic-original-stop-protection")
  before = fence.read_bytes()
  calls = []
  def inspect(*args, **kwargs):
    calls.append(True)
    assert flow.Store(state.ws, BATCH).read()["events"][-1]["action"] == "cancel"
    if stop_state == "missing":
      raise Conflict("synthetic-first-snapshot-absent")
    return {**state.stop_result, "status": "unknown", "plan_id": state.stop_plan["plan_id"]}
  monkeypatch.setattr(dsh_stop_client, "status_stop", inspect)
  for _ in range(2):
    result = flow.cancel(state.ws, BATCH)
    assert result["cancelled"] and result["stop_status"] == "unknown"
    assert fence.read_bytes() == before
    with registry._locked(nonblocking=True):
      with pytest.raises(Conflict):
        run_stop_fence.assert_unfenced(registry)
  assert [row["action"] for row in flow.Store(state.ws, BATCH).read()["events"]] == ["cancel"]
  with pytest.raises(Conflict):
    execute(state)
  with pytest.raises(Conflict):
    flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda *a, **kw: pytest.fail("cancelled"))
  assert not state.syncs and not state.launches and calls


def test_orphan_manifest_without_first_stop_snapshot_can_cancel_without_dispatch(workflow, monkeypatch):
  state = workflow
  # 绕过 fixture 的合成停止观察，实际 reader 必须发现没有首快照。
  real_status = _STATUS_STOP
  monkeypatch.setattr(dsh_stop_client, "status_stop", real_status)
  sent = []
  def failed_capture(*args, **kwargs):
    sent.append(True)
    raise OSError("synthetic-before-first-stop-snapshot")
  monkeypatch.setattr(dsh_stop_client, "execute_stop", failed_capture)
  result = flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: True)
  batch = result["batch_id"]
  assert result["stop_status"] == "unknown" and flow.Store(state.ws, batch).read()["revision"] == 0
  for _ in range(2):
    cancelled = flow.cancel(state.ws, batch)
    assert cancelled["cancelled"] and cancelled["stop_status"] == "unknown"
  assert [row["action"] for row in flow.Store(state.ws, batch).read()["events"]] == ["cancel"]
  assert sent == [True] and not state.syncs and not state.launches
  with pytest.raises(Conflict):
    flow.execute(state.ws, batch, approve=lambda _: pytest.fail("cancelled setup"),
      progress=Progress(), preview=lambda *a: None)


_HANDOFF_LOCKS = {
  "dsh": "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d",
  "pi": "62ac8348c34339599d280df5769ab0f8383a2f48c0885d84fa16c22a40a6b558",
  "omp": "490e6c90d0ef4d890bb2ab14e006dcd3a3f4d79b5e6ad0ca9fbf3e8f4ab610ab",
}


@pytest.mark.parametrize("agent,damage", [(agent, damage) for agent in ("dsh", "pi", "omp")
  for damage in (None, "runtime", "platform", "source") if damage != "source" or agent == "pi"])
def test_workflow_handoff_requires_exact_public_combination(monkeypatch, agent, damage):
  from agentcfg import pi_session_guard
  from agentcfg.process import DependencyError
  lock = SimpleNamespace(identity=_HANDOFF_LOCKS[agent])
  if damage == "runtime":
    lock.identity = "0" * 64
  monkeypatch.setattr(flow.sys, "platform", "unverified-platform" if damage == "platform" else "linux")
  if damage == "source":
    monkeypatch.setattr(pi_session_guard, "source_identity", lambda: "0" * 64)
  if damage is None:
    _REQUIRE_HANDOFF(SimpleNamespace(agent=agent), lock)
  else:
    with pytest.raises(DependencyError):
      _REQUIRE_HANDOFF(SimpleNamespace(agent=agent), lock)


@pytest.mark.parametrize("stage", ["plan", "stop"])
def test_unadmitted_workflow_fails_before_manifest_approval_or_stop(workflow, monkeypatch, stage):
  from agentcfg.process import DependencyError
  state = workflow
  monkeypatch.setattr(flow, "_require_handoff", _REQUIRE_HANDOFF)
  monkeypatch.setattr(dsh_stop_client, "execute_stop", lambda *a, **kw: pytest.fail("unadmitted stop"))
  with pytest.raises(DependencyError):
    if stage == "plan":
      flow.plan(state.ws, selected_runs=RUNS[:2], sessions=state.mapping)
    else:
      flow.stop(state.ws, expected_plan=state.plan, approve=lambda _: pytest.fail("unadmitted approval"))
  assert not (state.ws.state_root / "maintenance-workflows").exists()
  assert not state.syncs and not state.launches


def test_runtime_lock_changed_after_stop_refuses_setup_before_approval_or_intent(workflow, monkeypatch):
  state = workflow
  begin(state)
  state.lock.identity = "0" * 64
  monkeypatch.setattr(flow, "_require_handoff", _REQUIRE_HANDOFF)
  from agentcfg.process import DependencyError
  with pytest.raises(DependencyError):
    execute(state, approve=lambda _: pytest.fail("unadmitted setup approval"))
  assert flow.status(state.ws, BATCH)["setup"] is None
  assert flow.Store(state.ws, BATCH).read()["events"] == []
  assert not state.syncs and not state.launches
