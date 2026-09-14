## ADDED Requirements

### Requirement: SKILL-01 A complete maintenance skill is delivered and discoverable

首版 SHALL 交付 `shared/skills/maintain-agent-config/SKILL.md` 与实际需要的资源，记录来源/定制并按 profile 分发。技能 SHALL 指导维护 rotom 配置来源、模板、本地覆盖和生成结果，能定位管理仓库及用户所选实例，不假设当前业务 cwd 是 rotom。

#### Scenario: Installed skill references remain valid away from the source repository
- **WHEN** 技能被完整复制到隔离实例并从业务目录使用
- **THEN** 必需相对资源存在，指导能明确定位管理仓库和选择器，不因硬编码开发者 HOME 或错误 cwd 修改业务目录

### Requirement: SKILL-02 Local configuration authoring follows the actual schema

技能 SHALL 指导 Agent 按当前 schema 和字段参考编写合法本地 TOML：区分 machine、paths、environment、providers/models/MCP、profile overrides 和 secrets，说明数组替换、false、引用、路径及工具参数边界。不得猜字段、把 DSH 原生格式当框架格式或用未验证 extras 绕过校验。

#### Scenario: Adding a private model produces a valid local override
- **WHEN** 用户要求添加私有 provider/model、选择为一个 profile 主模型，并指定中文实例路径
- **THEN** 技能指导生成对应合法表和引用，使用 secret 引用与空占位而不索取/显示真实密钥，通过真实 validate 和 render/plan，其他 profile 不被替换

#### Scenario: Invalid local input is corrected narrowly
- **WHEN** 本地配置存在拼错字段、重复 ID 或错误参数类型
- **THEN** 技能指导根据脱敏校验错误定位并提出最小修改，不关闭 schema 校验，不全量重写秘密区域或添加任意原生键

### Requirement: SKILL-03 Local edits preserve unrelated private content

技能 SHALL 只修改任务涉及的本地非秘密区域，保留其他 profile、注释和 secrets；不得打印整份本地文件或将其复制到 Git/普通备份。无安全局部编辑方式时 SHALL 生成局部提案而不是破坏性全量重写。变更后 MUST 验证 TOML、schema、引用和合并结果。

#### Scenario: Editing one profile leaves canary and other settings untouched
- **WHEN** 合成测试本地文件包含 canary 密钥、注释、多个 profile，任务仅修改其中一个模型选择
- **THEN** 目标字段合法更新或形成明确局部提案，其他 profile/注释/秘密原文保留，输出/补丁上下文不暴露 canary

### Requirement: SKILL-04 Maintenance follows source and version boundaries

技能 SHALL 引导共享内容写 shared、工具内容写 adapter、机器私有内容写本地覆盖；原生 UI 变化走 allowlist capture。新字段/插件/认证需核实锁定版本；依赖改变才显式更新 lock 并检查差异，不直接修生成结果或暗中采用 latest。

#### Scenario: A template update does not become a native-home hotfix
- **WHEN** 用户要求调整 DSH 模板或加入共享规则
- **THEN** Agent 按技能修改对应来源并 validate/render/plan，原生 UI 私有变化保留，不直接覆盖 settings 或复制 OAuth 数据

### Requirement: SKILL-05 Generation and deployment follow user authorization

技能 SHALL 区分生成检查与实际部署，复用用户已授权范围，不要求无意义的重复确认，也不得扩展到其他工具、登录、发布或业务项目。备份/恢复/秘密注入 SHALL 使用管理器，不在技能中复制一套写文件逻辑。

#### Scenario: Generation-only request does not apply configuration
- **WHEN** 用户只要求生成新配置并查看差异
- **THEN** 完成校验、render 和 plan，不 apply/sync/login，不写目标实例

#### Scenario: Authorized deployment uses automatic previous backup
- **WHEN** 用户明确要求把选中配置应用到本机，且依赖和配置准备完成
- **THEN** 调用管理器 apply，在相同授权范围内完成备份和部署，不另行手工复制 home；若实例活动，说明退出后重试，不杀进程

### Requirement: SKILL-06 Skill validation checks realistic behavior and outcomes

技能 SHALL 通过结构校验及隔离场景验证：合法本地编写、无关内容保留、仅生成、授权部署、版本更新边界与未支持工具处理。引用资源必须存在，脚本若有新增必须实际运行验证，不以标题/措辞匹配代替行为证据。

#### Scenario: Maintenance acceptance runs without user secrets or live services
- **WHEN** 在临时仓库、HOME 和假管理器/真实离线校验器上验证维护场景
- **THEN** 验证实际编辑范围、合法配置、命令选择与脱敏，不读真实 OAuth、不调用模型服务，未执行的 Agent 行为测试明确标记待验证
