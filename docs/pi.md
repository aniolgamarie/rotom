# 使用 agentcfg 管理 Pi

Pi 迁移 spec 已按 2026-09-24 用户确认的范围完成：四配方、实例隔离、配置部署、Task Keeper 和 model-delegate 软件集成，以及 Linux x86_64 四配方 mock/native 与每配方双路径冷重建。候选 `9d6a9270` 已冻结，当前软件范围 81 项验收全部通过。其他三平台实机及真实账号／服务验证已移至[独立后续清单](follow-ups/pi-platform-and-live-validation.md)，仍为未验证。具体证据见 [完成报告](acceptance/pi-spec-closure-20260924/README.md)、[实施任务](../specs/001-unify-pi-capabilities/tasks.md)和 [支持矩阵](acceptance/pi-support-matrix.md)。

## 配置分别放在哪里

| 内容 | 管理位置 |
| --- | --- |
| 跨机器复用的技能、规则 | `shared/skills/`、`shared/content.toml` |
| Pi 角色、提示、主题、插件声明 | `agents/pi/` |
| 机器无关的能力组合 | `profiles/pi-*.toml` |
| 本机路径、精确模型绑定、服务与检查程序 | 私人 `local.toml` 的 `overrides` |
| API 密钥 | 私人 `local.toml` 的 `secrets`；不提交 |
| 原生 OAuth 登录、会话、任务数据 | agentcfg 生成的独立实例；不复制旧 HOME |
| 可重建依赖及来源摘要 | `locks/pi/`；四配方完整候选锁已生成 |

机器文件使用 0600 权限。数组覆盖会替换整个数组，例如追加插件时需要保留仍需启用的插件名称。

## 选择配方

| 配方 | 宿主 | 用途 |
| --- | --- | --- |
| `pi-default` | Node | 父会话实施，scout/reviewer 只读协作，Pi backend 委托 |
| `pi-managed` | Node | Task Keeper 候选 worktree、检查、审查和预算管理 |
| `pi-codex` | Node | 普通协作，以及通过 model-delegate 使用官方 Codex CLI |
| `pi-cursor` | Bun | Cursor provider 的独立普通会话和只读 Pi backend 委托 |

普通核心默认选择 Todo、循环保护和状态栏，Todo 独立于 Task Keeper 的任务/预算。`agent_options.todo` 可显式设置 `locale`、`maxWidgetLines`、`collapseKey` 与提示指导；不扫描旧 Todo 配置。

固定基线为 Pi 0.84.4、Node 24.14.0、npm 11.19.1、Bun 1.4.0、Codex 0.154.0、pi-cursor 1.4.29。版本声明不是平台通过证据。Cursor/Bun 与 Task Keeper 互斥；目前 Cursor 路线只接受显式直连，委托重试为零，代理配置会明确拒绝。

Linux 四个配方都安装锁定的 bwrap 辅助程序，Pi 宿主在独立 PID 命名空间中执行；宿主退出时由内核终止其后代，监督者核验回收后才解除保护。该辅助程序复用固定 Codex 发行物中的 bwrap，来源及许可证随锁保留；安装它不代表启用 Codex 委托。宿主门控保留原始标准输入，文件授权仍由原有实例策略决定。

## 新机准备顺序

以下是安装管线的使用顺序；完整冷重建与原生验收仍在执行，当前不宣称所有平台已验证。

1. 获取仓库，准备 Python 3.11+、uv 和所选配方要求的精确 Node/npm/Bun。agentcfg 不修改系统工具链。
2. 在仓库执行 `uv sync --locked`，之后使用 `./agentcfg`；该入口直接使用仓库 `.venv`。
3. 从 [普通示例](../examples/pi-workstation.toml) 或 [Task Keeper 示例](../examples/pi-managed.toml) 建立私人机器文件。替换虚构的 provider、远程模型 ID 和绝对路径；只把真实密钥放入私人 secrets。
4. 先验证、计划，再显式同步运行包和部署。常规机器消费已经审阅的锁；只有更新依赖的维护步骤才运行 `lock --agent pi`。

```sh
./agentcfg --local /private/local.toml --profile pi-default validate
./agentcfg --local /private/local.toml --profile pi-default plan
./agentcfg --local /private/local.toml --profile pi-default sync
./agentcfg --local /private/local.toml --profile pi-default apply
./agentcfg --local /private/local.toml --profile pi-default doctor
./agentcfg --local /private/local.toml --profile pi-default run pi --cwd /absolute/project
```

`sync` 才执行依赖下载和批准的必要构建。npm 生命周期脚本默认不执行；官方 Codex 原生资产按当前平台下载并核验 SHA256、入口和架构。下载或安装失败保留旧运行包。下载阶段保留标准 `http_proxy` / `https_proxy` / `no_proxy`（及大写形式）；代理 URL 不能内嵌凭据，系统 CA 校验保持开启。这些下载代理不会进入模型宿主，模型代理仍使用本机配置中的显式路线。`validate`、`render`、`plan`、`apply` 不以安装器隐式补齐依赖。

## 模型与账号

模型引用必须在当前 profile 选中的集合内。绑定 `main`、`scout`、`reviewer` 以及 managed 角色时填写逻辑模型 ID；模型声明中的 `remote_id` 必须精确，不使用模糊模型匹配。

无 `main` 的普通配方可以进入 bootstrap 登录界面，但不能派发任务。API key 使用 `secret:名称`，运行时转换成实例环境引用。OAuth 在目标实例的原生登录流程中建立；不自动读取系统 Cursor 账号、旧 Pi auth.json 或全局 CODEX_HOME。Codex 显式控制与登录流程见 [model-delegate 使用说明](../shared/skills/model-delegate/USAGE.md)。

## Task Keeper

[pi-managed.toml](../examples/pi-managed.toml) 展示完整的机器绑定结构：

- 绑定 reader、writer、reviewer；第二视角开启时另绑 `second_view`。
- 明确 project 根、候选权限策略和网络路线。
- 构建、测试使用可信前台程序及固定 argv，记录必要输入、解析器和最低测试数量。
- 写入在独立候选 worktree 中进行，原 checkout 不自动合并。只读角色不会因技能或用途模板而获得写权限。
- 所有操作复用唯一 AgentManager 和 supervisor。取消请求被接受不等于物理进程已经终止。

普通模式仍由父会话实施，并交给 fresh reviewer 审查；需要受管工作流时使用 `kernel_task`，不能把普通角色改成隐藏的 managed writer。

## model-delegate 替换

迁移目标中不保留 codex-delegate。`model_delegate` 是统一入口，必须明确 backend；七个原 Codex 角色已转为 `general`、`context`、`challenge`、`plan`、`research`、`review`、`scout` 用途模板。模板只补充任务要求，不增加另一层角色或授权。

Codex backend 使用官方 CLI 和原生工具，按整次运行绑定授权、沙箱、工作区及监督生命周期。Pi backend 为只读委托。高级 Codex 写操作只能使用显式授权的独立 worktree；细节见 [技能](../shared/skills/model-delegate/SKILL.md) 与 [协议](../shared/skills/model-delegate/API.md)。

Codex 文件操作需要明确选择可投影的策略，例如本机覆盖中的 `agent_options.permissions.policy_ref = "delegate-worktree"`。
该策略声明完整的项目文件操作范围，但只读模式仍由执行 grant 和原生只读挂载禁止写入；写入还需要 `explicit-write`、`implement` 和用户 CLI 的 worktree 授权。
默认 `project-default` 为 deny，不会因为选择了 Codex backend 自动开放文件。Linux 下过宽到同时包住私有实例和运行包的项目根会拒绝，需使用明确的业务项目目录。

按 2026-09-18 确认的路线，Codex 启动前执行受限配置准入：系统配置目录须为空或不存在，macOS 受管偏好须不存在，实例账号须为可识别的个人 OAuth 或明确 API key 模式。组织、未知或混合身份以及无法核验的配置来源会拒绝执行，保留原账号和管理员配置。稳定受信机器和账号是运行前提，预检不提供原子配置保证；平台行为仍待原生验收。详细原因码和处理方式见 [配置准入说明](pi-codex-admission.md)。

## 四种日常维护

**增加技能**：将完整技能目录（含相对引用、脚本、许可证）放入 `shared/skills/`，在 `shared/content.toml` 登记，再将 ID 加入目标 profile 的 `skills`。外部技能使用明确路径绑定，不扫描全局 HOME。重新 validate/plan/apply。

**调整角色**：修改 `agents/pi/roles/` 的来源或 profile 的逻辑模型绑定，再部署。受管角色同名冲突会失败；当前普通 scout/reviewer 保持只读。生成的 `pi-home/agents/` 不是编辑入口。

**切换模型**：登记 provider 和精确 remote_id，把逻辑 ID 加入所选 models，再调整角色引用。更改后旧模型／路线证据变为 stale，重新执行适用层级验证；不能把旧账号观测当成本次可用性证明。

**禁用插件**：从 profile 的 `plugins` 或 `agent_options.resources.extensions` 移除对应选择，同时处理明确依赖它的插件与选项。使用 plan 查看变化；有活动实例、子进程或未知租约时先处理活动，不强制覆盖。

## 可选能力

- [终端状态通知](pi-agent-state.md)：OSC 标题或明确绑定的 agent-report 服务。
- pi-rules：显式 `root_refs`，只读已声明规则根；不扫描 HOME。
- OpenSpec：固定 1.11.0 CLI 与 12 个完整技能；选择 `openspec` 后使用 `project init` 的显式目标目录，保留用户修改并进行冲突检查。
- Superpowers：固定提交的 14 个完整技能及 Pi bootstrap；选择 `superpowers` 才加载。辅助服务脚本需要显式绑定，不自动启动。
- [Slopchop 审查与编辑器](pi-review.md)：差异和标注 UI 保留，Git、文件与编辑器接入统一工作区监督；交互编辑器使用显式绑定的私人 PTY。代码与 mock 已接通，真实终端仍待验收。
- [MCP](pi-mcp.md)：stdio 监督传输、HTTP/SSE 显式路线、Bearer／OAuth、sampling、用户输入、脚本、Apps 页面和直接工具已接入代码并登记四配方来源。候选 `9d6a9270` 的 Linux 合成服务原生连接场景通过；真实服务与认证调用仍待后续 live 验证。
- [ReadSeek](pi-readseek.md)：九工具契约、监督控制器、Git/rg 选择、文件提交及视觉资产已接通。候选 `9d6a9270` 的 Linux pi-default、pi-codex、pi-cursor（Bun 宿主使用独立锁定 Node worker）均取得双目标九工具原生验证；pi-managed 使用 Task Keeper 工具。macOS x86_64 源码构建入口已有实现但缺实机验证，其他平台结果不由 Linux 结果推定。
- [web](pi-web.md)：显式提供方、路线、凭据和工具适配已接入；候选上的合成 SearXNG 搜索原生验收通过，真实服务验收尚未执行。配置样例仅说明格式，不代表账号已可用。

Codex、Cursor、MCP、web、代理、终端服务的真实验收选择保留，当前为“已选、未验证”，不会变成“未选择”。这些 live 验收与其他三平台实机验证已转出当前 spec，未来实际使用时另行处理；历史完整矩阵继续保留 not-run，不阻塞当前软件范围验收完成。

## 升级、冲突和恢复

`plan` 给出依赖、角色、策略、路线、资源与配置变化，以及旧 runtime 的历史定位。Pi session 和 Task Keeper store 当前都只接受已声明的 v3；不兼容数据明确拒绝，不自动降级或改写。

回滚仅恢复配置和保存的运行引用；账号、会话和任务数据库保留。跨实例共享 worktree 的活动写租约不能由换 HOME 绕过。显式停止恢复命令、300 秒计划有效期与未知活动处理见 [迁移指南](pi-migration.md#活动阻塞与显式停止恢复)。

诊断和发布验收是不同操作：`doctor` 分层显示状态；`report-only` 成功只表示报告生成；`check-release` 要求固定范围中所有适用证据匹配通过。命令与退出码见 [诊断说明](pi-diagnostics.md)。
