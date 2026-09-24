# rotom / agentcfg

[English](README.md) | **中文**

个人 Agent 配置管理仓库：公共规则、完整技能包、工具模板和依赖锁进入 Git，机器覆盖与 API key 留在仓库外。通过一个入口生成、检查、部署和启动独立实例；每个实例只保留上一版受管配置备份。

首版实现 **DSH + ccch1mneyyy/dsh-TUI**。Pi 迁移 spec 已按约定范围完成：软件集成、Linux x86_64 四配方 mock/native 验证，以及每配方两个全新 HOME/checkout 路径的冷重建。验收候选为 `9d6a9270`；其他平台与真实账号／服务仍未验证，已转入[独立后续清单](docs/follow-ups/pi-platform-and-live-validation.md)。Pi 中的 Codex 通过 model-delegate 调用官方 CLI，旧 codex-delegate 不作为迁移目标依赖。配置入口见 [Pi 指南](docs/pi.md)，具体范围与结果见 [Pi 支持矩阵](docs/acceptance/pi-support-matrix.md)和 [spec 完成报告](docs/acceptance/pi-spec-closure-20260924/README.md)。

下方新手流程面向 DSH；其中 Codex/Cursor 订阅指 DSH 内的认证/provider 接入。Pi 使用独立配方和实例登录。

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
./agentcfg init-local --machine workstation

# 用编辑器填写 ~/.config/agentcfg/machines/workstation.toml。
# 设置 XDG_CONFIG_HOME 时，文件位于该目录的 agentcfg/machines/ 下。
./agentcfg --machine workstation validate
./agentcfg --machine workstation plan
./agentcfg --machine workstation sync
./agentcfg --machine workstation apply
./agentcfg --machine workstation doctor
./agentcfg --machine workstation run dsh --cwd /path/to/worktree
```

默认配方选择 Codex/Cursor 订阅入口，没有虚构的 OAuth endpoint 或 model ID，也不要求 DeepSeek key。可以先完成 validate/render/sync/apply，再在原生 TUI 登录；实际模型调用仍需要用户账号。

公共选择器位于子命令前：`--machine NAME` 或 `--local PATH` 二选一，`--profile ID` 可选。缺省机器为 `default`，缺省 profile 来自本地文件，随后回落到 `dsh-default`。`init-local --machine NAME` 是保留的初始化形式，重复执行不会覆盖文件。

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
| `init-local --machine NAME` | 创建空密钥本地文件，不覆盖 |
| `validate` | 离线校验 schema、引用、适配与完整锁 |
| `render` | 离线生成，只写私人缓存；字段意图不是整份原生 settings |
| `plan` | 离线显示脱敏差异和定位编号；私人缓存保存具体字段定位，不写目标 |
| `lock --agent dsh` | 显式联网解析完整依赖；升级时审查锁与 vendor 差异 |
| `sync` | 消费现有锁并暂存安装或修复损坏包，不更新锁、不启动、不登录 |
| `apply` | 离线重新计划、备份并部署，不安装依赖 |
| `run dsh --cwd PATH` | 启动当前部署，保持工作目录，按需注入密钥，不隐式 sync/apply |
| `doctor` / `doctor --live` | 默认离线诊断；live 才做声明的服务可达性检查，不自动登录或调用模型 |
| `capture` | 捕获预览、支持的主题和已声明模型选择，生成合法本地提案，不导出认证数据 |
| `rollback` | 恢复上一版受管配置；成功后消费该备份 |
| `project init openspec --path PATH` | 使用锁定 CLI 仅初始化指定项目，预检查冲突 |

可选原生参数通过 `run dsh --cwd PATH -- <原生参数>` 传递，`--` 是分界，不会传给 DSH。退出码：0 成功，2 参数/配置/锁错误，3 所需密钥缺失，4 冲突/活动锁/恢复待处理，5 依赖或原生检查失败，6 IO/内部失败；成功启动后保留原生进程退出结果。

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

## 测试

```sh
.venv/bin/python -m pytest -q
```

默认测试使用临时 HOME/DSH_HOME/XDG、网络阻断及假进程，不运行第三方宿主。原生无账号 smoke 是独立显式步骤，真实模型调用另需用户授权和登录态。测试数量、实际运行环境、未运行平台及 live 状态以 [验收记录](docs/acceptance.md) 为准。

DSH/TUI/插件/OpenSpec 的完整 npm 锁及 vendor 补丁在 `locks/dsh/`。TUI 的 bundled 清单修复保持运行代码不变；Cursor 的补丁关闭自动账号导入、后台更新和运行包 stamp，并提供终端登录入口。来源与修改记录见 [上游核实记录](docs/upstream-verification.md)。不安装 Superpowers；ModSearch、Memento、ModLens、MCPLens 不在默认安装清单中。
