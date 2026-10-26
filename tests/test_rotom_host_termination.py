"""仅 fake pidfd 和 fake signal API；不创建、扫描或控制真实进程。"""

from copy import copy, deepcopy
import pickle

import pytest

from agentcfg import spawned_host as host
from agentcfg.storage import Conflict
from test_rotom_spawned_host import fake, capture, stat


@pytest.fixture
def channel(fake, monkeypatch):
  fake.sent = []
  def send(*args): fake.sent.append(args)
  monkeypatch.setattr(host.signal, "SIGTERM", 15, raising=False)
  monkeypatch.setattr(host.signal, "pidfd_send_signal", send, raising=False)
  return fake


def test_only_original_pidfd_receives_one_sigterm_and_remains_observable(channel):
  handle = capture(channel)
  assert handle.send_sigterm_once() is None
  assert channel.sent == [(77, 15, None, 0)]
  assert channel.opens == [(202, 0)] and channel.closes == []
  assert handle.snapshot()["identity"]["pid"] == 202
  with pytest.raises(Conflict): handle.send_sigterm_once()
  assert channel.sent == [(77, 15, None, 0)]
  handle.close(); assert channel.closes == [77]


@pytest.mark.parametrize("kind", [OSError, ProcessLookupError, InterruptedError, RuntimeError, KeyboardInterrupt, SystemExit])
def test_unknown_send_result_is_consumed_and_never_retried(channel, monkeypatch, kind):
  handle = capture(channel); error = kind("synthetic-private-canary")
  def failed(*args):
    channel.sent.append(args)
    raise error
  monkeypatch.setattr(host.signal, "pidfd_send_signal", failed)
  with pytest.raises(kind if kind in (KeyboardInterrupt, SystemExit) else Conflict) as caught:
    handle.send_sigterm_once()
  if kind in (KeyboardInterrupt, SystemExit): assert caught.value is error
  else: assert "synthetic-private-canary" not in str(caught.value)
  with pytest.raises(Conflict): handle.send_sigterm_once()
  assert channel.sent == [(77, 15, None, 0)] and channel.closes == []


@pytest.mark.parametrize("change", ["closed", "pid", "exited", "birth", "ppid", "manager", "thread", "handler", "event", "boot"])
def test_changed_identity_or_lifecycle_never_reaches_signal_api(channel, change):
  handle = capture(channel)
  if change == "closed": handle.close()
  elif change == "pid": channel.child.pid = 303
  elif change == "exited": channel.child.returncode = 0
  elif change == "birth": channel.stat = stat(start="100")
  elif change == "ppid": channel.stat = stat(ppid=303)
  elif change == "manager": channel.manager["birth_id"] += "0"
  elif change == "thread": channel.threads = 2
  elif change == "handler": channel.handler = object()
  elif change == "event": channel.events = [(77, 1)]
  else: channel.boot = "22345678-1234-1234-1234-123456789abc"
  with pytest.raises(Conflict): handle.send_sigterm_once()
  assert channel.sent == [] and channel.opens == [(202, 0)]
  with pytest.raises(Conflict): handle.send_sigterm_once()


def test_missing_native_api_has_no_pid_or_process_group_fallback(channel, monkeypatch):
  handle = capture(channel)
  monkeypatch.delattr(host.signal, "pidfd_send_signal")
  with pytest.raises(Conflict): handle.send_sigterm_once()
  monkeypatch.setattr(host.signal, "pidfd_send_signal", lambda *args: channel.sent.append(args), raising=False)
  with pytest.raises(Conflict): handle.send_sigterm_once()
  assert channel.sent == []


@pytest.mark.parametrize("result", [False, True, 0, "synthetic-unconfirmed"])
def test_unexpected_api_response_is_not_success_or_retry_permission(channel, monkeypatch, result):
  handle = capture(channel)
  def send(*args): channel.sent.append(args); return result
  monkeypatch.setattr(host.signal, "pidfd_send_signal", send)
  with pytest.raises(Conflict): handle.send_sigterm_once()
  with pytest.raises(Conflict): handle.send_sigterm_once()
  assert channel.sent == [(77, 15, None, 0)]


def test_reentrant_request_cannot_send_twice(channel, monkeypatch):
  handle = capture(channel)
  def send(*args):
    channel.sent.append(args)
    with pytest.raises(Conflict): handle.send_sigterm_once()
  monkeypatch.setattr(host.signal, "pidfd_send_signal", send)
  handle.send_sigterm_once()
  assert channel.sent == [(77, 15, None, 0)]


def test_copy_and_serialization_cannot_duplicate_descriptor_or_once_state(channel):
  handle = capture(channel)
  assert copy(handle) is deepcopy(handle) is handle
  with pytest.raises(TypeError): pickle.dumps(handle)
  copy(handle).send_sigterm_once()
  with pytest.raises(Conflict): deepcopy(handle).send_sigterm_once()
  copy(handle).close(); handle.close()
  assert channel.sent == [(77, 15, None, 0)] and channel.closes == [77]
