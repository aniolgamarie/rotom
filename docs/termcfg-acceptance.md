# termcfg 隔离验收记录

日期：2026-09-28。环境：Linux x86_64、Python 3.12 仓库 `.venv`；pytest 的 autouse fixture 将 HOME、XDG、TMP、PATH 指到临时目录，阻断网络与真实子进程。core/API/进程与订阅均为虚构数据。

| 命令 | 实际结果 | 范围 |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q tests/test_termcfg_*.py` | **106 passed**，23.32 秒 | 初始化、来源/锁拒绝、预览/秘密准入、备份失败零覆盖、两次公开来源更新的备份轮换、漂移、回滚与重复中断恢复、来源/锁损坏时救援恢复、假 core/插件下载与权限、机器及仓库锁竞争、服务租约/私人配置、进度及状态诊断。 |
| `.venv/bin/python -m pytest -q` | **2349 passed, 2 skipped, 6 failed**，286.90 秒 | 6 个失败均位于既有 `tests/test_pi_recovery_protocol_surrogate.py`，本地 Unix socket `connect` 被默认沙箱拒绝 `EPERM`；其余全项目测试通过。 |
| `.venv/bin/python -m pytest -q tests/test_pi_recovery_protocol_surrogate.py`（仅此文件，测试权限升级） | **6 passed**，0.97 秒 | 只运行临时 Unix socket 和假 helper，确认上述失败由默认沙箱的 socket 权限造成；没有启动 DSH、Pi、OMP、zsh、tmux 或 mihomo 宿主。 |

## 已核对的交互与恢复事实

- `init-local` 的非 TTY 空选择失败；显式选中、编辑旧→新、显式清空及 TTY 一次多选测试通过。`components --json` 的 stdout 可解析为单个对象。
- `plan` ID 对同一快照稳定；疑似秘密 `.zshenv` 在正文摘要和普通备份前阻断；自定义非秘密 `.zshenv` 需要接管和专门确认。
- 多组件调用中后一个组件备份失败时，已准备的其他组件 HOME 目标没有被覆盖。首次接管备份旧文件；无变化再次 `apply` 不改写 inode、不轮换上一版指针；改动受管文件后拒绝更新。
- 原子替换后、journal 写后身份前的注入崩溃可恢复；回滚到原不存在文件和旧链接时同一崩溃点可恢复。恢复路径不会报告原事务成功。
- 同机器 `apply` 锁冲突在 HOME 写入前返回 4；预览等待确认时依赖锁身份变化，确认后写入前返回 4；假下载期间锁身份变化，`sync` 不选定旧版本。
- 假 core/插件包的锁定 SHA、长度、资源、目录和文件权限已校验。真实发布的 Linux x86_64 mihomo core 锁记录官方 v1.19.31 资产长度 22,821,836 字节及 SHA-256，生成锁时从官方发布 API 核对；没有执行真实下载/启动 smoke。
- `service status` 不读取私人配置；假 `start` 写 0600 有效 YAML，租约及状态不含 secret；健康失败后终止本次启动的假子进程并保留待生效原因；未知 PID 身份拒绝 stop。旧 mgr 的旧服务入口被拒绝，私人配置即使 umask 022 仍为 0600/0700。
- 交互式 `--json` 的提示写 stderr；失败 JSON 带命令、组件及可用时的事务 ID。状态发现受管文件漂移时整体标为 blocked。回滚/恢复与写入前复核先做秘密准入；最终替换前再检查目标身份。两个维护者并发建锁目录暴露的创建竞态已修复，旧快照更新者返回 4。
- 两次公开来源更新后，上一版配置备份只指向紧邻版本；提交后的备份清理故障不再使已提交事务进入恢复。状态写入在机器锁内再次核对机器选择，并在待恢复 journal 存在时阻止 sync、service 和 init-local 编辑。
- 假 core 自行退出或租约写入失败时，启动清理不遗留失效租约；代理公开配置只在 API 可观察字段全部一致时判为已生效。假慢下载/健康等待在 2 秒内有心跳，失败摘要标明阶段与保守副作用范围。
- `recover` 不依赖当前 catalog/lock 完整性；中断后公开来源及锁读取被注入失败时，`status` 仍报告 journal，`recover` 仍能恢复。journal 相对目标和私人备份引用经过语法与边界校验。
- 恢复时还会核对 journal 中受信目标的内容摘要：外部改动即使与原文件等长、再把 mtime 恢复到记录值，也返回 4 并保留现场和 journal。

## 关键隔离场景与实际测试

| 场景 | 运行的测试 | 结果 |
| --- | --- | --- |
| 离线初始化、doctor、plan、TTY apply 及非 TTY 回滚两步 | `test_termcfg_init_local.py`、`test_termcfg_status.py`、`test_termcfg_apply.py`、`test_termcfg_recovery.py` | 通过；交互提示未混入 JSON stdout。 |
| 多组件备份失败、三方漂移、上一版轮换、状态提交故障与重复恢复中断 | `test_termcfg_apply.py`、`test_termcfg_drift.py`、`test_termcfg_interrupt.py` | 通过；目标/备份哨兵和 journal 逐项核对。 |
| 同机器 apply/rollback/sync/service 争锁 | `test_termcfg_apply.py`、`test_termcfg_recovery.py`、`test_termcfg_service.py` | 通过；后到者返回 4，写前目标/状态未交错。 |
| lock/lock、下载期间 lock/sync、交互 apply 确认期间 lock、持共享锁的 apply/lock | `test_termcfg_mihomo_sync.py` | 通过；过期快照方返回 4，旧锁或 HOME/状态未基于过期快照提交。 |
| 包权限、慢下载、长度/摘要/超时、中断后原锁字节 | `test_termcfg_mihomo_sync.py`、`test_termcfg_catalog.py` | 通过；真实网络和真实 core 未执行。 |
| 服务身份、私人权限、start/stop/reload/restart、心跳、子进程自行退出及租约失败 | `test_termcfg_service.py`、`test_termcfg_security.py` | 通过；API/进程均为假对象，未向真实进程发信号。 |

## 尚需独立证据

真实 HOME、真实 mihomo core、真实订阅、tmux server 及 shell 启动未运行；这些只在用户单独授权的 smoke 中验证。当前隔离测试尚未覆盖所有网络中断时序、不同机器对共享仓库锁的全部竞争组合、真实控制 API 重载/健康证据以及 macOS 平台。它们不能从 106 个假数据测试推断为已验证。
