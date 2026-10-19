# Pi 原生执行与授权审阅方案

本文件是执行方案，实际结果见[native-acceptance](native-acceptance.md)。2026-10-19用户在明确的A/B/C无账号原生请求后答复“授权”，
该范围已获准；不再重复申请。仅运行官方Pi、footer和缓存诊断的阻外网无账号验收，
不登录、不提交模型请求、不加载MCP/浏览器/Cursor。T038、真实服务和其他平台仍须各自范围和证据。
该范围的Linux本地可执行验证已完成；后续共享模型、D–G与性能的限定实际范围见
[补充验收](remaining-native-acceptance.md)。模型工具/账号、SSH及其它平台仍按各自证据保留，
既有管理器重建证据不能替代原生结果。

操作与边界来源：[quickstart](quickstart.md)、[运行契约](contracts/pi-runtime-and-modules.md)、
[协作与状态契约](contracts/collaboration-and-status.md)、[模块准入](module-admission.md)、
[可选模块](optional-module-recipes.md)、[当前 CLI parser](../../src/agentcfg/cli.py)及
[Pi adapter](../../src/agentcfg/pi.py)。

## 1. 组合与分别授权的范围

| 分组 | 精确组合 | 待审阅的执行边界 | 不能推定 |
| --- | --- | --- | --- |
| A | 官方 Pi `1.3.0` + Catppuccin `0.1.6`，`pi-base`，外部 plugins/MCP 均空 | 官方 CLI 的 version/help 和无账号 PTY 交互；虚构 provider/model，不提交模型请求，阻断服务网络 | 模型可用、账号通过、macOS 或远端终端通过 |
| B | A + 显式 `pi-footer@0.5.1` 与仓库 status observer | 单独允许加载该社区扩展及自有 observer；初始化配置后保留 `/footer` 修改，原生多宽度交互 | 默认启用已批准、全部十类信息对齐、统计等于账单 |
| C | A + `@narumitw/pi-cache-hit-monitor@0.1.1` | 单独允许加载 cache-hit-monitor；无模型请求时仅检查加载与空统计 | 真正缓存命中率、关闭显示即关闭 hooks |
| D | A + `@upstash/context7-mcp@4.4.2` | 单独允许 stdio 服务进程；联网连接/文档查询再单独授权。无 key 也会触及外部服务 | 不用账号就不需要网络授权、服务或费用已通过 |
| E | A + `@brave/brave-search-mcp-server@2.1.4` | 单独允许 stdio 服务进程；真实 Brave 账号、联网查询及费用另授权。未填写必需引用须 exit 3 且不启动服务 | `brave_web_search` 白名单限制 summary/Pro 等收费参数 |
| F | A + `@playwright/cli@0.1.22`及完整受管Skill，playwright/core精确alpha | CLI help/version、缺浏览器失败可在无账号阻外网环境验；完整页面操作需另获浏览器二进制下载和网站/本地测试页执行范围 | npm安装完成即有浏览器、open后daemon已退出、允许接个人浏览器/任意profile |
| G | A + `@rahularya01/pi-cursor@1.4.39`，provider cursor | 明确允许加载此非官方桥；固定关闭系统凭据，只用本实例Pi OAuth；无账号加载与catalog联网/登录/模型分别授权 | 继承token、读取Keychain/IDE、entitlement、费用和真实模型已通过 |

B/C/D/E 默认均不选择。首次各自单独验证，只有单项范围获准并完成后才审阅组合运行；
不能通过一次“允许原生”自动获得全部扩展、MCP、联网、登录或收费授权。
D 仅公开 `resolve-library-id` / `query-docs`，E 仅公开 `brave_web_search`。
MCP 使用已锁定 Python exec 清洗入口、独立空 cwd 和独立 HOME/XDG；不使用 npx、任意命令或项目 `.env`。

F/G同样默认未选，不随本次A/B/C授权开放。
F受管入口禁止install/attach/session/profile/config覆盖，浏览器缺失时停止，不用原始Skill中的
浮动npx或个人浏览器路线补齐。G登录和refresh由原生公开OAuth接口处理，管理器离线不读auth；
清理继承CURSOR_/PI_CURSOR_/USAGE_SESSION_TOKEN后仅注入固定系统凭据关闭键和本实例缓存。
真实journal保留、模型/entitlement/费用需对应账号场景，不能由无账号加载抵扣。

## 2. 每个场景的隔离准备

在仓库之外创建独立私人验证根，目录 `0700`、本地绑定 `0600`。每个场景使用独立候选仓库副本、
HOME、XDG_CONFIG_HOME、XDG_CACHE_HOME、XDG_DATA_HOME、XDG_STATE_HOME、实例、npm 缓存和空项目目录。
不读取、复制或自动发现真实 auth、模型清单、原生会话、项目历史或其他工作树的 owner 记录。
只从 [Base 公共示例](../../examples/pi-base.local.toml)构造虚构 provider/model 绑定，空 key；
Pro 基础配置如需重复，用 [Pro 示例](../../examples/pi-pro.local.toml)，仍关闭 collaboration。

记录候选 source digest/HEAD 与状态、依赖锁及所选 profile identity、Node `24.14.0`、npm `11.9.0`、
Python 版本、平台和终端条件。非秘密路径以场景别名记录；原始 PTY 日志可能含私人值，只在私人存储保留，
公开产物只保存脱敏步骤和结果。设置隔离环境，清除模型/service key、NODE_OPTIONS/NODE_PATH、
外部 PI_FOOTER_CONFIG 及服务路由污染；账号/服务未授权的 A/B/C 场景阻断出站网络。
不把虚构端点的失败写成真实模型或服务结果。

本次Linux验收采用私有PATH中的自有node启动包装器，在宿主child中进入user+net namespace，
再exec未经修改的真实Node/官方CLI；管理器留在外层，以免user namespace的UID映射破坏
公共私人路径祖先校验。namespace入口核对网络身份与路由为空，再exec，不使用NODE_OPTIONS
预加载或修改宿主。包装器/完整原始argv及网络身份只在私有证据保存；公开记录使用场景别名。
终端直接使用真实PTY，尺寸用该PTY的stty/ioctl修改，输入逐项发送，不伪造渲染或宽度。

以下是人工审阅命令模板，不是自动执行脚本。`$native_local`、`$native_workspace`、`$native_profile`
分别指向当前场景的私人绑定、空项目和已声明的 `pi-base` 或 `pi-pro`。运行前须在该终端设置上述隔离 HOME/XDG；
从该场景的候选仓库根执行。修改依赖选择时，在该副本显式生成并审阅锁，不能覆盖正式仓库锁：

```sh
./agentcfg --local "$native_local" --profile "$native_profile" lock --agent pi
./agentcfg --local "$native_local" --profile "$native_profile" validate
./agentcfg --local "$native_local" --profile "$native_profile" render
./agentcfg --local "$native_local" --profile "$native_profile" plan
./agentcfg --local "$native_local" --profile "$native_profile" sync
./agentcfg --local "$native_local" --profile "$native_profile" apply
./agentcfg --local "$native_local" --profile "$native_profile" doctor
```

`lock` 可能联网并写锁，`sync` 执行 npm ignore-scripts 安装，`apply` 写部署；三者不启动宿主。
它们的维护/下载权限须覆盖实际准备范围，不能由原生授权反向推定。
每次选择 B/C/D/E 或改变实际资源后都须显式 lock/sync/apply；不允许 `run` 隐式重锁、安装或修复。
`lock` 的有效本地选择只覆盖当前 profile，另一个 profile 当前重置为公开默认；发布前审阅两个 slice。

所有维护在首次原生运行之前完成。Linux在spawn前建立child subreaper观察；仅完整内核退出
证据可释放本次active owner。后代存活、覆盖失效、平台不支持或manager异常仍记unknown，
其EX维护继续阻断；新运行不能清除旧unknown。之后仍可按同binding的已部署契约启动另一main。
不同场景使用新建的独立验证实例，不复用旧账号/会话；这不清除也不裁定旧实例已退出。
不得删除 owner、超时清理、强制解锁或终止未知进程来取得通过。

## 3. 无账号原生授权后的精确入口

以下每条都启动真实第三方 Pi，必须获得原生授权；B/C/D/E 的已选组件还须包含在对应授权中。
version/help 各使用独立已准备场景；观察失效时unknown仍阻断后续维护：

```sh
./agentcfg --local "$native_local" --profile "$native_profile" run pi --cwd "$native_workspace" -- --version
./agentcfg --local "$native_local" --profile "$native_profile" run pi --cwd "$native_workspace" -- --help
```

它们最多证明所记录锁/目录下的 CLI 能执行；早期退出不能证明扩展已加载或模型成功。
PTY 场景的入口是：

```sh
./agentcfg --local "$native_local" --profile "$native_profile" run pi --cwd "$native_workspace"
```

A/B/C 的 PTY 不输入会发往 provider 的提示；粘贴测试只停留在编辑器，不提交。
需要真实 response、tool call、缓存或费用统计时转入第 5 节重新授权。
手工逐项记录，不创建或执行新的 PTY 自动化脚本：

| 场景 | 手工操作与通过证据 | 限制 |
| --- | --- | --- |
| 60/90/130 列 | 三个实际 PTY 宽度；中文/宽字符、长模型名和分支、连续 resize、粘贴后取消 | 自有模拟宽度测试不抵扣真实终端；不伪造宽度 |
| B 状态栏 | 两行布局、选择/活动/context 优先项；`/agentcfg-status` 完整观察；`/footer` 修改后退出、同 binding 再进入确认保留 | permission/缺失 usage/费率保持 unknown；时长和速度标明计算范围 |
| reload | 使用原生 `/reload` 后观察重复注册、残留 widgets、输入和终端恢复 | 只加载该场景已准入资源；不安装新包 |
| 取消/退出 | 编辑器粘贴取消；Ctrl+C/原生正常退出；记录实际 exit、manager/host/服务后代状态 | 取消回执不等于后代已释放；无请求不能声称模型请求取消通过 |
| 两个 main | 两个 PTY 启动同一已部署 binding；区分各自 run_id/进程 birth identity，退出一个后另一个仍活动；再退出另一个 | 不更改 main 共享资源；退出一个不清另一个；若均有完整内核证明才允许维护，任一unknown则继续阻断 |
| SSH/tmux | 实际SSH传输/PTY及tmux终端检查，记录真实宽度、粘贴、reload和退出；回环SSH与远端机器分列 | 普通本地PTY不能替代SSH；任务未要求必须远端机器或sshd exit0，非零服务端退出仍须保留原因/影响 |
| macOS | 在明确获准、工具链可用的 macOS 环境独立重建与上述验证 | Linux 管理器/PTY 通过不外推；当前缺环境保持 `not_run` |

两 main 的观察是主运行归属验证，不是允许 Pro 子调查。观察后代仅使用测试进程的公开 PID/birth identity，
不扫描真实用户会话正文。服务关闭/父退出/PTY 关闭均单独记录；未确认项记 unknown，并确认维护被阻断。
若现有接口无法给完整证据，保留限制，不实现新恢复或清理协议。

## 4. CI 仅验证自有 observer

[workflow](../../.github/workflows/tests.yml)新增独立 `pi-status-observer` job，固定 Node `24.14.0`，
不执行 npm install，不导入 Pi 或社区代码，仅运行：

```sh
node tests/pi_status_observer.test.mjs
```

[自有测试](../../tests/pi_status_observer.test.mjs)以 fake API 驱动
[observer](../../agents/pi/support/status-observer.mjs)。原生修订后该命令本地观察为 **7 tests / 7 pass / exit 0**，
Node 实际版本 `v24.14.0`；这不是原生宿主或 GitHub 托管 CI 已通过证据。
`node --test` 在当前工具环境可能只汇总一个文件，不能把文件级汇总误写成 7 个实际测试结果。

setup-node 固定 `2028fbc5c25fe9cf00d9f06a71cc4710d4507903`，是官方
[v6.0.0 release](https://github.com/actions/setup-node/releases/tag/v6.0.0)对应 commit，
已由 [GitHub 官方 tag API](https://api.github.com/repos/actions/setup-node/git/ref/tags/v6.0.0)
核实 object.type=commit、object.sha 为该完整值；不依赖浮动 tag。
[pinned action.yml](https://github.com/actions/setup-node/blob/2028fbc5c25fe9cf00d9f06a71cc4710d4507903/action.yml)
公开支持 `package-manager-cache`，job 显式关闭自动包缓存。Node 工具链安装会访问官方分发源，
自有观察测试没有服务调用；未增加账号 secrets 或原生 smoke。

## 5. 账号、模型与外部服务的另行授权

用户只需提供非秘密的 provider/model 标识、账号归属别名、允许的服务/操作、次数与费用上限、
允许联网的公开服务目标以及平台/终端范围；不索要或转发 key、token、登录链接或验证码。
凭据由所有者按已有 SecretRef 在私人环境填写。没有明确上限时不试探收费接口。

账号或服务获准后仍通过第 3 节同一受管 `run pi --cwd ...` 入口，在原生界面手工发起已批准的一次请求；
只追加已经核对、匹配选中声明的原生 provider/model 参数：

```sh
./agentcfg --local "$native_local" --profile "$native_profile" run pi --cwd "$native_workspace" -- --provider "$native_provider_route" --model "$native_remote_model"
```

`$native_provider_route` 是已选声明的原生 route，`$native_remote_model` 是已选模型的精确 remote ID；
不允许未知 route、自动别名或 fallback。这条命令只是受管启动模板，未包含模型提示或服务调用授权。

D 无 key 连接、带 key 调用分别记录；若声明 key 而缺失须在服务启动前 exit 3。
E 先核必需引用与准许的搜索参数/summary/Pro 等费用范围，再允许一次白名单工具调用。
C 的缓存统计需已批准的实际模型请求；B 的估算费用只能对照宿主价格来源，不当作账号账单。
记录请求模型、宿主可确认模型与服务可确认实际模型；无法确认的值保留 unknown。
服务错误或超限即停止，不自动换服务、补 key、重试或扩大查询。

本次独立授权已在[本轮交付验收](current-delivery-acceptance.md)记录：共享SecretRef默认请求、
Context7 keyless服务、固定Chromium合成页面，以及一次最多12调用的合成文件真实工具测试。
该工具测试在公开事件保护器下执行，所有越界工具/路径执行前拒绝，真实key正文不进入模型。
它是具体一次验收授权，不是一般性启用未受限工具的授权；生产默认也没有这份验收保护器。
用户已接受状态三差异，并明确延后Brave/Cursor真实账号验收；后续不重复索要已授予的授权。

## 6. Pro 的静态阻断，不能列入原生授权绕过

精确 `@mjakl/pi-subagent@3.1.0`（源码身份
`6d05481a475c08bfd1ee5a623d5b742fb95b2147`）的发布 `index.ts:874` 在遍历 calls、
判断是否提供 session 之前，无条件调用 `getPersistentSessionDir(ctx)`。
该函数 `index.ts:629–644` 通过强制类型转换探测 `ctx.sessionManager.usesDefaultSessionDir`。
官方 Pi `1.3.0` 发布 `dist/core/session-manager.d.ts:178` 的公开 `ReadonlySessionManager` 为 Pick 列表，
**不包含 `usesDefaultSessionDir`**。即使包有回退分支，这项非公开探测仍是实际执行路径。
固定来源：[mjakl 精确源码](https://github.com/mjakl/pi-subagent/blob/6d05481a475c08bfd1ee5a623d5b742fb95b2147/index.ts)、
[官方 Pi 固定版本](https://github.com/earendil-works/pi/tree/v1.3.0/packages/coding-agent)。

选择 read/ls、限制工具、不给资源或不传 session 都不能避开该调用；角色提示也不能构成强制只读闭包。
不能通过给插件打补丁、改宿主、包装私有方法或补自有调度器绕过。
另外每主强制 2、两主可各 2、取消/未知退出的名额及完整后代归属仍需全部满足准入门。
原候选保持 `held`；T064 未通过，不执行 T065–T069，也不把本方案或“允许 native”当作门已通过。

## 7. 交回的证据与停止条件

每项记录授权范围/来源、候选 digest、完整锁/profile/runtime identity、实际 argv、平台/终端条件、exit、
观察到的加载/进程/输出与副作用。状态只用已完成、进行中、失败待决策、环境不足未验证；
缺 SSH/tmux/macOS、缺账号或缺完整观察不得记为通过。原生失败不能用隔离测试或 CI 补记。
锁失配、包缺损、literal secret/未知 MCP、pending/opaque legacy owner、进程归属未知或需要未授权操作时停止，
保留文件与记录，不自动清理、重试、扩大模型/服务或更改费用上限。本方案本身不向用户提出授权请求。
