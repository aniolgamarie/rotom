# DSH 接入与认证

## 锁定配方

| 组件 | 固定身份 |
|---|---|
| DSH | `@deepseek-ai/dsh@0.1.5-rc.1`，host 组件统一该版本 |
| TUI | `@deepseek-harness-tui/dsh-tui@0.10.1`；修复 bundled `workspace:*` 元数据，运行代码不变 |
| Codex 认证 | TUI 自带 `dsh-auth@0.1.0`，只选择 `openai-codex`，不重复安装 |
| Cursor 认证 | `dsh-plugin-oauth-subs` 固定 SHA `793978ee3b72a1c81d8b769b269ac2fa3bc90654`；本地包 `0.0.88-agentcfg.1` |
| OpenSpec | `@fission-ai/openspec@1.13.0` |
| 工具链 | Node `24.14.0`、npm `11.19.1` |

完整传递依赖和 integrity 在 `locks/dsh/package-lock.json`；完整源码 SHA、工具链和平台记录在 manifest。`scripts/vendor-tui.py` 与 `scripts/vendor-cursor.py` 可从对应公开归档重建本地 tarball；补丁和逐文件摘要在 `locks/dsh/vendor/`。升级必须更新来源证据、依赖输入和 vendor，执行 lock，测试后再 sync/apply。

## Codex 订阅

先按 README sync/apply/run，在 DSH TUI 使用：

```text
/auth status
/auth login openai-codex
```

按原生交互完成登录，再通过 `/model` 选择其模型。这是订阅账号认证，不是填写 OpenAI API key。配置复刻不迁移账号；新机器需要重新登录。

## Cursor 订阅（社区适配）

在同一受管 DSH TUI 中运行：

```text
/cursor-login
```

打开命令返回的 URL，完成 Cursor 账号登录。社区插件在当前实例后台轮询授权，成功后更新 DSH 内 `oauth-cursor` provider 的模型目录，再用 `/model` 选择。取消尚未完成的流程使用 `/cursor-login cancel`。这不是调用 Cursor CLI。

本配方增加了原生 `commands` 登录入口，因此不需要另开临时 Web 宿主。插件 loopback proxy 默认在 `127.0.0.1:8318`；数据显式放在固定的 `dsh-home/oauth-subs`。多个 profile 同时运行时，在本地各 profile 的 `agent_options.cursor_port` 指定不同的 1024–65535 端口。端口不是 OAuth 回调地址，Cursor 采用远端轮询。

本地补丁关闭 Cursor/Ollama/Kimi/Copilot 自动导入，禁用后台升级和运行包 stamp；不使用 `NODE_TEST_CONTEXT` 冒充生产隔离。账号、refresh token、动态目录和 proxy-key 均归原生插件保管，不由管理器捕获、备份或回滚。

无账号 smoke 已验证入口和插件可加载，不等于真实订阅调用已验证；登录、模型可见性和实际请求走目标 provider 仍须按验收文档完成用户授权的 live 测试。

## API、百炼与私有网关

通过本地 `overrides.providers/models` 定义实际 endpoint/model；首版映射 `openai-compatible`→`openai-completions`、`openai-responses`→`openai-responses`。API provider 需要 `secret:` 引用，真实值启动时才进入选定环境变量，原生设置仅保存 `apiKeyEnv` 名称。

百炼可使用兼容协议接入，但必须从实际产品/地域/套餐文档确认 base URL 和 model ID；本仓库不默认猜测 qwen ID，也不将订阅套餐 endpoint 与普通按量 API 混用。下面仅说明已经核实的 DSH 参数结构，不证明任意远端模型都支持这些参数：

```toml
# 框架 TOML；private_gateway 必须是当前 profile 已选择的 provider。
[overrides.profiles.dsh-default.agent_options.provider_options.private_gateway]
reasoning = "medium"
transport = "sse"

[overrides.profiles.dsh-default.agent_options.provider_options.private_gateway.retryPolicy]
mode = "normal"
maxRetries = 2
```

已核实的原生 reasoning 词汇为 off/minimal/low/medium/high/xhigh/max；远端支持情况需另查。retry 的 always 模式没有 maxRetries。已知模型容量可用 `context_window`、`max_output_tokens` 和 `source` 记录，未知时省略；框架不会填虚构上限，原生库自己的默认值仍可能参与运行。

目前 `agent_options.provider_options` 只支持静态 API-key provider。给 Codex/Cursor OAuth provider 填这些选项会在 validate 失败，不再静默忽略。OAuth 参数持久化的字段所有权仍需专项核实，不能套用静态 provider 写入覆盖动态账号目录。

## 原生所有权与优先级

- `dsh-home/AGENTS.md`、完整技能、独占 overlay、独占主题是整文件受管。
- 静态 API provider 的明确字段位于混合 `settings.yaml`，逐字段三方合并；原生 OAuth provider 和未知字段保留。
- Cordis config 按行 ID 整段替换，本配方先合成完整 TUI config；不会执行读取到的 JS。管理器只允许已审核字段位置的少量标量表达式，拒绝 `__jsExpr` 等未标记载体。
- profile package.json/node_modules 链接归运行包准备流程管理；启动选择已部署 lock 的运行包，原生自身重写的 cordis.yml 不参与配置备份。
- HOME 固定为实例 `user-home`，避免真实 `~/.dsh-tui` 干扰。主题从该 home 的独占文件加载；terminal image 环境开关可压过原生保存的偏好，关闭预览不改变模型图片能力。
- 默认 standard preset、workspace-write 权限；恢复原生旧会话时，原生保存的 preset 仍可能生效。共享规则不能消除内置系统提示差异。
- `env-guard.mjs` 在锁定 host 导入前阻止其隐式读取 cwd/.env 与 DSH_HOME/.env；保持业务 cwd。这是已知读取接口的适配，不是 OS 沙箱。Agent 工具进程仍可能接触已注入的选定密钥。

## MCP

默认不选中服务。stdio 使用 `command` 和 `args`，转换为原生 `transport: stdio`；http/streamable-http 转为 `streamable-http`。远端 `credential_ref` 表示完整 Authorization header 的 secret 引用，通过审核过的 `process.env.AGENTCFG_MCP_<hash>` 标量传入；不将密钥写入 YAML。首版 stdio 未定义凭据环境映射时会拒绝 credential_ref，不猜变量名。

原生连接失败不一定让整个 host 启动失败，因此配置加载通过不能当作真实 MCP 服务可用。可选 ModSearch 尚未完成兼容 smoke，保持原生检索；Memento、ModLens、MCPLens 不默认安装。Superpowers 不在依赖或技能中。
