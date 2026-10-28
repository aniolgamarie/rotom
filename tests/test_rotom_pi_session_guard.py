"""Pi 合作 writer 保护：真实临时flock/claim，仅合成manager/host，不启动Pi。"""
from copy import deepcopy
import errno
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import pi_session_guard as guard, pi_session_helper as helper, run_owners
from agentcfg.adapter import LaunchSpec
from agentcfg.sessions import SessionError
from agentcfg.storage import Conflict, Tree
from test_rotom_run_records import MANAGER, RUN_ID, store, v2_record


SESSION = "12345678-1234-1234-1234-123456789abc"
SECOND = "12345678-1234-1234-1234-123456789abd"
SOURCE = "d" * 64
HOST = {"identity": {"pid": MANAGER["pid"]+1, "birth_id": "synthetic-pi-host"},
  "manager_identity": MANAGER, "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}


@pytest.fixture
def case(store, monkeypatch):
  instance = store.registry.root.parent / "instance"
  sessions = instance / "pi-home/sessions"
  sessions.mkdir(mode=0o700, parents=True)
  ws = SimpleNamespace(agent="pi", instance=instance, state_root=store.registry.root.parent,
    profile=store.binding["profile"], binding=store.binding)
  record = v2_record(store)
  record.update(agent="pi", host_identity=deepcopy(HOST))
  record["native_home_ref"].update(kind="pi-home", path=str(instance / "pi-home"))
  record["process_observation"]["host_identity"] = deepcopy(HOST)
  store.registry.root.mkdir(mode=0o700, exist_ok=True)
  def write(row):
    path = store.registry.root / (row["run_id"]+".json")
    path.write_bytes(run_owners._encode(row)); path.chmod(0o600)
    return path
  write(record)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  monkeypatch.setattr(run_owners, "observed_process_identity", lambda pid: deepcopy(HOST["identity"]) if pid == HOST["identity"]["pid"] else None)
  monkeypatch.setattr(guard, "source_identity", lambda: SOURCE)
  guard.register(ws, RUN_ID)
  def add(run="b" * 32, *, phase="active", registered=True):
    row = deepcopy(record); row["run_id"] = run
    run_owners._set_state(row, phase)
    write(row)
    if registered:
      with Tree(ws.state_root / "pi-session-guards") as tree:
        tree.write_new(run+".json", run_owners._encode(guard._guard_record(row, SOURCE)))
    return row
  return SimpleNamespace(ws=ws, store=store, record=record, sessions=sessions, write=write, add=add,
    claims=lambda run=RUN_ID, **kwargs: guard.Claims(ws, run, **kwargs))


def header(case, identifier=SESSION, *, cwd=None, body=b"PRIVATE_BODY_SENTINEL\n"):
  path = case.sessions / ("2026-10-26T00-00-00_"+identifier+".jsonl")
  value = {"type":"session", "id":identifier, "version":1, "timestamp":"2026-10-26T00:00:00Z", "cwd":str(cwd or case.store.cwd)}
  path.write_bytes(json.dumps(value).encode()+b"\n"+body); path.chmod(0o600)
  return path


def metadata(case, identifier=SESSION):
  return case.ws.state_root / "pi-session-claims" / (identifier+".json")


def test_precise_flock_and_durable_owner_protect_until_confirmed_idle(case):
  case.add()
  first, other = case.claims(), case.claims("b" * 32)
  try:
    fd = first.claim(SESSION)
    with pytest.raises((BlockingIOError, Conflict)): other.claim(SESSION)
    first.close()
    os.fstat(other.claim(SECOND))
    with pytest.raises(Conflict): other.claim(SESSION)
    row = deepcopy(case.record); run_owners._set_state(row, "unknown"); case.write(row)
    with pytest.raises(Conflict): other.claim(SESSION)
    run_owners._set_state(row, "idle_confirmed"); case.write(row)
    os.fstat(other.claim(SESSION))
    assert json.loads(metadata(case).read_bytes())["run_id"] == "b" * 32
  finally:
    first.close(); other.close()


def test_real_live_claim_contention_is_fixed_conflict_and_preserves_original_metadata(case):
  case.add()
  first, other = case.claims(), case.claims("b" * 32)
  try:
    fd = first.claim(SESSION)
    before = metadata(case).read_bytes()
    with pytest.raises(Conflict) as caught:
      other.claim(SESSION)
    assert caught.value.exit_code == 4 and other.fds == {}
    assert metadata(case).read_bytes() == before
    os.fstat(fd)
  finally:
    first.close(); other.close()


def test_claim_body_blocking_io_error_is_not_reclassified_as_lease_contention(case, monkeypatch):
  claims = case.claims()
  replace = Tree.replace
  error = BlockingIOError(errno.EAGAIN, "synthetic-commit-response-loss")
  writes = []
  def lost(tree, name, data, **kwargs):
    if tree.root.name == "pi-session-claims":
      writes.append(name)
      replace(tree, name, data, **kwargs)
      raise error
    return replace(tree, name, data, **kwargs)
  monkeypatch.setattr(Tree, "replace", lost)
  try:
    with pytest.raises(BlockingIOError) as caught:
      claims.claim(SESSION)
    assert caught.value is error and writes == [SESSION + ".json"]
    assert metadata(case).exists() and claims.fds == {}
  finally:
    claims.close()


def test_inherited_same_run_fd_is_duplicated_and_close_never_unlocks_borrowed_lease(case):
  manager, helper_claims = case.claims(), case.claims()
  try:
    fd = manager.claim(SESSION)
    copied = helper_claims.claim(SESSION, inherited_fd=fd)
    assert copied != fd
    helper_claims.close(); os.fstat(fd)
    probe = os.open(case.ws.state_root / "pi-session-claims" / (SESSION+".lock"), os.O_RDWR)
    try:
      with pytest.raises(BlockingIOError): fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally: os.close(probe)
  finally: manager.close(); helper_claims.close()


@pytest.mark.parametrize("damage", ["wrong-fd", "replaced-lock", "metadata", "replaced-metadata"])
def test_wrong_fd_or_changed_claim_never_grants_or_rewrites(case, damage):
  original, additional = case.claims(), case.claims()
  borrowed = None
  try:
    fd = original.claim(SESSION)
    if damage == "wrong-fd":
      borrowed = os.open(case.store.cwd, os.O_RDONLY | os.O_DIRECTORY)
      with pytest.raises(Conflict): additional.claim(SESSION, inherited_fd=borrowed)
      os.fstat(borrowed)
    elif damage == "replaced-lock":
      path = case.ws.state_root / "pi-session-claims" / (SESSION+".lock")
      path.rename(path.with_suffix(".retired")); path.write_bytes(b""); path.chmod(0o600)
      with pytest.raises(Conflict): original.claim(SESSION)
    else:
      path = metadata(case)
      payload = path.read_bytes()
      if damage == "metadata":
        row = json.loads(payload); row["unexpected"] = "synthetic-canary"; payload = run_owners._encode(row)
      path.unlink(); path.write_bytes(payload); path.chmod(0o600)
      before = path.read_bytes()
      with pytest.raises(Conflict): original.claim(SESSION)
      assert path.read_bytes() == before
  finally:
    if borrowed is not None: os.close(borrowed)
    original.close(); additional.close()


@pytest.mark.parametrize("phase,registered", [("active",False),("unknown",False)])
def test_legacy_unguarded_nonidle_owner_blocks_new_session(case, phase, registered):
  case.add(phase=phase, registered=registered)
  claims = case.claims()
  try:
    with pytest.raises(Conflict): claims.claim(SESSION)
    assert not metadata(case).exists()
  finally: claims.close()


def test_claim_is_durable_before_current_session_observation(case, monkeypatch):
  claims = case.claims()
  target = case.sessions / ("future_"+SESSION+".jsonl")
  request = {"seq":1,"op":"claim","session":SESSION,"file":str(target),"cwd":str(case.store.cwd)}
  original = Tree.replace
  trace=[]
  def replace(tree,name,data,**kwargs):
    if tree.root.name == "pi-session-observations":
      assert metadata(case).exists() and SESSION in claims.fds
      trace.append("observation")
    return original(tree,name,data,**kwargs)
  monkeypatch.setattr(Tree,"replace",replace)
  try:
    guard.handle(claims,request)
    saved=json.loads((case.ws.state_root / "pi-session-observations" / (RUN_ID+".json")).read_bytes())
    assert saved["session_id"] == SESSION and saved["file"] == str(target) and trace == ["observation"]
    assert not target.exists()
  finally: claims.close()


def test_prepare_header_claim_reads_only_first_line(case, monkeypatch):
  path=header(case,body=b"SENTINEL_BODY_MUST_NOT_BE_READ\n")
  claims=case.claims()
  original=os.read
  observed=bytearray()
  def read(fd,count):
    result=original(fd,count)
    observed.extend(result)
    return result
  monkeypatch.setattr(os,"read",read)
  try:
    guard.handle(claims,{"seq":1,"op":"prepare","file":str(path)})
    assert SESSION in claims.fds and b"SENTINEL_BODY" not in observed
    assert not (case.ws.state_root / "pi-session-observations").exists()
  finally: claims.close()


@pytest.mark.parametrize("args", [("--resume",),("-r",),("--session",),("--session",SESSION,"--session",SESSION),("--session="+SESSION,"--session="+SESSION)])
def test_ambiguous_or_incomplete_arguments_fail_with_fixed_session_error(case,args):
  header(case)
  spec=LaunchSpec(("node","synthetic",*args),case.store.cwd,"a"*64,())
  # prepare 自己登记本run；避免将已有guard重放冲突误当作参数拒绝。
  (case.ws.state_root / "pi-session-guards" / (RUN_ID+".json")).unlink()
  with pytest.raises(SessionError):
    with guard.prepare(case.ws,spec,{},(),run_id=RUN_ID,arguments=args): pytest.fail("歧义参数不得启动")


@pytest.mark.parametrize("inline", [False,True])
@pytest.mark.parametrize("suffix", [(), ("--", "--session=literal-prompt")])
def test_exact_session_argument_is_mapped_to_original_path_and_leased_before_yield(case,inline,suffix):
  path=header(case)
  args=(("--session="+SESSION,) if inline else ("--session",SESSION))+suffix
  spec=LaunchSpec(("node","synthetic",*args),case.store.cwd,"a"*64,())
  (case.ws.state_root / "pi-session-guards" / (RUN_ID+".json")).unlink()
  borrowed=os.open(case.store.cwd,os.O_RDONLY | os.O_DIRECTORY)
  try:
    with guard.prepare(case.ws,spec,{"SYNTHETIC":"kept"},(borrowed,),run_id=RUN_ID,arguments=args) as (changed,env,fds):
      option=changed.argv.index("--session")
      assert changed.argv[option:option+2] == ("--session",str(path))
      assert "--session="+str(path) not in changed.argv
      if suffix:
        assert changed.argv[-len(suffix):] == suffix
      assert env["SYNTHETIC"] == "kept" and json.loads(env["ROTOM_PI_CONTROL_CONTEXT"])["initial_session"] == SESSION
      assert borrowed in fds and len(fds)==2 and metadata(case).exists()
      lease=fds[-1]; os.fstat(lease)
    os.fstat(borrowed)
    with pytest.raises(OSError): os.fstat(lease)
  finally: os.close(borrowed)


def test_close_attempts_all_owned_fds_on_failure(case,monkeypatch):
  claims=case.claims(); first=claims.claim(SESSION); second=claims.claim(SECOND)
  original=os.close; closed=[]
  def close(fd):
    original(fd); closed.append(fd)
    if fd==first: raise OSError("synthetic-close-response-loss")
  monkeypatch.setattr(os,"close",close)
  with pytest.raises(OSError): claims.close()
  assert closed == [first,second] and claims.fds == {}


def test_helper_requires_original_host_parent_even_for_ping(case,monkeypatch):
  monkeypatch.setattr(os,"getppid",lambda: HOST["identity"]["pid"]+100)
  claims=case.claims(helper=True)
  with pytest.raises(Conflict): guard.handle(claims,{"seq":1,"op":"ping"})


@pytest.fixture
def source_repo(tmp_path,monkeypatch):
  repository=tmp_path / "source-repository"
  files=["agents/pi/templates/session-control.mjs","src/agentcfg/pi_session_guard.py","src/agentcfg/pi_session_helper.py"]
  actual=Path(__file__).resolve().parents[1]
  for name in files:
    path=repository/name; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((actual/name).read_bytes()); path.chmod(0o600)
  value={"version":1,"protocol":guard._PROTOCOL,"official":{"package":"@earendil-works/pi-coding-agent","version":"1.3.0"},
    "sources":{name:hashlib.sha256((repository/name).read_bytes()).hexdigest() for name in files}}
  lock=repository / "locks/pi/session-control.json"; lock.parent.mkdir(parents=True)
  lock.write_bytes(run_owners._encode(value)); lock.chmod(0o600)
  monkeypatch.setattr(guard,"__file__",str(repository / files[1]))
  return repository,lock,value


def test_source_identity_checks_actual_three_sources(source_repo):
  repository,lock,value=source_repo
  assert guard.source_identity() == hashlib.sha256(lock.read_bytes()).hexdigest()
  for name in value["sources"]:
    path=repository/name; before=path.read_bytes(); path.write_bytes(before+b"\n")
    with pytest.raises(Conflict): guard.source_identity()
    path.write_bytes(before)


@pytest.mark.parametrize("damage",["version-bool","bad-json","sources-list","extra"])
def test_source_lock_rejects_malformed_values_with_fixed_conflict(source_repo,damage):
  repository,lock,value=source_repo
  if damage=="version-bool": value["version"]=True
  elif damage=="sources-list": value["sources"]=list(value["sources"])
  elif damage=="extra": value["unexpected"]="synthetic-canary"
  lock.write_bytes(b"not-json" if damage=="bad-json" else run_owners._encode(value))
  with pytest.raises(Conflict): guard.source_identity()


def test_current_and_other_nonidle_guards_must_match_locked_sources(case,monkeypatch):
  case.add()
  marker=case.ws.state_root / "pi-session-guards" / ("b"*32+".json")
  value=json.loads(marker.read_bytes()); value["source_identity"]="e"*64
  marker.write_bytes(run_owners._encode(value))
  claims=case.claims()
  try:
    with pytest.raises(Conflict): claims.claim(SESSION)
    row=case.store.registry.snapshot()["b"*32]; run_owners._set_state(row,"idle_confirmed"); case.write(row)
    fd=claims.claim(SESSION)
    monkeypatch.setattr(guard,"source_identity",lambda: "e"*64)
    with pytest.raises(Conflict): claims.claim(SESSION)
    os.fstat(fd)
  finally: claims.close()


def test_guard_marker_same_bytes_replacement_does_not_extend_current_claim(case):
  claims=case.claims()
  try:
    claims.claim(SESSION)
    marker=case.ws.state_root / "pi-session-guards" / (RUN_ID+".json")
    payload=marker.read_bytes(); marker.unlink(); marker.write_bytes(payload); marker.chmod(0o600)
    with pytest.raises(Conflict): claims.claim(SECOND)
    assert not metadata(case,SECOND).exists()
  finally: claims.close()


@pytest.mark.parametrize("change",["outside","relative","wrong-id","cwd"])
def test_invalid_current_session_path_or_cwd_never_claims(case,change):
  path=header(case)
  value={"seq":1,"op":"claim","session":SESSION,"file":str(path),"cwd":str(case.store.cwd)}
  if change=="outside": value["file"]=str(case.store.cwd / path.name)
  elif change=="relative": value["file"]="relative.jsonl"
  elif change=="wrong-id": value["session"]=SECOND
  else: value["cwd"]=str(case.ws.instance)
  claims=case.claims()
  try:
    with pytest.raises((Conflict,SessionError,ValueError)): guard.handle(claims,value)
    assert claims.fds=={} and not metadata(case).exists()
  finally: claims.close()


def helper_context(case,**extra):
  return {"state_root":str(case.ws.state_root),"instance":str(case.ws.instance),
    "profile":case.ws.profile,"binding":case.ws.binding,"run_id":RUN_ID,
    "initial_session":None,"lease_fd":None,**extra}


def invoke_helper(case,monkeypatch,*,line=b'{"seq":1,"op":"ping"}\n',context=None):
  output=io.StringIO()
  with monkeypatch.context() as patch:
    patch.setenv("ROTOM_PI_CONTROL_CONTEXT",json.dumps(context or helper_context(case)))
    patch.setattr(helper.sys,"stdin",SimpleNamespace(buffer=io.BytesIO(line)))
    patch.setattr(helper.sys,"stdout",output)
    result=helper.main()
  return result,output.getvalue()


@pytest.fixture
def helper_clock(case,monkeypatch):
  state=SimpleNamespace(now=0.0,sleeps=[],action=lambda:None)
  monkeypatch.setattr(helper.os,"getppid",lambda: HOST["identity"]["pid"])
  monkeypatch.setattr(helper.time,"monotonic",lambda: state.now)
  def sleep(value):
    state.sleeps.append(value); state.now+=value; state.action()
  monkeypatch.setattr(helper.time,"sleep",sleep)
  return state


@pytest.mark.parametrize("kind",["already-bound","delayed","timeout","wrong-host","wrong-source"])
def test_helper_readonly_wait_is_bounded_and_only_for_unbound_original_host(case,helper_clock,monkeypatch,kind):
  if kind in ("delayed","timeout"):
    row=deepcopy(case.record); row["host_identity"]=None; row["process_observation"]["host_identity"]=None; case.write(row)
  if kind=="delayed": helper_clock.action=lambda: case.write(case.record)
  elif kind=="wrong-host":
    row=deepcopy(case.record); row["host_identity"]["identity"]["pid"]+=1
    row["process_observation"]["host_identity"]=deepcopy(row["host_identity"]); case.write(row)
  elif kind=="wrong-source": monkeypatch.setattr(guard,"source_identity",lambda: "e"*64)
  rc,output=invoke_helper(case,monkeypatch)
  if kind in ("already-bound","delayed"):
    assert rc==0 and json.loads(output)=={"seq":1,"ok":True}
  else: assert rc==4 and output==""
  if kind=="timeout": assert 1.99 <= helper_clock.now <= 2.0
  elif kind!="delayed": assert helper_clock.sleeps==[]
  assert all(0<delay<=0.02 for delay in helper_clock.sleeps)
  assert not (case.ws.state_root / "pi-session-claims").exists()


@pytest.mark.parametrize("line",[b'{"seq":2,"op":"ping"}\n',b'{"seq":1,"op":"ping","extra":true}\n',b'{"seq":1,"seq":1,"op":"ping"}\n',b'x'*16385+b'\n',b'{"seq":1,"op":"ping"}'])
def test_helper_rejects_malformed_protocol_once_without_echo(case,helper_clock,monkeypatch,line):
  rc,output=invoke_helper(case,monkeypatch,line=line)
  assert rc==4 and json.loads(output)=={"seq":1,"ok":False}
  assert not (case.ws.state_root / "pi-session-claims").exists()


def test_prepare_keeps_prompt_separator_and_closes_owned_fd_on_body_exception(case,monkeypatch):
  path=header(case)
  target=guard.lookup(case.ws,SESSION)
  (case.ws.state_root / "pi-session-guards" / (RUN_ID+".json")).unlink()
  args=("--","--session",SECOND)
  spec=LaunchSpec(("node","synthetic","--session",str(path),*args),case.store.cwd,"a"*64,())
  error=KeyboardInterrupt("synthetic-body-exception")
  with pytest.raises(KeyboardInterrupt) as caught:
    with guard.prepare(case.ws,spec,{},(),run_id=RUN_ID,arguments=args,target=target) as (changed,env,fds):
      assert changed.argv[-len(args):]==args
      assert changed.argv.index("-e")<changed.argv.index("--")
      fd=fds[-1]; raise error
  assert caught.value is error
  with pytest.raises(OSError): os.fstat(fd)


_FORK=os.fork


def test_forked_helper_death_keeps_durable_claim_until_owner_idle(case):
  case.add()
  read,write=os.pipe()
  pid=_FORK()
  if pid==0:
    os.close(read)
    try:
      claims=case.claims(); claims.claim(SESSION)
      os.write(write,b"claimed")
      os._exit(0)
    except BaseException: os._exit(7)
  os.close(write)
  try:
    assert os.read(read,32)==b"claimed"
    assert os.waitpid(pid,0)[1]==0
  finally: os.close(read)
  assert metadata(case).exists()
  other=case.claims("b"*32)
  try:
    with pytest.raises(Conflict): other.claim(SESSION)
    row=deepcopy(case.record); run_owners._set_state(row,"idle_confirmed"); case.write(row)
    os.fstat(other.claim(SESSION))
  finally: other.close()


@pytest.mark.parametrize("damage",["manager-as-host","untrusted-source"])
def test_helper_cannot_treat_manager_or_untrusted_identity_as_original_host(case,monkeypatch,damage):
  row=deepcopy(case.record)
  if damage=="manager-as-host": row["host_identity"]["identity"]=deepcopy(MANAGER)
  else: row["host_identity"]["source"]="historical-unconfirmed"
  row["process_observation"]["host_identity"]=deepcopy(row["host_identity"]); case.write(row)
  parent=row["host_identity"]["identity"]
  monkeypatch.setattr(os,"getppid",lambda: parent["pid"])
  monkeypatch.setattr(run_owners,"observed_process_identity",lambda pid: deepcopy(parent))
  with pytest.raises(Conflict): case.claims(helper=True)._owner()


def test_inherited_fd_three_roundtrip_uses_anonymous_pipes_and_preserves_manager_lock(case):
  header(case)
  claims=case.claims(); borrowed=claims.claim(SESSION)
  input_read,input_write=os.pipe(); output_read,output_write=os.pipe()
  pid=_FORK()
  if pid==0:
    try:
      os.close(input_write); os.close(output_read)
      os.dup2(borrowed,3)
      os.environ["ROTOM_PI_CONTROL_CONTEXT"]=json.dumps(helper_context(case,initial_session=SESSION,lease_fd=3))
      helper.os.getppid=lambda: HOST["identity"]["pid"]
      helper.sys.stdin=SimpleNamespace(buffer=os.fdopen(input_read,"rb",buffering=0))
      helper.sys.stdout=os.fdopen(output_write,"w",buffering=1)
      result=helper.main(); helper.sys.stdout.flush(); os._exit(result)
    except BaseException: os._exit(7)
  os.close(input_read); os.close(output_write)
  try:
    os.write(input_write,b'{"seq":1,"op":"ping"}\n'); os.close(input_write)
    assert json.loads(os.read(output_read,4096))=={"seq":1,"ok":True}
    assert os.waitpid(pid,0)[1]==0
    os.fstat(borrowed)
    probe=os.open(case.ws.state_root / "pi-session-claims" / (SESSION+".lock"),os.O_RDWR)
    try:
      with pytest.raises(BlockingIOError): fcntl.flock(probe,fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally: os.close(probe)
  finally:
    os.close(output_read); claims.close()


@pytest.mark.parametrize("change",["cwd","duplicate-target","bad-argv"])
def test_trusted_target_cannot_conflict_with_user_selection_or_cwd(case,change):
  path=header(case); target=guard.lookup(case.ws,SESSION)
  args=("--session",SECOND) if change=="duplicate-target" else ("--session",SESSION) if change=="bad-argv" else ()
  argv=("node","synthetic") if change=="bad-argv" else ("node","synthetic","--session",str(path),*args)
  spec=LaunchSpec(argv,case.ws.instance if change=="cwd" else case.store.cwd,"a"*64,())
  with pytest.raises(SessionError):
    with guard.prepare(case.ws,spec,{},(),run_id=RUN_ID,arguments=args,target=None if change=="bad-argv" else target): pass


def test_prepare_cleanup_failure_does_not_mask_body_exception(case,monkeypatch):
  header(case); target=guard.lookup(case.ws,SESSION)
  (case.ws.state_root / "pi-session-guards" / (RUN_ID+".json")).unlink()
  spec=LaunchSpec(("node","synthetic","--session",str(target.path)),case.store.cwd,"a"*64,())
  original=guard.Claims.close
  def close(claims): original(claims); raise OSError("synthetic-close-error")
  monkeypatch.setattr(guard.Claims,"close",close)
  problem=ValueError("synthetic-body-error")
  with pytest.raises(ValueError) as caught:
    with guard.prepare(case.ws,spec,{},(),run_id=RUN_ID,target=target): raise problem
  assert caught.value is problem


@pytest.mark.parametrize("committed",[False,True])
def test_claim_write_failure_closes_new_fd_and_preserves_possible_commit(case,monkeypatch,committed):
  case.add()
  claims=case.claims(); seen=[]
  original_flock,original_replace=fcntl.flock,Tree.replace
  def flock(fd,mode):
    if mode==fcntl.LOCK_EX | fcntl.LOCK_NB: seen.append(fd)
    return original_flock(fd,mode)
  def replace(tree,name,data,**kwargs):
    if tree.root.name=="pi-session-claims" and name==SESSION+".json":
      if committed: original_replace(tree,name,data,**kwargs)
      raise OSError("synthetic-claim-commit-response-loss")
    return original_replace(tree,name,data,**kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(fcntl,"flock",flock); patch.setattr(Tree,"replace",replace)
    with pytest.raises(OSError): claims.claim(SESSION)
  assert claims.fds=={} and len(seen)==1
  with pytest.raises(OSError): os.fstat(seen[0])
  assert metadata(case).exists() is committed
  other=case.claims("b"*32)
  try:
    if committed:
      with pytest.raises(Conflict): other.claim(SESSION)
    else: os.fstat(other.claim(SESSION))
  finally: claims.close(); other.close()


def test_isolated_helper_script_imports_stdlib_without_context_or_stderr(isolated_environment):
  # 只执行仓库自有 helper；绝不放开第三方宿主或通用 subprocess 权限。
  import subprocess
  import sys
  from conftest import _REAL_POPEN
  script=Path(guard.__file__).resolve().with_name("pi_session_helper.py")
  child=_REAL_POPEN([sys.executable,"-I","-B",str(script)],
    cwd=isolated_environment.cwd,env=isolated_environment.env,
    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  output,error=child.communicate(timeout=10)
  assert child.returncode==4 and output==error==b""
