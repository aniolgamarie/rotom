"""以真实第一方进程验证停止恢复授权；darwin经测试侧helper收据，不声称调用过模型或 SDK。"""
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

from .activity import digest
from .activity_linux import LinuxProcesses
from .deployment import json_bytes
from .pi_lifecycle import assert_inactive
from .pi_output import OutputCapture
from .pi_recovery import recover
from .process import DependencyError
from .storage import Conflict, Tree, ensure_private


def run_recovery_case(fixture, runtime, document, path):
  workspace = fixture["workspace"]
  ensure_private(workspace.state_root)
  with Tree(workspace.instance) as tree: manifest = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])
  config = {"state_root": str(workspace.state_root), "instance_root": str(workspace.instance), "repository": str(runtime.root / "supervisor"),
    "runtime_root": str(runtime.root), "instance_id": digest({"instance": str(workspace.instance), "binding": workspace.binding}),
    "lock_identity": runtime.lock_identity, "slice_identity": runtime.slice_identity, "policy_digest": digest(manifest["permission_policy"]),
    "manifest_digest": digest(manifest), "cwd": str(fixture["project"]), "engine": runtime.engine, "argv": [sys.executable],
    "protected_roots": [str(workspace.local_path), str(workspace.instance), str(workspace.state_root)]}
  source = Path(__file__).resolve().parents[2]
  intent = path.parent / "recovery-input.json"
  with Tree(path.parent) as tree: tree.write_new(intent.name, json_bytes({"config": config, "local": str(workspace.local_path), "profile": runtime.profile, "nonce": document["nonce"]}))
  environment = {**fixture["environment"], "AGENTCFG_NATIVE_VALIDATION": "1"}
  capture = OutputCapture(path.parent / "recovery-owner-output")
  runner = _run_recovery_case_darwin if sys.platform == "darwin" else _run_recovery_case_linux
  return runner(fixture, runtime, document, path, config, source, intent, environment, capture)


def _darwin_test_helper(runtime, directory):
  """测试侧监督helper：取运行包固定helper与收据摘要，仅用于包裹owner与kill-control。"""
  from .activity_macos import MacProcesses
  helper = runtime.root / "bin/pi-supervisor-macos"
  with Tree(runtime.root) as tree: raw = tree.read(".agentcfg-receipt.json")
  try: helper_digest = json.loads(raw[0])["files"]["bin/pi-supervisor-macos"]["sha256"]
  except (KeyError, TypeError, ValueError): raise DependencyError("macOS恢复helper尚未进入已验证运行包") from None
  return MacProcesses(helper, directory / "recovery-processes", helper_digest=helper_digest)


def _run_recovery_case_darwin(fixture, runtime, document, path, config, source, intent, environment, capture, processes_factory=None):
  """darwin完整恢复语义：owner异常退出→worker仍活动→恢复路径经owner自己的helper链显式停止→完整终止证明。

  流程：测试侧helper包裹owner；OWNER控制动作只SIGKILL owner（核对出生身份，按audit token），
  不触碰作用域内worker；owner死后测试侧helper继续服务通道直到worker也停止才退出；
  worker由owner启动时经运行包helper链监督，其控制socket在owner死后仍活着，
  恢复路径经撤权+计划+该socket完成带收据的停止——即"停止仍活动的遗留执行"。
  """
  from .pi_control import read_frame
  processes = processes_factory(runtime, path.parent) if processes_factory else _darwin_test_helper(runtime, path.parent)
  helper = processes.helper
  gate_read, gate_write = os.pipe(); nonce_read, nonce_write = os.pipe(); status_read, status_write = os.pipe()
  nonce = secrets.token_hex(32); control = path.parent / "recovery-owner.sock"
  os.write(nonce_write, (nonce + "\n").encode()); os.close(nonce_write)
  owner = subprocess.Popen([str(helper), "supervise", str(control), str(nonce_read), str(status_write), str(gate_read), "--",
      sys.executable, "-B", "-I", str(source / "scripts/pi-native-recovery.py"), "--owner-input", str(intent)],
    cwd=fixture["project"], env=environment, pass_fds=(nonce_read, status_write, gate_read), start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
  os.close(nonce_read); os.close(status_write); os.close(gate_read)
  capture.attach(owner)
  owner_identity = None; args = None; ready = None; worker = None; armed = None; completed = False
  facts = {"real_account_used": False, "sdk_session": False, "first_party_processes": True}
  try:
    with os.fdopen(status_read, "rb") as status: handshake = read_frame(status)
    if handshake["state"] != "ready" or handshake["control_path"] != str(control): raise Conflict("PI_NATIVE_RECOVERY_HANDSHAKE")
    owner_identity = handshake["worker"]
    os.write(gate_write, b"G"); os.close(gate_write); gate_write = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
      with Tree(path.parent) as tree:
        row = tree.read("recovery-owner.json"); marker = tree.read("recovery-worker.json"); armed_raw = tree.read("recovery-armed.json")
      if row and marker and armed_raw:
        ready = json.loads(row[0]); worker = json.loads(marker[0]); armed = json.loads(armed_raw[0])
        if (row[1] != 0o600 or marker[1] != 0o600 or armed_raw[1] != 0o600 or ready["nonce"] != document["nonce"]
            or ready["owner"] != owner_identity or ready["target"]["pid"] != worker["pid"] or armed["nonce"] != document["nonce"]):
          raise Conflict("PI_NATIVE_RECOVERY_IDENTITY")
        break
      if owner.poll() is not None: raise Conflict("PI_NATIVE_RECOVERY_OWNER_EXIT")
      time.sleep(0.05)
    if ready is None or armed is None: raise Conflict("PI_NATIVE_RECOVERY_TIMEOUT")
    args = SimpleNamespace(agent="pi", local=fixture["workspace"].local_path, profile=runtime.profile, lease=ready["lease_id"], stop=False, expect_plan=None)
    try: recover(args)
    except Conflict: facts["live_owner_rejected"] = True
    else: raise Conflict("PI_NATIVE_RECOVERY_LIVE_OWNER_ACCEPTED")
    # owner存活期间worker必须活动，作为后续场景基线。
    if processes.observe(ready["target"]) != "alive": raise Conflict("PI_NATIVE_RECOVERY_TARGET_EXIT")
    # OWNER控制动作：经helper按出生身份+audit token只SIGKILL owner；worker不受影响。
    read_fd, write_fd = os.pipe()
    try:
      os.write(write_fd, (nonce + "\n").encode()); os.close(write_fd); write_fd = None
      reply = subprocess.run([str(helper), "owner-control", str(control), str(read_fd), "2"], cwd=path.parent,
        env=environment, pass_fds=(read_fd,), capture_output=True, text=True)
      if reply.returncode or reply.stdout.strip() != "accepted": raise Conflict("PI_NATIVE_RECOVERY_OWNER_KILL_REJECTED")
    finally:
      os.close(read_fd)
      if write_fd is not None: os.close(write_fd)
    # owner死亡证明：明确dead，不接受unknown。
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
      if processes.observe(owner_identity) == "dead": break
      time.sleep(0.05)
    if processes.observe(owner_identity) != "dead": raise Conflict("PI_NATIVE_RECOVERY_OWNER_UNVERIFIED")
    facts["old_owner_dead"] = True
    # 关键事实：owner死后worker仍活动（遗留执行未被整体kill-control预先终止）。
    if processes.observe(ready["target"]) != "alive": raise Conflict("PI_NATIVE_RECOVERY_TARGET_PREMATURE_EXIT")
    facts["worker_survived_owner_death"] = True
    _, plan = recover(args)
    args.stop, args.expect_plan = True, "0" * 64
    try: recover(args)
    except Conflict: facts["wrong_plan_rejected"] = True
    else: raise Conflict("PI_NATIVE_RECOVERY_WRONG_PLAN_ACCEPTED")
    args.expect_plan = plan["plan_digest"]
    _, result = recover(args)
    with Tree(fixture["workspace"].state_root) as tree: lease = json.loads(tree.read("activity/leases/" + ready["lease_id"] + ".json")[0])
    facts["stop_only_recovery"] = result["protected"] is False and result["state"] == "reclaimed" and lease["grant_generation"] > 1
    # 终止证明：明确dead，unknown不算终止；收据由owner自己的helper链在停止时写入。
    facts["target_terminated"] = processes.observe(ready["target"]) == "dead"
    facts["source_preserved"] = (fixture["project"] / "code.txt").read_text() == "original\n"
    completed = all(facts.get(key) is True for key in ("live_owner_rejected", "old_owner_dead", "worker_survived_owner_death",
      "wrong_plan_rejected", "stop_only_recovery", "target_terminated", "source_preserved"))
  finally:
    if gate_write is not None:
      try: os.close(gate_write)
      except OSError: pass
    if owner.poll() is None:
      try: owner.kill()
      except OSError: pass
      owner.wait(timeout=10)
  deadline = time.monotonic() + 5
  for thread in capture.threads: thread.join(max(0, deadline - time.monotonic()))
  ended = capture.complete() and len(capture.results) == 2 and not any(row["failed"] for row in capture.results.values())
  try: assert_inactive(fixture["workspace"].state_root)
  except Conflict: ended = False
  with Tree(path.parent) as tree:
    tree.write_new("controller-result.json", json_bytes({"schema_version": 1, "nonce": document["nonce"], "scenario": "recovery-grants", "runtime_identity": runtime.identity,
      "status": "passed" if completed and ended else "failed", "host_exit_code": 0, "termination_confirmed": ended,
      "executions": 1 if ready else 0, "worker_executions": 0, "provider": {"requests": 0}, "facts": facts}))
  return 0 if completed and ended else 5


def _run_recovery_case_linux(fixture, runtime, document, path, config, source, intent, environment, capture):
  workspace = fixture["workspace"]
  ensure_private(workspace.state_root)
  owner = subprocess.Popen([sys.executable, "-B", "-I", str(source / "scripts/pi-native-recovery.py"), "--owner-input", str(intent)],
    cwd=fixture["project"], env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
  capture.attach(owner)
  processes = LinuxProcesses(workspace.state_root / "activity/processes")
  owner_identity = processes.identity(owner.pid)
  args, ready, completed = None, None, False
  facts = {"real_account_used": False, "sdk_session": False, "first_party_processes": True}
  try:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
      with Tree(path.parent) as tree:
        row = tree.read("recovery-owner.json"); marker = tree.read("recovery-worker.json")
      if row and marker:
        ready = json.loads(row[0]); worker = json.loads(marker[0])
        if row[1] != 0o600 or marker[1] != 0o600 or ready["nonce"] != document["nonce"] or ready["owner"] != owner_identity or ready["target"]["pid"] != worker["pid"]:
          raise Conflict("PI_NATIVE_RECOVERY_IDENTITY")
        break
      if owner.poll() is not None: raise Conflict("PI_NATIVE_RECOVERY_OWNER_EXIT")
      time.sleep(0.05)
    if ready is None: raise Conflict("PI_NATIVE_RECOVERY_TIMEOUT")
    args = SimpleNamespace(agent="pi", local=workspace.local_path, profile=runtime.profile, lease=ready["lease_id"], stop=False, expect_plan=None)
    try: recover(args)
    except Conflict: facts["live_owner_rejected"] = True
    else: raise Conflict("PI_NATIVE_RECOVERY_LIVE_OWNER_ACCEPTED")
    if processes.observe(ready["target"]) != "alive": raise Conflict("PI_NATIVE_RECOVERY_TARGET_EXIT")
    processes.send_signal(owner_identity, signal.SIGKILL)
    if owner.wait(timeout=10) != -signal.SIGKILL or processes.observe(owner_identity) != "dead": raise Conflict("PI_NATIVE_RECOVERY_OWNER_UNVERIFIED")
    facts["old_owner_dead"] = True
    _, plan = recover(args)
    args.stop, args.expect_plan = True, "0" * 64
    try: recover(args)
    except Conflict: facts["wrong_plan_rejected"] = True
    else: raise Conflict("PI_NATIVE_RECOVERY_WRONG_PLAN_ACCEPTED")
    if processes.observe(ready["target"]) != "alive": raise Conflict("PI_NATIVE_RECOVERY_PREMATURE_STOP")
    args.expect_plan = plan["plan_digest"]
    _, result = recover(args)
    with Tree(workspace.state_root) as tree: lease = json.loads(tree.read("activity/leases/" + ready["lease_id"] + ".json")[0])
    facts["stop_only_recovery"] = result["protected"] is False and result["state"] == "reclaimed" and lease["grant_generation"] > 1
    facts["target_terminated"] = processes.observe(ready["target"]) == "dead"
    facts["source_preserved"] = (fixture["project"] / "code.txt").read_text() == "original\n"
    completed = all(facts.get(key) is True for key in ("live_owner_rejected", "old_owner_dead", "wrong_plan_rejected", "stop_only_recovery", "target_terminated", "source_preserved"))
  finally:
    if owner.poll() is None:
      processes.send_signal(owner_identity, signal.SIGKILL)
      owner.wait(timeout=10)
    # 清理只复用同一夹具的正式停止计划；无法核验时保持持久保护。
    if args is not None and ready is not None and processes.observe(ready["target"]) == "alive":
      try:
        args.stop, args.expect_plan = False, None
        _, plan = recover(args)
        args.stop, args.expect_plan = True, plan["plan_digest"]
        recover(args)
      except Exception: completed = False
  deadline = time.monotonic() + 5
  for thread in capture.threads: thread.join(max(0, deadline - time.monotonic()))
  ended = capture.complete() and len(capture.results) == 2 and not any(row["failed"] for row in capture.results.values())
  try: assert_inactive(workspace.state_root)
  except Conflict: ended = False
  with Tree(path.parent) as tree:
    tree.write_new("controller-result.json", json_bytes({"schema_version": 1, "nonce": document["nonce"], "scenario": "recovery-grants", "runtime_identity": runtime.identity,
      "status": "passed" if completed and ended else "failed", "host_exit_code": 0, "termination_confirmed": ended,
      "executions": 1 if ready else 0, "worker_executions": 0, "provider": {"requests": 0}, "facts": facts}))
  return 0 if completed and ended else 5
