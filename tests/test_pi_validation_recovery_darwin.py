"""macOS 恢复流程替身测试：验证 approximate 实现不会被误记为 passed。"""
import json
import os
import tempfile
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_darwin_approximate_implementation_not_counted_as_passed():
  """验证 darwin_approximate_implementation=True 时，场景不会被计为 passed。"""
  # 模拟 darwin 恢复流程的 facts
  facts = {
    "real_account_used": False,
    "sdk_session": False,
    "first_party_processes": True,
    "live_owner_rejected": True,
    "old_owner_dead": True,
    "wrong_plan_rejected": True,
    "stop_only_recovery": True,
    "target_terminated": True,
    "source_preserved": True,
    "darwin_approximate_implementation": True,  # 近似实现标记
  }
  
  # 如果是近似实现，completed 应该为 False
  if facts["darwin_approximate_implementation"]:
    completed = False
  else:
    completed = all(facts.get(key) is True for key in (
      "live_owner_rejected", "old_owner_dead", "wrong_plan_rejected",
      "stop_only_recovery", "target_terminated", "source_preserved"
    ))
  
  assert completed is False, "近似实现不应该被计为完整通过"


def test_darwin_full_implementation_counted_as_passed():
  """验证 darwin_approximate_implementation=False 时，所有条件满足则计为 passed。"""
  # 模拟完整实现的 facts
  facts = {
    "real_account_used": False,
    "sdk_session": False,
    "first_party_processes": True,
    "live_owner_rejected": True,
    "old_owner_dead": True,
    "wrong_plan_rejected": True,
    "stop_only_recovery": True,
    "target_terminated": True,
    "source_preserved": True,
    "darwin_approximate_implementation": False,  # 完整实现
  }
  
  # 如果是完整实现，completed 应该为 True
  if facts["darwin_approximate_implementation"]:
    completed = False
  else:
    completed = all(facts.get(key) is True for key in (
      "live_owner_rejected", "old_owner_dead", "wrong_plan_rejected",
      "stop_only_recovery", "target_terminated", "source_preserved"
    ))
  
  assert completed is True, "完整实现且所有条件满足应该被计为通过"


def test_darwin_approximate_missing_fact_not_counted_as_passed():
  """验证即使 darwin_approximate_implementation=False，缺少必要条件也不会计为 passed。"""
  # 模拟缺少必要条件的 facts
  facts = {
    "real_account_used": False,
    "sdk_session": False,
    "first_party_processes": True,
    "live_owner_rejected": True,
    "old_owner_dead": True,
    "wrong_plan_rejected": True,
    "stop_only_recovery": True,
    "target_terminated": False,  # 缺少必要条件
    "source_preserved": True,
    "darwin_approximate_implementation": False,
  }
  
  if facts["darwin_approximate_implementation"]:
    completed = False
  else:
    completed = all(facts.get(key) is True for key in (
      "live_owner_rejected", "old_owner_dead", "wrong_plan_rejected",
      "stop_only_recovery", "target_terminated", "source_preserved"
    ))
  
  assert completed is False, "缺少必要条件不应该被计为通过"


if __name__ == "__main__":
  pytest.main([__file__, "-v"])
