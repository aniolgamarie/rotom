"""准入账本的并发、防重放和秘密边界；不启动宿主或真实进程。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from threading import Barrier

import pytest

from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def fixture(**options):
  clock = [1000]
  ledger = OperationAdmissions("activation", now_ms=lambda: clock[0], **options)
  current = {"activation_id": "activation", "profile": "pi-base", "session_id": "session", "role_id": "main",
    "cwd": "/project", "user_intent_ref": "user-turn-1", "restrictions_digest": "a" * 64,
    "policy_generation": 1, "cancel_epoch": 0, "runtime_identity": "b" * 64, "config_identity": "c" * 64,
    "reviewer_identity": None, "deadline_ms": 5000}
  resolved = {"kind": "file", "tool_name": "write", "target": {"path": "/project/file", "destination": None},
    "read_roots": [], "write_roots": [{"path": "/project", "identity": "d" * 64}], "workspace_keys": ["e" * 64],
    "network": "deny", "services": [], "backend": "guarded-files-v1",
    "policy": {"generation": 1, "policy_digest": "f" * 64, "ceiling_digest": "0" * 64, "hard_policy": "allow", "requires_human": False}}
  private = {"path": "file", "content": "synthetic private token"}
  return ledger, current, resolved, private, clock


def prepare(f, request_id="sdk-call"):
  ledger, current, resolved, private, _ = f
  return ledger.prepare(request_id, current=current, resolved=resolved, private_input=private)


def issue(f, prepared, **options):
  return f[0].issue(prepared["operation_id"], operation_digest=prepared["operation_digest"], current=f[1],
    source=options.pop("source", "deterministic-policy"), **options)


def test_prepare_is_repeatable_and_does_not_expose_private_body_or_hash(tmp_path):
  f = fixture()
  before = sorted(tmp_path.rglob("*"))
  first = prepare(f)
  assert prepare(f) == first
  public = json.dumps(first, sort_keys=True)
  body = f[3]["content"]
  assert body not in public and hashlib.sha256(body.encode()).hexdigest() not in public
  assert hashlib.sha256(json.dumps(f[3], sort_keys=True).encode()).hexdigest() not in public
  assert sorted(tmp_path.rglob("*")) == before
  assert f[0].status(first["operation_id"])["state"] == "prepared"
  # 外部可见投影不能修改控制面保存的准备对象。
  first["resolution"]["target"]["path"] = "/escape"
  assert prepare(f)["resolution"]["target"]["path"] == "/project/file"


@pytest.mark.parametrize("field", ["private", "target", "cwd", "role_id", "policy_generation", "cancel_epoch",
  "runtime_identity", "config_identity", "restrictions_digest", "user_intent_ref", "deadline_ms"])
def test_same_sdk_request_cannot_be_rebound(field):
  f = fixture(); prepare(f)
  if field == "private": f[3]["content"] = "changed body"
  elif field == "target": f[2]["target"]["path"] = "/project/other"
  elif field == "cwd": f[1][field] = "/other"
  elif field in ("policy_generation", "cancel_epoch", "deadline_ms"):
    f[1][field] += 1
    if field == "policy_generation": f[2]["policy"]["generation"] += 1
  else: f[1][field] = "9" * 64
  with pytest.raises(Conflict, match="IDEMPOTENCY_CONFLICT"): prepare(f)


def test_sessions_and_profiles_are_separate_namespaces_but_permits_do_not_cross_them():
  f = fixture(); original = prepare(f); permit = issue(f, original)
  f[1]["session_id"] = "second"
  other = prepare(f)
  assert other["operation_id"] != original["operation_id"]
  with pytest.raises(Conflict, match="CONTEXT_STALE"): f[0].consume(permit, current=f[1], resolved=f[2])
  f[1]["session_id"] = "session"
  with pytest.raises(Conflict, match="PERMIT_USED"): f[0].consume(permit, current=f[1], resolved=f[2])
  f[1]["profile"] = "pi-full"
  assert prepare(f)["operation_id"] != original["operation_id"]


def test_consume_race_returns_exactly_one_executable_object():
  f = fixture(); operation = prepare(f); permit = issue(f, operation)
  barrier = Barrier(2)
  def run():
    barrier.wait(timeout=5)
    try: return f[0].consume(permit, current=f[1], resolved=f[2])
    except Conflict as error: return str(error)
  with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(lambda _: run(), range(2)))
  assert sum(type(row) is dict for row in results) == 1
  assert results.count("OPERATION_PERMIT_USED") == 1
  consumed = next(row for row in results if type(row) is dict)
  assert consumed == {"prepared": operation, "private_input": f[3]}
  # 模拟随后ExecutionStore分配失败：没有回滚许可的入口，也不能补发。
  with pytest.raises(Conflict, match="NOT_PENDING"): issue(f, operation)
  assert f[0].revoke(operation["operation_id"]) == "consumed"


@pytest.mark.parametrize("change", ["digest", "source", "extra", "context", "root", "backend", "malformed"])
def test_failed_consume_burns_ticket_before_recheck(change):
  f = fixture(); operation = prepare(f); permit = issue(f, operation)
  invalid, current, resolved = deepcopy(permit), deepcopy(f[1]), deepcopy(f[2])
  if change == "digest": invalid["operation_digest"] = "9" * 64
  elif change == "source": invalid["source"] = "human"
  elif change == "extra": invalid["allow"] = True
  elif change == "context": current["cancel_epoch"] += 1
  elif change == "root": resolved["write_roots"][0]["identity"] = "9" * 64
  elif change == "backend": resolved["backend"] = "host-shell"
  else: current["unexpected"] = "private secret sentinel"
  with pytest.raises((Conflict, ConfigError)) as error: f[0].consume(invalid, current=current, resolved=resolved)
  assert "private secret sentinel" not in str(error.value)
  with pytest.raises(Conflict, match="PERMIT_USED"): f[0].consume(permit, current=f[1], resolved=f[2])
  with pytest.raises(Conflict, match="NOT_PENDING"): issue(f, operation)


def test_cancellation_expiry_and_restart_never_recreate_authority():
  f = fixture(); operation = prepare(f)
  assert f[0].revoke(operation["operation_id"]) == "revoked"
  assert prepare(f) == operation
  with pytest.raises(Conflict, match="NOT_PENDING"): issue(f, operation)
  active = prepare(f, "second"); permit = issue(f, active)
  f[4][0] = f[1]["deadline_ms"]
  with pytest.raises(Conflict, match="EXPIRED"): f[0].consume(permit, current=f[1], resolved=f[2])
  assert f[0].status(active["operation_id"])["state"] == "expired"
  replacement = OperationAdmissions("new-activation", now_ms=lambda: 1000)
  with pytest.raises(Conflict, match="PERMIT_UNKNOWN"): replacement.consume(permit, current=f[1], resolved=f[2])
  with pytest.raises(Conflict, match="CONTEXT_STALE"):
    replacement.prepare("second", current=f[1], resolved=f[2], private_input=f[3])


def test_human_and_reviewer_sources_do_not_expand_hard_policy():
  f = fixture(); f[2]["policy"]["hard_policy"] = "deny"
  with pytest.raises(Conflict, match="HARD_DENIED"): prepare(f)
  f[2]["policy"]["hard_policy"] = "allow"; f[2]["policy"]["requires_human"] = True
  operation = prepare(f)
  with pytest.raises(Conflict, match="HUMAN_REQUIRED"): issue(f, operation)
  permit = issue(f, operation, source="human")
  assert f[0].consume(permit, current=f[1], resolved=f[2])["prepared"] == operation
  # 显式fake qualifier仅用于此reviewer正控制，不代表产品资格。
  other = fixture(reviewer_current=lambda prepared, current: True); other[1].update(profile="pi-full", reviewer_identity="1" * 64)
  prepared = prepare(other)
  for model in (None, "2" * 64):
    with pytest.raises(Conflict, match="REVIEWER_MISMATCH"): issue(other, prepared, source="reviewer", reviewer_identity=model)
  good = issue(other, prepared, source="reviewer", reviewer_identity="1" * 64)
  assert good["reviewer_identity"] == "1" * 64


@pytest.mark.parametrize("change", ["model_identity", "unknown_tool", "unknown_backend", "service", "network", "relative_cwd", "relative_target",
  "mixed_type", "nan", "float", "bool_epoch", "extra_policy", "no_writer", "base_reviewer"])
def test_unrepresentable_inputs_do_not_produce_prepared_objects(change):
  f = fixture()
  if change == "model_identity": f[1]["operation_id"] = "chosen-by-model"
  elif change == "unknown_tool": f[2]["tool_name"] = "unregistered"
  elif change == "unknown_backend": f[2]["backend"] = "host-direct"
  elif change == "service": f[2]["services"] = ["mcp-outer"]
  elif change == "network": f[2]["network"] = "allow"
  elif change == "relative_cwd": f[1]["cwd"] = "project"
  elif change == "relative_target": f[2]["target"]["path"] = "/project/../secret"
  elif change == "mixed_type": f[3][1] = "value"
  elif change == "nan": f[3]["content"] = float("nan")
  elif change == "float": f[3]["content"] = 1.0
  elif change == "bool_epoch": f[1]["cancel_epoch"] = True
  elif change == "extra_policy": f[2]["policy"]["skip_deny"] = True
  elif change == "no_writer": f[2]["workspace_keys"] = []
  else: f[1]["reviewer_identity"] = "1" * 64
  with pytest.raises(ConfigError): prepare(f)


def test_private_input_can_contain_model_identity_claims_without_granting_them():
  f = fixture(); f[3].update(operation_id="forged", role_id="admin", source="human")
  prepared = prepare(f)
  assert prepared["operation_id"] != "forged" and prepared["context"]["role_id"] == "main"
  with pytest.raises(Conflict, match="OPERATION_UNKNOWN"):
    f[0].issue("forged", operation_digest=prepared["operation_digest"], current=f[1], source="human")


def test_capacity_never_forgets_consumed_or_revoked_requests():
  f = fixture(max_operations=1); prepared = prepare(f); f[0].revoke(prepared["operation_id"])
  assert prepare(f) == prepared
  with pytest.raises(Conflict, match="CAPACITY"): prepare(f, "second")
  with pytest.raises(Conflict, match="CAPACITY"): prepare(fixture(max_private_bytes=4))


def test_fixed_command_binds_resolved_argv_and_executable_identity():
  f = fixture()
  f[2].update(kind="fixed-command", tool_name="bash", backend="linux-bwrap-v1", target={"command_ref": "tool:build",
    "argv": ["/usr/bin/build", "--fixed"], "timeout_ms": 1000,
    "executable": {"path": "/usr/bin/build", "device": 1, "inode": 2, "uid": 0, "sha256": "9" * 64}})
  prepared = prepare(f); permit = issue(f, prepared)
  f[2]["target"]["argv"].append("--changed")
  with pytest.raises(Conflict, match="RESOLUTION_STALE"): f[0].consume(permit, current=f[1], resolved=f[2])


def shell_fixture():
  f = fixture()
  f[2].update(kind="shell-command", tool_name="bash", backend="linux-bwrap-v1",
    read_roots=[{"path": "/project", "identity": "d" * 64}],
    target={"command_ref": "tool:ordinary-shell", "timeout_ms": 30000,
      "executable": {"path": "/usr/bin/bash", "device": 1, "inode": 2, "uid": 0, "sha256": "9" * 64}})
  f[3].clear()
  f[3]["command"] = "printf '%s\\n' 'private-shell-sentinel' | cat > result\nprintf '%s' \"$(cat result)\""
  return f


def test_shell_consumes_the_original_private_script_without_publishing_it_or_its_hash():
  f = shell_fixture()
  original = deepcopy(f[3])
  operation = prepare(f)
  permit = issue(f, operation)
  public = json.dumps([operation, permit, f[0].status(operation["operation_id"])], sort_keys=True)
  assert "private-shell-sentinel" not in public
  assert hashlib.sha256(original["command"].encode()).hexdigest() not in public
  assert "argv" not in operation["resolution"]["target"]
  f[3]["command"] = "changed after approval"
  with pytest.raises(Conflict, match="IDEMPOTENCY_CONFLICT"): prepare(f)
  consumed = f[0].consume(permit, current=f[1], resolved=f[2])
  assert consumed["private_input"] == original
  with pytest.raises(Conflict, match="PERMIT_USED"):
    f[0].consume(permit, current=f[1], resolved=f[2])


@pytest.mark.parametrize("change", ["executable", "inode", "timeout", "root", "policy", "cancel"])
def test_shell_changes_after_approval_burn_the_permit(change):
  f = shell_fixture()
  operation = prepare(f); permit = issue(f, operation)
  if change == "executable": f[2]["target"]["executable"]["sha256"] = "1" * 64
  elif change == "inode": f[2]["target"]["executable"]["inode"] += 1
  elif change == "timeout": f[2]["target"]["timeout_ms"] += 1
  elif change == "root": f[2]["read_roots"][0]["identity"] = "1" * 64
  elif change == "policy": f[2]["policy"]["policy_digest"] = "1" * 64
  else: f[1]["cancel_epoch"] += 1
  with pytest.raises(Conflict): f[0].consume(permit, current=f[1], resolved=f[2])
  with pytest.raises(Conflict, match="PERMIT_USED"):
    f[0].consume(permit, current=f[1], resolved=f[2])


@pytest.mark.parametrize("change", ["argv", "command", "unknown", "tool", "backend", "command_ref", "no_reads", "no_writer"])
def test_shell_public_projection_cannot_carry_script_or_skip_execution_constraints(change):
  f = shell_fixture()
  if change in ("argv", "command", "unknown"): f[2]["target"][change] = "private-shell-sentinel"
  elif change == "tool": f[2]["tool_name"] = "editor"
  elif change == "backend": f[2]["backend"] = "host-shell"
  elif change == "command_ref": f[2]["target"]["command_ref"] = "model:self-authorized"
  elif change == "no_reads": f[2]["read_roots"] = []
  else: f[2]["workspace_keys"] = []
  with pytest.raises(ConfigError) as error: prepare(f)
  assert "private-shell-sentinel" not in str(error.value)


def test_readonly_shell_needs_no_writer_but_still_consumes_a_permit():
  f = shell_fixture()
  f[2].update(write_roots=[], workspace_keys=[])
  operation = prepare(f); permit = issue(f, operation)
  assert f[0].consume(permit, current=f[1], resolved=f[2])["private_input"] == f[3]


def test_same_request_concurrent_prepare_mints_one_control_plane_identity():
  f = fixture(); barrier = Barrier(2)
  def run(_):
    barrier.wait(timeout=5)
    return prepare(f)
  with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(run, range(2)))
  assert results[0] == results[1]


def test_decision_must_name_the_prepared_digest_it_actually_reviewed():
  f = fixture(); prepared = prepare(f)
  changed = {**prepared, "operation_digest": "8" * 64}
  with pytest.raises(Conflict, match="DECISION_MISMATCH"): issue(f, changed)
  assert f[0].status(prepared["operation_id"])["state"] == "prepared"


@pytest.mark.parametrize("body", ["x" * 4096, "\0" * 128, "字" * 256, "🙂" * 256])
def test_oversized_private_body_is_rejected_before_serializer_allocates_a_copy(monkeypatch, body):
  import agentcfg.pi_operation_admission as admission
  f = fixture(max_private_bytes=512); f[3]["content"] = body
  original = admission.json.dumps
  calls = []
  def guarded(value, **kwargs):
    if value is f[3]: calls.append("private serialization")
    return original(value, **kwargs)
  monkeypatch.setattr(admission.json, "dumps", guarded)
  with pytest.raises(Conflict, match="CAPACITY"): prepare(f)
  assert calls == []


@pytest.mark.parametrize("value", [None, True, False, 17, -19, "", "\\\"\b\f\n\r\t\0中文🙂", [1, {}, []], {"b": False, "a": ["🙂", None]}])
def test_serialization_size_boundary_includes_escaping_unicode_and_structure(value):
  from agentcfg.pi_operation_admission import _json
  encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
  assert _json(value, limit=len(encoded)) == encoded
  with pytest.raises(Conflict, match="CAPACITY"): _json(value, limit=len(encoded) - 1)


@pytest.mark.parametrize("tool", ["write", "edit", "rename", "read"])
def test_file_resolution_must_include_roots_for_each_final_target(tool):
  f = fixture(); f[2]["tool_name"] = tool
  if tool == "write": f[2]["target"]["path"] = "/escape/file"
  if tool == "edit": f[2]["read_roots"] = [{"path": "/other", "identity": "1" * 64}]
  if tool == "rename": f[2]["target"]["destination"] = "/escape/file"
  if tool == "read": f[2].update(read_roots=[{"path": "/other", "identity": "1" * 64}], write_roots=[], workspace_keys=[])
  with pytest.raises(ConfigError): prepare(f)
