"""运行登记的祖先持久化门禁；真实临时文件、假宿主，不发信号。"""

import json
import os

import pytest

from agentcfg import run_owners, runtime
from agentcfg.storage import Conflict
from test_rotom_run_records import MANAGER, store
from test_rotom_omp_cooperative_launch import case, install
from test_rotom_resource_owners import owner_path


def register(store, version):
  if version == 1: return store.registry.register(MANAGER)
  return store.registry.register_v2(MANAGER, store.metadata)


@pytest.mark.parametrize("version", [1, 2])
def test_registration_syncs_parent_after_record_before_return(store, monkeypatch, version):
  parent = store.registry.root.parent.stat(); fsync = os.fsync; seen = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
      assert len(list(store.registry.root.glob("*.json"))) == 1
      seen.append(True)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  run_id = register(store, version)
  assert seen == [True] and run_id in store.registry.snapshot()


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_registration_parent_sync_failure_preserves_active_fact(store, monkeypatch, version, kind):
  parent = store.registry.root.parent.stat(); fsync = os.fsync; error = kind("synthetic-private-canary")
  def failed(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino): raise error
    return fsync(fd)
  with monkeypatch.context() as patch:
    patch.setattr(os, "fsync", failed)
    with pytest.raises(Conflict if kind is OSError else kind) as caught: register(store, version)
  if kind is OSError: assert "synthetic-private-canary" not in str(caught.value)
  else: assert caught.value is error
  record, = store.registry.snapshot().values()
  assert run_owners.record_state(record) == "active"


@pytest.mark.parametrize("version", [1, 2])
def test_registration_cannot_return_owner_from_replaced_root(store, monkeypatch, version):
  root = store.registry.root; parent = root.parent.stat(); fsync = os.fsync; seen = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino) and not seen:
      seen.append(True); root.rename(root.with_name("saved-owners")); root.mkdir(mode=0o700)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  with pytest.raises(Conflict): register(store, version)
  assert seen and list(root.iterdir()) == []


@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_omp_owner_sync_failure_keeps_pending_and_record_without_spawn(case, monkeypatch, fake_subprocess, kind):
  install(case, monkeypatch)
  root = case.ws.state_root / "run-owners"; parent = root.parent.stat()
  fsync = os.fsync; error = kind("synthetic-private-canary"); seen = []
  def failed(fd):
    info = os.fstat(fd)
    if ((info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino)
        and root.exists() and list(root.glob("*.json"))):
      state = json.loads((case.domain.root / "coordination.json").read_bytes())
      entry, = state["reservations"].values()
      assert entry["phase"] == "owner_pending"
      seen.append(True); raise error
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", failed)
  with pytest.raises(Conflict if kind is OSError else kind) as caught: runtime.run(case.ws, cwd=case.cwd)
  if kind is OSError: assert "synthetic-private-canary" not in str(caught.value)
  else: assert caught.value is error
  assert seen == [True] and fake_subprocess.calls == [] and "observe" not in case.trace
  entry, = case.domain.snapshot()["reservations"].values()
  assert entry["phase"] == "owner_pending" and owner_path(case.ws, entry["run_id"]).exists()


def test_omp_owner_parent_sync_precedes_dispatch_and_spawn(case, monkeypatch, fake_subprocess):
  install(case, monkeypatch)
  root = case.ws.state_root / "run-owners"; parent = root.parent.stat(); fsync = os.fsync; seen = []
  def sync(fd):
    info = os.fstat(fd)
    if ((info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino)
        and root.exists() and list(root.glob("*.json"))):
      state = json.loads((case.domain.root / "coordination.json").read_bytes())
      entry, = state["reservations"].values()
      assert entry["phase"] == "owner_pending" and fake_subprocess.calls == []
      seen.append(True)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  fake_subprocess.queue(returncode=23)
  assert runtime.run(case.ws, cwd=case.cwd) == 23
  assert seen == [True] and len(fake_subprocess.calls) == 1
