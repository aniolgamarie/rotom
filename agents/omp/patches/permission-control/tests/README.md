# Permission-control patch tests

本目录保存应用到锁定 OMP v18.3.0 源码后的 bridge 集成测试。测试直接调用
patched wrapper、真实 `BashTool`、native prepare/commit 和桥的一次性 consume。当前基础组覆盖
严格受管 settings、准备阶段零 native/process/worker/network 副作用、批准后精确一次 `Shell.run`、
原始取消信号、target/environment/shell/settings 漂移永久失效、受管会话配置删除降级防护，
以及真实 provider safety metadata 的无 UI 失败关闭。reviewer、tiny 与 installed-only 加载器由
后续补丁任务加入，本轮不以占位 fake 声称覆盖。

基础补丁保留默认 kernel 行为：纯 interceptor 未命中和 auto-background 开关本身不再成为人工
原因，interceptor 命中在 permission UI 前返回原无执行引导；direnv auto 只有同步完整搜索链证明
没有有效配置时才可继续，链摘要漂移使计划失效。Bash 冷 snapshot 仍先走人工原路径；该次执行
只有使用宿主实际生成并重新读取的 snapshot、保守验证固定结构/options/相关命令名无 shadow，且
绑定同一真实 `Shell` 实例后，才建立后续低风险命令可复用的连续性。并发、取消、未知命令、重建
或无法追踪的状态变化会永久使该连续性失效，之后的 `pwd` 也不能重新认证。命令跟踪使用严格
core shell parser 的完整只读命令白名单；支持已证明的 `&&`、`||`、`;` 与 pipe，换行、动态展开、
输出重定向或未知命令均不属于可跟踪输入。占用状态同时按真实 `Shell` 实例共享，避免 snapshot key
与 continuity key 别名并发。缓存路径或单个全局布尔值不构成上述证明。

`bridge.preload.ts` 的 `__ompBridgeKernelEvidence` 只是假证据源：它提供可变摘要和 fake native
Shell，patched 源码仍须自行关联实际 Shell 实例并作 eligibility/revalidate 判断。测试不会把该对象
本身当作批准或状态证明。失败先行日志 `/tmp/rotom-host-t075-red.log` 记录锁定基础源码为
12 pass/4 fail；实现后的正式补丁组覆盖相同四项及 shadow/options/未知 mutation 反例。

auto-background 的实现接缝分成审批后的异步 stage 与最终同步 start。stage 只分配 artifact，
不注册 job 或启动 backend；取消、配置或绑定漂移时 backend 保持为 0。最终由
宿主私有 ledger 的 consume 回调同步 revalidate 并调用 start，中间不得 await，manager 的 callback
不得在 stage 时启动。T022 的自动 allow、native source 顺序和单次 UI 用例将在 controller 注册
接口接入 wrapper 后使用同一真实接缝；本组验证 host-private `onBeforeStart` 在 manager run callback
内最终 revalidate，随后同步 consume 并发起 native `Shell.run`，start 返回前已恰好启动一次。
staged native 继续使用 job 的取消信号、artifact、tail/progress 与 minimizer 保存回调；取消或漂移
会删除已分配的空 artifact。

最终 start 只有在同步 `onBeforeStart` 成功后才把 stage 标为 started。ledger consume、adapter.start
同步抛错或 callback 前异步拒绝都会永久失效计划并恰好清理一次未启动 artifact；callback 已成功、
backend 已启动后的执行拒绝保持 consumed，既不恢复许可也不删除活跃 artifact。

默认测试不得启动 OMP CLI/TUI、真实 worker 或模型，不得联网、安装依赖或写入真实
HOME/XDG/OMP home。完整 patch series 必须先干净应用；只测试与补丁无关的 fake bridge
不能作为通过证据。

`bridge.integration.test.ts` 和 `bridge.preload.ts` 设计为复制到 patched 源码的
`packages/coding-agent/test/` 后运行，因此其中 `../src/...` 导入始终指向刚应用完整 series 的
真实源码。preload 必须先于测试模块执行，确保 import 阶段已经替换 native addon 并阻断
`fetch`、`Bun.spawn`/`spawnSync`、`node:child_process` 和 `Worker`：

```sh
bun test --preload ./packages/coding-agent/test/bridge.preload.ts \
  ./packages/coding-agent/test/bridge.integration.test.ts
```

测试不执行 Bash command，不启动宿主 CLI、真实 native addon、provider、worker 或模型。

`host-identity.integration.test.ts` 单独使用真实只读文件系统 API，避免 bridge 的全局 `node:fs`
mock 改写身份检查语义。harness 把仓库受管插件树复制到临时源码外侧的 fixture，并用 Python
`permission_plugin_digest` 生成期望摘要；测试由宿主 TypeScript 独立重算完整树摘要，覆盖单一候选、
实际 `index.ts` 路径、receipt 字段、字节漂移、重复候选、suffix 冒充和入口/receipt 链接拒绝。
`identity.preload.ts` 仍在模块加载前阻断 fetch、process、child_process 与 Worker，且 Python harness
继续用 seccomp 禁止网络：

```sh
bun test --preload ./packages/coding-agent/test/identity.preload.ts \
  ./packages/coding-agent/test/host-identity.integration.test.ts
```

本 tranche 还把 `/permission-control` 放在 extension input handler 与普通 prompt 队列之前，并且只在
TUI editor 的真实提交路径记录授权文本。只有严格匹配且已经处理的 OOB 命令会提前返回；相似前缀、
含换行而未匹配的文本仍进入有界授权账本，超限后 completeness 永久降级。wrapper 现在对真实 native
`BashTool` 使用同一宿主 orchestration：prepare 后由 core policy 决策，ask
最多调用一次 native UI，批准后才 stage，并在 adapter 的同步 start callback 内完成 ledger consume。
测试先用人工路径建立真实 Bash snapshot continuity，再验证有界空上下文中的低风险 read proof 自动
启动一次且不重复提示；一旦存在尚未结构化解释的真实用户消息或上下文不完整则固定 ask，无 UI
失败关闭且 backend 不启动。锁定 pi-shell 内置命令范围为 `pwd`、`ls`、`head`、`wc`，以及显式普通
文件或管道上的 `rg`，每次都绑定有界真实目标证明。`rg` 递归、Git、输入重定向、隐藏枚举、`ls`
非 numeric 长格式、绝对或逃逸路径继续人工；不以 `verified: true`、process PATH 或 fixture 布尔值
扩大覆盖。

主审接线只接受宿主证明为被动的认证来源和同步物化 headers：配置中的 `!command`、未知 resolver、
OAuth 或无法订阅 credential generation 的宿主不会进入自动主审。认证、端点、model、input、deadline
与原始取消信号按单请求冻结；已知凭据只留在宿主闭包用于递归审查最终 envelope 的所有字符串和值，
不会传给扩展、审计或状态接口。宿主捕获并复制实际 primary/tiny 原始回包，再独立 decode 和重建完整
pipeline；扩展自报的 state/outcome/model/source 不参与授权，tiny 也只有在宿主已证明 primary 失败、
输入和 caps 精确匹配后才能启动。fallback 只能把结果收紧为 ask/deny。设置、model、session 与
credential generation 变化会立即撤销旧许可，切换或恢复会重建 session ledger 且不继承 mode。

自动执行前，宿主把固定字段 pending 审计记录追加到 session 并 flush；同步 consume/start 临界区后再
异步追加 consumed 或 invalidated 终态，human allow 链在两条记录中保持一致。operation digest 使用会话盐，
审计接口缺失或持久化失败会使 bridge 降级并阻止后续 backend；已经启动的 backend 不伪装成撤销。
status/explain 与裸命令 usage 只读，不刷新 generation 或延长许可，并显示最近一次完成分析后的真实覆盖。

permission-control variant 另有 `disabledModelProviders`：模型 registry、model browser 和 model hub 统一优先
读取它，未配置时才回退官方 `disabledProviders`。隔离测试确认该 variant 仍用原 18 项资源 denylist 阻断
Cursor 项目/用户资源，同时用 17 项模型 denylist 让 Cursor 模型可见；official 配置不生成新字段。

主审与 `remoteFallback` 使用两个分别冻结、最多一次的 transport。主审 OAuth/unsupported、注册缺失、超时、
服务失败或严格输出失败时才允许不同模型的 remote；有效 allow/ask/deny 和取消都禁止二次审查。宿主按实际
回包独立解码并重建 primary/remote/tiny 的模型身份、调用数和最终来源，远程有效结果可进入同一机械 policy，
主审失败状态不会把它误降级。remote 真实 deadline 取消证据允许剩余 5 秒进入 installed-only tiny；有效
primary deny 后伪造的 remote allow 在发送前被拦截。status 保留配置主审身份与 `reviewerHealth`，并单独显示
remote 身份/健康；模型或凭据 lifecycle 变化会撤销旧 binding。
