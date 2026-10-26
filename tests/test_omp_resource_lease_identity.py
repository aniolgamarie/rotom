"""只操作临时文件描述符，验证共享运行包租约的命名身份边界。"""

import fcntl
import os
from types import SimpleNamespace

import pytest

from agentcfg.omp_dependencies import OmpBackend
from agentcfg.storage import Conflict


@pytest.mark.parametrize("exclusive", [False, True])
@pytest.mark.parametrize("change", ["replace", "unlink", "replace-parent"])
def test_runtime_guard_rejects_named_lease_changed_after_flock(tmp_path, monkeypatch, exclusive, change):
  workspace = SimpleNamespace(cache=tmp_path / "cache")
  lock = workspace.cache / "leases/synthetic-runtime.lock"
  actual_flock = fcntl.flock
  locked = []

  def replace_after_lock(fd, flags):
    actual_flock(fd, flags)
    locked.append(fd)
    if change == "replace-parent":
      lock.parent.rename(workspace.cache / "old-leases")
      lock.parent.mkdir(mode=0o700)
    else:
      lock.rename(lock.with_name("old-runtime.lock"))
    if change != "unlink":
      replacement = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
      os.close(replacement)

  monkeypatch.setattr(fcntl, "flock", replace_after_lock)
  yielded = False
  with pytest.raises(Conflict):
    with OmpBackend().runtime_guard(workspace, "synthetic-runtime", exclusive=exclusive):
      yielded = True
  assert not yielded
  assert len(locked) == 1
  with pytest.raises(OSError):
    os.fstat(locked[0])


def test_shared_cache_leases_exclude_repair_across_instance_state_roots(tmp_path):
  first = SimpleNamespace(cache=tmp_path / "cache", instance=tmp_path / "instance-a", state_root=tmp_path / "state-a")
  second = SimpleNamespace(cache=first.cache, instance=tmp_path / "instance-b", state_root=tmp_path / "state-b")
  backend = OmpBackend()
  with backend.runtime_guard(first, "synthetic-runtime") as left:
    with backend.runtime_guard(second, "synthetic-runtime") as right:
      assert (os.fstat(left).st_dev, os.fstat(left).st_ino) == (os.fstat(right).st_dev, os.fstat(right).st_ino)
      with pytest.raises(Conflict):
        with backend.runtime_guard(second, "synthetic-runtime", exclusive=True):
          pytest.fail("shared cache must retain the existing physical lease")
  with backend.runtime_guard(second, "synthetic-runtime", exclusive=True):
    pass
  assert not first.instance.exists() and not second.instance.exists()
  assert not first.state_root.exists() and not second.state_root.exists()


@pytest.mark.parametrize("exceptional", [False, True])
def test_runtime_lease_remains_held_by_inherited_description(tmp_path, exceptional):
  workspace = SimpleNamespace(cache=tmp_path / "cache")
  backend = OmpBackend()
  inherited = None
  try:
    try:
      with backend.runtime_guard(workspace, "synthetic-runtime") as fd:
        inherited = os.dup(fd)
        if exceptional:
          raise ValueError("synthetic scope exit")
    except ValueError:
      assert exceptional
    with pytest.raises(Conflict):
      with backend.runtime_guard(workspace, "synthetic-runtime", exclusive=True):
        pytest.fail("manager scope must not unlock an inherited description")
  finally:
    if inherited is not None:
      os.close(inherited)
  with backend.runtime_guard(workspace, "synthetic-runtime", exclusive=True):
    pass
