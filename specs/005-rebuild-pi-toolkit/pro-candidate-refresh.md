# Pro 协作候选刷新

核对日期：2026-10-19。本记录补充[模块准入登记](module-admission.md)中的 Pro 协作证据，输入范围为[协作/状态契约](contracts/collaboration-and-status.md)及 T064–T071。只读取公开 registry、GitHub 资料与发布包，下文区分固定包证据和可变分支观察；未安装、运行或连接候选，也未作宿主原生验证。

## 精确新证据：@tintinweb/pi-subagents 0.22.0

固定 npm 单版本元数据：[registry 元数据](https://registry.npmjs.org/%40tintinweb%2Fpi-subagents/0.22.0)。名称与版本为 `@tintinweb/pi-subagents@0.22.0`，repository 为 [tintinweb/pi-subagents](https://github.com/tintinweb/pi-subagents)，npm `gitHead` 为 `85a704cb8f35c96c0cabfa665b572bab296942e5`，许可为 MIT。发布 integrity 为 `sha512-vkpH930uAi/Y8KOyc4+D7bSNgrL8xX4TAdMF6AWTqFjs2BTxuSobZ4ViA5jcL87FmyKb7O1X+r6ZPiEVTk3GQg==`，与读取 tarball 后计算值相符；tarball SHA-256 为 `149192c14f88a529ae92d118ce6f464006b4ecf13c74f0b3cbfeb3ded758765d`。精确包 `package.json` 的 peer 范围为 Pi AI、coding-agent、TUI `>=1.1.0`，覆盖本设计固定的 Pi 1.3.0；这是静态兼容范围，不是宿主运行结果。

**新增的可行性证据：**精确包 `src/settings.ts:11–34`公开 `maxConcurrentForeground`，可把一般 blocking foreground 顶层 spawn 限为 2；同一处明确它与后台池独立，而且 nested child、detached RPC/mention 及 foreground resume 不占该池。`src/agent-manager.ts:129–156`将其实现为仅 `blocking && top-level && non-workflow`。`src/agent-runner.ts:693–700`显示 agent 配置 `isolated: true` 会令 discovered extensions 与 skills 关闭；`src/agent-runner.ts:847–855`还向 SDK loader 关闭 prompt templates、themes、context files。`src/agent-runner.ts:1020–1033`在 noExtensions 路径把会话可用工具收窄为角色所列的 built-ins。因此公开前置配置能限制子代理使用的内置工具并排除发现的项目扩展/Skills。

**精确包仍保留的并发旁路：**

- `src/index.ts:1210–1232`在可用 UI 时无条件注册 Ctrl+B listener；`src/ui/conversation-viewer.ts:269–276`提供 `b` handoff。两条入口都调用 `AgentManager.sendToBackground`。
- `src/agent-manager.ts:1131–1165`实现 handoff：任务继续运行，计数从 foreground 池移到独立 background 池；源码明确即使后台池已满也会让该任务超限继续运行。由此 `maxConcurrentForeground=2` 不能证明同一主会话所有任务总数不超过 2，也不能保证没有 detached/background 工作。
- `src/index.ts:1744–1747`仍在 `Agent` 工具 schema 暴露 `resume` 参数；`src/index.ts:2090–2125`处理该参数。`src/agent-manager.ts:1171–1231`按 background resume 路径排入后台池，`1233`之后的 foreground resume 则直接恢复旧 session 并 inline 运行，不经过 foreground slot。
- `src/settings.ts:11–34,59–68,144–154,220–227`公开设置并没有 handoff-disable 或 resume-disable 开关。菜单可关闭 scheduling、workflows、agent mentions 和跨完成后的 remembered agents（`src/index.ts:3765–3778,3885–3897`），但这些选项没有删除 foreground handoff listener 或工具 schema 中的 `resume`。限制角色为 `run_in_background: false` 也不能消除运行中 UI handoff。

因此，这个版本比历史上审过的 tintinweb 包多了公开前台并发上限，值得保留为候选；精确发布源码仍证明它无法仅用公开包配置满足“每主会话所有调查严格至多 2、只在前台运行”。本记录不建议以自有 hook/guard 改写插件行为来补齐该缺口。

**SDK 资源关闭边界：**`src/agent-runner.ts:826–846`以 `DefaultResourceLoader` / `createAgentSession` SDK 构造子 session，不启动独立 Pi CLI，因此此处没有子进程 argv 可审。即使角色 `isolated: true`，loader 仍传入 `codemode`、`tool-search`、`mcp` 三个 builtin factories；但 `disabledBuiltinExtensions` 仅依据主 Pi 的 `process.argv` 中 `--no-mcp` 或 `--no-extensions` 设置。主 Pi 使用 `--no-mcp` 时，精确代码会将 MCP builtin 禁用传入子 session；`isolated` 自身不是 MCP 服务关闭保证。`--no-extensions` 会连主扩展一起关闭，不能作为加载本候选的 launcher 配置。已读到代码关于 `-builtin:<name>` 设置会关闭 builtin 的说明（`src/agent-runner.ts:828–836`），但本任务未进一步核验 Pi 1.3 的设置解析运行结果；如采用，仍须由主代理验证确切受管设置和服务启动边界。

精确源码链接使用 npm `gitHead` 固定提交：[`src/settings.ts`](https://github.com/tintinweb/pi-subagents/blob/85a704cb8f35c96c0cabfa665b572bab296942e5/src/settings.ts#L11-L34)、[`src/agent-manager.ts`](https://github.com/tintinweb/pi-subagents/blob/85a704cb8f35c96c0cabfa665b572bab296942e5/src/agent-manager.ts#L1131-L1165)、[`src/index.ts`](https://github.com/tintinweb/pi-subagents/blob/85a704cb8f35c96c0cabfa665b572bab296942e5/src/index.ts#L1210-L1232)、[`src/agent-runner.ts`](https://github.com/tintinweb/pi-subagents/blob/85a704cb8f35c96c0cabfa665b572bab296942e5/src/agent-runner.ts#L826-L855)。

## 本轮其余最新来源交叉核对

| 候选 | 本轮固定来源及结论 |
| --- | --- |
| 官方 Pi 子代理示例 | [Pi v1.3.0 精确示例源码](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/examples/extensions/subagent/index.ts#L2246-L2248) 仍把单次 parallel 批量设为 8、并发设为 4；`2709–2723` 仅由角色配置生成 `--tools`，没有 `--no-extensions` / `--no-mcp` 参数。它是可参考的官方示例，不是满足硬并发 2 与资源闭包的现成方案。 |
| mjakl | npm 当前仍为 [`@mjakl/pi-subagent@3.1.0`](https://www.npmjs.com/package/%40mjakl/pi-subagent?activeTab=versions)。本轮沿用对此精确发布包的既有静态检查：并发常量为 4、单批上限为 8，且调用 `ctx.sessionManager.buildSessionContext()`（精确包 `index.ts:629–644`、`1008–1011`），不满足公开上下文接口与每主硬上限条件。 |
| nicobailon | [GitHub releases](https://github.com/nicobailon/pi-subagents/releases) 当前 latest 为 0.79.1，提交短号 `95683a4`。此判断依据是精确 0.79.1 发布包，而非旧 0.79.0：`src/extension/declaration-pinning.js:98–104` 与 `src/extension/tool-activation.js:52–54`仍调用 ExtensionContext 公共类型未声明的 `sessionManager.buildSessionContext()`；新发布仍有此公开接口接缝问题。 |
| cullenbmacdonald | 本轮未发现可替代此前固定审阅提交的新发布证据；不把旧 peer/API 审阅外推成新版本结论。此前固定源码的异步运行及缺少每主硬并发 2 公开设置仍不足以通过 T064–T071。 |

本轮没有证明候选完整锁、依赖闭包、项目资源发现、取消与后代退出、Pi 1.3 实际会话行为或完整组合通过。所有候选仍须遵循[运行契约](contracts/pi-runtime-and-modules.md)及[协作/状态契约](contracts/collaboration-and-status.md)；本证据不改变任何 `selection`，不授权选择 held/candidate，也不将 T064–T071 记为完成。不得 patch 上游、monkey-patch 宿主或用自建 guard 伪造候选的配额与执行语义。原生验收范围见[独立验收记录](native-acceptance.md)，本候选未执行原生验证。

## 继续推进时的发布复核（2026-10-19）

在本轮已验模块交付后，再次匿名读取下列五个包的固定版本端点和 `latest` 端点，十次请求均为 HTTP 200。每包两份响应的 name、version、gitHead、tarball URL 和 SRI 均与已有固定记录一致；本次查询没有发现更新发布。没有安装或执行候选，也没有启动宿主或调用模型。

| 包 | 本次 `latest` | 公开来源 |
| --- | --- | --- |
| `@tintinweb/pi-subagents` | `0.22.0` | [registry latest](https://registry.npmjs.org/%40tintinweb%2Fpi-subagents/latest) |
| `@mjakl/pi-subagent` | `3.1.0` | [registry latest](https://registry.npmjs.org/%40mjakl%2Fpi-subagent/latest) |
| `pi-subagents` | `0.79.1` | [registry latest](https://registry.npmjs.org/pi-subagents/latest) |
| `@ian-pascoe/pi-minimal-subagents` | `0.19.2` | [registry latest](https://registry.npmjs.org/%40ian-pascoe%2Fpi-minimal-subagents/latest) |
| `@earendil-works/pi-coding-agent` | `1.3.0` | [registry latest](https://registry.npmjs.org/%40earendil-works%2Fpi-coding-agent/latest) |

其中 minimal-subagents 与 Pi 的 registry `gitHead` 仍为 `null`，不能据此声称取得了新的固定源码提交。发布身份未变也不等于本轮重新验证了全部源码、依赖或原生行为；上文已固定候选的准入缺口和实际验收范围继续适用。

### 新候选：@parke.dev/pi-subagent 0.8.0

[固定版本 registry 元数据](https://registry.npmjs.org/%40parke.dev%2Fpi-subagent/0.8.0)给出的 `gitHead` 为 `8a60e2c686ad0a9b3c4aff7847a168313978f838`，发布包为 [pi-subagent-0.8.0.tgz](https://registry.npmjs.org/@parke.dev/pi-subagent/-/pi-subagent-0.8.0.tgz)，SRI 为 `sha512-FXrvIcBv+CAhWQ8nio3ycQbfV0AnFkluz6jd6YkHmFcsSzMiN0grhj6YEW9TOLoaKLOZov7GbBmNhP1pV6fD0A==`。本次对下载包核算 SHA-512，与该 SRI 一致；实现判断来自此精确 tarball 的静态源码。GitHub raw 固定 SHA 请求连接重置，未完成文件与 Git 提交的单独比对，也不使用可变 `main` 曾显示的 0.6.0 代替实际发布包。

该精确包存在可直接调用的后台路径：`src/schema.ts:94–105` 公开 `async` 请求参数，`src/policy.ts:453–469` 在 parallel 和 single 模式都直接传递 `params.async === true`；`src/extension.ts:1249–1253` 随后登记到 `asyncRuns` 并在完成前返回，`1405–1410` 还注册 `subagent_wait`。配置类型 `src/config.ts:33–85`、文件配置白名单 `167–195` 和环境变量解析 `198–219` 没有统一关闭 async 的公开选项。`widget: "off"` 与 `notifications: "off"` 只影响界面和通知，不能关闭该执行路径。

因此，这个精确包不能用已核对的公开配置满足首轮“无后台调查”的条件，不通过 T064 初筛。此处没有继续核验其余并发、工具闭包、取消或后代行为，不把这些未检查项写成失败或通过；不以本地 guard 隐藏参数来补齐限制。

### 未固定来源：Integralist/pi-subagents

[GitHub 仓库](https://github.com/Integralist/pi-subagents)的可变 `main` 资料描述 detached 异步任务、结果等待和恢复能力，分支 package.json 显示 `@integralist/pi-subagents@0.1.0`。本次对该包的 npm `latest` 和包元数据两个端点均为 HTTP 404；GitHub 固定提交请求也未成功，因而没有取得可核对的固定发布包、提交或 integrity。该项仅是社区来源线索，既不准入，也不据可变分支观察断言所有发布版本不合格。

以上复核只补充候选证据，任务仍为 87/96；T064–T071 和 T096 保持开放。此前已验模块、生产文件、默认锁和用户已接受的交付范围未变。

## 用户决策（2026-10-19）

用户决定继续采用社区插件路线，并维持现有公开 API、无上游修改、每主会话严格配额、只读资源闭包、前台运行及取消/退出证据等原约束。Pro 协作暂不准入，等待上游提供满足这些约束的公开配置或行为；本轮不实施 SDK 子代理替代，也不新增仓库自有执行插件、调度器或配额执行器。

该决定保留上文的硬缺口：目前审阅到的社区候选仍未证明可公开配置地同时满足每主会话总并发上限 2、关闭后台 handoff 与 resume 旁路、限制子资源/工具闭包并证明取消及后代退出。此前对 Pi SDK 的静态可行性研究仅用于比较接口，不是候选、替代方案、准入依据或运行验证；不得据此把 T064–T071 标为完成或放宽 held 状态。
