"""锁消费失败不激活；真实包安装另由显式集成验收记录。"""

from pathlib import Path
from types import SimpleNamespace
import base64
import hashlib
import io
import json
import shutil
import tarfile
import yaml

import pytest

from agentcfg import dependencies as dep
from agentcfg.process import DependencyError, checked
from agentcfg.schema import ConfigError
from agentcfg.storage import ensure_private


REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", ["install", "changed-lock", "changed-installer-lock", "runtime-check", "missing-helper"])
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
    if argv[-1] == "--version" and argv[0] == "node":
      return lock.metadata["pnpm"]
    if "--frozen-lockfile" in argv:
      assert "--ignore-scripts" in argv and "--node-linker=hoisted" in argv and "--package-import-method=copy" in argv
      assert "--force" not in argv and "--legacy-peer-deps" not in argv
      (cwd / "partial").write_text("partial installation")
      if failure == "install":
        raise DependencyError("合成安装失败")
      if failure == "changed-lock":
        (cwd / "package-lock.json").write_text("changed")
      if failure == "changed-installer-lock":
        (cwd / "pnpm-lock.yaml").write_text("changed")
    if failure == "runtime-check" and argv[1].endswith("check-runtime.mjs"):
      raise DependencyError("合成模块身份不一致")
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


def lock_repository(tmp_path):
  repository = tmp_path / "repository"
  shutil.copytree(REPO / "agents/dsh", repository / "agents/dsh")
  shutil.copytree(REPO / "locks/dsh", repository / "locks/dsh")
  return repository


def test_frozen_installer_lock_and_tool_version_change_identity():
  lock = dep.read_lock(REPO)
  assert lock.installer_resolution
  assert dep.lock_identity(lock.package, lock.resolution, lock.metadata, lock.installer_resolution) == lock.identity
  assert dep.lock_identity(lock.package, lock.resolution, lock.metadata, lock.installer_resolution + b"\n") != lock.identity
  changed = {**lock.metadata, "pnpm": "11.19.1"}
  assert dep.lock_identity(lock.package, lock.resolution, changed, lock.installer_resolution) != lock.identity
  assert dep.Lock("fixture", {}, b"{}", b"{}").installer_resolution == b""


@pytest.mark.parametrize("change", ["installer-lock", "unknown-metadata", "source"])
def test_read_lock_rejects_changed_installer_unknown_metadata_and_unpacked_source(tmp_path, change):
  repository = lock_repository(tmp_path)
  if change == "installer-lock":
    path = repository / "locks/dsh/pnpm-lock.yaml"
    path.write_bytes(path.read_bytes() + b"\n")
  elif change == "unknown-metadata":
    path = repository / "locks/dsh/manifest.json"
    metadata = json.loads(path.read_bytes())
    metadata["unknown"] = True
    path.write_text(json.dumps(metadata))
  else:
    path = repository / "agents/dsh/packages/cursor-terminal/index.mjs"
    path.write_bytes(path.read_bytes() + b"\n// source changed without packing\n")
  with pytest.raises(ConfigError):
    dep.read_lock(repository)


def test_recipe_ignores_undeclared_historical_vendor(tmp_path):
  repository = lock_repository(tmp_path)
  before = dep.recipe_digest(repository)
  (repository / "locks/dsh/vendor/retired-unused.tgz").write_bytes(b"historical archive")
  assert dep.recipe_digest(repository) == before


def test_recipe_refuses_changed_local_source_without_repacking(tmp_path):
  repository = lock_repository(tmp_path)
  path = repository / "agents/dsh/packages/cursor-terminal/index.mjs"
  path.write_bytes(path.read_bytes() + b"\n// unpacked change\n")
  with pytest.raises(DependencyError, match="重新打包"):
    dep.recipe_digest(repository)


def test_pnpm_original_archive_integrity_checked_before_extraction(tmp_path):
  lock = dep.read_lock(REPO)
  metadata = {**lock.metadata, "pnpm_integrity": "sha512-incorrect"}
  with pytest.raises(DependencyError, match="完整性"):
    dep.prepare_pnpm(REPO, tmp_path, metadata)
  assert not (tmp_path / ".tooling").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "escape"])
def test_pnpm_archive_rejects_links_and_path_escape(tmp_path, kind):
  repository = tmp_path / "repository"
  archive = repository / "locks/dsh/vendor/pnpm-11.19.0.tgz"
  archive.parent.mkdir(parents=True)
  content = io.BytesIO()
  with tarfile.open(fileobj=content, mode="w:gz") as bundle:
    member = tarfile.TarInfo("../outside" if kind == "escape" else "package/unsafe")
    if kind != "escape":
      member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
      member.linkname = "../../outside"
    bundle.addfile(member)
  archive.write_bytes(content.getvalue())
  metadata = {"pnpm": "11.19.0", "pnpm_integrity": "sha512-" + base64.b64encode(hashlib.sha512(content.getvalue()).digest()).decode()}
  stage = tmp_path / "stage"
  stage.mkdir()
  with pytest.raises(DependencyError, match="结构不安全"):
    dep.prepare_pnpm(repository, stage, metadata)
  assert not (tmp_path / "outside").exists()


def test_installer_resolution_requires_exact_declared_specs():
  lock = dep.read_lock(REPO)
  package = json.loads(lock.package)
  package["dependencies"]["@deepseek-ai/dsh"] = "0.2.0-rc.3"
  with pytest.raises(ValueError):
    dep.validate_installer_resolution(json.dumps(package).encode(), lock.installer_resolution)


def test_read_lock_rejects_missing_pnpm_integrity_even_with_recomputed_identity(tmp_path):
  repository = lock_repository(tmp_path)
  root = repository / "locks/dsh"
  installer = yaml.safe_load((root / "pnpm-lock.yaml").read_bytes())
  next(iter(installer["packages"].values()))["resolution"].pop("integrity")
  data = yaml.safe_dump(installer).encode()
  (root / "pnpm-lock.yaml").write_bytes(data)
  metadata = json.loads((root / "manifest.json").read_bytes())
  metadata["identity"] = dep.lock_identity((root / "package.json").read_bytes(), (root / "package-lock.json").read_bytes(), metadata, data)
  (root / "manifest.json").write_text(json.dumps(metadata))
  with pytest.raises(ConfigError):
    dep.read_lock(repository)
