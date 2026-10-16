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
if [[ "$HOME" == /* ]]; then
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) PATH="$HOME/.local/bin:$PATH" ;;
  esac
  export PATH
else
  print -u2 -r -- "termcfg: invalid HOME; local bin default not added"
fi

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
unset _termcfg_zsh_plugins
_termcfg_data_home="${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}"
if [[ "$_termcfg_data_home" == /* ]]; then
  _termcfg_zsh_plugins="$_termcfg_data_home/termcfg/packages/plugins/zsh/current"
elif [[ -n "${XDG_DATA_HOME:-}" ]]; then
  print -u2 -r -- "termcfg: invalid XDG_DATA_HOME; zsh plugins not loaded"
else
  print -u2 -r -- "termcfg: invalid HOME; zsh plugins not loaded"
fi
unset _termcfg_data_home

# 有状态插件会自行派生缓存/历史路径；先校验其公开目录参数，不改写调用者变量。
_termcfg_effective_cache="${XDG_CACHE_HOME:-${HOME:+$HOME/.cache}}"
_termcfg_stateful_ok=1
if [[ "$HOME" != /* ]]; then
  _termcfg_stateful_ok=0
  print -u2 -r -- "termcfg: invalid HOME; stateful zsh plugins not loaded"
fi
if [[ "$_termcfg_effective_cache" != /* ]]; then
  _termcfg_stateful_ok=0
  print -u2 -r -- "termcfg: invalid XDG_CACHE_HOME or HOME; stateful zsh plugins not loaded"
fi
if [[ -n "${ZDOTDIR:-}" && "$ZDOTDIR" != /* ]]; then
  _termcfg_stateful_ok=0
  print -u2 -r -- "termcfg: invalid ZDOTDIR; stateful zsh plugins not loaded"
fi
if [[ -n "${ZSH_CACHE_DIR:-}" && "$ZSH_CACHE_DIR" != /* ]]; then
  print -u2 -r -- "termcfg: invalid ZSH_CACHE_DIR; Zinit and OMZ not loaded"
fi
if [[ -n "${ZSH_COMPDUMP:-}" && "$ZSH_COMPDUMP" != /* ]]; then
  print -u2 -r -- "termcfg: invalid ZSH_COMPDUMP; OMZ not loaded"
fi
if [[ -n "${_ZL_DATA:-}" && "$_ZL_DATA" != /* ]]; then
  print -u2 -r -- "termcfg: invalid _ZL_DATA; z.lua not loaded"
fi

# 用户可自行安装 Zinit，作为在 zshrc.local 中加载额外私人插件的逃生口。
if [[ $_termcfg_stateful_ok == 1 && ( -z "${ZSH_CACHE_DIR:-}" || "$ZSH_CACHE_DIR" == /* ) && -n "${_termcfg_zsh_plugins:-}" && -f "$_termcfg_zsh_plugins/zinit/zinit.zsh" ]]; then
  source "$_termcfg_zsh_plugins/zinit/zinit.zsh"
fi

# zsh-completions：补全脚本集合，须在 compinit 之前加入 fpath
if [[ -n "${_termcfg_zsh_plugins:-}" && -d "$_termcfg_zsh_plugins/zsh-completions/src" ]]; then
  fpath=("$_termcfg_zsh_plugins/zsh-completions/src" $fpath)
fi

if [[ $_termcfg_stateful_ok == 1 && ( -z "${ZSH_CACHE_DIR:-}" || "$ZSH_CACHE_DIR" == /* ) && ( -z "${ZSH_COMPDUMP:-}" || "$ZSH_COMPDUMP" == /* ) && -n "${_termcfg_zsh_plugins:-}" && -f "$_termcfg_zsh_plugins/ohmyzsh/oh-my-zsh.sh" ]]; then
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
  if [[ "$HOME" == /* ]]; then
    HISTFILE="$HOME/.zsh_history"
  else
    print -u2 -r -- "termcfg: invalid HOME; history file default not set"
  fi
  HISTSIZE=10000
  SAVEHIST=10000
  setopt SHARE_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE HIST_REDUCE_BLANKS
  setopt INTERACTIVE_COMMENTS
  bindkey -e
  # 补全系统：带 dump 缓存，目录缺失时先创建避免写入失败
  _termcfg_cache_home="${XDG_CACHE_HOME:-${HOME:+$HOME/.cache}}"
  if [[ "$_termcfg_cache_home" != /* ]]; then
    if [[ -n "${XDG_CACHE_HOME:-}" ]]; then
      print -u2 -r -- "termcfg: invalid XDG_CACHE_HOME; completion cache not used"
    else
      print -u2 -r -- "termcfg: invalid HOME; completion cache not used"
    fi
    autoload -Uz compinit && compinit -d /dev/null -D
  else
    _termcfg_zcompdump="$_termcfg_cache_home/zsh/zcompdump"
    [[ -d "${_termcfg_zcompdump:h}" ]] || mkdir -p "${_termcfg_zcompdump:h}"
    autoload -Uz compinit && compinit -d "$_termcfg_zcompdump"
    unset _termcfg_zcompdump
  fi
  unset _termcfg_cache_home
  # 简洁提示符，不依赖主题/插件
  PROMPT='%F{blue}%n@%m%f %F{yellow}%~%f %# '
fi

# 语法高亮与自动建议：在 compinit（OMZ 引导或兜底）之后加载
if [[ -n "${_termcfg_zsh_plugins:-}" && -f "$_termcfg_zsh_plugins/fast-syntax-highlighting/F-Sy-H.plugin.zsh" ]]; then
  _termcfg_fast_work_dir="${FAST_WORK_DIR:-${_termcfg_effective_cache:+$_termcfg_effective_cache/f-sy-h}}"
  _termcfg_fast_ready=0
  if [[ "$_termcfg_fast_work_dir" == /* ]]; then
    _termcfg_fast_theme="$_termcfg_fast_work_dir/secondary_theme.zsh"
    if [[ -f "$_termcfg_fast_theme" && -r "$_termcfg_fast_theme" ]]; then
      # 包括空主题在内的既有用户文件保持不变；不声称它由 termcfg 预置。
      _termcfg_fast_ready=1
    elif [[ ! -e "$_termcfg_fast_theme" && ! -L "$_termcfg_fast_theme" ]]; then
      # 同目录临时文件写完后无覆盖发布；GNU ln -T 不会向目标目录内创建链接。
      # 不支持 -T 或任何准备步骤失败时跳过 FSH，绝不进入上游下载分支。
      if (
        umask 077
        command mkdir -p "$_termcfg_fast_work_dir" || exit 1
        _termcfg_fast_seed="$_termcfg_zsh_plugins/fast-syntax-highlighting/share/free_theme.zsh"
        [[ -f "$_termcfg_fast_seed" && -r "$_termcfg_fast_seed" ]] || exit 1
        _termcfg_fast_temp=$(command mktemp "$_termcfg_fast_work_dir/.termcfg-theme.XXXXXXXX") || exit 1
        if command cat "$_termcfg_fast_seed" > "$_termcfg_fast_temp"; then
          command ln -T -- "$_termcfg_fast_temp" "$_termcfg_fast_theme"
        fi
        command rm -f "$_termcfg_fast_temp"
        [[ -f "$_termcfg_fast_theme" && -r "$_termcfg_fast_theme" ]]
      ) 2>/dev/null; then
        _termcfg_fast_ready=1
      fi
    fi
    if [[ $_termcfg_fast_ready != 1 ]]; then
      print -u2 -r -- "termcfg: FSH theme preparation failed; FSH not loaded"
    fi
  else
    print -u2 -r -- "termcfg: invalid FAST_WORK_DIR or XDG_CACHE_HOME or HOME; FSH not loaded"
  fi
  if [[ $_termcfg_fast_ready == 1 ]]; then
    FAST_WORK_DIR="$_termcfg_fast_work_dir"
    source "$_termcfg_zsh_plugins/fast-syntax-highlighting/F-Sy-H.plugin.zsh"
  fi
  unset _termcfg_fast_work_dir _termcfg_fast_theme _termcfg_fast_ready
fi
if [[ -n "${_termcfg_zsh_plugins:-}" && -f "$_termcfg_zsh_plugins/zsh-autosuggestions/zsh-autosuggestions.zsh" ]]; then
  source "$_termcfg_zsh_plugins/zsh-autosuggestions/zsh-autosuggestions.zsh"
fi

# z.lua 快速目录跳转：需要 lua 解释器，缺失时跳过
if (( $+commands[lua] )) && [[ $_termcfg_stateful_ok == 1 && ( -z "${_ZL_DATA:-}" || "$_ZL_DATA" == /* ) && -n "${_termcfg_zsh_plugins:-}" && -f "$_termcfg_zsh_plugins/z.lua/z.lua.plugin.zsh" ]]; then
  source "$_termcfg_zsh_plugins/z.lua/z.lua.plugin.zsh"
fi

unset _termcfg_zsh_plugins _termcfg_effective_cache _termcfg_stateful_ok

# 显式空值表示不加载 NVM；仅在变量未设置时提供默认路径。
if (( ! ${+NVM_DIR} )); then
  if [[ "$HOME" == /* ]]; then
    NVM_DIR="$HOME/.nvm"
  else
    print -u2 -r -- "termcfg: invalid HOME; NVM default not loaded"
  fi
fi
if (( ${+NVM_DIR} )); then
  export NVM_DIR
  if [[ -n "$NVM_DIR" && "$NVM_DIR" != /* ]]; then
    print -u2 -r -- "termcfg: invalid NVM_DIR; NVM not loaded"
  elif [[ -n "$NVM_DIR" && -s "$NVM_DIR/nvm.sh" ]]; then
    source "$NVM_DIR/nvm.sh"
  fi
fi

# 机器专属配置（代理、API key、本地函数等）放这里，不写入公开文件。
# XDG 优先、缺失时兼容 legacy；冲突时不执行任一私人 hook，不输出路径或正文。
_termcfg_config_home="${XDG_CONFIG_HOME:-${HOME:+$HOME/.config}}"
if [[ "$_termcfg_config_home" != /* ]]; then
  if [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
    print -u2 -r -- "termcfg: invalid XDG_CONFIG_HOME; zshrc private hook not loaded"
  else
    print -u2 -r -- "termcfg: invalid HOME; zshrc private hook not loaded"
  fi
else
  _termcfg_private_hook="$_termcfg_config_home/termcfg/zshrc.local"
  _termcfg_legacy_hook=""
  if [[ "$HOME" == /* ]]; then
    _termcfg_legacy_hook="$HOME/.config/termcfg/zshrc.local"
  else
    print -u2 -r -- "termcfg: invalid HOME; zshrc legacy private hook not loaded"
  fi
  if [[ -f "$_termcfg_private_hook" && -n "$_termcfg_legacy_hook" && -f "$_termcfg_legacy_hook" && ! "$_termcfg_private_hook" -ef "$_termcfg_legacy_hook" ]]; then
    print -u2 -r -- "termcfg: conflicting zshrc private hooks; neither loaded"
  elif [[ -f "$_termcfg_private_hook" ]]; then
    source "$_termcfg_private_hook"
  elif [[ -n "$_termcfg_legacy_hook" && -f "$_termcfg_legacy_hook" ]]; then
    source "$_termcfg_legacy_hook"
  fi
  unset _termcfg_private_hook _termcfg_legacy_hook
fi
unset _termcfg_config_home
