"""显式管理自身启动的 mihomo；私人有效配置不进入普通状态。"""

import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import time
import urllib.request

import yaml

from .catalog import REPO_ROOT, load_catalog
from .config import MachineSelection, require_current_machine
from .diagnostics import Progress, heartbeat
from .errors import TermcfgError
from .home_targets import inspect_target, read_regular
from .lease import operation_lease
from .packages import core_asset, installed_core
from .state import atomic_bytes, private_dir, read_json, read_state, require_no_pending_recovery, state_file, write_json


_PRIVATE_KEYS = {"proxies", "proxy-providers", "proxy-groups", "rule-providers", "rules", "dns", "secret"}
_LEASE_KEYS = {"version", "pid", "uid", "start_ticks", "executable", "core_sha256", "public_config_identity", "controller", "state"}


def _runtime_dir(machine: MachineSelection) -> Path:
  return machine.private_state_root / "mihomo"


def _lease_path(machine: MachineSelection) -> Path:
  return _runtime_dir(machine) / "service.json"


def _private_file(path: Path) -> bytes:
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
    raise TermcfgError(4, "unsafe_private_config")
  fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
  try:
    checked = os.fstat(fd)
    if (checked.st_dev, checked.st_ino) != (info.st_dev, info.st_ino):
      raise TermcfgError(4, "private_config_changed")
    with os.fdopen(fd, "rb", closefd=False) as stream:
      data = stream.read(1024 * 1024 + 1)
      if len(data) > 1024 * 1024:
        raise TermcfgError(2, "private_config_too_large")
      return data
  finally:
    os.close(fd)


class MihomoPrivateRuntime:
  def __init__(self, machine: MachineSelection):
    self.machine = machine
    self.directory = _runtime_dir(machine)

  def _private_values(self) -> dict:
    private_dir(self.directory)
    try:
      private = yaml.safe_load(_private_file(self.directory / "private.yaml"))
    except FileNotFoundError as exc:
      raise TermcfgError(3, "private_config_missing", "在私人目录建立 0600 mihomo/private.yaml") from exc
    except yaml.YAMLError as exc:
      raise TermcfgError(2, "private_config_invalid") from exc
    if not isinstance(private, dict) or not set(private).issubset(_PRIVATE_KEYS):
      raise TermcfgError(2, "private_config_invalid")
    secret = private.get("secret")
    if not isinstance(secret, str) or not secret:
      raise TermcfgError(3, "controller_secret_missing")
    if not private.get("proxies") and not private.get("proxy-providers"):
      raise TermcfgError(3, "proxy_source_missing")
    return private

  def secret(self) -> str:
    return self._private_values()["secret"]

  def prepare(self) -> tuple[Path, str]:
    private = self._private_values()
    secret = private["secret"]
    artifact = next(item for item in load_catalog() if item.id == "mihomo-base")
    identity = inspect_target(self.machine.target_home, artifact.destination)
    managed = read_state(self.machine)["targets"].get("mihomo-base")
    if identity.kind != "file" or managed is None:
      raise TermcfgError(5, "public_config_missing", "./termcfg apply --component mihomo")
    public_bytes = read_regular(self.machine.target_home, artifact.destination, identity)
    import hashlib
    observed = {**identity.as_dict(), "digest": hashlib.sha256(public_bytes).hexdigest()}
    if observed != managed["after"] or observed["digest"] != artifact.sha256:
      raise TermcfgError(4, "public_config_drift", "./termcfg plan --component mihomo")
    try:
      public = yaml.safe_load(public_bytes)
    except yaml.YAMLError as exc:
      raise TermcfgError(5, "public_config_missing", "./termcfg apply --component mihomo") from exc
    if not isinstance(public, dict) or "secret" in public or not str(public.get("external-controller", "")).startswith("127.0.0.1:"):
      raise TermcfgError(2, "public_config_invalid")
    merged = {**public, **private}
    try:
      rendered = yaml.safe_dump(merged, allow_unicode=True, sort_keys=True).encode()
      if not isinstance(yaml.safe_load(rendered), dict):
        raise ValueError("render")
    except (yaml.YAMLError, ValueError) as exc:
      raise TermcfgError(2, "effective_config_invalid") from exc
    path = self.directory / "effective.yaml"
    atomic_bytes(path, rendered, mode=0o600)
    return path, secret


def _process_identity(pid: int) -> dict | None:
  try:
    proc = Path("/proc") / str(pid)
    uid = proc.stat().st_uid
    raw = (proc / "stat").read_text()
    # comm 可含空格，最后一个 ')' 后从 state 字段开始。
    fields = raw.rsplit(")", 1)[1].strip().split()
    if fields[0] == "Z":
      return None
    start_ticks = fields[19]
    executable = os.readlink(proc / "exe")
    return {"pid": pid, "uid": uid, "start_ticks": start_ticks,
            "executable": executable}
  except (OSError, IndexError, ValueError):
    return None


def _read_lease(machine: MachineSelection) -> dict | None:
  directory = _runtime_dir(machine)
  if directory.exists() or directory.is_symlink():
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise TermcfgError(4, "unsafe_runtime_directory")
  value = read_json(_lease_path(machine))
  if value is not None and (set(value) != _LEASE_KEYS or value["version"] != 1):
    raise TermcfgError(2, "invalid_service_lease")
  return value


def _matches(lease: dict) -> bool:
  observed = _process_identity(lease["pid"])
  return observed is not None and all(observed.get(key) == lease[key] for key in ("pid", "uid", "start_ticks", "executable"))


def service_status(machine: MachineSelection) -> dict:
  lease = _read_lease(machine)
  if lease is None:
    return {"service": "stopped", "effective": "unverified", "reason": "no_service_lease"}
  if not _matches(lease):
    return {"service": "unknown/external", "effective": "unverified", "reason": "process_identity_mismatch"}
  if lease["state"] != "running":
    return {"service": lease["state"], "effective": "unverified", "reason": "service_operation_incomplete",
            "pid": lease["pid"]}
  return {"service": "running", "effective": "unverified", "reason": "health_not_checked",
          "pid": lease["pid"]}


def _controller_url() -> str:
  return "http://127.0.0.1:9090"


def _api(method: str, path: str, secret: str, *, payload: dict | None = None, timeout: float = 2.0):
  data = json.dumps(payload).encode() if payload is not None else None
  request = urllib.request.Request(_controller_url() + path, data=data, method=method,
                                   headers={"Authorization": "Bearer " + secret,
                                            "Content-Type": "application/json"})
  try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
      raw = response.read(1024 * 1024)
      return response.status, json.loads(raw) if raw else None
  except (OSError, ValueError) as exc:
    raise TermcfgError(5, "service_health_failed", "./termcfg service status") from exc


def _wait_for_health(secret: str, *, timeout: float, progress: Progress) -> dict:
  progress.stage("health", component="mihomo")
  end = time.monotonic() + timeout
  last_error = None
  with heartbeat(progress, "health", component="mihomo"):
    while time.monotonic() < end:
      try:
        status, version = _api("GET", "/version", secret, timeout=min(2, max(0.2, end - time.monotonic())))
        if status == 200 and isinstance(version, dict):
          return version
      except TermcfgError as exc:
        last_error = exc
      time.sleep(0.25)
  raise TermcfgError(5, "service_health_timeout", "./termcfg service status") from last_error


def _public_loaded(secret: str) -> bool:
  try:
    status, observed = _api("GET", "/configs", secret)
    public = yaml.safe_load(next(item for item in load_catalog() if item.id == "mihomo-base").bytes())
    return (status == 200 and isinstance(observed, dict) and isinstance(public, dict) and
            all(key in observed and observed[key] == value for key, value in public.items()))
  except TermcfgError:
    return False


def _port_available() -> bool:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
      connection.bind(("127.0.0.1", 9090))
      return True
    except OSError:
      return False


def _cleanup_failed_start(machine: MachineSelection, process, lease: dict | None,
                          state_before_effect: dict | None, state_effect_committed: bool) -> None:
  """只向本次创建且身份可确认的子进程发信号；清理失败保留租约。"""
  try:
    if lease is not None and _matches(lease):
      os.kill(lease["pid"], signal.SIGTERM)
    elif lease is None and process.poll() is None:
      process.terminate()
    try:
      process.wait(timeout=2)
    except subprocess.TimeoutExpired:
      if lease is not None and _matches(lease):
        os.kill(lease["pid"], signal.SIGKILL)
        process.wait(timeout=2)
      elif lease is None and process.poll() is None:
        process.kill()
        process.wait(timeout=2)
  except (OSError, ChildProcessError, AttributeError, subprocess.TimeoutExpired):
    pass
  if lease is None:
    return
  try:
    exited = process.poll() is not None
  except (OSError, AttributeError):
    exited = _process_identity(lease["pid"]) is None
  if exited:
    try:
      _lease_path(machine).unlink(missing_ok=True)
    except OSError:
      pass
    if state_effect_committed and state_before_effect is not None:
      try:
        write_json(state_file(machine), state_before_effect)
      except (OSError, TermcfgError):
        pass


def _start_locked(machine: MachineSelection, *, timeout: float, progress: Progress) -> dict:
  operation_deadline = time.monotonic() + timeout
  existing = _read_lease(machine)
  if existing is not None:
    if _matches(existing) and existing["state"] == "running":
      secret = MihomoPrivateRuntime(machine).secret()
      _wait_for_health(secret, timeout=max(0, min(5, operation_deadline - time.monotonic())), progress=progress)
      return {"service": "running", "idempotent": True, "pid": existing["pid"]}
    raise TermcfgError(4, "service_lease_conflict", "./termcfg service status")
  if not _port_available():
    raise TermcfgError(4, "external_controller_busy", "./termcfg service status")
  binary = installed_core(machine)
  asset, _ = core_asset()
  state = read_state(machine)
  if state["selected_core"] != asset["sha256"]:
    raise TermcfgError(5, "core_not_selected", "./termcfg sync --component mihomo")
  config, secret = MihomoPrivateRuntime(machine).prepare()
  if time.monotonic() >= operation_deadline:
    raise TermcfgError(5, "service_start_timeout", "./termcfg service status")
  progress.stage("start-or-signal", component="mihomo")
  log_path = _runtime_dir(machine) / "core.log"
  log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0), 0o600)
  try:
    os.fchmod(log_fd, 0o600)
    try:
      process = subprocess.Popen([str(binary), "-d", str(_runtime_dir(machine)), "-f", str(config)],
                                 stdin=subprocess.DEVNULL, stdout=log_fd, stderr=subprocess.STDOUT,
                                 close_fds=True, start_new_session=True,
                                 env={"HOME": str(machine.target_home), "PATH": "/usr/bin:/bin"})
    except OSError as exc:
      raise TermcfgError(5, "service_start_failed", "./termcfg service status") from exc
  finally:
    os.close(log_fd)
  lease = None
  state_before_effect = None
  state_effect_committed = False
  try:
    observed = None
    deadline = min(operation_deadline, time.monotonic() + 5)
    while time.monotonic() < deadline:
      observed = _process_identity(process.pid)
      if observed:
        break
      if process.poll() is not None:
        break
      time.sleep(0.05)
    if observed is None or observed["uid"] != os.getuid() or observed["executable"] != str(binary):
      raise TermcfgError(5, "started_process_unverified", "./termcfg service status")
    lease = {"version": 1, **observed, "core_sha256": asset["sha256"],
             "public_config_identity": state["public_config_identity"],
             "controller": "127.0.0.1:9090", "state": "starting"}
    write_json(_lease_path(machine), lease)
    state_before_effect = read_state(machine)
    _wait_for_health(secret, timeout=max(0, operation_deadline - time.monotonic()), progress=progress)
    if not _matches(lease):
      raise TermcfgError(4, "process_identity_conflict")
    state = read_state(machine)
    state["pending_core_effect"] = False
    if _public_loaded(secret):
      state["pending_config_effect"] = False
      effective = "effective"
    else:
      effective = "unverified"
    write_json(state_file(machine), state)
    state_effect_committed = True
    lease["state"] = "running"
    write_json(_lease_path(machine), lease)
  except BaseException:
    if lease is not None:
      lease["state"] = "failed"
      try:
        write_json(_lease_path(machine), lease)
      except (OSError, TermcfgError):
        pass
    _cleanup_failed_start(machine, process, lease, state_before_effect, state_effect_committed)
    raise
  return {"service": "running", "effective": effective, "pid": process.pid,
          "pending_core_effect": state["pending_core_effect"],
          "pending_config_effect": state["pending_config_effect"]}


def _stop_locked(machine: MachineSelection, *, timeout: float, progress: Progress) -> dict:
  lease = _read_lease(machine)
  if lease is None:
    return {"service": "stopped", "idempotent": True}
  if not _matches(lease):
    raise TermcfgError(4, "process_identity_conflict", "./termcfg service status")
  if timeout <= 0:
    raise TermcfgError(5, "service_stop_timeout", "./termcfg service status")
  progress.stage("start-or-signal", component="mihomo")
  os.kill(lease["pid"], signal.SIGTERM)
  end = time.monotonic() + timeout
  with heartbeat(progress, "health", component="mihomo"):
    while time.monotonic() < end:
      if _process_identity(lease["pid"]) is None:
        try:
          os.waitpid(lease["pid"], os.WNOHANG)
        except ChildProcessError:
          pass
        _lease_path(machine).unlink()
        return {"service": "stopped"}
      time.sleep(0.25)
  raise TermcfgError(5, "service_stop_timeout", "./termcfg service status")


def service_operation(machine: MachineSelection, action: str, *, timeout: int | None = None) -> dict:
  if action == "status":
    return service_status(machine)
  if action not in {"start", "stop", "reload", "restart"}:
    raise TermcfgError(2, "invalid_service_action")
  limit = timeout or (30 if action in {"start", "restart"} else 15)
  operation_deadline = time.monotonic() + limit
  progress = Progress("service " + action)
  with operation_lease(machine.machine_id):
    require_current_machine(machine)
    require_no_pending_recovery(machine)
    progress.stage("check", component="mihomo")
    if action == "start":
      return _start_locked(machine, timeout=max(0, operation_deadline - time.monotonic()), progress=progress)
    if action == "stop":
      return _stop_locked(machine, timeout=max(0, operation_deadline - time.monotonic()), progress=progress)
    if action == "restart":
      _stop_locked(machine, timeout=max(0, operation_deadline - time.monotonic()), progress=progress)
      remaining = operation_deadline - time.monotonic()
      if remaining <= 0:
        raise TermcfgError(5, "service_restart_timeout", "./termcfg service status")
      return _start_locked(machine, timeout=remaining, progress=progress)
    lease = _read_lease(machine)
    if lease is None or not _matches(lease):
      raise TermcfgError(4, "process_identity_conflict", "./termcfg service status")
    config, secret = MihomoPrivateRuntime(machine).prepare()
    remaining = operation_deadline - time.monotonic()
    if remaining <= 0:
      raise TermcfgError(5, "service_reload_timeout", "./termcfg service status")
    progress.stage("start-or-signal", component="mihomo")
    status, _ = _api("PUT", "/configs?force=true", secret, payload={"path": str(config), "payload": ""},
                     timeout=min(2, remaining))
    if status != 204:
      raise TermcfgError(5, "service_reload_failed", "./termcfg service status")
    progress.stage("health", component="mihomo")
    _wait_for_health(secret, timeout=max(0, operation_deadline - time.monotonic()), progress=progress)
    if not _matches(lease):
      raise TermcfgError(4, "process_identity_conflict")
    state = read_state(machine)
    effective = "effective" if _public_loaded(secret) else "unverified"
    if effective == "effective":
      state["pending_config_effect"] = False
      write_json(state_file(machine), state)
    return {"service": "running", "effective": effective,
            "pending_core_effect": state["pending_core_effect"],
            "pending_config_effect": state["pending_config_effect"]}
