# Quickstart：Pi Base/Pro 分层验证

官方 CLI 薄适配及 `pi-base` / `pi-pro` 已有实现。实现状态与验收证据分别见
[实施状态](implementation-status.md)和[验收记录](acceptance.md)。本指南只描述操作，
Linux x86_64上的显式锁解析、T036及退役后T048双路径管理重建已有通过证据；
T037/T038与状态栏T058/T059已按记录的Linux范围完成，包括有界真实工具与用户接受的三处状态差异。Pro按用户决定等待合格社区上游，仍为`not_ready`；Brave/Cursor真实账号验收延后。完整feature保持未完成，最新范围见[本轮交付验收](current-delivery-acceptance.md)。

先阅读[规格](spec.md)、[实施计划](plan.md)、[数据模型](data-model.md)、
[公共管理契约](contracts/common-management.md)、[运行与模块契约](contracts/pi-runtime-and-modules.md)
和[退役与证据契约](contracts/retirement-and-evidence.md)。

## 1. 前提与证据边界

当前组合为未修改的 `@earendil-works/pi-coding-agent@1.3.0`，可选的锁定主题来源为
`catppuccin-pi-theme@0.1.6`。Node >=22.19.0 是机器前提，维护使用固定 npm 11.9.0；
`run` 不会自动下载工具链。首轮平台范围为 Linux x86_64，其它平台需独立证据。
使用 Git、Python 3.11+ 和仓库 `.venv`；仅在开发环境缺失或需重建时显式运行
`uv sync --frozen --group dev`，该步骤可能联网。

| 层级 | 操作 | 能证明的范围 |
| --- | --- | --- |
| 隔离检查 | pytest，临时 HOME、阻网与假进程 | 配置、依赖、部署与启动契约；不证明原生加载 |
| T036 依赖重建 | 同候选同锁，两个独立路径显式 sync/apply | 完整锁消费、内容核验及部署幂等；不得启动宿主 |
| T037 原生 | 独立授权后的官方宿主与终端验证 | 所记录平台上的加载、资源、会话与交互 |
| T038 账号/模型 | 另获授权后的实际绑定与调用 | 实际账号、模型及工具场景；虚构端点无此证据 |

离线 `doctor` 分别报告配置、依赖、部署、加载、账号和运行证据。依赖 installed 不表示
加载、账号或运行通过；`doctor --live` 只增加 reachability，不提高这些阶段的证据层级。
`setup` 会执行 sync + apply，不用于只读检查。`--local` 与 `--machine` 互斥，
全局选择器放在子命令前，`lock --agent pi` 的 agent 参数放在子命令后。

## 2. 当前隔离入口

以下命令从仓库根执行；具体运行结果见acceptance，不将入口列表作为通过结果：

```sh
.venv/bin/python -B -m pytest \
  tests/test_pi_reboot_configuration.py \
  tests/test_pi_reboot_dependencies.py \
  tests/test_pi_reboot_runtime.py \
  tests/test_pi_reboot_pipeline.py -q --tb=short
```

[conftest.py](../../tests/conftest.py)提供临时 HOME/XDG、网络阻断与假进程。
公共模块变化还须运行受影响的 DSH/OMP 契约；不能仅凭 Pi 专属测试宣称公共回归通过。
文档检查使用 `.venv/bin/python -B scripts/check-public-docs.py` 与 `git diff --check`，并直接核对未跟踪文件和feature相对链接。

## 3. 私有绑定与依赖选择

使用新 [Base 示例](../../examples/pi-base.local.toml)或
[Pro 示例](../../examples/pi-pro.local.toml)。只支持 `roles.main`；不要复制旧角色或旧 profile。
示例模型和端点是虚构的，空 key 不构成账号就绪。将样例复制到私人目录（目录 0700、文件 0600），
例如设置 `demo_local` 指向该私有文件；不要读取或复制真实旧 auth、model、session 或任务库来构造样例。

```sh
demo_local="/private/config/pi-base.toml"
./agentcfg --local "$demo_local" --profile pi-base lock --agent pi
./agentcfg --local "$demo_local" --profile pi-base validate
./agentcfg --local "$demo_local" --profile pi-base render
./agentcfg --local "$demo_local" --profile pi-base plan
```

示例路径须替换。`lock` 是显式来源解析，会写仓库完整锁且可能联网；须先审阅来源与脚本。
缺锁或当前选择失配退出 2，禁止为了取得退出 0 跳过检查。
规则、完整 Skill 内容、prompt、theme 与 builtin 选择都绑定依赖 recipe；更改这些实际输入后，
必须以上述同一 `--local ... --profile pi-base lock --agent pi` 显式重锁。
模型、editor、UI 不进入 npm recipe，仍需对应配置/启动审阅；后端语义变化也不能因摘要未变省略重验。

消费时仅核对当前 profile 的实际选择与资源，另一 profile 的资源变化不使当前 slice 失效。
当前显式 lock 会重建两个 slice：所选 profile 使用有效机器覆盖，另一 profile 使用公开默认值，
不保留它以前的机器覆盖。发布前审阅两个 slice；需要另一组覆盖时明确选择其绑定重锁。
`resources.themes=[]` 会排除该 profile 的主题 npm 包。builtin 默认空，仅允许
`builtin:codemode` / `builtin:tool-search`。外部选择仅开放固定`cache-hit-monitor`、`pi-context7`、`pi-brave`；
默认均空。`builtin:mcp`仅随已选服务自动显式加载；其余候选和协作启用仍明确拒绝。

## 4. T036：同候选同锁的两个路径

依赖准备步骤可在已授权维护范围内执行，不包含原生宿主启动。先审阅包含实现、资源和完整锁的
稳定候选，记录其提交与锁身份，再准备两个不同仓库路径和独立 HOME/XDG、machine id、实例目录。
不提供旧 Pi home，不链接旧缓存；不要复用指向另一副本的 editable `.venv`。本轮使用同一已准备Python的`python -B -m agentcfg`加每副本PYTHONPATH进入，未重建Python工具链；后续若改变这一前提须重新记录。

可用 `git archive` 将同一已审阅提交展开到两个路径；候选占位符须替换：

```sh
candidate_ref="REPLACE_WITH_REVIEWED_COMMIT"
# 先自行创建两个隔离目录，并分别准备开发环境与私人样例绑定。
git archive "$candidate_ref" | tar -x -C "$demo_repo_a"
git archive "$candidate_ref" | tar -x -C "$demo_repo_b"
```

每个副本分别使用其临时 HOME/XDG 和本副本的 `.venv`，以显式私有绑定逐行执行：

```sh
./agentcfg --local "$demo_local" --profile pi-base validate
./agentcfg --local "$demo_local" --profile pi-base render
./agentcfg --local "$demo_local" --profile pi-base plan
./agentcfg --local "$demo_local" --profile pi-base sync
./agentcfg --local "$demo_local" --profile pi-base apply
./agentcfg --local "$demo_local" --profile pi-base plan
./agentcfg --local "$demo_local" --profile pi-base apply
./agentcfg --local "$demo_local" --profile pi-base doctor
```

两个副本消费同一锁，不各自重解析。任一步失败停止受影响后续操作并记录真实退出码；
`sync` 联网获取并核验完整锁，`apply` 只部署配置，都不能启动 Pi、登录或调用模型。
缺损依赖退出 5，未知安装脚本不得激活。不通过手改生成文件、删除 owner 或引用旧缓存绕过。

比较精确宿主/主题、选中资源、profile 运行身份、完整锁摘要、资源相对引用与原生配置语义，
仅忽略声明过的机器标识及实例绝对路径差异。最终 plan 应无待部署变化，重复 apply 不轮换备份。
核对另一路径及其它工具未被改写，记录生成文件手改次数为 0。本轮实际命令、规范化范围和两套来源摘要见acceptance的T036/T048；本节仍是供后续候选重做的步骤，不证明未来版本通过。

## 5. 所有权、旧状态与停止条件

UI 仅初始化合法所有权边界内的新/缺失偏好；后续原生主题选择限同一锁源的四个 Catppuccin 名称，
未知值明确拒绝并保留原文件。全局 packages 非空（含对象声明）会阻止受管启动；资源禁用 flags
不是 OS 沙箱，项目 AGENTS.md 上下文仍存在。账号、trust 和 sessions 均保持本实例原生归属。

每个主运行有独立 owner。active 或 unknown 阻止独占维护；同 binding 新运行可以登记，
不会删除已有 unknown 或证明旧后代退出。Linux在spawn前建立child subreaper覆盖，
只有内核确认无任何子进程时才释放本次active记录；后代存活、观察失败、平台不支持或管理器
异常退出仍保留保护。时间、父退出或人工口头确认不能清除它。

旧 activity/lease 内容和 worktree owner 按不透明归属保护，不能删除标记使新配置启动。
[迁移指南](../../docs/pi-migration.md)中的 `plan --from-pi-home` 只生成私有元数据计数提案，
不读取认证、模型正文或会话正文，不自动接管或复制模型；starter 比较不受支持。
旧执行平台、旧 profile 与旧 recover 路由不能用作新组合修复入口。

冲突、pending、活动/未知归属和未准入模块须停止受影响操作。配置 rollback 与 pending 恢复只恢复受管配置，
不降级软件、不迁移数据库、不重放任务。不要自动终止进程或扩大所有权。

## 6. T037/T038：已验证范围与后续授权

原生测试须先审阅实际 argv、候选、锁、平台和允许资源，再显式执行 `run`；它不能隐式 lock、sync
或 apply。T037 分别验证官方资源清单、主题/editor、会话目录、SSH/tmux/中文交互及多主运行保护。
已有自有Python的double-fork/setsid探针通过。另经明确授权，A默认宿主/主题、B仅footer、
C仅缓存诊断三组已实际通过version/help和tmux3.5a的60/90/130列中文多行bracketed粘贴、
Ctrl+C清除、reload及Ctrl+D退出0。A另通过真实宽度裸PTY并保留原生Frappe主题选择；
双主运行时apply退出4，退出一个仍为4，全部退出后为0。B的菜单保存禁用偏好经重建逐字节
保留，恢复显示后修订observer的provider标签、菜单prompt→idle及reload通过；C的显示/隐藏
与reload恢复默认隐藏无残留。最终A6/B4/C3条owner均idle_confirmed，active/unknown为0。

上述首次三组均为新临时实例、虚构provider/model及合成占位key，每次宿主进入新网络namespace，
仅loopback且无路由；该检查点0真实登录、0模型请求。后续共享默认模型、真实usage、D–G
局部原生/服务与性能检查见[补充验收](remaining-native-acceptance.md)。后续回环SSH实际传输/PTY、
运行中模型取消与恢复已有证据；非root服务端exit255限制保留。真实远端机器、macOS和实际账单
未验，不外推；原T037/T058没有另要求必须使用真实远端机器。

T038 已获复用共享默认模型/SecretRef的授权，且要求密钥不被模型读取；普通真实请求禁用全部
模型工具。另经明确一次授权，合成文件保护器下的读写检索与固定printf通过，越界读取执行前
阻断；该保护器只用于验收，不改变生产权限或CLI参数白名单。模型切换、继续/分支/压缩通过；
分列请求模型、所选模型和可确认的实际模型；无法确认标 unknown，虚构端点不可用于调用。
Pro 协作与未准入模块另有验收门，不能包装新调度器或修补宿主补齐。

每次记录候选、目标 main、锁身份、平台/工具链、实际 argv、退出码、预期/实际结果与脱敏日志位置。
未执行、失败、环境不足分别记录，不将本指南列出的命令当通过证据。
退出码为 0 成功、2 参数/配置/锁、3 缺凭据、4 所有权/活动/恢复、5 依赖/原生检查、6 文件系统/内部错误；
已启动宿主的原生退出码单独保留。公开证据不含真实凭据、账号/session 正文或私人绝对路径。

## 7. 当前交付和延后工作

Powerline0.20.2仍held；公开API替代pi-footer0.5.1的准入/接线、原生检查和信息门已完成。
权限不可查询的详情说明、分支输出均速、窄屏统计放详情三处差异获得用户明确接受。
真实账单仍unknown，不把没有价格来源的字段补零，也不将权限说明当作权限保护。

按需模块的所选组合、六场景与性能结果见[本轮交付验收](current-delivery-acceptance.md)及
[准入登记](module-admission.md)。默认不加载外部模块，选择变化须显式lock/sync/apply；
隐藏widget不等于禁用，禁用也不删除账号/缓存或自动终止已有进程。两种方法Skill不增工具或后台，
其他未注册候选仍不可启用。Brave/Cursor真实账号验收按用户决定延后，既有失败和未验证记录保留。

Pro T064–T071缺合格社区候选，继续not_ready；不自建调查执行器或降低原边界。
Linux子后代观察已实现，旧unknown或覆盖不完整继续阻断维护，不能手删owner绕过。
完整feature T096保持未完成，不归档、不自动提交或合并。
