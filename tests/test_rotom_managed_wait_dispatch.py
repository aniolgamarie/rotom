"""候选服务失败后只等待原宿主，保存逐项事实；无真实IPC或进程控制。"""

import pytest

from agentcfg.managed_wait import wait_with_service
from agentcfg.storage import Tree
from test_rotom_managed_wait import StrictChild, timeout
from test_rotom_stop_dispatches import dispatches, RUN


def test_duplicate_service_request_cannot_repeat_fake_signal_or_erase_sent(dispatches):
  case = dispatches
  child = StrictChild(timeout(), timeout(), 17)
  signals, notices = [], []
  def service():
    attempt = case.journal.begin(case.request)
    assert case.journal.read(RUN)["dispatch"] == "unknown"
    # 模拟已成功返回的通道；真实通道尚未接入。
    signals.append(RUN)
    attempt.sent()
  code = wait_with_service(child, service=service, unavailable=lambda: notices.append("unavailable"))
  assert code == 17 and signals == [RUN] and notices == ["unavailable"]
  assert child.calls == [{"timeout": 0.1}, {"timeout": 0.1}, {}]
  assert case.journal.read(RUN)["dispatch"] == "signal_sent"


@pytest.mark.parametrize("failure", ["transport-result", "receipt-before", "receipt-after"])
def test_ambiguous_result_stops_service_preserves_facts_and_waits_same_child(dispatches, monkeypatch, failure):
  case = dispatches
  child = StrictChild(timeout(), -15)
  signals, notices, requests = [], [], []
  write = Tree.write_new
  def receipt(tree, name, *args, **kwargs):
    if name.endswith(".sent.json") and failure == "receipt-before":
      raise OSError("synthetic-private-canary")
    result = write(tree, name, *args, **kwargs)
    if name.endswith(".sent.json") and failure == "receipt-after":
      raise OSError("synthetic-private-canary")
    return result
  def service():
    requests.append(RUN)
    attempt = case.journal.begin(case.request)
    signals.append(RUN)
    if failure == "transport-result":
      raise OSError("synthetic-private-canary")
    attempt.sent()
  monkeypatch.setattr(Tree, "write_new", receipt)
  assert wait_with_service(child, service=service, unavailable=lambda: notices.append("unavailable")) == -15
  assert signals == requests == [RUN] and notices == ["unavailable"]
  assert child.calls == [{"timeout": 0.1}, {}]
  assert case.journal.read(RUN)["dispatch"] == ("signal_sent" if failure == "receipt-after" else "unknown")
