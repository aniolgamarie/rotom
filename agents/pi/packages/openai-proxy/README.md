# OpenAI 自动代理

Pi 只使用 `agent_options.network.openai_proxy_route` 指定的 proxy 路线，将
`openai.com`、`chatgpt.com` 及其子域名的 API、认证、模型列表和 SSE 请求送到该代理。
没有默认端口，也不从环境代理变量补配置。凭据通过路线的 credential_ref 注入 Proxy-Authorization，
不放进 URL、状态或日志。代理失败不直连，其他域名仍由显式实例运行环境处理。
managed 上下文拒绝这条父侧辅助通道；Task Keeper 请求使用自身已计量的 transport gate。

代理地址可通过启动环境变量 `PI_OPENAI_PROXY` 覆盖。代理服务需要已启动；
代理不可用时请求报错，不自动回退到直连。自定义 OpenAI 兼容网关域名沿用原有设置。

由 `templates/pi/default.template.jsonc` 声明，`:PiGenerate` 同步。
首次使用在此目录执行 `npm install --ignore-scripts` 安装依赖，然后在 Pi 中执行 `/reload`。
每次重载都会重新创建分流和计数包装，保留仍开放的连接池及进程累计计数；
连接池关闭或代理地址变更时会创建新池。

## 对话结束诊断

一次用户请求结束后（包含工具循环、自动重试和自动压缩），在对话记录中显示：

```text
OpenAI 代理 · 本轮 2 请求 · ↑ 32.0 KiB ↓ 8.5 KiB（HTTP 正文） · HTTP 200×2
```

失败时追加失败次数和安全的底层错误码，例如 `失败 1（ECONNRESET）`。
没有请求时显示“本轮未观测到代理请求”，这不代表已验证直连。
展开记录可查看本轮代理地址、请求域名和统计口径。诊断使用 Pi custom entry，
不会作为用户消息注入模型，也不会自动触发回复。无 UI 的 print 模式输出到 stderr。

`/openai-proxy` 查看版本、代理地址、fetch/dispatcher 是否仍挂载、连接池是否关闭，
以及进程累计、本轮或上轮流量。配置已挂载不等于代理在线，实际 HTTP 状态和字节计数才是请求证据。

### 统计口径

- 在实际经过插件 ProxyAgent 的 Undici 回调中计数，不读取、复制或提前消费响应流。
- 上传统计已发送正文块；下载统计收到的正文块。有 gzip/zstd 等压缩时计入压缩后的大小。
- 不含 HTTP 头、CONNECT、TLS/TCP 开销、重传；不是代理软件的全量流量或计费数据。
- 每次网络尝试分别计数，包含 OAuth 和重试。HTTP 4xx/5xx、连接错误记为失败；保留失败前已传输的字节。
- 读取端取消单独计数，在展开记录及状态命令中查看。Pi 收到 SSE 完成事件后主动取消 reader 属于正常收尾，不能将它误报为网络失败；在传输层无法将它与用户主动中止区分。
- 按请求发起时所属的对话归属。该轮期间同一进程的后台 OpenAI 请求也可能计入；其他 Pi/子进程、浏览器和 Codex CLI 不计入。
- 对话之外的请求只计入进程累计。结束时仍未完成的请求标为“未结束”，其后续字节不混入下一轮；累计和 `/openai-proxy` 的上轮数据继续更新。
- SSE 正文完整计数；WebSocket 只统计 HTTP 握手，升级后的帧流量明确标为未计入。
- 只保留计数、HTTP 状态、域名和安全错误码，不记录请求正文、提示词、token、认证头、URL 查询参数或代理密码。
- 进程累计在退出 Pi 后归零；已输出的每轮摘要保留在该会话的 custom entry 中。

默认验证从仓库运行 `node scripts/test-pi-mock.mjs agents/pi/packages/openai-proxy/routing.test.mjs agents/pi/packages/openai-proxy/diagnostics.test.mjs`，网络被阻断。
`transport.test.mjs` 为独立原生传输验证，需明确授权后执行，不属于默认测试。
