# 32da4799 验证状态与阻塞记录

更新日期：2026-09-21。接续 [4c043f8f 阻塞记录](pi-validation-blockers-4c043f8f.md)，更早的 [484f07e9 记录](pi-validation-blockers-484f07e9.md) 同样保留。

## 已取得的证据（候选 32da4799）

- [完整隔离回归](agentcfg-pi-mock-20260921-32da4799.json)：**1805 Python + 7 subtests、325 Node** 全通过，锁定工具链（Node v24.14.0/npm 11.19.1/Bun 1.4.0）。
- **四配方 × 两新 HOME/checkout 冷重建全部通过**（[证据目录](pi-cold-32da4799/)+[SHA 索引](pi-cold-32da4799/index.json)，196文件）：default 7 case 组（含 readseek-tools 与 optional-services）、cursor 5、codex 7（含 readseek-tools 与 codex-receipts 官方 CLI 三态）、managed 5（含 taskkeeper-lifecycle 11 项）。8 目标同一源码摘要，48 份原生报告 108 个场景全部 termination_confirmed。合成模型与本地服务，无真实账号。
- **ReadSeek 原生验收**：readseek-tools 场景在 default/codex 全步通过——readSeek_grep 检索、readSeek_digest 读取、readSeek_write 创建、readSeek_edit 编辑、readSeek_rename 符号重命名（含引用级联）、越界写 local.toml 被拒、code.txt 源保护、项目无残留。能力矩阵依据：pi-readseek 为 O 保留（含 edit/write/rename，不当只读插件），验收缺口补齐，未扩 scope。
- **T112 逐项证据登记**：scope revision 3（[pi-scope-r3.json](pi-scope-r3.json)），linux-x86_64 格子的 mock/native 证据已按 [逐 V 项审计](pi-evidence-audit-32da4799.md) 登记为 EvidenceRecord；[report-only](pi-status-20260921-32da4799.json) 与 [check-release](pi-release-decision-20260921-32da4799.json) 见对应报告。身份取自第一目标部署投影（identity 随目标特异，口径已记录）。
- [候选记录](pi-candidate-32da4799.json)：来源 31/31、调用方 37/37、旧依赖 0；`locks/dsh` 全程未变。

## 相对 4c043f8f 的增量

1. T098 darwin 执行器实现（parent-loss 撤权+helper kill-control；recovery-grants 测试侧 helper 包裹 owner、收据链恢复）——**已实现、仅缺实机验证**，无“缺实现”项。
2. ReadSeek 原生验收（八处接线修复后全步通过，见实施记录（三））。
3. vendor 交付脚本与文档（[pi-vendor-deliverability.md](pi-vendor-deliverability.md)）。
4. test_project atime 竞态根因修复。

## 剩余阻塞（需要用户/外部环境）

1. **live**：六项已选服务与 Task Keeper direct/proxy 真实验收——等 Pi 本机 `--local` 配置、明确测试项目及账号/服务绑定；不借用本会话账号。
2. **T107—T109**：linux-arm64、darwin-arm64、darwin-x86_64 无机器；darwin 的 T098 执行器已就绪但未经真实平台执行。
3. **T112 最终批准**：linux-x86_64 已登记证据；全部 required/selected_optional 匹配 passed 才批准，当前 live 与三平台阻塞。
4. pi-cursor 的 ReadSeek：Bun 宿主下 worker 的锁定 node 解释器绑定未设计（场景级排除，有配置依据）。
5. 磁盘：运行根清理方案见 [pi-disk-cleanup-plan.md](pi-disk-cleanup-plan.md)，待确认后执行。
