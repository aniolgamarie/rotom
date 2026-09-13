"""agentcfg 命令行解析与调度

实现 ./agentcfg [--machine NAME | --local PATH] [--profile ID] COMMAND 契约。
公共选择参数位于子命令前；machine/local 互斥。
"""

import argparse
import os
import sys
import tomllib
from pathlib import Path

from .paths import InitializationError, PathError, configured_path

# 退出码定义（CLI-08）
EXIT_OK = 0
EXIT_USAGE = 2        # 参数/配置/锁错误
EXIT_CREDENTIALS = 3  # 必需凭据缺失
EXIT_CONFLICT = 4     # 所有权冲突/活动锁/恢复待处理
EXIT_DEPS = 5         # 依赖/原生检查失败
EXIT_INTERNAL = 6     # 文件系统/内部操作失败


class CLIParser(argparse.ArgumentParser):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, allow_abbrev=False, **kwargs)

  def fail(self, message):
    self.print_usage(sys.stderr)
    self.exit(EXIT_USAGE, f"{self.prog}: 错误: {message}\n")

  def error(self, message):
    # argparse 的原始错误可能含私有参数，不回显。
    self.fail("参数无效；请使用 --help 检查命令、参数名称和必填项")

  def _check_value(self, action, value):
    if action.choices is not None and value not in action.choices:
      self.fail(f"{action.dest}: 不支持的选择；可选: {', '.join(action.choices)}")

  def parse_args(self, args=None, namespace=None):
    tokens = list(sys.argv[1:] if args is None else args)
    # 先分离原生参数，避免 argparse 把其中的选项或 --help 当作管理器参数。
    separator = tokens.index("--") if "--" in tokens else len(tokens)
    parsed = super().parse_args(tokens[:separator], namespace)
    if separator < len(tokens) and parsed.command != "run":
      self.fail("仅 run 支持 -- 后的原生参数")
    if parsed.command == "run":
      parsed.passthrough = tokens[separator + 1:]
    if parsed.command == "init-local" and any(
      getattr(parsed, name) is not None for name in ("machine", "local", "profile")
    ):
      self.fail("init-local 仅使用子命令后的 --machine；全局选择器不适用")
    return parsed


class UniqueSelector(argparse.Action):
  def __call__(self, parser, namespace, values, option_string=None):
    if getattr(namespace, self.dest, None) is not None:
      parser.fail(f"{option_string}: 选择器不得重复")
    setattr(namespace, self.dest, values)


def selection_id(value):
  if (not isinstance(value, str) or not value or value in (".", "..")
      or any(char in value for char in ("/", "\\"))
      or any(ord(char) < 32 or ord(char) == 127 for char in value)):
    raise argparse.ArgumentTypeError("ID 必须为非空单一路径段，不得包含控制字符")
  return value


class SelectionError(Exception):
  """只承载固定的脱敏选择错误。"""


def local_path(value):
  text = str(value)
  if text.startswith("~/"):
    path = Path.home() / text[2:]
  elif text.startswith("~"):
    raise SelectionError("--local: 仅支持当前 HOME 的 ~/ 前缀")
  else:
    path = Path(text)
  if ".." in path.parts:
    # CLI 明确允许 ../ 相对选择；先逐段验证真实目录，再进行纯词法归一化。
    from .paths import _absolute_directory, _check_private
    from .storage import Conflict
    try:
      with _absolute_directory(path.absolute().parent) as parent:
        _check_private(parent)
    except (OSError, PathError):
      raise Conflict("本地配置相对路径不安全；不得穿透符号链接") from None
    path = Path(os.path.abspath(path))
  return path.absolute()


def resolve_selection(args):
  """只解析选择所需元数据；完整 schema 和秘密 resolver 由后续任务负责。"""
  if args.command == "init-local":
    args.machine = args.init_machine
    try:
      root = configured_path(os.environ.get("XDG_CONFIG_HOME") or "~/.config")
    except PathError:
      raise InitializationError(EXIT_USAGE) from None
    args.local = root / "agentcfg" / "machines" / f"{args.machine}.toml"
    return
  if args.local is None:
    args.machine = args.machine or "default"
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home) if config_home else Path.home() / ".config"
    args.local = (root / "agentcfg" / "machines" / f"{args.machine}.toml").absolute()
  else:
    args.local = local_path(args.local)

  try:
    from .config import read_local_document
    metadata = read_local_document(args.local)
  except FileNotFoundError:
    if args.machine == "default":
      raise SelectionError("默认机器文件不存在；请执行 init-local --machine default") from None
    if args.machine is not None:
      raise SelectionError("机器文件不存在；请执行 init-local --machine NAME 初始化所选机器") from None
    raise SelectionError("本地文件不存在；请检查 --local PATH") from None
  except (tomllib.TOMLDecodeError, UnicodeError):
    raise SelectionError("本地 TOML 无效；请检查语法和 UTF-8 编码") from None

  # 秘密及其他配置不交给命令；仅保留 profile 选择元数据。
  metadata.pop("secrets", None)
  machine = metadata.get("machine", {})
  if not isinstance(machine, dict):
    raise SelectionError("machine: 必须为 TOML 表")
  default_profile = machine.get("default_profile", "dsh-default")
  try:
    selection_id(default_profile)
  except argparse.ArgumentTypeError:
    raise SelectionError("machine.default_profile: 必须为合法的非空 ID") from None
  args.profile = args.profile if args.profile is not None else default_profile
  if args.command == "run" and args.cwd is None:
    args.cwd = Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器"""
    parser = CLIParser(
        prog="agentcfg",
        description="个人 Agent 配置管理器",
    )
    # 公共选择参数
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--machine",
        action=UniqueSelector,
        type=selection_id,
        metavar="NAME",
        help="选择机器配置文件（默认 default）",
    )
    selector.add_argument(
        "--local",
        action=UniqueSelector,
        metavar="PATH",
        help="直接指定本地配置文件路径",
    )
    parser.add_argument(
        "--profile",
        action=UniqueSelector,
        type=selection_id,
        metavar="ID",
        help="选择 profile（默认使用本地 default_profile，再回落 dsh-default）",
    )

    subparsers = parser.add_subparsers(dest="command", title="命令")

    # init-local: 初始化本地配置
    init_local = subparsers.add_parser(
        "init-local",
        help="初始化本地配置文件（不覆盖已有）",
    )
    init_local.add_argument(
        "--machine",
        dest="init_machine",
        action=UniqueSelector,
        type=selection_id,
        metavar="NAME",
        required=True,
        help="机器名称（init-local 专用参数）",
    )

    # validate: 离线校验
    subparsers.add_parser(
        "validate",
        help="离线校验 schema/引用/映射/锁",
    )

    # render: 离线确定性生成
    subparsers.add_parser(
        "render",
        help="离线确定性生成配置产物",
    )

    # plan: 离线差异计划
    subparsers.add_parser(
        "plan",
        help="离线展示脱敏差异/来源/漂移/冲突",
    )

    # lock: 依赖锁定
    lock = subparsers.add_parser(
        "lock",
        help="解析并提交完整依赖锁",
    )
    lock.add_argument(
        "--agent",
        required=True,
        choices=["dsh"],
        help="目标工具",
    )

    # sync: 依赖安装消费
    subparsers.add_parser(
        "sync",
        help="消费现有锁，暂存安装并注册可用运行包",
    )

    # apply: 部署配置
    subparsers.add_parser(
        "apply",
        help="离线重新检查并部署配置",
    )

    # run: 启动原生进程
    run = subparsers.add_parser(
        "run",
        help="使用已部署契约启动原生进程",
        epilog="原生参数须放在 -- 后，按 argv 原样透传（不包含分隔符）。",
    )
    run.add_argument(
        "agent",
        choices=["dsh"],
        help="目标工具",
    )
    run.add_argument(
        "--cwd",
        type=Path,
        help="工作目录（默认调用时 cwd）",
    )

    # doctor: 诊断
    doctor = subparsers.add_parser(
        "doctor",
        help="离线报告实例/依赖/漂移/备份/权限状态",
    )
    doctor.add_argument(
        "--live",
        action="store_true",
        help="允许网络检查",
    )

    # capture: 捕获提案
    subparsers.add_parser(
        "capture",
        help="捕获 allowlist 原生字段生成脱敏提案",
    )

    # rollback: 恢复上一版
    subparsers.add_parser(
        "rollback",
        help="恢复上一版受管配置",
    )

    # project: OpenSpec 项目集成
    project = subparsers.add_parser(
        "project",
        help="OpenSpec 项目集成",
    )
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_init = project_sub.add_parser(
        "init",
        help="初始化指定项目的 OpenSpec 集成",
    )
    project_init.add_argument(
        "integration",
        choices=["openspec"],
        help="集成类型",
    )
    project_init.add_argument(
        "--path",
        type=Path,
        required=True,
        help="项目路径",
    )

    return parser


def check_venv() -> None:
    """检查虚拟环境是否存在（LOCK-01）

    入口直接使用仓库 .venv，缺失时提示 uv sync --locked。
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print(
            "错误: 虚拟环境未找到\n"
            "请先执行: uv sync --locked\n"
            f"期望路径: {venv_python}",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    """命令行主入口"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_USAGE

    # 分发命令
    try:
        resolve_selection(args)
        return dispatch(args)
    except InitializationError as error:
        print(f"init-local: {error}", file=sys.stderr)
        return error.exit_code
    except SelectionError as error:
        print(f"配置错误: {error}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        return 130
    except OSError:
        print("文件系统操作失败；请检查所选文件及目录的访问权限", file=sys.stderr)
        return EXIT_INTERNAL
    except Exception as error:
        from .schema import ConfigError
        from .secrets import CredentialError
        from .storage import StateError
        from .render import RenderError
        if isinstance(error, (ConfigError, CredentialError, StateError, RenderError)):
            print(str(error), file=sys.stderr)
            return error.exit_code
        print("内部操作失败；请检查配置并报告脱敏复现步骤", file=sys.stderr)
        return EXIT_INTERNAL


def dispatch(args: argparse.Namespace) -> int:
    """命令调度"""
    from . import commands

    cmd = args.command.replace("-", "_")
    handler = getattr(commands, f"cmd_{cmd}", None)
    if handler is None:
        print(f"命令 '{args.command}' 尚未实现", file=sys.stderr)
        return EXIT_USAGE
    return handler(args)
