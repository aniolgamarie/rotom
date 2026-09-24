"""委托专用 MCP stdio 协议核心；真正文件动作仅通过已认证监督通道。"""

import base64
import hashlib
import json

from .activity import digest
from .pi_supervisor import closed
from .schema import ConfigError


class DelegateMcp:
  def __init__(self, request, grant, control):
    self.request, self.grant, self.control = request, grant, control
    self.initialized = False
    self.ready = False
    self.seen = set()
    self.schemas = self.tool_schemas()

  def tool_schemas(self):
    string = {"type": "string", "minLength": 1}
    path = {"type": "string", "minLength": 1, "description": "Path inside the authorized workspace; protected files and symlinks are rejected."}
    definitions = {
      "commands": ("List explicitly bound commands available to this delegation.", {}, [], "bash"),
      "command": ("Run one bound foreground command from commands. No shell text, argv overrides or environment are accepted.", {"command_ref": string}, ["command_ref"], "bash"),
      "read": ("Read bounded UTF-8 bytes with a content digest and next offset.", {"path": path, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 16384}}, ["path"], "tk_read"),
      "list": ("List an authorized directory.", {"path": path}, ["path"], "tk_ls"),
      "search": ("Find paths or literal text within authorized files; results are bounded.", {"path": path, "query": string, "kind": {"type": "string", "enum": ["find", "grep"]}}, ["path", "query", "kind"], None),
      "write": ("Write one authorized file. Provide an observed digest when replacing known content.", {"path": path, "content": {"type": "string"}, "expected_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}, ["path", "content"], "tk_write"),
      "edit": ("Replace exactly one occurrence of old_text after a fresh authorized read.", {"path": path, "old_text": string, "new_text": {"type": "string"}}, ["path", "old_text", "new_text"], "tk_edit"),
      "rename": ("Rename one file without overwriting; both paths need explicit rename permission.", {"path": path, "destination": path}, ["path", "destination"], "tk_edit"),
    }
    result = {}
    writable = self.request["mode"] == "implement" and self.request["execution_mode"] == "delegate-write"
    for name, (description, properties, required, tool) in definitions.items():
      if name in ("write", "edit", "rename") and not writable: continue
      if tool and tool not in self.grant["allowed_tools"]: continue
      if name == "search" and not {"tk_find", "tk_grep"} & set(self.grant["allowed_tools"]): continue
      result[name] = {"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        "annotations": {"readOnlyHint": name in ("read", "list", "search", "commands") or name == "command" and not writable, "openWorldHint": False}}
    return result

  def authorize(self):
    proof = self.control("authorize", {"lease_id": self.request["lease_id"], "grant_generation": self.request["grant_generation"]})
    if proof.get("valid") is not True or proof.get("grant_generation") != self.request["grant_generation"]:
      raise ConfigError("DELEGATE_GRANT_REVOKED")

  def action(self, request_id, action):
    return self.control("delegate_file_action", {"run_id": self.request["run_id"], "lease_id": self.request["lease_id"],
      "grant_generation": self.request["grant_generation"], "operation_id": "mcp-" + digest([request_id, self.request["request_digest"]]), "action": action})

  def tool(self, request_id, name, arguments):
    from jsonschema import Draft202012Validator
    if name not in self.schemas: raise ConfigError("DELEGATE_TOOL_UNAVAILABLE")
    if not Draft202012Validator(self.schemas[name]["inputSchema"]).is_valid(arguments): raise ConfigError("DELEGATE_TOOL_ARGUMENTS")
    self.authorize()
    if name in ("command", "commands"):
      binding = {"run_id": self.request["run_id"], "lease_id": self.request["lease_id"], "grant_generation": self.request["grant_generation"]}
      if name == "commands": return self.control("delegate_command_list", binding)
      import time
      result = self.control("delegate_command_start", {**binding, "operation_id": "mcp-" + digest([request_id, self.request["request_digest"]]), **arguments})
      identity = result.get("operation_id")
      if not isinstance(identity, str) or not identity: raise ConfigError("DELEGATE_COMMAND_RESPONSE")
      while result.get("state") == "running":
        time.sleep(0.05)
        self.authorize()
        result = self.control("delegate_command_status", {**binding, "operation_id": identity})
        if result.get("operation_id") != identity: raise ConfigError("DELEGATE_COMMAND_RESPONSE")
      if result.get("state") != "completed": raise ConfigError("DELEGATE_COMMAND_UNSETTLED")
      return result
    if name == "read":
      value = self.action(request_id, {"tool_id": "tk_read", "operation": "read", "path": arguments["path"], "offset": arguments.get("offset", 0), "limit": arguments.get("limit", 16384)})
      data = base64.b64decode(value.pop("data_b64"), validate=True)
      # 只允许跨页的不完整尾字符；文件末尾或中间的坏UTF-8必须拒绝。
      import codecs
      decoder = codecs.getincrementaldecoder("utf8")("strict")
      try:
        text = decoder.decode(data, final=value["offset"] + len(data) >= value["total_bytes"])
      except UnicodeError:
        raise ConfigError("DELEGATE_UTF8_REQUIRED") from None
      if data and not text: raise ConfigError("DELEGATE_UTF8_PAGE_TOO_SMALL")
      return {**value, "content": text, "next_offset": value["offset"] + len(text.encode())}
    if name == "list": return self.action(request_id, {"tool_id": "tk_ls", "operation": "list", "path": arguments["path"]})
    if name == "search": return self.action(request_id, {"tool_id": "tk_find" if arguments["kind"] == "find" else "tk_grep", "operation": "search", **arguments})
    if name == "rename": return self.action(request_id, {"tool_id": "tk_edit", "operation": "rename", **arguments})
    if name == "edit":
      chunks, offset, expected = [], 0, None
      while True:
        value = self.action(str(request_id) + "-read-" + str(offset), {"tool_id": "tk_edit", "operation": "read", "path": arguments["path"], "offset": offset, "limit": 65536})
        expected = expected or value["content_digest"]
        if value["content_digest"] != expected: raise ConfigError("DELEGATE_FILE_CHANGED")
        data = base64.b64decode(value["data_b64"], validate=True); chunks.append(data); offset += len(data)
        if offset >= value["total_bytes"]: break
        if not data: raise ConfigError("DELEGATE_FILE_RESPONSE")
      content = b"".join(chunks).decode("utf8")
      if content.count(arguments["old_text"]) != 1: raise ConfigError("DELEGATE_EDIT_AMBIGUOUS")
      content = content.replace(arguments["old_text"], arguments["new_text"], 1)
    else: content, expected = arguments["content"], arguments.get("expected_digest")
    self.authorize()
    return self.action(request_id, {"tool_id": "tk_edit" if name == "edit" else "tk_write", "operation": "write", "path": arguments["path"],
      "data_b64": base64.b64encode(content.encode()).decode(), "expected_digest": expected})

  def handle(self, message):
    identity = message.get("id") if isinstance(message, dict) else None
    try:
      closed(message, ("jsonrpc", "method"), ("id", "params"))
      if message["jsonrpc"] != "2.0" or not isinstance(message["method"], str): raise ConfigError("MCP_INVALID_REQUEST")
      method, params = message["method"], message.get("params", {})
      if "id" not in message:
        if method == "notifications/initialized" and self.initialized: self.ready = True
        elif method != "notifications/cancelled": raise ConfigError("MCP_INVALID_NOTIFICATION")
        return None
      if type(identity) not in (str, int) or isinstance(identity, str) and len(identity) > 200: raise ConfigError("MCP_REQUEST_ID")
      key = digest(identity)
      if key in self.seen or len(self.seen) >= 10000: raise ConfigError("MCP_REQUEST_REPLAY")
      self.seen.add(key)
      if method == "initialize":
        closed(params, ("protocolVersion", "capabilities", "clientInfo"), ("_meta",))
        if self.initialized: raise ConfigError("MCP_ALREADY_INITIALIZED")
        self.authorize(); self.initialized = True
        version = params["protocolVersion"] if params["protocolVersion"] in ("2024-11-05", "2025-03-26", "2025-06-18") else "2025-06-18"
        result = {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": {"name": "agentcfg-delegate-tools", "version": "1.0.0"}}
      elif method == "ping": result = {}
      elif not self.ready: raise ConfigError("MCP_NOT_INITIALIZED")
      elif method == "tools/list":
        closed(params, (), ("_meta",)); result = {"tools": list(self.schemas.values())}
      elif method == "tools/call":
        closed(params, ("name", "arguments"), ("_meta",))
        try:
          value = self.tool(identity, params["name"], params["arguments"])
          result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}], "isError": False}
        except Exception:
          result = {"content": [{"type": "text", "text": "DELEGATE_TOOL_REJECTED"}], "isError": True}
      else: raise ConfigError("MCP_METHOD_UNAVAILABLE")
      return {"jsonrpc": "2.0", "id": identity, "result": result}
    except (ConfigError, ValueError, TypeError, KeyError):
      return {"jsonrpc": "2.0", "id": identity if type(identity) in (str, int) else None, "error": {"code": -32602, "message": "DELEGATE_PROTOCOL_REJECTED"}}
