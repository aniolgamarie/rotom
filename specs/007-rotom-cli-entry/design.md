# Rotom 统一入口、交互补全与 zsh 接入方案

状态：首轮、补充差异与整体用户旅程审阅均已完成并修订；尚未实现。本文中的 `rotom` 命令均为拟议接口。

设计源码基线：`17bbacd6ab8be8f397e6356ce21822b422b41eed`；后续 `main` 变化已单独盘点，见 [基线复核](review.md#整理更新与基线复核)。
工作分支：`design/rotom-cli-entry`。
从 [当前计划总览](README.md) 查看已定决策、阶段门槛和阅读顺序。本文是中文项目设计记录；当前使用方式和支持范围仍以 [文档索引](../../docs/README.md) 为准。

## 1. 目标与范围

用户应能在任意项目目录输入 `rotom`，发现任务、补齐必要选择并启动 DSH、Pi 或 OMP；熟悉命令后可以完整输入参数直接操作。各级 help 和 zsh 补全提供同一套命令信息。

| 编号 | 已讨论需求 | 本方案位置 |
| --- | --- | --- |
| R1 | 使用项目名作为统一入口，关联现有管理能力 | 第 3 节 |
| R2 | DSH、Pi、OMP 具有一致的短启动命令 | 第 4 节 |
| R3 | `rotom run` 和其它子命令缺参时提供选择与提醒 | 第 5 节 |
| R4 | 每一级 help 可查询用途、参数、示例和操作影响 | 第 6 节 |
| R5 | 通过受管 zsh 部署入口、PATH 和补全 | 第 7 节 |
| R6 | 使用独立 worktree，先审阅方案再实施 | 第 10、11 节及 [审阅记录](review.md) |
| R7 | 更新前查看活跃运行、便捷停止，更新后恢复会话和终端位置 | [维护与会话恢复探索](maintenance.md) |
| R8 | session ID 可查询，CLI resume 可作为日常恢复入口 | 第 4.3、6 节及维护方案第 4、8 节 |

首阶段交付统一入口、按工具启动、各级任务导航和缺参补全、help、私人默认设置，以及 zsh 入口与补全的受管部署。`work` 通过门面继续使用既有项目工作区能力。OMP 工作区 launcher 扩展单独列入后续阶段，不能据 `rotom run omp` 可用就宣称它已支持工作区 type。

首阶段的 `resume` 只包括静态命令/help 和明确的能力提示，不将返回“不支持”的接口算作会话恢复交付。第二阶段优先完成 DSH 的可靠会话索引与当前终端中的实际 resume，不等待 Pi/OMP 达到同一能力。批量停止、原 pane 保留和自动继续各自依赖后续能力，完整完成标准见第 10 节。

新增的活跃实例与维护恢复需求单独记录在 [维护方案](maintenance.md)。统一入口提供未来接入点；批量停止、原生会话恢复、原 pane 保留和自动继续需按能力分别验收，不计入本阶段已具备的能力。

所有 Agent 继续使用未修改的上游实现。配置、运行包、活动实例、原生账号及会话的所有权和准入仍由现有模块负责；本次不改变这些边界，不引入后台服务或自动修复循环。

## 2. 已核对的现状与设计差异

| 当前事实 | 来源 | 对新设计的影响 |
| --- | --- | --- |
| `agentcfg` 按 machine/local 和单个 `machine.default_profile` 选择目标 | [cli.py](../../src/agentcfg/cli.py)、[local schema](../../schemas/local.schema.json) | 按工具默认 profile 是新能力，必须显式解析后传给旧运行层 |
| `agentcfg run pi` 的 `pi` 只核对 profile-agent 匹配，不切换 profile | [commands.py](../../src/agentcfg/commands.py)、[workspace.py](../../src/agentcfg/workspace.py) | 新 `rotom run pi` 与此语义有区别，help 要明确说明 |
| `run` 默认使用当前目录，沿用已部署契约，不隐式 sync/apply | [cli.py](../../src/agentcfg/cli.py)、[runtime.py](../../src/agentcfg/runtime.py) | 新入口直接复用此路径 |
| 旧 CLI 的无参导航是静态的，参数错误不会进入新向导 | [上一轮 CLI 设计](../../docs/design/cli-interaction.md) | 本方案只为新 `rotom` 入口增加任务导航和交互补全，保留旧入口契约 |
| zsh 已将 `$HOME/.local/bin` 加入 PATH，已有插件与兜底补全初始化 | [zshrc.zsh](../../terminals/zsh/zshrc.zsh) | 启动器可安装到该目录，补全目录须在 compinit 前接入 |
| termcfg 按固定来源摘要部署普通文件，journal 记录写前/写后身份 | [catalog.py](../../src/termcfg/catalog.py)、[preview.py](../../src/termcfg/preview.py)、[transaction.py](../../src/termcfg/transaction.py) | checkout 绑定是新增生成产物，须覆盖计划、写入、恢复和回滚 |
| 工作区 type 可配置，但 launcher 枚举仍没有 OMP | [work_config.py](../../src/termcfg/work_config.py)、[工作区 CLI 契约](../006-configurable-workspaces/contracts/cli.md) | 首阶段不更改既有工作区 type、固定 binding、操作时限或能力拒绝 |

现有机器上的 `dsh` 快捷方式来源尚未核实。本方案不通过读取私人 shell、密钥或会话文件来猜测它，也不自动改写这些入口。

## 3. 命令结构与兼容策略

```text
rotom [--interactive | --no-input] COMMAND ...

COMMAND:
  run       按工具与配方启动已部署 Agent
  resume    选择或指定原生会话并恢复；按适配器能力开放
  agent     Agent 配置、模型、依赖、部署与诊断
  term      zsh/tmux/可选 Herdr 配置及恢复
  work      既有项目与工作区操作
  config    只管理 Rotom 的私人入口偏好
```

`--interactive`、`--no-input` 是新门面的互斥控制参数，规范写法放在根命令后、命名空间前。它们不进入宿主原生 argv，也不充当任何接管或写入批准。

```sh
rotom run pi --profile pi-pro
rotom agent --machine workstation --profile pi-pro setup
rotom term --machine workstation status
rotom work --machine workstation open pi
rotom --no-input term --machine workstation sync --component zsh
```

命名空间内沿用各工具现有语法。尤其保留 `agent init-local` 的子命令后选择器、`term` 的 machine/json 位置规则，以及 `work` 的子命令前 machine/local 规则。首阶段不通过扫描、重排任意 argv 来统一这些差异。

新入口把解析结果转为类型明确的调用上下文，交给现有命令处理器；不拼接 shell 字符串、不使用 `eval`、不通过重新解析显示文本调度。

兼容入口 `agentcfg`、`termcfg` 和 `work` 继续可用，既有参数接受规则、默认设置、输出格式、退出码和无参行为保留。现有 Python 包名、项目包名、配置目录、实例 HOME、缓存与状态路径不因命令品牌更名而迁移。

`rotom agent run` 保留低层兼容语义；日常文档推荐根命令 `rotom run TOOL`。首阶段不增加 `rotom pi`、`rotom dsh` 等另一套简写。

### 3.1 输出与原生参数

- `agent` 的现有结构化命令继续使用 `--format auto|human|json`；`term` 和 `work` 继续使用各自的 `--json`，不引入统一结果 schema。
- 新选择器、范围提示、进度和等价命令写 stderr，最终结果留在既有输出通道。原生进程继承终端和退出状态。
- `run` 的第一个 `--` 之后全部属于原生 argv，Rotom 不再解释、补全或重排这些 token。后端原有身份与参数边界检查继续执行。
- `agent usage` 保留既有例外：其全部尾部属于 OMP，包括 `--help`。没有显式 profile 时不注入保存的 machine/profile 默认值，也不隐式转为受管调用。
- 建议命令由合法 token 和当前调用前缀生成，保留 machine/local、profile、component 等作用范围；不替换旧结果中的任意命令字符串。

## 4. 目标选择、默认设置与短启动

```text
rotom run [TOOL] [--machine NAME | --local PATH] [--profile ID]
          [--cwd PATH] [--inherit-env NAME] [--unset-env NAME] [-- ARGS...]
```

`TOOL` 仅为 `dsh`、`pi`、`omp`。`--machine` 与 `--local` 互斥且不可重复；`--cwd` 默认调用目录；环境变量参数仅传名称，沿用现有优先级和秘密值边界。

### 4.1 私人入口偏好

建议新增 `${XDG_CONFIG_HOME:-$HOME/.config}/rotom/config.toml`，仅保存入口偏好，不复制机器配置、项目注册、模型或密钥。

```toml
schema_version = 1

[defaults]
agent_machine = "workstation"
term_machine = "workstation"
work_machine = "workstation"

[run_profiles]
dsh = "dsh-default"
pi = "pi-base"
omp = "omp-default"
```

三个 machine 默认值分别对应三个管理面的配置命名空间，相同名字不证明它们共享 HOME、部署或所有权。`run_profiles` 只用于根命令 `rotom run`；它不改变 `rotom agent setup` 等管理命令的 `machine.default_profile`。因此，准备和重试提示必须始终带上实际选中的 profile。

拟议管理命令：

```sh
rotom config show
rotom config set defaults.agent_machine workstation
rotom config set run_profiles.pi pi-pro
rotom config unset run_profiles.pi
```

`config` 无子命令时进入偏好任务菜单。`set` 缺少 key 时从允许的 key 选择，缺少值时按字段提供选择或文本输入；完整参数直接执行明确的偏好更新。`show` 只读此非秘密文件，不显示真实模型地址或账号内容。

配置采用严格 schema，未知字段、损坏、符号链接和不安全权限明确失败，不能解释成“首次使用”。保存使用原子替换、外部编辑快照复核及私人目录/文件权限 `0700/0600`。选择器不会自动保存“上次使用”。

### 4.2 解析顺序

1. 先完成参数合法性检查。任何显式无效值、重复选择器或缺少选项值都报错，不通过菜单纠正。
2. machine/local 使用显式选择；否则使用对应命名空间保存的 machine；仍未设置时使用既有 `default`。默认文件不存在时提示初始化或显式切换，不扫描其它机器来猜测。
3. 根 `run` 未给 TOOL 但有显式 profile 时，从该公开 profile 推断工具；显式 TOOL 和 profile 不一致时报 2。两者都没有时，交互终端列出匹配公开配方；非交互返回 2。
4. TOOL 已知时，profile 依次采用显式 profile、保存的 `run_profiles.TOOL`、该工具内建默认配方：`dsh-default` / `pi-base` / `omp-default`。保存值失效或属于其它工具时报 2，不静默降级。
5. 管理命令继续沿用所选机器的 `machine.default_profile` 及既有回落。`profiles`、`model presets`、独立 `usage` 和固定公开配方的 `lock --agent omp` 均无需机器作用域，不注入 machine 或读取相关私人配置。命令注册表显式声明作用域，不能先统一加载机器再分发这些例外。
6. 固定最终 machine/local、工具、profile、cwd，再调用既有 `run`。合法的入口默认值不证明该目标已初始化、已部署、依赖完好或账号可用。

`--interactive` 在有交互终端时允许重新选择未显式提供的字段；显式参数保持约束。它可在 Pi Base/Pro 之间选择，但不绕过显式 `--profile`。没有实际可选字段时直接继续。

下表同时作为命令注册表的作用域验收依据，避免所有命令先解析同一份默认 profile：

| 路径 | machine/local 来源 | profile 来源 |
| --- | --- | --- |
| 根 `run` | 显式选择 → agent_machine → default | 显式 profile → 对应 run_profiles → 工具内建默认 |
| 根 `resume` | 显式选择 → agent_machine → default | 该范围内的会话归属；显式 profile 是硬约束，不自动收窄到 default_profile |
| `agent` 的普通所选目标命令 | 显式选择 → agent_machine → default | 显式 profile → machine.default_profile → 既有回落 |
| `agent instances list` | 显式选择 → agent_machine → default | 没有显式 profile 时，查看该范围全部受管运行元数据 |
| `term` | 显式 machine → term_machine → default | 不适用 |
| `work` | 显式 machine/local → work_machine → default | 项目/type 的明确设置或已保存固定 binding，入口偏好不覆盖 |
| help、公开目录、独立 usage、固定 OMP lock | 无需业务机器作用域 | 不注入任何默认 profile |

偏好菜单可提供“将同一个名称设为三类入口默认值”的一次保存操作，但必须分别验证对应配置面，显示缺失项，不复制机器文件、不初始化其它工具，也不把同名当作共享所有权。这是省输入的选项，不增加第四套隐式默认值。

### 4.3 日常会话恢复入口

session ID 和 resume 是日常能力，维护批次复用它们，不另建一套恢复执行路径。run ID、PID、原生 session ID 和 Herdr pane ID 分别表示一次受管调用、进程、持久会话和终端位置，不能互相替代。

```text
rotom resume [TOOL] [--session ID] [--machine NAME | --local PATH]
             [--profile ID] [--here | --original | --new-tab]
```

```sh
rotom resume
rotom resume dsh
rotom resume dsh --session session-example
rotom resume pi --profile pi-pro --session session-example --here
rotom resume --help
```

这些是拟议管理接口；具体工具只有通过公开恢复能力和受管边界验证后才开放，不代表 OMP 当前已允许 resume。管理器的 `--session` 是类型明确的会话引用，不承诺各宿主共享相同原生参数或 ID 格式。

- TTY 中省略 session 时，列出当前作用域已知的会话，按工具、profile、session ID、目录、记录时间、活跃/已停止/未知状态与可恢复性选择。`rotom resume dsh` 只列 DSH；必要参数不足的非交互调用返回 2。
- machine/local 使用显式选择，否则使用 `defaults.agent_machine`，再回落既有 `default`。显式 machine/local、工具和 profile 都是硬约束；先限制作用域再查 session，不能因其它机器有唯一同名记录而跨范围搜索或切换。local 的归属按既有实例绑定核对，不以相同 machine ID 合并不同 local 文件。未指定 profile 时列出所选 machine/local 内各 profile 的已知会话，不先按 `machine.default_profile` 隐藏其它条目。
- 会话信息来自公开事件或已验证的只读元数据通道，入口侧只保留最小索引，不复制会话数据库，不扫描对话正文。第一版只覆盖已可靠登记的会话；不能以空索引宣称宿主没有历史。
- session 标识至少绑定工具、backend、原生 HOME 和原生引用。ID 不视为全局唯一；同一 ID 有多个匹配时必须补充 scope。已知记录唯一匹配时使用其明确的 profile/native HOME，不能被 `run_profiles` 默认值覆盖。
- 显式 ID 尚未登记时，必须先确定工具/profile，并通过该适配器公开接口验证其存在与所属存储。无法验证则给出人工恢复方式，不扫描其它 HOME、不猜测同名会话、不静默冷启动。显式 profile 与已知归属冲突时报错。
- `resume --session ID` 省略工具时，仅从已经限定的 machine/local 索引中推断唯一匹配。多个匹配在 TTY 中要求选择明确条目，非交互返回 2；没有匹配时，TTY 可补工具/profile，非交互返回 2 并给出完整示例。没有匹配不触发跨机器或全 HOME 搜索，也不把未知 ID 当作新会话名称。
- 已有匹配会话 writer 活跃时，提供经核验的聚焦或所在位置说明，避免重复启动；writer 归属未知时拒绝自动恢复。实际恢复保持原有原生 writer 租约及准入检查。
- 默认在当前终端恢复；交互时可选择原位置或新标签页。`--here`、`--original`、`--new-tab` 互斥，且只选择终端位置，不改变恢复 cwd。从项目 B 的终端恢复项目 A 的会话，仍必须采用经核验的项目 A 路径。原位置不可验证时给出明确失败或重新选择，不能静默换位置。一个 TTY 同时只启动一个交互宿主。
- 每个适配器显式声明恢复 cwd 的公开规则：优先核验原生会话 cwd，只有公开契约明确允许时才采用已记录启动 cwd。两种记录冲突、路径失效、超出已部署工作区/权限边界，或原生恢复可能切换到未经预检的 cwd 时，重新审阅或拒绝自动恢复；不能回落到调用者 cwd。会话加载后也要核验实际 SID/cwd；缺少可靠元数据或检查接口时保留人工恢复。
- 恢复后需确认实际加载的 session ID；只派发了启动、原生会话未确认或结果未知时分别报告，不能统一显示“恢复成功”。不额外发送“继续”消息，相关批准与接收验证见维护方案第 9 节。

可查询的实例/会话列表和启动/退出提示应显示确认过的 session ID，以及不含秘密的等价 `rotom resume` 命令；未获得 ID 时显示未知并说明获取途径。DSH 公开的 `statusBar.sessionId` 初始化设置目前为 false，可将新实例的推荐初始显示改为开启；既有用户设置不持续覆盖，变更需显式操作。

resume 命令与索引可以独立于批量维护推进，但指定会话加载、writer 排他、cwd 和原生 HOME 兼容仍是前置能力。接口存在不意味着所有工具已经支持自动恢复；首个候选为 DSH，Pi 单独验收，OMP 保持现有拒绝直到边界有可验证设计。

## 5. 交互补全与提醒

### 5.1 统一规则

新门面的自动选择器只在 stdin、stdout、stderr 都连接 TTY，且未使用 `--no-input` 时启用。`--interactive` 在不满足此条件时返回 2，不重新打开 `/dev/tty`。根 `--help` 和各级 help 始终优先走静态查询路径。

| 情况 | 行为 |
| --- | --- |
| `rotom` 或 `rotom agent` / `term` / `agent model` | 进入该层任务导航；未选择实际任务前不读取私人配置 |
| 合法命令缺少可枚举的选择参数 | 展示该命令真实允许的值；已给出的范围参数继续生效 |
| 完整参数或已有有效默认值 | 直接进入现有操作；需要的预览与确认仍然存在 |
| 必需自由文本缺失 | 仅在明确支持的表单字段中输入；路径、版本等不凭空推断 |
| 显式错误、未知字段、`--cwd` 后无值等格式错误 | 返回 2，提示当前层 help，不进入修复向导 |
| 管道、脚本、`--no-input` | 不显示菜单、不补猜输入；缺参返回 2 和完整示例 |
| Esc、Ctrl-C、EOF 发生在尚未提交的交互中 | 退出 130，不把默认高亮行当作接受，不产生当前动作的副作用 |

根任务菜单包括“启动 Agent / 恢复会话 / 管理 Agent / 管理终端 / 项目工作区 / 入口偏好 / 帮助”。任务列表来自注册命令元数据；恢复尚未准入时标注能力限制，选择后只给静态说明，不读取无关配置或启动宿主。`rotom work` 无子命令时先进入工作区任务导航；后续候选、type 和动作仍按既有工作区契约生成，不把已移除 type 重新当成创建选项。

所有经新门面触发的选择与确认，包括 `rotom work` 的既有候选/action/type 选择，都使用可注入的同一选择器接口，必须有不依赖第三方工具的编号兜底。较长候选列表支持分页或过滤，并沿用既有数量限制；显示层不能删掉有不同操作语义的行。空输入重新提示或取消，不隐式执行第一项。可选方向键或 fzf 前端只能返回相同的不透明选项 ID；不可把显示文本当作命令。旧独立 `work` 保留原选择器行为，新增兜底不要求更改其默认依赖。

### 5.2 需要覆盖的路径

| 调用 | 选择内容 |
| --- | --- |
| `rotom run` | 工具与配方可一次展示，固定 machine 后选择，不强制逐层重复提问 |
| `rotom resume` / `rotom resume dsh` | 在当前 scope 中选择可验证的原生会话，显示 session ID；不会自动选择“最近会话” |
| `rotom --interactive run pi` | 展示 Pi 配方；显式 profile 存在时不覆盖它 |
| `rotom agent model key` / `url` | 当前 scope 中符合该操作要求的 provider ID，再复用隐藏输入 |
| `rotom agent model enable` | 允许的公开 preset；协议遵循原有默认或显式参数 |
| `rotom agent lock` | 先从公开维护目标选择 agent；选 OMP 不读取机器，选 DSH/Pi 后才解析其所需作用域；显式不匹配仍报错 |
| `rotom term sync` / `rollback` | 只列命令支持且已登记的组件；sync 仍为一次一个组件 |
| `rotom term init-local` | 复用已有组件选择、保存预览及确认；Herdr 保持显式 opt-in |
| `rotom work open` / `rebind` | 仅补齐已配置、当前契约允许的 type；进入后沿用固定 binding 和操作时限 |
| `rotom work source add` 等注册动作 | 复用现有 schema 和字段输入；保存注册与进入项目仍是不同动作 |

`--plan-id`、接管目标、`--confirm-zshenv`、关闭工作区 scope token、`--accept`、`--yes` 等授权相关参数不能从一个选择器的接受动作中自动推导或补造。支持交互确认的原命令仍执行原有审阅；原生能力不足的命令仍拒绝。

每个注册命令的参数都要声明为“枚举选择 / 文本或路径输入 / 已有默认值 / 授权证据 / 原生尾部”之一。上表是代表性路径，不是完整白名单；实现时逐个核对所有叶子命令，缺参必须有已声明的输入方式或清晰错误，不能遗漏冷门维护命令。合法值只有一个时可以使用已声明默认，但不能把唯一可见选项解释成写入批准。

每个可能确认的动作还须声明非交互策略：完整参数本身是否构成该动作请求、是否另需原有 plan/adopt/accept 等参数、是否只有交互批准路径。没有等价非交互授权方式时，新门面在 `--no-input` 下返回 2，不能默认回答 yes；已构成所有权、活动或未知结果冲突时仍返回 4。不得为交互便利新增一个绕过所有操作审批的通用 `--yes`。选择已声明目标和满足变更授权是两个独立检查。

`--no-input` 必须经统一调用上下文传到既有确认、隐藏输入、work 选择器等所有实际读取输入的位置，不能只隐藏门面菜单。work 当前经 `main(...)` 递归分发的候选动作、enter 和 rebind，也必须显式传递相同的交互策略、调用前缀与 scope；不得在递归入口重新生成默认上下文。需要隐藏输入但没有非交互接口的模型命令返回 2；不会因此新增 argv 密钥参数。非交互 apply 继续要求真实 plan ID 和原有接管证据。显式 JSON 保留原格式，脚本应同时使用 `--no-input` 防止任何终端提示。

### 5.3 显示范围和未就绪提醒

以下为界面示意，不是本机执行证据：

```text
$ rotom run

启动哪个 Agent？
机器：workstation
目录：/path/to/project

1  DSH       dsh-default
2  Pi Base   pi-base
3  Pi Pro    pi-pro
4  OMP       omp-default

选择编号；Ctrl-C / EOF 取消：
```

首版选择列表只依赖公开配方和已选 machine/local 的必要非秘密元数据，不自动运行 `doctor`、解析 SecretRef、读取原生账号或检查所有运行包。默认不展示“就绪”状态。若展示已有部署事实，必须验证记录的目标绑定并标为“已记录部署；启动时检查”；损坏、不安全、变化中的记录不能当作未部署。

选择完成后可以向 stderr 显示经过引用的等价管理命令，不包含隐藏输入或秘密值。实际 `run` 的检查若发现未部署、依赖缺失、冲突或待恢复，保留原原因码并给出带完整 scope 的下一步。

未部署时，仅在同一调用上下文仍允许交互时提供“查看计划 / 准备并部署 / 返回”。非 TTY、重定向或 `--no-input` 路径直接保留原失败结果、退出码和完整 scope 的静态建议，不调用后续菜单或操作。交互选择是下一项独立操作：只有用户明确选择后才进入 `plan` 或 `setup`，并保留其原有预览与确认。完成准备后回到结果页，不自动启动宿主；用户再次选择启动。仅改 key、仅改配置、更新锁分别遵循现有操作指南，不统一提示重装。

已经独立确认并完成的上一项操作不会因之后取消而回滚。实际写入开始后，取消和失败沿用当前操作的 journal、未知结果和恢复语义。

## 6. Help、错误引导与补全契约

```sh
rotom --help
rotom run --help
rotom run pi --help
rotom resume --help
rotom agent model key --help
rotom term apply --help
rotom work worktree create --help
rotom config set --help
```

每一级命令必须提供：用途和 synopsis、直接子命令、完整参数及位置约束、必填/互斥/可重复规则、默认值优先级、TTY/非 TTY 行为、至少一个最短示例和一个显式作用域示例，以及联网、写文件、启动宿主、接管和恢复的影响说明。

业务 help 不初始化配置、不读取入口偏好、机器文件、密钥或会话、不联网、不创建诊断文件、不启动选择器或宿主。直接从仓库执行 `./rotom ... --help` 不需要已安装的 checkout 绑定。通过已部署启动器执行时，启动层允许只读第 7 节唯一的非秘密 `entry.json` 来定位安装；这是 help 之前的安装定位阶段，不扩展到其它私人文件。绑定损坏时给出安装修复诊断，不扫描其它 checkout 以强求 help 成功。

help 不要求业务配置已经部署；Python 和仓库运行环境仍是工具安装前提，环境缺失时由启动层给出修复提示，不能假报完整 help 已可用。两种入口的安装定位和业务 help 分开验收。

```sh
rotom run pi --help       # Rotom 的启动帮助，不启动 Pi
rotom run pi -- --help    # 原生尾部；走实际受管启动和后端边界检查
rotom agent usage --help # 保留 OMP usage 的透明尾部契约
```

`agent usage` 的管理层说明放在 `rotom agent --help` 中，不能抢占原生尾部。旧入口的这一例外也保留。

命令注册信息作为 parser、help、任务菜单和静态补全的共同来源；显示名称与内部选项 ID 分离。等价命令和错误帮助按已识别的合法命令路径生成，不回显未知参数或秘密值，不通过正则批量替换 `agentcfg` 字样。

zsh Tab 补全覆盖命令、参数、公开 profile、工具、组件，以及显式请求的非秘密 machine/type ID。动态补全按当前层允许的 schema 取值，不遍历实例目录或解析凭据，不执行 `doctor`/宿主/网络。补全失败时退回静态候选，不输出不完整 JSON 或原始异常。`--` 之后交还原生输入，首阶段不为宿主扩展补全。

动态查询使用内部 `rotom _complete` 接口，根任务菜单不展示它，其 `--help` 仍是静态说明。接口只接受已声明的 kind、namespace、tool、profile、machine/local 和已注册 command 路径，不接受 shell 表达式或完整原生 argv：

```sh
rotom _complete --kind profile --tool pi
rotom _complete --kind machine --namespace term
rotom _complete --kind work-type --machine workstation
rotom _complete --kind session --machine workstation --tool dsh
```

| kind | 来源与作用域 | 限制 |
| --- | --- | --- |
| `profile`、`tool`、`preset`、`component`、`preference-key` | 公开目录/注册元数据，按工具和命令支持范围过滤 | 不加载业务机器配置或推断授权 |
| `machine` | 对应 namespace 配置目录中的安全普通文件名 | 只返回合法 ID，不打开其它机器正文猜默认 |
| `provider` | 明确选择的 agent machine/profile 的 provider ID | 仅允许字段名，不解析 SecretRef，不输出 URL 或 key |
| `work-type`、`work-template`、`work-source`、`work-named` | 已选 work 配置的相应非秘密 ID 字段 | 不查询 live endpoint，不把 type 补全当作允许创建的证明；项目路径沿用普通路径输入/补全，不伪装成 ID |
| `session` | 第 4.3 节同一受限会话索引，按 machine/local、工具和显式 profile 过滤 | 第二阶段准入后启用；只给合法 CLI session ID，原生路径引用不能作为 ID 输出 |

静态命令/参数补全直接使用注册元数据，不另设动态查询。表中 kind 是完整允许集合，新增 kind 必须补来源和范围契约；菜单可复用同一数据提供者，但授权证据没有自动补全生产接口。

候选值使用 NUL 分隔，只输出经 schema 校验的 ID，不包含地址、路径值、密钥或显示正文；zsh 按值处理，不 `eval` 输出。查询不写缓存或日志；失败返回非零和空候选，由补全前端静默回退。读取机器文档仅提取所需元数据，不解析 SecretRef 或打开独立秘密/原生认证文件。没有会话索引时返回空候选；手动途径由正常 resume 交互页说明，补全本身不弹提示，也不能为了补全扫描会话正文。

## 7. zsh 接入、checkout 绑定和恢复

### 7.1 受管文件

建议在所选 term machine 的保存 target HOME 下增加以下普通文件：

| 目标 | 内容 | 模式 |
| --- | --- | --- |
| `.local/bin/rotom` | 只负责安全读取绑定、定位 checkout 并按 argv 调用仓库入口的静态启动器 | `0700` |
| `.local/share/rotom/entry.json` | 严格版本化的非秘密 checkout 绑定，内容由本机生成 | `0600` |
| `.local/share/rotom/zsh/site-functions/_rotom` | 来自公开来源的静态 zsh 补全 | `0644` |

这些目标相对保存的 target HOME，符合当前 catalog 模型；不会把 `$XDG_CONFIG_HOME` 插值当作 HOME-relative 路径。入口偏好文件仍按第 4 节跟随调用时的有效 XDG 配置目录。此处固定 HOME 下的入口/补全路径是显式约定，并在 help 中说明。

受管 `.zshrc` 复用已有 `.local/bin` PATH 逻辑，在所有 compinit 分支之前添加补全目录，避免重复。现有 shell 需重新打开或由用户主动加载配置；apply 不自动重启、source 当前 shell 或重启 tmux/Herdr。shell 启动时只配置 PATH/fpath，不运行 Rotom、检查部署、安装依赖或联网。

静态启动器从自身部署位置定位固定的绑定文件，而不是由调用者 cwd 寻找仓库。验证普通文件、所有者、权限、路径、schema 和允许字段；只调用绑定 checkout 的固定 `rotom` 入口，使用其 `.venv`，保留 cwd、argv、环境契约、终端、信号和退出状态。绑定文件不接受任意 shell 文本或自由 executable 字段。

仓库缺失、绑定损坏、权限不安全或 `.venv` 缺失都明确失败并提示修复；不扫描其它 worktree、不联网、不自动选择 `main` 或新候选。绑定固定 checkout 位置，允许该 checkout 后续正常更新，不将一次绑定声称为代码内容永远固定。

### 7.2 绑定选择与计划

增加 `term plan/apply --entry-repo PATH`，仅适用于包含 zsh 的目标范围：

```sh
./rotom term --machine workstation plan --component zsh --entry-repo /path/to/rotom
./rotom term --machine workstation apply --component zsh --entry-repo /path/to/rotom --plan-id PLAN_ID
```

第一次安装、尚无受管绑定时，未给 `--entry-repo` 可提议当前执行的 checkout，但必须在预览中显示目标和绑定位置，并由既有 apply 规则确认。已有受管绑定时，未给参数保持原绑定；从另一个 worktree 执行命令不会自动重定向。绑定记录丢失、变化或损坏按漂移/错误处理，不能退回“首次安装”。

显式更换绑定、仓库搬迁或回滚入口前，先盘点日常启动器。遵循 [worktree 约定](../../docs/worktrees.md)：用两套 checkout 的公开 schema 校验完整机器配置，保持秘密引用未解析，不启动宿主或改变部署。已存在的日常 `dsh` 等入口不被本变更自动接管。

同名 `.local/bin/rotom` 和其它新增目标走原有未受管文件分类、冲突与接管检查；拒绝任意符号链接、漂移和不安全祖先。PATH 上其它同名程序以及用户 alias/function 不等于当前文件已归 Rotom 所有。doctor 可以解释实际能验证的文件与 PATH，不声称从子进程证明当前交互 shell 的 alias 或加载状态。

### 7.3 新生成产物的正确性要求

现有 catalog 只能读固定仓库文件。实现应只新增一种受限的 checkout 绑定产物，不引入任意模板或 shell 生成机制。

1. 计划绑定静态模板/启动器摘要、规范 checkout 身份、生成绑定的精确字节摘要、目标路径、mode、写前 identity，以及 term machine/state/lock 的既有快照。
2. apply 在锁内复核输入和完整计划；checkout、生成内容、目标或 machine 发生变化时旧 plan ID 失效，不在写入时临时重新选择。
3. journal 的 `desired` 对应实际生成字节，保留现有 before/intended_after/after 阶段。生成产物的读取、admit-existing 分类和漂移判断都使用正确的内容摘要，不能继续假设所有内容都来自公开固定 catalog。
4. 恢复与回滚只依赖已记录的事务、备份、精确内容和身份，不依赖当前 cwd 或重新生成的当前 checkout。旧静态目标和既有 journal 仍可按原契约恢复；若必须升级 schema，提供严格版本分支和兼容测试，未知版本拒绝。
5. 多文件操作沿用逐文件原子写入与恢复，不宣称整组原子。先写兼容的静态启动器/补全，绑定文件作为最后一个目标激活。绑定采用最小 schema，兼容版本内的新旧启动器读取同一格式；中断后只允许看到完整旧绑定或完整新绑定。首次安装的中间态可能尚无可用入口；更换绑定后即使 state/journal 尚未收尾，新位置也可能已生效，结果必须报告部分效果，不能声称失败等于仍在旧 checkout。启动器或绑定不匹配时明确拒绝，不启动猜测目标。
6. 缺少权限、恢复待处理或目标漂移时停下，不借入口安装放宽 termcfg 的私有路径、备份、活动状态或恢复检查。

`term status/doctor` 增加已部署入口、保存绑定、文件完整性和静态补全的事实报告。默认不启动绑定程序来“自测”，不读取 Agent 账号，也不证明当前 shell 已加载补全。

### 7.4 首次安装与日常入口衔接

以下为拟议用户旅程，不增加另一套安装向导。`workstation` 是示例名称，term 与 agent 仍各自维护配置：

| 步骤 | 从仓库调用的示例 | 结果与下一步 |
| --- | --- | --- |
| 准备运行环境 | `uv sync --locked`，再 `./rotom --help` | 安装前提与业务初始化分开；help 不选择机器 |
| 登记终端范围 | `./rotom term init-local --machine workstation --component zsh` | 只保存 term 选择，不部署 |
| 预览入口和 shell 变更 | `./rotom term --machine workstation plan --component zsh --entry-repo /path/to/rotom` | 展示接管、绑定和完整作用范围 |
| 审阅后部署 | `./rotom term --machine workstation apply --component zsh --entry-repo /path/to/rotom` | TTY 走原有确认；不省略额外接管和 zshenv 确认 |
| 登记 Agent 范围 | `./rotom agent init-local --machine workstation --profile dsh-default` | 只准备该范围的字段；模型填写按既有流程 |
| 保存入口偏好 | `./rotom config set defaults.agent_machine workstation`，对应设置 `defaults.term_machine` | 名称可相同，仍分别验证，不自动配置 work |
| 准备并启动 | `./rotom agent --machine workstation --profile dsh-default setup`，再 `./rotom run dsh` | 部署与运行分开，缺模型 key 的既有边界不改变 |

在新打开的受管 zsh 中验证 `rotom --help` 和 Tab 补全后，日常再使用无路径的 `rotom`。安装定位损坏时仍可从原 checkout 用 `./rotom` 或兼容入口诊断修复；不要求一个尚未安装的命令先完成自身安装。项目工作区为后续显式选择，不纳入基本启动的前提。

## 8. 内部接口与工作区联动边界

建议新增仓库自有入口与小型 `src/rotom/` 门面，负责命令注册、交互策略、偏好选择和调用上下文。`agentcfg`、`termcfg` 保留业务所有权；不用新的通用事务框架替换它们。

调用上下文至少记录合法命令路径、调用前缀、显式字段集合、交互策略、解析后的目标和结果格式。它用于范围提示、合法选择和输入门控，不能携带秘密值或替代实际操作的锁、快照、runtime receipt 和准入检查。

保持三个共享执行契约：一次受管运行继续由现有 runtime 负责；日常 resume 与维护 restore 共用会话解析/恢复路径；普通实例 stop 与维护 stop 共用精确目标计划/停止路径。维护层仅编排已声明步骤和记录部分结果，不复制一套启动、停止或会话数据库。

`rotom work` 保留当前 CLI、保存的项目/type 实例绑定、cwd、runtime receipt、超时和能力拒绝。现有已绑定实例不能因为入口偏好变化而切换 profile 或 executable；普通 focus 不重建 binding。旧 binding 继续可执行，采用新绑定必须走原有 rebind 流程。

新建工作区的 Pi/DSH 仍优先使用工作区配置中明确的 machine/profile；根 `run_profiles` 不覆盖它们。允许共享“校验明确工具与 profile 后交给 agentcfg”的纯解析函数，但不能把工作区创建改成再次猜测默认值的 `rotom run TOOL`。

后续若加入 OMP 工作区 launcher，需单独扩展 schema、WorkSettings、launcher、receipt 和操作时限，核对完整机器配置兼容及旧状态读取，不能只加菜单项。该工作不改变 Herdr 当前不支持原子 workspace close 和既有分支创建的能力拒绝。

## 9. 退出码与取消

| 退出码 | 管理器含义 |
| --- | --- |
| 0 | 成功、help 或允许的非阻塞提示 |
| 2 | 缺少参数/必要交互、无效选择、配置或锁校验错误 |
| 3 | 实际操作所需凭据缺失 |
| 4 | 所有权、漂移、活动实例、恢复或状态变化冲突 |
| 5 | 缺必要运行包、依赖或原生能力不足 |
| 6 | 文件系统或内部操作失败 |
| 130 | 新门面在尚未提交的交互中取消 |

已经分发到原生进程后保留真实退出码和既有信号归一化；不能把宿主的非零退出码强行映射到管理器表。已经开始的既有 work/部署动作继续按自己的结果、取消与恢复契约报告。

## 10. 分阶段实施与验收

### 第一阶段：本次交付范围

| 顺序 | 工作包 | 验收重点 |
| --- | --- | --- |
| A | 命令注册、门面、作用域和调用前缀 | 新旧入口差异明确，完整参数正确分发，原生尾部不被捕获 |
| B | 私人偏好与根 run，静态 resume 命令/help | 三工具短启动、显式优先、失效偏好失败、管理默认不混用；目标明确但未准入的 resume 返回 5，缺参仍按规则返回 2，不计为 R8 已完成 |
| C | 各级导航、缺参选择与输入门控 | 编号兜底、取消、非 TTY、no-input 覆盖所有输入位置 |
| D | 各层 help、错误引导、菜单说明和补全 | 无私人读取/副作用，元数据一致，示例和参数位置正确 |
| E | 受管 zsh 启动器、绑定生成与恢复 | 计划失效、接管、漂移、中断、回滚和旧 journal 兼容 |
| F | 文档更新与稳定差异审阅 | Getting started、operations、termcfg、工作区和中英文入口内容一致 |

A 到 D 可先在独立 worktree 完成离线验证。E 涉及新的生成产物，须由主代理审查计划、日志顺序与恢复语义；存在不明前提时先调整设计。未通过 E 的恢复测试前，不把日常启动器切到候选 checkout。第一阶段验收的是 R1–R6 的入口体验；不能据此宣称 R7/R8 完成。

### 第二阶段：DSH 日常会话身份与实际恢复

完成 DSH 的最小可靠登记/索引、确认过的 session ID 展示与复制、TTY 选择，以及当前终端中的确切会话恢复。该阶段至少证明作用域、原生 HOME、cwd、writer 排他及加载结果，才可计作 DSH 的 R8 已交付。只读字段按 backend 分别降级，不因 Pi/OMP 暂缺字段而隐藏已验证的 DSH 能力。

命令和菜单按“未支持 / 可观察 / 已准入恢复”等事实说明能力；源码可行或仅离线模拟不等于原生验收。这里的能力记录只复用当前支持/来源证据并关联所选版本，不新建宿主插件市场或通用能力平台。

### 后续阶段与依赖

| 交付结果 | 前置条件 |
| --- | --- |
| 普通停止与维护页承诺可恢复 | 该工具的最小登记、退出证明及第二阶段的确切恢复证据 |
| 原 pane 恢复 | 前项加显式驻留契约/公开重启能力及现有实例采用路径 |
| 批量维护编排 | 停止与恢复路径、部分结果、准入意图、计划重审和取消均可验证 |
| 自动继续 | 正确会话、可输入状态、批准和发送结果证明；独立于普通恢复交付 |

OMP 工作区 type 与现有 launcher 切换单独评估。额外短别名、更复杂 TUI、全机状态汇总和自动化向导不作为首阶段完成条件。自动继续可以长期保持未开放，不阻塞日常 resume 与手动继续。

### 验证矩阵

所有默认测试只使用仓库与临时 HOME/XDG、虚构配置、阻断网络、文件哨兵与假子进程，不启动 DSH/Pi/OMP/Codex、Herdr、zsh 或其它第三方宿主。

| 路径 | 必须证明的结果 |
| --- | --- |
| 无业务配置的每一级 help；不存在/无效 HOME/XDG | 仓库入口的业务 help 无私人读取或副作用；安装启动器只允许读取其绑定，损坏时独立报告修复诊断 |
| `rotom run` 的 TTY、非 TTY、重定向和 no-input | 选择只在规定终端条件发生；缺参退出 2，取消 130，零当前动作写入/启动 |
| 三工具、Pi Base/Pro、显式 profile/local/machine、失效默认 | 目标确定且不混用作用域；无自动修复、扫描或持久默认变化 |
| resume 的缺参、ID 冲突、scope 归属、活跃 writer 与不支持的工具 | 会话不被默认 profile 改绑；不冷启动替代恢复，不额外发送继续，未知结果单独报告 |
| 原生 `--` 尾部与 `agent usage` 全部尾部 | token 原样到达既有边界，help 和门面 flags 不截获原生参数 |
| model、term、work 的缺参和确认路径 | 合法选项、隐藏输入、既有批准、no-input 和取消都覆盖；不泄露秘密 |
| 完整参数但没有等价非交互确认路径 | no-input 在任何输入读取前返回 2，不自动确认、不扩大授权 |
| `run` 已有完整目标但未部署或缺运行包 | no-input/非 TTY 保留失败结果和静态建议，零后续菜单、setup 或启动 |
| 无机器配置的 OMP lock 和公开目录命令 | 不因统一作用域解析而读取或要求 machine/profile/SecretStore |
| work 的递归/链式调度；无 fzf 的选择与确认 | 上下文、前缀、scope 和 no-input 持续保留；编号前端不改变允许动作和候选身份 |
| JSON、菜单和错误输出 | stdout 维持原 schema/通道，菜单在 stderr，下一步保留范围 |
| PATH、fpath 和补全的静态内容 | 加载顺序与去重正确；动态候选使用假命令/假数据；无隐式运行或网络 |
| 内部补全查询的 kind、作用域、输出和失败 | 候选仅为允许的 ID，NUL 边界正确，未知查询拒绝，失败空输出且无私人值 |
| 首次安装、尚未安装的 PATH 与缺少另一类 machine | 可从 checkout 自举和修复；不依赖尚未部署的 rotom，不隐式初始化其它管理面 |
| 入口首次部署、接管、从另一 worktree 部署、仓库搬迁 | 绑定可审阅；未显式切换时保留原绑定；真实目标变化使旧计划失效 |
| 模拟每个写入阶段中断、恢复、回滚和旧状态读取 | 精确生成内容可验证；覆盖绑定已激活但 journal 未收尾的部分结果，保留漂移，不重新猜测恢复目标 |
| 原 work 受管绑定和能力拒绝 | 默认变化不改旧实例；focus 不重启，不新增越界执行 |
| 原入口和完整机器配置 | CLI/输出/路径兼容；两套 schema 不解析密钥地校验全部 overrides |

真实 zsh 补全加载、PTY 方向键、原生 Agent/Herdr 启动、账号和模型调用是独立显式验收。未经用户授权不执行；离线模拟通过不计为这些结果通过。

## 11. 任务记录与当前状态

| 状态 | 内容 |
| --- | --- |
| 已完成 | 创建独立工作树，核对基线，完成源码调查、核心设计与维护探索、独立审阅修订、差异复核及文档检查 |
| 进行中 | 无；后续功能实施和能力原型尚未开始 |
| 失败待决策 | 暂无；若生成产物的事务或恢复不变量无法满足，由主代理重新决策 |
| 环境不足未验证 | 本次文档工作暂无环境阻塞；实现测试尚无对象，真实验收尚未授权/执行，均不计为通过 |

本次只交付设计与审阅记录。没有功能实现、生产部署、入口切换、上游修改、提交或合并。后续实施的实际 argv、源码/锁身份、退出码、失败和环境限制需另行记录，不能复用历史验收结论。
