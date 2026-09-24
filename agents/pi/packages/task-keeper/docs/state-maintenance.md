# 状态数据库升级与恢复

数据库 schema 3 在现有 records 中保存 usage 事实、任务关联与修订审计，并增加查询索引；配置 schemaVersion 为 7。已有 schema 1/2 不会在插件加载时自动升级，返回 `DATABASE_MIGRATION_REQUIRED`。维护命令只处理显式指定的 Task Keeper 状态目录，不读取或写入 Pi/Claude 配置。

先停止使用该状态目录的 Pi 控制器，再在包目录执行：

```sh
node --experimental-strip-types scripts/state-maintenance.ts upgrade /absolute/task-keeper/state
```

维护工具在 SQLite 写事务内核对 owner 的进程启动身份，无法证明已停止就拒绝。它建立持久维护标记，阻止已打开和新连接的正常状态写入及派发；随后建立带哈希的私有备份，在事务中升级，并逐表确认所有业务事实保持不变。intent、unknown reservation、预算、资源占用、回执和工作区引用不因升级清零。

每个状态目录通过私有 `.task-keeper-database.json` 绑定唯一数据库，`storage.path` 的文件名仍可配置；维护工具读取该绑定。旧目录只有一个主库时可采用其名称，多个主库会拒绝并保留原文件，要求先对账。更换文件名不能创建第二份预算账本。

若升级中断，目录中的 `<数据库文件名>.maintenance`（默认 `runtime.db.maintenance`）保留操作身份、切点、备份路径与摘要。以下命令不会自动运行：

```sh
node --experimental-strip-types scripts/state-maintenance.ts finish /absolute/task-keeper/state
node --experimental-strip-types scripts/state-maintenance.ts rollback /absolute/task-keeper/state
```

`finish` 只完成已经提交且业务摘要仍匹配的升级；`rollback` 只恢复该次受维护标记保护的原始数据库。备份损坏、来源不一致、业务事实有新增、维护进程仍存活或无法核实 owner 时保持阻塞。回退到 schema 1 后可重新执行升级，或使用能读取 schema 1 的旧版本；它不自动切换插件版本。

恢复保留原数据库副本，旧连接通过文件身份变化被拒绝写入。维护日志和备份不自动删除。任意较新 schema 仍拒绝打开，不能把它当成新任务。未知外部 writer 的资源和现场仍保留，数据库维护不声称终止了它，也不恢复/回滚工作树文件。

适用范围是注册的 schema 1/2→3 升级以及该次中断的恢复，不提供任意 SQL 执行或任意旧备份覆盖功能。无法读懂/验证的当前数据库保持拒绝，不以猜测性恢复清除更新的预算。

测试覆盖五个实际进程中断切点、备份篡改、活动 owner、维护期间写入、旧连接写入及越过维护机制的新事实；完整 TK-R2 验收以当前 source/plan 报告为准。

实际 Pi 生命周期测试另覆盖 upgrade/disable/restart/rollback × not-sent/terminal-confirmed/unknown 的 12 个基本组合。每次重新加载后用新 SQLite 连接核对业务摘要、intent/request 状态、累计 used/reserved、claims、工作区与私有策略/auth 字节；回退 schema 1 后当前插件明确拒绝打开，事实不被清空。此矩阵的通过不等于所有生命周期竞态已认证。
