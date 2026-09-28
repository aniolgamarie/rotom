# termcfg 实现复核

日期：2026-09-28。范围：`src/termcfg/`、`terminals/`、`locks/termcfg/`、schema、CLI、文档及隔离测试。下表的“已核对”指代码和假数据隔离测试；真实 HOME、订阅、tmux server、mihomo core 运行另需独立授权的 smoke。

| 规格 | 复核证据 |
| --- | --- |
| FR-001 | `components/init-local` 独立选择 zsh/tmux/mihomo；公开 mgr、core 锁与服务命令存在。 |
| FR-002 | `preview.py` 逐目标 action、来源摘要和备份安排；`plan` 合并环境结论与冲突。 |
| FR-003 | `home_targets.py` 祖先、类型、属主和 final-dirfd 复核；`catalog.py` 来源校验；`environment.py` 必需程序/平台检查。 |
| FR-004 | `doctor` 的 required/optional/unverified 分栏；`apply` 在必要阻断时零 HOME 写入。 |
| FR-005 | `atomic_target_bytes` 复制公开字节；不会把仓库来源链接部署到 HOME。 |
| FR-006 | `transaction.py` 全调用备份优先、失败零覆盖；旧链接按链接身份保存；core 不进配置备份。 |
| FR-007 | 未受管既有目标标 `adopt-required`，交互一次确认或非 TTY 逐 ID 接管。 |
| FR-008 | 严格 `TargetRecord`、`TransactionJournal` 与私人备份引用不存正文。 |
| FR-009 | `unchanged` 路径无目标改写、无备份指针轮换；测试验证 inode。 |
| FR-010 | 基线/当前/期望三方比较与回滚预览拒绝漂移；来源及目标同变回归已覆盖。 |
| FR-011 | 组件级回滚恢复旧文件/链接及模式，原不存在则移除；保留 core 身份。 |
| FR-012 | `plan_id`、来源/锁快照及写前目标复核；救援恢复只依赖 journal/备份，即使当前公开来源或锁损坏仍可执行。 |
| FR-013 | stderr 阶段进度；失败 JSON 有组件、阶段和原因，逐文件故障另有 `target_id`，输出不含正文。 |
| FR-014 | `lock/sync/apply/service` 分离；两类待生效原因持久记录；文件同步无服务调用。 |
| FR-015 | zsh/tmux 来源移除启动时网络安装；插件仅显式 `sync`；会话未由配置同步操作。 |
| FR-016 | `terminals/SOURCES.md` 旧文件摘要、迁移理由、许可和原路径；运行时无 starter 路径依赖。 |
| FR-017 | catalog 检查目标 ID/路径重叠；未选与会话/私人哨兵测试。 |
| FR-018 | 秘密准入在旧目标摘要与普通备份前执行；疑似私人内容拒绝。 |
| FR-019 | `status` 按组件显示文件、依赖、备份/恢复、服务与两种待生效原因；未核验证据标 `unverified`。 |
| FR-020 | pytest autouse 临时 HOME/XDG、网络/真实子进程阻断；假 core/API/进程测试。 |
| FR-021 | 公开 base 与私人 YAML 分开；私人有效配置、日志、路由及统计不进入清单或状态。 |
| FR-022 | `.zshenv` 整文件目标，旧自定义非秘密内容需额外确认，拒绝后 zsh 零写。 |
| FR-023 | TTY 初始化一次多选、TTY apply 现场确认；非 TTY 预览 ID 绑定。 |
| FR-024 | 下载及服务等待有阶段/心跳和总时限；失败给阶段、保守副作用说明与下一条命令。真实网络停顿和真实核心耗时尚未测。 |
| FR-025 | `doctor --strict --json` 的整体/逐组件 ready 与非零退出；回滚专用只读 plan ID。 |
| FR-026 | 同机器所有状态写入受 OperationLease 保护；锁后再读机器文件核对，pending journal 阻止其它状态写入。 |
| FR-027 | 固定 core/插件包目录、归档、资源及入口权限/属主/摘要均在激活前后检查。 |
| FR-028 | 独立仓库共享/独占租约、旧锁身份复核；lock/lock、lock/sync、apply 确认窗口及共享锁竞争测试。 |

| 成功标准 | 隔离证据 |
| --- | --- |
| SC-001 | `plan` 列全部声明目标的 path/action/backup。 |
| SC-002 | 单组件同步及未选目标、私人/会话哨兵测试。 |
| SC-003 | 首次接管、重复调用、两次公开来源更新、回滚模式与漂移测试。 |
| SC-004 | 备份失败零覆盖、来源损坏定位到目标、doctor 必需阻断。 |
| SC-005 | apply/rollback/recover 中断与再次中断，status 展示逐目标 journal 阶段。 |
| SC-006 | `init-local → doctor → plan` 离线三命令路径。 |
| SC-007 | 默认 fixture 隔离 HOME/XDG/网络/真实进程；未做真实 smoke。 |
| SC-008 | sync/apply 保留 core/config 待生效原因且不调用服务。 |
| SC-009 | 自定义 `.zshenv` 拒绝零写、接管后回滚旧内容/权限。 |
| SC-010 | TTY apply 不抄 ID；非 TTY rollback 先只读取专用 ID。 |
| SC-011 | 假慢下载/健康等待有心跳，超时/SIGINT 路径有脱敏输出；真实网络未测。 |
| SC-012 | apply、rollback、sync、service 同机器竞争返回 4 并检查状态/目标未交错。 |
| SC-013 | 维护者 lock/lock、lock/sync、apply 预览确认窗口及共享仓库锁冲突；两类锁路径不别名。 |

复核修复：补了待恢复状态写入门槛、目标最终身份检查、提交后清理边界、服务启动全路径清理、已退出子进程的失效租约清理、完整可观察公开字段的生效核验、来源损坏时的救援恢复、恢复时的受信内容摘要核验，以及 `--json` 交互提示与失败上下文。功能边界和测试结果见[验收记录](termcfg-acceptance.md)。
