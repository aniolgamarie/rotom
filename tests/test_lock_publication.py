"""仅在临时仓库内发布虚构公开锁；真实 flock、假解析器、零网络。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from agentcfg import dependencies, omp_dependencies, publication
from agentcfg.deployment import json_bytes
from agentcfg.storage import Conflict, Tree


@pytest.fixture(params=["dsh", "omp", "pi"])
def public_lock(tmp_path, request):
  adapter = request.param
  repository = tmp_path / "repository"
  root = repository / "locks" / adapter
  root.mkdir(parents=True)
  names = sorted(publication.FILES[adapter])
  before = {}
  for index, name in enumerate(names):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if index == 0:
      before[name] = None
      continue
    path.write_bytes(("old-public-" + name).encode())
    path.chmod(0o640)
    before[name] = (path.read_bytes(), 0o640)
  after = {name: ("new-public-" + name).encode() for name in names}
  if adapter == "dsh":
    after["package-lock.json"] = None
  return repository, adapter, root, before, after


def _snapshot(root, names):
  with Tree(root, private=False) as tree:
    return {name: ((raw[0], raw[1]) if (raw := tree.read(name)) else None) for name in names}


def _pending(repository, adapter):
  return repository / ".cache/agentcfg-publication" / adapter / "pending.json"


def test_manifest_last_atomic_staging_and_private_journal(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  writes = []
  original = Tree.replace
  def observed(tree, path, data, *args, **kwargs):
    if tree.root == root:
      marker = _pending(repository, adapter)
      assert marker.stat().st_mode & 0o777 == 0o600
      assert marker.parent.stat().st_mode & 0o777 == 0o700
      assert marker.parent.parent.stat().st_mode & 0o777 == 0o700
      writes.append(path)
    return original(tree, path, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", observed)
  with publication.publisher_lease(repository, adapter) as publisher:
    result = publisher.publish(after, validate=lambda: "validated")
  assert result == "validated"
  assert writes[-1] == "manifest.json"
  assert not _pending(repository, adapter).exists()
  assert not list(root.rglob(".agentcfg-*"))
  assert {name: value[0] if value else None for name, value in _snapshot(root, after).items()} == after


def test_two_writers_and_reader_busy_during_resolution(public_lock):
  repository, adapter, root, before, after = public_lock
  entered = threading.Event()
  release = threading.Event()
  errors = []
  def writer():
    try:
      with publication.publisher_lease(repository, adapter):
        entered.set()
        assert release.wait(5)
    except BaseException as exc:
      errors.append(exc)
  thread = threading.Thread(target=writer)
  thread.start()
  assert entered.wait(2)
  try:
    with pytest.raises(Conflict):
      with publication.publisher_lease(repository, adapter):
        pytest.fail("second writer entered")
    with pytest.raises(Conflict):
      with publication.reader_lease(repository, adapter):
        pytest.fail("reader entered during publication")
    assert _snapshot(root, before) == before
  finally:
    release.set()
    thread.join(5)
  assert not errors and not thread.is_alive()


def test_writer_refused_while_readers_hold_generation(public_lock):
  repository, adapter, root, before, after = public_lock
  with publication.reader_lease(repository, adapter):
    with publication.reader_lease(repository, adapter):
      with pytest.raises(Conflict):
        with publication.publisher_lease(repository, adapter):
          pytest.fail("writer entered active readers")
  assert _snapshot(root, before) == before


def test_sync_holds_reader_before_any_instance_or_package_work(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  workspace, lock = SimpleNamespace(repository=repository), object()
  calls = []
  def consume(*args, **kwargs):
    with pytest.raises(Conflict):
      with publication.publisher_lease(repository, adapter):
        pytest.fail("publication entered active sync")
    calls.append("consumed")
    return "complete"
  if adapter == "dsh":
    monkeypatch.setattr(dependencies, "read_lock", lambda *args: lock)
    monkeypatch.setattr(dependencies, "_sync_guarded", consume)
    result = dependencies.sync(workspace, lock)
  elif adapter == "omp":
    backend = omp_dependencies.OmpBackend()
    monkeypatch.setattr(backend, "_sync", consume)
    result = backend.sync(workspace, lock)
  else:
    from agentcfg.pi_dependencies import PiBackend
    backend = PiBackend()
    monkeypatch.setattr(backend, "_read_lock_unlocked", lambda *args, **kwargs: lock)
    monkeypatch.setattr(backend, "_sync", consume)
    result = backend.sync(workspace, lock)
  assert result == "complete" and calls == ["consumed"]
  with publication.publisher_lease(repository, adapter):
    pass


def test_dsh_sync_rejects_stale_snapshot_before_instance_creation(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  if adapter != "dsh":
    return
  from agentcfg.schema import ConfigError
  monkeypatch.setattr(dependencies, "read_lock", lambda *args: "new-generation")
  monkeypatch.setattr(dependencies, "_sync_guarded", lambda *args, **kwargs: pytest.fail("stale lock consumed"))
  with pytest.raises(ConfigError):
    dependencies.sync(SimpleNamespace(repository=repository), "old-generation")


@pytest.mark.parametrize("public_lock,index",
  [("dsh", index) for index in range(4)] + [("omp", index) for index in range(6)] + [("pi", index) for index in range(5)],
  indirect=["public_lock"])
def test_exception_at_each_write_restores_all_files_and_modes(public_lock, monkeypatch, index):
  repository, adapter, root, before, after = public_lock
  original = Tree.replace
  calls = [0]
  def fail_once(tree, path, data, *args, **kwargs):
    result = original(tree, path, data, *args, **kwargs)
    if tree.root == root:
      calls[0] += 1
      if calls[0] == index + 1:
        raise OSError("synthetic write interruption")
    return result
  monkeypatch.setattr(Tree, "replace", fail_once)
  with pytest.raises(OSError):
    with publication.publisher_lease(repository, adapter) as publisher:
      publisher.publish(after, validate=lambda: None)
  assert _snapshot(root, before) == before
  assert not _pending(repository, adapter).exists()
  assert not list(root.rglob(".agentcfg-*"))


def test_validation_failure_restores_generation(public_lock):
  repository, adapter, root, before, after = public_lock
  def invalid():
    raise ValueError("synthetic invalid generated lock")
  with pytest.raises(ValueError):
    with publication.publisher_lease(repository, adapter) as publisher:
      publisher.publish(after, validate=invalid)
  assert _snapshot(root, before) == before
  assert not _pending(repository, adapter).exists()


class HardInterruption(BaseException):
  pass


def _interrupt(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  original = Tree.replace
  fired = [False]
  def interrupt(tree, path, data, *args, **kwargs):
    result = original(tree, path, data, *args, **kwargs)
    if tree.root == root and not fired[0]:
      fired[0] = True
      raise HardInterruption()
    return result
  monkeypatch.setattr(Tree, "replace", interrupt)
  with pytest.raises(HardInterruption):
    with publication.publisher_lease(repository, adapter) as publisher:
      publisher.publish(after, validate=lambda: None)
  monkeypatch.setattr(Tree, "replace", original)


def test_hard_interruption_blocks_reader_and_explicit_publisher_recovers(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  _interrupt(public_lock, monkeypatch)
  assert _pending(repository, adapter).exists()
  with pytest.raises(Conflict, match="待恢复"):
    with publication.reader_lease(repository, adapter):
      pytest.fail("pending generation admitted")
  with publication.publisher_lease(repository, adapter) as publisher:
    assert _snapshot(root, before) == before
    assert not _pending(repository, adapter).exists()
    publisher.publish(after, validate=lambda: None)
  assert {name: value[0] if value else None for name, value in _snapshot(root, after).items()} == after


def test_recovery_preflight_refuses_drift_without_partial_restore(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  _interrupt(public_lock, monkeypatch)
  (root / "manifest.json").write_bytes(b"external-public-edit")
  drifted = _snapshot(root, before)
  with pytest.raises(Conflict, match="漂移"):
    with publication.publisher_lease(repository, adapter):
      pytest.fail("drift admitted")
  assert _snapshot(root, before) == drifted
  assert _pending(repository, adapter).exists()


@pytest.mark.parametrize("damage", ["escape", "absolute", "unknown", "duplicate", "unknown-field", "adapter", "bad-base64"])
def test_unsafe_journal_never_writes_any_lock_path(public_lock, monkeypatch, damage):
  repository, adapter, root, before, after = public_lock
  _interrupt(public_lock, monkeypatch)
  marker = _pending(repository, adapter)
  value = json.loads(marker.read_bytes())
  if damage in {"escape", "absolute", "unknown"}:
    value["files"][0]["path"] = {"escape": "../outside", "absolute": "/tmp/outside", "unknown": "account.json"}[damage]
  elif damage == "duplicate":
    value["files"].insert(0, value["files"][0])
  elif damage == "unknown-field":
    value["extra"] = True
  elif damage == "adapter":
    value["adapter"] = "unknown"
  else:
    value["files"][0]["before"] = "not base64"
  marker.write_bytes(json_bytes(value))
  state = _snapshot(root, before)
  with pytest.raises(Conflict, match="日志无效"):
    with publication.publisher_lease(repository, adapter):
      pytest.fail("unsafe journal admitted")
  assert _snapshot(root, before) == state
  assert marker.exists()


@pytest.mark.parametrize("adapter", ["dsh", "omp", "pi"])
def test_adapter_reader_holds_shared_lease_through_complete_read(tmp_path, monkeypatch, adapter):
  repository = tmp_path / "repository"
  (repository / "locks" / adapter).mkdir(parents=True)
  def read(*args, **kwargs):
    with pytest.raises(Conflict):
      with publication.publisher_lease(repository, adapter):
        pytest.fail("reader released lease too early")
    return "complete-generation"
  if adapter == "dsh":
    monkeypatch.setattr(dependencies, "_read_lock_unlocked", read)
    assert dependencies.read_lock(repository) == "complete-generation"
  elif adapter == "omp":
    backend = omp_dependencies.OmpBackend()
    monkeypatch.setattr(backend, "_read_lock_unlocked", read)
    assert backend.read_lock(repository) == "complete-generation"
  else:
    from agentcfg.pi_dependencies import PiBackend
    backend = PiBackend()
    monkeypatch.setattr(backend, "_read_lock_unlocked", read)
    assert backend.read_lock(repository) == "complete-generation"


def _dsh_resolver(tmp_path, monkeypatch):
  repository = tmp_path / "repository"
  root = repository / "locks/dsh"
  root.mkdir(parents=True)
  recipe = repository / "agents/dsh"
  recipe.mkdir(parents=True)
  (recipe / "dependencies.json").write_bytes(b'{"dependencies":{}}')
  (recipe / "agent.toml").write_bytes(b'adapter_version = "dsh-1"\n')
  source = recipe / "synthetic-recipe"
  source.write_bytes(b"original recipe")
  policy = {"supported_platforms": ["linux", "darwin"], "node": "v24.0.0", "npm": "11.0.0",
            "pnpm": "10.0.0", "pnpm_integrity": "synthetic", "npm_integrity": "synthetic",
            "adapter_version": "dsh-1", "upstream": {}}
  monkeypatch.setattr(dependencies, "lock_policy", lambda *args: deepcopy(policy))
  monkeypatch.setattr(dependencies, "recipe_digest", lambda *args: hashlib.sha256(source.read_bytes()).hexdigest())
  monkeypatch.setattr(dependencies, "copy_vendors", lambda *args: None)
  monkeypatch.setattr(dependencies, "prepare_pnpm", lambda *args: ["synthetic-pnpm"])
  monkeypatch.setattr(dependencies, "check_pnpm_version", lambda *args, **kwargs: None)
  monkeypatch.setattr(dependencies, "validate_installer_resolution", lambda *args: None)
  monkeypatch.setattr(dependencies, "validate_installer_plugin_versions", lambda *args: None)
  monkeypatch.setattr(dependencies, "_read_lock_unlocked", lambda *args, **kwargs: "validated-generation")
  def checked(argv, *, cwd, env):
    if argv == ["node", "--version"]:
      return policy["node"]
    if argv == ["npm", "--version"]:
      return policy["npm"]
    (cwd / "pnpm-lock.yaml").write_bytes(b"synthetic installer resolution")
    return ""
  monkeypatch.setattr(dependencies, "checked", checked)
  return repository, source, checked


def test_dsh_resolver_rechecks_source_before_publishing(tmp_path, monkeypatch):
  repository, source, checked = _dsh_resolver(tmp_path, monkeypatch)
  manifest = repository / "locks/dsh/manifest.json"
  manifest.write_bytes(b"old usable public lock")
  def changed(argv, **kwargs):
    result = checked(argv, **kwargs)
    if "install" in argv:
      source.write_bytes(b"concurrent recipe edit")
    return result
  monkeypatch.setattr(dependencies, "checked", changed)
  with pytest.raises(Conflict, match="配方"):
    dependencies.resolve_lock(repository)
  assert manifest.read_bytes() == b"old usable public lock"
  assert not _pending(repository, "dsh").exists()


def test_dsh_explicit_resolver_recovers_before_resolution_and_avoids_nested_shared_lease(tmp_path, monkeypatch):
  repository, source, checked = _dsh_resolver(tmp_path, monkeypatch)
  with publication.publisher_lease(repository, "dsh") as publisher:
    original = publisher.tree.replace
    def crash(*args, **kwargs):
      original(*args, **kwargs)
      raise HardInterruption()
    monkeypatch.setattr(publisher.tree, "replace", crash)
    with pytest.raises(HardInterruption):
      publisher.publish({"package.json": b"interrupted", "manifest.json": b"interrupted manifest"}, validate=lambda: None)
  def inspect(argv, **kwargs):
    assert not _pending(repository, "dsh").exists()
    return checked(argv, **kwargs)
  monkeypatch.setattr(dependencies, "checked", inspect)
  assert dependencies.resolve_lock(repository) == "validated-generation"
  assert not _pending(repository, "dsh").exists()


def _omp_resolver(tmp_path, monkeypatch, *, change=False):
  import io
  import tarfile
  repository = tmp_path / "omp-repository"
  (repository / "locks/omp").mkdir(parents=True)
  source = repository / "synthetic-recipe"
  source.write_bytes(b"original recipe")
  stream = io.BytesIO()
  with tarfile.open(fileobj=stream, mode="w:gz") as archive:
    for name in ("bun.lock", "LICENSE", "THIRD-PARTY-NOTICES.txt"):
      raw = ("synthetic upstream " + name).encode()
      info = tarfile.TarInfo("source/" + name)
      info.size = len(raw)
      archive.addfile(info, io.BytesIO(raw))
  archive = stream.getvalue()
  monkeypatch.setattr(omp_dependencies, "SOURCE_SHA256", hashlib.sha256(archive).hexdigest())
  monkeypatch.setattr(omp_dependencies, "ASSETS", {})
  backend = omp_dependencies.OmpBackend()
  monkeypatch.setattr(backend, "_resources", lambda repository: ([], {}, {"synthetic-recipe": hashlib.sha256(source.read_bytes()).hexdigest()}))
  monkeypatch.setattr(backend, "_read_lock_unlocked", lambda *args, **kwargs: "validated-omp-generation")
  def download(url):
    assert not _pending(repository, "omp").exists()
    with pytest.raises(Conflict):
      with publication.reader_lease(repository, "omp"):
        pytest.fail("resolver released exclusive lease before downloads")
    if url == omp_dependencies.SOURCE_URL:
      if change:
        source.write_bytes(b"external recipe edit")
      return archive
    return b""
  monkeypatch.setattr(omp_dependencies, "_download", download)
  return repository, backend


def test_omp_resolver_rechecks_sources_before_publication(tmp_path, monkeypatch):
  repository, backend = _omp_resolver(tmp_path, monkeypatch, change=True)
  manifest = repository / "locks/omp/manifest.json"
  manifest.write_bytes(b"old usable public lock")
  with pytest.raises(Conflict, match="配方"):
    backend.resolve_lock(repository)
  assert manifest.read_bytes() == b"old usable public lock"
  assert not _pending(repository, "omp").exists()


def test_omp_explicit_resolver_recovers_before_download_and_does_not_reenter_reader(tmp_path, monkeypatch):
  repository, backend = _omp_resolver(tmp_path, monkeypatch)
  with publication.publisher_lease(repository, "omp") as publisher:
    def crash():
      raise HardInterruption()
    with pytest.raises(HardInterruption):
      publisher.publish({"manifest.json": b"interrupted manifest"}, validate=crash)
  assert _pending(repository, "omp").exists()
  assert backend.resolve_lock(repository) == "validated-omp-generation"
  assert not _pending(repository, "omp").exists()


def test_adapter_readers_fail_closed_on_pending_publication(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  _interrupt(public_lock, monkeypatch)
  with pytest.raises(Conflict, match="待恢复"):
    if adapter == "dsh":
      dependencies.read_lock(repository)
    elif adapter == "omp":
      omp_dependencies.OmpBackend().read_lock(repository)
    else:
      from agentcfg.pi_dependencies import PiBackend
      PiBackend().read_lock(repository)


def test_exception_with_external_edit_retains_journal_and_does_not_partially_restore(public_lock, monkeypatch):
  repository, adapter, root, before, after = public_lock
  original = Tree.replace
  fired = [False]
  observed = []
  def fail_with_drift(tree, path, data, *args, **kwargs):
    result = original(tree, path, data, *args, **kwargs)
    if tree.root == root and not fired[0]:
      fired[0] = True
      (root / "manifest.json").write_bytes(b"external public lock edit")
      observed.append(_snapshot(root, before))
      raise OSError("synthetic publisher failure")
    return result
  monkeypatch.setattr(Tree, "replace", fail_with_drift)
  with pytest.raises(Conflict, match="漂移"):
    with publication.publisher_lease(repository, adapter) as publisher:
      publisher.publish(after, validate=lambda: None)
  assert observed and _snapshot(root, before) == observed[0]
  assert _pending(repository, adapter).exists()
