"""实际 wrapper 状态机配合假原生端点；从不执行第三方程序。"""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import time

import pytest

from termcfg import work, work_config, work_shell
from termcfg.errors import TermcfgError
from termcfg.herdr import Deadline
from termcfg.work_state import WorkState, context_owner, digest, SOURCE, LAUNCH_SOURCE
from work_helpers import FakeHerdr, FakeExec, FakeExecCalled


def setup_launch(tmp_path, monkeypatch, *, action="workspace-initial", commit=True, timeout=20):
  start = tmp_path / "business"
  start.mkdir()
  executable = tmp_path / "synthetic-shell"
  executable.write_bytes(b"synthetic executable; never run")
  executable.chmod(0o700)
  monkeypatch.setenv("SHELL", str(executable))
  definition = {"label": "Problem", "launcher": "shell"}
  settings = work_config.WorkSettings(tmp_path / "private.toml", "/bin/synthetic-herdr", "trial",
    model="structured-v1", structured={"templates": {"trial": {
      "order": ["problem"], "initial": "problem", "tab_types": {"problem": definition}}}})
  typed = work_config.prepare_launch(settings, definition, start)
  fake = FakeHerdr(str(tmp_path / "native" / "api.sock"), Deadline(timeout), version="v2")
  fake.auto_ready = fake.auto_accept = False
  native = fake.request("workspace.create", {"cwd": str(start), "label": "Trial", "focus": False, "env": {}})
  workspace, pane = native["workspace"], native["root_pane"]
  owner = context_owner(fake.socket_path, "named", "case-a")
  binding = {"version": 2, "owner": owner, "endpoint": str(Path(fake.socket_path).resolve()),
    "generation": list(fake.identity), "epoch": "a" * 32, "context": {"kind": "named", "key": "case-a"},
    "workspace_start": str(start), "captured_home": os.environ["HOME"],
    "workspace_id": None if action == "workspace-initial" else workspace["workspace_id"],
    "template": "trial", "origin": "explicit", "types": {"problem": typed}}
  parent = WorkState(fake.socket_path, fake.identity, create=True)
  op = "b" * 32
  value = {"version": 2, "action": action, "kind": "default", "op": op, "instance": "c" * 32,
    "epoch": binding["epoch"], "owner": owner, "context_kind": "named", "type": "problem",
    "workspace_start": str(start), "cwd": typed["cwd"], "captured_home": typed["captured_home"],
    "launch": typed["launch"], "binding_digest": typed["digest"], "local": str(settings.local_path),
    "session": settings.session, "socket_path": fake.socket_path, "endpoint_dev": fake.identity[0],
    "endpoint_ino": fake.identity[1], "rotom_root": str(work_config.ROOT),
    "source_digest": work.source_digest(), "selection_digest": settings.selection_digest,
    "intent_path": str(parent.root / "intents" / (op + ".json")),
    "expires_at_ns": int(fake.deadline.expires_at * 1_000_000_000)}
  if action == "tab":
    value["workspace_id"] = workspace["workspace_id"]
    parent.save_binding(binding)
  parent.publish_intent(op, binding, action=action, payload_digest=digest(value),
    type_key=value["type"], instance=value["instance"], kind=value["kind"])
  parent.update_receipt(op, "dispatched")
  marker = {"rw2_owner": owner, "rw2_epoch": binding["epoch"], "rw2_model": "structured-v1", "rw2_pending": op}
  if action == "tab":
    work.report_tokens(fake, "workspace", workspace["workspace_id"], marker, source=SOURCE)
  def commit_ready(client, params):
    if not commit or params["tokens"].get("rw2_phase") != "ready":
      return
    work.report_tokens(fake, "workspace", workspace["workspace_id"], marker, source=SOURCE)
    current = fake.panes[pane["pane_id"]]
    parent.update_receipt(op, "commit-issued", **{key: current[key]
      for key in ("workspace_id", "pane_id", "tab_id", "terminal_id")})
    work.report_tokens(fake, "pane", pane["pane_id"], {"rw2_commit": op}, source=LAUNCH_SOURCE)
  fake.barriers[("pane.report_metadata", "after", 1)] = commit_ready
  monkeypatch.setenv("HERDR_PANE_ID", pane["pane_id"])
  monkeypatch.setenv("HERDR_WORKSPACE_ID", "stale-startup-workspace")
  monkeypatch.setenv("HERDR_TAB_ID", "stale-startup-tab")
  monkeypatch.setenv("HERDR_SOCKET_PATH", fake.socket_path)
  execute = FakeExec(str(executable))
  return value, settings, fake, parent, execute, pane


def wire(value):
  return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.parametrize("action", ["workspace-initial", "tab"])
def test_wrapper_requires_durable_commit_then_executes_once(tmp_path, monkeypatch, action):
  value, settings, fake, parent, execute, pane = setup_launch(tmp_path, monkeypatch, action=action)
  monkeypatch.setenv(work_config.PAYLOAD_ENV_V2, wire(value))
  monkeypatch.setenv(work_config.PAYLOAD_ENV, "synthetic stale payload")
  monkeypatch.setattr(work, "operation_lock", lambda *a, **kw: pytest.fail("wrapper must not take parent lock"))
  before = len(fake.mutation_calls)
  try:
    with pytest.raises(FakeExecCalled):
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert len(execute.calls) == 1 and execute.calls[0]["cwd"] == Path(value["cwd"])
    env = execute.calls[0]["env"]
    assert work_config.PAYLOAD_ENV not in env and work_config.PAYLOAD_ENV_V2 not in env
    assert env["HERDR_PANE_ID"] == pane["pane_id"]
    assert env["HERDR_WORKSPACE_ID"] == "stale-startup-workspace"
    assert env["HERDR_TAB_ID"] == "stale-startup-tab"
    assert fake.panes[pane["pane_id"]]["tokens"]["rw2_phase"] == "accepted"
    assert parent.read("receipts", value["op"])["phase"] == "commit-issued"
    assert all(method.endswith("report_metadata") for method, _ in fake.mutation_calls[before:])
    assert all(params["source"] == LAUNCH_SOURCE for method, params in fake.mutation_calls[before:]
      if method == "pane.report_metadata")
    with pytest.raises(TermcfgError):
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert len(execute.calls) == 1
  finally:
    parent.close()


@pytest.mark.parametrize("change", ["payload", "source", "intent-path", "marker", "membership", "receipt"])
def test_wrapper_rejects_changed_authorization_or_identity(tmp_path, monkeypatch, change):
  value, settings, fake, parent, execute, pane = setup_launch(tmp_path, monkeypatch)
  if change == "payload":
    value["instance"] = "d" * 32
  elif change == "source":
    monkeypatch.setattr(work, "source_digest", lambda *a: "f" * 64)
  elif change == "intent-path":
    value["intent_path"] = str(tmp_path / "other" / (value["op"] + ".json"))
  else:
    original = fake.barriers[("pane.report_metadata", "after", 1)]
    def alter(client, params):
      original(client, params)
      if change == "marker":
        fake.workspaces[pane["workspace_id"]]["tokens"]["rw2_epoch"] = "e" * 32
      elif change == "membership":
        fake.panes[pane["pane_id"]]["terminal_id"] = "different-terminal"
      else:
        receipt = parent.read("receipts", value["op"])
        receipt["pane_id"] = "different-pane"
        from termcfg.work_state import json_bytes
        parent.tree.write_state("receipts/" + value["op"] + ".json", json_bytes(receipt))
    fake.barriers[("pane.report_metadata", "after", 1)] = alter
  try:
    with pytest.raises(TermcfgError):
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert not execute.calls
  finally:
    parent.close()


@pytest.mark.parametrize("cause", ["exec", "accepted-reply"])
def test_wrapper_failure_clears_same_source_commit_without_fallback(tmp_path, monkeypatch, cause):
  value, settings, fake, parent, execute, pane = setup_launch(tmp_path, monkeypatch)
  if cause == "exec":
    execute.error = OSError("synthetic failure")
  else:
    fake.fail("pane.report_metadata", when="after", occurrence=3,
      error=TermcfgError(4, "synthetic response lost"))
  try:
    with pytest.raises(TermcfgError) as error:
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert error.value.fallback_safe is False
    marker = fake.panes[pane["pane_id"]]["tokens"]
    assert marker["rw2_phase"] == "failed" and "rw2_commit" not in marker
    assert all(params["source"] == LAUNCH_SOURCE for method, params in fake.requests if method == "pane.report_metadata")
  finally:
    parent.close()


def test_wrapper_main_invalid_v2_exits_without_shell_fallback(monkeypatch):
  monkeypatch.setenv(work_config.PAYLOAD_ENV_V2, "{}")
  monkeypatch.setattr(work_shell, "fallback_shell", lambda: pytest.fail("v2 must fail closed"))
  assert work_shell.main() == 2


def test_wrapper_main_rejects_two_payload_versions(monkeypatch):
  monkeypatch.setenv(work_config.PAYLOAD_ENV_V2, "{}")
  monkeypatch.setenv(work_config.PAYLOAD_ENV, "{}")
  monkeypatch.setattr(work_shell, "fallback_shell", lambda: pytest.fail("ambiguous intent"))
  assert work_shell.main() == 2


def test_uncommitted_wrapper_expires_without_exec_or_private_receipt_write(tmp_path, monkeypatch):
  value, settings, fake, parent, execute, pane = setup_launch(tmp_path, monkeypatch, commit=False, timeout=0.2)
  receipt_before = parent.read("receipts", value["op"])
  try:
    with pytest.raises(TermcfgError) as error:
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert error.value.fallback_safe is False and not execute.calls
    assert parent.read("receipts", value["op"]) == receipt_before
    assert fake.panes[pane["pane_id"]]["tokens"]["rw2_phase"] == "failed"
  finally:
    parent.close()


def test_failed_failure_report_keeps_no_false_fallback_or_exec(tmp_path, monkeypatch):
  value, settings, fake, parent, execute, pane = setup_launch(tmp_path, monkeypatch)
  fake.fail("pane.report_metadata", when="after", occurrence=3,
    error=TermcfgError(4, "synthetic accepted response lost"))
  fake.fail("pane.report_metadata", when="before", occurrence=4,
    error=TermcfgError(5, "synthetic failure report unavailable"))
  try:
    with pytest.raises(TermcfgError) as error:
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert error.value.fallback_safe is False and not execute.calls
    assert parent.pending(value["owner"])
  finally:
    parent.close()


@pytest.mark.parametrize("change", ["membership", "deadline"])
def test_accepted_window_is_rechecked_before_exec(tmp_path, monkeypatch, change):
  value, settings, fake, parent, execute, pane = setup_launch(tmp_path, monkeypatch)
  if change == "membership":
    def move(client, params):
      fake.panes[pane["pane_id"]]["workspace_id"] = "different-workspace"
    fake.barriers[("pane.report_metadata", "after", 3)] = move
  else:
    real_chdir = os.chdir
    def expire(path):
      real_chdir(path)
      fake.deadline.expires_at = time.monotonic() - 1
    monkeypatch.setattr(work_shell.os, "chdir", expire)
  try:
    with pytest.raises(TermcfgError):
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert not execute.calls
  finally:
    parent.close()


@pytest.mark.parametrize("next_op", [None, "e" * 32])
def test_accepted_exec_survives_parent_pending_bookkeeping(tmp_path, monkeypatch, next_op):
  value, settings, fake, parent, execute, pane = setup_launch(tmp_path, monkeypatch)
  def finished(client, params):
    marker = fake.workspaces[pane["workspace_id"]]["tokens"]
    if next_op is None:
      marker.pop("rw2_pending", None)
    else:
      marker["rw2_pending"] = next_op
  fake.barriers[("pane.report_metadata", "after", 3)] = finished
  try:
    with pytest.raises(FakeExecCalled):
      work_shell.launch_payload_v2(wire(value), client=fake, settings=settings, execute=execute)
    assert len(execute.calls) == 1
  finally:
    parent.close()


@pytest.mark.parametrize("agent", ["dsh", "pi"])
def test_v2_agent_wrap_uses_reviewed_settings_after_accepted(tmp_path, monkeypatch, agent):
  import sys
  from types import SimpleNamespace
  from termcfg.work_state import launch_digest
  prepare = work_config.prepare_launch
  def reviewed(*args, **kwargs):
    result = prepare(*args, **kwargs)
    result["launch"]["launcher"] = agent
    result["launch"]["runtime"] = {"generation": "c" * 64, "identity": "synthetic-runtime", "policy": "isolated"}
    result["digest"] = launch_digest(result["cwd"], result["captured_home"], result["launch"])
    return result
  monkeypatch.setattr(work_config, "prepare_launch", reviewed)
  value, settings, fake, parent, _, pane = setup_launch(tmp_path, monkeypatch)
  wrapped, calls = [], []
  def wrap_launch(chosen, launcher, command, cwd, client, current):
    assert chosen is settings and launcher == agent and client is fake
    assert fake.panes[pane["pane_id"]]["tokens"]["rw2_phase"] == "accepted"
    assert current["pane_id"] == pane["pane_id"] and cwd == value["cwd"]
    wrapped.append(command)
    return ["/synthetic-resident", "fixed"]
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(wrap_launch=wrap_launch))
  try:
    assert work_shell.launch_payload_v2(wire(value), client=fake, settings=settings,
      execute=lambda *args: calls.append(args)) == 0
    assert len(wrapped) == 1 and calls[0][1] == ["/synthetic-resident", "fixed"]
  finally:
    parent.close()
