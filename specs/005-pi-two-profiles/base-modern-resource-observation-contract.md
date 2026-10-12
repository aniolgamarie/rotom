# 现代加载资源的内存观测接口

2026-10-09 root，T011 第二生产子包。依据已完成的 modern loaded producer 公共接口证据；历史 loaded-manifest 不适用于现代入口。先实现当前会话的内存观测，后续持久化与 doctor 消费单独设计，不能把静态安装 matched 当作实际加载。

## 接口和语义

createOfficialResources 返回的自有闭包对象增加 observeLoadedResources()，不向 SDK resourceLoader 增加非官方方法。每次调用先核 ready，再运行现有 validateLoaded：选定文件快照、空 discovery settings、四类 SDK 公共 getter 的完整路径集合/错误、固定 rules/append/system、inline factory 与 command guard 均已校验；不从 SDK 任意对象复制正文。使用选定且已验证资源投影成不可变、脱离 SDK 缓存的非秘密记录。

观测 schemaVersion=1，scope=in-memory-public-sdk-load，resourcesDigest=selection.digest；resources 仅 extensions/skills/prompts/themes 四类，每行只有 id/scope；inlineExtensions 只含 factory name；selectedRoles 只含 id/scope 且明示 selection-only（roles 没有对应 SDK 已加载 getter），不可把 roles 当作已加载。rules/append 如输出只用固定已验证状态，不含正文、路径或各文件内容摘要。完整结果不含绝对/相对路径、错误原文、凭据、SDK对象、函数或 handlers。总行数含 roles/inline 最多4096，JSON UTF8最多65536，超限固定 pi-resource-observation-invalid；失败不能输出部分记录。返回值深冻结，每次重新验证，不缓存匹配结果，也不声称以前发出的值具有权限或持续有效性。

reload 是单 flight：第二个并发 reload 在改变第一调用状态前以 pi-resource-reload-in-progress 拒绝，不排队/重试。首个开始即 ready=false，成功完成公共 SDK reload 和 validateLoaded 才 ready=true，任何失败保持不可观测；finally 清理进行中标记。首个进行中 getter/observe/extend 均不能获取有效加载证据。此处只是自有闭包状态，未新增文件锁/事务，也未清空 SDK 私有缓存。

createOfficialSessionFactory 返回值增加 async resourceSnapshot()。先要求 fixedInstalled 的 profile_id 与 fixedManifest.profile_id 相符且 lock_identity/slice_identity/runtime_identity 为规范64hex；这些取自已固定输入，不接受调用参数。缺失/错误用固定 pi-session-resource-identity 拒绝，仅限制新诊断接口，不将旧缺字段测试和调用宣称有完整身份。调用既有 configurationSnapshot() 完整重验 settings/model/tools/runtime，随后同步 observeLoadedResources，resourcesDigest 必须同一 selection.digest。输出 schemaVersion/profileId/lockIdentity/sliceIdentity/runtimeIdentity/configIdentity/resourcesDigest/observation 深冻结；无新模型调用、认证刷新、资源重载或 SDK 私有访问。只报告端点的当前加载集合及配置身份，不签发 permit、SourceHold、持久化新鲜度或沙箱资格。

## 实现和验证范围

单一执行者可写 agents/pi/runtime/official-resources.ts、official-session.ts 及各自 tests/official-resources.test.ts、tests/official-session.test.ts。不改 legacy loader、宿主/vendor、locks/声明、SDK、test harness、其他实例/OMP。保存四文件前像和有效 RED，默认固定脚本只运行这两个 fake SDK 测试模块：Node24.14.0 scripts/test-pi-mock.mjs <两个精确路径>，现有 bwrap 断网、临时 HOME、仓库只读、禁止模型/第三方子进程。沙箱 namespace 权限不足可用 require_escalated 执行同一默认 fake 命令，不是原生 smoke，不扩大边界。

测试实际生产接口：未 reload 零记录；四类/inline 选择和 roles 非加载区分；深冻结/脱离 SDK 引用/无路径正文；错误与同数量路径替换拒绝；资源/settings 漂移；reload 异步进行中、失败和明确成功恢复；并发第二 reload 拒绝且首个不被取消；条数/UTF8上限；session 四身份/当前配置绑定、缺失与跨 profile 拒绝、配置/runtime 漂移以及零新 SDK/session/model/认证执行。只补受影响的有效测试，不重跑旧原生或全量。

完成后稳定四文件 diff/pins、RED/GREEN 日志、状态四分类与观察到的执行模型。超出写范围、原公开 getter 无法支撑、需要新锁/恢复/调用策略或同一失败两种有效尝试仍未解时升级 root。T011 未整体完成，正式8/100、Pi AUTO OFF。OMP 已移交。
