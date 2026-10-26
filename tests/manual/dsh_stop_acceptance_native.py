#!/usr/bin/env python3
"""显式隔离官方 DSH：真实停止 CLI、原句柄服务、快照及收尾验收。"""
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import termios
import time


HERE = Path(__file__).resolve().parent
DEFAULT_LAUNCH = "--default-launch" in sys.argv
if DEFAULT_LAUNCH:
  sys.argv.remove("--default-launch")
spec = importlib.util.spec_from_file_location("native_stop_base", HERE / "dsh_stop_native.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def worker(root, label, resume, candidate_resume=False):
  from agentcfg import dsh_process, dsh_stop_control, run_owners, runtime
  from agentcfg.workspace import load_workspace
  if candidate_resume:
    raise RuntimeError("STOP_ACCEPTANCE_ONLY")
  workspace = load_workspace(root / "machine.toml", profile="dsh-default", repository=base.REPOSITORY)
  prepared = json.loads((root / "preparation.json").read_text())
  if (not workspace.instance.is_relative_to(root) or not workspace.state_root.is_relative_to(root)
      or prepared["binding"] != workspace.binding or prepared["instance"] != str(workspace.instance)
      or prepared["state_root"] != str(workspace.state_root)):
    raise RuntimeError("ISOLATED_STOP_WORKER_REQUIRED")
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)

  def operation(workspace, launch, env, lease, contract, *, run_id, lifecycle_fd, package_fd):
    actual = dsh_stop_control.factory_for(workspace, instance_fd=lifecycle_fd, state_fd=lease)
    def factory(*, run_id, host):
      service = actual(run_id=run_id, host=host)
      base.save(root / label / "control.json", {"run_id": run_id, "endpoint": service.describe(),
        "lease_identities": [[os.fstat(fd).st_dev, os.fstat(fd).st_ino] for fd in (lifecycle_fd, lease)]})
      return service
    return dsh_process.launch(launch, env, tuple(fd for fd in (lifecycle_fd, lease, package_fd) if type(fd) is int),
      run_id=run_id, owner_registry=registry, manager_identity=registry.snapshot()[run_id]["manager_identity"],
      control_factory=factory)

  options = {} if DEFAULT_LAUNCH else {"resume_operation": operation}
  code = runtime.run(workspace, cwd=root / "project", arguments=("--resume", resume) if resume else (), **options)
  base.save(root / label / "worker-result.json", {"exit_code": code, "owners": registry.snapshot()})
  return code


def client(root, label):
  from agentcfg import dsh_stop
  from agentcfg.workspace import load_workspace
  from rotom import cli
  workspace = load_workspace(root / "machine.toml", profile="dsh-default", repository=base.REPOSITORY)
  if not workspace.state_root.is_relative_to(root):
    raise RuntimeError("ISOLATED_STOP_CLIENT_REQUIRED")
  control = json.loads((root / label / "control.json").read_text())
  selection = control.get("run_ids", [control["run_id"]])
  observed = dsh_stop.preview_stop(workspace, selected_runs=selection)
  base.save(root / label / "preview.json", observed)
  argv = ["--no-input", "agent", "--local", str(root / "machine.toml"), "--profile", "dsh-default",
    "instances", "stop", *[item for run in selection for item in ("--run", run)],
    "--plan-id", observed["plan"]["plan_id"], "--wait-seconds", "30"]
  base.save(root / label / "client-argv.json", {"argv": argv})
  return cli.main(argv)


def phase(root, env, workspace, label, resume=None, fixture=None, candidate_resume=False):
  from agentcfg.stop_dispatches import StopDispatches
  from agentcfg import dsh_stop_client, run_owners, run_stop_fence
  if fixture is not None or candidate_resume:
    raise RuntimeError("NO_INPUT_STOP_ACCEPTANCE_ONLY")
  folder = root / label
  folder.mkdir(mode=0o700)
  master, slave = pty.openpty()
  before = termios.tcgetattr(slave)
  fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
  argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--allow-host", "--root", str(root), "--worker", label]
  if resume:
    argv += ["--resume", resume]
  if DEFAULT_LAUNCH:
    argv += ["--default-launch"]
  base.save(folder / "worker-argv.json", {"argv": argv})
  child = subprocess.Popen(argv, cwd=root / "project", env=env, stdin=slave, stdout=slave, stderr=slave,
    start_new_session=True)
  output = bytearray()
  def pump():
    if select.select([master], [], [], 0.1)[0]:
      try:
        output.extend(os.read(master, 65536))
      except OSError:
        pass
  stopped = None
  control = None
  try:
    started = time.monotonic()
    while child.poll() is None and time.monotonic() - started < 20:
      pump()
      if DEFAULT_LAUNCH and not (folder / "control.json").exists():
        # 独立读取普通入口的登记；不注入工厂、不替换启动函数、不补写 owner。
        try:
          registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
          rows = [row for row in registry.snapshot().values() if row["manager_identity"]["pid"] == child.pid
            and row["lifecycle_state"] == "active" and row["protocol"]["control"] is not None]
          if len(rows) == 1:
            identities = [[path.stat().st_dev, path.stat().st_ino] for path in
              (workspace.instance, workspace.state_root / "instance.lock")]
            if base.leases_released(workspace, identities):
              raise RuntimeError("ORIGINAL_LEASES_NOT_HELD")
            base.save(folder / "control.json", {"run_id": rows[0]["run_id"],
              "endpoint": rows[0]["protocol"]["control"]["endpoint"], "lease_identities": identities})
        except Exception:
          # 尚未登记或读取竞争只继续观察，不建立候选控制或发送输入。
          pass
      if (folder / "control.json").exists() and time.monotonic() - started >= 8:
        break
    if child.poll() is None and (folder / "control.json").exists():
      control = json.loads((folder / "control.json").read_text())
      with (folder / "client.json").open("xb") as stdout, (folder / "client.stderr").open("xb") as stderr:
        stopped = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()),
          "--client", str(root), label], env=env, cwd=root / "project", stdin=subprocess.DEVNULL,
          stdout=stdout, stderr=stderr)
    until = time.monotonic() + 40
    while (child.poll() is None or stopped is not None and stopped.poll() is None) and time.monotonic() < until:
      pump()
    if child.poll() is None or stopped is not None and stopped.poll() is None:
      base.save(folder / "unconfirmed.json", {"status": "original-process-still-active"})
      print("Native stop unconfirmed; keeping original PTY, no additional signal or retry.", flush=True)
      while child.poll() is None or stopped is not None and stopped.poll() is None:
        pump()
  except BaseException:
    # 含客户端/元数据失败；不因测试退出关闭活动原宿主终端。
    while child.poll() is None or stopped is not None and stopped.poll() is None:
      pump()
    raise
  code = child.wait()
  restored = before == termios.tcgetattr(slave)
  os.close(master); os.close(slave)
  (folder / "transcript.bin").write_bytes(output)
  result = json.loads((folder / "client.json").read_text()) if stopped is not None else None
  dispatch = StopDispatches(workspace.state_root / "stop-dispatches", workspace.binding).read(control["run_id"]) if control else None
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  owners = registry.snapshot()
  saved = run_stop_fence.read_snapshot(registry, result["batch_id"]) if result else None
  status = dsh_stop_client.status_stop(workspace, batch_id=result["batch_id"]) if result else None
  matches = bool(dispatch and saved and control and result and dispatch["request"]["batch_id"] == result["batch_id"]
    and dispatch["request"]["plan_id"] == saved["plan_id"] == result["plan_id"]
    and dispatch["request"]["run_id"] == control["run_id"] == saved["selected_runs"][0])
  value = {"exit_code": code, "client_exit_code": stopped.returncode if stopped else None,
    "client_status": status, "requested_session": resume, "marker_before_stop": None,
    "marker_after_exit": base.session_id(workspace.instance / "user-home/.dsh-tui/resume.txt"),
    "stop_submitted": bool(stopped), "dispatch": dispatch, "dispatch_matches_request": matches,
    "owner_release": owners[control["run_id"]]["lifecycle_state"] if control else None,
    "physical_leases_released": base.leases_released(workspace, control["lease_identities"] if control else None),
    "termios_restored": restored, "input_bytes_sent": 0, "transcript_bytes": len(output)}
  base.save(folder / "result.json", value)
  return value


original_confirmed = base.channel_confirmed
base.channel_confirmed = lambda result: (original_confirmed(result) and result["client_exit_code"] == 0
  and result["client_status"]["status"] == "stopped" and result["client_status"]["protected"] is False)
base.worker, base.phase = worker, phase

if __name__ == "__main__":
  if len(sys.argv) == 4 and sys.argv[1] == "--client":
    os.umask(0o077)
    raise SystemExit(client(Path(sys.argv[2]), sys.argv[3]))
  raise SystemExit(base.main())
