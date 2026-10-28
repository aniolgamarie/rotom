"""恢复准备预算不能随逐项操作或 socket 分段响应续期。"""
import pytest

from termcfg.errors import TermcfgError


def test_remaining_shares_absolute_budget_and_local_cap():
  from rotom.restore_deadline import ReadyDeadline
  now = [10.0]
  deadline = ReadyDeadline(120, clock=lambda: now[0])
  assert deadline.expires_at == 130
  assert deadline.deadline_ns == 130_000_000_000
  assert deadline.remaining(3) == 3
  now[0] = 129.5
  assert deadline.remaining(3) == 0.5
  now[0] = 130
  assert deadline.expired
  with pytest.raises(TermcfgError) as error:
    deadline.remaining()
  assert (error.value.code, error.value.reason) == (4, "restore_ready_timeout")


def test_bootstrap_preserves_exact_absolute_deadline():
  from rotom.restore_deadline import ReadyDeadline
  now = [10.0]
  deadline = ReadyDeadline.from_expires_at_ns(150_123_456_789, clock=lambda: now[0])
  assert deadline.deadline_ns == 150_123_456_789
  now[0] = 150.123456789
  with pytest.raises(TermcfgError):
    deadline.remaining()


@pytest.mark.parametrize("values", [[10, 9], [10, float("nan")], [10, "invalid"]])
def test_clock_fault_is_fixed_restore_error(values):
  from rotom.restore_deadline import ReadyDeadline
  clock = iter(values)
  deadline = ReadyDeadline(clock=lambda: next(clock))
  with pytest.raises(TermcfgError) as error:
    deadline.remaining()
  assert (error.value.code, error.value.reason) == (4, "restore_ready_timeout")
