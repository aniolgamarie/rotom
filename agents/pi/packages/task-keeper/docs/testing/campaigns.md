# 缺口测试批次设计

状态：33 个批次均为测试设计；具体缺失层级、原始 WHEN/THEN、建议 file/name 和依赖见 [435 项逐项索引](gap-obligations.csv)。批次内列出的变体是最小展开集，不能挑其中一个成功样例就给全部 ID 记通过。夹具名是实施方向，不表示文件已存在。

共享执行约束、证据格式及竞态表见 [README](README.md)。每个义务只补其要求的层级；一批同时列出 U/A/P/E 不代表一份 mock 可以获得所有层级信用。

## G01 包加载、初始化及配置隔离

- 波次：B0；缺失层级义务：2。
- ID：CFG-003, CFG-011。
- 参考：ADR001/013/019;S5。
- 夹具：现有 config/workflows fixture；新增隔离 launcher 与假同步目标。

**操作步骤：** 在独立 HOME/PI_CODING_AGENT_DIR 内放置策略、auth、SQLite intent/unknown 哨兵；加载 disabled 包并执行 doctor/init；仅对临时 Pi 根执行两次包同步；新连接读回原等待任务。

**最低变体：** 无绑定 disabled；启用但角色/账号缺失；init 目标已存在/不可写；同步一次/两次；同步通用返回契约使用 fake target；allow_in_tests=true 仍不能绕过真实 writer 防护。

**独立断言：** O1: disabled/缺绑定零 HTTP；O2:预算、intent、unknown 不变；O3:临时 auth/策略逐字节与权限不变，包 identity 唯一；所有被写路径均位于隔离根。

**负向对照：** 在隔离副本中将路径 resolver 指向假受保护 home；launcher 在导入任何插件之前拒绝。不得以真实 Claude 文件作负向控制。

**实施依赖与边界：** 需先实现独立进程环境/写路径隔离门槛；不得运行全工具同步。

| 层级 | 待补义务 |
|---|---|
| A | CFG-003:A |
| E | CFG-011:E |

## G02 项目限制代数与禁止扩权

- 波次：B0；缺失层级义务：13。
- ID：CFG-004, CFG-005, CFG-006, CFG-008, CFG-009, T87, VAL-003。
- 参考：ADR005/006/013/019;S5。
- 夹具：现有 config/properties；新增 project-policy E fixture。

**操作步骤：** 建立用户预算12、required reviewer及可信 check；逐个写项目 override，reload 后提交同一合法任务；比较有效配置、拒绝原因和外部请求。

**最低变体：** 预算12→24/12/0；required 删除；未知保护开关；新argv/account/network；允许集合空/缺失/null；负数/小数/NaN/Infinity（JSON文本与对象入口分开）；重复收紧两次；Advisor on-demand/shadow 拒绝。

**独立断言：** O1:非法绑定不 spawn/send；O2:TaskSpec/预算未扩权；O4:定位非法字段；合法收紧仍能执行。P4仅验证本阶段关闭边界，不能充抵T66/T68/T69。

**负向对照：** 临时移除一个合并限制，单条件扩权测试必须失败。

**实施依赖与边界：** 现有逻辑可扩测；项目新可执行命令必须继续被拒绝。

| 层级 | 待补义务 |
|---|---|
| U | VAL-003:U |
| S | CFG-004:S, CFG-005:S, CFG-006:S, CFG-008:S, T87:S |
| E | CFG-004:E, CFG-005:E, CFG-006:E, CFG-008:E, CFG-009:E, T87:E |
| V | VAL-003:V |

## G03 Qwen 多服务绑定与分类可替换

- 波次：B1；缺失层级义务：8。
- ID：CFG-002, REC-002, TK10。
- 参考：ADR002/004/010;S5/S6/S9。
- 夹具：两份配置化服务响应 fixture；实际 Pi loopback transport。

**操作步骤：** 对同一长任务使用服务A/B的不同 provider/model/baseURL/classifier 配置；A返回429结构化错误，B返回各自 usage/window 结构；经同一恢复入口继续；交换模型显示名称复跑。

**最低变体：** 通用合成A/B与有来源的脱敏真实样本分列；HTTP/body冲突；未知code；服务更换但TaskSpec不变；classifier缺失拒绝；不能根据Qwen字符串选择代码分支。

**独立断言：** O1:接收端真实重试序列；O2:归一化category/notBefore及scope连续；O4:原来源、实际route、分类理由保留；核心代码摘要不因环境更换而变。

**负向对照：** 交换模型名称后行为随名称而变，或将resource_pressure误写monthly_exhausted，必须失败。

**实施依赖与边界：** 6.1仍缺有来源的Qwen多服务脱敏样本；合成fixture不能冒充真实来源。

| 层级 | 待补义务 |
|---|---|
| U | CFG-002:U |
| S | REC-002:S, TK10:S |
| A | CFG-002:A, REC-002:A, TK10:A |
| E | REC-002:E, TK10:E |

## G04 能力证书、真实生效配置与启动屏障

- 波次：B0；缺失层级义务：27。
- ID：EXE-001, EXE-002, EXE-003, EXE-004, EXE-007, EXE-012, T04, T06, T07, T08, T17, T48, T52, VAL-011。
- 参考：ADR002/004/007/014;S1/S2/S3/S4/S5。
- 夹具：现有 subagents/native-owner；真实Pi候选依赖的独立临时副本。

**操作步骤：** 先用固定lock的foreground/fresh正常启动并检查nativeRunId；每次只改变一项运行契约，再通过真实preflight/事件通道启动；保存requested/resolved/observed三者及doctor。

**最低变体：** Pi或patch哈希、listener入口、thinking mapping/tools/context/cwd单项差异；ack成功但IPC不可写/不可读；provider扩展缺失；后台/fork未认证；response model不一致/缺失；仅可选元数据缺失的成功对照；关键错误被吞且无外部事实。

**独立断言：** O1:屏障未满足零模型发送；O2:原生身份与工件真实关联，observed未知保持未知；O5:失败child退出；doctor按组合显示不支持，不全局禁用合格P1。

**负向对照：** 在临时adapter副本把注册ack当ready、requested当observed或引用另一安装的lock，相关负例必须失败。

**实施依赖与边界：** 未支持后台/fork不要求新增产品能力；验证拒绝与合法foreground正例。

| 层级 | 待补义务 |
|---|---|
| U | EXE-003:U, EXE-004:U, EXE-007:U, EXE-012:U, T06:U, T07:U, T08:U, T52:U |
| A | EXE-001:A, EXE-002:A, VAL-011:A, T04:A, T06:A, T07:A, T08:A, T17:A, T48:A, T52:A |
| P | T04:P, T06:P, T07:P, T08:P, T17:P, T48:P, T52:P |
| E | EXE-007:E |
| V | VAL-011:V |

## G05 投递已接受但启动或执行中断

- 波次：B0；缺失层级义务：8。
- ID：EXE-005, EXE-006, T01, T02。
- 参考：ADR004/010/014;S1/S5。
- 夹具：subagents fixture、可控制启动前退出的真实child。

**操作步骤：** 父端得到accepted后用barrier令child在agent_start前退出；另一用例令实际child收到取消且上报exitCode0/interrupted；等待父端持久结果并查询job。

**最低变体：** 接受前失败/接受后启动失败；正常exit0；exit0+interrupted；timeout+exit0；缺原生终态；失败原因在父端压缩后仍可见。

**独立断言：** O1:启动失败无模型请求；O2:delivery/execution/acceptance分维记录；O4:不得COMPLETED，原始原因到receipt/父模型；O5:supervisor确认process身份与退出。

**负向对照：** 将accepted或exit0单独转换success，必须误触断言。

**实施依赖与边界：** 需子进程屏障，不能只构造结果对象给A/P层。

| 层级 | 待补义务 |
|---|---|
| A | EXE-005:A, EXE-006:A, T01:A, T02:A |
| P | T01:P, T02:P |
| E | EXE-005:E, EXE-006:E |

## G06 关键事件去重、断序与补投递

- 波次：B0；缺失层级义务：10。
- ID：EVD-001, EVD-002, T14, T15。
- 参考：ADR004/010/011/018;S1/S5。
- 夹具：真实SQLite双连接、生产事件写入器、进程IPC supervisor。

**操作步骤：** 按1/2/3写关键事件，注入2缺失、3先到、同ID同payload重投与同ID异payload；杀父进程后以新连接重放通知并查询依赖动作。

**最低变体：** producer/run/job错误；关键seq缺失vs低优先级进度丢失；完成通知落库后丢失；相同eventId异payload与相同producer/seq异payload；对账可恢复/工件已缺失。

**独立断言：** O2:事件唯一且冲突不可覆盖；O1:补投递不产生新spawn/request；O4:关键未知阻塞依赖动作，进度缺失标stale；正常补齐后可推进。

**负向对照：** 移除事件唯一检查或把关键洞当普通丢进度，必须失败。

**实施依赖与边界：** 需持久事件故障注入与独立连接；现有U结果不可自动提为P。

| 层级 | 待补义务 |
|---|---|
| S | EVD-001:S, EVD-002:S, T14:S, T15:S |
| P | EVD-001:P, EVD-002:P, T14:P, T15:P |
| E | T14:E, T15:E |

## G07 五维结果、合法恢复及PARTIAL

- 波次：B2；缺失层级义务：18。
- ID：EVD-003, EVD-010, EVD-011, EVD-012, T03, T05, T09, T12, T13, T61。
- 参考：ADR004/005/014/017/018;S15/S25/S26。
- 夹具：task/recovery reducers、固定workflow与独立verifier/reviewer。

**操作步骤：** 手写五维真值表；先全满足形成COMPLETED，再每次仅撤去一个required条件；执行失败→授权恢复→当前快照验收，并在新连接读取历史；optional失败按预先TaskSpec分别允许/禁止PARTIAL。

**最低变体：** delivery/execution/contract/acceptance/observation分别false/unknown/not_run；required reviewer失败；final正常但工具错误未解决；明确resolvedFailure关系合法/缺失/跨快照；取消后迟到成功。

**独立断言：** O2:失败attempt不被改写，成功job引用新证据；O4:PARTIAL披露具体缺口且禁止临时降级required；完整正例不得永久blocked。

**负向对照：** 让request_finish决定COMPLETED或删除未解决failure条件，单条件反例必须失败。

**实施依赖与边界：** 9.6的完整PARTIAL/复用语义需补实现后再跑E；不能靠构造receipt声称端到端通过。

| 层级 | 待补义务 |
|---|---|
| S | EVD-003:S, EVD-010:S, EVD-011:S, EVD-012:S, T03:S, T05:S, T09:S, T12:S, T13:S, T61:S |
| A | T05:A |
| P | T05:P |
| E | EVD-011:E, T03:E, T09:E, T12:E, T13:E, T61:E |

## G08 EvidencePacket容量、引用与不可信日志

- 波次：B0；缺失层级义务：13。
- ID：EVD-005, EVD-006, T54, T55, T56, T58。
- 参考：ADR004/005/016;S11/S12/S19。
- 夹具：packet/artifact fixtures、真实父Pi上下文捕获HTTP端。

**操作步骤：** 固定job/snapshot的源码、日志和claims；构造硬状态预算前一字节/恰好/超限；注入不存在、跨job、倒置范围引用及日志重置预算指令；提交到实际packet/决策入口。

**最低变体：** Unicode与超长错误组；完整索引分组摘要；工件hash篡改/缺失；合法引用但只是worker自述；跨快照；日志含shell或伪造成功；所有引用合法且预算足够的正例。

**独立断言：** O1:非法packet不得派发；O2:预算/权限/Outcome不变；O4:PACKET_TOO_LARGE明确且必需事实不被裁掉，claim保持claim；真实请求body核对硬状态。

**负向对照：** 删掉最大的一组必需错误让packet勉强通过，或把claim晋级check，必须失败。

**实施依赖与边界：** A/E需要实际父模型请求输入，不是仅检查compile结果；无外发时观察明确拒绝。

| 层级 | 待补义务 |
|---|---|
| S | EVD-005:S, EVD-006:S, T54:S, T55:S, T56:S, T58:S |
| A | EVD-005:A |
| E | EVD-005:E, EVD-006:E, T54:E, T55:E, T56:E, T58:E |

## G09 失败五层传播、低噪声状态及无UI

- 波次：B1；缺失层级义务：21。
- ID：CFG-014, EVD-004, T10, T11, T53, T57, T83, T84, VAL-015。
- 参考：ADR004/007/014/018;S12/S19/S26。
- 夹具：RPC/PTY Pi、压缩服务fixture、结构化输出observer。

**操作步骤：** 生成不同类别required failure并压缩/截断历史；捕获raw→SQLite→receipt→父模型下一请求body→PTY或无UI输出；用fake clock驱动100次相同状态更新，再插入关键变化。

**最低变体：** content=Done/details含error；旧工具错误后native成功；多个错误组；脱敏marker；关键通道失效stale；等待时间/nextPermit/owner/unknown；无footer插件；无UI模式。

**独立断言：** O4:逐类别/计数/receipt ID/route/缺口跨五层一致，敏感marker全链零出现；O2:progress不改Outcome；更新次数不超声明节流阈值且关键变化及时通知。

**负向对照：** 仅从父模型input删除blocker（保留details和DB），传播测试必须红；调低UI文字不能使receipt通过。

**实施依赖与边界：** 传播oracle需逐层字段对应；没有父请求时应记录阻塞输出，不伪造该层已发送。

| 层级 | 待补义务 |
|---|---|
| U | CFG-014:U, T10:U, T11:U, T84:U |
| S | EVD-004:S, T10:S, T11:S, T53:S, T57:S, T83:S, T84:S |
| A | CFG-014:A |
| P | VAL-015:P |
| E | CFG-014:E, T10:E, T11:E, T53:E, T57:E, T83:E, T84:E |
| V | VAL-015:V |

## G10 提议新鲜度、唯一动作及重复指纹

- 波次：B2；缺失层级义务：13。
- ID：EVD-007, EVD-008, EVD-009, RTB-019, T59, T60, T62, T63, T64, T65, T70, T85。
- 参考：ADR005/006/016;S11/S12/S13。
- 夹具：decision-ledger、受限测试提议入口、真实TaskService。

**操作步骤：** 生成合法proposal后在dispatch前barrier修改source/TaskSpec/授权，逐项检查失效；另一分支只改心跳或费用，保留decisionRevision并再次预算准入；重复提交同fingerprint。

**最低变体：** 空/非法/多对象/截断JSON；任意shell/provider/删除required；资源不足/恢复充足；合法proposal全条件成功一次；等待期间取消；Advisor仍关闭，用通用提议契约fixture执行，不能声称在线Advisor。

**独立断言：** O1:无效或重复提议零额外发送/副作用；O2:TaskSpec不可写低、fingerprint只一份、费用不机械换revision；O4:拒绝原因包含stale或预算等实际条件。

**负向对照：** 跳过dispatch前二次准入或每次心跳增加revision，分别使安全反例和可进展正例失败。

**实施依赖与边界：** 公共提议入口尚不足时需要受限测试harness接生产dispatcher；不能增设旁路dispatcher。

| 层级 | 待补义务 |
|---|---|
| S | RTB-019:S |
| E | EVD-007:E, EVD-008:E, EVD-009:E, RTB-019:E, T59:E, T60:E, T62:E, T63:E, T64:E, T65:E, T70:E, T85:E |

## G11 存储故障、迁移备份与回退

- 波次：B0；缺失层级义务：7。
- ID：EVD-013, T47, T76。
- 参考：ADR010/011;S1/S5。
- 夹具：SQLite schema1真实fixture、只读/损坏副本、将来迁移测试driver。

**操作步骤：** 建立含intent、unknown reservation、owner与工作区引用的数据库；分别注入SQLITE_BUSY/commit失败/驱动ENOSPC/工件缺失；在迁移备份、改schema、commit、恢复各切点中断再重启。

**最低变体：** 已初始化DB消失；header损坏；未来schema拒绝；备份缺失/hash错误；回退不认识新字段；备份恢复到独立目录；未知预算和未结外部动作必须保留。

**独立断言：** O2:新连接核对所有主键、预算和unknown；O3:原DB/现场/备份可保留且权限正确；O1:异常后没有以新任务身份发送。

**负向对照：** 迁移时丢一条unknown或fallback新建空DB，守恒断言必须失败。

**实施依赖与边界：** 3.6/12.2一般迁移与restore未实现；未来schema夹具只是拒绝测试，不等于真实迁移通过。ENOSPC只能驱动注入或有限独立FS，禁止填真实磁盘。

| 层级 | 待补义务 |
|---|---|
| S | T47:S, T76:S |
| P | EVD-013:P, T47:P, T76:P |
| E | T47:E, T76:E |

## G12 外部调用C0–C5崩溃与未知ACK

- 波次：B0；缺失层级义务：11。
- ID：EXE-008, REC-021, T39, T40, T71。
- 参考：ADR003/009/010/011;S1/S5/S9。
- 夹具：现有store-worker/process，新增真实start/continue/verify三类切点hook。

**操作步骤：** 对start、continuation、可信verify各执行C0–C5；supervisor收到精确切点信号才kill父进程；外部接收端独立保存动作ID及生效事实；新进程对账，查询持久状态后尝试继续。

**最低变体：** 每切点×3动作=18基本轨迹；已证明未发送/已确认结束/未知三分支；ack丢失/原生工件缺失；C5仅补通知；不得把store-worker模拟调用当真实adapter三类覆盖。

**独立断言：** O1:外部同动作不重复；O2:ack/settle最多一次且unknown不释放；O3:verify/writer副作用计数不增；O5:对账使用原进程启动身份，不能仅PID。

**负向对照：** 在C2/C3重启时重发相同动作、C5重复settle，接收端计数和账本断言必须失败。

**实施依赖与边界：** 需生产adapter切点可观测性，部分切点目前只有底层P证据；缺原生对账能力保持BLOCKED_UNKNOWN。

| 层级 | 待补义务 |
|---|---|
| U | T71:U |
| S | EXE-008:S, T71:S |
| A | EXE-008:A, REC-021:A |
| P | EXE-008:P, REC-021:P |
| E | REC-021:E, T39:E, T40:E, T71:E |

## G13 唯一owner、撤权及失联writer

- 波次：B0；缺失层级义务：27。
- ID：EXE-009, EXE-010, EXE-011, SCH-014, T41, T42, T49, TK14。
- 参考：ADR003/008/010/011;S1/S5。
- 夹具：真实parent/child/descendant三进程，持续写sentinel，独立supervisor。

**操作步骤：** writer每次获barrier许可写一次；令parent失联或lease到期，启动竞争owner；在child取消ack但descendant仍活的窗口请求第二writer；最后由supervisor确认原process-group结束再对账。

**最低变体：** 同scope第二自动controller；旧epoch迟到回调；PID复用身份不匹配；普通/脱离process-group descendant；停止全部/部分/未知；读日志与独立workspace诊断继续。

**独立断言：** O1:未知writer期间第二writer零启动；O2:claims/unknown保持，迟到事实可记录但不复活job；O5:真实存活/写入记录优先于cancel ack；确认结束后合法竞争者可进展。

**负向对照：** 只按lease释放claim、用cancel ack当终止证据，必须使双writer检测失败。

**实施依赖与边界：** 5.5的任意外部工作覆盖不足；无法追踪的组合必须拒绝认证，测试不宣称OS沙箱。

| 层级 | 待补义务 |
|---|---|
| U | T41:U, T42:U, T49:U, TK14:U |
| S | EXE-009:S, EXE-010:S, EXE-011:S, SCH-014:S, T41:S, T42:S, T49:S, TK14:S |
| A | EXE-009:A, EXE-010:A, EXE-011:A, T49:A |
| P | EXE-009:P, EXE-010:P, EXE-011:P, SCH-014:P, T42:P, TK14:P |
| E | SCH-014:E, T41:E, T42:E, T49:E, TK14:E |

## G14 静默构建、请求timeout与整体deadline

- 波次：B1；缺失层级义务：12。
- ID：EXE-013, REC-011, REC-012, T16, T51。
- 参考：ADR008/010;S5/S9。
- 夹具：VerifyRunner真实静默子进程、挂起HTTP流、可控期限。

**操作步骤：** 构建启动后不输出且通过独立heartbeat保持存活；期限前查状态，期限到后走终止协议；另设quota forever但单次HTTP超时/整体deadline先到，抓取消和对账。

**最低变体：** 无输出但活/已死；toolTimeout/requestTimeout/native deadline分别先到/相等；忽略SIGTERM与孙进程；timeout时已发送未知；forever仅额度等待不使单请求无限。

**独立断言：** O5:期限前不误杀，期限后受控group终止或明确unknown；O2:超时语义及预留保留；O1:unknown后无马上重发；O4:静默与停滞不同诊断。

**负向对照：** 去掉requestTimeout或以无输出直接失败；独立watchdog/成功对照必须发现。

**实施依赖与边界：** 有限真实watchdog只作为挂死失败阈值；事件顺序不靠sleep猜测。

| 层级 | 待补义务 |
|---|---|
| U | EXE-013:U, T16:U |
| A | EXE-013:A, REC-011:A, REC-012:A, T16:A, T51:A |
| P | EXE-013:P, REC-011:P, REC-012:P, T16:P |
| E | T51:E |

## G15 临时额度与永久、网络故障的分类边界

- 波次：B1；缺失层级义务：9。
- ID：REC-003, REC-004, REC-005, T20, T26。
- 参考：ADR004/010;S6/S9。
- 夹具：HTTP/body/headers表驱动fixture及真实Pi错误适配器。

**操作步骤：** 真实Pi接收单个错误后读取归一化failure及下一动作；分别喂resource usage、429、401/403、billing、policy、context、连接失败与unknown；耗尽有限network政策。

**最低变体：** HTTP429+auth body优先级；usage allocated quota exceeded有来源样本；HTTP200 error body；过载与quota分离；非法/缺失code；网络maxAttempts/maxWait边界N−1/N/N+1。

**独立断言：** O1:永久错误无无限探测、网络上限后零新增；O2:resource pressure不写月额度耗尽，unknown不当临时额度；O4:保留分类依据且脱敏。

**负向对照：** 将所有错误归429或网络耗尽转forever，接收端上限断言必须失败。

**实施依赖与边界：** 真实服务分类样本来源属于6.1缺口；没有样本只能声明synthetic行为。

| 层级 | 待补义务 |
|---|---|
| S | REC-003:S, T20:S |
| A | REC-003:A, REC-004:A, REC-005:A, T20:A, T26:A |
| E | T20:E, T26:E |

## G16 冷却时间、时钟跳变与持久重启

- 波次：B1；缺失层级义务：12。
- ID：REC-008, REC-009, REC-010, T21, T25, TK11, TK12。
- 参考：ADR010/011;S6/S9。
- 夹具：fake wall/monotonic时钟、真实parent重启、独立receiver。

**操作步骤：** 写服务notBefore及本地cooldown；在前1ms/等于/后1ms触发调度；仅对测试clock注入墙钟回退/休眠跨多个tick；杀父后重启同scope并对账已发送状态。

**最低变体：** Retry-After delta/date/过去/非法/缺失；可信server Date与hour/week/month reset；jitter0/最大；时间不确定保守延后；重启多次不刷新deadline；无父进程期间零调度。

**独立断言：** O1:较晚notBefore之前零发送，补过期tick仅一个合法动作；O2:deadline/incident/counters跨进程不变；O4:恢复时间有依据。

**负向对照：** 比较符号反转、休眠后逐tick补发、重启重置stageEnteredAt，必须失败。

**实施依赖与边界：** P层可用注入clock但须真实进程/SQLite/receiver；不能改机器系统时钟。

| 层级 | 待补义务 |
|---|---|
| S | TK11:S |
| A | T21:A, T25:A, TK11:A, TK12:A |
| P | REC-008:P, REC-009:P, REC-010:P |
| E | T21:E, T25:E, TK11:E, TK12:E |

## G17 长上下文续跑、canary和完整流成功

- 波次：B1；缺失层级义务：21。
- ID：REC-001, REC-007, REC-015, REC-016, REC-017, REC-018, T18, T19, T22, T23, TK09。
- 参考：ADR003/004/010;S5/S6/S9/S19。
- 夹具：现有Pi RPC/PTY，长输入+工具sentinel fixture、流故障server。

**操作步骤：** 原任务先实际修改一次文件再收到限流；native retry成功对照与耗尽后外层恢复分别执行；canary成功后长请求继续失败；最终完整流成功才关闭incident，检查原session/continuation。

**最低变体：** agent_end后queued message/compact/retry；HTTP200后error/截断/超时；多轮限流；canary显式关闭/开启；无waiter；恢复后重复timer；超过packet边界的长Unicode输入。

**独立断言：** O1:原生成功时外层continue=0，已完成工具写入次数=1；canary请求无项目内容/工具且计费；O2:预算历史不清、只有真实完成关闭incident；O4:父模型与receipt保留恢复关系；O5:结束后timer/listener清理。

**负向对照：** 以canary200或agent_end当恢复完成、续跑重放原始任务，接收端与sentinel必须发现。

**实施依赖与边界：** Q1/S与Q2/A/E分别登记；P需要真实重启/共享进程观察；真实Qwen绑定由G32另验。

| 层级 | 待补义务 |
|---|---|
| S | REC-001:S, REC-015:S, REC-016:S |
| A | REC-007:A, REC-017:A, T18:A, T19:A, T22:A, T23:A, TK09:A |
| P | REC-015:P, REC-016:P, REC-017:P, REC-018:P |
| E | REC-007:E, REC-017:E, T18:E, T19:E, T22:E, T23:E, TK09:E |

## G18 工具命令共用状态与全部await撤权竞态

- 波次：B1；缺失层级义务：16。
- ID：CFG-001, CFG-012, CFG-013, REC-019, T35, T36, T37, T38。
- 参考：ADR003/005/010;S5。
- 夹具：真实RPC/PTY输入、TaskService、每个await测试barrier。

**操作步骤：** 工具创建job后用命令pause/resume/stop并从两个入口查询；在每个await的before-send窗口触发人工输入/取消或先完成await，按预定义两种顺序释放barrier；旧回调到达后观察外部动作。

**最低变体：** await集合见README的RACE表；真实按键vs终端协议回应/内部消息；reload/fork/switch/shutdown；重复resume；终态resume；notBefore/required失败/unknown writer仍在；取消后迟到额度成功。

**独立断言：** O1:撤权先于send零发送；send先发生只可保留事实不追加动作；O2:旧epoch失效、预算不清、终态不复活；O4:工具与命令同job状态；O5:旧timer/listener释放，用户按键未吞。

**负向对照：** 去掉任一个await后的epoch检查，仅该barrier反序用例必须失败。

**实施依赖与边界：** 13.5需登记真实可达await清单；不支持setModel/proxy路径只验证拒绝，不伪造为已支持竞态。

| 层级 | 待补义务 |
|---|---|
| U | CFG-001:U, T36:U |
| S | T36:S |
| A | CFG-012:A, CFG-013:A, REC-019:A, T35:A, T36:A, T37:A, T38:A |
| E | CFG-012:E, REC-019:E, T35:E, T36:E, T37:E, T38:E |

## G19 十会话共享许可与独立任务进展

- 波次：B1；缺失层级义务：14。
- ID：REC-013, REC-014, REC-022, SCH-013, T24, TK13。
- 参考：ADR003/008/009/011;S5/S9。
- 夹具：十个真实Pi父会话、共享SQLite、同池/异池loopback。

**操作步骤：** 十会话通过barrier同时到达冷却边界争同pool；对获许可者依次注入未发送退出/已终态/发送未知；用独立pool与workspace任务B验证其可完成；另测同父多job。

**最低变体：** 同state root共享 vs另root范围；等待执行已结束释放activity/repo slot；未知writer只保留相关写归属；全部waiter取消无探测；确认释放后竞争者继续。

**独立断言：** O1:同pool同时至多一个half-open真实请求，B实际有进展；O2:incident/预算/必要workspace保留，未知不靠lease释放；O5:持有者物理终态有证据。

**负向对照：** 对每session独立计许可或等待时占死所有host slot，分别使并发上限和B进展断言失败。

**实施依赖与边界：** 真实十会话成本用loopback；不能启动十个真实付费Qwen任务制造限流。

| 层级 | 待补义务 |
|---|---|
| S | SCH-013:S |
| A | REC-013:A, REC-014:A, REC-022:A, T24:A, TK13:A |
| P | REC-013:P, REC-014:P, REC-022:P, SCH-013:P |
| E | REC-013:E, REC-014:E, T24:E, TK13:E |

## G20 硬条件先过滤与thinking语义

- 波次：B3；缺失层级义务：8。
- ID：RTB-001, RTB-002, T27, T78。
- 参考：ADR002/013/016;S21/S22/S23。
- 夹具：policy/property表、实际profile preflight与生产route selector。

**操作步骤：** 用全合格两条路线建立确定性选择正例；让最低价候选每次只缺一种required能力；同名high但mapping/协议不同逐route核验；重排目录验证选择稳定。

**最低变体：** 授权、tools、context、thinking、transport、观察、风险各自单条件拒绝；无合法候选；unknown risk；同价tie-break；额外能力分数再高也不能抵消缺失。

**独立断言：** O1:拒绝路线零调用；O2:选择理由与被拒候选固定可重放；S层状态变化只影响合法候选；真实profile差异要求另有A证据。

**负向对照：** 用综合分数覆盖缺失hard constraint，单条件反例必须失败。

**实施依赖与边界：** 10.1完整认证待办；此批次S不等于所有provider thinking已认证。

| 层级 | 待补义务 |
|---|---|
| S | RTB-001:S, RTB-002:S, T27:S, T78:S |
| A | T27:A, T78:A |
| P | T27:P, T78:P |

## G21 恢复链阶段与事故备胎上限

- 波次：B3；缺失层级义务：16。
- ID：RTB-003, RTB-004, RTB-005, RTB-010, T28, T50。
- 参考：ADR003/009/010/016;S5/S9。
- 夹具：stage/recovery fixtures、真实Pi主备loopback、持久时钟。

**操作步骤：** 设阶段A有限等待→B备胎→A尾段，事故上限4；在B等待时让A成为候选；在B运行时让A可用；跨重启/暂停推进阶段直到4次备胎后请求第5次。

**最低变体：** 唯一stage ID；重复route首尾；未授权stage跳过；主备同pool/不同pool；主力notBefore较晚；备胎成功不关主力incident；active writer不因stage timeout被强杀；forever尾段仍有request deadline。

**独立断言：** O1:第5次备胎零发送且不双writer；O2:stageEnteredAt/deadline、incident及4次累计保留；O4:提前试探或等待理由；O5:活动writer未被阶段时限误杀。

**负向对照：** 备胎成功清incident或重启重置stage时间，守恒和发送上限断言必须失败。

**实施依赖与边界：** 10.5基础已实现；E需实际换路线边界证据，不支持主会话自动跨模型仍拒绝。

| 层级 | 待补义务 |
|---|---|
| S | RTB-003:S, RTB-004:S, RTB-005:S, RTB-010:S, T28:S, T50:S |
| A | RTB-003:A, RTB-004:A, RTB-005:A, RTB-010:A, T28:A, T50:A |
| P | RTB-010:P, T50:P |
| E | RTB-003:E, RTB-004:E |

## G22 账号遥测与网络路径失败

- 波次：B3；缺失层级义务：9。
- ID：RTB-006, T32, T34。
- 参考：ADR002/009/013;S6/S7/S8条件适用。
- 夹具：private telemetry file、不可用HTTP/SOCKS代理地址、独立direct接收端。

**操作步骤：** 配置明确network与account/bucket；分别提供新鲜匹配、过期、错账号/桶/来源遥测；网络绑定不可用时尝试protected dispatch，同时监视direct receiver。

**最低变体：** freshness边界−1/0/+1；remaining unknown/minReserve−1/恰好/+1；文件权限不安全/损坏；credential更换；SOCKS未支持显式拒绝；不能以其他pool的高余额准入。

**独立断言：** O1:网络失败不改直连、坏遥测protected零发送；O2:unknown不当剩余额度，transport失败不写quota incident；O4:doctor报告精确能力范围。

**负向对照：** proxy失败后fallback fetch direct或复用错账号缓存，独立receiver/账号断言必须失败。

**实施依赖与边界：** 当前仅direct执行受支持；SOCKS测试首先是拒绝验收，不能凭拒绝通过宣称已支持SOCKS。

| 层级 | 待补义务 |
|---|---|
| U | RTB-006:U, T34:U |
| S | RTB-006:S, T32:S, T34:S |
| A | T34:A |
| P | T32:P, T34:P |
| E | RTB-006:E |

## G23 每个真实请求的gate与累计预算

- 波次：B3；缺失层级义务：20。
- ID：RTB-007, RTB-008, RTB-009, RTB-011, RTB-012, RTB-013, T29, T30, T31, T33, T67。
- 参考：ADR003/009/010;S1/S5/S7条件适用。
- 夹具：HTTP gate/真实SDK retry、多个protected child、SQLite独立连接。

**操作步骤：** 设最后1许可，barrier同时触发多个真实请求；逐路径执行主生成/SDK retry/summary/compact/child/helper并在gate前拒绝；settle重复/乱序后换attempt/fork/scope别名；预算归零时跑可信纯CPU检查。

**最低变体：** N−1/N/N+1与0；incident/workScope分别耗尽；gate throw被catch后继续fetch；连接已发但ack未知；副调用计数；新session不清scope；本地check若发模型请求也须gate；无可靠gate禁严格自动备胎、独立P1仍可用。

**独立断言：** O1:独立receiver按requestAttempt精确计实际发送，被拒0次；O2:重复settle幂等、distinct retry独立累计、unknown不当0；CPU检查无模型许可仍实际完成。

**负向对照：** 明确构造吞gate异常继续send的坏adapter；接收端必须检出，不能以hook计数自证。

**实施依赖与边界：** 10.2/10.6真实调用路径清单待完整认证；T67仅通用summary预算部分，P4在线Advisor另延期。

| 层级 | 待补义务 |
|---|---|
| U | RTB-008:U, RTB-009:U, RTB-012:U, T29:U, T67:U |
| S | RTB-011:S, RTB-012:S, T29:S, T31:S |
| A | RTB-007:A, RTB-011:A, RTB-012:A, RTB-013:A, T30:A |
| P | RTB-007:P, RTB-012:P, T29:P, T33:P, T67:P |
| E | T31:E |

## G24 依赖图与模型不能刷新任务预算

- 波次：B2；缺失层级义务：8。
- ID：SCH-002, SCH-003, SCH-004, SCH-005, TK01, TK02。
- 参考：ADR005/009/015;S20。
- 夹具：生产Scheduler/TaskService、真实Pi工具入口、记录动作的checker。

**操作步骤：** 提交链/fan-out/join任务，分别让required前置失败、独立step成功、合法optional skip；通过kernel_task提交新scope/reset/循环/缺失引用；读取持久计划并等就绪动作。

**最低变体：** 空图/单节点；环/自引用/缺step；required exit0但无验收；optional失败有/无预设skip；重复上游成功事件；fork父scope映射；非法计划不能留下永久伪ready。

**独立断言：** O1:合法下游一次，失败下游零次，独立步骤确实执行；O2:原workScope预算继承、图拒绝原子；O4:具体依赖错误。

**负向对照：** 把进程exit当依赖pass或接受模型scope字段，必须失败。

**实施依赖与边界：** 固定workflow不能通过用户工具表达通用DAG时，E用测试harness经生产service提交并标范围，不给工具新增任意编排授权。

| 层级 | 待补义务 |
|---|---|
| P | TK01:P, TK02:P |
| E | SCH-002:E, SCH-003:E, SCH-004:E, SCH-005:E, TK01:E, TK02:E |

## G25 资源原子预留、写冻结与队列公平

- 波次：B2；缺失层级义务：27。
- ID：SCH-007, SCH-008, SCH-009, SCH-010, SCH-011, SCH-012, TK03, TK04, TK05, TK06, TK07, TK08。
- 参考：ADR008/011/018;S20。
- 夹具：多个真实parent、canonical临时仓库/软链接、SQLite barrier。

**操作步骤：** 两个进程按相反顺序申请同组资源；另测最后slot争抢、writer/verifier共享目录；释放获胜者后推进竞争者；固定有界任务流持续插入高优先级并观察旧ready任务aging。

**最低变体：** same/different root；alias/不存在路径最近实父目录/共享build目录；同job vs不同job；slot1/N；取消竞争者；未知终态不释放；aging seed与上限预先固定；真正verify持freeze时写请求。

**独立断言：** O1:整组最多一赢家，无部分claim死锁；O2:独立连接计数不负不超，释放后无泄漏；O3:验证快照期间零写入；O4:独立root不声称全宿主上限，选择原因可重放。

**负向对照：** 去原子事务、用字符串路径当identity、每次争抢重置ready age或让writer绕freeze，各对应反例必须失败。

**实施依赖与边界：** P必须OS进程barrier；不同root只证明保证范围，不声称其会相互排斥。

| 层级 | 待补义务 |
|---|---|
| U | TK06:U, TK07:U, TK08:U |
| S | SCH-008:S, TK06:S, TK07:S, TK08:S |
| P | SCH-007:P, SCH-008:P, SCH-009:P, SCH-010:P, SCH-011:P, SCH-012:P, TK03:P, TK04:P, TK06:P, TK08:P |
| E | SCH-009:E, SCH-010:E, SCH-011:E, SCH-012:E, TK03:E, TK04:E, TK05:E, TK06:E, TK07:E, TK08:E |

## G26 只读调查与持续工作区交付

- 波次：B2；缺失层级义务：10。
- ID：WFL-001, WFL-002, WFL-003, WFL-011, WFL-012, T43。
- 参考：ADR005/008/014;S19/S25。
- 夹具：真实Git脏树+未跟踪文件、0/1/2 reader、writer取消barrier。

**操作步骤：** 记录主树index/refs/dirty/untracked摘要；inspect尝试write/bash越权；fix工作区创建失败与正常创建分别执行；writer写一半后取消；最后独立验证成功任务输出候选补丁。

**最低变体：** reader0/1/2按已满足证据范围选择；只读缺能力；隔离失败/未知writer；嵌套cwd；外部symlink；staged+unstaged；首次成功与合法修复成功；取消保留部分文件。

**独立断言：** O3:主树/refs/远端不变、无隐式reset/clean/push，patch仅任务改变；O1:隔离失败零主树写；O2/O4:取消不是回滚/完成，成功receipt对应当前snapshot。

**负向对照：** worktree失败回退cwd或把取消显示已回滚，主树及receipt断言必须失败。

**实施依赖与边界：** 9.2 reader数量和scope规则按现有能力实现；不支持零reader验收时先补契约，不能空结果冒充调查。

| 层级 | 待补义务 |
|---|---|
| U | WFL-001:U, WFL-002:U, T43:U |
| P | WFL-003:P, WFL-011:P, WFL-012:P |
| E | WFL-001:E, WFL-003:E, WFL-011:E, T43:E |

## G27 真实测试计数与验收输入变更

- 波次：B2；缺失层级义务：6。
- ID：WFL-004, WFL-005, T44, T45, T46。
- 参考：ADR005/008/014/019;S15。
- 夹具：VerifyRunner真实node argv checker、绑定脚本/过滤器/环境。

**操作步骤：** 可信检查分别输出0 tests/all skip/unknown/实际pass/fail；验证后改源码或复用旧日志；改变check脚本/filter/阈值/env，尝试继续直到用户明确批准当前输入版本。

**最低变体：** JSON/TAP计数冲突；stderr错误；退出0但实际失败；argv含空格/$()/分号按字面传递；timeout/输出截断；验证中修改；审批前旧receipt失效/审批后版本递增不清预算；缺少inputs。

**独立断言：** O2:当前代码/政策/输入digest绑定，零测试与unknown不pass；O3:metachar无shell副作用，审批内容与实际执行一致；O5:真正checker退出事实。

**负向对照：** 只检查exitCode0或复用旧snapshot check结果，必须失败。

**实施依赖与边界：** 9.5基础已有；P层应从独立进程执行脚本并核对新连接回执，不能仅改字段。

| 层级 | 待补义务 |
|---|---|
| U | WFL-004:U |
| P | WFL-004:P, WFL-005:P |
| E | T44:E, T45:E, T46:E |

## G28 有界recipe、环境错误及required预留

- 波次：B3；缺失层级义务：26。
- ID：WFL-006, WFL-007, RTB-015, RTB-016, RTB-017, RTB-018, T72, T77, T79, T80, T82, T88。
- 参考：ADR005/009/015/016/017;S21/S22/S23/S24/S25。
- 夹具：真实fix workflow、implementation/environment分类checker、selector副作用陷阱。

**操作步骤：** direct保留required；环境基线失败不upgrade；有证据critic修订后尝试cascade并耗尽原step/semantic预算；将余额置于requiredReserve边界，观察可选critic跳过而required继续。

**最低变体：** maxSteps16/第17次；环境/unknown vs implementation；无发现/缺证据/有可处理发现；once critique/upgrade；策略切换计数继承；可选/required不足分开；selector调用spawn/write/setTimeout负向实现。

**独立断言：** O1:升级最多一次、无额外可选请求和nested loop；O2:共享原job/scope/计数，required不降级；O4:skip/park与理由显式；selector仅返回计划无副作用。

**负向对照：** 切recipe新建预算、direct删除reviewer或selector执行动作，真实动作日志和TaskSpec断言必须失败。

**实施依赖与边界：** 11.2/11.3已有基础；负向selector在隔离fixture中执行，不修改生产默认代码。

| 层级 | 待补义务 |
|---|---|
| U | WFL-006:U, WFL-007:U, T72:U, T77:U |
| S | RTB-015:S, RTB-016:S, RTB-017:S, RTB-018:S, WFL-006:S, WFL-007:S, T80:S, T82:S, T88:S |
| A | T82:A |
| P | T72:P, T77:P, T79:P, T82:P |
| E | RTB-017:E, RTB-018:E, WFL-007:E, T72:E, T77:E, T79:E, T80:E, T88:E |

## G29 独立审查、purpose与精确复用

- 波次：B2；缺失层级义务：11。
- ID：WFL-008, WFL-009, WFL-010, T81, T86。
- 参考：ADR005/014/017;S15/S25。
- 夹具：实际reviewer artifact读取日志、源snapshot、完整独立acceptance receipt。

**操作步骤：** 先获取同snapshot完整独立review；再次验收应精确复用且无新模型调用；每次只改变snapshot/policy/TaskSpec/purpose/risk/覆盖/独立性一项，再请求验收；记录实际读取的diff/check/failure范围。

**最低变体：** diagnostic critic不能自动作acceptance；只读部分diff；引用不存在/跨job；风险unknown/降级；writer自评；已知failure无resolution；完整匹配正例必须可复用并保留source receipt。

**独立断言：** O1:合格复用零重复收费，不合格不得直接完成；O2:新receipt绑定同source/snapshot/purpose并保留出处；O4:未覆盖范围披露，required reviewer仍必需。

**负向对照：** 只按snapshot复用而忽略purpose/独立性，或一律不复用，分别使反例和零重复收费正例失败。

**实施依赖与边界：** 9.6完整审查复用未完成，必须实现规则后才可执行E；不能降低复用条件求通过。

| 层级 | 待补义务 |
|---|---|
| U | WFL-008:U, WFL-009:U, WFL-010:U, T81:U, T86:U |
| S | T81:S, T86:S |
| E | WFL-008:E, WFL-010:E, T81:E, T86:E |

## G30 证据登记、来源漂移与诚实发布报告

- 波次：B0；缺失层级义务：10。
- ID：VAL-001, VAL-002, VAL-004, VAL-006, VAL-008, VAL-012, VAL-013, VAL-018, VAL-019。
- 参考：ADR004/012/019;S10/S15/S16/S17。
- 夹具：plan/report命令的隔离fixture副本、v6校验摘要、合成结果记录。

**操作步骤：** 准备完整合法小型计划和实际执行记录作为正例；逐项改Scenario WHEN/THEN、重复ID、test发现数、层级、断言、lock、binding、skip/失败/重跑；运行真实报告生成入口读取JSON/CSV/退出码。

**最低变体：** 多ID仅一个断言；全assertions总数不能代表每ID；零发现exit0；静态通过无执行；旧lock/缺工件；passed后failed或先failed后passed；缺Qwen绑定；只正常smoke无恢复；P1合格P3缺gate；完整P4延期清单；来源ADR变更缺测试依据。

**独立断言：** V:报告不将planned/skipped/stale/缺绑定记passed，精确缺口集与失败历史保留；原v6哈希不变；不能以单个测试标题挂多个ID提升覆盖；positive fixture可达到其声明范围ready但不冒充真实产品已ready。

**负向对照：** 伪造多ID共享无关断言或删除missing层级；独立预期表必须发现报告误认证。

**实施依赖与边界：** 13.1的逐义务断言与发现双向校验尚不完整；设计登记不进入runtime evidenceRecords。

| 层级 | 待补义务 |
|---|---|
| U | VAL-008:U |
| V | VAL-001:V, VAL-002:V, VAL-004:V, VAL-006:V, VAL-008:V, VAL-012:V, VAL-013:V, VAL-018:V, VAL-019:V |

## G31 验证器自身的负向控制与可重放序列

- 波次：B0；缺失层级义务：8。
- ID：VAL-014, VAL-016, VAL-017。
- 参考：ADR010/012;S9/S15/S16。
- 夹具：坏adapter、存活descendant、seed/barrier日志、决策真值表。

**操作步骤：** 让fake报告cancelled/预算合法而真实receiver收到超额或descendant继续写；对各决策仅改变一个准入条件；预设seed运行事件序列，并将捕获失败轨迹交给全新进程重放。

**最低变体：** 种子17/41/101/2026每个150步；组合条件全部坏不能替代单项反例；缺epoch/notBefore/required/request dedup/writer证明的隔离负向实现；删除seed或barrier记录必须使验证不合格。

**独立断言：** O1/O5:独立外部违规必须使测试失败；V:记录case/seed/切点/事件顺序/最小失败序列；S:良好实现满足守恒与合法进展；P:新进程重放同故障结论。

**负向对照：** 运行已知坏fixture并期待测试工具非零退出；坏fixture被报绿即验证器失败。

**实施依赖与边界：** 预设seed不能无限重跑到绿；测试故意的失败在子运行中记录为expected-negative，不覆盖产品实际failed记录。

| 层级 | 待补义务 |
|---|---|
| U | VAL-016:U |
| S | VAL-016:S |
| P | VAL-014:P, VAL-016:P, VAL-017:P |
| E | VAL-014:E |
| V | VAL-016:V, VAL-017:V |

## G32 Qwen Q3实际绑定、受控恢复与失败报告

- 波次：B4；缺失层级义务：8。
- ID：VAL-005, VAL-007。
- 参考：ADR002/004/010/012;S5/S6/S9。
- 夹具：显式验收profile、用户提供model/account/network引用、合成长任务。

**操作步骤：** 先校验实际绑定及有限request ceiling；一次正常可用性检查；在显式测试transport注入一次429后交还真实Qwen服务完成原任务；另用可控坏profile令该绑定失败，分别保存真实service-origin与injected事实并生成报告。

**最低变体：** 长输入先工具修改再限流；同session/continuation；正常smoke无故障；错误binding或不可恢复失败；注入不支持则仅可用性结果；Q3失败不能由其他模型或Q2通过覆盖。

**独立断言：** O1:每次真实/合成请求分来源计数且不超上限；O2:原scope/历史保持；O3:合成项目副作用一次；O4:版本/配置摘要、等待、完整终态、receipt及模型身份来源；O5:停止后不续发；V:无绑定pending、失败failed、仅正常成功不认证恢复。

**负向对照：** 把injected当service-origin、无故障smoke当恢复证据或错误绑定结果替换成loopback，报告必须拒绝。

**实施依赖与边界：** L需用户明确provider/model与总请求上限，未提供则planned-needs-live-binding；A/E可先用loopback设计行为但不能获取L信用。不得制造真实配额耗尽。

| 层级 | 待补义务 |
|---|---|
| A | VAL-005:A, VAL-007:A |
| E | VAL-005:E, VAL-007:E |
| L | VAL-005:L, VAL-007:L |
| V | VAL-005:V, VAL-007:V |

## G33 P4在线Advisor延期义务的未来设计

- 波次：P4；缺失层级义务：6。
- ID：T66, T68, T69。
- 参考：ADR006/009/012/016;S10/S11/S13/S15。
- 夹具：未来Advisor adapter与固定规则dispatcher；当前仅设计契约。

**操作步骤：** 未来启用经批准的Advisor测试profile后：含SDK retry的两次尝试耗尽；shadow产生合法建议；Advisor故障但规则下一步合法，分别观测模型请求、决策选择与回退。

**最低变体：** T66:格式错/网络重试也计入两次，不递归管理者；T68:建议可行仍零生产选择变化；T69:错误保留并实际执行合法规则动作，不伪造建议成功；V保留对应全调用证据。

**独立断言：** U:手写状态与有限动作契约；V:两次上限、shadow无执行效应、回退来源三项分别核验；当前off拒绝不是这三条在线行为的通过证据。

**负向对照：** 隐藏第三次格式修复请求、shadow改生产选择、错误被标成功，未来验证必须失败。

**实施依赖与边界：** P4未实现且本次不扩scope；保留全部6个缺失层级，deferred-P4仅是计划依赖状态，不代表passed。

| 层级 | 待补义务 |
|---|---|
| U | T66:U, T68:U, T69:U |
| V | T66:V, T68:V, T69:V |

