# OMP CLI 与公共配置契约

> 验收归属以[范围修订](../scope-change-20260924.md)为准：当前保留软件隔离契约与 Linux x64 无账号原生验收；其他平台实机和真实登录/usage/模型调用转独立遗留。原有产品接口、平台选择实现与安全边界保持要求，转出不等于验证通过。

以下接口均待实现。保留现有 `./agentcfg` 全局参数位置和退出码，不引入另一套配置管理入口。

## 生命周期命令

```text
./agentcfg [--local PATH | --machine ID] --profile ID validate|render|plan|apply|doctor|capture|rollback
./agentcfg [--local PATH | --machine ID] --profile ID sync
./agentcfg lock --agent omp
./agentcfg [--local PATH | --machine ID] --profile ID run omp [--cwd PATH] [-- NATIVE_ARGS...]
./agentcfg [--local PATH | --machine ID] --profile ID inventory omp --source ABS_PATH
```

具体既有 lock/recovery/capture 选项继续由现有 parser 定义，不重命名。由 profile.agent=omp 选择适配器。validate/render/plan/apply/默认 doctor 均离线且不启动宿主；render 仅生成非秘密产物；plan 显示身份、来源、目标及差异。lock 显式解析依赖，sync 显式准备，apply 显式部署，run 只运行已部署的匹配依赖。doctor 不自动执行 `omp --version` 或账号查询。

新增 inventory 只读取指定来源的允许字段与资源，不递归归档 HOME。输出私人 cache 中的 `disposition.json`、`local-overrides.toml`、`resources/` 候选包；认证值仅标为未导入。标记无法自动确认的文本/脚本为 review-required，不声称任意源文件一定无 secret。用户审阅后手工合并允许提案、复制批准资源并声明，然后 validate/render/plan/apply。来源、新实例以外数据保持原样；首次 apply 非空未归属目标失败4。capture 沿用已有命令，仅提案 theme、keybindings 和可唯一反查的 modelRoles。

## 公共配置

使用 `agents/omp/{agent,bindings,plugins,content}.toml`、`profiles/omp-default.toml`、既有 registry 与 local 覆盖机制。agent.toml 提供 defaults 与 resources catalog，bindings.toml 声明公共引用转换；未知字段通过严格 schema 拒绝。以下是新增 OMP agent_options 的完整首版用户配置范围：

```toml
[agent_options.resources]
prompts = ["rotom-review"]
themes = ["rotom-dark"]

[agent_options.ui]
theme_dark = "rotom-dark"
theme_light = "rotom-dark"

[agent_options.ui.keybindings]
"app.model.cycleForward" = "Ctrl+P"
"app.history.search" = []

[agent_options.discovery]
project_resources = false
project_roots = []

[agent_options.mcp.echo.environment_refs]
SERVICE_TOKEN = "echo-token"
```

environment_refs 只在已选 MCP 上有效；secret ref 必须存在于运行时 SecretStore，validate 不要求实际值。project_roots 是机器相关绝对路径，应在 local 覆盖，不写入公共默认；启用 project_resources 时必须非空且符合固定来源检查。未选的 prompts/themes/plugins/MCP 引用失败2。原生角色、provider 协议和具体文件映射见 [能力契约](native-capabilities.md)。

不给用户提供 native profile 名、任意 HOME/XDG、原生 settings 路径或 raw-native 表。身份算法和所有权见 [数据模型](../data-model.md)。`plan`/`doctor` 非秘密报告配方 ID、native name、实际路径、原生默认快捷键继承路径、来源政策和账号/会话作用域，不读取账号明细。

## 受管运行与显式登录

普通启动 argv 基础为 `<locked-omp> --profile NAME`，随后附加受管启动参数 `--no-title` 与经校验的 native args。操作类型先分类：普通会话、`--help`/`--version` 信息操作、`login [provider]`；登录/信息操作不附加会话专用参数。

```sh
./agentcfg --local "$OMP_LOCAL" --profile omp-default run omp --cwd "$OMP_WORKSPACE"
./agentcfg --local "$OMP_LOCAL" --profile omp-default run omp -- login openai-codex
```

login 使用同一锁定二进制、identity、归属和环境守卫，允许建立自己的原生认证。bootstrap profile 未选静态模型时允许登录；不因无模型而借用其他 profile 或自动登录。login 不解析无关 provider/MCP secrets。首次订阅映射支持 openai-codex，其他 provider login 仅在能力表明确登记后开放；本版不能假定所有原生 provider 都已纳管。

参数验证按固定版本 CLI grammar 解析，拒绝重复/等号形式/别名绕过。拒绝覆盖身份与来源的 `--profile`、`--alias`、`--config`、`--session-dir`、`--extension`/`-e`、`--hook`、`--plugin-dir` 以及绕过 manager 的 cwd 控制；禁止直接传 secret 与 auth broker 控制。模型选择参数仅可选已声明精确模型；bootstrap 的原生交互登录和目录选择单独验证。不开放 update/install/plugin/config/token/auth-broker 子命令。原生 `--` 后的普通提示文本不得被误判成管理器选项；采用 token-aware parser 而非字符串包含检查。所有禁止项均在 spawn 前返回2。

实施源码复核补充：`--trusted-extension` 同样会载入额外代码；`--add-dir`、`--from-claude`、`--from-codex` 及 `--continue`/`-c`、`--resume`/`-r`、`--session`、`--fork` 可能在管理器检查之后重新选择来源或 cwd，首版受管入口明确拒绝。原生会话文件保留原位；该限制不表示删除会话，也不扩展为对会话内用户主动操作的沙箱保证。依据固定源码 `cli/flag-tables.ts` 与 `main.ts` 的 `resumedProject.cwd` 分支。

## Usage 两种模式

| 条件 | 行为 |
|---|---|
| 没有显式 `--profile`，也没有 --local/--machine | 原生模式；不装载 workspace/local/secrets；PATH 查 omp，argv=`omp usage <tail>`；继承调用者 cwd/env |
| 显式 `--profile ID` | 受管模式；载入 OMP 配方，经过 runtime gate；argv=`<locked-omp> --profile NAME usage <tail>`；neutral cwd=实例 HOME |
| 只有 --local/--machine，无显式 --profile | 返回2，说明需显式选择；不猜测默认配方 |
| 显式 profile 指向 DSH/Pi | 返回2；不自动改选 OMP |

```sh
./agentcfg usage --json
./agentcfg usage -- --provider openai-codex --json
./agentcfg --local "$OMP_LOCAL" --profile omp-default usage -- --json
```

命令后的 tail 原样传给原生；只剥离一个可选前导 `--` 分隔符，管理器全局选项仅在 usage 前解析。受管 tail 禁止改变身份/来源的参数，其他查询参数和 invalidate/clients 等原生 usage 操作保留；无自创 provider 重命名或结果解释。原生模式遵循原生 profile 参数放置语义，选名环境可用 OMP_PROFILE；不把 `usage --profile` 改写成全局 profile 参数。

两种模式直接继承子进程 stdout/stderr，不缓存重绘、不在机器输出前后加说明；已启动子进程退出码原样保留，信号退出沿既有128+signal 约定。无账号/不支持/部分失败/窗口/缓存/缺失信息由原生定义，缺失不是零。受管只注入该操作必要的非秘密身份环境和原生已存认证；不解析无关 MCP/provider secret。查询允许原生网络/缓存/认证刷新，不安装、部署或自动交互登录，不执行模型生成。

受管 usage 与 run 默认互斥，持有同一实例 lease；活动实例返回4。native usage 不获取 rotom 锁、不写管理器状态、不跨 profile 聚合。原生上下文可能有上游自有认证共享行为，薄封装不伪称隔离；受管模式禁用 broker/网关共享认证以保证独立身份。

## 退出码与消息

管理器启动前：0成功（可提示待登录）、2参数/配置/锁校验、3实际所需凭据缺失、4归属/活动/恢复/保护边界冲突、5缺依赖/原生检查失败/不支持平台、6文件系统/内部失败。权限访问失败为6，已识别的归属/越界目标为4。消息给出操作和非秘密路径/引用，不能包含秘密值。运行后的任何原生退出码以原生为准。
