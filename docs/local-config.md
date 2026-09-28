# 本地机器配置

这是 **agentcfg 框架 TOML**，不是 DSH 原生配置。默认文件在 `$XDG_CONFIG_HOME/agentcfg/machines/<机器>.toml`，XDG 未设置时使用 `~/.config`。先运行 `./agentcfg profiles` 查看可选配方，再用 `./agentcfg init-local [--machine NAME] [--profile ID]` 初始化；不写机器名时创建 `default`，不会覆盖已有文件。后续命令用前置 `--machine NAME` 或 `--local /绝对路径/local.toml`，两者互斥；缺省选择机器 `default`。

文件权限 0600、私人目录 0700。API key 由用户手工填写，不从其他工具导入。不要打印整份文件、提交 Git 或放进普通部署快照。复制示例时保持 `[secrets]` 值为空，虚构地址不是生产服务。

DeepSeek、Kimi、GLM 的官方直连模型已登记在 `shared/providers.toml` 和 `shared/models.toml`。`./agentcfg model presets` 无需机器文件即可查看 OpenAI/Anthropic 地址、容量、能力、价格和来源。初始化在私人 `[secrets]` 中预置三个空 key 字段，但不自动选择这些 API 模型；因此没有填写 key 时，已有的订阅登录或其他已配置工具仍可启动。在终端运行 `./agentcfg [--machine NAME] [--profile ID] model enable deepseek|kimi|glm`，向导会隐藏输入该服务的 key，按 DSH/Pi 的 OpenAI 兼容协议或 OMP 的 Anthropic 兼容协议选择对应公共模型，并在当前 profile 没有 `main` 角色时绑定它。Pi 首次绑定主模型时，也会绑定其已启用代理资源所需的角色。OMP 可用 `--protocol openai` 改用 OpenAI 兼容地址。相同服务的两种协议和多个 profile 共用一份私人 key；确认写入前先校验候选配置与原生产物。若 Pi 锁不可用，向导会对原生产物做不含锁身份的离线校验并明确警告，完整锁验证留待补齐锁后执行 `validate`；已配置的角色和其他 profile 不会被覆盖。

已有机器文件可以运行 `./agentcfg [--machine NAME] model add`，交互式一次新增私有 API-key provider、模型、选择列表和角色绑定。密钥用隐藏输入读取；该向导要求填写密钥，以保证新模型写入后即可调用。向导先完成 schema、适配器和候选产物校验，展示不含密钥的摘要；输入 `yes` 后才原子写入 0600 私人文件。它保留未触及的注释与字段；遇到复杂多行 TOML 或不能安全定位的表会拒绝改写并保持原文件。向导只支持新增静态 API-key 模型；OAuth 和现有实体更新仍使用明确的配置编辑流程。

这些约束在每次读取时执行，不只在 init-local 时执行：拒绝符号链接、硬链接、非普通文件、不安全属主/权限及读取竞态。CLI `--local` 可用相对路径，包括经过真实目录检查的 `../`；框架 TOML 中的路径字段仍只接受下文的绝对路径/`~/` 规则。

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
| `secrets.<name>` | 真实秘密字符串，配置引用为 `secret:<name>` | 空或缺失不阻止离线生成；模型 key 缺失不阻止启动，必需的服务凭据缺失仍会失败 |

XDG 未设置时分别回落 `~/.local/share`、`~/.local/state`、`~/.cache`。TOML 路径允许中文和空格；仅开头 `~/` 展开，不支持相对路径、其他用户 `~user`、变量或命令插值。字段存在但为空不等于缺省。editor 不能写成 `nvim -f` 或 shell 命令。

provider 字段：`protocol`、`auth_kind` 必填；静态 API-key provider 需 `base_url`，凭据用 `credential_ref`。动态 OAuth provider 可没有静态地址，不应补虚构地址；路由和认证拥有者由工具 binding 决定。模型字段为 `provider`、`remote_id`、`input`（已知能力数组）；可选 `context_window`、`max_output_tokens` 为原生表使用的已核实正整数，`max_output_supported` 可额外记录服务端上限，`name`、`reasoning`、`reasoning_efforts` 和 `source` 记录展示名、推理能力及依据，未知时省略。Kimi K3 的原生默认输出上限设为 131072，同时记录官方支持的 1048576 上限。`native.pi`、`native.omp` 仅容纳 schema 明确允许的兼容字段；DeepSeek OpenAI 预设据官方接入文档记录思考等级、历史消息与工具调用要求。`pricing` 记录币种、每百万 token 的输入/输出/缓存读写单价、查询日期和来源；分时价格另记 `off_peak` 与 `schedule`。价格是目录快照，使用前请在官方页面复核。OMP/Pi 将容量和推理能力投影到原生模型表；DSH 当前只支持容量。三种工具的原生成本字段均不能准确表达人民币币种或 DeepSeek 分时费率，因此公共价格保留在目录与 `model presets` 输出中，不写成误导性的原生成本。MCP 的 `command` 与 `args` 是 argv，远端 URL 与凭据引用能否转换由 adapter 检查。

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
