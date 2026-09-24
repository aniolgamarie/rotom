# 484f07e9 冷重建证据

本目录收集锁 `484f07e9f16e070296b88ba24dcf7a5900f9d098ed1d5f43340c4f31b281dd26` 的 Linux x86_64 四配方冷重建报告。每个 profile 完成后写入其子目录；四份报告全部取得后才写入 `index.json`。

每个 profile 的布局：

- `report.json`：原始冷重建汇总，包含两个目标的安装步骤、运行包身份、源码摘要和原生检查状态。
- `first/native/*.json`：第一个新 HOME / checkout 的原生明细。
- `第二组 空格路径/native/*.json`：第二个新 HOME / checkout 的原生明细。
- 每个目标下的 `0.*`、`1.*`、`2.*`：Python 环境、sync、apply 的原始输出。

`report.json` 的 `native_cases[].report` 路径相对于对应目标子目录。报告内的绝对 `work_root`、`runtime_root`、`artifact_directory` 是验收沙箱中观察到的原始路径，保留用于审计；本目录不复制大型安装包、模型文件或临时运行状态。原始沙箱卷仍位于仓库忽略的 `cache/pi-validation/runtime-volume/`。

这些场景只使用合成模型及本地服务，没有真实账号调用。报告的 `passed` 表示该份报告列出的场景通过；不自动登记为固定 scope 的最终证据，也不批准四平台和真实账号的完整交付。软件输入身份及局限见 [候选记录](../pi-candidate-484f07e9.json)。
