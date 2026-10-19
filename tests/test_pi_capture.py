"""仅捕获非秘密主题/主模型叶子；拒绝未知值，不读取认证或会话正文。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg import cli, commands
from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
from agentcfg.workspace import load_workspace
from test_pi_reboot_configuration import local, REPOSITORY
from test_pi_reboot_pipeline import pipeline, prepare
from test_pi_reboot_dependencies import fake_npm, recipe_repository


def test_capture_reads_only_settings_allowlist_and_rejects_unknown_or_ambiguous_model(tmp_path):
  data = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY).resolved.data
  adapter = PiAdapter(REPOSITORY)
  model = data["models"]["example-main"]
  settings = {"theme": "catppuccin-frappe", "defaultProvider": adapter.route(data, model["provider"]),
    "defaultModel": model["remote_id"], "secret": "SYNTHETIC_PRIVATE_SENTINEL"}
  class Native:
    def read(self, name):
      assert name == "pi-home/settings.json"
      return (json.dumps(settings).encode(), 0o600, None)
  projection = adapter.capture_projection(Native())
  assert set(projection) == {"theme", "defaultProvider", "defaultModel"}
  assert "SYNTHETIC_PRIVATE_SENTINEL" not in json.dumps(projection)
  assert adapter.capture_configuration(projection, data) == {
    "agent_options": {"ui": {"theme": "catppuccin-frappe"}}, "roles": {"main": "example-main"}}
  for change in ({"defaultModel": "unknown"}, {"theme": "unknown"}):
    with pytest.raises(ConfigError): adapter.capture_configuration({**projection, **change}, data)
  data["models"]["duplicate"] = deepcopy(model)
  with pytest.raises(ConfigError, match="pi-capture-model"):
    adapter.capture_configuration(projection, data)


def test_capture_writes_private_validated_proposal_without_auth_or_machine_changes(pipeline, monkeypatch, capsys):
  workspace, backend, lock, _, launched = pipeline
  prepare(workspace, backend, lock)
  auth = workspace.instance / "pi-home/auth.json"
  auth.write_text("SYNTHETIC_PRIVATE_SENTINEL")
  auth.chmod(0o600)
  original_local = workspace.local_path.read_bytes()
  original_read = Tree.read
  def read(tree, name, *args, **kwargs):
    assert not name.endswith("auth.json") and "/sessions/" not in name
    return original_read(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", read)
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  # recipe_repository仅包含解析依赖所需来源；提案用完整公开catalog重新验证。
  monkeypatch.setattr(commands, "load_workspace", lambda *args, **kwargs:
    load_workspace(workspace.local_path, workspace.profile, repository=REPOSITORY, proposal=kwargs["proposal"]))
  assert cli.main(["--local", str(workspace.local_path), "capture"]) == 0
  result = json.loads(capsys.readouterr().out)
  path = Path(result["proposal"])
  assert path.stat().st_mode & 0o777 == 0o600
  proposal = json.loads(path.read_text())
  assert proposal["overrides"]["profiles"]["pi-base"]["roles"] == {"main": "example-main"}
  assert "SYNTHETIC_PRIVATE_SENTINEL" not in path.read_text()
  assert workspace.local_path.read_bytes() == original_local and not launched


def test_capture_rejects_unknown_projection_fields_and_does_not_invent_models(tmp_path):
  data = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY).resolved.data
  adapter = PiAdapter(REPOSITORY)
  for projection in ({"apiKey": "SYNTHETIC_PRIVATE_SENTINEL"}, {"theme": []}, {"defaultModel": ""}, {"defaultModel": "fictional-chat"}):
    with pytest.raises(ConfigError): adapter.capture_configuration(projection, data)
