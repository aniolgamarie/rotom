# Pi 权限与工作根登记

## 现代候选的入口覆盖状态

以下是2026-10-11的当前实现与分层证据。独立临时实例已有正常安装和真实CLI/SDK/TUI合成验证；用户默认入口未切换，完整产品沙箱验收尚未通过。

| 入口 | 当前接线与限制 |
|---|---|
| 模型read/write/edit/rename/ls/find/grep | 自有准入、一次许可与受管文件执行已接线；确定性政策不需UI，必须人工项无UI则阻塞。真实Host/socket/SDK十二工具及正式CLI默认deny/显式read-write-edit已有分层证据，真实用户会话与最终组合另验 |
| 模型Bash/editor | 七个文件工具之外，仅显式声明`external_tools.shell`时注册受管Bash；自有UI准入、监督执行、输出/取消已有离线组合。默认父侧已按显式Shell选择接入共享账本/后端预检，正式运行包与实际SDK执行仍未验，editor未注册；`noTools: "all"`继续关闭默认工具 |
| TUI `!`/`!!`、RPC `bash` | 独立于模型工具选择。现通过公开`user_bash`事件返回固定异常`PI_COMMAND_ADMISSION_UNAVAILABLE`；离线反例及reload检查已通过，尚未做真实前端验收 |
| 原生MCP/Code Mode | 同一准入账本、精确服务/工具白名单；所选服务默认断开，经TUI `/mcp` manager会话内Enable。实际CLI/Host/socket/SDK/PTY的HTTP none/bearer与受监督stdio合成服务均已观察查询、资源、内层错误与原终止收据；stdio稳定差量复核已接受。RPC没有stock Enable菜单，OAuth/经典SSE尚未接通，真实服务/账号与最终组合另验 |
| RPC `export_html`、TUI `/export`/`/share`等前端操作 | 自有公开session facade固定拒绝HTML/JSONL导出；TUI公开editor提交接缝关闭export/share/bug/debug/copy，未获准的editor/clipboard/copy快捷键和SGR鼠标输入关闭。最后默认176及官方SDK组件正反已通过；正式CLI/实际TUI与所有转换窗口仍另验，T037未完成 |
| 扩展直接IO/进程、Worker/Durable | 同进程已锁定扩展属于信任前提；公开工具包装不能隔离其任意IO。高级现代入口和整进程边界仍未验收 |

现代TUI候选暂只支持键盘输入。两个公开导出方法通过自有闭合session视图拒绝，不改官方对象；其余选定公开方法保留原receiver和重新绑定身份。公开editor factory接收stock onSubmit回调后先检查受限制命令，不能通过share内部helper绕过导出拒绝。SDK会吞扩展错误，自有TUI bind/reload还须核实际editor/listener安装与当前native session ID，失败固定拒绝。shutdown期间保留输入过滤器，不能在后续异步handler仍等待时提前解除；最终176默认和有限SDK组件证据不代替实际终端/转换窗口或整进程资格。全局debug热键和其他原生直接IO仍在T037后续覆盖范围。

`user_bash`保护使用自有inline扩展，不改SDK对象或上游实现。固定Pi1.0.1的TUI在该事件失败后不退回本地执行，RPC将异常交给其错误响应路径；这是固定发行物源码依据，不能替代原生观察。所选扩展增加`user_bash`处理器或换宿主时须重新验证事件顺序与覆盖，不能外推为抵抗恶意扩展的保护。

现代MCP从已选择的registry服务与机器绑定生成`native_mcp`，不重新选择旧`pi-mcp`/subagents包，也不发现全局或项目MCP配置。`agent_options.mcp.allowed_tools`必须逐服务声明原始工具名；空列表只允许资源入口，通配、规范化冲突或无法无歧义映射的工具名拒绝。TUI `/mcp` manager启用只改变当前会话，下一会话仍默认断开；固定SDK的RPC仅提供状态及有限认证操作，不能通过`ui.select`伪造stock Enable。Code Mode关闭模型目录能力，MCP/文件/Shell嵌套调用分别消费自身许可；内层失败保持外层`isError`。

[真实MCP组合证据](../specs/005-pi-two-profiles/native-base-mcp-product-probe.md)分别保存两项HTTP服务与一项stdio服务的独立身份。HTTP原工具flags为F/F/F/T/T，stdio为F/T/F；实际服务关闭只有原lease、出生身份、完整capture和终止证明齐全才回收。现代固定命令/stdio使用所选sealed独立bwrap并持FD exec；系统旧bwrap不作为其回退。收据位置由已授予的Supervisor endpoint派生状态根，不能从instanceRoot或模型参数拼接。两个探针早期未知Host记录仍保留，不能把新实例protected0称作所有旧状态已恢复。

MCP每调用先准备固定服务/动作/参数，在原账本签发并消费一次许可，然后不可逆标记`sending`才调用服务。派发或完成回执丢失不重发，不发布未经对账的成功结果；取消、截止或上下文失效后拒绝迟到结果。远端副作用可能已发生，本地取消不能证明远端事务回滚或服务已经停止；本地stdio进程终止另以监督租约的真实证明为准。Streamable HTTP使用受管路线及原fetch，关闭默认认证回退和重连；OAuth、经典SSE、sampling/apps/elicitation尚未完成的组合明确拒绝，不能作为可用支持声明。

日常可组合Shell仍是R05/T033的必需目标：用户无需预登记每种组合，固定命令不能成为唯一开发通道。内部准备器保留私有多行脚本并绑定选定Shell、cwd、根、网络和可执行身份。Shell桥现已绑定实际工作区，消费一次许可后才分配独立执行租约和所需Writer；回执丢失保持unknown，只读定位原分配，不重试或释放保护。模型工具和默认宿主现已按显式Shell配置构造共享准入桥；原helper收据、实际字节和完整挂载计划经过父侧预检。默认组合24项替身测试通过，实际正式runtime/SDK/系统挂载树与产品执行仍未验。

文件与Shell共用固定准入流程，Shell确认框显示捕获后的确切脚本、cwd、读写根和超时；控制字符转义。会话切换/退出同步关闭两个控制器，等待各自已发清理，不因另一项清理失败提前返回。Shell执行只引用已消费operation，不再传脚本；启动回执丢失只读对账，取消需实际终止证明，RPC等待越过截止时间也不能报成功。`inspect/reconcile`返回持久的`spawn_committed`；只有明确未提交的分配才可显式abort，未知启动继续保护Writer。

工具复用公开SDK的定义，执行与输出由自有组件提供；不调用SDK的Bash执行函数，因为后者超过输出阈值会自行写临时日志且无公开目录选项。流式和最终展示按监督者全局事件序列保留最多8192 UTF-8字节的尾部，包含截断提示；stdout/stderr的私密留存仍各自有界。无事件丢失时，实时两路的有限前缀字节数、散列和溢出标志还必须与最终capture收据一致。有事件丢失时只展示已观察顺序并明确截断，不能据此重建完整全局日志。退出码、最终输出内容及整个执行范围终止证据分别核对；capture完成不释放Writer。默认测试不代替真实前端或用户体验验收。

产品Shell启动由可信父进程一次取走已消费许可的私密脚本，在启动前准备密封脚本、来源、过滤器和遮罩FD；产品worker不领取监督RPC凭据、不经RPC取回正文。正文及其散列不进入持久操作记录。消费后会话变化仍依赖前端明确退役，取消不等于进程已终止。FD固定inode，不冻结目录树或普通可执行文件内容；失败后不恢复输入或重发许可。

当前证据包含真实临时租约存储、目录FD和Linux memfd；进程创建及最终exec仍是明确替身。私有worker、固定argv、FD交接、受信启动路由和超时取消已有组件实现，真实helper、输出及后代终止尚待运行验收。固定bwrap的FD挂载会递归包含子挂载，必须另验别名、嵌套Git和deny覆盖；断网命名空间也不能单独证明Unix socket路径被隔离。阶段默认人工确认不代替R11最终自动策略。

新增的内部挂载编译器按底层文件系统位置检查bind别名，保留策略只读路径，并生成Git/deny遮罩；不接受缺失遮罩目标，不自动创建业务文件。源内子挂载、无法安全表示的硬链接/特殊文件或扫描变化会拒绝整个计划。另有固定Linux x86_64系统调用过滤器生成器，其测试通过独立字节码解释器检查网络和namespace入口。两者都尚未接入实际helper；目录扫描不会冻结文件树，计划成功也不表示沙箱可启动或隔离已验收。

内部Shell启动链使用每操作独立的PID命名空间。父侧FD作用域覆盖命令绑定落盘、starting提交、就绪握手、进程登记、running持久化、Writer激活和最终G放行。放行前再次核验原操作、完整分配、grant generation、父会话、配置/运行身份、截止时间及来源。密封凭证绑定这些授权字段、nonce和worker出生身份；授权摘要用于变化检测，不能自行签发许可。

外层可信引导从空根构造，只包含已批准来源、只读运行包/解释器依赖及私有HOME/tmp。来源为外层专用FD副本，使用固定helper的`--bind-fd`/`--ro-bind-fd`完成挂载后身份核验，外层消费副本，内层保留原FD。普通`--bind /proc/self/fd/N`仍会解析为路径再打开，不能代替这项核验。PID1 worker接到G后按父侧UID投影核验原FD，以FD直接exec内层完整隔离helper，不重开来源或更换租约身份。最终helper环境为空，脚本入口仅保留显式环境与FD。

运行时限从首次构造启动描述计算，重试不延长。准备或命令落盘失败仍保留allocating，只有显式abort可以释放未提交分配；starting已提交后的失败保持保护。若running已经落盘而最终放行失败，清理闸门和进程句柄也不会伪造租约回收。既有poll必须确认整个登记范围终止并完成输出收集，才释放Writer。默认宿主现已注入仓库自有Shell factory与helper/计划预检；这项默认代码接线不证明真实helper执行或整体产品可用。直接用户命令入口继续拒绝。

现代Base源码清单显式选择Shell入口及十三个自有Shell模块，包含handoff、start、identity和namespace info读取器。启动固定`-I -B -S`，bootstrap只加入已选只读源码与依赖目录，不处理环境导入路径或`.pth`。裁剪包导入、缺传递依赖拒绝、逐文件0600收据和真实临时租约/FD的故障矩阵已有离线证据。产品父侧启动、helper执行及完整用户场景的组合仍需单独原生验收。

2026-10-05 的 [Linux helper 探针](../specs/005-pi-two-profiles/native-shell-probe.md) 已在当前Linux完成三项原生验证。实测单UID映射使系统root属主显示为overflow UID；现在由可信父侧保持原属主检查、固定来源FD，再按父侧独立读取的映射交接给已登记worker，子侧不重开来源或重编译计划。不可遍历系统目录和特殊对象所在子树显式遮罩，工作区错误仍拒绝。边界19项为真、错误helper身份拒绝、后台后代108ms内完整停止；默认回归842项通过。此结果只覆盖固定组件场景：产品操作/租约/Writer与运行包收据已有后续离线接线，前端输出与取消及完整组合仍须原生验收，Base/Full尚未宣布可用；通用属主白名单没有加入overflow UID。

用户意图也需独立处理。Pi1.0.1公开`input.source`区分interactive/rpc/extension，但不提供贯穿变换、排队与后续工具调用的关联ID；内容比较、时间邻近或随机确认ID都不能冒充原始输入关联。当前UI确认可以授权眼前的文件或Shell操作，尚不能作为移除确认、自动审批或恢复旧许可的依据。

## 工作根登记

`./agentcfg workspace register --path PATH` 显式登记当前用户已有的非 Git 目录。
`workspace inspect --path PATH` 查询最近登记的物理祖先，`workspace list` 列出登记。
三项支持 `--format auto|human|json`，不接受 `--machine`、`--local` 或 `--profile`；无需本地配置或凭据。

账户锚由 OS passwd 的账户 home 定位，环境 `HOME`、XDG 与 profile 不改变它。
协调目录为 `.agentcfg-workspaces`（0700），登记文件为 `registry.json`（0600）。
查询不创建目录或文件。每次操作先锁定账户目录 fd；锁繁忙、不支持、路径不安全、
锚身份改变或登记损坏均返回冲突（退出码 4）。登记不会创建业务目录或初始化 Git。

根身份绑定协调锚和目录 dev/inode/uid。可核验的符号链接别名复用同一登记；
父子目录可分别登记，查询子目录按实际祖先身份选择最近登记。
任一祖先存在 `.git` 的目录、账户控制目录及覆盖它的祖先或其后代不能作为非 Git 根。

只读观察包含 `record` 与 `status`：`current`、`missing` 或 `identity-changed`。
未命中为 `not-registered`。失联和替换的记录保留诊断线索，登记不会自动重绑、删除或恢复。
这些记录不阻塞无关根的新登记；再次登记匹配的失联或替换根仍拒绝。
首次登记允许账户 home 内的其他业务子目录，但不允许覆盖未来协调目录的账户目录或其祖先。
修改返回对象不会修改持久记录。

登记与 `current` 观察均不授予 Writer、工具或执行许可。当前工作分支已将已登记根接入
WorkspaceLeases、同一 ExecutionStore 和账户 claim：父子登记根，以及登记根内的 Git 子根，
按物理覆盖范围互斥；同一分配可覆盖多个重叠根。无关根可分别持有写租约。
非 Git 的局部租约位于账户锚的 `workspace-leases/<rootId>/`，OpenSpec 所有权记录位于
`project-metadata/<rootId>/`，不在业务目录建立 `.git` 或另一套执行队列。

普通文件、已绑定固定命令及仓库自有文件快照保留通用语义；快照同时绑定登记身份。
需要 Git/common-dir 的审查、原生根映射、linked-worktree 委派和 Task Keeper 工作树流程
保持 Git 专属，不把缺少 Git 的情况伪装为成功。原生 Codex 的非 Git 路线仍待专门准入设计。
已登记根被替换、失联或后来出现 Git 标记时拒绝自动转换，保留诊断和恢复边界。

上述接入已有 312 项默认隔离测试、12 项 Git 和 12 项非 Git 独立进程检查通过。
非 Git 检查使用自有 Python worker、不同临时 HOME 和同一账户锚，在 bwrap 私有 `/tmp`
内登记真实非 Git 根；两个进程完成识别后等待同一信号，同时竞争时仅一个取得预留。
它也检查无关根同时预留、别名、根替换，以及预留后退出未回执仍保持保护。
这些检查覆盖准入和预留状态；旧实例迁移门槛、受限进程对协调目录的保护、完整终止恢复
及产品真实入口尚未闭合，因此不构成正式 Writer 支持或产品验收通过。
