"""原Decision ticket、scope_required账户与平台计数替身；零SDK/真实账户。"""
from copy import deepcopy
import json
import traceback

import pytest

from agentcfg.pi_reviewer_decision import ReviewerDecisionControl
from agentcfg.storage import Conflict, Tree
from agentcfg.schema import ConfigError
from test_pi_reviewer_decision import fixture as decision_fixture, wire
from test_pi_reviewer_account_scopes import bound, raw_budget
from test_pi_reviewer_scopes import fixture as scope_fixture, refs
from test_pi_reviewer_scopes_account import request


def fixture(tmp_path):
  a=tmp_path/"private";a.mkdir();s=scope_fixture(a);s["refs"]=refs(s);ledger=bound(s)
  b=tmp_path/"decision";b.mkdir();f=decision_fixture(b)
  f["current"]["user_intent_ref"]=s["refs"]["intent_ref"]
  f["prepared"]=f["admissions"].prepare(s["refs"]["request_ref"],current=f["current"],resolved=f["resolved"],private_input=f["private"])
  config=deepcopy({k:v for k,v in f["config"].items() if not callable(v) and k!="mutex"})
  config.update({k:v for k,v in f["config"].items() if callable(v) or k=="mutex"})
  config.update(scope_provider=lambda _:deepcopy(s["refs"]),scope_current=lambda p,r:s["store"].verify_current(r),
    pricing=request(s["refs"])["pricing"],token_limits=request(s["refs"])["token_limits"])
  f.update(ledger=ledger,control=ReviewerDecisionControl(f["admissions"],ledger,**config),account=s)
  begin=f["control"].begin(f["prepared"]["operation_id"]);f["begin"]=begin;f["ticket"]=begin["ticket"]
  return f


def report(f, *, count=0, attempted=False, acknowledged=False, outcome="canceled", decision="allow"):
  return {"outcome":outcome,"platform_requests":count,"response":wire(f["begin"],decision) if outcome=="valid" else None,
    "gate_attempted":attempted,"gate_acknowledged":acknowledged}


def settle(f, value):return f["control"].conclude_transport(f["ticket"],value)
def observe(f):return f["ledger"].observe(f["prepared"]["operation_id"])


def test_reserved_zero_transport_facts_settle_original_ticket_without_send(tmp_path):
  f=fixture(tmp_path);result=settle(f,report(f))
  assert result["permit"] is None and observe(f)["requests"]==0
  assert observe(f)["send_state"]=="not-sent"
  assert f["control"].tickets[f["ticket"]]["settled"] is True


def closed(f):
  assert f["control"].tickets[f["ticket"]]["settled"] is True
  for method in (f["control"].commit_send,f["control"].mark_sent):
    with pytest.raises(Conflict,match="ALREADY_SETTLED"):method(f["ticket"])
  with pytest.raises(Conflict,match="ALREADY_SETTLED"):settle(f,report(f))
  with pytest.raises(Conflict,match="ALREADY_SETTLED"):
    f["control"].conclude(f["ticket"],{"outcome":"canceled","requests":None,"response":None})


@pytest.mark.parametrize("state,count,attempted,acknowledged,requests",[
  ("reserved",0,False,False,0),("reserved",0,True,False,0),
  ("committed",0,True,False,None),("committed",0,True,True,None),
  ("committed",1,True,True,1),("committed",1,False,False,1),("sent",1,True,True,1)])
def test_transport_reconciles_original_ready_facts_not_local_zero(tmp_path,state,count,attempted,acknowledged,requests):
  f=fixture(tmp_path)
  if state!="reserved":f["control"].commit_send(f["ticket"])
  if state=="sent":f["control"].mark_sent(f["ticket"])
  result=settle(f,report(f,count=count,attempted=attempted,acknowledged=acknowledged))
  row=observe(f);assert row["requests"]==requests and row["outcome"]=="canceled" and result["permit"] is None
  assert f["ledger"].snapshot()["committed_calls"]==(state!="reserved")
  assert row["settled_units"]==(0 if state=="reserved" else None)
  closed(f)


@pytest.mark.parametrize("count,attempted,ack",[(0,False,False),(0,True,False),(1,False,False),(1,True,False)])
def test_valid_without_one_acknowledged_platform_call_is_protocol_failure(tmp_path,count,attempted,ack):
  f=fixture(tmp_path)
  if count:f["control"].commit_send(f["ticket"])
  result=settle(f,report(f,count=count,attempted=attempted,acknowledged=ack,outcome="valid"))
  assert result["permit"] is None and observe(f)["outcome"]=="protocol-failure"
  closed(f)


@pytest.mark.parametrize("decision,status",[("allow","permitted"),("deny","blocked"),("ask","awaiting-human")])
def test_one_sent_valid_candidate_retains_original_decision_and_once_permission(tmp_path,decision,status):
  f=fixture(tmp_path);f["control"].commit_send(f["ticket"])
  result=settle(f,report(f,count=1,attempted=True,acknowledged=True,outcome="valid",decision=decision))
  assert result["status"]==status and observe(f)["decision"]==decision
  assert observe(f)["requests"]==1 and observe(f)["settled_units"] is None
  if result["permit"]:
    value=f["admissions"].consume(result["permit"],current=f["current"],resolved=f["resolved"])
    assert value["private_input"]==f["private"]
    with pytest.raises(Conflict):f["admissions"].consume(result["permit"],current=f["current"],resolved=f["resolved"])
  closed(f)


@pytest.mark.parametrize("state,count,attempted,ack",[
  ("reserved",1,True,True),("reserved",0,True,True),("sent",0,True,True),("committed",1,False,True)])
def test_conflicting_transport_facts_burn_ticket_without_rewriting_row(tmp_path,state,count,attempted,ack):
  f=fixture(tmp_path)
  if state!="reserved":f["control"].commit_send(f["ticket"])
  if state=="sent":f["control"].mark_sent(f["ticket"])
  before=raw_budget(f["account"]["home"])
  with pytest.raises(Conflict,match="REVIEW_SEND_FACT_CONFLICT"):settle(f,report(f,count=count,attempted=attempted,acknowledged=ack))
  assert raw_budget(f["account"]["home"])==before
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"]=="revoked";closed(f)


@pytest.mark.parametrize("change",["binding","scope","attempt","terminal","state"])
def test_observed_original_binding_and_scope_must_match_ticket(tmp_path,monkeypatch,change):
  f=fixture(tmp_path);row=observe(f)
  if change=="binding":row["binding"]["request_id"]="f"*32
  if change=="scope":row["scope"]["intent_ref"]="f"*32
  if change=="attempt":row["attempt_claimed"]=False
  if change=="terminal":row["outcome"]="canceled"
  if change=="state":row["send_state"]="not-sent"
  before=raw_budget(f["account"]["home"])
  monkeypatch.setattr(f["ledger"],"observe",lambda _:deepcopy(row))
  with pytest.raises(Conflict,match="REVIEW_SEND_FACT_CONFLICT"):settle(f,report(f))
  assert raw_budget(f["account"]["home"])==before;closed(f)


@pytest.mark.parametrize("change",["no-observe","exception","updating"])
def test_unobservable_facts_never_fall_back_get_finish_zero_or_retry(tmp_path,monkeypatch,change):
  f=fixture(tmp_path);marker="SYNTHETIC_PRIVATE_READ"
  def failed(*a,**k):raise OSError(marker)
  monkeypatch.setattr(f["ledger"],"get",lambda _:pytest.fail("fallback get"))
  monkeypatch.setattr(f["ledger"],"finish",lambda *a,**k:pytest.fail("finish unknown"))
  if change=="no-observe":monkeypatch.setattr(f["ledger"],"observe",None)
  if change=="exception":monkeypatch.setattr(f["ledger"],"observe",failed)
  if change=="updating":
    path=f["account"]["home"]/".agentcfg-workspaces/reviewer-budget.json"
    saved=json.loads(path.read_bytes());saved["state"]="updating";path.write_text(json.dumps(saved))
  before=raw_budget(f["account"]["home"])
  with pytest.raises(Conflict,match="RECONCILIATION_UNKNOWN") as caught:settle(f,report(f))
  assert marker not in "".join(traceback.format_exception(caught.value)) and raw_budget(f["account"]["home"])==before
  closed(f)


def test_ticket_closed_before_observation_blocks_late_commit_sent_and_conclude(tmp_path,monkeypatch):
  f=fixture(tmp_path);original=f["ledger"].observe
  def read(operation):closed(f);return original(operation)
  monkeypatch.setattr(f["ledger"],"observe",read)
  settle(f,report(f))
  assert observe(f)["send_state"]=="not-sent"
  assert f["control"].tickets[f["ticket"]]["transport_facts"]=={"platform_requests":0,"gate_attempted":False,"gate_acknowledged":False}


@pytest.mark.parametrize("key,value",[("platform_requests",True),("platform_requests",None),("platform_requests",2),
  ("gate_attempted",1),("gate_acknowledged",None),("outcome","invented"),("response","private"),("source","human")])
def test_malformed_transport_report_is_not_an_authority_or_fact(tmp_path,key,value):
  f=fixture(tmp_path);value_report=report(f);value_report[key]=value;before=raw_budget(f["account"]["home"])
  with pytest.raises(ConfigError):settle(f,value_report)
  assert f["control"].tickets[f["ticket"]]["settled"] is False and raw_budget(f["account"]["home"])==before


@pytest.mark.parametrize("step",["mark_sent","finish"])
@pytest.mark.parametrize("after",[False,True])
def test_facts_write_ack_failure_burns_ticket_and_preserves_actual_durable_row(tmp_path,monkeypatch,step,after):
  from agentcfg.pi_reviewer_ledger import ReviewerLedger
  f=fixture(tmp_path);f["control"].commit_send(f["ticket"]);original=getattr(ReviewerLedger,step);marker="SYNTHETIC_PRIVATE_WRITE"
  def failed(self,*args,**kwargs):
    if after:original(self,*args,**kwargs)
    raise OSError(marker)
  monkeypatch.setattr(ReviewerLedger,step,failed)
  with pytest.raises(Conflict,match="RECONCILIATION_UNKNOWN") as caught:settle(f,report(f,count=1,attempted=True,acknowledged=True,outcome="valid"))
  assert marker not in "".join(traceback.format_exception(caught.value));closed(f)
  raw=json.loads((f["account"]["home"]/".agentcfg-workspaces/reviewer-budget/reviewer-ledger.json").read_bytes())
  row=raw["rows"][f["prepared"]["operation_id"]]
  assert row["requests"]==(1 if step=="finish" or after else None)
  assert row["outcome"]==("valid" if step=="finish" and after else None)
  assert row["settled_units"] is None


@pytest.mark.parametrize("after",[False,True])
def test_commit_write_failure_observes_reserved_or_preserves_updating_unknown(tmp_path,monkeypatch,after):
  from agentcfg.pi_reviewer_ledger import ReviewerLedger
  f=fixture(tmp_path);original=ReviewerLedger.commit_send
  def failed(self,*args):
    if after:original(self,*args)
    raise OSError("private")
  with monkeypatch.context() as scoped:
    scoped.setattr(ReviewerLedger,"commit_send",failed)
    with pytest.raises(Conflict):f["control"].commit_send(f["ticket"])
  if after:
    with pytest.raises(Conflict,match="RECONCILIATION_UNKNOWN"):settle(f,report(f,attempted=True))
  else:
    assert settle(f,report(f,attempted=True))["permit"] is None and observe(f)["requests"]==0
  closed(f)


def test_commit_ready_ack_lost_retains_unknown_not_zero(tmp_path,monkeypatch):
  f=fixture(tmp_path);original=f["ledger"].commit_send
  def lost(*args):original(*args);raise OSError("private")
  monkeypatch.setattr(f["ledger"],"commit_send",lost)
  with pytest.raises(OSError):f["control"].commit_send(f["ticket"])
  settle(f,report(f,attempted=True))
  row=observe(f);assert row["send_state"]=="committed" and row["requests"] is None and row["settled_units"] is None
  assert f["ledger"].snapshot()["committed_calls"]==1;closed(f)


@pytest.mark.parametrize("change",["scope-retired","authority-expired","authority-updated"])
def test_valid_sent_after_live_qualification_changes_is_discarded_but_counts_one(tmp_path,change):
  f=fixture(tmp_path);f["control"].commit_send(f["ticket"]);a=f["account"]
  if change=="scope-retired":a["store"].retire_intent(a["refs"]["session_scope"],a["refs"]["intent_ref"])
  elif change=="authority-expired":a["clock"][0]=10000
  else:
    d=deepcopy(a["authority_snapshot"]["document"]);d["generation"]+=1;d["limits"]["max_calls"]-=1
    a["authority"].update(d,expected_identity=a["authority_snapshot"]["identity"])
  result=settle(f,report(f,count=1,attempted=True,acknowledged=True,outcome="valid"))
  assert result["permit"] is None and observe(f)["requests"]==1 and observe(f)["outcome"]=="discarded"
  assert f["ledger"].snapshot()["committed_calls"]==1;closed(f)



@pytest.mark.parametrize("outcome",["canceled","transport-failure","timeout"])
@pytest.mark.parametrize("legacy",[False,True])
def test_retired_scope_nonvalid_transport_facts_preserved_but_old_conclude_discards(tmp_path,outcome,legacy):
  f=fixture(tmp_path);f["control"].commit_send(f["ticket"]);a=f["account"]
  a["store"].retire_intent(a["refs"]["session_scope"],a["refs"]["intent_ref"])
  if legacy:result=f["control"].conclude(f["ticket"],{"outcome":outcome,"requests":None,"response":None})
  else:result=settle(f,report(f,attempted=True,outcome=outcome))
  assert result["permit"] is None and observe(f)["outcome"]==("discarded" if legacy else outcome)
  assert observe(f)["requests"] is None and observe(f)["settled_units"] is None;closed(f)


@pytest.mark.parametrize("step",["mark_sent","finish"])
def test_ready_facts_ack_loss_no_repeat_permit_even_if_completed_on_disk(tmp_path,monkeypatch,step):
  f=fixture(tmp_path);f["control"].commit_send(f["ticket"]);original=getattr(f["ledger"],step);calls=[]
  def lost(*args,**kwargs):calls.append(1);original(*args,**kwargs);raise OSError("private")
  monkeypatch.setattr(f["ledger"],step,lost)
  with pytest.raises(Conflict,match="RECONCILIATION_UNKNOWN"):settle(f,report(f,count=1,attempted=True,acknowledged=True,outcome="valid"))
  row=observe(f);assert row["requests"]==1 and row["outcome"]==("valid" if step=="finish" else None)
  assert len(calls)==1 and row["settled_units"] is None
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"]=="revoked";closed(f)


def test_scope_retired_after_finish_freshness_blocks_original_permission(tmp_path,monkeypatch):
  f=fixture(tmp_path);f["control"].commit_send(f["ticket"]);original=f["ledger"].finish;a=f["account"]
  def finish(*args,**kwargs):
    result=original(*args,**kwargs)
    a["store"].retire_intent(a["refs"]["session_scope"],a["refs"]["intent_ref"])
    return result
  monkeypatch.setattr(f["ledger"],"finish",finish)
  result=settle(f,report(f,count=1,attempted=True,acknowledged=True,outcome="valid"))
  assert result["permit"] is None and result["reason_code"]=="discarded"
  assert observe(f)["outcome"]=="valid" and observe(f)["requests"]==1;closed(f)


def test_authority_expiry_before_gate_commit_remains_reserved_and_zero_observed_send(tmp_path):
  f=fixture(tmp_path);f["account"]["clock"][0]=10000
  with pytest.raises(Conflict):f["control"].commit_send(f["ticket"])
  assert observe(f)["send_state"]=="reserved"
  result=settle(f,report(f,attempted=True,outcome="valid"))
  assert result["permit"] is None and observe(f)["outcome"]=="protocol-failure" and observe(f)["requests"]==0
  assert f["ledger"].snapshot()["committed_calls"]==0;closed(f)


@pytest.mark.parametrize("decision",[None,"ask","deny"])
def test_reconciled_unknown_ask_or_deny_retains_original_intent_lock(tmp_path,decision):
  f=fixture(tmp_path);f["control"].commit_send(f["ticket"])
  value=report(f,attempted=True) if decision is None else report(f,count=1,attempted=True,acknowledged=True,outcome="valid",decision=decision)
  settle(f,value);row=observe(f);a=f["account"]
  ref=a["store"].allocate_request({"session_scope":a["refs"]["session_scope"],"intent_ref":a["refs"]["intent_ref"],"tool_call_id":"next-tool"})
  value={key:deepcopy(row[key]) for key in ("binding","scope","pricing","token_limits")}
  value["binding"].update(operation_id="f"*32,request_id=ref)
  before=raw_budget(a["home"])
  with pytest.raises(Conflict,match="REVIEW_INTENT_"):f["ledger"].reserve(**value)
  assert raw_budget(a["home"])==before and row["settled_units"] is None
