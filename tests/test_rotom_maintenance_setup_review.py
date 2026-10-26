"""实际 setup 预览接入维护批准；真实临时域和锁，不执行 setup 或宿主。"""
from copy import deepcopy
from types import SimpleNamespace
import base64
import json

import pytest

from agentcfg import commands, deployment, maintenance, maintenance_progress as progress
from agentcfg import maintenance_release as release, maintenance_store as store
from agentcfg import resource_coordination as coordination, resource_owners as owners, run_owners
from agentcfg.storage import Conflict, Tree
from agentcfg.setup_preview import setup_plan_digest
from test_rotom_maintenance import acceptance as metadata_acceptance
from test_rotom_maintenance_live_store import leases_for
from test_rotom_maintenance_recovery import BATCH, RUNS, OPS, ledger, group
from test_rotom_maintenance_release import assert_locks, build_stopped
from test_rotom_resource_owners import IDENTITY, MANAGER, attach, owner_path, reserve
from test_rotom_resource_scopes import workspace, scopes, scope_ids, held_scope
from test_rotom_resource_coordination import locked


@pytest.fixture
def released(tmp_path, monkeypatch, request):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  domain = coordination.initialize_domain(tmp_path / "domain")
  cache = tmp_path / "cache"
  runtime = coordination.enroll_runtime(domain, cache, IDENTITY)
  ws = workspace(tmp_path)
  ws.cache = cache
  anchor = scopes().enroll_scope(domain, ws)
  resources = scope_ids(anchor) | {runtime["resource_id"]}
  runs = RUNS[:getattr(request, "param", 1)]
  rows = []
  for run, op in zip(runs, OPS):
    reserve(domain, ws, sorted(resources), run=run, op=op)
    with held_scope(ws, cache, runtime) as lease:
      attach(domain, lease, run=run)
      owners.dispatch_owner(domain, run, **lease)
    rows.append(SimpleNamespace(workspace=ws, cache=cache, runtime=runtime, resources=resources, run=run))
  case = SimpleNamespace(domain=domain, cache=cache, runtime=runtime, rows=rows)
  acceptance = metadata_acceptance(case, operation="setup", chosen=list(runs))
  content = b"synthetic guarded configuration\n"
  current = {"generation": "d" * 64, "binding": ws.binding,
    "launch": {"lock_identity": IDENTITY, "shared_files": [],
      "adapter_binding": {"identity": {"home": str(ws.instance / "user-home")}},
      "runtime_guards": {"files": ["managed.txt"], "roots": []}},
    "items": {"managed": {"path": "managed.txt", "selector": "", "codec": "bytes",
      "baseline": deployment.encoded({"bytes": base64.b64encode(content).decode(), "mode": 0o600})}}}
  with Tree(ws.instance) as tree:
    tree.write_new("managed.txt", content)
  with Tree(ws.state_root) as tree:
    tree.write_new("deployment.json", deployment.json_bytes({"version": 1, "current": current,
      "previous": None, "owner": {"binding": ws.binding, "shared_files": []}}))
  with leases_for(case, selected=runs) as leases:
    store.accept_stop_snapshot_live(domain, acceptance, leases=leases)
    for run in runs:
      observation = run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True)
      owners.finish_owner(domain, run, observation=observation,
        **{key: value for key, value in leases[run].items() if key != "state_fd"})
  for revision, run in enumerate(runs):
    progress.record_exit(domain, BATCH, expected_revision=revision,
      proof=run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True))
  batch = release.confirm_setup_release(domain, BATCH, expected_revision=len(runs), workspaces={run: ws for run in runs})
  return SimpleNamespace(case=case, workspace=ws, batch=batch)


def make_preview(released, monkeypatch):
  ws = released.workspace
  lock = SimpleNamespace(identity=IDENTITY)
  candidate = SimpleNamespace(generation="e" * 64)
  plan = deployment.Plan(current={"launch": {"runtime_identity": IDENTITY, "lock_identity": IDENTITY},
    "manifest": {"value": "synthetic-private-canary"}}, changes=[], drift=[], conflicts=[])
  args = SimpleNamespace(local=ws.binding["local"], profile=ws.profile)
  calls = []
  def prepared(actual):
    assert actual is args
    calls.append("prepared")
    return ws, lock, candidate
  def current(actual, actual_lock, actual_candidate):
    assert actual is ws and actual_lock is lock and actual_candidate is candidate
    calls.append("plan")
    return plan
  def forbidden(*args, **kwargs):
    pytest.fail("setup side effect is outside this internal seam")
  monkeypatch.setattr(commands, "prepared", prepared)
  monkeypatch.setattr(commands, "current_plan", current)
  for name in ("sync_backend", "apply_candidate", "prepare_launch", "_setup_operation"):
    monkeypatch.setattr(commands, name, forbidden)
  ws.adapter = SimpleNamespace(prepare_setup_resources=forbidden, pre_sync_preflight=forbidden)
  return SimpleNamespace(**vars(released), lock=lock, candidate=candidate, plan=plan, args=args, calls=calls)


@pytest.fixture
def preview(released, monkeypatch):
  return make_preview(released, monkeypatch)


def invoke(value, approve=lambda value: True, *, revision=None):
  from agentcfg.maintenance_setup import review_and_dispatch_setup
  return review_and_dispatch_setup(value.case.domain, BATCH,
    expected_revision=value.batch["revision"] if revision is None else revision, args=value.args, approve=approve)


def test_real_preview_digest_is_reviewed_and_durably_dispatched_without_setup(preview, capsys):
  from agentcfg.maintenance_dispatch import SetupDispatchResult
  from agentcfg.maintenance_permit import BatchPermit
  before = ledger(preview.case.domain)
  digest = setup_plan_digest(preview.workspace, preview.lock, preview.candidate, preview.plan)
  seen = []
  def approve(view):
    assert ledger(preview.case.domain) == before
    assert_locks(preview.case, {RUNS[0]: preview.workspace}, held=False)
    with preview.case.domain._transaction():
      pass
    assert view["setup_preview"] == preview.plan.public()
    assert view["setup_plan_digest"] == digest
    assert "synthetic-private-canary" not in json.dumps(view)
    seen.append(deepcopy(view))
    return True
  result = invoke(preview, approve)
  assert type(result) is SetupDispatchResult and type(result.permit) is BatchPermit
  assert len(seen) == 1 and preview.calls == ["prepared", "plan"]
  assert result.batch == progress.read_batch(preview.case.domain, BATCH)
  assert result.batch["phase"] == "maintenance_dispatch_intent"
  assert result.batch["maintenance_dispatch"]["setup_plan_digest"] == digest
  assert result.permit._used is False
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("decision", [False, None, 1, "yes"])
def test_only_exact_true_approves_and_refusal_has_no_writes(preview, decision):
  before = ledger(preview.case.domain)
  owners_before = owner_path(preview.workspace, RUNS[0]).read_bytes()
  with pytest.raises(Conflict):
    invoke(preview, lambda view: decision)
  assert ledger(preview.case.domain) == before
  assert owner_path(preview.workspace, RUNS[0]).read_bytes() == owners_before
  assert_locks(preview.case, {RUNS[0]: preview.workspace}, held=False)


@pytest.mark.parametrize("error", [ValueError("synthetic-private-canary"), KeyboardInterrupt(), SystemExit(7)])
def test_approval_errors_propagate_unchanged_without_writes(preview, error):
  before = ledger(preview.case.domain)
  def approve(view):
    raise error
  with pytest.raises(type(error)) as caught:
    invoke(preview, approve)
  assert caught.value is error
  assert ledger(preview.case.domain) == before


def test_input_cancellation_propagates_original_input_error(preview):
  from rotom.context import InputError
  error = InputError(130)
  before = ledger(preview.case.domain)
  def approve(view):
    raise error
  with pytest.raises(InputError) as caught:
    invoke(preview, approve)
  assert caught.value is error and caught.value.exit_code == 130
  assert ledger(preview.case.domain) == before


@pytest.mark.parametrize("site", ["prepared", "current_plan"])
@pytest.mark.parametrize("kind", ["config", "conflict", "dependency", "unknown"])
def test_normal_readonly_preparation_retains_original_error_contract(preview, monkeypatch, site, kind):
  from agentcfg.schema import ConfigError
  from agentcfg.process import DependencyError
  error = {"config": ConfigError, "conflict": Conflict, "dependency": DependencyError,
    "unknown": OSError}[kind]("synthetic-private-canary")
  def failed(*args):
    raise error
  monkeypatch.setattr(commands, site, failed)
  before = ledger(preview.case.domain)
  with pytest.raises(type(error)) as caught:
    invoke(preview)
  assert caught.value is error
  assert ledger(preview.case.domain) == before


@pytest.mark.parametrize("change", ["cache", "runtime", "profile", "local", "machine", "instance", "state",
  "missing-local", "empty-local", "missing-profile", "empty-profile", "nonstring-profile", "implicit-profile",
  "agent", "platform", "conflicts", "drift", "runtime-missing"])
def test_mismatched_or_unsafe_target_rejects_before_approval_and_without_other_instance_reads(preview, monkeypatch, change, capsys):
  from agentcfg import maintenance_dispatch, maintenance_setup
  from pathlib import Path
  ws = preview.workspace
  if change == "cache": ws.cache = ws.cache.parent / "other-private-canary-cache"
  elif change == "runtime": preview.plan.current["launch"]["runtime_identity"] = "f" * 64
  elif change in ("profile", "local", "machine"):
    ws.binding = {**ws.binding, change: "other-private-canary"}
    if change == "profile": ws.profile = preview.args.profile = ws.binding["profile"]
  elif change == "instance": ws.instance = ws.instance.parent / "other-private-canary-instance"
  elif change == "state": ws.state_root = ws.state_root.parent / "other-private-canary-state"
  elif change in ("missing-local", "empty-local"): preview.args.local = None if change == "missing-local" else ""
  elif change in ("missing-profile", "empty-profile", "nonstring-profile"):
    preview.args.profile = {"missing-profile": None, "empty-profile": "", "nonstring-profile": Path("omp-a")}[change]
  elif change == "implicit-profile": preview.args.profile = "other"
  elif change == "agent": ws.agent = "dsh"
  elif change == "platform": monkeypatch.setattr(maintenance_setup.sys, "platform", "darwin")
  elif change in ("conflicts", "drift"): getattr(preview.plan, change).append('["private-canary", ""]')
  else: preview.plan.current["launch"] = {}
  before = ledger(preview.case.domain)
  def forbidden(*args, **kwargs):
    pytest.fail("inadmissible preview must not approve or acquire physical resources")
  monkeypatch.setattr(maintenance_dispatch, "record_setup_dispatch", forbidden)
  # 准入只读协调表与接受记录，不能根据旧路径打开任何实例或运行包。
  original = Tree.__enter__
  opened = []
  def enter(tree):
    opened.append(tree.root)
    assert tree.root == preview.case.domain.root
    return original(tree)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "__enter__", enter)
    with pytest.raises(Conflict) as caught:
      invoke(preview, forbidden)
  assert "canary" not in str(caught.value)
  assert all(path == preview.case.domain.root for path in opened)
  assert ledger(preview.case.domain) == before
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("revision", [True, -1, 1, 3])
def test_stale_revision_rejects_before_approval(preview, revision):
  before = ledger(preview.case.domain)
  with pytest.raises(Conflict):
    invoke(preview, lambda view: pytest.fail("stale approval"), revision=revision)
  assert ledger(preview.case.domain) == before


def test_runtime_identity_falls_back_to_launch_lock_identity(preview):
  del preview.plan.current["launch"]["runtime_identity"]
  assert invoke(preview).batch["phase"] == "maintenance_dispatch_intent"


def test_path_local_is_supported_and_detached_callback_cannot_redirect_digest_or_summary(preview):
  from pathlib import Path
  preview.args.local = Path(preview.args.local)
  digest = setup_plan_digest(preview.workspace, preview.lock, preview.candidate, preview.plan)
  original_public = preview.plan.public()
  preview.plan.public = lambda: original_public
  def approve(view):
    assert view["setup_preview"] == original_public
    view["batch"]["revision"] += 99
    view["setup_plan_digest"] = "f" * 64
    view["setup_preview"]["changes"] = 99
    original_public["changes"] = 100
    preview.plan.current["manifest"]["value"] = "changed-after-review"
    return True
  result = invoke(preview, approve)
  assert result.batch["revision"] == 3
  assert result.batch["maintenance_dispatch"]["setup_plan_digest"] == digest


@pytest.mark.parametrize("change", ["batch", "deployment", "owner"])
def test_approval_time_change_is_rejected_by_original_transaction(preview, change):
  before = ledger(preview.case.domain)
  changed = []
  def approve(view):
    if change == "batch":
      with preview.case.domain._transaction(write=True) as state:
        state["intents"][BATCH]["progress"]["revision"] += 1
    elif change == "deployment":
      (preview.workspace.instance / "managed.txt").write_bytes(b"synthetic-private-canary")
    else:
      record = json.loads(owner_path(preview.workspace, RUNS[0]).read_bytes())
      run_owners._set_state(record, "unknown")
      with Tree(preview.workspace.state_root / "run-owners") as tree:
        tree.write_state(RUNS[0] + ".json", run_owners._encode(record))
    changed.append(ledger(preview.case.domain))
    return True
  with pytest.raises(Conflict) as caught:
    invoke(preview, approve)
  assert "canary" not in str(caught.value)
  assert ledger(preview.case.domain) == changed[0]
  assert (before != changed[0]) is (change == "batch")
  assert progress.read_batch(preview.case.domain, BATCH)["maintenance_dispatch"]["state"] == "not_dispatched"
  assert_locks(preview.case, {RUNS[0]: preview.workspace}, held=False)


def test_lost_commit_reply_never_retries_or_issues_permit(preview, monkeypatch):
  from agentcfg import maintenance_permit
  original = Tree.replace
  calls = []
  def replace(tree, name, data, *args, **kwargs):
    result = original(tree, name, data, *args, **kwargs)
    if name == "coordination.json":
      calls.append(name)
      raise OSError("synthetic-private-canary")
    return result
  monkeypatch.setattr(maintenance_permit, "_issue_batch_permit", lambda *args, **kwargs: pytest.fail("lost response issued permit"))
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replace)
    with pytest.raises(Conflict) as caught:
      invoke(preview)
  assert "canary" not in str(caught.value) and calls == ["coordination.json"]
  saved = progress.read_batch(preview.case.domain, BATCH)
  assert saved["phase"] == "maintenance_dispatch_intent"
  before = ledger(preview.case.domain)
  with pytest.raises(Conflict):
    invoke(preview, revision=saved["revision"])
  assert ledger(preview.case.domain) == before


def test_dispatch_still_blocks_ordinary_guards_and_keeps_all_protection(preview):
  from agentcfg.omp_identity import lifecycle_guard
  before = preview.case.domain.snapshot()
  owner_before = owner_path(preview.workspace, RUNS[0]).read_bytes()
  invoke(preview)
  after = preview.case.domain.snapshot()
  assert after["reservations"] == before["reservations"]
  assert owner_path(preview.workspace, RUNS[0]).read_bytes() == owner_before
  with pytest.raises(Conflict), lifecycle_guard(preview.workspace):
    pass
  with locked(preview.case.cache, IDENTITY, exclusive=True) as fd, pytest.raises(Conflict):
    preview.case.domain.check_runtime(preview.case.cache, IDENTITY, lease_fd=fd, idle=True)
  with pytest.raises(Conflict):
    preview.case.domain.cancel_intent(BATCH)


@pytest.mark.parametrize("released", [2], indirect=True)
def test_multiple_runs_of_exact_same_scope_map_to_one_current_workspace(preview):
  result = invoke(preview)
  assert result.batch["accepted_runs"] == list(RUNS[:2])
  assert result.batch["phase"] == "maintenance_dispatch_intent"
  # 多 run 共用同一物理 scope，只对唯一锁做一次独立排他探测。
  assert_locks(preview.case, {RUNS[0]: preview.workspace}, held=False)


def test_multi_scope_batch_rejects_instead_of_silently_selecting_one_profile(group, monkeypatch):
  case, workspaces = build_stopped(group)
  batch = release.confirm_setup_release(case.domain, BATCH, expected_revision=2, workspaces=workspaces)
  value = make_preview(SimpleNamespace(case=case, workspace=workspaces[RUNS[0]], batch=batch), monkeypatch)
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    invoke(value, lambda view: pytest.fail("cannot approve a subset of the batch"))
  assert ledger(case.domain) == before


@pytest.mark.parametrize("change", ["instance-path", "home-path", "runtime-cache", "runtime-version", "resource-key", "resource-id"])
def test_resource_catalog_binding_is_checked_before_approval(preview, change):
  from agentcfg.resource_keys import ResourceKey
  state = preview.case.domain.snapshot()
  selected = [state["resources"][rid] for rid in state["reservations"][RUNS[0]]["resources"]]
  by_kind = {item["key"]["kind"]: item for item in selected}
  if change == "instance-path": by_kind["instance"]["path"] = "/synthetic/private-canary"
  elif change == "home-path": by_kind["native-home"]["path"] = "/synthetic/private-canary"
  elif change == "runtime-cache": by_kind["runtime"]["cache"] = "/synthetic/private-canary"
  elif change == "runtime-version": by_kind["runtime"]["runtime_identity"] = "f" * 64
  elif change == "resource-key":
    old = by_kind["runtime"]["key"]
    by_kind["runtime"]["key"] = ResourceKey(old["kind"], old["device"], old["inode"] + 1).as_dict()
  else:
    by_kind["runtime"]["resource_id"] = "f" * 32
  # 损坏 ID 本身不能经正常编码事务发布；此处模拟落盘目录表损坏。
  with Tree(preview.case.domain.root) as tree:
    tree.write_state("coordination.json", deployment.json_bytes(state))
  before = ledger(preview.case.domain)
  with pytest.raises(Conflict) as caught:
    invoke(preview, lambda view: pytest.fail("catalog mismatch cannot approve"))
  assert "canary" not in str(caught.value)
  assert ledger(preview.case.domain) == before
