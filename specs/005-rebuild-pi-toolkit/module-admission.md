# Pi 重建模块准入登记

核对日期：2026-10-18。任务 T004；固定输入为 [research](research.md)、
[运行契约](contracts/pi-runtime-and-modules.md) 与[协作/状态契约](contracts/collaboration-and-status.md)。
本登记区分历史静态审阅和后续显式依赖维护；新增精确资料与ignore-scripts安装证据见末节。
2026-10-19已完成限定Linux本地A/B/C检查，以及共享默认模型、D–G局部原生/服务与性能
补充验证，分别见[原生验收](native-acceptance.md)和[补充验收](remaining-native-acceptance.md)。
本轮新增有界真实工具、状态多轮/压缩/取消和正缓存证据，用户接受三处显示差异；Brave/Cursor真实账号按明确决定延后，其他平台未验证。当前范围见[本轮交付验收](current-delivery-acceptance.md)。
`selection` 是设计选择，不能替代准入或运行结果；局部通过不表示完整组合或账号验收。
`candidate` 不得自动加载，`held` 不得选择或入新锁。未记录的身份/许可保持未核实，不能猜测。

## 1. 固定基础与已知 held

| 模块 / canonical | 精确发布物与来源身份 | 许可 | 公开 API 核对、decision / selection | 验证层级与下一条件 |
| --- | --- | --- | --- | --- |
| 官方宿主：[earendil-works/pi](https://github.com/earendil-works/pi) | `@earendil-works/pi-coding-agent@1.3.0`；[精确 npm 元数据](https://registry.npmjs.org/%40earendil-works%2Fpi-coding-agent/1.3.0)含 tarball/SHA-512 integrity；npm `gitHead=null`，不猜源码提交；[v1.3.0 release](https://github.com/earendil-works/pi/releases/tag/v1.3.0)只作交叉核对 | MIT；tarball无LICENSE，独立固定提交法律材料已纳入锁（见npm-script-audit与dependencies.json） | 官方 Node CLI、settings/schema、MCP、资源关闭与显式加载参数已作资料核对；`candidate / true`，Base/Pro 共用 | 静态与Linux完整npm闭包/忽略脚本安装已核；Linux本地无账号A/B/C范围passed，其余原生/账号门开放；Node ≥22.19.0 是机器前提，run 不自动下载 |
| 静态主题：[joizhang/catppuccin-pi-theme](https://github.com/joizhang/catppuccin-pi-theme) | `catppuccin-pi-theme@0.1.6`；[精确元数据](https://registry.npmjs.org/catppuccin-pi-theme/0.1.6)；源码身份 `1d5261b857061a1ba2990f329ca2572aa403e920`；[精确 tarball](https://registry.npmjs.org/catppuccin-pi-theme/-/catppuccin-pi-theme-0.1.6.tgz) | 发布包含 MIT LICENSE，已静态核对 | 仅 `themes`，无普通运行依赖；JSON name 为 `catppuccin-latte`、`catppuccin-frappe`、`catppuccin-macchiato`、`catppuccin-mocha`；`candidate / true`，初始 Mocha，可按合法机器覆盖改 flavor | 精确包、完整锁及资源身份已核；Linux本地真实PTY/tmux三宽度渲染及Frappe偏好保留passed，SSH/macOS未执行 |
| 状态栏：[nicobailon/pi-powerline-footer](https://github.com/nicobailon/pi-powerline-footer) | `pi-powerline-footer@0.20.2`；[精确元数据](https://registry.npmjs.org/pi-powerline-footer/0.20.2)；源码身份 `e06267494593c9006b014f42706a8d9e9259a417` | 精确包package.json/README声明MIT，tarball未含LICENSE，法律材料仍未闭合 | 精确包存在 Editor 内部 state/history 读取、lastWidth 写入及方法包装；关闭 fastRender/显示段不能排除全部路径，未确认 footer-only 开关；`held / false` | 静态审阅已发现不满足宪章 VI；原生/账号均未执行。等待公开接口版本重新审包；原生 UI 回退不代表十类信息对齐完成 |
| 协作：[mjakl/pi-subagent](https://github.com/mjakl/pi-subagent) | `@mjakl/pi-subagent@3.1.0`；[精确元数据](https://registry.npmjs.org/%40mjakl%2Fpi-subagent/3.1.0)；源码身份 `6d05481a475c08bfd1ee5a623d5b742fb95b2147`；[精确 tarball](https://registry.npmjs.org/@mjakl/pi-subagent/-/pi-subagent-3.1.0.tgz) | 精确包包含MIT LICENSE，正文SHA256见下方精确审包记录 | 公开深度参数设1有禁继续委派路径；并发常量4、批量最多8，无已确认每主强制2公开键；只读工具/MCP/Codemode/恢复与完整后代退出闭包仍未验证；`held / false` | 已知静态条件不满足每主会话至多 2；两个主会话各 2 的隔离也未验证。Pro 协作 `not_ready`；不补造调度器、修改包或调用私有字段 |

完整锁需记录发布物实际 integrity、source URI、许可、peers、工具链、脚本与传递依赖；
已重新审包的integrity、许可和入口证据见第6节；不以git commit代替发行物校验。
源码身份与锁生成身份分别按 [DependencyIdentity](data-model.md#3-dependencyidentity) 记录。

## 2. 按需候选

以下默认`selection=false`，不进入默认Base/Pro加载或连接路径。后续已完成静态admitted的
固定选择见第9节；表中早期candidate结论不代表这些新入口仍被拒绝。
精确身份缺失、浮动源码或未闭合的来源均阻止入锁；不把旧版本问题自动转移给新包。
公开安装示例只能作为接口资料；受管方案不用 `pi install` 或浮动 npx/uvx 安装。

| 类别 / canonical | 固定研究版本、identity、许可 | 已核公开入口与收益 / 未满足条件 |
| --- | --- | --- |
| 订阅：[Rahularya01/pi-cursor](https://github.com/Rahularya01/pi-cursor) | `@rahularya01/pi-cursor@1.4.39`；[元数据](https://registry.npmjs.org/%40rahularya01%2Fpi-cursor/1.4.39)；`ef3cafb5c38081ce6e06df8e594241aabd9621e3`；MIT正文已核（第8节） | 非官方 Connect/protobuf 桥；Node ≥22、Pi peers 和 integrity 存在有静态资料；`PI_CURSOR_SYSTEM_CREDENTIALS=0` 公开关闭系统凭据复用。entitlement、journal、账号/费用路线与 Pi 1.3 组合待验 |
| 缓存诊断：[narumiruna/pi-extensions](https://github.com/narumiruna/pi-extensions) | `@narumitw/pi-cache-hit-monitor@0.1.1`；[元数据](https://registry.npmjs.org/%40narumitw%2Fpi-cache-hit-monitor/0.1.1)；`70a034c1be212dd142969f9f17f8dfc894fbdf2f`；实际MIT正文已核（第8节） | `src/index.ts`、Pi peers、无普通运行依赖有资料；只观察上报，不能推算真实账单；隐藏 widget 不等于禁用 |
| 工具诊断：同一作者集合 | `@narumitw/pi-tool@0.3.2`；[元数据](https://registry.npmjs.org/%40narumitw%2Fpi-tool/0.3.2)；`76f42aeaec16aabc98af2b50ae5261e62e1c7935`；实际MIT正文已核（第8节） | `dist/index.ts`、依赖 `@narumitw/pi-tui-kit ^0.59.0` 有资料；加载成本、统计范围与退出待验 |
| 会话内进程：[aliou/pi-processes](https://github.com/aliou/pi-processes) | `@aliou/pi-processes@0.13.2`；[元数据](https://registry.npmjs.org/%40aliou%2Fpi-processes/0.13.2)；提交`434fa0a860b1fa4fe9fccdc986964d865ef98e47`/SRI已核；tarball无LICENSE正文 | Node ≥22.19；公开启动/输出/停止为候选。精确关闭hook发SIGKILL且不等待终止（第8节）；SIGKILL/OOM、取消、脱组后代与日志边界待验，不承担跨重启恢复 |
| 结构查询：[nicknisi/pi-extensions](https://github.com/nicknisi/pi-extensions) | `@nicknisi/pi-ast-grep@0.3.1`；[元数据入口](https://registry.npmjs.org/%40nicknisi%2Fpi-ast-grep)；npm `gitHead=null`，tag→发布物对应未闭合；许可未记录 | 0.3.0 的 ast_search/ast_rewrite 资料只作历史，不能当 0.3.1 审包。先比 [ast-grep CLI](https://github.com/ast-grep/ast-grep) + 完整 Skill；CLI版本/身份/许可也待固定；不能代替 clangd/编译器语义 |
| 网页 A：[nicobailon/pi-web-access](https://github.com/nicobailon/pi-web-access) | `pi-web-access@0.41.0` 为已有 manifest 研究版本，源码提交`d47dc040552505e3b135d0136a0b15eaf4bdba52`；精确SRI与实际MIT LICENSE已核（第7节） | 公开 Pi/MCP 路线；搜索/正文/PDF/视频为该项目资料，provider/fallback/代理/工具依赖/缓存待验；不复用旧补丁包 |
| 网页 B：[scoped 精确发布元数据](https://registry.npmjs.org/%40kvidzibo%2Fpi-web-access/0.2.1) | `@kvidzibo/pi-web-access@0.2.1`；`d25304a6e3478439568e168c6345017cfd3b603e`；实际MIT LICENSE和SRI已核（第7节）；不猜与网页A同源 | 精确包有 `mcp/cli.mjs`、web_search/fetch_content/get_search_content；无 PDF/video/Git clone；依赖 Readability/linkedom/turndown/TypeBox/MCP SDK；固定 provider、禁 fallback、每实例缓存路径待验 |
| 文档：[upstash/context7](https://github.com/upstash/context7) | 版本/发布物/integrity/精确许可未固定 | 公开原生 MCP，CLI + Skills 作替代；锁定真实 engines、工具过滤、账号/失败路径；不为所有调查预连 |
| 搜索：[Brave MCP](https://github.com/brave/brave-search-mcp-server)；[Exa MCP](https://github.com/exa-labs/exa-mcp-server)；[Tavily MCP](https://github.com/tavily-ai/tavily-mcp) | 三者版本/发布物/integrity/精确许可均未固定，分别登记 | 首先比较 Brave；明确用户选一个服务。需核对真实认证、工具过滤、查询接收方与费用；Exa/Tavily 不作静默 fallback |
| 浏览器：[Playwright CLI](https://github.com/microsoft/playwright-cli) + 完整 Skill | 版本/发布物/integrity未固定；既有资料 Apache-2.0，精确许可待核 | 首选公开 CLI；[Playwright MCP](https://github.com/microsoft/playwright-mcp)、[agent-browser](https://github.com/vercel-labs/agent-browser) 为替代，均版本未固定、资料 Apache-2.0；只用专用 profile/session，不接管个人浏览器 |
| PTY：[pi-unified-exec](https://github.com/iamwrm/pi-unified-exec) | 版本/提交/integrity/许可未固定 | stdin/PTY/REPL 需求触发，与 processes 二选一；不是跨重启恢复 |
| C++语义：[Serena](https://github.com/oraios/serena)、编译器/clangd | Serena版本未固定，资料 GPL-3.0-or-later；其余工具版本/许可按项目另定 | 原生 CLI/语言服务器优先；需项目索引/写入/取消/进程与数据边界；不默认新增常驻服务 |
| 跨终端长命令：[tmux](https://github.com/tmux/tmux) + 项目日志 | Pi 不另行锁定/安装；实际工具身份由独立 termcfg/项目所有者核对 | 复用既有工具前提，不覆盖 termcfg；工作目录、日志、显式停止与会话归用户/项目 |

## 3. 替代与方法资源的限制

| 候选 / 来源 | 身份与许可状态 | 决议理由 |
| --- | --- | --- |
| [nicobailon/pi-subagents](https://github.com/nicobailon/pi-subagents) | `pi-subagents@0.79.1`；提交`95683a4427e1e4af8de03f1a9ca03ec4c2799b73`；精确SRI及实际MIT LICENSE见第6节 | `candidate / false`；本版本调用公开ExtensionContext类型未声明的sessionManager.buildSessionContext；会话spawn总预算不是每主活动并发2；完整闭包仍未验证 |
| [tintinweb/pi-subagents](https://github.com/tintinweb/pi-subagents) | `@tintinweb/pi-subagents@0.22.0`；提交`85a704cb8f35c96c0cabfa665b572bab296942e5`；精确SRI及实际MIT LICENSE见第6节 | `candidate / false`；不得复用旧仓库0.19.0补丁发行；后台默认10、前台无限、嵌套绕名额；Explore角色有bash，提示只读不是强制边界 |
| [Ian minimal-subagents](https://registry.npmjs.org/%40ian-pascoe%2Fpi-minimal-subagents/0.19.2) | `@ian-pascoe/pi-minimal-subagents@0.19.2`，npm `gitHead=null`，精确SRI及实际MIT LICENSE见第6节 | `candidate / false`；当前精确包导入未导出的dist/extensions/mcp/config.js，加载失败回退连接全部MCP；省略子tools继承root工具；不以旧版本方法覆盖结论归罪当前包 |
| [官方 subagent 示例](https://github.com/earendil-works/pi/tree/v1.3.0/packages/coding-agent/examples/extensions/subagent) | v1.3.0，随官方MIT；本表不另建运行包 | `candidate / false`；只作公开契约对照，不复制成长驻自有执行平台 |
| [mitsuhiko/agent-stuff](https://github.com/mitsuhiko/agent-stuff/tree/0865c849befd2021490679f96a8dee58c84ac857) | 固定源码 `0865c849befd2021490679f96a8dee58c84ac857`；Apache-2.0资料 | `candidate / false`；只研究资源分层，若选单项须另固定完整目录、依赖、许可与退出，不整包加载 |
| [badlogic/pi-skills](https://github.com/badlogic/pi-skills/tree/90bb51cae36515a648515b633a81c0c6efc8c74d) | 固定源码 `90bb51cae36515a648515b633a81c0c6efc8c74d`；正式research未记录许可 | `candidate / false`；完整小型Skill包方法参考，未选具体资源 |
| [Superpowers](https://github.com/obra/superpowers/tree/bb92a77741419a4ab5f06e711a283343f1ada0c3) | 固定源码 `bb92a77741419a4ab5f06e711a283343f1ada0c3`；MIT资料 | `candidate / false`；只参考跨harness映射，不自动引导或全量装载 |
| [现有SpecKit](https://github.com/github/spec-kit) | 复用仓库既有 `.specify/` 与 skills，版本/来源仍由其现有管理记录核对 | 保留既有项目流程；这不是新增Pi模块准入，不默认增加Todo或OpenSpec初始化 |

## 4. 每项数据、账号、费用和退出前置

| 范围（覆盖上表各模块） | 数据/账号/费用 | 状态与退出要求 |
| --- | --- | --- |
| 宿主、主题、原生 builtin | 宿主按明确模型/provider发送上下文，账号仅本实例原生home或SecretRef；主题本身静态，无账号/外发/模型费用 | 保持账号/会话与运行包分离；关闭资源停止后续加载，不能自动删除会话或终止用户进程 |
| 协作候选与示例 | 子任务输入、结果、模型请求/观察身份逐项声明；实际模型调用按选定provider计费，不自动复制认证或路由其他账号 | 每主会话最多2，名额至退出确认；结果/取消/后代分开；禁递归、无后台、完整只读工具闭包待核，不授予shell桥 |
| Powerline、诊断候选 | 费用/缓存/用量只按可确认范围显示；模型生成文案/额外请求须独立显式核对，不能承诺零成本 | 选择false即不加载；记录本地状态及UI退出，不以隐藏widget代替禁用，不复建旧footer监督链 |
| Cursor | 非官方订阅桥接收运行上下文；明确entitlement/订阅费用；系统凭据复用关闭，认证来源/journal须在启用前核对 | 每实例journal/cache归属与退出待核；不读取真实认证验证本表、不自动删除日志或账号 |
| Context7、Brave、Exa、Tavily | 查询/库名/外发文本和接收服务明确；API key/OAuth由明确绑定注入；费用/额度独立核对，不承诺免费 | 关闭后不再连接；stdio进程/HTTP连接/缓存明确归属；禁止静默fallback或把私有代码/名称自动送出 |
| 网页A/B | URL、搜索文本、远端抓取器及cookie复用需明确；账号、provider及收费不能互相继承 | 精确包缓存路径和每实例隔离待核；网页B默认原生home缓存的资料不能证明适用于受管实例；TTL不等于自动销毁 |
| Playwright CLI/MCP、agent-browser | 页面、DOM、截图和认证状态可能敏感；专用浏览器profile/session，远端服务另核费用 | 浏览器/下载/trace/cache与退出由模块声明，不接管个人浏览器，不自动删除用户数据 |
| ast-grep、clangd、Serena、方法Skill | 项目路径、源码/索引、本地输出边界明确；如涉及模型或外部服务另声明，不能假定全本地 | 搜索与改写分开；限定目录，写入另核冲突；索引/进程停止/支持文件与许可完整保留 |
| processes、unified-exec、tmux | 命令、环境、输出日志及工作目录归属明确；命令引发的模型/服务费用另核 | 会话内退出与OS后代释放分别确认；tmux由用户/项目持有，不承诺跨崩溃恢复或自动重放 |

## 5. 证据状态与后续门禁

已完成：固定静态输入、完整锁/按选管线，Linux本地UI、共享模型会话操作、Context7连接及
独立服务查询、固定Chromium合成页面操作，以及Brave/Cursor无账号加载的限定范围。
已完成补充：有界真实工具与十类状态门；用户接受权限说明、分支均速、窄屏详情。已完成：本轮所选四模块六场景/组合及相同静态基础的fresh应用级首次/重复测量，结果在本轮交付记录收口。
等待上游：Powerline私有接口及社区调查插件边界缺口仍存在；用户已决定Pro等上游，
不实施自有执行插件。最新[精确候选证据](pro-candidate-refresh.md)保留后台/resume旁路。
按用户决定延后：Brave真实凭据/搜索及Cursor本实例OAuth/权益；其他未验平台：真实远端机器、macOS；
不把合成key初始化当认证成功。其它未执行项按补充验收单列。

升级或选择任何模块前重核精确canonical/版本/发布物、许可、公开API、读取位置、peer/脚本/
完整闭包与状态边界，再分别做隔离/原生/授权账号检查。每类单一所有者；未选模块不加载、不连接。
本表的静态资料本身不证明运行结果；实际安装与局部原生证据按acceptance分列，不外推真实只读、其它平台、费用或完整状态栏信息对齐。

## 6. 精确 UI / 协作发布物复审（2026-10-19）

本节覆盖T053/T063的静态审阅，不关闭T054/T064。所有tarball从对应精确registry元数据
地址取得并核验SHA512 SRI，未安装或执行。下面路径/行号属于发布包正文，不能用浮动主分支替代。
四种社区协作包的本轮peers均已采用`@earendil-works`命名，不能沿用旧scope不兼容理由。

| 精确包 | 发布物integrity | 实际许可正文SHA256 |
| --- | --- | --- |
| pi-powerline-footer@0.20.2 | `sha512-RK9a9gd0GjVT2sc7Ak3dAxw1BOLfq9O/muLyeQ+Zu7rHJ1s0azSudGtyk9c9dAlv7VBiq6rO5GGCfJDgtD95xQ==` | 未附LICENSE；MIT声明不能抵扣正文缺口 |
| @mjakl/pi-subagent@3.1.0 | `sha512-nXxtjCdOdnwEY0jcm4y8x9sOvP/0J6nBjoc2TPWtFmvypaF1EC9Aso54S6Vu0PawWkLxzaNlN+dKsaSCCBPScg==` | `ae4d6df64a19a0a6fbd67d090667d6714f9120560ed15d997e215220dd1e4930` |
| pi-subagents@0.79.1 | `sha512-7r+Dz2G9ewTuRrgmLnXGfK+nc14ZjVC+sWkw2WaL40MbYmlHeIxmfTMxDRvVSlK+CptKUArV6PtXAQtWZzCUVQ==` | `2d20dfacd9742706e564470dc77438608a1e54b0ed46959f080709389209093c` |
| @tintinweb/pi-subagents@0.22.0 | `sha512-vkpH930uAi/Y8KOyc4+D7bSNgrL8xX4TAdMF6AWTqFjs2BTxuSobZ4ViA5jcL87FmyKb7O1X+r6ZPiEVTk3GQg==` | `e7d9d11c28cce34f09dc7d2b0a3a6609ccba5fbc8e926e6d1bfdf060930e9f05` |
| @ian-pascoe/pi-minimal-subagents@0.19.2 | `sha512-UkaJ76c4MXVbaQGcglg4AsxGvWEDpaY2dsWDMu5PJwk/Eem/TWR1uvmfYnKSaFe4e7hOX6mFUqZnUQ3mkOLl1Q==` | `25159407f5dc0790d02daa5f168bfa85354dfce8996f5b18ac25551e58220021` |

Powerline精确包：`index.ts:930,1032–1061`读autocomplete/editor内部state并写lastWidth；
`bash-mode/editor.ts:354–524`反射编辑器内部成员；`index.ts:3263–3318`有组件/handler包装。
公开custom editor注册接口本身不构成违例，内部state读写及私有方法接缝才是暂停原因。
`powerline-config.ts:9–28`无已核实的enabled/footer-only开关；global/project `.pi/settings.json`
递归覆盖读取在`index.ts:325–351,610–612`，powerline/bashMode/shortcuts/showLastPrompt
不能由管理器虚构为统一disable。queue另写`powerline-footer/inbox.jsonl`，
`queue/store.ts:17–20,275–320`涉及项目别名/锁/原子写；compaction hooks在`index.ts:2134–2169`。
队列不因其持久化就自动判私有，但本包并非无状态纯footer。关闭fastRender、显示段或compact
不能证明所有hook卸载；额外模型请求/轮询/进程及真实渲染成本尚未测量，不作零成本声明。

mjakl精确包：`index.ts:55–59,130–135,1008–1011`为每次tool调用最多8/并发4，
不是跨调用每主会话强制2。`README:502–520`与`runner.ts:513–530`公开
`--subagent-max-depth`/`PI_SUBAGENT_MAX_DEPTH`，设1有禁继续委派路径，不能声称没有深度控制。
`agents.ts:189–221`与`runner.ts:271–280`允许tools/noTools，但扩展hooks仍继承
（`README:203–211`）；MCP/Codemode/恢复会话的实际只读闭包未验证。Unix进程组TERM/KILL
仅涵盖未脱离的后代（`runner.ts:619–667`），不是全部后代退出证明；没有相应生产归属回执。

备选逐项结论：

- pi-subagents：`src/extension/declaration-pinning.js:98–105`及tool-activation.js:52–53
  使用公开ExtensionContext类型未声明的`sessionManager.buildSessionContext`；会话累计spawn预算
  可由env/grant命令改变（docs/configuration:448–456），不是活动并发2。foreground runner显式
  加载Codemode/MCP；其余只读/账号/取消/完整后代和模型回执闭包未验证，保持candidate未选。
- tintinweb：`src/agent-manager.ts:4–14,99–106`后台默认10、前台无限、嵌套绕名额；
  default-agents.ts:9,29–43的Explore包含bash/扩展/skills。定向扫描未发现私有接缝不等于全包
  获准；递归/恢复/项目发现/账号/完整后代/模型回执尚未验证，保持candidate未选。
- Ian：`src/minimal-subagents-child-resources.ts:106–128`导入宿主未导出的MCP内部模块，
  loader失败后连接全部MCP；README:218–233省略tools继承root/Codemode/deferred/MCP，
  178–201可信项目可覆盖角色、默认深度2；coordinator:249–257,2041–2053未见每主2硬上限。
  不沿用旧包方法覆盖指控，当前公开接口/闭包条件仍不合格，保持candidate未选。
- 官方1.3.0示例：公开API导入可作参考；`examples/extensions/subagent/index.ts:34–35,
  602–608,643`为每调用8/并发4；298–305仅在配置agent时限定tools，未显式关闭扩展发现；
  408–417取消只处理直接进程。它是示例而非已锁管理包，不复制成自有调度器。

所有候选在每主2/两主4、只读闭包、禁递归/后台、账号发现、取消/全部后代、当前任务/模型回执
各项均须分别提供证据；当前没有候选闭合全部条件。`tests/test_pi_collaboration_contract.py`
仅定义合成验收双份，不证明第三方执行；T068–T071保持开放。

## 7. 两种 web-access 同样例静态比较

两包均为candidate未选，未运行样例/服务。精确来源为
[pi-web-access@0.41.0](https://registry.npmjs.org/pi-web-access/0.41.0)与
[@kvidzibo/pi-web-access@0.2.1](https://registry.npmjs.org/%40kvidzibo%2Fpi-web-access/0.2.1)。
前者gitHead=`d47dc040552505e3b135d0136a0b15eaf4bdba52`，SRI为
`sha512-8+UoNENGHKlYBxrtwh7Hwoh2twVfs+tcdR1Ciq7sRUtTur0mOXP8N/o7/y72JbdYij3NuSyCNjShbWBPPJ8JPA==`，
MIT LICENSE SHA256=`871b3c6c64e030c0647ca33543716bdae9511ae2d6a85d6f4ce63783bab52c8f`。
后者gitHead=`d25304a6e3478439568e168c6345017cfd3b603e`，SRI为
`sha512-MPSz3amZeIJYXWxqSaErPOZbDc890XZ7QsyA5GrEyEfs2148EqzuGA7g9eZIzC1kB2wBj7cqlFYemmlBAH0GHg==`，
MIT LICENSE SHA256=`d2ee025f63ff73b1f91d5472dfd7b81cb425e1f7cc8e1b1fff97e436c01a9846`。

| 同样例类别 | unscoped 0.41.0静态能力 | scoped 0.2.1静态能力 |
| --- | --- | --- |
| 普通HTML正文 | 本地HTTP/Readability与SSRF检查 | 同类；src/pages.ts:35–71 |
| 动态网页 | 可配置托管提取provider及fetchRouting，远端默认需opt-in；不保证任意站点 | README:54明确不执行JS；需另选专用浏览器 |
| PDF | pdf-extract.ts有endpoint/Datalab/Gemini/unpdf，部分外发且收费；默认保存Markdown到临时文件 | README:7不支持；src/pages.ts:60–64,85–91拒绝PDF类型 |
| HTTP/搜索失败 | 多provider可配置fallback；raw模式仅直接抓取，无自动fallback | 搜索auto为Exa→DuckDuckGo（超时例外）；fetch HTTP错误按页返回，无scraper回退 |
| 大响应 | README:371描述5MB流界限；缓存/分页与输出截断分别处理 | 解码后2,000,000字节硬界限；get_search_content每次最多30,000字符 |

unscoped读取Pi配置目录`web-search.json`（README:457起）；凭据/provider/fetch/PDF/
SSRF需分别严格投影，`PI_WEB_ACCESS_CACHE_ROOT`可隔离缓存。scoped的tool参数provider为
`auto|exa|duckduckgo`（src/tools.ts:24–32）；缓存硬编码`~/.pi/agent/web-access-cache`
（src/tools.ts:11），不能用设置PI_CODING_AGENT_DIR推定隔离。受管选择应明确单provider，
禁止auto静默fallback；当前未获得对应公开配置/缓存隔离/全闭包的组合证据，因此不注册入口。
scoped不继承unscoped的PDF/video/Git能力；更广能力也意味着更多依赖、外发与费用核对。

## 8. 订阅、诊断与会话内进程精确补审

本节是2026-10-19首次读取四个精确registry元数据及tarball的静态检查点，逐项SRI匹配，
当时均未安装或执行。后续cache-hit-monitor已接线（第9节），其他候选的当前结论以新增记录为准；
许可和入口静态核实不表示完整依赖、账号、生命周期或Pi组合准入。

| 包 | SHA512 SRI | 实际LICENSE SHA256 / 静态入口 |
| --- | --- | --- |
| [Cursor1.4.39](https://registry.npmjs.org/%40rahularya01%2Fpi-cursor/1.4.39) | `sha512-phpm4ZQNFqdCeYWcav7/RLHB2Bq2raUKyqufHqzq5eY9/ppTNKjhId+9/MAWXlGGe0T26kTncW773ouToAaBag==` | MIT `cf95abbe1576653e1e335cba07a100a71cda8dc580fa88baeb0185526b4b8155`；dist/index.js；Node>=22 |
| [cache-hit-monitor0.1.1](https://registry.npmjs.org/%40narumitw%2Fpi-cache-hit-monitor/0.1.1) | `sha512-eZ9SVOjAHKFHttwMt2s3WHw1nFrO0EEyViOdeRu5Yd5ulfOJu/NizCmNz0dbQPCDIQJoPM72sm+eX1GFL83VJw==` | MIT `5293e92f073f47012e723990a8605431b438757e9c6eb00c89868b1203e157da`；src/index.ts；未声明Node engines |
| [pi-tool0.3.2](https://registry.npmjs.org/%40narumitw%2Fpi-tool/0.3.2) | `sha512-6pRKKRmYF7otun14utUtbxOEkWEPz/GfENyJj15pGblNKWUh8S74v8WO2w+3WecldY+QDG/i1BWlK1MmlvDIRg==` | 同上MIT正文；dist/index.ts；未声明Node engines |
| [processes0.13.2](https://registry.npmjs.org/%40aliou%2Fpi-processes/0.13.2) | `sha512-Bl3PDxYDTiljd9mp6U/nZYPD+yRupcJBVAKDyZSqrStmU7DEyHbHUTp529nHXfmpf+IFAkN3S7Nl9dNrNjiuYg==` | 元数据MIT但tarball无LICENSE；processes/logs/dock三个扩展；Node>=22.19.0 |

Cursor gitHead保持`ef3cafb5c38081ce6e06df8e594241aabd9621e3`，Pi AI/coding-agent peers>=0.80.0。
有prepare且对应prepare脚本未入发行tar，不能执行来补包。README:85–105,202及捆绑正文
dist/index.js:1,40显示默认会在env/Pi OAuth之后查询Keychain、IDE state.vscdb和WSL。
真实键`PI_CURSOR_SYSTEM_CREDENTIALS=0`关闭后面三类，不关闭环境token和Pi原生auth store；
未来选择必须强制该值并核对本实例凭据链，不能只在说明里提醒而实际继承默认。
`PI_CURSOR_CACHE_DIR`或XDG_CACHE_HOME/pi-cursor下写run-journal，含session/checkpoint/blob恢复材料
（README:208；bundle:39–40），目录0700、文件0600。journal机密字段/保留/清理/entitlement与实际模型/费用仍待核。

cache-hit-monitor gitHead=`70a034c1be212dd142969f9f17f8dfc894fbdf2f`，Pi AI/TUI/coding-agent peers `*`，
无安装生命周期。src/cache-hit-monitor.ts:19–56,113–188使用公开getBranch/modelRegistry.find和会话hooks，
README:38,80–90声明只在内存处理usage/model，无文件/网络操作；这仍是静态资料，不是运行测量。
widget默认hidden、toggle只改显示（27,91–109），hooks继续采集/恢复usage，shutdown清内存；
provider上报或估算值不等于精确缓存字节，更不能推真实账单。不为信息重复而默认加入主题/UI路径。
后续C组本地原生已验证waiting for provider cache usage、显示/隐藏及reload恢复默认隐藏，
三宽度中文交互与正常退出passed；实际usage/cache/费用仍not_run，见[原生验收](native-acceptance.md)。

pi-tool gitHead=`76f42aeaec16aabc98af2b50ae5261e62e1c7935`，Pi TUI/coding-agent peers `*`；
runtime依赖pi-tui-kit ^0.59.0需显式解析完整闭包。prepack不是安装生命周期，dist已打包。
getAgentDir()/pi-tool.json仅有activeToolStatus；命令/hooks始终注册，enabled时每500ms查询getActiveTools
（dist/index.ts:10–56,293–325,349–387）。README:83注明多个Pi进程写设置无共享锁，96注明可能显示路径/提示文本。
默认不显示widget不代表无hook或零成本，真实多主偏好/退出尚未验证。

processes gitHead=`434fa0a860b1fa4fe9fccdc986964d865ef98e47`，Pi AI/TUI/coding-agent及TypeBox peers `*`，
prepare含husky条件，未执行。extensions/processes/index.ts:23–91自带process manager、工具/日志/通知；
hooks/cleanup.ts:26–42在session_shutdown调用killAll/cleanup；runtime-controller.ts:103–108,332–340
对已登记live PG发SIGKILL、吞信号错误且不等待退出；process-group.ts:21–25使用负PGID。
这与旧长任务平台职责有明显重叠；PGID信号不证明脱组后代或宿主崩溃资源已释放。
首轮继续优先tmux/项目日志交接，该包不因“关闭hook存在”进入锁或获得恢复能力声明。

## 9. 继续实施：固定可选入口与真实依赖静态审计

`cache-hit-monitor`、`pi-context7`、`pi-brave`已从candidate提升为静态admitted，默认未选。
严格接口及数据/费用/状态边界见[实际可选配方](optional-module-recipes.md)和
[全关闭示例](../../examples/pi-services.toml)。允许声明不等于loading/account/runtime通过，
选中后feature_readiness为not_verified。其他模块仍candidate/held，未知选择exit2。

固定宿主/主题加这三项的临时完整npm解析244包，package-lock-only及ci均exit0，全部ignore-scripts。
原host13项生命周期正文摘要不变；新增9个安装路径的prepare为已发布构建或Git hook准备，
运行入口/ESM/CJS/type产物已随包发布，主代理静态批准ignored_not_required。
分组按每模块dependencies/optionalDependencies闭包，不能经peer宿主绕入其他未选模块；
Context7组5项、Brave组8项有共享路径，缓存诊断组0项；全选去重后共22项。
精确命令及SHA256在dependencies.json.module_script_audits，实际清单变化即拒绝激活。

MCP环境清理launcher是对公开stdio命令接口的薄适配：Pi1.3默认transport会继承宿主环境，
故launcher必须在exec前过滤。没有改Pi、MCP服务或依赖源码。私有cwd避免Brave dotenv读取项目，
未选服务不进当前锁、不传builtin:mcp、不连接。本节静态检查点尚未执行服务调用、模型/账号或性能，
不能把默认关闭或静态admitted改写为这些交付门通过。

## 10. 状态栏替代的公开接口准入

选中入口为[pi-footer@0.5.1](https://registry.npmjs.org/pi-footer/0.5.1)，源码gitHead
`1b83749ffa9a3be0b88be6823231300a17a66b10`，SRI
`sha512-8CcySBJF5nOWZxmrfizjChNa3c/Lo45Y9T6ZbzQ8DLjvsTh3wyuEZuEsOALQ/RO7HORa2XA7UJR1/QyX8fOApQ==`；
MIT实际LICENSE SHA256 `9a10ed21f2fecf7d96aefeb8fabf4f6d2ff8196c1c262233b5f22743673310a8`。
完整包静态搜索与入口审阅未发现Editor内部状态、方法覆盖、私有宿主模块导入或runtime探测；
公开setFooter、footerData、ctx/session和pi.events负责显示。源包未修改。

pi-footer负责布局；仓库`status-observer.mjs`仅发布四项公开事件数据并提供完整信息命令，
不注册模型工具/执行器，不接管主loop。默认模板不使用上游缺失费用补零、全entries turn
缓存统计或非强类型payload verbosity。观察器按当前分支统计、未知值和口径见
[状态信息](../../docs/pi-status.md)。模板与观察器只在选择时绑定内容身份并复制到密封runtime。

包使用公开PI_FOOTER_CONFIG，整个本实例配置INITIALIZE，保留用户/footer更改。
Git通过公开pi.exec且timeout500；project runtime widgets默认未选，不因安装就执行版本命令。
配置UI animation interval在dispose clearInterval；B组真实菜单保存、关闭、reload与正常退出已复验，
无重复footer或显示残留，不能据此声称所有hook成本/清理路径已测量；隐藏footer不卸载hooks。
直接包无preinstall/install/postinstall/prepare，chalk^6需完整闭包校验；peers接受Pi/TUI1.3。

结论：T054静态公开接口admitted，T055按选接线完成，默认未选择；8文件267项隔离回归通过，
Node观察器修订后7/7合成事件通过，Python两份状态契约13 passed/11.30s。
B组实际通过三宽度中文粘贴/清除、菜单偏好经重建逐字节保留、provider紧凑标签与完整身份、
菜单prompt→idle、reload及退出检查；T058为Linux本地partial，T059完整信息交付仍开放。
最终305文件候选source为`39fa875a0cd6edc63f035515d8933032134afe2b92cdd6f0af24b76c20d70c1b`，
B锁为`e67e22a8fa6126909b928961ea106969ab2779e4f3f11966dafeb48fde9e3ec6`。
此前250包组合属于observer修订前检查点，不是新B来源；完整边界见[原生验收](native-acceptance.md)。
Powerline held保持原原因，未因改选候选而解除其准入失败。

## 11. Pro进一步核实：保守策略也无法绕过的宿主私有探测

对mjakl3.1.0已尝试根/子完整关闭资源、固定tools仅read/ls、公开tool_call策略限制每主2、
取消/错误保留名额的可行路径。官方read/ls不spawn，正常子close可提供该受限闭包的退出依据；
深度1、ephemeral、无parent context都有真实参数，不能误报没有这些能力。

但index.ts:874每次有效工具调用都会先调用getPersistentSessionDir(ctx)；629–644探测
只读sessionManager未声明的usesDefaultSessionDir成员，官方1.3的ReadonlySessionManager
类型不包含它。即使不传session也不会跳过。公开getSessionDir回退不消除私有成员探测。
因此不能按现有参数完成纯公开API准入；不修改插件、宿主或通过私有代理隐藏该成员。

cullenbmacdonald/pi-subagents固定提交b511b5b95b3f41599237ea22c815cfd03d9d8bd9
还直接读取private modelRegistry.runtime，且peer^0.81.1不含1.3；不是替代合格包。
其他精确候选结论见第6节。T064及其后续仍开放，Pro not_ready。
可供上游修复的最小问题是改用ReadonlySessionManager公开接口，不把此说明当授权对外发issue或PR。

## 12. Playwright CLI候选的完整支持文件与进程边界补审

CLI0.1.22随包含完整Skill、10份被引用指南和Apache-2.0 LICENSE；源内容完整性已核。
精确transitive `playwright-core@1.64.0-alpha-1790635538000`，gitHead
`e8149b8257d32dcf8f72573ecc43e72439da7080`、Node>=20，SRI
`sha512-pNwaXirhXMRLaRQs4NQ18EpTdtDoFwyPH9FOaaDC7YXG4hpwE2xmwCic/1srbuExVQC7zT9LJSJpDBAru+Vo9A==`
已从官方registry metadata/tarball比对。未执行CLI/browser。

Core lib/tools/cli-client/program.js:129–135,181–184,259–263与
session.js:121–159、registry.js:119–170：open会startSession并启动分离daemon；
缺浏览器时报错提示显式install-browser，不自动下载。daemon/session会写缓存并持续到close/idle超时，
这不等于父Pi退出即全释放。Linux默认XDG_CACHE_HOME/ms-playwright/daemon，
未设才用HOME/.cache；workspace按cwd向上找到.playwright后哈希分组，须隔离cwd/cache/session。
--profile/--persistent显式才启用磁盘profile，attach会接个人浏览器，因此受管候选不得默认使用。
NO_UPDATE_NOTIFIER=1关闭CLI更新联网；Skill中的浮动npx路线不能替代受管精确CLI。

继续实施后，`skills=["playwright-cli"]`已形成固定npm/完整Skill/受管wrapper的选择路径，
默认仍未选。静态公开接口与隔离管理接线admitted，实际浏览器/daemon关闭和原生操作not_verified。
wrapper只exec已锁定CLI，不fork、不下载；每主运行独立32位hex session，同主命令复用，
固定私有cwd/HOME/四个XDG/browser目录及PATH入口，模型/服务key和NODE_*不传给CLI。
私有cwd/.playwright marker阻止workspace祖先探测；cwd/HOME自动cli.config.json存在即拒绝，
不读正文或删除。禁止attach、persistent/profile/config/session覆盖、安装及跨会话close-all/kill-all。
完整上游Skill、10份指南和LICENSE原字节保留，并有固定SHA256清单；受管Skill明确覆盖其中
不适用的浮动npx/安装/个人浏览器建议。页面脚本、上传、cookie/storage等仍有副作用，只属
明确授权的主会话浏览器任务，不能提供给首轮只读调查，也不宣称wrapper约束任意Bash。

9文件299项隔离测试exit0/139.51s；覆盖未选零接线、选中锁与完整资源、假exec环境、
源码漂移、bin额外文件/内容漂移、禁用保留状态、自动config文件/链接/异常目录拒绝。
该隔离检查点没有执行CLI、下载浏览器或启动daemon；后续固定Chromium显式准备及合成页面
运行/正常退出通过，精确来源、失败与限制见[补充验收](remaining-native-acceptance.md)。

今天官方registry `@earendil-works/pi-coding-agent/latest`直接返回1.3.0，
当前锁定版本仍是本次核对的最新宿主；固定候选未自动升级。

## 13. 方法资源与诊断候选的首轮选择

选择依据不是默认补齐所有插件。已有只读公开usage观察足以支持状态数据，
`cache-hit-monitor@0.1.1`保留为显式诊断选项，默认不加载；隐藏widget时采集hooks仍运行。
`pi-tool@0.3.2`继续candidate且未注册：其500ms轮询、pi-tui-kit传递闭包、
多主进程写偏好无共享锁和退出尚无组合证据。严格插件集合拒绝该ID，不能将其列入已交付模块，
也不为诊断再新增profile。升级需重新审计固定包、完整传递依赖和hooks/轮询清理。

| 需求/方案 | 本轮选择与证据 | 未提供的能力 |
| --- | --- | --- |
| 有界C++结构调查 | 可选完整`cpp-bounded-investigation`方法Skill；查询只使用项目已提供且核实身份的ast-grep，公开flags逐版本核对 | 不安装或锁定项目CLI；文本/AST不能证明类型、重载或模板语义 |
| ast-grep扩展0.3.1 | 来源对应未闭合，保持candidate不入锁；0.3.0的工具说明不能替代当前审计 | 不注册ast_rewrite，不给予自动改写/扩大扫描权限 |
| 项目clangd/编译器 | 复用已有compile_commands.json和目标工具链，缺编译条件记语义未验证 | 不随Pi启动语义服务器、全库索引或Serena |
| 跨终端长命令 | 可选完整`long-command-handoff`方法Skill；复用已有tmux和项目日志，明确argv/cwd/会话/结果/下一步 | 不安装tmux、不接管termcfg、不自动重放或恢复任务 |
| processes0.13.2 | 会话内candidate未选，关闭信号不等于完整后代退出；许可正文缺失另待核 | 不承担跨重启恢复或Pi实例维护 |
| PTY/stdin/REPL | 真实需求触发后再选单一所有者，unified-exec身份未固定 | 不把内存session或PTY注册表当持久任务数据库 |

两项方法Skill位于shared目录，使用公共完整目录/文件权限/来源摘要机制，Pi只注册选择，
DSH/OMP的资源选择不因此改变。默认未选，选择后只复制静态资料，没有npm新包、工具入口、
定时器或后台hook。`tests/test_pi_method_resources.py`两项隔离测试exit0，证明完整文件、
仅所选来源漂移使该slice失配、未选Pro身份不受影响和无工具安装调用；不冒充真实CLI验证。
首次测试因未导入依赖fixture而setup失败，补齐后1项通过，再扩展两种资源后2项通过。

方法中的外部参数来源为[ast-grep官方CLI](https://ast-grep.github.io/reference/cli/run)、
[完整参数](https://ast-grep.github.io/reference/cli)及[clangd官方索引说明](https://clangd.llvm.org/design/indexing)。
这些资料不固定项目安装版本，也不授予执行、写入或工具安装授权。停止请求、回执、进程退出、
后代释放和副作用分别报告，配置rollback不恢复项目命令效果。

## 14. Cursor与浏览器新增闭包的静态脚本审定

Cursor固定`@rahularya01/pi-cursor@1.4.39`发布dist/index.js，tarball缺
scripts/prepare.mjs，但package.json声明prepare。精确gitHead下的
[prepare源码](https://raw.githubusercontent.com/Rahularya01/pi-cursor/ef3cafb5c38081ce6e06df8e594241aabd9621e3/scripts/prepare.mjs)
SHA256为`ed28f093c799fb40b134fb1b4c3437316c238d84a34517cf73b1f7a2ac0aef5e`：
dist存在直接退出；否则本地tsup，缺失则浮动`npx --yes tsup`。当前仅接受已发布registry tar，
不走git/source构建、不补缺失脚本、不执行prepare；运行产物已在包内，主代理明确审定该精确
manifest/lifecycle为ignored_not_required。原始package.json SHA256
`43c5697d8d31045bdd2697d49b23273be745eca125e34fb26f7a52bab4c93ee6`
绑定审计，不能改用规范化JSON摘要。无preinstall/install/postinstall。

其精确直接依赖`@bufbuild/protobuf@2.13.0`无生命周期/进一步runtime依赖；元数据许可
`(Apache-2.0 AND BSD-3-Clause)`，tar缺独立LICENSE，dist/esm/index.js保留Apache头，
dist/esm/wire/varint.js保留BSD版权、条款和免责声明。固定上游
`0648534fac5eed9a2775807c0ade241de425f244`根Apache LICENSE SHA256为
`c04b4216f1cd4c5a4f7fb2f2a1b0ae70d847e9e0cac7c9dee9bf8cc03177c449`。
安装树保留完整发布文件/法律材料，不修改vendor。静态事实不替代完整锁/安装核验。

Playwright CLI0.1.22、playwright与core精确alpha版本的SRI/manifest均已核，三者均无
安装生命周期；有效闭包Node>=20，Pi要求>=22.19.0仍是组合下限。playwright包SRI为
`sha512-/5XDUMxpOd/9AojJtWDFIRV3EJZNQ0AwvK69wgt3CPzy8wTgiBG9pX45VfxtqtvIRGwfWzMhrvawNKreG69Snw==`，
它和core共用提交`e8149b8257d32dcf8f72573ecc43e72439da7080`。
包中没有浏览器可执行文件；本审核未启动任何CLI/宿主、运行脚本或下载浏览器。
后续实际npm完整闭包和管理器维护结果须另行绑定来源摘要/锁身份记录。

## 15. 本轮交付选择与测量

完整增量见[本轮交付验收](current-delivery-acceptance.md)，前次检查点保留在
[补充验收](remaining-native-acceptance.md)。当前305文件源f1c83e6a…，权限说明阶段361a853d…与此前44be2fa6…各绑定原证据；默认两档锁522bed3a…不变；
所选临时锁按各次运行分别绑定，旧44be2fa6…样本不追认新源码。

| 选择 | 本轮观察与取舍 | 未覆盖/延后 |
| --- | --- | --- |
| 默认Base | 共享模型六类会话场景、有界合成读写检索/固定命令通过，无强制新增工作流 | 验收guard不等于生产权限保护；实际serving model/账单unknown |
| footer0.5.1 | 三宽度/回环SSH、偏好、reload、真实取消恢复、多轮/压缩统计通过；三处显示差异获接受 | Powerline0.20.2仍held；无真实权限查询来源 |
| cache0.1.1 | 零数据等待与正cacheRead1280→87.6%均通过；仅保留显式诊断选项 | 与footer统计有重叠，按需临时显示最近样本，不默认双重常驻，不作省token/费用主张 |
| Context7 4.4.2 | Pi连接/reload、独立stdio两次外部查询和一次无效工具错误后恢复/EOF退出通过 | 两层证据分列，不声称模型在Pi内调用；keyless路线不需新增账号 |
| Playwright CLI0.1.22 | 固定Chromium1247合成DOM/中文输入/点击/读取/close，PID退出确认；启动无浏览器进程 | 真网站/账号未验；缺系统Chrome和file URL拒绝保留 |
| Brave2.1.4 | 完整接线、共享引用缺凭据exit3与合成初始化证据保留 | 用户明确延后真实凭据、搜索、额度/费用；不是认证通过或从未选择 |
| Cursor1.4.39 | 完整接线、无账号version/help/doctor注册/reload/退出证据保留 | 用户明确延后本实例OAuth、catalog/权益/实际模型/账单 |
| 方法资源 | 两种完整静态Skill共用公共目录机制，不引入npm/工具/后台 | 项目自带CLI/clangd/tmux另按项目核验，无默认语义服务 |
| Pro调查 | 社区-only，等待合格上游，保持not_ready | 每主2/两主4、只读/无后台递归与完整取消后代闭包未过，不自建执行插件 |

已取得R/B/C/D/F共10次实际TUI与5次相同短prompt的SDK用量，另有历史18次version/help。
启动marker、CPU/RSS及树快照/额外进程分别记录。单样本、不同既有偏好和缓存状态不支持
显著性或因果增量；B首场全程CPU/RSS还包含详情UI动作，不作纯插件开销结论。
C input102另有cacheRead1280，不能与其他input1382附近直接相比声称节省上下文。

四模块同选、禁用/恢复与fresh实例应用级冷/热完成，T085–T087按当前选择范围收口；Pro及完整feature门保持开放。
冷/热明确为全新应用HOME/instance首次运行及同实例第二次运行，不清系统页缓存，不声称OS冷。
缺数据不称更快/更省token；缓存诊断作为最近样本的显式排障选项，原生或footer足够时不启用。
Context7有一个额外MCP进程，只有确需文档时才选择；浏览器Skill启动不自动open或下载引擎。

单选服务曾暴露npm提升路径与精确版本差异，已采用配对package/version源审计限定及真实锁路径
投影；manifest原字节/lifecycle严格校验未放宽。D/E最终六项维护均0，见
[脚本审阅](npm-script-audit.md)。源catalog条目数不等于每个实际锁的脚本审计数。

最终匹配对照使用source f1c83e6a…、相同两静态Skill/rules/prompts/themes，仅组合增加四模块。
应用首次/第二次startup：Base5.765/6.666秒，组合11.513/10.112秒；就绪额外进程0/1（MCP），
浏览器0。wait4 RSS及树快照、完整锁和实际标签修正见本轮交付。未清OS缓存，每阶段单样本，
不称更快或省token。维持精简Base；footer按信息需求选，cache仅排障临时选、与原生/footer
重叠时不启用，Context7/浏览器只按任务选，不默认同时启用。禁用只停止后续加载，保留账号/
偏好/缓存，已有进程须独立确认退出；来源升级必须重锁并重验原生/账号范围。
