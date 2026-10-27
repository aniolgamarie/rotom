# 按工具执行停止、更新与恢复

状态：候选留在任务分支，尚未合入 main，合入须人工批准。新增位置恢复实现已写入，最终十二组无 trace 原生验收全部通过，公开准入限定六个精确 Linux managed 组合的两种位置。以下 2026-10-27 当前终端历史证据不涵盖新增位置路径：已补齐 DSH/Pi/OMP 官方宿主贯穿公开 CLI 的停止、实际 setup 更新、停止清单与当前终端恢复验收，并修复 OMP 退出记账与查询之间的短锁竞争；main 新 Pi 锁的 Base/Pro 也已单独核验，见[最新验收记录](../specs/008-rotom-command-experience/tool-workflow-validation.md)。基线 main `45953f0`；本文说明候选接口，日常入口仍按已部署绑定运行。

## 分阶段操作

DSH、Pi、OMP 共用明确选择后的流程：保存恢复清单 → 精确停止 → 关闭本次 stop fence → 独立预览并批准普通 setup → 逐项恢复（默认当前终端，位置候选须另行准入）。这不是一笔跨进程事务。停止批准不授予更新许可，恢复也不发送继续文本。

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

完整目标锁没有恢复准入时，plan/stop 在停止前拒绝，execute 在更新批准前再次检查；可改用独立 instances stop、普通 setup 和官方界面人工恢复。第一次 plan 的摘要只用于 stop；停止完成后的 `plan --batch` 返回最新 setup 摘要，只用于 execute。不要复用摘要或把 JSON 当许可。`--operation setup` 可省略；首次 plan 与 stop 的 `--run`、`--session` 映射必须一致。选择多个运行时重复 `--run` 和对应 `--session`，不重复同一 run；maintenance restore 每次交接一项，默认当前终端，不让多项争用 stdin；另接受互斥 --here/--original/--new-tab。批量位置请求使用下述 resume --stopped --batch B --all。

自动交互要求 stdin/stdout/stderr 全部 TTY；根 `--interactive` 可明确请求交互，但不能绕过这一条件。TTY 可选择缺失的运行与会话，展示计划后分别批准 stop 和 setup。非 TTY 或根 `--no-input` 必须给足目标及当前 `--plan-id`，不读 stdin；缺参/批准返回 2，计划漂移返回 4。restore 的宿主仍需要自己的交互终端，`--no-input` 只约束 Rotom 的提问，不模拟宿主输入。计划只读，无网络和控制；execute 可通过原安装器联网/写配置，restore 可启动官方宿主。

## 并发短锁与事实保留

驻留 parent 在 child 活动时不读取 owner/Domain；退出后才按唯一出生身份核验完整 release 并 parked。active 的位置诊断只按 child/manager 身份关联候选，不授原位许可；原位消费仍需 parked、保存的 run 与所选旧 run 精确匹配。

共享 Domain 写事务默认只在首个 flock 前等最多 2 秒，显式 deadline 沿用原绝对点，不续期；进入 body 后的校验、提交或解锁异常不重放。外部只读和 snapshot 默认 NB，只有合作启动 package_guard/check_omp_launch 两处显式首锁读预算。OMP 资源及 anchor 选择与预留同一写事务完成，提交成功后才返回 token；通用 reserve 的 revision CAS 仍严格。

停止 close 后与最终 fallback 的 status 沿本次原截止时间等待纯读短锁；已过期时只允许一次无竞争观察，竞争或其它未知仍保留 close/fence 的真实落盘状态，不重 close、请求或信号。独立 status 默认 NB。Herdr V1 使用 accepted 前最后核验的 caller，accepted 后正常清 pending 不会导致驻留交接误退 shell。

本节描述实现语义，最终十二组无 trace 位置原生验收全部通过；[六组合、两位置及四项 work 入口矩阵](rotom-pane-capabilities.md#本轮精确组合验收清单)是实际支持范围。最终 delivery-verification 的14,166个唯一默认隔离测试已完成：14,153 passed / 13 skipped / 0 failed；前一源码快照 `14102 + 13 skipped` 保留为历史。功能分支尚未合入 main，T125 待人工批准。

## 精确停止与独立更新

三个工具的 Linux managed `stop_only` 均使用审阅后的快照、fence、CAS、一次请求、原 host pidfd 的 SIGTERM 和退出核验。不按 PID/进程名猜测，不强杀，不控制未选运行。等待默认 30 秒、范围 1–300 秒，整个集合共享绝对截止时间；超时或结果不确定保留批次和保护，返回 4，不重发。

Pi/OMP 的 stop endpoint 保存为既有 inbox 的 sidecar，绑定原 run/manager/host/deployment，不为兼容而改写旧 RunRecord；没有可信通道的旧运行仍需人工停止。OMP 的新 host 登记通过 `owner_pending` 与 Domain/owner 摘要协调，不能直接改 Registry 绕过 Domain。精确停止不声称已释放所有共享资源，也不改变 Domain 许可语义。

确认退出并关闭本次 stop fence 后，execute 重新取得普通 setup 的最新计划与独立批准，重走实例/HOME/包物理锁、owner 和共享资源完整门禁。并发新运行、未选共享引用或 unknown 均可阻止更新；不会扩大原停止集合。原维护结果和退出码保留，状态查询或恢复结果不能覆盖它。可能已执行的 unknown 不自动重试；只有可证实允许的新执行才能重新预览并批准，不从磁盘重建许可。

## 已停止会话清单与快捷恢复

不需要 Herdr。候选入口支持在当前机器的已保存停止记录中查看工具、profile、完整 session ID、原目录、标题、batch/run 和停止/恢复状态：

```sh
./rotom resume --machine workstation --stopped --list --format human
./rotom resume pi --machine workstation --profile pi-base --stopped
./rotom --no-input resume pi --machine workstation --profile pi-base --stopped --batch BATCH_ID --run RUN_ID --here
```

第一条只读列出记录，可用 `--format json` 获取结构化信息和精确范围的下一步 argv。第二条在 TTY 中选择一个满足批次条件的会话，直接交接到当前终端；第三条适合已知精确批次与运行的调用。非交互单项恢复必须同时给出完整 --batch 和 --run，不默认选最近一项。--stopped 与 --session 冲突，但可选择 --original/--new-tab；--list 不能带任何位置选项或 --all。不指定机器时沿用普通 resume 的机器解析。默认 here 仍只恢复一项。

维护批次的会话会在停止前保存。可给 plan 和 stop 同时添加相同的 `--label RUN_ID=TITLE`，例如 `--label 'RUN_ID=修复配置加载'`；多个 run 可重复该选项。备注限 1–160 字符单行文字。没有备注时，OMP 尝试读取官方固定标题槽；DSH/Pi 显示无标题，目前不扫描正文或自动生成摘要。标题属于这次批准的清单，变更后需重新 plan；标题不替代 session 身份。旧 v1 维护清单仍能读取，无标题保持为空。人工备注和原生标题只保存在本地私人状态，不应包含凭据。

“可尝试恢复”只表示批次条件满足；执行时仍会重新核实原生 ID、目录、部署和能力。配置尚未更新、取消、已有恢复意图/结果、停止未知或部署漂移的批次不会进入快速选择列表。`--list` 查询损坏批次时保留其它可读行并返回 4，不把未知当空历史；另一条完整批次仍可独立选择，执行前按精确范围复核。记录的 `observed_at_ns` 是会话观察时刻，不是停止时间。历史查询不读取原生会话正文，也不启动宿主。human 输出将控制/格式字符可见化；JSON 保留精确路径原值供程序使用。

旧 `instances stop` 的独立快照没有 workflow 来源证明；缺失维护日志的残留快照也可能呈现相同形态。因此这类记录只展示 ID、目录和人工核对后的普通恢复命令（JSON 的 `next_commands.manual_restore`），不直接进入批次快速恢复，以免绕过丢失的取消或派发记录。未观察到 ID/原目录时继续显示未知，不猜测。清单只能列出 Rotom 已保存的停止记录，不能追溯外部 `kill` 且未登记的会话。

选择恢复后仍显示“加载待确认”，由人在官方 TUI 核对；不发送继续命令。当前位置支持限定下述精确组合；当前终端入口独立于 Herdr 与位置准入。

## 完整批次的位置恢复候选

只有已经停止、setup/update 成功且未取消/未派发的完整 workflow 项可进入位置门禁。以下命令只在已通过最终原生验收的六个精确 Linux managed 组合内开放，现场仍须重新通过全部门禁。

```sh
./rotom --no-input resume pi --machine workstation --profile pi-base --stopped --batch BATCH_ID --run RUN_ID --new-tab --format json
./rotom --no-input agent --machine workstation --profile pi-base maintenance restore --batch BATCH_ID --run RUN_ID --original --format json
./rotom --no-input resume pi --machine workstation --profile pi-base --stopped --batch BATCH_ID --all --new-tab --format json
./rotom --no-input resume pi --machine workstation --profile pi-base --stopped --batch BATCH_ID --all --original --format json
```

--all 须完整 batch、非 here 位置，禁止 --run/--session/--list/--here。第一次分发前核验整批同 scope/profile/batch 的全部项，来源不明、坏记录或不可恢复项拒绝整批，不静默筛选；随后每项再重查原范围、精确会话、目录和部署。每项使用独立终端和一次意图，不共用 TUI 输入。遇非零或未知立即停止后续派发，未执行项明确 not_dispatched，先前创建/交接事实保留。JSON 只输出一个 `{batch_id,location,results,load_confirmation,continue_status}` 汇总，各结果保留 run_id、exit_code、result；全部交接返回0，其余返回4。不要将整体重试当成未执行项恢复，先查询原批次与位置事实。

Herdr V1/V2 的新 DSH/Pi Agent 启动与符合驻留组合的新 tab 恢复可由薄 launcher 管理；普通 rotom run 不驻留。只停止 Agent 并保留 launcher/pane 才能等待原位恢复。parked 不持单次 Agent 租约、运行包或凭据环境；源码身份变化、pane 复用或丢失拒绝旧位置，不在线升级旧普通实例。

## 恢复和 writer 的真实边界

Herdr 是工作区原生终端操作的前提：`work enter`、`work named enter` 需要配置的 Herdr 可执行文件和可核验 API，从外部进入可启动配置的 headless 会话；`work open`、`close`、`rebind` 需要当前 Herdr 调用上下文与运行中的 API。`work list --live`、`status`、`reconcile` 查询运行中的 API，不自动启动，endpoint unknown 不等于未安装或空闲。配置检查/编辑、注册元数据、离线 `work list`、不带 `--enter` 的 Git worktree 创建不需要 Herdr；`worktree create --enter` 仅后续进入需要它，进入失败保留 checkout。`named rename` 先保存元数据，再尝试同步原生标题，Herdr 不可用时保留保存结果并提示待同步。根 resume --here（默认）及 maintenance restore --here 在当前终端交接，不需要 Herdr。完整 workflow 的 --original/--new-tab 候选需要当前受支持 Herdr 上下文与精确组合准入；公开准入仅覆盖已验收的六个精确 Linux managed 组合、两种位置。普通 resume --session 的这两个位置保持未开放，安装 Herdr 本身不授予资格。

DSH 沿用已验收的原 Host 后端；Pi/OMP 使用 `HandoffResumeBackend`，核实保存部署、原 cwd 与精确会话文件后创建新运行。批准的部署摘要还会传入运行入口，在原物理/状态共享锁内重核，锁一直保持到宿主退出；预检后的配置漂移会拒绝派发并保留恢复意图。加载没有可信回执时显示“加载待确认”，请在官方 TUI 核对实际 ID、目录与历史；始终 `continue_status=not_sent`。退出码 0、人工确认或历史引用都不等于机器确认 `restored`。

Herdr 新标签页和新托管实例原 pane 候选已实现，十二组正式原生验收已通过，准入限定支持矩阵中的六个精确 Linux managed 组合及两种位置。原 pane 仅适用于通过 Rotom Herdr 入口、由驻留启动器托管且该工具已验收的新实例，入口默认驻留；普通 shell `rotom run` 仍在 Agent 退出后返回，旧普通实例或直接官方 CLI 不在线升级。只停止 Agent 才能保留原位等待；launcher/pane 关闭、被复用或归属未知时需当前终端或另行接受的新位置。help 与当前拒绝信息已说明这一区别，maintenance plan/停止交互批准中的 location_diagnostics 为只读提示，不改变 plan_id；停止清单还可展示已有 location_request，不能据此重新开放已派发请求。细节及证据见[位置能力说明](rotom-pane-capabilities.md)。

统一严格加载回执、原生 TUI 自动继续不在本轮承诺中；Pi Pro 委派独立规划，`pi-pro` 作为普通 profile 的维护恢复兼容性不受影响。不能将上述未开放项或历史已替代任务补勾成完成，当前任务分类见 [tasks.md](../specs/008-rotom-command-experience/tasks.md#当前范围与任务终态的含义)。

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
| Pi | `62ac8348c34339599d280df5769ab0f8383a2f48c0885d84fa16c22a40a6b558` | `e286d053f59613d94c8be14d89f3def12dafdc67ef54a9746d7d2229ce362d9a`（三来源控制锁） |
| Pi（另经 Base/Pro 核验的新锁） | `a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587` | 同上；Base 配置需与该锁的 footer/Cursor 选择及 provider 声明相符，不自动更改默认选择。 |
| OMP | `490e6c90d0ef4d890bb2ab14e006dcd3a3f4d79b5e6ad0ca9fbf3e8f4ab610ab` | `none` |

## 错误、取消与历史批次

```sh
./rotom --no-input agent --machine workstation --profile pi-base maintenance cancel --batch BATCH_ID --format json
./rotom --no-input resume pi --machine workstation --profile pi-base --session SESSION_ID --here
```

接受前取消/EOF/Ctrl-C 为 130，不派发动作。接受后的 cancel 只终止后续编排、保存原事实；不撤销已发生的停止或配置更新，不自动恢复。已投递或 unknown 的停止不能强行清保护；只对未投递或已证实退出的原 stop 批次按原协议收尾。即使停止快照缺失或原停止尚不确定，取消事实也先独立保存；这些情况返回 4，原保护继续保留。保留待恢复项，按 status 对账，不重发可能已执行的 setup/restore。status 对停止 pending 及无结果的 setup/restore 意图返回 4，即使取消已保存也不将它们显示为查询成功；已知原生结果仍单独保留。参数/配置错误 2，凭据缺失 3，冲突/未知/待恢复 4，缺依赖或能力未准入 5，文件系统/内部错误 6；宿主交接保留原生退出码。

旧 stop 批次保留原 status/cancel 语义；不伪造 workflow 清单。旧 OMP Domain setup 批次不迁移、不重放，显式公开 `--profile` 声明为 omp 并提供现存 batch 时仍可只读查询：

```sh
./rotom --no-input agent --local /path/to/machine.toml --profile omp-default maintenance status --batch BATCH_ID --format json
```

这一路径不扫描其它机器或历史批次。原 `operation_result` 与查询 `exit_code` 分离；`protected` 仅指本批资源意图，不代表全局空闲。原操作成功但尚未人工交接为 4；completed 且当前目标/资源核验通过为 0；unknown/pending 为 4，原非零操作码保留。初始未派发即取消且正常观察为 0 仅说明取消，异常观察仍为 4。manual 不表示会话已恢复；旧批次 next_commands 只有精确范围的 status，不签发新执行或恢复许可。

## 验收记录与剩余工作

历史当前终端范围：2026-10-27 的真实全 CLI 维护验收与 OMP 退出锁竞争修复已完成，Pi 新锁 Base/Pro 均有独立原生结果。隔离专项组包括 owner/release/cooperative 202 passed、Pi guard/准入/维护 CLI 318 passed / 4 skipped；各组重叠，不合算为全库结果。main 人工整合、其它平台、慢 SSH 与可选 Bun 材料仍单列，当时原 pane/新标签页尚未开放；当前位置准入另见[精确支持矩阵](rotom-pane-capabilities.md#本轮精确组合验收清单)，自动继续仍未开放，详见[最新验收记录](../specs/008-rotom-command-experience/tool-workflow-validation.md)。

此前复审修正通过的 71 条 Node 测试、391 passed / 4 skipped Python 组及 11 项官方 Pi 分项保留原范围。真实 helper 的 TUI 启动拒绝和运行中失联均退出 4，PTY 属性恢复，见[分支复审](../specs/008-rotom-command-experience/branch-review.md)。

以下是提交 `2cda58d` 阶段分别执行、有重叠的范围证据，不相加：tool workflow 162 passed；停止稳定组 165 passed；CLI 最终组 180 passed/4 skipped（较广阶段组 3451 passed/4 skipped）；Pi 观察组 250 passed；恢复组 21 passed。失败历史保留。UTF-8 header 最终组 78 passed；Pi 扩展 Node 最终组 43 passed。最终 workflow/resume/runtime/CLI 组为 353 passed / 4 skipped，旧 CLI/footer 组 99 passed，命令历史组 116 passed；最终集合对账为 13,561 passed / 12 skipped，未解决失败和未覆盖均为 0；分组覆盖与原失败复验见独立验收记录，main 合入另需人工批准。

提交 `2cda58d` 阶段的原生检查均使用授权隔离环境、未经修改的官方宿主和合成会话，无网络/模型请求：Pi 1.3.0 已验证精确 ID/缺失目标行为、公开扩展初次 claim/重复租约拒绝/`switch_session`、原 pidfd SIGTERM（143）；OMP 18.12.6 已验证精确路径/缺失拒绝、同 ID 写入分叉、原 pidfd SIGTERM（三个进程均 143）及释放后恢复原 ID 写入。官方 TUI/PTY 补验分别观察到请求的精确 ID、原 cwd、零终端输入和 raw mode；原 pidfd SIGTERM 后 Pi 返回 0、OMP 返回 143，两者终端属性均恢复。生产 Pi guard 的原生验证采用 RPC，TTY 采用只读公开观察扩展，不能合称一次真实全 CLI 维护链路。DSH 沿用原 main 验收证据。本轮默认 pytest 不启动官方宿主，不读取真实账号或会话。

各阶段具体来源、原生 argv 模板、失败历史与范围见[验收记录](../specs/008-rotom-command-experience/tool-workflow-validation.md)。

方案与规划见[按工具方案](../specs/008-rotom-command-experience/tool-workflows.md)、[任务清单](../specs/008-rotom-command-experience/tasks.md)；详细历史分别见[会话能力](rotom-session-capabilities.md)和[停止能力](rotom-stop-capabilities.md)。
