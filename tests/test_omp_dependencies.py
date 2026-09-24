"""依赖维护故障注入；仅使用独立合成锁和假资产。"""

from copy import deepcopy
import os

import pytest

from agentcfg import omp_dependencies as dep
from agentcfg.deployment import json_bytes
from agentcfg.schema import ConfigError
from test_omp_dependencies_foundation import locked, hashed


@pytest.mark.parametrize("damage", ["version", "commit", "asset", "missing", "entry", "mode", "interpreter"])
def test_lock_closure_rejects_each_maintenance_mismatch(locked, damage):
  workspace, original, save, _ = locked
  body = deepcopy(original)
  if damage == "version":
    body["adapter_version"] = "omp-future"
  elif damage == "commit":
    body["commit"] = "0" * 40
  elif damage == "asset":
    body["assets"]["linux-x64"]["sha256"] = "0" * 64
  elif damage == "missing":
    del body["upstream"]["upstream/bun.lock"]
  elif damage == "entry":
    body["packages"]["echo-mcp"]["entrypoints"] = ["missing.py"]
  elif damage == "mode":
    (workspace.repository / body["resources"][0]["path"]).chmod(0o700)
  else:
    body["interpreters"] = {}
  save(body)
  with pytest.raises(ConfigError):
    dep.OmpBackend().read_lock(workspace.repository)


@pytest.mark.parametrize("damage", ["same-size", "interpreter", "hardlink", "empty-directory"])
def test_runtime_exact_content_and_directory_identity(locked, damage):
  workspace, _, _, _ = locked
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  identity = backend.sync(workspace, lock)["identity"]
  root = backend.root(workspace, identity)
  if damage == "same-size":
    target = root / "bin/omp"
    info = target.stat()
    raw = target.read_bytes()
    target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
  elif damage == "interpreter":
    receipt = backend._receipt(workspace, lock, identity)
    receipt["interpreters"]["python"]["sha256"] = "0" * 64
    (root / ".agentcfg-receipt.json").write_bytes(json_bytes(receipt))
  elif damage == "hardlink":
    os.link(root / "bin/omp", workspace.cache / "alias")
  else:
    (root / "packages/undeclared-empty").mkdir(mode=0o700)
  assert backend.status(workspace, identity) == "damaged"


def test_offline_cache_reuse_and_explicit_repair_leave_home_and_lock_unchanged(locked, monkeypatch):
  workspace, _, _, content = locked
  workspace.instance.mkdir(parents=True)
  sentinel = workspace.instance / "user-auth-sentinel"
  sentinel.write_bytes(b"untouched")
  manifest = workspace.repository / "locks/omp/manifest.json"
  before_lock = manifest.read_bytes()
  monkeypatch.setattr(dep, "_download", lambda _: pytest.fail("offline cache must be sufficient"))
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  identity = backend.sync(workspace, lock)["identity"]
  root = backend.root(workspace, identity)
  before = (root / "bin/omp").stat()
  backend.sync(workspace, lock)
  assert (root / "bin/omp").stat().st_ino == before.st_ino
  assert (root / "bin/omp").stat().st_mtime_ns == before.st_mtime_ns
  (root / "bin/omp").write_bytes(b"damaged")
  assert backend.status(workspace, identity) == "damaged"
  assert (root / "bin/omp").read_bytes() == b"damaged"
  backend.sync(workspace, lock)
  assert (root / "bin/omp").read_bytes() == content
  assert sentinel.read_bytes() == b"untouched"
  assert manifest.read_bytes() == before_lock


def test_new_lock_keeps_old_package_but_old_binding_cannot_follow(locked):
  workspace, manifest, save, _ = locked
  backend = dep.OmpBackend()
  first = backend.read_lock(workspace.repository)
  old_identity = backend.sync(workspace, first)["identity"]
  old_root = backend.root(workspace, old_identity)
  resource = workspace.repository / manifest["resources"][0]["path"]
  resource.write_bytes(b"# next reviewed package\n")
  manifest["resources"][0]["sha256"] = hashed(resource.read_bytes())
  manifest["packages"]["echo-mcp"]["tree_digest"] = hashed(json_bytes(manifest["resources"]))
  save(manifest)
  second = backend.read_lock(workspace.repository)
  new_identity = backend.sync(workspace, second)["identity"]
  assert new_identity != old_identity
  assert backend.status(workspace, old_identity) == "damaged"
  assert backend.status(workspace, new_identity) == "installed"
  assert (old_root / "packages/echo-mcp/server.py").read_bytes() == b"# fixture, never executed\n"
  assert not workspace.instance.exists()


def test_stage_validation_failure_preserves_previous_package(locked, monkeypatch):
  workspace, _, _, _ = locked
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  identity = backend.sync(workspace, lock)["identity"]
  root = backend.root(workspace, identity)
  (root / "bin/omp").write_bytes(b"old-damaged-package")
  verify = backend._verify
  def fail_stage(path, *args):
    if path.name.startswith(".stage-"):
      raise ValueError("injected stage validation failure")
    return verify(path, *args)
  monkeypatch.setattr(backend, "_verify", fail_stage)
  with pytest.raises(ValueError):
    backend.sync(workspace, lock)
  assert (root / "bin/omp").read_bytes() == b"old-damaged-package"
  assert not list(root.parent.glob(".stage-*"))
  assert not list(root.parent.glob(".pending-*"))
