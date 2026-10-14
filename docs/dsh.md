# DSH 配方与本机部署

维护一套 `dsh-default`。本机日常部署由 main 的 agentcfg 管理，绑定长期 `workstation` 配置和标准实例路径，复用其原共享密钥来源。日常使用原生 workspace-write + ask，并默认接入 Perry auto-review。2026-10-14 用户明确接受已知上游生命周期/审计缺口后，按这个范围发布到同一个正式实例；完整安全验收仍有 FAIL，不把正式部署称为上游稳定版或全部门槛通过。完整结果见 [升级验收记录](acceptance/dsh-upgrade-20261012.md)。

2026-10-14 按用户明确授权清除两套候选测试账号、会话、实验运行包和快照，移除独立 `dsh-auto-review` 启动入口。正式实例使用全新原生 HOME，Cursor 需重新登录；原候选 API key 文件仅移动至私人备份，未读取或复制内容。更早的 workstation DSH 含历史补丁及未知账号资料，整体保留到私人恢复目录，未将旧会话导入新版本。Cursor 先前的用户文本/文件工具反馈保留其历史范围；本轮真实模型调用 0，Codex/国内 API 完整账号测试仍按用户要求跳过。DSH Core 仍为预发布 RC，正式部署不表示上游稳定版或自动审批验收通过。

## 版本、原包与锁

| 组件 | 当前日常配方 | 来源与边界 |
| --- | --- | --- |
| DSH Core | `0.2.0-rc.2` | `639ed015397290b3745d163aafe02ffee4aa3f84`；预发布版 |
| TUI | `0.14.0` | `c2eee95218d1decfce138f7d31ef7099cc391d00`；未改动 npm 原包 |
| Cursor Provider | `dsh-cursor-subscription@0.6.12` | `936fb5b40b8efb50a5bb2031c81f3c8f553bf7f8`；未改动原包，通过薄终端适配调用公开 API |
| 薄终端适配 | `rotom-dsh-cursor-terminal@0.1.1` | 本仓库 `agents/dsh/packages/cursor-terminal`；使用 TUI 公开 QuestionBridge，不复制 OAuth 或 Cursor wire 协议 |
| 认证 | TUI 的 `./oauth` | 仅挂载 `openai-codex`；不使用旧独立 dsh-auth 包或 OpenAI API key 替代订阅 |
| AI 审批 | `dsh-auto-review@0.12.17` | Perry 原始 npm 包，SHA `2b931b8375f9ee9ebe20e80ef336c69804e1aac0`，已进入正式锁 |
| 审查上下文 | `rotom-dsh-review-context@0.1.0` | 本仓库常量工具，不读取文件、环境、账号，不提供用户授权 |
| 公共运行时 | Cordis `4.0.5-alpha.1` / Schemastery `3.18.5-alpha.1` | 为满足 Perry peer 下界采用预发布版本；主审批/会话/子代理实际模块身份相同 |
| 工具链 | Node `24.14.0` / npm `11.19.1` / pnpm `11.19.0` | pnpm 原包固定 integrity 并随锁提供；不全局安装 |

`locks/dsh/pnpm-lock.yaml` 是唯一完整安装锁；manifest v2 明确 `resolution_kind=pnpm`。TUI 可选 Schema peer 的稳定版范围与 Perry alpha 下界使正常 npm 解析 ERESOLVE，未用 force、legacy-peer-deps、overrides 或删除 peer 绕过。当前配方不提供 npm ci，旧双锁仍可从历史 Git 追溯。Node/npm 工具链记录保留，实际解析和安装都使用锁定原始 pnpm。声明冲突仍存在，不把正常 pnpm 安装等同整棵 peer 通过。

普通 `sync` 从原始 pnpm 归档验证 SHA-512、解压固定安装器，使用 `--frozen-lockfile --ignore-scripts --node-linker=hoisted --package-import-method=copy`。唯一审核过的原生准备步骤仍是官方 `ensure-spawn-helper.mjs` 设置包内 helper 的执行位。`apply` 和 `run` 不安装依赖、不更新锁、不追踪 latest。

`pnpm peers check` 仍报告上游未启用的 working-activity 与实验 Web UI peer 警告。working-activity 会动态改写 Session 事件表，本配方明确禁用；TUI 使用自己的 spinner、聊天、工具卡和状态显示。实验 Agent Teams、语音等没有启用。不能把警告记为整棵依赖声明全部通过；主运行路径以公开模块身份检查和原生加载证据单独验收。

## 使用与登录

本机个人 PATH 的三个入口指向 `~/.local/share/agentcfg/launchers/`，管理器使用 main 源码及 `~/.config/agentcfg/machines/workstation.toml`，显式选择 `dsh-default`，不改变机器默认的 `omp-kernel`。实例为 `~/.local/share/agentcfg/instances/dsh/dsh-default`，状态为 `~/.local/state/agentcfg/dsh/dsh-default`：

```bash
cd /path/to/project
dsh                         # 默认使用当前目录；--cwd 也可显式指定
dsh-config doctor           # 离线检查当前日常实例
dsh-config plan
dsh-config model status
dsh-config model key kimi_tf    # 按需隐藏输入；更新与 OMP 共用的 TF key
dsh-cursor-login-url        # 用户本人在终端取完整登录链接；代理不执行
```

`dsh-config` 是薄 Shell 入口，固定正式 local/profile、使用现有 Node 24 工具链，再 exec 仓库 `agentcfg`；`dsh` 继续 exec 其 `run`。HOME/DSH_HOME/XDG 隔离由适配器负责，没有第二套管理器或日常/审批 profile。机器配置只补充 `overrides.profiles.dsh-default` 的 TF 选择，其他 Agent 配置及密钥文件不变。以下命令与个人入口管理同一正式实例：

```bash
./agentcfg --machine workstation --profile dsh-default sync
./agentcfg --machine workstation --profile dsh-default apply
./agentcfg --machine workstation --profile dsh-default run --cwd /path/to/project
./agentcfg --machine workstation --profile dsh-default doctor
```

本机另外提供个人辅助入口 `dsh-proxy`，固定为本次启动设置 `HTTP_PROXY=http://127.0.0.1:10808`、`HTTPS_PROXY=http://127.0.0.1:10808`、`NO_PROXY=localhost,127.0.0.1,::1` 和 `NODE_USE_ENV_PROXY=1`，再 exec 原来的 `dsh` 并透传参数：

```bash
cd /path/to/project
dsh-proxy
# 或显式指定工作目录
dsh-proxy --cwd /path/to/project
```

正式 workstation 的 `[machine.environment].inherit` 已加入这四个变量并完成 apply；配置源只记录变量名，代理地址由辅助脚本设置。普通 `dsh` 不主动设置代理；若调用环境已设置这些变量，则会按白名单继承。`dsh-proxy` 不新建 profile/HOME，不切换模型或权限，不修改系统代理。脚本位于 `~/.local/share/agentcfg/launchers/dsh-proxy`，PATH链接为 `~/.local/bin/dsh-proxy`；同原个人启动器一样，是本机辅助文件，并非新的上游命令。

10808需要支持HTTP或mixed代理，`127.0.0.1`指运行DSH的机器。Node24.14.0的原生HTTP(S)/fetch支持环境代理，但Cursor0.6.12的AgentRun主模型流直接使用HTTP/2，没有公开代理接口；不能将此入口宣称为Cursor流量全部经过10808。该限制与无账号检查见[代理入口验收](acceptance/dsh-upgrade-20261012.md#2026-10-14-本机代理快捷入口)。

本机已在保持原状态锁 inode 的条件下将历史实例及旧状态项移入恢复目录，再通过同一 plan/transact 契约建立新部署。没有清除 legacy 门禁：其他机器仍有旧受管 `settings.yaml` / env-guard、旧 owner 或 pending 时，直接 apply 会拒绝。应先在独立 HOME/XDG/实例根验收，不能清 owner 后强行认领旧数据。

新实例保留当前公共国内 API 模型入口及私人机器覆盖，默认主模型沿用实际 `kimi_code_openai` 配置。`model status` 查看缺项，`model key` 只修改选定私人密钥来源。缺少一个订阅登录不会阻止其他配置好的 API 路由启动；无 key 的路由保持不可用，不自动改用其他付费来源。关闭代理的国内 API 检查只修改测试子进程环境，网络可达仍是必要条件。

TF 目录在 `agents/dsh/content.toml` 中提供 11 个 `dsh-…` 模型绑定，覆盖与 `omp-kernel` 相同的四个 Kimi、五个 GLM 和两个 DeepSeek 型号。provider 复用已有 `kimi_tf`、`zhipu_tf`、`deepseek_tf` 定义，凭据引用仍分别为 `secret:omp_kimi_tf_key`、`secret:omp_zhipu_tf_key`、`secret:omp_deepseek_tf_key`，不复制密钥。Kimi/DeepSeek 使用 OpenAI Completions，GLM 使用原生 Anthropic Messages；当前锁定的 `llm-pi-ai` 已支持这三个协议，没有添加运行依赖。

TF 需要机器自己的 `tf_openai_url` 和 `tf_anthropic_url`，因此通过 `overrides.profiles.dsh-default` 选择，见 [私人配置示例](../examples/dsh-tf.local.toml)，没有强迫缺少网关地址的其他机器启用。默认主模型保持原值。模型名称、输入能力和客户端预算复用公共模板；DSH 的 reasoning/compat 使用公开字段，OMP 的 native 字段不会透传。网关实际模型可用性、额度和工具往返仍需用户验证；原生宿主与本机模拟服务通过不代表 TF 账号测试通过。

正式 workstation 已选择这 11 项 TF 绑定及三项 provider，保留已有 TF 地址和 main 角色。原 machine 未设置 `secrets_file`，仍使用其默认共享文件；这里已复用同一来源，不再引用候选 key 文件。密钥内容、账号额度和实际网关模型可用性均 NOT INSPECTED。原候选 key 文件仅按 inode 移至 `~/.config/agentcfg/retired-credentials/dsh-candidate-20261012.toml`（0600），不作为运行来源。需要 TF 时在 `/model` 选择对应 `agentcfg-kimi_tf`、`agentcfg-zhipu_tf` 或 `agentcfg-deepseek_tf`；未自动把原 main 切换到 TF。

Codex/ChatGPT 订阅在 DSH TUI 内使用：

```text
/auth status
/auth login openai-codex
/model
```

这里的 provider ID 是 `openai-codex`；`openai` 没有被本配方挂载。`/provider` 是交互式 provider 管理向导，选择 OAuth 后复用 `/auth` 的同一认证服务，并非第二套账号。SSH 下优先在原生登录方法提问中选择 `Device code login (headless)`；它不依赖远端 localhost 回调。浏览器模式则在原生面板粘贴授权码或完整回跳地址，回调/等待由上游流程负责，不添加自造超时或复制 OAuth 实现。

设备码登录的账号侧前提是先在ChatGPT安全设置或工作区管理员权限中启用device code login，见[OpenAI官方认证文档](https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta)。它不能修复网络连接错误。当前pi-ai0.87.1先显示登录方式提问，用户选择设备码后才申请并轮询；申请或轮询的fetch异常会结束本次登录。失败后重新执行`/auth login openai-codex`会开始新的流程；有设备码面板时先选`Cancel sign-in`，卡住时退出TUI并用`dsh-proxy`重启，再打开登录方式窗口。此操作不需要删除认证目录或配置回滚。

`/auth`的登录成功和状态结果是默认约4秒的原生通知，不写入聊天记录，也没有通知历史入口。错过提示时重新执行`/auth status`读取当前状态；需要保持显示，可输入`/provider`，依次进入Add、OAuth，在供应商列表中用方向键查看登录/到期描述，按Esc退出，不触发新登录或注销。0.14.0没有公开的全局通知时长设置。`/provider`成功登录另写当前会话的本地摘要，但不保证跨进程保留。

2026-10-14原生TUI+本地TLS假OAuth测试已验证发码失败、同会话重开、轮询失败、再次重开及取消停止轮询；初次和失败后选择页各等待5秒，回答前OAuth请求0。同10808代理下匿名Node fetch访问认证站点曾报ECONNRESET，而curl/Node https收到403、Node fetch访问example.com收到200，外部具体原因未确认，不从匿名HEAD推定实际发码请求同因。用户曾反馈“选择窗口出现前直接fetch failed”；退出失败TUI并用dsh-proxy重启后，用户确认登录方式窗口恢复，设备码显示并保持等待，浏览器授权后`/auth status`报告`openai-codex signed in`及到期时间。这个实际恢复无需重部署或删除认证目录；认证成功是用户实际反馈，原失败根因未确认，真实模型调用和重启后的凭据恢复仍未测试。完成提示消失时可重新执行`/auth status`查看当前登录状态。证据和明确未完成项见[认证故障验收](acceptance/dsh-upgrade-20261012.md#2026-10-14-codex设备码故障与键盘查看复核)。

2026-10-14 真实 `/auth login openai-codex` 浏览器模式在全新无账号 HOME 中能显示登录方法/授权码面板，空闲五秒后取消，退出和 termios 恢复通过。URL 只在内存验证，未写账号凭据；这不能证明已完成真实账号登录，也没有复现用户原会话“迅速退出”的症状。模拟 device-code 面板通过，不替代实际联网设备码发行/登录证据。真实浏览器入口另有一次原生 npm 版本 GET，单列为背景请求，无 OAuth 远端/真实模型调用或依赖安装。

Codex设备码登录已由用户实际反馈确认，真实模型路由/工具请求、重启后恢复和刷新未验收。账户保存在隔离实例的原生认证目录，不读取全局 Codex HOME。这与 `/kernel` 的外部 Codex 内核不同：后者是上游入口，DSH Provider/审批插件不自动作用于它，本次没有维护第二套 Codex 配置。

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

- API providers、Core `agent-default-model` 的默认路由及 TUI 的内核/preset/modes 等明确字段使用按行 id 的 `cordis-yaml` 三方比较。TUI 不再固定 provider/model，避免覆盖恢复会话的记录。未知行、未知字段和未执行的标量 JS 保留；重复 id/重复键、非法结构和受管字段父节点被改成 JS 都失败。
- whale/idle/minimal、侧栏开关和面板列表只首次初始化。默认 whale=true、whaleGirl=false、companion.skin=whale，显示鲸鱼；minimal=false 显示品牌横幅，whaleIdle=false 避免空闲动画。鲸鱼选择已进入正式配置来源，重建不依赖手改生成文件；开发 preset 仍为 standard。收起侧栏，按需打开 todo/jobs/agents/trajectory/info。重复 apply 不恢复用户改变的这些偏好。
- `brand=deepseek` 也只初始化，用于保持鲸鱼品牌并避免切到 Claude/Codex 内核时自动更换用户保存的主题。TUI 0.14 的 `brand=auto` 可以覆盖 `theme.json` 的持久选择；本会话 `/theme` 手选或显式环境主题才锁住主题。用户仍可在 `/settings` 改 brand，也可在 `/theme` 改主题，不用环境变量强制覆盖偏好。
- 主题偏好、home/onboarding 标记也只初始化，默认 `rotom-catppuccin`，同时保留可选择的 Poimandres 资产。主题 capture 是初始化默认提案，不保证双向同步。首次已有非空且未接管的偏好文件会报告冲突，不会覆盖未知字段。已初始化实例不会因 apply 自动改主题；本次手测候选的主题和横幅按用户明确要求，在活动锁释放后逐字段修改。
- `.dsh-tui` 始终位于实例 `user-home`，HOME/DSH_HOME 身份固定。全局 AGENTS.md、完整两项框架技能、独占 overlay、主题资产和薄启动器按文件管理；账号、会话和日志由原生服务拥有。
- 薄启动器使用公开 `@deepseek-ai/dsh/profile-boot` 与 launch environment snapshot；不调用 dotenv 发现，不改 Node fs 或上游。业务 cwd 不变，cwd/.env 与 DSH_HOME/.env 不被隐式导入。
- 原生 packageManager 通过公开启动参数指向拒绝更新的受管入口；普通 TUI 自更新不受支持。独立 CLI/手工修改不能当作受管操作，doctor/run 会检查受管运行包漂移。

常用状态入口是 `/status`、`/tokens`、`/settings`、`/panel`、`/preset` 与 `/permission`。实际快捷键以该版本 `/help` 为准；tmux 的 Ctrl+B 会吃掉默认侧栏键，可在原生设置中重绑。本配方的 `terminalImages` 默认关闭（TUI 原生默认开启），它控制主渲染器的图像协议探测，同时影响图片预览和头部立绘原图；模型自身图片输入能力保留。在 `/settings` 的「终端图片预览」调整后，用 `/restart` 生效。中文/多行粘贴、窄窗和退出的实际验收范围以记录为准；未运行 SSH/tmux 客户端交互不能据 PTY 推断通过。

原生 `/settings` 还可以选择女仆娘立绘（`whaleGirl`）、欢迎期闲置动画和开屏大字字体；字体有按天轮换及内置固定字面，以实际选择器为准。立绘是原生用户偏好，不是 Rotom 强制默认，保存在同一用户 Cordis patch 中，apply 保留。0.14.0 的伙伴皮肤会优先接管头部：默认 `companion.skin=deepy` 会盖过立绘开关。显示作者的头部女仆立绘需 `whaleGirl=true` 配合 `companion.skin=whale`；选择 `companion.skin=whaleGirl` 则是另一套动态吉祥物素材。原图还需开启 `terminalImages`、重启后成功探测到 Kitty/Sixel，并成功解码资产。0.14.0 在 tmux/screen 中直接禁用图像探测，即使外层终端支持图像协议也使用字符画。回退是作者自带的 30×30 真彩色精灵，用半块字符显示为30列×15行；复制为纯文本会丢失颜色，只剩轮廓。图像协议缺失本身不会回退成鲸鱼。矮窗口会由原生布局收起立绘，扩大终端后再查看。女仆组合曾完成真实欢迎页/会话头部字符画验证，原图协议未验收；正式默认延续用户的 Ghostty+tmux 使用偏好，选择像素鲸鱼（whaleGirl=false、whale=true、companion.skin=whale），主题与推荐状态栏保留。

原生主题切换使用 `/theme` 实时预览，或 `/theme dark`、`/theme rotom-catppuccin`。作者的主题文档介绍 Gentle Mist Blue 色系，深色终端对应 `dark`，没有明确指定“最好看”的主题；Catppuccin 是 Rotom 通过公开 JSON 主题格式配置的色板，不是 0.14.0 内置主题。

0.14.0 的立绘仅支持内置素材选择：`whaleGirl` 是头部女仆开关，`companion.skin` 可选 deepy/whale/whaleGirl；静态头图与伙伴动画是不同素材。没有公开配置可导入任意图片或自定义皮肤目录。内部皮肤注册函数未通过包 exports 开放，不能当作已交付的扩展 API；不替换安装包 assets。[Ghostty 支持 Kitty 图像协议](https://ghostty.org/docs/features)，但该 TUI 的 tmux 分支仍直接禁用探测。查看原图可先退出当前 TUI，在不进入 tmux 的 Ghostty 标签页运行同一入口，开启「终端图片预览」并 `/restart`；仅增加 tmux passthrough 设置不会改变上游的禁用分支。

Catppuccin 色表来自官方 [Neovim Mocha](https://github.com/catppuccin/nvim/blob/edefef779ab08ce1a4a404713e3012b0d202bd35/lua/catppuccin/palettes/mocha.lua)，本配方覆写 TUI 0.14.0 全部 81 个 Theme 字段，保留空 cursor 的原生反显语义。强调色 peach、边框 blue/lavender、关键字 mauve、函数 blue、字符串 green、数值 peach、运算符 sky、标点 overlay2，与本仓库 OMP Catppuccin 对齐。注释 overlay0、变量 text 沿用 OMP 的选择；它们不等同于 Neovim `syntax.lua` 的传统 Comment/Identifier 映射，也不是唯一的官方映射。

TUI 的 `background` 表示徽标填充，配置为 blue，与 inverseText 的 base 保持对比；它不是终端整体背景。`inputBackground` 为 Mocha base，主题不修改系统终端背景/壁纸。Diff 行背景按官方 [Neovim DiffAdd/DiffDelete](https://github.com/catppuccin/nvim/blob/edefef779ab08ce1a4a404713e3012b0d202bd35/lua/catppuccin/groups/syntax.lua) 的 green/red 与 base 18% 混色，得到 `#364143` / `#443244`；dimmed 用 9% 是本适配的选择，变更字色保持纯 green/red。不能把 OMP 的 diff 文字色直接移作 TUI 的行背景。女仆原图和上游固定的品牌渐变保留作者配色，不能称所有像素都由主题覆写。

公共默认模型来源与私人密钥文件是两层配置：DSH 继承 `shared/defaults/models.toml` 的模型入口及 main 角色；同一个 `secret:` 引用供多个 Agent 共用时，需使用同一私人来源。正式 workstation 保留原共享来源，main 仍为 Kimi Code 的 `kimi-for-coding`。本轮空 `SecretStore` 验证产生的“key 未填写”提示仅描述测试上下文，不能解释为用户共享文件缺 key；代理没有读取该文件。用户自行运行 `dsh-config model status` 可查看缺项。

正式普通部署省略 `secrets_file` 时沿用 `XDG_CONFIG_HOME/agentcfg/secrets.toml`，没有设置 XDG_CONFIG_HOME 时为 `~/.config/agentcfg/secrets.toml`；共享文件在管理器解析配置时读取，再通过已选引用注入实例环境，不因子进程 HOME 隔离而改变来源。DSH 和 OMP 标准 Kimi/GLM Provider 分别走 OpenAI/Anthropic 协议，但共用 `kimi_code_key` / `glm_coding_key`。OMP 的 TokensFlow `kimi_tf` 等扩展 Provider 使用独立引用，不能因为同叫 Kimi 就自动改用其 key。共享读取、跨 profile/协议、写入分组与不泄漏渲染的现有离线测试已复核通过。

### 日常 UI、状态栏与图标

正式实例已按用户确认的方案配置原生 statusBar：保留 compact，开启 model、thinking、cwd、contextUsage、cache、tokens、cost、tps、gitBranch、sessionTitle、goal、mode、contextBar；关闭 sessionId、activity、trajectory、shortcutHint。相对 0.14.0 默认新增 tokens、tps、gitBranch、sessionTitle、mode 五项。开启代表允许展示，缺少数据仍会隐藏。`thinking` 字段用于推理档位；消息内的 Thinking 计时是另一个运行阶段显示。

截图里的 `glm-5.2-high` 是当前模型标签；来源可在模型 hover 详情或 `/model` 查询。`6.0k/200k 3.0%` 是上下文占用/窗口，`cache 0.0%` 是最后一份 usage 的缓存读取占输入比例，不是 Cursor 余额。compact 栏里的 `workspace` 是当前目录 basename；它不证明 workspace-write 或 ask 已生效，实际模式用 `/permission` 查询。原生费用项仅在后端报告费用或支持官方 DeepSeek 估价时出现；当前 Cursor 不报告费用时不补一个 0。tokens 已开启，其详情可显示已完成轮次的重试数。

推理档位还要求当前会话有明确的effort值；未指定时即使`statusBar.thinking=true`也留空，不能由此判断推理已关闭。`/effort status`将当前档位或`—`写入会话的本地输出，便于回看；`/effort`打开当前路由支持的档位选择，`/effort medium`可直接设置有效档位。原生设置立即作用于当前路由，并保存到隔离HOME的`.dsh-tui/effort.json`作为本实例后续会话默认偏好；它不是仅当前模型的独立偏好，其他路由会按支持档位回退，不应向所有provider硬写medium。若status已有档位但底栏仍缺失，在`/settings`检查状态栏的Thinking开关；apply保留用户现有UI偏好。`/thinking`只控制推理文本展示，不调整effort。锁定pi-ai目录的`openai-codex/gpt-6-sol`标注支持推理，TUI提供low/medium/high/xhigh/max，但这不是远端所有档位均已实测的证据。

无鼠标查看当前供应商：输入裸`/model`并按Enter打开选择器，看`✓`标记的当前provider/model；`❯`仅是键盘焦点。有最近模型时行前显示provider，分组视图中当前provider组也有选中标记；看完按Esc退出。带`provider/model`参数的`/model`会切换路由。0.14.0的statusBar schema没有provider字段，公开贡献协议也没有状态栏片段接口；不添加无效字段或改写模型ID。`/status`只报模型，不报provider。

可配置类别包括主题/极简界面、欢迎图形与大字、伙伴皮肤、侧栏及面板、状态栏字段与紧凑布局、工具卡/滚动展示、图片预览、按键等。通过 `/settings` 修改原生用户偏好，`/theme` 选主题，`/panel` 打开面板。TUI 的大字字体不是系统字体选择器。0.14.0 没有 Nerd Font 图标主题开关；可在客户端采用 Nerd Font 绘制普通 Unicode，但不会自动变成 OMP 的 Nerd 图标集。SSH 字体由本地终端决定。

以下对照以候选 DSH 和仓库公共 OMP/Pi 配方为准，未检查 OMP/Pi 的用户运行态：

| 项目 | DSH 候选 | OMP kernel 公共配方 | Pi default 公共配方 |
| --- | --- | --- | --- |
| 外观 | Catppuccin Mocha、原生欢迎页/女仆、idle 关闭 | 原工作树深浅 Catppuccin | Everforest Dark、quiet startup |
| 状态栏配置 | 原生逐项开关、compact，布局由 TUI 决定 | custom 左右段及顺序、powerline-thin 分隔 | colorful-footer 的颜色/图标/分隔/最大行数及宽度分档 |
| 主要信息 | 模型/推理档位/目录/上下文/cache/tokens/tps，分支、标题、模式、费用及 goal 按数据出现 | 左 vim/model/context_pct/token_rate/time_spent；右 session_name/path/git/mode/token_total/cache_hit | 按宽度显示 provider/model、thinking、上下文、速度、分支、时长、费用、cache 等 |
| 图标 | 普通 Unicode，未提供 Nerd 图标主题 | symbolPreset=nerd | footer 提供 Nerd glyph 检测/配置及普通 Unicode 回退 |
| 辅助视图 | 侧栏收起，todo/jobs/agents/trajectory/info | 原生任务/Agent 能力，未使用 DSH 同一套侧栏 | pi-todo/subagents；不把其他 profile 的 Task Keeper 算进 default |
| 偏好所有权 | UI 偏好/主题初始化，日后 apply 保留；后端/preset/Core 默认路由持续管理，原生模型偏好和会话路由保留 | 状态栏等字段三方合并，漂移保留或冲突 | 原生 settings 字段三方合并，footer 读取受管 manifest 的 ui.footer |

### tmux中的输出历史

全屏TUI使用alternate screen并自己管理transcript视口，tmux复制模式看到的是终端画面缓冲，不等同于会话历史。退出tmux复制模式回到DSH后，PgUp/PgDn按一页滚动输出，End回到底部；默认Ctrl+E展开或折叠隐藏的旧消息，只作用于当前已加载内容。`/vim`控制输入框草稿编辑，不提供transcript的j/k滚动。

默认Ctrl+T打开轨迹视图，方向键移动、PgUp/PgDn翻页、g/G到首尾、Enter展开详情、q退出；它用于检视轨迹，不保证定位主聊天视口。需要用Vim键逐行搜索或复制长输出时，输入`/export`，TUI在当前工作目录写出`dsh-tui-export-<时间戳>.md`并提示路径，再用less或编辑器打开。导出的是当前会话投影，不宣称包含未载入的全部历史。Minimal UI和全屏草稿编辑器均不是终端滚屏模式开关；本轮不改tmux/termcfg、不自造复制UI。

### 推荐状态栏（已应用）与按需审批设计（未启用）

2026-10-13 按用户确认，下面的 18 项 `statusBar` 偏好已进入 `dsh-default` 正式来源，逐字段仅首次初始化。日后通过 `/settings` 修改仍属于原生用户偏好，apply 保留；未知字段也保留。升级时已受管共享文件中的既存偏好只消费初始化机会，不采纳用户值为受管基线，也不重写文件。首次接管非空未拥有文件仍失败。正式实例的重复 apply 为 changes=0；原生账号与会话不属于受管配置。

```yaml
statusBar:
  compact: true
  model: true
  thinking: true
  cwd: true
  contextUsage: true
  cache: true
  tokens: true
  cost: true
  tps: true
  gitBranch: true
  sessionTitle: true
  sessionId: false
  goal: true
  mode: true
  contextBar: true
  activity: false
  trajectory: false
  shortcutHint: false
```

model 是当前模型；thinking 是推理档位而不是耗时；cwd 是目录；contextUsage 是窗口占用，tokens 是累计输入/输出；cache 是缓存比例；tps 是输出速度。cost/goal/Git/标题等只有对应数据才出现。mode 展示符合条件的非默认模式，不能靠这一开关保证 workspace-write+ask 常驻显示；没有独立 auto-review 状态栏字段。权限用 `/permission`，审批状态用已注册的 `/auto-review status`。Provider、最近轮次重试及速度统计通过原生详情查询；活动行/轨迹默认关闭，减少重复信息。

审批目标维持 workspace-write+ask：普通沙箱内允许操作直接执行，只有实际 approval/request 才进入规则和 reviewer。硬拒绝先于模型；生产/外部写入、破坏性删除、权限变化、动态脚本、未知工具和不明目标转人工或拒绝，不按整个 Shell 名称建立 allow 白名单。模型只能给本请求一次允许，不产生后续通用授权。

正式配置默认 `agent_options.auto_review=true`，profile 按 base → 常量上下文 → Perry → TUI 的顺序加载。Perry 已在真实 approval/request 链上先于人工回答器处理适用请求，未加载官方 Full-access Auto review。下面是受管的公开配置：

| 字段 | 当前值与实际行为 |
| --- | --- |
| enableByDefault | true；新会话默认 ON |
| toolsPolicy | default=human；仅 write/edit=ai。普通工作区允许操作不额外调用模型；只有待审批请求进入 reviewer |
| reviewerProvider / model | spawn；不指定 reviewerModel，继承当前主会话路由，不自动换付费来源 |
| reviewerTools | rotom_review_context；只有常量配置说明，不提供 read/glob/grep/Shell |
| contextBudget | 最近 1 轮，最多 6000 字符；来自动作、授权/上下文，工具输出及文件里的“批准”不等于用户授权 |
| timeout / budgets | 30 秒；每轮最多 3 次审查、1 次失败；verdictCacheTtlMs=0，不复用其他请求的批准 |
| riskPolicy | 仅 low 可自动允许；更高风险转人工。判决协议只有 allow/deny，需人工的高风险 allow 由插件 delegate |
| fallbackPolicy | delegate；超时、格式/模型错误、预算耗尽转人工；人工不可用/失败则不执行 |
| allowUnmarkedAudit | false；原生审批记录持久化，完整 Perry 裁决审计在本 RC 上仍为内存 |

真实原生文件 smoke 已验证：AI allow 一次写入；deny、never、high、审查错误/人工失败和预算耗尽不写；未知工具走人工；普通工作区写入不调用 reviewer。人工模式通过同配方 false → apply → 完整重启验证，service/命令不注册，workspace-write + ask 不变。

Reviewer 的实际 native 工具目录仍会呈现 subagent，并非完全隐藏。当前审查子会话 depth=1，使用有效参数再次委派被原生 maxDepth=1 拒绝，额外 child=0；read 攻击被拒绝，目录没有写入/Shell/run_code。普通父会话保留原生子代理目录，未额外执行普通委派任务。本证据仅适用于当前 standard、spawn、native presentation；提高深度、换 provider、启用 PTC 后不得套用此边界。没有用工具白名单宣称 OS 读取根隔离或同用户凭据隔离。

上游 OFF 下一轮恢复 ON、关闭/卸载时迟到批准仍执行、完整裁决不持久化仍为 FAIL。配置中的风险文字不是确定性 Shell/path 分析器；文件目标与用户授权不明应转人工，但通用规范化读目录/上下文来源边界仍未完整证明。用户接受这些限制后部署，后续 [DSH-F01](acceptance/dsh-upgrade-20261012.md#dsh-f01-后续上游升级跟踪) 继续跟踪修复，失败没有改记 PASS。

`/model` 切换当前会话的模型，并由上游保存实例 HOME 内 `.dsh-tui/model.json` 的新会话偏好，不改 Rotom 的全局 main 角色。新会话先用该原生偏好，没有完整偏好时使用 Core `agent-default-model` 的受管 main 默认路由；这是用户选择的持久化，不自动切换其他付费来源。恢复已有会话用 `/resume` 打开原生列表并按 Enter，恢复目标最后一次请求记录的路由。旧配方同时固定 TUI provider/model 会优先覆盖恢复路由，现已改为 Core fallback；apply 只删除所有权记录完整且未漂移的旧字段，有漂移则冲突，原生偏好/账号/会话不迁移或重写。配置 rollback 可恢复旧 pin，也会恢复其覆盖行为，不是软件或会话降级。真实宿主回归覆盖公开启动 `--resume`，实际 `/resume` 选择器及修复后的 Cursor 账号续接仍未重测。主题、欢迎页和认证面板均使用上游公开入口，Rotom 不维护另一套菜单或会话管理界面。

修复不改写历史请求路由：如果此前恢复后已经用默认模型继续发过消息，目标会话最后记录的模型可能就是该默认模型，需要通过 `/model` 重新选择 Cursor 再继续正常任务。仅切换模型但尚未发出请求的选择没有新的 request/header，恢复不能保证保留这次未使用的选择；原生新会话偏好仍保留。无请求记录的空会话同样没有可恢复的请求路由。

## 重试与权限

Cursor 的内部 POST retry 为 0，Provider-owned recovery 也为 0，总尝试一次；不重发无法确认服务端是否已处理的请求。静态 API 默认 normal/0，显式上限为 2；拒绝 always。Codex OAuth 使用上游唯一 `dsh-llm-retry` 的有限默认 5 次重试，最多 6 次尝试，取消和 backoff 由原生实现处理；TUI 没有公开 OAuth retry 字段，不伪造覆盖。真实请求故障/Retry-After 的账号侧证据未完成；不靠重做已成功工具恢复模型流。

正式实例默认启用上述有限 auto-review 配置，没有第二个实验日常入口。使用 `/permission` 查看本会话有效模式，`/permission workspace-write` 回到原生 workspace-write + ask。`never` 会拒绝需要审批的请求，并非总是允许；批准只针对当前请求，不形成 bash/python/make 等通用白名单。

历史稳定运行时 Cordis4.0.4/Schema3.18.4 无法满足 Perry0.12.17 peer 下界，正式配方现使用上表 alpha 版本。真实主运行图、文件工具和原生审批已通过功能测试；完整 npm/peer 声明一致性、生命周期与审计仍保留失败。没有开启 Full-access/YOLO，也未加入第二个审批器或规则层。

| 通道 | 实际边界 |
| --- | --- |
| 文件工具 | 原生 ToolRuntime 与文件策略；正常工作区操作不额外调用 reviewer；write/edit 的待审批请求可 AI 审查，其余默认人工 |
| Shell | 待审批请求人工；沙箱内原生允许操作直接执行。OS confinement 的外部/符号链接哨兵实际拒绝，不宣称每条 Shell 都经过 AI |
| MCP | 待审批请求默认人工；远端服务副作用不由本地文件沙箱隔离，实际远端连接/交互未验收 |
| 原生子代理 | 原生 toolFilter、继承规则；父级批准不等于子级每个动作已审核，独立 read-roots 未建立 |
| 外部 Agent 内核 | 自己的原生权限/认证；DSH 插件覆盖未宣称 |
| PTC/run_code | 原生工具与 runtime 公开链；未运行相关原生通道则标 NOT RUN |
| 插件/直接 Node | 同宿主进程权限，不能称所有副作用已进入审批或 OS confinement |

workspace-write 管的是文件写入，并非通用凭据、网络、环境变量或同用户进程隔离。模型 API key 只按已选择引用注入；工具进程可能接触注入环境，插件自身是可信宿主代码。AI reviewer 不是同用户恶意进程安全边界。没有可用沙箱时，原生 confined 操作必须拒绝，不能偷偷降级 Full access；只显示配置模式不等于已验证后端。

## OpenSpec、迁移与恢复

DSH 不安装 OpenSpec，不自动部署 Spec 工作流/技能，也不使用 Spec Kit 替代。`project init openspec` 因 Pi 的独立可选能力保留，DSH 调用失败闭合。Rotom 和业务项目的 `openspec/`、`.specify/`、`specs/`、AGENTS.md 与用户技能原样保留；有漂移的受管产物不被覆盖或删除。

`rollback` 只还原受管配置。锁/软件再部署、原生会话格式和账号数据是不同恢复边界；没有将新版本写过的会话交给旧版本测试。正式部署记录为 `~/.local/state/agentcfg/migrations/dsh-formal-20261014/promotion.json`（0600），历史实例和状态项保留在 `~/.local/share/agentcfg/recovery/dsh-legacy-20261014/{instance,state}`。该目录没有日常启动入口，包含未知旧原生数据及历史包，不能宣称旧补丁宿主可继续正式使用。迁移前失败的合成恢复验证及一次复制保护失败恢复通过；正式就绪后不自动逆向搬迁数据。用户授权删除的候选账号/会话无法通过配置 rollback 恢复。不要自动降级或跨 HOME 复制真实会话。

显式原生验收入口：

```bash
.venv/bin/python scripts/smoke-dsh.py --allow-host \
  --runtime /absolute/path/to/current-sealed-runtime \
  --evidence /absolute/path/to/new-evidence-directory
```

中文多行/窄窗/原生文件工具/退出的独立入口为 `scripts/smoke-dsh-ui.py --allow-host --runtime ... --evidence ...`（仅本地假模型）。加 `--agentcfg-cli` 可验收真实 `agentcfg --local <临时配置> --profile dsh-default apply/sync/run`；完整复制已有 sealed runtime 及原收据，sync 必须保持无变化，run 不联网安装。两个新 HOME 的重建入口为 `scripts/smoke-dsh-rebuild.py --allow-install --cache /absolute/task-cache --evidence ...`，缓存根必须满足私人路径祖先保护；记录显式共享下载缓存，不称两次 cold build。两个脚本均用本任务私人 `/dev/shm` HOME，当前仅在 Linux 运行。

Cursor 原生认证面板的独立入口为 `scripts/smoke-dsh-auth-panel.py --allow-host --runtime ... --evidence ...`，使用真实 TUI/QuestionBridge、假 Coordinator 和明确标记的假长链接，验证面板交互，不访问真实认证。`scripts/check-dsh-cursor-panel.mjs /absolute/runtime` 另测并发、重新显示、错误隔离、注销失败和文件漂移。复制动作的完整参数可验证，真实 SSH 剪贴板和浏览器仍需客户端手测。

默认 pytest 仍隔离 HOME/DSH/XDG、阻断网络和真实子进程。native 脚本使用虚构状态、真实原包和任务临时哨兵，不是账号模型验收；其确定性答复者也不冒称 Perry reviewer 或真人点击。真实账号按授权范围单列，完整生命周期/审计与会话降级不在当前通过声明中；日常部署采用用户明确接受的限制。


### Perry auto-review 的操作与上游跟踪

当前正式 `dsh-default` 已使用 [Perry 0.12.17](https://github.com/PerryLink/dsh-auto-review/releases/tag/v0.12.17) 原包，不再用副作用为零的 probe 当作日常功能。限定实验入口已退役，历史锁/fixture/失败证据保留。最新正式原生功能与 OS 沙箱结果见 [验收记录](acceptance/dsh-upgrade-20261012.md#2026-10-14-正式配方默认启用-perry-auto-review)。

```text
/auto-review status
/auto-review on
/auto-review off
/permission
```

on/off 是上游会话命令。OFF 的跨轮次和在途请求缺陷未修复，不能把 off 或卸载作为可靠的急停。需要持续人工模式时，先取消当前轮次并退出 TUI，在正式 machine 的已有/新增对应表中设置：

```toml
[overrides.profiles.dsh-default.agent_options]
auto_review = false
```

然后运行 `dsh-config plan`、`dsh-config apply`、`dsh`。这会停用 Perry row，完整重启后仅原生人工审批。恢复时改 true 后 apply/restart；同一个 profile、实例、账号与会话，不安装另一套环境。不要重复 TOML 表；已有表时只增加/修改这一行。日常启动仍是 `dsh`，没有 `dsh-auto-review` 第二入口。

原生 asked/decided 的 session/request/call 可追溯，但完整 Perry verdict/reason 不可由冷读重建；不新建审计数据库、不强行写未标记事件。最新 C 回归仍观察到 off-late/unload-late 执行1、预期0，OFF下一轮回ON，Perry持久裁决0；用户接受这些上游限制用于日常部署，后续修复仍需原生复测。配置 rollback 只回受管字段，不降级软件/数据库，也不代替可靠的 false+重启切换。
