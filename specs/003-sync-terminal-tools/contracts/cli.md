# CLI Contract: `termcfg`

本文件约定首版用户接口。命令名称和选项在实现前固定；目标标识来自目录清单，用户输入不能作为任意文件路径使用。`./termcfg` 使用仓库 `.venv`，不依赖旧 `starter` 工作目录。

## 通用参数与选择

| 参数 | 语义 |
| --- | --- |
| `--machine ID` | 选择私人机器配置；省略时使用默认机器。不存在或未知字段返回 2。 |
| `--component ID` | 可重复；`ID` 仅可为 `zsh`、`tmux`、`mihomo`。省略时使用机器配置已启用的组件。 |
| `--json` | 结构化输出；仅包含脱敏事实、路径、摘要、原因码和进度，不含文件正文或私人值。 |
| `--home PATH` | 仅 `plan`、`doctor`、`status` 的隔离诊断参数；实际同步须在机器配置中声明目标 HOME，避免误写。 |
| `--timeout SECONDS` | 仅 `lock`、`sync` 和有等待的 `service` 操作可用；覆盖该命令总时限，范围 10–3600 秒，不取消连接/空闲超时与定期进度。 |

机器配置由 `init-local` 在私人 XDG 配置目录创建，默认 0600。交互式初始化只出现一次组件多选：显示 `zsh/tmux/mihomo` 与检测结果，默认预选检测到必需本地程序的 zsh/tmux，mihomo 默认不选；用户可更改，保存前显示最终选择。已有机器文件仅可用 `init-local --edit` 修改组件选择：先展示旧值与新值，交互默认保留旧值，确认后原子替换私人文件，不改 HOME 目标或服务。非 TTY 初始化/编辑必须显式给出至少一个 `--component`；清空选择须显式 `--none`，不得默选。`--machine` 不读取 `agentcfg` profile。所有命令先校验 ID、目录清单与机器配置；未知字段失败。机器选择为空时，`plan` 和 `doctor` 显示所有组件的可选性，`apply` 报参数错误并给出 `./termcfg init-local --edit`。

`init-local` 写入（含 `--edit`）、`sync`、`apply`、执行型 `rollback` 及 `service start/stop/reload/restart` 均先取得同一机器的非阻塞独占活动锁，持有至提交或记录待恢复状态。占用时在写入前返回 4，显示 `machine_id`、当前操作可安全识别的信息和重试命令；不依据 PID 强制解锁。`plan`、`doctor`、`status` 和 `rollback --plan-only` 保持只读，必要时报告活动操作而不等待锁。

共享依赖锁另有仓库级读写锁，与机器锁分处私人 XDG 状态根的 `leases/repos/` 和 `leases/machines/`，路径永不重合。维护者 `lock` 更新前持独占锁并复核旧锁身份；执行型 `apply` 先取机器锁并重算预览，用户确认后才取仓库共享锁，再复核锁、来源、目标和状态身份并写入。`sync` 也按“机器锁 → 仓库共享锁”顺序复核所用完整锁快照；提交依赖该快照的本机状态前不得放开仓库共享锁，下载期间可放开，但提交前须重新取得并复核。锁被占用或快照失效返回 4，指出当前组件、阶段和可重试命令。只读命令不为此创建锁文件。

## 命令

| 命令 | 输入/输出与副作用 |
| --- | --- |
| `components` | 列出组件、来源身份、平台支持范围；只读、离线。 |
| `init-local [--component ID...] [--edit] [--none]` | 一次组件多选建立私人机器选择；显示默认与最终选择及私人路径，已有文件只允许 `--edit` 修改组件选择并显示旧→新值。非 TTY 必须显式给出组件或 `--none`。不会采集订阅或 secret，也不改 HOME 目标。 |
| `doctor [--component ID...] [--strict]` | 只读检查 OS/架构、必需与可选程序、来源/锁、HOME/父目录、目标文件类型/属主/权限及服务可观测性；每组件显示 `ready/blocked/degraded/unverified` 和下一条建议命令，最后显示整体结论。默认完整列出所有结果并返回 0；`--strict` 在有必需阻断项时按对应错误类型返回非零。 |
| `plan [--component ID...]` | 只读逐目标预览 `create`、`replace`、`unchanged`、`adopt-required`、`conflict`、`blocked`，显示旧目标备份安排、来源身份、影响提示和 `plan_id`。`plan_id` 由选择、来源、锁、状态及目标身份生成；不包含正文。 |
| `lock --component ID --version VERSION [--timeout SECONDS]` | 维护者显式联网更新仓库共享锁；固定版本/提交、资产名、URL、长度、SHA-256 与入口/运行资源。旧锁身份在提交前变化时返回 4，不覆盖另一维护者的更新。缺锁时说明它会修改 `locks/termcfg/`；不接受 latest，不安装包、不修改 HOME 或启动服务。普通使用优先消费仓库已提交的锁。 |
| `sync --component ID [--timeout SECONDS]` | 对 `mihomo` 安装锁定 core，对 `zsh/tmux` 安装声明的锁定可选插件；只消费现有锁，不更新锁。下载到私人暂存并校验完整资产、目录形状、属主、权限和入口后激活。版本化包目录 0700，清单声明的可执行入口 0700，归档及非执行资源 0600；无锁、校验不符或网络失败均不修改受管 HOME 配置目标。 |
| `apply [--component ID...] [--plan-id ID] [--adopt-target ID...] [--confirm-zshenv ID]` | 离线重新生成并核对预览，再执行备份与复制覆盖。交互 TTY 中一次展示完整预览、需接管的目标和备份位置；一次明确确认涵盖所列目标的接管与本次执行，自定义非秘密 `.zshenv` 另作一次专门确认，不要求复制 ID。非 TTY 必须先 `plan` 并提供 `--plan-id`，逐个用 `--adopt-target` 明确接管目标。 |
| `status [--component ID...]` | 只读报告来源、文件、备份/恢复、`pending_core_effect` 与 `pending_config_effect` 两种待生效原因及服务状态；未知事实输出 `unverified`，不得根据文件一致推断服务生效。 |
| `rollback --component ID --plan-only` | 只读生成该组件当前回滚目标、备份身份、冲突和专用 `plan_id`；不执行恢复。 |
| `rollback --component ID [--plan-id ID]` | 每次仅恢复一个组件最近一次成功配置变更。交互 TTY 内展示回滚预览并一次确认；非 TTY 必须先用 `--plan-only` 取得匹配 `plan_id`。冲突时保留目标和备份。 |
| `service status\|start\|stop\|reload\|restart [--timeout SECONDS]` | 仅操作 mihomo；`status` 只读，其他动词为独立显式副作用。已有匹配租约且健康的运行实例再次 `start` 幂等返回，不重复启动；外部/身份不明进程或端口占用时不启动第二实例，返回冲突与占用信息。`stop/reload/restart` 必须核验租约和进程身份。 |

普通用户使用仓库已提交的锁：需要运行包时执行 `sync`，随后交互式 `apply` 可直接预览并确认。只有维护者需要更新共享版本时才运行 `lock`，审阅锁变化后再 `sync`。`apply` 不调用二者；缺少已锁定且校验通过的 core 运行包时报告所需 `sync --component mihomo`，不使用 PATH 中的 core 或 latest 下载。core 安装在版本化私人包路径，不作为配置覆盖或 rollback 目标。`apply` 不启动或重载 mihomo，也不关闭或重载现有 zsh/tmux 会话。zinit、TPM 和其他插件只能由 `sync --component zsh|tmux` 显式准备；缺失时配置安全降级。

## 确认和接管

- `plan_id` 仅识别一份事实快照，不能代替首次接管、`.zshenv` 覆盖或秘密准入确认。执行前重新读取并比较来源、锁、状态、目标类型/身份/摘要；任何差异要求重新 `plan`。
- `--adopt-target` 只接受预览中 `adopt-required` 的 ID。旧 `starter` 链接、已有普通文件，即使内容相同，也需要此确认。旧链接先备份链接本身。
- 旧 `.zshenv` 有自定义非秘密内容时，CLI 脱敏说明哪些目标会整文件替换；交互 TTY 对该文件另作一次确认，拒绝或缺少确认将整项 `zsh` 组件停在写入前。疑似秘密或无法判定的旧目标直接 `blocked`；上述确认不能绕过。
- 无 TTY 时所有必要确认均使用明确参数绑定当前 `plan_id`，禁止默认 yes。所有目标写入前，所选组件整体完成准入、备份和备份校验。

## 输出与退出码

`apply/rollback` 阶段进度至少为 `validate`、`backup`、`write`、`verify`、`commit`；`lock/sync` 至少为 `resolve/download/verify/activate`，`service` 至少为 `check/start-or-signal/health`。每阶段带组件、目标 ID 或包 ID、计数、经过时间与结果；长操作每 2 秒至少一次进度或心跳，已知总量显示字节/项数，未知总量显示阶段与经过时间。默认联网连接超时 10 秒、读取空闲超时 30 秒、命令总时限 300 秒；服务 start/restart 总时限 30 秒，stop/reload 为 15 秒；`--timeout` 可覆盖总时限。超时或 SIGINT 后保留已验证的包/事务状态并报告是否修改配置、包或服务、失败位置和可直接执行的重试/恢复命令，不留下无标识半成品。失败输出命令、组件、目标 ID/安全路径、原因码、建议下一步及可引用的事务 ID。路径含可疑私人信息时脱敏；不打印订阅 URL、密钥、目标正文、有效代理配置、API 响应正文或子进程原始 stderr。终端进度写 stderr，最终摘要写 stdout；`--json` 的 stdout 是单个最终 JSON 对象，含 `overall_ready`、逐组件 `ready`、原因码和 `next_command`，stderr 的进度不混入该对象。

| 码 | 含义与示例 |
| --- | --- |
| 0 | 命令成功；`doctor/status/plan` 可以含漂移、降级或待登录/待生效提示，具体状态在输出中。 |
| 2 | 参数、机器配置、清单或锁格式错误；plan_id 不匹配。 |
| 3 | 显式服务操作缺少必需私人凭据；文件预览和非代理组件不因此失效。 |
| 4 | 所有权冲突、目标漂移、同机器活动操作或实例、仓库共享锁并发冲突或快照过期、未确认接管或待恢复事务。 |
| 5 | 必需环境、依赖包、来源校验、联网/服务等待超时或原生服务健康检查失败。 |
| 6 | 文件系统或内部操作失败，或收到 SIGINT 后完成受控中断；可能留下可诊断的 `recovery_pending`。 |

`doctor` 默认完整列出逐组件阻断并返回 0，醒目显示整体 `ready/blocked`；`doctor --strict` 有必需阻断时按 2/4/5 等对应原因返回非零，私人凭据仅影响显式服务操作时使用 3。`apply` 对所选组件的阻断返回相应非零码。多组件执行逐项报告，最终退出码非零若任一选中组件失败，不把已成功组件写成失败或把失败组件写成整体成功。
