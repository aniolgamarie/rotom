## ADDED Requirements

### Requirement: LOCK-01 Manager dependencies are locked and offline entry is passive

仓库 SHALL 提交 Python 3.11+ 的 pyproject.toml 和真实 uv.lock；执行一次 `uv sync --locked` 后可使用 `./agentcfg`。入口 SHALL 直接调用已准备的仓库虚拟环境，不能通过普通 uv run 隐式同步。

#### Scenario: Missing environment reports initialization without installation
- **WHEN** 无虚拟环境执行 validate/plan
- **THEN** 入口非零退出并提示 `uv sync --locked`，不联网、不安装、不更新 lock

### Requirement: LOCK-02 Tool locks include the actual transitive resolution

`lock --agent dsh` SHALL 显式解析 DSH、TUI、插件和 OpenSpec 的实际完整包管理锁，记录精确包版本/完整 Git SHA、integrity、Node/包管理器版本、适配器版本、配方摘要与平台证据。顶层版本列表不得冒充完整锁；默认 latest、浮动 main、未锁定 npx 下载 MUST 禁止。

#### Scenario: First lock is produced by isolated resolution
- **WHEN** 首次构建在临时 HOME/XDG 下执行 lock 并准备实际依赖
- **THEN** 提交实际解析的完整锁及元数据，记录测试平台和来源，不使用手写虚构 integrity/SHA，不触碰用户 Agent 配置

### Requirement: LOCK-03 Missing or stale locks fail before implicit resolution

validate/plan/sync SHALL 检查锁是否存在、完整且适用于当前配方和 adapter；缺失或过期 MUST 给出明确 lock 命令，不静默解析。plan SHALL 脱敏报告依赖需求，不安装或联网。

#### Scenario: Changed plugin selection invalidates its dependency resolution
- **WHEN** 插件约束或影响依赖的配方变更，现有锁未更新
- **THEN** 校验解释锁过期，sync 不下载重新解析的版本，提示显式 lock

### Requirement: LOCK-04 Sync stages and consumes locks without activating failures

sync SHALL 只消费现有锁，在暂存目录安装、核对实际依赖与适配结果后注册可用运行包；不得改锁、登录、启动或隐式 apply。已部署配置 SHALL 通过 lock identity 选择兼容运行包，失败不得替换已可用运行包。

#### Scenario: Failed installation leaves a working deployment intact
- **WHEN** 当前运行包可用，另一锁的安装、integrity 校验或无账号检查失败
- **THEN** 原有包与部署绑定保持不变，锁字节不变，失败目录不作为可用包注册，sync 非零退出

#### Scenario: Frozen installation matches the committed dependency tree
- **WHEN** 在新临时环境 sync 现有完整锁
- **THEN** 包管理器使用锁消费模式，实际树匹配锁和 profile 写入记录，锁文件前后字节一致

### Requirement: LOCK-05 Native installer limits and platforms are explicit

系统 SHALL 核实原生安装器对 profile 的写入范围和二次解析行为，声明包管理器所有权并比对结果。无法冻结的步骤 MUST 标具体限制且不得宣称严格复刻。Linux/macOS 证据 SHALL 分别记录，依赖/数据库迁移不纳入配置恢复保证。

#### Scenario: Unfrozen native resolution is not reported as reproducible
- **WHEN** 上游安装过程存在无法锁定的二次解析或某平台未能测试
- **THEN** doctor/验收记录明确标注该环节或平台未验证，不把另一平台成功或顶层 pin 当成完整复刻证明
