# 按工具维护流程：验收范围与证据

## 2026-10-28：T143 会话补全与 T144 状态收口

本轮从候选 `97ab387` 继续，完成普通恢复的会话ID补全接线及任务进度说明。生产来源摘要为 `948512b1a2a4b645c22d432a577196ce2d1ba38ee67621cfac0c3fc769b63dc5`。补全复用 `load_known` 的受管会话投影，仅补全入口使用非阻塞owner读取，普通恢复默认行为保持；物理/OMP必要身份校验亦只读且非阻塞。不建立新索引、不读原生正文或凭据，不启动宿主或授予控制许可。明确machine/local与tool，profile可选；完整SessionRef/profile/cwd仍有歧义时省略该裸ID。所有ID验证后一次输出NUL列表，坏记录不输出部分结果。

严格Schema校验新增有界512项、按规范JSON内容索引的进程内子树证明复用，退出进程即丢弃。无引用子树可以复用完整证明；含引用节点只复用元schema语法证明，原strict遍历仍按本次根解析引用。新父字段、未知关键词、变动内容、未访问的default/examples及坏引用目标继续验证；严格根失败不发布新缓存，没有磁盘缓存或对上游宿主的修改。

隔离证据：最初真实UID RED为20 failed / 245 passed，另一次sandboxUID失败不计产品结论；Schema复用各阶段分别取得拒绝/重复工作RED再GREEN。当前source的12个不重复受影响文件最终 **649 passed / 0 failed / 0 skipped**，覆盖补全/严格Schema与原恢复、实例、配置消费者；此前合并组648 passed / 1 failed为帮助测试惰性导入哨兵留给后续配置用例，修正测试导入隔离后同组全绿，生产源码未再变。未把早期402项与其它重叠组相加，也未重跑原14,166项全量快照。

真实zsh使用临时HOME/XDG和合成v2 owner元数据，由实际autoload补全函数调用仓库 `_complete`，9个场景通过：machine带/不带profile、带空格local、缺scope/tool及原生尾部不查询、无索引空、跨profile同ID不补全和显式profile消歧。CLI子进程使用benchmark CHILD_GUARD阻断写入/联网/宿主调用；元数据文件mode和SHA-256前后相同，子进程全部回收。这里只证明真实zsh函数至CLI/索引管道，未执行PTY Tab，也未重跑Agent或Herdr原生流程；既有Agent验收保持下文各自源码范围。

正式冷进程测量在固定单CPU亲和性的合成环境中进行，仅对子进程设置，不改变主进程、系统优先级或其它实例。当前source的同场景30次CLI全部退出0、NUL结果精确：p50 **0.746秒**、p95 **0.771秒**、max **0.772秒**，满足该场景1秒目标。这不是全部工具、1000记录或非固定运行环境的统一性能承诺；实际argv/条件及原始样本保存为私人证据。

超限历史保留：最初未固定CPU的p95为1.625秒，后续源码阶段为1.403秒、1.313秒；早期固定环境两轮30次仍分别为1.022秒、1.119秒，均不记通过。最终有限容量及语法/引用证明复用方案在上述固定环境重新取得30次通过证据，没有删除前次数据、扩大目标或跳过校验。元schema投影/引用证明经独立只读审查，未发现可达语义回归。负责原生验收的executor在交付首轮固定环境报告后遇模型容量不足，主代理接手最终复验，未将中断记为通过。

本轮仍在独立任务分支，main `45953f0` 与四个既有Pi锁修改保留；T125没有人工合入批准。任务当前进度统一以[tasks.md](tasks.md#当前范围与任务终态的含义)顶部摘要与逐项状态为准，格式段不重复硬编码计数，下面旧阶段数字保留其时间与来源范围。

## 2026-10-28：T141 持久恢复防重与 T142 并发清单兼容

当前生产来源摘要为 `86275882bdcd0a7cbc437a5cf4ee5332c3f4e919f8c72810a7a1735a51da8f55`。T141 在同范围、完整 SessionRef 的普通恢复入口核验历史请求并原子认领；新 CLI/coordinator/run 不能绕过未决请求。active/unknown、孤立 intent、旧版不完整 owner 关联及缺退出事实返回4，保留可信原 run 与同范围查询。只有旧 run 完整 idle 且请求保存 launched/退出码后才允许明确新请求，加载 unknown 本身不阻止后续恢复。不同会话或范围保留合法并行；不扩大外部 writer 保证。

owner 仅在短锁内读取严格快照，扫描及持久化请求时已释放其锁；请求锁保证唯一认领，固定 owner 目录句柄并重核根身份。合法 API 不复用 run ID，idle 是单调终态；晚到且缺快照 owner 的 intent 按未决拒绝。Pi 预检不授予派发资格，合作 claim 后仍重新认领；claim 首次 flock 的真实竞争映射为4。三个自有来源已同步 `locks/pi/session-control.json`，新 observer identity 为 `3a8f77f7ecb2c0642db3af45708877a968cda033be385c61e737f1c628a4c2da`；旧 observer 的历史准入保留。

T142 修复正式并发验收暴露的维护清单首次取锁竞争：Store 的 read/begin/append/complete 仅在首次锁获取前最多等待2秒，位置准备同时受原整批 ReadyDeadline 更早期限约束。取得锁后重核原意图/CAS，锁内不获取物理或 Domain 锁，不重放 body、fsync、宿主或信号。缺目录查询仍不创建，交接后的官方宿主没有时长上限。

| 隔离范围 | 实际证据 |
| --- | --- |
| T141 恢复请求、候选及 Pi guard 五文件 | 阶段执行183 passed；最后追加旧 owner/超长可信引用和非法引用9例，在修正后9 passed，192个唯一case已有通过证据，并非一次192项运行；最终针对性组45 passed与前述有重叠，不累加。 |
| 既有恢复、维护、位置与继续兼容八文件 | Pi 来源清单同步后481 passed；发生于T142之前。T142后的受影响维护和位置路径在下两行重新执行，不将旧全量当作当前执行。 |
| T142 新真实 flock 测试与完整既有维护文件 | 63 passed与190 passed，文件不重叠；覆盖等待、原CAS漂移、其它run合法尾部、相同run重复拒绝、两种预算耗尽零写、锁体异常零重放和缺目录。 |
| T142 位置/整批准备期限/清单与CLI五文件 | 298 passed / 4 skipped；4项为DSH/OMP参数下仅适用于Pi的辅助观察，不记作平台通过。 |
| 静态 help、位置条件、能力来源与公开检查四文件 | 318 passed；随后公开文档/相对链接另按最终写入检查。组间有重叠，不汇总为本轮全库结果。 |

原生进度：最终摘要的 OMP 18.12.6 / 完整锁 `490e6c90…` 双会话正式组已退出0；普通重复恢复返回4，原两宿主出生身份及会话历史保持；停止/实际更新/整批新标签页/再次停止更新/整批原 pane 均通过，共6次官方运行、7条受管记录（额外拒绝记录无宿主）。源码前后相同、无trace、输入0、加载unknown、继续not_sent；TTY、资源EX、原parent/pane与最终namespace回收均核实。Pi四组既有锁/profile的新来源正式复验全部通过，见下表。本轮未重新执行DSH原生组合，既有证据保持其来源范围。

| 当前源码正式组 | 完整锁前缀 / profile | 结果 |
| --- | --- | --- |
| OMP 双会话 | `490e6c90…` / omp-default | 6次官方运行；同SID活动重复恢复拒绝4，两个独立终端整批新标签页/原pane恢复通过。 |
| Pi 旧锁 Base | `62ac8348…` / pi-base | 单项完整3run流程通过。 |
| Pi 新锁 Base | `a68d9dcf…` / pi-base，显式footer/Cursor及provider | 单项完整3run流程通过。 |
| Pi 新锁 Pro | `a68d9dcf…` / pi-pro | 单项完整3run流程通过；作为普通profile，不含委派。 |
| Pi 旧锁 Pro | `62ac8348…` / pi-pro | 单项完整3run流程独立通过，不由Base推定。 |

合计5/5正式组、18次未经修改的官方运行，驱动均退出0且无trace；各组source前后均为上述当前摘要。Pi12个实际guard marker均为当前 `3a8f77…` 来源；原目录/历史、原parent/pane/终端、TTY与资源释放、重复拒绝、源码漂移和Herdr丢失保护均核实。全程输入0、加载unknown、继续not_sent；全部自建namespace已回收。main四个受保护Pi锁的SHA-256与原基线一致；精确argv、退出码、完整锁与逐文件来源摘要保存在私人证据，失败记录未覆盖。

失败历史完整保留：初始防重复RED为12失败及另一组9失败；Pi claim竞争错误码、旧 owner和超长可信run引用均有独立RED再GREEN。第一版跨元数据锁持有贯穿fsync，正式复验暴露OMP宿主绑定NB竞争；已改短owner快照。随后一次原位失败尚无新reservation，独立诊断定位到维护Store.read NB竞争，新增T142；所有未知请求均保留，没有重发。Pi源码修正后的首次兼容组6 failed / 475 passed由来源清单未同步触发，清单和精确能力已同步，481项重新通过。中间失败和诊断不冒充正式通过；最终OMP使用全新合成请求。

当前仍处任务分支，T125没有人工合入批准。main `45953f0` 与四个原有Pi锁修改保持原样，日常入口未换绑。任务已按上述证据更新为120/121，T141/T142完成；唯一待办T125仍需具体候选的人工批准、main整合验收与符合条件的清理。下文保留旧阶段来源与计数。

## 2026-10-28：收敛任务T139/T140验收完成

生产来源摘要为 `74543af7437c24d20c9a956a91fda544dffd133fbd0edb6e7ca2b4256b86663b`。位置恢复使用ControlDeadline的薄适配ReadyDeadline，默认30秒、显式1–300秒；明确目标后计算一次绝对期限，同批次的核验、Herdr/原位socket和bootstrap共用，不按项目或分段响应续期。期限内已发出的请求可能稍后完成，超时保留未知事实、后续不再派发，不撤回、不强杀、不重发；交接后的官方Agent没有任务时长上限。只有停止清单的位置恢复和maintenance restore的位置路径接受该选项，普通session/here/list拒绝显式传入。

共享预算后端的6个隔离文件为 **364 passed / 4 skipped**，CLI、交互、帮助与补全的5个隔离文件为 **3376 passed**；文件不重叠，合计 **3740 passed / 4 skipped / 0 failed**。覆盖累计等待、首次预检耗尽、到期后零新派发、原位socket分段响应、bootstrap原绝对期限、120秒payload和交接后宿主不受限；帮助的13个命名空间示例先RED再通过，并验证可解析和零业务读取。本次未重跑此前完整14,166个测试的全量快照，不把旧全量计作当前新执行。

原生复验使用未经修改的官方Pi 1.3.0、Pi Base完整锁 `62ac8348…` / runtime `d9701039…`、Node 24.14.0、Herdr 0.9.5，在断网/PID隔离、临时HOME/XDG及合成会话中，以实际 `--wait-seconds 300` 完成两个会话的停止、真实配置更新、整批新标签页恢复、再次停止/更新和整批原pane恢复，共6个新run。原session/cwd、独立终端、原parent/pane、TTY属性与原资源EX可取得性均核对；source drift返回5、重复返回4、Herdr丢失返回5。退出0且外层namespace已回收；输入0、load unknown、continue not_sent。其它五个工具/profile/锁组合沿此前明确的验收范围，本次未重复原生执行；不扩展平台、Bun、SSH或账号/模型支持承诺。

首次原生尝试被验收脚本误传参数名挡在parser，恢复请求未派发；保留失败记录，只修driver的实际CLI选项为 `--wait-seconds`，随后以全新合成会话/批次通过，未重发旧请求。早期沙箱属主限制单列，最终隔离组在真实UID环境通过，没有放宽属主校验。

任务表现为118/119，T139/T140按上述证据完成；T125人工批准、main整合验收及条件清理仍待执行。main保持原基线和四个既有Pi锁修改，日常入口未切换。下列内容是此前阶段证据，不能替代本轮来源及范围。

## 2026-10-27：交付源码的真实位置验收完成

本轮真实位置验收与完整隔离回归的生产来源摘要为 `4b1779e5f99374dc91493e016471b088567ae37d7c5ec659ee40ed9900bc9755`。私有候选仅位置准入表曾与公开源码不同；12 组正式验收通过后，已把 SHA-256 为 `0c2a8788e72739d4ff2b94607662a861ef039b05caaca403f4339d0c02106a21` 的 `pane_dispatch.py` 原样写回，并重新核对完整生产来源摘要与实际验收一致。未经修改的官方宿主和完整运行包仍由原后端核验，没有宿主补丁、私有加载接口或自动继续。

Linux、Herdr 0.9.5 / protocol 22、隔离 HOME/XDG 和合成会话下，最终 **12/12 组、34 个 run** 通过。所有正式组均无追踪、输入0字节、`load_confirmation=unknown`、`continue_status=not_sent`；TTY 属性、单次运行资源/物理与状态 EX 可取得性均核实，全部自建 namespace 已结束。

| 正式验证 | 结果 |
| --- | --- |
| DSH 固定完整锁（TUI 配方锁定 0.16.1） | 单项完整停止、实际更新、新标签页、原 pane、三次新 run、同原 session/cwd；通过 |
| Pi 1.3.0，候选 `62ac8348…` Base/Pro | 两档分别完成同一完整流程；Base 另以两个会话验证整批 `--all --new-tab` / `--all --original`、独立终端和六 run；通过 |
| Pi 1.3.0，main 保留 `a68d9dcf…` Base/Pro | 两档分别完成完整流程；Base 使用锁中精确 footer/Cursor 组合；main 公开锁仅只读输入，四个既有脏文件 SHA 未变；通过 |
| OMP 18.12.6 / Linux x64 完整锁 `490e6c90…` | 单项及两个会话整批完整流程均通过；严格核对官方 `--resume FILE`、原 cwd 和 UI 历史。实际受控退出143如实保留；通过 |
| Rotom Herdr V1/V2 普通新建入口 | DSH/Pi 各两入口，实际公开 work enter/open、新 pane 主进程为 resident、CLI manager 与官方 host 的准确父子/PTY 关系；公开 stop 后等待、TTY/EX；4/4通过。未用无SID的新启动冒充会话恢复验证 |

所有恢复流程均核对原 parent/pane/terminal、新 run、明确请求与原 session/cwd。重复恢复返回4；管理源码变化返回5且未派发，恢复原字节后新明确请求仍可执行；自行关闭 Herdr server 后原位拒绝5，保留停止记录及当前终端路径。批量两个 TUI 使用独立终端，不争 stdin。严格加载回执和自动继续不在交付范围；Pi Pro 在此为普通 profile，不含委派。

单实例组的 parked 基线使用两次采样、脚本等待间隔0.5秒：DSH RSS 33,968 kB，Pi 四组 34,188–34,912 kB，OMP 35,136 kB；各组 `utime + stime` 的 CPU ticks 增量均为0。没有保存实际采样时间戳，双实例与 work 入口也未采样，以上只记录该轮基线。Pi/OMP 版本分别为1.3.0/18.12.6，Node 24.14.0；DSH 的版本证据来自完整锁与上游 commit，未另作 SemVer 命令采样。

### 并发与收尾边界

实际验收推动了对应离线故障验证：首次 host/control 记账、停止快照与最终只读查询可等待原短元数据锁；写入、信号与恢复派发仍一次。OMP 各写事务只在首个 flock 前有界等待，release 复用原2秒预算；包验证/启动物理核验的两处关键读显式等短 SH，其它诊断读仍 NB。启动声明/anchor 选择和预留改为同一写事务，通用 reserve 的严格 revision CAS 没有放宽。进入 body 或提交/解锁后异常不重放。

驻留父进程活动期间只等待 child，不轮询 owner/Domain；退出后再按唯一出生身份和完整释放观察确认 parked。active 位置查询按 child/manager 出生身份只作候选，不能授予原位。V1 工作入口在 accepted 前保留最后核验的 caller，accepted 后不再要求父入口已经正常清理的 pending 标记。

### 隔离验证与当前整合状态

最终交付来源冻结的完整默认隔离测试为 **14,153 passed / 13 skipped / 0 failed**，共 **14,166** 个唯一测试，六个不重叠 tmpfs/断网分片全部退出0。全量结束时，638个源码与测试文件的 SHA-256 清单和工作树一致，生产来源摘要与上述12组原生验收一致。跳过项保持未验证，未计作通过。

稳定审查随后仅把 resume 帮助的“非TTY须完整 --batch 与 --run”明确为“非TTY单项恢复须完整 --batch 与 --run”，避免与整批 `--all` 的参数条件混淆。最终来源摘要为 `e9907a328ce9f922eb6ea51c48eaa71318f16c652df70a545d264f9643ff2830`；与上述全量/原生快照只有这处静态帮助文案不同，没有 parser、启动、锁或恢复逻辑变化。最终帮助、CLI 与补全专项复验为 **412 passed**，退出0；不将旧快照冒充最终完全相同的字节。

前一冻结候选的 **14,102 passed / 13 skipped** 保留为历史；宿主登记418、薄驻留364/4 skipped、V1入口210、停止最终查询269、Domain首锁467、OMP启动/退出216等受影响组也分别通过，但与最终全量有重叠，不相加。

早期测试环境 ENOSPC、错误祖先属主的 namespace、初始不完整夹具，以及曾复现的各锁竞争和旧脚本对 OMP 路径/143退出码的误判均保留历史。官方 addon 可再生缓存现仅挂专用 `natives` tmpfs，配置/会话与原始证据不覆盖。旧未知请求从未重放，环境不足不记通过。

任务清单收尾核对：17个历史替代项已逐项对应新方案实现与验收，未发现当前选定范围的行为缺口；另4个自动继续任务按已确定范围移除。21项保留原ID、描述和关闭原因，转为非执行历史记录，没有补勾为实现通过。当前有效清单为 **116/117**，唯一未勾为 T125；完整历史仍有138个ID。人工明确批准、main整合验收和符合条件的worktree清理完成前，不报告本轮全部收尾。该次只改任务终态、说明及链接，生产源码摘要不变。

候选仍在独立任务分支，main 基线为 `45953f0`，日常入口未切换。支持文档和任务表按最终验收收口；T125 人工合入审批与整合验收单独保留，不由本节推导合入授权。下列内容均为此前阶段历史，当前结果以本节和支持矩阵为准。


## 2026-10-27：位置实现与早期验收（历史阶段）

本轮在 `43c7c49` 之后实现生产薄驻留启动器、严格位置记录、原 pane 控制端点和 Herdr 新标签页交接。恢复只消费已停止并完成配置更新的公开 maintenance workflow；普通 `resume --session` 与旧独立 stop 快照不因此开放位置恢复。`resume --stopped --batch B --all --original|--new-tab` 可为每项创建独立请求，部分失败保留已派发事实并停止后续项目。当前真实 Herdr/官方宿主验收进行中，位置准入表仍为空；本节不声明这两个位置已交付。

父进程只保留 `InstanceWorkspace` 的轻量归属、受保护控制端点及原终端标识；完整 Workspace、凭据解析、运行包和单次租约留在短生命周期子进程。必须观察到本地 managed 运行的完整后代/资源退出才显示等待恢复。普通 shell `rotom run` 不进入驻留模式；SSH 不从相同运行包 identity 推定位置能力。管理代码或终端身份变化时拒绝原位恢复，保留批次并给出当前终端路径。实际交接仍为加载待确认，零自动继续。

隔离证据：记录 codec 98 passed；位置/批量/补全及目录完整性组 253 passed；新增本地/SSH 边界与驻留核心组 71 passed。核心交接及普通 work 回归组先运行 179 项，其中一条新增测试错误使用 `SessionError.exit_code` 而失败；断言改为实际公共字段 `code` 后，相关 71 项全部通过，另 108 项原运行已通过。组间重叠，不累加为全库结果。完整默认隔离回归已启动，结果尚未完成。

真实 Herdr 基础探针已核对 0.9.5 / API protocol 22 的公开结构化能力、同用户 Unix 端点、无前端 headless tab/PTY、独立终端和工作目录，以及候选 `rotom-work-shell` 的实际加载；探针没有启动 Agent。原生位置验收使用受保护私人候选，仅精确准入表与生产待验源码不同，不修改官方宿主、注入恢复后端或向 TUI 发送恢复文本。仅通过的组合才会原样加入发行准入表。

### 真实位置流程发现的停止收尾竞争

Pi 的首次新标签页恢复已实际启动，但再次停止时，owner 已完整退出，`close_stop` 在保存收尾之前遇到另一只读查询持有的短元数据锁，原非阻塞获取立即返回 Conflict，留下 protected 批次。诊断定位到 `run_owners._locked` 的 `BlockingIOError`，不是向已退出进程重发停止，也不是耗尽原 30 秒截止点。

修复让该收尾沿用最初 `ControlDeadline`，仅在首个收尾写入前等待原 owner 锁；持有物理 SH、state SH，再取得 owner，body 仍只执行一次。超期不写、写入或结果不确定不重试、不重发信号，不撤销未知 fence。真实临时 flock 的等待/过期/写后失败测试及相关停止回归 281 passed。修复后的官方位置流程正在无追踪复验，旧失败保留，不计作最终通过。

独立只读审查随后复现并修正驻留观察的另一窗口：单次子进程刚退出，配置更新先取得物理 EX 时，原观察 SH 的短竞争会被永久写成 unknown。现在仅真实 flock 竞争以 `LockBusy`（`Conflict` 子类）传递；父进程保留原 child/birth/退出事实，以 parking 等待下一次只读核验，普通身份、路径与未知写入错误仍失败保护。真实 EX/SH、一般错误及 DSH/OMP 生命周期观察组 122 passed。交接后配置/凭据/依赖/路由/路径异常已转为脱敏失败事实，六类异常及相关握手/驻留/work 回归 189 passed；延迟旧 run 请求在消费前另受当前 run 匹配检查，驻留组 66 passed。最终稳定审查按这些新字节复核。

完整默认回归的首次执行在临时磁盘耗尽后中断（702 passed、1 failed、58 errors，不能作为完整产品结论）；原始 root 只读挂载的后续尝试因命名空间祖先属主不受信任而终止。随后使用新根 tmpfs、真实 UID、断网及冻结源码/测试，先核验 CLI 组 106 passed，再启动 14,101 个唯一测试的六个不重叠分片。首轮完成 14,069 passed / 13 skipped / 19 failed：15 项为旧部署缺环境字段时只读位置诊断抛错，1 项为过时 help 断言，3 项为合成源码夹具仅复制旧固定清单、未包含完整管理包。诊断缺字段现保留 unknown、不影响原维护；帮助已按实际条件更新；篡改夹具复制完整来源后仍验证篡改拒绝。最终相关 CLI/help/补全 496 passed / 4 skipped，源码篡改/停止预览组 60 passed。新锁竞争修复另行验证，尚未把该首轮记为全库通过。保留环境失败历史，没有放宽属主保护或记为测试通过。真实 Pi 核心已观察同 session/cwd、三 run、原 pane/terminal/parent，仍待最终稳定全流程；Pro 控制通道缺失正在另行定位，不类推 Base 结果。

任务按证据更新为 112/138：新增机制与隔离验证 10 项已勾；T094/T137 原生验收和 T095/T138 准入发布仍未勾，T125 人工合入批准仍未勾。历史 17 个替代项和 4 个本轮范围外项不伪装成完成。下方位置提示修订节是此前阶段记录。


## 2026-10-27：位置范围、任务与当前提示核对

从候选 `121ab0a` 继续，仅修订当前 help、未开放位置的拒绝信息及规划一致性，没有启用驻留或新标签页。`run`/`agent run` 说明普通启动随 Agent 退出返回；`resume`/`maintenance restore` 说明当前终端不需 Herdr，以及原 pane 未来仅适用于 Rotom Herdr 新托管且逐工具已验收的实例。旧普通实例、直接官方 CLI、launcher/pane 丢失不保证原位；未开放位置仍返回 5，并给出同范围 `--here` 命令。

任务表保留全部旧 checkbox，17 个旧未完成项标明新方案替代，4 个自动继续项标为本轮范围外。原 pane 的 T085/T087–T095 保留待实现，并去除已替代的旧 T081/T082/T076 前置；新标签页新增 T135–T138。只有当前提示/规划同步 T134 完成，现为 102/138；T125 人工合入批准仍待处理。统一严格加载回执、原生 TUI 自动继续和 Pi Pro 委派不承诺，`pi-pro` 普通 profile 的维护恢复保留。

隔离验证：help/Herdr 提示/resume/停止清单/代理组 364 passed；普通 CLI 组 85 passed；公开文档检查测试 4 passed。新增 15 项提示边界测试包含静态 help 无业务 I/O、拒绝时 stdout 不变/精确范围命令和既有互斥检查。公开内容检查、变化的规格相对链接与任务编号/引用核对通过。上述不是全库重跑，也不产生新的 Herdr 或官方宿主原生验收。

Pi 的稳定父进程/同一 PTY 核心可行性探针另见[位置能力说明](../../docs/rotom-pane-capabilities.md#核心可行性证据与缺口)；它不代替生产驻留或三工具原位验收。以下官方 CLI 维护证据按原范围保留，不类推为新增位置能力。

## 2026-10-27：官方宿主贯穿公开 CLI 的补验

从候选 `47e1481` 继续，main 基线仍为 `45953f0`。以下使用未经修改的锁定官方宿主、Linux 原用户 UID、全新私人 HOME/XDG 和合成会话。运行阶段由 bubblewrap 隔离网络；DSH 的假模型 HTTP 服务在同一隔离网络的 loopback 内，不连接外部模型。没有注入恢复后端、替换生产启动器或修改原生包。原始 argv、退出码、锁、逐文件来源摘要和失败历史保存在私人任务记录。

三工具均通过公开 CLI 完成：启动 → 维护 plan/明确批准 stop → 已停止批次最新 plan/独立批准 execute → 实际配置更新 → `resume --stopped --list` → 精确 batch/run 当前终端恢复 → 独立停止新 run → 重复恢复拒绝。每次只有一个合成实例；旧 DSH 三选二和共享资源/失败场景的分项证据仍按原范围保留。

| 工具与组合 | 实际更新 | 原生结果 |
| --- | --- | --- |
| DSH，完整锁 `e4d56f…` | `terminal_images` 从 false 到 true，至少一项实际变更 | 初始及恢复宿主退出 0；同一原生 session 与 cwd，历史 `DONE_ONE` 可见，新 run；终端属性恢复；重复恢复返回 4；原 host 身份均退出。初始输入 28 字节创建合成历史，恢复输入 0 字节。 |
| Pi Base，候选锁 `62ac8348…` | thinking 从 medium 到 low | 生产公开扩展初始及恢复观察到精确 ID/cwd；两次退出 0，终端恢复，原历史保留、重复恢复 4、无活动 manager，恢复输入 0 字节。 |
| Pi Base，新锁 `a68d9dcf…` | 同上，保留 Cursor/footer 的精确锁选择 | 与上行同项通过。先在私人候选加入精确准入，再跑完整链路；其 `sessions.py` SHA-256 与本轮应用到任务分支的源码完全一致。 |
| Pi Pro，新锁 `a68d9dcf…` | 同上，保留 Pro 默认 footer 与协作配置 | 与 Base 同项独立通过；没有调用委派工具或模型，不将 Base 结果类推为 Pro 通过。 |
| OMP 18.12.6，完整锁 `490e6c90…` | 更换已声明主题，至少一项实际变更 | 使用公开 `resume --session` 启动已有合成会话，随后完整维护与 `--stopped` 恢复。两次 host 退出 143，manager 按原生码返回；原目录/历史可见、新 run、终端恢复、owner 全为 idle_confirmed、重复恢复 4、输入 0 字节。最终无追踪执行退出 0。 |

各工具仍记录 `load_confirmation=unknown`、`continue_status=not_sent`。TUI 中的历史与人工观察不升级为严格加载回执。DSH 的恢复使本地假模型请求从 2 次增加到 3 次，系统请求材料保留为宿主标题/辅助行为；不能称零模型请求或把它记为 Rotom 发送继续。Pi/OMP 本轮没有模型提示输入。

显式原生脚本分别为 `tests/manual/dsh_tool_workflow_native.py`、`pi_tool_workflow_native.py`、`omp_tool_workflow_native.py`，均要求 `--allow-host`，不进入默认 pytest。运行包准备经过正常安装器/后端及收据核验；OMP 的可再生缓存放在 namespace 的 tmpfs，防止重复二进制占满系统磁盘。新 Pi 两档正常 `npm ci --ignore-scripts`、离线闭包及脚本审核通过；官方 host tarball SRI 和每档 1,276 个归档文件字节匹配。

### OMP 真实验收发现与修复

原停止客户端轮询 `status` 时会短暂持有 owner 锁；OMP 已证明完整退出后的 `finish_owner` 若碰到该锁，原 NB 获取立即失败，保留 active 并阻断后续维护。真实诊断记录到 owner 的 `BlockingIOError`，随后退出阶段抛 Conflict，终端显示收尾未确认；信号已发送不等于停止完成。

修复只在退出写入前遇到真实 owner 锁竞争时，释放 Domain，最多等待 2 秒后按原顺序重取并重核。owner 仍以 NB 获取，成功后持续持有至 Domain 提交/同步/读回完成；任一写入或结果不确定都不重试。两个退出阶段的原 manager、完整释放观察、路径/资源/摘要和 unknown 保护保持严格校验。2 秒是锁竞争预算，不是整个持久化事务的执行时限。

针对性测试用真实临时 flock 复现旧获取路径：4 failed / 4 passed；修复后的新测试及 owner/release/cooperative 组为 202 passed。Pi 准入及 guard/观察/维护 CLI 组为 318 passed / 4 skipped。各组有重叠，不相加为全库结果。最终维护/停止历史受影响回归另记私人任务记录，未把旧 13,561 项结果冒充本轮全量重跑。

失败历史保留：测试 fixture 缺少模型容量/vision 字段、错误使用受管 `run --resume`、启动探针争 owner 锁、准备阶段 DNS/祖先归属限制、早期退出 helper 在 Domain 提交前释放 owner 的单测失败，以及临时磁盘耗尽。修正均经过对应复验。启动时控制服务未建立仍保留人工停止提示，不把无端点记录当可自动控制。

### main 的 Pi 锁兼容结论

main 的四个未提交 Pi 锁文件始终未修改或吸收到本分支。新锁完整 identity 为 `a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587`；本轮只给这组锁和当前 observer `e286d053…` 的 Linux/managed/here 组合新增精确交接条目，旧 `62ac8348…` 仍支持。新条目不开放严格加载、自动继续或其它位置。

新 Base 锁的选择为 footer 后 Cursor，且 Cursor 需要公开 cursor provider；默认仅 footer 的 Base 示例与该选择不同，会按既有规则拒绝 stale lock。核验用临时配置显式声明锁中的选择，没有暗改公共默认或真实机器配置。Pro 没有新增直接依赖，但间接闭包变化已独立安装并做原生验收。账号登录、真实模型/委派工具及其它平台不在本轮验收范围。

本节 supersedes 下方旧阶段“全 CLI 未验证”和“新 Pi 锁未准入”的状态；历史记录保留。main 整合仍需人工批准和整合验收。

## 以下为此前阶段记录

**2026-10-26 分支复审补验**：Pi 保护失败后的执行阻断已修复，覆盖打印、JSON、RPC 与 TUI；官方运行包分项与受影响隔离回归通过。候选尚未合入 main，合入须人工批准；完整官方 CLI 维护链路等未验证范围仍单独保留。详见[分支复审](branch-review.md)。

日期：2026-10-26。开发基线为 main `45953f09ce14908282b4af4c08101227e151ca3f`；
候选分支为 `feat/tool-maintenance-workflows-20261026`。提交 `2cda58d` 的候选实现和分组回归曾完成；后续复审发现的保护失败问题已修复并完成分项补验，详见分支复审。候选仍待人工审批，
本记录不表示 main 已具有候选能力。私人任务记录保存逐文件摘要、原始 argv、退出码和原始日志。

## 行为与兼容性

三工具沿用各自运行和部署保护，通过保存恢复清单、精确停止、独立批准普通 setup、
逐项当前终端恢复形成完整的显式维护流程。没有跨阶段写许可，没有自动继续输入。
以下边界已有实现和针对性回归，整库结果见下方单独状态：

- OMP host 更新复用 `owner_pending` 的 Domain/owner 双向摘要；共享运行包引用仍约束更新。
- Pi/OMP 控制端点置于既有 inbox 的 sidecar，保持旧 RunRecord reader 和 OMP 摘要兼容。
- 普通 setup 保留现有物理锁、运行 owner 和共享资源检查；新并发实例不会被自动加入停止集合。
- `lock` / `sync` 仅显式选择命名代理；不继承普通 run 的代理默认；窄签名后端保持兼容。
- 目标完整运行包没有恢复准入时，在维护停止前拒绝；更新批准前再次核验。独立停止和普通 setup 仍可用。
- 恢复绑定本次批准的部署摘要，在运行共享锁内重核；配置发生变化不会启动错误版本。
- cancel 先保存禁止后续阶段的事实；原停止未确定时保留 fence，返回 4，不重投信号。
- 所有会话头严格 UTF-8 解码。OMP 固定格式的 256 字节标题槽可跳过；标题不作为会话身份，正文不读取。
- help、交互选择、非 TTY 缺参、重复选择、旧停止批次和旧 OMP 查询均分别回归。

主目录已有四个 Pi 锁文件的未提交改动，完整 identity 为
`a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587`，
与本候选验收的完整组合不同。本轮未修改或吸收这些文件，也未给新组合补造恢复准入。
当前适配器的只读校验已接受该锁格式；独立普通启动/部署入口保留，但没有据此宣称真实日常部署已验收。若保留该锁用于维护，应先完成其单独验收。不能把本候选的测试结果
当作对主目录未提交组合的通过证明。

## 未修改的官方运行包

| 对象 | 本轮核验 |
| --- | --- |
| Pi 1.3.0 | 官方 tgz 的 SHA-512 SRI 与锁一致；安装目录中归档内 1276 个文件逐字节一致。 |
| OMP 18.12.6 | 固定提交 `45c35e40c46166dc726ccc52f5d27f40f2449f99`；使用官方 Linux x64 二进制，SHA-256 `85d9daf3a05fc76e8cd425ae1904eb576af8d21cc85fcf4690742626e07ccfa4` 与当前 asset 锁一致。 |
| Pi 自有控制来源（提交 `2cda58d` 阶段） | 三个来源与当时 `locks/pi/session-control.json` 相符，identity 为 `100331dd76bf2740304f7177ca1452660317484f674bb374a48fefae802f5817`。后续等号参数和失败阻断修正的来源 identity 与复验见分支复审。 |
| DSH | 沿用 main 的固定锁原生验收；本轮未重跑 DSH 原生测试。 |

OMP 二进制来自已准备的官方缓存；二进制匹配不表示缓存目录名代表当前完整配置 identity。
Pi/OMP 恢复准入仍绑定[维护指南](../../docs/tool-maintenance-workflows.md)列出的完整锁组合。
没有修改 vendor、缓存宿主源码、官方二进制或导入宿主私有接口。Pi 原生运行使用 Node v24.14.0，满足适配器的 Node v22.19.0 最低版本要求。

## 显式授权的原生验证

Linux、原用户 UID、隔离 HOME/XDG、合成会话；bubblewrap 隔离网络，未访问真实账号或会话。
所有模型标识和密钥值均为测试配置；没有发送模型请求。公开报告使用路径占位值；原始 argv
保存在私人证据内。下表的 RPC 请求是官方控制接口请求，不是模型提示词或终端继续输入。

| 验证 | 观察和退出码 |
| --- | --- |
| Pi 官方 RPC 精确 `--session FILE` | `get_state` 返回请求 ID；正常退出 0。缺失目标可创建新的内存会话 ID，仍退出 0，不能将原生成功当作精确恢复。 |
| Pi 生产公开控制扩展 | 实际初次 claim 和辅助会话观察一致；第二个登记运行争用同 ID 被拒绝；官方 `switch_session` 切换到精确新 ID 后新 helper 观察一致；原 pidfd SIGTERM 后 143。 |
| OMP 官方 RPC 精确 `--resume FILE` | 精确目标返回原 ID、退出 0；缺失目标拒绝、退出 1。 |
| OMP 原生 writer | 两进程可只读打开同 ID；第二进程首次写入通过原生逻辑改用新的 sibling ID，第一进程 ID 不变。原 writer 退出后可恢复原 ID 并写入；三个进程原 pidfd SIGTERM 后均 143。 |
| Pi 官方 TUI / PTY | 只读公开 `session_start` 观察到精确 ID、原 cwd；原生进入 raw mode；输入 0 字节；原 pidfd SIGTERM 后退出 0，终端属性恢复。 |
| OMP 官方 TUI / PTY | 同上；原 pidfd SIGTERM 后退出 143，终端属性恢复。 |

TUI 检查采用额外的自有只读公开观察扩展。Pi 生产 guard 在独立 RPC 检查中验证；
不能把这些分项结果说成一次使用真实官方宿主贯穿全部 Rotom CLI 的停止→setup→恢复测试。
全流程 CLI 的持久化、部署、批准与故障顺序由隔离测试验证，原生协议由上述分项验证。

关键原生 argv 模板（`FILE`、`SESSION_DIR`、`OBSERVER` 均为隔离环境路径）：

```text
node PI/dist/bundle/cli.js --mode rpc --session-dir SESSION_DIR --no-extensions --no-skills --no-prompt-templates --no-themes --no-mcp --no-approve --session FILE
omp --mode rpc --no-extensions --no-skills --provider openai --model gpt-4o --resume FILE
node PI/dist/bundle/cli.js --session-dir SESSION_DIR --no-extensions --no-skills --no-prompt-templates --no-themes --no-mcp --no-approve --session FILE --provider openai --model gpt-4o -e OBSERVER
omp --no-extensions --no-skills --resume FILE --provider openai --model gpt-4o -e OBSERVER
```

Pi guard 检查由生产 `prepare` 在第一条 argv 上追加受锁校验的公开扩展，并通过最小环境传递
控制上下文和继承租约 FD。helper 使用 Python `-I`，不继承 PYTHONPATH 或认证环境。

## 隔离回归与失败历史

默认 pytest 使用临时 HOME/XDG、阻断网络与假宿主；不能作为真实宿主证据。
各组有重叠，不能相加称为全库测试数。

| 范围 | 当前结果 |
| --- | --- |
| header 最终组，含 UTF-16/32 负例 | 78 passed；退出 0。 |
| Node 公开控制扩展阶段组（`2cda58d`） | 43 passed；退出 0；宿主和 helper 均为替身。最新失败阻断组为 71 passed，其中 28 条使用真实 Node 子进程执行自有扩展，仍不启动第三方宿主。 |
| Pi 观察 / guard / runtime 阶段组 | 250 passed；退出 0。后续部署绑定变更另跑受影响组。 |
| workflow / resume / runtime / CLI 最终组 | 353 passed / 4 skipped；退出 0；生产与测试摘要稳定。四项为 Pi 专属场景的非 Pi 参数跳过。 |
| 旧 CLI / footer 契约修复 | 99 passed；退出 0。 |
| 命令历史隔离 | 116 passed；退出 0；相对哨兵不依赖临时根路径格式。 |
| 整库分组阶段 | 首段 4629 passed / 8 skipped / 8 failed 后主动中断；四组依次为 2239 passed / 1 failed、2235 passed / 2 skipped / 3 failed、2239 passed、2233 passed / 2 skipped / 4 failed。原始失败记录保留。 |
| 后续完整文件复验 | 预览/部署 55 passed；OMP 实例 15 passed；恢复工厂 29 passed；所有分组阶段失败均已通过相应完整文件复验。 |

初轮隔离失败、错用沙箱假 Node 所得单文件结果、原生环境准备失败、Pi helper 的 stdlib
名称遮蔽错误和 OMP writer 冲突行为的错误预期均保留在私人证据中；后两项已分别修复并重跑。
审查发现的部署 TOCTOU、取消与停止收尾耦合、UTF-16/32 自动探测，以及 help epilog 被覆盖
均已修复，最终受影响组合已通过。测试替身自身的失败与生产缺陷分开记录。分组期间出现的旧工具准入预期、额外控制扩展与 UI 链排序、fake child hook，以及临时目录格式依赖均已更新并完整复验；没有修改生产代码来迁就旧断言。

提交 `2cda58d` 阶段的最终稳定收集共 **13,573** 个唯一测试节点。按首段、四个分组及受影响完整文件复验逐项对账，结果为 **13,561 passed / 12 skipped / 0 未解决失败 / 0 未覆盖**。重叠测试只计一次；5 个已被替换的旧工厂测试 ID 记录为替换，不冒称原 ID 重跑通过。首段另有 7 个通过的 subtest，不计入上述节点总数。这是分组及复验汇总，不是一次未中断的全绿运行。

12 个跳过项包括 7 个已退休 OMP 宿主补丁测试、1 个未提供可选锁定 Bun 材料的官方 SDK 测试，以及 4 个 Pi 专属测试在 DSH/OMP 参数下的跳过；均未计作通过。

严格加载回执、原 Herdr pane 恢复、自动继续及其它平台均未由本轮开放。
这些条件能力不是本轮分阶段维护流程的隐藏前置。main 整合保留为独立人工批准步骤。
