# Herdr 项目工作区

在服务器上，Herdr 把同一个项目的终端放在一个工作区里。`work enter` 先进入项目工作区；`work open` 再按用途打开或切回终端。你可以让编辑器、编译、调试和 Agent 各用一个终端，之后按用途找回来。

如果你在本机用 Ghostty 通过 SSH 连接服务器，Ghostty 提供本机终端窗口，SSH 负责连接服务器；下面的命令、Herdr 终端、编辑器和编译进程都运行在服务器上。先按后面的[准备和配置](#准备和配置)与[一次性切换步骤](#一次性切换步骤)准备好服务器，再使用日常流程。

## 日常进入和用途

下面的 `/opt/rotom`、`/projects/kernel` 和 `workstation` **都是占位示例**：分别换成服务器上的 Rotom 安装目录、项目路径和你已准备的机器配置名。这里的“机器配置”选择服务器上的私人配置，不是 Ghostty 所在本机的名称。

最短流程只有两步：

1. 在普通 SSH shell、tmux 之外，先进入项目工作区：

   ```sh
   /opt/rotom/work --machine workstation enter /projects/kernel
   ```

2. 进入 Herdr 后，在这个项目的 shell 中打开编译终端；如果当前显示编辑器或运行中的程序，先用 **Ctrl+x，再 g** 切到项目的 shell：

   ```sh
   /opt/rotom/work --machine workstation open build
   ```

如果这个项目还没有 build 终端，会新建项目目录下的**普通交互终端**，由你输入项目实际使用的编译命令；已有时只切回原终端。`build` 只是用途名，不会替你运行编译；`debug` 也不会自动启动调试器。

### 首次打开与再次切回

以下 `open …` 都接在同一个 `/opt/rotom/work --machine workstation` 后面，按需选择即可，不必逐条全部执行。

| 用途 | 尚无对应终端时 | 已有对应终端时再次执行 |
| --- | --- | --- |
| `open shell` | 打开普通交互终端；新工作区的初始 shell 已可复用 | 切回这个 shell |
| `open build` | 打开供你输入编译或测试命令的普通交互终端 | 切回原来的 build 终端 |
| `open debug` | 打开供你输入调试命令的普通交互终端 | 切回原来的 debug 终端 |
| `open edit` | 启动 `machine.editor` 配置的编辑器，例如 Avalon | 切回原来的编辑器终端 |
| `open pi` | 启动已准备并部署的 `machine.work.pi_profile` | 切回原来的 Pi 终端 |
| `open dsh` / `open codex` | 启动已准备的 DSH profile / 所选独立 Codex CLI | 切回相应用途的原终端 |

`shell`、`build`、`debug` 是用来稳定找回终端的用途名称，不是三个预设任务。普通 `open` 找到原终端后只切换焦点：当前程序继续运行，当前目录保持原样，不向里面输入命令，也不自动重新启动程序。即使你已经在 build 终端里切换了目录，再次 `open build` 也不会把它改回项目根目录。

### 什么时候用 `--new`

只有确实需要第二个同用途终端时才加 `--new`。例如：

- 第一个 build 终端正在跑长编译，你想保留它继续运行。
- 用 **Ctrl+x，再 g** 打开 Herdr 原生 Goto，切回这个项目的 shell；不要往正在编译的终端里输入管理命令。
- 在 shell 中执行：

  ```sh
  /opt/rotom/work --machine workstation open build --new
  ```

- 在新终端里自己输入测试命令。现在可以一边编译、一边测试。

额外终端不会替换默认的那个：以后普通 `open build` 仍切回第一个 build 终端。需要找到额外终端时使用 **Ctrl+x，再 g** 的原生 Goto。每次 `--new` 都是新增终端，不是重新运行当前编译，也不是切换到某个固定的第二终端。不要为了“回到编译界面”反复加 `--new`。

每次 `enter` / `open` 保持同一 `--machine`。也可始终用 `--local FILE` 选择同一个私人 agentcfg 文件；两种选择互斥，且在子命令之前。`open` 要在所选项目内能输入命令的 Herdr shell 中执行。`enter` 不会自动启动编辑器或 Agent；它只进入工作区，并在新建工作区时提供初始 shell。

通过 `work` 新启动的 Herdr server，其 PATH 已包含 Rotom 安装目录，终端内也可使用 `work --machine workstation open build`。本页保留绝对路径写法，方便确认调用的是哪个 Rotom 入口。已有 server 不会被自动修改环境；入口找不到时使用完整路径，并按下文检查准备情况。

布局、Goto、分屏和手工终端继续使用 Herdr 原生操作。手工新建的 tab/分屏不会自动登记为上述用途。断线重接见[恢复与未知结果](#恢复与未知结果)，回到旧入口见[回退](#回退)。

## 常用键位与复制

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

Herdr 配置是 [termcfg](termcfg.md) 的可选组件。以下 `/opt/rotom` 是示例 Rotom 安装目录，须替换为服务器上的实际安装目录；使用绝对入口可以在任意项目目录中执行，避免误用 `./work`。示例始终选择 `workstation`。agentcfg 的私人机器配置与 termcfg 的私人组件选择是两个文件，须分别准备。

新 termcfg 机器选择可用：

```sh
/opt/rotom/termcfg --machine workstation init-local --component zsh --component herdr
```

已有选择使用 `init-local --edit`，列出全部保留组件并加上 Herdr。`--component` 替换完整选择，并非追加；例如已有 zsh/tmux 时：

```sh
/opt/rotom/termcfg --machine workstation init-local --edit --component zsh --component tmux --component herdr
```

在当前 SSH shell 中将 Rotom 安装目录与选定 Herdr 版本的目录加入 PATH，供静态 doctor 定位 `rotom-work-shell` 和 `herdr`。下面的目录仍须替换为实际路径，并与 `machine.work.herdr_binary` 对应；无需为此修改全局 shell 配置。

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

## 项目归属与启动边界

`enter` 接受现存 Git 项目检出目录或其子目录，按真实路径归一。同一仓库的不同项目检出目录各有工作区，同名仓库也不合并。为额外检出目录新建工作区时，先查询原生 Git 检出目录列表，从返回的主仓库来源发起打开；归属仍取目标检出目录。非 Git 目录退出 2；临时任务使用 Herdr 原生临时工作区。只在所选 session 确实不存在时启动独立 server，连接失败不会触发另建。Herdr 外部进入后原生 attach；内部只聚焦。旧 tmux 内的外部进入退出 4，先显式离开旧复用器。

项目身份是所选固定 server 端点与项目检出目录路径。分支名、tab 标题、后续 `cd` 或外置构建目录不会改归属。内部 `enter` 聚焦到另一工作区，也不会把发起命令的旧 shell 移过去；在目标项目的实际 pane 内运行 `open`。

只管理 `.config/herdr/config.toml`（0600），不管理 session、socket、缓存、日志或集成生成文件。非默认 `HERDR_CONFIG_PATH` / `XDG_CONFIG_HOME` 目标被拒绝。原生新 tab 使用 `rotom-work-shell` 与 `non_login`，无启动意图时进入原 `SHELL`（空值 `/bin/sh`）。新 server 的 PATH 由 `work` 前置 Rotom 安装目录，既有 server 不被重启或改环境。

`work` 要求配置文件存在、为当前用户的私有普通文件，并检查 launcher/non_login/禁用 Agent 自动恢复的意图。启动新 server 前用同一路径运行官方 `herdr config check`，非零诊断或期间文件改变立即失败。该命令只读配置，不连接 server；缺文件却会使用默认值，因此不能单独以退出 0 证明文件存在。依据：[0.9.5 CLI](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli.rs)、[配置加载](https://github.com/herdrdev/herdr/blob/v0.9.5/src/config/io.rs)。普通 `termcfg doctor` 只做静态准备检查，真实加载与 zsh 提示符仍须原生验证。

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

edit 直接调用已验收独立 Avalon profile 的 `bin/avalon`；无需新插件或 `NVIM_APPNAME` 替代。Agent 修改后，由人在同一项目检出目录的 Avalon 显式刷新冻结 Review，审查并导出选定修复要求，再交给明确目标 Agent，最后由 build/test 终端验证。work 不读取 Review 目录，不自动刷新/广播/删除导出；关闭 Review 保留已保存的 review.json/review.md/prompt.md 与清单。

Pi/DSH 使用 `agentcfg [--local FILE] --profile ID run AGENT --cwd CHECKOUT`，保留已有实例 HOME、配置、凭据和状态，不在工作区层面设置隔离 HOME。准备不足先失败，不自动 sync/apply/login。独立 Codex 默认附 `--no-daemon`；`codex_daemon=true` 仅为该入口省略该参数，不改 alias、全局配置、Pi 委托或活动 daemon。共享 daemon 的 pane/会话关联限制见 [上游问题 #4649](https://github.com/herdrdev/herdr/issues/4649)，没有可靠身份时保持 unknown。

`enter`和普通用途操作的管理总期限为30秒；受管Pi/DSH的`open`为60秒，包含父调用和新pane各自的完整运行包校验。等锁最多10秒、connect2秒、单request5秒，均受剩余总期限限制；launcher继承父调用的绝对期限，不重新计时。交互程序成功exec后不受该管理期限终止。

### Herdr、DSH 的插件与两者之间的桥接

**Herdr 和 DSH 都有插件扩展能力。** 它们的插件负责不同层面的功能：

| 扩展层 | 能做什么 | 本方案如何使用 |
| --- | --- | --- |
| Herdr 自身插件 | 扩展工作流动作、事件响应、终端面板和链接处理；可从 GitHub 安装 | 先使用原生项目工作区和导航，按实际需求选择插件。见 [Herdr 0.9.5 插件文档](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/plugins.mdx) |
| DSH 自身插件 | 通过 Cordis 插件和 bundle 扩展宿主；插件管理器支持安装、移除、启用与配置 | Rotom 已通过受管配方使用 TUI、认证和审查等扩展，仍按原有配置与依赖锁管理。见 [DSH 插件管理器](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/boot/plugin-manager/README.md) |
| DSH 与 Herdr 的桥接 | 把 DSH 的 Agent 生命周期状态报告给对应的 Herdr pane | 社区 [dsh-herdr](https://github.com/TheRealHaoLiu/dsh-herdr) 提供这一能力，须单独验证依赖、实例和目标 pane |

DSH 另有可选的[插件市场组件](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/boot/plugin-market/README.md)，支持配置索引和发现插件；该版本默认 profile 未启用此组件，也没有默认索引来源。当前 Rotom 锁没有纳入这一市场组件，不能据此宣称已提供可直接浏览的商店。

### 本次迁移的状态集成范围

以下记录 Rotom 本次迁移的集成范围；机器上已有的全局集成需用 `herdr integration status` 单独查询。DSH 原有插件继续按原配方使用。

| 工具 | 已有接缝 | 本轮决定与启用条件 |
| --- | --- | --- |
| Pi | 官方扩展 + Rotom 受管资源/实例目录 | 未取得当前实例加载、依赖身份和双实例事件证据，暂不纳入资源锁 |
| DSH | 社区 dsh-herdr 插件 | 本轮未启用；声明的 DSH peer 范围不覆盖当前锁，真实生命周期仍须验证，不强制 peer，不新建 profile |
| Codex | 屏幕识别、原生会话信息 | 提示可看，未证明关联不接管会话、不自动恢复 |

截至 2026-10-21，`dsh-herdr` 0.1.0 的[依赖声明](https://github.com/TheRealHaoLiu/dsh-herdr/blob/1843455eded74721b0582b102d864af16a1e90bd/package.json)要求 DSH agent/session `^0.1.1-rc.2`，不包含 Rotom 当前锁定的 `0.2.1-rc.2`；Cordis `^4.0.1` 则包含当前锁定的 `4.0.5`。这说明需要验证和适配依赖范围，尚不能判定桥接运行时是否可用。其[文档](https://github.com/TheRealHaoLiu/dsh-herdr/blob/1843455eded74721b0582b102d864af16a1e90bd/README.md)限定单个根 Agent，忽略并发根与子 Agent；状态提示也不能承担任务调度或完成判定。

`HERDR_ENV`、`HERDR_PANE_ID`、`HERDR_BIN_PATH`、`HERDR_SOCKET_PATH` 仅在后续选择集成时通过既有 `machine.environment.inherit` 逐项声明，不自动扩白名单。socket 能控制终端，继承变量不等于仅有状态上报权限；不安装控制其他终端的 skill、不扩 sandbox socket 权限、不改上游源码。启用前分别验证两个根实例、子 Agent、迟到事件与目标 pane；不能证明就继续关闭。

### 更新后为什么提示集成，而没有 DSH

`herdr update` 更新 Herdr 程序。若它提示必须停止某个运行会话，并且你确认了 `y`，该会话中的 shell、编辑器、编译和 Agent 进程也会结束；这与 `Ctrl+x`、再 `d` 的断开连接不同。重新启动可恢复的布局不等于恢复已经结束的进程。

更新末尾列出的 `herdr integration install pi`、`codex` 等命令，是针对检测到的旧集成文件或配置的更新提示，不是全部可用 Agent 的清单。0.9.5 的更新器调用 `integration status --outdated-only` 生成该提示；可手动运行 `herdr integration status` 查看集成状态。依据：[0.9.5 更新实现](https://github.com/herdrdev/herdr/blob/v0.9.5/src/update.rs)、[集成 CLI](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli/integration.rs)。

0.9.5 的内置 `integration install` 目标中没有 `dsh`。**DSH 仍可作为项目终端中的程序运行**：在已进入的项目 shell 中执行 `work --machine workstation open dsh`，Rotom 会使用已经准备好的 `dsh_profile`。侧栏中的 DSH 专用状态、事件和会话关联属于另一层增强；社区 [dsh-herdr](https://github.com/TheRealHaoLiu/dsh-herdr) 插件本轮保持关闭，先完成其依赖与真实实例验证再决定启用。使用 DSH 不需要先安装其他 Agent 的 Herdr 集成。

受管 Pi/DSH 的扩展仍按 Rotom 的资源和实例目录配置。全局安装某个 Herdr 集成，不代表受管实例已经加载它；本轮也不执行提示中的安装或卸载命令。

## 原生输入与存活验收

Agent 状态只供查看，不决定任务完成、重试或关闭。功能分支的实现、隔离检查和原生分项记录见 [实施证据](../specs/005-herdr-project-workspaces/implementation-evidence.md)，当前主线组合的检查见 [合入记录](../specs/005-herdr-project-workspaces/integration.md)。旧原生收据不自动覆盖本次集成后的配置、锁或会话；本次集成离线验证不能证明当前 `pi-base` / `pi-pro` 的真实会话已通过，也不表示生产已切换。

默认 pytest 只用临时 HOME、fake API/子进程和秘密哨兵。真实 Herdr、SSH/终端、Avalon/Agent/账号及基准分别按授权范围执行。先在合成项目检出目录和独立 server 验证，再考虑新工作 canary；任何代码/测试通过都不自动切换入口。

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

2026-10-19续验收以本机为唯一测试环境，使用官方0.9.5资产，未替换PATH中既有0.8.0安装或现有server。9个项目检出目录/27个普通终端、enter重复100次及2/10并发、用途复用100次和额外10终端通过；实际37个shell均存活于正确项目检出目录。新server显式umask077，不要求用户修改全局umask。隔离zsh使用现有锁定公共插件及公开示例中的bash兼容shim，不读取私人hook。大体积准备和回归临时文件使用本机安全HOME下的专用0700目录，避免共享临时分区空间不足；不放宽共享祖先保护。

已有独立Avalon profile经work启动并返回正确cwd、独立目录与Review命令；新合成项目检出目录验证冻结、显式刷新、三个导出包manifest及Close保留。其ready/release_qualified标记未提升。独立Codex0.163.0在新pane确认实际--no-daemon及cwd；另由官方CLI使用已有认证、临时会话及只读沙箱，完成明确选定的合成prompt.md模型交接，未复制凭据或整个Review状态。受管DSH复用现有dsh-default及公共锁，隔离准备和实际Node启动通过，cwd、独立HOME/DSH_HOME、运行包身份正确。Pi已通过官方入口重新生成五个锁文件并准备隔离实例，直接来源保持不变、四套slice的传递typebox更新单列。首次30秒期限失败保留；按上述受管预算修订后，primary及extra实际Node双实例分别29.263秒/25.094秒返回0，cwd/profile/HOME与独立租约持续存活通过，最后只清理这两个闲置测试实例和专用server。最新分项与未完成范围见实施证据。

状态增强最终选择全部关闭；关闭路径是本轮交付，未安装或宣称任何实例级状态集成通过。冻结功能分支的严格完整首基线、独立 canary 及回退门禁已完成，见[验收摘要](../specs/005-herdr-project-workspaces/acceptance-summary.json)和[最终实施证据](../specs/005-herdr-project-workspaces/implementation-evidence.md)；这些结果适用于其冻结来源与已声明组合，本次集成离线检查另记，不表示当前 Pi Base/Pro 真实会话或生产入口已切换，也不因合入本身要求重跑已完成的长时基线。
