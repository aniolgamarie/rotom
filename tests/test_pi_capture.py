"""只捕获主题/主模型叶子；私有认证与任意原生内容不得进入提案。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg import cli
from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
from test_pi_adapter import pi_data
from test_pi_pipeline import fixture_workspace

ROOT = Path(__file__).resolve().parents[1]


def test_capture_reads_only_settings_allowlist_and_rejects_unknown_or_ambiguous_model(tmp_path):
  data = pi_data(tmp_path)
  adapter = PiAdapter(ROOT)
  data["profile"]["agent_options"]["resources"]["themes"] = ["everforest-dark"]
  settings = {"theme": "Everforest Dark", "defaultProvider": "agentcfg-example", "defaultModel": "fake-main", "secret": "not-exported"}
  class Native:
    def read(self, name):
      assert name == "pi-home/settings.json"
      return (json.dumps(settings).encode(), 0o600, None)
  projection = adapter.capture_projection(Native())
  assert set(projection) == {"theme", "defaultProvider", "defaultModel"}
  assert "not-exported" not in json.dumps(projection)
  # 使用当前选定映射，不能凭捕获结果新增公共模型。
  model = data["models"]["main"]
  projection.update(defaultProvider=adapter.route(data, model["provider"]), defaultModel=model["remote_id"])
  assert adapter.capture_configuration(projection, data)["roles"] == {"main": "main"}
  for change in ({"defaultModel": "unknown"}, {"theme": "unknown"}):
    with pytest.raises(ConfigError):
      adapter.capture_configuration({**projection, **change}, data)
  data["models"]["duplicate"] = deepcopy(model)
  with pytest.raises(ConfigError, match="pi-capture-model"):
    adapter.capture_configuration(projection, data)


def test_capture_writes_private_fully_validated_proposal_without_auth_or_machine_changes(tmp_path, monkeypatch, capsys):
  local, w = fixture_workspace(tmp_path, monkeypatch)
  args = ["--local", str(local)]
  assert cli.main([*args, "apply"]) == 0
  auth = w.instance / "pi-home/auth.json"
  auth.write_text("synthetic-private-auth"); auth.chmod(0o600)
  local_before = local.read_bytes()
  original = Tree.read
  def read(tree, name, *args, **kwargs):
    assert not name.endswith("auth.json")
    return original(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", read)
  assert cli.main([*args, "capture"]) == 0
  result = json.loads(capsys.readouterr().out.splitlines()[-1])
  path = Path(result["proposal"])
  assert path.stat().st_mode & 0o777 == 0o600
  proposal = json.loads(path.read_text())
  assert proposal["overrides"]["profiles"]["pi-fixture"]["roles"]["main"] == "main"
  assert "synthetic-private-auth" not in path.read_text()
  assert local.read_bytes() == local_before


def test_capture_rejects_unknown_projection_fields_and_does_not_invent_models(tmp_path):
  adapter, data = PiAdapter(ROOT), pi_data(tmp_path)
  for projection in ({"apiKey": "synthetic-secret"}, {"theme": []}, {"defaultModel": ""}, {"defaultModel": "fictional-chat"}):
    with pytest.raises(ConfigError):
      adapter.capture_configuration(projection, data)
