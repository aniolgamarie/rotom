# Phase 14：公开插件接入原生 Bash 的隔离验收

2026-10-04，`feat/omp-native-bash-approval` worktree。基线 `7558475`，设计提交 `1dac0d2`。生产插件、配置与隔离官方宿主验证已完成；真实 Cursor 服务、合入主分支和日常部署仍未执行。本记录不能作为 Cursor OAuth wire 或模型质量评测通过的证明。

机器记录：[omp-native-bash-approval-20261004.json](omp-native-bash-approval-20261004.json)。规格与任务：[Phase 14](../../specs/004-omp-permission-control/tasks.md#phase-14cursor-原生-bash-智能审批)。

## 实现与身份

现有插件注册可选同名 `bash`，通过官方 `ctx.invokeTool()` 委托原生；保留 `permission_bash`，使用同一模型链及会话状态。`native_bash` 为可选布尔配置，省略关闭，kernel 明确开启；生成 sidecar 的 `nativeBash` 参与 policy identity。未修改任何 agent 上游、vendor、官方二进制或私有对象，也未扩大历史 patch。

钩子捕获真实 scoped Settings；执行要求有效一次性调用票据，绑定完整参数、cwd、会话、generation、模型和相关设置摘要。实际全局 Settings 必须与会话设置同源；原生 deny/prompt 下限不被模型或外层 allow 覆盖。未知 async/service/PTY 字段显式拒绝；敏感或不可核实上下文转人工，无 UI 时阻止。审批后改参、改设置、取消、切模式/模型/会话均不能沿用许可。

| 身份 | 值 |
|---|---|
| 官方宿主 | v18.4.5 / `79808c3bf8f8cd9826decc63e3e18b13035f64f8` |
| Linux x64 二进制 SHA256 | `42c710239b3fc30b9759424f973c6c143709935d5752be7eec8d7b011f40d864` |
| 普通锁 | `7d3c261942b428a2a461a202273014eec6fe694ef5cb417fb27b42e00e49af33` |
| 插件树 | `572d340ee622f87a764a5848c413b939fb24bd187ff681b993e14786c5e67355` |

普通锁通过管理器 `OmpBackend.resolve_lock()` 使用既有固定 commit 归档和 SHA256SUMS 离线生成，随后 `read_lock()` 复核；没有网络下载。与基线语义比较证明 tag、commit、source、assets、upstream 和解释器身份不变，只有本地包与受影响配方内容变化。

## 验证结果

| 层次 | 实际结果 | 范围 |
|---|---|---|
| 定向 Bun | 44 pass、0 fail、155 assertions | 当前独立插件、票据/竞态、原生下限、模型链和上下文 |
| 包级 Bun | 335 pass、0 fail、1240 assertions | 独立模块及历史纯核心；不将历史核心结果冒充新宿主通过 |
| 固定 pristine SDK tsgo | 退出 0、无诊断 | 真实官方公开声明，未伪造 SDK |
| OMP Python 五组 | 131 pass、7 skip、25.13s | permission/kernel/dependencies/pipeline/discovery；skip 是退休的 patched-host 材料 |
| 最终锁回归 | 31 pass、0 fail、26.62s | 刷新最终锁后的 kernel/dependencies |
| 官方宿主 JSON fixture | 24/24 pass | 临时 HOME、固定 loopback provider、原生执行与故障保护 |
| 真实 TUI 人工批准 | 通过 | 显示 Approve，实际 pwd 一次；reviewer 0 次 |

默认测试使用临时 HOME、假模型/子进程和隔离网络边界，不启动真实宿主。官方宿主和 TUI 属于独立、已有明确授权的 smoke；配置、账号、缓存均在本轮临时目录。无真实账号访问，无外部/付费请求，旧 102/102 账本不变。只停止本轮 TUI 临时进程，没有终止日常实例。

官方宿主证明普通 pwd 和读取管道可自动审查，原生 deny、pattern deny/prompt、有效 ask/deny、manual 无 UI、startup/.envrc、插件缺失/配置错误均不执行；主审失败或不支持可进入不同远程备用，有效 ask/deny 不进入备用。async/service/PTY 不触发 reviewer 或执行；审批后改参数返回 INVALID_TICKET，运行时规则变更返回 STALE_REVIEW。原生非零退出（exitCode 2）与 interceptor 错误保持原生结果，未自动重试。

TUI 采用固定执行 provider 两次响应、固定 title 一次响应，manual 不调用 reviewer。选择 Approve 后，第二次固定执行请求中的真实工具结果包含临时 cwd，证明不是仅打印批准文字。

## 首次失败与修复

首轮官方宿主 17 组中 16 pass、unknown-async 1 fail：官方校验对 `additionalProperties:false` 的 unknown issue 进行 coercion，删除 async 后才通知 tool_call，直接调用单元测试没有覆盖这条路径。实际只执行无害 pwd。修复为工具 schema 保留未知字段，hook 与 execute 精确拒绝；sidecar/公共配置仍封闭。最终 24 组复验包含新增 async/service/PTY 和后续钩子修改，全部通过。model-facing schema 可由宿主转换为 strict，本地拒绝保证不依赖 wire schema 或 TypeScript strict。

最后稳定 diff 审查补入两个边界回归。队列取消测试先出现 40 pass/2 fail：切模式恰在 acquire 返回后，旧请求虽阻止，却未释放 gate，后续审批超时；在两个 early-return 分支释放 gate 后通过。启动文件回归先出现 9 pass/1 fail：仅有 `.bash_login` 时仍被评为 allow；补入启动候选后转人工、删除后仍保持粘性不确定，原生 deny 优先。`.bash_login` 属于更保守的启动上下文范围：官方普通 Bash 使用嵌入式 Brush，snapshot 显式读取 `.bashrc`；这个回归不是实际执行 `.bash_login` 的危险证明。上游 snapshot 与 Brush 环境导入均过滤 BASH_ENV/ENV，当前标准路径不因这两个值额外转人工。上述检查未执行真实脚本或危险命令。最终代码复验 44 项定向、335 项包级、24 项官方宿主和真实 TUI，类型检查无诊断。

首次 TUI fixture 未声明 setupVersion，进入公开首次设置向导，未调用模型或工具；补齐 setupVersion=2 后通过。两次失败结果留在忽略的本机测试目录，没有删失败、改标签或冒充首次通过。

## 复现与限制

命令和日志位于 worktree `.cache/native-bash-review/`，缓存和终端原始输出不提交。纯测试命令为：

```sh
/tmp/rotom-omp-build-inputs/bin/bun test ./agents/omp/packages/omp-permission-control
.venv/bin/python -m pytest tests/test_omp_permission_control.py tests/test_omp_kernel.py tests/test_omp_dependencies.py tests/test_omp_pipeline.py tests/test_omp_discovery.py -q
```

真实宿主脚本为 `.cache/native-bash-review/host/run-proof.py` 与 `run-ui-proof.py`，不得纳入默认 pytest。固定 SDK 检查配置和日志在 `executor-logs/`，通过记录仅适用于本次固定版本/Linux x64。

执行由观察到的 gpt-5.6-sol/medium 完成插件实现和对应测试，gpt-5.6-luna/medium 完成源码/参数管线与规格独立证据，主代理负责设计、配置、稳定 diff、官方宿主和锁验收。最后竞态实现与验证由 executor 角色 gpt-6.1-sol/medium 完成，独立证据复核由 scout 角色 gpt-6-luna/high 完成。后续委派按最新角色配置执行，本记录不声称自动切换主代理模型。

首批支持新 CLI 进程从启动即加载插件。公开接口无法查询加载前已有的私有 shell snapshot 缓存；观察到未知 startup、不同 HOME 或继承函数后，在插件生命周期内保持粘性人工状态，删除 rc 不恢复自动批准。热加载到已有执行进程、完整 async/service/PTY/动态调度、其它平台和本地 tiny 权限推理未验证或明确不支持。这是应用层审批，不能控制所有其它工具、MCP/子代理和外部文件竞态。

真实 Cursor wire 和本机部署须完成各自授权与验收；不能依据本记录声称用户会话已经启用新版本。
