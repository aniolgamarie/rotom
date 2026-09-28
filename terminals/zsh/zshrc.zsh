# termcfg 公开 zsh 配置。插件缺失时仅跳过，不在 shell 启动时联网。
export LANG="${LANG:-en_US.UTF-8}"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) PATH="$HOME/.local/bin:$PATH" ;;
esac
export PATH

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

# 用户可自行安装 Zinit；插件加载需先经过显式锁定与准备。
_termcfg_zinit="${XDG_DATA_HOME:-$HOME/.local/share}/termcfg/packages/plugins/zsh/current/zinit/zinit.zsh"
if [[ -f "$_termcfg_zinit" ]]; then
  source "$_termcfg_zinit"
fi
unset _termcfg_zinit

export NVM_DIR="$HOME/.nvm"
[[ -s "$NVM_DIR/nvm.sh" ]] && source "$NVM_DIR/nvm.sh"
