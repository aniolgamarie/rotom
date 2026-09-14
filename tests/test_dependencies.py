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


@pytest.mark.parametrize("tool", ["node", "npm"])
def test_sync_rejects_minor_toolchain_version_drift(tmp_path, monkeypatch, tool):
  w = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    cache=tmp_path / "cache", repository=REPO, resolved=SimpleNamespace(data={"machine": {}}))
  lock = dep.read_lock(REPO)
  def fake(argv, *, cwd, env):
    if argv == ["node", "--version"]:
      return "v24.14.1" if tool == "node" else lock.metadata["node"]
    if argv == ["npm", "--version"]:
      return "11.19.2" if tool == "npm" else lock.metadata["npm"]
    pytest.fail("版本不匹配后不应开始安装")
  monkeypatch.setattr(dep, "checked", fake)
  with pytest.raises(DependencyError, match="版本不匹配"):
    dep.sync(w, lock)


def test_missing_and_stale_lock_do_not_resolve_dependencies(tmp_path, monkeypatch):
  with pytest.raises(ConfigError):
    dep.read_lock(tmp_path)
  monkeypatch.setattr(dep, "recipe_digest", lambda repository: "changed")
  with pytest.raises(ConfigError):
    dep.read_lock(REPO)


def test_child_failure_does_not_expose_native_output(tmp_path, fake_subprocess, capsys):
  canary = "synthetic-private-child-error"
  fake_subprocess.queue(returncode=9, stdout=canary, stderr=canary)
  with pytest.raises(DependencyError) as caught:
    checked(["npm", "ci"], cwd=tmp_path, env={"PATH": "/synthetic"})
  assert canary not in str(caught.value)
  assert capsys.readouterr() == ("", "")
