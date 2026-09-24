> 审查修复当前35/36：功能修复与针对性回归、二次复核已完成，6.11等待最终完整报告。详见包内docs/reviews/2026-09-15.md。

> 2026-09-15：审查发现的问题正在修复，以下完成报告作为历史快照保留。当前源码须重新验收。

# TK-R2 当前进度

**36/36 项实施任务完成。** 当前功能范围已实现并通过完整发布验收；没有新增产品范围或以特定品牌账号作为完成条件。

正式入口：[proposal](proposal.md) → [design](design.md) / [config-contract](config-contract.md) → [specs](specs) → [tasks](tasks.md)。验收依据：[test-plan](test-plan.md) / [acceptance-cases](acceptance-cases.csv)。静态计划中的 planned 保留为规范定义，实际执行状态以以下报告及检查点为准。

## 最终发布证据

- 完整隔离运行：`2026-09-14T15-30-22-801Z`，`--report --release` 退出0。
- **949/949 测试通过，23,077 次断言；零失败、取消或跳过。**
- **38组 AC、300个命名变体全部有有效证据，142个当前 Scenario 无缺口。** 检查点收录331条实际证据，部分变体有多个独立观察。
- source：`cedc9969484ac6174fc0f40ad124e503bd39d12ae6f203489623139adb59669e`。
- plan：`b2d427b91257fda4b0cd244acd823ec088a06b39a2dc1fb16a952aef12b2e547`。
- typecheck、静态计划和 OpenSpec strict validation 通过；19份当前规范与测试快照、20份历史文件逐字一致。
- `evidence-checkpoint.ts` 已核验原始执行/发现记录、TAP、工件和当前源码/计划，写入唯一机器检查点，`ready=true`。

[完整报告](../../../pi/packages/task-keeper/test-results/2026-09-14T15-30-22-801Z/report.json) · [原始TAP](../../../pi/packages/task-keeper/test-results/2026-09-14T15-30-22-801Z/tests.tap) · [机器检查点](../../../pi/packages/task-keeper/docs/testing/runtime-progress.json) · [使用说明](../../../pi/packages/task-keeper/README.md)

## 已交付功能

| 工作组 | 完成情况 |
|---|---|
| 当前计划与报告 | 新旧规范隔离、语义/hash检查、逐AC工件和负向报告控制 |
| 配置与兼容 | config v7、v6只读迁移预览、独立开关、可信参数限制；cascade从新启用流程移除 |
| 通用恢复 | 当前Pi模型、全局/provider/model策略、小时级退避、独立共享floor、期限与取消/重启对账 |
| 任务统计 | Store v3、父子及辅助usage、跨轮次/模型归属、幂等/修订/冲突、实际/估算/未知费用、人工比较和历史重估 |
| 第二视角 | 独立只读B、A唯一写入、finding版本/举证/修订、真实重验、0/1/2交换边界、预算/配额/取消/重启、必要审查精确复用 |
| Pi内定时与模型选择 | 一次性计划、时段/期限/资源准入、未来恢复/错过暂停、显式resume；默认手动、可选时段/历史成本选择 |
| 保留核心及组合 | 原生start/continue/verify各C0–C5、共享资源与未知writer、根验收与证据、隔离同步、四条组合流程、八个有效负向控制 |

## 支持范围与历史

认证运行组合限定 Linux / Node 24.1.0 / Pi 0.84.4 / 固定补丁的 pi-subagents 0.63.0，以及 direct 的 openai-completions 请求路径。具体供应商服务未做实网测试，不能据此宣称账号/服务已认证；Qwen只是错误fixture来源。

本轮没有付费模型请求，没有修改真实Pi home，没有部署、提交或自动归档。配置启用和状态维护步骤见包内README。退出Pi后运行、周期任务、价格抓取、付费探索、在线Advisor和大型策略效用实验不属于本版。

原822/822基线、旧71/76及旧层级/矩阵缺口在[历史快照](history/2026-09-14-p0-p3/implementation-progress.md)保留；没有将其改成新版通过。当前报告的legacy缺口是历史统计，不作为TK-R2的新分母。

本轮失败原件保留：15:19候选为937/948，9个旧测试上下文需明确区分hasUI=false，另2个AC观察位置/错误字段已修正并针对性通过；15:26候选为947/948，并发运行期间100次verifier压力夹具超过35秒观察窗口。最终运行未放宽该窗口，同一压力检查通过。补齐规范要求的maxExchanges=1后，最终949项在同一源码快照全部通过。
