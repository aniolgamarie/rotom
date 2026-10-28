"""跨请求恢复防重；真实私人目录锁、严格 owner 与假宿主。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import errno
import fcntl
import json
import os
import threading

import pytest

from agentcfg import run_owners, sessions
from agentcfg.resume_attempts import ResumeAttempts
from agentcfg.paths import PathError
from agentcfg.storage import Conflict, LockBusy, Tree
from agentcfg import resume_attempts
from test_rotom_resume_attempts import attempt_store
from test_rotom_run_records import store


def publish(journal, owner):
  registry = run_owners.Registry(journal.root.parent / "run-owners", journal.binding)
  with Tree(registry.root, create=True) as tree:
    tree.write_new(owner["run_id"] + ".json", run_owners._encode(owner))
  return registry


def next_owner(journal, owner):
  following = deepcopy(owner)
  following["run_id"] = "c" * 32
  publish(journal, following)
  return following


@pytest.mark.parametrize("previous", ["intent", "active", "unknown", "exited_unknown"])
def test_new_request_same_full_session_ref_is_blocked(attempt_store, previous):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  registry = run_owners.Registry(journal.root.parent / "run-owners", journal.binding)
  if previous != "intent":
    handle.launched()
  if previous == "exited_unknown":
    handle.exited(0)
  if previous in ("unknown", "exited_unknown"):
    registry.mark_unknown(owner["run_id"], owner["manager_identity"])
  following = next_owner(journal, owner)
  fresh = ResumeAttempts(journal.root, journal.binding)
  before = {path.name: path.read_bytes() for path in journal.root.glob("*.json")}
  with pytest.raises(Conflict):
    fresh.begin(target, following)
  assert {path.name: path.read_bytes() for path in journal.root.glob("*.json")} == before


def test_simultaneous_distinct_runs_publish_only_one_intent(attempt_store):
  journal, target, owner = attempt_store
  following = next_owner(journal, owner)
  barrier = threading.Barrier(2)
  def claim(candidate):
    fresh = ResumeAttempts(journal.root, journal.binding)
    barrier.wait(timeout=5)
    try:
      fresh.begin(target, candidate)
      return "claimed"
    except Conflict:
      return "blocked"
  with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(claim, (owner, following)))
  assert sorted(results) == ["blocked", "claimed"]
  assert len(list(journal.root.glob("*.json"))) == 1


@pytest.mark.parametrize("change", ["previous-run", "cwd"])
def test_request_history_or_cwd_does_not_bypass_same_session_claim(attempt_store, tmp_path, change):
  journal, target, owner = attempt_store
  journal.begin(target, owner)
  following = deepcopy(owner)
  following["run_id"] = "c" * 32
  if change == "previous-run":
    target = replace(target, run_id=owner["run_id"])
  else:
    cwd = tmp_path / "another-project"
    cwd.mkdir()
    following["start_cwd"]["path"] = str(cwd)
    target = replace(target, cwd=str(cwd))
  publish(journal, following)
  with pytest.raises(Conflict):
    ResumeAttempts(journal.root, journal.binding).begin(target, following)


@pytest.mark.parametrize("exit_code", [0, 17, 143])
def test_complete_owner_and_saved_exit_allow_new_request_despite_unknown_load(attempt_store, exit_code):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  handle.launched()
  handle.exited(exit_code)
  registry = run_owners.Registry(journal.root.parent / "run-owners", journal.binding)
  registry.finish_current(owner["run_id"], owner["manager_identity"], run_owners.ReleaseObservation(
    run_id=owner["run_id"], manager_identity=owner["manager_identity"], all_related_exited=True, complete=True))
  assert journal.read(owner["run_id"])["load_confirmation"] == "unknown"
  following = next_owner(journal, owner)
  ResumeAttempts(journal.root, journal.binding).begin(target, following)
  assert journal.read(following["run_id"])["dispatch"]["state"] == "intent"


def test_idle_owner_without_attempt_exit_remains_blocked(attempt_store):
  journal, target, owner = attempt_store
  journal.begin(target, owner).launched()
  registry = run_owners.Registry(journal.root.parent / "run-owners", journal.binding)
  registry.finish_current(owner["run_id"], owner["manager_identity"], run_owners.ReleaseObservation(
    run_id=owner["run_id"], manager_identity=owner["manager_identity"], all_related_exited=True, complete=True))
  following = next_owner(journal, owner)
  with pytest.raises(Conflict):
    ResumeAttempts(journal.root, journal.binding).begin(target, following)


@pytest.mark.parametrize("damage", ["missing-owner", "corrupt-owner", "corrupt-attempt", "unknown-attempt-field"])
def test_orphan_or_unreadable_claim_blocks_without_disclosing_data(attempt_store, damage):
  journal, target, owner = attempt_store
  journal.begin(target, owner)
  following = next_owner(journal, owner)
  owner_path = journal.root.parent / "run-owners" / (owner["run_id"] + ".json")
  path = journal.root / (owner["run_id"] + ".json")
  secret = "synthetic-private-canary"
  if damage == "missing-owner":
    owner_path.unlink()
  elif damage == "corrupt-owner":
    owner_path.write_text(secret)
  elif damage == "corrupt-attempt":
    path.write_text(secret)
  else:
    record = json.loads(path.read_bytes())
    record["private"] = secret
    path.write_text(json.dumps(record))
  before = path.read_bytes()
  with pytest.raises(Conflict) as caught:
    ResumeAttempts(journal.root, journal.binding).begin(target, following)
  assert secret not in str(caught.value)
  assert path.read_bytes() == before
  assert not (journal.root / (following["run_id"] + ".json")).exists()


def test_different_native_session_does_not_block_or_become_current_session(attempt_store):
  journal, target, owner = attempt_store
  journal.begin(target, owner)
  following = next_owner(journal, owner)
  other = replace(target, ref=replace(target.ref, native_ref="another-session"))
  ResumeAttempts(journal.root, journal.binding).begin(other, following)
  assert journal.for_owner(following)["requested_session"]["native_ref"] == "another-session"
  assert following["session_observation"] is None and following["session_cwd"] is None


@pytest.mark.parametrize("dimension", ["profile", "local", "home"])
def test_separate_managed_scope_can_claim_same_native_id(attempt_store, tmp_path, dimension):
  journal, target, owner = attempt_store
  journal.begin(target, owner)
  binding = deepcopy(journal.binding)
  following = deepcopy(owner)
  following["run_id"] = "c" * 32
  if dimension == "profile":
    binding["profile"] = following["profile"] = "another-profile"
  elif dimension == "local":
    binding["local"] = str(tmp_path / "another-local.toml")
    following["machine_ref"]["local"] = binding["local"]
  else:
    following["native_home_ref"]["path"] = str(tmp_path / "another-native-home")
  root = journal.root if dimension == "home" else tmp_path / ("separate-" + dimension) / "resume-attempts"
  other = ResumeAttempts(root, binding)
  following["binding_digest"] = other.binding_digest
  publish(other, following)
  from agentcfg.dsh_sessions import scope_key
  other_target = replace(target, scope=scope_key(binding), profile=following["profile"],
    ref=replace(target.ref, native_home_ref=run_owners.native_home_key(following["native_home_ref"])))
  other.begin(other_target, following)
  assert other.read(following["run_id"])["dispatch"]["state"] == "intent"


def test_real_first_lock_contention_can_proceed_after_release(attempt_store, monkeypatch):
  journal, target, owner = attempt_store
  fd = os.open(journal.root.parent / "run-owners", os.O_RDONLY | os.O_DIRECTORY)
  fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  waiting = threading.Event()
  sleep = resume_attempts.time.sleep
  def observed_wait(seconds):
    waiting.set()
    sleep(seconds)
  monkeypatch.setattr(resume_attempts.time, "sleep", observed_wait)
  try:
    with ThreadPoolExecutor(max_workers=1) as pool:
      pending = pool.submit(journal.begin, target, owner)
      try:
        assert waiting.wait(timeout=1)
      finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
      pending.result(timeout=3)
  finally:
    os.close(fd)
  assert journal.read(owner["run_id"])["dispatch"]["state"] == "intent"


def test_permission_lock_failure_does_not_wait_or_retry(attempt_store, monkeypatch):
  journal, target, owner = attempt_store
  calls = []
  def denied(fd, flags):
    calls.append(flags)
    raise PermissionError(errno.EACCES, "synthetic-private-canary")
  monkeypatch.setattr(resume_attempts.fcntl, "flock", denied)
  monkeypatch.setattr(resume_attempts.time, "sleep", lambda seconds: pytest.fail("permission failure waited"))
  with pytest.raises(Conflict) as caught:
    journal.begin(target, owner)
  assert not isinstance(caught.value, LockBusy)
  assert calls == [fcntl.LOCK_EX | fcntl.LOCK_NB]
  assert "synthetic-private-canary" not in str(caught.value)
  assert not journal.root.exists()


@pytest.mark.parametrize("published", [False, True])
def test_body_lockbusy_never_replays_intent_write(attempt_store, monkeypatch, published):
  journal, target, owner = attempt_store
  write = Tree.write_new
  calls = []
  def lost(tree, *args, **kwargs):
    calls.append(args[0])
    if published:
      write(tree, *args, **kwargs)
    raise LockBusy("synthetic acknowledgement unavailable")
  monkeypatch.setattr(Tree, "write_new", lost)
  monkeypatch.setattr(resume_attempts.time, "sleep", lambda seconds: pytest.fail("body failure waited"))
  with pytest.raises(LockBusy):
    journal.begin(target, owner)
  assert calls == [owner["run_id"] + ".json"]
  record = journal.read(owner["run_id"])
  assert (record is not None) is published
  if published:
    assert record["dispatch"]["state"] == "intent"


@pytest.mark.parametrize("operation", ["begin", "check_pending"])
@pytest.mark.parametrize("damage", ["permissions", "symlink"])
def test_unsafe_admission_path_is_conflict_without_write_or_retry(attempt_store, tmp_path,
    monkeypatch, operation, damage):
  journal, target, owner = attempt_store
  if damage == "permissions":
    journal.root.mkdir(mode=0o755)
    journal.root.chmod(0o755)
  else:
    replacement = tmp_path / "untrusted-replacement"
    replacement.mkdir(mode=0o700)
    journal.root.symlink_to(replacement)
  monkeypatch.setattr(Tree, "write_new", lambda *args, **kwargs: pytest.fail("unsafe admission wrote"))
  monkeypatch.setattr(resume_attempts.time, "sleep", lambda seconds: pytest.fail("unsafe admission retried"))
  with pytest.raises(Conflict) as caught:
    getattr(journal, operation)(target, owner)
  assert caught.value.exit_code == 4


@pytest.mark.parametrize("kind", [OSError, PathError])
def test_admission_body_filesystem_failure_keeps_one_possible_commit(attempt_store, monkeypatch, kind):
  journal, target, owner = attempt_store
  write = Tree.write_new
  calls = []
  def lost(tree, *args, **kwargs):
    calls.append(args[0])
    write(tree, *args, **kwargs)
    raise kind("synthetic-private-canary")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", lost)
    patch.setattr(resume_attempts.time, "sleep", lambda seconds: pytest.fail("filesystem failure retried"))
    with pytest.raises(Conflict) as caught:
      journal.begin(target, owner)
  assert caught.value.exit_code == 4 and "synthetic-private-canary" not in str(caught.value)
  assert calls == [owner["run_id"] + ".json"]
  assert journal.read(owner["run_id"])["dispatch"]["state"] == "intent"


def test_4097_healthy_historical_sessions_do_not_globally_block_new_session(attempt_store, monkeypatch):
  journal, target, owner = attempt_store
  journal.root.mkdir(mode=0o700)
  identity = journal.root.stat()
  history = {}
  prior_owners = {}
  for index in range(4097):
    run_id = format(index + 1, "032x")
    prior = deepcopy(owner)
    prior["run_id"] = run_id
    run_owners._set_state(prior, "idle_confirmed")
    journal._registry._validate_record(run_id + ".json", prior)
    prior_owners[run_id] = prior
    history[run_id] = {"schema_version": 1, "binding_digest": journal.binding_digest,
      "run_id": run_id, "manager_identity": deepcopy(owner["manager_identity"]),
      "requested": {"session": {**vars(target.ref), "native_ref": "historical-" + str(index)},
        "cwd": target.cwd, "previous_run_id": target.run_id},
      "dispatch": {"state": "launched", "observed_at_ns": 1}, "exit_code": 0,
      "load_confirmation": "unknown", "continue_status": "not_sent"}
  listdir, read, records = os.listdir, journal._read, run_owners.Registry._records
  def listed(fd):
    if type(fd) is not int:
      return listdir(fd)
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
      return [run_id + ".json" for run_id in history] + listdir(fd)
    return listdir(fd)
  def historical(tree, run_id):
    if run_id in history:
      journal._validate(run_id, history[run_id])
      return deepcopy(history[run_id]), None
    return read(tree, run_id)
  def owners(registry, tree):
    saved, originals = records(registry, tree)
    return ({**saved, **prior_owners}, originals) if registry.root.name == "run-owners" else (saved, originals)
  # 仅以受控元数据替代历史文件IO；保留严格schema、真实锁和本次intent写入。
  monkeypatch.setattr(os, "listdir", listed)
  monkeypatch.setattr(journal, "_read", historical)
  monkeypatch.setattr(run_owners.Registry, "_records", owners)
  journal.begin(target, owner)
  assert journal.read(owner["run_id"])["dispatch"]["state"] == "intent"


@pytest.mark.parametrize("stage", ["write", "sync"])
def test_intent_commit_does_not_hold_owner_metadata_lock(attempt_store, monkeypatch, stage):
  journal, target, owner = attempt_store
  checked = []
  def independent_owner_lock():
    fd = os.open(journal.root.parent / "run-owners", os.O_RDONLY | os.O_DIRECTORY)
    try:
      try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      except BlockingIOError:
        return False
      return True
    finally:
      os.close(fd)
  with ThreadPoolExecutor(max_workers=1) as pool:
    def verify():
      acquired = pool.submit(independent_owner_lock).result(timeout=2)
      checked.append(acquired)
      assert acquired, "intent commit retained the owner metadata lock"
    if stage == "write":
      write = Tree.write_new
      def writing(tree, *args, **kwargs):
        if tree.root == journal.root:
          verify()
        return write(tree, *args, **kwargs)
      monkeypatch.setattr(Tree, "write_new", writing)
    else:
      sync = resume_attempts.storage.sync_directory_ancestors
      def syncing(path):
        verify()
        return sync(path)
      monkeypatch.setattr(resume_attempts.storage, "sync_directory_ancestors", syncing)
    journal.begin(target, owner)
  assert checked == [True]
  assert journal.read(owner["run_id"])["dispatch"]["state"] == "intent"


def test_attempt_created_after_owner_snapshot_remains_pending_when_owner_was_not_observed(attempt_store,
    monkeypatch):
  journal, target, owner = attempt_store
  original_tree = resume_attempts.Tree
  main_thread = threading.get_ident()
  published = []
  metadata = {key: deepcopy(owner[key]) for key in run_owners._METADATA_FIELDS}
  def competing():
    registry = run_owners.Registry(journal.root.parent / "run-owners", journal.binding)
    run_id = registry.register_v2(owner["manager_identity"], metadata)
    following = registry.snapshot()[run_id]
    ResumeAttempts(journal.root, journal.binding).begin(target, following)
    return run_id
  with ThreadPoolExecutor(max_workers=1) as pool:
    def opening(root, **kwargs):
      if root == journal.root and threading.get_ident() == main_thread and not published:
        published.append(pool.submit(competing).result(timeout=3))
      return original_tree(root, **kwargs)
    pending = journal._pending
    def verify_missing_owner(tree, selected, owners):
      assert published and published[0] not in owners
      return pending(tree, selected, owners)
    monkeypatch.setattr(resume_attempts, "Tree", opening)
    monkeypatch.setattr(journal, "_pending", verify_missing_owner)
    with pytest.raises(resume_attempts.PendingResume) as caught:
      journal.begin(target, owner)
  assert caught.value.run_ids == tuple(published)
  assert journal.read(owner["run_id"]) is None
  assert journal.read(published[0])["dispatch"]["state"] == "intent"


def test_legacy_v1_owner_for_matching_attempt_remains_pending_with_original_run(attempt_store):
  journal, target, owner = attempt_store
  journal.begin(target, owner)
  following = next_owner(journal, owner)
  legacy = {"schema_version": 1, "binding_digest": journal.binding_digest, "run_id": owner["run_id"],
    "manager_identity": deepcopy(owner["manager_identity"]), "session_ref": "synthetic-session",
    "state": "unknown", "affected_resources": deepcopy(owner["affected_resources"]),
    "observation": run_owners._observation("unknown")}
  registry = run_owners.Registry(journal.root.parent / "run-owners", journal.binding)
  registry._validate_record(owner["run_id"] + ".json", legacy)
  with registry._locked() as tree:
    name = owner["run_id"] + ".json"
    raw = tree.read(name)
    tree.replace(name, run_owners._encode(legacy), expected=raw[2])
  before = (journal.root / name).read_bytes()
  with pytest.raises(resume_attempts.PendingResume) as caught:
    ResumeAttempts(journal.root, journal.binding).begin(target, following)
  assert caught.value.run_ids == (owner["run_id"],)
  assert (journal.root / name).read_bytes() == before
  assert journal.read(following["run_id"]) is None
