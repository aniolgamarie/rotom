# Durable 单写所有者与原锁持有链

2026-10-06，主代理根据现有Python锁、进程身份和监督回执的静态证据确定Linux路线。以下是实现决定；首稿时没有Node持锁或双进程竞争运行证据。后续授权的六场基础fd／锁探针已有下述限定实测，产品长期owner与完整崩溃恢复仍未资格，T081/T090继续开放。首个记录实现只处理原锁下的所有者文件，不启动Node或打开Durable数据库。

## 所有者边界

一个持久存储目录对应一个专用Python监督者和一个Node写者。Python负责私有目录、原OS锁、所有者记录与进程身份；Node通过自有启动协议取得同一个原锁fd，之后才构造公开SQLite/Session/Harness。服务客户端、任务参数、模型返回值都不能提供或选择锁fd、所有者epoch、部署身份、数据库位置或SDK构造参数。只读工具与受限子进程不能挂载控制目录或取得锁fd。

复用`storage.instance_lock(Tree)`的EX/NB flock与close释放语义。必须持有原目录和锁文件的物理身份，锁文件不删除、不替换；每个准入窗口核原fd、原路径叶节点与目录身份一致。不能使用`pi_lifecycle.guard`的显式LOCK_UN释放方式承担跨Node的Durable存储锁，因为父进程解除共享open-file-description上的锁也会解除子进程的保护。Pi实例活动锁仍按原职责使用，不能把两个锁混成一个。

Node写者必须从受信专用监督者通过`pass_fds`继承同一open-file-description；父、写者两侧均保持原fd至各自写活动结束，并且都不调用LOCK_UN。父异常退出而Node仍活时，Node的原fd必须继续阻止新owner；Node退出而父仍活时，父继续持有，直到结束自身受保护写活动。Node自有bootstrap只接收私有启动通道与原fd，不把它传入SDK或业务backend，不向客户端暴露通用fd接入接口。是否确实同一flock持有链只能由独立进程实测签发，fd编号、fstat相同或owner JSON单独不足。

该Linux选择的内核语义已另查[Linux man-pages flock(2)](https://man7.org/linux/man-pages/man2/flock.2.html)：fork/dup后的描述符共享锁，任一描述符LOCK_UN即可解除，全部关闭才自动释放，execve保留锁。它是协作式锁；NFS/SMB和锁转换另有语义，取得锁也不证明全部close效果或进程退出。首批范围沿用契约的已测本地文件系统，不将其他挂载或恶意本机同UID程序纳入此锁保证；仍需实测本仓库实际fd持有链、原进程与未完成IO。

LinuxProcesses的boot/start_time/namespace/UID身份用于确认原进程。PID目录不存在才能按现有公开自有观察器记dead；PID重用、读取失败、部分记录、未知或仍活均不接管。PPID重置不等于退出。心跳超时、客户端断开、锁文件缺失、另一个boot字符串或SDK idle均不能单独作退出证明。跨重启的kernel boot证明和显式恢复接管属于后续独立资格；初版未知时保持recovery-required。

## 启动与停止次序

1. 检查已固定部署、私有存储目录、受控数据库/控制路径及平台能力，不启动SDK。
2. 原子取得该物理目录下的EX/NB锁，锁忙退出4，不扫描或终止活动实例。
3. 在锁内读取并完整检查原owner记录、部署/格式及原controller/writer身份。旧进程任何一方alive/unknown、不兼容、缺失重要字段或记录损坏均不覆盖、不删除、不开始新epoch。
4. 只有旧记录缺省的合法首次创建，或旧controller/writer均具有合格退出证据时，持久记录新的随机epoch及当前controller身份；新epoch不能由调用方传入或复用。此时仅为acquired，尚无数据库准入。
5. 从私有通道启动固定自有Node bootstrap，继承原锁fd；Node保持待命，零SDK/数据库/模型调用。记录并核对原writer的完整进程身份与一次启动绑定，持久回执确认后才可进入后续持锁资格与ready握手。
6. ready之后依次打开公开数据库、核WAL/FULL与部署身份、读取未完成任务和attempt账本。对账与模型资格未完成前不resume调度、不发送；unknown预算仍保留。
7. 停止先永久关闭新准入，持久closing，停止SDK/自有写入口，再核原writer退出、其他受保护写活动结束及私有退出回执。Node原fd随已核退出释放；controller此时必须仍持原锁，在该锁内原子持久写released并fsync文件/父目录，明确回执确认后永久停止所有owner写，最后才close-only释放controller原fd并退出。不得先释放最后原锁再写released，也不能在controller已退出后补写或由裸close/finally补造；released写前失败或写后丢回执保持unknown，不重新覆盖新epoch。Node/父退出不推导远端模型物理停止、零计费或预算退款。

launch、writer身份绑定、持久回执、ready、开库都是不同切点。任一写前/写后回执丢失均停止本次新入口，不自动重新launch/open、更换epoch或删除旧owner；原记录只能用于精确查询/对账。旧Node可能仍活时，即使监督者退出或另一个锁路径可取得，也不得启动第二写者。

合法首次创建必须由本次受信构造过程排他创建全新的私有存储目录，并保留原创建/目录句柄绑定；不能把调用方的create=true、目录为空或owner文件不存在当首次证明。create遇既有目录直接冲突，不复用、删除或覆盖；active打开既有目录时owner记录缺失一律recovery-required，连空目录也不自动初始化。首次创建在owner持久写之前失败留下的目录只能查询或经过后续明确维护步骤处理，不由恢复路径暗中清理。可序列化的codec元数据不代替原创建回执。

## 第一个有界实现包

先实现Python自有所有者记录与锁范围模块，复用原Tree、instance_lock和LinuxProcesses；Node的`owner.ts`只在持有链实际资格后接自有启动通道。首包不得将记录/临时替身证据称为Node owner或数据库准入。接口的具体字段与状态在编码前另行冻结，不能由executor自行决定锁、恢复或日志顺序。

此首包需要完整闭合记录、部署/目录/epoch绑定、原方法和receiver、在原锁范围内的旧身份核对、原退出证据与写前/写后未知的区分。所有保存均原子替换并fsync文件/父目录，不保存认证信息，不复制Durable任务队列。不得把owner记录的字符串或重构对象当不可伪造授权；真正准入必须由原控制面与实际原锁持有链签发。

默认测试使用临时私有Tree、合成/proc或身份/launcher/锁替身，不启动第三方宿主；核启动次序、busy、旧alive/unknown/复用拒绝、部署/物理目录/方法漂移、完整输入与未知字段拒绝、写前失败/写后丢回执零ready/零open、close不伪造released。实际双owner、Python父SIGKILL后Node仍持锁、Node退出父仍持锁、fd丢失/关闭、PID重用、磁盘满/只读另做显式独立进程材料和授权；不把SIGKILL当断电。

## 已有证据与尚未验证

复用静态包归档`durable-owner-reuse-static/`：五必要模块、一次已批准的定位预览和两份默认测试源码，共十三输入；未运行锁、进程或SDK。当前仓库没有已资格的Node长期flock路线，不能因Python监督者存在就声称跨Node所有者完成。

[基础fd／锁探针](native-owner-fd-probe.md)已按固定d857 plan在断网bwrap中运行六场并完成稳定验收，八十九输入归档 `durable-owner-fd-native-observed-review02/`，此次授权闭合。四正例核fd3入口CLOEXEC、固定后代零同inode，以及原controller退出／SIGKILL、原Node退出／SIGKILL的busy／busy／free锁切点；两负例核错误fd及高号fd拒绝。controller退出后的孤儿Node waitstatus为null，namespaceTermination始终unknown，未保存每次pidfd退出分支trace；不声称全部进程树／IO终止、OwnerRecordScope活Node finally安全、产品writer ready／released、SQLite／对账或冷恢复。该实测为此路线的有界基础，不能直接扩到产品生命周期。

后续必须核Node启动器确实保留原fd、不会提前开库、不会将fd泄漏给工具；重入/异常/取消不主动解锁仍活写者；原锁路径与真实存储别名保护、冷启动丢回执与boot恢复、停止期间未完成写IO、SDK/模型外部活动分别留证。实际Linux资格完成前，不对Mac或其他平台宣称通过。
