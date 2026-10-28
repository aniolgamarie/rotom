"""官方可选插件的选择、原生渲染和配置边界；不启动任何宿主。"""

from pathlib import Path
import tomllib

import pytest
import yaml

from agentcfg import native
from agentcfg.dsh import DshAdapter
from agentcfg.dsh_optional import OPTIONAL_PLUGINS, optional_plugin_rows
from agentcfg.storage import Conflict


ROOT = Path(__file__).resolve().parents[1]
TMUX = {"id": "tmux-context", "name": "@deepseek-ai/dsh-tmux-context"}
WORKTREE = [
  {"id": "worktree", "name": "@deepseek-ai/dsh-experimental-worktree"},
  {"id": "tool-worktree", "name": "@deepseek-ai/dsh-experimental-tool-worktree"},
]


def data(selected=()):
  defaults = tomllib.loads((ROOT / "agents/dsh/agent.toml").read_text())["defaults"]
  plugins = tomllib.loads((ROOT / "agents/dsh/plugins.toml").read_text())["plugins"]
  baseline = [key for key in defaults["plugins"] if key not in OPTIONAL_PLUGINS]
  return {"providers": {}, "models": {}, "mcp": {}, "rules": {},
    "plugins": {key: plugins[key] for key in [*baseline, *selected]},
    "profile": {"roles": {}, "rules": [], "agent_options": defaults["agent_options"]},
    "adapter_documents": {"bindings": {}}}


@pytest.mark.parametrize(("selected", "expected"), [
  ((), []),
  (("tmux-context",), [TMUX]),
  (("git-worktrees",), WORKTREE),
  (("git-worktrees", "tmux-context"), [TMUX, *WORKTREE]),
])
def test_selected_plugins_render_exact_official_rows(selected, expected):
  fixture = data(selected)
  assert optional_plugin_rows(fixture) == expected
  rendered = DshAdapter(ROOT).render(fixture)
  patch = native.load(next(artifact.content for artifact in rendered
    if artifact.target.path == "dsh-home/agentcfg.patch.yml"))
  inserted = [row for operation in patch for row in operation.get("insert", [])]
  optional_names = {row["name"] for row in [TMUX, *WORKTREE]}
  actual = [row for row in inserted if row.get("name") in optional_names]
  assert actual == expected
  assert len({row["id"] for row in inserted}) == len(inserted)
  # 配方不覆盖公开 inject，也不替换 sandbox 或文件策略。
  assert all(set(row) == {"id", "name"} for row in actual)


def test_selection_is_the_only_input_and_each_call_has_fresh_rows():
  assert OPTIONAL_PLUGINS == frozenset({"tmux-context", "git-worktrees", "agent-teams"})
  fixture = {"plugins": {"git-worktrees": {}, "tmux-context": {}, "unrelated": {}}}
  first = optional_plugin_rows(fixture)
  first[1]["config"] = {"directory": "changed"}
  first.pop()
  assert optional_plugin_rows(fixture) == [TMUX, *WORKTREE]
  assert fixture == {"plugins": {"git-worktrees": {}, "tmux-context": {}, "unrelated": {}}}
  assert optional_plugin_rows({"plugins": {"tui": {}, "unrelated": {}}}) == []


def test_optional_packages_are_already_locked_and_selected_for_local_default():
  defaults = tomllib.loads((ROOT / "agents/dsh/agent.toml").read_text())["defaults"]
  assert (OPTIONAL_PLUGINS - {"agent-teams"}).issubset(defaults["plugins"])
  assert "agent-teams" not in defaults["plugins"]
  profile = tomllib.loads((ROOT / "profiles/dsh-default.toml").read_text())
  assert profile["plugins"] == defaults["plugins"] + ["agent-teams"]
  packages = yaml.safe_load((ROOT / "locks/dsh/pnpm-lock.yaml").read_text())["packages"]
  for row in [TMUX, *WORKTREE]:
    assert row["name"] + "@0.2.1-rc.3" in packages


def test_native_rows_retain_order_and_reject_duplicate_top_level_ids():
  rows = optional_plugin_rows({"plugins": {"git-worktrees": {}}})
  encoded = native.dump(rows)
  document = native.load_cordis(encoded)
  assert document.rows == ["worktree", "tool-worktree"]
  assert native.load(native.dump_cordis(document)) == WORKTREE
  # helper 只生成一个 bundle；已有配置合并的重复 id 由原生解析层拒绝。
  with pytest.raises(Conflict, match="id 无效或重复"):
    native.load_cordis(native.dump([*rows, *rows]))
