"""私有scoped prepare组合：真实临时账户/File/Shell桥，假后端与进程。"""
from copy import deepcopy
import traceback

import pytest

from agentcfg.pi_admission_control import FileAdmissionControl
from agentcfg.pi_admitted_shell import ShellOperationAdmissions
from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.pi_reviewer_scope_control import ReviewerScopeControl, METHODS
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_admitted_shell import fixture as shell_fixture
from test_pi_reviewer_scopes import fixture as scopes_fixture

CONTROL="1"*32
CONFIRM="2"*32


def fixture(tmp_path, *, provider=True):
  business=tmp_path/"business";business.mkdir()
  raw=shell_fixture(business,profile="pi-full")
  _,ops,host,principal,current,_,proof=raw
  current["reviewer_identity"]="9"*64
  private=tmp_path/"private";private.mkdir()
  f=scopes_fixture(private)
  scopes=ReviewerScopeControl(host,f["store"])
  scopes.handle(principal,"ordinary_reviewer_scope_open",{"control_id":CONTROL,"session_id":current["session_id"]})
  refs=scopes.handle(principal,"ordinary_reviewer_scope_allocate_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM})
  current["user_intent_ref"]=refs["intent_ref"]
  shared=OperationAdmissions(host.store.owner["manager_activation_id"],now_ms=lambda:int(ops.now().timestamp()*1000))
  def factory(operations,**kwargs):return ShellOperationAdmissions(operations,binding_name="shell",backend_preflight=lambda _:deepcopy(proof),**kwargs)
  control=FileAdmissionControl(ops,shared_admissions=shared,shell_bridge_factory=factory,reviewer_scope_control=scopes if provider else None)
  def call(name,args):return control.handle(principal,"ordinary_admission_"+name,args)
  call("open",{"control_id":"admission","session_id":current["session_id"]})
  f.update(control=control,scopes=scopes,shared=shared,operations=ops,host=host,principal=principal,current=current,call=call)
  return f


def arguments(f, *, tool="write", tool_id="tool/1", confirmation=CONFIRM, scope_control=CONTROL):
  refs=f["scopes"].handle(f["principal"],"ordinary_reviewer_scope_allocate_request",{"control_id":scope_control,"confirmation_ref":confirmation,"tool_call_id":tool_id})
  return {"control_id":"admission","request_id":refs["request_ref"],"context":deepcopy(f["current"]),"tool_name":tool,
    "input":{"command":"printf scoped"} if tool=="bash" else {"path":"new.txt","content":"private-scoped-body"},
    "reviewer_scope":{"control_id":scope_control,"confirmation_ref":confirmation,"tool_call_id":tool_id,"request_ref":refs["request_ref"]}}


def prepare(f,args):return f["call"]("prepare",args)
def issue(f,p):return f["call"]("issue",{"operation_id":p["operation_id"],"context":f["current"]})
def consume(f,permit):return f["call"]("consume",{"permit":permit,"context":f["current"]})
def cancel(f,args):return f["call"]("cancel_request",{"control_id":"admission","request_id":args["request_id"]})
def external(f):return [r for r in f["host"].store.records() if r["kind"]=="external"]


@pytest.mark.parametrize("tool",["write","bash"])
def test_scoped_prepare_original_refs_human_once_and_permitted_reread(tmp_path,tool):
  f=fixture(tmp_path);a=arguments(f,tool=tool);p=prepare(f,a)
  assert set(p)=={"schema_version","operation_id","request_id","context","resolution","private_input_ref","operation_digest"}
  assert p["request_id"]==a["reviewer_scope"]["request_ref"] and p["context"]["user_intent_ref"]==f["current"]["user_intent_ref"]
  assert p["resolution"]["policy"]["requires_human"] is True
  assert prepare(f,a)==p
  permit=issue(f,p);assert permit["source"]=="human"
  assert prepare(f,a)==p  # 不重bind已经permitted的Admission。
  assert consume(f,permit)["state"]=="consumed"
  with pytest.raises(Conflict):consume(f,permit)
  assert len(external(f))==1


@pytest.mark.parametrize("change",["metadata","remove","input","context","cross-kind"])
def test_known_scoped_row_changes_cancel_original_and_intent(tmp_path,change):
  f=fixture(tmp_path);a=arguments(f);p=prepare(f,a);permit=issue(f,p);changed=deepcopy(a)
  if change=="metadata":changed["reviewer_scope"]["tool_call_id"]="other"
  if change=="remove":changed.pop("reviewer_scope")
  if change=="input":changed["input"]["content"]="changed"
  if change=="context":changed["context"]["cancel_epoch"]+=1
  if change=="cross-kind":changed.update(tool_name="bash",input={"command":"printf changed"})
  with pytest.raises(Conflict):prepare(f,changed)
  assert f["control"].requests[a["request_id"]]["state"]=="canceled"
  assert f["store"].snapshot()["retired_intents"]==1
  with pytest.raises(Conflict):consume(f,permit)
  assert external(f)==[]


def test_legacy_row_cannot_upgrade_to_scoped(tmp_path):
  f=fixture(tmp_path);a=arguments(f);legacy=deepcopy(a);legacy.pop("reviewer_scope");p=prepare(f,legacy)
  with pytest.raises(Conflict):prepare(f,a)
  assert f["shared"].status(p["operation_id"])["state"]=="revoked"
  assert f["store"].snapshot()["retired_intents"]==0


def test_provider_missing_has_zero_store_or_bridge_call(tmp_path,monkeypatch):
  f=fixture(tmp_path,provider=False);a=arguments(f)
  monkeypatch.setattr(f["store"],"verify_current",lambda _:pytest.fail("Store verify"))
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",lambda *a:pytest.fail("Store cleanup"))
  monkeypatch.setattr(f["control"].bridge,"prepare",lambda *a:pytest.fail("bridge prepare"))
  with pytest.raises(Conflict):prepare(f,a)
  assert f["control"].requests[a["request_id"]]["state"]=="canceled"
  assert not f["shared"]._operations and external(f)==[]


@pytest.mark.parametrize("bad",[None,{},True,{"control_id":CONTROL,"confirmation_ref":CONFIRM,"tool_call_id":"x","request_ref":False}])
def test_explicit_invalid_scope_is_fixed_and_no_cleanup(tmp_path,bad):
  f=fixture(tmp_path);a=arguments(f);a["reviewer_scope"]=bad
  with pytest.raises(ConfigError):prepare(f,a)
  assert f["store"].snapshot()["retired_intents"]==0
  assert f["control"].requests[a["request_id"]]["state"]=="canceled"


@pytest.mark.parametrize("stage",["bridge-throw","bridge-after-prepare","bad-return","bind"])
def test_unknown_prepare_or_binding_keeps_tombstone_and_retires_owned_intent(tmp_path,monkeypatch,stage):
  f=fixture(tmp_path);a=arguments(f);bridge=f["control"].bridge;original=bridge.prepare;marker="SYNTHETIC_PRIVATE_ERROR"
  def failed(*args):
    if stage=="bridge-after-prepare":original(*args)
    if stage=="bad-return":return {"operation_id":"f"*32}
    raise RuntimeError(marker)
  if stage=="bind":
    preparebinder=f["control"]._scope_binder(f["principal"])
    monkeypatch.setattr(preparebinder,"bind",lambda *args:failed())
  else:monkeypatch.setattr(bridge,"prepare",failed)
  with pytest.raises(Conflict) as caught:prepare(f,a)
  assert marker not in "".join(traceback.format_exception(caught.value))
  row=f["control"].requests[a["request_id"]]
  assert row["state"]=="canceled" and f["store"].snapshot()["retired_intents"]==1
  assert row["prepared"] is not None if stage=="bind" else row["prepared"] is None
  if stage=="bridge-after-prepare":assert len(bridge.records)==1  # 未返回投影不猜ID/删除未知记录。
  with pytest.raises(Conflict):prepare(f,a)
  assert external(f)==[]


@pytest.mark.parametrize("phase",["issue","consume"])
@pytest.mark.parametrize("reason",["retire","expiry","update"])
def test_scope_or_authority_change_blocks_human_permission(tmp_path,phase,reason):
  f=fixture(tmp_path);a=arguments(f);p=prepare(f,a);permit=issue(f,p) if phase=="consume" else None
  if reason=="retire":f["store"].retire_intent(f["control"].requests[a["request_id"]]["scope_refs"]["session_scope"],f["current"]["user_intent_ref"])
  if reason=="expiry":f["clock"][0]=10000
  if reason=="update":
    old=f["authority_snapshot"];doc=deepcopy(old["document"]);doc["generation"]+=1;doc["limits"]["max_calls"]-=1
    f["authority"].update(doc,expected_identity=old["identity"])
  with pytest.raises(Conflict):consume(f,permit) if permit else issue(f,p)
  assert external(f)==[] and f["control"].requests[a["request_id"]]["state"]=="canceled"


@pytest.mark.parametrize("fault",["expiry","io"])
def test_initial_current_unknown_can_cleanup_only_original_owned_mapping(tmp_path,monkeypatch,fault):
  f=fixture(tmp_path);a=arguments(f)
  if fault=="expiry":f["clock"][0]=10000
  else:
    def unknown(_):raise RuntimeError("SYNTHETIC_PRIVATE")
    monkeypatch.setattr(f["store"],"verify_current",unknown)
  with pytest.raises(Conflict):prepare(f,a)
  assert f["store"].snapshot()["retired_intents"]==1
  assert not f["shared"]._operations


@pytest.mark.parametrize("bad",["other-intent","request-mismatch"])
def test_existing_foreign_metadata_cannot_cleanup_another_intent(tmp_path,monkeypatch,bad):
  f=fixture(tmp_path);a=arguments(f);other="4"*32
  f["scopes"].handle(f["principal"],"ordinary_reviewer_scope_allocate_intent",{"control_id":CONTROL,"confirmation_ref":other})
  b=arguments(f,tool_id="other/tool",confirmation=other)
  if bad=="other-intent":a["reviewer_scope"]=b["reviewer_scope"];a["request_id"]=b["request_id"]
  else:a["reviewer_scope"]["request_ref"]=b["request_id"]
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",lambda *args:pytest.fail("cannot retire foreign nonce"))
  with pytest.raises(Conflict):prepare(f,a)
  assert f["store"].snapshot()["retired_intents"]==0
  assert external(f)==[]


def test_cleanup_ack_loss_is_unknown_and_explicit_original_nonce_retry(tmp_path,monkeypatch):
  f=fixture(tmp_path);a=arguments(f);prepare(f,a);original=f["store"].retire_intent_confirmation;calls=[]
  def lost(*args):
    calls.append(args);result=original(*args)
    if len(calls)==1:raise RuntimeError("SYNTHETIC_PRIVATE")
    return result
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",lost)
  with pytest.raises(Conflict,match="CLEANUP_UNKNOWN"):cancel(f,a)
  assert f["control"].requests[a["request_id"]]["scope_cleanup"]=="unknown"
  assert f["store"].snapshot()["retired_intents"]==1
  assert cancel(f,a)=={"request_id":a["request_id"],"state":"canceled"}
  assert calls[0]==calls[1] and len(calls)==2
  assert f["control"].requests[a["request_id"]]["scope_cleanup"]=="confirmed"


@pytest.mark.parametrize("consumed",[False,True])
def test_sibling_cancel_closes_intent_without_releasing_consumed_writer(tmp_path,consumed):
  f=fixture(tmp_path);a=arguments(f,tool="bash",tool_id="a");b=arguments(f,tool="write",tool_id="b")
  pa=prepare(f,a);pb=prepare(f,b);permit=issue(f,pa)
  if consumed:
    ticket=consume(f,permit);lease_before=deepcopy(f["host"].store.read(ticket["lease_id"]))
  cancel(f,b)
  with pytest.raises(Conflict):issue(f,pb)
  if not consumed:
    with pytest.raises(Conflict):consume(f,permit)
    assert external(f)==[]
  else:
    assert f["control"].requests[a["request_id"]]["state"]=="consumed"
    assert f["host"].store.read(ticket["lease_id"])==lease_before
    assert f["control"].shell_bridge.status(f["principal"],pa["operation_id"])["execution"]["state"]=="consumed"


def test_bound_context_callback_never_acquires_service_or_reenters_admission(tmp_path,monkeypatch):
  f=fixture(tmp_path);a=arguments(f);p=prepare(f,a)
  class Forbidden:
    def __enter__(self):pytest.fail("borrowed service acquire")
    def __exit__(self,*args):pass
  monkeypatch.setattr(f["control"]._scope_bindings,"mutex",Forbidden())
  monkeypatch.setattr(f["scopes"],"mutex",Forbidden())
  for name in ("prepared","revoke","status"):
    monkeypatch.setattr(f["shared"],name,lambda *args:pytest.fail("Admission reentry"))
  permit=issue(f,p)
  assert consume(f,permit)["state"]=="consumed"


def test_business_scope_fields_do_not_select_scoped_provider(tmp_path):
  f=fixture(tmp_path);a=arguments(f);a.pop("reviewer_scope");a["input"]["reviewer_scope"]={"control_id":CONTROL}
  with pytest.raises(ConfigError):prepare(f,a)
  assert f["store"].snapshot()["retired_intents"]==0


def test_scope_cleanup_does_not_add_rpc_method_and_closing_allows_owned_cleanup(tmp_path):
  f=fixture(tmp_path);a=arguments(f);prepare(f,a);f["host"].service.closing=True
  cancel(f,a)
  assert f["store"].snapshot()["retired_intents"]==1 and len(METHODS)==6


@pytest.mark.parametrize("bad",["unknown", "subclass", "other-host", "other-mutex", "no-shared"])
def test_provider_constructor_rejects_before_bridge(tmp_path,monkeypatch,bad):
  f=fixture(tmp_path);provider=f["scopes"];shared=f["shared"]
  if bad=="unknown":provider=object()
  if bad=="subclass":
    class Derived(ReviewerScopeControl):pass
    provider=Derived(f["host"],f["store"])
  if bad=="other-host":provider=object.__new__(ReviewerScopeControl);provider.host=object();provider.mutex=f["host"].service.mutex
  if bad=="other-mutex":provider.mutex=object()
  if bad=="no-shared":shared=None
  monkeypatch.setattr("agentcfg.pi_admission_control.FileOperationAdmissions",lambda *a,**k:pytest.fail("bridge constructed"))
  with pytest.raises(ConfigError):FileAdmissionControl(f["operations"],shared_admissions=shared,reviewer_scope_control=provider)


def test_reread_failure_and_retire_do_not_retry_cleanup_within_one_call(tmp_path,monkeypatch):
  f=fixture(tmp_path);a=arguments(f,tool_id="a");b=arguments(f,tool_id="b");prepare(f,a);prepare(f,b)
  original=f["store"].retire_intent_confirmation;calls=[]
  def failed(*args):calls.append(args);raise RuntimeError("private")
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",failed)
  changed=deepcopy(a);changed["context"]["cancel_epoch"]+=1
  with pytest.raises(Conflict):prepare(f,changed)
  assert len(calls)==1
  assert all(f["control"].requests[x["request_id"]]["state"]=="canceled" for x in (a,b))
  with pytest.raises(Conflict):f["call"]("retire",{"control_id":"admission"})
  assert len(calls)==2  # 一次显式retire只确认一次原intent，不为siblings重试。
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",original)
  f["call"]("retire",{"control_id":"admission"})
  assert f["store"].snapshot()["retired_intents"]==1


def test_same_scoped_prepare_threads_share_original_operation(tmp_path):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  f=fixture(tmp_path);a=arguments(f);barrier=Barrier(2)
  def run():barrier.wait();return prepare(f,deepcopy(a))
  with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(lambda _:run(),range(2)))
  assert values[0]==values[1] and len(f["shared"]._operations)==1


def test_failed_cleanup_never_closes_another_owned_intent(tmp_path,monkeypatch):
  f=fixture(tmp_path);a=arguments(f);prepare(f,a);other="7"*32
  refs=f["scopes"].handle(f["principal"],"ordinary_reviewer_scope_allocate_intent",{"control_id":CONTROL,"confirmation_ref":other})
  f["current"]["user_intent_ref"]=refs["intent_ref"]
  b=arguments(f,tool_id="other",confirmation=other);pb=prepare(f,b)
  def failed(*args):raise RuntimeError("private")
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",failed)
  with pytest.raises(Conflict):cancel(f,a)
  assert f["control"].requests[b["request_id"]]["state"]=="prepared"
  assert issue(f,pb)["source"]=="human"


@pytest.mark.parametrize("cleanup_lost",[False,True])
def test_unknown_shell_consumption_keeps_original_allocation_and_writer(tmp_path,monkeypatch,cleanup_lost):
  f=fixture(tmp_path);a=arguments(f,tool="bash",tool_id="unknown/a");b=arguments(f,tool_id="pending/b")
  p=prepare(f,a);pb=prepare(f,b);permit=issue(f,p);original=f["host"].store.allocate
  marker="SYNTHETIC_PRIVATE_ALLOCATION";cleanups=[];cleanup=f["store"].retire_intent_confirmation
  def retire(*args):
    cleanups.append(args);result=cleanup(*args)
    if cleanup_lost:raise OSError(marker)
    return result
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",retire)
  def lost(**kwargs):original(**kwargs);raise OSError(marker)
  monkeypatch.setattr(f["host"].store,"allocate",lost)
  with pytest.raises(Conflict,match="OPERATION_EXECUTION_UNKNOWN") as caught:consume(f,permit)
  assert marker not in "".join(traceback.format_exception(caught.value))
  assert len(cleanups)==1 and f["control"].requests[b["request_id"]]["state"]=="canceled"
  with pytest.raises(Conflict):issue(f,pb)
  row=f["control"].requests[a["request_id"]]
  assert row["scope_cleanup"]==("unknown" if cleanup_lost else "confirmed")
  leases=external(f);assert len(leases)==1
  lease=deepcopy(leases[0])
  assert f["control"].requests[a["request_id"]]["state"]=="consumed"
  assert f["host"].store.read(lease["lease_id"])==lease
  status=f["control"].shell_bridge.status(f["principal"],p["operation_id"])
  assert status["execution"]["state"]=="unknown" and status["execution"]["lease_id"]==lease["lease_id"]
  with pytest.raises(Conflict):consume(f,permit)
  assert len(external(f))==1


def test_cleanup_wrapper_requires_exact_original_expected_refs_without_store(tmp_path,monkeypatch):
  f=fixture(tmp_path);a=arguments(f);prepare(f,a)
  monkeypatch.setattr(f["store"],"retire_intent_confirmation",lambda *args:pytest.fail("foreign cleanup Store"))
  for expected in ({"intent_ref":"f"*32,"request_ref":a["request_id"]},
      {"intent_ref":a["context"]["user_intent_ref"],"request_ref":"f"*32}):
    with pytest.raises(Conflict):f["scopes"].retire_operation_intent(f["principal"],a["reviewer_scope"],session_id=a["context"]["session_id"],**expected)
  assert f["control"].requests[a["request_id"]]["state"]=="prepared"



def test_scoped_issue_unknown_error_is_fixed_and_intent_retired(tmp_path,monkeypatch):
  f=fixture(tmp_path);a=arguments(f);p=prepare(f,a);marker="SYNTHETIC_PRIVATE_ISSUE"
  def failed(*args,**kwargs):raise OSError(marker)
  monkeypatch.setattr(f["control"].bridge,"issue",failed)
  with pytest.raises(Conflict) as caught:issue(f,p)
  assert marker not in "".join(traceback.format_exception(caught.value))
  assert f["control"].requests[a["request_id"]]["state"]=="canceled"
  assert f["store"].snapshot()["retired_intents"]==1 and external(f)==[]


def test_second_scoped_controller_same_shared_admission_rejected_before_bridge(tmp_path,monkeypatch):
  from agentcfg.pi_operations import OrdinaryOperations
  f=fixture(tmp_path);a=arguments(f);p=prepare(f,a);permit=issue(f,p)
  second=OrdinaryOperations(f["host"],now=f["operations"].now)
  before=f["file"].read_bytes();status=f["shared"].status(p["operation_id"])
  monkeypatch.setattr(f["store"],"verify_current",lambda _:pytest.fail("scope query"))
  with pytest.raises(Conflict,match="REVIEW_SCOPE_OWNER_ALREADY_BOUND"):
    FileAdmissionControl(second,shared_admissions=f["shared"],reviewer_scope_control=f["scopes"])
  assert second.admission is None and f["file"].read_bytes()==before
  assert f["shared"].status(p["operation_id"])==status
  assert f["control"].bridge.permits[permit["permit_id"]]==p["operation_id"]


def test_same_host_different_ledger_cannot_install_second_scoped_controller(tmp_path,monkeypatch):
  from agentcfg.pi_operations import OrdinaryOperations
  f=fixture(tmp_path);second=OrdinaryOperations(f["host"],now=f["operations"].now)
  other=OperationAdmissions(f["shared"].activation_id)
  monkeypatch.setattr("agentcfg.pi_admission_control.FileOperationAdmissions",lambda *a,**k:pytest.fail("bridge assembled"))
  with pytest.raises(Conflict,match="REVIEW_SCOPE_OWNER_ALREADY_BOUND"):
    FileAdmissionControl(second,shared_admissions=other,reviewer_scope_control=f["scopes"])
  assert second.admission is None and other._reviewer_scope_owner is None


def test_failed_scoped_assembly_permanently_claims_host_and_ledger(tmp_path,monkeypatch):
  from agentcfg.pi_operations import OrdinaryOperations
  f=fixture(tmp_path,provider=False);first=OrdinaryOperations(f["host"],now=f["operations"].now)
  def failed(*a,**k):raise ConfigError("synthetic-assembly-failed")
  monkeypatch.setattr("agentcfg.pi_admission_control.FileOperationAdmissions",failed)
  with pytest.raises(ConfigError):FileAdmissionControl(first,shared_admissions=f["shared"],reviewer_scope_control=f["scopes"])
  owner=f["host"]._scoped_admission_owner
  assert f["shared"]._reviewer_scope_owner is owner and f["shared"]._reviewer_scope_binder is None
  for ledger in (f["shared"],OperationAdmissions(f["shared"].activation_id)):
    second=OrdinaryOperations(f["host"],now=f["operations"].now)
    with pytest.raises(Conflict,match="REVIEW_SCOPE_OWNER_ALREADY_BOUND"):
      FileAdmissionControl(second,shared_admissions=ledger,reviewer_scope_control=f["scopes"])
    assert second.admission is None
  assert f["shared"]._reviewer_scope_owner is owner
