"""主模型route/账号/SDK原生配置的端到端默认投影；网络和模型均未执行。"""
import json
import pytest


from agentcfg.pi import PiAdapter, key_variable
from agentcfg.process import launch_environment
from agentcfg.schema import ConfigError
from agentcfg.secrets import SecretStore
from test_pi_model_config import fixture, ROOT


def test_two_selected_provider_routes_use_separate_keys_and_exact_model_targets(tmp_path, monkeypatch):
  data = fixture(tmp_path)
  data["providers"]["second"] = {"protocol": "openai-responses", "auth_kind": "api-key",
    "base_url": "https://second.invalid/v1", "credential_ref": "secret:second-key"}
  data["models"]["second-model"] = {"provider": "second", "remote_id": "second-target", "input": ["text"]}
  data["profile"]["providers"].append("second"); data["profile"]["models"].append("second-model")
  adapter = PiAdapter(ROOT); adapter.validate(data)
  artifacts = adapter.render(data)
  manifest = json.loads(next(item.content for item in artifacts if item.target.path == "pi-home/agentcfg-manifest.json"))
  providers = manifest["model_configuration"]["providers"]
  assert providers["agentcfg-fictional"]["config"]["api"] == "openai-completions"
  assert providers["agentcfg-second"]["config"]["api"] == "openai-responses"
  assert providers["agentcfg-second"]["config"]["baseUrl"] == "https://second.invalid/v1"
  assert providers["agentcfg-second"]["config"]["models"] == [{"id": "second-target", "input": ["text"]}]
  assert manifest["model_bindings"]["main"] == {"provider": "agentcfg-fictional", "model": "fictional-chat"}
  assert all(name not in manifest["plugins"] for name in ("openai-proxy", "model-delegate", "pi-subagents"))
  monkeypatch.setenv("ALL_PROXY", "http://unselected.invalid:1234")
  spec = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime",
    instance_root=tmp_path / "instance", lock_identity="synthetic-lock")
  env = launch_environment(spec, data["machine"], SecretStore({"fixture": "first-private", "second-key": "second-private"}))
  assert env[key_variable("fictional")] == "first-private" and env[key_variable("second")] == "second-private"
  assert "ALL_PROXY" not in env
  env = launch_environment(spec, data["machine"], SecretStore({"second-key": "second-private"}))
  assert key_variable("fictional") not in env and env[key_variable("second")] == "second-private"
  assert "second-private" not in repr(spec) and b"second-private" not in b"".join(row.content for row in artifacts)


def test_changing_main_model_updates_route_binding_without_copying_native_oauth(tmp_path):
  data = fixture(tmp_path)
  data["providers"]["codex"] = {"protocol": "oauth-dynamic", "auth_kind": "oauth"}
  data["models"]["oauth"] = {"provider": "codex", "remote_id": "synthetic-native-model", "input": ["text"]}
  data["profile"]["providers"].append("codex"); data["profile"]["models"].append("oauth")
  data["profile"]["roles"]["main"] = "oauth"
  artifacts = PiAdapter(ROOT).render(data)
  manifest = json.loads(next(item.content for item in artifacts if item.target.path == "pi-home/agentcfg-manifest.json"))
  assert manifest["model_bindings"]["main"] == {"provider": "openai-codex", "model": "synthetic-native-model"}
  assert manifest["model_configuration"]["providers"]["openai-codex"]["credential_ref"] is None
  assert manifest["provider_bindings"]["openai-codex"]["owner"] == "pi-native"
  assert all(row.target.path != "pi-home/auth.json" for row in artifacts)


@pytest.mark.parametrize("mode", ["direct", "proxy"])
def test_native_main_provider_route_does_not_silently_fall_back_to_direct(tmp_path, mode):
  data = fixture(tmp_path)
  route = {"mode": mode, "provider_ids": ["fictional"], "service_ids": []}
  if mode == "proxy": route["proxy_url"] = "http://proxy.invalid:8123"
  data["profile"]["agent_options"]["network"] = {"routes": {"main-route": route}}
  adapter = PiAdapter(ROOT)
  if mode == "direct": adapter.validate(data)
  else:
    with pytest.raises(ConfigError) as error: adapter.validate(data)
    assert error.value.code == "pi-native-provider-route-unavailable"
    assert "proxy.invalid" not in str(error.value)
