# Tasks: OMP 权限管控

当前任务已扩展到独立插件迁移（T088 起）；T001—T087 的闭合仅代表历史补丁方案。当前需求与边界见[独立插件修订](standalone-plugin.md)。


当前进度（2026-09-30）：T001—T087共87项已闭合；Phase 11是当前交付。Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。 真实Cursor目录、GLM备用质量、tiny推理及其它平台未验证；历史付费账本不变。
**Input**: `specs/004-omp-permission-control/` 中的 spec、plan、research、data-model、quickstart 与四份 contracts

**Prerequisites**: `plan.md`、`spec.md`、`research.md`、`data-model.md`、`contracts/`

**Tests**: 规格明确要求测试。每个用户故事先编写隔离测试并确认在实现前因缺少行为而失败；默认测试不得启动 OMP CLI/TUI、真实 worker、真实模型或访问网络。

**Organization**: 八个阶段按共享基础和五个用户故事组织。原始 T001—T073 保留稳定 ID；实施时经用户确认新增的 T074—T077 按其显式插入点和依赖执行，不重编号已完成任务。标记 `[P]` 的任务只在其注明的前置任务完成后，因写入不同文件且没有直接依赖才可并行。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 前置条件完成后可与同组其它 `[P]` 任务并行
- **[Story]**: 仅用户故事阶段使用 `[US1]`—`[US5]`
- 每项任务都给出精确文件路径；同一 patch series、`index.ts`、`controller.ts`、`src/agentcfg/omp.py` 始终串行由单一写入者维护

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 建立可隔离执行的源码、fixture、补丁和证据骨架，不接触本机 OMP。

- [X] T001 创建扩展源码与测试目录、补丁测试目录、固定样本目录和交付证据目录的占位说明，明确所有默认测试使用临时 HOME/XDG/OMP home/cache、假 subprocess/provider/execute、网络阻断和文件哨兵，不启动第三方宿主，写入 `agents/omp/packages/omp-permission-control/README.md`
- [X] T002 [P] 在 T001 后创建扩展包元数据，固定包名 `omp-permission-control`、入口 `index.ts`、OMP v18.3.0/Bun 兼容范围且不声明安装脚本或运行时下载，写入 `agents/omp/packages/omp-permission-control/package.json`
- [X] T003 [P] 在 T001 后、任何规则实现前建立标签 schema，并实际冻结不少于 100 条 policy-safe、100 条 ask/deny、40 条故障/状态样本到 `cases.jsonl`，要求 safe 与 ask/deny 各至少 30 条 compound、每例含完整动作/平台/shell/cwd 类别/原生规则/真实用户来源证明/预期结果/理由，另生成逐标签数量与冻结 tree digest 摘要；digest 只覆盖 `fixture-schema.json`、`cases.jsonl`、`labels.json` 三者的相对路径与文件字节，不包含记录摘要的 `FROZEN.md` 自身，也不包含后续原生基线结果或 runtime fixture。四项一同进入 Git，后续禁止删改标签、重标失败样本或补录用例来覆盖已见结果，写入 `tests/fixtures/omp/permission-control/fixture-schema.json`、`tests/fixtures/omp/permission-control/cases.jsonl`、`tests/fixtures/omp/permission-control/labels.json` 与 `tests/fixtures/omp/permission-control/FROZEN.md`
- [X] T004 [P] 在 T001 后建立 OMP v18.3.0 commit `62bc57be1b03ef0802a33cf7f5f530e534527531`、archive SHA256、完整 bun.lock 身份、补丁顺序和 bridge ABI `permission-control/v1` 的来源账本；同时实现严格封闭的构建输入 schema 与正式输入锁，顶层字段恰为 `schemaVersion`、`platform`、`upstreamSource`、`dependencyLock`、`tools`、`dependencyArtifacts`：`upstreamSource={commit,archiveSha256}`，`dependencyLock={path,sha256}`，每个 tool 为 `{name,version,cacheKey,sha256}` 且 cacheKey 是无绝对路径/`..`/逃逸的相对内容键，每个依赖产物为 `{cacheKey,sha256,size}`；清单必须完整传递离线安装所需全部依赖和资源，未知/遗漏项失败，禁止猜值和隐式下载；基础 Bun 身份只来自该独立输入清单，构建前不依赖 receipt，且 build-inputs 不得引用 official recipe identity、补丁锁 identity 或任何构建输出，写入 `agents/omp/patches/permission-control/SOURCES.md`、`schemas/omp-permission-build-inputs.schema.json` 与 `agents/omp/patches/permission-control/build-inputs.lock.json`
- [X] T005 [P] 在 T001 后建立四态验收记录模板：`完成`、`进行中`、`失败待决策`、`环境不足未验证`，另保留 `尚未执行`；每条必须记录命令、隔离环境、结果、范围和未覆盖项，写入 `docs/acceptance/omp-permission-control.md`

**Checkpoint**: `test -f` 核对上述任务声明的全部路径，并校验冻结样本计数/tree digest 与 build-inputs schema/lock；预期仅形成仓库内骨架、实际冻结集和封闭构建输入，本机配置、账号目录和宿主进程均无变化。

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 先建立封闭配置、共享实体、真实宿主补丁接口及离线构建契约，作为所有故事的安全边界。

**⚠️ CRITICAL**: T006—T017 的接口与隔离时序验证完成后用户故事才可开始。T018 的真实离线构建证据是交付门槛；若已准备工具链/依赖缓存不存在，必须把该组记为“环境不足未验证”，但不得把任务勾为完成，也不得阻塞不依赖真实二进制的纯逻辑、Python 或文档工作。

### Tests for shared foundation

- [X] T006 [P] 在 T001—T004 后先编写失败的独立配置 validator 契约测试（本阶段不要求尚未修改的完整 adapter pipeline 通过），覆盖 `permission_control` 封闭对象只允许必填 `default_mode` 和可选 `reviewer_model`、`fallback_model`；`default_mode` 仅 `smart|manual`；`fallback_model` 仅 `local/lfm2.5-230m`；reviewer 必须在同 profile `models` 中且解析为恰好一个 provider/model；未知字段、歧义、未选择、plugin/variant/config 三方不一致、bash 非 prompt、yolo 均退出 2，写入 `tests/test_omp_permission_control.py`
- [X] T007 [P] 在 T001—T004 后先编写失败的共享 TypeScript 契约测试，覆盖 `PluginDeliveryIdentity.plugin_id="omp-permission-control"`、`manifest_path="locks/omp/permission-control/manifest.json"`、`runtime_variant="permission-control-v1"`、`bridge_abi="permission-control/v1"`、`plugin_tree_digest` 为 SHA-256、`runtime_identity` 为字符串、`load_state=verified|missing|damaged|identity-mismatch|not-loaded|unhealthy`，写入 `agents/omp/packages/omp-permission-control/tests/foundation.test.ts`
- [X] T008 [P] 在 T004 后先编写失败的真实源码补丁测试：补丁必须干净应用到锁定源码，并直接调用 patched wrapper、`prepareBashExecution`、`commitPreparedBashExecution` 配合 fake Settings/UI/provider/execute；断言 prepare 前后 mkdir/direnv/service/job/backend 哨兵均为 0、commit 前执行为 0、commit 后实参逐字节等于 frozen plan 且恰好一次，写入 `agents/omp/patches/permission-control/tests/bridge.integration.test.ts`

### Implementation for shared foundation

- [X] T009 在 T007 后定义共享实体：`ManagedPermissionConfig.runtime_variant` 启用时必须为 `permission-control-v1`、`default_mode` 必填且为 `smart|manual`、`reviewer_model` 可选且须已选择、`fallback_model` 可选且唯一值 `local/lfm2.5-230m`、`plugin_selected` 必须选择插件；`NativePermissionControl.schemaVersion=1`、`defaultMode=smart|manual`、`reviewer=session|{provider,model}`、可选 `fallback={provider,model,installedOnly:true}`、`bridgeAbi="permission-control/v1"`、`pluginId="omp-permission-control"`、`pluginDigest`/`policyVersion` 为 SHA-256、`runtimeIdentity` 非空，未知字段全部拒绝，写入 `agents/omp/packages/omp-permission-control/types.ts`
  **约束原文（T009 必须逐字段实现）：**

  | 实体.字段 | 类型 | 约束/说明 |
  |---|---|---|
  | `ManagedPermissionConfig.runtime_variant` | 字面量 | 启用本功能时必须为 `permission-control-v1` |
  | `ManagedPermissionConfig.default_mode` | `smart \| manual` | 必填；`omp-kernel` 为 `smart` |
  | `ManagedPermissionConfig.reviewer_model` | 可选 rotom model ID | 若存在，必须同时出现在该 profile 的 `models` 选择中 |
  | `ManagedPermissionConfig.fallback_model` | 可选字面量 | 唯一允许值为 `local/lfm2.5-230m`；省略表示禁用 |
  | `ManagedPermissionConfig.plugin_selected` | 布尔派生值 | 必须选择 `omp-permission-control` |
  | `NativePermissionControl.schemaVersion` | `1` | 原生对象版本 |
  | `NativePermissionControl.defaultMode` | `smart \| manual` | 每次新建或恢复会话的期望模式 |
  | `NativePermissionControl.reviewer` | `session` 或 `{provider, model}` | 缺省动态绑定审查开始时的会话主模型；显式值是已解析原生模型 |
  | `NativePermissionControl.fallback` | 可选 `{provider, model, installedOnly}` | 省略即禁用；首版只允许本地 tiny 且 `installedOnly=true` |
  | `NativePermissionControl.bridgeAbi` | `permission-control/v1` | 插件与补丁宿主的 ABI |
  | `NativePermissionControl.pluginId` | `omp-permission-control` | 插件身份 |
  | `NativePermissionControl.pluginDigest` | SHA-256 | 已锁定插件树身份 |
  | `NativePermissionControl.runtimeIdentity` | 非空身份字符串 | 已锁定 patched runtime 资产身份 |
  | `NativePermissionControl.policyVersion` | SHA-256 | 影响判定的固定策略与配置的生成摘要 |
  | `PluginDeliveryIdentity.plugin_id` | 字面量 | `omp-permission-control` |
  | `PluginDeliveryIdentity.plugin_tree_digest` | SHA-256 | 插件源码及受管入口点摘要 |
  | `PluginDeliveryIdentity.manifest_path` | 字面量 | `locks/omp/permission-control/manifest.json` |
  | `PluginDeliveryIdentity.runtime_variant` | 字面量 | `permission-control-v1` |
  | `PluginDeliveryIdentity.runtime_identity` | 字符串 | patched OMP v18.3.0 构建资产身份 |
  | `PluginDeliveryIdentity.bridge_abi` | 字面量 | `permission-control/v1` |
  | `PluginDeliveryIdentity.load_state` | 枚举 | `verified \| missing \| damaged \| identity-mismatch \| not-loaded \| unhealthy` |
- [X] T010 [P] 在 T006 后实现 `permission-control-v1` 严格 runtime schema，封闭 manifest 字段恰为 `schemaVersion`、`variant`、`upstreamIdentity`、`bridgeAbi`、`patches`、`buildReceiptDigest`、`pluginDigest`、`assets`、`identity`；`patches` 是有序相对 path/SHA256 数组，assets 按平台含 `cacheKey`/`sha256`/`size`，identity 是去掉自身后的规范 JSON SHA-256，cacheKey 必须是摘要相对键并拒绝绝对路径、`..`、符号链接和逃逸，写入 `schemas/omp-permission-runtime.schema.json`
- [X] T011 在 T006、T009 后实现 profile 配置解析并同步原生 settings schema：拒绝未知字段、原生片段透传、手填 `pluginDigest|runtimeIdentity|policyVersion`，对 `/permissionControl` 和嵌套 reviewer/fallback 设置 `additionalProperties:false`，保留 direnv/devenv/prefix/service/async/PTY/ACP/useUserShell/启动脚本原义且不为覆盖率静默改写，写入 `src/agentcfg/omp_settings.py` 与 `schemas/omp-agent.schema.json`
- [X] T012 [P] 在 T002、T009 后注册本地插件来源、入口和 tree digest 计算输入，不执行扩展源码或技能脚本，写入 `agents/omp/plugins.toml`
- [X] T013 在 T008、T009 后编写有序 patch series：patched settings 对 `/permissionControl` 及嵌套对象 `additionalProperties:false`，未选择功能不生成对象；minimal shim 保留 native prompt，选择插件却缺对象/ABI 时失败关闭，写入 `agents/omp/patches/permission-control/series`
- [X] T014 在 T013 后实现 `permission-control/v1` bridge 补丁，提供无副作用 `prepareBashExecution` 与只消费同一不可变计划的 `commitPreparedBashExecution`；`PreparedBashExecution.prepared_execution_id` 为宿主不可伪造内存身份且与 request/session/generation 一一绑定，`final_command` 为易失字节串，`transformation_summary` 为不含秘密或自由文本的固定结构，`execution_binding` 为绑定最终 args/cwd/shell/backend/环境摘要/目标指纹/延迟效果/算法版本的摘要与本地引用，`coverage_state=eligible|manual-required`，`coverage_reasons` 为 direnv/devenv、prefix、service/async/PTY、ACP terminal、未知启动脚本等固定枚举数组；纯 prepare 不得 mkdir、加载环境脚本、启动进程/daemon/job 或执行探测 shell，写入 `agents/omp/patches/permission-control/0001-host-bridge.patch`
  **约束原文（T014 必须逐字段实现）：**

  | 实体.字段 | 类型 | 说明 |
  |---|---|---|
  | `PreparedBashExecution.prepared_execution_id` | 宿主不可伪造内存身份 | 与 request/session/generation 一一绑定 |
  | `PreparedBashExecution.final_command` | 易失字节串 | interceptor、确定性 cwd/参数变换后的实际待执行 command；模型只接收其允许发送的完整脱敏视图 |
  | `PreparedBashExecution.transformation_summary` | 固定结构 | raw request 到最终 command 的变换种类与必要效果，不含秘密或自由文本 |
  | `PreparedBashExecution.execution_binding` | 摘要与本地引用 | 绑定最终 args、cwd、shell、backend、环境摘要、目标指纹、延迟效果及 prepare 算法版本 |
  | `PreparedBashExecution.coverage_state` | `eligible \| manual-required` | 只有完全可准备的前台 native backend 可为 eligible |
  | `PreparedBashExecution.coverage_reasons` | 固定枚举数组 | direnv/devenv、prefix、service/async/PTY、ACP terminal、未知启动脚本等实际不覆盖原因 |
- [X] T015 在 T014 后运行补丁干净应用与 T008 真实函数测试；默认未注册 reviewer 的路径必须与上游行为等价，且 explicit-deny、command-prompt、critical-safety、未知来源仍由原生保护，结果记录到 `docs/acceptance/omp-permission-control.md`
- [X] T016 [P] 在 T004、T010 后实现显式离线构建入口：先按 `schemas/omp-permission-build-inputs.schema.json` 校验并消费 `agents/omp/patches/permission-control/build-inputs.lock.json`，再逐字节验证已准备 source/tool cache/dependency cache 中的上游 archive、dependency lock、全部 tools 和 dependencyArtifacts，platform 必须一致；缺失、额外未声明、摘要/大小/版本不符均在执行构建前失败，禁止猜值、搜索全局安装和联网补齐。基础 Bun 身份从 build-inputs lock 验证，输出 asset 与含完整输入/工具链/依赖来源/平台/输出摘要的 receipt，receipt 仅在产出后与独立输入锁交叉校验；补充纯 Python schema/边界测试，使缺 Bun 时文档、schema 和输入闭包验证仍可继续，写入 `agents/omp/build-permission-control.py` 及 `tests/test_omp_permission_build_inputs.py`
- [X] T017 在 T010、T016 后实现补丁 manifest、receipt、ABI、平台资产和 plugin digest 的纯校验模块；结构错退出 2，缺平台或资产/身份/ABI 不兼容退出 5，错误只含字段路径、固定原因码和非秘密摘要，写入 `src/agentcfg/omp_permission_runtime.py`
- [X] T018 在 T014—T017 后用已准备的锁定源码、工具链和依赖缓存显式执行一次 `agents/omp/build-permission-control.py --offline`，只核对 patched standalone 实际 SHA/size、静态声明 ABI、receipt 和不联网哨兵并写入 `docs/acceptance/omp-permission-control.md`；不得执行 `omp --version`、CLI 或宿主握手，真实 ABI 加载只归 T072；缺准备输入时保持本任务未完成并只登记该构建组“环境不足未验证”，不得用猜测摘要或源码测试代替
- [X] T019 在 T006—T017 后执行 `.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_build_inputs.py`，并以 T004 独立 build-inputs lock 校验已准备 Bun 后运行 `foundation.test.ts`、`bridge.integration.test.ts` 的纯模块测试；有构建 receipt 时只做产出后的身份交叉核验，不把它当 Bun 身份来源。预期 config validator、构建输入闭包、共享类型、真实 wrapper prepare-commit 和副作用哨兵通过且不启动宿主；Bun 缺失时 TS 基础门槛保持未通过并登记环境不足，Python 组继续，证据写入 `docs/acceptance/omp-permission-control.md`

**Checkpoint**: T006—T017 与可执行的 T019 证明接口、严格配置和真实源码隔离时序；T018 单独决定是否已有可交付二进制，不能用其环境不足阻塞故事逻辑，也不能据此宣称 kernel 可用。

---

## Phase 3: User Story 1 - 智能审查完整命令副作用 (Priority: P1) 🎯 MVP

**Goal**: 对完整 prepared Bash 计划按硬规则、人工边界、确定性低风险和主审建议固定排序，批准前零执行副作用并只消费一次许可。

**Independent Test**: 在临时 HOME/XDG、假模型/UI/execute 和网络阻断下，用低风险、高风险、禁止、复合、未知语法和不可信授权样本验证结果、调用次数、无重复 prompt 与逐字节执行一致性。

### Tests for User Story 1

- [X] T020 [P] [US1] 在 T019 后先扩充会失败的 shell/policy 测试，覆盖字面量简单命令及 `&&|\|\||;|管道` 整体效果、引号/转义/注释/重定向，以及变量/命令或进程替换/glob/here-doc/后台/函数/控制结构/脚本内容为 unknown；连接符本身不决定结果。另覆盖绑定 generation 的用户限制状态 `clear|conflicting|unknown`：clear 仅在上下文完整、没有待解释用户自由文本且结构化限制机械检查全通过时成立，已知结构化限制冲突为 conflicting，其余包括自由文本或缺上下文为 unknown；仅 clear 可走确定性受限只读，conflicting 必须人工或原生 deny 且不交主审覆盖，只有 unknown 在 smart 可进入本次主审解释，manual 人工，主审结果不缓存成默认 clear；写入/删除、网络发送、凭据/秘密或设备访问不能因模型给 low 自动 allow，未知效果 ask，写入 `agents/omp/packages/omp-permission-control/tests/policy.test.ts`
- [X] T021 [P] [US1] 在 T019 后先编写会失败的模型 JSON 契约测试，顶层字段必须恰为且全部必填 `decision`、`risk`、`authorization`、`effects`、`unknowns`、`reasonCode`、`evidence`；拒绝额外字段、Markdown/前后文本、工具调用、NaN、重复 key、自由文本理由；`decision=allow|ask|deny`、`risk=low|medium|high|unknown`、`authorization=sufficient|insufficient|conflicting|unknown`，effects 唯一且精确覆盖全部 effectId，unknowns 最多 7 且只允许 `dynamic-syntax|unresolved-target|redaction-loss|missing-context|ambiguous-authorization|unsupported-effect|state-not-verifiable`，reasonCode 只允许 `LOW_RISK_AUTHORIZED|USER_CONFIRMATION_REQUIRED|AUTHORIZATION_INSUFFICIENT|AUTHORIZATION_CONFLICTING|MATERIAL_RISK|PROHIBITED_EFFECT|UNKNOWN_EFFECT|INCOMPLETE_CONTEXT|REDACTION_LOSS|POLICY_MISMATCH`。`evidence` 必须恰有 `userMessageIds`、`bindings`；userMessageIds 唯一且最多 16、只接受宿主认证真实 user 来源且不得含无 binding 的 ID；bindings 每项恰有 `effectId`、`userMessageId`、`startByte`、`endByte`、`scopeDigest`，ask/deny 可为空，模型 allow 时每个输入 effect 恰一项且数组非空，ID 必须来自输入并相互对应，UTF-8 半开字节区间必须非负、start<end、位于脱敏消息字符边界，scopeDigest 必须等于宿主随该 effect 提供的种类/规范目标/完整参数/cwd/执行上下文会话盐摘要；allow 的重复、缺漏、伪造/越界引文、错对象/参数/cwd 摘要、超 512 tokens/4 KiB 均使 allow 无效并转 ask 且不重试，合法 ask/deny 的空 bindings 不归 invalid-output、不得触发 tiny，写入 `agents/omp/packages/omp-permission-control/tests/reviewer-contract.test.ts`
- [X] T022 [US1] 在 T019 后先扩充会失败的 patched bridge 测试，覆盖 native deny/command prompt/critical/unknown 优先、tool-default 可委派、人工 UI 恰一次、有效 allow 不重复 prompt、批准前所有副作用哨兵为 0、执行参数等于 prepared plan、deny/ask 不改入口重试，写入 `agents/omp/patches/permission-control/tests/bridge.integration.test.ts`
- [X] T023 [P] [US1] 在 T019 后先编写会失败的一次性许可/并发测试，覆盖同会话 Bash 从审查至发起串行、不同 request/session 不共享、取消/编辑/参数/cwd/shell/目标/授权/模式/策略/模型/身份/健康变化失效、迟到响应不恢复、许可只允许 `pending→consumed` 一次，写入 `agents/omp/packages/omp-permission-control/tests/permit.test.ts`

### Implementation for User Story 1

- [X] T024 [P] [US1] 在 T020 后实现不执行输入的保守 Bash 分析器，效果含请求内唯一 `effectId`、固定种类、目标类别和影响等级；受限允许表只覆盖完整选项/操作数约束的 `pwd|ls|head|wc|rg|git status|git diff|git log`，pager/external diff/textconv/exec/设备/秘密路径/未知可执行/仓库脚本不得按首词放行，写入 `agents/omp/packages/omp-permission-control/shell-analysis.ts`
- [X] T025 [P] [US1] 在 T020、T021 后实现固定策略顺序 `explicit deny → mandatory human/native protection/known structured restriction conflict → coverage/health/completeness gate → deterministic low risk → manual boundary → reviewer synthesis → qualified tiny tightening`；确定性受限只读前必须验证用户限制状态 clear，conflicting/unknown 不直通；已知结构化 conflicting 必须人工或原生 deny 且不能由主审覆盖，仅 unknown 在 smart 可进入本次主审解释。模型仅在 low+sufficient+unknowns 空+effects 全覆盖、完整上下文及逐 effect evidence 通过机械核验时可能 allow，medium/high/unknown 最多 ask，写入/删除、网络发送、凭据/秘密或设备访问受固定风险下限阻止仅凭 model low 自动 allow，未知效果 ask。自然语言授权语义由主审判断，宿主不宣称独立证明；本次结果不缓存为后续授权，写入 `agents/omp/packages/omp-permission-control/policy.ts`
- [X] T026 [US1] 在 T021、T024 后实现 `ReviewRequest`：`request_id` 会话内唯一，`session_id/generation` 固定，`operation` 是完整脱敏 final command 且不入审计，`operation_digest` 为会话盐 SHA-256，`argv_digest` 为 SHA-256，`prepared_execution_id/execution_binding/transformation_summary/execution_context/effects/native_constraints/authorization_evidence/mode/policy_version/reviewer/reviewer_source` 必填，`fallback` 可选，`deadline` 为开始构造起 30 秒单调时钟，`cancel_state=active|cancelled`；每个 effect 的宿主 `scopeDigest` 随输入提供，主审收到相关真实用户消息的完整脱敏上下文（含更晚限制/撤销，而非只给它选出的引文），限制状态 `clear|conflicting|unknown` 与 generation 绑定；输入 ≤24 KiB、输出 ≤512 tokens 且 ≤4 KiB，不能完整表达上下文/evidence 或脱敏损失时 ask/无 UI 阻止，不拆成多次推理，写入 `agents/omp/packages/omp-permission-control/reviewer.ts`
  **约束原文（T026 必须逐字段实现）：**

  | 实体.字段 | 类型 | 说明 |
  |---|---|---|
  | `ReviewRequest.request_id` | 随机 ID | 会话内唯一，用于关联 |
  | `ReviewRequest.session_id / generation` | 身份 | 绑定当前会话保护基线 |
  | `ReviewRequest.operation` | 易失 UTF-8 字符串 | `PreparedBashExecution.final_command` 的完整脱敏视图，不是 raw args；不入审计 |
  | `ReviewRequest.operation_digest` | 会话盐 SHA-256 | 审计关联身份，不能跨会话追踪正文 |
  | `ReviewRequest.argv_digest` | SHA-256 | 绑定工具名和最终参数 |
  | `ReviewRequest.prepared_execution_id / execution_binding` | 宿主引用与摘要 | 绑定唯一 prepared plan；最终核验和 commit 必须使用同一计划 |
  | `ReviewRequest.transformation_summary` | 固定结构 | 随最终 command 交给主审的必要变换摘要；不能只发送 raw args |
  | `ReviewRequest.execution_context` | 结构化对象 | 来自 prepared plan 的 cwd、shell/backend 身份、必要目标状态摘要；排除环境秘密 |
  | `ReviewRequest.effects` | 解析效果数组 | 每项有本请求内唯一 `effectId`、固定种类、目标类别和影响等级，以及宿主按实际种类、规范目标、完整参数、cwd、执行上下文生成并随输入提供的会话盐 `scopeDigest` |
  | `ReviewRequest.native_constraints` | 结构化数组 | 原生来源和每个简单命令的结果 |
  | `ReviewRequest.authorization_evidence` | 宿主认证证据数组 | 仅当前有效上下文中与动作相关、且宿主证明来自真实用户输入通道的消息 ID；完整脱敏消息及更晚限制只在易失模型请求中，ID 或引文机械有效不等于宿主能证明自然语言授权语义 |
  | `ReviewRequest.mode / policy_version` | 固定值 | 审查期间不可变化 |
  | `ReviewRequest.reviewer / reviewer_source` | 固定模型 | 审查开始时解析；不随标题切换 |
  | `ReviewRequest.fallback` | 可选固定模型 | 与标题 tiny role 无关 |
  | `ReviewRequest.deadline` | 单调时钟时间点 | 从开始构造审查上下文起算 30 秒，覆盖预处理、资源检查及模型等待；排队和人工等待除外 |
  | `ReviewRequest.cancel_state` | `active \| cancelled` | 取消后至迟 1 秒失去执行资格 |
- [X] T027 [US1] 在 T023、T025、T026 后实现 `PermissionDecision.decision_id/request_id/outcome/source/reason_code/health_result/created_at_monotonic` 必填，`outcome=allow|ask|deny`，`source=hard-rule|low-risk-rule|reviewer|fallback|manual-boundary|native-protection|system-failure`，可选 model/fallback 结果且未调用时 actual_model/model_source=`not-called`；`HumanDecision` 必须有唯一 ID、仍有效 ask/request、`outcome=allow|deny`、`source=human`、generation/binding；`ExecutionPermit` 必须有唯一 ID、同链 request/decision、`grant_source=automatic|human`、覆盖完整绑定的 SHA-256、`state=pending|consumed|invalidated` 及可选固定 invalid_reason，写入 `agents/omp/packages/omp-permission-control/controller.ts`
  **约束原文（T027 必须逐字段实现）：**

  | 实体.字段 | 类型 | 说明 |
  |---|---|---|
  | `PermissionDecision.decision_id` | 随机 ID | 会话内唯一 |
  | `PermissionDecision.request_id` | 外键 | 指向唯一请求 |
  | `PermissionDecision.outcome` | `allow \| ask \| deny` | 最终策略结果，不是模型原样结论 |
  | `PermissionDecision.source` | 枚举 | `hard-rule \| low-risk-rule \| reviewer \| fallback \| manual-boundary \| native-protection \| system-failure` |
  | `PermissionDecision.reason_code` | 固定枚举 | UI 使用代码模板解释 |
  | `PermissionDecision.model_result` | 可选结构化结果 | 严格 JSON 验证后的主审建议 |
  | `PermissionDecision.actual_model / model_source` | 可选 | 未调用模型时必须为 `not-called` |
  | `PermissionDecision.fallback_result` | 可选 ask/deny | 永远不能产生 allow |
  | `PermissionDecision.health_result` | 固定枚举 | 本次 bridge、主审、tiny 健康摘要 |
  | `PermissionDecision.created_at_monotonic` | 单调时间 | 不用于跨进程授权 |
  | `HumanDecision.human_decision_id` | 随机 ID | 会话内唯一 |
  | `HumanDecision.ask_decision_id / request_id` | 外键 | 必须关联仍有效的原 ask 与同一请求 |
  | `HumanDecision.outcome` | `allow \| deny` | 只接受真实用户 UI 操作；模型、工具和文件不能模拟 |
  | `HumanDecision.source` | 字面量 `human` | 保留 reviewer/fallback/native 的上游 ask 来源链 |
  | `HumanDecision.generation / binding_digest` | 固定身份 | 人工响应到达时必须仍与请求一致 |
  | `ExecutionPermit.permit_id` | 随机 ID | 不可由模型指定 |
  | `ExecutionPermit.request_id / decision_id` | 外键 | 只能关联同一请求链 |
  | `ExecutionPermit.grant_source` | `automatic \| human` | human 时同时保存 `ask_decision_id` 与 `human_decision_id` |
  | `ExecutionPermit.binding_digest` | SHA-256 | 覆盖 prepared execution 身份与 binding、最终 command/参数、cwd、shell/backend、目标状态、授权、模式、策略、模型选择、插件/runtime 身份和 session generation |
  | `ExecutionPermit.state` | `pending \| consumed \| invalidated` | 仅允许一次 `pending → consumed` |
  | `ExecutionPermit.invalid_reason` | 可选固定枚举 | 记录取消或哪类绑定变化 |
- [X] T028 [US1] 在 T022、T027、T076 后扩展同一 bridge patch，将原生来源分类、完整 prepared plan、人工决定和一次性 permit 接入真实 wrapper；宿主机械验证完整真实用户上下文、evidence 精确字段、真实来源、UTF-8 字节边界、逐 effect 唯一覆盖、scopeDigest、当前 generation 与固定风险下限，任何失败都不能采纳 model allow，但不把这些检查表述为独立证明自然语言授权语义。最终核验后在同步临界区消费 permit 并 commit，中间不得 await、重算 command/cwd/env 或运行新 hook；本次模型/人工结果不写长期授权或跨请求缓存，写入 `agents/omp/patches/permission-control/0001-host-bridge.patch`
### 实施时新增：默认 kernel 兼容（用户明确选择；插入 T028 前后）

T001—T019 的完成证据只覆盖原基础范围；以下新增任务不追溯冒充已完成。T074—T076 在 T028 前完成，T077 在 T028 后、T029 前完成。

- [X] T074 [US1] 把用户明确选择的默认 kernel 兼容纳入 `spec.md`、`plan.md`、`data-model.md`、`contracts/host-bridge.md`、`contracts/review-decision.md` 与本任务表：增加 FR-035—037/SC-012，区分纯 prepare、已有本次批准后的资源 stage、同步消费/启动；保留设置、冷环境初始化人工与无法核实状态降级边界，不动本机配置和冻结样本
- [X] T075 [US1] 在 T019、T024 后先扩充失败的真实补丁测试，保留 kernel interceptor/自动后台默认：未命中 interceptor 不笼统人工、命中保留原无执行引导；冷 snapshot 批准前零生成，初始化后有宿主状态证明的连续低风险请求可进入智能路径；相关名称 shadowing、未知 options、未跟踪执行、snapshot/env/direnv 搜索链变化必须失效；stage 期间取消/配置变动零执行；自动后台前台完成/超阈值/取消行为保持原义，写入 `agents/omp/patches/permission-control/tests/bridge.integration.test.ts`
- [X] T076 [US1] 在 T075、T027 后扩展同一 `0001-host-bridge.patch`：提供纯 interceptor/direnv 检测、带来源的 cached snapshot 元数据与宿主实际 Shell 状态连续性验证；缓存文件存在或全局布尔标记不算证明；未知 mutation 降级且不静默 reset。为 auto-background 分离审批后尚未启动的 artifact/job stage 与最终原子 revalidate/consume/start，必要时扩展原生 job manager 的内部 reservation/start；保留完整原生结果/cleanup和配置，不在纯prepare产生副作用、不在consume后await或重写命令；实际动态初始化仍本次人工，禁止隐式下载/环境探测
- [X] T077 [US1] 在 T028、T076 后将最终完整 series 应用到锁定新副本，运行 T075 兼容组与既有基础13项反例；证明 FR-035—037/SC-012 的隔离行为并写入 `docs/acceptance/omp-permission-control.md`、`quickstart.md`。默认设置兼容样本与冻结240条分开记录，不改标签/字节、不将假 native 称为真实宿主通过

- [X] T029 [P] [US1] 在 T024—T028、T077 后按相对路径+字节只读重算并验证 T003 的 `fixture-schema.json`、`cases.jsonl`、`labels.json` 与 `FROZEN.md` 所记 tree digest 完全一致；摘要不包含 `FROZEN.md` 自身、此次原生基线结果或后续 runtime fixture。随后在不改变、重标或补录冻结集的前提下测量当前原生策略询问基线、记录标签依据和结果；冻结集必须已有有效用户 ID 却漏管道 effect、伪造/越界/非 UTF-8 边界引文、scopeDigest 错对象/参数/cwd、未提供更晚限制、旧 generation、model low 写入受风险下限阻止，以及否定、只读限制、路径范围、例外、撤销、指代等自然语言标签。若冻结身份漂移或覆盖不足则失败并回到任务决策，不得用已见实现结果修补覆盖；fake 只验流程，不能据此宣称宿主独立证明授权语义，结果写入 `docs/acceptance/omp-permission-control.md`
- [X] T030 [US1] 在 T028、T029 后扩展 Python harness 调用真实 patched 纯函数和 Bun 测试，注入 fake Settings/UI/provider/execute 与网络、mkdir、direnv、service/job、backend、secret 哨兵，写入 `tests/test_omp_permission_control.py`
- [X] T031 [US1] 在 T024—T030 后运行 US1 隔离组，预期禁止/必须人工误放行 0、compound 全效果匹配 100%、批准前执行 0、批准后恰一次且字节一致、有效 allow 无重复 UI，命令与结果写入 `docs/acceptance/omp-permission-control.md`
- [X] T032 [US1] 在 T031 后记录 MVP 工程增量边界：US1 只证明隔离规则、prepared plan 与 permit 时序，真实可用仍依赖 US2 会话控制、US3 主审/fallback、US4 真实运行包交付和 US5 审计证据，不得把 fake 模型或源码测试称为宿主可用，写入 `specs/004-omp-permission-control/quickstart.md`

**Checkpoint**: 运行完整 `.venv/bin/python -m pytest -q tests/test_omp_permission_control.py`，并用 T004 独立 build-inputs lock 已校验的 Bun 运行 US1 tests；有 receipt 时仅追加交叉核验。预期测试 collected 数大于 0，SC-002/003 的隔离安全路径和 FR-004—013/034 有证据，真实模型质量与宿主加载仍为尚未执行。

---

## Phase 4: User Story 2 - 显式控制并理解会话模式 (Priority: P1)

**Goal**: 只提供四个完整命令，模式切换仅作用当前会话并立刻撤销旧许可，status/explain 如实显示实际状态。

**Independent Test**: 模拟新建、恢复、reviewing、awaiting-human、permitted 和无决定会话，调用四命令及非法参数，验证状态、generation、abort、来源链和零模型调用边界。

### Tests for User Story 2

- [X] T033 [P] [US2] 在 T019 后先编写会失败的命令契约测试：仅 `/permission-control smart|manual|status|explain`，大小写敏感；缺参/多参/未知命令不改状态并只列四条用法；manual、status、explain 模型调用均为 0；status/explain 不改变 mode/generation/permit/pending、不创建或延长许可；新建/恢复不继承临时模式，写入 `agents/omp/packages/omp-permission-control/tests/session-commands.test.ts`
- [X] T034 [US2] 在 T023、T033 后先编写会失败的会话并发测试：smart/manual 经独立控制路径先原子递增 generation、撤销 permit、abort 在途请求再更新模式，不等待 Bash 串行锁；重复设置也递增；status/explain 在审查中读取一致快照但不延长 deadline，写入 `agents/omp/packages/omp-permission-control/tests/session-state.test.ts`

### Implementation for User Story 2

- [X] T035 [US2] 在 T033 后注册且仅注册四命令及严格参数错误，用固定模板输出且命令本身不执行 Bash、不创建许可，写入 `agents/omp/packages/omp-permission-control/index.ts`
- [X] T036 [US2] 在 T027、T034 后扩展 `SessionPermissionState`：`session_id` 宿主会话唯一、`generation` 单调、`configured_mode/active_mode=smart|manual`、`mode_source=profile-default|session-command`、reviewer selection 为 session-default 或显式、`fallback_state=disabled|ready|unavailable|unhealthy`、`bridge_health=healthy|degraded|unavailable`、coverage 列 Linux 主会话 Bash 前台 native 及 manual-required 原因、`last_decision_id/pending_permit_id` 可选且最多一个 pending；新建/恢复从 configured 初始化，写入 `agents/omp/packages/omp-permission-control/controller.ts`
  **约束原文（T036 必须逐字段实现）：**

  | 实体.字段 | 类型 | 说明 |
  |---|---|---|
  | `SessionPermissionState.session_id` | 宿主会话 ID | 不与其它会话共享许可 |
  | `SessionPermissionState.generation` | 单调整数 | 保护基线变化时递增 |
  | `SessionPermissionState.configured_mode` | `smart \| manual` | 来自 profile 的期望值 |
  | `SessionPermissionState.active_mode` | `smart \| manual` | 当前会话切换后的值 |
  | `SessionPermissionState.mode_source` | `profile-default \| session-command` | 状态解释来源 |
  | `SessionPermissionState.reviewer_selection` | 模型选择 | `session-default` 或显式模型 |
  | `SessionPermissionState.fallback_state` | 枚举 | `disabled \| ready \| unavailable \| unhealthy` |
  | `SessionPermissionState.bridge_health` | 枚举 | `healthy \| degraded \| unavailable` |
  | `SessionPermissionState.coverage` | 结构化状态 | 首版候选范围及当前实际覆盖：Linux 主会话 Bash、前台 native backend，并列出使请求转人工的限制原因 |
  | `SessionPermissionState.last_decision_id` | 可选请求 ID | 供 `explain` 查找；不构成许可 |
  | `SessionPermissionState.pending_permit_id` | 可选许可 ID | 串行受管 Bash 路径最多一个 |
- [X] T037 [US2] 在 T035、T036 后为 patched 宿主接入独立控制/取消路径与 minimal `/permissionControl` shim：插件不健康时 status/explain 报 unavailable、smart 不生效、manual 仍收紧；取消 1 秒内使请求不可执行，写入 `agents/omp/patches/permission-control/0001-host-bridge.patch`
- [X] T038 [US2] 在 T035—T037 后实现只读且 model calls=0 的 status/explain：status 固定字段 configured/active mode、mode source、reviewer/source、fallback/health、`fallbackLimit="ask-or-deny-only; installed-only; never-allow"`、coverage/execution limits/native protection、`childAndHeadless="native-prompt-or-block; no-smart-permit-inheritance; no-yolo"`、bridge、policyVersion、pending、unverified；explain 显示关联 ID、结果、固定来源/短原因、ask→human 链和 permit 状态且无原命令/模型自由文本，不改变 mode/generation/permit/pending 或延长许可，写入 `agents/omp/packages/omp-permission-control/index.ts`
- [X] T039 [US2] 在 T033—T038 后运行 session tests，预期过期许可复用 0、临时模式跨会话继承 0、取消 ≤1 秒、100% status 一次响应字段齐全、无决定返回 `no-decision-in-session`，证据写入 `docs/acceptance/omp-permission-control.md`

**Checkpoint**: 用 T004 独立 build-inputs lock 已校验的 Bun 运行 `session-commands.test.ts` 与 `session-state.test.ts`；有 receipt 时仅追加交叉核验。预期 collected 数大于 0，FR-001—003/010—013/021—022/026 和 SC-004/007/008 的隔离场景通过。

---

## Phase 5: User Story 3 - 选择独立主审模型并安全降级 (Priority: P1)

**Goal**: 冻结显式或会话主审身份，单次有界调用；只有指定故障可进入 installed-only tiny，tiny 永远不能 allow。

**Independent Test**: 用假 transport/registry/clock 覆盖显式与默认选择、缺模型、切换、超时、服务失败、严格 JSON 无效、deny/ask、tiny 缺失/失败/返回 allow 和迟到结果。

### Tests for User Story 3

- [X] T040 [P] [US3] 在 T019 后先编写会失败的模型选择/transport 测试，覆盖显式已选择模型、审查开始冻结 session 主模型、无主模型、无效/歧义显式引用、认证只留宿主边界、无 SDK retry/fallback/candidate pool/工具调用且每请求主审最多一次，写入 `agents/omp/packages/omp-permission-control/tests/model-selection.test.ts`
- [X] T041 [P] [US3] 在 T019 后先编写会失败的 tiny 契约测试：仅主审 `timeout|service-failure|invalid-output` 可创建；主审 ask/deny、hard rule、取消、配置错误或不支持 transport 不创建；输入 ≤8 KiB、输出 ≤128 tokens 且 ≤1 KiB，顶层恰为 `decision`/`reasonCode`，decision 仅 `ask|deny`，reasonCode 只允许 `FALLBACK_HUMAN_REQUIRED|FALLBACK_MATERIAL_RISK|FALLBACK_UNKNOWN_EFFECT|FALLBACK_INCOMPLETE_CONTEXT`，allow/额外字段/重复 key/自由文本均失败为 ask，写入 `agents/omp/packages/omp-permission-control/tests/fallback.test.ts`
- [X] T042 [US3] 在 T040、T041 后先编写会失败的 deadline 测试：自动 30 秒从构造上下文起含预处理/资源检查/模型等待，排队和人工等待不计；主审最多 25 秒，tiny 仅余量且最多 5 秒；取消/超时/旧 generation 的迟到响应不得写许可或触发执行，写入 `agents/omp/packages/omp-permission-control/tests/deadline.test.ts`

### Implementation for User Story 3

- [X] T043 [US3] 在 T026、T040、T042 后实现插件侧无工具、无重试的主审信封构造、`services.reviewOnce` 调用和严格 JSON 解码；插件不接收凭据、不直接实例化 SDK/transport，固定 provider/model/source/输入摘要并拒绝重复 key 与不精确 effect/message ID，invalid-output 不尝试修复，写入 `agents/omp/packages/omp-permission-control/reviewer.ts`
- [X] T044 [US3] 在 T036、T040、T043 后实现 reviewer 解析与变化失效：显式来源 `explicit-profile`，省略时审查开始冻结 `session-default`，不可解析为 `unavailable` 并人工/阻止；模型、策略或认证有效性变化递增 generation，凭据不进入配置/状态/审计/错误，写入 `agents/omp/packages/omp-permission-control/controller.ts`
- [X] T045 [US3] 在 T040—T044 后向同一 patch series 添加宿主服务 `registerPermissionController`、`reviewOnce`、`tinyInstalledOnly`：凭据仅在宿主认证边界解析，首批只支持 `anthropic-messages|openai-completions`，其它 transport 标 unsupported 转人工；对 SDK/fetch/retry/fallback 的推理请求总计数最多为 1，认证刷新独立计数且不得重发推理；tiny 使用独立 installed-only worker，只接受完整安装的 `local/lfm2.5-230m`，不接管标题 worker且不下载/安装/升级；更新 series，并让 `bridge.integration.test.ts` 直接调用真实 tiny 加载函数验证网络/安装/标题 worker 哨兵为 0，写入 `agents/omp/patches/permission-control/0002-installed-only-tiny.patch` 与 `agents/omp/patches/permission-control/series`
- [X] T046 [US3] 在 T041—T045 后接入 tiny 单次限权合成，主审 deny/ask 不复审，tiny 任何 allow 或非法输出按 failure→ask，且 status/audit 的实际模型与来源一致，写入 `agents/omp/packages/omp-permission-control/reviewer.ts`
- [X] T047 [US3] 在 T040—T046 后先把完整有序 patch series 干净应用到 T004 锁定的上游源码，再运行模型选择/fallback/deadline 隔离组，并运行 `agents/omp/patches/permission-control/tests/bridge.integration.test.ts` 直接调用 patched wrapper、`prepareBashExecution`、`commitPreparedBashExecution` 和 T045 的真实 tiny installed-only 加载函数；预期每请求主审 ≤1、合条件 tiny ≤1、tiny 越权/隐式下载/安装/接管标题 worker/无 UI 自动批准均为 0、自动等待 ≤30 秒，且完整 series 的源码身份与测试输入记录到 `docs/acceptance/omp-permission-control.md`

**Checkpoint**: 用 T004 独立 build-inputs lock 已校验的 Bun 运行 `model-selection.test.ts`、`fallback.test.ts`、`deadline.test.ts`；有 receipt 时仅追加交叉核验。预期 collected 数大于 0，FR-014—020/025—026 和 SC-005—007 隔离场景通过，真实模型质量仍为尚未执行。

---

## Phase 6: User Story 4 - 受管交付且故障时保持保护 (Priority: P2)

**Goal**: 以独立 patched standalone 锁、内容寻址 cache、现有部署事务和 omp-kernel 显式选择交付；缺失、损坏、回滚时保留原生保护。

**Independent Test**: 合成 profile、插件树、artifact cache、receipt 和临时 OMP home，执行 validate/render/lock/sync/plan/apply/discovery/run 前置检查/rollback；不启动真实宿主，不修改其它 profile 或账号数据。

### Tests for User Story 4

- [X] T048 [P] [US4] 在 T017 后先编写会失败的 runtime 锁契约测试，覆盖 manifest 精确字段/identity、自身排除哈希、有序 patch path+SHA、receipt 交叉摘要、Linux glibc x64 asset、cacheKey 路径/链接边界、actual sha/size、ABI/plugin digest/runtime identity；结构错 2、缺平台/不兼容 5，写入 `tests/test_omp_permission_runtime.py`
- [X] T049 [P] [US4] 在 T017 后先编写会失败的依赖生命周期测试，覆盖 official 不要求补丁锁、permission-control-v1 只从 profile OMP cache 同摘要资产消费、不搜索全局目录/联网回退/编译/安装 tiny，且 Bun/Rust installer、build subprocess、network/download 哨兵均为 0；stage 成功后才激活并沿用运行包租约，写入 `tests/test_omp_dependencies.py`
- [X] T050 [US4] 在 T048、T049 后先编写会失败的交付事务测试，覆盖插件 missing/damaged/not-loaded/identity-mismatch/unhealthy、ABI/asset 错、字段所有权冲突 4、pending 恢复、失败回滚、成功 rollback 消费备份、未选择插件 profile 官方行为不变及非受管配置/认证/会话哨兵不变，写入 `tests/test_omp_kernel.py`

### Implementation for User Story 4

- [X] T051 [P] [US4] 在 T010、T048 后完成 runtime schema 对 build receipt 的完整工具链版本/摘要、依赖来源、upstream identity、build script digest、platform、asset SHA/size 和 ABI 的必填约束，写入 `schemas/omp-permission-runtime.schema.json`
- [X] T052 [US4] 在 T017、T048、T051 后完成 lock/receipt/asset/plugin tree 校验、combined identity 计算（官方锁+补丁锁+平台+实际插件树，位于 manifest 外）和固定错误映射，写入 `src/agentcfg/omp_permission_runtime.py`
- [X] T053 [US4] 在 T049、T052 后实现 runtime variant 选择、内容寻址 cache 复制、stage/验证/激活、租约与 receipt；permission-control 缺资产不回退 official smart，写入 `src/agentcfg/omp_dependencies.py`
- [X] T054 [US4] 在 T052 后新增严格 CLI `agentcfg lock --agent omp --runtime-variant permission-control-v1 --artifact-cache <prepared>`，只消费已有有效构建材料并更新独立锁；普通 official lock、apply、run 语义不变，run 不允许覆盖身份，写入 `src/agentcfg/cli.py`
- [X] T055 [US4] 在 T011—T013、T050、T052—T054 后由单一写入者实现 `/permissionControl` 确定性渲染、精确字段所有权/三方比较、capture allowlist、plugin/runtime/ABI/保护基线启动检查、discovery 健康与 rollback 删除受管对象但保留非受管数据，写入 `src/agentcfg/omp.py`
- [X] T056 [P] [US4] 在 T012、T052 后更新插件选择与发现清单：未选 profile 不加载/不生成对象，选择后核验入口和 tree digest，写入 `agents/omp/discovery-manifest.json`
- [X] T057 [US4] 在 T011、T012、T055、T056 后配置 `omp-kernel` 选择插件、`runtime_variant="permission-control-v1"`、`default_mode="smart"`、省略 reviewer、fallback=`local/lfm2.5-230m`，并保持 bash/task/eval prompt、禁止 yolo；同步虚构本地示例和 kernel reference 的期望原生对象/发现结果，写入 `profiles/omp-kernel.toml`、`examples/omp-kernel.local.toml` 与 `tests/fixtures/omp/kernel-reference.json`
- [X] T058 [US4] 在 T051—T057 后生成仅供隔离测试的合成 patched manifest/receipt/artifact cache fixture，摘要必须由 fixture 实际字节计算、不得写入正式 recipe lock 或冒充发布资产，写入 `tests/fixtures/omp/permission-control/runtime/manifest.json`
- [X] T059 [US4] 在 T050、T052—T058 后扩展合成端到端测试依次 validate→render→lock→sync→plan→apply→fake discovery/run preflight→握手/Bash 判定→rollback，核对 cache 租约、pending 恢复、上一版备份和其它 profile 隔离，并断言 sync/apply/run 前置检查期间 Bun/Rust installer、build subprocess、network/download 哨兵均为 0，写入 `tests/test_omp_permission_runtime.py`
- [X] T060 [US4] 在 T048—T059 后只运行使用临时仓库目录、按 fixture 实际字节重算合成锁的 `.venv/bin/python -m pytest -q tests/test_omp_permission_runtime.py`，预期合成交付故障全放行残留 0、非受管哨兵变化 0，且不读取尚未更新的正式 recipe identity；此处只证明资产消费与事务逻辑，现有 OMP 全回归留给 T070 正式锁后的 T071，证据写入 `docs/acceptance/omp-permission-control.md`

**Checkpoint**: Python 交付组必须通过，但这里只使用合成资产验证消费与事务。源码测试或 fake discovery 不能替代实际 patched standalone 身份；正式交付声明依赖所有代码稳定后的 T070，缺构建环境只把早期/最终构建与正式锁组标环境不足，不伪造通过。

---

## Phase 7: User Story 5 - 查看脱敏审计与真实支持范围 (Priority: P2)

**Goal**: 为每次决定追加会话隔离的最小脱敏记录，并严格区分隔离测试、真实模型质量、宿主 smoke 和平台证据。

**Independent Test**: 以秘密哨兵、长对话、人工来源链、模式切换和平台标签生成 allow/ask/deny，验证审计字段齐全、正文与凭据零出现、status/explain 一致及证据状态不夸大。

### Tests for User Story 5

- [X] T061 [P] [US5] 在 T019 后先编写会失败的审计/秘密测试，覆盖 args/env/授权/provider error/model output 中哨兵在配置、外发请求非必要字段、新增审计、status、explain、异常和摘要出现数为 0；脱敏损失语义最多 ask，写入 `agents/omp/packages/omp-permission-control/tests/audit.test.ts`
- [X] T062 [P] [US5] 在 T029、T030 后先编写会失败的指标报告测试，固定计算 safe 免询问率、危险样本误 allow、compound 整体率、过期 permit、tiny 越权/下载、deadline/取消、status 完整率、secret 泄露和交付残留，并拒绝把 fake 结果、宿主退出 0 或有限样本零误放行表述为普遍保证，写入 `tests/test_omp_permission_control.py`

### Implementation for User Story 5

- [X] T063 [US5] 在 T027、T061 后实现 `RedactedAuditRecord` 必含 schema version、request/decision ID、会话盐 operation digest、outcome/source/reason code、active mode、policy version、actual reviewer/source 或 `not-called`、fallback 配置/是否调用、coverage、bridge/model/tiny health、调用次数、耗时桶和 permit 最终状态；人工时另含 human decision ID、`source=human`、allow/deny、上游 ask ID；可含已验证消息 ID，禁止原始/可逆 command、完整 argv、秘密 cwd/env、凭据、完整对话、模型自由文本/provider 正文/异常原文/未脱敏工具文件输出，写入 `agents/omp/packages/omp-permission-control/audit.ts`
- [X] T064 [US5] 在 T038、T063 后让 status/explain 和审计从同一固定枚举快照生成；审计写失败将 health 标 degraded，绝不把 ask/deny 放宽或把审计用于恢复 mode/permit/pending，写入 `agents/omp/packages/omp-permission-control/index.ts`
- [X] T065 [US5] 在 T029、T062—T064 后实现可执行评测入口：默认 fake 模式消费冻结 `cases.jsonl`、只审查而绝不执行命令并生成隔离报告；真实模式必须显式选择授权后的主审服务/模型且禁止 retry/fallback 链，报告 model/provider/transport、策略/样本/插件/宿主摘要、平台、结果和未覆盖项；SC-001 至少 80% 只在对应真实模型评测计算，SC-002 的 0 误 allow 只限定固定样本，写入 `agents/omp/packages/omp-permission-control/evaluation/run.ts`
- [X] T066 [US5] 在 T061—T065 后运行审计/secret/metrics 隔离组，预期 reviewer/status/audit 实际模型来源一致 100%、秘密哨兵 0、脱敏损失自动 allow 0、每个决定均可关联且不含正文，证据写入 `docs/acceptance/omp-permission-control.md`
- [X] T067 [US5] 在 T060、T066 后更新支持矩阵，只声明首版候选范围为 Linux glibc x64 主会话 Bash 前台 native backend；非 Bash、eval/MCP/task/child/子代理、service/async/PTY/ACP、direnv/devenv/prefix/未知启动脚本与 WSL/macOS/Windows 保留原生保护或人工并标未验证，不宣称 OS 沙箱，写入 `docs/acceptance-matrix.md`

**Checkpoint**: 用 T004 独立 build-inputs lock 已校验的 Bun 运行 `audit.test.ts`（有 receipt 时仅追加交叉核验），并运行完整 `.venv/bin/python -m pytest -q tests/test_omp_permission_control.py`；预期两组 collected 数均大于 0，FR-023—024/029—033 和 SC-001—003/006/008—011 均有明确隔离证据或未执行分类。

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 完成跨故事回归、文档、证据边界及未来授权步骤，不扩大本轮宿主或账号副作用。

- [X] T068 [P] 在 T060 后更新 OMP 配置、独立 runtime lock、离线 build、sync/apply/run/rollback、退出码 2/4/5 和故障关闭说明，明确日常命令不编译、不下载 tiny，sync/apply 不启动宿主，而 run 只显式启动已部署且身份核验通过的宿主，写入 `docs/omp-dependencies.md`
- [X] T069 [P] 在 T067 后更新架构与适配器文档，说明本地 TS 扩展 + OMP v18.3.0 bridge、prepare/commit、会话串行与 out-of-band cancel、覆盖边界及其它 profile official 路径不变，写入 `docs/architecture.md`
- [X] T070 在 T031、T039、T047、T060、T066、T068—T069 后按固定顺序完成最终锁定：(1) 确认 US1/US2/US3/US5、文档、插件、完整 patch series、build-inputs lock 与所有 recipe/package/resource 输入字节稳定；(2) 先据这些稳定字节更新 `locks/omp/manifest.json` 中实际受锁管理的 official recipe/package/resource 摘要和 official recipe identity（包括插件 catalog、发现清单及 kernel 配方），不凭空增加不受支持项并保持 official upstream/assets 来源语义；(3) 只依据该已更新 official recipe identity 及 T004 独立构建输入执行显式离线构建，核对 actual patched standalone、plugin tree、静态 ABI、asset SHA/size 与完整 toolchain/dependency receipt；(4) 据实际产出生成并交叉校验 `locks/omp/permission-control/build-receipt.json` 和正式 `locks/omp/permission-control/manifest.json`；(5) 最后以 official lock identity、patched lock identity、platform 和实际 plugin tree 计算 manifest 外的 combined runtime identity，并核对 `tests/fixtures/omp/kernel-reference.json`。build-inputs 仍只引用原始上游源、工具与依赖，不得引用 official recipe identity、receipt、补丁锁或构建输出；步骤 (2) 后任何受锁输入字节变化都必须废弃后续产物并从该步重新生成，禁止手改摘要。全程不执行 OMP CLI/`--version`/宿主握手；缺准备环境时本任务保持未完成并登记环境不足，禁止沿用 T018 早期摘要或合成 T058 fixture，真实 ABI 握手只归 T072
- [X] T071 在 T068—T070 后运行相关回归 `.venv/bin/python -m pytest -q tests/test_omp_adapter.py tests/test_omp_dependencies.py tests/test_omp_kernel.py tests/test_runtime.py tests/test_dsh_pipeline.py tests/test_pi_pipeline.py`，并运行两个新增 Python suite harness 及构建输入契约组 `.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_runtime.py tests/test_omp_permission_build_inputs.py`；使用 T004 锁定的 Bun/输入把最终完整 patch series 干净应用到其锁定上游源码，运行完整 bridge TypeScript 组（至少含 foundation、bridge integration、policy、permit、session、model-selection、fallback、deadline、audit），其中 `bridge.integration.test.ts` 必须调用最终 patched wrapper/prepare/commit 与 installed-only 真实函数。全部测试先核对最终源码、patch series、build-inputs、official/patched lock、receipt、plugin tree 与 combined runtime identity 一致，再按 `specs/004-omp-permission-control/quickstart.md` 检查链接、schema 示例、冻结 fixture 数量/labels/tree digest、需求映射和 `git diff --check`；仅在新失败证据揭示系统性问题时扩大范围，结果与未执行组写入 `docs/acceptance/omp-permission-control.md`
- [X] T072 在 T070—T071 后、获得真实宿主运行的独立明确授权时，按 `specs/004-omp-permission-control/quickstart.md` 在隔离临时实例执行 actual patched OMP smoke：先核对 identity/status，再测 manual/smart/explain/new/resume/missing-plugin、一个无害 allow 无重复 prompt、故障关闭和回滚；未获授权时保持本任务未勾并记“尚未执行”，不能记环境不足或以 fake discovery/宿主退出 0代替，报告写入 `docs/acceptance/omp-permission-control-host-smoke.md`
- [X] T073 在 T065、T070—T071 后、获得真实模型调用与成本的独立明确授权时，用 `agents/omp/packages/omp-permission-control/evaluation/run.ts` 对冻结样本只做审查不执行命令，固定主审 identity、禁止 retry/fallback 链；真实评测必须单独统计逐 effect 授权语义，覆盖否定、只读限制、路径范围、例外、后续撤销/限制和指代，以及固定风险下限样本，记录 SC-001/SC-002 与版本/平台/样本/environment。有限冻结集结果不得外推为任意自然语言保证；未获授权时保持本任务未勾并记“尚未执行”，不能用 fake 成绩、严格 JSON/机械 binding 通过或无账号 smoke 代替，报告写入 `docs/acceptance/omp-permission-control-model-evaluation.md`

**Checkpoint**: 默认隔离回归、文档和静态检查完成；T072 与 T073 是两个实际验收任务，分别只有未来获得对应授权并实际执行后才能勾选和改变“尚未执行”状态。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 先行；T002—T005 在 T001 后可按标记并行。
- **Foundational (Phase 2)**: 依赖 Setup。T006—T008 先写失败测试；T009—T017 按任务内 ID 依赖实现；T019 是故事逻辑门槛。T018 是尽早执行的真实构建边界证据，环境不足时不阻塞 T020—T069，但正式可交付声明仍依赖 T070 实际成功。
- **US1 (Phase 3)**: 依赖 T019；T020—T023 先写失败测试，再执行 T024—T032。
- **US2 (Phase 4)**: 依赖 T019、T023、T027；不依赖 US1 的真实模型结果，可与 US3 的不同文件测试并行，但 `controller.ts`、`index.ts` 和 patch 更新按 ID 串行。
- **US3 (Phase 5)**: 依赖 T019、T026、T036；不依赖真实模型或真实宿主，测试全部使用假 transport/clock。
- **US4 (Phase 6)**: 合成交付逻辑依赖 T017，T058—T060 只证明合成资产消费和事务，不生成正式 recipe lock。正式构建与锁在所有 US5 插件字节稳定后的 T070 执行，避免插件摘要立即漂移。
- **US5 (Phase 7)**: 审计逻辑依赖 T027/T038，样本指标依赖 T029；支持矩阵依赖交付和审计证据 T060/T066。
- **Polish (Phase 8)**: T070 依赖全部源码稳定；T072/T073 分别依赖未来真实宿主/真实模型授权，未授权时保持未完成且不阻塞默认隔离工作状态的如实报告。

### User Story Dependencies

```text
Setup T001-T005
  └─ Foundation interface gate T006-T017,T019
       ├─ US1 T020-T032 (isolated engineering MVP)
       ├─ US2 T033-T039
       ├─ US3 T040-T047
       ├─ US5 audit core T061-T066
       └─ US4 logic T048-T057,T059
Early build-boundary evidence T018 ───┘
US4 synthetic delivery T060 + US5 stable plugin T066 ──> support matrix T067
T067-T069 ──> final real build and official/patched lock verification T070 ──> T071 ──> authorized T072/T073
```

- **US1 (P1)**: 在 foundation 后可独立证明规则/permit/执行时序，是 MVP 工程增量；它尚不具备真实模型选择、会话体验、正式运行包或审计交付，因此不得称真实可用。
- **US2 (P1)**: 使用 foundation 的状态/permit 接口；其命令与会话失效可独立用模拟会话验收。
- **US3 (P1)**: 使用 foundation 的 reviewer/bridge 接口；其选择、预算和 tiny 上限可独立用假 transport 验收。
- **US4 (P2)**: 可先用合成资产完成管理器逻辑；正式 kernel 交付必须有代码稳定后 T070 的真实 patched asset、receipt、plugin digest 和 patched/official recipe lock 核验。
- **US5 (P2)**: 审计与指标可用隔离输入独立验收；真实质量/宿主/平台结论仍依赖未来授权证据。

### Parallel Opportunities

- T002/T003/T004/T005 在 T001 后写不同文件，可并行。
- T006/T007/T008 写 Python、扩展 TS、补丁 TS 三个不同测试文件，可并行。
- T010/T012/T016 在各自前置完成后写不同文件，可并行；T013→T014→T015 的 series/patch 流程串行。
- 每个故事标 `[P]` 的测试在 foundation gate 后写不同文件，可并行；同一 `controller.ts`、`index.ts`、`reviewer.ts`、patch 或 `omp.py` 的任务严格按 ID 串行。
- T048/T049 在 T017 后可并行；T051/T056 在其各自前置完成后写不同文件可并行。
- T061/T062 写 TS 与 Python 测试，可并行；T068/T069 写不同文档，可并行。

## Parallel Examples by User Story

### User Story 1

```text
完成 T019 后并行：T020 policy tests、T021 reviewer contract tests、T023 permit tests
完成对应测试后并行：T024 shell-analysis.ts、T025 policy.ts
随后串行：T026 reviewer.ts → T027 controller.ts → T028 host patch → T030 harness → T031 checkpoint
```

### User Story 2

```text
完成 T019/T023 后：T033 command tests → T034 state tests；它们可与 US1/US3 的不同文件任务跨故事并行
实现串行：T035 index.ts → T036 controller.ts → T037 host patch → T038 index.ts → T039 checkpoint
```

### User Story 3

```text
完成 T019 后并行：T040 model-selection tests、T041 fallback tests
随后：T042 deadline tests → T043 reviewer transport → T044 controller selection → T045 tiny patch → T046 reviewer synthesis
```

### User Story 4

```text
完成 T017 后并行：T048 runtime lock tests、T049 dependency tests
实现中可在前置满足后并行：T051 runtime schema、T056 discovery manifest
合成交付串行：T052 runtime validator → T053 dependencies/T054 CLI → T055 omp.py → T057 kernel → T058 synthetic fixture → T059/T060；正式 build/locks 等 US5 后执行 T070
```

### User Story 5

```text
完成各自前置后并行：T061 audit tests、T062 metrics tests
随后串行：T063 audit.ts → T064 index.ts → T065 report → T066 checkpoint → T067 matrix
```

## Requirements & Success Criteria Mapping

| Requirement | Tasks |
|---|---|
| FR-001—003 | T006, T033—T039, T057 |
| FR-004—009 | T008, T020—T022, T024—T030 |
| FR-010—013 | T023, T027—T028, T034—T037 |
| FR-014—020 | T006, T021, T040—T047 |
| FR-021—024 | T033—T039, T061—T066 |
| FR-025—026 | T026, T040—T047 |
| FR-027—028 | T010—T018, T048—T060 |
| FR-029—031 | T020, T024, T050, T055—T057, T067, T069 |
| FR-032—033 | T001, T005, T019, T029—T032, T060—T073 |
| FR-034 | T008, T014—T015, T022—T023, T027—T031 |
| SC-001—003 | T003, T020—T025, T029—T031, T062, T065—T066 |
| SC-004 | T023, T033—T039 |
| SC-005—007 | T040—T047 |
| SC-008 | T033—T039, T064—T066 |
| SC-009 | T026, T061—T066 |
| SC-010 | T048—T060 |
| SC-011 | T005, T019, T031, T039, T047, T060, T065—T073 |

## Implementation Strategy

### MVP First: Isolated Engineering Increment

1. 完成 T001—T017 与可执行的 T019；T018 尽早尝试并如实分类。
2. 完成 T020—T032，证明 US1 的隔离工程增量。
3. 停止并运行 US1 checkpoint；只报告规则、permit 和真实 patched 函数的隔离证据。
4. 不把该 MVP 称为真实可用；真实可用还需 US2/US3、US5 审计、T070 的最终交付身份以及未来经授权 smoke/评测。

### Incremental Delivery

1. Foundation → 严格配置、bridge 与离线构建契约。
2. US1 → 完整副作用和一次性许可。
3. US2 → 会话命令、状态与即时失效。
4. US3 → 主审选择、预算与 installed-only tiny。
5. US4 → 先用合成资产验证锁契约、cache、部署/回滚、discovery 和 kernel；真实 build/locks 在 US5 后由 T070 生成，资产不足时不宣布交付。
6. US5 → 脱敏审计、指标与支持矩阵。
7. Polish → 最终真实构建/recipe locks、回归与文档；真实宿主 T072 和真实模型 T073 仅在未来分别授权后执行。

## Notes

- `[P]` 只表示前置完成后可因文件独立并行，不允许两个写入者同时修改同一 patch series、`index.ts`、`controller.ts`、`reviewer.ts` 或 `src/agentcfg/omp.py`。
- 测试任务必须先确认因缺少目标行为而失败，再实现；不得通过放宽断言、关闭网络/秘密/原生保护哨兵来获取通过。
- 真实构建成功不等于宿主 smoke；fake 模型通过不等于真实模型质量；宿主退出 0 不等于功能通过。
- 工具链、真实资产或平台确实缺失时只标对应组“环境不足未验证”；尚未获真实宿主/模型授权时标“尚未执行”。
- 每个 checkpoint 保存实际命令、环境、结果、范围和未覆盖项；未执行检查不得声称通过。

## 初次任务生成记录（2026-09-29，历史记录）

以下内容仅保留初次生成时的任务统计与当时声称的检查范围，不表示后续修订轮次重新运行过这些检查；每轮实际证据应写入对应验收记录。

| 状态 | 初次生成结果 |
|---|---|
| 完成 | 初次生成了任务，并在当时记录需求覆盖、数据字段、格式和依赖检查；该历史状态不作为本轮复核证据 |
| 进行中 | 无；T001—T073 的实现与运行验收尚未开始，全部保持未勾选 |
| 失败待决策 | 无未解决的任务拆分问题 |
| 环境不足未验证 | 未尝试构建/宿主/模型，不据此判断环境不足；这些执行项均为尚未执行 |

历史任务统计为 73 项任务、8 阶段，US1/US2/US3/US4/US5 分别为 13/7/8/13/7 项，其余共享任务 25 项；27 项有条件可并行。初次生成记录声称当时核对了未勾选 checkbox、连续 ID、故事标签、路径、显式前置、字段原文与 FR/SC 映射，并运行过仓库 `.venv/bin/python` 静态检查与 `git diff --check`；未执行 pytest、Bun 测试、构建或真实调用。后续修订不得引用这段历史文字冒充当轮检查通过。

多模型分工：`gpt-5.6-sol / medium` executor 起草与修订，复用 scout 做只读覆盖核对，主代理决定依赖取舍并做最终验收。

## 本轮文档修复记录（2026-09-29）

| 状态 | 本轮结果 |
|---|---|
| 完成 | 仅修订 `tasks.md`、`quickstart.md`、`contracts/host-bridge.md`，闭合六项文档问题：U2 构建输入、C1 完整 patch series、I2 冻结样本、I3 最终身份顺序、授权职责/逐 effect 证据、最终验收与历史证据边界；未实现插件且未勾选任何 T001—T073 任务。executor 本地静态检查确认 73 个连续且未勾选的任务 ID、无重复 ID或错误前置、本组三文件本地链接无断链、无尾空白且 `git diff --check` 无输出；主代理另报告 203 条显式前置边无前向/环、全规格 29 个本地链接通过、34 项 FR 与 11 项 SC 映射覆盖。 |
| 进行中 | 无 |
| 失败待决策 | 无 |
| 环境不足未验证 | 本轮未执行 pytest、Bun 测试、构建、宿主或模型检查，不据此判断环境不足；这些运行项仍为“尚未执行” |

本轮实际执行模型：`gpt-5.6-sol / medium` executor；主代理负责最终只读验收。

## 本轮实施记录（2026-09-29，持续更新）

| 状态 | 实施结果 |
|---|---|
| 完成 | 以任务 checkbox 为准：当前76/77完成；T039/T070/T071真实缺陷修复后重建及103项最终回归通过，T072最终真实宿主限定验收通过，详见真实宿主报告 |
| 进行中 | 无进行中的已授权步骤；T072以真实宿主+固定审查响应验证一次许可/执行，3次外部模型额度已用完 |
| 失败待决策 | 无待用户决策；早期generic adapter及简化cleanup版本均已被真实执行器复用修订替代并通过基础验收 |
| 环境不足未验证 | 无当前环境缺口；T018早期standalone已实际构建并校验，未启动产物 |
| 尚未执行 | T073 完整真实模型评测仍待独立授权；T072 已开始，不再属于未执行 |

执行分工：早期主代理实现Python构建校验，executor修订实现、scout收集接口证据；本轮两名gpt-5.6-sol / medium executor负责补丁回归和文档，主代理负责最终验收。真实宿主与3次main模型请求已获授权并执行，固定响应许可不代表真实reviewer质量；日常本机OMP配置未修改。

## 实施扩展追踪（2026-09-29）

用户已明确选择优先兼容现有 kernel。T074—T077 是新增实施范围，不改变历史73项生成记录；当前任务总数77。FR-035—037/SC-012 映射至 T075—T077，最终 T070/T071 必须包含这组最终补丁；T072 仍需独立真实宿主授权。原16项文档 checklist 是扩展前的历史检查，不声称已经由 reviewer 重新评估新范围。


## 最终真实宿主复验记录（2026-09-29）

T039/T070/T071重开问题现已修复并重新闭合，T072勾选依据为[真实宿主报告](../../docs/acceptance/omp-permission-control-host-smoke.md)的最终产物、审计及回滚证据；不是仅凭进程退出0。自动许可的审查响应是固定fixture，真实主模型3次已用尽，T073仍独立未执行。最终受影响回归103 passed/92.46s、bridge31/253，冻结样本240条未变。requirements checklist16/16为既有文档检查，未改其标记。


## T073 授权执行记录（2026-09-30，进行中）

用户授权固定kimi_tf/kimi-for-coding最多新增92次真实审查请求；240条冻结集经无网络预检有92个模型候选。只审查不执行，禁止重试/fallback/tiny，日常配置不改。T073保持未勾，完成依据为[模型评测报告](../../docs/acceptance/omp-permission-control-model-evaluation.md)实际出站账本及逐effect语义结果，不凭预检计数宣布成功。

## T073 实测暴露的兼容性修复（2026-09-30）

| 状态 | 内容 |
|---|---|
| 完成 | 103项材料化回归、新评测工具产物的真实宿主lifecycle；累计6次独立诊断请求，账本不重置 |
| 进行中 | T078；冻结主集尚未发送，T073仍未勾选 |
| 失败待修复 | 生产512-token上限被kimi-for-coding隐藏reasoning消耗；首批另见effects输出类型不符 |
| 环境不足未验证 | 无；临时盘不足已通过搬移本任务历史缓存解决 |

- [X] T078 根据真实诊断修正专用review传输：仅对已知支持的kimi-for-coding/openai-completions显式关闭thinking，保留512 tokens/4KiB/25秒和单次请求，未知型号不泛化；加强固定JSON输出形状说明，不放宽decoder；增加隔离回归并刷新真实构建、locks、身份及宿主lifecycle。此修复完成后继续T073冻结主集，诊断请求仍计入本轮92次总上限。

- [X] T079 真实逐字节审计发现model给出的partial quote可截词却仍机械合法。收紧allow证据为完整真实用户消息：envelope提供机器计算utf8ByteLength，binding必须startByte=0/endByte=该完整长度；prompt直接引用该长度，不再让模型计字节。保持全部effect、来源、scope及风险检查；补红绿回归、更新契约、重建交付并重跑真实评测。旧响应/诊断不能冒充最终协议的新推理；完成结果见T080与最终闭合状态。

### T078 验收闭合

专用review集成13 passed/119 assertions、插件264 passed/964 assertions、宿主与reviewer strict typecheck通过；完整材料化回归103 passed/104.47s。新0002摘要be830a4238d67d840621dc4503e342679f625f8aed3e86af1a9cdf515089f508，0001未变；最终asset6e76b95f5a03a252946e2bd81245880960a23708f6b50ce54ced266d62cb0b17/runtime c16d3c89f1bb9f03d63edb9355883d5943420b3d1b82781300898f764fa09598已真实隔离lifecycle通过。T079是后续逐字节审计发现的新问题，T073仍待最终协议完整模型评测。

### T079 修复与离线交付验收完成，模型质量仍归T073

插件269 passed/972 assertions、strict通过；两条非冻结bridge fixture更新到完整utf8ByteLength后，最终材料化103 passed/87.97s（/tmp/rotom-permission-full-evidence-final-pytest.log），冻结240条未改。最终build/receipt/locks与source身份一致，真实隔离host lifecycle、固定响应完整消息allow的permit消费/单次pwd、missing-plugin退出5及rollback通过，外部模型0。T079的完整真实模型复测部分尚未完成，暂保持未勾；T073亦未勾。当前真实账本16次，不用旧响应冒充最终协议。

### 最终T073扩额授权

用户明确新增10次额度，本轮最多102次，原16不重置。最终T079版本82次纯文字审查正在执行，预计总98；用完额度才申请，不以预估不足提前停。每日本机OMP配置未动。

## T080：真实指代歧义修复（2026-09-30）

- [X] T080 针对最终 T079 补充真实评测 coreference-004 的错误 allow，增加通用指代唯一解析与显式选择权政策；不根据 operation 反向消歧，不改变冻结样本或期望。验证受影响契约、类型、交付身份、隔离宿主与4条真实补充复测，再完成原始78次评测。

状态：进行中。真实账本20次；新增4次有明确ID，累计预计102/102（20历史+4复验+78原始）。T079错误结果保留为失败证据，不混入最终成功率。默认沙箱loopback测试被禁止，授权升级环境中relay边界9/9通过。

### T080 最终执行证据（等待语义审计收尾）

实际三组材料化151 passed/66.79s（permission_control、runtime、build_inputs；build_inputs另48项，不能误写103），完整Bun core270项在材料化中通过。reviewer定向61 passed/98 assertions、strict退出0。最新正式runtime b1566c3e211f0dbd71d1849509a7f3b10bb27651602f1ca6fc5b51bd1f7ccbe4已通过真实隔离lifecycle、固定响应单次pwd审批许可消费、missingplugin启动前退出5与rollback；外部模型0。

真实本轮102/102已用尽，relay stopped：历史20 + 最终原始78 + 最终补充4。原始冻结240的safe免询问99/100、risk危险allow0/100、fault允许0/40，SC-001/002达到门槛。最终82条模型回复79有效/3格式失败均转人工；补充4条仅3/4符合期望（明确指代002错误binding key被严格拒绝），不声称4/4。没有新增模型请求需求。逐effect授权语义独立审计在修正动态scopeDigest重算方法后收尾，不能将静态fixture scopeDigest与本次salted scopeDigest直接比较。

## T080 历史闭合状态（2026-09-30）

| 状态 | 内容 |
|---|---|
| 已完成 | T001—T080全部实施与各自授权验收已闭合；151项最终材料化、270项Bun core、strict、真实隔离host、102次计费账本及独立逐effect语义审计都有实际证据 |
| 进行中 | 无当前实施任务 |
| 失败待决策 | 无阻塞实现的问题；模型格式失败3/82均按设计转人工，安全样本1/100误询问及补充仅3/4保留为质量限制，未放宽契约或冻结标签 |
| 环境不足未验证 | 当前没有阻塞所选Linux x64交付的环境缺项；tiny真实本地推理和其它平台未验证，不计通过 |

最终99/100 safe免询问、0/100应问/拒绝误allow、0/40fault allow达到冻结范围SC-001/002；59有效allow均完成动态scope、来源、完整UTF-8及逐effect授权审计。48条compound实际主审中46有效完整effects、2格式失败，输入inventory指标不冒充模型覆盖。14条机械故障正控制及拒绝通过不收费。真实预算102/102=历史20+最终78+最终4，relay已停止；无追加模型请求需要。日常本机OMP cache/config/实例部署未修改，本机启用步骤见quickstart，资产已生成且验证。

模型分工实际执行：gpt-5.6-sol/medium负责实现、常规修复、材料化验证和文档；gpt-5.6-luna/medium负责独立日志、逐effect及冻结消息证据；主代理负责预算、政策取舍、实际模型调用和最终身份/验收。历史阶段的“未完成/待执行”文字保留为当时记录，本节和当前checkbox代表最终状态。

## Phase 9: Convergence

2026-09-30 `$speckit-converge` 对当前源码与 spec/plan/tasks 的只读核查发现以下两项未闭合边界。本节更新当前剩余工作；前文 T001—T080 的 checkbox 与历史验收字节保持原样。两项都未发现误自动放行，但分别未满足逐决定审计与即时状态准确性的要求。

- [X] T081 [US5] 修复受管 Bash 在审批审计建立前退出造成的漏记，per FR-023、US5/AC1、SC-011、T063/T064（partial，HIGH，F1）：在 `agents/omp/patches/permission-control/0001-host-bridge.patch` 的 wrapper、`permissionNativeConstraints`、`executeHostPermissionBash` 与 runner 审计接口中，保证无交互界面的 ask、等待人工时取消/抛错、初始参数 native deny 和最终参数 native deny 都生成按会话隔离、可关联且脱敏的 permission audit；不能用普通 tool error 代替，不虚构已调用模型或人工批准。人工确认前记录 ask，随后的人类结果与 permit 生命周期保持同一请求链且不重复记录同一决定；审计失败仍不得扩大许可。扩充 `agents/omp/patches/permission-control/tests/bridge.integration.test.ts` 的实际补丁路径反例：两类 native deny 各恰一条 deny 审计、模型/UI/执行调用均为 0；无 UI 与人工等待取消各保留 ask 审计、命令/job/artifact 零执行、无额外模型调用；批准后的既有审计关联、秘密哨兵与审计失败关闭行为仍通过。
- [X] T082 [US2] 修复模型与认证/provider 生命周期变化后立即查询 status 得到旧缓存的问题，per FR-021、US2/AC4、SC-006/008、T038（partial，MEDIUM，F2）：在 `agents/omp/patches/permission-control/0001-host-bridge.patch` 的 session model-changed、runtime setModel、credential generation 与 provider 注册/移除路径中，依据变更后的权威被动元数据同步 ledger 的 reviewer/来源/健康状态，并保留旧 permit 失效；`status` 本身仍仅读取快照，不增加 generation、不解析/刷新凭据、不调用模型、不探测 tiny、不产生执行或网络副作用。扩充 `agents/omp/patches/permission-control/tests/bridge.integration.test.ts`，在不执行下一条 Bash、也不先调用会刷新状态的 permissionGeneration/smart/manual 的条件下，直接断言模型切换、凭据变化及 provider 变化后的首次 status 与当前选择/可用性一致；显式 reviewer 不被会话主模型切换替换，历史决定的实际模型审计保持冻结，连续 status 查询无副作用。

**Dependencies / delivery checkpoint**: T081 与 T082 共用 `0001-host-bridge.patch`，由同一写入者顺序实施。两项修复合并后按既有 T070/T071/T072 的交付约束一次完成最终补丁干净应用、构建输入/patch/recipe 身份核验、离线重建与 lock/manifest/receipt/combined runtime 刷新；运行 `.venv/bin/python -m pytest -q tests/test_omp_permission_control.py tests/test_omp_permission_runtime.py tests/test_omp_permission_build_inputs.py`，以及锁定 Bun 的受影响 bridge、session/audit 与 strict 检查。真实宿主复验使用既有授权范围内的临时 HOME 和固定本地响应；更新 `docs/acceptance/omp-permission-control.md`、宿主机器可读证据、支持矩阵及 quickstart 的最终交付身份与实际结果，不沿用旧 runtime 的宿主证据冒充新产物通过。保持冻结样本、原始模型响应与 102/102 请求账本不变，不新增真实模型请求，不修改日常本机 OMP 配置。

**状态**：已完成＝T081/T082、正式离线构建与锁定、152项最终隔离回归、bridge37项/287 assertions、strict/format与同一新资产的真实临时HOME复验；进行中＝无；失败待决策＝无；环境不足未验证＝无阻塞本轮所选交付的已确认环境缺项；尚未执行/未验证＝真实tiny、真实interceptor扩展链/长任务和其它平台保留既有证据边界，不计为通过。

### Phase 9 实施验收（2026-09-30）

T081红灯31 pass/4 fail、T082定向红灯0 pass/1 fail；修复后bridge37 pass/0 fail/287 assertions，最终三组材料化151项加kernel渲染1项共152 passed/71.68s，完整coding-agent类型及四文件format检查通过。新runtime `36c0e8a46da3999b4eee73edc0121117fd284f2880bc7784ba36189946854e0f`，asset `ada205aeec0cd2aefbb4c2d0b00d924ba2d9360395159fdd76f2c6a56a128f41`（367281352 bytes），manifest `f3a274d2c593851d17101d57a8aca6c5705994655f6b93755f356d258918af2f`，receipt `f5ab42e0d4ef6997d0f13bed74d97945190e0a6dbb149ce6d94808bf85269da3`。实际临时宿主main fixture2/review fixture1、primary1/tiny0/human0、成功pwd结果1、permit consumed；new/resume、missing-plugin exit5、rollback restored4通过，provider已停止，外部模型0。构建及宿主详细命令/结果见[最新验收记录](../../docs/acceptance/omp-permission-control.md)和host JSON的convergenceDelivery20260930。日常local摘要不变，模型账本/响应/冻结样本不变，未部署日常cache或实例。

实际分工：executor gpt-5.6-sol/medium负责两项补丁和回归；scout gpt-5.6-luna/medium只读整理交付材料与入口（新线程数量限制时复用现有scout）；主代理负责拒绝边界审查、正式重建、回归与真实宿主验收。

实施后hook核查：`.specify/extensions.yml` 不存在，无需派发after_implement hook。最终45个本地文档链接、82项checkbox唯一性及patch/manifest/receipt/新host证据/启用指南身份一致性检查通过；日常local、模型账本/响应、冻结样本和build-inputs原字节保持不变。

## Phase 10: Convergence

- [X] T083 刷新 `docs/acceptance/omp-permission-control.md` 的“当前运行组”汇总，per FR-033、SC-011、T071（partial，LOW，F1）：该表仍列 T080 的151项/66.79s回归、367269064 bytes资产及 `b1566…` 宿主身份，与同文件 Phase 9 当前交付不一致。依据已有 Phase 9 实际证据更新当前回归为152 passed/71.68s、bridge37 passed/287 assertions、当前资产为 `ada205aeec0cd2aefbb4c2d0b00d924ba2d9360395159fdd76f2c6a56a128f41`（367281352 bytes）、当前宿主runtime为 `36c0e8a46da3999b4eee73edc0121117fd284f2880bc7784ba36189946854e0f`，并保持manifest/receipt与正式锁一致；模型质量行明确沿用T080历史runtime下的冻结集评测，本轮外部模型请求0、102/102账本不变，不冒充新资产重测。保留历史证据原文，以只读结构/链接及锁和host JSON交叉核对验收；无需改代码、重建资产、重跑测试/宿主或新增模型请求。

### Phase 10 实施验收（2026-09-30）

T083完成：当前运行组已刷新为Phase 9回归、bridge、新资产与新宿主身份；模型质量行明确保留T080历史runtime和冻结集范围，本轮模型请求0，102/102账本不变。只读文档验收通过：9个本地链接存在，汇总表5组数据与Phase 9 host JSON一致；正式manifest/receipt schema、receipt摘要、patch摘要及combined runtime交叉核对通过。当前汇总表以外的验收记录原字节不变，8项正式锁/host JSON/冻结样本输入摘要不变。执行由主代理直接完成，单项文档修正未委派；未重跑功能测试、宿主或模型，未改本机配置。

## Phase 11: Cursor 模型选择与远程审查 fallback

用户于2026-09-30授权修复并扩展，主动选择的reviewer_model保留优先级。执行模型重试、主审、远程fallback、本地tiny分别配置；有效模型决定不复审，错误引用不降级掩盖；历史模型评测与账本不改写。

- [X] T084 分离patched宿主模型与资源来源禁用设置，per FR-038/SC-013：增加独立disabledModelProviders，未配置回退旧设置；统一ModelRegistry和model hub过滤，capability继续原资源denylist。仅patched profile生成精确受管设置，保留项目/用户Cursor外部来源禁用、官方profile行为及登录数据；新增实际补丁路径和Python配置/来源边界回归。
- [X] T085 扩展插件三层审查链，per FR-014/019/020/025/026/039、SC-006/013：显式reviewer优先、否则session；remote只在运行失败时使用完整同等级审查协议，同模型跳过；local tiny最后只ask/deny；一次性分层调用计数、共享30秒预算、取消/绑定失效、分层status/explain/audit和旧配置兼容均有隔离回归。
- [X] T086 完成远程fallback宿主与管理器配置，per FR-027/034/039、SC-013：严格remote_fallback_model引用解析、native remoteFallback、独立有界single-attempt运输、两审查模型状态绑定及生命周期失效；kernel选GLM5.3Flash远程fallback并保留省略reviewer、本地tiny和原生保护。验证Cursor unsupported零主审请求→remote许可消费、显式主审不受执行模型切换、远程故障→tiny及UI/审计/取消失败路径。
- [X] T087 完成更新交付，per FR-032/033/038/039、SC-011/013、plan分层验收：稳定代码后刷新official受锁输入身份、离线构建和正式patched锁/receipt；运行相关隔离回归和actual-patched TypeScript/类型检查，并用固定本地provider在临时HOME复验新资产的remote审查与生命周期；更新文档、当前汇总、启用指南及历史身份边界。新远程模型质量、真实Cursor目录与其它平台未验证须明确登记；不新增付费模型请求或修改日常账号/活动会话。

### Phase 11 实施验收

Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。 runtime `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`，asset `0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86`。已完成＝T084—T087；进行中＝无；失败待决策＝无；环境不足未验证＝无本轮交付阻塞，真实账号/模型质量与其它平台未尝试、不得记为通过。完整身份和命令见[验收记录](../../docs/acceptance/omp-permission-control.md)。


本轮验收后，将同一已验证资产原子准备到日常omp-kernel的私人内容寻址cache并显式sync，退出0，runtime为`06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`。仅新增缓存运行包，未apply原生配置、未访问OMP账号库、未启动或停止日常会话；workstation.toml摘要保持不变。退出活动OMP后由用户plan/apply/run启用。


### 本机部署闭合（2026-09-30，后续明确授权）

用户确认已退出 OMP，并明确要求完成日常 `omp-kernel` 的 `plan` 与 `apply`。以原 workstation.toml 执行：`plan` 退出 0，3 项变更、冲突 0、漂移 0；`apply` 退出 0，部署同一 3 项变更；随后 `doctor --format json` 退出 0，状态 `offline-ready`，待变更 0，当前和已部署依赖均 `installed`，`deployed_runtime_matches_current=true`，无冲突、漂移或待恢复事务，`live=false`。当前 combined runtime 为 `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`。

这是前文“仅 cache/sync”阶段之后的新增授权与执行证据。未启动日常宿主、未访问 OMP 账号库，新增模型请求 0；workstation.toml、历史模型响应/账本、冻结样本及 build-inputs 共 9 项受保护输入摘要保持不变。用户接下来可直接 `run`；本次部署健康检查不声称已验证真实 Cursor 目录或新 GLM 模型质量。机器可读结果位于 host evidence 的 `remoteFallbackDelivery20260930.dailyDeployment`。

## Phase 12：官方宿主与独立插件（仓库实现完成）

依据 2026-09-30 用户指令及宪章 VI，本阶段取代宿主补丁方案。历史 T001—T087、补丁 manifest/receipt 和模型原始结果只保存原有身份，不扩展或重新构建。

- [X] T088 记录所有 agent 上游源码不修改的项目原则，更新 AGENTS、宪章版本与架构的历史偏离说明；核对官方公开扩展接口，形成独立插件修订。
- [X] T089 实现 `permission_bash` 独立工具和公开 API 接入、四命令、会话状态、严格审批链及有意义的隔离测试；不覆盖原生 Bash、不依赖宿主 bridge/private tiny，不设只读命令允许表。
- [X] T090 实现官方运行包的 sidecar 配置、封闭验证、模型引用、工具审批策略及旧字段迁移；Cursor 只通过官方配置发现模型且前置守卫拒绝外来资源；验证配置/所有权/凭据隔离。
- [X] T091 稳定插件入口与内容身份后刷新普通依赖锁，更新当前使用与验收文档；历史 patched 结果不转移到独立插件。
- [X] T092 验收独立插件单元/集成与受影响 Python 回归，核对上游源码/官方运行包未改动、原生保护、明确禁止/人工边界、取消和故障关闭；记录实际执行模型、命令、结果及未验证范围。

| 状态 | 当前项目 |
|---|---|
| 完成 | T088—T092：原则、独立插件、官方 sidecar/迁移、锁与文档、限定验收 |
| 进行中 | 无本阶段实现工作；日常启用按指南另行执行 |
| 失败待决策 | 无 |
| 环境不足未验证 | 无已发现的实施阻塞；日常部署、真实 Cursor、新模型质量和其它平台尚未执行 |

独立宿主复验若执行，只使用原有授权范围内的临时 HOME 和 loopback 固定 provider。日常当前仍为旧 patched 部署，迁移 plan/apply 不在本轮默认测试中自动执行。

Phase 12 实际证据：Bun 24 pass / 67 assertions，pristine SDK strict 类型检查与 bundle 通过；正式 catalog 的 kernel+三方迁移 14 pass，discovery+dependencies 53 pass，adapter+pipeline 25 pass。官方二进制隔离宿主通过 ls-la 一次、primary503→remote一次、manual/new重置，最终计数main2/primary1/remote1/skillDescriptions0，新增外部或付费请求0。官方二进制执行后摘要不变，13项保护输入不变。旧构建CLI及旧patched测试入口已退休。详细命令、身份、首次失败及修复、平台/模型与日常部署未验证范围见[Phase 12验收](../../docs/acceptance/omp-permission-control.md#phase-12官方-omp-与独立插件2026-09-30当前交付)。

## Phase 13：本机独立插件迁移与 Cursor 默认模型绑定

用户明确要求更新本机并确认已退出。official sync 退出0，首轮plan/apply各6项、冲突0；原生默认模型 `cursor/kimi-k3-high:high` 相对公共Kimi意图漂移，已保留而未覆写。默认模型属于受管启动资源，故漂移仍会阻止启动；不得删除守卫或篡改基线。

- [X] T093 增加显式 `agent_options.native_model_roles`，仅支持当前官方已启用的 Cursor 动态模型引用，严格角色/标识/思考级别校验；用官方 modelRoles 字段渲染，不伪造 API-key provider 或静态元数据，不改变 reviewer/fallback；完成隔离正反回归。
- [X] T094 将用户已选择的 Cursor 默认模型窄写入本机非秘密覆盖，验证其余配置语义不变；plan/apply正常接纳一致意图，核对doctor、官方二进制和无宿主启动的完整准入，记录本机启用状态及未验证范围。

完成＝官方依赖准备和首轮6项迁移；进行中＝T093—T094；失败待决策＝无；环境不足未验证＝实际Cursor OAuth/模型调用仍未尝试。本阶段不访问账号库、不新增模型请求。

Phase 13 完成：T093—T094。Cursor OAuth 明确声明与native角色覆盖正反回归59 pass；本机首轮迁移6项、无冲突，原生Cursor默认选择保留。通过render_edit+Tree原子0600窄编辑三个非秘密字段范围，其它TOML语义未改；后二次plan/apply变更0、漂移0、冲突0，doctor offline-ready、依赖installed、运行包匹配、无恢复/live。完整运行路径准入通过（过滤SecretRef并使用launch callback，不启动宿主）；official SHA与plugin identity不变。12项其余保护输入不变、模型预算不变。完成＝T093—T094；进行中＝无；失败待决策＝无；环境不足未验证＝无本轮阻塞；真实Cursor认证/模型调用及其它平台仍未尝试。详细记录见验收Phase13及standalone evidence.dailyDeployment。
