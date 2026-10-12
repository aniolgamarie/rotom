"""共同 frame/endpoint JSON 动作前边界；仅 fake IO/连接/服务，无 listener。"""
from io import BytesIO
import builtins
import importlib.util
import json
from pathlib import Path
import socket
import stat
import traceback
from types import SimpleNamespace

import pytest
from agentcfg import pi_control as control
from agentcfg import pi_supervisor as supervisor
from agentcfg.deployment import json_bytes
from agentcfg.storage import Conflict

SECRET = "SYNTHETIC_CONTROL_JSON_SECRET"
MESSAGE = {"schema_version": 1, "request_id": "synthetic", "method": "handshake", "args": {}}


def test_control_client_import_does_not_load_deployment_configuration(monkeypatch):
  original = builtins.__import__
  calls = []
  def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 1 and name == "deployment":
      calls.append(name)
      raise AssertionError("control client must not load deployment configuration")
    return original(name, globals, locals, fromlist, level)
  monkeypatch.setattr(builtins, "__import__", guarded)
  spec = importlib.util.spec_from_file_location("agentcfg._control_import_test", control.__file__)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  assert calls == []
  assert module.read_frame(BytesIO(b'{"message":"literal"}\n')) == {"message": "literal"}


def invalid(call, message):
  with pytest.raises(Conflict) as caught: call()
  error = caught.value
  assert type(error) is Conflict and error.args == (message,)
  assert error.__context__ is None and error.__cause__ is None and not hasattr(error, "doc")
  assert SECRET not in "".join(traceback.format_exception(error))
  return error


def bad_frame(mode):
  raw = '{"schema_version":1,"request_id":"synthetic","method":"handshake","args":{}}'
  if mode == "utf16be": return b"\xfe\xff" + (raw + "\n").encode("utf-16-be")
  if mode == "bom": return b"\xef\xbb\xbf" + raw.encode() + b"\n"
  if mode == "root-duplicate": raw = raw.replace('"method":"handshake"', '"method":"bad","m\\u0065thod":"handshake"')
  elif mode == "nested-duplicate": raw = raw.replace('"args":{}', '"args":{"x":0,"\\u0078":1}')
  elif mode in ("NaN", "Infinity", "-Infinity", "1e999"): raw = raw.replace('"args":{}', '"args":{"x":' + mode + '}')
  elif mode == "malformed": raw = '{"secret":'
  return raw.encode() + b"\n"


@pytest.mark.parametrize("mode", ["utf16be", "bom", "root-duplicate", "nested-duplicate", "NaN", "Infinity", "-Infinity", "1e999", "malformed"])
def test_read_frame_strict_format(mode): invalid(lambda: control.read_frame(BytesIO(bad_frame(mode))), "监督消息格式无效")


@pytest.mark.parametrize("raw,message", [(b"", "监督消息缺失或超过长度限制"), (b'{}', "监督消息缺失或超过长度限制"), (b' '*(1024*1024)+b'\n', "监督消息缺失或超过长度限制"), (b'[]\n', "监督消息必须是对象"), (b'1\n', "监督消息必须是对象")])
def test_existing_frame_size_lf_and_topdict_messages(raw, message): invalid(lambda: control.read_frame(BytesIO(raw)), message)


def test_read_frame_valid_unicode_whitespace_key_order_and_float():
  value = {"z": 1.25, "a": {"value": "合成"}}
  assert control.read_frame(BytesIO((" \t" + json.dumps(value, ensure_ascii=False) + "\r\n").encode())) == value


@pytest.mark.parametrize("kind", ["object", "bytes-subclass", "bytearray", "str"])
def test_frame_type_before_truth_len_endswith_and_ambient_context(kind):
  calls = []
  class Poison:
    def __bool__(self): calls.append("bool"); raise RuntimeError(SECRET)
    def __len__(self): calls.append("len"); raise RuntimeError(SECRET)
    def endswith(self, *args): calls.append("endswith"); raise RuntimeError(SECRET)
  class Payload(bytes):
    def __len__(self): calls.append("len"); raise RuntimeError(SECRET)
    def endswith(self, *args): calls.append("endswith"); raise RuntimeError(SECRET)
  value = {"object": Poison(), "bytes-subclass": Payload(b'{}\n'), "bytearray": bytearray(b'{}\n'), "str": '{}\n'}[kind]
  stream = SimpleNamespace(readline=lambda limit: value)
  try: raise RuntimeError(SECRET)
  except RuntimeError: invalid(lambda: control.read_frame(stream), "监督消息格式无效")
  assert calls == []


@pytest.mark.parametrize("raw,message", [(b'{"secret":\n', "监督消息格式无效"), (b'{"x":NaN}\n', "监督消息格式无效"), (b'[]\n', "监督消息必须是对象"), (b'', "监督消息缺失或超过长度限制")])
def test_actual_conflict_context_and_parser_doc_absent(raw, message):
  try: raise RuntimeError(SECRET)
  except RuntimeError: invalid(lambda: control.read_frame(BytesIO(raw)), message)


class Stream:
  def __init__(self, raw, events): self.input = BytesIO(raw); self.output = BytesIO(); self.events = events
  def __enter__(self): return self
  def __exit__(self, *args): return False
  def readline(self, limit): self.events.append(("readline", limit)); return self.input.readline(limit)
  def write(self, raw): self.events.append(("write",)); return self.output.write(raw)
  def flush(self): self.events.append(("flush",))


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
  record = {"schema_version": 1, "owner": {"finite": 1.25}, "socket_name": "control.sock", "socket_identity": {"device": 11, "inode": 22}, "user_capability": "synthetic-user"}
  events = []; state = {"raw": json_bytes(record), "mode": 0o600, "error": None, "stat_error": None, "peer": 41, "reply": json_bytes({"ok": True, "result": {"finite": 1.25}}), "events": events, "enforce_bound": False}
  class Tree:
    def __init__(self, parent): events.append(("tree", parent)); self.fd = 202
    def __enter__(self): events.append(("enter",)); return self
    def __exit__(self, *args): events.append(("exit",)); return False
    def read(self, name, **kwargs):
      events.append(("read", name, kwargs));
      if state["error"] is not None: raise state["error"]
      if state["enforce_bound"] and kwargs.get("max_bytes") is not None and len(state["raw"]) > kwargs["max_bytes"]: raise Conflict(SECRET)
      return None if state["raw"] is None else (state["raw"], state["mode"], None)
  def status(name, **kwargs):
    events.append(("stat", name, kwargs))
    if state["stat_error"]: raise state["stat_error"]
    return SimpleNamespace(st_mode=stat.S_IFSOCK|0o600, st_uid=41, st_dev=11, st_ino=22)
  fake_os = SimpleNamespace(stat=status, geteuid=lambda: 41, O_RDONLY=0, O_DIRECTORY=65536,
    open=lambda name, flags: events.append(("open", name, flags)) or 101,
    fchdir=lambda fd: events.append(("chdir", fd)), close=lambda fd: events.append(("close-fd", fd)))
  class Connection:
    def close(self): state["connection_closed"] = state.get("connection_closed", 0) + 1
    def settimeout(self, timeout): events.append(("timeout", timeout))
    def connect(self, name): events.append(("connect", name))
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def makefile(self, mode): events.append(("makefile", mode)); self.stream = Stream(state["reply"], events); return self.stream
  connection = Connection()
  def create(family, kind): events.append(("socket", family, kind)); return connection
  def peer(value): assert value is connection; events.append(("peer",)); return state["peer"]
  monkeypatch.setattr(control, "Tree", Tree); monkeypatch.setattr(control, "os", fake_os)
  monkeypatch.setattr(control, "socket", SimpleNamespace(socket=create, AF_UNIX=socket.AF_UNIX, SOCK_STREAM=socket.SOCK_STREAM)); monkeypatch.setattr(control, "peer_uid", peer)
  state.update(record=record, connection=connection, path=tmp_path / "endpoint.json")
  return state


def endpoint_bytes(record, mode):
  text = json.dumps(record, separators=(",", ":"))
  if mode == "utf16be": return b"\xfe\xff" + text.encode("utf-16-be")
  if mode == "bom": return b"\xef\xbb\xbf" + text.encode()
  if mode == "root-duplicate": text = text.replace('"socket_name":"control.sock"', '"socket_name":"bad","socket_\\u006eame":"control.sock"')
  elif mode == "nested-duplicate": text = text.replace('"device":11', '"device":0,"d\\u0065vice":11')
  elif mode in ("NaN", "Infinity", "-Infinity", "1e999"): text = text.replace('"finite":1.25', '"finite":'+mode)
  elif mode == "malformed": text = '{"secret":'
  return text.encode()


@pytest.mark.parametrize("mode", ["utf16be", "bom", "root-duplicate", "nested-duplicate", "NaN", "Infinity", "-Infinity", "1e999", "malformed"])
def test_endpoint_bad_json_rejects_before_stat_socket_and_peer(endpoint, mode):
  endpoint["raw"] = endpoint_bytes(endpoint["record"], mode)
  try: raise RuntimeError(SECRET)
  except RuntimeError: invalid(lambda: control.request(endpoint["path"], "synthetic-capability", MESSAGE), "监督端点身份已改变")
  assert [event[0] for event in endpoint["events"]] == ["tree", "enter", "read", "exit"]


def test_only_original_tree_read_conflict_bounded_and_not_mutated(endpoint):
  original = Conflict(SECRET); cause = RuntimeError(SECRET); original.__cause__ = cause; endpoint["error"] = original
  try: raise RuntimeError(SECRET)
  except RuntimeError as ambient:
    invalid(lambda: control.request(endpoint["path"], "synthetic-capability", MESSAGE), "监督端点身份已改变")
    assert original.__cause__ is cause and original.__context__ is ambient and original.args == (SECRET,)
  assert endpoint["events"][2] == ("read", "endpoint.json", {"max_bytes": control.MAX_FRAME})
  assert all(event[0] not in ("stat", "socket", "peer", "connect") for event in endpoint["events"])


@pytest.mark.parametrize("raw,mode", [(None, 0o600), (b'{}', 0o644)])
def test_missing_unsafe_endpoint_keeps_message_and_clears_context(endpoint, raw, mode):
  endpoint.update(raw=raw, mode=mode)
  try: raise RuntimeError(SECRET)
  except RuntimeError: invalid(lambda: control.request(endpoint["path"], "cap", MESSAGE), "监督端点记录缺失或不安全")


def test_valid_endpoint_reply_finite_and_cwd_peer_capability_order(endpoint):
  endpoint["raw"] = json.dumps(endpoint["record"], indent=1).encode()  # endpoint 没有 LF 要求。
  assert control.request(endpoint["path"], "synthetic-capability", MESSAGE) == {"ok": True, "result": {"finite": 1.25}}
  events = endpoint["events"]
  assert events[2] == ("read", "endpoint.json", {"max_bytes": control.MAX_FRAME})
  names = [value[0] for value in events]
  assert names == ["tree", "enter", "read", "stat", "open", "chdir", "socket", "timeout", "connect", "chdir", "peer", "makefile", "write", "flush", "readline", "chdir", "close-fd", "exit"]
  assert events[3] == ("stat", "control.sock", {"dir_fd": 202, "follow_symlinks": False})
  assert events[5] == ("chdir", 202) and events[9] == ("chdir", 101) and events[15] == ("chdir", 101)
  assert ("timeout", 30) in events
  assert json.loads(endpoint["connection"].stream.output.getvalue()) == {"capability": "synthetic-capability", "message": MESSAGE}
  assert endpoint["connection"].stream.output.getvalue() == json_bytes({"capability": "synthetic-capability", "message": MESSAGE})


def test_control_request_keeps_original_unicode_wire_bytes(endpoint):
  message = {**MESSAGE, "args": {"literal": "中文\\n", "number": 1.25, "nested": {"z": False, "a": None}}}
  assert control.request(endpoint["path"], "synthetic-capability", message)["ok"] is True
  body = endpoint["connection"].stream.output.getvalue()
  assert body == json_bytes({"capability": "synthetic-capability", "message": message})
  assert b"\\u4e2d" not in body and body.endswith(b"\n")


def test_bad_reply_format_is_rejected_after_normal_connect(endpoint):
  endpoint["reply"] = bad_frame("utf16be")
  invalid(lambda: control.request(endpoint["path"], "cap", MESSAGE), "监督消息格式无效")
  assert ("connect", "control.sock") in endpoint["events"] and endpoint["events"][-3:] == [("chdir", 101), ("close-fd", 101), ("exit",)]


def test_original_postparse_os_error_maps_but_socket_or_tree_entry_error_not_expanded(endpoint, monkeypatch):
  original = OSError(SECRET); endpoint["stat_error"] = original
  invalid(lambda: control.request(endpoint["path"], "cap", MESSAGE), "监督端点身份已改变")
  endpoint["stat_error"] = None
  class FailedTree:
    def __init__(self, path): raise original
  monkeypatch.setattr(control, "Tree", FailedTree)
  with pytest.raises(OSError) as caught: control.request(endpoint["path"], "cap", MESSAGE)
  assert caught.value is original


@pytest.mark.parametrize("mode", ["utf16be", "bom", "root-duplicate", "nested-duplicate", "NaN", "Infinity", "-Infinity", "1e999"])
def test_actual_server_connection_bad_frame_has_zero_service_dispatch(monkeypatch, mode):
  calls = []; events = []; stream = Stream(json_bytes({"capability": "synthetic-capability", "message": MESSAGE}), events)
  # 根／嵌套格式反例放到真实 framing 入口；服务 dispatcher 完全没机会看到它。
  text = json.dumps({"capability": "synthetic-capability", "message": MESSAGE}, separators=(",", ":"))
  if mode == "utf16be": raw = b"\xfe\xff" + (text+"\n").encode("utf-16-be")
  elif mode == "bom": raw = b"\xef\xbb\xbf" + text.encode() + b"\n"
  else:
    if mode == "root-duplicate": text = text.replace('"capability":"synthetic-capability"', '"capability":"bad","cap\\u0061bility":"synthetic-capability"')
    elif mode == "nested-duplicate": text = text.replace('"args":{}', '"args":{"x":0,"\\u0078":1}')
    else: text = text.replace('"args":{}', '"args":{"x":'+mode+'}')
    raw = text.encode() + b"\n"
  stream.input = BytesIO(raw)
  class Connection:
    def settimeout(self, seconds): assert seconds == 30; events.append(("timeout",))
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def makefile(self, mode): assert mode == "rwb"; return stream
    def close(self): events.append(("closed",))
  connection = Connection()
  def reply(token, uid, message): calls.append((token, uid, message)); return {"ok": True}
  monkeypatch.setattr(control, "peer_uid", lambda value: 41); monkeypatch.setattr(supervisor, "os", SimpleNamespace(geteuid=lambda: 41))
  supervisor.SupervisorServer._connection(SimpleNamespace(service=SimpleNamespace(reply=reply)), connection)
  assert calls == [] and stream.output.getvalue() == b""


def test_actual_server_connection_normal_body_after_peer_and_capability(monkeypatch):
  events = []; calls = []; value = {"capability": "synthetic-capability", "message": MESSAGE}; stream = Stream(json_bytes(value), events)
  class Connection:
    def settimeout(self, seconds): events.append(("timeout", seconds))
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def makefile(self, mode): return stream
    def close(self): events.append(("closed",))
  connection = Connection()
  def peer(value): assert value is connection; events.append(("peer",)); return 41
  def reply(token, uid, message):
    assert token == "synthetic-capability" and uid == 41 and message == MESSAGE; events.append(("service",)); calls.append(message); return {"ok": True, "result": {"finite": 1.25}}
  monkeypatch.setattr(control, "peer_uid", peer); monkeypatch.setattr(supervisor, "os", SimpleNamespace(geteuid=lambda: 41))
  supervisor.SupervisorServer._connection(SimpleNamespace(service=SimpleNamespace(reply=reply)), connection)
  assert len(calls) == 1 and json.loads(stream.output.getvalue())["result"]["finite"] == 1.25
  assert [item[0] for item in events][:4] == ["timeout", "peer", "readline", "service"]


def test_endpoint_original_bounded_read_over_limit_has_zero_stat_socket(endpoint):
  endpoint["raw"] = json_bytes(endpoint["record"]) + b" " * control.MAX_FRAME
  endpoint["enforce_bound"] = True
  invalid(lambda: control.request(endpoint["path"], "cap", MESSAGE), "监督端点身份已改变")
  assert endpoint["events"][2] == ("read", "endpoint.json", {"max_bytes": control.MAX_FRAME})
  assert [event[0] for event in endpoint["events"]] == ["tree", "enter", "read", "exit"]


def test_peer_mismatch_preserves_order_and_fixed_conflict(endpoint):
  endpoint["peer"] = 42
  try: raise RuntimeError(SECRET)
  except RuntimeError: invalid(lambda: control.request(endpoint["path"], "cap", MESSAGE), "监督端点用户不匹配")
  assert ("connect", "control.sock") in endpoint["events"] and ("chdir", 101) in endpoint["events"]
  assert not any(event[0] == "write" for event in endpoint["events"])


def test_request_size_fixed_error_after_stat_before_cwd_socket(endpoint):
  try: raise RuntimeError(SECRET)
  except RuntimeError: invalid(lambda: control.request(endpoint["path"], "cap", {"data": "x" * control.MAX_FRAME}), "监督请求超过长度限制")
  assert [event[0] for event in endpoint["events"]] == ["tree", "enter", "read", "stat", "exit"]


def test_socket_connect_error_stays_original_without_expanded_mapping(endpoint):
  original = OSError(SECRET)
  def connect(name): raise original
  endpoint["connection"].connect = connect
  with pytest.raises(OSError) as caught: control.request(endpoint["path"], "cap", MESSAGE)
  assert caught.value is original
  assert endpoint["events"][-3:] == [("chdir", 101), ("close-fd", 101), ("exit",)]


def test_endpoint_read_non_conflict_error_not_newly_mapped(endpoint):
  original = OSError(SECRET); endpoint["error"] = original
  with pytest.raises(OSError) as caught: control.request(endpoint["path"], "cap", MESSAGE)
  assert caught.value is original
