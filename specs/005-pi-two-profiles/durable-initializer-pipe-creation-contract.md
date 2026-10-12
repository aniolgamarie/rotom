# 初始化双 pipe 的创建与关闭原语

2026-10-09 Root。接续 durable-controller-private-channel.md 的原端点选择；本包只创建本进程自有两条单向 Linux pipe，不 launch、读写、handoff、签发 grant 或创建持久目录。既有 grant/native 全部保持其原边界，不开放新的 actual syscall smoke。

## 接口与所有权

新增 src/agentcfg/pi_durable_initializer_pipes.py，唯一入口 create_initializer_pipes() 无参数。专用初始化创建者的原主线程以保存的 os.pipe2/os.fstat/os.close/fcntl.fcntl 和 threading.current_thread/main_thread 引用执行。先核当前主线程，再调用 pipe2(O_CLOEXEC|O_NONBLOCK) 两次。第一条返回读端为 controller 的读、写端为 parent 的写；第二条返回读端为 parent 的读、写端为 controller 的写。两条新管道必须不同，四端必须两两不同且最终都>=4。本包不改变 SIGPIPE/SIGCHLD disposition，不读/write任何一端；PIPE/FIFO identity 只证明本次持有资源，不提供来源/principal/child资格。

每次原 pipe2 返回后，立即记录它返回的两端，再作 fstat/fcntl 或下一次 pipe2；第二次创建之前第一条两端必须已归本记录管理。只接收原 API 返回的 exact tuple 两个 exact nonnegative int；这不是 caller DTO。内部分配/登记失败时，对本次已返回的有效自有整数和此前仍持有的资源分别作一次 close-only cleanup；两两重复整数仅关闭一次，不猜测或关闭没有被本次 API 返回的其他 fd。此假值容错不证明 CPython/kernel 任意 OOM 的内部行为。

新得低号端点以保存的 fcntl(F_DUPFD_CLOEXEC,4) 复制到高号，复制返回即登记，核>=4/未冲突及相同 held FIFO identity、方向、NONBLOCK/CLOEXEC，然后永久退休旧端点并只 close 一次。dup2/覆盖已有3/重新 pipe2/LOCK_UN/fdopen/socket wrapper 均禁止。新端点物理字段 dev/ino/mode/uid/gid/rdev，FIFO/read-only或write-only、O_NONBLOCK与FD_CLOEXEC须核对；同 pipe 两端 dev/ino 相同，不同 pipe dev/ino 不同。不要把 size/time/nlink 当不变数据。任何未知/失败零后续创建、继续各自 known-owned cleanup 一次；close异常不重试，也不称 released。

成功返回不可序列化的自有 InitializerPipes，仅本工厂登记的原对象有效。private registry 保存四端及原方法/receiver/线程；无公开构造、fileno/整数列表/DTO/角色或launch方法。公开 check() 核原对象/线程/活性以及四端 held identity/flags；不得重新打开路径或新建端点。close() 先核登记原对象/原线程/未退休，再永久退役整体；对每个仍持有端点以原方法核 held identity/flags，核失败不关闭已观察为 foreign 的fd，其他端点仍继续逐一核并close-only一次；任一核/close失败输出固定自有 initializer-pipes error code、exit4，无 foreign exception链或原路径/载荷。重复 close/check 拒绝。wrongthread/foreignobject 不得退休原记录。核与close间任意恶意同进程竞态及相同pipe OFD替换不由本包证明。没有contextmanager/finalizer自动close；未来handoff须另冻，不能从resource object重建authority。

## 默认验收与范围

唯一writer新增上述模块和 tests/test_pi_durable_initializer_pipes.py，自有证据 durable-initializer-pipe-creation-implementation-review01。默认所有 pipe2/fstat/fcntl/close/thread 都 fake；不实际创建 pipe、dup/close pytest fd，不 Popen/fork/SDK/Node/signals、不改 conftest。有意义行为 RED 后只跑新 pytest 模块。断言两次固定创建顺序、方向与flags、低fd规范化原OFD字段、创建/登记/dup/核/close每点故障 cleanup一次、不触碰foreign3、不重新创建、非main零IO、copy/foreign/手工构造拒绝、check零路径IO、端点漂移close拒绝但其他自有端继续cleanup、close失败不重试、fixed errors rendered链无sentinel。

你不是唯一作者，不回退他人改动；不写 state/tasks/docs/其他模块/OMP/SDK缓存。接口/资源顺序需扩大范围或同失败两有效尝试升级Root，子代理不得再派生。完成稳定diff/pins/testlogs/report后STOP交回；Root再独立复核。不补 actor/原Popen/SourceHold/FullSourceView，不标整体任务完成，正式8/100，AUTO OFF。

## Root malformed API return 裁定

失败cleanup仅识别原pipe2返回的exact tuple中exact nonnegative int（长度非2也如此），与此前owned去重各close-only一次；非tuple/list/tuple subclass不遍历，不调用foreign iterator、不猜fd，不声称完整released。dup返回与已登记fd冲突时去重一次cleanup并零后续创建/dup。实际kernel公开API正常返回两个fd；此边界不证明任意API内部破坏或OOM。
