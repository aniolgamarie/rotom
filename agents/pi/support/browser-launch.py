"""固定Playwright CLI入口；仅隔离受管命令，不约束主会话的完整Bash。

argv表来自精确core 1.64.0-alpha-1790635538000公开help.json的受管子集。
open可产生分离daemon；本入口不fork、不下载、不提供进程回收证明。
"""

import os
from pathlib import Path
import re
import stat
import sys

COMMANDS = {
  "open": {"flags": {"device": "string", "headed": "boolean", "mobile": "boolean"}, "max_args": 1},
  "close": {"flags": {}, "max_args": 0},
  "goto": {"flags": {}, "max_args": 1},
  "type": {"flags": {"submit": "boolean"}, "max_args": 1},
  "click": {"flags": {"modifiers": "string"}, "max_args": 2},
  "dblclick": {"flags": {"modifiers": "string"}, "max_args": 2},
  "fill": {"flags": {"submit": "boolean"}, "max_args": 2},
  "drag": {"flags": {}, "max_args": 2},
  "drop": {"flags": {"path": "string", "data": "string"}, "max_args": 1},
  "hover": {"flags": {}, "max_args": 1},
  "select": {"flags": {}, "max_args": 2},
  "upload": {"flags": {}, "max_args": None},
  "check": {"flags": {}, "max_args": 1},
  "uncheck": {"flags": {}, "max_args": 1},
  "snapshot": {"flags": {"filename": "string", "depth": "string", "boxes": "boolean"}, "max_args": 1},
  "find": {"flags": {"regex": "string", "filename": "string"}, "max_args": 1},
  "eval": {"flags": {"filename": "string"}, "max_args": 2},
  "console": {"flags": {"clear": "boolean"}, "max_args": 1},
  "dialog-accept": {"flags": {}, "max_args": 1},
  "dialog-dismiss": {"flags": {}, "max_args": 0},
  "resize": {"flags": {}, "max_args": 2},
  "run-code": {"flags": {"filename": "string"}, "max_args": 1},
  "go-back": {"flags": {}, "max_args": 0},
  "go-forward": {"flags": {}, "max_args": 0},
  "reload": {"flags": {}, "max_args": 0},
  "press": {"flags": {}, "max_args": 1},
  "keydown": {"flags": {}, "max_args": 1},
  "keyup": {"flags": {}, "max_args": 1},
  "mousemove": {"flags": {}, "max_args": 2},
  "mousedown": {"flags": {}, "max_args": 1},
  "mouseup": {"flags": {}, "max_args": 1},
  "mousewheel": {"flags": {}, "max_args": 2},
  "screenshot": {"flags": {"filename": "string", "type": "string", "full-page": "boolean", "hires": "boolean"}, "max_args": 1},
  "pdf": {"flags": {"filename": "string"}, "max_args": 0},
  "tab-list": {"flags": {}, "max_args": 0},
  "tab-new": {"flags": {}, "max_args": 1},
  "tab-close": {"flags": {}, "max_args": 1},
  "tab-select": {"flags": {}, "max_args": 1},
  "state-load": {"flags": {}, "max_args": 1},
  "state-save": {"flags": {}, "max_args": 1},
  "cookie-list": {"flags": {"domain": "string", "path": "string"}, "max_args": 0},
  "cookie-get": {"flags": {}, "max_args": 1},
  "cookie-set": {"flags": {"domain": "string", "path": "string", "expires": "string", "httpOnly": "boolean", "secure": "boolean", "sameSite": "string"}, "max_args": 2},
  "cookie-delete": {"flags": {}, "max_args": 1},
  "cookie-clear": {"flags": {}, "max_args": 0},
  "localstorage-list": {"flags": {}, "max_args": 0},
  "localstorage-get": {"flags": {}, "max_args": 1},
  "localstorage-set": {"flags": {}, "max_args": 2},
  "localstorage-delete": {"flags": {}, "max_args": 1},
  "localstorage-clear": {"flags": {}, "max_args": 0},
  "sessionstorage-list": {"flags": {}, "max_args": 0},
  "sessionstorage-get": {"flags": {}, "max_args": 1},
  "sessionstorage-set": {"flags": {}, "max_args": 2},
  "sessionstorage-delete": {"flags": {}, "max_args": 1},
  "sessionstorage-clear": {"flags": {}, "max_args": 0},
  "set-color-scheme": {"flags": {}, "max_args": 1},
  "set-reduced-motion": {"flags": {}, "max_args": 1},
  "set-forced-colors": {"flags": {}, "max_args": 1},
  "set-contrast": {"flags": {}, "max_args": 1},
  "set-media": {"flags": {}, "max_args": 1},
  "clear-color-scheme": {"flags": {}, "max_args": 0},
  "clear-reduced-motion": {"flags": {}, "max_args": 0},
  "clear-forced-colors": {"flags": {}, "max_args": 0},
  "clear-contrast": {"flags": {}, "max_args": 0},
  "clear-media": {"flags": {}, "max_args": 0},
  "requests": {"flags": {"static": "boolean", "filter": "string", "clear": "boolean"}, "max_args": 0},
  "request": {"flags": {"filename": "string"}, "max_args": 1},
  "request-headers": {"flags": {"filename": "string"}, "max_args": 1},
  "request-body": {"flags": {"filename": "string"}, "max_args": 1},
  "response-headers": {"flags": {"filename": "string"}, "max_args": 1},
  "response-body": {"flags": {"filename": "string"}, "max_args": 1},
  "route": {"flags": {"status": "string", "body": "string", "content-type": "string", "header": "string", "remove-header": "string"}, "max_args": 1},
  "route-list": {"flags": {}, "max_args": 0},
  "unroute": {"flags": {}, "max_args": 1},
  "network-state-set": {"flags": {}, "max_args": 1},
  "recording-start": {"flags": {}, "max_args": 0},
  "recording-stop": {"flags": {}, "max_args": 0},
  "tracing-start": {"flags": {}, "max_args": 0},
  "tracing-stop": {"flags": {}, "max_args": 0},
  "video-start": {"flags": {"size": "string", "fps": "string", "cursor": "boolean"}, "max_args": 1},
  "video-stop": {"flags": {}, "max_args": 0},
  "video-chapter": {"flags": {"description": "string", "duration": "string"}, "max_args": 1},
  "video-show-actions": {"flags": {"duration": "string", "position": "string", "cursor": "string", "point-style": "string", "highlight-style": "string", "title-style": "string"}, "max_args": 0},
  "video-hide-actions": {"flags": {}, "max_args": 0},
  "pause-at": {"flags": {}, "max_args": 1},
  "resume": {"flags": {}, "max_args": 0},
  "step-over": {"flags": {}, "max_args": 0},
  "generate-locator": {"flags": {}, "max_args": 1},
  "highlight": {"flags": {"hide": "boolean", "style": "string"}, "max_args": 1},
  "webmcp-list": {"flags": {}, "max_args": 0},
  "webmcp-call": {"flags": {"params": "string", "frame": "string"}, "max_args": 1},
}



def validate_arguments(arguments):
  if (type(arguments) is not list or len(arguments) > 256
      or any(type(value) is not str or not value or "\0" in value for value in arguments)):
    raise ValueError("invalid managed browser arguments")
  if not arguments:
    return []
  if arguments in (["--help"], ["-h"], ["--version"], ["-v"]):
    return arguments[:]
  # 先定位command；前置global选项只能是无值的固定输出选项。
  position = 0
  while position < len(arguments) and arguments[position] in ("--raw", "--json"):
    position += 1
  if position == len(arguments) or arguments[position] not in COMMANDS:
    raise ValueError("unsupported managed browser command")
  command = COMMANDS[arguments[position]]
  flags = {**command["flags"], "raw": "boolean", "json": "boolean", "help": "boolean"}
  count, index = 0, position + 1
  while index < len(arguments):
    token = arguments[index]
    if token.startswith("-"):
      if not token.startswith("--"):
        raise ValueError("unsupported managed browser flag")
      name, equal, value = token[2:].partition("=")
      if name not in flags:
        raise ValueError("unsupported managed browser flag")
      if flags[name] == "boolean":
        if equal and value not in ("true", "false"):
          raise ValueError("invalid managed browser flag")
      elif equal:
        if not value:
          raise ValueError("invalid managed browser flag")
      else:
        index += 1
        if index == len(arguments) or arguments[index].startswith("-"):
          raise ValueError("invalid managed browser flag")
    else:
      count += 1
    index += 1
  if command["max_args"] is not None and count > command["max_args"]:
    raise ValueError("invalid managed browser argument count")
  return arguments[:]


PRIVATE_DIRS = {"HOME": "home", "XDG_CONFIG_HOME": "config", "XDG_CACHE_HOME": "cache",
  "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state", "PLAYWRIGHT_BROWSERS_PATH": "browsers"}


def browser_environment(root, source):
  session = source.get("AGENTCFG_PI_BROWSER_SESSION")
  if type(session) is not str or not re.fullmatch(r"[a-f0-9]{32}", session):
    raise ValueError("managed browser session required")
  env = {key: value for key, value in source.items() if key in {"PATH", "LANG", "TZ"} or key.startswith("LC_")}
  env.update({name: str(root / relative) for name, relative in PRIVATE_DIRS.items()})
  env.update(PLAYWRIGHT_CLI_SESSION=session, NO_UPDATE_NOTIFIER="1")
  return env


def reject_config(parent, *, required=False):
  flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
  try:
    directory = os.open(".playwright", flags, dir_fd=parent)
  except FileNotFoundError:
    if required:
      raise ValueError("managed workspace marker missing") from None
    return
  try:
    info = os.fstat(directory)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise ValueError("invalid managed workspace marker")
    try:
      os.stat("cli.config.json", dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
      return
    raise ValueError("custom browser config not admitted")
  finally:
    os.close(directory)


def main():
  try:
    runtime = Path(RUNTIME_ROOT)
    root = Path(BROWSER_ROOT)
    if not runtime.is_absolute() or not root.is_absolute() or ".." in runtime.parts or ".." in root.parts:
      raise ValueError()
    arguments = validate_arguments(sys.argv[1:])
    # 仅由受管入口固定选择同版内置Chromium，调用者仍不能覆盖浏览器渠道。
    command = next((value for value in arguments if value not in ("--raw", "--json")), None)
    if command == "open":
      arguments.append("--browser=chromium")
    env = browser_environment(root, os.environ)
  except (NameError, ValueError, TypeError):
    print("受管浏览器参数或主运行session无效；未执行CLI", file=sys.stderr)
    return 2
  descriptors = []
  try:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.open(root, flags)
    descriptors.append(parent)
    for relative in ["cwd", *PRIVATE_DIRS.values()]:
      fd = os.open(relative, flags, dir_fd=parent)
      descriptors.append(fd)
    for fd in descriptors:
      info = os.fstat(fd)
      if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError()
    reject_config(descriptors[1], required=True)
    reject_config(descriptors[2])
    os.fchdir(descriptors[1])
    os.execvpe("node", ["node", str(runtime / "node_modules/@playwright/cli/playwright-cli.js"), *arguments], env)
    return 0
  except (OSError, ValueError):
    print("受管浏览器私有目录、配置边界或Node入口不可用；未执行替代命令", file=sys.stderr)
    return 4
  finally:
    for fd in reversed(descriptors):
      os.close(fd)


if __name__ == "__main__":
  raise SystemExit(main())
