"""收尾后的只读短锁竞争沿用原预算；真实独立 FD，不启动宿主。"""
from contextlib import ExitStack, contextmanager
import fcntl
import os
import threading
import time

import pytest

from agentcfg import dsh_stop_client as client, dsh_stop_completion as completion, run_owners, run_stop_fence
from agentcfg.control_deadline import ControlDeadline
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.stop_inbox import StopInbox
from agentcfg.storage import Conflict
from test_rotom_dsh_stop_client import clock, fresh, execute, metadata
from test_rotom_dsh_stop_completion import accepted, finish, close, request
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import MANAGER, observation


_REAL_NS, _REAL_SLEEP = time.monotonic_ns, time.sleep


@contextmanager
def held(root, *, release=False):
  fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  released = threading.Event()
  timer = None
  def unlock():
    fcntl.flock(fd, fcntl.LOCK_UN)
    released.set()
  try:
    if release:
      timer = threading.Timer(0.05, unlock)
      timer.start()
    yield released
  finally:
    if timer is not None:
      timer.cancel()
      timer.join()
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def completed(value):
  ws, registry, args, runs, plan = value
  ticket = request(value) | {"deadline_ns": _REAL_NS() + 10_000_000_000}
  inbox = StopInbox(ws.state_root / "stop-inboxes" / runs[0], ws.binding)
  inbox.submit(ticket, expected=inbox.describe())
  journal = StopDispatches(ws.state_root / "stop-dispatches", ws.binding)
  attempt = journal.begin(ticket)
  attempt.sent()
  finish(value)
  close(value)
  return {"owner": registry.root, "inbox": inbox.root, "journal": journal.root}


@pytest.mark.parametrize("kind", ["owner", "inbox", "journal"])
def test_status_waits_for_read_contention_using_original_deadline(accepted, kind):
  ws, registry, args, runs, plan = accepted
  roots = completed(accepted)
  before = metadata(ws)
  with held(roots[kind], release=True) as released:
    result = client.status_stop(ws, batch_id=args["batch_id"], deadline_ns=_REAL_NS() + 1_000_000_000)
  assert released.is_set()
  assert result["status"] == "stopped" and result["protected"] is False
  assert next(row for row in result["targets"] if row["run_id"] == runs[0])["dispatch"] == "signal_sent"
  assert metadata(ws) == before


@pytest.mark.parametrize("kind", ["owner", "inbox", "journal"])
def test_expired_status_only_observes_once_without_wait_or_write(accepted, monkeypatch, kind):
  ws, registry, args, runs, plan = accepted
  roots = completed(accepted)
  before = metadata(ws)
  monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("expired read waited"))
  deadline = _REAL_NS() - 1
  with held(roots[kind]):
    with pytest.raises(Conflict):
      client.status_stop(ws, batch_id=args["batch_id"], deadline_ns=deadline)
  result = client.status_stop(ws, batch_id=args["batch_id"], deadline_ns=deadline)
  assert result["status"] == "stopped" and result["protected"] is False
  assert metadata(ws) == before


@pytest.mark.parametrize("kind", ["owner", "inbox", "journal"])
def test_independent_status_retains_nonblocking_read(accepted, monkeypatch, kind):
  ws, registry, args, runs, plan = accepted
  roots = completed(accepted)
  before = metadata(ws)
  monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("default status waited"))
  with held(roots[kind]):
    with pytest.raises(Conflict):
      client.status_stop(ws, batch_id=args["batch_id"])
  assert metadata(ws) == before


@pytest.mark.parametrize("release", [True, False])
@pytest.mark.parametrize("response_loss", [False, True])
def test_execute_final_read_never_repeats_durable_close_or_publication(fresh, clock, monkeypatch, release, response_loss):
  ws, registry, args, runs, plan = fresh
  monkeypatch.setattr(time, "monotonic_ns", _REAL_NS)
  monkeypatch.setattr(time, "sleep", _REAL_SLEEP)
  monkeypatch.setattr(client, "ControlDeadline", ControlDeadline)
  clock.exited = True
  original_publish, original_close = client.publish_request, completion.close_stop
  published, closed, deadlines = [], [], []
  with ExitStack() as locks:
    def publish(workspace, value, **kwargs):
      published.append(value)
      original_publish(workspace, value, **kwargs)
      registry.finish_current(value["run_id"], MANAGER,
        run_owners.ReleaseObservation(value["run_id"], MANAGER, True, True))
    def close_once(*args, **kwargs):
      closed.append(kwargs)
      result = original_close(*args, **kwargs)
      locks.enter_context(held(registry.root, release=release))
      if response_loss:
        raise OSError("synthetic-private-canary")
      return result
    original_status = client.status_stop
    def status(*args, **kwargs):
      if closed:
        deadlines.append(kwargs.get("deadline_ns"))
      return original_status(*args, **kwargs)
    monkeypatch.setattr(client, "publish_request", publish)
    monkeypatch.setattr(completion, "close_stop", close_once)
    monkeypatch.setattr(client, "status_stop", status)
    result = execute(fresh)
  assert len(closed) == 1 and len(published) == 2
  assert deadlines and all(value == published[0]["deadline_ns"] for value in deadlines)
  assert result["status"] == ("stopped" if release else "unknown")
  assert completion.read_close(registry, result["batch_id"])["reason"] == "stopped"
  assert run_stop_fence.read(registry) is None
  observed = client.status_stop(ws, batch_id=result["batch_id"])
  assert observed["status"] == "stopped" and observed["protected"] is False
  assert all(row["request"] == "posted" for row in observed["targets"])
