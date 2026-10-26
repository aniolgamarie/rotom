"""部署快照现场只读核验；临时文件与假进程，不获得停止授权。"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
import os

import pytest

from agentcfg import deployment, maintenance_deployment as check, run_owners, runtime
from agentcfg.native_projection import reference_guard
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.storage import Conflict, Tree
from test_rotom_omp_cooperative_launch import case
from test_rotom_omp_setup_flow import fresh
from test_rotom_omp_setup_admission import contents
from test_rotom_resource_owners import MANAGER, metadata


@pytest.fixture
def prepared(case):
  with Tree(case.ws.state_root) as state:
    current = deployment.read_state(state)["current"]
  supplied = metadata(case.ws)
  supplied["deployed_identity"] = {"deployment": current["generation"], "runtime": case.lock.identity}
  case.record = run_owners.Registry(case.ws.state_root / "run-owners", case.ws.binding)._prepare_v2("a" * 32, MANAGER, supplied)
  return case


@contextmanager
def held(case):
  with ExitStack() as stack:
    physical = stack.enter_context(_shared_file(case.ws.instance, ".agentcfg-omp.lock"))
    state = stack.enter_context(_shared_file(case.ws.state_root, "instance.lock"))
    stack.enter_context(_shared_file(case.ws.cache, "leases/" + case.lock.identity + ".lock"))
    yield {"instance_fd": physical, "state_fd": state}


def invoke(case, fds):
  return check.check_stop_deployment(case.ws, case.record, **fds)


def state_change(case, edit):
  path = case.ws.state_root / "deployment.json"
  value = json.loads(path.read_bytes())
  edit(value)
  path.write_bytes(deployment.json_bytes(value))


def test_exact_deployed_identity_is_readonly_keeps_fds_and_ignores_unprotected_contents(prepared, monkeypatch):
  (prepared.ws.instance / "synthetic-unprotected").write_bytes(b"synthetic-unmanaged-content")
  def forbidden(*args, **kwargs): pytest.fail("no backend/env/secret/repair operations")
  monkeypatch.setattr(prepared.ws.backend, "status", forbidden)
  monkeypatch.setattr(prepared.ws.adapter, "validate_runtime_binding", forbidden)
  monkeypatch.setattr(type(prepared.ws.secret_store), "resolve", forbidden)
  before = contents(prepared.ws.instance), contents(prepared.ws.state_root)
  with held(prepared) as fds:
    assert invoke(prepared, fds) is None
    for fd in fds.values(): os.fstat(fd)
  assert (contents(prepared.ws.instance), contents(prepared.ws.state_root)) == before


@pytest.mark.parametrize("damage", ["current", "pending-empty", "pending", "generation", "runtime", "binding", "owner-binding", "home", "record-home", "record-scope", "record-agent", "record-state"])
def test_scope_pending_generation_runtime_and_home_changes_reject(prepared, damage):
  if damage == "current": (prepared.ws.state_root / "deployment.json").unlink()
  elif damage.startswith("pending"):
    (prepared.ws.state_root / "pending.json").write_bytes(b"" if damage == "pending-empty" else b"synthetic-pending")
  elif damage == "record-home": prepared.record["native_home_ref"]["path"] = "/synthetic-other-home"
  elif damage == "record-scope": prepared.record["profile"] = "different-profile"
  elif damage == "record-agent": prepared.record["agent"] = "pi"
  elif damage == "record-state": prepared.record["lifecycle_state"] = "unknown"
  else:
    def edit(value):
      current = value["current"]
      if damage == "generation": current["generation"] = "0" * 64
      elif damage == "runtime": current["launch"]["runtime_identity"] = "0" * 64
      elif damage == "binding": current["binding"]["machine"] = "different-machine"
      elif damage == "owner-binding": value["owner"]["binding"]["machine"] = "different-machine"
      else: current["launch"]["adapter_binding"]["identity"]["home"] = "/synthetic-other-home"
    state_change(prepared, edit)
  before = contents(prepared.ws.state_root), contents(prepared.ws.instance)
  with held(prepared) as fds, pytest.raises(Conflict): invoke(prepared, fds)
  assert (contents(prepared.ws.state_root), contents(prepared.ws.instance)) == before


@pytest.mark.parametrize("mutation", ["drift", "missing", "bad-reference"])
def test_real_projection_rejects_guarded_file_drift_missing_and_illegal_reference(prepared, mutation):
  path = prepared.ws.instance / "synthetic-reference.json"
  path.write_bytes(b'{"key":"$SYNTHETIC_REFERENCE"}')
  path.chmod(0o600)
  item = {"path": path.name, "selector": "/key", "codec": "json", "ownership": "managed",
    "guard": reference_guard(["$SYNTHETIC_REFERENCE", "$SYNTHETIC_OTHER_REFERENCE"]), "baseline": deployment.encoded("$SYNTHETIC_REFERENCE")}
  def edit(value):
    value["current"]["items"][deployment.item_key(item)] = item
    value["current"]["launch"]["runtime_guards"]["files"].append(path.name)
  state_change(prepared, edit)
  with held(prepared) as fds:
    assert invoke(prepared, fds) is None
  if mutation == "missing": path.unlink()
  elif mutation == "drift": path.write_bytes(b'{"key":"$SYNTHETIC_OTHER_REFERENCE"}')
  else: path.write_bytes(b'{"key":"synthetic-private-canary"}')
  with held(prepared) as fds, pytest.raises(Conflict) as caught: invoke(prepared, fds)
  assert "synthetic-private-canary" not in str(caught.value)


@pytest.mark.parametrize("field", ["instance_fd", "state_fd"])
@pytest.mark.parametrize("damage", ["closed", "wrong", "bool", "replaced"])
def test_invalid_or_replaced_lease_fd_refuses_without_closing_other_borrowed_fds(prepared, field, damage):
  with held(prepared) as original:
    fds = dict(original)
    if damage == "closed":
      fd = os.dup(fds[field]); os.close(fd); fds[field] = fd
    elif damage == "wrong": fds[field] = original["state_fd" if field == "instance_fd" else "instance_fd"]
    elif damage == "bool": fds[field] = True
    else:
      path = prepared.ws.instance / ".agentcfg-omp.lock" if field == "instance_fd" else prepared.ws.state_root / "instance.lock"
      data = path.read_bytes(); path.unlink(); path.write_bytes(data); path.chmod(0o600)
    with pytest.raises(Conflict): invoke(prepared, fds)
    for fd in original.values(): os.fstat(fd)


def test_state_lock_replaced_during_projection_is_rejected(prepared, monkeypatch):
  original = deployment.projection
  replacements = []
  def projected(*args):
    result = original(*args)
    if not replacements:
      path = prepared.ws.state_root / "instance.lock"
      data = path.read_bytes(); path.unlink(); path.write_bytes(data); path.chmod(0o600)
      replacements.append(True)
    return result
  monkeypatch.setattr(deployment, "projection", projected)
  with held(prepared) as fds, pytest.raises(Conflict): invoke(prepared, fds)
  assert replacements == [True]


def test_platform_runtime_identity_uses_same_sha_projection_as_run_metadata(prepared):
  import hashlib
  identity = prepared.lock.identity + "-synthetic-platform"
  prepared.record["deployed_identity"]["runtime"] = hashlib.sha256(identity.encode()).hexdigest()
  state_change(prepared, lambda value: value["current"]["launch"].update(runtime_identity=identity))
  with held(prepared) as fds:
    assert invoke(prepared, fds) is None


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_control_interrupt_is_not_reclassified(prepared, monkeypatch, error_type):
  error = error_type("synthetic-control")
  def interrupted(*args): raise error
  monkeypatch.setattr(runtime, "check_deployed_resources", interrupted)
  with held(prepared) as fds, pytest.raises(error_type) as caught: invoke(prepared, fds)
  assert caught.value is error


def test_ordinary_run_calls_shared_projection_checker_once_without_extra_process(case, monkeypatch, fake_subprocess):
  original = runtime.check_deployed_resources
  calls = []
  def checked(current, target):
    calls.append((current["generation"], target.root))
    return original(current, target)
  monkeypatch.setattr(runtime, "check_deployed_resources", checked)
  fake_subprocess.queue(returncode=9)
  assert runtime.run(case.ws, cwd=case.cwd) == 9
  assert calls == [("d" * 64, case.ws.instance)] and len(fake_subprocess.calls) == 1


def test_real_fake_setup_run_active_owner_deployment_is_supported_without_stop_authority(fresh, monkeypatch, fake_subprocess):
  from agentcfg import commands
  from types import SimpleNamespace
  assert commands.cmd_setup(SimpleNamespace(command="setup")) == 0
  import subprocess
  original = subprocess.run
  calls = []
  def child(*args, **kwargs):
    record, = run_owners.Registry(fresh.ws.state_root / "run-owners", fresh.ws.binding).snapshot().values()
    assert record["lifecycle_state"] == "active" and record["host_identity"] is None
    fds = kwargs["pass_fds"]
    assert check.check_stop_deployment(fresh.ws, record, instance_fd=fds[0], state_fd=fds[1]) is None
    calls.append(True)
    return original(*args, **kwargs)
  monkeypatch.setattr(subprocess, "run", child)
  fake_subprocess.queue(returncode=17)
  assert runtime.run(fresh.ws, cwd=fresh.cwd) == 17
  assert calls == [True]
