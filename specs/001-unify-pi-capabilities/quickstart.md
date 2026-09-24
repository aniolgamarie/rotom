# Pi 迁移验证指南

本指南说明使用流程和验证入口。当前 spec 的软件迁移、Linux x86_64 四配方 mock/native 与双路径冷重建已验收完成；其他三平台和真实账号／服务验证已转出，未来另行处理。
当前范围与通过证据见[关闭报告](../../docs/acceptance/pi-spec-closure-20260924/README.md)，未验证项见[后续清单](../../docs/follow-ups/pi-platform-and-live-validation.md)。下方账号及平台操作说明不表示对应场景已经通过。

## 1. 前提与验证层级

- 已完成本计划的代码、真实依赖锁、vendor 构建及机器示例。
- 管理器 Python 3.11+，仓库 `.venv` 已通过 `uv sync --locked` 准备。
- 锁生成/安装：Node 24.14.0、npm 11.19.1；Cursor 可选引擎另需 Bun 1.4.0。
- Linux managed 需要可用 bwrap/namespace；macOS 需要 Xcode CLT/clang 与已通过预检的 sandbox-exec。
- 真实账号只由用户在实例内配置/登录；代理、MCP、项目检查和可选工具须显式绑定。

| 层级 | 允许行为 | 授权与结果含义 |
|---|---|---|
| mock | 临时HOME、网络阻断、假宿主/模型/子进程、真实临时文件 | 默认测试；不证明原生加载或账号可用 |
| native | 临时实例中运行锁定宿主，使用虚构provider/受控本地替身 | 必须独立明确授权并加 --allow-host；不读取真实账号 |
| live | 用户选择的实例、账号和任务，可能产生真实请求 | 必须另行授权并同时 --allow-host --allow-live；限明确场景 |

native/live 未授权时停留在对应未执行记录，不能自动退回 mock 后标为已通过。

## 2. 默认隔离验证

新克隆先显式准备 Node 测试依赖（消费测试工具的固定 package-lock；仅此准备步骤可能联网，不启动宿主或登录）：

```bash
npm ci --ignore-scripts --no-audit --no-fund --prefix tests/fixtures/pi/tooling
```

此目录的 node_modules 是本机可重建测试依赖，不进入 Git。准备完成后，在仓库根运行默认隔离回归：

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python scripts/verify-pi.py --tier mock --case all --output /tmp/agentcfg-pi-mock-report.json
```

预期：所有默认用例通过；HOME/PI_CODING_AGENT_DIR/DSH_HOME/XDG 使用临时路径；
没有真实宿主调用、外部网络、用户目录写入；脚本非零结果意味着失败，不覆盖历史失败记录。
Node 单元测试由此入口调用隔离的 mock runner，不能复用会启动 Pi 的旧 Task Keeper 全量入口。

定向场景可独立重复：

```bash
.venv/bin/python scripts/verify-pi.py --tier mock --case migration-conflicts --output /tmp/pi-migration.json
.venv/bin/python scripts/verify-pi.py --tier mock --case budget-permissions --output /tmp/pi-budget.json
.venv/bin/python scripts/verify-pi.py --tier mock --case termination-recovery --output /tmp/pi-recovery.json
.venv/bin/python scripts/verify-pi.py --tier mock --case model-delegate-replacement --output /tmp/pi-delegate.json
.venv/bin/python scripts/verify-pi.py --tier mock --case dsh-compatibility --output /tmp/pi-dsh.json
```

具体负向条件与FR/SC对应关系见 [validation-matrix.md](validation-matrix.md)。
报告分开记录 schema、mock、native、live，不出现未经执行的 passed。

## 3. 普通配方：新机器配置与只读预览

```bash
./agentcfg init-local --machine pi-workstation
./agentcfg --machine pi-workstation --profile pi-default validate
./agentcfg --machine pi-workstation --profile pi-default render
./agentcfg --machine pi-workstation --profile pi-default plan
```

空私有模型集允许初始化，doctor 不会报告模型已就绪。
用户在创建的本地文件中登记实际 provider/model ID、选择数组和 main/scout/reviewer 绑定；
API key 仅写本地 secrets，原生账号采用独立登录。不要把虚构示例当作真实服务。
资源、机器根、外部工具与选项字段见 [配置契约](contracts/cli-and-configuration.md)。

若核对旧环境，以下命令仅输出私人迁移提案和脱敏摘要：

```bash
./agentcfg --machine pi-workstation --profile pi-default plan --from-pi-home "$HOME/.pi/agent" --from-starter /path/to/starter
```

将 `/path/to/starter` 换为实际来源。预期旧home、账号、会话和starter字节不变；
清单区分来源、选择、磁盘、加载证据和执行证据。采纳非秘密来源修改后重新 validate/plan，
不能把提案直接覆盖原生配置或先运行旧同步器。

## 4. 显式准备与部署

以下是独立的安装/部署操作，在用户要求执行该步骤后运行：

```bash
./agentcfg --machine pi-workstation --profile pi-default sync
./agentcfg --machine pi-workstation --profile pi-default apply
./agentcfg --machine pi-workstation --profile pi-default doctor
./agentcfg --machine pi-workstation --profile pi-default apply
```

预期：只安装所选切片；原始锁文件不变；第二次 apply 的 changed=0，previous 不轮换。
HOME 位于实例内，原全局Pi配置保持不变。待登录、未绑定或未验证状态不得写成完整可用。
普通模型登记和绑定完成后，经明确宿主启动授权：

```bash
./agentcfg --machine pi-workstation --profile pi-default run pi --cwd /path/to/project
```

替换业务项目路径；在该原生实例内完成用户选择的登录。实际加载必须只有一个新管理者，
scout/reviewer 来源与预期一致。capture 只用于已声明、已选模型及允许的主题，不自动登记未知模型。

## 5. Task Keeper 配方

在机器覆盖的 pi-managed 中绑定三种受管角色模型、候选项目根、至少一个真实检查命令、
请求/轮次/时间上限。启用第二视角时额外绑定 second_view，检查命令必须前台且为明确 argv。
未绑定 pi-managed 的 validate 应返回2，但不影响未选择它的 DSH/pi-default。

```bash
./agentcfg --machine pi-workstation --profile pi-managed validate
./agentcfg --machine pi-workstation --profile pi-managed plan
./agentcfg --machine pi-workstation --profile pi-managed sync
./agentcfg --machine pi-workstation --profile pi-managed apply
./agentcfg --machine pi-workstation --profile pi-managed doctor
```

先在 native 授权下使用虚构服务证明原生运行链：

```bash
.venv/bin/python scripts/verify-pi.py --tier native --allow-host --case taskkeeper-lifecycle --runtime /absolute/prepared/pi-managed-runtime --output /tmp/pi-native-tk.json
```

runtime 必须是本机已准备并有匹配收据的锁定目录，脚本不安装；脚本创建自己的临时实例，
注入虚构provider及受控响应，不读取用户账号。测试调查、修复、检查、必要审查、第二视角、
限流、预算、暂停恢复、停止、定时与结果缺失。停止请求接受但资源残留时必须保持unknown/活动保护。

用户另行授权宿主启动和真实任务后，进入受管实例：

```bash
./agentcfg --machine pi-workstation --profile pi-managed run pi --cwd /path/to/project
```

在该 pi-managed 原生会话使用：

```text
/orch inspect -- 调查指定项目的问题并列出证据
/orch fix --second-opinion -- 修复指定问题并运行绑定检查
/orch status <本次jobId>
```

检查当前候选、真实检查结果、审查、消耗和终止证据；不自动合并原checkout。
`<本次jobId>` 必须使用本次返回值，不能引用旧任务通过记录。

## 6. 可选能力

- model-delegate：pi-default提供Pi backend，pi-codex另启用Codex backend；工具统一为model_delegate。
  先用假backend验证只读、显式写入、detach/poll/wait/resume与反馈，再独立授权真实调用。
  pi-codex在实例中使用 `/model-login codex`；高级操作全部由model-delegate技能提供，
  新环境不安装旧codex-delegate，不保留codex_delegate工具或七角色注册。
- pi-cursor：验证 Bun1.4.0 及单独账号，确认没有 Task Keeper；把cursor选进Node managed必须返回配置错误2。
- MCP/web/proxy：每项服务与凭据显式绑定。proxy失败不直连；doctor --live只验证可达性，不验证模型答案。
- notifications/agent-state：缺外部脚本时说明未就绪，不能把原机全局脚本当作隐式前提。

替换专项验收必须移除新测试环境的旧执行器和角色，覆盖七用途映射、两backend只读、
Codex显式worktree写入、Pi拒绝未支持写入、后台启动未知、cursor断点观察、取消/恢复、
原结果凭证关联、结构化上下文/反馈及上层批次聚合。修改过的提示/规则不能再指导调用旧工具。
测试旧名称字符串只用于迁移映射和拒绝场景，不能靠兼容wrapper让用例通过。

## 7. 冷构建与恢复

经 native 授权，在每个准备好的目标平台执行：

```bash
.venv/bin/python scripts/verify-pi.py --tier native --allow-host --case cold-rebuild --runtime /absolute/prepared/runtime --output /tmp/pi-cold-rebuild.json
```

cold-rebuild 使用两个独立 HOME/仓库路径、未安装的目标实例，复制批准的仓库来源，
从锁定依赖源显式执行 sync，再部署和原生验证；`--runtime` 是参考身份，不是复制旧安装树。
这一步允许锁定源下载但不允许模型外网；报告分别记录两次安装与调用链。
断开 starter/旧home/全局缓存后仍应可用；每个所选切片分别运行，不能用普通配方替代managed。

在临时环境中演练：用户改受管字段→冲突；单侧原生漂移→保留；写中断→pending恢复；
父退出/子任务活动→apply/sync/rollback返回4；凭据引用合法轮换与回滚成功，秘密字面量在快照前拒绝。
恢复完成后才允许回滚上一轮配置，任务数据库和账号不跟随回滚。

### 控制者崩溃后的显式停止

先查看保存的旧执行计划，检查lease和目标；计划也可表示撤销已证明未启动的分配预留。以下命令不启动宿主或模型：

```bash
./agentcfg --machine pi-workstation --profile pi-managed recover pi --lease LEASE_ID
```

用户明确要求停止该目标后，使用上一步返回、300秒内有效的实际计划摘要：

```bash
./agentcfg --machine pi-workstation --profile pi-managed recover pi --lease LEASE_ID --stop --expect-plan PLAN_DIGEST
```

将LEASE_ID/PLAN_DIGEST换成本次值。旧supervisor仍活跃、PID身份不符、计划过期或外部工作未知时
必须返回冲突/unknown并保留保护，不能force解锁。此权限只用于停止或回收已证明未启动的本次预留，不恢复旧任务继续执行。
旧日志缺失/损坏或启动边界已提交但进程未知时不能清锁；普通业务编辑使用ordinary授权，不要求候选任务。
控制恢复和工作区写锁细节见 [recovery-and-workspaces.md](contracts/recovery-and-workspaces.md)。

### 随时汇总，单独检查交付

2026-09-24 范围修订后，本 spec 的最终 scope 为 `docs/acceptance/pi-spec-closure-20260924/scope.json`，evidence-root 为 `docs/acceptance/pi-cold-9d6a9270`；关闭结果见 [验收报告](../../docs/acceptance/pi-spec-closure-20260924/README.md)。
下方原始 scope 的示例保留用于历史完整范围及后续平台/live 验证，该范围报告仍不批准；不能把它与当前 spec 软件范围的批准混为一谈。后面的 live 操作说明是未来使用入口，不是当前 spec 待完成任务。

固定scope已准备后，即使尚无平台/账号证据也能出报告：

```bash
.venv/bin/python scripts/verify-pi.py --report-only --scope docs/acceptance/pi-scope.json --evidence-root docs/acceptance --output /tmp/pi-status-initial.json
.venv/bin/python scripts/verify-pi.py --check-release --scope docs/acceptance/pi-scope.json --evidence-root docs/acceptance --output /tmp/pi-release-check.json
```

这些命令不启动宿主/网络。报告生成返回0不等于验收通过；check-release遇缺失、失败、过期证据返回1。
未选可选账号项显示not-selected而不计通过；已选但缺账号/授权显示not-run并阻止批准。
每次output用新文件名，禁止覆盖已有报告。scope变化使旧批准失效，不能为通过而删必需范围。

## 8. 验证入口接口

`scripts/verify-pi.py` 为本计划新增验证CLI：

- 执行模式必须指定 `--tier mock|native|live`，默认不启动宿主；报告模式使用 `--report-only` 或 `--check-release`，三种模式互斥。
- `--case` 支持 all、migration-conflicts、budget-permissions、termination-recovery、
  host-resources、optional-services、codex-receipts、model-delegate-replacement、readseek-tools、dsh-compatibility、taskkeeper-lifecycle、cold-rebuild。
- `--runtime PATH`：native的已准备参考/运行包身份；cold-rebuild另执行两个目标安装。
- `--allow-host`：native/live必须；`--allow-live`：live额外必须。
- `--local PATH --profile ID --project PATH`：live必须，用于限定本次用户授权的实例、配方与项目。
- `--scope PATH --native-report PATH --live-item SCENARIO_ID`：live必须。所选 scope 项应冻结到当前部署，native报告必须匹配运行包、平台和所需完整场景；单个开发调试结果不满足此门槛。
- `--output PATH`：私人0600结果，拒绝覆盖已有报告，保留失败证据。
- 报告模式必须有 `--scope PATH --evidence-root PATH`，不接受tier/allow-host/allow-live；按 [证据契约](contracts/evidence-and-release.md) 处理缺失或损坏记录。

mock不接受真实HOME/运行包参数；native不接受真实本地凭据文件；live不接受all，
只执行用户选择的case与绑定范围。非法参数返回2，执行验证失败或交付检查阻塞返回1；
执行模式只有全部所需场景通过才返回0，report-only的0只表示报告成功。
此脚本不是管理器CLI，其退出1只表示验证失败；不改变agentcfg现有退出码。


## Codex原生执行配置补充

普通Codex委托保留官方CLI原生工具。所选配方须显式声明：

```toml
[agent_options.model_delegate.codex.native_execution]
allow_shell = true
tool_network = "none"
```

这只声明原生命令权限；业务文件范围仍需可表达的FilePolicy以及只读/显式写入准入。
不会从文件read规则或tool:ID自动推导原生命令授权。allow_shell=false关闭原生shell，不改走MCP。
取消会停止整次执行，确认物理终止前保持写保护。新边界协议不能直接认证/恢复缺字段的旧记录。
原生参数/沙箱/配置发现未获本平台证据时，仍不得称完整可用。


### 实网工作流专用项目

Task Keeper 的验收会主动准备已知坏输入，并要求模型修复，因此只接受以下命令新建的合成 Git 项目。该步骤不启动 Pi、不调用模型，不覆盖已有路径：

```bash
.venv/bin/python scripts/verify-pi.py --prepare-live-project \
  --project /absolute/private/path/pi-live-probe \
  --output /absolute/private/path/prepared.json
```

将新项目作为 `pi-managed` 的唯一测试项目根绑定，登记 reader/writer/reviewer 模型、预算及检查命令。检查应执行该项目的 `test_live_fixture.py`（例如私人可信 Python 的 `-m pytest -q -p no:cacheprovider`），`inputs` 绑定该测试文件，`kind="tests"`、`parser="pytest"`、`minimum_tests=1`。启用第二视角时另绑 `second_view`。配置修改后重新 apply、冻结 scope 身份，再运行：

```bash
.venv/bin/python scripts/verify-pi.py --tier live --case taskkeeper-lifecycle \
  --allow-host --allow-live --local /absolute/private/local.toml --profile pi-managed \
  --project /absolute/private/path/pi-live-probe --runtime /absolute/installed/runtime \
  --scope /absolute/frozen-scope.json --native-report /absolute/matching-native-report.json \
  --live-item pi-managed.live-direct.inspect-fix-review --output /absolute/new-live-report.json
```

同一入口支持 `pi-managed.live-direct.second-view`、`pi-managed.live-proxy.inspect-fix-review` 和 `pi-managed.live-proxy.second-view`；选择代理时，所有受管模型必须绑定代理路线并具有该路线的匹配原生证据。成功要求两个工作流的当前检查与审查收据、源项目恢复和全部进程退出。失败报告保留，不自动恢复未知活动或清理未确认终止的任务。

Codex、Cursor、代理使用对应 `live-codex` / `live-cursor` / `live-proxy` scope 项；MCP、web、终端使用 `--case host-resources` 加对应 `live-mcp` / `live-web` / `live-terminal`，前置报告来自 `--tier native --case optional-services`。服务验收只加载本次所选扩展；MCP实际连接并刷新元数据，web逐个指定搜索提供方验证响应，终端必须三次确认状态报告。凭据或服务缺失仍记未执行，不能记为未选择。
