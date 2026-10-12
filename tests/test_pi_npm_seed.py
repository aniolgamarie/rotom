"""固定npm输入默认回归；所有resolver命令均fake，actual146只做数据/archive核对。"""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg import pi_vendor as vendor
from agentcfg.pi_dependencies import PiBackend
from agentcfg.schema import ConfigError
from agentcfg.process import DependencyError
from test_pi_dependencies import payload, fixture_repository
from test_pi_lock_families import generator_fixture

ROOT = Path(__file__).resolve().parents[1]
INVALID = "pi-build-resolution-seed-invalid"
DRIFT = "pi-build-resolution-seed-drift"


def helper():
  from agentcfg import pi_npm_seed
  return pi_npm_seed


def synthetic(tmp_path, monkeypatch):
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  root = workspace.repository
  package = {"name":"agentcfg-pi-base", "version":"1.0.0", "private":True,
    "dependencies":{row["package"]:row["version"] for row in inputs["sources"].values()}}
  resolution = json.loads((root / "locks/pi-modern/pi-base/package-lock.json").read_bytes())
  seed = {"name":package["name"], "version":"1.0.0", "lockfileVersion":3, "requires":True,
    "packages":resolution["packages"]}
  seed["packages"][""].update(name=package["name"],version=package["version"])
  source = "agents/pi/build/resolutions/pi-base.package-lock.json"
  target = root / source; target.parent.mkdir(parents=True)
  raw = payload(seed); target.write_bytes(raw)
  ref = {"source":source,"sha256":hashlib.sha256(raw).hexdigest()}
  inputs["profiles"]["pi-base"]["npm_resolution_seed"] = ref
  path.write_bytes(payload(inputs))
  return workspace, inputs, path, calls, package, seed, raw, ref


def reject(function, *args, code=INVALID):
  try: raise RuntimeError("SYNTHETIC_PRIVATE_SEED")
  except RuntimeError:
    with pytest.raises(ConfigError) as caught: function(*args)
  assert caught.value.args == ConfigError(code).args and caught.value.exit_code == 2
  assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_seed_is_written_before_original_fake_npm_and_candidate_readback(tmp_path, monkeypatch):
  workspace, inputs, path, calls, package, seed, raw, ref = synthetic(tmp_path, monkeypatch)
  observed=[]
  def checked(argv, *, cwd, env):
    calls.append(argv)
    if argv==["node","--version"]: return inputs["toolchains"]["node"]
    if argv==["npm","--version"]: return inputs["toolchains"]["npm"]
    assert argv==["npm","install","--package-lock-only","--ignore-scripts","--no-audit","--no-fund"]
    assert (cwd/"package-lock.json").read_bytes()==raw
    assert json.loads((cwd/"package.json").read_bytes())==package
    observed.append(True); return ""
  monkeypatch.setattr(vendor,"checked",checked)
  lock=PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert observed==[True] and len(calls)==3
  assert lock.validated_bindings["pi-base"].state=="candidate"
  assert lock.pairs["pi-base"][1]==raw and "npm_resolution_seed" not in lock.metadata["profile_slices"]["pi-base"]
  with pytest.raises(DependencyError): PiBackend(profile="pi-base").sync(workspace,lock)


@pytest.mark.parametrize("fault", ["source","sha","unknown","bool","wrong-profile","missing","digest","duplicate","top-field","version-float","requires","root-name","root-extra","dependency","direct-version","link","file-extra","uri","sri","missing-sri"])
def test_invalid_seed_fails_before_any_temporary_directory_or_checked(tmp_path, monkeypatch, fault):
  workspace, inputs, path, calls, package, seed, raw, ref = synthetic(tmp_path, monkeypatch)
  root=workspace.repository; target=root/ref["source"]
  if fault=="source": ref["source"]="agents/pi/build/resolutions/../pi-base.package-lock.json"
  elif fault=="sha": ref["sha256"]="A"*64
  elif fault=="unknown": ref["proof"]=True
  elif fault=="bool": inputs["profiles"]["pi-base"]["npm_resolution_seed"]=True
  elif fault=="wrong-profile": ref["source"]="agents/pi/build/resolutions/pi-full.package-lock.json"
  elif fault=="missing": target.unlink()
  elif fault=="digest": target.write_bytes(b"different")
  elif fault=="duplicate":
    raw=b'{"name":"agentcfg-pi-base","name":"duplicate"}';target.write_bytes(raw);ref["sha256"]=hashlib.sha256(raw).hexdigest()
  else:
    host=next(name for name in seed["packages"] if name and "synthetic-host" in name)
    if fault=="top-field": seed["proof"]=True
    elif fault=="version-float": seed["lockfileVersion"]=3.0
    elif fault=="requires": seed["requires"]=1
    elif fault=="root-name": seed["packages"][""]["name"]="wrong"
    elif fault=="root-extra": seed["packages"][""]["optionalDependencies"]={}
    elif fault=="dependency": seed["packages"][""]["dependencies"]={}
    elif fault=="direct-version": seed["packages"][host]["version"]="2.0.0"
    elif fault=="link": seed["packages"][host]["link"]=True
    elif fault=="file-extra": seed["packages"]["node_modules/extra"]={"version":"1.0.0","resolved":"file:../extra.tgz","integrity":"sha512-"+base64.b64encode(b"x"*64).decode()}
    elif fault=="uri": seed["packages"][host]["resolved"]="https://user:password@example.invalid/a.tgz"
    elif fault=="sri": seed["packages"][host]["integrity"]="sha256-bad"
    elif fault=="missing-sri": seed["packages"][host].pop("integrity")
    raw=payload(seed);target.write_bytes(raw);ref["sha256"]=hashlib.sha256(raw).hexdigest()
  path.write_bytes(payload(inputs)); sentinel=(root/"locks/pi-modern/manifest.json").read_bytes()
  monkeypatch.setattr(vendor.tempfile,"TemporaryDirectory",lambda *a,**k:pytest.fail("preflight must precede TemporaryDirectory"))
  reject(lambda:PiBackend(profile="pi-base").resolve_lock(root))
  assert calls==[] and (root/"locks/pi-modern/manifest.json").read_bytes()==sentinel


@pytest.mark.parametrize("field", ["path","name","version","resolved","integrity","optional","os","cpu","libc"])
def test_nine_identity_drift_rejects_before_publish_and_keeps_prior_manifest(tmp_path, monkeypatch, field):
  workspace, inputs, path, calls, package, seed, raw, ref = synthetic(tmp_path, monkeypatch)
  root=workspace.repository; sentinel=(root/"locks/pi-modern/manifest.json").read_bytes();changed=deepcopy(seed)
  key=next(k for k in changed["packages"] if k and "synthetic-host" in k)
  if field=="path": changed["packages"]["node_modules/moved-host"]=changed["packages"].pop(key)
  else: changed["packages"][key][field]={"name":"different","version":"2.0.0","resolved":"https://example.invalid/drift.tgz","integrity":"sha512-"+base64.b64encode(b"x"*64).decode(),"optional":True,"os":["darwin"],"cpu":["arm64"],"libc":["musl"]}[field]
  def checked(argv, *, cwd, env):
    calls.append(argv)
    if argv==["node","--version"]:return inputs["toolchains"]["node"]
    if argv==["npm","--version"]:return inputs["toolchains"]["npm"]
    (cwd/"package-lock.json").write_bytes(payload(changed));return ""
  monkeypatch.setattr(vendor,"checked",checked)
  reject(lambda:PiBackend(profile="pi-base").resolve_lock(root),code=DRIFT)
  assert len(calls)==3 and (root/"locks/pi-modern/manifest.json").read_bytes()==sentinel


def test_sri_completion_happens_before_seed_projection_comparison(tmp_path, monkeypatch):
  workspace, inputs, path, calls, package, seed, raw, ref = synthetic(tmp_path, monkeypatch)
  altered=deepcopy(seed);key=next(k for k in seed["packages"] if k and "synthetic-host" in k);original=seed["packages"][key];altered["packages"][key].pop("integrity")
  def checked(argv, *, cwd, env):
    calls.append(argv)
    if argv==["node","--version"]:return inputs["toolchains"]["node"]
    if argv==["npm","--version"]:return inputs["toolchains"]["npm"]
    if argv[:2]==["npm","view"]:return json.dumps({"tarball":original["resolved"],"integrity":original["integrity"]})
    (cwd/"package-lock.json").write_bytes(payload(altered));return ""
  monkeypatch.setattr(vendor,"checked",checked)
  lock=PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert len(calls)==4 and lock.validated_bindings["pi-base"].state=="candidate"


def test_actual_declared_canonical_seed_and_current_registry_projection():
  recipes, inputs=vendor.read_inputs(ROOT,family="modern",current_profiles=("pi-base",));profile=inputs["profiles"]["pi-base"];selected={key:inputs["sources"][key] for key in profile["source_ids"] if inputs["sources"][key]["kind"] in ("npm","local","git")};records={};archives={}
  for key,source in selected.items():
    if source["kind"]=="npm":continue
    raw,record=vendor.build_archive(ROOT,recipes["sources"][key]);record["vendor_path"]="vendor/"+key+"-"+record["archive_digest"]+".tgz";records[key]=record;archives[record["vendor_path"]]=raw
  assert archives and len(archives)==sum(source["kind"] in ("local","git") for source in selected.values())
  package={"name":"agentcfg-pi-base","version":"1.0.0","private":True,"dependencies":{source["package"]:source["version"] if source["kind"]=="npm" else "file:../"+records[key]["vendor_path"] for key,source in selected.items()}}
  raw,identity=helper().load_seed(ROOT,"pi-base",profile["npm_resolution_seed"],package,selected,records,archives)
  assert hashlib.sha256(raw).hexdigest()==profile["npm_resolution_seed"]["sha256"]
  from agentcfg.pi_license_bundle import REGISTRY
  registries=[row["source"] for row in profile["runtime_files"] if REGISTRY.fullmatch(row["path"])]
  assert len(registries)==1
  registry=json.loads((ROOT/registries[0]).read_bytes())
  fields=("path","name","version","resolved","integrity","optional","os","cpu","libc")
  assert identity and len(identity)==len(registry["packages"]) and identity==[{key:row[key] for key in fields} for row in registry["packages"]]
  assert json.loads(raw)["packages"][""]["name"]==package["name"]


@pytest.mark.parametrize("fault",["uri","version","integrity","archive"])
def test_actual_local_seed_preflight_uses_actual_archive_bytes(tmp_path, fault):
  source={"kind":"local","package":"@fixture/local","version":"1.0.0"};record={**source,"vendor_path":"vendor/local.tgz"};raw=b"inert actual archive bytes"
  package={"name":"agentcfg-pi-base","version":"1.0.0","private":True,"dependencies":{"@fixture/local":"file:../vendor/local.tgz"}}
  seed={"name":package["name"],"version":"1.0.0","lockfileVersion":3,"requires":True,"packages":{"":{"name":package["name"],"version":"1.0.0","dependencies":package["dependencies"]},"node_modules/@fixture/local":{"version":"1.0.0","resolved":"file:../vendor/local.tgz","integrity":"sha512-"+base64.b64encode(hashlib.sha512(raw).digest()).decode()}}}
  if fault=="uri":seed["packages"]["node_modules/@fixture/local"]["resolved"]="file:../wrong.tgz"
  if fault=="version":seed["packages"]["node_modules/@fixture/local"]["version"]="2.0.0"
  if fault=="integrity":seed["packages"]["node_modules/@fixture/local"]["integrity"]="sha512-AA=="
  if fault=="archive":raw=b"different archive"
  path=tmp_path/"agents/pi/build/resolutions/pi-base.package-lock.json";path.parent.mkdir(parents=True);body=payload(seed);path.write_bytes(body);ref={"source":"agents/pi/build/resolutions/pi-base.package-lock.json","sha256":hashlib.sha256(body).hexdigest()}
  reject(helper().load_seed,tmp_path,"pi-base",ref,package,{"local":source},{"local":record},{"vendor/local.tgz":raw})


def test_reference_file_symlink_is_fixed_invalid(tmp_path):
  outside=tmp_path/"outside";outside.write_bytes(b"inert")
  path=tmp_path/"agents/pi/build/resolutions/pi-base.package-lock.json";path.parent.mkdir(parents=True);path.symlink_to(outside)
  ref={"source":"agents/pi/build/resolutions/pi-base.package-lock.json","sha256":hashlib.sha256(b"inert").hexdigest()}
  reject(helper().load_seed,tmp_path,"pi-base",ref,{}, {},{}, {})


def test_legacy_rejects_seed_without_new_helper_or_subprocess(tmp_path, monkeypatch):
  root,manifest=fixture_repository(tmp_path);build=root/"agents/pi/build";build.mkdir();(build/"recipes.json").write_bytes(payload({"schema_version":1,"sources":{}}))
  source=manifest["sources"]["host"]
  inputs={"schema_version":1,"toolchains":manifest["toolchains"],"platforms":manifest["platforms"],"sources":{"host":{key:source[key] for key in ("kind","package","version","license_files")}},"profiles":{"pi-fixture":{"engine":"node","source_ids":["host"],"entrypoint":"node_modules/synthetic-host/index.js","npm_resolution_seed":{}}},"build_steps":[]}
  inputs["sources"]["host"]["resources"]={key:[] for key in ("extensions","skills","prompts","themes")};(root/"agents/pi/dependencies.json").write_bytes(payload(inputs));calls=[];monkeypatch.setattr(vendor,"checked",lambda *a,**k:calls.append(a))
  with pytest.raises(ConfigError):vendor.read_inputs(root)
  assert calls==[]


def test_unseeded_modern_retains_original_fresh_resolver(tmp_path, monkeypatch):
  workspace,inputs,path,calls=generator_fixture(tmp_path,monkeypatch)
  assert "npm_resolution_seed" not in inputs["profiles"]["pi-base"]
  lock=PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert len(calls)==3 and lock.validated_bindings["pi-base"].state=="candidate"


def test_legitimate_added_remote_row_count_drift_keeps_prior_manifest(tmp_path, monkeypatch):
  workspace,inputs,path,calls,package,seed,raw,ref=synthetic(tmp_path,monkeypatch);root=workspace.repository
  before=(root/"locks/pi-modern/manifest.json").read_bytes();output=deepcopy(seed)
  output["packages"]["node_modules/extra"]={"version":"1.0.0","resolved":"https://example.invalid/extra.tgz","integrity":"sha512-"+base64.b64encode(b"x"*64).decode()}
  def checked(argv, *, cwd, env):
    calls.append(argv)
    if argv==["node","--version"]:return inputs["toolchains"]["node"]
    if argv==["npm","--version"]:return inputs["toolchains"]["npm"]
    (cwd/"package-lock.json").write_bytes(payload(output));return ""
  monkeypatch.setattr(vendor,"checked",checked)
  reject(lambda:PiBackend(profile="pi-base").resolve_lock(root),code=DRIFT)
  assert len(calls)==3 and (root/"locks/pi-modern/manifest.json").read_bytes()==before


def test_seed_logical_dotdot_remote_node_fails_before_checked(tmp_path, monkeypatch):
  workspace,inputs,path,calls,package,seed,raw,ref=synthetic(tmp_path,monkeypatch);root=workspace.repository
  seed["packages"]["node_modules/../escape"]={"version":"1.0.0","resolved":"https://example.invalid/extra.tgz","integrity":"sha512-"+base64.b64encode(b"x"*64).decode()}
  body=payload(seed);(root/ref["source"]).write_bytes(body);ref["sha256"]=hashlib.sha256(body).hexdigest();path.write_bytes(payload(inputs))
  before=(root/"locks/pi-modern/manifest.json").read_bytes()
  reject(lambda:PiBackend(profile="pi-base").resolve_lock(root))
  assert calls==[] and (root/"locks/pi-modern/manifest.json").read_bytes()==before


@pytest.mark.parametrize("over",[False,True])
def test_scaled_seed_tree_read_limit_before_any_checked(tmp_path,monkeypatch,over):
  workspace,inputs,path,calls,package,seed,raw,ref=synthetic(tmp_path,monkeypatch);root=workspace.repository
  monkeypatch.setattr(helper(),"MAX_SEED",len(raw)-int(over))
  if over:
    reject(helper().load_seed,root,"pi-base",ref,package,inputs["sources"],{}, {})
  else:
    actual,identity=helper().load_seed(root,"pi-base",ref,package,inputs["sources"],{}, {})
    assert actual==raw and identity
  assert calls==[]
