"""Pi 合作会话写入保护；只约束使用本协议启动的 Rotom 实例。

租约丢失不会清除持久归属：原 run 未确认 idle 时其它 run 仍不得接管。
它不宣称约束绕过 Rotom 的外部 Pi，也不提供实际加载或继续许可。
"""
from contextlib import contextmanager
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from . import run_owners
from .omp_lifecycle import _same_file
from .sessions import SessionError
from .storage import Conflict, Tree, sync_directory_ancestors
from .tool_session_headers import candidates, lookup, recheck


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ERROR = "Pi 会话写入归属不能确认；请先停止相关实例或在官方界面人工核验"
_PROTOCOL = "rotom-pi-session-claims-v1"


def _read(tree, name):
  try:
    raw = tree.read(name, max_bytes=16384)
    if raw is None:
      return None
    if raw[1] != 0o600:
      raise ValueError()
    return json.loads(raw[0], object_pairs_hook=run_owners._pairs,
      parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant), raw[2]
  except Exception:
    raise Conflict(_ERROR) from None


def source_identity():
  try:
    root = Path(__file__).resolve().parents[2]
    with Tree(root, private=False) as tree:
      raw = tree.read("locks/pi/session-control.json", max_bytes=16384)
      if raw is None:
        raise Conflict(_ERROR)
      value = json.loads(raw[0], object_pairs_hook=run_owners._pairs)
      files = {"agents/pi/templates/session-control.mjs", "src/agentcfg/pi_session_guard.py", "src/agentcfg/pi_session_helper.py"}
      if (type(value) is not dict or set(value) != {"version", "protocol", "official", "sources"}
          or type(value["version"]) is not int or value["version"] != 1 or value["protocol"] != _PROTOCOL
          or value["official"] != {"package": "@earendil-works/pi-coding-agent", "version": "1.3.0"}
          or type(value["sources"]) is not dict or set(value["sources"]) != files):
        raise Conflict(_ERROR)
      for name in files:
        source = tree.read(name, max_bytes=1024 * 1024)
        if source is None or hashlib.sha256(source[0]).hexdigest() != value["sources"][name]:
          raise Conflict(_ERROR)
      return hashlib.sha256(raw[0]).hexdigest()
  except Exception:
    raise Conflict(_ERROR) from None


def _registry(workspace):
  return run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)


def _current(workspace, run_id):
  record = _registry(workspace).snapshot().get(run_id)
  if (record is None or record.get("schema_version") != 2 or record["agent"] != "pi"
      or record["backend"] != "managed" or record["lifecycle_state"] != "active"
      or record["native_home_ref"]["path"] != str(workspace.instance / "pi-home")):
    raise Conflict(_ERROR)
  return record


def _guard_record(record, identity):
  return {"schema_version": 1, "protocol": _PROTOCOL, "run_id": record["run_id"],
    "manager_identity": record["manager_identity"], "source_identity": identity}


def _verify_guard(workspace, record):
  with Tree(workspace.state_root / "pi-session-guards") as tree:
    value = _read(tree, record["run_id"] + ".json")
  if value is None or type(value[0]) is not dict:
    raise Conflict(_ERROR)
  expected = _guard_record(record, source_identity())
  if run_owners._encode(value[0]) != run_owners._encode(expected):
    raise Conflict(_ERROR)
  return value[1]


def register(workspace, run_id):
  record = _current(workspace, run_id)
  if record["manager_identity"] != run_owners.current_process_identity():
    raise Conflict(_ERROR)
  value = _guard_record(record, source_identity())
  with Tree(workspace.state_root / "pi-session-guards", create=True) as tree:
    tree.write_new(run_id + ".json", run_owners._encode(value))
    sync_directory_ancestors(tree.root)
    if _read(tree, run_id + ".json")[0] != value:
      raise Conflict(_ERROR)


class Claims:
  """原 manager 或其直接官方宿主的 helper 持有；不从布尔状态恢复排他。"""

  def __init__(self, workspace, run_id, *, helper=False):
    self.workspace, self.run_id, self.helper = workspace, run_id, helper
    run_owners._run_id(run_id)
    self.fds = {}
    self.metadata = {}
    self.guard_identity = None
    self.root = workspace.state_root / "pi-session-claims"

  def _owner(self):
    record = _current(self.workspace, self.run_id)
    marker = _verify_guard(self.workspace, record)
    if self.guard_identity is not None and marker != self.guard_identity:
      raise Conflict(_ERROR)
    if self.helper:
      host = record["host_identity"]
      if (host is None or host["identity"]["pid"] != os.getppid()
          or host["identity"]["pid"] == record["manager_identity"]["pid"]
          or host["source"] != "linux-spawn-pidfd" or host["relationship"] != "reported-by-current-run"
          or run_owners.observed_process_identity(os.getppid()) != host["identity"]):
        raise Conflict(_ERROR)
    elif record["manager_identity"] != run_owners.current_process_identity():
      raise Conflict(_ERROR)
    self.guard_identity = marker
    return record

  def claim(self, identifier, *, inherited_fd=None):
    if type(identifier) is not str or _UUID.fullmatch(identifier) is None:
      raise Conflict(_ERROR)
    record = self._owner()
    if identifier in self.fds:
      with Tree(self.root) as tree:
        _same_file(tree, identifier + ".lock", self.fds[identifier])
        current = _read(tree, identifier + ".json")
        expected, identity = self.metadata[identifier]
        if (current is None or current[1] != identity
            or run_owners._encode(current[0]) != run_owners._encode(expected)):
          raise Conflict(_ERROR)
      return self.fds[identifier]
    if len(self.fds) >= 1024:
      raise Conflict(_ERROR)
    # 旧运行未安装公开扩展时不能推导它没有打开目标 session。
    for prior in _registry(self.workspace).snapshot().values():
      if run_owners.record_state(prior) != "idle_confirmed":
        if prior.get("schema_version") != 2 or prior["agent"] != "pi":
          raise Conflict(_ERROR)
        _verify_guard(self.workspace, prior)
    with Tree(self.root, create=True) as tree:
      fd = None
      try:
        if inherited_fd is not None:
          if type(inherited_fd) is not int or inherited_fd < 0:
            raise Conflict(_ERROR)
          _same_file(tree, identifier + ".lock", inherited_fd)
          fd = os.dup(inherited_fd)
        else:
          with tree.parent(identifier + ".lock") as (parent, leaf):
            fd = os.open(leaf, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=parent)
          _same_file(tree, identifier + ".lock", fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prior = _read(tree, identifier + ".json")
        home = run_owners.native_home_key(record["native_home_ref"])
        expected = {"schema_version": 1, "protocol": _PROTOCOL, "session_id": identifier,
          "native_home_key": home, "run_id": self.run_id, "manager_identity": record["manager_identity"]}
        matches = prior is not None and run_owners._encode(prior[0]) == run_owners._encode(expected)
        if prior is not None and not matches:
          old = prior[0]
          if (type(old) is not dict or set(old) != set(expected) or type(old["schema_version"]) is not int or old["schema_version"] != 1
              or old["protocol"] != _PROTOCOL or old["session_id"] != identifier or old["native_home_key"] != home):
            raise Conflict(_ERROR)
          run_owners._run_id(old["run_id"])
          previous = _registry(self.workspace).snapshot().get(old["run_id"])
          if (previous is None or previous.get("schema_version") != 2 or previous["agent"] != "pi"
              or run_owners.record_state(previous) != "idle_confirmed"
              or run_owners._encode(previous["manager_identity"]) != run_owners._encode(old["manager_identity"])
              or run_owners.native_home_key(previous["native_home_ref"]) != home):
            raise Conflict(_ERROR)
        if not matches:
          tree.replace(identifier + ".json", run_owners._encode(expected), expected=prior[1] if prior else None)
          sync_directory_ancestors(tree.root)
        saved = _read(tree, identifier + ".json")
        if saved is None or run_owners._encode(saved[0]) != run_owners._encode(expected):
          raise Conflict(_ERROR)
        _same_file(tree, identifier + ".lock", fd)
        self.metadata[identifier] = (expected, saved[1])
        self.fds[identifier], fd = fd, None
        return self.fds[identifier]
      finally:
        if fd is not None:
          os.close(fd)

  def close(self):
    # 不显式 unlock：dup/继承者共享同一租约，关自有副本不能撤销其它持有人。
    owned, self.fds = self.fds, {}
    self.metadata.clear()
    error = None
    for fd in owned.values():
      try:
        os.close(fd)
      except BaseException as problem:
        if error is None:
          error = problem
    if error is not None:
      raise error


def _file(workspace, file):
  if type(file) is not str:
    raise Conflict(_ERROR)
  path = run_owners._absolute(file)
  root = workspace.instance / "pi-home/sessions"
  if path.parent != root or path.suffix != ".jsonl":
    raise Conflict(_ERROR)
  return path


def handle(claims, request):
  """只由原宿主的匿名管道输入；不接收正文、命令或任意路径。"""
  workspace = claims.workspace
  if type(request) is not dict or type(request.get("seq")) is not int or request["seq"] < 1:
    raise Conflict(_ERROR)
  if request.get("op") == "ping" and set(request) == {"seq", "op"}:
    claims._owner()
    return
  if request.get("op") == "prepare" and set(request) == {"seq", "op", "file"}:
    path = _file(workspace, request["file"])
    matches = [value for value in candidates(workspace) if value.path == path]
    if len(matches) != 1:
      raise Conflict(_ERROR)
    claims.claim(matches[0].known.ref.native_ref)
    recheck(workspace, matches[0])
    return
  if request.get("op") != "claim" or set(request) != {"seq", "op", "session", "file", "cwd"}:
    raise Conflict(_ERROR)
  identifier, file, cwd = request["session"], request["file"], request["cwd"]
  directory = run_owners._absolute(cwd)
  if not directory.is_dir():
    raise Conflict(_ERROR)
  if file is not None:
    path = _file(workspace, file)
    if path.exists() or path.is_symlink():
      target = lookup(workspace, identifier)
      if target.path != path or target.known.cwd != cwd:
        raise Conflict(_ERROR)
    elif not path.name.endswith("_" + identifier + ".jsonl"):
      raise Conflict(_ERROR)
  claims.claim(identifier)
  record = claims._owner()
  value = {"schema_version": 1, "protocol": _PROTOCOL, "run_id": claims.run_id,
    "manager_identity": record["manager_identity"], "host_identity": record["host_identity"],
    "session_id": identifier, "file": file, "cwd": cwd, "observed_at_ns": time.time_ns()}
  with Tree(workspace.state_root / "pi-session-observations", create=True) as tree:
    name = claims.run_id + ".json"
    prior = tree.read(name, max_bytes=16384)
    tree.replace(name, run_owners._encode(value), expected=prior[2] if prior else None)
    sync_directory_ancestors(tree.root)


@contextmanager
def prepare(workspace, spec, env, pass_fds, *, run_id, arguments=(), target=None):
  """所有新受管 Pi 使用公开扩展；已存在恢复目标先取得合作租约再启动。"""
  arguments = list(arguments)
  argv = list(spec.argv)
  requested = None
  for index, token in enumerate(arguments):
    if type(token) is not str:
      raise SessionError(2, "invalid_pi_session_arguments")
    if token == "--":
      break
    option, equal, inline = token.partition("=")
    if option in ("--continue", "-c", "--resume", "-r"):
      raise SessionError(2, "pi_use_rotom_resume_for_explicit_session")
    if option == "--session":
      if requested is not None or not equal and index + 1 >= len(arguments):
        raise SessionError(2, "invalid_pi_session_arguments")
      identifier = inline if equal else arguments[index + 1]
      requested = (index, equal, identifier)
  if target is None and requested is not None:
    index, equal, identifier = requested
    target = lookup(workspace, identifier)
    if argv[-len(arguments):] != arguments:
      raise SessionError(2, "invalid_pi_session_arguments")
    position = len(argv) - len(arguments) + index
    if equal:
      # 官方解析器只识别独立 --session；等号形式会被当作扩展参数。
      argv[position:position + 1] = ["--session", str(target.path)]
    else:
      argv[position + 1] = str(target.path)
  elif target is not None and requested is not None:
    raise SessionError(2, "invalid_pi_session_arguments")
  if target is not None and target.known.cwd != str(spec.cwd):
    raise SessionError(4, "pi_use_original_session_cwd")
  register(workspace, run_id)
  claims = Claims(workspace, run_id)
  try:
    fd = None
    if target is not None:
      recheck(workspace, target)
      fd = claims.claim(target.known.ref.native_ref)
      recheck(workspace, target)
    root = Path(__file__).resolve().parents[2]
    context = {"state_root": str(workspace.state_root), "instance": str(workspace.instance),
      "profile": workspace.profile, "binding": workspace.binding, "run_id": run_id,
      "initial_session": target.known.ref.native_ref if target else None, "lease_fd": fd}
    environment = {**env, "ROTOM_PI_CONTROL_PYTHON": sys.executable,
      "ROTOM_PI_CONTROL_HELPER": str(root / "src/agentcfg/pi_session_helper.py"),
      "ROTOM_PI_CONTROL_CONTEXT": json.dumps(context, ensure_ascii=False)}
    # 插入在用户的 -- 之前；自有公开扩展来源由独立锁验证，不修改官方运行包。
    position = argv.index("--") if "--" in argv else len(argv)
    argv[position:position] = ["-e", str(root / "agents/pi/templates/session-control.mjs")]
    fds = (*pass_fds, fd) if fd is not None else pass_fds
    yield replace(spec, argv=tuple(argv)), environment, tuple(fds)
  finally:
    problem = sys.exc_info()[0]
    try:
      claims.close()
    except BaseException:
      if problem is None:
        raise
