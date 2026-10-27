#!/usr/bin/env python3
"""显式授权的 OMP 官方宿主 CLI 维护验收；默认 pytest 不收集。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time


REPOSITORY = Path(__file__).resolve().parents[2]
SESSION = "12345678-1234-4234-8234-123456789abc"
MARKER = "ROTOM_SYNTHETIC_HISTORY_20261027"


def save(path, value):
  path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
  path.chmod(0o600)


def inside(diagnose=False):
  sys.path.insert(0, str(REPOSITORY / "src"))
  from agentcfg import deployment, run_owners
  from agentcfg.omp_identity import native_identity
  from agentcfg.storage import Tree
  from agentcfg.workspace import load_workspace
  root = Path("/probe")
  for name in ("home", "project", "tmp", "logs"):
    (root / name).mkdir(mode=0o700)
  (root / "cache").chmod(0o700)
  os.environ.clear()
  os.environ.update(HOME=str(root / "home"), PATH="/opt/node/bin:/usr/bin:/bin", TERM="xterm-256color",
    LANG="C.UTF-8", TMPDIR=str(root / "tmp"), PYTHONDONTWRITEBYTECODE="1")
  if diagnose:
    os.environ["ROTOM_NATIVE_DIAGNOSTIC"] = "1"
  entry = root / "entry.py"
  entry.write_text('''import json, os, sys
sys.path.insert(0, "/workspace/src")
if os.environ.get("ROTOM_NATIVE_DIAGNOSTIC") == "1":
  def trace(frame, event, arg):
    filename = frame.f_code.co_filename
    if filename.startswith("/workspace/src/agentcfg/") and filename.rsplit("/", 1)[-1] in (
        "resource_owners.py", "resource_coordination.py", "omp_lifecycle.py", "run_owners.py", "descendants.py"):
      if event == "exception":
        with open("/probe/diagnostic.jsonl", "a") as output:
          output.write(json.dumps({"pid": os.getpid(), "file": filename, "line": frame.f_lineno,
            "function": frame.f_code.co_name, "exception": arg[0].__name__}) + "\\n")
      return trace
    return None
  sys.settrace(trace)
from rotom.cli import main
raise SystemExit(main())
''')
  entry.chmod(0o600)
  machine = root / "machine.toml"
  def configure(updated=False):
    machine.write_text('schema_version=1\n[machine]\nid="native-workflow-fixture"\ndefault_profile="omp-default"\n'
      '[machine.paths]\ninstances_root="/probe/instances"\nstate_root="/probe/states"\ncache_root="/probe/cache"\n'
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nauth_kind="api-key"\n'
      'credential_ref="secret:fixture"\nbase_url="http://127.0.0.1:9/v1"\n'
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text","image"]\n'
      'context_window=32768\nmax_output_tokens=4096\n'
      '[overrides.profiles.omp-default]\nproviders=["fixture"]\nmodels=["fixture"]\nmcp=[]\n'
      '[overrides.profiles.omp-default.roles]\n' + ''.join(name+'="fixture"\n' for name in
      ("main", "smol", "slow", "plan", "task", "advisor", "vision")) +
      '[overrides.profiles.omp-default.agent_options.ui]\ntheme_dark="' +
      ("light-catppuccin" if updated else "dark-catppuccin") + '"\n'
      '[secrets]\nfixture="synthetic-not-a-secret"\n')
    machine.chmod(0o600)
  configure()
  ws = load_workspace(machine, profile="omp-default")
  lock = ws.backend.read_lock(REPOSITORY)
  asset = lock.metadata["assets"]["linux-x64"]
  binary = Path("/opt/omp")
  assert hashlib.sha256(binary.read_bytes()).hexdigest() == asset["sha256"]
  downloads = ws.cache / "downloads"
  downloads.mkdir(mode=0o700, parents=True)
  # 正常 backend 从精确摘要的缓存资产安装、生成自己的收据，不伪造运行包。
  shutil.copyfile(binary, downloads / asset["sha256"])
  (downloads / asset["sha256"]).chmod(0o600)
  prefix = ["--no-input", "agent", "--local", str(machine), "--profile", ws.profile]
  calls = []
  def command(label, tokens, expected=(0,)):
    argv = [sys.executable, "-B", str(entry), *tokens]
    result = subprocess.run(argv, cwd=root / "project", capture_output=True, timeout=90)
    (root / "logs" / (label + ".stdout")).write_bytes(result.stdout)
    (root / "logs" / (label + ".stderr")).write_bytes(result.stderr)
    calls.append({"label": label, "argv": argv, "exit_code": result.returncode})
    save(root / "calls.json", calls)
    if result.returncode not in expected:
      raise RuntimeError(label + ":exit=" + str(result.returncode))
    try:
      return json.loads(result.stdout)
    except ValueError:
      return result.stdout.decode(errors="replace")
  command("initial-setup", [*prefix, "setup"])
  assert ws.backend.status(ws, ws.backend.runtime_identity(ws, lock)) == "installed"
  with Tree(ws.state_root) as tree:
    original = deployment.read_state(tree)["current"]
  sessions = native_identity(ws.profile, ws.instance).agent_dir / "sessions" / "fixture-project"
  sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
  target = sessions / ("2026-10-27T00-00-00_" + SESSION + ".jsonl")
  target.write_text(json.dumps({"type": "session", "version": 3, "id": SESSION,
    "cwd": str(root / "project"), "timestamp": "2026-10-27T00:00:00.000Z"}) + "\n" +
    json.dumps({"type": "message", "id": "fixture-entry", "parentId": None,
      "timestamp": "2026-10-27T00:00:01.000Z", "message": {"role": "user", "content": [
        {"type": "text", "text": MARKER}], "timestamp": 1793059201000}}) + "\n")
  target.chmod(0o600)
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  children = []
  cleanup = []
  def launch(label, tokens):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
    before = termios.tcgetattr(slave)
    argv = [sys.executable, "-B", str(entry), *tokens]
    child = subprocess.Popen(argv, cwd=root / "project", stdin=slave, stdout=slave, stderr=slave,
      start_new_session=True)
    item = {"child": child, "master": master, "slave": slave, "before": before,
      "output": bytearray(), "label": label, "argv": argv, "host_fd": None}
    children.append(item)
    def drain():
      while child.poll() is None:
        if select.select([master], [], [], 0.1)[0]:
          try:
            item["output"].extend(os.read(master, 65536))
          except OSError:
            break
    item["reader"] = threading.Thread(target=drain, daemon=True)
    item["reader"].start()
    end = time.monotonic() + 40
    while time.monotonic() < end and child.poll() is None:
      time.sleep(0.1)
      # 仅探针读取自己的原子 JSON；启动登记期间不争 owner NB 锁。
      records = [json.loads(path.read_text()) for path in registry.root.glob("*.json")]
      found = [row for row in records if row["manager_identity"]["pid"] == child.pid
        and row["lifecycle_state"] == "active" and row["host_identity"] is not None]
      if len(found) == 1:
        item["record"] = found[0]
        if item["host_fd"] is None:
          item["host_fd"] = os.pidfd_open(found[0]["host_identity"]["identity"]["pid"])
        if (MARKER.encode() in item["output"] and not termios.tcgetattr(slave)[3] & termios.ICANON
            and (ws.state_root / "stop-inboxes" / found[0]["run_id"] / "endpoint.json").exists()):
          from agentcfg.dsh_stop_control import available
          if available(ws, found[0]):
            return item
    (root / "logs" / (label + ".failed-terminal")).write_bytes(item["output"])
    save(root / "logs" / (label + ".failed-ready.json"), {"exit_code": child.poll(),
      "record_seen": "record" in item, "marker_visible": MARKER.encode() in item["output"],
      "raw_mode": not bool(termios.tcgetattr(slave)[3] & termios.ICANON)})
    raise RuntimeError(label + ":native-ready-unconfirmed")
  def finish(item):
    child = item["child"]
    child.wait(timeout=20)
    item["reader"].join(timeout=2)
    assert child.poll() is not None, "manager-exit-unconfirmed"
    assert termios.tcgetattr(item["slave"]) == item["before"], "terminal-not-restored"
    (root / "logs" / (item["label"] + ".terminal")).write_bytes(item["output"])
    calls.append({"label": item["label"], "argv": item["argv"], "exit_code": child.returncode,
      "termios_restored": True, "history_visible": MARKER.encode() in item["output"], "input_bytes": 0})
    save(root / "calls.json", calls)
  try:
    first = launch("initial-resume", ["--no-input", "resume", "omp", "--local", str(machine),
      "--profile", ws.profile, "--session", SESSION, "--here"])
    run = first["record"]["run_id"]
    configure(True)
    planned = command("maintenance-plan", [*prefix, "maintenance", "plan", "--run", run,
      "--session", run + "=" + SESSION, "--label", run + "=Synthetic workflow", "--format", "json"])
    assert planned["readiness"] == "ready" and planned["setup"]["summary"]["changes"] > 0
    stopped = command("maintenance-stop", [*prefix, "maintenance", "stop", "--run", run,
      "--session", run + "=" + SESSION, "--label", run + "=Synthetic workflow",
      "--plan-id", planned["plan_id"], "--wait-seconds", "30", "--format", "json"])
    batch = stopped["batch_id"]
    assert stopped["stop_status"] == "stopped"
    finish(first)
    assert registry.snapshot()[run]["lifecycle_state"] == "idle_confirmed"
    preview = command("setup-plan", [*prefix, "maintenance", "plan", "--batch", batch, "--format", "json"])
    updated = command("execute", [*prefix, "maintenance", "execute", "--batch", batch,
      "--plan-id", preview["setup_preview"]["plan_id"], "--format", "json"])
    assert updated["status"] == "updated"
    with Tree(ws.state_root) as tree:
      current = deployment.read_state(tree)["current"]
    assert current != original
    listed = command("stopped-list", ["--no-input", "resume", "omp", "--local", str(machine),
      "--profile", ws.profile, "--stopped", "--list", "--format", "json"])
    rows = [row for row in listed["sessions"] if row["batch_id"] == batch and row["run_id"] == run]
    assert len(rows) == 1 and rows[0]["restorable"] and rows[0]["session_id"] == SESSION
    restored = launch("stopped-resume", ["--no-input", "resume", "omp", "--local", str(machine),
      "--profile", ws.profile, "--stopped", "--batch", batch, "--run", run, "--here"])
    next_run = restored["record"]["run_id"]
    assert next_run != run
    assert Path("/proc/" + str(restored["record"]["host_identity"]["identity"]["pid"]) + "/cwd").resolve() == root / "project"
    stopping = command("resumed-stop-plan", [*prefix, "instances", "stop", "--run", next_run, "--dry-run"])
    command("resumed-stop", [*prefix, "instances", "stop", "--run", next_run,
      "--plan-id", stopping["plan_id"], "--wait-seconds", "30"])
    finish(restored)
    status = command("final-status", [*prefix, "maintenance", "status", "--batch", batch, "--format", "json"])
    assert status["continue_status"] == "not_sent" and status["load_confirmation"] == "unknown"
    command("repeat-rejected", ["--no-input", "resume", "omp", "--local", str(machine), "--profile", ws.profile,
      "--stopped", "--batch", batch, "--run", run, "--here"], expected=(4,))
    assert all(row["lifecycle_state"] == "idle_confirmed" for row in registry.snapshot().values())
    result = {"success": True, "lock_identity": lock.identity, "batch_id": batch, "old_run": run,
      "new_run": next_run, "session_id": SESSION, "cwd": str(root / "project"), "input_bytes": 0,
      "load_confirmation": "unknown", "continue_status": "not_sent", "calls": calls}
    save(root / "result.json", result)
    print(json.dumps({"success": True, "calls": len(calls), "load_confirmation": "unknown", "input_bytes": 0}), flush=True)
    return 0
  finally:
    for item in children:
      if item["child"].poll() is None and item["host_fd"] is not None:
        # 仅清理本脚本刚创建且已持有原 pidfd 的合成宿主；本次验收不能记为通过。
        signal.pidfd_send_signal(item["host_fd"], signal.SIGTERM)
        cleanup.append(item["label"])
        try:
          item["child"].wait(timeout=15)
        except subprocess.TimeoutExpired:
          save(root / "cleanup-unconfirmed.json", {"active": item["label"], "pid": item["child"].pid})
      if item["host_fd"] is not None:
        os.close(item["host_fd"])
      item["reader"].join(timeout=2)
      (root / "logs" / (item["label"] + ".terminal")).write_bytes(item["output"])
      for fd in (item["master"], item["slave"]):
        os.close(fd)
    if cleanup:
      save(root / "cleanup.json", {"native_case_failed": True, "original_pidfd_sigterm": cleanup})


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
  parser.add_argument("--diagnose", action="store_true", help="仅记录仓库自有退出记账异常；诊断不能替代无追踪验收")
  parser.add_argument("--root", type=Path)
  parser.add_argument("--binary", type=Path)
  parser.add_argument("--node-root", type=Path)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要显式 --allow-host 与已授权隔离宿主/单次停止验收")
  os.umask(0o077)
  if args.inside:
    return inside(args.diagnose)
  if args.root is None or args.binary is None or args.node_root is None or args.root.exists():
    parser.error("需要不存在的私人 --root、官方 --binary 和 --node-root")
  args.root.mkdir(mode=0o700)
  argv = ["/bin/bwrap", "--unshare-user", "--unshare-pid", "--unshare-net", "--die-with-parent", "--new-session", "--tmpfs", "/",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
    "--symlink", "usr/bin", "/bin", "--proc", "/proc", "--dev", "/dev", "--dir", "/tmp",
    "--ro-bind", str(REPOSITORY), "/workspace", "--ro-bind", str(REPOSITORY / ".venv"), "/venv",
    "--ro-bind", str(args.node_root), "/opt/node", "--ro-bind", str(args.binary), "/opt/omp",
    "--bind", str(args.root), "/probe", "--tmpfs", "/probe/cache", "--chdir", "/workspace", "/venv/bin/python", "-B",
    "/workspace/tests/manual/omp_tool_workflow_native.py", "--allow-host", "--inside"]
  if args.diagnose:
    argv.append("--diagnose")
  save(args.root / "invocation.json", {"argv": argv})
  with (args.root / "driver.stdout").open("wb") as stdout, (args.root / "driver.stderr").open("wb") as stderr:
    result = subprocess.run(argv, env={"PATH": "/usr/bin:/bin"}, stdout=stdout, stderr=stderr)
  print(json.dumps({"exit_code": result.returncode, "evidence": str(args.root)}))
  return result.returncode


if __name__ == "__main__":
  raise SystemExit(main())
