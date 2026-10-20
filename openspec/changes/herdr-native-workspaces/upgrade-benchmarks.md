# Herdr 升级与可重复基准计划

本文是后续实施与执行计划，不提供已存在的 runner 命令，也不构成原生运行授权。本轮只编写文档；没有启动 Herdr、真实 Agent 或基准进程，没有生产基线或性能成绩。接口依据、已知边界和原生验收步骤分别见 [evidence.md](evidence.md)、[design.md](design.md) 和 [acceptance.md](acceptance.md)。

## 候选选择与基线

每次首次安装或升级，都显式核对官方最新 stable release，记录核对日期、release URL、tag、完整提交、目标平台 asset 名称、来源 URL、官方校验材料及实际下载文件 SHA256。2026-10-18 核对的本轮候选为 v0.9.5；它不是永久固定目标。后续若最新 stable 改变，重新审查差异后选择候选；不默认采用预览版，不在 `work` 中硬编码版本必须等于 0.9.5。

公开接口、协议、配置及 capability 的可用性以选定 release 的 tagged 证据和实际验证为准。磁盘 binary、实际 server、加载配置与检测规则分别记录身份；版本号相同不能替代资产摘要或 server 身份证明。未知或未验证版本可以在独立环境试验，不能自动接管生产。普通工作入口不联网检查、下载、后台升级或替换运行包，不通过终止旧 server 消除版本差异。

本机已观察到的 0.8.0 只有元信息证据，不是“已通过”的比较基线。首次候选完成正确性、资源校准及授权的 SSH 验收后，才能冻结首个已验收生产基线。首轮性能只能记录绝对测量及重复噪声，不能捏造旧版 A/B 结论。以后以该生产基线 A 对比升级候选 B；保留 A 的 binary、配置、rules、fixture 和报告摘要以便重放。

## 隔离与比较条件

每个 candidate、每个 batch 使用独立的临时 HOME、XDG 配置/数据/状态/缓存/runtime 位置、socket、server/session、日志与持久化目录。先针对该 release 核实其公开隔离方法，确认 named session 是否仍共享全局配置、manifest、集成或状态。仅更换 session 名或 HOME 不算隔离证明；不能证明时停止原生启动，记录失败待决策。不得连接现有 server 或读取真实认证、session、终端 buffer 来验证隔离。

同机 A/B 固定 OS/内核与平台类别、终端及 SSH 客户端版本、shell 类别、TERM/COLORTERM、locale、字体/渲染选项、初始 120×40 cols/rows、resize 序列、配置、PTY 数、输出速率和后台负载条件。报告只记录非识别性的环境类别与必要工具链事实，不记录主机名或私人路径。依赖锁、Rotom 源摘要、配置和公开 fixture 摘要也必须匹配。测量工具及采样开销保持一致，缺失工具不得换成不可比指标后宣布通过。

分别建立两条比较，不能混算：

| 比较 | 固定项与目的 | 不可比时的处理 |
| --- | --- | --- |
| runtime A/B | 固定配置和同一组检测 rules/manifest/集成，比较 binary 本身 | 新版不支持同规则时，记录不可比原因；另列完整新版结果，不能归因为 runtime 回归或改善 |
| 完整新版 A/B | A 使用已验收组合，B 使用新版计划部署的 rules/manifest/集成；记录每项来源、版本、摘要和差异 | 差异作为组合升级单独验收，不能声称固定规则比较通过 |

若公开接口无法固定 rules，不通过修改宿主或私有接口实现；将此限制交回设计决策。默认关闭恢复、声音、toast、后台版本/manifest 检查和实验 history；是否实际生效须有独立证据。不得删除私人缓存或覆盖来制造固定条件。

主性能 workload 使用无账号、无 Agent 的合成程序。真实 Agent、Avalon、网络和模型调用只进入另行授权的兼容性报告；其 CPU、RSS、网络等待或模型成本不能计作复用器开销。synthetic producer 本身也单独计量，Herdr server、辅助子进程、client 与 producer 使用可核实的进程清单分组；不能简单把整个进程树都算给 Herdr。

## 可重放 fixture 与执行契约

将来实施时，为 fixture、workload、测量方法和报告 schema 各设版本号，保存源码摘要及确定性 seed。公开 fixture 只生成虚构仓库 `project-a`、`project-b`、`project-c`，各含主 checkout 与两个 linked worktree，使用固定假提交和假文件。别名路径、中文和空格路径位于测试根内；报告用逻辑标签映射对象，不输出测试根绝对路径。fixture 不复制业务 checkout、认证或会话正文，也不采集真实屏幕、终端 buffer 或剪贴板。

执行前冻结 manifest，包含每个步骤的实际 argv 数组、cwd 逻辑标签、允许的非秘密环境变量、预期退出码/副作用、就绪条件、操作超时、采样窗口及清理所有权。下文是 workload 参数，实际 Herdr argv 必须在实施时按候选公开接口生成并随报告保存，不能将猜测命令当成已验证入口。外层 argv 与底层 shell 编码边界分开记录。完成判据使用合成程序握手/计数、进程身份及原生只读查询，不依赖 UI 图标或 Agent 状态。

合成程序至少提供三种模式：无输出等待；按固定字节生成 ASCII 行；只记录测试输入字节、窗口尺寸及单调时钟事件。所有日志只含合成数据。输出模式固定 seed、每行 128 bytes（含 LF）、每秒 512 行、持续 300 秒，即每终端 19,660,800 bytes；采用绝对单调时钟节拍，记录实际发出行数、bytes、耗时与背压。达不到目标速率的 run 无效，不能拿较少输出换取较低 CPU。CJK/宽字符属于独立正确性 fixture，不能混入 ASCII 吞吐量比较。

清理只作用于 manifest 中本轮创建且重新确认身份的测试对象。默认离线测试使用假子进程、临时 HOME/XDG、网络阻断与文件哨兵，不启动任何第三方宿主。原生 runner 必须显式 opt-in，先确认隔离，再启动专用原生 server；本计划不授权执行。

## 正确性门槛

以下错误零容忍，任一失败阻止切换默认入口；性能改善和安全更新的紧迫性均不能豁免错误目标、输入注入、任务退出或权限退步。每个场景先有离线契约测试，再在获授权的独立候选环境验证实际公开行为。详细交互步骤沿用 [acceptance.md](acceptance.md)，每个 run 保存预期、观察、退出码及脱敏证据引用。

| 场景 | 必须成立的不变量 |
| --- | --- |
| checkout 身份 | 子目录与 symlink 解析到同一 checkout realpath；同仓库不同 worktree 保持独立，切分支和 shell `cd` 不改项目身份；不按动态 cwd、标题或 common Git directory 合并 |
| 重复与并发 | 重复 enter/open 只复用已证明对象；同时 2、10 个调用不会静默重复或错归属；并发原生操作不受本地锁保护时也须检测冲突，不宣称全局事务 |
| stale、move、close | 过期环境、ID 复用、终端/项目关闭、pane 移动、另一 client 切焦点后，重新查询 server 与成员关系；未知目标失败，不操作另一终端 |
| 结果不明 | 覆盖发送前超时、创建成功但响应丢失、查询超时及断连；先只读对账，不盲目重试创建、输入或关闭；无法确定时明确失败/冲突 |
| cold role unknown | 冷恢复用途身份未知时默认 `work open ROLE` 退出 4，无创建、接管或关闭；显式 `--new` 可建立新 primary，保留旧布局且不解除其他用途未知状态 |
| 复用与 shell launcher | 复用只聚焦，合成输入记录器观察到零启动文本/控制字符；新拥有终端才可启动，单处逐参数 shell 编码覆盖空格、中文、单双引号、美元、反引号，换行按契约拒绝；无 eval，无哨兵副作用 |
| 输入与 resize | `C-x` 字面输入、组合键、Shift+Enter、CJK 宽度、快速 resize 后字节与尺寸正确，无丢字/错位；真实终端证据与纯 PTY 证据分开 |
| OSC 52 | 只写已知合成文本，由人到测试文本框确认；不发读取查询，不读取原剪贴板，直连与嵌套链路分别记录 |
| 共享 focus | 多客户端对同 server 的全局焦点行为如实记录；调用终端身份不得被全局活动项替代，不承诺独立客户端项目焦点 |
| disconnect 存活 | 分别测 client detach、SSH 中断、启动 shell 退出、专用 server 退出；以合成进程身份/计数区分原进程存活与重启，不自动重跑任务 |
| 隔离与配置 | 非 Git 输入在任何 server 写操作前退出 2；未连接生产 socket，哨兵不变；未知配置字段失败，账号、私人状态、权限与所有权不扩张 |

## 性能矩阵与采样

按变更范围选择测试层级，首次建立基线运行完整矩阵；日常启动不运行基准，也不创建定时任务。常规稳定版升级先完成全部受影响正确性检查，再运行规模代表项：30 终端 idle/output、所有 client detach、27 终端项目操作和暖路径延迟。终端渲染/输入、协议、持久化、进程或内存管理有变化，或代表项出现回归时，追加相应规模梯度、多客户端和 churn/leak 项；首轮、跨兼容边界或系统性异常执行完整矩阵。报告冻结并列明本次选择及省略原因，未执行项保持未验证，不能把代表项通过写成整个矩阵通过。最后通过版本没有对应 workload 数据时须补测同机 A，不拿不同 workload 的旧报告直接比较。

每个 workload 各做 3 个独立 batch；同机交替 A/B 顺序，按预先冻结 seed 决定先后，避免始终先测 A。每 batch 先预热 60 秒，再测 300 秒；冷启动另测，不将其预热成本藏入暖路径。样本不因结果难看被删，异常值须保留并注明；负载干扰、丢样或 producer 未达标则整次 run 标无效并重做，不记 PASS。

| Workload ID | 固定操作与规模 | 重点观察 |
| --- | --- | --- |
| idle-1/10/30 | 1、10、30 个无输出合成终端，1 client；各独立 run | idle CPU、RSS、wakeup、随终端数增长 |
| output-1/10/30 | 同样终端规模，按上述固定 bytes/line/rate/duration 输出；不受终端速度驱动无限循环 | 实际吞吐、背压、CPU、RSS、client 渲染成本；固定总 bytes 的排空耗时另列 |
| projects-27 | 3 project × 3 checkout/worktree × 3 终端，共 27；固定 enter/open/focus 序列 | 项目与用途正确性、规模下暖路径、资源；20–30 终端范围的固定代表值 |
| detached-30 | 30 个终端；分别 idle/output，所有 client detach 后仍采样 300 秒，再 attach | server/producer 存活、无 client 时 CPU/输出处理、资源回收；不把 client 消失误记为 server 节省 |
| clients-size | 2 client，120×40 与 80×24；每 10 秒按固定序列 resize/focus/detach，重复 30 次 | 尺寸策略、共享 focus、client 与 server 资源及输入正确性 |
| churn/leak | 固定存量 27 终端，创建/关闭额外合成终端 300 次、attach/detach 300 次；每 50 次回到相同存量静置 60 秒；结束再观察 30 分钟 | 残留进程、对象/FD 数、RSS/wakeup 阶梯增长及稳定窗口斜率 |

latency 使用单调高精度时钟，测 runner 发起到可核实完成的端到端时间，记录 runner/CLI 开销；不只计一次 socket 往返。分开记录冷 server 启动→就绪、client attach→可收合成输入、暖 `enter` 已有项目→确认 focus、暖 `open` 已有 role→确认 focus、创建新 role→握手。每个暖路径每 batch 至少 200 个独立样本，报告 n、median、nearest-rank p95、min/max；3 batch 共至少 600 个样本，不用 5 次测量计算 p95。冷启动每 batch 30 次，报告 n、median/range，若要给冷启动 p95，则将每 batch 扩到至少 200 次。主动创建只用独立测试对象，不在活跃 shell 注入计时哨兵。

CPU 以各组 user+system CPU 增量 core-seconds 报告，并给出 `core-seconds / wall-seconds`（1.0 表示占满一个核），输出 workload 同时报 `core-seconds / MiB`。报告 server 本体、Herdr 自有辅助子进程、client、producer 分项与对应汇总，固定组定义；真实 Agent 成本不得进入主对比。采样窗口使用实际单调 wall 时间，不能用瞬时 `%CPU` 峰值代替平均占用。

RSS 每秒采样，报告 server+Herdr 自有辅助子进程之和的峰值、稳定窗口 median/p95，client 与 producer 另列；记录共享页可能重复计数的限制，若有 PSS 可附报但不能替换主口径。峰值采样可能漏短峰，注明分辨率；候选间不能换工具。wakeup 使用同工具同定义每秒计数；工具不支持时该指标标环境不足未验证，不能把 voluntary context switches 直接改名为 wakeup。同步记录 FD、测试终端数、server 自有进程数及 churn 同存量检查点；“泄漏”要求重复增长证据，不以短窗口 RSS 高水位单次断言。

正确性、选定 workload 的 latency/CPU/RSS 为推广必需项；wakeup/PSS 等附加指标在现有权限与工具允许时采集，不为测量自动扩大权限。附加项不可用须逐项标未验证，不能冒充通过，也不自动阻塞已经具备必要证据的升级。进程清单须防 PID 复用，并说明短命辅助进程的累计 CPU/峰值是否完整；若遗漏影响必需指标的可比性，该次相应测量无效。

## 预注册门槛与噪声处理

正确性零容忍。以下性能门槛只是待首轮噪声校准的候选政策，实施者须在看候选 B 结果前冻结、签入政策版本与批准记录；未校准不得记性能 PASS。校准使用已验收 A 对 A 重放、3 batch 的波动和测量开销，明确每个指标是否适用。首轮没有已验收 A 时，只建立测量和绝对预算，生产基线需首轮验收后形成。

候选门槛：对每个可比 workload 的每项指标，只有同时超过相对增幅和绝对增量才触发回归；两者任何一个未超过仍须报告实际数值。建议起点如下，数值需校准，不能被当作已接受预算：

| 指标 | 相对增幅候选 | 绝对增量候选 |
| --- | --- | --- |
| 暖路径 median / p95 | +10% / +15% | +10 ms / +20 ms |
| CPU core-seconds / wall-second | +15% | +0.02 core（300 秒为 +6 core-seconds） |
| 稳定 RSS / 峰值 RSS | +15% / +20% | +16 MiB / +32 MiB |
| idle wakeup | +20% | +5 wakeups/s |

A 接近零时相对值可能无定义，预先指定改用绝对预算并记录原因，不事后换分母。另设与相对比较独立的绝对资源/交互预算，按目标机器能力预注册；任何预算超限均需决策，不因旧版同样很差而通过。churn/leak 若存在重复可复现的未回收对象/进程，或同存量检查点 RSS 持续增长超过已校准噪声包络，也阻止通过。

3 batch 都在噪声包络内才可作稳定结论；触发回归或批间分歧时，保留首轮数据，排查负载/采样，预注册重复 3 batch，不只挑一次较好结果。无法排除噪声则记录环境不足未验证；可复现超限记失败待决策。不得看到结果后调宽政策掩盖回归。跨机器只比较各自同机 A/B 与能力类别，不把不同机器的绝对 latency/CPU/RSS 直接排名或据此通过。

## 分阶段升级与回退

1. 显式核对最新 stable；审阅 release/tag、asset/hash、许可、协议/CLI/schema、配置默认值、manifest/rules 与 integrations diff。核实官方来源，记录选择旧 stable 的具体理由；安全更新优先安排验证，但不绕过误操作阻断。
2. 将官方未修改 binary 准备到独立、版本化 staging 位置，验证摘要和平台 ABI；不覆盖运行中的可执行文件，不写私人 native state。核对磁盘 client、测试 server 身份和公开 capability，不根据版本字符串单独推断兼容。
3. 先离线契约与受影响回归，再在单独授权、隔离证明成立后执行上述原生 A/B。固定 runtime 与完整规则两条结果各有结论，缺少数据不算 PASS。
4. 取得相应显式授权后进行人工普通 SSH 直连测试，覆盖输入、resize、OSC 52 只写、多客户端、断连和启动 shell 退出。嵌套 tmux、真实 Avalon/Agent 分别列证据，不外推平台。
5. 仅将新工作作为 canary，使用新专用 server 和明确的新版本入口；保留旧 server 与旧入口运行长任务。观察期、负载范围、退出判据及操作者先约定，不自动迁移旧进程。
6. canary 与门槛通过后，由显式操作切换未来新工作的默认入口，记录切换配置及撤销方法。不结束旧 server；现有工作自然结束，禁止默认 live handoff，不把新入口当作迁移了已运行进程。

升级前逐项确认旧 client→旧 server、新 client→新 server，以及是否允许跨版本 client/server 配对；未证明协议兼容就拒绝跨配对，不能用“同一 socket 能连上”作证明。native snapshot/state 格式及 migration 必须独立审查；旧 binary 不得直接读取新版 native state。恢复默认关闭时仍需保留原有状态边界。

需要验证 snapshot 兼容时，只在额外授权下使用独立快照/副本，分别保留版本与摘要，禁止对唯一原件尝试迁移。真实私人备份位于公开仓库外，目录 0700、文件 0600，不公开其路径或正文；合成测试优先用合成状态。不得将认证或会话拷入公开 fixture。回退使用旧版独立 HOME/XDG/socket/server 和对应旧配置/状态副本；切回旧入口只影响未来启动，不能迁移新 server 中的运行进程。无法无损降级时保留新 server 存量任务并报告边界，不结束任务来伪造回退成功。termcfg 配置 rollback 与 native state/binary 降级是不同操作，还须按 [design.md](design.md) 的旧状态/pending 边界验证。

## 后续实施交接与报告模板

后续任务可提议新增显式 opt-in runner（例如 `tools/bench/herdr_upgrade.py`）、合成 fixture（例如 `tests/fixtures/herdr-bench/v1/`）、机器可读结果 JSON Schema（例如 `schemas/herdr-benchmark-report.schema.json`）与报告模板（例如 `docs/templates/herdr-upgrade-report.md`）。这些只是建议路径，目前没有这些 runner、schema 或命令；实现时先确定文件所有权和接口，再补实际可执行 argv。默认 pytest 仅验证 runner 的假进程/解析/统计及失败路径，不隐式转成原生 bench。

报告 schema 应要求未知字段失败、缺失指标显式 null+reason、测量单位及有效样本数，拒绝将 null 当零。每项结果绑定候选与工作树源摘要/最终 commit、目标 main、依赖锁、fixture/workload/政策/schema 版本；版本发生变化需重新评估证据。报告模板至少包括：

| 字段组 | 必填内容 |
| --- | --- |
| candidate/baseline | release/tag/commit、asset URL/摘要、client 与实际 server 身份、基线是否已验收；无基线写明原因 |
| effective inputs | 配置/rules/manifest/集成来源及摘要、固定 runtime 或完整组合、fixture seed/摘要、平台与工具类别、cols/rows、采样工具与定义 |
| execution | 授权范围引用、隔离证明、每步实际 argv 数组与逻辑 cwd、退出码、单调开始/结束与 wall、就绪判据、batch 顺序、有效性/重试原因 |
| correctness | case ID、预期/观察、对象与进程的脱敏对应、失败副作用、四种状态、证据引用 |
| measurements | 每 batch 原始合成数值、n、median/p95 算法、CPU/RSS/wakeup/FD 分组、实际 bytes/lines、漏样/背压、噪声与绝对/相对门槛判定 |
| decision | 基线/候选/生产适用范围、阻断项与未验证项、人工接受的精确范围、canary 与默认入口切换/撤销记录 |

公开报告只保存合成数值与脱敏结论；原始日志如含私人信息必须保持在私人存储并只引用脱敏证据编号。没有数据、工具不可用、未授权或不具备平台时记录环境不足未验证，不写零、不写 PASS。实际失败不可转记成环境不足；需要设计取舍、并发语义不明、两种有效尝试后仍失败或范围扩大时交回主代理。

| 工作项 | 当前状态 | 当前证据或下一步 |
| --- | --- | --- |
| 升级/基准方案 | 已完成 | 本文；文档检查证据由交付记录提供 |
| runner、fixture、schema 和报告模板实现 | 环境不足未验证 | 本轮不实施运行时代码；未来任务确定可写范围和验收命令 |
| 原生隔离证明、正确性与资源测量 | 环境不足未验证 | 未执行，需候选运行包、实施与单独显式授权 |
| A/A 校准、性能门槛批准与生产基线 | 环境不足未验证 | 无已验收生产基线；候选数值不是已校准政策 |
| 人工 SSH、canary 与默认入口切换 | 环境不足未验证 | 未执行，需前序门槛与相应显式授权 |

执行时另外使用“进行中”和“失败待决策”记录活动工作与真实失败；当前没有实际基准失败或成绩。任何验证后改动只重跑受影响检查，最后在稳定 diff/commit 上复核，不能把文档完成写成原生性能通过。
