# 自有账户账本的独立进程证据

本层运行仓库自有 Python worker，不加载 Pi/Codex/模型 SDK、候选包或真实账号，不发送请求，不部署。默认 pytest 只测试父检查器的假进程与固定协议；独立 OS 入口必须显式选择。目标是为账户锁、持久墓碑与崩溃窗口补独立进程证据，不重复已通过的线程用例，也不声称断电恢复或完整产品验收。

worker 在固定 bwrap 中断网，只有探针创建的私有 work/account 目录可写。Python、所需自有 Python 源码及 schema 副本、Python 依赖和系统库只读；空环境只补临时 HOME/XDG/TMPDIR，RegisteredRoots始终显式指向该次临时account，不查询真实 passwd。冻结来源和系统程序身份，执行前后复核；stdout只允许闭合有界JSON，stderr丢弃，仅保留字节数。不挂载真实HOME、配置、凭据、会话或业务项目。

固定六场景，每个独立目录，最多两个并发自有 worker：

1. 双进程已各自构造门面后，同时claim同一synthetic operation。恰好一个取得claim返回并写一次fake-dispatch哨兵，另一个明确冲突；非阻塞账户锁的`REVIEW_ACCOUNT_BUSY`与持久墓碑的`REVIEW_ATTEMPT_ALREADY_CLAIMED`分别记录，均不得dispatch。随后独立reopen必须得到后者，累计账本保留同一attempt，不把fake-dispatch当真实模型调用。
2. updating哨兵持久后、原ledger写前，用自有写入函数故障切点 `os._exit`。重新构造必须待恢复，旧row未claimed，不补发。
3. claim的原ledger替换/fsync后、ready前退出。claimed墓碑持久、updating保留，构造拒绝，fake-dispatch为零。
4. 最终ready替换前退出。与上一场景分别记录切点，claimed墓碑保留，构造拒绝，无回滚或清零。
5. 最终ready替换/fsync后、方法返回前退出。构造只能观察持久claimed墓碑；重复claim明确冲突，不能补写fake-dispatch。
6. 一个进程登记synthetic unknown send，重开保留calls/reservation；随后仅在synthetic状态机中登记有效deny，另一个新进程对同intent操作明确拒绝。合成发送事实与实际HTTP/模型调用数分别记录，实际始终0。

仅测试 worker 对自有 Tree.replace 加固定故障切点，不改上游、stdlib、vendor或缓存。故障切点不接收任意代码/方法名/文件路径；父进程只传六个固定scenario与自建临时根，worker身份和参数都冻结。真实 `os._exit` 是进程突然退出证据，不等于电源断电、内核崩溃、SIGKILL/PID重用或namespace全域终止证明。

父层须保留失败原始工件，目录不可覆盖/重放；bounded watchdog回收自有进程组，退出未知时不删除状态。运行前完成默认fake测试和稳定独立审查。

当前证据已完成：run04目录`/tmp/agentcfg-reviewer-account-os-2ob_ent1`的父检查器和worker均exit0，六场景observed，stdout72字节、stderr0字节。并发一胜一冲突与fake-dispatch=1分别由原始JSON核对；四个cut=71..74、墓碑/ready/updating/recovery状态、unknown预留320及后续独立deny-lock全部核对。默认父协议63项通过；独立静态及原始工件审查未见该组件剩余P1/P2。私有归档在`.cache/pi-two-profiles/run-20261004/risk-reviewer-account-os-run04`，包含当时19模块闭包、131纯依赖、系统程序pins及原始工件。后续RegisteredRoots授权文件白名单接线属于新的源码版本，不能把历史OS来源当新版本重跑证据。

run01与run02在进入场景前因bwrap固定`PWD=/work`未列入精确ENV而退出；保留failed工件并根据固定形状诊断修复。run03的worker虽六场景完成，父检查器因错误预留期望120拒绝，仍保存为failed，未重新解释成通过。原账本按输入/缓存档最高价计算`100×3+10×2=320`正确；修复父oracle和fake工件，并增加实际自有临时Ledger.reserve独立算例。run04还逐一等待两个控制器构造完成，再共同go执行并发claim，避免把构造的非阻塞锁争用混作claim结果。

这只接受为schema1/no-claims自有OS组件证据，actual HTTP/模型调用均0，未加载SDK或真实账号。scope termination仍`not-independently-observed`，不释放未知请求预留；schema2共存OS、断电恢复、完整产品factory/审批来源/真实质量均未由本层证明。
