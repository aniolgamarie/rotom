"""非 DSH 测试适配器复用部署和上一版恢复，不代表新增产品支持。"""

import json

from agentcfg import deployment as dep
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.render import RenderCandidate
from test_adapter import JsonTestAdapter, FixtureConfig
from agentcfg.adapter import SecretRef


def test_json_adapter_instances_and_backups_are_independent(tmp_path):
  adapter = JsonTestAdapter()
  config = FixtureConfig("https://example.invalid/v1", "fictional", SecretRef("secret:test"))
  first = RenderCandidate("one", adapter.render(config))
  a, b = tmp_path / "first", tmp_path / "second"
  sa, sb = tmp_path / "state-first", tmp_path / "state-second"
  dep.apply(a, sa, first, {"id": "a"}, {"lock": "fixture"})
  dep.apply(b, sb, first, {"id": "b"}, {"lock": "fixture"})
  before = (sb / "deployment.json").read_bytes()
  altered = FixtureConfig("https://changed.example.invalid/v1", "fictional", SecretRef("secret:test"))
  dep.apply(a, sa, RenderCandidate("two", adapter.render(altered)), {"id": "a"}, {"lock": "fixture"})
  dep.rollback(a, sa, {"id": "a"})
  assert json.loads((a / "native/config.json").read_bytes())["endpoint"] == config.endpoint
  assert (sb / "deployment.json").read_bytes() == before


def test_explicit_codec_extension_does_not_silently_use_yaml(tmp_path, monkeypatch):
  monkeypatch.setattr(dep, "NATIVE_CODECS", dict(dep.NATIVE_CODECS))
  dep.register_codec("fixture-format", json.loads, dep.json_bytes)
  target = ManagedTarget("config.fixture", Ownership.FIELDS, "fixture-format", "/enabled")
  candidate = RenderCandidate("custom", (Artifact(target, b"false"),))
  dep.apply(tmp_path / "instance", tmp_path / "state", candidate, {"id": "custom"}, {})
  assert json.loads((tmp_path / "instance/config.fixture").read_text()) == {"enabled": False}
