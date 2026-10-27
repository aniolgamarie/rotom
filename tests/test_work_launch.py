"""独立launcher执行参数和所有关键握手失败窗口。"""

import json
import os
from pathlib import Path
import time

import pytest

from termcfg.errors import TermcfgError
from termcfg.herdr import Deadline
from termcfg.work import enter_project, open_role, source_digest
from termcfg.work_config import ROOT, WorkSettings, PAYLOAD_ENV
from termcfg.work_shell import parse_payload, launch_payload
from work_helpers import FakeHerdr


def payload_for(api, ws, root, settings):
  op = "b" * 32
  api.workspaces[ws["workspace_id"]]["tokens"]["rw_pending"] = "build:" + op + ":primary"
  value = {"version": 1, "role": "build", "kind": "primary", "op": op,
    "epoch": ws["tokens"]["rw_epoch"], "project_digest": ws["tokens"]["rw_project"],
    "checkout": str(root), "workspace_id": ws["workspace_id"], "local": str(settings.local_path),
    "session": "main", "socket_path": api.socket_path, "endpoint_dev": api.identity[0],
    "endpoint_ino": api.identity[1], "rotom_root": str(ROOT), "source_digest": source_digest(),
    "selection_digest": settings.selection_digest, "expires_at_ns": time.monotonic_ns() + 20_000_000_000}
  return value


@pytest.fixture
def launch_case(tmp_path, monkeypatch):
  api = FakeHerdr(deadline=Deadline())
  api.auto_ready = api.auto_accept = False
  ws = enter_project(api, tmp_path)
  settings = WorkSettings(tmp_path / "local.toml", "herdr", "main")
  value = payload_for(api, ws, tmp_path, settings)
  made = api.request("tab.create", {"workspace_id": ws["workspace_id"], "cwd": str(tmp_path),
    "label": "build", "env": {PAYLOAD_ENV: json.dumps(value)}})
  pane_id = made["root_pane"]["pane_id"]
  monkeypatch.setenv("HERDR_PANE_ID", pane_id)
  original = api.request
  def request(method, params=None):
    result = original(method, params)
    if method == "pane.get" and api.panes[pane_id].get("tokens", {}).get("rw_phase") == "ready":
      api.panes[pane_id]["tokens"]["rw_commit"] = value["op"]
    return result
  api.request = request
  monkeypatch.setattr("termcfg.work_shell.prepare_tool", lambda *a: ["/synthetic literal shell"])
  return api, settings, value, pane_id


def test_valid_payload_execs_once_and_consumes_environment(launch_case, monkeypatch):
  api, settings, value, pane_id = launch_case
  monkeypatch.setenv(PAYLOAD_ENV, "not inherited")
  calls = []
  monkeypatch.setattr(os, "chdir", lambda path: calls.append(("cwd", path)))
  result = launch_payload(json.dumps(value), client=api, settings=settings,
    execute=lambda *args: calls.append(args))
  assert result == 0
  assert calls[0] == ("cwd", Path(value["checkout"]))
  assert calls[1][0:2] == ("/synthetic literal shell", ["/synthetic literal shell"])
  assert PAYLOAD_ENV not in calls[1][2]
  assert api.panes[pane_id]["tokens"]["rw_phase"] == "accepted"
  with pytest.raises(TermcfgError):
    launch_payload(json.dumps(value), client=api, settings=settings,
      execute=lambda *a: pytest.fail("intent replayed"))


@pytest.mark.parametrize("change", [{"command": "forbidden"}, {"op": "x"},
  {"version": True}, {"expires_at_ns": 1}, {"endpoint_ino": True}, {"local": "bad\npath"}])
def test_invalid_or_expired_payload_never_executes(launch_case, change):
  api, settings, value, _ = launch_case
  value.update(change)
  with pytest.raises(TermcfgError):
    launch_payload(json.dumps(value), client=api, settings=settings,
      execute=lambda *a: pytest.fail("invalid payload executed"))


def test_json_duplicates_and_byte_limit_rejected():
  for text in ('{"version":1,"version":1}', "中" * 6000):
    with pytest.raises(TermcfgError): parse_payload(text)


def test_exec_failure_is_irreversible_marker(launch_case, monkeypatch):
  api, settings, value, pane_id = launch_case
  monkeypatch.setattr(os, "chdir", lambda *a: None)
  def failed(*args): raise OSError("synthetic sensitive message must not escape")
  with pytest.raises(TermcfgError) as error:
    launch_payload(json.dumps(value), client=api, settings=settings, execute=failed)
  assert error.value.reason == "work_launch_exec_failed"
  marker = api.panes[pane_id]["tokens"]
  assert marker["rw_phase"] == "failed" and "rw_commit" not in marker


def test_create_response_lost_does_not_repeat_and_accepted_reconciles(tmp_path, monkeypatch):
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a: ["/bin/sh"])
  original = api.request
  def request(method, params=None):
    result = original(method, params)
    if method == "tab.create": raise TermcfgError(4, "synthetic_response_lost")
    return result
  api.request = request
  pane = open_role(api, settings, "build", caller_id=next(iter(api.panes)))
  assert len(api.panes) == 2
  assert sum(m == "tab.create" for m, _ in api.requests) == 1
  assert pane["tokens"]["rw_phase"] == "accepted"


def test_uncommitted_timeout_leaves_pending_and_never_retries(tmp_path, monkeypatch):
  api = FakeHerdr(deadline=Deadline(timeout=0.08))
  ws = enter_project(api, tmp_path)
  api.auto_accept = False
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a: ["/bin/sh"])
  with pytest.raises(TermcfgError) as error:
    open_role(api, settings, "build", caller_id=next(iter(api.panes)))
  assert error.value.code == 4
  assert "rw_pending" in api.workspaces[ws["workspace_id"]]["tokens"]
  assert sum(m == "tab.create" for m, _ in api.requests) == 1


@pytest.mark.parametrize("field", ["source_digest", "selection_digest"])
def test_launch_source_or_selection_change_never_executes(launch_case, field):
  api, settings, value, _ = launch_case
  value[field] = "0" * 64
  with pytest.raises(TermcfgError):
    launch_payload(json.dumps(value), client=api, settings=settings,
      execute=lambda *a: pytest.fail("unbound intent executed"))


def test_missing_selector_never_defaults_machine(launch_case):
  api, settings, value, _ = launch_case
  value.pop("local")
  with pytest.raises(TermcfgError): parse_payload(json.dumps(value))


def test_accepted_reply_lost_and_failed_tombstone_lost_exits_instead_of_plain_shell(launch_case):
  api, settings, value, pane_id = launch_case
  original = api.request
  def request(method, params=None):
    result = original(method, params)
    if method == "pane.report_metadata" and params["tokens"].get("rw_phase") in ("accepted", "failed"):
      raise TermcfgError(4, "synthetic_response_lost")
    return result
  api.request = request
  with pytest.raises(TermcfgError) as error:
    launch_payload(json.dumps(value), client=api, settings=settings,
      execute=lambda *a: pytest.fail("uncertain acceptance executed"))
  assert error.value.fallback_safe is False


def test_parent_and_real_launcher_handshake_concurrently_without_auto_ready(tmp_path, monkeypatch):
  import threading
  api = FakeHerdr(deadline=Deadline(timeout=2))
  api.auto_ready = api.auto_accept = False
  ws = enter_project(api, tmp_path)
  caller = next(iter(api.panes))
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a: ["/synthetic/tool"])
  monkeypatch.setattr("termcfg.work_shell.prepare_tool", lambda *a: ["/synthetic/tool"])
  monkeypatch.setattr(os, "chdir", lambda *a: None)
  original = api.request
  executions, errors, children = [], [], []
  def request(method, params=None):
    result = original(method, params)
    if method == "tab.create":
      monkeypatch.setenv("HERDR_PANE_ID", result["root_pane"]["pane_id"])
      def launch():
        try:
          launch_payload(params["env"][PAYLOAD_ENV], client=api, settings=settings,
            execute=lambda *a: executions.append(a))
        except BaseException as error: errors.append(error)
      child = threading.Thread(target=launch)
      children.append(child)
      child.start()
    return result
  api.request = request
  pane = open_role(api, settings, "build", caller_id=caller)
  for child in children: child.join(timeout=3)
  assert not errors and not any(child.is_alive() for child in children)
  assert len(executions) == 1 and executions[0][:2] == ("/synthetic/tool", ["/synthetic/tool"])
  assert pane["tokens"]["rw_phase"] == "accepted"
  assert "rw_pending" not in api.workspaces[ws["workspace_id"]]["tokens"]
  assert sum(method == "tab.create" for method, _ in api.requests) == 1


def test_caller_moves_after_ready_but_before_commit_no_business_admission(tmp_path, monkeypatch):
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  caller = next(iter(api.panes))
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a: ["/synthetic/tool"])
  original = api.request
  def request(method, params=None):
    result = original(method, params)
    if method == "pane.list" and any(p.get("tokens", {}).get("rw_phase") == "ready" for p in api.panes.values()):
      api.panes[caller]["workspace_id"] = "moved-by-native"
    return result
  api.request = request
  with pytest.raises(TermcfgError) as error:
    open_role(api, settings, "build", caller_id=caller)
  assert error.value.code == 4
  made = list(api.panes.values())[-1]
  assert "rw_commit" not in made["tokens"]
  assert "rw_pending" in api.workspaces[ws["workspace_id"]]["tokens"]


@pytest.mark.parametrize("role,seconds", [("pi", 60), ("dsh", 60), ("shell", 30), ("edit", 30), ("build", 30), ("debug", 30), ("codex", 30)])
def test_payload_role_specific_upper_bound_keeps_absolute_expiration(launch_case, monkeypatch, role, seconds):
  _, _, value, _ = launch_case
  monkeypatch.setattr(time, "monotonic_ns", lambda: 100_000_000_000)
  value.update(role=role, expires_at_ns=(100 + seconds) * 1_000_000_000)
  assert parse_payload(json.dumps(value))["expires_at_ns"] == value["expires_at_ns"]
  value["expires_at_ns"] += 1
  with pytest.raises(TermcfgError):
    parse_payload(json.dumps(value))


def test_managed_launcher_uses_remaining_parent_deadline_without_reset(launch_case, monkeypatch):
  api, settings, value, _ = launch_case
  now = [100.0]
  monkeypatch.setattr(time, "monotonic", lambda: now[0])
  monkeypatch.setattr(time, "monotonic_ns", lambda: int(now[0] * 1_000_000_000))
  value.update(role="pi", expires_at_ns=145_000_000_000)
  api.workspaces[value["workspace_id"]]["tokens"]["rw_pending"] = "pi:" + value["op"] + ":primary"
  deadlines = []
  class Captured(Deadline):
    def __init__(self, *args, **kwargs):
      super().__init__(*args, **kwargs)
      deadlines.append(self)
  monkeypatch.setattr("termcfg.herdr.Deadline", Captured)
  def prepare(*args):
    now[0] += 5
    return ["/bin/sh"]
  monkeypatch.setattr("termcfg.work_shell.prepare_tool", prepare)
  monkeypatch.setattr(os, "chdir", lambda *args: None)
  assert launch_payload(json.dumps(value), client=api, settings=settings, execute=lambda *args: None) == 0
  assert deadlines[0].expires_at == 145
  assert deadlines[0].remaining() == 40


@pytest.mark.parametrize("role,seconds", [("build", 30), ("pi", 60), ("dsh", 60)])
def test_preparation_cannot_restart_expired_parent_budget(launch_case, monkeypatch, role, seconds):
  api, settings, value, _ = launch_case
  now = [100.0]
  monkeypatch.setattr(time, "monotonic", lambda: now[0])
  monkeypatch.setattr(time, "monotonic_ns", lambda: int(now[0] * 1_000_000_000))
  value.update(role=role, expires_at_ns=(100 + seconds) * 1_000_000_000)
  api.workspaces[value["workspace_id"]]["tokens"]["rw_pending"] = role + ":" + value["op"] + ":primary"
  def prepare(*args):
    now[0] = 101 + seconds
    return ["/bin/sh"]
  monkeypatch.setattr("termcfg.work_shell.prepare_tool", prepare)
  with pytest.raises(TermcfgError):
    launch_payload(json.dumps(value), client=api, settings=settings,
      execute=lambda *args: pytest.fail("expired parent executed"))


@pytest.mark.parametrize("agent", ["dsh", "pi"])
def test_agent_launch_wraps_only_after_accepted_with_reviewed_settings(launch_case, monkeypatch, agent):
  import sys
  from types import SimpleNamespace
  api, settings, value, pane_id = launch_case
  value["role"] = agent
  api.workspaces[value["workspace_id"]]["tokens"]["rw_pending"] = agent + ":" + value["op"] + ":primary"
  wrapped = []
  def wrap_launch(chosen, launcher, command, cwd, client, pane):
    assert chosen is settings and launcher == agent and client is api
    assert api.panes[pane_id]["tokens"]["rw_phase"] == "accepted"
    assert pane["pane_id"] == pane_id and cwd == value["checkout"]
    wrapped.append(command)
    return ["/synthetic-resident", "fixed"]
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(wrap_launch=wrap_launch))
  monkeypatch.setattr(os, "chdir", lambda path: None)
  calls = []
  assert launch_payload(json.dumps(value), client=api, settings=settings,
    execute=lambda *args: calls.append(args)) == 0
  assert len(wrapped) == 1 and calls[0][1] == ["/synthetic-resident", "fixed"]


@pytest.mark.parametrize("agent", ["dsh", "pi"])
def test_accepted_parent_cleanup_does_not_invalidate_committed_agent_launch(launch_case, monkeypatch, agent):
  import sys
  from types import SimpleNamespace
  from termcfg import work_shell
  api, settings, value, pane_id = launch_case
  value["role"] = agent
  api.workspaces[value["workspace_id"]]["tokens"]["rw_pending"] = agent + ":" + value["op"] + ":primary"
  expected = {key: api.panes[pane_id][key] for key in ("workspace_id", "tab_id", "pane_id", "terminal_id")}
  original = api.request
  cleaned = []
  def request(method, params=None):
    result = original(method, params)
    if method == "pane.report_metadata" and params["tokens"].get("rw_phase") == "accepted":
      api.workspaces[value["workspace_id"]]["tokens"].pop("rw_pending")
      cleaned.append(True)
    return result
  api.request = request
  wrapped, executed = [], []
  def wrap_launch(chosen, launcher, command, cwd, client, pane):
    assert cleaned == [True] and chosen is settings and launcher == agent and client is api
    assert all(pane[key] == item for key, item in expected.items())
    assert pane["tokens"]["rw_phase"] == "ready"
    assert api.panes[pane_id]["tokens"]["rw_phase"] == "accepted"
    assert cwd == value["checkout"]
    wrapped.append(command)
    return ["/synthetic-resident", "fixed"]
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(wrap_launch=wrap_launch))
  monkeypatch.setattr(os, "chdir", lambda path: None)
  monkeypatch.setattr(work_shell, "launch_payload", lambda text: launch_payload(text,
    client=api, settings=settings, execute=lambda *args: executed.append(args)))
  monkeypatch.setattr(work_shell, "fallback_shell", lambda: pytest.fail("committed launch fell back to shell"))
  monkeypatch.setenv(PAYLOAD_ENV, json.dumps(value))
  assert work_shell.main() == 0
  assert len(wrapped) == 1 and len(executed) == 1
  assert executed[0][1] == ["/synthetic-resident", "fixed"]
  assert api.panes[pane_id]["tokens"]["rw_phase"] == "accepted"
