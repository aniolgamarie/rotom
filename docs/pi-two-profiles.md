# Pi Base / Full 升级与当前使用边界

本文对应 `specs/005-pi-two-profiles/` 的新方案；历史四配方使用说明仍见 [Pi 使用说明](pi.md)。两者的锁、支持证据与运行包不能互换。

## 当前状态

截至 2026-10-12，Base 与 Full 的完整产品验收均未完成，正式任务32/100。Base 已有配置投影、独立现代锁管线、官方 SDK 启动适配、资源白名单和受管文件/Shell/MCP 接线；正常 producer、临时 HOME 冷安装及真实 CLI 读写正反场景已有实际证据。仓库已发布两 profile 锁：Base 为 current，Full 为 candidate。用户日常默认入口尚未切换；当前核心代码仍在修改，锁须在稳定后重新生成和验收。

2026-10-10 默认生产代码接线增量：父侧按显式配置构造受管 Shell 桥，文件与 Shell 共用准入账本（24项默认测试）；插件用户ID到安装能力ID显式映射，Todo经公开工具归属核对后进入主会话白名单（Python33/Node131）。均已稳定独立复核，真实官方SDK/运行包/系统树资格仍另验。

主模型现在通过真实 ModelRuntime 的受限公开视图交给会话，发送前检查所选模型/API/端点和认证来源；SDK 的 scopedModels 筛选本身不充当权限。当前原生主模型仅接显式直连，未接通的 Provider 代理路线明确拒绝。Footer 的未知费用显示“费用未计量”，新会话清除旧缓存。当前八场官方 SDK 合成探针已验证正常发送、越界模型/API 拒绝、取消和压缩后关闭重开；真实账号/Provider、默认入口与模型质量另验。

MCP 默认接线只开放显式选择的 stdio、Streamable HTTP none/bearer 组合，按需启用，嵌套调用消费同一准入账本；当前 OAuth/经典 SSE 组合拒绝为未合格，不回退 SDK 默认网络。普通工具默认基线 T017 已完整验收。私有正常安装的原 CLI/Host/SDK 已实际执行 C++ 边界修复与16项通过、Shell两项、Neovim一项及敏感文件拒绝；测试使用本地合成 Provider，逐轮失败保留，尚未验证真实模型质量、实际账号与完整体验。详见 [日常业务记录](../specs/005-pi-two-profiles/implementation-status.md)。

Full 显式 profile 和正常生成的基础候选锁已存在，当前只选择共享基础能力；统一委派、Task Keeper 和 Durable 的完整控制器/启动组合正在实现。已实现的 Durable 存储、模型调用与恢复组件不等于可以启动的 Full 服务。当前模型自动审核保持关闭：默认模型的发送前严格输入 token 上界仍未验证。

未完成的入口、真实账号、终端与整体隔离分别记录，见 [权限覆盖状态](pi-permissions.md)、[实施任务](../specs/005-pi-two-profiles/tasks.md) 与 [验收要求](../specs/005-pi-two-profiles/acceptance.md)。旧迁移的通过结果不能外推为本次升级通过。

## 两种配置的职责

| 配置 | 目标 | 默认能力边界 |
| --- | --- | --- |
| Base | 单主 Agent 的日常 C++、Shell、Neovim 开发 | 原生主会话、领域技能、普通提示词、Todo/Footer/Loop Guard；不需要 Full 包、Codex 账号或持久服务 |
| Full | 按需委派、受管任务和持久只读任务 | 在共享基础上增加统一 delegate、Task Keeper 和 Durable；每项有独立能力/提供者/恢复契约 |

Base 当前选择 `cpp-database-kernel`、`neovim-plugin-development`、`safe-linux-scripting` 完整技能目录，包含相对脚本、资源和许可证；部署只复制，不运行迁入脚本。默认普通提示词为 implement、plan、review；其他普通提示词通过配置显式选择。Base 不默认注入完整 Superpowers/OpenSpec，不引导调用 Full 专属工具。

主会话模型沿用 rotom 的公共 provider/model 与机器覆盖。模型标识、endpoint、路由和秘密引用参与配置投影；API key、OAuth token 及其内容散列不进入通用身份和日志。OAuth 使用目标实例的原生账号目录；不复制全局或旧实例账号。切换 provider 不代表允许跨账号 fallback。

## 锁、实例与升级

现代提供者替换沿用原受锁部署事务。`sync` 只记录包已安装和验证；`apply` 才选择运行身份。有状态提供者变源或辅助依赖变化需要明确格式迁移材料，当前不能自动迁移；无状态等价提供者必须保持能力接口与配置所有权。完整实际替换组合仍在验收。

新增 `./agentcfg --profile pi-base pi-maintenance status --format json` 查询保存阶段和实际部署指针；它不触发恢复。`pi-maintenance recover --format json` 在空闲边界恢复原配置 journal 后对账，不重派旧任务。`pi-maintenance uninstall --runtime-identity HEX64 --format json` 只删除明确受管旧运行包，当前/previous/活动/未知恢复/会话引用会阻断；不删除账号或业务数据。Full 的存储引用退休查询尚不完整，旧包目前保持保护。安装后丢失回执或侧记录未完成时，`run` 明确拒绝，先保存现场并执行显式维护恢复。

现代 profile 使用 `locks/pi-modern/`；历史 profile 继续使用 `locks/pi/`。缺失现代锁会明确失败，不回退到旧宿主。RuntimeIdentity 固定运行包与能力绑定，ConfigIdentity 固定有效非秘密配置；旧执行仍使用原绑定。

来源、依赖、公开契约、许可证和资源清单必须一致后，候选才能被显式晋级。市场插件可替换，但替换是维护操作：先验证新提供者和状态迁移，再发布新锁；运行中的任务不自动换源。账号、会话和任务数据库属于实例的可写状态，升级/回滚不覆盖它们。活动实例、未知租约、所有权冲突和待恢复状态必须保留并诊断。

维护流程沿用 agentcfg 的 validate → plan → sync → apply → doctor → run。这个流程已在独立临时 HOME 中实际执行；产品发布仍需完整验收，代码、来源或锁变化后重新生成对应运行包。下载/安装只由显式 sync 或锁维护执行，render/doctor 不启动模型或持久服务。

非 Git 工作根通过 [workspace register](pi-permissions.md#工作根登记) 显式登记。登记不是写授权；所有受管写入仍需同一物理根上的 Writer 租约。路径别名、不同 profile HOME、子任务和另一进程不能创建第二个 Writer。Git 专属功能在非 Git 根明确不可用。

## 权限、模型审查与隔离

权限核心先形成绑定实际参数、cwd、工作根、策略代次、会话、运行身份、截止时间和取消代次的 PreparedOperation。确定性策略、人工确认或获准 reviewer 只审查这个对象；执行只能消费对应的一次许可。模型返回的风险分数、operationId 或摘要不具有授权能力。

模型审查通过仓库自有公开扩展/适配接口接入，不修改 Pi 上游。pi-jev 是包含工具拦截、风险判断、人工确认和放行/拒绝的权限控制扩展，已列为优先衡量完整原样复用的候选，其mode、重试及输出审核等默认值可通过配置调整；只在真实缺口上加薄适配。当前尚未安装或启用，最终权限控制提供者在T049–T057按同条件实证决定；本地权限核心继续独立承担执行授权。缓存只能复用诊断，不能缓存执行许可。审核错误、未知 usage、取消及迟到回复仍服从现有拒绝/人工决定和预算保留规则。详见 [D17 参考决定](../specs/005-pi-two-profiles/research.md#d17-pi-jev-权限控制扩展复用候选2026-10-10-更新)。

公开扩展与宿主同进程运行，工具包装无法隔离扩展任意文件/进程行为。Linux bwrap、路径遮罩、网络边界和进程终止必须通过实际产品入口验证；组件探针成功不能替代整进程隔离结论。当前直接用户命令、MCP/Code Mode 与前端文件操作仍有未闭合覆盖，不能声明现代 Base 已有完整沙箱保护。

## 验证与交付

默认测试只操作仓库或临时 HOME，使用虚构 provider、网络阻断及假子进程，不启动第三方宿主。官方 SDK/RPC 合成探针、实际终端、真实账号模型与整体产品验收分层保存。用户已允许主代理自行判断测试风险；无外部副作用的隔离合成测试直接执行，其他步骤核对对应已有授权。

最终 Base 需要日常 C++ 复现/最小修复/检查/diff、Shell/Neovim、主会话认证与切换、压缩恢复、原生 MCP、完整权限/隔离、冷安装、升级恢复与两态性能证据。Full 另需 delegate/TK/Durable 和持久恢复证据。Linux 是本次必须实测的平台；其他平台按需处理。未运行、失败、缺账号、环境不足或过期证据分别保留，不能算通过。

## 当前 Base CLI：能核对什么，何时会拒绝

下面参数以当前 `agentcfg` parser 为准。全局 `--local PATH` 与 `--machine NAME` 二选一，`--profile pi-base` 放在子命令前；不修改本地 `default_profile`。`--local` 是明确的私人 TOML 文件路径；相对路径按调用时 cwd 解析，`~/...` 即使被 shell 引号保留，也由 agentcfg 展开到当前 HOME。`workspace` 是独立账户级登记入口，不接受这些选择器。

| 命令 | 当前参数与作用 | 当前限制 |
| --- | --- | --- |
| `validate` | `--format auto/human/json`；离线核 schema、引用、映射和锁 | 不检查真实凭据；现代锁缺失或无效仍失败，不能只因配置投影可解析就算通过 |
| `plan` | `--format`；展示部署差异、漂移和冲突 | 迁移盘点另有 `--from-pi-home PATH`，`--from-starter PATH` 必须与前者一起；提案不是执行授权 |
| `sync` | `--format`；消费现有锁并暂存、注册运行包 | 有安装/下载副作用；临时 HOME 的正常安装已实测。当前来源与锁不一致时拒绝，不能靠旧锁补齐 |
| `apply` | `--format`；重新核验并部署配置 | 有实例写入副作用；活动/未知执行、漂移或恢复待处理不能强行覆盖 |
| `doctor` | `--format`、`--input`、`--live` | 默认离线；`--input` 只报告终端/就绪元数据，不读按键；`--live` 允许网络检查，不能混入离线验证。诊断可能写私人证据文件，不代表账号已登录或运行资格通过 |
| `run [pi]` | `--cwd PATH`；原生参数必须放在 `--` 后 | 没有 `--format` 参数；使用已部署契约与所选运行包。临时安装的 help/print/RPC 已实测；锁或资格未就绪时拒绝，不回退系统 Pi |

以下是**已核 parser 的虚构 argv 示意**；`/tmp/rotom-base-manual-demo/local.toml` 是示例路径，不是用户配置。手册参数测试使用临时 HOME 中不存在的 local，实际 CLI 在 dispatch 前返回 2；另有独立正常安装和宿主测试，两类证据分别保存。实际部署须使用已准备好的目标、匹配来源的正式锁和运行资格。

```text
./agentcfg --local /tmp/rotom-base-manual-demo/local.toml --profile pi-base validate --format json
./agentcfg --local /tmp/rotom-base-manual-demo/local.toml --profile pi-base plan --format json
./agentcfg --local /tmp/rotom-base-manual-demo/local.toml --profile pi-base sync --format json
./agentcfg --local /tmp/rotom-base-manual-demo/local.toml --profile pi-base apply --format json
./agentcfg --local /tmp/rotom-base-manual-demo/local.toml --profile pi-base doctor --input --format json
./agentcfg --local /tmp/rotom-base-manual-demo/local.toml --profile pi-base run pi --cwd /tmp/rotom-base-manual-demo/project -- --help
```

最后一个例子的 `--help` 是透传给原生 Pi 的参数，不能用来验证 agentcfg parser 而忽略启动前检查。只看管理器帮助应使用 `./agentcfg run --help`；它无需 local、锁或账号。不存在 `run --format json`、`apply --yes` 或通用 `--dry-run` 开关，不要借用其他工具的参数。

### 工作根登记与查询

接口为 `./agentcfg workspace register --path PATH --format json`、`workspace inspect --path PATH --format json` 和 `workspace list --format json`。虚构示例路径是 `/tmp/rotom-base-manual-demo/non-git`；register 有登记写入，仅核其 parser，没有执行该写入示例。inspect/list 是查询；原隔离 CLI 测试验证它们不读取配置或秘密。

登记绑定 OS 账户 home 下的私人协调目录及实际物理根，不按 profile HOME 分裂出第二套 Writer；临时改 `$HOME` 不迁移登记。必须是明确已有、当前属主的安全非 Git 根，Git 标记、控制目录覆盖、身份变化或锁繁忙会拒绝。登记不是 permission allow 或 Writer 租约；后续写入仍走同一原准入及工作区租约，未知旧执行不因查询而释放。

### 错误与恢复边界

| 退出码 | 管理器边界 | 处理方向 |
| --- | --- | --- |
| 2 | 参数、配置/schema/引用、缺失或无效锁 | 先核选择器、本地配置和对应现代锁；不自动解析新依赖、换旧 profile 或系统宿主 |
| 3 | 所需凭据缺失 | 在选定私人配置/目标实例的受控账号入口补齐；不复制宿主 token，不换账号 fallback |
| 4 | 所有权/活动实例、未知租约、漂移冲突或恢复待处理 | 保留现场，先 doctor/对账；不能直接覆盖、释放 Writer 或强停旧实例 |
| 5 | 缺必要运行包、依赖/原生资格或运行时未合格 transport | 明确能力尚不可用；组件/default 测试不能替代实际运行包和平台资格。现代主模型未接通的代理路线在配置校验阶段拒绝，属于退出码 2 |
| 6 | 文件系统或内部操作失败 | 保存固定错误、运行身份和私人日志，核对文件/所有权后恢复；不把失败当作已释放/已完成 |

`run` 真正启动后的原生退出码可能超出这个管理器错误表。当前固定合成 CLI 场景已观察到退出0；完整错误矩阵、真实账号和终端仍另验。错误码相同也不代表故障原因相同；以当前诊断和状态事实为准。

回退分四层：公共来源只通过版本审查/明确回退修改，来源快照不自动改当前包；运行包按已保存身份保留，现代/历史锁不互换，活动或恢复引用的旧包不删除；配置 apply/rollback 仍须原所有权和恢复检查，不能用复制旧目录绕过；账号、会话和业务状态属于目标实例，不因源码或包回退而拷贝/覆盖。`rollback` 命令存在，但本次没有执行维护回退，不能从本手册宣称现代 Base 升级/失败恢复已通过。

当前 MCP 的 stdio、Streamable HTTP none/bearer 是已接线范围，默认 server disabled，需在 TUI 的 `/mcp` manager 中明确 session-only Enable。固定 SDK 的 RPC 模式不提供这一启用菜单；RPC `/mcp` 状态查询不能启用服务。OAuth/经典 SSE 仍未合格，账号/实际服务另验。主模型受限视图的合成 SDK 资格不等于真实 provider 认证；主模型 proxy 路线未接通，不能把网络路由声明或命令存在视为已支持。Base 完整产品验收尚未完成，日常默认入口保持原设置。T048 的 Full/完整维护手册仍待完成。

### 会话历史与可选 Stop hook

Base 的公开 RPC 会话查询、分支、手动压缩和切换原生会话已通过实际安装 CLI 合成测试：分支使用新的原生 ID，旧文件保留；完全关闭 CLI 后，新 CLI 能切回同一分支 ID、恢复压缩记录并继续发送。查询、分支和切换未触发模型请求。固定合成摘要保留了任务、产物和失败引用；这验证持久化链路，不表示真实模型摘要质量已合格。证据绑定当时的安装身份，见 [会话验收记录](../specs/005-pi-two-profiles/native-base-session-product-probe.md)。

可选项目/会话 Stop hook 当前为 **inactive**，用户未选择或信任任何此类 hook。固定 Pi 1.0.1 提供 `agent_end`、`agent_settled` 和 `session_shutdown` 等公开扩展事件；这些事件本身没有赋予脚本执行、重新发送模型或批准工具的权限。当前没有自动运行项目 Stop 脚本、停止后重新派发任务或改变其他会话的流程。以后显式启用时，仍需原公开事件、受管命令准入、有限无进展规则和终止证明；hook 故障不能把失败改成成功，也不能阻止原生退出恢复。可选 hook 保持 inactive 不阻塞产品验收。
