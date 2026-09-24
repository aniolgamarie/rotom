# Pi Web 迁移进度

Web 派生包已声明到四个配方，正在验证完整依赖闭包；最终锁尚未生成。本文描述代码与离线验证，不表示原生加载或真实账号通过。

## 已接通的部分

- 配置取当前实例 manifest，凭据仅解析该插件声明的秘密引用。秘密正文中的 `$` 或 `!` 不再解释为环境变量或命令。
- 每个 HTTP 服务必须声明 origin 和网络路线。公共页面请求检查 DNS 和地址范围，再固定实际连接地址；代理失败终止所属操作，不能切换为直连。
- 四个 Web 工具以及命令、快捷键经过实例绑定入口。工具名称与 MCP 共用冲突检查，不能覆盖普通文件工具或 ReadSeek。
- HTTP 请求、后台内容抓取和关闭过程由已有 AgentManager 保留同进程资源记录；后台工作结束前，前台返回不会解除会话保护。
- 摘要、查询改写和页面问答调用当前实例受约束的 ModelRuntime，只选已配置模型，不扫描旧账号、不轮换备用模型，模型重试为零。超时后尚未结束的调用仍有活动记录。
- 搜索服务的可用性先检查显式选择。Gemini ADC 改为秘密引用中的 JSON，原生解析错误不输出凭据原文，不访问全局 gcloud 文件。

## 尚待完成

主要剩余为完整依赖安装、完整宿主发现与原生/真实账号验收。PDF 产物、设置投影、订阅账号、浏览器 profile、Git/媒体命令和 curator 已有代码及离线测试，不据此标为原生通过。

## 证据层级

定向测试使用虚构模型、服务与替身 HTTP；源码类型检查使用锁定 SDK 声明。没有执行真实 Pi、浏览器、模型调用或账号验收。
最终 Linux x86_64 原生验收尚待完成，Linux arm64、macOS arm64、macOS x86_64 按用户要求保留未验证。

## curator 当前接入

显式开启 `web.curator.enabled` 并声明 `browser_network = "user-browser"` 后，可在代码路径中创建本机 loopback 界面；端口和最长存活时间可以固定。默认 workflow 仍为 none；配置 summary-review 却未启用 curator 会在校验时失败。

监听器与 MCP 共用已有 manager 的资源生命周期，请求各自登记 Web 活动；关闭时中止并等待请求。页面仅从当前冻结切片读取 marked 18.0.5，不加载 CDN 或远程字体。用户从提示中的本地链接打开浏览器，不启动桌面命令或寻找全局 npm。

远程 curator 与浏览器 profile 的代码路径见下文。模拟监听器与请求测试通过不代表本机端口或真实浏览器已验收。

## 认证页面抓取与 GitHub API

新增 `web.auth_fetch.<profile>` 以 `cookie_ref` 引用秘密，并列出允许发送 cookie 的 HTTPS origins；这些 origins 还必须包含在 `web.services.authenticated.origins` 中，服务具有明确的网络 route。模型输入不能覆盖 cookie/认证头，也不能借该入口执行写请求。重定向按 profile 的精确 origin 重新检查。该路径支持已绑定 cookie 或下文的显式浏览器 profile。

GitHub 仓库大小、默认分支、树、README 和单文件 API 读取已使用 `web.services.github` 的受控 HTTP 路线及可选 `githubToken` 引用，不需要 gh CLI 或其全局账号。API 树被截断时会明确标注。PR/issue 使用下面的固定 API 查询；clone 使用后文的监督命令入口。

PR/issue 的详细视图也已改为固定只读 GraphQL 和 REST 请求：保留评论、审查、提交、检查与关联条目，连接超过 100 项时明确标记。字段依据 [GitHub Pull requests](https://docs.github.com/en/graphql/reference/pulls)、[Issues](https://docs.github.com/en/graphql/reference/issues) 和 [Commits](https://docs.github.com/en/graphql/reference/commits) 官方 schema 核对；没有使用真实账号执行查询。GitHub clone 已接入同一监督体系，见后文。

## 显式浏览器 profile

已实现 POSIX 浏览器认证读取的代码路径：

- `web.browser_profiles.<id>` 指定 `root_ref`、单个 `profile` 目录、`browser`、`password_ref`、`allowed_hosts`，可配置数据库及 sidecar 的总大小上限。
- `web.gemini_browser_profile` 选择 Gemini Web 使用的 profile；认证页面也可用 `web.auth_fetch.<name>.browser_profile`，与该项 `cookie_ref` 二选一。
- 引用的浏览器根必须是声明的 read 根。适配器把它加入普通工具的硬拒绝范围，原始配置不被改写。缺密码引用值时，不读取数据库。
- 监督器同时核验 DB/WAL/SHM 的文件身份，拒绝链接、额外写权限、超限和读取期间变化。私有副本及 SQLite 工作目录仅放在受保护认证缓存中；不创建全局 `/tmp` cookie 副本。
- 仅用固定 Node/Bun 的 `node:sqlite`，密码来自秘密引用；不扫描其他浏览器/profile，不调用 OS keychain、secret-tool、全局 sqlite3 或 Python fallback。
- 已完成的副本显式释放；过期副本按自身代次清理，重启后再次使用能力时只回收已标记且过期的本实例副本。

当前适配继承上游的 POSIX preset 范围：Linux 为 Chrome/Chromium，macOS 为 Chrome/Brave/Helium/Arc；其他组合明确不可用。这里描述代码与合成数据库测试，真实浏览器版本、账号、文件系统时序和目标平台仍未验收。

## 本地媒体与远程界面

本地视频元数据和上传读取现走普通 `read` 权限，流式冻结到私有只读副本；同一 Web 操作复用同一内容版本并核对摘要，不再通过目录扫描猜测相似文件名。默认输入硬上限 128 MiB，可用 `web.media.max_file_bytes` 配置；原生 `video.maxSizeMB` 仍限制上传大小。Gemini API/Web 的请求默认上限为 64 MiB，所选 HTTP 服务可以显式覆盖。

本地抽帧和时长检查分别使用 `web.media.ffmpeg_tool_ref`、`ffprobe_tool_ref` 的明确工具绑定；还需要相应 command 许可。实际命令没有网络、没有原项目挂载和写根，只读取授权副本，复用同一 manager/supervisor。输入保留到所有相关进程已证实结束，非零退出、截断、缺失或不匹配证明不输出成功帧。

远程 curator 也已接通代码：`web.curator.bind` 指定监听 IP；非默认 loopback 地址必须同时给出 `advertised_origin`，可表达既有 HTTPS 反向代理入口。Host/Origin 只接受该入口，agentcfg 只展示绑定中的链接。远程反向代理由机器显式提供，代码没有自动发现主机名或启动系统浏览器。真实远程连接仍未验收。

## 联网媒体 CLI（代码接通，真实工具未验收）

`web.media.yt_dlp_tool_ref` 和 `javascript_tool_ref` 分别引用明确的 yt-dlp 与 Node 工具；已有 `ffmpeg_tool_ref` 同时用于远程抽帧。工具需要 `bash/execute` 命令权限，只读依赖目录由 `external_tools.<id>.read_roots` 明确声明（包括工具实际需要的证书与动态库）。不自动使用 PATH 中的其他工具，不继承机器代理或账号。

运行时通过第一方回环中继连接私人 Unix 代理，再使用 `web.services.public` 的声明路线。Linux CLI 保持独立网络命名空间；macOS 只投影一个回环端口和私人 Unix socket，尚待该平台原生验证。代理检查目标与地址、限制连接/字节，所选上游代理失败不会回退直连。撤权检查关闭已有通道；真正进程停止仍由同一 supervisor 证明。

yt-dlp 不加载全局配置、额外插件或动态下载的 JavaScript 组件，Node 运行时显式选择。所选发行物必须具备对应内置组件；当前代码/mock 通过不等于工具安装及真实 YouTube 可用。远程抽帧只接受 HTTPS 视频输入，禁用输入的本地文件协议。截断输出、非零退出或未确认终止均不会作为成功媒体返回。

## GitHub 克隆与产物

`web.github_clone` 需要 `git_tool_ref` 和 `root_ref`。后者引用 `purpose = "write"` 的目录；当前公共写租约要求该目录位于可核验的 Git 工作树内。新产物使用独立 `clone-<随机标识>` 子目录，需普通文件 `write/create` 权限及 Git 的命令执行权限。目录/内容展示分别需要 `ls/list` 与 `read/read` 权限，也会应用拒绝规则。代码不会通过插件自身的文件读取绕过这些权限。

GitHub 服务须显式包含 `https://github.com`；API 内容读取另需 `https://api.github.com`。私人仓库只使用声明的 `githubToken`，以该子进程的临时 Git 配置环境传递，不写入克隆的 `.git/config` 或命令行。禁用全局 Git 配置、credential helper、hook、模板、子模块递归与 HTTPS 之外的协议。克隆及其子进程使用与媒体相同的中继和监督。

成功或已启动的部分克隆作为显式写根中的产物保留，便于继续使用普通工具检查；会话切换不自动删除，以免删除用户后续修改。内存缓存绑定当前运行时。私人驱动输入（包括短期代理 token 和声明的认证数据）在确认终止后清理；重启后只回收本实例已标记、已过期且关联租约不再受保护的输入。原始媒体副本同样按持久租约记录清理，未知活动保留。

## PDF 与完整设置投影

未选择落盘目录时，PDF 提取直接返回 Markdown 正文。`web.pdf_output_root_ref` 引用明确的 write 根后，才经 ordinary write 保存独立文件；根须满足公共 Git 工作区租约要求，写入上限沿用普通工具的 1 MiB 限制。不会默默写入 `/tmp/pi-web-pdf`。固定选择 Gemini/Datalab 却缺该服务或执行失败时，不冒充另一后端成功。

`web.settings` 另支持工具命名、searchRouting、fetchRouting、fetch.timeout、youtube/PDF 开关与边界、Bright Data zone、Firecrawl 版本与 fresh scrape、SERPdive 模型、Datalab 模式与地域。显式路由不能引用未选服务；provider 与 searchRouting 不能同时配置。

SearXNG 私有请求头使用 `web.header_credentials.searxng.<header> = "secret:<id>"`，只投影生成引用。禁止覆盖 Host、代理认证和 HTTP framing 头。Datalab API 地址使用 `web.endpoints.datalabApiBase`，仍需属于声明的 origin。

原生模型字段统一映射：summaryModel → `web.models.summary`，fetch.answerProvider/answerModel → `web.models.answer`，searchModel 与视频/YouTube preferredModel → `web.models.gemini`，OpenAI/xAI 搜索模型 → 对应 `web.models.openai/xai`。原来遍历 openaiSearchProviders 的逻辑由一个明确模型绑定替代。原生 proxy/curatorRemote/clonePath 分别映射到显式 network routes、web.curator 和 web.github_clone.root_ref。
