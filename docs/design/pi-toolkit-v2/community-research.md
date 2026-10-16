# Pi 双档工具集：社区候选证据目录

临时设计材料：仅用于开发分支讨论；合入 `main` 前必须删除，或整合到正式文档后移除本临时文件。本地提交不代表设计已采纳或产品已验收。

研究日期：2026-10-16。状态：**研究候选**。本文没有安装包、启动 Pi、调用模型或读取真实认证与会话；README、测试脚本和维护者的性能数字都不是本仓库的实测通过证据。base/pro/观察仅是供主设计取舍的建议，最终选择见本目录的其它设计文档。

来源编号按项目分组，组内给出精确一手页面。除特别注明失败外，下列链接在研究时可通过网页工具读取。`main`/`master` 是浮动证据；本文记录看到的版本和日期，不把它们作为最终锁。后续必须核对源码 commit、npm tarball、最终 package manifest、完整依赖锁和许可证文件。包名相似、旧 scope 或宽泛 peer 范围都不证明 Pi 1.3.0 兼容。

## 候选分布与建议

| 来源 | 实际项目或方案 | 建议位置 | 决策重点 |
| --- | --- | --- | --- |
| [E01](#e01) | 官方 Pi 1.3.0 原生 MCP/codemode | base 基线 | 先使用原生能力，再证明扩展的增量 |
| [E02](#e02) | nicobailon/pi-subagents | pro 候选 | 前后台委派、可观测性；跨宿主版本修复频繁 |
| [E03](#e03) | tintinweb/pi-subagents | pro 对照候选 | 另一套工具和编排语义，不与 E02 同时默认启用 |
| [E04](#e04) | nicobailon/pi-messenger | 观察，可选 pro | 跨会话协作、文件预留；Crew 自带执行引擎 |
| [E05](#e05) | mitsuhiko/agent-stuff（mitsupi） | 观察，按项借鉴 | 真实个人配置集合，整包行为过宽 |
| [E06](#e06) | nicobailon/pi-web-access | pro 候选 | 搜索与抓取；网络路由、认证选择和本地缓存 |
| [E07](#e07) | nicobailon/pi-mcp-adapter | 观察，可选 pro | 替代原生 MCP，存在设置变更和额外依赖 |
| [E08](#e08) | nicobailon/pi-powerline-footer | 可选 pro UI | 已超出纯状态栏；输入、队列、bash 模式 |
| [E09](#e09) | juicesharp/rpiv-mono 的 rpiv-todo | base Todo 候选 | 分支回放、codemode 间接调用后的持久化 |
| [E10](#e10) | code-yeongyu/pi-todotools | Todo 对照候选 | phased todo；旧 todowrite/todoread 已移除 |
| [E11](#e11) | gotgenes/pi-packages 的 permission-system | pro 候选 | 工具门禁与子代理转发，不能当 OS 沙箱 |
| [E12](#e12) | MasuRii/pi-permission-system | 观察 | peers 不含 1.x，安装脚本需要审阅 |
| [E13](#e13) | 官方扩展示例：plan/todo/permissions/status/subagent | base 参考候选 | 公开 API 的最小对照，不等于完整产品 |
| [E14](#e14) | thevibeworks/awesome-pi-agent | 发现入口 | 清单含 fork，逐项核实，不整批导入 |
| [E15](#e15) | qualisero/awesome-pi-agent | 历史观察 | 已归档且 README 明示过时 |
| [E16](#e16) | 历史本地 starter-pi-loop-guard | 待决策 | 本地自有包，不伪装为社区发布项目 |

## 一手证据与适用边界

<a id="e01"></a>
### E01 · 官方 Pi 与当前原生基线

Canonical：[earendil-works/pi](https://github.com/earendil-works/pi)。[v1.3.0 release](https://github.com/earendil-works/pi/releases/tag/v1.3.0) 标为 Latest，页面显示 10 月 15 日发布；这是研究日看到的当前版本。[MIT 许可证](https://github.com/earendil-works/pi/blob/main/LICENSE)。官方 [MCP 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/mcp.md) 已公开 stdio、streamable HTTP、工具与资源接入；[codemode 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/codemode.md) 是工具组合的原生基线。

建议 base 优先原生 MCP/codemode，不能继续用“Pi 没有 MCP”作为 adapter 必选理由。依赖与平台：选定官方运行包及对应平台；MCP server 自身的运行时、网络与凭据另计。未验证：各平台安装、第三方 server、OAuth、取消与恢复。release 记录了内部依赖精确固定和 codemode 取消修复，只能证明上游有对应变更记录。

<a id="e02"></a>
### E02 · nicobailon/pi-subagents

Canonical：[仓库与 README](https://github.com/nicobailon/pi-subagents)，包 `pi-subagents`，公开接入为 `pi install npm:pi-subagents`，通过 Pi 扩展及 SDK 创建子会话。[manifest](https://github.com/nicobailon/pi-subagents/blob/main/package.json) 当时为 0.78.0，MIT，声明 `@earendil-works` peers、typebox，以及 `@js-temporal/polyfill`（日期 API polyfill，非编排服务）、acorn/jiti/undici/yaml 依赖；源码根 manifest 同时 `private: true`，有单独打包脚本，因此不能据此断言 npm 发布内容完全一致。

公开配置：[agents 文档](https://github.com/nicobailon/pi-subagents/blob/main/docs/agents.md) 明确 `tools` 严格 allowlist、`extensions`/`subagentOnlyExtensions`、skills 与上下文继承控制，以及 `allowedAgents` 后代角色约束；[configuration 文档](https://github.com/nicobailon/pi-subagents/blob/main/docs/configuration.md) 明确 `params.sessionDir` → `defaultSessionDir` → 父会话派生目录的优先级，`maxSubagentDepth` 默认 2，子级只能收紧继承限制。前台子代理是父进程内 SDK 会话；`PI_SUBAGENT_PI_BINARY` 只覆盖文档列明的 pane/probe 和部分后台宿主启动，不是任意 CLI argv 透传接口。任意 argv 与每子代理独立 agentDir 覆盖均未确认。继承同 profile 实例可接受，独立 agentDir 不是当前硬要求；仍须验证等效资源约束、会话目录及父子归属。

用途：角色委派、前台/后台、工作流、任务产物及 Fleet/inspector。与原生 SDK 子会话、官方 subagent 示例重叠，增量是编排与可观测管理。[CHANGELOG](https://github.com/nicobailon/pi-subagents/blob/main/CHANGELOG.md) 明确 0.78.0（2026-10-12）修复 Pi 1.2.0 后台启动；早于此版本的兼容声明不可外推。README 的 standalone 支持边界特指过往 Linux x64 版本，不能外推所有 1.3.0 平台。建议 pro 优先评估；未验证：发布包、1.3.0 同步/后台/取消/恢复、模型路由、共享工作区并发、子代理权限与预算。researcher 角色还需要子会话中的 web-access。

<a id="e03"></a>
### E03 · tintinweb/pi-subagents

Canonical：[tintinweb/pi-subagents](https://github.com/tintinweb/pi-subagents)，包 `@tintinweb/pi-subagents`；README 接入 `pi install npm:@tintinweb/pi-subagents`。[manifest](https://github.com/tintinweb/pi-subagents/blob/master/package.json) 为 0.22.0、MIT，peers 为 Pi `>=1.1.0`、typebox，依赖 croner/nanoid。不要改写成 E02 的 npm 包或以 `pi-packages` 镜像替代 canonical。

公开配置：[README frontmatter、scoping 与 persistent settings](https://github.com/tintinweb/pi-subagents/blob/master/README.md) 明确 `tools`、`extensions`、`exclude_extensions`、`skills`、`disallowed_tools`；`session_dir` 在 `persist_session: true` 时指定会话目录，相对路径基于 agent cwd。`maxSubagentDepth` 默认 2，0/1 禁止嵌套，每层须独立配置 `allowed_subagents`。任意子 Pi CLI argv 与每子代理独立 agentDir 覆盖未确认；`--subagents-workflow-file` 是父会话工作流入口，不证明向子代理透传 argv。继承同 profile 实例可接受，但需验证资源约束及 session 归属，不能仅以支持 session_dir 推断完整隔离。

用途：`Agent`、结果查询/steer、后台队列、UI、自定义角色、JavaScript 工作流；与 E02 及官方 SDK 重叠。[CHANGELOG](https://github.com/tintinweb/pi-subagents/blob/master/CHANGELOG.md) 0.22.0（2026-10-13）注明后台完成通知可能破坏旧行为，含 Esc 后待处理通知会再启动 turn 的语义。建议 pro 对照候选，先决定中断语义再选型。[安全策略](https://github.com/tintinweb/pi-subagents/blob/master/SECURITY.md) 明确子代理拥有同一用户权限；嵌套 allowlist 不是 OS 隔离。依赖与平台：Pi SDK、Node 环境，worktree 模式另需 Git。未验证：1.3.0、事件/恢复、嵌套权限、跨平台及包内角色发现。

<a id="e04"></a>
### E04 · pi-messenger 的 canonical 与 Crew 边界

Canonical：[nicobailon/pi-messenger](https://github.com/nicobailon/pi-messenger)，包 `pi-messenger`；公开安装 `pi install npm:pi-messenger`。[manifest](https://github.com/nicobailon/pi-messenger/blob/main/package.json) 0.15.2、MIT，声明 Pi 四个 `@earendil-works` peers 和 typebox。用途：本机文件系统 presence、消息、文件预留、聊天 overlay；Crew 另做任务依赖图和 worker 执行。

[CHANGELOG](https://github.com/nicobailon/pi-messenger/blob/main/CHANGELOG.md) 0.15.2（2026-08-27）修复 Crew worker 的 messenger 工具可用性。README 明确仅可读取 pi-subagents 角色元数据，Crew 仍使用自己的 agents；不能写成 E02 必需依赖。它与 subagents 的任务/角色/并发管理有明显重叠。前提：同机共享可写文件系统、worker 可启动 Pi，TUI 功能需交互终端；Windows 启动处理有上游记录。建议观察或显式 pro 协作组件；未验证：预留是否覆盖所有写入工具、陈旧状态回收、并发任务去重、跨项目隔离与当前 SDK。

<a id="e05"></a>
### E05 · mitsuhiko/agent-stuff：真实配置实例

Canonical：[agent-stuff README](https://github.com/mitsuhiko/agent-stuff/blob/main/README.md)，发布包实际叫 `mitsupi`。[manifest](https://github.com/mitsuhiko/agent-stuff/blob/main/package.json) 1.6.0 导出 extensions/skills/themes/commands，运行依赖 diff、Pi/typebox peers；[LICENSE](https://github.com/mitsuhiko/agent-stuff/blob/main/LICENSE) 为 Apache-2.0（manifest 没有 license 字段，不能猜 MIT）。可经 Pi 包机制或公开扩展加载路径接入，后续应按项过滤。

实例包括 review、file-backed todos、goal 自动延续、session control、tmux 串行子代理、主题与 skills。[CHANGELOG](https://github.com/mitsuhiko/agent-stuff/blob/main/CHANGELOG.md) 有 1.6.0 和 API 适配记录，但条目没有日历日期，本次未取得可核实发布日期，维护时间未知。README 明说个人环境需调整。平台前提按项不同：tmux、Ghostty 分屏、macOS caffeinate/Quick Look 等不能视为通用。与原生会话/工具/UI 重叠；自动信任、工具替换也需单独决策。建议观察和借鉴单项，不默认整包装入。未验证：每个选中资源的当前公开 API、平台、凭据和工具冲突。

<a id="e06"></a>
### E06 · nicobailon/pi-web-access

Canonical：[README](https://github.com/nicobailon/pi-web-access)，包 `pi-web-access`，公开接入 `pi install npm:pi-web-access`。[manifest](https://github.com/nicobailon/pi-web-access/blob/main/package.json) 0.41.0、MIT，Node `>=22.19.0`，Pi/typebox peers；依赖 MCP SDK、Readability/defuddle/linkedom、undici、unpdf 等。用途：搜索、抓取、PDF/视频及 GitHub 内容提取；可另以公开 MCP CLI 服务其它客户端。

[CHANGELOG](https://github.com/nicobailon/pi-web-access/blob/main/CHANGELOG.md) 至少可核实 0.31.0（2026-09-22）的按需工具激活和提供商修复；不将这个日期套在 0.41.0 上。与原生 MCP 接 web server 和模型原生搜索重叠，增量是统一内容提取/路由。README 的 keyless Exa 和 Codex 登录复用是上游承诺，未实际请求；浏览器 cookie、远程抓取器须显式选择，不能默认扫描认证。建议 pro；未验证：1.3.0、网络代理/超时、URL与缓存边界、所有 fallback、平台 PDF/视频工具和计费。

<a id="e07"></a>
### E07 · nicobailon/pi-mcp-adapter

Canonical：[README](https://github.com/nicobailon/pi-mcp-adapter)，包 `pi-mcp-adapter`，公开接入 `pi install npm:pi-mcp-adapter`。[manifest](https://github.com/nicobailon/pi-mcp-adapter/blob/main/package.json) 5.3.1、MIT、Node `>=20`；Pi-ai peers 含 `^1.0.0`，另有 TUI/typebox/zod，依赖 MCP v2 client/core、原生 keyring、QuickJS-WASI 等。[CHANGELOG](https://github.com/nicobailon/pi-mcp-adapter/blob/main/CHANGELOG.md) 5.3.1（2026-10-15）有 Windows secret-command 与 MCP UI 修复。

与原生 MCP 强重叠；增量候选包括延迟 server 生命周期、proxy、MCP Apps/elicitation 等，README 的性能对比是维护者特定测试，不是本仓库结果。README 明示安装/更新会在设置里关闭内建 MCP，移除后需重新打开；它也能导入其它宿主配置。因此建议观察或有明确增量需求时选 pro，不能无声叠加。依赖与平台：keychain 支持、UI 浏览器/窗口、server 自身运行时；Windows shell 行为有特定前提。未验证：1.3.0、设置所有权与回滚、proxy 后权限粒度、OAuth、原生依赖产物、取消和资源释放。

<a id="e08"></a>
### E08 · UI/status：pi-powerline-footer

Canonical：[nicobailon/pi-powerline-footer](https://github.com/nicobailon/pi-powerline-footer)，准确包名 `pi-powerline-footer`，不是推测的 `pi-powerline`。公开 Pi 包安装；[manifest](https://github.com/nicobailon/pi-powerline-footer/blob/main/package.json) 0.20.1、MIT，Pi peers `>=0.81.0`。[CHANGELOG](https://github.com/nicobailon/pi-powerline-footer/blob/main/CHANGELOG.md) 0.20.1（2026-10-12）修复 Pi 1.2.0 中扩展发起 turn 的异常。

用途：模型/推理、git、token、费用、上下文及扩展状态；与 Pi 默认 footer 及官方 `setStatus/setFooter` 示例重叠。README 还包含 sticky bash、编辑器 stash、发送延迟和自动 follow-up；UI 选型要同时审阅这些行为。前提：交互终端；Nerd Font 有 ASCII fallback，git 段需 Git，可选自动 follow-up 涉及额外服务。建议可选 pro UI，先试最少功能。未验证：窄屏/Unicode、状态与 Todo widget 共存、键位、输入队列、停止/恢复、各平台和 1.3.0。

<a id="e09"></a>
### E09 · Todo：@juicesharp/rpiv-todo

Canonical：[rpiv-mono/packages/rpiv-todo](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-todo)，包 `@juicesharp/rpiv-todo`，公开接入 `pi install npm:@juicesharp/rpiv-todo`。[manifest](https://github.com/juicesharp/rpiv-mono/blob/main/packages/rpiv-todo/package.json) 2.13.8、MIT，依赖同系列 rpiv-config，Pi/typebox peers；i18n 为可选 peer。用途是 `todo`、`/todos`、状态面板和分支回放，无需独立模型认证；面板需交互会话。

[CHANGELOG](https://github.com/juicesharp/rpiv-mono/blob/main/packages/rpiv-todo/CHANGELOG.md) 可核实 2.13.5（2026-10-12）修复 codemode/executeTool 间接调用后任务在恢复、reload、树导航、压缩时丢失的问题；抓取的 manifest 已是 2.13.8，不能用旧 changelog 日期证明该版本发布日期。与官方 todo 示例及 E05/E10 重叠。建议 base Todo 候选，但只启用一种 `todo` 注册。未验证：最终 tarball、1.3.0、所有状态回放、非交互工具和多 widget 共存。

<a id="e10"></a>
### E10 · Todo 对照：code-yeongyu/pi-todotools

Canonical：[pi-todotools](https://github.com/code-yeongyu/pi-todotools)，包 `pi-todotools`；README 提供放入 Pi 扩展目录的公开接入方式。[manifest](https://github.com/code-yeongyu/pi-todotools/blob/main/package.json) 0.2.1、MIT、Node `>=22.19.0`，Pi coding-agent/TUI `>=0.87.0`、typebox peers，依赖 strip-ansi。

[CHANGELOG](https://github.com/code-yeongyu/pi-todotools/blob/main/CHANGELOG.md) 0.2.0（2026-07-26）把 todowrite/todoread 替换为 phased `todo`，保留历史状态迁移但不改外部 allowlist，同时移除未完成任务自动续跑。用途是按阶段管理任务与侧栏；与 E09/官方 todo 重叠。建议观察/对照，不同时加载两个同名工具。0.2.1 的具体发布日期本次未核实。未验证：1.3.0、codemode 间接调用持久化、迁移、工具名与 UI 冲突、平台表现。

<a id="e11"></a>
### E11 · 权限：@gotgenes/pi-permission-system

Canonical：[gotgenes/pi-packages/packages/pi-permission-system](https://github.com/gotgenes/pi-packages/tree/main/packages/pi-permission-system)，准确包名 `@gotgenes/pi-permission-system`，经 Pi npm 包扩展机制接入。[manifest](https://github.com/gotgenes/pi-packages/blob/main/packages/pi-permission-system/package.json) 40.2.1、MIT、Node `>=22`，Pi coding-agent/TUI `>=1.0.0`，运行依赖 tree-sitter-bash、web-tree-sitter、zod。[CHANGELOG](https://github.com/gotgenes/pi-packages/blob/main/packages/pi-permission-system/CHANGELOG.md) 40.2.1（2026-10-14），并已出现 40.2.2（2026-10-16）；浮动抓取不同步，最终版本需重新绑定。

用途是工具/bash/MCP/skill 规则与子代理审批转发；与官方 permission 示例重叠但复杂度更高，不能等同系统权限隔离。当前 shell wrapper、路径、转发行为有连续修复记录，不能沿用旧规则的验收结论。建议 pro 候选，base 需求须先明确。前提：WASM/解析依赖、交互审批或明确 headless 拒绝路径；平台 shell 差异需覆盖。未验证：1.3.0、选中 subagent 集成、codemode、内建/adapter MCP、超时和审计脱敏。

<a id="e12"></a>
### E12 · 权限对照：MasuRii/pi-permission-system

Canonical：[MasuRii/pi-permission-system](https://github.com/MasuRii/pi-permission-system)，包 `pi-permission-system`，README 的公开接入为 `pi install npm:pi-permission-system`，与 E11 不是同一个 npm 来源。[manifest](https://github.com/MasuRii/pi-permission-system/blob/main/package.json) 0.8.0、MIT、Node `>=20`/Bun `>=1.1.0`，jsonc-parser 依赖、旧 typebox 与 Pi 0.74–0.80 peers，不含 1.x。[CHANGELOG](https://github.com/MasuRii/pi-permission-system/blob/main/CHANGELOG.md) 0.8.0（2026-07-03）。

用途是规则门禁与审批 UI，与 E11/官方示例重叠。manifest 的 postinstall 在特定扩展目录布局下查找并执行 `scripts/patch-vulnerable-deps.mjs`；这证明存在条件安装副作用，**尚不能证明修改了宿主源码**，也不能跳过治理审阅。建议观察，不进入默认组合。未验证：1.3.0（声明范围不匹配）、npm tarball 安装脚本实际目标、公开接口、转发和跨平台。不得为兼容而修补 Pi 上游。

<a id="e13"></a>
### E13 · 官方扩展示例作为低依赖对照

Canonical：[官方扩展示例索引](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/README.md)，随 Pi 仓库 MIT；通过 `--extension` 或扩展发现目录公开加载。[plan-mode](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/plan-mode) 提供只读探索与步骤跟踪；索引还列出 todo、permission-gate、protected-paths、subagent、status-line/custom-footer。它们展示公开 registerTool、tool_call 与 UI API，不能推断为默认内建、完整权限系统或沙箱。

维护证据是所在项目 v1.3.0（见 E01）；本次未单独核实每个示例最后 commit 日期，不能说所有示例在该 release 都有更新。平台前提按示例区分：纯 todo/status 与 sandbox/Gondolin 的外部依赖不同。建议 base 设计参考，先解决最小功能再决定引入社区包；与 E02–E12 重叠。未验证：选中示例的依赖闭包、1.3.0 行为、状态回放和自定义工具绕过路径。

<a id="e14"></a>
### E14 · 精选清单：thevibeworks/awesome-pi-agent

Canonical：[清单仓库](https://github.com/thevibeworks/awesome-pi-agent)，[README](https://github.com/thevibeworks/awesome-pi-agent/blob/main/README.md) 覆盖扩展、skills、前端与 forks，GitHub 标示 CC0-1.0。用途是发现入口，没有可安装的单一 Pi 功能包；无运行依赖与平台保证。与官方包目录重叠，增量是分类与更多实例。

维护日期：本次读取到当前清单，但未取得可核实 release/commit 日期，明确记为未知，不根据抓取时间或 star 推断维护活跃度。建议观察。清单列入某项目仅是发现线索，不是被列项目能力的一手证据，也不能授权接入 fork。未验证：清单覆盖完整性、每项 canonical、许可证及当前兼容性。

<a id="e15"></a>
### E15 · 历史清单：qualisero/awesome-pi-agent

Canonical：[仓库](https://github.com/qualisero/awesome-pi-agent)，MIT；[README](https://github.com/qualisero/awesome-pi-agent/blob/main/README.md) 现已说明过时并退休，GitHub 标记 Public archive。没有单一运行包、运行依赖或平台保证；用途限历史发现。归档的具体日期与最后 commit 本次未核实，不能给出维护时间。

建议历史观察，不作为当前精选包或 Pi 1.3.0 兼容性依据。它与 E14 及官方包目录重叠；引用过去条目时仍需返回项目一手来源。未验证：历史版本、原链接现状与后续迁移。

<a id="e16"></a>
### E16 · 历史 loop guard：本地来源，不冒充社区包

只读现有 `agents/pi/dependencies.json` 可见 `starter-pi-loop-guard` 为 `kind: local`、版本 0.1.0，资源是 `index.ts`，声明有 LICENSE。此信息只用于识别历史来源；本次不扩散读取 vendor 源码，未核实许可证正文、公开 canonical、维护日期、公开接入 API、依赖与平台，因此这些项均为未知。

研究中尝试的 [npm 精确包页](https://www.npmjs.com/package/starter-pi-loop-guard) 返回网页工具 `Cache miss`；canonical 仍未知，查询失败不证明项目不存在。不能将本地版本或相似名字包装为社区维护证据。建议待主设计决定是否保留自有守卫需求；与原生取消/超时及扩展预算上限可能重叠，具体语义未验证。

## 研究结果的使用限制与任务状态

已完成：识别 11 个实际社区运行包/配置项目、官方基线和示例方案、两份社区清单及一个历史本地来源；核对上述一手 README/manifest/changelog/许可证入口，区分 canonical 与镜像及同名包。没有使用二手文章证明技术能力。

失败待决策：未发现必须修改 Pi 上游的已确定需求；E12 安装副作用的实际目标未审阅，E07 的内建 MCP 设置替换必须由主设计决定所有权与恢复。E16 canonical 未确认。

环境不足未验证：所有包的实际安装、模型调用、宿主启动、平台矩阵、并发/恢复/取消、认证与完整依赖锁均未执行。本次 shell 直接请求 GitHub API 受网络沙箱阻断，改用网页工具读取一手页面；未取得精确日期的条目保持未知。本文不把“未验证”改写为“可用”。

进行中：主代理最终选型、版本绑定和后续验收方案。建议先冻结每类唯一工具提供者，再隔离验证；不要让两个 `todo`、两套委派器、内建与 adapter MCP 在默认配置里竞争所有权。
