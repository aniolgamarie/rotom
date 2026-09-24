# Model Delegate 统一委托与旧组件退出契约

**Contract version**: 2（未发布协议增加执行边界绑定；早期缺少新字段的记录不能自动认证或恢复）  
**User decision**: 2026-09-16，完善model-delegate并完整替换codex-delegate，七角色收敛为用途模板。

## 1. 最终交付与所有者

唯一技能来源为 `shared/skills/model-delegate`，唯一Pi工具桥为 `agents/pi/packages/model-delegate`。
完整迁入run-model.sh、backend/lib、schema、所需资源和测试，吸收旧实现的必要语义及来源说明。
禁止通过内部调用run-codex.sh、隐藏工具别名或动态搜索旧技能实现“替换”。

- `pi-default`：选择model-delegate和Pi backend。
- `pi-codex`：同一入口另选Codex backend，锁定CLI与独立实例账号。
- `pi-managed`：Task Keeper继续调用可逐请求门控的managed executor；未认证的外部model-delegate
  请求必须在启动前拒绝，不能借另一Pi/Codex进程绕过任务预算。不存在自动外部fallback。
- 七个codex-*独立角色及旧codex_delegate工具退出注册；用途映射见 [能力矩阵](capability-matrix.md)。
- 不新增AgentManager。Pi工具调用通过既有manager的external executor申请一次运行，
  standalone用户单run通过实例supervisor准入；批量分解/并发由上层承担。

## 2. 模型工具与用户命令

模型工具 `model_delegate` 接收closed schema：

| 字段 | 约束 |
|---|---|
| backend | pi / codex；必须显式或由已锁定配方唯一确定，不能根据失败改后端 |
| mode | review / investigate；模型工具始终只读 |
| preset | general/context/challenge/plan/research/review/scout |
| task | 非空有界目标，不授权额外工具、网络或写入 |
| cwd | 显式允许的业务根内路径，真实路径与项目身份校验 |
| model_role | 可选，引用已声明模型绑定；与model二选一 |
| model | 可选精确ID，属于所选backend允许集合；不模糊匹配 |
| timeout_seconds | 正整数且不超过配方max_run_seconds |
| context_artifact | 可选、经过schema校验的任务/范围/工作区/事实引用，无秘密 |

`/model-login codex` 是用户显式登录命令，经supervisor使用该切片的Codex CLI和实例CODEX_HOME；
不注册旧/codex-login别名。Pi账号使用当前实例原生登录机制，model-delegate不拷贝旧home认证。
登录不是doctor/live的模型执行证明，也不由模型工具自动触发。

统一技能CLI目标为：

```text
run-model.sh start --backend BACKEND --mode MODE --cwd DIR --prompt-file FILE [options]
run-model.sh resume --run-id RUN_ID --prompt-file FILE [options]
run-model.sh status --run-id RUN_ID
run-model.sh cancel --run-id RUN_ID
run-model.sh poll --run-id RUN_ID --after CURSOR --wait-seconds N
run-model.sh wait --run-id RUN_ID --wait-seconds N
```

保留probe与前台--observe；补齐--detach、启动ready握手与start_unknown。
MODE为review/investigate/implement；implement仅对已声明支持写入的backend开放。
所有命令使用canonical部署runner和显式实例state，禁止扫描HOME找旧入口。

Pi桥到现有AgentManager增加external executor契约：
`submit_delegate(request_id, idempotency_key, instance_id, policy_digest, request_digest, backend_request)`，
返回固定run_id/lease_id；相同键同请求返回原run，异请求拒绝。
`get_delegate_result(run_id)`与`cancel_delegate(run_id)`复用owner校验及结果/取消语义。
`submit_batch(batch_id, items[])`是上层明确给定的任务集合，manager负责容量，
客户端只能收集与取消，不能自行改变依赖关系或新建额外执行。
桥先拒绝未经认证的managed上下文、后端未选择、写模式越权和资源冲突，之后才准入启动。
standalone单run必须认证同实例supervisor并遵守活动容量/工作区规则，不自建队列。

## 2.1 执行边界与原生工具

Pi为execution_boundary=agentcfg-tools；Codex为native-sandbox，使用官方CLI及原生文件/命令工具。
请求与收据必须带execution_boundary、execution_policy_digest，二者由supervisor按选中backend生成。
execution_policy冻结FilePolicy以及Codex显式native_execution（allow_shell、tool_network=none），原生权限投影不可无授权扩大。
Codex还固定configuration_admission="official-cli-restricted-v1"并纳入摘要。按2026-09-18用户决定，官方CLI启动前检查系统配置目录／macOS受管偏好及所选实例账号类别；无法核验、组织或未知账号拒绝，保留兼容性缺口。稳定受信机器与账号是运行前提，不把独立预检称为原子保证。新start/resume均复查；默认doctor/probe不读取认证文件。
模型不能选择/覆盖执行边界，不加入额外MCP IO执行器或第二个manager。

原生启动授权由supervisor持久保存并绑定run/request/runtime/lease/generation/cwd。只有模型退出零或候选有变化都不够；
结果还需本次授权、完整原生事件、非空产物和物理终止证明。Pi仍由受控工具实施只读与逐动作检查。
缺少边界字段的早期V2记录不得补默认值升级为可信新运行；保留原记录，明确拒绝恢复与认证。

## 3. 显式写入

第一版Codex backend实现write，Pi backend继续supports_write=false，不能伪造通用写入支持。
用户明确的implement任务必须同时具备：

- 配方选择explicit-write、`--allow-workspace-write`与`--worktree-root`。
- 已存在且身份验证通过的独立Git worktree，cwd位于该根内，源checkout不可写。
- 获得跨实例WorkspaceWriteLease，排除所有profile的同worktree活动或unknown writer，
  包括Task Keeper候选、ordinary编辑和可写检查。以文件系统/worktree身份仲裁，不按实例目录各自判断。
- 明确模型、范围、验收标准与允许的资源。源码/策略/候选变化导致准入失效。

写任务不得自动重试；resume必须用户显式请求且旧执行已终止。
只读工具不能通过task/preset/context转成写入。detach仅在supervisor持续持有lease且ready握手成功后返回，
否则报告start_unknown，不能启动第二个writer或释放保护。

## 4. 单run、重试与批次

一次run只对应一个backend、模型和任务。上层manager负责并发槽，supervisor负责物理执行。
保留只读有界重试，但责任只在一个层级：standalone允许经配置重试；上层已控制重试时runner设为零。
每次尝试有独立attempt_id和证据，不清除失败记录后复用成功凭证。

现有run-model-fanout.sh改为显式批次提交/状态/取消与结果收集客户端，复用上层manager队列，
不自行fork sibling runs。没有可用批次管理接口时明确拒绝批量命令，单run仍可用。
结果聚合只基于该批次终态与逐run凭证，保留失败/缺失，不把部分结果包装成全通过。

## 5. 观察、控制与监督

- start先写allocating意图及完整workspace计划，再预留写租约，持久提交starting边界后才能spawn；
  预留期间崩溃按abort_allocation恢复。ready确认身份、request_digest和可控制进程后才能报告running。
- 超时未确认就绪为start_unknown；旧supervisor记录继续保护，禁止以父命令返回认定停止。
- 增量事件使用单调seq与cursor，poll返回next_cursor/has_more；cursor跨run或超界拒绝。
- wait仅等待当前run终态，等待超时不取消执行；cancel回执只表示接受。Codex按整次运行停止，停止完成前可能继续发生原授权范围内操作，不能声称逐工具即时撤权。
- checkpoint来自实际语义事件；心跳不伪造进度，不推进语义cursor；普通模型原文与私密推理不作公开进度。
- 默认观察/控制摘要上限4096字节，长信息保存私人artifact并返回引用，路径也不得使信封失控。
- Linux/macOS统一调用实例supervisor，替换两旧runner中setsid、/proc、固定代理和任意全局路径依赖。
- resume核对backend、模型、工作区、owner、协议与旧运行终止；显式resume token，不支持隐式last。
- supervisor崩溃后的显式停止使用 [恢复契约](recovery-and-workspaces.md) 的受限授权，
  不复活旧nonce、不擅自继续执行，工作区写租约直到完整终止证明才释放。
- 旧codex-delegate历史记录只留在原环境作参考；不会自动转成新可恢复运行。新协议v1历史只读查看，
  跨协议resume需明确兼容校验，不可证明兼容则拒绝，并允许用户建立独立新任务。

## 6. Context 与反馈

统一context含artifact_id、task/scope/constraints、workspace快照、带来源的facts/decisions/hypotheses、
references、turn与budget；允许转换现有memory entries，不能据内容扩权。
裁剪顺序优先保留权威约束、任务、决策和证据，记录截断；不把固定1M context_limit当作所有模型能力。

反馈必须关联artifact_id/run_id/turn/candidate_digest。schema有效不代表事实成立；
引用证据经调用方检查后分别标verified/provisional/disputed/stale/unverified。
旧工作区、旧turn或无法核对的反馈不能进入已验证事实集合。没有结构化反馈可返回普通结果并标缺失，
需要结构化反馈的调用不得因此通过。迁移后保持多轮关联与已知冲突，不静默抹去。

## 7. Request 与 Receipt v2

请求保存run_id、attempt_id、backend、requested_model、request_digest、cwd/worktree_identity、
mode、execution_mode=delegate-readonly/delegate-write、execution_boundary、execution_policy_digest、policy_digest、runtime_identity、parent_task_id（如适用）、lease_id、context_artifact_id、
workspace_write_lease_ids、workspace_identity_digest、grant_generation。只读run的写租约数组为空。
新请求不接受任意run目录或旧receipt作为结果输入。

receipt包含以上关联字段及terminal_status、backend_resume_token、event_sequence_complete、
final_artifact_id/digest、process_terminated、resources_reclaimed、usage、feedback_dispositions、
requested_model与observed_model（可空）。Pi桥负责核实本次凭证，而不是盲信脚本输出。

只有本次身份一致、合法终态、宿主成功结果、非空final、完整事件和资源终止证据同时满足，
才返回verified-execution；它不等于review-pass或implement验收通过。
旧run、错cwd/model、空结果、超时partial、假stopped、序列缺口或反馈错配都不能通过。
原生写结果不要求受控MCP的mutation journal；冻结授权和当前候选证明与物理终止缺一不可。
各backend共享契约测试，原生差异在adapter内明确，不允许读取旧codex-delegate收据充当新凭证。

## 8. 依赖与秘密

backend可执行路径来自所选锁切片；Pi backend使用实例隔离的已安装Pi和受限资源清单，
不能隐式调用全局pi auth或继承其扩展、凭据与模型配置。
Codex backend只用选中的实例CODEX_HOME；网络route显式，不使用固定10808或环境任意fallback。
凭据最小注入，公共摘要无原始秘密、auth头、私密模型响应、推理或原始错误。
Bash/jq/Git及平台supervisor公开列为前提或锁资源；不会在start中安装依赖。

## 9. 退出旧组件验收

发布来源与锁无codex-delegate可执行包、run-codex.sh、codex-agents旧桥或旧工具别名；
技能发现无codex-delegate、agent roster无七个旧codex-*角色。历史名称允许只出现在来源说明、
迁移映射及负向测试数据中。旧机器原目录不因迁移而删除。

在旧组件完全缺席的干净环境执行七模板与全部登记调用方，验证两backend只读、Codex显式写入、
进度/控制/恢复、批次与上下文反馈。未知写支持、无授权、重复派发和伪凭证用例必须失败。
默认只运行fake backend；真实Pi/Codex/账号验证仍分native/live独立授权。
