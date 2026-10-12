# 当前现代 Runtime 的加载观测接线

2026-10-09 root，T011 后续生产子包。前一包的 session resourceSnapshot 是自有工厂返回字段，官方 runtime 不必保留此扩展字段；现有 official-file-runtime facade 也未暴露它。不能把存在工厂方法当作 Rotom 入口可查询。本包仅在既有自有 facade 接线，不新增持久文件、诊断 RPC、账号查询或宿主修改。

## 当前实例与生命周期

createOfficialFileRuntime 的已有 active 记录增添该次成功创建的 result.session 和 result.resourceSnapshot（函数只在仓库返回值中取得，不读 SDK 私有字段）。创建调用用自己的 current 引用；函数仅登记在该引用上，不给后来创建的 active 赋值。此前 root 已冻结的 createSession retire、admission drain、native session replacement/dispose 顺序不修改，不添加队列、锁、恢复、模型调用或自动重试。

返回的自有 facade 新增 async resourceSnapshot()，不改写 native。调用前必须尚未 disposed、没有 busy transition、active 已完成且 snapshot 函数存在，并且 native 的公开 session getter 与 active 捕获的 session 是同一对象。retired 用已有 PI_SESSION_RETIRED，transition 用 PI_SESSION_TRANSITION_BUSY，缺完成记录用 PI_SESSION_NOT_READY，错误退出码4。诊断不接收 profile/身份/path 参数。

取得 current 引用再 await 该次工厂的 snapshot；无论成功/失败，返回前再次同步核 disposed、busy、active===current 和 native.session===current.session。不满足则 PI_SESSION_RESOURCE_STALE/4，旧结果不得发布；满足时保留原 snapshot 固定错误与不可变结果。并发 snapshot 可独立执行；不形成第二 session owner。先前已返回的快照仍只是当时端点的记录，没有可持续权限/有效性，不自动升级为 live doctor、permit 或 SourceHold。

与 newSession/switchSession/fork/importFromJsonl/beforeInvalidate/dispose 共用原生命周期；正在切换、失败退役、关闭和 awaiting 中切走时不能重新暴露旧 session 的证据。只使用 native 公开 session getter和既有公开 replacement 回调，不依赖 upstream 保存 custom fields。

## 写范围和验收

前一生产子包写入稳定并验收后才开始。唯一执行者可写 agents/pi/runtime/official-file-runtime.ts 与 agents/pi/runtime/tests/official-session.test.ts 的真实组合测试；不修改前一包其余3文件、SDK/runtime prototypes/legacy/native/lock/catalog/OMP，也不写 state/tasks。先新即时前像/有效RED，固定 default fake SDK runner 只运行 official-session.test.ts；namespace不足可同边界 require_escalated，不是第三方真实 smoke。

覆盖真实自有 facade首次四身份和guard观测、配置检查/漂移、不复制SDK任意custom字段；新session/切换/fork/import四种transition阻断及下一代可查询；beforeInvalidate先退役、失败无旧结果、dispose立即关闭；pending snapshot在切换/关闭后成功或reject都不发布旧值；native公开session引用变了但缺回调时也拒绝。记录该接口没有额外创建/加载/session/model调用，且主模型查找仅原 snapshot 验证，不调用模型服务或刷新认证。复用真实生产接口，SDK/监督者均为合成替身，断网/临时HOME/原进程守卫保持。

超出写范围、需要扩大生命周期/锁/恢复协议或同一失败两种有效修复仍未解决升级root。完成STOP稳定diff/pins/logs，最终独立review后root验收。正式8/100、AUTO OFF；现代实际SDK及持久doctor消费仍另验。

2026-10-09 root验收补充：前一四文件producer绿149/149且独立复核无P1/P2。观测层行数/UTF8已有负例；session外层八字段增加的字节上限尚缺近边界行为证据。本包拥有同一测试文件，额外补一个有效场景：实际观测本身小于等于65536 UTF8字节，但加上session envelope后超限；真实新接口必须固定拒绝且不输出部分记录。仅新增意义测试，不改变已验收的producer代码。
