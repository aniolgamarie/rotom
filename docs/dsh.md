# DSH 配方与升级候选

本分支维护一套 `dsh-default`。2026-10-12 的候选升级尚未完成整套验收：核心/TUI、离线配置和原生人工审批在隔离实例验证；Cursor/Codex/国内 API 真实账号以及 AI reviewer 没有测试实例授权。既有部署不切换，旧状态自动升级受阻止。完整结果见 [升级验收记录](acceptance/dsh-upgrade-20261012.md)。

## 版本、原包与锁

| 组件 | 当前候选 | 来源与边界 |
| --- | --- | --- |
| DSH Core | `0.2.0-rc.2` | `639ed015397290b3745d163aafe02ffee4aa3f84`；预发布版 |
| TUI | `0.14.0` | `c2eee95218d1decfce138f7d31ef7099cc391d00`；未改动 npm 原包 |
| Cursor Provider | `dsh-cursor-subscription@0.6.12` | `936fb5b40b8efb50a5bb2031c81f3c8f553bf7f8`；未改动原包，通过薄终端适配调用公开 API |
| 薄终端适配 | `rotom-dsh-cursor-terminal@0.1.1` | 本仓库 `agents/dsh/packages/cursor-terminal`；使用 TUI 公开 QuestionBridge，不复制 OAuth 或 Cursor wire 协议 |
| 认证 | TUI 的 `./oauth` | 仅挂载 `openai-codex`；不使用旧独立 dsh-auth 包或 OpenAI API key 替代订阅 |
| 公共运行时 | Cordis `4.0.4` / Schemastery `3.18.4` | 安装检查验证主运行路径模块身份相同 |
| 工具链 | Node `24.14.0` / npm `11.19.1` / pnpm `11.19.0` | pnpm 原包固定 integrity 并随锁提供；不全局安装 |

`locks/dsh/pnpm-lock.yaml` 是实际安装使用的完整 frozen 锁。`package-lock.json` 保留 npm 的固定解析证据，包含在锁身份中，但不能据此宣称 npm ci 支持原始 TUI 包。npm 11.19.1 和机器现有 11.9.0 均因 TUI bundled `workspace:*` 元数据失败；0.14.1 原包也保留此形状。pnpm 正常消费原包，不移植旧 metadata 修补。

普通 `sync` 从原始 pnpm 归档验证 SHA-512、解压固定安装器，使用 `--frozen-lockfile --ignore-scripts --node-linker=hoisted --package-import-method=copy`。唯一审核过的原生准备步骤仍是官方 `ensure-spawn-helper.mjs` 设置包内 helper 的执行位。`apply` 和 `run` 不安装依赖、不更新锁、不追踪 latest。

`pnpm peers check` 仍报告上游未启用的 working-activity 与实验 Web UI peer 警告。working-activity 会动态改写 Session 事件表，本配方明确禁用；TUI 使用自己的 spinner、聊天、工具卡和状态显示。实验 Agent Teams、语音等没有启用。不能把警告记为整棵依赖声明全部通过；主运行路径以公开模块身份检查和原生加载证据单独验收。

## 使用与登录

先准备仓库 `.venv`，从明确的私人机器文件启动：

```bash
./agentcfg --machine workstation --profile dsh-default sync
./agentcfg --machine workstation --profile dsh-default apply
./agentcfg --machine workstation --profile dsh-default run --cwd /path/to/project
./agentcfg --machine workstation --profile dsh-default doctor
```

本次不要将上述 apply 用于旧部署。升级门禁会拒绝旧受管 `settings.yaml` / env-guard 记录、旧 owner 和旧 pending。应在独立 HOME/XDG/实例根中用同一配方验收；旧部署继续从原工作树运行。

新实例保留当前公共国内 API 模型入口及私人机器覆盖，默认主模型沿用实际 `kimi_code_openai` 配置。`model status` 查看缺项，`model key` 只修改选定私人密钥来源。缺少一个订阅登录不会阻止其他配置好的 API 路由启动；无 key 的路由保持不可用，不自动改用其他付费来源。关闭代理的国内 API 检查只修改测试子进程环境，网络可达仍是必要条件。

Codex/ChatGPT 订阅在 DSH TUI 内使用：

```text
/auth status
/auth login openai-codex
/model
```

真实账号未验收。账户保存在隔离实例的原生认证目录，不读取全局 Codex HOME。这与 `/kernel` 的外部 Codex 内核不同：后者是上游入口，DSH Provider/审批插件不自动作用于它，本次没有维护第二套 Codex 配置。

Cursor 的终端入口：

```text
/cursor-login
/cursor-login url
/cursor-login status
/cursor-login models
/cursor-login cancel
/cursor-login logout
/model
```

`/cursor-login` 打开 TUI 原生认证面板，提供完整链接的 Copy、Open browser again 和 Cancel sign-in 操作。面板持续等待本次登录；`/cursor-login url` 重新显示同一登录，重复 start 不另建并行登录。登录有效期由上游决定，适配器另设十分钟观察上限，成功、失败、取消或退出时结束面板。SSH 的系统剪贴板/浏览器能力取决于终端环境；完整链接另存于该实例 `DSH_HOME/cursor-login-url.txt`（0600），只在登录未结束时供用户本机读取，不能发到对话或日志。已有同名文件、符号链接及用户改动不会被覆盖或删除。

插件进行远端 PKCE 轮询，不猜测 localhost 转发，也不需要常驻 Web UI。`models` 明确刷新账号目录，在短通知中只显示数量，完整列表用 `/model`；失败则返回未知/空目录，内置 fallback 不被标成可用模型。用量未查到时显示未知。status/models 的错误不会取消正在等待的登录。认证、刷新、注销由上游公开 AuthService/CredentialStore 保管，管理器不导入 IDE/浏览器/钥匙串凭据。注销会取消本适配器的未完成请求；注销未确认时请求保持暂停，status 显示 paused，显式重新登录成功才恢复。已发生的副作用无法撤销。

本地稳定 provider ID 仍为 `cursor`，原生路由从 `oauth-cursor` 改为 `cursor-subscription`。旧 `agent_options.cursor_port` 已移除；新终端认证不建立该本地代理端口。含旧字段的机器文件严格校验失败，应仅在候选配置副本移除字段，不修改旧部署来源。旧会话的 provider 不被静默重写，旧 oauth-subs 数据不复制或转换成新凭据；新实例需重新登录。未完成真实登录、账号目录、主会话请求、工具往返、续接与额度对应验证之前，不能称为“Cursor 替换已验收”。

## 设置所有权与 UI

DSH 内核、standard preset、workspace-write + ask 为默认。默认显示原生欢迎页与品牌横幅，采用 Catppuccin Mocha 配色，与 OMP 的暗色主题对齐。`agent_options.show_welcome=false` 可选择直接进入会话；通过公开 `DSH_TUI_NO_LAUNCHPAD` 控制，不修改 TUI。视觉 minimal 与工具 minimal preset 不混用；本配方没有为了界面削减文件工具、压缩或原生子代理。

实际 RC2 `/settings` 写入 `dsh-home/profiles/agentcfg/cordis.patch.yml`。`~/.dsh-tui/settings.json` 不是该版本的活动设置文件；其 npm 包 `lib/settings.json` 是字段目录。本配方保留用户已有文件，不构造不存在的双向同步。

- API providers 及 TUI 的模型/内核/preset/modes 等明确字段使用按行 id 的 `cordis-yaml` 三方比较。未知行、未知字段和未执行的标量 JS 保留；重复 id/重复键、非法结构和受管字段父节点被改成 JS 都失败。
- whale/idle/minimal、侧栏开关和面板列表只首次初始化。默认 whale=true、minimal=false 显示品牌横幅，whaleIdle=false 避免空闲动画；开发 preset 仍为 standard。收起侧栏，按需打开 todo/jobs/agents/trajectory/info。重复 apply 不恢复用户改变的这些偏好。
- 主题偏好、home/onboarding 标记也只初始化，默认 `rotom-catppuccin`，同时保留可选择的 Poimandres 资产。主题 capture 是初始化默认提案，不保证双向同步。首次已有非空且未接管的偏好文件会报告冲突，不会覆盖未知字段。已初始化实例不会因 apply 自动改主题；本次手测候选的主题和横幅按用户明确要求，在活动锁释放后逐字段修改。
- `.dsh-tui` 始终位于实例 `user-home`，HOME/DSH_HOME 身份固定。全局 AGENTS.md、完整两项框架技能、独占 overlay、主题资产和薄启动器按文件管理；账号、会话和日志由原生服务拥有。
- 薄启动器使用公开 `@deepseek-ai/dsh/profile-boot` 与 launch environment snapshot；不调用 dotenv 发现，不改 Node fs 或上游。业务 cwd 不变，cwd/.env 与 DSH_HOME/.env 不被隐式导入。
- 原生 packageManager 通过公开启动参数指向拒绝更新的受管入口；普通 TUI 自更新不受支持。独立 CLI/手工修改不能当作受管操作，doctor/run 会检查受管运行包漂移。

常用状态入口是 `/status`、`/tokens`、`/settings`、`/panel`、`/preset` 与 `/permission`。实际快捷键以该版本 `/help` 为准；tmux 的 Ctrl+B 会吃掉默认侧栏键，可在原生设置中重绑。终端图片预览默认关闭，模型自身图片输入能力保留。中文/多行粘贴、窄窗和退出的实际验收范围以记录为准；未运行 SSH/tmux 客户端交互不能据 PTY 推断通过。

原生 `/settings` 还可以选择女仆娘立绘（`whaleGirl`）、欢迎期闲置动画和开屏大字字体；字体有按天轮换及内置固定字面，以实际选择器为准。立绘是原生用户偏好，不是 Rotom 强制默认，保存在同一用户 Cordis patch 中，apply 保留。0.14.0 的伙伴皮肤会优先接管头部：默认 `companion.skin=deepy` 会盖过立绘开关。显示作者的头部女仆立绘需 `whaleGirl=true` 配合 `companion.skin=whale`；选择 `companion.skin=whaleGirl` 则是另一套动态吉祥物素材。终端支持 Kitty/Sixel 时可以显示原图，否则使用女仆字符画回退；图像协议缺失本身不会回退成鲸鱼。矮窗口会由原生布局收起立绘，扩大终端后再查看。当前手测实例已完成此组合配置及真实欢迎页/会话头部字符画验证，主题保持 Catppuccin。

原生主题切换使用 `/theme` 实时预览，或 `/theme dark`、`/theme rotom-catppuccin`。作者的主题文档介绍 Gentle Mist Blue 色系，深色终端对应 `dark`，没有明确指定“最好看”的主题；Catppuccin 是 Rotom 通过公开 JSON 主题格式配置的色板，不是 0.14.0 内置主题。

Catppuccin 色表来自官方 [Neovim Mocha](https://github.com/catppuccin/nvim/blob/edefef779ab08ce1a4a404713e3012b0d202bd35/lua/catppuccin/palettes/mocha.lua)，本配方覆写 TUI 0.14.0 全部 81 个 Theme 字段，保留空 cursor 的原生反显语义。强调色 peach、边框 blue/lavender、关键字 mauve、函数 blue、字符串 green、数值 peach、运算符 sky、标点 overlay2，与本仓库 OMP Catppuccin 对齐。注释 overlay0、变量 text 沿用 OMP 的选择；它们不等同于 Neovim `syntax.lua` 的传统 Comment/Identifier 映射，也不是唯一的官方映射。

TUI 的 `background` 表示徽标填充，配置为 blue，与 inverseText 的 base 保持对比；它不是终端整体背景。`inputBackground` 为 Mocha base，主题不修改系统终端背景/壁纸。Diff 行背景按官方 [Neovim DiffAdd/DiffDelete](https://github.com/catppuccin/nvim/blob/edefef779ab08ce1a4a404713e3012b0d202bd35/lua/catppuccin/groups/syntax.lua) 的 green/red 与 base 18% 混色，得到 `#364143` / `#443244`；dimmed 用 9% 是本适配的选择，变更字色保持纯 green/red。不能把 OMP 的 diff 文字色直接移作 TUI 的行背景。女仆原图和上游固定的品牌渐变保留作者配色，不能称所有像素都由主题覆写。

公共默认模型来源与私人密钥文件是两层配置：DSH 继承 `shared/defaults/models.toml` 的模型入口及 main 角色；同一个 `secret:` 引用可供多个 Agent 共用，但它们必须引用同一私人 `secrets_file`。本次候选显式使用 `/home/private-user/rotom-dsh-candidate-20261012/secrets.toml`，没有自动连接原机器密钥文件。截至本次脱敏 `model status`，main 为 Kimi Code 的 `kimi-for-coding`，Kimi/GLM/DeepSeek key 均未填写。要复用现有共享密钥，应由用户指定该文件的绝对路径后连接引用，不能扫描真实 HOME 或自动复制凭据。

正式普通部署省略 `secrets_file` 时沿用 `XDG_CONFIG_HOME/agentcfg/secrets.toml`，没有设置 XDG_CONFIG_HOME 时为 `~/.config/agentcfg/secrets.toml`；共享文件在管理器解析配置时读取，再通过已选引用注入实例环境，不因子进程 HOME 隔离而改变来源。DSH 和 OMP 标准 Kimi/GLM Provider 分别走 OpenAI/Anthropic 协议，但共用 `kimi_code_key` / `glm_coding_key`。OMP 的 TokensFlow `kimi_tf` 等扩展 Provider 使用独立引用，不能因为同叫 Kimi 就自动改用其 key。共享读取、跨 profile/协议、写入分组与不泄漏渲染的现有离线测试已复核通过。

### 日常 UI、状态栏与图标

当前候选没有单独覆写 statusBar，采用 0.14.0 的 compact 默认：开启 model、thinking、cwd、contextUsage、cache、cost、goal、contextBar；关闭 tokens、tps、gitBranch、sessionTitle、sessionId、mode、activity、trajectory、shortcutHint。开启代表允许展示，缺少数据仍会隐藏。`thinking` 字段用于推理档位；消息内的 Thinking 计时是另一个运行阶段显示。

截图里的 `glm-5.2-high` 是当前模型标签；来源可在模型 hover 详情或 `/model` 查询。`6.0k/200k 3.0%` 是上下文占用/窗口，`cache 0.0%` 是最后一份 usage 的缓存读取占输入比例，不是 Cursor 余额。compact 栏里的 `workspace` 是当前目录 basename；它不证明 workspace-write 或 ask 已生效，实际模式用 `/permission` 查询。原生费用项仅在后端报告费用或支持官方 DeepSeek 估价时出现；当前 Cursor 不报告费用时不补一个 0。tokens 的详情可显示已完成轮次的重试数，但它默认关闭。

可配置类别包括主题/极简界面、欢迎图形与大字、伙伴皮肤、侧栏及面板、状态栏字段与紧凑布局、工具卡/滚动展示、图片预览、按键等。通过 `/settings` 修改原生用户偏好，`/theme` 选主题，`/panel` 打开面板。TUI 的大字字体不是系统字体选择器。0.14.0 没有 Nerd Font 图标主题开关；可在客户端采用 Nerd Font 绘制普通 Unicode，但不会自动变成 OMP 的 Nerd 图标集。SSH 字体由本地终端决定。

以下对照以候选 DSH 和仓库公共 OMP/Pi 配方为准，未检查 OMP/Pi 的用户运行态：

| 项目 | DSH 候选 | OMP kernel 公共配方 | Pi default 公共配方 |
| --- | --- | --- | --- |
| 外观 | Catppuccin Mocha、原生欢迎页/女仆、idle 关闭 | 原工作树深浅 Catppuccin | Everforest Dark、quiet startup |
| 状态栏配置 | 原生逐项开关、compact，布局由 TUI 决定 | custom 左右段及顺序、powerline-thin 分隔 | colorful-footer 的颜色/图标/分隔/最大行数及宽度分档 |
| 主要信息 | 模型/推理档位/目录/上下文/cache，费用及 goal 按数据出现 | 左 vim/model/context_pct/token_rate/time_spent；右 session_name/path/git/mode/token_total/cache_hit | 按宽度显示 provider/model、thinking、上下文、速度、分支、时长、费用、cache 等 |
| 图标 | 普通 Unicode，未提供 Nerd 图标主题 | symbolPreset=nerd | footer 提供 Nerd glyph 检测/配置及普通 Unicode 回退 |
| 辅助视图 | 侧栏收起，todo/jobs/agents/trajectory/info | 原生任务/Agent 能力，未使用 DSH 同一套侧栏 | pi-todo/subagents；不把其他 profile 的 Task Keeper 算进 default |
| 偏好所有权 | UI 偏好/主题初始化，日后 apply 保留；后端/preset/主模型持续管理 | 状态栏等字段三方合并，漂移保留或冲突 | 原生 settings 字段三方合并，footer 读取受管 manifest 的 ui.footer |

`/model` 切换当前会话的模型，不改 Rotom 的全局 main 角色。新会话沿用配方明确指定的 provider/model；恢复已有会话用 `/resume` 打开原生列表并按 Enter，路由从该会话记录恢复。主题、欢迎页和认证面板均使用上游公开入口，Rotom 不维护另一套菜单或会话管理界面。

## 重试与权限

Cursor 的内部 POST retry 为 0，Provider-owned recovery 也为 0，总尝试一次；不重发无法确认服务端是否已处理的请求。静态 API 默认 normal/0，显式上限为 2；拒绝 always。Codex OAuth 使用上游唯一 `dsh-llm-retry` 的有限默认 5 次重试，最多 6 次尝试，取消和 backoff 由原生实现处理；TUI 没有公开 OAuth retry 字段，不伪造覆盖。真实请求故障/Retry-After 的账号侧证据未完成；不靠重做已成功工具恢复模型流。

目前 AI 审批未交付，没有可用的自动模式开关。使用 `/permission` 查看本会话有效模式，`/permission workspace-write` 回到原生 workspace-write + ask。`never` 会拒绝需要审批的请求，并非总是允许；批准只针对当前请求，不形成 bash/python/make 等通用白名单。

有限版本核验未找到满足 RC2/Cordis 4.0.4/Schemastery 3.18.4 全部 peer 的 auto-review：0.12.10 的 DSH peer 排除 RC2，0.12.11 起要求 alpha Cordis/Schemastery。PerryLink auto-review `0.12.17` 的候选源码依赖 alpha Cordis/Schemastery；reviewer start 没有独立 cwd/read-roots 设置，只读工具名单不限制读取目录，默认审计在预发布宿主降级内存。没有组合、真实 reviewer、目录边界与持久审计证据，不能启用或称“自动审批安全可用”。没有启用官方实验性 Full-access Auto review、YOLO 或新的审批框架，也没有加入第二个规则层。

| 通道 | 实际边界 |
| --- | --- |
| 文件工具 | 原生 ToolRuntime 与文件策略；正常工作区操作不额外调用 reviewer，仅 ask 才进审批 |
| Shell | 原生工具链及 OS confinement；外部写入和符号链接哨兵以实际内核 runner 测试验证 |
| MCP | 注册工具走 ToolRuntime；远端服务的副作用不由本地文件沙箱隔离，连接/人工交互未验收 |
| 原生子代理 | 原生 toolFilter、继承规则；父级批准不等于子级每个动作已审核，独立 read-roots 未建立 |
| 外部 Agent 内核 | 自己的原生权限/认证；DSH 插件覆盖未宣称 |
| PTC/run_code | 原生工具与 runtime 公开链；未运行相关原生通道则标 NOT RUN |
| 插件/直接 Node | 同宿主进程权限，不能称所有副作用已进入审批或 OS confinement |

workspace-write 管的是文件写入，并非通用凭据、网络、环境变量或同用户进程隔离。模型 API key 只按已选择引用注入；工具进程可能接触注入环境，插件自身是可信宿主代码。AI reviewer 不是同用户恶意进程安全边界。没有可用沙箱时，原生 confined 操作必须拒绝，不能偷偷降级 Full access；只显示配置模式不等于已验证后端。

## OpenSpec、迁移与恢复

DSH 不安装 OpenSpec，不自动部署 Spec 工作流/技能，也不使用 Spec Kit 替代。`project init openspec` 因 Pi 的独立可选能力保留，DSH 调用失败闭合。Rotom 和业务项目的 `openspec/`、`.specify/`、`specs/`、AGENTS.md 与用户技能原样保留；有漂移的受管产物不被覆盖或删除。

`rollback` 只还原受管配置。锁/软件再部署、原生会话格式和账号数据是不同恢复边界；没有将新版本写过的会话交给旧版本测试。当前恢复方式是保留原工作树/旧运行包和旧 HOME，在新隔离目录验收候选；不要自动降级或跨 HOME 复制真实会话。

显式原生验收入口：

```bash
.venv/bin/python scripts/smoke-dsh.py --allow-host \
  --runtime /absolute/path/to/current-sealed-runtime \
  --evidence /absolute/path/to/new-evidence-directory
```

中文多行/窄窗/原生文件工具/退出的独立入口为 `scripts/smoke-dsh-ui.py --allow-host --runtime ... --evidence ...`（仅本地假模型）。两个新 HOME 的重建入口为 `scripts/smoke-dsh-rebuild.py --allow-install --cache /absolute/task-cache --evidence ...`；记录显式共享下载缓存，不称 cold build。两个脚本均用本任务私人 `/dev/shm` HOME，当前仅在 Linux 运行。

Cursor 原生认证面板的独立入口为 `scripts/smoke-dsh-auth-panel.py --allow-host --runtime ... --evidence ...`，使用真实 TUI/QuestionBridge、假 Coordinator 和明确标记的假长链接，验证面板交互，不访问真实认证。`scripts/check-dsh-cursor-panel.mjs /absolute/runtime` 另测并发、重新显示、错误隔离、注销失败和文件漂移。复制动作的完整参数可验证，真实 SSH 剪贴板和浏览器仍需客户端手测。

默认 pytest 仍隔离 HOME/DSH/XDG、阻断网络和真实子进程。native 脚本使用虚构状态、真实原包和任务临时哨兵，不是账号模型验收；其确定性答复者也不冒称 Perry reviewer 或真人点击。凭据授权、真实账号、完整 AI 审批与会话降级仍是单独阻塞项。
