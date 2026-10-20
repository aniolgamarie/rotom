# Quickstart: Herdr 分层验证指南

这是已实现入口的分层验证指南；代码、隔离检查及原生分项状态见 [implementation-evidence.md](implementation-evidence.md)。隔离Linux核心和部分工具入口已验收；真实客户端、完整账号/模型、性能基线和生产切换仍有缺证。接口以[配置契约](contracts/configuration.md)与实际CLI为准。

默认测试只使用仓库内/临时HOME与fake host。原生及账号/模型smoke按对应授权范围执行；用户已授权本轮续验收，并指定本机为唯一测试环境，实际执行了证据列明的隔离Herdr、回环SSH、Avalon、DSH及Codex分项。剩余项为完整CPU统计/校准/首基线及推广前置；macOS26.6.2/Ghostty1.3.1 stable八步和受管Pi期限修订后双实例已完成，不以缺少重复授权或另找机器解释。通过一层不代表其他层验收完成或生产切换安全。

## 1. 准备与离线验证

从仓库根使用已准备的Python >=3.11 `.venv`，不使用隐式安装入口。Linux端点固定依赖procfs/O_PATH，应先用自有临时Unix socket验证能力，缺失退出5，不降级到按路径重连。支持声明仍须绑定实际服务器平台与客户端组合；已验macOS客户端不代表macOS服务器支持，其他组合不能外推。

先核对 [spec.md](spec.md)、[data-model.md](data-model.md)、[work-cli](contracts/work-cli.md)、[configuration](contracts/configuration.md) 和 [benchmark](contracts/benchmark.md)。准备虚构Git项目、linked worktree、空格/中文/引号路径、非Git目录和状态哨兵；不能复制真实账号、会话或业务checkout到fixture。

默认隔离检查：

```sh
.venv/bin/python -m pytest tests/test_work_identity.py tests/test_work_context.py tests/test_work_roles.py tests/test_work_launch.py tests/test_work_recovery.py tests/test_termcfg_herdr.py tests/test_herdr_benchmark.py
```

这些测试文件已实现，具体执行结果见实施证据。测试隔离HOME/XDG、阻断网络、替换子进程/native API并验证秘密哨兵，不启动第三方宿主。实际argv只保存在仓库外0700/0600私人执行记录；公开验收记录保存normalized_argv、逻辑路径标签、原件digest/evidence_ref、退出码、候选/target/锁/环境类别，不将归一化数组称原始argv。

至少验证：

- Git子目录/symlink归一，linked worktree分离；非Git在server副作用前退出2；空格/中文/元字符按字面处理。
- 重复100次及并发2/10调用无重复项目、无错归属；普通用途复用100次新增输入为零，显式新增10次不替换已知primary。
- 外部或未知上下文普通open与`--new`各10次均退出4，无创建/启动/接管/自动连接；冷恢复unknown默认退出4、显式新增只建立该用途新primary。
- 移动/关闭/ID复用/换server、超时与创建响应丢失先只读对账，不盲目重试。未决pending阻止新建（包括--new），不覆盖/自动超时回收；已确认primary可只聚焦。冷恢复无pending时unknown的--new规则不变。
- pending恢复按[runbook](contracts/work-cli.md#pending-recovery-runbook)：唯一同op已证明failed/accepted则enter登记，不重启；持续未知时用原生tab继续工作，待全部任务自然结束并另获停服授权再冷恢复，不自动结束任务清标记。
- 配置未知字段失败、非受管文件/旧state/pending与恢复边界保留；五次无变化部署不重写、不轮换备份。
- benchmark拒绝未知字段、null当0、producer不足、未校准policy、缺必需数据、不可比输入和虚构首轮A/B通过。

## 2. 显式选择与预览配置

以下命令为显式部署入口，本轮没有在真实HOME执行。为示例机器准备独立私人配置；本指南只写通用标签，不公开私人文件正文或位置。已有本地配置不得通过重新初始化覆盖，按[配置契约](contracts/configuration.md)显式增选组件。

```sh
./termcfg init-local --component zsh --component herdr
./termcfg plan --component herdr --json
```

`init-local`不是软件安装；`plan`离线显示声明目标、采用要求、冲突及稳定plan ID。审阅计划后，将实际返回的ID原样传入：

```sh
./termcfg apply --component herdr --plan-id ID
```

`ID`在此表示上一条实际返回的计划标识，不是可直接复制的固定值。部署不得安装binary、停止活动实例或接管整个配置目录。已有私人Herdr文件需要显式采用；不以覆盖解决冲突。未选择Herdr的机器继续原有zsh/tmux行为。

只拥有声明的Herdr配置文件。默认静态配置设 `terminal.default_shell="rotom-work-shell"`、`terminal.shell_mode="non_login"`；新server的PATH必须包含仓库根且launcher来源通过检查。`work`启动新server时提供这一PATH，不修改全局shell。已有server未继承PATH时须明确准备/验证，不能假定写了文件即生效。异常HERDR_CONFIG_PATH/XDG指向、旧pending或目标漂移先按配置契约报告/恢复。

编辑器复用 `machine.editor` 的单一executable；`machine.work`只选择binary/session及已准备的Pi/DSH配方、独立Codex策略。不得另建编辑器配置体系，shell/edit不解析SecretStore。此阶段不运行Avalon/Agent。

## 3. 获授权后验证原生人工终端

仅在用户明确授权原生Herdr测试后，准备未修改官方发行的独立版本化资产、隔离HOME/XDG/socket与专用server，核对资产摘要、磁盘client、实际server、有效配置和公开能力。核对最新stable属于显式选版，不是日常启动联网。当前研究候选不是永久版本限制或通过证据。

使用合成Git项目演练以下接口，路径按字面传入；`"fixtures/项目 space"`代表事先创建的虚构Git checkout：

```sh
./work enter "fixtures/项目 space"
```

machine/local选择在子命令之前，且互斥：

```sh
./work --machine test-machine enter "fixtures/项目 space"
./work --local fixtures/machine.toml enter "fixtures/项目 space"
```

`enter`创建/复用已确认项目，只建立必要初始终端，不自动启动editor/Agent。已在确认项目归属的Herdr终端内，再验证：

```sh
./work open shell
./work open build
./work open debug --new
```

shell/build/debug只打开人工交互终端，任务由人输入。已有用途只聚焦，不能发启动文本、改目录或重跑程序。Herdr外部的`open`连同`--new`必须退出4并提示先enter。共享server的焦点会影响其他client，不能把全局活动项当成调用终端归属。

用合成输入记录器验证C-x字面输入、中文、Shift+Enter、编辑器组合键与20轮resize/切换。分别验证client detach、SSH中断、启动shell退出后原合成进程存活；主动停止server只检查布局恢复边界，不能声称原进程恢复或重放任务。真实SSH/客户端组合须另获对应授权并逐组合记证据；OSC52只写已知合成文本，由人到测试文本框确认，不发送剪贴板读取请求、不读取原剪贴板。纯PTY证据不能替代真实终端交互。

## 4. 获对应授权后验证编辑器与Agent

先确认所选独立Avalon、Pi/DSH配方、独立Codex入口已准备、部署且身份正确。需要真实账号或模型调用时另获明确授权；无账号smoke不能替代真实调用证据。缺少准备应失败，不能自动安装、部署、登录或换配方。

在已确认Herdr项目内分别执行获授权用途：

```sh
./work open edit
./work open pi
./work open dsh
./work open codex
```

启动仅能发生在新建且提交握手成功的pane，经 `rotom-work-shell` 重建固定argv并exec；已有用途仍只聚焦。底层复用现有入口，参数顺序是 `./agentcfg [selectors] --profile PROFILE run pi|dsh --cwd ROOT`，selectors必须在`run`之前，不新增Codex配置适配器。独立Codex默认不共享daemon，不改变Pi委托或已有daemon。

逐项核对实际checkout、配置/账号/state身份，无额外安装或迁移。Avalon审查只在用户显式刷新后交接选定文件到同checkout的明确目标，关闭审查保留已保存导出。关闭所有状态增强后重跑核心流程；状态提示不得判定任务完成、发送操作或清理终端。某项无法在现有权限内接入则保持关闭，不扩socket/终端控制权限。

## 5. 显式基准与首轮校准

命令接口、schema字段与判定以[benchmark契约](contracts/benchmark.md)为准。先准备合成manifest及冻结政策；以下使用相对文件标签，不表示本轮已生成这些文件。离线validate/compare无需启动宿主：

```sh
.venv/bin/python tools/bench/herdr_upgrade.py validate --manifest bench/manifest.json --policy bench/absolute-policy.json
```

第一轮无已验收A时，先冻结绝对预算、fixture、3batch采样和校准方法。取得原生基准授权并证明隔离后，同candidate重复测噪声：

```sh
.venv/bin/python tools/bench/herdr_upgrade.py calibrate --manifest bench/manifest.json --policy bench/absolute-policy.json --subject candidate --allow-native --authorization native-bench-approval-01 --output bench/calibration.json --policy-output bench/calibrated-policy.json
```

`native-bench-approval-01`是脱敏授权记录标签，必须对应已取得的授权，标志本身不能授权。校准输出policy须审阅批准并冻结摘要，不能按候选成绩放宽绝对预算；下文假定批准版本保存为 `bench/policy.json`。后续使用新输出文件名，不覆盖已有证据。

```sh
.venv/bin/python tools/bench/herdr_upgrade.py run --manifest bench/manifest.json --policy bench/policy.json --subject candidate --scope first-baseline --allow-native --authorization native-bench-approval-01 --output bench/candidate.json
.venv/bin/python tools/bench/herdr_upgrade.py compare --manifest bench/manifest.json --policy bench/policy.json --candidate bench/candidate.json --output bench/decision.json
```

首轮只评价正确性、必需数据、已校准绝对预算；实际通过对应范围验收后才能形成首基线，不声称A/B升级回归通过。后续有已验收A时，冻结分别用于runtime与full-stack的manifest，按同机预注册顺序一次配对采集：`run --subject candidate --scope runtime --output bench/candidate.json --paired-output bench/baseline.json`（其余manifest/policy/授权参数同上），full-stack另建对应manifest与报告。compare增加`--baseline bench/baseline.json`；不能先跑完整A再跑完整B冒充交替采样。两种范围分别输出报告，不把配置/规则/集成变化归因到程序本体。

合成终端负载通过专用测试machine.editor指向固定fixture executable，再在确认项目内open edit --new启动；不扩大生产work接口、不代表Avalon验收。fixture从checkout根 `.rotom-bench-v1.json`读取本轮严格mode/seed/runID/control_dir配置，实例按已确认pane映射；文件在启动前固定，不同mode/batch/run使用新checkout。ready/start barrier对齐单调窗口，detached在测量start前全部断开；runner stdout输出不是Herdr终端负载。

完整首轮包括idle/output 1/10/30、3×3×3=27项目终端、detached-30、clients-size和churn-leak。每workload三个batch，每batch预热60秒、测量300秒；每暖路径每batch>=200样本，合计>=600。输出每终端128 bytes（含LF）×512lines/s×300s=19,660,800bytes，producer不足整run无效，不可换低CPU成绩。

正确性与所选latency/CPU/RSS是必要证据；wakeup/PSS不可用逐项null+reason标未验证，不能当0或为测量扩权。必要数据缺失、未校准、噪声未解均不得性能PASS。实际正确性/可复现预算失败记失败待决策；无效实验保留原因并重测，不伪称候选失败或通过。

## 6. 记录与推广边界

每层私人原件记录预期/实际argv，公开记录使用normalized_argv/路径标签/原件摘要/脱敏引用，保留退出码、合成数据、候选/target/锁/fixture/policy摘要、通过范围和未覆盖组合。实际执行身份必须核验私人原件，公开结构校验不能替代。任务状态统一为：

| 状态 | 适用情况 |
| --- | --- |
| 已完成 | 本项要求已实际执行并有充分证据；文档完成只证明文档 |
| 进行中 | 本项正在实施或执行，尚无最终结论 |
| 失败待决策 | 实际失败、设计前提失效或需主代理决定；不能改写为缺环境 |
| 环境不足未验证 | 未授权、缺实现/工具/平台/必要数据或实验无效待重测；不记通过，也不自动阻塞无关项 |

代码与fake-host检查、隔离Linux Herdr核心、双回环SSH客户端、Avalon Review冻结/刷新/导出保留及DSH/Codex入口已分别记录；macOS/Ghostty实体IME/粘贴/C-x/Shift+Enter已有分项结果，官方Codex真实模型选定Review交接已通过；实体固定样本剪贴板/视觉/detach/SSH重连已完成，Avalon内部Ctrl+w v/h/l及显式+复制补验也已完成；Pi完整校验的期限修订与双实例实际进程/独立租约复验已通过，CPU后端、单窗口原件、客户端首帧就绪及正常detach已核对，性能校准和生产基线尚未通过。已修复的准备失败保留历史原件，当前状态以实施证据首页为准，不填写虚构成绩。

任何PASS都不是canary或生产切换授权。后续取得对应授权后，只让新工作进入专用新server，保留旧server与长任务；再显式决定未来启动入口。回退分别核对程序选择、受管配置rollback和native持久状态兼容/副本，不让旧binary直接读未知新版状态，不自动迁移/结束存量进程。最终写入结束后审阅稳定diff；验证后再修改须重跑受影响检查。
