# 原锁范围内的首次 owner 记录与读取

本包落实[原锁持有链](durable-owner-custody.md)的首个文件操作边界，使用[纯记录 codec](durable-owner-record-codec.md)。它只支持新目录首次 acquired 记录和既有记录读取，不接管既有 owner，不启动 Node/SDK，不打开数据库，不签发 ready、released、发送许可或模型预算资格。原 OS 持锁链的跨进程资格另行实测。

## 已冻结接口

自有 `src/agentcfg/pi_durable_owner_store.py` 提供两个 context manager：`create_owner_record_scope(root, deployment_identity)` 和 `open_owner_record_scope(root, deployment_identity)`。root 是精确原 str、绝对规范字面路径，每段非空且不是 `.`/`..`，无控制字符、反斜线或末尾斜线；部署身份是精确原 str 的 64 位小写十六进制。非法参数在文件操作前失败，不调用输入对象的 fspath/str/repr/比较 hook。不接受 kwargs 中的 epoch、controller、writer、proc_root、Tree、fd、权限对象、恢复策略或依赖；依赖替身只在默认测试 monkeypatch 自有模块的既定构造边界。

yield 自有不可变外观 `OwnerRecordScope`，只公开 `observe()` 和三个永久 False 属性 `writer_lock_verified/database_allowed/can_take_over`。不公开 lock fd、Tree、写方法或 close 方法；关闭由 context manager 唯一管理。observe 返回 codec 原冻结 record，永远不是原持锁能力。scope 在正常退出、异常或任一一致性失败后永久退役，晚到 observe 固定失败；不会再打开、续租、重写记录或恢复 scope。

## 首次创建

1. 只在 Linux 执行。逐段 no-follow 打开已存在安全祖先，root 的直接父目录必须当前 euid 的 0700 私有目录。缺父目录直接失败，不创建祖先。
2. 在原父句柄下使用排他 mkdir 创建最终目录，保留原创建返回目录 fd，检查 euid/0700，并 fsync 新目录和原父目录。既有路径（包括目录、文件、symlink）直接冲突，零 owner/lock/epoch 写入，绝不改权限、复用、清空或删除。mkdir 后的任何失败留下目录，不回滚。

这里的创建句柄是排他 mkdir 后逐段 no-follow 打开并核对的原目录 fd，并非 Linux 单次 syscall 同时完成 mkdir 和取得 fd。直接父目录 0700 与受信构造过程是前提，同 UID 恶意本机程序替换此私有路径不在保证内。必须保留原父与创建目录句柄并检查随后 Tree 一致；替身与目录 fd 相同都不作真实 birth/别名/崩溃资格证据。
3. `Tree(root, create=False)` 的原 fd 必须与原创建句柄的 device/inode 一致，并持续保留两者直到范围结束。不能用 Tree(create=True)、空目录检查或 owner 缺失重造首次凭据。
4. 用 `storage.instance_lock(Tree, create=True)` 获取原 EX/NB 锁。核私有物理目录、原锁 fd 与原叶路径为同一个 euid/0600/单链接普通文件；固定 device/inode/mode/uid/nlink，不将 atime 当身份。不删除、替换锁文件，不调用 LOCK_UN。
5. 在锁内确认 owner.json 缺省，再通过自有 `LinuxProcesses.identity(os.getpid())` 捕获当前 controller；PID/euid 必须等于本进程，完整八字段经 codec 精确验证，原 observer 必须 observe 为 alive。由控制面 `secrets.token_hex(32)` 生成一次新 epoch，经 codec 验证，客户端不能指定。直到这些操作结束及最终原目录/锁检查通过，才允许一次 owner 写入。
6. 记录仅 acquired/writer=null。用原 Tree.write_new 发布 owner.json，0600，文件与父目录 fsync；本包不得 replace/覆盖既有 owner。写前失败、写后异常、持久回执丢失、后置身份或读回失败均不再次调用 write_new、不换 epoch。只有原方法返回、后置原目录/锁/observer 检查与原 Tree.read 的完整 bytes/0600/单链接读回相同后，才 yield scope。此回执只是 owner 元数据记录成功，不是 Node/数据库准入。

## 打开既有目录

打开时不创建目录、不创建或修复锁、不生成 epoch、不读本机进程身份、不更新任何 owner。使用 `Tree(root, create=False)`，缺失/不安全目录失败。原锁文件必须存在、安全；原 EX/NB 锁通过 `instance_lock(Tree, create=False)` 获取，缺省也失败。锁内只读 owner.json，严格 16KiB/0600/单链接/codec；缺省即 recovery-required，即使目录为空也失败。部署身份和存储 device/inode 必须等于本次原 Tree。合法 acquired/bound/ready/closing/released 都只可读取，不据状态、PID 或持锁情况启动新 owner、生成 epoch或发送。旧进程观察/退出及恢复接管算法不在这个读取接口中实现。

## 持续检查与退出

保存原 Tree exactclass/原实例、root/private/fd，原 Tree.parent/read/write_new/close 函数和 receiver、原锁函数与 Linux identity/observe 的原函数/receiver。所有可能执行自有依赖的调用后以及任何写前，检查原引用与物理目录/锁绑定；不能因依赖回调最后返回合法对象而忽略其漂移。默认替身在构造前固定，构造后漂移即失效，不追加回调修复。

observe 每次在原锁范围内核原目录与锁，再读并校验完整 owner/deployment/storage；结果必须等于范围最初的原 record 与原 bytes（即本包不接受外部更换 epoch/状态）。读后再次检查原引用与物理身份，才返回原冻结 record。构造后 owner 缺失、权限/内容/身份漂移或根/锁别名变化，永久 retire，零写入。Tree 的目录句柄不允许借由同路径新目录或新锁文件续用。

本包没有 Node 写者，退出顺序为先 retire scope，结束所有受保护调用，再 close-only 释放原锁及目录句柄。正常 close 不写 closing/released，不删除 owner，不补造退出回执；退出后的 acquired 记录留给以后精确查询或明确恢复。异常清理不能触发重写、生成 epoch、重新开锁或启动进程。代码不得将同样 finally 释放规则用于以后仍活的 Node，Node 生命周期接口必须另外冻结并通过跨进程持有链资格。

清理不能仅调用已捕获的 Tree.close：该原方法读取当前 self.fd。只有当前 fd 仍是原数值且原 fstat 绑定未变时，才调用原 close/receiver。发生 Tree.fd 漂移时，不关闭或修改 foreign currentfd，只按内部保留的原 fd 与原物理身份核对后清理本包自己的句柄；无法核对则保持未知，不盲关、不重试、不造 released。所有原 fd 均私有且未交给 Node，不能将同 UID 恶意代码关原 fd 再以同 inode 复用编号的场景宣称为已检测能力。

取得本包自己的 open/dup/Tree 目录 fd 后，必须先保存独立 raw 物理回执（原 device/inode 与 S_IFMT 文件种类），然后才执行准入所需的 euid/0700 等严格政策。cleanup 使用这份原私有 fd 与 raw 回执确认同一物理对象，不能再次以严格权限政策决定是否关闭：拒绝最初 0755 的既有目录、Tree 形状/绑定不符，或取得后目录 chmod 成 0755，仍应关闭本包已取得且能核对的原句柄。模式权限、uid、nlink 的准入检查照旧严格；原权限不合规不等于本包未拥有打开的 fd。原 raw 回执缺失/物理身份未知才保留 unknown，不盲关 foreign fd。此修正不扩展恶意同 UID 关原 fd 并重用同 inode 的检测保证，也不增加重开或 released 操作。

原 `_absolute_directory` context manager 提供的 parent_fd 是向本范围借用的句柄，关闭由原 producer 的私有闭包管理；它与本范围直接取得的创建/open/dup/Tree fd 分开。退出必须调用原 parent CM 的显式出口，让该 producer 关闭自己的原句柄，不能用 consumer 的 raw fstat 缺失/失败跳过原出口并依赖 generator GC（GC 仍可能运行 producer finally，且其时机不能用于持有或释放证明）。这里不以序列化 fd/metadata 提供关闭权，也不关闭 foreign Tree.fd；原 producer 出口失败仍是 cleanup unknown，遵守主异常优先，不伪造 released。默认新增切点应证明即使 consumer 无法再观察 parent fd 元数据，原 private producer 仍显式退出，准入严格检查、直接 owned fd 回执和活 Node 排除全部保持。

固定错误包装仅限自有初始化、observe 和 cleanup 操作，不跨 yield 包装调用方 body 异常（包括 OSError/Conflict），不修改该原异常或其上下文。如果初始化或 body 已失败，cleanup 的额外失败不覆盖主异常；scope 仍永久 retire，owner 保持 acquired 或未知，零 released、重开或重写。仅在没有主异常时将 cleanup 失败作为固定 StateError 抛出。默认测试分别核这些退出切点，不能以正常 finally 执行声称释放已确认。

输入、缺省、busy、身份/权限/格式/漂移错误固定 Conflict（exit4）；文件系统失败固定 StateError（exit6）。不带路径、原字段/数据或底层异常正文，清除自有错误的 __context__/__cause__，包括 caller 正在处理含秘密异常的场景。后置写入未知不被描述为未写入或可重试。

## 最小共享变更与默认验收

`storage.instance_lock` 仅增加精确 bool 的 `create=True` 关键字，默认老行为保持；create=False 的 os.open flags 排除 O_CREAT，缺失不得生成文件。添加 O_NONBLOCK 防止叶节点被替换为 FIFO 时阻塞，flock EX/SH/NB 与 close-only 原语不变。禁止扩展显式 unlock、恢复、锁文件替换或删除。此共享 diff 必须单独核原默认调用的行为兼容。

默认测试只在临时 HOME/XDG/私有目录运行自有 Python；fcntl.flock、LinuxProcesses.identity/observe、epoch生成替身固定，fsync 可用真实临时文件并记录次序；不读真实 /proc、不运行 OS 锁竞争/子进程/信号/第三方宿主/SDK/SQL/模型/网络。覆盖首次排他创建与父/根权限、既有路径零修改、永久失败遗留不被再初始化、原创建句柄与 Tree 绑定、busy、missing owner/lock、目录/lock 替换、原方法漂移、当前 PID/euid 和 observer、write_new 前失败/写后丢回执/后置读失败零重写、observer 最后一次返回后 drift、所有 observe 前后固定绑定/retire、全部 stage 只读、close 零released、错误上下文隐私与 no-O_CREAT。缺实现导入错误不作行为红；真实行为反例分别记录 source/test pins、原日志与 counts。无新失败不扩展到全仓测试。

这是文件与原锁范围的默认验收；替身 flock 不证明实际内核独占或 Node fd 持有链，不勾 T081/T090、OwnerReady 或 Full 产品资格。
