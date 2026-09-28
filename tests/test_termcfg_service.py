"""代理服务仅操作可验证的本机租约，私人值不泄露。"""

import json
import threading
import time

import pytest

from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.errors import TermcfgError
from termcfg import mihomo
from termcfg.state import read_state, state_file, write_json


def test_service_status_does_not_read_private_config(isolated_environment):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  directory = machine.private_state_root / "mihomo"
  directory.mkdir(parents=True, mode=0o700)
  secret = directory / "private.yaml"
  secret.write_text("secret: synthetic-private\n")
  secret.chmod(0o000)
  assert mihomo.service_status(machine)["service"] == "stopped"


def test_start_uses_private_yaml_and_lease_omits_secret(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  public = machine.target_home / ".config/termcfg/mihomo/base.yaml"
  public.parent.mkdir(parents=True)
  public.write_bytes((mihomo.REPO_ROOT / "terminals/mihomo/base.yaml").read_bytes())
  private_dir = machine.private_state_root / "mihomo"
  private_dir.mkdir(parents=True, mode=0o700)
  private = private_dir / "private.yaml"
  private.write_text("secret: synthetic-private\nproxies:\n  - name: fake\n    type: direct\n")
  private.chmod(0o600)
  binary = isolated_environment.root / "fake-core"
  binary.write_bytes(b"synthetic executable")
  binary.chmod(0o700)
  monkeypatch.setattr(mihomo, "installed_core", lambda machine: binary)
  monkeypatch.setattr(mihomo, "core_asset", lambda: ({"sha256": "a" * 64}, "synthetic-lock"))
  monkeypatch.setattr(mihomo, "_port_available", lambda: True)
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {"pid": pid, "uid": __import__("os").getuid(), "start_ticks": "synthetic", "executable": str(binary)})
  monkeypatch.setattr(mihomo, "_wait_for_health", lambda *a, **k: {"version": "synthetic"})
  monkeypatch.setattr(mihomo, "_public_loaded", lambda secret: secret == "synthetic-private")
  class FakeProcess:
    pid = 4242
  monkeypatch.setattr(mihomo.subprocess, "Popen", lambda *a, **k: FakeProcess())
  state = read_state(machine)
  state["selected_core"] = "a" * 64
  state["pending_core_effect"] = True
  state["pending_config_effect"] = True
  from termcfg.home_targets import inspect_target
  import hashlib
  identity = inspect_target(machine.target_home, __import__("pathlib").Path(".config/termcfg/mihomo/base.yaml"))
  digest = hashlib.sha256(public.read_bytes()).hexdigest()
  state["targets"]["mihomo-base"] = {"component": "mihomo", "after": {**identity.as_dict(), "digest": digest}, "source_digest": digest}
  write_json(state_file(machine), state)
  result = mihomo.service_operation(machine, "start")
  assert result["effective"] == "effective"
  assert (private_dir / "effective.yaml").stat().st_mode & 0o777 == 0o600
  lease = (private_dir / "service.json").read_text()
  assert "synthetic-private" not in lease
  assert "synthetic-private" not in state_file(machine).read_text()
  assert read_state(machine)["pending_core_effect"] is False


def test_unknown_process_cannot_be_stopped(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  directory = machine.private_state_root / "mihomo"
  directory.mkdir(parents=True, mode=0o700)
  write_json(directory / "service.json", {"version": 1, "pid": 12345, "uid": 0,
             "start_ticks": "old", "executable": "/tmp/other", "core_sha256": "a" * 64,
             "public_config_identity": None, "controller": "127.0.0.1:9090", "state": "running"})
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: None)
  assert mihomo.service_status(machine)["service"] == "unknown/external"
  with pytest.raises(TermcfgError) as error:
    mihomo.service_operation(machine, "stop")
  assert error.value.code == 4


def test_health_failure_terminates_new_child_and_keeps_pending_effect(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  public = machine.target_home / ".config/termcfg/mihomo/base.yaml"
  public.parent.mkdir(parents=True)
  public.write_bytes((mihomo.REPO_ROOT / "terminals/mihomo/base.yaml").read_bytes())
  private_dir = machine.private_state_root / "mihomo"
  private_dir.mkdir(parents=True, mode=0o700)
  private = private_dir / "private.yaml"
  private.write_text("secret: synthetic-private\nproxies:\n  - name: fake\n    type: direct\n")
  private.chmod(0o600)
  binary = isolated_environment.root / "fake-core"
  binary.write_bytes(b"synthetic executable")
  binary.chmod(0o700)
  state = read_state(machine)
  state["selected_core"] = "a" * 64
  state["pending_core_effect"] = True
  state["pending_config_effect"] = True
  from termcfg.home_targets import inspect_target
  import hashlib
  identity = inspect_target(machine.target_home, __import__("pathlib").Path(".config/termcfg/mihomo/base.yaml"))
  digest = hashlib.sha256(public.read_bytes()).hexdigest()
  state["targets"]["mihomo-base"] = {"component": "mihomo", "after": {**identity.as_dict(), "digest": digest}, "source_digest": digest}
  write_json(state_file(machine), state)
  alive = [True]
  monkeypatch.setattr(mihomo, "installed_core", lambda machine: binary)
  monkeypatch.setattr(mihomo, "core_asset", lambda: ({"sha256": "a" * 64}, "synthetic-lock"))
  monkeypatch.setattr(mihomo, "_port_available", lambda: True)
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {"pid": pid, "uid": __import__("os").getuid(), "start_ticks": "synthetic", "executable": str(binary)} if alive[0] else None)
  monkeypatch.setattr(mihomo, "_wait_for_health", lambda *a, **k: (_ for _ in ()).throw(TermcfgError(5, "synthetic_health_failure")))
  signals = []
  def kill(pid, value):
    signals.append((pid, value))
    alive[0] = False
  monkeypatch.setattr(mihomo.os, "kill", kill)
  class FakeProcess:
    pid = 4242
    def wait(self, timeout):
      alive[0] = False
  monkeypatch.setattr(mihomo.subprocess, "Popen", lambda *a, **k: FakeProcess())
  with pytest.raises(TermcfgError):
    mihomo.service_operation(machine, "start")
  assert signals and signals[0][0] == 4242
  assert not (private_dir / "service.json").exists()
  assert read_state(machine)["pending_core_effect"] is True
  assert read_state(machine)["pending_config_effect"] is True


def test_stop_uses_only_verified_lease_and_does_not_read_private_yaml(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  directory = machine.private_state_root / "mihomo"
  directory.mkdir(parents=True, mode=0o700)
  private = directory / "private.yaml"
  private.write_text("secret: synthetic-private\n")
  private.chmod(0o000)
  lease = {"version": 1, "pid": 4242, "uid": __import__("os").getuid(),
           "start_ticks": "synthetic", "executable": "/synthetic/core", "core_sha256": "a" * 64,
           "public_config_identity": None, "controller": "127.0.0.1:9090", "state": "running"}
  write_json(directory / "service.json", lease)
  alive = [True]
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {key: lease[key] for key in ("pid", "uid", "start_ticks", "executable")} if alive[0] else None)
  signals = []
  def fake_kill(pid, signum):
    signals.append((pid, signum))
    alive[0] = False
  monkeypatch.setattr(mihomo.os, "kill", fake_kill)
  assert mihomo.service_operation(machine, "stop")["service"] == "stopped"
  assert len(signals) == 1
  assert not (directory / "service.json").exists()


def test_reload_keeps_config_pending_without_public_load_evidence(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  directory = machine.private_state_root / "mihomo"
  directory.mkdir(parents=True, mode=0o700)
  lease = {"version": 1, "pid": 4242, "uid": __import__("os").getuid(),
           "start_ticks": "synthetic", "executable": "/synthetic/core", "core_sha256": "a" * 64,
           "public_config_identity": None, "controller": "127.0.0.1:9090", "state": "running"}
  write_json(directory / "service.json", lease)
  state = read_state(machine)
  state["pending_config_effect"] = True
  write_json(state_file(machine), state)
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {key: lease[key] for key in ("pid", "uid", "start_ticks", "executable")})
  monkeypatch.setattr(mihomo.MihomoPrivateRuntime, "prepare", lambda self: (directory / "effective.yaml", "synthetic-private"))
  monkeypatch.setattr(mihomo, "_api", lambda *a, **k: (204, None))
  monkeypatch.setattr(mihomo, "_wait_for_health", lambda *a, **k: {"version": "synthetic"})
  monkeypatch.setattr(mihomo, "_public_loaded", lambda secret: False)
  result = mihomo.service_operation(machine, "reload")
  assert result["effective"] == "unverified"
  assert result["pending_config_effect"] is True
  assert read_state(machine)["pending_config_effect"] is True


def test_repeated_start_checks_health_without_rewriting_effective_yaml(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  directory = machine.private_state_root / "mihomo"
  directory.mkdir(parents=True, mode=0o700)
  lease = {"version": 1, "pid": 4242, "uid": __import__("os").getuid(),
           "start_ticks": "synthetic", "executable": "/synthetic/core", "core_sha256": "a" * 64,
           "public_config_identity": None, "controller": "127.0.0.1:9090", "state": "running"}
  write_json(directory / "service.json", lease)
  private = directory / "private.yaml"
  private.write_text("secret: synthetic-private\nproxies:\n  - name: fake\n    type: direct\n")
  private.chmod(0o600)
  effective = directory / "effective.yaml"
  effective.write_text("original effective bytes\n")
  effective.chmod(0o600)
  original_inode = effective.stat().st_ino
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {key: lease[key] for key in ("pid", "uid", "start_ticks", "executable")})
  monkeypatch.setattr(mihomo, "_wait_for_health", lambda *a, **k: {"version": "synthetic"})
  result = mihomo.service_operation(machine, "start")
  assert result["idempotent"] is True
  assert effective.stat().st_ino == original_inode


def test_lease_write_failure_terminates_started_core(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  public = machine.target_home / ".config/termcfg/mihomo/base.yaml"
  public.parent.mkdir(parents=True)
  public.write_bytes((mihomo.REPO_ROOT / "terminals/mihomo/base.yaml").read_bytes())
  private_dir = machine.private_state_root / "mihomo"
  private_dir.mkdir(parents=True, mode=0o700)
  private = private_dir / "private.yaml"
  private.write_text("secret: synthetic-private\nproxies:\n  - name: fake\n    type: direct\n")
  private.chmod(0o600)
  binary = isolated_environment.root / "fake-core"
  binary.write_bytes(b"synthetic executable")
  binary.chmod(0o700)
  from termcfg.home_targets import inspect_target
  import hashlib
  state = read_state(machine)
  state["selected_core"] = "a" * 64
  identity = inspect_target(machine.target_home, __import__("pathlib").Path(".config/termcfg/mihomo/base.yaml"))
  digest = hashlib.sha256(public.read_bytes()).hexdigest()
  state["targets"]["mihomo-base"] = {"component": "mihomo", "after": {**identity.as_dict(), "digest": digest}, "source_digest": digest}
  write_json(state_file(machine), state)
  alive = [True]
  monkeypatch.setattr(mihomo, "installed_core", lambda machine: binary)
  monkeypatch.setattr(mihomo, "core_asset", lambda: ({"sha256": "a" * 64}, "synthetic-lock"))
  monkeypatch.setattr(mihomo, "_port_available", lambda: True)
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {"pid": pid, "uid": __import__("os").getuid(), "start_ticks": "synthetic", "executable": str(binary)} if alive[0] else None)
  monkeypatch.setattr(mihomo.os, "kill", lambda pid, signum: alive.__setitem__(0, False))
  class FakeProcess:
    pid = 4242
    def wait(self, timeout):
      alive[0] = False
  monkeypatch.setattr(mihomo.subprocess, "Popen", lambda *a, **k: FakeProcess())
  original_write = mihomo.write_json
  def fail_lease(path, value):
    if path.name == "service.json":
      raise OSError("synthetic lease write failure")
    return original_write(path, value)
  monkeypatch.setattr(mihomo, "write_json", fail_lease)
  with pytest.raises(OSError):
    mihomo.service_operation(machine, "start")
  assert alive[0] is False
  assert not (private_dir / "service.json").exists()


def test_public_load_requires_all_observable_fields(isolated_environment, monkeypatch):
  monkeypatch.setattr(mihomo, "_api", lambda *a, **k: (200, {"mixed-port": 7890, "mode": "rule", "allow-lan": False}))
  assert mihomo._public_loaded("synthetic-private") is False
  import yaml
  public = yaml.safe_load((mihomo.REPO_ROOT / "terminals/mihomo/base.yaml").read_bytes())
  monkeypatch.setattr(mihomo, "_api", lambda *a, **k: (200, public))
  assert mihomo._public_loaded("synthetic-private") is True


def test_child_exit_during_health_clears_failed_lease_for_retry(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  public = machine.target_home / ".config/termcfg/mihomo/base.yaml"
  public.parent.mkdir(parents=True)
  public.write_bytes((mihomo.REPO_ROOT / "terminals/mihomo/base.yaml").read_bytes())
  private_dir = machine.private_state_root / "mihomo"
  private_dir.mkdir(parents=True, mode=0o700)
  private = private_dir / "private.yaml"
  private.write_text("secret: synthetic-private\nproxies:\n  - name: fake\n    type: direct\n")
  private.chmod(0o600)
  binary = isolated_environment.root / "fake-core"
  binary.write_bytes(b"synthetic executable")
  binary.chmod(0o700)
  from termcfg.home_targets import inspect_target
  import hashlib
  state = read_state(machine)
  state["selected_core"] = "a" * 64
  identity = inspect_target(machine.target_home, __import__("pathlib").Path(".config/termcfg/mihomo/base.yaml"))
  digest = hashlib.sha256(public.read_bytes()).hexdigest()
  state["targets"]["mihomo-base"] = {"component": "mihomo", "after": {**identity.as_dict(), "digest": digest}, "source_digest": digest}
  write_json(state_file(machine), state)
  alive = [True]
  monkeypatch.setattr(mihomo, "installed_core", lambda machine: binary)
  monkeypatch.setattr(mihomo, "core_asset", lambda: ({"sha256": "a" * 64}, "synthetic-lock"))
  monkeypatch.setattr(mihomo, "_port_available", lambda: True)
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {"pid": pid, "uid": __import__("os").getuid(), "start_ticks": "synthetic", "executable": str(binary)} if alive[0] else None)
  class FakeProcess:
    pid = 4242
    def poll(self):
      return None if alive[0] else 1
    def wait(self, timeout):
      return 1
  monkeypatch.setattr(mihomo.subprocess, "Popen", lambda *a, **k: FakeProcess())
  def exit_during_health(*args, **kwargs):
    alive[0] = False
    raise TermcfgError(5, "synthetic_health_failure")
  monkeypatch.setattr(mihomo, "_wait_for_health", exit_during_health)
  with pytest.raises(TermcfgError):
    mihomo.service_operation(machine, "start")
  assert not (private_dir / "service.json").exists()
  alive[0] = True
  monkeypatch.setattr(mihomo, "_wait_for_health", lambda *a, **k: {"version": "synthetic"})
  monkeypatch.setattr(mihomo, "_public_loaded", lambda secret: False)
  assert mihomo.service_operation(machine, "start")["service"] == "running"


def test_service_and_apply_lose_to_active_sync_before_side_effects(isolated_environment,
                                                                    fake_terminal_commands, monkeypatch):
  from termcfg import packages
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  entered = threading.Event()
  release = threading.Event()
  def held_plugin_sync(*args, **kwargs):
    entered.set()
    release.wait(5)
    return {"component": "zsh", "prepared": [], "next_command": "./termcfg doctor"}
  monkeypatch.setattr(packages, "_sync_plugins", held_plugin_sync)
  results = []
  thread = threading.Thread(target=lambda: results.append(packages.sync(machine, "zsh")))
  thread.start()
  assert entered.wait(2)
  state_path = state_file(machine)
  try:
    with pytest.raises(TermcfgError) as error:
      mihomo.service_operation(machine, "start")
    assert error.value.code == 4
    assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 4
    assert not (machine.private_state_root / "journal.json").exists()
    assert not state_path.exists()
    assert not (machine.private_state_root / "mihomo/service.json").exists()
    assert not (isolated_environment.home / ".zshrc").exists()
  finally:
    release.set()
    thread.join(3)
  assert results and results[0]["component"] == "zsh"


def test_active_service_start_blocks_sync_and_apply(isolated_environment, fake_terminal_commands,
                                                    monkeypatch):
  from termcfg import packages
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  entered = threading.Event()
  release = threading.Event()
  def held_start(*args, **kwargs):
    entered.set()
    release.wait(5)
    return {"service": "running", "effective": "unverified"}
  monkeypatch.setattr(mihomo, "_start_locked", held_start)
  thread = threading.Thread(target=lambda: mihomo.service_operation(machine, "start"))
  thread.start()
  assert entered.wait(2)
  try:
    with pytest.raises(TermcfgError) as error:
      packages.sync(machine, "zsh")
    assert error.value.code == 4
    assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 4
    assert not (machine.private_state_root / "state.json").exists()
    assert not (isolated_environment.home / ".zshrc").exists()
  finally:
    release.set()
    thread.join(3)


def test_external_port_refuses_start_before_process_creation(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  monkeypatch.setattr(mihomo, "_port_available", lambda: False)
  with pytest.raises(TermcfgError) as error:
    mihomo.service_operation(machine, "start")
  assert error.value.code == 4
  assert error.value.reason == "external_controller_busy"


def test_restart_stops_then_starts_under_one_machine_lease(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  events = []
  monkeypatch.setattr(mihomo, "_stop_locked", lambda *a, **k: events.append("stop") or {"service": "stopped"})
  monkeypatch.setattr(mihomo, "_start_locked", lambda *a, **k: events.append("start") or {"service": "running"})
  assert mihomo.service_operation(machine, "restart")["service"] == "running"
  assert events == ["stop", "start"]


def test_reload_health_failure_keeps_pending_flag(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  directory = machine.private_state_root / "mihomo"
  directory.mkdir(parents=True, mode=0o700)
  lease = {"version": 1, "pid": 4242, "uid": __import__("os").getuid(),
           "start_ticks": "synthetic", "executable": "/synthetic/core", "core_sha256": "a" * 64,
           "public_config_identity": None, "controller": "127.0.0.1:9090", "state": "running"}
  write_json(directory / "service.json", lease)
  state = read_state(machine)
  state["pending_config_effect"] = True
  write_json(state_file(machine), state)
  monkeypatch.setattr(mihomo, "_process_identity", lambda pid: {key: lease[key] for key in ("pid", "uid", "start_ticks", "executable")})
  monkeypatch.setattr(mihomo.MihomoPrivateRuntime, "prepare", lambda self: (directory / "effective.yaml", "synthetic-private"))
  monkeypatch.setattr(mihomo, "_api", lambda *a, **k: (204, None))
  monkeypatch.setattr(mihomo, "_wait_for_health", lambda *a, **k: (_ for _ in ()).throw(TermcfgError(5, "synthetic_health_timeout")))
  with pytest.raises(TermcfgError):
    mihomo.service_operation(machine, "reload")
  assert read_state(machine)["pending_config_effect"] is True


def test_health_wait_reports_heartbeat_and_timeout(isolated_environment, monkeypatch, capsys):
  from termcfg.diagnostics import Progress
  def slow_failure(*args, **kwargs):
    time.sleep(1.7)
    raise TermcfgError(5, "synthetic_unhealthy")
  monkeypatch.setattr(mihomo, "_api", slow_failure)
  with pytest.raises(TermcfgError) as error:
    mihomo._wait_for_health("synthetic-private", timeout=1.6, progress=Progress("service start"))
  assert error.value.reason == "service_health_timeout"
  assert "service start | health | mihomo" in capsys.readouterr().err


def test_health_wait_interrupt_propagates_without_secret(isolated_environment, monkeypatch, capsys):
  from termcfg.diagnostics import Progress
  monkeypatch.setattr(mihomo, "_api", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
  with pytest.raises(KeyboardInterrupt):
    mihomo._wait_for_health("synthetic-private", timeout=1, progress=Progress("service start"))
  assert "synthetic-private" not in capsys.readouterr().err


def test_sync_and_apply_leave_service_stopped_with_separate_pending_causes(isolated_environment,
                                                                            monkeypatch, capsys):
  import gzip
  import hashlib
  from termcfg import packages
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  archive = gzip.compress(b"synthetic-core-not-executable")
  asset = {"version": "v1.0.0", "platform": "linux-x86_64",
           "name": "mihomo-linux-amd64-compatible-v1.0.0.gz",
           "url": "https://github.com/MetaCubeX/mihomo/releases/download/v1.0.0/mihomo-linux-amd64-compatible-v1.0.0.gz",
           "size": len(archive), "sha256": hashlib.sha256(archive).hexdigest(),
           "archive": "gzip-single", "entry": "mihomo", "resources": []}
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: ({"assets": {"linux-x86_64": asset}}, "synthetic-snapshot"))
  monkeypatch.setattr(packages, "_download", lambda *a, **k: archive)
  assert packages.sync(machine, "mihomo")["pending_core_effect"] is True
  plan = build_preview(machine, ("mihomo",))
  capsys.readouterr()
  assert main(["plan", "--component", "mihomo", "--json"]) == 0
  assert json.loads(capsys.readouterr().out)["environment"]["mihomo"]["service"]["service"] == "stopped"
  assert main(["apply", "--component", "mihomo", "--plan-id", plan.plan_id, "--json"]) == 0
  applied = json.loads(capsys.readouterr().out)
  assert applied["pending_core_effect"] is True
  assert applied["pending_config_effect"] is True
  state = read_state(machine)
  assert state["pending_core_effect"] is True
  assert state["pending_config_effect"] is True
  assert mihomo.service_status(machine)["service"] == "stopped"
  assert not (machine.private_state_root / "mihomo/service.json").exists()
