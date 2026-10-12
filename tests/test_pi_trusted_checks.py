"""仅真实临时文件与 fake Host；不执行 checker、Shell 或第三方宿主。"""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.activity import digest
from agentcfg.pi_checks import compile_check, verify_check
from agentcfg.pi_trusted_checks import host_context
from agentcfg.storage import Conflict
from agentcfg.schema import ConfigError


def fixture(tmp_path, *, inline=True):
  project=tmp_path/"candidate";project.mkdir()
  trusted=tmp_path/"trusted";trusted.mkdir()
  exe=tmp_path/"node";exe.write_text("inert checker, never executed");exe.chmod(0o700)
  script=trusted/"check.js";script.write_text("immutable acceptance logic")
  binding={"executable":str(exe),"args":["-e","literal fixed code"] if inline else [str(script)],"project_root":"project",
    "timeout_seconds":5,"foreground":True,"kind":"tests","parser":"json","minimum_tests":1,"inputs":[], "read_roots":["trusted"]}
  if not inline:binding["trusted_inputs"]=[{"root_ref":"trusted","relative_path":"check.js"}]
  instance=tmp_path/"instance";(instance/"pi-home").mkdir(parents=True)
  manifest={"profile_id":"pi-full","engine":"node","options":{"paths":{"roots":{"trusted":{"path":str(trusted)},"project":{"path":str(project)}}},"checks":{"test":binding}},
    "permission_policy":{"rules":[]},"role_bindings":{"task-keeper-writer":{"managed":True,"write_roots":["project"]}}}
  path=instance/"pi-home/agentcfg-manifest.json";path.write_text(json.dumps(manifest))
  calls=[]
  def identify(path):
    calls.append(str(path));info=Path(path).stat()
    return {"workspace_key":"fake","worktree_path":str(path),"git_dir_path":None,"canonical_worktree_identity":{"device":info.st_dev,"inode":info.st_ino,"uid":info.st_uid}}
  host=SimpleNamespace(engine_executable=str(exe),config={"engine":str(exe),"instance_root":str(instance),"instance_id":"private","lock_identity":"locked","slice_identity":"slice","protected_roots":[]},store=SimpleNamespace(workspaces=SimpleNamespace(identify=identify)))
  lease={"lease_id":"a"*32,"grant_generation":1}
  def compile():
    path.write_text(json.dumps(manifest))
    host.config["manifest_digest"]=digest(manifest);host.config["policy_digest"]=digest(manifest["permission_policy"])
    context=host_context(host,manifest,lease,"test",project)
    return compile_check(binding,candidate=project,executable=Path(binding["executable"]),read_roots=[Path(binding["executable"]),trusted],trusted_context=context)
  return SimpleNamespace(project=project,trusted=trusted,exe=exe,script=script,binding=binding,manifest=manifest,manifest_path=path,host=host,compile=compile,calls=calls)


@pytest.mark.parametrize("inline",[True,False])
def test_fixed_inline_or_readonly_external_checker_and_host_workspace_binding(tmp_path,inline):
  f=fixture(tmp_path,inline=inline);check=f.compile();verify_check(check)
  assert f.calls==[str(f.project)]
  assert check["trusted_implementation"]["context"]["checker_id"]=="test"
  assert check["trusted_implementation"]["executable"]["sha256"]
  assert check["result_contract"]["minimum_tests"]==1


@pytest.mark.parametrize("mutation",["executable","script","newfile","symlink","hardlink","root","manifest","minimum-tests"])
def test_admitted_implementation_drift_rejects_before_any_execution(tmp_path,mutation,monkeypatch):
  f=fixture(tmp_path,inline=False)
  if mutation=="newfile":f.binding["trusted_inputs"][0]["relative_path"]="."
  check=f.compile();effects=[]
  monkeypatch.setattr("subprocess.run",lambda *a,**k:effects.append(a))
  if mutation=="executable":f.exe.write_text("changed")
  elif mutation=="script":f.script.write_text("changed")
  elif mutation=="newfile":(f.trusted/"new.js").write_text("new acceptance")
  elif mutation=="symlink":f.script.unlink();f.script.symlink_to(f.exe)
  elif mutation=="hardlink":f.script.unlink();os.link(f.exe,f.script)
  elif mutation=="root":f.trusted.rename(f.trusted.with_name("old"));f.trusted.mkdir();f.script.write_text("immutable acceptance logic")
  elif mutation=="minimum-tests":check["trusted_binding"]["minimum_tests"]=0;check["binding_digest"]=digest({k:v for k,v in check.items() if k!="binding_digest"})
  else:f.manifest["role_bindings"]["task-keeper-writer"]["write_roots"]=[];f.manifest_path.write_text(json.dumps(f.manifest))
  with pytest.raises((Conflict,ConfigError,OSError)):verify_check(check)
  assert effects==[]


@pytest.mark.parametrize("case",["exe-writable","input-writable","missing","unbound","unknown","symlink","hardlink","private","candidate-input"])
def test_unsafe_source_does_not_compile(tmp_path,case,monkeypatch):
  f=fixture(tmp_path,inline=False);effects=[];monkeypatch.setattr("subprocess.run",lambda *a,**k:effects.append(a))
  if case=="exe-writable":f.manifest["role_bindings"]["task-keeper-writer"]["write_roots"]=["project","trusted"];(f.trusted/"node").write_bytes(f.exe.read_bytes());(f.trusted/"node").chmod(0o700);f.exe=f.trusted/"node";f.binding["executable"]=str(f.exe)
  elif case=="input-writable":f.manifest["role_bindings"]["task-keeper-writer"]["write_roots"].append("trusted")
  elif case=="missing":f.binding.pop("trusted_inputs")
  elif case=="unbound":f.binding["read_roots"]=[]
  elif case=="unknown":f.binding["trusted_inputs"][0]["extra"]=True
  elif case=="symlink":f.script.unlink();f.script.symlink_to(f.exe)
  elif case=="hardlink":os.link(f.script,f.trusted/"alias")
  elif case=="private":f.host.config["protected_roots"]=[str(f.trusted)]
  else:(f.project/"accept.js").write_text("mutable logic");f.binding["inputs"]=["accept.js"]
  with pytest.raises((Conflict,ConfigError)):f.compile()
  assert effects==[]


def test_bind_alias_uses_backing_coordinate_not_visible_path(tmp_path,monkeypatch):
  f=fixture(tmp_path,inline=False)
  dev=[os.major(f.project.stat().st_dev),os.minor(f.project.stat().st_dev)]
  table=[{"mountpoint":"/","root":"/","device":dev}, {"mountpoint":str(f.project),"root":"/physical/shared","device":dev}, {"mountpoint":str(f.trusted),"root":"/physical/shared","device":dev}]
  monkeypatch.setattr("agentcfg.pi_trusted_checks._table",lambda:table)
  with pytest.raises(Conflict,match="WRITABLE"):f.compile()


def test_ambiguous_mount_and_scan_caps_fail_closed(tmp_path,monkeypatch):
  f=fixture(tmp_path,inline=False);dev=[os.major(f.project.stat().st_dev),os.minor(f.project.stat().st_dev)]
  monkeypatch.setattr("agentcfg.pi_trusted_checks._table",lambda:[{"mountpoint":"/","root":"/","device":dev}]*2)
  with pytest.raises(Conflict,match="AMBIGUOUS"):f.compile()
  monkeypatch.undo();monkeypatch.setattr("agentcfg.pi_trusted_checks.MAX_BYTES",2)
  with pytest.raises(Conflict,match="LIMIT"):f.compile()


@pytest.mark.parametrize("unsafe",[False,True])
def test_original_resolver_uses_host_scope_and_rejects_before_capability_or_input_write(tmp_path,unsafe,monkeypatch):
  from agentcfg.pi_auxiliary import resolve_auxiliary, check_binding_snapshot
  from agentcfg.storage import Tree
  from agentcfg.deployment import json_bytes
  f=fixture(tmp_path)
  instance=Path(f.host.config["instance_root"]);candidate=instance/"pi-home/task-keeper/worktrees/task";candidate.mkdir(parents=True)
  f.project=candidate;f.manifest["options"]["paths"]["roots"]["project"]["path"]=str(candidate)
  f.manifest["options"]["task_keeper"]={"enabled":True,"project_root":"project","check_ids":["test"]}
  f.manifest["plugins"]=["task-keeper"]
  if unsafe:f.binding["args"]=[str(f.script)];f.binding.pop("trusted_inputs",None)
  f.manifest_path.write_text(json.dumps(f.manifest));f.host.config["manifest_digest"]=digest(f.manifest);f.host.config["policy_digest"]=digest(f.manifest["permission_policy"])
  runtime=tmp_path/"runtime";runtime.mkdir(mode=0o700);state=tmp_path/"state";state.mkdir(mode=0o700)
  with Tree(runtime) as tree:tree.write_state("runtime/commands.json",json_bytes({"programs":{"check":{"kind":"check"}}}))
  repo=tmp_path/"repo";(repo/"scripts").mkdir(parents=True);(repo/"scripts/pi-project-check").write_text("inert helper")
  effects=[];f.host.runtime_root=runtime;f.host.root=state;f.host.repository=repo;f.host.manifest=lambda:f.manifest
  f.host.server=SimpleNamespace(endpoint=tmp_path/"endpoint");f.host.service=SimpleNamespace(issue_capability=lambda *a:effects.append(a) or "synthetic")
  lease={"lease_id":"b"*32,"grant_generation":1,"kind":"check","task_id":"task","planned_workspaces":[{"workspace_key":"fake"}]}
  payload={"check_id":"test","cwd":str(candidate),"task_id":"task"}
  if unsafe:
    payload["contract_digest"]="a"*64
    with pytest.raises(Conflict,match="CHECK_TRUSTED_INPUT_REQUIRED"):resolve_auxiliary(f.host,lease,"check",payload)
    assert effects==[] and not (state/"activity/auxiliary-homes").exists() and not (state/"activity/auxiliary-inputs").exists()
  else:
    # 固定 helper 来源端口只在此默认夹具替身；不执行二进制或 namespace。
    with Tree(runtime) as tree:tree.write_state("bin/pi-bwrap",b"inert selected helper")
    (runtime/"bin/pi-bwrap").chmod(0o700)
    monkeypatch.setattr("agentcfg.pi_pid_namespace.host_namespace_binary",lambda current:runtime/"bin/pi-bwrap")
    payload["contract_digest"]=check_binding_snapshot(f.host,payload)["contract_digest"]
    command=resolve_auxiliary(f.host,lease,"check",payload)
    assert len(effects)==1 and command.cwd==candidate
    assert command.process_scope=="linux-pid-namespace"
    with Tree(state) as tree:value=json.loads(tree.read("activity/auxiliary-inputs/"+lease["lease_id"]+".json")[0])
    verify_check(value["check"])


@pytest.mark.parametrize("field,value",[("minimum_tests",0),("minimum_tests",True),("parser","unknown")])
def test_result_contract_cannot_enter_trusted_binding(tmp_path,field,value):
  f=fixture(tmp_path);f.binding[field]=value
  with pytest.raises(ConfigError):f.compile()


def test_unknown_trusted_schema_field_rejected_and_complete_shape_accepted(tmp_path):
  from agentcfg.pi_catalog import validate
  f=fixture(tmp_path,inline=False);options={"checks":{"test":f.binding}}
  validate("options",options)
  f.binding["trusted_inputs"][0]["authority"]=True
  with pytest.raises(ConfigError):validate("options",options)


def test_new_argv_script_cannot_borrow_unrelated_trusted_file(tmp_path):
  f=fixture(tmp_path,inline=False);mutable=f.project/"bad.js";mutable.write_text("mutable checker")
  f.binding["args"]=[str(mutable)]
  with pytest.raises(Conflict,match="CHECK_TRUSTED_INPUT_REQUIRED"):f.compile()


def test_scan_drift_and_entry_cap_are_not_admitted(tmp_path,monkeypatch):
  f=fixture(tmp_path,inline=False);f.binding["trusted_inputs"][0]["relative_path"]="."
  monkeypatch.setattr("agentcfg.pi_trusted_checks.MAX_ENTRIES",1)
  with pytest.raises(Conflict,match="LIMIT"):f.compile()
  monkeypatch.undo();original=os.read;mutated=[]
  def drift(fd,size):
    raw=original(fd,size)
    if raw==b'immutable acceptance logic' and not mutated:
      mutated.append(True);f.script.write_text("changed during read")
    return raw
  monkeypatch.setattr("agentcfg.pi_trusted_checks.os.read",drift)
  with pytest.raises(Conflict,match="DRIFT"):f.compile()


@pytest.mark.parametrize("invalid",["host-digest","root-ref","permissions","policy"])
def test_host_expected_digest_and_current_denials_cannot_be_replaced_by_binding(tmp_path,invalid):
  f=fixture(tmp_path,inline=False)
  if invalid=="host-digest":
    f.host.config["manifest_digest"]="wrong";f.host.config["policy_digest"]=digest(f.manifest["permission_policy"])
    with pytest.raises(Conflict,match="ADMISSION_STALE"):
      host_context(f.host,f.manifest,{"lease_id":"a","grant_generation":1},"test",f.project)
  elif invalid=="root-ref":
    f.binding["trusted_inputs"][0]["root_ref"]="unknown"
    with pytest.raises(Conflict,match="UNBOUND"):f.compile()
  else:
    if invalid=="permissions":f.manifest["options"]["permissions"]={"denied_roots":["trusted"]}
    else:f.manifest["permission_policy"]["rules"]=[{"kind":"file","effect":"deny","root_ref":"trusted","relative_path":"check.js"}]
    with pytest.raises(Conflict,match="PRIVATE"):f.compile()


def test_original_git_backlink_drift_cannot_reuse_physical_directory_identity(tmp_path):
  f=fixture(tmp_path);git=f.project/".git";git.mkdir();(git/"HEAD").write_text("ref: refs/heads/fixture");(git/"gitdir").write_text("original backlink")
  def identify(path):
    info=f.project.stat();gi=git.stat()
    return {"workspace_key":"original","worktree_path":str(f.project),"git_dir_path":str(git),
      "canonical_worktree_identity":{"device":info.st_dev,"inode":info.st_ino,"uid":info.st_uid},
      "git_dir_identity":{"device":gi.st_dev,"inode":gi.st_ino,"uid":gi.st_uid}}
  f.host.store.workspaces.identify=identify;check=f.compile();verify_check(check)
  (git/"gitdir").write_text("changed backlink")
  with pytest.raises(Conflict,match="CHANGED"):verify_check(check)


def test_policy_root_denial_and_nested_symlink_parent_fail_closed(tmp_path):
  f=fixture(tmp_path,inline=False)
  f.manifest["permission_policy"]["rules"]=[{"kind":"file","effect":"deny","root_ref":"trusted","relative_path":"."}]
  with pytest.raises(Conflict,match="PRIVATE"):f.compile()
  f.manifest["permission_policy"]["rules"]=[]
  alias=f.trusted/"alias";alias.symlink_to(f.trusted,target_is_directory=True)
  f.binding["trusted_inputs"][0]["relative_path"]="alias/check.js"
  with pytest.raises(Conflict,match="CANONICAL"):f.compile()


@pytest.mark.parametrize("args",[["--loader","dynamic.js"],["--require"],["--import="],["--eval","code","extra"],["--","--loader"],["--unknown"]])
def test_unsupported_node_shapes_do_not_borrow_runtime_identity(tmp_path,args):
  f=fixture(tmp_path,inline=False);f.binding["args"]=args
  with pytest.raises((Conflict,OSError)):f.compile()


@pytest.mark.parametrize("prefix",[["--"],["--require"],["--import"],["--require="],["--import="],["-r"]])
def test_proven_runtime_engine_fixed_script_and_imports_preserve_subject_arguments(tmp_path,prefix):
  f=fixture(tmp_path,inline=False);subject=f.project/"subject.js";subject.write_text("mutable source under test")
  value=prefix[0]
  if value=="--":args=[value,str(f.script)]
  elif value.endswith("="):args=[value+str(f.script),str(f.script)]
  else:args=[value,str(f.script),str(f.script)]
  f.binding["args"]=[*args,str(subject)];verify_check(f.compile())


def test_unproven_named_node_cannot_use_literal_inline_exception(tmp_path):
  f=fixture(tmp_path);other=f.trusted/"node";other.write_text("different inert executable");other.chmod(0o700);f.exe=other;f.binding["executable"]=str(other)
  with pytest.raises(Conflict,match="REQUIRED"):f.compile()


def test_explicit_external_implementation_allows_subject_path_without_trust_promotion(tmp_path):
  f=fixture(tmp_path,inline=False);external=f.trusted/"checker";external.write_text("inert own checker implementation");external.chmod(0o700)
  f.exe=external;f.binding["executable"]=str(external);f.binding["trusted_inputs"]=[{"root_ref":"trusted","relative_path":"checker"}]
  subject=f.project/"subject.py";subject.write_text("mutable source under test");f.binding["args"]=[str(subject)]
  check=f.compile();verify_check(check)
  assert all(row["path"]!=str(subject) for row in check["trusted_implementation"]["trusted_inputs"])


def test_unknown_external_implementation_and_nonlinux_mounts_fail_closed(tmp_path,monkeypatch):
  f=fixture(tmp_path,inline=False);other=f.trusted/"fake-python";other.write_text("different implementation");other.chmod(0o700)
  f.binding["executable"]=str(other)
  with pytest.raises(Conflict,match="UNVERIFIABLE"):f.compile()
  monkeypatch.setattr("agentcfg.pi_trusted_checks.sys.platform","darwin")
  with pytest.raises(ConfigError,match="UNSUPPORTED"):f.compile()
