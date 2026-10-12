# OMP 权限生命周期与工具环境验收

日期：2026-10-11。方案见[全链修复方案](../follow-ups/omp-approval-lifecycle-and-environment-2026-10-11.md)。本轮保持官方 OMP v18.8.6 / `f068751e2f1dbdbc195977776d47a26db8697495`，不修改宿主源码、官方二进制或私有执行接口。网络代理延后，执行模型套件、主动权限主审和备用模型选择不变。

状态：实现、离线验收与稳定差量复核已完成。2026-10-12 用户明确授权后，官方宿主隔离验收通过，进入合入和部署步骤；本机部署结果在完成后追加。机器可读记录见[验收证据](omp-tool-stability-20261011-evidence.json)。

## 行为变化

- 长期审批移入公开 registered tool 的 `execute`，`tool_call` 只做快速协议检查。模型并发两个槽位，人工 UI 单独串行；排队限时 120 秒，capture/recheck 限时 5 秒，已显示的人工 UI 不受旧 hook 的 30 秒期限限制。
- 用户待输入、参数、会话、模型、cwd、设置和代际变更使未执行审批失效。取消与 opaque Promise 的迟到结果不会取得执行权；切模式不自动终止已开始的命令，caller abort 和宿主退出仍传入执行 signal。
- 原生与 raw 入口共用一次执行账目。同一 session/toolCallId 不能重入或重放；切换 A→B→A 后也保留 A 的记录。执行前重核，原始参数对象与命令原样交给公开原生委派或 `omp.exec`。
- 原生 prompt 与执行绑定分别表达。人工批准不能覆盖未知路线、设置分裂等无法绑定的上下文；明确 deny 保留优先级。普通受管 Bash 初始化仅提供路径元数据与未知效果证据，不读取 rc 正文，不声称 snapshot 或副作用已被证明。
- 普通命令仍先送模型，语法分析只作为辅助。完整多行凭据在送审与人审显示前遮蔽；注释伪槽位或复杂动态秘密无法安全表示时，以 `INPUT_INVALID` 阻止发送、询问和执行，避免把真实执行操作遮掉。无法识别的未知秘密仍是此检测器的能力限制。
- Reviewer 响应按流计数，超过 64 KiB 即停止/取消读取，不先读取完整响应。合法 ask/deny 不寻找更宽松备用；服务失败保留固定类别。
- 每次请求终态审计保留关联摘要、固定原因、尝试类别与阶段耗时，不保存命令、用户文本、模型正文或异常正文。`explain` 可显示当前排队/审批/执行阶段；raw 执行抛错记录运行失败或取消，不伪报为未执行的设置错误。

## 工具环境与存储

新部署保留启动者 HOME、原 XDG 值与运行目录，并继承明确名单中的 Git、zsh、动态库、Python/Node/虚拟环境路径。未知终端变量与环境密钥不自动继承；显式机器声明仍通过现有接口生效。本轮没有改变代理继承策略。

管理器生成相对 `PI_CONFIG_DIR` 并保留原 `--profile`，使配置、认证、会话、history、blob、placeholder key、session owner 与 daemon 路径保持原位。物理 owner/layout 不改、不搬迁正文。已有 XDG OMP 根会改变存储选择时明确拒绝，不能静默切换账号或租约。

新执行绑定记录 HOME/XDG 与实际原生路径，并在启动前重核。旧部署可按已保存的隔离环境继续启动；兼容的旧来源摘要仅限定为已知旧值。新 binding 与旧格式 launch spec 混用被拒绝。环境变更通过现有 plan/apply/previous/rollback，不在 run 中自动迁移。

dotenv 来源检查覆盖实际 HOME、base config、活动 profile config、agent、项目及有效 NODE_ENV 的 mode/mode.local。保存契约决定早期有效模式，prepare 后及 spawn 前再核对；检查存在性和链接，不读取 dotenv 正文。中性操作也核对实际 cwd dotenv。此边界是配置来源门禁，不是文件系统沙箱。

kernel 默认关闭将 cat/find 等强制改用专用工具的 Bash interceptor，降低批准后仍被工具拦截的失败。其五条规则保留，用户显式开启时遵循官方行为；read/glob/grep 工具与原生 deny/prompt 仍存在。

## 验证证据

| 层次 | 结果 | 范围 |
| --- | --- | --- |
| 当前 standalone 默认入口 | 423 pass / 0 fail，106,331 assertions | 10 个包根测试文件；假模型/原生委派/用户 UI，阻断网络、临时 HOME |
| 冻结历史集合 | 11,473 条预期继续核对 | 原历史/差量不重生；11,472 条有效请求进入假模型，1 条无效请求拒绝；不执行语料命令 |
| 官方 SDK 接线 | 12 pass / 0 fail，75 assertions | 官方 wrapper/runner/adapter 的实际源码，25 个入口/闭包模块导入前核验固定 SHA；包括快照 cwd 与实时 cwd 分离；外围 IO/Settings/provider 使用明确替身 |
| 严格类型检查 | exit 0，旧 SDK 文件 0 | TypeScript 7.0.2，解析 2,535 份官方 18.8.6 SDK 源文件；缓存第三方类型依赖不等于新宿主构建闭包验收 |
| 环境和管理器回归 | 全量 1,205 passed；7 项失败所在的三个模块修正后 35 passed；7 项退休 skip | 全量范围为 OMP 与通用 runtime。失败为旧环境断言/fixture接线，修正后只重验受影响模块，未重跑全量；HOME/XDG、dotenv、混合契约拒绝、环境-only 回滚与账号/owner 哨兵通过 |
| 官方 CLI 隔离 smoke | exit 0，9 条执行成功 / 1 条 deny，zsh 通过 | 临时 HOME、私有网络/PID namespace、本地假模型、虚构凭据；reviewer 9 次，主模型假服务 2 次，审查并发最高 2，外部请求 0 |
| 真实 reviewer / Cursor | 本轮未调用 | 追加授权余量仍 2；假模型通过不代表远程服务可用或真实 Cursor 并发已验 |
| 本机部署 | 本轮未执行 | 没有修改本机密钥、真实 rc、认证库、会话或当前部署 |

默认入口为 `tests/test_omp_standalone.py` 的两个独立 Bun 子进程，避免官方 SDK `mock.module` 污染生产套件。缺 Bun/SDK 明确 skip，错误 SHA/无效可执行文件明确失败，不将缺材料记成通过。退休的宿主补丁测试保持退休。

相关默认命令：

```sh
python -m pytest tests/test_omp_standalone.py -q -s --basetemp=/tmp/rotom-tool-stability-final-ts
python -m pytest tests/test_omp_*.py tests/test_runtime.py --ignore=tests/test_omp_standalone.py -q --basetemp=/tmp/rotom-tool-stability-omp-final
```

阶段失败与修复保留在忽略的 `.cache/worktrees/omp-tool-stability-20261011/.cache/`：初次 Python 预期仍指向旧 HOME；默认 TS 全量发现 fake native decision/reason 不一致，以及 raw 已验证 clone 场景的人工确认与未知执行绑定被混同。分别修正测试契约与生产区分后再验收，没有修改冻结历史场景以迎合实现。TypeScript JS launcher 曾因缓存原生子包解析失败而未启动，随后直接使用已校验的同版原生编译器；失败日志不计为通过。

独立最终 review 发现并修复跨行脱敏隐藏副作用、人工越过无法绑定路线、会话返回重放、新旧契约混用、旧 HOME 误判来源和官方快照 cwd 的实时失效缺口。稳定差量复核后无遗留 P1/P2。审查使用 executor 角色，其工具声明配置为 `gpt-6.1-sol / medium`；类型材料定位使用 scout 角色，其工具声明配置为 `gpt-6-luna / high`。原子消费、取消和部署语义由主代理决策并验收。未验证宿主状态分别记录，不能用早期审查结果代替。

## 2026-10-12 官方宿主验证

官方二进制和本次生产插件实际启动；HOME、XDG app 配置/Unix socket、用户 bin、Git 全局配置、显式 Bash rc 函数、zsh rc 函数与非秘密变量均按合成预期工作。deny 哨兵没有产生文件。没有启动真实 Cursor、付费主模型或真实 reviewer，也没有读取真实用户账号、密钥或 rc 文件正文。

首次 CLI 在模型前因根文件系统仅余约55 MB而不能解包内置组件。释放本轮重复二进制副本，并把已完成 pytest 的临时证据迁至本轮忽略缓存，保留文件、链接及 FIFO 负例，未删除用户数据。重试又发现隔离脚本关闭 Unix socket 后未 unlink，造成后续 worker 在 CLI 启动前停止；修复仅限测试脚本的已核验 socket 路径。中间尝试的日志与最终通过日志分别保留，不将旧 result 文件当作当次成功证据。最终运行使用原正常缓存位置，未使用 native 目录覆盖；官方宿主、生产源码和本机配置在此验证阶段均未修改。
