# 本地机器配置

这是 **agentcfg 框架 TOML**，不是 DSH 原生配置。默认文件在 `$XDG_CONFIG_HOME/agentcfg/machines/<机器>.toml`，XDG 未设置时使用 `~/.config`。初始化用 `./agentcfg init-local --machine workstation`，不会覆盖已有文件。后续命令用前置 `--machine workstation` 或 `--local /绝对路径/local.toml`，两者互斥；缺省选择机器 `default`。

文件权限 0600、私人目录 0700。API key 由用户手工填写，不从其他工具导入。不要打印整份文件、提交 Git 或放进普通部署快照。复制示例时保持 `[secrets]` 值为空，虚构地址不是生产服务。

| 表或字段 | 类型与用途 | 缺省行为 |
|---|---|---|
| `schema_version` | 整数，当前为 1 | 必填；不静默迁移 |
| `machine.id` | 非空单路径段 ID，可含中文/空格，禁止 `/`、反斜线、控制字符、`.`、`..` | 必填 |
| `machine.default_profile` | 仓库中已声明 profile 的 ID | `dsh-default`；命令前置 `--profile` 优先 |
| `machine.editor` | 单个程序名或绝对程序路径，例如 `nvim` | 不填则使用允许的终端环境 |
| `machine.paths.instances_root` | 实例根，绝对路径或 `~/` | XDG_DATA_HOME/agentcfg/instances |
| `machine.paths.state_root` | 状态/锁/上一版备份根 | XDG_STATE_HOME/agentcfg |
| `machine.paths.cache_root` | 私人生成物与安装缓存根 | XDG_CACHE_HOME/agentcfg |
| `machine.environment.inherit` | 明确允许继承的非秘密变量名数组 | `[]`；不会复制全部父环境 |
| `machine.environment.values` | 非秘密变量名到字符串的表 | 空表；不 eval，不展开 `$()` |
| `overrides.providers.<id>` | 覆盖或新增 provider | 未选择的实体不启用 |
| `overrides.models.<id>` | 覆盖或新增模型逻辑 ID | 远端 ID 不代表跨 provider 能力相同 |
| `overrides.mcp.<id>` | 覆盖或新增私有 MCP 定义 | 默认不选中任何服务 |
| `overrides.profiles.<id>` | 覆盖已存在 profile 的选择/角色/工具参数 | 不允许改变所属 agent 或偷偷创建 profile |
| `secrets.<name>` | 真实秘密字符串，配置引用为 `secret:<name>` | 空或缺失不阻止离线生成；实际必需时才失败 |

XDG 未设置时分别回落 `~/.local/share`、`~/.local/state`、`~/.cache`。TOML 路径允许中文和空格；仅开头 `~/` 展开，不支持相对路径、其他用户 `~user`、变量或命令插值。字段存在但为空不等于缺省。editor 不能写成 `nvim -f` 或 shell 命令。

provider 字段：`protocol`、`auth_kind` 必填；静态 API-key provider 需 `base_url`，凭据用 `credential_ref`。动态 OAuth provider 可没有静态地址，不应补虚构地址；路由和认证拥有者由工具 binding 决定。模型字段为 `provider`、`remote_id`、`input`（已知能力数组）；可选 `context_window`、`max_output_tokens` 为已核实的正整数，`source` 记录依据，未知时省略。MCP 的 `command` 与 `args` 是 argv，远端 URL 与凭据引用能否转换由 adapter 检查。

允许覆盖 profile 的 `providers/models/rules/skills/plugins/mcp` 选择数组、`roles` 模型别名和经 adapter schema 校验的 `agent_options`。合并顺序为 registry/工具默认值 → profile → 本地 overrides → 明确支持的单次参数；对象递归，数组整体替换，标量覆盖。`mcp = []` 清空选择，`terminal_images = false` 保留 false。省略字段继承原值；删除 registry 中仍被引用的 ID 会失败。

## 私有网关示例

```toml
schema_version = 1
[machine]
id = "workstation"
default_profile = "dsh-default"
editor = "nvim"
[overrides.providers.private_gateway]
protocol = "openai-compatible"
auth_kind = "api-key"
base_url = "https://gateway.example.invalid/v1"
credential_ref = "secret:private_gateway_key"
[overrides.models.private_main]
provider = "private_gateway"
remote_id = "fictional-private-chat"
input = ["text"]
[overrides.profiles.dsh-default]
providers = ["private_gateway"]
models = ["private_main"]
mcp = []
[overrides.profiles.dsh-default.roles]
main = "private_main"
[secrets]
private_gateway_key = ""
```

地址和模型须改为实际服务的已核实值；填写前先确认对应 adapter 已支持该协议。更多纯框架例子见 `examples/*.example.toml`。目前例子中的 `dsh-ssh` 需要仓库显式声明对应 profile；不能仅复制一个 override 就创建 profile。

环境表禁止覆盖管理器掌管的 HOME/XDG、DSH_/AGENTCFG_ 前缀、NODE_OPTIONS/NODE_PATH 或凭据目标变量。不要把带密码 URL、API_KEY、ACCESS_TOKEN 等放入普通环境表。machine.editor 会覆盖 EDITOR/VISUAL。编辑本地文件时只改本次需要的表，保留其他 profile、注释和秘密区域；无法安全局部修改时先形成局部提案。校验错误只展示字段位置和原因，私有值默认脱敏。

配置生成与部署不同：`render/plan` 不修改实例；`apply` 才应用并维护上一版备份。同一凭据引用下的 key 轮换在下一次启动解析，不需要将 key 写入生成配置。框架的备份不覆盖这份含秘密的机器文件。
