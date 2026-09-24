# 实施工作记录（不是最终验收证据）

2026-09-24 当前状态：软件实现和 Linux x86_64 四配方 mock/native、双路径冷重建已完成，T112 已按用户修订范围验收通过，当前 spec 已正常完成。原 T107—T111 已转至独立后续清单，不阻塞本 spec；当前107/107项有效任务完成。最新结论见 [关闭报告](../../docs/acceptance/pi-spec-closure-20260924/README.md) 与 [范围修订](scope-change-20260924.md)。

下文全部是按时间积累的历史记录，早期“未实现”“待接线”“97/112”等描述不代表当前状态。

## 已实现并验证的集成

- Pi adapter、fixture 依赖锁/部署管线、监督/恢复和跨实例写租约。
- 唯一 subagents 管理者、持久 managed RPC、Task/Attempt 和请求预算。
- TaskService 的 inspect/fix 接入 fresh worker、受管候选、真实检查接口、required review 和显式 second_view。
- 丢失 dispatch 应答不重发；验证收据可补回关联；物理终止与逻辑状态分离。
- 一次性调度与工作区启动共用 SQLite 事务；错过执行时间暂停；resume 保留预算。
- /orch、kernel_task、配置生成、使用量接线；默认 mock 与生产 typecheck 独立于历史宿主测试。
- 默认项目策略保持 deny。本机可显式选择 task-keeper-candidate 的 tk_* read/write；无 delete/rename 授权。
- US4 已新增迁移/capture/多文件故障测试，修复历史 Pi apiKey 缺 guard 仍可回滚的问题。

## 验证与边界

- 最近全量 Python：969 passed、7 subtests（后续新增维护测试尚待再次全量）。
- 运行时 + TK mock：91 passed，之后新增队列恢复/统计测试通过；需最终汇总。
- TK 生产源码与派生 subagents 已在精确 SDK 的临时工具链静态检查。
- 没有启动真实 Pi/DSH/Codex，没有模型请求；native/live 未运行。
- 没有生成最终可发布 Pi 锁；当前不可宣称完整迁移。

## 剩余工作

- US4 维护回归75项通过；current/previous/pending 保护、来源标记保留与私人 capture 已闭合。
- model-delegate 已从冻结 Git 完整迁入48文件；V2 schemas/记录/单run持久生命周期8项测试、新工具意图校验2项通过。原生backend/CLI尚未接线，不能执行源V1脚本作为迁移结果。
- T067—T088：完整 model-delegate 迁移、V2 生命周期/证据、两 backend、七 preset、所有调用方及其他插件适配。
- T089—T112：诊断、平台组合、四配方真实锁、文档和授权后的原生/账号验收。
- 原始 Task Keeper 的旧测试/文档保留作移植参考，不作为新版通过证据。
- 修改 subagents 源后重建 patch 并从冻结提交验证可重建性。


## model-delegate 当前工作面（T067—T072，未整体完成）

- `model_delegate.py`：V2 closed schema、verified-execution、4096 字节信封、cursor、持久 run/终态CAS、显式resume、linked worktree写准入、显式route。
- `pi_delegate.py`：DelegateController 先写意图再调用 ExecutionStore.allocate，持久输入与 OperationGrant；ready未知不重发；刷新结果独立核验退出/终止/文件/事件。已挂到 SupervisorService 的 delegate_* 分发。
- `model_delegate_backends.py`：固定Codex argv与最小环境，已按官方0.154.0源码核对；CLI未运行。
- 工具意图校验 `packages/model-delegate/contract.ts` 已拒绝managed外部helper、模型写入、未知字段、未绑定模型和根。
- 待接线：HostSupervisor.resolve_command 尚不认识 delegate-*；没有实际worker入口；manager external RPC、standalone CLI、context/feedback、七preset和最终退出旧路径仍未完成。
- 12项 Python协议/生命周期/backend测试、2项controller测试、2项桥请求测试通过（最新Codex零重试参数还需再跑targeted）。
- V1源脚本尚未替换，不能运行它们作为迁移结果。所有T067以后的任务仍未勾选。
- 官方Codex只读源码缓存 `/tmp/agentcfg-codex-0154-source/`，包含schema.json、shared-options.rs、exec-lib.rs；来源链接已写入skill references。


## 最新接线（尚在 US5 实施中）

- `pi_delegate_spawn.py` 已接 HostSupervisor.resolve_command：固定 worker 输入、精确模型、最小env；仍需运行包 commands 注册。
- Pi worker `runtime/delegate-pi.ts` + `delegate-pi-main.ts`：closed loader、readonly tk_* 文件RPC、显式route fetch、无重试；core mock2项通过。Pi外部backend暂只实现openai-completions API-key模型，其他provider须显式拒绝，不能作为完整支持。
- Codex worker `scripts/pi-delegate-codex.py` 已写，尚未跑wrapper替身测试。源码核对使用固定0.154.0官方exec_events和permissions；不能用旧V1 fixtures中的message格式冒充新agent_message事件。
- `codex_permissions` 转换为命名profile，默认root deny；拒绝把partial write扩大成delete/rename。原生行为未验证。Codex可信PreToolUse授权钩子仍需评估接入，确保取消后新工具动作不会使用旧grant。
- `external-executor.ts` + `external-rpc.ts` 绑定同一AgentManager并复用2槽位；实际管理者+假supervisor队列测试2项通过。
- `subagents-vendor/src/agentcfg-managed.ts` 新增external挂载；vendor tsc通过，尚需lint/重建patch。`docs/rpc.md`及NOTICE更新。
- `DelegateController` file_action readonly真实临时文件测试通过；固定spawn精确凭据测试通过。Controller结果再次获取会重查候选/最终文件/物理证明。
- 尚未实现standalone CLI接线、CLI resume、context/feedback、七preset、model_delegate插件入口和最终依赖注册。T067—T112仍未勾选。


## 回归快照与 US5 接线更新

- 全量Python：**1017 passed，7 subtests passed**；运行时/TK/委托Node mock：**100 passed**。
- 委托插件 index/runner 已实现唯一 model_delegate 工具；用户 /model-login codex 使用监督登录操作，bootstrap 可加载该登录入口。
- standalone CLI 复用 runtime.run 的部署/运行包/实例锁校验，先进入专用 supervisor，再发单次目标；--detach/observe/status/poll/wait/cancel/resume/result 有代码接线。
- 离线结果查询重新核验持久终止证据、当前候选与最终文件。Python 冻结入口已禁止写 __pycache__，避免运行后破坏内容收据。
- 七个 preset 已从冻结角色的用途/输出段迁入并绑定到真实 prompt。源码与目标摘要见 preset-manifest.json。
- Context/memory/required feedback 已接入；旧 revision/claim/evidence 可转换，新增事实不自动 verified。
- fanout 改为私有 UDS 控制客户端，已有 AgentManager 接收批次；没有端点则拒绝。需要补传输端点 mock 与批次CLI测试。
- shell backend/lib 已改为 V2 canonical客户端；无全局 pi auth/进程组kill/旧runner执行路径。
- T067/T068/T070/T071 已勾选；T069及T072—T088仍需闭合所有用例和插件适配，未勾选。

### 仍须处理

1. readonly可配置重试还未闭合；当前实际后端和runner均为0重试。写入不能自动重试。
2. Pi委托目前只实现 openai-completions API-key模型；openai-responses与必要OAuth/选中auth能力需进一步适配或明确阻塞，不能假报完整支持。
3. Codex可信工具前授权检查仍需接入/验证；当前有原生静态权限与物理监督，不能据此声称动态grant撤销已认证。
4. batch UDS需覆盖UTF8拆帧/身份/缺端点；缺权限反馈的失败收据、反馈sidecar重新获取也需测试。
5. final-source caller-map/旧组件退出测试仍未完；V1导入测试只作来源，不计新版通过。
6. model-delegate生产typecheck已在临时副本修正一处progress类型，修正已写回；需再跑三包检查和vendor lint/patch更新。
7. 其他插件/US6诊断与验收脚本/最终锁/原生账号证据未完成。没有执行任何真实Pi/Codex/DSH或模型调用。


## 权限与插件迁入（T084—T086 正在实施）

- 37个本地插件/扩展文件从冻结Git迁入；local-plugins-manifest.json记录来源。仍需逐个适配并登记最终依赖。
- 权限包175文件从npm @gotgenes/pi-permission-system@29.3.0按integrity核验迁入，目标29.3.0-agentcfg.1。
- 新AgentcfgPolicyLoader只读当前清单、保留原生ask提示层；ConfigStore不读写全局/项目配置、不写原始输入审计日志；每个tool_call先走agentcfgGate。
- runtime/permission-access.ts有硬策略检查、真实YOLO提示状态、一次性批准票据、stale票据拒绝；3项mock通过。
- **关键未完成：runtime.ordinaryOperations尚未实现，因此新权限gate在普通IO上返回ORDINARY_IO_CAPABILITY_MISSING。不能将当前源码称为可用完整Pi。**
- Session YOLO已重写为permissionAccess客户端；footer读取agent_options.ui.footer并显示实际提示状态。严格schema已补。
- OpenAI proxy不再使用10808/环境默认，必须绑定network.openai_proxy_route；managed helper请求拒绝。原路由测试尚未适配/运行。
- LoopGuard读取显式loop_guard配置；managed不做父上下文裁剪。新增capability-policy，普通压缩owner为native/smart-compact，handoff改用当前受约束ModelRuntime。尚待静态与插件测试。
- Permission vendor补丁已生成并从原npm树git apply重建成功。生成器 scripts/update-pi-permissions-patch.py --source /tmp/agentcfg-pi-permissions-29.3.0/package。
- 最新Python定向schema/adapter/catalog：23 passed。新增后续改动还没全量复测。

### 下一步具体实现建议

1. 完成普通IO：SDK0.84.4提供createRead/Write/EditToolDefinition的operations注入，可保持原生显示与多edit语义。read/ls/find可通过supervisor的fd安全操作；write/edit应使用有真实进程身份的一次性受管helper，绑定WorkspaceWriteLease，不能伪造父宿主已终止。
2. ordinary只读subagent不能再绕过权限层；agent-runner.ts在978行附近构造sessionOpts/customTools。只读搜索子进程需要监督。避免两个普通session占满manager槽后各等待新辅助槽造成死锁；可明确借用父普通session槽位执行一个受限工具子操作，保持总容量与未知活动保护。
3. permission-system原生policyLoader是固定ask层，canonical硬规则在实际IO层仍必须再次核验。当前PermissionAccess.check会调用ordinaryOperations.preflight；agentcfgGate拒绝/stale时会调用abort；成功approve后Tool执行需take票据。
4. 需要完善Codex动态grant撤销（可信PreToolUse检查或等价严格方案）。当前有静态native权限、实际监督与明确write准入，未认证动态工具撤销。
5. 普通调用方 dirty-repo-guard/git-checkpoint/notify/gentle-agent-state/pi-processes/slopchop/editor 的子进程与写入接线尚未做。
6. 仍缺可配置readonly重试、更多Pi协议/必要auth适配、batch端点/CLI测试、反馈sidecar重验、retirement/caller-map和完整US5验证。
7. User-login helper已写但尚需测试；native执行未做。所有原生/账号验收任务继续未勾选。


## 最新实施快照（普通工具、委托控制与替换验证）

- 全量默认 pytest：**1057 passed，7 subtests passed，145.22s**；Node runtime/TK/delegate mock：**115 passed**。未执行任何真实 Pi/Codex/DSH 或账号/模型请求。
- 普通 read/write/edit/rename/ls/find/grep 已接入 SDK 与监督者；批准绑定会话、cwd、输入，一次性消费。未用授权五分钟到期回收。rename 使用 Linux renameat2 / macOS renameatx_np 排他语义，临时目录竞态测试通过；macOS 原生未执行。
- 普通 bash/editor 仅接受配置的 agentcfg:command_id 或精确 argv；external_tools 声明 project_root/read_roots/write_roots/timeout_seconds，command_ref 规则允许后才准入。可写命令共享 worktree 租约；沙箱读写根、文件拒绝、输出/退出/物理身份已接线并通过 mock。任意 shell 未绑定就拒绝。插件调用者仍需迁移。
- Pi 委托新增 openai-responses API-key 协议，终止事件/模型错配/截断负向通过。OAuth 委托仍缺适配。
- readonly_retries 配置为0–3，默认0；只独立CLI可用。manager提交和写入为0，流重试为0，start_unknown不重发。每次Pi fetch重新核验原授权。
- required feedback 在在线/离线结果获取时重新计算并比对 sidecar、上下文、候选与receipt；篡改拒绝。
- CLI动作参数严格分组；probe区分installed、native_load/not-run、authentication/unknown、execution/not-run。bootstrap拒绝冻结目录内未列入收据的Python源码；execv替身测试通过。
- 批次传输mock覆盖UTF8拆帧、错误capability、坏帧、关闭未完成连接；用户登录mock覆盖bootstrap监督和queued超时不启动。
- caller-map.json记录37个冻结来源调用方；旧runner/角色完全缺席时两backend×七preset共14个假启动通过，实际插件仅注册model_delegate和/model-login。T069、T072、T077、T078、T082已勾选；未闭合项未勾。
- subagents补丁19个修改文件，sha256=75037a121c5382b2fcee0b7f1864e752d22d822ef008b8137bda752d641d21ef，已从固定commit重建比对。权限补丁目前10个修改文件，含Node新类型兼容，已重新生成。
- subagents、Task Keeper、model-delegate、permission-system四包临时副本生产TypeScript检查通过；权限包临时tsconfig需ES2023与#src/*路径映射。尚需补正式tsconfig和剩余插件检查。

### 当前主要未完成项

1. 固定Codex0.154.0的PreToolUse源码已核对：hook错误/超时默认fail-open。不能只加普通hook冒充严格撤权。需要可靠工具前拒绝边界，仍阻塞T074/原生认证。源码缓存 /tmp/agentcfg-codex-0154-source/，来源链接在skill reference。
2. Pi OAuth委托、batch CLI传输完整测试、probe完整mock、manager reload/未消费结果恢复继续待补。
3. dirty-repo-guard/git-checkpoint/gentle-agent-state/notify/pi-processes/slopchop/readseek/btw/smartcompact尚需完成调用适配与运行包闭包。当前普通命令能力已提供底层入口，未声称所有调用方已迁好。
4. loop-guard配置需去掉运行时静默clamp；openai-proxy原路由测试需适配显式manifest。普通grep使用有界JS正则线程，本地ignore仅基础规则，需补兼容性与边界。
5. US6诊断/证据/scope/验收脚本、最终真实依赖锁、四平台native和live仍未完成。无需在可自主完成的代码工作前请求授权。


## 追加：插件控制、OAuth 与回归

- 最新完整 Node 隔离组合 **136 passed**，含 openai-proxy 16项、plugin-policy4项、Pi delegate5项；完整 Python 仍以最近1057+7为基线，其后新增改动的定向回归已通过（29项Pi/adapter/pipeline，27项supervisor/vendor/pipeline/schema，14项guarded/workerfiles，6项supervisor）。
- Pi OAuth支持新增 openai-codex 的未过期access-only投影，provider_bindings解决原生route与逻辑provider映射；不复制refresh或其他账号、不在worker刷新。zstd请求有界解压后核对模型，经显式route发送；兼容固定SDK的response.done与response.completed语义。Cursor委托transport尚缺。
- 原生PreToolUse错误放行风险仍未解决；Codex动态撤权保持未完成。不能将普通hook当作严格边界。
- session边界守卫检查实际supervisor activity_summary及manager未消费受控结果；reload/fork/switch/handoff拒绝丢失活动。delegate结果核验后消费镜像；login结果同样消费，queued超时通过manager取消。
- LoopGuard显式manifest坏值不再clamp/fallback；/yolo真实命令状态测试通过。Footer纠正为pi.events权限广播，关闭时解除监听，修复Config返回类型与原始错误输出。
- openai-proxy移除README固定10808建议，显式route及credential_ref生效；凭据只用于Proxy-Authorization，不出现在状态中。tests/fixtures/pi/tooling新增undici8.9.0（--ignore-scripts，临时HOME）；默认网络拦截仍启用。
- 新增本地包recipes：session-yolo/colorful-footer/loop-guard/openai-proxy。permission-system依赖pi-subagents，session-yolo依赖permission-system，避免可写工具缺manager。未自动开启全部插件。
- 权限fork正式tsconfig新增；补丁11个修改文件。四本地包+权限包临时类型检查通过；extensions检查发现handoff两个隐式any，已用AssistantMessage返回类型修正，正在复查。
- 文件写入补上新建父目录的create权限检查；精确文件授权不能暗中创建未授权目录。
- 仍须：完成插件进程调用适配（git checkpoint/dirty guard/gentle-state/notify/processes/slopchop/readseek/btw/smartcompact）、批次CLI/probe完整测试、Codex严格撤权和最终依赖/US6/平台证据。


### 本轮续记

- 新V2 shell入口已实际执行：contract27 passed、lifecycle26 passed（此后批次测试又增加6项）。
- 批次Python客户端新增实例/UDS inode/peer UID/响应batch关联校验；无manager/坏输入拒绝，无standalone fork。混合completed+canceled修正为partial；大控制摘要保留私人完整产物引用。batch+contract定向10 passed。T083已勾选。
- extensions生产tsc通过（handoff改为AssistantMessage类型，非stop结果不建立交接会话）。
- 接下来下载固定版本源码至/tmp：pi-btw0.55.3、smart-compact9.6.0、processes0.11.1、slopchop0.10.1、readseek0.9.16；只核验来源，不运行包。脚本/tmp/agentcfg-fetch-plugin-sources.py。


### 新插件源码已入库，仍在适配

- 固定npm源码已核验integrity并完整导入：btw-vendor15文件、smart-compact-vendor172、processes-vendor119、slopchop-vendor15、readseek-vendor13。各migration/*-manifest.json明确adaptation=pending；尚未登记为可运行recipe。processes发行包缺LICENSE，需从固定来源补齐许可证。
- BTW与smart-compact实际入口已接runtime/plugin-model；它复用当前受约束ModelRuntime、禁嵌套provider重试，并拒绝managed scope及managed配方活动期间的旁路helper。原生声明/包加载尚未验证。
- runtime/plugin-settings新增只读配置与实例路径接口；BTW从agent_options.btw读，smart-compact从smart_compact读，原生配置写入提示用户改agentcfg。智能压缩state/cache/backups迁到实例pi-home，Git指纹不再execSync而使用声明项目根。
- 新options/agent schema保持仓库严格子集；辅助模型必须属于同一登记集合。schema+adapter22 passed；plugin-model/policy6 passed，后续新增settings测试待收结果。
- .gitignore补入固定vendor dist例外，避免npm提供的真正执行入口/类型文件被当构建垃圾忽略。
- 未完成：BTW仍有detached浏览器opener；smart-compact实际工具/状态/恢复行为与UI更改流程仍需验证；其他新vendor尚未适配，不能据此勾T085/T086。


### 当前工作入口

- helper插件schema已修正类型子集，schema+adapter22项通过；新plugin-settings mock3项通过。
- 正在继续评估Codex严格工具边界：普通PreToolUse不能可靠fail-closed；备选是在官方CLI内仅暴露受控MCP文件/命令工具，原生项目文件权限deny，通过同一delegate lease逐动作验证。**尚未决定或实现此方案，不得声称问题已解决。** 固定官方工具/配置源码正在下载到/tmp/agentcfg-codex-0154-source。
- 所有新vendor尚未进recipes，仍adaptation=pending。BTW浏览器detached opener、smartcompact完整实际入口测试和其余三个插件适配仍待办。


### Codex接法待用户偏好；受控工具原型推进中

- 已通过async问题询问官方CLI+MCP桥（推荐）与同版本补丁构建的偏好；暂无回答，已说明先按推荐方案做原型，仍未标严格撤权解决。
- 新src/agentcfg/pi_delegate_files.py将Pi现有readonly IO统一出来，并提供Codex显式delegate-write的逐动作准入和mutation journal。self.file_action已接该模块；**原型还需测试，Codex实际CLI尚未切MCP，不得宣称完成。**
- CLI源码确认shell工具可关闭；apply_patch由模型能力决定仍可能出现，拟让原生工具对项目无读写权限，由受控MCP代理真正的项目操作。系统/企业配置、其他MCP来源、web工具边界仍需核对，尚未最终设计。
- 尚需测试/闭合：新delegate_files write真实linked worktree/撤权/重复mutation/未settled收据；MCP stdio broker；官方CLI config隔离与native proof。父高级写入必须保留三项明确准入，不能为适配桥放宽默认policy。


### 回归与监督边界最新结果

- 最新完整默认Python回归：**1074 passed，7 subtests passed，169.90s**；最新完整Node组合：**142 passed**。
- 其后新增force取消（manager/user控制通道，worker不能升级）：Linux只用已核验pidfd，macOS通过原helper nonce+已撤销generation的KILL控制消息。24项定向通过；macOS C替身SDK清点测试通过，非原生证据。
- 普通命令interactive显式开启后才提供管道stdin；单块<=PIPE_BUF/4096、非阻塞、当前generation/进程/工作区复核。默认捕获型子进程stdin=DEVNULL，避免偷偷读取父终端。
- 新MCP协议核心src/agentcfg/pi_delegate_mcp.py与脚本scripts/pi-delegate-mcp.py已写；只读/编辑/schema拒绝/重放/协议stdout/能力不外泄3项通过。Codex真实CLI仍未接线。
- pi_delegate_files实际写代理2项通过；host增加service mutex非阻塞回收屏障，避免worker已死但监督者仍执行文件IO时释放租约。相关host+MCP+write组9项通过。
- Smart Compact修复单owner自动触发：settled触发，native自动压缩关闭；hook无结果/失败返回cancel，不让native LLM补做。schema强制scrubSecrets=true。plugin-model4项通过。
- 正在检查跨平台路径别名和macOS沙箱基础权限；Apple官方unistd定义_PC_CASE_SENSITIVE=11，文件/tmp/agentcfg-macos-unistd.h。尚未修改case规则。官方seatbelt基础策略正在下载/tmp/agentcfg-codex-0154-source/seatbelt_base_policy.sbpl。
- 所有代码未提交。没有真实Pi/Codex/DSH、真实模型、真实账号操作。tasks当前76/112已勾，T073–076、T079–081、T084以后的未完成项保持未勾。


## 当前接线与测试（最新）

- pi-processes三个入口+skill已登记本地fork0.11.1-agentcfg.1，所有四配方的依赖切片包含它但不默认激活。旧裸PGID/独立spawn实现移到migration并从配方排除。
- ProcessManager仅保留视图/日志，真实执行提交同一AgentManager与supervisor。queued无PID；stdin通过已授权管道；取消ack不能清除unknown记录或日志。两项实际facade+共享队列mock通过，整个包临时tsc通过。
- 进程设置改读agent_options.processes，旧global/local自动导入已关闭；ps:settings展示配置并指向agentcfg。命令仍受external_tools静态绑定、当前无网络沙箱限制。尚需处理可选网络服务与更多失败路径；不因此勾T086。
- OutputCapture增加有界实时事件窗口（最多1024块/4MiB）、游标/丢失标记，使用read1避免等待64KiB才显示日志；14项output/commands/schema定向通过。
- 新pi_resource_reads.py解决已选skill路径位于私人实例、普通read因此读不到的问题：只允许main读取已选且加载摘要匹配的技能树，不开放相邻auth/session目录；10项operations/resource-discovery通过。还需审核外部skill边界与读写策略关系。
- 辅助检查新增read_roots显式依赖根，不再把可执行程序整个父目录当默认可读；传入项目/私人拒绝。macOS基础策略改为同sandbox进程信息/信号和有限sysctl，原生仍待验。
- FilePolicy新增已有对象别名拒绝与Darwin大小写不敏感/Unicode拒绝处理（fpathconf 11）。23项guarded/ordinary/delegate/worker files通过。Node预检尚未做完整对象别名对齐，但实际IO以Python层为准。
- 普通和auxiliary helper在已知未spawn失败时撤销分配并消费已失败镜像，unknown仍保留。auxiliary结果增加独立物理身份/终止证明；TaskService inspect/fix完整mock复跑通过。
- Codex登录与运行中委托的账号归属互斥；登录不跟随不安全auth文件。8项login/delegate通过。
- Codex工具现支持已登记openai-codex模型角色，拒绝同名其他provider；桥5项通过。CLI默认timeout取配方max，start/resume失败终态返回5；相关CLI/output14项通过。
- Codex TOML参数支持非BMP路径（项目😀），backend6项通过。
- 最近完整Python基线1074+7、Node142均通过；之后继续有上述改动。当前正在跑vendor/pipeline/resource/operations/commands/output组与完整Node组合（session10960、78244，需收结果）。
- 用户偏好问题仍未收到回答；MCP受控文件原型已通过，但Codex实际wrapper/CLI尚未切换。固定CLI的系统/云配置合并会保留未覆盖MCP项，仍需解决封闭资源与严格撤权，不得称已完成。


### 最后收集结果与未决项

- vendor/pipeline/resource/operations/commands/output组合：32 passed。Node全部runtime/TK/delegate/proxy组合：146 passed。
- notify已改为配置化OSC99/OSC777/bell/off，不产生未受监督的PowerShell；Windows Terminal自动模式为bell，已明确记录行为变化。notify单测1 passed。
- 曾起草Git管理helper，但尚未实现统一policy/OperationGrant及过滤器边界；草稿仅保留于/tmp/agentcfg-git-operations-draft.py，未接入仓库或运行包。dirty guard/checkpoint/slopchop Git改造仍待办。
- 已选择技能实际read入口10项通过；processes正向共享队列/实时输出/输入及取消unknown两项通过；包版本0.11.1-agentcfg.1、三扩展及skill已纳入dependency recipe（未默认开启）。
- 未决架构问题：已询问官方Codex CLI+受控MCP桥与同版本补丁构建，用户尚未答复。MCP只是原型；不能把它与完整原生工具能力或严格资源封闭画等号，尤其还须验证CLI系统/云配置层以及原生工具路径。
- 没有执行native/live或真实账号模型操作。tasks仍76/112；完整迁移未完成，不能批准发布或宣称新机完整重建就绪。

### 用户确认 Codex 接法（2026-09-17）

- 用户明确选择保留官方 CLI，文件与命令操作经 agentcfg 受控 MCP 工具桥；不维护 Codex 分支。此前的接法偏好问题已经关闭，不再重复询问。
- 实施约束：桥复用现有 supervisor、当前 grant generation、工作区租约和 mutation journal；不另启 manager，不扩大默认权限。原生 shell/apply_patch 等业务 IO 通道必须封闭；系统/云配置中的外来 MCP 不能靠空表覆盖假定已经清除。
- 此决定不等于 native/live 授权；仍只运行隔离 mock 测试，真实宿主与账号证据继续单独记录。

### 受控 MCP 文件与派生命令控制层

- 接法偏好已确认并写入 plan；当前仍在 T074/T086 的实施范围内，不能勾完整 CLI 接线或 native 验收。
- CodexEvents 增加受控 MCP 模式：限定 agentcfg_delegate 服务和本次工具集合，检查开始/结束身份、漏事件、重复完成；拒绝原生 command_execution/file_change，不泄漏工具参数或错误正文。实际 Codex wrapper 尚未切入此模式。
- 新 pi_delegate_commands.py 接入 delegate_command_list/start/status；只接受 tool:ID、固定 argv、显式根和 policy。写命令绑定父候选与父写租约，禁止额外写根/原 checkout 重映射；使用冻结 pi-project-check 和既有 supervisor，保留全局 active_children 上限，容量不足明确失败。
- 子命令登记独立执行和父引用后才越过 spawn 提交点；parent lease 必须等子执行核实终止，启动未知不重发。撤权/父进程死亡/时限到达停止子执行；未知身份继续保护。结果同时校验真实退出记录、物理身份和捕获文件摘要。
- ExecutionStore 持久绑定 execution-lease: 子引用到终止凭证，恢复/正常回收/离线 saved_termination 均不能遗忘子执行；子证据删除或损坏后离线状态降为未验证。
- 文件与写命令共享 mutation journal；verify_mutations 重放所有操作的 request/lease/顺序/前后摘要，线上和离线均校验。没有日志只能证明候选未变，不能认证裸写。
- 修复 ordinary_commands 与策略 schema 的真实接口不一致：权限查找统一 tool:ID；原测试夹具也改为合法 schema 值。
- MCP 字节分页只允许跨页不完整 UTF-8 字符；末尾/中间坏字节拒绝。broker 脚本加入冻结运行包复制闭包。
- 定向监督/恢复/委托组合 73 passed；之后新增子凭证丢失/启动未知等测试，完整默认回归运行中。未启动真实 Pi/Codex/DSH、模型、登录或项目命令。

### 本轮验证结果

- 全量默认 Python 回归实际结果：1089 passed、7 subtests passed、8 failed（176.35s）。8项均定位到测试仓库复制清单遗漏新增 pi-delegate-mcp.py，导致部署器正确报“监督源码不完整”；没有放宽生产闭包检查。
- 补齐测试夹具后，dependencies/pipeline/派生命令/MCP/activity/recovery组合 **47 passed（46.82s）**，包含全部8项原失败；先前监督/恢复/CLI/backend组合 **73 passed**。两组合有重叠，不累计为独立测试总数。未重新宣称全量单次全绿。
- git diff --check、Python compileall通过；未发现 .specify/extensions.yml，无扩展后置hook。
- 未完成项不勾选：官方 CLI 的 MCP启动接线、原生工具封闭、系统/云配置隔离、native/live证明仍待实施。tasks仍76/112；用户选择已经确定，不再需要接法偏好确认。

## Codex 路线重新评估完成（2026-09-17，取代此前接法结论）

- 用户质疑MCP必要性并明确要求重新评估；本轮仅核对冻结starter、固定Codex源码、现行规范和实现，未继续MCP接线、未改动运行代码或权限配置。
- 报告：codex-execution-reassessment.md。推荐普通Codex委托保留官方CLI与原生工具，由agentcfg管理整次授权、沙箱、工作区互斥与生命周期；Task Keeper/受控Pi工具保留逐请求/逐工具门控。MCP强制IO替换暂停，不再作为默认交付前提。
- 这项建议包含真实契约变化：直接CLI不承诺逐工具grant复核或撤权零延迟；取消到物理终止的窗口须保留写锁。父deny、不可表达限制拒绝、原checkout禁写、预算边界与真实证据要求均保留。现行spec/contracts/schema尚未改成新授权模型，不以评估直接扩大权限。
- 查明原生路线实现冲突：全部delegate-write强制验证桥的mutation journal会误拒原生写入；原生权限投影不能自动等同工具级FilePolicy；MCP脚本已纳入runtime复制闭包，后续需明确分离。可复用的父子终止校验、普通tool:ID修复等保留，不能整块回滚。
- plan/research/tasks状态及Codex接口说明已标记重评估结果，报告列出逐文件/任务修订、旧高级操作映射和测试顺序。112项任务、76项勾选保持原状。
- 文档相对链接、代码围栏、任务ID唯一性及git diff --check通过。本轮未执行测试套件或真实宿主/账号/模型调用；评估完成不代表实现或原生验收完成。

## 按原生CLI路线继续实施（2026-09-17）

- 用户“继续”后同步spec、Permission Policy、委托契约、data-model、plan/research/tasks、validation-matrix/quickstart与技能API。两种边界正式分开：Pi受控工具/Task Keeper逐动作；Codex原生沙箱整次授权和停止撤权，停止窗口写锁保持。
- 新pi_delegate_policy.py冻结execution_policy；request/receipt V2必填execution_boundary与execution_policy_digest，backend固定映射，resume不能更换边界/策略。旧记录缺字段不补默认值认证/恢复。
- Codex显式native_execution={allow_shell,tool_network:none}，配方和schema已登记；真实命令构造按该声明设置shell_tool，原有文件/command deny可表达性拒绝保留。
- 原生启动授权由supervisor落盘，绑定本次run/request/runtime/lease/generation/cwd和编译权限；线上/离线结果校验该授权。原生候选编辑不再被强制要求MCP mutation journal；缺授权、错授权或结果/候选/物理证明不全仍失败。
- 默认controller取消MCP原型命令注册/tick，native-sandbox不能调用受控文件RPC；pi_vendor排除MCP脚本和两原型Python模块。原型源码及隔离测试保留，父子物理终止和普通tool:ID修复保留。
- Pi入口与共享manager检查新增边界身份；Pi主入口同时检查冻结策略及定义摘要。策略失配由controller.tick请求停止，未物理终止不放写锁。
- 验证记录：docs/acceptance/pi-codex-native-boundary-mock.md。完整Python1104 passed+7 subtests（198.21s）；最终schema补充后相关36 passed；Node委托/manager/tool桥15 passed；subagents临时副本tsc、Pi入口语法、Python compileall和git diff --check通过。任务仍76/112，不以这些mock勾T074或原生交付。
- 仍未解决：官方CLI系统/企业配置及额外资源发现的完整封闭核验、全部目标平台的原生沙箱/终止证据，以及其余US5插件/US6/最终锁与冷重建。没有执行真实宿主、登录或模型。

- 末尾复核补齐保守拒绝：原生投影不再跳过非project根file deny；机器级readonly_roots/denied_roots非空时，因尚无可靠原生投影，明确拒绝准入。未宣称完成这些根规则。最新backend/native组合16 passed（4.20s），offline删除授权也已断言拒绝，静态检查再通过。

## 机器根限制的原生投影完成mock接线（2026-09-17）

- 新pi_native_roots.py冻结机器根与目录身份、project的worktree/git-dir/common-dir身份；execution_policy.root_limits必填并参与摘要。运行时检查原目录和Git锚点，不以路径字符串相同推定身份没变。
- readonly_roots/denied_roots不再一律拒绝，而是保留原路径并按共同Git身份投影到候选；不同Git项目不重绑定。readonly只降低已有write，不给其他目录新增read；具体allow不能重开readonly/deny。
- 声明的非project file deny支持相同映射；目录别名按实际对象关系辅助识别。项目file allow含符号链接父目录也会拒绝，不能偷偷开放根外文件。
- 源根替换/删除导致快照失效，tick请求停止而不崩溃或提前释放；缺失候选限制目标、未知根、exact目录和链接歧义仍明确拒绝。
- 真实resolve_delegate（替身进程、虚构认证文件）用例确认本次permissions与native authorization相同，并验证根变化在CLI创建前失败。
- 固定Codex配置接口进一步核对：exec的ignore_user_config/ignore_rules加载选项不能直接视为app-server config/read的等价条件；未加入不真实的预检认证。系统/企业配置检查仍未闭合，不换用MCP，也不偷偷改变执行入口。
- 首次完整回归因自动审核超时未启动，允许重试一次后成功：1117 passed、7 subtests passed，201.71s。compileall、git diff --check、文档链接检查通过。记录：docs/acceptance/pi-native-root-projection-mock.md。
- 所有操作在仓库/临时环境，未执行真实宿主、模型、登录或操作系统沙箱。任务仍76/112，native/最终交付未勾。

## 普通代码恢复点适配（2026-09-17）

- git-checkpoint已改为实例内持久代码快照，不再直接pi.exec Git stash或在agent_end清空。新增/checkpoint、/checkpoint-restore，自动捕获关联会话叶节点；无UI不自动恢复。
- 新pi_checkpoints.py、pi-checkpoint.py、runtime/checkpoints入口接既有manager与supervisor；默认冻结闭包登记helper，扩展走@agentcfg/pi-runtime导出，启用需显式范围及pi-subagents。
- 捕获和恢复均取得同worktree跨实例租约；FilePolicy逐路径复核，恢复前先检查全部操作权限，预览CAS拒绝窗口变化。恢复前保存备份，磁盘中途失败报告partial并取消fork，不显示成功。
- 快照正文与metadata分开，历史列表不读取文件正文；秘密命名在正文读取前排除。声明max_files/max_bytes/max_checkpoints，超限不截断或自动删历史。quota/theme调整不改变文件范围，policy/runtime/session/project变化拒绝跨范围恢复。
- Task Keeper实际适配器去掉缺permissionAccess时回落parentDenials/[]的路径；父桥、策略摘要、拒绝列表缺失/不匹配均在分配前拒绝。已补真实适配器负向测试。
- 进一步对齐文件权限：Python FilePolicy拒绝未绑定根；PiAdapter验证所选policy的根/command_ref与机器限制引用。managed/Pi delegate额外传递声明根身份仅供拒绝检查，不扩大角色read/write roots；Pi委托显式继承机器readonly/denied根。
- 最新全量基线（后续权限引用补充前）：Python1129 passed+7 subtests（235.55s），Node完整组合152 passed。后续权限补充的定向回归仍需收集；代码恢复点旧dirty-repo-guard、gentle-agent-state、slopchop/readseek等整体T086未因此完成。
- 指南docs/pi-checkpoints.md说明从stash到文件快照的行为差异、配置、权限、备份与限制。未执行真实Pi/Codex/账号/模型，也未对业务工作区执行真实恢复。

### 本轮最终验证与任务状态

- 最终完整Python回归：1132 passed、7 subtests passed，232.02s；最终完整Node组合152 passed，2251ms。Task Keeper与扩展tsc、Python compileall、git diff --check及新增文档链接检查通过。
- T084已按源码与mock要求完成复核并勾选，证据见docs/acceptance/pi-checkpoints-permissions-mock.md。当前77/112完成，35项未完成。
- T086只完成其中代码恢复点适配，整体仍不勾选；dirty-repo-guard、gentle-agent-state、slopchop/readseek等仍待处理。其余Codex配置隔离、最终锁、US6工具链及native/live验收也未因此完成。
- 所有变更留在工作区，未提交、未部署到真实Pi目录，未执行真实宿主/登录/模型或用户代码恢复。

## dirty-repo-guard 受控 Git 状态检查（2026-09-17）

- 删除扩展的裸 pi.exec；新增 pi_git_status.py 和 runtime/git-status，复用 OrdinaryCommands、同一 AgentManager、supervisor 与捕获输出校验。专用 RPC 固定 Git 参数，普通命令仍拒绝 .git 访问。
- Git 工具必须显式声明 executable/version、单一 project/read 根、空 write_roots/args、非交互及超时；PiAdapter 在资源选择时验证绑定和 pi-subagents。所选策略需明确允许对应 tool:ID，不扩大默认权限。
- checkout/linked worktree 的 Git 元数据只读投影，冻结根身份与工作区锚点；检查取得同 worktree 的跨实例租约，活动/未知 writer 阻止新检查。元数据内部根名不会覆盖用户同名项目根。
- 状态结果区分非仓库、干净、脏；非零退出、截断、协议损坏或未验证终止均取消切换。NUL 格式正确计数换行文件名和 rename；无 UI 不跳过脏仓库保护，确认之后再次检查活动边界。
- 命令不继承全局/系统 Git 配置，关闭 optional locks、fsmonitor、hooks、lazy fetch，沙箱无网络、工作树只读。文件/机器 deny 与完整检查范围交叠时明确拒绝，不隐藏后声称干净。项目 Git 配置保留，外部 filter 等依赖不在沙箱内可能失败；尚未原生认证。
- 文档：docs/pi-dirty-repo-guard.md；能力矩阵已同步。T086 仅新增这个子项，不勾选整项，任务仍 77/112。
- gentle-agent-state 后续范围已确认：本机 agent-report.sh 是 dispatcher，tmux 后端使用 pane/window 状态和 socket；Zellij 还依赖 jq、状态文件与 pane/tab rollup；Ghostty 使用 /dev/tty、title 查询/恢复，旧实现还可能启动后台音效或 fish。仅冻结 dispatcher 路径不能算完整依赖闭包。尚未修改/执行这些本机脚本，下一步需把服务端点、终端目标、状态目录、子程序和整个派生进程生命周期显式纳入受管服务；不能借普通 Git 工作区命令放开全局 HOME。

### 本轮最终验证

- Python 完整隔离回归1145 passed、7 subtests（226.92s）；在全量收集后追加的元数据根重名修复由最终定向33 passed覆盖。Node最终完整组合156 passed（2235.68ms），包括 stderr 警告与未知截断标志拒绝。
- 扩展临时副本tsc、Python compileall、git diff --check通过；记录见docs/acceptance/pi-git-status-mock.md。
- requirements checklist仍16/16，未修改勾选；无before/after implement扩展hook。任务仍77/112，未提交、未部署、未运行真实宿主或服务。

## 持续完成剩余任务（2026-09-17，进行中）

用户要求无人工决策部分持续推进，不按单插件停轮。T089、T091 的测试已勾选，当前79/112；其余部分完成的任务不提前勾选。

- 新 pi_evidence/pi_acceptance：私有不可变证据、显式文件清单、固定 scope 摘要、五态支持矩阵、独立 release_approved、旧批准匹配与禁止自动缩减范围。零证据可报告；坏记录/路径/重复/不一致时间报输入错误。
- verify-pi.py + pi_verification/pi_validation 已实现报告/发布检查、严格授权参数、0600原子不覆盖输出和 pytest+Node mock 调度。native/live完整场景仍未接齐，明确 not-run。
- Pi doctor 增加分层 capabilities，认证四态及观测日期，不读原生账号；身份覆盖实际渲染内容与选中技能内容。缺必要依赖输出后返回5；可选钩子用getattr保留不继承Adapter的既有第三方适配器兼容。
- storage.write_new/create_new_private_file 支持原子新建且绝不覆盖；报告允许系统sticky临时目录中的0600文件，仍保持祖先/no-follow检查。
- gentle-agent-state 重写：显式 OSC标题或 agent-report服务；消除固定全局脚本、raw spawn和自动环境启用。服务仅manager可提交、固定state/pane、脚本正文与socket身份复查、私人state根、封闭终端环境，复用OrdinaryCommands/同一manager/supervisor，退出通知有500ms等待上限。新 pi_services、runtime/service-bindings；未连真实终端。docs/pi-agent-state.md。
- pi-rules 0.6.0完整npm源码已校验迁入rules-vendor并适配0.6.0-agentcfg.1：通过supervisor读取显式root_refs，拒绝符号链接/机器deny/未知frontmatter，禁用可空根；无HOME/.claude自动扫描，事件不能扩源。引用技能通过已选资源的ordinary read读取；after-commit nudge有ordinary-helper门控。新增精确yaml/picomatch/typebox mock依赖。
- OpenSpec1.11.0从npm官方归档校验SHA512，纯模板在受限Node环境生成12技能，保存源码/许可证/来源哈希，新增agentcfg-openspec wrapper精确依赖CLI1.11.0并加入四配方闭包。backend.openspec_argv限定所选锁定运行包；项目初始化加Node精确预检和同Git-dir准入锁保护同步CAS，不在业务树运行生成器。
- 新 pi_cold_rebuild：源+锁复制到两组新HOME/checkout（含中文空格），不复制旧实例/node_modules/.pi/venv，独立uv/npm缓存，显式uv sync、agentcfg sync/apply和安装收据核验。安装verified不冒充native执行；原生能力仍not-run。当前尚未接入完整native runner。
- 源码核对确认Task Keeper STORE_SCHEMA_VERSION=3、Pi0.84.4 CURRENT_SESSION_VERSION=3；升级兼容诊断尚待实现。
- 新受控服务促使检查macOS编译策略：父state deny原会覆盖本次scratch；现只从父拒绝中排除显式单次scratch，直接拒绝scratch或内部路径仍失败。只有编译mock，未执行macOS沙箱。
- 当前Node全组合161 passed；第一轮完整pytest1198 passed+7 subtests、2个旧鸭子类型adapter失败，已修复并定向通过。新统一入口首次实际pytest1205 passed+7 subtests（262.42s），Node排序暴露processes-bridge测试裸await不保活问题，已改为测试自持有界等待；排序组合正在复核，不把该次整体算passed。
- 已向用户异步询问其他三个平台测试机/CI入口，以及可选live账号/服务最终选择；尚未获得回答，不把缺授权当not-selected，也不影响继续实现。
- 已下载校验但尚未完整迁移：/tmp/agentcfg-plugin-source-pi-mcp-2.32.1、pi-web-0.27.0、pi-cursor-1.4.29。没有执行包安装脚本、Pi/Codex/OpenSpec CLI、模型或真实终端。


## 持续接通运行包与资源（2026-09-17，仍在实施）

- 用户确认四个平台保留；仅当前 Linux x86_64 可用，其他三个平台保持 not-run。Codex、Cursor、MCP、web、代理、终端全部为已选 live 项，不因缺账号或缺授权转成未选。
- T073 的 Pi backend 已完成本轮代码／mock适配：固定 SDK、closed loader、只读工具、实例账号、精确模型、取消／恢复和事件归一化；新增 Cursor/Bun 原生 provider 适配，直连、零重试，仅复制选中实例的 access token，无 refresh/global token。原生层不在此任务的完成证明内。
- 官方 Codex 0.154.0 四平台资产声明进入 dependencies；锁支持远端 asset，离线读锁不下载，sync 只安装匹配平台。SHA256、归档成员、ELF/Mach-O 架构、执行位与许可证均核验；拒绝归档路径穿越、重复、链接、错架构、超限与原始网络异常泄露。还未执行真实 Codex，也未生成最终锁。
- 修复 doctor 把 Pi 平台列表当 dict 的入口错误，并加入完整 CLI 管线断言。Pi live HEAD 探测仅走显式路线；没有 ambient proxy/NO_PROXY 绕行，无登录或模型调用证明。
- Superpowers 固定 Git 提交完整迁入 14 个技能及配套参考／脚本，保留 MIT 和逐文件源摘要。仅修改版本声明、Pi bootstrap 和 Pi 工具映射；显式资源发现、父上下文注入、重压缩后恢复与 managed 拒绝测试通过。保留重建补丁。
- 已完成适配的 session-yolo、colorful-footer、loop-guard、openai-proxy 补入各完整依赖切片；安装可用与选中加载分开。
- 增加 docs/pi.md，覆盖配置来源、新机管线、精确模型与账号、Task Keeper、model-delegate、四种维护操作和真实尚缺内容。MCP/web、slopchop/readseek 等剩余适配、最终锁、完整 native/live runner 仍未完成。
- 本轮完整隔离验证：`.venv/bin/python scripts/verify-pi.py --tier mock --case all --output /tmp/agentcfg-pi-mock-20260917-assets-resources.json` 返回 0；Python **1234 passed、7 subtests passed（257.51s）**，Node **167 passed、0 failed/cancelled**。只证明该次开发源码的默认 mock；后续依赖切片声明更新尚需定向验证，T105 不提前勾选。
- Node 24.14.0、npm 11.19.1、Bun 1.4.0 的官方固定版本已确认存在；正准备 /tmp 独立构建工具链，不改系统工具链。


### 真实安装试验与服务接线补充（2026-09-17）

- 已在 `/tmp/agentcfg-pi-build-tools-24.14.0` 准备独立 Node 24.14.0 / npm 11.19.1 / Bun 1.4.0，归档均核对官方摘要，未改变系统工具链。
- 临时四配方锁最初发现 Pi 0.84.4 上游 shrinkwrap 6 个嵌套条目省略 integrity。lock 阶段现按精确 npm 版本和相同 tarball 地址补全 SHA512，离线读锁／sync 仍严格拒绝缺摘要。
- Pi 0.84.4 的 npm 包没有 LICENSE；从其 npm gitHead `b79e4cc834970cca69daebffab7df1da7d1e52c4` 取得完整 MIT 正文，通过显式 `license_sources` 入锁和安装，不覆盖冲突许可证。相关 schema/契约与负向测试已补。
- 临时锁 `/tmp/agentcfg-pi-lock-probe-wpwebb0e/locks/pi/manifest.json`，identity `9bc6c24fb8fa359eb7cad08148ea6ff4e866d0f2e81a155f75dc097a05d259e1`，19 个来源、4 个完整切片全部解析通过。它是中间源码安装试验，不是最终候选锁；后续源码修改不继承该身份。
- 在当前 Linux x86_64 上四个临时实例的 npm ci --ignore-scripts、许可／入口与内容收据全部得到 installed：default `/tmp/agentcfg-pi-install-probe-tmp4rjr7`，managed `/tmp/agentcfg-pi-install-probe-gjsk3dfg`，cursor `/tmp/agentcfg-pi-install-probe-1lcknj6i`，codex `/tmp/agentcfg-pi-install-probe-1huzy45_`。Codex Linux x86_64 官方资产完整下载、摘要与 ELF 架构通过；没有运行二进制。Bun 切片现在另核验精确 Bun 版本；Node 切片不要求执行 Bun。
- **上述仅为开发期安装验证，四个 profile 的宿主执行均为 not-run，不构成 T106/native/live 通过。** 其余三个平台仍无机器、未验证。
- MCP 从 npm 2.32.1 完整迁入 110 文件，派生 2.32.1-agentcfg.1；新增只认显式服务的配置、监督 stdio、HTTP/SSE direct/proxy、bearer 与代理 SecretRef、实例私人凭据存储。单服务复用既有 manager，管道按 512 字节 UTF-8 安全分块，背压只重试明确未接收数据；丢输出、未知终止均失败并保留保护。
- MCP 目前仍未登记到最终 source_ids：OAuth/UI/scripting/sampling 的完整适配与实际插件加载尚缺。stdio/HTTP/存储模块隔离测试通过，整个派生插件在固定 SDK 与 MCP 2.0 类型依赖下 tsc 通过。新增服务 TOML 示例已通过真实 load_workspace/schema/交叉引用验证。
- 配置入口／Pi/MCP 管线／DSH schema 定向回归 112 passed；Bun/doctor/可选能力后续 25 passed。后续新增 MCP 与 BTW 改动尚待下一次统一默认回归。
- BTW 正在收尾：受约束 ModelRuntime 和只读配置沿用；浏览器链接与剪贴板改为终端 OSC 8/52，消除 detached 桌面进程；配套类型检查进行中。其新 fork 尚未完成最终依赖登记。


### T085 辅助插件收尾（2026-09-17）

- BTW 0.55.3-agentcfg.1、Smart Compact 9.6.0-agentcfg.1 进入四配方 source_ids；保留完整来源与 MIT、生成可重建补丁。BTW 使用适配后的 src 入口，旧 dist 不进入运行归档。
- BTW 和 Smart Compact 的配置／交互选择现在只访问受约束 ModelRuntime；明确指定而不可用的模型不会回退到主模型或列表首项。统一 Python helper-model 校验和原稳定错误码保留。
- Smart Compact 的实际插件登记经过假 SDK 集成测试：3 个工具和命令统一拒绝 managed helper；session_before_compact 只有一个 owner，拒绝时 cancel，不转给原生第二压缩者；恢复会话前检查活动边界。
- BTW 完整 src 在固定 SDK 下 tsc 通过；界面链接／剪贴板通过 OSC 8/52，无 desktop detached spawn。该界面行为仍待真实终端验收。
- Python 本批首次 53 passed / 1 failed：重复校验改变错误码；已移除重复校验并重跑相关配置测试通过。Node helper/压缩/代理/终端集成 31 passed。
- T085 仅标记代码与 mock 收尾。T086 的 slopchop/readseek 及后续插件、最终锁／原生验收仍保留未完成。

### T086 Slopchop 与受监督终端（2026-09-17）

- Slopchop 0.10.1-agentcfg.1 完整源码接入四配方；从固定 npm 归档重新核对 SRI 和全部 15 个原始文件摘要，生成 `slopchop-agentcfg.patch` 并保留 MIT/NOTICE。固定 SDK 与 `@pierre/diffs@1.2.1` 下完整 TypeScript 类型检查通过；本地确定性归档校验通过。
- Git 审查使用封闭参数与 NUL 输出；正文读取走现有 FilePolicy。嵌套仓库父子租约及只读子模块元数据核验保留。编辑器仅接受显式工具绑定和字面参数，并复用跨实例写租约。
- 新增私人 PTY 的 IO/尺寸、Linux 执行许可后取得控制终端、macOS 单设备写规则、父终端输入恢复。假设备／假进程覆盖，不启动真实终端。macOS helper C 源码进入 launcher 的来源闭包；本机 macOS 构建与输出锁仍未闭合。
- 本批 Slopchop/依赖/配置 Python 定向回归 60 passed；PTY/host/checks 21 passed；Codex 参数/PTY/editor 25 passed。Node Slopchop/terminal/MCP/storage 9 passed；随后 MCP 上传取消新增测试 2 passed。
- Codex `projects` 参数改为整个 inline table，修复 CLI 按点拆键造成的特殊路径错误。系统／MDM／云配置准入仍未完成，两个方案见 `codex-config-admission.md`，已向用户请求架构选择。
- MCP 上传请求体改为有界流读取；传输关闭会取消未完成 body，禁止在关闭后补发请求。完整 OAuth/UI/script/sampling 适配仍未完成，未登记最终发布切片。
- T086 仍未勾选：ReadSeek 专用受限执行与符号多文件写入等尚未完成。没有把本批隔离测试计为 native/live；全部已选服务和三个暂无机器的平台继续保留待验收。
- 本批统一 `verify-pi --tier mock --case all` 已完成：1273 passed + 7 subtests，Node 182 passed，报告退出 0。记录见 `docs/acceptance/pi-review-terminal-mock.md`。mock 使用 Node v24.1.0，不作为锁定 Node 24.14.0／Bun 原生证明。任务总数仍为 81/112。


### T074–T081 官方 CLI 受限准入闭合（2026-09-18）

- 用户明确选择保留官方 CLI；系统／企业配置无法核验时拒绝，接受兼容性缺口。决定同步 plan、配置准入评估、用户文档和支持矩阵；不删已选账号／平台范围。
- 新增 `pi_codex_admission.py`：系统 Codex 目录不存在／为空；macOS 使用同名 CoreFoundation 域与键，仅判断存在性；实例账号只接受已知个人 OAuth 或明确 API key，组织、未知、混合身份拒绝。测试只用临时目录与虚构认证，不读取真实账号。
- 父 resolver 启动 worker 前检查；worker 启动 Codex 前再查并复核 grant。策略 `official-cli-restricted-v1` 纳入执行身份。登录还拒绝实例已有 config.toml；不改写系统或账号文件。报告无账号 ID／令牌／配置正文，明确 atomic_config_binding=false。
- 默认 doctor 不读认证，只展示受限条件。监督 RPC、独立 CLI、Pi 工具与登录通知只放行固定原因码，未知错误继续脱敏。
- 重新核对 T075 的三重写授权、跨实例 linked worktree 租约，T076 的 start_unknown/poll/wait/resume，T079 的终态 CAS／收据／物理终止，T080 唯一 manager 外部委托，T081 单一工具与显式登录。对应实现和 fake 链路已有，Codex 准入缺口在所选受限路线内补齐后，标记 T074/T075/T076/T079/T080/T081 的代码与 mock 任务完成。
- 定向 Python 委托回归 148 passed；Node 后端／manager／工具／登录 19 passed。公开拒绝码和 doctor 后续新增测试首次 65 passed / 1 failed（fixture 插件选择不完整），修正后准入／doctor 39 passed；最后相关 Python 66 passed，Node 控制通道／工具／登录 10 passed。
- 新计数 87/112。这些标记不表示原生通过；T086、US6 剩余适配、最终锁和 T106–T112 仍未完成。稳定受信机器与账号是前提，启动预检不防管理员或账号类型在运行中改变。
- Codex 本批完整 `verify-pi --tier mock --case all` 通过：1315 passed + 7 subtests，Node 183 passed，报告 `/tmp/agentcfg-pi-mock-20260918-codex-admission.json`。开始于 2026-09-18 02:41:28 UTC，结束于 02:46:24 UTC。MCP sampling 的后续新增用例不在该次预先收集的清单内，另行验证。

### MCP sampling 接入（2026-09-18，T094 部分工作）

- `agent_options.mcp.sampling` 显式启用、绑定模型／单次 max_tokens／是否自动批准。默认关闭；启用时模型必须属于当前实例模型集合。保留原有请求与返回两次用户确认。
- vendor sampling handler 使用当前 ModelRuntime，禁用重试，不扫描 modelRegistry 账号、不直接取 API key、不按远程 hints 更换 provider/model。受管调用、未选模型和超限请求在调用前拒绝。
- 新 Node sampling 用例 2 passed；完整 MCP 源码 TypeScript 检查通过。初次 TS 检查暴露 pluginSettings 的 unknown 类型，已补充明确接口。Python 首次配置集 19 passed / 1 failed（新 fixture 漏选 pi-permissions），补齐后该新增用例通过；后续统一回归待最后批次执行。
- MCP 来源补丁和 NOTICE 已更新。OAuth、脚本、UI 服务及最终切片登记仍未完成，T094 不勾选。

### MCP elicitation／脚本监督（2026-09-18，T094 部分工作）

- elicitation 由显式 boolean 启用；表单与 URL 请求核验所选服务。URL 经过协议／凭据／控制字符校验，经用户确认后输出 OSC 8 链接，不派生浏览器。完整 SDK 类型检查通过；URL 分支使用假 SDK 错误类型隔离验证，不把它算成表单 validator 或原生终端通过。
- scripting 增加显式 Node tool_ref 与 max_seconds。解释器版本声明须匹配锁定 Node，固定脚本入口来自运行包，命令规则必须明确允许。`pi_mcp_script.py` 只挂载入口／解释器和每次运行的私人目录，无业务工作树、账号环境或网络；执行与取消复用 OrdinaryCommands 和唯一 manager。
- 新 `mcp-script-process.mjs` 以 JSONL 收发代码／工具请求；原 JS VM 只负责计算上下文，实际 IO 边界由监督进程沙箱约束。父侧 SupervisedScriptWorker 处理重复请求、超限帧、取消、迟到租约和物理终止；mcp-code 在关闭时等待已派发请求 settle。未取得终止证明不能报告完成或释放操作。
- pi-mcp 最终切片尚未登记；安装器已声明未来所选 source 的固定脚本入口，缺入口时明确失败。普通 `mcpScript` 仅 main 角色且明确启用后可进入；readonly/managed 不因此获得脚本权限。
- 修复监督 RPC 将零写入背压统一遮蔽的问题：仅公开 `ORDINARY_STDIN_BACKPRESSURE`，未知管道失败仍脱敏且不自动重发。stdio 改为严格 UTF-8 解码。
- Python 脚本准入 10 passed，后续脚本／配置／监督／依赖／Codex 定向合计 83 passed；Node 本批控制／sampling／elicitation／stdio／script 14 passed，随后 unknown-termination 补充后 script 5 passed。完整 MCP TypeScript 检查与新进程脚本语法检查通过；没有执行真实解释器脚本进程或宿主。
- T094 仍未勾选：OAuth、MCP Apps UI 服务、direct-tool 配置与最终切片尚待收尾。ReadSeek、web、最终锁和原生／实网验收也仍未完成。
- 后续补充：Codex 父 resolver 移除重复且错误分类为凭据缺失的元数据分支，统一调用同一配置准入函数；对应 54 项隔离回归通过。数据模型／委托契约／技能 API 和使用说明已同步新配置准入策略及 Cursor OAuth 的当前适配状态。
- 最后本批统一默认回归完成：1327 passed + 7 subtests，Node 192 passed，`verify-pi --tier mock --case all` 退出 0。记录见 `docs/acceptance/pi-codex-admission-mock.md`。本批任务仍为 87/112，未执行宿主或实网验收。

### MCP OAuth／Apps／直接工具及依赖接通（2026-09-18）

- 直接工具与服务 namespace 工具用实际登记表准入，按当前服务／原始工具名匹配选择；撤销或替换登记后旧函数失效。readonly 与 managed 上下文仍拒绝。严格 schema 使用闭合对象 `direct_tools={enabled,tools?}`，未放宽核心 schema 子集。
- OAuth 支持明确客户端凭据、HTTPS 手工回调和固定 loopback 回调；发现／换码／刷新绑定同一显式路线与授权源站。服务 Bearer 不传给不同源的授权端点，浏览器授权 URL 也核验声明源站。无动态凭据命令、二次环境展开、系统 keyring 恢复、旧明文导入或删除。
- 修复上游将 `!` 开头 client secret 当命令的问题；客户端秘密保持字面值。私有存储及内存缓存按认证绑定建立账号键，切换 client ID／认证契约不借旧账号。无 client secret 的公共 OAuth 也正确显示认证未检查。
- Callback 和 MCP Apps listener 属于现有 manager，物理进程为 supervisor 已持有的 Pi。Apps 两个 loopback 端口共用一条记录，关闭等待 socket 和发出的请求；关闭未知不消耗记录。启动请求取消与会话生命周期分离，避免正常返回 auth-start 后误关回调。浏览器源站／权限显式配置；GUI 统一为用户打开终端链接，移除自动浏览器／Glimpse／全局 npm 探测路径。App 请求新 agent turn 需要交互确认。
- MCP 派生源码、完整 scripting skill、MIT／NOTICE 和全文件补丁已登记四配方；T094 仍包含未完成的 web 等工作，不因此勾完成。
- Node 定向 MCP／IO 回归 27 passed，包含生命周期、来源与字面凭据验证；完整 MCP TypeScript 检查通过。Python 配置／资源／依赖／诊断定向 48 passed；公共 OAuth 诊断补充后 doctor 9 passed。
- 完整 mock 回归：1328 passed + 7 subtests，Node 203 passed，报告 `/tmp/agentcfg-pi-mock-20260918-mcp-oauth-apps.json`。后续单个 cleanup await／doctor 补充由定向检查覆盖，最终候选身份尚未冻结。
- 真实在线锁解析只在 `/tmp/agentcfg-pi-lock-probe-rcj58pc1` 隔离副本进行：23 个来源、四配方通过；中间锁 identity `8fdba9c62a4c15404ef56994ccb6154e7d3c62d8e52eba73a754de4763120fe0`。随后所有四配方 npm ci --ignore-scripts／运行包密封通过，分别位于 `/tmp/agentcfg-pi-install-probe-fttjrq3d`、`hghhjykq`、`1f_v2xxp`、`w2nclq0y`。日志中的 pi-host LICENSE 是 overlay 前诊断，最终安装已核验许可证。
- 上述安装全部 host execution=not-run。未执行 Pi/Codex/Cursor/MCP 真实宿主、账号调用或浏览器；仓库最终锁仍待 ReadSeek/web 等源码完成后生成。后续 Pi npm 环境另显式关闭 user/global npmrc 并使用私人缓存，避免借用全局 npm 配置；不更改 DSH 环境。

### ReadSeek 文件边界基础（2026-09-18，T086 未完成）

- 多文件提交先全量检查目标权限和基线，再逐文件 CAS；日志分别保存不可变计划、逐文件意图／完成记录及进度。撤权或失败保留中断记录，不自动回滚或重做前缀，不把部分写入报成整次成功。新增 expect_absent 防止新文件竞争覆盖。
- 私有副本导出只读取当前 FilePolicy 允许的文件，不挂载业务树或 Git 元数据，不跟随链接；显式 Git 文件选择不会被文件系统 fallback 扩大。输出记录范围完整性、限制和内容摘要，提交前可重新检查源漂移。
- 对真实临时文件的回归：事务／GuardedFiles 首批 17 passed，补充 noop 基线与旧文件操作后 24 passed；副本／事务／GuardedFiles 22 passed。没有执行 ReadSeek 原生程序。
- 后续还需接上完整九工具、受监督原生 worker、逐文件来源映射、会话 anchors、Git 选择及 native/vision 依赖；当前仅完成可复用文件边界，尚未登记 ReadSeek 最终配方，T086 不勾选。
- 真实 npm 配置检查发现 user/global 同时指向 `/dev/null` 会报 double-loading；已改为临时 HOME 内两个独立、未创建的 npmrc 路径。固定 npm 11.19.1 的实际版本检查退出 0，相关环境与依赖回归继续通过。早先四配方安装发生在此隔离增强前，不能把它们写成增强后重新安装的证据。

### ReadSeek worker／产物接受与 Git 选择（2026-09-18，T086 仍未完成）

- 从原九工具提取封闭参数契约；父侧包装保留界面而不运行原始文件操作，worker 登记时再次核对契约。worker 的固定入口、取消、私有产物和 accepted 握手已实现；完整监督器控制器尚未接通，不能因这些基础模块存在而标记可运行。
- 新 `pi_readseek_results.py` 验证调用/工具/副本/实际计算文件摘要，拒绝只读写入、写错文件、删除、链接、错误结果伴随写入、源漂移与非法 anchors。结果与 anchors 只在受控提交接受后发布，保留多文件中断日志。
- Git 查询类别保留 cached/others/ignored 与默认 tracked+untracked；私有 shim 只返回已选已导出文件。修复普通目录 fallback 与 Git 对 target/node_modules 的不同语义。无法进入 agentcfg 路径契约的控制字符/反斜线/无效 UTF-8 文件名明确拒绝，没有默默丢项。
- 原 npm ReadSeek 来源全部文件摘要再次核对，补充 SOURCE/NOTICE 和可重建来源补丁；仍未登记最终 recipe。MCP 全文件补丁也重新生成，包含之前的 cleanup await。
- Python 本批最终定向 51 passed；Node 8 passed。先前测试发现 Path/str 类型、路径拒绝码以及 Node 权限模式不支持 fsync/symlink 的测试问题，已修复；符号链接拒绝继续由 Python 真实临时文件覆盖，未放宽隔离。
- 临时依赖安装使用 ignore-scripts。固定 Node 24.14.0 + Jiti 2.7.0 的假 Pi 登记核对九工具契约成功；未调用任何工具、宿主或原生 ReadSeek。安装规则下六模块语法检查通过。说明见 `docs/pi-readseek.md`。
- 任务计数保持 87/112。ReadSeek controller、原生/视觉依赖、web、最终锁及全部 native/live 仍待完成；其他三个平台继续未验证。
- 本批完整 `verify-pi --tier mock --case all` 已结束：1358 passed + 7 subtests，Node 211 passed，两个 runner 均退出 0。报告 `/tmp/agentcfg-pi-mock-20260918-readseek-boundaries.json`，正式说明见 `docs/acceptance/pi-readseek-boundaries-mock.md`。统一 mock 的 Node v24.1.0 不作为锁定 Node/Bun 的原生通过证据。

### ReadSeek 监督控制器与目录执行接通（2026-09-18，T086 仍未完成）

- 正式 ordinary_readseek RPC 串起准入、私人副本、结果接受、分块返回与终止后发布；复用 OrdinaryOperations/OrdinaryCommands、现有 manager 和同一工作区租约。接受回复丢失不重复提交；未确认终止不能丢弃记录或发布 anchors。
- 新第一方 `pi-readseek.py` 在同一租约内执行固定 Git/rg 只读选择，再请求监督器导出，最后进入计算沙箱。第三方进程不接收控制凭据；超限清单由内核文件大小限额拒绝。driver 的 subprocess/exec 在默认测试中均为替身。
- 保留子目录 cwd 的 workspace rename 范围；grep 使用原项目忽略规则进行选择，副本 rg 不再次用忽略规则丢项。私人 git/rg 入口只接受固定参数，rg 收到取消信号后等待原生子进程关闭。
- 补充只读预留到期回收、会话更换后旧工具失效、MCP 不得冒用 ReadSeek 名称，以及只读 16 MiB/写入 1 MiB 的统一文件上限。schema 保留原插件设置，拒绝 overrideTools。
- ReadSeek 0.9.16-agentcfg.1 派生来源登记四配方；固定 API、diff、xxhash 和 SDK peer 版本。原生安装器校验已安装 npm 平台包、ELF/Mach-O 头、版本与许可摘要，不执行二进制。LGPL 原文取自固定提交的 packages/readseek/LICENSE，记录来源与摘要。macOS x86_64 源码构建、视觉资产与原生缓存连续性仍未完成，不把缺预构建包写成已支持。
- Python 控制链/普通工具/依赖定向最终 86 passed；后续 native/vendor/dependencies 30 passed、来源/配置/可选能力 49 passed；Node 定向 24 passed。初次更改发现 ReadSeek driver 不应强加给未选切片，改为仅所选来源安装，对应 34 项回归通过。新增只读媒体上限用例随统一回归执行。
- 临时真实锁解析在 `/tmp/agentcfg-pi-lock-probe-hg_lcmmz` 完成：24 个来源、四配方，identity `2f68db97fc2911cf11698bc6f250d982a837f3139fed348f6023152e7b10abd3`。它是媒体上限/旧工具失效补充前的中间源码副本；不能当作最终候选身份。四配方临时 npm 安装检查与当前源码完整 mock 已启动，结果尚待记录。
- 任务仍为 87/112。未执行任何真实 Pi/ReadSeek/Codex/Cursor 宿主或账号调用；其他三个平台继续未验证。
- 本批完整默认回归通过：1390 passed + 7 subtests，Node 216 passed；报告 `/tmp/agentcfg-pi-mock-20260918-readseek-controller.json`。四配方中间候选实际 npm ci/原生文件投影/密封也全部成功，均 host execution=not-run。确切目录、身份和源码时间边界见 `docs/acceptance/pi-readseek-controller-mock.md`。

### T086 代码/mock 收尾与视觉资产（2026-09-18）

- ReadSeek 固定视觉数据进入四配方完整来源；资产 schema 支持有大小与 SHA-256 的跨平台 raw data。同步流式下载、单链接原子发布，运行包盘点改为流式哈希。Tree 保留 no-follow/文件身份复核；DSH/部署/运行与资产定向回归 152 passed，后续边界复验 107 passed。
- 两份真实 GGUF 文件实际下载并通过大小、SHA-256 和格式核验，共 1,552,463,168 字节。源修订和许可声明已核验并保存；没有执行推理。Node 仅挂载只读模型缓存，完整数据闭包缺失时不允许生成所选 ReadSeek 安装。
- 同会话/权限/实例契约使用稳定副本与缓存路径；保留同一源句柄的 mtime，先证明上一操作终止再清理私人副本，清理不跟随链接。未知执行继续独占会话；权限契约变化不复用旧缓存。相关文件/受管/委托回归 78 passed。
- 普通 stdio 生命周期提取为 `supervised-stdio.ts`，MCP 与 ReadSeek 分别绑定协议，继续共用唯一 manager。没有修改官方 Codex CLI/native-tool 路线。pi-processes 补齐 119 个原始文件及 npm SRI 核对、SOURCE 与可重建补丁；T086 路径从未使用的 ordinary-tools.patch 改为实际 SDK 包装入口。
- 完整默认回归：1406 passed + 7 subtests，Node 216 passed。随后 bootstrap/managed 活动下可用性查询改为不可用元数据，不使 session hook 报错；实际调用继续拒绝，定向 Node 20 passed。未执行宿主。
- 新临时锁 `/tmp/agentcfg-pi-lock-probe-8hwkbi6f` 包含 26 来源、四配方；四配方包含视觉数据的真实安装/密封均成功。该候选早于闭包加强/bootstrap 修订，最终锁不继承其身份。完整目录与证据边界见 `docs/acceptance/pi-readseek-vision-mock.md`。
- 复核 T086 其余子项已有的 dirty guard、checkpoint、通知、agent-report、processes、Slopchop/editor、可写检查和共享工作区保护；结合 ReadSeek 控制链完成，标记 T086 代码/mock 完成，任务计数 88/112。
- macOS x86_64 ReadSeek 来源构建、US5 清单/调用方收尾、web、最终锁和全部 native/live 仍保留未完成。其他三个平台继续未验证，不将源码/数据/安装检查升级为原生通过。

### Web 配置、请求与生命周期基础（2026-09-18，T094 未完成）

- 完整导入并核验 pi-web-access 0.27.0 原始 73 文件及 npm SRI；保留许可证、媒体、SOURCE 与全量派生补丁。尚未登记 runtime recipes，不能把源码迁入当作 Web 可用。
- Python 投影新增显式 Web 服务、origin、网络路线、秘密引用及模型用途；配置模块改读 manifest。HTTP 使用私有 dispatcher，检查公共 DNS/私网/映射地址，固定连接地址并保留 Host/TLS 身份，限制请求和响应，代理失败不直连。Gemini Web 保留足够的显式响应头预算。
- 同进程 MCP/UI/Web 资源记录复用唯一 manager，最多 16 个，不占两个实际执行槽位；真正 session/managed/external 执行仍共用上限 2。关闭未知与取消待确认继续保留记录；合同与 vendor NOTICE 已更新。
- MCP 清理绑定到 adapter generation 和 runtime，修复旧实例清理同名新工具风险。Web/MCP 共用名称所有权，Web 的工具、命令、快捷键与后台链接入现有 manager；会话关闭等待 Web 活动终止。
- 摘要/查询改写/页面问答使用当前受约束 ModelRuntime 和已选模型，禁用隐藏备用模型及重试；不读取全局/项目 settings。搜索服务可用性先验证显式选择；ADC 只读引用数据，不读 gcloud 文件。
- 定向测试先后 13、13、19 passed；Web 与 MCP 全源码 TypeScript 检查通过。修正 Node 24.14 权限模式下模块边界测试，以 package main 逃逸替代创建 symlink，生产 realpath 检查保持不变。
- 完整 mock 回归输出目标为 `/tmp/agentcfg-pi-mock-20260918-web-foundation.json`，当前运行中，结果另记。此前 1406 Python/216 Node 的完整通过不能当作这批新改动的证明。
- 浏览器 cookie/认证抓取、订阅账号服务、Git/媒体子进程、curator 监听器和完整设置闭包继续未完成。总任务仍 88/112；其他三平台仍未验证，没有真实宿主或账号调用。

- 第一轮 Web 完整 mock：51 failed / 1367 passed / 7 subtests，Node 245 passed。失败统一来自 Web provider 的无显式类型 anyOf，不是 DSH 行为变更；保持公共严格 schema 不变，将多服务选择投影为显式 `web.providers`，单服务仍为字符串。修复后相关 DSH/Pi/公共扩展回归 47 passed。
- 模型调用另登记同一 manager 的 external/model 执行，继续占实际槽位；取消未知不释放。搜索订阅认证改为显式模型用途、实例 ModelRuntime 和最小生成环境；无模型遍历、无全局账号 fallback，认证错误脱敏。相关定向 Node 17 passed，后续凭据 auth_kind 契约复验 3 passed。
- 第二轮完整 mock 输出目标 `/tmp/agentcfg-pi-mock-20260918-web-foundation-fixed.json`，当前运行中。来源补丁已重新生成并核对 73 个原始摘要。
- T087 完成：四配方/目录/37 调用方/七模板的旧入口退出清单已核对；独立契约 36 passed、生命周期 37 passed。说明与 T088 尚缺 runner 链测试见 `docs/acceptance/pi-model-delegate-mock.md`。总任务 89/112；T088 和 T094 均仍未完成。

- 第二轮完整回归通过：1420 Python + 7 subtests，249 Node；11:59:47–12:05:52 UTC。详见 `docs/acceptance/pi-web-foundation-mock.md`，其后的变更单独列出验证边界。
- T088 补齐插件→Runner→RPC 的 14 个 backend/preset 组合、进度/取消、终态拒绝和旧运行时拒绝；定向 Node 28 passed，model-delegate TypeScript 通过。标记 T088 代码/mock 完成，不升级原生或账号状态。
- 补齐 Web doctor 的显式服务 HEAD 探测、公共目标未指定和无凭据不需登录分类；Web 依赖明确包含 manager/权限。诊断/证据/固定范围/升级/可选能力/目录定向 Python 80 passed。T090、T092、T093 完成，说明见 `docs/acceptance/pi-diagnostics-mock.md`。
- 当前任务 93/112。T094 的 Web 浏览器与进程适配、最终锁、原生 runner 和 native/live 均继续未完成；其他三个平台仍保留未验证。

### Web curator 生命周期接入（T094 继续）

- 抽取 `owned-listener.ts`，MCP 的 callback/apps 和 Web curator 共用唯一 manager 的资源生命周期；MCP 定向兼容 8 passed。
- Web curator 明确选择 browser_network，默认只绑定 127.0.0.1；检查 Host/Origin，设置无 referrer/CSP，请求脱离已结束工具的旧异步上下文并分别保留活动。关闭中止请求，等待实际结束；关闭失败保留记录。
- 页面 marked 从当前 runtime 的固定 18.0.5 包读取，检查包版本与路径边界；移除 CDN 与外部字体。浏览器由用户打开本地链接，移除全局 npm/Glimpse 查找及自动桌面启动。
- 模型/认证/HTTP 活动/curator/MCP listener 定向 Node 22 passed；补测三个 Web 模型请求共享两个实际执行槽。Web 完整源码 TypeScript 通过。配置/目录/依赖定向 Python 仍在运行，另记结果。
- 本批在完整 1420 Python /249 Node 报告之后，不能继承该完整报告的源码身份。T094 未完成，Web 仍不登记配方；远程 curator、cookie/认证抓取、Git/媒体进程与完整设置闭包继续处理。总任务仍 93/112，native/live 未运行。
- curator 配置/目录/可选能力定向 Python 40 passed；后续显式 cookie 的认证页面抓取接入 `web.services.authenticated`，精确 HTTPS origin、只读方法、禁止传入认证头及逐跳检查。相关 Node 13 passed、配置/doctor/schema Python 32 passed。
- GitHub 的仓库大小、默认分支、树、README 和文件 API 读取改走显式 github 服务及可选秘密引用，未调用 gh；树响应截断明确报告。移除 SSRF 中环境代理豁免分支，环境变量不能跳过地址检查。相关 Node 11 passed、Web 全源码类型检查通过。
- GitHub clone 与 PR/issue CLI、浏览器数据库/解密、媒体进程、远程 curator 和完整设置闭包继续未完成；Web 不登记配方。源码与补丁需随这些适配继续刷新；没有真实宿主、浏览器或账号调用。
- GitHub PR/issue 详细视图已从 gh 子进程改为固定只读 GraphQL/REST，经同一显式服务、路线及凭据入口；保留评论、审查、提交、检查和关联条目。100 项连接边界明确报告，GraphQL 部分错误不能当完整成功；实际提取函数也纳入假 HTTP 测试。相关 Node 5 passed，TypeScript 通过；字段已查官方 schema，没有账号调用。
- 移除几个原生配置 reader 的跨运行时缓存短路；ADC token 缓存按 runtime 与凭据摘要分域，并防止刷新过程中身份变化后发布旧 token。相关配置/提取 Node 9 passed。clone、媒体、浏览器 cookie 数据库和远程 curator 仍未完成。

### 浏览器 profile 与认证数据库（T094 继续）

- 最新稳定完整回归 `/tmp/agentcfg-pi-mock-20260918-web-ui-api.json`：1424 Python + 7 subtests、266 Node，12:46:50–12:53:02 UTC，复核期间无相关源码变化。以下浏览器变更晚于该报告。
- 固定 Bun 1.4.0 的内存 SQLite 检查返回 3.53.2；只验证内置库可用，没有 Pi/Cursor 宿主、真实浏览器或账号通过结论。
- 新增显式 browser_profiles、Gemini profile 引用及 auth_fetch 的 browser_profile/cookie_ref 二选一。派生 manifest 给普通工具加入浏览器根硬拒绝，来源不变；密码只解析生成的秘密引用，缺失先于数据库读取拒绝。
- `BrowserSnapshots` 经同一 supervisor 的 ordinary RPC 复制 DB/WAL/SHM：no-follow、单链接、身份复核、总大小限制，拒绝并发 checkpoint。工作副本留在受保护认证缓存，不使用全局临时 cookie 目录；到期清理绑定代次，旧清理不能删除新副本，重启后再使用时回收带本实例标记的过期副本。
- 原生 reader 只消费已验证副本与声明密码，保留现有 POSIX 解密逻辑，使用内置 node:sqlite，去掉全局 profile 扫描、keychain/secret-tool 和外部 SQLite/Python fallback。合成加密数据库经过实际 reader 与认证 fetch 测试；没有真实账号访问。
- 聚合搜索的路由测试发现 service 检查误用了 gemini-search 模块名；已修复并验证 provider 数组及 all 都能实际分派到已选 Brave，未选服务零调用。增加固定 linkedom 0.16.11 纯 DOM 测试依赖，安装使用独立 HOME/cache 和 --ignore-scripts；默认测试继续阻断网络与宿主。
- 浏览器相关定向测试先后 Python 39/35/37/20 passed，Node 7/8/12/13 passed；各批对应其当时改动。后续已补 Cookie profile 的认证 fetch 联通、Unicode profile 和单标签 HTTPS 主机，结果另记。T094 未完成，任务仍 93/112。

### 媒体权限与长期服务容量（T094 继续）

- 远程 curator 增加明确 bind/advertised_origin，严格 Host/Origin，保留原浏览器功能并消除主机名猜测。curator/MCP listener Node 10 passed，相关 Python 回归 55 passed。
- WebFiles 复用 ordinary read 权限，流式冻结大媒体到私有只读副本；上传不再直接读取原文件，去掉近似文件名扫描。相关 Python 17 passed；输入缓存隔离、摘要校验、终止后清理 Node 14 passed。
- 本地 FFmpeg/ffprobe 改经固定 argv、无网络沙箱、唯一 manager 和 supervisor；不挂原项目，输入有独立完整性校验、关联命令结束前拒绝清理。补充已验证二进制输出回调，截断/失败/未知终止不返回成功帧。Python 18 passed、Node 6 passed，Web TypeScript 修订后通过。
- 长期 MCP stdio 经专用准入登记为服务资源，任务仍上限 2；监督者服务上限 16，manager 资源总上限 16。不改旧租约 schema，公开 allocate 无服务分类字段，恢复仍保留未知活动。专用服务名进入幂等摘要和持久记录；真实终止/文件范围/工作区租约仍保留。相关 Python 32/37 passed、Node 5/17 passed。
- 新增真实 manager 联通测试，修复同一 Web 操作的辅助模型阻断自身 HTTP/凭据/文件 IO：内部 service_owner_run_id 只能指向活动 resource，模型仍占任务槽；其他操作、managed/session 和取消未知不能借用。Node 30/33/21 passed，subagents TypeScript 通过。
- 剩余主要为联网 Git clone、YouTube/远程 FFmpeg、全部配置与依赖闭包收尾，以及最终锁和 native/live。Web 仍未登记配方；任务仍 93/112。没有真实 Pi/Codex/Cursor、浏览器或账号调用。
- 浏览器/媒体/服务容量完整回归已完成：`/tmp/agentcfg-pi-mock-20260918-web-browser-media.json`，15:35:11–15:41:53 UTC，1456 Python + 7 subtests、283 Node 全部通过；运行期间无相关源码修改。Web 与 subagents 类型检查通过。最新 subagents 补丁 SHA-256 为 `4321cac1e2a858ffcfbd6b61ff3e00610775ee1aacf89f39282079c4225c2f34`。
- 本机只读命令发现确认当前 PATH 没有 ffmpeg、ffprobe、yt-dlp；有 bwrap 与 Git。尚未执行这些媒体宿主或修改机器安装；后续需补可复现获取与原生绑定。联网 Git/YouTube 路径仍待完成，Web 不登记配方，整体仍 93/112。

### 联网媒体受控 CLI 与隔离中继（2026-09-19，T094 继续）

- 新增 `web-cli-proxy.ts`、`pi_web_relay.py` 和第一方 `pi-web-cli.py`。父进程按显式 Web 路线核验 HTTPS 目标、DNS/地址、代理及凭据；CLI 只见回环代理和短期 token。Linux 保留 `--unshare-all`；macOS 策略只声明选定回环端口及 Unix socket，其平台效果仍未验证。
- yt-dlp 信息提取与远程 FFmpeg 抽帧已从插件直接子进程迁至 ordinary 命令监督、唯一 manager 与真实终止证据；新增 yt_dlp_tool_ref/javascript_tool_ref。忽略环境配置/插件/远程组件，JavaScript 运行时显式绑定。CLI/第一方输入在启动前复核，原项目不挂载；撤权后关闭存量隧道，失败/截断/终止未知不发布成功结果。
- 中继限定私人 Unix socket、固定 loopback 端口、64 对连接和每方向 64 KiB 缓冲，支持背压、半关闭排空与空闲回收。代理在绑定前登记为 Web operation transport，失败时也保留清理责任；响应头后的二进制数据不丢失。
- 离线 Python 52 passed（Web CLI/中继/沙箱/本地媒体/Web 配置/普通命令），Node 10 passed（联网与本地媒体、代理），Web 全源码 TypeScript 通过。尚未执行本批完整 mock。
- Linux 独立第一方预检：网络隔离内回环检查通过；完整驱动/中继的 Unix 回显检查通过，报告 `/tmp/acw-preflight-s6_ryhkx/report.json`。初次完整驱动预检因测试脚本 `/tmp` 挂载顺序错误失败，报告 `/tmp/acw-preflight-2s1qoung/report.json`；修正预检后通过。均未启动第三方宿主、Git/yt-dlp/FFmpeg 或真实账号，没有外网通信，不能作为 T106/T111 通过证据。
- Git clone、完整 Web 设置/依赖闭包、缓存重启清理和最终验收继续未完成；Web 尚未登记配方，任务仍 93/112。其他三个平台继续未验证。
- GitHub clone 已接通显式 Git 工具、GitHub 路线、临时凭据及普通写授权/工作区租约；所有插件直接 Git/gh 子进程路径已移除。新目录由 supervisor 创建，只有指定产物目录可写。公共写租约只接受可核验 Git 工作树，测试初次使用非 Git 缓存根明确失败；改为工作树内的显式写根并在文档说明此约束，不放宽公共锁。
- clone 展示迁至 supervisor 的 GuardedFiles，不继续使用插件直接 fs 读取。支持结构/目录/README/文件展示，实际读权限和链接边界生效。初次联通测试发现 GuardedFiles 构造缺少只读 mutation 参数，修复后相关 Python 47 passed、Node 11 passed，Web 类型检查通过。克隆作为显式产物保留，会话切换只清除引用，避免删除用户修改。
- 原始媒体副本新增持久租约关联与到期/重启回收；CLI 私人输入新增本实例标记、过期和保护检查。媒体清理定向 24 passed；最新 CLI 重启回收用例随完整回归运行。
- 已启动完整 mock `/tmp/agentcfg-pi-mock-20260919-web-cli.json`，结果另记；后续只读盘点不改测试中的源码。Git/yt-dlp/FFmpeg 真实运行、全部设置/依赖闭包仍未完成，任务仍 93/112，Web 不登记配方。
- 完整联网 CLI 批次通过：1473 Python + 7 subtests，292 Node，结束 2026-09-18 16:35:44 UTC；相关源码在报告运行期间零修改。此后修订不继承该报告的源码身份。
- 后续补齐 PDF 默认内联/显式普通写产物、完整搜索/抓取/PDF/服务设置及 SearXNG 头秘密引用。修复撤权与退出 0 的竞争，发布前再次核验 generation；缓存写入需有效 Web 操作，内存按 runtime 隔离，session_start/tree 等待旧活动关闭。私人 cache 目录逐层校验，不自动 chmod 不安全的旧目录。
- 后续定向 Python 128 passed，Node 14 passed；包登记与依赖/目录/可选能力 Python 60 passed。Web 0.27.0-agentcfg.1 已声明到四配方，固定直接 npm/SDK 依赖并保留 NOTICE/全部来源和最新派生补丁。当前在独立 /tmp 副本解析真实锁，结果另记；T094 尚未勾选，任务仍 93/112。
- Web 临时真实锁解析成功：`/tmp/agentcfg-pi-lock-probe-tkoxlj65`，27 来源、四配方，identity `1a552314999dc20db25ef78ce01c6815a002ab9f0239180a63c95ce250c3bfcf`。该副本早于缓存 fchmod、Gemini 绑定、SearXNG/Kagi/Ollama 分派及 PDF 释放修订，不能当作最新源码/最终候选身份。
- 固定 HTML/PDF 库加入默认测试 tooling，独立 HOME/npm 配置/cache、--ignore-scripts 安装成功，日志 `/tmp/agentcfg-web-fixture-deps-dczccsl8`。实际插件注册→raw/readable fetch→private cache→shutdown 与合成 PDF 的真实 unpdf 解析通过，仍为假宿主/假 HTTP 的 mock。修复真实联通测试发现的缓存 fchmod 在 Node Permission Model 不可用问题，并用只校验模式替代。
- 修复服务归属遗漏：SearXNG 搜索与 Kagi/Ollama extract 现使用各自已声明的 API transport，保留用户页面目标检查。PDF 本地 parser 在结束/异常时 await loadingTask.destroy；初次误用 pdf.destroy 的失败已修正。相关定向 Node 22 passed 后新增实际解析/服务用例 5 passed；可选能力/OpenSpec/Cursor/升级/配置/doctor/source 定向 Python 65 passed；Web 全源码类型检查通过。
- 四配方独立安装/密封检查仍在运行，收据目录 `/tmp/agentcfg-web-install-evidence-vwd3x1lw`，当前 default/managed/codex 已成功，cursor 待结果。每个自建临时安装保存收据后移除，保留模型数据缓存并重新验证其摘要；没有宿主执行。
- 启动本批完整回归 `/tmp/agentcfg-pi-mock-20260919-web-complete.json`；来源补丁已更新为 6385 行。运行期间继续只读审核后续验证 runner；新结果另记，任务暂仍 93/112。

- 四配方临时 npm ci/资源投影/密封检查全部成功（default、managed、codex、cursor），收据保存在 `/tmp/agentcfg-web-install-evidence-vwd3x1lw`；全部 host_execution=not-run，临时安装按计划移除。依赖验证对应上述中间锁，不冒充当前源码或最终候选。
- 结合已通过的源包/配置/实际插件 mock 联通与服务监督测试，T094 标记代码/mock 完成。stdio 的明确边界是本地无外网命令；远端认证服务使用 HTTP/SSE 绑定，不能靠环境继承获得额外访问。
- 审核已有 OpenSpec 1.11.0 真实资料/显式初始化、Cursor/Bun 配置身份及独立账号目录、升级差异与历史契约/原生数据保留实现；对应定向 65 项包含相关用例并通过，T095、T096、T097 标记代码/mock 完成。原生Bun/Cursor/账号行为仍由后续原生与实网任务验证，未据此记 passed。
- 当前 97/112。T098 原生/实网 runner、冷构建原生联通、最终文档/矩阵/候选/锁及各平台与已选 live 验收继续未完成；第二批完整 mock 仍运行中。
- 最新完整回归通过：`/tmp/agentcfg-pi-mock-20260919-web-complete.json`，1475 Python + 7 subtests、300 Node，UTC 17:06:57–17:14:08；相关源码零改动。它覆盖 PDF/缓存/API 分派/完整配置与真实解析器 mock 联通。T094–T097 保持代码/mock 完成；进入 T098，任务仍 97/112。

### T098 原生执行器（2026-09-19，仍未完成）

- 新增运行包静态准入、本地确定性 Chat Completions/SSE 夹具、四配方私人实例及合成 Git 项目生成。只接受回环模型地址，禁止借真实账号环境；Cursor 仅保留插件与 Bun 元数据，模型调用仍使用合成 provider。静态/协议/夹具/沙箱/打包定向 30 passed，随后验证 CLI/结果门槛等 44 passed。
- 新增固定原生 SDK 场景入口、受 supervisor 管理的控制驱动和外层平台沙箱。原生入口要求真实会话、唯一 manager、工具读操作、工作流收据和物理结束事实，版本/空输出不能算通过。调度保留未实现场景为 not-run，不从 all 中删掉；live runner 仍未完成。结果门槛与 CLI 定向最终 24 passed，Node 断言 1 passed。
- 已接入 host-resources 和 Task Keeper 九类场景的代码路径，尚未运行真实 SDK；继续准备新的临时真实锁/运行包用于开发期 Linux 原生调试，不把它作为最终 T106 候选验收。
- 此阶段曾发现 Tree 首次写入 API 参数不匹配及 Cursor 夹具缺显式 provider/route，均在离线测试中修正。服务代理 launch 防御性读取 provider_ids，但配置仍要求显式 []；相关 Web 与验收基础回归 35 passed。
- T098–T112 保持未完成，97/112；其他三个平台仍未验证。
- 原生调度器已接入 CLI，加入明确 host-resources 场景；真实 SDK 场景代码要求实际工具读、唯一 manager、模型往返、工作流/检查/审查收据与关闭事实。外层复用 HostSupervisor 做超时撤销和输出捕获；未完成场景继续列出 not-run，不能让 all 缩小范围。结果错 nonce、空事实、版本-only、超时或终止未确认均失败，相关 Python 24 passed、Node 1 passed。
- 新原生调试快照真实锁完成：`/tmp/agentcfg-pi-lock-probe-sf7g2bl_`，identity `8a8d6918e06a613cc1e3ef6ec6f2ea06d0192f9be1f707f3eed75e9ec200e556`。六个核心原生验收源文件与工作区逐字一致。现在只安装 pi-managed 调试运行包，随后用隔离网络和合成本地模型运行真实 SDK；尚未产生原生通过证据。T098 仍未完成。
- 原生开发调试暴露外层重复 HostSupervisor 的问题：继承环境在过滤前触发 SpawnCommand 校验，且外层会把内层合法独立进程组误判为逃逸。已改为外层仅持有隔离沙箱 Popen 句柄、持续有界排空输出；超时通过本夹具的已认证 user 控制入口撤销内层执行，未知租约继续保留，正常结果还必须通过内层活动检查。监督者绑定 Unix socket 后恢复 cwd。
- Linux /proc 扫描遇到无关同 UID nondumpable 进程时，改用 stat 的亲子/进程组信息判定关联；属于本执行但身份不完整的成员仍记 unknown，禁止盲发信号。原生调度与 Linux/宿主/监督定向 37 passed；随后新增控制入口取消测试待复跑。
- 临时开发运行包位于 `/tmp/agentcfg-pi-native-debug-wk53tfiy/instance/runtimes/ca89aeffaa727247ee8b7672dfcfcdcade1e889f0427f25de5f39e7d2013cad8`。早期外层监督失败的 unknown 记录完整保留于 `/tmp/agentcfg-native-crvzkiqf/cases/`，没有清除保护或推断通过。
- 开发验收继续发现临时锁探测脚本只复制了 Pi 适配器，缺失 load_workspace 所需的公共 DSH 输入；已补全临时源码和探测脚本，未更改已密封运行包。当前调试使用工作区新版外层 runner 配旧版密封运行包，只用于定位问题，不是最终候选原生通过证据。T098 继续未完成，97/112。
- 原生外层 bwrap 增加 `--new-session`，避免新 PID 命名空间继承外部进程组时出现 pgid=0；第一方 Python 3.11 预检观察到 pid=2、ppid=1、pgid=1。首次预检使用 `/usr/bin/python3` 的外部分发符号链接失败，改用显式 3.11 后通过。
- 真实 SDK 已成功加载扩展、创建会话并完成两次合成模型请求，但普通 read 门禁拒绝，因此仍记录 failed。最初怀疑工具策略，检查别名后否定；控制通道诊断确认是夹具额外登记 `/usr` 为文件访问根，隔离 UID 映射下其所有权不可核验。已移除冗余系统读根，检查进程继续使用沙箱固有系统库挂载；未放宽生产文件权限。
- 同时移除尚未生成的结果文件作为 protected_roots 的输入；它们仍位于全部授权项目/工具根之外。诊断输出只保留异常类型及源码位置，不回显异常正文。后续定向回归分别 43、40、35 passed（各批对应当时修订）；没有新的全量 mock 或最终 native passed。
- 真实 host-resources 开发场景已跑通：`/tmp/agentcfg-native-crvzkiqf/cases/host-resources-runner-3e8f02f3/controller-result.json`，真实 SDK/扩展/唯一 manager（上限 2）、两次合成模型请求、实际 guarded read、源文件保持原样、宿主退出 0、执行全部终止。未使用真实账号。
- 该结果使用新版第一方开发控制器和旧版密封 SDK 运行包，以及开发提示批准引导，仅作为修复联通性的证据，不登记最终 T106/native 平台通过。生产验收入口已加入同等的显式合成 cwd 会话提示批准，硬策略/preflight 保持生效；相关 Node 权限/场景门槛 6 passed。
- 初次读门禁修正后仍被原生提示层要求交互批准；现在验收控制者明确设置合成项目会话提示，不通过关闭硬权限绕过。继续 Task Keeper inspect 原生调试；T098 未完成。
- Task Keeper inspect 已真实创建候选 Git 工作区并登记 reader worker；首次尝试在模型请求前失败，全部执行已回收。开发诊断定位生产代码 `HostSupervisor.resolve_command` 复用了 `name`：输入路径写入后又被环境清理循环覆盖成 SSH_TTY，最终 `--input` 指向错误文件。已改为独立 input_name，并在既有 worker 协议回归中核对 argv 路径及实际 JSON 内容。
- 首次新增断言漏导入 Path，出现 1 failed/11 passed；补齐导入后重跑结果另记。后续原生调试使用更新后的独立控制器，密封 SDK 包不变，仍不登记最终候选通过。
- worker 输入路径回归补齐后 12 passed；inspect/fix 夹具与协议回归 15 passed。原生 inspect 的 reader 已完成四次真实合成请求、完整文件/产物读取和结构化结果，收据 terminal_status=completed、termination_confirmed=true；整轮因原 180 秒场景等待不足仍记录 failed，不借单步骤通过改写结果。
- 夹具的工作流预算设为 900 秒，场景轮询最长 600 秒、外层控制最长 900 秒，超时继续撤销并记失败。下一轮已观察到 reader 和 native-build 通过，native-tests/独立审查继续执行中。
- 新增 permission-denials 代码：合成模型请求读取确实存在的夹具 local.toml；要求真实工具拒绝，并由第一方控制者核对没有 ordinary 文件准入记录。尚未实际运行该原生场景。
- 本批原生调度/夹具/合成服务/worker/宿主/Linux/CLI 离线回归 68 passed，Node 权限及原生门槛 6 passed。后续 pytest 原生夹具显式加 -B，避免 -I 忽略环境变量后在候选生成字节码；该小修订仍待原生复验。
- 新的真实 permission-denials 开发场景通过：`/tmp/agentcfg-native-crvzkiqf/cases/permission-denials-runner-4bb92bf8/controller-result.json`。模型尝试读取存在的夹具 local.toml，控制通道在 ordinary_prepare 返回 PERMISSION_DENIED，没有普通文件准入记录；两次合成请求、源文件保持、宿主退出 0、执行全部终止。仍是混合开发输入，不能登记最终冻结候选通过。
- 使用 -B 前的一轮 inspect：native-build passed，真实 pytest 输出 1 passed，但候选新增字节码导致 candidate_changed_during_check，整轮正确失败。现运行加 -B 的 inspect 与独立 fix 场景，验证完整检查和审查闭环。
- 加 -B 后的 inspect 在检查阶段暴露真实并发竞争：HostSupervisor.poll 调用 ExecutionStore.records 时可观察到同一 store 原子写入的 .agentcfg 暂存文件，误报“执行记录目录包含未知状态”并退出。现 records 使用同一 RLock 与发布串行；持久未知文件仍明确拒绝，不过滤暂存名前缀。
- 新增并发回归，验证读取等待正在发布的写入，同时静态未知文件继续报错。本轮失败目录 `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-inspect-runner-5e4e852b` 的 termination_confirmed=false，保留全部活动保护记录，不清理或宣称已终止。
- 发现监督热路径每次重复解析 schema 并执行元 schema 校验。现按 schema 正文缓存已编译 validator（最多 128 项），每次仍读取源正文，修改/删除立即失效；read_schema 返回独立副本，调用方不能改共享规则。定向 59 passed。相同小型测量：100 次 process-identity 0.845→0.036 秒，20 次 execution-lease 1.034→0.166 秒；仅为本机开发测量。
- 最新完整离线回归：`/tmp/agentcfg-pi-mock-20260919-native-foundation.json`，UTC 01:50:22–01:51:39，1522 Python + 7 subtests、301 Node 全部 passed；运行期间相关源码零修改。此证据覆盖原生执行器基础代码、租约竞争、schema 缓存与 worker 路径修复，不能替代 native/live。
- 真实 taskkeeper-budget 开发场景通过：`/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-budget-runner-f6fa4d58/controller-result.json`；只发出两次合成模型请求，后续请求被阻止，任务 BLOCKED，执行收据和物理结束已确认。继续完整 inspect/fix 的独立审查。任务仍 97/112。
- 更严格复核预算发现：本地 turn ceiling 的同步拒绝会被 SDK 包装成普通失败，旧回执只有 EXECUTION_FAILED/HTTP_200，缺少独立拒绝原因。已让 turn guard 排队持久化 request_denied，并由 finish 等待；worker 保留 BUDGET_EXHAUSTED。原生预算断言必须看到 BUDGET_DENIED 且实际请求不超过 2，不能仅凭 BLOCKED 通过。相关 Node 11 passed、Python 27 passed。此前 budget 的 passed 仅对应旧断言，不能用作加强后门槛的通过证据。
- 加速前的 fix 进入独立审查后超时，用户取消被接受但最终 termination_confirmed=false；`taskkeeper-fix-runner-0cc9381d` 的保护记录保留。加速前的 inspect 也未形成最终收据，退出 5，但全部执行结束。现在使用新的控制器和独立 worker v2 开发入口重跑预算、inspect、fix；已密封 SDK 运行包仍不改写。
- 最新完整 mock 的 1522 + 7 / 301 结果早于上述预算拒绝记录修订；不可把它称为后续预算修订后的完整回归。
- 加强后的真实预算开发场景通过：`/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-budget-runner-af32dee5/controller-result.json`，budget_denial_observed=true、两次请求、任务 BLOCKED、全部执行已结束。独立 worker v2 确认 BUDGET_EXHAUSTED 到 BUDGET_DENIED 的证据链，不再依赖笼统失败。仍为开发混合输入，最终候选需重建验证。
- 合成审查夹具原先漏读 Evidence 列表中的裸 artifact-ID，真实工作流以 REVIEW_EVIDENCE_NOT_READ 拒绝了结论。已同时识别显式 artifact:ID 和裸的冻结产物 ID，实际逐个调用 tk_read 后才提交结构化结论；没有放宽审查代码。Python 定向 28 passed；预算修订后的完整 Node 清单 303 passed。
- **完整 inspect 开发验收通过**：`taskkeeper-inspect-runner-62c17f2d`，12 个受监督执行、2 个 worker、10 次合成模型请求、3 条检查/审查记录、COMPLETED 和最终收据、源项目保持、所有执行结束。
- **完整 fix 开发验收通过**：`taskkeeper-fix-runner-32f5d428`，16 个受监督执行、2 个 worker、14 次合成请求；候选真实修改、构建/pytest/独立审查和最终收据通过，源项目保持，所有执行结束。
- quota 开发验收通过：`taskkeeper-quota-runner-6862b284`，合成 429 后进入 WAITING_QUOTA，显式 stop 后 CANCELLED 且全部终止。
- missing-result 加强后开发验收通过：`taskkeeper-missing-result-runner-5b8dcd09`，1 次请求，当前 worker 的 EVIDENCE_EMPTY 正文与 lease attempt 匹配，任务 BLOCKED，所有执行终止。新增第一方证据匹配和结果门槛回归 39 passed。
- 上述目录均位于 `/tmp/agentcfg-native-crvzkiqf/cases/`，仍为独立开发入口搭配旧密封 SDK，不能登记最终 T106 候选或真实账号通过。继续第二视角、暂停恢复、停止与定时场景；任务仍 97/112。
- 第二视角开发场景通过：`taskkeeper-second-view-runner-263f2147`，14 个执行、3 个 worker、18 次请求、4 条检查/审查记录，second_view_verified=true，最终 COMPLETED、源项目保持、全部终止。
- 停止首轮 `taskkeeper-stop-runner-98f81f5e` 在旧断言下通过。现进一步要求停止/暂停前 supervisor 已确认 worker 的真实进程身份和 running 状态，不只依赖 manager 状态；worker_executions 只统计有进程身份的工作。结果门槛回归 36 passed，正在加强后复跑 stop 与 schedule，pause-resume 旧轮仍在运行。
- 加强后的停止开发场景通过：`taskkeeper-stop-runner-f73bebec`，worker_started_before_control=true，真实 worker 已开始并发出一次合成请求，停止后全部回收。
- 一次性定时开发场景通过：`taskkeeper-schedule-runner-6d37e5fe`，准入时间不早于 not-before，完整检查/审查收据通过且全部终止。
- 暂停恢复仍在定位。新增不含正文/凭据的 scenario-progress.json 后发现验收器漏识别 Task Keeper 的结构化命令拒绝（{code,exit_code}），曾把 resume 拒绝当成 handler 成功。已准确识别，只对 JOB_STILL_STOPPING 短暂重试，其余拒绝立即失败；Node 定向 2 passed。三轮旧探测通过认证 user 控制入口停止，终止最终均已确认，失败证据保留。
- 暂停恢复新轮 `taskkeeper-pause-resume-runner-7266ba64` 已正确识别结构化 JOB_STILL_STOPPING，等待收尾后 resume 成功：任务从 PAUSED 到 RUNNING/user_resumed，controlEpoch 从 2 到 3，并启动 fresh attempt。继续等待完整检查和最终收据；还不能标为场景通过。
- 开始最新全量 mock `/tmp/agentcfg-pi-mock-20260919-native-controls.json`；本轮期间不修改相关源码。
- 暂停恢复开发场景最终通过：`taskkeeper-pause-resume-runner-7266ba64`，14 个受监督执行、3 个 worker、16 次合成请求；先确认真实 worker 启动，暂停后以 fresh attempt 恢复，保留同一任务/预算，构建/pytest/独立审查及最终收据通过，源项目保持，全部终止。
- 最新全量 mock `/tmp/agentcfg-pi-mock-20260919-native-controls.json` 通过：UTC 02:26:19–02:27:26，1532 Python + 7 subtests、304 Node；运行期间相关源码零修改。
- Task Keeper 这批开发场景已具备真实证据，包括正向工作流、独立审查、第二视角、预算、限流等待、暂停恢复、真实停止、定时与缺失最终结果拒绝；不据此将 T098/T106 勾选。父宿主丢失、恢复授权、model-delegate/Codex 原生替换、冷构建和 live runner 等仍有待完成。下一步继续剩余原生执行器。
- 父宿主丢失原生开发场景通过：`parent-loss-runner-1593c4a7`，只在实际 worker 已启动并发出合成请求后，用已核验 pidfd 中断本夹具父 Pi；观察到宿主退出 137、worker grant 撤销、子执行回收、源项目保持。场景控制器正常退出 0，全部执行终止。
- 新增 Linux/pi-managed 的 parent-loss 驱动及错误 nonce/身份/尚无请求的负向门槛；离线 33 项相关回归通过。其他配方/平台的该场景继续明确 not-run，没有借 Linux managed 的结果提升其他格子。
- Linux 停止恢复原生探测通过：`recovery-grants-runner-9938c3e2`。实际创建第一方目标进程，旧监督者活跃时拒绝恢复、错误计划拒绝、原监督者被确认失效后按匹配停止计划撤权并终止目标；sdk_session=false、provider.requests=0，没有冒称 SDK/模型调用。相关回归 62 passed。
- 冷重建不再只生成 machine 路径：已提取安装前配置阶段，为四配方生成合成模型/角色/受管检查，Python 检查绑定新 checkout 的 .venv，未借原仓库依赖。修复包装函数先访问空 runtime 导致的负向测试回归，最终相关 49 passed。
- 冷重建接入新目标自身 Python 的分层原生验证，逐场景核对 source/lock/runtime 身份、场景完整性和物理结束；安装成功不代替原生通过。源码复制的可执行位归一化后，两代私人源码副本身份一致。两目标 HOME/cache/TMPDIR 独立；安装命令进入只读系统/显式工具链和新目标的独立沙箱，下载阶段可联网，原生宿主仍使用内层回环隔离。
- 冷重建 CLI 分派与隔离/证据回归 71 passed；系统信任根不采用调用者 SSL_CERT_FILE/DIR 覆盖，相关 47 passed。
- 第一方冷安装沙箱预检通过：`/tmp/agentcfg-cold-preflight-omd6z_95/第二组 空格路径/report.json`。实际验证 Unicode/空格路径、外部合成哨兵不可见，以及 Node v24.14.0/npm 11.19.1/Git 2.43.5/uv 0.12.13 可执行。未安装包、未启动 Pi/Codex/账号，不能算完整 cold-rebuild 通过。
- 开始生成新的临时四配方锁，供 pi-default/model-delegate 开发期原生验收准备；不作为仓库最终锁或 T104 完成。T098/T099 及后续仍未完成。
- pi-default 开发运行包安装完成：`/tmp/agentcfg-pi-native-debug-awv64fjh/instance/runtimes/0bdc1a0531088996b8b8451f1efa650337a1881c4b56cb34b2b72aa4497c02f4`，对应临时锁 `6aec0f1453813212818eeb46b1e840f652b6ccb44b1971891c1a149366b92be9`；模型缓存仅重验固定摘要后用于普通安装，未把它作为冷重建。
- Native 委托夹具补齐 pi.model_roles 和显式 network_route；开始七模板时曾因独立开发控制器缺共享 schema 失败，已补齐开发源。首个真实委托进一步暴露 minimal PATH 下裸 node/bun 无法启动；监督者现在在初始化时绑定解释器绝对路径，委托启动不恢复继承 PATH。相关 Node/Bun/宿主/目录回归 34 passed。
- Linux 用户 CLI 验收使用新实例内的只读 SDK 挂载和正式 deployment.apply，现有目录/非只读槽拒绝接管，未知目录权限不被偷偷修补。生产状态和运行包核验完整执行；开发期 CLI/监督脚本使用独立当前代码，旧密封 SDK 保持原样。
- **delegate-batch 开发验收通过**：`/tmp/agentcfg-native-default-davgcm5t/cases/delegate-batch/controller-result.json`，实际用户批次 CLI、3 个不同核验结果、幂等重放、manager 峰值 2、模型服务实际并发峰值 2、6 次请求，源项目保持，全部执行结束。
- **delegate-control 开发验收通过**：`/tmp/agentcfg-native-default-_ye73jsc/cases/delegate-control/controller-result.json`，probe/start/status/poll/wait/result/resume/cancel 八操作，两个 verified-execution 结果、新 run 关联 continuation_of、真实请求后取消，全部结束。probe 本身继续只声明依赖，不当作执行证明。
- 七模板循环观察到 general/context 已实际送入子模型且底层收据 completed，但上层工具将完成竞态误判失败：先取物理快照，再刷新结果会用到过时的 active 证明；pending 到后续物理终止之间也可能发生切换。现结果后重取物理证明，并在首次观察到终止时只读刷新一次最终收据，不重新 submit/start。14 项 Node 相关回归通过。
- 新临时锁正在准备以将解释器绑定与收据竞态修复装入完整 pi-default 包；不覆盖旧 sealed 目录。开始全量 mock `/tmp/agentcfg-pi-mock-20260919-delegate-native-foundation.json`，期间不修改相关源码。
- 最新完整 mock 通过：`/tmp/agentcfg-pi-mock-20260919-delegate-native-foundation.json`，UTC 04:38:32–04:39:42，1575 Python + 7 subtests、307 Node；运行期间相关源码零修改。覆盖冷重建、恢复授权、委托 CLI/批次、解释器绝对路径及完成收据竞态修复。
- 包含本轮修复的新临时锁解析完成：`/tmp/agentcfg-pi-lock-probe-60srl6k_`，27 来源、四配方，identity `e3d0a45129ee3cb5291d2889a3cb67cbce843d8209ed075f569e62dd9f524a40`。正在另建 pi-default 运行包复验七模板；旧 SDK 不修改，仓库最终锁仍未发布。
- 修复后的 pi-default 包已构建：`/tmp/agentcfg-pi-native-debug-a6yma3sq/instance/runtimes/71a6dd5904c3252d2ceec3ef625c27995a55d3b2820604847936dfb7a9eb7c42`，对应临时锁 `e3d0a45129ee3cb5291d2889a3cb67cbce843d8209ed075f569e62dd9f524a40`。
- 已改用临时候选源码自带的正式 verify-pi.py 入口，不再注入开发控制器。该轮工作根 `/tmp/agentcfg-native-zaqicybk`；**delegate-presets 已通过**：七模板实际分别调用唯一工具、全文到达子模型、七个不同 verified-execution 结果、源项目保持、全部执行终止。CLI 控制与批次还在同一轮执行，整组总报告尚待结束。
- 临时复制工具改为保留仓库入口的执行权限；已修正本次临时源码 agentcfg 的执行位。未改 SDK 内容，也不把临时锁当成仓库最终锁。
- **同一临时候选的正式 model-delegate 原生整组验收通过**：`/tmp/agentcfg-pi-native-delegate-candidate-20260919.json`，UTC 04:47:23–04:52:22，delegate-presets / delegate-control / delegate-batch 均 passed。使用临时源码 `60srl6k_`、锁 `e3d0a45129ee3cb5291d2889a3cb67cbce843d8209ed075f569e62dd9f524a40`、密封运行包 `71a6dd5904c3252d2ceec3ef625c27995a55d3b2820604847936dfb7a9eb7c42`；无开发控制器注入。
- 七模板均真实送入子模型且形成独立执行收据；用户 CLI 八操作和 fresh run/continuation_of 验证完成；三项批次使用唯一 manager、实测并发峰值 2、幂等重放及结果核验通过。全部使用合成回环模型，未进行真实账号调用。
- 整体仍 97/112：T098 还有 Codex 原生/其他配方平台与 live 执行器等收尾，完整真实冷重建、仓库最终锁/候选、交付文档与矩阵和已选实网验收未完成；另外三目标平台按用户要求保留未验证。没有把临时通过记录提升为最终交付批准。

## 2026-09-19：补齐场景枚举、普通取消与迁移冲突

- 修复原生 `--case all` 漏掉迁移冲突和普通任务取消；冷重建目标也必须执行迁移冲突。某场景未确认终止时，后续场景逐项记录 `not-run / previous-scenario-termination-unverified`，停止执行但不从报告消失。
- 新增 `ordinary-cancel`：通过真实 Pi SDK 和现有 manager 启动普通 scout，会等合成服务确认收到模型请求后再取消，同时等待 SDK promise、流和 manager 完成收尾。开发原生通过：`/tmp/agentcfg-native-default-tiueapsi/cases/ordinary-cancel/controller-result.json`；1 次合成模型请求，宿主退出 0、进程终止确认、项目未变。该场景没有独立 worker，证据明确记录 worker_executions=0。
- 新增 `migration-runtime-conflicts`：真实新实例部署与 Pi 宿主运行、合成旧 HOME 盘点、未接管文件拒绝覆盖、运行期正式 CLI apply/sync/rollback 全部返回 4、结束后 apply 零变更、旧配置与合成账号不导入。开发原生通过：`/tmp/agentcfg-native-default-nun39cmu/cases/migration-runtime-conflicts/controller-result.json`；2 次合成模型请求，全部进程结束。SDK 创建空 auth 对象是新存储初始化，不能误判为旧账号导入；非空账号仍拒绝。
- 上述两次为当前第一方控制器搭配旧密封 SDK 的开发验收，不是最终候选证据，不改写旧运行包。首次迁移挂载失败和空 auth 误判失败的记录均保留，没有改成 passed。
- 冷重建的准备、安装核验和原生阶段异常分别落入该目标的失败记录，仍尝试第二个新目标，不输出异常正文或私人配置。
- 增加 `validation-run` 闭合 schema 与执行报告检查：拒绝空成功、场景缺失、身份错配、重复 runner、时间倒置、汇总状态不一致或缺失物理终止证明。执行报告仍不能自动充当固定 scope 的发布证据。
- 本批定向 Python 回归 111 项通过（107 项调度/报告/冷重建 + 4 项迁移），Node 原生驱动回归 4 项通过。完整默认回归通过：`/tmp/agentcfg-pi-mock-20260919-validation-completeness.json`，UTC 12:44:19–12:45:31，1612 Python + 7 subtests、308 Node；回归期间未修改相关源码。
- 继续补齐普通配方父宿主丢失：通过唯一 manager 的 Pi 委托入口启动真实子进程，模型请求到达后只用已核验的父宿主 pidfd 发信号，随后观察子执行撤权与回收。`/tmp/agentcfg-native-default-q4ynupa8/cases/parent-loss/controller-result.json` 开发原生通过：2 个执行租约、1 次合成请求，父宿主退出 137、子执行 reclaimed、全部进程结束、源项目不变。子执行类型明确为 external，worker_executions=0，不混同 Task Keeper worker。
- 上述父宿主补充发生在全量回归之后；补充定向 Python 88 项、Node 原生驱动 4 项通过。没有把较早全量报告改写成包含后续源码的证据。
- T098/T099 仍不勾选：Codex 原生及 live 执行器、macOS 特定验收接线、真正两路径完整冷重建尚未关闭；最终候选、仓库锁和全量原生/账号验收也未完成。三个缺机器平台继续保留未验证。

## 2026-09-19：Codex 官方 CLI 原生链路

- 增加显式 `model_delegate.codex.api_base_url`，地址只进非秘密配置和冻结执行策略；默认仍为官方地址。自定义地址要求 API key，父监督者和 worker 两次拒绝个人 OAuth／未知身份；不继承 `OPENAI_BASE_URL`。无用户名、密码、查询串和片段的 HTTPS 可选；HTTP 只允许数字回环地址。
- 新增合成 Responses 服务和 `codex-native-readonly` / `codex-native-write` 驱动，经正式用户 model-delegate CLI 启动密封的官方 Codex。读取、尝试写入、独立 worktree、核验收据、源项目保持和物理终止均为通过前提。
- 第一份一致候选：锁 `cda8ed6b13eb69f42ffdf9d8813d070c9a86b9d7f05e13f24d3ae00d56c3f378`，运行包 `0f7c37d456c36ad8155f41ee378477933176c34a1ca93f90178e40b2483ab083`。正式报告 `/tmp/agentcfg-pi-native-codex-20260919.json` 为 **failed**：只读场景失败且终止无法确认，后续写入场景保留 not-run，没有跳过后宣称通过。
- 实际发现两处生产适配问题：官方 CLI 的原生命令创建独立进程组，原监督器会把已登记后代也置为 escaped；原生工具的环境清空后没有 PATH，Codex 无法找到系统 bwrap，工具返回退出码 101。
- 修正：仅 Linux Codex 在启动闸门前选择独立子组记录 v2，按存活父身份登记同 UID 后代和独立组长，逐成员核验并用 pidfd 停止；PGID/启动时间/namespace 后续改变或未知成员混入仍 unknown。普通执行、macOS、旧记录不扩权，不清除旧 escaped。原生工具明确设置固定 `/usr/bin:/bin`，其余环境继续不继承。
- 完整默认回归：`/tmp/agentcfg-pi-mock-20260919-codex-endpoint.json`（1639 Python + 7 subtests、308 Node）；监督修正后 `/tmp/agentcfg-pi-mock-20260919-codex-supervision.json`（1657 Python + 7 subtests、308 Node，UTC 15:47:32–15:48:48）。两次均为离线回归，不是原生通过。
- 临时分区空间不足时，纯模型缓存逐文件 SHA-256 核对后迁到忽略目录 `cache/pi-validation/model-data`，旧缓存空间回收，原活动记录和失败运行包保留。`/data` 上层目录不符合私人实例安全条件，没有放宽检查；修正版构建在独立 bwrap 视图中将大分区验证卷映射到安全临时路径。
- 修正版锁 `97b272328494bd2520ae4385b8b45bc6b3297ea575983fbbc2094265736f5f1d` 已生成，正在安装临时 Codex 候选；原生复验尚待完成。仓库最终锁和 release 批准仍未生成。

### 同轮后续结果（本地日期已到 2026-09-20）

- 固定 PATH 不是全部原因：实际系统 bwrap 0.4.0 缺少官方 CLI 必需的 `--perms`；独立 Codex tar 只包含主程序。已核对官方 release 和源码，补齐两种 Linux bwrap 以及四平台 code-mode-host/响应代理的固定资产、SHA-256 与许可证；共 37 来源。归档验证不冒充其他平台原生通过。
- 官方 JSONL 可在 turn.started 前发送非致命 completed error item，也可在 error 后以 turn.failed 收尾。解析器现在保留真实失败语义，不因这两种合法序列主动二次取消；不采纳提示正文为完成证明。
- 私有路径投影修正：Linux 的 root-deny 已覆盖未授权临时路径，去掉遮住授权挂载的冗余 /tmp 遮罩。实例内密封代码只读、本次空白 scratch 可写，其他私有同级目录继续默认拒绝；私有目录落入项目或系统可读根时继续显式屏蔽，无法分离的过宽项目布局拒绝。明确用户 deny/readonly 不放宽。
- 开发原生通过：`codex-debug-356dtjh2`（readonly）、`codex-debug-4xd_tdjp`（write），位于 `cache/pi-validation/runtime-volume/`。各 4 次假 Responses 请求，配置及账号文件读取被拒，只读写入 EROFS，显式 worktree 写入退出 0，源文件保持，收据与回收确认。
- **一致候选正式原生通过**：`docs/acceptance/pi-codex-native-candidate-20260920.json`，UTC 16:57:07–16:59:49；readonly/write 均 passed。锁 `49fe54e1a01e7ad568cd4f2ad7b37b2160efac8fd13f24b19ba2928446272c16`，运行包 `e476fd70eb3d8183885396908b4f70d1a93deaaa2d26e75198e77df6476739c1`。源码和运行包存于验证卷 `source-sqfoxexe` / `runtime-sj7bk40k`，正式执行时映射到 `/tmp/agentcfg-pi-volume-o7nluwv_`；无开发注入，无真实账号。
- 最新全量离线：`/tmp/agentcfg-pi-mock-20260920-codex-native-policy.json`，1666 Python + 7 subtests、308 Node，全通过（UTC 16:51:16–16:52:31），运行期间相关源码不变。
- README 中的“Pi 尚未适配”已改为准确的开发状态和指南入口；仍不宣称最终交付。T098 尚有 Codex 控制操作／live 和平台专用执行器，最终仓库锁、完整冷重建及账号验收仍待完成，任务清单仍 97/112。

## 2026-09-20：实网执行器、可选服务与代理验证

- 实网调度已接入 Codex/Cursor/代理的实际 model-delegate CLI，以及 MCP/web/终端的密封 SDK 入口。准入要求固定 scope、同平台同运行身份的完整 native 报告、当前已 apply 的部署、项目范围和无活动冲突；真实账号尚未执行，用户所选六类可选能力仍全保留。
- Codex 控制链开发原生通过：验证卷 `codex-debug-5jd9sixy`，probe/start/status/poll/wait/result/resume/cancel，3 租约、6 次假 Responses 请求、2 个核验结果，恢复创建新执行，取消后全回收。原先两场景正式候选报告不冒充新增第三控制场景的证明。
- 新增 `--prepare-live-project`：只创建新合成 Git 项目、不调用模型。Task Keeper 实网入口执行 inspect 和 fix，核对当前检查、审查、第二视角，恢复源夹具并确认终止；模型角色与 direct/proxy 选择必须匹配前置原生证据。错误/中断保留失败记录，不输出第三方正文或凭据。已补入 quickstart。
- 可选 SDK 验收只收窄已允许的扩展集合。修复实例扩展无法解析运行包模块的问题：四个明确 helper 通过受管的实例桥接调用当前运行包；未知 helper 拒绝。终端状态上报改为每运行身份共用串行队列，启动事件与验收调用不会并发争抢通道。
- 开发原生 MCP、SearXNG web、终端均通过；早期 Brave 回环 HTTP 拒绝符合协议，改用支持自托管的 SearXNG，未放宽 Brave HTTPS 规则。一次失败终端启动通过认证控制端点回收，失败记录保留。
- **同源码／同锁候选三项服务正式原生通过**：`docs/acceptance/pi-services-native-candidate-20260920.json`，UTC 20:08:54–20:10:33。锁 `f815508da8e97b61a56d84a224bb8fc20c74193e8fb957f618795b1c8730139f`，pi-default runtime `3d8b9756d111bfad591a7c41d784a16edd0c9799a88de4aa9b69608db44a0027`，验证卷 `source-la2ix7pj` / `runtime-i10msl8x`。MCP 实际重连及元数据刷新、web 实际假搜索、终端三次确认；全回收、源不变。无开发代码注入、无真实账号，仍不是最终仓库候选。
- 认证代理开发原生通过：验证卷 `tmp/agentcfg-native-default-uauzort5/cases/delegate-proxy-control`。8 个实际 CLI 操作、3 租约、2 个核验结果、4 次请求均经认证代理；模型地址为不可直接解析的 `.invalid`，代理缺失不可能直连通过。该场景已加入普通配方原生调度与冷构建，Task Keeper 另增代理修复和第二视角场景。
- 全量离线回归 `.../pi-mock-20260920-live-managed-services.json` 的 Python 1728 + 7 subtests 通过，但 Node 24.14 权限模型禁止真实 fsync/symlink，报告保留 failed。Linux 测试入口改用 bwrap 的只读仓库、唯一可写临时目录、隔离网络，同时保留假进程/网络 guard，不跳过测试。复验 `/tmp/agentcfg-pi-mock-20260920-live-services-os-isolation.json`：**1728 Python + 7 subtests、319 Node 全通过**，UTC 20:08:44–20:10:06；此后源码构建入口与中断补充另有定向测试，不能借用本报告当其全量证明。
- macOS helper 现在在 sync 阶段显式按目标架构编译并核验 Mach-O；新增 Intel ReadSeek 源码构建路径，固定根提交、三个子模块、上游 PDFium 全部 Git/工具归档锁、Zig 0.16.0 和关键脚本摘要，独立缓存构建，保留静态依赖许可证及构建收据。24 项相关替身测试通过。两者都没有 macOS 实机原生通过证据，三个缺硬件平台继续未验证。
- 待关闭：上述最新源码的最终锁、完整原生/cold-rebuild、真实账号/服务；macOS 特有场景及 ReadSeek 工具级原生覆盖仍需核对。任务清单不因开发或替身通过提前勾选。

- 同一候选委托四组正式原生通过：`docs/acceptance/pi-delegate-native-candidate-20260920.json`，包含七模板、8 控制操作、批量并发和认证代理。旧 codex-delegate 未进入运行包；本报告仍只对应上述候选身份。
- 四配方真实锁和 vendor 已写入 `locks/pi/`（37 来源，约 22 MiB）；解析脚本逐文件验证 `locks/dsh` 完全不变。随后发现新增 Task Keeper 代理场景的 SDK 白名单漏项，已补测试并修正，锁随之刷新。最终候选身份尚未冻结，不能据此批准迁移或覆盖较早报告。
- 原生外层执行器现对 Ctrl-C 走认证取消、回收和失败落盘，后续场景保留未运行，不继续派发；中断与超时分开记录。相关 Python 110 项、Node 14 项定向回归通过。
- Intel 源码构建所需 Zig/make/Python/patch 和显式 Xcode developer 根已纳入 macOS 冷重建沙箱；固定 Zig 子模块没有额外远程依赖。冷重建与源码构建定向回归 28 项通过，仍不声明 macOS 实机通过。
- 仓库锁下全量回归 `/tmp/agentcfg-pi-mock-20260920-repository-lock.json`：1742 Python + 7 subtests、320 Node 全通过。对应锁 `e15ea3e790e2e139790417c1e4964c383232313357e5d0e9e3bd97f79da64c94`；后续 Python 冷重建修正需使用更新身份。
- 首次真正双路径冷重建保存 `cache/pi-validation/runtime-volume/cold-default-e15-report.json`：两目标各自在独立 HOME 完成 `uv sync --locked`，随后 `sync` 均因 `/usr/bin/env python3` 无法穿过未挂载的 `/etc/alternatives` 返回 127，native 保留 not-run。未复用参考 runtime 或模型缓存。冷沙箱现在在自己的 tool-bin 明确绑定基础 Python，定向17项回归通过，保留旧失败目录，准备新目标复验。

### 实现任务与验收任务分别核对

- T099 已完成的是冷重建执行器：真实锁、两个新 HOME/源码路径、隔离旧缓存、逐目标安装/原生结果和失败继续记录。两次实际运行暴露并记录失败，并未满足 T106 的双路径通过要求；T106 保持未完成。完成 T099 不代表冷重建已通过。
- T100 的新机、模型/账号、检查绑定、替换、可选能力、恢复和四类维护文档已交付，并更新到真实仓库锁及当前未验证状态。
- T101 的缺依赖/凭据、冲突、升级失效、capture、维护与 scope/发布负向回归已经通过完整默认测试，用户选择保存在 revision 2 scope。
- T102 的初始支持矩阵及独立发布检查报告已生成。`/tmp/agentcfg-pi-release-decision-20260920.json` 明确 `release_approved=false`、364 项 not-run、0 项 not-selected；开发候选报告不会自动填入最终 scope。
- 因此上述四项按其“实现/报告”验收条件勾选，清单现为 **101/112**。T098 的平台专用执行器与完整接线核对仍待关闭，T103–T112 中除 T102 外的最终冻结/安装/原生/账号/交付任务不提前勾选。

- 最新完整隔离回归 `/tmp/agentcfg-pi-mock-20260920-cold-python-binding.json`：1742 Python + 7 subtests、320 Node 全通过，UTC 20:35:53–20:37:11，对应锁 `450444cc11f42b6e0f7e054e47c3702a472de70f7c39f8d4c946b7ce22bf108f`。其后安装网络修正单独验证，不借用该报告当作新源码的全量证明。
- `cold-default-python-binding-report.json` 的两目标均已进入 sync，但视觉资产下载返回5，原生未执行。对照宿主/同隔离边界诊断发现：HuggingFace 在当前网络需要标准安装代理；传入下载代理后 OpenSSL 缺少系统 CA 的符号链接入口（只挂了终点）。现在仅安装阶段保留无 URL 内凭据的标准代理，native/模型环境剔除；系统信任文件同时绑定编译时入口和真实终点，不接受环境指定私有 CA、不禁用 TLS。相同隔离环境对两个公开视觉资产均返回 HTTP 200 并读到首字节；这只证明可达性，不冒充完整下载校验或冷重建通过。
- 较早 `managed-lifecycle-v5-report.json` 保留 failed：9类直连场景全部通过；新增代理2场景因当时 SDK 白名单漏项失败，终止均确认。修正版仓库锁的完整11场景复验正在运行，不覆盖旧结果。
- 安装网络修正版锁：`7c9ae661d67dd9bfc65f7db2affca9aa601c9925e76d7294ec9f51eacb5f8b44`。`/tmp/agentcfg-pi-mock-20260920-install-network-binding.json` 全量 **1744 Python + 7 subtests、320 Node** 通过；记录见 `docs/acceptance/pi-default-tests.md`。
- 第三轮真正冷重建 `cold-default-network-binding` 的 first 目标已从独立 HOME 完成 Python 依赖、完整 sync 和 apply，运行包 `854d45af1fbf7296e3cfa122b180ac1a40d5a63820a16a574f9658470665b022`，目前继续原生场景。安装成功尚不勾选 T106 或冷重建通过。
- Task Keeper 代理验收修正后，开发原生两场景通过：`tmp/agentcfg-native-managed-proxy-oovhoo4v` 修复（14次认证代理请求、16租约、2 worker、3检查）；`tmp/agentcfg-native-managed-proxy-k23l_6l0` 第二视角（18次认证代理请求、14租约、3 worker、4检查）。均源不变、收据核验、全回收。修正只允许保留 `.invalid` 模型目标、固定回环代理端口与假凭据；仍拒绝真实外部账号输入。
- 四配方第一个真正冷目标都完成 sync/apply。pi-default 第一个目标全部6组原生通过；其他配方继续暴露并保留实际失败，不以安装成功计作原生通过。
- Cursor/Bun 1.4 将分离的 `--config PATH` 误作脚本参数，之前宿主未执行 SDK。普通启动与委托都改用 `--config=PATH` / `--tsconfig-override=PATH`；52项 Python 定向回归通过。`tmp/agentcfg-native-cursor-g4y04eyt` 开发原生通过真实 SDK、2次假模型请求及受控读取，全回收；Bun 自身 tsconfig directory-mismatch 诊断仍出现在 stderr，没有通过移除配置限制隐藏它。
- Codex 配方的 Pi backend 批次曾在部分结果可读、其他执行仍活动时被验收器当作最终 partial 并退出，原报告保留失败。验收现在等待 manager 排空；`tmp/agentcfg-native-batch-1k73oyc9` 开发驱动复验3结果、并发峰值2、6假请求、全回收通过。另在生产 external executor 中把完成结果刷新移到物理证明采样之前，避免用刷新前的状态核验收据；新增定向回归通过。该开发驱动使用的旧密封扩展没有加载新 external executor，生产修正须由后续一致候选复验。
- 发现长验证期间工作仓库继续修改会使第二个冷目标复制不同源码，原7c批次的第二目标因锁不匹配保留失败。冷重建现在先复制并核验唯一 candidate-source，两个新目标都从这份源码输入重建；它不包含现有运行包、node_modules 或下载缓存。新增回归在第一个目标执行时修改原工作仓库，确认第二目标仍使用同一源摘要。旧失败目录不改写。

- 7c 冷目标中的官方 Codex 只读出现 v2 进程组 escaped，控制超时且终止未确认；后续写入/控制按 not-run 保留。未清除该记录，单次开发重试通过也没有重写它。
- Linux Codex 现改为整次执行的 PID 命名空间。新第一方门控入口作为 PID 1，监督者先核验固定 bwrap 的 init/包装出生身份和 NSpid，再持久登记 v3 并放行。内核范围覆盖原生工具独立进程组与重新托管后代，不再依赖每个短命孙进程都被轮询捕获；v1/v2 unknown 保持原语义。
- 第一方内核 smoke `/tmp/agentcfg-namespace-smoke-xzxcat_5` 通过：孙进程 fork 后脱离原组、父进程退出，停止 PID 1 后两个命名空间进程的 pidfd 均确认退出。没有执行模型、Pi 或 Codex。
- 开发原生新范围已通过只读 `codex-debug-9xw7u46m` 与写入 `codex-debug-7i3h8go_`：各4次假 Responses 请求，隐私拒绝、只读写拒绝/独立 worktree 写入、核验结果和全部回收。初始失败是内部 PGID 在组长位于父命名空间时显示0；握手改为比较不可变出生身份，未修改公共进程身份 schema。新范围的僵尸判定与严格握手有独立回归。
- 新 PID 范围的 Codex 控制开发原生 `codex-debug-i3d5erqy` 通过：3个真实执行、6次合成请求，8项CLI控制操作、fresh resume、请求到达后取消、2份核验结果、全部进程回收。所有新命名空间记录均独立于旧 escaped 记录。
- Linux Codex 验收现在还显式检查 v3 命名空间的已终止证明，缺少证明不能凭旧式组记录获得通过。默认回归首次因测试安装夹具漏复制新增门控脚本而有8项安装测试失败；夹具已补齐，32项安装/管线回归通过，失败报告保留。

- 新完整候选锁 `9c4036fff6d92b414b5f242e8dda7428497c787a690ed151b1bafec3faa0ee20`（37来源、四配方、DSH锁不变）。全量 `/tmp/agentcfg-pi-mock-20260920-codex-namespace-complete.json`：**1762 Python + 7 subtests、322 Node** 全通过，UTC 22:31:29–22:33:14。
- 四配方新一轮双路径冷重建使用该锁；每个任务已冻结唯一 candidate-source，再创建两个独立 HOME/源码/缓存。旧运行包与模型下载缓存仍不挂入安装命名空间。
- speckit-analyze 复核：46 FR、12 SC（经 V01–V24）全部有任务，无未映射任务/宪章冲突。发现并按既有自动修复授权修正4项文档问题：计划时状态与当前状态混淆、要求矩阵的过期“全部未执行”、T098/T099实际模块路径、T099接口依赖与平台验收依赖混淆。复核0项遗留；未因此勾选原生/账号任务，未更改宪章批准日期。

### 本轮候选输入冻结

- 来源审核：31个资源目标内容摘要全部匹配，37个旧调用方都有存在的目标路径，声明的旧执行依赖为0；完整默认回归同时覆盖来源闭包和退休入口拒绝。
- `docs/acceptance/pi-candidate-9c4036ff.json` 冻结本轮软件输入、实际锁/配方摘要、四个已安装 Linux 运行身份及固定 scope 摘要。四份宿主报告的源摘要相同。未构建平台和真实机器/账号身份没有填占位值；该文件不等于 AcceptanceScope 全部身份已冻结，也不批准发布。
- T103（本轮来源审核/候选输入冻结）、T104（四配方真实锁/vendor、DSH不变）、T105（完整默认回归）按已取得的具体证据勾选，当前 **104/112**。
- 仍未完成的是 T098 的平台专用验收接线核对、T106–T109 的平台/冷重建验收、T110–T111 的真实账号/服务和 T112 的完整交付批准。其他平台按用户决定保持未验证。后续源码改变时必须重新冻结受影响候选，不继承当前通过身份。

- 9c 冷重建的 Task Keeper inspect 已产生当前检查/审查通过收据并正常退出0，但 host 租约未能回收。定位到新 namespace_record 探测对所有进程记录先施加64KiB限制；该旧式 host 记录实际65618字节、380个历史成员，escaped=false，因此被错误归类为无法核验。已把大小限制仅用于v3命名空间记录，旧v1/v2继续按原读取契约处理，并新增500成员兼容回归；未清空记录或绕过 unknown。
- 此修正改变源身份，9c候选及其已有报告保持原样。T103/T104/T105重新打开，待新候选、锁和完整回归再次一致后关闭；当前任务101/112。这是修订候选，不回写9c为通过。

- 对照能力矩阵继续核对发现普通核心的 Todo/循环保护/状态栏未默认选入。已为三个 ordinary 配方补齐选择，并更新服务示例以保留普通核心；135项配置/兼容回归通过。
- 初始基线开发探测进一步发现 Todo 只有 catalog 声明、没有依赖源，SDK筛选还会静默忽略缺失的已选插件，因此先前两次“宿主通过”不计 Todo 通过。已加入完整 rpiv-todo 2.9.0 派生来源（UI、状态/replay、九语言、MIT许可与原归档摘要），来源总数38；Todo配置与语言只从实例manifest读取，取消legacy/global配置与自动i18n SDK发现，保留空指导语义。
- 资源选择现在拒绝缺失的已选插件；新增catalog→依赖→资源全覆盖断言和默认core选择断言。原生host-resources还要求Todo实际工具存在并完成create/update/delete。新基线需重新形成一致锁与原生验证，既有core-only结果不能替代此项。

- cc71 的 Task Keeper 多数场景通过，pause-resume在暂停后的30秒收尾等待中超时。核对业务代码：pause只暂停后续步骤，stop才中止当前执行；原生驱动误用了硬停止窗口。现将软暂停的有界收尾等待设为180秒，stop仍为30秒；不改任务权限、预算或实际pause语义。旧超时报告保留。
- 完整 Todo 适配全量回归：`/tmp/agentcfg-pi-mock-20260920-todo-complete.json`，1771 Python + 7 subtests、325 Node 全通过（不包含之后的冷控制器隔离修正）。
- 同源码/同锁的38来源候选 Todo 在 Node 与 Bun 分别正式原生通过，实际工具列表包含todo，create/update/delete三次操作核验通过，并完成合成模型往返、受控读取与进程回收。报告为 `docs/acceptance/pi-todo-native-node-20260920.json`、`pi-todo-native-bun-20260920.json`；锁323a6f64，与仓库最终候选分别记录。
- cc71 中 Cursor 两目标全部通过；default/Codex第二目标的源码摘要与第一目标一致但准备失败。进一步定位到控制代码的schema根仍指向调用者工作树，恰遇Todo schema调整，单独冻结源码字节不足。生产冷重建现在由冻结快照重新导入控制代码/schema，所有目标读取同版本规则；注入替身的默认测试路径保持隔离。20项冷重建回归通过，并补充子控制器返回身份/两目标/摘要/汇总校验。

- 当前完整候选锁 `c050a526060af559921796181c0cb77f5e32abbae1a6c4bef29be012ddbb7578`，38来源，包含完整Todo及普通默认核心、软暂停有界收尾和冻结代码/schema控制器。DSH锁逐文件未变。
- 最新全量默认回归 `/tmp/agentcfg-pi-mock-20260920-frozen-driver.json`：1772 Python + 7 subtests、325 Node 全通过；此后未修改运行源码。
- 四配方 c050 的第一目标均完成从新HOME下载/安装与apply，正在各自的冻结源码与新Python环境内原生验收。两个目标的控制代码和schema不再受工作树文档/实现编辑影响。
- 最终 c050 候选的 Cursor/Bun 双路径冷重建全部通过，报告 `docs/acceptance/pi-cursor-linux-cold-20260920.json`：两个新HOME/仓库目录各自完整安装、部署及5组原生场景通过，源摘要一致，未复用原运行包或下载缓存。此为Bun软件/合成服务通过，真实Cursor账号仍待配置和live验收。
- c050 的 Codex 配方两个新目标完整通过（含官方CLI readonly/write/control与内核终止证明），报告 `docs/acceptance/pi-codex-linux-cold-20260920.json`；Cursor同候选双目标亦已通过。
- default第二目标恢复停止出现退出瞬间/proc namespace链接消失造成的短暂unknown，旧停止实现立即返回冲突。现在只在原有等待期限内继续观察，不向未知身份补发信号；持续unknown仍保留保护。新增短暂/持续两种负向回归，47项定向通过；第一方原生恢复复验 `tmp/agentcfg-native-default-pbpy59mm/cases/recovery-grants` 通过（错误计划拒绝、仅停止授权、目标终止），没有模型请求。旧失败保持原样；源身份已变，需更新最终锁与验证。

- 当前锁 fdfdc71436abeedc27a8fdab707052b4f384d1536a925648629e02783fdbb976，38来源、四配方。完整回归 `pi-mock-20260920-recovery-observation.json`：1774 Python + 7 subtests、325 Node 全通过。
- 新候选四配方第一目标均已从全新环境完成sync/apply，正在重新原生验收；控制器、schema与源码保持同一冻结快照。
- 用户明确答复实网所需 Pi `--local` 配置和测试项目尚未准备。T110/T111 保持已选待验收，不调用真实账号，不改记not-selected；继续完成不依赖该配置的代码、默认测试和Linux合成服务/冷重建验证。

- fdfdc714 候选重新完成来源与锁核对：31资源目标摘要、37调用方目标、38依赖来源、四配方当前锁一致；四份当前 host-resources 的源摘要一致。`docs/acceptance/pi-candidate-fdfdc714.json` 已保存软件输入身份，完整mock报告及原始输出也从临时目录保存到 `docs/acceptance/`。T103/T104/T105重新勾选，104/112；这不替代仍在执行的两目标完整原生/冷重建或尚未准备的live验收。

- fdfdc714 的 Cursor/Bun 四配方中的第一份双路径冷重建正式完成：两个新HOME/checkout均安装、部署及全部5组原生通过，源摘要 `1fce14cfb3935d91045c0f88d488a3b7ea76c58b1029b6c5ec9309aaed15f457` 一致。汇总和逐目标明细保存在 `docs/acceptance/pi-cold-fdfdc714/pi-cursor/`；其他配方仍运行，不先关闭T106。

- fdfdc714 的 managed 第一目标11项生命周期全部通过，但随后 parent-loss 的宿主进程组记录进入 escaped=true；子任务已经回收，宿主保护不能清除。该失败记录保留。Linux Pi宿主现也进入独立PID命名空间，新增SO_PEERCRED核验的一次性门控，保留原始stdin；不修改既有v1/v2未知记录。第一方内核smoke `/tmp/agentcfg-host-namespace-smoke-u1e5zjkf` 已证明stdin保留、双重fork/setsid后代随PID 1终止，尚需完整原生复验。源身份变化，T103/T104/T105重新打开，101/112。

- 宿主命名空间开发复验 `agentcfg-host-namespace-dev-3jwu40gq/cases/parent-loss` 通过：宿主137退出、一次合成模型请求、worker撤权与全部三租约回收。旧managed包缺少bwrap，首次开发启动失败保留；四配方现声明同一固定bwrap资产，已安装它不代表注册Codex委托。67项定向回归通过；新锁 `484f07e9f16e070296b88ba24dcf7a5900f9d098ed1d5f43340c4f31b281dd26`，DSH不变；完整mock 1782 Python + 7 subtests、325 Node通过，原报告及输出已保存仓库。新锁四配方双路径冷重建已启动。

- 484f07e9四配方正式host-resources全部通过，源摘要相同；重新核对31资源、37调用方、38来源及四份运行包身份，保存 `docs/acceptance/pi-candidate-484f07e9.json`。T103/T104/T105再次依一致锁和完整默认回归关闭，104/112。其余原生与两目标冷重建继续，未提前勾T106。只读挂载哨兵及门控EOF第一方测试均通过，证据为 `pi-host-kernel-smoke-484f07e9.json`。

- 484f07e9四profile第一目标原生全部通过，包括修复后的managed parent-loss；Cursor两目标完整通过。Codex第二目标sync数据资产大小/摘要校验失败；managed第二目标uv下载coverage时TLS handshake EOF，3次重试后失败，均未原生执行。锁固定后的补充mock及Codex冷重建重跑申请各经历两次自动审核超时，命令未启动；默认沙箱Python重跑因根目录/tmp属主65534与有效UID1002不匹配出现847 passed/892 failed/43 errors，不能用于通过证明，未放宽保护。详见 `docs/acceptance/pi-validation-blockers-484f07e9.md`。默认profile第二目标继续运行。

- 484f07e9本批次全部结束：default/Cursor双目标完整通过；Codex/managed第一目标完整通过、第二目标分别因资产校验/TLS下载失败。58个已通过目标的宿主v3记录均terminated且lease reclaimed，索引中所有报告及输出SHA核对通过。`docs/acceptance/pi-linux-x86_64.json`保持failed，T106未勾，当前104/112。新mock及两配方冷重建的固定锁重试入口已准备；mock与Codex申请均因自动审核连续超时未启动，已向用户说明并请求执行确认。没有修改目录保护、旧未知记录或scope选择。

### 2026-09-21：转交本机Pi继续

用户要求将剩余工作整理为文档和prompt，交给本机Pi完成。本轮仅编写交接材料，不再启动依赖安装、mock/native/live或锁解析。交接见 [操作文档](../../docs/handoffs/pi-migration-2026-09-21.md) 与 [接手prompt](../../docs/handoffs/pi-migration-prompt.md)。

核对确认任务仍为104/112、锁仍为484f07e9；冷重建索引79个证据文件摘要匹配。旧/tmp重跑脚本、固定工具链目录及沙箱挂载别名已不存在，交接提供了直接使用仓库生产入口的方法，并要求重新核验工具链。文档20个链接、5段shell与2段嵌入Python均完成存在性/语法检查；未执行其中的验证命令。原Codex自动审核超时不作为本机Pi重复征求既有测试授权的项目条件，Pi仍须遵守自身执行权限及既定测试边界。

### 2026-09-21：本机Pi接手后补齐T098平台验收器接线（中间候选7942277e）

正常用户环境核对：UID 1002、`/`与`/tmp`属主为root（无65534映射问题）、无遗留验收进程；Node发现为v24.1.0、npm 11.3.0、无bun，均非锁要求。按锁准备独立工具链：Node v24.14.0（nodejs.org官方SHASUMS256校验通过）、npm 11.19.1（registry SRI sha512校验后安装进前缀）、Bun 1.4.0（GitHub下载停滞，改用官方npm包`@oven/bun-linux-x64@1.4.0`，SRI sha512与shasum双校验通过），位于`~/.local/share/agentcfg-pi-tools`；node tarball sha256 `41cd79bb7877c81605a9e68ec4c91547774f46a40c67a17e34d7179ef11729df`，bun tgz sha256 `1e812bd440362ae0a7f99f340a4d1202a1ed6c8e97553c820ffbb6445e576a65`。

T098逐项审计结论与改动：

- `pi_validation_native.py`：四条硬编码`非Linux即not-run`的inline门控收敛为单一`platform_limitation()`按能力推导。`delegate-control`、`delegate-proxy-control`、`migration-runtime-conflicts`及三项`codex-native-*`在darwin密封`bin/pi-supervisor-macos`运行包下放行（经`macos_helper_sealed()`读取运行包收据判定），缺helper时报`*-requires-macos-sealed-helper`；`recovery-grants`与`parent-loss`保留`*-requires-linux`原因不变，因其真实依赖Linux pidfd身份信号入口，不能伪装成darwin。原因字符串无任何归档报告引用过，语义修正安全。
- `pi_validation_sandbox.py`：darwin分支补上`local_runtime`实例slot接线。sandbox-exec无bind挂载且`inspect_runtime`拒绝符号链接根，改为整包拷贝为真实目录；原始运行包仍在策略reads中只读，副本变更只影响本夹具实例（darwin特有限制已注释）。
- `activity_macos.py`：`MacProcesses`新增显式`send_signal`，直接`Conflict("macOS停止必须通过helper控制通道")`，把父丢失场景在darwin的AttributeError变为明确平台契约拒绝；不对裸PID发信号。
- 能力覆盖核查：scope冻结364项、无ReadSeek独立场景项；ReadSeek工具操作完整用户流程仍只有mock覆盖（native场景组不驱动ReadSeek工具流），按交接要求记为已知限制落盘，不擅自扩scope。新增针对门控/slot/helper契约的替身与负向回归5项，定向114项通过。

源码变化进入锁：`resolve_lock()`复现解析，`recipe_digest`覆盖`src/agentcfg/*.py`与`scripts/pi-*.py`控制代码，故身份随T098改动变为 `7942277ef024eb2cd4bb5e5754037ac3c879df449a4e8ff4bc17ab7a72f53189`；与484f07e9冻结manifest逐项对比，来源/切片/工具链/构建步骤全部一致，仅recipe_digest随代码变化，vendor归档0差异，`locks/dsh`逐文件未变。484f07e9的旧证据保留原样，不给旧报告改身份；四配方原生证据需按新候选重新取得。

完整mock在锁定工具链下通过：pytest 1787 passed + 7 subtests（1782+5恰为新增测试）、Node 325 passed。该次候选身份为 `7942277e…`，其报告 `agentcfg-pi-mock-20260921-7942277e.json` 保留；随后冷重建在sync阶段失败，原因是本机出口对 github releases CDN（`release-assets.githubusercontent.com`）与huggingface不稳定（单连接成功率约50%，curl实测同一资产一次2.2秒成功、一次30秒连接失败），旧484f07e9首轮的TLS失败本轮未复现（pythonhosted可达，python-environment步骤通过）。

### 2026-09-21：资产vendored后最终冻结4c043f8f

为消除CDN不稳定对sync的影响且不放宽任何校验：利用锁已有的asset `vendor_path`机制（读取`locks/pi/<vendor_path>`并强制比对`archive_digest`），把6个linux/all资产vendored进`locks/pi/vendor/`：bwrap tarball（本轮下载后校验）、codex/code-mode-host/responses-api-proxy三个tar.gz（github重试下载后校验，其中codex主归档首次截断、重下后匹配）、readseek视觉模型与projector（从旧484f07e9已验证运行包中取出，sha256与固定摘要逐一比对通过）。`agents/pi/dependencies.json`仅增加6个`vendor_path`字段（与冻结副本的canonical格式逐字节一致，语义diff仅此6项）；darwin/arm64资产保持下载模式，本轮不需要且避免无谓增大仓库。`resolve_lock()`重新解析：新候选 `4c043f8fa2f52cc7b198a030c51f814ba937c405da100331ed75bd8a73993424`；与484f07e9对比仅`recipe_digest`与6个asset源（仅新增vendor_path）变化，profile_slices逐字节相同，`locks/dsh`逐文件未变，`read_lock()`全量校验（含vendor摘要）通过。7942277e仅在mock阶段存在过，未产出任何原生证据，旧报告保留不删除。

最终候选的完整mock重新通过：pytest 1787 passed + 7 subtests、Node 325 passed，报告 `docs/acceptance/agentcfg-pi-mock-20260921-4c043f8f.json(.artifacts)`。中途一次整库运行在`test_project_target_only_idempotent_and_conflicts`出现跨秒`st_atime`竞态失败（stat比较包含atime，第二次apply读取文件跨过1秒边界即触发）；单测连续6次通过，属既有测试在特定秒边界的闪失，非本次改动回归，不修改生产代码或放宽断言。四配方双路径冷重建随后启动。

### 2026-09-21：四配方双路径冷重建全部通过，T106关闭

pi-default与pi-cursor并行、随后pi-codex与pi-managed并行（7942277e轮的sync失败目录改名`retired-7942277e-sync-fail-*`保留），全部完成：8个新HOME/checkout各自python-environment/sync/apply退出0、安装verified、原生全passed——default两组各6场景（含optional-services）、cursor两组各5场景、codex两组各6场景（codex-receipts官方CLI只读/写入/控制全过，484f07e9轮的资产校验失败未复现）、managed两组各5场景（taskkeeper-lifecycle 11项含两项proxy全过，TLS失败未复现）。8目标源码摘要一致（`615713e72cd2803b…1938`）、每配方运行包身份一致；宿主租约82/82回收、v3进程记录92/92终止（1条external failed为负向场景预期）。证据归档 `docs/acceptance/pi-cold-4c043f8f/`（184文件+index.json全SHA核对），平台记录 `pi-linux-x86_64.json` 置 passed，候选记录 `pi-candidate-4c043f8f.json` 保存（来源31/31、调用方37/37、旧依赖0）。tasks.md T098、T106勾选（106/112）。

report-only成功（364项identity未登记均not-run）、check-release返回1=有效不批准，报告存 `pi-status-20260921-4c043f8f.json` / `pi-release-decision-20260921-4c043f8f.json`。新阻塞记录 `pi-validation-blockers-4c043f8f.md` 落盘：逐条scope证据登记属T112核心剩余（不复制native汇总给所有V项）；ReadSeek工具完整用户流程仍仅mock覆盖（不擅自扩scope）；剩余阻塞=live配置/项目绑定（用户）、三个无机器平台、T112最终批准。支持矩阵说明行更新。运行根 `~/.cache/agentcfg-pi-handoff/run.9EvW7wDS` 保留审计用，确认无活动进程后由用户清理。

### 2026-09-21（二）：复核缺口补齐——macOS执行器、ReadSeek原生覆盖、测试稳定性、vendor交付

**T098边界更正与macOS执行器**：第一轮把darwin的recovery-grants/parent-loss以`send_signal`拒绝契约充当实现，本轮修正为真实执行器，状态明确为“已实现、仅缺实机验证”（归T108/T109执行，非缺实现）——

- parent-loss：`ParentLossSupervisor.terminate_parent_host(lease_id)`按平台派发（`kill_platform`可注入测试）；darwin先`store.request_cancel`撤权（grant_generation+1）再`MacProcesses.stop(force=True)`经持有helper的kill-control强停宿主（audit-token身份核对、收据链），linux保持pidfd SIGKILL。预期宿主退出码两种路径均为137。替身测试验证darwin走request_cancel+helper_stop、linux走pidfd信号，无裸PID路径。
- recovery-grants：`run_recovery_case`拆出darwin分支；owner由测试侧helper包裹（supervise握手+nonce+控制套接字），darwin下owner先用自己持有的helper停worker留下terminated收据（无收据的死亡在darwin不被恢复路径采信——`termination_status`只认收据文件，helper死亡不影响已落盘收据读取），写`recovery-armed.json`后由测试侧`kill-control <nonce> 2`整体停止owner作用域；live_owner_rejected/wrong_plan_rejected/stop_only_recovery/target_terminated/source_preserved各事实与Linux一致。`pi-native-recovery.py`放开darwin（owner武装模式），worker-marker模式不变。`pi_recovery.make_processes`本就平台分发，恢复授权契约零改动。
- 调度门控darwin两场景由`-requires-linux`改为按密封helper放行（缺helper报`recovery-runner-requires-macos-sealed-helper`/`parent-loss-runner-requires-macos-sealed-helper`），未知平台仍`-requires-linux`/`scenario-not-implemented`。`MacProcesses.send_signal`显式拒绝保留为契约护栏。

**ReadSeek原生覆盖**：新增native场景`readseek-tools`（ordinary配方：default/codex/cursor；managed按能力矩阵用tk工具，映射`readseek-profile-required`）：ScriptedProvider新`readseek`脚本按已调用序列驱动真实`readSeek_grep→view→write→edit→rename`+越界写拒；`native-validation.ts`逐步验证工具结果与文件实际状态（写入/编辑/符号重命名落盘核对、越界写local.toml必须isError、项目无残留、code.txt不变）；`verified_result`要求八项事实+provider.requests≥6；`--case readseek-tools`进CLI CASES与quickstart。能力矩阵依据：pi-readseek为O保留、含edit/write/rename不当只读，本轮把既定要求的验收缺口补齐，未扩scope。

**测试稳定性**：`test_project_target_only_idempotent_and_conflicts`根因为完整`stat`比较含`st_atime`——第二次apply为比对内容读取文件，atime跨秒更新是合法读取副作用，不代表重写。修正为幂等真义断言（mtime_ns/ctime_ns/size/内容四轮不变），5轮复跑稳定；未触碰生产读取语义。

**vendor交付**：新`scripts/fetch-pi-assets.py`（非pi-前缀，不进recipe_digest）：从dependencies.json固定URL重建vendor——下载每轮全量SHA-256/大小校验、截断或损坏自动整体重下（续传仅用于连接中断）、0600临时文件原子发布、已验证跳过、摘要不一致默认拒绝覆盖（`--force`）、拒绝非https/内嵌凭据/带query的URL。4项替身测试覆盖发布/跳过/续传重组/摘要拒绝/URL校验。交付文档 `docs/acceptance/pi-vendor-deliverability.md` 写明A（固定URL重建）/B（制品镜像+同口径校验）两条路径与大小清单。

源码变化使pi-runtime归档摘要改变（级联切片身份），重新冻结候选 **`2146aeb4eb6d00dca7706b1298b2d889ff69c9fd5fad5ef81ef00acf861fbc84`**；`locks/dsh`不变、read_lock校验通过、来源38不变。完整mock：**1804 pytest + 7 subtests、325 Node全通过**（新增17项），报告 `agentcfg-pi-mock-20260921-2146aeb4.json`。四配方双路径冷重建（含新readseek-tools场景）随后启动；干净环境交付验证v1（mirror+摘要+staleness检测）与v2（删vendor后真实URL重建）并行进行。

### 2026-09-21（二续）：recovery回归修复、stash事故与冻结78c0739d

第一轮冷重建（2146aeb4）发现并修复：

1. **recovery重复写入回归**（本轮引入）：`run_recovery_case`重构时wrapper与`_run_recovery_case_linux`重复写`recovery-input.json`（write_new冲突），termination-recovery失败并中断后续场景。已修复，旧报告保留在运行根`attempt1-evidence/`（79文件+REASON.md，大安装树已删腾盘）。
2. readseek-tools首轮接线缺口见（三）。

**stash事故与恢复**：排查中误执行`git stash`卷走22个跟踪文件的未提交迁移修改（含storage.py的`write_new`族、test_project修复等），发现并立即`git stash pop`恢复，全量定向测试确认无损；在stash污染状态下解析的候选455c22fb作废不留档。

候选 **`78c0739d82a09fc8638a3b4d4b76fe59a9a4cadc85ef25b6e8dab04b751f2478`**（`locks/dsh`不变）；完整mock **1804+7/325全通过**（`agentcfg-pi-mock-20260921-78c0739d.json`）。干净环境交付验证：v1通过（mirror+摘要+staleness）；v2/github下载路径实证（bwrap与code-mode-host真实下载发布），99MB codex与1.5GB HF资产在本出口超时——下载机制单测全覆盖，大文件受出口限制记录为环境事实，交付文档已写明双路径。

### 2026-09-21（三）：readseek原生链路四轮实证修复后冻结d3ed4cd7

readseek-tools冷重建逐轮暴露真实接线缺口（每轮失败码精确定位，全部修复并补防回归）：

1. 场景未列入`native_cases()`（从未执行）→ 已补，限定pi-default/pi-codex（cursor为Bun宿主，readseek worker的锁定node解释器绑定未设计，列剩余项）。
2. pi-readseek扩展在`before_agent_start`才激活工具 → mjs热身prompt后再核对活动工具名；provider改为按prompt点名驱动。
3. 部署未选pi-readseek插件 → 场景级显式选择（同服务验收模式），fixture注入`options.readseek`三绑定（node=锁定引擎、git=programs、rg=系统rg只读绑定）+独立策略`readseek-candidate`/`delegate-worktree-readseek`（初版改共享策略造成悬空command_ref校验失败，已纠正为独立策略）。
4. **driver命令记录缺顶层`temporary`**（`pi_readseek_prepare`真实bug，`closed()`一检即退5；mock从未断言driver的closed契约）→ 已补`session_root/scratch/<key>`并加回归断言。mjs失败时落盘实际工具结果（`readseek-failed-step.json`）可观测性。
5. **rg选型列出.git元数据**：`rg --files --hidden`输出含11条`.git/`记录，安全解码`decode_git_paths`按设计拒绝（worker不得接收Git元数据）→ 源头glob排除`!.git`/`!**/.git/**`/`!.readseek`，真实输出验证洁净+防回归测试。
6. **readSeek_view不识别无语言文件**（`view does not support this document format`）→ 读取步改用规范的`readSeek_digest`（别名表read→digest；digest对未知语言文本正常返回内容，已实测）。
7. **vendor插件9个工具入口仅grep/write调用`ensureHashInit()`**（xxhash WASM惰性初始化）——上游共享会话进程由首个grep/write隐式初始化所以隐性；agentcfg每操作独立worker进程下edit等入口的LINE:HASH计算必然失败关闭（离线worker复现拿到真实堆栈`Hash not initialized`，编辑已落快照仅卡此后崩溃）。已在`readseek-vendor`源为全部7个缺失入口补齐初始化，NOTICE与派生patch附记同步。
8. **场景收尾清单漏夹具自带文件**（`test_native_fixture.py`）→ 修正期望清单。

r11（候选32da4799）实证：**pi-default双路径完整通过，readseek-tools全步成功**——检索/读取/写入/编辑/符号重命名级联/越界写拒/源项目保护/活动清空八项事实全真，正式归档 `pi-cold-32da4799/pi-default/`。**pi-codex同样双路径完整通过**（readseek-tools+codex-receipts官方CLI三态），已归档。pi-cursor与pi-managed接续运行。

最终候选 **`506a9b106e7137cf64ed6c5e33423425c7e10fb06f9b5f0933db58177ef1dab6`**（`locks/dsh`不变）；完整mock **1805+7/325全通过**（`agentcfg-pi-mock-20260921-506a9b10.json`）。pi-default+pi-codex冷重建（r9）随后启动，cursor+managed接续。
