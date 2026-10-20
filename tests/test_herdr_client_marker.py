"""首帧固定 marker 只做瞬时匹配，不保留终端正文。"""
import pytest

from test_herdr_client_detach import client
from test_herdr_geometry import geometry


def test_marker_fragmented_only_target_fd_and_bounded_tail(geometry, client):
  process, master, pinned, state, _ = client
  marker = b"RBREADY:" + b"a" * 32
  chunks = [(master, b"private-junk" * 10000), (master + 1, marker),
    (master, marker[:11]), (master, marker[11:29]), (master, marker[29:] + b"\n")]
  tails = []
  def pump(observer):
    state["clock"] += 0.01
    fd, chunk = chunks.pop(0)
    observer(fd, chunk)
    cells = dict(zip(observer.__code__.co_freevars, observer.__closure__))
    tails.append(len(cells["tail"].cell_contents))
  assert geometry.wait_owned_client_marker(process, master, run_id="a" * 32, pump=pump) is None
  assert not chunks and max(tails) <= 39
  assert not state["writes"]
  assert ("inheritable", pinned, False) in state["events"]
  assert [item for item in state["events"] if item[0] == "close"] == [("close", pinned)]


@pytest.mark.parametrize("kind", ["wrong_run", "other_fd", "dead", "reused", "timeout", "pump_timeout", "bad_pty"])
def test_marker_refuses_uncertain_identity_or_missing_marker(geometry, client, monkeypatch, kind):
  process, master, pinned, state, _ = client
  def pump(observer):
    state["clock"] += 0.01
    observer(master, b"RBREADY:" + b"b" * 32)
  if kind == "dead":
    process.returncode = 0
  elif kind == "reused":
    calls = iter([456, 457])
    monkeypatch.setattr(geometry, "_process_start", lambda pid: next(calls))
  elif kind == "other_fd":
    def pump(observer):
      state["clock"] += 0.01
      observer(master + 1, b"RBREADY:" + b"a" * 32)
  elif kind == "timeout":
    def pump(observer):
      state["clock"] += 0.01
  elif kind == "pump_timeout":
    def pump(observer):
      state["clock"] += 1
      observer(master, b"RBREADY:" + b"a" * 32)
  elif kind == "bad_pty":
    state["tty"] = False
  with pytest.raises(geometry.GeometryError):
    geometry.wait_owned_client_marker(process, master, run_id="a" * 32, pump=pump, timeout=0.05)
  assert not state["writes"]
  assert [item for item in state["events"] if item[0] == "close"] == [("close", pinned)]


@pytest.mark.parametrize("run", [None, "a" * 31, "A" * 32, "a" * 32 + "\n"])
def test_marker_invalid_run_never_observes(geometry, client, run):
  process, master, pinned, state, _ = client
  with pytest.raises(geometry.GeometryError):
    geometry.wait_owned_client_marker(process, master, run_id=run, pump=lambda callback: pytest.fail("invalid run"))
  assert not state["writes"]


def test_marker_rejects_exit_during_pump_even_with_match(geometry, client):
  process, master, pinned, state, _ = client
  def pump(observer):
    observer(master, b"RBREADY:" + b"a" * 32)
    process.returncode = 0
  with pytest.raises(geometry.GeometryError):
    geometry.wait_owned_client_marker(process, master, run_id="a" * 32, pump=pump)
  assert ("close", pinned) in state["events"]


@pytest.mark.parametrize("ready, failure", [(False, False), (True, False), (True, True)])
def test_attach_waits_only_record_after_route_and_retains_failed_owned_ui(monkeypatch, ready, failure):
  import os
  from test_herdr_benchmark import bench
  events, clients, spawns = [], [], []
  process = object()
  def route(*args):
    events.append("route")
    return ["herdr", "--session", "fake"], {}
  def spawn(*args, **kwargs):
    events.append("spawn")
    return process
  def pump(registered, timeout, observer=None):
    assert registered is clients and timeout == 0.005
    observer(clients[-1][1], b"RBREADY:" + b"a" * 32)
    return 40
  def wait(owned, master, *, run_id, pump):
    assert events == ["route", "spawn", "route"]
    assert owned is process and clients == [(process, master)] and spawns[0][0] is process
    assert run_id == "a" * 32
    observed = []
    pump(lambda fd, chunk: observed.append((fd, chunk)))
    assert observed == [(master, b"RBREADY:" + b"a" * 32)]
    events.append("marker")
    if failure:
      raise bench.GeometryError("owned_client_marker_timeout")
  monkeypatch.setattr(bench, "interactive_client_route", route)
  monkeypatch.setattr(bench.subprocess, "Popen", spawn)
  monkeypatch.setattr(bench, "pump_owned_ptys", pump)
  monkeypatch.setattr(bench, "wait_owned_client_marker", wait)
  try:
    def attach():
      bench.attach_interactive("herdr", "fake", {}, None, None, clients, spawns, 120, 40,
        ready_run_id="a" * 32 if ready else None)
    if failure:
      with pytest.raises(bench.BenchError) as error:
        attach()
      assert error.value.code == 5 and error.value.reason == "owned_client_marker_timeout"
    else:
      attach()
    assert clients[0][0] is process and spawns[0][0] is process
    os.fstat(clients[0][1])
    assert events == ["route", "spawn", "route"] + (["marker"] if ready else [])
  finally:
    for owned, master in clients:
      os.close(master)


def test_pump_observer_only_receives_new_bytes_from_owned_fds():
  import os
  from test_herdr_benchmark import bench
  read_fd, write_fd = os.pipe()
  os.set_blocking(read_fd, False)
  rows = []
  try:
    os.write(write_fd, b"fixed-marker-fragment")
    assert bench.pump_owned_ptys([(None, read_fd)], observer=lambda fd, chunk: rows.append((fd, chunk))) == 21
    assert rows == [(read_fd, b"fixed-marker-fragment")]
    assert bench.pump_owned_ptys([(None, read_fd)], observer=lambda *args: pytest.fail("cached bytes")) == 0
  finally:
    os.close(read_fd)
    os.close(write_fd)


@pytest.mark.parametrize("timeout", [0, -1, 6, True, float("inf")])
def test_marker_invalid_deadline_never_pumps(geometry, client, timeout):
  process, master, pinned, state, _ = client
  with pytest.raises(geometry.GeometryError):
    geometry.wait_owned_client_marker(process, master, run_id="a" * 32,
      pump=lambda callback: pytest.fail("invalid deadline"), timeout=timeout)
  assert not state["writes"]


def test_marker_checks_pinned_identity_after_pump(geometry, client, monkeypatch):
  process, master, pinned, state, _ = client
  fstat = geometry.os.fstat
  def replaced(fd):
    value = fstat(fd)
    if fd == pinned and state["clock"]:
      value.st_rdev += 1
    return value
  monkeypatch.setattr(geometry.os, "fstat", replaced)
  def pump(observer):
    state["clock"] += 0.01
    observer(master, b"RBREADY:" + b"a" * 32)
  with pytest.raises(geometry.GeometryError):
    geometry.wait_owned_client_marker(process, master, run_id="a" * 32, pump=pump)
  assert ("close", pinned) in state["events"] and ("close", master) not in state["events"]
