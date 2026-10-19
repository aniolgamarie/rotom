# Pi support, decisions and sources

This is the current Base/Pro support boundary. Source research, implementation, dependency
preparation, native loading and account/model use are separate evidence levels. See the
[implementation status](../specs/005-rebuild-pi-toolkit/implementation-status.md),
[acceptance record](../specs/005-rebuild-pi-toolkit/acceptance.md),
[module admission register](../specs/005-rebuild-pi-toolkit/module-admission.md) and
[retirement execution](../specs/005-rebuild-pi-toolkit/retirement-execution.md).

The `review/pi-toolkit-reboot-main` integration candidate has a separate
[source and verification record](../specs/005-rebuild-pi-toolkit/integration-candidate.md).
Native results below retain the original reboot source and lock identities; native, model,
service and performance checks for the replayed candidate are not run in this preparation step.

## Platform and verification scope

| Platform | Manager and dependency scope | Native/account scope |
| --- | --- | --- |
| Linux x86_64 | Isolated manager contracts and frozen-candidate dependency-only rebuilding have evidence; final-candidate records remain separate | Local A/B/C UI checks, shared-default model/session operations, Context7 connection and separate service queries, synthetic-page Chromium operations, and no-account Brave/Cursor loading have bounded evidence; bounded real-tool and cancellation/statistics checks also passed; selected-combination measurements are recorded separately, Brave/Cursor accounts are deferred by user decision |
| macOS | No current Base/Pro rebuild acceptance is claimed | Native loading, process/descendant observation, terminal and account behavior are not run |
| Other platforms | Not declared by the current Pi dependency recipe | No support claim |

A published complete lock or an installed receipt does not prove a theme rendered, an extension
loaded, a provider authenticated or a model request succeeded. Offline doctor reports six separate
stages; `--live` adds route reachability only. Historical Pi 0.84.4/four-profile native results remain
historical. CI configuration is not proof that CI ran.

Initial Linux local acceptance used three independent temporary instances and fictional provider/model bindings
with synthetic placeholder keys. Every host launch used a fresh loopback-only network namespace
with no routes: zero real logins, zero model requests. Each group passed version/help and tmux 3.5a
TUI checks at 60/90/130 columns, Chinese multiline bracketed paste, Ctrl+C clearing, reload and
Ctrl+D exit; the default group also passed bare PTY checks. Final owner totals were A 6, B 4 and C 3,
all idle_confirmed, with no active or unknown records. This is local evidence, not SSH/macOS or
account acceptance. That record is historical; subsequent shared-default requests used real network
access with all model tools disabled. Initial requests, continue, fork, model switch and compaction
passed. Footer input/output values matched SDK usage; all-zero SDK prices did not become billing claims.
Context7 service calls, fixed Chromium operations and the limited Brave/Cursor loading scope are
documented in [supplementary acceptance](../specs/005-rebuild-pi-toolkit/remaining-native-acceptance.md).
The [current delivery record](../specs/005-rebuild-pi-toolkit/current-delivery-acceptance.md)
adds the explicitly authorized synthetic-file tool task, real cancellation/recovery, compaction usage,
positive cache display and explicit acceptance of the three status differences. T037/T038/T058/T059
are complete for that Linux scope. Brave/Cursor real-account acceptance is explicitly deferred.
The tool smoke used an additional validation-only public hook; it does not imply production permission
protection, and did not expose credential bodies or real project files to the model.

A later loopback-only SSH fixture also passed 90-column Chinese paste, clearing, reload and normal
Pi exit for A/B/C. SSH clients and remote managers exited 0; the non-root inetd sshd exited 255 with
disconnect/login-record limitations retained. This is local SSH transport evidence, not a real remote
platform, three SSH widths, or a clean server-exit claim.

## Capability boundaries

| Area | Current decision and behavior | Outstanding evidence or gate |
| --- | --- | --- |
| Host | Unmodified official `@earendil-works/pi-coding-agent@1.3.0`, Node >=22.19.0; complete npm lock per profile | Linux local UI, shared-default sessions and one explicitly authorized synthetic-file tool task passed; other platforms remain unverified |
| Base/Pro | `pi-base` and `pi-pro`, same shared foundation and isolated instances; only main role | Pro investigation remains unavailable |
| Theme/UI | `catppuccin-pi-theme@0.1.6`, four declared flavors; Mocha initializes missing preference, later valid native choice preserved | Local bare PTY/tmux, Chinese paste, resize/reload/exit, Frappe retention and loopback SSH90 passed; real remote SSH/macOS remain unverified; three display differences explicitly accepted |
| Status information | Native UI by default; explicit `pi-footer@0.5.1` with public-event observer and initialized preferences; Powerline 0.20.2 remains held | Rendering/preferences/reload, branch usage through compaction, running cancellation/recovery and positive cache passed; user accepted permission explanation, branch-average speed and narrow-screen details; actual billing remains unknown |
| Investigation | Community-only route retained by user decision; collaboration enabled is rejected | mjakl 3.1.0 requires a private member; tintinweb 0.22.0 can bypass the foreground cap through background/resume. Pro waits for upstream; no custom investigation executor is introduced |
| Builtins | `builtin:codemode` and `builtin:tool-search` are explicit optional resource choices; default empty | Selection is not native execution proof; indirect tool reachability still needs review |
| MCP/external plugins | Default absent; fixed cache-hit-monitor, Context7 4.4.2 and Brave 2.1.4 choices bind complete locks and explicit loading | Context7 native connection/reload and separate external protocol queries passed. Brave shared-key lookup returned missing credentials; synthetic-key connection only passed, with no real search; real-account acceptance is deferred by user decision. Cache diagnostics also displayed 87.6% with SDK cacheRead1280/input182; no savings or billing claim |
| Browser | Optional complete `playwright-cli` Skill selects `@playwright/cli@0.1.22` and a fixed private-session CLI entry; open fixes `--browser=chromium` | Explicit Chromium 1247 preparation and synthetic about:blank DOM input/click/state/close passed; browser exit confirmed. Real sites/accounts remain outside the tested scope; startup/context/resource samples are recorded separately; no automatic download or personal-browser attachment |
| Method resources | Optional bounded C++ investigation and long-command handoff Skills use the shared resource mechanism | No extra CLI/tool installation or background process; actual project tool and terminal behavior requires its own evidence |
| Cursor bridge | Optional fixed unofficial `@rahularya01/pi-cursor@1.4.39`, provider `cursor`, this instance's Pi OAuth only; system credentials disabled and inherited Cursor tokens/routes removed | No-account version/help/doctor-command registration, reload and normal exit passed; login/catalog, entitlement, actual models and billing are deferred by user decision; disable preserves native state |
| Model/editor | Private machine bindings and guarded model environment references; native session/model arguments within declared routes | No automatic account import, route alias or silent provider fallback |
| Ownership | Shared admission and independent runs; Linux child-subreaper observation can release only the current run after complete kernel evidence | Own-process double-fork/setsid probe and Linux native two-main maintenance blocking/release passed; all A/B/C owners ended idle_confirmed. Unavailable observation and old unknown records continue blocking maintenance |

Future collaboration quotas belong to each main run, not to a whole profile. Two independent main
runs could each have two read-only investigations, but no current dispatcher implements that
contract. Cancellation request, parent exit, timeout or file-lock release alone does not prove
resource release. Do not clear owner records or force-stop processes to make maintenance proceed.

The ten status classes are provider/model/reasoning, project/Git branch, input/output usage, cache,
cost, context, session duration, main-session activity, speed and permissions, with explicit
missing-value rules.
These are requirements in the [status/collaboration contract](../specs/005-rebuild-pi-toolkit/contracts/collaboration-and-status.md),
not values that a configuration file can manufacture. Unknown is not zero. The user explicitly accepted
the documented permission explanation, branch-average speed and narrow-screen details; the native-UI
fallback alone was not used to close that gate. `--no-approve` concerns project configuration trust,
not per-tool permission approval or OS isolation.

## Optional candidate recipes

[Optional module recipes](../specs/005-rebuild-pi-toolkit/optional-module-recipes.md) and the
[all-off services example](../examples/pi-services.toml) describe candidate prerequisites and ownership.
Context7, one selected search service, Playwright/browser tooling, web extraction, Cursor bridges,
diagnostics, AST/semantic tools and session process tools are not a simultaneously enabled bundle.
One owner per capability, explicit data/account/cost consent, complete dependencies, native public
APIs, disable/exit behavior and selected-combination tests remain required. Documentation or catalog
presence does not authorize loading, connecting a service or reading another application's credentials.

Existing SpecKit/project methods remain the workflow. No default Task Keeper, Todo platform,
Superpowers boot sequence or custom supervisor is restored. Method Skills require individual source,
license, support-file and tool-mapping review. Public hooks do not imply an OS sandbox; trusted
extensions execute with host-process authority and native tool calls retain their own boundaries.

## Source evidence and attribution

The design observations below were collected on 2026-10-16 and updated on 2026-10-18. They are
static historical observations, not fresh network verification. The active recipe and admission
register are authoritative for exact selected versions, SHA/SRI, license and decision fields.
A fixed tag/commit identifies that source; a floating README, package index or popularity listing
is discovery evidence only. Different canonical projects and scoped/unscoped packages are not
interchangeable. Missing npm gitHead remains null; a release/source commit is not invented as its value.

The official host tarball lacks LICENSE. The separately pinned upstream MIT notice lives in
[pi-coding-agent.LICENSE](../agents/pi/licenses/pi-coding-agent.LICENSE) and is copied to the independent
runtime licenses directory with declared SHA256. It neither modifies host files nor establishes npm
source provenance. Catppuccin's npm package contains its own MIT notice. All upstream authorship,
notices and retained legal/source material keep their original meaning. For example,
[mitsuhiko/agent-stuff](https://github.com/mitsuhiko/agent-stuff) is an Apache-2.0 research source,
not a guessed MIT package or an adopted bundle.

The effective architecture, configuration ownership, discovery, migration and validation decisions
from eight temporary design notes have been consolidated into [architecture](architecture.md),
[the Pi guide](pi.md), [migration](pi-migration.md),
[research](../specs/005-rebuild-pi-toolkit/research.md), the admission register and formal contracts.
Historical branch progress and document-only checks are not implementation or native acceptance.
The following bibliography preserves their public source references, including alternatives that
remain unselected. Upstream performance/security claims are not Rotom measurements.

## Research bibliography

1. [GitHub最新正式release](https://api.github.com/repos/earendil-works/pi/releases/latest)
2. [FAQ](https://ast-grep.github.io/advanced/faq)
3. [C++规则](https://ast-grep.github.io/catalog/cpp/)
4. [CLI指南](https://ast-grep.github.io/guide/tooling-overview)
5. [checkpointing](https://code.claude.com/docs/en/checkpointing)
6. [扩展机制分工](https://code.claude.com/docs/en/features-overview)
7. [子代理与 worktree](https://code.claude.com/docs/en/sub-agents)
8. [Docker agent 清单](https://docs.docker.com/ai/sandboxes/agents/)
9. [Docker 入门](https://docs.docker.com/ai/sandboxes/get-started/)
10. [Docker 安全模型](https://docs.docker.com/ai/sandboxes/security/)
11. [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec)
12. [MIT](https://github.com/Fission-AI/OpenSpec/blob/main/LICENSE)
13. [支持工具矩阵](https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md)
14. [团队工作流](https://github.com/Fission-AI/OpenSpec/blob/main/docs/team-workflow.md)
15. [workflows](https://github.com/Fission-AI/OpenSpec/blob/main/docs/workflows.md)
16. [MasuRii/pi-permission-system](https://github.com/MasuRii/pi-permission-system)
17. [CHANGELOG](https://github.com/MasuRii/pi-permission-system/blob/main/CHANGELOG.md)
18. [manifest](https://github.com/MasuRii/pi-permission-system/blob/main/package.json)
19. [NVIDIA/OpenShell README](https://github.com/NVIDIA/OpenShell/blob/main/README.md)
20. [OrestesK/pi](https://github.com/OrestesK/pi)
21. [个人配置说明](https://github.com/OrestesK/pi/blob/2a8915c5a761dfbd6546bbefd309e334a651216e/README.md)
22. [Cursor作者说明](https://github.com/Rahularya01/pi-cursor)
23. [Cursor固定tag](https://github.com/Rahularya01/pi-cursor/tree/v1.4.39)
24. [`@aliou/pi-processes`](https://github.com/aliou/pi-processes)
25. [shutdown hook](https://github.com/aliou/pi-processes/blob/main/extensions/processes/hooks/cleanup.ts)
26. [进程控制器](https://github.com/aliou/pi-processes/blob/main/src/manager/process-runtime-controller.ts)
27. [ast-grep](https://github.com/ast-grep/ast-grep)
28. [badlogic/pi-skills](https://github.com/badlogic/pi-skills)
29. [pi-skills README](https://github.com/badlogic/pi-skills/blob/90bb51cae36515a648515b633a81c0c6efc8c74d/README.md)
30. [brave/brave-search-mcp-server](https://github.com/brave/brave-search-mcp-server)
31. [pi-todotools](https://github.com/code-yeongyu/pi-todotools)
32. [CHANGELOG](https://github.com/code-yeongyu/pi-todotools/blob/main/CHANGELOG.md)
33. [manifest](https://github.com/code-yeongyu/pi-todotools/blob/main/package.json)
34. [Gondolin README](https://github.com/earendil-works/gondolin/blob/main/README.md)
35. [earendil-works/pi](https://github.com/earendil-works/pi)
36. [MIT 许可证](https://github.com/earendil-works/pi/blob/main/LICENSE)
37. [codemode 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/codemode.md)
38. [MCP 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/mcp.md)
39. [官方扩展示例索引](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/README.md)
40. [固定CLI](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/cli.md)
41. [codemode.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/codemode.md)
42. [configuration.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/configuration.md)
43. [公开环境变量](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/environment-variables.md)
44. [extensions.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/extensions.md)
45. [MCP 连接与 exposure](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/mcp.md)
46. [packages.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/packages.md)
47. [项目信任规则](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/security.md)
48. [sessions.md](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/sessions.md)
49. [v1.3.0 settings](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/settings.md)
50. [版本包清单](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/package.json)
51. [固定schema](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/schemas/settings.schema.json)
52. [Pi扩展类型](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/extensions/types.ts)
53. [Pi会话存储类型](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/src/core/session-manager.ts)
54. [Editor类](https://github.com/earendil-works/pi/blob/v1.3.0/packages/tui/src/components/editor.ts)
55. [v1.3.0 release](https://github.com/earendil-works/pi/releases/tag/v1.3.0)
56. [plan-mode](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/plan-mode)
57. [扩展示例](https://github.com/earendil-works/pi/tree/v1.3.0/packages/coding-agent/examples/extensions)
58. [subagent示例](https://github.com/earendil-works/pi/tree/v1.3.0/packages/coding-agent/examples/extensions/subagent)
59. [exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server)
60. [官方 server descriptor](https://github.com/exa-labs/exa-mcp-server/blob/main/server.json)
61. [github/spec-kit](https://github.com/github/spec-kit)
62. [开发说明](https://github.com/github/spec-kit/blob/main/DEVELOPMENT.md)
63. [MIT](https://github.com/github/spec-kit/blob/main/LICENSE)
64. [workflows](https://github.com/github/spec-kit/blob/main/workflows/README.md)
65. [CHANGELOG](https://github.com/gotgenes/pi-packages/blob/main/packages/pi-permission-system/CHANGELOG.md)
66. [manifest](https://github.com/gotgenes/pi-packages/blob/main/packages/pi-permission-system/package.json)
67. [gotgenes/pi-packages/packages/pi-permission-system](https://github.com/gotgenes/pi-packages/tree/main/packages/pi-permission-system)
68. [`pi-unified-exec`](https://github.com/iamwrm/pi-unified-exec)
69. [主题仓库](https://github.com/joizhang/catppuccin-pi-theme)
70. [CHANGELOG](https://github.com/juicesharp/rpiv-mono/blob/main/packages/rpiv-todo/CHANGELOG.md)
71. [manifest](https://github.com/juicesharp/rpiv-mono/blob/main/packages/rpiv-todo/package.json)
72. [rpiv-mono/packages/rpiv-todo](https://github.com/juicesharp/rpiv-mono/tree/main/packages/rpiv-todo)
73. [microsoft/playwright-cli](https://github.com/microsoft/playwright-cli)
74. [package.json](https://github.com/microsoft/playwright-cli/blob/main/package.json)
75. [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)
76. [MCP/CLI 对比](https://github.com/microsoft/playwright-mcp#playwright-mcp-vs-playwright-cli)
77. [mitsuhiko/agent-stuff](https://github.com/mitsuhiko/agent-stuff)
78. [agent-stuff manifest](https://github.com/mitsuhiko/agent-stuff/blob/0865c849befd2021490679f96a8dee58c84ac857/package.json)
79. [CHANGELOG](https://github.com/mitsuhiko/agent-stuff/blob/main/CHANGELOG.md)
80. [LICENSE](https://github.com/mitsuhiko/agent-stuff/blob/main/LICENSE)
81. [agent-stuff README](https://github.com/mitsuhiko/agent-stuff/blob/main/README.md)
82. [manifest](https://github.com/mitsuhiko/agent-stuff/blob/main/package.json)
83. [作者仓库](https://github.com/mjakl/pi-subagent)
84. [mjakl固定tag](https://github.com/mjakl/pi-subagent/tree/v3.1.0)
85. [servers 清单](https://github.com/modelcontextprotocol/servers/blob/main/README.md)
86. [诊断集合](https://github.com/narumiruna/pi-extensions)
87. [作者集合](https://github.com/nicknisi/pi-extensions)
88. [README](https://github.com/nicobailon/pi-mcp-adapter)
89. [CHANGELOG](https://github.com/nicobailon/pi-mcp-adapter/blob/main/CHANGELOG.md)
90. [manifest](https://github.com/nicobailon/pi-mcp-adapter/blob/main/package.json)
91. [nicobailon/pi-messenger](https://github.com/nicobailon/pi-messenger)
92. [CHANGELOG](https://github.com/nicobailon/pi-messenger/blob/main/CHANGELOG.md)
93. [manifest](https://github.com/nicobailon/pi-messenger/blob/main/package.json)
94. [nicobailon/pi-powerline-footer](https://github.com/nicobailon/pi-powerline-footer)
95. [对应源码](https://github.com/nicobailon/pi-powerline-footer/blob/e06267494593c9006b014f42706a8d9e9259a417/index.ts)
96. [精确配置类型](https://github.com/nicobailon/pi-powerline-footer/blob/e06267494593c9006b014f42706a8d9e9259a417/powerline-config.ts)
97. [segment实现](https://github.com/nicobailon/pi-powerline-footer/blob/e06267494593c9006b014f42706a8d9e9259a417/segments.ts)
98. [CHANGELOG](https://github.com/nicobailon/pi-powerline-footer/blob/main/CHANGELOG.md)
99. [manifest](https://github.com/nicobailon/pi-powerline-footer/blob/main/package.json)
100. [Powerline固定源码](https://github.com/nicobailon/pi-powerline-footer/tree/e06267494593c9006b014f42706a8d9e9259a417)
101. [仓库与 README](https://github.com/nicobailon/pi-subagents)
102. [委派器对应源码](https://github.com/nicobailon/pi-subagents/blob/1e272e942bd8d2e6446494ce5de7a21a3f58ab55/src/extension/tool-activation.ts)
103. [CHANGELOG](https://github.com/nicobailon/pi-subagents/blob/main/CHANGELOG.md)
104. [agents 文档](https://github.com/nicobailon/pi-subagents/blob/main/docs/agents.md)
105. [configuration 文档](https://github.com/nicobailon/pi-subagents/blob/main/docs/configuration.md)
106. [manifest](https://github.com/nicobailon/pi-subagents/blob/main/package.json)
107. [0.79.0发布说明](https://github.com/nicobailon/pi-subagents/releases/tag/v0.79.0)
108. [nicobailon 0.79.1发布](https://github.com/nicobailon/pi-subagents/releases/tag/v0.79.1)
109. [README](https://github.com/nicobailon/pi-web-access)
110. [CHANGELOG](https://github.com/nicobailon/pi-web-access/blob/main/CHANGELOG.md)
111. [manifest](https://github.com/nicobailon/pi-web-access/blob/main/package.json)
112. [obra/superpowers](https://github.com/obra/superpowers)
113. [Pi 支持章节](https://github.com/obra/superpowers#pi)
114. [Superpowers Pi集成](https://github.com/obra/superpowers/blob/bb92a77741419a4ab5f06e711a283343f1ada0c3/.pi/extensions/superpowers.ts)
115. [许可证](https://github.com/obra/superpowers/blob/main/LICENSE)
116. [移植指南](https://github.com/obra/superpowers/blob/main/docs/porting-to-a-new-harness.md)
117. [Pi 集成讨论](https://github.com/obra/superpowers/issues/435)
118. [发布记录](https://github.com/obra/superpowers/releases)
119. [oraios/serena](https://github.com/oraios/serena)
120. [LICENSE](https://github.com/oraios/serena/blob/main/LICENSE)
121. [使用工作流](https://github.com/oraios/serena/blob/main/docs/02-usage/040_workflow.md)
122. [仓库](https://github.com/qualisero/awesome-pi-agent)
123. [README](https://github.com/qualisero/awesome-pi-agent/blob/main/README.md)
124. [tavily-ai/tavily-mcp](https://github.com/tavily-ai/tavily-mcp)
125. [server 源码](https://github.com/tavily-ai/tavily-mcp/blob/main/src/index.ts)
126. [清单仓库](https://github.com/thevibeworks/awesome-pi-agent)
127. [README](https://github.com/thevibeworks/awesome-pi-agent/blob/main/README.md)
128. [tintinweb/pi-subagents](https://github.com/tintinweb/pi-subagents)
129. [CHANGELOG](https://github.com/tintinweb/pi-subagents/blob/master/CHANGELOG.md)
130. [README frontmatter、scoping 与 persistent settings](https://github.com/tintinweb/pi-subagents/blob/master/README.md)
131. [安全策略](https://github.com/tintinweb/pi-subagents/blob/master/SECURITY.md)
132. [manifest](https://github.com/tintinweb/pi-subagents/blob/master/package.json)
133. [tmux](https://github.com/tmux/tmux/wiki)
134. [upstash/context7](https://github.com/upstash/context7)
135. [许可证](https://github.com/upstash/context7/blob/master/LICENSE)
136. [CLI 文档](https://github.com/upstash/context7/blob/master/docs/clients/cli.mdx)
137. [客户端文档](https://github.com/upstash/context7/blob/master/docs/resources/all-clients.mdx)
138. [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser)
139. [官方 Skill](https://github.com/vercel-labs/agent-browser/blob/main/skill-data/core/SKILL.md)
140. [总更新日志](https://pi.dev/changelog)
141. [1.3.0 公告](https://pi.dev/changelog/releases/1.3.0)
142. [Pi 当前隔离指南](https://pi.dev/docs/latest/containerization)
143. [包目录](https://pi.dev/packages)
144. [包目录](https://pi.dev/packages/%40nicknisi/pi-ast-grep)
145. [npm官方包](https://registry.npmjs.org/%40earendil-works%2Fpi-coding-agent)
146. [`@ian-pascoe/pi-minimal-subagents 0.19.2`](https://registry.npmjs.org/%40ian-pascoe%2Fpi-minimal-subagents/0.19.2)
147. [精确0.2.1元数据](https://registry.npmjs.org/%40kvidzibo%2Fpi-web-access/0.2.1)
148. [`@mjakl/pi-subagent 3.1.0`](https://registry.npmjs.org/%40mjakl%2Fpi-subagent/3.1.0)
149. [缓存诊断精确元数据](https://registry.npmjs.org/%40narumitw%2Fpi-cache-hit-monitor/0.1.1)
150. [工具诊断精确元数据](https://registry.npmjs.org/%40narumitw%2Fpi-tool/0.3.2)
151. [AST npm元数据](https://registry.npmjs.org/%40nicknisi%2Fpi-ast-grep)
152. [Cursor精确元数据](https://registry.npmjs.org/%40rahularya01%2Fpi-cursor/1.4.39)
153. [精确发布包](https://registry.npmjs.org/@ian-pascoe/pi-minimal-subagents/-/pi-minimal-subagents-0.19.2.tgz)
154. [精确tarball](https://registry.npmjs.org/@kvidzibo/pi-web-access/-/pi-web-access-0.2.1.tgz)
155. [精确发布包](https://registry.npmjs.org/@mjakl/pi-subagent/-/pi-subagent-3.1.0.tgz)
156. [主题精确元数据](https://registry.npmjs.org/catppuccin-pi-theme/0.1.6)
157. [精确发布包](https://registry.npmjs.org/pi-powerline-footer/-/pi-powerline-footer-0.20.2.tgz)
158. [`pi-powerline-footer 0.20.2`](https://registry.npmjs.org/pi-powerline-footer/0.20.2)
159. [`pi-subagents 0.79.0`](https://registry.npmjs.org/pi-subagents/0.79.0)
160. [npm 精确包页](https://www.npmjs.com/package/starter-pi-loop-guard)
