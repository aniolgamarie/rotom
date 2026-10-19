# Phase 0 Research: 公共治理对齐与 Pi 重建

日期：2026-10-18。结论层级：仓库源码调查、公开资料和部分精确发布物静态证据。
本轮未安装或执行宿主、插件、服务或模型。实现与运行验收均未开始。

## 1. 待研究问题与决议

| 问题 | 决议 | 实现/验收条件 |
| --- | --- | --- |
| 公共逻辑共用到什么程度 | 复用现有配置、部署与 backend 接口；提取生命周期和安装校验的中性原语 | 保留原生格式，受影响 DSH/OMP 回归 |
| 三种工具是否合并锁格式 | 否；完整身份、验证和激活语义共用，包锁/资产锁保留薄后端 | 不读旧 Pi 执行账本生成新锁 |
| 官方宿主与发行方式 | 精确 npm 官方包 1.3.0，Node ≥22.19.0；完整 npm 锁，Node-only | 不沿用旧 SDK 主循环或 Bun 运行配方 |
| Base 默认内容 | 官方 CLI、原生 UI、静态主题、精简规则及现有 SpecKit | 默认无第三方进程内扩展或外部服务 |
| 配置和项目发现 | 显式资源清单、稳定实例/会话目录、阻止启动时安装 | 原生发现与漂移 preflight 均有验证 |
| Pro 委派器 | 当前不准入；mjakl 为首个复核候选 | 每主会话并发 2、只读工具闭包、禁递归均可核实后再启用 |
| Powerline | 0.20.2 暂停准入；保留信息需求和原生 UI 阶段回退 | 上游公开接口修复后重新审包及组合验证 |
| 可选模块 | 共用来源、启动前显式选择，每类一个所有者 | 账号、数据、缓存、进程及卸载逐项准入 |
| 后代进程与维护 | 公共准入保守处理，不能确认空闲就阻止受影响维护 | 不新建监督器或跨崩溃任务恢复服务 |
| 首轮平台与证据 | 首个实施验收目标 Linux x86_64；macOS 另列候选 | 任何平台当前均无新组合运行通过声明 |

以上为已作出的设计决议，不留需要人类回答的澄清项。插件准入失败是已知交付阻断条件，
不是把未解决技术条件写成“已支持”。后续任务必须显式保留 Pro 与信息对齐未完成状态。

## 2. 公共接缝与中性实现

**Decision**：沿用公共解析/渲染/部署管线，先对齐已有语义，再抽取共同实现；不建立 Pi 管理 facade。

| 领域 | 当前仓库证据 | 设计处理 |
| --- | --- | --- |
| 来源与配置 | `workspace.py`、`config.py`、`merge.py`、`render.py`、`adapter.py` | 同一 schema/引用/覆盖入口，Pi 只做原生投影 |
| 命令分发 | `commands.py`、`runtime.py` | 同一命令副作用和退出码；不再穿过旧 Pi 主循环 |
| 配置事务 | `deployment.py`、`native_projection.py`、`storage.py` | 复用三方所有权、pending、上一版与 rollback |
| 完整依赖 | `backends.py:DependencyBackend`；DSH `dependencies.py`；OMP `omp_dependencies.py` | 共用契约及可共享的内容检查/暂存原语，不强制同锁或同安装器 |
| 实例准入 | DSH `lifecycle.guard`；OMP `omp_identity.lifecycle_guard`；Pi `pi_lifecycle.py` | 从前两者提取锁/身份检查原语，以 adapter hook 保留标记和布局差异 |
| 旧任务平台 | `activity.py`、`workspace_leases.py`、`pi_recovery.py`、`model_delegate*.py` | 先处置消费者，再退役；不是公共恢复层 |

**Rationale**：当前已存在公共接缝，重复实现只会增加漂移；运行目录、锁格式和账号身份却有真实差异。
DSH/OMP 当前物理锁不同，不能以重命名宣称已对齐。公共抽取必须以相同输入/失败行为的差分回归验收。

**Alternatives considered**：整套保留旧 Pi 基础（保留过多执行平台）、强制所有宿主统一目录/锁
（制造不必要兼容破坏）、为 Pi 复制管理器（违背 FR-002）；均不采用。

上述位置均相对于 `src/agentcfg/`。本轮独立 scout 已读取具体调用关系；不是完整动态调用图。
删除前仍须按[退役契约](contracts/retirement-and-evidence.md)重新检查实际候选。

## 3. 宿主、完整依赖与安装形状

**Decision**：第一实现目标为 `@earendil-works/pi-coding-agent@1.3.0`，使用官方 Node CLI，
Node 运行时最低 22.19.0。运行时由机器前提声明；只检查，不在 run 自动下载。
Base/Pro 正常同版，分别记录完整 npm package-lock 与选中资源身份。

**Rationale**：2026-10-18 核对的[官方正式发布](https://github.com/earendil-works/pi/releases/tag/v1.3.0)
和[固定版本 manifest](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/package.json)
给出该宿主与 Node 前提；[精确 npm 元数据](https://registry.npmjs.org/%40earendil-works%2Fpi-coding-agent/1.3.0)
提供发布 tarball 与 SHA-512 integrity；其 gitHead 为 null，不能宣称 npm 已绑定某个源码提交。
官方固定 release/tag 用于来源交叉核对，实际锁须以发行物完整性为身份，不能编造缺失源码绑定。
版本固定不等于已获得完整传递锁。

实现时在显式 lock 阶段生成新依赖闭包，记录 tarball integrity、许可证、平台原生依赖和安装脚本。
sync 消费已审阅锁，在暂存目录执行确定安装、核验清单与入口后激活；实例原生 home 不随包目录切换。
旧 `locks/pi/manifest.json` 和四配方锁是历史输入，不能原样复用为新版本身份。

安装采用 npm 完整锁路径，禁止用 `pi install` 作为管理器的依赖解析/安装替代。
安装脚本必须先列明：未知脚本阻止激活；确需脚本的原生依赖在受控暂存阶段运行并验证，
不能一概禁用后仍声称安装完整。Pi 提供的 peer 包按公开加载契约复用，不能嵌套第二个宿主来掩盖 peer 不匹配。

**Alternatives considered**：官方安装脚本、可验证独立发行物、未修改源码的官方构建。
当前不增加发行路径；只有 npm 闭包无法满足明确平台前提时才重新评估，仍不修改上游。

## 4. Base、配置归属与项目发现

**Decision**：继续使用公共 TOML 的 rules/skills/plugins/mcp/roles 和机器覆盖机制，
不新增通用模块 DSL。Pi 原生设置通过重新设计的严格 adapter schema 映射，
模块是选型与资源清单概念，实际启用仍由既有资源选择字段表达。

Base 默认保留原生编辑器与 UI、单一静态 Catppuccin 来源、精简 rules/prompts/skills，
外部服务与第三方进程内扩展默认不加载。主题候选为
[`catppuccin-pi-theme@0.1.6`](https://registry.npmjs.org/catppuccin-pi-theme/0.1.6)，
源码身份 `1d5261b857061a1ba2990f329ca2572aa403e920`。
直接静态读取[精确主题 tarball](https://registry.npmjs.org/catppuccin-pi-theme/-/catppuccin-pi-theme-0.1.6.tgz)
确认四个 `themes/catppuccin-{latte,frappe,macchiato,mocha}.json` 的 name 为对应文件名去掉扩展名。
采用 `theme="catppuccin-mocha"` 为可覆盖初始值，不将 flavor 当作用户已最终选择；
包内含 MIT LICENSE，manifest 无普通运行依赖。此为静态核对，不是主题原生渲染通过。

**Rationale**：使用同一公共表达与来源，独立状态；用户模型、服务及编辑器由机器绑定，
不预置开发机路径或虚构模型为可运行默认。包内有 settings 文件不表示宿主会读取它。

受管父进程采用明确 session directory、`--no-approve`、各类关闭自动发现的公开开关，
再显式加载本地已锁资源。需要的 builtin 扩展单列，不能用 `--no-extensions` 意外关闭 MCP。
启动前只读检查原生非秘密资源声明；发现未准入远程 package 或加载路径漂移，拒绝受管启动，
不覆盖漂移、不自动安装。项目 `AGENTS.md` 仍可能提供上下文，不将其称为 OS 隔离。

依据：[固定 CLI](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/cli.md)、
[安全与项目信任](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/security.md)、
[原生配置](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/settings.md)。
原生数组可能有自己的合并规则，管理器必须先解析最终选择再生成显式资源序列，不改变公共数组替换语义。

**Alternatives considered**：完全自动信任并发现项目资源、只固定 defaultProjectTrust、复制旧资源 schema。
均不能单独证明 run 不安装或不扩大能力；不采用。

## 5. Pro：选择未准入状态，而不是补造执行平台

**Decision**：为 Pro 保留独立配方与共享基础，但初始协作状态为 `not_ready`，不加载委派器。
在满足全部条件前不能宣称交付了 Pro 协作；Base 可单独交付。此为准入决议，不是降低 FR-023–026。

首个专项候选是 [`@mjakl/pi-subagent@3.1.0`](https://registry.npmjs.org/%40mjakl%2Fpi-subagent/3.1.0)，
[固定源码](https://github.com/mjakl/pi-subagent/tree/6d05481a475c08bfd1ee5a623d5b742fb95b2147)
与精确发布物对应。既有静态审阅表明 RPC 子进程、深度/循环参数存在，但并发常量为 4、批量最多 8，
没有已确认可设为 2 的公开键；不能用角色约定声称满足每主会话强制并发 2。
深度设为 1 是单层意图，仍须验证传播与嵌套拒绝；工具 allowlist 还须核对 MCP、Codemode、
会话恢复和资源继承后的完整可达工具集合。

**Rationale**：当前候选不能直接满足规格。不得包装一个新调度器、修改缓存包或读私有字段来补足。
任何候选须同时证明：每主会话至多两个调查、无写入工具通路、禁递归、无后台、模型/结果归属及取消/后代状态。
2026-10-18 澄清选择 A：同配方可有多个独立主会话；各自的两调查名额独立，两个主会话可合计四个调查。
候选现有并发常量仍不能满足每主会话上限 2，准入状态不因计数范围澄清而改变。
不给只读调查 shell 或任意执行桥；工具限制不冒充 OS 沙箱。

**Alternatives considered**：nicobailon 的 `pi-subagents`、tintinweb、Ian 的 minimal-subagents、
[官方 subagent 示例](https://github.com/earendil-works/pi/tree/v1.3.0/packages/coding-agent/examples/extensions/subagent)。
功能更广不等于满足边界；Ian 0.19.2 的宿主方法覆盖仍不准入；nicobailon 0.79.0 的静态问题
不能自动归于后续 0.79.1，后者必须独立审阅。示例只作最小契约对照，不默认复制成长期自有执行器。

## 6. 状态栏：保留需求，暂停 Powerline 0.20.2

**Decision**：默认原生 UI；`pi-powerline-footer@0.20.2` 不进入选中插件与锁。
只有上游适用版本全部使用公开接缝、重新审包且通过信息与交互验收后才可启用。
不重建完整自有 footer 平台，不将当前原生回退称为信息对齐完成。

**Rationale**：[固定 Powerline 源码](https://github.com/nicobailon/pi-powerline-footer/tree/e06267494593c9006b014f42706a8d9e9259a417)
和[Pi 1.3 Editor](https://github.com/earendil-works/pi/blob/v1.3.0/packages/tui/src/components/editor.ts)
支持现有精确包结论：存在 Editor 内部 state/history 读取、lastWidth 写入和方法包装。
关闭 fastRender、显示段或 compactPromptMode 不消除全部路径；没有已核实 footer-only 开关。
[npm 精确版本](https://registry.npmjs.org/pi-powerline-footer/0.20.2)的源码身份为
`e06267494593c9006b014f42706a8d9e9259a417`。本轮复核没有发现改变此前提的新发布证据。

十类旧信息、优先级、统计及缺失处理正式承接在[状态与协作契约](contracts/collaboration-and-status.md)。
公开 customItems/setStatus 可以呈现值，不能凭配置创造活动、速度或权限数据。
若未来需要小型 collector，须单独证明公开接口、收益与成本，不能默认恢复旧监督链。

**Alternatives considered**：保留 colorful-footer、复制旧私有权限 Symbol、隐藏相关组件后加载 Powerline。
均不能作为公开接口和真实信息的替代。不满足时维持缺口，不要求用户现在接受功能损失。

## 7. 可选模块与社区实践

**Decision**：每类一个所有者，先原生/通用 CLI，再选择有增量的扩展；不新增默认常驻服务。
以下是下一阶段的固定研究起点，不是已获准加载的组合。

| 类别 | 首选研究路径 | 不默认采用/需要单独验证 |
| --- | --- | --- |
| 文档 | Context7 原生 MCP | 不为所有调查预连服务 |
| 搜索 | 用户选一个服务；Brave 为首个比较对象 | Exa/Tavily 不作为静默 fallback |
| 浏览器 | Playwright CLI + 完整 Skill | MCP/agent-browser 为替代，不接管个人浏览器 |
| 网页抽取 | 普通文档与原生工具优先；两个 web-access 独立比较 | scoped 包不能继承 unscoped 包 PDF/video 能力 |
| 订阅 | `@rahularya01/pi-cursor@1.4.39` 显式选择 | 非官方桥，不当作原生 provider；关闭系统凭据复用 |
| 诊断 | cache-hit-monitor 0.1.1 / pi-tool 0.3.2 各自按需启动 | 隐藏 widget 不等于不加载；后一包有传递依赖 |
| 结构查询 | ast-grep CLI + Skill 优先比较 | `@nicknisi/pi-ast-grep@0.3.1` 来源对应未闭合，暂停进入锁 |
| C++ 语义 | 编译器/clangd 按项目需要 | AST 匹配不替代类型、宏和模板语义 |
| 长命令 | tmux + 项目日志 | processes 0.13.2 只作会话内候选，PTY 另择单一所有者 |
| 任务流程 | 现有 SpecKit + 精选单项方法资源 | 不默认完整 Superpowers、第二套 Todo 或 OpenSpec 初始化 |

**Rationale**：社区实践值得借鉴的是资源分层与按需选择，而非整包搬运。
[mitsuhiko/agent-stuff](https://github.com/mitsuhiko/agent-stuff/tree/0865c849befd2021490679f96a8dee58c84ac857)
提供资源类型分层；[badlogic/pi-skills](https://github.com/badlogic/pi-skills/tree/90bb51cae36515a648515b633a81c0c6efc8c74d)
提示保留完整小型 Skill 目录；[Superpowers](https://github.com/obra/superpowers/tree/bb92a77741419a4ab5f06e711a283343f1ada0c3)
的跨 harness 工具映射可作方法参考，其自动引导不进入默认组合。
个人 settings 的信任、队列、包列表或私有压缩键不视为社区共识。

可选包的精确元数据：[Cursor](https://registry.npmjs.org/%40rahularya01%2Fpi-cursor/1.4.39)、
[缓存诊断](https://registry.npmjs.org/%40narumitw%2Fpi-cache-hit-monitor/0.1.1)、
[工具诊断](https://registry.npmjs.org/%40narumitw%2Fpi-tool/0.3.2)、
[进程工具](https://registry.npmjs.org/%40aliou%2Fpi-processes/0.13.2)、
[scoped web-access](https://registry.npmjs.org/%40kvidzibo%2Fpi-web-access/0.2.1)。
这些延续先前精确版本调研，不表示本轮重新读取了每个包或验证其当前 latest。

## 8. 恢复、后代进程和退役顺序

**Decision**：只对齐配置事务恢复和实例维护准入；不新建任务账本、监督服务、后台恢复队列或执行重放协议。
启动者的普通前台等待与实例准入属于管理器职责，不接管 Pi 内部 agent loop。

维护需要一致的实例资源排他视图。主进程存活、可确认相关后代存活或身份不确定时均阻止受影响维护。
父进程退出或文件锁释放不能单独清除活动记录；无法证明空闲就保留 `unknown` 并报告阻塞。
新会话启动也不得覆盖未知归属。Linux 首轮验证包括异常退出、后台后代与身份复用，
其他平台没有等效证据时不启用相应维护并发。具体契约见[公共管理](contracts/common-management.md)。

先解除 CLI、展示、配方、资源清单及测试对旧平台的引用，再退役 `model_delegate*`、
`pi_*` 中专属控制链，最后处理 `activity.py`、`workspace_leases.py`、`process_tracking.py` 的剩余消费者。
`commands.py` 的旧 Pi recover 入口不得保留为新组合启动前提；历史恢复需要单独、显式、
不启动旧宿主的兼容入口或文档方案，不能把旧运行平台留在发行闭包内。

**Alternatives considered**：父退出即视为空闲、继承锁描述符就视为全部进程覆盖、自动 kill 后维护、
继续旧 supervisor。均不足以满足身份与数据边界；不采用。

## 9. 验证与调研状态

| 状态 | 本轮事实 |
| --- | --- |
| 已完成 | 公共代码接缝调查；官方稳定版/Node 复核；候选决议；规格到契约设计 |
| 进行中 | 无运行时实施；任务拆分待单独命令 |
| 失败待决策 | 无宪章豁免或必要人类决策；已知 Pro/Powerline 准入失败保留为交付条件 |
| 环境不足未验证 | 未确认存在此类阻断；平台、终端、账号与原生组合本轮未执行，不宣称运行支持 |

未执行与环境不足分开记录：本轮原生/账号检查因阶段与授权边界未执行，不推定环境确实缺失。
两名 scout 的角色配置为 gpt-6-luna / high；只提供只读证据，设计与事务边界由主代理决定。
