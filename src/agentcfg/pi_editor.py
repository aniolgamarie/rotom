"""显式编辑器绑定；文件参数不进入 shell，写入复用命令的工作区准入。"""
from pathlib import Path
import stat

from .paths import configured_path
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict


def prepare_editor(commands, principal, args):
  closed(args, ("operation_id", "cwd", "path", "line"), ("rows", "columns"))
  manifest = commands.host.manifest()
  if principal.role != "manager" or "pi-slopchop" not in manifest.get("plugins", []):
    raise Conflict("EDITOR_CONTEXT_UNAVAILABLE")
  options = manifest["options"]
  name = options.get("slopchop", {}).get("editor_tool_ref")
  binding = options.get("external_tools", {}).get(name)
  if not binding:
    raise ConfigError("pi-editor-binding-required")
  terminal_size = None
  if binding.get("interactive"):
    from .pi_terminal import dimensions
    if "rows" not in args or "columns" not in args: raise ConfigError("pi-editor-terminal-size-required")
    dimensions(args["rows"], args["columns"])
    terminal_size = (args["rows"], args["columns"])
  elif "rows" in args or "columns" in args:
    raise ConfigError("pi-editor-terminal-not-selected")
  if type(args["line"]) is not int or not 1 <= args["line"] <= 1000000000:
    raise ConfigError("pi-editor-line")
  templates = binding.get("args", [])
  if templates.count("{path}") != 1 or "--" not in templates or templates.index("--") > templates.index("{path}"):
    raise ConfigError("pi-editor-argv-template")
  target = configured_path(args["path"])
  project = configured_path(options["paths"]["roots"][binding["project_root"]]["path"]).resolve(strict=True)
  if not target.is_relative_to(project) or ".git" in target.relative_to(project).parts:
    raise Conflict("EDITOR_TARGET_OUTSIDE_PROJECT")
  if target.resolve(strict=True) != target or not stat.S_ISREG(target.lstat().st_mode) or target.lstat().st_nlink != 1:
    raise Conflict("EDITOR_TARGET_INVALID")
  arguments = []
  for value in templates:
    if value == "{path}": value = str(target)
    elif value in ("{line}", "+{line}"): value = value.replace("{line}", str(args["line"]))
    elif "{" in value or "}" in value: raise ConfigError("pi-editor-argv-template")
    arguments.append(value)
  return commands.prepare(principal, {"operation_id": args["operation_id"], "cwd": args["cwd"], "role_id": "main", "tool_name": "editor",
    "input": {"command": "agentcfg:" + name}}, arguments=arguments, terminal_size=terminal_size)
