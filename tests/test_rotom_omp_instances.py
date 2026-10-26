"""合作 OMP 列表只读接线；合成 owner/child 不授予 stop/resume 或加载能力。"""
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path

import pytest

from agentcfg import lifecycle, local, resource_coordination as core, run_owners, runtime, workspace
from agentcfg.storage import Conflict, Tree
from test_rotom_omp_cooperative_launch import case
from test_rotom_omp_setup_admission import contents, fresh
from test_rotom_resource_scopes import claim_path


@pytest.fixture
def observed(case, monkeypatch):
  ws = case.ws
  light = workspace.InstanceWorkspace("omp", ws.profile, Path(ws.binding["local"]),
    ws.binding["machine"], ws.instance, ws.state_root,
    global_state_root=ws.resolved.data["machine"]["paths"]["state_root"], cache=ws.cache)
  monkeypatch.setattr(local, "available_profiles", lambda: [(ws.profile, "omp")])
  def selected(path, profiles):
    assert path == light.local_path and profiles == [ws.profile]
    return (light,)
  monkeypatch.setattr(workspace, "load_instance_workspaces", selected)
  monkeypatch.setattr(run_owners, "observed_process_identity", lambda pid: deepcopy(case.module.run_owners.current_process_identity()))
  return light


def query(observed):
  return run_owners.instances(observed.local_path, agent="omp", profile=observed.profile)


def registered(report):
  return [row for row in report["instances"] if row["kind"] == "registered"]


@pytest.mark.parametrize("complete,expected", [(True, "stopped"), (False, "unknown")])
def test_cooperative_saved_records_display_separate_process_and_unknown_session(case, observed, fake_subprocess, complete, expected):
  case.control["complete"] = complete
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  before = contents(case.ws.state_root.parent.parent), contents(case.ws.instance)
  report = query(observed)
  row, = report["instances"]
  assert row["kind"] == "registered" and row["process"]["status"] == expected
  assert row["start_cwd"]["path"] == str(case.cwd)
  assert row["process"]["manager_identity"] is not None and row["process"]["host_identity"] is None
  assert row["session"]["status"] == "unknown" and row["session"]["resume_available"] is False
  assert row["terminal"]["restore_available"] is False
  assert report["coverage"][0]["registration"] == "cooperative-v2"
  assert report["coverage"][0]["status"] == "observed" and report["incomplete"] is False
  assert report["capabilities"] == {"stop": False, "resume": False}
  assert (contents(case.ws.state_root.parent.parent), contents(case.ws.instance)) == before


def test_running_manager_and_cwd_are_visible_without_implying_host_or_session(case, observed, monkeypatch, fake_subprocess):
  original = runtime._run_dsh_child
  reports = []
  def child(spec, env, pass_fds, **kwargs):
    # 查询发生在新直接 child 边界；替身不伪造尚未捕获的原生 host。
    assert kwargs["owner_registry"].snapshot()[kwargs["run_id"]]["manager_identity"] == run_owners.current_process_identity()
    assert callable(kwargs["control_factory"]) and len(pass_fds) == 3
    entry = case.domain.snapshot()["reservations"][kwargs["run_id"]]
    assert entry["phase"] == "dispatched"
    before = contents(case.ws.state_root.parent.parent), case.domain.snapshot()
    reports.append(query(observed))
    assert (contents(case.ws.state_root.parent.parent), case.domain.snapshot()) == before
    with pytest.raises(Conflict):
      with lifecycle.omp_scope_write_guard(case.ws):
        pytest.fail("active OMP 的原运行租约仍须阻止写入")
    return original(spec, env, pass_fds, **kwargs)
  monkeypatch.setattr(runtime, "_run_dsh_child", child)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  assert len(reports) == len(fake_subprocess.calls) == 1
  row, = reports[0]["instances"]
  assert row["process"]["status"] == "active" and row["process"]["coverage"] == "manager-only"
  assert row["process"]["manager_status"] == "active" and row["process"]["ownership_state"] == "active"
  assert row["process"]["manager_identity"] == run_owners.current_process_identity()
  assert row["start_cwd"]["path"] == str(case.cwd)
  assert row["process"]["host_identity"] is None and row["session_cwd"] is None
  assert row["process"]["host_status"] == "unknown" and row["session"]["status"] == "unknown"
  assert row["session"]["resume_available"] is False and row["terminal"]["restore_available"] is False
  assert reports[0]["incomplete"] is False


@pytest.mark.parametrize("known", [False, True])
def test_reserved_without_owner_is_not_zero_and_preserves_known_rows(case, observed, fake_subprocess, known):
  if known:
    fake_subprocess.queue(returncode=0)
    assert runtime.run(case.ws, cwd=case.cwd) == 0
  token = lifecycle.reserve_omp_launch(case.ws, case.lock.identity)
  before = case.domain.snapshot()
  report = query(observed)
  assert len(registered(report)) == int(known)
  pending, = [row for row in report["instances"] if row["kind"] == "unregistered-or-unverified"]
  assert pending["process"]["source"] == "coordination-records-pending"
  assert report["coverage"][0]["registration"] == "cooperative-v2"
  assert report["coverage"][0]["status"] == "unknown" and report["incomplete"] is True
  assert case.domain.snapshot() == before and before["reservations"][token.run_id]["phase"] == "reserved"


def test_scope_claim_with_missing_instance_stays_unknown_without_creation(case, observed):
  case.ws.instance.rename(case.ws.instance.with_name("synthetic-moved-instance"))
  before = case.domain.snapshot()
  report = query(observed)
  assert report["coverage"][0]["registration"] == "cooperative-unverified"
  assert report["coverage"][0]["status"] == "unknown" and report["incomplete"] is True
  assert len(report["instances"]) == 1 and not case.ws.instance.exists()
  assert case.domain.snapshot() == before


@pytest.mark.parametrize("damage", ["domain", "claim", "owner-link"])
def test_broken_cooperative_provenance_is_unknown_incomplete_not_unsupported(case, observed, fake_subprocess, damage):
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  if damage == "domain":
    (case.domain.root / "coordination.json").unlink()
  elif damage == "claim":
    claim_path(case.ws).write_bytes(b"{synthetic-broken")
  else:
    with case.domain._transaction(write=True) as state:
      entry, = state["reservations"].values()
      entry["owner_link"]["ownership_digest"] = "0" * 64
  before = contents(case.ws.state_root.parent.parent)
  report = query(observed)
  assert report["incomplete"] is True and report["coverage"][0]["status"] == "unknown"
  assert report["coverage"][0]["registration"] == "cooperative-unverified"
  assert len(report["instances"]) == 1
  assert contents(case.ws.state_root.parent.parent) == before


def test_query_does_not_read_native_body_take_package_lock_or_modify_unknown(case, observed, monkeypatch, fake_subprocess):
  case.control["complete"] = False
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  native = case.ws.instance / "user-home"
  (native / "synthetic-native-sentinel").write_bytes(b"synthetic-private-body")
  original = Tree.read
  def read(tree, name, *args, **kwargs):
    if tree.root == native and name != ".rotom-resource.json":
      pytest.fail("query must not read native body")
    return original(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", read)
  monkeypatch.setattr(core, "read_runtime_anchor", lambda *a: pytest.fail("query must not read package anchor"))
  before = contents(case.ws.state_root.parent.parent)
  fd = os.open(case.ws.cache / "leases" / (case.lock.identity + ".lock"), os.O_RDWR)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    report = query(observed)
  finally:
    os.close(fd)
  row, = report["instances"]
  assert row["process"]["status"] == "unknown" and report["incomplete"] is False
  assert contents(case.ws.state_root.parent.parent) == before and len(fake_subprocess.calls) == 1


def test_missing_current_package_allows_historical_listing_but_actual_run_still_refuses(case, observed, fake_subprocess):
  fake_subprocess.queue(returncode=0)
  assert runtime.run(case.ws, cwd=case.cwd) == 0
  (case.ws.cache / "leases" / (case.lock.identity + ".lock")).unlink()
  case.ws.backend.root(case.ws, case.lock.identity).rmdir()
  before = contents(case.ws.state_root.parent.parent)
  report = query(observed)
  assert len(registered(report)) == 1 and report["incomplete"] is False
  assert report["coverage"][0]["registration"] == "cooperative-v2"
  assert contents(case.ws.state_root.parent.parent) == before
  with pytest.raises(Conflict):
    runtime.run(case.ws, cwd=case.cwd)
  assert len(fake_subprocess.calls) == 1


def test_legacy_omp_still_reports_unsupported_without_creating_cooperative_domain(tmp_path, monkeypatch):
  from types import SimpleNamespace
  from agentcfg.omp_identity import lifecycle_guard
  ws = SimpleNamespace(agent="omp", profile="omp-legacy", instance=tmp_path / "instance",
    state_root=tmp_path / "state", binding={"machine": "synthetic", "local": str(tmp_path / "local.toml"), "profile": "omp-legacy"})
  with lifecycle_guard(ws, create=True):
    pass
  monkeypatch.setattr(local, "available_profiles", lambda: [(ws.profile, "omp")])
  monkeypatch.setattr(workspace, "load_instance_workspaces", lambda *a: (ws,))
  report = run_owners.instances(Path(ws.binding["local"]), agent="omp")
  assert report["coverage"][0]["registration"] == "unsupported"
  row, = report["instances"]
  assert row["process"]["source"] == "omp-registration-unavailable"
  assert not ws.state_root.exists()


def test_actual_loader_passes_same_configured_global_root_and_cache_without_credentials(tmp_path, monkeypatch):
  from test_runtime import local_file
  path = tmp_path / "local.toml"
  local_file(path)
  root = tmp_path / "synthetic-state"
  cache = tmp_path / "synthetic-cache"
  with path.open("a") as stream:
    stream.write('[machine.paths]\nstate_root=' + json.dumps(str(root)) + '\ncache_root=' + json.dumps(str(cache)) + '\n')
  original = workspace.load_local
  calls = []
  def loading(*args, **kwargs):
    calls.append(kwargs.get("load_credentials"))
    return original(*args, **kwargs)
  monkeypatch.setattr(workspace, "load_local", loading)
  monkeypatch.setattr(workspace, "load_workspace", lambda *a, **k: pytest.fail("observation must not resolve runnable workspace"))
  light, = workspace.load_instance_workspaces(path, ["omp-default"])
  assert light.global_state_root == str(root)
  assert light.state_root == root / "omp/omp-default" and light.cache == cache / "omp/omp-default"
  assert light.binding["local"] == str(path) and calls == [False]
  assert not root.exists() and not cache.exists()


def test_partial_scope_claim_without_instance_or_state_is_not_not_prepared(fresh, monkeypatch):
  from test_rotom_resource_scopes import scopes
  d = core.initialize_domain(fresh.state_root.parent.parent / "lifecycle")
  original = Tree.write_new
  def interrupted(tree, name, data):
    original(tree, name, data)
    if tree.root == claim_path(fresh).parent:
      raise Conflict("synthetic-after-claim")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", interrupted)
    with pytest.raises(Conflict):
      scopes().enroll_scope(d, fresh)
  assert claim_path(fresh).exists() and not fresh.instance.exists() and not fresh.state_root.exists()
  light = workspace.InstanceWorkspace("omp", fresh.profile, Path(fresh.binding["local"]),
    fresh.binding["machine"], fresh.instance, fresh.state_root,
    global_state_root=fresh.resolved.data["machine"]["paths"]["state_root"], cache=fresh.cache)
  monkeypatch.setattr(local, "available_profiles", lambda: [(fresh.profile, "omp")])
  monkeypatch.setattr(workspace, "load_instance_workspaces", lambda *a: (light,))
  before = contents(fresh.instance.parent.parent), d.snapshot()
  report = query(light)
  assert report["incomplete"] is True and report["coverage"][0]["status"] == "unknown"
  assert report["coverage"][0]["registration"] == "cooperative-unverified" and len(report["instances"]) == 1
  assert not fresh.instance.exists() and not fresh.state_root.exists()
  assert (contents(fresh.instance.parent.parent), d.snapshot()) == before


def test_pending_metadata_and_busy_physical_ex_do_not_duplicate_uncertain_row(case, observed):
  lifecycle.reserve_omp_launch(case.ws, case.lock.identity)
  fd = os.open(case.ws.instance / ".agentcfg-omp.lock", os.O_RDWR)
  try:
    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    report = query(observed)
  finally:
    os.close(fd)
  row, = report["instances"]
  assert row["process"]["source"] == "coordination-records-pending" and report["incomplete"] is True
  assert report["coverage"][0]["lease_observation"] == "busy-or-unverified"
