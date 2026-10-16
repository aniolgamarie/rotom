# 官方基线与跨宿主工具研究

临时设计材料：仅用于开发分支讨论；合入 `main` 前必须删除，或整合到正式文档后移除本临时文件。本地提交不代表设计已采纳或产品已验收。

调研日期：2026-10-16。本文是来源研究，不是安装、平台或账号验收。引用上游性能和安全陈述时保留其范围；本项目尚无对应测量。

## 证据规则与来源冲突

证据按用途区分：固定 tag/commit 下的接口和源码、正式发布说明、浮动 README/manifest、项目说明与精选清单。清单用于发现，发布记录用于证明发生过相应修复，二者都不能证明本机安装与运行通过。最终实现须把浮动资料重新绑定至具体版本。

调研中出现以下冲突，记录处理依据：

| 冲突 | 采用的解释与限制 |
| --- | --- |
| 部分 GitHub main/Releases 页面只显示 Pi 0.99.1/1.0.4，官方 changelog 和 v1.3.0 tag 显示 1.3.0 | 以精确 tag 包清单与官方版本公告交叉确认 1.3.0、2026-10-15；不能确认旧结果具体属于缓存还是更新延迟 |
| Pi 指南列出 Docker Sandboxes 的 Pi kit，但 Docker curated agent 列表未列 Pi | 记录为 Pi 官方提供使用路径，Docker curated 列表未单独背书；不推断已完成组合验收 |
| 插件 main manifest、changelog、npm 发布包可能版本不同 | 分别记录观察；锁定时核对源码提交、tarball、实际 manifest 和许可证，不把某个旧条目的日期套给新版本 |
| 仓库旧 Pi 指南称锁已重建，支持矩阵仍记录 recipe/lock 不匹配 | 本轮不改写历史或认定当前可部署；新支持声明必须绑定新锁和实际证据 |

<a id="o-baseline"></a>
## O01–O12：Pi 原生基线

| 来源 | 一手链接 | 对设计的具体影响 |
| --- | --- | --- |
| O01 发行版本 | [1.3.0 公告](https://pi.dev/changelog/releases/1.3.0)、[总更新日志](https://pi.dev/changelog) | 2026-10-15 的 1.3.0 是研究基线，不是当前仓库部署版本 |
| O02 包身份 | [v1.3.0 package.json](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/package.json) | 包名为 `@earendil-works/pi-coding-agent`，Node.js >=22.19.0，MIT；旧 scope 不自动等价 |
| O03 CLI | [固定版本命令行文档](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/cli.md) | 存在显式会话目录、资源发现开关、项目信任覆盖及工具选项 |
| O04 配置 | [configuration.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/configuration.md) | agent directory、项目目录、原生认证和上下文文件分开；项目发现不只等于 `.pi/extensions` |
| O05 设置 | [settings.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/settings.md) | 优先使用模型、压缩、终端和主题设置；原生资源数组合并需与管理器数组替换区别处理 |
| O06 包管理 | [packages.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/packages.md) | 支持精确 npm/git ref、本地路径、资源过滤；固定包版本不自动固定全部依赖 |
| O07 MCP | [mcp.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/mcp.md) | stdio/streamable HTTP、OAuth、tool exposure、资源与连接管理已有原生接口 |
| O08 Codemode | [codemode.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/codemode.md) | 工具组合交给上游；QuickJS 的脚本边界不代表其调用的工具也受 OS 沙箱限制 |
| O09 安全 | [security.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/security.md) | 项目信任不隔离工具；项目 `sessionDir` 先于信任；信任后可安装缺失包 |
| O10 扩展 | [extensions.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/extensions.md) | 仅使用公开事件、工具、命令与 UI API；扩展拥有宿主进程权限 |
| O11 会话 | [sessions.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/sessions.md) | 会话继续、分支与压缩优先原生；不能表述为磁盘文件回滚 |
| O12 隔离 | [Pi 当前隔离指南](https://pi.dev/docs/latest/containerization) | 整进程隔离与仅工具隔离要分开；浮动指南不能代替具体版本/平台验收 |

另参考官方[包目录](https://pi.dev/packages)和[扩展示例](https://github.com/earendil-works/pi/tree/v1.3.0/packages/coding-agent/examples/extensions)。包目录收录、示例存在与可维护产品支持是三种不同证据。

## T01：Superpowers

Canonical：[obra/superpowers](https://github.com/obra/superpowers)。MIT；[许可证](https://github.com/obra/superpowers/blob/main/LICENSE)、[发布记录](https://github.com/obra/superpowers/releases)、[移植指南](https://github.com/obra/superpowers/blob/main/docs/porting-to-a-new-harness.md)。本轮未锁定其具体版本，不以仓库热度说明维护周期承诺。

[Pi 支持章节](https://github.com/obra/superpowers#pi)直接说明原生 Pi package：加载 Skills 和一个启动/压缩后注入引导的扩展；子代理和任务列表由可选 companion packages 提供。可核查的[Pi 集成讨论](https://github.com/obra/superpowers/issues/435)有设计边界与测试说明，讨论内容不是已发布包行为的替代证据。

优点是方法论跨宿主复用，规划、调试、验证、审查各有可选择的资源；代价是完整引导带来强制流程、更多读取和子任务。部分 Skills 依赖特定工具名、支持文件和执行假设，不能只复制 SKILL.md 或认为加载成功就适配完成。

设计采用方法型 Skills 的精选子集，优先调试、验证、审查和复杂任务规划。完整引导扩展不默认加载；全套模式须显式选择。方法有助于工作纪律，不能保证每个任务更快、更省 token 或模型一定遵守。

## T02–T03：Spec Kit 与 OpenSpec

| 对比项 | GitHub Spec Kit | OpenSpec |
| --- | --- | --- |
| Canonical | [github/spec-kit](https://github.com/github/spec-kit) | [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) |
| 一手流程 | [workflows](https://github.com/github/spec-kit/blob/main/workflows/README.md)、[开发说明](https://github.com/github/spec-kit/blob/main/DEVELOPMENT.md) | [workflows](https://github.com/Fission-AI/OpenSpec/blob/main/docs/workflows.md)、[团队工作流](https://github.com/Fission-AI/OpenSpec/blob/main/docs/team-workflow.md) |
| 许可 | [MIT](https://github.com/github/spec-kit/blob/main/LICENSE) | [MIT](https://github.com/Fission-AI/OpenSpec/blob/main/LICENSE) |
| 主要载体 | 模板、脚本、agent 资源与可配置工作流 | 变更与规格 Markdown、动作式工作流 |
| 写入与安装 | 初始化会写项目文件；脚本/CLI 是独立依赖 | 初始化/配置也会写项目资源；独立 CLI 管理动作 |
| 适用场景 | 项目已有规格驱动流程或需要统一阶段产物 | 增量变更、提案到归档、项目持续规格 |
| Pi 证据限制 | 本轮未建立某个发行版本完整 Pi 集成已验证的证据 | [支持工具矩阵](https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md)需在最终版本重新核定 Pi 适配 |

二者是项目工作流选择，不能与 Superpowers 的实现方法混为同一产品层。默认不初始化两套，也不让两份任务清单同时成为执行真相源。已有项目用哪套就尊重哪套，明确产物位置后按需调用。

维护证据来自官方仓库、工作流文档与版本锁定时的发布记录；本轮不编造持续支持年限、某个最新版本或 Pi smoke 结果。

## T04–T06：浏览器方案

| 对比项 | Playwright CLI | Playwright MCP | agent-browser |
| --- | --- | --- | --- |
| Canonical | [microsoft/playwright-cli](https://github.com/microsoft/playwright-cli) | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) |
| 主要接口 | 命令行 + Skill | MCP 工具 | 命令行，也提供 Skill/MCP 路径 |
| 作者定位 | coding agent 的紧凑命令工作流 | 持久交互、结构检查、探索 | agent 浏览器命令、快照引用、会话管理 |
| 本地状态 | 命名 session；可选择持久 profile | persistent/isolated profile、server 进程 | 命名 session 与保存状态 |
| 副作用 | 安装 CLI/浏览器，启动浏览器进程 | 另启动 MCP server/浏览器，可能连接用户浏览器 | 安装二进制/浏览器，运行后台组件或浏览器 |
| Pi 关系 | 通用 CLI/Skill 接入，非 Pi 专属承诺 | 通用 MCP 接入，非 Pi 专属承诺 | 通用 CLI/Skill/MCP 接入 |
| 许可 | Apache-2.0 | Apache-2.0 | Apache-2.0 |
| 设计位置 | 默认浏览器模块候选 | 需要 MCP 交互时的替代模式 | 对照候选，暂不并装 |

Microsoft 自己的[MCP/CLI 对比](https://github.com/microsoft/playwright-mcp#playwright-mcp-vs-playwright-cli)支持优先研究 CLI + Skills 的上下文取舍；这是上游陈述，本项目不采用其描述代替 token 基准。CLI 运行和会话说明见其[README](https://github.com/microsoft/playwright-cli)，包信息见[package.json](https://github.com/microsoft/playwright-cli/blob/main/package.json)。agent-browser 的[官方 Skill](https://github.com/vercel-labs/agent-browser/blob/main/skill-data/core/SKILL.md)提醒使用命名会话和保护保存的认证状态。

Pi 专属包装器只有存在通用接口无法覆盖的价值才考虑。浏览器模块不默认 attach 个人日常浏览器、不复制用户 cookies；每个实例/项目使用明确的 session/profile，原生状态保持私有。Linux 浏览器依赖、显示服务器、headless 模式与 macOS/Windows 的差异分别验收。

浏览器能读页面不等于已覆盖高质量正文/PDF抽取。常见网页、动态页面和文档附件需要分开测量；若 CLI 路径不足，再比较 E06 的统一提取能力。

## T07：Context7

Canonical：[upstash/context7](https://github.com/upstash/context7)。官方仓库同时说明 CLI + Skills、MCP 和 Pi 扩展包入口；[客户端文档](https://github.com/upstash/context7/blob/master/docs/resources/all-clients.mdx)明确提到 Pi 的内建 MCP 接入。CLI setup 的 agent 自动发现清单不等于 Pi 专属自动安装已验证。

| 接口 | 价值 | 成本和限制 | 设计选择 |
| --- | --- | --- | --- |
| 原生 MCP 连接 Context7 | 文档工具少；可保持与模型工具调用一致 | 远端账号/OAuth/API key、网络和服务限制 | 文档模块默认候选 |
| `ctx7` CLI + Skill | 跨宿主，已有 CLI 工作流可复用 | CLI 版本与安装、Skill 引用、认证 | 替代入口，不默认重复安装 |
| `@upstash/context7-pi` | 项目提供专门 Pi 扩展入口 | 新增进程内包和 API 兼容维护 | 观察；通用 MCP 不足再比较 |

参考[CLI 文档](https://github.com/upstash/context7/blob/master/docs/clients/cli.mdx)及[许可证](https://github.com/upstash/context7/blob/master/LICENSE)。不同页面的 Node 要求与版本可能不同，锁定时检查真实发布包 engines，不把任一浮动文档数字当统一前提。费用仅记录为外部服务/账号配置，不承诺免费额度。文档质量仍取决于库来源和具体版本，Context7 不是官方文档正确性的保证。

## T08–T10：搜索与内容获取

| 对比项 | Brave Search MCP | Exa MCP | Tavily MCP |
| --- | --- | --- | --- |
| Canonical | [brave/brave-search-mcp-server](https://github.com/brave/brave-search-mcp-server) | [exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server) | [tavily-ai/tavily-mcp](https://github.com/tavily-ai/tavily-mcp) |
| 能力侧重 | 通用 web/news/image/video 等搜索 | 检索与内容服务，托管 MCP 入口 | search/extract/map/crawl |
| 认证与成本类别 | Brave API key、外部服务 | 托管/API 服务；具体工具认证与额度需核定 | key/keyless 路径因工具而异，不能承诺全部免 key |
| 本地运维 | stdio server 或显式 HTTP 部署 | 托管可减少本地进程，仍有远端依赖 | 本地或托管依最终入口 |
| Pi 关系 | 通用 MCP | 通用 MCP | 通用 MCP |
| 首版倾向 | 默认搜索提供方候选 | 替代候选 | 同时需要抽取时的替代候选 |

Exa 的[官方 server descriptor](https://github.com/exa-labs/exa-mcp-server/blob/main/server.json)和 Tavily 的[server 源码](https://github.com/tavily-ai/tavily-mcp/blob/main/src/index.ts)用于核对接入和认证陈述。Brave README 说明 key、环境变量和工具过滤；MCP 官方[servers 清单](https://github.com/modelcontextprotocol/servers/blob/main/README.md)可发现其替代旧参考实现的位置，不能替各服务背书。

每个最终发布包的许可证、工具清单、provider 网络路径和数据条款在 lock 准入时逐项确认；本轮不固定三者版本、不公布实时价格，也不假设服务可用。默认只选一家，不做静默多 provider fallback，避免费用、隐私和错误语义不可解释。

Pi 专属统一 web 包 E06 是另一条实现路线，比较重点是正文抽取质量能否抵偿新增依赖、认证路由与缓存维护；不能因一个接口统一就认为成本更低。

## T11：Serena 与代码语义能力

Canonical：[oraios/serena](https://github.com/oraios/serena)。README 与[使用工作流](https://github.com/oraios/serena/blob/main/docs/02-usage/040_workflow.md)描述基于语言服务器的符号、引用和代码操作，并说明已有 coding harness 时可关闭重复的基础读写/shell工具。GPL-3.0-or-later；许可说明以锁定版本[LICENSE](https://github.com/oraios/serena/blob/main/LICENSE)为准。

适合大仓库的符号导航或大量引用定位。前提是目标语言、语言服务器和项目初始化，可能写索引及 memory；是否启用 memory要显式配置。通过 MCP 接入 Pi 属于协议路径，本轮未确立 Serena 对某个 Pi 版本的专属支持。

首版保留原生 read/grep/find 与 rg；Serena 作为后续 opt-in 模块，要求真实语言样例证明收益后加入。语义能力与全文搜索互补，不以“有 LSP”代替编辑、引用一致性或重构结果验收。

## T12–T15：隔离方式

| 方案 | 隔离位置 | Pi 支持证据 | 主要成本与边界 |
| --- | --- | --- | --- |
| 普通 Docker 容器 | 整个 Pi、扩展及其子进程 | Pi 官方隔离指南给出方案 | 容器、挂载、网络与凭据配置；暴露的工作区仍可被修改 |
| Docker Sandboxes | 整个 agent 所在环境 | Pi 指南提供 kit；Docker curated 列表未列 Pi | 平台/虚拟化/产品版本；代理与共享目录策略，需核对支持范围 |
| NVIDIA OpenShell | 整个沙箱进程树及策略 | 官方 agent 列表把 Pi 标为 Community | Docker/Podman/后端及策略维护，不能称为所有平台同级支持 |
| Gondolin 工具扩展 | Pi 在宿主，选中工具进入 microVM | Gondolin 与 Pi 官方都有接入说明 | 其它扩展仍可能在宿主；环境变量继承与网络策略要核查 |

一手来源：[Pi 隔离指南](https://pi.dev/docs/latest/containerization)、[Docker 入门](https://docs.docker.com/ai/sandboxes/get-started/)、[Docker 安全模型](https://docs.docker.com/ai/sandboxes/security/)、[Docker agent 清单](https://docs.docker.com/ai/sandboxes/agents/)、[NVIDIA/OpenShell README](https://github.com/NVIDIA/OpenShell/blob/main/README.md)、[Gondolin README](https://github.com/earendil-works/gondolin/blob/main/README.md)。OpenShell 与 Gondolin 仓库采用 Apache-2.0；Docker 产品支持条件及条款须独立核查。

Gondolin 项目能力与某个 Pi 示例扩展的实际配置必须区别看待。项目支持 host egress/secret 替换不代表默认 Pi 工具示例自动移除了宿主环境变量。仅工具隔离不能约束未委派的扩展，也不能通过限制 MCP exposure 推导认证文件隔离。

这些方案均不在基础安装中自动部署。首版先支持受信任本机使用；明确需要边界时优先研究整进程隔离。平台与授权不足时保留未验证状态，不把安全模块配置成产品已具备的保证。

## C01–C03：Claude Code 作为能力参照

参考其[扩展机制分工](https://code.claude.com/docs/en/features-overview)、[子代理与 worktree](https://code.claude.com/docs/en/sub-agents)、[checkpointing](https://code.claude.com/docs/en/checkpointing)。这用于建立功能场景和比较边界，不要求复制其内部实现，也不承诺所有 provider 上的体验完全一致。

可借鉴的是按职责组合规则、Skills、外部连接和子代理，并控制上下文成本。自动文件撤销、审批、隔离和后台任务各有自己的限制，不能从 Pi 的会话树或某个插件工具名推导同等语义。
