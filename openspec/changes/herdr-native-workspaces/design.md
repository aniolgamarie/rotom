## Context

本变更采用用户确定的方向：未修改的 Herdr 接替服务器上 tmux 的主力位置，Rotom 提供最小项目入口和受管配置，Avalon 继续独立编辑与审查。Agent 状态不承担调度或完成判定。

当前 `termcfg` 只管理 zsh/tmux，组件枚举还存在于机器配置、catalog、state、previous、journal、环境检查和呈现代码中。新增 Herdr 不能只加一份 TOML；必须覆盖旧状态兼容和恢复检查，但不需要重构事务引擎。现有 `agentcfg` 提供部署后 run、显式 cwd、机器 editor 和环境继承白名单。

本机为 Linux x86_64，现有 Herdr 元信息返回 0.8.0；采用尽量新的稳定版，2026-10-18 重新核实的当前候选仍为 0.9.5。首次安装时若已有更新稳定版，应先评估新版而非机械沿用旧候选。本机系统 Python 为 3.8.17，仓库 `.venv` 为 3.11.11；这些是验收环境记录，不是跨机器版本要求。工程在 `pyproject.toml` 和 `uv.lock` 中声明 Python `>=3.11`，不固定解释器补丁版本。当前会话位于 SSH/tmux，直接在其中验证 Herdr 会额外引入嵌套协议和前缀问题。完整事实与来源见 [evidence.md](evidence.md)。

本轮生成设计文件与独立 worktree，未写运行时代码、部署配置或切换主力入口。OpenSpec CLI 未在 PATH，当前是手工准备的 spec-driven 工件，未通过 `openspec validate`。

## Goals / Non-Goals

**Goals**

- 普通 SSH 进入指定服务器环境后，按 checkout 找到项目工作区；终端用途稳定，默认复用。
- 将已有 termcfg 所有权、冲突、备份和恢复机制扩展到一份声明的 Herdr 配置。
- 保持 Avalon launcher、Agent profile/cwd/HOME、运行包准备和账号状态的现有边界。
- 分别取得离线测试、原生终端、真实客户端及可选 Agent 集成证据。

**Non-Goals**

不构建终端数据库、守护进程、侧栏、任务系统或跨平台包管理器；不追踪每次 cd，不猜测会话，不增加默认终端控制 skill，不修改宿主。不调整 Avalon 的语言服务、索引或 Review 功能。不自动关闭长任务，不重放历史 shell 命令，不用新 tmux 接管 Herdr 进程。

## Decisions

### 1. 单台服务器使用一个明确选择的主 server

工作入口通过私有机器配置选择一个 Herdr 可执行文件和一个命名 session。不同 server 的对象绝不混用。环境中的 socket/pane/workspace 只提供上下文线索，不能覆盖明确的 server 选择；不匹配时停止操作并给出说明。

0.9.5 的 `workspace focus` 使用 server 的全局活动工作区，并非按 client 保存焦点。这是当前架构的公开边界：同一 server 上桌面和手机可以共同查看/操作，但切换项目会影响其他客户端。若以后要求两个客户端同时独立停留在不同项目，应重新评估原生能力或使用不同原生 session；本变更不实现客户端焦点代理。

外部 `work enter` 需要编排原生 server 准备、项目打开和 TUI attach；内部调用只查询/聚焦。没有单条原生命令原子完成整个外部冷启动链。首阶段必须固化实际 argv、启动就绪检查、单 server 启动锁及失败处置。只允许启动原生 Herdr server，不新增 Rotom 常驻进程；普通工作入口不下载依赖、不升级现有 server、不替换运行包。不通过停止旧 server 解决版本差异。

首轮交互证据使用普通 SSH 直连服务器 Herdr。当前 tmux 内的调用不应静默嵌套；给出直连入口说明。主动进行的嵌套测试单独记录，不将嵌套结果当直连结果。

### 2. Git checkout 使用原生 worktree open，避免第二套项目清单

身份为 `(selected server, canonical checkout root)`。用户传入 Git 子目录时，以该 checkout 的 top level 作为根，再解析符号链接；不能使用 common Git directory 合并不同 worktree。仓库/分支名只影响显示，分支切换不改变身份。

v0.9.5 的 worktree open handler 对路径 canonicalize，并查找对应的已打开工作区。实现优先使用这个原生入口，以路径打开已有 checkout，不调用 Git worktree create/remove、不猜分支唯一性、不复制用户工作树。snapshot/restore 会保留原生 worktree membership。仍需检验普通主 checkout、linked worktree、切分支和外置 build 目录的实际 native 查询结果；不能只根据 handler 名称宣称所有边界通过。

普通 workspace 的 cwd 可能优先取第一个 tab/root pane 的实时 cwd，不能直接用 list 中的 cwd 充当不变项目身份。native tokens 也不能未经证实就当冷重启后的持久注册表。显示标签、shell 标题、Git branch、前台进程 cwd 都不作为替代身份。

第一阶段只接受 Git checkout 路径。`work enter` 对非 Git 目录在启动或修改 server 之前退出 2，提示改用 Herdr 原生“临时”工作区。自动进入/复用非 Git 项目仅在证明原生可靠身份和重启语义后另行纳入；不为此新增终端数据库。此处是对原方案“显式非 Git 目录也可成为自动项目”的实施收缩，不能在文档中写成已支持。

### 3. 用途复用只聚焦，不重跑命令

`work open` 的用途限定为 `shell/edit/build/debug/pi/codex/dsh`。`shell/build/debug` 新建普通交互 shell；入口不猜构建命令或调试器参数。`edit` 启动已选 Avalon launcher，Agent 用途启动明确配置的入口。

每个用途有一个明确的 primary；`--new` 创建新实例，不替换已证明存在的 primary。不根据最近活跃时间、Agent idle、标题或现有同名 tab 选 primary。若多个实例身份冲突则报错，不能任选一个。已确认 primary 关闭后可以创建新的 primary；额外实例不会自动被晋升。

用途 metadata 仅保证当前运行 server 内的关联：冷恢复会清空 tokens，不能自动把恢复布局中的同名 tab 重新认作 primary。身份未知不等于不存在，默认 `work open ROLE` 此时退出 4，只提示原生导航或显式 `--new`，不新增/接管/关闭终端。用户明确 `--new` 且没有已证明 primary 时，可以为该用途建立新的 primary，旧布局对象保持非受管；其他用途的未知状态不因此自动解除。新建空工作区与冷恢复旧工作区须在原生查询/运行期标记中可区分，无法区分就按未知处理。在证明原生持久用途身份之前，不承诺跨冷重启的用途自动复用。

复用不读取 shell 输入行，不发送命令、Enter、控制字符，不改变 cwd，不恢复 Agent 会话。已存在的用途终端即使是 idle，也只聚焦。手工新建的 tab/pane 保持原生行为，不因名称相同就被接管。

每次从调用终端解析上下文，重新查询当前 server、pane、workspace 和终端成员关系。移动后不继续相信启动环境中的旧复合 ID，也不能因另一个客户端改变全局焦点而作用于其项目。若只能查询全局活动项而无法证明调用终端身份，则失败并提示明确目标。移动不自动改变原有进程的项目；归组后用途和项目标记不一致时不向该 pane 发送启动命令。

### 4. 原生启动路径也要检查参数边界

外层 Python `subprocess` 使用参数数组、超时和受控环境，但这不能证明底层启动安全。0.9.5 的 tab create 没有通用 command/argv 参数；`pane run` 把参数拼成终端输入；`agent start` 的 args 数组最终也经目标 shell 编码后发送到 PTY，且其 executable 限定为已知 Agent，不能指定 Avalon 或 agentcfg launcher。

创建 shell 可以使用原生 tab/pane 创建接口；启动 Avalon 和受管 Agent 必须在新建且确认拥有的终端上使用已验证的公开启动路径。若原生内部最终使用 shell 字符串，则只允许一处明确的 shell quoting 边界，逐参数编码、没有 eval，覆盖空格、中文、引号、美元符号、反引号和换行拒绝等情形。不得把启动字符串送到复用的终端；不把“调用 Herdr 时用了 argv”作为完整证明。

如果官方接口无法满足这些约束，先交付普通 shell 入口并记录 editor/Agent 启动限制，不能修改上游或声称用途启动已完成。

### 5. 最小机器配置沿用现有选择与非秘密读取

工作入口继续使用已准备的仓库 `.venv`。解释器遵循工程声明的兼容范围，不检查其是否精确等于本机的 3.11.11，也不要求替换系统 Python。依赖按现有锁准备；较新解释器的实际支持由依赖兼容与对应测试证明，不能将最低版本声明当成所有未来版本的验收结论。Node.js 沿用各受管 Agent 已有运行包与版本契约，本变更不新增系统 Node.js 精确版本要求。日常入口仍不隐式安装或切换运行时。

工作入口沿用 `--machine NAME`/`--local PATH` 的机器选择，默认机器仍为现有 default 规则。拟新增可选 `machine.work`，仅保存单个 Herdr executable、session、Pi/DSH profile 映射、独立 Codex executable 及其 daemon 模式。具体字段在实现时按此语义固化并严格校验；不增加通用命令模板语言。

编辑器直接读取 `machine.editor`，不再定义第二个 editor 设置。其值继续是单一可执行名称或路径；私有机器填写实际 `avalon-profile/bin/avalon`。调用时使用项目 cwd，不将完整 shell 命令塞进 editor。

普通 shell 和 edit 不应为了项目管理加载秘密文件。现有 `load_local(..., load_credentials=False)` 可以延迟凭据加载，工作入口必须保持该边界，不解析 SecretStore、不读取认证或 session 文件。严格配置校验和错误输出也不得泄露私有字段正文。新增可选字段不能使已有机器配置失效。

DSH/Pi 启动向现有 `agentcfg` 传递明确机器选择、profile 和 `run --cwd CHECKOUT`；不直接启动包缓存里的宿主、不执行 sync/apply、不在 workspace 层设置隔离 HOME。独立 Codex 不是 agentcfg 适配器，使用官方 executable，默认 no-daemon 模式；需要 remote control 的入口可以显式选择 daemon，并标注关联限制。不会修改全局 alias、Pi 的委托或现有 daemon。

外置 build/log 目录不改变已进入项目。第一阶段不新增构建目录别名系统；有实际映射需求再使用私有显式声明，不能按目录名相似度猜测。

### 6. termcfg 只扩组件，不扩成安装器

管理一份 catalog 声明的 Herdr 配置文件，不拥有整个目录。配置需要与实际 native 路径及 XDG 行为核对，不能假定现有 catalog 的 HOME 目标天然覆盖所有覆盖目录。无法表达的私有路径先显式拒绝，不静默部署到不生效的位置。

在现有 config/catalog/machine/state/journal 中允许新增组件名，保留未选择 Herdr 的旧机器语义和旧 v2 状态。测试覆盖旧 previous/pending 的读取恢复、新组件部分写入和回滚。不要仅为多一个枚举改写既有事务顺序。使用过新组件后，旧程序可能无法读取包含 Herdr 记录的状态；配置 rollback 不承诺程序降级兼容，不能靠切回旧二进制修复 pending。

已有目标仍走显式采用/冲突流程。只写声明文件，不碰 socket、session、缓存、日志、机器生成的集成和账号；不自动 reload 活动 server，不以终止进程获取写入权。应用和回退沿用已有所有权及备份机制。

二进制使用单独明确的安装/升级步骤。记录官方 release asset、SHA256、架构和实际候选；不把它加入 zsh/tmux 的插件解析器或改造成跨平台安装后端。`work`、shell 和 Agent 日常启动完全离线。

### 7. 候选配置保持终端优先

保留用户给定的少量候选设置，逐项核实字段与值，而不是复制默认配置。关键意图为 `C-x` 前缀、前缀 detach、cwd follow、稳定用途名、关闭声音/toast、禁自动 Agent 恢复、stable channel 且关闭后台版本/manifest 检查、禁实验 history。界面折叠后的 hidden 不等于启动即隐藏侧栏。

不得抢占无前缀的 `Ctrl+h/j/k/l`；Goto 保留原生前缀入口。原样输入 `C-x` 和 Avalon 原生组合键必须有实际可用路径。窗口标题模板需要原生占位符校验，不只检查 TOML 类型。

版本检查分别覆盖磁盘 executable、运行中 server、加载配置和实际检测规则。关后台更新不删除旧 manifest 缓存或私人覆盖；验收要记录生效来源/版本/摘要。新版检查使用独立环境，不使用实验 live handoff 更新活动长任务环境。

### 8. 状态增强最后接入

人工终端核心独立于 Pi/Codex/DSH 状态。Pi 优先采用与选定 Herdr 发行版对应的官方扩展，来源、许可、资源声明和加载路径通过 Rotom 现有机制进入选定实例。不能因为全局安装命令成功就认定受管 Pi 已加载。

Herdr 环境只在实际启用对应集成时通过 `machine.environment.inherit` 声明必要变量，不继承整个父环境、不伪造 TMUX、不把 socket 当成只上报权限。当前沙箱无法容纳状态扩展时保持关闭，不新增权限代理。DSH 插件须先证明依赖、锁版本、生命周期和目标 pane 兼容，不覆盖 peer dependencies 或另增 profiles 绕过。

Avalon 不增加终端插件；Review 维持显式刷新、冻结快照和选定导出文件交接，关闭 Review 不删除已保存导出。只交接选定文件，不开放整个状态目录。SSH 剪贴板保持普通 yank 内部寄存器、显式 `+` 复制、不发 OSC 52 读取查询。

### 9. 持续采用较新稳定版，以可重放基准决定升级

版本策略分为三个对象：当前上游稳定候选、最后完成本机验收的版本、每次安装使用的精确资产。每次首次安装和显式升级前重新查询官方 stable release、检查变化和相关缺陷；默认不选预览版。当前候选 0.9.5 不是永久上限，也不代表已经有通过的生产基线。既有 0.8.0 只有元信息观察，不冒充已验收基线。

首次通过人工终端验收后，将该版本与配置、检测规则、集成、协议/能力及基准结果登记为首个基线。后续优先评估最新稳定版；候选遇到阻断问题时保留最后通过版本，并记录原因、缺失证据和重新评估的触发条件，不因一次失败永久放弃更新。

每次评估精确绑定 release/tag、平台资产与摘要、磁盘 binary、实际 server、配置、规则及集成身份，以便复现。入口不能硬编码 `version == 0.9.5`，也不能只凭 `version >= 0.9.5` 假定未来版本兼容。按所需公开协议/能力和已有验收记录检查；缺少证据的新版可以在独立测试环境评估，生产变更须完成对应门槛。本文中 0.9.5 的源码结论保留版本限定，新版可能改善既有限制，须据对应 tag 重新判断并更新规范。

升级基准使用版本化的合成项目、worktree、终端数量、固定输出流和输入事件；不依赖真实 Agent、业务目录或对话。最后通过版本与候选使用同一机器、同一客户端/尺寸、同一 workload，交错运行 A/B；分别测固定检测规则的 binary 对比和候选完整配置/规则包，避免同时改变变量而错误归因。正确性是硬门槛，性能记录启动/attach/enter/open 延迟、CPU、RSS、唤醒和持续增长；采样、噪声、阈值、缺失数据和报告格式见 [upgrade-benchmarks.md](upgrade-benchmarks.md)。首次基线未建立前只报告测量值及未校准状态，不填写虚构的相对退化结论。

顺序为显式选版与差异审查、版本目录暂存、独立 server 契约/基准、真实 SSH 输入和编辑器验证、仅新工作的试用、再显式切换未来启动入口。磁盘选择切换不表示活动 server 已升级，不终止旧 server、不默认 live handoff，旧任务自然结束。检测规则和可选集成升级也单独记录，不能在相同 binary 版本下悄悄改变基线。

回退分别处理启动入口、受管配置、native 持久状态。保留旧包不等于旧包能够读取新版写过的快照；在专用合成状态中验证格式和回退路径，不能把新版状态直接交给旧 binary 猜兼容。确需真实私人状态备份/迁移时另行明确范围并遵守私人存储权限；不把会话/缓存目录纳入 termcfg 公共同步。回退启动入口不能迁移或恢复已经运行的进程。

## Risks / Trade-offs

| 风险或限制 | 处理与门槛 |
| --- | --- |
| 当前磁盘 Herdr 是 0.8.0 | 安装前重新选取较新稳定候选并核实资产；现有 server 未核实，不假定未运行或可以停止 |
| 同 server 全局工作区焦点 | 按共享主环境验收并明确告知；独立客户端焦点不在本变更承诺内 |
| 非 Git 项目和用途标记冷恢复 | 先证明原生身份；不能证明则缩小支持范围，不以标题/动态 cwd 补齐 |
| 原生请求没有已证明的幂等键 | 单 server 范围序列化、创建后查实；超时结果不明先对账，无法证明则返回冲突 |
| CLI 锁不覆盖用户原生操作 | 重新查询返回 ID 和成员关系，检测重复/关闭/移动，不把本地锁称为 server 全局事务 |
| `pane run` 文本注入，tab create 没通用 argv | 追踪公开启动链；只在新拥有终端使用受测编码边界，复用只聚焦 |
| zsh 重绘和客户端输入/剪贴板差异 | 用真实 zsh、Avalon、CJK、resize、SSH 客户端验证；不以 Fish 修复或纯 PTY 测试代替 |
| termcfg 扩枚举触及恢复状态 | 复用现有事务，增加旧状态、partial failure 和 rollback 的定向回归 |

## Migration Plan

1. 当前独立 worktree 中完成契约门槛和离线实现；不吸收主工作树或其他工作树的无关改动。
2. 明确准备当次选定的较新稳定测试包（当前候选 0.9.5），在专用 HOME/XDG/server 中执行已获授权的原生验收，并建立首个实际基准。
3. 用普通 SSH 和新工作验收人工终端，包括三项目、多 worktree、20–30 终端、输入、断连、多客户端尺寸和资源。
4. 阻断项通过后，再将主入口切到 Herdr；旧 tmux 会话自然结束，保留 tmux 备用入口。
5. 分别启用并验收 Pi、Codex、DSH 增强。只有实际测试过的 Linux/客户端组合标为通过。

输入错误、错误 cwd、错误目标或会话关联、权限退步、任务意外退出均阻止切换；状态图标、通知和 DSH 增强缺失不阻止已验收的人工终端核心。具体观察步骤见 [acceptance.md](acceptance.md)。

## Validation Strategy

默认测试使用临时 HOME/XDG、阻断网络、假子进程和虚构 profile，不启动第三方宿主。原生专用 server、真实 SSH 终端和真实 Agent 独立记录并取得所需显式授权。记录实际 argv、候选/锁身份、退出码和证据，不把环境不足写成通过。

文档本轮完成后，只运行匹配范围的结构、链接、公开内容与 diff 检查。运行时代码实现后再执行新测试及受影响回归；最终审查只针对写入结束后的稳定候选，后续修改重跑受影响检查。
