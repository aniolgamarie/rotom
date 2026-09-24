# 4c043f8f 验证状态与阻塞记录

更新日期：2026-09-21（本机 Pi 接手后）。工作仓库：`/data/1/weixiaoxian.wxx/dev_tool/rotom`。本文件接续 [484f07e9 阻塞记录](pi-validation-blockers-484f07e9.md)，旧记录与旧证据全部保留。

## 已取得的证据（候选 4c043f8f）

- [完整隔离回归](agentcfg-pi-mock-20260921-4c043f8f.json)：1787 Python + 7 subtests、325 Node 全通过，锁稳定后运行，Node/Bun 为锁定工具链 v24.14.0/1.4.0；原始输出在同目录 `.artifacts/`。中间候选 7942277e 的同规模回归亦通过（[报告](agentcfg-pi-mock-20260921-7942277e.json)），该候选未产出原生证据。
- **四配方 × 两新 HOME/checkout 冷重建全部通过**（[证据目录](pi-cold-4c043f8f/)+[SHA 索引](pi-cold-4c043f8f/index.json)，共184文件）：
  - pi-default：两组各 6 场景（含 optional-services）全 passed；
  - pi-cursor：两组各 5 场景全 passed；
  - pi-codex：两组各 6 场景全 passed，含 codex-receipts 官方 CLI 只读/写入/控制（484f07e9 轮第二目标的资产校验失败本轮未复现）；
  - pi-managed：两组各 5 场景全 passed，含 taskkeeper-lifecycle 的 11 项生命周期（含两项 proxy；484f07e9 轮第二目标的 TLS 失败本轮未复现）。
  - 8 个目标源码摘要一致（`615713e72cd2…1938`），每配方运行包身份一致；82 个宿主租约全部回收、92 条 v3 进程记录全部终止（另 1 条 external `failed` 为负向服务场景预期终态）。全部使用合成模型与本地服务，无真实账号。
- [候选记录](pi-candidate-4c043f8f.json)：来源 31/31 摘要匹配、调用方 37/37、旧运行时依赖 0；`locks/dsh` 逐文件未变。
- [平台记录](pi-linux-x86_64.json)：`passed`。T106 已勾选。
- [report-only](pi-status-20260921-4c043f8f.json) 成功生成（364 项因候选身份未登记均为 not-run）；[check-release](pi-release-decision-20260921-4c043f8f.json) 返回 1 = 有效"不批准"。

## 候选变化原因（相对 484f07e9）

1. T098 平台验收器接线：darwin 五场景按密封 `bin/pi-supervisor-macos` 能力推导执行入口；darwin `local_runtime` slot（整包拷贝，原始运行包策略只读）；`MacProcesses.send_signal` 显式契约拒绝。recovery-grants/parent-loss 保留 Linux-only 显式原因（真实依赖 pidfd 身份信号）。
2. 6 个 linux/all 资产 vendor_path 化（url 与固定摘要不变，sync 改读 `locks/pi/vendor/` 并强校验）：本机出口对 github releases CDN 与 huggingface 不稳定（单连接约半数失败），vendored 后 sync 完全离线化。darwin/arm64 资产保持下载模式（本轮平台不需要）。
3. 中间候选 7942277e 因上述 CDN 问题在两配方冷重建 sync 失败（报告保留在运行根 `retired-7942277e-sync-fail-*`），vendor 化后以 4c043f8f 重新冻结并通过全部验证。

## 已知限制（不视为通过）

- **scope 证据未登记**：364 项 identity 均为空。按证据契约的逐条登记（每 AcceptanceItem 的 EvidenceRecord + 部署投影完整身份 + 逐项覆盖核对，不得复制 native 汇总给所有 V 项）是 T112 的核心剩余工作；本轮只生成报告与缺口，未做逐条登记。
- **ReadSeek 工具操作完整用户流程**：仍只有 mock 覆盖，native 场景组不驱动 ReadSeek 工具流；scope 无独立 ReadSeek 项，不擅自扩 scope。
- 一次整库 mock 出现 `test_project` 跨秒 `st_atime` 竞态失败（单测 6/6 通过），非回归，未改生产代码。

## 剩余阻塞（需要用户/外部环境）

1. **T110/T111 live**：六项已选服务（Codex/Cursor/MCP/web/代理/终端）与 Task Keeper direct/proxy 真实验收 —— 等用户提供 Pi 本机 `--local` 配置、明确测试项目及其账号/服务绑定；不得借用当前会话账号。
2. **T107—T109**：linux-arm64、darwin-arm64、darwin-x86_64 无机器，保持 not-run；darwin 的 T098 接线已就绪但未经真实平台执行。
3. **T112**：以上全部满足后才可批准；当前 report-only/check-release 已可重复生成真实阻塞状态。
