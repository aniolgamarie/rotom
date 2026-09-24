"""自定义 Responses 端点须显式冻结，不能向其发送 OAuth 账号。"""
import json
from copy import deepcopy
import pytest

from agentcfg.activity import digest
from agentcfg.model_delegate_backends import codex_command
from agentcfg.pi_codex_admission import admit_codex_endpoint, CodexAdmissionError
from agentcfg.pi_delegate_policy import codex_api_base_url, execution_policy
from agentcfg.schema import ConfigError
from test_model_delegate_contract import request


@pytest.mark.parametrize("value", ["https://service.example.invalid/v1", "http://127.0.0.1:43210/v1", "http://[::1]:43210/v1"])
def test_endpoint_becomes_an_explicit_cli_setting(value):
  assert codex_api_base_url(value) == value
  argv = codex_command("/fixture/codex", request("codex"), "/fixture/output", permissions={":root": "deny", ":minimal": "read"},
    native={"allow_shell": True, "tool_network": "none"}, api_base_url=value)
  assert "model_providers.agentcfg-delegate.base_url=" + json.dumps(value) in argv
  assert "--ignore-user-config" in argv
  assert 'shell_environment_policy.inherit="none"' in argv
  assert 'shell_environment_policy.set.PATH="/usr/bin:/bin"' in argv


@pytest.mark.parametrize("value", ["", None, "http://remote.invalid/v1", "https://user:secret@remote.invalid", "https://remote.invalid?key=secret",
  "https://remote.invalid/#secret", "https://remote.invalid:0/v1", "https://remote.invalid:bad/v1", "https://remote.invalid/\nvalue", "https://remote.invalid\\@other.invalid"])
def test_bad_endpoint_rejects_without_echoing_input(value):
  with pytest.raises(ConfigError) as error: codex_api_base_url(value)
  assert str(error.value) == "配置校验失败: delegate-codex-api-base-url"


@pytest.mark.parametrize("account", ["personal", "unknown", None])
def test_custom_endpoint_cannot_receive_personal_oauth_or_unknown_credentials(account):
  with pytest.raises(CodexAdmissionError, match="CUSTOM_ENDPOINT_REQUIRES_API_KEY"):
    admit_codex_endpoint({"account_class": account}, "https://fixture.invalid/v1")
  admit_codex_endpoint({"account_class": account}, None)
  admit_codex_endpoint({"account_class": "api-key"}, "https://fixture.invalid/v1")


def test_endpoint_change_invalidates_execution_policy():
  manifest = {"permission_policy": {"schema_version": 1, "default": "deny", "rules": []}, "options": {"model_delegate": {"codex": {
    "native_execution": {"allow_shell": True, "tool_network": "none"}}}}}
  original = execution_policy(manifest, "codex")
  manifest["options"]["model_delegate"]["codex"]["api_base_url"] = "http://127.0.0.1:43210/v1"
  selected = execution_policy(manifest, "codex")
  assert selected["api_base_url"] == manifest["options"]["model_delegate"]["codex"]["api_base_url"]
  assert digest(original) != digest(selected)
