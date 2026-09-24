# Pi 实网验收前提

## 当前状态

用户已明确选择 Codex、Cursor、MCP、web、代理和终端全部验收，并在本轮确认：Pi 的本机 `--local` 配置和测试项目**未准备**。

| 项目 | 状态 | 对验收的影响 |
|---|---|---|
| 六项可选服务的选择 | 全部已选 | 全部保留 `selected_optional`，不能改为 `not-selected` |
| Pi 本机配置 | 未准备 | 不能确认模型、路由、凭据引用和服务绑定 |
| 实网测试项目 | 未准备 | 不能确认明确授权的项目范围与检查绑定 |
| Linux x86_64 合成服务验收 | 四配方第一目标通过；两份第二目标待重跑 | 各项真实调用须使用匹配的已通过原生前提 |
| 另外三个平台 | 无测试入口，未验证 | 不继承 Linux x86_64 证据 |
| 真实账号调用 | 本轮未执行 | 所有相关 live 项保持待验收 |

本文件记录准备情况，不是通过证据，也不修改固定 [scope](pi-scope.json)。当前 [484f07e9 输入记录](pi-candidate-484f07e9.json) 已保存，本批次结果见 [Linux汇总](pi-linux-x86_64.json)，尚缺完整双路径通过；默认测试见 [测试记录](pi-default-tests.md)。历史候选及失败报告保持原样。

## 后续所需输入

准备实网环境时，需要明确的 Pi `--local` 文件路径，以及专用测试项目路径。配置示例为 [基本配置](../../examples/pi-workstation.toml)、[受管任务配置](../../examples/pi-managed.toml) 和 [服务配置](../../examples/pi-services.toml)；执行步骤及合成项目准备入口见 [quickstart](../../specs/001-unify-pi-capabilities/quickstart.md)。凭据继续保留在本机专用来源中，不写入报告或仓库。

无需重新决定六项服务是否选择。准备完成后，先验证配置和项目，再按相同平台、profile、transport、候选身份的原生通过记录逐项执行 live 验收。
