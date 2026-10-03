# OMP permission-control 真实宿主 smoke

当前独立插件宿主验收见[Phase 12](omp-permission-control.md#phase-12官方-omp-与独立插件2026-09-30当前交付)与[独立证据](omp-permission-control-standalone-evidence.json)；以下保留历史补丁宿主记录。

> 当前已按维护者要求改为官方宿主与独立插件，仓库实现及隔离验收完成；本机日常实例已按后续明确授权完成独立插件迁移（见验收 Phase 13）。下文 patched runtime/bridge 的构建和验收为历史记录，不继续构建发布，也不作为新插件通过证据。当前需求见[独立插件修订](../../specs/004-omp-permission-control/standalone-plugin.md)。本机部署是否切换须单独登记。

日期：2026-09-29。用户已明确授权尝试真实宿主；本轮先执行无付费模型 smoke，少量真实模型调用另行征询，不等同于 T073 的冻结样本评测。

## 当前状态

**当前 Phase 11 新运行包的限定宿主复验已通过**：Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。 历史结果保留在下文；本轮明细见文末Phase 11。

下列早期观察和失败定位保留为历史；最终身份与结果见文末“最终交付与验收”。日常本机 OMP 配置未写入。

## 初始无付费阶段环境与范围

- 仓库 profile：`omp-kernel`，正式 asset SHA-256 `a2ba1be6269f2874b9475687acbc39fa148ec1f3fa836e214c6481feee632d2a`，combined runtime `357acc7e1fb9d16dd14b29d77d6cff9decf69b335f856e4f622205c960107f01`。
- 独立实例/机器配置/缓存：`/tmp/rotom-permission-host-smoke-20260929`。全部使用空凭据与虚构 endpoint；清空继承环境，Linux seccomp 阻断网络。
- 工作目录：`/var/tmp/rotom-permission-smoke-work-20260929`。原 `/tmp` 祖先已有 `.omp` 来源被管理器正确拒绝（退出 4）；保留该既有目录，改用全新私有工作目录。
- 管理器实际 sync、plan、apply 成功；首次 smoke 自建 artifact 父目录不是 0700，修正临时目录权限后成功，未放宽生产安全检查。sandbox UID 映射会误报本地文件所有权，因此这些真实步骤在授权的执行环境运行。
- 不修改日常本机 OMP 配置；没有真实 provider 调用或 tiny 下载。

## 初始观察结果（修复前）

| 检查 | 实际结果 |
|---|---|
| manager run 启动最终 standalone | OMP v18.3.0 TUI 真实启动 |
| `/permission-control status` | `bridge.health=healthy`、`identityVerified=true`、ABI `permission-control/v1`；默认 smart/profile-default |
| manual/smart 切换 | mode-updated、generation 递增；status 显示对应模式与 session-command 来源 |
| explain 无决定 | `no-decision-in-session` |
| 缺 tiny | `fallbackHealth=unavailable`，保留 installed-only/never-allow 限制 |
| 手工 `!pwd` 两次 | 真实 native Shell 均返回指定临时工作目录；此入口绕过工具审批，不能作为 permit/自动放行/无重复 prompt 证据 |
| `/new` | 会话 ID 确实变化，但 activeMode 仍为 manual、modeSource 仍为 session-command；违反临时模式不跨会话继承的约定 |

旧会话 ID `01a0ed79-a96c-768a-9d1e-e6999582587b`，新会话 ID `01a0ed7c-7d87-71d4-83b4-fb16112a93f2`。新会话 status generation=9、configuredMode=smart，却 activeMode=manual。证据保存在临时 `interactive-evidence.txt`；宿主 `/exit` 正常退出 0。退出码仅用于记录进程结束，不替代功能证据。

## 当时待验证项（后续结果见文末）

修复 new/resume 生命周期后重新生成正式补丁、构建及身份，再复测。真实工具审批仍需由模型发出工具调用；手工 `!pwd` 不能代替。插件缺失、恢复、回滚检查及真实模型请求范围按后续实际结果追加。

## 插件缺失保护

宿主退出后，只在本次私有 runtime 暂移 `packages/omp-permission-control/index.ts`，再通过同一 `agentcfg run` 入口启动：真实返回退出码 **5**、提示“当前部署的运行包缺失或损坏”；未出现 OMP TUI。`finally` 恢复入口原文件。该结果证明管理器启动前的交付故障关闭，不代替宿主内 degraded status。日志 `missing-plugin.log`。

## 生命周期缺陷根因与修复方向

实际 `/new` 由内置 command controller 调用 `AgentSession.newSession()`，未经过扩展 command-context 的 newSession 包装器；当前重置逻辑仅在包装器里。真实 committed `session_switch` 事件没有触发 ledger 重建，且缺少外部 handler 时 before 事件可能被跳过。修复将由宿主内部订阅保证 before 阶段撤销许可、committed post 阶段按新 session 重建；取消切换只撤销许可，不改变原模式；扩展包装器保留单次 fallback，避免双重重置。正在补充真实事件路径反例与验证。

恢复插件原字节后再次通过 manager run 启动，status 为 healthy/identityVerified=true、smart/profile-default，证明临时损坏可恢复。未持久化的空会话 ID 无法 resume，UI 正确报 not found，当前 manual 状态不变；这不作为成功恢复会话证据。

为生成可恢复的真实会话，向断网、虚构 endpoint 的实例提交一次“只回复 OK、不调用工具”的普通消息。主代理请求按 kernel 原有 fallback 链尝试后均报 `ENOTFOUND smoke.example.invalid`，随后取消并正常退出；没有成功的网络请求、模型推理或工具执行。该过程是普通主模型失败路径，未进入权限审查，不拿其耗时评价权限审查的 30 秒预算。产生的持久化会话 `01a0ed7f-4a1c-76f3-b3bd-4d5975848cc9` 将用于修复后 resume 验证。

## 生命周期修复后的实际验证

- 0001 更新为 `b0c5dcb77a82b42f251c3a937d7b02cde59bcb1d43a3f613f519f7f3ecdad7c6`。源码事件回归先红后绿：30 bridge tests / 245 assertions；fresh coding-agent strict tsgo 和定向 oxlint 通过。
- 实际重新离线构建并发布：asset `e4071c28800a5a2f35460c156d8660e3e66e50dc4d8461db743ab1993abc9772`，367264968 bytes；patched manifest `e8f901b220af740a785d1422bdaf05d7af449f700854794c12e622e1e5dcba91`；receipt `11aacb8aec3bd87511080f4b300cc7831463153af4ed57d1a6001b3e0991cee9`；combined runtime `c2ddebe42741fe49b7ac5e87d24b3df9e42f85150f8bfaad80b83f732fec4ea3`。official/plugin 身份未变。
- 同一真实 PTY 回归旧资产稳定失败；新资产 **通过**：manual→new 与 manual→resume 均恢复 smart/profile-default，pending none，bridge healthy/identityVerified=true，explain no-decision，正常退出 0。
- 新身份受影响回归命令：`.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_runtime.py tests/test_omp_kernel.py --omp-build-source /tmp/rotom-omp-plan/commit.tar.gz --omp-tool-cache /tmp/rotom-omp-build-inputs/tools --omp-dependency-cache /tmp/rotom-omp-build-inputs/dependencies`，**103 passed in 99.66s**，没有跳过。未改变其它适配器生产逻辑，因此不重复已通过的无关组。

## 最多三次真实模型请求

用户单独明确授权“允许最多 3 次无害模型请求”。只读本机既有主模型配置确认 `kimi_tf/kimi-for-coding` 与凭据可用；凭据仅在转发器进程内存，未复制到隔离 OMP。临时实例使用 loopback endpoint 与无价值 dummy key；为控制费用，临时禁用跨模型 fallback、主模型思考 off、每次输出最多 2048 tokens。转发器只接受固定模型与路径，实际出站前计数、硬上限 3，不重试、不跟随跳转，不记录请求正文、地址或密钥；错误响应仅返回固定代码。

实际出站 **3 次**：第一请求产生同批 `pwd`、`ls` 两个工具调用，第二请求为完成总结，第三请求为独立暖态 `pwd`。三次均收到模型输出；SDK 在消费完成后关闭 SSE，relay 记录 CLIENT_DISCONNECTED/499，不据该本地转发状态误判为没有发生推理。后续总结请求在本地返回 `400 RELAY_BUDGET_EXHAUSTED`，实际出站数保持 3。这不是 T073 的冻结样本评测。

三条工具均各出现一次人工审批、各执行一次，并各有两条审计：ask/human allow/permit pending→consumed；没有命令改写、二次审批或重复执行。手工输入 status 的 Enter 在 modal 中实际确认了第一条 pwd，随后明确确认 ls；记录审批行为，不将该输入当作 out-of-band status 已验证。

三条命令均为 `coverage=manual-required`、`coverage_reasons=[startup-script]`、`primary_calls=0`、`tiny_calls=0`。前两条同批调用可由冷态计划提前冻结解释，但所有任务完成后独立第三条 pwd 仍如此，不能用并行时序解释实际暖态结果。当前正用无模型真实 Bash 诊断继续定位；**尚未证明真实智能自动 allow**。模型自身总结“Smoke test passed”不作为验收证据。

结构化结果见[本轮证据](omp-permission-control-host-smoke-evidence.json)。真实 OMP 已 `/exit` 退出，relay 已停止；不会追加付费调用。

## 临时实例真实回滚

停止宿主与 relay 后，恢复 smoke 机器文件的离线 endpoint/空凭据，再执行真实 `agentcfg --local <smoke>/machine.toml --profile omp-kernel rollback`，退出 0、restored=4。实际 config 恢复 profile smart 与原 modelFallback=true，临时 dummy key 被移除，pending.json 不存在。只回滚本次临时实例；日常用户配置未写入。

## 独立暖态证明失败的真实根因

执行器的快照分析白名单只有 `expand_aliases`，而干净 Bash 默认启用 `cmdhist`、`complete_fullquote`、`extquote`、`force_fignore`、`hostcomplete`、`interactive_comments`、`progcomp`、`promptvars`、`sourcepath`。真实生成快照因此始终 `optionsKnownSafe=false`，首条命令完成后 continuity 不能保留。已在仅 HOME/TMP/PATH/LANG 的干净环境、断网、锁定 Bun 与真实 native 中复现，排除用户 rc/env；没有打印环境正文。此前“同批提前冻结”只解释第一批的第二条，不能解释后续独立暖态调用，不能作为最终根因。

已决定最小修复：显式列入上述不影响已支持纯读语法的默认选项，未知选项继续转人工；同时使函数声明头和单独左花括号接受 Bash `declare -f` 的尾部 ASCII 空格，不放宽函数体、影子命令或动态语法。新增生成格式反例、真实 native 暖态回归；默认隔离测试仍不启动宿主，真实 native 只作为本次显式 smoke。之后重新构建实际资产再验证。


## 暖态修复后验证（中间轮次）

- 0001 SHA `b31de2a3db8d1d0540da18f73aac6268402ebdb94a84fa510b116029042761de`；离线 standalone `95076aa2e3a4de29ff43d846474a9f03e30f2ce720d5414c75a2c9278a047684`，367264968 bytes；combined runtime `fa94bd4c6db06a16526f4b84624cdec4af1be145ea2bbd50d59fee0bc1ece15b`。
- 干净环境真实 native Bash：初次执行建立 continuity，后续 prepare reasons=[]，generation 1→2。bridge 30 tests/248 assertions，fresh strict TypeScript、oxlint/oxfmt、pristine 完整补丁应用均通过。
- 最终受影响三组 pytest 使用前述完整 material flags：**103 passed in 98.01s**。沙箱 UID 映射导致20项属主检查误报，改用已授权的真实身份执行相同命令后全部通过；未放宽安全哨兵。
- 该资产真实 TUI lifecycle 复测：new/resume 恢复 smart/profile-default、healthy/identityVerified=true、pending none，退出0。
- 新建只监听 loopback 的固定响应 provider，不含网络客户端，不读取凭据或本机配置。实际 OMP main 从其获得一个 pwd 工具调用；`!pwd` 只预热 Shell，不作为审批证据。此次工具已 `coverage=eligible`、reasons=[]，证明 shopt 修复有效；但在向审查服务发出请求之前转 `POLICY_MISMATCH`，primary_calls=0。结束时 Ctrl-C 拒绝该询问，工具返回 `PERMISSION_CONTROL_DENIED_BY_USER`，没有以手动确认冒充自动放行。
- 此次固定响应总计2次 main 请求、0次 review、0次外部模型请求。仅凭“Done.”不算通过，继续定位审查入口问题。


## 审查入口提前取消根因

断网真实插件注册诊断表明：mode=smart、restriction=unknown、唯一 read/low effect、tool-default/prompt、2924-byte envelope、未超时、generation一致、signal未取消，全部入口条件满足。插件实际调用服务一次，但宿主 transport 立即返回 cancelled，实际 inference/fetch 计数仍为0。

宿主准备 transport 时固定 `primaryDeadline = startedAt + 25s`；真实插件稍后计算 `min(overallDeadline, now + 25s)`，因此通常比 transport 已绑定的截止时间更晚。transport 正确拒绝越界 deadline，最终转人工。替身 controller 没有重现真实插件的时钟计算，故早期测试漏检。修复约束为在 runner 交给 boundPrimary 前钳制到两者最早截止时间；不放宽 transport 的身份、输入、次数或上限检查，保留总体30秒与tiny剩余时间。修复后需重新构建并跑真实固定响应 smoke。


截止时间修复回归：移除钳制时 bridge 30 pass/1 fail，新增用例稳定转人工；修复后31 pass/253 assertions，fetch=1、prompt=0、start=1、consumed=1。用例使用 stage_permission_core 的生产 reviewWithFallback 字节和完整插件树身份，注册 descriptor 由测试组装；真实动态插件加载仍由 standalone smoke 覆盖。fresh 完整 series、coding-agent strict tsgo、定向 oxlint/oxfmt 和 pristine apply-check 通过。0001 SHA `b9c597b0f60c6e2b58855828602cf65495b79715664a25047d28d49677faaaf6`；bridge 用例格式化后的 SHA `232fdeb3001a3196f1db28ee9138f4ee1738e8c8dfbb25486f3b1f3339228b8d`。

最终二进制重建首次退出6（通用输入/输出失败）；当时 /tmp 可用2.8GB，fresh依赖树约2.1GB，存在空间压力。改用仓库忽略的私有 cache 临时目录重试，不修改源码、receipt规则或输入材料。没有把首次失败记为通过。


## 最终交付与验收

最终离线构建改用仓库忽略的私有临时 cache 后成功；构建网络仍由 Linux seccomp 阻断，receipt 标记 hostExecuted=false，宿主运行由后续 smoke 单独证明。

| 身份 | 最终实际值 |
|---|---|
| 0001 patch | `b9c597b0f60c6e2b58855828602cf65495b79715664a25047d28d49677faaaf6` |
| standalone SHA-256 | `da436eff28dab0d72249e5a3c69f7e3f56e693f6b739e3069ac11fa274e66f83` |
| standalone size | 367264968 bytes |
| patched manifest | `7c6caa302f43d5c8637aa3b58383c01d65f5bbf55df329f8580a97d1f42d3bbb` |
| build receipt | `9b77413bc042be76b46e57dd1b7a6b9b9ed3da3424f8693f3cd17ad56c1cbb1c` |
| combined runtime | `bf6f18b45fc80c177f6644e96366b978bb3d524b0d476664d228e4a7de48bc08` |

official recipe `0504c78b719146cf72ad2030940002d4fd06f52c2a6b6031b102f8c0e3c50be9`、plugin `203d1d0bb14f65fad52888b23e05361f2e6b6c428334863b71b34eb2703997a8`、0002与独立构建输入保持原字节，按实际构建重新生成正式锁。最终受影响回归 **103 passed in 92.46s**；完整参数同前，最终使用安全的 `/tmp/rotom-permission-final-pytest-review-2` basetemp。尝试仓库cache作pytest基目录时，20项按设计拒绝 `/data` 的777非sticky祖先；未修改所有权检查，改回安全临时根后通过。

| 最终实际检查 | 结果 |
|---|---|
| 同一最终资产 manager sync/plan/apply/run | 成功，bridge healthy、identityVerified=true |
| manual→new、manual→resume | 均恢复 smart/profile-default，pending none；explain无旧决定 |
| 自动工具许可 | 固定provider一轮2个main响应+1个review响应；warm Bash的pwd仅执行一次，无人工确认 |
| 审计与explain | 同一决定 allow/reviewer/LOW_RISK_AUTHORIZED，coverage eligible、reasons=[]，primary_calls=1、tiny_calls=0；permit pending→consumed；无human字段，唯一toolResult成功；explain显示consumed |
| 缺失插件 | 暂移本次runtime入口后manager run退出5，未启动TUI；finally恢复完全相同字节 |
| 回滚 | 真实rollback退出0，restored=4；smart、modelFallback=true，dummy key已去除，无pending.json |
| 收尾 | OMP退出0，付费relay和固定provider均停止；日常OMP配置未修改 |

固定provider严格接受目标临时目录中的单个pwd/read/low effect，以及按顺序的两条已知消息 `!pwd` 和明确的pwd授权；scopeDigest/effectId/messageId/UTF-8引用均绑定实际信封，仍由宿主严格解码校验。最初fixture错误要求只有一条消息，因宿主正确保留预热输入而拒绝；仅修正fixture到上述精确两条消息，未放宽生产代码。第一次许可实际成功后，脚本因TUI自动换行拆开reasonCode而误判；修正显示解析后完整复跑成功。固定服务最终计数累计4个main+2个review（两轮成功），最后一轮为2+1；不将本地fixture请求算成真实模型推理。

实际执行模型：两名 executor 均为 `gpt-5.6-sol / medium`；主代理作方案决定、最终产物与真实宿主验收。完整冻结样本真实模型质量、真实tiny推理及其它平台仍未验证。`status.unverified` 的保守静态声明未修改，不把当前这一台机器的报告推广为其它安装的证明。

## 2026-09-30 评测工具修正后的交付复核

真实评测前修正 evaluation runner 的14条机械故障注入及输入effect指标说明；生产reviewer/policy和两项host patch未变。新asset `cacb2a43945f8e05a25986208d7cc672afd8f1032ad17a834ff8e1e2e7dc8c7c`、runtime identity `28e85f1f871fabd39fbf3882f654c630df53ce384a4e851ec688e439358e3107` 已在隔离HOME通过真实OMP加载与lifecycle：bridge健康/身份验证成功，manual后new和resume均恢复smart/profile-default，pending none，exit 0，付费模型调用0。证据在JSON的 `evaluationHarnessDelivery20260930`，不将此前产物的付费或scripted审批记录冒充此次重测。最终材料化回归103 passed / 104.39s；首次因临时盘满失败，释放空间后原命令重跑通过。历史T072证据保留。

## 2026-09-30 整消息引用修复后的最终宿主复核

当前T079 asset `d12934cb53383e70103aaf937b9b7475efbabc3cf50b3be9fb244355d76ec786`（367269064 bytes）、runtime `fcdf5e32046deec53295f3590a87f12b9a2e3d415ff241af348b0be930d0f3d0` 已核对正式身份并在隔离HOME运行。lifecycle验证new/resume恢复smart/profile-default、bridge健康且身份验证成功、exit0。固定本地review响应按新utf8ByteLength契约绑定完整真实授权消息：primary1/tiny0，无人工批准和重复prompt，审计pending→consumed，成功toolResult恰1；main fixture2次、review fixture1次全部在回环服务，外部模型请求0。完成后rollback restored4，默认smart和fallback恢复，dummykey和pending清除。JSON的fullMessageEvidenceDelivery20260930保存当前证据；不把固定响应记为真实审批质量。

## T080 指代政策交付复验（历史，2026-09-30）

当时 T080 combined runtime `b1566c3e211f0dbd71d1849509a7f3b10bb27651602f1ca6fc5b51bd1f7ccbe4`，asset `3ab701bfa0d496e72e9f5725b2077a0241a4e9cc4603d091fcf10761be2c2556` 已通过同一隔离实例 sync/plan/apply、真实 lifecycle、固定本地 provider 的工具审批、missing-plugin 和 rollback。new/resume恢复 smart/profile-default；bridge healthy、identityVerified=true；审查1次、tiny0、人工0、permit consumed、pwd工具结果1次；退出0。缺插件在宿主启动前退出5，finally恢复原字节。回滚恢复4项、默认smart与fallback、移除虚构key且pending absent。外部模型请求0。日志 `/tmp/rotom-permission-reference-fix-lifecycle.log`、`/tmp/rotom-permission-reference-fix-host-verification.log`、`/tmp/rotom-permission-reference-fix-missing-plugin.log`。结构化证据见[host JSON](omp-permission-control-host-smoke-evidence.json) 的 referencePolicyDelivery20260930。

模型质量由独立[最终模型评测](omp-permission-control-model-evaluation.md)与[原始结果](omp-permission-control-model-results.json)记录；固定provider不是实际reviewer。此次没有修改日常本机OMP配置。

## Phase 9 收敛修复后的真实宿主复验（2026-09-30）

T081/T082 已完成。native deny 在 pre/effective 阶段使用只供拒绝审计的保守宿主计划，不运行 tool_call 改写或 native prepare；final 阶段保留真实冻结计划。已知 native deny 不依赖可选来源 callback 才生效，三个阶段均记录一次关联 deny。ask 在等待 UI 前写入审计；无 UI 或取消不丢记录，人类结果及 permit 后续阶段保留同一请求链。模型、凭据和 provider 变化后同步权威被动状态；status 只读取快照，显式 reviewer 与历史审计模型身份不被替换。

TDD 实际证据：T081 首轮 bridge 31 pass/4 fail（提前 deny 和无 UI/取消漏审计）；T082 定向 0 pass/1 fail（模型已是 review-b，首次 status 仍是 review-a）。修复后 bridge **37 pass/0 fail/287 assertions**；材料化定向 pytest 1 passed/58.79s，完整 coding-agent `bun run check:types` 与四文件 oxfmt check 均退出0。代码和测试由 executor `gpt-5.6-sol / medium` 实施；scout `gpt-5.6-luna / medium` 只读整理交付入口，主代理负责拒绝语义、最终审查与交付验收。

| 身份 | 本轮实际值 |
|---|---|
| 0001 patch | `f5478d8c128a92e19fc5ff46269a6cf6743dc8fc7c20389211c676afe605ce94` |
| standalone SHA-256 | `ada205aeec0cd2aefbb4c2d0b00d924ba2d9360395159fdd76f2c6a56a128f41` |
| standalone size | 367281352 bytes |
| patched manifest | `f3a274d2c593851d17101d57a8aca6c5705994655f6b93755f356d258918af2f` |
| build receipt | `f5ab42e0d4ef6997d0f13bed74d97945190e0a6dbb149ce6d94808bf85269da3` |
| combined runtime | `36c0e8a46da3999b4eee73edc0121117fd284f2880bc7784ba36189946854e0f` |


official `969b7e6052eb4020cf27ffaecdacf4abc25bbaf98dbf4e05ba8d114410c027d5`、plugin `430bad7398aeb47748a5bf9871558c923a62a949a1888efbc5520824c5416113`、0002 `be830a4238d67d840621dc4503e342679f625f8aed3e86af1a9cdf515089f508`、独立 build-inputs 与冻结样本保持原身份。正式离线构建的 artifact cache 为 `/tmp/rotom-omp-permission-artifacts-convergence-20260930`；构建的 `hostExecuted=false` 不代表宿主通过，实际宿主结果由后续步骤单列。

最终回归命令：

```sh
.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_runtime.py tests/test_omp_permission_build_inputs.py tests/test_omp_kernel.py::test_kernel_deployment_preserves_reviewed_native_configuration --omp-build-source /tmp/rotom-omp-plan/commit.tar.gz --omp-tool-cache /tmp/rotom-omp-build-inputs/tools --omp-dependency-cache /tmp/rotom-omp-build-inputs/dependencies --basetemp /tmp/rotom-permission-convergence-final-pytest
```

结果：**152 passed in 71.68s**，包括原三组151项和本轮新身份的kernel渲染单项，无跳过。默认回归仍是隔离测试，不启动真实宿主。

新 runtime 独立真实宿主 case：`/tmp/rotom-permission-convergence-host-20260930`。实际 sync/plan/apply/run 成功；固定服务 main2/review1、外部模型0，pwd恰执行一次，primary1/tiny0/human0，审计同一请求 pending→consumed；manual→new、manual→resume 均恢复 smart/profile-default；missing-plugin 在启动前退出5并恢复原字节；rollback退出0、restored4、dummy key移除、pending absent。OMP退出0，固定服务已停止。结构化证据在 [host JSON](omp-permission-control-host-smoke-evidence.json) 的 `convergenceDelivery20260930`。

| 状态 | 本轮范围 |
|---|---|
| 完成 | T081/T082、正式重建/锁定、152项回归、37项bridge、strict/format与同一新资产宿主复验 |
| 进行中 | 无本轮剩余任务 |
| 失败待决策 | 无；原始红灯与测试夹具缺桩修正保留为诊断记录，不计通过 |
| 环境不足未验证 | 本轮无阻塞所选Linux x64交付的已确认环境缺项 |
| 尚未执行/未验证 | 真实tiny推理、真实interceptor扩展链/长任务和其它平台保留既有证据边界，不计为通过 |

本轮未新增付费模型调用。102/102账本、最终模型响应和冻结样本逐字节不变；T080冻结模型质量结果保留其原始runtime身份，不冒充本轮重测。日常机器配置摘要不变，日常cache和实例未部署。

## Phase 11 远程审批与Cursor模型开关（2026-09-30）

| 身份 | 本轮实际值 |
|---|---|
| official recipe | `60d399dd4b0a2f2265d117d17b9e566669b64ca1413d4dc0fac66487165b9521` |
| plugin tree | `4511e7cdb9efb312029acfff93f0f6fe73cc5c3c018325c25756f9fd7eea040d` |
| 0001 patch | `45a0fcbdd4092161cbc3c14ac8b40a323928cd4dc915538e2cbee7f6ead8e51f` |
| 0002 patch | `c34d02d19941e09ca507e67164f5b8d37a67e991b6ed96ab51dca2b67ece33da` |
| standalone SHA-256 | `0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86` |
| standalone size | 367318216 bytes |
| patched manifest | `dce490890453ccff4165ece76a460fb9cbf23756cdb553c3fd7fe8d72bbb815e` |
| build receipt | `f0716c84316192f349253d68247ba4bcfc455f41218816efe79675952df4a0ac` |
| combined runtime | `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2` |

Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。

主审使用固定本地OpenAI-completions响应返回503；远程备用使用固定本地Anthropic-messages响应，并按完整真实授权消息及scopeDigest生成严格allow。模型公开ID分别为kimi_tf/kimi-for-coding、zhipu_tf/glm-5.3-flash，但这两个provider都是loopback脚本，不代表真实Kimi/GLM质量。持久化审计保留primary_model和remote_model、两层调用计数及最终remote-fallback来源；status仍显示配置主审及远程备用。真实Cursor模型目录、本地tiny推理和其它平台未验证。

实际命令为`.venv/bin/python /tmp/rotom-permission-remote-host-20260930-attempt2/run-host-verification.py`，该driver运行7个有界脚本，全部退出0；日志与结构化结果在同目录。使用临时HOME/XDG/private cache、dummy key和loopback地址，没有读取日常账号数据库或请求付费模型。机器可读证据见[host JSON](omp-permission-control-host-smoke-evidence.json)的remoteFallbackDelivery20260930。


本轮验收后，将同一已验证资产原子准备到日常omp-kernel的私人内容寻址cache并显式sync，退出0，runtime为`06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`。仅新增缓存运行包，未apply原生配置、未访问OMP账号库、未启动或停止日常会话；workstation.toml摘要保持不变。退出活动OMP后由用户plan/apply/run启用。


### 本机部署闭合（2026-09-30，后续明确授权）

用户确认已退出 OMP，并明确要求完成日常 `omp-kernel` 的 `plan` 与 `apply`。以原 workstation.toml 执行：`plan` 退出 0，3 项变更、冲突 0、漂移 0；`apply` 退出 0，部署同一 3 项变更；随后 `doctor --format json` 退出 0，状态 `offline-ready`，待变更 0，当前和已部署依赖均 `installed`，`deployed_runtime_matches_current=true`，无冲突、漂移或待恢复事务，`live=false`。当前 combined runtime 为 `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`。

这是前文“仅 cache/sync”阶段之后的新增授权与执行证据。未启动日常宿主、未访问 OMP 账号库，新增模型请求 0；workstation.toml、历史模型响应/账本、冻结样本及 build-inputs 共 9 项受保护输入摘要保持不变。用户接下来可直接 `run`；本次部署健康检查不声称已验证真实 Cursor 目录或新 GLM 模型质量。机器可读结果位于 host evidence 的 `remoteFallbackDelivery20260930.dailyDeployment`。
