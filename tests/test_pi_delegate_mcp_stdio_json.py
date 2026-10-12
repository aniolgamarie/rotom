"""原 stdio main + BytesIO/fakeTree/fakecontrol；不启动宿主/socket/子进程。"""
import base64
from io import BytesIO
import json
from pathlib import Path
import runpy
import traceback
from types import SimpleNamespace

import pytest

from agentcfg.activity import digest
from agentcfg.pi_delegate_mcp import DelegateMcp
from test_model_delegate_contract import request

ROOT = Path(__file__).resolve().parents[1]
SECRET = "SYNTHETIC_MCP_JSON_SECRET"
ERROR = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "DELEGATE_PROTOCOL_REJECTED"}}
INITIAL = {"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "synthetic", "version": "1"}}}


def line(value): return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


@pytest.fixture
def entry(tmp_path, monkeypatch):
  main = runpy.run_path(str(ROOT / "scripts/pi-delegate-mcp.py"))["main"]
  req = request("codex"); req["cwd"] = str(tmp_path); monkeypatch.chdir(tmp_path)
  body = {"schema_version": 2, "request": req, "grant": {"allowed_tools": ["tk_read", "tk_find", "tk_grep", "tk_ls"]}}
  body["definition_digest"] = digest(body)
  startup = {"schema_version": 2, "input": body}
  state = {"raw": line(startup), "control": [], "handles": [], "tree_reads": []}; output = BytesIO()
  class Tree:
    def __init__(self, path): assert path == tmp_path
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, name, *, max_bytes):
      assert name == "input.json" and max_bytes == 1024 * 1024
      state["tree_reads"].append(max_bytes); return (state["raw"], 0o600, None)
  class Server(DelegateMcp):
    def handle(self, message): state["handles"].append(message); return super().handle(message)
  def control(endpoint, capability, message):
    assert endpoint == str(tmp_path / "endpoint") and capability == "synthetic-private-capability"
    state["control"].append(message["method"])
    if message["method"] == "handshake": result = {"role": "worker", "lease_id": req["lease_id"], "runtime_identity": req["runtime_identity"]}
    elif message["method"] == "authorize": result = {"valid": True, "grant_generation": req["grant_generation"]}
    elif message["method"] == "delegate_file_action": result = {"data_b64": base64.b64encode(b"synthetic").decode(), "offset": 0, "total_bytes": 9, "content_digest": "a" * 64}
    else: pytest.fail("unexpected own control method")
    return {"ok": True, "result": result}
  monkeypatch.setitem(main.__globals__, "Tree", Tree); monkeypatch.setitem(main.__globals__, "DelegateMcp", Server); monkeypatch.setitem(main.__globals__, "control_request", control)
  monkeypatch.setattr(main.__globals__["sys"], "argv", ["broker", "--input", str(tmp_path / "input.json")])
  monkeypatch.setattr(main.__globals__["sys"], "stdout", SimpleNamespace(buffer=output))
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_ENDPOINT", str(tmp_path / "endpoint")); monkeypatch.setenv("AGENTCFG_DELEGATE_MCP_CAPABILITY", "synthetic-private-capability")
  def run(raw=b""):
    # pytest 在 setup/call 之间切换 stdout；在实际 main 调用前绑定 BytesIO。
    monkeypatch.setattr(main.__globals__["sys"], "stdout", SimpleNamespace(buffer=output))
    monkeypatch.setattr(main.__globals__["sys"], "stdin", SimpleNamespace(buffer=BytesIO(raw)))
    return main()
  return SimpleNamespace(main=main, run=run, state=state, startup=startup, output=output)


def invalid_startup(value, mode):
  text = json.dumps(value, separators=(",", ":"))
  if mode == "utf16be": return b"\xfe\xff" + (text + "\n").encode("utf-16-be")
  if mode == "bom": return b"\xef\xbb\xbf" + text.encode() + b"\n"
  if mode == "duplicate-input": return ('{"schema_version":2,"input":null,"\\u0069nput":' + json.dumps(value["input"]) + '}').encode()
  if mode == "duplicate-unused": return (text[:-1] + ',"unused":0,"\\u0075nused":1}').encode()
  return (text[:-1] + ',"unused":' + mode + '}').encode()


@pytest.mark.parametrize("mode", ["utf16be", "bom", "duplicate-input", "duplicate-unused", "NaN", "Infinity", "-Infinity", "1e999"])
def test_bad_startup_rejected_before_handshake(entry, mode):
  entry.state["raw"] = invalid_startup(entry.startup, mode)
  with pytest.raises(ValueError): entry.run()
  assert entry.state["control"] == [] and entry.state["handles"] == []
  assert entry.output.getvalue() == b""


@pytest.mark.parametrize("mode", ["utf16be", "bom", "duplicate-id", "duplicate-method", "duplicate-nested", "NaN", "Infinity", "-Infinity", "1e999"])
def test_bad_initial_stdio_frame_never_enters_real_core(entry, mode):
  text = json.dumps(INITIAL, separators=(",", ":"))
  if mode == "utf16be": frame = b"\xfe\xff" + (text + "\n").encode("utf-16-be")
  elif mode == "bom": frame = b"\xef\xbb\xbf" + text.encode() + b"\n"
  elif mode == "duplicate-id": frame = text.replace('"id":9', '"id":8,"\\u0069d":9').encode() + b"\n"
  elif mode == "duplicate-method": frame = text.replace('"method":"initialize"', '"method":"tools/list","method":"initialize"').encode() + b"\n"
  elif mode == "duplicate-nested": frame = text.replace('"capabilities":{}', '"capabilities":{"x":0,"\\u0078":1}').encode() + b"\n"
  else: frame = text.replace('"capabilities":{}', '"capabilities":{"value":' + mode + '}').encode() + b"\n"
  assert frame.endswith(b"\n") and frame.count(b"\n") == 1
  assert entry.run(frame) == 0
  assert {"handles": len(entry.state["handles"]), "control": entry.state["control"]} == {"handles": 0, "control": ["handshake"]}
  assert json.loads(entry.output.getvalue()) == ERROR


def test_escaped_duplicate_tool_path_cannot_authorize_or_act_after_normal_initialization(entry):
  bad = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"read","arguments":{"path":"wrong","\\u0070ath":"code.txt"}}}\n'
  raw = line(INITIAL) + line({"jsonrpc": "2.0", "method": "notifications/initialized"}) + bad
  assert entry.run(raw) == 0
  assert {"handles": len(entry.state["handles"]), "control": entry.state["control"]} == {"handles": 2, "control": ["handshake", "authorize"]}
  assert [json.loads(value) for value in entry.output.getvalue().splitlines()][-1] == ERROR


@pytest.mark.parametrize("bad", [b'{"SECRET":', b'{"own":1,"own":2}', b'{"own":1e999}', bytearray(b'{}'), "{}"])
def test_invalid_startup_error_has_no_ambient_context_or_json_doc(entry, bad):
  entry.state["raw"] = bad
  try: raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(ValueError) as caught: entry.run()
  error = caught.value
  assert type(error) is ValueError and error.args == ("DELEGATE_PROTOCOL_REJECTED",)
  assert error.__context__ is None and error.__cause__ is None and not hasattr(error, "doc")
  assert SECRET not in "".join(traceback.format_exception(error))
  assert entry.state["control"] == []


def test_valid_utf8_finite_float_and_real_initialize_tools_flow(entry):
  entry.startup["unused"] = 1.25; entry.state["raw"] = line(entry.startup)
  initial = {**INITIAL, "params": {**INITIAL["params"], "capabilities": {"value": 1.25}}}
  raw = line(initial) + line({"jsonrpc": "2.0", "method": "notifications/initialized"}) + line({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
  assert entry.run(raw) == 0
  assert entry.state["handles"][0]["params"]["capabilities"]["value"] == 1.25
  replies = [json.loads(value) for value in entry.output.getvalue().splitlines()]
  assert [value["id"] for value in replies] == [9, 10] and all("result" in value for value in replies)
  assert b"synthetic-private-capability" not in entry.output.getvalue()


def test_finite_float_tool_limit_still_fails_business_schema_before_action(entry):
  call = {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "read", "arguments": {"path": "code.txt", "limit": 1.25}}}
  assert entry.run(line(INITIAL) + line({"jsonrpc": "2.0", "method": "notifications/initialized"}) + line(call)) == 0
  assert len(entry.state["handles"]) == 3 and entry.state["control"] == ["handshake", "authorize"]
  assert json.loads(entry.output.getvalue().splitlines()[-1])["result"]["isError"] is True


@pytest.mark.parametrize("frame", [b'{}', b'x' * (1024 * 1024 + 1) + b'\n'])
def test_existing_stdio_size_and_lf_boundary_unchanged(entry, frame):
  assert entry.run(frame) == 2
  assert entry.state["handles"] == [] and entry.state["control"] == ["handshake"]


def test_startup_over_limit_rejects_before_any_handshake(entry):
  entry.state["raw"] = b" " * (1024 * 1024 + 1)
  with pytest.raises(ValueError): entry.run()
  assert entry.state["control"] == []


def test_exact_bytes_rejection_does_not_invoke_subclass_hooks(entry):
  calls = []
  class Payload(bytes):
    def decode(self, *args, **kwargs): calls.append("decode"); raise RuntimeError(SECRET)
    def __len__(self): calls.append("len"); return super().__len__()
  entry.state["raw"] = Payload(line(entry.startup))
  with pytest.raises(ValueError): entry.run()
  assert calls == [] and entry.state["control"] == []


def test_valid_startup_utf8_object_does_not_require_stdio_lf(entry):
  entry.state["raw"] = line(entry.startup)[:-1]
  assert entry.run() == 0 and entry.state["control"] == ["handshake"]
