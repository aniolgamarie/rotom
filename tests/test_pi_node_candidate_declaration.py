"""候选 Node 元数据闭包，只造纯已解析 lock，不读 vendor 或运行工具。"""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_capabilities import source_identity, validate_manifest_bindings, validate_selection
from agentcfg.pi_dependencies import PiLock
from agentcfg.pi_node_asset import capture_node_asset, validate_node_asset_toolchain
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError


ROOT = Path(__file__).resolve().parents[1]
NODE = "pi-node-linux-x86_64"
NODE_IDENTITY = "de0e7d78f97d21efb33ceef4949f73e3813314d4ce56ed9a7e4a98c2874c3865"
SNAPSHOT = {"schema":1,"release":"v24.14.0","platform":"linux-x86_64",
  "archive_sha256":"dbf5b8665dec15e59e6359a517fefb47b23fdb9152d8def975b9bca3dfc6d355",
  "binary_sha256":"e237a2839d0cbdc9a9a2adda1a184afc0f5b20306ffbe923af5686550472d8a8",
  "license_sha256":"4573185d56580da2b890ba34a85a409257640f1c5632eade4300137266194d18"}
EXPECTED_SOURCE = {"kind":"asset","format":"node.tar.gz","url":"https://nodejs.org/download/release/v24.14.0/node-v24.14.0-linux-x64.tar.gz",
  "platform":"linux-x86_64","archive_digest":SNAPSHOT["archive_sha256"],"archive_member":"node-v24.14.0-linux-x64/bin/node","target":"bin/pi-node",
  "license_files":["agents/pi/build/licenses/node-v24.14.0/LICENSE"],"vendor_path":"vendor/node-v24.14.0-linux-x64-"+SNAPSHOT["archive_sha256"]+".tar.gz","node_archive":SNAPSHOT}
EXPECTED_PROJECTION = {"kind":"asset","archive_digest":SNAPSHOT["archive_sha256"],"archive_member":"node-v24.14.0-linux-x64/bin/node","target":"bin/pi-node","platform":"linux-x86_64","format":"node.tar.gz","node_archive":SNAPSHOT}


def candidate():
  return json.loads((ROOT/"agents/pi/dependencies-modern.json").read_bytes())


def support(document):
  return document["capability_bindings"]["providers"]["pi-native-session-v1"]["support_sources"]


def exact_package_contract(document):
  assert document["sources"][NODE] == EXPECTED_SOURCE
  bindings = document["capability_bindings"];catalog = bindings["catalog"];selection = bindings["selections"]["pi-base"]
  assert document["profiles"]["pi-base"]["source_ids"].count(NODE)==1
  assert document["profiles"]["pi-base"]["source_ids"][-1]==NODE
  assert catalog["capabilities"]["session-runtime"]["source_ids"].count(NODE)==1
  assert catalog["capabilities"]["session-runtime"]["source_ids"][-1]==NODE
  assert catalog["source_profiles"][NODE]==["pi-base"]
  rows=[row for row in support(document) if row["source_id"]==NODE]
  assert rows==[{"source_id":NODE,"source_version":None,"source_identity":NODE_IDENTITY}]
  assert support(document)[-1]==rows[0]
  assert catalog["revision"]==selection["revision"]==selection["source_revision"]==2
  assert selection["state"]=="candidate" and set(document["profiles"])==set(bindings["selections"])=={"pi-base"}
  assert all(row["verified_host_versions"]==[] and row["candidate_host_versions"]==["1.0.1"] for row in bindings["providers"].values())


def synthetic_lock(document):
  value=deepcopy(document);resolved={}
  for key,row in value["sources"].items():
    row.pop("resources",None)
    if key!=NODE:
      if row["kind"]=="npm":row.update(resolved="https://example.invalid/"+key+".tgz",integrity="sha512-"+base64.b64encode(bytes(64)).decode())
      else:
        row["archive_digest"]=hashlib.sha256(("synthetic-archive:"+key).encode()).hexdigest()
        if row["kind"] in ("local","git"):row["source_tree_digest"]=hashlib.sha256(("synthetic-tree:"+key).encode()).hexdigest()
    resolved[key]=row
  bindings=value["capability_bindings"]
  for provider in bindings["providers"].values():
    for declared in [provider,*provider.get("support_sources",[])]:
      key=declared["source_id"]
      if key!=NODE:
        declared["source_version"]=resolved[key].get("version")
        declared["source_identity"]=source_identity(resolved[key])
  selection=bindings["selections"]["pi-base"]
  resources={kind:[] for kind in ("extensions","skills","prompts","themes")}
  for capability_id,capability in bindings["catalog"]["capabilities"].items():
    for resource_id in capability["resource_ids"]:
      resources["extensions"].append({"id":resource_id,"capability_id":capability_id})
  piece={"engine":"node","source_ids":list(value["profiles"]["pi-base"]["source_ids"]),
    "capability_ids":[row["capability_id"] for row in selection["bindings"]],"resource_manifest":resources}
  metadata={"sources":resolved,"profile_slices":{"pi-base":piece}}
  return bindings,PiLock("1"*64,metadata,{})


def validate(document):
  bindings,lock=synthetic_lock(document)
  validate_manifest_bindings(bindings,lock.metadata["profile_slices"])
  return validate_selection(bindings["catalog"],bindings["providers"],bindings["selections"]["pi-base"],lock,host_version="1.0.1",engine="node")


def test_exact_source_schema_helper_toolchain_and_independent_digest():
  document=candidate();exact_package_contract(document)
  assert hashlib.sha256(json_bytes(EXPECTED_PROJECTION)).hexdigest()==NODE_IDENTITY
  assert json_bytes(EXPECTED_PROJECTION).endswith(b"\n")
  schema=json.loads((ROOT/"schemas/pi-lock.schema.json").read_bytes())["properties"]["sources"]["additionalProperties"]
  jsonschema.Draft202012Validator(schema).validate(document["sources"][NODE])
  reference=capture_node_asset(document["sources"][NODE])
  assert reference==validate_node_asset_toolchain(document["sources"][NODE],document["toolchains"])
  assert source_identity(document["sources"][NODE])==NODE_IDENTITY
  license=(ROOT/document["sources"][NODE]["license_files"][0]).read_bytes()
  assert hashlib.sha256(license).hexdigest()==SNAPSHOT["license_sha256"]
  assert document["toolchains"]=={"node":"v24.14.0","npm":"11.19.1","bun":"1.4.0"}


def test_complete_original_resource_and_source_closure_candidate_only():
  document=candidate();exact_package_contract(document);result=validate(document)
  assert result.state=="candidate"
  assert (NODE,None,NODE_IDENTITY) in result.source_expectations
  assert {row[0] for row in result.source_expectations}==set(document["profiles"]["pi-base"]["source_ids"])
  assert dict(result.resource_expectations)["extensions"]==("colorful-footer","loop-guard","pi-todo")
  assert all(not values for kind,values in result.resource_expectations if kind!="extensions")


@pytest.mark.parametrize("fault",["source","profile","capability","source_profiles","support","support_identity","support_version","duplicate_profile","duplicate_support","catalog_revision","source_revision"])
def test_public_validators_reject_individual_closure_fault(fault):
  document=candidate();exact_package_contract(document);assert validate(document).state=="candidate"
  bindings=document["capability_bindings"];catalog=bindings["catalog"]
  if fault=="source":del document["sources"][NODE]
  if fault=="profile":document["profiles"]["pi-base"]["source_ids"].remove(NODE)
  if fault=="capability":catalog["capabilities"]["session-runtime"]["source_ids"].remove(NODE)
  if fault=="source_profiles":del catalog["source_profiles"][NODE]
  if fault=="support":support(document).pop()
  if fault=="support_identity":support(document)[-1]["source_identity"]="0"*64
  if fault=="support_version":support(document)[-1]["source_version"]="24.14.0"
  if fault=="duplicate_profile":document["profiles"]["pi-base"]["source_ids"].append(NODE)
  if fault=="duplicate_support":support(document).append(deepcopy(support(document)[-1]))
  if fault=="catalog_revision":catalog["revision"]=3
  if fault=="source_revision":bindings["selections"]["pi-base"]["source_revision"]=3
  with pytest.raises((ConfigError,DependencyError)):validate(document)


@pytest.mark.parametrize("field",["catalog","selection","source"])
def test_fixed_three_revisions_are_independent_package_requirements(field):
  document=candidate();exact_package_contract(document)
  if field=="catalog":document["capability_bindings"]["catalog"]["revision"]=1
  else:document["capability_bindings"]["selections"]["pi-base"]["revision" if field=="selection" else "source_revision"]=1
  with pytest.raises(AssertionError):exact_package_contract(document)


@pytest.mark.parametrize("field",["archive_sha256","binary_sha256","license_sha256"])
def test_digest_drift_keeps_valid_derived_fields_and_original_binding(field):
  document=candidate();exact_package_contract(document);assert validate(document).state=="candidate"
  row=document["sources"][NODE];row["node_archive"][field]="d"*64
  if field=="archive_sha256":
    row["archive_digest"]="d"*64;row["vendor_path"]="vendor/node-v24.14.0-linux-x64-"+"d"*64+".tar.gz"
  capture_node_asset(row)
  assert support(document)[-1]["source_identity"]==NODE_IDENTITY
  assert source_identity(row)!=NODE_IDENTITY
  with pytest.raises(ConfigError):validate(document)


def test_generic_validation_cannot_replace_named_node_requirement():
  document=candidate();exact_package_contract(document)
  del document["sources"][NODE]
  document["profiles"]["pi-base"]["source_ids"].remove(NODE)
  catalog=document["capability_bindings"]["catalog"]
  catalog["capabilities"]["session-runtime"]["source_ids"].remove(NODE);del catalog["source_profiles"][NODE];support(document).pop()
  assert validate(document).state=="candidate"
  with pytest.raises(KeyError):exact_package_contract(document)
