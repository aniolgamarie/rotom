# Slopchop／终端适配后的隔离回归

执行日期：2026-09-17。层级：mock。当前源码的默认测试通过；不代表原生或真实账号验收通过。

## 统一回归

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/agentcfg-pi-mock-20260917-slopchop-terminal.json
```

- Python 3.11.11：1273 passed，7 subtests passed，耗时 280.49 秒。
- Node v24.1.0：182 passed，0 failed。
- 调度报告 `status=passed`，退出码 0；2026-09-17 13:45:28 至 13:50:12 UTC。
- 原始报告：`/tmp/agentcfg-pi-mock-20260917-slopchop-terminal.json`。
- 日志：同路径加 `.artifacts/` 下的 `pytest.stdout`、`pytest.stderr`、`node.stdout`、`node.stderr`。

测试调度器使用临时 HOME，阻断网络和真实宿主子进程。Node v24.1.0 是本轮 mock 的执行器；生产锁要求的 Node 24.14.0、Bun 1.4.0 仍须在各自原生验收中验证，不能借本报告宣称平台通过。

## 另行完成的静态／构建检查

- 完整 Slopchop fork 在固定 SDK 和 `@pierre/diffs@1.2.1` 下 TypeScript 检查通过。依赖装入临时目录，使用 `--ignore-scripts`；未加载 Pi 宿主。
- 官方 npm 0.10.1 归档 SRI 与迁移记录中的全部 15 个原始文件摘要匹配。
- Slopchop 派生归档生成成功，含适配源码、MIT 与 NOTICE；新版本已登记四配方。最终完整依赖锁尚未生成。
- 特殊项目路径经过 Codex 实际 CLI 按点拆键的语义回归。
- 假设备／假进程验证 PTY 绑定、执行闸门、尺寸和输入输出、取消及父终端恢复；macOS 只验证生成的设备规则。
- MCP 请求体大小和关闭竞态使用假 HTTP 请求测试，没有访问服务。

## 未覆盖范围

未执行真实 Pi、Codex、Cursor、Git 沙箱、编辑器或账号／服务调用。ReadSeek、MCP/web 完整适配、最终锁、原生场景执行器与验收仍未完成。固定范围中全部已选服务维持 selected_optional；暂无机器的三个平台维持 not-run。本文不构成 CapabilityEvidence 或 release approval。
