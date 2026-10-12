"""Shell 共享控制面并发边界：真实租约存储、假进程，不执行脚本。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from agentcfg.storage import Conflict
from test_pi_admitted_shell import external, fixture, running_worker, shared_control, shared_prepare


SCRIPT = "printf '%s\\n' 'private race script' | cat > output\nvalue=$(cat output)\nprintf '%s' \"$value\""


def prepared_control(tmp_path):
  f = fixture(tmp_path)
  control, call = shared_control(f)
  prepared = shared_prepare(f, call, private={"command": SCRIPT})
  permit = call("ordinary_admission_issue", {"operation_id": prepared["operation_id"], "context": f[4]})
  return f, control, call, prepared, permit


def consumed_control(tmp_path):
  f, control, call, prepared, permit = prepared_control(tmp_path)
  ticket = call("ordinary_admission_consume", {"permit": permit, "context": f[4]})
  worker = running_worker(f, ticket)
  return f, control, call, prepared, ticket, worker


def assert_one_writer(f, ticket, *, state):
  lease, = external(f)
  assert lease["lease_id"] == ticket["lease_id"]
  planned, = lease["planned_workspaces"]
  writer = f[2].store.workspaces.read(planned)
  assert writer["execution_lease_id"] == lease["lease_id"]
  assert writer["state"] == state
  return lease, writer


def test_concurrent_shell_consume_allocates_exactly_one_real_writer(tmp_path):
  f, control, call, prepared, permit = prepared_control(tmp_path)
  barrier = Barrier(2)
  def consume():
    barrier.wait(timeout=5)
    try:
      return call("ordinary_admission_consume", {"permit": permit, "context": f[4]})
    except Conflict:
      return None
  with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(consume) for _ in range(2)]
    results = [future.result(timeout=10) for future in futures]
  ticket, = [result for result in results if result is not None]
  assert results.count(None) == 1 and ticket["state"] == "consumed"
  lease, _ = assert_one_writer(f, ticket, state="reserved")
  assert lease["state"] == "allocating" and lease["spawn_committed"] is False
  assert control.private_bytes == 0
  assert call("ordinary_admission_status", {"operation_id": prepared["operation_id"]})["execution"] == ticket


def test_concurrent_worker_input_delivers_original_script_exactly_once(tmp_path):
  f, control, call, prepared, ticket, worker = consumed_control(tmp_path)
  barrier = Barrier(2)
  def take():
    barrier.wait(timeout=5)
    try:
      return call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)
    except Conflict:
      return None
  with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(take) for _ in range(2)]
    results = [future.result(timeout=10) for future in futures]
  delivered, = [result for result in results if result is not None]
  assert results.count(None) == 1
  assert delivered["command"].encode("utf-8") == SCRIPT.encode("utf-8")
  assert delivered["lease_id"] == ticket["lease_id"] and delivered["operation_id"] == prepared["operation_id"]
  assert control.shell_bridge.records[prepared["operation_id"]]["private"] is None
  lease, _ = assert_one_writer(f, ticket, state="active")
  assert lease["state"] == "running"


@pytest.mark.parametrize("first", ["cancel", "take"])
def test_cancel_and_private_handoff_obey_both_controlled_orders_without_releasing_writer(tmp_path, first):
  f, control, call, prepared, ticket, worker = consumed_control(tmp_path)
  before_lease, before_writer = assert_one_writer(f, ticket, state="active")
  started = Barrier(2)
  first_done = Event()
  cancel_done = Event()
  def cancel():
    started.wait(timeout=5)
    if first == "take": assert first_done.wait(timeout=5)
    try:
      return call("ordinary_admission_cancel_request", {"control_id": "main-control", "request_id": "real-shell"})
    finally:
      cancel_done.set()
      if first == "cancel": first_done.set()
  def take():
    started.wait(timeout=5)
    if first == "cancel": assert first_done.wait(timeout=5)
    try:
      try:
        return call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)
      except Conflict:
        return None
    finally:
      if first == "take": first_done.set()
  with ThreadPoolExecutor(max_workers=2) as pool:
    cancel_future, take_future = pool.submit(cancel), pool.submit(take)
    canceled = cancel_future.result(timeout=10)
    delivered = take_future.result(timeout=10)
  assert cancel_done.is_set() and canceled["state"] == "canceled"
  if first == "cancel": assert delivered is None
  else: assert delivered["command"].encode("utf-8") == SCRIPT.encode("utf-8")
  with pytest.raises(Conflict):
    call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)
  after_lease, after_writer = assert_one_writer(f, ticket, state="active")
  assert after_lease == before_lease and after_writer == before_writer
  assert control.requests["real-shell"]["state"] == "canceled"
  assert control.shell_bridge.records[prepared["operation_id"]]["private"] is None
