"""调用pane与全局焦点分开；缺上下文没有副作用。"""

from pathlib import Path

import pytest

from termcfg.errors import TermcfgError
from termcfg.herdr import Deadline
from termcfg.work import enter_project, open_role, main
from termcfg.work_config import WorkSettings
from work_helpers import FakeHerdr


def scenario(tmp_path):
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  settings = WorkSettings(tmp_path / "machine.toml", "/opt/herdr/herdr", "main")
  return api, ws, settings, next(iter(api.panes))


@pytest.mark.parametrize("new", [False, True])
def test_external_open_rejected_before_config_or_native(tmp_path, monkeypatch, new):
  for _ in range(10):
    assert main(["open", "edit"] + (["--new"] if new else [])) == 4
  assert not (tmp_path / "private-state").exists()


def test_caller_id_not_global_focus(tmp_path):
  api, ws, settings, caller = scenario(tmp_path)
  other = tmp_path / "other"
  other.mkdir()
  enter_project(api, other)
  before = len(api.panes)
  result = open_role(api, settings, "shell", caller_id=caller)
  assert result["workspace_id"] == ws["workspace_id"]
  assert len(api.panes) == before
  assert ("pane.current", {"caller_pane_id": caller}) in api.requests


def test_closed_or_moved_caller_not_old_environment(tmp_path):
  api, ws, settings, caller = scenario(tmp_path)
  del api.panes[caller]
  for new in (False, True):
    with pytest.raises(TermcfgError) as error:
      open_role(api, settings, "shell", new=new, caller_id=caller)
    assert error.value.code == 4


def test_cli_rejects_unknown_role_and_selectors():
  assert main(["open", "unknown"]) == 2
  assert main(["--machine", "one", "--local", "two", "enter", "."]) == 2
  assert main(["--help"]) == 0


def test_native_caller_move_during_lookup_cannot_focus_old_project(tmp_path):
  api, ws, settings, caller = scenario(tmp_path)
  other = api.request("tab.create", {"workspace_id": ws["workspace_id"], "cwd": str(tmp_path),
    "label": "native", "env": {}})
  caller = other["root_pane"]["pane_id"]
  original = api.request
  def request(method, params=None):
    result = original(method, params)
    if method == "pane.list":
      api.panes[caller]["workspace_id"] = "moved-workspace"
    return result
  api.request = request
  with pytest.raises(TermcfgError) as error:
    open_role(api, settings, "shell", caller_id=caller)
  assert error.value.code == 4
  assert not any(m.endswith(".focus") for m, _ in api.requests[api.requests.index(("pane.list", {})) + 1:])


def test_other_session_or_socket_context_is_rejected(tmp_path, monkeypatch):
  from termcfg.work import _caller_scope
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  monkeypatch.setenv("HERDR_PANE_ID", "synthetic-pane")
  monkeypatch.setenv("HERDR_SOCKET_PATH", "/synthetic/other.sock")
  monkeypatch.setenv("HERDR_SESSION", "other")
  with pytest.raises(TermcfgError): _caller_scope(settings)
  monkeypatch.setenv("HERDR_SESSION", "main")
  with pytest.raises(TermcfgError): _caller_scope(settings, "/synthetic/selected.sock")
