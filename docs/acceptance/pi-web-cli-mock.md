# Web 完整适配与依赖检查（代码/mock）

本批已将 Web 0.27.0-agentcfg.1 声明到四个配方，并接通实例配置、服务/路线/凭据、模型、浏览器副本、认证抓取、curator、Git、媒体和 PDF 输出。工具入口、后台活动及外部进程共用 AgentManager/supervisor。

## 当前源码验证

- 可选能力/OpenSpec/Cursor/升级/项目初始化/Web/doctor/vendor 定向 Python：65 passed。
- Web 原生插件登记与 raw/readable fetch、合成 PDF 的真实 unpdf 解析、秘密请求头/API 分派、受控 CLI、缓存和工具生命周期的定向 Node 测试通过。全部使用假宿主、假模型或假 HTTP，外部网络和第三方进程被阻断。
- Web 全源码 TypeScript 检查通过，类型依赖来自固定 SDK 0.84.4 与 TypeScript 5.9.3。
- 完整上一批报告 `/tmp/agentcfg-pi-mock-20260919-web-cli.json`：1473 Python + 7 subtests、292 Node passed，测试期间无相关源码修改。该报告早于随后 PDF/缓存/API 分派/完整配置修订，不能覆盖这些修订。

## 真实锁与安装（未运行宿主）

临时源码副本：`/tmp/agentcfg-pi-lock-probe-tkoxlj65`。
27 个来源、四个配方真实解析成功，锁身份：
`1a552314999dc20db25ef78ce01c6815a002ab9f0239180a63c95ce250c3bfcf`。

四配方均实际执行禁用安装脚本的 npm ci、资源投影和运行包密封，状态 installed。
收据与结果保存在 `/tmp/agentcfg-web-install-evidence-vwd3x1lw` 的四个 profile 子目录。
为避免重复保存大型模型数据，每个自建临时安装在保存收据后已移除；原始锁来源与模型缓存保留。

此源码副本早于缓存 fchmod、Gemini 绑定、SearXNG/Kagi/Ollama 分派和 PDF 释放修订。它证明对应依赖图可以安装，不是最终候选身份，也不作为最新源码的原生通过证据。

## 尚未证明

没有真实 Pi/Codex/Cursor、Git/yt-dlp/FFmpeg、浏览器或账号通过证据。
第一方 Linux 隔离中继预检只验证内核回环与 Unix 通道，记录于 implementation-progress.md。
其他三个平台仍按用户选择保留未验证。最终依赖锁和 native/live 验收仍待后续任务。

## 最新完整回归

`/tmp/agentcfg-pi-mock-20260919-web-complete.json`：1475 Python + 7 subtests、300 Node passed。
UTC 2026-09-18 17:06:57–17:14:08；运行期间相关源码零改动。
该批覆盖后续 PDF、缓存权限/生命周期、服务分派、配置和插件联通修订。仍为 mock-only，不升级 native/live 状态。
