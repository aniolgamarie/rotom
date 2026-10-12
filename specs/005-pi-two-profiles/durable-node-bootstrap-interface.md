# 零 SDK Node bootstrap：首个实现包接口候选

2026-10-08，root 接续 owner-controller-launch 的五消息路线和静态输入接受 receipt `bb1702738ac04d13a58f453c6500c3ac7a2e8ae25ff3238fa016f069e580fa05`。本包仅实现 Node 一端的 metadata 握手，不签发 controller、持锁、初始化、数据库或服务资格；父 controller、Full 来源、issuer 和运行资格仍是独立前置。初版独立复核及fd-flags增量已完成；root随后冻结确切effect API，以15输入receipt `d49a1143d7c0b605a6c22ec0194913cba4cb86528f096b2cf01929d52728bbcd`授权executor仅实现下述三文件及默认测试。实际Node/fd与正式factory仍未资格。

## 唯一文件范围与安装

拟议唯一 writer 范围是新 `agents/pi/runtime/durable-owner-bootstrap.ts`、新 `agents/pi/runtime/tests/durable-owner-bootstrap.test.ts` 和新 `tests/test_pi_owner_bootstrap_runtime_file.py`。不修改 owner codec、旧测试、mock guard、安装转换、正式声明、锁、profile 或启动入口。

bootstrap 使用无类型注解的 JavaScript 写法，只有 Node builtin 和 literal `./durable-owner-message.mjs` import。现有 `ts-module` 转换没有 TypeScript 编译步骤；它只替换本地 `.ts` import 后缀。因此直接保存可运行的 `.mjs` 字节，沿已声明的 owner_bootstrap／owner_codec 两个固定路径。默认 Node 测试在 mock harness 的私有 TMPDIR 下放这两个 sibling 文件，动态 import bootstrap 的测试切点，不能运行 CLI 分支。Python 映射测试调用真实 lock／transform／install／validate_files，仅操作临时 Tree。

## 输入与测试切点

CLI 只在 `process.argv[1]` 与本 module 的绝对路径相同时进入；单纯 import 零 fd、proc、stream 或 timer IO。入口 Linux x64，父方仍须验证固定未改动 Node 来源。只有六个参数：deployment hex64、epoch hex64、storage device／inode、lock device／inode。全为 primitive strings；decimal 转换前限制20字符、canonical u64，两个 inode 必须大于0。拒绝多余、缺失、非规范值，零自选路径、fd、provider、预算或 Node 选项。

生产 `_main` 仅用捕获的 Node 公共 builtin producer。隔离测试可使用模块内的一个显式测试构造切点，传六标量和假的 effect table；这个表不会从 CLI、消息、配置或正式 source 引用取得。构造器拒绝 proxy、getter、symbol、未知键和非 function。精确 effects 为 `lock`、`writer`、`write`、`close`、`now`、`setTimer`、`clearTimer`、`finish`，调用时保存原 function／receiver；漂移永久失败。返回的 driver 只供该私有过程使用，不能成为 initializer 或 DB grant。

## 首包固定 effect API

`_createOwnerBootstrapForTests(scalars, effects)` 接收原生 Array（拒绝proxy、自定义prototype、getter、symbol／额外属性）的六个primitive string；构造期只做纯校验，失败抛固定自有码且零effects。返回冻结的 `start()`、`push(bytes)`、`end()` driver，三方法返回undefined；可信timer回调由driver闭包建立，测试从假的setTimer取得，driver不公开expire／恢复／重新开始入口。start只允许一次；进入完成／失败后迟到事件不能产生新write、lock、writer或close。

effects保存确切八个own enumerable data function及原receiver，调用前后拒绝table形状或函数漂移。`lock()`返回plain/null-prototype、无proxy/getter/symbol、确切十一字段：`device,inode,mode,uid,gid,nlink,size,mtime_ns,ctime_ns,close_on_exec,read_write`。前七个为canonical decimal strings（device/inode/nlink/size为u64，mode/uid/gid为u32；inode和nlink非零），两个时间为canonical signed64 decimal strings、禁止负零并先限长度；两个flag必须literal true。mode必须33152（regular0600）、nlink必须1，device/inode等于CLI原锁；不增加空文件要求。九个stat字段逐字相等作为后续身份比较；此表只是producer的观察，不是同OFD或EX锁证据。生产lock第一次内部必须先fstat3，并在读取fdinfo前核对mode/nlink/current uid/CLI devino；测试表不能代替当前uid的生产观察。

`writer()`返回existing hello codec接受的确切八字段process identity；driver通过原codec捕获，首次核writer.uid与lock.uid对应，后续全文相等。`now()`返回有限非负number毫秒，driver拒绝倒退、负零和非finite值。`write(frame, done)`接收driver自有完整Uint8Array和单次回调，正常返回必须undefined；done的唯一参数undefined或null为成功，其余值为固定失败且不读取foreign错误属性。`close()`正常返回必须undefined，只尝试一次。`setTimer(delayMs, callback)`只为当前固定期限建立单次timer，返回可信opaque handle；`clearTimer(originalHandle)`返回undefined，绝不从消息取得handle。若timer在setTimer返回前同步触发，只能失败，不能推进握手；原handle返回后最多清除一次。`finish(code)`接收0或2，返回undefined，最多调用一次；finish抛异常不重试。生产finish只结束自身这次过程，默认fake仅记录调用。失败的固定自有码不含foreign exception、原帧或账号值。

故障cleanup是effect guard的唯一显式例外：失败先永久关闭所有新入口和推进路径，然后只用最初捕获的可信clearTimer／finish及原receiver，各最多一次；不读取或调用漂移table中的替换函数，不再lock／writer／write／close。clearTimer异常仍允许一次captured finish(2)，finish异常不重试，不读取foreign错误属性。正常effect调用仍前后核形状和函数。生产effects table为本模块内冻结对象、外部不可取得；测试可变table只用来检验此故障语义，不作为生产source资格。

这些签名冻结的是可默认验证的组件契约；正式controller factory、实际Node flags、退出／pipe quiet证明仍未形成。当前允许实现的唯一新文件和默认验收范围保持前文三文件；不扩大到父controller、真实fd或native smoke。

## 自身观察与来源限制

入口第一个自有 fd 操作是 `fstat(3)`；在核原 lock device／inode、regular file、当前 UID、mode600、nlink1之前，不显式关闭3、不读取 fdinfo／proc、不取得 stdin／stdout stream。随后 bounded 读取 `/proc/self/fdinfo/3`（最多4096B）并再核 fd3。要求 flags 里 CLOEXEC 和 read-write；记录排除 atime 的九字段 stat 身份，后续必须相同。flag 与 fstat 是元数据事实，不能证明同 OFD／原 EX lock；这些仍靠父原 producer、固定来源和独立真实资格。

父创建链在后续 controller 包必须保持确切值：现有 `storage.instance_lock` 创建 `instance.lock` 使用 `O_RDWR | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK`（首次另有 `O_CREAT`）并 EX/NB flock；只将此原 OFD dup到自己拥有的预留3，parent3保持CLOEXEC，固定Popen设置 `close_fds=True, pass_fds=(3,)`。能跨exec的child3不能被假定仍带parent的CLOEXEC；Node启动后的bit另由当前fdinfo观察。bootstrap不设置／修复flags，不调用私有Node／libuv接口，不从hello或历史FD6补bit；观察不到CLOEXEC或read-write即拒绝、零hello／close／SDK。默认组件只实现这一条件与拒绝分支，不能把fake true或该创建算法签成实际传递链已实现。后续新组合原生资格必须分别观察原parent3、exec之后Node3和零原锁inode后代继承；资格未通过前父正式factory继续unavailable。这闭合静态接口的flags职责／失败行为，实际启动结果仍是未验证前提。

writer 只从本进程的公共 builtin 和固定 `/proc/self/stat`、`/proc/sys/kernel/random/boot_id`、`/proc/self/ns/pid` 捕获。stat最多4096B，boot最多128B，namespace最多128字符；没有进程扫描、环境认证、账户路径或外来 PID。值先按现有 hello codec独立捕获，并对应当前 pid／ppid／UID。每次发送前、完整发送后的相应窗口及关闭前核原 writer 和 lock 身份；不声称这些检查是原子 snapshot 或对任意同 UID 内存修改的屏障。关闭原3后不再通过新增文件 IO 重核已退休的3。

## 私有 driver 与发送顺序

driver 的外部事件只有开始、原 stdin bytes、原 EOF 和可信 timer；生产绑定本次原 streams，测试传入假的事件。正常顺序为 hello→接收 bind→bound→接收 close→关闭原3→closed→完成退出。bind 的 writer 全字段必须等于保存的 hello；controller pid等于本次 writer ppid，boot／namespace／UID对应；record 的 deployment／storage／epoch等于六标量。close 仅将同一 bound record 的 stage改为closing，其余全字段相同。所有消息仍调用原 codec，不复制宽松 JSON 解析器。

发送前 arm 唯一下一回复窗口。hello 或 bound 写入尚未完成时，匹配 bind／close 仅存一个有界 candidate。完整 write callback 成功、原 write 调用正常返回、postpure 成功三条件同时满足后才消费；callback先到不能越过尚未返回的 write，throw-after-callback也永久unknown。一次发送只调用原 writer 一次，不重发。生产的 write callback含义只限本地原 stream 对该完整 frame 的发送回执；它不是对端接受、持久写或退出证明。重复 callback、返回异常、错误 callback、partial／broken pipe及source漂移均失败。

close消费前再核原来源和closing全文，先永久退休原3的可用状态，close-only尝试一次。只有 close正常返回才能发 closed／descriptor_closed=true。close异常不重试，不发成功 ACK；closed发送结束前没有任何新接收窗口。bootstrap 没有 flock／LOCK_UN、SDK、SQLite、网络、后代或自行创建的线程；Node运行时内部线程不在“自有线程零创建”声明内。

## 有界 framing、截止与故障

4BE＋单UTF-8 JSON，payload1–4096B；header完成后在分配payload前检查。累计最多4100B，并仅另容许一字节检出同次输入的尾数据。拒绝超限 chunk、尾帧、重复／乱序／错全文、EOF、关闭窗口中的bytes；不会把第二帧缓存给下一窗口。将来迟到bytes只能在到来后拒绝，不能以一次无数据证明不存在。调用者的 buffer独立复制，不调用其 getter／slice／species。

每个hello发送／等bind、bound发送／等close、closed发送阶段采用固定10秒单调期限。timer仅用于进入永久失败；事件循环或同步 builtin IO 阻塞时不声称具有整体硬截止。真正父监督仍需原held-pidfd路线。所有失败永久关闭新入口，取消自有timer、固定自有码 `PI_DURABLE_OWNER_BOOTSTRAP_INVALID`，finish最多一次；不记录原帧、foreign exception、token或错误链。unknown3没有显式close；已知原3也不从finally无条件关闭或发closed。生产只退出自己这一次Node过程，退出请求本身不是实际wait证明。父 controller 继续负责原锁和 unknown-held，不能据此补released或再次launch。

## 默认验收与明确未验证项

默认正控制实际执行上述 driver 的正常三发送及关闭顺序，验证early candidate只在完整发送后消费。负控制覆盖六标量规范／effects外观、锁／writer漂移、wrong parent、header分片／超限／尾数据／重复／EOF／迟到、callback-before-return／throw-after-callback／重复callback／callback错误、各发送和关闭丢回执、close异常不重试、source拒绝零额外IO、timer与正常关闭后的迟到事件。使用 effect日志检查实际调用顺序／次数和禁止项；只测常量或镜像数据不能验收。

Python只验真实安装映射、字节、mode、闭合条目和漂移拒绝。默认不执行真实 Node CLI、fd3、proc observer、信号、第三方宿主或 SDK。写入 STOP 后独立审稳定 diff及失败证据，修复只复核受影响路径。新实际 Python／controller／Node／pipe／fd3组合另备材料并明确授权；旧FD6／Recovery3等已闭合授权不覆盖它。生产 Full／controller gate保持 unavailable，formal任务与全部产品gate不因本组件通过而更新，严格计量前 AUTO OFF保持。

2026-10-08（本地）三新文件实现已 STOP 并有限验收，18输入 root receipt `daa520bf4ac787369e9843e49cb9eb7e7b8876252c76bb19ebba2862eb9ea55b`。Node 默认 mock 一次实际59/59通过，Python临时源码映射一次实际6/6通过；collect-only的6项不计作运行通过。原Node reporter没有解析出计数的 `{}` 保留，后从同次原始日志核实59项，无重新执行。5输入raw log附录receipt `181e8a07b730f274928c2a2f1d6ede774837b957fa7a0ccde23316f0b9f0aa6a`保存确切日志和runner。

root完整读产品和测试，独立executor对稳定三文件、接口和codec完整审查，未确认P1/P2；三个产品／测试文件与只读参考pins未漂移。实现及独立review角色配置均为gpt-6.1-sol/medium，scout为gpt-6-luna/high；这是观察到的角色配置，不是backend模型证明。真实CLI／fd3／proc／flags／pipe／原OFD／EX锁／wait尚未运行；原父controller、来源、初始化权、DB和Full仍未资格。下一包只准备实际零SDK合成组合及独立授权材料。
