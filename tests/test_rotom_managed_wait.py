"""严格fake child：无真实子进程、线程、睡眠或信号。"""
import subprocess

import pytest

from agentcfg import managed_wait
from agentcfg.storage import Conflict


class StrictChild:
  def __init__(self, *results):
    self.results = list(results)
    self.calls = []
    self.trace = []

  def wait(self, *args, **kwargs):
    assert not args
    assert not kwargs or set(kwargs) == {"timeout"}
    self.calls.append(dict(kwargs)); self.trace.append("wait")
    assert self.results, "unexpected repeated wait"
    result = self.results.pop(0)
    if isinstance(result, BaseException): raise result
    return result

  def forbidden(self, *args, **kwargs): pytest.fail("no polling/control/IO/context operations")
  poll = kill = terminate = send_signal = communicate = __enter__ = __exit__ = forbidden


def timeout(): return subprocess.TimeoutExpired("synthetic-command", 0.1)


@pytest.mark.parametrize("code", [0, 17, -15])
def test_child_already_exited_returns_original_without_service(code):
  child = StrictChild(code)
  assert managed_wait.wait_with_service(child, service=lambda: pytest.fail("exited child serviced")) == code
  assert child.calls == [{"timeout": 0.1}]


@pytest.mark.parametrize("interval", [0.001, 0.1, 1])
def test_timeouts_service_once_each_and_keep_same_child(interval):
  child = StrictChild(timeout(), timeout(), -9)
  def service(): child.trace.append("service")
  assert managed_wait.wait_with_service(child, service=service, interval=interval) == -9
  assert child.trace == ["wait", "service", "wait", "service", "wait"]
  assert child.calls == [{"timeout": interval}] * 3


@pytest.mark.parametrize("kind", [ValueError, OSError, RuntimeError])
@pytest.mark.parametrize("notify", [False, True])
def test_service_failure_permanently_falls_back_one_wait_and_notice_at_most_once(kind, notify):
  child = StrictChild(timeout(), 23)
  def service(): child.trace.append("service"); raise kind("synthetic-private-canary")
  def unavailable(): child.trace.append("unavailable")
  assert managed_wait.wait_with_service(child, service=service, unavailable=unavailable if notify else None) == 23
  assert child.trace == ["wait", "service"] + (["unavailable"] if notify else []) + ["wait"]
  assert child.calls == [{"timeout": 0.1}, {}]


def test_unavailable_ordinary_error_is_ignored_native_code_preserved(capsys):
  child = StrictChild(timeout(), -15)
  def service(): child.trace.append("service"); raise ValueError("synthetic-private-canary")
  def unavailable(): child.trace.append("unavailable"); raise OSError("synthetic-private-canary")
  assert managed_wait.wait_with_service(child, service=service, unavailable=unavailable) == -15
  assert child.trace == ["wait", "service", "unavailable", "wait"]
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("site", ["wait", "service", "unavailable", "fallback-wait"])
def test_control_exception_is_original_without_more_waits_or_callbacks(kind, site):
  error = kind("synthetic-control")
  child = StrictChild(error) if site == "wait" else StrictChild(timeout(), error if site == "fallback-wait" else 0)
  def service():
    child.trace.append("service")
    raise error if site == "service" else ValueError("synthetic-service-unconfirmed")
  def unavailable():
    child.trace.append("unavailable")
    if site == "unavailable": raise error
  with pytest.raises(kind) as caught:
    managed_wait.wait_with_service(child, service=service, unavailable=unavailable)
  assert caught.value is error
  expected = {"wait": ["wait"], "service": ["wait", "service"],
    "unavailable": ["wait", "service", "unavailable"], "fallback-wait": ["wait", "service", "unavailable", "wait"]}
  assert child.trace == expected[site]


@pytest.mark.parametrize("kind", [ValueError, OSError, ConnectionError])
def test_unexpected_wait_error_is_original_without_service_retry(kind):
  error = kind("synthetic-private-canary")
  child = StrictChild(error)
  with pytest.raises(kind) as caught:
    managed_wait.wait_with_service(child, service=lambda: pytest.fail("wait failed before service"))
  assert caught.value is error and child.calls == [{"timeout": 0.1}]


def test_unexpected_timeout_during_fallback_is_not_retried():
  error = timeout(); child = StrictChild(timeout(), error)
  def service(): child.trace.append("service"); raise ValueError("synthetic-failure")
  with pytest.raises(subprocess.TimeoutExpired) as caught:
    managed_wait.wait_with_service(child, service=service)
  assert caught.value is error and child.calls == [{"timeout": 0.1}, {}]
  assert child.trace == ["wait", "service", "wait"]


@pytest.mark.parametrize("field,value", [("service", None), ("service", True), ("unavailable", 1),
  ("interval", True), ("interval", False), ("interval", 0), ("interval", -0.1), ("interval", 1.001),
  ("interval", "0.1"), ("interval", None), ("interval", float("inf")), ("interval", float("nan")), ("interval", 10**1000)])
def test_invalid_input_fixed_conflict_before_wait_or_callbacks(field, value):
  child = StrictChild(0)
  options = {"service": lambda: pytest.fail("invalid input serviced"),
    "unavailable": lambda: pytest.fail("invalid input callback"), field: value}
  with pytest.raises(Conflict) as caught: managed_wait.wait_with_service(child, **options)
  assert "synthetic-private-canary" not in str(caught.value)
  assert child.calls == [] and child.trace == []
