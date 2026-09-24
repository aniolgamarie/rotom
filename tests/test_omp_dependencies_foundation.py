"""完整合成锁与真实摘要校验；默认不运行任何第三方宿主。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import omp_dependencies as dep
from agentcfg.deployment import json_bytes
from agentcfg.schema import ConfigError
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict


def hashed(value):
  return hashlib.sha256(value).hexdigest()


@pytest.fixture
def locked(tmp_path, monkeypatch):
  repository = tmp_path / "repository"
  root = repository / "locks/omp"
  root.mkdir(parents=True)
  (repository / "schemas").mkdir()
  (repository / "schemas/omp-lock.schema.json").write_bytes((Path(__file__).resolve().parents[1] / "schemas/omp-lock.schema.json").read_bytes())
  content = b"synthetic executable bytes; never run\n"
  assets = {name: {"url": "https://example.invalid/" + name, "sha256": hashed(content)}
    for name in ("linux-x64", "linux-arm64", "macos-x64", "macos-arm64")}
  # 合成独立来源仍走同一摘要验证器，不让假字节匹配正式发布 SHA。
  monkeypatch.setattr(dep, "ASSETS", assets, raising=False)
  upstream = {}
  for name in ("bun.lock", "LICENSE", "THIRD-PARTY-NOTICES.txt", "provenance.json", "NOTICE.md"):
    path = root / "upstream" / name
    path.parent.mkdir(exist_ok=True)
    value = ("synthetic " + name).encode()
    path.write_bytes(value)
    upstream["upstream/" + name] = hashed(value)
  package = repository / "agents/omp/packages/echo-mcp/server.py"
  package.parent.mkdir(parents=True)
  package.write_bytes(b"# fixture, never executed\n")
  entry = {"path": "agents/omp/packages/echo-mcp/server.py", "target": "packages/echo-mcp/server.py",
    "sha256": hashed(package.read_bytes()), "executable": False}
  body = {"version": 1, "adapter_version": "omp-1", "tag": dep.TAG, "commit": dep.COMMIT,
    "source": {"url": dep.SOURCE_URL, "sha256": dep.SOURCE_SHA256}, "assets": assets,
    "upstream": upstream, "resources": [entry], "packages": {"echo-mcp": {
      "source": "agents/omp/packages/echo-mcp", "entrypoints": ["server.py"],
      "tree_digest": hashed(json_bytes([entry])), "license": "MIT", "compatibility": dep.TAG}},
    "recipe": {}, "interpreters": {"python": {"kind": "manager-python", "implementation": "cpython", "minimum": [3, 11]}}}
  def save(data):
    value = {key: value for key, value in data.items() if key != "identity"}
    value["identity"] = hashed(json_bytes(value))
    (root / "manifest.json").write_bytes(json_bytes(value))
    return value
  manifest = save(body)
  workspace = SimpleNamespace(repository=repository, cache=tmp_path / "private/cache",
    instance=tmp_path / "private/instance", state_root=tmp_path / "private/state")
  cache = workspace.cache / "downloads" / hashed(content)
  cache.parent.mkdir(parents=True, mode=0o700)
  workspace.cache.chmod(0o700)
  cache.write_bytes(content)
  cache.chmod(0o600)
  return workspace, manifest, save, content


def test_sync_preserves_uncreated_instance_and_has_complete_receipt(locked):
  workspace, manifest, _, content = locked
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock)
  assert not workspace.instance.exists()
  assert not workspace.state_root.exists()
  runtime = backend.root(workspace, result["identity"])
  assert runtime.is_relative_to(workspace.cache)
  assert (runtime / "bin/omp").read_bytes() == content
  assert (runtime / "packages/echo-mcp/server.py").is_file()
  receipt = json.loads((runtime / ".agentcfg-receipt.json").read_bytes())
  assert receipt["lock_identity"] == manifest["identity"]
  assert receipt["platform"] == dep.platform_id()
  assert receipt["interpreters"]["python"]["sha256"]
  assert backend.status(workspace, result["identity"]) == "installed"


def test_receipt_and_binary_cannot_self_attest_tampering(locked):
  workspace, _, _, _ = locked
  backend = dep.OmpBackend()
  result = backend.sync(workspace, backend.read_lock(workspace.repository))
  root = backend.root(workspace, result["identity"])
  (root / "bin/omp").write_bytes(b"tampered")
  receipt_path = root / ".agentcfg-receipt.json"
  receipt = json.loads(receipt_path.read_bytes())
  receipt["binary_sha256"] = hashed(b"tampered")
  receipt_path.write_bytes(json_bytes(receipt))
  assert backend.status(workspace, result["identity"]) == "damaged"


@pytest.mark.parametrize("damage", ["unknown", "traversal", "resource", "upstream", "symlink"])
def test_closed_lock_rejects_invalid_content_and_paths(locked, damage):
  workspace, manifest, save, _ = locked
  data = deepcopy(manifest)
  if damage == "unknown":
    data["hidden"] = True
  elif damage == "traversal":
    data["upstream"]["../outside"] = "a" * 64
  elif damage == "resource":
    (workspace.repository / data["resources"][0]["path"]).write_bytes(b"changed")
  elif damage == "upstream":
    (workspace.repository / "locks/omp/upstream/bun.lock").write_bytes(b"changed")
  else:
    path = workspace.repository / data["resources"][0]["path"]
    target = path.with_name("outside")
    path.rename(target)
    path.symlink_to(target)
  save(data)
  with pytest.raises(ConfigError):
    dep.OmpBackend().read_lock(workspace.repository)


def test_runtime_lease_blocks_sync_mutation(locked):
  workspace, _, _, _ = locked
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  identity = backend.runtime_identity(workspace, lock)
  with backend.runtime_guard(workspace, identity):
    with pytest.raises(Conflict):
      backend.sync(workspace, lock)
  assert not workspace.instance.exists()


def test_corrupt_cache_does_not_activate(locked):
  workspace, _, _, content = locked
  (workspace.cache / "downloads" / hashed(content)).write_bytes(b"wrong")
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  with pytest.raises(DependencyError):
    backend.sync(workspace, lock)
  assert not backend.root(workspace, backend.runtime_identity(workspace, lock)).exists()


@pytest.mark.parametrize("system,machine,libc", [
  ("linux", "x86_64", "musl"), ("win32", "AMD64", ""), ("linux", "riscv64", "glibc")])
def test_unsupported_platforms_fail_before_install(monkeypatch, system, machine, libc):
  monkeypatch.setattr(dep.sys, "platform", system)
  monkeypatch.setattr(dep.platform, "machine", lambda: machine)
  monkeypatch.setattr(dep.platform, "libc_ver", lambda: (libc, "test"))
  with pytest.raises(DependencyError):
    dep.platform_id()


def test_download_failure_keeps_previous_runtime(locked, monkeypatch):
  workspace, _, _, content = locked
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock)
  root = backend.root(workspace, result["identity"])
  before = (root / "bin/omp").read_bytes()
  (root / "bin/omp").write_bytes(b"damaged-old")
  (workspace.cache / "downloads" / hashed(content)).unlink()
  def unavailable(*args, **kwargs):
    raise OSError("not a credential")
  monkeypatch.setattr(dep.urllib.request, "urlopen", unavailable)
  with pytest.raises(DependencyError):
    backend.sync(workspace, lock)
  assert (root / "bin/omp").read_bytes() == b"damaged-old"
  assert before == content


def test_activation_failure_restores_old_directory(locked, monkeypatch):
  workspace, _, _, _ = locked
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock)
  root = backend.root(workspace, result["identity"])
  (root / "bin/omp").write_bytes(b"old-content")
  rename = dep.os.rename
  def fail_stage(source, target, *args, **kwargs):
    if Path(source).name.startswith(".stage-"):
      raise OSError("injected activation failure")
    return rename(source, target, *args, **kwargs)
  monkeypatch.setattr(dep.os, "rename", fail_stage)
  with pytest.raises(OSError):
    backend.sync(workspace, lock)
  assert (root / "bin/omp").read_bytes() == b"old-content"
  assert not list(root.parent.glob(".stage-*"))
  assert not list(root.parent.glob(".previous-*"))


@pytest.mark.parametrize("damage", ["extra", "mode", "linked"])
def test_runtime_whole_tree_shape_is_verified(locked, damage):
  workspace, _, _, _ = locked
  backend = dep.OmpBackend()
  result = backend.sync(workspace, backend.read_lock(workspace.repository))
  root = backend.root(workspace, result["identity"])
  if damage == "extra":
    (root / "packages/extra.ts").write_bytes(b"unknown")
  elif damage == "mode":
    (root / "bin/omp").chmod(0o600)
  else:
    package = root / "packages/echo-mcp/server.py"
    package.unlink()
    package.symlink_to(root / "bin/omp")
  assert backend.status(workspace, result["identity"]) == "damaged"


def test_resolver_checks_archive_and_writes_complete_upstream(locked, monkeypatch, tmp_path):
  import io
  import tarfile
  workspace, _, _, _ = locked
  buffer = io.BytesIO()
  with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
    for name in ("bun.lock", "LICENSE", "THIRD-PARTY-NOTICES.txt"):
      body = ("complete synthetic " + name).encode()
      info = tarfile.TarInfo("fixed-commit/" + name)
      info.size = len(body)
      archive.addfile(info, io.BytesIO(body))
  path = tmp_path / "source.tar.gz"
  path.write_bytes(buffer.getvalue())
  monkeypatch.setattr(dep, "SOURCE_SHA256", hashed(buffer.getvalue()))
  sums = tmp_path / "SHA256SUMS.txt"
  sums.write_text("\n".join(asset["sha256"] + " " + asset["url"].rsplit("/", 1)[1] for asset in dep.ASSETS.values()))
  lock = dep.OmpBackend().resolve_lock(workspace.repository, source_archive=path, checksums=sums)
  assert set(lock.metadata["upstream"]) == dep.UPSTREAM
  assert lock.metadata["packages"]["echo-mcp"]["entrypoints"] == ["server.py"]
  assert dep.OmpBackend().read_lock(workspace.repository) == lock
  path.write_bytes(b"not the archive")
  with pytest.raises(ConfigError):
    dep.OmpBackend().resolve_lock(workspace.repository, source_archive=path, checksums=sums)
  assert dep.OmpBackend().read_lock(workspace.repository) == lock


def test_sync_recovers_interrupted_activation_before_rebuilding(locked):
  workspace, _, _, _ = locked
  backend = dep.OmpBackend()
  lock = backend.read_lock(workspace.repository)
  identity = backend.runtime_identity(workspace, lock)
  backend.sync(workspace, lock)
  root = backend.root(workspace, identity)
  old = root.parent / ".previous-interrupted"
  stage = root.parent / ".stage-interrupted"
  stage.mkdir(mode=0o700)
  (stage / "partial").write_bytes(b"incomplete")
  journal = root.parent / (".pending-" + identity + ".json")
  journal.write_bytes(json_bytes({"version": 1, "identity": identity, "old": old.name, "stage": stage.name}))
  journal.chmod(0o600)
  root.rename(old)
  backend.sync(workspace, lock)
  assert backend.status(workspace, identity) == "installed"
  assert not journal.exists()
  assert not old.exists()
  assert not stage.exists()
