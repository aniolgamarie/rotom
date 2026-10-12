"""控制专用held目录与handoff；只自有文件/fake exec，绝不操作pytest fd3。"""
import array
import importlib.util
import json
import os
from pathlib import Path
import socket
import stat
from types import SimpleNamespace
import pytest
from agentcfg.pi_control import _HeldControlDirectory
from agentcfg.storage import Conflict
from agentcfg.pi_supervisor import SupervisorServer


def load_gate():
  path = Path(__file__).resolve().parents[1] / "scripts/pi-namespace-exec.py"
  spec = importlib.util.spec_from_file_location("control_gate_fixture", path)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  return module


def test_held_directory_reads_only_control_and_preserves_original_file_guards(tmp_path):
  root = tmp_path / "control"; root.mkdir(mode=0o700)
  target = root / "control.json"; target.write_bytes(b"fixture\n"); target.chmod(0o600)
  fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
  try:
    with _HeldControlDirectory(fd) as held:
      assert held.read("control.json")[0] == b"fixture\n"
      with pytest.raises(Conflict): held.read("../secret")
      target.unlink(); target.symlink_to(tmp_path / "foreign")
      with pytest.raises(Conflict): held.read("control.json")
    assert os.fstat(fd).st_ino == root.stat().st_ino
    assert os.get_inheritable(fd) is False
  finally: os.close(fd)


@pytest.mark.parametrize("kind", ["file", "mode", "closed"])
def test_wrong_directory_descriptor_fails_closed(tmp_path, kind):
  if kind == "file":
    path = tmp_path / "file"; path.write_text("fixture"); fd = os.open(path, os.O_RDONLY)
  else:
    path = tmp_path / "dir"; path.mkdir(mode=0o755 if kind == "mode" else 0o700)
    if kind == "mode": path.chmod(0o755)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
  if kind == "closed": os.close(fd)
  try:
    with pytest.raises(Conflict): _HeldControlDirectory(fd)
  finally:
    if kind != "closed": os.close(fd)


@pytest.mark.parametrize("fault", [None, "extra", "truncated", "eof", "file", "mode"])
def test_gate_accepts_exactly_one_private_directory_and_closes_rejected_rights(tmp_path, fault, monkeypatch):
  module = load_gate(); root = tmp_path / "dir"; root.mkdir(mode=0o755 if fault == "mode" else 0o700)
  if fault == "mode": root.chmod(0o755)
  if fault == "file": root = tmp_path / "file"; root.write_text("fixture")
  descriptors = [os.open(root, os.O_RDONLY)]
  if fault == "extra": descriptors.append(os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY))
  reply = (b"" if fault == "eof" else b"G", [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", descriptors).tobytes())],
    socket.MSG_CTRUNC if fault == "truncated" else 0, None)
  gate = SimpleNamespace(recvmsg=lambda *args: reply)
  if fault:
    with pytest.raises((ValueError, OSError)): module.receive_control_directory(gate)
    for fd in descriptors:
      with pytest.raises(OSError): os.fstat(fd)
  else:
    fd = module.receive_control_directory(gate)
    assert os.fstat(fd).st_ino == root.stat().st_ino
    os.close(fd)


def test_server_retires_held_directory_even_when_socket_close_raises(tmp_path, monkeypatch):
  import threading
  fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
  info = os.fstat(fd)
  server = object.__new__(SupervisorServer)
  server._directory_fd = fd; server._directory_identity = (info.st_dev, info.st_ino, info.st_uid, info.st_mode)
  server.stopping = threading.Event(); server.service = SimpleNamespace(closing=False)
  duplicate = server.duplicate_control_directory(); os.close(duplicate)
  def failed_close(): raise OSError("synthetic-close")
  monkeypatch.setattr(server, "_close_socket", failed_close)
  with pytest.raises(OSError): server.close()
  assert server._directory_fd is None
  with pytest.raises(OSError): os.fstat(fd)
  with pytest.raises(Conflict): server.duplicate_control_directory()


def test_direct_worker_eof_closes_passed_directory_without_mapping_fd3(tmp_path, monkeypatch):
  path = Path(__file__).resolve().parents[1] / "scripts/pi-exec.py"
  spec = importlib.util.spec_from_file_location("direct_control_gate", path)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  read, write = os.pipe(); os.close(write)
  directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
  monkeypatch.setattr(module.sys, "argv", ["pi-exec.py", "--gate-fd", str(read), "--control-directory-fd", str(directory), "--", "synthetic"])
  monkeypatch.setattr(module, "os", SimpleNamespace(read=os.read, close=os.close,
    dup2=lambda *args: pytest.fail("canceled gate mapped fd3"), execvpe=lambda *args: pytest.fail("canceled gate executed")))
  assert module.main() == 125
  with pytest.raises(OSError): os.fstat(directory)


def test_python_control_incoming_fd_is_cloexec_for_business_exec(tmp_path):
  fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY); os.set_inheritable(fd, True)
  try:
    with _HeldControlDirectory(fd): assert os.get_inheritable(fd) is False
    assert os.get_inheritable(fd) is False
  finally: os.close(fd)
