# 验收范围修订：完成当前 Pi 软件迁移 spec

## 用户决定与动机

2026-09-24 用户明确更正：不是暂停本 spec，而是正常验收并完成；另外三个平台和真实账号环境的测试留待未来实际使用时处理，不再规划在本 spec 内。
本修订取代同日早先的“阶段交付、验收暂缓”说明。它调整交付范围，不改变任何执行结果。

## 当前 spec 的验收基线

- 保留全部软件迁移、agentcfg 集成、DSH 兼容、Task Keeper 新版适配、model-delegate 完整替换及旧组件退出要求。
- 验收平台为 Linux x86_64，包含 pi-default、pi-managed、pi-codex、pi-cursor 四配方。
- 验收层级为 mock 与使用虚构服务的真实 native，包括四配方各两个全新 HOME/checkout 的冷重建。
- FR-001—FR-046、SC-001—SC-012 的软件行为要求保留；其中平台及账号执行要求按上述平台/层级限定。
- 原始矩阵中符合 `os=linux AND architecture=x86_64 AND live 不在 levels 中` 的全部 81 项原样纳入；不按测试结果筛选、不删场景、不改身份、不降所需层级。

## 移出本 spec

| 原任务 | 后续工作 | 本 spec 中的处理 |
|---|---|---|
| T107 | Linux arm64 实机及两路径冷重建 | 转出，不记测试完成 |
| T108 | macOS arm64 实机及两路径冷重建 | 转出，不记测试完成 |
| T109 | macOS x86_64 实机及两路径冷重建 | 转出，不记测试完成 |
| T110 | Task Keeper direct/proxy 真实模型工作流与第二视角 | 转出，不记测试完成 |
| T111 | Codex/Cursor/MCP/web/代理/终端真实账号与服务验收 | 转出，不改记未选 |

后续入口为 [独立后续清单](../../docs/follow-ups/pi-platform-and-live-validation.md)，不新建或自动启动另一个 spec。
原矩阵的 273 项其他平台条目和 10 项 Linux live 条目保留在旧 scope，事实状态仍为 not-run；未来真实服务的选择意图保留。

## 范围与批准身份

旧 scope `001-unify-pi-capabilities` revision 2 及 364 项历史报告完整保留，其 `release_approved=false` 不变。
本次为明确规格变更后的新基线，使用 `001-unify-pi-capabilities-linux-software` revision 1；两者关系、精确转出条目和摘要保存在 [scope-amendment.json](../../docs/acceptance/pi-spec-closure-20260924/scope-amendment.json)。

生产 `validate_revision()` 继续拒绝普通证据登记过程中缩减必需范围。不修改该校验、不伪装成普通 revision 更新；新基线必须随本规格修订共同审阅，之后只在自身范围内按原规则演进。
新基线由原生产 `report-only` / `check-release` 验收，全部 81 项匹配 passed 才能关闭 T112。

## 完成与支持声明

本 spec 的有效任务为 T001—T106 加修订后的 T112，共 107 项；原 112 个任务编号中有 5 项转出，不报告为“原 112 项全部执行通过”。
通过新基线后，本 spec 状态为 Completed。此完成仅声明上述软件迁移和 Linux mock/native 范围通过；不声明另外三个平台或真实账号/服务已经通过。
没有秘密授权、清理授权或账号调用随范围变更产生；运行期准入与 fail-closed 保护不变。

## 宪章与兼容性

符合宪章 V：执行过的结果才记通过；跨平台和无账号结果不互相替代。符合原则 I：支持声明仍限定于实际原生证据覆盖。
范围调整由用户明确要求，不是汇总器因失败自动删项。候选锁、运行实现、DSH 锁和历史证据均不修改，无宪章例外。

详细验收结果见 [关闭报告](../../docs/acceptance/pi-spec-closure-20260924/README.md)。
