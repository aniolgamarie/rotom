# 官方公开 SDK 用户意图探针

## 当前异步材料：13场景，父post修复及授权review02重跑均已验收

日期：2026-10-06。用户已明确授权本13场景与同边界必要修复重跑。首轮 `/tmp/rotom-intent-scope-probe-async-20261006-review01`（plan SHA256 `62534d59a3d91602a8ce808d943bb812b801c638ef938c05a1f5f5881803a2c0`）实际执行13行计数均满足，但独立复核发现父检查器未强制完整post工作/根目录清单。本轮保留首轮原始工件和P2，先修复父检查器及默认反例，不把原执行当修复后验收。

当前 probe_id 仍为 `confirmed-intent-public-sdk-async-v2`。修复后的新目录 `/tmp/rotom-intent-scope-probe-async-20261006-review02`，plan SHA256 `b29437c31a8346da3f44317fef9cd435bcce224420537322ffefda1f38425a17`；固定2项子来源、10项父控制器、18498项候选与3项系统可执行文件。scope SHA `395fa8fe8c564542e73f515c2a1c0fe1d6690f6c6fe72c2ae7551ceaaf592376`、MJS及13行oracle均未改动；父检查器 SHA 为 `977cdd40b46950f33737727b14a7da5c97b5ff361417371c8b9fe2fed3a9c5e1`。prepare、preflight、run均退出0；按原同边界修复授权执行，没有重复申请授权。

review02实际13行及完整post清单均满足，capture_failed=false、stdout73字节、stderr0、native_started=true、verification=observed。停止写入后的独立executor复核plan、2+10来源完整身份/SHA、bundle、root5项/work34项、原始闭合摘要及独立测试字面oracle，无范围内开放P1/P2。候选完整前后清单由父检查器核验，独立审查另核lock/3个manifest，未独立重扫18,498全树。两轮原始工件、首轮P2、修复及默认红绿、固定来源和稳定审查分别归档 `.cache/pi-two-profiles/run-20261004/risk-intent-sdk13-native-observed-review02/` 与父修复目录；只记录本轮13场景，不将两轮相加。当前授权执行闭合，产品gate继续false，正式7/100。

保留下文旧十场景，再追加 async-confirmed、async-late-resolve、async-late-reject。正例在公开 ToolDefinition.execute 中使用原 slash ID `scope-call/1`，两次并发 bindingForToolAsync 只调用一次 native Promise allocator，得到原 session/intent/request 的同一冻结对象，并核对 memo。两个迟到场景须观察真实 execute 已进入 allocation 后才 invalidate 原 scope，等待立即 null；后续 Promise resolve/reject 均不能恢复权限。它们不证明底层 SDK/allocator 物理取消或产品持久墓碑。

Python 独立封闭 oracle 固定13行顺序和旧计数，额外核对 async_binding_waits 为2/1/1、async_late_results 为0/1/1；旧十行两项均0。三项新增场景 confirm/intent/request 均为1、合成模型调用2；正例 scoped1/unscoped0/settled，迟到两例 scoped0/unscoped1/retired。合成 UI 的 exact true 不证明真实人工授权，fake allocator 不证明持久 RPC 或原操作消费。

父post修复的默认 Python 假父测试97通过（1.80秒）。旧父代码在8个闭合清单反例实际失败（86 deselected、0.71秒）；最初错误selector的零选择记录另存，不作红例。稳定两文件及独立 executor（gpt-6.1-sol/medium）复核无该父修复范围剩余P1/P2，归档 `risk-intent-sdk13-parent-post-inventory-fix/`。此前默认86、自有Node helper/scope9与旧oracle红例仍分别保留，不相加，也不代替修复后SDK执行。

断网 bwrap、只读固定候选/自有探针、空父环境、私有临时 work 唯一可写、capture 限额/期限及exclusive started边界沿用下文。修后pre根只准plan/bundle/work，七个固定work子目录必须私有0700且空；post根在写execution前只准再增加started，work只准原七个空目录、13个精确case目录（各只含空agent目录）和单链接0600结果。任意额外文件/目录、权限漂移、链接或缺失保留failed。完整清单检查是运行后时点检查，不证明namespace终止或以后不会写入。当前不启动 TUI/Codex/MCP、不读真实 HOME/账号/凭据、不调用真实模型/外网、不部署；namespace termination仍标未独立观察，product_gate始终false。

静态预检（不加载 SDK）：

```
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-intent-scope.py preflight --directory /tmp/rotom-intent-scope-probe-async-20261006-review02
```

本次同边界修复重跑使用的固定命令（已开始目录不得重复执行）：

```
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-intent-scope.py run --directory /tmp/rotom-intent-scope-probe-async-20261006-review02 --native-intent-scope-probe
```

本公开input/start/execute/settling/异步分配路径已取得独立明确授权，并非借用SDK6/reviewer SDK9授权。必要修复保留旧目录、重新固定新来源和默认验收，未放宽oracle或扩大到真实账号/模型/部署。`AGENTS.md` 的“真实 smoke 为独立显式步骤，需用户明确授权”适用于加载官方SDK的运行步骤；本次review02已完成范围内验收，仍不证明真人确认、持久allocator/RPC、费用或物理终止。

## 旧十场景 review01：来源已失效，仅历史

本探针只验证自有 scope 与固定 Pi 1.0.1 公开接口的组合，不启动 Pi TUI、Codex、MCP 服务器，不访问真实模型、账号或外网，不部署。准备、静态核对和默认 fake 测试不加载 SDK；以下实际运行尚未获准，不能引用此前六项 SDK 或九项 reviewer SDK 探针授权替代。

当前自有 `confirmed-intent-scope.ts` 正在增加私有异步请求分配接口。review01 的 plan 明确固定了该自有文件，不仅固定官方 SDK；来源改变后整份材料不能覆盖当前实现。本轮不执行旧材料，保留旧十场景和来源为准备历史。新接口默认验收及独立复审完成后，须重新准备并验证受影响组合，再核对对应实际运行授权。不可变的 SDK 静态源码证据与此自有代码/SDK组合的固定材料分别记录。

## 要解决的问题

自有注册命令等待合成 UI 的明确确认，再在私有 AsyncLocalStorage 中调用并等待官方公开 `AgentSession.prompt()`。工具只有在同一 marker 下的原 input 和首次 `agent_start` 均被观察到后，才能取得内部用户意图引用。`isIdle` 不是原子 reservation，`prompt()` 在收尾窗口可能延迟执行并提前 resolve；这种任务即便后来运行，也只能走人工路径，不能保留旧 scope。

确认回调在本探针中由合成 UI 返回；因此它验证公开 API、异步传播和保守失效规则，不证明人工终端体验或真实人的身份。意图/请求 allocator 也是固定 fake，不验证产品持久映射或累计账号预算。

## 固定十个场景

1. confirmed-idle：合成确认 exact true，原 input/start/tool/settled 在同一上下文，工具取得唯一引用，结束后旧引用不可再取得。
2. declined：false，零提交、零意图分配、零模型调用。
3. no-ui：公开无 UI binding，零确认及零提交。
4. base：Base 下零确认、分配和模型调用。
5. off：Full 关闭时同样零调用。
6. unrelated-input：普通公开 prompt 可执行自有 fake 工具，但没有确认 scope 或内部引用。
7. nested-follow-up：模型调用的自有 fake 工具追加消息，原 scope 立即退役，后续工具不能延续它。
8. handled-input：输入被公开 handler 消费，提交 Promise 无启动就完成，不能误认启动或重发。
9. canceled：原工具开始后明确撤销并调用公开 abort，迟到执行不能恢复引用。
10. settling-deferred：在公开 agent_settled 回调中复现 isIdle 与延后提交窗口，提前完成的 scope 退役，随后真实执行的工具没有旧引用。

各场景逐项核对确认、意图分配、请求分配、合成模型调用、带/不带 scope 的工具调用计数及内部 command status。固定计数是待验证 oracle；失败保留原始结果，不能只为获得通过而放宽。没有真实 HTTP/费用或业务文件操作。

## 材料和隔离

- 自有探针：`scripts/pi-probe-intent-scope.mjs`。
- 自有 scope：`agents/pi/runtime/confirmed-intent-scope.ts`。
- 父检查及 CLI：`src/agentcfg/pi_intent_scope_probe.py`、`scripts/pi-probe-intent-scope.py`。
- 复用自有已审查的 candidate inventory、bounded capture 等辅助函数，当前AST可达的十个自有父Python模块（含paths/storage/schema及其相对依赖）全部在清单中固定 SHA，不改动上游实现。Python解释器、stdlib、jsonschema/referencing及系统库属于受信父环境，未声称完整系统依赖闭包。
- 候选：`.cache/pi-two-profiles/candidates/pi-1.0.1/closure`；Pi 1.0.1、Pi AI 1.0.2，完整文件清单与 lock SHA 固定并在运行前后复核。
- 固定 Node 24.14.0、bwrap 和 timeout；空父环境，仅固定 HOME/XDG/offline 等变量。候选、Node、自有冻结副本和系统库只读；只有本次私有临时 `/work` 可写，`/tmp` 为 tmpfs。没有真实 HOME、账号或工作区挂载。
- stdout 只保留闭合摘要；stderr 有界丢弃，仅记字节数。普通异常或超限回收自有启动器进程组；这不证明整个 namespace 的终止，结果保持 `not-independently-observed`。
- 新目录准备，不覆盖已有材料；wx started 标记禁止同一目录重放。必要修复重跑必须重新准备并固定新 SHA，保留此前失败。

## 准备证据与执行授权

控制器87项默认测试、父检查器70项fake测试、探针纯观测记录函数5项测试已通过。两个UI/错误Promise边界、post-bundle目录/模式及父模块pin缺口都有因果红例和修复记录。nested follow-up的静态oracle为4次合成调用：nested工具、leaf工具及stop先完成，随后SDK drain已排的follow-up，再产生一次stop；默认测试使用独立固定行，不从生产EXPECTED反向生成。

最终独立复核已完成：七个当前源码/测试SHA一致，清单的十个父模块、两个子进程来源、18,498条候选记录和三个系统可执行文件均匹配；bundle目录/文件模式及空work树通过检查，started标记不存在，没有执行SDK。证据保存在私有任务记录 `risk-intent-scope-native-preparation/`。产品 gate 始终 false，正式任务仍7/100。

已准备目录为 `/tmp/rotom-intent-scope-probe-20261005-review01`，plan SHA-256 为 `7e7d958ac65f2ea0b8538ed80664f326599e78943a3dd0087bd99d1baa8a340d`。等待明确授权后，固定命令如下：

```sh
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-intent-scope.py run --directory /tmp/rotom-intent-scope-probe-20261005-review01 --native-intent-scope-probe
```

授权请求仅覆盖这十个断网合成场景，以及相同边界必要修复后使用新目录的重跑；每次重新固定来源和系统身份，失败记录保留。当前文件是可审查的执行方案，本身不是授权。仓库 [AGENTS.md](../../AGENTS.md) 明确规定“真实 smoke 为独立显式步骤，需用户明确授权”；已授权九项 reviewer SDK 探针验证provider/SSE，未覆盖此次input、settling与私有异步scope路径。
