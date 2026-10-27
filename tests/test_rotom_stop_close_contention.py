"""停止收尾只在首个写入前等待短锁；不重发信号或重试写后未知。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import time

import pytest

from agentcfg import dsh_stop_completion as completion, run_stop_fence
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_stop_completion import accepted, finish
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


def test_close_waits_before_write_for_owner_query_in_original_budget(accepted):
  ws, registry, args, runs, plan = accepted
  finish(accepted)
  entered = threading.Event()
  release = threading.Event()
  def query():
    with registry._locked(nonblocking=True):
      entered.set()
      assert release.wait(3)
  with ThreadPoolExecutor(max_workers=1) as pool:
    holder = pool.submit(query)
    assert entered.wait(3)
    timer = threading.Timer(0.08, release.set)
    timer.start()
    try:
      value = completion.close_stop(ws, batch_id=args["batch_id"], plan_id=plan["plan_id"],
        reason="stopped", deadline_ns=time.monotonic_ns() + 1_000_000_000)
    finally:
      release.set()
      timer.join()
      holder.result(timeout=3)
  assert value["reason"] == "stopped"
  assert run_stop_fence.read(registry) is None


def test_expired_close_does_not_write_or_remove_fence(accepted, monkeypatch):
  ws, registry, args, runs, plan = accepted
  finish(accepted)
  monkeypatch.setattr(Tree, "write_new", lambda *args: pytest.fail("expired close wrote"))
  with pytest.raises(Conflict):
    completion.close_stop(ws, batch_id=args["batch_id"], plan_id=plan["plan_id"], reason="stopped",
      deadline_ns=time.monotonic_ns() - 1)
  assert run_stop_fence.read(registry) is not None


def test_close_after_write_error_is_not_retried(accepted, monkeypatch):
  ws, registry, args, runs, plan = accepted
  finish(accepted)
  original = Tree.write_new
  writes = []
  def write(tree, name, data):
    writes.append(name)
    original(tree, name, data)
    raise OSError("synthetic write acknowledgement lost")
  monkeypatch.setattr(Tree, "write_new", write)
  with pytest.raises(Conflict):
    completion.close_stop(ws, batch_id=args["batch_id"], plan_id=plan["plan_id"], reason="stopped",
      deadline_ns=time.monotonic_ns() + 1_000_000_000)
  assert len(writes) == 1
  assert (ws.state_root / completion.close_name(registry, args["batch_id"])).is_file()
  assert run_stop_fence.read(registry) is not None
