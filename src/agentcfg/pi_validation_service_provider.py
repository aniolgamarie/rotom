"""原生可选服务的合成 MCP/搜索端点；只在验收网络命名空间中监听。"""
from .pi_validation_provider import ScriptedProvider


class ServiceProvider(ScriptedProvider):
  def __init__(self, models):
    super().__init__(models)
    self.mcp_calls = {}
    self.web_calls = 0

  def mcp_response(self, payload):
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0": raise ValueError("native-mcp-message")
    method = payload.get("method")
    names = {"initialize", "notifications/initialized", "notifications/cancelled", "tools/list", "resources/list", "resources/templates/list", "prompts/list", "ping"}
    if method not in names: raise ValueError("native-mcp-method")
    with self.mutex: self.mcp_calls[method] = self.mcp_calls.get(method, 0) + 1
    if method.startswith("notifications/"): return None
    if method == "initialize":
      result = {"protocolVersion": payload.get("params", {}).get("protocolVersion", "2025-03-26"),
        "serverInfo": {"name": "agentcfg-native-mcp", "version": "1.0.0"}, "capabilities": {"tools": {}, "resources": {}, "prompts": {}}}
    elif method == "tools/list": result = {"tools": [{"name": "fixture_echo", "description": "Synthetic native metadata", "inputSchema": {"type": "object", "properties": {}}}]}
    elif method == "resources/list": result = {"resources": []}
    elif method == "resources/templates/list": result = {"resourceTemplates": []}
    elif method == "prompts/list": result = {"prompts": []}
    else: result = {}
    return {"jsonrpc": "2.0", "id": payload["id"], "result": result}

  def web_response(self):
    with self.mutex: self.web_calls += 1
    return {"query": "OpenAI API documentation", "results": [{"title": "Native fixture documentation", "url": "https://example.invalid/native-fixture",
      "content": "Synthetic search result from the local native acceptance service.", "engine": "native-fixture"}], "unresponsive_engines": []}

  def snapshot(self):
    return {**super().snapshot(), "mcp_calls": dict(self.mcp_calls), "web_calls": self.web_calls}
