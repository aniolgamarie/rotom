"""阶段共享绝对预算；fake clock，不睡眠、不观察或控制真实进程。"""
import math

import pytest

from agentcfg import control_deadline
from agentcfg.control_deadline import ControlDeadline
from agentcfg.storage import Conflict


class Clock:
  def __init__(self, value=100.0):
    self.value = value
    self.calls = 0

  def __call__(self):
    self.calls += 1
    return self.value


def test_three_items_share_one_thirty_second_absolute_deadline():
  clock = Clock()
  budget = ControlDeadline(clock=clock)
  assert clock.calls == 1
  for item, expected in ((1, 20), (2, 10), (3, 0)):
    clock.value = 100 + item * 10
    assert budget.remaining() == expected
  assert budget.expired() is True and clock.calls == 5
  assert not hasattr(budget, "reset") and not hasattr(budget, "rearm")


def test_polling_does_not_reset_and_expiry_is_exactly_zero():
  clock = Clock(0)
  budget = ControlDeadline(clock=clock)
  values = []
  for point in (0, 0, 0.5, 1, 10, 29.999, 30, 30, 31, 1000000):
    clock.value = point
    values.append(budget.remaining())
  assert values[:5] == [30, 30, 29.5, 29, 20]
  assert values[5] == pytest.approx(0.001)
  assert values[6:] == [0, 0, 0, 0]
  assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("seconds", [1, 30, 300])
def test_explicit_budget_bounds(seconds):
  clock = Clock(0)
  budget = ControlDeadline(seconds, clock=clock)
  assert budget.remaining() == seconds and budget.expired() is False
  clock.value = seconds
  assert budget.expired() is True and budget.remaining() == 0


def test_default_uses_monotonic_once_at_construction(monkeypatch):
  clock = Clock(5)
  monkeypatch.setattr(control_deadline.time, "monotonic", clock)
  budget = ControlDeadline()
  assert clock.calls == 1
  clock.value = 25
  assert budget.remaining() == 10 and clock.calls == 2


def test_ready_phase_is_an_explicit_independent_budget():
  clock = Clock(0)
  stop = ControlDeadline(clock=clock)
  clock.value = 30
  assert stop.expired() is True
  ready = ControlDeadline(clock=clock)
  assert ready.remaining() == 30
  clock.value = 45
  assert ready.remaining() == 15 and stop.remaining() == 0


@pytest.mark.parametrize("seconds", [True, False, None, "30", 30.0, 0, -1, 301, 10 ** 100])
def test_invalid_wait_is_value_error_before_any_clock_access(seconds):
  clock = Clock()
  with pytest.raises(ValueError):
    ControlDeadline(seconds, clock=clock)
  assert clock.calls == 0


def test_int_subclass_wait_is_not_an_exact_int():
  class Seconds(int):
    pass
  clock = Clock()
  with pytest.raises(ValueError):
    ControlDeadline(Seconds(30), clock=clock)
  assert clock.calls == 0


@pytest.mark.parametrize("clock", [False, 1, "synthetic-clock", object()])
def test_clock_must_be_callable(clock):
  with pytest.raises(Conflict) as caught:
    ControlDeadline(clock=clock)
  assert caught.value.exit_code == 4


@pytest.mark.parametrize("value", [True, False, None, "100", object(), math.nan, math.inf, -math.inf, 10 ** 1000])
def test_invalid_clock_value_is_fixed_conflict_at_start_and_later(value):
  clock = Clock(value)
  with pytest.raises(Conflict):
    ControlDeadline(clock=clock)
  clock.value = 0
  budget = ControlDeadline(clock=clock)
  clock.value = value
  with pytest.raises(Conflict):
    budget.remaining()


@pytest.mark.parametrize("start,seconds", [(1e308, 30), (-1e308, 30), (float(2 ** 53), 1)])
def test_unrepresentable_or_nonadvancing_deadline_is_rejected(start, seconds):
  with pytest.raises(Conflict):
    ControlDeadline(seconds, clock=Clock(start))


@pytest.mark.parametrize("poll", ["remaining", "expired"])
def test_clock_backwards_never_increases_or_revives_budget(poll):
  clock = Clock(0)
  budget = ControlDeadline(clock=clock)
  clock.value = 10
  assert budget.remaining() == 20
  clock.value = 9
  with pytest.raises(Conflict):
    getattr(budget, poll)()
  clock = Clock(0)
  budget = ControlDeadline(clock=clock)
  clock.value = 30
  assert budget.expired() is True
  clock.value = 29
  with pytest.raises(Conflict):
    getattr(budget, poll)()


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError, OverflowError])
@pytest.mark.parametrize("stage", ["construction", "poll"])
def test_clock_failure_never_exposes_original_exception(error_type, stage):
  clock = Clock(0)
  budget = ControlDeadline(clock=clock) if stage == "poll" else None
  def broken():
    raise error_type("synthetic-private-clock-canary")
  if budget is not None:
    # 可调用对象保留其身份，故障由同一 clock 实例在后续读取时注入。
    clock.value = None
    clock_type = type(clock)
    original = clock_type.__call__
    def raising(self):
      if self is clock:
        broken()
      return original(self)
    with pytest.MonkeyPatch.context() as patch:
      patch.setattr(clock_type, "__call__", raising)
      with pytest.raises(Conflict) as caught:
        budget.remaining()
  else:
    with pytest.raises(Conflict) as caught:
      ControlDeadline(clock=broken)
  assert "synthetic-private-clock-canary" not in str(caught.value)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("stage", ["construction", "poll"])
def test_control_interrupt_is_the_same_exception_object(error_type, stage):
  interruption = error_type("synthetic-control-interruption")
  calls = []
  def clock():
    calls.append(True)
    if stage == "construction" or len(calls) > 1:
      raise interruption
    return 0
  with pytest.raises(error_type) as caught:
    budget = ControlDeadline(clock=clock)
    budget.expired()
  assert caught.value is interruption


def test_finite_negative_clock_origin_is_allowed():
  clock = Clock(-10)
  budget = ControlDeadline(clock=clock)
  clock.value = 0
  assert budget.remaining() == 20


def test_unrepresentable_remaining_arithmetic_is_not_silent_expiry():
  clock = Clock(-(10 ** 308))
  budget = ControlDeadline(clock=clock)
  clock.value = 1e308
  with pytest.raises(Conflict):
    budget.remaining()
