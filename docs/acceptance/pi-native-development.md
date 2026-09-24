# Pi 原生验收开发记录

本记录用于定位原生执行器与生产代码的联通问题。**不代表最终冻结候选、Linux 平台或真实账号验收通过。**

## 已观察到的真实行为

- `host-resources` 开发场景通过：实际加载 Pi SDK 0.84.4 和扩展；唯一 manager 的并发上限为 2；通过受控 `read` 读取合成 Git 项目；完成两次本地合成模型请求；源文件保持原样；退出码 0，全部执行终止。
- `permission-denials` 开发场景通过：真实读取请求指向存在的私人夹具配置；在 ordinary_prepare 被拒绝，没有普通文件访问准入记录，宿主退出 0，全部执行终止。批准会话提示不会扩大硬权限。
- 加强后的 `taskkeeper-budget` 开发场景通过：仅两次实际请求，拒绝后续请求，并在收据中保留 BUDGET_EXHAUSTED / BUDGET_DENIED；任务 BLOCKED，全部执行终止。单纯 BLOCKED 不再满足验收门槛。
- Task Keeper 完整 inspect 和 fix 开发流程均通过：真实候选、子进程、构建检查、pytest、独立审查和最终收据形成完整链路；源项目保持不变，所有执行终止。inspect 共 12 个受监督执行/10 次请求，fix 共 16 个执行/14 次请求。
- quota 和 missing-result 开发场景通过：分别验证合成 429 后等待及显式停止、当前 worker 的明确 EVIDENCE_EMPTY 被拒绝；全部执行终止。
- 第二视角、真实 worker 停止、一次性定时和暂停恢复也通过开发验证；暂停恢复使用新的执行尝试，最终收据通过且全部终止。
- Linux managed 的父宿主丢失场景通过：真实 worker 开始请求后，用已核验 pidfd 中断父 Pi，观察到 worker 撤权和全部执行回收；其他配方/平台未因此通过。
- 默认测试继续使用假进程、网络阻断和临时 HOME；以上宿主运行属于用户已授权的独立原生开发步骤，没有真实账号或外部模型通信。

宿主通过记录：`/tmp/agentcfg-native-crvzkiqf/cases/host-resources-runner-3e8f02f3/controller-result.json`。
权限拒绝通过记录：`/tmp/agentcfg-native-crvzkiqf/cases/permission-denials-runner-4bb92bf8/controller-result.json`。
预算拒绝通过记录：`/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-budget-runner-af32dee5/controller-result.json`。
Reader 成功执行记录位于：`/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-inspect-runner-0ed9d554/fixture/`。该轮完整场景因等待超时仍为 failed，不能据 reader 的成功收据改成 passed。

后续完整流程通过记录：

- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-inspect-runner-62c17f2d/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-fix-runner-32f5d428/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-quota-runner-6862b284/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-missing-result-runner-5b8dcd09/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-second-view-runner-263f2147/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-stop-runner-f73bebec/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-schedule-runner-6d37e5fe/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/taskkeeper-pause-resume-runner-7266ba64/controller-result.json`
- `/tmp/agentcfg-native-crvzkiqf/cases/parent-loss-runner-1593c4a7/controller-result.json`

当前全量离线回归：`/tmp/agentcfg-pi-mock-20260919-native-controls.json`，1532 Python 测试、7 个子测试、304 Node 测试通过；运行期间没有相关源码修改。它不能替代最终 native/live 证据。

后续委托与冷构建修订的完整回归：`/tmp/agentcfg-pi-mock-20260919-delegate-native-foundation.json`，1575 Python 测试、7 个子测试、307 Node 测试通过（UTC 04:38:32–04:39:42），运行期间没有相关源码修改。

pi-default 委托开发记录：

- 批次 CLI 通过：`/tmp/agentcfg-native-default-davgcm5t/cases/delegate-batch/controller-result.json`。三个核验结果、幂等重放、manager 和实际模型请求并发峰值均为 2，全部执行结束。
- 用户 CLI 八操作通过：`/tmp/agentcfg-native-default-_ye73jsc/cases/delegate-control/controller-result.json`。真实部署、启动/状态/轮询/等待/取结果/恢复/取消，保留新的 run 与 continuation_of；probe 单独保持未执行声明。
- 七用途模板循环在修复结束竞态后完成整组复验，见下方同一临时候选报告。早期失败记录保留。

## 同一临时候选的正式委托验收

报告：`/tmp/agentcfg-pi-native-delegate-candidate-20260919.json`，UTC 2026-09-19 04:47:23–04:52:22。

- `delegate-presets`、`delegate-control`、`delegate-batch` 全部通过。
- 源码快照：`/tmp/agentcfg-pi-lock-probe-60srl6k_`。
- 锁身份：`e3d0a45129ee3cb5291d2889a3cb67cbce843d8209ed075f569e62dd9f524a40`。
- 运行包身份：`71a6dd5904c3252d2ceec3ef625c27995a55d3b2820604847936dfb7a9eb7c42`。

本轮直接执行该源码快照自带的 verify-pi.py 和密封入口，没有注入开发控制器。它证明这份 Linux x86_64/pi-default 临时候选的 Pi 委托链路；仍不是仓库最终锁、Codex 后端、其他平台或真实账号通过证据。

## 发现并修复的问题

### Codex 官方 CLI 一致候选（2026-09-20）

[候选报告](pi-codex-native-candidate-20260920.json)，UTC 2026-09-19 16:57:07–16:59:49：

- `codex-native-readonly` 与 `codex-native-write` 均通过，使用正式候选入口，无开发注入。
- 源码、锁与运行包一致：锁 `49fe54e1a01e7ad568cd4f2ad7b37b2160efac8fd13f24b19ba2928446272c16`，运行包 `e476fd70eb3d8183885396908b4f70d1a93deaaa2d26e75198e77df6476739c1`。
- 官方 CLI 实际读取文件、尝试读取配置及账号文件、尝试写入；私有文件不可见，只读写入明确拒绝，显式写入只改变独立 worktree；核验收据与物理回收通过。
- 固定官方 Codex 主程序、code-mode-host、responses-api-proxy 和 Linux bwrap 的完整来源；其他三个架构只有归档与锁验证，没有原生通过声明。
- 仍为临时候选和合成服务证据，不是仓库最终锁、真实账号或整个 Linux 平台通过。Codex 控制操作、其他配方完整复验、cold-rebuild 和 live 仍待完成。

修复包括官方非致命启动提示／失败收尾序列、Linux 已登记子组的 pidfd 回收、完整沙箱资源，以及 default-deny 下运行代码／scratch 与私密目录的分离。
Linux 过宽项目根包住私有实例时拒绝，不通过更具体 allow 放开秘密。旧 escaped/unknown 记录保持不变。

本批全量离线报告 `/tmp/agentcfg-pi-mock-20260920-codex-native-policy.json`：1666 Python、7 个子测试、308 Node，通过时间 UTC 16:51:16–16:52:31。

### 普通取消与迁移冲突补充（2026-09-19）

- 普通取消：`/tmp/agentcfg-native-default-tiueapsi/cases/ordinary-cancel/controller-result.json`。真实 SDK 的 scout 请求到达合成服务后取消；SDK promise、流、manager 收尾确认，宿主退出 0、终止确认，项目不变。普通子会话在宿主进程内，未声称存在独立 worker。
- 迁移冲突：`/tmp/agentcfg-native-default-nun39cmu/cases/migration-runtime-conflicts/controller-result.json`。真实部署和宿主运行中调用正式 apply/sync/rollback，三者均拒绝活动冲突；结束后 apply 零变更；合成旧配置、未接管文件保持，合成旧账号未导入。
- 两项均使用当前第一方开发控制器与原密封 SDK，属于开发联通证据。失败尝试未覆盖；最终源码、锁和运行包一致的复验仍待执行。
- 原生 all 与冷重建补入遗漏场景；未确认进程终止后，剩余场景保留为未执行。冷重建阶段错误逐目标记录，第二条路径继续执行。
- verify-pi 执行报告新增结构和状态检查；报告生成成功与固定 scope 的发布批准保持独立。
- 完整默认回归：`/tmp/agentcfg-pi-mock-20260919-validation-completeness.json`，UTC 12:44:19–12:45:31，1612 Python、7 个子测试、308 Node 全部通过。运行期间未修改相关源码。
- 后续补充普通配方父宿主丢失：`/tmp/agentcfg-native-default-q4ynupa8/cases/parent-loss/controller-result.json`。通过真实 Pi 委托启动子执行，收到模型请求后中断夹具父宿主，观察 external 子执行撤权、reclaimed 和全部进程终止。该补充使用开发控制器；发生在上方全量回归之后，另有 Python 88 项和 Node 4 项定向回归通过。

### 此前修复

1. 原生验收器重复使用两层 HostSupervisor，外层会误判内层合法独立进程组。外层现只持有沙箱子进程句柄；应用执行由内层唯一监督者负责，超时走已认证用户取消入口。
2. Linux 扫描无关同 UID 进程时，读取不可访问的命名空间会打断扫描。现保留基本亲子与进程组关系；相关执行若身份仍不完整，继续保持 unknown 和停止保护。
3. bwrap 新 PID 命名空间需要独立会话，避免继承不可见外部进程组后出现 pgid=0。
4. `HostSupervisor.resolve_command` 的输入路径变量被环境清理循环覆盖，导致 worker 把 SSH_TTY 当成输入文件名。现使用独立变量，回归测试核对真实写入的 JSON 与启动参数一致。
5. 合成夹具移除多余的系统 Python 文件访问根；未来才生成的结果文件不作为已存在的保护根；普通工具场景显式批准合成 cwd 的会话提示，硬权限检查仍然执行。
6. inspect 和 fix 的检查预期分开：前者要求原文件内容，后者要求候选中的修改。多进程原生场景采用有上限的较长等待；超时仍判失败并检查终止。
7. 租约目录扫描与同一 store 的原子写入共用 RLock，避免把在途暂存文件误判为损坏。持久未知文件仍拒绝；对应并发与监督回归 37 项通过。

## 证据边界

早期开发探测使用工作区第一方控制器和场景入口，搭配较早快照的密封 SDK 运行包；后续同一候选验收的精确范围和身份已在上节列明。开发包装、输入、结果与失败记录保留在临时目录；原密封运行包未被改写。最终验收必须重新生成一致的源码、锁和运行包身份，再通过正式验证入口运行。

早期失败留下的 unknown 记录没有删除或解除保护。其他三个目标平台仍未验证。Codex、Cursor、MCP、web、代理和终端仍属于已选择的实网验收范围，不能因尚未执行改为 not-selected。

## 当前候选：9c4036ff（2026-09-20）

[候选输入](pi-candidate-9c4036ff.json) 固定软件来源、37个依赖来源、四配方锁、scope摘要及已安装的Linux运行身份。
[完整默认回归](pi-default-tests.md) 为1762 Python + 7 subtests、322 Node，全部通过。

当前四配方正分别运行两个全新 HOME/仓库路径的冷重建。每个任务先冻结一份源码输入；
两目标分别创建 Python 环境、重新下载/校验依赖和视觉文件、安装、部署及执行原生场景，不复制旧运行包或下载缓存。
结果位于 `cache/pi-validation/runtime-volume/cold-pi-*-9c4036ff/`，任务未结束前不记整体通过。

Linux Codex 新执行采用v3 PID命名空间证明。第一方内核 smoke 已验证 fork 后重新托管且独立组的后代随 PID 1 终止；
开发原生 readonly/write/control 均通过。内部 PGID=0 只通过不可变出生身份进行命名空间内外匹配，公共进程身份 schema 未放宽。
旧v1/v2 escaped/unknown、旧候选失败报告及两次冷下载失败均保留；它们不被新记录覆盖。

最新同锁完整冷重建结果及实际账号验证仍须独立记录。此节不将开发包装或单目标通过提升为整个平台通过。
