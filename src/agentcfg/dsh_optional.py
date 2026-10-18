"""DSH 官方可选插件的原生配置行；运行策略沿用宿主公开服务。"""


OPTIONAL_PLUGINS = frozenset({"tmux-context", "git-worktrees"})


def optional_plugin_rows(data):
  """只投影已选插件；使用官方 bundle 的行标识和默认配置。"""
  rows = []
  if "tmux-context" in data["plugins"]:
    rows.append({"id": "tmux-context", "name": "@deepseek-ai/dsh-tmux-context"})
  if "git-worktrees" in data["plugins"]:
    # 消费方公开 inject 依赖 tools 和 worktrees，运行时必须先挂载。
    rows.extend([
      {"id": "worktree", "name": "@deepseek-ai/dsh-experimental-worktree"},
      {"id": "tool-worktree", "name": "@deepseek-ai/dsh-experimental-tool-worktree"},
    ])
  return rows
