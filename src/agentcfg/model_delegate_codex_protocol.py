"""固定 Codex app-server 的只读请求编码；不授权、不发送、不恢复线程。"""

import posixpath
import re
import unicodedata

from .schema import ConfigError


_ACTIONS = {
  "thread_start": ("thread/start", set()),
  "thread_resume": ("thread/resume", {"thread_id"}),
  "turn_start": ("turn/start", {"thread_id", "text"}),
  "turn_steer": ("turn/steer", {"thread_id", "turn_id", "text"}),
  "turn_interrupt": ("turn/interrupt", {"thread_id", "turn_id"}),
}


def _invalid():
  raise ConfigError("codex-delegate-request-invalid") from None


def _closed(value, fields):
  # 先检查原生类型，不调用 dict/str 子类的用户钩子。
  if type(value) is not dict or any(type(key) is not str for key in value): _invalid()
  if value.keys() != fields: _invalid()


def _text(value, *, characters=65536, byte_limit=65536, no_nul=False):
  if type(value) is not str or not 1 <= len(value) <= characters or no_nul and "\0" in value: _invalid()
  try:
    if len(value.encode("utf8")) > byte_limit: _invalid()
  except UnicodeError:
    _invalid()
  return value


def _native_id(value):
  _text(value, characters=200, byte_limit=200)
  if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value) or value == "--last": _invalid()
  return value


def build_codex_delegate_request(value):
  """捕获原生字典/scalar并返回独立 wire 数据；ID 与只读设置均不构成授权。"""
  if type(value) is not dict: _invalid()
  value = dict.copy(value)
  if any(type(key) is not str for key in value): _invalid()
  if not {"action", "request_id", "binding"} <= value.keys(): _invalid()
  action = value["action"]
  if type(action) is not str: _invalid()
  if action not in _ACTIONS:
    raise ConfigError("codex-delegate-action-unsupported") from None
  method, fields = _ACTIONS[action]
  _closed(value, {"action", "request_id", "binding"} | fields)
  request_id = _text(value["request_id"], characters=200, byte_limit=800, no_nul=True)
  binding = value["binding"]
  if type(binding) is not dict: _invalid()
  binding = dict.copy(binding)
  _closed(binding, {"model", "model_provider", "cwd"})
  model = _text(binding["model"])
  provider = _text(binding["model_provider"], characters=256)
  if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in model + provider): _invalid()
  cwd = _text(binding["cwd"], no_nul=True)
  if not cwd.startswith("/") or cwd == "/" or cwd.startswith("//") or posixpath.normpath(cwd) != cwd: _invalid()
  # 不访问文件系统；lexical 规范不代表存在、所有权或实际 sandbox 隔离。
  identities = {field: _native_id(value[field]) for field in fields & {"thread_id", "turn_id"}}
  if "text" in fields:
    text = _text(value["text"])
    if not text.strip(): _invalid()
    message = [{"type": "text", "text": text, "text_elements": []}]
  if action in {"thread_start", "thread_resume"}:
    params = {"model": model, "modelProvider": provider, "cwd": cwd, "approvalPolicy": "never", "sandbox": "read-only"}
    if action == "thread_resume": params["threadId"] = identities["thread_id"]
  elif action == "turn_start":
    params = {"threadId": identities["thread_id"], "input": message, "model": model, "cwd": cwd,
      "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly", "networkAccess": False}}
  elif action == "turn_steer":
    params = {"threadId": identities["thread_id"], "expectedTurnId": identities["turn_id"], "input": message}
  else:
    params = {"threadId": identities["thread_id"], "turnId": identities["turn_id"]}
  # 固定 ClientRequest 没有 jsonrpc 字段；显式模型/provider 只在支持的动作位置发送。
  return {"id": request_id, "method": method, "params": params}
