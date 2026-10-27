# CLI 公共契约

日期：2026-10-26。状态：既有当前终端维护候选的分组与受影响复验保留原范围；新增位置恢复已通过最终十二组无 trace 原生验收，公开准入为六个精确 Linux managed 组合的两种位置。尚未合入 main，合入须人工批准。P-SESSION/P-EXIT/P-PANE/P-INPUT 仍分别准入。
依据：[规格](../spec.md)、[007 入口设计](../../007-rotom-cli-entry/design.md)、
[维护设计](../../007-rotom-cli-entry/maintenance.md)。部署产物见
[入口部署契约](entry-deployment.md)，身份、停止和恢复门禁见
[生命周期契约](lifecycle.md)，持久字段见[数据模型](../data-model.md)。

## 语法与兼容边界

```text
rotom [--interactive | --no-input] COMMAND ...
COMMAND := run | resume | agent | term | work | config
rotom run [TOOL] [--machine NAME | --local PATH] [--profile ID]
          [--cwd PATH] [--inherit-env NAME]... [--unset-env NAME]... [-- ARGS...]
rotom resume [TOOL] [--session ID] [--machine NAME | --local PATH]
             [--profile ID] [--here | --original | --new-tab]
rotom resume [TOOL] [--machine NAME | --local PATH] [--profile ID]
             --stopped [--list | --batch B --run R [--here | --original | --new-tab]]
rotom resume [TOOL] [--machine NAME | --local PATH] [--profile ID]
             --stopped --batch B --all (--original | --new-tab)
rotom agent [--machine NAME | --local PATH] [--profile ID] SUBCOMMAND ...
rotom term [--machine NAME] SUBCOMMAND ...
rotom work [--machine NAME | --local PATH] SUBCOMMAND ...
rotom config {show | set [KEY] [VALUE] | unset [KEY]}
```

`TOOL` 为 `dsh|pi|omp`。根交互 flags 互斥，放在命名空间前；根 `run/resume`
选择器放在相应命令后。`agent/term/work` 沿用底层选择器位置与参数规则；
兼容子命令已有的位置别名仍保留，帮助须显示其位置限制。
`--machine` 与 `--local` 互斥且不得重复；重复 profile、无值选项、未知字段、
未知子命令和显式不匹配均先报 2，不进入纠错菜单。

`agentcfg`、`termcfg`、独立 `work` 保留既有语法、默认、无参行为、输出和退出状态；
本契约不重命名 Python 包，不移动原生 HOME、配置、账号、缓存或会话目录。
`rotom agent run` 采用兼容层管理默认，日常短启动使用根 `rotom run`。
不另加 `rotom pi` 等简写；`rotom run omp` 不证明 OMP 工作区 type 已准入。

第一个 `run --` 后的每个 token 均归原生程序，保留 argv 次序和字节含义，
不解释根 flags、help 或补全；后端既有安全边界检查仍有效。
`agent usage` 的**全部尾部**归 OMP，包括 `--help`；管理说明位于 `agent --help`。
未显式选择 profile 的独立 usage 不注入保存的默认 machine/profile。

```sh
rotom run pi --help
rotom run pi -- --help
rotom agent usage --help
rotom --no-input term --machine workstation sync --component zsh
```

前一条为静态启动帮助；第二条是实际受管启动请求；第三条交给原生 usage。
根 `--no-input` 不进入宿主 argv，也不允许绕过宿主原有参数限制。

## 默认解析和作用域

先校验显式参数，再按下表选择；失效偏好明确失败，不扫描其它机器、自动初始化或回落。
三个 machine 偏好名称相同也不表示三个管理面共享配置或所有权。

| 路径 | machine/local | profile / 目标 |
| --- | --- | --- |
| 根 `run` | 显式 → `defaults.agent_machine` → `default` | 显式 → `run_profiles.TOOL` → `dsh-default/pi-base/omp-default` |
| 根 `resume` | 显式 → `defaults.agent_machine` → `default` | 当前范围内已核实会话归属；显式 profile 是硬约束 |
| `agent` 普通目标命令（含兼容 `run`） | 显式 → `defaults.agent_machine` → `default` | 显式 → `machine.default_profile` → 既有回落 |
| `agent instances list` | 显式 → `defaults.agent_machine` → `default` | 仅显式 profile 过滤；省略时列范围内全部受管运行 |
| `term` | 显式 machine → `defaults.term_machine` → `default` | 已选组件；无 profile |
| `work` | 显式 → `defaults.work_machine` → `default` | 项目/type 配置或已有固定 binding；偏好不覆盖 |
| help、`agent profiles/model presets`、独立 usage、`agent lock --agent omp` | 不加载业务机器 | 不注入保存的 profile；OMP lock 用固定公开配方 |

根 `run` 仅给公开 profile 时推断工具；工具和 profile 都缺时，交互列选择，非交互报 2。
`--cwd` 默认为调用目录；环境选项只接收名称，沿用现有环境优先级及秘密隔离。
固定最终目标后调用既有运行层，使用保存的已部署契约。未部署、启动绑定不兼容、
已部署运行包不可用分别失败并给出准确建议。**待部署 runtime 更新本身不阻止仍有效的旧部署运行**；
提示显式预览/部署下一步，不切换版本、不自动 setup/sync/apply/login。

入口偏好仅允许 `schema_version=1`、`defaults.agent_machine/term_machine/work_machine`
和 `run_profiles.dsh/pi/omp`。`config show` 只读非秘密偏好；`set/unset` 是明确保存/清除请求，
按严格 schema 验证，原子替换前复核外部编辑，不因运行或菜单选择自动保存。
损坏、未知字段、符号链接及不安全权限失败，不当作新文件。
偏好存储位置与 `0700/0600` 边界见[数据模型](../data-model.md)。

恢复只在已选 machine/local 内的受限索引查找；session 引用包括工具、backend、
原生 HOME 和原生引用。裸 ID 不全局唯一。省略工具只允许唯一已知匹配推断；
歧义在交互中补范围，非交互报 2；未知 ID 需归属核验，不能跨机器/HOME 搜索、
采用最近会话或新建空会话。`run_profiles`、`default_profile` 均不改写已知归属。
`--here` 为默认位置，位置 flags 互斥；位置选择不改变会话 cwd，目录失效不能用调用目录替代。

## 输入、确认与失败后续

自动交互条件是 `isatty(stdin) && isatty(stdout) && isatty(stderr) && !no_input`。
`--interactive` 在任一标准流非 TTY 时返回 2；不重新打开 `/dev/tty`。
静态 help 优先返回，不读取输入或进入选择器。

根及每级非叶子导航来自命令注册表。完整参数或有效默认直接进入同一执行路径，
只有实际缺项才补齐；`--interactive` 可重选未显式字段，不能覆盖显式约束。
枚举选择须有编号兜底，增强选择器只返回相同不透明 ID；自由文本提示字段规则，
空输入不默认执行首项。取消、EOF 或中断在接受当前动作前返回 130，当前动作零副作用；
此前独立接受的动作保留其真实结果。

统一调用上下文必须传至全部 leaf、work 递归动作、接管确认、隐藏输入、
保存预览、恢复位置选择和失败后的准备菜单。无输入时缺参/缺少等价批准返回 2，
在读取输入及当前未接受动作副作用前结束；已有冲突/未知占用仍按 4 返回。
没有非交互秘密输入接口的命令不新增 argv 密钥参数。

选择目标不等于批准；`--plan-id`、接管证据、`--confirm-zshenv`、work close scope token、
`--accept/--yes` 保留原语义，不能由选择器生成，不增加万能批准 flag。
命令注册表必须声明非交互批准路径；只有交互批准路径的动作在无输入模式报 2。
未部署失败后的“查看计划/准备并部署”是下一项独立动作，只能在同一上下文仍允许输入且
用户明确选择后开始，保留原确认；准备完成后也不自动启动。无输入只输出同范围静态建议。

## 全部叶子命令注册表验收

实现须将下列清单逐叶展开，不能按表中分组只测试一个代表。每个参数声明以下类别：
`E` 枚举、`T` 文本/路径（秘密必须隐藏）、`D` 已有默认、`A` 授权证据、`N` 原生尾部。
每个 leaf 注册用途、scope、参数位置/互斥/重复规则、缺参来源、非交互批准方式、
输出形式、副作用及最短/显式示例。可选参数用声明的 D，缺少必填 E/T 则交互补齐或无输入报 2；
缺 A 绝不靠默认补造。表中“原批准”要求逐项沿用既有规则，并非自动批准。

| 公开叶子（每项独立注册） | 主要输入类别与缺参来源 | 执行与批准边界 |
| --- | --- | --- |
| 根 `run` | E 工具/profile；D scope/cwd；T 环境名称；N `--` 后 argv | 仅已部署启动，不隐式准备 |
| 根 `resume` | E 同 scope 会话/工具/位置；T 明确 ID；D `--here` | 能力与 writer 门禁；默认不发送文本 |
| `config show` | D 偏好路径 | 只读 |
| `config set`、`config unset` | E 允许 key；set 的 E/T value | 完整参数为相应偏好写入/清除请求 |
| `agent init-local` | E/D machine/profile；T schema 字段 | 原保存预览与确认 |
| `agent profiles`、`agent model presets` | D 公开目录；D verbose | 无业务 scope，只读 |
| `agent model status` | D scope/verbose | 只读，不补 key |
| `agent model add` | T provider/model/角色及隐藏秘密；E 协议 | 原校验/确认，无输入缺字段报 2 |
| `agent model key`、`agent model url` | E 当前操作允许 provider；T 隐藏值 | 无等价非交互输入时返回 2，不读 stdin |
| `agent model enable` | E 公开 preset/协议；D 工具默认；T 缺少的隐藏 key | 已有批准与隐藏输入门控 |
| `agent validate`、`agent render`、`agent plan` | D scope；plan 可选 T `--from-pi-home` | 沿用各自离线生成/差异与受管写入范围 |
| `agent lock` | E agent；D 相应 scope | OMP 例外无机器；有意解析/写锁，不是普通修复 |
| `agent sync`、`agent apply`、`agent setup` | D scope；A 原批准 | 安装、部署分明；setup 原组合审阅流程 |
| `agent run` | D 管理 profile/cwd；E 可选工具；T 环境名称；N 尾部 | 不采用根按工具 profile 偏好 |
| `agent usage` | N 全部尾部；显式 scope 在 usage 前 | 保留原生 help/结果及独立调用路径 |
| `agent inventory` | E omp；T 必填 source | 显式只读来源盘点与私人提案 |
| `agent doctor` | D scope；D environment/input；显式 live | 默认离线，不因展示自动启用联网 |
| `agent capture`、`agent rollback` | D scope；A 原批准 | allowlist 捕获/受管恢复，不处理账号会话 |
| `term components` | D 公开组件目录 | 只读 |
| `term init-local` | E 组件；D machine；T 原编辑字段 | 原预览/确认，Herdr 显式 opt-in |
| `term plan`、`term status`、`term doctor` | E/D 组件；T 可选 home；plan 的 T entry-repo | 原只读/诊断边界；入口诊断不启动绑定程序 |
| `term apply` | E/D 组件；T entry-repo；A plan/adopt/zshenv | 原精确计划和接管门禁，换绑需显式审阅 |
| `term recover` | D machine；A 原恢复规则 | 只恢复已记录事务，不猜 checkout |
| `term lock` | E tmux/zsh；T version/plugin/repo/entry；D timeout | 有意解析/写锁，字段按原 schema |
| `term sync` | E 单个 tmux/zsh；D timeout | 消费锁，不扩大到全部组件 |
| `term migrate` | A 必须显式 `--drop-mihomo` | 原元数据迁移边界，不转为普通选择默认 |
| `term rollback` | E 组件；D plan-only；A plan-id | 原恢复审阅与漂移保护 |
| `work enter` | T 项目 path | 原项目选择与进入契约 |
| `work open`、`work rebind` | E 当前允许 type（既有参数名 role）；D new；A rebind accept | 固定 binding、deadline 不变；focus 无重启/改目录/文本注入 |
| `work list`、`work status`、`work reconcile` | D scope/json；list 显式 live | 原观察/对账能力，不猜闲置 |
| `work source add` | T id/path/exclude；E mode/template；D depth/隐藏/跟随/预览 | 原发现数量限制；保存注册与进入分开 |
| `work project add` | T path；E mode/template；D dry-run | 原注册预览，不自动进入 |
| `work named add` | T id/title/start-path；E template；D dry-run | 原命名实例注册 |
| `work named enter`、`work named rename` | E/T 已注册 id；rename 的 T title、D dry-run | 固定身份不变；原变更/部分成功规则 |
| `work config check`、`work config edit` | D scope；edit 的 T schema 字段 | check 只读；edit 原保存预览/确认 |
| `work worktree create` | T repo/path/new-branch 或 existing-branch/base；E template；D enter/dry-run | 分支模式互斥；创建与进入独立接受 |
| `work close` | D dry-run；A scope token + yes | 原单工作区精确关闭；不得默造 scope |
| `agent instances list` | E 可选 agent；显式 profile 过滤；D scope/format | 阶段二只读观察，未知项保留 |
| `agent instances stop` | E/T 显式 run 集合；D dry-run/wait；A plan-id | 阶段三：只读计划与实际停止共用精确输入 |
| `agent maintenance plan` | D setup operation 或 T batch；E/T run/session 映射；D scope | 只读，不建批次/准入意图；先核验目标完整锁的恢复准入 |
| `agent maintenance stop` | D setup operation；E/T run/session 映射；A 当前 plan-id；D wait | 复算目标/资源快照；接受后才持久化批次 |
| `agent maintenance execute` | T batch；A 每次最新 setup plan-id 或独立交互批准 | 退出与资源释放门禁、恢复能力重核；普通 setup 重新检查当前状态 |
| `agent maintenance restore` | T batch、run（TTY 可选）；默认 here，可显式 original/new-tab 候选 | 同日常恢复身份/writer 门禁；每次一项，不共用 stdin |
| `agent maintenance status` | T 现存 batch；D scope/format；旧 OMP Domain 批次须显式 profile | 三工具 workflow 查询；旧停止/Domain 批次沿原查询路径 |
| `agent maintenance cancel` | T batch；D scope | 三工具 workflow 先保存取消事实，再按原停止协议安全收尾；旧 OMP Domain 批次不迁移或开放新取消能力 |

`instances`、`maintenance` 及全部嵌套命令组无子命令时有该层导航；能力未准入的项须标限制。
`_complete` 是唯一内部叶子，亦须注册静态 help、参数 schema 与零副作用策略。
将来增加叶子必须同步本表、help/补全元数据和缺参/确认/失败路径的输入门控测试；
注册表对实际 parser 叶子集合做双向比较，漏项与过期项都失败。

## 帮助、输出与退出状态

每级 help 含用途、synopsis、直接子命令、完整参数位置与必填/互斥/重复约束、默认优先级、
输入条件、最短与显式范围示例、联网/写文件/启动/接管/恢复影响。仓库 `./rotom ... --help`
不读偏好、机器、密钥或会话，不联网、写状态或启动宿主。已部署 launcher 只允许在安装定位层
从自身受管安装文件的固定布局定位唯一的最小非秘密 `entry.json`，不依赖调用者 HOME、XDG 或 cwd
选择绑定。部署使用保存的 target HOME；定位细节见[入口部署契约](entry-deployment.md)。
绑定损坏给安装诊断，不扫描其它 checkout。

`agent` 原结构化命令保持 `--format auto|human|json`，`term/work` 保持各自 `--json`。
提示、进度、选择器及脱敏失败建议进入 stderr，stdout 保持原结果 schema；不强行统一 schema。
建议保留实际 machine/local、profile、component、batch 和批准需求，不包含秘密或原始会话正文。
控制结果同时保留原维护退出码与逐项事实；聚合失败不能覆盖已派发维护的原结果。

| 退出码 | 语义 |
| --- | --- |
| 0 | 管理动作成功，可有漂移/待登录提示 |
| 2 | 参数、配置、锁错误；缺参、缺非交互批准、交互条件不足 |
| 3 | 所需凭据缺失 |
| 4 | 所有权/活动冲突、计划漂移、未知控制结果或恢复待处理 |
| 5 | 依赖/原生检查失败、缺运行包或已明确的能力未准入 |
| 6 | 文件系统或内部操作失败 |
| 130 | 尚未接受的交互被取消/中断 |

原生进程成功交接后保留其退出状态，不重写为管理器成功。
阶段一 `resume --help` 为静态 0；非交互缺少必要工具/会话或范围歧义为 2，
参数完整但能力未开放为 5。静态 stub、离线 fake 均不计 R8/故事 4 完成。
阶段二首先真实验收 DSH 当前终端官方恢复交接、指定历史和 writer 冲突拒绝；
缺严格加载回执不禁止已准入的交接，输出明确区分“请求 session”“已派发”“加载待确认”“未发送继续”。
机器没有证据时不得显示“恢复成功”。用户在官方 TUI 自行确认和输入，不增加“强制标记已恢复”的开关。
Pi/OMP 当前终端交接按本轮工具方案验收。普通 `--session` 的 `--original`/`--new-tab` 尚未开放；拒绝时给出同范围可复制的 `--here` 命令，保留能力未准入退出码 5，不污染结果 stdout。

Herdr 新标签页和受支持 Rotom Herdr 新托管实例原 pane 已有候选实现，最终十二组无 trace 原生验收全部通过，现仅开放六个精确 Linux managed 组合的两种位置。驻留包装覆盖 Herdr V1/V2 的新 DSH/Pi Agent 启动和符合驻留组合的新 tab 恢复；普通 shell 单次 run 退出返回。旧普通/直接官方实例不升级，launcher 或 pane 丢失时使用当前终端或明确接受的新位置。help、命令提示与只读诊断/停止计划说明条件、可用/不支持/丢失/未知和下一步；静态 help 不查询 Herdr、私人配置或启动程序。新标签页创建和恢复交接逐项展示，可能已创建时不重复开页。

位置入口仅接受已停止且已完成 setup/update 的完整 maintenance workflow；普通 session 和旧 stop 快照不得绕过来源门禁。`maintenance restore --batch B --run R` 也接受互斥的 `--here/--original/--new-tab`，默认 here。

`--all` 必须与 `--stopped --batch B` 及非 here 位置配合，不能带 `--run/--session/--list/--here`；缺 batch 即 2。先核验批次所有项同范围、可恢复且来源完整，坏记录或不可恢复项拒绝整批，不静默过滤。分发前逐项重查，独立终端、独立意图，不让多个 TUI 争 stdin。JSON 只输出一个 batch 汇总，保留每项 run_id、exit_code 与 result；首个非零或未知后停止，后续为 not_dispatched，保留先前事实，汇总返回 4，全部交接返回 0。`--list` 保持只读且不能带任意位置或 `--all`。

统一严格加载回执、原生 TUI 自动继续与 Pi Pro 委派本轮不承诺；`pi-pro` 普通 profile 的维护/恢复兼容性保留。位置选择不放宽原范围、精确会话、目录、部署、取消与已派发防重门禁，加载待确认仍为零自动输入。T134 的提示验收不能代替 T085/T087–T095 和 T135–T138 的生产实现/原生验收。

人工继续指引使用既有根 `--interactive`，不新增自动发送参数。默认完整参数和 `--no-input`
不增加输入步骤；显式交互可跳过指引、选择固定“继续”示例或输入自定义单行文本。
文本最多 4096 字符且 UTF-8 不超过 16384 字节，不接受不可打印字符；保留合法文本的首尾空格。
先展示当前请求目标与加载未确认边界，再预览文本并单独确认“仅展示供手工复制”；取消发生在派发前。
文本只存在于该次指引局部内存和必要终端展示，不传给恢复后端、日志、清单或 JSON。
用户须自行核对官方 TUI 的会话 ID、目录和历史，再聚焦输入框复制；不调用剪贴板、聚焦或按键程序。
日常 resume 尚未准入时仍可查看这项人工指引，但成功展示不改变其退出码 5，也不成为加载或发送许可。

当前终端的交接提示进入 stderr，保留原生 stdio 与最终退出码；原生退出码 0 不是加载确认。
维护 restore 同样保留已知原生退出码，包括 0，同时保留加载待确认；退出结果未知才返回 4 并保留未完成意图，不自动重试。
停止完成后的最终 status 查询沿原停止 deadline 等待纯读短锁；过期后只允许无竞争 NB 观察，仍不能确认时保留 unknown 与落盘事实，不再次 close、发布或发送信号。独立 status 保持默认 NB。

只读 status 的退出码反映阶段记录可否查询及停止/setup/restore 是否仍无确定结果；停止 pending、未完成的 setup-intent/restore-intent 均返回 4，cancel 不能盖住这些事实。已知原生退出结果仍保存在原阶段记录，不把加载待确认或原生 0 升格为 restored。
确认等待超时仅停止后续自动步骤，不终止已交接的交互会话；显式已知失败保留原错误及退出码。

普通 stop 与维护复用同一精确目标计划：dry-run 不建批次，stop 重复原 scope、run 集合、
operation（维护时）和 plan ID，复核后才能接受；不能仅拿摘要猜目标。
首版维护 `operation` 仅准入 `setup`；普通实例停止的计划 operation 为 `stop_only`。

当前候选按工具的公开路径为 `maintenance plan --run ... --session RUN_ID=SESSION_ID` → `stop` → `plan --batch BATCH_ID` → `execute --batch BATCH_ID --plan-id SETUP_PLAN_ID` → `restore --batch BATCH_ID --run RUN_ID`。`--operation setup` 可省略；plan 的 `--batch` 与 `--operation` 互斥，batch 计划不混入新的 run/session 集合。run/batch 为完整 32 位小写十六进制，重复 run 或重复会话映射拒绝。

TTY 可补选择并在锁外展示批准；非 TTY/根 `--no-input` 需完整 run/session 与 stop/setup 各自当前 plan-id，缺失 2、漂移 4。选择不等于批准；stop 前先保存清单及同 ID 快照/fence，单次请求原 host pidfd，等待未知保留事实为 4，不强杀或重发。DSH/Pi/OMP 精确 stop_only 不因未选共享引用覆盖未知单独拒绝，但必须披露；普通 setup 全资源门禁仍拒绝未选引用/unknown。

停止确证并关本次 fence 后独立预览/批准普通 setup，不携带跨阶段写入许可；并发新 run 可阻挡但不加入停止集合。保存原维护结果与码，unknown 不重试。restore 只接一项当前终端，保存请求与实际加载的区别、加载待确认、`continue_status=not_sent`。Pi 仅 Rotom 合作 writer 租约，原生 --resume 是 picker，受管完整 ID 转精确路径；OMP 同 ID open 不取 writer 锁，竞争首次写入可能分叉。请在官方 TUI 核对 ID，不能宣称外部 writer 提前拒绝或自动 restored。

cancel 只终止后续编排，不撤销已发生停止/配置，不强清已投递或 unknown 的保护。旧 stop 批次沿原 status/cancel；旧 OMP Domain 批次保留以下只读路径，不迁移/重放为新 workflow。详细示例与候选状态见[维护指南](../../../docs/tool-maintenance-workflows.md)。

Linux OMP 的 `maintenance status` 已接通只读 setup 批次查询：必须提供现存 `--batch` 和显式
`--profile`，由公开 profile 声明的工具为 `omp` 决定路由，不按名称前缀或 `scope.agent` 猜测。
沿原 `--local` 或所选机器配置路径读取，不扫描其它机器、历史路径或自动发现批次/profile；
没有显式 profile 时仍走原 DSH 查询。对这些旧 Domain 批次 status 不调用 stop/execute/restore/cancel；新 workflow 批次独立分阶段处理。

```sh
./rotom --no-input agent --local /path/to/machine.toml --profile omp-default maintenance status --batch BATCH_ID --format json
```

`BATCH_ID` 须替换为现存的完整 32 位小写十六进制 ID。`auto/human/json` 都不读 stdin、
不写入或控制宿主；JSON 的 stdout 只有一个对象，限制说明进入 stderr，human 转义终端控制字符。
输出保留原 `operation_result` 与独立的查询 `exit_code`、逐项 stop/restore 和现场 observation；
`protected` 只表示本批资源意图是否仍阻挡，不证明全局资源空闲。原维护成功但尚未交接返回 4；
completed 且当前目标/资源核验通过返回 0；unknown/pending 返回 4，既有非零 operation result 保留原码。
初始未派发即取消且正常只读观察返回 0 仅表示取消，异常观察仍为 4。manual 不表示已恢复，
`continue_status=not_sent`；`next_commands` 只给同一精确 local/profile/batch 的 status argv。

其它原有命令仍可独立调用；扩展维护操作须单独完成资源闭包与恢复审查。
控制等待 `--wait-seconds` 默认 30，范围 1–300；整个所选集合共享一个阶段的绝对单调 deadline，
不按 run 重置。耗尽返回逐项事实和下一步，不强杀、不自动进入 execute/restore。
该等待预算不限制整个 setup 安装耗时，也不限制明确交接到当前终端后的普通会话交互寿命。
维护仍要求原全资源释放证明；交接须核实各工具实际 writer 语义与精确目标。自动输入的完整排他/加载/接收证明不足时保持零发送；原 pane、continue 各自独立门禁。
停止不具备自动恢复证据时只能明确说明人工恢复。详细批准及状态机见[生命周期契约](lifecycle.md)。

## `_complete` 协议

```text
rotom _complete --kind KIND [--namespace agent|term|work]
                [--tool TOOL] [--profile ID] [--machine NAME | --local PATH]
                [--command REGISTERED_PATH]
```

`--command` 的值是注册表内的命令路径，不接受 shell 表达式、完整 argv 或原生尾部。
静态命令/参数由注册元数据直接提供。动态 kind 仅允许下表；其它值报 2。

| kind | 唯一允许来源 | 范围与降级 |
| --- | --- | --- |
| `profile`、`tool`、`preset`、`component`、`preference-key` | 公开目录或注册元数据 | 按命令/工具过滤，不读取业务机器 |
| `machine` | 相应 namespace 配置目录的安全普通文件名 | 只给合法 ID，不打开其它机器正文猜默认 |
| `provider` | 明确 agent machine/profile 中该操作允许的 provider ID 字段 | 不解析 SecretRef，不返回 URL/key |
| `work-type`、`work-template`、`work-source`、`work-named` | 已选 work 配置对应非秘密 ID 字段 | 不连 live endpoint；候选不证明可创建；项目路径不作为 ID |
| `session` | 同范围受限会话索引 | 阶段二准入后启用，按 tool/显式 profile 过滤；不扫描会话正文 |

stdout 为 UTF-8 合法 CLI ID，每项末尾一个 NUL；空候选输出零字节，无标题、JSON、描述或路径。
zsh 按值处理，禁止 `eval`。正常缺数据/索引不存在为 0 + 空候选；非法查询/读取失败为非零
且空候选，前端静默退回静态补全，不输出原始异常。诊断如需 stderr 只能为静态脱敏错误。
查询不读独立秘密/原生认证文件，不联网、不启动程序、不建索引、不写缓存/日志或修复配置。
`--` 后停止 Rotom 补全；没有候选不启动向导，普通交互页另行说明手动输入途径。
