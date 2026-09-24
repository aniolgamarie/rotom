"""DSH-10：默认离线隔离；Python 级防护不是操作系统沙箱。"""

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import ssl  # 在 socket 替身安装前定义 SSLSocket；随后实际联网仍被阻断。
import signal
import stat
import subprocess
import sys
import tempfile

import pytest


_REAL_POPEN = subprocess.Popen
_ENTRY = Path(__file__).resolve().parents[1] / "agentcfg"


@dataclass
class IsolatedEnvironment:
  root: Path
  home: Path
  cwd: Path
  env: dict[str, str]


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
  previous_umask = os.umask(0o077)
  home = tmp_path / "home"
  cwd = tmp_path / "业务 中文 目录"
  paths = {
    "HOME": home,
    "DSH_HOME": home / "dsh",
    "PI_CODING_AGENT_DIR": home / "pi-agent",
    "PI_CODING_AGENT_SESSION_DIR": home / "pi-sessions",
    "CODEX_HOME": home / "codex",
    "XDG_CONFIG_HOME": home / "config",
    "XDG_DATA_HOME": home / "data",
    "XDG_CACHE_HOME": home / "cache",
    "XDG_STATE_HOME": home / "state",
    "TMPDIR": tmp_path / "tmp",
    "TMP": tmp_path / "tmp",
    "TEMP": tmp_path / "tmp",
    "PATH": tmp_path / "empty-bin",
  }
  for path in paths.values():
    path.mkdir(parents=True, exist_ok=True)
  cwd.mkdir()
  env = {name: str(path) for name, path in paths.items()}
  env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
  # 不从父进程挑秘密名称黑名单，直接使用全新的有限环境。
  for name in list(os.environ):
    monkeypatch.delenv(name)
  for name, value in env.items():
    monkeypatch.setenv(name, value)
  monkeypatch.setattr(tempfile, "tempdir", str(paths["TMPDIR"]))
  monkeypatch.chdir(cwd)
  try:
    yield IsolatedEnvironment(tmp_path, home, cwd, env)
  finally:
    os.umask(previous_umask)


@pytest.fixture(autouse=True)
def offline_guards(isolated_environment, monkeypatch):
  def no_network(*args, **kwargs):
    raise RuntimeError("test network disabled")

  def no_process(*args, **kwargs):
    raise RuntimeError("test process disabled")

  for name in (
    "socket", "SocketType", "create_connection", "getaddrinfo", "gethostbyname",
    "gethostbyname_ex", "gethostbyaddr", "getnameinfo", "socketpair", "fromfd",
  ):
    if hasattr(socket, name):
      monkeypatch.setattr(socket, name, no_network)
  monkeypatch.setattr(subprocess, "Popen", no_process)
  for name in (
    "system", "fork", "forkpty", "posix_spawn", "posix_spawnp",
    "kill", "killpg", "pidfd_open",
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
  ):
    if hasattr(os, name):
      monkeypatch.setattr(os, name, no_process)
  if hasattr(signal, "pidfd_send_signal"):
    monkeypatch.setattr(signal, "pidfd_send_signal", no_process)


class FileSentinel:
  def __init__(self, root):
    self.root = root
    self.before = self.snapshot()

  def snapshot(self):
    result = {}

    def visit(path):
      info = path.lstat()
      value = None
      if stat.S_ISREG(info.st_mode):
        # 不受业务测试对 Path.open 的故障注入影响。
        with open(path, "rb") as file:
          value = file.read()
      elif stat.S_ISLNK(info.st_mode):
        value = os.readlink(path)
      result[path.relative_to(self.root)] = (
        info.st_mode, info.st_mtime_ns, info.st_ino, value,
      )
      if stat.S_ISDIR(info.st_mode):
        for child in path.iterdir():
          visit(child)

    if self.root.exists() or self.root.is_symlink():
      visit(self.root)
    return result

  def assert_unchanged(self):
    # 不把哨兵正文或私有路径带入断言输出。
    if self.snapshot() != self.before:
      raise AssertionError("test file sentinel changed")


@pytest.fixture
def sentinel_factory():
  return FileSentinel


@pytest.fixture(autouse=True)
def outside_sentinels(isolated_environment, sentinel_factory):
  # 只模拟外部目录，绝不遍历或读取真实 HOME。
  outside = isolated_environment.root / "outside-managed-targets"
  outside.mkdir()
  (outside / "untouched").write_bytes(b"synthetic outside sentinel\n")
  native = isolated_environment.home / "oauth-sentinel"
  native.write_bytes(b"synthetic native sentinel\n")
  sentinels = [sentinel_factory(outside), sentinel_factory(native)]
  yield sentinels
  for sentinel in sentinels:
    sentinel.assert_unchanged()


@pytest.fixture
def fake_catalog():
  # 虚构资料不是完整 schema，也不是生产服务配方。
  return {
    "provider": {
      "id": "synthetic-provider", "base_url": "https://example.invalid/v1",
      "protocol": "openai-compatible", "credential_ref": "secret:selected",
    },
    "model": {
      "id": "synthetic-model", "provider": "synthetic-provider",
      "remote_id": "synthetic-chat-not-a-real-model",
    },
    "secrets": {
      "selected": 'synthetic-selected-"\n$()`false`',
      "unused": 'synthetic-unused-"\n$()`false`',
    },
  }


class FakeSubprocess:
  def __init__(self):
    self.calls = []
    self.results = deque()

  def queue(self, *, returncode, stdout=None, stderr=None):
    self.results.append((returncode, stdout, stderr))

  def run(self, argv, *, cwd=None, env=None, shell=False, check=False,
          capture_output=False, text=False, encoding=None, timeout=None, pass_fds=()):
    # 只模拟 run 的明确输入；不回退到真实进程，也不默认返回成功。
    assert isinstance(argv, (list, tuple)) and argv, "explicit argv required"
    assert not shell, "shell execution forbidden"
    assert cwd is not None and env is not None, "explicit cwd and env required"
    assert self.results, "fake subprocess requires a queued result"
    copied_argv = list(argv)
    self.calls.append({"argv": copied_argv, "cwd": cwd, "env": dict(env)})
    assert isinstance(pass_fds, tuple) and all(isinstance(fd, int) and os.fstat(fd) for fd in pass_fds)
    if pass_fds:
      self.calls[-1]["pass_fds"] = pass_fds
    returncode, stdout, stderr = self.results.popleft()
    result = subprocess.CompletedProcess(copied_argv, returncode, stdout, stderr)
    if check:
      result.check_returncode()
    return result


@pytest.fixture
def fake_subprocess(offline_guards, monkeypatch):
  fake = FakeSubprocess()
  monkeypatch.setattr(subprocess, "run", fake.run)
  return fake


@pytest.fixture
def prepared_runtime():
  """有完整收据的虚构安装包，不执行第三方代码。"""
  from agentcfg.runtime_packages import REQUIRED_FILES, seal
  from agentcfg.storage import ensure_private
  def prepare(workspace, lock):
    root = workspace.backend.root(workspace, lock.identity)
    ensure_private(root)
    for name in REQUIRED_FILES:
      target = root / name
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_bytes(lock.package if name == "package.json" else lock.resolution if name == "package-lock.json" else b"synthetic installed artifact\n")
    seal(root, lock.identity)
    return root
  return prepare


@pytest.fixture
def entry_python(request, isolated_environment, offline_guards):
  """仅为 test_entry 的临时入口副本开口，不恢复全局 Popen。"""
  instance = request.instance
  assert instance is not None and request.node.path.name == "test_entry.py"

  def run(command, *, cwd, env, capture_output, text, encoding, timeout):
    command = [os.fspath(part) for part in command]
    entry = instance.entry
    base = Path(sys._base_executable).resolve()
    python = instance.repo / ".venv/bin/python"
    assert entry.is_relative_to(isolated_environment.root)
    assert entry.read_bytes() == _ENTRY.read_bytes(), "only the copied entry is allowed"
    assert Path(cwd) == instance.cwd
    assert env == instance.env
    assert set(env) == {
      "PATH", "HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
      "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR", "PYTHONPATH",
      "PYTHONDONTWRITEBYTECODE", "PYTHONUTF8", "EXPECTED_VENV_PYTHON",
    }
    assert env["EXPECTED_VENV_PYTHON"] == str(python)
    assert env["PYTHONPATH"] == str(instance.root / "guard")
    assert (Path(env["PYTHONPATH"]) / "sitecustomize.py").is_file()
    assert (Path(env["PATH"]) / "python3").resolve() == base
    if command[0] != str(entry):
      assert command[0] in (str(base), str(python)), "only entry Python is allowed"
      assert Path(command[0]).resolve() == base
      assert command[1] == str(entry), "only the entry script is allowed"
    assert capture_output and text and encoding == "utf-8" and 0 < timeout <= 10
    # 使用预先保存的单个入口，不给测试恢复通用的进程执行权限。
    with _REAL_POPEN(command, cwd=cwd, env=dict(env), stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=text, encoding=encoding) as process:
      try:
        stdout, stderr = process.communicate(timeout=timeout)
      except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
      return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

  instance.entry_runner = run
