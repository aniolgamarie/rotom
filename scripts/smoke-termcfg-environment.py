#!/usr/bin/env python3
"""Explicit isolated zsh with synthetic plugin/tmux guards; never starts a tmux server."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile


REPOSITORY = Path(__file__).resolve().parents[1]
KINDS = ("unset", "empty", "absolute", "relative")
SOURCES = ("terminals/zsh/zshenv", "terminals/zsh/zshrc.zsh", "terminals/tmux/tmux.conf")


class CheckFailure(Exception):
  """仅传递固定用例名称和失败类别，不输出子进程正文。"""


def require(condition, reason):
  if not condition:
    raise CheckFailure(reason)


def write(path, content, *, executable=False):
  path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
  path.write_text(content)
  path.chmod(0o700 if executable else 0o600)


def value(kind, absolute, relative):
  return None if kind == "unset" else "" if kind == "empty" else str(absolute) if kind == "absolute" else relative


def candidate(raw, home, suffix, cwd):
  # 缺失 HOME 的攻击哨兵只放入 cwd，绝不在文件系统根创建 fixture。
  path = Path(raw) if raw else Path(home or ".") / suffix
  return path if path.is_absolute() else cwd / path


def snapshot(path):
  result = {}
  for item in path.rglob("*"):
    name = str(item.relative_to(path))
    if item.is_symlink():
      result[name] = ("link", os.readlink(item))
    elif item.is_dir():
      result[name] = ("directory", item.stat().st_mode & 0o777)
    elif item.is_file():
      result[name] = ("file", hashlib.sha256(item.read_bytes()).hexdigest())
  return result


def zsh_case(root, zsh, *, home_kind="absolute", data_kind="unset", cache_kind="unset",
             config_kind="unset", nvm_kind="empty", layout="selected", history_kind="absolute"):
  root.mkdir(mode=0o700)
  home, cwd, zdot = root / "home", root / "workspace", root / "zdot"
  for directory in (home, cwd, zdot, root / "tmp"):
    directory.mkdir(mode=0o700)
  raw_home = value(home_kind, home, "relative-private-home")
  raw_data = value(data_kind, root / "data", "relative-private-data")
  raw_cache = value(cache_kind, root / "cache", "relative-private-cache")
  raw_config = value(config_kind, root / "config", "relative-private-config")
  raw_nvm = value(nvm_kind, root / "nvm", "relative-private-nvm")
  env = {"HOME": str(home), "ZDOTDIR": str(zdot), "PATH": "/usr/bin:/bin",
         "COLORTERM": "truecolor", "TERM": "dumb", "LANG": "C"}
  for name, raw in (("XDG_DATA_HOME", raw_data), ("XDG_CACHE_HOME", raw_cache),
                    ("XDG_CONFIG_HOME", raw_config), ("NVM_DIR", raw_nvm)):
    if raw is not None:
      env[name] = raw
  # 所有其余发现目录也固定为合成绝对路径。
  env["XDG_STATE_HOME"] = str(root / "state")
  env["XDG_RUNTIME_DIR"] = str(root / "runtime")
  for name in ("TMPDIR", "TMP", "TEMP"):
    env[name] = str(root / "tmp")
  plugin = candidate(raw_data, raw_home, ".local/share", cwd) / "termcfg/packages/plugins/zsh/current/zinit/zinit.zsh"
  write(plugin, 'typeset -g PROBE_PLUGIN=$(( ${PROBE_PLUGIN:-0} + 1 ))\n')
  selected_config = candidate(raw_config, raw_home, ".config", cwd)
  legacy_config = candidate(None, raw_home, ".config", cwd)
  for stage in ("zshenv", "zshrc"):
    selected = selected_config / "termcfg" / (stage + ".local")
    legacy = legacy_config / "termcfg" / (stage + ".local")
    content = 'typeset -g PROBE_' + stage.upper() + '=$(( ${PROBE_' + stage.upper() + ':-0} + 1 ))\n'
    if layout != "legacy":
      write(selected, content)
    if layout in {"legacy", "conflict"}:
      write(legacy, content)
    elif layout == "shared" and selected != legacy:
      legacy.parent.mkdir(parents=True, exist_ok=True)
      legacy.symlink_to(selected)
  nvm = candidate(raw_nvm, raw_home, ".nvm", cwd) / "nvm.sh"
  write(nvm, 'typeset -g PROBE_NVM=$(( ${PROBE_NVM:-0} + 1 ))\n')
  write(cwd / "untouched", "synthetic sentinel\n")
  before = snapshot(cwd)
  # 先以安全 HOME 启动，再在 shell 内模拟缺失/空/相对值，防止 passwd 回填。
  script = r'''
case "$1" in
  unset) unset HOME ;;
  empty) HOME="" ;;
  relative) HOME="relative-private-home" ;;
esac
before_home=${HOME-unset}
before_data=${XDG_DATA_HOME-unset}
before_cache=${XDG_CACHE_HOME-unset}
before_config=${XDG_CONFIG_HOME-unset}
before_nvm=${NVM_DIR-unset}
before_path=$PATH
if [[ "$5" == unset ]]; then
  unset HISTFILE
else
  HISTFILE="$4/caller-history"
fi
before_history=${HISTFILE-unset}
source "$2"
source "$3"
source "$2"
source "$3"
[[ ${HOME-unset} == "$before_home" && ${XDG_DATA_HOME-unset} == "$before_data" && ${XDG_CACHE_HOME-unset} == "$before_cache" && ${XDG_CONFIG_HOME-unset} == "$before_config" ]] || exit 21
if [[ "$HOME" != /* ]]; then
  [[ "$PATH" == "$before_path" && "${HISTFILE-unset}" == "$before_history" ]] || exit 22
fi
if [[ "$before_nvm" != unset ]]; then
  [[ ${NVM_DIR-unset} == "$before_nvm" ]] || exit 23
elif [[ "$HOME" != /* ]]; then
  (( ! ${+NVM_DIR} )) || exit 24
fi
completion_ready=false
if (( ${+_comps} && ${+functions[compdef]} )); then
  completion_ready=true
fi
print -r -- "${PROBE_PLUGIN:-0} ${PROBE_ZSHENV:-0} ${PROBE_ZSHRC:-0} ${PROBE_NVM:-0} $completion_ready"
'''
  command = [str(zsh), "-d", "-f", "-c", script, "termcfg-check", home_kind,
             str(REPOSITORY / SOURCES[0]), str(REPOSITORY / SOURCES[1]), str(root), history_kind]
  result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=20)
  require(result.returncode == 0, "zsh_exit_or_caller_mutation")
  valid_home = home_kind == "absolute"
  valid_data = data_kind == "absolute" or data_kind in {"unset", "empty"} and valid_home
  valid_cache = cache_kind == "absolute" or cache_kind in {"unset", "empty"} and valid_home
  valid_config = config_kind == "absolute" or config_kind in {"unset", "empty"} and valid_home
  hooks = valid_config and (layout != "legacy" or valid_home) and layout != "conflict"
  valid_nvm = nvm_kind == "absolute" or nvm_kind == "unset" and valid_home
  expected = f"{2 if valid_data and valid_home and valid_cache else 0} {2 if hooks else 0} {2 if hooks else 0} {2 if valid_nvm else 0}"
  observed = result.stdout.strip().split()
  require(" ".join(observed[:4]) == expected and len(observed) == 5, "zsh_load_counts")
  require(snapshot(cwd) == before, "cwd_sentinel_changed")
  require(str(root) not in result.stderr and "relative-private-" not in result.stderr, "diagnostic_value_leaked")
  if not valid_data or not valid_cache or not valid_config or not valid_home or nvm_kind == "relative":
    require("termcfg: invalid " in result.stderr, "diagnostic_missing")
  if layout == "conflict":
    require("conflicting zshenv private hooks" in result.stderr and "conflicting zshrc private hooks" in result.stderr,
            "hook_conflict_diagnostic_missing")
  if valid_cache:
    cache = candidate(raw_cache, raw_home, ".cache", cwd)
    require((cache / "zsh").is_dir(), "absolute_cache_missing")
  return {"status": "PASS", "home": home_kind, "data": data_kind, "cache": cache_kind,
          "config": config_kind, "nvm": nvm_kind, "hooks": layout, "history": history_kind,
          "completion_initialization": "READY" if observed[4] == "true" else "NOT VERIFIED"}


def plugin_case(root, zsh, *, home_kind="absolute", cache_kind="absolute", fast_kind="unset",
                invalid=None, theme="fresh", concurrent=False):
  """用受控插件入口和下载计数器验证公开配置；不冒充锁定插件原生验收。"""
  root.mkdir(mode=0o700)
  home, cwd, binaries = root / "home", root / "workspace", root / "bin"
  for directory in (home, cwd, binaries, root / "zdot", root / "tmp"):
    directory.mkdir(mode=0o700)
  raw_cache = value(cache_kind, root / "cache", "relative-private-cache")
  raw_fast = value(fast_kind, root / "fast", "relative-private-fast")
  env = {"HOME": str(home), "ZDOTDIR": str(root / "zdot"), "PATH": str(binaries) + ":/usr/bin:/bin",
         "XDG_DATA_HOME": str(root / "data"), "XDG_CONFIG_HOME": str(root / "config"),
         "XDG_STATE_HOME": str(root / "state"), "XDG_RUNTIME_DIR": str(root / "runtime"),
         "TMPDIR": str(root / "tmp"), "NVM_DIR": "", "COLORTERM": "truecolor", "LANG": "C", "TERM": "dumb",
         "PROBE_NETWORK": str(root / "network-attempts")}
  if raw_cache is not None:
    env["XDG_CACHE_HOME"] = raw_cache
  if raw_fast is not None:
    env["FAST_WORK_DIR"] = raw_fast
  if invalid and invalid != "ZDOTDIR":
    env[invalid] = "relative-private-override"
  for name in ("curl", "wget"):
    write(binaries / name, '#!/bin/sh\nprintf attempted >> "$PROBE_NETWORK"\nexit 99\n', executable=True)
  write(binaries / "lua", '#!/bin/sh\nexit 99\n', executable=True)
  if theme == "unsupported-ln":
    write(binaries / "ln", '#!/bin/sh\nexit 99\n', executable=True)
  plugins = root / "data/termcfg/packages/plugins/zsh/current"
  for relative, name in (("zinit/zinit.zsh", "ZINIT"), ("ohmyzsh/oh-my-zsh.sh", "OMZ"),
                         ("z.lua/z.lua.plugin.zsh", "ZLUA"), ("zsh-autosuggestions/zsh-autosuggestions.zsh", "SUGGEST")):
    write(plugins / relative, 'typeset -g PROBE_' + name + '=$(( ${PROBE_' + name + ':-0} + 1 ))\n')
  write(plugins / "fast-syntax-highlighting/F-Sy-H.plugin.zsh",
        '[[ -e "$FAST_WORK_DIR/secondary_theme.zsh" ]] || { curl synthetic; wget synthetic; }\n'
        'typeset -g PROBE_FSH=$(( ${PROBE_FSH:-0} + 1 ))\n')
  seed = b"# synthetic locked free theme\n"
  if theme != "missing-seed":
    write(plugins / "fast-syntax-highlighting/share/free_theme.zsh", seed.decode())
  write(root / "config/termcfg/zshrc.local", 'typeset -g PROBE_HOOK=$(( ${PROBE_HOOK:-0} + 1 ))\n')
  raw_home = value(home_kind, home, "relative-private-home")
  cache = candidate(raw_cache, raw_home, ".cache", cwd)
  fast = Path(raw_fast) if raw_fast else cache / "f-sy-h"
  if not fast.is_absolute():
    fast = cwd / fast
  target = fast / "secondary_theme.zsh"
  if theme in {"custom", "empty"}:
    write(target, "" if theme == "empty" else "# synthetic user theme\n")
  elif theme == "directory":
    target.mkdir(parents=True)
  elif theme in {"readable-link", "directory-link", "dangling-link"}:
    target.parent.mkdir(parents=True)
    other = root / "theme-target"
    if theme == "directory-link":
      other.mkdir()
    elif theme == "readable-link":
      write(other, "# synthetic linked user theme\n")
    target.symlink_to(other)
  before = snapshot(cwd)
  preserved = target.read_bytes() if target.is_file() else None
  preserved_link = os.readlink(target) if target.is_symlink() else None
  script = r"""
case "$1" in
  unset) unset HOME ;;
  empty) HOME="" ;;
  relative) HOME="relative-private-home" ;;
esac
[[ "$2" != ZDOTDIR ]] || ZDOTDIR="relative-private-zdot"
before_values="${HOME-unset}|${XDG_CACHE_HOME-unset}|${ZDOTDIR-unset}|${ZSH_CACHE_DIR-unset}|${ZSH_COMPDUMP-unset}|${_ZL_DATA-unset}"
before_fast=${FAST_WORK_DIR-unset}
source "$3"
source "$3"
[[ "$before_values" == "${HOME-unset}|${XDG_CACHE_HOME-unset}|${ZDOTDIR-unset}|${ZSH_CACHE_DIR-unset}|${ZSH_COMPDUMP-unset}|${_ZL_DATA-unset}" ]] || exit 31
if [[ -n "$before_fast" && "$before_fast" != unset ]]; then
  [[ ${FAST_WORK_DIR-unset} == "$before_fast" ]] || exit 32
fi
completion_ready=false
if (( ${+_comps} && ${+functions[compdef]} )); then completion_ready=true; fi
print -r -- "${PROBE_ZINIT:-0} ${PROBE_OMZ:-0} ${PROBE_ZLUA:-0} ${PROBE_FSH:-0} ${PROBE_SUGGEST:-0} ${PROBE_HOOK:-0} $completion_ready"
"""
  command = [str(zsh), "-d", "-f", "-c", script, "termcfg-plugins", home_kind, invalid or "none", str(REPOSITORY / SOURCES[1])]
  def run():
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=20)
  if concurrent:
    with ThreadPoolExecutor(max_workers=2) as pool:
      results = list(pool.map(lambda _: run(), range(2)))
  else:
    results = [run()]
  valid_cache = cache_kind == "absolute" or cache_kind in {"unset", "empty"} and home_kind == "absolute"
  stateful = home_kind == "absolute" and valid_cache and invalid != "ZDOTDIR"
  zinit = stateful and invalid != "ZSH_CACHE_DIR"
  omz = zinit and invalid != "ZSH_COMPDUMP"
  zlua = stateful and invalid != "_ZL_DATA"
  fsh = (fast_kind == "absolute" or fast_kind in {"unset", "empty"} and valid_cache) and theme in {"fresh", "custom", "empty", "readable-link"}
  expected = " ".join(str(2 if enabled else 0) for enabled in (zinit, omz, zlua, fsh, True, True))
  for result in results:
    require(result.returncode == 0, "plugin_exit_or_caller_mutation")
    observed = result.stdout.strip().split()
    require(" ".join(observed[:6]) == expected and len(observed) == 7, "plugin_load_counts")
    require(str(root) not in result.stderr and "relative-private-" not in result.stderr, "diagnostic_value_leaked")
  require(not (root / "network-attempts").exists(), "plugin_download_attempted")
  require(snapshot(cwd) == before, "plugin_cwd_sentinel_changed")
  if preserved is not None:
    require(target.read_bytes() == preserved, "existing_user_theme_changed")
  elif fsh:
    require(target.read_bytes() == seed and target.stat().st_mode & 0o777 == 0o600, "theme_seed_or_mode_invalid")
  if preserved_link is not None:
    require(target.is_symlink() and os.readlink(target) == preserved_link, "existing_theme_link_changed")
  if theme in {"directory", "directory-link"}:
    require(list(target.iterdir()) == [], "theme_directory_modified")
  if theme == "dangling-link":
    require(target.is_symlink() and not target.exists(), "dangling_theme_replaced")
  require(not list(fast.glob(".termcfg-theme.*")), "theme_temporary_leftover")
  return {"status": "PASS", "home": home_kind, "cache": cache_kind, "fast": fast_kind,
          "invalid_override": invalid, "theme": theme, "concurrent": concurrent,
          "download_attempts": 0, "completion_initialization": "READY" if observed[6] == "true" else "NOT VERIFIED"}


def tmux_case(root, *, home_kind, data_kind):
  root.mkdir(mode=0o700)
  home, cwd, binaries = root / "home", root / "workspace", root / "bin"
  for directory in (home, cwd, binaries):
    directory.mkdir(mode=0o700)
  raw_home = value(home_kind, home, "relative-private-home")
  raw_data = value(data_kind, root / "data", "relative-private-data")
  env = {"PATH": str(binaries) + ":/usr/bin:/bin"}
  if raw_home is not None:
    env["HOME"] = raw_home
  if raw_data is not None:
    env["XDG_DATA_HOME"] = raw_data
  marker = root / "plugin-loaded"
  env["TERMCFG_MARKER"] = str(marker)
  plugin = candidate(raw_data, raw_home, ".local/share", cwd) / "termcfg/packages/plugins/tmux/current/tpm/tpm"
  write(plugin, '#!/bin/sh\nprintf loaded > "$TERMCFG_MARKER"\n', executable=True)
  write(binaries / "tmux", '#!/bin/sh\nexit 0\n', executable=True)
  source = (REPOSITORY / SOURCES[2]).read_text()
  condition = next(line for line in source.splitlines() if line.startswith("if-shell 'case "))[len("if-shell '"):-3]
  command = next(line for line in source.splitlines() if line.strip().startswith("run-shell 'case ")).strip()[len("run-shell '"):-1]
  valid = data_kind == "absolute" or data_kind in {"unset", "empty"} and home_kind == "absolute"
  for code in (condition, command):
    result = subprocess.run(["/bin/sh", "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=10)
    require(result.returncode == (0 if valid else 1), "tmux_guard_exit")
    require(str(root) not in result.stderr and "relative-private-" not in result.stderr, "diagnostic_value_leaked")
  require(marker.exists() == valid, "tmux_plugin_load")
  return {"status": "PASS", "home": home_kind, "data": data_kind}


def run_matrix(root, zsh):
  zsh_results, tmux_results = [], []
  cases = [{"data_kind": data, "cache_kind": cache} for data, cache in itertools.product(KINDS, repeat=2)]
  cases += [{"home_kind": home, "data_kind": xdg, "cache_kind": xdg, "config_kind": xdg, "nvm_kind": nvm}
            for home, xdg, nvm in itertools.product(("relative", "unset", "empty"), KINDS, KINDS)]
  cases += [{"home_kind": home, "config_kind": "absolute", "layout": "legacy"}
            for home in ("relative", "unset", "empty")]
  cases += [{"home_kind": home, "history_kind": "unset"} for home in ("relative", "unset", "empty")]
  cases += [{"config_kind": "absolute", "layout": layout} for layout in ("conflict", "shared", "legacy")]
  for index, case in enumerate(cases):
    zsh_results.append(zsh_case(root / ("zsh-" + str(index)), zsh, **case))
  for index, (home, data) in enumerate(itertools.product(KINDS, repeat=2)):
    tmux_results.append(tmux_case(root / ("tmux-" + str(index)), home_kind=home, data_kind=data))
  plugin_cases = [{"home_kind": home, "cache_kind": "absolute"} for home in KINDS]
  plugin_cases += [{"cache_kind": "relative", "fast_kind": fast} for fast in ("unset", "relative", "absolute")]
  plugin_cases += [{"invalid": name} for name in ("ZDOTDIR", "ZSH_CACHE_DIR", "ZSH_COMPDUMP", "_ZL_DATA")]
  plugin_cases += [{"theme": theme} for theme in ("custom", "empty", "readable-link", "directory", "directory-link", "dangling-link", "missing-seed", "unsupported-ln")]
  plugin_cases += [{"fast_kind": "relative"}, {"concurrent": True}]
  plugin_results = [plugin_case(root / ("plugins-" + str(index)), zsh, **case) for index, case in enumerate(plugin_cases)]
  return {"zsh": zsh_results, "synthetic_tmux_shell_guards": tmux_results,
          "synthetic_zsh_plugin_guards": plugin_results}


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-terminal", action="store_true", help="Explicitly allow real isolated zsh and sh processes")
  parser.add_argument("--zsh", type=Path, default=Path("/bin/zsh"), help="Absolute zsh executable; default /bin/zsh")
  parser.add_argument("--evidence", type=Path, required=True, help="New absolute private evidence directory")
  args = parser.parse_args(argv)
  if not args.allow_terminal:
    parser.error("--allow-terminal is required; default tests do not start terminal programs")
  if not args.zsh.is_absolute() or not args.zsh.is_file() or not os.access(args.zsh, os.X_OK):
    parser.error("zsh executable must be an existing absolute executable")
  if not args.evidence.is_absolute():
    parser.error("evidence must be a new absolute directory")
  previous = os.umask(0o077)
  try:
    try:
      args.evidence.mkdir(mode=0o700, exist_ok=False)
    except OSError:
      parser.error("cannot create a new private evidence directory")
    report = {"status": "FAIL", "scope": "isolated real zsh; synthetic zsh plugins and tmux shell guards",
              "tmux_server": "NOT RUN", "locked_plugins": "NOT RUN", "agent_hosts": "NOT RUN", "accounts": "NOT RUN"}
    try:
      with tempfile.TemporaryDirectory(prefix="fixtures-", dir=args.evidence) as temporary:
        report["results"] = run_matrix(Path(temporary), args.zsh)
      report["source_sha256"] = {name: hashlib.sha256((REPOSITORY / name).read_bytes()).hexdigest()
                                  for name in (*SOURCES, "scripts/smoke-termcfg-environment.py")}
      report["status"] = "PASS"
    except (CheckFailure, OSError, subprocess.SubprocessError, ValueError, StopIteration) as error:
      report["reason"] = str(error) if isinstance(error, CheckFailure) else "terminal_check_failed"
    (args.evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "scope": report["scope"],
                      "counts": {name: len(cases) for name, cases in report.get("results", {}).items()},
                      **({"reason": report["reason"]} if "reason" in report else {})}))
    return 0 if report["status"] == "PASS" else 1
  finally:
    os.umask(previous)


if __name__ == "__main__":
  raise SystemExit(main())
