## Context

rotom 当前只有仓库说明、许可证和已初始化的 OpenSpec，没有管理器实现。设计输入为用户提供的 2026-09-11《Agent Config：个人 Agent 配置仓库方案》及实施 Prompt，以及随后确认的独立实例、仅保留上一版备份、多工具扩展与维护 skill 要求。本文将这些要求落成实现决策；具体行为见本 change 的八份 capability specs。

后续讨论优先于初稿：`rollback --to GENERATION` 改为 `rollback`，只恢复上一版受管配置；不维护面向用户的任意历史回滚。generation 仍用于确定性标识、部署关系和恢复检查，不代表无限保留历史文件。

本次提案未调查或安装 DSH、TUI、认证插件、OpenSpec，也未进行模型调用。输入文档中的 Cordis patch、认证入口、偏好路径等原生行为均须针对选定提交复核。仓库中已有的 OpenSpec 开发技能及本机 CLI 不等于产品依赖已经锁定。

## Goals / Non-Goals

**Goals:**

- 通过 `./agentcfg` 管理公共配置来源、机器覆盖、原生转换、完整依赖、部署与启动，支持 macOS 和 Linux SSH/tmux。
- 首版真实支持 DSH + `ccch1mneyyy/dsh-TUI`，包括 Codex 订阅认证、Cursor 社区 provider、API provider 和显式 OpenSpec 项目集成。
- 安全保留原生运行数据、用户界面改动及未知字段；失败可恢复，上一版备份容易使用。
- 为 Pi、Codex 等未来适配器复用配置、秘密隔离、文件事务、备份与命令基础设施。
- 提供实际维护 skill、隔离测试、平台 CI 和分层验收证据。

**Non-Goals:**

- 不实现新的 Agent 内核、模型代理、通用调度器、OAuth 云同步或外部密钥系统。
- 不在首版实现 Pi/Codex 适配器，不声称统一各 Agent 内置系统提示、权限语义或模型能力。
- 不默认接管既有 Agent 配置、扫描业务仓库、建立全仓库 Serena/clangd 索引或放开全部权限。
- 不安装 Superpowers，包括通过其他套件间接安装；不默认启用所有可选插件或 MCP。
- 配置回滚不保证软件降级、插件数据库迁移逆转或账号与会话恢复。

## Decisions

### 1. 名称、实现和目录职责

项目名沿用 `rotom`，命令使用用户给出的 `agentcfg`；避免为暂名重命名远程仓库。Python 3.11+、argparse、tomllib、PyYAML、jsonschema、Jinja2；pytest 为测试依赖。提交 `pyproject.toml` 与真实 `uv.lock`，入口直接执行仓库 `.venv` Python，缺失时提示 `uv sync --locked`。不以普通 `uv run` 包装离线命令。

实施时采用 uv 的非打包项目模式（`tool.uv.package=false`），入口明确加载仓库 `src`。本产品通过 Git 仓库分发，不需要构建 wheel；这样 `uv sync --locked` 不会另外解析 uv.lock 之外的 Hatchling/PEP 517 构建依赖。默认测试同样通过项目 pythonpath 加载源码。

公共模块负责 loader/schema/merge/provenance、secret resolver、render plan、路径边界、事务与状态、环境构造和 CLI。DSH 模块负责原生字段、序列化边界、依赖准备、启动参数和原生诊断。采用小模块而不是单个大型脚本；依赖成熟序列化器而不是自建 TOML/YAML 解析器。

目录按原设计落实：`shared/{rules,skills}`、公共 registry TOML、`profiles/`、`agents/dsh/{agent.toml,bindings.toml,plugins.toml,templates/}`、`locks/dsh/`、`examples/local.example.toml`、`schemas/`、`src/agentcfg/`、`tests/`、`docs/`。DSH 专属 rules/skills 有实际内容才创建。根 `AGENTS.md` 说明仓库开发约定；不把它当成分发给所有 Agent 的规则。

### 2. 配置解析与私有值隔离

合并顺序：公共 registry 与工具默认值 → profile → 本地 overrides → schema 明确允许的本次参数。profile 选择实体，不自动启用全部 registry。对象递归、标量覆盖、数组整体替换；空数组和 false 保持意义。稳定 ID、重复定义、未知字段、引用、适配能力和认证拥有者均显式校验。

本地文件为 `$XDG_CONFIG_HOME/agentcfg/machines/<machine>.toml`，默认 XDG 回落到 `~/.config`。包含 `[machine]`、`[overrides.providers.*]`、`[overrides.models.*]`、`[overrides.profiles.*]`、`[secrets]`。`--machine` 与 `--local` 互斥；无选择器时使用 `default` 机器文件，缺文件明确提示初始化，不扫描或猜测其他文件。profile 优先级为显式参数、本地 default_profile、`dsh-default`。`init-local --machine NAME` 与其他命令前置公共参数是唯一有文档的特殊语法。

解析本地 TOML 必然会接触 secrets 区，因此立即将秘密值隔离在 resolver 中，不进入普通配置对象、来源树、摘要或异常上下文。离线命令允许缺失/空凭据，不做有效性请求。只有需要凭据的实际运行操作才解析引用并注入；不把 secret 值当作模板变量。

缺失是内部独立状态，不与空值、false 或空数组混用。覆盖表中省略字段意味着继承；profile 空选择数组意味着清空。registry 删除仍被引用的实体报错。取消选择实体会产生受管字段/文件删除计划；只有 manifest 证明所有权且目标符合三方合并条件时才删除。首版不引入任意 TOML 删除表达式。

本地来源字段默认视为私有，来源显示“本地覆盖”和字段路径，不展示 endpoint/model ID 等值。私人渲染产物允许包含这些必要值；公开 plan、日志和错误只显示脱敏变更。生成编号只使用规范化的非秘密渲染输入、锁身份、机器路径及适配器版本，不使用 secret 内容。

### 2a. 本地文件格式作为公开契约

本地文件承载大量机器差异，必须有专用 schema 和字段说明，不能用一个不校验的 extras 表容纳所有设置。它是一份框架 TOML，不是 DSH/Pi/Codex 原生文件；未知字段失败，未来增加合法字段通过 schema 版本与适配器 schema 演进。

首版框架结构如下，字段名为本框架拟实现接口；所有示例地址与模型均为虚构，不可作为真实配方：

```toml
schema_version = 1

[machine]
id = "workstation"
default_profile = "dsh-default"
editor = "nvim"

# 以下三项均可省略，默认遵循 XDG。
[machine.paths]
instances_root = "~/agentcfg-private/instances"
state_root = "~/agentcfg-private/state"
cache_root = "~/agentcfg-private/cache"

[machine.environment]
inherit = []

# 仅允许非秘密的字面值；不做 shell 或环境变量展开。
[machine.environment.values]
LANG = "zh_CN.UTF-8"

[overrides.providers.private_gateway]
protocol = "openai-compatible"
base_url = "https://gateway.example.invalid/v1"
auth_kind = "api-key"
credential_ref = "secret:private_gateway_key"

[overrides.models.private_main]
provider = "private_gateway"
remote_id = "example-private-chat"
input = ["text"]

[overrides.profiles.dsh-default]
providers = ["private_gateway"]
models = ["private_main"]
mcp = []

[overrides.profiles.dsh-default.roles]
main = "private_main"

[overrides.profiles.dsh-default.agent_options]
terminal_images = false

[secrets]
private_gateway_key = ""
```

字段分工：`machine` 仅保存机器身份、默认选择和 editor；`machine.paths` 控制管理器实例/状态/缓存根；`machine.environment` 控制明确允许的非秘密环境输入；registry 实体差异进入 `overrides.providers/models`；模型选择、规则/技能/插件/MCP 选择和工具参数进入 `overrides.profiles.<id>`。工具参数依据该 profile 所属 adapter 的 schema 校验，不把原生键任意塞进通用层。不覆盖 profile 的 agent 身份；切换工具建立独立 profile。

本地 override 可引用仓库中所有已存在 profile，并分别校验；首版不以本地覆盖偷偷创建缺少基线的 profile。用户可以在同一文件维护多个已声明的工具/profile，启用哪一个由命令选择；禁用或取消选择的内容不因此自动安装或运行。补充明确定义的 `[overrides.mcp.<id>]`，复用 MCP registry schema，允许本机私有 URL、命令/参数和凭据引用的新增与覆盖；默认仍不选中服务，并接受相同的运行时凭据限制。

路径字段允许绝对路径或开头的 `~/`；`~` 只按当前进程 HOME 展开一次，拒绝相对路径、其他用户的 `~user`、环境变量插值和命令替换。空格、中文按字面处理。默认值只在字段缺失时使用，不能把空字符串视为“使用默认”；空字符串是否有效逐字段定义。路径迁移不自动搬运原生登录/会话；检测已有实例绑定变化并说明新旧位置。

环境名遵循合法变量名格式，基础允许清单之外必须逐项声明。`values` 是明确的字符串表，声明任意变量名的能力不等于继承全部环境；框架拥有的 DSH_HOME、实例隔离 XDG/HOME、凭据目标变量等保留名称不得被覆盖。凭据值不允许放在 values 或含凭据 URL 中，认证通过 `secret:`；非法输入错误只打印字段路径与原因，不打印原值。editor 是单个可执行名称/路径，不是可 eval 的 shell 命令。

提供最小可用例子和多个本机场景说明（XDG 默认、Linux SSH/tmux、macOS、自定义磁盘路径、私有网关、多个 profile、空数组/false）；这些例子必须用同一 schema 和离线校验流程测试。未来 schema 升级不静默重写已有文件，应给出显式迁移说明和提案。

维护 skill 必须按字段说明编写本地文件：先定位用户选择的文件，避免输出 secrets，仅修改任务涉及的表，保留其他 profile、注释和秘密区域。修改前后执行安全解析/校验；无安全的 TOML 局部修改办法时输出局部补丁提案而不全量重写。`init-local` 仍不覆盖已有文件，离线命令不擅自修复格式。

### 3. 原生渲染与完整技能

规则按选择顺序保留原文；仅明确声明为模板的文本使用 Jinja2 StrictUndefined。JSON/YAML 使用序列化器。完整技能包复制资源与执行位，不执行脚本；shared/agent 同 ID 必须有显式覆盖声明。提供实际可用的 `repo-navigation` 技能，包含局部检索、大型 C++ 仓库与按需索引指导，并记录来源和定制。

DSH adapter 为每个产物声明目标、所有权、受管字段选择器和序列化方式。若锁定 Cordis 版本按 ID 替换完整 config，先读取允许结构并保留不受管内容，合成完整一行，再序列化；不把半段配置作为深合并 patch。安全 loader 只允许适配器白名单的 `!!js` 原样标记，不执行 JS；未知标签报错，解析错误不回显配置片段。

确定性 render 只生成来源决定的独占文件、新实例基线和受管字段意图，不将当前运行时文件混入 generation 输入。共享文件的最终完整行在 plan 中模拟、apply 持锁并写前复查时合成；它保留的运行时字段不进入渲染缓存或部署快照。因此原生完整行替换与离线确定性生成可以同时满足。

### 4. 实例、路径与配置来源绑定

默认实例位于 `$XDG_DATA_HOME/agentcfg/instances/<agent>/<profile>/`；DSH 内的 `dsh-home/` 固定，运行包目录可变化。状态位于 `$XDG_STATE_HOME/agentcfg/`，缓存位于 `$XDG_CACHE_HOME/agentcfg/`。实例级状态、锁和备份互相独立；不同工具使用同名 profile 不共享运行数据。

首次部署将实例绑定到机器标识和规范化本地配置路径。不同本地配置企图写同一实例时拒绝，提示使用不同 profile 或显式不同实例根；不自动共享登录。路径配置允许迁移实例根，但不得绕过目标归属校验。机器 ID、profile ID 和产物相对路径拒绝绝对路径和 `..` 逃逸。

敏感目录 0700，配置/状态/备份 0600；技能脚本保留必要执行位。检查实例根、父目录和每个文件，避免符号链接穿透；写入和删除时重新校验，尽可能使用目录句柄及 no-follow 操作。拒绝源技能中的符号链接，以防复制仓库外数据。

2026-09-13 实施补充：显式可信的只读仓库源与私人部署目标使用不同入口。来源逐段 no-follow 固定句柄并检查仓库本身属主/不可被他人写入，允许位于共享挂载祖先下；部署目标继续严格检查祖先与私人目录权限。此来源信任不授予目标写入权限，不防御同用户修改可信源码。

### 5. 字段所有权与三方合并

所有权为整文件受管、字段受管、仅首次初始化、运行时拥有、包管理器拥有。初始化值与持续受管值分别记录；运行时与包管理器内容不进入普通渲染器的管理范围。首次部署遇到非空未接管同名受管文件报冲突；框架不能通过猜测内容来源接管文件。若原生安装器合法创建共享文件，必须由安装阶段显式记录其来源和渲染器可管理的字段边界。

令 B 为上次受管基线，C 为当前值，D 为期望值（均包含独立缺失状态）：

| 判断 | 行为 | 新基线 |
|---|---|---|
| C = D | 无需写入 | D |
| C = B | 写入 D，包括安全删除 | D |
| D = B 且 C ≠ B | 保留 C，报告漂移 | 保持 B |
| C、D 都改且不同 | 冲突，停止本次部署 | 保持 B |

未知字段和原生动态 OAuth provider 保留。基线与备份分开：基线用于识别谁改了字段，备份用于恢复上一次实际修改；不能用“新建 generation”把保留的漂移偷偷接纳为基线。

### 6. 单份上一版备份与失败恢复

选择一份上一版备份，符合个人维护的简单使用目标；放弃多代快照和任意历史回退。每个实例有 current manifest、previous 备份和仅操作期间存在的 pending journal。previous 只含此次受管变更需要的前值、所有权/基线与必要非秘密运行绑定，不复制整份共享 settings、原生 home、OAuth、会话或本地密钥文件。

共享文件的持久化摘要仅针对允许的非秘密受管投影；不对包含凭据的原生整文件制作内容摘要。若原生 credential 字段被改成明文，适配器必须将其识别为不允许捕获的状态并报脱敏冲突，不能先把它写入 previous/journal。文件身份、变化检测与重新读取用于保护共享文件写入，不以保存全部内容作为恢复手段。

部署流程：加实例锁 → 恢复/拒绝未完成操作 → 重新计划及预检查 → 写入私有 pending 前值与目标摘要 → 写前复查每个目标 → 单文件原子替换 → 提交 current 与 previous 的状态指针 → 清理 pending 和过期备份。状态指针使用原子写并定义 fsync 与恢复顺序；多文件不宣称整体原子。跨文件失败按 journal 恢复已写受管部分，遇到后续冲突保留记录并停止，不覆盖新变化。

成功且有实际部署变化才将本次前状态作为 previous；无变化不重写目标、不轮换备份。失败且恢复成功后 current 和旧 previous 不变；失败恢复受阻时不伪报已恢复。日志仅保留有限非秘密操作元数据，不变相保存历史内容副本。运行绑定发生有效变化也属于部署变更，即使文本相同。

`rollback` 只针对 previous，仍进行锁、路径、写前复查和三方冲突检查，仅恢复上次操作拥有并改变的内容。成功恢复后消费 previous，避免反复切换被误解为历史回滚；下一次成功 apply 再建立上一版备份。回滚失败不消费备份。首次部署前无配置时，恢复只删除该次新增且未漂移的受管对象，保留原生运行数据。相同字段发生后续冲突时要求用户处理，未受管变化始终保留。

### 7. 依赖、配置与启动的配对

`lock` 显式解析并提交完整实际包管理锁，包含传递依赖、包 integrity、完整 Git SHA、Node/包管理器版本、适配器版本和平台证据。版本约束/配方摘要用于判断锁过期。`sync` 只消费现有锁，在暂存运行目录验证后注册可用运行包；失败不切换当前可用包、不修改锁。

`apply` 离线记录配置 generation 所要求的 lock identity 和启动契约，允许依赖尚未安装，doctor 显示“配置已部署，依赖未准备”。`run` 按已部署契约选择匹配的运行包；缺包提示 sync，不能使用新旧任意版本混配，不能根据尚未 apply 的配置重新解释 provider 选择。

启动契约保存所需非秘密凭据引用/环境映射，启动时从绑定本地文件解析当前值。同一引用的 key 轮换无需 apply；provider、endpoint 或 credential_ref 变化必须 apply 后生效。依赖回退不属于配置 rollback 承诺；旧包缺失或有已知数据库迁移不兼容时明确报告，不能自动降级或声称实例可运行。

`run` 持有实例活动锁直至子进程结束；apply/sync/rollback 与活动实例互斥，不杀进程。外部绕过管理器的宿主无法可靠识别，doctor 和文档说明检测边界，写前复查仍执行。首版不做跨实例全局事务或一键更新全部工具。

### 8. CLI、环境与脱敏捕获

公共选择参数位于子命令前：`./agentcfg [--machine NAME | --local PATH] [--profile ID] COMMAND`。`init-local --machine NAME` 保留原始易用形式，禁止重复冲突的选择器。实现 validate/render/plan/lock/sync/apply/run/doctor/capture/rollback/project，详细副作用见 CLI spec。`--` 后只传给原生进程，绝不作为字面参数。

退出码：0 成功（可有漂移/待登录提示）；2 参数或配置/锁校验错误；3 所需凭据缺失；4 所有权冲突、活动实例或恢复待处理；5 依赖/原生检查失败或缺必要运行包；6 文件系统/内部操作失败。run 正常启动后保留原生子进程退出码，信号按平台约定说明；错误始终不回显秘密。

子进程通过 argv 数组和显式 cwd 启动。基础环境仅允许存在的 PATH、HOME、USER、LOGNAME、SHELL、TERM、COLORTERM、LANG、LC_*、TZ、TMPDIR、TMP、TEMP、EDITOR、VISUAL、SSH_TTY、SSH_AUTH_SOCK、TMUX、TMUX_PANE 与 XDG 路径；具体变量逐项文档化。机器可以显式声明额外变量名称，不能通配继承父环境；带凭据的值只能通过 resolver，安装代理需求单独声明和脱敏。run 注入已部署能力所需的选定 secret；缺少强制凭据失败，可延迟认证的能力必须由适配器证据明确声明。

安装/项目 CLI 不接收模型密钥。HOME/XDG/DSH 专用变量如何组合以隔离原生写入须上游验证，不能仅设置 DSH_HOME 就认定所有偏好已隔离。基础环境不构成 OS 沙箱；DSH 内工具进程可能继承已注入密钥。

capture 只解析 allowlist 原生字段，终端显示脱敏提案；可用的私有覆盖值写入 0600 本地提案文件，绝不包含凭据、动态目录或全量 settings。用户审阅后再整理到本地覆盖或 Git。doctor 默认离线；live 才允许网络检查，OAuth 登录与模型付费调用另须明确授权。

### 9. DSH 配方与上游证据门槛

实施时先读取选定版本的上游文档和必要源码，输出 `docs/upstream-verification.md` 和 `locks/dsh/` 兼容性清单。调查入口包括 `https://github.com/ccch1mneyyy/dsh-TUI`、`https://github.com/xxww0098/dsh-plugin-oauth-subs`；host、配套 dsh-auth、OpenSpec 与可选 ModSearch 的权威地址由这些来源或各自官方项目确认。本文不填未经核实的版本、endpoint、model ID、配置键或端口。

调查覆盖 host/TUI 启动、包管理和 profile 写入、规则/技能加载、Cordis 替换、JS 标记、权限、MCP、credential env、外部偏好及插件服务。形成产物所有权表和最小无账号加载 smoke 后再冻结真实配方。

配方保持 standard preset 与原生任务/权限。提供受管低噪声 Poimandres 风格主题，关闭终端图片预览但不改变模型图片输入能力。Codex 优先配套 dsh-auth 的 openai-codex，Cursor 使用 oauth-subs 社区路线，均在 DSH 内注册；一个 provider 一个认证拥有者，已随包提供 auth/working-activity 不重复安装。OAuth 动态模型不要求虚构静态目录。

Cursor 服务、数据目录、profile、代理端口和认证入口以锁定版本证据为准；若需要 Web 辅助登录，用同一隔离实例串行启动。百炼/私有网关提供本地配置入口；qwen ID、medium/SSE/重试须核实后才给真实例子，不默认要求 DeepSeek 或混淆 Codex 订阅与 OpenAI API key。

MCP 默认空选择，stdio 是命令和参数数组；远端秘密只映射到已验证的运行时引用。原生不支持所需引用则该定义明确失败，不落明文。ModSearch 只有兼容 smoke 成功才默认启用；否则保留原生检索。Memento、ModLens、MCPLens 只登记可选用途，启用前另做核实。

### 10. OpenSpec 项目集成

产品的 OpenSpec CLI 使用精确锁定安装产物，不依赖用户全局 CLI。先核实原生工具列表；有 DSH 目标则验证原生流程，没有则采用上游文档支持的自定义集成。不能把“已安装”当成“项目已初始化”。

`project init openspec --path PATH` 只操作明确指定项目，使用临时 home 做集成测试；apply 不自动修改业务项目。初始化前检查既有文件，重复执行无变化或明确冲突，不自动覆盖用户修改。记录本次产物；无账号 smoke 证明 DSH 实际识别生成的指令/技能。初始化工具如不能可靠限定写入范围，必须先解决或明确阻塞该集成，不能伪报成功。

### 11. 扩展接口与维护技能

Adapter 契约为 validate、render、dependency_plan、managed_targets、launch_spec、capture、doctor，另提供锁解析/锁消费/原生配置读写等必要钩子。公共核心控制事务、备份、锁与秘密注入；适配器返回声明式目标和 argv，不直接绕过保护写文件。schema_version 与 adapter_version 分别管理数据结构与映射变化。

`agents/<id>/agent.toml` 声明真实能力及所有权，bindings 保留工具路由/原生字段，不把 DSH Cordis 语义塞入通用 registry。增加工具时先核实原生配置范围、认证拥有者、环境与备份边界，再复用契约测试。首版用测试适配器检验公共核心，无产品空适配器。

维护技能为 `shared/skills/maintain-agent-config/SKILL.md`，完整资源按需随包分发。共用正文包含任务分类、正确编辑位置、版本核实、validate/render/plan、授权范围和结果说明；长篇工具细节从仓库适配文档或技能 references 按需读取，不复制整本上游手册。技能须能定位管理仓库；不假设当前业务目录就是 rotom，命令参数保持用户选中的实例。

“生成配置”只生成并检查；“应用到本机”在已授权范围内调用 apply，依赖变化才运行 lock/sync；不重复请求已有授权，不自行扩大到安装、登录、发布或所有工具。原生 UI 变化走 capture 提案，不全量反向同步。技能不实现第二套备份/密钥逻辑，不直接修改运行中实例；活动锁冲突时清楚说明退出实例后重试。

## Risks / Trade-offs

- [第三方接口尚未核实] → 将事实调查作为第一阶段，逐项记录 SHA、源码位置和 smoke；不锁定猜测字段。
- [完整依赖可能经过原生安装器二次解析] → 记录写入所有权并比对实际依赖树；无法冻结则列出具体限制，不宣称完全复刻。
- [共享 YAML 含动态认证字段] → 安全解析、字段选择器、最小前值记录、异常脱敏；不保存整个文件的恢复副本。语义保留不保证 YAML 注释和原始排版保留。
- [多文件写入与外部进程竞态] → journal、原子单文件写、写前复查、冲突保留和恢复锁；声明外部宿主不受管理器活动锁约束，不声称消除所有跨进程竞态。
- [只有上一版，较早错误无法一键恢复] → 公共源用 Git 历史人工恢复后重新生成；私人配置和运行数据不属于历史快照服务。
- [上一版配置可能需要旧软件或旧数据库] → 保存依赖身份并诊断兼容性，不自动逆向迁移数据库，不将配置恢复描述为整环境恢复。
- [本地文件单份密钥与运行环境继承] → 0700/0600、按需解析、明确环境允许清单；说明它不是保护同一用户任意代码的沙箱。
- [无账号或缺 macOS 环境] → 分层记录离线、无账号宿主 smoke、授权 live 和逐平台证据；未执行不勾选成功。

## Migration Plan

1. 完成上游接口调查与版本候选验证，建立验收编号和所有权映射；此时只操作仓库和临时测试目录。
2. 实现虚构 fixture 驱动的配置核心和 render/plan，再实现三方合并、上一版备份与失败恢复。
3. 完成锁定安装、启动契约和 DSH/认证/OpenSpec 适配，补齐诊断、capture 与维护技能。
4. 在临时 HOME/XDG/DSH_HOME 下运行默认离线测试和单独无账号 smoke，提交实际锁与可运行文档；平台未实测如实记录。
5. 使用者 clone 后执行 `uv sync --locked`、`init-local`，手工填写本地非秘密覆盖与需要的密钥，再执行 validate/plan/sync/apply/doctor/run。首次构建不访问现有用户配置。
6. 下一次成功 apply 更新单份 previous；配置损坏时显式 rollback，保留运行数据。用户授权后单独完成 Codex/Cursor 登录和真实调用，不自动 push 或发布。

## Open Questions

这些是实施调查任务，不要求用户先提供账号或替实现者选原生字段：

- 选定 host/TUI/auth/oauth-subs/OpenSpec 的具体版本、包管理器、完整传递锁及 macOS/Linux 原生依赖兼容情况。
- DSH 原生安装器对 profile 的实际写入范围，settings/Cordis/JS、MCP 环境引用和技能加载的精确接口。
- Codex 与 Cursor 插件动态目录的拥有者、Cursor 辅助服务/端口/登录入口和无账号情况下可验证的边界。
- DSH_HOME 之外偏好的重定向方式与优先级；无法隔离时哪些字段只能诊断而不能托管。
- OpenSpec 原生或自定义 DSH 集成路径，以及 ModSearch 是否达到默认启用门槛。

需根据调查调整原生映射并留下原因，不能降低密钥隔离、备份、用户工作目录、权限或真实验收要求。未核实项不得用虚构值填满配方。
