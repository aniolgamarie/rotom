"""真实执行store与假process验证readonly来源投影，不启动宿主或宣称物理资格。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest

from agentcfg.activity import digest, valid_evidence
from agentcfg.deployment import json_bytes
from agentcfg.pi_delegate import DelegateController
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Tree, Conflict
from test_pi_activity import make_store, identity


def fixture(tmp_path):
  store, processes = make_store(tmp_path)
  process = identity(201)
  def spawn(_lease):
    processes.current[201] = process
    return process
  lease = store.begin(kind="external", execution_id="physical-one", task_id=None, attempt_id="attempt-one",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
    planned_workspaces=[], spawn=spawn)
  request = {"run_id": "physical-one", "attempt_id": "attempt-one", "lease_id": lease["lease_id"],
    "grant_generation": lease["grant_generation"], "instance_id": store.owner["instance_id"],
    "runtime_identity": "e" * 64, "policy_digest": lease["policy_digest"]}
  processes.current.pop(201)
  final = store.finish(lease["lease_id"], store.owner)
  assert valid_evidence(final)
  with Tree(store.root) as tree:
    tree.write_state("activity/exits/" + lease["lease_id"] + ".json", json_bytes(
      {"schema_version": 1, "lease_id": lease["lease_id"], "process_identity": process, "exit_code": 0}))
  physical = {"request": request, "receipt": {**request, "terminal_status": "completed",
    "process_terminated": True, "resources_reclaimed": True}, "verification": "verified-execution", "state": "completed"}
  action = {"physical_run_id": request["run_id"], "attempt_id": request["attempt_id"], "lease_id": lease["lease_id"]}
  controller = DelegateController.__new__(DelegateController)
  controller.host = SimpleNamespace(store=store, root=store.root, runtime_root=tmp_path / ("e" * 64))
  controller.runs = SimpleNamespace(read=lambda _run: deepcopy(physical))
  controller.sources = SimpleNamespace(resolve=lambda _principal, ref, **_kwargs: {"origin": {"instance_id": store.owner["instance_id"]}} if ref == "own" else (_ for _ in ()).throw(Conflict("SOURCE_DENIED")))
  controller.logical = SimpleNamespace(private=lambda _run: {"binding": {}},
    query=lambda _origin, _run, _binding: {"actions": [deepcopy(action)]})
  controller._modern_origin = lambda source, _run: source["origin"]
  return controller, store, physical, action


def test_original_public_query_projects_only_matched_production_valid_lease_proof(tmp_path):
  controller, store, physical, action = fixture(tmp_path)
  before = {str(p): p.read_bytes() for p in store.root.rglob("*.json")}
  row = controller.modern_query(Principal("manager"), "own", "logical")["actions"][0]
  proof = row["execution_evidence"]
  lease = store.read(action["lease_id"])
  assert proof == {"schema_version": 1, "physical_run_id": action["physical_run_id"], "attempt_id": action["attempt_id"],
    "lease_id": action["lease_id"], "grant_generation": lease["grant_generation"],
    "process_identity_digest": digest(lease["process_identity"]),
    "termination_evidence_digest": lease["termination_evidence"]["evidence_digest"],
    "terminated": True, "resources_reclaimed": True, "exit_code": 0}
  assert "owner_nonce" not in json.dumps(proof)
  assert before == {str(p): p.read_bytes() for p in store.root.rglob("*.json")}
  with pytest.raises(Conflict, match="SOURCE_DENIED"):
    controller.modern_query(Principal("manager"), "foreign", "logical")


@pytest.mark.parametrize("field", ["run_id", "attempt_id", "lease_id", "instance_id", "runtime_identity", "grant_generation"])
def test_wrong_physical_receipt_association_has_no_execution_proof(tmp_path, field):
  controller, store, physical, action = fixture(tmp_path)
  physical["receipt"][field] = 99 if field == "grant_generation" else "foreign"
  assert controller.modern_query(Principal("manager"), "own", "logical")["actions"][0]["execution_evidence"] is None


@pytest.mark.parametrize("fault", ["generation", "process", "protected", "unverified", "missing-exit", "wrong-exit", "never-started"])
def test_wrong_final_generation_process_or_unknown_proof_never_gets_complete_pass(tmp_path, fault, monkeypatch):
  controller, store, physical, action = fixture(tmp_path)
  if fault == "unverified": physical["verification"] = "unverified"
  if fault == "missing-exit": (store.root / "activity/exits" / (action["lease_id"] + ".json")).unlink()
  if fault == "wrong-exit":
    with Tree(store.root) as tree:
      tree.write_state("activity/exits/" + action["lease_id"] + ".json", json_bytes(
        {"schema_version": 1, "lease_id": "foreign", "process_identity": identity(201), "exit_code": 0}))
  original = store.reconcile
  if fault in ("generation", "process", "protected"):
    def altered(key):
      row = original(key)
      if fault == "generation": row["grant_generation"] += 1
      if fault == "process": row["process_identity"] = identity(201, "different")
      if fault == "protected": row["protected"] = True
      return row
    monkeypatch.setattr(store, "reconcile", altered)
  if fault == "never-started":
    original_read = store.read
    monkeypatch.setattr(store, "read", lambda key: {**original_read(key), "process_identity": None, "spawn_committed": False})
  result = controller.modern_query(Principal("manager"), "own", "logical")["actions"][0]["execution_evidence"]
  if fault == "missing-exit": assert result["exit_code"] is None
  else: assert result is None
