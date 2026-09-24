# Web 基础与公共回归（mock）

## 完整回归

命令：

```sh
.venv/bin/python scripts/verify-pi.py --tier mock --case all \
  --output /tmp/agentcfg-pi-mock-20260918-web-foundation-fixed.json
```

- 时间：2026-09-18 11:59:47–12:05:52 UTC。
- Python：1420 passed，另有 7 subtests passed；退出 0。
- Node：249 passed；退出 0。
- 报告与原始输出：上述 JSON 及同名 `.artifacts/pytest.stdout`、`node.stdout`。
- 默认 runner 使用临时 HOME、虚构服务、网络阻断和假进程。Node 为系统 v24.1.0；定向测试另使用固定 v24.14.0。两者都不是原生宿主通过证据。

第一轮报告 `/tmp/agentcfg-pi-mock-20260918-web-foundation.json` 保留失败结果：Python 51 failed / 1367 passed / 7 subtests，Node 245 passed。
根因是新增 provider 字段使用公共框架不支持的无类型 anyOf；已将单服务字符串与多服务 `web.providers` 数组分开，未放宽公共 schema。相关 DSH/Pi 定向复验 47 passed。

## 本次覆盖

显式 Web 服务与秘密引用、私有路由 HTTP、DNS/地址边界、代理失败处理、实例工具名称所有权、manager 活动记录、后台抓取、摘要模型选择与取消、实例搜索认证和无环境账号 fallback。

完整回归后另有变更，不能继承这份完整报告的源码身份：

- model-delegate 增加实际插件→RPC→结果/进度/取消测试，并修复旧运行时入口仍可能派发的问题；相关 Node 28 passed，TypeScript 通过。
- doctor 补充 Web API origin 的 HEAD 路线探测、公共抓取无目标时的明确未验证分类；公共页面无凭据时不宣称需要账号。连同证据/范围/升级/可选能力定向 Python 80 passed。
- Web 声明依赖 pi-subagents 和 pi-permissions。

## 未覆盖

Web 尚未登记运行配方。浏览器 cookie、认证抓取、Git/媒体子进程、curator 监听器与完整设置闭包仍在迁移。没有真实浏览器、宿主、账号或模型请求，没有最终锁、冷构建及平台验收证明。

## 后续稳定回归：Web UI/API

`/tmp/agentcfg-pi-mock-20260918-web-ui-api.json` 于 2026-09-18 12:46:50–12:53:02 UTC 运行通过：Python 1424 passed + 7 subtests，Node 266 passed，均退出 0。按源文件 mtime 复核，运行期间没有相关代码变更。

这份报告包含 curator、认证 cookie 引用、GitHub API/PR/issue 读取与当时的缓存修订。随后增加的浏览器 profile/数据库快照/解密与聚合搜索路由测试不属于该报告的源码范围。

另外只执行了固定 Bun 1.4.0 的内存 SQLite 库检查，返回 SQLite 3.53.2。没有启动 Pi/Cursor 宿主或读取浏览器数据；这不是 Bun 配方或账号通过证据。

## 浏览器/媒体/服务容量稳定回归

`/tmp/agentcfg-pi-mock-20260918-web-browser-media.json` 于 2026-09-18 15:35:11–15:41:53 UTC 通过：Python 1456 passed + 7 subtests，Node 283 passed，两个 runner 均退出 0。复核对应源文件 mtime，运行期间无相关源码变更。

本批包含显式浏览器数据库副本、真实 reader 对合成加密 cookie 的处理、普通权限下的大媒体快照、本地媒体固定命令、MCP 服务容量，以及同一 Web 操作的模型与 IO 联通。默认测试依旧没有启动 Pi/Codex/Cursor、真实浏览器、FFmpeg 或真实账号调用。

## 2026-09-19：联网 CLI 批次完整默认回归

报告 `/tmp/agentcfg-pi-mock-20260919-web-cli.json`，1473 Python + 7 subtests、292 Node 全部通过。结束于 2026-09-18 16:35:44 UTC（本地 9 月 19 日）。复核源码在完整运行窗口内无改动。它覆盖 Git/媒体监督、中继、权限和清理；不覆盖随后补入的 PDF 产物、完整设置、缓存和撤权竞争修订。

第一方 Linux 隔离中继预检见 `/tmp/acw-preflight-s6_ryhkx/report.json`。使用合成 Python 客户端与私人 Unix 回显，未执行第三方宿主或账号。首次预检的挂载顺序错误及失败报告保留在 implementation-progress.md。
