"""纯登记记录，不涉及账户索引、进程或存储 IO。"""

from dataclasses import FrozenInstanceError, replace
import json
import traceback

import pytest

from agentcfg import pi_durable_registration_record as codec
from agentcfg.pi_durable_owner_record import StorageIdentity
from agentcfg.storage import Conflict


SECRET = "SYNTHETIC_PRIVATE_SOURCE"


def wire(stage="reserved"):
  return {"schema":1,"platform":"linux","service_id":"a"*64,"stage":stage,
    "account_home":"/synthetic/账户","account_identity":{"device":0,"inode":1,"uid":1000},
    "index_identity":{"device":2,"inode":3,"uid":1000},
    "initial_binding":{"machine":"fixture-machine","local":"/synthetic/local.toml","profile":"pi-full"},
    "initial_instance":"/synthetic/instance","initial_state_root":"/synthetic/state",
    "storage_path":"/synthetic/state/durable/storage","storage_identity":None if stage=="reserved" else {"device":0,"inode":1},
    "initial_deployment_identity":"b"*64}


def invalid(action):
  try: raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Conflict) as caught: action()
  error=caught.value
  assert type(error) is Conflict and error.args==("Durable服务登记无效",)
  assert error.__context__ is None and error.__cause__ is None
  assert SECRET not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize("stage",["reserved","registered"])
def test_whole_canonical_roundtrip_independent_frozen(stage):
  value=wire(stage);record=codec.capture_service_registration(value)
  encoded=codec.encode_service_registration(record)
  assert encoded==(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode()
  assert codec.decode_service_registration(encoded)==record
  assert record.writer_lock_verified is False and record.database_allowed is False and record.can_take_over is False
  assert not any(flag.encode() in encoded for flag in ["writer_lock_verified","database_allowed","can_take_over"])
  value["account_identity"]["device"]=99;value["initial_binding"]["machine"]="changed"
  if stage=="registered": value["storage_identity"]["inode"]=88
  assert record.account_identity.device==0 and record.initial_binding.machine=="fixture-machine"
  if stage=="registered": assert type(record.storage_identity) is StorageIdentity and record.storage_identity.inode==1
  for target,name in [(record,"stage"),(record.account_identity,"device"),(record.index_identity,"uid"),(record.initial_binding,"profile")]:
    assert not hasattr(target,"__dict__")
    with pytest.raises(FrozenInstanceError):setattr(target,name,None)


@pytest.mark.parametrize("field,value",[("schema",True),("schema",2),("platform","darwin"),("service_id","A"*64),("service_id","a"*63),("stage","ready"),("storage_path","/other/storage"),("initial_deployment_identity","g"*64),("extra",SECRET)])
def test_top_field_controls(field,value):
  data=wire();data[field]=value
  invalid(lambda:codec.capture_service_registration(data))


@pytest.mark.parametrize("field",list(wire()))
def test_each_required_field(field):
  data=wire();del data[field]
  invalid(lambda:codec.capture_service_registration(data))


@pytest.mark.parametrize("identity",["account_identity","index_identity","storage_identity"])
@pytest.mark.parametrize("field,value",[("device",True),("device",-1),("device",2**64),("inode",0),("inode",2**64)])
def test_identity_numeric_limits(identity,field,value):
  data=wire("registered");data[identity][field]=value
  invalid(lambda:codec.capture_service_registration(data))


@pytest.mark.parametrize("value",[True,-1,2**32-1,1.0,"1000"])
def test_uid_limits(value):
  data=wire();data["account_identity"]["uid"]=value
  invalid(lambda:codec.capture_service_registration(data))


def test_identity_extremes_and_uid_crossmatch():
  data=wire("registered")
  for name in ["account_identity","index_identity"]:data[name]={"device":2**64-1,"inode":2**64-1,"uid":2**32-2}
  data["storage_identity"]={"device":2**64-1,"inode":2**64-1}
  record=codec.capture_service_registration(data);assert codec.decode_service_registration(codec.encode_service_registration(record))==record
  data["index_identity"]["uid"]=0;invalid(lambda:codec.capture_service_registration(data))


@pytest.mark.parametrize("stage,storage",[("reserved",{"device":0,"inode":1}),("registered",None),("registered",{"device":0,"inode":1,"uid":1000})])
def test_stage_storage_relationship(stage,storage):
  data=wire(stage);data["storage_identity"]=storage
  invalid(lambda:codec.capture_service_registration(data))


@pytest.mark.parametrize("field,value",[("machine","Upper"),("machine","a"*65),("machine",True),("profile","pi-base"),("profile",None),("unknown","x")])
def test_initial_binding_closed(field,value):
  data=wire();data["initial_binding"][field]=value
  invalid(lambda:codec.capture_service_registration(data))


@pytest.mark.parametrize("path",["/","relative","//root/a","/a/","/a//b","/a/./b","/a/../b","/a\\b","/a\x00b","/a\x1fb","/a\x7fb","/a\x9fb","/a\ud800b","/"+"a"*4096,True])
def test_lexical_path_domain_without_normalization(path):
  data=wire();data["account_home"]=path
  invalid(lambda:codec.capture_service_registration(data))


def test_utf8_path_capacity_and_lexical_alias_not_io():
  data=wire();data["account_home"]="/"+"a"*4095
  assert codec.capture_service_registration(data).account_home==data["account_home"]
  data["account_home"]="/"+"界"*1366
  invalid(lambda:codec.capture_service_registration(data))
  data=wire();data["initial_state_root"]="/alias";data["storage_path"]="/alias/durable/storage"
  assert codec.capture_service_registration(data).storage_path==data["storage_path"]


@pytest.mark.parametrize("raw",[b"",b"\xff",b"\xef\xbb\xbf{}",b'{"schema":1,"schema":1}',b'{"schema":1,"\\u0073chema":1}',b'{"x":{"a":1,"a":2}}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":-Infinity}',b'{"x":1e999}',b"["*2000+b"0"+b"]"*2000,b" "*32769,bytearray(b"{}"),"{}"])
def test_decoder_native_utf8_json_and_capacity(raw):
  invalid(lambda:codec.decode_service_registration(raw))


def test_decoder_whitespace_key_order_and_exact_limit():
  data=wire();raw=json.dumps(dict(reversed(list(data.items()))),ensure_ascii=False).encode()
  assert codec.decode_service_registration(raw)==codec.capture_service_registration(data)
  padded=raw+b" "*(32768-len(raw));assert codec.decode_service_registration(padded)==codec.capture_service_registration(data)
  invalid(lambda:codec.decode_service_registration(padded+b" "))


def test_type_first_hooks_zero():
  calls=[];armed=False
  class String(str):
    def __hash__(self):
      if armed:calls.append("hash");raise AssertionError()
      return str.__hash__(self)
    def __eq__(self,other):calls.append("eq");raise AssertionError()
  class Number(int):
    def __le__(self,other):calls.append("le");raise AssertionError()
  class Dict(dict):
    def items(self):calls.append("items");raise AssertionError()
  class Foreign:
    def __getattribute__(self,name):calls.append("attribute");raise AssertionError()
  value={String("schema"):1};armed=True
  invalid(lambda:codec.capture_service_registration(value))
  invalid(lambda:codec.capture_service_registration(Dict()))
  value=wire();value["service_id"]=String("a"*64);invalid(lambda:codec.capture_service_registration(value))
  value=wire();value["account_identity"]["device"]=Number(1);invalid(lambda:codec.capture_service_registration(value))
  invalid(lambda:codec.encode_service_registration(Foreign()))
  assert calls==[]


@pytest.mark.parametrize("field",["account_identity","index_identity","initial_binding","storage_identity"])
def test_foreign_nested_type_before_slots(field):
  calls=[]
  class Foreign:
    def __getattribute__(self,name):calls.append(name);raise AssertionError()
  record=codec.capture_service_registration(wire("registered"));record=replace(record,**{field:Foreign()})
  invalid(lambda:codec.encode_service_registration(record));assert calls==[]


@pytest.mark.parametrize("field",[None,"account_identity","index_identity","initial_binding","storage_identity"])
def test_uninitialized_record_or_nested_fixed_error(field):
  if field is None:record=object.__new__(codec.ServiceRegistration)
  else:
    cls=StorageIdentity if field=="storage_identity" else codec.InitialBinding if field=="initial_binding" else codec.DirectoryIdentity
    record=replace(codec.capture_service_registration(wire("registered")),**{field:object.__new__(cls)})
  invalid(lambda:codec.encode_service_registration(record))


def test_encoder_constructor_forgery_and_revalidation():
  record=codec.capture_service_registration(wire());invalid(lambda:codec.encode_service_registration(replace(record,schema=True)))
  class Child(codec.ServiceRegistration):pass
  invalid(lambda:codec.encode_service_registration(Child(**{name:getattr(record,name) for name in wire()})))
  object.__setattr__(record,"initial_deployment_identity",SECRET)
  invalid(lambda:codec.encode_service_registration(record))


def test_encoder_total_capacity_rechecks_without_asdict():
  data=wire();path="/"+'"'*4079
  for name in ["account_home","initial_instance","initial_state_root"]:data[name]=path
  data["initial_binding"]["local"]=path;data["storage_path"]=path+"/durable/storage"
  record=codec.capture_service_registration(data)
  invalid(lambda:codec.encode_service_registration(record))
