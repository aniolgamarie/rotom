#!/usr/bin/env python3
"""显式 Pi 双 CLI / 原生 TUI 并发验收；新建隔离夹具，零 prompt、零模型请求。"""
import argparse
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import shutil
import tempfile
import struct
import subprocess
import sys
import termios
import threading
import time
import uuid


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
  parser.add_argument("--runtime", required=True, type=Path, help="匹配仓库完整锁的 sealed pi-default 包")
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("requires --allow-host")
  os.umask(0o077)
  repo = args.repository.resolve()
  sys.path.insert(0, str(repo / "src"))
  from agentcfg.activity import OWNER_KEYS, allocation_digest, digest, protected
  from agentcfg.activity_linux import LinuxProcesses
  from agentcfg.pi_dependencies import PiBackend
  from agentcfg.pi_validation_fixture import prepare_configuration
  from agentcfg.pi_validation_native import program_bindings
  from agentcfg.pi_validation_runtime import inspect_runtime
  from agentcfg.pi_pid_namespace import namespace_record
  from agentcfg.pi_catalog import validate
  from agentcfg.pi_control import endpoint_for_owner, request
  from agentcfg.storage import Conflict, Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, exist_ok=False)
  ensure_private(evidence)
  result = {"overall": "FAIL", "stage": "prepare", "platform": sys.platform, "checks": {}, "commands": [],
            "hosts": [], "real_model_calls": 0, "accounts": "NOT RUN", "model_requests": "NOT RUN",
            "cross_platform": "NOT RUN", "nondefault_profiles": "NOT RUN", "os_sandbox_bypass": False,
            "budgets": {"wall_seconds": 600, "ready_seconds": 120, "cli_seconds": 180}, "timings": []}
  children, server, requests, root = [], None, [], None
  started = time.monotonic()
  deadline = started + 600
  def checkpoint(stage):
    result["timings"].append({"stage": stage, "elapsed_seconds": round(time.monotonic() - started, 3)})
  def budget(seconds=60):
    left = deadline - time.monotonic()
    if left <= 0:
      raise RuntimeError("OVERALL_TIMEOUT")
    return min(seconds, left)
  def pump(seconds=0.05):
    for fd in select.select([row["master"] for row in children], [], [], seconds)[0] if children else []:
      try:
        next(row for row in children if row["master"] == fd)["output"].extend(os.read(fd, 65536))
      except OSError:
        pass
  def visible(child):
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", child["output"].decode(errors="replace"))
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
  def wait(child, predicate, seconds=120):
    until = time.monotonic() + budget(seconds)
    while not predicate() and time.monotonic() < until:
      if child["process"].poll() is not None and not predicate():
        raise RuntimeError("HOST_EXITED_BEFORE_CHECK")
      if requests:
        raise RuntimeError("UNEXPECTED_MODEL_REQUEST")
      pump()
    if not predicate():
      raise RuntimeError("NATIVE_TIMEOUT")
  def cli(command, expected):
    argv = [str(repo / "agentcfg"), "--local", str(local), "--profile", "pi-default", command]
    value = subprocess.run(argv, cwd=root, env=env, capture_output=True, timeout=budget(180))
    log = f"cli-{len(result['commands'])}-{command}.log"
    (evidence / log).write_bytes(value.stdout + value.stderr)
    result["commands"].append({"argv": argv, "exit": value.returncode, "log": log})
    checkpoint("cli_" + command)
    if value.returncode != expected:
      raise RuntimeError("CLI_EXIT_MISMATCH")
  def leases():
    rows = []
    directory = workspace.state_root / "activity/leases"
    if not directory.exists():
      return rows
    # 原生监督者以同一短锁发布记录；跨文件快照不能枚举在途暂存文件。
    with Tree(workspace.state_root / "activity") as mutations, instance_lock(mutations, shared=True, timeout=5), Tree(directory) as tree:
      for name in os.listdir(tree.fd):
        if not name.endswith(".json"):
          raise RuntimeError("LEASE_INVALID")
        raw = tree.read(name)
        row = json.loads(raw[0])
        validate("execution-lease", row)
        if name != row["lease_id"] + ".json" or raw[1] != 0o600 or row["allocation_journal_digest"] != allocation_digest(row):
          raise RuntimeError("LEASE_INVALID")
        if row["kind"] == "host":
          rows.append(row)
    return rows
  def alive(row):
    return (row["state"] == "running" and protected(row)
      and processes.observe(row["process_identity"]) == "alive"
      and processes.observe(row["supervisor_process_identity"]) == "alive")
  def ownership(row):
    owner = {key: row[key] for key in OWNER_KEYS}
    with Tree(workspace.state_root) as tree:
      registration = json.loads(tree.read("activity/supervisors/" + owner["supervisor_activation_id"] + ".json")[0])
    if registration != {"version": 2, "owner": owner}:
      raise RuntimeError("COMPLETE_OWNER_REGISTRATION")
    endpoint, control = endpoint_for_owner(workspace.state_root, owner)
    handshake = request(endpoint, control["user_capability"], {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": "handshake", "args": {}})
    if not handshake.get("ok") or handshake["result"]["supervisor_activation_id"] != owner["supervisor_activation_id"]:
      raise RuntimeError("CONTROL_OWNER_HANDSHAKE")
    return owner, endpoint, control
  try:
    if sys.platform != "linux":
      result.update(overall="BLOCKED", blocker="PLATFORM_NOT_IMPLEMENTED")
      raise RuntimeError("PLATFORM_NOT_IMPLEMENTED")
    def timeout(_signum, _frame): raise RuntimeError("OVERALL_TIMEOUT")
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(600)
    runtime = inspect_runtime(args.runtime)
    lock = PiBackend().read_lock(repo)
    checkpoint("source_runtime_and_lock_verified")
    if runtime.profile != "pi-default" or runtime.lock_identity != lock.identity:
      raise RuntimeError("SEALED_BINDING_CHANGED")
    original_receipt = (runtime.root / ".agentcfg-receipt.json").read_bytes()
    programs = program_bindings(runtime)
    root = Path(tempfile.mkdtemp(prefix="rotom-pi-concurrency-", dir="/tmp"))
    result["fixture_root"] = str(root)
    env = {"PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    for name, suffix in {"HOME": "native-manager-home", "XDG_CONFIG_HOME": "native-config", "XDG_DATA_HOME": "native-data", "XDG_STATE_HOME": "native-state", "XDG_CACHE_HOME": "native-cache", "TMPDIR": "native-tmp"}.items():
      env[name] = str(root / suffix)
      ensure_private(root / suffix)
    os.environ.clear()
    os.environ.update(env)
    result["candidate_commit"] = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], env=env, capture_output=True, text=True, check=True, timeout=budget(5)).stdout.strip()
    public = [repo / "agentcfg", *sorted((repo / "src/agentcfg").glob("*.py")), *sorted((repo / "agents/pi/runtime").glob("*.ts"))]
    source = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in public}
    result["source_sha256"] = digest(source)
    result["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    version = subprocess.run([programs["engine"], "--version"], env=env, capture_output=True, text=True, check=True, timeout=budget(5)).stdout.strip()
    if version != runtime.toolchains["node"]: raise RuntimeError("NODE_VERSION")
    result["node"] = version
    class Handler(BaseHTTPRequestHandler):
      def log_message(self, *_args):
        pass
      def do_POST(self):
        requests.append("unexpected")
        self.send_response(503)
        self.send_header("Content-Length", "0")
        self.end_headers()
      do_GET = do_POST
    class Server(ThreadingHTTPServer):
      daemon_threads = True
    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True).start()
    def git_run(argv, **kwargs):
      value = subprocess.run(argv, **kwargs, capture_output=True, check=True, timeout=budget(10))
      result["commands"].append({"argv": argv, "exit": value.returncode})
    fixture = prepare_configuration(root / "fixture", repo, "pi-default", f"http://127.0.0.1:{server.server_port}/v1", programs, run=git_run)
    local = root / "fixture/local.toml"
    with local.open("a") as output: output.write('\n[machine.environment.values]\nPI_OFFLINE="1"\n')
    workspace = load_workspace(local, "pi-default", repository=repo)
    if workspace.backend.runtime_identity(workspace, lock) != runtime.identity: raise RuntimeError("SEALED_BINDING_CHANGED")
    destination = workspace.backend.root(workspace, runtime.identity)
    if not destination.is_relative_to(root): raise RuntimeError("ISOLATION_BOUNDARY")
    ensure_private(destination.parent)
    shutil.copytree(runtime.root, destination, symlinks=True)
    if inspect_runtime(destination).public_identity() != runtime.public_identity(): raise RuntimeError("COPY_INVALID")
    checkpoint("isolated_runtime_copy_verified")
    result.update(lock_identity=lock.identity, runtime=runtime.public_identity(), source_files=source,
      config_sha256=hashlib.sha256(local.read_bytes()).hexdigest(), candidate_generation=workspace.candidate(lock.identity).generation)
    cli("apply", 0)
    cli("sync", 0)
    processes = LinuxProcesses(workspace.state_root / "activity/processes")
    for label in ("ONE", "TWO"):
      result["stage"] = "launch_" + label
      project = root / ("native-project-" + label + "-" + uuid.uuid4().hex[:6])
      ensure_private(project)
      subprocess.run(["git", "init", "-q", str(project)], env=env, check=True, timeout=budget(5))
      known = {row["lease_id"] for row in leases()}
      master, slave = pty.openpty()
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
      child = {"label": label, "master": master, "slave": slave, "before": termios.tcgetattr(slave), "output": bytearray()}
      argv = [str(repo / "agentcfg"), "--local", str(local), "--profile", "pi-default", "run", "--cwd", str(project)]
      child["process"] = subprocess.Popen(argv, cwd=project, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
      children.append(child)
      checkpoint("launched_" + label)
      record = {"label": label, "argv": argv}
      result["hosts"].append(record)
      wait(child, lambda: "agentcfg-native-main" in visible(child) and not termios.tcgetattr(slave)[3] & termios.ICANON and any(row["lease_id"] not in known and alive(row) for row in leases()))
      row = next(row for row in leases() if row["lease_id"] not in known and alive(row))
      namespace = namespace_record(processes, row["process_identity"])
      if namespace is None or namespace["terminated"]: raise RuntimeError("HOST_NAMESPACE_UNVERIFIED")
      owner, endpoint, control = ownership(row)
      checkpoint("native_ready_" + label)
      child.update(lease_id=row["lease_id"], owner=owner, endpoint=endpoint, control=control)
      record.update(lease_id=row["lease_id"], owner_sha256=digest(owner), supervisor_activation_id=owner["supervisor_activation_id"],
        manager_activation_id=owner["manager_activation_id"], complete_owner_live=True, endpoint=str(endpoint), raw_terminal_ready=True, tui_model_rendered=True, pid_namespace_verified=True)
    first, second = children
    if first["owner"]["instance_id"] != second["owner"]["instance_id"] or any(first["owner"][key] == second["owner"][key] for key in OWNER_KEYS if key != "instance_id"):
      raise RuntimeError("OWNER_NOT_DISTINCT")
    if first["endpoint"] == second["endpoint"]: raise RuntimeError("ENDPOINT_NOT_DISTINCT")
    if not all(alive(next(row for row in leases() if row["lease_id"] == child["lease_id"])) for child in children): raise RuntimeError("OWNER_NOT_LIVE")
    result["checks"]["two_complete_distinct_live_host_owners"] = "PASS"
    crossed = request(second["endpoint"], first["control"]["user_capability"], {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": "handshake", "args": {}})
    if crossed.get("ok") or crossed.get("exit_code") != 4:
      raise RuntimeError("CROSS_OWNER_CONTROL_ACCEPTED")
    mixed = {**second["owner"], "supervisor_activation_id": first["owner"]["supervisor_activation_id"]}
    try:
      endpoint_for_owner(workspace.state_root, mixed)
    except Conflict:
      result["checks"]["activation_endpoints_and_cross_owner_refusal"] = "PASS"
    else:
      raise RuntimeError("CROSS_OWNER_ENDPOINT_ACCEPTED")
    cli("apply", 4)
    result["checks"]["maintenance_blocked_both_active"] = "PASS"
    for index, child in enumerate(children):
      result["stage"] = "exit_" + child["label"]
      os.write(child["master"], b"\x03")
      until = time.monotonic() + 0.3
      while time.monotonic() < until:
        pump()
      if child["process"].poll() is None:
        os.write(child["master"], b"\x03")
      wait(child, lambda: child["process"].poll() is not None, 20)
      restored = child["before"] == termios.tcgetattr(child["slave"])
      result["hosts"][index].update(exit=child["process"].returncode, termios_restored=restored)
      if child["process"].returncode != 0 or not restored:
        raise RuntimeError("EXIT_OR_TERMIOS_FAILED")
      checkpoint("clean_exit_" + child["label"])
      finished = next(row for row in leases() if row["lease_id"] == child["lease_id"])
      namespace = namespace_record(processes, finished["process_identity"])
      if namespace is None or not namespace["terminated"]: raise RuntimeError("HOST_NAMESPACE_NOT_TERMINATED")
      if protected(finished):
        raise RuntimeError("EXIT_LEASE_REMAINS_PROTECTED")
      if index == 0:
        survivor = next(row for row in leases() if row["lease_id"] == second["lease_id"])
        if second["process"].poll() is not None or not alive(survivor):
          raise RuntimeError("SECOND_OWNER_NOT_LIVE")
        ownership(survivor)
        cli("apply", 4)
        result["checks"]["first_exit_preserves_second_owner_and_lease"] = "PASS"
    cli("apply", 0)
    if requests or (runtime.root / ".agentcfg-receipt.json").read_bytes() != original_receipt or inspect_runtime(runtime.root).public_identity() != runtime.public_identity() or workspace.backend.status(workspace, runtime.identity) != "installed":
      raise RuntimeError("MODEL_CALL_OR_RUNTIME_CHANGE")
    result["checks"].update(both_exit0_termios_restored="PASS", final_maintenance="PASS", sealed_runtime_unchanged="PASS")
    result.update(overall="PASS", stage="complete")
  except Exception as error:
    result.update(error_code=str(error) if isinstance(error, RuntimeError) and re.fullmatch(r"[A-Z_]{1,80}", str(error)) else type(error).__name__, error_location=result["stage"])
  finally:
    signal.alarm(0)
    for child in children:
      process = child["process"]
      try:
        if process.poll() is None:
          if os.getpgid(process.pid) != process.pid: raise RuntimeError("OWNED_GROUP_MISMATCH")
          os.killpg(process.pid, signal.SIGTERM)
          try: process.wait(timeout=5)
          except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
      except (OSError, RuntimeError, subprocess.TimeoutExpired):
        result.update(overall="FAIL", cleanup="OWNED_CHILD_CLEANUP_FAILED")
      pump(0)
      result.setdefault("observed_exits", {})[child["label"]] = process.poll()
      raw = bytes(child["output"])
      if result["overall"] != "PASS" and any(word in raw.lower() for word in [b"operation not permitted", b"creating new namespace failed"]):
        result["overall"], result["blocker"] = "BLOCKED", "OS_NAMESPACE_UNAVAILABLE"
      (evidence / (child["label"] + ".pty.log")).write_bytes(raw)
    for child in children:
      os.close(child["master"])
      os.close(child["slave"])
    if server:
      server.shutdown()
      server.server_close()
    if "workspace" in locals():
      try:
        result["execution_records"] = [{"lease_id": row["lease_id"], "state": row["state"], "protected": protected(row),
          "process_status": processes.observe(row["process_identity"]) if row.get("process_identity") else "not_spawned"} for row in leases()]
      except Exception: result["execution_records"] = "UNVERIFIED"
    if "original_receipt" in locals():
      try:
        if (runtime.root / ".agentcfg-receipt.json").read_bytes() != original_receipt or inspect_runtime(runtime.root).public_identity() != runtime.public_identity(): raise RuntimeError()
        result["checks"]["source_runtime_unchanged"] = "PASS"
      except Exception: result.update(overall="FAIL", source_runtime="UNVERIFIED")
    result["log_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence.glob("*.log")}
    result["fixture_http_requests"] = len(requests)
    if requests:
      result.update(overall="FAIL", error_code="UNEXPECTED_MODEL_REQUEST")
    if root is not None and result["overall"] == "PASS": shutil.rmtree(root)
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
  print(json.dumps({"overall": result["overall"], "evidence": str(evidence)}))
  return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
