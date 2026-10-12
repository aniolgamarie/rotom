# Main SDK scope probe preparation

Status: **current run08: eight synthetic native SDK scenarios observed, independently reviewed and Root accepted**. Historical SDK6/RPC5 authorization is closed and does not authorize this probe. Default JSON plan tests do not import SDK or run its native entry. Preparation is not Base product acceptance. See the current frozen material below; the repository template intentionally remains non-executable.

The candidate is the existing readonly Pi 1.0.1 / pi-ai 1.0.2 closure:
`.cache/pi-two-profiles/run-20261004/modern-base-isolated-install-preparation-review01/install01/installed-tree/pi-base-1e4f9e6dc96d1083ed6b201deef2356cea8dcf743839db887f703f7ae386a76f`.
Node is fixed 24.14.0 at `/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0`.

## Planned observations

Eight fresh own temporary sessions test these claims; each must report its own observed/failed/not-run result. These are planned assertions, not observed SDK behavior.

1. Real public ModelRuntime creation, own synthetic Provider registration, then the own scope Proxy remains `instanceof ModelRuntime`, leaves original target descriptors unchanged on scope creation, and is consumed by real public session services.
2. Ordinary main prompt through own `createOfficialSessionFactory` produces exactly one synthetic faux sender call and a valid configuration snapshot.
3. Actual `session.modelRuntime.getAvailableSnapshot()` and root-exported `new ModelRegistry(scope.modelRuntime).getAvailable()` list only the manifest model. This is **SDK public available catalog**, not execution of the RPC `get_available_models` protocol.
4. Public `session.setModel` successfully changes to a same-provider out-of-range model; the subsequent prompt cannot invoke the sender. A setter failure is reported as an unobserved planned mutation, not hidden by catch.
5. Public `session.setModel` successfully changes the selected pair's API; the subsequent prompt cannot invoke the sender.
6. Real manual `session.compact` produces a compaction entry using the synthetic summary sender. Dispose and reopen the own private JSONL with public SessionManager.open and the same own session factory; configuration/manifest constraints remain. Own failed/unfinished task sentinels remain in original custom-message entries and the synthetic compaction summary. These are synthetic session sentinels, not Task Keeper/Durable recovery or proof that a real model preserves task semantics.
7. Cancel a main prompt while the own Provider's synthetic auth resolution is delayed; assert the public resolver received an AbortSignal that became aborted, release late auth, settle cancellation, assert sender count zero.
8. Cancel an actual main prompt after the synthetic sender starts but before its response resolves; release late response, assert no additional send or successful late assistant commit.

`fauxProvider`, `createProvider`, `ModelRuntime.create/registerNativeProvider`, `createAgentSessionFromServices`, ModelRegistry, SettingsManager, SessionManager, and AgentSession methods are fixed candidate root/public APIs. The Provider supplies only synthetic API-key auth and side-effect-free check; no real account/provider credentials or environment lookups are used. No SDK namespace, class method, prototype, source, vendor file or private hook is patched. The own initializer module is pinned as an integration input; this probe constructs the real runtime via public APIs before registering the own Provider and tests the own scope + session services. It does not qualify the initializer's real provider/account provisioning path.

## Freeze and authorization gates

`tests/fixtures/pi/main-sdk-probe/plan.json` intentionally says `requires-final-freeze` and has no source/package pins. Runtime rejects it. Root's initializer/session composition is still being finalized. After that composition stabilizes, Root must independently freeze the complete own transitive runtime source closure and actual installed candidate bytes/receipt identity, place those SHA256s in the closed `source_pins`/`candidate_pins`, and set state `frozen`. Freeze every own runtime `.ts` source and the actual candidate full tree receipt, not merely the two package.json files. `prepareFrozenPlan` provides the readonly preparation path described below; the package pins are auxiliary version bindings, not closure proof. Preserve a receipt of this final identity and readonly mount invocation. Do not reuse this preparation identity as final native input approval.

`scripts/pi-probe-main-sdk.mjs` exports `validatePlan` and `buildInvocation`; both are inert pure preparation functions. `buildInvocation` returns argv/env, never starts a process. Root supplies exact absolute **already frozen** host source/candidate/Node/fixture paths and a fresh private `/tmp` or `/data` work directory. Actual future execution needs one separate user authorization covering the final frozen package and all eight scenarios. No such authorization is sought or inferred here.

The returned invocation requires an empty parent env and uses unshare-all (network disabled), no capabilities, readonly `/source`, `/candidate`, `/node`, worker/fixture, only private writable `/work`, proc/dev and private tmpfs `/tmp`. It symlinks `/probe/node_modules` to the candidate for root package imports. Its fixed environment uses private HOME/XDG/TMPDIR, empty PATH, telemetry off. Native entry checks environment, versions, frozen pins and Linux before dynamic SDK imports. It writes `/work/probe-result.json` (exclusive 0600), private session/config files, and bounded nonsecret observations; underlying errors, message bodies and credentials are never printed. Each case has a five-second deadline and the entire future probe sixty seconds. No subprocess API is present in this worker. No Pi TUI/Codex/MCP, live model, account, external network or user project is involved.

## Default verification

Eight default checks include a tiny own temporary tree positive and extra/changed-file negatives for the readonly full receipt checker; they never read the actual candidate. Only the repository guarded mock runner with fixed Node24 may run `tests/fixtures/pi/main-sdk-probe/plan.test.mjs` now. It checks closed plan/versions/deadlines, required freeze, pin paths, readonly mount arguments, and private writable work without SDK import. At executor preparation, native execution, runtime ABI, compaction/cancellation and RPC products were unverified. Current eight-case SDK observations are recorded below; RPC process/product qualification remains unverified. Any future public ABI mismatch or failed cancellation assertion must be reported to Root without patching upstream or weakening the planned oracle.

## Static resolution and full-tree preparation

The preparation-time literal transitive own import closure is recorded in `.cache/pi-two-profiles/run-20261004/base-main-sdk-probe-preparation-review01/source-import-closure.json`: ten own modules, relative own imports and `node:*` only, no bare package or dynamic SDK imports. Thus these scoped/session entrypoints do not require `/source/node_modules`. Empty resources/extensionFactories do not reach own runtime-module, web/MCP transport or delegate modules. This fact applies to the captured source closure and must be rechecked after final source changes.

The native worker resolves root SDK packages from `/probe/node_modules -> /candidate/node_modules`. Official `dist/core/extensions/loader.js:40–66` builds aliases using its own package import.meta.url/createRequire and package-relative or import.meta.resolve paths, all under the readonly candidate node_modules; it does not resolve from `/source`. No selected external extension path is configured. This is static resolution evidence, not executed jiti/resource-loader qualification.

The original complete receipt is `modern-base-isolated-install-preparation-review01/install01/installed-tree-inventory.json` (about 5.1MiB; includes 16,653 entries across the official npm package and sibling resources). Its original generator is `executor.py:260` installed_file_pin and `:317` preserve_installed. The latter copies a tree and is not a readonly verification helper; this preparation does not call it.

The owned `tests/fixtures/pi/main-sdk-probe/candidate-inventory.mjs` exports `verifyCandidateInventory({candidateRoot,receiptPath,receiptSha256})`. It checks the whole exact tree keyset (no added/missing entries), regular file sizes/hashes, tightened docs0600/scripts0700/directories0700 modes, contained original relative symlinks, file identity before/after reads, and fixed original count/depth/64MiB-file/512MiB-total limits. It returns only nonsecret count/hash observations and never copies or mutates the tree. This is a readonly point-in-time check, not an atomic same-user immutability guarantee.

The worker's `prepareFrozenPlan({plan,sourceRoot,candidateRoot,receiptPath,receiptSha256})` is an inert exported **outer preparation function**, not a process runner. When Root later calls it, it reads/checks the full original receipt/tree, pins all regular flat runtime `.ts` sources plus auxiliary candidate package metadata, and returns a frozen closed plan. It does not write files, start a child, import SDK or authorize native execution. Root must independently supply and freeze the original receipt SHA, stage the returned plan and exact receipt bytes as `candidate-inventory.json` with the owned checker in the readonly fixture directory, pin worker/helper/fixture/Node artifacts, then use buildInvocation's argv under a separate authorized runner. Native entry additionally rechecks the complete receipt from the readonly fixture against `/candidate` before SDK imports. Frozen plans without a full candidate_inventory declaration reject. The executor preparation did not call the checker on the real candidate. Root subsequently completed the readonly package-root freeze; the current material below records that distinct operation. SDK/native execution remains unperformed.


## 当前冻结材料（review01）

2026-10-10：`.cache/pi-two-profiles/run-20261004/base-main-sdk-frozen-review01/` 保存冻结 worker、12 个完整自有传递模块、fixture/plan、只读挂载命令与工具身份。plan SHA256：`72d653f84afc0e76e9c586e66dded26181c295eed64d8dabdc58c4742fc13225`；worker SHA256：`ac2b899367f308cba62380cb148e239084fe5fec1620581f210b19bd57fc788d`。

只读冻结准备已实际核对整个将挂载的官方 npm 安装包：16,531 项、15,073 个普通文件、123,413,022 字节。原安装收据还包含 122 项旧 runtime/supervisor/licenses/vendor 兄弟资源，均不挂载；`receipt-scope.json` 明确记录收据投影，不把它们算作本探针验证。当前自有来源从单独 `/source` 只读挂载。冻结准备未加载 SDK；默认计划/收据正反例八项通过。

范围模型场景要求先观察公开 setter 成功变更，再验证后续请求零发送；认证取消明确观察 resolver 的 AbortSignal；摘要 sender 检查输入里含两个合成哨兵。合成摘要输出不证明真实模型的语义保真。每场限时五秒，整体六十秒；超时竞速本身不取消底层 SDK 操作。外层仅回收此次启动的隔离进程，保留专用临时 work 和失败记录，不能宣称目录已清理或整个产品进程隔离已验收。

用户已明确授权原冻结包的同一八场景及同边界必要修复重跑，当前执行结果如下。不读取真实账号，不调用真实模型/外网，不启动 TUI/Codex/MCP，不部署或切换默认入口。AGENTS.md 的“真实 smoke 为独立显式步骤，需用户明确授权”适用于本步骤；独立默认实现继续。


## 已观察结果（run08）

`.cache/pi-two-profiles/run-20261004/base-main-sdk-run08/`：八个场景全部 observed，exit 0，stdout 1,283 字节、stderr 0，stdout 与保存结果相等；12 个自有模块与当前源码一致。当前 plan SHA256：`61fc100dd16e0825cb2e382be4a6e98c16283c8ed33750ca0ad22cff1451334a`。独立稳定审查没有本差量 P1/P2；Root 收据 `base-main-sdk-root-accept-review01`。

同边界修复包括：旧系统 bwrap 不支持 --clearenv，外层保持 env={} 并在 guest 精确校验环境；scope 显式验证/投影公开 AgentLoopConfig 的 loop-only 字段，不交给 Provider，未知字段仍拒绝；压缩可能合法产生 history 与 turn-prefix 两路请求，跨实际输入聚合哨兵覆盖，合成响应只回显当次输入里确实出现的哨兵，最终摘要及关闭重开仍严格核对两个哨兵。原失败、诊断及准备身份完整保留。getAuth 的公开 apiKey/env 槽兼容修复另有默认反例证据，不能将原实例 prepareRequest 的内部调用误记成进入 proxy 的 Main 故障因果。

观察到原实例类型/Receiver与真实会话消费、正常 main 发送一次、选中目录、越界模型/API 零发送、真实 compaction entry 与完整关闭/公开重开、取消 auth 的 AbortSignal 与迟到零发送、取消响应无追加发送/无成功迟到 commit。仅合成 Provider 和组件公开 SDK 链资格；不覆盖真实账号/provider、TUI/RPC进程、实际默认 launcher/服务/OS沙箱、产品隔离、账单或模型摘要质量。当前授权已满足并闭合；没有新的原生调用计划，整体 T021–T023 和 Base gate 仍需对应后续证据。
