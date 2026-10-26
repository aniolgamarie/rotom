"""公开语法、逐叶元数据及类型化分发；复用原有业务执行器。"""
import argparse
from collections.abc import Mapping
import json
import re
from dataclasses import dataclass
import sys
from types import MappingProxyType

from termcfg.errors import TermcfgError

from .context import InputError, InputGateway, InputPolicy, InvocationContext, Scope, TypedInvocation


class Parser(argparse.ArgumentParser):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, allow_abbrev=False, **kwargs)

  def error(self, message):
    self.exit(2, "rotom: 参数无效或缺少必填项；请查看当前命令 --help\n")

  def fail(self, message=None):
    self.error(message)


@dataclass(frozen=True)
class ParameterDefinition:
  name: str
  position: tuple[str, ...]
  category: str
  required: bool
  candidate_source: str
  choices: tuple[str, ...] = ()
  repeatable: bool = False
  exclusive_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandDefinition:
  parser_leaf: tuple[str, ...]
  scope_rule: str
  parameters: tuple[ParameterDefinition, ...]
  candidate_source: str
  noninteractive_approval: str
  effects: tuple[str, ...]
  help: str
  examples: tuple[str, ...]


def _subparsers(parser):
  return next((action for action in parser._actions if isinstance(action, argparse._SubParsersAction)), None)


def parser_leaves(parser, path=(), inherited=()):
  """遍历实际 parser；祖先选择器亦属 leaf 的输入约束。"""
  sub = _subparsers(parser)
  actions = inherited + tuple(action for action in parser._actions
    if not isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)))
  if sub is None:
    yield path, (parser, actions)
  else:
    for name, child in sub.choices.items():
      yield from parser_leaves(child, (*path, name), actions)


def _selectors(parser, *, profile=False, local=True):
  from agentcfg.cli import UniqueSelector, selection_id
  group = parser.add_mutually_exclusive_group()
  group.add_argument("--machine", action=UniqueSelector, type=selection_id)
  if local:
    group.add_argument("--local", action=UniqueSelector)
  if profile:
    parser.add_argument("--profile", action=UniqueSelector, type=selection_id)


def _future_agent(parser):
  groups = _subparsers(parser)
  instances = groups.add_parser("instances", help="查询受管实例；精确停止已准入的 Linux DSH")
  commands = instances.add_subparsers(dest="instances_command", required=True)
  listing = commands.add_parser("list", help="只读列出所选范围受管实例")
  listing.add_argument("--agent", choices=("dsh", "pi", "omp"))
  listing.add_argument("--format", choices=("auto", "human", "json"), default="auto")
  stop = commands.add_parser("stop", help="预览或停止所选 Linux 受管 DSH 实例")
  stop.add_argument("--run", action="append", required=True)
  stop.add_argument("--dry-run", action="store_true")
  stop.add_argument("--plan-id")
  stop.add_argument("--wait-seconds", type=_wait_seconds, default=30)
  maintenance = groups.add_parser("maintenance", help="查询或取消普通停止批次；完整维护与批量恢复尚未准入")
  commands = maintenance.add_subparsers(dest="maintenance_command", required=True)
  for name in ("plan", "stop", "execute", "restore", "status", "cancel"):
    child = commands.add_parser(name, help=("只读 setup 计划；实际维护尚未准入" if name == "plan"
      else "查询普通停止批次" if name == "status" else "取消尚未投递的普通停止项，或核对原收尾" if name == "cancel"
      else "维护 " + name + "；当前能力待准入"))
    if name == "plan":
      targets = child.add_mutually_exclusive_group(required=True)
      targets.add_argument("--operation", choices=("setup",))
      targets.add_argument("--batch")
      child.add_argument("--run", action="append")
    elif name == "stop":
      child.add_argument("--operation", choices=("setup",), required=True)
      child.add_argument("--run", action="append", required=True)
      child.add_argument("--plan-id", required=True)
    else:
      child.add_argument("--batch", required=True)
    if name == "execute":
      child.add_argument("--plan-id")
    if name in ("stop", "restore"):
      child.add_argument("--wait-seconds", type=_wait_seconds, default=30)
    child.add_argument("--format", choices=("auto", "human", "json"), default="auto")


def _wait_seconds(value):
  number = int(value)
  if not 1 <= number <= 300:
    raise argparse.ArgumentTypeError("wait seconds out of range")
  return number


def build_parser():
  from agentcfg.cli import build_parser as agent_parser
  from termcfg.cli_parser import build_parser as term_parser
  from termcfg.work import build_parser as work_parser
  parser = Parser(prog="rotom", description="统一管理 Agent、终端与工作区",
    epilog="默认：显式参数优先；旧管理器保留既有默认。输入需要三个标准流均为 TTY。\n"
      "示例：rotom run pi；rotom agent --machine workstation profiles。\n"
      "影响：help 不读取业务配置；执行命令的联网、写入、启动和批准边界见各级帮助。")
  flags = parser.add_mutually_exclusive_group()
  flags.add_argument("--interactive", action="store_true")
  flags.add_argument("--no-input", action="store_true")
  commands = parser.add_subparsers(dest="namespace", required=True)
  run = commands.add_parser("run", help="仅使用已部署契约启动 Agent")
  run.add_argument("tool", nargs="?", choices=("dsh", "pi", "omp"))
  _selectors(run, profile=True)
  run.add_argument("--cwd")
  run.add_argument("--inherit-env", action="append", default=[])
  run.add_argument("--unset-env", action="append", default=[])
  run.add_argument("--proxy", metavar="NAME", default=None,
    help="仅本次普通启动使用 [machine.proxies.NAME] 的命名代理，优先于持久默认")
  run.epilog = "原生参数放在 -- 后；不自动安装或部署。示例：rotom run pi -- --help"
  resume = commands.add_parser("resume", help="锁定 Linux DSH 当前终端恢复交接；加载待确认")
  resume.add_argument("tool", nargs="?", choices=("dsh", "pi", "omp"), help="会话所属工具；能力分别验证")
  _selectors(resume, profile=True)
  from agentcfg.cli import selection_id
  resume.add_argument("--session", type=selection_id, help="所选 machine/local 与 profile 范围内的明确 session ID")
  location = resume.add_mutually_exclusive_group()
  for name, description in (("here", "当前终端交接，保留会话原工作目录（默认）"),
      ("original", "原终端位置恢复；需独立验证的位置能力"),
      ("new-tab", "新标签页恢复；需独立验证的位置能力")):
    location.add_argument("--" + name, action="store_true", help=description)
  resume.epilog = ("默认 --here；不发送继续文本。请求 ID、启动派发与实际加载分别判断；"
    "锁定完整运行包的 Linux managed DSH --here 已准入；无加载回执保持待确认，不自动重试或强杀。"
    "Pi/OMP、其他平台或位置返回 5；参数或范围错误为 2，冲突为 4，保留原生退出码。上游默认可能生成自动回顾。"
    "rotom agent instances list 可查询独立的请求与进程观察。\n"
    "人工继续：在官方 TUI 核对会话 ID、原目录和历史后，自行聚焦输入框，"
    "手工输入或复制所需指令（例如：继续）。Rotom 不操作剪贴板或发送按键。")
  for name, factory in (("agent", agent_parser), ("term", term_parser), ("work", work_parser)):
    backend = factory()
    if name == "agent":
      _future_agent(backend)
    commands.add_parser(name, parents=[backend], add_help=False, help=backend.description)
  config = commands.add_parser("config", help="明确查看、保存或清除入口偏好")
  children = config.add_subparsers(dest="config_command", required=True)
  children.add_parser("show", help="只读查看非秘密偏好")
  setting = children.add_parser("set", help="保存明确偏好")
  setting.add_argument("key")
  setting.add_argument("value")
  children.add_parser("unset", help="清除明确偏好").add_argument("key")
  complete = commands.add_parser("_complete", help="内部只读 NUL 候选协议")
  complete.add_argument("--kind", required=True, choices=("profile", "tool", "preset", "component",
    "preference-key", "machine", "provider", "work-type", "work-template", "work-source", "work-named", "session"))
  complete.add_argument("--namespace", choices=("agent", "term", "work"), dest="completion_namespace")
  complete.add_argument("--tool", choices=("dsh", "pi", "omp"))
  _selectors(complete, profile=True)
  complete.add_argument("--command", choices=tuple(line for line in _PATHS.splitlines() if line))
  def display_names(current, path=()):
    current.prog = " ".join(("rotom", *path))
    current.allow_abbrev = False
    children = _subparsers(current)
    if children is not None:
      for name, child in children.choices.items():
        display_names(child, (*path, name))
  display_names(parser)
  for path, (leaf, _) in parser_leaves(parser):
    leaf.set_defaults(_command_path=path)
  _configure_static_help(parser)
  return parser


# 显式公开清单独立于 parser 遍历；增删语法必须同步注册。
_PATHS = """
run
resume
config show
config set
config unset
agent init-local
agent profiles
agent setup
agent model add
agent model presets
agent model status
agent model key
agent model url
agent model enable
agent validate
agent render
agent plan
agent lock
agent sync
agent apply
agent run
agent usage
agent inventory
agent doctor
agent capture
agent rollback
agent instances list
agent instances stop
agent maintenance plan
agent maintenance stop
agent maintenance execute
agent maintenance restore
agent maintenance status
agent maintenance cancel
term components
term init-local
term plan
term doctor
term status
term apply
term recover
term lock
term sync
term migrate
term rollback
work enter
work open
work rebind
work list
work status
work reconcile
work source add
work project add
work named add
work named enter
work named rename
work config check
work config edit
work worktree create
work close
_complete
"""
_APPROVALS = {"plan_id", "accept", "yes", "scope", "adopt_target", "confirm_zshenv", "drop_mihomo"}
_APPROVAL_PATHS = {
  ("agent", "init-local"): "preview then explicit save confirmation",
  ("agent", "model", "add"): "validated fields and explicit save confirmation; hidden secrets",
  ("agent", "model", "key"): "hidden input and explicit save; no argv secret interface",
  ("agent", "model", "url"): "hidden input and explicit save; no argv secret interface",
  ("agent", "model", "enable"): "existing protocol review and hidden input if missing",
  ("agent", "setup"): "existing setup preview and deployment confirmation",
  ("term", "init-local"): "existing configuration preview and save confirmation",
  ("term", "apply"): "exact --plan-id, --adopt-target and --confirm-zshenv when required",
  ("term", "migrate"): "explicit --drop-mihomo",
  ("term", "rollback"): "review --plan-only then exact --plan-id",
  ("work", "close"): "exact --scope token plus --yes; --dry-run only observes",
  ("work", "rebind"): "explicit --accept after binding review",
  ("work", "config", "edit"): "existing preview and save confirmation",
  ("agent", "instances", "stop"): "exact --run set and current --plan-id, or interactive plan review; admitted Linux managed DSH only",
  ("agent", "maintenance", "stop"): "exact --operation, --run set and --plan-id",
  ("agent", "maintenance", "execute"): "accepted batch and original operation approval; renewed --plan-id on drift",
}
_READ_ONLY = {"profiles", "presets", "status", "plan", "validate", "doctor", "components", "list", "check", "show", "inventory", "_complete"}


_AGENT_EFFECTS = {
  "init-local": ("read:selected-machine", "write:private-machine-and-secret-placeholders"),
  "profiles": ("read:public-profiles",),
  "model presets": ("read:public-model-catalog",),
  "model status": ("read:selected-models-and-credential-presence",),
  "model add": ("read:selected-machine", "write:private-model-config-and-shared-key"),
  "model key": ("read:selected-provider", "write:private-shared-key"),
  "model url": ("read:selected-provider", "write:private-machine-url"),
  "model enable": ("read:public-preset-and-selected-machine", "write:private-model-config-and-optional-key"),
  "validate": ("read:selected-config-and-lock",),
  "render": ("read:selected-config-and-lock", "write:render-cache"),
  "plan": ("read:selected-config-and-managed-files", "write:private-diagnostic-cache-and-optional-migration-proposal"),
  "lock": ("network:dependency-resolution", "process:package-resolver", "write:public-dependency-lock"),
  "sync": ("network:locked-package-downloads", "process:locked-installers", "write:runtime-and-cache"),
  "apply": ("read:reviewed-source-and-ownership", "write:managed-instance-and-recovery-state"),
  "setup": ("network:locked-package-downloads", "process:locked-installers", "write:runtime-cache-and-managed-instance"),
  "run": ("process:native-host", "network:native-host-policy", "write:run-owner-state-and-native-session"),
  "usage": ("process:native-usage", "network:native-usage-policy", "read:native-or-explicit-managed-identity"),
  "inventory": ("read:explicit-old-native-directory", "write:private-inventory-proposal"),
  "doctor": ("read:selected-instance-and-diagnostics", "network:only-with--live", "write:private-diagnostic-cache"),
  "capture": ("read:allowlisted-native-fields", "write:private-capture-proposal"),
  "rollback": ("read:saved-managed-backup", "write:managed-instance-and-recovery-state"),
}
_TERM_EFFECTS = {
  "components": ("read:public-component-catalog",),
  "init-local": ("read:selected-machine-and-environment", "write:private-machine-selection"),
  "plan": ("read:selected-target-files-and-entry-source",),
  "doctor": ("read:selected-environment-and-target-files",),
  "status": ("read:selected-managed-files-and-transaction",),
  "apply": ("read:reviewed-exact-plan", "write:target-files-entry-binding-backups-and-transaction"),
  "recover": ("read:saved-transaction-bytes", "write:recorded-target-files-and-transaction"),
  "lock": ("network:explicit-plugin-source", "process:plugin-resolver", "write:public-plugin-lock"),
  "sync": ("network:locked-plugin-downloads", "process:plugin-downloader", "write:private-plugin-packages"),
  "migrate": ("read:legacy-ownership-metadata", "write:selected-private-ownership-metadata"),
  "rollback": ("read:saved-backup-and-plan", "write:recorded-target-files-and-transaction", "condition:--plan-only-is-read-only"),
}
_WORK_EFFECTS = {
  "enter": ("read:selected-project-and-fixed-binding", "process:focus-or-native-workspace", "write:workspace-intents-and-bindings"),
  "open": ("read:fixed-type-binding", "process:focus-or-selected-type-launch", "write:new-instance-intent-if-created"),
  "rebind": ("read:inactive-fixed-binding", "write:explicitly-accepted-type-binding"),
  "list": ("read:registered-projects-and-optional-live-observations",),
  "status": ("read:registered-binding-and-live-observations",),
  "reconcile": ("read:registered-intents-and-live-observations", "write:verified-work-reconciliation"),
  "source add": ("read:explicit-discovery-path", "write:private-source-registration", "condition:--dry-run-is-read-only"),
  "project add": ("read:explicit-project-boundary", "write:private-project-registration", "condition:--dry-run-is-read-only"),
  "named add": ("write:private-named-registration", "condition:--dry-run-is-read-only"),
  "named enter": ("read:registered-named-context", "process:focus-or-native-workspace", "write:workspace-intents-and-bindings"),
  "named rename": ("write:private-named-title-and-verified-native-title", "condition:--dry-run-is-read-only"),
  "config check": ("read:selected-work-config-and-registered-paths",),
  "config edit": ("process:explicit-editor", "write:temporary-fragment-and-reviewed-private-work-config"),
  "worktree create": ("process:local-git-and-optional-enter", "write:explicit-checkout-and-optional-work-binding", "condition:--dry-run-is-read-only"),
  "close": ("read:exact-workspace-scope", "control:explicitly-approved-workspace-close", "condition:--dry-run-is-read-only"),
}


def command_effects(path):
  if path == ("run",):
    return _AGENT_EFFECTS["run"]
  if path == ("agent", "instances", "list"):
    return ("read:selected-machine-owner-records-and-process-birth-identity",
      "network:none", "write:none", "control:none")
  if path == ("agent", "instances", "stop"):
    return ("read:selected-owner-records-and-deployed-layout-for-plan", "capability:linux-managed-dsh-stop",
      "network:none", "write:reviewed-snapshot-request-and-close", "control:original-pidfd-once",
      "condition:--dry-run-is-read-only")
  if path == ("agent", "maintenance", "plan"):
    return ("read:selected-owner-records-and-deployed-layout-for-plan", "capability:stop-maintenance-not-admitted",
      "network:none", "write:none", "control:none")
  if path == ("agent", "maintenance", "status"):
    return ("read:explicit-dsh-stop-batch", "network:none", "write:none", "control:none")
  if path == ("agent", "maintenance", "cancel"):
    return ("read:explicit-dsh-stop-batch", "network:none", "write:verified-stop-close", "control:none")
  if path == ("resume",):
    return ("capability:linux-dsh-here", "network:host-defined", "write:run-owner/resume-attempt/session", "control:handoff-only")
  if path[:2] in (("agent", "instances"), ("agent", "maintenance")):
    return ("capability:not-admitted", "network:none", "write:none", "control:none")
  if path[0] == "config":
    return ("read:non-secret-preferences",) + (("write:explicit-private-preference",) if path[-1] != "show" else ())
  if path == ("_complete",):
    return ("read:allowed-public-or-explicit-scope-ids", "network:none", "write:none", "process:none")
  table = {"agent": _AGENT_EFFECTS, "term": _TERM_EFFECTS, "work": _WORK_EFFECTS}[path[0]]
  return table[" ".join(path[1:])]


def _examples(path, leaf, actions):
  import shlex
  values = {"provider": "kimi_code_openai", "repo": "/path/to/repository", "path": "/path/to/project",
    "id": "item-example", "title": "Example", "template": "dev", "source": "/path/to/old-agent",
    "key": "run_profiles.pi", "value": "pi-pro", "plan_id": "b" * 64, "batch": "c" * 32,
    "version": "0123456789012345678901234567890123456789", "run": "a" * 32}
  tokens = ["rotom", *path]
  for action in actions:
    if not action.required or isinstance(action, argparse._SubParsersAction):
      continue
    if action.nargs == 0:
      tokens.append(action.option_strings[0])
      continue
    value = values.get(action.dest, "value-example")
    if action.choices is not None:
      value = "zsh" if action.dest == "component" else str(next(iter(action.choices)))
    tokens.extend([action.option_strings[0], value] if action.option_strings else [value])
  if path == ("run",):
    tokens = ["rotom", "run", "pi"]
  elif path == ("resume",):
    tokens += ["dsh", "--session", "session-example"]
  elif path == ("agent", "model", "key"):
    tokens[-1] = "kimi-code"
  elif path == ("agent", "usage"):
    tokens += ["--help"]
  elif path == ("work", "open"):
    tokens += ["shell"]
  elif path == ("work", "worktree", "create"):
    tokens += ["--new-branch", "task-example", "--base", "HEAD"]
  elif path == ("agent", "instances", "stop"):
    tokens += ["--dry-run"]
  elif path == ("agent", "maintenance", "plan"):
    tokens += ["--operation", "setup", "--run", "a" * 32]
  shortest = shlex.join(tokens)
  explicit = list(tokens)
  if path == ("run",):
    explicit += ["--machine", "workstation", "--profile", "pi-base"]
  elif path == ("resume",):
    explicit += ["--machine", "workstation", "--here"]
  elif path == ("agent", "init-local"):
    explicit += ["--machine", "workstation", "--profile", "dsh-default"]
  elif path[0] == "agent" and path not in (("agent", "profiles"), ("agent", "model", "presets")):
    explicit[2:2] = ["--machine", "workstation", "--profile", "omp-default" if path[-1] == "usage" else "dsh-default"]
  elif path[0] == "term" and path[-1] != "components":
    explicit[2:2] = ["--machine", "workstation"]
  elif path[0] == "work":
    explicit[2:2] = ["--local", "/path/to/work.toml"]
  return shortest, shlex.join(explicit)


def _default_help(path):
  if path == ("run",):
    return "显式machine/local/profile → defaults.agent_machine / run_profiles.TOOL → default机器与dsh-default/pi-base/omp-default；只有公开profile可推断工具。"
  if path == ("resume",):
    return "显式scope → defaults.agent_machine → default；profile只约束已知会话归属，不套用run_profiles；位置默认--here。"
  if path[:1] == ("agent",):
    return "普通目标：显式machine/local → defaults.agent_machine → default；显式profile → machine.default_profile →既有默认。公共profiles/presets、独立usage、OMP lock不读偏好或机器。instances与maintenance plan仅显式profile过滤。"
  if path[:1] == ("term",):
    return "显式machine → defaults.term_machine → default；组件保持原选择。--json显式输出原JSON对象。"
  if path[:1] == ("work",):
    return "显式machine/local → defaults.work_machine → default；已存在workspace/type的固定binding、cwd和启动契约不被偏好替换。"
  if path[:1] == ("config",):
    return "仅明确show/set/unset操作入口偏好；正常运行和菜单选择不保存偏好。"
  if path == ("_complete",):
    return "不使用偏好；provider必须显式machine/local+profile，work-kind必须显式machine/local，session还须tool（当前仅空结果）。"
  return "显式条件优先；agent、term、work各自独立machine默认；root run使用按工具profile，管理agent使用机器默认。"


def _configure_static_help(parser):
  leaves = dict(parser_leaves(parser))
  def visit(current, path=(), purpose=None):
    current.formatter_class = argparse.RawDescriptionHelpFormatter
    current.description = "用途：" + (current.description or purpose or "执行 " + " ".join(path))
    selected = [value for key, value in leaves.items() if key[:len(path)] == path]
    if path in leaves:
      leaf, actions = leaves[path]
      examples = _examples(path, leaf, actions)
      effects = command_effects(path)
    else:
      examples = ("rotom " + " ".join(path) + " --help", "rotom " + " ".join(path) + " --help")
      effects = ("导航本身无联网、写入或启动；实际影响由所选叶子明确列出。",)
    position = "根--interactive/--no-input在命名空间前；run/resume选项在命令后；agent/work选择器在子命令前，term选择器可在子命令前后；init-local的agent选择器仅在init-local后。"
    lines = ["参数位置：" + position,
      "约束：--machine与--local互斥，machine/local/profile选择器不得重复；未知参数先报2。必填位置参数和互斥组见synopsis；--表示run原生尾部边界。"]
    for action in current._actions:
      if isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)):
        continue
      label = "/".join(action.option_strings) if action.option_strings else action.dest
      lines.append("  " + label + ("：必填" if action.required else "：可选") + ("；可重复" if isinstance(action, argparse._AppendAction) else ""))
    for group in current._mutually_exclusive_groups:
      lines.append("互斥" + ("（必选其一）" if group.required else "") + "：" + " / ".join("/".join(action.option_strings) for action in group._group_actions))
    lines += ["默认优先级：" + _default_help(path),
      "输入条件：auto要求stdin/stdout/stderr全部TTY；--no-input不读输入，缺参或缺等价批准返回2；--interactive缺任一TTY返回2；取消/EOF/Ctrl-C返回130。选择目标不等于批准。",
      "副作用：" + "；".join(effects), "最短示例：" + examples[0], "显式范围示例：" + examples[1],
      "原生帮助：run --后的全部token和agent usage全部尾部含--help属于宿主；管理说明请看agent --help。"]
    if path == ("resume",):
      lines.append("根 --interactive 可在启动前选择仅显示人工文本并独立确认；文本须为可打印单行，最多4096字符/16384 UTF-8字节；不发送、不操作剪贴板或聚焦。锁定 Linux DSH --here 可用；加载待确认，不会发送继续；上游默认可能生成自动回顾。")
    if path in (("agent", "instances", "stop"), ("agent", "maintenance", "plan")):
      lines.append("--run 为完整32位小写十六进制且不得重复。instances stop --dry-run 只读预览；Linux 受管 DSH 固定锁版本的新启动可停止，旧运行/Pi/OMP 尚不支持。非交互实际停止须显式 --plan-id（缺失返回2，漂移返回4）；交互先展示计划并确认。超时/结果未知返回4和batch查询命令，不重发或强杀；maintenance status/cancel --batch 查询或取消未投递项。setup维护尚未准入。")
    if path in (("agent", "instances", "list"), ("agent", "instances", "stop"), ("agent", "maintenance", "plan")):
      lines.append("版本：deployment 是启动时配置/部署组合摘要，runtime 是锁定运行包身份；旧记录缺失时为 unknown，不按当前配置补填。版本相同不表示进程或资源已释放。")
    if path in (("agent", "maintenance", "status"), ("agent", "maintenance", "cancel")):
      lines.append("--batch 使用停止返回的完整32位小写十六进制ID。status只读；cancel只解除已确认退出或尚未投递的活动项，已投递/unknown不强行清除。写入后响应丢失须按原收尾事实对账；不重发停止或自动恢复。")
    if path == ("work", "worktree", "create"):
      lines.append("条件必填：--new-branch需要--base；--existing-branch禁止--base；创建与进入分别接受。")
    if path == ("_complete",):
      lines.append("补全stdout仅合法ID加NUL；正常缺数据0空，非法/不安全查询非零空。不读认证/会话正文，不写索引缓存；--后停止补全。")
    current.epilog = "\n".join(lines)
    sub = _subparsers(current)
    if sub is not None:
      purposes = {action.dest: action.help for action in sub._choices_actions}
      for name, child in sub.choices.items():
        visit(child, (*path, name), purposes.get(name))
  visit(parser)


def _registry(parser=None):
  leaves = dict(parser_leaves(build_parser() if parser is None else parser))
  expected = {tuple(line.split()) for line in _PATHS.splitlines() if line}
  if expected != set(leaves):
    raise ValueError("command registry and parser leaves differ")
  result = {}
  for path in sorted(expected):
    parser, actions = leaves[path]
    parameters = []
    for action in actions:
      enum_sources = {"tool": "public-tools", "agent": "public-tools", "profile": "public-profiles",
        "init_profile": "public-profiles", "component": "public-components", "preset": "public-presets",
        "provider": "selected-operation-provider-ids", "role": "selected-work-type-ids",
        "template": "selected-work-template-ids", "operation": "registered-maintenance-operations"}
      if path[:1] == ("config",):
        enum_sources["key"] = "registered-preference-keys"
      category = ("A" if action.dest in _APPROVALS else "E" if action.choices is not None or action.dest in enum_sources
        else "D" if action.option_strings and not action.required else "T")
      source = (enum_sources.get(action.dest, "registered-enum") if category == "E" else "explicit-approval" if category == "A"
        else "existing-default" if category == "D" else "explicit-text")
      exclusive = tuple(other.dest for group in parser._mutually_exclusive_groups if action in group._group_actions
        for other in group._group_actions if other is not action)
      parameters.append(ParameterDefinition(action.dest, tuple(action.option_strings) or (action.dest,), category,
        action.required, source, tuple(action.choices or ()), isinstance(action, argparse._AppendAction), exclusive))
    if path in (("run",), ("agent", "run"), ("agent", "usage")):
      parameters.append(ParameterDefinition("native_tail", ("all-tail" if path[-1] == "usage" else "--",), "N", False, "opaque-native-argv"))
    readonly = path[-1] in _READ_ONLY
    approval = _APPROVAL_PATHS.get(path, "none-required" if readonly else "complete explicit request; existing backend approval rules apply")
    shortest, scoped = _examples(path, parser, actions)
    effects = command_effects(path)
    result[path] = CommandDefinition(path, "public-only" if path[-1] in ("profiles", "presets", "components", "_complete") else "selected-namespace",
      tuple(parameters), "declared-parameter-sources", approval,
      effects,
      parser.description or "执行 " + " ".join(path), (shortest, scoped))
  return result


class _CommandRegistry(Mapping):
  """仅缓存不可变命令定义；不跨调用保存 parser 或 action。"""

  def __init__(self):
    self._definitions = None

  def _initialize(self, parser=None):
    if self._definitions is None:
      self._definitions = MappingProxyType(_registry(parser))
    return self._definitions

  def __getitem__(self, key):
    return self._initialize()[key]

  def __iter__(self):
    return iter(self._initialize())

  def __len__(self):
    return len(self._initialize())


COMMANDS = _CommandRegistry()


def _duplicates(tokens):
  seen = set()
  index = 0
  while index < len(tokens):
    token = tokens[index]
    name = token.split("=", 1)[0]
    if name in ("--machine", "--local", "--profile"):
      if name in seen or (name in ("--machine", "--local") and seen & {"--machine", "--local"}):
        raise ValueError("duplicate selector")
      seen.add(name)
      index += 1 if "=" in token else 2
    else:
      index += 1


def _opaque_tail(tokens):
  # usage 的尾部归原生程序；只跨过其前方的合法选择器。
  start = next((i for i, token in enumerate(tokens) if token not in ("--interactive", "--no-input")), len(tokens))
  if start < len(tokens) and tokens[start] == "agent":
    index = start + 1
    while index < len(tokens):
      token = tokens[index]
      if token in ("--machine", "--local", "--profile"):
        index += 2
      elif token.split("=", 1)[0] in ("--machine", "--local", "--profile"):
        index += 1
      else:
        break
    if index < len(tokens) and tokens[index] == "usage":
      return tokens[:index + 1], tokens[index + 1:]
  if "--" in tokens:
    index = tokens.index("--")
    return tokens[:index], tokens[index + 1:]
  return tokens, []


def main(argv=None, *, resume_candidate=None):
  tokens = list(sys.argv[1:] if argv is None else argv)
  parser = build_parser()
  try:
    COMMANDS._initialize(parser)
    management, native_tail = _opaque_tail(tokens)
    _duplicates(management)
    if "_complete" in management and next((token for token in management if token not in ("--no-input", "--interactive")), None) == "_complete":
      if "--" in tokens:
        return 0
      seen_options = set()
      for token in management:
        if token.startswith("--"):
          option = token.split("=", 1)[0]
          if option in seen_options:
            return 2
          seen_options.add(option)
      args = parser.parse_args(management)
      from .completion import main as complete
      return complete(args)
    if "--help" in management or "-h" in management:
      parser.parse_args(management)
    gateway = InputGateway()
    policy = InputPolicy.NO_INPUT if "--no-input" in management else InputPolicy.INTERACTIVE if "--interactive" in management else InputPolicy.AUTO
    _relax_missing(parser)
    args = parser.parse_args(management)
    validate_explicit_conditions(args)
    if policy == InputPolicy.INTERACTIVE:
      gateway.require_input(policy)
    original_management = tuple(management)
    explicit_tool = getattr(args, "tool", None) is not None
    management, args, navigated, candidate_scope, resume_candidate = complete_missing(parser, args, management, gateway, policy, resume_candidate=resume_candidate)
    path = args._command_path
    if path in (("agent", "model", "add"), ("agent", "model", "key"), ("agent", "model", "url"), ("agent", "model", "enable")):
      gateway.require_input(policy)
    if "--" in tokens and path not in (("run",), ("agent", "run"), ("agent", "usage")):
      return 2
    explicit = frozenset(token.split("=", 1)[0].lstrip("-").replace("-", "_") for token in original_management if token.startswith("--"))
    if explicit_tool:
      explicit = explicit | {"tool"}
    if not navigated:
      explicit = explicit | {"command"}
    scope = candidate_scope if candidate_scope is not None else resolve_scope(path, args, explicit)
    context = InvocationContext(path, explicit_fields=explicit, input_policy=policy,
      output_mode="json" if getattr(args, "json", False) else getattr(args, "format", "auto"), scope=scope, input_gateway=gateway)
    invocation = TypedInvocation(context, tuple(management), tuple(native_tail))
    if path == ("resume",) and resume_candidate is not None:
      from .resume import CandidateResume
      if type(resume_candidate) is not CandidateResume:
        return 5
      return resume_candidate.dispatch(invocation, args)
    return dispatch(invocation, args)
  except SystemExit as error:
    return int(error.code)
  except Exception as error:
    from .preferences import PreferenceError
    if isinstance(error, InputError):
      if error.exit_code == 2:
        print("rotom: 参数或输入条件不满足；请查看当前命令 --help，补齐必要参数；交互选择需要在终端中运行。", file=sys.stderr)
      return error.exit_code
    if isinstance(error, PreferenceError):
      print("rotom: " + str(error), file=sys.stderr)
      return error.exit_code
    if isinstance(error, TermcfgError):
      print("rotom: 参数无效；请查看当前命令 --help", file=sys.stderr)
      return error.code
    if isinstance(error, ValueError):
      print("rotom: 参数无效；请查看当前命令 --help", file=sys.stderr)
      return 2
    if isinstance(error, OSError):
      print("rotom: 文件系统操作失败", file=sys.stderr)
      return 6
    from agentcfg.paths import InitializationError
    from agentcfg.cli import SelectionError
    from agentcfg.schema import ConfigError
    from agentcfg.storage import StateError
    if isinstance(error, (InitializationError, ConfigError, StateError)):
      print("rotom: 所选范围配置无效或不可用", file=sys.stderr)
      return error.exit_code
    if isinstance(error, SelectionError):
      print("rotom: 所选范围配置无效或不可用", file=sys.stderr)
      return 2
    print("rotom: 内部操作失败；请报告脱敏复现步骤", file=sys.stderr)
    return 6
  except KeyboardInterrupt:
    return 130


def validate_explicit_conditions(args):
  """显式条件冲突先失败，不能交给补参菜单纠正。"""
  path = getattr(args, "_command_path", None)
  if path == ("agent", "instances", "stop") or path is not None and path[:2] == ("agent", "maintenance"):
    runs = getattr(args, "run", None)
    plan_id = getattr(args, "plan_id", None)
    if runs is not None and (any(re.fullmatch(r"[0-9a-f]{32}", run) is None for run in runs)
        or len(runs) != len(set(runs))):
      raise InputError(2)
    if plan_id is not None and re.fullmatch(r"[0-9a-f]{64}", plan_id) is None:
      raise InputError(2)
    if path in (("agent", "maintenance", "status"), ("agent", "maintenance", "cancel")):
      batch = getattr(args, "batch", None)
      if batch is not None and re.fullmatch(r"[0-9a-f]{32}", batch) is None:
        raise InputError(2)
  if path in (("run",), ("resume",), ("agent", "run")):
    profile = getattr(args, "profile", None)
    if profile is not None:
      inferred = _profile_tool(profile)
      tool = getattr(args, "tool", None) or getattr(args, "agent", None)
      if tool is not None and inferred != tool:
        raise InputError(2)
  if path == ("work", "worktree", "create") and args.existing_branch is not None and args.base is not None:
    raise InputError(2)


def _relax_missing(parser):
  for action in parser._actions:
    action._rotom_required = action.required
    action._rotom_nargs = action.nargs
    if isinstance(action, argparse._SubParsersAction):
      action.required = False
      for child in action.choices.values():
        _relax_missing(child)
    elif action.required:
      action.required = False
      if not action.option_strings and action.nargs is None:
        action.nargs = "?"
  for group in parser._mutually_exclusive_groups:
    group._rotom_required = group.required
    group.required = False


def _restore_missing(parser):
  """同次调用恢复严格约束；不跨调用共享可变 parser。"""
  for action in parser._actions:
    action.required = action._rotom_required
    action.nargs = action._rotom_nargs
    if isinstance(action, argparse._SubParsersAction):
      for child in action.choices.values():
        _restore_missing(child)
  for group in parser._mutually_exclusive_groups:
    group.required = group._rotom_required


def _candidate_rows(path, action, args):
  if action.choices is not None:
    return [(str(choice), str(choice)) for choice in action.choices]
  if path == ("config",) or action.dest == "key" and path[:1] == ("config",):
    from .preferences import KEYS
    return [(key, key) for key in KEYS]
  if action.dest == "template" and path[:1] == ("work",):
    from termcfg.work_config import read_settings
    explicit = frozenset(name for name in ("machine", "local") if getattr(args, name, None) is not None)
    scope = resolve_scope(path, args, explicit)
    settings = read_settings(machine=scope.machine, local=scope.local)
    return ([(key, key) for key in settings.structured.get("templates", {})], scope)
  if action.dest == "provider":
    from agentcfg.cli import resolve_selection
    from agentcfg.workspace import load_workspace
    from types import SimpleNamespace
    from dataclasses import replace
    explicit = frozenset(name for name in ("machine", "local", "profile") if getattr(args, name, None) is not None)
    scope = resolve_scope(path, args, explicit)
    selected = SimpleNamespace(command="model", model_command=path[-1], machine=scope.machine, local=scope.local, profile=scope.profile)
    resolve_selection(selected)
    workspace = load_workspace(selected.local, selected.profile, allow_missing_local_values=True)
    frozen = replace(scope, profile=selected.profile, sources={**scope.sources, "profile": scope.sources.get("profile", "existing-default")})
    keys = [key for key, provider in workspace.resolved.data["providers"].items() if provider.get("auth_kind") == "api-key"]
    if path[-1] == "key":
      keys = list(dict.fromkeys(["kimi-code", "glm-code", "deepseek", *keys]))
    return ([(key, key) for key in keys], frozen)
  return None


def complete_missing(parser, args, management, gateway, policy, *, resume_candidate=None):
  tokens = list(management)
  current, path = parser, ()
  navigated = False
  candidate_scope = None
  while True:
    sub = _subparsers(current)
    if sub is None:
      break
    selected = getattr(args, sub.dest, None)
    if selected is None:
      summaries = {item.dest: item.help for item in sub._choices_actions}
      rows = [(name, child.description or summaries.get(name) or name) for name, child in sub.choices.items() if name != "_complete"]
      selected = gateway.choose(rows, policy=policy, label=current.prog)
      tokens.append(selected)
      args = parser.parse_args(tokens)
      navigated = True
    path = (*path, selected)
    current = sub.choices[selected]
  validate_explicit_conditions(args)
  if path == ("resume",):
    if getattr(args, "session", None) is None:
      gateway.require_input(policy)
    if resume_candidate is None:
      # 只在实际叶子（含根菜单）完成语法核验后懒建；帮助/补全不触达后端。
      from .resume import dsh_candidate
      resume_candidate = dsh_candidate()
  for action in current._actions:
    required = getattr(action, "_rotom_required", False)
    required = required or (path in (("run",), ("resume",)) and action.dest == "tool"
      and not (path == ("run",) and getattr(args, "profile", None)))
    required = required or (path == ("resume",) and action.dest == "session")
    if path == ("resume",) and resume_candidate is not None and action.dest in ("tool", "session"):
      required = False
    missing = getattr(args, action.dest, None) is None or isinstance(action, argparse._StoreTrueAction) and not getattr(args, action.dest, False)
    if required and missing:
      gateway.require_input(policy)
      if action.dest in _APPROVALS:
        if action.nargs == 0:
          gateway.confirm(action.option_strings[0], policy=policy)
          tokens.append(action.option_strings[0])
        else:
          value = gateway.text(action.dest + "（已有批准证据）", policy=policy)
          tokens.append(action.option_strings[0] + "=" + value)
        args = parser.parse_args(tokens)
        continue
      rows = _candidate_rows(path, action, args)
      if action.dest in ("provider", "template") and isinstance(rows, tuple):
        rows, candidate_scope = rows
      value = (gateway.choose(rows, policy=policy, label=action.dest) if rows is not None
        else gateway.text(action.dest, policy=policy))
      tokens.extend([action.option_strings[0] + "=" + value] if action.option_strings else [value])
      args = parser.parse_args(tokens)
  for group in current._mutually_exclusive_groups:
    if getattr(group, "_rotom_required", False) and not any(getattr(args, action.dest, None) is not None for action in group._group_actions):
      selected = gateway.choose([(action.dest, action.option_strings[0]) for action in group._group_actions], policy=policy)
      action = next(action for action in group._group_actions if action.dest == selected)
      value = gateway.text(action.dest, policy=policy)
      tokens.append(action.option_strings[0] + "=" + value)
      args = parser.parse_args(tokens)
  if path == ("work", "worktree", "create") and args.new_branch is not None and args.base is None:
    value = gateway.text("base（明确的本地基线）", policy=policy)
    tokens.append("--base=" + value)
  # 完成后仍走严格实际 parser，确保补齐不削弱原语法约束。
  _restore_missing(parser)
  args = parser.parse_args(tokens)
  return tokens, args, navigated, candidate_scope, resume_candidate


def _profile_tool(profile):
  from agentcfg.local import available_profiles
  profiles = dict(available_profiles())
  if profile not in profiles:
    raise ValueError("unknown public profile")
  return profiles[profile]


def resolve_scope(path, args, explicit):
  """只应用当前命令需要的偏好；显式目标始终是硬约束。"""
  from .preferences import load_preferences, validate_reference
  machine = getattr(args, "init_machine", None) or (getattr(args, "machine", None) if "machine" in explicit else None)
  local = getattr(args, "local", None)
  profile = getattr(args, "init_profile", None) or getattr(args, "profile", None)
  agent = getattr(args, "tool", None) or getattr(args, "agent", None)
  sources = {name: "explicit" for name, value in (("machine", machine), ("local", local), ("profile", profile), ("agent", agent)) if value is not None}
  public_only = path in (("agent", "profiles"), ("agent", "model", "presets"), ("term", "components"))
  public_only = public_only or (path == ("agent", "usage") and profile is None)
  public_only = public_only or (path == ("agent", "lock") and agent == "omp")
  if path[0] in ("config", "_complete") or public_only:
    return Scope(machine, local, agent, profile, tuple(getattr(args, "component", None) or ()), sources)
  if path in (("run",), ("resume",), ("agent", "run")) and profile is not None:
    inferred = _profile_tool(profile)
    if agent is not None and inferred != agent:
      raise ValueError("tool profile mismatch")
    if agent is None and path == ("run",):
      agent, sources["agent"] = inferred, "profile"
  if path == ("run",) and agent is None:
    raise ValueError("tool required")
  preferences = load_preferences()
  namespace = "agent" if path[0] in ("run", "resume", "agent") else path[0]
  if machine is None and local is None:
    key = "defaults." + namespace + "_machine"
    selected = preferences.get(key)
    machine = selected if selected is not None else "default"
    sources["machine"] = "preference" if selected is not None else "default"
    if selected is not None:
      validate_reference(key, selected)
  if path == ("run",) and profile is None:
    key = "run_profiles." + agent
    selected = preferences.get(key)
    profile = selected if selected is not None else {"dsh": "dsh-default", "pi": "pi-base", "omp": "omp-default"}[agent]
    sources["profile"] = "preference" if selected is not None else "default"
    if selected is not None:
      validate_reference(key, selected)
    if _profile_tool(profile) != agent:
      raise ValueError("tool profile mismatch")
  return Scope(machine, local, agent, profile, tuple(getattr(args, "component", None) or ()), sources)


def dispatch(invocation, args):
  path = invocation.context.command_path
  if path == ("agent", "instances", "list"):
    return dispatch_instances(invocation, args)
  if path == ("agent", "instances", "stop"):
    return dispatch_stop_plan(invocation, args)
  if path in (("agent", "maintenance", "status"), ("agent", "maintenance", "cancel")):
    return dispatch_stop_status(invocation, args)
  if path == ("agent", "maintenance", "plan") and args.operation is not None:
    if not args.run:
      return 2
    return dispatch_stop_plan(invocation, args)
  if path == ("resume",):
    if args.tool is None or args.session is None:
      return 2
    print("rotom: 所选组合的恢复能力尚未准入", file=sys.stderr)
    if invocation.context.input_policy == InputPolicy.INTERACTIVE:
      from .manual_continue import offer
      scope = invocation.context.scope
      location = "original" if args.original else "new-tab" if args.new_tab else "here"
      offer(invocation.context, f"参数仅请求、未核验：tool={args.tool} / machine={scope.machine} / "
        f"local={scope.local} / profile={scope.profile} / session={args.session} / location={location} / cwd=未知")
    print("人工恢复：在所选工具的官方 TUI 中选择并核对会话 ID、原目录和历史；"
      "确认后自行聚焦输入框，手工输入或复制所需指令（例如：继续）。", file=sys.stderr)
    return 5
  if path[0] == "config":
    from .preferences import load_preferences, update_preference
    if path[-1] == "show":
      print(json.dumps(load_preferences().data, ensure_ascii=False, sort_keys=True))
    else:
      update_preference(args.key, args.value if path[-1] == "set" else None)
    return 0
  if path[0] == "_complete" or path[:2] in (("agent", "instances"), ("agent", "maintenance")):
    print("rotom: 此能力尚未开放", file=sys.stderr)
    return 5
  if path == ("run",):
    if args.tool is None and args.profile is None:
      return 2
    from agentcfg.cli import main as backend
    tokens = []
    for name in ("machine", "local", "profile"):
      value = getattr(invocation.context.scope, name)
      if value is not None:
        tokens += ["--" + name, value]
    tokens += ["run", invocation.context.scope.agent]
    if args.cwd is not None:
      tokens += ["--cwd", args.cwd]
    for name in ("inherit_env", "unset_env"):
      for value in getattr(args, name):
        tokens += ["--" + name.replace("_", "-"), value]
    if args.proxy is not None:
      tokens += ["--proxy", args.proxy]
    tokens += ["--", *invocation.native_tail]
  else:
    if path[0] == "agent":
      from agentcfg.cli import main as backend
    elif path[0] == "term":
      from termcfg.cli import main as backend
    else:
      from termcfg.work import main as backend
    namespace_index = invocation.tokens.index(path[0])
    tokens = list(invocation.tokens[namespace_index + 1:])
    if invocation.context.scope.sources.get("machine") in ("preference", "default"):
      if path == ("agent", "init-local"):
        tokens += ["--machine", invocation.context.scope.machine]
      else:
        tokens = ["--machine", invocation.context.scope.machine, *tokens]
    if invocation.context.scope.sources.get("profile") == "existing-default" and getattr(args, "profile", None) is None:
      tokens = ["--profile", invocation.context.scope.profile, *tokens]
    if path == ("agent", "usage"):
      tokens += list(invocation.native_tail)
    elif path == ("agent", "run"):
      tokens += ["--", *invocation.native_tail]
  return backend(tokens, context=invocation.context)


def dispatch_instances(invocation, args):
  from agentcfg.cli import local_path
  from agentcfg.paths import xdg_config_home
  from agentcfg.run_owners import instances
  scope = invocation.context.scope
  local = local_path(scope.local) if scope.local is not None else (
    xdg_config_home() / "agentcfg" / "machines" / ((scope.machine or "default") + ".toml"))
  result = instances(local, agent=scope.agent, profile=scope.profile)
  refresh = ["rotom", "agent", "--local", str(local)]
  if scope.profile is not None:
    refresh += ["--profile", scope.profile]
  refresh += ["instances", "list"]
  if scope.agent is not None:
    refresh += ["--agent", scope.agent]
  result["next_commands"] = {"refresh": refresh, "resume": None}
  if args.format == "json" or (args.format == "auto" and not sys.stdout.isatty()):
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
  else:
    from agentcfg.presentation import _text
    import shlex
    def line(value):
      print(_text(value))
    print("实例观察（进程、会话及终端位置分别判断；控制能力未开放）")
    for row in result["instances"]:
      process, session = row["process"], row["session"]
      manager = process["manager_identity"]
      host = process["host_identity"]
      line(f"{row['agent']} / {row['profile']}  run={row['run_id'] or 'unknown'}")
      version = row.get("deployed_identity")
      line(f"  deployment={version['deployment'] if version else 'unknown'} "
        f"runtime={version['runtime'] if version else 'unknown'}（启动时登记版本）")
      line(f"  process={process['status']} manager={manager['pid'] if manager else 'unknown'} "
        f"host={host['identity']['pid'] if host else 'unknown'} (host_status=unknown) "
        f"source={process['source']} observed_at_ns={process['observed_at_ns']} coverage={process['coverage']}")
      start, cwd = row["start_cwd"], row["session_cwd"]
      line(f"  start_cwd={start['path'] if start else 'unknown'} session_cwd={cwd['path'] if cwd else 'unknown'}")
      ref = session["ref"]
      line(f"  session={ref['native_ref'] if ref else 'unknown'} ({session['status']}) "
        f"source={session['source'] or 'unknown'} observed_at_ns={session['observed_at_ns'] or 'unknown'}; "
        "terminal=unknown; resume=unavailable")
      request = row.get("resume_request")
      if request is not None:
        if request["source"] == "resume-request-unavailable":
          line("  恢复请求记录不可核实；当前会话仍按独立观察判断。")
        else:
          line(f"  requested_session={request['requested_session']['native_ref']} "
            f"requested_cwd={request['requested_cwd']} resume={request['status']} "
            f"native_exit={request['exit_code'] if request['exit_code'] is not None else 'unknown'}")
          if request["status"] == "unknown":
            line("  派发结果待核实；加载未确认；未发送继续。")
          elif request["status"] == "failed":
            line("  原生进程失败；加载未确认；未发送继续。")
          elif request["exit_code"] is None:
            line("  已发起恢复，加载待确认；请在 TUI 检查；未发送继续。")
          else:
            line("  已取得原生退出码；加载待确认；未发送继续。")
    for item in result["coverage"]:
      line(f"  coverage {item['agent']}/{item['profile']}: {item['status']} "
        f"source={item['source']} observed_at_ns={item['observed_at_ns']}")
    line("再次观察：" + shlex.join(refresh))
  print("rotom: 列表只读；unknown 和未登记项不能作为空闲或可维护的证明。", file=sys.stderr)
  return 4 if result["incomplete"] else 0


def dispatch_stop_plan(invocation, args):
  """预览当前计划，实际请求须通过独立审阅和现场重核。"""
  from copy import deepcopy
  from agentcfg.cli import local_path
  from agentcfg.paths import xdg_config_home
  from agentcfg.presentation import _text
  import shlex
  context = invocation.context
  stopping = context.command_path == ("agent", "instances", "stop")
  if (stopping and not args.dry_run and args.plan_id is None
      and not context.input_gateway.allows_input(context.input_policy)):
    return 2
  from agentcfg.dsh_stop import preview_for_scope
  scope = context.scope
  local = local_path(scope.local) if scope.local is not None else (
    xdg_config_home() / "agentcfg" / "machines" / ((scope.machine or "default") + ".toml"))
  observed = preview_for_scope(local, selected_runs=list(args.run), profile=scope.profile,
    operation="stop_only" if stopping else args.operation)
  plan = observed["plan"]
  supplied = getattr(args, "plan_id", None)
  if supplied is not None and supplied != plan["plan_id"]:
    print("rotom: 当前只读计划与 --plan-id 不一致；请重新预览，未请求停止", file=sys.stderr)
    return 4
  targets = deepcopy(observed["targets"])
  for target in targets:
    if target["session_status"] in ("confirmed", "final", "historical"):
      target["session_status"] = "historical"
  exact = plan["scope"]
  preview = ["rotom", "agent", "--local", exact["local"], "--profile", exact["profile"]]
  preview += ["instances", "stop"] if stopping else ["maintenance", "plan", "--operation", "setup"]
  for run in plan["selected_runs"]:
    preview += ["--run", run]
  if stopping:
    preview += ["--dry-run"]
  value = {"readonly": True, "scope": deepcopy(exact), "plan_id": plan["plan_id"],
    "selected_runs": list(plan["selected_runs"]), "targets": targets, "readiness": plan["readiness"],
    "blockers": list(plan["blockers"]), "plan": plan, "next_commands": {"preview": preview}}
  if stopping and not args.dry_run and plan["readiness"] == "ready":
    from agentcfg.dsh_stop import workspace_for_scope
    from agentcfg.dsh_stop_client import execute_stop
    workspace = workspace_for_scope(local, selected_runs=list(args.run), profile=exact["profile"])
    def approve(current):
      if supplied is not None:
        return supplied == current["plan_id"]
      # 确认前展示所选版本、进程、目录与会话；交互不发生在任何元数据锁中。
      print(_text(json.dumps(value, ensure_ascii=False, sort_keys=True)), file=sys.stderr)
      return context.input_gateway.confirm("仅停止计划中的实例；保存恢复清单，共享资源覆盖仍为 unknown",
        policy=context.input_policy)
    result = execute_stop(workspace, expected_plan=plan, approve=approve, wait_seconds=args.wait_seconds)
    render_stop_result(result, output=getattr(args, "format", "auto"))
    return 0 if result["status"] == "stopped" else 4
  output = getattr(args, "format", "auto")
  if output == "json" or output == "auto" and not sys.stdout.isatty():
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
  else:
    def line(text): print(_text(text))
    line("DSH 只读停止计划；历史会话信息不证明加载或可恢复。实际停止须重新核验；setup维护尚未准入。")
    line(f"scope: local={exact['local']} profile={exact['profile']} agent={exact['agent']}")
    line(f"plan_id={plan['plan_id']} readonly=true readiness={plan['readiness']}")
    line("selected_runs=" + ", ".join(plan["selected_runs"]))
    for target in targets:
      manager, host = target["manager_identity"], target["host_identity"]
      start, cwd, session = target["start_cwd"], target["session_cwd"], target["session_ref"]
      line(f"run={target['run_id']} manager={manager['pid'] if manager else 'unknown'} "
        f"host={host['identity']['pid'] if host else 'unknown'}（仅历史登记）")
      version = target.get("deployed_identity")
      line(f"  deployment={version['deployment'] if version else 'unknown'} "
        f"runtime={version['runtime'] if version else 'unknown'}（启动时登记版本）")
      line(f"  start_cwd={start['path'] if start else 'unknown'} session_cwd={cwd['path'] if cwd else 'unknown'} "
        f"session={session['native_ref'] if session else 'unknown'} ({target['session_status']})")
    line("blockers=" + (", ".join(plan["blockers"]) or "none"))
    for resource in plan["resources"]:
      line(f"  resource={resource['key']['kind']} coverage={resource['coverage']} "
        "reference_runs=" + ", ".join(resource["reference_runs"]))
    line("再次只读预览：" + shlex.join(preview))
  if stopping and not args.dry_run:
    print("rotom: 当前组合或现场状态不支持停止；以上仅为只读计划，未批准或发送停止", file=sys.stderr)
    return 5
  return 0


def render_stop_result(result, *, output="auto"):
  from agentcfg.presentation import _text
  import shlex
  value = dict(result)
  exact = value["scope"]
  prefix = ["rotom", "agent", "--local", exact["local"], "--profile", exact["profile"], "maintenance"]
  value["next_commands"] = {name: prefix + [name, "--batch", value["batch_id"]] for name in ("status", "cancel")}
  if output == "json" or output == "auto" and not sys.stdout.isatty():
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
  else:
    print(_text(f"停止批次 {value['batch_id']}：{value['status']}；未发送继续。"))
    print(_text("共享资源覆盖仍为 unknown；停止完成不表示配置可以立即改写。"))
    for row in value.get("targets", []):
      print(_text(f"  {row['run_id']}: {row['lifecycle_state']} request={row['request']} dispatch={row['dispatch']}"))
      target = row.get("target")
      if target:
        manager, host = target["manager_identity"], target["host_identity"]
        cwd, session = target["start_cwd"], target["session_ref"]
        print(_text(f"    manager={manager['pid'] if manager else 'unknown'} "
          f"host={host['identity']['pid'] if host else 'unknown'} start_cwd={cwd['path'] if cwd else 'unknown'} "
          f"session={session['native_ref'] if session else 'unknown'} ({target['session_status']})"))
        deployed = target.get("deployed_identity") or {}
        print(_text(f"    deployment={deployed.get('deployment', 'unknown')} "
          f"runtime={deployed.get('runtime', 'unknown')}（启动时登记版本）"))
    print(_text("查询：" + shlex.join(value["next_commands"]["status"])))
    if value["status"] not in ("stopped", "cancelled"):
      print(_text("仅未投递的活动项可取消：" + shlex.join(value["next_commands"]["cancel"])))


def dispatch_stop_status(invocation, args):
  from agentcfg.cli import local_path
  from agentcfg.paths import xdg_config_home
  from agentcfg.dsh_stop_client import workspace_for_batch, status_stop
  from agentcfg.dsh_stop_completion import close_stop
  context = invocation.context
  scope = context.scope
  local = local_path(scope.local) if scope.local is not None else (
    xdg_config_home() / "agentcfg" / "machines" / ((scope.machine or "default") + ".toml"))
  workspace = workspace_for_batch(local, batch_id=args.batch, profile=scope.profile)
  result = status_stop(workspace, batch_id=args.batch)
  if context.command_path[-1] == "cancel" and result["status"] not in ("stopped", "cancelled"):
    close_stop(workspace, batch_id=args.batch, plan_id=result["plan_id"], reason=result.get("close_reason") or "cancelled")
    result = status_stop(workspace, batch_id=args.batch)
  render_stop_result(result, output=args.format)
  return 4 if result["status"] in ("unknown", "snapshot_only") else 0
