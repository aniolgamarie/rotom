"""静态任务导航和参数说明；显示帮助不读取配置或检查宿主。"""

ENTRY_GUIDE = """termcfg：独立管理 zsh / tmux 公开配置

首次配置：components → init-local → doctor / plan → apply → status
日常查看：status 看受管目标；doctor 查环境；plan 看将要发生的变化。
可选插件：sync 显式联网准备；lock 仅供维护者更新仓库依赖锁。
异常处理：先处理恢复/漂移；不要直接重试覆盖。旧元数据用 migrate 显式迁移。

  ./termcfg init-local --component zsh --component tmux
  ./termcfg --machine workstation status
  ./termcfg plan --help

下一步：./termcfg --help 查看全部命令；COMMAND --help 查看参数和示例。
此导航不检查机器状态，也不会自动执行任何步骤。
"""

ROOT_HELP = """按任务使用：
  发现/初始化  components, init-local
  观察/预览    status, doctor, plan
  显式变更     sync, apply, rollback
  维护/恢复    lock, recover, migrate

--machine NAME 与 --json 可放在命令前或命令后。
默认 machine 是 default；默认输出人类摘要，管道不会自动切换 JSON。
--json 保持一个结果对象；已有交互确认/进度在 stderr，JSON 不代表同意。
只管理 zsh/tmux；不提供代理、core 或 service 管理。

示例：
  ./termcfg components
  ./termcfg --machine workstation status --json
  ./termcfg --machine workstation plan --component zsh
"""

COMMANDS = {
  "components": ("列出公开组件及目标，无需机器配置", """只读公开目录，不检查私人 HOME 或原生程序。
示例：./termcfg components"""),
  "init-local": ("保存私人机器和组件选择，不部署目标文件", """写私人机器元数据；首次使用 --component（可重复）或 --none。
TTY 可交互选择；非 TTY 必须显式选择。已有机器需 --edit 并确认保存。
没有选择组件不等于环境就绪；之后用 doctor / plan 检查。
示例：
  ./termcfg init-local --component zsh --component tmux
  ./termcfg --machine workstation init-local --component zsh
  ./termcfg init-local --edit --none"""),
  "status": ("查看受管目标、漂移、备份和待恢复事务", """离线检查环境和目标文件；不是只看元数据的缓存状态。
不启动 shell/tmux，不验证当前会话是否加载了新配置。
--home 仅改变诊断视图，不授权写入；写入前对保存目标重新 plan。
示例：./termcfg --machine workstation status --component zsh"""),
  "doctor": ("诊断必需程序、可选插件和目标安全状态", """默认离线；必需程序缺失需由用户准备，不自动安装。
可选插件/fzf 缺失是降级，不等于必需环境失败。
默认报告可退出 0；--strict 在必需阻塞时返回 4（待恢复）或 5。
--home 仅用于诊断；不能用其结果授权保存 HOME 上的写入。
示例：./termcfg --machine workstation doctor --component zsh --strict"""),
  "plan": ("预览逐目标变化、接管要求和计划 ID", """离线预览，不写 HOME；ready 不等于已同意接管。
必须审阅目标/计划 ID；自定义 .zshenv 另需确认。
--home 是诊断覆盖；该视图的计划 ID 不可用于保存目标的 apply。
示例：./termcfg --machine workstation plan --component zsh"""),
  "apply": ("备份后写入已审阅目标；保留所有接管和计划校验", """写目标文件和私人事务/备份；不会自动下载可选插件或重启 shell/tmux。
TTY 审阅并确认；非 TTY 必须提供当前 --plan-id。
接管用 --adopt-target（可重复）；自定义 .zshenv 需额外 --confirm-zshenv。
先执行下例检查目标，再显式 apply；不要把示例当成已取得同意：
  ./termcfg --machine workstation plan --component zsh"""),
  "sync": ("显式联网准备一个组件的锁定可选插件", """下载并验证仓库已锁定插件，写私人包/选择；不安装 zsh/tmux 程序，
不写 HOME 配置，不自动 apply。每次必须显式选一个组件。
示例：./termcfg --machine workstation sync --component zsh"""),
  "lock": ("维护者显式联网更新公开插件锁", """修改仓库锁，不部署机器；--version 必须是完整提交 ID。
zsh 未提供 --plugin 时使用 zinit；tmux 必须提供 --plugin。
新增插件还需 --repo 和 --entry，来源须在现有允许前缀内。
这不是普通诊断故障的自动修复；已有锁准备使用 sync。
示例：./termcfg lock --component zsh --version 0123456789012345678901234567890123456789"""),
  "recover": ("按保存的事务安全恢复目标；机器级操作", """只恢复仍匹配事务事实的目标，不强行覆盖漂移，不接受 --component。
会写目标/私人状态；应先查看 status。无待恢复事务不会虚构恢复。
示例：./termcfg --machine workstation recover"""),
  "rollback": ("预览或恢复一个组件的上一版配置", """--plan-only 仅预览；执行回滚会写目标/私人事务状态。
TTY 需确认；非 TTY 必须提供当前回滚 --plan-id。
必须先解决待恢复事务；漂移不自动覆盖。
示例：./termcfg --machine workstation rollback --component zsh --plan-only"""),
  "migrate": ("显式退役旧 mihomo 所有权元数据", """必须提供 --drop-mihomo；机器级元数据变更，不管理代理文件或服务。
待恢复事务必须先处理；不接受 --component。
示例：./termcfg --machine workstation migrate --drop-mihomo"""),
}

OPTION_HELP = {
  "machine": "选择机器配置（默认 default；命令前后均可）",
  "json": "输出一个 JSON 结果对象（不代表确认；默认人类摘要）",
  "component": "选择组件；plan/doctor/status/apply/init-local 可重复，其他命令只选一个",
  "edit": "显式修改已有机器选择，不部署 HOME 配置",
  "none": "显式保存空组件选择，与 --component 互斥",
  "home": "诊断 HOME 覆盖；不修改保存目标，不授权部署",
  "strict": "必需环境阻塞时返回非零，可选降级不作为必需失败",
  "plan_id": "使用本次选定目标的已审阅计划 ID；非 TTY 执行必填",
  "adopt_target": "显式同意接管计划中的目标 ID（可重复）",
  "confirm_zshenv": "以当前计划 ID 额外确认自定义 .zshenv 整文件替换",
  "version": "维护者选择的完整插件提交 ID（40 位十六进制）",
  "plugin": "插件 ID（zsh 默认 zinit；tmux 必填）",
  "timeout": "下载超时秒数（默认 300；允许 10–3600）",
  "drop_mihomo": "明确退役旧代理所有权元数据（必填）",
  "plan_only": "只预览回滚目标和回滚计划 ID，不执行写入",
}


def describe_options(parser):
  for action in parser._actions:
    if action.dest in OPTION_HELP:
      action.help = OPTION_HELP[action.dest]


def argument_label(action):
  return "/".join(action.option_strings) if action.option_strings else action.dest.upper()


def parameter_guidance(parser, detail="参数无效；请检查名称、位置和必填项"):
  required = [argument_label(action) for action in parser._actions
              if action.required and action.option_strings]
  if required:
    detail += "。本命令必填：" + "、".join(required)
  return detail
