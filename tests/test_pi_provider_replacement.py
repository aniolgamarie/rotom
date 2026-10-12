"""替换复用真实临时部署事务；宿主、网络与账号调用均为零。"""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from agentcfg import deployment as dep
from agentcfg import pi_replacement as replacement
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree


BINDING = {"machine": "fixture", "local": "/synthetic/local.toml", "profile": "pi-base"}


def candidate(value):
  return RenderCandidate(value, (Artifact(ManagedTarget("rules.md", Ownership.FILE, "bytes"), value.encode()),))


def launch(value):
  return {"lock_identity": value * 64, "runtime_identity": value * 64}


def contract(provider="first", source="a"):
  return {"schema_version": 1, "profile": "pi-base", "providers": [{"capability_id": "footer", "provider_id": provider,
    "contract_version": "1", "source_identity": source * 64, "implementation_identity": source * 64, "state_owners": [], "config_fields": ["/settings/footer"]}]}


@pytest.fixture
def workspace(tmp_path):
  root = tmp_path / "instance"
  root.mkdir(mode=0o700)
  (root / "auth.json").write_text("synthetic-account-sentinel")
  (root / "session.jsonl").write_text("synthetic-session-sentinel")
  backend = SimpleNamespace(status=lambda w, identity: "installed")
  return SimpleNamespace(instance=root, state_root=tmp_path / "state", binding=BINDING, profile="pi-base", backend=backend)


def activate(w, value, descriptor=None):
  return replacement.apply(w, candidate(value), launch(value), descriptor or contract())


def saved(w):
  with Tree(w.state_root) as tree:
    return dep.read_state(tree)


def test_install_fact_does_not_select_runtime_and_apply_preserves_sentinels(workspace):
  w = workspace
  replacement.record_validated(w, launch("a"), contract())
  assert saved(w)["current"] is None
  assert replacement.status(w)["phase"] == "validated"
  activate(w, "a")
  assert saved(w)["current"]["launch"] == launch("a")
  assert replacement.status(w)["phase"] == "active"
  activate(w, "b", contract("second", "b"))
  assert saved(w)["previous"]["current"]["launch"] == launch("a")
  assert (w.instance / "auth.json").read_text() == "synthetic-account-sentinel"
  assert (w.instance / "session.jsonl").read_text() == "synthetic-session-sentinel"


@pytest.mark.parametrize("after_commit", [False, True])
def test_lost_receipt_reconciles_original_pointer_without_replaying(workspace, monkeypatch, after_commit):
  w = workspace
  activate(w, "a")
  original = dep.apply
  calls = []
  def lost(*args, **kwargs):
    calls.append(1)
    if after_commit:
      original(*args, **kwargs)
    raise OSError("synthetic-lost-receipt")
  monkeypatch.setattr(dep, "apply", lost)
  with pytest.raises(OSError):
    activate(w, "b", contract("second", "b"))
  result = replacement.status(w)
  assert result["phase"] == ("active" if after_commit else "restored")
  assert saved(w)["current"]["launch"] == launch("b" if after_commit else "a")
  replacement.recover(w)
  assert len(calls) == 1


def test_side_record_failure_after_commit_requires_explicit_recovery(workspace, monkeypatch):
  w = workspace
  activate(w, "a")
  original = replacement._write
  def crash(tree, record):
    if record["phase"] == "active" and record["new_runtime"] == "b" * 64:
      raise OSError("synthetic-side-record-full")
    return original(tree, record)
  monkeypatch.setattr(replacement, "_write", crash)
  with pytest.raises(OSError):
    activate(w, "b", contract("second", "b"))
  assert saved(w)["current"]["launch"] == launch("b")
  before = (w.state_root / "replacement.json").read_bytes()
  assert replacement.status(w)["phase"] == "activation-pending"
  assert (w.state_root / "replacement.json").read_bytes() == before
  with pytest.raises(Conflict):
    replacement.assert_runnable(w)
  monkeypatch.setattr(replacement, "_write", original)
  replacement.recover(w)
  assert replacement.status(w)["phase"] == "active"
  replacement.assert_runnable(w)


def test_unknown_pointer_and_original_pending_keep_recovery_required(workspace):
  w = workspace
  activate(w, "a")
  with Tree(w.state_root) as tree:
    state = dep.read_state(tree)
    state["current"]["launch"] = launch("c")
    tree.write_state("deployment.json", dep.json_bytes(state))
  replacement.recover(w)
  assert replacement.status(w)["phase"] == "recovery-required"
  with pytest.raises(Conflict):
    replacement.assert_runnable(w)


@pytest.mark.parametrize("fault", ["stateful", "duplicate", "unknown", "contract", "config"])
def test_non_equivalent_provider_has_zero_deployment_effect(workspace, fault):
  w = workspace
  activate(w, "a")
  descriptor = contract("second", "b")
  row = descriptor["providers"][0]
  if fault == "stateful": row["state_owners"] = ["unknown-store"]
  if fault == "duplicate": descriptor["providers"].append(deepcopy(row))
  if fault == "unknown": row["surprise"] = True
  if fault == "contract": row["contract_version"] = "2"
  if fault == "config": row["config_fields"] = ["/settings/other"]
  before = (w.state_root / "deployment.json").read_bytes()
  with pytest.raises(Conflict):
    activate(w, "b", descriptor)
  assert (w.state_root / "deployment.json").read_bytes() == before
  assert (w.instance / "rules.md").read_text() == "a"


def test_legacy_record_missing_cannot_assert_compatibility(workspace):
  w = workspace
  dep.apply(w.instance, w.state_root, candidate("a"), w.binding, launch("a"))
  with pytest.raises(Conflict):
    activate(w, "b", contract("second", "b"))
  assert saved(w)["current"]["launch"] == launch("a")


def test_missing_package_zero_activation_and_rollback_does_not_install(workspace):
  w = workspace
  w.backend.status = lambda w, identity: "missing"
  with pytest.raises(Conflict): activate(w, "a")
  assert saved(w)["current"] is None
  w.backend.status = lambda w, identity: "installed"
  activate(w, "a")
  activate(w, "b", contract("second", "b"))
  w.backend.status = lambda w, identity: "missing" if identity == "a" * 64 else "installed"
  replacement.rollback(w)
  assert saved(w)["current"]["launch"] == launch("a")
  assert replacement.status(w)["phase"] == "recovery-required"


def test_current_previous_session_and_unknown_references_prevent_uninstall(workspace):
  w = workspace
  activate(w, "a")
  activate(w, "b", contract("second", "b"))
  assert "deployment-previous" in replacement.references(w, "a" * 64)
  assert "deployment-current" in replacement.references(w, "b" * 64)
  assert "native-session-unknown" in replacement.references(w, "c" * 64)
  (w.state_root / "delegate").mkdir(mode=0o700)
  assert "delegate-reference-unknown" in replacement.references(w, "c" * 64)


def test_identity_cannot_be_rebound_to_different_provider_contract(workspace):
  w = workspace
  activate(w, "a")
  before = (w.state_root / "deployment.json").read_bytes()
  with pytest.raises(Conflict): activate(w, "a", contract("second", "b"))
  with pytest.raises(Conflict): replacement.record_validated(w, launch("a"), contract("second", "b"))
  assert (w.state_root / "deployment.json").read_bytes() == before


def test_command_apply_and_rollback_use_original_lifecycle_guard(workspace, monkeypatch):
  from contextlib import contextmanager
  from agentcfg import commands, runtime
  w = workspace
  w.agent = "pi"
  events = []
  @contextmanager
  def guard(_):
    events.append("enter")
    try: yield
    finally: events.append("leave")
  w.adapter = SimpleNamespace(lifecycle_guard=guard)
  monkeypatch.setattr(runtime, "record", lambda w, lock: launch(lock))
  monkeypatch.setattr(replacement, "descriptor", lambda lock, profile: contract())
  commands.apply_candidate(w, "a", candidate("a"))
  commands.apply_candidate(w, "b", candidate("b"))
  monkeypatch.setattr(commands, "workspace", lambda args: w)
  monkeypatch.setattr(commands, "output", lambda w, command, result, **kwargs: result)
  assert commands.cmd_rollback(SimpleNamespace())["restored"] == 1
  assert events == ["enter", "leave"] * 3


def test_cancel_before_original_commit_restores_old_pointer(workspace, monkeypatch):
  w = workspace
  activate(w, "a")
  def cancelled(*args, **kwargs): raise KeyboardInterrupt()
  monkeypatch.setattr(dep, "apply", cancelled)
  with pytest.raises(KeyboardInterrupt): activate(w, "b", contract("second", "b"))
  assert saved(w)["current"]["launch"] == launch("a")
  assert replacement.status(w)["phase"] == "restored"


def test_original_journal_recovery_does_not_replay_deployment(workspace):
  w = workspace
  activate(w, "a")
  with Tree(w.state_root) as tree, Tree(w.instance) as target:
    original = dep.read_state(tree)
    plan = dep.plan(target, original, candidate("b"), w.binding, launch("b"))
    after = {**original, "current": plan.current}
    tree.write_state("pending.json", dep.json_bytes({"after_state": after, "changes": plan.changes}))
    dep.write_changes(target, plan.changes)
  assert (w.instance / "rules.md").read_text() == "b"
  assert replacement.status(w)["recovery_pending"]
  replacement.recover(w)
  assert (w.instance / "rules.md").read_text() == "a"
  assert saved(w)["current"]["launch"] == launch("a")
  assert not replacement.status(w)["recovery_pending"]


def test_maintenance_parser_is_explicit_and_status_readonly(workspace):
  from agentcfg.cli import build_parser
  args = build_parser().parse_args(["--profile", "pi-base", "pi-maintenance", "recover", "--format", "json"])
  assert args.maintenance_command == "recover"
  w = workspace
  activate(w, "a")
  before = {path.name: path.read_bytes() for path in w.state_root.iterdir() if path.is_file()}
  replacement.status(w)
  assert before == {path.name: path.read_bytes() for path in w.state_root.iterdir() if path.is_file()}


def test_uninstall_only_unreferenced_owned_package_and_preserves_user_data(workspace):
  w = workspace
  activate(w, "a")
  w.backend.root = lambda w, identity: w.instance / "runtimes" / identity
  identity = "c" * 64
  with Tree(w.backend.root(w, identity), create=True) as tree:
    tree.write_state(".agentcfg-ready", (identity + "\n").encode())
    tree.write_state("owned-module", b"synthetic")
  with pytest.raises(Conflict): replacement.uninstall(w, identity)
  assert w.backend.root(w, identity).exists()
  (w.instance / "session.jsonl").unlink()
  result = replacement.uninstall(w, identity)
  assert result["removed"] and not result["user_data_removed"]
  assert not w.backend.root(w, identity).exists()
  assert (w.instance / "auth.json").read_text() == "synthetic-account-sentinel"
  with pytest.raises(Conflict): replacement.uninstall(w, "a" * 64)


def test_uninstall_rejects_foreign_root_symlink_and_full_unknown_store(workspace):
  w = workspace
  activate(w, "a")
  (w.instance / "session.jsonl").unlink()
  identity = "c" * 64
  w.backend.root = lambda w, identity: w.instance / "unowned"
  with pytest.raises(Conflict): replacement.uninstall(w, identity)
  w.backend.root = lambda w, identity: w.instance / "runtimes" / identity
  root = w.backend.root(w, identity)
  root.parent.mkdir(mode=0o700)
  root.symlink_to(w.instance)
  with pytest.raises(Conflict): replacement.uninstall(w, identity)
  assert root.is_symlink()
  w.profile = "pi-full"
  with pytest.raises(Conflict): replacement.references(w, identity)
  # 独立尚未部署的 Full 不能借 Base 的绑定或记录判断 store 已清零。
  w.state_root = w.state_root.parent / "full-state"
  assert "full-store-reference-unknown" in replacement.references(w, identity)


def test_foreign_owner_recovery_zero_journal_effect(workspace):
  w = workspace
  activate(w, "a")
  with Tree(w.state_root) as tree:
    record = json.loads(tree.read("replacement.json")[0])
    record["binding"] = {**w.binding, "machine": "other"}
    tree.write_state("replacement.json", dep.json_bytes(record))
    tree.write_state("pending.json", b"synthetic-journal-sentinel")
  before = (w.state_root / "pending.json").read_bytes()
  with pytest.raises(Conflict): replacement.recover(w)
  with pytest.raises(Conflict): replacement.rollback(w)
  assert (w.state_root / "pending.json").read_bytes() == before


def test_stateful_support_source_change_is_not_transparently_compatible(workspace):
  w = workspace
  original = contract()
  original["providers"][0]["state_owners"] = ["native-sessions"]
  activate(w, "a", original)
  following = deepcopy(original)
  following["providers"][0]["implementation_identity"] = "f" * 64
  with pytest.raises(Conflict): activate(w, "b", following)
  assert saved(w)["current"]["launch"] == launch("a")


def test_backend_sync_records_validation_inside_original_guard(workspace, monkeypatch):
  from contextlib import contextmanager
  from agentcfg import pi_dependencies, pi_lifecycle, runtime
  w = workspace
  lock = SimpleNamespace(metadata={"schema_version": 2}, validated_bindings={"pi-base": SimpleNamespace(state="current")})
  backend = pi_dependencies.PiBackend(profile="pi-base")
  events = []
  @contextmanager
  def guard(_):
    events.append("enter")
    try: yield
    finally: events.append("leave")
  monkeypatch.setattr(pi_lifecycle, "source_guard", guard)
  monkeypatch.setattr(backend, "runtime_identity", lambda *args: "a" * 64)
  monkeypatch.setattr(backend, "_sync", lambda *args, **kwargs: {"installed": True})
  monkeypatch.setattr(runtime, "record", lambda *args: launch("a"))
  monkeypatch.setattr(replacement, "descriptor", lambda *args: contract())
  original = replacement.record_validated
  def record(*args):
    assert events == ["enter"]
    original(*args)
  monkeypatch.setattr(replacement, "record_validated", record)
  backend.sync(w, lock)
  assert events == ["enter", "leave"]
  assert replacement.status(w)["phase"] == "validated"
  assert saved(w)["current"] is None


def test_real_lifecycle_guard_blocks_activation_and_maintenance_before_effect(workspace, monkeypatch):
  from agentcfg import commands, pi_lifecycle, runtime
  from agentcfg.pi import PiAdapter
  w = workspace
  w.agent = "pi"
  w.repository = w.instance.parent
  w.adapter = PiAdapter(w.repository)
  monkeypatch.setattr(runtime, "record", lambda *args: launch("a"))
  monkeypatch.setattr(replacement, "descriptor", lambda *args: contract())
  monkeypatch.setattr(commands, "workspace", lambda args: w)
  def protected(_): raise Conflict("synthetic protected original lease")
  monkeypatch.setattr(pi_lifecycle, "assert_inactive", protected)
  with pytest.raises(Conflict, match="protected"):
    commands.apply_candidate(w, None, candidate("a"))
  for name in ("recover", "uninstall"):
    with pytest.raises(Conflict, match="protected"):
      commands.cmd_pi_maintenance(SimpleNamespace(maintenance_command=name, runtime_identity="c" * 64))
  assert not (w.state_root / "deployment.json").exists()
  assert not (w.state_root / "replacement.json").exists()
  assert (w.instance / "auth.json").read_text() == "synthetic-account-sentinel"
