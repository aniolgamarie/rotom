# 官方 reviewer SDK + fresh-process 组合探针

## 当前共享模型review02：11场景，已授权执行并完成范围内验收

日期：2026-10-06。目录`/tmp/rotom-reviewer-sdk-process-shared-20261006-review02`；plan.json SHA256=`463b663a3c224b855442efd22e8ad23e700b937c1d940a07087ed247dda8e2d5`。固定候选Pi1.0.1/PiAI1.0.2/OpenAI7.19.0仍18498项，15项自有bundle、10项父控制器、3项系统二进制；与下述共享review01相比键集合完全相同，内容变化只有transport/wire-fetch。候选未修改。

场景、八项预计发送/三项零调用、DeepSeek disabled与文本形状、合成provider/SSE、完整共享Model绑定、空启动环境/FD3、4、断网只读bwrap/临时work、95秒/64KiB限制及完整进程域终止unknown均沿用下述11场景边界。**本探针不传beforeSend，不验证账户提交gate。** inputQualification仍为fake，不证明真实输入上限；product_gate=false。没有真实账号、模型、外网、TUI、部署或完整产品资格。

用户已明确授权当前 plan 及同边界必要修复重跑。固定 preflight 和 run 均退出0，11行闭合 oracle 全部满足：8项各一次 fresh child/Worker 合成请求，3项零 child/零请求；子进程 stdout/stderr 均0。missing-usage 保持 unknown/null，错误模型、取消、超限不产生候选决定。execution 的 capture_failed=false、stdout=73字节、stderr=0、verification=observed；未修复或重复运行 SDK11。

停止写入后，独立 executor（gpt-6.1-sol/medium）复核固定 plan、15+10现场来源身份/SHA、bundle、原始摘要和完整行，与 root 验收一致，无该 SDK11 范围剩余P1/P2。候选18,498条完整清单由父检查器运行前后核验；独立审查另外重哈希 lock/3个 manifest，未另称独立重扫全树。原始 plan/bundle/started/execution/result、日志、来源和稳定审查归档 `.cache/pi-two-profiles/run-20261004/risk-shared-sdk11-native-observed-review02/`。此前 Python 父 fake131 和 Node 假适配器14仍是分别记录的默认测试，不与11场景相加。

静态预检：

```
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-reviewer-sdk-process.py preflight --directory /tmp/rotom-reviewer-sdk-process-shared-20261006-review02
```

本次已授权且已执行的固定命令（started 标记禁止在此目录再次执行）：

```
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-reviewer-sdk-process.py run --directory /tmp/rotom-reviewer-sdk-process-shared-20261006-review02 --native-reviewer-sdk-process-probe
```

`AGENTS.md`要求“真实 smoke 为独立显式步骤，需用户明确授权”，本次对应授权已执行闭合。source变更后保留失败/历史材料、重新固定清单；不覆盖已开始目录，不扩大场景或访问范围。下述共享review01和旧v1命令仅历史，禁止执行。异步intent SDK13另有明确授权，其父post清单修复和重跑独立处理。该观察不证明真实输入计量、账户提交、原操作许可、账单或完整 namespace 终止，正式任务仍7/100，产品gate保持false。

## 共享模型review01：11场景，来源已失效，待重新准备

发送gate的自有增量改变了下述transport/wire-fetch来源。review01固定目录只保留历史，不执行；当前同场景review02见上节。后续SDK11仍只验证共享模型与SSE形状，不传gate，不证明持久提交或产品启用。异步intent SDK13不受这两个来源变化影响。本节其余状态、SHA及命令均指旧快照。

日期：2026-10-06。当前 `reviewer-sdk-process-shared-v2` 将已完成离线接线的完整共享 Model 传入独立子进程及 Worker，再通过固定候选的公开 SDK 接口生成请求。只使用合成 provider、认证、消息与 SSE，不调用实际模型或外网，不读取真实 HOME、账号或凭据，不部署。固定候选仍为 Pi 1.0.1 / PiAI 1.0.2 / OpenAI 7.19.0；候选源码没有修改。

当前准备目录为 `/tmp/rotom-reviewer-sdk-process-shared-20261006-review01`，plan.json SHA256 为 `62274ffe9f35e8054542a46fa331ec0c241db1ff8c21975d658abf82dd52aa24`。15项自有 bundle 来源、10项父控制器、18498项候选与3项系统二进制均固定并前后核验。目录只有 plan/bundle/work，没有 started.json 或 execution.json。旧 review02 继续保留为历史材料，禁止执行；当前材料也没有借用旧 SDK9 授权执行。

11场景固定为 allow、ask、deny、missing-usage、wrong-model、canceled、response-limit、hard-deny、human-required、text-allow、input-unqualified。前七项加 text-allow 共8项预计建立一个 fresh child 和 Worker、发送一次合成请求；hard-deny、human-required、input-unqualified 三项均必须零 child、零 send。前三项及 text-allow 保留 reported usage 5/3/8；缺失用量不能填零。错误模型、取消、响应超限均没有候选决定。

10场景使用合成 DeepSeek 形状的 descriptor，保留 name/reasoning/text+image/contextWindow=1000000/native maxTokens=384000/cost/map/compat；text-allow 使用非推理文本 descriptor。每次 reviewer 请求的输出上限独立固定4096，reasoning 固定 off。完整 packet 的 compiler variant identity 同时约束 transport、子进程 argv marker、私有 run 帧、Worker 与 SSE 决定绑定。除 input-unqualified 故意缺失资格外，其余 inputQualification 为自有 fake exact true；这不证明真实输入 token 上限、真实路线授权或产品资格。

父发送边界核验最终请求正文和合成 headers，仅保存安全投影 shape/model/max_tokens/thinking；DeepSeek 分支必须显式 thinking disabled，文本分支必须没有该字段。安全投影不是完整请求正文观测。任何认证、prompt、header 正文或其 hash 均不进入结果。子进程 stdout/stderr 必须0字节；完整进程域终止始终标为 not-independently-observed，factory terminate 即使观察到 child close 也返回 false。产品 gate 始终 false。

固定只读挂载、断网 bwrap、临时 work 唯一可写、私有 FD3/4、空启动环境、95秒外层期限、64KiB有界捕获、exclusive started 标记及完整 post work 清单沿用下文边界。默认 Python 假父检查131项、Node 假适配器14项分别通过；闭包漏掉三个 shared dependency 的因果红例已修复。根代理与独立 scout 对稳定来源和清单审查未发现剩余P1/P2。这些记录不等于官方 SDK 已运行。

静态预检（不执行 SDK）：

```
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-reviewer-sdk-process.py preflight --directory /tmp/rotom-reviewer-sdk-process-shared-20261006-review01
```

仅在取得本材料的新明确授权后执行：

```
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-reviewer-sdk-process.py run --directory /tmp/rotom-reviewer-sdk-process-shared-20261006-review01 --native-reviewer-sdk-process-probe
```

同边界必要修复重跑须保留失败材料；来源变化后重新默认验收、审查及准备新目录，不覆盖已开始的目录，也不扩大到真实模型/账号/部署。`AGENTS.md` 的“真实 smoke 为独立显式步骤，需用户明确授权”适用于这次加载官方 SDK 的步骤；此前的 reviewer SDK9 没有覆盖新鲜进程和共享 Model 路径。

## 旧 v1 review02：来源已失效，仅历史

本材料只准备固定来源；当前没有启动官方 SDK、fresh child、Worker、模型或 HTTP。既有 SDK9 原生授权已关闭，不能借用旧观察或自有 fake-process 观察称此组合通过。probe_id 固定 `reviewer-sdk-process-offline-v1`，product_gate 永远 false。

当前材料已失效：共享真实模型接线修改了 `sdk-worker.ts`、`sdk-worker-entry.ts`，且 `transport.ts` 正在升级。`review02` 的 plan 与只读 bundle 仍作为准备历史保留，但其固定来源不匹配当前代码，不执行该材料。须在新的进程接线稳定并完成默认验收后重新准备受影响来源；本页其余命令、SHA和场景描述均指旧快照。

组合调用链为自有 MJS → createReviewAttempt → createProcessReviewSdk → 固定 sdk-process-entry.ts → createIsolatedReviewSdk → 候选公开 `@earendil-works/pi-ai/api/openai-completions` 与 `utils/transcript`。只使用 public exports，候选固定 Pi 1.0.1 / PiAI 1.0.2 / OpenAI 7.19.0（18498 项闭包）。parent send 只返回自有合成 SSE Response，绝不调用真实 fetch；密钥、路线、消息、模型与绑定全为 synthetic。

九场景顺序固定 allow、ask、deny、missing-usage、wrong-model、canceled、response-limit、hard-deny、human-required。前三项 valid 且 decision 对应，usage reported 5/3/8；missing-usage valid allow，但 usage unknown/null；wrong-model 与 response-limit transport-failure、canceled 为 canceled，均无候选且 usage unknown/null。hard/human 分别 policy-blocked/human-required、零 child/零 send，usage not-sent 0/0/0。前七项必须各 child_started=true、child_close_observed=true、requests=1，最后两项均 false/0。每项 stdout/stderr 计数严格 0，任何诊断污染保留失败，不能吞掉后改 oracle。

factory 仅启动收到的固定自有 entry URL，Node argv 是唯一公开 resolver flag、entry、`--risk-review-sdk-process`；execArgv 不继承 parent，env 只有 OPENAI_LOG=off，stdio 固定 ignore/pipe/pipe/pipe/pipe，私密协议 FD3/4，cwd=/work。主进程放入合成 ambient OPENAI_*、合成环境 data/key 哨兵；不读任何账号、认证文件或真实用户环境来构造 expectedHeaders。fresh child + Worker 的隔离语义依赖公开 Node APIs，当前 default fake 不证明真实运行。

factory terminate 即使收到 close 仍返回 false。row scope_termination 固定 not-independently-observed；child_close_observed 仅 leader close，不能写成 whole-process/namespace termination、预算可释放或产品通过。SDK返回 reported usage 不是真实账单。process adapter 首版完整有界收齐 response body 再转 base64 帧，所以不等于流式延迟验收。

固定 bundle 是新 MJS、own package.json 和 10 TS（protocol/wire-fetch/request-wire/transport/sdk-worker/sdk-worker-entry/request-headers/process-frames/sdk-process/sdk-process-entry），不扫描扩大来源。父 AST 可达固定 10 文件（新 wrapper、__init__/adapter/omp_env/paths/pi_reviewer_sdk_probe/pi_reviewer_sdk_process_probe/schema/secrets/storage）全部身份/SHA前后核验，含函数内相对 imports。受信父 Python/stdlib/jsonschema/referencing 未完整 pin，不称完整系统闭包。Node/bwrap/timeout 二进制及候选全树另 pin，source 完整性检查并非同UID加载竞态的原子执行证明。

OS计划 unshare-all/new-session/cap-drop ALL，/usr /lib /lib64、candidate、Node、bundle 只读，唯一私有 work 可写；/proc、/dev 为新实例，/tmp tmpfs；Popen env={} / stdin DEVNULL / close_fds / new session。没有真实 HOME、账号目录、workspace 或完整仓库挂载。工作根及七个固定私有子目录必须0700且空，bundle文件600目录700。prepare目录只允许 plan/bundle/work；exclusive started.json 阻重放。post重新核验来源、candidate、system、bundle与目录全集，work只准七个仍空的私有目录和唯一0600 result；额外文件、认证/cache/session工件或权限漂移均保留失败。闭合结果/摘要不一致不能 observed。

Node硬截止60秒；外层GNU timeout95秒（5秒kill尾窗），父捕获deadline100秒并做有界 TERM/KILL清理。stdout/stderr分别最多64KiB；stderr只计数/drop，不保存或回显原文。execution的outer_launcher_started仅表示capture的外层Popen启动，返回后为true，capture异常为null；sdk_execution_observed仅在九场景及完整post检查通过时为true。捕获异常另记录capture_failed=true和固定code，whole namespace仍unknown。同目录不可重跑，不自动删除失败材料。

静态命令（不启动 SDK）：

```
.venv/bin/python scripts/pi-probe-reviewer-sdk-process.py prepare --directory /tmp/rotom-reviewer-sdk-process-probe-20261005-review02
.venv/bin/python scripts/pi-probe-reviewer-sdk-process.py preflight --directory /tmp/rotom-reviewer-sdk-process-probe-20261005-review02
```

未来另获明确授权并经主代理审查后，唯一运行入口才是：

```
.venv/bin/python scripts/pi-probe-reviewer-sdk-process.py run --directory /tmp/rotom-reviewer-sdk-process-probe-20261005-review02 --native-reviewer-sdk-process-probe
```

该命令当前 not-authorized / not-run。结果路径 work/reviewer-process-result.json，摘要仅 schema_version/status/cases/product_gate；execution.json只保存计数、固定状态/错误与未独立观察的scope结论。CLI不接受候选、factory、配置或test seam覆盖。

默认验收 Python父只 fake capture/临时文件，Node只自有注入 adapter/child EventEmitter 与实际 transport/header验证，不启动 process/Worker/第三方包。

首轮review01只有静态准备，未运行；独立审查发现post work清单遗漏P2，六个fake红例复现后修复，原材料保留且因controller漂移失效。修复后Python父108项通过；未改变MJS/Node fake9项的固定来源。当前材料目录 `/tmp/rotom-reviewer-sdk-process-probe-20261005-review02`，plan.json SHA256 `e0bdeebde42a7a76c5a5dcecfeb2eb5ddb22b5f4a1ab47a549d8037b7dd015c0`；12 source files / 10 own controllers / 18498 candidate entries，prepare成功；没有started.json。来源哈希见 `/tmp/pi-risk-sdk-process-native-final-hashes.json`。当前仅prepared，native/self-child/Worker/SDK execution全部not-run，product_gate=false。
