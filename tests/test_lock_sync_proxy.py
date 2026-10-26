"""lock/sync 的命名代理只注入 npm 构建环境；不透传调用者代理变量，不进入会话环境。"""

from types import SimpleNamespace

import pytest

from agentcfg.commands import sync_backend
from agentcfg.pi_dependencies import npm_environment
from agentcfg.process import npm_proxy_config
from agentcfg.schema import ConfigError


PROXY = {"url": "http://fixture-proxy:8080", "no_proxy": "localhost,127.0.0.1"}


def test_npm_proxy_config_maps_named_proxy_profile():
  assert npm_proxy_config(None) == {}
  assert npm_proxy_config({"url": "http://fixture-proxy:8080"}) == {
    "npm_config_proxy": "http://fixture-proxy:8080",
    "npm_config_https_proxy": "http://fixture-proxy:8080"}
  assert npm_proxy_config(PROXY) == {
    "npm_config_proxy": "http://fixture-proxy:8080",
    "npm_config_https_proxy": "http://fixture-proxy:8080",
    "npm_config_noproxy": "localhost,127.0.0.1"}


def test_pi_npm_environment_injects_proxy_only_when_selected(tmp_path, monkeypatch):
  monkeypatch.setenv("HTTP_PROXY", "http://caller-proxy:1")
  monkeypatch.setenv("HTTPS_PROXY", "http://caller-proxy:1")
  plain = npm_environment(tmp_path / "plain")
  assert not any("proxy" in name.lower() for name in plain)
  proxied = npm_environment(tmp_path / "proxied", proxy=PROXY)
  assert proxied["npm_config_proxy"] == "http://fixture-proxy:8080"
  assert proxied["npm_config_https_proxy"] == "http://fixture-proxy:8080"
  assert proxied["npm_config_noproxy"] == "localhost,127.0.0.1"
  assert "HTTP_PROXY" not in proxied and "HTTPS_PROXY" not in proxied


class _LegacyBackend:
  def sync(self, workspace, lock):
    return {"installed": True}


class _CapableBackend:
  def sync(self, workspace, lock, *, progress=None, proxy=None):
    return {"proxy": proxy, "progress": callable(progress)}


def test_sync_backend_threads_proxy_only_to_capable_backends():
  legacy = SimpleNamespace(backend=_LegacyBackend())
  assert sync_backend(legacy, object(), lambda stage: None, proxy=PROXY) == {"installed": True}
  capable = SimpleNamespace(backend=_CapableBackend())
  assert sync_backend(capable, object(), lambda stage: None, proxy=PROXY) == {"proxy": PROXY, "progress": True}
  assert sync_backend(capable, object(), lambda stage: None) == {"proxy": None, "progress": True}


def _pi_workspace_args(tmp_path, proxy):
  local = tmp_path / "machine.toml"
  local.write_text('schema_version=1\n[machine]\nid="fixture"\n'
    '[machine.proxies.fixture]\nurl="http://fixture-proxy:8080"\nno_proxy="localhost"\n')
  return SimpleNamespace(local=local, profile="pi-base", agent="pi", proxy=proxy)


def test_cmd_lock_resolves_named_proxy_for_pi(tmp_path, monkeypatch):
  from agentcfg import commands
  from agentcfg.pi_dependencies import PiBackend
  captured = {}
  monkeypatch.setattr(PiBackend, "resolve_lock_for",
    lambda self, workspace, *, proxy=None: captured.setdefault("proxy", proxy))
  args = _pi_workspace_args(tmp_path, "fixture")
  assert commands.cmd_lock(args) == 0
  assert captured["proxy"] == {"url": "http://fixture-proxy:8080", "no_proxy": "localhost"}


def test_cmd_lock_without_proxy_passes_none(tmp_path, monkeypatch):
  from agentcfg import commands
  from agentcfg.pi_dependencies import PiBackend
  captured = {}
  monkeypatch.setattr(PiBackend, "resolve_lock_for",
    lambda self, workspace, *, proxy=None: captured.setdefault("proxy", proxy))
  args = _pi_workspace_args(tmp_path, None)
  assert commands.cmd_lock(args) == 0
  assert captured["proxy"] is None


def test_cmd_lock_rejects_unknown_proxy_name(tmp_path, monkeypatch):
  from agentcfg import commands
  from agentcfg.pi_dependencies import PiBackend
  monkeypatch.setattr(PiBackend, "resolve_lock_for",
    lambda self, workspace, *, proxy=None: None)
  args = _pi_workspace_args(tmp_path, "missing")
  with pytest.raises(ConfigError, match="environment-proxy-unknown"):
    commands.cmd_lock(args)


def test_cmd_lock_rejects_proxy_for_omp():
  from agentcfg import commands
  args = SimpleNamespace(agent="omp", proxy="fixture")
  with pytest.raises(ConfigError, match="lock-proxy-unsupported"):
    commands.cmd_lock(args)
