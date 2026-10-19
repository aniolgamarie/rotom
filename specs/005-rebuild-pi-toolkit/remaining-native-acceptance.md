# 共享模型与可选模块补充验收

日期：2026-10-19。分支 `design/pi-toolkit-reboot`，候选基点
`8ac50aaa8168b8a377c59736eaa1aebeb83a48c6`、目标 main
`93e4f7899725336c1180e53b4ec239eea5f984ce` 均未移动，候选仍未提交。
本文补充 [A/B/C 本地验收](native-acceptance.md)，不改写其历史范围。
完整任务状态见 [实施记录](implementation-status.md)；局部通过不关闭完整 feature 门。

## 授权、秘密与证据范围

用户要求继续所有剩余工作，随后明确允许新建实例复用共享默认模型和 key 配置，并要求密钥
不能被模型读取。新实例仅引用既有共享 SecretRef；准备程序不读取或复制秘密正文，不导入
真实 OAuth、其他工具账号或既有会话。秘密仅由管理器正常启动路径解析。
所有真实模型请求固定使用官方 `--no-tools --thinking off`，关闭内置和扩展工具。
这只是本次保密验收的条件，不是 Base 提供通用 OS 沙箱的承诺。

原始 argv、终端输出、服务响应和测试会话仅存于仓库外的私人证据目录，目录 0700、文件
0600。公开内容只记录布尔判断、允许的 usage 元数据、版本、锁和退出码；不发布路径、
会话标识、正文或端点。用量提取只取本次合成测试会话的元数据。

环境：Linux x86_64、Python 3.11.11、Node 24.14.0、npm 11.9.0、tmux 3.5a。
宿主始终为未修改的官方 Pi 1.3.0，主题为 0.1.6。模型请求与独立 Context7 查询使用实际
网络；无账号宿主检查使用新网络 namespace、仅 lo、IPv4 路由为 0。macOS 未运行。

## 来源与完整锁

生产输入范围为 `src/agents/shared/schemas/profiles` 的 305 个公开文件；算法为按相对
路径排序的 `[path, mode, sha256(body)]` 紧凑 JSON 再取 SHA256，排除缓存和 node_modules。
当前摘要为 `44be2fa6fb13714ad2cf54a7e1e704fdb35fe988f728a3fcaab124f63cf635e4`。
审计映射修订前、已包含 fork/浏览器修订的摘要为
`afa0be6672262b432d166363b485ed0dc0d5bd1ca376513e9981250698ead59f`。
每次验收使用当时复制的来源，不将早期运行追认为使用最终代码。

| 场景 | 实际选择 | 完整锁 identity | 来源及运行层级 |
| --- | --- | --- | --- |
| R | 默认 Base，共享默认模型 | `522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7` | 初始/继续为审计映射前来源；修订 fork、切换及压缩为 afa0be66…；真实模型 |
| B | footer 0.5.1 + 公开 observer | `e67e22a8fa6126909b928961ea106969ab2779e4f3f11966dafeb48fde9e3ec6` | 当前 44be2fa6…；真实短请求和状态数据 |
| C | cache-hit-monitor 0.1.1 | `e5ad0250fdf8eaea2d35d0b138890797851aad0654b053ca812749631bbdbcc8` | 当前 44be2fa6…；真实短请求，无正缓存命中样本 |
| D | Context7 4.4.2 | `cb35039ed9f0179cf1f1798e505bc9618e22f9378c788a107aec2df651d9fe5f` | 当前 44be2fa6…；原生连接，外部服务另测 |
| E | Brave 2.1.4 | `06ff518f10e89bd5339645751440f63ac6aa45cadef19110455ddbbde43d6116` | 当前 44be2fa6…；真实缺凭据路径，合成凭据仅初始化 |
| F | 完整 Playwright Skill，CLI 0.1.22 | `5f991611a184c554b267f0364ad47612fa560e76f116e7d27710d8363c3a6aa4` | afa0be66…；固定 Chromium，本地合成页面操作 |
| G | Cursor 1.4.39 | `e26c3f660b5990a25743a490fda876e8cb3e045c8424628f9561927ba0d77611` | afa0be66…；无账号加载、命令注册和重载 |

默认仓库锁保持 522bed3a…，没有用临时所选锁替换。D/E/F/G 各自实际执行
`lock → validate → sync → apply → doctor → apply`，最后修订来源的六项均 exit 0，
所有 npm 安装均 ignore-scripts。B/C 更新公开来源后分别 validate/apply/doctor 全 exit 0，
原锁未改变。R 初始 validate/sync/apply/doctor/apply 全 exit 0。

## 共享默认模型与真实状态数据

R 首次短请求、继续原会话、正确语法的分支、切到第二个已声明模型均 exit 0，预期回复
布尔判断均为 true；耗时分别 8.928、9.092、7.629、9.647 秒。继续验证了前文记忆，
分支通过官方 `--fork <session-id>` 入口。真实 TUI 的 `/compact` 产生一个 compaction
事件，随后短请求回复匹配、stop reason 为 stop，Ctrl+D 正常退出 0。
R 共六次宿主运行，其中一次历史 fork 参数错误 exit 1，其余五次 exit 0；六个 owner
最终全部 `idle_confirmed`，观察覆盖均 complete。

模型三列严格分开：请求为共享声明的默认 `kimi_code_openai`，切换请求为同账号另一声明
`kimi_code_k3_openai`；宿主选择分别为公开配置映射的 `kimi-for-coding` 和 `k3`；
服务端独立实际模型回执为 unknown。不得将宿主选择当作服务器证明。
SDK cost 各项为 0 不证明免费、订阅权益或实际账单为 0；实际用量的数据核对以下述B/C样本为准。

B/C 各完成一个真实短请求，共两次，没有重试或模型工具调用：

| 检查 | 观察结果 | 限制 |
| --- | --- | --- |
| B footer | SDK input 1395/output 12；footer 对应显示 1395/12、cache 0%；费用与 permission 保持 unknown | 只证明本次分支统计，不证明真实账单、缓存收益或输出速度 |
| C 缓存诊断 | SDK input 1389/output 12；cache read/write 均 0；waiting provider cache usage；reload 隐藏及重显通过 | 没有正缓存样本，不声称缓存命中或节省 |
| 生命周期 | 两组 Ctrl+D 均 exit 0；该检查点累计 B 11/C 10 owner 均 idle_confirmed/complete，active/unknown 为 0 | 运行中模型排队、取消及跨分支统计仍未验 |

T038 尚缺真实模型读写检索及命令场景；为防止模型触达密钥，本次未启用这些工具。
T058 有真实用量的局部证据，T059 仍受完整覆盖与差异接受门约束。

随后B仅重新打开本次测试会话和分支，没有新增模型请求。`--session`与`--fork`两次原生
打开各exit0，`/agentcfg-status`在reload前后均为input1395/output12，已有用量未重复累计，
费用仍unknown。它证明该单请求样本的续开/分支/reload统计，不证明新增请求累加、压缩后
统计、子任务合并或运行中取消。两条新增owner完整空闲，B从SSH结束的12增为14。

## D–G：原生加载、服务及浏览器

**Context7：**实际 Pi `/mcp` 显示 pi-context7 connected、两个工具，reload 后仍单份
连接。最终限定审计锁重建后再次原生连接成功，正常退出 0，两个 owner 均完整空闲。
独立通过发布的 stdio launcher 执行 initialize/list tools、resolve-library-id 和 query-docs，
后两者共两次外部工具调用，找到官方库并取得预期 API 内容，无 isError，服务正常 EOF
结束 exit 0，耗时 5.103 秒。该协议测试没有模型调用或 API key；它与 Pi 中原生连接
是两份不同层级的证据，不能合称模型已在 Pi 内调用服务。

**Brave：**先用正常启动解析共享引用，确认为所需 Brave 凭据缺失，exit 3，未启动服务。
随后仅在该私人测试实例填入明确的合成占位值，在隔离网络下检查初始化；Pi `/mcp`
显示 connected、一个工具，reload 后仍一份，正常退出 0。一个 owner 完整空闲，末次
apply exit 0。这不证明认证成功、搜索、额度或账单；真实搜索仍为环境不足未验证。
未修改共享秘密文件。

**Playwright：**初次 open 因默认系统 Chrome 不存在失败；自有入口现只在 open 注入
固定公开参数 `--browser=chromium`，不开放用户浏览器/配置/个人 profile 覆盖。
显式固定安装 Chromium 1247 和 ffmpeg 1011；没有全局安装、npx 或改动上游文件。
只有 headless-shell 不满足该公开 browser 选项，需要完整 Chromium。
file URL 被上游拒绝，未绕过限制；修订后用 about:blank 和纯字面 DOM 验证 snapshot、
中文 fill、click、读取输入/计数/结果及 close。无外部网页、账号、文件读取或模型请求。
浏览器正常关闭且已确认 PID 消失，管理器 exit 0，累计四个 owner 完整空闲。

**Cursor：**version/help/TUI 三次均 exit 0；`/cursor.doctor` 在 reload 前后注册，
未匹配虚构模型/无可用模型提示符合无账号条件。三次均在隔离网络运行，三个 owner
完整空闲。未读取其他工具的认证，未登录、核对 entitlement、请求 Cursor 模型或账单；
不能用共享模型 API key 代替该实例的 Cursor OAuth。

最终 D/E/F/G/R 归属汇总分别为 2/1/4/3/6 个 idle_confirmed，全部 observation complete，
active/unknown 为 0。没有发送终止信号、删除 owner 或用 UI 空闲代替内核观察。

## 回环SSH：传输与原生终端的限定证据

另建私有回环SSH fixture，仅监听127.0.0.1临时高端口，使用全新host/client key和私有
known_hosts；只由SSH工具读取新私钥，未读取个人.ssh、私钥或认证文件。
客户端固定空配置、严格hostkey、公钥only，关闭agent/密码/GSSAPI/转发；服务端配置
UsePAM no并关闭用户rc和转发，forced command及HOME固定到本次隔离启动器。无系统配置修改。

首次AuthorizedKeysFile被StrictModes拒绝/tmp可写祖先，认证前client/server均exit255，
未进入Pi、owner未增加。保留拒绝，不关闭StrictModes。第二次使用官方
AuthorizedKeysCommand接口，固定可信root-owned的cat及全部祖先，只读取该fixture新生成的
public authorized_keys；不使用shell或个人认证。配置-t/-T通过，随后公钥认证成功。

A/B/C各完成一次真实90列SSH PTY：中文bracketed paste、Ctrl+C清除、reload、Ctrl+D
正常退出，SSH client及remote manager均exit0，模型请求0。B/C额外固定--no-tools，
原始终端不进入模型上下文。SSH结束检查点owner为A13/B12/C11，全idle_confirmed/complete，
active/unknown0；所有单连接listener/sshd自然结束，三个fixture端口均已拒绝连接。

三组各305个公开文件的实际来源：A为早期
`086ad4b0d9a956d2c3f20cb502770ffaf18f09c5466e995782a31f07c945f183`，锁522bed3a…；
B/C为当前44be2fa6…，锁分别为表中e67e22a8…与e5ad0250…。
A没有使用未来参数/审计代码，不将该回环检查称为整个当前源码的原生覆盖。

该sshd非root inetd模式每次均exit255，日志为客户端正常disconnect，并提示无法写系统login
记录；不把server255改记0。传输、forced command和Pi交互有通过证据，服务端退出口径
及非root限制原样保留。此处只有本机回环90列，不能当作SSH三宽度、真实远端主机、不同网络
或其它平台验收，也不单独关闭T037/T058。

全部原生工作结束后再次只读核对本次八组归属：A13/B14/C11/D2/E1/F4/G3/R6，共54条，
均idle_confirmed且observation complete，active/unknown0。SSH三个端口仍拒绝连接，
所有临时client/listener/sshd/manager均已退出；没有遗留活动fixture或清除未知owner。

## 性能：只记录已测条件

A/B/C 各执行三次 version 和三次 help，顺序交错，共 18 次官方 CLI，全部 exit 0。
每次为新宿主进程，包含管理器、完整依赖核对与 CLI/资源发现；未清 OS 页缓存。
中位数如下，不能称为冷系统启动、初始上下文或长时间运行性能。

| 场景 | version wall/user/sys 秒；peak RSS KiB | help wall/user/sys 秒；peak RSS KiB |
| --- | --- | --- |
| A Base | 6.608 / 4.862 / 0.951；119088 | 6.268 / 4.823 / 0.967；123800 |
| B footer | 6.644 / 4.810 / 0.964；119404 | 8.723 / 6.824 / 1.086；137136 |
| C 缓存诊断 | 6.174 / 4.722 / 0.956；120620 | 6.280 / 4.847 / 1.021；126060 |

每组累计多六个完整空闲 owner；此后 B/C 的真实用量运行另各增加一个，不与早期
13 次记录混作同一检查点。没有足够数据宣称更快、更省 token 或更便宜。
所选服务/浏览器的同条件冷/热启动、额外进程和初始上下文比较未完成，T086 保持 partial。

## 失败修订、命令与开放门

- 首次 fork 使用旧的无值语义，native exit 1。自有参数校验改为 Pi 1.3 的必需 ID，并拒绝
  外部路径、分隔符、点目录及 `.jsonl` 文件名；正确入口真实复验通过，原失败保留。
- Context7 单选安装暴露与 250 包组合不同的 npm 提升路径；Brave 同路径又可能是无脚本
  的旧版本。将已审阅清单限定到精确包名/版本，再投影至实际锁路径。实际 manifest
  正文哈希和 lifecycle 严格校验未放宽，冲突拒绝、未知脚本仍失败。见
  [脚本审阅](npm-script-audit.md)。D/E 最终六项维护及原生连接均通过。
- 浏览器最初缺 Chrome、随后 file URL 被拒绝，两项失败原样保留；最终通过范围限于固定
  Chromium 与 about:blank 合成 DOM，不声称 file URL 已通过。
- 一次归属汇总脚本误取不存在的 descendants.coverage，显示 false；更正为真实
  observation.coverage 后，全部为 complete。只修报告程序，未改生产归属或证据文件。

实际 argv 保存在私人证据。公开等价模板如下，`LOCAL/WORKSPACE/SESSION_ID` 仅为占位符：

```sh
./agentcfg --local LOCAL --profile pi-base validate --format json
./agentcfg --local LOCAL --profile pi-base lock --format json --agent pi
./agentcfg --local LOCAL --profile pi-base sync --format json
./agentcfg --local LOCAL --profile pi-base apply --format json
./agentcfg --local LOCAL --profile pi-base doctor --format json
./agentcfg --local LOCAL --profile pi-base run pi --cwd WORKSPACE -- --no-tools --thinking off -p PROMPT
./agentcfg --local LOCAL --profile pi-base run pi --cwd WORKSPACE -- --no-tools --thinking off --session SESSION_ID -p PROMPT
./agentcfg --local LOCAL --profile pi-base run pi --cwd WORKSPACE -- --no-tools --thinking off --fork SESSION_ID -p PROMPT
```

这些模板不是实际私密 argv 的替代证据。真实执行用已准备 venv 的 `python -B -m agentcfg`，
启动时显式清理 HOME/XDG/PATH，并在私人记录保存完整参数、退出码和来源。

用户已决定继续只用社区调查插件，Pro 等上游完善；T064–T071 保持等待上游，
不实施自有调查执行插件，不降低并发/只读/递归/后台要求。精确包旁路证据见
[候选刷新](pro-candidate-refresh.md)。此外，真实模型工具、运行中取消、完整状态信息
差异接受、真实 Brave/Cursor 账号、服务性能及未验证平台仍开放，不能将本轮局部通过
记作 T096 或完整 feature 完成。
