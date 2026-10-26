"""适配器使用真实临时 scope/包元数据；不启动真实 OMP。"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import lifecycle, omp_admission as admission, omp_identity, resource_coordination as core, runtime
from agentcfg.omp import OmpAdapter
from agentcfg.storage import Conflict
from test_rotom_omp_setup_admission import fresh, cooperative, domain, contents
from test_rotom_omp_cooperative_launch import case
from test_rotom_resource_owners import IDENTITY
from test_rotom_resource_scopes import claim_path


@pytest.fixture
def selected(fresh):
  fresh.adapter = OmpAdapter(Path(__file__).resolve().parents[1])
  fresh.backend = SimpleNamespace(runtime_identity=lambda ws, lock: lock.identity + "-synthetic")
  return fresh, SimpleNamespace(identity=IDENTITY)


def test_adapter_prepare_registers_exact_backend_identity_before_sync_without_instance(selected):
  ws, lock = selected
  ws.adapter.prepare_setup_resources(ws, lock)
  assert core.runtime_claim_exists(ws.cache, IDENTITY + "-synthetic")
  record, = domain(ws).snapshot()["resources"].values()
  assert record["runtime_identity"] == IDENTITY + "-synthetic"
  assert not ws.instance.exists() and not ws.state_root.exists()
  with ws.adapter.apply_lifecycle_guard_for(ws, lock) as fd:
    assert type(fd) is int and claim_path(ws).exists()
  assert not ws.state_root.exists()


@pytest.mark.parametrize("method", ["lifecycle_guard", "apply_lifecycle_guard"])
def test_legacy_low_level_hooks_return_int_without_runtime_or_scope_enrollment(selected, method):
  ws, _ = selected
  if method == "lifecycle_guard":
    with omp_identity.lifecycle_guard(ws, create=True):
      pass
  with getattr(ws.adapter, method)(ws) as fd:
    assert type(fd) is int and os.fstat(fd).st_ino == os.stat(ws.instance / ".agentcfg-omp.lock").st_ino
  assert not domain(ws).root.exists() and not claim_path(ws).exists()


@pytest.mark.parametrize("method", ["lifecycle_guard", "apply_lifecycle_guard", "pre_sync_preflight"])
def test_existing_scope_write_and_preflight_use_accepted_scope_guard(selected, method):
  ws, _ = selected
  cooperative(ws)
  before = domain(ws).snapshot()
  if method == "pre_sync_preflight":
    ws.adapter.pre_sync_preflight(ws)
  else:
    with getattr(ws.adapter, method)(ws) as fd:
      assert type(fd) is int
  assert domain(ws).snapshot() == before and not ws.state_root.exists()


@pytest.mark.parametrize("method", ["lifecycle_guard", "apply_lifecycle_guard", "pre_sync_preflight"])
def test_bad_scope_claim_never_falls_back_or_repairs(selected, method):
  ws, _ = selected
  cooperative(ws)
  claim_path(ws).write_bytes(b"{synthetic-broken")
  before = contents(ws.cache.parent)
  with pytest.raises(Conflict):
    if method == "pre_sync_preflight":
      ws.adapter.pre_sync_preflight(ws)
    else:
      with getattr(ws.adapter, method)(ws):
        pytest.fail("bad scope cannot become legacy")
  assert contents(ws.cache.parent) == before


@pytest.mark.parametrize("operation", ["prepare", "apply"])
@pytest.mark.parametrize("evidence", ["none", "scope", "runtime"])
def test_nonlinux_only_legacy_without_cooperative_evidence_is_allowed(selected, monkeypatch, operation, evidence):
  ws, lock = selected
  identity = runtime.runtime_identity(ws, lock)
  if evidence == "scope":
    cooperative(ws)
  elif evidence == "runtime":
    core.enroll_runtime(core.initialize_domain(domain(ws).root), ws.cache, identity)
  monkeypatch.setattr(admission.sys, "platform", "darwin")
  before = contents(ws.cache.parent)
  def perform():
    if operation == "prepare":
      ws.adapter.prepare_setup_resources(ws, lock)
    else:
      with ws.adapter.apply_lifecycle_guard_for(ws, lock) as fd:
        assert type(fd) is int
  if evidence != "none":
    with pytest.raises(Conflict):
      perform()
    assert contents(ws.cache.parent) == before
  else:
    perform()
    assert not domain(ws).root.exists() and not claim_path(ws).exists()
    assert ws.instance.exists() == (operation == "apply")


@pytest.mark.parametrize("fallback", [False, True])
def test_scope_run_uses_deployed_identity_even_when_current_lock_resolution_differs(case, monkeypatch, fallback):
  ws = case.ws
  path = ws.state_root / "deployment.json"
  state = json.loads(path.read_bytes())
  if fallback:
    state["current"]["launch"].pop("runtime_identity", None)
  else:
    state["current"]["launch"]["runtime_identity"] = case.lock.identity
  path.write_text(json.dumps(state))
  monkeypatch.setattr(ws.backend, "runtime_identity", lambda *a: pytest.fail("run must not resolve current repository lock"))
  with ws.adapter.run_lifecycle_guard(ws) as lease:
    assert type(lease) is lifecycle.CooperativeRunLease
    entry, = case.domain.snapshot()["reservations"].values()
    record = case.domain.snapshot()["resources"][case.package["resource_id"]]
    assert case.package["resource_id"] in entry["resources"] and record["runtime_identity"] == case.lock.identity
    with lease.package_guard(ws, case.lock.identity) as fd:
      assert os.fstat(fd).st_ino == os.stat(ws.cache / "leases" / (case.lock.identity + ".lock")).st_ino
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "cancelled"


@pytest.mark.parametrize("damage", ["pending", "missing-current", "binding", "claim", "missing-state", "nonlinux"])
def test_scope_run_refuses_unconfirmed_deployment_without_reservation(case, monkeypatch, damage):
  ws = case.ws
  path = ws.state_root / "deployment.json"
  if damage == "pending":
    (ws.state_root / "pending.json").write_bytes(b"")
  elif damage == "claim":
    claim_path(ws).write_bytes(b"{synthetic-broken")
  elif damage == "missing-state":
    path.unlink()
  elif damage == "nonlinux":
    monkeypatch.setattr(admission.sys, "platform", "darwin")
  else:
    state = json.loads(path.read_bytes())
    if damage == "binding":
      state["current"]["binding"]["machine"] = "different-synthetic-machine"
    else:
      state["current"] = None
    path.write_text(json.dumps(state))
  before = contents(ws.cache.parent), case.domain.snapshot()
  with pytest.raises(Conflict):
    with ws.adapter.run_lifecycle_guard(ws):
      pytest.fail("uncertain deployment cannot reserve launch")
  assert (contents(ws.cache.parent), case.domain.snapshot()) == before


def test_legacy_run_returns_original_shared_int(selected):
  ws, _ = selected
  with omp_identity.lifecycle_guard(ws, create=True):
    pass
  with ws.adapter.run_lifecycle_guard(ws) as fd:
    assert type(fd) is int
  assert not domain(ws).root.exists()


def test_adapter_runtime_full_chain_uses_cooperative_descriptor_and_preserves_exit(case, fake_subprocess):
  fake_subprocess.queue(returncode=41)
  assert runtime.run(case.ws, cwd=case.cwd) == 41
  assert len(fake_subprocess.calls) == 1
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "released"


def test_cooperative_run_missing_state_directory_does_not_create_it(selected):
  ws, _ = selected
  cooperative(ws)
  before = contents(ws.cache.parent)
  assert not ws.state_root.exists()
  with pytest.raises(Conflict), ws.adapter.run_lifecycle_guard(ws):
    pytest.fail("missing deployment cannot initiate cooperative run")
  assert not ws.state_root.exists() and contents(ws.cache.parent) == before


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
def test_prepare_control_interrupt_propagates_original_object(selected, monkeypatch, exception_type):
  from agentcfg import omp_setup
  ws, lock = selected
  interruption = exception_type("synthetic-control-interruption")
  def interrupted(*args):
    raise interruption
  monkeypatch.setattr(omp_setup, "prepare_setup", interrupted)
  with pytest.raises(exception_type) as caught:
    ws.adapter.prepare_setup_resources(ws, lock)
  assert caught.value is interruption


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit, ValueError])
def test_write_body_exception_is_not_reclassified(selected, exception_type):
  ws, _ = selected
  error = exception_type("synthetic-body-error")
  with pytest.raises(exception_type) as caught:
    with ws.adapter.apply_lifecycle_guard(ws):
      raise error
  assert caught.value is error


def test_private_admission_exception_is_fixed_conflict(selected, monkeypatch):
  ws, lock = selected
  def interrupted(*args):
    raise ValueError("synthetic-private-runtime-source")
  monkeypatch.setattr(ws.backend, "runtime_identity", interrupted)
  before = contents(ws.cache.parent)
  with pytest.raises(Conflict) as caught:
    ws.adapter.prepare_setup_resources(ws, lock)
  assert "synthetic-private" not in str(caught.value) and contents(ws.cache.parent) == before


@pytest.mark.parametrize("operation", ["write", "preflight"])
def test_real_xdg_layout_conflict_preserves_trusted_fixed_diagnostic(selected, operation):
  ws, _ = selected
  with omp_identity.lifecycle_guard(ws, create=True):
    pass
  identity = omp_identity.native_identity(ws.profile, ws.instance)
  alternate = identity.xdg_config / "omp/profiles" / identity.native_name
  alternate.mkdir(parents=True, mode=0o700)
  with pytest.raises(Conflict, match="XDG"):
    if operation == "preflight":
      ws.adapter.pre_sync_preflight(ws)
    else:
      with ws.adapter.lifecycle_guard(ws):
        pytest.fail("XDG layout is already conflicting")


@pytest.mark.parametrize("operation", ["write", "preflight"])
def test_nonconflict_guard_error_is_sanitized(selected, monkeypatch, operation):
  ws, _ = selected
  def interrupted(*args, **kwargs):
    raise ValueError("synthetic-private-guard-canary")
  monkeypatch.setattr(omp_identity, "preflight_setup" if operation == "preflight" else "lifecycle_guard", interrupted)
  with pytest.raises(Conflict) as caught:
    if operation == "preflight":
      ws.adapter.pre_sync_preflight(ws)
    else:
      with ws.adapter.apply_lifecycle_guard(ws):
        pytest.fail("guard rejected")
  assert "synthetic-private" not in str(caught.value)
