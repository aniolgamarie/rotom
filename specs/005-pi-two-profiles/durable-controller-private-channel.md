# Durable 初始化的原父子私有通道

2026-10-07，root 接续已接受的初始化授权、索引发布和 owner lifecycle，冻结传输与接收者职责的候选。五源只读证据9输入 receipt `3a09a428850ab671306df37c3b5e71b8f9f9707947c6e450f8d80cc462d968f6` 表明：普通 child gate 保存原 Popen，但当前 supervisor launcher 为临时文件加 subprocess.run；路径 RPC 与纯 OwnerReplyWindow 也没有提供本次专用组合。本稿不修改这些旧入口。尚未授权实现新 IO、启动 controller、Node 或 SDK；完整 current Full producer／issuer principal 和闭合源仍为前置 gate。

## 原创建者和 fd 所有权

选择 Linux 两条 `os.pipe2(O_CLOEXEC | O_NONBLOCK)`，一条 issuer→controller，一条 controller→issuer；不使用 socket wrapper、账户路径 listener、临时文件或 caller 交来的端点。原 issuer 在自身私有初始化记录内登记四个 raw fd、原 syscall、读写方向、物理 fstat 和来源函数。完整取得后 child 只继承自己的读／写两端；parent 保留相反两端。pipe inode／数字／token只补足检查，不能单独证明原OFD或创建者。

取得端点后立即登记，第二次pipe2之前必须已登记第一次返回的两端；登记分配失败也须对本次已得但未登记的每个自有fd各close-only尝试一次，再继续其他原资源清理。取得、登记、交接错误不另造pipe或重试本次创建。这里检查自有代码取得原API返回值以后的所有权，不声称默认fault fake证明CPython/kernel在任意内部OOM下绝不泄漏。

四端须两两不同且最终>=4。若新创建者得到自己的低号fd，用保存的 `fcntl(F_DUPFD_CLOEXEC,4)` 复制到高号，立即登记新rawfd及同方向／原source，确认后永久退休旧rawfd、close-only一次。失败继续清理已知自有资源；不覆盖或关闭parent已有未知3。全程不创建socket／file wrapper，不让自动destructor和rawregistry同时持一个descriptor的关闭责任。controller的3预留与parent自己新得的低号pipe不是同一对象。

原 issuer 只能用已核正式 Full 的固定 Python interpreter／controller script／显式闭合源，固定 `-I -S -B` 和 `--bootstrap-read-fd R --bootstrap-write-fd W` 参数。数字不是secret，两个高号和方向不由client提供。固定环境不继承Python loader、账号或agent capability；`close_fds=True`、`pass_fds`恰为本次child高号两端。index／storage fd、manager token、父端、其他lease不继承。stdin和stdout设DEVNULL；stderr是该Popen新建的有界观测pipe，不能当协议或授权。实际interpreter/source/runtime producer仍待资格，不接受任意Python路径加摘要。

## 父侧创建、原pidfd和私有handoff

父manager主线程在本实例初始化且没有启动该controller之前，使用保存的原 `signal.signal(SIGCHLD,SIG_DFL)` 建立本actor的disposition。没有本controller的SIGCHLD reaper／SA_NOCLDWAIT，也不交普通childregistry、Popen context／poll／wait／communicate、waitpid(-1)或第三方waiter；闭合manager源码与实际Python/kernel资格必须证明此约束，不能借用子controller管理Node的前提。条件不成立即拒绝这条路径，不通过新lookup wirePID补齐。

主线程先创建并登记原四端、arm唯一slot回复窗口、消费本次controller launch状态，再调用保存的原Popen一次。正常返回后保存原child／PID／方法／receiver／stderr，在任何可能reap的调用之前立即用原pidfd_open取得held child，并核真实birth／UID、原pipe和来源。绑定完成前零read；已经排入原reply pipe的slot仅在绑定后检查。Popen返回后parent永久退休并close-only关闭自己的两条child端副本，避免自己保留writer而伪装EOF；原父端和heldpidfd仍保存。

主线程只负责上述短创建／绑定与handoff，不在普通编辑的共享主循环里执行index发布／fsync或等待整段初始化。通过同一私有记录的单次handoff，把原child／端点／pidfd／窗口和source引用交给唯一受限、非daemon初始化event-loop owner；不是把可重建DTO／fd整数列表发给任意callback。handoff之前只有原主线程可操作，之后原主线程永久失去该job的read／send／close／wait权限；不产生两个IO所有者。实际主线程dispatcher／私有job注册、quota／handoff及源验证API仍须冻结，不声称现有manager已经实现。只有handoff完整成功才读slot、发offer或消费业务grant，index IO由该唯一owner负责。

Popen、pidfd、birth绑定或handoff失败，controller launch仍已消耗；零offer／grant消费／持久目录／Node，不再次Popen。主线程继续持有未交接的原对象，按held-pidfd的实际wait／unknown监督；无合格原pidfd不按PID signal，关闭原pipe也不是child已退出。已启动controller此时最多预留自己3并等待原通道。未成功handoff的source/IO处于本地已静止时才能清理自有pipe；未取得真实退出不能合成成功或退款。

controller在专用入口主线程操作本通道。Python内部启动／import不在“零文件IO”保证内；自有入口先用原os.fstat检查自己3，仅EBADF时独占打开并保存自己的 `/dev/null` 预留3，未知已占用3就拒绝且不关闭它。预留成功前不做自有source/path/storage/index IO、不起线程或SDK。随后核继承的两高号为原FIFO、方向分别read-only／write-only且非阻塞，设CLOEXEC，保存原syscall；不因合法metadata产生issuer。此时只可读固定自身源及发送slot，零持久目录创建、零Node。

原pipe write还必须分配SIGPIPE前提：[Python signal公共契约](https://docs.python.org/3.11/library/signal.html#general-rules)说明Python默认忽略SIGPIPE，但这不是当前actor的自动证明。parent在setup及每个send窗口用原getsignal核SIGPIPE仍为SIG_IGN，不能在worker线程或共享manager中偷偷改全局handler；失败零新send。专用controller在主线程、首次pipe write之前明确设置SIG_IGN，捕获并核其来源。实际闭合源不能在write间隙改此disposition；当前检查不是防任意同UID改内存的原子屏障。[Linux pipe契约](https://man7.org/linux/man-pages/man7/pipe.7.html)说明reader全部关闭会触发SIGPIPE，忽略后write报告EPIPE；不把EPIPE当对端已退出的证明。[os.pipe2公共API](https://docs.python.org/3.11/library/os.html#os.pipe2)用于原始端点和创建flags，实际继承／方向／CLOEXEC另须原生资格。

## 双方私有阶段

初始化 frame 与 Node 五消息协议分开。两进程均为本仓库 Python；Node 继续只用既有 owner-message codec 和原3，不得到初始化端点或 token。下列是阶段接口；完整消息字段、纯 codec 和文件包必须下一包另冻，当前不把表格直接当可执行 schema。

| 原方向／阶段 | 发送前和接收后的必要条件 |
|---|---|
| controller → issuer：slot | 仅原 controller 已预留自己的3，回报独立 process／slot 元数据；parent 逐字段核原 Popen／held pidfd／observer，不从消息 pid 取得 child 权限。slot 本身不能授予目录或 fresh storage。 |
| issuer → controller：offer | 仅原签发者的私有 draft／当前正式 Full 引用；固定 context、一次 token 和原 source 描述只走原端点，不进 argv／env／文件／日志。controller 可捕获预备数据，尚无创建许可。 |
| controller → issuer：offer-ack | 本次原 context 和 token 的有界匹配；只确认原接收者准备完成。parent 原 one-shot 状态未消费之前仍零控制锚／storage。 |
| issuer → controller：fresh-storage | slot／offer 已明确确认；parent 消费同一原 grant，最后 current／policy／取消核通过，reserved 索引已取得完整持久回执后，才在首 send 前消费唯一 fresh 发送状态。命令绑定本次 token／原 reservation／完整 reserved record。 |
| controller → issuer：acquired | controller 在原等候阶段核完整 fresh 命令和自己的来源／期限／取消，不自行新选路径；只创建首次排他 storage，持原 EX 锁、dup 原预留3、持久 acquired 后回报独立实际 storage identity。parent 原窗口匹配后才构造 register-storage 后继。 |
| issuer → controller：registered；controller → issuer：registered-ack | 原 registered 索引完整持久回执后，仅发送并确认同一 metadata；controller 一直持 storage，仍零 Node。普通 reader、EOF 或此前 ACK 不能确认 parent 已 close index 锁。 |
| issuer → controller：release；controller → issuer：release-ack | 原 index 写者永久退役、IO 静止、明确 close-only 回执及最后 current/source 核之后，parent 消费一次 release 发送状态。controller 完整匹配本次原 reservation／registered 与自己的等待阶段，核自己的原 storage/3、source／取消／期限，才消费一次 Node launch。ACK只确认阶段事实，不能代替 Node hello／bound 或 DB grant。 |

parent 不从 slot／offer-ack／acquired metadata 重建原 grant，controller 不从另一组 pipe、ordinary worker、同 UID 字段或 public DTO 获得初始化许可。trusted adapter／原 issuer 仍须真实实现；本通道选择没有补齐确认或 current Full 来源。token 在 grant 消费后仅为原会话匹配秘密，不能恢复可用状态；取消、EOF、超时、关闭或错误永久退役其未用入口，不能把迟到的 matching token 当新授权。

## 单线程、有界 IO 和回执

每个job的两父端只有一个handoff后的初始化event-loop owner，禁止daemon reader/writer、fdopen／makefile缓冲和跨线程并发IO。manager其他线程只向有界取消队列投递请求，不直接close／send／wait／换窗口；实际队列、quota、活性与source属于后续接口。controller无后台IO producer。最后原raw操作返回、owner操作全退出并永久退休入口之后才有明确local IO quiescence，不用线程看起来空闲作证明。

index fsync等同步调用可能阻塞且不能由monotonic deadline证明已经停止；等待期间原owner仍持协调锁并禁止其他job写同一索引，不能外部close fd或finally释放。普通编辑和只读查询不等待此初始化job。初始化quota包含starting和unknown，不清计数后另开无限线程／新ID；当前无法静止的job保留原保护和明确未知，实际停机／维护另走已授权边界。非daemon线程是持有链的一部分，不用自动daemon退出替代producer静止。

使用 4BE＋单 UTF-8 JSON 的原 framing 规则。初始化帧 payload 上限候选为65536B，因为完整 registration 的原上界32768B、路径最多4096字符，4096B的 Node 元数据帧不适用于初始化 context；完整 offer schema 必须验证最坏 encoded 大小，不能直接允许任意64KiB字段。严格拒绝未知键、重复键、非 canonical 数字、非 finite／surrogate 和过深输入。cap 在分配 payload／解码之前检查；每窗口最多一帧和一字节尾数据探测，不缓存下一阶段。最大累计65541B。所有秘密帧只存在本次有界内存；错误只用固定自有码，不携原 JSON／foreign exception 链或 token 摘要。

唯一 sender 用保存的原 os.write，处理 short write／EINTR／EAGAIN、0、broken pipe 和可信绝对 monotonic deadline；offset 到完整 frame 长度且最后原 source/context 核通过后，保存发送回执。不重发已可能发送的业务阶段。65536B可超过PIPE_BUF，不声称整帧原子写；每方向唯一writer与完整 framing负责分片，没有多writer交错或按write次数推断一帧。raw pipe 无用户态缓冲，故不存在额外 stream.flush；“完整 send”只说明整帧已被本机 pipe 接受，不证明 child 接收或持久动作完成。原设计中的完整 send／flush条件在此具体化为 raw 完整发送且无未提交的本地 buffer，不能用此名称扩大到 peer／内核／介质证明。

接收窗口必须在首个可能触发回复的 send 前 arm。早 ACK 只保存私有有界 candidate，等本次 raw 完整 send 和 postpure 成功后才报告明确发送确认；不能把 parent 的 postpure／flush 事实当 child 完整收到命令之前必须先观察到的条件。原os.read取得的分片进入本窗口，空bytes为EOF；坏 header、溢出、尾帧、错阶段或全文不匹配永久失败。关闭窗口期间读到 bytes 不供下一窗口；未知将来迟到数据不能由 peek／某次无数据推断不存在。状态、全文和原双向端点共同约束；具体窗口类须与纯 codec 一起审查，不能泛化 OwnerReplyWindow 的4096B限制。

## 故障与描述符关闭

在 first fresh send 前失败，controller 只拥有预留3／双向pipe，没有storage。fresh 一旦可能交付，可能已有原唯一storage与锁；parent不能删除、换ID、补发或按未收到acquired推断未创建。registered未知、index close未知或 first release send前失败，零Node。release一旦可能交付，即使parent完整send／ACK／最后核失败，controller仍可能已合法启动唯一Node；保存launch unknown，零第二launch／重发／新ID／DB授予。

parent EOF／终止只关闭新入口，不当 controller／Node／storage已停止的回执。controller 对自己原Node沿既有held-pidfd／TERM2s／KILL2s／unknown-held处理；自己的原storage/3保护与初始化pipe关闭是不同职责，不套finally无条件释放storage。尚未消费release的controller不因EOF启动Node。已消费后的本次零SDK Node可按原生命周期停止，但退出未知时controller继续保留保护，不能为进程退出而强清最后锁。

每个自有pipe／pidfd只由其原owner close-only一次；关闭之前先永久退休该对象可用状态，关闭异常不retry可能已复用的rawfd，其他自有资源继续各尝试一次。pipe关闭不涉及LOCK_UN。未知child期间可以关闭已静止初始化端点，但不得把端点关闭receipt冒充storage释放或物理退出。stderr仅有固定上界的本次私有观测，不能把可能秘密内容放通用错误；满界停止新入口并沿原child监督，禁止无界积累。

## 默认与原生验收

后续默认使用自有假pipe／Popen／pidfd／时钟／source和临时自有目录，原grant构造仅隔离测试切点，生产固定真实producer；不运行第三方宿主、信号、Node或SDK。直接断言两个正确方向高号继承且无index/token/env泄漏、未知3不关闭、资源登记失败各自一次cleanup、原Popen／heldpidfd和端点绑定且handoff前零read、每阶段仅一次发送、早ACK不补send、short send及EOF／迟到／错窗口、父actor SIGCHLD/no-reaper与SIGPIPE不符零launch／send、handoff失败原主线程仍为唯一owner、fsync阻塞时编辑不等待且原锁仍持、阶段前失败零持久IO、可能fresh后原ID保留、metadata ACK后零launch。fake controller必须实际消费完整release并launch一次，再模拟parent lostACK，断言launch unknown且零第二次；不能以 inert fake 把它伪装为零Node。

实际 Python／controller/pipe2/CLOEXEC/fd3/锁/pidfd/source 闭包组合须独立准备和明确授权，当前旧FD6／Harness8不覆盖此组合，d61799三场已按精确授权执行验收并闭合，其授权不覆盖此新组合。设计审查通过仅关闭传输路线与因果职责；完整 pure schema／原currentFull／issuer principal／实际 Python来源／源安装角色、bootstrap producer、主线程dispatcher／原对象handoff／quota与具体 event loop 和唯一写入范围仍须冻结，不能先用permissive fake授权索引IO或产品。正式7/100、全部产品gate、严格计量前AUTO OFF保持。
