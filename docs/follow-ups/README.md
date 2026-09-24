# 遗留问题索引（follow-ups）

本目录登记所有"已确认但未执行"的后续工作。建立日期：2026-09-24（随 PI-F 清单建立）。
历史遗留原文件保留在原位置，本索引统一登记状态与执行前提；新遗留直接以本目录为家。

约定：每个条目须记录日期、状态（未执行/待前提/观察期）、执行前提与恢复入口；
不登记已关闭事项，不重复 acceptance 矩阵中按职责维护的待验证状态。

## 条目总表

| 编号 | 内容 | 位置 | 状态 | 执行前提 |
|---|---|---|---|---|
| PI-F01–F05 | 三平台实机验证（T107–T109）与 live 验收（T110–T111）转出 | [pi-platform-and-live-validation.md](pi-platform-and-live-validation.md) | 未验证 | 对应机器、账号绑定与逐项授权 |
| OMP-F01–F05 | Linux arm64、macOS双架构及真实登录、usage、模型调用（原T061未覆盖部分、T062–T065）转出 | [omp-platform-and-live-validation.md](omp-platform-and-live-validation.md) | 未验证 / 待环境 | 对应机器、账号、预算与逐项独立授权 |
| DSH-F01 | DSH Cursor 认证缺陷（oauth-subs `parseTurns` 折叠连续 user 消息）；rotom 侧已搁置 Cursor 路线 | [../dsh-cursor-auth-deficiency.md](../dsh-cursor-auth-deficiency.md) | 待上游修复 | 上游发 issue 并修复后 bump vendor；或用户授权 rotom 侧行为补丁（优先级 B） |
| PI-F06 | pi-cursor 精确钉死旧版 bug：已止血（1.4.36），根治项待办——8 个扩展版本落后、缺巡检机制 | [../pi-cursor-stale-pin-legacy.md](../pi-cursor-stale-pin-legacy.md) | 止血完成，根治未做 | 定期维护窗口；信任边界类扩展（pi-cursor、pi-mcp-adapter）优先审 |
| PI-F07 | pi-permission-system `ob-make *` 过度匹配：已修复（deny→ask），观察期 | [../pi-permission-ob-make-overmatch.md](../pi-permission-ob-make-overmatch.md) | 观察期 | 观察 ask 频率；治理缺口（权限 config.json 纳入版本管理）待排期 |
| SEC-F01 | secrets 与配置同文件（AI 场景泄露风险）：短期用临时移除 workaround | [../defect-secrets-in-same-file.md](../defect-secrets-in-same-file.md) | 待修复 | 中期实现 secrets_file 分离（方案 1，需改代码）；排在功能需求之后 |
| REVIEW-F01 | harden-agent-config 变更的遗留验收：B–E 行为验收 + 平台与账号验收 4 项 | [../improvement-plan.md](../improvement-plan.md) | 待执行 | 用户授权 live、macOS 环境、推送远端 CI；不自动执行 |
| OPS-F01 | 磁盘清理（/home ~170G + /data ~142G）：方案已编制 | [../acceptance/pi-disk-cleanup-plan.md](../acceptance/pi-disk-cleanup-plan.md) | 待用户确认，未执行任何删除 | 用户逐项确认；删除前核验归档 SHA 与清单 |

## 归并不迁移的说明

AGENTCFG-F01的软件范围已实现并通过隔离验收，故从待办表移出；历史决策、证据和真实账号限制保留在[usage记录](agentcfg-usage-command.md)。OMP真实usage已随用户2026-09-24范围决定转为 [OMP-F04](omp-platform-and-live-validation.md)（保留原任务号T064），不再属于当前spec 002的未完成任务；当前状态仍为未验证，见[支持状态](../omp-support.md)。

DSH-F01、PI-F06、PI-F07、SEC-F01 成文早于本目录，原文件含完整证据链与会话日志引用，
迁移会断开既有链接，故仅在此索引。新遗留问题请直接在 `docs/follow-ups/` 建文件，格式参照
[pi-platform-and-live-validation.md](pi-platform-and-live-validation.md)。

## 不在本索引范围

- `docs/acceptance.md` / `acceptance-matrix.md` 的 macOS/账号待验证：验收矩阵按职责就地维护。
- `docs/handoffs/`：交接记录，任务恢复后即失效。
- `docs/review-*.md`：审查报告，结论已落入对应实现或本索引条目。
