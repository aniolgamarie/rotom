# 2026-09-09 第二轮实现与验收增量

最新完整运行 `2026-09-09T08-14-09-053Z`：**746 passed，0 failed/cancelled/skipped，15633条断言**。报告见[report.json](../../test-results/2026-09-09T08-14-09-053Z/report.json)。当前产品与测试源码摘要为 `6b995121a046d52f166f0847fc1a342aad68e06ac2bf0e938df247dcd83a07f1`，与完整报告一致。

| 指标 | 本轮开始 | 当前 |
|---|---:|---:|
| 完整通过测试 | 727 | 746 |
| P0–P3最低证据缺口 | 171 | 140 |
| 展开矩阵已获证据 | 123/436 | 123/436 |
| OpenSpec大项完成数 | 71/76 | 71/76 |

增加19项测试，补齐31项最低层级义务；旧最低证据没有新增缺口。剩余U18、S0、A23、P25、E65、V7、L2。展开矩阵还缺313项，与140是不同口径，不能相加。全变体和observer审核仍未完成，releaseReady=false。

## 实际实现修复

1. **额度等待的恢复入口**：新增持久quotaWaitPending。候选不变时，pause/resume或等待态重启后的恢复重新进入stage准入，保留incident、stageEnteredAt/deadline和预算，不直接沿最后备胎启动无效子执行。真实四次备胎用尽场景在旧代码中复现RUNNING/额外执行，修复后保持等待且不增加grant或请求。
2. **派发前SQLite争用**：保留lastDispatchError；仅在无本次intent、未处于事务的等待态，对真实BUSY/LOCKED延后重查，不扣次数、不释放未知资源。deadline、暂停、其它SQL错误和提交后失败分别验证。受控6.5秒写锁使旧代码九个真实Pi等待者全部BLOCKED/SQLite5；修复后九个仍WAITING_QUOTA/SQLite5，原失联许可保留，接收数仍11。
3. **模型来源披露**：adapter返回modelIdentity，回执observed项标记client_configuration、responseModel=null、serverWeights=unverified。实际SSE返回不同model或省略model时，不用请求配置补造服务端身份。fix回执、命令和工具中的标记也已验证。

## 补测与测试运行器

- 真实OS ENOENT的accepted-but-not-started；生产终止证明不足时仍保留unknown，不依赖测试观测器或错误文本释放写入。
- 工作区创建失败保留用户dirty tree；工具已改文件后取消保留部分候选、确认进程停止，不能当作已验收完成。
- 实际SDK重试中重复unknown/sent事实不退款、不重复扣费；两次真实请求用两个requestAttempt计费。未认证fetch链阻止受保护派发。
- 项目保护关闭字段在真实session reload中拒绝，既有spent/unknown预算和写入占用保留。
- native retry、流内错误、工具后限流和canary/Retry-After补充逐ID、真实接收端、跨进程账本及父输入断言。
- 68个工作流场景保留原名/ID/断言，拆为四个独立入口17/16/18/17。增加get_state就绪握手，原90秒整体及场景窗口不变。完整测试本次执行约4.2分钟，上轮约10.2分钟；这是本机这两次运行的观测，不是跨环境性能保证。

## 验证及历史失败

类型检查、OpenSpec strict、git diff --check、设计检查15项及14个设计负向控制通过。失败的完整运行2026-09-09T07-44-52-460Z和2026-09-09T07-53-23-044Z分别保留冷启动计时和多父等待中断事实，未作为成功报告。后者当时没有底层错误细节，不能事后证明原始异常类型；后续用真实写锁确定性复现并验证了SQLite争用路径。

7.4、10.2、11.6、12.1、13.5仍未完成。还有138项非live最低义务需要实现/补测，2项live义务待Qwen绑定及请求上限。没有实际Qwen服务认证、真实home同步、提交、部署或归档。

详细取舍见[决策日志I72–I79](../decisions.md)，当前待办见[runtime-gap-cases.csv](runtime-gap-cases.csv)。
