# 宿主与运行包契约

> 本文保留宿主补丁方案的历史模型/契约。自2026-09-30起按不修改上游源码原则迁移，当前要求以[独立插件修订](../standalone-plugin.md)为准；不得继续依赖宿主bridge或私有接口。

本文件定义拟新增的 `permission-control/v1`，不是 OMP v18.3.0 已有 API。依据 [研究](../research.md)，扩展不覆盖原生 Bash，也不借 `invokeTool` 跳过原生判定。

## 注册与可信边界

宿主仅接受与受管 `/permissionControl` 中 `pluginId`、`pluginDigest`、`runtimeIdentity`、`bridgeAbi` 一致的扩展注册。`registerPermissionController` 的插件参数只声明固定 pluginId/ABI 和 review/command 函数；loader 从调用者实际加载路径与受管运行包核验并绑定 digest/runtimeIdentity，扩展不能通过自报字符串提升身份。一个会话只能有一个审查器；重复、版本不符、热重载或完整性失败先撤销未消费许可，再转 degraded。扩展代码和宿主属于同一可信计算边界，不声称能防恶意扩展在进程内绕过。

| 接口 | 输入 | 输出/约束 |
|---|---|---|
| `registerPermissionController` | plugin identity、ABI、异步 `review(request, services, signal)` handler | 会话级注册句柄；通过完整性检查才启用 |
| `services.reviewOnce` | 固定模型、脱敏有界输入、输出 schema、deadline | 单次独立推理；不暴露凭据，不接受工具或 fallback 链 |
| `services.tinyInstalledOnly` | 固定 local230m、脱敏有界输入、deadline | 不安装/下载的辅助结果；缺资源返回 unavailable |
| `services.setMode` | 来自真实用户会话命令的 smart/manual | 先递增 generation、取消 pending，再更新模式；工具/模型不能模拟调用 |
| 宿主内部许可消费 | 请求 ID、不可伪造的内存句柄、当前快照 | 校验并一次性消费；不对扩展公开任意字符串令牌入口 |

`review` 返回结构化决定候选与理由码。许可只能由宿主创建；候选 allow 本身没有执行能力。宿主强制硬边界、预算、模式、UI 能力和最后核验。扩展不能提供任意可执行回调或改写命令。

规则、请求校验和许可实体使用同一份受锁 TypeScript 纯核心。构建器与隔离测试 harness 把插件目录中明确列出的 `types.ts`、`shell-analysis.ts`、`policy.ts`、`reviewer.ts`、`controller.ts`、`session-commands.ts`、`audit.ts` 按原字节复制到宿主 `src/permission-control/core/`；不复制或执行扩展入口。插件树摘要绑定这些源码，构建脚本摘要绑定复制列表和步骤，receipt 同时绑定两者。最终构建输入因此是完整 patch series 加上这组受锁生成源码，不能只凭 patch 摘要声称闭包完整。宿主创建并私有持有 `PermissionLedger` 实例；候选审查 handler 得不到该实例、真实 UI 记录能力或任意 start 回调。

存在受管 `/permissionControl` 时，宿主保留 `/permission-control` 命令入口并将健康状态查询绑定到自身状态。扩展注册四个子命令的正常处理器；未加载/故障时，宿主的最小处理器仍可回答 status/explain 的 unavailable/无决定状态，拒绝 smart 生效并允许 manual 收紧。这样插件丢失不会把健康查询变成“命令不存在”。未选择功能的 profile 不注册该入口。原生命令输入必须有宿主确认的真实用户来源，不能由工具或合成 role 标记调用模式控制。

## 执行时序

1. 原有无副作用参数准备、interceptor、扩展 input 修改全部完成，验证最终 Bash 参数。调用补丁的纯 `prepareBashExecution`，冻结实际执行计划（见下节），不能仅冻结 raw args。原生提前 deny 可以短路，但不得提前自动 allow。
2. 建立唯一 request ID，锁定会话 generation 与该 Bash 请求的处理序列。保留原始字节用于本地核验，仅把允许发送的脱敏视图交给模型。
3. 宿主在有效 Settings 上运行原生审批，保留结果和来源。显式 deny、命令级 prompt、critical 检查不得被 YOLO 抹掉。完整解析的 compound 简单命令逐个通过同一原生匹配器；仅有结构性 compound prompt 不等于必须人工。
4. deny 结束；command-prompt/critical/无法识别的来源强制人工。其它请求进入确定性低风险判定；只有完整可分析、上下文充分的 smart 请求进入独立主审。
5. 按 [模型策略](review-decision.md) 得到 allow/ask/deny。manual 不调用模型。故障只收紧；fallback 严格限权。
6. ask 只走一次原生 UI，展示完整待执行动作（遮蔽秘密）、来源与短原因。不提供永久允许前缀或自动改规则选项。无 UI 返回 blocked；用户拒绝保持 denied，取消保持 cancelled，不重试模型翻转。
7. 模型 allow 或用户本次批准后，可 stage 本次所需、尚未启动的 artifact/job 资源。随后重新核对参数、会话、授权、规则、模式、模型、运行包/插件健康、shell/cwd、目标状态指纹。变化则撤销并清理尚未启动资源，作为新请求重新判定，不能沿用前次批准。
8. 以同步临界区消费许可并调用 `commitPreparedBashExecution`，其间不再 await、不运行改 input 的 hook。commit 使用已核验计划调用原生 backend，不重新进入会改 command/cwd/env 的整套 BashTool.execute 前处理。实际执行恰好一次；执行错误不自动换工具或包装命令重试。

wrapper 对步骤 8 的有效许可跳过同一次默认 prompt；硬规则已在步骤 3 生效。不得先产生副作用再审批；首版禁用跨请求批准缓存。

## 授权证据的宿主边界

自然语言授权的语义由主审结合完整真实用户上下文判断，包括每个 effect 是否被覆盖以及之后的限制、撤销或冲突。宿主只承担可机械验证的部分：消息来自真实用户输入通道、完整相关上下文已提供、逐 effect 原文引文和实际对象/参数/cwd/执行上下文绑定有效、generation 未变化、固定风险下限和原生规则仍满足。宿主不能独立证明任意自然语言蕴含，也不得把有效 message ID、严格 JSON 或引文字节合法宣称为语义正确保证。本接口不要求固定用户句式，也不新增授权范围命令或长期授权对象。

主审 `evidence` 恰有 `userMessageIds` 与 `bindings`。每个 binding 恰有 `effectId`、`userMessageId`、`startByte`、`endByte`、`scopeDigest`；ask/deny 的 bindings 可以为空，模型 allow 时每个输入 effect 恰好一项且 bindings 非空。宿主验证 ID 均来自本次输入、消息 ID 已列入 userMessageIds 且没有无引用 ID，UTF-8 半开字节区间非负、start<end、未越界并落在字符边界。`scopeDigest` 是宿主为真实 effect 的种类、规范目标、完整参数、cwd 和执行上下文生成并随输入提供的会话盐 SHA-256；它只作绑定摘要，不是授权令牌。重复/遗漏 effect、伪造或越界引文、摘要对应另一对象/参数/cwd、超输出预算或无法完整表达都使 model allow 无效并转 ask，不拆成多次推理；合法 ask/deny 的空 bindings 不属于 invalid-output，不触发 tiny。

主审收到相关真实用户消息的完整脱敏内容，不能只有它自己挑出的引文；更晚限制、撤销与冲突必须包含，脱敏或 24 KiB 输入预算使语义不完整时 ask。用户限制状态 `clear|conflicting|unknown` 绑定当前 generation：上下文完整、没有待解释用户自由文本且结构化限制机械检查全通过才是 clear，已知结构化限制冲突是 conflicting，其余包括自由文本或缺上下文是 unknown。只有 clear 可走确定性受限只读；conflicting 必须人工或由原生规则 deny，不能交主审覆盖；只有 unknown 在 smart 可进入本次唯一主审解释，manual 转人工。模型判断只适用于当前请求，不缓存为后续默认 clear 或授权。固定策略另外阻止写入/删除、网络发送、凭据/秘密或设备访问仅因 model low 自动 allow，未知 effect 保持 ask。

## 最终执行计划与首版覆盖条件

`PreparedBashExecution` 是宿主持有的不可变对象：request/session/generation、最终 tool args、最终 command 字节、规范 cwd、shell 路径/摘要/启动选项、backend、有效环境的本地摘要、prefix、前台/PTY/service/async标志、相关目标指纹、全部延迟效果及准备算法版本。环境秘密只在原生执行上下文中持有，不发送给模型；摘要用会话盐且不输出可逆正文。

首版自动批准可完全准备的前台 native backend，包括其原生自动后台管理。显式 service/name/ready/env、async、pty、ACP terminal、实际需加载而不能冻结的 direnv/devenv、非空 shell prefix、useUserShell/未知启动脚本、BASH_ENV 或未核实导出函数影响、内部 URL 与未核实 worktree rewrite，仍不在智能覆盖。interceptor 未命中、自动后台开关开启和 direnv 自动检测本身不能作为笼统人工原因。纯准备不得创建 URL 父目录、加载环境脚本、启动 daemon/job，或先执行探测 shell。

上述不支持路径仍先检查原生 deny，再通过原生人工 UI 审批完整请求及环境副作用类别，无 UI 阻止；不产生插件 smart permit。人工授权只适用于已绑定的原生请求/配置快照，不把未知展开冒充已审查字节。将来扩大这类路径的自动批准，必须先使最终 plan 可无副作用准备与原样消费，再增加独立验收。

智能路径的确定性 cwd/参数变换在 prepare 内做一次；原生检查同时覆盖原始请求和实际计划，任何一者 deny/mandatory 都不能被变换隐藏。模型收到最终命令及必要的变换说明。commit 不重算 prefix/direnv/URL/cwd，不执行新的 discovery；最终核验后 backend 只能消费同一计划。若现有 native backend 无法接受冻结计划，补丁必须补齐该入口，不能退回 raw command execute 并声称 FR-034 完成。

不静默改用户环境以凑覆盖。若 kernel 实际设置启用这些行为，status 展示具体不覆盖原因，相关操作人工；这可能影响免询问指标，应如实计入固定样本结果。

### 默认 kernel 兼容扩展（用户于实施时明确选择）

- 保留原纯 interceptor 对原请求及确定性变换后的检查。命中时返回原来的无执行引导结果；未命中继续准备，不能因为功能开启而一律人工。原生 deny 仍优先。
- Bash 冷启动 snapshot 的 rc 执行属于本次人工审批范围，不在纯 prepare 偷跑。初始化后，只有宿主能把生成输入、snapshot 摘要、相关名称解析/options、实际 Shell 实例与后续状态连续性联系起来，才可复用已初始化环境进入后续智能审批。必须核实会实际调用的名字；无关且未被调用的函数存在不能单独作为全局阻断理由。缓存路径存在或元数据相同不能替代 native 状态证据。未知 mutation/未跟踪执行使证明失效，不自动重置 Shell 来掩盖状态。
- direnv 自动模式可在纯文件读取证明完整搜索链没有有效配置时判为无动态加载；文件/祖先路径漂移必须失效。实际加载或已导入环境缺少完整证明时仍人工。
- auto-background 保留原有 manager、artifact、前台等待阈值、后台结果和清理行为。新增本次批准后的资源 stage，只准备尚未启动的资源；不能调用会立即执行 `run()` 的注册 API 冒充纯 prepare。最终同步区重新验证、消费许可并启动冻结 native 请求；若现有 manager 无安全启动边界，须新增内部 reservation/start 接口或等价分割，不能在 consume 后再 await artifact 或重新运行 Bash 前处理。
- stage 取消/失败/漂移清理未启动资源，不启动 backend，也不复用批准重试。已有 ask→human 来源链保留。stage 属于自动处理预算，人工等待仍排除；状态查询显示初始化/资源准备/降级的固定原因，不暴露 snapshot/环境正文。
- 新增默认设置兼容测试组，既验证前台完成，也验证超阈值后台与取消；使用真实 patched 函数、假 native/clock/job 边界。既有冻结240条样本保持不变，真实宿主语义仍需 T072 独立证据。

## 来源分类与不变量

| 原生来源 | smart | manual | 插件不健康 |
|---|---|---|---|
| explicit-deny | deny | deny | deny |
| command-prompt / critical-safety / 未知来源 | 人工或无 UI 阻止 | 同左 | 同左 |
| native-allow | 仍须已知低风险或完整审查 | 已知低风险才自动 | 回到受保护的原生流程 |
| tool-default / tier-default / compound-structural | 可委派完整审查 | 已知安全之外人工 | 原生人工或无 UI 阻止 |

受管基线保留 `tools.approval.bash=prompt`，禁止 yolo。运行中若保护基线被改弱，bridge 撤销 pending、降级并强制受控 Bash ask/无 UI blocked；不能靠宽松原生状态放行。选插件而运行包没有 ABI 时管理器启动检查失败，退出 5。

同名工具被覆盖、运行身份不能核实、目标状态无法枚举时不启用智能放行。插件消失时 native prompt 仍在；移除/回滚须同步删除其受管对象/选择，不能遗留 bash allow。

## 并发、恢复、取消

- generation 在模式、模型、授权消息、策略、健康、session 切换/恢复时递增；响应到达及执行前均检查。
- 每会话仅一个 Bash 操作处于审查至发起执行过程；排队请求不继承前一请求授权或 cwd。其它工具造成目标变化也会使最后核验失败。
- 取消立即撤销执行资格并传递 abort；即使网络/worker 不能立即停止，1 秒内请求也进入不可执行状态。已开始的原生进程依原生机制取消，不声称撤回已有副作用。
- 自动总预算 30 秒从开始构造审查上下文起算，包含预处理、资源检查、全部模型等待，不含请求开始前排队与人工等待；主审最多 25 秒，tiny 只用剩余最多 5 秒。deadline 后转人工/阻止，迟到结果丢弃。
- 最终核验前目标变化必须重审。对于外部进程恰在系统调用窗口改文件，本插件不提供 OS 级原子隔离；不能稳定识别效果或目标的动作不自动批准。
- 恢复会话只恢复脱敏审计，读取配方默认；不得从审计恢复 mode、permit 或 pending。

## 未覆盖入口

首版仅 Linux 主会话 Bash 智能判定。其它 Shell、平台和 child session 不注册智能许可；子会话不能消费主会话 permit，也不能通过继承 yolo 免掉原生保护。选择本功能的 kernel 为 task、eval 设置原生 prompt；没有安全人工回路的委派阻止，无 UI prompt 永不自动批准。MCP、Python 等保持原生审批，不扩大 allow 范围。

这不是所有工具的统一安全沙箱。用户批准独立入口不意味着它由插件审查；status 必须区分。插件不会在 Bash 拒绝后自动改用 eval、子代理或包装执行。

## 运行包交付

| 输入/资产 | 所属位置与要求 |
|---|---|
| 官方基线 | `locks/omp/manifest.json`、`locks/omp/upstream/` 保留官方来源语义 |
| 补丁 | `agents/omp/patches/permission-control/` 有序 series、来源、bridge/installed-only 补丁和隔离测试 |
| 构建输入契约 | `schemas/omp-permission-build-inputs.schema.json` 与 `agents/omp/patches/permission-control/build-inputs.lock.json`，独立封闭上游源、依赖锁、工具和离线依赖产物身份 |
| 构建入口 | `agents/omp/build-permission-control.py`，维护者显式调用，无自动工具链安装 |
| 构建 receipt | `locks/omp/permission-control/build-receipt.json`，真实完整输入/工具链/平台/输出摘要 |
| 补丁锁 | `locks/omp/permission-control/manifest.json`，独立严格 schema，含基线身份、补丁/构建/插件身份、ABI、平台资产 |
| 本地二进制 | 私人内容寻址 artifact cache；Git 不存大二进制或机器绝对路径 |
| 部署产物 | 既有 cache 的 `runtimes/<combined-identity>/bin/omp`、packages、receipt，沿用 stage/租约/恢复 |

combined identity 包含官方锁、补丁锁、平台及实际插件树身份。`runtime_variant=official` 不要求补丁锁；`permission-control-v1` 必须存在对应平台资产与 ABI。首版资产 Linux glibc x64；Linux arm64/其它平台只有单独构建验证后登记。缺平台资产退出 5，不自动切官方 smart。

补丁 manifest 封闭字段为 `schemaVersion`、`variant`、`upstreamIdentity`、`bridgeAbi`、`patches`、`buildReceiptDigest`、`pluginDigest`、`assets`、`identity`。`patches` 为有序的相对 path/SHA256 数组；`assets` 按平台存 `cacheKey`、`sha256`、`size`。`identity` 为去掉自身后规范化 JSON 的 SHA256，不引入自引用哈希。cacheKey 只能是按摘要形成的相对键；拒绝绝对路径、`..`、符号链接和目录逃逸。receipt 保存完整工具链/依赖来源；其摘要与 manifest 交叉核验。combined runtime identity 在 manifest 外计算，并写入运行包 receipt/生成配置，避免循环身份。

拟新增 `agentcfg lock --agent omp --runtime-variant permission-control-v1 --artifact-cache <已准备目录>`，消费已有有效 receipt/资产/构建材料，更新独立补丁锁；普通官方 lock 保持原语义。`--artifact-cache` 仅供这一维护命令验证产物，路径不写入公开锁；日常 sync 从该 profile 已配置 OMP cache 的 artifact 区消费同摘要资产。维护者须显式把构建结果供应到目标 cache，缺资产报错，不搜索全局目录。参数严格校验，不能在 run 覆写已部署身份。锁内仅存相对 content-addressed key，不增任意脚本下载入口。

build-inputs lock 顶层只允许 `schemaVersion`、`platform`、`upstreamSource`、`dependencyLock`、`tools`、`dependencyArtifacts`。`upstreamSource` 必含 commit 与 archive SHA256；`dependencyLock` 必含仓库相对 path 与 SHA256；每个 tool 必含 name、version、相对内容寻址 cacheKey 与 SHA256；每个 dependency artifact 必含相对 cacheKey、SHA256 与 size。所有对象拒绝未知字段；cacheKey 拒绝绝对路径、`..`、符号链接和目录逃逸。清单必须完整枚举依赖解析与离线安装所需资源，构建器拒绝缺失、额外未声明、版本/摘要/大小不符的输入，不猜值、不搜索全局安装、不隐式下载。

基础 Bun 身份在构建前只取自该独立输入清单；receipt 是产出，生成后才能与输入清单交叉核验，不能倒置为工具身份来源。build-inputs 只引用原始上游源、工具与依赖，不引用 official recipe identity、补丁锁 identity、receipt、asset 或 combined identity，避免哈希循环。显式构建脚本从已准备且逐项校验的 source/tool/dependency cache 生成 standalone；供应和可能联网获取另行显式维护，不进入日常 sync。纯 Python 的 schema、闭包和路径边界验证不依赖 Bun，可在工具链不足时继续；构建成功不等于 smoke 成功。

最终锁定顺序为：先稳定所有源、patch、插件与 recipe 输入字节并更新 official recipe identity；再以该 identity 和独立 build-inputs lock 构建并生成 receipt/补丁锁；最后由 official lock identity、patched lock identity、platform 与实际 plugin tree 计算 manifest 外 combined runtime identity。official recipe identity 更新后若任何受锁输入变化，必须废弃后续 receipt、补丁锁及 combined identity 并按顺序重新生成，禁止手改摘要。

sync 仅从锁定本地 artifact cache 复制补丁资产，不回退下载官方包；apply、run、rollback 沿用现有边界。退出码保持 2 配置/锁、3 必需凭据、4 所有权/活动/恢复、5 缺依赖/不兼容、6 文件系统/内部故障；会话 ask/deny 是工具决定，不是管理器退出码。

## 验证要求

隔离测试必须把完整有序 patch series 干净应用到 build-inputs 锁定的上游源码，覆盖该最终源码上的 bridge 逻辑及真实 wrapper/prepare/commit/installed-only 集成函数，使用假 Settings/UI/provider/execute，不启动 CLI/TUI/真实 worker。不能只测与补丁无关的 fake bridge。检验 ABI、默认流程等价、硬规则、无重复 UI、单次消费、迟到/目标漂移、installed-only 的网络/安装/标题 worker 哨兵。为 mkdir、direnv、service/job 和 backend 调用设置副作用哨兵：批准前均为0，批准后实参必须逐字节等于 prepared plan，不能在 execute 中再重写。最终回归还必须运行完整 bridge TypeScript 组和 `tests/test_omp_permission_control.py`、`tests/test_omp_permission_runtime.py` 两个 Python suite harness，并先核对最终源码、series、输入锁、official/patched lock、receipt、plugin tree 与 combined identity 一致。

交付前独立核验实际 patched standalone 身份与加载；真实宿主 smoke、模型调用各需对应授权和结果。只有源码测试无实际运行包时，不能宣称 kernel 可用。

### 宿主服务的请求身份与观测接口

- `buildReviewRequest(input, clock, {requestId, startedAt})` 接收宿主在上下文处理开始前固定的请求 ID 与单调时钟起点；该 ID 与 prepared plan、ledger、SDK 单次请求账本一致。不能在 shell/文件证据收集结束后重新开始 30 秒预算。
- `reviewOnce` / `tinyInstalledOnly` 在即将发出实际推理时调用该请求的 `onInferenceStarted()`，资源检查、unsupported 或 installed-only 缺资源不调用。回调拒绝重复、取消和过期请求；SDK/fetch 仍须自行保证没有隐式 retry 或 fallback，不能把回调计数当作底层计数证明。
- loader 只接受固定 `pluginId`/`bridgeAbi` 与 `review`/`command` 处理器；实际插件树摘要、入口路径和运行身份由宿主核验绑定。`command` 仅由宿主认证的控制输入调用，收到的窄服务只有 snapshot/explain/setMode；不公开 ledger、recordHuman、permit 或 backend callback。
- 宿主 minimal shim 复用受锁纯 `session-commands.ts`，审计复用 `audit.ts`；与其它 core 文件一样由构建器明确复制。没有扩展时查询仍能报告 unavailable，manual 仍可收紧。

### 提前拒绝与人工等待审计

原生解析已deny且尚未native prepare时，宿主仅建立保守的拒绝审计关联计划：覆盖为manual-required/unknown-target，不作为真实执行来源证明，不调用native prepare/stage/commit，不产生许可。pre/effective/final原生deny均不可由参数改写或缺失来源metadata降为prompt/allow。ask在等待UI前记录；无UI、取消或等待抛错仍保留该决定，后续human与permit生命周期记录关联同一ask，审计失败不扩大执行资格。
