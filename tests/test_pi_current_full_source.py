"""实际 Workspace current 数据观察；合成原安装，无实际 Full/角色/SDK。"""

import builtins
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import traceback

import pytest

from agentcfg import pi_current_full_source as source
from agentcfg.config import ResolvedConfig
from agentcfg.deployment import json_bytes, read_state
from agentcfg.merge import Provenance
from agentcfg.pi import PiAdapter
from agentcfg.pi_dependencies import PiBackend
from agentcfg import pi_capabilities as capabilities
from agentcfg import pi_owner_origin as origin
from agentcfg import pi_installed_source as installed_source
from agentcfg import pi_runtime_packages as packages
from agentcfg import pi_source_latch as latch_module
from agentcfg.storage import Tree
from agentcfg.workspace import Workspace
import test_pi_owner_origin as fixture_origin
from test_pi_wheel_lock_integration import _republish


CODE = "PI_CURRENT_FULL_SOURCE_INVALID"
SECRET = "SYNTHETIC_CURRENT_SOURCE_PRIVATE"
GENERATION = "private-generation-" + SECRET


class UnusedSecretStore:
  def __getattribute__(self, name): raise AssertionError("secret store touched")


class Case:
  def __repr__(self): return "<synthetic current source fixture>"


def workspace(repository, base, profile="pi-full", plugins=()):
  data = {"profile": {"id": profile, "agent": "pi", "plugins": list(plugins), "agent_options": {"runtime": {"engine": "node"}}},
    "machine": {"id": "synthetic-machine", "paths": {"instances_root": str(base / "instances"),
      "state_root": str(base / "states"), "cache_root": str(base / "cache")}}}
  resolved = ResolvedConfig(data, Provenance({}), 1)
  return Workspace(repository, base / "private-local.toml", resolved, PiAdapter(repository), None, UnusedSecretStore())


def build_case(base, monkeypatch, state="current"):
  original_prepare = fixture_origin._prepare
  def real_workspace_prepare(path, patch, **kwargs):
    old, lock, *rest = original_prepare(path, patch, **kwargs)
    if state == "accepted":
      metadata = deepcopy(lock.metadata)
      metadata["capability_bindings"]["selections"]["pi-full"]["state"] = "accepted"
      _republish(old.repository, metadata)
      metadata = json.loads((old.repository / "locks/pi-modern/manifest.json").read_bytes())
      bindings = metadata["capability_bindings"]
      selected = capabilities._resolve_selection_data(bindings["catalog"], bindings["providers"], bindings["selections"]["pi-full"],
        metadata, lock_identity=metadata["identity"], host_version=metadata["sources"]["pi-host"]["version"], engine=metadata["profile_slices"]["pi-full"]["engine"])
      lock = PiBackend(profile="pi-full").read_lock(old.repository, accepted_binding_digests={"pi-full": selected.acceptance_context_digest})
    actual = workspace(old.repository, base / "managed", plugins=lock.metadata["profile_slices"]["pi-full"]["capability_ids"])
    return actual, lock, *rest
  monkeypatch.setattr(fixture_origin, "_prepare", real_workspace_prepare)
  actual, lock, root, result, rest = fixture_origin._install(base / "pipeline", monkeypatch)
  assert type(actual) is Workspace and type(actual.adapter) is PiAdapter
  assert packages.status(root, result["identity"]) == "installed"
  marker = json_bytes({"schema_version": 1, "state_root": str(actual.state_root), "binding": actual.binding})
  with Tree(actual.instance) as tree: tree.write_new(".agentcfg-instance.json", marker)
  with latch_module.source_latch(actual, shared=True, create=True): pass
  saved = {"version": 1, "current": {"generation": GENERATION, "binding": actual.binding,
    "launch": {"lock_identity": lock.identity, "runtime_identity": result["identity"],
      "environment": [{"name": "SYNTHETIC_REFERENCE", "source": "secret:synthetic-reference"}],
      "machine": {"private": SECRET}}, "items": {}}, "previous": None,
    "owner": {"binding": actual.binding, "shared_files": []}}
  with Tree(actual.state_root) as tree:
    tree.write_state("deployment.json", json_bytes(saved))
    assert read_state(tree)["current"]["generation"] == GENERATION
  case = Case()
  case.workspace, case.root = actual, root
  case.context = fixture_origin._context(root)
  case.piece = deepcopy(lock.metadata["profile_slices"]["pi-full"])
  case.saved = saved
  return case


@pytest.fixture
def full(monkeypatch):
  with tempfile.TemporaryDirectory(prefix="pi-current-source-owned-", dir="/tmp") as temporary:
    yield build_case(Path(temporary), monkeypatch)


def rejected(action):
  try:
    raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Exception) as caught: action()
  error = caught.value
  assert error.args == (CODE,) and getattr(error, "exit_code", None) == 4
  assert error.__cause__ is None and error.__context__ is None
  rendered = "".join(traceback.format_exception(error))
  assert SECRET not in rendered and GENERATION not in rendered


def save(case):
  with Tree(case.workspace.state_root) as tree: tree.write_state("deployment.json", json_bytes(case.saved))


def after_capture(monkeypatch, action):
  original = installed_source.capture_installed_full_source
  def capture(*args, **kwargs):
    result = original(*args, **kwargs)
    action()
    return result
  monkeypatch.setattr(installed_source, "capture_installed_full_source", capture)


def test_real_current_to_original_complete_source_result_and_locks_close(full, monkeypatch):
  visited = []
  original = installed_source.capture_installed_full_source
  def captured(root, piece, **context):
    visited.append((root, piece, context))
    return original(root, piece, **context)
  monkeypatch.setattr(installed_source, "capture_installed_full_source", captured)
  result = source.observe_current_full_source(full.workspace)
  assert len(visited) == 1
  assert visited[0] == (str(full.root), full.piece, full.context)
  assert set(result) == {"schema_version", "profile", "lock_identity", "runtime_identity", "root", "markers", "entries"}
  assert result["profile"] == "pi-full" and result["runtime_identity"] == full.context["identity"]
  assert result["lock_identity"] == full.context["lock_identity"] and result["entries"]
  assert GENERATION not in repr(result) and SECRET not in repr(result)
  assert hashlib.sha256(GENERATION.encode()).hexdigest() not in repr(result)
  with latch_module.source_latch(full.workspace): pass


def test_accepted_selection_real_digest_install_and_current_pointer_allowed(monkeypatch):
  with tempfile.TemporaryDirectory(prefix="pi-current-accepted-owned-", dir="/tmp") as temporary:
    case = build_case(Path(temporary), monkeypatch, "accepted")
    result = source.observe_current_full_source(case.workspace)
    assert result["runtime_identity"] == case.context["identity"]


def test_base_and_foreign_workspace_adapter_reject_before_optional_import_or_tree(tmp_path, monkeypatch):
  actual = workspace(tmp_path, tmp_path, "pi-base")
  touched = []
  original_import = builtins.__import__
  def checked_import(name, *args, **kwargs):
    if name.endswith(("pi_owner_origin", "pi_installed_source", "pi_source_latch")):
      touched.append(name); raise AssertionError("optional Full import")
    return original_import(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", checked_import)
  monkeypatch.setattr(source, "Tree", lambda *args, **kwargs: pytest.fail("base Tree IO"))
  rejected(lambda: source.observe_current_full_source(actual))
  class ForeignWorkspace(Workspace): pass
  class ForeignAdapter(PiAdapter): pass
  foreign = ForeignWorkspace(**actual.__dict__)
  rejected(lambda: source.observe_current_full_source(foreign))
  actual.resolved.data["profile"]["id"] = "pi-full"
  actual.adapter = ForeignAdapter(tmp_path)
  rejected(lambda: source.observe_current_full_source(actual))
  assert touched == []


@pytest.mark.parametrize("fault", ["missing", "wrong", "mode", "link", "anchor-missing"])
def test_marker_and_existing_anchor_only_no_creation(full, fault):
  marker = full.workspace.instance / ".agentcfg-instance.json"
  if fault == "missing": marker.unlink()
  if fault == "wrong": marker.write_bytes(json_bytes({"schema_version": 1, "state_root": "/unrelated", "binding": full.workspace.binding}))
  if fault == "mode": marker.chmod(0o644)
  if fault == "link": marker.unlink(); marker.symlink_to("source.lock")
  if fault == "anchor-missing": (full.workspace.instance / "source.lock").unlink()
  rejected(lambda: source.observe_current_full_source(full.workspace))
  if fault == "anchor-missing": assert not (full.workspace.instance / "source.lock").exists()
  if fault == "missing": assert not marker.exists()


@pytest.mark.parametrize("fault", ["missing", "no-current", "binding", "runtime-missing", "runtime-invalid", "lock-invalid", "generation-type", "unknown-current", "unknown-launch", "bad-top", "item-guard"])
def test_actual_saved_state_closed_consumer_and_original_guards_reject(full, fault):
  current = full.saved["current"]
  if fault == "missing": (full.workspace.state_root / "deployment.json").unlink()
  elif fault == "no-current": full.saved["current"] = None
  elif fault == "binding": current["binding"] = {**current["binding"], "machine": "unrelated"}
  elif fault == "runtime-missing": current["launch"].pop("runtime_identity")
  elif fault == "runtime-invalid": current["launch"]["runtime_identity"] = "not-hex"
  elif fault == "lock-invalid": current["launch"]["lock_identity"] = "not-hex"
  elif fault == "generation-type": current["generation"] = 1
  elif fault == "unknown-current": current["extra"] = SECRET
  elif fault == "unknown-launch": current["launch"]["extra"] = SECRET
  elif fault == "bad-top": full.saved["extra"] = SECRET
  elif fault == "item-guard": current["items"] = {"invalid": {"baseline": {"present": True, "value": "literal"},
    "path": "pi-home/models.json", "selector": "/providers/fixture/apiKey", "codec": "json"}}
  if fault != "missing": save(full)
  rejected(lambda: source.observe_current_full_source(full.workspace))


def test_pending_presence_rejects_without_reading_body(full, monkeypatch):
  pending = full.workspace.state_root / "pending.json"
  pending.write_bytes(b"not JSON body"); pending.chmod(0o600)
  original = Tree.read
  def read(tree, name, **kwargs):
    if name == "pending.json": pytest.fail("pending body read")
    return original(tree, name, **kwargs)
  monkeypatch.setattr(Tree, "read", read)
  rejected(lambda: source.observe_current_full_source(full.workspace))


def test_candidate_detached_selection_is_rejected_after_original_owner_validation(full, monkeypatch):
  original = origin.validate_installed_owner_origin
  verified = []
  def candidate(*args, **kwargs):
    result = original(*args, **kwargs)
    verified.append(True)
    result["metadata"]["capability_bindings"]["selections"]["pi-full"]["state"] = "candidate"
    return result
  monkeypatch.setattr(origin, "validate_installed_owner_origin", candidate)
  rejected(lambda: source.observe_current_full_source(full.workspace))
  assert verified


@pytest.mark.parametrize("target", ["generation", "binding", "lock", "runtime", "pending", "named-runtime", "receipt", "marker", "anchor"])
def test_end_recheck_refuses_actual_private_pointer_and_named_resource_changes(full, monkeypatch, target):
  def mutate():
    if target == "generation": full.saved["current"]["generation"] += "-changed"; save(full)
    if target == "binding": full.saved["current"]["binding"]["machine"] += "-changed"; save(full)
    if target == "lock": full.saved["current"]["launch"]["lock_identity"] = "a" * 64; save(full)
    if target == "runtime": full.saved["current"]["launch"]["runtime_identity"] = "b" * 64; save(full)
    if target == "pending": (full.workspace.state_root / "pending.json").write_bytes(b"pending")
    if target == "named-runtime":
      full.root.rename(full.root.with_name("retired-runtime")); full.root.mkdir(mode=0o700)
    if target == "receipt":
      path = full.root / ".agentcfg-receipt.json"; path.write_bytes(path.read_bytes() + b" ")
    if target == "marker": (full.workspace.instance / ".agentcfg-instance.json").write_bytes(b"changed marker")
    if target == "anchor":
      path = full.workspace.instance / "source.lock"; path.rename(path.with_name("retired-source.lock")); path.write_bytes(b""); path.chmod(0o600)
  after_capture(monkeypatch, mutate)
  rejected(lambda: source.observe_current_full_source(full.workspace))


def test_legal_mutable_directory_metadata_and_activity_do_not_self_invalidate(full, monkeypatch):
  def activity():
    (full.workspace.instance / "activity-directory").mkdir(mode=0o700)
    (full.workspace.state_root / "heartbeat.json").write_bytes(b"activity")
    (full.workspace.state_root / "budget.json").write_bytes(b"activity")
    path = full.root / "temporary-observation-dir"; path.mkdir(mode=0o700); path.rmdir()
  after_capture(monkeypatch, activity)
  result = source.observe_current_full_source(full.workspace)
  assert result["runtime_identity"] == full.context["identity"]


def test_source_ex_is_present_observer_refuses_and_does_not_release_it(full):
  with latch_module.source_latch(full.workspace):
    rejected(lambda: source.observe_current_full_source(full.workspace))
    with pytest.raises(Exception):
      with latch_module.source_latch(full.workspace, shared=True): pytest.fail("EX released")
  with latch_module.source_latch(full.workspace): pass


def test_source_uses_no_new_repository_lock_or_model_secret_store(full, monkeypatch):
  def forbidden(*args, **kwargs): pytest.fail("new repository lock/auth/model used")
  monkeypatch.setattr(PiBackend, "read_lock", forbidden)
  full.workspace.resolved.data["models"] = UnusedSecretStore()
  (full.workspace.repository / "locks/pi-modern/manifest.json").write_bytes(b"new broken repository lock")
  result = source.observe_current_full_source(full.workspace)
  assert result["runtime_identity"] == full.context["identity"]


def test_bounded_same_bytes_memory_read_state_and_caps_before_decode(full, monkeypatch):
  raw = (full.workspace.state_root / "deployment.json").read_bytes()
  monkeypatch.setattr(source, "MAX_DEPLOYMENT", len(raw), raising=False)
  assert source.observe_current_full_source(full.workspace)["runtime_identity"] == full.context["identity"]
  monkeypatch.setattr(source, "MAX_DEPLOYMENT", len(raw) - 1)
  calls = []
  original = source._READ_STATE
  def forbidden(reader): calls.append(True); raise AssertionError("parsed over cap")
  monkeypatch.setattr(source, "_READ_STATE", forbidden)
  rejected(lambda: source.observe_current_full_source(full.workspace))
  assert calls == []
  monkeypatch.setattr(source, "_READ_STATE", original)


def test_first_receipt_raw_and_original_validated_raw_must_match(full, monkeypatch):
  original = packages._validated_receipt
  def different(*args):
    receipt, raw = original(*args)
    return receipt, raw + b" "
  monkeypatch.setattr(packages, "_validated_receipt", different)
  rejected(lambda: source.observe_current_full_source(full.workspace))


def test_context_exit_failure_rejects_original_source_result(full, monkeypatch):
  original = latch_module.source_latch
  @contextmanager
  def unknown_close(*args, **kwargs):
    with original(*args, **kwargs): yield None
    raise OSError(SECRET)
  monkeypatch.setattr(latch_module, "source_latch", unknown_close)
  rejected(lambda: source.observe_current_full_source(full.workspace))


def test_bad_binding_is_fixed_without_echo():
  for args, kwargs in (((), {}), ((None, None), {}), ((), {SECRET: GENERATION}), ((object(),), {})):
    rejected(lambda: source.observe_current_full_source(*args, **kwargs))


def test_first_receipt_cap_equal_and_next_byte_reject_before_original_validator(full, monkeypatch):
  size = (full.root / ".agentcfg-receipt.json").stat().st_size
  monkeypatch.setattr(source, "MAX_RECEIPT", size, raising=False)
  assert source.observe_current_full_source(full.workspace)["runtime_identity"] == full.context["identity"]
  monkeypatch.setattr(source, "MAX_RECEIPT", size - 1)
  called = []
  def forbidden(*args): called.append(True); raise AssertionError("receipt validation before cap")
  monkeypatch.setattr(packages, "_validated_receipt", forbidden)
  rejected(lambda: source.observe_current_full_source(full.workspace))
  assert called == []
