"""原scoped控制面/bridge的许可消费；仅合成政策、账本和假后端。"""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from threading import RLock
import traceback

import pytest

from agentcfg.pi_admission_control import FileAdmissionControl
from agentcfg.pi_admitted_shell import ShellOperationAdmissions
from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.pi_reviewer_decision import ReviewerDecisionControl
from agentcfg.pi_reviewer_ledger import ReviewerLedger
from agentcfg.pi_reviewer_scope_control import ReviewerScopeControl
from agentcfg.storage import Conflict
from agentcfg.schema import ConfigError
from test_pi_admitted_shell import fixture as shell_fixture
from test_pi_reviewer_account_scopes import bound
from test_pi_reviewer_scopes_account import request
from test_pi_reviewer_scopes import fixture as scopes_fixture
from test_pi_scoped_admission_control import arguments, prepare, consume, external, CONTROL, CONFIRM


def fixture(tmp_path, monkeypatch, *, tool="write", automatic=True, install=True, account=True):
  business=tmp_path/"business";business.mkdir()
  base_bridge,ops,host,principal,current,_,proof=shell_fixture(business,profile="pi-full",reviewer_policy=automatic)
  current["reviewer_identity"]="9"*64
  private=tmp_path/"private";private.mkdir();f=scopes_fixture(private)
  scopes=ReviewerScopeControl(host,f["store"])
  scopes.handle(principal,"ordinary_reviewer_scope_open",{"control_id":CONTROL,"session_id":current["session_id"]})
  refs=scopes.handle(principal,"ordinary_reviewer_scope_allocate_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM})
  current["user_intent_ref"]=refs["intent_ref"]
  owned={}
  shared=OperationAdmissions(host.store.owner["manager_activation_id"],now_ms=lambda:int(ops.now().timestamp()*1000),
    reviewer_current=lambda p,c:owned["control"]._scope_bindings.reviewer_current_borrowed(p,c))
  def factory(operations,**kwargs):return ShellOperationAdmissions(operations,binding_name="shell",
    backend_preflight=base_bridge.backend_preflight,**kwargs)
  control=FileAdmissionControl(ops,shared_admissions=shared,shell_bridge_factory=factory,reviewer_scope_control=scopes)
  owned["control"]=control
  def call(name,args):return control.handle(principal,"ordinary_admission_"+name,args)
  call("open",{"control_id":"admission","session_id":current["session_id"]})
  f.update(control=control,scopes=scopes,shared=shared,operations=ops,host=host,principal=principal,current=current,call=call)
  # 原manifest显式合成reviewer规则与fake backend只用于接缝，不代表生产资格。
  bridge=control.shell_bridge if tool=="bash" else control.bridge
  args=arguments(f,tool=tool);p=prepare(f,args);row=control.operation_requests[p["operation_id"]]
  f["refs"]=control._scope_bindings.scopes_for_prepared(p)
  ledger=bound(f) if account else ReviewerLedger(tmp_path/"settlement",limits={"currency":"USD","max_calls":20,"max_cost_units":1000000})
  config={"current_provider":lambda _:control._context(row["request_id"]),
    "resolution_provider":lambda _:deepcopy(p["resolution"]),
    "qualification_provider":lambda _:{"enabled":True,"role_allows":True,"automatic_risk_allowed":True},
    "scope_provider":control._scope_bindings.scopes_for_prepared,"scope_current":control._scope_bindings.scope_current,
    "route_identity":"9"*64,"pricing":request(f["refs"])["pricing"],
    "token_limits":{"input_tokens":100,"output_tokens":10},"mutex":host.service.mutex}
  if install:config["admission_control"]=control
  decision=ReviewerDecisionControl(shared,ledger,**config)
  f.update(decision=decision,config=config,ledger=ledger,prepared=p,args=args,bridge=bridge,row=row,account=account)
  return f


def settle(f, *, decision="allow"):
  control=f["decision"];begin=control.begin(f["prepared"]["operation_id"])
  assert begin["ticket"] is not None
  control.commit_send(begin["ticket"])
  raw=json.dumps({"schema_version":1,**begin["binding"],"decision":decision,
    "reason_code":{"allow":"authorized-in-scope","ask":"needs-human","deny":"outside-user-scope"}[decision]})
  if f["account"]:
    result=control.conclude_transport(begin["ticket"],{"outcome":"valid","platform_requests":1,"response":raw,
      "gate_attempted":True,"gate_acknowledged":True})
  else:
    control.mark_sent(begin["ticket"])
    result=control.conclude(begin["ticket"],{"outcome":"valid","requests":1,"response":raw})
  f["begin"]=begin;return result


@pytest.mark.parametrize("tool",["write","bash"])
@pytest.mark.parametrize("account",[False,True])
def test_reviewer_permit_routes_through_original_bridge_and_consumes_once(tmp_path,monkeypatch,tool,account):
  f=fixture(tmp_path,monkeypatch,tool=tool,account=account);result=settle(f)
  assert result["status"]=="permitted" and result["permit"]["source"]=="reviewer"
  assert f["bridge"].permits[result["permit"]["permit_id"]]==f["prepared"]["operation_id"]
  other=f["control"].bridge if tool=="bash" else f["control"].shell_bridge
  assert result["permit"]["permit_id"] not in other.permits
  assert result["permit"]["operation_digest"]==f["prepared"]["operation_digest"]
  assert consume(f,result["permit"])["state"]=="consumed"
  assert len(external(f))==1
  with pytest.raises(Conflict):consume(f,result["permit"])


@pytest.mark.parametrize("tool",["write","bash"])
def test_actual_default_still_requires_human_and_no_reviewer_attempt(tmp_path,monkeypatch,tool):
  f=fixture(tmp_path,monkeypatch,tool=tool,automatic=False)
  assert f["prepared"]["resolution"]["policy"]["requires_human"] is True
  assert f["decision"].begin(f["prepared"]["operation_id"])["status"]=="human-required"
  assert f["ledger"].snapshot()["reserved_calls"]==0 and not f["bridge"].permits and not external(f)
  permit=f["call"]("issue",{"operation_id":f["prepared"]["operation_id"],"context":f["current"]})
  assert permit["source"]=="human" and consume(f,permit)["state"]=="consumed"


@pytest.mark.parametrize("decision",["ask","deny"])
def test_non_allow_does_not_register_bridge_permit(tmp_path,monkeypatch,decision):
  f=fixture(tmp_path,monkeypatch);result=settle(f,decision=decision)
  assert result["permit"] is None and not f["bridge"].permits and not external(f)
  assert f["ledger"].observe(f["prepared"]["operation_id"])["decision"]==decision


@pytest.mark.parametrize("change",["foreign-id","body-ref","context","digest","extra"])
def test_unverified_prepared_projection_cannot_cancel_original(tmp_path,monkeypatch,change):
  f=fixture(tmp_path,monkeypatch);p=deepcopy(f["prepared"])
  if change=="foreign-id":p["operation_id"]="f"*32
  elif change=="body-ref":p["private_input_ref"]="f"*32
  elif change=="context":p["context"]["cancel_epoch"]+=1
  elif change=="digest":p["operation_digest"]="f"*64
  else:p["source"]="reviewer"
  with pytest.raises(Conflict,match="BINDING_MISMATCH"):
    f["control"]._issue_reviewer_prepared(p,current=f["current"])
  assert f["shared"].status(f["prepared"]["operation_id"])["state"]=="prepared"
  assert f["store"].verify_current(f["refs"]) is True and not f["bridge"].permits


@pytest.mark.parametrize("drift",["cancel","retire","ceiling"])
def test_fresh_drift_before_bridge_issue_never_allows_original(tmp_path,monkeypatch,drift):
  f=fixture(tmp_path,monkeypatch)
  if drift=="cancel":f["control"]._cancel(f["principal"],f["row"])
  elif drift=="retire":f["store"].retire_intent(f["refs"]["session_scope"],f["refs"]["intent_ref"])
  else:f["host"].manifest()["permission_policy"]["rules"].clear()
  with pytest.raises(Conflict):f["control"]._issue_reviewer_prepared(f["prepared"],current=f["current"])
  assert not f["bridge"].permits and not external(f)


@pytest.mark.parametrize("phase",["before","after"])
def test_issue_failure_retains_unknown_mapping_and_fixed_exception(tmp_path,monkeypatch,phase):
  f=fixture(tmp_path,monkeypatch);original=f["bridge"].issue
  def failed(*a,**kw):
    if phase=="after":original(*a,**kw)
    raise OSError("SYNTHETIC_PRIVATE_ISSUE_ERROR")
  monkeypatch.setattr(f["bridge"],"issue",failed)
  with pytest.raises(Conflict,match="RECONCILIATION_UNKNOWN") as caught:settle(f)
  assert "SYNTHETIC_PRIVATE" not in "".join(traceback.format_exception(caught.value))
  assert f["shared"].status(f["prepared"]["operation_id"])["state"]=="revoked"
  assert len(f["bridge"].permits)==(phase=="after") and not external(f)
  row=f["ledger"].observe(f["prepared"]["operation_id"])
  assert row["requests"]==1 and row["outcome"]=="valid"
  with pytest.raises(Conflict):f["control"]._issue_reviewer_prepared(f["prepared"],current=f["current"])


@pytest.mark.parametrize("case",["wrong-admission","wrong-mutex","wrong-type"])
def test_constructor_must_share_original_native_control_and_mutex(tmp_path,monkeypatch,case):
  f=fixture(tmp_path,monkeypatch,install=False);config=dict(f["config"]);config["admission_control"]=f["control"]
  admissions=f["shared"]
  if case=="wrong-admission":admissions=OperationAdmissions(f["shared"].activation_id)
  elif case=="wrong-mutex":config["mutex"]=RLock()
  else:config["admission_control"]=object()
  with pytest.raises(ConfigError):ReviewerDecisionControl(admissions,f["ledger"],**config)
  assert f["control"]._reviewer_decision_owner is None


def test_constructor_infers_original_mutex_and_permanently_rejects_second_owner(tmp_path,monkeypatch):
  f=fixture(tmp_path,monkeypatch,install=False);config=dict(f["config"]);config.pop("mutex");config["admission_control"]=f["control"]
  decision=ReviewerDecisionControl(f["shared"],f["ledger"],**config)
  assert decision.mutex is f["host"].service.mutex
  with pytest.raises(Conflict,match="OWNER_ALREADY_BOUND"):ReviewerDecisionControl(f["shared"],f["ledger"],**config)
  f["control"].retire(f["principal"],{"control_id":"admission"})
  with pytest.raises(Conflict,match="OWNER_ALREADY_BOUND"):ReviewerDecisionControl(f["shared"],f["ledger"],**config)


def test_new_internal_method_is_not_a_model_or_manager_rpc(tmp_path,monkeypatch):
  f=fixture(tmp_path,monkeypatch)
  with pytest.raises(ConfigError):f["control"].handle(f["principal"],"ordinary_admission_issue_reviewer_prepared",{})
  assert not f["bridge"].permits and not external(f)


def test_issue_and_consume_qualifier_run_under_original_service_mutex(tmp_path,monkeypatch):
  f=fixture(tmp_path,monkeypatch);observed=[];original=f["shared"]._reviewer_current
  def qualifier(p,c):
    observed.append(f["host"].service.mutex._is_owned())
    return original(p,c)
  monkeypatch.setattr(f["shared"],"_reviewer_current",qualifier)
  result=settle(f);consume(f,result["permit"])
  assert observed==[True,True]


def test_concurrent_original_ticket_settlement_signs_one_bridge_permit(tmp_path,monkeypatch):
  f=fixture(tmp_path,monkeypatch);d=f["decision"];b=d.begin(f["prepared"]["operation_id"]);d.commit_send(b["ticket"])
  value={"outcome":"valid","platform_requests":1,"gate_attempted":True,"gate_acknowledged":True,
    "response":json.dumps({"schema_version":1,**b["binding"],"decision":"allow","reason_code":"authorized-in-scope"})}
  def conclude():
    try:return d.conclude_transport(b["ticket"],value)
    except Conflict as error:return str(error)
  with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(lambda _:conclude(),range(2)))
  permitted=[r for r in results if type(r) is dict]
  assert len(permitted)==1 and "REVIEW_DECISION_ALREADY_SETTLED" in results
  assert len(f["bridge"].permits)==1
  assert consume(f,permitted[0]["permit"])["state"]=="consumed" and len(external(f))==1
  assert f["ledger"].snapshot()["committed_calls"]==1


@pytest.mark.parametrize("change",["retire","manager-dies"])
def test_issued_original_permit_cannot_survive_scope_or_owner_loss(tmp_path,monkeypatch,change):
  f=fixture(tmp_path,monkeypatch);result=settle(f)
  if change=="retire":f["store"].retire_intent(f["refs"]["session_scope"],f["refs"]["intent_ref"])
  else:
    manager=f["host"].store.read(f["principal"].lease_id)
    f["host"].store.processes.current.pop(manager["process_identity"]["pid"])
  with pytest.raises(Conflict):consume(f,result["permit"])
  assert not external(f)
  assert result["permit"]["permit_id"] in f["bridge"].permits
