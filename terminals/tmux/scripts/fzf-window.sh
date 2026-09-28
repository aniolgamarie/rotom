#!/usr/bin/env bash
# shell_config/scripts/fzf-window.sh — fzf 窗口选择器
# 由 tmux.conf 通过 display-popup 调用

set -euo pipefail

# 检查窗口数量，只有 1 个时跳过
window_count=$(tmux list-windows -a 2>/dev/null | wc -l)
if [ "$window_count" -le 1 ]; then
  echo "Only 1 window, nothing to switch."
  sleep 1
  exit 0
fi

# 列出所有窗口：会话:编号\t窗口名\t路径
windows=$(tmux list-windows -a -F '#{session_name}:#{window_index}	#{window_name}	#{pane_current_path}')

# fzf 选择
selected=$(printf '%s\n' "$windows" | fzf \
  --delimiter=$'\t' \
  --with-nth=2,3 \
  --prompt='Window> ' \
  --header='模糊搜索: 窗口名 / 路径 / 会话:编号' \
  --reverse \
  --preview="tmux capture-pane -t {1} -p 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | tail -20" \
  --preview-window=up:40% || true)

# 跳转
if [ -n "$selected" ]; then
  target=$(printf '%s\n' "$selected" | cut -f1)
  tmux switch-client -t "$target"
fi
