"""B4只读物理观察：真实原Full安装、原offline guard、自有临时树及时清理。"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace

import pytest

from agentcfg import pi_runtime_packages as packages
from agentcfg.deployment import json_bytes
from agentcfg.paths import PathError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_owner_origin import _install, _context


CALLBACKS = []


def module():
  return importlib.import_module("agentcfg.pi_installed_source")


@pytest.fixture(autouse=True)
def callbacks():
  CALLBACKS.clear()
  yield
  assert CALLBACKS == []


@pytest.fixture
def full(monkeypatch):
  with tempfile.TemporaryDirectory(prefix="pi-installed-source-case-",dir="/tmp") as temporary:
    workspace, lock, root, result, rest = _install(Path(temporary), monkeypatch)
    yield root, deepcopy(lock.metadata["profile_slices"]["pi-full"]), _context(root)


def capture(full):
  root,piece,context=full
  return module().capture_installed_full_source(str(root),piece,**context)


def reject(function,*args,**kwargs):
  try:raise RuntimeError("PRIVATE_ERROR_SENTINEL")
  except RuntimeError:
    with pytest.raises(ValueError) as caught:function(*args,**kwargs)
  assert type(caught.value) is ValueError and caught.value.args == ("pi-installed-source",)
  assert caught.value.__cause__ is None and caught.value.__context__ is None


def physical(path,directory=False):
  info=path.stat(follow_symlinks=False)
  row={"device":str(info.st_dev),"inode":str(info.st_ino),"uid":str(info.st_uid),"mode":str(info.st_mode)}
  if not directory:row.update(size=str(info.st_size),mtime_ns=str(info.st_mtime_ns),ctime_ns=str(info.st_ctime_ns),nlink=str(info.st_nlink))
  return row


def test_real_full_complete_actual_tree_and_markers_detached_no_content(full):
  root,piece,context=full;result=capture(full);receipt=json.loads((root/".agentcfg-receipt.json").read_bytes())
  assert receipt["schema_version"]==2 and packages.status(root,context["identity"])=="installed"
  assert set(result)=={"schema_version","profile","lock_identity","runtime_identity","root","markers","entries"}
  assert result["schema_version"]==1 and result["profile"]=="pi-full" and result["root"]==physical(root,True)
  assert set(result["entries"])==set(receipt["files"])
  assert {row["kind"] for row in result["entries"].values()}=={"file","directory","link"}
  for name,row in result["entries"].items():
    path=root/name;kind=row["kind"];assert row["physical"]==physical(path,kind=="directory")
    if kind=="file":assert row["sha256"]==hashlib.sha256(path.read_bytes()).hexdigest()==receipt["files"][name]["sha256"]
    elif kind=="link":assert row["target"]==os.readlink(path)==receipt["files"][name]["target"]
  for slot,name in (("ready",".agentcfg-ready"),("receipt",".agentcfg-receipt.json")):
    assert result["markers"][slot]=={"physical":physical(root/name),"sha256":hashlib.sha256((root/name).read_bytes()).hexdigest()}
  raw=json_bytes(result)
  assert b"synthetic fixed role" not in raw and b"PRIVATE_ERROR_SENTINEL" not in raw and str(root).encode() not in raw
  result["entries"].clear();assert capture(full)["entries"]


@pytest.mark.parametrize("fault",["Path","pathlike","subclass","relative","root","double-root","triple-root","dot-root","parent","nul","long-char","long-byte","surrogate","piece-subclass","key","cycle","unknown","owner-missing","engine-bool","bad-piece-digest","bad-binding","alias-budget"])
def test_input_rejects_before_tree_and_optional_owner(full,monkeypatch,fault):
  root,piece,context=full;root=str(root);api=module();calls=[]
  class Key(str):
    def __hash__(self):return str.__hash__(self)
    def __eq__(self,other):CALLBACKS.append("eq");raise AssertionError()
  class Dict(dict):
    def items(self):CALLBACKS.append("items");raise AssertionError()
  class PathLike:
    def __fspath__(self):CALLBACKS.append("fspath");raise AssertionError()
  if fault=="Path":root=Path(root)
  elif fault=="pathlike":root=PathLike()
  elif fault=="subclass":root=Key(root)
  elif fault=="relative":root="tmp/root"
  elif fault=="root":root="/"
  elif fault=="double-root":root="//"
  elif fault=="triple-root":root="///"
  elif fault=="dot-root":root="/./"
  elif fault=="parent":root="/tmp/../x"
  elif fault=="nul":root="/tmp/\x00"
  elif fault=="long-char":root="/"+"a"*4096
  elif fault=="long-byte":root="/"+"é"*2048
  elif fault=="surrogate":root="/tmp/\ud800"
  elif fault=="piece-subclass":piece=Dict(piece)
  elif fault=="key":piece={Key("engine"):"node"}
  elif fault=="cycle":piece["cycle"]=piece
  elif fault=="unknown":piece["approved"]=True
  elif fault=="owner-missing":piece.pop("durable_owner")
  elif fault=="engine-bool":piece["engine"]=True
  elif fault=="bad-piece-digest":piece["identity"]="a"*64
  elif fault=="bad-binding":context["binding_identity"]["slice"]="a"*64
  else:piece["alias"]=[[[0]*1000]*1000]
  class Forbidden:
    def __init__(self,*args,**kwargs):calls.append("Tree");raise AssertionError()
  monkeypatch.setattr(api,"Tree",Forbidden)
  reject(api.capture_installed_full_source,root,piece,**context)
  assert calls==[]


def test_owned_alias_and_late_caller_mutation_use_first_capture(full,monkeypatch):
  root,piece,context=full;api=module();original=api.Tree
  # 合法值别名保持；不是新增字段、循环或超预算展开。
  empty=[]
  for kind in ("skills","prompts","themes"):
    assert piece["resource_manifest"][kind]==[]
    piece["resource_manifest"][kind]=empty
  old=deepcopy(piece);events=[]
  class Key(str):
    def __hash__(self):return str.__hash__(self)
    def __eq__(self,other):CALLBACKS.append("eq");raise AssertionError()
  def opening(path,*args,**kwargs):
    if not events:
      piece.clear();piece[Key("engine")]=True
      context["toolchains"].clear();context["toolchains"][Key("node")]=False
      context["binding_identity"].clear();context["binding_identity"][Key("runtime")]=True
    events.append(True);return original(path,*args,**kwargs)
  monkeypatch.setattr(api,"Tree",opening)
  assert api.capture_installed_full_source(str(root),piece,**context)["entries"]
  assert events==[True,True] and old["engine"]=="node"


@pytest.mark.parametrize("target",["origin","receipt","ready","Node","license","pair","body","wheel","role","extra","missing","kind","hardlink","outside-link","link-target","mode"])
def test_actual_material_tree_marker_drift_refuses(full,target):
  root,piece,context=full
  paths={"origin":"runtime/durable-owner-origin.json","receipt":".agentcfg-receipt.json","ready":".agentcfg-ready","Node":"bin/pi-node","license":"licenses/owner-node/0-LICENSE","pair":piece["package_path"],"body":"runtime/durable-python-bundle.json","role":"runtime/durable-owner-bootstrap.mjs"}
  if target=="wheel":path=root/next(name for name,row in packages.inventory(root).items() if name.startswith("vendor/wheels/") and row["kind"]=="file")
  else:path=root/paths.get(target,"runtime/durable-owner-bootstrap.mjs")
  if target=="extra":(root/"runtime/extra").write_bytes(b"PRIVATE_SOURCE_SENTINEL")
  elif target=="missing":path.unlink()
  elif target=="kind":path.unlink();path.mkdir()
  elif target=="hardlink":os.link(path,root/"runtime/hardlink")
  elif target in ("outside-link","link-target"):
    link=next(root/name for name,row in packages.inventory(root).items() if row["kind"]=="link");link.unlink();link.symlink_to("/tmp" if target=="outside-link" else "missing")
  elif target=="mode":path.chmod(0o640)
  else:path.write_bytes(path.read_bytes()+b"drift")
  reject(module().capture_installed_full_source,str(root),piece,**context)


def test_old_ready_strip_legality_and_new_exact65_domain(full):
  root,piece,context=full;(root/".agentcfg-ready").write_bytes(b" \n"+context["identity"].encode()+b"\n\t")
  assert packages.status(root,context["identity"])=="installed"
  reject(module().capture_installed_full_source,str(root),piece,**context)


@pytest.mark.parametrize("error",[OSError("x"),ValueError("x"),KeyError("x"),TypeError("x"),Conflict("x"),PathError("x"),ConfigError("x")])
def test_status_after_inventory_equal_preserves_exact_catchtuple(full,monkeypatch,error):
  root,_,context=full
  def fail(*args,**kwargs):raise error
  monkeypatch.setattr(packages,"validate_installed",fail)
  assert packages.status(root,context["identity"])=="damaged"


@pytest.mark.parametrize("error",[RuntimeError("outside"),KeyboardInterrupt("outside"),SystemExit(7)])
def test_status_outside_catchtuple_original_object_propagates(full,monkeypatch,error):
  root,_,context=full
  def fail(*args,**kwargs):raise error
  monkeypatch.setattr(packages,"validate_installed",fail)
  with pytest.raises(type(error)) as caught:packages.status(root,context["identity"])
  assert caught.value is error


def test_status_malformed_receipt_and_shared_actual_raw(full):
  root,_,context=full;receipt,raw=packages._validated_receipt(root,context["identity"])
  assert receipt["schema_version"]==2 and raw==(root/".agentcfg-receipt.json").read_bytes()
  (root/".agentcfg-receipt.json").write_bytes(b'{')
  assert packages.status(root,context["identity"])=="damaged"


@pytest.mark.parametrize("kind",["file","directory","root","marker"])
def test_equal_byte_or_name_replacement_after_observation_rejects(full,monkeypatch,kind):
  root,piece,context=full;api=module();original=api._finish;events=[]
  def finishing(*args,**kwargs):
    if kind in ("file","marker"):
      path=root/(".agentcfg-ready" if kind=="marker" else "runtime/durable-owner-bootstrap.mjs");new=path.with_name("replaced");new.write_bytes(path.read_bytes());new.chmod(path.stat().st_mode&0o777);new.replace(path)
    elif kind=="directory":
      path=root/"runtime";saved=root/"runtime-old";path.rename(saved);shutil.copytree(saved,path)
    else:
      old=root.with_name(root.name+"-old");root.rename(old);shutil.copytree(old,root)
    events.append(True);return original(*args,**kwargs)
  monkeypatch.setattr(api,"_finish",finishing)
  reject(api.capture_installed_full_source,str(root),piece,**context);assert events==[True]


@pytest.mark.parametrize("name",["MAX_ENTRIES","MAX_FILE","MAX_TOTAL","MAX_RECEIPT","MAX_LINK","MAX_RESULT"])
def test_each_new_observation_cap_rejects_real_supported_tree_only(full,monkeypatch,name):
  api=module();monkeypatch.setattr(api,name,0 if name!="MAX_RESULT" else 1)
  reject(api.capture_installed_full_source,str(full[0]),full[1],**full[2])


@pytest.mark.parametrize("value",[None,True,1,1.0,"","00","01","-0","+1"," 1","1 ","1e2","18446744073709551616"])
def test_decimal_uint64_exact_string_domain(value):
  with pytest.raises(ValueError):module()._decimal(value,64)


def test_decimal_ranges_and_physical_full_type_slots():
  api=module();assert api._decimal("18446744073709551615",64)=="18446744073709551615"
  assert api._decimal("-9223372036854775808",64,signed=True)=="-9223372036854775808"
  for value in ("-9223372036854775809","9223372036854775808"):
    with pytest.raises(ValueError):api._decimal(value,64,signed=True)


@pytest.mark.parametrize("control",[KeyboardInterrupt("x"),SystemExit(7),GeneratorExit("x")])
def test_new_boundary_original_controls_and_ordinary_error_chain(control):
  api=module()
  def raising():raise control
  with pytest.raises(type(control)) as caught:api._boundary(raising)
  assert caught.value is control
  reject(api._boundary,lambda:(_ for _ in ()).throw(RuntimeError("PRIVATE")))


@pytest.mark.parametrize("name",["MAX_ENTRIES","MAX_FILE","MAX_TOTAL","MAX_RECEIPT","MAX_LINK","MAX_RESULT"])
def test_scaled_measured_cap_exact_boundary_pass_and_one_less_fails(full,monkeypatch,name):
  api=module();result=capture(full);root,piece,context=full
  values={"MAX_ENTRIES":len(result["entries"]),"MAX_FILE":max(int(row["physical"]["size"]) for row in result["entries"].values() if row["kind"]=="file"),
    "MAX_TOTAL":sum(int(row["physical"]["size"]) for row in result["entries"].values() if row["kind"]=="file"),
    "MAX_RECEIPT":len((root/".agentcfg-receipt.json").read_bytes()),
    "MAX_LINK":max(len(row["target"].encode()) for row in result["entries"].values() if row["kind"]=="link"),"MAX_RESULT":len(json_bytes(result))}
  # 真实小型sealed树的scaled limits，不声称65536/2GiB满界已执行。
  limit=values[name];assert limit>0;monkeypatch.setattr(api,name,limit)
  assert capture(full)==result
  monkeypatch.setattr(api,name,limit-1)
  reject(api.capture_installed_full_source,str(root),piece,**context)


@pytest.mark.parametrize("fault",["nlink","size","content"])
def test_actual_new_regular_read_phase_mutation_is_detected(full,monkeypatch,fault):
  api=module();root,piece,context=full;target="runtime/durable-owner-bootstrap.mjs";original_scan=api._scan;original_open=Tree.open_read;phase=[];changed=[]
  def scanning(*args,**kwargs):
    phase.append(True)
    return original_scan(*args,**kwargs)
  @contextmanager
  def opening(tree,path,**kwargs):
    with original_open(tree,path,**kwargs) as (stream,opened):
      if not phase or path!=target:yield stream,opened
      else:
        class Stream:
          def fileno(self):return stream.fileno()
          def read(self,count):
            if not changed:
              if fault=="nlink":os.link(root/path,root.parent/"outside-sealed-hardlink")
              elif fault=="size":(root/path).write_bytes((root/path).read_bytes()+b"changed length")
              else:(root/path).write_bytes((root/path).read_bytes()[::-1])
              changed.append(True)
            return stream.read(count)
        yield Stream(),opened
  monkeypatch.setattr(api,"_scan",scanning);monkeypatch.setattr(Tree,"open_read",opening)
  reject(api.capture_installed_full_source,str(root),piece,**context)
  assert phase==[True] and changed==[True]


def test_complete_shape_exact_keys_native_scalar_and_physical_types(full):
  value=capture(full);assert set(value["markers"])=={"receipt","ready"}
  assert type(value["schema_version"]) is int
  for key in ("profile","lock_identity","runtime_identity"):assert type(value[key]) is str
  for row in value["markers"].values():assert set(row)=={"physical","sha256"}
  for name,row in value["entries"].items():
    assert type(name) is str and type(row) is dict
    expected={"kind","physical"}|({"sha256"} if row["kind"]=="file" else {"target"} if row["kind"]=="link" else set())
    assert set(row)==expected and type(row["kind"]) is str
    fields={"device","inode","uid","mode"}|(set() if row["kind"]=="directory" else {"size","mtime_ns","ctime_ns","nlink"})
    assert set(row["physical"])==fields and all(type(k) is str and type(v) is str for k,v in row["physical"].items())


def test_missing_owner_fails_before_optional_import_or_material_schema_io(full,monkeypatch):
  import builtins
  root,piece,context=full;piece.pop("durable_owner");api=module();imports=[];io=[];original=builtins.__import__;original_read=Tree.read
  def importing(name,*args,**kwargs):
    if name.rsplit(".",1)[-1] in ("pi_owner_origin","pi_modern_launcher"):imports.append(name)
    return original(name,*args,**kwargs)
  def read(*args,**kwargs):io.append(True);return original_read(*args,**kwargs)
  monkeypatch.setattr(builtins,"__import__",importing);monkeypatch.setattr(Tree,"read",read)
  reject(api.capture_installed_full_source,str(root),piece,**context)
  assert imports==io==[]


@pytest.mark.parametrize("marker",[False,True])
def test_synthetic_scandir_replay_duplicate_is_rejected_before_overwrite(tmp_path,monkeypatch,marker):
  api=module();root=tmp_path/"directory";root.mkdir(mode=0o700);name=".agentcfg-ready" if marker else "data";(root/name).write_bytes(b"x");(root/name).chmod(0o600)
  expected={} if marker else packages.inventory(root);original=os.scandir
  class Replay:
    def __init__(self,path):
      with original(path) as children:self.entries=list(children)
    def __enter__(self):return iter(self.entries+self.entries)
    def __exit__(self,*args):return None
  # 仅合成OS条目重放反例；完整正控仍是真实scandir/原validator。
  with Tree(root) as tree:
    monkeypatch.setattr(api.os,"scandir",Replay)
    with pytest.raises(ValueError):api._scan(tree,expected)


def test_synthetic_stat_directory_owner_rejection_is_not_actual_chown():
  info=SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=os.geteuid()+1,st_dev=1,st_ino=1)
  with pytest.raises(ValueError):module()._directory(info)
