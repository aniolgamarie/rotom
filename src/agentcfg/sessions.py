"""受限会话视图与内部恢复协调；具体后端仍须独立核验和准入。"""

from dataclasses import asdict, dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import re
from threading import Lock

from . import run_owners


class SessionError(Exception):
  def __init__(self, code, reason):
    self.code = code
    self.reason = reason
    super().__init__(reason)


def _token(value):
  return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is not None


def _scope(value):
  return type(value) is str and bool(value) and "\0" not in value


@dataclass(frozen=True)
class SessionCapability:
  """描述性精确组合；不可作为部署、writer 或实际加载的准入凭据。"""

  agent: str
  backend: str
  runtime_identity: str
  observer_identity: str
  platform: str
  location: str
  handoff: str
  reason: str
  manual_guidance: str
  load_confirmation: bool = field(default=False, init=False)
  automatic_continue: bool = field(default=False, init=False)
  final_seal: bool = field(default=False, init=False)


# 完整运行锁与自有控制来源分别锁定；条目只描述交接，不证明实际加载。
_SESSION_HANDOFF_ADMITTED = frozenset({(
  "dsh", "managed", "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d",
  "none", "linux", "here",
), (
  "pi", "managed", "62ac8348c34339599d280df5769ab0f8383a2f48c0885d84fa16c22a40a6b558",
  "e286d053f59613d94c8be14d89f3def12dafdc67ef54a9746d7d2229ce362d9a", "linux", "here",
), (
  "pi", "managed", "a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587",
  "e286d053f59613d94c8be14d89f3def12dafdc67ef54a9746d7d2229ce362d9a", "linux", "here",
), (
  "omp", "managed", "490e6c90d0ef4d890bb2ab14e006dcd3a3f4d79b5e6ad0ca9fbf3e8f4ab610ab",
  "none", "linux", "here",
)})


def session_capability(*, agent, backend, runtime_identity, observer_identity, platform, location):
  """静态能力描述；不读取机器配置、不派发进程，也不替代后端实际核验。"""
  key = (agent, backend, runtime_identity, observer_identity, platform, location)
  if any(not _token(value) for value in key):
    raise SessionError(2, "invalid_session_capability_key")
  admitted = key in _SESSION_HANDOFF_ADMITTED
  return SessionCapability(*key,
    handoff="admitted" if admitted else "unavailable",
    reason="verified_linux_" + agent + "_handoff" if admitted else "exact_combination_unavailable",
    manual_guidance=("恢复交接已准入；加载待确认，请在官方界面检查目标；不自动发送继续"
      if admitted else "请在所选工具的官方界面人工选择会话；不自动发送继续"))


@lru_cache(maxsize=2)
def _validator(name):
  from jsonschema import Draft202012Validator
  schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/rotom/session.schema.json").read_text())
  return Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": schema["$defs"]})


def _validate(name, value):
  try:
    run_owners._no_float(value)
    _validator(name).validate(value)
  except Exception:
    raise SessionError(2, "invalid_" + name) from None


@dataclass(frozen=True)
class SessionRef:
  agent: str
  backend: str
  native_home_ref: str
  native_ref: str

  def __post_init__(self):
    _validate("session_ref", asdict(self))
    if not _token(self.backend) or not _token(self.native_home_ref):
      raise SessionError(2, "invalid_session_ref")


@dataclass(frozen=True)
class SessionObservation:
  session: SessionRef
  run_id: str
  emitter_epoch: str
  sequence: int
  confirmation: str
  source: str
  observed_at_ns: int

  def __post_init__(self):
    if type(self.session) is not SessionRef:
      raise SessionError(2, "invalid_session_observation")
    _validate("session_observation", asdict(self))
    if (type(self.run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", self.run_id) is None
        or not _token(self.emitter_epoch) or not _token(self.source)):
      raise SessionError(2, "invalid_session_observation")


@dataclass(frozen=True)
class KnownSession:
  ref: SessionRef
  scope: str
  profile: str
  cwd: str | None
  cwd_status: str
  confirmation: str
  observed_at_ns: int
  run_id: str | None

  def __post_init__(self):
    if (type(self.ref) is not SessionRef or not _scope(self.scope) or not _token(self.profile)
        or self.cwd_status not in ("confirmed", "historical", "unknown")
        or self.confirmation not in ("confirmed", "historical", "unknown", "final")
        or type(self.observed_at_ns) is not int or self.observed_at_ns <= 0
        or self.run_id is not None and (type(self.run_id) is not str
          or re.fullmatch(r"[0-9a-f]{32}", self.run_id) is None)
        or self.cwd is None and self.cwd_status != "unknown"):
      raise SessionError(2, "invalid_known_session")
    if self.cwd is not None:
      try:
        run_owners._absolute(self.cwd)
      except ValueError:
        raise SessionError(2, "invalid_session_cwd") from None


class SessionIndex:
  def __init__(self, sessions):
    self._sessions = tuple(sessions)
    if any(type(item) is not KnownSession for item in self._sessions):
      raise SessionError(2, "invalid_known_session")

  def candidates(self, *, scope, agent=None, profile=None, native_ref=None):
    if (not _scope(scope) or agent is not None and agent not in ("dsh", "pi", "omp")
        or profile is not None and not _token(profile)
        or native_ref is not None and (type(native_ref) is not str or not native_ref or "\0" in native_ref
          or len(native_ref) > 1024)):
      raise SessionError(2, "invalid_session_selector")
    groups = {}
    for item in self._sessions:
      if (item.scope != scope or agent is not None and item.ref.agent != agent
          or profile is not None and item.profile != profile
          or native_ref is not None and item.ref.native_ref != native_ref):
        continue
      # 只合并同一个精确目标的观察；不同归属或目录不能按时间选最近。
      key = (item.scope, item.profile, item.ref, item.cwd, item.cwd_status)
      if key not in groups or item.observed_at_ns > groups[key].observed_at_ns:
        groups[key] = item
    return tuple(groups.values())

  def select(self, *, scope, agent=None, profile=None, native_ref=None):
    groups = self.candidates(scope=scope, agent=agent, profile=profile, native_ref=native_ref)
    if not groups:
      raise SessionError(2, "session_not_found")
    if len(groups) != 1:
      raise SessionError(2, "ambiguous_session")
    return groups[0]


def from_run_records(records, *, scope, machine_ref, profile=None):
  """只投影完整校验过的保存记录；scope 是调用方精确绑定的 opaque 键。"""
  try:
    if (not _scope(scope) or type(machine_ref) is not dict
        or set(machine_ref) != {"machine", "local"} or not _token(machine_ref["machine"])
        or profile is not None and not _token(profile) or type(records) is not dict):
      raise ValueError()
    run_owners._absolute(machine_ref["local"])
  except (KeyError, ValueError):
    raise SessionError(2, "invalid_session_scope") from None
  result = []
  for key, record in records.items():
    try:
      if (type(record) is not dict or type(record.get("schema_version")) is not int
          or type(key) is not str or re.fullmatch(r"[0-9a-f]{32}", key) is None or key != record.get("run_id")):
        raise ValueError()
      if record["schema_version"] == 1:
        # v1 不包含 machine/local；只校验结构并忽略，不为它重建或推造归属。
        run_owners._record_validator().validate(record)
        run_owners._manager(record["manager_identity"])
        if type(record["manager_identity"]["pid"]) is not int or type(record["observation"]["observed_at_ns"]) is not int:
          raise ValueError()
        continue
      if record["schema_version"] != 2:
        raise ValueError()
      binding = {**record["machine_ref"], "profile": record["profile"]}
      # 复用 Registry 的完整来源/绑定校验；此路径仅作内存验证，不打开虚构目录。
      registry = run_owners.Registry(Path("/run-owners"), binding)
      registry._validate_record(key + ".json", record)
    except Exception:
      raise SessionError(2, "invalid_run_record") from None
    if record["machine_ref"] != machine_ref or profile is not None and record["profile"] != profile:
      continue
    observation = record["session_observation"]
    if observation is None:
      continue
    ref = SessionRef(**observation["session"])
    cwd = record["session_cwd"]
    # 保存快照不能证明仍在当前会话或目录；start_cwd 也不能代替 session_cwd。
    result.append(KnownSession(ref=ref, scope=scope, profile=record["profile"],
      cwd=None if cwd is None else cwd["path"],
      cwd_status="unknown" if cwd is None or cwd["confirmation"] == "unknown" else "historical",
      confirmation="historical", observed_at_ns=observation["observed_at_ns"], run_id=record["run_id"]))
  return tuple(result)


@dataclass(frozen=True)
class WriterEvidence:
  """可信后端的当次排他观察；不能从用户配置或保存的布尔值构造准入。"""

  session: SessionRef
  source: str
  coverage: str
  is_live: object


@dataclass(frozen=True)
class LaunchReceipt:
  """启动派发事实，不包含实际加载身份；退出码零也不是加载证明。"""

  run_id: str
  exit_code: int | None = None


@dataclass(frozen=True)
class LoadReceipt:
  """仅限已准入后端的实际加载观察；普通启动不得自行构造此事实。"""

  run_id: str
  session: SessionRef
  cwd: str
  loaded: bool
  input_ready: bool = False


@dataclass(frozen=True)
class ResumeOutcome:
  status: str
  requested_session: SessionRef
  requested_cwd: str
  reason: str
  run_id: str | None = None
  session: SessionRef | None = None
  cwd: str | None = None
  input_ready: bool = False
  continue_status: str = "not_sent"
  exit_code: int | None = None


class HostResumeBackend:
  """由宿主内部完成严格恢复及 writer 准入的可信适配接缝。

  子类负责完整部署/目标/目录核验，保存运行身份后、实际启动前调用 before_dispatch，
  仅在创建子进程成功后调用 after_dispatch；两次回调关联同一新 run。
  writer 由官方宿主取得并持有到退出，不能将方法返回或此类型本身当作排他证明。
  只有独立验证的适配实现才可注册到生产入口；此模块不提供默认实现或能力开关。
  """

  def resume_session(self, target, *, location, before_dispatch, after_dispatch):
    raise SessionError(5, "resume_backend_unavailable")


class HandoffResumeBackend:
  """按工具公开接口交接，不宣称启动即取得写锁或已加载。

  Pi 使用启动前的合作租约及公开切换扩展；OMP 保留原生首次写入锁。
  回调顺序与宿主恢复接缝相同，但只能返回派发事实，不能据此声明加载完成。
  """

  def resume_session(self, target, *, location, before_dispatch, after_dispatch):
    raise SessionError(5, "resume_backend_unavailable")


def _writer_live(evidence, target):
  if (type(evidence) is not WriterEvidence or not _token(evidence.source)
      or evidence.coverage != "external-writers" or not callable(evidence.is_live)):
    raise SessionError(5, "writer_evidence_unavailable")
  if evidence.session != target.ref:
    raise SessionError(4, "writer_target_mismatch")
  try:
    live = evidence.is_live()
  except Exception:
    live = False
  if live is not True:
    raise SessionError(4, "writer_evidence_expired")


def _resume_target(target, location, cwd_override):
  if type(target) is not KnownSession or location != "here":
    raise SessionError(2, "invalid_resume_target")
  if target.confirmation == "unknown" or target.cwd_status == "unknown" or target.cwd is None:
    raise SessionError(5, "session_identity_unavailable")
  if cwd_override is not None and cwd_override != target.cwd:
    raise SessionError(2, "session_cwd_override")
  try:
    if not Path(target.cwd).is_dir():
      raise ValueError()
  except (ValueError, OSError):
    raise SessionError(2, "session_cwd_unavailable") from None


class ResumeCoordinator:
  """一次已接受请求的内存协调，不提供跨重启防重或生产后端准入。

  分步后端必须持续持有真实 writer；HostResumeBackend 则封装宿主内部恢复事务，
  不能为了满足前一种接缝而让父进程预抢原生锁。公开 CLI 只接入已准入的精确后端组合。
  """

  def __init__(self, backend, *, notice=None):
    self._backend = backend
    self._notice = notice
    self._lock = Lock()
    self._request = None
    self._outcome = None
    self._failure = None

  def snapshot(self):
    with self._lock:
      return self._outcome

  def _notify(self, outcome):
    if self._notice is not None:
      try:
        self._notice(outcome)
      except Exception:
        # 展示失败不参与控制、派发或原生退出的判定。
        pass

  def _publish(self, target, status, reason, **fields):
    value = ResumeOutcome(status=status, requested_session=target.ref,
      requested_cwd=target.cwd, reason=reason, **fields)
    with self._lock:
      self._outcome = value
    self._notify(value)
    return value

  def _receipt(self, target, receipt, expected_run_id=None):
    if (type(receipt) not in (LaunchReceipt, LoadReceipt)
        or type(receipt.run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", receipt.run_id) is None
        or receipt.run_id == target.run_id
        or expected_run_id is not None and receipt.run_id != expected_run_id):
      raise SessionError(4, "invalid_launch_receipt")
    if type(receipt) is LaunchReceipt:
      if receipt.exit_code is not None and (type(receipt.exit_code) is not int or not 0 <= receipt.exit_code <= 255):
        raise SessionError(4, "invalid_launch_receipt")
      failed = receipt.exit_code not in (None, 0)
      return self._publish(target, "failed" if failed else "launch_dispatched",
        "native_exit_failure" if failed else "load_unconfirmed",
        run_id=receipt.run_id, exit_code=receipt.exit_code)
    if type(receipt.loaded) is not bool or type(receipt.input_ready) is not bool:
      raise SessionError(4, "invalid_load_receipt")
    if not receipt.loaded:
      # 回执中回显的请求字段不成为实际会话；ready 单独也不能证明加载。
      return self._publish(target, "launch_dispatched", "load_unconfirmed", run_id=receipt.run_id)
    if type(receipt.session) is not SessionRef or receipt.session != target.ref or receipt.cwd != target.cwd:
      raise SessionError(4, "loaded_target_mismatch")
    return self._publish(target, "restored", "load_confirmed", run_id=receipt.run_id,
      session=receipt.session, cwd=receipt.cwd, input_ready=receipt.input_ready)

  def resume(self, target, *, location, cwd_override=None):
    request = (target, location, cwd_override)
    with self._lock:
      if self._request is not None:
        if self._request != request:
          raise SessionError(4, "resume_request_already_used")
        if self._failure is not None:
          raise SessionError(*self._failure)
        return self._outcome
      _resume_target(target, location, cwd_override)
      self._request = request
      self._outcome = ResumeOutcome(status="unknown", requested_session=target.ref,
        requested_cwd=target.cwd, reason="request_in_progress")
    dispatched = False
    dispatched_run_id = None
    acknowledged = False
    failure = None

    def before_dispatch(run_id):
      nonlocal dispatched, dispatched_run_id
      if (type(run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", run_id) is None
          or run_id == target.run_id):
        raise SessionError(4, "invalid_dispatch_identity")
      with self._lock:
        if dispatched:
          raise SessionError(4, "resume_already_dispatched")
        dispatched = True
        dispatched_run_id = run_id
        self._outcome = ResumeOutcome(status="unknown", requested_session=target.ref,
          requested_cwd=target.cwd, reason="dispatch_in_progress", run_id=run_id)
        outcome = self._outcome
      self._notify(outcome)

    def after_dispatch(run_id):
      nonlocal acknowledged
      with self._lock:
        if (not dispatched or type(run_id) is not str or run_id != dispatched_run_id
            or acknowledged):
          raise SessionError(4, "invalid_dispatch_acknowledgment")
        acknowledged = True
        self._outcome = ResumeOutcome(status="launch_dispatched", requested_session=target.ref,
          requested_cwd=target.cwd, reason="load_unconfirmed", run_id=run_id)
        outcome = self._outcome
      self._notify(outcome)

    try:
      backend = self._backend
      if isinstance(backend, (HostResumeBackend, HandoffResumeBackend)):
        receipt = backend.resume_session(target, location=location, before_dispatch=before_dispatch,
          after_dispatch=after_dispatch)
        if not dispatched:
          # 不符合事务接缝的返回也可能已执行，不能当作安全的未派发。
          dispatched = True
          raise SessionError(4, "dispatch_identity_unconfirmed")
        if isinstance(backend, HandoffResumeBackend) and type(receipt) is not LaunchReceipt:
          raise SessionError(4, "handoff_load_confirmation_unavailable")
        self._receipt(target, receipt, dispatched_run_id)
      elif backend is None or any(not callable(getattr(backend, method, None))
          for method in ("acquire_writer", "verify_session", "launch_session")):
        raise SessionError(5, "resume_backend_unavailable")
      else:
        with backend.acquire_writer(target) as evidence:
          _writer_live(evidence, target)
          verified = backend.verify_session(target, evidence)
          if (type(verified) is not KnownSession or verified.ref != target.ref
              or verified.scope != target.scope or verified.profile != target.profile or verified.cwd != target.cwd):
            raise SessionError(4, "verified_target_mismatch")
          _resume_target(verified, location, cwd_override)
          _writer_live(evidence, target)
          # 先记录可能派发；此后任何异常都不能被解释为尚未执行并再次调用后端。
          dispatched = True
          self._publish(target, "unknown", "dispatch_in_progress")
          receipt = backend.launch_session(verified, evidence, location=location)
          _writer_live(evidence, target)
          self._receipt(target, receipt)
    except SessionError as error:
      # 保留有限类别及退出码，不让后端异常中的路径/账号/会话正文进入结果或重查。
      code = error.code if type(error.code) is int and error.code in (2, 3, 4, 5, 6) else 6
      failure = (code, "resume_result_unconfirmed" if dispatched else "resume_preflight_rejected")
      self._publish(target, "unknown", failure[1], run_id=dispatched_run_id)
    except Exception:
      self._publish(target, "unknown", "launch_result_unknown" if dispatched else "resume_preflight_failed",
        run_id=dispatched_run_id)
      if not dispatched:
        failure = (5, "resume_preflight_failed")
    if failure is not None:
      with self._lock:
        self._failure = failure
      raise SessionError(*failure)
    return self.snapshot()


@dataclass(frozen=True)
class SessionEvent:
  """可信内部观察事件；不提供用户 JSON 或生产宿主注入入口。"""

  run_id: str
  emitter_epoch: str
  sequence: int
  kind: str
  session: SessionRef
  cwd: str
  observed_at_ns: int
  source: str

  def __post_init__(self):
    if (type(self.run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", self.run_id) is None
        or not _token(self.emitter_epoch) or not _token(self.source)
        or type(self.sequence) is not int or self.sequence <= 0
        or type(self.observed_at_ns) is not int or self.observed_at_ns <= 0
        or type(self.session) is not SessionRef or type(self.kind) is not str
        or self.kind not in ("session-selection", "session-confirmed", "load-confirmed", "session-sealed")):
      raise SessionError(2, "invalid_session_event")
    try:
      run_owners._absolute(self.cwd)
    except ValueError:
      raise SessionError(2, "invalid_session_event") from None


class SessionEventTracker:
  """单 run/epoch 的有界内存归并；缺口不能靠迟到事件补造证明。"""

  def __init__(self, *, run_id, emitter_epoch, manager_identity):
    if (type(run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", run_id) is None
        or not _token(emitter_epoch)):
      raise SessionError(2, "invalid_session_tracker")
    try:
      self._manager = run_owners._manager(manager_identity)
    except Exception:
      raise SessionError(2, "invalid_session_tracker") from None
    self._run_id = run_id
    self._epoch = emitter_epoch
    self._lock = Lock()
    self._sequence = 0
    self._recent = {}
    self._continuous = True
    self._current = None
    self._cwd = None
    self._loaded = False
    self._seal = None
    self._sealed_once = False
    self._exit_proven = False

  def _invalidate(self):
    self._continuous = False
    self._loaded = False
    self._seal = None

  def accept(self, event):
    if type(event) is not SessionEvent:
      raise SessionError(2, "invalid_session_event")
    if event.run_id != self._run_id or event.emitter_epoch != self._epoch:
      return False
    with self._lock:
      previous = self._recent.get(event.sequence)
      if previous is not None:
        if previous == event:
          return False
        self._invalidate()
        raise SessionError(4, "conflicting_session_sequence")
      if self._sealed_once:
        self._invalidate()
      if event.sequence <= self._sequence:
        # 迟到或已被淘汰的旧序号不覆盖较新前台，也不补齐连续性。
        self._invalidate()
        if event.sequence > self._sequence - 256:
          self._recent[event.sequence] = event
        return False
      if event.sequence != self._sequence + 1:
        self._invalidate()
      self._sequence = event.sequence
      self._recent[event.sequence] = event
      self._recent = {key: value for key, value in self._recent.items()
        if key > self._sequence - 256}
      if event.kind == "session-selection":
        self._loaded = False
        self._seal = None
      elif event.kind == "session-confirmed":
        self._current, self._cwd = event.session, event.cwd
        self._loaded = False
        self._seal = None
      else:
        exact = self._continuous and event.session == self._current and event.cwd == self._cwd
        if not exact:
          # 同一顺序源给出矛盾身份或目录，后续匹配不能重新建立本代证明。
          self._invalidate()
        elif event.kind == "load-confirmed":
          self._loaded = True
        else:
          self._seal = event.session
          self._sealed_once = True
      return True

  def record_release(self, observation):
    if (type(observation) is not run_owners.ReleaseObservation
        or observation.run_id != self._run_id or observation.complete is not True
        or observation.all_related_exited is not True):
      return False
    try:
      manager = run_owners._manager(observation.manager_identity)
    except Exception:
      return False
    if run_owners._encode(manager) != run_owners._encode(self._manager):
      return False
    with self._lock:
      self._exit_proven = True
    return True

  def snapshot(self):
    with self._lock:
      final = self._seal if self._continuous and self._exit_proven else None
      confirmation = ("final" if final is not None else "unknown" if self._current is None
        else "confirmed" if self._continuous and not self._exit_proven else "historical")
      return {"current": self._current, "cwd": self._cwd, "confirmation": confirmation,
        "load_confirmed": self._loaded, "final": final, "process_exit_proven": self._exit_proven}
