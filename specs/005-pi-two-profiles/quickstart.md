# 长期任务的验证与恢复入口

状态：计划指南。下面现有命令经过源码/路径核对，本轮没有执行产品测试。拟议的新功能命令必须在实现后替换成真实入口，不能直接复制假参数。

本轮plan选择官方Pi v1.0.1与原生MCP/Code Mode作为初始候选，正式安装/兼容仍未验；当前仓库锁保持0.84.4。已有离线检查用于回归现有边界，不证明候选升级成功。提供者选择见research.md D12，替换和服务协议见[能力契约](contracts/capability-providers.md)、[服务契约](contracts/durable-service.md)。

## 1. 从正确任务继续

在仓库根目录先读 `AGENTS.md`、本目录 `spec.md`、`plan.md`、`tasks.md`、`acceptance.md` 和最新运行交接记录。当前必需平台是用户指定的本机 Linux x86_64；Mac 等按需，不阻塞完成。

现有只读现场命令：

```bash
git status --short
git diff --stat
git branch --show-current
```

再核对实际运行身份/日志与未完成操作，不通过全量读取HOME/环境/认证来“盘点”。本轮计划不改变现有日常Pi实例。

## 2. 默认离线检查（现有入口）

前提：仓库 `.venv` 和所需Node工具链已准备，依赖与fixture已存在；不通过命令隐式联网安装。以下只对应当前测试入口，后续实现须补入新增场景并保存运行身份。每组的通过只覆盖该组实际行为。

Profile/资源基线：

```bash
./.venv/bin/python -m pytest -q tests/test_pi_capability_manifest.py tests/test_pi_optional_capabilities.py tests/test_pi_validation_fixture.py
```

依赖/运行包：

```bash
./.venv/bin/python -m pytest -q tests/test_pi_vendor.py tests/test_pi_dependencies.py tests/test_pi_assets.py tests/test_pi_validation_runtime.py
```

权限/命令：

```bash
./.venv/bin/python -m pytest -q tests/test_pi_guarded_files.py tests/test_pi_operations.py tests/test_pi_commands.py tests/test_pi_checks.py
```

委派与受管检查：

```bash
./.venv/bin/python -m pytest -q tests/test_model_delegate_contract.py tests/test_model_delegate_backends.py tests/test_model_delegate_codex_worker.py tests/test_pi_delegate.py
./.venv/bin/python -m pytest -q tests/test_pi_worker_protocol.py tests/test_pi_worker_files.py tests/test_pi_checks.py
```

插件桥的仓库隔离runner：

```bash
node scripts/test-pi-mock.mjs agents/pi/packages/model-delegate/tests/bridge.test.ts
```

聚合mock入口示例（每次将output改为新的私密运行路径，不覆盖历史证据）：

```bash
./.venv/bin/python scripts/verify-pi.py --tier mock --case model-delegate-replacement --output /tmp/pi-two-profiles-delegate-mock.json
./.venv/bin/python scripts/verify-pi.py --tier mock --case taskkeeper-lifecycle --output /tmp/pi-two-profiles-taskkeeper-mock.json
```

默认runner使用临时HOME/XDG、虚构模型/服务和假子进程；不得为了让上述命令通过而启动第三方宿主或读真实认证。依赖缺失记环境不足，不记测试失败或通过。

## 3. 必须新增的端到端场景

以下为验收步骤，不是已经存在的命令：

1. 新建临时HOME与合成C++/Shell项目，在无Full依赖的安装目录部署Base；通过实际Rotom入口启动，记录加载集合。使用合成provider或真实账号的层级按授权分开。
2. 通过真实受管工具读写允许根，尝试读取合成秘密哨兵、写禁止根、网络/socket越界；由父侧观察文件/连接事实。正例必须同时通过，不能“所有命令失败”就算隔离正确。
3. Full启用/关闭reviewer分别运行；真假允许、拒绝、超时、取消、迟到和参数变化不混淆。真实模型质量集只判断命令，不实际执行危险命令。
4. 从Pi与Codex入口调用统一核心，在两个后端核对实际模型、消息、继续、取消及唯一Writer。禁止用新任务伪装原会话继续。
5. Inspect/Fix合成失败案例：先测试失败，Worker最小修改，可信检查和独立Reviewer，至多两轮修复；零测试/全跳过/输入变化使最终gate失败。
6. Durable提交只读调查任务，保存ID；断开前端后重连，再做服务受控重启和强制退出；请求应答丢失时用同ID找回，不重发副作用。
7. 在数据副本上升级、注入迁移故障、恢复；旧活动实例不被强停，新版本不写坏旧状态。
8. 对同一能力选择等价提供者做替换、卸载及失败恢复演练；复用正常/拒绝/取消/故障契约，核对配置入口、状态归属、旧任务及恢复引用、加载残留和证据失效。不兼容候选明确失败；两个替身只验证机制，真实支持组合另验，禁止为替换自动换源或强停旧实例。
9. 从两个独立受管profile分别对Git根和显式登记的非Git根竞争写入；别名指向同一根时仍只允许一个Writer，未知旧执行不释放。未登记非Git根明确拒绝并给出登记路径，不自动git init。
10. Durable静态查询、result和watch逐项核对零模型调用、零调度推进；在模型请求sending持久化后模拟响应丢失，重启保留unknown和预算，不自动补发。分别验证公开SQLite适配的实际同步设置及registry不匹配拒绝，不能以SDK示例通过代替。

第1、3、4、5、6中真实宿主/账号分别核对授权。本指南不提供自动登录、复制token或修改全局默认的捷径。

新增9/10同样按实际使用的层级核对授权。应先以替身的外部请求计数、状态文件、占用记录和哨兵核对，再运行获准的OS/native/live组合。当前没有这些新场景的实现命令；tasks阶段已将其绑定下表及tasks.md的V0–V10命令组；新增文件实现后执行，不能提前登记通过。

### 场景到实施入口

任务编排完成，以下测试文件是明确的待实现落点。现有命令仍可验证旧边界，新增命令在对应任务完成前不可执行；完整命令和默认/独立层级见[tasks.md](tasks.md)“验收命令组”。

| 场景 | 当前任务 | 首要检查入口 |
|---|---|---|
| 1 Base日常/冷安装 | T017–T028、T040–T041 | 现有test_pi_optional_capabilities.py、test_pi_validation_runtime.py及合成日常场景 |
| 2 受管工具隔离 | T029–T040 | 新增tests/test_pi_tool_sandbox_os.py；默认test_pi_checks.py |
| 3 审批开关/质量 | T049–T057 | 新增risk-review/tests/protocol.test.ts、permit-races.test.ts；真实评测脚本单独授权 |
| 4 两宿主/两后端 | T058–T066 | test_model_delegate_contract.py、test_pi_delegate.py；真实矩阵另验 |
| 5 TK Inspect/Fix | T067–T075 | 新增task-keeper/tests/two-profiles-contract.test.ts、tests/test_pi_input_snapshots.py |
| 6 持久连续性 | T076–T092 | 新增durable-service/tests/protocol.test.ts、recovery.test.ts及独立进程suite |
| 7 维护恢复 | T042–T048、T091、T095 | test_pi_validation_runtime.py；新增durable-service/tests/maintenance.test.ts |
| 8 提供者替换 | T042–T046、T095 | 新增tests/test_pi_provider_replacement.py；真实组合另验 |
| 9 非Git共享Writer | T014–T016、T064 | tests/test_pi_workspace_leases.py与新增tests/test_pi_registered_roots.py，必须两个独立进程 |
| 10 Durable发送/查询/持久化 | T077–T090 | 新增durable-service/tests/recovery.test.ts与tests/test_pi_durable_processes.py；外部请求与scheduler计数oracle |

TS包相对路径分别位于agents/pi/packages/下。入口与文件完整路径以tasks.md为准，不将表中简写当shell参数。

## 4. 证据汇总与发布

现有汇总器支持如下形状，尖括号是需要替换的真实路径，不能原样执行：

```text
./.venv/bin/python scripts/verify-pi.py --report-only --scope <本任务冻结scope.json> --evidence-root <本次证据目录> --output <新的报告路径>
```

实现阶段扩展/复用它处理本任务矩阵；旧scope不能自动代表新scope。report-only只是核对事实，不能产生缺失的测试证据。Base、Full、隔离、维护、账号与人工体验分别报告。Base按自身/共同能力适用项（含纯Pi/Base两态性能和维护）独立判定；Full/总交付再要求完整四态及专属功能证据。两态或局部报告不能冒充总矩阵通过。

## 5. 中断后恢复

使用当前宿主支持的原生会话恢复方式；若需Codex CLI命令，先核对所装版本的公开帮助，明确session ID，不盲用last。不假定进程仍在，也不自动重跑。

可直接交给接手代理的工作说明：

> 继续 specs/005-pi-two-profiles 的长期任务。先读 plan.md、tasks.md、acceptance.md 和最新私密运行记录；核对git diff、实际进程/会话身份、未完成许可、预算及近期证据。当前Linux x86_64是必需平台，Mac等按需。先对账unknown，再执行最低编号且依赖满足的未完成任务。Base通过后继续Full；已有授权不重复问，缺授权只阻塞依赖路径。不修改上游、不复制凭据、不将mock或旧版本证据算成当前真实验收。

仅在全部完成、用户停止、运行环境/额度限制，或没有安全可执行独立路径的真实阻塞时结束实施；计划文件和恢复命令不保证断电或宿主退出后任务进程存活。


## 当前已实现的独立进程租约检查

默认 pytest 仍禁用这些进程用例。仅检查自有合成 Python worker 的 Git 租约时，显式执行：

```sh
.venv/bin/python -m pytest -q tests/test_pi_workspace_leases_os.py -m pi_lease_os --run-pi-lease-os
```

该入口限定临时工作区和账号环境，不启动 Pi/Codex，不读取真实认证，也不证明文件或网络沙箱。当前七项覆盖独立进程竞争、别名/子目录、忙锁与提交前后骤停；非Git、PID复用及真实宿主另验。

## T038：整进程 Q3 合成 fixture（仅准备）

自有材料位于 [`tests/fixtures/pi/whole-process/`](../../tests/fixtures/pi/whole-process/README.md)。默认静态入口：

```sh
.venv/bin/python -m pytest -q tests/test_pi_whole_process_fixture.py
```

此入口只读封闭 JSON、来源 SHA、固定路径/场景/子进程预算及执行前提，不加载或执行 `.mjs`、Node、Pi、Docker、网络或子进程。它不证明整 Pi 已隔离，也不表示 Q3/T039 已执行或选择技术不支持。

后续整进程入口是公开扩展命令 `/whole-process-probe <封闭case-id>`，八个固定场景及来源见 fixture 的 plan/README：允许项目读写、禁止宿主文件读写、禁止出站、允许容器自身 loopback、固定自有子进程允许/越界，以及**容器内原生合成账号可读**的限制观察。命令只注册、不自动运行；执行须另外冻结 Node/Pi/扩展/完整候选树与容器 image 身份、实际 public CLI 参数、非 root UID/GID 和私有 bind/tmpfs 所有权、Docker namespace 与生命周期，再统一核对具体授权。当前 plan 为 prepared-only，image/UID/运行身份留空，没有可直接启动的容器 runner；不复用旧 SDK/RPC 授权。

Docker 候选场景限定 readonly root、cap-drop ALL、no-new-privileges、network none、有限 pid/memory/CPU、只挂载冻结来源和新私有项目/state/results；禁止 privileged、宿主 namespace/devices/docker.sock/HOME/token mount、任意 argv、隐式安装、自动部署或切默认。父侧必须独立核实际允许结果、未暴露的宿主哨兵未变、连接事实和全部容器/后代终止；命令全失败或扩展自报 blocked 不算隔离通过。仅超时/无监听不算网络负例，须有实际 namespace 与外发观察证据。

普通容器不向容器内同 UID 的恶意扩展隐藏 Pi 原生凭据。fixture 只使用自有 synthetic auth，明确预期该文件可读，不复制或检查真实宿主认证；network none 同时阻断真实登录/模型外网，不拿此场景当账号资格或 provider 正控。CLI/SSH/真实登录等 Q3 场景仍需各自明确受限配置与授权；整进程调查不能替代必需受管工具隔离验收。

## 当前 Base 参数核对（T048 子项）

当前存在的 validate/plan/sync/apply/doctor/run 及 workspace 参数和拒绝条件见 [中文手册](../../docs/pi-two-profiles.md#当前-base-cli能核对什么何时会拒绝)。全局 `--local`/`--machine` 二选一、`--profile pi-base` 在子命令前；`run` 的原生 tail 只放在 `--` 后，**run 不接受 --format**。workspace 不接受机器/local/profile 选择器，登记不是写许可。

本轮只以临时 HOME、虚构缺失 local 和原隔离 guard 核 own CLI parser/失败路径，sync/apply/run 没有 dispatch 执行，真实安装、部署、宿主、账号、网络和回退均未测。现代锁未发布时 validate/plan 等仍可能返回 2，缺运行包/资格返回 5；不能借历史锁、candidate 目录或系统 Pi 消除这个真实约束。诊断/组件证据不能签发 Base 产品通过，也不应切换用户默认。Full/维护与实际 OAuth/SSE/主模型 proxy 仍分列待完成。
