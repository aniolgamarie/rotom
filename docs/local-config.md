# 本地机器配置

这是 **agentcfg 框架 TOML**，不是 DSH 原生配置。默认文件在 `$XDG_CONFIG_HOME/agentcfg/machines/<机器>.toml`，XDG 未设置时使用 `~/.config`。先运行 `./agentcfg profiles` 查看可选配方，再用 `./agentcfg init-local [--machine NAME] [--profile ID]` 初始化或补齐占位；不写机器名时选择 `default`。后续命令用前置 `--machine NAME` 或 `--local /绝对路径/local.toml`，两者互斥；缺省选择机器 `default`。

`init-local` 根据所选 profile 及其继承的全局默认生成实际需要的字段：机器文件中增加缺失的 `[local_values]` URL 空值，共享密钥文件中增加缺失的 key 空值。以 `omp-kernel` 为例，会准备两个 TF URL 字段、三个官方 key 和两个 TF key。已有文件也会校验并补齐，保留已填写值、其他配置、注释和已有密钥分组；没有缺项时不重写文件。重复引用只生成一个占位，旧机器文件中已有的密钥声明不迁移或复制。

```sh
# 新机器初始化和已有机器补齐使用同一命令
./agentcfg init-local --machine workstation --profile omp-kernel
./agentcfg --machine workstation --profile omp-kernel model status
```

省略 `--profile` 时，已有机器使用其 `default_profile`，新机器回落到 `dsh-default`。显式指定 profile 会为它补齐字段，不改变已有机器的默认 profile。初始化只准备字段，不填写真实地址或 key、不联网、不部署；未知字段、无效格式、机器 ID 不匹配或不安全权限会报错，不按模板覆盖修复。修改现有文件使用快照检查；关联写入失败时尝试回滚本次共享文件修改，并拒绝覆盖并发更新。

机器文件权限 0600、私人目录 0700。新建机器文件不含密钥；API key 默认写入 `$XDG_CONFIG_HOME/agentcfg/secrets.toml`（XDG 未设置时为 `~/.config/agentcfg/secrets.toml`），所有工具、机器选择和 profile 共用。管理器不导入其他工具的认证，也不联网验证 key。

DeepSeek、Kimi、GLM 的官方直连默认由 [`shared/defaults/models.toml`](../shared/defaults/models.toml) 加入所有 DSH、Pi、OMP profile。DSH/Pi 使用 OpenAI 兼容协议，OMP 使用 Anthropic 兼容协议。同一服务的不同协议共用 `deepseek_key`、`kimi_key`、`glm_key`。未指定主模型时默认 DeepSeek；profile 和本地 overrides 的显式角色优先。Pi 所需而未绑定的资源角色继承当前主模型。profile 的 provider/model 列表与默认集合去重追加，不必复制默认项；普通 rules、skills、plugins、MCP 数组仍按原有覆盖规则处理。

```sh
./agentcfg --machine workstation --profile omp-kernel model status
./agentcfg --machine workstation model key deepseek
./agentcfg --machine workstation model key kimi
./agentcfg --machine workstation model key glm
```

`model status` 默认显示缺项摘要、provider 来源与状态、角色绑定，以及文件路径、TOML 分组、密钥名与 provider 对应关系，便于直接编辑。加 `--verbose` 展开完整模型目录和保留当前机器/profile 的逐项填写命令。状态页不显示私人 URL 或 key 实际值，也不验证部署同步或账号连通性。`model key` 仅从终端隐藏输入读取 key，留空取消；不存在的共享文件会以 0600 创建。命令行不接受 key 值。已配置只表示有非空值；缺少模型 key 仍允许启动，相应模型请求需要凭据。只更新 key 后退出并重新 `run`；URL/provider/model/角色改变后退出工具，执行 `setup` 再 `run`，已经运行的实例不会自动刷新。

共享文件格式如下，实际值由上述命令写入，不要将真实内容粘贴给 Agent：

```toml
schema_version = 1

# 三家官方默认凭据，由各工具和 profile 共同引用。
[shared]
deepseek_key = ""
kimi_key = ""
glm_key = ""

# omp-kernel 追加的 TF provider；其他选择相同 provider 的 profile 也可复用。
[providers.kimi_tf]
omp_kimi_tf_key = ""

[providers.zhipu_tf]
omp_zhipu_tf_key = ""
```

新 key 自动分类：三个默认官方引用进入 `[shared]`，额外 provider 的 key 进入 `[providers.<provider-id>]`；`model key` 在输入前显示保存文件和分组。分组是组织方式，不是 profile 访问隔离，也不改变 `secret:<name>` 引用。密钥名在整个文件中必须唯一；跨组重复（包括空占位符）会报错。多个 profile 共用同一 provider 时引用同一个条目，不需要复制 key。

旧共享文件的平铺 `[secrets]` 仍可读取和更新，状态页会标注“旧格式”。已有 key 保持原组和注释，不自动搬迁或重排整份文件；同一次更新只改目标条目。新分组也可与旧表并存，但不可重复声明相同密钥名。

机器文件顶层可设置 `secrets_file = "~/private/agentcfg/secrets.toml"` 指定另一份共享文件，只支持绝对路径或 `~/`，不展开环境变量，不能指向机器文件或仓库内文件。缺失文件视为尚未填写；已存在的文件必须通过权限、属主、无链接校验。旧机器文件的 `[secrets]` 继续兼容，空占位符不遮蔽共享值；同一个引用在两处都有非空值时明确拒绝，避免悄悄用错账号。`model key` 更新已有旧 key 时会说明仍写回原位置，不自动迁移或删除旧秘密。把新 key 分文件降低误读和误分享风险，不构成对同用户进程的访问隔离。

`./agentcfg model presets` 无需机器文件即可查看官方模型概要；`./agentcfg model presets --verbose` 展开公开地址、规格、计价和来源。`model enable deepseek|kimi|glm` 保留为显式添加协议路线的兼容入口，通常无需再执行；OMP 可用 `--protocol openai` 追加另一种协议。它不会替换已有主模型角色。

企业地址等私人配置可以保存在机器文件 `[local_values]` 中。公共 provider 使用 `base_url_ref = "local:<名称>"` 引用地址，和直接 `base_url` 二选一；当前引用仅用于 provider URL，不进行通用字符串插值、环境变量展开或命令执行。例子：

```toml
# 公共 provider 定义，仅保存引用
[providers.kimi_tf]
protocol = "openai-compatible"
auth_kind = "api-key"
base_url_ref = "local:tf_openai_url"
credential_ref = "secret:omp_kimi_tf_key"
```

```toml
# 私人 machines/workstation.toml 中填写；这里的域名仅为虚构示例
[local_values]
tf_openai_url = "https://gateway.example.invalid/v1"
tf_anthropic_url = "https://gateway.example.invalid/anthropic"
```

用 `./agentcfg --machine workstation --profile omp-kernel model url kimi_tf` 隐藏输入真实地址。`model status` 不显示实际 URL，只显示是否配置和填写位置；`--verbose` 展开逐项填写命令。缺 URL 不影响状态查看和补 key，但当前 profile 的部署、启动必须先补齐；未选择该 provider 的其他 profile 不因它缺值而失败。地址需为合法 HTTP(S) 绝对地址且不得包含 userinfo、凭据查询参数或控制字符。已有私人 `overrides.providers.<id>.base_url` 可以直接替换公共引用；反向用 `base_url_ref` 替换公共 literal 也支持，但同一层不能同时声明两者。

本地值不属于 API key 存储。未使用的 `local_values` 不进入生成结果；已引用地址必须进入本机私人原生配置供宿主连接，因此不能分享完整部署产物。公共仓库中只保留引用及虚构测试地址。只做结构和引用校验时，未选 profile 的缺失地址会推迟依赖地址的适配器校验；选择或部署它时必须补齐并通过完整校验。

已有机器文件可以运行 `./agentcfg [--machine NAME] model add`，交互式一次新增私有 API-key provider、模型、选择列表和角色绑定。密钥用隐藏输入读取；该向导要求填写密钥，以保证新模型写入后即可调用。向导先完成 schema、适配器和候选产物校验，展示不含密钥的摘要；输入 `yes` 后写入 0600 私人配置和共享密钥文件；若配置提交失败，会尝试回滚本次共享密钥版本，并拒绝覆盖并发修改。它保留未触及的注释与字段；遇到复杂多行 TOML 或不能安全定位的表会拒绝改写并保持原文件。向导只支持新增静态 API-key 模型；OAuth 和现有实体更新仍使用明确的配置编辑流程。

这些约束在每次读取时执行，不只在 init-local 时执行：拒绝符号链接、硬链接、非普通文件、不安全属主/权限及读取竞态。CLI `--local` 可用相对路径，包括经过真实目录检查的 `../`；框架 TOML 中的路径字段仍只接受下文的绝对路径/`~/` 规则。

TOML 语法或编码错误返回 2，并给出安全来源和从 1 开始的行列，例如 `parse @ local.line.8.column.12.TOML`。`local` 指本次选择的私人机器文件，不回显其路径、正文或秘密字段。公共来源显示类别及加载序号：`registry.N`、`profile.N`、`adapter.N.agent|bindings|plugins`。默认仓库按文件名排序加载 `shared/*.toml` 和 `profiles/*.toml`；registry 再按适配器注册顺序追加已有的 `agents/<id>/content.toml`，adapter 顺序见 `src/agentcfg/workspace.py` 的 `ADAPTER_TYPES`。序号从 1 开始，表示本次加载顺序，不是永久文件 ID。修复语法后重新执行原命令，不要为排查而打印含秘密的整份文件。

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
| `local_values.<name>` | 私人字符串值，当前用于 provider 的 `local:<name>` URL 引用 | 缺失或空值在选中使用时必须补齐；不回显实际值 |
| `secrets_file` | 顶层共享密钥文件路径 | `$XDG_CONFIG_HOME/agentcfg/secrets.toml`，或 `~/.config/agentcfg/secrets.toml` |
| `secrets.<name>` | 旧内联秘密，引用为 `secret:<name>` | 向后兼容；新 key 默认写共享文件，不应把真实值交给 Agent |

XDG 未设置时分别回落 `~/.local/share`、`~/.local/state`、`~/.cache`。TOML 路径允许中文和空格；仅开头 `~/` 展开，不支持相对路径、其他用户 `~user`、变量或命令插值。字段存在但为空不等于缺省。editor 不能写成 `nvim -f` 或 shell 命令。

provider 字段：`protocol`、`auth_kind` 必填；静态 API-key provider 需 `base_url` 或 `base_url_ref`，凭据用 `credential_ref`。动态 OAuth provider 可没有静态地址，不应补虚构地址；路由和认证拥有者由工具 binding 决定。模型字段为 `provider`、`remote_id`、`input`（已知能力数组）；可选 `context_window`、`max_output_tokens` 为原生表使用的已核实正整数，`max_output_supported` 可额外记录服务端上限，`name`、`reasoning`、`reasoning_efforts` 和 `source` 记录展示名、推理能力及依据，未知时省略。Kimi K3 的原生默认输出上限设为 131072，同时记录官方支持的 1048576 上限。`native.pi`、`native.omp` 仅容纳 schema 明确允许的兼容字段；DeepSeek OpenAI 预设据官方接入文档记录思考等级、历史消息与工具调用要求。`pricing` 记录币种、每百万 token 的输入/输出/缓存读写单价、查询日期和来源；分时价格另记 `off_peak` 与 `schedule`。价格是目录快照，使用前请在官方页面复核。OMP/Pi 将容量和推理能力投影到原生模型表；DSH 当前只支持容量。三种工具的原生成本字段均不能准确表达人民币币种或 DeepSeek 分时费率，因此公共价格保留在目录与 `model presets` 输出中，不写成误导性的原生成本。MCP 的 `command` 与 `args` 是 argv，远端 URL 与凭据引用能否转换由 adapter 检查。

允许覆盖 profile 的 `providers/models/rules/skills/plugins/mcp` 选择数组、`roles` 模型别名和经 adapter schema 校验的 `agent_options`。合并顺序为 registry/工具默认值 → profile → 本地 overrides → 明确支持的单次参数；对象递归，标量覆盖；providers/models 按层去重追加，其他数组整体替换。`mcp = []` 清空选择，`terminal_images = false` 保留 false。省略字段继承原值；删除 registry 中仍被引用的 ID 会失败。

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
```

配置后运行 `./agentcfg --machine NAME --profile dsh-default model key private_gateway` 隐藏输入其 key。

地址和模型须改为实际服务的已核实值；填写前先确认对应 adapter 已支持该协议。更多纯框架例子见 `examples/*.example.toml`。目前例子中的 `dsh-ssh` 需要仓库显式声明对应 profile；不能仅复制一个 override 就创建 profile。

环境表禁止覆盖管理器掌管的 HOME/XDG、DSH_/AGENTCFG_ 前缀、NODE_OPTIONS/NODE_PATH 或凭据目标变量。不要把带密码 URL、API_KEY、ACCESS_TOKEN 等放入普通环境表。machine.editor 会覆盖 EDITOR/VISUAL。编辑本地文件时只改本次需要的表，保留其他 profile、注释和秘密区域；无法安全局部修改时先形成局部提案。校验错误只展示字段位置和原因，私有值默认脱敏。

配置生成与部署不同：`render/plan` 不修改实例；`apply` 才应用并维护上一版备份。同一凭据引用下的 key 轮换在下一次启动解析，不需要将 key 写入生成配置。框架的备份不覆盖这份含秘密的机器文件。
