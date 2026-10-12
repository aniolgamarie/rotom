# 服务索引的协调与发布顺序

2026-10-07，root 在完整快照、固定账户只读和纯后继关系设计之上确定下一处事务方向。本文是独立审查候选，只描述磁盘写者需要达到的行为；未授权 IO 实现、Full 引用／issuer、controller、真实锁／进程、开库或产品入口。下述 original grant／current reference／private channel 均须由真实受控 producer 提供，不能用数据对象、回调 true、假 Popen 或合法 JSON 补齐。

## 一份逻辑权威和固定协调对象

固定账户来自原 EUID/passwd，所有目录的安全祖先及账户 policy 沿已接受 readonly 设计。`<account_home>/.agentcfg-pi-durable/index.json` 是唯一 service／init request／association 逻辑权威；不得扫描残留文件重建索引。固定同目录 `index.lock` 是协调对象，要求原 UID、exact0600、普通单链接、size0；创建后不替换、不删除、不截断、不重建成同名新锁。控制目录必须原 UID/exact0700。account／控制目录和 lock 的 device/inode/UID/mode、lock basename与原 fd 必须在取得锁及每个发布窗口重新对应。

写者用独立原 open-file-description对该 lock 取得 `LOCK_EX|LOCK_NB`。锁忙直接拒绝该次入口；不持 account index 锁无限等待另一个 owner。写者不暴露 raw fd，也不从 caller 的 fd／pid／fstat／字段推导持有权。所有受管 index writer 均经过这一协调；普通 reader 不取得锁、不等待、不修复。锁不是抵抗任意同 UID 外部改写的保证，外部改写使当前引用失效；本设计不签发磁盘回滚检测或历史最高 generation 证明。

协调只由原 issuer/server 持有，不传给 controller、Node、SDK 或受限任务；open 均CLOEXEC，原 controller 的 bootstrap 继承列表避开 fd3，Node 的 pass_fds仍仅storage原3。index锁与storage锁不是同一对象。首次路线的唯一锁序是 issuer 的index EX → controller 的fresh storage EX；controller 不另取index锁，issuer不借storage句柄写owner，也不在同一个调用里等待一个会反向取index锁的进程。已有服务的运行／恢复路线另定，不能反向拼接本首次协议。

## 首次控制锚的创建

原当前 Full 引用、明确本次初始化确认、专用 issuer、自己原 Popen/bootstrap、controller fd3空闲且原预留槽确认必须先闭合。一次 grant 在最后 current／policy／cancel／deadline核前销毁可用状态，失败也不能再消费。检查从未初始化不能依赖只读 Inspection；writer在消费之后重新捕获原account fd／完整目录来源和固定控制basename的absence expectation。

若该固定控制basename在原account fd下第一次已存在，此次不是首次锚创建。不论其为空、缺lock、缺index或畸形，都不能进入新目录路线，也不做chmod、补lock或清理。若首次明确缺失，使用原account fd相对固定basename排他mkdir0700；FileExists或任意失败不重试。mkdir成功后立即以固定nofollow目录flags打开，核新对象原UID/exact0700/原basename身份，捕获其真实index_identity并绑定到同一私有reservation的原absence／grant，然后fsync原account目录。不能把absence构造成虚假的DirectoryIdentity，也不能重新签一个grant。

在该本次新目录内创建固定index.lock：相对原目录 `O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK`、mode0600，核真实普通单链接/原UID/size0/exact0600，fsync文件和原控制目录，再原fd EX/NB锁；保留原account／新control／lock来源。任何首次锚、打开、同步或锁失败都让原grant永久停用。未知或残留锚不自动回到fresh；重启看到旧空锚不能假定自己是中断的原creator。当前已有 public Tree(create=True)/ensure_private 会创建缺失父目录，不能用来决定首次锚或补齐旧目录。本段需要固定原相对fd的专用受控IO，不调用旧模块私有helper或改旧opener policy。

## 已有完整索引的受控读取

只有已经安全打开的旧control、原既有index.lock及EX锁，且固定index.json首次stat为合法存在，才进入已有索引修改路线。不能因index缺失而新建；不能用旧Inspection的snapshot／文件身份作为expected或原来源。writer在锁内重新捕获完整合法文件：原UID、0600、普通单链接、有界非空bytes，stat/open/fstat/读前后及decode后八项完整身份沿readonly切点，snapshot的account/index identity必须对应当前真实目录。

保存本次原完整bytes、规范snapshot及文件身份；实际文件可能是合法但非canonical排序，不因读取自动重写。后继纯验证使用独立原snapshot，内容发布用following的public canonical encoder。已有服务和关联保持及generation恰加一须经已接受的有限transition验证；该结果仍须与本次原授权的request／service／instance／目的和current Full引用比对。构造出一个合法后继不产生写入资格。

同一初始化request_id在快照中已存在，首先只能按原完整初始化identity和目标关联核对并报告原service ID／stage；错identity固定冲突。即使匹配也不再生成reservation、不增加generation、不重写、不分配新ID、不重发fresh-storage许可。service/association原键已被占用但request不同也不能自动换指向；关联旧service是另一次专门明确授权。随机service ID只有确定无该原request且允许新增原关联之后才分配一次，保存于原私有reservation；发布失败后不可换ID再试。

## reserved 发布与一次 fresh storage 许可

首次新锚使用initial规则：generation1、恰一reserved服务、init request完整绑定、恰一初始关联。已有完整索引新增服务使用reserve-service规则，所有旧行完整保持。声明storage路径取自原current引用的首次state_root，不能由client选择，也不能用deployment新digest生成新空库绕过已有对象。

首次写只能在本次新锚、原absence及原grant／reservation完整核验后调用 public `Tree.write_new("index.json", bytes)`；旧完整索引只调用 public `Tree.replace(..., mode=0o600, expected=原identity六项)`。writer需另核uid/nlink等八项及原目录／lock／current来源，Tree自己的六项expected不能代替它们。Tree接口没有kernel CAS，最后stat和replace之间仍有外部竞争窗口；本协议只约束遵守原锁的受管写者。首次write_new内部link发布与temporary unlink之间可能有暂时nlink2；此时readonly拒绝该对象，不把它当正常incomplete或初始化许可。

一旦进入任何public发布调用，保守记该次publication可能已经发生。异常即unknown，不依exception文案推断未写，也不重试、回滚、另行清理临时痕迹或重新生成ID。原public Tree内部已经定义的temporary清理及父目录同步仍属于该次调用，不能把其finally的完成或错误当成业务未发布／已持久证明；本写者不在返回后另发修复操作。调用返回之后还须得到明确的文件及父目录fsync回执、完整合法singlelink0600新文件原字节readback、原account/control/lock对象和grant/source最后核；单次readback成功不能补齐已经失败的fsync。原公开Tree调用的完整成功回执及后续独立readback各自保留。

只有这份reserved完整持久回执和之后的原privatechannel整帧send/flush及postpure核全部成功，才允许原controller一次fresh storage创建。私有窗口必须在首可能触发controller响应的send之前打开；早ACK只存有界候选，不补齐partial send、flush或source失败。未知send/ACK也不能重发许可。controller仍要求storage路径排他新建，旧空目录／缺owner／已有storage都失败，不用reserved stage推断路径不存在。

## registered 发布、协调释放与 Node

原controller创建fresh storage、取得原storage EX、dup到自己原预留3并完整持久acquired之后，向原privatechannel回报真实storage identity；issuer只接原child、原通道、原reservation及完整阶段对应回执。合法metadata本身不证明原OFD、controller存活或acquired持久化，这些由controller producer及另行原生资格承担。

issuer仍持同一index锁，重新核其原index文件identity／reserved全文／所有原source，构造register-storage后继，仅该service的stage和storage_identity改变、generation+1。完整发布／fsync／readback回执后才发送原registered ACK。该ACK仅登记metadata；原controller继续持storage锁等待，收到完整ACK也不能启动Node、从普通reader推断index锁释放或用EOF代替释放确认。ACK未知保留原SID／路径且不发送下一阶段；不能因磁盘现已registered就自动补ACK或继续旧被中断流程。

正常释放时永久停止这次index变更入口，确认没有未结index IO producer或后续可执行写回，再close-only关闭自有协调锁fd，并保存明确本地关闭回执。关闭异常不宣称已释放，不retry可能复用的raw fd、不LOCK_UN；其他自有句柄继续各尝试一次清理。controller没有该锁fd，不能从此前metadata ACK获知parent本地close的结果。

因此必须有独立、只用原privatechannel的release/launch阶段。issuer确认完整registered ACK、明确协调close回执以及最后current/source核后，消费原reservation的一次release发送状态；进入首write之前记该阶段可能已交付并永久禁止重发。原controller只在自己等待此阶段时接受一次完整匹配原SID／registered内容／原reservation的原issuer消息，核自己的原storage锁／fd3、当前来源／取消／时限后，才消费自己的一次Node launch状态，进入既定hello／bound／closing生命期。不能从重建的数据proof、任意pipe、普通查询或同UID文本取得这个阶段。实际消息schema、child/source原producer及双方接收窗口另冻；registered仍不是ready／DB／模型资格。

原send/flush和postpure回执决定issuer能否报告该交付明确成功，早ACK仅私有候选；它们不能倒置成controller收到完整命令之前已观察到的parent事实。首write之前失败时零Node；一旦可能交付release命令，controller可能在parent write/flush返回前已经合法启动唯一Node。此后send/ACK/最后核失败是launch unknown，不能保证零Node，也不能用丢ACK当未启动证明。保持原SID／storage／controller引用并按原生命周期监督，零第二次launch、零补发或新ID；数据库／模型另有未放行的阶段，不能因可能已有零SDK Node而继续开库。

## 失败、迟到与原 ID 保留

| 切点 | 必须保留的事实与禁止续做 |
|---|---|
| 消费后、mkdir之前失败 | 原grant已消耗，零自动重试；不把新确认当原token重放 |
| mkdir／lock或首次index发布前失败 | 原新锚/对象可能残留，原私有request／SID若已分配保持；旧空锚不修复、不换fresh |
| reserved发布可能发生但完整持久回执未知 | 原request／SID／首次关联不换；零fresh-storage许可；仅只读观察 |
| reserved已完整、fresh-storage发送或ACK未知 | 原controller可能已创建并持storage锁；零重发/Node，不能释放或虚构该storage保护 |
| acquired已完整、registered发布／ACK未知 | 保留原storage和锁，index可能仍reserved或已registered；零Node／新ID／补ACK |
| 协调close或release首write前原source/producer静止未知 | 零release命令／零Node；停止新入口，不把异常当释放或业务成功；不能强关未知来源fd |
| release命令可能交付后send／ACK／最后核未知 | 原controller可能已启动唯一Node；保留原对象并监督，零第二次launch／补发／新ID／DB grant，不声称零Node |
| parent退出／controller原通道EOF／迟到消息 | release前零Node，可能交付后保留可能已启动事实；旧controller按既定unknown-held保护storage，新parent仅查原ID、不重建grant或接管 |

未知index结果并不要求永久阻止不同服务的所有元数据操作，但释放协调前必须确认本写者已永久退休且本次index IO不会再写；同步调用抛错说明结果可能未知，不说明仍有异步producer。若无法证明静止，继续保留协调锁而不在finally释放。unknown storage由原controller持其原storage锁独立保护，issuer不能因index可以释放就宣称storage可用。迟到acquired／ACK仅作为有限事实保存，不能触发旧注册写回／Node；original controller与受保护IO的停止仍沿held-pidfd／unknown-held，不能从通道EOF、PID或metadata合成释放。

外部恢复旧快照／删除锚／改目录不在当前逻辑锁能阻断的范围内；旧数据不能成为never-created或takeover证明。正式维护恢复还须原物理历史／活动owner／存储和运行身份检查，不由本包自动修复；恢复或历史回滚无法核对时维持unknown，不能清表或换ID绕过。

## 默认和原生验收的分层

实际写者API及唯一可写文件范围尚待root冻结原producer／issuer／bootstrap接口。本稿即使通过设计审查也只关闭顺序选择，不开始实现或让fake capability开启IO。后续默认使用自己的临时账户/Tree/文件、假原controller及受限故障切点，原授权构造仅隔离test seam；分别验证首次／已有完整／忙锁、旧空锚拒绝、保存原request-ID查找、64/512容量、expected八项与source漂移、singlelink发布窗口、每一发布/同步/readback/send/ACK/close前后故障、迟到零写和没有automatic retry。另必须直接观察registered ACK后仍零launch、close成功前零release、首write前失败零Node，以及完整release已被fake原controller接收并launch一次但parent flush／ACK丢失时保留launch unknown且零第二次；不得用一个从不消费命令的fake把可能启动覆盖为零。默认FS事实不证明真实controller/OFD/SDK/SQLite或断电。

真实Linux组合须另准备原材料和明确授权，观察实际flock竞争、原fd3/OFD／pidfd、两进程退出／unknown-held、私有pipe碎片和ACK、原index/storage fsync/readback。SIGKILL只验证对应进程切点，不冒充断电／介质损坏、任何provider尝试或业务根隔离。待授权d61799仍只含原三场恢复，与本新设计无关；旧八场授权不复用。正式7/100、全部产品gate、严格计量前AUTO OFF保持。
