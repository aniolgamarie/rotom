"""真实 DSH adapter 的离线 CLI 路径；不启动第三方 host。"""

import json
from pathlib import Path

import pytest

from agentcfg import cli, commands, native
from agentcfg.dependencies import read_lock
from agentcfg.workspace import load_workspace
from agentcfg.storage import Conflict


def test_cli_full_offline_roundtrip(tmp_path, capsys, sentinel_factory):
  assert cli.main(["init-local", "--machine", "pipeline"]) == 0
  import os
  local = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/pipeline.toml"
  w = load_workspace(local)
  untouched = sentinel_factory(w.instance)
  for command in ("validate", "plan"):
    assert cli.main(["--local", str(local), command]) == 0
    untouched.assert_unchanged()
  assert cli.main(["--local", str(local), "render"]) == 0
  untouched.assert_unchanged()
  for command in ("apply", "apply", "doctor", "capture", "rollback"):
    assert cli.main(["--local", str(local), command]) == 0
  assert not (w.instance / "dsh-home/AGENTS.md").exists()
  assert "尚未实现" not in capsys.readouterr().err


def test_real_recipe_preserves_full_tui_config_and_has_no_static_oauth_catalog(tmp_path):
  local = tmp_path / "local.toml"
  local.write_text('schema_version=1\n[machine]\nid="test"\n')
  w = load_workspace(local)
  candidate = w.candidate(read_lock(w.repository).identity)
  patch = native.load(next(a.content for a in candidate.artifacts if a.target.path.endswith("patch.yml")))
  tui = next(row for row in patch if row.get("id") == "dsh-tui")
  assert tui["config"]["provider"] == "openai-codex"
  assert "model" not in tui["config"]
  assert tui["config"]["terminalImages"] is False
  assert "workspace" in tui["config"] and "sessionId" in tui["config"]
  assert sum(row.get("id") == "dsh-tui-auth" for row in patch) == 1
  assert not w.resolved.data["models"]


@pytest.mark.parametrize("source", [
  "value: !!js process.exit()", "value: {__jsExpr: 'process.exit()'}",
  "value: !!js [unexpected]", "value: !!python/object:os.system {}",
  "value: !!js process.env.DSH_TUI_PRESET ?? undefined",
])
def test_native_expressions_reject_unknown_tags_and_wrong_locations(source):
  with pytest.raises(Conflict):
    native.load(source)


def test_full_config_replacement_keeps_unknown_data():
  rows = [{"id": "tui", "config": {"known": False, "unknown": {"x": 1}}, "disabled": False}]
  row = native.replace_config(rows, "tui", {"known": True})
  assert row == {"id": "tui", "config": {"known": True, "unknown": {"x": 1}}, "disabled": False}
  assert rows[0]["config"]["known"] is False
