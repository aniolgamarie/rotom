"""临时账户下的授权存储；不加载SDK、不启动进程、不读取真实账号。"""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.pi_reviewer_authority import ReviewerAuthorityStore, FILE
from agentcfg.pi_reviewer_authority_protocol import encode_authority
from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree


def authority():
  return {"schema_version": 1, "authority_ref": "a" * 32, "generation": 1,
    "route": {"logical_provider": "synthetic", "native_route": "agentcfg-synthetic",
      "model_id": "synthetic-model", "auth_kind": "api-key", "owner": "pi-environment",
      "api": "openai-completions", "base_url": "https://synthetic.invalid/v1"},
    "pricing": {"revision": "b" * 32, "currency": "USD", "input_units_per_million": 1000000,
      "output_units_per_million": 2000000, "cache_read_units_per_million": 500000,
      "cache_write_units_per_million": 3000000, "source": "https://synthetic.invalid/pricing",
      "checked_on": "2026-10-05"},
    "limits": {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000},
    "token_limits": {"input_tokens": 100, "output_tokens": 10},
    "categories": ["file-read", "file-write", "shell"], "valid_from": 100, "valid_until": 200}


@pytest.fixture
def account(tmp_path):
  home = tmp_path / "account"
  home.mkdir(mode=0o700)
  return home


def path(home):
  return home / ".agentcfg-workspaces" / FILE


def store(home):
  return ReviewerAuthorityStore(account_home=home)


def test_missing_read_and_update_create_no_control_or_budget(account):
  value = store(account)
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_MISSING"):
    value.read()
  next_document = authority(); next_document["generation"] = 2
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_MISSING"):
    value.update(next_document, expected_identity="0" * 64)
  assert list(account.iterdir()) == []


def test_private_shared_file_deepcopy_and_no_ledger(account, monkeypatch, tmp_path):
  import agentcfg.pi_registered_roots as roots
  monkeypatch.setattr(roots.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(account)))
  snapshot = ReviewerAuthorityStore().create(authority())
  for name in ("HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME"):
    monkeypatch.setenv(name, str(tmp_path / "unrelated"))
  other = ReviewerAuthorityStore().read()
  assert snapshot == other
  assert path(account).stat().st_mode & 0o777 == 0o600
  assert path(account).parent.stat().st_mode & 0o777 == 0o700
  assert {p.name for p in path(account).parent.iterdir()} == {FILE, "registry.json"}
  assert not (tmp_path / "unrelated").exists()
  snapshot["document"]["limits"]["max_calls"] = 999
  assert store(account).read()["document"]["limits"]["max_calls"] == 20


@pytest.mark.parametrize("kind", ["secret-field", "generation", "boolean", "missing-price"])
def test_invalid_create_writes_nothing(account, kind):
  document = authority()
  if kind == "secret-field": document["route"]["headers"] = {"Authorization": "SYNTHETIC_PRIVATE"}
  if kind == "generation": document["generation"] = 2
  if kind == "boolean": document["generation"] = True
  if kind == "missing-price": document.pop("pricing")
  with pytest.raises(ConfigError) as error:
    store(account).create(document)
  assert error.value.code == "PI_RISK_REVIEW_AUTHORITY_INVALID"
  assert "SYNTHETIC_PRIVATE" not in str(error.value)
  assert list(account.iterdir()) == []


def test_existing_authority_never_overwritten_or_recreated(account):
  value = store(account)
  snapshot = value.create(authority()); before = path(account).read_bytes()
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_EXISTS"):
    value.create(authority())
  assert path(account).read_bytes() == before
  assert value.read() == snapshot


def test_tightening_changes_live_identity_but_does_not_touch_budget(account):
  value = store(account); before = value.create(authority())
  ledger = ReviewerAccountLedger(account_home=account, limits=authority()["limits"])
  ledger.snapshot()
  budget = account / ".agentcfg-workspaces/reviewer-budget"
  untouched = {p: p.read_bytes() for p in budget.iterdir()}
  sentinel = account / ".agentcfg-workspaces/reviewer-budget.json"
  old_sentinel = sentinel.read_bytes()
  document = authority(); document["generation"] = 2; document["limits"]["max_calls"] = 10
  after = value.update(document, expected_identity=before["identity"])
  assert after["identity"] != before["identity"] and after["document_identity"] != before["document_identity"]
  assert after["document"]["limits"]["max_calls"] == 10
  assert {p: p.read_bytes() for p in budget.iterdir()} == untouched and sentinel.read_bytes() == old_sentinel
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"):
    value.verify_current(before["identity"], now=150)
  assert store(account).verify_current(after["identity"], now=150) == after


@pytest.mark.parametrize("kind", ["increase-calls", "increase-cost", "currency", "generation", "ref"])
def test_invalid_update_never_changes_file(account, kind):
  value = store(account); before = value.create(authority()); raw = path(account).read_bytes()
  document = authority(); document["generation"] = 2
  if kind == "increase-calls": document["limits"]["max_calls"] += 1
  if kind == "increase-cost": document["limits"]["max_cost_units"] += 1
  if kind == "currency": document["pricing"]["currency"] = document["limits"]["currency"] = "EUR"
  if kind == "generation": document["generation"] = 3
  if kind == "ref": document["authority_ref"] = "f" * 32
  with pytest.raises(ConfigError): value.update(document, expected_identity=before["identity"])
  assert path(account).read_bytes() == raw and value.read() == before


@pytest.mark.parametrize("kind", ["identical-replace", "inplace"])
def test_same_document_file_change_invalidates_old_identity(account, kind):
  value = store(account); old = value.create(authority()); raw = path(account).read_bytes()
  if kind == "identical-replace":
    with Tree(path(account).parent) as tree:
      saved = tree.read(FILE)
      tree.replace(FILE, raw, expected=saved[2])
  else: path(account).write_bytes(raw)
  after = store(account).read()
  assert after["document_identity"] == old["document_identity"] and after["identity"] != old["identity"]
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"):
    value.verify_current(old["identity"], now=150)
  document = authority(); document["generation"] = 2
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"):
    value.update(document, expected_identity=old["identity"])


@pytest.mark.parametrize("kind", ["missing", "symlink", "hardlink", "fifo", "mode", "duplicate", "unknown", "oversize", "anchor-replaced"])
def test_missing_invalid_or_replaced_state_never_authorizes(account, tmp_path, kind):
  value = store(account); old = value.create(authority())
  target = path(account)
  if kind == "missing": target.unlink()
  if kind == "symlink":
    clone = tmp_path / "outside"; clone.write_bytes(target.read_bytes()); target.unlink(); target.symlink_to(clone)
  if kind == "hardlink": os.link(target, tmp_path / "outside")
  if kind == "fifo": target.unlink(); os.mkfifo(target, 0o600)
  if kind == "mode": target.chmod(0o644)
  if kind == "duplicate": target.write_bytes(target.read_bytes().replace(b'"generation":', b'"generation":1,"generation":', 1))
  if kind == "unknown":
    document = authority(); document["credential"] = "SYNTHETIC_PRIVATE"; target.write_bytes(json.dumps(document).encode())
  if kind == "oversize": target.write_bytes(b" " * 16385)
  if kind == "anchor-replaced":
    target.parent.rename(account / "detached"); target.parent.mkdir(mode=0o700)
  for controller in (value, store(account)):
    with pytest.raises((Conflict, ConfigError)) as error:
      controller.verify_current(old["identity"], now=150)
    assert "SYNTHETIC_PRIVATE" not in str(error.value)


@pytest.mark.parametrize("fault", ["before", "after"])
def test_update_ack_loss_is_unconfirmed_without_retry(account, monkeypatch, fault):
  value = store(account); old = value.create(authority())
  document = authority(); document["generation"] = 2
  original = Tree.replace; writes = []
  def replace(tree, name, data, *args, **kwargs):
    if name != FILE: return original(tree, name, data, *args, **kwargs)
    writes.append(name)
    if fault == "before": raise OSError("SYNTHETIC_PRIVATE")
    result = original(tree, name, data, *args, **kwargs)
    raise OSError("SYNTHETIC_PRIVATE")
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_WRITE_UNCONFIRMED$"):
    value.update(document, expected_identity=old["identity"])
  assert writes == [FILE]
  observed = value.read()
  assert observed["document"]["generation"] == (1 if fault == "before" else 2)
  assert (observed["identity"] == old["identity"]) is (fault == "before")


def test_missing_authority_with_existing_budget_requires_recovery(account):
  value = store(account); value.create(authority())
  ReviewerAccountLedger(account_home=account, limits=authority()["limits"])
  path(account).unlink()
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_RECOVERY_REQUIRED"):
    value.create(authority())
  assert not path(account).exists()


@pytest.mark.parametrize("now", [99, 200, 201])
def test_expired_or_not_yet_effective_authority_is_only_passive_observation(account, now):
  value = store(account); snapshot = value.create(authority())
  assert value.read() == snapshot
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_INACTIVE"):
    value.verify_current(snapshot["identity"], now=now)
  assert value.verify_current(snapshot["identity"], now=100) == snapshot


def test_account_lock_busy_writes_nothing_and_returns_fixed_code(account, monkeypatch):
  import agentcfg.pi_registered_roots as roots
  value = store(account); old = value.create(authority()); raw = path(account).read_bytes()
  def busy(fd, flags): raise BlockingIOError("SYNTHETIC_PRIVATE")
  monkeypatch.setattr(roots.fcntl, "flock", busy)
  with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"):
    value.read()
  assert path(account).read_bytes() == raw


def initialize_registry(account):
  """只初始化合成空registry；不构造budget，也不依赖宿主Git祖先。"""
  from agentcfg.pi_registered_roots import RegisteredRoots
  roots = RegisteredRoots(account_home=account)
  with roots._locked(write=True) as account_fd:
    with roots._state(account_fd, create=True) as (tree, document, raw):
      assert raw is None
      tree.replace("registry.json", json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii"), expected=None)
  return roots


@pytest.mark.parametrize("fault", ["before", "after"])
def test_initial_authority_ack_loss_existing_registry_no_retry(account, monkeypatch, fault):
  initialize_registry(account)
  value = store(account); original = Tree.replace; writes = []
  def replace(tree, name, data, *args, **kwargs):
    if name != FILE: return original(tree, name, data, *args, **kwargs)
    writes.append(name)
    if fault == "before": raise OSError("SYNTHETIC_PRIVATE_ACK")
    original(tree, name, data, *args, **kwargs)
    raise OSError("SYNTHETIC_PRIVATE_ACK")
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_WRITE_UNCONFIRMED$") as error:
    value.create(authority())
  assert "SYNTHETIC_PRIVATE_ACK" not in str(error.value) and writes == [FILE]
  if fault == "after":
    observed = store(account).read()
    assert observed["document"] == authority() and observed["document"]["generation"] == 1
    with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_EXISTS$"): store(account).create(authority())
    assert writes == [FILE]
  else:
    assert not path(account).exists()
    with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_MISSING$"): store(account).read()
  assert {p.name for p in path(account).parent.iterdir()} == ({"registry.json", FILE} if fault == "after" else {"registry.json"})


@pytest.mark.parametrize("fault", ["before", "after"])
def test_initial_registry_ack_loss_never_writes_authority_or_retries(account, monkeypatch, fault):
  original = Tree.replace; writes = []
  def replace(tree, name, data, *args, **kwargs):
    writes.append(name)
    if name == "registry.json":
      if fault == "after": original(tree, name, data, *args, **kwargs)
      raise OSError("SYNTHETIC_PRIVATE_REGISTRY_ACK")
    return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_WRITE_UNCONFIRMED$") as error:
    store(account).create(authority())
  assert writes == ["registry.json"] and not path(account).exists()
  assert "SYNTHETIC_PRIVATE_REGISTRY_ACK" not in str(error.value)
  registry = path(account).parent / "registry.json"
  assert registry.exists() is (fault == "after")
  if fault == "after":
    with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_MISSING$"): store(account).read()
  else:
    with pytest.raises(Conflict): store(account).read()
  assert writes == ["registry.json"] and not path(account).exists()


def test_same_expected_identity_two_controllers_only_first_update_wins(account, monkeypatch):
  first, second = store(account), store(account)
  old = first.create(authority()); assert second.read() == old
  one = authority(); one["generation"] = 2; one["limits"]["max_calls"] = 10
  two = authority(); two["generation"] = 2; two["limits"]["max_calls"] = 5
  writes = []; original = Tree.replace
  def replace(tree, name, data, *args, **kwargs):
    if name == FILE: writes.append(data)
    return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace)
  winner = first.update(one, expected_identity=old["identity"])
  raw = path(account).read_bytes()
  with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_STALE$"):
    second.update(two, expected_identity=old["identity"])
  assert len(writes) == 1 and path(account).read_bytes() == raw
  assert second.read() == winner and winner["document"]["generation"] == 2
  assert winner["document"]["limits"]["max_calls"] == 10


@pytest.mark.parametrize("invalid", [True, False, 150.0, "150", None])
def test_invalid_active_clock_and_expected_identity_never_write(account, monkeypatch, invalid):
  value = store(account); old = value.create(authority()); raw = path(account).read_bytes()
  writes = []; original = Tree.replace
  def replace(tree, name, data, *args, **kwargs):
    writes.append(name); return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(ConfigError) as error: value.active(now=invalid)
  assert error.value.code == "PI_RISK_REVIEW_AUTHORITY_INVALID"
  with pytest.raises(ConfigError): value.verify_current(old["identity"], now=invalid)
  with pytest.raises(ConfigError): value.verify_current(invalid, now=150)
  document = authority(); document["generation"] = 2
  with pytest.raises(ConfigError): value.update(document, expected_identity=invalid)
  assert writes == [] and path(account).read_bytes() == raw and value.read() == old


@pytest.mark.parametrize("expected", ["", "A" * 64, "a" * 63, "a" * 65, "SYNTHETIC_PRIVATE_EXPECTED"])
def test_malformed_expected_is_fixed_error_and_has_no_write(account, monkeypatch, expected):
  value = store(account); value.create(authority()); raw = path(account).read_bytes()
  monkeypatch.setattr(Tree, "replace", lambda *a, **k: pytest.fail("invalid expected wrote"))
  document = authority(); document["generation"] = 2
  with pytest.raises(ConfigError) as error: value.update(document, expected_identity=expected)
  assert error.value.code == "PI_RISK_REVIEW_AUTHORITY_INVALID"
  if expected: assert expected not in str(error.value)
  with pytest.raises(ConfigError): value.verify_current(expected, now=150)
  assert path(account).read_bytes() == raw


def test_future_authority_passive_read_preserves_schema2_live_claims(account, tmp_path, monkeypatch):
  """真实临时WorkspaceClaims事务；进程/模型均不启动，也不扩充OS探针。"""
  from agentcfg.pi_registered_roots import RegisteredRoots
  from agentcfg.workspace_leases import WorkspaceLeases
  from test_pi_workspace_leases import allocation, worktree
  import agentcfg.pi_registered_roots as roots
  original_marker = roots._has_git_marker
  monkeypatch.setattr(roots.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(account)))
  monkeypatch.setattr(roots, "_has_git_marker", lambda directory: original_marker(directory) if directory.is_relative_to(tmp_path) else False)
  registry = RegisteredRoots(account_home=account)
  business = tmp_path / "registered-business"; business.mkdir(mode=0o700)
  registered = registry.register(business)
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path)); lease = allocation(planned); lease["allocation_journal_digest"] = "e" * 64
  manager.reserve(planned, lease)
  anchor = account / ".agentcfg-workspaces"
  before_registry = (anchor / "registry.json").read_bytes(); before_claims = (anchor / "claims.json").read_bytes()
  assert json.loads(before_registry)["schema_version"] == 2
  document = authority(); document.update(valid_from=300, valid_until=400)
  snapshot = store(account).create(document)
  assert store(account).read() == snapshot
  with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_INACTIVE$"): store(account).active(now=150)
  assert (anchor / "registry.json").read_bytes() == before_registry and (anchor / "claims.json").read_bytes() == before_claims
  assert registry.list() == [registered] and manager.read(planned)["execution_lease_id"] == lease["lease_id"]
