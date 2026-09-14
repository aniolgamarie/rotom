# managed-deployment Specification

## Purpose
TBD - created by archiving change build-agent-config-framework. Update Purpose after archive.

## Requirements

### Requirement: DEP-01 Instances and sensitive directories are isolated

系统 SHALL 按工具和 profile 建立独立实例、状态、备份与锁，默认遵循 XDG；DSH 的 dsh-home SHALL 跨配置与运行包更新保持固定。目录 SHALL 为 0700，敏感文件为 0600，技能执行位按需保留。默认不得接管既有 Agent home。

#### Scenario: Profiles and tools do not share backups or login homes
- **WHEN** 在临时 HOME 部署两个 DSH profile 并通过契约 fixture 部署另一工具
- **THEN** 各实例、备份和锁独立，更新一个不更改其他实例，dsh-home 路径不随 generation 改变，既有模拟用户目录不变

#### Scenario: Two local configurations cannot silently claim the same instance
- **WHEN** 已绑定一个机器/本地路径的实例被另一份本地文件作为相同目标申请部署
- **THEN** 系统拒绝并提示使用独立 profile 或显式独立实例路径，不共享登录、不自动迁移运行数据

### Requirement: DEP-02 Ownership and first adoption are explicit

适配器 SHALL 声明整文件、字段、首次初始化、运行时和包管理器五类所有权。首次遇到未接管的非空同名受管文件 MUST 冲突；原生安装器创建的共享文件仅能通过已记录的明确字段边界处理。运行时及包管理器拥有数据不得由渲染器强制覆盖。

#### Scenario: First apply succeeds only on owned or empty targets
- **WHEN** 分别对空新实例和含未接管非空目标的实例 apply
- **THEN** 新实例部署成功；未接管目标报冲突且不自动 force，运行时/包管理器文件不被猜测接管

#### Scenario: Initialization-only values stop being enforced
- **WHEN** 首次初始化值随后由 TUI 修改，再次 apply 相同配方
- **THEN** 用户值被保留，系统不将初始化默认值作为持续受管字段覆盖

### Requirement: DEP-03 Three-way merge preserves drift without adopting it

字段和整文件 SHALL 比较 B 基线、C 当前、D 期望：C=D 无需写且基线可记 D；C=B 应用 D；D=B 保留 C并报告漂移且保留 B；双方改变且不同则冲突。缺失 SHALL 是独立值，未知与不受管字段始终保留。

#### Scenario: All merge branches have explicit outcomes
- **WHEN** 测试分别构造 C=B、D=B、C=D 和双方不同的状态，包括字段删除
- **THEN** 每一分支符合规定；保留漂移后再 apply 不会因为新 generation 而将 C 自动接纳为 B

#### Scenario: OAuth additions and UI changes survive deployment
- **WHEN** settings 中出现新增动态 OAuth provider、未知字段及用户 UI 变化，而期望只更新独立受管字段
- **THEN** 只更新允许字段，动态 provider、未知字段和未冲突 UI 变化保留，普通快照不包含运行时认证内容

### Requirement: DEP-04 Previous backup rotates only after successful change

每个实例 SHALL 仅保留一份上一版受管配置备份。备份 SHALL 在修改前准备，在有效变更成功提交后替换旧备份；无变化或失败恢复成功 MUST 保留既有备份。备份准备失败不得写目标；备份不得包含整份混合 settings、OAuth、会话或本地秘密文件。

#### Scenario: Successful updates retain only the immediate predecessor
- **WHEN** A 已部署，依次成功应用 B、C
- **THEN** 当前为 C，仅保留 B 的必要受管前状态作为 previous，A 内容不作为隐藏历史副本继续保留

#### Scenario: No-op and failed apply do not destroy a useful backup
- **WHEN** 当前 B、备份 A，重复 apply B 或在应用 C 时发生可恢复故障
- **THEN** 当前仍为 B、备份仍为 A；无变化不重写目标，不因重复命令轮换备份

### Requirement: DEP-05 Journals recover interrupted multi-file operations

系统 SHALL 为多文件操作写入私有 pending journal，只记录恢复所需受管前值、目标摘要及状态，不存秘密/运行时快照；单文件 SHALL 原子替换。进程中断后 SHALL 按明确阶段恢复或报告冲突，恢复未解决前阻止进一步修改。

#### Scenario: Interruption during file or manifest commit is recoverable
- **WHEN** 在第一个文件替换后、后续文件替换时或 current/previous 状态提交期间注入进程中断
- **THEN** 下次操作按 journal 恢复一致的已提交/未提交状态，保留其他字段，失败不伪报成功且不提前丢弃旧备份

#### Scenario: Recovery does not overwrite subsequent unrelated changes
- **WHEN** 故障后外部进程增加不受管字段或修改待恢复的同一受管字段
- **THEN** 前者保留，后者报告恢复冲突并保留 pending 证据，管理器不盲目整文件恢复

### Requirement: DEP-06 Rollback restores and consumes the previous managed state

`rollback` SHALL 恢复 previous 中上一次变更的受管前状态，按相同所有权、并发及写前冲突规则执行。成功后 SHALL 消费 previous，失败不消费；无备份明确报告。恢复不得回退登录、会话或数据库，不得承诺依赖降级。

#### Scenario: Rollback preserves later runtime changes
- **WHEN** B 部署后新增会话、未知字段且受管字段未冲突，执行 rollback
- **THEN** 恢复 A 的相关受管值，保留新增运行数据，消费 previous；再次 rollback 明确无可恢复备份

#### Scenario: Changed managed field prevents destructive rollback
- **WHEN** 用户在 B 部署后修改同一受管字段为 C，且 C 与恢复目标不同
- **THEN** rollback 报冲突，不覆盖 C，不消费备份

#### Scenario: First deployment can be undone without deleting the home
- **WHEN** 首次部署创建文件后执行 rollback，期间工具新增不受管运行文件
- **THEN** 只删除本次新增且仍符合管理条件的对象，保留 home 和运行文件

### Requirement: DEP-07 Mutations are mutually exclusive and recheck targets

apply/sync/rollback SHALL 使用实例互斥锁，并被 run 持有的活动锁阻止。管理器 MUST 不自动杀宿主。每次写入前 SHALL 复查目标及其路径身份；旧 plan 不构成写入授权快照。外部绕过管理器的进程检测限制 SHALL 文档化。

#### Scenario: Concurrent operations and active run are rejected
- **WHEN** 两个 apply 同时运行，或 run 启动的假宿主活动期间执行 sync/rollback
- **THEN** 仅允许符合锁规则的操作，其他明确提示稍后重试，不修改活动依赖或配置、不杀宿主

#### Scenario: A target changes after planning
- **WHEN** plan 或预检查之后、原子替换之前，目标文件或路径身份变化
- **THEN** 写前检测阻止覆盖，已写部分按 journal 安全恢复或报告冲突

### Requirement: DEP-08 Paths and cleanup remain within owned boundaries

目标路径、技能资源及备份恢复 SHALL 阻止绝对路径逃逸、`..` 和符号链接穿透。删除 SHALL 限于 manifest 记录且仍满足管理条件的对象，不得递归清空未知文件。

#### Scenario: Symlink and traversal attacks cannot reach external files
- **WHEN** 模板目标、技能资源、实例父目录或写前竞态包含逃逸路径/符号链接
- **THEN** 操作拒绝，仓库与实例范围外的哨兵文件不被读作复制来源、不被写入或删除
