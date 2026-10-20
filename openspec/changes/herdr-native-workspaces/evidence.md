# Herdr 原生工作区迁移证据

本记录支持设计评审，不构成部署或迁移通过证明。日期为 2026-10-18；目标基线为 `main` 的 `93e4f7899725336c1180e53b4ec239eea5f984ce`，设计分支为 `feat/herdr-native-workspaces`。本次只准备文档，未修改依赖锁、安装运行包、连接 Herdr socket 或启动编辑器、Agent。

## 状态与证据规则

状态统一使用“已完成”“进行中”“失败待决策”“环境不足未验证”。已完成只覆盖明确执行或核实的项目。已有测试文件、命令退出零、版本字符串、上游 issue 和经验文章均不能代替本仓库的功能验收。

本机事实由主代理提供的已核实结果转录，本记录作者没有重复运行本机探测。公开记录只保留平台类别、工具链事实、参数向量和脱敏结论，不记录真实主机名、用户路径、认证或会话内容。后续验收记录格式见 [acceptance.md](acceptance.md)。

## 来源矩阵

| 来源 | 已核实内容 | 能支持的结论与限制 |
| --- | --- | --- |
| [v0.9.5 release](https://github.com/herdrdev/herdr/releases/tag/v0.9.5) | latest 定向 v0.9.5；2026-10-14 发布；tag 缩写提交 `2ecf19a`；修复 CJK prefix、移除 Codex turn hooks、改用屏幕识别状态 | 迁移候选版本为 0.9.5；不能把状态识别视为任务完成或会话绑定证据 |
| [v0.9.5 release assets](https://github.com/herdrdev/herdr/releases/expanded_assets/v0.9.5) | 本机目标 asset 为 `herdr-linux-x86_64`，官方 SHA256 为 `14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d` | 仅核实发布清单，未下载、安装或执行该 asset；与本机 0.8.0 磁盘摘要分开记录 |
| [v0.9.4 release](https://github.com/herdrdev/herdr/releases/tag/v0.9.4) | Fish 重绘问题修复；zsh/P10k 仍等待 Ghostty 修复 | zsh 的重绘、resize 必须单独观察；Fish 修复不能外推为 zsh 已通过 |
| [issue #4649](https://github.com/herdrdev/herdr/issues/4649) | Linux、Herdr 0.9.5 与 Codex 0.162.1 有受控复现；维护者建议 `--no-daemon` | 状态与会话绑定分别验证；不因此停止已有 daemon；issue 不是本机复现结果 |
| [issue #5377](https://github.com/herdrdev/herdr/issues/5377) | 0.9.5 有重复完成通知报告 | 默认关闭声音与 toast；状态通知不得驱动任务完成判定 |
| [持久化与远程文档](https://herdr.dev/docs/persistence-remote/) | 持久化与远程使用的公开说明 | rolling 文档仅作辅助；恢复、安全边界与具体参数须对照 0.9.5 tagged 源码 |
| [会话状态文档](https://herdr.dev/docs/session-state/) | 会话状态的公开说明 | 不能由 UI 状态推断命令退出、Agent 完成或项目身份 |
| [socket API 文档](https://herdr.dev/docs/socket-api/) | 原生 socket 能力的公开说明 | 仅作接口线索；关键命令与作用域的 tagged 结论见下文，编排和重连仍需实际测试 |
| [DevelopersIO 迁移经验](https://dev.classmethod.jp/articles/herdr-tmux-replacement/) | 7 月第一人称迁移文章，使用 0.7.1 | 只作工作流体验参考，不作为 0.9.5 的功能、性能或恢复证据 |
| [Zellij session resurrection](https://zellij.dev/documentation/session-resurrection.html) | 恢复布局需要重新运行程序，原进程不会复活 | 对比恢复语义时区分布局、命令重启和原进程存活，不将布局恢复称为进程恢复 |
| [tmux clipboard wiki](https://github.com/tmux/tmux/wiki/Clipboard) | OSC 52 依赖终端链路支持，嵌套还有额外边界 | 复制必须在真实终端链路验证；只测试写剪贴板，不读取本地剪贴板内容 |
| Avalon [安装](https://raw.githubusercontent.com/aniolgamarie/avalon.nvim/refs/heads/main/docs/install.md)、[评审](https://raw.githubusercontent.com/aniolgamarie/avalon.nvim/refs/heads/main/docs/review.md)、[配置](https://raw.githubusercontent.com/aniolgamarie/avalon.nvim/refs/heads/main/docs/configuration.md) | 上游公开安装与 profile 配置材料 | `machine.editor` 只保存一个 launcher；实际选择哪个 profile 必须独立核实，PATH 中有脚本不等于 profile 正确 |

上述来源内容由主代理核实后提供。rolling 文档和主分支文件可能变化；实现接口以 v0.9.5 tagged 源码为准。发布资产数量不作为验收事实：网页的 Assets 计数包含来源归档等条目，release API 的上传平台资产为五个；只锁实际选定资产及其摘要。

## Tagged 源码评审结果

scout 补充读取 v0.9.5 的 schema、CLI、handler、持久化与启动路径后，主代理据此收敛设计。网页缓存缺失的公开源码通过获准只读网络取得，暂存临时目录，没有下载发行二进制或修改宿主。Git tree API 返回的 source tree 标识为 `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`；短 release commit 标识为 `2ecf19a`。树标识不冒充运行中 server 的构建身份，后续实施仍需绑定完整 commit/资产。

| Tagged 来源 | 核实结果 | 设计影响 |
| --- | --- | --- |
| [worktree handler](https://github.com/herdrdev/herdr/blob/v0.9.5/src/app/api/worktrees.rs)、[参数](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/schema/worktrees.rs) | path 经过 canonicalize；查找已打开 checkout 并复用；branch 选择要求唯一；参数没有幂等键 | Git 项目优先走原生 worktree open；不另存项目清单，不声称整个调用链为原子事务 |
| [workspace](https://github.com/herdrdev/herdr/blob/v0.9.5/src/workspace.rs)、[snapshot](https://github.com/herdrdev/herdr/blob/v0.9.5/src/persist/snapshot.rs)、[restore](https://github.com/herdrdev/herdr/blob/v0.9.5/src/persist/restore.rs) | 普通 workspace cwd 会受首 tab/root pane cwd 影响；snapshot 保存 worktree membership，restore 保留 membership 但清空 metadata tokens | 不能把 list cwd 或 tokens 当通用持久项目身份；非 Git 自动关联及用途标记的冷恢复不作已支持承诺 |
| [workspace focus handler](https://github.com/herdrdev/herdr/blob/v0.9.5/src/app/api/workspaces.rs) | 只按 workspace ID 调用 server 的全局 workspace switch | 同一 server 的客户端共享活动项目；不能宣称桌面和手机拥有独立项目焦点 |
| [tab schema](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/schema/tabs.rs)、[pane CLI](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli/pane.rs)、[Agent 启动](https://github.com/herdrdev/herdr/blob/v0.9.5/src/app/agents.rs) | tab create 不接受通用 command/argv；pane run 拼接终端输入；agent start 限定已知 Agent，服务端仍编码成 shell 命令再注入 | 没有任意直接 exec 的 argv 接口；Avalon 和 agentcfg launcher 要在新拥有终端使用受测 shell 编码边界，不能向复用终端发送命令 |
| [headless bootstrap](https://github.com/herdrdev/herdr/blob/v0.9.5/src/server/headless/bootstrap.rs)、[session attach](https://github.com/herdrdev/herdr/blob/v0.9.5/src/session.rs)、[CLI request](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli/runtime.rs) | 有 headless server 和 session attach；没有组合 start/open/focus/attach 的单一入口；固定 request.id 仅关联响应 | 外部 enter 分阶段编排，检查就绪与结果不明超时，不把固定 request.id 当幂等令牌 |
| [配置模型](https://github.com/herdrdev/herdr/blob/v0.9.5/src/config/model.rs)、[按键解析](https://github.com/herdrdev/herdr/blob/v0.9.5/src/config/keybinds.rs)、[标题模板](https://github.com/herdrdev/herdr/blob/v0.9.5/src/config/window_title.rs) | 候选字段/值有模型、enum 或解析测试依据；标题支持 hostname/workspace/tab/pane/terminal_title，未知项拒绝 | 原候选可以作为实施起点；仍须取得 native diagnostics，不能只验证 TOML 可解析 |

关键来源文件的 SHA256，供后续实现对照，不代表代码已运行：

| v0.9.5 路径 | SHA256 |
| --- | --- |
| `src/app/api/worktrees.rs` | `2e71d9683d7ddcdfe8fb833c81e20ae497eeeb83fe4618f0da3b08bc1a2f28bf` |
| `src/app/api/workspaces.rs` | `15dd978d8be6859b662edaf7d91d77c7e4a84e3d8d6a7cf2b2a08c6b1cd10974` |
| `src/app/agents.rs` | `ca3098441379df882c94681f795dd8b22bb30efcda19f8c1524e4463a03015a7` |
| `src/persist/snapshot.rs` | `62498f417377a4fd416fbd48ba75369110a3111bd25b813cce9943cfd82fa1e6` |
| `src/persist/restore.rs` | `17d0a12757e1496f5382d8cc1eb87b71c0a8e21e606f3f6ff74f644ffde55c29` |
| `src/config/model.rs` | `22a0e0ea19728d63dca866ea8669ca558e516d8d4ccac346a262aba4ec6ad6b2` |
| `src/config/window_title.rs` | `7c416071f8afff65115416b8b1f8ff9bc85da1d5e352fe4de075cfea4edd57bc` |

静态证据支持上述原语和限制，尚不证明本仓库编排、并发、不确定结果恢复、初始 shell 就绪或真实客户端正确性。源码中的内部辅助函数/启动环境常量仅用于理解，不作为 Rotom 可调用的私有集成接口。

## 本机脱敏事实

| 项目 | 已核实事实 | 状态及边界 |
| --- | --- | --- |
| 平台 | Linux x86_64，glibc 2.32 | 已完成：只描述此次平台，不覆盖 macOS 或其他 Linux ABI |
| Python | 系统 `python3` 3.8.17；仓库 `.venv` Python 3.11.11 | 已完成：仅记录本机版本；工程声明 `>=3.11`，不固定 3.11.11；入口及验证使用准备好的仓库环境 |
| 工具链 | uv 0.12.13，zsh 5.5.1，tmux 3.5a | 已完成：不是 Herdr 兼容性通过证明 |
| 当前终端类别 | SSH 中，`TMUX` 已设置，`TERM=tmux-256color`，`COLORTERM=truecolor`，`HERDR_*` 未设置 | 已完成：嵌套终端链路事实；没有记录 socket 路径或任何标识值 |
| Herdr 文件 | PATH 可找到，ELF；SHA256 `b872ea7e40fa2cb17e857ac9b62b1bf26db7b403c622f5d2f3f5b35f6e9acd28` | 已完成：仅磁盘候选文件身份，不代表运行中 server 身份 |
| Herdr 元信息 | 临时 HOME/XDG 中运行 `['herdr', '--version']`；退出码 `0`；stdout `herdr 0.8.0`；stderr 空；临时 HOME 零文件 | 已完成：唯一二进制执行检查。0.8.0 不是 0.9.5 验收基线，也不证明任意 server 版本 |
| Avalon | PATH 可找到；脚本包含 profile/exec，不包含 `NVIM_APPNAME` | 已完成：只读脚本结构；未运行编辑器，未证明 profile 正确 |
| 私人状态 | 未读取认证或会话文件；未连接任意 Herdr socket | 已完成：没有借已有账号或会话充当测试夹具 |

临时 HOME 隔离不等于 named server 配置隔离，也不能证明 daemon 不共享配置。未来启动原生 server 之前，必须先核实该版本的 server、socket、配置、持久化和日志隔离方式。

## 已决定的边界

- 普通终端优先。工作区助手不调度任务，不依据屏幕、标题、状态、最近日志判定任务完成。
- 项目身份为 `(server, checkout realpath)`；不同 Git worktree 保持独立；不跟随每次 `cd` 改写身份，不按 cwd 近似匹配。
- `work enter` 查找并聚焦或创建项目；`open shell/edit/build/debug/pi/codex/dsh` 默认复用，`--new` 显式新增。复用不能向正在工作的 shell 注入命令；手工原生终端不自动接管。
- Agent 沿用原 `agentcfg` profile 和 cwd；启动不触发 sync、apply、联网或配置迁移。Avalon 经 `machine.editor` 的单个 launcher 启动。
- 0.9.5 磁盘版本、实际 server 版本与实际生效规则分别核实；默认关闭恢复、声音、toast、后台更新和实验 history。
- 不修改上游宿主、不新增守护进程或第二套终端数据库、不扩大权限。接口不足时回到设计决策，不绕过公开接口。

## 执行模型与当前交付状态

观察到的委派执行模型为 scout `gpt-6-luna / high` 和 executor `gpt-6.1-sol / medium`，由各角色固定配置决定；主代理使用当前会话配置，本记录不推测其具体型号或 effort。本文档执行者没有再派生子代理。

| 工作项 | 状态 | 证据或剩余工作 |
| --- | --- | --- |
| 来源与本机元信息汇总 | 已完成 | 本文转录主代理核实结果；唯一元信息命令与退出码见上表 |
| 设计边界与验收计划记录 | 已完成 | 本文及 [acceptance.md](acceptance.md) |
| v0.9.5 tagged 关键接口与配置审计 | 已完成 | 原生 worktree 复用、全局 focus、argv 限制和 token 冷恢复边界已核实；编排测试仍待实施 |
| 离线实现与默认隔离测试 | 环境不足未验证 | 当前只写设计文档，没有实现候选 |
| 0.9.5 原生独立 server 验收 | 环境不足未验证 | 当前二进制为 0.8.0；未启动或连接 server；需另行显式授权 |
| 真实 SSH、终端、编辑器、Agent 验收 | 环境不足未验证 | 未运行；需要相应环境及真实 smoke 的显式授权 |
| OpenSpec 校验 | 环境不足未验证 | `openspec` 未在 PATH；没有运行 `openspec validate`，没有自动安装 |
| 依赖锁变更 | 已完成 | 本次文档工作不变更锁；不将此项表述为运行包锁定已完成 |

没有记录为“失败待决策”的实际运行失败。上游问题属于风险线索；未来实际失败必须记录具体候选、触发步骤、退出码和所需决策，不可转记为环境不足或忽略。

## 较新稳定版与未来升级策略补充

2026-10-18 根据用户要求重新打开官方 [latest release](https://github.com/herdrdev/herdr/releases/latest)，仍重定向到 v0.9.5。它是当前可核实的最新稳定候选，不是永久版本限制；首次实际安装及每次升级前重新核实。以上 v0.9.5 源码与资产记录保留为该版本证据，新候选须重新绑定对应 tag、资产摘要及所需接口，不拿旧结论自动证明新版。

当前没有完成本仓库工作流验收的 Herdr 版本，也没有性能结果。观察到的 0.8.0 不能充当最后通过基线，0.9.5 也不能仅凭发布说明算通过。首轮实际通过后才登记基线；[upgrade-benchmarks.md](upgrade-benchmarks.md) 是已准备的基准与升级计划，runner、fixtures 和实测报告尚未实现或执行。

| 升级来源 | 核实内容与限制 |
| --- | --- |
| v0.9.5 [CLI](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli.rs)、[API ping](https://github.com/herdrdev/herdr/blob/v0.9.5/src/api/server.rs) | CLI 检查协议，ping 提供 server 版本/协议/capabilities。兼容检查应核实所需接口与能力，不能硬编码 client/server 版本字符串相等 |
| v0.9.5 [server CLI](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli/server.rs) | 配置 reload、manifest 查询/更新/reload 是不同入口；关闭后台检查不等于所有缓存和 override 已归一 |
| 官方 [安装更新](https://herdr.dev/docs/install/)、[连接机器](https://herdr.dev/docs/connecting-machines/) | 访问日 rolling 文档区分磁盘更新与仍运行旧版的 server、按能力检查兼容；具体目标 release 的支持须重新确认，不据此停止旧实例 |
| 官方 [配置](https://herdr.dev/docs/configuration/)、[Agents](https://herdr.dev/docs/agents/) | 访问日 rolling 文档区分 reload 与启动期设置，检测规则可以独立更新且存在 local override；binary/config/rules/integrations 必须分别记录 |
| 官方 [session state](https://herdr.dev/docs/session-state/) | 访问日 rolling 文档将 live handoff 标为 experimental/opt-in，且存在连接/请求边界；不作默认升级或无损回退保证 |

本轮新增委派仍按角色配置执行：scout `gpt-6-luna / high` 负责升级来源证据，executor `gpt-6.1-sol / medium` 负责基准计划，主代理负责策略与规范一致性。没有执行安装、原生基准、真实 Agent 或活动 server 操作。
