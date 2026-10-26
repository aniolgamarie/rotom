# 按工具执行停止、更新与恢复

状态：候选实现与分组验收已完成。基线 main `45953f0`，保留在分支 `feat/tool-maintenance-workflows-20261026`，尚未合入 main；合入须人工批准。本文说明候选接口，不能据此将日常入口切到候选工作树。

## 分阶段操作

DSH、Pi、OMP 共用明确选择后的流程：保存恢复清单 → 精确停止 → 关闭本次 stop fence → 独立预览并批准普通 setup → 逐项当前终端恢复。这不是一笔跨进程事务。停止批准不授予更新许可，恢复也不发送继续文本。

以下使用虚构机器、run 和 session；先用列表与原 TUI 核对，再替换占位值。run/batch 使用完整 32 位小写十六进制 ID，session 使用工具的完整 ID。示例选 Pi；DSH/OMP 使用对应公开 profile。尚未部署日常入口时在候选工作树使用 `./rotom`。

```sh
./rotom agent --machine workstation --profile pi-base instances list --agent pi --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance plan --run RUN_ID --session RUN_ID=SESSION_ID --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance stop --run RUN_ID --session RUN_ID=SESSION_ID --plan-id STOP_PLAN_ID --wait-seconds 30 --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance status --batch BATCH_ID --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance plan --batch BATCH_ID --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance execute --batch BATCH_ID --plan-id SETUP_PLAN_ID --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance restore --batch BATCH_ID --run RUN_ID
```

完整目标锁没有恢复准入时，plan/stop 在停止前拒绝，execute 在更新批准前再次检查；可改用独立 instances stop、普通 setup 和官方界面人工恢复。第一次 plan 的摘要只用于 stop；停止完成后的 `plan --batch` 返回最新 setup 摘要，只用于 execute。不要复用摘要或把 JSON 当许可。`--operation setup` 可省略；首次 plan 与 stop 的 `--run`、`--session` 映射必须一致。选择多个运行时重复 `--run` 和对应 `--session`，不重复同一 run；restore 每次只交接一项当前终端，不让多项争用 stdin。

自动交互要求 stdin/stdout/stderr 全部 TTY；根 `--interactive` 可明确请求交互，但不能绕过这一条件。TTY 可选择缺失的运行与会话，展示计划后分别批准 stop 和 setup。非 TTY 或根 `--no-input` 必须给足目标及当前 `--plan-id`，不读 stdin；缺参/批准返回 2，计划漂移返回 4。restore 的宿主仍需要自己的交互终端，`--no-input` 只约束 Rotom 的提问，不模拟宿主输入。计划只读，无网络和控制；execute 可通过原安装器联网/写配置，restore 可启动官方宿主。

## 精确停止与独立更新

三个工具的 Linux managed `stop_only` 均使用审阅后的快照、fence、CAS、一次请求、原 host pidfd 的 SIGTERM 和退出核验。不按 PID/进程名猜测，不强杀，不控制未选运行。等待默认 30 秒、范围 1–300 秒，整个集合共享绝对截止时间；超时或结果不确定保留批次和保护，返回 4，不重发。

Pi/OMP 的 stop endpoint 保存为既有 inbox 的 sidecar，绑定原 run/manager/host/deployment，不为兼容而改写旧 RunRecord；没有可信通道的旧运行仍需人工停止。OMP 的新 host 登记通过 `owner_pending` 与 Domain/owner 摘要协调，不能直接改 Registry 绕过 Domain。精确停止不声称已释放所有共享资源，也不改变 Domain 许可语义。

确认退出并关闭本次 stop fence 后，execute 重新取得普通 setup 的最新计划与独立批准，重走实例/HOME/包物理锁、owner 和共享资源完整门禁。并发新运行、未选共享引用或 unknown 均可阻止更新；不会扩大原停止集合。原维护结果和退出码保留，状态查询或恢复结果不能覆盖它。可能已执行的 unknown 不自动重试；只有可证实允许的新执行才能重新预览并批准，不从磁盘重建许可。

## 恢复和 writer 的真实边界

DSH 沿用已验收的原 Host 后端；Pi/OMP 使用 `HandoffResumeBackend`，核实保存部署、原 cwd 与精确会话文件后创建新运行。批准的部署摘要还会传入运行入口，在原物理/状态共享锁内重核，锁一直保持到宿主退出；预检后的配置漂移会拒绝派发并保留恢复意图。加载没有可信回执时显示“加载待确认”，请在官方 TUI 核对实际 ID、目录与历史；始终 `continue_status=not_sent`。退出码 0、人工确认或历史引用都不等于机器确认 `restored`。原 pane、新标签页和自动继续仍是独立条件能力，不能以本轮实现补勾完成。

| 工具 | 当前候选保护与限制 |
| --- | --- |
| DSH | 沿用精确锁定 Linux managed 当前终端交接及其 writer 检查；历史原生证据沿用，不宣称本轮重跑。 |
| Pi 1.3.0 | 仓库公开扩展在启动前预占 session 租约，公开切换事件先取得目标锁，再发布当前 ID；helper 保守持有用过的全部租约直到 host 退出。Claims 只覆盖 Rotom 合作进程；旧 active/unknown 且无 guard 的运行会阻止 claim，不按 PID 消失或 TTL 清除。三个自有来源由 `locks/pi/session-control.json` 校验。原生 `--resume` 是 picker；明确受管恢复用 `rotom resume pi --session SESSION_ID`，普通 `run pi -- --session SESSION_ID` 将完整 ID 核实为精确路径并持租约。原生目标文件缺失会产生新 ID，Rotom 启动前严格重核存在性；外部事后变化仍可能使结果 unknown。 |
| OMP 18.12.6 | 官方 session-ID writer 锁不在只读 open 时取得。固定源码 `session-manager.ts:1103–1128` 在首次写入发现原 ID 锁被占用时迁移到新 ID 的 sibling；不是预先拒绝第二次打开。原生已验证第二进程同 ID 打开、首次写入后 ID 分叉且原 ID 不变；原 writer 释放后可从原文件恢复原 ID 并写入。Rotom 明示可能分叉与加载待确认，请核对 TUI ID；不承诺任意外部 writer 提前拒绝。 |

Pi 的辅助 guard 观察只产生有来源的历史会话线索，不读会话正文、不授予 writer 或加载准入。损坏/跨 run/host/目录/权限的数据拒绝采用，辅助观察失败不应丢掉原进程列表。合法旧 source hash 的历史观察和已不存在 cwd 可保留为 historical，实际恢复须重新核验当前来源与目录。


当前 `sessions.py` 静态交接表仅准入以下精确组合，全部为 Linux / managed / here；任一运行锁、观察来源、平台或位置变化都拒绝并需重审。条目只准入交接，`load_confirmation` 与 `automatic_continue` 均为 false。

| 工具 | 完整 runtime identity | observer identity |
| --- | --- | --- |
| DSH | `e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d` | `none` |
| Pi | `62ac8348c34339599d280df5769ab0f8383a2f48c0885d84fa16c22a40a6b558` | `100331dd76bf2740304f7177ca1452660317484f674bb374a48fefae802f5817`（三来源控制锁） |
| OMP | `490e6c90d0ef4d890bb2ab14e006dcd3a3f4d79b5e6ad0ca9fbf3e8f4ab610ab` | `none` |

## 错误、取消与历史批次

```sh
./rotom --no-input agent --machine workstation --profile pi-base maintenance cancel --batch BATCH_ID --format json
./rotom --no-input resume pi --machine workstation --profile pi-base --session SESSION_ID --here
```

接受前取消/EOF/Ctrl-C 为 130，不派发动作。接受后的 cancel 只终止后续编排、保存原事实；不撤销已发生的停止或配置更新，不自动恢复。已投递或 unknown 的停止不能强行清保护；只对未投递或已证实退出的原 stop 批次按原协议收尾。即使停止快照缺失或原停止尚不确定，取消事实也先独立保存；这些情况返回 4，原保护继续保留。保留待恢复项，按 status 对账，不重发可能已执行的 setup/restore。参数/配置错误 2，凭据缺失 3，冲突/未知/待恢复 4，缺依赖或能力未准入 5，文件系统/内部错误 6；宿主交接保留原生退出码。

旧 stop 批次保留原 status/cancel 语义；不伪造 workflow 清单。旧 OMP Domain setup 批次不迁移、不重放，显式公开 `--profile` 声明为 omp 并提供现存 batch 时仍可只读查询：

```sh
./rotom --no-input agent --local /path/to/machine.toml --profile omp-default maintenance status --batch BATCH_ID --format json
```

这一路径不扫描其它机器或历史批次。原 `operation_result` 与查询 `exit_code` 分离；`protected` 仅指本批资源意图，不代表全局空闲。原操作成功但尚未人工交接为 4；completed 且当前目标/资源核验通过为 0；unknown/pending 为 4，原非零操作码保留。初始未派发即取消且正常观察为 0 仅说明取消，异常观察仍为 4。manual 不表示会话已恢复；旧批次 next_commands 只有精确范围的 status，不签发新执行或恢复许可。

## 验收记录与剩余工作

以下是分别执行、有重叠的范围证据，不相加，也不称为 full suite：tool workflow 162 passed；停止稳定组 165 passed；CLI 最终组 180 passed/4 skipped（较广阶段组 3451 passed/4 skipped）；Pi 观察组 250 passed；恢复组 21 passed。失败历史保留。UTF-8 header 最终组 78 passed；Pi 扩展 Node 最终组 43 passed。最终 workflow/resume/runtime/CLI 组为 353 passed / 4 skipped，旧 CLI/footer 组 99 passed，命令历史组 116 passed；最终集合对账为 13,561 passed / 12 skipped，未解决失败和未覆盖均为 0；分组覆盖与原失败复验见独立验收记录，main 合入另需人工批准。

原生检查均使用授权隔离环境、未经修改的官方宿主和合成会话，无网络/模型请求：Pi 1.3.0 已验证精确 ID/缺失目标行为、公开扩展初次 claim/重复租约拒绝/`switch_session`、原 pidfd SIGTERM（143）；OMP 18.12.6 已验证精确路径/缺失拒绝、同 ID 写入分叉、原 pidfd SIGTERM（三个进程均 143）及释放后恢复原 ID 写入。官方 TUI/PTY 补验分别观察到请求的精确 ID、原 cwd、零终端输入和 raw mode；原 pidfd SIGTERM 后 Pi 返回 0、OMP 返回 143，两者终端属性均恢复。生产 Pi guard 的原生验证采用 RPC，TTY 采用只读公开观察扩展，不能合称一次真实全 CLI 维护链路。DSH 沿用原 main 验收证据。本轮默认 pytest 不启动官方宿主，不读取真实账号或会话。

本轮具体来源、原生 argv 模板、失败历史与范围见[验收记录](../specs/008-rotom-command-experience/tool-workflow-validation.md)。

方案与规划见[按工具方案](../specs/008-rotom-command-experience/tool-workflows.md)、[任务清单](../specs/008-rotom-command-experience/tasks.md)；详细历史分别见[会话能力](rotom-session-capabilities.md)和[停止能力](rotom-stop-capabilities.md)。
