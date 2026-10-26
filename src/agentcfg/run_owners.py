"""仅登记主运行归属；不调度任务、不恢复执行、不以父退出证明后代释放。

调用方必须先持有同一实例的物理准入锁，再访问元数据：register/mark_unknown持SH，
assert_inactive持EX。reconcile自行进入调用方提供的可信物理EX context manager，
随后才获得元数据EX锁。该顺序避免核实空闲后又有新运行登记的竞争。
同binding的合法active/unknown记录允许新增运行；unknown仅表示既有运行存活性未知，
不表示owner来源不可信。两者均阻止维护，新增运行不能清除旧归属或证明旧后代退出。
metadata锁不替代物理锁；此模块不接受TOML或用户确认开关作为完整释放证据。
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import fcntl
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from . import storage
from .paths import PathError
from .storage import Conflict, Tree


_RUN_ID = re.compile(r"[0-9a-f]{32}")
_STATES = {"active", "unknown", "idle_confirmed"}
_RESOURCES = ["instance", "runtime", "native-home"]
_OBSERVATIONS = {"active": ("manager_registered", "unknown"),
  "unknown": ("manager_scope_ended", "unknown"), "idle_confirmed": ("complete_release", "complete")}
_SOURCES = {"active": "manager-registration", "unknown": "manager-scope-end", "idle_confirmed": "kernel-release"}
_NATIVE_KINDS = {"dsh": "dsh-home", "pi": "pi-home", "omp": "omp-managed-home"}
_METADATA_FIELDS = {"agent", "backend", "profile", "machine_ref", "start_cwd",
  "native_home_ref", "deployed_identity", "coordination_domain"}


def _run_id(value):
  if type(value) is not str or not _RUN_ID.fullmatch(value):
    raise Conflict("运行归属标识无效")
  return value


def _encode(value):
  return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
    separators=(",", ":")) + "\n").encode("utf-8")


def _manager(value):
  if (type(value) is not dict
      or type(value.get("pid")) is not int or value["pid"] <= 0
      or type(value.get("birth_id")) is not str or not value["birth_id"] or "\0" in value["birth_id"]):
    raise Conflict("运行进程身份缺失或无效")
  try:
    # 保存全部可确认身份字段，比较时不能只匹配PID。
    copied = json.loads(_encode(value))
  except (TypeError, ValueError, UnicodeError, RecursionError):
    raise Conflict("运行进程身份不可序列化") from None
  if copied != value:
    raise Conflict("运行进程身份格式不稳定")
  return copied


def _observation(state):
  # 时间仅记录观察时刻，不参与超时、空闲推断或归属清除。
  kind, coverage = _OBSERVATIONS[state]
  observed_at_ns = time.time_ns()
  if type(observed_at_ns) is not int or observed_at_ns <= 0:
    raise Conflict("运行观察时间无效")
  return {"kind": kind, "observed_at_ns": observed_at_ns, "coverage": coverage}


def _pairs(items):
  value = {}
  for key, item in items:
    if key in value:
      raise ValueError()
    value[key] = item
  return value


def _invalid_constant(value):
  raise ValueError()


def record_state(record):
  return record["lifecycle_state" if record["schema_version"] == 2 else "state"]


def _set_state(record, state):
  if record["schema_version"] == 1:
    record["state"] = state
    record["observation"] = _observation(state)
  else:
    record["lifecycle_state"] = state
    record["process_observation"] = {**_observation(state), "source": _SOURCES[state],
      "manager_identity": deepcopy(record["manager_identity"]),
      "host_identity": deepcopy(record["host_identity"])}


@lru_cache(maxsize=2)
def _record_validator(version=None):
  from jsonschema import Draft202012Validator
  schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/rotom/run-record.schema.json").read_text())
  if version == 2:
    # 固定记录格式仅使用无循环的命名本地引用；展开一次，逐条仍由同一完整 schema 校验。
    def expand(node, references=()):
      if isinstance(node, list):
        return [expand(child, references) for child in node]
      if not isinstance(node, dict):
        return node
      if {"$id", "$anchor", "$dynamicRef", "$dynamicAnchor"} & node.keys():
        raise ValueError("unsupported record schema scope")
      if "$ref" in node:
        ref = node["$ref"]
        if (set(node) != {"$ref"} or type(ref) is not str
            or not ref.startswith("#/$defs/") or ref in references):
          raise ValueError("unsupported record schema reference")
        return expand(schema["$defs"][ref.removeprefix("#/$defs/")], (*references, ref))
      return {key: expand(child, references) for key, child in node.items()}
    schema = expand(schema["$defs"]["v2"])
  return Draft202012Validator(schema)


def _no_float(value):
  if type(value) is float:
    raise ValueError("unsupported number")
  if isinstance(value, dict):
    for item in value.values():
      _no_float(item)
  elif isinstance(value, list):
    for item in value:
      _no_float(item)


def _absolute(value):
  if type(value) is not str or not value or "\0" in value:
    raise ValueError("invalid path")
  path = Path(value)
  if (not path.is_absolute() or value.startswith("//") or str(path) != value
      or any(part in (".", "..") for part in value.split("/"))):
    raise ValueError("invalid path")
  return path


def native_home_key(reference):
  """非秘密存储引用的键；不从该键推导当前会话或读取原生文件。"""
  return hashlib.sha256(_encode({"kind": reference["kind"], "path": reference["path"]})).hexdigest()


@dataclass(frozen=True)
class ReleaseObservation:
  """可信内部observer的一次完整观察；不是公共配置或用户保证。"""

  run_id: str
  manager_identity: dict
  all_related_exited: bool
  complete: bool


def current_process_identity():
  """Linux公开/proc身份；缺可靠出生信息则拒绝，不猜测其他平台支持。"""
  if sys.platform != "linux":
    raise Conflict("当前平台尚无可靠的主进程身份来源")
  try:
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    if str(uuid.UUID(boot)) != boot:
      raise ValueError()
    def read_stat():
      value = Path("/proc/self/stat").read_text(encoding="ascii")
      prefix, separator, tail = value.rpartition(")")
      if not separator or int(prefix.split("(", 1)[0].strip()) != os.getpid():
        raise ValueError()
      start = tail.split()[19]
      if not start.isdecimal() or int(start) <= 0:
        raise ValueError()
      return start
    start = read_stat()
    if start != read_stat() or boot != Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip():
      raise ValueError()
    return {"pid": os.getpid(), "birth_id": "linux:" + boot + ":" + start}
  except (OSError, ValueError, IndexError, UnicodeError):
    raise Conflict("无法可靠确认当前主进程出生身份") from None


def observed_process_identity(pid):
  """仅观察已登记 PID 的公开出生身份；不扫描进程参数或推断资源释放。"""
  if sys.platform != "linux" or type(pid) is not int or pid <= 0:
    return None
  try:
    boot_path = Path("/proc/sys/kernel/random/boot_id")
    boot = boot_path.read_text(encoding="ascii").strip()
    if str(uuid.UUID(boot)) != boot:
      return None
    def sample():
      prefix, separator, tail = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rpartition(")")
      if not separator or int(prefix.split("(", 1)[0].strip()) != pid:
        raise ValueError()
      start = tail.split()[19]
      if not start.isdecimal() or int(start) <= 0:
        raise ValueError()
      return start
    start = sample()
    if start != sample() or boot != boot_path.read_text(encoding="ascii").strip():
      return None
    return {"pid": pid, "birth_id": "linux:" + boot + ":" + start}
  except (OSError, ValueError, IndexError, UnicodeError):
    return None


def _instance_row(workspace, record, observed_at_ns):
  # record 来自本次独立解码且不会缓存；行内引用只属于这次查询，不写回持久记录。
  version = record["schema_version"]
  state = record_state(record)
  saved = record["process_observation"] if version == 2 else record["observation"]
  process = {"status": "unknown", "ownership_state": state,
    "manager_status": "unknown", "host_status": "unknown",
    "manager_identity": record["manager_identity"],
    "host_identity": record["host_identity"] if version == 2 else None,
    "source": saved.get("source", "legacy-owner-record"),
    "observed_at_ns": saved["observed_at_ns"], "coverage": saved["coverage"]}
  if state == "idle_confirmed":
    process["status"] = "stopped"
  elif state == "active":
    # 身份相符只证明观察时 manager 存在，不证明宿主/后代或会话状态。
    manager = record["manager_identity"]
    if observed_process_identity(manager["pid"]) == manager:
      process.update(status="active", source="selected-manager-birth-identity",
        manager_status="active", observed_at_ns=observed_at_ns, coverage="manager-only")
  session = {"status": "unknown", "ref": None, "source": None,
    "observed_at_ns": None, "resume_available": False}
  if version == 2 and record["session_observation"] is not None:
    saved_session = record["session_observation"]
    session.update(status="historical", ref=saved_session["session"],
      source=saved_session["source"], observed_at_ns=saved_session["observed_at_ns"],
      saved_confirmation=saved_session["confirmation"])
  return {"kind": "registered", "run_id": record["run_id"],
    "schema_version": version, "agent": workspace.agent, "profile": workspace.profile,
    "deployed_identity": record["deployed_identity"] if version == 2 else None,
    "process": process, "start_cwd": record["start_cwd"] if version == 2 else None,
    "session_cwd": record["session_cwd"] if version == 2 else None,
    "session": session, "terminal": {"status": "unknown", "ref": None,
      "source": None, "observed_at_ns": None, "restore_available": False}}


def _unverified_row(workspace, observed_at_ns, source):
  return {"kind": "unregistered-or-unverified", "run_id": None, "schema_version": None,
    "agent": workspace.agent, "profile": workspace.profile,
    "deployed_identity": None,
    "process": {"status": "unknown", "ownership_state": "unknown",
      "manager_status": "unknown", "host_status": "unknown",
      "manager_identity": None, "host_identity": None, "source": source,
      "observed_at_ns": observed_at_ns, "coverage": "unknown"},
    "start_cwd": None, "session_cwd": None,
    "session": {"status": "unknown", "ref": None, "source": None,
      "observed_at_ns": None, "resume_available": False},
    "terminal": {"status": "unknown", "ref": None, "source": None,
      "observed_at_ns": None, "restore_available": False}}


def instances(local, *, agent=None, profile=None):
  """所选机器的只读快照；没有记录/锁冲突均不构成全局空闲证明。"""
  from .lifecycle import observation_guard
  from .local import available_profiles
  from .workspace import load_instance_workspaces
  from .resume_attempts import ResumeAttempts
  if agent not in (None, "dsh", "pi", "omp"):
    raise ValueError("invalid tool")
  profiles = available_profiles()
  if profile is not None and not any(p == profile and agent in (None, a) for p, a in profiles):
    raise ValueError("profile scope mismatch")
  selected = [(p, a) for p, a in profiles if (profile is None or p == profile) and agent in (None, a)]
  rows, coverage, incomplete, machine = [], [], False, None
  workspaces = load_instance_workspaces(Path(local), [p for p, _ in selected])
  for workspace in workspaces:
    profile_id = workspace.profile
    if workspace.agent != dict(selected).get(profile_id) or agent not in (None, workspace.agent):
      raise Conflict("公开配方来源在查询期间变化；请重新查询所选范围")
    machine = workspace.binding["machine"]
    now = time.time_ns()
    item = {"agent": workspace.agent, "profile": profile_id, "status": "observed",
      "source": "managed-instance-and-owner-records", "observed_at_ns": now,
      "registration": "unsupported" if workspace.agent == "omp" else "v1-v2"}
    coverage.append(item)
    cooperative, pending = False, False
    try:
      if workspace.agent == "omp":
        from .resource_scopes import scope_claim_exists
        cooperative = scope_claim_exists(workspace.instance)
        if cooperative:
          item["registration"] = "cooperative-unverified"
      with Tree(workspace.instance) as target:
        exists = target.fd is not None
      if not exists:
        # 旧 state 仍存在时不能把丢失的实例锚点当作空记录。
        if cooperative or workspace.state_root.exists() or workspace.state_root.is_symlink():
          raise Conflict("实例锚点缺失，历史归属无法核实")
        item["status"] = "not-prepared"
        continue
      with observation_guard(workspace) as fd:
        if cooperative:
          from . import omp_observation
          records, pending = omp_observation.snapshot(workspace, instance_fd=fd)
          item["registration"] = "cooperative-v2"
        else:
          records = Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()
    except (Conflict, PathError, OSError):
      incomplete = True
      item["status"] = "unknown"
      rows.append(_unverified_row(workspace, now, "ownership-or-records-unavailable"))
      continue
    if pending:
      incomplete = True
      item["status"] = "unknown"
      rows.append(_unverified_row(workspace, now, "coordination-records-pending"))
    requests = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding)
    try:
      # Registry 已验证完整 owner；辅助目录只打开一次，缺失时不逐 run 重新遍历祖先。
      request_rows = requests.for_validated_owners(records)
    except (Conflict, PathError, OSError):
      request_rows = {run_id: {"status": "unknown", "source": "resume-request-unavailable"}
        for run_id in records}
    for record in records.values():
      row = _instance_row(workspace, record, now)
      row["resume_request"] = request_rows[record["run_id"]]
      if row["resume_request"] is not None and row["resume_request"]["source"] == "resume-request-unavailable":
        # 辅助请求记录不可核实时保留独立进程/会话观察，不丢掉整个实例。
        incomplete = True
        item["resume_observation"] = "unavailable"
      rows.append(row)
    lease_available = True
    try:
      # SH 已释放且 owner 锁也已释放；不持 owner 锁反向取物理 EX。
      with observation_guard(workspace, shared=False):
        pass
    except (Conflict, PathError, OSError):
      lease_available = False
    if (workspace.agent == "omp" and not cooperative) or (not lease_available and not pending and not any(
        record_state(record) in ("active", "unknown") for record in records.values())):
      item["status"] = "unknown"
      rows.append(_unverified_row(workspace, now,
        "omp-registration-unavailable" if workspace.agent == "omp" and not cooperative else "physical-lease-or-ownership"))
    item["lease_observation"] = "available-at-observation" if lease_available else "busy-or-unverified"
  return {"command": "instances list", "scope": {"machine": machine,
    "local": str(local), "agent": agent, "profile": profile},
    "instances": rows, "coverage": coverage, "incomplete": incomplete,
    "capabilities": {"stop": False, "resume": False}}


class Registry:
  def __init__(self, root: Path, binding: dict):
    if (not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts
        or root == Path("/") or type(binding) is not dict):
      raise Conflict("运行归属容器或绑定无效")
    try:
      self.binding_digest = hashlib.sha256(_encode(binding)).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
      raise Conflict("运行归属绑定不可序列化") from None
    self.root = root
    self.binding = deepcopy(binding)

  def _verify_root(self, tree):
    # 等待元数据锁和observer返回后仍重新核对当前路径的目录inode及0700边界。
    with Tree(self.root) as current:
      if current.fd is None:
        raise Conflict("运行归属目录已消失")
      before, after = os.fstat(tree.fd), os.fstat(current.fd)
      if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise Conflict("运行归属目录身份已变化")

  @contextmanager
  def _locked(self, *, create=False, nonblocking=False):
    try:
      with Tree(self.root, create=create) as tree:
        if tree.fd is None:
          yield None
          return
        # 短元数据操作阻塞串行；调用者先持物理锁，不在此反向获取物理锁。
        fcntl.flock(tree.fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        try:
          self._verify_root(tree)
          yield tree
        finally:
          fcntl.flock(tree.fd, fcntl.LOCK_UN)
    except (OSError, PathError):
      raise Conflict("无法安全访问运行归属元数据") from None

  def _validate_record(self, name, record):
    if type(record) is dict and type(record.get("schema_version")) is int and record["schema_version"] == 2:
      self._validate_v2(name, record)
      return
    if (type(record) is not dict
        or set(record) != {"schema_version", "binding_digest", "run_id", "manager_identity", "session_ref", "state",
          "affected_resources", "observation"}
        or type(record["schema_version"]) is not int or record["schema_version"] != 1
        or record["binding_digest"] != self.binding_digest
        or type(record["run_id"]) is not str or not _RUN_ID.fullmatch(record["run_id"])
        or name != record["run_id"] + ".json"
        or type(record["state"]) is not str or record["state"] not in _STATES
        or (record["session_ref"] is not None and (type(record["session_ref"]) is not str
          or not record["session_ref"] or "\0" in record["session_ref"]))):
      raise Conflict("运行归属记录损坏或绑定不匹配")
    observation = record["observation"]
    kind, coverage = _OBSERVATIONS[record["state"]]
    if (type(record["affected_resources"]) is not list or record["affected_resources"] != _RESOURCES
        or type(observation) is not dict or set(observation) != {"kind", "observed_at_ns", "coverage"}
        or observation["kind"] != kind or observation["coverage"] != coverage
        or type(observation["observed_at_ns"]) is not int or observation["observed_at_ns"] <= 0):
      raise Conflict("运行资源范围或观察记录无效")
    _manager(record["manager_identity"])

  def _validate_v2(self, name, record):
    try:
      _no_float(record)
      _record_validator(2).validate(record)
      if (name != record["run_id"] + ".json" or record["binding_digest"] != self.binding_digest
          or set(self.binding) != {"machine", "local", "profile"}
          or record["profile"] != self.binding["profile"]
          or record["machine_ref"] != {key: self.binding[key] for key in ("machine", "local")}):
        raise ValueError("binding mismatch")
      for path in (record["machine_ref"]["local"], record["start_cwd"]["path"], record["native_home_ref"]["path"]):
        _absolute(path)
      if record["native_home_ref"]["kind"] != _NATIVE_KINDS[record["agent"]]:
        raise ValueError("native storage mismatch")
      if record["coordination_domain"] is not None and record["agent"] != "omp":
        raise ValueError("unsupported coordinated owner")
      _manager(record["manager_identity"])
      state = record_state(record)
      observation = record["process_observation"]
      kind, coverage = _OBSERVATIONS[state]
      if (observation["kind"] != kind or observation["coverage"] != coverage
          or observation["source"] != _SOURCES[state]
          or observation["manager_identity"] != record["manager_identity"]
          or observation["host_identity"] != record["host_identity"]):
        raise ValueError("observation mismatch")
      if record["host_identity"] is not None and record["host_identity"]["manager_identity"] != record["manager_identity"]:
        raise ValueError("host relationship mismatch")
      control = record["protocol"]["control"]
      if control is not None:
        endpoint = control["endpoint"]
        host = record["host_identity"]
        if (record["agent"] != "dsh" or record["backend"] != "managed"
            or record["coordination_domain"] is not None or host is None
            or host["source"] != "linux-spawn-pidfd" or host["relationship"] != "reported-by-current-run"
            or endpoint["binding_digest"] != record["binding_digest"] or endpoint["run_id"] != record["run_id"]
            or _encode(endpoint["manager_identity"]) != _encode(record["manager_identity"])
            or _encode(endpoint["host_identity"]) != _encode(host["identity"])
            or _encode(host["manager_identity"]) != _encode(record["manager_identity"])
            or endpoint["host_identity"]["pid"] == endpoint["manager_identity"]["pid"]
            or len(_encode(endpoint)) > 16384):
          raise ValueError("control description mismatch")
      if record["session_cwd"] is not None:
        _absolute(record["session_cwd"]["path"])
      session = record["session_observation"]
      if session is not None and (session["run_id"] != record["run_id"] or session["session"]["agent"] != record["agent"]
          or session["session"]["backend"] != record["backend"]
          or session["session"]["native_home_ref"] != native_home_key(record["native_home_ref"])):
        raise ValueError("session scope mismatch")
      if session is not None and session["confirmation"] == "final" and state != "idle_confirmed":
        raise ValueError("final session without complete release")
    except Conflict:
      raise
    except Exception:
      raise Conflict("运行归属 v2 记录损坏、来源不完整或绑定不匹配") from None

  def _records(self, tree):
    if tree is None:
      return {}, {}
    records, originals = {}, {}
    for name in sorted(os.listdir(tree.fd)):
      if not name.endswith(".json") or not _RUN_ID.fullmatch(name[:-5]):
        raise Conflict("运行归属目录包含未知记录")
      raw = tree.read(name, max_bytes=65536)
      if raw is None or raw[1] != 0o600:
        raise Conflict("运行归属记录缺失或权限不符")
      try:
        record = json.loads(raw[0], object_pairs_hook=_pairs, parse_constant=_invalid_constant)
      except (ValueError, UnicodeError, RecursionError):
        raise Conflict("运行归属记录格式无效") from None
      self._validate_record(name, record)
      records[record["run_id"]] = record
      originals[record["run_id"]] = raw
    self._verify_root(tree)
    return records, originals

  def register(self, manager_identity, session_ref=None):
    """调用者持物理SH；同binding的active/unknown均保留且允许并行。"""
    manager = _manager(manager_identity)
    run_id = uuid.uuid4().hex
    record = {"schema_version": 1, "binding_digest": self.binding_digest, "run_id": run_id,
      "manager_identity": manager, "session_ref": session_ref, "state": "active",
      "affected_resources": list(_RESOURCES), "observation": _observation("active")}
    self._validate_record(run_id + ".json", record)
    with self._locked(create=True) as tree:
      self._records(tree)
      self._publish_record(tree, record)
    return run_id

  def register_v2(self, manager_identity, metadata):
    """新登记只保存已解析的非秘密来源；宿主/会话/位置没有证据时保持未知。"""
    # 合作引用只能由先落盘的 reservation 建立；普通登记不能自填域引用。
    if type(metadata) is not dict or metadata.get("coordination_domain") is not None:
      raise Conflict("普通运行登记不能提供共享资源协调引用")
    run_id = uuid.uuid4().hex
    record = self._prepare_v2(run_id, manager_identity, metadata)
    with self._locked(create=True) as tree:
      self._records(tree)
      self._publish_record(tree, record)
    return run_id

  def _publish_record(self, tree, record):
    """调用方已持物理和 owner 锁；记录与祖先项持久化后才允许后续派发。"""
    from .run_stop_fence import assert_unfenced
    assert_unfenced(self)
    name = record["run_id"] + ".json"
    encoded = _encode(record)
    tree.write_new(name, encoded)
    storage.sync_directory_ancestors(self.root.parent)
    saved = tree.read(name, max_bytes=65536)
    self._verify_root(tree)
    if saved is None or saved[1] != 0o600 or saved[0] != encoded:
      raise Conflict("运行归属发布后发生变化；保留记录并停止启动")

  def _prepare_v2(self, run_id, manager_identity, metadata):
    """仅构建内部记录；协调调用者须先持物理锁，并在 owner 锁内不可覆盖发布。"""
    _run_id(run_id)
    manager = _manager(manager_identity)
    if type(metadata) is not dict or set(metadata) != _METADATA_FIELDS:
      raise Conflict("运行登记来源字段不完整或包含未知字段")
    try:
      supplied = deepcopy(metadata)
      record = {"schema_version": 2, "binding_digest": self.binding_digest, "run_id": run_id,
        "manager_identity": manager, "host_identity": None, **supplied,
        "session_cwd": None, "affected_resources": list(_RESOURCES),
        "session_observation": None, "terminal_ref": None,
        "protocol": {"registration": 2, "control": None}}
      _set_state(record, "active")
      self._validate_record(run_id + ".json", record)
      # 验证的是新登记时的存储目录；历史只读不要求旧目录仍然存在。
      with Tree(_absolute(record["native_home_ref"]["path"])) as native:
        if native.fd is None:
          raise Conflict("运行存储目录尚未准备")
    except (PathError, OSError, ValueError, TypeError, RecursionError):
      raise Conflict("运行登记来源或私人存储目录无效") from None
    return record

  def mark_unknown(self, run_id, expected_identity):
    """调用者仍持物理SH；仅更新身份完全匹配的本次运行。"""
    _run_id(run_id)
    expected = _manager(expected_identity)
    with self._locked() as tree:
      records, originals = self._records(tree)
      record = records.get(run_id)
      if (record is None or _encode(record["manager_identity"]) != _encode(expected)
          or record_state(record) == "idle_confirmed"):
        raise Conflict("运行归属或出生身份不匹配")
      if record_state(record) == "unknown":
        return
      _set_state(record, "unknown")
      tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])

  def bind_current_host(self, run_id, host):
    """本次受管 DSH 启动的只读进程观察；调用者仍持物理/状态/包 SH。

    不接受序列化身份，不更新合作 OMP 的双向摘要，也不启用控制协议。
    观察或写入结果不明时不重试；已运行的宿主继续由原等待路径处理。
    """
    from .spawned_host import SpawnedHost
    try:
      _run_id(run_id)
      if type(host) is not SpawnedHost:
        raise ValueError()
      # 可选观察不等待其它元数据操作者；错过登记只使 host 保持未知。
      with self._locked(nonblocking=True) as tree:
        records, originals = self._records(tree)
        record = records.get(run_id)
        if (record is None or record["schema_version"] != 2 or record["agent"] != "dsh"
            or record["backend"] != "managed" or record["coordination_domain"] is not None
            or record_state(record) != "active" or record["host_identity"] is not None):
          raise ValueError()
        observed = host.snapshot()
        manager = record["manager_identity"]
        if (observed["manager_identity"] != manager or current_process_identity() != manager
            or observed["identity"]["pid"] == manager["pid"]
            or observed["source"] != "linux-spawn-pidfd"
            or observed["relationship"] != "reported-by-current-run"):
          raise ValueError()
        record["host_identity"] = deepcopy(observed)
        _set_state(record, "active")
        self._validate_record(run_id + ".json", record)
        self._verify_root(tree)
        tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])
    except Exception:
      raise Conflict("本次启动的宿主身份未能登记；保留未知观察与原运行保护") from None

  def bind_current_control(self, run_id, host, service):
    """只登记当前原句柄/服务的描述；不派发停止，也不以历史记录授予 live 权限。

    调用者保留原运行租约；只按 owner NB → inbox 短锁顺序读取，不取得物理锁。
    写入或响应不明时不重试、不改变已启动宿主，历史描述随 owner 状态保留。
    """
    from .spawned_host import SpawnedHost
    from .stop_service import StopService
    try:
      _run_id(run_id)
      if (type(host) is not SpawnedHost or type(service) is not StopService
          or service.belongs_to(run_id, host) is not True):
        raise ValueError()
      with self._locked(nonblocking=True) as tree:
        records, originals = self._records(tree)
        record = records.get(run_id)
        if (record is None or record["schema_version"] != 2 or record["agent"] != "dsh"
            or record["backend"] != "managed" or record["coordination_domain"] is not None
            or record_state(record) != "active" or record["host_identity"] is None
            or record["protocol"]["control"] is not None):
          raise ValueError()
        manager = record["manager_identity"]
        observed = host.snapshot()
        if (_encode(current_process_identity()) != _encode(manager)
            or _encode(observed) != _encode(record["host_identity"])):
          raise ValueError()
        endpoint = service.describe()
        record["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": deepcopy(endpoint)}
        self._validate_record(run_id + ".json", record)
        if (service.belongs_to(run_id, host) is not True
            or _encode(host.snapshot()) != _encode(observed)
            or _encode(current_process_identity()) != _encode(manager)):
          raise ValueError()
        self._verify_root(tree)
        tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])
    except Exception:
      raise Conflict("本次停止端点未能登记；保留原宿主与已有记录且不重试") from None

  def finish_current(self, run_id, expected_identity, observation):
    """调用者仍持物理SH；本次完整内核观察只能结束本次active记录。

    不同主运行仍可登记，其active/unknown不会被本次观察清除。旧unknown
    的后续核实仍只能经过reconcile的物理EX维护路径。
    """
    _run_id(run_id)
    expected = _manager(expected_identity)
    with self._locked() as tree:
      records, originals = self._records(tree)
      record = records.get(run_id)
      if (record is None or record_state(record) != "active"
          or _encode(record["manager_identity"]) != _encode(expected)
          or type(observation) is not ReleaseObservation or observation.run_id != run_id
          or _encode(_manager(observation.manager_identity)) != _encode(expected)
          or observation.all_related_exited is not True or observation.complete is not True):
        raise Conflict("当前运行没有完整且身份匹配的后代释放观察")
      _set_state(record, "idle_confirmed")
      tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])

  def snapshot(self):
    with self._locked() as tree:
      records, _ = self._records(tree)
      # 每次均从受保护文件重新解码；Registry 不保留这些对象，无需再次整份复制。
      return records

  def assert_inactive(self):
    """调用者持物理EX；不因PID死亡、超时或父退出清除归属。"""
    from .run_stop_fence import assert_unfenced
    with self._locked() as tree:
      assert_unfenced(self)
      records, _ = self._records(tree)
      if any(record_state(record) != "idle_confirmed" for record in records.values()):
        raise Conflict("存在活动或未知运行；共享资源维护被阻止")

  def reconcile(self, run_id, *, maintenance_guard, observe=None):
    """先获得可信物理EX，再锁元数据；observer接收副本，不得重入Registry。"""
    _run_id(run_id)
    if maintenance_guard is None or not hasattr(maintenance_guard, "__enter__"):
      raise Conflict("核实运行归属需要物理排他维护准入")
    with maintenance_guard:
      with self._locked() as tree:
        records, originals = self._records(tree)
        record = records.get(run_id)
        if record is None or not callable(observe):
          raise Conflict("没有完整的运行释放观察")
        try:
          result = observe(deepcopy(record))
        except Exception:
          raise Conflict("无法完整核实相关运行及后代资源释放") from None
        if (type(result) is not ReleaseObservation or result.run_id != run_id
            or _encode(_manager(result.manager_identity)) != _encode(record["manager_identity"])
            or result.all_related_exited is not True or result.complete is not True):
          raise Conflict("运行释放观察不完整或身份不匹配")
        self._verify_root(tree)
        _set_state(record, "idle_confirmed")
        tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])
        return deepcopy(record)
