"""Pi 辅助会话观察只投影历史；真实临时claim/部署，假原生child。"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from agentcfg import pi_session_guard as guard, pi_session_observation as observed, run_owners, runtime
from agentcfg.sessions import SessionError
from agentcfg.storage import Tree, Conflict
from test_rotom_pi_session_guard import case, store, source_repo, SESSION, SOURCE, RUN_ID
from test_rotom_pi_run_host import pi, pipeline, fake_npm, recipe_repository, observation, fake_popen, capture, owner


@pytest.fixture
def selected(case):
  claims=case.claims()
  target=case.sessions / ("future_"+SESSION+".jsonl")
  try:
    guard.handle(claims,{"seq":1,"op":"claim","session":SESSION,"file":str(target),"cwd":str(case.store.cwd)})
    yield case,case.ws.state_root / "pi-session-observations" / (RUN_ID+".json"),target
  finally: claims.close()


def read(selected):
  case,_,_=selected
  return observed.from_records(case.ws,case.store.registry.snapshot())


def test_true_guard_observation_is_only_historical_and_never_reads_session_body(selected,monkeypatch):
  case,path,target=selected
  target.write_bytes(b"BODY_MUST_NOT_BE_READ\n"); target.chmod(0o600)
  original=Tree.read
  def metadata_only(tree,name,**kwargs):
    assert tree.root != case.sessions
    return original(tree,name,**kwargs)
  monkeypatch.setattr(Tree,"read",metadata_only)
  before=path.read_bytes()
  known,=read(selected)
  assert known.ref.agent=="pi" and known.ref.native_ref==SESSION and known.run_id==RUN_ID
  assert known.confirmation==known.cwd_status=="historical" and known.cwd==str(case.store.cwd)
  assert known.profile==case.ws.profile and path.read_bytes()==before
  assert case.store.registry.snapshot()[RUN_ID]["session_observation"] is None


@pytest.mark.parametrize("damage",["unknown","schema-bool","run","manager","host","relative-cwd","outside-file","missing-marker","marker-unknown","marker-bool","record-home","workspace-profile"])
def test_malformed_or_cross_scope_auxiliary_metadata_fails_without_repair(selected,damage):
  case,path,_=selected
  value=json.loads(path.read_bytes())
  marker=case.ws.state_root / "pi-session-guards" / (RUN_ID+".json")
  if damage=="unknown": value["extra"]=True
  elif damage=="schema-bool": value["schema_version"]=True
  elif damage=="run": value["run_id"]="b"*32
  elif damage=="manager": value["manager_identity"]["birth_id"]="synthetic-other"
  elif damage=="host": value["host_identity"]["identity"]["birth_id"]="synthetic-other"
  elif damage=="relative-cwd": value["cwd"]="relative"
  elif damage=="outside-file": value["file"]=str(case.store.cwd / "outside.jsonl")
  elif damage=="missing-marker": marker.unlink()
  elif damage.startswith("marker-"):
    row=json.loads(marker.read_bytes())
    if damage=="marker-unknown": row["extra"]=True
    else: row["schema_version"]=True
    marker.write_bytes(run_owners._encode(row))
  elif damage=="record-home":
    row=deepcopy(case.record); row["native_home_ref"]["path"]=str(case.ws.instance / "other-home"); case.write(row)
  else: case.ws.profile="other-profile"
  path.write_bytes(run_owners._encode(value))
  before={p:p.read_bytes() for p in case.ws.state_root.rglob("*.json")}
  with pytest.raises(SessionError) as caught: read(selected)
  assert caught.value.code==4 and before=={p:p.read_bytes() for p in case.ws.state_root.rglob("*.json")}


@pytest.mark.parametrize("kind",["observation-file","guard-file","observation-directory","guard-directory","symlink-directory"])
def test_unsafe_metadata_modes_or_directory_links_are_rejected(selected,kind):
  case,path,_=selected
  guard_dir=case.ws.state_root / "pi-session-guards"
  if kind=="observation-file": path.chmod(0o644)
  elif kind=="guard-file": (guard_dir / (RUN_ID+".json")).chmod(0o644)
  elif kind=="observation-directory": path.parent.chmod(0o755)
  elif kind=="guard-directory": guard_dir.chmod(0o755)
  else:
    retired=guard_dir.with_name("retired-guards"); guard_dir.rename(retired); guard_dir.symlink_to(retired,target_is_directory=True)
  with pytest.raises(SessionError): read(selected)


def test_old_guard_source_and_missing_cwd_remain_historical(selected):
  case,path,_=selected
  marker=case.ws.state_root / "pi-session-guards" / (RUN_ID+".json")
  row=json.loads(marker.read_bytes()); row["source_identity"]="e"*64; marker.write_bytes(run_owners._encode(row))
  value=json.loads(path.read_bytes()); value["cwd"]=str(case.store.cwd / "missing-historical-directory")
  path.write_bytes(run_owners._encode(value))
  known,=read(selected)
  assert known.confirmation=="historical" and known.cwd==value["cwd"]


@pytest.mark.parametrize("phase",["active","unknown","idle_confirmed"])
def test_legacy_pi_owner_without_auxiliary_files_is_not_rewritten_or_inferred(case,phase):
  row=deepcopy(case.record); run_owners._set_state(row,phase); case.write(row)
  marker=case.ws.state_root / "pi-session-guards" / (RUN_ID+".json"); marker.unlink()
  assert observed.from_records(case.ws,case.store.registry.snapshot())==()
  assert case.store.registry.snapshot()[RUN_ID]["session_observation"] is None


def test_current_source_lock_matches_frozen_actual_sources():
  root=Path(guard.__file__).resolve().parents[2]
  assert guard.source_identity()==hashlib.sha256((root / "locks/pi/session-control.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("damage",["missing","hash"])
def test_missing_or_wrong_source_lock_blocks_runtime_before_host(pi,source_repo,fake_popen,damage):
  ws,_,legacy=pi
  repository,lock,value=source_repo
  if damage=="missing": lock.unlink()
  else:
    value["sources"]["src/agentcfg/pi_session_guard.py"]="0"*64; lock.write_bytes(run_owners._encode(value))
  with pytest.raises(Conflict): runtime.run(ws,cwd=ws.local_path.parent)
  assert fake_popen.calls==[] and legacy==[]


def test_new_pi_runtime_injects_public_extension_and_preserves_user_prompt_and_exit(pi,fake_popen):
  ws,_,legacy=pi
  prompt=("--thinking","minimal","--","literal --resume prompt")
  fake_popen.queue(returncode=29)
  assert runtime.run(ws,cwd=ws.local_path.parent,arguments=prompt)==29
  assert len(fake_popen.calls)==1 and legacy==[]
  call=fake_popen.calls[0]; root=Path(guard.__file__).resolve().parents[2]
  extension=str(root / "agents/pi/templates/session-control.mjs")
  assert call["argv"][-len(prompt[-2:]):]==list(prompt[-2:])
  position=call["argv"].index(extension)
  assert call["argv"][position-1]=="-e" and position<call["argv"].index("--")
  assert call["argv"][position-3:position-1]==["--thinking","minimal"]
  context=json.loads(call["env"]["ROTOM_PI_CONTROL_CONTEXT"])
  assert context["run_id"]==owner(ws)["run_id"] and context["initial_session"] is None and context["lease_fd"] is None
  assert len(call["pass_fds"])==2 and fake_popen.children[0].wait_calls==1


@pytest.mark.parametrize("damaged",[False,True])
def test_instances_retains_original_process_when_auxiliary_observation_is_unavailable(pi,fake_popen,monkeypatch,damaged):
  from agentcfg import local,workspace
  ws,_,_=pi
  def wait():
    row=owner(ws); claims=guard.Claims(ws,row["run_id"])
    try:
      guard.handle(claims,{"seq":1,"op":"claim","session":SESSION,"file":str(ws.instance / "pi-home/sessions" / ("future_"+SESSION+".jsonl")),"cwd":str(ws.local_path.parent)})
    finally: claims.close()
  fake_popen.queue(returncode=31,on_wait=wait)
  assert runtime.run(ws,cwd=ws.local_path.parent)==31
  row=owner(ws)
  path=ws.state_root / "pi-session-observations" / (row["run_id"]+".json")
  if damaged: path.write_bytes(b"synthetic-malformed-observation")
  before={p:p.read_bytes() for p in ws.state_root.rglob("*.json")}
  monkeypatch.setattr(local,"available_profiles",lambda:[(ws.profile,"pi")])
  monkeypatch.setattr(workspace,"load_instance_workspaces",lambda path,profiles:[ws])
  result=run_owners.instances(ws.local_path,agent="pi",profile=ws.profile)
  current,=result["instances"]
  assert current["kind"]=="registered" and current["run_id"]==row["run_id"]
  assert current["process"]["ownership_state"]==row["lifecycle_state"]
  assert current["session"]["status"]==("unknown" if damaged else "historical")
  if damaged:
    assert result["incomplete"] is True and result["coverage"][0]["session_observation"]=="unavailable"
  else: assert current["session"]["ref"]["native_ref"]==SESSION
  assert before=={p:p.read_bytes() for p in ws.state_root.rglob("*.json")}


def test_explicit_existing_session_is_leased_before_original_child_and_released_after_wait(pi,fake_popen):
  import fcntl
  ws,_,_=pi
  path=ws.instance / "pi-home/sessions" / ("existing_"+SESSION+".jsonl")
  value={"type":"session","id":SESSION,"version":1,"timestamp":"2026-10-26T00:00:00Z","cwd":str(ws.local_path.parent)}
  path.write_bytes(json.dumps(value).encode()+b"\nPRIVATE_BODY\n"); path.chmod(0o600)
  held=[]
  def wait():
    call=fake_popen.calls[0]; context=json.loads(call["env"]["ROTOM_PI_CONTROL_CONTEXT"])
    assert context["initial_session"]==SESSION and context["lease_fd"] in call["pass_fds"]
    assert len(call["pass_fds"])==3
    position=call["argv"].index("--session")
    assert call["argv"][position+1]==str(path)
    lease=context["lease_fd"]; os.fstat(lease); held.append(lease)
    lock=ws.state_root / "pi-session-claims" / (SESSION+".lock")
    probe=os.open(lock,os.O_RDWR)
    try:
      with pytest.raises(BlockingIOError): fcntl.flock(probe,fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally: os.close(probe)
  fake_popen.queue(returncode=23,on_wait=wait)
  assert runtime.run(ws,cwd=ws.local_path.parent,arguments=("--session",SESSION))==23
  assert len(fake_popen.calls)==1 and len(held)==1
  with pytest.raises(OSError): os.fstat(held[0])
  claim=ws.state_root / "pi-session-claims" / (SESSION+".json")
  assert json.loads(claim.read_bytes())["run_id"]==owner(ws)["run_id"]
