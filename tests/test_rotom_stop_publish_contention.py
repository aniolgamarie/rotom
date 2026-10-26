"""客户端等待短锁仍用原截止点；等待不会重投或越过取消。"""
from copy import deepcopy

import pytest

from agentcfg import dsh_stop_client as client
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.storage import Conflict
from test_rotom_dsh_stop_client import clock, inbox_for
from test_rotom_dsh_stop_completion import accepted, request
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


@pytest.mark.parametrize("site", ["owner", "inbox"])
@pytest.mark.parametrize("release", [False, True])
def test_publish_waits_for_original_short_lock_but_never_renews_or_reposts(accepted, clock, monkeypatch, site, release):
  ws, registry, args, runs, plan = accepted
  inbox = inbox_for(accepted)
  held = (registry if site == "owner" else inbox._registry)._locked(nonblocking=True)
  held.__enter__()
  released = []
  def sleep(seconds):
    if release and not released:
      held.__exit__(None, None, None); released.append(True)
    clock.sleeps.append(seconds); clock.now += seconds
  monkeypatch.setattr(client.time, "sleep", sleep)
  value = request(accepted); value["deadline_ns"] = 25000000
  row = deepcopy(args["expected_records"][runs[0]])
  try:
    if release:
      client.publish_request(ws, value, expected_record=row)
    else:
      with pytest.raises(Conflict): client.publish_request(ws, value, expected_record=row)
  finally:
    if not released: held.__exit__(None, None, None)
  pending = inbox.pending(expected=inbox.describe())
  assert len(pending) == int(release)
  assert clock.now <= 0.025
  assert len(clock.sleeps) == (1 if release else 3)
  if release: assert pending[0] == value


def test_timed_journal_read_is_readonly_and_handles_missing_root(accepted, clock, monkeypatch):
  ws, registry, args, runs, plan = accepted
  journal = StopDispatches(ws.state_root / "stop-dispatches", ws.binding)
  assert journal.read(runs[0], deadline_ns=25000000) is None and not journal.root.exists()
  value = request(accepted); value["deadline_ns"] = 25000000
  journal.begin(value)
  held = journal._registry._locked(nonblocking=True); held.__enter__()
  released = []
  def sleep(seconds):
    held.__exit__(None, None, None); released.append(True)
    clock.sleeps.append(seconds); clock.now += seconds
  monkeypatch.setattr(client.time, "sleep", sleep)
  try:
    result = journal.read(runs[0], deadline_ns=value["deadline_ns"])
  finally:
    if not released: held.__exit__(None, None, None)
  assert result == {"request": value, "dispatch": "unknown"}
  assert clock.sleeps == [0.01]
