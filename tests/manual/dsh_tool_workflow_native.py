"""显式禁网隔离的 DSH 公开 CLI 停止、setup 与精确恢复验收。"""
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import threading
import time
import traceback

from pi_tool_workflow_native import REPO, ROOT, CLI, save, wait_for


def inside(trace=False):
  command = CLI
  if trace:
    command = [sys.executable, "-c", "exec(open('/probe/trace_cli.py').read())"]
  sys.path.insert(0, str(REPO / "src"))
  from agentcfg import commands, dependencies, run_owners, runtime_packages
  from agentcfg.storage import Tree, instance_lock
  from agentcfg.workspace import load_workspace
  os.umask(0o077)
  os.environ.clear()
  os.environ.update(PATH="/opt/node/bin:/usr/bin:/bin", HOME="/probe/home", DSH_HOME="/probe/dsh",
    XDG_CONFIG_HOME="/probe/config", XDG_DATA_HOME="/probe/data", XDG_STATE_HOME="/probe/state",
    XDG_CACHE_HOME="/probe/cache", TMPDIR="/probe/tmp", TERM="xterm-256color", COLORTERM="truecolor",
    LANG="C.UTF-8", PYTHONPATH=str(REPO / "src"), PYTHONDONTWRITEBYTECODE="1")
  for name in ("home", "dsh", "config", "data", "state", "cache", "tmp", "project"):
    (ROOT / name).mkdir(mode=0o700)
  module_spec = importlib.util.spec_from_file_location("native_model_fixture", REPO / "scripts/smoke-dsh-concurrency.py")
  fixture_module = importlib.util.module_from_spec(module_spec)
  module_spec.loader.exec_module(fixture_module)
  fixture = {"gate": threading.Lock(), "requests": 0, "responses": set(), "error": None, "request_observations": []}
  server = fixture_module.FixtureServer(("127.0.0.1", 0), fixture_module.handler(fixture, "not-a-real-key"))
  server_thread = threading.Thread(target=server.serve_forever, daemon=True)
  server_thread.start()
  local = ROOT / "local.toml"
  local.write_text('schema_version=1\n[machine]\nid="native-dsh-workflow-fixture"\n'
    'default_profile="dsh-default"\n[machine.paths]\ninstances_root="/probe/instances"\n'
    'state_root="/probe/managed-state"\ncache_root="/probe/managed-cache"\n'
    '[overrides.providers.fixture]\nprotocol="openai-compatible"\nauth_kind="api-key"\n'
    'credential_ref="secret:fixture"\n' + f'base_url="http://127.0.0.1:{server.server_port}/v1"\n' +
    '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
    '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\n'
    '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n'
    '[overrides.profiles.dsh-default.agent_options]\nshow_welcome=false\nterminal_images=false\n'
    '[secrets]\nfixture="not-a-real-key"\n')
  ws = load_workspace(local, "dsh-default", repository=REPO)
  lock = dependencies.read_lock(REPO)
  evidence = {"commands": [], "lock": lock.identity, "uid": os.getuid(), "euid": os.geteuid(),
    "sources": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
      (REPO / "tests/manual/dsh_tool_workflow_native.py", REPO / "tests/manual/pi_tool_workflow_native.py",
       REPO / "src/agentcfg/dsh_stop_control.py", REPO / "src/agentcfg/dsh_stop_scope.py")}, "locks": {
    str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (REPO / "locks/dsh").rglob("*") if p.is_file() and "vendor" not in p.parts}}
  processes, terminals = [], []
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  def records():
    return registry.snapshot()
  def ready_run(exclude=None):
    # 只读原子 owner 文件提示就绪，避免观察者持锁干扰可选控制工厂初始化。
    for path in registry.root.glob("*.json"):
      try:
        row = json.loads(path.read_bytes())
      except (FileNotFoundError, ValueError):
        continue
      if row.get("run_id") != exclude and row.get("protocol", {}).get("control"):
        return row["run_id"]
    return None
  def snapshot():
    with fixture["gate"]:
      return {key: copy.deepcopy(fixture[key]) for key in ("requests", "responses", "error", "request_observations")}
  def call(args, expected=0):
    result = subprocess.run([*command, *args], capture_output=True, text=True, timeout=60)
    evidence["commands"].append({"argv": [*command, *args], "exit_code": result.returncode,
      "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode == expected, evidence["commands"][-1]
    return json.loads(result.stdout) if result.stdout.strip() else None
  prefix = ["--no-input", "agent", "--local", str(local), "--profile", "dsh-default", "maintenance"]
  def maintenance(action, *args):
    return call([*prefix, action, *args, "--format", "json"])
  def start(args):
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
    before = termios.tcgetattr(slave)
    output = bytearray()
    child = subprocess.Popen([*command, *args], stdin=slave, stdout=slave, stderr=slave,
      cwd=ROOT / "project", start_new_session=True)
    processes.append(child)
    def drain():
      while child.poll() is None:
        if select.select([master], [], [], 0.1)[0]:
          try:
            output.extend(os.read(master, 65536))
          except OSError:
            break
    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    terminals.append((master, slave, before, output, thread))
    evidence["commands"].append({"argv": [*command, *args], "pid": child.pid})
    return child
  def text(index):
    value = terminals[index][3].decode(errors="replace")
    return re.sub(r"\s+", "", re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value))
  def host(run):
    record = records()[run]
    identity = record["host_identity"]["identity"]
    evidence.setdefault("native_hosts", {})[run] = {
      "argv": (Path("/proc") / str(identity["pid"]) / "cmdline").read_bytes().decode().split("\0"),
      "cwd": os.readlink(Path("/proc") / str(identity["pid"]) / "cwd"), "identity": identity}
    assert evidence["native_hosts"][run]["cwd"] == "/probe/project"
  def artifacts():
    return sorted({path.parent.name for path in (ws.instance / "dsh-home/sessions").glob("*/*/session*.jsonl*")})
  try:
    assert runtime_packages.status(Path("/seed"), lock.identity) == "installed"
    destination = ws.backend.root(ws, lock.identity)
    destination.parent.mkdir(mode=0o700, parents=True)
    shutil.copytree("/seed", destination, symlinks=True)
    assert runtime_packages.status(destination, lock.identity) == "installed"
    evidence["sync"] = ws.backend.sync(ws, lock)
    commands.apply_candidate(ws, lock, ws.candidate(lock.identity))
    with Tree(ws.state_root) as state, instance_lock(state):
      ws.adapter.prepare_runtime(ws, destination)
    first = start(["--no-input", "run", "dsh", "--local", str(local), "--profile", "dsh-default", "--cwd", "/probe/project"])
    old = wait_for(ready_run, "initial control")
    wait_for(lambda: not (termios.tcgetattr(terminals[0][1])[3] & termios.ICANON)
      and "fixture-not-real" in text(0), "initial TUI ready")
    host(old)
    # 仅首次运行提交一次合成提示；恢复阶段严格零输入。
    initial_input = os.write(terminals[0][0], b"\x1b[200~CONCURRENCY_ONE\x1b[201~")
    wait_for(lambda: "CONCURRENCY_ONE" in text(0), "synthetic paste visible")
    initial_input += os.write(terminals[0][0], b"\r")
    wait_for(lambda: "DONE_ONE" in text(0) and "ONE" in snapshot()["responses"], "synthetic history complete")
    ids = wait_for(lambda: artifacts(), "native session artifact")
    assert len(ids) == 1
    sid = ids[0]
    evidence["fixture_before_stop"] = snapshot()
    local.write_text(local.read_text().replace("terminal_images=false", "terminal_images=true"))
    args = ["--run", old, "--session", old + "=" + sid, "--label", old + "=Synthetic history"]
    plan = maintenance("plan", *args)
    stopped = maintenance("stop", *args, "--plan-id", plan["plan_id"])
    evidence["initial_exit"] = first.wait(timeout=30)
    assert termios.tcgetattr(terminals[0][1]) == terminals[0][2]
    batch = stopped["batch_id"]
    preview = maintenance("plan", "--batch", batch)
    assert preview["setup_preview"]["summary"]["changes"] > 0
    updated = maintenance("execute", "--batch", batch, "--plan-id", preview["setup_preview"]["plan_id"])
    assert updated["status"] == "updated"
    listing = call(["--no-input", "resume", "dsh", "--local", str(local), "--profile", "dsh-default",
      "--stopped", "--list", "--batch", batch, "--run", old, "--format", "json"])
    assert len(listing["sessions"]) == 1
    row = listing["sessions"][0]
    assert row["session_id"] == sid and row["cwd"] == "/probe/project" and row["restorable"]
    restore_args = ["--no-input", "resume", "dsh", "--local", str(local), "--profile", "dsh-default",
      "--stopped", "--batch", batch, "--run", old, "--here", "--format", "json"]
    restored = start(restore_args)
    new = wait_for(lambda: ready_run(old), "restored control")
    wait_for(lambda: "DONE_ONE" in text(1), "resumed native history visible")
    host(new)
    assert "--resume" in evidence["native_hosts"][new]["argv"]
    assert sid in evidence["native_hosts"][new]["argv"]
    stop_args = ["--no-input", "agent", "--local", str(local), "--profile", "dsh-default", "instances", "stop", "--run", new]
    stop_preview = call([*stop_args, "--dry-run"])
    call([*stop_args, "--plan-id", stop_preview["plan_id"]])
    evidence["restore_exit"] = restored.wait(timeout=30)
    assert termios.tcgetattr(terminals[1][1]) == terminals[1][2]
    status = maintenance("status", "--batch", batch)
    assert status["load_confirmation"] == "unknown" and status["continue_status"] == "not_sent"
    call(restore_args, expected=4)
    assert artifacts() == [sid] and set(records()) == {old, new}
    evidence["fixture_after_restore"] = snapshot()
    assert snapshot()["error"] is None
    for record in records().values():
      identity = record["host_identity"]["identity"]
      assert run_owners.observed_process_identity(identity["pid"]) != identity
    evidence.update(success=True, old_run=old, new_run=new, session=sid, batch=batch,
      initial_input_bytes=initial_input, restore_input_bytes=0, history_visible=True,
      terminal_restored=True, no_active_hosts=True, final_records=records())
  except Exception as error:
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
    server.shutdown()
    server.server_close()
    server_thread.join()
    for name in ("fixture_before_stop", "fixture_after_restore"):
      if name in evidence:
        evidence[name]["responses"] = sorted(evidence[name]["responses"])
    save("result.json", evidence)
  print(json.dumps({key: evidence[key] for key in ("success", "failure") if key in evidence}))
  return 0 if evidence.get("success") else 1


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--root", type=Path)
  parser.add_argument("--node-root", type=Path)
  parser.add_argument("--runtime", type=Path)
  parser.add_argument("--trace", action="store_true", help=argparse.SUPPRESS)
  parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要明确 --allow-host；会启动和停止隔离的真实 DSH")
  if args.inside:
    return inside(args.trace)
  if args.root is None or args.node_root is None or args.runtime is None or args.root.exists():
    parser.error("需要不存在的 --root、锁定 --node-root 和已核验 --runtime")
  args.root.mkdir(mode=0o700)
  argv = ["bwrap", "--die-with-parent", "--unshare-pid", "--unshare-net", "--proc", "/proc", "--dev", "/dev",
    "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
    "--symlink", "usr/lib64", "/lib64", "--ro-bind", str(REPO), "/workspace",
    "--ro-bind", str((REPO / ".venv").resolve()), "/venv", "--ro-bind", str(args.node_root), "/opt/node",
    "--ro-bind", str(args.runtime), "/seed", "--bind", str(args.root), "/probe", "--tmpfs", "/tmp",
    "--setenv", "PATH", "/opt/node/bin:/usr/bin:/bin", "--chdir", "/workspace",
    "/venv/bin/python", "/workspace/tests/manual/dsh_tool_workflow_native.py", "--allow-host", "--inside"]
  if args.trace:
    argv.append("--trace")
    (args.root / "trace_cli.py").write_text('''import sys, os, json
fd = os.open("/probe/trace-events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
selected = {"dsh_stop_control.py", "stop_service.py", "run_owners.py", "stop_inbox.py", "dsh_stop_scope.py"}
def trace(frame, event, arg):
  name = frame.f_code.co_filename.rsplit("/", 1)[-1]
  if event == "exception" and name in selected:
    os.write(fd, (json.dumps({"file": name, "function": frame.f_code.co_name, "line": frame.f_lineno, "exception": arg[0].__name__}) + "\\n").encode())
  return trace if name in selected else None
sys.settrace(trace)
from rotom.cli import main
raise SystemExit(main())
''')
  (args.root / "argv.json").write_text(json.dumps(argv, indent=2) + "\n")
  with (args.root / "run.log").open("wb") as log:
    result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=600,
      env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
  print(json.dumps({"exit_code": result.returncode, "evidence": str(args.root)}))
  return result.returncode


if __name__ == "__main__":
  raise SystemExit(main())
