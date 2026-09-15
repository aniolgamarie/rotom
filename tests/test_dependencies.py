"""锁消费失败不激活；真实包安装另由显式集成验收记录。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import dependencies as dep
from agentcfg.process import DependencyError, checked
from agentcfg.schema import ConfigError
from agentcfg.storage import ensure_private


REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", ["install", "changed-lock", "missing-helper"])
def test_failed_sync_keeps_old_runtime_and_repository_lock(tmp_path, monkeypatch, failure):
  w = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    cache=tmp_path / "cache", repository=REPO, resolved=SimpleNamespace(data={"machine": {}}))
  lock = dep.read_lock(REPO)
  previous = w.instance / "runtimes/previous"
  ensure_private(previous)
  (previous / "keep").write_text("working runtime")
  before = (REPO / "locks/dsh/package-lock.json").read_bytes()
  def fake(argv, *, cwd, env):
    assert "API_KEY" not in env
    if argv == ["node", "--version"]:
      return lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return lock.metadata["npm"]
    if argv[1] == "ci":
      (cwd / "partial").write_text("partial installation")
      if failure == "install":
        raise DependencyError("合成安装失败")
      if failure == "changed-lock":
        (cwd / "package-lock.json").write_text("changed")
    return ""
  monkeypatch.setattr(dep, "checked", fake)
  with pytest.raises(DependencyError):
    dep.sync(w, lock)
  assert (previous / "keep").read_text() == "working runtime"
  assert not dep.runtime_root(w, lock).exists()
  assert not list((w.instance / "runtimes").glob(".stage-*"))
  assert (REPO / "locks/dsh/package-lock.json").read_bytes() == before


@pytest.mark.parametrize(("tool", "actual"), [("node", "v25.0.0"), ("npm", "12.0.0"), ("node", "v24.1.0")])
def test_sync_rejects_incompatible_toolchain_version(tmp_path, monkeypatch, tool, actual):
  w = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    cache=tmp_path / "cache", repository=REPO, agent="dsh", resolved=SimpleNamespace(data={"machine": {}}))
  lock = dep.read_lock(REPO)
  def fake(argv, *, cwd, env):
    if argv == ["node", "--version"]:
      return actual if tool == "node" else lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return actual if tool == "npm" else lock.metadata["npm"]
    pytest.fail("版本不匹配后不应开始安装")
  monkeypatch.setattr(dep, "checked", fake)
  with pytest.raises(DependencyError, match=f"期望 .*实际 {actual}"):
    dep.sync(w, lock)


@pytest.mark.parametrize(("tool", "actual", "locked"),
  [("Node", "v24.2.0", "v24.14.0"), ("Node", "v24.14.1", "v24.14.0"),
   ("npm", "11.0.0", "11.19.1")])
def test_toolchain_accepts_same_major_version(tool, actual, locked):
  from agentcfg.toolchain import compatible_toolchain
  assert compatible_toolchain(tool, actual, locked)


@pytest.mark.parametrize(("tool", "actual", "locked"), [
  ("Node", "v024.1.0", "v24.14.0"), ("Node", "v24.1.0\nprivate-token", "v24.14.0"),
  ("npm", "011.0.0", "11.19.1"), ("npm", "１１.0.0", "11.19.1"),
])
def test_toolchain_rejects_and_hides_malformed_output(tool, actual, locked):
  from agentcfg.toolchain import ensure_compatible_toolchain
  with pytest.raises(DependencyError) as caught:
    ensure_compatible_toolchain(tool, locked, actual)
  assert actual not in str(caught.value)
  assert "已隐藏" in str(caught.value)


@pytest.mark.parametrize(("tool", "actual"), [
  ("node", "v24.14.1"), ("npm", "11.19.2"), ("node", "v24.14.0\nsynthetic-private-token"),
])
def test_resolve_lock_requires_exact_toolchain_before_install(tmp_path, monkeypatch, tool, actual):
  lock = dep.read_lock(REPO)
  before = {name: (REPO / "locks/dsh" / name).read_bytes()
            for name in ("package.json", "package-lock.json", "manifest.json")}

  def fake(argv, *, cwd, env):
    if argv == ["node", "--version"]:
      return actual if tool == "node" else lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return actual if tool == "npm" else lock.metadata["npm"]
    pytest.fail("精确版本不匹配后不应解析锁")

  monkeypatch.setattr(dep, "checked", fake)
  with pytest.raises(DependencyError) as caught:
    dep.resolve_lock(REPO)
  assert "期望" in str(caught.value) and "实际" in str(caught.value)
  assert "synthetic-private-token" not in str(caught.value)
  assert all((REPO / "locks/dsh" / name).read_bytes() == raw for name, raw in before.items())


def test_lock_rejects_adapter_declaration_drift(monkeypatch):
  from agentcfg.adapter import AdapterDeclaration
  from agentcfg.backends import DshBackend
  from agentcfg.dsh import DshAdapter
  monkeypatch.setattr(DshAdapter, "declaration", AdapterDeclaration("dsh", 1, "dsh-2"))
  with pytest.raises(ConfigError):
    DshBackend().read_lock(REPO)


def test_missing_and_stale_lock_do_not_resolve_dependencies(tmp_path, monkeypatch):
  with pytest.raises(ConfigError):
    dep.read_lock(tmp_path)
  monkeypatch.setattr(dep, "recipe_digest", lambda repository, adapter_id="dsh": "changed")
  with pytest.raises(ConfigError):
    dep.read_lock(REPO)


def test_child_failure_does_not_expose_native_output(tmp_path, fake_subprocess, capsys):
  canary = "synthetic-private-child-error"
  fake_subprocess.queue(returncode=9, stdout=canary, stderr=canary)
  with pytest.raises(DependencyError) as caught:
    checked(["npm", "ci"], cwd=tmp_path, env={"PATH": "/synthetic"})
  assert canary not in str(caught.value)
  assert "npm" in str(caught.value) and "退出码 9" in str(caught.value)
  assert capsys.readouterr() == ("", "")
