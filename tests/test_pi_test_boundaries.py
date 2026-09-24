"""Pi 默认测试必须只接触临时目录与替身。"""

import os
from pathlib import Path
import socket
import subprocess

import pytest


def test_native_homes_are_isolated(isolated_environment):
  for name in ("HOME", "DSH_HOME", "PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR", "CODEX_HOME"):
    assert Path(os.environ[name]).is_relative_to(isolated_environment.home)


def test_network_and_real_hosts_are_rejected():
  with pytest.raises(RuntimeError, match="network disabled"):
    socket.create_connection(("example.invalid", 443))
  for command in ("pi", "dsh", "codex"):
    with pytest.raises(RuntimeError, match="process disabled"):
      subprocess.run([command, "--version"])


def test_fake_process_requires_an_explicit_result(fake_subprocess, isolated_environment):
  with pytest.raises(AssertionError, match="queued result"):
    fake_subprocess.run(["synthetic-host"], cwd=isolated_environment.cwd, env=isolated_environment.env)


def test_private_sentinel_detects_mutation(tmp_path, sentinel_factory):
  root = tmp_path / "native-sentinel"
  root.mkdir()
  marker = root / "auth.json"
  marker.write_text("synthetic private sentinel")
  sentinel = sentinel_factory(root)
  marker.write_text("modified")
  with pytest.raises(AssertionError, match="sentinel changed"):
    sentinel.assert_unchanged()


def test_default_tests_cannot_send_signals_or_open_real_pidfds():
  with pytest.raises(RuntimeError, match="process disabled"):
    os.kill(os.getpid(), 0)
  if hasattr(os, "pidfd_open"):
    with pytest.raises(RuntimeError, match="process disabled"):
      os.pidfd_open(os.getpid())
