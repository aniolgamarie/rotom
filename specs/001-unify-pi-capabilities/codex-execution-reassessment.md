# Codex 执行边界重新评估

**日期**：2026-09-17  
**状态**：用户要求继续后，按官方 CLI 与原生工具路线实施；spec、权限/委托契约和数据模型已同步。MCP强制替换不进入默认路线。下文保留评估依据与修订清单，实施进度见implementation-progress.md；原生验收仍未通过。  
**触发**：用户指出 codex-delegate 本来通过 CLI 工作，要求重新评估引入 MCP 的必要性。

## 1. 结论

推荐调用链：

```text
Pi model_delegate 工具 / model-delegate 用户 CLI
  → 既有 AgentManager（Pi 调用时）与 agentcfg supervisor
  → 锁定的官方 Codex CLI exec / exec resume
  → Codex 原生工具，在明确授权、经过验证的原生沙箱内执行
```

model-delegate 统一任务提交、状态、取消、恢复、上下文和结果凭证；agentcfg 管理配置、依赖、实例账号、启动边界、工作区租约和物理生命周期。Codex 负责在该次运行的授权范围内选择原生工具和命令。

不把受控 MCP 文件/命令桥作为本次替换交付的默认条件。MCP 协议本身不提供权限隔离；桥是否安全仍取决于实际工具执行器、其他通道是否封闭以及子命令的系统沙箱。给桥增加任意 shell 后，也不能仅凭“经过 MCP”就获得每次文件系统访问的授权检查。

这不是恢复旧 codex-delegate：新入口仍为 model-delegate，旧技能、run-codex.sh、旧工具别名与七个可执行协调角色仍退出发布。七种用途模板保留。

## 2. 已核对的依据

### 2.1 冻结 starter 源码

使用基线 commit `c60599df39e6350123f7fb9378cfe63dc5ed814f` 的 Git 对象，未读取账号或运行历史，未改写 starter：

- `skill/codex-delegate/scripts/run-codex.sh`：直接构造 `codex exec` / `exec resume`，使用 JSONL 与最终输出文件；默认 read-only，显式 linked worktree 支持 workspace-write。其进程组监督、固定代理和全局入口发现需要迁移，但工具执行没有经过 MCP 替代层。
- `skill/model-delegate/scripts/backends/codex.sh`：同样直接构造 Codex CLI；已有 resume/cancel 适配，源版本声明 supports_write=false。真正的差距是写入、控制协议、可移植监督、隔离配置和凭证闭合，不是缺少 MCP。
- `skill/codex-delegate/SKILL.md`：要求显式真实 Codex、独立候选写入、不能重复启动未知 writer、显式恢复及独立检查结果。没有要求逐次拦截所有 Codex 内部工具。

旧功能不能简单等同于旧参数全部保留：隐式全局发现、固定代理、任意继承用户配置必须改为声明式来源；idle/hard timeout、交互审批选项、历史清理等高级入口还需逐项登记映射或说明处置，不能因改了入口便宣称全部兼容。

### 2.2 固定 Codex 版本

- [0.154.0 exec 接口](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/exec/src/cli.rs)提供非交互执行、JSONL、结果文件和显式恢复等基础接口；这些仍需目标平台 native 验证。
- [PreToolUse 实现](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/hooks/src/events/pre_tool_use.rs)中，部分错误分支只报告失败而不设置阻止执行标志。因此不能把普通 hook 当作可靠的逐工具撤权边界。这不否定官方 CLI 的原生沙箱，也不推出必须使用 MCP。
- 已下载并核对同一 tag 的配置 loader 与 [合并实现](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/config/src/merge.rs)：用户配置忽略选项不能直接等同于系统/云配置全部隔离，空 MCP 表也不保证清除继承项。这是两条路线共有的配置发现问题。

### 2.3 agentcfg 需求与架构

- FR-022、FR-028、FR-043：强调工作区互斥、未知保持保护、取消不等于终止、显式写入与恢复；可以按整个 CLI 运行实施监督。
- FR-032、FR-033、FR-044—046：要求统一入口、真实执行身份、结果与长任务控制，没有指定 MCP。
- 真正造成额外约束的是 [Permission Policy v1](contracts/permission-policy.md) 第1节的精确 command_ref，以及第5节对所有模式统一要求“每次实际工具动作前复核”。直接 CLI 不能被宣称满足同一语义。
- 宪章强调公共管理与真实原生适配，没有要求用同一个工具执行器替代每个宿主的原生工具。统一生命周期和状态协议，与保留不同宿主的执行边界可以并存。

## 3. 路线比较

| 路线 | 原生能力保留 | 逐工具授权 | 代价与结论 |
|---|---|---|---|
| 官方 CLI + 原生沙箱 + agentcfg 进程监督 | 最贴近旧委托方式；保留沙箱内动态命令与原生编辑 | 不提供 agentcfg 的逐次检查；按整次运行授权、停止收回 | 推荐普通 Codex 委托使用；必须明确契约边界与平台证据 |
| 官方 CLI + 强制替换 IO 的 MCP 桥 | 需要重建工具语义；当前固定命令引用明显限制使用方式 | 受控文件接口可做到；命令内部 IO 仍需系统沙箱 | 不作为本次默认迁移路线；当前原型不能视为完整 CLI 替换 |
| 官方 CLI + PreToolUse hook | 接近原生路径 | 已核对错误路径不满足严格拒绝要求 | 可作提示/观察，不能作为唯一保护 |
| 修改 Codex 构建 | 可定制 | 需要自己实现并长期维护 | 用户选择官方 CLI，本次不采用 |

配置隔离、账号归属、源工作区保护、平台进程终止和原生证据在所有路线中都不可省略；MCP 不能自动解决这些问题。

## 4. 推荐的两种执行边界

### A. 普通 Codex 外部委托：原生执行授权

- 保留 `delegate-readonly` / `delegate-write`；模式不会因为提示、模板或上下文而改变。
- 另行声明原生执行授权类型，绑定锁定 CLI、模型、cwd、可读写根、网络、原生权限配置、资源清单、超时和沙箱身份；字段由可信适配器生成，模型不能自行切换授权类型。
- readonly 保证业务工作区不可写；implement 仍需 explicit-write、allow-workspace-write、独立 worktree 和跨实例唯一写租约。
- 原生命令是在整次运行授权内执行，不逐条转成 tool:ID。该权限必须在原生执行配置中明确声明，不能从“允许 tk_read”之类的规则自动推导出任意命令权限。
- 父侧适用拒绝、秘密保护和源 checkout 禁写仍要实际实现。无法无扩权映射到原生沙箱的规则，启动前失败；例如“允许覆写但不许删除”不能直接当作同等的原生目录读写权限。
- 配置变更不原地放宽活动运行。应用新策略前先停止旧执行并确认终止；手工破坏运行配置或检测到失配时停止而不是继续认证。
- cancel/超时/撤权先禁止新的 agentcfg 派发与恢复，再停止当前 CLI 和所有被纳入监督的子工作；确认终止后才释放工作区。停止期间仍可能发生原授权范围内的操作，不能承诺零延迟工具撤权。
- 终态证据使用本次请求/运行时/授权、原生完成事件、最终产物、候选最终快照与完整终止证明。最终 diff 只证明候选的结果变化，不能代替沙箱对越界写入的实际防护，也不能冒充逐操作审计链。
- 任何已选择的 MCP、插件、嵌套 agent 或可脱离监督的服务都需独立声明和验证；“保留原生工具”不等于自动加载全部全局集成。

### B. Task Keeper 与 agentcfg 受控工具：细粒度授权

继续执行每次工具动作的 policy/grant/generation 复核、变更链和请求前预算门控。未经认证的外部 Codex 不能进入 managed 执行链，也不能作为不计量 helper。普通 Pi 受控工具的现有权限与 workspace 保护也不因 Codex 改用原生边界而放宽。

两种边界共用任务身份、supervisor、工作区锁、状态和证据格式；具体授权语义由适配器明确呈现，不能以一个“安全/可用”标志混在一起。

## 5. 需要同步修订的契约与任务

下表为本次路线修订清单；规范已按后续继续实施指令同步，任务勾选仍只反映实际完成。

| 文件/任务 | 所需调整 |
|---|---|
| spec.md FR-029、FR-043及执行实体说明 | 区分原生运行授权与受控逐工具授权；写保护、父 deny、未知互斥保留 |
| contracts/permission-policy.md §0/§1/§5 | 定义适用边界；原生 shell 不能伪装成精确 command_ref，运行级撤权不能冒充逐工具撤权 |
| contracts/model-delegation.md §3/§5/§7/§8 | 明确官方 CLI 原生工具、取消窗口、授权身份及 backend 对应的结果证据 |
| data-model.md、相关 schema | 添加可核验的授权/执行边界身份；明确证据版本兼容与失效，不接受模型自报 |
| T074/T075/T079/T088 | 覆盖原生 CLI 准入、沙箱可表达性、原生命令/文件事件、候选结果与物理终止；移除强制 MCP 替代作为完成条件 |
| T084/T086 | 保留 Pi/managed 的逐操作控制；不要将普通 Pi editor/checkpoint 的适配扩大为重建 Codex 工具栈 |
| validation-matrix.md、quickstart及验收报告 | 分别描述两种授权保证；原生未执行照实 not-run，不因换路线删除已选能力的验收范围 |

本次评估授权不用于修改本机账号、启动真实宿主或执行 live 验证。

## 6. 已有代码的处置

### 保留并复核

唯一 AgentManager、supervisor、跨实例写租约、Linux/macOS 物理身份与停止、start_unknown 不重发、结果凭证、模型/网络路线、上下文反馈、七模板与旧调用方迁移继续使用。普通命令 `tool:ID` 格式修复与父子终止证据校验有独立价值，不能整块回滚。

### 与默认 Codex 路线分离

- `src/agentcfg/pi_delegate_mcp.py`、`scripts/pi-delegate-mcp.py`、`src/agentcfg/pi_delegate_commands.py`：当前为未接通的桥接原型；后续应移出默认 Codex 必需闭包或明确隔离，不能仅改文档后继续成为隐性依赖。
- `CodexEvents(mcp_tools=...)` 的 MCP 专用模式：不得用于原生 CLI 路线，否则会错误拒绝原生 command_execution/file_change；默认原生解析仍需针对固定版本审查。
- `pi_delegate_files.py` 的 Pi readonly 文件操作与受控工具共用能力仍有用途，不能为退出 MCP 直接删除整个模块。

### 已发现必须修正的实现冲突

1. `pi_delegate.py` 与 `model_delegate_cli.py` 当前对全部 delegate-write 调用 `verify_mutations`。原生 CLI 写入不会产生该桥日志，会被误判为失败；必须按可信执行边界选择验证器，不能简单删除全部写入校验。
2. `codex_permissions()` 从工具级 FilePolicy 投影原生文件系统权限：只能表达部分规则，不能把部分操作权限或 tool ID 约束默认为完整原生授权。应增加显式的原生授权建模与可表达性测试。
3. `pi_vendor.py` 已把 MCP 脚本复制进固定运行包；暂停接线并不意味着它已退出默认闭包。须在后续实现中同时处理依赖、测试夹具和说明。
4. 系统/企业配置与额外资源发现仍未闭合，不能把 ignore-user-config 或禁用某几个 feature 当作完整证明。必须对实际生效配置和发现结果核验；无法验证的所选组合明确阻塞。

## 7. 后续执行顺序与验收

1. 先同步上述规范、执行边界 schema 和验收矩阵，避免代码与现行“全部逐工具授权”承诺冲突。
2. 分离 MCP 原型和原生执行证据；保留可复用的生命周期修复。
3. 补 CLI 直接执行的隔离测试：readonly 写入拒绝、显式候选内编辑与动态命令、越界/原 checkout 写拒绝、无法映射策略拒绝、策略变化停止、取消后写锁保持、逃逸/未知子工作阻塞、resume 不重复写入、错误/缺失结果不能通过。
4. 用旧组件完全缺席的环境跑两 backend、七模板和高级控制映射；检查 idle timeout、审批方式与清理等高级操作的最终处置，不能只测入口名称。
5. 再做各平台单独授权的 native 和 live 验证；真实工具发现、参数接受、OS 沙箱、终止与恢复能力均需本次证据。

最初评估仅核对源码与规划；后续用户要求继续后开始实现，结果在implementation-progress.md追加记录。真实CLI/账号/模型验证仍需独立授权，不因mock通过勾选原生验收。
