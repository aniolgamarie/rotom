# Contract: Herdr 升级基准

本契约定义 `tools/bench/herdr_upgrade.py`、合成 fixture 和 schema 的实现接口；代码和隔离检查见实施证据，本轮没有取得有效原生基准；启动诊断失败及原因见实施证据。需求见 [spec.md](../spec.md) FR-025–034，依据见 [research.md](../research.md) R8。历史[升级材料](../../../openspec/changes/herdr-native-workspaces/upgrade-benchmarks.md)只作负载来源。隔离机器配置把固定、版本化的合成fixture executable作为machine.editor，经work open edit --new在新PTY中启动；不扩大生产七种role或允许任意argv，也不向已有shell注入命令。合成编辑器替身不构成Avalon验收。

## 调用与副作用

入口固定使用已准备的仓库 `.venv/bin/python`，不隐式安装、下载、登录、改锁或扩权。参数路径相对调用 cwd 解析；文件内容路径相对 manifest 所在目录解析，报告只公开逻辑标签和合成数据。所有参数和结构化对象未知字段均退出 2，不能静默忽略。下列数组是接口示例，输入文件由实施者按 schema 事先准备，实际执行需按schema准备输入与授权，示例不构成执行或授权证据。

```json
[".venv/bin/python", "tools/bench/herdr_upgrade.py", "validate", "--manifest", "bench/manifest.json", "--policy", "bench/policy.json", "--report", "bench/candidate.json"]
[".venv/bin/python", "tools/bench/herdr_upgrade.py", "calibrate", "--manifest", "bench/manifest.json", "--policy", "bench/absolute-policy.json", "--subject", "candidate", "--allow-native", "--authorization", "native-bench-approval-01", "--output", "bench/calibration.json", "--policy-output", "bench/calibrated-policy.json"]
[".venv/bin/python", "tools/bench/herdr_upgrade.py", "run", "--manifest", "bench/manifest.json", "--policy", "bench/policy.json", "--subject", "candidate", "--scope", "first-baseline", "--allow-native", "--authorization", "native-bench-approval-01", "--output", "bench/candidate.json"]
[".venv/bin/python", "tools/bench/herdr_upgrade.py", "compare", "--manifest", "bench/manifest.json", "--policy", "bench/policy.json", "--candidate", "bench/candidate.json", "--output", "bench/decision.json"]
```

| 子命令 | 必需参数与可选参数 | 结果与边界 |
| --- | --- | --- |
| `validate` | `--manifest FILE`；可选 `--policy FILE`、可重复 `--report FILE` | 离线严格校验各文件 schema、摘要、引用、单位与内部一致性；stdout 为 JSON 诊断，不启动宿主，不将结构有效当作验收通过 |
| `calibrate` | `--manifest FILE --policy FILE --subject baseline\|candidate --allow-native --authorization REF --output FILE --policy-output FILE` | 显式原生同身份 A/A 重放；输入 policy 已冻结绝对预算与校准方法，输出校准报告及待批准政策。不能自动批准政策或生产基线 |
| `run` | `--manifest FILE --policy FILE --subject baseline\|candidate --scope first-baseline\|runtime\|full-stack --allow-native --authorization REF --output FILE`；runtime/full-stack另必需`--paired-output FILE` | 只执行冻结的合成矩阵、收集报告；不作默认入口切换。scope 必须匹配 manifest；first-baseline 只允许 subject=candidate |
| `compare` | `--manifest FILE --policy FILE --candidate FILE --output FILE`；可选 `--baseline FILE` | 完全离线比较。缺 baseline 只评价首轮正确性、绝对预算与证据，输出 `first-baseline` 结论；有 baseline 才允许 runtime/full-stack 升级结论 |

输出文件必须是新文件，存在时退出 4，不覆盖证据；以同目录0600临时文件完整写入并fsync，再经Linux renameat2(RENAME_NOREPLACE)原子发布新名并fsync目录；首次可见时必须是完整单链接文件，reader的uid/mode/nlink检查保持严格。本轮Linux基准缺少libc/kernel/文件系统所需能力时以atomic_publish_unavailable拒绝（runner退出5），不退回hard link、覆盖式replace或直接写final；目录fsync失败保留已发布final，不据失败重试覆盖。正常生成报告时 stdout 为含 `report` 逻辑引用、`validity`、`decision`、`task_status` 的 JSON 摘要；stderr 仅脱敏错误，不含环境全量、shell 历史或会话内容。`run` 原始性能结果只有 measured 状态；最终性能结论由 `compare` 生成。缺少 opt-in 参数是参数错误，授权引用只是审计标识，不能代替真实用户授权。

| 退出码 | 含义 |
| --- | --- |
| 0 | 校验成功、测量有效或本次限定范围的比较通过；首轮有效测量不代表升级回归通过 |
| 2 | 参数、schema、未知字段、输入身份/政策引用不一致或未冻结 |
| 3 | 明确另获授权的集成范围所需凭据缺失；合成主基准不需要凭据，也不尝试读取 |
| 4 | 输出已存在、隔离/所有权冲突、活动对象冲突或原生操作结果不明；保留证据和对象，不盲目重试 |
| 5 | 依赖/能力缺失、run 无效、正确性失败、必需指标缺失、预算/回归失败或必需范围未验证 |
| 6 | 文件系统或 runner 内部操作失败；不能降格成被测工具性能失败 |

## 三类输入与报告

实现文件为 `schemas/herdr-benchmark-manifest.schema.json`、`schemas/herdr-benchmark-report.schema.json`、`schemas/herdr-benchmark-policy.schema.json`。三者独立版本化，各对象层级 `additionalProperties=false`。数字必须有单位、有效样本数和适用范围；不可测值必须为 `value: null` 配合非空 `reason`，禁止缺省成 0。缺失必要值使对应范围不能通过；可选值缺失仅使该项未验证。

| 文档 | 必填字段组与约束 |
| --- | --- |
| manifest | `schema_version`、`manifest_id`、`fixture_version`、`fixture_digest`、`seed`；`source` 绑定候选 commit/源摘要、target main、依赖锁摘要；`subjects` 为 baseline（可空并说明原因）/candidate 的发行、官方来源、资产摘要、磁盘 client 与运行 server 身份及对应验收引用；`scope`；`inputs` 的配置、检测规则、集成摘要；`environment` 的平台/工具类别、尺寸、测量定义；`workloads`、`steps`、`sampling`、`isolation`、`authorization_ref` |
| 每个 step | `id`、`argv` 字符串数组、`cwd_label`、非秘密 `env_allowlist`、期望退出码/副作用、可核实就绪条件、单调超时、清理对象标签。执行manifest为私人输入，公开副本用路径标签。argv不能为shell文本，禁eval/PTY send-input/pane run/agent.start；终端producer通过隔离machine.editor固定fixture与open edit --new启动，runner外直接输出不能冒充PTY输出负载 |
| policy | `schema_version`、`policy_id`、内容摘要、适用 fixture/scope/环境类别、冻结时间及批准引用；每指标绝对预算、相对与绝对回归阈值、近零分母规则、A/A 噪声包络、批间一致性规则、预注册重测规则、校准报告引用。未完成校准的字段显式 null+reason，不能给性能 PASS |
| report | `schema_version`、`report_id`、manifest/policy/fixture 摘要、source/target/lock 身份、subject/scope、授权与隔离证明、实际磁盘/server/配置/规则/集成身份；每步`normalized_argv`/cwd标签/退出码/单调起止/就绪证据、私人原件`execution_digest`/`evidence_ref`；batch顺序、合成样本与汇总、正确性、producer计数、无效/重试原因、必需/可选证据、逐项结论和四种任务状态 |

私人执行记录区分预期argv和实际argv，保存在公开仓库外，目录0700/文件0600；实际身份不符不得继续比较。公开report只有明确命名的normalized_argv、逻辑路径映射、原记录SHA256及脱敏evidence_ref，不能把规范化数组称为实际argv。公开validate只能检查结构与摘要引用，实际执行身份还须核验私人原件；在公开报告标记原件核验结果和脱敏证据引用，不公开原件路径。

manifest/policy/report若含自身digest，统一将该字段删除后，以UTF-8、排序键、紧凑逗号/冒号分隔、无ASCII转义的canonical JSON计算SHA256；禁止非有限数字。被引用的外部资产/文件按原始bytes计算SHA256，不能混用。公开规范化副本与私人原件分别有摘要，不把两者说成同一文件。

摘要绑定本工具、fixture、测量工具和policy版本，变更后重新判断可比性。公开报告不存私人路径/主机名/认证/会话/终端buffer/原剪贴板，不读取真实私人数据证明清理，只使用虚构checkout、固定假提交、合成输入。

同冻结manifest从校准衔接首基线时，isolation.root须不存在，不能复用旧树。仅在校准结束、自有进程退出及四组fresh核验为空后，保全归档完整owned隔离树到同文件系统的新私有目标，不覆盖；manifest内容及所在目录、private_record_root、sentinel、原件argv均保持原样。归档后重验校准原件，再由runner按同一冻结root新建树。现有records非空允许，但输出文件须新建；单独改root可能破坏旧argv的归一化，不能以放宽原件核验解决。核验依赖已保存的records，不重新读取旧checkout/control/socket；实际归档与postflight结果须另记，不因该流程可行而提前通过。

fixture只读取本轮生成的严格配置（mode=idle/output/record、seed、runID、控制目录），不接受任意命令。runner拥有的临时控制目录用于ready/start barrier与合成计数；fixture从新pane stdout输出，须核对native pane对应的producer身份。测量start采用固定同机单调时间；output在预热与测量窗口分别计数；detached场景在测量barrier前断开全部client，完整输出/采样300秒，不以提前启动的计数冒充该窗口。控制文件仅限测试，不成为生产管理服务或终端库存。

配置传递锚点固定为合成checkout根的 `.rotom-bench-v1.json`：runner在启动该checkout的任何fixture前创建，不作为Git来源提交。字段严格为version=1、run_id、mode、seed、control_dir、config_digest；同checkout的并发fixture读取同一份不可变配置，各自用经原生确认的HERDR_PANE_ID作为实例键，在0700 control_dir下写独立0600 ready/count文件。runner预先登记期望pane集合，拒绝重复/陌生实例；不改生产handoff payload、不增加任意argv。不同mode/batch/run使用新的合成checkout目录，不能在现存producer运行时改该文件；路径/owner/链接/摘要不符则该run失败。start barrier为控制目录内只读JSON（run_id、phase、start_ns），phase限定warmup/measure，start_ns为同机单调时间；fixture拒绝其他指令。结束计数注明窗口边界及pane逻辑标签，公开报告不暴露私人control_dir。

## 对照范围与首轮基线

`runtime` A/B 固定配置、检测规则、集成、fixture、采样工具和环境，仅改变官方程序/资产。`full-stack` A/B 记录各自实际配置/规则/集成全部摘要及差异，用于评价完整组合；不能把该差异归因为程序本体。两类结果独立报告、各有结论；缺一类只能报告已有证据支持的范围。真实 Avalon/Agent、模型与网络成本作为独立授权的附加报告，不能混入合成主基准 CPU/RSS/latency。

首轮没有已验收 A 的顺序：

1. 冻结 fixture、测量方法、校准方法和目标机器类别的绝对预算，输入 `absolute-policy.json`。绝对预算由验收目标决定，不能看候选成绩后倒推。
2. 明确授权后以同一 candidate 身份重复测量，运行 `calibrate --subject candidate` 估计 A/A 噪声；它是候选自重放，不虚称已验收 A。
3. 审阅校准报告，批准并冻结输出 policy，记录批准引用和摘要；预算不随校准放宽。必要修改须产生新政策版本、记录理由并重新测量，不能掩盖已见回归。
4. 执行 `run --scope first-baseline` 与无 `--baseline` 的 compare。正确性、必需证据、已校准绝对预算均通过后，报告才可作为对应环境/范围的首个已验收基线；它仍没有 A/B 升级回归结论。
5. 后续升级以该已验收报告作为 A，同机交替测 A/B，并分别执行 runtime、full-stack。旧基线没有对应 workload 数据时补测 A，不能复用不同负载成绩。

有已验收 A 时对同一个 A 重放校准。在观察候选 B 结果之前冻结政策、顺序 seed 与门槛。calibrate 输出不自动获得批准，compare 校验其冻结引用与 A/A 证据。绝对预算和校准缺失、不可比或结果仍受噪声影响时结论为 unverified，不能以未检测出差异冒充通过。

## 固定负载与采样

完整首轮矩阵如下；常规升级可按变更风险冻结子集与省略原因。基础代表项为 idle-30/output-30、detached-30、projects-27 和所有暖路径；终端输入/渲染、协议、持久化或资源管理变化，或代表项回归，追加相应梯度、clients-size、churn-leak；跨兼容边界或系统性问题重跑完整矩阵。省略项保持未验证。

| workload ID | 固定输入与操作 |
| --- | --- |
| `idle-1`、`idle-10`、`idle-30` | 相应数量无输出合成终端，一个 client，各自独立 run |
| `output-1`、`output-10`、`output-30` | 同规模，一个 client；每终端 ASCII 每行 128 bytes（含 LF）×512 lines/s×300 s=153,600 行、19,660,800 bytes；固定 seed、绝对单调时钟节拍 |
| `projects-27` | 3 project×3 checkout/worktree×3 终端=27；固定 enter/open/focus 序列，覆盖100次重复、10次并发及用途复用零输入 |
| `detached-30` | 30 终端分别 idle/output，全部 client detach 后完整测300秒，再 attach；producer/原任务身份保持可验证 |
| `clients-size` | 两个 client 为120×40、80×24；每10秒按冻结序列resize/focus，30轮，每轮由两个UI的固定nonce各自确认尺寸控制；detach由detached-30及churn完整验证；记录共享焦点和尺寸规则 |
| `churn-leak` | 固定存量27终端，额外终端创建/关闭300次、client attach/detach300次；每50次回到同存量静置60秒，结束再观察30分钟，尾部最后60个1Hz RSS取median作为第7个斜率/对象/进程/FD检查点 |

每 workload 三个独立 batch，同机按预先冻结 seed 交替 A/B 顺序。每 batch 预热60秒、测量300秒，churn 的检查点/30分钟尾部观察另计。输出负载在测量窗口按每终端目标计数，记录实际 lines/bytes、耗时、背压与 producer CPU；producer 未达目标、丢样、负载干扰或组归属不完整影响必要指标时，该 run 为 invalid，不能以较少输出换低 CPU。固定 bytes 排空耗时可另列，不能替代速率负载。CJK/宽字符是独立正确性 fixture，不混入 ASCII 吞吐比较。

latency 从 runner 发起到可核实完成，以单调高精度时钟计端到端耗时，包含 CLI/runner 成本。分别记录冷 server→就绪、client attach→可收合成输入、暖 enter→确认 focus、暖 open 复用→确认 focus、新 role→launcher/producer 握手。每个暖路径每 batch 至少200独立样本，三 batch 至少600；报告 n、median、nearest-rank p95、min/max。冷启动每 batch 30次只报 median/range；要报 p95 必须每 batch 至少200。复用中的终端不接受计时哨兵输入。

| 指标 | 必需性与口径 |
| --- | --- |
| 正确性 | 必需；错误目标、额外输入/执行、非授权新增、任务退出、权限/所有权退步零容忍。覆盖 checkout、上下文/冷恢复、2/10并发、响应丢失/超时、移动/关闭/ID复用与新server、注入路径、断连与隔离；原生 SSH/输入/剪贴板另授权 |
| latency | 所选 workload 的相应路径必需；分 batch 汇总，不以5次采样计算 p95 |
| CPU | 必需；user+system 增量 core-seconds、core-seconds/实际 wall-second，output另报 core-seconds/MiB；server、Herdr辅助进程、client、producer分项和固定汇总组，防 PID 复用并覆盖短命进程 |
| RSS | 必需；每秒采样，server+Herdr辅助进程合计峰值、稳定窗 median/p95；client/producer另列。注明共享页重复、采样漏短峰限制，不在候选间换工具 |
| producer、对象/进程/FD | 输出计数及清理正确性必需；churn 在同存量检查点比较对象、FD、进程及RSS斜率，不能以单次高水位断言泄漏 |
| wakeup、PSS | 可选，同工具同定义；不可用为 null+reason、环境不足未验证。context switches不能改名wakeup，不为采集扩大权限 |

CPU/RSS缺失或不可比使该必要范围未验证；optional 缺测不自动阻塞其他充分证据支持的范围。每条原生正确性结论必须有实际行为证据，第三方进程退出0不代表通过；fake API测试不代表真实客户端通过。

## 判定、噪声与状态

正确性失败优先阻断。每项回归采用预先冻结的“同时超过相对增幅与绝对增量”规则；另独立应用绝对预算，任何超限不得因 A 同样差而通过。近零 A 使用事前声明的绝对规则，不能事后换分母。具体预算数值由政策校准批准，本契约不伪造机器成绩或已接受门槛。churn 的重复残留对象/进程、超噪声包络的持续增长阻止通过。

三 batch 均落在噪声包络支持的结论内才可稳定判定。批间分歧或回归触发后保留首轮，按预注册方法排查并完整重复三 batch；不删除难看样本或只选最好一次。无法排除噪声为 unverified；可复现预算超限为 failure。跨机器只比较各自同机A/B，不直接排名绝对值。

| 维度 | 值及意义 |
| --- | --- |
| `validity` | `valid` 或 `invalid`；invalid表示producer不足/采样损坏/干扰等性能实验无效；不能掩盖本次已观察到的正确性错误 |
| `decision` | `measured`（尚未评价）、`pass`、`failure`、`unverified`；实际正确性失败优先总体failure，不能改成缺环境。必要证据缺失/未授权/噪声未解为unverified；invalid性能项只能unverified且不参与A/B，但同run正确性failure仍为failure |
| `comparison_kind` | `first-baseline`、`runtime`、`full-stack`；first-baseline的pass仅表示首轮限定验收，不表示升级回归通过 |
| `task_status` | `已完成`、`进行中`、`失败待决策`、`环境不足未验证`；有效测量不等于推广。真实failure记失败待决策；无环境/权限/工具或仅性能实验无效待重测记环境不足未验证，原因单列；已有正确性failure不能被性能invalid覆盖 |

## 隔离、清理与推广边界

run/calibrate 必须先证明临时 HOME/XDG、专用测试 server/socket、虚构checkout与专属对象、非生产配置、网络阻断/允许范围、原始日志所有权和哨兵不变。无法证明则在启动第三方宿主前退出4/5。默认 pytest只测fake host、解析、统计、schema、错误和误判路径；native/SSH/Avalon/Agent/账号/模型调用各自另获明确授权，runner标志不扩大授权。

只清理manifest记录且重新确认属于本轮的合成对象；不按全局名字、PID或最近焦点批量关闭，不终止已有server/任务。操作结果不明先只读对账，保留pending与证据，不重放创建、输入或关闭。未修改的官方工具和公开API是唯一宿主接缝。

通过报告只提供决策证据，不授权canary或生产切换。后续显式推广只影响未来新工作；旧server、长任务和状态保留。分别验证磁盘client/运行server配对、受管配置rollback、native状态格式/副本及程序选择，不能假定旧版可读新版状态，不把布局恢复称为进程恢复。发现设计前提失效、并发/状态语义不明、需扩范围或两种有效尝试仍失败，交回主代理决策。

## Paired upgrade collection

主代理在实施中批准最小接口细化：runtime/full-stack 的run必须另传 `--paired-output FILE`，一次原生执行按冻结seed为每workload/mode/batch选择AB或BA顺序，同机顺序执行双方，两个报告共同保存paired_run_id、冻结/实际顺序与单调窗口。`--output`对应--subject，paired-output对应另一subject。first-baseline/calibrate拒绝该参数，不制造旧版。两个输出路径先检查为不同新文件；任一落盘失败保留已有证据并报4/6，不删除或覆盖。compare必须核对配对身份与顺序，缺证不能升级PASS。先前已接受baseline收据与本次A测量分开；本次A本身可为measured，但须提供先前对应身份的接受报告及摘要，不能要求本次A先通过本次A/B形成循环。

## Diagnostic subset and origin identity refinement

`estimate --manifest FILE` is offline and reports the complete fixed-window lower bound (18492 seconds per subject including barriers, excluding setup and operations). `run --case WORKLOAD:MODE --batch 1|2|3 --allow-incomplete-cpu` is an explicit first-baseline diagnostic subset; it retains the frozen case's full warmup/measurement windows. It always produces partial/invalid evidence and cannot create an accepted baseline or replace full A/A/A-B. Only this combination may observe under a pending policy; the report keeps that policy and an unverified pending-policy-diagnostic record. Full runs/calibrate continue to require frozen approved budgets.

Rules and disabled integrations may be identified by explicit origin fingerprints, rather than pretending the public API exports effective rule bytes. A builtin-origin-fingerprint binds the exact official asset to the canonical public server agent-manifest source list; a disabled-origin-fingerprint binds asset/configuration and all audited public integration-status targets. Cached/local sources, installed integrations, missing originals or mismatched kind/digest remain unverified. Private raw replies and reproducible digests are required; the fingerprint is not a raw rules-content hash.

The Linux runner's procfs polling does not prove complete short-lived CPU accounting. Missing complete user+system coverage remains unverified; perf task-clock is a distinct clock and cannot satisfy CPU budgets. Native preflight stops before hosts unless incomplete observation was explicitly chosen. The optional same-UID user/network namespace helper must preserve the core socket ancestor protections; unmapped trusted root, unsafe socket pathname length or unavailable isolation fails before workload execution. No additional socket capability, supervisor daemon or accounting service is implied.

For the trusted fixed synthetic fixture, an explicitly authorized run may instead
select `--offline-sockets` (mutually exclusive with `--isolated-netns`). Its fixed
helper uses installed libseccomp and no_new_privs to deny non-AF_UNIX
socket/socketpair creation and io_uring_setup, closes extra inherited descriptors,
and rejects non-Unix socket stdio. It retains the caller UID/GID and protected root
ownership view. Actual kernel state, denied IPv4/IPv6 creation, working Unix IPC
and safe descriptors are checked again before each case. Private 0600 proofs bind
the helper digest, subject and case; offline verification checks their originals.
This is a socket policy for the fixture, not a general sandbox or state-only Agent
interface. It does not satisfy missing CPU coverage or relax partial/policy gates.

## Native proof continuation

`--cpuacct-delegation FILE`使用本轮管理员委派的四个空组，统计完整user+system；管理员准备/空组清理是显式独立操作，不由日常入口执行。CPU窗口301快照绑定前后成员和PID/starttime、固定50ms采集容差；平均核数以实际快照中点wall-second计算。缺委派时仅显式不完整观察可继续，partial始终无效，不能建立基线。

成员快照每次从原固定role目录FD新开只读cgroup.procs，核验与原pin相同dev/ino、owner/0600、regular及cgroup filesystem，严格读取后关闭，不能以旧FD pread/seek作为fresh证明。原18个持久FD、CPU counter路径及严格PID/starttime逻辑保留；临时FD须在spawn/离线descriptor检查前关闭，不增加白名单。正常server.wait返回后，最多5秒等server/client/producer组为空，普通非空可等待，身份/权限/格式错误立即失败；不重试异常，不移动或终止进程，下一case原members门禁不变。此等待在测量窗口之外，不缩短负载。

原生尺寸证明只适用于本轮已审核的干净HOME/默认几何/单pane/primary screen：120×40和80×24外层PTY，对应surface94×39和54×23、producer PTY93×39和53×23。公式由官方0.9.5的client surface、pane borders及scrollbar实现核对；其他配置/版本若不满足观测关系则保留未验证，不用放宽比较解决。`pane.layout`是公开只读CLI，API focus本身不能证明某个UI获得尺寸控制；只有该UI的本轮nonce实际进入已确认record producer，才能与真实PTY及布局关联。record可在waiting/warmup/measure/record阶段读固定nonce，其他模式不读stdin；不接受命令或保存任意文本。

每batch保存60个measure geometry帧及200个attach-ready帧的私有原件，公开evidence仅给摘要文件名引用。attach原件包含attach_start_ns/attach_end_ns及未改写的helper frame，可重算全部样本和最近秩p95。CPU/geometry/attach均须核验原件、source与窗口；修改report布尔值不能补足证明。measurement_tool摘要覆盖runner/cpuacct/geometry模块，fixture另绑定producer。

correctness_cases按本次原生benchmark真正执行的行为身份冻结，不能把隔离fault-injection测试标成原生通过。响应丢失、ID复用、冷恢复等协议风险由同源码的隔离检查及独立原生核心矩阵分别记录；首基线资格须联审这些收据、适用实体客户端与性能报告。性能report中的first-baseline结论只适用于已声明的矩阵/环境，不单独授予生产切换或其他层通过。


The initial offline reexec still requires no inherited nonstdio descriptors.
Repeated CPU-enabled proofs may retain only all 18 identity-checked,
non-inheritable cgroup descriptors; unknown live descriptors fail without being
closed or reopened. UI nonce input waits for raw mode under the same five-second
deadline. Safe empty receipts wait for their first write; malformed nonempty
content and ownership failures do not become valid. Each geometry round explicitly
focuses workspace/tab/pane, resizes both clients, drains PTYs for 250 ms, then checks
its first nonce and exact native layout. That pause remains inside the 300-second
window; attach timing includes all startup/raw-mode wait.


Happy-path UI teardown uses only fixed native C-x+d on an owned, raw-mode PTY.
The helper duplicates and pins the caller's master for the operation, checks the
owned PID/starttime and waits for exit 0 under one five-second deadline, then
closes its duplicate. The caller closes its original master only after success.
No signal, kill, shell input or alternate exit code is a success fallback. Active
clients detach before the owned server stops. Failure cleanup preserves actual
nonzero exits and original evidence. Attach latency excludes subsequent detach.


Raw mode alone is insufficient for fresh-client readiness. Record fixtures emit
only a fixed `RBREADY:` marker followed by the 32-hex run ID at initialization
and after a valid nonce receipt, so it remains visible after echoed test input.
Record UI attach waits for this marker in that owned client's first frame before
returning. The bounded output observer retains at most 39 trailing bytes and
never records terminal text. The same five-second wait limit and PID/PTY guards
apply. Attach timing includes this wait, and the first nonce must still succeed;
marker recognition alone is never acceptance evidence. Idle/output emission and
their clocks remain unchanged. Calibration must bind the revised fixture digest.

专用case正常结束时，在正常detach所有自有UI后，fresh pane.list必须与本轮owned全部pane_id/terminal_id/workspace_id三元组集合完全一致，且非空、无重复/缺字段，才可经固定socket一次调用官方server stop。不跨workspace逐pane清空，不关闭confirm_close。未知/缺失/替换或操作结果不明时保留现场，不重试；进程退出及四空组后验仍必需。

## 2026-10-20仅本轮的校准接受例外

用户明确接受原校准report的唯一detached-30/output/batch1/warmup实例少计1行/128字节，经独立复核用于校准；不把该事后例外伪装为事前规则。原报告/计数/invalid及严格默认工具均保留。例外须有具体批准、原report与原件SHA、唯一selector、同run/pane/PID、正式measure计数和无重叠CPU窗口证据；其他warmup/measure、所有必需指标/预算/三batch/原件/正确性/UI均不能豁免。budget、regression及由原数据计算的noise不变。

测量runner、三个schema及原校准manifest不改；本次用仓库外一次性审阅器生成独立接受收据和冻结policy，在首基线compare前重新核验显式例外及原件，再调用原公开Python compare校准验证参数，保存schema合法comparison和独立provenance。裸CLI仍拒绝invalid校准引用，不将其输出谎报PASS；独立review JSON本身也不是未来baseline acceptance。首基线候选仍必须严格valid且所有必需门槛通过；例外不适用于后续候选，不自动批准生产入口。

## Exact target-main metadata refresh for this first baseline

长校准期间共享main前进时，不改原校准manifest/report或共享Git引用。若feature未合并/rebase且实际受测输入全部未变，允许另建首基线manifest，仅改变manifest_id的明确后缀、source.target_main和自身digest。独立复核必须以原manifest的deepcopy重建新manifest并严格相等，原校准按原manifest、候选报告按新manifest分别validate_references和核验原件；policy及校准噪声原样不变。底层verify_calibrations没有检查manifest绑定不能当作该证明。完整首基线仍须严格valid、正式/预热输出精确、全部矩阵/CPU/正确性/指标/预算通过，才可调用原compare公开校准验证参数并记录双manifest摘要和独立provenance。

此限定只处理当前首基线的目标引用元数据；candidate commit/source/lock/asset/subject/config/rules/integration、负载/采样、隔离root/private records/sentinel任何改变均拒绝沿用。结果不证明合入新main后的兼容性，也不授权merge/rebase/生产入口切换。原失败、原manifest和原报告保持不变。
