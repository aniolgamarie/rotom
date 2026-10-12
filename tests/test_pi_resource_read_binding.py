"""P2: 当前资源profile必须绑定原receipt slice，不能靠自报ID扩读。"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from agentcfg.deployment import json_bytes
from agentcfg.pi_dependencies import digest, platform_id
from agentcfg.pi_modern_launcher import commands
from agentcfg.pi_resource_reads import selected_resource
from agentcfg.storage import Tree, Conflict


def resource_host(tmp_path, profile_id="pi-full"):
  tmp_path.mkdir(parents=True, exist_ok=True, mode=0o700)
  piece = {"engine": "node", "source_ids": ["pi-host", "pi-ai"], "package_path": "slice/package.json",
    "lock_path": "slice/package-lock.json", "package_json_digest": "1"*64, "package_lock_digest": "2"*64,
    "entrypoint": "slice/node_modules/fixture-sdk/index.js", "ai_package": "fixture-ai",
    "resource_manifest": {"extensions": [], "skills": [{"id": "selected-skill", "capability_id": "unified-delegate", "path": "skills/selected"}], "prompts": [], "themes": []},
    "resource_manifest_digest": "", "capability_ids": ["unified-delegate"], "runtime_files": [
      {"source": "src/agentcfg/fixture.py", "path": "supervisor/fixture.py", "transform": "copy", "input_digest": "4"*64, "digest": "4"*64, "mode": 384}]}
  piece["resource_manifest_digest"] = digest(piece["resource_manifest"])
  piece["identity"] = digest(piece)
  tools = {"node": "v24.14.0", "npm": "11.19.1", "bun": "1.4.0"}
  binding = {key: "3"*64 for key in ("selection", "catalog", "bindings", "binding_context")}
  lock = "a"*64; platform = platform_id()
  base = digest({"lock_identity":lock,"slice_identity":piece["identity"],"platform":platform,"toolchain_identity":digest(tools)})
  binding.update(runtime=base, lock=lock, slice=digest(piece), profile=profile_id, adapter_version="pi-1", platform=platform)
  identity = digest(binding);root=tmp_path/identity;root.mkdir(mode=0o700)
  receipt={"schema_version":2,"status":"installed","identity":identity,"lock_identity":lock,"slice_identity":piece["identity"],
    "slice":piece,"files":{},"platform":platform,"toolchains":tools,"toolchain_identity":digest(tools),"binding_identity":binding}
  profile={"schema_version":2,"profile_id":profile_id,"engine":"node","package_path":piece["package_path"],"entrypoint":piece["entrypoint"],
    "resources":piece["resource_manifest"],"lock_identity":lock,"slice_identity":piece["identity"],"runtime_identity":identity,
    "toolchains":tools,"platform":platform,"sdk_package":"fixture-sdk","sdk_version":"1.0.1","ai_package":"fixture-ai","ai_version":"1.0.2"}
  with Tree(root) as tree:
    tree.write_state(".agentcfg-receipt.json",json_bytes(receipt))
    tree.write_state("runtime/profile.json",json_bytes(profile))
    tree.write_state("runtime/commands.json",json_bytes(commands(piece)))
    for name,version in (("fixture-sdk","1.0.1"),("fixture-ai","1.0.2")):
      tree.write_state("slice/node_modules/"+name+"/package.json",json_bytes({"name":name,"version":version}))
    tree.write_state(piece["lock_path"],json_bytes({"packages":{"node_modules/fixture-sdk":{"version":"1.0.1"},"node_modules/fixture-ai":{"version":"1.0.2"}}}))
    for name in ("selected","unselected"):tree.write_state("skills/"+name+"/SKILL.md",("# "+name).encode())
  manifest={"profile_id":"pi-full","resources":{"skills":[]},"resource_ids":{"skills":{}},"plugins":["model-delegate"],
    "plugin_capabilities":{"model-delegate":{"capability_id":"unified-delegate","model_tools":[]}}}
  host=SimpleNamespace(runtime_root=root,config={"instance_root":str(tmp_path/"instance"),"lock_identity":lock,"slice_identity":piece["identity"]})
  return host,manifest,receipt,profile


def test_current_profile_same_ids_cannot_redirect_to_existing_unselected_skill(tmp_path):
  host,manifest,_,profile=resource_host(tmp_path)
  assert selected_resource(host,manifest,host.runtime_root/"skills/selected/SKILL.md") is not None
  profile["resources"]["skills"][0]["path"]="skills/unselected"
  (host.runtime_root/"runtime/profile.json").write_bytes(json_bytes(profile))
  with pytest.raises(Conflict):
    selected_resource(host,manifest,host.runtime_root/"skills/unselected/SKILL.md")


def test_resource_binding_does_not_scan_full_runtime_inventory(tmp_path, monkeypatch):
  host,manifest,_,_=resource_host(tmp_path)
  monkeypatch.setattr("agentcfg.pi_runtime_packages.inventory", lambda *_: pytest.fail("resource read must not scan installation"))
  assert selected_resource(host,manifest,host.runtime_root/"skills/selected/SKILL.md")["path"] == str(host.runtime_root/"skills/selected")


@pytest.mark.parametrize("name,row", [
  ("dir", {"kind":"directory"}), ("link", {"kind":"link","target":"target"}),
  ("file", {"kind":"file","sha256":"a"*64,"mode":384}), ("file", {"kind":"file","sha256":"a"*64,"mode":1.0}),
  ("file", {"kind":"file","sha256":"a"*64,"mode":True}), ("file", {"kind":"file","sha256":"a"*64,"mode":512}),
  ("file", {"kind":"file","sha256":"a"*64,"mode":-1}), ("file", {"kind":"directory","unknown":True}),
  ("file", []), ("file", {"kind":"unknown"}), ("file", {"kind":False}),
  ("../bad", {"kind":"directory"}), ("bad\\path", {"kind":"directory"}), ("bad\x00", {"kind":"directory"}),
  ("line\nname", {"kind":"directory"}), ("surrogate\ud800", {"kind":"directory"}),
])
def test_receipt_dispatch_matches_original_schema_exact_semantics(tmp_path, name, row):
  from agentcfg.pi_catalog import read_schema
  from agentcfg.pi_resource_reads import _valid_receipt
  from jsonschema import Draft202012Validator
  _,_,receipt,_=resource_host(tmp_path)
  receipt["files"]={name:row};schema=read_schema("runtime-receipt")
  assert _valid_receipt(receipt,schema) == Draft202012Validator(schema).is_valid(receipt)


@pytest.mark.parametrize("change", ["new-files-rule", "nonexclusive-kind"])
def test_receipt_schema_change_uses_full_fallback(tmp_path, change):
  from agentcfg.pi_catalog import read_schema
  from agentcfg.pi_resource_reads import _valid_receipt, _receipt_validators
  from jsonschema import Draft202012Validator
  _,_,receipt,_=resource_host(tmp_path);schema=read_schema("runtime-receipt")
  if change=="new-files-rule":schema["properties"]["files"]["minProperties"]=1
  else:schema["properties"]["files"]["additionalProperties"]["oneOf"][0]["properties"]["kind"]={"type":"string"}
  assert _receipt_validators(json.dumps(schema,sort_keys=True,separators=(",",":")))[1] is None
  assert _valid_receipt(receipt,schema) == Draft202012Validator(schema).is_valid(receipt)


@pytest.mark.parametrize("fault", ["receipt-slice","receipt-id","profile-missing","profile-mode","profile-unknown","profile-duplicate","receipt-duplicate"])
def test_broken_current_resource_binding_fails_closed(tmp_path,fault):
  host,manifest,receipt,profile=resource_host(tmp_path)
  p=host.runtime_root/"runtime/profile.json";r=host.runtime_root/".agentcfg-receipt.json"
  if fault=="receipt-slice":receipt["slice"]["resource_manifest"]["skills"][0]["path"]="skills/unselected";r.write_bytes(json_bytes(receipt))
  elif fault=="receipt-id":receipt["identity"]="f"*64;r.write_bytes(json_bytes(receipt))
  elif fault=="profile-missing":p.unlink()
  elif fault=="profile-mode":p.chmod(0o644)
  elif fault=="profile-unknown":profile["unknown"]=True;p.write_bytes(json_bytes(profile))
  elif fault=="profile-duplicate":p.write_text(p.read_text().replace('"schema_version":2','"schema_version":1,"schema_version":2'))
  else:r.write_text(r.read_text().replace('"schema_version":2','"schema_version":1,"schema_version":2'))
  with pytest.raises(Conflict):
    selected_resource(host,manifest,host.runtime_root/"skills/selected/SKILL.md")
