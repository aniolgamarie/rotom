"""准入账本接真实文件/Writer事务；只有临时树、虚构身份和假进程。"""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from agentcfg.pi_admitted_files import FileOperationAdmissions
from agentcfg.deployment import json_bytes
from agentcfg.pi_resource_reads import tree_digest
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_activity import identity
from test_pi_operation_admission import fixture as ledger_fixture
from test_pi_operations import setup


def fixture(tmp_path, *, profile="pi-base"):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["profile_id"] = profile
  current = ledger_fixture()[1]
  current.update(activation_id=host.store.owner["manager_activation_id"], profile=profile, cwd=cwd,
    runtime_identity=host.runtime_root.name, deadline_ms=int(operations.now().timestamp() * 1000) + 60000)
  requests = []
  def context_provider(request_id):
    requests.append(request_id)
    return deepcopy(current)
  bridge = FileOperationAdmissions(operations, context_provider=context_provider)
  return bridge, operations, host, cwd, principal, current, requests


def prepare(f, *, request_id="sdk-call", tool="write", payload=None):
  if payload is None:
    payload = {"path": "new.txt", "content": "synthetic-private-body"} if tool == "write" else {"path": "code.txt"}
  return f[0].prepare(f[4], request_id, tool, payload)


def issue(f, prepared, *, source="human", principal=None, **options):
  return f[0].issue(principal or f[4], prepared["operation_id"], operation_digest=prepared["operation_digest"], source=source, **options)


def external(host):
  return [row for row in host.store.records() if row["kind"] == "external"]


def disk_snapshot(root):
  return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def no_writer(f):
  assert external(f[2]) == []
  assert not (Path(f[3]) / ".git/agentcfg/write-lease.json").exists()
  assert not list((f[2].root / "activity/ordinary-operations").glob("*.json"))
  assert not (Path(f[3]) / "new.txt").exists()


@pytest.mark.parametrize("tool", ["ls", "find", "grep"])
def test_deterministic_enumeration_uses_consumed_source_without_ui_or_writer(tmp_path, tool):
  f = fixture(tmp_path)
  rule = f[2].manifest()["permission_policy"]["rules"][0]
  rule.update(approval="deterministic-policy", tool_ids=["read", "write", "edit", "ls", "find", "grep"],
    operations=["read", "write", "create", "list", "search"])
  prepared = prepare(f, tool=tool, payload={"path": ".", **({"pattern": "**/*"} if tool == "find" else {"pattern": "source"} if tool == "grep" else {})})
  assert prepared["resolution"]["policy"]["approval"] == "deterministic-policy"
  ticket = f[0].consume(f[4], issue(f, prepared, source="deterministic-policy"))
  value = f[1].inputs[ticket["operation_id"]]
  assert value["approval_source"] == "deterministic-policy"
  assert f[1].policy(value).approval_ceiling == "deterministic-policy"
  listed = f[1].listing(f[4], {"operation_id": ticket["operation_id"]})
  assert any(item["path"] == "code.txt" for item in listed["entries"])
  if tool == "grep":
    raw = f[1].read(f[4], {"operation_id": ticket["operation_id"], "relative_path": "code.txt", "offset": 0, "limit": 65536})
    assert base64.b64decode(raw["data_b64"]) == b"source"
  assert external(f[2]) == []
  with pytest.raises(Conflict): f[0].consume(f[4], issue(f, prepared, source="deterministic-policy"))


def test_missing_consumed_source_cannot_reopen_execution_authority(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f, tool="read")
  ticket = f[0].consume(f[4], issue(f, prepared))
  value = f[1].inputs[ticket["operation_id"]]
  value.pop("approval_source")
  with pytest.raises(Conflict, match="OPERATION_ADMISSION_REQUIRED"):
    f[1].read(f[4], {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})


def test_stricter_classification_after_ledger_consume_fails_before_writer_allocation(tmp_path, monkeypatch):
  f = fixture(tmp_path)
  f[2].manifest()["permission_policy"]["rules"][0]["approval"] = "deterministic-policy"
  prepared = prepare(f); permit = issue(f, prepared, source="deterministic-policy")
  original = f[1].preview
  def changed(value):
    approval = original(value)
    return "human" if value["state"] == "revoked" else approval
  monkeypatch.setattr(f[1], "preview", changed)
  with pytest.raises(Conflict, match="OPERATION_APPROVAL_REQUIRED"):
    f[0].consume(f[4], permit)
  assert f[0].ledger.status(prepared["operation_id"])["state"] == "consumed"
  assert external(f[2]) == []
  assert not (Path(f[3]) / "new.txt").exists()
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  with pytest.raises(Conflict): issue(f, prepared, source="deterministic-policy")


@pytest.mark.parametrize("tool", ["ls", "find", "grep"])
def test_actual_manifest_change_during_enumeration_discards_result_and_cannot_replay(tmp_path, tool, monkeypatch):
  from agentcfg import pi_operations
  f = fixture(tmp_path)
  rule = f[2].manifest()["permission_policy"]["rules"][0]
  rule.update(approval="deterministic-policy", tool_ids=["read", "write", "edit", "ls", "find", "grep"],
    operations=["read", "write", "create", "list", "search"])
  prepared = prepare(f, tool=tool, payload={"path": ".", **({"pattern": "**/*"} if tool == "find" else {"pattern": "source"} if tool == "grep" else {})})
  permit = issue(f, prepared, source="deterministic-policy")
  ticket = f[0].consume(f[4], permit)
  original = pi_operations.os.listdir
  changed = []
  def listing(fd):
    names = original(fd)
    if not changed:
      rule["approval"] = "human"
      changed.append(True)
    return names
  with monkeypatch.context() as patch:
    patch.setattr(pi_operations.os, "listdir", listing)
    with pytest.raises(Conflict, match="PERMISSION_STALE"):
      f[1].listing(f[4], {"operation_id": ticket["operation_id"]})
  assert changed and external(f[2]) == []
  assert f[0].ledger.status(prepared["operation_id"])["state"] == "consumed"
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  with pytest.raises(Conflict): issue(f, prepared, source="deterministic-policy")


def test_policy_changes_while_reading_cannot_publish_cached_body(tmp_path, monkeypatch):
  from contextlib import contextmanager
  f = fixture(tmp_path); prepared = prepare(f, tool="read")
  ticket = f[0].consume(f[4], issue(f, prepared))
  original = Tree.open_read
  @contextmanager
  def changing(tree, *args, **kwargs):
    with original(tree, *args, **kwargs) as opened:
      f[2].manifest()["permission_policy"]["rules"][0]["approval"] = "reviewer"
      yield opened
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "open_read", changing)
    with pytest.raises(Conflict, match="PERMISSION_STALE"):
      f[1].read(f[4], {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert "read_cache" not in f[1].inputs[ticket["operation_id"]]
  assert f[0].ledger.status(prepared["operation_id"])["state"] == "consumed"


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_prepare_and_human_issue_do_not_persist_or_reserve_writer(tmp_path, profile):
  f = fixture(tmp_path, profile=profile)
  before = disk_snapshot(tmp_path)
  prepared = prepare(f)
  assert prepare(f) == prepared
  assert prepared["context"] == f[5]
  assert prepared["resolution"]["policy"]["requires_human"] is True
  assert prepared["resolution"]["target"]["path"] == str(Path(f[3]) / "new.txt")
  assert prepared["resolution"]["workspace_keys"]
  assert prepared["resolution"]["write_roots"]
  issue(f, prepared)
  assert disk_snapshot(tmp_path) == before
  no_writer(f)
  assert f[6] and set(f[6]) == {"sdk-call"}


def test_read_consume_uses_parent_lease_and_real_guarded_file_read(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f, tool="read")
  ticket = f[0].consume(f[4], issue(f, prepared))
  assert ticket["state"] == "consumed" and ticket["write"] is False
  assert ticket["lease_id"] == f[4].lease_id
  data = f[1].read(f[4], {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert base64.b64decode(data["data_b64"]) == b"source"
  assert external(f[2]) == []
  assert f[0].status(f[4], prepared["operation_id"])["execution"] == ticket


def test_write_consume_then_actual_worker_perform_uses_one_reserved_writer(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f)
  ticket = f[0].consume(f[4], issue(f, prepared))
  assert ticket["state"] == "consumed" and ticket["write"] is True
  lease = f[2].store.read(ticket["lease_id"])
  assert external(f[2]) == [lease]
  assert lease["state"] == "allocating" and not lease["spawn_committed"]
  assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  assert not (Path(f[3]) / "new.txt").exists()
  f[1].stage_write(f[4], {"operation_id": ticket["operation_id"], "content": "synthetic-private-body", "expected_digest": None})
  f[2].store.processes.current[203] = identity(203)
  f[2].store.start(ticket["lease_id"], f[2].store.owner, spawn=lambda _: identity(203))
  worker = Principal("worker", ticket["lease_id"], lease["grant_generation"])
  result = f[1].perform(worker, {"operation_id": ticket["operation_id"]})
  assert result["changed"] is True
  assert (Path(f[3]) / "new.txt").read_text() == "synthetic-private-body"


@pytest.mark.parametrize("source", ["deterministic-policy", "reviewer"])
def test_initial_bridge_cannot_replace_human_approval_with_other_source(tmp_path, source):
  f = fixture(tmp_path); prepared = prepare(f)
  with pytest.raises((Conflict, ConfigError)):
    issue(f, prepared, source=source)
  no_writer(f)
  assert f[0].consume(f[4], issue(f, prepared))["state"] == "consumed"


@pytest.mark.parametrize("change", ["digest", "source", "context", "extra"])
def test_tampered_permit_is_burned_without_writer_and_original_cannot_replay(tmp_path, change):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared); bad = deepcopy(permit)
  if change == "digest": bad["operation_digest"] = "9" * 64
  elif change == "source": bad["source"] = "deterministic-policy"
  elif change == "context": bad["context"]["config_identity"] = "9" * 64
  else: bad["allow"] = True
  with pytest.raises((Conflict, ConfigError)): f[0].consume(f[4], bad)
  no_writer(f)
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  with pytest.raises(Conflict): issue(f, prepared)


def test_permit_replay_cannot_allocate_a_second_writer(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  ticket = f[0].consume(f[4], permit)
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  assert len(external(f[2])) == 1
  assert f[0].status(f[4], prepared["operation_id"])["execution"] == ticket


@pytest.mark.parametrize("field", ["cancel_epoch", "config_identity", "runtime_identity", "user_intent_ref", "restrictions_digest", "policy_generation", "session_id", "deadline_ms"])
def test_late_trusted_context_change_invalidates_consumption(tmp_path, field):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  if field in ("cancel_epoch", "policy_generation", "deadline_ms"): f[5][field] += 1
  else: f[5][field] = "9" * 64
  with pytest.raises((Conflict, ConfigError)): f[0].consume(f[4], permit)
  no_writer(f)
  f[5].update(prepared["context"])
  with pytest.raises(Conflict): f[0].consume(f[4], permit)


@pytest.mark.parametrize("change", ["policy", "root"])
def test_actual_permission_or_root_drift_cannot_reuse_human_permit(tmp_path, change):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  if change == "policy": f[2].manifest()["permission_policy"]["rules"][0]["effect"] = "deny"
  else:
    path = Path(f[3]); path.rename(path.with_name("original-root")); path.mkdir()
  with pytest.raises((Conflict, ConfigError)): f[0].consume(f[4], permit)
  assert external(f[2]) == []
  assert not (Path(f[3]) / "new.txt").exists()
  with pytest.raises(Conflict): f[0].consume(f[4], permit)


@pytest.mark.parametrize("method", ["prepare", "issue", "consume", "status", "revoke"])
@pytest.mark.parametrize("caller", ["worker", "other-manager", "generation"])
def test_admission_does_not_cross_principal_or_manager_generation(tmp_path, method, caller):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  if caller == "worker": principal = Principal("worker", f[4].lease_id, f[4].grant_generation)
  elif caller == "other-manager": principal = Principal("manager", "foreign-manager", f[4].grant_generation)
  else: principal = Principal("manager", f[4].lease_id, f[4].grant_generation + 1)
  actions = {
    "prepare": lambda: f[0].prepare(principal, "foreign", "write", {"path": "new.txt", "content": "foreign"}),
    "issue": lambda: issue(f, prepared, principal=principal),
    "consume": lambda: f[0].consume(principal, permit),
    "status": lambda: f[0].status(principal, prepared["operation_id"]),
    "revoke": lambda: f[0].revoke(principal, prepared["operation_id"]),
  }
  with pytest.raises(Conflict): actions[method]()
  no_writer(f)
  # 外来调用不得消费真正manager的许可。
  assert f[0].consume(f[4], permit)["state"] == "consumed"


def test_lost_allocation_response_keeps_unknown_writer_and_status_never_retries(tmp_path, monkeypatch):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  allocate = f[2].store.allocate; calls = []
  def lose_response(**kwargs):
    lease = allocate(**kwargs); calls.append(lease["lease_id"])
    raise Conflict("SYNTHETIC_ALLOCATION_RESPONSE_LOST")
  monkeypatch.setattr(f[2].store, "allocate", lose_response)
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  assert len(calls) == 1 and len(external(f[2])) == 1
  before = disk_snapshot(tmp_path)
  first = f[0].status(f[4], prepared["operation_id"])
  assert first["admission"]["state"] == "consumed"
  assert first["execution"]["state"] == "unknown" and first["execution"]["lease_id"] == calls[0]
  assert f[0].status(f[4], prepared["operation_id"]) == first
  f[0].revoke(f[4], prepared["operation_id"])
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  assert len(calls) == 1 and disk_snapshot(tmp_path) == before
  lease = f[2].store.read(calls[0])
  assert f[2].store.reconcile(calls[0])["protected"] is True
  assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"


def test_status_is_readonly_and_returned_projection_cannot_modify_ledger(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f)
  before = disk_snapshot(tmp_path)
  observed = f[0].status(f[4], prepared["operation_id"])
  assert observed["admission"]["state"] == "prepared"
  assert observed["execution"]["lease_id"] is None
  observed["admission"]["state"] = "consumed"; observed["execution"]["lease_id"] = "forged"
  actual = f[0].status(f[4], prepared["operation_id"])
  assert actual["admission"]["state"] == "prepared" and actual["execution"]["lease_id"] is None
  assert disk_snapshot(tmp_path) == before
  no_writer(f)


def test_same_request_body_conflict_and_nonce_do_not_expose_private_hash(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f)
  with pytest.raises(Conflict): prepare(f, payload={"path": "new.txt", "content": "changed"})
  other = prepare(f, request_id="another-call")
  assert other["private_input_ref"] != prepared["private_input_ref"]
  assert other["operation_digest"] != prepared["operation_digest"]
  public = json.dumps([prepared, other, issue(f, prepared), f[0].status(f[4], prepared["operation_id"])])
  body = "synthetic-private-body"
  payload = {"path": "new.txt", "content": body}
  assert body not in public
  assert hashlib.sha256(body.encode()).hexdigest() not in public
  assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() not in public
  no_writer(f)


@pytest.mark.parametrize("field", ["activation_id", "runtime_identity", "profile", "role_id"])
def test_prepare_requires_actual_activation_runtime_profile_and_main_role(tmp_path, field):
  f = fixture(tmp_path)
  f[5][field] = "scout" if field == "role_id" else "pi-full" if field == "profile" else "9" * 64
  with pytest.raises((Conflict, ConfigError)): prepare(f)
  no_writer(f)


@pytest.mark.parametrize("method", ["ordinary_prepare", "ordinary_prepare_deferred", "ordinary_consume"])
def test_modern_manifest_cannot_bypass_bridge_via_legacy_file_rpc(tmp_path, method):
  f = fixture(tmp_path)
  args = {"operation_id": "bypass", "role_id": "main", "cwd": f[3], "tool_name": "write", "input": {"path": "new.txt", "content": "unapproved"}}
  if method == "ordinary_consume": args = {"operation_id": "bypass"}
  with pytest.raises(Conflict): f[1].handle(f[4], method, args)
  no_writer(f)


def test_old_profile_keeps_legacy_file_prepare_and_consume_behavior(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["profile_id"] = "pi-development"
  args = {"operation_id": "legacy", "role_id": "main", "cwd": cwd, "tool_name": "write", "input": {"path": "new.txt", "content": "legacy"}}
  prepared = operations.handle(principal, "ordinary_prepare_deferred", args)
  consumed = operations.handle(principal, "ordinary_consume", {"operation_id": prepared["operation_id"]})
  assert consumed["state"] == "consumed" and len(external(host)) == 1


def test_concurrent_bridge_consumers_only_allocate_one_external_lease(tmp_path, monkeypatch):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  allocate = f[2].store.allocate; calls = []
  def counted(**kwargs):
    calls.append(deepcopy(kwargs)); return allocate(**kwargs)
  monkeypatch.setattr(f[2].store, "allocate", counted)
  gate = Barrier(2)
  def consume():
    gate.wait(timeout=5)
    try: return f[0].consume(f[4], permit)
    except Conflict as error: return str(error)
  with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(consume) for _ in range(2)]
    outcomes = [future.result(timeout=5) for future in futures]
  tickets = [value for value in outcomes if type(value) is dict]
  assert len(tickets) == 1 and sum(type(value) is str for value in outcomes) == 1
  assert len(calls) == 1 and len(external(f[2])) == 1
  lease = f[2].store.read(tickets[0]["lease_id"])
  assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"


def test_private_input_and_prepared_projection_do_not_alias_executable_body(tmp_path):
  f = fixture(tmp_path); private = {"path": "new.txt", "content": "approved-body"}
  prepared = prepare(f, payload=private)
  original = deepcopy(prepared)
  private["content"] = "changed-after-prepare"
  prepared["resolution"]["target"]["path"] = str(Path(f[3]) / "forged.txt")
  prepared["context"]["role_id"] = "scout"
  ticket = f[0].consume(f[4], issue(f, original))
  assert ticket["path"] == str(Path(f[3]) / "new.txt")
  with pytest.raises(Conflict):
    f[1].stage_write(f[4], {"operation_id": ticket["operation_id"], "content": "changed-after-prepare", "expected_digest": None})
  f[1].stage_write(f[4], {"operation_id": ticket["operation_id"], "content": "approved-body", "expected_digest": None})
  assert not (Path(f[3]) / "new.txt").exists()


def test_revoke_prepared_operation_does_not_create_writer_or_allow_later_issue(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f)
  before = disk_snapshot(tmp_path)
  revoked = f[0].revoke(f[4], prepared["operation_id"])
  assert revoked["admission"]["state"] == revoked["execution"]["state"] == "revoked"
  with pytest.raises(Conflict): issue(f, prepared)
  assert disk_snapshot(tmp_path) == before
  no_writer(f)


def test_context_failure_is_redacted_and_never_enters_writer_allocation(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["profile_id"] = "pi-base"
  def unavailable(_): raise RuntimeError("synthetic-private-context-marker")
  bridge = FileOperationAdmissions(operations, context_provider=unavailable)
  with pytest.raises(Conflict) as error:
    bridge.prepare(principal, "sdk-call", "write", {"path": "new.txt", "content": "synthetic-private-body"})
  assert "synthetic-private" not in str(error.value)
  assert external(host) == []
  assert not (Path(cwd) / ".git/agentcfg/write-lease.json").exists()


@pytest.mark.parametrize("change", ["context", "policy"])
def test_issue_rechecks_current_context_and_real_hard_policy(tmp_path, change):
  f = fixture(tmp_path); prepared = prepare(f)
  if change == "context": f[5]["cancel_epoch"] += 1
  else: f[2].manifest()["permission_policy"]["rules"][0]["effect"] = "deny"
  with pytest.raises((Conflict, ConfigError)): issue(f, prepared)
  no_writer(f)


@pytest.mark.parametrize("method", ["issue", "consume", "status", "revoke"])
def test_existing_running_other_manager_cannot_use_original_manager_preparation(tmp_path, method):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  other = f[2].store.allocate(kind="host", execution_id="another-manager", task_id=None, attempt_id="another-manager",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None, planned_workspaces=[])
  f[2].store.processes.current[204] = identity(204)
  f[2].store.start(other["lease_id"], f[2].store.owner, spawn=lambda _: identity(204))
  caller = Principal("manager", other["lease_id"], other["grant_generation"])
  actions = {
    "issue": lambda: issue(f, prepared, principal=caller),
    "consume": lambda: f[0].consume(caller, permit),
    "status": lambda: f[0].status(caller, prepared["operation_id"]),
    "revoke": lambda: f[0].revoke(caller, prepared["operation_id"]),
  }
  with pytest.raises(Conflict): actions[method]()
  assert external(f[2]) == []
  assert f[0].consume(f[4], permit)["state"] == "consumed"


def test_retired_physical_preparation_cannot_be_given_a_new_permit(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f)
  ordinary_id = f[0].status(f[4], prepared["operation_id"])["execution"]["operation_id"]
  f[1].handle(f[4], "ordinary_finish", {"operation_id": ordinary_id})
  with pytest.raises(Conflict): issue(f, prepared)
  assert f[0].status(f[4], prepared["operation_id"])["execution"]["state"] == "finished"
  no_writer(f)


def test_known_admitted_ticket_cannot_be_consumed_through_legacy_rpc(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  ordinary_id = f[0].status(f[4], prepared["operation_id"])["execution"]["operation_id"]
  with pytest.raises(Conflict, match="OPERATION_ADMISSION_REQUIRED"):
    f[1].handle(f[4], "ordinary_consume", {"operation_id": ordinary_id})
  no_writer(f)
  assert f[0].consume(f[4], permit)["state"] == "consumed"


@pytest.mark.parametrize("changed", [False, True])
def test_selected_resource_is_bound_to_admission_and_original_content(tmp_path, changed):
  f = fixture(tmp_path)
  from test_pi_resource_read_binding import resource_host
  bound, _, _, _ = resource_host(tmp_path / "bound", "pi-base")
  f[2].runtime_root = bound.runtime_root
  f[2].config.update(lock_identity=bound.config["lock_identity"], slice_identity=bound.config["slice_identity"])
  f[5]["runtime_identity"] = bound.runtime_root.name
  root = Path(f[2].config["instance_root"])
  with Tree(root, create=True) as tree:
    tree.write_state("pi-home/skills/fixture/SKILL.md", b"# synthetic skill")
  skill = root / "pi-home/skills/fixture"
  f[2].manifest()["resources"] = {"skills": ["pi-home/skills/fixture"]}
  f[2].manifest()["resource_ids"]["skills"] = {"fixture": "pi-home/skills/fixture"}
  with Tree(root) as tree:
    tree.write_state("pi-home/loaded-manifest.json", json_bytes({"resources": {"skills": [
      {"id": "fixture", "path": str(skill), "digest": tree_digest(skill), "scope": "instance"}]}}))
  prepared = prepare(f, tool="read", payload={"path": str(skill / "SKILL.md")})
  assert prepared["resolution"]["read_roots"][0]["path"] == str(skill)
  permit = issue(f, prepared)
  if changed:
    (skill / "SKILL.md").write_text("# changed skill")
    with pytest.raises(Conflict): f[0].consume(f[4], permit)
  else:
    ticket = f[0].consume(f[4], permit)
    assert ticket["lease_id"] == f[4].lease_id
    result = f[1].read(f[4], {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
    assert base64.b64decode(result["data_b64"]) == b"# synthetic skill"
  assert external(f[2]) == []

@pytest.mark.parametrize("fault", [None, "unselected", "wrong-cap", "mapping-unknown", "mapping-duplicate", "link", "runtime-mismatch", "schema-mismatch", "profile-mismatch", "auth-entry"])
def test_modern_package_skill_read_uses_explicit_capability_owner_and_never_writer(tmp_path, fault):
  f = fixture(tmp_path, profile="pi-full")
  from test_pi_resource_read_binding import resource_host
  bound, _, _, _ = resource_host(tmp_path / "bound")
  host = f[2]; host.runtime_root = bound.runtime_root; runtime = host.runtime_root
  host.config.update(lock_identity=bound.config["lock_identity"], slice_identity=bound.config["slice_identity"])
  f[5]["runtime_identity"] = runtime.name
  skill = runtime / "skills/selected"
  (skill / "SKILL.md").write_bytes(b"# selected modern delegation instructions")
  manifest = host.manifest()
  manifest["plugins"] = ["model-delegate"]
  manifest["plugin_capabilities"] = {"model-delegate": {"capability_id": "unified-delegate", "model_tools": []}}
  Path(host.config["instance_root"]).mkdir(mode=0o700)
  assert not (Path(host.config["instance_root"]) / "pi-home/loaded-manifest.json").exists()
  if fault == "unselected":
    manifest["plugins"] = []; manifest["plugin_capabilities"] = {}
  elif fault == "wrong-cap":
    manifest["plugin_capabilities"]["model-delegate"]["capability_id"] = "other-cap"
  elif fault == "mapping-unknown":
    manifest["plugin_capabilities"]["model-delegate"]["unknown"] = True
  elif fault == "mapping-duplicate":
    manifest["plugins"].append("other-plugin")
    manifest["plugin_capabilities"]["other-plugin"] = {"capability_id": "unified-delegate", "model_tools": []}
  elif fault == "link":
    (skill / "sibling-link").symlink_to(runtime / "runtime/profile.json")
  elif fault in ("runtime-mismatch", "schema-mismatch", "profile-mismatch", "auth-entry"):
    target = runtime / "runtime/profile.json"
    installed = json.loads(target.read_text())
    if fault == "runtime-mismatch": installed["runtime_identity"] = "f" * 64
    elif fault == "schema-mismatch": installed["schema_version"] = 1
    elif fault == "profile-mismatch": installed["profile_id"] = "pi-base"
    else:
      (runtime / "auth.json").write_bytes(b"synthetic account sentinel")
      installed["resources"]["skills"][0]["path"] = "auth.json"
      skill = runtime
    target.write_text(json.dumps(installed))
  if fault is not None:
    with pytest.raises((Conflict, ConfigError)):
      prepare(f, tool="read", payload={"path": str(runtime / "auth.json" if fault == "auth-entry" else skill / "SKILL.md")})
    assert external(host) == []
    return
  prepared = prepare(f, tool="read", payload={"path": str(skill / "SKILL.md")})
  assert prepared["resolution"]["read_roots"][0]["path"] == str(skill)
  ticket = f[0].consume(f[4], issue(f, prepared, source="human"))
  result = f[1].read(f[4], {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert base64.b64decode(result["data_b64"]) == b"# selected modern delegation instructions"
  with pytest.raises((Conflict, ConfigError)):
    prepare(f, request_id="sibling", tool="read", payload={"path": str(runtime / "runtime/profile.json")})
  assert external(host) == []
