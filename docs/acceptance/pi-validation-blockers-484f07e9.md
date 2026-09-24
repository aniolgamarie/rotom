# 484f07e9 验证阻塞记录

## 已取得的证据

- [完整隔离回归](agentcfg-pi-mock-20260920-host-namespace.json)：1782 Python、7 subtests、325 Node 全通过。该轮测试期间源码未变；锁在 Python 回归开始约30秒后生成，Node 回归发生在锁生成之后。
- [软件候选身份](pi-candidate-484f07e9.json)与[第一方内核验证](pi-host-kernel-smoke-484f07e9.json)已保存。
- 四个 profile 的第一目标原生检查均通过，包括 Task Keeper 的11项生命周期、父宿主退出和恢复。每个 profile 的最终双路径状态以[原始冷重建报告](pi-cold-484f07e9/README.md)为准。
- 本批次已结束：pi-default、pi-cursor双路径全部通过；pi-codex、pi-managed第二目标未通过。报告与输出的索引摘要已逐项核对，[Linux汇总](pi-linux-x86_64.json)仍为failed。已通过目标中的58个宿主租约均具有已终止的v3命名空间记录。

## 未通过的冷目标

| Profile / 目标 | 阶段 | 实际结果 |
|---|---|---|
| pi-codex / 第二组 空格路径 | sync | 退出5：数据资产大小或摘要不匹配；未执行该目标原生检查 |
| pi-managed / 第二组 空格路径 | Python 环境安装 | uv下载 `coverage==7.16.0` 时TLS握手EOF，3次重试后失败；未执行sync或原生检查 |

两份失败报告和目录保持原样。没有忽略摘要校验、使用旧缓存或将第一目标结果复制为第二目标通过。

## 补充回归与自动审核

为取得锁生成后开始的完整默认回归，尝试了正常用户环境的执行申请。自动权限审核未在截止时间内完成；按工具允许重试一次后仍超时，命令均未启动。

默认沙箱内随后运行了 `.venv/bin/python -m pytest -q tests`。该环境的有效UID为1002，但 `/` 和 `/tmp` 的属主映射为65534，触发生产路径保护。结果为847 passed、892 failed、43 errors、7 subtests passed，大量失败为“路径祖先不属于可信用户”。这是另一次未通过的验证尝试，不覆盖此前完整通过报告，也不作为修复代码或放宽所有权检查的理由。

Codex冷重建重跑的正常用户执行申请及其一次重试同样因自动审核超时未启动。准备好的重跑使用同一锁、全新目录与合成服务。需要执行通道恢复或新的明确执行批准后再提交；尚未取得通过证据。

准备好的执行入口如下，均断言锁仍为484f07e9；冷重建使用新的`-retry1`目录：

```sh
.venv/bin/python -B /tmp/agentcfg-run-final-mock.py
bash /tmp/agentcfg-run-codex-cold-retry.sh
bash /tmp/agentcfg-run-managed-cold-retry.sh
```

其中Task Keeper重跑入口已准备，尚未提交新的执行申请；此前失败来自已授权冷重建中的依赖下载。

在默认沙箱中再次执行 `--check-release` 时也未能安全保存新报告，退出2。固定scope未变，[已有发布检查](pi-release-decision-20260920.json)仍不批准交付。

## 其余范围

- Pi本机配置和实网测试项目由用户明确标记为[未准备](pi-live-readiness.md)，六项已选服务继续待验收。
- Linux arm64、macOS arm64、macOS x86_64没有测试入口，保持未验证。
- T098的平台专用验收器接线仍未完成；T106、T107—T112不因已有部分证据提前勾选。
