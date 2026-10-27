"""显式授权的 Pi 官方 TUI/公开 Rotom CLI 维护链路；默认 pytest 不收集。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import sys
import termios
import threading
import time


REPO = Path(__file__).resolve().parents[2]
SID = "12345678-1234-4234-8234-123456789abc"
ROOT = Path("/probe")
CLI = [sys.executable, "-c", "from rotom.cli import main; raise SystemExit(main())"]


def save(name, value):
  (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def wait_for(check, description):
  deadline = time.monotonic() + 30
  while time.monotonic() < deadline:
    value = check()
    if value:
      return value
    time.sleep(0.05)
  raise RuntimeError("timeout: " + description)


def inside(prepare):
  sys.path.insert(0, str(REPO / "src"))
  from agentcfg import commands, run_owners, pi_session_guard
  from agentcfg.workspace import load_workspace
  os.umask(0o077)
  os.environ.clear()
  os.environ.update(PATH="/opt/node/bin:/usr/bin:/bin", HOME="/probe/home",
    XDG_CONFIG_HOME="/probe/config", XDG_DATA_HOME="/probe/data", XDG_STATE_HOME="/probe/state",
    XDG_CACHE_HOME="/probe/cache", TMPDIR="/probe/tmp", TERM="xterm-256color",
    LANG="C.UTF-8", PYTHONPATH=str(REPO / "src"), PYTHONDONTWRITEBYTECODE="1")
  for name in ("home", "config", "data", "state", "cache", "tmp", "project"):
    (ROOT / name).mkdir(mode=0o700, exist_ok=True)
  local = ROOT / "local.toml"
  if prepare:
    local.write_text('schema_version=1\n[machine]\nid="native-workflow-fixture"\n'
      'default_profile="pi-base"\n[machine.paths]\ninstances_root="/probe/instances"\n'
      'state_root="/probe/managed-state"\ncache_root="/probe/managed-cache"\n'
      '[overrides.providers.fixture]\nprotocol="openai-compatible"\nauth_kind="api-key"\n'
      'credential_ref="secret:fixture"\nbase_url="https://example.invalid/v1"\n'
      '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fictional-chat"\ninput=["text"]\n'
      '[overrides.profiles.pi-base]\nproviders=["fixture"]\nmodels=["fixture"]\n'
      '[overrides.profiles.pi-base.roles]\nmain="fixture"\n'
      '[overrides.profiles.pi-base.agent_options.settings]\ndefaultThinkingLevel="medium"\n'
      '[secrets]\nfixture="SYNTHETIC_NATIVE_FIXTURE"\n')
  ws = load_workspace(local, "pi-base", repository=REPO)
  lock = ws.backend.read_lock(REPO)
  if prepare:
    save("preparation-input.json", {"lock": lock.identity, "source": pi_session_guard.source_identity(),
      "locks": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (REPO / "locks/pi").rglob("*") if p.is_file()}})
    # 完整官方 npm 安装、审核、封存均经正常后端；不制作准入收据。
    if Path("/seed").exists():
      identity = ws.backend.runtime_identity(ws, lock)
      destination = ws.backend.root(ws, identity)
      destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
      shutil.copytree("/seed", destination, symlinks=True)
      assert ws.backend.status(ws, identity) == "installed"
    result = ws.backend.sync(ws, lock)
    commands.apply_candidate(ws, lock, ws.candidate(lock.identity))
    save("preparation-result.json", result)
    return 0
  prefix = ["--no-input", "agent", "--local", str(local), "--profile", "pi-base", "maintenance"]
  evidence = {"commands": [], "source": pi_session_guard.source_identity(), "lock": lock.identity}
  processes = []
  terminals = []
  def call(args, expected=0):
    result = subprocess.run([*CLI, *args], capture_output=True, text=True, timeout=60)
    evidence["commands"].append({"argv": [*CLI, *args], "exit_code": result.returncode,
      "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode == expected, evidence["commands"][-1]
    return json.loads(result.stdout) if result.stdout.strip() else None
  def maintenance(action, *args):
    return call([*prefix, action, *args, "--format", "json"])
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  def records():
    return registry.snapshot()
  def observed(run):
    path = ws.state_root / "pi-session-observations" / (run + ".json")
    if not path.exists():
      return None
    value = json.loads(path.read_text())
    return value if value.get("session_id") == SID else None
  def start(args):
    master, slave = os.openpty()
    import fcntl
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 110, 0, 0))
    before = termios.tcgetattr(slave)
    output = bytearray()
    child = subprocess.Popen([*CLI, *args], stdin=slave, stdout=slave, stderr=slave,
      cwd=ROOT / "project", start_new_session=True)
    processes.append(child)
    def drain():
      while child.poll() is None:
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
          try:
            output.extend(os.read(master, 65536))
          except OSError:
            break
    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    terminals.append((master, slave, before, output, thread))
    evidence["commands"].append({"argv": [*CLI, *args], "pid": child.pid})
    return child
  try:
    sessions = ws.instance / "pi-home/sessions"
    sessions.mkdir(mode=0o700, exist_ok=True)
    target = sessions / ("2026-10-27T00-00-00_" + SID + ".jsonl")
    target.write_text(json.dumps({"type": "session", "version": 3, "id": SID,
      "cwd": "/probe/project", "timestamp": "2026-10-27T00:00:00.000Z"}) + "\n" +
      json.dumps({"type": "message", "id": "abcdef12", "parentId": None,
        "timestamp": "2026-10-27T00:00:01.000Z", "message": {"role": "user",
        "content": [{"type": "text", "text": "SYNTHETIC_HISTORY_NO_CONTINUATION"}],
        "timestamp": 1793059201000}}) + "\n")
    original = target.read_bytes()
    first = start(["--no-input", "run", "pi", "--local", str(local), "--profile", "pi-base",
      "--cwd", "/probe/project", "--", "--session", SID])
    old = wait_for(lambda: next(iter(records()), None), "initial run")
    evidence["initial_observation"] = wait_for(lambda: observed(old), "initial session observation")
    evidence["initial_native_argv"] = (Path("/proc") / str(records()[old]["host_identity"]["identity"]["pid"]) / "cmdline").read_bytes().decode().split("\0")
    assert evidence["initial_observation"]["cwd"] == "/probe/project"
    wait_for(lambda: not (termios.tcgetattr(terminals[0][1])[3] & termios.ICANON), "initial raw terminal")
    local.write_text(local.read_text().replace('defaultThinkingLevel="medium"', 'defaultThinkingLevel="low"'))
    plan = maintenance("plan", "--run", old, "--session", old + "=" + SID, "--label", old + "=Synthetic history")
    stopped = maintenance("stop", "--run", old, "--session", old + "=" + SID,
      "--label", old + "=Synthetic history", "--plan-id", plan["plan_id"])
    evidence["initial_exit"] = first.wait(timeout=30)
    assert target.read_bytes().startswith(original)
    stopped_history = target.read_bytes()
    assert termios.tcgetattr(terminals[0][1]) == terminals[0][2]
    batch = stopped["batch_id"]
    preview = maintenance("plan", "--batch", batch)
    updated = maintenance("execute", "--batch", batch, "--plan-id", preview["setup_preview"]["plan_id"])
    assert updated["status"] == "updated"
    assert json.loads((ws.instance / "pi-home/settings.json").read_text())["defaultThinkingLevel"] == "low"
    assert target.read_bytes() == stopped_history
    listing = call(["--no-input", "resume", "pi", "--local", str(local), "--profile", "pi-base",
      "--stopped", "--list", "--batch", batch, "--run", old, "--format", "json"])
    assert len(listing["sessions"]) == 1
    row = listing["sessions"][0]
    assert row["session_id"] == SID and row["cwd"] == "/probe/project" and row["restorable"]
    restore_args = ["--no-input", "resume", "pi", "--local", str(local), "--profile", "pi-base",
      "--stopped", "--batch", batch, "--run", old, "--here", "--format", "json"]
    restored = start(restore_args)
    new = wait_for(lambda: next((run for run in records() if run != old), None), "restored new run")
    evidence["restored_observation"] = wait_for(lambda: observed(new), "restored exact session")
    assert new != old
    evidence["restored_native_argv"] = (Path("/proc") / str(records()[new]["host_identity"]["identity"]["pid"]) / "cmdline").read_bytes().decode().split("\0")
    assert evidence["restored_observation"]["cwd"] == "/probe/project"
    wait_for(lambda: not (termios.tcgetattr(terminals[1][1])[3] & termios.ICANON), "restored raw terminal")
    stop_args = ["--no-input", "agent", "--local", str(local), "--profile", "pi-base", "instances", "stop", "--run", new]
    stop_preview = call([*stop_args, "--dry-run"])
    call([*stop_args, "--plan-id", stop_preview["plan_id"]])
    evidence["restore_exit"] = restored.wait(timeout=30)
    assert termios.tcgetattr(terminals[1][1]) == terminals[1][2]
    status = maintenance("status", "--batch", batch)
    assert status["load_confirmation"] == "unknown" and status["continue_status"] == "not_sent"
    call(restore_args, expected=4)
    assert set(records()) == {old, new}
    assert all(child.poll() is not None for child in processes)
    evidence["final_records"] = records()
    for record in records().values():
      identity = record["host_identity"]["identity"]
      assert run_owners.observed_process_identity(identity["pid"]) != identity
    evidence.update(success=True, old_run=old, new_run=new, batch=batch, terminal_restored=True,
      history_preserved=True, input_bytes=0, no_active_managers=True)
  except Exception as error:
    import traceback
    evidence.update(success=False, failure=type(error).__name__ + ":" + str(error), traceback=traceback.format_exc())
  finally:
    for child in processes:
      if child.poll() is None:
        child.terminate()
        try:
          child.wait(timeout=10)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait(timeout=10)
    for index, (master, slave, before, output, thread) in enumerate(terminals):
      thread.join(timeout=2)
      (ROOT / f"terminal-{index}.log").write_bytes(output)
      os.close(master)
      os.close(slave)
    save("result.json", evidence)
  print(json.dumps({key: evidence[key] for key in ("success", "failure") if key in evidence}))
  return 0 if evidence.get("success") else 1


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--root", type=Path)
  parser.add_argument("--node-root", type=Path)
  parser.add_argument("--runtime-source", type=Path, help="正常后端生成的完整当前锁运行包；只读复制并复核")
  parser.add_argument("--inside", choices=("prepare", "run"), help=argparse.SUPPRESS)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要明确 --allow-host；会启动和停止隔离的真实 Pi")
  if args.inside:
    return inside(args.inside == "prepare")
  if args.root is None or args.node_root is None or args.root.exists():
    parser.error("需要不存在的 --root 和锁定 --node-root")
  args.root.mkdir(mode=0o700)
  # 新根只暴露系统公开运行库、候选源码、工具链和本次证据目录。
  base = ["bwrap", "--die-with-parent", "--unshare-pid", "--proc", "/proc", "--dev", "/dev",
    "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
    "--symlink", "usr/lib64", "/lib64", "--ro-bind", str(REPO), "/workspace",
    "--ro-bind", str((REPO / ".venv").resolve()), "/venv",
    "--ro-bind", str(args.node_root), "/opt/node", "--bind", str(args.root), "/probe", "--tmpfs", "/tmp",
    "--setenv", "PATH", "/opt/node/bin:/usr/bin:/bin", "--chdir", "/workspace"]
  if args.runtime_source is not None:
    base.extend(["--ro-bind", str(args.runtime_source), "/seed"])
  for phase in ("prepare", "run"):
    network = ["--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf", "--ro-bind", "/etc/ssl", "/etc/ssl"] if phase == "prepare" else ["--unshare-net"]
    argv = [*base, *network, "/venv/bin/python", "/workspace/tests/manual/pi_tool_workflow_native.py",
      "--allow-host", "--inside", phase]
    (args.root / (phase + "-argv.json")).write_text(json.dumps(argv, indent=2) + "\n")
    with (args.root / (phase + ".log")).open("wb") as log:
      result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=600,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    if result.returncode:
      print(json.dumps({"phase": phase, "exit_code": result.returncode, "evidence": str(args.root)}))
      return result.returncode
  print(json.dumps({"success": True, "evidence": str(args.root)}))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
