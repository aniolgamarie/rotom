# Pi 后续平台及真实服务验证（不属于 spec 001）

2026-09-24 用户明确将以下工作移出 `001-unify-pi-capabilities`，未来实际使用时再安排。
这是后续工作清单，不是已启动的新 spec，也不阻塞当前软件迁移 spec 验收关闭。

## 后续条目

| 后续编号 | 原任务 | 内容 | 执行前提 |
|---|---|---|---|
| PI-F01 | T107 | Linux arm64 四配方真实原生能力与双路径冷重建，含停止、预算、权限、完整替换 | 对应机器与原生执行授权 |
| PI-F02 | T108 | macOS arm64 四配方及 helper 编译、OWNER 恢复、沙箱、后代终止、双路径冷重建 | 对应机器与原生执行授权 |
| PI-F03 | T109 | macOS x86_64 同等覆盖，含 ReadSeek Intel Zig 源码构建 | 对应机器与原生执行授权；不能借用 arm64 结果 |
| PI-F04 | T110 | Task Keeper direct/proxy 的调查、修复、检查、审查和第二视角，记录消耗与终止 | 对应部署的 native 前提、私人配置、项目、模型、预算与调用授权 |
| PI-F05 | T111 | Codex、Cursor、MCP、web、代理、终端真实登录/调用及委托显式 write/control | 对应服务与账号绑定、native 前提、操作范围与授权 |

状态均为 **未验证 / not-run**。所有已选服务的后续验证意图保留，不能将移出当前 spec 解释为 not-selected 或 passed。

## 恢复入口

- [live 配置草案、逐项缺项及生产流程](../acceptance/pi-live-9d6a9270/README.md)。现有 probe/目录/账号状态均需届时复核，不能假定一直存在。
- [原始 364 项 scope](../acceptance/pi-cold-9d6a9270/pi-scope-9d6a9270-r1-r2.json) 与同目录原生证据保留；当前 81 passed / 283 not-run。
- [验收范围修订](../../specs/001-unify-pi-capabilities/scope-change-20260924.md) 记录转出缘由与当前 spec 边界。

未来执行前核对当时源码、锁、runtime、部署和平台身份。匹配证据可复用；变化部分按影响补验收，不直接继承历史 passed。
live 继续按 apply → 逐项 freeze → native 前提核对 → live → 登记 → 正式报告；失败和重试分别保留，秘密只放私人文件。

当前无需提供测试机、账号或预算；后续是否建立新 spec、何时执行届时决定。
