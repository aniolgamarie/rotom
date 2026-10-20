# Herdr 项目工作区

`work` 将明确选择的 Git checkout 对应到原生 Herdr 工作区，再按用途聚焦终端。布局、Goto、分屏和手工终端仍使用 Herdr。Agent 状态只供查看，不决定任务完成、重试或关闭。功能分支的实现、隔离检查和原生分项记录见 [实施证据](../specs/005-herdr-project-workspaces/implementation-evidence.md)，当前主线组合的检查见 [合入记录](../specs/005-herdr-project-workspaces/integration.md)。旧原生收据不自动覆盖本次集成后的配置、锁或会话；本次集成离线验证不能证明当前 `pi-base` / `pi-pro` 的真实会话已通过，也不表示生产已切换。

## 准备和配置

业务代码使用仓库已准备的 Python >=3.11 `.venv`。系统 Python 3.8 可以转交入口；不要求 3.11.11 等补丁版本完全相同。`work` 不运行 `uv run`、安装依赖或自动下载。Node 的运行兼容范围沿用相应 Agent 配方，依赖锁中的精确身份用于复现和验收。

先显式准备未修改的官方稳定版 Herdr。选择时核对最新 stable，不把研究候选 0.9.5 固定为永久版本门禁。运行时核对公开协议与所需能力；发行资产、平台和校验收据必须在原生验收中精确记录。步骤见 [升级指南](herdr-upgrades.md)。

在私人 agentcfg 机器配置中显式增加：

```toml
[machine]
id = "workstation"
editor = "/opt/editor-profile/bin/avalon"

[machine.work]
herdr_binary = "/opt/herdr/current/herdr"
session = "main"
pi_profile = "pi-base"
dsh_profile = "dsh-default"
codex_binary = "/opt/codex/bin/codex"
codex_daemon = false
```

路径均为示例；在现有私人文件中合并字段，不重复建立已有表。Pi 也可显式选已准备的 `pi-pro`，参见 [Base/Pro 指南](pi.md)。editor、Agent profile 和 Codex 入口只在请求对应用途时必需。单 executable 可为绝对路径或简单 PATH 名称，不能填 shell 命令。Pi/DSH profile 必须已部署且完整运行包已准备，不从默认 profile 猜测。配置读取不解析凭据；秘密继续由既有 `agentcfg run` 按需处理。

## 一次性切换步骤

先准备上面的官方 Herdr binary、仓库 Python >=3.11 环境，以及所需的独立 Avalon executable 和 Agent 配方/运行包，再修改私人 agentcfg 文件的 `machine.editor` / `machine.work`。准备步骤见 [首次安装](getting-started.md)、[Pi](pi.md) 和 [DSH](dsh.md)；`work` 不自动安装、部署或登录。

Herdr 配置是 [termcfg](termcfg.md) 的可选组件。以下 `/opt/rotom` 是虚构的仓库绝对路径，须替换为已合入 `main` 的 checkout 入口；这样在业务 checkout 内也不会误用 `./work`，也不会调用仍停留在其他分支的仓库副本。示例始终选择 `workstation`。agentcfg 的私人机器配置与 termcfg 的私人组件选择是两个文件，须分别准备。

新 termcfg 机器选择可用：

```sh
/opt/rotom/termcfg --machine workstation init-local --component zsh --component herdr
```

已有选择使用 `init-local --edit`，列出全部保留组件并加上 Herdr。`--component` 替换完整选择，并非追加；例如已有 zsh/tmux 时：

```sh
/opt/rotom/termcfg --machine workstation init-local --edit --component zsh --component tmux --component herdr
```

在当前 SSH shell 中将仓库根与选定 Herdr 版本的目录加入 PATH，供静态 doctor 定位 `rotom-work-shell` 和 `herdr`。下面的目录仍须替换为实际路径，并与 `machine.work.herdr_binary` 对应；无需为此修改全局 shell 配置。

```sh
export PATH="/opt/rotom:/opt/herdr/current:$PATH"
```

显式预览并审阅，再应用当前计划：

```sh
/opt/rotom/termcfg --machine workstation plan --component herdr --json
/opt/rotom/termcfg --machine workstation apply --component herdr --plan-id ID
/opt/rotom/termcfg --machine workstation doctor --component herdr
```

`ID` 必须换成刚返回的实际计划 ID。已有文件按 [termcfg 采用/冲突流程](termcfg.md)处理，不以覆盖绕过冲突。doctor 只证明静态准备，不证明真实启动或提示符正常。保留旧 tmux 长任务；下一步只让明确选择的新工作进入 Herdr，不迁移或停止旧进程。

只管理 `.config/herdr/config.toml`（0600），不管理 session、socket、缓存、日志或集成生成文件。非默认 `HERDR_CONFIG_PATH` / `XDG_CONFIG_HOME` 目标被拒绝。原生新 tab 使用 `rotom-work-shell` 与 `non_login`，无启动意图时进入原 `SHELL`（空值 `/bin/sh`）。新 server 的 PATH 由 `work` 前置仓库根，既有 server 不被重启或改环境。

`work` 要求配置文件存在、为当前用户的私有普通文件，并检查 launcher/non_login/禁用 Agent 自动恢复的意图。启动新 server 前用同一路径运行官方 `herdr config check`，非零诊断或期间文件改变立即失败。该命令只读配置，不连接 server；缺文件却会使用默认值，因此不能单独以退出 0 证明文件存在。依据：[0.9.5 CLI](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli.rs)、[配置加载](https://github.com/herdrdev/herdr/blob/v0.9.5/src/config/io.rs)。普通 `termcfg doctor` 只做静态准备检查，真实加载与 zsh 提示符仍须原生验证。

## 日常进入和用途

在普通 SSH 终端、tmux 之外先执行 `enter`：

```sh
/opt/rotom/work --machine workstation enter /projects/kernel
```

`enter` 接受现存 Git checkout 或其子目录，按 realpath 归一；linked worktree 各有工作区，同名仓库不合并。新建linked工作区时先查询原生worktree列表，从返回的主仓库source发起open；归属仍取目标checkout。非 Git 目录退出 2；临时任务使用 Herdr 原生临时工作区。只在所选 session 确实不存在时启动独立 server，连接失败不会触发另建。Herdr 外部进入后原生 attach；内部只聚焦。旧 tmux 内的外部进入退出 4，先显式离开旧复用器。

项目身份是所选固定 server 端点与 checkout 路径。branch、tab 标题、后续 `cd` 或外置构建目录不会改归属。内部 `enter` 聚焦到另一工作区，也不会把发起命令的旧 shell 移过去；在目标项目的实际 pane 内运行 `open`。

```sh
/opt/rotom/work --machine workstation open shell
/opt/rotom/work --machine workstation open build
/opt/rotom/work --machine workstation open debug
/opt/rotom/work --machine workstation open edit
/opt/rotom/work --machine workstation open pi
/opt/rotom/work --machine workstation open dsh
/opt/rotom/work --machine workstation open codex
# 显式增加同用途实例：
/opt/rotom/work --machine workstation open debug --new
```

每次 `enter` / `open` 保持同一 `--machine`。也可始终用 `--local FILE` 选择同一个私人 agentcfg 文件；两种选择互斥，且在子命令之前。`open` 应在所选项目的实际 Herdr pane 中执行。

用途严格为 shell/edit/build/debug/pi/codex/dsh。已有用途只聚焦，不发送输入、不改目录、不重跑。shell/build/debug 新建普通交互 shell，编译和调试命令由人输入；edit 打开所选 Avalon，pi/dsh 打开已准备的受管 profile，codex 打开所选独立 CLI。只有 `--new` 增加同用途实例，已有 primary 保持稳定。原生 tab/分屏留在当前工作区，不被自动登记为用途。

`open` 必须从所选 Herdr 中能核验的项目 pane 发起。缺上下文、过期 ID、其他 session 或未确认项目均退出 4；`--new` 也不能绕过。环境变量仅用于定位，实际归属来自原生当前查询。新程序通过新 pane 的一次性 ready/commit/accepted 交接启动，意图绑定配置选择、代码来源、端点和期限，不进入历史 shell 命令，不在旧终端输入命令。

错误码：2 参数/配置；4 上下文冲突或未决恢复；5 依赖/协议/加载检查失败；6 文件系统失败。业务 exec 之后保留程序本身退出码。`open` 的成功只证明终端交接，不能证明 Agent 已登录或任务完成。

## 恢复与未知结果

detach 或 SSH 断线后，重新 SSH 登录，在 tmux 之外重复同一个入口：

```sh
/opt/rotom/work --machine workstation enter /projects/kernel
```

SSH 断开、客户端退出、启动 shell 退出时，接回仍运行的 server 和原进程。server 停止或机器重启后恢复布局并不恢复原编译/调试进程；Agent 自动恢复关闭，不自动选最近会话，不重放历史命令。

冷恢复丢失 metadata 的用途视为 unknown，普通 `open` 返回 4；显式 `--new` 只为该用途建立新 primary，不收养旧 pane。关闭/移动 primary 只有在完整原生查询证明后才允许重新创建；标记被擦除不能当作关闭，不提升 extra。

创建或交接超时不重发。未决 pending 阻止所有新建，已核实 primary 仍可聚焦。等待原操作期限后再 `work enter CHECKOUT`：只有唯一同 op、成员/项目吻合且已证明 failed 并清 commit，或 accepted 且 commit 匹配，才完成登记。否则保持未知，先用原生 Goto/普通 tab 工作；待该 server 全部任务自然结束且另获明确停服授权，才原生停服并冷恢复。不得手工清 pending 后假设旧 launcher 已取消。完整查询命令见 [runbook](../specs/005-herdr-project-workspaces/contracts/work-cli.md#pending-recovery-runbook)。

launcher 失败会尝试写不可逆 failed 标记、清本 pane commit，再回普通 shell。若 accepted 请求可能已经生效且失败标记也无法确认，则退出 launcher，避免把普通 shell 留成“工具已交接”的假象。失败上报最多额外 2 秒，不延长业务准入期限、不重启任务。

## Avalon 和 Agent

### 常用键位与复制

Herdr 前缀为 **Ctrl+x**：先按下并松开，再按后一个键。Avalon 内部窗口键位属于编辑器。

| 键位或命令 | 用途 |
| --- | --- |
| `Ctrl+x`，再 `g` | 原生 Goto，选择工作区或终端 |
| `Ctrl+x`，再 `d` | detach 当前客户端，保留 server 和运行任务 |
| Avalon `Ctrl+w`，再 `v` | 编辑器内垂直分窗 |
| Avalon `Ctrl+w`，再 `h` / `l` | 编辑器内切到左 / 右窗口 |
| Avalon `:normal! "+2yy` | 从光标处显式将两行复制到 `+` 寄存器 |

其他布局/分屏键位以所选 Herdr 版本的原生帮助为准，不占用无前缀 Ctrl+h/j/k/l。字面 Ctrl+x、Shift+Enter 仍须按实际客户端组合核对。

Avalon 普通 yank 留在内部寄存器。远程复制到本机使用独立 profile 已准备的显式 `+` / OSC52 写入路径，再用本机终端或系统粘贴；先用已知非秘密文本检查结果。上述两行命令可避开直接输入双引号触发的寄存器提示。该路径不查询原剪贴板；终端的 OSC52 策略和 SSH/客户端支持仍会影响结果。

edit 直接调用已验收独立 Avalon profile 的 `bin/avalon`；无需新插件或 `NVIM_APPNAME` 替代。Agent 修改后，由人在同 checkout 的 Avalon 显式刷新冻结 Review，审查并导出选定修复要求，再交给明确目标 Agent，最后由 build/test 终端验证。work 不读取 Review 目录，不自动刷新/广播/删除导出；关闭 Review 保留已保存的 review.json/review.md/prompt.md 与清单。

Pi/DSH 使用 `agentcfg [--local FILE] --profile ID run AGENT --cwd CHECKOUT`，保留已有实例 HOME、配置、凭据和状态，不在工作区层面设置隔离 HOME。准备不足先失败，不自动 sync/apply/login。独立 Codex 默认附 `--no-daemon`；`codex_daemon=true` 仅为该入口省略该参数，不改 alias、全局配置、Pi 委托或活动 daemon。共享 daemon 的 pane/会话关联限制见 [上游问题 #4649](https://github.com/herdrdev/herdr/issues/4649)，没有可靠身份时保持 unknown。

`enter`和普通用途操作的管理总期限为30秒；受管Pi/DSH的`open`为60秒，包含父调用和新pane各自的完整运行包校验。等锁最多10秒、connect2秒、单request5秒，均受剩余总期限限制；launcher继承父调用的绝对期限，不重新计时。交互程序成功exec后不受该管理期限终止。

状态扩展本轮全部保持关闭：

| 工具 | 已有接缝 | 本轮决定与启用条件 |
| --- | --- | --- |
| Pi | 官方扩展 + Rotom 受管资源/实例目录 | 未取得当前实例加载、依赖身份和双实例事件证据，暂不纳入资源锁 |
| DSH | 社区 dsh-herdr 插件 | 依赖声明与当前锁兼容性及真实生命周期尚未验证，不强制 peer，不新建 profile |
| Codex | 屏幕识别、原生会话信息 | 提示可看，未证明关联不接管会话、不自动恢复 |

`HERDR_ENV`、`HERDR_PANE_ID`、`HERDR_BIN_PATH`、`HERDR_SOCKET_PATH` 仅在后续选择集成时通过既有 `machine.environment.inherit` 逐项声明，不自动扩白名单。socket 能控制终端，继承变量不等于仅有状态上报权限；不安装控制其他终端的 skill、不扩 sandbox socket 权限、不改上游源码。启用前分别验证两个根实例、子 Agent、迟到事件与目标 pane；不能证明就继续关闭。

## 原生输入与存活验收

默认 pytest 只用临时 HOME、fake API/子进程和秘密哨兵。真实 Herdr、SSH/终端、Avalon/Agent/账号及基准分别按授权范围执行。先在合成 checkout 和独立 server 验证，再考虑新工作 canary；任何代码/测试通过都不自动切换入口。

每个拟支持组合登记服务端系统/架构、client 版本、SSH 路径、提示符、资产及配置/规则身份。用固定合成文本记录器，在两个尺寸 120×40 和 80×24 客户端逐项核对：

1. 中文、宽字符、组合字符、Shift+Enter、多行 Prompt 与字面元字符，输入字节/目标一致；保持 Avalon 原生组合键路径。
2. C-x 前缀、字面 C-x 的原生透传路径、Goto（prefix+g）、分屏导航，连续 20 轮 resize/focus 无影响使用的残留或错位。不占用无前缀 Ctrl+h/j/k/l。
3. 首次与重复显式 `+` 复制已知中文/多行文本，在本机测试文本框人工核对，再测试终端粘贴。只发 OSC52 写，不发读取查询、不读取原剪贴板；普通 yank 保持内部寄存器。
4. 启动持续合成 producer 并记录 PID/启动时刻，分别执行 client detach、SSH 强断、启动 shell 退出；重新连接后必须是同进程且输出连续。另测停止 server 后布局恢复且原进程不会被宣称恢复，不重放命令。
5. 桌面与窄屏/手机同时查看同 tab，登记实际尺寸协调规则与焦点影响。共享 server 不等于每个 client 有独立 TUI 尺寸。

输入错误、错误cwd/目标/会话、权限退步或任务意外退出均阻断切换。状态图标和通知未完善不阻断核心。本机Linux x86_64、Herdr0.9.5与合成PTY，以及OpenSSH8.0回环双客户端的精确输入、20轮分屏/resize/zoom/focus、detach/客户端退出/重接同进程存活与冷恢复已有分项证据。实际macOS/Ghostty SSH的中文输入法、两行粘贴、字面C-x及Shift+Enter也已记录：普通Enter为CR、Shift+Enter为CSI-u。记录器曾漏识别CSI-u前缀，保留失败和仅切换测试键盘模式的干预记录，不冒充修订版fixture完整通过。实体组合为macOS 26.6.2/Ghostty 1.3.1 stable；固定中文多行OSC52写入后本机粘贴、20轮视觉核对、detach及退出SSH后的重接均已完成，同一记录器PID/starttime保持。Avalon内部Ctrl+w v/h/l已观察到分窗和左右焦点变化，`:normal! "+2yy`的整行+寄存器事件与本机两行粘贴均已核对；直接按双引号会触发当前Avalon寄存器提示，可使用上述原生命令；手机及其他客户端组合未验证。详细收据见实施证据，不因回环SSH、上游二进制或CI成功扩展支持声明。

## 回退

若只想让后续新工作回到 tmux，先 detach Herdr，在普通 SSH shell 使用原有 tmux 入口，保留仍在运行的 Herdr 任务。配置回退先审阅计划：

```sh
/opt/rotom/termcfg --machine workstation rollback --component herdr --plan-only --json
/opt/rotom/termcfg --machine workstation rollback --component herdr --plan-id ID
```

将 `ID` 换为实际 rollback 计划 ID；这不授权停止活动任务。

旧 tmux 长任务自然结束，不能接管 Herdr 进程。程序选择、termcfg 配置 rollback、native state 降级分别验收；不 live handoff、不自动杀旧实例。旧代码不认识新增 Herdr state 时，先用当前代码处理 pending/受管状态，再回退代码；保留所有私人和非受管数据。具体步骤见 [termcfg](termcfg.md) 和 [升级方案](herdr-upgrades.md)。

## 历史功能分支的原生验收边界

下列收据描述旧功能分支的候选、配置和依赖身份；本次集成离线检查须独立记录。尤其旧 Pi 双实例结果不覆盖当前 `pi-base` / `pi-pro` 的真实启动、账号或模型会话，不应据此更新当前支持或生产切换声明。

2026-10-19续验收以本机为唯一测试环境，使用官方0.9.5资产，未替换PATH中既有0.8.0安装或现有server。9个checkout/27个普通终端、enter重复100次及2/10并发、用途复用100次和额外10终端通过；实际37个shell均存活于正确checkout。新server显式umask077，不要求用户修改全局umask。隔离zsh使用现有锁定公共插件及公开示例中的bash兼容shim，不读取私人hook。大体积准备和回归临时文件使用本机安全HOME下的专用0700目录，避免共享临时分区空间不足；不放宽共享祖先保护。

已有独立Avalon profile经work启动并返回正确cwd、独立目录与Review命令；新合成checkout验证冻结、显式刷新、三个导出包manifest及Close保留。其ready/release_qualified标记未提升。独立Codex0.163.0在新pane确认实际--no-daemon及cwd；另由官方CLI使用已有认证、临时会话及只读沙箱，完成明确选定的合成prompt.md模型交接，未复制凭据或整个Review状态。受管DSH复用现有dsh-default及公共锁，隔离准备和实际Node启动通过，cwd、独立HOME/DSH_HOME、运行包身份正确。Pi已通过官方入口重新生成五个锁文件并准备隔离实例，直接来源保持不变、四套slice的传递typebox更新单列。首次30秒期限失败保留；按上述受管预算修订后，primary及extra实际Node双实例分别29.263秒/25.094秒返回0，cwd/profile/HOME与独立租约持续存活通过，最后只清理这两个闲置测试实例和专用server。最新分项与未完成范围见实施证据。

状态增强最终选择全部关闭；关闭路径是本轮交付，未安装或宣称任何实例级状态集成通过。冻结功能分支的严格完整首基线、独立 canary 及回退门禁已完成，见[验收摘要](../specs/005-herdr-project-workspaces/acceptance-summary.json)和[最终实施证据](../specs/005-herdr-project-workspaces/implementation-evidence.md)；这些结果适用于其冻结来源与已声明组合，本次集成离线检查另记，不表示当前 Pi Base/Pro 真实会话或生产入口已切换，也不因合入本身要求重跑已完成的长时基线。
