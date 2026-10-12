"""现代 source caller 默认接线；同进程 flock，不证明长期 SourceHold。"""

import fcntl
import os
from types import SimpleNamespace

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi import PiAdapter
from agentcfg.pi_dependencies import PiBackend
from agentcfg.pi_source_latch import source_latch
from agentcfg.storage import Conflict, Tree, instance_lock
import agentcfg.pi_lifecycle as lifecycle


@pytest.fixture
def workspace(tmp_path):
  instance = tmp_path / "instance"
  instance.mkdir(mode=0o700)
  state = tmp_path / "state"
  state.mkdir(mode=0o700)
  for directory, name in [(instance, "auth.json"), (instance, "session.json"), (state, "state.json")]:
    (directory / name).write_bytes(b"synthetic existing sentinel")
    (directory / name).chmod(0o600)
  return SimpleNamespace(instance=instance, state_root=state, profile="pi-base", repository=tmp_path)


def marker(workspace):
  return json_bytes({"schema_version": 1, "state_root": str(workspace.state_root),
    "binding": getattr(workspace, "binding", {"profile": workspace.profile})})


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_actual_adapter_hooks_share_source_but_keep_lifecycle_exclusive(workspace, profile):
  workspace.profile = profile
  adapter = PiAdapter(workspace.repository)
  with source_latch(workspace, shared=True, create=True):
    with pytest.raises(Conflict):
      with adapter.lifecycle_guard(workspace):
        pytest.fail("mutator ignored SH")
    with adapter.run_lifecycle_guard(workspace) as fd:
      assert os.fstat(fd).st_ino == workspace.instance.stat().st_ino
      with source_latch(workspace, shared=True):
        pass
      with pytest.raises(Conflict):
        with adapter.run_lifecycle_guard(workspace):
          pytest.fail("lifecycle directory EX lost")
  with source_latch(workspace):
    for hook in (adapter.lifecycle_guard, adapter.run_lifecycle_guard):
      with pytest.raises(Conflict):
        with hook(workspace):
          pytest.fail("source EX ignored")
  with adapter.lifecycle_guard(workspace):
    pass
  for directory, name in [(workspace.instance, "auth.json"), (workspace.instance, "session.json"), (workspace.state_root, "state.json")]:
    assert (directory / name).read_bytes() == b"synthetic existing sentinel"
    assert (directory / name).stat().st_mode & 0o777 == 0o600


def test_cold_bootstrap_and_original_lifecycle_fd(tmp_path):
  workspace = SimpleNamespace(instance=tmp_path / "cold", state_root=tmp_path / "cold-state", profile="pi-base")
  with lifecycle.source_guard(workspace) as fd:
    assert os.fstat(fd).st_ino == workspace.instance.stat().st_ino
    assert (workspace.instance / ".agentcfg-instance.json").read_bytes() == marker(workspace)
    assert (workspace.instance / "source.lock").stat().st_mode & 0o777 == 0o600
  with lifecycle.source_guard(workspace, create=False):
    pass


@pytest.mark.parametrize("fault", ["foreign", "mode", "symlink", "missing"])
def test_marker_failure_precedes_anchor_creation(workspace, fault):
  path = workspace.instance / ".agentcfg-instance.json"
  if fault == "symlink":
    path.symlink_to("auth.json")
  elif fault != "missing":
    path.write_bytes(b"foreign binding" if fault == "foreign" else marker(workspace))
    path.chmod(0o644 if fault == "mode" else 0o600)
  with pytest.raises(Conflict):
    with lifecycle.source_guard(workspace, create=fault != "missing"):
      pytest.fail("invalid binding admitted")
  assert not (workspace.instance / "source.lock").exists()


def test_order_source_lifecycle_state_and_original_fd(workspace, monkeypatch):
  real_flock = fcntl.flock
  observed = []
  def flock(fd, operation):
    info = os.fstat(fd)
    if operation != fcntl.LOCK_UN:
      kind = "life" if info.st_ino == workspace.instance.stat().st_ino else "source" if info.st_ino == (workspace.instance / "source.lock").stat().st_ino else "state"
      observed.append((kind, operation))
    return real_flock(fd, operation)
  monkeypatch.setattr(fcntl, "flock", flock)
  with lifecycle.source_guard(workspace) as life:
    assert os.fstat(life).st_ino == workspace.instance.stat().st_ino
    with Tree(workspace.state_root) as state, instance_lock(state):
      pass
  assert observed == [("source", fcntl.LOCK_EX | fcntl.LOCK_NB), ("life", fcntl.LOCK_EX | fcntl.LOCK_NB), ("state", fcntl.LOCK_EX | fcntl.LOCK_NB)]


def test_activity_only_original_guard_works_under_long_shared_source(workspace):
  with lifecycle.source_guard(workspace):
    pass
  with source_latch(workspace, shared=True):
    with lifecycle.guard(workspace, allow_active=True, create=False):
      (workspace.state_root / "activity-only.json").write_bytes(b"synthetic stop activity")
  assert (workspace.state_root / "activity-only.json").read_bytes() == b"synthetic stop activity"


def test_run_still_checks_activity_and_binding(workspace, monkeypatch):
  adapter = PiAdapter(workspace.repository)
  def active(_):
    raise Conflict("synthetic activity protected")
  monkeypatch.setattr(lifecycle, "assert_inactive", active)
  with source_latch(workspace, shared=True, create=True):
    with pytest.raises(Conflict, match="activity protected"):
      with adapter.run_lifecycle_guard(workspace):
        pytest.fail("activity skipped")
    with lifecycle.guard(workspace, allow_active=True, create=False):
      pass


def test_real_unknown_activity_rejects_run_but_allows_original_activity_guard(workspace):
  with lifecycle.source_guard(workspace):
    pass
  leases = workspace.state_root / "activity/leases"
  leases.mkdir(parents=True, mode=0o700)
  (leases / "unknown.json").write_bytes(b"{}")
  with source_latch(workspace, shared=True):
    with pytest.raises(Conflict, match="执行记录损坏"):
      with PiAdapter(workspace.repository).run_lifecycle_guard(workspace):
        pytest.fail("real unknown lease ignored")
    with lifecycle.guard(workspace, allow_active=True, create=False):
      assert (leases / "unknown.json").read_bytes() == b"{}"


@pytest.mark.parametrize("profile", ["pi-base", "pi-full", "pi-legacy"])
def test_real_sync_method_selects_guard_before_fake_install_body(workspace, monkeypatch, profile):
  from agentcfg import pi_replacement, runtime
  workspace.profile = profile
  backend = PiBackend()
  lock = SimpleNamespace(metadata={"schema_version": 2 if profile != "pi-legacy" else 1},
    validated_bindings={profile: SimpleNamespace(state="current")})
  identity_calls = []
  monkeypatch.setattr(backend, "runtime_identity", lambda w, l: identity_calls.append((w, l)) or "synthetic identity")
  bodies = []
  monkeypatch.setattr(backend, "_sync", lambda w, l, **kw: bodies.append(w.profile) or "fake installation body")
  # 本测试只验证 guard 顺序；完整安装事实与侧记录在 replacement 接线测试另验。
  monkeypatch.setattr(runtime, "record", lambda *_: {})
  monkeypatch.setattr(pi_replacement, "descriptor", lambda *_: {})
  monkeypatch.setattr(pi_replacement, "record_validated", lambda *_: None)
  if profile != "pi-legacy":
    with source_latch(workspace, shared=True, create=True):
      with pytest.raises(Conflict):
        backend.sync(workspace, lock)
    assert bodies == []
  else:
    monkeypatch.setattr(lifecycle, "source_guard", lambda *_a, **_k: pytest.fail("legacy touched source"))
  assert backend.sync(workspace, lock) == "fake installation body"
  assert bodies == [profile] and identity_calls
  if profile == "pi-legacy":
    assert not (workspace.instance / "source.lock").exists()


@pytest.mark.parametrize("failure", ["identity", "candidate"])
def test_sync_preconditions_fail_before_any_anchor_or_guard(workspace, monkeypatch, failure):
  from agentcfg.process import DependencyError
  backend = PiBackend()
  lock = SimpleNamespace(metadata={"schema_version": 2}, validated_bindings={workspace.profile: SimpleNamespace(state="candidate")})
  def identity(w, l):
    if failure == "identity":
      raise DependencyError("synthetic identity rejected")
    return "synthetic identity"
  monkeypatch.setattr(backend, "runtime_identity", identity)
  monkeypatch.setattr(lifecycle, "guard", lambda *_a, **_k: pytest.fail("precondition reached guard"))
  monkeypatch.setattr(lifecycle, "source_guard", lambda *_a, **_k: pytest.fail("precondition reached source guard"))
  monkeypatch.setattr(backend, "_sync", lambda *_a, **_k: pytest.fail("precondition reached body"))
  with pytest.raises(DependencyError):
    backend.sync(workspace, lock)
  assert not (workspace.instance / "source.lock").exists()
  assert not (workspace.instance / ".agentcfg-instance.json").exists()


def test_legacy_adapter_hooks_keep_original_guard_only(workspace, monkeypatch):
  workspace.profile = "pi-legacy"
  adapter = PiAdapter(workspace.repository)
  monkeypatch.setattr(lifecycle, "source_guard", lambda *_a, **_k: pytest.fail("legacy touched source"))
  for hook in (adapter.lifecycle_guard, adapter.run_lifecycle_guard):
    with hook(workspace):
      pass
  assert not (workspace.instance / "source.lock").exists()
