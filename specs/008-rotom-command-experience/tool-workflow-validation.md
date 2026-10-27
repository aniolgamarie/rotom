# 按工具维护流程：验收范围与证据

## 2026-10-27：位置范围、任务与当前提示核对

从候选 `121ab0a` 继续，仅修订当前 help、未开放位置的拒绝信息及规划一致性，没有启用驻留或新标签页。`run`/`agent run` 说明普通启动随 Agent 退出返回；`resume`/`maintenance restore` 说明当前终端不需 Herdr，以及原 pane 未来仅适用于 Rotom Herdr 新托管且逐工具已验收的实例。旧普通实例、直接官方 CLI、launcher/pane 丢失不保证原位；未开放位置仍返回 5，并给出同范围 `--here` 命令。

任务表保留全部旧 checkbox，17 个旧未完成项标明新方案替代，4 个自动继续项标为本轮范围外。原 pane 的 T085/T087–T095 保留待实现，并去除已替代的旧 T081/T082/T076 前置；新标签页新增 T135–T138。只有当前提示/规划同步 T134 完成，现为 102/138；T125 人工合入批准仍待处理。统一严格加载回执、原生 TUI 自动继续和 Pi Pro 委派不承诺，`pi-pro` 普通 profile 的维护恢复保留。

隔离验证：help/Herdr 提示/resume/停止清单/代理组 364 passed；普通 CLI 组 85 passed；公开文档检查测试 4 passed。新增 15 项提示边界测试包含静态 help 无业务 I/O、拒绝时 stdout 不变/精确范围命令和既有互斥检查。公开内容检查、变化的规格相对链接与任务编号/引用核对通过。上述不是全库重跑，也不产生新的 Herdr 或官方宿主原生验收。

Pi 的稳定父进程/同一 PTY 核心可行性探针另见[位置能力说明](../../docs/rotom-pane-capabilities.md#核心可行性证据与缺口)；它不代替生产驻留或三工具原位验收。以下官方 CLI 维护证据按原范围保留，不类推为新增位置能力。

## 2026-10-27：官方宿主贯穿公开 CLI 的补验

从候选 `47e1481` 继续，main 基线仍为 `45953f0`。以下使用未经修改的锁定官方宿主、Linux 原用户 UID、全新私人 HOME/XDG 和合成会话。运行阶段由 bubblewrap 隔离网络；DSH 的假模型 HTTP 服务在同一隔离网络的 loopback 内，不连接外部模型。没有注入恢复后端、替换生产启动器或修改原生包。原始 argv、退出码、锁、逐文件来源摘要和失败历史保存在私人任务记录。

三工具均通过公开 CLI 完成：启动 → 维护 plan/明确批准 stop → 已停止批次最新 plan/独立批准 execute → 实际配置更新 → `resume --stopped --list` → 精确 batch/run 当前终端恢复 → 独立停止新 run → 重复恢复拒绝。每次只有一个合成实例；旧 DSH 三选二和共享资源/失败场景的分项证据仍按原范围保留。

| 工具与组合 | 实际更新 | 原生结果 |
| --- | --- | --- |
| DSH，完整锁 `e4d56f…` | `terminal_images` 从 false 到 true，至少一项实际变更 | 初始及恢复宿主退出 0；同一原生 session 与 cwd，历史 `DONE_ONE` 可见，新 run；终端属性恢复；重复恢复返回 4；原 host 身份均退出。初始输入 28 字节创建合成历史，恢复输入 0 字节。 |
| Pi Base，候选锁 `62ac8348…` | thinking 从 medium 到 low | 生产公开扩展初始及恢复观察到精确 ID/cwd；两次退出 0，终端恢复，原历史保留、重复恢复 4、无活动 manager，恢复输入 0 字节。 |
| Pi Base，新锁 `a68d9dcf…` | 同上，保留 Cursor/footer 的精确锁选择 | 与上行同项通过。先在私人候选加入精确准入，再跑完整链路；其 `sessions.py` SHA-256 与本轮应用到任务分支的源码完全一致。 |
| Pi Pro，新锁 `a68d9dcf…` | 同上，保留 Pro 默认 footer 与协作配置 | 与 Base 同项独立通过；没有调用委派工具或模型，不将 Base 结果类推为 Pro 通过。 |
| OMP 18.12.6，完整锁 `490e6c90…` | 更换已声明主题，至少一项实际变更 | 使用公开 `resume --session` 启动已有合成会话，随后完整维护与 `--stopped` 恢复。两次 host 退出 143，manager 按原生码返回；原目录/历史可见、新 run、终端恢复、owner 全为 idle_confirmed、重复恢复 4、输入 0 字节。最终无追踪执行退出 0。 |

各工具仍记录 `load_confirmation=unknown`、`continue_status=not_sent`。TUI 中的历史与人工观察不升级为严格加载回执。DSH 的恢复使本地假模型请求从 2 次增加到 3 次，系统请求材料保留为宿主标题/辅助行为；不能称零模型请求或把它记为 Rotom 发送继续。Pi/OMP 本轮没有模型提示输入。

显式原生脚本分别为 `tests/manual/dsh_tool_workflow_native.py`、`pi_tool_workflow_native.py`、`omp_tool_workflow_native.py`，均要求 `--allow-host`，不进入默认 pytest。运行包准备经过正常安装器/后端及收据核验；OMP 的可再生缓存放在 namespace 的 tmpfs，防止重复二进制占满系统磁盘。新 Pi 两档正常 `npm ci --ignore-scripts`、离线闭包及脚本审核通过；官方 host tarball SRI 和每档 1,276 个归档文件字节匹配。

### OMP 真实验收发现与修复

原停止客户端轮询 `status` 时会短暂持有 owner 锁；OMP 已证明完整退出后的 `finish_owner` 若碰到该锁，原 NB 获取立即失败，保留 active 并阻断后续维护。真实诊断记录到 owner 的 `BlockingIOError`，随后退出阶段抛 Conflict，终端显示收尾未确认；信号已发送不等于停止完成。

修复只在退出写入前遇到真实 owner 锁竞争时，释放 Domain，最多等待 2 秒后按原顺序重取并重核。owner 仍以 NB 获取，成功后持续持有至 Domain 提交/同步/读回完成；任一写入或结果不确定都不重试。两个退出阶段的原 manager、完整释放观察、路径/资源/摘要和 unknown 保护保持严格校验。2 秒是锁竞争预算，不是整个持久化事务的执行时限。

针对性测试用真实临时 flock 复现旧获取路径：4 failed / 4 passed；修复后的新测试及 owner/release/cooperative 组为 202 passed。Pi 准入及 guard/观察/维护 CLI 组为 318 passed / 4 skipped。各组有重叠，不相加为全库结果。最终维护/停止历史受影响回归另记私人任务记录，未把旧 13,561 项结果冒充本轮全量重跑。

失败历史保留：测试 fixture 缺少模型容量/vision 字段、错误使用受管 `run --resume`、启动探针争 owner 锁、准备阶段 DNS/祖先归属限制、早期退出 helper 在 Domain 提交前释放 owner 的单测失败，以及临时磁盘耗尽。修正均经过对应复验。启动时控制服务未建立仍保留人工停止提示，不把无端点记录当可自动控制。

### main 的 Pi 锁兼容结论

main 的四个未提交 Pi 锁文件始终未修改或吸收到本分支。新锁完整 identity 为 `a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587`；本轮只给这组锁和当前 observer `e286d053…` 的 Linux/managed/here 组合新增精确交接条目，旧 `62ac8348…` 仍支持。新条目不开放严格加载、自动继续或其它位置。

新 Base 锁的选择为 footer 后 Cursor，且 Cursor 需要公开 cursor provider；默认仅 footer 的 Base 示例与该选择不同，会按既有规则拒绝 stale lock。核验用临时配置显式声明锁中的选择，没有暗改公共默认或真实机器配置。Pro 没有新增直接依赖，但间接闭包变化已独立安装并做原生验收。账号登录、真实模型/委派工具及其它平台不在本轮验收范围。

本节 supersedes 下方旧阶段“全 CLI 未验证”和“新 Pi 锁未准入”的状态；历史记录保留。main 整合仍需人工批准和整合验收。

## 以下为此前阶段记录

**2026-10-26 分支复审补验**：Pi 保护失败后的执行阻断已修复，覆盖打印、JSON、RPC 与 TUI；官方运行包分项与受影响隔离回归通过。候选尚未合入 main，合入须人工批准；完整官方 CLI 维护链路等未验证范围仍单独保留。详见[分支复审](branch-review.md)。

日期：2026-10-26。开发基线为 main `45953f09ce14908282b4af4c08101227e151ca3f`；
候选分支为 `feat/tool-maintenance-workflows-20261026`。提交 `2cda58d` 的候选实现和分组回归曾完成；后续复审发现的保护失败问题已修复并完成分项补验，详见分支复审。候选仍待人工审批，
本记录不表示 main 已具有候选能力。私人任务记录保存逐文件摘要、原始 argv、退出码和原始日志。

## 行为与兼容性

三工具沿用各自运行和部署保护，通过保存恢复清单、精确停止、独立批准普通 setup、
逐项当前终端恢复形成完整的显式维护流程。没有跨阶段写许可，没有自动继续输入。
以下边界已有实现和针对性回归，整库结果见下方单独状态：

- OMP host 更新复用 `owner_pending` 的 Domain/owner 双向摘要；共享运行包引用仍约束更新。
- Pi/OMP 控制端点置于既有 inbox 的 sidecar，保持旧 RunRecord reader 和 OMP 摘要兼容。
- 普通 setup 保留现有物理锁、运行 owner 和共享资源检查；新并发实例不会被自动加入停止集合。
- `lock` / `sync` 仅显式选择命名代理；不继承普通 run 的代理默认；窄签名后端保持兼容。
- 目标完整运行包没有恢复准入时，在维护停止前拒绝；更新批准前再次核验。独立停止和普通 setup 仍可用。
- 恢复绑定本次批准的部署摘要，在运行共享锁内重核；配置发生变化不会启动错误版本。
- cancel 先保存禁止后续阶段的事实；原停止未确定时保留 fence，返回 4，不重投信号。
- 所有会话头严格 UTF-8 解码。OMP 固定格式的 256 字节标题槽可跳过；标题不作为会话身份，正文不读取。
- help、交互选择、非 TTY 缺参、重复选择、旧停止批次和旧 OMP 查询均分别回归。

主目录已有四个 Pi 锁文件的未提交改动，完整 identity 为
`a68d9dcf3346c0c6ab9bff231f85510dea2d9d25794664cd835cd476c3460587`，
与本候选验收的完整组合不同。本轮未修改或吸收这些文件，也未给新组合补造恢复准入。
当前适配器的只读校验已接受该锁格式；独立普通启动/部署入口保留，但没有据此宣称真实日常部署已验收。若保留该锁用于维护，应先完成其单独验收。不能把本候选的测试结果
当作对主目录未提交组合的通过证明。

## 未修改的官方运行包

| 对象 | 本轮核验 |
| --- | --- |
| Pi 1.3.0 | 官方 tgz 的 SHA-512 SRI 与锁一致；安装目录中归档内 1276 个文件逐字节一致。 |
| OMP 18.12.6 | 固定提交 `45c35e40c46166dc726ccc52f5d27f40f2449f99`；使用官方 Linux x64 二进制，SHA-256 `85d9daf3a05fc76e8cd425ae1904eb576af8d21cc85fcf4690742626e07ccfa4` 与当前 asset 锁一致。 |
| Pi 自有控制来源（提交 `2cda58d` 阶段） | 三个来源与当时 `locks/pi/session-control.json` 相符，identity 为 `100331dd76bf2740304f7177ca1452660317484f674bb374a48fefae802f5817`。后续等号参数和失败阻断修正的来源 identity 与复验见分支复审。 |
| DSH | 沿用 main 的固定锁原生验收；本轮未重跑 DSH 原生测试。 |

OMP 二进制来自已准备的官方缓存；二进制匹配不表示缓存目录名代表当前完整配置 identity。
Pi/OMP 恢复准入仍绑定[维护指南](../../docs/tool-maintenance-workflows.md)列出的完整锁组合。
没有修改 vendor、缓存宿主源码、官方二进制或导入宿主私有接口。Pi 原生运行使用 Node v24.14.0，满足适配器的 Node v22.19.0 最低版本要求。

## 显式授权的原生验证

Linux、原用户 UID、隔离 HOME/XDG、合成会话；bubblewrap 隔离网络，未访问真实账号或会话。
所有模型标识和密钥值均为测试配置；没有发送模型请求。公开报告使用路径占位值；原始 argv
保存在私人证据内。下表的 RPC 请求是官方控制接口请求，不是模型提示词或终端继续输入。

| 验证 | 观察和退出码 |
| --- | --- |
| Pi 官方 RPC 精确 `--session FILE` | `get_state` 返回请求 ID；正常退出 0。缺失目标可创建新的内存会话 ID，仍退出 0，不能将原生成功当作精确恢复。 |
| Pi 生产公开控制扩展 | 实际初次 claim 和辅助会话观察一致；第二个登记运行争用同 ID 被拒绝；官方 `switch_session` 切换到精确新 ID 后新 helper 观察一致；原 pidfd SIGTERM 后 143。 |
| OMP 官方 RPC 精确 `--resume FILE` | 精确目标返回原 ID、退出 0；缺失目标拒绝、退出 1。 |
| OMP 原生 writer | 两进程可只读打开同 ID；第二进程首次写入通过原生逻辑改用新的 sibling ID，第一进程 ID 不变。原 writer 退出后可恢复原 ID 并写入；三个进程原 pidfd SIGTERM 后均 143。 |
| Pi 官方 TUI / PTY | 只读公开 `session_start` 观察到精确 ID、原 cwd；原生进入 raw mode；输入 0 字节；原 pidfd SIGTERM 后退出 0，终端属性恢复。 |
| OMP 官方 TUI / PTY | 同上；原 pidfd SIGTERM 后退出 143，终端属性恢复。 |

TUI 检查采用额外的自有只读公开观察扩展。Pi 生产 guard 在独立 RPC 检查中验证；
不能把这些分项结果说成一次使用真实官方宿主贯穿全部 Rotom CLI 的停止→setup→恢复测试。
全流程 CLI 的持久化、部署、批准与故障顺序由隔离测试验证，原生协议由上述分项验证。

关键原生 argv 模板（`FILE`、`SESSION_DIR`、`OBSERVER` 均为隔离环境路径）：

```text
node PI/dist/bundle/cli.js --mode rpc --session-dir SESSION_DIR --no-extensions --no-skills --no-prompt-templates --no-themes --no-mcp --no-approve --session FILE
omp --mode rpc --no-extensions --no-skills --provider openai --model gpt-4o --resume FILE
node PI/dist/bundle/cli.js --session-dir SESSION_DIR --no-extensions --no-skills --no-prompt-templates --no-themes --no-mcp --no-approve --session FILE --provider openai --model gpt-4o -e OBSERVER
omp --no-extensions --no-skills --resume FILE --provider openai --model gpt-4o -e OBSERVER
```

Pi guard 检查由生产 `prepare` 在第一条 argv 上追加受锁校验的公开扩展，并通过最小环境传递
控制上下文和继承租约 FD。helper 使用 Python `-I`，不继承 PYTHONPATH 或认证环境。

## 隔离回归与失败历史

默认 pytest 使用临时 HOME/XDG、阻断网络与假宿主；不能作为真实宿主证据。
各组有重叠，不能相加称为全库测试数。

| 范围 | 当前结果 |
| --- | --- |
| header 最终组，含 UTF-16/32 负例 | 78 passed；退出 0。 |
| Node 公开控制扩展阶段组（`2cda58d`） | 43 passed；退出 0；宿主和 helper 均为替身。最新失败阻断组为 71 passed，其中 28 条使用真实 Node 子进程执行自有扩展，仍不启动第三方宿主。 |
| Pi 观察 / guard / runtime 阶段组 | 250 passed；退出 0。后续部署绑定变更另跑受影响组。 |
| workflow / resume / runtime / CLI 最终组 | 353 passed / 4 skipped；退出 0；生产与测试摘要稳定。四项为 Pi 专属场景的非 Pi 参数跳过。 |
| 旧 CLI / footer 契约修复 | 99 passed；退出 0。 |
| 命令历史隔离 | 116 passed；退出 0；相对哨兵不依赖临时根路径格式。 |
| 整库分组阶段 | 首段 4629 passed / 8 skipped / 8 failed 后主动中断；四组依次为 2239 passed / 1 failed、2235 passed / 2 skipped / 3 failed、2239 passed、2233 passed / 2 skipped / 4 failed。原始失败记录保留。 |
| 后续完整文件复验 | 预览/部署 55 passed；OMP 实例 15 passed；恢复工厂 29 passed；所有分组阶段失败均已通过相应完整文件复验。 |

初轮隔离失败、错用沙箱假 Node 所得单文件结果、原生环境准备失败、Pi helper 的 stdlib
名称遮蔽错误和 OMP writer 冲突行为的错误预期均保留在私人证据中；后两项已分别修复并重跑。
审查发现的部署 TOCTOU、取消与停止收尾耦合、UTF-16/32 自动探测，以及 help epilog 被覆盖
均已修复，最终受影响组合已通过。测试替身自身的失败与生产缺陷分开记录。分组期间出现的旧工具准入预期、额外控制扩展与 UI 链排序、fake child hook，以及临时目录格式依赖均已更新并完整复验；没有修改生产代码来迁就旧断言。

提交 `2cda58d` 阶段的最终稳定收集共 **13,573** 个唯一测试节点。按首段、四个分组及受影响完整文件复验逐项对账，结果为 **13,561 passed / 12 skipped / 0 未解决失败 / 0 未覆盖**。重叠测试只计一次；5 个已被替换的旧工厂测试 ID 记录为替换，不冒称原 ID 重跑通过。首段另有 7 个通过的 subtest，不计入上述节点总数。这是分组及复验汇总，不是一次未中断的全绿运行。

12 个跳过项包括 7 个已退休 OMP 宿主补丁测试、1 个未提供可选锁定 Bun 材料的官方 SDK 测试，以及 4 个 Pi 专属测试在 DSH/OMP 参数下的跳过；均未计作通过。

严格加载回执、原 Herdr pane 恢复、自动继续及其它平台均未由本轮开放。
这些条件能力不是本轮分阶段维护流程的隐藏前置。main 整合保留为独立人工批准步骤。
