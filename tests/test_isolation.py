"""DSH-10：共享隔离设施的行为证据，不执行真实宿主。"""

import os
from pathlib import Path
import socket
import subprocess

import pytest


@pytest.mark.parametrize("name", [
  "HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
  "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMPDIR", "TMP", "TEMP",
])
def test_isolated_environment_paths(isolated_environment, name):
  path = Path(os.environ[name])
  assert path.is_dir()
  assert path.is_relative_to(isolated_environment.root)
  assert Path.cwd() == isolated_environment.cwd


def test_isolated_environment_does_not_copy_parent(isolated_environment, monkeypatch):
  monkeypatch.setenv("UNDECLARED_PARENT_SECRET", "synthetic-parent-canary")
  assert "UNDECLARED_PARENT_SECRET" not in isolated_environment.env
  assert set(isolated_environment.env) == {
    "HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "XDG_STATE_HOME", "TMPDIR", "TMP", "TEMP", "PATH",
    "PYTHONDONTWRITEBYTECODE", "PYTHONUTF8",
  }
  assert "ROTOM_PARENT_TEST_CANARY" not in os.environ
  # pytest 在 fixture setup 后写入当前测试名，不是父进程环境继承。
  assert set(os.environ) == set(isolated_environment.env) | {
    "UNDECLARED_PARENT_SECRET", "PYTEST_CURRENT_TEST",
  }


@pytest.mark.parametrize("attempt", [
  lambda: socket.socket(),
  lambda: socket.create_connection(("example.invalid", 443)),
  lambda: socket.getaddrinfo("example.invalid", 443),
  lambda: socket.gethostbyname("example.invalid"),
  lambda: socket.gethostbyname_ex("example.invalid"),
  lambda: socket.gethostbyaddr("192.0.2.1"),
  lambda: socket.getnameinfo(("192.0.2.1", 443), 0),
])
def test_default_network_guard_rejects_attempts(isolated_environment, attempt):
  with pytest.raises(RuntimeError, match="network disabled"):
    attempt()


@pytest.mark.parametrize("attempt", [
  lambda: subprocess.run(["dsh"]),
  lambda: subprocess.Popen(["codex"]),
  lambda: os.system("pi"),
  lambda: os.execv("dsh", ["dsh"]),
  lambda: os.execve("dsh", ["dsh"], {}),
  lambda: os.spawnv(os.P_WAIT, "dsh", ["dsh"]),
])
def test_default_process_guard_rejects_attempts(isolated_environment, attempt):
  with pytest.raises(RuntimeError, match="process disabled"):
    attempt()


@pytest.mark.parametrize("name", ["fork", "forkpty", "posix_spawn", "posix_spawnp"])
def test_platform_process_guards(isolated_environment, name):
  if not hasattr(os, name):
    pytest.skip("platform does not expose this process API")
  with pytest.raises(RuntimeError, match="process disabled"):
    getattr(os, name)()


def test_fake_subprocess_records_literal_inputs(fake_subprocess, isolated_environment, fake_catalog):
  argv = ["synthetic-host", "中文 空格", "", "$(touch forbidden)", "`false`", "a;b"]
  env = dict(isolated_environment.env, SELECTED_KEY=fake_catalog["secrets"]["selected"])
  fake_subprocess.queue(returncode=17, stdout="fixture output", stderr="fixture error")
  result = subprocess.run(argv, cwd=isolated_environment.cwd, env=env,
                          capture_output=True, text=True)
  assert (result.returncode, result.stdout, result.stderr) == (17, "fixture output", "fixture error")
  call = fake_subprocess.calls[0]
  assert call["argv"] == argv
  assert call["cwd"] == isolated_environment.cwd
  assert call["env"] == env
  assert fake_catalog["secrets"]["unused"] not in repr(call)
  argv.append("later mutation")
  env["SELECTED_KEY"] = "changed"
  assert call["argv"] != argv
  assert call["env"] != env
  assert not (Path.cwd() / "forbidden").exists()
  with pytest.raises(RuntimeError, match="process disabled"):
    subprocess.Popen(["dsh"])


def test_fake_subprocess_requires_explicit_result(fake_subprocess, isolated_environment):
  with pytest.raises(AssertionError, match="queued result"):
    subprocess.run(["synthetic-host"], cwd=isolated_environment.cwd,
                   env=isolated_environment.env)


@pytest.mark.parametrize("kwargs", [
  {"shell": True}, {"cwd": None}, {"env": None},
])
def test_fake_subprocess_rejects_implicit_or_shell_execution(fake_subprocess, isolated_environment, kwargs):
  options = {"cwd": isolated_environment.cwd, "env": isolated_environment.env, **kwargs}
  fake_subprocess.queue(returncode=0)
  with pytest.raises(AssertionError):
    subprocess.run(["synthetic-host"], **options)


def test_fake_subprocess_check_preserves_failure(fake_subprocess, isolated_environment):
  fake_subprocess.queue(returncode=23, stdout=b"out", stderr=b"err")
  with pytest.raises(subprocess.CalledProcessError) as error:
    subprocess.run(["synthetic-host"], cwd=isolated_environment.cwd,
                   env=isolated_environment.env, check=True, capture_output=True)
  assert error.value.returncode == 23
  assert error.value.output == b"out"
  assert error.value.stderr == b"err"


def test_fictitious_catalog_uses_only_synthetic_values(fake_catalog):
  assert fake_catalog["provider"]["base_url"] == "https://example.invalid/v1"
  assert fake_catalog["model"]["provider"] == fake_catalog["provider"]["id"]
  assert fake_catalog["model"]["remote_id"] == "synthetic-chat-not-a-real-model"
  assert fake_catalog["provider"]["credential_ref"] == "secret:selected"
  assert fake_catalog["secrets"]["selected"] != fake_catalog["secrets"]["unused"]
  assert all(char in fake_catalog["secrets"]["selected"] for char in ['"', "\n", "$()", "`"])


@pytest.mark.parametrize("change", ["write", "delete", "add", "mode", "symlink"])
def test_sentinel_detects_unexpected_changes(sentinel_factory, tmp_path, change):
  outside = tmp_path / "simulated outside"
  outside.mkdir()
  file = outside / "untouched"
  file.write_bytes(b"synthetic sentinel")
  sentinel = sentinel_factory(outside)
  sentinel.assert_unchanged()
  if change == "write":
    file.write_bytes(b"unexpected")
  elif change == "delete":
    file.unlink()
  elif change == "add":
    (outside / "unexpected").write_bytes(b"new")
  elif change == "mode":
    file.chmod(file.stat().st_mode ^ 0o100)
  else:
    file.unlink()
    file.symlink_to(tmp_path / "missing")
  with pytest.raises(AssertionError, match="sentinel changed"):
    sentinel.assert_unchanged()
