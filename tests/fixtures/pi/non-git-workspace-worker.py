"""固定非Git合成worker与纯启动协议；真实文件系统隔离由bwrap提供。"""
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = ("register", "reserve", "reserve-race", "exit-before-reserve", "exit-after-reserve")
ENV_NAMES = {"HOME", "PWD", "PATH", "TMPDIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE"}


def closed_case(case, parent, scenario):
  case, parent = Path(case), Path(parent)
  if scenario not in SCENARIOS or not case.is_absolute() or case.parent != parent or case.is_symlink() or not case.is_dir() or case.resolve() != case:
    raise ValueError("fixed non-Git worker input required")
  file = case / "case.json"
  if file.is_symlink() or not file.is_file() or file.stat().st_nlink != 1: raise ValueError("regular case required")
  data = json.loads(file.read_bytes())
  if not isinstance(data, dict) or set(data) != {"workspace", "register"} or not isinstance(data["register"], list): raise ValueError("closed case required")
  for value in [data["workspace"], *data["register"]]:
    if not isinstance(value, str) or any(ord(char) < 32 for char in value): raise ValueError("local workspace required")
    path = Path(value)
    if not path.is_absolute() or not path.resolve(strict=True).is_relative_to(parent) or not path.is_dir(): raise ValueError("local workspace required")
  account = parent / "os-account"
  if account.is_symlink() or not account.is_dir() or account.resolve() != account or account.stat().st_uid != os.geteuid() or account.stat().st_mode & 0o777 != 0o700:
    raise ValueError("private shared account required")
  for name in ("ready", "go", "stop", "exit", "active.json", "result.json", "persisted"):
    if (case / name).is_symlink(): raise ValueError("local controls required")
  gate = parent / "race-go"
  if gate.is_symlink() or (gate.exists() and (not gate.is_file() or gate.stat().st_nlink != 1 or gate.stat().st_uid != os.geteuid())):
    raise ValueError("local shared barrier required")
  return data


def invocation(case, parent, scenario, python):
  closed_case(case, parent, scenario)
  case, parent, python = Path(case), Path(parent), Path(python)
  if not python.is_absolute() or python.name != "python" or python.parent.name != "bin" or not python.is_file(): raise ValueError("prepared interpreter required")
  venv = python.parent.parent
  env = {"LC_ALL": "C.UTF-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PWD": str(case)}
  for key, name in (("HOME", "home"), ("PATH", "empty-bin"), ("TMPDIR", "tmp"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
    env[key] = str(case / name)
  command = ["/bin/bwrap", "--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL"]
  # venv解释器可指向/bin/python；/bin和/usr/bin均按原系统只读挂载。
  for source in (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64")):
    command += ["--ro-bind", str(source), str(source)]
  command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
  for source in (ROOT / "src", ROOT / "agents/pi/schemas", ROOT / "schemas", Path(__file__).resolve(), venv):
    command += ["--ro-bind", str(source), str(source)]
  command += ["--bind", str(parent), str(parent)]
  for key, value in env.items(): command += ["--setenv", key, value]
  command += ["--chdir", str(case), str(python), "-I", str(Path(__file__).resolve()), str(case), scenario]
  return command


def deny(*args, **kwargs):
  raise RuntimeError("synthetic external operation disabled")


def main():
  if len(sys.argv) != 3: raise ValueError("fixed arguments required")
  case = Path(sys.argv[1]); scenario = sys.argv[2]
  data = closed_case(case, case.parent, scenario)
  if set(os.environ) != ENV_NAMES or Path.cwd() != case: raise ValueError("closed environment required")
  if os.path.lexists("/tmp/.git"): raise ValueError("private tmp required")
  for key in ENV_NAMES - {"LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE", "PWD"}:
    if Path(os.environ[key]).parent != case: raise ValueError("private environment required")
  os.umask(0o077); sys.dont_write_bytecode = True
  for key in ENV_NAMES - {"LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE", "PWD"}: Path(os.environ[key]).mkdir(exist_ok=True)
  for name in ("socket", "create_connection", "getaddrinfo", "socketpair", "fromfd"): setattr(socket, name, deny)
  subprocess.Popen = deny
  for name in ("fork", "forkpty", "system", "posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execvpe", "kill", "killpg"):
    if hasattr(os, name): setattr(os, name, deny)
  signal.signal(signal.SIGALRM, lambda *_: os._exit(124)); signal.alarm(9)
  sys.path.insert(0, str(ROOT / "src"))
  from agentcfg.pi_registered_roots import RegisteredRoots
  from agentcfg.workspace_leases import WorkspaceLeases
  from agentcfg.storage import Conflict
  account = case.parent / "os-account"
  manager = WorkspaceLeases("synthetic-non-git-boot", account_home=account)
  deadline = time.monotonic() + 8

  def wait(name):
    while time.monotonic() < deadline:
      if (case / name).exists(): return True
      if (case / "stop").exists(): return False
      time.sleep(0.01)
    os._exit(124)

  def write(name, value):
    temporary = case / (name + ".tmp")
    with temporary.open("x") as file:
      file.write(json.dumps(value)); file.flush(); os.fsync(file.fileno())
    temporary.replace(case / name)

  def result(outcome, planned=None):
    guards = {}
    for name, operation in (("network", socket.socket), ("process", lambda: subprocess.Popen(["forbidden"])), ("fork", os.fork)):
      try: operation()
      except RuntimeError: guards[name] = True
      else: guards[name] = False
    write("result.json", {"outcome": outcome, "planned": planned, "home": os.environ["HOME"], "guards": guards, "private_tmp": not os.path.lexists("/tmp/.git")})

  if scenario != "reserve-race":
    (case / "ready").touch()
    if not wait("go"): return
  if scenario == "register":
    registry = RegisteredRoots(account_home=account)
    for root in data["register"]: registry.register(root)
    result("registered"); return
  try:
    planned = manager.identify(data["workspace"])
    if planned.get("workspace_kind") != "registered-root": raise ValueError("non-Git identity required")
    lease = {"instance_id": "profile-" + case.name, "lease_id": "execution-" + case.name, "allocation_id": "execution-" + case.name,
      "task_id": None, "attempt_id": "attempt-" + case.name, "owner_nonce": "nonce-" + case.name,
      "supervisor_activation_id": "supervisor-" + case.name, "grant_generation": 1, "planned_workspaces": [planned], "state": "allocating", "spawn_committed": False}
    if scenario == "exit-before-reserve":
      with manager.maintenance(data["workspace"]):
        write("active.json", {"workspace_key": planned["workspace_key"]})
        if wait("exit"): os._exit(71)
      return
    if scenario == "reserve-race":
      write("ready", {"planned": planned})
      if not wait(case.parent / "race-go"): return
    manager.reserve(planned, lease)
    if scenario == "exit-after-reserve":
      (case / "persisted").touch(); os._exit(72)
  except Conflict:
    result("denied"); return
  write("active.json", {"workspace_key": planned["workspace_key"]})
  result("reserved", planned)
  wait("stop")


if __name__ == "__main__":
  try: main()
  except Exception:
    print("synthetic non-Git worker failed", file=sys.stderr)
    sys.exit(2)
