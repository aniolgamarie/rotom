# 官方 reviewer SDK 断网合成 SSE 探针

状态：用户已明确授权及同边界必要重跑；review02 九项官方 provider/SSE 断言全部 observed，父端退出 0，独立来源和原始工件复核通过。默认 Node 7 项、Python 62 项另属隔离测试。此前 run05 六项 SDK 接口探针注入自有 streamSimple，不覆盖真实 PiAI provider/SSE parser；本探针单独记录，不能借用原生通过证据。

当前来源覆盖：后续共享真实模型接线已修改自有 `sdk-worker.ts`、`sdk-worker-entry.ts`，并正在修改 `transport.ts`。上述九项观察只覆盖 review02 归档中的原字节，不能证明当前实现。原材料和已通过事实保留为历史证据；旧探针授权已经完成，不自动扩展为新进程组合或新模型契约的原生授权。

自有入口为 [Python prepare/preflight/run](../../scripts/pi-probe-reviewer-sdk.py)、[父启动器](../../src/agentcfg/pi_reviewer_sdk_probe.py) 和 [Node payload](../../scripts/pi-probe-reviewer-sdk.mjs)。不修改官方源码、vendor、缓存或二进制，不启动 Pi 主会话/Codex，不部署或启用 Full reviewer。固定官方候选为 Pi coding-agent 1.0.1 的安装切片、PiAI 1.0.2、OpenAI SDK 7.19.0，Node v24.14.0。package-lock SHA 为 `f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac`。

Node 仅在专用 CLI 参数与全部固定环境值吻合时执行。实际 SDK 在自有 Worker 内通过公开 provider/transcript exports 导入；不经过模型发现、SecretStore、账号、OAuth 或 refresh。私密 key 全为固定合成字符串。父侧自有 send 返回内存中的合成 SSE Response，从未调用平台 fetch、HTTP client 或外部模型；bwrap 网络 namespace 同时阻断其它网络路径。

## 固定观察与失败条件

| Case | 传输结果 | 决定 | 本地 send | 用量 | Worker |
|---|---|---|---:|---|---|
| allow | valid | allow | 1 | reported 5/3/8 | 已终止 |
| ask | valid | ask | 1 | reported 5/3/8 | 已终止 |
| deny | valid | deny | 1 | reported 5/3/8 | 已终止 |
| missing-usage | valid | allow | 1 | unknown，保持 null | 已终止 |
| wrong-model | transport-failure | 无 | 1 | unknown | 已终止 |
| canceled | canceled | 无 | 1，不归零 | unknown | 已终止 |
| response-limit | transport-failure | 无 | 1，无重试 | unknown | 已终止 |
| hard-deny | policy-blocked | 无 | 0 | not-sent，确认零 | 未启动 |
| human-required | human-required | 无 | 0 | not-sent，确认零 | 未启动 |

每个 case 独立 adapter，finally 中等待 close 并核对 Worker 的实际 terminate 结果。allow/ask/deny 区分保留，不把 ask 变成人类批准，不向执行许可或 Writer 接线。错模型只指服务商返回字段与固定请求不符；reported usage 不是账单或模型权重证明。

全部九项固定条件满足才写 `observed`，任意失败退出 5。父侧独立复核闭合结果、九 case 集合/顺序、具体计数/分类、stdout 摘要、退出码与运行后来源；`product_gate` 始终 false，不发 passed/许可。超时、日志洪泛、异常或未知清理不能通过，不补零用量，不覆盖旧结果。

## 准备与隔离边界

prepare/preflight 只读固定来源与安装切片，不执行 Node 或 SDK。prepare 只接受全新的 `/tmp` 后代 0700 目录，复制九个自有源文件至 bundle；工作目录初始只有七个空私有目录。完整候选普通文件/内部文件符号链接、版本、lock、Node/bwrap/timeout 二进制及自有父控制器均有来源记录；FIFO、外部链接、夹带文件、未知 plan 字段、漂移和重复 run 全部拒绝。

初次静态准备目录为 `/tmp/rotom-reviewer-sdk-probe-20261005-review01`，18,498 条 candidate 记录，九个自有源文件；prepare 和独立 preflight 均退出 0，native_started=false。plan SHA-256 为 `401b8244e2e304af8a67961127e3029d2ba0f06689982346b49f86375dee97bb`。稳定 Node payload SHA 为 `343de16bcb52340dedc7dd05ad587390e5db4699885809b6cd7f1275ba45bf40`，父控制器 SHA 为 `dbeb7aabfd680763a308f9aaa1325d88265115eb248ffb49306eac9fb8964a0d`；来源漂移须重新准备，不能直接复用旧计划。

原生运行只挂载以下来源：系统 `/usr`、`/lib`、`/lib64` 只读；固定 candidate 切片只读为 `/candidate`；固定 Node 工具链只读为 `/node`；已复制 bundle 只读为 `/probe`。仅本次私有 work 绑定为可写 `/work`，另有 namespace 内私有 `/tmp`、proc/dev。真实 HOME、工作区、账号、密钥文件与会话均不挂载。

父 Popen 使用 `env={}`、stdin DEVNULL、close_fds 与新 session；bwrap 固定 `--unshare-all --die-with-parent --new-session --cap-drop ALL`，只显式设置临时 HOME/PATH/XDG、离线/遥测关闭，以及六项合成 OpenAI 环境污染负控。Worker env 仅 OPENAI_LOG=off；父 payload 不临时修改宿主环境。公开 Node ESM 解析 flag 显式固定，不继承 loader 或 NODE_OPTIONS。

Node 全进程 60 秒截止、各 attempt 5 秒、close 3 秒；外层 timeout 95 秒加最多 5 秒强制终止，父 capture 100 秒截止。stdout 最多保留 64KiB 待闭合验证，stderr 最多 64KiB，仅记字节数后丢弃，不保存正文或其散列。超限或异常只回收本次启动器的进程组，管道在 wait 仍超时时也关闭；无法确认的 native 状态为 null，保留 started marker 与失败执行记录，禁止同目录重放。

具体命令（先准备，run 仅在本探针另获明确授权后执行）：

```text
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-reviewer-sdk.py prepare --directory /tmp/rotom-reviewer-sdk-probe-20261005-review01
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-reviewer-sdk.py preflight --directory /tmp/rotom-reviewer-sdk-probe-20261005-review01
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-reviewer-sdk.py run --directory /tmp/rotom-reviewer-sdk-probe-20261005-review01 --native-reviewer-sdk-probe
```

## 已有默认证据与限制

自有 Node payload 两文件已由 executor 实现、scout 独立审查；7 项测试覆盖九 case，实际仅导入临时自有 import-only 假 SDK，marker 确认七次导入，两个资格负控零导入。Python 父层最终 62 项默认测试全部 fake 子进程/读取/signals，包含来源漂移、固定挂载/环境、闭合输出、请求不退款、零调用、洪泛/异常清理及不可重放；不把这些记成官方 SDK 或 OS 运行证据。清理修复前的三个行为红例已保留。最初默认工具的祖先 UID 视图失败单列为环境不足，正常属主回归没有放宽原守卫。

候选整体与系统 readonly 挂载约束本次运行的可见/写入边界，但来源 snapshot/stat 不是防同 UID 并发替换的原子 module pin；系统动态库未形成完整不可变发行闭包。Node Worker 的环境 Data map 不是通用凭据隔离。正常成功只核对自有 Worker terminate，父执行记录的 namespace_termination 保持 not-independently-observed；超时失败也不冒充全 namespace 的独立终止证明。探针无共享 Writer、许可或预算资源，不能用其记录释放产品资源。

本授权请求仅拟覆盖上述九项断网、合成、无账号 SDK 观察及同边界修复后的必要重跑。真实模型质量、付费/外发、Codex、部署、默认启用、全产品隔离与性能验收均不包含在内。


## 原生 review02 观察与历史修复

review01 中 Node 九项全部 observed、SDK 启动器退出0，但父复核退出5：父 oracle 错把两个确认零发送的 qualification blocks 当作 unknown/null，而实际 transport 固定为 not-sent/0。旧父失败记录原样保留。保存真实Node返回为默认离线fixture，并复现一项 oracle 行为红例；仅修父分支及测试，SDK、请求/响应边界与九项断言未放宽。确已发送但无用量的场景仍 unknown/null，取消请求仍为1。

重准备的 review02 目录为 `/tmp/rotom-reviewer-sdk-probe-20261005-review02`，plan SHA `5cb5906def6b916d543c8fec4e4d693914c9c3b2989b26635ad3bd93551ad42e`。父 run 与启动器均退出0，verification=observed，stdout72字节、stderr0字节；九项完整有序，七个实际SDK Worker逐一关闭确认，两个hard/human资格负控零Worker/零send。平台send全为内存Response，共七次；HTTP、外部模型和真实账号调用均为0。

scout独立核对当前六个源码/测试/fixture SHA、九个来源和两个控制器，重新读取18498条候选记录（普通文件总223155286字节）与plan完全相同，精确版本和lock一致，未发现P1/P2。快照、两次历史原始工件及审查保存在`.cache/pi-two-profiles/run-20261004/risk-sdk-native-review02/`。源码进一步变更不把历史原生证据冒充新实现通过，按受影响边界重验。

本结果只验已授权的合成provider/公开SDK路径。完整namespace终止仍未独立观察，真实账号/模型质量/账单、权限与持久预算接线、产品默认启用仍未验，product_gate=false。原先的待授权段落只代表初次准备阶段，当前授权已闭合，不重复询问。
