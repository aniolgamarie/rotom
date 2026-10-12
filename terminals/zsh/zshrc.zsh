# termcfg 公开 zsh 配置。插件缺失时仅跳过，不在 shell 启动时联网。

# ---- 清除 bash 兼容 shim（与 zshenv.local 配套；必须在任何真实调用之前）----
# zshenv.local 为 /etc/profile.d 的 bash-only 脚本定义空函数 shim 并置标记；
# 此处按标记还原，让 zinit/兜底层使用真正的 complete/compdef/compinit。
if [[ ${STARTER_COMPLETE_SHIM:-} == 1 ]]; then
  unfunction complete 2>/dev/null
  unset STARTER_COMPLETE_SHIM
fi
if [[ ${STARTER_COMPDEF_SHIM:-} == 1 ]]; then
  unfunction compdef 2>/dev/null
  unset STARTER_COMPDEF_SHIM
fi
if [[ ${STARTER_COMPINIT_SHIM:-} == 1 ]]; then
  unfunction compinit 2>/dev/null
  unset STARTER_COMPINIT_SHIM
fi

export LANG="${LANG:-en_US.UTF-8}"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) PATH="$HOME/.local/bin:$PATH" ;;
esac
export PATH

# 真彩检测：仅在实际支持 24-bit 色时设置 COLORTERM。
# ssh 不转发 COLORTERM，tmux update-environment 会将其清空；此处按终端
# 实际能力补设，避免 tmux 内程序（OMP 等）误判为 256 色。
if [[ -z "$COLORTERM" ]]; then
  if [[ -n "$TMUX" ]] && command -v tmux >/dev/null 2>&1; then
    # tmux 内：仅当 attached client 协商出 RGB 能力时启用
    if tmux display -p '#{client_termfeatures}' 2>/dev/null | grep -qw RGB; then
      export COLORTERM=truecolor
    fi
  elif infocmp -x "$TERM" 2>/dev/null | grep -q setrgbf; then
    # 直连终端：terminfo 声明了真彩转义序列（setrgbf）
    export COLORTERM=truecolor
  fi
fi

autoload -Uz add-zsh-hook
_termcfg_tmux_preexec() {
  if [[ -n ${TMUX:-} && ${TERMCFG_TMUX_NO_RENAME:-0} != 1 ]]; then
    tmux rename-window "$(printf '%s' "$1" | cut -d' ' -f1 | cut -c1-12) ┆ $(basename "$PWD")" 2>/dev/null
  fi
}
_termcfg_tmux_precmd() {
  if [[ -n ${TMUX:-} && ${TERMCFG_TMUX_NO_RENAME:-0} != 1 ]]; then
    tmux rename-window "zsh ┆ $(basename "$PWD")" 2>/dev/null
  fi
}
add-zsh-hook preexec _termcfg_tmux_preexec
add-zsh-hook precmd _termcfg_tmux_precmd

# ---- 锁定插件加载（由 ./termcfg sync --component zsh 准备；缺失时仅跳过）----
# 所有插件来自仓库锁文件固定的 commit，shell 启动不访问网络。
_termcfg_zsh_plugins="${XDG_DATA_HOME:-$HOME/.local/share}/termcfg/packages/plugins/zsh/current"

# 用户可自行安装 Zinit，作为在 zshrc.local 中加载额外私人插件的逃生口。
if [[ -f "$_termcfg_zsh_plugins/zinit/zinit.zsh" ]]; then
  source "$_termcfg_zsh_plugins/zinit/zinit.zsh"
fi

# zsh-completions：补全脚本集合，须在 compinit 之前加入 fpath
if [[ -d "$_termcfg_zsh_plugins/zsh-completions/src" ]]; then
  fpath=("$_termcfg_zsh_plugins/zsh-completions/src" $fpath)
fi

if [[ -f "$_termcfg_zsh_plugins/ohmyzsh/oh-my-zsh.sh" ]]; then
  # ---- Oh-My-Zsh 本地引导 ----
  # 锁定归档为纯文件快照（无 .git），配合以下开关保证完全离线。
  export ZSH="$_termcfg_zsh_plugins/ohmyzsh"
  ZSH_THEME="ys"
  plugins=(git sudo svn colored-man-pages extract)
  DISABLE_AUTO_UPDATE=true
  DISABLE_UPDATE_PROMPT=true
  source "$ZSH/oh-my-zsh.sh"
else
  # ---- 无插件兜底：基础历史/补全/提示符，保证裸机可用 ----
  HISTFILE="$HOME/.zsh_history"
  HISTSIZE=10000
  SAVEHIST=10000
  setopt SHARE_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE HIST_REDUCE_BLANKS
  setopt INTERACTIVE_COMMENTS
  bindkey -e
  # 补全系统：带 dump 缓存，目录缺失时先创建避免写入失败
  _termcfg_zcompdump="${XDG_CACHE_HOME:-$HOME/.cache}/zsh/zcompdump"
  [[ -d "${_termcfg_zcompdump:h}" ]] || mkdir -p "${_termcfg_zcompdump:h}"
  autoload -Uz compinit && compinit -d "$_termcfg_zcompdump"
  unset _termcfg_zcompdump
  # 简洁提示符，不依赖主题/插件
  PROMPT='%F{blue}%n@%m%f %F{yellow}%~%f %# '
fi

# 语法高亮与自动建议：在 compinit（OMZ 引导或兜底）之后加载
if [[ -f "$_termcfg_zsh_plugins/fast-syntax-highlighting/F-Sy-H.plugin.zsh" ]]; then
  source "$_termcfg_zsh_plugins/fast-syntax-highlighting/F-Sy-H.plugin.zsh"
fi
if [[ -f "$_termcfg_zsh_plugins/zsh-autosuggestions/zsh-autosuggestions.zsh" ]]; then
  source "$_termcfg_zsh_plugins/zsh-autosuggestions/zsh-autosuggestions.zsh"
fi

# z.lua 快速目录跳转：需要 lua 解释器，缺失时跳过
if (( $+commands[lua] )) && [[ -f "$_termcfg_zsh_plugins/z.lua/z.lua.plugin.zsh" ]]; then
  source "$_termcfg_zsh_plugins/z.lua/z.lua.plugin.zsh"
fi

unset _termcfg_zsh_plugins

export NVM_DIR="$HOME/.nvm"
[[ -s "$NVM_DIR/nvm.sh" ]] && source "$NVM_DIR/nvm.sh"

# 机器专属配置（代理、API key、本地函数等）放这里，不写入公开文件。
if [[ -f "$HOME/.config/termcfg/zshrc.local" ]]; then
  source "$HOME/.config/termcfg/zshrc.local"
fi
