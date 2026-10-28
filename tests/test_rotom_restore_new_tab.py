"""新 tab 恢复握手只使用私有请求和固定子命令。"""
import json
import time
from copy import deepcopy
from pathlib import Path

import pytest

from termcfg.errors import TermcfgError
from termcfg import restore_tabs as transport


def test_duplicate_payload_rejected():
  with pytest.raises(TermcfgError):
    transport.parse_payload('{"version":1,"version":1}')


class Store:
  def __init__(self, root, request):
    self.root = root
    self.request = request
    self.receipt = {"schema_version": 1, "request_id": request["request_id"], "phase": "prepared",
      "terminal_ref": None, "exit_code": None, "reason": None}
    self.auto_commit = False
    self.auto_handoff = False

  def read_request(self):
    return deepcopy(self.request)

  def read_receipt(self):
    if self.auto_commit and self.receipt["phase"] == "ready":
      self.receipt["phase"] = "committed"
    if self.auto_handoff and self.receipt["phase"] == "committed":
      self.receipt["phase"] = "handoff"
    return deepcopy(self.receipt)

  def transition(self, expected, replacement):
    assert expected == self.receipt
    self.receipt = deepcopy(replacement)
    return deepcopy(replacement)


@pytest.fixture
def case(tmp_path, monkeypatch):
  import sys
  from types import SimpleNamespace
  from termcfg.herdr import Deadline
  from termcfg.work import enter_project
  from termcfg.work_config import ROOT, WorkSettings
  from work_helpers import FakeHerdr
  api = FakeHerdr(deadline=Deadline(0.1))
  api.auto_ready = api.auto_accept = False
  workspace = enter_project(api, tmp_path)
  api.requests.clear()
  store = Store(tmp_path / "request", {"request_id": "a" * 32, "mode": "new-tab",
    "rotom_root": str(ROOT), "cwd": str(tmp_path), "manager_code_identity": "d" * 64})
  settings = WorkSettings(tmp_path / "local", "/bin/sh", "main")
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(
    child_command=lambda selected: [str(ROOT / ".venv/bin/python"), "-B",
      str(ROOT / "src/rotom/restore_child.py"), "--request-root", str(selected.root)]))
  monkeypatch.setattr(transport, "request_digest", lambda request: "b" * 64)
  monkeypatch.setattr(transport, "source_digest", lambda: "d" * 64)
  monkeypatch.setattr(transport, "require_startup_evidence", lambda *args: None)
  monkeypatch.setattr(transport, "_store", lambda root: store)
  value = {"version": 1, "request_path": str(store.root / "request.json"),
    "request_digest": "b" * 64, "socket_path": api.socket_path,
    "endpoint_dev": api.identity[0], "endpoint_ino": api.identity[1],
    "source_digest": transport.source_digest(), "rotom_root": str(ROOT),
    "expires_at_ns": time.monotonic_ns() + 1_000_000_000}
  return api, workspace, store, settings, value


@pytest.mark.parametrize("patch", [{"version": True}, {"endpoint_dev": True}, {"argv": ["bad"]},
  {"expires_at_ns": 1}, {"request_path": "/tmp/../request.json"}, {"source_digest": "x"},
  {"socket_path": "/tmp/socket\n"}])
def test_payload_strict(case, patch):
  value = case[-1]
  value.update(patch)
  with pytest.raises(TermcfgError):
    transport.parse_payload(json.dumps(value))


def test_bootstrap_executes_fixed_child_and_consumes_payload(case, monkeypatch):
  api, workspace, store, _, value = case
  store.receipt["phase"] = "dispatched"
  store.auto_commit = True
  pane = next(iter(api.panes.values()))
  monkeypatch.setenv("HERDR_PANE_ID", pane["pane_id"])
  monkeypatch.setenv(transport.PAYLOAD_ENV, "consumed")
  monkeypatch.setenv("ROTOM_WORK_LAUNCH_V1", "consumed")
  monkeypatch.setattr("os.chdir", lambda cwd: None)
  calls = []
  assert transport.bootstrap_restore(json.dumps(value), client=api, execute=lambda *args: calls.append(args)) == 0
  assert calls[0][1] == [str(transport.ROOT / ".venv/bin/python"), "-B",
    str(transport.ROOT / "src/rotom/restore_child.py"), "--request-root", str(store.root)]
  assert not any(name.startswith("ROTOM_") and "LAUNCH" in name for name in calls[0][2])
  assert store.receipt["phase"] == "handoff"
  with pytest.raises(TermcfgError):
    transport.bootstrap_restore(json.dumps(value), client=api, execute=lambda *args: pytest.fail("replay"))


def test_bootstrap_exec_failure_never_falls_back(case, monkeypatch):
  api, _, store, _, value = case
  store.receipt["phase"] = "dispatched"
  store.auto_commit = True
  monkeypatch.setenv("HERDR_PANE_ID", next(iter(api.panes)))
  monkeypatch.setattr("os.chdir", lambda cwd: None)
  def fail(*args):
    raise OSError("private synthetic detail")
  with pytest.raises(TermcfgError) as error:
    transport.bootstrap_restore(json.dumps(value), client=api, execute=fail)
  assert store.receipt["phase"] == "failed"
  assert "private" not in str(error.value)


@pytest.mark.parametrize("kind,code", [("config", 2), ("credential", 3), ("dependency", 5),
  ("session", 5), ("state", 4), ("path", 4)])
def test_bootstrap_scope_errors_after_handoff_are_recorded_without_exec(case, monkeypatch, kind, code):
  import sys
  from agentcfg.paths import PathError
  from agentcfg.process import DependencyError
  from agentcfg.schema import ConfigError
  from agentcfg.secrets import CredentialError
  from agentcfg.sessions import SessionError
  from agentcfg.storage import StateError
  api, _, store, _, value = case
  store.receipt["phase"] = "dispatched"
  store.auto_commit = True
  monkeypatch.setenv("HERDR_PANE_ID", next(iter(api.panes)))
  errors = {"config": ConfigError("synthetic"), "credential": CredentialError(),
    "dependency": DependencyError("private synthetic detail"), "session": SessionError(5, "private_synthetic_detail"),
    "state": StateError("private synthetic detail"), "path": PathError("private synthetic detail")}
  def fail(selected):
    assert store.receipt["phase"] == "handoff"
    raise errors[kind]
  monkeypatch.setattr(sys.modules["rotom.pane_dispatch"], "child_command", fail)
  with pytest.raises(TermcfgError) as error:
    transport.bootstrap_restore(json.dumps(value), client=api,
      execute=lambda *args: pytest.fail("invalid scope must not exec"))
  assert error.value.code == code
  assert store.receipt["phase"] == "failed"
  assert store.receipt["exit_code"] == (code if code in (2, 3, 5) else None)
  assert "private" not in str(error.value)
  with pytest.raises(TermcfgError):
    transport.bootstrap_restore(json.dumps(value), client=api,
      execute=lambda *args: pytest.fail("failed request cannot replay"))


def test_parent_single_create_and_durable_handoff(case):
  api, workspace, store, settings, value = case
  original = api.request
  store.auto_handoff = True
  def request(method, params=None):
    result = original(method, params)
    if method == "tab.create":
      assert store.receipt["phase"] == "dispatched"
      payload = transport.parse_payload(params["env"][transport.PAYLOAD_ENV])
      assert payload.keys() == value.keys()
      pane = api.panes[result["root_pane"]["pane_id"]]
      pane["tokens"].update(transport._marker(store.request, payload))
      store.receipt.update(phase="ready", terminal_ref=transport._reference(api, pane, store.request["cwd"]))
      raise TermcfgError(4, "synthetic_lost_response")
    return result
  api.request = request
  result = transport.create_restore_tab(api, settings, store, workspace_id=workspace["workspace_id"],
    caller_id=next(iter(api.panes)))
  assert result["created"] and result["handoff"]
  assert sum(method == "tab.create" for method, _ in api.requests) == 1
  assert not any(method.endswith("focus") for method, _ in api.requests)


def test_unconfirmed_create_is_unknown_without_retry(case):
  api, workspace, store, settings, _ = case
  with pytest.raises(TermcfgError) as error:
    transport.create_restore_tab(api, settings, store, workspace_id=workspace["workspace_id"])
  assert error.value.code == 4
  assert store.receipt["phase"] == "unknown"
  assert sum(method == "tab.create" for method, _ in api.requests) == 1


def test_restore_payload_conflict_and_bad_payload_no_shell(monkeypatch):
  from termcfg.work_shell import main
  monkeypatch.setattr("termcfg.work_shell.fallback_shell", lambda: pytest.fail("fallback forbidden"))
  monkeypatch.setenv(transport.PAYLOAD_ENV, "bad")
  assert main() == 2
  monkeypatch.setenv(transport.PAYLOAD_ENV, "bad")
  monkeypatch.setenv("ROTOM_WORK_LAUNCH_V2", "bad")
  assert main() == 2


def test_missing_protected_request_is_static_conflict(case, monkeypatch):
  api, _, store, _, value = case
  store.request = None
  with pytest.raises(TermcfgError) as error:
    transport.bootstrap_restore(json.dumps(value), client=api)
  assert error.value.code == 4


def test_request_code_change_rejects_before_creating_tab(case):
  api, workspace, store, settings, _ = case
  store.request["manager_code_identity"] = "0" * 64
  with pytest.raises(TermcfgError):
    transport.create_restore_tab(api, settings, store, workspace_id=workspace["workspace_id"])
  assert store.receipt["phase"] == "prepared"
  assert not any(method == "tab.create" for method, _ in api.requests)


@pytest.mark.parametrize("mutation", ["endpoint", "source", "marker", "membership", "preconsumed"])
def test_bootstrap_identity_changes_never_execute(case, monkeypatch, mutation):
  api, _, store, _, value = case
  store.receipt["phase"] = "dispatched"
  store.auto_commit = True
  monkeypatch.setenv("HERDR_PANE_ID", next(iter(api.panes)))
  if mutation == "endpoint":
    value["endpoint_ino"] += 1
  elif mutation == "source":
    value["source_digest"] = "0" * 64
  elif mutation == "preconsumed":
    next(iter(api.panes.values()))["tokens"]["rr_request"] = "c" * 32
  else:
    original = api.request
    def request(method, params=None):
      result = original(method, params)
      if method == "pane.current" and store.receipt["phase"] in ("ready", "committed"):
        if mutation == "membership":
          result["pane"]["terminal_id"] = "changed"
        else:
          result["pane"]["tokens"]["rr_request"] = "c" * 32
      return result
    api.request = request
  with pytest.raises(TermcfgError):
    transport.bootstrap_restore(json.dumps(value), client=api,
      execute=lambda *args: pytest.fail("identity changed"))


def test_wrong_caller_workspace_refuses_before_dispatch(case):
  api, _, store, settings, _ = case
  with pytest.raises(TermcfgError):
    transport.create_restore_tab(api, settings, store, workspace_id="different", caller_id=next(iter(api.panes)))
  assert store.receipt["phase"] == "prepared"
  assert not any(method == "tab.create" for method, _ in api.requests)


def test_parent_and_bootstrap_complete_real_handshake(case, monkeypatch):
  import threading
  api, workspace, store, settings, _ = case
  original = api.request
  child_errors = []
  commands = []
  children = []
  monkeypatch.setattr("os.chdir", lambda cwd: None)
  def request(method, params=None):
    result = original(method, params)
    if method == "tab.create":
      monkeypatch.setenv("HERDR_PANE_ID", result["root_pane"]["pane_id"])
      def bootstrap():
        try:
          transport.bootstrap_restore(params["env"][transport.PAYLOAD_ENV], client=api,
            execute=lambda *args: commands.append(args))
        except BaseException as error:
          child_errors.append(error)
      child = threading.Thread(target=bootstrap)
      children.append(child)
      child.start()
    return result
  api.request = request
  result = transport.create_restore_tab(api, settings, store, workspace_id=workspace["workspace_id"])
  for child in children:
    child.join(timeout=2)
    assert not child.is_alive()
  assert not child_errors
  assert result["phase"] == "handoff" and len(commands) == 1
  assert store.receipt["phase"] == "handoff"


def test_private_store_conflict_is_static(monkeypatch, capsys):
  from agentcfg.storage import Conflict
  from termcfg.work_shell import main
  def blocked(text):
    class Unsafe:
      def read_request(self):
        raise Conflict("synthetic private detail")
    return transport._read(Unsafe(), "read_request")
  monkeypatch.setattr(transport, "bootstrap_restore", blocked)
  monkeypatch.setenv(transport.PAYLOAD_ENV, "synthetic")
  assert main() == 4
  assert "private detail" not in capsys.readouterr().err


def test_child_command_conflict_marks_failed_and_is_static(case, monkeypatch):
  import sys
  from agentcfg.storage import Conflict
  api, _, store, _, value = case
  store.receipt["phase"] = "dispatched"
  store.auto_commit = True
  monkeypatch.setenv("HERDR_PANE_ID", next(iter(api.panes)))
  def changed(selected):
    raise Conflict("synthetic private child detail")
  monkeypatch.setattr(sys.modules["rotom.pane_dispatch"], "child_command", changed)
  with pytest.raises(TermcfgError) as error:
    transport.bootstrap_restore(json.dumps(value), client=api, execute=lambda *args: pytest.fail("changed"))
  assert store.receipt["phase"] == "failed"
  assert "private" not in str(error.value)


def test_configurable_payload_above_sixty_seconds_preserves_absolute_deadline(case, monkeypatch):
  from rotom.restore_deadline import ReadyDeadline
  api, workspace, store, settings, _ = case
  api.deadline = ReadyDeadline(120)
  expires = api.deadline.deadline_ns
  original = api.request
  store.auto_handoff = True
  def request(method, params=None):
    result = original(method, params)
    if method == "tab.create":
      payload = transport.parse_payload(params["env"][transport.PAYLOAD_ENV])
      assert payload["expires_at_ns"] == expires
      assert payload["expires_at_ns"] > time.monotonic_ns() + 60_000_000_000
      pane = api.panes[result["root_pane"]["pane_id"]]
      pane["tokens"].update(transport._marker(store.request, payload))
      store.receipt.update(phase="ready", terminal_ref=transport._reference(api, pane, store.request["cwd"]))
    return result
  api.request = request
  assert transport.create_restore_tab(api, settings, store, workspace_id=workspace["workspace_id"])["handoff"]


def test_bootstrap_same_deadline_does_not_wait_for_or_limit_host(case, monkeypatch):
  api, _, store, _, value = case
  store.receipt["phase"] = "dispatched"
  store.auto_commit = True
  monkeypatch.setenv("HERDR_PANE_ID", next(iter(api.panes)))
  monkeypatch.setattr("os.chdir", lambda cwd: None)
  now = [time.monotonic()]
  value["expires_at_ns"] = int((now[0] + 120) * 1_000_000_000)
  monkeypatch.setattr("rotom.restore_deadline.time.monotonic", lambda: now[0])
  calls = []
  def execute(*args):
    assert api.deadline.deadline_ns == value["expires_at_ns"]
    assert store.receipt["phase"] == "handoff"
    now[0] += 500
    calls.append(args)
  assert transport.bootstrap_restore(json.dumps(value), client=api, execute=execute) == 0
  assert len(calls) == 1 and store.receipt["phase"] == "handoff"


def test_payload_over_300_seconds_and_expired_payload_are_rejected(case):
  value = case[-1]
  for expires in (time.monotonic_ns() - 1, time.monotonic_ns() + 301_000_000_000):
    with pytest.raises(TermcfgError) as error:
      transport.parse_payload(json.dumps({**value, "expires_at_ns": expires}))
    assert error.value.code == 2
