# TK-R2 测试与证据入口

当前规范是 OpenSpec `add-pi-task-keeper` 的 TK-R2：142个场景、38组 AC、300个命名变体。`tests/plan-r2/bundle.json` 是正式规范的校验快照；`npm run test:plan` 检查映射、规范语义及历史 hash。下文的 P0–P3 最低义务和扩展矩阵说明属于历史契约，原文件仍供旧报告回归使用。

`npm run test:report` 执行当前完整隔离套件。每个 AC 需要实际 file/name、非零断言、正确层级、独立 observer、存在的工件及当前 source/plan 摘要；历史运行不自动计入。`currentCoverage.ready`只表示命名验收记录齐全，Scenario状态由AC映射推导；实现语义是否满足要求必须另行审查。`npm run test:report -- --release` 额外要求当前发布门槛全部满足。

完整通过后执行 `node --experimental-strip-types scripts/evidence-checkpoint.ts test-results/<runId>/report.json`。它重算当前证据并核对原始记录、TAP、source/plan 和产物摘要，原子更新唯一机器进度 `docs/testing/runtime-progress.json`，保留旧 checkpoint 备份。TK-R2 分支不回填旧矩阵为新版通过。

实际支持范围与状态见 [README](../../README.md)、[能力范围](../scope-audit.md) 和 [OpenSpec单一进度](../../../../../openspec/changes/add-pi-task-keeper/implementation-progress.md)。未运行真实服务不宣称实网认证；品牌不构成验收前置条件。

以下保留历史测试设计及工具说明，旧数字不控制 TK-R2：

# 当前测试设计与覆盖检查

> 2026-09-14：当前功能设计已重订为TK-R2，见[唯一实施进度](../../../../../openspec/changes/add-pi-task-keeper/implementation-progress.md)。本页旧71/76和P0–P3覆盖数字仅对应现有代码基线，不是新版完成状态。包内源码与旧测试计划尚未迁移；此设计整理不赋予新运行信用。


2026-09-10续做入口：[Pi执行交接](../../../../../openspec/changes/add-pi-task-keeper/pi-execution-handoff.md)。当前源码包含最后完整报告之后的修改；40项只读定向检查通过，隔离全套受环境权限阻塞，尚未新增发布证据。下列777/114/313仍是最后完整运行的历史检查点。

当前设计已覆盖 **707/707 项 P0–P3 义务（设计映射 100%）**，包含设计建立时全部 **618 项缺失证据**，其中原设计已有 398 项、新暴露 220 项均已逐项补齐。另保留 6 项 P4 在线延期设计，总计 **713 项义务、228 个场景/故障 ID、36 个批次**。此前已获得证据的 89 项 P0–P3 义务也保留明确回归 case，避免证据失效后再次没有设计。

**设计覆盖、实际执行和完整变体审计分开记录。** v2 设计建立时是197项通过、618项P0–P3缺口、66/76任务；该基线不改写。当前运行 `2026-09-09T20-06-39-144Z` 通过777项测试、16845条断言，最低缺口114，实施71/76；完整变体/observer审计仍未完成，`releaseReady=false`。当前事实见 [runtime-progress.json](runtime-progress.json)。

| 当前文件 | 内容 |
|---|---|
| [case-design.md](case-design.md) | 可读设计：7 层执行规则、36 批领域配方、171 项具体检查、正反对照、边界与依赖 |
| [coverage-cases.csv](coverage-cases.csv) | 全部 713 项义务的唯一 case ID、原 WHEN/THEN/摘要、步骤、断言归属、建议 file/name、变体与工件要求 |
| [runtime-gap-cases.csv](runtime-gap-cases.csv) | 最新运行的114项最低缺口，逐项关联完整设计；继续实施优先从这里读取 |
| [runtime-case-evidence.csv](runtime-case-evidence.csv) | 实际测试file/name、逐ID断言和工件；完整变体审计仍单列pending |
| [current-gap-cases.csv](current-gap-cases.csv) | v2设计基准的618项缺口，冻结保留用于对比 |
| [newly-uncredited-cases.csv](newly-uncredited-cases.csv) | 新暴露的 220 项缺口，逐项给出完整设计；不是只补场景标签 |
| [case-recipes.json](case-recipes.json)、[layer-profiles.json](layer-profiles.json) | 人工编写的领域输入/独立预期与分层执行规则；修改后重新生成 CSV |
| [expanded-matrices.json](expanded-matrices.json) | 66 个 await 双向组合、18 个动作/崩溃切点、42 个请求路径/取消窗口、4 种流终态、12 个生命周期/发送状态组合 |
| [design-baseline-v2.json](design-baseline-v2.json) | 原 435 设计、来源矩阵、spec 和当前运行检查点的冻结哈希 |
| [design-review-v2.json](design-review-v2.json) | 设计结构审查和 14 个负向控制结果；明确 runtimeEvidenceAdded=0 |
| [current-checkpoint.json](current-checkpoint.json) | 原运行事实和精确缺口，设计补齐不会改动此文件 |

在仓库根目录校验，无需加载 Pi、真实配置、网络或模型：

```sh
python3 pi/packages/task-keeper/docs/testing/check-design.py --self-test
```

修改人工设计输入后生成文档，再重新校验并保存设计审查结果：

```sh
python3 pi/packages/task-keeper/docs/testing/build-design.py
python3 pi/packages/task-keeper/docs/testing/check-design.py --self-test --output pi/packages/task-keeper/docs/testing/design-review-v2.json
```

生成器只渲染设计，**不自动重建冻结来源哈希**。新增/修改规范或更换运行检查点时，校验会报漂移，必须先审阅新增/变更义务与缺口，再显式更新相应设计基线，不能借重新生成绕过审查。历史报告未随 Git 分发时，校验会明确列出实际核验到的报告，不假称读取过缺失工件。

## 从设计到实际覆盖的完成标准

1. 每项义务必须有原场景的主断言，附正例、负向对照、批次检查以及本层适用的全部组合。源码路径和建议测试名是实施位置，不能当作已经存在或已经运行的证明。
2. 测试实现可复用现有函数或共享夹具，但必须关联 `caseId → variantId → obligation → assertionId → observer artifact + predicate`。历史候选文件只作审查线索；不能给旧测试简单加 ID 就认定补齐。
3. U/S 只证明规则与事件序列；A 要实际 adapter/SDK，P 要真实 SQLite/OS 事实，E 要真实宿主/用户/模型入口。批次领域步骤按层级转换，U 中的“请求数”只能是动作描述，不能冒充实际接收数。
4. 原规范要求成功而当前没有入口或接口时，标记实现依赖并保持未通过。只有明确不在支持范围的组合才以拒绝作为预期；不能把所有路径拒绝来获得完整认证。
5. `primary`、正反对照、每个具体检查及组合都通过才满足本case；任意必测变体缺失、skip、证据过期或observer缺失仍为未完成。现有报告器的逐ID断言计数只是第一道检查，还需实施变体与工件归属审计（12.1）。
6. 两项 L 保持 `needs-live-binding`；6 项 P4 保持延期。T75 的离线报告规则属于本阶段，不能挪到延期项。计划完整不改变当前 `releaseReady=false`。

例如 `TC-CFG-004-U` 的预算检查不能只记录“测试通过”：输入应固定用户上限12、项目上限24，分别断言有效预算仍为12、required reviewer保留、原used/reserved未清零。原上限12→项目6是合法成功对照；移除单调合并限制的隔离坏实现必须使扩权反例失败。两种输入及每条断言都绑定该case与具体变体。

后续运行证据的每条记录必须包含：`caseId`、`variantId`、`obligation`、`assertionId`、`sourceDigest`、`runtimeLockDigest`、`observer`、`artifact`、`predicate`、`actual`、`status`。建议断言身份为 `<caseId>.<variantId>.<predicate-name>`；CSV中的 `<run>` 只是未来工件路径模板，不能填入实际通过证据。一个case可拆成多个测试函数，共享测试也可服务多个case，但每项分别核对其主断言、全部必测变体和层级。

本轮还检查了全部八份 spec、56 个 Requirement、126 个 Scenario 与 102 个 fault 的对应关系，保留 v6 的 ADR/S 来源与九份校验和。原始 435 项设计文件保持不变；以下保留建立该基线时的说明，**当前执行方法、依赖状态和完整索引以 v2 为准**。

---

# 历史基线：435 项缺失证据的测试设计

本补充基于运行 `2026-09-07T23-05-22-890Z` 的原始缺口，覆盖 **216 个受影响 ID、435 个 ID × 层级义务**，组织为 **33 个测试批次**。其中规范 Scenario 缺 211 项、故障条目缺 224 项。这是补测设计建立时的冻结基线（**designed / not-executed**），不是当前执行状态。后续实现、隔离测试、严格逐 ID 归属和当前缺口见 [实施状态](../implementation-status.md)；原始 CSV 与 baseline 保留，不能被新结果覆盖。

| 文件 | 用途 |
|---|---|
| [gap-obligations.csv](gap-obligations.csv) | 每项包含原 ID、缺失层级、原始触发/期望、步骤、变体、独立断言、负向对照、建议测试 file/name、实施依赖与状态 |
| [campaigns.md](campaigns.md) | 可读的 33 个批次操作设计与每批精确缺口列表 |
| [campaigns.json](campaigns.json) | 同一批次定义的结构化版本；修改时与 Markdown 同步 |
| [baseline.json](baseline.json) | 原始 missing 集合、运行及矩阵哈希；用于识别以后新增/消除的缺口 |
| [design-review.json](design-review.json) | 本次只读结构校验结果；不是测试通过报告 |

所有文件在包内 `docs/`，可随源码保留；OpenSpec 工作区的入口为 [test-plan.md](../../../../../openspec/changes/add-pi-task-keeper/test-plan.md)。原 126 个 Scenario、102 个 fault、required_layers 和历史运行报告不改写。

## 1. 覆盖口径

| 缺失层级 | 项数 | 补充证据 |
|---|---:|---|
| U | 51 | 独立真值表、边界、单条件拒绝、合法正例 |
| S | 88 | 可重放事件序列、状态迁移、固定时钟与种子 |
| A | 77 | 真实 Pi/adapter、序列化与 SDK 调用、独立接收端 |
| P | 76 | 真实 SQLite、OS 多进程、重启、终止观察 |
| E | 122 | 命令/工具到执行、账本、回执、父模型及展示的整条路径 |
| L | 2 | 明确绑定的真实 Qwen 有限实测 |
| V | 19 | 实际测试发现、证据归属、发布与评测报告的验证 |

这 435 项不是 435 个测试函数，也不是现有测试的失败数。建议文件名使用 `tests/gap-gNN-层级.test.ts`，位于当前测试发现器扫描的顶层；建议名称明确包含 `[层级 ID]`。这些 file/name 目前是**计划身份**，不能填入运行 evidence。

实施时可复用现有测试，但必须检查其实际触发和断言是否满足该 ID 的全部要求。CSV 中 `existing_candidate_files` 仅从历史记录找出可参考文件，既不证明缺失层级已覆盖，也不建议靠加标签消除缺口。

每个测试含多个 ID 时，要生成逐义务断言索引：`obligation → assertionId → observer artifact + field/predicate`。总断言数大于零不能证明每个 ID 都有断言。报告器现已通过 `evidence(id, assertions)` 校验多 ID 测试的逐义务断言，并校验实际发现、执行和清理失败。未归属的旧断言不再计入相应 ID；这会使当前缺口多于冻结基线的 435 项。该机制仍不能代替对每项必测变体、断言语义及独立观测的人工审计。

## 2. 实施顺序及前置条件

| 波次 | 内容 | 完成标准与前置条件 |
|---|---|---|
| B0 | 测试隔离、证据报告、配置/契约、存储、owner、崩溃 | 先建立隔离执行入口，再运行真实进程；迁移实现未完成时 G11 保持待办 |
| B1 | Qwen 同路线恢复、时间、流错误、用户控制、共享许可 | 在实际 Pi 上完成 Q1/Q2；G03/G15 的服务来源样本与合成样本分开 |
| B2 | 调度、持续工作区、独立验收、PARTIAL、审查复用 | 先完成 9.6 所缺语义，再跑完整 E；测试固定工作流不扩大模型授权 |
| B3 | 多路线、protected gate、预算、有界策略 | 10.1/10.2/10.6 的真实路径认证逐项成立；不支持路径验证拒绝 |
| B4 | Qwen 环境认证 | G32 的 V 报告器反例可离线执行；VAL-005/007 的 A/E/L 六项实际服务义务等待真实绑定与请求上限 |
| P4 | 在线 Advisor 的未来测试 | G33 保留 T66/T68/T69 的 6 项 U/V；未实现，不以 off 拒绝测试替代在线行为 |

**实网边界纠正：VAL-005/007 的 A/E/L 共六项依赖实际服务绑定；其 V 报告规则可以离线验证。六项 P4 延期保持。**“本地可验证”只表示不需要真实付费服务，不表示其生产功能、测试 harness 或接口已经齐全。G11、G13、G23、G29 等明确有实现依赖。

所有 P0–P3 完整发布要求仍按原矩阵判断。明确的能力子范围发布需要单独列出适用义务和不支持能力；不得删除总矩阵中的缺口，或用“P4 延期”把全功能报告改成通过。

## 3. 测试进程隔离是执行前置条件

此前真实 Claude 配置被旧同步测试写入，说明只设置 XDG 或通用 test-mode 并不足够。以下是设计建立时规定的执行前置条件；当前包测试入口已使用 bwrap 命名空间验证真实 home 隐藏、源码只读、私有写目录和仅 loopback 网络，隔离审计随每次运行保留。历史事故与恢复状态见实施状态文档。

1. supervisor 创建一次性根目录，进程创建时传入独立 HOME、所有 XDG 路径、`PI_CODING_AGENT_DIR`、`PI_SUBAGENTS_TEMP_ROOT`、`PI_MODEL_EXCLUSIONS_PATH`、state root 和 workspace。环境从白名单构造；仅指定的 L 测试注入运行时凭证引用，其余使用合成标记。插件导入前核对所有解析路径落在独立根内。
2. 对会执行插件加载、仓库脚本或同步的进程，使用容器/文件系统命名空间等可验证的写入约束：真实 home 不可写，仓库与依赖只读，临时工作树和结果目录才可写。只改 HOME 或测试内 monkey-patch 不能替代这一隔离证明。缺少该执行环境时，相关测试标 blocked，不能降级到真实 home 运行。
3. 同步单元测试使用假目标；Pi 资源集成测试只指定临时 Pi 目录。不得调用真实 `sync_all`、`:AISync`、`:PiGenerate`，也不得在真实 home 放哨兵。用临时“受保护 home”验证 `allow_in_tests`、路径穿越、绝对路径硬编码和 symlink 不能绕过边界。
4. 离线 A/P/E 只允许 loopback 测试服务；子进程脱离 group 的负例由外层 supervisor 跟踪并回收。每个测试有有限超时，失败保留工件，清理只能删本次创建且 identity 验证通过的临时根。不能按宽泛进程名杀任务。
5. 隔离自身测试：正常临时写入成功；假受保护目录写入拒绝；绝对路径逃逸拒绝；launcher 配置缺失在导入插件前失败。独立 observer 保存写入拒绝事实。这些是新增执行前置要求，不被算作原 435 项已经通过。

这项测试环境设计不意味着产品 VerifyRunner 自带 OS 沙箱；产品当前仍只承诺已认证的工具/进程覆盖。

## 4. 可复现的竞态与崩溃展开

G18 至少登记以下可达的生产异步边界。每个边界分别运行“撤权先到、await 先完成”两种顺序；**auth/telemetry/资源读取结束但实际 fetch 尚未调用**的窗口必须重新准入。

| RACE ID | await/边界 | 撤权或状态变化 |
|---|---|---|
| R01 | auth/凭证刷新返回 | 输入、stop、绑定变更 |
| R02 | telemetry 读取返回 | 输入、stop、账号/桶变更 |
| R03 | probe/canary 返回 | 输入、pause、stop、shutdown |
| R04 | setModel/route 生效返回 | 输入、stop、配置摘要变更 |
| R05 | 资源/请求许可已预留，外部调用前 | 输入、stop、ownerEpoch 变更 |
| R06 | 原生 dispatch accepted，start/ack 返回 | stop、reload、owner 丢失 |
| R07 | continuation ack 返回 | 输入、stop、switch/fork |
| R08 | compact/原生 retry/queued follow-up settled | 输入、stop、切换会话 |
| R09 | 工作区快照 helper 返回 | pause、stop、dispose |
| R10 | verifier/reviewer 结束返回 | stop、源码/验收输入变化 |

每个实际支持的边界 × 表列变化 × 两种顺序展开用例，保存 barrier 名与事件次序；不以 pairwise 省略这些交叉。未实现或不可达的路径记具体拒绝证据和支持范围，不能假造成功 setModel/fetch。其他独立维度如 UI 模式、项目形态可使用显式列出的 pairwise 集合。

G12 的 C0–C5 沿用原计划：intent 前、提交后发送前、已生效 ack 前、ack 到达落库前、终止结算前、结算通知前。对 **start / continue / verify 三种动作分别覆盖，至少 18 个基本轨迹**。底层 store-worker 的 C0–C5 结果不能直接证明三种真实调用链；需要实际 adapter hook、receiver 或 verifier sentinel 关联。

独立 supervisor 才能决定“子孙进程已停”；账本 unknown 不得以 fakeAdapter.cancel 返回成功清除。隔离环境中无法证明终止的用例应得到明确 blocked/unknown，并保留资源，随后由测试 supervisor 清理自己的进程。

## 5. 固定输入、断言和工件格式

U/S 的 expected 由规范真值表给出，禁止调用被测 reducer 或 selector 生成 expected。临界值至少为 N−1/N/N+1、0、空/缺失/null，以及期限前/恰好/后；所有关键准入均有全合法正例和每次仅一项不合法的反例。

S 属性集预先固定 seed `17,41,101,2026`，每个 150 步；失败保存完整事件与可重放最小序列。该次数是可重复测试范围，不是穷尽证明。性能/公平性使用明确有界输入和选择计数，不靠随机 sleep 或无限等待来判断最终进展。

实施后的每条断言证据至少关联以下字段：

```json
{
  "caseId": "GAP-REC-013-P",
  "obligation": "REC-013:P",
  "testFile": "tests/gap-g19-p.test.ts",
  "variant": "ten-sessions-same-pool",
  "sourceDigest": "<reviewed obligation digest>",
  "runtimeLockDigest": "<actual source/runtime/profile digest>",
  "assertionId": "receiver.concurrent-half-open<=1",
  "observer": "independent-http-receiver",
  "artifact": "<run/case/receiver.jsonl>",
  "status": "<actual passed/failed/skipped>"
}
```

示例是设计结构，不是已实现记录格式。工件应同时有 scope/job/attempt/request ID、测试时间、PID 启动身份（适用时）、seed/barrier、脱敏配置摘要；敏感数据用合成 marker 检查不落盘。G09/G32 明确比较 raw/ledger/receipt/父模型实际输入/UI 五层，不能用一个 details.error 替代。

每批负向控制只在隔离副本或专门坏 fixture 中进行；坏实现应使子测试非零退出，父验证记录 expected-negative。正式产品测试出现的失败仍是 failed，不能改名为负向控制隐藏。正例也必须成功，以免构建“永远拒绝”的错误实现。

## 6. Qwen、环境参数与研究参考

G03/G15 的分类响应包含 provenance：`synthetic`、脱敏的实际服务响应或已核实文档样本。模型、provider、endpoint、账号引用、quotaGroup、network、classifier 均从配置取得。两个服务的同系列模型使用同一核心；不得把历史百炼样例推广为所有 Qwen 服务错误语义。

Q1 是规则/状态，Q2 是实际 Pi 加受控服务，Q3 是实际绑定。Q3 不要求耗尽账号额度：只有显式验收 profile 可以注入一次带来源标记的429，然后交还实际服务。若注入入口不可验证，正常 smoke 只能证明可用性。缺绑定/上限保持 pending；不在本次设计补充中请求真实凭证或执行付费请求。

每批 `refs` 追溯原 ADR 与 S 来源；完整对应仍在 OpenSpec [traceability.md](../../../../../openspec/changes/add-pi-task-keeper/traceability.md)。S1–S5 支持候选执行接口的核对，S6–S9 只在实际采用的分类/telemetry/transport 绑定处核实；S10–S26 提供受限控制、验收、依赖、路由与效用评测方法。本文没有重新联网认证资料版本，也不把论文或 draft 当成产品可靠性证据。

11.6 的效用实测与故障覆盖分开：冻结模型/工具/任务/验收及分组留出，比较 direct 与有界策略；所有启动、失败、等待、截止未完成、人工介入及 unknown 成本进入统计。现有 V 层结果或这份测试设计都不能证明模型策略提升了收益。

## 7. 设计完成与执行完成的检查

本次静态审查核对：CSV 的 obligation 集合与原报告 missing **完全相等**；435 行唯一；所有 ID/层级存在于原矩阵；原触发与期望保持；每行有批次、步骤、断言、变体、独立观测、负向对照、工件要求与依赖；建议 file/name 唯一；运行状态均为 not-executed，result_artifact 为空；33 个批次无遗漏；原报告、原矩阵、v6 哈希不变。

实施后才可将测试发现记录关联到计划并产出新的独立运行报告。每次报告与 baseline 比较新增、已补证据、失效和失败，不修改原运行。一个 obligation 只有其所有必测变体具备当前 lock 下有效断言，才可在相应层级满足；单个 file/name 的 passed 不足以跳过尚未实施的变体。

此补充记录建立时 **63/76 实施任务、126 个已通过测试、435 个运行证据缺口** 的历史基线；后续进展见 [实施状态](../implementation-status.md)。设计文件本身不自动勾选实施或验收任务。


## 扩展矩阵的实际证据

新增 `matrixCase(matrixId, caseId, assertions)` 记录独立的变体断言。全量报告的 `expandedCoverage` 逐项检查扩展矩阵的 436 个「变体 × 层级」位置：没有运行、零断言、跳过、失败或过期证据都不能补齐。一个顺序通过不代表反向顺序通过，P 层证据也不自动取得 S/A/E 层信用。`matrixEvidence` 保存实际 file/name、断言数及运行工件。

这项检查单列于原来的 707 项 P0–P3 最低义务，不改写原设计或缩减缺口；完整领域配方/observer 质量仍需人工逐项核查。已开始登记生命周期基本矩阵和 canary/continuation await 时序，其余尚未逐变体登记的旧测试不会自动获得信用。


定向运行使用包内明确文件路径，路径相对于 Task Keeper 包；也接受包内绝对路径，并转换到隔离快照。全部指定文件都必须存在，包外路径、越界软链和未展开的文件通配符拒绝执行。只给筛选选项时按包内测试清单发现用例，筛选结果为零仍失败。`--report` 只接受可选 `--release`，不能用附加文件名伪装成定向报告。


## 工作流测试分组

68 个工作流场景按独立夹具分到四个入口：`tests/workflows.test.ts`（工作区与核心流程）、`tests/workflows-recovery.test.ts`（恢复）、`tests/workflows-evidence.test.ts`（证据）、`tests/workflows-policy.test.ts`（策略与控制）。它们复用 `tests/fixtures/workflow-cases.ts`，完整报告同时发现并运行四组，保持原场景名、ID 和断言。定向执行请使用报告中的实际入口文件；原 `workflows.test.ts` 现在只注册核心组。

## 当前证据回填命令

完整隔离报告通过后，在包目录执行：

```sh
node --experimental-strip-types scripts/evidence-checkpoint.ts test-results/<runId>/report.json
```

该命令先校验当前包源码摘要、原始 discovery/execution JSONL、完整测试名、层级、逐项断言数、工件路径，以及重新计算的 missing 集合。全部校验通过才从报告生成 runtime-case-evidence、runtime-matrix-evidence、runtime-gap-cases 和 runtime-progress；closure 表仅更新 current_run/current_runtime_evidence，原始设计和人工审核状态保留。旧视图保存到对应的 `test-results/checkpoint-before-<runId>/`，同一 checkpoint 禁止覆盖其审计备份。它不把最低证据存在视为完成全部变体审核，也不替代对断言语义与实际测试层级的审查。

## 具体服务恢复证据报告

`node --experimental-strip-types scripts/recovery-report.ts /path/to/evidence/input.json` 是只读报告入口，输入类型见 `src/evidence/recovery-acceptance.ts` 的 `RecoveryAcceptanceInput`。它读取已经采集的记录，不发请求、不读取凭证、不写运行时认证。观测引用的工件必须是输入目录内存在且非空的文件。

输入明确区分 injected、service-origin、loopback；记录每次请求的身份、会话/continuation、版本/profile/binding 摘要、发送/结束时间、notBefore、结果、工具副作用和真实任务终态。只有配置与观察身份一致、请求不超限、冷却被遵守、原会话恢复完整完成且无重复副作用时，报告才给出针对该组合的 recoveryQualified。仅 smoke 通过只显示 availabilityPassed，缺绑定、失败服务、loopback 回放、失效身份、unknown 或缺工件均不取得恢复通过结论。工件真实性仍需独立审核；包内 V 测试的所有输入均为显式合成报告反例，不构成 Q3 实网认证。

2026-09-15：新增结构化 `code-coverage.json`，按原源码路径排除tests/临时副本，仅报告测试worker的观测范围；原生Pi子进程尚未完整采集，明确`complete=false`，不再把混合all-files数字作为产品覆盖率。
