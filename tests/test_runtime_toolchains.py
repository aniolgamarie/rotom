"""宿主公开最低版本与既有同 major 契约分别验证。"""

import pytest

from agentcfg.process import DependencyError
from agentcfg.toolchain import compatible_toolchain


@pytest.mark.parametrize("actual", ["v22.19.0", "v22.20.1", "v24.14.0", "v25.0.0"])
def test_minimum_toolchain_accepts_supported_stable_node(actual):
  from agentcfg.toolchain import ensure_minimum_toolchain
  ensure_minimum_toolchain("Node", "v22.19.0", actual)


@pytest.mark.parametrize("actual", ["v22.18.9", "v21.99.99", "v22.19.0-rc.1", "22.19.0", "secret-sentinel"])
def test_minimum_toolchain_rejects_old_or_nonstable_output_without_leaking(actual):
  from agentcfg.toolchain import ensure_minimum_toolchain
  with pytest.raises(DependencyError) as caught:
    ensure_minimum_toolchain("Node", "v22.19.0", actual)
  assert "secret-sentinel" not in str(caught.value)


def test_minimum_does_not_change_legacy_same_major_policy():
  assert not compatible_toolchain("Node", "v24.14.0", "v22.19.0")
  assert not compatible_toolchain("Node", "v24.0.0", "v24.14.0")
  assert compatible_toolchain("Node", "v24.14.0", "v24.2.0")
