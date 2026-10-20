"""创建不明、恢复丢标记与已知启动结果登记。"""

import pytest

from termcfg.errors import TermcfgError
from termcfg.herdr import Deadline
from termcfg.work import enter_project
from work_helpers import FakeHerdr


def test_create_applied_but_response_lost_not_retried(tmp_path):
  api = FakeHerdr(deadline=Deadline())
  original = api.request
  def request(method, params=None):
    result = original(method, params)
    if method == "worktree.open": raise TermcfgError(4, "synthetic_lost_response")
    return result
  api.request = request
  ws = enter_project(api, tmp_path)
  assert len(api.workspaces) == 1
  assert sum(m == "worktree.open" for m, _ in api.requests) == 1
  assert all(ws["tokens"]["rw_" + role] == "unknown"
    for role in ("shell", "edit", "build", "debug", "pi", "codex", "dsh"))


def test_cold_restore_never_adopts_old_pane(tmp_path):
  api = FakeHerdr(deadline=Deadline())
  before = enter_project(api, tmp_path)
  api.workspaces[before["workspace_id"]]["tokens"].clear()
  for pane in api.panes.values(): pane["tokens"].clear()
  ws = enter_project(api, tmp_path)
  assert ws["tokens"]["rw_epoch"] != before["tokens"]["rw_epoch"]
  assert ws["tokens"]["rw_shell"] == "unknown"
  assert not next(iter(api.panes.values()))["tokens"]


def test_pending_without_proof_never_cleared(tmp_path):
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  api.workspaces[ws["workspace_id"]]["tokens"]["rw_pending"] = "edit:" + "a" * 32 + ":primary"
  with pytest.raises(TermcfgError) as error: enter_project(api, tmp_path)
  assert error.value.code == 4
  assert "rw_pending" in api.workspaces[ws["workspace_id"]]["tokens"]
  assert len(api.panes) == 1


@pytest.mark.parametrize("phase", ["accepted", "failed"])
def test_final_registration_lost_resolves_only_proven_operation(tmp_path, monkeypatch, phase):
  from termcfg.work import open_role
  from termcfg.work_config import WorkSettings
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a: ["/synthetic/shell"])
  original = api.request
  def request(method, params=None):
    if method == "workspace.report_metadata" and "rw_build" in params["tokens"]:
      raise TermcfgError(4, "synthetic_lost_registration")
    return original(method, params)
  api.request = request
  with pytest.raises(TermcfgError):
    open_role(api, settings, "build", caller_id=next(iter(api.panes)))
  api.request = original
  pane = list(api.panes.values())[-1]
  pane["tokens"]["rw_phase"] = phase
  if phase == "failed": pane["tokens"].pop("rw_commit")
  result = enter_project(api, tmp_path)
  assert "rw_pending" not in result["tokens"]
  assert result["tokens"]["rw_build"].startswith("p:") if phase == "accepted" else result["tokens"]["rw_build"] == "absent"
  assert sum(m == "tab.create" for m, _ in api.requests) == 1
