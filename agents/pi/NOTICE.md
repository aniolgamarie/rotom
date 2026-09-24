# Pi 迁移来源记录

来源：用户指定的starter仓库，固定提交见migration/source-baseline.json。
该文件记录Git对象身份和执行意图，不含机器配置、账号或会话正文。

- 本地Pi插件、资源和model-delegate的原始出处保持在逐文件manifest中。
- 派生版本的修改说明及各第三方许可证必须在vendor构建时逐项收录；
  本记录不替代原始许可证，也不表示包已经完成适配或原生验收。
- codex-delegate与codex-agents仅为历史行为对照来源，不进入最终可执行依赖。
- Linux Codex 附带同一官方 release 的 bwrap 发行物，不能只锁定 codex 主程序后依赖机器碰巧安装兼容版本。
  bubblewrap 原许可证与固定源码出处位于 `build/licenses/codex-bwrap/`；Codex wrapper 继续保留 `build/licenses/codex/` 的声明。
- Codex primary 发行清单中的 `codex-code-mode-host`、`codex-responses-api-proxy` 同样固定到 0.154.0 的四平台归档，
  作为官方 CLI 的内部辅助程序保留，不增加第二个委托入口或 MCP 工具桥。
