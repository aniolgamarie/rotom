# 4c043f8f 冷重建证据

本目录收集锁 `4c043f8fa2f52cc7b198a030c51f814ba937c405da100331ed75bd8a73993424` 的 Linux x86_64 四配方冷重建报告。每个 profile 完成后写入其子目录；四份报告全部取得后才写入 `index.json`。

每个 profile 的布局：

- `report.json`：原始冷重建汇总，包含两个目标的安装步骤、运行包身份、源码摘要和原生检查状态。
- `first/native/*.json`：第一个新 HOME / checkout 的原生明细。
- `第二组 空格路径/native/*.json`：第二个新 HOME / checkout 的原生明细。
- 每个目标下的 `0.*`、`1.*`、`2.*`：Python 环境、sync、apply 的原始输出。

本候选相对 484f07e9 的差异：T098 平台验收器接线（darwin 能力推导门控、darwin local_runtime slot、MacProcesses 显式停止契约）及 6 个 linux/all 资产的 `vendor_path` 化（下载源 url 与固定摘要不变，sync 改读 `locks/pi/vendor/` 并强校验）；`profile_slices` 与全部依赖解析逐字节不变，DSH 锁不变。逐项差异见 [实施记录](../../specs/001-unify-pi-capabilities/implementation-progress.md)。

`report.json` 的 `native_cases[].report` 路径相对于对应目标子目录。报告内的绝对 `work_root`、`runtime_root`、`artifact_directory` 是运行根中观察到的原始路径（`~/.cache/agentcfg-pi-handoff/run.9EvW7wDS`），保留用于审计；本目录不复制大型安装包、模型文件或临时运行状态。原始运行目录在归档核对后清理，失败过程证据见 `retired-7942277e-sync-fail-*`（7942277e 中间候选因 CDN 不稳定 sync 失败的报告，未产出原生证据）。

这些场景只使用合成模型及本地服务，没有真实账号调用。报告的 `passed` 表示该份报告列出的场景通过；不自动登记为固定 scope 的最终证据，也不批准四平台和真实账号的完整交付。
