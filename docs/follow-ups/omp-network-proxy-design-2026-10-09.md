# OMP v18.8.6 网络代理设计方案

日期：2026-10-09  
调查范围：现有 OMP 启动环境、Cursor 模型传输、权限主审请求、agentcfg 的 GitHub 依赖下载。未读取机器配置、认证库、数据库或运行日志；未启动 OMP，也未发送模型请求。此文为后续实现提案，实际升级验证见[验收记录](../acceptance/omp-upgrade-18.8.6.md)。

## 结论

官方 v18.8.6 **有公开的 provider-scoped 代理环境变量**：`PI_PROXY_<PROVIDER>`，provider ID 转大写并把非字母数字字符改为下划线，例如 `github-copilot` 对应 `PI_PROXY_GITHUB_COPILOT`。它是环境变量接口，不是 OMP 原生配置文件里的 per-provider proxy 字段。官方文档将其作用范围限定为 provider 请求；`PI_PROXY` 则装到进程级 `fetch`，会影响 OAuth 刷新/登录、usage 和模型发现等非 provider wrapper 请求。两者不可当作同一条路由。

建议把三类流量分开建模：

1. **OMP 模型请求**：OMP 启动边界不继承 caller 的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、大小写变体或 `NO_PROXY`，也不设置全局 `PI_PROXY`。默认不设置任何 `PI_PROXY_<PROVIDER>`，因此 Cursor 默认直连；需要代理的主执行模型按 provider 注入相应的 `PI_PROXY_<PROVIDER>`。源码已确认 Cursor HTTP/2 路径也读取 provider 专属变量，因此选路支持有源码依据；目标运行包的端到端联通性仍需独立验收。
2. **权限 API reviewer**：现有权限插件以所选模型身份解析 provider，再经 `runtime.fetch` 发送请求；当前注入的 fetch 是传入的 `globalThis.fetch`，因此 `PI_PROXY_<PROVIDER>` 不会自动成为这次请求的路由。可在仓库自有插件的 fetch wrapper 中按 reviewer provider 选择 Bun 每请求 `proxy` 选项；未配置时强制 `proxy: false`。这属于公开 Bun fetch API 的可行候选，限 HTTP/HTTPS 代理；需要在 OMP 18.8.6 的嵌入 Bun/扩展环境做隔离验证。
3. **GitHub 下载**：为锁定资产和 source/checksum 下载增加独立的显式下载路线，使用专用 urllib opener，而不是继承进程代理环境或临时修改全局环境。仅把下载代理交给该 opener；模型宿主继续使用干净环境。下载路线需要由本机配置单独选择并验证。

因此，一期推荐**主执行 API 模型使用官方 `PI_PROXY_<PROVIDER>` provider 路由；不设全局 `PI_PROXY`，不继承标准 HTTP(S)/ALL proxy 环境；Cursor 不配置专属代理，默认 direct；权限 reviewer 用 request-scoped fetch 按 reviewer provider 选路；GitHub 下载使用独立 opener 和独立路线**。这能覆盖源码已接入 upstream resolver 的主模型 provider 与 Cursor H2 自定义传输，不把代理扩展成全进程规则。

明确限制：`PI_PROXY_<PROVIDER>` 会继承给 OMP bash/worker 子进程。普通 curl/npm 等命令通常不消费该 OMP 专用变量；但子进程中再启动 OMP 会继承同一路由，因此这不是全子进程隔离保证。当前需求先关注网络选路，不把严格隔离作为一期门槛。SOCKS 和带凭据 proxy URL 不纳入一期；配置只允许无 userinfo 的 HTTP/HTTPS proxy origin，代理认证后续另行设计。

## 观察到的证据

### OMP 官方 v18.8.6

发布标签页面显示 v18.8.6 于 2026-10-08 发布，提交短 ID 为 `f068751`；v18.8.6 标签的 providers 文档将模型后端称作 provider，并明确有内建、custom 和 extension provider。  
来源：[v18.8.6 release](https://github.com/can1357/oh-my-pi/releases/tag/v18.8.6)、[v18.8.6 providers.md](https://github.com/can1357/oh-my-pi/blob/v18.8.6/docs/providers.md)。

[v18.8.6 environment-variables.md](https://github.com/can1357/oh-my-pi/blob/v18.8.6/docs/environment-variables.md) 的“Outbound proxy routing”段落明确记载：

- provider HTTP fetch 的优先顺序是 `PI_PROXY_<PROVIDER>`、`PI_PROXY`、按 URL scheme 选择的 `HTTPS_PROXY/https_proxy` 或 `HTTP_PROXY/http_proxy`，最后是 `ALL_PROXY/all_proxy`；先应用 `NO_PROXY/no_proxy`。provider proxy 查找结果在进程生命周期内缓存；localhost 绕过 provider fetch wrapper。（该标签文档第 327–333 行）
- `PI_PROXY` 会在 CLI 启动时装到 process-wide fetch，覆盖 provider wrapper 以外的请求，例如 OAuth refresh/login、usage 和 model discovery；`PI_PROXY_<PROVIDER>` 仅应用于相应 provider 请求，并覆盖该 provider 的 `PI_PROXY`。（第 335–338 行）
- 文档把 `cursor` 列作 Cursor provider，并将 `CURSOR_ACCESS_TOKEN` 列作其认证环境变量。（第 275 行）
- 文档说 loopback、link-local、私网地址和 `NO_PROXY` 匹配总是绕过代理。（第 338 行）

这些记载证明存在 provider 路由环境接口；没有发现 v18.8.6 文档承诺 TOML/YAML/JSON 配置里的 per-provider proxy 字段。配置 `models.yml` 中的 provider `baseUrl` 是模型 API endpoint，不等价于 HTTP forward proxy。

对指定 source checkout 的定向核对补足了传输实现：

- `packages/ai/src/providers/cursor.ts:1241-1257` 的 Cursor HTTP/2 分支以 `getProxyForUrl(model.provider, new URL(baseUrl))` 选路；有代理时先调用 `connectProxiedSocket()` 建 TLS/HTTP CONNECT 隧道，再将该 socket 交给 `http2.connect(..., { createConnection })`。无代理时直接 `http2.connect(baseUrl)`。这证明 Cursor H2 传输有 provider/env proxy 接线，不再是未知项。
- `packages/ai/src/utils/proxy.ts:154-161` 的真实优先级是：命中硬 bypass/`NO_PROXY` 时直连；否则 provider 专属 `PI_PROXY_<NORMALIZED_PROVIDER>` 优先于 `PI_PROXY`，再按 URL 取 HTTP(S)_PROXY，最后 ALL_PROXY。`getProxyForProvider()` 的结果按 provider 缓存进程生命周期，见 `:122-151`。
- “provider 没有专属变量”会尝试 `PI_PROXY`，不是显式 direct。源码及单测 `packages/ai/test/proxy.test.ts:129-153` 没有 `none` sentinel；例如 `PI_PROXY_CURSOR=none` 会被当成 URL 文本，而空值会回退到通用 `PI_PROXY`。需要 Cursor 默认直连时，应不设置通用 `PI_PROXY`，也不设置 `PI_PROXY_CURSOR`，并清除标准代理变量，不能依赖 `none`。
- `shouldBypassProxy()` 在 `packages/ai/src/utils/proxy.ts:63-119` 支持 `NO_PROXY/no_proxy` 的 `*`、域名精确/后缀匹配和可选端口，另硬编码绕过 localhost、loopback、RFC1918、link-local、IPv6 ULA 与 metadata hostname/IP。此自定义 matcher 未实现 CIDR 语法、`*.domain` 通配符语法（前导点后缀可覆盖子域）、按工具/模型区分的 allowlist；不要把 Bun fetch 文档的 CIDR 支持外推给 OMP 该 resolver。
- `connectProxiedSocket()` 在 `packages/ai/src/utils/proxy.ts:287-304, 375-415, 427-439` 实作 HTTP CONNECT；proxy URL `http:` 走普通 TCP、`https:` 先 TLS 连接代理，再 CONNECT 并对目标建立 ALPN `h2` 的 TLS。它解析 URL username/password 并组成 Basic `Proxy-Authorization`，日志只取 proxy host，不打印凭据。该实现不是 SOCKS 协议实现；`socks5://` 不可用。HTTP1 Cursor 路线另走 fetch/HTTP1，需按具体场景验证。
- `packages/utils/src/procmgr.ts:43-54` 的 `buildSpawnEnv()` 基于 `filterChildShellEnv(Bun.env, ...)` 构造 bash spawn env，但没有移除 `PI_PROXY*`。`packages/utils/src/env.ts:153-160, 199-239` 只滤掉项目 dotenv 值和固定 unsafe/Git repo 项，并没有 proxy allowlist。由此，若 OMP 启动环境设置 `PI_PROXY_CURSOR` 或别的 provider 变量，普通及交互 shell 的环境都会带上这些变量；`packages/coding-agent/src/tools/bash-interactive.ts:34-41, 106-119` 使用同一 `shellEnv`。`packages/coding-agent/src/subprocess/worker-client.ts:185-198` 对 worker 也会复制整个 parent env，仅剔除 Git repo 路径变量。标准 `HTTP_PROXY` 等若未在 OMP 启动环境中，就不会凭空从父 shell外进入；但 OMP 没有将 `PI_PROXY_<PROVIDER>` 从子进程剥离的保证。

### Bun fetch 的公开 API 边界

Bun 官方 [fetch proxy 文档](https://bun.sh/docs/runtime/networking/fetch)说明：

- 单个请求可传 `proxy: URL|string|{url, headers}`，或传 `proxy: false` 直连；显式 proxy 仍受 `NO_PROXY/no_proxy` 影响，除非设 `respectNoProxy: false`。
- 环境变量读取 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 及小写形式；scheme-specific 变量优先，`ALL_PROXY` 在其缺少时回退。文档明确忽略诸如 `socks5://` 这类另一种代理 URL scheme。
- HTTPS 目标通过 HTTP `CONNECT` 建隧道；代理对 CONNECT 返回非 2xx 时 fetch 报错。它没有承诺任意自定义 HTTP/2 客户端、原生 socket 或所有 WebSocket 实现都沿用同一代理配置。

这支持对 reviewer 使用 request-scoped HTTP(S) proxy wrapper 的设计；不支持把 SOCKS、HTTP/2、自定义 CONNECT 或所有 OMP 网络活动概括为已覆盖。Bun 的文档不是 OMP 18.8.6 内嵌运行时的验证记录，需在目标运行包上验证 API 可用性。

### rotom 目前的环境和网络调用

- [process.py](../../src/agentcfg/process.py#L10) 的基础子进程环境 allowlist 不含任何代理变量；[environment()](../../src/agentcfg/process.py#L19) 仅复制 allowlist 与 `LC_*`，再加入 machine 显式声明的 inherit/values。因此从该函数启动的 OMP 不默认继承用户 shell 的 HTTP(S)/ALL/NO_PROXY。受管 machine 可以显式添加这些变量，故调用环境与部署配置仍要分开检查。
- [omp_download.py](../../src/agentcfg/omp_download.py#L85) 以默认 `urllib.request.Request` 创建请求，[资产下载](../../src/agentcfg/omp_download.py#L286) 使用默认 `urllib.request.urlopen`；[锁维护下载](../../src/agentcfg/omp_download.py#L332) 同样调用默认 opener。当前没有独立 route 参数或专用 opener。Python 默认 urllib opener 会按当前 Python 进程环境发现代理，所以这类下载和 OMP 子进程 allowlist 是两种不同环境路线。
- npm 依赖安装使用单独构造的 allowlist 环境：[dependencies.py](../../src/agentcfg/dependencies.py#L203) 创建 `env` 并用它运行 npm；默认不含代理变量。不要把 npm 的子进程环境证据误当成 `omp_download.urlopen` 的行为证据。
- 权限插件的 [reviewRuntime](../../agents/omp/packages/omp-permission-control/standalone.ts#L256) 接收 `fetchImpl` 并直接转发；默认来源为 `dependencies.fetch ?? globalThis.fetch`（同文件约第 372 行）。[reviewer request](../../agents/omp/packages/omp-permission-control/standalone-reviewer.ts#L187) 先按模型取 API key，再调用该 fetch 发送 POST。审查模型已规范化为 provider/model/API 身份，[selectReviewer](../../agents/omp/packages/omp-permission-control/controller.ts#L14) 不复制 registry 的任意凭据字段。当前没有 per-provider transport selector。

### Cursor 执行传输

Cursor 默认直连可以通过不给 OMP 进程设置任何代理变量达成：provider resolver 返回无代理，源码 H2 分支直接 `http2.connect()`。显式设置 `PI_PROXY_CURSOR` 会被 Cursor H2 传输通过 `getProxyForUrl()` 读取，并用自定义 HTTP CONNECT socket 建立 H2；HTTP/HTTPS 代理可接线，SOCKS 不支持。推荐保留“不设置 `PI_PROXY_CURSOR`”作为 Cursor 默认，不需要把 Cursor 纳入代理出口。`NO_PROXY` 会在此传输分支生效，但只覆盖 OMP 自己的实现语法，不能推断 CIDR 支持。

工具子进程边界已由 v18.8.6 源码核对：OMP bash env 构造保留来自父进程的普通变量，包括已设置的 `PI_PROXY_<PROVIDER>`。它们不是通常的 curl/npm `HTTP_PROXY` 变量，普通子命令一般不消费该变量；但子进程中再启动 OMP 或主动读取 `PI_PROXY_*` 的命令会观察并可能继承这条 provider 路线。因此不能把此方案称作全子进程环境隔离。

## 路由表与实现建议

| 流量 | 默认选择 | 显式选择方式 | 边界 |
| --- | --- | --- | --- |
| OMP 主执行模型 provider | 未配置的 provider direct；按需显式路由 | 受管运行环境按 provider 设置 `PI_PROXY_<NORMALIZED_PROVIDER>`；不设 `PI_PROXY` 和标准 HTTP(S)/ALL proxy | Cursor H2 源码确认读 provider 变量并经 HTTP CONNECT；provider 变量会继承至 bash/worker child env，普通 curl/npm 通常不消费它，但子进程 OMP 会继承该路线 |
| 权限 API reviewer | direct | 插件传入的 fetch wrapper 根据已解析 reviewer provider 选择 Bun request-scoped `proxy` | Bun API 支持 HTTP/HTTPS；不能假设 SOCKS 或普通 Node `RequestInit` 类型自动等价 |
| GitHub 锁定资产/source | 独立 direct | 下载模块使用 route-specific urllib opener | 当前默认 opener 可能采用 agentcfg 进程 ambient proxy，需改为显式 opener 才可隔离 |
| 工具 shell / MCP / 子进程 | 不配置标准代理环境 | OMP 主进程仅显式注入目标 provider 的 `PI_PROXY_<PROVIDER>`；普通工具不使用这类 OMP 专用变量 | v18.8.6 bash/worker 会继承 provider 变量；嵌套 OMP 也继承，不提供全子进程隔离保证 |

推荐代理配置只保存无 userinfo、无 query/fragment 的 origin；如果需要代理认证，使用私有 secret reference，并且只在具体请求的内存态构造代理认证 header。不要读取或打印 shell 里的代理值，不要在错误消息、receipt、摘要、测试输出中放代理 URL 或 API key。代理失败日志只允许固定类别和目标 provider ID；URL、Authorization、Proxy-Authorization 不输出。该机密处理是建议设计要求，并非当前全部路径已通过的证据。

## 需要实证的项目

1. 对 v18.8.6 Cursor HTTP/2 CONNECT 在临时 TLS/HTTP2 endpoint 与假代理下做隔离传输验证；验证认证代理 URL 的秘密不会出现在 rotom 或 OMP 日志中；不要把这种可实现性误记为 SOCKS 支持。
2. 在 OMP v18.8.6 实际嵌入 Bun 上，用临时 reviewer endpoint 与假代理验证 fetch wrapper 按 reviewer provider 选路，未配置时 `proxy:false` 直连，不读取 shell proxy env，NO_PROXY 行为符合预期；确认 HTTP、HTTPS、CONNECT、重定向拒绝策略。
3. 为 GitHub 下载单独实现 opener 后，用本地假代理与被动假 GitHub endpoint验证只下载流量命中它，且代理密钥和 URL 不出现在输出。不要发真实模型请求或读取真实身份文件。

## 一期落地顺序和范围拆分

**网络代理工作与 OMP 宿主升级分开成两个变更。** v18.8.6 升级只负责锁定官方 release/source、验证插件兼容与既定宿主迁移；它不自动捎带任何网络路由。网络方案另起 rotom 自有代码的设计/实现和验收，保持不改 OMP 上游源码。

一期网络实现建议包含以下部分：

1. 受管 OMP 启动环境明确丢弃 shell 继承的 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/大小写及 `NO_PROXY`，同时不设置 `PI_PROXY`。对 Cursor 保持不设置 `PI_PROXY_CURSOR`，因此默认走官方 direct 路径。
2. 给需要代理的主执行模型按 provider 显式配置 `PI_PROXY_<PROVIDER>`；禁止全局 `PI_PROXY`，标准代理变量不从 caller shell 继承。只配置无 userinfo 的 HTTP/HTTPS proxy origin；SOCKS 和认证代理暂不支持。
3. 给权限插件 reviewer fetch 增加独立按 reviewer provider 选路；每个 request 的 fetch 初始化显式给 proxy 或 `proxy:false`，不改变 `globalThis.fetch`，也不读取/打印秘密。HTTP/HTTPS 地址可作为第一阶段范围。
4. 给 agentcfg GitHub release/source/checksum 下载增加独立的 route 配置和 `urllib` opener，默认 direct；代理只应用于下载请求。不要用调用 shell 环境或共享 `PI_PROXY` 作为下载配置。

OMP provider 代理环境值会被 bash/worker 子进程继承；普通 curl/npm 通常不消费 `PI_PROXY_<PROVIDER>`，但 child OMP 会继承相同路线。本期接受这一明确的限制，不宣称具备全子进程隔离；未来若要改成严格隔离，单独设计并验证 public API 方案，不修改 OMP 上游源码。


## 拟新增配置与验收合同

下述字段属于下一轮 rotom 自有实现提案，当前适配器尚不接受；不能直接写入本机配置。
在 `agent_options.network` 下提供严格 `default_route`、命名 `routes`、`provider_routes`、
`reviewer_provider_routes` 与 `download_route`。缺省为 direct；proxy 路线只引用
`local:...` 的无凭据 HTTP(S) origin，未知字段、悬空路线、标准变量冲突、provider 名归一化冲突
均失败。配置按 provider 而非套件或 main/smol 角色匹配；每次选择实际模型后再取路线，
包括执行 fallback 与 reviewer 的主审/远程 fallback。

- 执行模型：渲染声明 provider 的 `PI_PROXY_<NORMALIZED_ID>`，不注入全局代理。Cursor
  缺省 direct；本期不替用户启用 Cursor 代理，不改变可用模型和计费范围。
- 权限审查：在仓库自己的 reviewer transport 中传入明确的 provider/model 请求上下文，
  每次构造独立 fetch 初始化 `proxy` 或 `proxy:false`。不得按 URL 猜 provider，
  不修改全局 fetch；失败按现有 primary→remote→local/human 链处理，不自动改网络路线。
- 下载：sync 的固定源、清单和二进制使用显式 urllib opener，沿用严格续传、摘要、锁和
  激活事务。lock 维护须使用独立显式下载参数或已准备的离线材料，不能默借会话路线。

一期验收使用假 provider/代理和临时 HOME，分别证明：两个执行 provider 可选不同路线；
Cursor 默认不会落入别的 provider 代理；reviewer primary/remote 各按实际模型路线；
下载路线独立；NO_PROXY/本地目标 bypass 与 OMP 实现一致；取消、超时、拒绝、重定向、
异常路径没有路线串用或凭据输出。固定 11,473 条 shell 集与审批矩阵继续通过。
SOCKS、带认证代理和完整子进程网络隔离留在后续范围，不以一期通过声称已经支持。

本轮交付为方案和源码可行性证据；尚未新增这些配置字段或启用本机网络路由。
