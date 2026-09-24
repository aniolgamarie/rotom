"""纯响应构造，不创建监听器、不连接第三方服务。"""
import pytest
from agentcfg.pi_validation_service_provider import ServiceProvider


def test_native_mcp_fixture_records_real_protocol_methods_without_payloads():
  provider = ServiceProvider(["agentcfg-native-main"])
  value = provider.mcp_response({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
  assert value["result"]["protocolVersion"] == "2025-03-26"
  assert provider.mcp_response({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
  assert len(provider.mcp_response({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]) == 1
  assert provider.snapshot()["mcp_calls"]["tools/list"] == 1
  with pytest.raises(ValueError): provider.mcp_response({"jsonrpc": "2.0", "id": 3, "method": "tools/call"})


def test_native_search_fixture_counts_only_explicit_search_calls():
  provider = ServiceProvider(["agentcfg-native-main"])
  assert provider.snapshot()["web_calls"] == 0
  assert provider.web_response()["results"][0]["url"] == "https://example.invalid/native-fixture"
  assert provider.snapshot()["web_calls"] == 1 and provider.snapshot()["requests"] == 0
