# 2026-09-14 实现与证据审计

本次沿 `add-pi-task-keeper` 原范围继续。707 项 P0–P3 义务、436 项矩阵、6 项 P4 延期以及 171 项领域检查保持原定义；未将最低证据、矩阵映射或正常 Qwen smoke 视为整体验收。

已完成的行为与验证：

- EXE-010 P：真实 writer 撤权后继续写入，替代 writer 的资源申请被拒绝；确认旧进程停止后，接替进程实际写入。负向控制只运行该正例，移除资源检查必须准确触发 `EXE010_LIVE_WRITER_MUST_BLOCK_REPLACEMENT`，其记录与正常运行分开保存。
- VAL-005/006/007 V：用实际 `scripts/recovery-report.ts` 子进程验证报告输入，不再检查手写对象的字面属性。无绑定、失败实网、仅 smoke、过期身份、来源混淆、抢跑冷却、重复副作用和缺工件不能得到恢复通过结论。合成输入只用于 V，不取得 A/E/L 服务验收信用。
- CFG-011 E：通过真实 Neovim `ai.pi.write_config` 入口向隔离 Pi home 连续同步两次，独立连接检查真实 SQLite 的 intent、unknown、预算与等待记录；用户策略、auth 和工作区字节保持。包声明及复制入口实际存在。
- R09 的 pause/stop/dispose × revoke-first/await-first：使用真实 Pi RPC、真实工作区 snapshot helper，在私有源码副本的 resume await 返回处注入 barrier。只有实际观测的 12 个 A/E 矩阵位置可以取得信用。移除 stale-resume 检查的负向控制必须触发 `SNAPSHOT_REVOKED_CONTROL_MUST_PERSIST`。
- verifier 握手前取消：发现 stop 先于命名空间证明时可能留下仍等待授权管道的子进程，导致等待完整 workspace timeout。`supervisor.ts` 在取消时关闭尚未发送授权的管道；EOF 使接收端退出，仍不发执行许可。固定子进程存活并注入信号不可用的正反例验证此机制；旧代码能偶然被正常信号结束不被视为有效反例。
- 证据回填：`scripts/evidence-checkpoint.ts` 核对当前源码、原始 discovery/execution、真实 file/name、层级、逐项断言和 missing，再生成当前 CSV/JSON；旧 checkpoint 单独备份。篡改源码/记录/断言/名称/层级/hash/missing 的反例都必须在更新文件前失败。

## 历史错误与失败保留

- 接手时 `implementation-progress.md`、runtime-progress、case evidence、matrix evidence 引用了不同日期的报告；历史报告不能代表接手时源码。
- `cases-g32-v.test.ts` 的旧 VAL-005/007 信用无效：旧测试没有调用任何报告器。此次以实际 CLI 反例替换，旧报告保留，不追改成新的运行结果。
- 冻结检查发现 `tests/plan/fault-traceability.csv` 的 102 行被此前运行结果改写。与冻结 SHA-256 匹配的历史源副本逐字段比较确认，仅 status/test_file/test_name/result_artifact 被改，WHEN/THEN/required_layers 没变。已恢复 SHA-256 `d65ff7e7d20e24c71e268240b55296d0685f94ae0cc2995413218bcf3ae9b5d0`；恢复前文件和字段清单保存于 `test-results/audit-2026-09-14/`。当前运行结果应写派生 evidence/report，不改冻结计划。
- 本轮首次 EXE 反例输出格式断言失败、snapshot 私有切点歧义、R09 stop 收尾超时、dispose 输出判定、step 结算与 job CANCELLED 之间的观察竞态，以及信号仍可结束子进程导致的无效负向控制，均保留在对应 isolation 目录。已按具体原因修正；没有把正式测试失败改名为 expected-negative。
- 全量回归还暴露 `subagents-harness.ts` 直接写 adapter-result.json 的半写入观察竞态；现通过临时文件和原子 rename 发布完整 JSON，读者仍等待同一正式路径。全量报告的文件级 worker 并发固定为 8，各场景内部的真实多父/多进程竞争保持原样。
- `test-results/isolation-2026-09-14T01-32-06-747Z/` 保留了 verifier 收尾超时的真实工作区和 SQLite；只有后续当前源码运行可代表修复结果。

## 尚未结束的原范围

5 个大任务仍须分别满足退出条件。真实 Qwen Q3 及 direct/有界策略实测等待显式验收绑定和总请求/费用上限；V 报告器反例属于已执行离线工作，不能放入实网等待。其余缺失 A/P/E/V 及原矩阵均为离线工程/审核工作，不因外部参数缺失而豁免。

尤其，当前 InteractiveAdapter 仍拒绝受保护主会话路线，已有严格逐请求预算只覆盖明确认证的受管 child 路径。原请求矩阵中的未完成路径、C0–C5 实际调用链和其余 await 次序仍需逐项实现/认证；不得靠换标签或统一拒绝原定成功路径关闭它们。详细 missing 集合以最新、源码匹配的 runtime-progress.json 为准。

部署、真实 home 同步、提交、归档和新增平台/transport/Advisor 均未执行。

## 本轮最终 checkpoint

- 完整运行：`2026-09-14T01-50-24-884Z`，822/822 通过，17,928 次断言，失败/取消/跳过均为 0。
- 源码摘要：`f71bf637f0b69b9b4b14a5021990d73c651cb20d5a2d1b2f35a867de17068c81`。
- 最低 P0–P3 义务缺口 91；矩阵缺口 301。没有整体关闭任务 7.4/10.2/11.6/12.1/13.5。
- evidence-checkpoint 成功核对并生成 1217 条义务记录、143 条矩阵记录；原始 source/records/TAP/report 及回填前视图均保留。
- 校验：隔离 typecheck、test plan、完整 test report、严格 OpenSpec、check-design.py --self-test，以及保留冻结 CSV 原 CRLF 的 Git whitespace 检查通过。
- 失败完整运行 `2026-09-14T01-38-07-784Z` 和 `2026-09-14T01-44-12-369Z` 保留原失败；分别对应已经修正的 job 终态观察竞态和 adapter-result JSON 发布竞态。
