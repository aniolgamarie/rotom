"""OMP 合作实例只读观察；字段与保护状态分开，不取得包维护或恢复能力。"""
from copy import deepcopy
import importlib
import os
from types import SimpleNamespace

import pytest

from agentcfg import lifecycle, resource_coordination as core, resource_owners, run_owners, runtime
from agentcfg.storage import Conflict
from test_rotom_omp_cooperative_launch import case
from test_rotom_resource_scopes import claim_path


def observation():
  return importlib.import_module("agentcfg.omp_observation")


def read(case):
  module = observation()
  with module.guard(case.ws) as fd:
    return module.snapshot(case.ws, instance_fd=fd)


@pytest.mark.parametrize("complete,expected", [(True, "idle_confirmed"), (False, "unknown")])
def test_saved_cooperative_record_can_be_read_without_mutation(case, fake_subprocess, complete, expected):
  case.control["complete"] = complete
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  before = case.domain.snapshot()
  records, pending = read(case)
  record, = records.values()
  assert run_owners.record_state(record) == expected and pending is False
  assert case.domain.snapshot() == before
  assert record["start_cwd"]["path"] == str(case.cwd)


def test_active_manager_query_does_not_need_package_lock_or_touch_native_files(case, monkeypatch, fake_subprocess):
  import subprocess
  original = subprocess.run
  def child(*args, **kwargs):
    before = case.domain.snapshot()
    records, pending = read(case)
    record, = records.values()
    assert run_owners.record_state(record) == "active" and pending is False
    assert case.domain.snapshot() == before
    return original(*args, **kwargs)
  monkeypatch.setattr(subprocess, "run", child)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0


def test_unattached_reservation_is_visible_as_incomplete_observation(case):
  token = lifecycle.reserve_omp_launch(case.ws, case.lock.identity)
  before = case.domain.snapshot()
  records, pending = read(case)
  assert records == {} and pending is True
  assert case.domain.snapshot() == before
  assert before["reservations"][token.run_id]["phase"] == "reserved"


def test_release_pending_never_becomes_resource_idle_from_owner_alone(case, monkeypatch, fake_subprocess):
  monkeypatch.setattr(resource_owners, "reconcile_owner_release", lambda *a, **k: None)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  records, pending = read(case)
  assert len(records) == 1 and pending is True
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "release_pending"


@pytest.mark.parametrize("damage", ["claim", "domain", "home-anchor", "owner-link", "missing-reservation"])
def test_bad_metadata_never_reads_as_empty_or_repairs(case, fake_subprocess, damage):
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  if damage == "claim":
    claim_path(case.ws).unlink()
  elif damage == "domain":
    (case.domain.root / "coordination.json").unlink()
  elif damage == "home-anchor":
    (case.ws.instance / "user-home/.rotom-resource.json").unlink()
  else:
    with case.domain._transaction(write=True) as state:
      if damage == "missing-reservation":
        state["reservations"].clear()
      else:
        entry = next(iter(state["reservations"].values()))
        entry["owner_link"]["ownership_digest"] = "0" * 64
  before = {p: p.read_bytes() for root in (case.ws.instance, case.ws.state_root, case.domain.root)
    for p in root.rglob("*") if p.is_file()}
  with pytest.raises(Conflict):
    read(case)
  assert {p: p.read_bytes() for root in (case.ws.instance, case.ws.state_root, case.domain.root)
    for p in root.rglob("*") if p.is_file()} == before


def test_historical_fields_do_not_require_current_runtime_anchor(case, fake_subprocess):
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  (case.ws.cache / "leases" / (case.lock.identity + ".lock")).unlink()
  records, pending = read(case)
  assert len(records) == 1 and pending is False
  # 这里只展示元数据；包门禁仍拒绝，查询没有制造替代租约。
  with pytest.raises(Conflict):
    runtime.run(case.ws, cwd=case.cwd)
  assert not (case.ws.cache / "leases" / (case.lock.identity + ".lock")).exists()


def test_owner_lock_contention_never_waits_inside_coordination(case):
  registry = run_owners.Registry(case.ws.state_root / "run-owners", case.ws.binding)
  with registry._locked(create=True):
    with pytest.raises(Conflict):
      read(case)
    with case.domain._transaction(write=True):
      pass


def test_light_observation_context_requires_trusted_explicit_roots(case):
  from agentcfg.workspace import InstanceWorkspace
  ws = case.ws
  light = InstanceWorkspace(ws.agent, ws.profile, ws.local_path, ws.binding["machine"], ws.instance,
    ws.state_root, global_state_root=case.domain.root.parent, cache=ws.cache)
  with observation().guard(light) as fd:
    records, pending = observation().snapshot(light, instance_fd=fd)
  assert records == {} and pending is False
  from dataclasses import replace
  bad = replace(light, global_state_root=case.domain.root.parent.with_name("untrusted"))
  with pytest.raises(Conflict), observation().guard(bad):
    pytest.fail("query must not infer domain root from claim")


def test_reading_history_never_reads_package_or_native_session_contents(case, monkeypatch, fake_subprocess):
  from agentcfg.storage import Tree
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  sentinel = case.ws.instance / "user-home/private-session"
  sentinel.write_bytes(b"synthetic-private-session-canary")
  original = Tree.open_read
  def metadata_only(tree, path, *args, **kwargs):
    assert not tree.root.is_relative_to(case.ws.cache), "查询不得打开运行包或缓存声明"
    assert str(path).split("/")[-1] != sentinel.name, "查询不得读取原生正文"
    return original(tree, path, *args, **kwargs)
  monkeypatch.setattr(Tree, "open_read", metadata_only)
  records, pending = read(case)
  assert len(records) == 1 and not pending
  assert sentinel.read_bytes() == b"synthetic-private-session-canary"


def test_missing_linked_owner_retains_incomplete_fact_without_recreating_record(case, fake_subprocess):
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  entry, = case.domain.snapshot()["reservations"].values()
  path = case.ws.state_root / "run-owners" / (entry["run_id"] + ".json")
  path.unlink()
  before = case.domain.snapshot()
  records, pending = read(case)
  assert records == {} and pending is True
  assert not path.exists() and case.domain.snapshot() == before


def test_scope_maintenance_intent_is_reported_without_granting_permission(case):
  from test_rotom_resource_scopes import scope_ids
  case.domain.accept_intent(batch_id="1" * 32, generation=1, operation="setup",
    resources=sorted(scope_ids(case.scope)), selected_runs=[], expected_revision=case.domain.snapshot()["revision"])
  before = case.domain.snapshot()
  records, pending = read(case)
  assert records == {} and pending is True and case.domain.snapshot() == before
