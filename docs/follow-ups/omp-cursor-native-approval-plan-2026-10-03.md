# Cursor 原生 Bash 智能审批：独立插件方案与可行性

状态：可行性关键机制已验证；生产插件改造尚未实施，日常部署不变。日期：2026-10-03。

## 问题与结论

当前独立插件只审查 `permission_bash`。官方 OMP v18.4.5 的 Cursor shell、shellStream、piBash 通道按固定名称查找 registry 中的 `bash`，不受模型 active tools 中移除 bash 的约束。因此 smart/ready 与 reviewer 调用数 0 可以同时出现，原生 `Allow tool: bash` 仍会弹出。

建议通过公开 `registerTool()` 注册同名 bash，在执行函数完成审批后使用公开 `ctx.invokeTool()` 委托原生实现。接口文档明确支持这种包装，不修改上游源码、vendor/cache、二进制或内部对象。它能保留原生执行与 bookkeeping，无需重新实现终端后端。但委托不会再次经过原生审批 gate，安全检查必须在包装器中完成。

固定验证身份：v18.4.5，commit `79808c3bf8f8cd9826decc63e3e18b13035f64f8`，Linux x64 官方二进制 SHA256 `42c710239b3fc30b9759424f973c6c143709935d5752be7eec8d7b011f40d864`。不把结论推广到未验证版本或平台。

## 已验证与尚未验证

| 状态 | 证据 | 实际证明范围 |
|---|---|---|
| 已完成 | 固定 SDK 严格类型检查通过 | 包装、委托、原生审批类、设置句柄使用真实官方声明，无伪造 SDK |
| 已完成 | 7 项纯原型测试，27 assertions | allow 委托一次；deny/unavailable/缺少委托入口/扩展参数不委托 |
| 已完成 | 6 组隔离官方宿主 fixture | allow 实际 ls 一次；deny/unavailable 无执行；插件缺失原生 prompt 在无 UI 环境阻止；钩子可阻止 runtime override 与原生 bash deny |
| 已完成 | 官方宿主中调用公开 `BashTool.approval()` | 普通命令、pattern deny、pattern prompt、critical prompt、复合命令 deny 五种结果符合上游实现；只判定危险字符串，不执行它们 |
| 已完成 | 公开 scoped Settings 与 Setting 句柄 | 工具事件内取得真实会话设置、实际 bash 策略和 patterns；能读取内存 override；两个并发 scope 各自取得自己的实例 |
| 已完成 | 源码分派与公开接口复核 | Cursor 三个原生分派入口使用 registry 的 bash；同名包装替换该槽并可委托被保留的原生实现 |
| 环境不足未验证 | 直接 Cursor handler 分派探针 | 严格类型检查通过，但相对模块中的包 import 在 standalone 扩展加载时 ResolveMessage；没有把它记为运行通过 |
| 已完成（替代方法失败，已作取舍） | 将 Cursor 探针 bundle 成单入口的替代尝试 | 官方二进制仍无法加载该子路径，整个探针扩展未加载；回到已通过的设置探针。保留失败证据，生产插件不依赖 CursorExecHandlers 导入 |
| 待实施 | 完整生产审批链 | 原型使用确定性 allow/deny/unavailable；未接入真实 reviewer、人工 UI、完整审批票据与配置变更 |
| 环境不足未验证 | 真实 Cursor OAuth 端到端 | 本轮无外部推理，无 OAuth wire 取证；本机已授权付费预算 102/102 耗尽，不借 fixture 声称真实服务通过 |
| 待实施 | kernel 默认环境与高级执行 | startup/direnv/interceptor/auto-background、async/service/PTY、取消/超时/模型切换须分项验证 |

机器证据见 [omp-bash-wrapper-feasibility-20261003.json](../acceptance/omp-bash-wrapper-feasibility-20261003.json)。原型与本机日志在 `.cache/omp-wrapper-feasibility-20261002/`，日期目录保留启动时身份。原型的拒绝结果未统一设置 isError，只用于“不发生委托”的计数证明；生产版本必须返回明确错误语义。

## 入口与外层策略

原生 bash 包装器声明 `{ tier: "exec", policyKey: "permission_bash" }`。配方保持 `tools.approval.permission_bash=allow` 和 `tools.approval.bash=prompt`。

allow 仅允许进入插件自己的审批函数，不等于批准执行。插件缺失时回到内建 bash，仍受原生 prompt 保护。插件加载但配置、Settings、票据、原生委托入口不可用时必须阻止，不能直接 delegate。

独立 policyKey 会优先于原生 bash 设置，所以必须显式读取当前 `tools.approval.bash`。其中 deny 必须生效；通常的 bash=prompt 是插件缺失时的保护，不作为所有包装调用都必询问的理由。用户要求所有命令询问时使用 `/permission-control manual`，不能把原生 prompt 的这两种含义混淆。

保留现有 `permission_bash` 作为明确的非交互独立入口，迁移期间两入口共用审查逻辑，执行实现不同：原生 bash 使用 invokeTool；permission_bash 继续自己的公开 exec 后端。invokeTool 是同名委托，不能从 permission_bash 跨名调用 bash。启用包装后，session reset 不再把 active bash 删除；status 应验证注册来源和有效入口。

## 审批顺序与设置来源

1. **捕获可信设置与调用。** 在公开 `tool_call` 事件中取得 `findScopedSettings(ctx.cwd)`。上游 runner 在此事件上调用 `withActiveSettings(this.settings, ...)`，这是捕获时机依据。保存实际 Settings 引用、toolCallId、会话 ID、generation、当前模型身份、规范化完整参数与 cwd。事件外不能凭 cwd 调用查找函数后假设得到了同一会话设置。
2. **检查有效执行上下文。** 从公开 Setting 句柄读取影响执行的配置；使用实际会话 Settings 构造只用于审批的 `BashTool(ToolSession)`。不调用它的 execute，不用默认 Settings 或管理器 sidecar 摘要冒充会话设置，不复制其私有 matcher。只使用公共导出和配置句柄，不使用 rawValue/writeValue 等内部 plumbing。
3. **保留原生下限。** 原生 bash per-tool deny 或 `BashTool.approval()` 的 deny 立即阻止；显式 pattern prompt、critical override 必须人工确认。普通 exec tier、native allow 只是允许进入智能审查，不绕过审查模型。YOLO 不可关闭插件自身的安全下限。语法或执行上下文不在支持范围时转人工，无法明确呈现实际行为则阻止。
4. **运行模式与模型链。** manual 直接人工；smart 按下述主审/fallback 策略审查。有效 allow 只在低风险且用户授权充分时生效；ask 转人工；deny 阻止。
5. **执行前再次核验。** 完整参数、cwd、generation、会话、模型、相关 Settings 指纹均与审批时一致，重新运行原生下限判定。变化则废弃票据，重新审批或阻止，不沿用旧 allow。票据一次性消费后，最多调用一次 `ctx.invokeTool(params,{signal,onUpdate})`。

审批票据按会话与 toolCallId 绑定，并校验工具名。参数被后续钩子改写、延迟执行或重用 ID 时不得复用旧决定。不能只 hash command 而遗漏 timeout、cwd、运行模式或其它影响行为的参数。队列沿用现有每会话串行审查策略；取消、切模型、切会话、branch/shutdown、模式变化使未完成审批失效。原生结果与更新流直接转交，不把原生执行错误当作“审批失败”后自动重试执行。

多个插件同名注册/后续替换需要 fail-closed 检查。公开元数据不足以证明最终注册来源时，不报告 coverage ready。初始化尚未完成的窗口只允许阻止，不得临时 allow。

加载失败验证还显示：如果把执行包装与安全钩子拆成两个可独立加载的扩展，钩子扩展失败后包装仍能执行。这不是安全设计。生产版本必须把原生下限检查与执行放在同一插件、同一审批闭包中；执行函数强制要求钩子已捕获的有效票据，不能以“钩子没运行”当作通过。探针中的分离只是机制测试，不可照搬为产品。

## 执行模型、主动主审和备用模型

选择策略保持现有约定，执行模型与 reviewer 各自独立：

| 阶段 | 选择 | 后继条件 |
|---|---|---|
| 主审 | 显式 reviewer_model；未配置才使用当前会话模型 | 不支持传输、运行故障或无效响应才进入远程备用 |
| 远程备用 | 显式 remote_fallback_model，实际模型与主审去重 | 同类故障后才考虑本地备用 |
| 本地备用 | 已安装且有公开推理接口的本地模型 | 当前官方宿主没有 installed-only tiny 权限推理 API，保持 unavailable，不调用私有 worker/不下载 |
| 人工 | 审查不可用或有效 ask | 无 UI、取消或拒绝均不执行 |

有效 ask/deny 是决定，不是故障；不能通过不断 fallback 寻找 allow。Cursor OAuth 当前不受 reviewer 的标准 API-key transport 支持：如果主审=session 且当前执行 Cursor，就明确记录 unsupported，尝试已配置远程 GLM；显式 Kimi/GLM reviewer 则直接作为主审，远程备用仍是另一层。注册原生 bash 包装不改变这些选择规则，也不自动让 reviewer 获得 Cursor OAuth 能力。

审查请求包含完整命令、cwd、用户授权上下文、参数与影响执行的已知设置；不以命令字符串前缀代替模型判断。敏感输入沿用本地检查与人工路径，诊断不记录命令正文、用户消息、环境、密钥或推理输出。

## kernel 环境与原生高级能力

同名委托改善了原生执行能力的保留，但不意味着只检查裸 command 就能安全覆盖环境初始化与后台管理。startup 脚本、direnv 的可变外部资源、shell 配置、interceptor 与 worktree 等上下文必须纳入审查材料；无法通过公开接口捕获真实行为时不能假装已经透明覆盖。

首批支持 command/cwd/timeout 的普通前台命令。schema 从公开类型核对，未知字段显式失败；不要剥掉 async/service/PTY 参数后执行一个不同命令。当前 kernel 的默认设置应先做完整清单和 fixture 验证，避免为了“独立插件”重新造成默认环境下一律人工的历史问题。interceptor 可原样委托并验证其结果；auto-background、PTY、hub/reap 的完整语义分别验收后扩大支持。

公开 ToolDefinition 不暴露原生 Bash 的动态 concurrency 策略，首批不得声称所有调度语义与内建工具完全相同。高级命令可以在核对 schema、人工确认与安全性后放行；不能安全处理的参数明确阻止，而不是换用权限更弱的第二后端。

这仍是工具审批插件，不是 OS 沙箱。其它工具、MCP、子代理和程序内部行为不自动进入它的覆盖范围。

## 可观测性

`/permission-control status` 增加 entrypoints、nativeDelegateAvailable、scopedSettingsReady、coverage 状态与未支持能力；configuration ready 与 coverage ready 分开。保留 primary/remote/local/human 的模型身份、调用数和健康状态。

`explain` 显示最近一次来源与原因码，例如 NATIVE_DENY、NATIVE_PROMPT、PRIMARY_UNSUPPORTED、REMOTE_ALLOW、REVIEW_UNAVAILABLE、STALE_REVIEW、UNSUPPORTED_EXECUTION_CONTEXT。原生 gate 与插件人工询问的计数分别呈现，避免再次出现“smart 但计数全零，原因无法解释”。

## 实施分包与验收

| 顺序 | 修改范围 | 必须通过的验收 |
|---|---|---|
| 1 | specs/004-omp-permission-control 的独立插件修订、plan、tasks 与本方案 | 明确 native wrapper 与 raw 工具不同边界；消除“原生 bash 永远人工”的旧合同冲突 |
| 2 | 插件审批核心、原生包装、设置捕获、票据与单元测试 | allow 一次；deny/prompt 下限；双入口；未知参数；取消/切模型/设置变更；fallback ask/deny 停链；无 UI 阻止 |
| 3 | profile/schema/render、插件资产锁、status/explain 与管理器测试 | 未加载/加载失败/配置缺失均保护；不修改上游；不放宽资产和漂移检查 |
| 4 | 单独授权的隔离官方宿主 smoke | 人工确认 UI、真实原生 deny/prompt、参数传递、输出/退出码、取消/超时、kernel 默认上下文与同名注册冲突 |
| 5 | 有明确新预算的真实 Cursor smoke | native shell/stream/piBash 实际进入插件；无害复合读取自动批准；审查故障转人工；禁止样本不执行 |
| 6 | 用户已退出实例后的 plan/apply/doctor | 匹配插件与锁、保留账号/会话、确认 coverage 状态；不自动终止实例 |

默认测试继续使用临时 HOME、假模型和阻断网络，不启动真实宿主。真实 smoke 独立标记，跨平台、真实服务、高级能力未通过则保留“环境不足未验证”或“待实施”，不能计作通过。

先以可开关的 native wrapper 方式上线，保留 raw 入口。回退需要恢复匹配的插件、profile/schema、资产锁与部署记录，不能只替换一份运行文件造成受管漂移；无需更换宿主版本或覆盖私人数据库。

## 复现与本轮工作边界

严格检查：`/tmp/rotom-omp-build-inputs/workspace/node_modules/.bin/tsgo -p .cache/omp-wrapper-feasibility-20261002/host/tsconfig.json --pretty false`。

纯原型：`/tmp/rotom-omp-build-inputs/bin/bun test ./.cache/omp-wrapper-feasibility-20261002/prototype.test.ts`。

已授权的隔离宿主：`.venv/bin/python .cache/omp-wrapper-feasibility-20261002/host/run-proof.py`；需要真实宿主独立授权，不属于默认测试。fixture provider 只在 loopback，不使用账号或外部推理。

本轮已完成原型、可行性验证和方案文档；未修改生产插件、受管配方、依赖锁、本机配置或日常运行包。执行工作由 gpt-5.6-sol/medium 子代理完成，源码证据由 gpt-5.6-luna/medium 子代理搜集，主代理完成设置探针、隔离宿主验证和关键边界验收。

直接导入 Cursor 分派类的失败只限制此种探针方法，不是生产入口依赖；生产入口只需要已运行验证的 SDK、BashTool 和设置句柄。Cursor 是否实际经过包装最终仍须真实端到端验证，不能因源码推导而省略。
