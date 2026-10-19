# Pi 本轮交付验收（2026-10-19）

本页保留原 reboot 已验快照及其来源身份。从 `main` 重放的候选和独立检查见
[集成审阅记录](integration-candidate.md)。

本轮约定交付完成，任务87/96；剩余T064–T071与T096按用户决定继续开放。
本记录承接[补充验收](remaining-native-acceptance.md)，后者的80/96、54条owner和局部未验结论
属于该次检查点。本轮按用户明确决定交付已验模块；Brave/Cursor真实账号验收延后，Pro继续
只采用社区插件并等待上游。历史失败和未验证范围保留，完整feature仍受T096约束。

## 用户决定与来源边界

- 用户允许新建隔离实例引用共享默认模型与SecretRef，同时要求“密钥不能被模型读取”。
  凭据只由正常框架解析用于认证，不输出秘密正文；普通模型请求均使用`--no-tools --thinking off`。
- 用户明确接受：“宿主未提供可查询的权限状态”的详情说明、当前分支输出均速、窄屏部分统计
  放在详情。权限不可查询不表示存在权限保护；`--no-approve`是项目资源信任选项，不能当工具审批。
- 用户明确选择“本轮交付已验模块，Brave/Cursor延后真实账号验收”。两者已有接线和无账号证据
  仍保留，真实认证/调用/权益/账单保持not_run，不改称从未选择或已通过。
- 自动审批首次拒绝真实工具测试，理由为向外部默认模型发送私人临时绝对路径和授权工具执行。
  准备相对合成文件名版本后，用户明确回答“授权这一次有界真实工具测试”；仅执行该次有界任务。
- Pro按用户决定继续社区路线；不引入自有调查执行插件，不降低每主2/两主4、只读、禁后台/递归要求。

候选HEAD与目标main均未移动，见[实施记录](implementation-status.md)。当前305个生产文件摘要为
`f1c83e6a2dc4a16b32c82de832df75a791d7f9beab5f8ea461560d581a934dad`，算法为相对路径排序的
`[path,mode,sha256(body)]`紧凑JSON再SHA256。范围为src、agents、shared、schemas、profiles，
不含Python缓存。状态栏验收阶段摘要为`361a853d…`，相对先前`44be2fa6…`只新增中文权限说明；
随后四模块禁用/重选暴露公共共享文件来源缺口，修复后为上述f1c83e6a…，详见下节。
此前运行绑定原摘要，不把新摘要回填旧证据。默认Base/Pro锁仍为
`522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7`。

平台为Linux x86_64、Python3.11.11、Node24.14.0/npm11.9.0、Pi1.3.0、主题0.1.6，
终端用tmux3.5a与实际PTY。macOS、其他架构和真实远端机器不在本轮支持声明内。
所有完整argv、原始TTY/合成会话及运行记录只在0700私人临时目录保存，文件0600；
公开投影仅包含数值、状态和预期匹配布尔，不含凭据或会话正文。

## Base真实工具与会话（T037/T038）

先前原生资源、静态主题/编辑器、中文三宽度、reload、两主运行与维护保护证据继续有效。
A/B/C的回环SSH实际经过SSH传输和PTY，90列粘贴/清除/reload/正常退出均通过，client/manager
均exit0。非root inetd sshd退出255及login-record限制原样保留；不将其写成服务端exit0、
真实远端机器或三种SSH宽度。原任务要求SSH/tmux交互，并未要求真实远端机器或sshd必须exit0；
先前验证计划增加的这一额外停点已改回与任务一致的范围，不能据此外推其他平台。

共享默认模型的短请求、模型切换、继续/分支/压缩在前次检查点通过。本轮补齐一次真实工具任务：

| 检查 | 实际结果 |
| --- | --- |
| 允许的工具 | read、grep、write、bash；各执行一次，bash仅固定printf命令 |
| 合成越界 | 仅一次读取`../blocked.txt`，在工具执行前阻断，没有重试 |
| 输出 | 固定输出文件逐字节一致；最终回复、read/grep/printf结果布尔均true |
| 上限与退出 | 5次tool_call；第12次阻断并公开abort的上限未触发；最终stopReason=stop，manager exit0 |
| 用量 | SDK合计input2881/output257/cacheRead5120/cacheWrite0/total8258 |
| 归属 | R owner9→10，全部complete/idle，active/unknown=0 |

该次沿用正常`load_workspace`、`runtime.run`和物理/状态/包租约及后代观察，通过显式
`launch_operation`测试回调追加官方公开`-e`和`--tools read,write,grep,bash`。
基线argv与实际argv分别完整记录，生产参数白名单未放宽。保护器只使用公开`tool_call`事件，
不注册替代工具；精确合成路径/参数/长度/固定命令之外一律拒绝，异常也拒绝。
保护器SHA256为`5a9215efc015302576f9f90868eae6d02b973c1b87d21972582233d7b1fead3c`。
17项Node stub检查通过；官方扩展加载故障的无账号RPC预验在模型交互前exit1。
首次`--help`早退未加载扩展，不作该故障预验的通过证据。

这是显式验收保护器下的官方工具行为，不是生产默认权限隔离、Pro执行器或通用安全沙箱。
没有读取模型key正文、其他真实项目、用户文件或个人认证；实际服务端模型与账单仍unknown。
一次agent运行含三段assistant响应，不能将其写成只有一次底层HTTP请求。

## 状态信息与缓存（T058/T059）

B本轮续开已有合成测试会话，全部工具关闭。第一次取消尝试因回复先结束未成功中断，保留为
完成响应；第二次实际在working阶段按Escape，宿主stopReason=aborted并回到idle，随后短请求
正常回复。只证明宿主本地取消确认，不证明远端服务已停止计费或服务端取消。

| 检查点 | 分支累计input/output | 缓存/其他观察 |
| --- | --- | --- |
| 既有起点 | 1395/12 | SDK与界面一致 |
| 多轮与实际中断后恢复、压缩前 | 3201/127 | 界面缓存47%；aborted的零用量不解释为免费 |
| 原生compact后 | 3201/127 | 一条compaction，tokensBefore1636；压缩摘要不重复计入分支assistant累计 |
| 压缩后新增短请求 | 3625/142 | 界面缓存53%；新增424/15、cacheRead1280 |

B该轮manager exit0，工具结果0，owner14→15完整空闲。该轮生产源为44be2fa6…，footer锁
`e67e22a8fa6126909b928961ea106969ab2779e4f3f11966dafeb48fde9e3ec6`。
随后复制当前305文件、正常lock/validate/sync/apply/doctor/apply全部exit0；依赖packages集合
与旧锁相同，偏好配置逐字节不变。新B锁为
`3546e744dde2bd8855b43c829443ddbacd001b10a6ec19eb2605fade8960a0d7`，真实详情已确认显示
“宿主未提供可查询的权限状态”。未修改社区包、宿主或缓存副本。

C在原合成会话中新增两次短回复，第一笔1425/13且cache0，第二笔182/13/cacheRead1280。
插件显示87.6%，即1280/(182+1280)，与标准SDK字段一致；不是从费用猜缓存。
reload、重新显示和正常退出通过，没有模型工具。C该轮owner11→12完整空闲；
后续性能三次运行后为15。C源44be2fa6…、锁
`e5ad0250fdf8eaea2d35d0b138890797851aad0654b053ca812749631bbdbcc8`。

十类信息均在[状态口径](../../docs/pi-status.md)逐项处置：公开来源可确认的模型选择、项目/Git、
分支usage/cache、context、会话起点、活动和分支均速按范围展示；价格表全零或无账单来源时
费用unknown，不补零。权限说明、分支均速、窄屏详情三处差异已有用户明确接受。
Pro未启用，没有真实子调查统计的承诺；不将合成子任务或compaction用量当父分支累计。

hooks清理按可观察效果分层确认：[首次原生验收](native-acceptance.md)已记录B reload后单一
footer、C两种显示状态reload后恢复默认隐藏且无重复widget，正常退出后alternate screen和
bracketed paste等终端模式恢复。完整内核后代退出证明没有插件进程继续执行；不靠UI idle
推断后代已结束。自有观察器公开`session_shutdown`清空四个事件值由
[Node测试](../../tests/pi_status_observer.test.mjs)7/7独立验证，属合成事件证据。
上述native UI/终端/进程效果与自有事件清理分别列明，不声称反射第三方私有hook注册表或
逐条观测其内部移除；没有为验收修改包或插入私有探针。

## 按需模块的服务证据

Context7固定4.4.2：Pi连接/两个工具/reload与独立stdio的两次真实resolve/query继续分列。
本轮另向同一固定公开launcher发送一次虚构不存在工具名，返回明确工具错误；随后tools/list
仍可用，EOF正常退出0，耗时0.565秒，无模型、无API key、无外部查询。这里验证服务失败后
仍可用，不声称模型已通过Pi调用MCP。该keyless路线没有账号前提，不凭空增加账号门。

Playwright保留固定Chromium1247、about:blank合成DOM、中文输入/点击/读取/close与PID退出
证据。初次系统Chrome缺失、只装headless-shell不足、file URL被上游拒绝均保留为实际失败；
最终支持范围不包含真实网站/账号。显示偏好隐藏与模块禁用分别验收，不能互相抵扣。

四模块所选组合/真实禁用恢复及六场景已通过，T085完成；最终匹配应用级首次/重复测量
也已通过，T086/T087完成，数据和取舍见下节。

## 组合测试发现的共享文件来源缺口

四模块启用与正常操作通过，禁用维护及无模块原生启动也通过；重选时lock/validate/sync
均0，但apply和plan均exit4，10个冲突全部位于`pi-home/mcp.json`的原MCP字段。
禁用后这些字段已退出，文件留下`{}`或原生非受管内容；长期owner只记录首次启动静态声明的
settings/models，没有记录后来实际管理的MCP文件，因此重选被正确拒绝为非空未接管文件。
不是footer INITIALIZE遗失；后者原本就跨取消选择保留初始化已消费的记录。

公共修复只在计划通过后，将实际current.items中字段目标的文件路径累积到既有
owner.shared_files；不提前把待部署候选或从未启用的MCP文件当成已拥有。
补录与原部署状态走同一pending/commit事务；即便配置无变化而只有来源需补录，也提交状态，
不轮换真实配置备份。首次陌生非空文件仍拒绝，已存在的受管字段仍冲突，原生内容不进入来源记录。
该来源按实例相对路径识别，沿用既有共享文件契约，不承诺inode级身份或删除后重新创建检测。

隔离复现覆盖动态文件退役/重选与回滚、从未选择的文件不预认领、历史路径上现存字段仍拒绝、
无变更补录幂等及提交失败原子恢复；另有Pi的footer+cache+Context7禁用重选并保留偏好/原生
哨兵用例。旧state若已完全丢失该路径不会被该修复凭空接管；本次F计划使用正常公开rollback
恢复仍在单份备份中的组合，再由正常apply补录来源，最后重新验disable/reselect。
跨工具七文件171项隔离回归通过；最后仅补强一个测试断言后公共31项再次通过。
F原生复验已通过：正常rollback0，plan0且正文changes0，apply0补录mcp来源，doctor0；
随后禁用六项维护和真实无模块TUI、重选六项维护及组合TUI均0。未手改owner、接管字段、
删原生文件或放宽引用保护；F最终原local逐字节还原，单browser锁与原锁5f991611…完全相同，依赖/部署doctor均passed。
F owner7→11全部complete/idle，active/unknown0；manager/client均0，termios逐字相同，
私人tmux server已退出。匹配fresh测量已完成，数据见下节。

## 所选模块六场景（T085）

本轮明确选择交付footer、cache诊断、Context7和Playwright CLI。Brave/Cursor真实账号按
用户决定延后，已有连接失败/缺凭据/合成初始化/无账号加载记录继续保留，不移作通过。
正常MCP查询与浏览器页面操作可分别经公开服务客户端/CLI完成，原任务不要求每模块均由模型
自主调用；Pi实际连接与独立服务调用两层证据保持分列。

| 场景 | footer | cache诊断 | Context7 | Playwright CLI |
| --- | --- | --- | --- | --- |
| 启用 | 单选及四组合实际加载 | 单选及四组合命令/widget加载 | 单选及四组合connected、两工具 | 精确CLI/完整Skill和固定Chromium加载 |
| 正常使用 | 分支usage、多轮/compact统计 | 真实cacheRead1280→87.6% | Pi连接/reload；独立真实resolve/query | about:blank中文输入/点击/读取/snapshot/close |
| 缺前提 | 无独立外部凭据/服务前提，不重复制造共同宿主缺包 | 同左；零cache是正常waiting，不冒充缺前提 | 本轮keyless路线无账号必需；声明必需key缺失由隔离门exit3 | 初始缺系统Chrome/仅headless-shell均失败，显式固定完整Chromium后通过 |
| 失败 | 四组合断网合成绑定错误后idle/reload仍单份footer | 同错误下保持waiting，可reload重显 | 虚构工具明确error，随后list可用；正常EOF0 | 缺浏览器和file URL拒绝保留，不绕过 |
| 禁用 | 从选择移除后无-e入口；偏好保留 | 无-e、无widget加载；隐藏与禁用分开 | no-mcp/无额外服务后代；文件路径来源保留 | 受管CLI入口移除，无浏览器自动启动；原生状态保留 |
| 退出 | 正常CtrlD/client/manager0、终端恢复 | 同左，无重复widget | 服务EOF0；Pi及后代完整退出 | 显式close后PID消失，Pi退出后归属完整空闲 |

首轮正常四组合TUI/固定about:blank DOM及close绑定source361a…；组合锁30d5e922…，
同时有Context7、footer、cache与browser Skill。公共所有权修复后的F源f1c…、组合锁仍相同，
浏览器CLI/Skill/引擎来源没有变化；复验聚焦受影响的禁用/重选、MCP和界面生命周期。
修复后的禁用真实TUI只有宿主后代1，
无-e/no-mcp、browser入口不存在；重选后Context7重新connected。footer行数reload前后
均1，cache waiting行数1→reload默认隐藏0→重显1，不使用私有hook注册表反射。

断网失败用例首度自动审批拒绝，未发送输入；随后安全核验确认保留域名example.invalid、
明确合成key、无secrets_file，OS namespace只有lo/IPv4路由0、所有工具关闭。透明说明这些
事实后，正常手工输入复审通过。仅一次合成输入；SDK自身产生4条连接error响应且usage全0，
不是四次人工重试，也没有可达真实provider或真实凭据。toolResults0；错误后footer仍单份、
cache waiting、活动idle，reload和正常退出通过。SDK零值不作真实账号账单证据。

## 性能的既有实例样本

同一平台/90×35终端、相同公开启动代理、no-tools/thinking-off；每档每阶段一个样本。
startup为实际TUI启动提示标记，CPU与wait4峰值RSS为整个交互运行，后者不是进程树总峰值。
树RSS是就绪时单次快照。没有清OS页缓存，以下first/repeat不是全新实例或OS冷启动。

| 组合 | startup first/repeat秒 | user first/repeat秒 | sys first/repeat秒 | wait4 RSS first/repeat KiB | 额外就绪进程 |
| --- | --- | --- | --- | --- | --- |
| 默认R | 6.173/5.892 | 4.948/4.723 | 0.911/0.876 | 147304/135492 | 0 |
| footer B | 9.878/7.931 | 8.983/6.595 | 1.189/1.093 | 332592/153408 | 0 |
| cache C | 6.269/6.782 | 4.931/5.264 | 0.959/0.933 | 141532/137508 | 0 |
| Context7 D | 8.238/7.922 | 6.745/6.617 | 1.505/1.369 | 134788/136472 | 1个MCP |
| browser Skill F | 6.588/5.950 | 5.001/4.778 | 0.971/0.950 | 135920/136484 | 0；未open浏览器 |

B首场后续执行过状态详情，整场CPU/peakRSS含该额外UI动作；启动marker和详情前的树RSS
单独保留，不能用该行推算插件纯增量。R/D/F源44be2fa6…，B361a…，C44be2fa6…；
既有偏好、资源与测量轮次不同，样本不支持显著性、因果性能增量或更快/省token主张。

另各用同一短prompt、同一SDK provider/model标识完成一次no-tools请求，均exit0：

| R | B | C | D | F |
| --- | --- | --- | --- | --- |
| input1386/output11/cacheRead0 | 1382/11/0 | 102/11/1280 | 1395/11/0 | 1383/11/0 |

C的input加cacheRead为1382，缓存状态不一致，不能把102与其他input直接相比宣称省上下文。
SDK cost全零仍不代表免费，实际serving model/账单unknown。10次TUI与5次独立短请求退出0，
全部新owner完整空闲；R最终10（含工具测试）、B18、C15、D5，F后续组合另计。
应用级冷/热测量另用fresh实例，不以此表冒充首次运行。

## 首轮fresh应用实例与后续匹配对照

另建全新应用HOME/XDG/instance/state，正常sync/apply/doctor后首次真实TUI，再同实例第二次
真实TUI。两组均source361a…，默认锁522bed3a…，四组合锁
`30d5e922be3a5e168caffbf780e0a900ac394437b024c7921fab15e61e6c51e4`。
四场均exit0，各0→2条owner complete/idle，无模型请求或浏览器open；采样进程均退出。

| 组合 | 首次/重复startup秒 | user秒 | sys秒 | wait4 RSS KiB | 就绪额外进程 |
| --- | --- | --- | --- | --- | --- |
| fresh Base | 5.851/5.815 | 4.735/4.705 | 0.975/0.932 | 147764/135400 | 0 |
| fresh四组合 | 12.526/9.492 | 11.159/8.588 | 1.753/1.522 | 331328/157076 | 1个MCP，浏览器0 |

Base带默认两种静态Skill，四组合只带browser Skill，rules/prompts/themes相同；这处已核实
的静态资源差异是混杂，保留真实记录，不把它称为只增加四模块的纯增量。
为完成条件一致的测量，最终source f1c…另准备保留同一Base两种静态Skill、仅增加四模块的
匹配fresh对照，最终结果如下。没有清OS页缓存，每阶段仅一例，不作统计显著性或系统冷启动主张。

首轮fresh组合sync已成功后，私人prepare脚本因余量低于自设150MiB在apply前停止；这是
辅助脚本门限，不是产品失败。确认后续仅无安装apply/doctor/两次短TUI，在103MiB余量下
完成，随后持锁回收自己的派生依赖树。未降低生产文件系统或所有权校验，未触发ENOSPC。

## 最终条件一致的应用级冷/热对照（T086/T087）

两组均使用最终source f1c83e6a…，全新HOME/XDG/instance/state，虚构provider/model相同，
rules/prompts/themes及repo-navigation、safe-linux-scripting两种静态Skill相同；组合只增加
pi-footer、cache-hit-monitor、Context7及playwright-cli。正常lock/validate/sync/apply/doctor
各五项均0，随后首次/第二次实际90×35 TUI各一，四场均exit0，无模型请求或browser open。

| 组合 | 应用首次/第二次startup秒 | user秒 | sys秒 | wait4 RSS KiB | 就绪树RSS KiB | 就绪额外进程 |
| --- | --- | --- | --- | --- | --- | --- |
| 匹配Base | 5.765/6.666 | 4.683/4.960 | 0.945/0.951 | 150076/136068 | 201064/187724 | 0/0 |
| 匹配四模块 | 11.513/10.112 | 10.521/8.624 | 1.547/1.458 | 333316/154476 | 512088/302744 | 1/1个MCP；浏览器0 |

Base实际锁522bed3a…，匹配组合实际锁
`14f845163acd43c1461b71600e4a58e9688ef06c4dcd4f5c91834e9510e24b0d`。
私人factory最初复制模板时把30d5e922…标签带进run元数据；正常启动实际使用部署契约。
manifest、deployed launch与sealed receipt三方均确认实际14f845…，receipt含三种Skill；
`actual-lock-amendment.json`保存差异并更正最终安全摘要，原记录未重写，不把模板标签当实际锁。

两组各0→2条owner complete/idle，active/unknown0，采样进程均已退出。每阶段单样本、
OS页缓存/外部编译缓存未清；“冷/热”仅指应用实例首次/第二次，不是OS冷启动。
全程wall含手工停留，startup marker才是启动代理；wait4 RSS不是树总峰，树RSS只是单快照。
逐模块初始SDK用量见前表，最终组合没有再发模型请求，不声称组合真实账单或token收益。

取舍：保留精简Base默认，不默认同时启用四模块。footer满足已接受的信息需求；cache诊断
与footer有重叠，只作最近样本排障时的显式选项，原生/现有显示够用时不启用；Context7仅在
需要文档时选择，承担一个额外MCP进程；browser Skill按任务选择，未open时不启动浏览器。
没有速度/token/费用收益证据，不以“社区热门”默认增加开销。Brave/Cursor真实账号继续延后，
其他未注册候选保持candidate/held，不自动fallback、安装、登录或启动后台。

本轮最终只读汇总A/B/C/D/E/F/G/R分别13/18/15/5/1/11/3/10，首轮fresh与匹配fresh
各两组、每组2条，共84条owner全部complete/idle，active/unknown=0。该统计只读运行归属
元数据，不读取auth/key/session正文；不把历史54或旧B/C快照当最终数字。

T085四模块六场景与组合、T086适用测量、T087选择/准入/退出矩阵按该范围完成。
完整feature尚未完成：Pro T064–T071等待上游，T096保持开放，不归档或提前宣称Pro可用。

## 验收产物与临时资源

私人产物basename包括`source-current.json`、B/C的`session-metadata.json`、`tui-captures.json`、
`B-refresh-safe.json`、工具`reviewable-action.json`/`run-summary.json`/`safe-summary.json`、
round2–4性能`safe-summary.json`及`service-failure-summary.json`。实际完整argv和未规范化路径
仅存私人证据，公开等价命令见[补充验收](remaining-native-acceptance.md)。

空间不足时，仅回收本任务已结束合成fixture的可再生node_modules，先doctor核验，再持物理EX
生命周期锁与状态锁复核所有owner complete/idle及收据/锁身份；不删除owner或终止进程。
E/G回收前doctor均exit0，分别1/3条owner完整空闲；全部source/lock/receipt/native home/记录
保留，未来重跑须显式sync，回收后不能沿用旧doctor声称当前依赖已安装。
旧B的非current依赖树也按相同保护回收，当前运行包未动。

本轮未提交、合并、推送或发布；工作仍在reboot工作树。Pro T064–T071与完整feature T096
继续保持开放，延后真实账号验收不等于完整feature通过。
