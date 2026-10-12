# 原低号 fd / Node 持有链基础探针

状态：自有默认组件已完成稳定验收，76 项 Python 默认检查通过，未改动的纯 facts Node 检查保留独立 20 项通过记录，不合计。首版 67／20 绿后的两个 P2 保留于未验收档；完整旧源码同新测试实际 7 失败、69 通过，修后 76 通过，root 与独立增量复审无开放 P1/P2。正常属主真实 plan 已准备，六场尚未获授权或执行。此材料是[候选路线](durable-owner-node-fd-route.md)的独立基础验证，不接入当前 `OwnerRecordScope`，不实现 owner 的 bound/ready/closing/released，也不把元数据转换为准入能力。已完成的 Durable SDK7 授权已闭合，不能用于本探针。

## 固定边界与目的

只支持当前 Linux x86_64、固定未修改的 Node v24.14.0 CLI、Python 3.11 与 bwrap。所有实际运行位于断网 PID/user/mount namespace：系统 `/usr`、`/lib`、`/lib64`、固定解释器和自有最小脚本/模块只读，唯一可写树是每场独立的临时 `/work`。空环境再显式设置临时 HOME/XDG/TMPDIR、空 PATH 与 locale；不加载 NODE_OPTIONS、Python site、用户 loader 或插件。没有 Pi/Codex/MCP/SDK/SQLite/模型/账号或业务目录。系统挂载只核固定解释器 hash 与目录身份，不能宣称完整系统镜像已锁定。

拟新增 `scripts/pi-probe-owner-fd.py` 与 `.mjs`，固定 fixture/oracle 和默认测试。Python 入口分为外部 prepare/run-native 与 namespace 内 driver/controller；内部模式须有固定 guest 环境和参数，导入、prepare 与默认检查不启动任何真实子进程。外部 plan 记录完整自有源/fixture、解释器及系统边界、六项 argv、空 host env、上限、scope；nativeStarted/nativeAuthorized 初始为 false。run-native 另需显式 flag、独立人类授权和一轮新目录。旧 started 目录不能再运行；任何 material/argv/环境/fixture 漂移直接失败，绝不自动刷新 plan。

这不是完整 launch/ready 握手或丢回执恢复验证。通过也只证明固定探针的原锁描述符基础；产品 controller 的私有接口、原 writer birth 绑定、开库、账本、结束写入/持久 released、任意工具后代和旧 owner 接管仍分别开放。

## 进程与原 fd

外部 parent 启动 bwrap 后，保留 namespace init/reaper 与自有 driver；driver 再启动专用 controller，controller 启动 Node。不能假设现有 bwrap 下 driver 必为 PID1：实际记录 driver/controller/Node PID 与 namespace，controller 必须不是 PID1，且信号只对本次保留并核对身份的 controller 或 Node pidfd。driver 与 namespace init 在 controller 退出/被杀期间持续存活。不得杀 PID1 或整个组来制造“父死子活”的通过。外部失败清理只针对本次保存的 bwrap session；namespace/任意后代的完整停止资格仍是 unknown。

controller 通过固定 Python `-I -S -B` 启动，`close_fds=True`，只有 stdio 0–2；在首次路径/锁/并发活动前打开自己的 `/dev/null` 预留槽。返回值必须恰为 3；若非 3，只关闭此次新取得的 fd 并失败，不探测后覆盖未知 3。随后使用原自有 `Tree` 与 close-only `storage.instance_lock` 在临时私有状态目录取得原 EX/NB 锁，固定原普通文件 device/inode、uid、0600、单链接与原叶路径。当前 owner-store 的公开接口不暴露或复用 fd。

正例只把原 lock fd `dup2(..., 3, inheritable=False)` 到自己预留的槽，保留原 parent lock fd 与槽 3；`Popen` 使用固定 Node/自有脚本、固定 stdio/空 loader 环境、`close_fds=True` 和 `pass_fds=(3,)`。这是受信单线程专用控制面中的具体链，不允许客户端 fd、普通 Pi 进程或盲 dup2。Python 的原锁上下文始终 close-only，全部路径禁止 LOCK_UN、换锁、删除锁或在 unknown 后重启。

Node 不将 fd3 包装为 stream，不交给 backend/SDK/tools；在读取 fdinfo 或任何文件前，使用公开 `fstatSync(3, {bigint:true})` 核原 device/inode、普通文件、uid、0600 和单链接，避免 Number 精度截断。检查前后仍核 fd3 与原锁物理身份。私有预期 binding 由原 controller 生成，参数/记录的 fd 编号本身不提供权限。

## fdinfo 与后代 oracle

本机须实际符合 Linux x86_64、kernel >=5.3、Python `os.O_CLOEXEC == 0o2000000`、pidfd_open/send_signal 可用及 guest procfs 可读；静态 generic UAPI 不替代本机资格。Node 通过公开 fs 读取 `/proc/self/fdinfo/3`，最多 4KiB，精确一项 `flags:` 八进制字段，不接受重复、缺省、非法数字或溢出。显式检查 `0o2000000` 位，并在读取后再次核原 fd 物理身份。[Linux 文档](https://man7.org/linux/man-pages/man5/proc_pid_fdinfo.5.html)仅支持 current flags 的观察；观察不设置标志，不证明同一 open-file-description 或仍持 flock。

正例 Node 使用公开 child_process.spawn 启动固定同一 Node/自有 descendant 模式，stdio 固定，完整等待该已知子进程结束后才发布 entry 回执。descendant 有界枚举自己的 `/proc/self/fd`，对最多 1024 项使用 bigint fstat，找所有对应原锁 device/inode 的 fd，而非仅问 fd3 是否存在。枚举本身的已关闭临时目录 fd 可按 ENOENT/EBADF 处理；其他未知错误失败。必须为零匹配，stdout 单个完整固定形状 frame、stderr 空、原 child exit0。这只资格该固定 spawn 路线；不宣称未来任意工具/任意 launcher 后代零继承。

driver 的竞争者始终重新打开同一个原锁叶路径，no-follow、原普通文件/uid/0600/单链接/原 device/inode 前后核对，EX/NB busy 仅接受 EAGAIN/EACCES；free 必须真实取得原 EX 后 close-only。不能使用不同目录、新锁或模拟返回值作为 native oracle。锁元数据、fdinfo 和 birth 均与竞争结果分列。

## 六项固定切点

| case | 必须观察的原事实 |
| --- | --- |
| entry-and-node-exit | parent 与 Node 同时存活时原锁 busy；Node 原 fd3/CLOEXEC 与 descendant 零匹配成立；Node 正常退出后 parent 仍存活且原锁 busy；parent 最后 close-only 退出后原锁 free。 |
| controller-exit | 正例 entry 后 controller 正常 close-only 退出；Node 原身份仍活、pidfd 未就绪、原锁 busy；随后 Node 正常退出、原锁 free。 |
| controller-kill | 正例 entry 后仅对核对后的原 controller pidfd 发 SIGKILL；Node 仍活且原锁 busy；Node 最后正常退出后原锁 free。SIGKILL 不冒称断电。 |
| node-kill | 正例 entry 后仅对原 Node pidfd 发 SIGKILL；原 controller 观察原 child wait 为 -SIGKILL、仍活且原锁 busy；controller 最后 close-only 后 free。 |
| wrong-fd | fd3 保持自己预留的 `/dev/null`，原锁由 parent 另持；只 pass3，Node 在首次物理核对拒绝，零 descendant spawn；parent 仍忙、最后退出 free。拒绝路径不显式 close Node 内未知 fd。 |
| high-fd-rejected | 用 F_DUPFD_CLOEXEC 从原 lock 在 >=64 取得自己新副本，要求实际返回64，否则关闭自己的新副本并失败；只 pass64，固定 bootstrap 仍只认3，必须拒绝且零 descendant spawn；parent 仍忙，最后 free。不预测或签发高号 fd 实际泄漏。 |

每场 Node 最多启动一次，负例不是旧 owner 恢复/零发送资格。Node 由 driver 写入固定短字节命令文件请求正常退出；controller 另有固定独立退出命令。不能使用父 pipe EOF/stdio 一结束就杀 Node，否则父退出持锁切点无效。命令及回执只属于私有探针控制面，不对外提供通用服务。

driver 在 controller 存活时保存 Node PID，取得 `pidfd_open(pid, 0)`，通过 guest proc 原 birth、uid、namespace、exe 与该原 pidfd 前后核对；以后只忽略因 reparent 改变的 PPID。预期 alive 的切点要求完整原身份一致且该 pidfd 未就绪；它并不是失败。发信号之前同样要求 alive，只使用原 pidfd，不向裸 PID/PGID 发信号。预期退出时，未就绪只表示尚未观察退出，可在期限内等待，期限到即失败/unknown。

原 pidfd 的 POLLIN 或已回收时 POLLHUP 均属于退出 readiness，POLLERR/POLLNVAL 仍是 unknown，不能把 HUP-only 当成仍活。driver 在任何切点或信号之前即保存并核自身原 birth，controller/Node 的 expected exe、uid、namespace 必须与这个原 driver 边界相符，三个 PID 不同且 controller 不是 PID1；每次发信号前复核原链。只与目标自己第一次读取的值一致，或等最终 oracle 才核 uid/namespace，不足以准入本探针的信号。默认新增回归要在旧完整实现上真实体现 HUP-only 被漏认和 wrong chain 已发生一次假信号，不运行真实 guest/proc/signal，也不能以缺新 export 作行为红。

直接 child 使用原 Popen.wait，孤儿 Node 的 exit-observed 要求原 pidfd 已就绪，并且原 proc 已消失，或两次有界 stat 读取为 Z、PID/start_time/uid 与保存的原 birth 一致。Z 时 exe/namespace 链接不可读不补造当前值、不再称 alive；其他错误、身份不符或不可解析都保持 unknown。此分支只用于固定 namespace 中事先存活核验并保留 pidfd 的本次进程，不从客户端 PID、裸 Z 或旧序列化元数据制造原 pidfd。[pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)说明 flags=0 指向 process，并在最后 thread 退出时变为可读；[proc_pid_stat(5)](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html)定义 Z 与 starttime。它支持限定的原进程退出观察，不证明 lock free、任意后代/物理树或 IO 已结束；lock free 仍必须通过原路径竞争者另测。EOF、JSON和普通 subprocess poll不能替代这些事实；不向未知身份追加信号，不重启来收敛。

## 材料保存、失败与默认检查

每场限时15秒，全轮120秒；stdout 单行64KiB，stdout+stderr 合计1MiB，私有 JSON/命令与 work 文件严格总量/大小上界。全轮 source/system 检查与每场 argv 重算一致；启动前写 started，Popen 成功后立即保留 started/PID/phase。setup 前失败 not-run，任何已启动后的 capture/oracle/工件失败必须保持 started=true/outcome=failed，不能回写为未启动。第一失败后后场 not-run，原日志/阶段/exit/材料完整性和 namespaceTermination=unknown 独立记录。后置保存失败同样保留已知事实，不自动重复本轮。

外部证据为 stdout/state 一致的封闭 schema，并记录每切点 busy/free、原 lock identity、原进程 identity/退出观察、Node entry/flag/descendant 结果、真实 launch 次数；未知字段、类型、重复 JSON 键、错 case/缺切点/多frame/stderr/错误 exit/extra work文件/link/权限/源漂移失败。外部 post_work 需封闭列出所有允许的控制、输出、临时HOME/XDG、状态/lock文件，不将仅保存一份 oracle 常量当观察。

默认测试只用小自有静态 bundle、临时 HOME/XDG、假 Popen/pidfd/proc/flock 与合成 frame，部分 deadline 计算使用原 monotonic 时钟；不启动 guest 进程、Node/bwrap、不执行 OS 锁竞争／信号或读取真实 proc。新增回归可在上述依赖全部替换后调用原 driver 控制流，不把它算作 guest/native 执行。覆盖 prepare 零 launch、精确 source/argv/环境/权限与一轮保护、六个正反 oracle、多/重复/非法 frame、缺切点/错误 physical binding/退出观察、后代非零/高号失败、不覆盖未知预留槽的纯决策、late material failure 保留 known started、超时/保存失败及后场 not-run。默认行为红须用完整旧源码与相同新用例真实复现，缺导入或假环境不足不当产品反例。最终稳定 diff 与 raw 默认日志独立复审后，才准备正常属主固定 plan 与授权说明；未运行六场不得记 PASS。

## review02 执行前的正常属主材料与命令

临时目录为 `/tmp/pi-durable-owner-fd-native-review02-normal-owner`，0700、属主 UID 1002；执行前仅有 0600 单链接 `plan.json`。prepare 与只读复核均退出 0、零子进程，plan 逐项等于当时受信脚本生成结果，源／fixture／固定解释器 hash、系统目录身份、六份完整 argv、空 host env 和上限均固定。它不复制或挂载用户 HOME、账号、业务根、SDK 或数据库。

原 plan SHA-256：`d857a88862a7581b5969e0a7436f72fdf874c4b3b70e1b34d21909612d7cfda2`，13415 bytes；parent SHA 为 `8c36086ffc2c808d380c540c46ca37c687517c7a59b6da1524135a9c55d5f512`，Node worker 为 `d0c4d9f2adbcad0ddce228e9a655647b2d9b527d6aaa35e4906721dfbcf2eb0a`。plan 的 `nativeAuthorized=false`、`nativeStarted=false` 保留执行前语义；执行事实另存 started／execution，不改写原 plan。系统挂载不是完整镜像内容锁，不能把这些 metadata 检查当作实际 runtime 通过。

仅在取得本六场的独立显式授权后，按正常属主执行：

```sh
/usr/bin/python3.11 -I -S -B scripts/pi-probe-owner-fd.py run-native --directory /tmp/pi-durable-owner-fd-native-review02-normal-owner --native-owner-fd-probe
```

六场仅验证 fd3 入口和 Node 退出、controller 正常退出、原 controller pidfd SIGKILL、原 Node pidfd SIGKILL、错误 fd 拒绝、高号 64 拒绝。实际锁竞争只针对临时原锁叶；信号只针对事前和动作前核验过的本场原目标，不触及活动实例或未知 PID。每场 15 秒、总上限 120 秒、stdout 64 KiB、合计输出 1 MiB，保存 started/失败/未运行原事实，不自动刷新或重用已 started 目录。

授权可覆盖这六场相同边界内的必要修复重跑；每次使用新临时目录和重新审查的固定 plan，保存旧失败／源／原回执。不得扩大为 owner／SQLite／Harness／模型／账号／产品部署测试；扩大范围须另准备材料。要求独立授权来自仓库 `AGENTS.md` 的“真实 smoke 为独立显式步骤，需用户明确授权”，此前 SDK7 授权不提供本六场的真实锁／fd／信号资格。

## review02 六场实际观察与验收

2026-10-06 收到本六场及同边界必要修复重跑的显式授权后，按上述固定命令以正常属主执行，入口退出 0。六场均 started／observed／complete／exit0，stderr 为 0 bytes，materialIntact=true、parentFailed=false。本次没有原生失败或重跑；默认阶段旧失败仍单独保留。

| 场景 | controller wait | Node wait | 入口接受 | 后代启动 | 原锁切点 |
| --- | ---: | ---: | --- | ---: | --- |
| entry-and-node-exit | 0 | 0 | true | 1 | busy／busy／free |
| controller-exit | 0 | null | true | 1 | busy／busy／free |
| controller-kill | -9 | null | true | 1 | busy／busy／free |
| node-kill | 0 | -9 | true | 1 | busy／busy／free |
| wrong-fd | 0 | 0 | false | 0 | busy／busy／free |
| high-fd-rejected | 0 | 0 | false | 0 | busy／busy／free |

四个正例观察到 fd3 原入口接受、CLOEXEC、固定后代退出 0 且原锁 device／inode 零匹配。controller 正常退出或被杀时，原 Node 仍活且原路径竞争 busy；最后原持有者退出后竞争 free。两个负例拒绝入口且后代零启动。孤儿 Node 的 waitstatus 未获得，保留 null；不能从出口观察补造正常退出码。高号拒绝没有启动后代，不能作为高号 fd 无泄漏证明。

root 与独立 executor 对稳定工件复审无开放 P1/P2：138 节点封闭树、六份 argv、严格 typed stdout／state、原 oracle、原锁物理关联、八项材料和三固定二进制／系统目录身份均核对。八十九输入归档 `durable-owner-fd-native-observed-review02/`，包括原执行前文档；复制品只保留原字节及原物理回执，不冒充原 inode。此次六场授权验收后闭合，已 started 目录不得复用。

每次 pidfd poll mask 和 proc gone／两次 Z 分支没有独立 trace，因此不声称实际触发了 HUP-only 或某个特定退出分支。namespaceTermination 始终 unknown，固定后代测试不证明任意进程树／IO 全部终止。本探针没有接入 OwnerRecordScope，不证明 bound／ready／released、数据库、恢复、模型权限、T081／T090 或 Full；正式完成仍为 7/100，全部产品 gate 保持 false。
