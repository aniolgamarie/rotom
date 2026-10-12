"""按冻结manifest选择构造监督能力；真实构造链与假进程，不启动宿主。"""
import builtins
import json
import os
from pathlib import Path

import pytest

from agentcfg import pi_host
from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.pi_supervisor import Principal
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_activity import FakeProcesses, identity
from test_pi_supervisor import request


def configured(tmp_path, monkeypatch, plugins):
  processes = FakeProcesses(); processes.current[os.getpid()] = identity(os.getpid())
  processes.identity = lambda pid: processes.current[pid]
  monkeypatch.setattr(pi_host, "LinuxProcesses", lambda *args: processes)
  monkeypatch.setattr(pi_host.sys, "platform", "linux")
  instance = tmp_path / "instance"; home = instance / "pi-home"
  home.mkdir(parents=True, mode=0o700); instance.chmod(0o700)
  manifest = {"schema_version": 1, "plugins": plugins, "options": {}, "permission_policy": {"schema_version": 1, "default": "deny", "rules": []}}
  file = home / "agentcfg-manifest.json"; file.write_bytes(json_bytes(manifest)); file.chmod(0o600)
  config = {"state_root": str(tmp_path / "state"), "instance_root": str(instance),
    "repository": str(Path(__file__).resolve().parents[1]), "runtime_root": str(tmp_path / "runtime"), "instance_id": "fixture",
    "lock_identity": "a" * 64, "slice_identity": "b" * 64, "policy_digest": digest(manifest["permission_policy"]),
    "manifest_digest": digest(manifest), "cwd": str(tmp_path), "engine": "node", "argv": ["synthetic-host"], "delegate_request": {}}
  return config, file


@pytest.mark.parametrize("existing", [False, True])
def test_host_protects_passwd_account_anchor_without_creating_it(tmp_path, monkeypatch, existing):
  import pwd
  config, _ = configured(tmp_path, monkeypatch, [])
  anchor = Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".agentcfg-workspaces"
  other = str(tmp_path / "another-control-root")
  config["protected_roots"] = [other, *([str(anchor)] if existing else [])]
  before = list(config["protected_roots"])
  assert not anchor.exists()
  host = pi_host.HostSupervisor(config, lease_fd=None)
  assert host.config["protected_roots"] == [other, str(anchor)]
  assert list(host.service.protected_roots) == [other, str(anchor)]
  assert config["protected_roots"] == before
  assert not anchor.exists()


def poison_controller(monkeypatch):
  import agentcfg.pi_delegate as module
  def forbidden(*args, **kwargs): raise AssertionError("unselected Full controller constructed")
  monkeypatch.setattr(module, "DelegateController", forbidden)


def block_codex_formatting_import(monkeypatch):
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if name == "pi_codex_admission" or name.startswith("agentcfg.pi_codex_admission"):
      raise AssertionError("unselected error formatter imported Codex")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)


def test_unselected_full_controller_is_never_constructed_even_with_files(tmp_path, monkeypatch):
  config, _ = configured(tmp_path, monkeypatch, ["pi-permissions"])
  poison_controller(monkeypatch)
  full = Path(config["runtime_root"]) / "supervisor/shared/skills/model-delegate"; full.mkdir(parents=True)
  (full / "poison.txt").write_text("not an activation source")
  host = pi_host.HostSupervisor(config, lease_fd=None)
  assert host.delegates is None and host.service.delegate_handler is None
  assert not (Path(config["instance_root"]) / "pi-home/model-delegate").exists()
  assert host.operations is not None
  host.poll()


def test_unselected_full_module_is_not_imported_when_files_absent(tmp_path, monkeypatch):
  config, _ = configured(tmp_path, monkeypatch, [])
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if name == "pi_delegate" or name.startswith("agentcfg.pi_delegate"):
      raise AssertionError("unselected Full module imported")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  host = pi_host.HostSupervisor(config, lease_fd=None)
  assert host.delegates is None
  assert not Path(config["runtime_root"]).exists()


@pytest.mark.parametrize("method", ["delegate_prepare", "delegate_start", "delegate_status", "delegate_command_start"])
def test_unselected_delegate_dispatch_returns_dependency_error(tmp_path, monkeypatch, method):
  config, _ = configured(tmp_path, monkeypatch, [])
  poison_controller(monkeypatch)
  host = pi_host.HostSupervisor(config, lease_fd=None)
  with pytest.raises(DependencyError) as error:
    host.service.handle(Principal("delegate"), request(method, {}))
  assert error.value.exit_code == 5
  token = host.service.issue_capability("delegate")
  block_codex_formatting_import(monkeypatch)
  reply = host.service.reply(token, os.geteuid(), request(method, {}))
  assert reply["ok"] is False and reply["exit_code"] == 5
  assert reply["error"] == "DELEGATE_CAPABILITY_UNAVAILABLE"
  assert host.children == {} and host.store.records() == []


def test_unselected_standalone_delegate_reports_code5_and_cleans_endpoint(tmp_path, monkeypatch):
  config, _ = configured(tmp_path, monkeypatch, [])
  poison_controller(monkeypatch)
  from agentcfg import pi_codex_admission
  def forbidden_probe(): raise AssertionError("unselected Codex probe executed")
  monkeypatch.setattr(pi_codex_admission, "_system_configuration_absent", forbidden_probe)
  lookups = []
  monkeypatch.setattr(pi_host.shutil, "which", lambda name: lookups.append(name))
  host = pi_host.HostSupervisor(config, lease_fd=None)
  events = []
  host.server.open = lambda: events.append("open")
  host.server.close = lambda: events.append("close")
  block_codex_formatting_import(monkeypatch)
  read_fd, write_fd = os.pipe()
  try:
    assert host.run_delegate(write_fd) == 5
    with pytest.raises(OSError): os.fstat(write_fd)
    reply = json.loads(os.read(read_fd, 4096))
    assert reply["ok"] is False and reply["exit_code"] == 5
    assert reply["error_code"] == "DELEGATE_CAPABILITY_UNAVAILABLE"
    assert events == ["open", "close"]
    assert lookups == ["node"]
    assert host.children == {} and host.store.records() == []
    assert not (Path(config["instance_root"]) / "pi-home/model-delegate").exists()
  finally:
    os.close(read_fd)


def test_selected_controller_constructs_handles_and_ticks(tmp_path, monkeypatch):
  import agentcfg.pi_delegate as module
  config, _ = configured(tmp_path, monkeypatch, ["model-delegate"])
  original = module.DelegateController; calls = []
  class Selected(original):
    def __init__(self, host):
      calls.append("construct"); super().__init__(host)
    def handle(self, principal, method, args):
      calls.append((principal.role, method)); return {"selected": True}
    def tick(self): calls.append("tick")
  monkeypatch.setattr(module, "DelegateController", Selected)
  host = pi_host.HostSupervisor(config, lease_fd=None)
  assert isinstance(host.delegates, Selected)
  assert host.service.delegate_handler.__self__ is host.delegates
  assert host.service.handle(Principal("delegate"), request("delegate_status", {})) == {"selected": True}
  host.poll()
  assert calls == ["construct", ("delegate", "delegate_status"), "tick"]


def test_selected_broken_controller_error_is_not_swallowed(tmp_path, monkeypatch):
  import agentcfg.pi_delegate as module
  config, _ = configured(tmp_path, monkeypatch, ["model-delegate"])
  def damaged(*args, **kwargs): raise DependencyError("synthetic selected package damaged")
  monkeypatch.setattr(module, "DelegateController", damaged)
  with pytest.raises(DependencyError, match="synthetic selected package damaged"):
    pi_host.HostSupervisor(config, lease_fd=None)


@pytest.mark.parametrize("fault", ["missing", "policy", "digest"])
def test_unselected_manifest_identity_errors_are_not_ignored(tmp_path, monkeypatch, fault):
  config, file = configured(tmp_path, monkeypatch, [])
  poison_controller(monkeypatch)
  if fault == "missing": file.unlink()
  if fault == "policy": config["policy_digest"] = "d" * 64
  if fault == "digest": config["manifest_digest"] = "d" * 64
  with pytest.raises(Conflict): pi_host.HostSupervisor(config, lease_fd=None)


@pytest.mark.parametrize("plugins", ["model-delegate", {"model-delegate": {}}, None, [True], ["model-delegate", "model-delegate"]])
def test_selection_shape_cannot_enable_delegate_by_substring_or_map(tmp_path, monkeypatch, plugins):
  config, _ = configured(tmp_path, monkeypatch, plugins)
  poison_controller(monkeypatch)
  with pytest.raises(ConfigError): pi_host.HostSupervisor(config, lease_fd=None)


def forbid_worker_imports(monkeypatch):
  original = builtins.__import__
  def guarded(name, *args, **kwargs):
    if any(part in name for part in ("pi_worker_files", "pi_worker_protocol")):
      raise AssertionError("unselected Worker module imported")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)


def test_fresh_base_host_import_and_workspace_snapshot_never_load_worker_modules(tmp_path, monkeypatch):
  import importlib.util
  from agentcfg.pi_workspace_snapshot import snapshot
  from test_pi_workspace_leases import worktree
  config, file = configured(tmp_path, monkeypatch, [])
  manifest = json.loads(file.read_bytes()); manifest["profile_id"] = "pi-base"
  file.write_bytes(json_bytes(manifest)); config["manifest_digest"] = digest(manifest)
  root = worktree(tmp_path / "project"); (root / "source").write_text("business source")
  expected = snapshot(root)
  forbid_worker_imports(monkeypatch)
  spec = importlib.util.spec_from_file_location("agentcfg._base_host_import_probe", pi_host.__file__)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  monkeypatch.setattr(module, "LinuxProcesses", pi_host.LinuxProcesses)
  host = module.HostSupervisor(config, lease_fd=None)
  assert host.service.worker_operation is None
  assert host.service.handle(Principal("manager"), request("workspace_snapshot", {"path": str(root)})) == {"snapshot_digest": expected}
  assert host.store.records() == []


def test_unselected_worker_resolution_rejects_before_registry_or_protocol(tmp_path, monkeypatch):
  config, _ = configured(tmp_path, monkeypatch, [])
  host = pi_host.HostSupervisor(config, lease_fd=None)
  reads = []
  def forbidden_read(*args, **kwargs):
    reads.append(args); raise AssertionError("unselected worker read registry or protocol")
  forbid_worker_imports(monkeypatch)
  monkeypatch.setattr("agentcfg.pi_host.Tree.read", forbidden_read)
  with pytest.raises(DependencyError) as caught:
    host.resolve_command({"kind": "worker"}, "worker", {})
  assert caught.value.exit_code == 5 and reads == []


def test_selected_task_keeper_constructs_actual_worker_files(tmp_path, monkeypatch):
  from agentcfg.pi_worker_files import WorkerFiles
  config, _ = configured(tmp_path, monkeypatch, ["task-keeper"])
  host = pi_host.HostSupervisor(config, lease_fd=None)
  assert isinstance(host.service.worker_operation, WorkerFiles)
  assert host.service.worker_operation.store is host.store
