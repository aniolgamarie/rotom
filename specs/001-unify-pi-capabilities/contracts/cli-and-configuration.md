# CLI 与配置契约

**Contract version**: 1  
**Status**: 待实现设计；现有 CLI 尚不接受本契约的 Pi 新入口。

## 1. 用户命令

公共选择器保持 `--machine NAME | --local PATH` 与可选 `--profile ID`，置于子命令之前。

| 命令 | 行为和结果 |
|---|---|
| `init-local --machine NAME` | 既有初始化；不覆盖，不隐式选择或部署 Pi |
| `validate` | 严格来源、引用、能力组合和完整锁校验；managed 必需绑定缺失返回 2 |
| `render` | 非秘密确定性产物，仅私人缓存 |
| `plan` | 三方差异、来源和冲突；无安装/原生执行 |
| `plan --from-pi-home PATH [--from-starter PATH]` | 新增只读盘点及迁移提案，PATH 必须显式提供；from-starter 不能单独使用 |
| `lock --agent pi` | 明确解析所有 Pi 配方所需的依赖图与平台归档，写锁；不得启动 Pi |
| `sync` | 消费选择配方对应锁切片，暂存安装/修复，激活前验证，不登录/启动 |
| `apply` | 重新计划、投影保护、活动检查、上一轮备份和部署，不安装 |
| `run pi --cwd PATH -- <native-args>` | 使用已部署契约与运行包启动实例；cwd 为业务项目，不是配置目录 |
| `doctor` / `doctor --live` | 离线配置/依赖/活动/匹配证据；live 仅声明服务可达性 |
| `capture` | 允许的主题与已声明主模型选择转成本地覆盖提案 |
| `rollback` | 仅恢复上一轮受管配置，消费备份，保留原生和任务运行数据 |
| `recover pi --lease ID` | 只读生成旧执行停止计划，不发信号 |
| `recover pi --lease ID --stop --expect-plan DIGEST` | 用户明确停止请求，仅对身份可证明且旧监督者已失效的执行发放停止恢复授权 |
| `project init openspec --path PATH` | 仅选中 OpenSpec 能力且依赖已准备时，显式针对项目初始化 |

`run`/`lock` 的 agent 参数必须与选择的 profile.agent 一致，否则在副作用前返回 2。
默认 profile 仍遵循现有机器配置及 dsh-default 回落，不因新增 Pi 改变 DSH 用户行为。
recover使用受保护实例元数据与保存的lease身份，不要求当前模型/secret/新依赖齐备，
也不启动原生宿主；完整字段、计划300秒有效期和退出码见 [恢复契约](recovery-and-workspaces.md)。
计划区分停止已启动执行与abort_allocation撤销已证明未启动的预留；两者都不能绕过身份或日志核对。
apply/sync/rollback不隐式触发recover --stop。

原生透传参数必须预检：不得覆盖实例 HOME、资源 loader、受管模型/工具/角色、进程模式或
引入临时远程扩展（例如动态 -e 来源）。拒绝破坏契约的参数，不能照原生可接受就执行。
非受管普通 UI 选项可按 Pi 适配器显式 allowlist 透传；未知项返回 2 并说明受限参数位置。

## 2. 公共来源保持兼容

- `profile.roles` 永远为 **逻辑角色 ID → 所选逻辑模型 ID**，不存放角色内容。
- `providers/models/rules/skills/plugins/mcp` 仍使用显式选择数组；对象递归合并，数组整体替换。
- 普通角色绑定为 `main/scout/reviewer`；受管绑定为
  `task_keeper_reader/task_keeper_writer/task_keeper_reviewer`，第二视角另用 `second_view`。
- 全部 profile 检查结构、未知字段、已提供引用和静态不支持组合；必需机器绑定与所选能力就绪
  仅检查当前选择的 profile。未选中的未绑定 pi-managed 不得阻塞 DSH 或 pi-default。
- 所有已提供引用在 resolve/validate 时检查；原生 provider/model 不允许模糊选择或偷偷 fallback。
- Pi 原生设置只通过 Pi adapter schema 接受，不增加公共任意 extras。

## 3. Pi 资源声明与选择

`agents/pi/agent.toml` 新增 adapter 私有的 `resources.<id>` 表：

| 字段 | 类型与约束 |
|---|---|
| kind | role / prompt / theme / extension |
| path | 仓库相对路径，无越界或符号链接；完整资源身份受锁约束 |
| scope | global / project；project 是显式项目集成资源，不自动写每个 cwd |
| override | 可选，必须精确匹配被替代来源身份；未声明覆盖拒绝 |
| model_role | 仅 role；引用公共 roles 的键，不重复模型 ID |
| tools | 仅 role；固定工具 ID 数组；受管工具不可动态扩大 |
| read_roots / write_roots | 仅 role；已声明根 ID 数组，不接受随模型输出产生的新根 |
| nested | 仅 role；本版固定 false |

Pi `agent.toml` 另有三个 closed catalog：`external_skills.<id>` 声明来源用途与缺省禁用，
`policies.<id>` 必须符合 [Permission Policy v1](permission-policy.md)：schema_version=1、
default=deny及closed file/command rules，固定exact/subtree匹配和deny优先；
`external_tools.<id>` 声明版本检查/用途。
机器覆盖用 `agent_options.external_skills.<id>.path`、`external_tools.<id>.executable/args/version`
绑定具体位置；不得新增未登记 ID。policies 的具体规则通过 `permissions` 已声明字段编译，
不允许任意可执行策略脚本。catalog 均可从来源解析，缺绑定只影响选中的能力。

Pi `agent_options` 为 closed schema；下列子表中的未知键一律拒绝：

| 表 | 字段及含义 |
|---|---|
| runtime | `engine=node\|bun`；配方固定，普通用户不能与锁身份不一致 |
| resources | `roles/prompts/themes/extensions`：资源 ID 选择数组 |
| model_settings | 按已选逻辑 model ID 指定 `reasoning` 布尔值和 `thinking_level_map`（off/minimal/low/medium/high/xhigh/max 到非空 string）及 `disabled_thinking_levels[]`（转成原生 null；TOML 本身没有 null）；映射到 Pi 原生模型能力，不修改 DSH 字段 |
| ui | `theme`：已选 theme ID；`quiet_startup`、`hide_thinking` 布尔值 |
| discovery | `project_resources` 布尔默认 false；`external_skills=[]`；启用时用显式已登记来源 ID |
| external_skills | `<已登记id>.path`：机器显式技能目录，只读验证，无隐式全局扫描 |
| external_tools | `<已登记id>.executable/args/version`：明确工具绑定，版本校验不执行宿主默认探测 |
| paths | `roots.<id>`：机器绝对路径与用途 read/write/project；禁止 secrets 目录作为项目根 |
| checks | `<id>.executable`、`args[]`、`project_root`、`timeout_seconds`、`foreground=true` ；受管检查还需 `kind=build\|tests`、`parser=exit-code\|json\|tap\|pytest`、`minimum_tests` 正整数及 `inputs[]`（不可静默改动的验收逻辑文件）；tests 不接受 exit-code 单独作计数证据 |
| permissions | `policy_ref`、`readonly_roots[]`、`denied_roots[]`；按Permission Policy v1编译，无任意规则脚本 |
| task_keeper | `enabled`、`project_root`、`check_ids[]`、`second_view_enabled`、`max_second_view_rounds`、`limits` |
| task_keeper.limits | `active_children=2`、`parallel_readers=1`、`writers_per_job=1`；`model_requests`、`model_turns`、`wall_seconds` 正整数；`token_limit` 可选正整数；`cost_limit` 可选十进制字符串 |
| network | `routes.<id>.mode=direct\|proxy`、可选 `proxy_url`、`provider_ids[]`、可选 `credential_ref` |
| model_delegate | `enabled`、`backends[]`、`allowed_modes[]`、`presets[]`、`max_run_seconds`、`context_budget_tokens` |
| model_delegate.codex | `mode=readonly\|explicit-write`、`network_route`、`model` 可选明确ID；backend选择决定是否安装Codex |
| model_delegate.pi | `model_roles[]`、`network_route`；只使用所选provider/model与隔离Pi运行包 |
| terminal | `notifications` 布尔；`agent_state_command` 可选外部工具 ID，不猜测全局脚本 |

machine 差异放在既有 `overrides.profiles.<id>.agent_options`；代理 URL 不允许内嵌秘密。
项目检查 argv 是维护者可信配置，不做 shell eval，不允许模型随任务增加命令。
插件更细设置通过逐插件 closed schema 编译；不得开放 raw native config 字典。
execution_mode由可信运行入口决定：ordinary根为实际业务worktree，managed根为candidate，
delegate-readonly禁止写，delegate-write根为独立授权worktree；普通会话不要求Task Keeper的task grant。

## 4. 初始化和绑定状态

`pi-default` 默认不包含私有模型；空模型集可校验、渲染与部署，doctor 标记 model_binding=unconfigured。
首次原生 UI 仅用于显式登录/选择；普通 scout/reviewer 及主任务未绑定时拒绝 dispatch，
不能用原生 fallback 自动选模。用户先在机器覆盖登记实际 provider/model ID、选择数组与角色，
再登录、选择和 capture；capture 不负责把未知原生模型自动变为公共声明。没有凭据不能标为执行就绪。
`pi-managed` 的三角色、项目根和至少一个真实检查必须绑定；缺少时 validate=2。
第二视角开启时必须绑定 second_view，不能自动用 reviewer 填充不同用户意图。
可选能力未选中为 not-selected；一旦选中缺少依赖为 5，所需 secret 缺失为 3。

## 5. 原生所有权与秘密

- settings 的已声明叶子为 FIELDS；角色/主题/提示/规则等完整内容为 FILE。
- models 的非秘密叶子为 FIELDS；apiKey 仅为精确生成的 `$AGENTCFG_PI_CREDENTIAL_<ID>`。
- credential projection guard 在所有差异、备份、恢复与捕获前运行，字面秘密、命令、组合模板
  或错误引用返回 4，并且不将原值写入错误或快照。框架输入的错误引用返回 2。
  candidate、current、previous/pending 使用各自启动契约保存的合法引用集合；
  当前原生值按已部署集合校验，新期望按candidate集合校验，合法轮换和回滚不互相误拒绝。
- auth/trust、会话、任务库、日志与缓存为 RUNTIME；安装树为 PACKAGE，不属于配置备份。
- `HOME=<instance>/user-home`、`PI_CODING_AGENT_DIR=<instance>/pi-home`；所有 XDG 在隔离 HOME。
  `CODEX_HOME=<instance>/codex-home` 只在选中外部 Codex 时设置，禁止读取全局账户。
- 以上 home/bridge/grant 变量为保留变量，机器 inherit/values 不得覆盖。
- capture 只接受选择集内可唯一反解的主题和主模型；动态未声明模型或重复映射返回 2。

旧agent_options.codex不作为新配置的长期别名；迁移提案转换到model_delegate.codex并重新严格校验。
未选择backend时注册入口报告not-selected；Pi主能力和其他backend不因此失效。
完整委托/登录/控制接口见 [model-delegation.md](model-delegation.md)。

## 6. 迁移提案与诊断输出

私人提案含 `schema_version, source_snapshot, feature_identity, items[], proposed_overrides, blockers[]`。
item 含来源 ID、当前选择、磁盘存在、加载/执行证据状态、处置、目标、理由和依赖；
实际机器路径仅在私人位置映射中存储。不会读取认证或会话正文，也不执行旧生成器。
提案不是可直接 apply 的原生文件；先采纳允许的来源修改，再 validate/plan/apply。

doctor 保留既有顶层结果，新增 `capabilities` 列表：
`id, selected, configured, deployed, dependencies, load_evidence, authentication, execution_evidence, blockers, location_id`。
证据状态为 verified / stale / not-run；authentication 为 not-required / not-inspected / pending-login / observed-ready，
离线不能为获取 observed-ready 而读取账号或调用服务。只依据匹配的已有观测，且显示日期。

退出码保持 0/2/3/4/5/6；仅 run 成功启动后透传宿主退出码。
存在漂移或待登录提示可返回 0，但 blockers 必须可见；必需配置/依赖错误按相应退出码失败。
