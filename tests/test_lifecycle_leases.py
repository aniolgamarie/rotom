"""用共享 open-file-description 模拟继承 FD，不启动任何宿主。"""

import os
from types import SimpleNamespace

import pytest

from agentcfg.lifecycle import guard as directory_guard
from agentcfg.omp_identity import lifecycle_guard as omp_guard
from agentcfg.storage import Conflict


@pytest.fixture(params=[directory_guard, omp_guard], ids=["directory", "omp-file"])
def physical_guard(tmp_path, request):
  workspace = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    profile="synthetic-profile", binding={"machine": "synthetic", "local": str(tmp_path / "local.toml"),
      "profile": "synthetic-profile"})
  with request.param(workspace, create=True):
    pass
  return lambda **kwargs: request.param(workspace, create=False, **kwargs)


@pytest.mark.parametrize("exceptional", [False, True])
def test_inherited_description_keeps_lease_after_manager_scope(physical_guard, exceptional):
  inherited = None
  try:
    def run_scope():
      nonlocal inherited
      with physical_guard(shared=True) as fd:
        inherited = os.dup(fd)
        if exceptional:
          raise ValueError("synthetic manager failure")
    if exceptional:
      with pytest.raises(ValueError, match="synthetic manager failure"):
        run_scope()
    else:
      run_scope()
    # dup 与继承 FD 共享同一 open-file-description；父作用域不得主动解锁它。
    with pytest.raises(Conflict):
      with physical_guard():
        pass
    with physical_guard(shared=True):
      pass
  finally:
    if inherited is not None:
      os.close(inherited)
  with physical_guard():
    pass


def test_normal_scope_closes_its_descriptor_and_releases_without_inheritors(physical_guard):
  with physical_guard() as fd:
    os.fstat(fd)
  with pytest.raises(OSError):
    os.fstat(fd)
  with physical_guard():
    pass
