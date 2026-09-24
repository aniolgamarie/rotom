# 新执行工具接手 Pi 迁移的完整 prompt

将下方内容交给本机新执行工具。它可以读取同一工作区。本轮只编写交接指令，没有启动验证或清理磁盘。

```text
请接手并继续完成rotom/agentcfg的Pi迁移，重点完成当前Linux上的剩余原生/冷重建验证、可信证据登记和交付记录。

工作目录：
/data/1/weixiaoxian.wxx/dev_tool/rotom

你是新的执行工具，可能没有之前的对话上下文。先读本文列出的仓库资料，再以真实源码、进程和报告为准恢复工作。不要从零重做，不把上一工具的总结当作已经核验的事实。

【执行方式】

上一工具因外层LoopGuard频繁中断，现改由不带该限制的新工具继续。这个变化只涉及执行任务的外层工具，不授权删除agentcfg管理的loop-guard插件，也不授权关闭被测系统的预算、权限、撤权和进程监督。

请持续执行“检查→修复→测试→核验→继续”，不在每个阶段结束时询问是否继续。耗时较长、需要设计或需要更多测试都不是新的用户决策。

只在真正缺少外部机器、live配置、出现新的需求冲突或执行权限无法解决时，记录具体阻塞并继续其他独立工作。遵守你自己的实际工具权限，不规避审批或安全限制。

【必须阅读】

1. AGENTS.md
2. specs/001-unify-pi-capabilities/spec.md、plan.md、tasks.md、quickstart.md
3. specs/001-unify-pi-capabilities/contracts/capability-matrix.md
4. specs/001-unify-pi-capabilities/contracts/evidence-and-release.md
5. docs/acceptance/pi-register-review-20260922.md
6. docs/acceptance/pi-review-32da4799-20260922.md
7. docs/acceptance/pi-final-report-ed34c4e7.md
8. docs/acceptance/pi-cold-ed34c4e7/及当前scope/证据目录
9. specs/001-unify-pi-capabilities/implementation-progress.md（按需要追溯）

较早handoff文档中的临时脚本、锁身份和进度已经过期，只能用于理解历史。

【既定需求和授权】

- model-delegate彻底替换codex-delegate；七个旧协调角色收敛为统一入口与用途模板，保留完整技能及显式高级操作。
- 保留官方Codex CLI和原生工具，不改回默认MCP工具桥或Codex分支。系统/企业/组织配置和账号边界无法核验时拒绝执行。
- macOS完整owner退出后遗留worker恢复协议、Cursor/Bun宿主下锁定Node worker绑定，均已明确要求实现，不再询问“实现还是排除”。
- 可自主完成代码修复、默认隔离测试、已授权的依赖安装/锁解析及合成服务native/cold验证。
- 默认测试必须使用临时HOME、假网络/进程/模型，不启动第三方宿主；native为独立已授权步骤，只用合成服务。
- Codex、Cursor、MCP、web、代理、终端全部选择live验收，但明确的Pi --local、专用项目和账号/服务绑定尚未准备。保持selected_optional/not-run，不借用本会话账号。
- Linux arm64、macOS arm64、macOS x86_64没有测试入口，保持未验证。
- 保留已有未提交修改、未跟踪实现、历史失败和unknown/escaped保护；不执行会丢失这些内容的reset/clean/stash等操作。
- 不删除旧运行根、旧cache或历史报告，不进行外部发布，不放宽TLS、摘要、属主、权限或终止检查。

【接手时核对的候选】

2026-09-23核对时：
lock_identity = ed34c4e717790999ae2af55db02789ee06864455c7ecdcf13cce6015aeb68323
recipe_digest = 4374fea4238f71ea575ebf24553fd1d0f9952caa74f9d312a474341c8c010b01
该recipe_digest当时与源码匹配。开始执行前重新核验，不能只看manifest里声明的字段。

旧候选包括32da4799、4c043f8f、484f07e9等，保留为历史记录，不改标签用于新候选。

上一工具自报完整mock为1839 pytest + 7 subtests、325 Node；请找到对应原始报告并核对候选、执行时间及输出，不只引用这一行数字。

【进度汇总必须先重建】

上一工具自报：
- Codex两个目标各7组通过；
- default和managed的某些重试目标完整通过，其他目标失败或部分完成；
- Cursor第一目标5组通过，第二目标2组通过；
- ReadSeek在default/Codex的若干目标通过。

这些是待核实线索，不是最终通过依据。当前仓库pi-cold-ed34c4e7归档中，已核对到的default顶层报告仍为failed：first verified/passed且有7组，第二目标target-preparation-failed。

不要沿用“41/72”“剩余31场景”的总数：
- 真正的profile只有pi-default、pi-cursor、pi-codex、pi-managed四个。
- pi-default-second、pi-managed-second是尝试目录或重试标签，不是新增profile。
- case组与组内scenario不是同一个计数单位；Task Keeper一个组内有11项场景。
- 历史失败尝试不需要全部补绿。目标是每个真实profile获得符合契约的两套独立干净目标的完整证明。

先建立实际执行清单，每行至少记录：
profile、attempt、目标物理/逻辑路径、HOME、checkout、lock/source/runtime身份、安装状态、预期case、实际case、进程状态、报告路径、缺口。

从生产native_cases()/scenarios()及需求矩阵推导预期集合，不能以现存文件数作为分母。

特别注意：核对时pi_validation_native.py已允许Cursor的readseek-tools，但pi_cold_rebuild.native_cases()仍只给default/codex加入ReadSeek。必须处理这一缺口，不能以Cursor的5/5声称该组合完整验收。若修复源码，按正式流程重新冻结候选并处理受影响证据。

【第一步：检查现有后台作业，避免重复启动】

- 前一工具被LoopGuard中断，不代表其后台子进程已停止。
- 根据运行记录核对明确归属的作业、PID出生身份、控制通道和报告进度；不要仅凭进程名或PID数字判断。
- 仍运行且身份可信的作业继续观察，不重复启动。
- 没有最终报告时，检查步骤输出、scenario进度和controller结果；不要只因汇总文件尚未生成就判定失败。
- 不读取无关账号环境，不按名字批量杀进程，不清除未知租约。
- 原挂载视图已消失时，先核对物理目录与历史逻辑路径；无法安全恢复视图就用新目标，不修改旧报告路径或保护记录来伪装恢复。

【第二步：工具链与存储】

正确工具链此前已经实测存在：
/home/weixiaoxian.wxx/.local/share/agentcfg-pi-tools/node-v24.14.0-linux-x64/bin
/home/weixiaoxian.wxx/.local/share/agentcfg-pi-tools/bun-1.4.0/bin

预期版本：Node v24.14.0、npm 11.19.1、Bun 1.4.0。
uv此前位于/home/weixiaoxian.wxx/.local/bin/uv。

在实际执行命令及其子进程中显式设置并核验工具链；不要因默认PATH指向nvm旧版本再次要求用户安装。

2026-09-23检查到的空间：/data约291GB可用、/home约23GB、/tmp约11GB。空间会变化，执行前重新测量，不把这些数字当作保证。

- 大型验收优先使用/data上的独立新卷。
- /data及/data/1不是可直接用作私人实例的可信祖先；不要chmod它们或放宽paths.py。
- 按此前已用方式，在受控bwrap视图中将新卷映射到可信逻辑路径，显式只读绑定仓库、工具链及系统依赖。
- HOME、TMPDIR、输出和大型安装树应实际落到新卷，不落入小容量宿主/tmp。
- 内层生产cold runner仍只见新目标和工具链，不挂旧runtime、旧HOME或旧下载缓存。
- locks/pi/vendor中已声明并强校验的源资产可以使用，它们是交付输入。
- 先做轻量路径/空间/工具链/只读隔离预检，再启动长作业。

【第三步：集中核查并修复真正的实现缺口】

“全部软件完成”是上一工具的自报，不能替代检查。

- 对照复核文档，确认登记器真的拒绝空集合、场景缺失/重复、超时、错误facts、跨身份以及失败的引用native报告，并保留真实格式正例和主入口测试。
- 检查macOS OWNER协议及恢复流程没有用近似实现冒充完整语义；完整替身测试与实际平台验证分开记录。缺机器的原生部分不阻塞Linux工作。
- 检查Cursor独立Node的配置、版本、沙箱可见性、派发、启动和回收；保留Cursor原有必需插件和配置。
- ReadSeek九工具必须各自实际调用并验证结果；不能只数事实布尔值或检查无isError。
- 检查T098/T106及其他任务是否仍有与事实冲突的完成说明。

需要修改的代码集中完成、定向回归通过后再冻结。不要在长验收途中继续改控制代码/schema，使报告不断失效。

源码变化时使用正式resolve_lock流程重建完整锁/vendor和身份，保持locks/dsh逐文件不变。禁止直接编辑recipe_digest“对齐”旧锁。没有源码变化时不无条件生成新锁或重跑已经匹配的完整证据。

【第四步：完成Linux有效验证】

- 优先完成Cursor ReadSeek及其他新增/修复场景的定向native，先发现接线错误。
- 对最终冻结候选，取得四profile各两个独立HOME/checkout的完整冷安装与原生证据。
- 已匹配且完整通过的profile保留，不无条件重跑。
- 失败重试使用新attempt，保留旧记录。不要把所有历史失败尝试都加入待补清单。
- 仅在既有执行器和证据契约支持可审计续跑、安装已核验且没有活动/unknown污染时复用一个目标的已完成步骤；否则建立新目标。
- 不将不同源码、不同runtime或不同目标中的零散case拼成一个目标通过。
- 不改写原始failed报告为passed；若有续跑/重试，使用新的汇总并显式引用原始来源。
- 调用生产真实执行器，不注入假native回调，不跳过未实现case。
- 注意native --case all会包含cold-rebuild，避免无意重复触发嵌套整轮重建。

运行管理：
- 使用工具支持的持久任务/session机制，记录启动命令、工作目录、日志和任务标识。
- 根据资源安排顺序或有限并行，每个目标目录唯一。
- 采用合理间隔或事件驱动观察，不频繁重复同一个查询，也不因暂时无新输出就重启作业。
- 发生错误先读取具体阶段和原始诊断，再决定修复或新尝试；不能把target-preparation-failed一概归为磁盘不足。
- 长任务耗时不是停止点；持续给用户简短、有新信息的进度。

【第五步：可信归档与正式报告】

核对完整链条：
候选输入 → 安装收据 → 顶层cold报告 → 各native报告 → 场景结果/终止证明 → EvidenceRecord → scope → 正式报告器。

- 每层lock/runtime/source/profile/platform/case必须匹配。
- SHA索引证明文件完整，不证明其内容属于同一候选；两者都要检查。
- 保存真实命令来源、时间及全部必要引用，不构造未执行过的命令或时间。
- 新报告、证据、scope使用新名称/revision，不覆盖历史。
- 正式统计由report-only/check-release产生，不能手工凑完成数。
- 10项Linux live仍未执行，不能把Linux全部91项写成passed。
- 其他平台保持not-run，不因缺机器改成not-selected。
- 已取得证据可以逐项登记；不能一份汇总复制给所有V项。

【本轮不做的动作】

- 不删除111GB旧运行根、run2、仓库cache或历史失败。
- 不调用未明确准备的真实账号与服务。
- 不进行外部发布、上传或会丢失已有工作的Git操作。

清理只能在证据、非秘密身份材料、终止证明和失败记录完成归档审计后，提交具体清单等待用户确认。它不是当前仍有安全存储可用时的前置决策。

【完成标准与最终汇报】

持续推进当前机器和既有授权内可完成的工作。只有真实外部条件才保留阻塞；不要以工作量、前一工具LoopGuard、默认PATH错误或单个分区空间不足提前结束。

最后汇报：
1. 最终候选和源码身份。
2. 原进度统计的纠正结果；按四个真实profile列出两个目标，而不是按重试目录增加profile。
3. 每个目标的实际安装、必需case、终止证明和通过/失败/未运行结果。
4. Cursor ReadSeek、九工具和Task Keeper生命周期的实际覆盖。
5. 登记器的关键正负向及主入口验证结果。
6. 正式scope统计及发布结论。
7. 真实剩余任务、外部机器/live输入及未批准清理清单。

明确区分代码修改、mock通过、native通过、live通过；未全部满足时不称完整迁移完成。
```
