"""默认Host File/Shell接线；真实有界helper文件+原小planner，绝不启动helper/Shell。"""

import builtins
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import traceback

import pytest

from agentcfg import pi_host
from agentcfg import pi_shell_mounts
from agentcfg import pi_admitted_shell
from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict, Tree
from test_pi_host_capabilities import configured
from test_pi_pid_namespace import modern_host
from test_pi_admitted_shell import fixture as shell_fixture
from test_pi_shell_mounts import mount_row
from test_pi_operation_admission import fixture as ledger_fixture


PRIVATE = "SYNTHETIC_PRIVATE_COMMAND"


def default_host(tmp_path, monkeypatch, *, profile="pi-base", selected=True):
  config, file = configured(tmp_path / "host", monkeypatch, [])
  sealed = modern_host(tmp_path / "backend", monkeypatch, "pi-base" if profile == "legacy" else profile)
  raw = shell_fixture(tmp_path / "business", profile="pi-base" if profile == "legacy" else profile)
  manifest = json.loads(file.read_bytes())
  manifest.update(profile_id=profile, options=deepcopy(raw[2].manifest()["options"]), permission_policy=deepcopy(raw[2].manifest()["permission_policy"]))
  if not selected: manifest["options"]["external_tools"].pop("shell")
  file.write_bytes(json_bytes(manifest))
  config.update(runtime_root=str(sealed.runtime_root), repository=str(sealed.repository), cwd=raw[4]["cwd"],
    lock_identity=sealed.config["lock_identity"], slice_identity=sealed.config["slice_identity"],
    manifest_digest=digest(manifest), policy_digest=digest(manifest["permission_policy"]))
  return pi_host.HostSupervisor(config, lease_fd=None), raw


def real_small_planner(monkeypatch, *, mutate=None):
  original = pi_shell_mounts.compile_mount_plan
  seen = []
  def planner(public, **kwargs):
    seen.append(deepcopy(public))
    # 真实原planner；仅自有临时树/合成mountinfo，不证明生产默认系统树。
    result = original(public, system_roots=(), mountinfo=mount_row(1, "/"))
    if mutate: mutate()
    return result
  monkeypatch.setattr(pi_shell_mounts, "compile_mount_plan", planner)
  monkeypatch.setattr(pi_admitted_shell, "compile_mount_plan", planner)
  return seen


def public(raw):
  part, _, _ = raw[0]._compile(raw[4], {"command": "printf '" + PRIVATE + "'"})
  return {key: part[key] for key in ("resolution", "physical")}


def reject(action):
  with pytest.raises(Conflict) as caught: action()
  assert caught.value.args == ("SHELL_BACKEND_UNAVAILABLE",)
  assert PRIVATE not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_default_selected_host_installs_shell_and_exact_shared_file_ledger(tmp_path, monkeypatch, profile):
  host, raw = default_host(tmp_path, monkeypatch, profile=profile)
  control = host.operations.admission_control
  assert control.shell_bridge is not None, "default selected Shell bridge missing"
  assert type(control.bridge.ledger) is OperationAdmissions
  assert host.operations.admission is control.bridge
  assert control.bridge.ledger is control.shell_bridge.ledger is control._shared_admissions
  assert control.bridge.ledger.activation_id == host.store.owner["manager_activation_id"]
  assert control.bridge.ledger.max_operations == 4096
  assert control.bridge.ledger.max_private_bytes == 32 * 1024 * 1024
  host.operations.now = lambda: datetime(2030, 1, 1, tzinfo=timezone.utc)
  assert control.bridge.ledger.now_ms() == int(host.operations.now().timestamp() * 1000)
  assert control.shell_bridge.context_provider.__self__ is control
  assert control.shell_bridge.binding_name == "shell"
  assert control.shell_bridge.backend_preflight.__self__ is host
  assert not host.children and not host.store.records()


@pytest.mark.parametrize("profile,selected", [("pi-base", False), ("pi-full", False), ("legacy", True)])
def test_no_selection_or_legacy_never_imports_shell_factory(tmp_path, monkeypatch, profile, selected):
  original = builtins.__import__
  seen = []
  def imported(name, *args, **kwargs):
    if name.endswith("pi_admitted_shell"):
      seen.append(name); raise AssertionError("unselected Shell imported")
    return original(name, *args, **kwargs)
  # raw fixture already imported its bridge; guard only actual default Host construction.
  monkeypatch.setattr(builtins, "__import__", imported)
  host, raw = default_host(tmp_path, monkeypatch, profile=profile, selected=selected)
  control = host.operations.admission_control
  assert control is None if profile == "legacy" else control.shell_bridge is None
  assert seen == []


def test_default_backend_reads_bound_helper_and_returns_complete_real_plan_without_spawn(tmp_path, monkeypatch):
  host, raw = default_host(tmp_path, monkeypatch)
  seen = real_small_planner(monkeypatch)
  value = public(raw)
  proof = host._shell_backend_preflight(value)
  assert proof["runtime_identity"] == host.runtime_root.name
  assert proof["helper_identity"] == hashlib.sha256((host.runtime_root / "bin/pi-bwrap").read_bytes()).hexdigest()
  assert proof["plan_digest"] == digest(proof["mount_plan"])
  assert proof["mount_plan"]["network"] == "deny"
  assert seen and all(set(row) == {"resolution", "physical"} for row in seen)
  assert PRIVATE not in repr(seen) + repr(proof)
  assert not host.children and not host.store.records()


@pytest.mark.parametrize("fault", ["helper", "receipt", "unsafe-plan", "non-linux", "private-input"])
def test_backend_failures_fixed_unavailable_with_zero_spawn(tmp_path, monkeypatch, fault):
  host, raw = default_host(tmp_path, monkeypatch)
  real_small_planner(monkeypatch)
  value = public(raw)
  if fault == "helper": (host.runtime_root / "bin/pi-bwrap").write_bytes(b"changed helper")
  if fault == "receipt":
    path = host.runtime_root / ".agentcfg-receipt.json"
    receipt = json.loads(path.read_bytes()); receipt["lock_identity"] = "f" * 64; path.write_bytes(json_bytes(receipt))
  if fault == "unsafe-plan": value["physical"]["denied_paths"] = [value["physical"]["cwd"]]
  if fault == "non-linux": monkeypatch.setattr(pi_host.sys, "platform", "darwin")
  if fault == "private-input": value["command"] = PRIVATE
  reject(lambda: host._shell_backend_preflight(value))
  assert not host.children and not host.store.records()


def test_helper_coherent_change_during_planner_is_not_old_helper_proof(tmp_path, monkeypatch):
  host, raw = default_host(tmp_path, monkeypatch)
  value = public(raw)
  def changed():
    path = host.runtime_root / "bin/pi-bwrap"
    body = path.read_bytes() + b"changed after read"; path.write_bytes(body)
    path = host.runtime_root / ".agentcfg-receipt.json"
    receipt = json.loads(path.read_bytes()); receipt["files"]["bin/pi-bwrap"]["sha256"] = hashlib.sha256(body).hexdigest()
    path.write_bytes(json_bytes(receipt))
  real_small_planner(monkeypatch, mutate=changed)
  reject(lambda: host._shell_backend_preflight(value))
  assert not host.children and not host.store.records()


def test_default_control_prepares_consumes_and_resolves_only_linux_shell_ticket(tmp_path, monkeypatch):
  host, raw = default_host(tmp_path, monkeypatch)
  real_small_planner(monkeypatch)
  entry = "supervisor/scripts/pi-shell.py"
  with Tree(host.runtime_root) as tree:
    tree.write_new(entry, b"synthetic worker, never execute")
    tree.write_new("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"ordinary-shell": {
      "entrypoint": entry, "kind": "external", "engine": "python"}}}))
    receipt = json.loads(tree.read(".agentcfg-receipt.json")[0])
    for name in (entry, "runtime/commands.json"):
      body = tree.read(name); receipt["files"][name] = {"kind": "file", "mode": body[1], "sha256": hashlib.sha256(body[0]).hexdigest()}
    tree.write_state(".agentcfg-receipt.json", json_bytes(receipt))
  parent = host.store.allocate(kind="host", execution_id="synthetic-manager", task_id=None, attempt_id="a" * 32,
    lock_identity=host.config["lock_identity"], slice_identity=host.config["slice_identity"], policy_digest=host.config["policy_digest"],
    candidate_digest=None, planned_workspaces=[])
  parent = host.store.start(parent["lease_id"], host.store.owner, spawn=lambda _: host.store.owner["supervisor_process_identity"])
  host.host_lease_id = parent["lease_id"]
  principal = Principal("manager", parent["lease_id"], parent["grant_generation"])
  current = deepcopy(raw[4]); current.update(activation_id=host.store.owner["manager_activation_id"],
    runtime_identity=host.runtime_root.name, config_identity=host.config["manifest_digest"])
  control = host.operations.admission_control
  control.open(principal, {"control_id": "default", "session_id": current["session_id"]})
  prepared = control.prepare(principal, {"control_id": "default", "request_id": "bash", "context": current,
    "tool_name": "bash", "input": {"command": "printf '" + PRIVATE + "'"}})
  permit = control.issue(principal, {"operation_id": prepared["operation_id"], "context": current})
  ticket = control.consume(principal, {"permit": permit, "context": current})
  lease = host.store.read(ticket["lease_id"])
  command = host.resolve_command(lease, "ordinary-shell", {"operation_id": prepared["operation_id"]})
  assert command.process_scope == "linux-shell"
  assert PRIVATE not in repr(command) + repr(command.argv) + repr(command.environment)
  assert not host.children
