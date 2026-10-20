"""复用零输入，新增不替换，关闭与清标记分别处理。"""

import pytest

from termcfg.errors import TermcfgError
from termcfg.herdr import Deadline
from termcfg.work import enter_project, open_role
from termcfg.work_config import WorkSettings
from work_helpers import FakeHerdr


@pytest.fixture
def setup_role(tmp_path, monkeypatch):
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  settings = WorkSettings(tmp_path / "machine.toml", "/opt/herdr/herdr", "main")
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a, **k: ["/bin/sh"])
  return api, ws, settings, next(iter(api.panes))


def test_hundred_reuses_zero_input_ten_new_preserve_primary(setup_role):
  api, ws, settings, caller = setup_role
  primary = api.workspaces[ws["workspace_id"]]["tokens"]["rw_shell"]
  for _ in range(100): open_role(api, settings, "shell", caller_id=caller)
  assert len(api.panes) == 1
  for _ in range(10): open_role(api, settings, "shell", new=True, caller_id=caller)
  assert len(api.panes) == 11
  assert api.workspaces[ws["workspace_id"]]["tokens"]["rw_shell"] == primary
  assert all("send" not in method and method != "agent.start" for method, _ in api.requests)


def test_cold_unknown_new_only_resolves_that_role(setup_role):
  api, ws, settings, caller = setup_role
  api.workspaces[ws["workspace_id"]]["tokens"].clear()
  for pane in api.panes.values(): pane["tokens"].clear()
  ws = enter_project(api, __import__("pathlib").Path(ws["worktree"]["checkout_path"]))
  with pytest.raises(TermcfgError) as error: open_role(api, settings, "build", caller_id=caller)
  assert error.value.code == 4
  open_role(api, settings, "build", new=True, caller_id=caller)
  state = api.workspaces[ws["workspace_id"]]["tokens"]
  assert state["rw_build"].startswith("p:") and state["rw_edit"] == "unknown"
  assert len(api.panes) == 2


def test_marker_erased_is_not_closed_and_not_adopted(setup_role):
  api, ws, settings, caller = setup_role
  # 当前调用pane仍在项目，但初始用途标记被清掉。
  api.panes[caller]["tokens"].clear()
  with pytest.raises(TermcfgError) as error: open_role(api, settings, "shell", caller_id=caller)
  assert error.value.code == 4 and len(api.panes) == 1


def test_known_closed_primary_can_be_created_from_other_pane(setup_role):
  api, ws, settings, caller = setup_role
  other = open_role(api, settings, "shell", new=True, caller_id=caller)["pane_id"]
  del api.panes[caller]
  made = open_role(api, settings, "shell", caller_id=other)
  assert made["pane_id"] != other
  assert len(api.panes) == 2


def test_pending_does_not_cancel_even_explicit_new(setup_role):
  api, ws, settings, caller = setup_role
  api.workspaces[ws["workspace_id"]]["tokens"]["rw_pending"] = "edit:" + "a" * 32 + ":primary"
  for new in (False, True):
    with pytest.raises(TermcfgError) as error: open_role(api, settings, "build", new=new, caller_id=caller)
    assert error.value.code == 4
  open_role(api, settings, "shell", caller_id=caller)
  assert len(api.panes) == 1


def test_registered_then_exec_failure_is_unknown_not_restarted(setup_role):
  api, ws, settings, caller = setup_role
  pane = open_role(api, settings, "build", caller_id=caller)
  api.panes[pane["pane_id"]]["tokens"].update(rw_phase="failed")
  api.panes[pane["pane_id"]]["tokens"].pop("rw_commit")
  with pytest.raises(TermcfgError) as error: open_role(api, settings, "build", caller_id=caller)
  assert error.value.code == 4 and len(api.panes) == 2
  open_role(api, settings, "build", new=True, caller_id=caller)
  assert len(api.panes) == 3


def test_reused_id_with_new_terminal_is_not_old_primary(setup_role):
  api, ws, settings, caller = setup_role
  other = open_role(api, settings, "build", caller_id=caller)["pane_id"]
  api.panes[caller]["tokens"].clear()
  api.panes[caller]["terminal_id"] = "replacement-terminal"
  with pytest.raises(TermcfgError):
    open_role(api, settings, "shell", caller_id=other)
  assert len(api.panes) == 2


def test_moved_primary_is_preserved_and_never_promotes_extra(setup_role, tmp_path):
  api, ws, settings, caller = setup_role
  extra = open_role(api, settings, "shell", new=True, caller_id=caller)
  other_root = tmp_path / "other-project"
  other_root.mkdir()
  other_ws = enter_project(api, other_root)
  api.panes[caller]["workspace_id"] = other_ws["workspace_id"]
  made = open_role(api, settings, "shell", caller_id=extra["pane_id"])
  assert made["pane_id"] not in (extra["pane_id"], caller)
  assert api.panes[caller]["workspace_id"] == other_ws["workspace_id"]


def test_duplicate_primary_markers_never_focus_or_create(setup_role):
  api, ws, settings, caller = setup_role
  extra = open_role(api, settings, "shell", new=True, caller_id=caller)
  api.panes[extra["pane_id"]]["tokens"] = dict(api.panes[caller]["tokens"])
  before = len(api.requests)
  with pytest.raises(TermcfgError): open_role(api, settings, "shell", caller_id=caller)
  assert not any(m.endswith(".focus") or m == "tab.create" for m, _ in api.requests[before:])
