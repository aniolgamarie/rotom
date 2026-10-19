"""候选验收用的合成执行者；只定义边界，不证明任何第三方实现遵守。

没有生产调度器、进程、磁盘协议或工具执行。T068/T069须将同一场景连接
获准候选的公开接口；本文件不能抵扣这两个集成任务。
"""

from dataclasses import dataclass, field

import pytest


@dataclass
class FakeInvestigation:
  parent_run_ref: str
  task_ref: str
  model_request: str
  model_observed: str = "unknown"
  execution: str = "running"
  cancellation: str = "not_requested"
  process: str = "active"
  effects: str = "unknown"
  result: str = "missing"


@dataclass
class CandidateAcceptanceDouble:
  """测试资料中的预期行为；不作为可接入生产的执行库。"""

  tasks: dict = field(default_factory=dict)

  def request(self, parent, task, *, depth=0, tools=("read", "search"), background=False):
    if depth or background or set(tools) - {"read", "search"}:
      return "rejected"
    occupied = sum(row.parent_run_ref == parent and row.process != "exited_confirmed"
      for row in self.tasks.values())
    if occupied >= 2 or task in self.tasks:
      return "rejected"
    self.tasks[task] = FakeInvestigation(parent, task, "fictional-model")
    return "accepted"


def test_contract_two_main_runs_have_two_independent_slots_each():
  candidate = CandidateAcceptanceDouble()
  for parent in ("main-a", "main-b"):
    assert candidate.request(parent, parent + "-1") == "accepted"
    assert candidate.request(parent, parent + "-2") == "accepted"
    assert candidate.request(parent, parent + "-3") == "rejected"
  assert len(candidate.tasks) == 4
  assert {row.parent_run_ref for row in candidate.tasks.values()} == {"main-a", "main-b"}


@pytest.mark.parametrize("process", ["active", "unknown"])
@pytest.mark.parametrize("cancellation", ["requested", "acknowledged"])
def test_contract_cancellation_or_unknown_descendants_keep_the_parent_slot(process, cancellation):
  candidate = CandidateAcceptanceDouble()
  for task in ("one", "two"):
    candidate.request("main-a", task)
  candidate.tasks["one"].cancellation = cancellation
  candidate.tasks["one"].process = process
  candidate.tasks["one"].execution = "unknown"
  assert candidate.request("main-a", "three") == "rejected"
  assert candidate.request("main-b", "other") == "accepted"
  candidate.tasks["one"].process = "exited_confirmed"
  assert candidate.request("main-a", "three") == "accepted"


@pytest.mark.parametrize("options", [{"depth": 1}, {"background": True},
  {"tools": ("read", "write")}, {"tools": ("bash",)},
  {"tools": ("codemode-unrestricted",)}, {"tools": ("mcp-write",)},
  {"tools": ("resume-unreviewed-tools",)}])
def test_contract_rejects_recursive_background_and_indirect_write_routes_before_execution(options):
  candidate = CandidateAcceptanceDouble()
  assert candidate.request("main-a", "task", **options) == "rejected"
  assert candidate.tasks == {}


@pytest.mark.parametrize("result", ["missing", "empty", "truncated", "complete"])
def test_contract_model_result_and_process_observations_are_independent(result):
  candidate = CandidateAcceptanceDouble()
  candidate.request("main-a", "current-task")
  row = candidate.tasks["current-task"]
  row.result = result
  row.cancellation = "acknowledged"
  row.process = "unknown"
  assert row.model_observed == "unknown"
  assert row.execution == "running" and row.effects == "unknown"
  assert row.task_ref == "current-task" and row.parent_run_ref == "main-a"
  assert row.model_request == "fictional-model"
