"""默认验收只测授权及封闭代理边界，不启动宿主或网络。"""

import importlib.util
import io
from pathlib import Path
import socket
import subprocess
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]


def entry():
  spec = importlib.util.spec_from_file_location("device_smoke", ROOT / "scripts/smoke-dsh-codex-device.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_default_entry_cannot_launch_host_or_open_network(tmp_path, monkeypatch):
  def forbidden(*_args, **_kwargs):
    pytest.fail("默认入口不得启动子进程或网络")
  monkeypatch.setattr(subprocess, "Popen", forbidden)
  monkeypatch.setattr(socket, "socket", forbidden)
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as error:
    entry().main(["--runtime", str(tmp_path / "absent"), "--evidence", str(evidence)])
  assert error.value.code == 2
  assert not evidence.exists()


def test_unsealed_runtime_fails_before_fixture_creation(tmp_path, monkeypatch):
  from types import SimpleNamespace
  from agentcfg import dependencies, runtime_packages
  def forbidden(*_args, **_kwargs):
    pytest.fail("失效运行包不得启动子进程或网络")
  monkeypatch.setattr(subprocess, "Popen", forbidden)
  monkeypatch.setattr(socket, "socket", forbidden)
  monkeypatch.setattr(dependencies, "read_lock", lambda _repo: SimpleNamespace(identity="fixture"))
  monkeypatch.setattr(runtime_packages, "status", lambda _root, _identity: "damaged")
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as error:
    entry().main(["--allow-host", "--runtime", str(tmp_path / "absent"), "--evidence", str(evidence)])
  assert error.value.code == 2
  assert not evidence.exists()


@pytest.mark.parametrize("connect_line", [
  b"CONNECT example.com:443 HTTP/1.1\r\n",
  b"CONNECT auth.openai.com:80 HTTP/1.1\r\n",
  b"GET https://auth.openai.com/ HTTP/1.1\r\n",
])
def test_fixture_proxy_rejects_unknown_destinations_without_forwarding(connect_line, monkeypatch):
  module = entry()
  def forbidden(*_args, **_kwargs):
    pytest.fail("代理不得创建任何上游连接")
  monkeypatch.setattr(socket, "socket", forbidden)
  proxy = object.__new__(module.DeviceProxy)
  proxy.lock = threading.Lock()
  proxy.counts = {"connect": 0, "rejected_connect": 0, "unexpected": 0}
  class Connection:
    response = b""
    def settimeout(self, _timeout):
      pass
    def makefile(self, _mode):
      return io.BytesIO(connect_line)
    def sendall(self, body):
      self.response += body
  connection = Connection()
  proxy.handle(connection)
  assert connection.response.startswith(b"HTTP/1.1 403 Forbidden")
  assert proxy.counts == {"connect": 1, "rejected_connect": 1, "unexpected": 0}
