"""固定的独立合成 worker；只测试自有 Git lease，不联网或派生进程。"""
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import ssl  # 在替换 socket 前定义标准库类。
import subprocess
import sys
import time


SCENARIOS = ("reserve", "hold-lock", "exit-before-commit", "exit-after-reserved")
ENV_KEYS = {"HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMPDIR", "PATH", "LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE"}


def fail():
  raise ValueError("invalid synthetic worker input")


def inputs():
  if len(sys.argv) != 3 or sys.argv[2] not in SCENARIOS: fail()
  case = Path(sys.argv[1])
  if not case.is_absolute() or case.is_symlink() or not case.is_dir() or case.resolve() != case: fail()
  document = case / "case.json"
  if document.is_symlink() or not document.is_file() or document.stat().st_nlink != 1: fail()
  config = json.loads(document.read_bytes())
  if not isinstance(config, dict) or set(config) != {"role", "workspace"} or config["role"] not in ("one", "two", "holder", "probe") or config["role"] != case.name: fail()
  workspace = Path(config["workspace"])
  if not workspace.is_absolute() or not workspace.resolve(strict=True).is_relative_to(case.parent): fail()
  canonical = workspace.resolve(strict=True)
  while not (canonical / ".git").exists():
    if canonical == case.parent: fail()
    canonical = canonical.parent
  marker = canonical / ".git"
  if marker.is_symlink(): fail()
  git_dir = marker
  if marker.is_file():
    if marker.stat().st_nlink != 1: fail()
    text = marker.read_text()
    if not text.startswith("gitdir: ") or text.count("\n") != 1: fail()
    git_dir = (canonical / text[8:].strip()).resolve(strict=True)
    if not git_dir.is_relative_to(case.parent): fail()
    if (git_dir / "gitdir").is_symlink() or (git_dir / "commondir").is_symlink(): fail()
    if (git_dir / (git_dir / "gitdir").read_text().strip()).resolve(strict=True) != marker: fail()
    if not (git_dir / (git_dir / "commondir").read_text().strip()).resolve(strict=True).is_relative_to(case.parent): fail()
  if not git_dir.is_dir() or (git_dir / "HEAD").is_symlink() or (git_dir / "HEAD").read_bytes() != b"ref: refs/heads/fixture\n": fail()
  account_home = case.parent / "os-account"
  if account_home.is_symlink() or not account_home.is_dir() or account_home.resolve() != account_home or account_home.stat().st_uid != os.geteuid() or account_home.stat().st_mode & 0o777 != 0o700: fail()
  if set(os.environ) != ENV_KEYS or Path.cwd() != case: fail()
  for key in ENV_KEYS - {"LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE"}:
    value = Path(os.environ[key])
    if value.is_symlink() or not value.is_dir() or value.parent != case or value.resolve() != value: fail()
  for name in ("ready", "go", "stop", "exit", "active.json", "result.json", "persisted"):
    if (case / name).is_symlink(): fail()
  return case, workspace, config["role"], sys.argv[2]


def deny(*args, **kwargs):
  raise RuntimeError("synthetic worker external operation disabled")


def install_guards(account_home):
  for name in ("socket", "SocketType", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo", "socketpair", "fromfd"):
    if hasattr(socket, name): setattr(socket, name, deny)
  subprocess.Popen = deny
  for name in ("system", "fork", "forkpty", "posix_spawn", "posix_spawnp", "kill", "killpg", "pidfd_open", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe"):
    if hasattr(os, name): setattr(os, name, deny)
  if hasattr(signal, "pidfd_send_signal"): signal.pidfd_send_signal = deny
  # 账号锚与profile HOME独立；两个worker共享同一个临时OS账户。
  account = pwd.struct_passwd(("synthetic-worker", "x", os.geteuid(), os.getegid(), "", str(account_home), ""))
  pwd.getpwuid = lambda _: account
  pwd.getpwnam = lambda _: account


def main():
  case, workspace, role, scenario = inputs()
  os.umask(0o077); sys.dont_write_bytecode = True
  account_home = case.parent / "os-account"
  install_guards(account_home)
  # -I 不消费 PYTHONPATH；只加入固定仓库的自有源码目录。
  sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
  from agentcfg.workspace_leases import WorkspaceLeases
  from agentcfg.storage import Conflict, Tree
  manager = WorkspaceLeases("synthetic-os-boot", account_home=account_home)
  try:
    planned = manager.identify(workspace)
  except Conflict as error:
    if "WORKSPACE_BUSY" not in str(error): raise
    planned = None  # 账户维护锁也可在只读身份查询阶段明确阻止准入。
  if planned is not None and not Path(planned["worktree_path"]).is_relative_to(case.parent): fail()
  lease = {"instance_id": "profile-" + role, "lease_id": "execution-" + role, "allocation_id": "execution-" + role,
    "task_id": None, "attempt_id": "attempt-" + role, "owner_nonce": "nonce-" + role, "supervisor_activation_id": "supervisor-" + role,
      "grant_generation": 1, "planned_workspaces": [planned] if planned else [], "state": "allocating", "spawn_committed": False}
  # 自身有硬截止，parent 即使异常也不留下常驻进程。
  signal.signal(signal.SIGALRM, lambda *_: os._exit(124)); signal.alarm(9)
  deadline = time.monotonic() + 8

  def wait(name):
    while time.monotonic() < deadline:
      if (case / "stop").exists(): return False
      if (case / name).exists(): return True
      time.sleep(0.01)
    os._exit(124)

  def write_json(name, value):
    temporary = case / (name + ".tmp")
    with temporary.open("x") as file:
      file.write(json.dumps(value)); file.flush(); os.fsync(file.fileno())
    temporary.replace(case / name)

  def active():
    write_json("active.json", {"pid": os.getpid(), "workspace_key": planned["workspace_key"]})

  def reply(outcome):
    # 输出限定在非秘密测试身份；不记录完整环境或帐号资料。
    guards = {}
    for name, operation in (("network", socket.socket), ("process", lambda: subprocess.Popen(["forbidden"])), ("fork", os.fork)):
      try: operation()
      except RuntimeError: guards[name] = True
      else: guards[name] = False
    write_json("result.json", {"outcome": outcome, "workspace_key": planned["workspace_key"] if planned else None, "home": os.environ["HOME"],
      "admission_phase": "reserve" if planned else "identify",
      "env_keys": sorted(os.environ), "guards": guards})

  (case / "ready").touch()
  if not wait("go"): return
  if planned is None:
    reply("busy")
    return
  if scenario in ("hold-lock", "exit-before-commit"):
    with manager.maintenance(workspace):
      active()
      if scenario == "exit-before-commit":
        if wait("exit"): os._exit(71)
      else:
        wait("stop")
    return
  if scenario == "exit-after-reserved":
    original = Tree.write_state
    def persist_then_exit(tree, name, value):
      original(tree, name, value)
      if name == "write-lease.json":
        (case / "persisted").touch()
        os._exit(72)  # 已持久预留，尚未返回 reserve 的回执。
    Tree.write_state = persist_then_exit
  try:
    manager.reserve(planned, lease)
  except Conflict:
    reply("busy")
    return
  active(); reply("reserved")
  wait("stop")


if __name__ == "__main__":
  try:
    main()
  except Exception:
    print("synthetic lease worker failed", file=sys.stderr)
    sys.exit(2)
