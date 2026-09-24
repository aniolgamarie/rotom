"""Cursor/Bun 的配置身份与登录目录；不启动 Bun、Cursor 或 Pi。"""
from pathlib import Path
import pytest
from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from test_pi_adapter import ROOT, pi_data
from test_pi_optional_capabilities import select


def configured(tmp_path):
  data = pi_data(tmp_path); select(data, "pi-cursor")
  data["profile"]["agent_options"]["runtime"]["engine"] = "bun"
  return data


def test_cursor_native_instance_paths_never_inherit_system_credentials_or_proxy(tmp_path):
  data = configured(tmp_path); adapter = PiAdapter(ROOT)
  spec = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=tmp_path / "instance", lock_identity="fixture")
  env = {row.name: row.value for row in spec.environment}
  assert spec.argv[0] == "bun" and "--no-env-file" in spec.argv and "--no-install" in spec.argv
  assert env["PI_CURSOR_SYSTEM_CREDENTIALS"] == "deny" and env["CURSOR_ACCESS_TOKEN"] == ""
  assert env["CURSOR_CONFIG_DIR"] == str(tmp_path / "instance/cursor-home")
  assert env["PI_CURSOR_CACHE_DIR"] == str(tmp_path / "instance/pi-home/cursor-cache")
  assert env["HTTPS_PROXY"] == env["http_proxy"] == "" and env["PI_CURSOR_STREAM_IDLE_MAX_RETRIES"] == "0"
  assert env["PI_CURSOR_PROVIDER_DEBUG"] == "0"


def test_cursor_never_uses_node_proof_or_falls_back_from_proxy_to_direct(tmp_path):
  data = configured(tmp_path); adapter = PiAdapter(ROOT)
  data["profile"]["agent_options"]["network"]["routes"]["cursor-direct"] = {"mode": "proxy", "provider_ids": ["cursor"], "proxy_url": "http://127.0.0.1:8123"}
  with pytest.raises(ConfigError, match="cursor-direct-binding"): adapter.validate(data)
  data = configured(tmp_path); data["profile"]["agent_options"]["cursor"]["endpoint"] = "https://unselected.invalid"
  with pytest.raises(ConfigError, match="cursor-direct-binding"): adapter.validate(data)
  data = configured(tmp_path); data["profile"]["agent_options"]["runtime"]["engine"] = "node"
  with pytest.raises(ConfigError, match="plugin-combination"): adapter.validate(data)
