# 完整测试 case 设计（v2）

本文件与 CSV 由 `build-design.py` 从手工审阅的领域配方、层级规则和组合矩阵生成。生成登记不生成运行证据。

覆盖全部 713 项义务：707 项 P0–P3、6 项 P4 延期；其中当前 P0–P3 缺口 618 项、新暴露缺口 220 项。

逐义务的原 WHEN/THEN、source digest、case ID、文件/名称、断言、步骤与必测变体均在 [coverage-cases.csv](coverage-cases.csv)。只看当前缺口用 [current-gap-cases.csv](current-gap-cases.csv)，只看新增 220 项用 [newly-uncredited-cases.csv](newly-uncredited-cases.csv)。

适用规则：原场景主断言必须单独成立；同一批次的检查不能自动给其他场景计分。正例、负向对照与本层级适用的全部变体均需执行。共享组合矩阵按稳定 ID 展开，不使用 pairwise 省略高风险交叉。原规范要求的成功行为若缺实现，保持待办，不能用拒绝测试代替。

## 分层执行与边界

### U — 单元契约与规则

1. 把该case原触发和批次检查转换为固定输入对象；expected由原规范和本设计常量给出，不调用被测代码生成。
2. 直接调用targets中的生产纯规则/契约函数，逐一改变一个字段或条件；状态输入只测一条边的决定。
3. 逐条比较返回值/错误码/动作描述及输入未被改写；生产没有可单测规则接口时记实现依赖，不在fixture复制一份逻辑。

**独立观测：** 独立手写真值表、输入前后快照和断言调用记录；动作描述仅证明规则输出，不证明真实HTTP或进程终止。

**不能替代：** 不得把fake fetch、构造receipt、模拟process.kill当A/P/E结果；U不承担真实OS崩溃。

**时限：** 每个基本case 5s；不得真实等待quota时间。

### S — 可重放状态与事件顺序

1. 从明确的初始scope/incident/job/intent快照开始；用固定wall/monotonic clock、jitter及seed。
2. 经生产controller/service的状态入口逐一投递本case事件；await用barrier安排两个顺序，记录每个边界而非随机sleep。
3. 每步核对状态、预算守恒和允许动作，与独立转移表比较；合法解除阻塞后必须有进展。真实发出与进程事实留给A/P/E。

**独立观测：** 手写状态转移表＋事件/动作轨迹；依赖可替身，但替身不能为自己的预期结果背书。

**不能替代：** Promise并发不是OS竞争；fake cancel成功不证明writer停止。

**时限：** 每个有界序列15s；seed17/41/101/2026各150步，失败保留最小重放序列。

### A — 真实Pi/adapter协议边界

1. 启动隔离Pi及锁定adapter，用独立loopback接收器记录原始请求/响应/事件，receiver不导入产品调度决策。
2. 经实际adapter调用或Pi RPC/PTY触发原case；在SDK重试/序列化/取消边界注入指定响应或barrier。
3. 比较receiver、原生事件和生效模型/profile事实；每次只改变一个准入条件，并运行全合法正例。

**独立观测：** 独立HTTP接收日志或原生IPC/工具物理效果observer＋实际adapter输出；对不发网络的路径明确记录其动作观察方式。

**不能替代：** 不能只调用reducer或mock SDK取得A信用；本地服务不是远端Qwen认证。

**时限：** 每基本case30s，复杂原生子任务最多90s；watchdog只判挂死，不安排竞态。

### P — SQLite与真实OS进程

1. supervisor创建私有state/workspace，启动独立controller或worker；用IPC确认实际切点和进程启动身份。
2. 按本case注入竞争、kill、重启、文件故障或真实verifier活动；只操作本次创建的进程和文件。
3. 在新进程/新SQLite连接读取事实，与receiver/文件副作用及进程存活独立对照；保持unknown直至可证明结算。

**独立观测：** 独立SQLite连接＋receiver/现场字节＋supervisor的PID namespace/start ticks/进程组记录；取消ack不是终止oracle。

**不能替代：** 同进程多个Promise不计跨进程；不得填满真实磁盘或按宽泛进程名清理。

**时限：** 每基本case30s；适用descendant退出测试最多90s且supervisor负责回收。

### E — 真实用户或模型入口到最终事实

1. 建立隔离Pi、合成项目、用户配置、可信检查和独立接收器；记录auth/策略/主树/DB基线摘要。
2. 通过真实/orch、/throttle命令或实际模型kernel_task入口触发本case；生命周期用宿主真实事件；等待明确终态/阻塞，不直接调用私有service方法代替入口。
3. 逐一对照raw事件→新连接账本→TaskReceipt→父模型下一实际输入→PTY/无UI；另核对真实副作用与主树。确实未产生某层时记录原因，要求该层的case不能记通过。

**独立观测：** 用户入口记录＋独立receiver/sentinel＋新连接账本＋回执＋实际父请求与展示捕获；包含断言的observer与产品投影分离。

**不能替代：** 内部测试harness仅可算相应S/A/P；缺产品入口先补实现，不能给E降级。

**时限：** 每基本case90s；长组合拆成独立case，假时钟只控制测试绑定。

### L — 实际Qwen绑定的有限验收

1. 要求用户指定provider/model或验收配置、凭证引用、network/profile及总请求上限；缺任何必需项保持needs-live-binding。
2. 在隔离合成项目和显式验收transport上执行固定长任务；标记一次注入429后交还真实Qwen，禁止密集调用制造真实额度耗尽。
3. 独立记录每次真实与注入请求、原session/continuation、已完成工具副作用、完整服务终态和回执；正常smoke与恢复认证分别判定。

**独立观测：** 具有来源标记的真实服务响应/实际请求账单观察＋合成项目副作用＋版本与模型身份来源；配置model不是实际权重证明。

**不能替代：** fake credentials/loopback/其他模型不可取得L信用；仅正常成功不算恢复；失败不自动换模型重跑覆盖。

**时限：** 有限deadline和requestTimeout由显式验收profile固定，必须在执行前记录；本轮不运行L。

### V — 报告/评测/证据验证器

1. 准备明确的小型计划、实际发现记录或固定评测样本和独立预期报告；产品整套报告只作为待验证输入。
2. 运行真实报告/校验入口；一次只删除或污染一个ID、层级、断言、来源、lock、变体或工件，对照合法输入。
3. 比较JSON/CSV/退出码、分母、unknown、延期与失败历史；负向子运行必须被拒绝，不能把合成报告ready当产品ready。

**独立观测：** 独立固定算术/集合与预期报告＋真实命令退出码和输出；不使用被测coverage函数生成expected。

**不能替代：** 文档存在/静态检查通过不证明产品故障覆盖；不把未执行shadow或过滤infra后的成绩当收益。

**时限：** 每基本case15s；所有坏输入在内存或隔离副本，不污染正式结果。

## 高风险组合的完整展开

### await-orders — 66 个组合

批次：G18；层级：S, A, E。每个实际可达边界展开全部指定事件和两个顺序。接口未支持时记录拒绝范围；若原规范要求该成功路径，则保持实现/认证待办，不以拒绝替代成功。

| 组合 ID | 输入／切点 | 预期 |
|---|---|---|
| R01.input.revoke-first | auth refresh barrier；input；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R01.input.await-first | auth refresh barrier；input；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R01.stop.revoke-first | auth refresh barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R01.stop.await-first | auth refresh barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R01.binding-change.revoke-first | auth refresh barrier；binding-change；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R01.binding-change.await-first | auth refresh barrier；binding-change；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.input.revoke-first | telemetry barrier；input；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.input.await-first | telemetry barrier；input；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.stop.revoke-first | telemetry barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.stop.await-first | telemetry barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.account-change.revoke-first | telemetry barrier；account-change；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.account-change.await-first | telemetry barrier；account-change；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.bucket-change.revoke-first | telemetry barrier；bucket-change；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R02.bucket-change.await-first | telemetry barrier；bucket-change；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.input.revoke-first | canary barrier；input；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.input.await-first | canary barrier；input；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.pause.revoke-first | canary barrier；pause；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.pause.await-first | canary barrier；pause；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.stop.revoke-first | canary barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.stop.await-first | canary barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.shutdown.revoke-first | canary barrier；shutdown；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R03.shutdown.await-first | canary barrier；shutdown；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R04.input.revoke-first | setModel barrier；input；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R04.input.await-first | setModel barrier；input；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R04.stop.revoke-first | setModel barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R04.stop.await-first | setModel barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R04.config-change.revoke-first | setModel barrier；config-change；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R04.config-change.await-first | setModel barrier；config-change；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R05.input.revoke-first | resource/request permit barrier；input；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R05.input.await-first | resource/request permit barrier；input；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R05.stop.revoke-first | resource/request permit barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R05.stop.await-first | resource/request permit barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R05.ownerEpoch-change.revoke-first | resource/request permit barrier；ownerEpoch-change；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R05.ownerEpoch-change.await-first | resource/request permit barrier；ownerEpoch-change；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R06.stop.revoke-first | native accepted/start ack barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R06.stop.await-first | native accepted/start ack barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R06.reload.revoke-first | native accepted/start ack barrier；reload；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R06.reload.await-first | native accepted/start ack barrier；reload；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R06.owner-loss.revoke-first | native accepted/start ack barrier；owner-loss；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R06.owner-loss.await-first | native accepted/start ack barrier；owner-loss；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.input.revoke-first | continuation ack barrier；input；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.input.await-first | continuation ack barrier；input；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.stop.revoke-first | continuation ack barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.stop.await-first | continuation ack barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.fork.revoke-first | continuation ack barrier；fork；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.fork.await-first | continuation ack barrier；fork；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.switch.revoke-first | continuation ack barrier；switch；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R07.switch.await-first | continuation ack barrier；switch；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R08.input.revoke-first | compact/retry/follow-up settled barrier；input；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R08.input.await-first | compact/retry/follow-up settled barrier；input；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R08.stop.revoke-first | compact/retry/follow-up settled barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R08.stop.await-first | compact/retry/follow-up settled barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R08.switch.revoke-first | compact/retry/follow-up settled barrier；switch；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R08.switch.await-first | compact/retry/follow-up settled barrier；switch；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R09.pause.revoke-first | workspace snapshot barrier；pause；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R09.pause.await-first | workspace snapshot barrier；pause；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R09.stop.revoke-first | workspace snapshot barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R09.stop.await-first | workspace snapshot barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R09.dispose.revoke-first | workspace snapshot barrier；dispose；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R09.dispose.await-first | workspace snapshot barrier；dispose；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R10.stop.revoke-first | verifier/reviewer completion barrier；stop；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R10.stop.await-first | verifier/reviewer completion barrier；stop；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R10.source-change.revoke-first | verifier/reviewer completion barrier；source-change；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R10.source-change.await-first | verifier/reviewer completion barrier；source-change；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R10.acceptance-change.revoke-first | verifier/reviewer completion barrier；acceptance-change；revoke-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |
| R10.acceptance-change.await-first | verifier/reviewer completion barrier；acceptance-change；await-first | 撤权先到：若尚未实际调用则零发送/零新增写入；await先完成：仅真实发送先于撤权的既有动作可保留，不允许迟到回调追加。unknown占用保留；记录send与revoke独立时间序列。 |

### crash-cuts — 18 个组合

批次：G12；层级：S, A, P, E。18个基本轨迹；S只模拟事件决定，A/P/E必须实际生产调用与独立receiver/verifier副作用。不是把store-worker的18次fake调用记为adapter全覆盖。

| 组合 ID | 输入／切点 | 预期 |
|---|---|---|
| start.C0 | start在C0生产边界触发中断 | 外部动作0；未提交intent/reservation不得发送。 |
| start.C1 | start在C1生产边界触发中断 | 仅明确未发送才可释放或合法重试；发送状态不明则unknown。 |
| start.C2 | start在C2生产边界触发中断 | 接收端已生效，无ack；对账同动作身份，不得重复调用。 |
| start.C3 | start在C3生产边界触发中断 | ack已到未持久；补记录，不重复外部动作。 |
| start.C4 | start在C4生产边界触发中断 | 物理终态已确认未结算；补结算且预算只记一次。 |
| start.C5 | start在C5生产边界触发中断 | 结算已提交未通知；只补通知，不重执行或重复计费。 |
| continue.C0 | continue在C0生产边界触发中断 | 外部动作0；未提交intent/reservation不得发送。 |
| continue.C1 | continue在C1生产边界触发中断 | 仅明确未发送才可释放或合法重试；发送状态不明则unknown。 |
| continue.C2 | continue在C2生产边界触发中断 | 接收端已生效，无ack；对账同动作身份，不得重复调用。 |
| continue.C3 | continue在C3生产边界触发中断 | ack已到未持久；补记录，不重复外部动作。 |
| continue.C4 | continue在C4生产边界触发中断 | 物理终态已确认未结算；补结算且预算只记一次。 |
| continue.C5 | continue在C5生产边界触发中断 | 结算已提交未通知；只补通知，不重执行或重复计费。 |
| verify.C0 | verify在C0生产边界触发中断 | 外部动作0；未提交intent/reservation不得发送。 |
| verify.C1 | verify在C1生产边界触发中断 | 仅明确未发送才可释放或合法重试；发送状态不明则unknown。 |
| verify.C2 | verify在C2生产边界触发中断 | 接收端已生效，无ack；对账同动作身份，不得重复调用。 |
| verify.C3 | verify在C3生产边界触发中断 | ack已到未持久；补记录，不重复外部动作。 |
| verify.C4 | verify在C4生产边界触发中断 | 物理终态已确认未结算；补结算且预算只记一次。 |
| verify.C5 | verify在C5生产边界触发中断 | 结算已提交未通知；只补通知，不重执行或重复计费。 |

### request-paths — 42 个组合

批次：G23；层级：S, A, P。42个路径/窗口组合。不存在预算可控接口的parent helper只能拒绝：allowed行的预期是该路径明确不支持且零请求，同时独立普通用户请求的正例仍需成功。其他未实现的规范成功路径保持待办，不能一律拒绝来取得严格自动兜底认证。

| 组合 ID | 输入／切点 | 预期 |
|---|---|---|
| primary.allowed | 支持路径=primary；切点=allowed | 准入/许可/身份全合法，一次合法请求对应一个requestAttempt。 |
| primary.denied | 支持路径=primary；切点=denied | 预算或requiredReserve不足，接收端零请求。 |
| primary.cancel-before-gate | 支持路径=primary；切点=cancel-before-gate | 取消发生在门控前，零发送。 |
| primary.cancel-after-reserve | 支持路径=primary；切点=cancel-after-reserve | 取消在预留后实际调用前，重查拒绝且仅确证未发送才释放。 |
| primary.cancel-after-recheck | 支持路径=primary；切点=cancel-after-recheck | 凭证/遥测/最终准入await返回后、fetch调用前取消，仍不得发送。 |
| primary.cancel-after-receiver | 支持路径=primary；切点=cancel-after-receiver | 接收端已收到后取消，保留已发送事实，终态未知仍预留；迟到完成不追加请求。 |
| native-retry.allowed | 支持路径=native-retry；切点=allowed | 准入/许可/身份全合法，一次合法请求对应一个requestAttempt。 |
| native-retry.denied | 支持路径=native-retry；切点=denied | 预算或requiredReserve不足，接收端零请求。 |
| native-retry.cancel-before-gate | 支持路径=native-retry；切点=cancel-before-gate | 取消发生在门控前，零发送。 |
| native-retry.cancel-after-reserve | 支持路径=native-retry；切点=cancel-after-reserve | 取消在预留后实际调用前，重查拒绝且仅确证未发送才释放。 |
| native-retry.cancel-after-recheck | 支持路径=native-retry；切点=cancel-after-recheck | 凭证/遥测/最终准入await返回后、fetch调用前取消，仍不得发送。 |
| native-retry.cancel-after-receiver | 支持路径=native-retry；切点=cancel-after-receiver | 接收端已收到后取消，保留已发送事实，终态未知仍预留；迟到完成不追加请求。 |
| summary.allowed | 支持路径=summary；切点=allowed | 准入/许可/身份全合法，一次合法请求对应一个requestAttempt。 |
| summary.denied | 支持路径=summary；切点=denied | 预算或requiredReserve不足，接收端零请求。 |
| summary.cancel-before-gate | 支持路径=summary；切点=cancel-before-gate | 取消发生在门控前，零发送。 |
| summary.cancel-after-reserve | 支持路径=summary；切点=cancel-after-reserve | 取消在预留后实际调用前，重查拒绝且仅确证未发送才释放。 |
| summary.cancel-after-recheck | 支持路径=summary；切点=cancel-after-recheck | 凭证/遥测/最终准入await返回后、fetch调用前取消，仍不得发送。 |
| summary.cancel-after-receiver | 支持路径=summary；切点=cancel-after-receiver | 接收端已收到后取消，保留已发送事实，终态未知仍预留；迟到完成不追加请求。 |
| compaction.allowed | 支持路径=compaction；切点=allowed | 准入/许可/身份全合法，一次合法请求对应一个requestAttempt。 |
| compaction.denied | 支持路径=compaction；切点=denied | 预算或requiredReserve不足，接收端零请求。 |
| compaction.cancel-before-gate | 支持路径=compaction；切点=cancel-before-gate | 取消发生在门控前，零发送。 |
| compaction.cancel-after-reserve | 支持路径=compaction；切点=cancel-after-reserve | 取消在预留后实际调用前，重查拒绝且仅确证未发送才释放。 |
| compaction.cancel-after-recheck | 支持路径=compaction；切点=cancel-after-recheck | 凭证/遥测/最终准入await返回后、fetch调用前取消，仍不得发送。 |
| compaction.cancel-after-receiver | 支持路径=compaction；切点=cancel-after-receiver | 接收端已收到后取消，保留已发送事实，终态未知仍预留；迟到完成不追加请求。 |
| child.allowed | 支持路径=child；切点=allowed | 准入/许可/身份全合法，一次合法请求对应一个requestAttempt。 |
| child.denied | 支持路径=child；切点=denied | 预算或requiredReserve不足，接收端零请求。 |
| child.cancel-before-gate | 支持路径=child；切点=cancel-before-gate | 取消发生在门控前，零发送。 |
| child.cancel-after-reserve | 支持路径=child；切点=cancel-after-reserve | 取消在预留后实际调用前，重查拒绝且仅确证未发送才释放。 |
| child.cancel-after-recheck | 支持路径=child；切点=cancel-after-recheck | 凭证/遥测/最终准入await返回后、fetch调用前取消，仍不得发送。 |
| child.cancel-after-receiver | 支持路径=child；切点=cancel-after-receiver | 接收端已收到后取消，保留已发送事实，终态未知仍预留；迟到完成不追加请求。 |
| parent-helper.allowed | 支持路径=parent-helper；切点=allowed | 准入/许可/身份全合法，一次合法请求对应一个requestAttempt。 |
| parent-helper.denied | 支持路径=parent-helper；切点=denied | 预算或requiredReserve不足，接收端零请求。 |
| parent-helper.cancel-before-gate | 支持路径=parent-helper；切点=cancel-before-gate | 取消发生在门控前，零发送。 |
| parent-helper.cancel-after-reserve | 支持路径=parent-helper；切点=cancel-after-reserve | 取消在预留后实际调用前，重查拒绝且仅确证未发送才释放。 |
| parent-helper.cancel-after-recheck | 支持路径=parent-helper；切点=cancel-after-recheck | 凭证/遥测/最终准入await返回后、fetch调用前取消，仍不得发送。 |
| parent-helper.cancel-after-receiver | 支持路径=parent-helper；切点=cancel-after-receiver | 接收端已收到后取消，保留已发送事实，终态未知仍预留；迟到完成不追加请求。 |
| canary.allowed | 支持路径=canary；切点=allowed | 准入/许可/身份全合法，一次合法请求对应一个requestAttempt。 |
| canary.denied | 支持路径=canary；切点=denied | 预算或requiredReserve不足，接收端零请求。 |
| canary.cancel-before-gate | 支持路径=canary；切点=cancel-before-gate | 取消发生在门控前，零发送。 |
| canary.cancel-after-reserve | 支持路径=canary；切点=cancel-after-reserve | 取消在预留后实际调用前，重查拒绝且仅确证未发送才释放。 |
| canary.cancel-after-recheck | 支持路径=canary；切点=cancel-after-recheck | 凭证/遥测/最终准入await返回后、fetch调用前取消，仍不得发送。 |
| canary.cancel-after-receiver | 支持路径=canary；切点=cancel-after-receiver | 接收端已收到后取消，保留已发送事实，终态未知仍预留；迟到完成不追加请求。 |

### stream-terminals — 4 个组合

批次：G17, G23；层级：S, A, P, E。完整成功正例与三类失败分别执行，HTTP状态不能替代SDK流终态。

| 组合 ID | 输入／切点 | 预期 |
|---|---|---|
| complete | HTTP200，流终态=complete | 完整真实终态后才能确认恢复；一个attempt正确结算。 |
| error | HTTP200，流终态=error | HTTP200但流内error，恢复失败且原错误传播。 |
| truncated | HTTP200，流终态=truncated | 缺完整终态，不标恢复；按真实已发状态保留/结算。 |
| timeout | HTTP200，流终态=timeout | 有限requestTimeout生效，先终止对账，unknown不立即重发。 |

### lifecycle-preservation — 12 个组合

批次：G01, G11, G13；层级：P, E。12个基本组合；升级和回退受已有维护协议约束，不把取消当现场回滚。

| 组合 ID | 输入／切点 | 预期 |
|---|---|---|
| upgrade.not-sent | upgrade时intent为not-sent，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| upgrade.terminal-confirmed | upgrade时intent为terminal-confirmed，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| upgrade.unknown | upgrade时intent为unknown，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| disable.not-sent | disable时intent为not-sent，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| disable.terminal-confirmed | disable时intent为terminal-confirmed，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| disable.unknown | disable时intent为unknown，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| restart.not-sent | restart时intent为not-sent，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| restart.terminal-confirmed | restart时intent为terminal-confirmed，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| restart.unknown | restart时intent为unknown，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| rollback.not-sent | rollback时intent为not-sent，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| rollback.terminal-confirmed | rollback时intent为terminal-confirmed，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |
| rollback.unknown | rollback时intent为unknown，同时保留workspace及累计预算 | 新连接核对所有业务主键/used/reserved/claims/工作区引用；仅确证未发送/终止才相应释放；unknown保持。回退只限同次维护备份，不能覆盖新增事实。 |

## 领域测试配方

### G01 — 包加载、初始化及配置隔离

义务数：3；当前 P0–P3 缺口：2。

**ID：** CFG-003, CFG-011

**参考：** ADR001/013/019;S5

**生产接口检查位置：** `src/config.ts`; `index.ts`

**夹具：** 现有 config/workflows fixture；新增隔离 launcher 与假同步目标

**领域步骤（按上面的层级规则执行）：** 在独立 HOME/PI_CODING_AGENT_DIR 内放置策略、auth、SQLite intent/unknown 哨兵；加载 disabled 包并执行 doctor/init；仅对临时 Pi 根执行两次包同步；新连接读回原等待任务。

**成功对照：** 空的私有可写Pi根，初始化一次后同配置同步两次；文件安全建立、包identity唯一且再次操作幂等。

**负向对照：** 在隔离副本中将路径 resolver 指向假受保护 home；launcher 在导入任何插件之前拒绝。不得以真实 Claude 文件作负向控制。

**实现依赖：** bwrap 隔离入口已实现；仍需真实临时 Pi 根同步与字节/权限对照。禁止真实 AISync/PiGenerate 或跨工具同步。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G01.disabled | enabled=false；放置 auth、策略、intent、unknown 和预算哨兵 | HTTP=0，业务摘要及用户文件字节/权限不变 |
| G01.initialization | init 路径依次不存在、已存在、不可写 | 只在不存在且可写时建立默认禁用文件；其余不覆盖 |
| G01.synchronize | 对同一临时 Pi 根连续同步两次 | 包 identity 仅一份；auth/策略/runtime DB 保留；第二次幂等 |
| G01.escape | 将测试目标设为隔离根外绝对路径或经 symlink 逃逸 | 隔离边界拒绝写入，受保护临时哨兵不变 |

**精确义务索引：** CFG-003:U, CFG-003:A, CFG-011:E

### G02 — 项目限制代数与禁止扩权

义务数：19；当前 P0–P3 缺口：18。

**ID：** CFG-004, CFG-005, CFG-006, CFG-008, CFG-009, T87, VAL-003

**参考：** ADR005/006/013/019;S5

**生产接口检查位置：** `src/config.ts`

**夹具：** 现有 config/properties；新增 project-policy E fixture

**领域步骤（按上面的层级规则执行）：** 建立用户预算12、required reviewer及可信 check；逐个写项目 override，reload 后提交同一合法任务；比较有效配置、拒绝原因和外部请求。

**成功对照：** 用户预算12，项目收紧6且保留required reviewer、只引用已有可信check；有效预算6、required保留且允许合法动作。

**负向对照：** 临时移除一个合并限制，单条件扩权测试必须失败。

**实现依赖：** 现有逻辑可扩测；项目新可执行命令必须继续被拒绝。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G02.budget | 用户上限12，项目依次给24、12、1、0 | 结果不超过12；0禁止新对应请求；既有 used/reserved 不清零 |
| G02.required | 删除 required reviewer；另引用已绑定的额外 check | reviewer 保持 required；可信新增约束可加入 |
| G02.authority | 项目增加 check argv、account、network、ignoreRequiredChecks 或 cancelMayResume | 未知/扩权字段拒绝且不产生执行 |
| G02.algebra | 重复收紧；允许集分别空、缺失、null | 幂等且不扩权；空集禁止；缺失继承；非法 null 拒绝 |
| G02.numbers | 输入负数、小数、NaN、Infinity、比例上限前/等于/后 | 非法值拒绝；合法边界按字段契约保留；JSON 不可表示值与对象入口分别测 |

**精确义务索引：** CFG-004:U, CFG-004:S, CFG-004:E, CFG-005:U, CFG-005:S, CFG-005:E, CFG-006:U, CFG-006:S, CFG-006:E, CFG-008:U, CFG-008:S, CFG-008:E, CFG-009:U, CFG-009:E, VAL-003:U, VAL-003:V, T87:U, T87:S, T87:E

### G03 — Qwen 多服务绑定与分类可替换

义务数：8；当前 P0–P3 缺口：2。

**ID：** CFG-002, REC-002, TK10

**参考：** ADR002/004/010;S5/S6/S9

**生产接口检查位置：** `src/reliability/classifier.ts`; `src/adapters/http-transport.ts`

**夹具：** 两份配置化服务响应 fixture；实际 Pi loopback transport

**领域步骤（按上面的层级规则执行）：** 对同一长任务使用服务A/B的不同 provider/model/baseURL/classifier 配置；A返回429结构化错误，B返回各自 usage/window 结构；经同一恢复入口继续；交换模型显示名称复跑。

**成功对照：** 服务A/B各自有匹配规则和来源；同任务均经临时失败后完整成功，交换显示名不影响分类。

**负向对照：** 交换模型名称后行为随名称而变，或将resource_pressure误写monthly_exhausted，必须失败。

**实现依赖：** 6.1仍缺有来源的Qwen多服务脱敏样本；合成fixture不能冒充真实来源。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G03.service-binding | 同一任务交换服务A/B配置及模型显示名称 | 仅绑定的分类规则决定结果，不按名字分支 |
| G03.provenance | 分别输入 synthetic、document-derived、service-origin 样本 | 来源与采样/文档摘要保留；前两类不获得真实服务信用 |
| G03.envelope | 相同临时错误分别嵌套 error 和顶层数字 code | 归一化保留原 code、message、HTTP；SDK 丢字段时仅采用有界已完成前缀 |
| G03.unknown | 未知 code、缺 classifier、HTTP429 与 auth body 冲突 | 未知不当无限配额重试；缺绑定拒绝；按显式优先级保留永久拒绝 |

**精确义务索引：** CFG-002:U, CFG-002:A, REC-002:S, REC-002:A, REC-002:E, TK10:S, TK10:A, TK10:E

### G04 — 能力证书、真实生效配置与启动屏障

义务数：39；当前 P0–P3 缺口：33。

**ID：** EXE-001, EXE-002, EXE-003, EXE-004, EXE-007, EXE-012, T04, T06, T07, T08, T17, T48, T52, VAL-011

**参考：** ADR002/004/007/014;S1/S2/S3/S4/S5

**生产接口检查位置：** `src/adapters/capabilities.ts`; `src/adapters/subagents.ts`; `src/adapters/route-requirements.ts`

**夹具：** 现有 subagents/native-owner；真实Pi候选依赖的独立临时副本

**领域步骤（按上面的层级规则执行）：** 先用固定lock的foreground/fresh正常启动并检查nativeRunId；每次只改变一项运行契约，再通过真实preflight/事件通道启动；保存requested/resolved/observed三者及doctor。

**成功对照：** foreground/fresh/显式cwd/工具/模型/观察通道全匹配；真实执行可启动并完整返回身份。

**负向对照：** 在临时adapter副本把注册ack当ready、requested当observed或引用另一安装的lock，相关负例必须失败。

**实现依赖：** 未支持后台/fork不要求新增产品能力；验证拒绝与合法foreground正例。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G04.mode | foreground/fresh/cwd 全合格，对照 background/fork 未认证 | 只认证实际合格组合；不能由其他模式通过继承 |
| G04.drift | 分别改 runtime hash、patch、tools、thinking、context、cwd、profile | 每次仅一个关键差异就使依赖动作拒绝，requested 不填充 observed |
| G04.channel | 注册 ack 成功但 IPC 不可读、不可写、producer 错、关键 seq 缺失 | 启动屏障不放行或关键观察失效后阻止后续危险动作 |
| G04.identity | 响应 model 不同/缺失；另仅可选元数据缺失 | 未知身份如实保留，关键不匹配拒绝；可选缺失不错误全局禁用 |

**精确义务索引：** EXE-001:U, EXE-001:A, EXE-002:U, EXE-002:A, EXE-003:U, EXE-003:A, EXE-003:P, EXE-004:U, EXE-004:A, EXE-004:P, EXE-007:U, EXE-007:A, EXE-007:E, EXE-012:U, EXE-012:A, EXE-012:P, VAL-011:A, VAL-011:V, T04:U, T04:A, T04:P, T06:U, T06:A, T06:P, T07:U, T07:A, T07:P, T08:U, T08:A, T08:P, T17:U, T17:A, T17:P, T48:U, T48:A, T48:P, T52:U, T52:A, T52:P

### G05 — 投递已接受但启动或执行中断

义务数：12；当前 P0–P3 缺口：12。

**ID：** EXE-005, EXE-006, T01, T02

**参考：** ADR004/010/014;S1/S5

**生产接口检查位置：** `src/adapters/subagents.ts`; `src/contracts/task.ts`

**夹具：** subagents fixture、可控制启动前退出的真实child

**领域步骤（按上面的层级规则执行）：** 父端得到accepted后用barrier令child在agent_start前退出；另一用例令实际child收到取消且上报exitCode0/interrupted；等待父端持久结果并查询job。

**成功对照：** accepted/start/完整终态和全部验收条件齐全，任务可完成。

**负向对照：** 将accepted或exit0单独转换success，必须误触断言。

**实现依赖：** 需子进程屏障，不能只构造结果对象给A/P层。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G05.accepted | accepted 后在 agent_start 前退出 | delivery accepted 保留，execution failed，任务不得 completed |
| G05.interrupt | exitCode=0 且 interrupted=true；另 timeout=true | 中断/超时优先于退出码，不算成功 |
| G05.healthy | accepted→start→完整终态且 required 验收齐全 | 合法任务可完成，原生身份与回执一一对应 |
| G05.missing-end | accepted 后无可核实终态 | 保持 unknown 并阻止依赖动作，不能假造 exit0 |

**精确义务索引：** EXE-005:U, EXE-005:A, EXE-005:E, EXE-006:U, EXE-006:A, EXE-006:E, T01:U, T01:A, T01:P, T02:U, T02:A, T02:P

### G06 — 关键事件去重、断序与补投递

义务数：14；当前 P0–P3 缺口：14。

**ID：** EVD-001, EVD-002, T14, T15

**参考：** ADR004/010/011/018;S1/S5

**生产接口检查位置：** `src/store/database.ts`; `src/evidence/progress.ts`

**夹具：** 真实SQLite双连接、生产事件写入器、进程IPC supervisor

**领域步骤（按上面的层级规则执行）：** 按1/2/3写关键事件，注入2缺失、3先到、同ID同payload重投与同ID异payload；杀父进程后以新连接重放通知并查询依赖动作。

**成功对照：** 合法producer按1/2/3发送完整一致事件，依赖动作一次且最终事实完整。

**负向对照：** 移除事件唯一检查或把关键洞当普通丢进度，必须失败。

**实现依赖：** 需持久事件故障注入与独立连接；现有U结果不可自动提为P。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G06.dedup | 相同 eventId/producer/seq/payload 重投两次 | 事实一份，补通知不重执行 |
| G06.conflict | 同 eventId 或同 producer/seq 配不同关键 payload | 记录冲突且阻塞依赖，不能覆盖原事实 |
| G06.gap | 1、3 先到，2 稍后到/永远丢失 | 关键洞未补齐保持 unknown；补齐后合法推进一次 |
| G06.progress | 只丢低优先级进度；完成已落盘但通知丢失 | 进度标 stale 不改 Outcome；完成补投递而非重执行 |

**精确义务索引：** EVD-001:U, EVD-001:S, EVD-001:P, EVD-002:U, EVD-002:S, EVD-002:P, T14:U, T14:S, T14:P, T14:E, T15:U, T15:S, T15:P, T15:E

### G07 — 五维结果、合法恢复及PARTIAL

义务数：31；当前 P0–P3 缺口：29。

**ID：** EVD-003, EVD-010, EVD-011, EVD-012, T03, T05, T09, T12, T13, T61

**参考：** ADR004/005/014/017/018;S15/S25/S26

**生产接口检查位置：** `src/contracts/task.ts`; `src/evidence/progress.ts`

**夹具：** task/recovery reducers、固定workflow与独立verifier/reviewer

**领域步骤（按上面的层级规则执行）：** 手写五维真值表；先全满足形成COMPLETED，再每次仅撤去一个required条件；执行失败→授权恢复→当前快照验收，并在新连接读取历史；optional失败按预先TaskSpec分别允许/禁止PARTIAL。

**成功对照：** 当前快照全required合格、独立审查完整、无未知writer，明确COMPLETED。

**负向对照：** 让request_finish决定COMPLETED或删除未解决failure条件，单条件反例必须失败。

**实现依赖：** 9.6 PARTIAL 已实现；仍需各层必测变体和生产入口断言，构造 receipt 不算 E。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G07.complete | 五维及所有 required 全满足、当前 snapshot、无未知 writer | COMPLETED；事实与输出一致 |
| G07.single-reject | 逐一将 delivery/execution/contract/acceptance/observation 或 required 条件改 false/unknown/not_run | 对应依赖阻止完成，其他条件保持全合格 |
| G07.recovery | 失败 attempt 后新合格 attempt 与明确 resolvedFailure 关系 | job 可完成但旧失败、实际路线和恢复关系不改写 |
| G07.partial | optional 失败且其余 required 通过，allowPartial 分别 true/false | 仅前者 PARTIAL 并披露缺口；后者不完整完成 |
| G07.late-success | 终态 CANCELLED 后迟到 completed | 原终态不复活，不派新步骤 |

**精确义务索引：** EVD-003:U, EVD-003:S, EVD-003:E, EVD-010:U, EVD-010:S, EVD-010:E, EVD-011:U, EVD-011:S, EVD-011:E, EVD-012:U, EVD-012:S, EVD-012:E, T03:U, T03:S, T03:E, T05:U, T05:S, T05:A, T05:P, T09:U, T09:S, T09:E, T12:U, T12:S, T12:E, T13:U, T13:S, T13:E, T61:U, T61:S, T61:E

### G08 — EvidencePacket容量、引用与不可信日志

义务数：19；当前 P0–P3 缺口：19。

**ID：** EVD-005, EVD-006, T54, T55, T56, T58

**参考：** ADR004/005/016;S11/S12/S19

**生产接口检查位置：** `src/evidence/packet.ts`; `src/store/artifacts.ts`

**夹具：** packet/artifact fixtures、真实父Pi上下文捕获HTTP端

**领域步骤（按上面的层级规则执行）：** 固定job/snapshot的源码、日志和claims；构造硬状态预算前一字节/恰好/超限；注入不存在、跨job、倒置范围引用及日志重置预算指令；提交到实际packet/决策入口。

**成功对照：** 合法同job同snapshot引用、完整硬事实在字节预算内，packet成功且事实无损。

**负向对照：** 删掉最大的一组必需错误让packet勉强通过，或把claim晋级check，必须失败。

**实现依赖：** A/E需要实际父模型请求输入，不是仅检查compile结果；无外发时观察明确拒绝。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G08.size | 硬状态编码字节数为预算N−1/N/N+1，含多字节 Unicode | 前两者完整保留；超限明确 PACKET_TOO_LARGE，不静默裁必需事实 |
| G08.reference | 不存在/跨 job/旧 snapshot/倒置范围/篡改 hash 引用 | 拒绝引用并保留授权、预算、Outcome |
| G08.claim | 存在合法出处但内容仅 worker 自述 | 保持 claim，不变为 verifier 事实 |
| G08.injection | 日志包含重置预算、任意 shell 和假成功指令 | 仅数据，权限与任务终态不变 |
| G08.grouping | 多组错误超正文预算但完整索引可容纳 | 分组摘要保留每组计数和全部 ID，无法容纳则显式阻塞 |

**精确义务索引：** EVD-005:U, EVD-005:S, EVD-005:A, EVD-005:E, EVD-006:U, EVD-006:S, EVD-006:E, T54:U, T54:S, T54:E, T55:U, T55:S, T55:E, T56:U, T56:S, T56:E, T58:U, T58:S, T58:E

### G09 — 失败五层传播、低噪声状态及无UI

义务数：29；当前 P0–P3 缺口：29。

**ID：** CFG-014, EVD-004, T10, T11, T53, T57, T83, T84, VAL-015

**参考：** ADR004/007/014/018;S12/S19/S26

**生产接口检查位置：** `src/evidence/progress.ts`; `index.ts`

**夹具：** RPC/PTY Pi、压缩服务fixture、结构化输出observer

**领域步骤（按上面的层级规则执行）：** 生成不同类别required failure并压缩/截断历史；捕获raw→SQLite→receipt→父模型下一请求body→PTY或无UI输出；用fake clock驱动100次相同状态更新，再插入关键变化。

**成功对照：** 同一required failure在五层均可观察到；状态查询正确保留阻塞且不重复刷屏。

**负向对照：** 仅从父模型input删除blocker（保留details和DB），传播测试必须红；调低UI文字不能使receipt通过。

**实现依赖：** 传播oracle需逐层字段对应；没有父请求时应记录阻塞输出，不伪造该层已发送。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G09.five-layers | content=Done，details/raw/DB 有 required failure，再压缩历史 | raw/DB/receipt/下一父请求/实际展示均保留同一 blocker |
| G09.one-layer-loss | 每次只在一层删除错误类别或缺口 | 传播验收失败，即使其他四层正确 |
| G09.throttle | 固定clock下100次相同状态，再插入关键状态变化 | 重复输出不超配置节流阈值；关键变更及时显示 |
| G09.privacy | 在错误/参数中注入合成 secret marker | 持久/回执/父请求/展示中 marker 全链不泄露 |
| G09.no-ui | 相同账本分别走PTY和无UI | 状态语义一致；缺 footer 插件不影响必需错误可见 |

**精确义务索引：** CFG-014:U, CFG-014:A, CFG-014:E, EVD-004:U, EVD-004:S, EVD-004:A, EVD-004:E, VAL-015:A, VAL-015:P, VAL-015:E, VAL-015:V, T10:U, T10:S, T10:E, T11:U, T11:S, T11:E, T53:U, T53:S, T53:E, T57:U, T57:S, T57:E, T83:U, T83:S, T83:E, T84:U, T84:S, T84:E

### G10 — 提议新鲜度、唯一动作及重复指纹

义务数：36；当前 P0–P3 缺口：36。

**ID：** EVD-007, EVD-008, EVD-009, RTB-019, T59, T60, T62, T63, T64, T65, T70, T85

**参考：** ADR005/006/016;S11/S12/S13

**生产接口检查位置：** `src/evidence/decision-ledger.ts`; `src/orchestration/service.ts`

**夹具：** decision-ledger、受限测试提议入口、真实TaskService

**领域步骤（按上面的层级规则执行）：** 生成合法proposal后在dispatch前barrier修改source/TaskSpec/授权，逐项检查失效；另一分支只改心跳或费用，保留decisionRevision并再次预算准入；重复提交同fingerprint。

**成功对照：** 新鲜合法proposal、权限预算资源全满足，恰好派发一次。

**负向对照：** 跳过dispatch前二次准入或每次心跳增加revision，分别使安全反例和可进展正例失败。

**实现依赖：** 公共提议入口尚不足时需要受限测试harness接生产dispatcher；不能增设旁路dispatcher。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G10.semantic-drift | proposal 后依次只改源码/TaskSpec/权限/关键证据 | dispatch 前拒绝旧 revision 并重新投影 |
| G10.observation-only | 只改 heartbeat/费用/reservation，分别预算仍足/已不足 | 前者不机械失效且可准入；后者明确预算拒绝 |
| G10.invalid | 空、截断、多JSON、任意shell、新provider、删除required | schema/准入拒绝；不默认 advance |
| G10.duplicate | 同 fingerprint 重复两次；后一次恰逢资源释放 | 只允许一次合法动作；无重复管理者调用 |
| G10.cancel | 提议接收与最终派发之间撤销 owner | 旧提议不派发，TaskSpec 不被修改 |

**精确义务索引：** EVD-007:U, EVD-007:S, EVD-007:E, EVD-008:U, EVD-008:S, EVD-008:E, EVD-009:U, EVD-009:S, EVD-009:E, RTB-019:U, RTB-019:S, RTB-019:E, T59:U, T59:S, T59:E, T60:U, T60:S, T60:E, T62:U, T62:S, T62:E, T63:U, T63:S, T63:E, T64:U, T64:S, T64:E, T65:U, T65:S, T65:E, T70:U, T70:S, T70:E, T85:U, T85:S, T85:E

### G11 — 存储故障、迁移备份与回退

义务数：10；当前 P0–P3 缺口：9。

**ID：** EVD-013, T47, T76

**参考：** ADR010/011;S1/S5

**生产接口检查位置：** `src/store/maintenance.ts`; `src/store/database.ts`

**夹具：** SQLite schema1真实fixture、只读/损坏副本、将来迁移测试driver

**领域步骤（按上面的层级规则执行）：** 建立含intent、unknown reservation、owner与工作区引用的数据库；分别注入SQLITE_BUSY/commit失败/驱动ENOSPC/工件缺失；在迁移备份、改schema、commit、恢复各切点中断再重启。

**成功对照：** 静止schema1正常升级2，同次维护受保护回退后业务事实逐表相等。

**负向对照：** 迁移时丢一条unknown或fallback新建空DB，守恒断言必须失败。

**实现依赖：** schema 1→2 显式迁移/回退已有实现；补 busy/ENOSPC/业务事实/未知占用组合。仅恢复同次维护备份；不设计任意旧备份覆盖为成功。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G11.upgrade | 含未结intent/unknown预算/claim/工作区的schema1正常升级2 | 业务逐表摘要守恒，备份私有且hash匹配 |
| G11.cuts | 在备份/维护标记/DDL/commit/标记清理各切点杀维护进程 | 重启finish或同次rollback保持事实；不清库当新任务 |
| G11.corruption | DB消失/损坏/未来schema；备份缺失或hash错 | 依赖动作拒绝且原现场保留 |
| G11.io | 隔离驱动注入busy/commit失败/ENOSPC | 事务回滚或持久阻塞，不生成未记录外部动作 |
| G11.restore-fence | 活动owner、外部新业务事实、旧连接在物理替换后写入 | 维护/恢复或旧写入被拒绝；不能恢复任意旧备份清预算 |

**精确义务索引：** EVD-013:U, EVD-013:P, T47:U, T47:S, T47:P, T47:E, T76:U, T76:S, T76:P, T76:E

### G12 — 外部调用C0–C5崩溃与未知ACK

义务数：19；当前 P0–P3 缺口：19。

**ID：** EXE-008, REC-021, T39, T40, T71

**参考：** ADR003/009/010/011;S1/S5/S9

**生产接口检查位置：** `src/store/database.ts`; `src/adapters/pi-interactive.ts`; `src/adapters/subagents.ts`; `src/verification/runner.ts`

**夹具：** 现有store-worker/process，新增真实start/continue/verify三类切点hook

**领域步骤（按上面的层级规则执行）：** 对start、continuation、可信verify各执行C0–C5；supervisor收到精确切点信号才kill父进程；外部接收端独立保存动作ID及生效事实；新进程对账，查询持久状态后尝试继续。

**成功对照：** start/continue/verify不崩溃各正常一次，外部动作与settle一一对应。

**负向对照：** 在C2/C3重启时重发相同动作、C5重复settle，接收端计数和账本断言必须失败。

**实现依赖：** 需生产adapter切点可观测性，部分切点目前只有底层P证据；缺原生对账能力保持BLOCKED_UNKNOWN。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G12.crash-actions | start/continue/verify 分别在C0–C5准确barrier杀父进程 | 按切点表补记录/通知或保留unknown，不重复外部动作 |
| G12.send-state | 同一恢复intent分别证明未发送/终态已确认/是否已发未知 | 只前两者按事实释放或结算，未知继续占用 |
| G12.lost-ack | 接收端已生效，ack丢失或原生工件缺失 | 对账原身份；无法核实不重放 |
| G12.late-notification | 结算后通知丢失再重复到达 | 只补通知，计费/副作用均不重复 |

**精确义务索引：** EXE-008:S, EXE-008:A, EXE-008:P, REC-021:S, REC-021:A, REC-021:P, REC-021:E, T39:U, T39:S, T39:P, T39:E, T40:U, T40:S, T40:P, T40:E, T71:U, T71:S, T71:P, T71:E

### G13 — 唯一owner、撤权及失联writer

义务数：28；当前 P0–P3 缺口：28。

**ID：** EXE-009, EXE-010, EXE-011, SCH-014, T41, T42, T49, TK14

**参考：** ADR003/008/010/011;S1/S5

**生产接口检查位置：** `src/adapters/process-identity.ts`; `src/adapters/pi-interactive.ts`; `src/orchestration/service.ts`

**夹具：** 真实parent/child/descendant三进程，持续写sentinel，独立supervisor

**领域步骤（按上面的层级规则执行）：** writer每次获barrier许可写一次；令parent失联或lease到期，启动竞争owner；在child取消ack但descendant仍活的窗口请求第二writer；最后由supervisor确认原process-group结束再对账。

**成功对照：** 确认旧进程及所有被覆盖外部工作已结束后，新writer正常取得释放资源。

**负向对照：** 只按lease释放claim、用cancel ack当终止证据，必须使双writer检测失败。

**实现依赖：** 5.5的任意外部工作覆盖不足；无法追踪的组合必须拒绝认证，测试不宣称OS沙箱。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G13.lease | 原writer仍活但lease过期或parent失联 | 新owner不能释放claim或启动冲突writer |
| G13.descendant | child取消ack但孙进程继续写/脱离group | termination未知，占用保留，supervisor看到的事实优先 |
| G13.identity | 旧PID复用、启动tick不同、不同PID namespace | 不能以不匹配身份证明旧writer终止 |
| G13.release | supervisor确认全部已覆盖进程停止且无未结动作 | 对账后竞争者可继续，避免永远阻塞 |
| G13.read-only | 未知writer存在时请求独立只读诊断 | 按实际资源边界允许诊断，不误允许同现场写入 |

**精确义务索引：** EXE-009:S, EXE-009:A, EXE-009:P, EXE-010:S, EXE-010:A, EXE-010:P, EXE-011:S, EXE-011:A, EXE-011:P, SCH-014:S, SCH-014:P, SCH-014:E, T41:U, T41:S, T41:P, T41:E, T42:U, T42:S, T42:P, T42:E, T49:U, T49:S, T49:A, T49:E, TK14:U, TK14:S, TK14:P, TK14:E

### G14 — 静默构建、请求timeout与整体deadline

义务数：18；当前 P0–P3 缺口：17。

**ID：** EXE-013, REC-011, REC-012, T16, T51

**参考：** ADR008/010;S5/S9

**生产接口检查位置：** `src/verification/runner.ts`; `src/reliability/recovery.ts`

**夹具：** VerifyRunner真实静默子进程、挂起HTTP流、可控期限

**领域步骤（按上面的层级规则执行）：** 构建启动后不输出且通过独立heartbeat保持存活；期限前查状态，期限到后走终止协议；另设quota forever但单次HTTP超时/整体deadline先到，抓取消和对账。

**成功对照：** 静默子进程在deadline前被测试barrier释放，退出成功且无错误超时。

**负向对照：** 去掉requestTimeout或以无输出直接失败；独立watchdog/成功对照必须发现。

**实现依赖：** 有限真实watchdog只作为挂死失败阈值；事件顺序不靠sleep猜测。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G14.silent | 构建不输出但进程与独立barrier仍活 | 期限前保持运行，释放barrier后成功 |
| G14.deadline | tool/request/native期限分别先到或相等 | 先到的有效期限约束执行；forever不覆盖单次timeout |
| G14.timeout-unknown | 请求发出后timeout，无法确认终态 | 保留unknown reservation，不立刻重复发送 |
| G14.kill | 忽略SIGTERM或孙进程尚存 | 升级受控终止或明确unknown；不假称全停 |

**精确义务索引：** EXE-013:U, EXE-013:A, EXE-013:P, REC-011:U, REC-011:S, REC-011:A, REC-011:P, REC-012:U, REC-012:S, REC-012:A, REC-012:P, T16:U, T16:A, T16:P, T51:U, T51:S, T51:A, T51:E

### G15 — 临时额度与永久、网络故障的分类边界

义务数：17；当前 P0–P3 缺口：15。

**ID：** REC-003, REC-004, REC-005, T20, T26

**参考：** ADR004/010;S6/S9

**生产接口检查位置：** `src/reliability/classifier.ts`; `src/reliability/recovery.ts`

**夹具：** HTTP/body/headers表驱动fixture及真实Pi错误适配器

**领域步骤（按上面的层级规则执行）：** 真实Pi接收单个错误后读取归一化failure及下一动作；分别喂resource usage、429、401/403、billing、policy、context、连接失败与unknown；耗尽有限network政策。

**成功对照：** 绑定明确临时429后按规则冷却，下一完整成功恢复；不把永久错误混入。

**负向对照：** 将所有错误归429或网络耗尽转forever，接收端上限断言必须失败。

**实现依赖：** 真实服务分类样本来源属于6.1缺口；没有样本只能声明synthetic行为。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G15.classes | resource usage/429/401/403/billing/policy/context/network/unknown逐条输入 | 按配置给固定类别；永久错误不进入forever |
| G15.conflict | HTTP429与auth body冲突；200 error body；code缺失 | 原来源保留，错误不由HTTP成功或429一概覆盖 |
| G15.network-bound | 网络尝试/等待上限N−1/N/N+1 | 仅限额内可重试，耗尽后暂停，不转配额forever |
| G15.usage | 有来源的usage压力与小时/周/月窗口分别匹配 | 按样本绑定解释，资源压力不假定月额度耗尽 |

**精确义务索引：** REC-003:U, REC-003:S, REC-003:A, REC-004:U, REC-004:S, REC-004:A, REC-005:U, REC-005:S, REC-005:A, T20:U, T20:S, T20:A, T20:E, T26:U, T26:S, T26:A, T26:E

### G16 — 冷却时间、时钟跳变与持久重启

义务数：26；当前 P0–P3 缺口：23。

**ID：** REC-008, REC-009, REC-010, T21, T25, TK11, TK12

**参考：** ADR010/011;S6/S9

**生产接口检查位置：** `src/reliability/classifier.ts`; `src/reliability/recovery.ts`; `src/reliability/stages.ts`

**夹具：** fake wall/monotonic时钟、真实parent重启、独立receiver

**领域步骤（按上面的层级规则执行）：** 写服务notBefore及本地cooldown；在前1ms/等于/后1ms触发调度；仅对测试clock注入墙钟回退/休眠跨多个tick；杀父后重启同scope并对账已发送状态。

**成功对照：** 时间达到较晚notBefore且身份/队列/预算均合格，一个恢复动作合法发出。

**负向对照：** 比较符号反转、休眠后逐tick补发、重启重置stageEnteredAt，必须失败。

**实现依赖：** P层可用注入clock但须真实进程/SQLite/receiver；不能改机器系统时钟。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G16.not-before | server=2000、本地=1500；时钟1999/2000/2001，再交换两限制 | 较晚限制前零动作；到时仍需其他准入合格 |
| G16.retry-after | delta秒/HTTP-date/过去/非法/缺失；hour/week/month可信reset | 可信约束取更晚，无依据的窗口保持明确阻塞 |
| G16.jitter | 正向jitter取0与配置最大值 | 都不得早于服务notBefore |
| G16.clock | 只修改测试墙钟：倒退、休眠跨100tick、时间不确定 | 保守延后或合并一个到期动作，不补发积压 |
| G16.restart | 同scope跨两个真实父进程恢复等待 | incident/阶段起点/deadline/预算不刷新；无父期间无daemon派发 |

**精确义务索引：** REC-008:U, REC-008:S, REC-008:A, REC-008:P, REC-009:U, REC-009:S, REC-009:A, REC-009:P, REC-010:U, REC-010:S, REC-010:A, REC-010:P, T21:U, T21:S, T21:A, T21:E, T25:U, T25:S, T25:A, T25:E, TK11:S, TK11:A, TK11:E, TK12:S, TK12:A, TK12:E

### G17 — 长上下文续跑、canary和完整流成功

义务数：44；当前 P0–P3 缺口：33。

**ID：** REC-001, REC-007, REC-015, REC-016, REC-017, REC-018, T18, T19, T22, T23, TK09, REC-006

**参考：** ADR003/004/010;S5/S6/S9/S19

**生产接口检查位置：** `src/reliability/recovery.ts`; `src/adapters/pi-interactive.ts`

**夹具：** 现有Pi RPC/PTY，长输入+工具sentinel fixture、流故障server

**领域步骤（按上面的层级规则执行）：** 原任务先实际修改一次文件再收到限流；native retry成功对照与耗尽后外层恢复分别执行；canary成功后长请求继续失败；最终完整流成功才关闭incident，检查原session/continuation。

**成功对照：** 原生短重试成功不外层续跑；耗尽后合法原生continuation可最终完成。

**负向对照：** 以canary200或agent_end当恢复完成、续跑重放原始任务，接收端与sentinel必须发现。

**实现依赖：** Q1/S与Q2/A/E分别登记；P需要真实重启/共享进程观察；真实Qwen绑定由G32另验。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G17.native-retry | 首次429后SDK原生短重试完整成功 | 外层continuation=0，原生实际请求独立计数 |
| G17.settled | agent_end后分别仍有queue/compact/retry | 全部settled且重新准入前不得外层继续 |
| G17.long-resume | 原任务先工具写一次，限流耗尽后多轮等待再完整成功 | 同session/continuation，工具副作用恰一次，失败历史保留 |
| G17.canary | 小canary成功但原长请求再次429 | 同incident延长等待，不清预算、不全体放行 |
| G17.stream | HTTP200后error/截断/超时，对照完整成功流 | 前三者不关breaker，只有完整真实成功可恢复 |
| G17.no-waiter | 全部waiter结束/取消后再次触发timer | 零新探测，清除本scope旧timer/listener；canary无项目或工具 |

**精确义务索引：** REC-001:S, REC-001:A, REC-001:E, REC-006:S, REC-006:A, REC-006:E, REC-007:S, REC-007:A, REC-007:E, REC-015:S, REC-015:A, REC-015:P, REC-015:E, REC-016:S, REC-016:A, REC-016:P, REC-016:E, REC-017:S, REC-017:A, REC-017:P, REC-017:E, REC-018:S, REC-018:A, REC-018:P, REC-018:E, T18:U, T18:S, T18:A, T18:E, T19:U, T19:S, T19:A, T19:E, T22:U, T22:S, T22:A, T22:E, T23:U, T23:S, T23:A, T23:E, TK09:S, TK09:A, TK09:E

### G18 — 工具命令共用状态与全部await撤权竞态

义务数：30；当前 P0–P3 缺口：27。

**ID：** CFG-001, CFG-012, CFG-013, REC-019, T35, T36, T37, T38, REC-020

**参考：** ADR003/005/010;S5

**生产接口检查位置：** `index.ts`; `src/reliability/recovery.ts`; `src/orchestration/service.ts`; `src/adapters/terminal-input.ts`

**夹具：** 真实RPC/PTY输入、TaskService、每个await测试barrier

**领域步骤（按上面的层级规则执行）：** 工具创建job后用命令pause/resume/stop并从两个入口查询；在每个await的before-send窗口触发人工输入/取消或先完成await，按预定义两种顺序释放barrier；旧回调到达后观察外部动作。

**成功对照：** 未撤权且其余条件合法时，await完成后的当前owner动作可执行一次。

**负向对照：** 去掉任一个await后的epoch检查，仅该barrier反序用例必须失败。

**实现依赖：** 13.5需核对真实可达await清单；原规范要求的成功接口未实现时保持待办。仅未声明支持的setModel/proxy组合按明确拒绝验证，不能用拒绝取得成功路径认证。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G18.shared-entry | kernel_task建立job，再用/orchpause/resume/stop并双入口查询 | 同job状态；不存在入口专属队列 |
| G18.both-orders | R01–R10每个撤权事件与await完成按两种顺序释放 | 先撤权零发送；先发送只记既有事实，迟到回调不追加动作 |
| G18.input-origin | 真实用户输入、可信内部恢复消息、终端协议回应分别到达 | 用户撤权且按键不吞；内部/协议不自我取消 |
| G18.lifecycle | reload/fork/switch/shutdown各发生两次 | 旧ctx/epoch/timer失效，不叠加handler |
| G18.resume-blocker | required失败/unknown writer/notBefore未到/预算耗尽分别resume | 原blocker/预算保留，只准入合法动作；终态不得重开 |

**精确义务索引：** CFG-001:U, CFG-001:E, CFG-012:U, CFG-012:A, CFG-012:E, CFG-013:U, CFG-013:A, CFG-013:E, REC-019:S, REC-019:A, REC-019:E, REC-020:S, REC-020:A, REC-020:E, T35:U, T35:S, T35:A, T35:E, T36:U, T36:S, T36:A, T36:E, T37:U, T37:S, T37:A, T37:E, T38:U, T38:S, T38:A, T38:E

### G19 — 十会话共享许可与独立任务进展

义务数：22；当前 P0–P3 缺口：21。

**ID：** REC-013, REC-014, REC-022, SCH-013, T24, TK13

**参考：** ADR003/008/009/011;S5/S9

**生产接口检查位置：** `src/reliability/incidents.ts`; `src/orchestration/scheduler.ts`; `src/orchestration/service.ts`

**夹具：** 十个真实Pi父会话、共享SQLite、同池/异池loopback

**领域步骤（按上面的层级规则执行）：** 十会话通过barrier同时到达冷却边界争同pool；对获许可者依次注入未发送退出/已终态/发送未知；用独立pool与workspace任务B验证其可完成；另测同父多job。

**成功对照：** 共享池第一个确认完成释放后另一个等待者进展，独立池任务也能完成。

**负向对照：** 对每session独立计许可或等待时占死所有host slot，分别使并发上限和B进展断言失败。

**实现依赖：** 真实十会话成本用loopback；不能启动十个真实付费Qwen任务制造限流。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G19.ten | 十会话同root同pool在到期barrier竞争 | 同pool至多一个half-open真实请求 |
| G19.holder | 许可者依次未发取消/已确认终态/发送未知后失联 | 释放/结算/保留分别正确，不仅靠lease释放 |
| G19.independent | A等待额度且原执行已停，B在独立pool/workspace | A释放activity/repo active槽且保留现场预算；B真正完成 |
| G19.unknown-writer | A有未知writer再让同现场B与独立现场C竞争 | B阻塞，C按实际资源准入，A必要写占用保留 |
| G19.roots | 同root与不同root分别运行竞争 | 只声明配置协调范围，不声称不同root全宿主互斥 |

**精确义务索引：** REC-013:S, REC-013:A, REC-013:P, REC-013:E, REC-014:S, REC-014:A, REC-014:P, REC-014:E, REC-022:S, REC-022:A, REC-022:P, REC-022:E, SCH-013:S, SCH-013:P, SCH-013:E, T24:S, T24:A, T24:P, T24:E, TK13:S, TK13:A, TK13:E

### G20 — 硬条件先过滤与thinking语义

义务数：14；当前 P0–P3 缺口：7。

**ID：** RTB-001, RTB-002, T27, T78

**参考：** ADR002/013/016;S21/S22/S23

**生产接口检查位置：** `src/orchestration/policy.ts`; `src/adapters/route-requirements.ts`; `src/orchestration/service.ts`

**夹具：** policy/property表、实际profile preflight与生产route selector

**领域步骤（按上面的层级规则执行）：** 用全合格两条路线建立确定性选择正例；让最低价候选每次只缺一种required能力；同名high但mapping/协议不同逐route核验；重排目录验证选择稳定。

**成功对照：** 两候选所有硬条件满足，按配置偏好和稳定ID选出唯一候选。

**负向对照：** 用综合分数覆盖缺失hard constraint，单条件反例必须失败。

**实现依赖：** 10.1完整认证待办；此批次S不等于所有provider thinking已认证。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G20.hard | 合法候选A更便宜；逐一缺授权/tools/context/thinking/transport/观察/资源/预算/风险条件 | 每个独立不满足都拒绝A，分数不能抵消；合法B仍可选 |
| G20.missing | 同一required字段false/缺失/null/0/字符串true | 均不当true准入 |
| G20.thinking | 两路线同名high但映射/协议/上下文不同 | 逐路线核验实际满足程度，unknown不按低风险放行 |
| G20.ordering | 全合格候选逆序输入、同偏好tie、无合法候选 | 选择稳定ID及理由可重放；空合法集不派发 |

**精确义务索引：** RTB-001:U, RTB-001:S, RTB-001:A, RTB-002:U, RTB-002:S, RTB-002:A, T27:U, T27:S, T27:A, T27:P, T78:U, T78:S, T78:A, T78:P

### G21 — 恢复链阶段与事故备胎上限

义务数：24；当前 P0–P3 缺口：23。

**ID：** RTB-003, RTB-004, RTB-005, RTB-010, T28, T50

**参考：** ADR003/009/010/016;S5/S9

**生产接口检查位置：** `src/reliability/stages.ts`; `src/orchestration/service.ts`

**夹具：** stage/recovery fixtures、真实Pi主备loopback、持久时钟

**领域步骤（按上面的层级规则执行）：** 设阶段A有限等待→B备胎→A尾段，事故上限4；在B等待时让A成为候选；在B运行时让A可用；跨重启/暂停推进阶段直到4次备胎后请求第5次。

**成功对照：** 合法A→B→A链在冷却、预算和安全边界均满足时实际推进，不永久等待。

**负向对照：** 备胎成功清incident或重启重置stage时间，守恒和发送上限断言必须失败。

**实现依赖：** 10.5基础已实现；E需实际换路线边界证据，不支持主会话自动跨模型仍拒绝。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G21.stages | A有限等待→B→A forever尾段；唯一stageID但允许路线重复 | 阶段身份与进入时间稳定，重复stageID拒绝 |
| G21.return | B等待时A恢复；对照B仍在写入时A恢复 | 只在安全边界申请主力许可，不双writer |
| G21.attempts | 事故备胎上限4，使用3/4/请求第5次 | 最多4次；第5次不发并回主力等待 |
| G21.continuity | B成功但A未真实恢复，再fallback；暂停/重启 | 同incident累计不清，阶段deadline不刷新 |
| G21.constraints | 未授权阶段、主备同pool较晚notBefore、active writer逢阶段到期 | 跳过未授权；遵守共享冷却；阶段时限不强杀writer |

**精确义务索引：** RTB-003:U, RTB-003:S, RTB-003:A, RTB-003:E, RTB-004:U, RTB-004:S, RTB-004:A, RTB-004:E, RTB-005:U, RTB-005:S, RTB-005:A, RTB-005:E, RTB-010:U, RTB-010:S, RTB-010:A, RTB-010:P, T28:U, T28:S, T28:A, T28:P, T50:U, T50:S, T50:A, T50:P

### G22 — 账号遥测与网络路径失败

义务数：14；当前 P0–P3 缺口：12。

**ID：** RTB-006, T32, T34, RTB-014

**参考：** ADR002/009/013;S6/S7/S8条件适用

**生产接口检查位置：** `src/adapters/telemetry.ts`; `src/orchestration/policy.ts`; `src/adapters/http-transport.ts`

**夹具：** private telemetry file、不可用HTTP/SOCKS代理地址、独立direct接收端

**领域步骤（按上面的层级规则执行）：** 配置明确network与account/bucket；分别提供新鲜匹配、过期、错账号/桶/来源遥测；网络绑定不可用时尝试protected dispatch，同时监视direct receiver。

**成功对照：** 新鲜匹配账号/桶/来源与支持的direct绑定允许合法protected请求。

**负向对照：** proxy失败后fallback fetch direct或复用错账号缓存，独立receiver/账号断言必须失败。

**实现依赖：** 当前仅direct执行受支持；SOCKS测试首先是拒绝验收，不能凭拒绝通过宣称已支持SOCKS。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G22.fresh | 账号a桶b来源s，freshness=1000，观测age999/1000/1001 | 前两者可采用，过期unknown；未来时间拒绝 |
| G22.wrong | 逐一错account/bucket/source，另remaining未知/负数 | 不准入依赖该遥测的protected路线 |
| G22.binding-change | 缓存后换凭证引用/账号或文件内容 | 旧遥测不能沿用新绑定，诊断不泄露凭证 |
| G22.network | 配置代理不可用/未支持SOCKS，旁边放direct接收端 | 明确拒绝且direct收不到请求，不悄悄回退或误记quota事故 |
| G22.positive | direct与匹配新鲜遥测、预算和其余准入全合格 | 请求确实可发；文件权限错误/损坏时拒绝 |

**精确义务索引：** RTB-006:U, RTB-006:S, RTB-006:A, RTB-006:E, RTB-014:U, RTB-014:A, T32:U, T32:S, T32:A, T32:P, T34:U, T34:S, T34:A, T34:P

### G23 — 每个真实请求的gate与累计预算

义务数：43；当前 P0–P3 缺口：34。

**ID：** RTB-007, RTB-008, RTB-009, RTB-011, RTB-012, RTB-013, T29, T30, T31, T33, T67, SCH-001

**参考：** ADR003/009/010;S1/S5/S7条件适用

**生产接口检查位置：** `src/store/database.ts`; `src/adapters/http-transport.ts`; `src/orchestration/work-scope.ts`

**夹具：** HTTP gate/真实SDK retry、多个protected child、SQLite独立连接

**领域步骤（按上面的层级规则执行）：** 设最后1许可，barrier同时触发多个真实请求；逐路径执行主生成/SDK retry/summary/compact/child/helper并在gate前拒绝；settle重复/乱序后换attempt/fork/scope别名；预算归零时跑可信纯CPU检查。

**成功对照：** 剩一许可时一个真实请求发出并只结算一次；纯本地检查不耗模型额度。

**负向对照：** 明确构造吞gate异常继续send的坏adapter；接收端必须检出，不能以hook计数自证。

**实现依赖：** 10.2/10.6真实调用路径清单待完整认证；T67仅通用summary预算部分，P4在线Advisor另延期。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G23.paths | 主生成/native retry/summary/compact/child/helper每条路径最后许可或gate拒绝 | 每真实发送有独立requestAttempt；拒绝后receiver=0 |
| G23.budget | incident/workScope上限独立，used+reserved为N−1/N/N+1及0 | 不超任一上限，required reserve不能被可选请求占用 |
| G23.settlement | 同request终态重复/乱序；另独立retry；unknown终态 | 重复只settle一次，retry独立计数，unknown不作0释放 |
| G23.scope | 同逻辑目标resume/fork/new job/model伪造scope/reset | 继承原workScope预算，拒绝模型重置 |
| G23.local | 模型额度为0时执行纯CPU可信check/取消/对账 | 无需模型许可仍可执行；实际发模型的helper仍受gate |
| G23.bypass | 坏adapter吞gate异常继续fetch；受保护HTTP307重定向 | 独立接收端发现违规则验收失败；保护路径不隐式多发POST |

**精确义务索引：** RTB-007:U, RTB-007:A, RTB-007:P, RTB-008:U, RTB-008:A, RTB-008:P, RTB-009:U, RTB-009:A, RTB-009:P, RTB-011:U, RTB-011:S, RTB-011:A, RTB-011:P, RTB-012:U, RTB-012:S, RTB-012:A, RTB-012:P, RTB-013:U, RTB-013:S, RTB-013:A, RTB-013:P, SCH-001:U, SCH-001:S, SCH-001:E, T29:U, T29:S, T29:A, T29:P, T30:U, T30:S, T30:A, T30:P, T31:U, T31:S, T31:P, T31:E, T33:U, T33:S, T33:A, T33:P, T67:U, T67:A, T67:P

### G24 — 依赖图与模型不能刷新任务预算

义务数：20；当前 P0–P3 缺口：18。

**ID：** SCH-002, SCH-003, SCH-004, SCH-005, TK01, TK02

**参考：** ADR005/009/015;S20

**生产接口检查位置：** `src/orchestration/scheduler.ts`; `src/orchestration/work-scope.ts`

**夹具：** 生产Scheduler/TaskService、真实Pi工具入口、记录动作的checker

**领域步骤（按上面的层级规则执行）：** 提交链/fan-out/join任务，分别让required前置失败、独立step成功、合法optional skip；通过kernel_task提交新scope/reset/循环/缺失引用；读取持久计划并等就绪动作。

**成功对照：** 合法chain/fanout/join依赖完成后下游恰好执行一次。

**负向对照：** 把进程exit当依赖pass或接受模型scope字段，必须失败。

**实现依赖：** 固定workflow不能通过用户工具表达通用DAG时，E用测试harness经生产service提交并标范围，不给工具新增任意编排授权。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G24.graph | 空/单节点/chain/fanout/join；环/自引用/缺step | 合法图可执行；非法图原子拒绝不留伪ready |
| G24.required | required前置exit0但验收失败，另独立step合法 | 依赖下游零派发，独立step可执行 |
| G24.optional | optional失败有/无预设skip，对照明确合法skip | 仅预设且确认skip可满足下游条件 |
| G24.once | 上游成功通知重复或乱序 | 合法下游从blocked到ready且只派发一次 |
| G24.scope | 模型新job带scope/reset，宿主fork原任务 | 模型不能刷新预算，继承宿主责任范围 |

**精确义务索引：** SCH-002:U, SCH-002:S, SCH-002:E, SCH-003:U, SCH-003:S, SCH-003:E, SCH-004:U, SCH-004:S, SCH-004:E, SCH-005:U, SCH-005:S, SCH-005:E, TK01:U, TK01:S, TK01:P, TK01:E, TK02:U, TK02:S, TK02:P, TK02:E

### G25 — 资源原子预留、写冻结与队列公平

义务数：38；当前 P0–P3 缺口：34。

**ID：** SCH-007, SCH-008, SCH-009, SCH-010, SCH-011, SCH-012, TK03, TK04, TK05, TK06, TK07, TK08, SCH-006

**参考：** ADR008/011/018;S20

**生产接口检查位置：** `src/orchestration/scheduler.ts`; `src/store/database.ts`; `src/workspace/worktree.ts`

**夹具：** 多个真实parent、canonical临时仓库/软链接、SQLite barrier

**领域步骤（按上面的层级规则执行）：** 两个进程按相反顺序申请同组资源；另测最后slot争抢、writer/verifier共享目录；释放获胜者后推进竞争者；固定有界任务流持续插入高优先级并观察旧ready任务aging。

**成功对照：** 资源整组空闲且路径已规范化时竞争者可取得全部；合法释放后另一方能进展。

**负向对照：** 去原子事务、用字符串路径当identity、每次争抢重置ready age或让writer绕freeze，各对应反例必须失败。

**实现依赖：** P必须OS进程barrier；不同root只证明保证范围，不声称其会相互排斥。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G25.atomic | 两个竞争者反序申请同两个资源，容量1 | 至多一个整组成功，失败者无局部新增claim |
| G25.identity | 同repo/workspace经symlink、未存在路径最近实父目录、共享build目录别名 | 冲突资源归一化，最多一writer；不同root保证范围单列 |
| G25.freeze | verifier冻结snapshot时同源writer请求 | writer等待，验证期间源码零改动 |
| G25.slots | host/repo/reader/heavy容量N−1/N/N+1 | 事务计数不负不超，释放后竞争者进展 |
| G25.aging | 固定有界step，低优先任务持续ready，持续插入高优先任务 | 固定推导的选择上界内旧任务获选，阻塞时间不计ready age |
| G25.release | 已确认终止/未知终态/等待额度分别释放 | 只释放被事实允许的槽；unknown保留必要占用 |

**精确义务索引：** SCH-006:U, SCH-006:S, SCH-007:S, SCH-007:P, SCH-008:S, SCH-008:P, SCH-009:P, SCH-009:E, SCH-010:P, SCH-010:E, SCH-011:P, SCH-011:E, SCH-012:P, SCH-012:E, TK03:U, TK03:S, TK03:P, TK03:E, TK04:U, TK04:S, TK04:P, TK04:E, TK05:U, TK05:S, TK05:P, TK05:E, TK06:U, TK06:S, TK06:P, TK06:E, TK07:U, TK07:S, TK07:P, TK07:E, TK08:U, TK08:S, TK08:P, TK08:E

### G26 — 只读调查与持续工作区交付

义务数：13；当前 P0–P3 缺口：12。

**ID：** WFL-001, WFL-002, WFL-003, WFL-011, WFL-012, T43

**参考：** ADR005/008/014;S18/S19/S25

**生产接口检查位置：** `src/orchestration/service.ts`; `src/workspace/worktree.ts`

**夹具：** 真实Git脏树+未跟踪文件、0/1/2 reader、writer取消barrier

**领域步骤（按上面的层级规则执行）：** 记录主树index/refs/dirty/untracked摘要；inspect尝试write/bash越权；fix工作区创建失败与正常创建分别执行；writer写一半后取消；最后独立验证成功任务输出候选补丁。

**成功对照：** 正常inspect只读交付，fix在持续worktree经独立验收交付候选且主树不改。

**负向对照：** worktree失败回退cwd或把取消显示已回滚，主树及receipt断言必须失败。

**实现依赖：** 9.2 reader数量和scope规则按现有能力实现；不支持零reader验收时先补契约，不能空结果冒充调查。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G26.inspect | 只读调查分别需要0/1/2 reader且证据范围明确 | 按TaskSpec所需证据选择；不足不能以空结果成功 |
| G26.read-only | reader尝试write/edit/bash、越界路径、外部symlink | 权限拒绝且主树/外部临时哨兵不变 |
| G26.worktree | 脏主树含staged/unstaged/untracked，工作区创建成功或失败 | 成功保留用户主树，失败不回退主树执行 |
| G26.cancel | writer部分改动后取消，之后迟到成功 | 现场保留，取消不声称回滚或完成 |
| G26.receipt | 首次成功/失败后合格修复，最终当前snapshot通过required | 交付候选patch与回执；refs/remote不改，不自动push/merge |

**精确义务索引：** WFL-001:U, WFL-001:E, WFL-002:U, WFL-002:E, WFL-003:P, WFL-003:E, WFL-011:P, WFL-011:E, WFL-012:P, WFL-012:E, T43:U, T43:P, T43:E

### G27 — 真实测试计数与验收输入变更

义务数：15；当前 P0–P3 缺口：12。

**ID：** WFL-004, WFL-005, T44, T45, T46

**参考：** ADR005/008/014/019;S15

**生产接口检查位置：** `src/verification/runner.ts`; `src/verification/inputs.ts`

**夹具：** VerifyRunner真实node argv checker、绑定脚本/过滤器/环境

**领域步骤（按上面的层级规则执行）：** 可信检查分别输出0 tests/all skip/unknown/实际pass/fail；验证后改源码或复用旧日志；改变check脚本/filter/阈值/env，尝试继续直到用户明确批准当前输入版本。

**成功对照：** 当前输入摘要与可信脚本匹配，实际足量测试通过且进程终止，回执有效。

**负向对照：** 只检查exitCode0或复用旧snapshot check结果，必须失败。

**实现依赖：** 9.5基础已有；P层应从独立进程执行脚本并核对新连接回执，不能仅改字段。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G27.counts | exit0但0tests/allskip/unknown/计数冲突，对照真实pass/fail | 只有可信足量实际通过才pass；未知不猜测 |
| G27.inputs | 逐一改source/untracked/check脚本/filter/阈值/env | 旧receipt失效，验收标准变更需明确批准 |
| G27.literal-argv | 参数含空格、分号、$()、反引号的合成字面值 | 按argv传递，无shell执行或额外哨兵 |
| G27.during | 验证期间写入、timeout、输出截断、孙进程未停 | 不签发可复用通过回执；未知终止保留占用 |
| G27.approve | 原输入版本与批准摘要匹配/不匹配，批准后重跑 | 匹配才新版本，旧结果不沿用，预算历史不清 |

**精确义务索引：** WFL-004:U, WFL-004:P, WFL-004:E, WFL-005:U, WFL-005:P, WFL-005:E, T44:U, T44:P, T44:E, T45:U, T45:P, T45:E, T46:U, T46:P, T46:E

### G28 — 有界recipe、环境错误及required预留

义务数：37；当前 P0–P3 缺口：34。

**ID：** WFL-006, WFL-007, RTB-015, RTB-016, RTB-017, RTB-018, T72, T77, T79, T80, T82, T88

**参考：** ADR005/009/015/016/017;S21/S22/S23/S24/S25

**生产接口检查位置：** `src/orchestration/policy.ts`; `src/orchestration/service.ts`

**夹具：** 真实fix workflow、implementation/environment分类checker、selector副作用陷阱

**领域步骤（按上面的层级规则执行）：** direct保留required；环境基线失败不upgrade；有证据critic修订后尝试cascade并耗尽原step/semantic预算；将余额置于requiredReserve边界，观察可选critic跳过而required继续。

**成功对照：** direct保留required，预算足够的单次有证据质疑/升级按固定规则完成。

**负向对照：** 切recipe新建预算、direct删除reviewer或selector执行动作，真实动作日志和TaskSpec断言必须失败。

**实现依赖：** 11.2/11.3已有基础；负向selector在隔离fixture中执行，不修改生产默认代码。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G28.direct | direct完成固定workflow | required verifier/reviewer保持，不因便宜策略省略 |
| G28.classify | implementation质量失败，对照environment与unknown错误 | 仅符合升级条件的质量失败可cascade，环境先诊断 |
| G28.critique | 无发现/无证据意见/有证据可处理发现 | 前两者不虚构修复；后者最多一次有界修订 |
| G28.shared | critique后cascade，step16/第17次，语义/请求余额边界 | 共用原限额，升级/质疑各最多一次，不开嵌套循环 |
| G28.reserve | optional调用后会使requiredReserve不足，对照恰好足够 | 不足跳过可选；required不足明确park不降级 |
| G28.pure | selector尝试setTimeout/spawn/write | 隔离负向控制检出副作用，正常selector只返回决策 |

**精确义务索引：** RTB-015:U, RTB-015:S, RTB-015:E, RTB-016:U, RTB-016:S, RTB-016:E, RTB-017:U, RTB-017:S, RTB-017:E, RTB-018:U, RTB-018:S, RTB-018:E, WFL-006:U, WFL-006:S, WFL-006:E, WFL-007:U, WFL-007:S, WFL-007:E, T72:U, T72:P, T72:E, T77:U, T77:P, T77:E, T79:U, T79:P, T79:E, T80:U, T80:S, T80:E, T82:U, T82:S, T82:A, T82:P, T88:U, T88:S, T88:E

### G29 — 独立审查、purpose与精确复用

义务数：12；当前 P0–P3 缺口：3。

**ID：** WFL-008, WFL-009, WFL-010, T81, T86

**参考：** ADR005/014/017;S15/S25

**生产接口检查位置：** `src/verification/reuse.ts`; `src/verification/review.ts`; `src/orchestration/service.ts`

**夹具：** 实际reviewer artifact读取日志、源snapshot、完整独立acceptance receipt

**领域步骤（按上面的层级规则执行）：** 先获取同snapshot完整独立review；再次验收应精确复用且无新模型调用；每次只改变snapshot/policy/TaskSpec/purpose/risk/覆盖/独立性一项，再请求验收；记录实际读取的diff/check/failure范围。

**成功对照：** 完整独立review所有当前契约匹配，精确复用且保留原出处、无重复收费。

**负向对照：** 只按snapshot复用而忽略purpose/独立性，或一律不复用，分别使反例和零重复收费正例失败。

**实现依赖：** 9.6 精确审查复用已实现；完整 diagnostic 仅在独立且满足 acceptance 所有条件时可复用，purpose 名称本身既不授权也不永久阻止复用。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G29.reuse | 同snapshot/TaskSpec/政策/profile/model/runtime/输入集合且完整独立review | 可复用且零新模型请求，保留原proof/receipt出处 |
| G29.one-change | 逐一改snapshot/版本/风险/覆盖/模型/profile/runtime/输入 | 不复用旧证据；必须满足当前验收 |
| G29.diagnostic | diagnostic仅局部/不独立，对照独立且满足全部acceptance条件 | 前者不能替代required；后者可按完整条件精确复用 |
| G29.read | 仅读部分diff/check/failure；非法或跨job引用 | 完整性失败，未覆盖具体列出 |
| G29.risk | 模型声称低风险但TaskSpec为high/unknown | 风险不降级；writer自评不作独立审查 |

**精确义务索引：** WFL-008:U, WFL-008:E, WFL-009:U, WFL-009:E, WFL-010:U, WFL-010:E, T81:U, T81:S, T81:E, T86:U, T86:S, T86:E

### G30 — 证据登记、来源漂移与诚实发布报告

义务数：18；当前 P0–P3 缺口：12。

**ID：** VAL-001, VAL-002, VAL-004, VAL-006, VAL-008, VAL-012, VAL-013, VAL-018, VAL-019

**参考：** ADR004/012/019;S10/S15/S16/S17

**生产接口检查位置：** `src/contracts/test-plan.ts`; `scripts/test-report.ts`

**夹具：** plan/report命令的隔离fixture副本、v6校验摘要、合成结果记录

**领域步骤（按上面的层级规则执行）：** 准备完整合法小型计划和实际执行记录作为正例；逐项改Scenario WHEN/THEN、重复ID、test发现数、层级、断言、lock、binding、skip/失败/重跑；运行真实报告生成入口读取JSON/CSV/退出码。

**成功对照：** 实际发现与执行一致、逐ID断言及当前工件齐全的小型合成计划，报告可在其声明范围ready。

**负向对照：** 伪造多ID共享无关断言或删除missing层级；独立预期表必须发现报告误认证。

**实现依赖：** 13.1 发现与逐 ID 断言计数已实现；补完整变体、断言语义、observer 工件和来源摘要审查，不以总计数替代。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G30.discovery | 零发现、未执行、skip、timeout、清理失败 | 实际发现/执行/退出事实一致，不能标全通过 |
| G30.attribution | 多ID测试只对一个ID有断言，对照逐ID明确断言 | 无关ID保持missing；不能分摊总断言数 |
| G30.drift | 改WHEN/THEN、层级、test名、lock或工件hash | 旧映射/证据失效，保持完整源义务集合 |
| G30.history | 先fail再pass和先pass再fail的独立运行 | 保留失败历史，不能用重跑覆盖旧工件 |
| G30.scope | P1合格/P3缺gate、P4六项延期、T75离线规则 | 准确分范围；不得用关闭拒绝证据抵在线行为 |
| G30.live-report | 缺绑定、仅正常smoke、wrong binding结果 | pending或失败；不得把loopback或其他模型代替Q3 |

**精确义务索引：** VAL-001:U, VAL-001:V, VAL-002:U, VAL-002:V, VAL-004:U, VAL-004:V, VAL-006:U, VAL-006:V, VAL-008:U, VAL-008:V, VAL-012:U, VAL-012:V, VAL-013:U, VAL-013:V, VAL-018:U, VAL-018:V, VAL-019:U, VAL-019:V

### G31 — 验证器自身的负向控制与可重放序列

义务数：12；当前 P0–P3 缺口：12。

**ID：** VAL-014, VAL-016, VAL-017

**参考：** ADR010/012;S9/S15/S16

**生产接口检查位置：** `tests/recorded-test.ts`; `src/contracts/test-plan.ts`

**夹具：** 坏adapter、存活descendant、seed/barrier日志、决策真值表

**领域步骤（按上面的层级规则执行）：** 让fake报告cancelled/预算合法而真实receiver收到超额或descendant继续写；对各决策仅改变一个准入条件；预设seed运行事件序列，并将捕获失败轨迹交给全新进程重放。

**成功对照：** 固定seed的正确实现满足预算/owner/终态守恒；重放同序列结论一致。

**负向对照：** 运行已知坏fixture并期待测试工具非零退出；坏fixture被报绿即验证器失败。

**实现依赖：** 预设seed不能无限重跑到绿；测试故意的失败在子运行中记录为expected-negative，不覆盖产品实际failed记录。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G31.external-truth | mock称预算正常/已停但receiver超额/孙进程继续写 | 能力验收失败，外部事实优先 |
| G31.one-condition | 全合法正例后逐项只改epoch/notBefore/required/request dedup/writer证明 | 每个负例可检出，正常正例可进展 |
| G31.replay | seed17/41/101/2026各150步；捕获失败轨迹交新进程 | 同输入重放同结论，记录barrier/最小序列 |
| G31.missing-record | 删除seed/barrier/observer工件 | 验证不合格；不能随机重跑直到绿 |

**精确义务索引：** VAL-014:A, VAL-014:P, VAL-014:E, VAL-014:V, VAL-016:U, VAL-016:S, VAL-016:P, VAL-016:V, VAL-017:U, VAL-017:S, VAL-017:P, VAL-017:V

### G32 — Qwen Q3实际绑定、受控恢复与失败报告

义务数：8；当前 P0–P3 缺口：8。

**ID：** VAL-005, VAL-007

**参考：** ADR002/004/010/012;S5/S6/S9

**生产接口检查位置：** `index.ts`; `src/reliability/recovery.ts`

**夹具：** 显式验收profile、用户提供model/account/network引用、合成长任务

**领域步骤（按上面的层级规则执行）：** 先校验实际绑定及有限request ceiling；一次正常可用性检查；在显式测试transport注入一次429后交还真实Qwen服务完成原任务；另用可控坏profile令该绑定失败，分别保存真实service-origin与injected事实并生成报告。

**成功对照：** 有限预算下真实Qwen同session经历标明来源的一次注入限流并完整续跑成功。

**负向对照：** 把injected当service-origin、无故障smoke当恢复证据或错误绑定结果替换成loopback，报告必须拒绝。

**实现依赖：** L需用户明确provider/model与总请求上限，未提供则planned-needs-live-binding；A/E可先用loopback设计行为但不能获取L信用。不得制造真实配额耗尽。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G32.binding | provider/model/account/network/profile与有限request ceiling完整，对照缺一项 | 只完整且明确授权的L执行；缺项pending且零真实请求 |
| G32.recovery | 合成项目长输入、先工具写一次，transport注入一次429后回真实Qwen | 原session继续，副作用一次，完整终态与预算可核实 |
| G32.origins | 正常service-origin与injected响应分别记录 | 不混来源；模型身份有实际来源而非配置推测 |
| G32.failure | 坏profile/错绑定/注入不支持或真实终态失败 | 失败保留；正常smoke仅可用性，不能假认证恢复 |
| G32.ceiling | 达到总请求上限或用户stop后触发旧timer | 无后续真实请求，不制造真实配额耗尽 |

**精确义务索引：** VAL-005:A, VAL-005:E, VAL-005:L, VAL-005:V, VAL-007:A, VAL-007:E, VAL-007:L, VAL-007:V

### G33 — P4在线Advisor延期义务的未来设计

义务数：6；当前 P0–P3 缺口：0。

**ID：** T66, T68, T69

**参考：** ADR006/009/012/016;S10/S11/S13/S15

**生产接口检查位置：** `src/config.ts`; `src/orchestration/policy.ts`

**夹具：** 未来Advisor adapter与固定规则dispatcher；当前仅设计契约

**领域步骤（按上面的层级规则执行）：** 未来启用经批准的Advisor测试profile后：含SDK retry的两次尝试耗尽；shadow产生合法建议；Advisor故障但规则下一步合法，分别观测模型请求、决策选择与回退。

**成功对照：** 未来Advisor在两次限制内给合法建议，规则dispatcher仍独立准入；本阶段不执行。

**负向对照：** 隐藏第三次格式修复请求、shadow改生产选择、错误被标成功，未来验证必须失败。

**实现依赖：** P4未实现且本次不扩scope；保留全部6个缺失层级，deferred-P4仅是计划依赖状态，不代表passed。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G33.attempts | 未来Advisor坏JSON和SDK retry共耗两次后试第三次 | 所有尝试计入两次上限，无递归管理者 |
| G33.shadow | 未来shadow建议合法且看似更优 | 不改变生产选择，无执行效果不宣称收益 |
| G33.fallback | Advisor失败但规则仍有合法动作 | 保留Advisor失败并执行规则动作，不能伪造建议成功 |

**精确义务索引：** T66:U, T66:V, T68:U, T68:V, T69:U, T69:V

### G34 — 根契约变更的明确用户授权

义务数：3；当前 P0–P3 缺口：0。

**ID：** CFG-007

**参考：** ADR005/009/013/019;S5

**生产接口检查位置：** `src/config.ts`; `src/orchestration/service.ts`

**夹具：** 冻结 TaskSpec v1、proposal、receipt；用户审批命令及模型工具入口

**领域步骤（按上面的层级规则执行）：** 建立 v1 根契约和合格回执；分别调整验收、权限、预算；先普通 resume 再提交与差异摘要一致的用户批准；读取新版本与所有受影响提议/回执。

**成功对照：** 真实用户批准当前差异摘要后版本递增、旧验收失效，实际消费历史保留。

**负向对照：** 把普通 resume 或模型参数当用户批准，或批准后清 used/reserved，版本与守恒断言必须失败。

**实现依赖：** 现有 approve-checks/approve-bindings 只覆盖对应子范围；一般预算/权限批准若无产品入口，需补实现并保持相关 E 未执行，不能把局部批准冒充全根契约支持。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G34.approval | 分别验收/权限/预算差异，普通resume后再匹配用户批准 | resume不改根契约；批准才新授权/TaskSpec版本 |
| G34.wrong-proof | 旧hash/错job/旧epoch/模型伪造批准/重复批准 | 不产生额外版本或扩权 |
| G34.invalidation | v1已有proposal/receipt，批准v2后尝试复用 | 受影响证据失效，必须按新版本重新验收 |
| G34.conservation | 批准时已有used/reserved/unknown与失败历史 | 额度版本可合法变化但实际消费/未知占用不清零 |
| G34.race | 批准await与stop两种顺序；仅价格变化对照 | 旧控制不得恢复派发；非语义费用变化不伪造新授权 |

**精确义务索引：** CFG-007:U, CFG-007:S, CFG-007:E

### G35 — 主会话恢复与可选受管后端独立准入

义务数：2；当前 P0–P3 缺口：1。

**ID：** CFG-010

**参考：** ADR001/002/003;S1/S5

**生产接口检查位置：** `src/adapters/capabilities.ts`; `index.ts`

**夹具：** Pi + InteractiveAdapter 已认证；独立安装副本分别移除 pi-subagents/破坏 child reporter

**领域步骤（按上面的层级规则执行）：** 保持同一交互认证与配额配置；分别令受管后端不存在、reporter 未认证、完全可用；加载包并查询 doctor，执行主会话一次限流后续跑，再尝试受管 workflow。

**成功对照：** 交互认证合格但无child包时，实际Pi仍可完成主会话同路线恢复。

**负向对照：** 将可选 child import 提到包顶层或用 child 状态全局禁用恢复，合格 P1 正例必须失败。

**实现依赖：** U 检查独立准入输出；E 必须用真实隔离安装与 Pi 恢复路径，不能仅 mock import 抛错。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G35.missing-child | child未安装/导入失败/reporter未认证，交互认证合格 | P1正常续跑，workflow明确不可用 |
| G35.bad-interactive | child可用但InteractiveAdapter认证不合格 | 不能借child合格开放主会话恢复 |
| G35.healthy | 交互与child均合格、各自模式获准 | 对应两类能力正常可用 |
| G35.reload | 从缺child到恢复依赖，再disabled加载 | 能力准确更新，disabled零HTTP，不叠加旧控制器 |

**精确义务索引：** CFG-010:U, CFG-010:E

### G36 — 全部启动分母、分组留出和收益声明边界

义务数：10；当前 P0–P3 缺口：10。

**ID：** VAL-009, VAL-010, T73, T74, T75

**参考：** ADR006/012/016;S10/S15/S16/S17/S21/S24

**生产接口检查位置：** `src/evidence/evaluation.ts`

**夹具：** 固定 10 次启动记录、issue/group/snapshot 元数据、direct/策略对照与未执行 shadow 记录

**领域步骤（按上面的层级规则执行）：** 固定 10 次启动：4 passed、2 failed、1 infra_failed、1 parked、1 censored、1 cancelled；独立计算分母与费用已知/未知数；加入同 issue 近重复开发/留出样本和只建议未执行的 shadow；调用实际评测报告入口。

**成功对照：** 干净分组且所有启动/成本状态齐全的固定样本，报告准确显示4/10及未知成本，不扩大收益结论。

**负向对照：** 过滤 infra 或用 shadow 分数替代实际结果、清除近重复组关系，独立固定算术和声明等级断言必须失败。

**实现依赖：** U/V 为离线报告规则，T75 在此不延期；11.6 实际效用试验需另绑定模型与预算，不能以这些合成数字声称收益。

| 检查 ID | 输入变化 | 独立预期 |
|---|---|---|
| G36.denominator | 10启动=4pass+2fail+1infra+1parked+1censored+1cancelled | 全部保留，完整成功4/10；状态单列 |
| G36.cost | 已知费用[1,2,3]另两个unknown，不含成功筛选 | 已知总额6且unknown=2，不写成总成本6或unknown0 |
| G36.holdout | 同issue不同文件/近重复snapshot跨开发留出，对照组完全隔离 | 前者污染不得声称留出收益；后者保留分组来源 |
| G36.utility-level | L1选择指标、未执行shadow、真实固定对照分别输入 | 只有实际下游后果才支持对应L2/L3结论，未知局限明示 |

**精确义务索引：** VAL-009:U, VAL-009:V, VAL-010:U, VAL-010:V, T73:U, T73:V, T74:U, T74:V, T75:U, T75:V

