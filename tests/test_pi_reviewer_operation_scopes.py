"""真实临时scope/authority和原Admission组合；无SDK/真实账号/进程。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import traceback

import pytest

from agentcfg.activity import digest
from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.pi_reviewer_operation_scopes import ReviewerOperationScopeBindings
from agentcfg.pi_reviewer_scope_control import METHODS
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_operation_admission import fixture as admission_fixture
from test_pi_reviewer_scope_control import fixture as control_fixture, opened, intent, allocated, CONTROL, CONFIRM


def fixture(tmp_path, *, cap=4096, human=False):
  f = control_fixture(tmp_path)
  opened(f); intent(f); refs = allocated(f)
  _, current, resolved, private, clock = admission_fixture()
  current.update(profile="pi-full", activation_id=f["host"].store.owner["manager_activation_id"],
    session_id="sdk-session", user_intent_ref=refs["intent_ref"], reviewer_identity="9" * 64)
  resolved["policy"]["requires_human"] = human
  admissions = OperationAdmissions(current["activation_id"], now_ms=lambda: clock[0])
  bindings = ReviewerOperationScopeBindings(admissions, f["control"], f["principal"], max_operations=cap)
  admissions._reviewer_current = bindings.reviewer_current_borrowed  # 仅本组合显式fake宿主组装。
  prepared = admissions.prepare(refs["request_ref"], current=current, resolved=resolved, private_input=private)
  metadata = {"control_id":CONTROL,"confirmation_ref":CONFIRM,"tool_call_id":"nested/tool:1","request_ref":refs["request_ref"]}
  f.update(admissions=admissions, bindings=bindings, prepared=prepared, metadata=metadata, refs=refs,
    current=current, resolved=resolved, private=private, admission_clock=clock)
  return f


def bind(f): return f["bindings"].bind(f["prepared"], f["metadata"])

def issue(f, source="reviewer"):
  with f["control"].mutex:
    return f["admissions"].issue(f["prepared"]["operation_id"], operation_digest=f["prepared"]["operation_digest"],
      current=f["current"], source=source, reviewer_identity="9" * 64 if source=="reviewer" else None)


def consume(f, permit):
  with f["control"].mutex:
    return f["admissions"].consume(permit,current=f["current"],resolved=f["resolved"])


def assert_retired(f):
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])
  with pytest.raises(Conflict): bind(f)


def test_original_binding_copy_and_once_actual_admission(tmp_path):
  f=fixture(tmp_path); assert bind(f)==f["refs"]
  value=bind(f);value["request_ref"]="0"*32
  assert f["bindings"].scopes_for_prepared(f["prepared"])==f["refs"]
  assert f["bindings"].scope_current(f["prepared"],f["refs"])
  p=issue(f);executions=[consume(f,p)]
  with pytest.raises(Conflict): consume(f,p)
  assert len(executions)==1 and executions[0]["private_input"]==f["private"]
  assert "synthetic private token" not in str(f["bindings"].scopes_for_prepared(f["prepared"]))
  assert METHODS==tuple("ordinary_reviewer_scope_"+x for x in ("open","allocate_intent","allocate_request","verify","retire_intent","retire_session"))


def test_same_parameter_concurrency_serialized_and_no_allocation(tmp_path,monkeypatch):
  f=fixture(tmp_path); before=f["file"].read_bytes(); calls=[]; original=f["store"].verify_current
  def verify(value): calls.append(deepcopy(value)); return original(value)
  monkeypatch.setattr(f["store"],"verify_current",verify)
  gate=Barrier(2)
  def run(): gate.wait(); return bind(f)
  with ThreadPoolExecutor(2) as pool: a,b=list(pool.map(lambda _:run(),range(2)))
  assert a==b==f["refs"] and len(calls)==2
  assert len(f["bindings"]._bindings)==1 and f["file"].read_bytes()==before


@pytest.mark.parametrize("field",["control_id","confirmation_ref","tool_call_id","request_ref"])
def test_private_metadata_change_closes_original_operation(tmp_path,field):
  f=fixture(tmp_path);bind(f);f["metadata"][field]="different" if field=="tool_call_id" else "f"*32
  with pytest.raises(Conflict): bind(f)
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"]=="revoked"
  assert_retired(f)


@pytest.mark.parametrize("field",["session_id","activation_id","user_intent_ref","profile","request_id"])
def test_original_cross_binding_rejected_after_trusted_projection(tmp_path,field):
  f=fixture(tmp_path);c=deepcopy(f["current"]);req=f["refs"]["request_ref"]
  if field=="request_id": req="f"*32
  elif field=="profile": c.update(profile="pi-base",reviewer_identity=None)
  else: c[field]="other" if field!="user_intent_ref" else "f"*32
  admissions=OperationAdmissions(c["activation_id"],now_ms=lambda:1000)
  b=ReviewerOperationScopeBindings(admissions,f["control"],f["principal"])
  p=admissions.prepare(req,current=c,resolved=f["resolved"],private_input=f["private"])
  with pytest.raises(Conflict): b.bind(p,f["metadata"])
  assert admissions.status(p["operation_id"])["state"]=="revoked"


def test_same_request_new_operation_retires_both_trusted_originals(tmp_path):
  f=fixture(tmp_path);bind(f);c=deepcopy(f["current"]);c["session_id"]="different"
  p=f["admissions"].prepare(f["refs"]["request_ref"],current=c,resolved=f["resolved"],private_input=f["private"])
  with pytest.raises(Conflict): f["bindings"].bind(p,f["metadata"])
  for value in (p,f["prepared"]): assert f["admissions"].status(value["operation_id"])["state"]=="revoked"
  assert_retired(f)


@pytest.mark.parametrize("phase",["first","rebind"])
def test_unknown_durable_verify_permanently_closes_slot(tmp_path,monkeypatch,phase):
  f=fixture(tmp_path)
  if phase=="rebind":bind(f)
  marker="SYNTHETIC_PRIVATE_SCOPE_ERROR"
  original=f["store"].verify_current
  def unknown(value): raise RuntimeError(marker)
  monkeypatch.setattr(f["store"],"verify_current",unknown)
  with pytest.raises(Conflict) as caught:bind(f)
  assert marker not in "".join(traceback.format_exception(caught.value))
  monkeypatch.setattr(f["store"],"verify_current",original)
  assert_retired(f)
  assert len(f["bindings"]._bindings)==1


@pytest.mark.parametrize("phase",["issue","consume"])
@pytest.mark.parametrize("reason",["intent","session","expired","authority-missing","closing"])
def test_live_persistent_change_prevents_execution_and_never_revives(tmp_path,phase,reason):
  f=fixture(tmp_path);bind(f);permit=issue(f) if phase=="consume" else None
  if reason=="intent": f["call"]("retire_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM})
  if reason=="session": f["call"]("retire_session",{"control_id":CONTROL,"session_id":"sdk-session"})
  if reason=="expired": f["clock"][0]=10000
  if reason=="authority-missing":
    authority=f["home"] / ".agentcfg-workspaces/reviewer-authority.json"
    saved=authority.read_bytes();authority.unlink()
  if reason=="closing": f["host"].service.closing=True
  executions=[]
  with pytest.raises(Conflict,match="OPERATION_REVIEWER_UNQUALIFIED"):
    executions.append(consume(f,permit) if phase=="consume" else issue(f))
  assert executions==[]
  if reason=="expired":f["clock"][0]=150
  if reason=="authority-missing":authority.write_bytes(saved);authority.chmod(0o600)
  f["host"].service.closing=False
  with pytest.raises(Conflict):issue(f)
  if permit:
    with pytest.raises(Conflict):consume(f,permit)
  assert_retired(f)


def test_human_ceiling_preserved_binding_does_not_upgrade_it(tmp_path):
  f=fixture(tmp_path,human=True);bind(f)
  assert f["prepared"]["resolution"]["policy"]["requires_human"] is True
  with pytest.raises(Conflict,match="OPERATION_HUMAN_REQUIRED"):issue(f)
  f["call"]("retire_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM})
  assert consume(f,issue(f,"human"))["private_input"]==f["private"]


def test_capacity_includes_unknown_tombstone_no_eviction(tmp_path,monkeypatch):
  f=fixture(tmp_path,cap=1)
  original=f["store"].verify_current
  monkeypatch.setattr(f["store"],"verify_current",lambda _:False)
  with pytest.raises(Conflict):bind(f)
  monkeypatch.setattr(f["store"],"verify_current",original)
  newrefs=allocated(f,tool="second/tool")
  p=f["admissions"].prepare(newrefs["request_ref"],current=f["current"],resolved=f["resolved"],private_input=f["private"])
  m={**f["metadata"],"tool_call_id":"second/tool","request_ref":newrefs["request_ref"]}
  with pytest.raises(Conflict,match="CAPACITY"):f["bindings"].bind(p,m)
  assert len(f["bindings"]._bindings)==1
  assert f["admissions"].status(p["operation_id"])["state"]=="revoked"


@pytest.mark.parametrize("fault",["unknown","bool","digest","subclass","getter"])
def test_malformed_or_forged_initial_prepared_zero_effects(tmp_path,monkeypatch,fault):
  f=fixture(tmp_path);p=deepcopy(f["prepared"])
  if fault=="unknown":p["private_input"]="SYNTHETIC_PRIVATE"
  if fault=="bool":p["schema_version"]=True
  if fault=="digest":p["operation_digest"]="0"*64
  if fault=="subclass":
    class Custom(dict):
      def items(self): pytest.fail("custom items")
    p=Custom(p)
  if fault=="getter":
    class Secret:
      @property
      def secret(self): pytest.fail("getter")
      def __deepcopy__(self,memo): pytest.fail("deepcopy")
    p["context"]["session_id"]=Secret()
  monkeypatch.setattr(f["admissions"],"prepared",lambda _:pytest.fail("must validate before lookup"))
  with pytest.raises(ConfigError):f["bindings"].bind(p,f["metadata"])
  assert not f["bindings"]._bindings


def test_forged_initial_valid_digest_cannot_revoke_original(tmp_path):
  f=fixture(tmp_path);p=deepcopy(f["prepared"]);p["context"]["cancel_epoch"]+=1
  p["operation_digest"]=digest({k:v for k,v in p.items() if k!="operation_digest"})
  with pytest.raises(Conflict):f["bindings"].bind(p,f["metadata"])
  assert not f["bindings"]._bindings and f["admissions"].prepared(f["prepared"]["operation_id"])==f["prepared"]


@pytest.mark.parametrize("argument",["prepared","current","scopes"])
def test_callback_binding_drift_is_false_and_local_permanent(tmp_path,argument):
  f=fixture(tmp_path);bind(f);p=deepcopy(f["prepared"]);c=deepcopy(f["current"]);s=deepcopy(f["refs"])
  if argument=="prepared":
    p["context"]["cancel_epoch"]+=1;p["operation_digest"]=digest({k:v for k,v in p.items() if k!="operation_digest"})
  if argument=="current":c["cancel_epoch"]+=1
  if argument=="scopes":s["request_ref"]="f"*32
  if argument=="scopes":assert not f["bindings"].scope_current(p,s)
  else:
    with f["control"].mutex:assert not f["bindings"].reviewer_current_borrowed(p,c)
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])


def test_actual_admission_hook_does_not_acquire_service_or_reenter_admission(tmp_path,monkeypatch):
  f=fixture(tmp_path);bind(f)
  class NoAcquire:
    def __enter__(self):pytest.fail("borrowed hook acquired service")
    def __exit__(self,*args):pass
  original=f["control"].mutex
  monkeypatch.setattr(f["control"],"mutex",NoAcquire())
  monkeypatch.setattr(f["host"].service,"mutex",NoAcquire())
  monkeypatch.setattr(f["bindings"],"mutex",NoAcquire())
  for method in ("prepared","revoke","status"):
    monkeypatch.setattr(f["admissions"],method,lambda *args:pytest.fail("Admission reentry"))
  with original:
    permit=f["admissions"].issue(f["prepared"]["operation_id"],operation_digest=f["prepared"]["operation_digest"],current=f["current"],source="reviewer",reviewer_identity="9"*64)
    assert f["admissions"].consume(permit,current=f["current"],resolved=f["resolved"])["private_input"]==f["private"]


@pytest.mark.parametrize("value",[None,True,0,4097])
def test_capacity_exact_integer_constructor(tmp_path,value):
  f=fixture(tmp_path)
  with pytest.raises(ConfigError):ReviewerOperationScopeBindings(f["admissions"],f["control"],f["principal"],max_operations=value)


def test_local_projection_is_not_authority_or_current_proof(tmp_path):
  f=fixture(tmp_path);bind(f);f["clock"][0]=10000
  assert f["bindings"].scopes_for_prepared(f["prepared"])==f["refs"]
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])
  f["clock"][0]=150
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])


@pytest.mark.parametrize("phase",["issue","consume"])
@pytest.mark.parametrize("change",["update","same-bytes-replace"])
def test_authority_physical_or_document_change_rejects_at_both_permit_boundaries(tmp_path,phase,change):
  f=fixture(tmp_path);bind(f);permit=issue(f) if phase=="consume" else None
  if change=="update":
    old=f["authority_snapshot"];doc=deepcopy(old["document"]);doc["generation"]+=1;doc["limits"]["max_calls"]-=1
    f["authority"].update(doc,expected_identity=old["identity"])
  else:
    path=f["home"] / ".agentcfg-workspaces/reviewer-authority.json"
    replacement=path.with_name("replacement");replacement.write_bytes(path.read_bytes());replacement.chmod(0o600);replacement.replace(path)
  with pytest.raises(Conflict,match="OPERATION_REVIEWER_UNQUALIFIED"):
    consume(f,permit) if permit else issue(f)
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])


@pytest.mark.parametrize("reason",["manager-dead","generation","owner","worker"])
def test_live_manager_principal_is_part_of_each_current_verification(tmp_path,reason):
  from agentcfg.pi_supervisor import Principal
  f=fixture(tmp_path);bind(f)
  if reason=="manager-dead":f["host"].store.processes.current.clear()
  if reason=="generation":f["bindings"]._principal=Principal("manager",f["principal"].lease_id,f["principal"].grant_generation+1)
  if reason=="owner":f["host"].store.owner["owner_nonce"]="f"*32
  if reason=="worker":f["bindings"]._principal=Principal("worker",f["principal"].lease_id,f["principal"].grant_generation)
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])


@pytest.mark.parametrize("shape",["unknown","subclass","custom-value","unicode","bool"])
def test_metadata_fails_without_custom_methods_and_leaves_trusted_tombstone(tmp_path,shape):
  f=fixture(tmp_path);m=deepcopy(f["metadata"])
  class Secret:
    def __eq__(self,other):pytest.fail("custom equality")
    def __deepcopy__(self,memo):pytest.fail("custom deepcopy")
  if shape=="unknown":m["source"]="reviewer"
  if shape=="subclass":
    class Custom(dict):
      def __iter__(self):pytest.fail("custom iterator")
    m=Custom(m)
  if shape=="custom-value":m["control_id"]=Secret()
  if shape=="unicode":m["tool_call_id"]="中文"
  if shape=="bool":m["request_ref"]=True
  with pytest.raises(Conflict):f["bindings"].bind(f["prepared"],m)
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"]=="revoked"
  assert len(f["bindings"]._bindings)==1


def test_known_binding_changed_valid_projection_retires_without_replacing_cache(tmp_path):
  f=fixture(tmp_path);bind(f);original=deepcopy(f["prepared"]);p=deepcopy(original)
  p["resolution"]["target"]["path"]="/project/changed"
  p["operation_digest"]=digest({k:v for k,v in p.items() if k!="operation_digest"})
  with pytest.raises(Conflict):f["bindings"].bind(p,f["metadata"])
  assert f["bindings"]._bindings[p["operation_id"]]["prepared"]==original
  assert f["admissions"].status(p["operation_id"])["state"]=="revoked"
  assert_retired(f)


@pytest.mark.parametrize("kind",["current","scopes"])
def test_none_cannot_skip_callback_argument_validation(tmp_path,kind):
  f=fixture(tmp_path);bind(f)
  if kind=="scopes":assert not f["bindings"].scope_current(f["prepared"],None)
  else:
    with f["control"].mutex:assert not f["bindings"].reviewer_current_borrowed(f["prepared"],None)
  assert not f["bindings"].scope_current(f["prepared"],f["refs"])


def test_operation_helper_closed_session_check_and_no_rpc_registration(tmp_path):
  f=fixture(tmp_path)
  before=f["file"].read_bytes()
  assert f["control"].operation_binding(f["principal"],f["metadata"],session_id="sdk-session")==f["refs"]
  with pytest.raises(Conflict):f["control"].operation_binding(f["principal"],f["metadata"],session_id="another-session")
  with pytest.raises(ConfigError):f["control"].operation_binding(f["principal"],{**f["metadata"],"session_scope":f["refs"]["session_scope"]},session_id="sdk-session")
  assert f["file"].read_bytes()==before


def test_second_binder_and_same_owner_second_token_cannot_replace_original(tmp_path,monkeypatch):
  f=fixture(tmp_path);bind(f);before=f["file"].read_bytes()
  monkeypatch.setattr(f["store"],"verify_current",lambda _:pytest.fail("constructor scope query"))
  for owner in (None,f["bindings"]._scope_owner):
    with pytest.raises(Conflict,match="REVIEW_SCOPE_OWNER_ALREADY_BOUND"):
      ReviewerOperationScopeBindings(f["admissions"],f["control"],f["principal"],owner=owner)
  assert f["file"].read_bytes()==before
  assert f["bindings"].scopes_for_prepared(f["prepared"])==f["refs"]


def test_scope_owner_claim_atomic_and_owner_confirmation_keeps_binder():
  admissions=OperationAdmissions("activation");gate=Barrier(2);owners=[object(),object()]
  def claim(owner):
    gate.wait()
    try:admissions._claim_reviewer_scope_owner(owner);return owner
    except Conflict:return None
  with ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,owners))
  winner=next(value for value in results if value is not None)
  assert sum(value is not None for value in results)==1
  token=object();admissions._claim_reviewer_scope_owner(winner,binder=token)
  admissions._claim_reviewer_scope_owner(winner)
  admissions._claim_reviewer_scope_owner(winner,binder=token)
  assert admissions._reviewer_scope_binder is token
  with pytest.raises(Conflict):admissions._claim_reviewer_scope_owner(winner,binder=object())
  with pytest.raises(Conflict):admissions._claim_reviewer_scope_owner(object(),binder=token)
  assert admissions._reviewer_scope_owner is winner and admissions._reviewer_scope_binder is token
  fresh=OperationAdmissions("another-activation");fresh._claim_reviewer_scope_owner(object(),binder=object())
  assert fresh._reviewer_scope_owner is not winner


@pytest.mark.parametrize("bad",[None,True,{},"capability"])
def test_scope_owner_claim_only_native_objects_and_no_partial_claim(bad):
  admissions=OperationAdmissions("activation")
  with pytest.raises(ConfigError):admissions._claim_reviewer_scope_owner(bad)
  assert admissions._reviewer_scope_owner is None and admissions._reviewer_scope_binder is None
  with pytest.raises(ConfigError):admissions._claim_reviewer_scope_owner(object(),binder=bad if bad is not None else True)
  assert admissions._reviewer_scope_owner is None and admissions._reviewer_scope_binder is None
