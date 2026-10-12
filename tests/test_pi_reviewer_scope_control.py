"""临时真实账户scope + FakeProcesses，只接manager私有通道；不SDK/网络。"""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
import traceback

import pytest

from agentcfg.activity import digest
from agentcfg.pi_reviewer_scope_control import ReviewerScopeControl
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_operations import setup
from test_pi_reviewer_scopes import fixture as scope_fixture
from test_pi_supervisor import request

CONTROL = "1" * 32
CONFIRM = "2" * 32


def fixture(tmp_path, **limits):
  business = tmp_path / "business"; business.mkdir()
  operations, host, _, principal = setup(business)
  account = tmp_path / "private"; account.mkdir()
  f = scope_fixture(account)
  control = ReviewerScopeControl(host, f["store"], **limits)
  operations.reviewer_scope_control = control
  host.service.ordinary_handler = operations.handle
  def call(name, args, caller=principal):
    return host.service.handle(caller, request("ordinary_reviewer_scope_" + name, args))
  f.update(control=control, operations=operations, host=host, principal=principal, call=call)
  return f


def opened(f, control=CONTROL, session="sdk-session"):
  return f["call"]("open", {"control_id": control, "session_id": session})


def intent(f, confirmation=CONFIRM, control=CONTROL):
  return f["call"]("allocate_intent", {"control_id": control, "confirmation_ref": confirmation})


def allocated(f, tool="nested/tool:1", confirmation=CONFIRM, control=CONTROL):
  return f["call"]("allocate_request", {"control_id": control, "confirmation_ref": confirmation, "tool_call_id": tool})


def verified(f, binding, tool="nested/tool:1", confirmation=CONFIRM, control=CONTROL):
  return f["call"]("verify", {"control_id": control, "confirmation_ref": confirmation, "tool_call_id": tool, "request_ref": binding["request_ref"]})


def test_manager_private_route_durable_mapping_and_closed_projection(tmp_path):
  f=fixture(tmp_path); first=opened(f); refs=intent(f); binding=allocated(f)
  assert opened(f)==first and intent(f)==refs and allocated(f)==binding
  assert verified(f,binding)=={"current":True,**binding}
  assert f["store"].snapshot()["requests"]==1
  assert set(binding)=={"session_scope","intent_ref","request_ref"}
  row=json.loads(f["file"].read_text()); owner=f["host"].store.owner
  activation=digest({"domain":"reviewer-scope-session-v1","manager_activation_id":owner["manager_activation_id"],"lease_id":f["principal"].lease_id,"grant_generation":f["principal"].grant_generation,"control_id":CONTROL})[:32]
  nonce=digest({"domain":"reviewer-scope-intent-v1","activation_ref":activation,"confirmation_ref":CONFIRM})[:32]
  assert row["sessions"][activation]["session_scope"]==first["session_scope"]
  assert row["intents"][nonce]["intent_ref"]==refs["intent_ref"]
  assert owner["owner_nonce"] not in f["file"].read_text()


@pytest.mark.parametrize("role",["worker","delegate","user"])
def test_non_manager_zero_account_io(tmp_path,monkeypatch,role):
  f=fixture(tmp_path); monkeypatch.setattr(f["store"],"allocate_session",lambda _:pytest.fail("account read"))
  with pytest.raises(Conflict,match="MANAGER_REQUIRED"): f["call"]("open",{"control_id":CONTROL,"session_id":"session"},Principal(role))


@pytest.mark.parametrize("fault",["session","owner","generation","dead","unknown","kind"])
def test_original_live_owner_lease_and_sdk_session_cannot_drift(tmp_path,fault):
  f=fixture(tmp_path); opened(f)
  if fault=="session":
    with pytest.raises(Conflict,match="BINDING"): opened(f,session="different")
    return
  if fault=="owner": f["host"].store.owner["manager_activation_id"]="f"*32
  if fault=="generation": f["principal"]=Principal("manager",f["principal"].lease_id,f["principal"].grant_generation+1)
  if fault in ("dead","unknown"): f["host"].store.processes.current.clear()
  if fault=="kind":
    original=f["host"].store.read
    f["host"].store.read=lambda ident:{**original(ident),"kind":"external"}
  with pytest.raises(Conflict): f["call"]("allocate_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM},f["principal"])


@pytest.mark.parametrize("method",["open","allocate_intent","allocate_request","verify"])
def test_closing_rejects_new_work_but_allows_nonce_retirement(tmp_path,method):
  f=fixture(tmp_path); opened(f); intent(f); binding=allocated(f); f["host"].service.closing=True
  args={"control_id":CONTROL,"session_id":"sdk-session"} if method=="open" else {"control_id":CONTROL,"confirmation_ref":CONFIRM}
  if method in ("allocate_request","verify"): args["tool_call_id"]="nested/tool:1"
  if method=="verify": args["request_ref"]=binding["request_ref"]
  before=f["file"].read_bytes()
  with pytest.raises(Conflict): f["call"](method,args)
  assert f["file"].read_bytes()==before
  with pytest.raises(Conflict,match="CLOSING"): f["control"].handle(f["principal"],"ordinary_reviewer_scope_"+method,args)
  assert f["call"]("retire_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM})["state"]=="retired"
  assert f["call"]("retire_session",{"control_id":CONTROL,"session_id":"sdk-session"})["state"]=="retired"


@pytest.mark.parametrize("stage",["session","intent","request"])
def test_allocate_ack_loss_same_private_nonce_reconciles_no_new_mapping(tmp_path,monkeypatch,stage):
  f=fixture(tmp_path)
  if stage!="session": opened(f)
  if stage=="request": intent(f)
  name={"session":"allocate_session","intent":"allocate_intent","request":"allocate_request"}[stage]
  original=getattr(f["store"],name); raised=[False]
  def lost(*args):
    value=original(*args)
    if not raised[0]: raised[0]=True; raise RuntimeError("synthetic-private")
    return value
  monkeypatch.setattr(f["store"],name,lost)
  action={"session":opened,"intent":intent,"request":allocated}[stage]
  with pytest.raises(Conflict,match="CONTROL_UNAVAILABLE") as error: action(f)
  assert "synthetic-private" not in "".join(traceback.format_exception(error.value))
  counts=f["store"].snapshot(); result=action(f); assert action(f)==result
  assert f["store"].snapshot()==counts


@pytest.mark.parametrize("stage",["session","intent"])
def test_retire_before_allocation_blocks_late_opening(tmp_path,stage):
  f=fixture(tmp_path)
  if stage=="session":
    args={"control_id":CONTROL,"session_id":"sdk-session"}; name="retire_session"; action=opened
  else:
    opened(f); args={"control_id":CONTROL,"confirmation_ref":CONFIRM}; name="retire_intent"; action=intent
  assert f["call"](name,args)["state"]=="retired"
  assert f["call"](name,args)["state"]=="retired"
  before=f["file"].read_bytes()
  with pytest.raises(Conflict,match="RETIRED"): action(f)
  assert f["file"].read_bytes()==before


@pytest.mark.parametrize("stage",["session","intent"])
def test_unknown_allocation_ack_can_retire_original_nonce(tmp_path,monkeypatch,stage):
  f=fixture(tmp_path)
  if stage=="intent": opened(f)
  name="allocate_session" if stage=="session" else "allocate_intent"; original=getattr(f["store"],name)
  def lost(*args): original(*args); raise RuntimeError("private")
  monkeypatch.setattr(f["store"],name,lost)
  with pytest.raises(Conflict): (opened if stage=="session" else intent)(f)
  args={"control_id":CONTROL,**({"session_id":"sdk-session"} if stage=="session" else {"confirmation_ref":CONFIRM})}
  f["call"]("retire_"+stage,args)
  with pytest.raises(Conflict,match="RETIRED"): (opened if stage=="session" else intent)(f)


def test_cross_control_confirmation_and_tool_refs_never_borrow(tmp_path):
  f=fixture(tmp_path); opened(f); intent(f); a=allocated(f); opened(f,"4"*32,"other"); intent(f,control="4"*32); b=allocated(f,control="4"*32)
  assert a!=b
  with pytest.raises(Conflict,match="BINDING"): verified(f,a,control="4"*32)
  with pytest.raises(Conflict,match="BINDING"): verified(f,a,tool="different")
  with pytest.raises(Conflict): verified(f,a,confirmation="5"*32)


@pytest.mark.parametrize("fault",["expiry","update","missing"])
def test_actual_authority_live_check_before_allocate_and_verify(tmp_path,fault):
  f=fixture(tmp_path); opened(f); intent(f); binding=allocated(f); before=f["file"].read_bytes()
  if fault=="expiry": f["clock"][0]=10000
  if fault=="missing": (f["home"] / ".agentcfg-workspaces/reviewer-authority.json").unlink()
  if fault=="update":
    from test_pi_reviewer_account_authority import document
    value=document(); value["generation"]=2; value["limits"]["max_calls"]-=1
    f["authority"].update(value,expected_identity=f["authority_snapshot"]["identity"])
  with pytest.raises((Conflict,ConfigError)): allocated(f,tool="new")
  with pytest.raises((Conflict,ConfigError)): verified(f,binding)
  assert f["file"].read_bytes()==before
  assert f["call"]("retire_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM})["state"]=="retired"


@pytest.mark.parametrize("level",["control","intent","request"])
def test_capacities_do_not_evict_original_reserved_or_accepted_slots(tmp_path,level):
  f=fixture(tmp_path,**{"max_"+level+"s":1}); opened(f); intent(f); allocated(f); before=f["file"].read_bytes()
  with pytest.raises(Conflict,match="CAPACITY"):
    if level=="control": opened(f,"4"*32)
    elif level=="intent": intent(f,"4"*32)
    else: allocated(f,tool="new")
  assert f["file"].read_bytes()==before
  assert verified(f,allocated(f))["current"] is True


def test_shared_service_mutex_serializes_same_tool_into_one_persistent_request(tmp_path):
  f=fixture(tmp_path); opened(f); intent(f); barrier=Barrier(3)
  def work(): barrier.wait(); return allocated(f)
  with ThreadPoolExecutor(max_workers=2) as pool:
    a=pool.submit(work); b=pool.submit(work); barrier.wait(); assert a.result()==b.result()
  assert f["store"].snapshot()["requests"]==1


@pytest.mark.parametrize("fault",["method","extra","control-bool","unicode","space","refs"])
def test_closed_rpc_inputs_fail_before_account_lookup(tmp_path,monkeypatch,fault):
  f=fixture(tmp_path); monkeypatch.setattr(f["store"],"allocate_session",lambda _:pytest.fail("store called"))
  args={"control_id":CONTROL,"session_id":"sdk-session"}; method="open"
  if fault=="method": method="reset"
  if fault=="extra": args["source"]="human"
  if fault=="control-bool": args["control_id"]=True
  if fault=="unicode": args["session_id"]="中文"
  if fault=="space": args["session_id"]="session id"
  if fault=="refs": args["session_scope"]="4"*32
  with pytest.raises(ConfigError): f["call"](method,args)


def test_default_unavailable_route_has_zero_store_io(tmp_path):
  business=tmp_path / "business"; business.mkdir(); operations,host,_,principal=setup(business)
  assert operations.reviewer_scope_control is None
  host.service.ordinary_handler=operations.handle
  with pytest.raises(Conflict,match="UNAVAILABLE"): host.service.handle(principal,request("ordinary_reviewer_scope_open",{"control_id":CONTROL,"session_id":"session"}))
  with pytest.raises(ConfigError): operations.handle(principal,"ordinary_reviewer_scope_reset",{})


@pytest.mark.parametrize("stage",["session","intent"])
def test_retire_ack_loss_blocks_binding_and_same_nonce_cleanup_retry(tmp_path,monkeypatch,stage):
  f=fixture(tmp_path); opened(f); intent(f); allocated(f)
  method="retire_session_activation" if stage=="session" else "retire_intent_confirmation"
  original=getattr(f["store"],method); once=[False]; marker="SYNTHETIC_PRIVATE_STOP"
  def lost(*args):
    result=original(*args)
    if not once[0]: once[0]=True; raise RuntimeError(marker)
    return result
  monkeypatch.setattr(f["store"],method,lost)
  args={"control_id":CONTROL,**({"session_id":"sdk-session"} if stage=="session" else {"confirmation_ref":CONFIRM})}
  with pytest.raises(Conflict,match="CONTROL_UNAVAILABLE"): f["call"]("retire_"+stage,args)
  counts=f["store"].snapshot()
  with pytest.raises(Conflict,match="RETIRED"): allocated(f)
  assert f["call"]("retire_"+stage,args)["state"]=="retired"
  assert f["store"].snapshot()==counts


@pytest.mark.parametrize("stage",["control","intent","request"])
def test_failed_store_call_still_occupies_bounded_slot(tmp_path,monkeypatch,stage):
  f=fixture(tmp_path,**{"max_"+stage+"s":1})
  if stage!="control": opened(f)
  if stage=="request": intent(f)
  method={"control":"allocate_session","intent":"allocate_intent","request":"allocate_request"}[stage]
  def fail(*args): raise RuntimeError("private")
  monkeypatch.setattr(f["store"],method,fail)
  with pytest.raises(Conflict,match="CONTROL_UNAVAILABLE"): {"control":opened,"intent":intent,"request":allocated}[stage](f)
  with pytest.raises(Conflict,match="CAPACITY"):
    if stage=="control": opened(f,"4"*32)
    elif stage=="intent": intent(f,"4"*32)
    else: allocated(f,tool="new")


@pytest.mark.parametrize("change",["closing","dead"])
def test_late_session_allocation_cannot_return_capability_after_host_invalidated(tmp_path,monkeypatch,change):
  f=fixture(tmp_path); original=f["store"].allocate_session
  def allocate(nonce):
    result=original(nonce)
    if change=="closing": f["host"].service.closing=True
    else: f["host"].store.processes.current.clear()
    return result
  monkeypatch.setattr(f["store"],"allocate_session",allocate)
  with pytest.raises(Conflict): opened(f)
  assert f["control"]._controls[CONTROL]["state"]=="reserved"
  assert f["store"].snapshot()["sessions"]==1


def test_retired_control_cannot_create_unknown_intent_cleanup_slot(tmp_path):
  f=fixture(tmp_path); opened(f); intent(f)
  f["call"]("retire_session",{"control_id":CONTROL,"session_id":"sdk-session"})
  before=f["file"].read_bytes()
  with pytest.raises(Conflict,match="UNKNOWN"): f["call"]("retire_intent",{"control_id":CONTROL,"confirmation_ref":"5"*32})
  assert f["file"].read_bytes()==before
  assert f["call"]("retire_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM})["state"]=="retired"


def test_different_activation_does_not_reuse_previous_control_refs(tmp_path):
  f=fixture(tmp_path); old=opened(f); intent(f); old_request=allocated(f)
  business=tmp_path / "new-business"; business.mkdir()
  operations,host,_,principal=setup(business)
  control=ReviewerScopeControl(host,f["store"]); operations.reviewer_scope_control=control; host.service.ordinary_handler=operations.handle
  opened_new=host.service.handle(principal,request("ordinary_reviewer_scope_open",{"control_id":CONTROL,"session_id":"sdk-session"}))
  assert opened_new["session_scope"]!=old["session_scope"]
  host.service.handle(principal,request("ordinary_reviewer_scope_allocate_intent",{"control_id":CONTROL,"confirmation_ref":CONFIRM}))
  with pytest.raises(Conflict,match="BINDING"):
    host.service.handle(principal,request("ordinary_reviewer_scope_verify",{"control_id":CONTROL,"confirmation_ref":CONFIRM,"tool_call_id":"nested/tool:1","request_ref":old_request["request_ref"]}))
