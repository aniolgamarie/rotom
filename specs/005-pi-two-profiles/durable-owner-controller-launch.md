# 专用 owner controller 首次启动与关闭：候选接口

2026-10-06，root 在已接受的原锁范围、fd6 限定实测和纯五消息 codec 基础上冻结下一包的目标。本文是待独立审查的候选，不据此运行 Node 或签发持锁／开库资格。首包只处理可信专用 controller 与零 SDK bootstrap 的首次创建、一次 launch、原写者绑定和正常关闭；不实现既有库接管、数据库、服务 socket、模型或产品入口。

## 来源与所有权

专用入口在普通 Pi／多线程父进程之外运行。业务参数、消息、模型输出和客户端不能选 controller／writer 身份、epoch、fd、Node 可执行文件、loader、启动脚本、环境或 owner 路径。未来产品调用方只传已验证的部署和存储注册引用，不能传任意 child 或 capability 回执。默认 suite 可在唯一测试构造切点使用自有假 producer，生产路径固定原 producer，测试构造入口不作为配置项／CLI／消息字段发布。

旧 `OwnerRecordScope` 的三个 False 属性、只读观察和清理职责保留；不得从该外观取 fd 或把当前无 Node 的 finally 直接套在活写者外面。新 controller 在自有内部持有原 Tree、原 lock context、原目录、原方法／receiver 和当前 owner 字节及完整文件身份。可重用自有 store 的内部实现，但必须将新生命期和旧只读 facade 明确隔开；不能通过重构 record 或公开函数传入的 fd 建立所有权。

只允许本次排他创建的新私有目录。既有目录（包括空目录／缺 owner）失败，不复用、不清理、不换 epoch。原 acquired 记录的创建、父目录和文件 fsync、读回、随机 epoch、controller birth 与原 EX/NB 锁采用已有契约。首次记录回执失败时不启动 Node。冷恢复另做接口和资格，不把旧 controller／writer 的 PID 不存在直接变成新 epoch。

## 低号 fd 与固定 child

入口在其他路径打开、并发和 SDK 活动之前预留自己拥有的 fd3；发现 fd3 被未知对象占用直接失败，不关闭或覆盖它。预留对象和原 producer 的物理回执保存在 controller 内。取得原 EX/NB 锁后，只在自己仍拥有的预留槽替换为原 lock 的 dup；原父 lock fd 与新 fd3 都保留。这个操作发生在单线程可信入口内，不接受来自外部回调的槽位描述。原 fd3、lock path 和存储目录逐窗口检查；同 inode 的元数据核对仍不是同 OFD 证明。

launch 一次固定未修改 Node CLI 和自有 bootstrap，`close_fds=True`，继承列表只含原 fd3；stdin／stdout 为本次 Popen 创建的私有 pipe，stderr 为私有有界观测通道。bootstrap 在固定脚本位置之后仅收 controller 自行构造的六个只读标量参数：deployment hex、epoch hex、存储目录 device／inode decimal strings、原 lock device／inode decimal strings。值来自本次 acquired 与原物理回执，各自按既有范围／canonical规则核验；不是客户端转发的 argv、不含密钥、不携 Node选项／loader，Node 保存独立纯值用于 bind比较，不据此开库。固定受控环境不继承 NODE_OPTIONS、任意 loader、账号或模型认证。Node 来源及 bootstrap／依赖清单由部署验证控制，不能在 startup 失败时回退系统 PATH 或改选 runtime。Node 入口的 fd3／CLOEXEC／后代零原锁 inode 继承仍须在这个新组合上另做原生资格；历史 fd6 不自动覆盖它。

controller 捕获本次原 Popen 对象、原方法／receiver、原 PID、三条原 pipe 和 producer，任何 drift 永久关闭新入口。数据不得提供 signal target；所有等待／终止都针对原 child，不能按 hello 的 PID 去 kill。bootstrap 只导入 Node builtin 和自有消息 codec，接触 fd3 仅限固定 fstat／必要原 fd 标志观察以及最后 close；不包装 fd3 为 stream、不作 flock／LOCK_UN、不启动后代、不导入 SDK／SQL／backend。

## 原 pidfd 与退出回执决定

scout 的四源静态证据记录在 `/tmp/pi-owner-launch-pidfd-evidence.md/.json`：本机 Python3.11 的正常 Popen 启动不先 reap 新 child；原 poll／wait 的某些 ECHILD 分支会形成 synthetic status0，send_signal 则使用裸 PID。因此本包不能只凭 `Popen.returncode==0` 或重新打开 wire PID 签发退出／终止。证据里的 zombie／PID 保留最初为推论，root 另核 [Linux pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)：post-fork 打开已退出 child 的 pidfd 依赖未 SIG_IGN、无 SA_NOCLDWAIT 且无人先 reap；pidfd readable 也不等于已保存退出状态。该系统约束是本设计的前提，尚无新组合实测。

专用进程 main thread 在 launch前用保存的原 `signal.signal(SIGCHLD,SIG_DFL)` 明确初始化该 disposition，不装 SIGCHLD reaper、不启其他 waiter线程、不把原 child交给通用 Popen context／communicate／poll／wait。固定 [CPython3.11 源码 PyOS_setsig](https://github.com/python/cpython/blob/v3.11.0/Python/pylifecycle.c#L2822) 在 sigaction 分支设置 SA_ONSTACK，不保留 SA_NOCLDWAIT；这是 tag来源事实，不能据此宣称本机二进制等同 tag。实际 Python 来源和这个 disposition 初始化在原生资格固定／验证；实现前 fail closed 检查原 pidfd_open、waitid、P_PIDFD、pidfd_send_signal 等 API，原native材料再验证 kernel路径，缺条件不回退裸 PID。

Popen正常返回后，在任何可能 reap 的调用前，立即用保存的原 `os.pidfd_open(original_child.pid,0)` 捕获并保留本次 kernel child引用；用原身份 observer核 birth／UID和 hello，原 fd／producer源漂移即unknown。未取得 pidfd 时零新 signal，不用 Popen.send_signal／kill／killpg回退，只保持原锁并等待既有 bootstrap 自行结束或后续明确维护。等待采用原 `os.waitid(P_PIDFD,original_pidfd,WEXITED|WNOHANG)`，不是按 PID的新查找；公开 [Python waitid/P_PIDFD](https://docs.python.org/3.11/library/os.html#os.waitid)支持该接口，Linux≥5.4的实际支持另测。保存完整独立 si_pid／si_uid／si_signo／si_code／si_status，核本次原 child／UID、SIGCHLD及 CLD_EXITED／CLD_KILLED／CLD_DUMPED；None是尚未得到退出回执，ECHILD／EINTR之外错误或不符结果是unknown，不合成0。EINTR只重做没有结果的同一 wait观测，不能重做业务发送或持久写；已取得退出回执永久缓存，不能第二次 reap要求同结果。原 Popen retained object与其公开returncode仅作本地观测，不作为授权或真实wait证据，也不改写Popen类／函数或调用其私有实现。

故障停止只经原保存的 `signal.pidfd_send_signal` 向该 held pidfd发一次SIGTERM，最多等2秒，再在仍未取得合格退出时发一次SIGKILL并等2秒；用捕获的单调时钟，观测间隔最多50ms，期间继续有限排空原 pipes。这个行为只适用于本次自己创建的零 SDK bootstrap，不针对既有实例／client参数PID。signal返回或 ESRCH 不代退出回执；无原 pidfd或source不符时不signal。两次有界窗口之后仍无合格退出／producer静止则进入 unknown-held：专用进程继续保留原锁、禁止全部新入口，以有限观测保持存活，不从异常finally释放保护。没有保证 SIGKILL后一定即时终止；未知状态不能因deadline而变成功。后来实际退出／producer静止可终止故障监督，但仍不补 released／重做未知写；受保护写IO本身未知时继续 held，维护决定另处理。正常 released 必须有完整 closed ACK、实际 CLD_EXITED/status0、producer静止及所有同步owner写回执，不走这个故障分支。

## 首次握手与持久绑定

1. acquired 的持久回执和当前原锁／目录核验成功后，先 arm 唯一 hello 的逻辑接收窗口并记本次 launch 已消耗，再调用原 launcher。只有原 Popen／原 pipe 捕获绑定成功后才启动 read，尚未绑定时不读取或接受任何外来 pipe；bootstrap 在启动期间排入本次原 pipe的 hello仍由这个已arm窗口核验。失败、超时、EOF、迟到或未知回执均不得第二次 launch。
2. bootstrap 尚未开库，先发送唯一 hello。controller 只读本次原 stdout，按下述有限 framing 解码；核完整 Linux writer 元数据，再从原 LinuxProcesses 观察原 child PID 的真实 birth／boot／namespace／UID。必须与原 child 及 hello 全字段对应，不从 metadata 取得进程所有权。
3. controller 核当前 acquired 原字节、完整 owner 文件身份、当前 controller alive、原目录／lock fd／path 和原 methods／receiver；构造同 deployment／storage／epoch／controller 的 bound，writer 为原 child 的独立捕获身份。用原 Tree.replace(expected=上次完整身份) 持久发布、fsync 并读回全文和新完整文件身份。先完成持久回执，再打开唯一 expected bound回复窗口，最后才向原 stdin发送唯一 bind；窗口必须在第一个可能触发回复的原 send调用前打开，不等 send／flush返回后才开。
4. bootstrap 核 bind 的 writer 为本次自己、lock_identity 为原 fd3 的物理身份，record 的 deployment／storage／epoch 为本次私有启动材料；核自己当前 birth 和必要 fd 标志。这里只核元数据与固定程序职责，不声称由 JSON／fstat 证明 OFD。返回唯一 bound，全文必须匹配 controller 已保存的同一 bound record、锁身份和协议 flag。
5. 原 write／flush尚未完成时收到的 bound仅保存为有界私有候选，不提交metadata-bound；完整 frame的原发送／flush回执与其后的原sources／record跨源纯核全部成功，才消费本次原 pipe候选。任何partial／flush失败都是unknown，不用早ACK补齐发送回执或续流程。controller成功消费bound后只记本次metadata-bound。数据库准入、服务 ready、模型 grant、takeover 仍为 False。首包 bootstrap 在此等待 close，任何额外消息、乱序或重复都失败，不偷偷开库。后续数据库入口必须在这个组合取得原生资格后另冻结，不能把 bound ACK 当服务已 ready。

任何 Tree.replace／fsync／读回／发送之后的错误都可能已有可见结果；统一保留 unknown，不假称未写入，不重试 replace、不回滚、不重开、新 launch 或换 epoch。可以在仍持原锁时精确读取原 owner／原 child 状态作观测，但不能据一次成功读取继续被中断的绑定流程。

## 有界 pipe 消息

保留 4BE＋单 UTF-8 JSON、payload≤4096 的现有完整 frame codec。私有 reader 固定捕获原 pipe 和原 read producer；接收本次窗口的 header4，再取得声明的 payload，所有暂存累计≤4100，并最多另读取一字节用于检出本次读取中已出现的尾数据，不分配额外 payload。0、>4096 或非法 header 在 payload 分配／读取前拒绝。header／payload 可分片，本次读取已出现的尾字节／第二帧、EOF、不合法 JSON、阶段不符、乱序／重复都拒绝；不将额外 frame排队用于后续阶段。接收 pump 持续观测，窗口关闭期间实际读到的 bytes 拒绝；不能用某次无数据／peek证明 kernel中或未来绝无迟到数据。每个会话只接收 hello→bound→closed一次，三种type不同；逐窗口核期望type及完整保存的 record／epoch／lock，旧type在新窗口仍拒绝。消息全文、原 pipe、固定 bootstrap 的状态顺序共同校验；不把 bytes 到达时间或无 EOF 当来源证明。

发送方使用完整 canonical frame，一条消息只向保存的原 pipe 写入，必须处理 partial write、flush／broken pipe 与 deadline，不接受一次 write 返回值作为完整发送证据。接收／发送时限有界，由可信 controller 的单调时钟和固定配置决定，不来自消息。超时／取消／EOF 是失败或 unknown，永不默认确认。stdout 仅协议，stderr 有限保存且不得泄露外来正文；超限停止本次入口并处理原 child，不积累无界后台 buffer。

framing 的 codec 通过仅为格式事实，来自本次原 pipe 的解码结果也仍须阶段、原 child、持久回执和源身份核验。parser／encoder 错误使用既有固定文案，不保存账号、原输入或 JSONDecodeError.doc。对未知 IO 不能写成功回执。

## 永久关闭与 released

bound 后正常 close：先在内存永久关闭本次新入口；在仍持原锁下，以当前原 bound 字节／完整文件身份和相同 immutable 字段发布 closing，fsync、读回确认后，先打开唯一 expected closed回复窗口，再向原 stdin发送唯一 close。和 bound相同，send／flush期间的早closed仅为有界私有候选，必须等完整发送回执和原sources／record再次纯核成功才消费；发送失败不借ACK继续。bootstrap 验同一 closing record，保持零 SDK／后代；关闭自己原 fd3 后发送唯一 closed（record 仍 closing，descriptor_closed=true），结束本次程序。closed 是私有 metadata ACK，不是进程退出证明。

controller 即使收到 closed，也必须取得上述 held-pidfd 的实际 waitid回执，排空并结束本次原 stdout／stderr 观测 producer，并完成自己受保护的同步 owner IO；三者各自的回执不能互相代替。首包没有 DB／SDK／业务 IO，不能把这个简化外推到以后有数据库和工具的写者。只在已核原 child 退出、原私有 producer 静止、controller 仍持原 lock／fd3且当前 owner 精确为 closing 时，原子持久写 released、fsync、读回确认。随后永久停止所有 owner 写，最后 close-only 关闭原 controller 持锁句柄并退出。任何路径都不调用 LOCK_UN，不在最后锁释放后补写 released，不从 `finally`／裸 close／pipe EOF／descriptor_closed／PID 元数据合成 released。

若 bound 前后或 closing 发布／发送／ACK／wait／producer join／released 回执失败，永久 unknown，零新启动、零 SDK／开库、零新 epoch。故障清理采用上述原 pidfd和unknown-held路线，必须核原对象／methods／receiver，不终止既有实例或 wire PID；主错误保持，清理错误仅固定自有次级状态，不覆写／泄漏原异常。原 child 未取得合格退出回执时，controller 保持自己的原锁，不能先释放最后保护锁并报告停止。未知 record 不补写 released，即使后来 wait 成功也不自动恢复失败的持久流程；维护接管另处理。这里只决定算法，仍须独立设计审查；executor 不自行更换路线。

## 默认验证与实现 gate

下一实现包须在审查后明确唯一文件写入范围和实际接口；尚未授权 executor 写 lifecycle 代码。默认仅临时 HOME／Tree、假 fd／锁／LinuxProcesses／launcher／pipe／时钟／wait 回执，不运行真实 Node、信号、SQL、SDK、账号或业务 subprocess；旧 source／assertions 和 guards 保持。分别验证唯一 launch、真实 producer 引用与 receiver、bound 发布先于 bind、首次私有 hello／ACK全文、不合法 framing／乱序／迟到／超时、closing 永久、closed 不代 wait、wait 与 producer join 顺序、released 在原锁内、所有写前／写后丢回执不重试、错误保留未知与原记录、unknown child 不释放最后锁。

新实际 Python／Node组合还需单独准备和审查断网原生材料，具体场景和 plan 未固定时不运行。真实同 OFD、原 child birth、CLOEXEC、父／子退出、真实 pipe 分片和锁竞争、released fsync／读回均分别观察；SIGKILL 不冒充断电／全部 IO／远端模型终止。缺任一必要条件时产品 factory 继续关闭，T081／T090／Full 不勾选。后续存储、唯一服务、恢复接管和整个任务验收继续独立完成。
