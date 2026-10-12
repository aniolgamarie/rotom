"""固定公开app-server有界stdio；turn不是model计量，生产发送默认不可用。"""
from copy import deepcopy
import json
import os
import selectors
import time
import uuid

from .model_delegate_codex_protocol import build_codex_delegate_request
from .storage import Conflict


class CodexAppServerTransport:
  def __init__(self, process, *, check, stop, deadline, synthetic_oracle=None, selector=None):
    if (not callable(check) or not callable(stop) or type(deadline) not in (int, float)
        or not time.monotonic() < deadline <= time.monotonic() + 60):
      raise Conflict("DELEGATE_CODEX_TRANSPORT_INVALID")
    self.process, self.check, self.stop, self.deadline = process, check, stop, deadline
    self.stdin, self.stdout = process.stdin, process.stdout
    self.write, self.flush = self.stdin.write, self.stdin.flush
    self.synthetic_oracle = synthetic_oracle
    self.selector = selector or selectors.DefaultSelector()
    self.selector.register(self.stdout, selectors.EVENT_READ)
    self.buffer = b""; self.bytes = 0; self.frames = 0; self.ids = set(); self.events = []
    self.retired = False; self.stopped = False
    self.thread_id = None; self.turn_id = None

  def _current(self):
    if self.retired or time.monotonic() >= self.deadline: raise Conflict("DELEGATE_CODEX_TRANSPORT_UNKNOWN")
    try: valid = self.check()
    except Exception: raise Conflict("DELEGATE_CODEX_TRANSPORT_UNKNOWN") from None
    if valid is not True: raise Conflict("DELEGATE_CODEX_TRANSPORT_UNKNOWN")

  def _send(self, frame):
    self._current()
    data = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    if len(data) > 65536: raise Conflict("DELEGATE_CODEX_FRAME_LIMIT")
    try: self.write(data); self.flush()
    except Exception: raise Conflict("DELEGATE_CODEX_SEND_UNKNOWN") from None
    self._current()

  def _receive(self):
    while b"\n" not in self.buffer:
      self._current()
      if not self.selector.select(max(0, self.deadline - time.monotonic())):
        raise Conflict("DELEGATE_CODEX_TRANSPORT_UNKNOWN")
      self._current()
      chunk = os.read(self.stdout.fileno(), min(65536, 1024 * 1024 + 1 - len(self.buffer)))
      if not chunk: raise Conflict("DELEGATE_CODEX_EOF_UNKNOWN")
      self.bytes += len(chunk); self.buffer += chunk
      if self.bytes > 16 * 1024 * 1024 or len(self.buffer) > 1024 * 1024: raise Conflict("DELEGATE_CODEX_FRAME_LIMIT")
    raw, self.buffer = self.buffer.split(b"\n", 1); self.frames += 1
    if self.frames > 4096: raise Conflict("DELEGATE_CODEX_FRAME_LIMIT")
    try:
      frame = json.loads(raw)
      if type(frame) is not dict or any(type(key) is not str for key in frame): raise ValueError()
      return frame
    except (ValueError, TypeError, UnicodeError): raise Conflict("DELEGATE_CODEX_FRAME_INVALID") from None

  def exchange(self, wire):
    self._current()
    request_id = wire["id"]
    if request_id in self.ids: raise Conflict("DELEGATE_CODEX_REQUEST_REPLAY")
    self.ids.add(request_id)  # 先记一次提交；失败也不能以同ID补发。
    self._send(wire)
    while True:
      frame = self._receive()
      if "id" in frame:
        if frame["id"] != request_id or set(frame) not in ({"id", "result"}, {"id", "error"}):
          raise Conflict("DELEGATE_CODEX_RESPONSE_IDENTITY")
        if "error" in frame: raise Conflict("DELEGATE_CODEX_REMOTE_REJECTED")
        self._current(); return deepcopy(frame["result"])
      if (set(frame) not in ({"method", "params"}, {"method", "params", "emittedAtMs"})
          or type(frame["method"]) is not str or type(frame["params"]) is not dict
          or "emittedAtMs" in frame and (type(frame["emittedAtMs"]) is not int
            or not -(2 ** 63) <= frame["emittedAtMs"] < 2 ** 63)):
        raise Conflict("DELEGATE_CODEX_EVENT_INVALID")
      if len(self.events) >= 256: raise Conflict("DELEGATE_CODEX_EVENT_LIMIT")
      self.events.append(deepcopy(frame))  # 仅进程内私有观察，不记录正文/错误到日志。

  def initialize(self):
    result = self.exchange({"id": uuid.uuid4().hex, "method": "initialize", "params": {
      "clientInfo": {"name": "agentcfg-unified-delegate", "version": "3"}, "capabilities": {"experimentalApi": False}}})
    self._send({"method": "initialized", "params": {}})
    return result

  def action(self, value):
    wire = build_codex_delegate_request(value)
    if value["action"] in ("turn_start", "turn_steer"):
      # 合成oracle必须来自受信fixture；该门只用于合成生命周期，不能计turn为model calls。
      if not callable(self.synthetic_oracle) or self.synthetic_oracle(deepcopy(value)) is not True:
        raise Conflict("DELEGATE_CODEX_METER_UNAVAILABLE")
    if "thread_id" in value and value["thread_id"] != self.thread_id: raise Conflict("DELEGATE_CODEX_THREAD_IDENTITY")
    if "turn_id" in value and value["turn_id"] != self.turn_id: raise Conflict("DELEGATE_CODEX_TURN_IDENTITY")
    result = self.exchange(wire)
    if value["action"] in ("thread_start", "thread_resume"):
      identity = result.get("thread", {}).get("id") if type(result) is dict else None
      if type(identity) is not str or not identity or value["action"] == "thread_resume" and identity != value["thread_id"]:
        raise Conflict("DELEGATE_CODEX_THREAD_IDENTITY")
      self.thread_id = identity
    elif value["action"] == "turn_start":
      identity = result.get("turn", {}).get("id") if type(result) is dict else None
      if type(identity) is not str or not identity: raise Conflict("DELEGATE_CODEX_TURN_IDENTITY")
      self.turn_id = identity
    return result

  def close(self):
    if self.retired: return
    self.retired = True
    try:
      if not self.stopped:
        self.stopped = True
        self.stop()  # 原controller停止已登记执行；EOF/关管道不是终止证明。
    finally:
      self.selector.close()
