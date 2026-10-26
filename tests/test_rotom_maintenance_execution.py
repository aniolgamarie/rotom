"""维护执行的真实临时门禁组合；合成产物和运行包状态，不启动宿主或联网。"""
from contextlib import contextmanager, ExitStack, nullcontext
from copy import deepcopy
from types import SimpleNamespace
import fcntl
import hashlib
import json
import os

import pytest

from agentcfg import commands, deployment, maintenance_execution as execution, maintenance_progress as progress
from agentcfg import maintenance_release as release, maintenance_setup, maintenance_store as store
from agentcfg import publication, resource_coordination as coordination, resource_owners as owners, run_owners
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.omp import OmpAdapter
from agentcfg.omp_dependencies import OmpBackend
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree, instance_lock
from test_rotom_maintenance import acceptance as metadata_acceptance
from test_rotom_maintenance_recovery import BATCH, RUNS, OPS, ledger
from test_rotom_resource_owners import MANAGER, metadata, owner_path, reserve
from test_rotom_resource_scopes import scopes, scope_ids


def candidate(generation, text):
  target = ManagedTarget("managed.txt", Ownership.FILE, "bytes")
  return RenderCandidate(generation, (Artifact(target, text),))


@contextmanager
def leases(case):
  ws = case.workspace
  with ExitStack() as stack:
    instance_fd = stack.enter_context(_shared_file(ws.instance, ".agentcfg-omp.lock"))
    home = stack.enter_context(Tree(ws.instance / "user-home"))
    state_fd = stack.enter_context(_shared_file(ws.state_root, "instance.lock"))
    package = stack.enter_context(_shared_file(ws.cache, "leases/" + case.identity + ".lock"))
    yield {row.run: {"workspace": ws, "instance_fd": instance_fd, "native_home_fd": home.fd,
      "state_fd": state_fd, "runtime_fds": {case.runtime["resource_id"]: package}} for row in case.rows}


def probe(path, mode, *, blocked):
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  try:
    if blocked:
      with pytest.raises(BlockingIOError): fcntl.flock(fd, mode | fcntl.LOCK_NB)
    else:
      fcntl.flock(fd, mode | fcntl.LOCK_NB)
  finally:
    os.close(fd)


def assert_body_locks(case, *, stage):
  ws = case.workspace
  probe(ws.instance / ".agentcfg-omp.lock", fcntl.LOCK_SH, blocked=True)
  probe(ws.state_root / "instance.lock", fcntl.LOCK_SH, blocked=stage == "apply")
  probe(ws.state_root / "instance.lock", fcntl.LOCK_EX, blocked=True)
  package = ws.cache / "leases" / (case.identity + ".lock")
  probe(package, fcntl.LOCK_SH, blocked=stage == "sync")
  probe(package, fcntl.LOCK_EX, blocked=True)
  for root in (case.domain.root, ws.state_root / "run-owners"):
    with Tree(root) as tree:
      fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.fixture
def case(tmp_path, monkeypatch, request):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  domain = coordination.initialize_domain(tmp_path / "lifecycle")
  lock = SimpleNamespace(identity="c" * 64)
  events = []
  class Backend(OmpBackend):
    def read_lock(self, repository): return lock
    def _permission_runtime(self, workspace, actual): return None
    def status(self, workspace, identity): return "installed"
    def _recover_activation(self, workspace, actual, identity):
      events.append("sync-body")
      assert value.dispatch.permit._used is True
      assert progress.read_batch(domain, BATCH)["phase"] == "maintenance_running"
      assert_body_locks(value, stage="sync")
      if value.sync_hook is not None: value.sync_hook()
  backend = Backend()
  repository = tmp_path / "repository"
  repository.mkdir(mode=0o700)
  ws = SimpleNamespace(agent="omp", profile="omp-synthetic", instance=tmp_path / "instances/omp-synthetic",
    state_root=tmp_path / "omp/omp-synthetic", cache=tmp_path / "cache", repository=repository,
    binding={"machine": "synthetic", "local": str(tmp_path / "local.toml"), "profile": "omp-synthetic"},
    resolved=SimpleNamespace(data={"machine": {"paths": {"state_root": str(tmp_path)}},
      "profile": {"agent_options": {}}}), backend=backend)
  identity = backend.runtime_identity(ws, lock)
  runtime = coordination.enroll_runtime(domain, ws.cache, identity)
  anchor = scopes().enroll_scope(domain, ws)
  resources = scope_ids(anchor) | {runtime["resource_id"]}
  selected_runs = RUNS[:getattr(request, "param", 1)]
  for run, op in zip(selected_runs, OPS):
    reserve(domain, ws, sorted(resources), run=run, op=op)
  launch = {"lock_identity": lock.identity, "runtime_identity": identity, "shared_files": [],
    "adapter_binding": {"identity": {"home": str(ws.instance / "user-home")}},
    "runtime_guards": {"files": ["managed.txt"], "roots": []}}
  deployment.apply(ws.instance, ws.state_root, candidate("d" * 64, b"old\n"), ws.binding, launch)
  value = SimpleNamespace(domain=domain, workspace=ws, cache=ws.cache, runtime=runtime, identity=identity,
    rows=[SimpleNamespace(workspace=ws, run=run, resources=resources) for run in selected_runs],
    lock=lock, launch=launch, proposed=candidate("e" * 64, b"new\n"), events=events,
    sync_hook=None, apply_hook=None)
  with leases(value) as selected:
    lease = {key: child for key, child in selected[RUNS[0]].items() if key != "state_fd"}
    supplied = metadata(ws)
    supplied["deployed_identity"]["runtime"] = hashlib.sha256(identity.encode()).hexdigest()
    for run in selected_runs:
      owners.attach_owner(domain, run, manager_identity=MANAGER, metadata=supplied, **lease)
      owners.dispatch_owner(domain, run, **lease)
  acceptance = metadata_acceptance(value, operation="setup", chosen=selected_runs)
  with leases(value) as selected:
    store.accept_stop_snapshot_live(domain, acceptance, leases=selected)
    observations = [run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True) for run in selected_runs]
    for observation in observations:
      owners.finish_owner(domain, observation.run_id, observation=observation,
        **{key: child for key, child in selected[observation.run_id].items() if key != "state_fd"})
  for revision, observation in enumerate(observations):
    progress.record_exit(domain, BATCH, expected_revision=revision, proof=observation)
  batch = release.confirm_setup_release(domain, BATCH, expected_revision=len(observations),
    workspaces={run: ws for run in selected_runs})
  adapter = OmpAdapter(repository)
  adapter.validate_deployment_state = lambda saved: None
  original_prepare = adapter.prepare_runtime
  def prepare_runtime(workspace, root):
    events.append("apply-body")
    assert_body_locks(value, stage="apply")
    if value.apply_hook is not None: value.apply_hook()
    original_prepare(workspace, root)
  adapter.prepare_runtime = prepare_runtime
  ws.adapter = adapter
  args = SimpleNamespace(local=ws.binding["local"], profile=ws.profile, agent="omp", command="setup")
  monkeypatch.setattr(commands, "prepared", lambda actual: (ws, lock, value.proposed))
  monkeypatch.setattr(commands.runtime, "record", lambda *args: deepcopy(value.launch))
  monkeypatch.setattr(publication, "reader_lease", lambda *args: nullcontext())
  class Progress:
    def stage(self, *args, **kwargs): pass
    def sync_stage(self, *args): pass
    def heartbeat(self): return nullcontext()
  value.args, value.progress, value.batch = args, Progress(), batch
  value.dispatch = maintenance_setup.review_and_dispatch_setup(domain, BATCH,
    expected_revision=batch["revision"], args=args, approve=lambda view: True)
  return value


def execute(case):
  return execution.execute_setup(case.domain, case.dispatch, args=case.args,
    progress=case.progress, preview=lambda *args: None)


def test_real_setup_updates_managed_file_under_original_physical_guards(case):
  before = case.domain.snapshot()
  owner = owner_path(case.workspace, RUNS[0]).read_bytes()
  result = execute(case)
  assert type(result) is execution.SetupExecutionResult
  assert result.operation.code == 0 and result.batch["phase"] == "maintenance_succeeded"
  assert result.batch["operation_result"]["status"] == "succeeded"
  assert len(result.batch["operation_result"]["result_digest"]) == 64
  assert case.dispatch.permit._used is True
  assert (case.workspace.instance / "managed.txt").read_bytes() == b"new\n"
  assert case.events == ["sync-body", "apply-body", "apply-body"]
  assert case.domain.snapshot()["reservations"] == before["reservations"]
  assert owner_path(case.workspace, RUNS[0]).read_bytes() == owner
  assert case.domain.snapshot()["intents"][BATCH]["phase"] == before["intents"][BATCH]["phase"]
  with pytest.raises(Conflict): execute(case)
  assert case.events == ["sync-body", "apply-body", "apply-body"]


@pytest.mark.parametrize("kind", ["json", "permit", "boolean", "exception"])
def test_untrusted_values_cannot_supply_dispatch(case, kind):
  supplied = {"json": deepcopy(case.dispatch.batch), "permit": case.dispatch.permit,
    "boolean": True, "exception": Conflict("synthetic")}[kind]
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    execution.execute_setup(case.domain, supplied, args=case.args,
      progress=case.progress, preview=lambda *args: None)
  assert ledger(case.domain) == before and case.events == []
  assert case.dispatch.permit._used is False


def change_evidence(case, change):
  if change == "source":
    case.proposed = candidate("f" * 64, b"changed\n")
  elif change == "deployment":
    (case.workspace.instance / "managed.txt").write_bytes(b"changed\n")
  elif change == "owner":
    path = owner_path(case.workspace, RUNS[0])
    record = json.loads(path.read_bytes())
    run_owners._set_state(record, "unknown")
    with Tree(path.parent) as tree:
      tree.write_state(path.name, run_owners._encode(record))
  else:
    with case.domain._transaction(write=True) as state:
      if change == "cas":
        state["intents"][BATCH]["progress"]["revision"] += 1
      elif change == "unknown":
        state["reservations"][RUNS[0]]["phase"] = "unknown"
      elif change == "intent":
        other = deepcopy(state["intents"][BATCH])
        other["batch_id"] = "8" * 32
        other.pop("progress", None)
        other.pop("acceptance", None)
        state["intents"]["8" * 32] = other
      elif change == "resources":
        state["resources"][case.runtime["resource_id"]]["runtime_identity"] = "f" * 64


@pytest.mark.parametrize("change", ["source", "deployment", "resources"])
def test_initial_plan_change_never_enters_sync(case, change):
  change_evidence(case, change)
  before = ledger(case.domain)
  if change == "deployment":
    assert execute(case).operation.code == 4
  else:
    with pytest.raises(Conflict): execute(case)
  assert case.events == [] and ledger(case.domain) == before
  assert case.dispatch.permit._used is False


@pytest.mark.parametrize("stage", ["preflight", "prepare"])
def test_original_adapter_hooks_cannot_skip_execution_stages(case, stage):
  permit = execution._Execution(execution._TOKEN, case.domain, case.dispatch, case.args)
  if stage == "prepare":
    permit.approve(case.workspace, case.lock, case.proposed,
      commands.current_plan(case.workspace, case.lock, case.proposed))
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    if stage == "preflight":
      case.workspace.adapter.pre_sync_preflight(case.workspace, maintenance=permit)
    else:
      case.workspace.adapter.prepare_setup_resources(case.workspace, case.lock, maintenance=permit)
  assert case.events == [] and ledger(case.domain) == before
  assert case.dispatch.permit._used is False


@pytest.mark.parametrize("change", ["source", "owner", "cas", "unknown", "intent", "shared-unknown", "instance-sh", "package-sh"])
def test_sync_entry_rechecks_live_evidence_before_consuming(case, monkeypatch, change):
  original = commands.sync_backend
  snapshots = []
  def sync(*args, **kwargs):
    with ExitStack() as stack:
      if change.endswith("-sh"):
        root, name = ((case.workspace.instance, ".agentcfg-omp.lock") if change == "instance-sh"
          else (case.workspace.cache, "leases/" + case.identity + ".lock"))
        stack.enter_context(_shared_file(root, name))
      else:
        if change == "shared-unknown":
          with case.domain._transaction(write=True) as state:
            other = deepcopy(state["reservations"][RUNS[0]])
            other.update(run_id=RUNS[2], op_id=OPS[2], phase="unknown",
              resources=[case.runtime["resource_id"]])
            other.pop("owner_link", None)
            other.pop("release_receipt", None)
            state["reservations"][RUNS[2]] = other
        else:
          change_evidence(case, change)
      snapshots.append(ledger(case.domain))
      return original(*args, **kwargs)
  monkeypatch.setattr(commands, "sync_backend", sync)
  owner_before = owner_path(case.workspace, RUNS[0]).read_bytes()
  with pytest.raises(Conflict): execute(case)
  assert len(snapshots) == 1 and ledger(case.domain) == snapshots[0]
  assert case.events == [] and case.dispatch.permit._used is False
  if change != "owner":
    assert owner_path(case.workspace, RUNS[0]).read_bytes() == owner_before


@pytest.mark.parametrize("after", [False, True])
def test_running_commit_failure_never_runs_body_or_reissues_permit(case, monkeypatch, capsys, after):
  original, writes = Tree.replace, []
  failure = OSError("synthetic-private-canary")
  def commit(tree, name, data, *args, **kwargs):
    if name != "coordination.json": return original(tree, name, data, *args, **kwargs)
    writes.append(json.loads(data))
    probe(case.workspace.instance / ".agentcfg-omp.lock", fcntl.LOCK_SH, blocked=True)
    probe(case.workspace.cache / "leases" / (case.identity + ".lock"), fcntl.LOCK_SH, blocked=True)
    with Tree(case.workspace.state_root / "run-owners") as owner:
      with pytest.raises(BlockingIOError): fcntl.flock(owner.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not after: raise failure
    original(tree, name, data, *args, **kwargs)
    raise failure
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", commit)
    with pytest.raises(Conflict): execute(case)
  assert len(writes) == 1 and case.events == [] and case.dispatch.permit._used is True
  assert progress.read_batch(case.domain, BATCH)["phase"] == (
    "maintenance_running" if after else "maintenance_dispatch_intent")
  assert "准入记账未确认" in capsys.readouterr().err
  before = ledger(case.domain)
  with pytest.raises(Conflict): execute(case)
  assert ledger(case.domain) == before and case.events == []


@pytest.mark.parametrize("stage", ["sync", "apply"])
@pytest.mark.parametrize("kind", ["error", "interrupt"])
def test_body_exception_is_preserved_and_records_unknown(case, stage, kind):
  failure = RuntimeError("synthetic-private-canary") if kind == "error" else KeyboardInterrupt()
  raised = []
  def fail():
    if not raised:
      raised.append(True)
      raise failure
  setattr(case, stage + "_hook", fail)
  before = case.domain.snapshot()
  with pytest.raises(type(failure)) as caught: execute(case)
  assert caught.value is failure
  saved = progress.read_batch(case.domain, BATCH)
  assert saved["phase"] == "unknown" and saved["operation_result"]["status"] == "unknown"
  intent = case.domain.snapshot()["intents"][BATCH]
  assert intent["phase"] == "unknown"
  assert {key: value for key, value in intent.items() if key not in ("phase", "progress")} == {
    key: value for key, value in before["intents"][BATCH].items() if key not in ("phase", "progress")}
  assert case.domain.snapshot()["reservations"] == before["reservations"]
  # 部署自己的恢复流程再次准备旧启动资源，仍在同一次 apply 和原物理门禁内。
  assert case.events == (["sync-body"] if stage == "sync" else ["sync-body", "apply-body", "apply-body"])
  assert (case.workspace.instance / "managed.txt").read_bytes() == b"old\n"
  before_retry = ledger(case.domain)
  with pytest.raises(Conflict): execute(case)
  assert ledger(case.domain) == before_retry


def test_unknown_accounting_failure_does_not_replace_original_interrupt(case, monkeypatch, capsys):
  original, writes = Tree.replace, []
  failure = KeyboardInterrupt()
  def fail(): raise failure
  case.sync_hook = fail
  def commit(tree, name, data, *args, **kwargs):
    if name == "coordination.json":
      writes.append(json.loads(data))
      if len(writes) == 2: raise OSError("synthetic-accounting-failure")
    return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", commit)
  with pytest.raises(KeyboardInterrupt) as caught: execute(case)
  assert caught.value is failure and len(writes) == 2
  assert progress.read_batch(case.domain, BATCH)["phase"] == "maintenance_running"
  assert "结果记账未确认" in capsys.readouterr().err


def test_post_sync_plan_change_returns_original_partial_result(case, monkeypatch):
  case.sync_hook = lambda: change_evidence(case, "source")
  original, outcomes = commands._setup_operation, []
  def operation(*args, **kwargs):
    outcome = original(*args, **kwargs)
    outcomes.append(outcome)
    return outcome
  monkeypatch.setattr(commands, "_setup_operation", operation)
  result = execute(case)
  assert result.operation is outcomes[0] and result.operation.code == 4
  assert result.batch["phase"] == "partial" and result.batch["operation_result"]["exit_code"] == 4
  assert case.domain.snapshot()["intents"][BATCH]["phase"] == "unknown"
  assert case.events == ["sync-body"]
  assert (case.workspace.instance / "managed.txt").read_bytes() == b"old\n"


@pytest.mark.parametrize("change", ["deployment", "owner", "resources"])
def test_apply_entry_rechecks_live_evidence_and_preserves_protection(case, monkeypatch, change):
  original = commands.apply_candidate
  protected = []
  def apply(*args, **kwargs):
    change_evidence(case, change)
    protected.append((case.domain.snapshot()["reservations"], owner_path(case.workspace, RUNS[0]).read_bytes(),
      (case.workspace.instance / "managed.txt").read_bytes()))
    return original(*args, **kwargs)
  monkeypatch.setattr(commands, "apply_candidate", apply)
  with pytest.raises(Conflict): execute(case)
  assert case.events == ["sync-body"] and len(protected) == 1
  assert case.domain.snapshot()["reservations"] == protected[0][0]
  assert owner_path(case.workspace, RUNS[0]).read_bytes() == protected[0][1]
  assert (case.workspace.instance / "managed.txt").read_bytes() == protected[0][2]
  assert progress.read_batch(case.domain, BATCH)["phase"] == "unknown"


def test_completion_response_loss_does_not_replay_or_clear_ordinary_guards(case, monkeypatch):
  original, writes = Tree.replace, []
  failure = OSError("synthetic-response-loss")
  def commit(tree, name, data, *args, **kwargs):
    value = original(tree, name, data, *args, **kwargs)
    if name == "coordination.json":
      writes.append(json.loads(data))
      if len(writes) == 2: raise failure
    return value
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", commit)
    with pytest.raises(Conflict): execute(case)
  assert len(writes) == 2
  assert progress.read_batch(case.domain, BATCH)["phase"] == "maintenance_succeeded"
  before, events = ledger(case.domain), list(case.events)
  with pytest.raises(Conflict): execute(case)
  with pytest.raises(Conflict): case.workspace.backend.sync(case.workspace, case.lock)
  with pytest.raises(Conflict):
    commands.apply_candidate(case.workspace, case.lock, case.proposed)
  assert ledger(case.domain) == before and case.events == events


@pytest.mark.parametrize("case", [2], indirect=True)
def test_two_released_runs_in_one_scope_execute_setup_once(case):
  owners_before = {row.run: owner_path(row.workspace, row.run).read_bytes() for row in case.rows}
  before = case.domain.snapshot()
  result = execute(case)
  assert result.operation.code == 0 and result.batch["phase"] == "maintenance_succeeded"
  assert result.batch["accepted_runs"] == list(RUNS[:2])
  assert case.events == ["sync-body", "apply-body", "apply-body"]
  assert case.domain.snapshot()["reservations"] == before["reservations"]
  assert {row.run: owner_path(row.workspace, row.run).read_bytes() for row in case.rows} == owners_before
