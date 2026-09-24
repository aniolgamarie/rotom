# Permission Policy v1

**Version**: 1  
**Resolves**: U3；定义closed策略字段、匹配与父规则转换，不允许实现者自行选择其他规则语言。

## 0. 执行模式与授权范围

execution_mode由可信launcher/监督者确定，绑定policy/grant摘要，模型工具不能自行覆盖：

| 模式 | project根 | 当前授权 | 源checkout写入 |
|---|---|---|---|
| ordinary | 用户显式选择的实际业务worktree | 所选profile/实例能力上限内的OperationGrant | 可在policy允许且取得写租约后编辑，不要求创建候选 |
| managed | Task Keeper当前candidate worktree | 当前task grant与角色上限 | source_checkout只读，禁止写入 |
| delegate-readonly | 本次明确授权的业务根 | 只读OperationGrant | 禁止任何项目写入 |
| delegate-write | 本次获授权的独立linked worktree | 显式写OperationGrant | 与目标分离的source_checkout只读 |

ordinary没有Task Keeper任务时使用operation_id，不伪造task_id或要求不存在的task grant。
OperationGrant由选定配置与用户当前授权生成，不是模型传来的自授权字段。
其closed字段为schema_version=1、grant_id、operation_id、instance_id、issuer_activation_id、
execution_mode、allowed_tools、root_bindings、grant_generation（正整数）、issued_at、expires_at、grant_digest。
issued_at使用UTC RFC3339；expires_at为同格式或null。ordinary的null仅表示当前operation和issuer存活期间有效，
操作结束、撤销或issuer失效即结束；delegate授权必须有不超过max_run_seconds的有限deadline。
managed使用task grant而非OperationGrant，不能通过切换grant_kind扩展权限。
普通父会话实施、人工editor与checkpoint使用ordinary权限，在同一workspace租约下遵守policy/硬拒绝。
这些操作不会因managed的候选规则被整体禁用；managed仍不能退回ordinary绕过约束。

### 0.1 执行边界

execution_mode描述只读/写入用途；execution_boundary描述执行机制，不能混为一项权限。
Pi受控工具与Task Keeper使用agentcfg-tools，以下工具匹配和逐动作规则适用；普通Codex使用native-sandbox。
Codex通过锁定官方CLI执行原生工具，不把其内部命令伪装成tool:ID。

原生执行必须显式配置model_delegate.codex.native_execution：allow_shell为布尔值，tool_network首版固定none。
该配置与FilePolicy快照共同构成execution_policy，摘要进入请求/收据；父侧适用deny保留。
Codex的configuration_admission固定为official-cli-restricted-v1并参与同一摘要；启动前拒绝无法核验的系统／受管配置或账号，保持用户已确认的受限官方CLI支持范围，不声明原子配置保证。
FilePolicy的文件范围是原生权限投影的上限，而其工具别名不是原生命令授权。精确command_ref仍约束agentcfg受控命令；
原生allow_shell是独立、明确的运行授权，不能由command_ref allow自动产生。
command deny或文件操作限制无法无扩权表达时拒绝该原生执行，不丢弃规则。

## 1. 声明格式

`agents/pi/agent.toml` 的 `policies.<policy_id>` 只有以下字段：

| 字段 | 类型/约束 |
|---|---|
| schema_version | 整数，固定1 |
| default | 字符串，固定deny |
| rules | Rule数组，可为空；rule.id在policy内唯一 |

Rule为以下closed判别联合；所有ID符合 `^[a-z][a-z0-9_-]{0,63}$`，禁止未知字段。

| 字段 | file规则 | command规则 |
|---|---|---|
| id | 必填ID | 必填ID |
| kind | 固定file | 固定command |
| effect | allow或deny | allow或deny |
| tool_ids | 非空、无重复、在固定工具目录中存在的精确ID数组 | 同左 |
| operations | 非空、无重复，read/list/search/write/create/delete/rename | 非空、无重复，仅execute |
| root_ref | 必填逻辑根ID | 禁止出现 |
| relative_path | 必填，`.`或规范化相对路径；无绝对路径、空组件、`..`和NUL | 禁止出现 |
| match | exact或subtree | 禁止出现 |
| command_ref | 禁止出现 | 必填CheckBinding或ExternalTool的完整类型化引用，如check:unit或tool:editor |

不支持正则、glob、工具前缀、自由shell字符串、内嵌脚本或模型提供的新规则。
command_ref解析到已冻结的executable、argv、根与网络策略摘要，调用时必须一致；
允许某个工具不等于允许它运行任意argv。provider网络路径另由已声明route控制，不从file规则推导授权。

## 2. 匹配与优先级

1. 工具ID先通过固定别名表转成规范ID，例如read→tk_read；未知/动态新增工具没有规则时拒绝。
2. 文件工具的所有访问路径必须按实际文件系统解析并复查目录句柄；拒绝链接逃逸、越界和身份变化。
3. exact只匹配指定对象；subtree匹配该目录及其后代，按路径组件/真实身份判断，不能让src匹配src2。
4. 工具ID、operation、根和路径/command_ref必须全部匹配，该规则才适用。
5. 任意适用deny优先；没有适用allow为deny。规则顺序不改变结果。
6. 最终权限=所选用户policy的allow范围 ∩ 当前模式的角色或实例能力上限 ∩ 对应的OperationGrant/task grant，
   再扣除父侧适用deny和内置硬拒绝。空/过期/不匹配授权拒绝，ordinary不依赖Task Keeper记录。
   readonly_roots等价于该根下全部修改操作deny，denied_roots拒绝该根全部操作。
7. 对模型文件工具，.git、秘密目录及未取得WorkspaceWriteLease的修改是所有模式的内置硬拒绝。
   source_checkout只读仅约束managed/delegate-write；delegate-readonly禁止全部项目写入。
   ordinary的业务worktree由policy与OperationGrant决定可写范围，不套用候选专属禁写规则。
   supervisor在其专属Git管理元数据目录写运行记录是管理器操作，不暴露成模型工具权限。
8. rename必须同时满足源/目标修改权限与涉及工作区的写租约；目录递归操作逐目标检查。
9. session-yolo仅可跳过已经允许操作的交互确认，不能增加allow、消除deny或更改角色/task上限。

## 3. 逻辑根与候选重绑定

根声明只引用MachineRoot ID；策略文件不嵌入用户绝对路径。
`project`按第0节模式绑定：ordinary为用户业务worktree，managed为candidate，
两种delegate模式为各自授权根。只有managed/delegate-write提供与可写目标分离的source_checkout只读根。
有候选的执行中，父会话对原项目内路径的拒绝先转换为project根相对路径，再绑定候选；
因此父侧拒绝project/.env，在候选/.env上也必须生效，不能因新临时路径失效。
对其他根的拒绝保持其原身份，角色/task无该根allow时仍拒绝。

## 4. 父规则转换表

| 父规则输入 | 转换结果 |
|---|---|
| 本格式的精确工具+file根相对路径 | 保留effect/operation；对project根按上述规则重绑定 |
| 已声明工具别名与明确绝对单文件路径 | 按别名表归一，只有能唯一映射已声明根时转exact |
| 已声明工具别名与明确目录递归范围 | 唯一根映射后转subtree，不用字符串前缀 |
| 明确executable+精确argv的拒绝 | 只有唯一匹配已冻结command_ref时转换，保留deny |
| 自由shell片段、regex/glob、条件脚本、未知工具或不能唯一映射的路径/命令 | PERMISSION_UNREPRESENTABLE，受影响子执行预检失败；不能跳过或降级成提示词 |

只转换真实读取到的父策略快照，包含原格式/来源身份/转换器版本与摘要；
父deny不能被子配置或session-yolo覆盖。迁移提案列出不能转换的规则，用户需显式改成可表达的等价配置。
malformed/未知字段在配置校验返回2；运行时父策略不能转换返回能力错误5，均无工具执行。

## 5. 冻结与变更

编译输出包含policy_digest、root_binding_digest、parent_policy_digest、alias_table_digest、
role_or_instance_ceiling_digest、execution_mode、grant_kind=operation/task与grant_generation，
全部绑定admission_token与ExecutionLease。
agentcfg-tools在启动前和每次实际工具动作前复核；策略收紧/来源变化即拒绝旧token。
native-sandbox启动前核对冻结授权与原生权限投影，之后以supervisor停止整个执行实现撤权；检测到授权失配即请求停止。
不能声称原生下一条工具调用会立即被拦截；物理终止前维持工作区保护，不发新writer，不自动resume。
两类执行都不能在活动期间静默放宽；新授权必须产生新描述符与准入，部署仍受活动实例保护。

## 6. 契约用例

所有样例假定其他权限层和写租约已经满足，除非该行另有说明。

| 输入/动作 | 预期 |
|---|---|
| allow tk_read/project/src/subtree，读src/a.py | allow |
| 同规则读src2/a.py | deny |
| allow项目读取，同时deny project/.env/exact | 读.env为deny，规则顺序无关 |
| 父拒绝源项目.env，子任务使用新候选路径 | 候选.env仍deny |
| 写入路径通过symlink指向根外 | deny |
| allow tk_write，但角色是reviewer | deny |
| allow写入且/yolo开启，但父deny匹配 | deny |
| allow写入，但另profile持有该worktree写租约 | WORKSPACE_BUSY，零写入 |
| rename源允许、目标被拒绝 | deny，源目标都不修改 |
| allow check:unit，调用argv或executable已变 | ADMISSION_STALE，零启动 |
| 父规则是未支持的glob或shell表达式 | PERMISSION_UNREPRESENTABLE，零子执行 |
| 空rules或无匹配规则 | deny |
| ordinary在授权业务worktree中编辑，policy允许且独占写租约 | allow，无需Task Keeper任务或候选 |
| managed请求写source_checkout，其他条件满足 | deny |
| delegate-readonly请求写入或模型试图改execution_mode | deny |

T007/T038/T049/T084负责实现与验证；本契约同时适用于ordinary受控操作及managed工具的上限，
不宣称能拦截用户在管理器之外直接启动的任意同UID程序。

### 原生执行补充用例

| 场景 | 预期 |
|---|---|
| Codex未声明native_execution | 准入失败，无CLI启动 |
| allow_shell=false | 原生shell功能关闭，不转用MCP或其他命令通道 |
| 仅允许write/create，原生投影需要delete/rename | PERMISSION_UNREPRESENTABLE，不扩大操作权限 |
| Codex候选内原生编辑，没有MCP变更日志 | 按冻结原生授权、候选结果及终止证明验证；缺日志本身不作为失败 |
| 授权失配或cancel，CLI尚未终止 | 拒绝新派发并停止旧执行；写租约继续保护 |
| native-sandbox调用agentcfg受控文件/原型命令RPC | 拒绝，不能跨边界借工具 |

当前原生投影已覆盖声明的机器目录根：execution_policy.root_limits冻结根路径、目录身份、project的worktree/git-dir/common-dir身份及readonly_roots/denied_roots。
启动时复核身份；同一Git common-dir的限制同时绑定原路径和候选对应路径，目录对象别名按文件系统身份处理。
readonly仅收紧已授权路径，不给未授权目录新增read；deny优先，具体子路径allow不能重开只读或拒绝范围。
已声明的非project根file deny也按同一映射生效；未声明根、缺失候选限制路径、符号链接歧义、不能等价表达的exact目录规则仍拒绝。
原生沙箱实际执行这些投影的各平台行为仍须native证据，mock只证明转换与监督接线。
