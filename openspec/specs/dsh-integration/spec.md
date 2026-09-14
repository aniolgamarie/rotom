# dsh-integration Specification

## Purpose
TBD - created by archiving change build-agent-config-framework. Update Purpose after archive.

## Requirements

### Requirement: DSH-01 Native interfaces are verified against locked sources

DSH 适配 SHALL 使用 `ccch1mneyyy/dsh-TUI`，实施时读取所选版本文档与必要源码，记录 host/TUI/插件完整版本或 SHA、来源和测试平台。host/TUI 启动、包管理/profile、credential env、配置写入范围、规则/技能、MCP、权限、认证与 OpenSpec 接口 MUST 有证据后才写入真实配方。

#### Scenario: Compatibility record distinguishes evidence from assumptions
- **WHEN** 完成版本调查并提交首次真实配方
- **THEN** 每项原生映射可追溯到选定版本的源码/文档或 smoke；未知字段、端口、模型 ID 不以猜测填充，未验证部分明确标记

### Requirement: DSH-02 Native configuration respects complete row replacement and safe tags

适配器 SHALL 按锁定 Cordis 实际 patch 语义渲染；若按 ID 整段替换 config，必须先合成保留不受管内容的完整行。YAML SHALL 使用安全 loader，只有适配器白名单 `!!js` 表达式可原样传递，禁止执行 JS 和 unsafe loader。

#### Scenario: Complete row patch preserves unrelated config
- **WHEN** 原生行有未知字段、动态 provider 和受管 API 字段，仅后者需要修改
- **THEN** 输出完整原生行保留其余配置，并被锁定 host 接受；不把半段 YAML 当原生深合并

#### Scenario: Unknown executable tags are rejected without evaluation
- **WHEN** 配置含允许的 JS 标记或未允许的 JS/其他 YAML 标签
- **THEN** 白名单值仅按原样标记序列化，未知标签失败；任何读取内容均不执行，错误不回显敏感原文

### Requirement: DSH-03 Default recipe retains native permissions and low-noise behavior

真实配方 SHALL 默认 standard preset、受管低噪声 Poimandres 风格主题，保留原生工具/任务/权限；关闭终端图片预览不得关闭已知模型图片输入能力。规则 SHALL 体现中文、nvim、macOS/Linux SSH/tmux、大型 C++ 局部检索和按需索引。不得从长任务需求推断完全访问。

#### Scenario: Terminal settings do not alter model capabilities or permission scope
- **WHEN** 渲染默认 profile，选定模型已知支持图片且 terminal_images=false
- **THEN** 预览关闭、模型图片输入仍保留，权限未提升为完全访问，不创建全仓库索引

### Requirement: DSH-04 Subscription authentication has one owner per provider

Codex SHALL 优先使用配套 dsh-auth 的 openai-codex 路线；Cursor SHALL 使用 `xxww0098/dsh-plugin-oauth-subs` 社区路线在 DSH 内注册 provider。每个 provider SHALL 恰有一个认证拥有者；随包提供的 auth/working-activity 不得重复安装。OAuth 动态目录不要求编造静态 endpoint/model。

#### Scenario: Bundled and community auth compose without duplicates
- **WHEN** 默认配方组合 TUI、配套 Codex auth 与 Cursor 社区插件
- **THEN** 实际插件树无重复 bundled 插件，认证归属唯一；冲突选择在安装前失败，OpenAI API key 与 Codex 订阅入口明确区分

### Requirement: DSH-05 Cursor integration is native to the selected DSH instance

Cursor 接入 SHALL 核实插件所需服务、数据目录、profile、代理端口、认证入口；若需要临时 Web 辅助登录，SHALL 使用同一隔离实例串行运行。验收 SHALL 区分插件可装载、入口可用、登录后模型可见、实际请求走 Cursor provider；不得以 Cursor CLI 调用替代。

#### Scenario: No-account smoke verifies configuration without claiming model access
- **WHEN** 未提供账号，在临时 home 执行显式无账号 Cursor 插件 smoke
- **THEN** 验证可装载和认证入口配置，记录服务/端口使用方式；模型目录与真实调用标为待用户授权登录验收，不读取现有 OAuth 文件

#### Scenario: Authorized live verification proves the provider route
- **WHEN** 用户提供该实例可用登录态并明确授权 live 调用
- **THEN** 验证 DSH 内 Cursor provider/模型可见且请求走该 provider，报告脱敏证据，不导出 token，不启动冲突的 TUI/Web 服务

### Requirement: DSH-06 API and private models use verified metadata and environment references

provider SHALL 支持稳定 ID、protocol、适用的 base_url/auth_kind/credential_ref，model SHALL 区分逻辑 ID、provider、remote_id 与已知输入能力。真实配方和百炼迁移说明 MUST 核实 model ID、medium/SSE/重试等原生映射，未知元数据不得虚构。API key SHALL 为运行时环境引用，不默认要求 DeepSeek key。

#### Scenario: Private provider is rendered without leaking its credential
- **WHEN** 合法本地私有网关/model 被选中并引用 secret
- **THEN** 适配产物使用验证过的环境引用，本地 endpoint/model 只进入私人产物，未知上下文/模态能力不被自动补值

### Requirement: DSH-07 MCP conversion is explicit and defaults to disabled

通用及本地 MCP 定义 SHALL 转换到已核实 DSH 接口，默认选择为空。stdio SHALL 使用命令和 argv 数组；远端凭据 SHALL 使用验证过的运行时引用。不能表达所需秘密引用的服务 MUST 明确失败，不能把密钥写入模板。

#### Scenario: Supported MCP mappings are safe and unused services remain inactive
- **WHEN** registry 有 stdio 与远端服务，profile 先为空后显式选择服务
- **THEN** 空选择不加载 MCP；所选 stdio 保留参数边界，远端仅使用支持的运行时引用，未支持的认证映射在部署前失败

### Requirement: DSH-08 Optional plugins require evidence and prohibited suites stay absent

原生检索 SHALL 可用；ModSearch 仅在兼容 smoke 通过后进入默认配方。Memento/ModLens/MCPLens SHALL 仅登记可选用途，默认不安装。Superpowers MUST 不作为直接或隐含依赖安装。

#### Scenario: An optional plugin without smoke evidence does not enter defaults
- **WHEN** ModSearch 未通过兼容检查，或可选插件仅出现在目录清单
- **THEN** 默认仍使用原生检索，可选插件不自动安装；实际依赖检查发现 Superpowers 时拒绝配方

### Requirement: DSH-09 Preferences outside DSH_HOME are accounted for

适配器 SHALL 核实主题/effort/preset 的原生持久化值与环境优先级，明确 DSH_HOME 外的偏好影响；只使用支持的重定向或管理明确字段，并由 doctor 报告限制。不得复制或接管整个用户 `~/.dsh-tui`。

#### Scenario: External preferences do not silently invalidate managed settings
- **WHEN** 隔离测试中模拟 DSH_HOME 外的优先级更高偏好
- **THEN** 已支持的重定向使受管值生效，或 doctor 明确报告具体影响/不支持字段；不读取真实用户偏好或接管目录

### Requirement: DSH-10 Acceptance evidence is separated by execution level

测试记录 SHALL 分为管理器离线测试、锁定 DSH 无账号 smoke、授权真实 Codex/Cursor 调用。默认测试使用临时 HOME/DSH_HOME/XDG、虚构 fixture 与假进程，不启动第三方宿主；真实 smoke SHALL 为独立显式步骤。Linux/macOS 各自记录运行结果。

#### Scenario: Offline success cannot be promoted to live success
- **WHEN** 只有离线测试与某平台无账号 smoke 完成
- **THEN** 报告仅声明实际通过项目，另一平台与真实模型调用标记待验证，不把 CI 配置文件存在当作 CI 成功
