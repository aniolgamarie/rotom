"""纯 Node 声明身份与原 legacy 身份，不读取发行物。"""

import base64
import copy
import traceback

import pytest

from agentcfg import pi_capabilities as capabilities, pi_node_asset
from agentcfg.activity import digest
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError


SECRET = "SYNTHETIC_PRIVATE_SOURCE"


def node_source(release="v24.14.0", archive="a"*64, binary="b"*64, license="c"*64, vendor=False):
  root="node-"+release+"-linux-x64"
  row={"kind":"asset","format":"node.tar.gz","url":"https://nodejs.org/download/release/"+release+"/"+root+".tar.gz", "platform":"linux-x86_64",
    "archive_digest":archive,"archive_member":root+"/bin/node","target":"bin/pi-node","license_files":["agents/pi/build/licenses/node-"+release+"/LICENSE"],
    "node_archive":{"schema":1,"release":release,"platform":"linux-x86_64","archive_sha256":archive,"binary_sha256":binary,"license_sha256":license}}
  if vendor:row["vendor_path"]="vendor/"+root+"-"+archive+".tar.gz"
  return row


def projection(release="v24.14.0", archive="a"*64, binary="b"*64, license="c"*64):
  return {"kind":"asset","archive_digest":archive,"archive_member":"node-"+release+"-linux-x64/bin/node","target":"bin/pi-node","platform":"linux-x86_64","format":"node.tar.gz",
    "node_archive":{"schema":1,"release":release,"platform":"linux-x86_64","archive_sha256":archive,"binary_sha256":binary,"license_sha256":license}}


def invalid(action):
  try:raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(ConfigError) as caught:action()
  error=caught.value
  assert type(error) is ConfigError and error.code=="pi-provider-binding"
  assert error.__cause__ is None and error.__context__ is None
  assert SECRET not in "".join(traceback.format_exception(error))
  return error


def test_exact_seven_field_canonical_projection_and_optional_vendor():
  assert capabilities.source_identity(node_source())==digest(projection())
  assert capabilities.source_identity(node_source(vendor=True))==digest(projection())


@pytest.mark.parametrize("field,value",[("release","v24.14.1"),("archive","d"*64),("binary","e"*64),("license","f"*64)])
def test_all_selection_identity_changes_are_causal(field,value):
  kwargs={field:value}
  original=capabilities.source_identity(node_source())
  changed=capabilities.source_identity(node_source(**kwargs))
  assert changed==digest(projection(**kwargs)) and changed!=original


@pytest.mark.parametrize("fault",["missing","kind","format","url","member","target","license","archive","platform","vendor","unknown","metadata_unknown","metadata_type"])
def test_node_route_cannot_fallback_and_complete_derivations(fault):
  row=node_source()
  if fault=="missing":del row["node_archive"]
  elif fault=="kind":row["kind"]="local"
  elif fault=="format":row["format"]="tar.gz"
  elif fault=="url":row["url"]="https://mirror.invalid/node"
  elif fault=="member":row["archive_member"]="node/bin/node"
  elif fault=="target":row["target"]="bin/other"
  elif fault=="license":row["license_files"]=["agents/pi/build/licenses/other/LICENSE"]
  elif fault=="archive":row["archive_digest"]="d"*64
  elif fault=="platform":row["platform"]="linux-arm64"
  elif fault=="vendor":row["vendor_path"]="vendor/wrong.tar.gz"
  elif fault=="unknown":row["extra"]=SECRET
  elif fault=="metadata_unknown":row["node_archive"]["extra"]=1
  elif fault=="metadata_type":row["node_archive"]=[]
  invalid(lambda:capabilities.source_identity(row))


def test_captured_reference_remains_original_during_caller_mutation(monkeypatch):
  row=node_source(); original=pi_node_asset.capture_node_asset;calls=[]
  def capture(snapshot):
    assert snapshot is not row
    ref=original(snapshot);calls.append(ref)
    row.update(node_source(release="v25.0.0",archive="d"*64))
    return ref
  monkeypatch.setattr(pi_node_asset,"capture_node_asset",capture)
  assert capabilities.source_identity(row)==digest(projection())
  assert len(calls)==1 and row["node_archive"]["release"]=="v25.0.0"


@pytest.mark.parametrize("fault",["dict","key","format","kind","release","schema","metadata","license"])
def test_native_type_first_zero_foreign_hooks(fault):
  calls=[];armed=False
  class String(str):
    def __hash__(self):
      if armed:calls.append("hash");raise AssertionError()
      return str.__hash__(self)
    def __eq__(self,other):calls.append("eq");raise AssertionError()
  class Number(int):
    def __eq__(self,other):calls.append("eq");raise AssertionError()
  class Dict(dict):
    def get(self,*args):calls.append("get");raise AssertionError()
    def items(self):calls.append("items");raise AssertionError()
  row=node_source()
  if fault=="dict":row=Dict(row)
  if fault=="key":row[String("extra")]=1;armed=True
  if fault=="format":row["format"]=String("node.tar.gz")
  if fault=="kind":row["kind"]=String("asset")
  if fault=="release":row["node_archive"]["release"]=String("v24.14.0")
  if fault=="schema":row["node_archive"]["schema"]=Number(1)
  if fault=="metadata":row["node_archive"]=Dict(row["node_archive"])
  if fault=="license":row["license_files"]=[String(row["license_files"][0])]
  invalid(lambda:capabilities.source_identity(row))
  assert calls==[]


def test_foreign_dependency_and_digest_errors_unchanged_fresh(monkeypatch):
  foreign=DependencyError(SECRET)
  def fail(*args):raise foreign
  monkeypatch.setattr(pi_node_asset,"capture_node_asset",fail)
  first=invalid(lambda:capabilities.source_identity(node_source()))
  second=invalid(lambda:capabilities.source_identity(node_source()))
  assert first is not second and foreign.args==(SECRET,) and foreign.__cause__ is None


def test_digest_failure_mapped_to_fresh_fixed_error(monkeypatch):
  foreign=ValueError(SECRET)
  def fail(*args):raise foreign
  monkeypatch.setattr(capabilities,"digest",fail)
  invalid(lambda:capabilities.source_identity(node_source()))
  assert foreign.args==(SECRET,)


def legacy(route):
  row={"kind":route,"license_files":["agents/pi/build/licenses/fixture/LICENSE"]}
  if route=="npm":
    integrity="sha512-"+base64.b64encode(bytes(64)).decode()
    row.update(package="fixture",version="1.0.0",resolved="https://example.invalid/fixture.tgz",integrity=integrity)
    expected={"kind":"npm","package":"fixture","version":"1.0.0","integrity":integrity}
  elif route in ("git","local"):
    row.update(package="fixture",version="1.0.0",source_path="agents/pi/packages/fixture",source_tree_digest="d"*64,vendor_path="vendor/fixture.tgz",archive_digest="e"*64)
    expected={"kind":route,"package":"fixture","version":"1.0.0","archive_digest":"e"*64,"source_tree_digest":"d"*64}
    if route=="git":row["commit"]="f"*40;expected["commit"]="f"*40
  else:
    row.update(kind="asset",format="raw" if route=="raw" else "tar.gz",platform="all" if route=="raw" else "linux-x86_64",target="data/fixture" if route=="raw" else "bin/fixture",archive_digest="e"*64)
    expected={key:row[key] for key in ("kind","archive_digest","target","platform","format")}
    if route=="raw":row["size"]=1;expected["size"]=1
    else:row["archive_member"]="fixture";expected["archive_member"]="fixture"
    if route=="built":
      row.update(target="bin/pi-bwrap",archive_member="bin/pi-bwrap",vendor_path="vendor/fixture.tgz",build_record={"recipe":"bubblewrap-v1","path":"build-records/"+"f"*64+".json","digest":"f"*64},license_files=["agents/pi/build/licenses/fixture/LICENSE","agents/pi/build/licenses/fixture/NOTICE"])
      expected.update(target="bin/pi-bwrap",archive_member="bin/pi-bwrap",build_record={"recipe":"bubblewrap-v1","digest":"f"*64})
    else:row["url"]="https://example.invalid/fixture"
  return row,expected


@pytest.mark.parametrize("route",["npm","git","local","raw","tar.gz","built"])
def test_legal_legacy_hash_exact_and_only_added_node_metadata_rejected(route):
  row,expected=legacy(route)
  assert capabilities.source_identity(row)==digest(expected)
  row["node_archive"]=node_source()["node_archive"]
  invalid(lambda:capabilities.source_identity(row))
