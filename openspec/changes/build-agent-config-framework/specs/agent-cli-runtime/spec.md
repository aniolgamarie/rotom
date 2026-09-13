## ADDED Requirements

### Requirement: CLI-01 Public selectors and command contracts are consistent

系统 SHALL 实现 `./agentcfg [--machine NAME | --local PATH] [--profile ID] COMMAND`，machine/local 互斥；无选择器使用 default 机器文件，无显式 profile 使用本地 default_profile 再回落 dsh-default。命令 SHALL 提供帮助、所选 profile/实例位置与脱敏结果；不支持的工具明确失败。

#### Scenario: Selectors behave the same across offline and mutating commands
- **WHEN** 对 validate/plan/sync/apply/doctor 使用相同公共参数，或同时指定 machine 与 local
- **THEN** 合法调用解析同一配置/实例，冲突参数在写入前失败；缺省机器文件不存在时提示初始化，不选择其他现有文件

### Requirement: CLI-02 Init-local creates a private non-overwriting file

`init-local --machine NAME` SHALL 创建仓库外 0600 空密钥本地 TOML及必要 0700 私人目录，不覆盖已有文件、不读取现存密钥。全局重复或冲突选择器 MUST 失败，不修改其他配置目录权限。

#### Scenario: Repeated initialization preserves user content
- **WHEN** 首次初始化后用户编辑文件，再执行同名 init-local
- **THEN** 首次产物符合 schema，第二次明确报告已存在且字节/权限不被意外改变，不从 HOME 搜集凭据

### Requirement: CLI-03 Offline commands have bounded writes

validate SHALL 离线检查 schema/引用/映射/锁且不写目标；render SHALL 离线确定性生成且仅写私人缓存；plan SHALL 离线展示脱敏差异、来源、漂移、冲突和依赖需求且不写目标；apply SHALL 离线重新检查并部署，不安装或登录。

#### Scenario: Default commands cannot fetch dependencies behind the scenes
- **WHEN** 默认测试阻断网络并监控目标目录，分别执行 validate/render/plan/apply
- **THEN** 无网络请求或隐式依赖命令；validate/plan 不修改目标，render 仅写缓存，apply 仅在其受管边界写入

### Requirement: CLI-04 Run uses the deployed launch contract and caller cwd

`run dsh [--cwd PATH] [-- args]` SHALL 使用当前部署的配置、所要求的锁身份与启动契约，不隐式 sync/apply。cwd SHALL 为显式 PATH 或调用时工作目录，不得为了定位 rotom 而改到管理仓库；参数以 argv 数组透传。

#### Scenario: Native process retains worktree and literal arguments
- **WHEN** 从含中文空格的业务路径启动，并传递含引号或 shell 特殊字符的原生参数
- **THEN** 假进程收到正确 cwd 和原样 argv，不收到分隔符 `--`，无 shell eval

#### Scenario: Unapplied provider changes do not change injected credentials
- **WHEN** 当前部署引用 provider A 的 key_a，本地未 apply 改选 B/key_b，或仅更新 key_a 的秘密值
- **THEN** run 仍按部署契约只解析 A 所需引用，并使用 key_a 当前值；B 不启用，密钥轮换无需 apply

#### Scenario: Missing deployed runtime gives a repair instruction
- **WHEN** 配置已 apply 但所需锁的运行包尚未 sync，或对应包不兼容
- **THEN** run 明确失败并提示准备对应依赖，不任取其他版本、不隐式安装

### Requirement: CLI-05 Child environments contain only allowed and required values

子进程环境 SHALL 从文档化基础允许清单、显式机器非秘密环境和此次声明所需 secret 构造，不复制全部父环境或 secrets。secret SHALL 仅在需要的操作启动时解析，不进入 argv；安装及 OpenSpec 子进程不得接收无关模型密钥。环境引用不支持时 MUST 失败，不落明文。

#### Scenario: Fake process receives only selected synthetic credentials
- **WHEN** 本地含选定/未选定 canary 密钥，父环境含未允许秘密，run 启动假进程
- **THEN** 假进程仅收到声明需要的凭据和允许变量，未使用密钥/未允许父秘密不传递，argv/日志/异常均无 canary

#### Scenario: Missing required credential has a distinct failure
- **WHEN** 运行所需 secret 为空且 adapter 未声明支持延迟认证
- **THEN** 启动前以凭据缺失状态失败，只报告引用名；同一配置的离线校验仍可成功

### Requirement: CLI-06 Doctor separates offline status from live checks

doctor SHALL 默认离线报告实例/依赖/漂移/恢复记录/备份/权限/认证入口及原生外部偏好影响，不读取用户现存 OAuth 文件。`--live` SHALL 才允许服务检查；真实 Codex/Cursor 调用还要求用户明确授权并提供可用登录态，不得从无账号 smoke 推断成功。

#### Scenario: Offline doctor reports a machine awaiting login
- **WHEN** 新实例配置与依赖已准备但未登录
- **THEN** doctor 不联网，分别显示配置/依赖/登录待完成状态和认证入口，不把未登录当 schema 错误

### Requirement: CLI-07 Capture produces a scoped private proposal

capture SHALL 只捕获 allowlist 原生字段，输出脱敏报告及 0600 本地覆盖提案，不修改 Git、机器文件或运行配置，不全量导出 settings/auth。提案中的非秘密私有值 SHALL 可形成合法框架 overrides；凭据、动态模型目录和 session 不得捕获。

#### Scenario: UI preference becomes a valid local override proposal
- **WHEN** 原生 UI 改变受支持主题/模型选择，同时文件有 OAuth 字段与私有 endpoint
- **THEN** capture 仅转换允许字段，终端不打印私有值，提案通过本地 schema，凭据与运行数据完全排除，原文件不变

### Requirement: CLI-08 Exit codes distinguish failure classes

管理器 SHALL 使用 0 成功、2 参数/配置/锁错误、3 必需凭据缺失、4 冲突/活动锁/恢复待处理、5 依赖或原生检查失败、6 文件系统或内部操作失败。run 成功启动后 SHALL 保留子进程退出结果并文档化信号映射，错误不得包含秘密。

#### Scenario: Failures are actionable and not reported as success
- **WHEN** 分别触发未知字段、缺密钥、冲突、安装失败、IO 失败及假宿主非零退出
- **THEN** 命令返回对应类别或子进程结果，输出说明下一步，不伪报成功、不泄露输入值
