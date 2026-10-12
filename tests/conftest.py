"""DSH-10：默认离线隔离；Python 级防护不是操作系统沙箱。"""

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import pwd
import socket
import ssl  # 在 socket 替身安装前定义 SSLSocket；随后实际联网仍被阻断。
import signal
import stat
import subprocess
import sys
import tempfile

import pytest


@pytest.fixture
def fake_terminal_commands(isolated_environment):
  """仅供 termcfg 隔离测试识别，不执行真实 zsh/tmux。"""
  directory = isolated_environment.root / "empty-bin"
  for name in ("zsh", "tmux", "fzf"):
    path = directory / name
    path.write_text("#!/bin/sh\nexit 99\n")
    path.chmod(0o700)
  return directory


_REAL_POPEN = subprocess.Popen
_REAL_KILL = os.kill
_ENTRY = Path(__file__).resolve().parents[1] / "agentcfg"
_LEASE_WORKER = Path(__file__).resolve().parent / "fixtures/pi/workspace-lease-worker.py"
_LEASE_SCENARIOS = ("reserve", "hold-lock", "exit-before-commit", "exit-after-reserved")


def pytest_addoption(parser):
  parser.addoption("--run-pi-lease-os", action="store_true", default=False, help="Run isolated synthetic Pi lease worker processes")
  group = parser.getgroup("omp-permission-control")
  group.addoption("--omp-standalone-bun", default=None,
    help="Explicit locked Bun executable for current standalone and official SDK tests")
  # 兼容历史调用参数；补丁fixture 始终退休跳过，绝不消费这些材料。
  for name in ("omp-build-source", "omp-tool-cache", "omp-dependency-cache"):
    group.addoption("--" + name, default=None, help="Retired host-patch test input (ignored)")


def pytest_collection_modifyitems(config, items):
  if not config.getoption("run_pi_lease_os"):
    skipped = pytest.mark.skip(reason="synthetic OS lease workers require --run-pi-lease-os")
    for item in items:
      if item.get_closest_marker("pi_lease_os") is not None:
        item.add_marker(skipped)


@pytest.fixture(scope="session")
def omp_permission_materials():
  pytest.skip("historical OMP host-patch integration retired; standalone plugin tests are current evidence")


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
  # OS 账户home独立于profile HOME；默认测试不得经passwd绕回真实账户目录。
  account_home = tmp_path / "os-account"
  account_home.mkdir(mode=0o700)
  account = pwd.struct_passwd(("synthetic-account", "x", os.geteuid(), os.getegid(), "", str(account_home), ""))
  def account_by_uid(uid):
    if uid != account.pw_uid: raise KeyError("test account not declared")
    return account
  def account_by_name(name):
    if name != account.pw_name: raise KeyError("test account not declared")
    return account
  monkeypatch.setattr(pwd, "getpwuid", account_by_uid)
  monkeypatch.setattr(pwd, "getpwnam", account_by_name)
  monkeypatch.setattr(pwd, "getpwall", lambda: [account])
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


class LeaseWorkerHandle:
  """只管理 fixture 已登记的固定 worker；不暴露通用命令入口。"""
  def __init__(self, process, case):
    self._process, self.case = process, case
    self._pid = process.pid

  @property
  def pid(self):
    return self._pid

  def poll(self):
    return self._process.poll()

  def stop(self):
    if self.poll() is None: (self.case / "stop").touch()

  def crash(self):
    # 仅杀此fixture持有的自有child；不接收PID/信号，不恢复全局kill。
    if self._process.pid != self._pid: raise ValueError("fixed worker process required")
    if self.poll() is None: _REAL_KILL(self._pid, signal.SIGKILL)

  def wait(self, *, timeout=5):
    if not 0 < timeout <= 10: raise ValueError("bounded worker wait required")
    return self._process.wait(timeout=timeout)


@pytest.fixture
def pi_lease_worker(request, tmp_path, isolated_environment, offline_guards):
  """唯一开放固定自有 worker；全局 Popen/fork/network 防护始终保留。"""
  from types import SimpleNamespace
  import json
  handles = []

  def start(case, scenario):
    case = Path(case)
    if scenario not in _LEASE_SCENARIOS or not case.is_absolute() or case.parent != tmp_path or case.is_symlink() or not case.is_dir() or case.resolve() != case:
      raise ValueError("fixed worker case/scenario required")
    document = case / "case.json"
    if document.is_symlink() or not document.is_file() or document.stat().st_nlink != 1:
      raise ValueError("regular worker case required")
    try:
      config = json.loads(document.read_bytes())
      if not isinstance(config, dict) or set(config) != {"role", "workspace"} or config["role"] not in ("one", "two", "holder", "probe") or config["role"] != case.name:
        raise ValueError()
      workspace = Path(config["workspace"])
      if not workspace.is_absolute() or not workspace.resolve(strict=True).is_relative_to(tmp_path) or not workspace.is_dir(): raise ValueError()
      canonical = workspace.resolve(strict=True)
      while not (canonical / ".git").exists():
        if canonical == tmp_path: raise ValueError()
        canonical = canonical.parent
      marker = canonical / ".git"
      if marker.is_symlink(): raise ValueError()
      git_dir = marker
      if marker.is_file():
        if marker.stat().st_nlink != 1: raise ValueError()
        text = marker.read_text()
        if not text.startswith("gitdir: ") or text.count("\n") != 1: raise ValueError()
        git_dir = (canonical / text[8:].strip()).resolve(strict=True)
        if not git_dir.is_relative_to(tmp_path): raise ValueError()
        if (git_dir / "gitdir").is_symlink() or (git_dir / "commondir").is_symlink(): raise ValueError()
        if (git_dir / (git_dir / "gitdir").read_text().strip()).resolve(strict=True) != marker: raise ValueError()
        if not (git_dir / (git_dir / "commondir").read_text().strip()).resolve(strict=True).is_relative_to(tmp_path): raise ValueError()
      if not git_dir.is_dir() or (git_dir / "HEAD").is_symlink() or (git_dir / "HEAD").read_bytes() != b"ref: refs/heads/fixture\n": raise ValueError()
      account_home = tmp_path / "os-account"
      if account_home.is_symlink() or not account_home.is_dir() or account_home.resolve() != account_home or account_home.stat().st_uid != os.geteuid() or account_home.stat().st_mode & 0o777 != 0o700: raise ValueError()
      if any((case / name).is_symlink() for name in ("ready", "go", "stop", "exit", "active.json", "result.json", "persisted")): raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
      raise ValueError("worker workspace must stay within test case") from None
    if not request.config.getoption("run_pi_lease_os") or request.node.get_closest_marker("pi_lease_os") is None or request.node.path.name != "test_pi_workspace_leases_os.py":
      raise RuntimeError("synthetic worker requires explicit opt-in marker")
    if _LEASE_WORKER.is_symlink() or not _LEASE_WORKER.is_file() or _LEASE_WORKER.resolve() != _LEASE_WORKER:
      raise ValueError("fixed repository worker required")
    env = {}
    for key, directory in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("TMPDIR", "tmp"), ("PATH", "empty-bin")):
      path = case / directory
      if path.is_symlink(): raise ValueError("worker environment path must stay in case")
      path.mkdir(exist_ok=True); env[key] = str(path)
    env.update(LC_ALL="C.UTF-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-I", str(_LEASE_WORKER), str(case), scenario]
    process = _REAL_POPEN(command, cwd=case, env=env, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    handle = LeaseWorkerHandle(process, case); handles.append(handle)
    return handle

  yield SimpleNamespace(start=start, handles=handles)
  for handle in handles:
    if handle.poll() is None:
      handle.stop()
      try: handle.wait(timeout=2)
      except subprocess.TimeoutExpired:
        # 仅超时清理本 fixture 登记且仍存活的子进程；不触碰任何宿主进程。
        if handle.poll() is None:
          try: _REAL_KILL(handle.pid, signal.SIGTERM)
          except ProcessLookupError: pass
        try: handle.wait(timeout=2)
        except subprocess.TimeoutExpired:
          if handle.poll() is None:
            try: _REAL_KILL(handle.pid, signal.SIGKILL)
            except ProcessLookupError: pass
          handle.wait(timeout=2)
    handle._process.stdout.close(); handle._process.stderr.close()


@pytest.fixture
def pi_non_git_worker(request, tmp_path, isolated_environment, offline_guards):
  """只开放固定非Gitworker的bwrap入口；保留全局进程/联网守卫。"""
  import importlib.util
  from types import SimpleNamespace
  worker = Path(__file__).resolve().parent / "fixtures/pi/non-git-workspace-worker.py"
  spec = importlib.util.spec_from_file_location("fixed_non_git_worker", worker)
  protocol = importlib.util.module_from_spec(spec); spec.loader.exec_module(protocol)
  handles = []

  def start(case, scenario):
    if not request.config.getoption("run_pi_lease_os") or request.node.get_closest_marker("pi_lease_os") is None or request.node.path.name != "test_pi_non_git_workspaces_os.py":
      raise RuntimeError("fixed non-Git worker requires explicit opt-in")
    if worker.is_symlink() or worker.resolve() != worker or not worker.is_file(): raise ValueError("fixed worker required")
    command = protocol.invocation(case, tmp_path, scenario, sys.executable)
    process = _REAL_POPEN(command, cwd=case, env={}, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    handle = LeaseWorkerHandle(process, Path(case)); handles.append(handle)
    return handle

  yield SimpleNamespace(start=start, handles=handles)
  for handle in handles:
    if handle.poll() is None:
      handle.stop()
      try: handle.wait(timeout=2)
      except subprocess.TimeoutExpired:
        if handle.poll() is None:
          try: _REAL_KILL(handle.pid, signal.SIGTERM)
          except ProcessLookupError: pass
        try: handle.wait(timeout=2)
        except subprocess.TimeoutExpired:
          if handle.poll() is None:
            try: _REAL_KILL(handle.pid, signal.SIGKILL)
            except ProcessLookupError: pass
          handle.wait(timeout=2)
    handle._process.stdout.close(); handle._process.stderr.close()
