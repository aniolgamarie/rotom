# 同步、备份与服务状态契约

本契约约束 `plan`、`apply`、`rollback` 和显式 mihomo 服务操作。私有状态路径仅由当前用户访问；以下字段为语义模型，具体落盘格式由实现确定，但未知字段必须拒绝。

## 输入和信任边界

1. 仓库目录清单只声明 `zsh`、`tmux`、`mihomo` 的公开源、目标 ID、相对 HOME 路径、mode、来源摘要与锁定资产。一个目标只能有一个组件所有者。
2. 机器选择存于 0600 私人文件；来源路径和目标路径都须限制在各自根内。`HOME` 的父目录安全性、属主和路径分量在预览及写前检查；普通目标不跟随 symlink，旧 symlink 只能显式接管。
3. shell 目标准入采用**已知非秘密公开格式**和保守检查；未知自定义内容无法证明安全时拒绝普通备份和覆盖，并提示用户先迁走私人值。不得声称通用正则能识别所有秘密。旧目标须先通过非秘密准入，才计算或记录普通同步所需内容摘要；拒绝时只输出类型/原因码，不输出摘要。代理目标不得是含订阅、凭据、有效配置或运行数据的文件。
4. mihomo 私人订阅、secret、有效配置、路由草稿/发布状态、日志和统计在单独私人目录，由 mgr 管理。普通目录清单、预览、备份、journal、进度和错误中只出现非秘密状态码和公开基础配置摘要。
5. 机器级 `OperationLease` 位于固定私人 XDG 状态根的 `termcfg/leases/machines/<machine_id>.lock`，使用当前用户所有、单硬链接的 0600 普通锁文件及逐级 0700 父目录；no-follow 打开后以非阻塞内核独占锁保护 `init-local` 新建或编辑、`apply`、执行型 `rollback`、`sync` 和会改变状态的 `service` 操作。读取可变状态前取得，提交或留下恢复记录后释放；占用返回 4，不终止其他进程。PID 仅用于诊断，不能凭陈旧 PID 擅自解除锁。
6. core/插件的版本化运行包不含秘密，目录及暂存目录为当前用户所有的 0700；归档、元数据与非执行资源为 0600，清单声明的可执行入口为 0700 普通文件。激活前后核验属主、mode、摘要、链接边界与目录形状；不把这些执行位套用到私人配置文件。
7. 仓库级 `RepositoryLease` 位于 `termcfg/leases/repos/<仓库规范路径摘要>.lock`，与 `machines/` 目录不相交，使用 0600 单硬链接普通锁文件、逐级 0700 父目录及 no-follow 打开。维护者 `lock` 先读取旧锁身份，联网准备后取得非阻塞独占锁并比较旧身份，再原子替换；冲突返回 4。`sync/apply` 在机器锁内取得仓库共享锁读取或复核完整锁快照，提交依赖该快照的包选择、待生效状态或 HOME 配置时仍持仓库共享锁；统一先取机器锁、再取仓库共享锁，`lock` 只取仓库锁。只读预览不创建锁文件；过期快照返回 4，不能静默使用新锁或提交旧锁选择。

## `plan` 快照

每个目标返回：组件/目标 ID、安全路径、来源身份、旧目标类型与属主、已通过非秘密准入的目标摘要/身份、所有权状态、拟执行操作、是否备份、阻断/确认原因码。`plan_id` 覆盖这些事实和机器选择；不包含内容正文，不能当长期有效授权。对不可安全判定或读取的目标仅报告 `blocked`，不计算或输出内容摘要。未选组件不列为写入候选。版本化 core/插件包单列依赖状态，不列入配置回滚目标。

`apply` 重新检查快照。若目标在预览后从普通文件变为链接、目录、硬链接、不同 inode 或内容漂移，整个相关组件在第一笔写入前停止。确认只适用于当前 `plan_id` 中的明确目标。源身份、锁身份或本机平台变化同样令预览失效。

## `apply` 顺序

```text
acquire machine OperationLease; rebuild preview and validate all selected targets
  → show preview and collect required confirmations
  → acquire repository shared lease; revalidate lock, source, targets and state
  → create and fsync old-target backups for every selected component
  → verify backup copies and journal
  → write each new target via same-directory temporary file + atomic replace
  → verify installed bytes/mode
  → under repository shared lease, revalidate lock identity and commit each component state and previous-config-version pointer
  → release repository shared lease, then machine lease after commit or durable recovery_pending
```

首次创建的目标记录“原不存在”；旧普通文件保存内容和必要 mode/owner 元数据；旧链接保存链接本身。备份保存在私人 0700 目录，文件 0600。本次调用所有选中组件的配置备份完成并校验后才能写任何目标；备份空间不足或任一失败时本次调用目标变更数为 0。成功且有变更才轮换上一版指针并安全清理更旧的成功配置备份集合；重复同步无新备份。`fsync`、同目录临时文件和状态提交遵守 POSIX 可恢复性，不能宣称跨多文件绝对原子。

写入开始后保留 journal，逐目标记录 `pending`、`written`、`verified`。中断后 `status` 显示实际已完成与未完成目标，下一次 `apply` 先处理 `recovery_pending`，不自动覆盖用户在中断后改过的目标。每个目标恢复前与 journal 的预期写后身份比较；不匹配即冲突。多组件执行时各组件有独立事务，最终汇总实际结果。

## 漂移与回滚

已有受管配置目标更新前比较上次 `after` 与当前类型、身份、内容摘要。内容变更、链接替换或权限/所有权异常均为漂移或冲突，保留目标与上一版备份。`rollback` 也做相同检查，不能用 `--force` 绕过。成功回滚将旧配置内容与必要权限恢复；原本不存在的目标只有仍受本管理器所有且与其写后状态一致才移除。上一版配置备份在成功恢复后消费；失败仍保留。版本化 core/插件软件包不随配置 rollback 降级。恢复过程自身写入中断必须留下 journal 和可操作建议。

首次接管已有文件的可恢复状态指向接管前原件；旧 `starter` 的备份/管理片段只是待调查来源，不作为 termcfg 所有权。`.zshenv` 的整文件覆盖与 zsh 其他目标同属一次组件事务；有自定义非秘密内容时单独确认，拒绝则 zsh 目标全部不变；疑似私人值时不能入普通备份。

## mihomo 生效与进程身份

文件状态和服务状态分开记录：`files_synced`、`pending_config_effect`、`pending_core_effect`、`running/stopped/unknown/external`、`effective/unverified`。US1 即建立持久的非秘密 `EffectState`：`sync --component mihomo` 安装并选定新 core 版本后记录 `pending_core_effect`；`apply` 仅在公开配置成功提交且确有变更后记录 `pending_config_effect`；失败或无变化不新增原因。两者都不向运行中服务发 API 请求或信号。US1 的最终摘要提示待生效，并只给出当前可执行的 `doctor/plan` 诊断命令，说明服务操作尚未提供；US3 接入服务命令后才建议显式重载/重启，并由 `status` 分别报告原因，在服务核验证据充分时清除。`service start` 或确需新有效配置的 `reload/restart` 才读取私人数据，用结构化 YAML 序列化器生成并校验仅供运行的私人有效配置，文件为当前用户所有的 0600 普通文件，父目录 0700；`service status/stop` 不读取订阅或重建 YAML。私人有效配置不进入普通渲染、摘要、状态、日志或备份。`reload/restart` 可在同一受限边界使用控制 API 或受管进程；仅核验已加载配置不能清除 core 待生效，须另核验进程可执行版本。启动/重载失败保留准确的待生效状态，不能仅因 API 返回成功就声称新配置已加载。

停止或重启前须匹配 UID、PID、进程开始身份、可执行文件/锁身份和管理器租约；匹配不全时状态为 `unknown/external`，不发终止信号。`ServiceLease` 只保存非秘密公开基础配置摘要，绝不对含订阅/secret 的私人有效 YAML 计算或保存摘要。进程身份、健康与可安全观察的公开配置加载证据均匹配后才标记 `effective`；若无法证明有效配置已加载则标为 `unverified`，不得用私人有效配置摘要代替证据。同步和服务操作不隐式下载 DB、core 或插件。

## 验收不变量

- 没有所有权、确认、锁或安全备份的目标，没有写入路径。
- 私人值不进入公开来源、普通备份、预览、状态、错误、日志或测试快照。
- `apply` 不改变活动代理、shell 和 tmux 会话；显式 `service` 命令只管理自身拥有的进程。
- 任何部分失败都留下逐目标事实、可恢复备份和下一步；无证据的状态是 `unverified`。
