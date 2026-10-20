"""有限的官方 Herdr JSON API；固定端点，每个连接恰好一个请求。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import time
import uuid

from jsonschema import Draft202012Validator

from .errors import TermcfgError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SUPPORTED_PROTOCOLS = frozenset({22})


def _object(properties, required=None, *, extra=True):
  return {"type": "object", "properties": properties, "required": list(properties) if required is None else required, "additionalProperties": extra}


_STRING = {"type": "string", "minLength": 1}
_BOOL = {"type": "boolean"}
_UINT = {"type": "integer", "minimum": 0}
_TOKENS = {"type": "object", "maxProperties": 32, "propertyNames": {"pattern": "^[A-Za-z0-9_-]{1,32}$"}, "additionalProperties": {"type": "string"}}
_STATUS = {"enum": ["idle", "working", "blocked", "done", "unknown"]}
_PROVENANCE = _object({**{k: _STRING for k in ("repo_key", "repo_name", "repo_root", "checkout_path")}, "is_linked_worktree": _BOOL})
_WORKSPACE = _object({**{k: _STRING for k in ("workspace_id", "label", "active_tab_id")}, **{k: _UINT for k in ("number", "pane_count", "tab_count")}, "focused": _BOOL, "agent_status": _STATUS, "tokens": _TOKENS, "worktree": _PROVENANCE}, ["workspace_id", "number", "label", "focused", "pane_count", "tab_count", "active_tab_id", "agent_status"])
_PANE = _object({**{k: _STRING for k in ("pane_id", "terminal_id", "workspace_id", "tab_id")}, "focused": _BOOL, "agent_status": _STATUS, "revision": _UINT, "tokens": _TOKENS}, ["pane_id", "terminal_id", "workspace_id", "tab_id", "focused", "agent_status", "revision"])
_TAB = _object({**{k: _STRING for k in ("tab_id", "workspace_id", "label")}, "number": _UINT, "focused": _BOOL, "pane_count": _UINT, "agent_status": _STATUS})
_WORKTREE = _object({"path": _STRING, "label": _STRING, **{k: _BOOL for k in ("is_bare", "is_detached", "is_prunable", "is_linked_worktree")}, "open_workspace_id": _STRING, "branch": _STRING}, ["path", "label", "is_bare", "is_detached", "is_prunable", "is_linked_worktree"])
_SOURCE = _object({k: _STRING for k in ("repo_key", "repo_name", "repo_root", "source_checkout_path")})
_CAPABILITIES = _object({"live_handoff": _BOOL, "detached_server_daemon": _BOOL, "endpoint_protocol_generation": _UINT, "surface_interest": _BOOL, "health_check": _BOOL, "ssh_agent_registration": _BOOL}, ["live_handoff"])


def _result(kind, **fields):
  return _object({"type": {"const": kind}, **fields})


RESULT_SCHEMAS = {
  "ping": _result("pong", version=_STRING, protocol={"enum": sorted(SUPPORTED_PROTOCOLS)}, capabilities=_CAPABILITIES),
  "workspace.list": _result("workspace_list", workspaces={"type": "array", "items": _WORKSPACE}),
  "workspace.get": _result("workspace_info", workspace=_WORKSPACE),
  "workspace.focus": _result("workspace_info", workspace=_WORKSPACE),
  "workspace.report_metadata": _result("ok"),
  "worktree.list": _result("worktree_list", source=_SOURCE, worktrees={"type": "array", "items": _WORKTREE}),
  "worktree.open": _result("worktree_opened", workspace=_WORKSPACE, tab=_TAB, root_pane=_PANE, worktree=_WORKTREE, already_open=_BOOL),
  "tab.create": _result("tab_created", tab=_TAB, root_pane=_PANE),
  "tab.get": _result("tab_info", tab=_TAB),
  "tab.focus": _result("tab_info", tab=_TAB),
  "pane.current": _result("pane_current", pane=_PANE),
  "pane.list": _result("pane_list", panes={"type": "array", "items": _PANE}),
  "pane.get": _result("pane_info", pane=_PANE),
  "pane.focus": _result("pane_info", pane=_PANE),
  "pane.report_metadata": _result("ok"),
}
ALLOWED_METHODS = frozenset(RESULT_SCHEMAS)
READ_METHODS = frozenset({"ping", "workspace.list", "workspace.get", "worktree.list", "tab.get", "pane.current", "pane.list", "pane.get"})

_PATCH = {**_TOKENS, "maxProperties": 16, "additionalProperties": {"type": ["string", "null"]}}
_METADATA = {"source": _STRING, "tokens": _PATCH, "seq": {**_UINT, "maximum": 2**64 - 1}, "ttl_ms": {"type": "integer", "minimum": 1, "maximum": 86400000}}
PARAM_SCHEMAS = {
  "ping": _object({}, extra=False),
  "workspace.list": _object({}, extra=False),
  **{method: _object({"workspace_id": _STRING}, extra=False) for method in ("workspace.get", "workspace.focus")},
  "workspace.report_metadata": _object({"workspace_id": _STRING, **_METADATA}, ["workspace_id", "source", "tokens"], extra=False),
  "worktree.list": _object({"workspace_id": _STRING, "cwd": _STRING, "trust_repository": _BOOL}, [], extra=False),
  "worktree.open": _object({**{k: _STRING for k in ("workspace_id", "cwd", "path", "branch", "label")}, "focus": _BOOL, "trust_repository": _BOOL}, [], extra=False),
  "tab.create": _object({**{k: _STRING for k in ("workspace_id", "cwd", "label")}, "focus": _BOOL, "env": {"type": "object", "additionalProperties": {"type": "string"}}}, [], extra=False),
  **{method: _object({"tab_id": _STRING}, extra=False) for method in ("tab.get", "tab.focus")},
  "pane.current": _object({"caller_pane_id": _STRING}, extra=False),
  "pane.list": _object({"workspace_id": _STRING}, [], extra=False),
  **{method: _object({"pane_id": _STRING}, extra=False) for method in ("pane.get", "pane.focus")},
  "pane.report_metadata": _object({"pane_id": _STRING, **_METADATA}, ["pane_id", "source", "tokens"], extra=False),
}


class Deadline:
  def __init__(self, timeout=30):
    self.expires_at = time.monotonic() + timeout

  @property
  def expired(self):
    return time.monotonic() >= self.expires_at

  def remaining(self, limit=None):
    left = self.expires_at - time.monotonic()
    if left <= 0:
      raise TermcfgError(5, "Herdr operation deadline expired")
    return min(left, limit) if limit is not None else left


def _private_socket(info):
  return stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077


def _pin_endpoint(path):
  """逐层打开目录，拒绝符号链接及可被其他用户改写的祖先。"""
  if not hasattr(os, "O_PATH") or not Path("/proc/self/fd").is_dir():
    raise TermcfgError(5, "Herdr endpoint pinning requires Linux O_PATH and procfs")
  path = Path(path)
  if not path.is_absolute() or ".." in path.parts:
    raise TermcfgError(5, "Herdr socket path must be absolute")
  directory = None
  endpoint = None
  try:
    directory = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    for part in path.parts[1:-1]:
      next_fd = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
      os.close(directory)
      directory = next_fd
      info = os.fstat(directory)
      root_sticky = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
      if info.st_uid not in (0, os.getuid()) or (info.st_mode & 0o022 and not root_sticky):
        raise TermcfgError(5, "Herdr socket ancestor is not protected")
    parent = os.fstat(directory)
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
      raise TermcfgError(5, "Herdr socket requires a private same-user directory")
    endpoint = os.open(path.name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    info = os.fstat(endpoint)
    if not _private_socket(info):
      raise TermcfgError(5, "Herdr endpoint is not a private same-user socket")
    pinned = os.stat(f"/proc/self/fd/{endpoint}")
    identity = (info.st_dev, info.st_ino)
    if (pinned.st_dev, pinned.st_ino) != identity:
      raise TermcfgError(5, "Herdr endpoint pinning unavailable")
    result, endpoint = endpoint, None
    return result, identity
  except OSError:
    raise TermcfgError(6, "Cannot open protected Herdr endpoint") from None
  finally:
    if directory is not None:
      os.close(directory)
    if endpoint is not None:
      os.close(endpoint)


def _json(data):
  def unique(pairs):
    result = {}
    for key, value in pairs:
      if key in result:
        raise ValueError("duplicate field")
      result[key] = value
    return result
  return json.loads(data, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid constant")))


class HerdrClient:
  def __init__(self, socket_path, deadline, expected_identity=None):
    self.socket_path = str(socket_path)
    self.deadline = deadline
    self._fd, self.identity = _pin_endpoint(socket_path)
    if expected_identity is not None and self.identity != tuple(expected_identity):
      self.close()
      raise TermcfgError(4, "Herdr endpoint changed")

  @property
  def pinned_fd(self):
    if self._fd is None:
      raise TermcfgError(5, "Herdr endpoint is closed")
    return self._fd

  @property
  def pinned_address(self):
    return f"/proc/self/fd/{self.pinned_fd}"

  def __enter__(self):
    return self

  def __exit__(self, *args):
    self.close()

  def close(self):
    if self._fd is not None:
      os.close(self._fd)
      self._fd = None

  def request(self, method, params=None):
    params = {} if params is None else params
    if method not in ALLOWED_METHODS or not Draft202012Validator(PARAM_SCHEMAS[method]).is_valid(params):
      raise TermcfgError(5, "Unsupported Herdr API request")
    if self._fd is None:
      raise TermcfgError(5, "Herdr endpoint is closed")
    # 本次预算包含 connect/send/read；每次读不能重新获得五秒。
    end = time.monotonic() + self.deadline.remaining(5)
    request_id = uuid.uuid4().hex
    try:
      wire = json.dumps({"id": request_id, "method": method, "params": params}, ensure_ascii=False, allow_nan=False).encode() + b"\n"
    except (ValueError, TypeError, UnicodeError):
      raise TermcfgError(5, "Herdr API request cannot be encoded") from None
    connection = None
    attempted = False
    failure_code = 5
    def remaining(limit=None):
      left = min(self.deadline.remaining(), end - time.monotonic())
      if left <= 0:
        raise TimeoutError()
      return min(left, limit) if limit else left
    try:
      connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      connection.settimeout(remaining(2))
      connection.connect(f"/proc/self/fd/{self._fd}")
      connection.settimeout(remaining())
      attempted = True
      connection.sendall(wire)
      data = bytearray()
      while b"\n" not in data:
        connection.settimeout(remaining())
        chunk = connection.recv(min(65536, MAX_RESPONSE_BYTES + 1 - len(data)))
        if not chunk:
          raise ValueError("incomplete response")
        data.extend(chunk)
        if len(data) > MAX_RESPONSE_BYTES:
          raise ValueError("response too large")
      line, rest = data.split(b"\n", 1)
      if rest.strip():
        raise ValueError("multiple responses")
      reply = _json(line)
      if not isinstance(reply, dict) or reply.get("id") != request_id or set(reply) not in ({"id", "result"}, {"id", "error"}):
        raise ValueError("invalid envelope")
      if "error" in reply:
        if not Draft202012Validator(_object({"code": _STRING, "message": {"type": "string"}}, extra=False)).is_valid(reply["error"]):
          raise ValueError("invalid error")
        # 不透传上游消息，避免路径、会话正文或秘密进入异常。
        failure_code = 4 if reply["error"]["code"] in {"pane_not_found", "workspace_not_found", "tab_not_found"} else 5
        raise TermcfgError(failure_code, "Herdr API rejected request")
      result = reply["result"]
      if not Draft202012Validator(RESULT_SCHEMAS[method]).is_valid(result):
        raise ValueError("invalid result")
      return result
    except TermcfgError as error:
      if attempted and method not in READ_METHODS and error.reason != "Herdr API rejected request":
        raise TermcfgError(4, "Herdr mutation result is unknown") from None
      raise
    except (OSError, ValueError, TypeError, UnicodeError):
      if attempted and method not in READ_METHODS:
        raise TermcfgError(4, "Herdr mutation result is unknown") from None
      raise TermcfgError(5, "Herdr API unavailable or incompatible") from None
    finally:
      if connection is not None:
        connection.close()


def _cli_json(argv, deadline):
  try:
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=deadline.remaining(5), check=False)
    if result.returncode or len(result.stdout.encode()) > MAX_RESPONSE_BYTES:
      raise ValueError("CLI failed")
    return _json(result.stdout)
  except (OSError, ValueError, TypeError, subprocess.SubprocessError):
    raise TermcfgError(5, "Herdr public CLI unavailable or incompatible") from None


def discover(binary, session, deadline):
  result = _cli_json([str(binary), "session", "list", "--json"], deadline)
  info_schema = _object({**{k: _STRING for k in ("name", "socket_path", "session_dir")}, "default": _BOOL, "running": _BOOL, "connection_error": _STRING}, ["name", "default", "running", "socket_path", "session_dir"])
  if not Draft202012Validator(_object({"sessions": {"type": "array", "items": info_schema}})).is_valid(result):
    raise TermcfgError(5, "Herdr session discovery is malformed")
  matches = [item for item in result["sessions"] if item["name"] == session]
  if len(matches) > 1:
    raise TermcfgError(5, "Herdr session discovery is ambiguous")
  if not matches:
    return None
  info = matches[0]
  if info.get("connection_error"):
    raise TermcfgError(5, "Herdr session connection failed")
  return info if info["running"] else None


def start_headless(binary, session, deadline, repo_root):
  deadline.remaining()
  environment = dict(os.environ)
  # 新 server 不继承旧 pane 的一次性交接或调用上下文。
  for name in ("ROTOM_WORK_LAUNCH_V1", "HERDR_PANE_ID", "HERDR_WORKSPACE_ID",
               "HERDR_TAB_ID", "HERDR_TERMINAL_ID", "HERDR_SOCKET_PATH",
               "HERDR_SESSION", "HERDR_ENV"):
    environment.pop(name, None)
  environment["PATH"] = str(Path(repo_root)) + os.pathsep + environment.get("PATH", "")
  try:
    # 原生目录沿用进程umask；不继承调用shell的022而生成755 socket父目录。
    return subprocess.Popen([str(binary), "--session", session, "server"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, umask=0o077, env=environment)
  except OSError:
    raise TermcfgError(5, "Cannot start Herdr headless server") from None


def verify_schema(binary, deadline):
  """核对安装包公开 schema 的能力；不把产品版本字符串作为门禁。"""
  schema = _cli_json([str(binary), "api", "schema", "--json"], deadline)
  try:
    if schema["protocol"] not in SUPPORTED_PROTOCOLS or type(schema["protocol"]) is not int or schema["schema_version"] != 1:
      raise ValueError("unsupported protocol")
    request = schema["schemas"]["request"]
    definitions = request["$defs"]
    methods = {}
    for variant in request["oneOf"]:
      properties = variant["properties"]
      name = properties["method"]["const"]
      reference = properties["params"]["$ref"]
      if not reference.startswith("#/schemas/request/$defs/") or name in methods:
        raise ValueError("invalid method definition")
      methods[name] = definitions[reference.rsplit("/", 1)[1]]
    for method, local in PARAM_SCHEMAS.items():
      params = methods[method]
      if params.get("type") != "object":
        raise ValueError("invalid parameters")
      properties = params.get("properties", {})
      # 当前 wrapper 使用的公开字段必须保留；新增 native 字段允许存在。
      if not set(local["properties"]).issubset(properties):
        raise ValueError("missing capability")
      if not set(params.get("required", [])).issubset(local["required"]):
        raise ValueError("new required parameter")
      for name, expected in local["properties"].items():
        actual = properties[name]
        if name == "tokens":
          if actual != _PATCH:
            raise ValueError("incompatible metadata token limits")
        elif name == "env":
          if actual.get("type") != "object" or actual.get("additionalProperties") != {"type": "string"}:
            raise ValueError("invalid environment capability")
        elif "type" in expected and actual.get("type") != expected["type"]:
          # 官方 Option<T> 可用 type 数组或 anyOf 表示。
          choices = actual.get("anyOf", [])
          types = actual.get("type", [])
          if not (isinstance(types, list) and expected["type"] in types) and not any(choice.get("type") == expected["type"] for choice in choices):
            raise ValueError("incompatible parameter")
    return schema
  except (KeyError, TypeError, ValueError, AttributeError):
    raise TermcfgError(5, "Herdr public schema lacks required capabilities") from None
