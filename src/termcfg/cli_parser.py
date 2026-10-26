"""终端命令语法与静态帮助；不加载部署、包或事务执行器。"""

import argparse
from pathlib import Path

from .config import COMPONENTS
from .errors import TermcfgError
from .guidance import hint
from .cli_help import COMMANDS, ROOT_HELP, argument_label, describe_options, parameter_guidance


class Parser(argparse.ArgumentParser):
  command_name = None

  def fail(self, detail=None):
    error = TermcfgError(2, "invalid_arguments", hint(self.command_name, "--help"))
    error.usage_detail = parameter_guidance(self, detail) if detail else parameter_guidance(self)
    raise error

  def error(self, message):
    # argparse 的 message 可能包含私人值或未知 token；不反射、不解析它。
    self.fail()

  def _check_value(self, action, value):
    if action.choices is not None and value not in action.choices:
      choices = "、".join(action.choices)
      self.fail(f"{argument_label(action)}：不支持的选择；可选：{choices}")

  def _get_value(self, action, arg_string):
    try:
      return super()._get_value(action, arg_string)
    except argparse.ArgumentError:
      self.fail(f"{argument_label(action)}：值类型无效；请检查该参数说明")

  def parse_args(self, args=None, namespace=None):
    parsed, extras = self.parse_known_args(args, namespace)
    if extras:
      # 已解析的命令来自 choices；不扫描未知 argv 来猜上下文。
      for action in self._actions:
        if isinstance(action, argparse._SubParsersAction):
          selected = action.choices.get(getattr(parsed, "command", None))
          if selected is not None:
            selected.fail("参数无效或位置不正确；请检查本命令参数")
      self.fail()
    return parsed


def build_parser() -> Parser:
  parser = Parser(prog="./termcfg", description="独立管理 zsh/tmux 与可选 Herdr 公开配置",
                  epilog=ROOT_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--machine", default="default")
  parser.add_argument("--json", action="store_true")
  commands = parser.add_subparsers(dest="command", required=True, title="命令", metavar="COMMAND")

  def add_command(name):
    summary, detail = COMMANDS[name]
    child = commands.add_parser(name, help=summary, description=summary, epilog=detail,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    child.command_name = name
    return child

  add_command("components")
  init = add_command("init-local")
  init.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  init.add_argument("--edit", action="store_true")
  init.add_argument("--none", action="store_true")
  plan = add_command("plan")
  plan.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  plan.add_argument("--home")
  plan.add_argument("--entry-repo", type=Path, help="zsh 入口明确绑定的可信 checkout 绝对路径；省略时保持已有绑定")
  doctor_parser = add_command("doctor")
  doctor_parser.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  doctor_parser.add_argument("--strict", action="store_true")
  doctor_parser.add_argument("--home")
  status_parser = add_command("status")
  status_parser.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  status_parser.add_argument("--home")
  apply_parser = add_command("apply")
  apply_parser.add_argument("--component", action="append", choices=sorted(COMPONENTS))
  apply_parser.add_argument("--plan-id")
  apply_parser.add_argument("--adopt-target", action="append", default=[])
  apply_parser.add_argument("--confirm-zshenv")
  apply_parser.add_argument("--entry-repo", type=Path, help="仅 zsh：使用预览中相同的可信 checkout 绝对路径换绑入口")
  add_command("recover")
  lock_parser = add_command("lock")
  lock_parser.add_argument("--component", required=True, choices=["tmux", "zsh"])
  lock_parser.add_argument("--version", required=True)
  lock_parser.add_argument("--plugin")
  lock_parser.add_argument("--repo", help="新增插件的 GitHub 仓库（owner/name，须在允许前缀内）")
  lock_parser.add_argument("--entry", help="新增插件的入口文件相对路径")
  lock_parser.add_argument("--timeout", type=int, default=300)
  sync_parser = add_command("sync")
  sync_parser.add_argument("--component", required=True, choices=["tmux", "zsh"])
  sync_parser.add_argument("--timeout", type=int, default=300)
  migrate_parser = add_command("migrate")
  migrate_parser.add_argument("--drop-mihomo", action="store_true", required=True)
  rollback_parser = add_command("rollback")
  rollback_parser.add_argument("--component", required=True, choices=sorted(COMPONENTS))
  rollback_parser.add_argument("--plan-only", action="store_true")
  rollback_parser.add_argument("--plan-id")
  for command in commands.choices.values():
    command.add_argument("--machine", default=argparse.SUPPRESS)
    command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    describe_options(command)
  describe_options(parser)
  return parser
