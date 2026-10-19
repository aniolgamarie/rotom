"""静态任务导航与注册参数提示；不探测机器配置或原生宿主。"""

import argparse
import shlex


ENTRY_GUIDE = """usage: ./agentcfg [--machine NAME | --local PATH] [--profile ID] COMMAND
agentcfg：选择目标 → 检查/预览 → 明确部署 → 启动
首次使用: profiles → init-local → model status → setup → run
日常启动: run 使用已部署的所选 profile，不隐式同步或部署。
诊断预览: doctor 查看原因，plan 查看拟变更；离线检查可写诊断文件。
模型配置: model --help；key/URL 使用已有隐藏输入，不写在命令行。
依赖维护: sync 消费现有锁；lock 仅用于有意重新解析依赖。
恢复处理: rollback 恢复配置；不自动停止进程或恢复账号。
公共选择参数在命令前；init-local 的 --machine/--profile 在子命令后。
完整帮助: ./agentcfg --help；局部帮助: ./agentcfg COMMAND --help
原生帮助: usage --help 和 run -- --help 属于原生参数，不是管理器帮助。"""


_SELECTION_HELP = (
  "公共选择参数 --machine NAME / --local PATH 与 --profile ID 位于命令前。\n"
  "--machine 与 --local 互斥；全局选择器不得重复。\n"
  "init-local 例外：--machine/--profile 位于子命令后，不接受全局选择器。\n"
  "profiles 与 model presets 是公共目录入口，不接受选择器。"
)


DESCRIPTIONS = {
  (): "个人 Agent 配置与运行包管理器。\n"
    "首次: profiles → init-local → model status → setup → run。\n"
    "日常: run；诊断/预览: doctor / plan；依赖维护: sync / lock；恢复: rollback。\n"
    "先明确目标与前置条件；这些入口不是自动执行的命令序列。",
  ("init-local",): "创建或补齐私人机器配置与共享空占位，不部署、不验证账号。\n"
    "--machine/--profile 仅放在本子命令后；新机器默认 dsh-default。\n"
    "已有机器默认使用 default_profile；补齐其它 profile 不替换已有默认选择。",
  ("profiles",): "列出公共配方，无需初始化私人配置，不接受机器或 profile 选择器。\n"
    "终端显示表格；管道保留 TSV。",
  ("setup",): "先预览并检查漂移/冲突，再同步现有锁的依赖，随后重新校验并部署。\n"
    "同步可能联网、安装运行包；部署会写入受管实例。不是盲目串联 plan/sync/apply。\n"
    "先补齐所选 profile 的必要配置；不会登录账号，也不会修改当前默认 profile。",
  ("model",): "模型子命令：status 查配置缺项，key/url 隐藏填写，add/enable 增加配置。\n"
    "model status 是配置视图，不是部署、账号或服务连通性检查。",
  ("model", "add"): "交互添加 provider、模型与角色绑定，并校验私人配置；不是登录或部署。\n"
    "需要已有交互终端；取消与非交互限制沿用当前配置输入规则。",
  ("model", "presets"): "查看公共模型目录；--verbose 展开价格、地址和来源。\n"
    "不接受机器/profile 选择器，不检查密钥或账号。",
  ("model", "status"): "检查所选模型配置的缺项和填写位置；会检查引用密钥是否已填写。\n"
    "不验证密钥有效性、部署同步、账号登录或服务连通性。",
  ("model", "key"): "隐藏输入并保存共享 API key；引用同一 key 的工具/profile 共用。\n"
    "只传 provider ID，不把秘密值放进 argv、日志或 shell 历史。",
  ("model", "url"): "隐藏输入并保存所选 profile 的私人模型服务地址。\n"
    "只传 provider ID；保存后按模型命令反馈决定是否需要重新部署。",
  ("model", "enable"): "追加公共预设的协议路线，保留已有角色；必要时隐藏输入缺少的 key。\n"
    "这是私人配置修改，不是账号登录或部署成功的证明。",
  ("validate",): "离线校验配置、引用、适配映射和依赖锁；不部署、不验证在线账号。",
  ("render",): "离线生成配置产物并写入缓存；不部署受管实例。离线不等于零文件写入。",
  ("plan",): "离线预览拟变更、漂移和冲突；会写私人诊断文件，不部署。\n"
    "--from-pi-home 只读盘点显式旧 Pi home 并写迁移提案。\n"
    "提案和计划不是接管授权；先审阅后再决定后续操作。",
  ("lock",): "有意重新解析并写入公共依赖锁，可能联网；用于依赖版本维护。\n"
    "普通使用由 sync 消费现有锁。锁缺失或无效时先核对/恢复仓库锁，不直接重建。",
  ("sync",): "消费现有锁，暂存安装并注册完整运行包；可能联网和写入缓存。\n"
    "不更新依赖锁、不部署配置；完成后按 plan/setup 或已部署契约判断下一步。",
  ("apply",): "重新检查当前来源、所有权和恢复条件，再部署受管配置。\n"
    "不会绕过漂移、冲突、活动实例或凭据边界；先审阅 plan。",
  ("run",): "使用已部署契约启动原生进程；不隐式 sync/apply。\n"
    "agent 可省略，由所选 profile 推断；显式 agent 只校验匹配，不切换 profile。\n"
    "原生参数仅在 -- 后提供；CLI 本层不解释或重排参数；--cwd 只选工作目录。\n"
    "后续既有受管身份、凭据及适配器边界检查仍适用。\n"
    "示例要求相应 profile 已初始化并部署；原生登录见对应集成指南。",
  ("usage",): "CLI 本层不解释或重排 OMP 原生 usage 的全部尾部，包括 --help。\n"
    "后续既有受管身份、凭据及适配器边界检查仍适用。\n"
    "不提供管理器局部 help；前置显式 profile 使用受管身份，否则沿用原生入口。",
  ("inventory",): "只读盘点显式旧 OMP 目录，写入私人审阅提案；不部署、不接管账号。",
  ("doctor",): "报告所选实例的部署、依赖、漂移、恢复和已收集的诊断信息。\n"
    "默认离线；可能计算差异并写诊断文件，不是轻量状态快照。\n"
    "--environment 显示变量名及来源；--input 检查终端/受管事件，不读取按键。\n"
    "--live 才允许在线检查；HTTP 可达不代表登录成功或模型调用成功。",
  ("capture",): "捕获允许的原生字段并生成脱敏提案，不直接改写公共来源。\n"
    "这是审阅提案入口，不是恢复或绕过所有权检查。",
  ("rollback",): "恢复上一版受管配置，保留活动实例、所有权和恢复检查。\n"
    "仅恢复配置；不自动终止原生进程或恢复账号。",

}


# 示例保留为 token，打印时统一引用；测试只解析，不调度任何操作。
EXAMPLES = {
  (): (("profiles",), ("init-local",), ("--machine", "workstation", "doctor", "--format", "human")),
  ("init-local",): (("init-local", "--machine", "workstation", "--profile", "dsh-default"),),
  ("profiles",): (("profiles",),),
  ("setup",): (("--machine", "workstation", "setup"),),
  ("model",): (("model", "status"), ("model", "presets")),
  ("model", "add"): (("model", "add"),),
  ("model", "presets"): (("model", "presets", "--verbose"),),
  ("model", "status"): (("--machine", "workstation", "model", "status"),),
  ("model", "key"): (("model", "key", "kimi-code"),),
  ("model", "url"): (("--profile", "omp-kernel", "model", "url", "kimi_tf"),),
  ("model", "enable"): (("model", "enable", "deepseek"),),
  ("validate",): (("validate",),),
  ("render",): (("render",),),
  ("plan",): (("plan",), ("--profile", "pi-base", "plan", "--from-pi-home", "/path/to/old-pi-home")),
  ("lock",): (("--profile", "dsh-default", "lock", "--agent", "dsh"),),
  ("sync",): (("--machine", "workstation", "sync"),),
  ("apply",): (("--machine", "workstation", "apply"),),
  ("run",): (("run",), ("--profile", "omp-default", "run", "--cwd", "/path/to/workspace"),
    ("--profile", "pi-base", "run", "--", "--help")),
  ("usage",): (("usage", "--help"),),
  ("inventory",): (("inventory", "omp", "--source", "/path/to/old-omp-agent"),),
  ("doctor",): (("--machine", "workstation", "doctor", "--environment", "--input", "--format", "human"),),
  ("capture",): (("capture",),),
  ("rollback",): (("--machine", "workstation", "rollback"),),

}


def configure_help(parser):
  """只遍历已注册语法；显示元数据不参与参数接受、选择或调度。"""
  context = {"parser": parser}
  def visit(current, path):
    current.guidance_path = path
    current.guidance_context = context
    current.formatter_class = argparse.RawDescriptionHelpFormatter
    current.description = DESCRIPTIONS.get(path, current.description)
    examples = EXAMPLES.get(path, ())
    lines = ["示例（须先满足所选配置与命令前置条件）:"]
    lines.extend("  " + shlex.join(("./agentcfg", *words)) for words in examples)
    if not path:
      lines.extend(("", _SELECTION_HELP,
        "原生尾部: CLI 本层不解释或重排 usage 的全部尾部及 run -- 后的原生参数。\n"
        "后续既有受管身份、凭据及适配器边界检查仍适用。",
        "配置默认值与安全边界见 docs/getting-started.md 和 docs/operations.md。"))
    elif path not in (("profiles",), ("model", "presets"), ("init-local",)):
      lines.extend(("", "公共选择器放在命令前；完整规则见 ./agentcfg --help。"))
    current.epilog = "\n".join(lines)
    for action in current._actions:
      if isinstance(action, argparse._SubParsersAction):
        for name, child in action.choices.items():
          visit(child, (*path, name))
  visit(parser, ())


def action_label(action):
  if isinstance(action, argparse._SubParsersAction):
    return "子命令"
  return "/".join(action.option_strings) if action.option_strings else action.dest


def error_guidance(parser):
  """只输出注册名称、choices 和固定文本，不读取或拆解 argparse 原始错误。"""
  path = getattr(parser, "guidance_path", ())
  required = [action_label(action) for action in parser._actions if action.required]
  lines = []
  if required:
    lines.append("本命令必需参数: " + ", ".join(required))
  for group in parser._mutually_exclusive_groups:
    lines.append("互斥选项: " + " / ".join(action_label(action) for action in group._group_actions))
  if path == ("init-local",):
    lines.append("init-local 的 --machine/--profile 仅放在子命令后；不接受全局选择器。")
  elif path not in (("profiles",), ("model", "presets")):
    lines.append("公共选择参数 --machine/--local/--profile 放在命令前；init-local 使用子命令后的 --machine/--profile。")
  lines.append("帮助: " + shlex.join(("./agentcfg", *path, "--help")))
  return "\n".join(lines)
