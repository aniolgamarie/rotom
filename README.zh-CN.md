# rotom / agentcfg

[English](README.md) | **中文**

个人 Agent 配置管理仓库：公共规则、完整技能包、工具模板和依赖锁进入 Git，机器覆盖与 API key 留在仓库外。通过一个入口生成、检查、部署和启动独立实例；每个实例只保留上一版受管配置备份。

首版实现 **DSH + ccch1mneyyy/dsh-TUI**。Pi 迁移 spec 已按约定范围完成：软件集成、Linux x86_64 四配方 mock/native 验证，以及每配方两个全新 HOME/checkout 路径的冷重建。验收候选为 `9d6a9270`；其他平台与真实账号／服务仍未验证，已转入[独立后续清单](docs/follow-ups/pi-platform-and-live-validation.md)。Pi 中的 Codex 通过 model-delegate 调用官方 CLI，旧 codex-delegate 不作为迁移目标依赖。配置入口见 [Pi 指南](docs/pi.md)，具体范围与结果见 [Pi 支持矩阵](docs/acceptance/pi-support-matrix.md)和 [spec 完成报告](docs/acceptance/pi-spec-closure-20260924/README.md)。

下方新手流程面向 DSH；其中 Codex/Cursor 订阅指 DSH 内的认证/provider 接入。Pi 使用独立配方和实例登录。

OMP管理器集成见[OMP指南](docs/omp.md)和[支持状态](docs/omp-support.md)：固定v18.3.0 standalone，每个配方使用新HOME和独立原生profile，登录重新建立。`omp-default`是日常bootstrap配方；九行虚构验收配方仅在临时验收仓库登记。Linux x64 无账号真实 smoke 已通过；其他平台及真实账号验证已转入[独立遗留](docs/follow-ups/omp-platform-and-live-validation.md)，不属于当前已完成的 OMP spec。

终端与代理的公开配置由独立入口 [`./termcfg`](docs/termcfg.md) 管理：按组件预览、备份并复制 zsh/tmux/mihomo 文件；core/插件下载和代理服务动作均需显式命令。私人配置、恢复及隔离验证状态见指南。

日常复刻本机 kernel 配置请使用 [`omp-kernel`](docs/omp-kernel.md)：包含模型、审批策略、主题、原生子代理和完整技能；另附 WSL 配置步骤。`omp-default` 仅作空白 bootstrap 模板。

**第一次使用请从 [新手使用教程](docs/getting-started.md) 开始。** 教程按实际操作顺序说明准备环境、创建本机文件、安装、部署、登录、日常启动和备份恢复，并解释命令输出。仅使用 Codex/Cursor 订阅时，可以先保留空的 `[secrets]`，不需要照抄下面的私有网关示例。

已有首版安装的用户请先看 [升级与故障修复说明](docs/operations.md#审查修复后的升级)。本地文件现在会严格检查权限和链接；旧运行包没有文件收据时，退出 DSH 后执行一次 `sync` 重建即可，账号 home 保持不变。

记住三个动作即可：`sync` 安装软件，`apply` 部署配置，`run` 启动 DSH。第一次需要依次执行；之后通常只需 `run`。命令中的 `workstation` 是本机配置名称，`dsh-default` 是配置配方名称；可先原样使用。

## 准备环境

- 管理器：Python 3.11+、uv。运行一次 `uv sync --locked` 后，入口直接调用仓库 `.venv`，离线命令不安装依赖。
- DSH 工具链：**Node 24.14.0、npm 11.19.1**。使用自己的版本管理器准备它们；`sync` 和 `run` 会检查所需版本。Node 24.1 虽满足部分上游宽泛声明，但无法执行该版本使用的 `import.meta.main` 入口，已在实际检查中排除。
- 首版平台：Linux、macOS；原生 Windows 不支持。Linux 已进行隔离验证，macOS 验收状态见 [验收记录](docs/acceptance.md)。

## 从 clone 到运行

```sh
git clone <你的仓库地址> rotom
cd rotom
uv sync --locked
./agentcfg profiles
./agentcfg init-local

./agentcfg setup
./agentcfg run --cwd /path/to/worktree
```

默认配方选择 Codex/Cursor 订阅入口，没有虚构的 OAuth endpoint 或 model ID，也不要求 DeepSeek key。`setup` 先预览，再同步锁定依赖（缺失时可能联网）并部署；阶段进度和失败位置显示在标准错误。在原生 TUI 登录后才能实际调用模型。新增私有 API-key 模型可用 `model add`；其他自定义配置可编辑私人 TOML。

三家官方直连预设可用 `./agentcfg model presets` 查看容量、能力、计价和双协议地址；填入 key 后用 `./agentcfg model enable deepseek|kimi|glm` 为当前 profile 启用。`model status` 列出当前 profile 已选模型和 key 状态，包括 profile 自带的模型。缺少模型 key 不阻止工具启动，但对应模型及依赖它的 fallback 在填写 key 前无法调用；未启用的预设也不影响启动。详见[本地配置](docs/local-config.md)。

公共选择器位于子命令前：`--machine NAME` 或 `--local PATH` 二选一，`--profile ID` 可选。缺省机器为 `default`，缺省 profile 来自本地文件，随后回落到 `dsh-default`。`init-local` 默认创建 `default` 机器；也可用 `init-local --machine NAME --profile ID` 指定名称和配方。重复执行不会覆盖文件。

## 本地文件

下面是 **框架 TOML，不是原生 DSH 配置**。地址和模型是虚构示例；使用私有 API 时替换为服务实际支持的值，密钥由用户手工填写。

```toml
schema_version = 1
[machine]
id = "workstation"
default_profile = "dsh-default"
editor = "nvim"

[overrides.providers.private_gateway]
protocol = "openai-compatible"
base_url = "https://gateway.example.invalid/v1"
auth_kind = "api-key"
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

文件为 0600，私人目录为 0700。对象递归合并，数组整体替换；空数组和 `false` 有效。未知字段、无效引用和认证拥有者冲突会失败。更多字段、机器路径、环境变量和多 profile 说明见 [本地配置参考](docs/local-config.md)；`examples/` 是明确标为虚构数据的格式例子，不能当作可调用服务。

## 命令与副作用

| 命令 | 行为 |
|---|---|
| `profiles` | 列出可选 profile 和所属工具，无需本地配置 |
| `init-local [--machine NAME] [--profile ID]` | 创建空密钥本地文件，不覆盖 |
| `setup` | 脱敏预览后同步锁定依赖并部署；有冲突、漂移或待恢复事务时停止 |
| `validate` | 离线校验 schema、引用、适配与完整锁 |
| `render` | 离线生成，只写私人缓存；字段意图不是整份原生 settings |
| `plan` | 离线显示脱敏差异和定位编号；私人缓存保存具体字段定位，不写目标 |
| `lock --agent dsh` | 显式联网解析完整依赖；升级时审查锁与 vendor 差异 |
| `sync` | 消费现有锁并暂存安装或修复损坏包，不更新锁、不启动、不登录 |
| `apply` | 离线重新计划、备份并部署，不安装依赖 |
| `run [dsh] --cwd PATH` | 启动当前部署；可由 profile 推断工具，不隐式 sync/apply |
| `usage <原生参数>` | 无前置选择器时透传PATH上的OMP usage，不读local；显式OMP `--profile`使用已部署受管身份，见[两模式说明](docs/omp-usage.md) |
| `doctor` / `doctor --live` | 默认离线诊断；live 才做声明的服务可达性检查，不自动登录或调用模型 |
| `model add` | 交互新增私有 API-key provider、model 和角色绑定，确认后原子写入私人机器文件 |
| `model presets` | 无需机器文件即可查看三家官方直连预设、容量、能力、价格及来源 |
| `model status` | 查看当前 profile 已选 provider、模型、角色和 key 是否已填写，不显示 key 值 |
| `model enable deepseek\|kimi\|glm` | 填写隐藏 API key 后为当前 profile 启用公共预设；未启用的预设不影响启动 |
| `doctor --input` | 所有工具均报告诊断终端与离线交互就绪状态；OMP 另汇总结构化阻塞事件，不记录按键 |
| `capture` | 捕获预览、支持的主题和已声明模型选择，生成合法本地提案，不导出认证数据 |
| `rollback` | 恢复上一版受管配置；成功后消费该备份 |
| `project init openspec --path PATH` | 使用锁定 CLI 仅初始化指定项目，预检查冲突 |

可选原生参数通过 `run dsh --cwd PATH -- <原生参数>` 传递，`--` 是分界，不会传给 DSH。退出码：0 成功，2 参数/配置/锁错误，3 必需的 MCP/服务密钥缺失，4 冲突/活动锁/恢复待处理，5 依赖或原生检查失败，6 IO/内部失败；模型 API key 缺失只提示，成功启动后保留原生进程退出结果。

## 备份和运行状态

默认实例为 `~/.local/share/agentcfg/instances/dsh/<profile>/`；其 `dsh-home` 和隔离的 `user-home` 保持固定。状态/备份在 XDG state，生成物在 XDG cache。不会默认接管 `~/.dsh`、Pi 或其他工具的账号目录。

成功应用 A→B 后保留 A；再成功应用 C 后仅保留 B。无变化或失败操作不轮换备份。多文件写入有临时恢复记录，单文件原子替换；恢复会再次检查冲突。备份只包含受管文件/字段，不包含 OAuth、会话、整个混合 settings 或本地密钥文件。软件降级和数据库迁移不属于配置 rollback 保证。

运行中的受管实例阻止 apply/sync/rollback；管理器不杀用户进程。绕过管理器直接启动或修改文件的外部进程不受活动锁完全约束，写前复查仍执行。只读可信仓库可以位于共享挂载祖先下，但私人部署目录继续要求安全祖先、属主和权限。

## 认证、项目集成与维护

- [DSH 认证、参数与已核实限制](docs/dsh.md)：Codex 原生配套 `/auth login openai-codex`；Cursor 社区包增加 `/cursor-login`，账号由原生插件保管。
- [OpenSpec 项目操作](docs/openspec.md)：采用上游 `agents` 集成，属于自定义 DSH 接入；初始化 Git 工作树根目录，不自动修改所有业务仓库。
- [日常维护与新增共享资料](docs/operations.md)：包含规则、技能、provider/model 的例子。
- `maintain-agent-config` 技能随默认 profile 分发，指导 Agent 编写合法本地 TOML、修改模板和校验生成结果；部署仍走管理器的备份/冲突流程。
- [增加第二个工具](docs/adapters.md)：接口、所有权、原生编解码和验收边界。
- [OMP配置](docs/omp.md)、[Profile](docs/omp-profiles.md)、[迁入](docs/omp-migration.md)、[依赖](docs/omp-dependencies.md)和[Usage](docs/omp-usage.md)：资源映射、新身份、只读提案和固定运行包。

## 测试

```sh
.venv/bin/python -m pytest -q
```

默认测试使用临时 HOME/DSH_HOME/XDG、网络阻断及假进程，不运行第三方宿主。原生无账号 smoke 是独立显式步骤，真实模型调用另需用户授权和登录态。测试数量、实际运行环境、未运行平台及 live 状态以 [验收记录](docs/acceptance.md) 为准。

DSH/TUI/插件/OpenSpec 的完整 npm 锁及 vendor 补丁在 `locks/dsh/`。TUI 的 bundled 清单修复保持运行代码不变；Cursor 的补丁关闭自动账号导入、后台更新和运行包 stamp，并提供终端登录入口。来源与修改记录见 [上游核实记录](docs/upstream-verification.md)。不安装 Superpowers；ModSearch、Memento、ModLens、MCPLens 不在默认安装清单中。
