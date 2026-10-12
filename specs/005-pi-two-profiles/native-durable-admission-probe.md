# 官方 Durable kernel 受理合成探针

状态：2026-10-06，用户授权的七场景及同边界必要修复已完成。最终review05七场均实际observed/complete、exit0、stderr为空，原完整oracle、运行前后材料及独立工件复核通过；root验收有限公开Session/SQLite kernel组合，本次授权闭合。此前三轮首场失败及各后六项not-run保留，不能合计或改写为通过。完整RootTask正文、Harness/owner/恢复/模型与产品验收仍待完成。

首轮76项默认替身检查虽通过，稳定审查发现三个P2，旧材料保持未验收：当前场景已启动后finally保存失败可能被汇总为not-run、stdout/state普通比较混淆boolean与integer、固定bwrap不支持准备argv里的`--clearenv`。root已决定保留当前mutable执行记录、改用严格值比较及独立state oracle、使用Popen `env={}`及固定setenv白名单。修复、旧源反例和新稳定复审完成前，不执行或申请授权旧plan。

## 有限目标

验证固定 `@earendil-works/pi-durable@1.0.1` 的公开 createSession、SqliteStorage 和 Chord Draft 接缝，组合自有 [requests 组件](durable-request-admission.md)及[存储初始化组件](durable-storage-composition.md)。使用固定 Chord1.0.2、pi-ai1.0.2、diff8.0.4、typebox1.3.27 和 Node24.14.0；四个直接依赖在现有固定 Pi closure 中，选定 metadata 与249条锁依赖边的静态核对不代替运行证明。

选择公开 createSession 与原 SqliteStorage 的较窄 kernel；自有结构门面把 commit/snapshot 原样绑定原 Session，把 getTask 绑定保留的原 Storage.task。通过公开 defineTask 构造自有合成 token，仅测试 initial 和保存原 input，不运行 phase/abort 正文。不会打开 Harness、安装 registry、启动 scheduler、调用 Models、真实账号、外网、Pi TUI、Codex 或 MCP；不部署、不修改用户环境或上游源码。

每场景显式用公开 Tx.createConversation 的合法 ownership 创建独立临时 conversation，保存返回的真实 ID。seed 批次与 ID 分配单列，不混入组件受理的 Task/Doc 计数。每个 SDK 方法都使用从官方 Chord/context 公开导出的 BACKGROUND_CONTEXT；不制造 Context、不传 undefined。

真实 SDK Draft 通过公开 copyJson 提取，再做自有闭合校验。原 Storage 的公共 commit 门面只记录批次类型、Task 数和合成 native ID，不导出或散列完整写批次。持久 oracle 同时用原 Storage.task、findDocument/address/current 和 document/id/current 读取；不能只靠 Session 缓存宣称 SQLite 持久记录存在。

## 七场景

1. 正常初始化和受理：真实 Proxy Draft、WAL/FULL 读回、同一 SDK batch 的 Task 与 Doc、冻结 receipt，以及持久原 Task/Doc/input/ID 一致。
2. 十二个相同完整请求并发，仅创建一个 Task；改变正文、路线、授权或预算后同 key 冲突，零新 Task。
3. 原 SDK submit commit 完成后，自有调用门面丢回执；旧组件保持封闭，lookup 找回同一原 ID，新的 submit 拒绝。
4. 原 SDK initialize commit 完成后丢回执；Doc 绑定保留，旧组件不能再次初始化或受理。
5. active 模式缺 Doc，零组件 commit、零 Doc 重建、零 Task。
6. snapshot 已观察缺 Doc 后，以独立公开 Session.commit/Tx.doc 写入历史未绑定哨兵；组件初始化必须拒绝，零覆盖、零 Task。
7. 原 SDK submit commit 完成后关闭自有组件；不能返回 accepted，lookup 仍能核原持久 ID。

故障通过自有公开结构门面注入，不替换或改写 SDK 对象、方法、原型、数据库字段、全局 fetch 或 vendor 源码。未知回执和关闭不推导未发送、退款或物理停止。

## 准备和执行边界

自有 parent 的默认 prepare/默认测试不启动 SDK。运行需要显式 native flag、已准备不可暗改的 plan 和新授权；实际命令、plan SHA、源/候选/系统 pins、逐场景 oracle 与具体输出目录在准备完成和稳定审查后补入。

bwrap 断网、unshare-all、cap-drop ALL、new-session、die-with-parent；只读挂载固定 Node、Durable 原发行目录、现有 Pi closure、自有探针/组件/fixture，以及有界系统运行目录。自有 namespace 的 node_modules symlink 仅解析到只读原候选，不改原 package/node_modules、不安装依赖；设置完成后remount根只读。子进程环境为空，通过setenv固定白名单，不使用本机不支持的clearenv参数。HOME/XDG/TMP/PATH 使用临时目录与空命令目录；应用文件系统仅临时work可写，另有必要的proc/dev namespace伪文件挂载。

manifest 绑定所有自有源、Durable243条发行文件/257个候选项及现有closure18498项全集，并做闭合盘点，不只核 SOURCE.json。system pin有界于Node/bwrap实际可执行文件SHA/stat和usr/lib/lib64挂载根身份，不声称整个系统树内容固定；在未来实际normal-owner执行环境重新准备并固定身份，不能放宽检查来适配不同UID视图。parent 对 argv/env、JSON重复键/未知字段/计数/ID、stdout/stderr上界、超时与工件全集失败关闭；具体实现尚待稳定复审。

默认 pytest 只用临时 HOME、小候选和假 Popen，验证准备、漂移、参数、严格 oracle、输出上界及异常工件；不把替身中 native_started=true 当执行 SDK 证据。原始失败、stdout/stderr、运行前后清单与稳定审查结果都保留。

## 历史review02候选材料

三项P2已在自有parent和默认测试中修复，worker、两fixture及accepted requests/storage未变。真实旧源IO/state反例5 failed/76 deselected，纯argv反例1 failed/81 deselected；最终同守卫默认模块83 passed、0 failed、1.02秒。旧76和旧plan完整保留为未验收历史，计数不相加。独立executor（gpt-6.1-sol/medium）稳定增量复审无剩余P1/P2，root验收；实际SDK仍未启动。

正常属主环境只读prepare已完成，固定plan为`/tmp/pi-durable-admission-probe-preparation-review02-normal-owner-plan/plan.json`，SHA-256 `843f3fabe8913b906d840c02afa944d2c878ea15b791b3a806a2148f04077424`。目录仅plan.json，nativeAuthorized/nativeStarted均false；源/候选/argv/env/system完整绑定，system根UID0、Node UID1002，未放宽此前不一致身份检查。root已复核五份自有源、两份accepted输入、plan SHA、七个空env固定argv及固定bwrap的remount-ro字面证据；这些都是准备/静态事实。

用户已授权的当前命令，**执行结果另行登记**：

```sh
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-durable-admission.py run-native --directory /tmp/pi-durable-admission-probe-preparation-review02-normal-owner-plan --native-durable-admission-probe
```

此命令必须在与prepare相同的正常属主环境中执行。每场景15秒、全部120秒期限；每场景stdout单行64KiB、stdout+stderr累计最多1MiB。父进程只清理本次保存的进程组，namespace/整进程树终止仍unknown。one-shot started记录禁止隐式复用目录重跑，同边界必要修复后另备新目录和完整plan并保留历史。所有执行/错误记录保留原started身份，保存失败不改写为未运行。

最终自有source pins：parent `4a27fa31db93140779da482711f75d0428f41c52157b2fe02bbe5feac82e643b`，worker `4e14a9223e32166cd7d65865ab066277365424f3c06fdf1cdb15915c040d1cc8`，默认测试 `f9c328dcef74b6c9b042e5a25867db43258e3a3b155c2f63c8554de65b17406c`。完整fixture/SOURCE/system/log pins及最小diff见`/tmp/pi-durable-admission-probe-preparation-review02-hashes.json`和`/tmp/pi-durable-admission-probe-preparation-review02-source.diff`；稳定独立复审为`/tmp/pi-durable-admission-probe-preparation-review02-final-review.md/.json`，归档包含这些材料及root-review.json，不把材料存在当授权。

用户对本次独立问题已回复“授权执行及同边界必要修复重跑（推荐）”，授权绑定上述review02 plan SHA和七场景。依据仓库[AGENTS.md](../../AGENTS.md)的明确规则：“真实 smoke 为独立显式步骤，需用户明确授权”。它首次运行公开Durable Session/SqliteStorage kernel，未包含在已经闭合的SDK11/SDK13/RPC5范围内。必要重跑保持同七场景、只读固定来源、临时数据库、断网、无账户/模型/部署，另建one-shot目录并重新prepare所有pins。

## 历史原生失败证据

用户已授权当前plan及同边界必要修复重跑。原review02 plan `843f3fab…` 实际启动normal，exit1、stdout0、stderr仅固定worker-failed；parent退出2，汇总materialIntact=true、parentFailed=false、failed1/not-run6。其后保持公开方法、正常state/oracle和隔离材料不变，自有worker增加固定阶段名；独立增量审查确认该变化无P1/P2。review03 plan `4401c18c…` 的原输出定位document-readback；root再将该固定诊断细分，review04 plan `c6114b02…` 的原输出定位document-compare。两次诊断都首场exit1、后六项not-run；不把越过前置步骤当完整持久通过。

原目录分别为`/tmp/pi-durable-admission-probe-preparation-review02-normal-owner-plan`、`/tmp/pi-durable-admission-probe-native-diagnostic-review03-normal-owner-plan`、`/tmp/pi-durable-admission-probe-native-diagnostic-review04-normal-owner-plan`；one-shot目录不复用。原Session.snapshot、Storage.findDocument和Storage.document在review04均已返回，但copyJson/严格对象比较具体失败原因尚待源码证据和新验收，不能仅凭静态推断改成通过。诊断只固定阶段名，不输出SDK错误、SQL、请求或路径。

## 最终review05运行与验收

最终one-shot目录为`/tmp/pi-durable-admission-probe-native-repaired-review05-normal-owner-plan`，plan SHA-256为`fa67ab0bcfd1016c408547ac5f9b1188461041e1e9df98fef76d78eddf298ab8`。原命令实际退出0；七场均started=true、observed、complete、exit0、stderr0，materialIntact=true、parentFailed=false。七场原stdout与state严格逐类型一致，case-result与汇总一致；全部原oracle保留。root额外只读核对完整257项Durable、18498项closure、七项源及原system，工件全集109项（64目录、45文件）闭合。独立executor（gpt-6.1-sol/medium）稳定工件复审在有限范围无开放P1/P2；其报告完成时root额外核对尚待完成，最终root报告另附实际exit0，未修改历史时间事实。

必要修复只涉及自有代码：完整持久JSON比较忽略合法普通/null原型和对象键顺序，仍核全部键、类型、值和数组顺序；可信Draft先由原公开copyJson提取。公开Chord源码说明该原型差异可能导致旧严格JS对象比较失败，纯旧谓词反例失败，最终原生全比较通过；未记录原SDK异常，故不宣称唯一旧失败原因已直接观测。新增纯JSON32项与parent85项默认检查分别通过。requests同步校验器的普通已拒绝Promise观察修复经79项默认检查及独立复审通过；Promise仍不能授权，未知constructor/species/subclass拒绝，不能普遍保证任意回调无后台异常。各层计数分开记录。

最终源SHA-256：parent `c1f0dbbae89c38708df503d12a6d5f0ef094495e144851e99f73dbf907a3180a`，worker `64b08b47ab8d863597cb8f5477a154682f581befb501015c98916be901736c90`，JSON helper `4500a205c53b8f1b183b07d4d97fc126dd9abb36bc98ac1c9b0508bdda3fbbff`，requests `a30be9a9d91dc412ffceb74e642f9ec02b4b009a65fcc766d2dfff99c979d235`，storage `765117da9012506e49f0f493d6f57ea5cba011d974d5519b6d287ef078d2ceec`；两fixture与原oracle未改。root额外核对首次因自有脚本函数名写错失败，修正后只读检查退出0，没有因此重跑SDK。

原工件、源副本、root与独立报告归档到`.cache/pi-two-profiles/run-20261004/durable-kernel-native-observed-review05/`。前三次失败在`durable-kernel-native-failed-attempts/`单独保留；review03 worker副本由固定阶段变更精确重构并核原d590 SHA，明确标记重构，不能称当时捕获的原副本。持久读取使用原Storage当前同一SQLite handle；没有cold reopen、崩溃/断电或owner竞争证据。

## 不由此推导的资格

即使七场景通过，也只验收所选 kernel 组合：不证明 Harness 注册/RootTask 正文、自动恢复/重复发送、registry/只读工具、owner 锁、真实进程竞争、崩溃或断电、实际账单、严格输入计量、用户前端和产品权限。普通退出和 SQLite 读回也不证明整个进程树物理停止或独立 namespace 观测。T078/T082/T083 和 Full gate 按各自完整条件验收，正式完成数不因本准备变化。
