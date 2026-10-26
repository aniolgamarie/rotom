"""仅 fake transport 的一次接收原型；不提供宿主适配器或自动继续准入。"""
from dataclasses import asdict, dataclass
import hashlib
import re
import uuid

from agentcfg.sessions import SessionRef
from agentcfg.storage import Conflict


_ERROR = "合成输入接收无法确认；保留未知状态，不能重发"


@dataclass(frozen=True)
class InputTarget:
  """测试提供的可信前提；这些字段不是从官方 inserted payload 推导的。"""

  run_id: str
  session: SessionRef
  agent: object
  foreground_generation: int
  input_ready: bool
  writer_covered: bool
  load_confirmed: bool
  observation_complete: bool

  def __post_init__(self):
    if (type(self.run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", self.run_id) is None
        or type(self.session) is not SessionRef or self.agent is None
        or type(self.foreground_generation) is not int or self.foreground_generation <= 0
        or any(type(value) is not bool for value in (self.input_ready, self.writer_covered,
          self.load_confirmed, self.observation_complete))):
      raise Conflict(_ERROR)


class InputProbe:
  """单次内存尝试；accepted 只描述 live inbox，不证明模型完成或持久去重。"""

  def __init__(self, target, *, transport, current_target, persist_intent):
    if (type(target) is not InputTarget or not callable(current_target) or not callable(persist_intent)
        or any(not callable(getattr(transport, name, None)) for name in ("subscribe", "followup"))):
      raise Conflict(_ERROR)
    self._target = target
    self._transport = transport
    self._current_target = current_target
    self._persist_intent = persist_intent
    self._status = "bound"
    self._message_id = None
    self._digest = None
    self._window = False
    self._matches = 0
    self._send_attempted = False

  def snapshot(self):
    return {"status": self._status, "message_id": self._message_id, "text_sha256": self._digest,
      "send_attempted": self._send_attempted, "execution_complete": False,
      "cross_restart_deduplication": False}

  def _check(self):
    current, target = self._current_target(), self._target
    if (self._status == "unknown" or type(current) is not InputTarget
        or current.run_id != target.run_id or current.session != target.session
        or current.agent is not target.agent or current.foreground_generation != target.foreground_generation
        or any(value is not True for value in (current.input_ready, current.writer_covered,
          current.load_confirmed, current.observation_complete,
          target.input_ready, target.writer_covered, target.load_confirmed, target.observation_complete))):
      raise Conflict(_ERROR)

  def _inserted(self, payload):
    try:
      self._check()
      if (not self._window or self._matches != 0 or type(payload) is not dict
          or payload.get("agent") is not self._target.agent or type(payload.get("message")) is not dict
          or payload["message"].get("id") != self._message_id):
        raise Conflict(_ERROR)
      # 不保留事件、message 对象或正文；无上游 sequence 字段假设。
      self._matches = 1
    except Exception:
      self._status = "unknown"

  def request_followup(self, approved_text):
    if self._message_id is not None:
      raise Conflict(_ERROR)
    if type(approved_text) is not str or not approved_text:
      raise Conflict(_ERROR)
    try:
      digest = hashlib.sha256(approved_text.encode("utf-8", errors="strict")).hexdigest()
    except UnicodeError:
      raise Conflict(_ERROR) from None
    self._message_id = uuid.uuid4().hex
    self._digest = digest
    unsubscribe = None
    failed = False
    try:
      self._check()
      self._status = "intent"
      self._persist_intent({"schema_version": 1, "kind": "fake-input-intent",
        "run_id": self._target.run_id, "session": asdict(self._target.session),
        "foreground_generation": self._target.foreground_generation,
        "message_id": self._message_id, "text_sha256": self._digest})
      self._check()
      unsubscribe = self._transport.subscribe(self._inserted)
      if not callable(unsubscribe):
        raise Conflict(_ERROR)
      self._check()
      self._status = "sending"
      self._window = True
      self._send_attempted = True
      try:
        # 这是 fake 接缝签名，不声称是官方 UserMessage 构造或宿主适配 API。
        self._transport.followup(self._target.agent, self._message_id, approved_text)
      finally:
        self._window = False
      self._check()
      if self._matches != 1:
        raise Conflict(_ERROR)
    except Exception:
      failed = True
    finally:
      self._window = False
      if callable(unsubscribe):
        try:
          unsubscribe()
        except Exception:
          failed = True
    if not failed:
      try:
        self._check()
      except Exception:
        failed = True
    if failed or self._status == "unknown":
      self._status = "unknown"
      raise Conflict(_ERROR) from None
    self._status = "accepted"
    return self.snapshot()
