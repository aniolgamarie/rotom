"""darwin恢复流程完整替身测试：用Python假helper模拟真实协议，调用生产流程函数。

覆盖：握手身份、gate放行、FD关闭、owner存活拒绝、OWNER动作后worker仍活动、
错误/过期计划拒绝、unknown不算终止、源项目保护、停止收据语义。
在Linux上运行；不启动macOS宿主，不修改生产helper语义。
capture回收与assert_inactive属宿主I/O层，替身中以受控替身提供，不在本测试范围。
"""
import json
import os
import socket
import time
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RECOVERY = __import__("importlib").import_module("agentcfg.pi_validation_recovery")

# 在任何fixture打补丁前保存真实Popen/os.kill/socket（与conftest同法）。
_REAL_POPEN = subprocess.Popen
_REAL_OS_KILL = os.kill
_REAL_SOCKET = socket.socket

NONCE = "f" * 64

# 假helper：argv与生产一致 [.., "supervise", socket, nonce_fd, status_fd, gate_fd, "--", owner...]
# 行为：读nonce→fork owner→握手→等gate→写三类身份标记(0600)→服务socket(OWNER/STOP/KILL)→
#       OWNER只SIGKILL child并留owner-action标记；child死后若worker-alive在、scope-killed不在则继续等。
FAKE_HELPER = r'''
import json, os, signal, socket, sys, threading, time
socket_path, nonce_fd, status_fd, gate_fd = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
owner_argv = sys.argv[7:]
directory = os.environ["FAKE_DIR"]
nonce = os.read(nonce_fd, 65).decode().strip()
child = os.fork()
if child == 0:
    # 与C helper一致：gate读端由child持有，读到放行字节后才exec owner。
    os.close(status_fd)
    gate = os.read(gate_fd, 1)
    if gate != b"G": os._exit(125)
    os.execv(owner_argv[0], owner_argv)
    os._exit(127)
os.close(gate_fd)
try: os.setpgid(child, child)
except OSError: pass
def write_marker(name, value):
    path = os.path.join(directory, name)
    # 与生产标记发布契约一致：完整写入后原子发布，读者不能看见半写入文件。
    temporary = path + ".partial"
    with open(temporary, "xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(value).encode())
    os.replace(temporary, path)
owner_identity = {"platform": "darwin", "boot_id": "fake:1:0", "pid": child, "ppid": os.getpid(),
                  "pgid": child, "uid": os.getuid(), "namespace": None, "start_time": "1.0"}
worker_identity = {**owner_identity, "pid": child + 100000}
status = os.fdopen(status_fd, "w")
status.write(json.dumps({"schema_version": 1, "state": "ready", "control_path": socket_path,
    "worker": owner_identity}) + "\n")
status.flush()
write_marker("recovery-owner.json", {"nonce": nonce, "lease_id": "lease-1",
    "owner": owner_identity, "target": worker_identity})
write_marker("recovery-worker.json", {"pid": worker_identity["pid"]})
write_marker("recovery-armed.json", {"nonce": nonce, "pid": child})
stopped = threading.Event()
def serve():
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path); server.listen(4); server.settimeout(0.2)
    generation = 2
    while not stopped.is_set():
        try: client, _ = server.accept()
        except socket.timeout: continue
        try:
            parts = client.recv(256).decode().strip().split(" ")
            if len(parts) == 3 and parts[1] == nonce and int(parts[2]) >= generation and parts[0] in ("OWNER", "KILL", "STOP"):
                action, _, gen = parts
                generation = int(gen)
                os.kill(child, signal.SIGKILL if action in ("OWNER", "KILL") else signal.SIGTERM)
                with open(os.path.join(directory, "owner-action" if action == "OWNER" else "scope-killed"), "w") as f:
                    f.write(action + "\n")
                client.sendall(b"ACCEPTED\n")
            else:
                client.sendall(b"REJECTED\n")
        except Exception:
            try: client.sendall(b"REJECTED\n")
            except Exception: pass
        finally: client.close()
    try: server.unlink(socket_path)
    except OSError: pass
threading.Thread(target=serve, daemon=True).start()
_, code = os.waitpid(child, 0)
# owner死后：worker-alive在且scope-killed不在 → 继续等待恢复路径停止worker（scope-killed出现）。
while not os.path.exists(os.path.join(directory, "scope-killed")) \
      and not os.path.exists(os.path.join(directory, "worker-stop-receipt")) \
      and os.path.exists(os.path.join(directory, "worker-alive")):
    time.sleep(0.02)
status.write(json.dumps({"schema_version": 1, "state": "terminated"}) + "\n"); status.flush()
status.close()
stopped.set()
sys.exit(128 + signal.SIGKILL)
'''


class FakeProcesses:
  """替身适配器：owner观察走受控序列；worker观察返回受控状态。"""
  def __init__(self, helper, directory, *, worker_states=("alive",), owner_states=None):
    self.helper = Path(helper)
    self.directory = Path(directory)
    self.worker_states = list(worker_states)
    self.owner_states = list(owner_states or [])

  def _owner_pid(self):
    try:
      row = json.loads((self.directory / "recovery-owner.json").read_text())
      return row["owner"]["pid"]
    except Exception:
      return None

  def observe(self, expected):
    pid = expected.get("pid") if isinstance(expected, dict) else None
    if pid is not None and pid == self._owner_pid():
      return self.owner_states.pop(0) if self.owner_states else "dead"
    if len(self.worker_states) > 1:
      return self.worker_states.pop(0)
    return self.worker_states[0]


class FakeRecover:
  def __init__(self, sequence):
    self.sequence = list(sequence)
    self.calls = []

  def __call__(self, args):
    self.calls.append((args.stop, args.expect_plan))
    action = self.sequence.pop(0)
    if action == "conflict": raise RECOVERY.Conflict("PI_RECOVERY_LIVE")
    if action == "plan": return None, {"plan_digest": "e" * 64}
    if action == "result":
      # 模拟带收据的worker停止：恢复路径完成，通知假helper退出等待循环。
      marker = Path(os.environ.get("FAKE_DIR", "/tmp")) / "worker-stop-receipt"
      try: marker.write_text("stop\n")
      except OSError: pass
      return None, {"protected": False, "state": "reclaimed"}


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
  # AF_UNIX路径上限108字节；pytest的tmp_path过长，改用短路径根。
  import shutil
  root = Path(tempfile.mkdtemp(prefix="/tmp/agentcfg-surrogate-"))
  directory = root / "case"
  directory.mkdir(parents=True)
  helper = directory / "fake-helper.py"
  helper.write_text(FAKE_HELPER)
  helper.chmod(0o755)
  project = directory / "project"; project.mkdir(mode=0o700)
  (project / "code.txt").write_text("original\n")
  case_dir = directory / "case-root"
  case_dir.mkdir(mode=0o700)
  (case_dir / "worker-alive").write_text("1\n")
  leases = directory / "state" / "activity" / "leases"
  leases.mkdir(mode=0o700, parents=True)
  (directory / "state" / "activity").chmod(0o700)
  (directory / "state").chmod(0o700)
  lease_path = leases / "lease-1.json"
  fd = os.open(lease_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
  os.write(fd, json.dumps({"grant_generation": 2}).encode()); os.close(fd)
  monkeypatch.setenv("FAKE_DIR", str(case_dir))
  monkeypatch.setattr(RECOVERY.secrets, "token_hex", lambda n: NONCE)
  monkeypatch.setattr(RECOVERY, "assert_inactive", lambda root: None)
  # 替身测试明确恢复进程控制：协议验证需要真实helper子进程生命周期。
  monkeypatch.setattr(RECOVERY.os, "kill", _REAL_OS_KILL)
  # helper控制通道验证需要真实unix socket（fake_owner_control_run使用本模块的socket引用）。
  monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
  capture = SimpleNamespace(threads=[], complete=lambda: True, attach=lambda p: None,
    results={"owner": {"failed": False}, "worker": {"failed": False}})
  yield directory, helper, capture, case_dir
  shutil.rmtree(root, ignore_errors=True)


def run_darwin_flow(directory, helper, capture, monkeypatch, processes, recover_sequence):
  fake = FakeRecover(recover_sequence)
  monkeypatch.setattr(RECOVERY, "recover", fake)
  # 返回 fake 以便测试检查调用记录
  case_socket = directory / "case-root" / "recovery-owner.sock"

  def fake_owner_control_run(argv, **kwargs):
    # 真实模拟 owner-control 客户端：连接helper socket发送OWNER动作。
    assert argv[1] == "owner-control", argv
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(5)
    deadline = time.time() + 5
    while True:
      try:
        client.connect(str(case_socket)); break
      except (FileNotFoundError, ConnectionRefusedError):
        if time.time() > deadline: raise
        time.sleep(0.05)
    client.sendall(f"OWNER {NONCE} 2\n".encode())
    reply = client.recv(16).decode()
    client.close()
    if reply != "ACCEPTED\n":
      return SimpleNamespace(returncode=4, stdout="")
    return SimpleNamespace(returncode=0, stdout="accepted\n")

  monkeypatch.setattr(RECOVERY.subprocess, "run", fake_owner_control_run)

  def fake_popen(argv, **kwargs):
    # argv: [helper, "supervise", sock, nfd, sfd, gfd, "--", owner...]
    # owner替换为长眠进程，保证OWNER动作时child仍存活（模拟真实owner等待中）。
    owner_replacement = [sys.executable, "-c", "import time; time.sleep(120)"]
    new_argv = [sys.executable, "-B", "-I", str(helper)] + argv[1:7] + owner_replacement
    import sys as _sys
    print(f"DEBUG fake_popen: sys.executable={sys.executable}, owner_replacement={owner_replacement}", file=_sys.stderr)
    kwargs["pass_fds"] = tuple(fd for fd in kwargs.get("pass_fds", ()) if fd > 2)
    kwargs["env"] = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
      "FAKE_DIR": os.environ.get("FAKE_DIR", str(directory)), "PYTHONDONTWRITEBYTECODE": "1"}
    kwargs["stderr"] = open(Path(kwargs["env"]["FAKE_DIR"]) / "helper-stderr.log", "wb")
    return _REAL_POPEN(new_argv, **kwargs)

  monkeypatch.setattr(RECOVERY.subprocess, "Popen", fake_popen)

  runtime = SimpleNamespace(root=directory / "runtime", profile="pi-default", identity="a" * 64,
    lock_identity="b" * 64, slice_identity="c" * 64, engine="node")
  fixture = {"workspace": SimpleNamespace(state_root=directory / "state",
    local_path=directory / "local.toml", instance=directory / "instance"),
    "project": directory / "project", "environment": {}}
  code = RECOVERY._run_recovery_case_darwin(fixture, runtime, {"nonce": NONCE},
    directory / "case-root" / "controller-result.json", {}, directory / "scripts",
    directory / "intent.json", {}, capture, processes_factory=lambda r, d: processes)
  return code, fake


def read_result(directory):
  return json.loads((directory / "case-root" / "controller-result.json").read_text())


def test_full_recovery_semantics_owner_dies_worker_survives(fake_env, monkeypatch):
  """完整流程：OWNER动作→owner死→worker仍活动→恢复路径显式停止→全部事实为真。"""
  directory, helper, capture, case_dir = fake_env
  processes = FakeProcesses(helper, case_dir, worker_states=("alive", "alive", "dead"), owner_states=["alive", "dead", "dead"])
  code, fake = run_darwin_flow(directory, helper, capture, monkeypatch, processes,
    ["conflict", "plan", "conflict", "result"])
  result = read_result(directory)
  facts = result["facts"]
  assert facts["live_owner_rejected"] is True
  assert facts["old_owner_dead"] is True
  assert facts["worker_survived_owner_death"] is True
  assert facts["wrong_plan_rejected"] is True
  assert facts["stop_only_recovery"] is True
  assert facts["target_terminated"] is True
  assert facts["source_preserved"] is True
  assert "darwin_approximate_implementation" not in facts, "近似标记必须已移除"
  assert result["status"] == "passed"
  assert code == 0
  # OWNER动作确实施行：整体scope-killed标记不存在
  assert not (case_dir / "scope-killed").exists()
  assert (case_dir / "owner-action").exists()
  # 恢复确实触发了worker停止（fake helper按scope-killed退出等待循环——
  # 本流程中worker停止由真实recover替身模拟，helper由finally清理终止）


def test_owner_alive_rejected_before_kill(fake_env, monkeypatch):
  directory, helper, capture, case_dir = fake_env
  processes = FakeProcesses(helper, case_dir, worker_states=("alive", "alive", "dead"), owner_states=["alive", "dead", "dead"])
  run_darwin_flow(directory, helper, capture, monkeypatch, processes,
    ["conflict", "plan", "conflict", "result"])
  assert read_result(directory)["facts"]["live_owner_rejected"] is True


def test_wrong_plan_rejected_and_verified_plan_used(fake_env, monkeypatch):
  directory, helper, capture, case_dir = fake_env
  processes = FakeProcesses(helper, case_dir, worker_states=("alive", "alive", "dead"), owner_states=["alive", "dead", "dead"])
  code, fake = run_darwin_flow(directory, helper, capture, monkeypatch, processes,
    ["conflict", "plan", "conflict", "result"])
  assert fake.calls[2] == (True, "0" * 64), "错误计划必须以全零摘要显式尝试并被拒"
  assert fake.calls[3] == (True, "e" * 64), "真实计划来自plan响应"


def test_unknown_not_treated_as_terminated(fake_env, monkeypatch):
  directory, helper, capture, case_dir = fake_env
  processes = FakeProcesses(helper, case_dir, worker_states=("alive", "alive", "unknown"), owner_states=["alive", "dead", "dead"])
  code, fake = run_darwin_flow(directory, helper, capture, monkeypatch, processes,
    ["conflict", "plan", "conflict", "result"])
  result = read_result(directory)
  assert result["facts"]["target_terminated"] is False
  assert result["status"] == "failed" and code != 0


def test_worker_premature_exit_fails_flow(fake_env, monkeypatch):
  directory, helper, capture, case_dir = fake_env
  processes = FakeProcesses(helper, case_dir, worker_states=("alive", "dead"), owner_states=["alive", "dead", "dead"])
  import pytest as _pytest
  from agentcfg.storage import Conflict as _Conflict
  with _pytest.raises(_Conflict):
    run_darwin_flow(directory, helper, capture, monkeypatch, processes,
      ["conflict", "plan", "conflict", "result"])


def test_source_preserved_check(fake_env, monkeypatch):
  directory, helper, capture, case_dir = fake_env
  (directory / "project" / "code.txt").write_text("tampered\n")
  processes = FakeProcesses(helper, case_dir, worker_states=("alive", "alive", "dead"), owner_states=["alive", "dead", "dead"])
  code, fake = run_darwin_flow(directory, helper, capture, monkeypatch, processes,
    ["conflict", "plan", "conflict", "result"])
  result = read_result(directory)
  assert result["facts"]["source_preserved"] is False
  assert result["status"] == "failed"


if __name__ == "__main__":
  pytest.main([__file__, "-v"])
