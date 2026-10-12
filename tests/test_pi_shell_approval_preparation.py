"""Shell完整计划审批接原准备/控制面；临时真实源树、假进程，不执行宿主。"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from agentcfg.activity import digest
from agentcfg.pi_shell_mounts import compile_mount_plan
from agentcfg.pi_shell_sources import pin_shell_sources
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_admitted_shell import fixture as original_fixture, external, shared_control, shared_prepare


SCRIPT = "printf '%s' 'SYNTHETIC_PRIVATE_SHELL_GRADE' | cat > output\ncat output"
CAPABILITIES = ["read", "list", "search", "write", "create", "delete", "rename"]


def fixture(tmp_path, *, write=True, grade="deterministic-policy", full=True):
  f = original_fixture(tmp_path, write=write)
  manifest = f[2].manifest()
  rules = manifest["permission_policy"]["rules"]
  rules[0]["operations"] = CAPABILITIES[:]
  for row in rules:
    if grade is not None: row["approval"] = grade
  manifest["options"]["paths"]["roots"]["executable"] = {"path": str(tmp_path), "purpose": "read"}
  rules.append({"id": "executable", "kind": "file", "effect": "allow", "tool_ids": ["read"],
    "operations": ["read"], "root_ref": "executable", "relative_path": "synthetic-shell", "match": "exact",
    "approval": "deterministic-policy"})
  observations, state = [], {"mutate": None}
  def preflight(public):
    observations.append(deepcopy(public))
    plan = compile_mount_plan(public, system_roots=[])
    backend = {"runtime_identity": f[2].runtime_root.name, "helper_identity": "1" * 64, "plan_digest": digest(plan)}
    if full: backend["mount_plan"] = plan
    if state["mutate"] is not None: state["mutate"](backend)
    return backend
  f[0].backend_preflight = preflight
  control, call = shared_control(f)
  return f, control, call, observations, state


def prepare(case):
  return shared_prepare(case[0], case[2], private={"command": SCRIPT})


def rpc(case, method, prepared=None, **args):
  if prepared is not None: args["operation_id"] = prepared["operation_id"]
  return case[2]("ordinary_admission_" + method, {"context": case[0][4], **args})


def snapshot(root):
  return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("write", [False, True])
def test_real_complete_plan_prepares_and_deterministically_consumes_once_without_early_writer(tmp_path, write):
  case = fixture(tmp_path, write=write); f, control, _, observations, _ = case
  before = snapshot(tmp_path)
  p = prepare(case)
  policy = p["resolution"]["policy"]
  assert policy["approval"] == "deterministic-policy" and policy["requires_human"] is False
  assert len(policy) == 6 and bool(p["resolution"]["workspace_keys"]) is write
  permit = rpc(case, "issue_deterministic", p)
  assert permit["source"] == "deterministic-policy" and permit["reviewer_identity"] is None
  assert external(f) == [] and snapshot(tmp_path) == before
  ticket = rpc(case, "consume", permit=permit)
  assert ticket["state"] == "consumed" and ticket["write"] is write
  lease, = external(f)
  assert lease["state"] == "allocating" and not lease["spawn_committed"]
  assert bool(lease["planned_workspaces"]) is write
  if write:
    writer = f[2].store.workspaces.read(lease["planned_workspaces"][0])
    assert writer["execution_lease_id"] == lease["lease_id"] and writer["state"] == "reserved"
  for method, args in (("consume", {"permit": permit}), ("issue_deterministic", {})):
    with pytest.raises(Conflict): rpc(case, method, p if method.startswith("issue") else None, **args)
  assert external(f) == [lease] and len(observations) == 3
  entry = control.shell_bridge.records[p["operation_id"]]
  assert entry["backend"]["mount_plan"] == compile_mount_plan(observations[0], system_roots=[])
  public = json.dumps((p, permit, ticket, observations)).encode()
  disk = b"\n".join(snapshot(f[2].root).values())
  for hidden in (SCRIPT.encode(), b"SYNTHETIC_PRIVATE_SHELL_GRADE", hashlib.sha256(SCRIPT.encode()).hexdigest().encode()):
    assert hidden not in public and hidden not in disk
  assert not (Path(f[4]["cwd"]) / "output").exists()


@pytest.mark.parametrize("grade,expected", [("human", "human"), ("reviewer", "reviewer"), (None, "human")])
def test_full_plan_retains_other_grades_and_original_human_source(tmp_path, grade, expected):
  case = fixture(tmp_path, grade=grade); p = prepare(case)
  assert p["resolution"]["policy"]["approval"] == expected
  assert p["resolution"]["policy"]["requires_human"] is (expected == "human")
  with pytest.raises(Conflict, match="OPERATION_APPROVAL_SOURCE_MISMATCH"): rpc(case, "issue_deterministic", p)
  assert rpc(case, "issue", p)["source"] == "human"
  assert external(case[0]) == []


@pytest.mark.parametrize("restriction", ["global-higher", "create-uncovered"])
def test_whole_file_policy_and_future_create_capability_cannot_be_downgraded(tmp_path, restriction):
  case = fixture(tmp_path)
  policy = case[0][2].manifest()["permission_policy"]
  if restriction == "create-uncovered": policy["rules"][0]["operations"].remove("create")
  else:
    policy["rules"].append({"id": "global", "kind": "file", "effect": "allow", "tool_ids": ["editor"],
      "operations": ["delete"], "root_ref": "executable", "relative_path": "unselected", "match": "exact", "approval": "human"})
  p = prepare(case)
  assert p["resolution"]["policy"]["approval"] == "human"
  with pytest.raises(Conflict, match="OPERATION_APPROVAL_SOURCE_MISMATCH"): rpc(case, "issue_deterministic", p)
  assert external(case[0]) == []


def test_original_only_digest_backend_keeps_five_field_human_projection(tmp_path):
  case = fixture(tmp_path, full=False); p = prepare(case)
  policy = p["resolution"]["policy"]
  assert len(policy) == 5 and "approval" not in policy and policy["requires_human"] is True
  with pytest.raises(Conflict, match="OPERATION_APPROVAL_SOURCE_MISMATCH"): rpc(case, "issue_deterministic", p)
  assert rpc(case, "issue", p)["source"] == "human" and external(case[0]) == []


@pytest.mark.parametrize("mutation", ["digest", "cwd", "masks", "executable", "visible", "writable"])
def test_claimed_plan_is_recompiled_from_original_part_and_cannot_add_capabilities(tmp_path, mutation):
  case = fixture(tmp_path, write=False)
  extra = tmp_path / "extra"; extra.mkdir()
  def mutate(backend):
    plan = backend["mount_plan"]
    if mutation == "digest": backend["plan_digest"] = "0" * 64; return
    if mutation == "cwd": plan["cwd"]["identity"] = "0" * 64
    elif mutation == "masks": plan["masks"] = []
    elif mutation == "executable": plan["mounts"][-1]["identity"]["sha256"] = "0" * 64
    elif mutation == "visible": plan["mounts"].insert(0, {"path": str(extra), "kind": "directory", "identity": "0" * 64,
      "role": "workspace", "writable": False})
    else: plan["mounts"][0]["writable"] = True
    backend["plan_digest"] = digest(plan)
  case[4]["mutate"] = mutate
  with pytest.raises(Conflict, match="SHELL_BACKEND_UNAVAILABLE"): prepare(case)
  assert external(case[0]) == [] and case[1].shell_bridge.records == {}


@pytest.mark.parametrize("when", ["issue", "consume"])
@pytest.mark.parametrize("change", ["source", "policy", "current", "plan", "helper"])
def test_original_sources_policy_context_and_complete_plan_are_rechecked_before_execution(tmp_path, when, change):
  case = fixture(tmp_path); p = prepare(case)
  permit = rpc(case, "issue_deterministic", p) if when == "consume" else None
  f = case[0]
  if change == "source": Path(f[2].manifest()["options"]["external_tools"]["shell"]["executable"]).write_bytes(b"replaced fake executable")
  elif change == "policy": f[2].manifest()["permission_policy"]["rules"][0]["approval"] = "human"
  elif change == "current": f[4]["cancel_epoch"] += 1
  elif change == "helper": case[4]["mutate"] = lambda backend: backend.update(helper_identity="3" * 64)
  else:
    def mutate(backend):
      backend["mount_plan"]["masks"] = []
      backend["plan_digest"] = digest(backend["mount_plan"])
    case[4]["mutate"] = mutate
  with pytest.raises((Conflict, ConfigError)):
    rpc(case, "consume", permit=permit) if when == "consume" else rpc(case, "issue_deterministic", p)
  assert external(f) == []
  if permit is not None:
    with pytest.raises(Conflict): rpc(case, "consume", permit=permit)
    assert external(f) == []


CALLBACKS = []


class BackendSubclass(dict):
  def items(self):
    CALLBACKS.append("items")
    raise AssertionError("untrusted custom callback")


@pytest.mark.parametrize("malformed", ["null-plan", "subclass-plan", "subclass-response", "oversize", "unknown", "scalar-plan"])
def test_backend_optional_plan_requires_native_bounded_closed_capture(tmp_path, malformed):
  case = fixture(tmp_path)
  CALLBACKS.clear()
  def mutate(backend):
    if malformed == "null-plan": backend["mount_plan"] = None
    elif malformed == "subclass-plan": backend["mount_plan"] = BackendSubclass(backend["mount_plan"])
    elif malformed == "oversize": backend["mount_plan"]["unaccepted"] = "SYNTHETIC_PRIVATE" * 100000
    elif malformed == "unknown": backend["unaccepted"] = "SYNTHETIC_PRIVATE"
    elif malformed == "scalar-plan": backend["mount_plan"] = True
  if malformed == "subclass-response":
    case[1].shell_bridge.backend_preflight = lambda _: BackendSubclass()
  else: case[4]["mutate"] = mutate
  with pytest.raises(Conflict) as caught: prepare(case)
  assert str(caught.value) == "SHELL_BACKEND_UNAVAILABLE" and caught.value.__cause__ is None
  assert "SYNTHETIC_PRIVATE" not in str(caught.value) and CALLBACKS == [] and external(case[0]) == []


@pytest.mark.parametrize("grade,human", [("human", True), ("reviewer", False), ("deterministic-policy", False)])
def test_new_source_projection_pins_real_sources_with_consistent_grade(tmp_path, grade, human):
  case = fixture(tmp_path, grade=grade); prepare(case)
  public = deepcopy(case[3][-1])
  public["resolution"]["policy"].update(approval=grade, requires_human=human)
  before = deepcopy(public)
  with pin_shell_sources(public) as sources:
    assert os.read(sources["executable_fd"], 100) == b"synthetic shell, never execute"
    assert sources["roots"] and all(not os.get_inheritable(row["fd"]) for row in sources["roots"])
  assert public == before


@pytest.mark.parametrize("fault", ["unknown", "null", "flag", "extra"])
def test_new_source_projection_rejects_invalid_grade_without_pinning(tmp_path, fault, monkeypatch):
  from agentcfg import pi_shell_sources
  case = fixture(tmp_path); prepare(case)
  public = deepcopy(case[3][-1]); policy = public["resolution"]["policy"]
  policy.update(approval="deterministic-policy", requires_human=False)
  if fault == "unknown": policy["approval"] = "SYNTHETIC_PRIVATE"
  elif fault == "null": policy["approval"] = None
  elif fault == "flag": policy["requires_human"] = True
  else: policy["source"] = "deterministic-policy"
  monkeypatch.setattr(pi_shell_sources, "_directory", lambda *_: pytest.fail("invalid projection opened source"))
  with pytest.raises(ConfigError) as caught:
    with pin_shell_sources(public): pytest.fail("invalid grade pinned")
  assert caught.value.code == "pi-shell-sources" and "SYNTHETIC_PRIVATE" not in str(caught.value)


def test_legacy_source_projection_cannot_imply_automatic_approval(tmp_path, monkeypatch):
  from agentcfg import pi_shell_sources
  case = fixture(tmp_path, full=False); prepare(case)
  public = deepcopy(case[3][-1])
  assert "approval" not in public["resolution"]["policy"]
  public["resolution"]["policy"]["requires_human"] = False
  monkeypatch.setattr(pi_shell_sources, "_directory", lambda *_: pytest.fail("legacy nonhuman projection opened source"))
  with pytest.raises(ConfigError) as caught:
    with pin_shell_sources(public): pytest.fail("legacy projection inferred automatic approval")
  assert caught.value.code == "pi-shell-sources"
