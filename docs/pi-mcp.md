# MCP 接入状态与配置

MCP 适配源码已登记四个配方，临时副本的真实依赖解析和安装检查通过；最终发布锁尚未冻结。以下能力已有代码和隔离验证，真实插件加载、OAuth、浏览器 UI 与服务调用仍待验收。

## 服务来源

只加载 registry 中被 profile 选中的 MCP 服务，并在 `agent_options.mcp.servers` 为每个服务提供匹配绑定。不扫描全局 HOME、项目 MCP 配置或环境中的服务列表。

- stdio：`command_ref` 指向明确的交互式 `external_tools`。registry 的 command/args 必须逐字匹配绑定；进程进入已有 manager、监督者和已声明的文件范围。
- HTTP/SSE：声明 `network_route` 和 `authentication="none"`、`"bearer"` 或 `"oauth"`；路线 `service_ids` 包含 `mcp:服务名`。Bearer／OAuth client secret 来自该服务的 SecretRef。
- HTTP 传输固定源站与路线，不跟随跳转；代理失败不会直连。关闭时取消未完成请求体和活动请求。

示例见 [pi-services.toml](../examples/pi-services.toml)。Bearer 成功不等同于 OAuth 验收。

## OAuth 与直接工具

OAuth 服务将原服务绑定替换为如下内容；源站和 URI 都替换为所选服务的真实声明。公共 OAuth 客户端应移除 registry 中的 credential_ref；需要 client secret 时，须同时填写 client_id，并让 credential_ref 指向客户端秘密，不能沿用 Bearer token。

```toml
[overrides.profiles.pi-default.agent_options.mcp.servers.documentation]
transport = "streamable-http"
network_route = "documentation-proxy"
authentication = "oauth"

[overrides.profiles.pi-default.agent_options.mcp.servers.documentation.oauth]
grant_type = "authorization_code"
allowed_origins = ["https://auth.example.invalid"]
redirect_uri = "http://localhost:8765/callback"
# client_id = "YOUR_REGISTERED_CLIENT_ID"
# auth_server_metadata_url = "https://auth.example.invalid/.well-known/oauth-authorization-server"

[overrides.profiles.pi-default.agent_options.mcp.servers.documentation.direct_tools]
enabled = true
tools = ["search"]
```

本地回调只绑定声明的 loopback 端口；HTTPS 远端回调使用完整回调 URL 手工完成。`client_credentials` 模式必须指定 client_id 和服务 SecretRef，不能带 redirect_uri。发现、换码、刷新和授权 URL 必须属于明确授权的源站；代理失败不改路线。客户端秘密按原值使用，`!`、环境变量样式的内容也不会变成命令或再次展开。

凭据和缓存按当前实例及认证绑定隔离。更改客户端身份后不借旧账号；不导入、删除旧明文文件，也不回退系统 Keychain/keyring。

直接工具默认关闭；省略 `tools` 表示启用该服务发现的全部直接工具，提供列表则仅选择原始工具名。按服务分组的 `mcp__服务名` 入口与直接工具都使用真实登记记录准入，不能靠伪造前缀取得权限。只有 main 角色可以调用；撤销登记后旧函数失效。

## 模型辅助请求（sampling）

默认关闭。需要时添加：

```toml
[overrides.profiles.pi-default.agent_options.mcp.sampling]
enabled = true
model = "agentcfg-example/fictional-exact-model"
max_tokens = 1024
auto_approve = false
```

`model` 是当前实例明确选中的原生 provider/model；省略时使用当前主模型，仍须位于受约束模型集合内。远端模型 hints 不会触发切换或账号扫描。调用经同一个 ModelRuntime，重试为零；超出 token 上限的请求拒绝。

默认在请求发送前和结果交回服务前分别确认。只有明确配置 `auto_approve=true` 才能省略确认。受管调用拒绝；有活动 Task Keeper 相关工作时仍服从普通 helper 边界。

## 服务请求用户输入（elicitation）

`agent_options.mcp.elicitation=true` 才启用。表单保留原有确认和提交步骤；URL 只接受 HTTP(S) 且不能带用户名密码或控制字符，用户选择显示链接后才输出 OSC 8 终端链接。用户在浏览器中打开链接，插件不自行启动浏览器进程。

URL 分支已有隔离测试；表单 schema validator 和真实终端交互仍需完整插件／原生验证。此能力不等同于 MCP Apps 的本地 UI 服务。

## 脚本调用多个 MCP 工具

默认关闭。启用时明确绑定锁定版本的 Node 解释器：

```toml
[overrides.profiles.pi-default.agent_options.mcp.scripting]
enabled = true
tool_ref = "mcp-script-node"
max_seconds = 30

[overrides.profiles.pi-default.agent_options.external_tools.mcp-script-node]
executable = "/absolute/path/to/node"
version = "v24.14.0"
args = []
```

所选 Permission Policy 来源还须包含命令授权：

```json
{"id":"mcp-script-node","kind":"command","effect":"allow","command_ref":"tool:mcp-script-node","tool_ids":["bash"],"operations":["execute"]}
```

`mcpScript` 只向 main 角色开放。监督者固定脚本入口与解释器身份，脚本从 stdin 接收，使用每次运行的私人目录和无网络沙箱；业务工作树、账号环境与父监督凭据不传入脚本进程。JavaScript VM 负责计算上下文，实际文件和网络访问范围由进程沙箱限制。

脚本的 `tools.call/search/describe` 交回父侧分派，仍只能访问已选 MCP 能力。超时或取消会停止监督进程并等待物理终止；关闭时也等待已派发请求结束。未证明终止时保持保护，不能当作成功。

源码类型检查、固定脚本语法检查、假进程／假通道测试已通过。真实 Node 解释器、操作系统沙箱、服务调用和平台终止尚未执行。

## MCP Apps 页面服务

需要页面时明确选择：

```toml
[overrides.profiles.pi-default.agent_options.mcp.apps]
enabled = true
browser_network = "user-browser"
host_port = 0
proxy_port = 0
max_seconds = 1800
allowed_browser_origins = []
permissions = []
```

两个端口仅绑定 `127.0.0.1`；0 表示由操作系统分配，固定端口不能相同。它们共用现有 manager 的一条活动记录，父 Pi 进程由 supervisor 监督。关闭时终止连接并等待已发出的请求结束；未知关闭不会被当作释放成功。

页面使用标准浏览器，通过终端链接交给用户打开。远程使用时须转发两个 loopback 端口。浏览器的外部请求使用用户浏览器网络，不继承 agentcfg 的服务代理；页面声明的外部源站必须在 allowed_browser_origins 中，摄像头、麦克风、位置或剪贴板权限也须显式选择。App 请求启动新的 agent turn 还须在 Pi 界面确认。

## 验证界限

已有静态类型、隔离回归和临时安装证据；最终锁、四平台原生行为、浏览器交互和真实服务验收仍待完成。所有已选 MCP 实网验收保留，当前没有 MCP live passed 记录。


长期 stdio 服务与有限执行任务使用同一 manager/supervisor，分别限制容量：执行任务最多 2 个，服务进程最多 16 个，manager 的资源记录总数也最多 16 个。服务仍受原有文件范围、工作区租约和物理终止核验约束；声明可写业务根的长期服务会持续占有相应写租约，不能与同工作区其他写入者并用。服务分类只由匹配的 MCP stdio 准入登记，模型不能把普通任务声明成服务绕过上限。

stdio 命令当前使用无外网的文件沙箱和最小环境，不继承机器上的代理变量、登录环境或系统配置。需要远端网络与认证的服务使用显式 HTTP/SSE 绑定。把需要联网的任意本地 MCP 程序直接配置为 stdio，不会因此获得隐式网络能力；应在验收中明确报告该传输前提。
