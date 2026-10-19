"""公共命令消费不透明原生锁；假后端/假运行环境，不安装或启动宿主。"""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agentcfg import cli, commands, runtime
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError


class FakeBackend:
  def __init__(self, native_lock):
    self.lock = SimpleNamespace(identity="synthetic-lock", metadata=native_lock)
    self.calls = []
    self.lock_error = None
    self.sync_error = None
    self.package_status = "installed"

  def read_lock(self, repository):
    self.calls.append(("read_lock", repository))
    if self.lock_error:
      raise self.lock_error
    return self.lock

  def resolve_lock(self, repository):
    pytest.fail("未显式 lock 时不得解析来源或重锁")

  def sync(self, workspace, lock):
    self.calls.append(("sync", lock))
    assert lock is self.lock
    if self.sync_error:
      raise self.sync_error
    pytest.fail("本测试没有授权成功安装或激活")

  def root(self, workspace, identity):
    self.calls.append(("root", identity))
    return workspace.instance / "runtimes" / identity

  def status(self, workspace, identity):
    self.calls.append(("status", identity))
    return self.package_status

  def executable_paths(self, root):
    pytest.fail("依赖检查失败后不得准备可执行路径")

  def toolchain(self, lock):
    pytest.fail("失败路径不得继续探测工具链")


@pytest.fixture(params=[
  pytest.param({"installer": "pnpm", "resolution": {"importers": {}}}, id="package-lock"),
  pytest.param({"assets": {"synthetic-platform": {"sha256": "a" * 64}}}, id="asset-lock"),
  pytest.param({"npm": {"lockfileVersion": 3, "packages": {}}, "resources": []}, id="npm-lock"),
])
def backend_workspace(tmp_path, monkeypatch, request):
  backend = FakeBackend(deepcopy(request.param))
  candidates = []
  def candidate(identity):
    candidates.append(identity)
    return SimpleNamespace(artifacts=())
  workspace = SimpleNamespace(repository=tmp_path / "repository", backend=backend,
    instance=tmp_path / "instance", state_root=tmp_path / "state", cache=tmp_path / "cache",
    agent="synthetic", profile="synthetic-profile", binding={"profile": "synthetic-profile"},
    resolved=SimpleNamespace(data={"machine": {}}, validated_profiles=1), candidate=candidate,
    adapter=SimpleNamespace(), secret_store=SimpleNamespace(resolve=lambda *a, **k: pytest.fail("不得读取秘密")))
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  # 只替换选择元数据读取；保留真实parser、dispatch及异常退出码映射。
  def select(args):
    args.local = tmp_path / "synthetic-local.toml"
    args.profile = workspace.profile
    if args.command == "run":
      args.cwd = tmp_path
  monkeypatch.setattr(cli, "resolve_selection", select)
  return workspace, backend, candidates


@pytest.mark.parametrize("command", ["validate", "render", "plan", "apply", "sync"])
@pytest.mark.parametrize("reason", ["missing", "source-mismatch"])
def test_lock_failure_is_exit_two_before_render_or_install(backend_workspace, command, reason,
    tmp_path, sentinel_factory):
  workspace, backend, candidates = backend_workspace
  backend.lock_error = ConfigError("synthetic-lock-" + reason)
  sentinel = sentinel_factory(tmp_path)

  assert cli.main([command]) == cli.EXIT_USAGE == 2

  assert backend.calls == [("read_lock", workspace.repository)]
  assert candidates == []
  sentinel.assert_unchanged()


def test_validate_passes_complete_native_lock_identity_without_reformatting(backend_workspace):
  workspace, backend, candidates = backend_workspace
  native = deepcopy(backend.lock.metadata)

  assert cli.main(["validate"]) == 0

  assert candidates == [backend.lock.identity]
  assert backend.lock.metadata == native
  assert backend.calls == [("read_lock", workspace.repository)]


def test_sync_content_failure_is_exit_five_and_preserves_existing_files(backend_workspace,
    tmp_path, sentinel_factory):
  workspace, backend, candidates = backend_workspace
  # 合成原生home/旧包/备份哨兵，不读取真实账号或会话。
  for name in ("native-home/untouched", "active-package/body", "previous-config/body"):
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic existing content\n")
  sentinel = sentinel_factory(tmp_path)
  backend.sync_error = DependencyError("synthetic staged content verification failed")

  assert cli.main(["sync"]) == cli.EXIT_DEPS == 5

  assert backend.calls == [("read_lock", workspace.repository), ("sync", backend.lock)]
  assert candidates == []
  sentinel.assert_unchanged()


class FakeTree:
  def __init__(self, *args, **kwargs):
    pass

  def __enter__(self):
    return self

  def __exit__(self, *args):
    pass

  def read(self, path):
    assert path == "pending.json"
    return None


@pytest.mark.parametrize("status", ["missing", "damaged"])
def test_run_rejects_deployed_package_before_credentials_or_spawn(backend_workspace,
    monkeypatch, tmp_path, sentinel_factory, status):
  workspace, backend, candidates = backend_workspace
  backend.package_status = status
  # 不模拟安装器或生命周期；这里只隔离存储，检查真实run的依赖失败顺序。
  contract = {"machine": {}, "lock_identity": "deployed-native-lock",
    "runtime_identity": "deployed-platform-runtime", "runtime_guards": {"files": [], "roots": []}}
  monkeypatch.setattr(runtime, "Tree", FakeTree)
  monkeypatch.setattr(runtime, "instance_lock", lambda *a, **k: nullcontext())
  monkeypatch.setattr(runtime, "read_state", lambda tree: {
    "current": {"binding": workspace.binding, "launch": contract, "items": {}}})
  monkeypatch.setattr(runtime, "prepare_environment", lambda *a, **k: pytest.fail("依赖缺损后不得准备启动环境"))
  monkeypatch.setattr(runtime, "checked", lambda *a, **k: pytest.fail("依赖缺损后不得执行preflight"))
  monkeypatch.setattr(backend, "read_lock", lambda *a: pytest.fail("run只能消费已部署身份，不读取或更新当前锁"))
  sentinel = sentinel_factory(tmp_path)

  assert cli.main(["run"]) == cli.EXIT_DEPS == 5

  assert backend.calls == [("root", "deployed-platform-runtime"), ("status", "deployed-platform-runtime")]
  assert candidates == []
  sentinel.assert_unchanged()


def test_runtime_identity_keeps_backend_platform_identity_separate(backend_workspace, monkeypatch):
  workspace, backend, _ = backend_workspace
  assert runtime.runtime_identity(workspace, backend.lock) == backend.lock.identity
  monkeypatch.setattr(backend, "runtime_identity", lambda w, lock: "synthetic-platform-runtime", raising=False)

  assert runtime.runtime_identity(workspace, backend.lock) == "synthetic-platform-runtime"
  assert backend.lock.identity == "synthetic-lock"
