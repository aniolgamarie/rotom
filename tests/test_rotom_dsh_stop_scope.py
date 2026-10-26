"""临时DSH部署/假包与真实两层SH；不运行宿主或扫描原生会话。"""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import deployment, dsh_stop_scope as scope, execution_environment, lifecycle, run_owners, runtime
from agentcfg.resource_keys import ResourceKey
from agentcfg.storage import Conflict, Tree, instance_lock
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import MANAGER, observation


@pytest.fixture
def case(managed, tmp_path):
  ws, lock, package, observed = managed
  with Tree(ws.state_root) as tree: current = deployment.read_state(tree)["current"]
  spec = runtime.decode(current["launch"], tmp_path, ())
  record = run_owners.Registry(ws.state_root / "run-owners", ws.binding)._prepare_v2(
    "a" * 32, MANAGER, runtime.run_metadata(ws, current, spec))
  return SimpleNamespace(ws=ws, lock=lock, record=record, root=ws.instance / "runtimes" / lock.identity)


@contextmanager
def held(case):
  with lifecycle.guard(case.ws, shared=True, create=False) as physical, Tree(case.ws.state_root) as state:
    with instance_lock(state, shared=True, create=False) as fd:
      yield {"instance_fd": physical, "state_fd": fd}


def invoke(case, fds): return scope.inspect_deployment(case.ws, case.record, **fds)


def edit(case, mutate):
  path = case.ws.state_root / "deployment.json"; value = json.loads(path.read_bytes())
  mutate(value); path.write_bytes(deployment.json_bytes(value))


def contents(root):
  return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode & 0o777)
    for path in root.rglob("*") if path.is_file()}


def test_exact_real_deployment_keys_layout_borrowed_fds_and_no_side_effects(case, monkeypatch):
  def forbidden(*args, **kwargs): pytest.fail("no host/backend/secret/current environment or repair")
  monkeypatch.setattr(case.ws.backend, "status", forbidden)
  monkeypatch.setattr(type(case.ws.secret_store), "resolve", forbidden)
  monkeypatch.setattr(execution_environment, "capture_caller", forbidden)
  before = contents(case.ws.instance), contents(case.ws.state_root)
  with held(case) as fds:
    value = invoke(case, fds)
    for field, kind, path in (("instance", "instance", case.ws.instance),
        ("native_home", "native-home", case.ws.instance / "dsh-home"), ("runtime", "runtime", case.root)):
      info = path.stat(); assert value[field] == ResourceKey(kind, info.st_dev, info.st_ino).as_dict()
    info = (case.ws.instance / "user-home").stat()
    assert value["user_home"] == {"device": info.st_dev, "inode": info.st_ino}
    assert value["deployed_identity"] == case.record["deployed_identity"]
    value["deployed_identity"]["runtime"] = "0" * 64
    assert case.record["deployed_identity"]["runtime"] == case.lock.identity
    for fd in fds.values(): os.fstat(fd)
  assert (contents(case.ws.instance), contents(case.ws.state_root)) == before


@pytest.mark.parametrize("damage", ["pending", "pending-empty", "no-current", "generation", "binding", "owner-binding", "lock", "runtime", "argv", "marker", "record-state", "record-backend", "record-domain", "record-profile", "record-home"])
def test_wrong_deployment_or_record_rejected_without_writes(case, damage):
  if damage.startswith("pending"):
    path = case.ws.state_root / "pending.json"; path.write_bytes(b"" if damage == "pending-empty" else b"synthetic-private-canary"); path.chmod(0o600)
  elif damage == "no-current": (case.ws.state_root / "deployment.json").unlink()
  elif damage == "marker": (case.ws.instance / ".agentcfg-instance.json").write_bytes(b"synthetic-private-canary")
  elif damage == "record-state": case.record["lifecycle_state"] = "unknown"
  elif damage == "record-backend": case.record["backend"] = "ssh"
  elif damage == "record-domain": case.record["coordination_domain"] = {"synthetic-private-canary": True}
  elif damage == "record-profile": case.record["profile"] = "other"
  elif damage == "record-home": case.record["native_home_ref"]["path"] = "/synthetic/outside-home"
  else:
    def mutate(value):
      current = value["current"]
      if damage == "generation": current["generation"] = "0" * 64
      elif damage == "binding": current["binding"]["machine"] = "other"
      elif damage == "owner-binding": value["owner"]["binding"]["machine"] = "other"
      elif damage == "lock": current["launch"]["lock_identity"] = "not-64hex"
      elif damage == "runtime": current["launch"]["runtime_identity"] = "0" * 64
      else: current["launch"]["argv"][2] = "/synthetic/external-runtime"
    edit(case, mutate)
  before = contents(case.ws.instance), contents(case.ws.state_root)
  # 标记故障需在原物理SH已由可信调用方取得后测试；不让fixture guard先拒绝。
  with Tree(case.ws.instance) as target, Tree(case.ws.state_root) as state, instance_lock(state, shared=True, create=False) as state_fd:
    from agentcfg.storage import advisory_lock
    with advisory_lock(target.fd, shared=True):
      with pytest.raises(Conflict) as caught: invoke(case, {"instance_fd": target.fd, "state_fd": state_fd})
  assert "synthetic-private-canary" not in str(caught.value)
  assert (contents(case.ws.instance), contents(case.ws.state_root)) == before


@pytest.mark.parametrize("name", ["DSH_HOME", "HOME", "AGENTCFG_DSH_EXECUTION"])
@pytest.mark.parametrize("damage", ["missing", "duplicate", "secret", "wrong"])
def test_exact_literal_home_and_local_route(case, name, damage):
  def mutate(value):
    environment = value["current"]["launch"]["environment"]
    rows = [row for row in environment if row["name"] == name]
    if name == "AGENTCFG_DSH_EXECUTION" and not rows:
      environment.append({"name": name, "required": True, "literal": "local"})
      rows = [environment[-1]]
    if damage == "missing": environment[:] = [row for row in environment if row["name"] != name]
    elif damage == "duplicate": environment.append(deepcopy(rows[0]))
    elif damage == "secret": rows[0].pop("literal"); rows[0]["secret_ref"] = "secret:synthetic-private-canary"
    else: rows[0]["literal"] = "ssh" if name == "AGENTCFG_DSH_EXECUTION" else "/synthetic/outside"
  edit(case, mutate)
  with held(case) as fds:
    if name == "AGENTCFG_DSH_EXECUTION" and damage == "missing": assert invoke(case, fds)["runtime"]["kind"] == "runtime"
    else:
      with pytest.raises(Conflict) as caught: invoke(case, fds)
      assert "synthetic-private-canary" not in str(caught.value)


@pytest.mark.parametrize("target", ["instance", "native", "runtime", "user", "state-lock", "marker", "deployment", "pending", "state-root"])
def test_replacement_during_guard_projection_is_rejected(case, monkeypatch, target, tmp_path):
  original = runtime.check_deployed_resources; replacements = []
  def changed(*args):
    original(*args)
    if target == "pending":
      (case.ws.state_root / "pending.json").write_bytes(b"")
      replacements.append(True)
      return
    path = {"instance": case.ws.instance, "native": case.ws.instance / "dsh-home", "runtime": case.root,
      "user": case.ws.instance / "user-home", "state-lock": case.ws.state_root / "instance.lock",
      "marker": case.ws.instance / ".agentcfg-instance.json", "deployment": case.ws.state_root / "deployment.json",
      "state-root": case.ws.state_root}[target]
    if path.is_dir(): path.rename(tmp_path / "old-resource"); path.mkdir(mode=0o700)
    else:
      data = path.read_bytes(); path.unlink(); path.write_bytes(data); path.chmod(0o600)
    replacements.append(True)
  monkeypatch.setattr(runtime, "check_deployed_resources", changed)
  with held(case) as fds, pytest.raises(Conflict): invoke(case, fds)
  assert replacements == [True]


@pytest.mark.parametrize("target", ["native", "runtime", "user"])
def test_symlink_containment_is_rejected_without_reading_external_content(case, target, tmp_path):
  path = {"native": case.ws.instance / "dsh-home", "runtime": case.root, "user": case.ws.instance / "user-home"}[target]
  path.rename(tmp_path / "original-resource")
  outside = tmp_path / "outside"; outside.mkdir(mode=0o700); (outside / "private-body").write_bytes(b"synthetic-private-canary")
  path.symlink_to(outside, target_is_directory=True)
  with held(case) as fds, pytest.raises(Conflict) as caught: invoke(case, fds)
  assert "synthetic-private-canary" not in str(caught.value)


@pytest.mark.parametrize("name", ["instance_fd", "state_fd"])
@pytest.mark.parametrize("damage", ["wrong", "closed", "bool"])
def test_invalid_borrowed_fds_are_rejected_and_not_closed(case, name, damage):
  with held(case) as original:
    fds = dict(original)
    if damage == "wrong": fds[name] = original["state_fd" if name == "instance_fd" else "instance_fd"]
    elif damage == "bool": fds[name] = True
    else:
      fd = os.dup(original[name]); os.close(fd); fds[name] = fd
    with pytest.raises(Conflict): invoke(case, fds)
    for fd in original.values(): os.fstat(fd)


@pytest.mark.parametrize("damage", ["drift", "missing"])
def test_protected_launcher_changes_rejected(case, damage):
  path = case.ws.instance / "launch.mjs"
  if damage == "missing": path.unlink()
  else: path.write_bytes(b"synthetic-private-canary")
  with held(case) as fds, pytest.raises(Conflict) as caught: invoke(case, fds)
  assert "synthetic-private-canary" not in str(caught.value)


@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_projection_errors_sanitized_or_original_control_and_fds_live(case, monkeypatch, kind):
  error = kind("synthetic-private-canary")
  def fail(*args): raise error
  monkeypatch.setattr(runtime, "check_deployed_resources", fail)
  with held(case) as fds:
    with pytest.raises(Conflict if kind is OSError else kind) as caught: invoke(case, fds)
    if kind is not OSError: assert caught.value is error
    else: assert "synthetic-private-canary" not in str(caught.value)
    for fd in fds.values(): os.fstat(fd)


@pytest.mark.parametrize("name", ["instance_fd", "state_fd"])
def test_closed_borrowed_fd_rejected_before_opening_any_tree(case, monkeypatch, name):
  calls = []
  def opened(*args, **kwargs):
    calls.append(True)
    raise OSError("synthetic-tree-open-canary")
  with held(case) as fds:
    closed = os.dup(fds[name]); os.close(closed)
    invalid = {**fds, name: closed}
    monkeypatch.setattr(scope, "Tree", opened)
    with pytest.raises(Conflict): invoke(case, invalid)
    assert calls == []


@pytest.mark.parametrize("damage", ["missing", "selector", "ownership", "duplicate"])
def test_launcher_requires_unique_nonselector_file_item(case, damage):
  def mutate(value):
    items = value["current"]["items"]
    key = next(key for key, item in items.items() if item["path"] == "launch.mjs")
    if damage == "missing": del items[key]
    elif damage == "selector": items[key]["selector"] = "/synthetic"
    elif damage == "ownership": items[key]["ownership"] = "initialize"
    else: items["synthetic-duplicate"] = deepcopy(items[key])
  edit(case, mutate)
  with held(case) as fds, pytest.raises(Conflict): invoke(case, fds)


@pytest.mark.parametrize("damage", ["drift", "missing"])
def test_original_declared_runtime_guard_remains_enforced(case, damage):
  from agentcfg.dsh_optional import TEAM_SELECTION_FILE
  path = case.ws.instance / TEAM_SELECTION_FILE
  if damage == "missing": path.unlink()
  else: path.write_bytes(b"synthetic-private-canary")
  with held(case) as fds, pytest.raises(Conflict) as caught: invoke(case, fds)
  assert "synthetic-private-canary" not in str(caught.value)
