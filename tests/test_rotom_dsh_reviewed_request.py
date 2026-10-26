"""真实临时受理快照与 manager 核验组合；不运行第三方宿主。"""
import pytest

from agentcfg import dsh_stop_scope, dsh_stop_completion
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_stop_completion import accepted, request
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


def inspect(accepted, monkeypatch):
  ws, registry, args, runs, plan = accepted
  monkeypatch.setattr(dsh_stop_scope.time, "monotonic_ns", lambda: 1)
  return dsh_stop_scope.inspect_stop_request(ws, request(accepted), instance_fd=args["instance_fd"],
    state_fd=args["state_fd"], expected_layout=args["expected_layout"], require_reviewed_stop=True)


def test_reviewed_plan_and_original_active_record_are_accepted(accepted, monkeypatch):
  result = inspect(accepted, monkeypatch)
  assert result == accepted[1].snapshot()[accepted[3][0]]


def test_close_saved_before_failed_fence_delete_blocks_manager(accepted, monkeypatch):
  ws, registry, args, runs, plan = accepted
  real = Tree.replace
  def fail(tree, name, content, **kw):
    if content is None: raise OSError("synthetic-delete-failure")
    return real(tree, name, content, **kw)
  monkeypatch.setattr(Tree, "replace", fail)
  with pytest.raises(Conflict):
    dsh_stop_completion.close_stop(ws, batch_id=args["batch_id"], plan_id=plan["plan_id"], reason="cancelled")
  with pytest.raises(Conflict): inspect(accepted, monkeypatch)
