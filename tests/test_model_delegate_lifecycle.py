"""V2 单 run 生命周期只调用进程替身，ready 未确认不能重发或解除写保护。"""

from copy import deepcopy
import pytest

from agentcfg.model_delegate import DelegationRuns, cursor
from agentcfg.storage import Conflict
from test_model_delegate_contract import request, receipt, proof


def test_start_unknown_is_durable_idempotent_and_cannot_automatically_resend(tmp_path):
  runs = DelegationRuns(tmp_path / "runs")
  value = request()
  calls = []
  def start(saved):
    calls.append(saved)
    raise TimeoutError("private backend error")
  assert runs.start(value, start)["state"] == "start_unknown"
  assert DelegationRuns(tmp_path / "runs").start(value, start)["state"] == "start_unknown"
  assert len(calls) == 1
  with pytest.raises(Conflict):
    runs.start({**value, "request_digest": "a" * 64}, start)
  assert "private backend error" not in str(runs.status(value["run_id"]))


def test_ready_identity_cancel_acceptance_and_timeout_do_not_fake_termination(tmp_path):
  runs = DelegationRuns(tmp_path / "runs"),
  runs = runs[0]
  value = request()
  ready = {"ready": True, "run_id": value["run_id"], "lease_id": "lease", "request_digest": value["request_digest"]}
  assert runs.start(value, lambda _: ready)["state"] == "running"
  assert runs.cancel(value["run_id"], lambda _: {"accepted": True})["termination_confirmed"] is False
  assert runs.status(value["run_id"])["state"] == "running"
  assert runs.wait(value["run_id"], 0)["timed_out"] is True
  assert runs.status(value["run_id"])["state"] == "running"


def test_semantic_cursor_ignores_heartbeat_and_terminal_commit_is_compare_and_swap(tmp_path):
  runs = DelegationRuns(tmp_path / "runs")
  value = request()
  runs.start(value, lambda _: {"ready": True, "run_id": value["run_id"], "lease_id": "lease", "request_digest": value["request_digest"]})
  event = {"schema_version": 2, "run_id": value["run_id"], "seq": 1, "timestamp": "2026-09-17T00:00:00Z", "kind": "checkpoint", "phase": "turn-completed", "artifact_id": None}
  runs.event(value["run_id"], event)
  assert runs.poll(value["run_id"], cursor(value["run_id"], 0))["next_cursor"] == cursor(value["run_id"], 1)
  assert runs.poll(value["run_id"], cursor(value["run_id"], 1))["events"] == []
  runs.finish(value["run_id"], receipt(value), proof())
  assert runs.wait(value["run_id"], 0)["timed_out"] is False
  changed = receipt(value); changed["terminal_status"] = "failed"
  with pytest.raises(Conflict): runs.finish(value["run_id"], changed, proof())


def test_resume_is_explicit_new_run_after_proven_old_termination(tmp_path):
  runs = DelegationRuns(tmp_path / "runs")
  value = request(); runs.start(value, lambda _: {})
  following = {**value, "run_id": "new-run", "attempt_id": "new-attempt", "lease_id": "new-lease", "continuation_of": value["run_id"]}
  with pytest.raises(Conflict): runs.check_resume(value["run_id"], following, {**proof(), "termination_verified": False}, user_authorized=True)
  with pytest.raises(Conflict): runs.check_resume(value["run_id"], following, proof(), user_authorized=False)
  runs.check_resume(value["run_id"], following, proof(), user_authorized=True)
  with pytest.raises(Conflict): runs.check_resume(value["run_id"], {**following, "cwd": "/other"}, proof(), user_authorized=True)


def test_codex_write_requires_all_explicit_controls_and_independent_linked_worktree(tmp_path):
  from agentcfg.model_delegate import write_workspace
  from agentcfg.workspace_leases import WorkspaceLeases
  from agentcfg.schema import ConfigError
  from test_pi_workspace_leases import worktree
  manager = WorkspaceLeases("fixture-boot")
  source = worktree(tmp_path, "source")
  root = tmp_path / "candidate"; root.mkdir()
  gitdir = source / ".git/worktrees/candidate"; gitdir.mkdir(parents=True)
  (root / ".git").write_text("gitdir: " + str(gitdir) + "\n")
  (gitdir / "gitdir").write_text(str(root / ".git") + "\n")
  (gitdir / "commondir").write_text("../..\n")
  (gitdir / "HEAD").write_text("a" * 40 + "\n")
  args = {"backend": "codex", "mode": "implement", "configured_mode": "explicit-write", "allow_workspace_write": True,
    "worktree_root": str(root), "cwd": str(root), "user_authorized": True}
  assert write_workspace(manager, **args)[0]["worktree_path"] == str(root)
  for change in ({"backend": "pi"}, {"configured_mode": "readonly"}, {"allow_workspace_write": False},
      {"worktree_root": None}, {"user_authorized": False}, {"cwd": str(source)}, {"worktree_root": str(source), "cwd": str(source)}):
    with pytest.raises((ConfigError, Conflict)):
      write_workspace(manager, **{**args, **change})


def test_explicit_write_uses_same_cross_instance_allocation_transaction(tmp_path):
  from agentcfg.activity import ExecutionStore
  from agentcfg.workspace_leases import WorkspaceLeases
  from test_pi_activity import make_store
  from test_pi_workspace_leases import worktree
  first, processes = make_store(tmp_path / "first")
  second, _ = make_store(tmp_path / "second")
  first.workspaces = WorkspaceLeases("fixture-boot"); second.workspaces = WorkspaceLeases("fixture-boot")
  root = worktree(tmp_path, "candidate")
  planned = first.workspaces.identify(root)
  common = {"task_id": None, "lock_identity": "a" * 64, "slice_identity": "b" * 64, "policy_digest": "c" * 64,
    "candidate_digest": "d" * 64, "planned_workspaces": [planned]}
  lease = first.allocate(kind="worker", execution_id="managed", attempt_id="first", **common)
  with pytest.raises(Conflict):
    second.allocate(kind="codex", execution_id="delegate", attempt_id="second", **common)
  assert first.read(lease["lease_id"])["state"] == "allocating"
  assert first.workspaces.read(planned)["state"] == "reserved"
