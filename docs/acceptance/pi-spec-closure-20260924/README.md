# Spec 001 验收与完成报告

**日期：2026-09-24；结论：Completed（按用户明确修订的范围）**

本 spec 已完成软件迁移、agentcfg 集成和 Linux x86_64 四配方 mock/native 与双路径冷重建验收。
另外三个平台及真实账号/服务验证已转出本 spec，未来实际使用时另行处理；当前不要求提供这些环境。

## 范围依据

- [规格修订](../../../specs/001-unify-pi-capabilities/scope-change-20260924.md)：用户要求正常验收并完成本 spec，遗留验证不再规划在本 spec 内。
- [范围映射](scope-amendment.json)：从历史 364 项中按平台和层级选出全部 81 项，逐项保留身份、证据路径、适用性和层级；明确登记 283 项去向。
- [新 scope](scope.json)：`001-unify-pi-capabilities-linux-software` revision 1。
- [后续工作](../../follow-ups/pi-platform-and-live-validation.md)：原 T107—T111，不是本 spec 的待办或新的已启动 spec。

## 正式结果

| 范围 | passed | not-run | failed / stale | check-release | 批准 |
|---|---:|---:|---:|---|---|
| 本 spec：Linux x86_64 软件范围，81 项 | 81 | 0 | 0 / 0 | rc 0 | 是，仅对该 scope |
| 原四平台与 live 完整范围，364 项 | 81 | 283 | 0 / 0 | rc 1 | 否，保留历史与后续基线 |

正式产物：[report-only](report-only.json)、[check-release](check-release.json)、[原范围复算](historical-check-release.json)、[真实命令与退出码](cli-executions.json)。
`report-only` rc 0 与 `check-release` rc 0 分别表明报告生成和当前范围验收成功。
本次没有运行真实账号调用，没有将任何 live/其他平台条目标记为通过，也没有修改原始证据。

## 核验依据

- 锁：`9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`。
- recipe：`85fc15c3babf58e768e2b09c25f7eac031644cac220c60c16d093c87cbb9257b`。
- 生产 `PiBackend.read_lock()` 通过，包含当前 recipe 与锁一致性检查。
- [既有冷重建归档](../pi-cold-9d6a9270/index.json) 349 个文件的 SHA-256 全部匹配；原正式报告按生产 `report()` 复算后逐字段完全一致。
- 新 scope 81 项与原 scope 对应条目完全相同；移出项按平台/层级划分，不按成功与否挑选证据。
- 四配方各双目标的原生/冷重建证据复用已验证候选；本轮只变更规格、文档与验收范围工件，没有改动运行源码或锁，没有重跑长时间测试。
- live 登记器 v3 回归记录见 [离线验证记录](../pi-live-9d6a9270/offline-validation.md)；其测试记录不作为真实 live 通过证据。

机器可读核验摘要见 [verification.json](verification.json)；最终任务计数、范围分区、报告复算、历史证据不变及文档链接检查见 [closure-audit.json](closure-audit.json)。本次关闭工件的文件摘要见 [index.json](index.json)。

## 命令复现

从仓库根执行，输出必须是尚不存在的文件，父目录需满足生产路径安全契约：

```bash
.venv/bin/python -B scripts/verify-pi.py --report-only \
  --scope docs/acceptance/pi-spec-closure-20260924/scope.json \
  --evidence-root docs/acceptance/pi-cold-9d6a9270 \
  --output /tmp/pi-spec-001-status-new.json

.venv/bin/python -B scripts/verify-pi.py --check-release \
  --scope docs/acceptance/pi-spec-closure-20260924/scope.json \
  --evidence-root docs/acceptance/pi-cold-9d6a9270 \
  --output /tmp/pi-spec-001-release-new.json
```

本次首次尝试在受限工具环境直接写仓库输出目录，CLI 安全保存检查返回 2，未生成报告。
之后在正常用户环境使用新建私人临时目录，正式执行上述三次报告命令，退出码分别为 0、0、1，再将报告字节原样归档；未放宽任何路径或运行保护。

## 任务与支持声明

- 有效任务 **107/107 完成**：T001—T106 加修订后的 T112。
- 原 112 项中 **5 项转出**：T107—T111，没有把它们勾成执行通过。
- 本 spec **正常完成，不是暂停**。支持声明限于 Linux x86_64 已验证的软件层级。
- macOS/Linux arm64 原生执行、Codex/Cursor 真实登录、Task Keeper 真实模型和其他真实服务尚未验证。
- 后续扩大支持范围时，必须核对届时的源码/锁/runtime/部署身份并取得相应真实证据；本次批准不能用于旧完整范围或未来不同候选。
- Git 提交整理、历史磁盘与进程清理不作为本 spec 的功能验收门槛，本次没有执行提交、删除或账号调用。
