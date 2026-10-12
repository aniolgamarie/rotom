"""真实File/Shell桥共享原Admission；默认仅临时树和假后端/假进程。"""
from copy import deepcopy

import pytest

from agentcfg.pi_admitted_files import FileOperationAdmissions
from agentcfg.pi_admitted_shell import ShellOperationAdmissions
from agentcfg.pi_admission_control import FileAdmissionControl
from agentcfg.pi_operation_admission import OperationAdmissions, encode_private_input
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_admitted_shell import fixture as shell_fixture


def fixture(tmp_path, *, max_operations=4096, max_private_bytes=32*1024*1024):
  f=shell_fixture(tmp_path)
  _,operations,host,principal,current,observations,proof=f
  shared=OperationAdmissions(host.store.owner["manager_activation_id"],now_ms=lambda:int(operations.now().timestamp()*1000),
    max_operations=max_operations,max_private_bytes=max_private_bytes)
  kwargs={"admissions":shared}
  shell=ShellOperationAdmissions(operations,context_provider=lambda _:deepcopy(current),binding_name="shell",
    backend_preflight=lambda _:deepcopy(proof),max_operations=max_operations,max_private_bytes=max_private_bytes,**kwargs)
  kwargs={"admissions":shared}
  files=FileOperationAdmissions(operations,context_provider=lambda _:deepcopy(current),**kwargs)
  return {"shell":shell,"files":files,"operations":operations,"host":host,"principal":principal,"current":current,"shared":shared,"proof":proof}


def test_real_bridges_borrow_one_admission_without_reset(tmp_path):
  f=fixture(tmp_path)
  assert f["files"].ledger is f["shell"].ledger is f["shared"]


def prepare(f, kind, request="request", body=None):
  if kind=="file":return f["files"].prepare(f["principal"],request,"write",body or {"path":"new.txt","content":"private-shared-body"})
  return f["shell"].prepare(f["principal"],request,"bash",body or {"command":"printf shared"})


def issue(f, kind, prepared):
  return f["files" if kind=="file" else "shell"].issue(f["principal"],prepared["operation_id"],operation_digest=prepared["operation_digest"],source="human")


@pytest.mark.parametrize("first",["file","shell"])
def test_same_session_request_cannot_cross_kind(tmp_path,first):
  f=fixture(tmp_path);p=prepare(f,first)
  with pytest.raises(Conflict,match="OPERATION_IDEMPOTENCY_CONFLICT"):prepare(f,"shell" if first=="file" else "file")
  assert f["shared"].prepared(p["operation_id"])==p
  assert len(f["shared"]._operations)==1
  assert not [r for r in f["host"].store.records() if r["kind"]=="external"]


@pytest.mark.parametrize("kind",["file","shell"])
def test_same_kind_request_cannot_change_captured_input(tmp_path,kind):
  f=fixture(tmp_path);p=prepare(f,kind)
  body={"path":"new.txt","content":"changed"} if kind=="file" else {"command":"printf changed"}
  with pytest.raises(Conflict,match="OPERATION_IDEMPOTENCY_CONFLICT"):prepare(f,kind,body=body)
  assert f["shared"].prepared(p["operation_id"])==p
  assert len(f["shared"]._operations)==1


@pytest.mark.parametrize("first",["file","shell"])
def test_operation_capacity_is_global_between_real_bridges(tmp_path,first):
  f=fixture(tmp_path,max_operations=1);prepare(f,first,"first")
  with pytest.raises(Conflict,match="OPERATION_CAPACITY"):prepare(f,"shell" if first=="file" else "file","second")
  assert len(f["shared"]._operations)==1
  assert not [r for r in f["host"].store.records() if r["kind"]=="external"]


@pytest.mark.parametrize("first",["file","shell"])
def test_private_byte_budget_is_sum_of_both_bridge_inputs(tmp_path,first):
  file_body={"path":"new.txt","content":"x"*30};shell_body={"command":"printf '"+"x"*30+"'"}
  file_size=len(encode_private_input({"tool_name":"write","input":file_body}))
  shell_size=len(encode_private_input(shell_body));limit=file_size+shell_size-1
  f=fixture(tmp_path,max_private_bytes=limit)
  prepare(f,first,"first",file_body if first=="file" else shell_body)
  with pytest.raises(Conflict,match="OPERATION_CAPACITY"):prepare(f,"shell" if first=="file" else "file","second",shell_body if first=="file" else file_body)
  assert f["shared"]._private_bytes== (file_size if first=="file" else shell_size)
  assert len(f["shared"]._operations)==1


@pytest.mark.parametrize("issuer",["file","shell"])
def test_permit_cannot_cross_bridge_and_original_consumes_once(tmp_path,issuer):
  f=fixture(tmp_path);p=prepare(f,issuer);permit=issue(f,issuer,p)
  bridge=f["files" if issuer=="file" else "shell"]
  other=f["shell" if issuer=="file" else "files"]
  with pytest.raises(Conflict,match="OPERATION_PERMIT_UNKNOWN"):other.consume(f["principal"],permit)
  ticket=bridge.consume(f["principal"],permit)
  assert ticket["state"]=="consumed"
  with pytest.raises(Conflict):bridge.consume(f["principal"],permit)
  assert f["shared"].status(p["operation_id"])["state"]=="consumed"
  assert len([r for r in f["host"].store.records() if r["kind"]=="external"])==1


@pytest.mark.parametrize("issuer",["file","shell"])
def test_wrong_source_or_operation_identity_burns_original_global_permit(tmp_path,issuer):
  f=fixture(tmp_path);p=prepare(f,issuer);permit=issue(f,issuer,p)
  forged=deepcopy(permit);forged["source"]="deterministic-policy";forged["operation_id"]="f"*32
  bridge=f["files" if issuer=="file" else "shell"]
  with pytest.raises(Conflict):bridge.consume(f["principal"],forged)
  with pytest.raises(Conflict):bridge.consume(f["principal"],permit)
  assert f["shared"].status(p["operation_id"])["state"]=="revoked"
  assert not [r for r in f["host"].store.records() if r["kind"]=="external"]


@pytest.mark.parametrize("bridge",["file","shell","control"])
@pytest.mark.parametrize("bad",["activation","subclass","object","bool"])
def test_shared_injection_rejects_foreign_activation_or_nonexact_type(tmp_path,bridge,bad):
  raw=shell_fixture(tmp_path);operations,host=raw[1:3]
  if bad=="activation":shared=OperationAdmissions("different")
  elif bad=="subclass":
    class Sub(OperationAdmissions):pass
    shared=Sub(host.store.owner["manager_activation_id"])
  elif bad=="object":shared=object()
  else:shared=True
  with pytest.raises(ConfigError) as caught:
    if bridge=="file":FileOperationAdmissions(operations,context_provider=lambda _:raw[4],admissions=shared)
    elif bridge=="shell":ShellOperationAdmissions(operations,context_provider=lambda _:raw[4],binding_name="shell",admissions=shared)
    else:FileAdmissionControl(operations,shared_admissions=shared)
  assert caught.value.code=="pi-operation-shared-admissions"
  assert operations.admission is None


@pytest.mark.parametrize("field,value",[("max_operations",2),("max_private_bytes",2048),("max_operations",True),("max_private_bytes",True)])
def test_shell_shared_explicit_limits_must_match_exactly(tmp_path,field,value):
  raw=shell_fixture(tmp_path);operations,host=raw[1:3]
  shared=OperationAdmissions(host.store.owner["manager_activation_id"],max_operations=1,max_private_bytes=1024)
  kwargs={"max_operations":1,"max_private_bytes":1024};kwargs[field]=value
  with pytest.raises(ConfigError) as caught:
    ShellOperationAdmissions(operations,context_provider=lambda _:raw[4],binding_name="shell",admissions=shared,**kwargs)
  assert caught.value.code=="pi-operation-shared-admissions"


def control_fixture(tmp_path, *, factory_kind="shared", shared_enabled=True):
  raw=shell_fixture(tmp_path);_,operations,host,principal,current,_,proof=raw
  shared=OperationAdmissions(host.store.owner["manager_activation_id"],now_ms=lambda:int(operations.now().timestamp()*1000))
  seen=[]
  def factory(operations,**kwargs):
    seen.append(kwargs)
    if factory_kind=="none":return None
    if factory_kind=="unrelated":return object()
    if factory_kind=="getter":
      class Bad:
        @property
        def ledger(self):raise RuntimeError("SYNTHETIC_PRIVATE")
      return Bad()
    if factory_kind=="fallback":kwargs.pop("admissions",None)
    return ShellOperationAdmissions(operations,binding_name="shell",backend_preflight=lambda _:deepcopy(proof),**kwargs)
  control=FileAdmissionControl(operations,shell_bridge_factory=factory,shared_admissions=shared if shared_enabled else None)
  def call(name,args):return control.handle(principal,"ordinary_admission_"+name,args)
  call("open",{"control_id":"control","session_id":current["session_id"]})
  return control,shared,seen,current,call,host


def test_control_passes_exact_same_shared_object_to_both_real_bridges(tmp_path):
  control,shared,seen,current,call,_=control_fixture(tmp_path)
  assert control.bridge.ledger is control.shell_bridge.ledger is shared
  assert set(seen[0])=={"context_provider","admissions"} and seen[0]["admissions"] is shared
  for request,tool,body in [("file-call","write",{"path":"new.txt","content":"file body"}),("shell-call","bash",{"command":"printf body"})]:
    p=call("prepare",{"control_id":"control","request_id":request,"context":current,"tool_name":tool,"input":body})
    assert p["resolution"]["policy"]["requires_human"] is True
    assert p["operation_id"] in shared._operations
  assert len(shared._operations)==2


@pytest.mark.parametrize("kind",["fallback","none","unrelated","getter"])
def test_shared_factory_cannot_silently_return_another_ledger(tmp_path,kind):
  with pytest.raises(ConfigError) as caught:control_fixture(tmp_path,factory_kind=kind)
  assert caught.value.code=="pi-admission-shared-admissions"
  assert "SYNTHETIC_PRIVATE" not in str(caught.value)


def test_default_none_preserves_old_factory_signature_and_separate_ledgers(tmp_path):
  control,_,seen,_,_,_=control_fixture(tmp_path,shared_enabled=False)
  assert set(seen[0])=={"context_provider"}
  assert control.bridge.ledger is not control.shell_bridge.ledger


def test_shared_file_only_control_and_existing_ledger_records_not_reset(tmp_path):
  raw=shell_fixture(tmp_path);_,ops,host,principal,current,_,_=raw
  shared=OperationAdmissions(host.store.owner["manager_activation_id"],now_ms=lambda:int(ops.now().timestamp()*1000))
  file_only=FileAdmissionControl(ops,shared_admissions=shared)
  assert file_only.bridge.ledger is shared and file_only.shell_bridge is None
  p=raw[0].prepare(principal,"existing","bash",{"command":"printf original"})
  # 明确预先已存在的内存墓碑属于共享core，注入不能清零或改变其原字段。
  original=shared.prepare("existing",current=p["context"],resolved=p["resolution"],private_input={"command":"printf original"})
  shared.revoke(original["operation_id"])
  shell=ShellOperationAdmissions(ops,context_provider=lambda _:deepcopy(current),binding_name="shell",admissions=shared)
  assert shell.ledger.status(original["operation_id"])["state"]=="revoked"
  assert len(shared._operations)==1


@pytest.mark.parametrize("kind",["file","shell"])
def test_business_admissions_field_cannot_install_shared_capability(tmp_path,kind):
  f=fixture(tmp_path)
  body={"path":"new.txt","content":"body","admissions":"trusted"} if kind=="file" else {"command":"printf body","admissions":"trusted"}
  with pytest.raises(ConfigError):prepare(f,kind,body=body)
  assert len(f["shared"]._operations)==0


def test_rpc_shared_admissions_extra_is_rejected_not_configured(tmp_path):
  control,shared,_,current,call,_=control_fixture(tmp_path)
  with pytest.raises(ConfigError):call("prepare",{"control_id":"control","request_id":"request","context":current,"tool_name":"bash","input":{"command":"printf x"},"shared_admissions":True})
  assert len(shared._operations)==0


@pytest.mark.parametrize("kind",["throw","legacy-signature"])
def test_shared_factory_call_failure_is_fixed_without_raw_chain(tmp_path,kind):
  import traceback
  raw=shell_fixture(tmp_path);operations,host=raw[1:3]
  shared=OperationAdmissions(host.store.owner["manager_activation_id"])
  marker="SYNTHETIC_PRIVATE_FACTORY"
  if kind=="throw":
    def factory(operations,**kwargs):raise RuntimeError(marker)
  else:
    def factory(operations,*,context_provider):pytest.fail("must not call incompatible factory")
  with pytest.raises(ConfigError) as caught:
    FileAdmissionControl(operations,shared_admissions=shared,shell_bridge_factory=factory)
  assert caught.value.code=="pi-admission-shared-admissions"
  assert marker not in "".join(traceback.format_exception(caught.value))
