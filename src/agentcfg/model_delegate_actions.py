"""schema 3 的纯规范动作及稳定来源身份；不授权、不读取路径、不登记意图。"""

import hashlib
import json
import posixpath
import re
import unicodedata

from .schema import ConfigError


_COMMON = {"schema_version", "action", "request_id"}
_REQUIRED = {
  "submit": {"backend", "mode", "preset", "task", "model", "cwd", "timeout_seconds"},
  "message": {"run_id", "text"},
  "continue": {"run_id", "text", "timeout_seconds"},
  "cancel": {"run_id"},
}
_DEFAULTS = {"context_artifact": None, "feedback_required": False, "allow_workspace_write": False, "worktree_root": None}


def _fail(code):
  raise ConfigError(code) from None


def _snapshot(value, code):
  if type(value) is not dict: _fail(code)
  captured = dict.copy(value)
  if any(type(key) is not str for key in captured): _fail(code)
  return captured


def _closed(value, required, optional, code):
  # 原生 dict/scalar 先校验，避免外来 keys/str/deepcopy 等用户钩子。
  if type(value) is not dict or any(type(key) is not str for key in value): _fail(code)
  if not required <= value.keys() or value.keys() - required - optional: _fail(code)


def _text(value, code, *, characters=65536, byte_limit=65536, no_nul=False, nonblank=False):
  if type(value) is not str or not 1 <= len(value) <= characters or no_nul and "\0" in value: _fail(code)
  try:
    if len(value.encode("utf8")) > byte_limit: _fail(code)
  except UnicodeError:
    _fail(code)
  if nonblank and not value.strip(): _fail(code)
  return value


def _identity(value, code):
  _text(value, code, characters=200, byte_limit=200)
  if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value): _fail(code)
  return value


def _path(value, code):
  _text(value, code, no_nul=True)
  if not value.startswith("/") or value == "/" or value.startswith("//") or posixpath.normpath(value) != value: _fail(code)
  return value


def _timeout(value, code):
  if type(value) is not int or not 1 <= value <= 2**53 - 1: _fail(code)
  return value


def _enum(value, choices, code):
  if type(value) is not str or value not in choices: _fail(code)
  return value


def capture_delegate_action(value):
  """返回独立规范数据；结构上的 implement/write 请求不创建 Writer 权限。"""
  code = "delegate-action-invalid"
  value = _snapshot(value, code)
  _closed(value, _COMMON, set().union(*_REQUIRED.values(), _DEFAULTS), code)
  if type(value["schema_version"]) is not int or value["schema_version"] != 3: _fail(code)
  action = value["action"]
  if type(action) is not str: _fail(code)
  if action not in _REQUIRED: _fail("delegate-action-unsupported")
  _closed(value, _COMMON | _REQUIRED[action], set(_DEFAULTS) if action == "submit" else set(), code)
  if action == "submit":
    model = _snapshot(value["model"], code)
    _closed(model, {"provider_id", "model_id"}, set(), code)
  result = {"schema_version": 3, "action": action,
    "request_id": _text(value["request_id"], code, characters=200, byte_limit=800, no_nul=True)}
  if action != "submit":
    result["run_id"] = _identity(value["run_id"], code)
    if action != "cancel": result["text"] = _text(value["text"], code, nonblank=True)
    if action == "continue": result["timeout_seconds"] = _timeout(value["timeout_seconds"], code)
    return result
  result.update({
    "backend": _enum(value["backend"], ("pi", "codex"), code),
    "mode": _enum(value["mode"], ("review", "investigate", "implement"), code),
    "preset": _enum(value["preset"], ("general", "context", "challenge", "plan", "research", "review", "scout"), code),
    "task": _text(value["task"], code, nonblank=True), "cwd": _path(value["cwd"], code),
    "timeout_seconds": _timeout(value["timeout_seconds"], code),
  })
  model_id = _text(model["model_id"], code, nonblank=True)
  if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in model_id): _fail(code)
  result["model"] = {"provider_id": _identity(model["provider_id"], code), "model_id": model_id}
  for field, default in _DEFAULTS.items():
    captured = value.get(field, default)
    if field in {"feedback_required", "allow_workspace_write"}:
      if type(captured) is not bool: _fail(code)
    elif captured is not None:
      captured = _path(captured, code) if field == "worktree_root" else _identity(captured, code)
    result[field] = captured
  if result["mode"] == "implement":
    if result["allow_workspace_write"] is not True or result["worktree_root"] is None: _fail(code)
  elif result["allow_workspace_write"] or result["worktree_root"] is not None:
    _fail(code)
  return result


def capture_delegate_origin(value):
  """来源必须由受信控制面供给；这些标签本身不认证 caller。"""
  code = "delegate-origin-invalid"
  value = _snapshot(value, code)
  _closed(value, {"instance_id", "host", "source_id", "task_id", "step_id"}, set(), code)
  result = {"instance_id": _identity(value["instance_id"], code), "host": _enum(value["host"], ("pi", "codex", "cli"), code),
    "source_id": _identity(value["source_id"], code)}
  for field in ("task_id", "step_id"):
    result[field] = None if value[field] is None else _identity(value[field], code)
  return result


def _digest(value):
  # 与 deployment.json_bytes 格式等价；这里只序列化已捕获的原生数据，不执行外来 hook。
  encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode("utf8")
  return hashlib.sha256(encoded).hexdigest()


def delegate_action_identity(origin, value):
  captured_origin = capture_delegate_origin(origin)
  action = capture_delegate_action(value)
  return {"key": _digest({"origin": captured_origin, "request_id": action["request_id"]}), "request_digest": _digest(action)}
