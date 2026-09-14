## 1. 核实上游接口与实施边界

- [x] 1.1 阅读仓库说明和已有变更，建立工程 AGENTS.md 与验收记录格式；保持用户已有 OpenSpec/技能文件，记录只允许仓库和临时 HOME 测试的边界（DSH-10）。
- [x] 1.2 调查并选择 DSH host 与 ccch1mneyyy/dsh-TUI 兼容提交，记录启动、包管理器、Node 要求、profile 与安装器写入范围（DSH-01、LOCK-05）。
- [x] 1.3 核实 settings/Cordis 完整行替换、允许 JS 标记、规则/技能加载与所有权，保存最小可追溯 fixture（DSH-02、DEP-02）。
- [x] 1.4 核实配套 dsh-auth 的 openai-codex、bundled auth/working-activity 与 oauth-subs 的 Cursor 注册、服务、数据目录、端口、认证入口（DSH-04、DSH-05）。
- [x] 1.5 核实主题/effort/preset 优先级、DSH_HOME 外偏好、credential env、MCP transport 与秘密引用；将无法支持项明确记录（DSH-06、DSH-07、DSH-09）。
- [x] 1.6 核实 OpenSpec 的锁定候选版本、包管理、原生工具列表及自定义 DSH 集成方式，区分本仓库开发 CLI 与产品锁（OS-01、OS-03）。
- [x] 1.7 在临时环境解析安装候选依赖并执行独立无账号最小兼容检查，完成 docs/upstream-verification.md；ModSearch 未验证不得进入默认选择，检查 Superpowers 缺席（LOCK-02、DSH-08、DSH-10）。

## 2. 管理器基础与隔离测试设施

- [x] 2.1 建立 Python 3.11+ 模块、pyproject.toml 和真实 uv.lock，实现直接使用 .venv 的 agentcfg 可执行入口；测试缺环境不会安装（LOCK-01）。
- [x] 2.2 实现 argparse 命令树、公共选择器、默认机器/profile 规则、帮助和退出码骨架，未实现操作不得伪报成功（CLI-01、CLI-08）。
- [x] 2.3 建立临时 HOME/DSH_HOME/XDG、网络阻断、假子进程、虚构 provider/model 和文件哨兵 fixtures；默认测试不运行第三方 host（DSH-10）。
- [x] 2.4 配置 Git 忽略真实本地文件、生成物、运行状态与认证数据，建立私人目录/文件权限及路径归属工具（DEP-01、DEP-08）。
- [x] 2.5 定义 adapter 接口、声明式产物/启动契约与测试适配器，验证不需要生产空 Pi/Codex adapter（EXT-01、EXT-02、EXT-03）。

## 3. 本地格式、公共 schema 与合并

- [x] 3.1 实现 registry、profile、agent/binding/plugin schema 和稳定 ID 引用校验，覆盖重复 ID、未知字段、无效映射、认证拥有者冲突（CFG-01）。
- [x] 3.2 实现本地 schema：machine、paths、environment、providers/models/mcp/profiles overrides、secrets；校验多个 profile 和本地新增实体（CFG-02）。
- [x] 3.3 实现绝对路径/~/规则、中文空格、editor 单程序语义、环境变量名/保留名与非秘密值校验；拒绝插值与逃逸（CFG-03）。
- [x] 3.4 实现分层递归合并、数组整体替换、空数组/false、缺失状态、选择取消/引用删除及字段来源树（CFG-04、CFG-05）。
- [x] 3.5 实现秘密存储与 secret resolver 边界、私有来源标记、脱敏校验异常；确保 secret 不进入通用配置/摘要输入（CFG-06）。
- [x] 3.6 实现 init-local 的 0700/0600 初始化与不覆盖行为；提供最小 examples/local.example.toml 和本地格式字段文档（CLI-02、CFG-09）。
- [x] 3.7 添加经真实 schema 验证的 XDG、自定义路径、SSH/macOS、私有网关、多 profile 例子，测试非法 schema 版本及未知表明确失败（CFG-02、CFG-09）。

## 4. 确定性渲染与计划

- [x] 4.1 实现原文规则顺序合并、StrictUndefined 文本模板、结构化序列化与非秘密 generation 输入（CFG-07、CFG-06）。
- [x] 4.2 实现完整技能包复制、执行位、资源引用、显式同名覆盖和源路径安全检查（CFG-08、DEP-08）。
- [x] 4.3 编写实际可用的 repo-navigation 技能和中文/终端/C++ 局部检索规则，记录来源和定制，不默认索引或放开权限（CFG-08、DSH-03）。
- [x] 4.4 实现 validate/render/plan：缓存权限、脱敏差异/来源、漂移/冲突与依赖需求，确定性渲染与当前运行文件合成分开（CLI-03、CFG-07）。
- [x] 4.5 测试重复 render 字节/集合/模式一致，普通模板花括号保留，特殊字符不求值，离线命令无目标写入或网络（CFG-07、CLI-03）。

## 5. 所有权部署、上一版备份与恢复

- [x] 5.1 实现实例路径、机器来源绑定、固定 dsh-home、current/previous/pending 状态 schema 与五类所有权（DEP-01、DEP-02）。
- [x] 5.2 实现含缺失状态的 B/C/D 合并和逐字段基线，测试所有分支、保留漂移不采纳、首次接管冲突与初始化项（DEP-02、DEP-03）。
- [x] 5.3 实现持锁预检查、写前复查、原子单文件替换和 manifest 范围内删除；加入路径/符号链接/中文空格测试（DEP-07、DEP-08）。
- [x] 5.4 实现修改前 pending 记录、提交状态指针和单份 previous 轮换；备份只包含非秘密受管前值，备份失败停止写入（DEP-04、DEP-05）。
- [x] 5.5 实现中断恢复及恢复冲突处理，注入文件写入、状态提交和清理阶段故障，验证旧备份与不受管状态保留（DEP-05）。
- [x] 5.6 实现 rollback 上一版恢复/成功消费/失败保留、首次部署安全撤销、同字段后改冲突与依赖兼容提示（DEP-06）。
- [x] 5.7 测试 A→B→C 只留 B、重复 apply 无非必要写入/不轮换、失败恢复回 B且保留 A，不留下隐藏历史内容（DEP-04）。
- [x] 5.8 测试动态 OAuth provider、未知字段、会话、UI 改动与原生明文 credential 异常状态，确保受管前值/摘要/journal 不保存秘密（DEP-03、CFG-06）。
- [x] 5.9 测试并发 apply、run 活动锁和 plan 后竞态，证明不杀宿主、不改活动配置，记录外部进程检测边界（DEP-07）。

## 6. 完整锁与安装消费

- [x] 6.1 实现 lock --agent dsh，对实际完整包管理锁写入版本/SHA/integrity/平台/适配器/配方摘要，禁止浮动下载（LOCK-02）。
- [x] 6.2 实现缺锁/过期锁/平台不适用校验和明确更新指令，不在离线命令或 sync 重新解析（LOCK-03）。
- [x] 6.3 实现 sync 暂存安装、锁消费、安装器写入归属及实际依赖树比对，验证后注册可用运行包（LOCK-04、LOCK-05）。
- [x] 6.4 在隔离环境用已提交锁执行真实安装验证，保存锁字节一致、失败不激活和当前包保留的测试证据（LOCK-04）。
- [x] 6.5 记录原生二次解析或平台限制，确保无法冻结时不宣称完全复刻，sync 不登录、不启动宿主、不轮换配置备份（LOCK-05、DEP-04）。

## 7. 启动、环境、诊断与捕获

- [x] 7.1 实现部署启动契约与 lock identity 绑定，允许 apply 早于依赖安装，run 对缺包给出明确提示（CLI-04）。
- [x] 7.2 实现 argv/cwd 透传、原生退出码和活动锁生命周期，测试中文空格工作目录、参数边界及未隐式 apply/sync（CLI-04、CLI-08）。
- [x] 7.3 实现并文档化子进程环境允许清单、显式机器环境和按部署引用注入 secret；安装/项目子进程不接收模型密钥（CLI-05）。
- [x] 7.4 测试仅轮换 key 下次启动生效、未 apply 的 provider 更改不生效、未用/父进程秘密不继承及必需凭据缺失退出码（CLI-04、CLI-05）。
- [x] 7.5 实现离线 doctor 的依赖/实例/漂移/备份/恢复/权限/待登录状态与外部偏好说明，以及显式 live 检查入口（CLI-06）。
- [x] 7.6 实现 allowlist capture 的有效本地覆盖提案和脱敏报告，通过本地 schema 校验且不修改 Git/机器文件/认证数据（CLI-07）。
- [x] 7.7 覆盖各失败类别的可操作错误和退出码，检查错误正文/子进程失败处理不回显 canary 或私有 endpoint（CLI-08、CFG-06）。

## 8. 实际 DSH 配方与认证接入

- [x] 8.1 按调查证据实现 agent.toml、bindings.toml、plugins.toml、模板及真实 profile，冻结 adapter 版本和所有权映射（DSH-01、EXT-02）。
- [x] 8.2 实现完整 Cordis 行合成、安全 YAML 标签及静态 API 环境引用，通过锁定版本配置加载检查（DSH-02、DSH-06）。
- [x] 8.3 接入配套 Codex 订阅认证，验证唯一拥有者及 bundled 插件不重复，提供同一隔离实例的原生登录步骤（DSH-04）。
- [x] 8.4 接入 Cursor 社区插件的 DSH provider 与认证入口，记录服务/数据/profile/端口及必要 Web 串行流程，完成无账号装载 smoke（DSH-05）。
- [x] 8.5 实现 standard preset、低噪声主题、原生权限/任务与图片预览独立设置；核实并诊断外部偏好优先级（DSH-03、DSH-09）。
- [x] 8.6 实现 stdio/远端 MCP 转换及不支持秘密引用时的明确错误，覆盖本地私有 MCP 和默认空选择（DSH-07、CFG-02）。
- [x] 8.7 核实百炼/private gateway 实例字段与模型/参数说明，保留未知能力；确认可选插件启用门槛与无 Superpowers 实际依赖（DSH-06、DSH-08）。
- [x] 8.8 单独运行临时 home 的 DSH 无账号 smoke，验证规则/完整技能、主题、原生配置、插件归属与生成产物，不报告真实模型调用成功（DSH-10）。

## 9. OpenSpec 指定项目集成

- [x] 9.1 实现仅使用锁定 OpenSpec 安装产物的 project 命令和缺包提示，禁止全局/未锁定回退（OS-01）。
- [x] 9.2 实现指定项目的预检查、argv/cwd/环境隔离、产物清单及重复初始化/冲突处理（OS-02、OS-04）。
- [x] 9.3 根据核实结果实现 DSH 原生或上游支持的自定义集成，显式无账号 smoke 证明 DSH 实际加载产物（OS-03）。
- [x] 9.4 测试双项目与外部哨兵隔离、中文空格路径、重复执行/用户修改/中途失败，确认 apply/sync 不初始化业务项目（OS-02、OS-04）。

## 10. 多工具契约与维护 skill

- [x] 10.1 用测试适配器验证公共 render/plan/apply/rollback 无 DSH 特殊分支，各工具/profile 的配置、锁和备份独立（EXT-01、EXT-04）。
- [x] 10.2 编写增加 Pi/Codex 等第二工具的适配步骤、原生字段/认证/依赖/所有权清单及契约测试说明，首版仅公布 DSH 支持（EXT-02、EXT-03）。
- [x] 10.3 按 skill-creator 规范编写完整 maintain-agent-config 技能与必要 references，说明如何定位 rotom、选择本地文件和实例（SKILL-01）。
- [x] 10.4 在维护技能中加入本地 TOML 字段路由、合法 provider/model/MCP/多 profile 示例、数组/false/路径/环境语义和 validate 流程（SKILL-02）。
- [x] 10.5 提供安全的本地局部编辑方式或局部提案流程，保持秘密、注释和其他 profile；必要的辅助脚本须实际验证，不复制整份私有文件（SKILL-03）。
- [x] 10.6 明确技能的源文件/模板/版本更新/capture 边界、仅生成与授权部署区别、调用管理器备份及活动实例处理（SKILL-04、SKILL-05）。
- [x] 10.7 校验技能结构和相对资源，在隔离场景验证私有模型编写、非法字段纠正、canary 保留、仅生成、授权部署与未支持工具处理；如未运行行为验收明确记录（SKILL-06）。

## 11. 综合验收、CI 与日常文档

- [x] 11.1 汇总并执行覆盖产物/日志/异常/diff/argv/锁/备份/journal/generation 输入的 canary 测试，确认私有 endpoint/model 在可分享输出中脱敏（CFG-06、CLI-05）。
- [x] 11.2 添加 Linux/macOS CI：按锁准备测试依赖后离线测试；无账号第三方 smoke 单独显式入口，逐平台记录实际运行状态（DSH-10、LOCK-05）。
- [x] 11.3 编写 README 的 clone→uv sync --locked→init-local→本地填写→validate/plan/sync/apply/doctor/run 流程，测试命令语法与缺环境提示（CLI-01、CLI-02、LOCK-01）。
- [x] 11.4 编写本地格式/字段参考、增加共享 skill/rule/provider/model 的例子、上一版恢复/失败恢复/漂移处理和维护技能使用方式；说明真实源与虚构 fixture 区别（CFG-09、DEP-06、SKILL-02）。
- [x] 11.5 编写 DSH/Codex/Cursor 认证与 OpenSpec 操作说明，明确原生/社区/自定义集成、登录入口、端口串行、配置恢复不回退依赖数据库（DSH-04、DSH-05、OS-03）。
- [x] 11.6 建立 requirement ID→测试/命令/平台/结果的验收矩阵，记录实际环境、上游限制及未完成的 Codex/Cursor 授权 live 验收；不以无账号 smoke 或 CI 文件代替通过证据（DSH-10）。

## 12. 用户授权后的独立 live 验收准备

- [x] 12.1 提供可复查的 Codex/Cursor live 验收步骤、所需用户授权/登录前置条件和脱敏记录模板；未获授权时仅将真实调用标记待验证，不阻塞其余离线实现交付（DSH-05、DSH-10、CLI-06）。

真实 live 调用不是默认实施任务：只有用户另行明确授权并提供目标实例的可用登录态后执行。上述准备任务完成不代表调用已通过，验收矩阵需独立保留其待验证状态。不得为完成此清单读取既有 OAuth、擅自登录、push 或发布。

## 实施验收记录（2026-09-13）

71 项实施任务已交付。完整离线测试：756 passed、7 subtests passed；Linux 原生无账号 smoke、实际锁消费安装与 OpenSpec 项目集成通过。具体 requirement 映射和命令证据见 docs/acceptance.md 与 docs/acceptance-matrix.md。

复选框表示代码、配方、文档或明确要求的验收准备已完成，不表示未执行的外部验收通过：macOS/GitHub CI 尚未运行；真实 Codex/Cursor 登录与模型调用待用户授权；独立 Agent 自动使用维护 skill 的行为评估未执行。没有读取现存 OAuth、push 或发布。

后续整体审查发现与修复由 `harden-agent-config-after-review` 单独跟踪。最新测试和独立维护技能 A 场景结果见 docs/acceptance.md，后续外部验收见 docs/improvement-plan.md；上述 71 项记录保留首版交付时的历史证据。
