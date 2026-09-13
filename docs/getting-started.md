# 第一次使用 agentcfg

本教程从打开终端开始。`agentcfg` 负责准备软件和同步配置，实际与你对话、操作项目的是 DSH。当前只有 DSH 适配器；Codex 和 Cursor 订阅可以作为 DSH 的模型来源。

下面用 `workstation` 作为这台机器的配置名称。你可以原样使用；如果改成 `macbook` 等名称，后续所有命令也要一起替换。`dsh-default` 是仓库提供的配方，可以先保留。

## 1. 打开仓库并检查环境

已经有这个仓库就进入它，无需再次 clone。在当前开发机器上：

```sh
cd /data/1/weixiaoxian.wxx/dev_tool/rotom
```

另一台机器需要先取得包含实现代码的仓库版本，再进入自己的 `rotom` 目录。仅提交到本地 Git 的内容不会自动出现在 GitHub，换机器之前需要由你决定何时推送。

在终端检查：

```sh
uv --version
node --version
npm --version
```

管理器需要 Python 3.11+ 和 uv；当前 DSH 锁要求 **Node 24.14.0、npm 11.19.1**。Node 应输出 `v24.14.0`，npm 应输出 `11.19.1`。如命令不存在或版本不符，先使用你已有的工具链管理方式准备这些版本，再继续安装。`agentcfg sync` 不负责安装 Node/npm，也不会自动改你的全局版本。

准备本仓库的 Python 环境：

```sh
uv sync --locked
./agentcfg --help
```

`uv sync` 可能联网下载依赖。成功后 `--help` 应列出 validate、plan、sync、apply、run 等命令。以后无需手动激活 `.venv`，也不用把命令改成 `uv run`。

## 2. 创建这台机器的配置

```sh
./agentcfg init-local --machine workstation
nvim "${XDG_CONFIG_HOME:-$HOME/.config}/agentcfg/machines/workstation.toml"
```

初始化成功时会提示已创建本地配置。文件已存在则不会覆盖，直接打开原文件编辑即可。没有 nvim 时用自己熟悉的文本编辑器。

**只使用 Codex/Cursor 订阅时，文件可以保持如下内容。** `editor` 是可选项；新增时要放在 `[machine]` 内、`[secrets]` 前。

```toml
# agentcfg 框架格式，不是 DSH 原生配置。
schema_version = 1

[machine]
id = "workstation"
default_profile = "dsh-default"
editor = "nvim"

[secrets]
```

订阅登录稍后在 DSH 内完成，空 `[secrets]` 不影响生成和部署。无需填写 DeepSeek key，也不要把 Codex 订阅登录信息当作 OpenAI API key 填在这里。

如果使用百炼或私有 API，按 [本地配置参考](local-config.md#私有网关示例) 添加 provider、model、选择列表和密钥；地址和模型 ID 必须来自你的服务。示例中的 `example.invalid` 和 `fictional-*` 是虚构数据，不能直接调用。已有文件只修改需要的表，不要整份覆盖。

机器文件保存在仓库外，初始化权限是 0600；不要提交到 Git。它可以包含 API key，也可以包含这台机器独有的路径和模型。所有字段说明见 [本地配置参考](local-config.md)。

## 3. 检查、安装和部署

在仓库目录依次执行；某一步失败时，先解决它，再继续下一步：

```sh
./agentcfg --machine workstation validate
./agentcfg --machine workstation plan
./agentcfg --machine workstation sync
./agentcfg --machine workstation apply
./agentcfg --machine workstation doctor
```

| 操作 | 做什么 | 怎样理解结果 |
|---|---|---|
| `validate` | 离线检查配置和依赖锁 | `"valid": true` 表示校验通过；不会验证账号是否已登录 |
| `plan` | 预览将改哪些配置，不写入实例 | 首次 `changes` 大于 0 正常；`conflicts` 应为 0；`sync-required` 表示尚需安装依赖 |
| `sync` | 按已有锁安装 DSH、插件和 OpenSpec，可能联网 | 完成后依赖可用；不会登录或启动 DSH |
| `apply` | 将配置部署到独立实例，并保留上一版受管内容 | 会重新检查冲突；你执行该命令就表示应用本次配置 |
| `doctor` | 离线检查部署、依赖和备份状态 | 正常部署应有 `deployed: true`、`dependencies: "installed"`、`recovery_pending: false` |

命令当前输出 JSON，一行可能较长。关注上表字段即可。`authentication: "not-inspected; use native auth status"` 表示管理器没有查看账号数据，不是登录失败。检查命令之后可以单独执行 `echo $?`；`0` 表示该命令成功。

首次使用不需要执行 `lock`，仓库已经带有依赖锁；`lock` 用于开发维护或明确升级版本。也不必单独执行 `render`，`plan/apply` 会计算需要的产物。

## 4. 启动 DSH 并登录

将下面路径换成你希望 Agent 操作的项目目录，路径有空格时保留引号：

```sh
./agentcfg --machine workstation run dsh --cwd "/你的项目绝对路径"
```

该路径必须存在。`--cwd` 决定 DSH 操作哪个项目；不要为了方便填 rotom 路径，除非你确实要维护 rotom。日常启动仍用这条命令，无需每次 sync/apply。

**下面是输入到 DSH 对话输入框的命令，不是在系统 Shell 执行：**

使用 Codex 订阅：

```text
/auth status
/auth login openai-codex
```

按登录提示操作，然后输入 `/model` 选择该 provider 的模型。

使用 Cursor 订阅：

```text
/cursor-login
```

打开它返回的登录 URL。完成授权后，在同一个 DSH 实例中用 `/model` 查看并选择 `oauth-cursor` 的模型。取消等待中的授权可输入 `/cursor-login cancel`。Cursor 是社区接入，详细说明见 [DSH 认证](dsh.md)。SSH 场景按登录入口实际提示操作，不需要另外启动一个 DSH Web 实例。

登录入口和插件加载已做无账号验证；真实登录及模型调用还没有完成账号实测。如果模型不可见或请求失败，应按 [live 验收说明](live-acceptance.md) 检查，不能根据 `doctor` 成功推断订阅调用成功。

要退出时使用 DSH 的退出操作，确认终端回到 Shell 后再部署新配置。管理器会阻止修改它启动的活动实例，不会自动结束你的会话。

## 5. 修改配置和恢复上一版

修改这台机器的偏好，编辑第 2 步的本地 TOML；修改多台机器共用的规则、技能或模板，编辑 rotom 仓库里的对应文件。退出正在运行的 DSH 后执行：

```sh
./agentcfg --machine workstation validate
./agentcfg --machine workstation plan
./agentcfg --machine workstation apply
```

规则、技能、模板怎么添加，以及怎样让 Agent 使用 `maintain-agent-config` 维护技能，见 [日常维护](operations.md)。数组是整体替换：例如只写一个 skill，就只选择这一个；希望保留已有技能时需写完整列表。

发现刚部署的配置有问题，可以恢复上一版：

```sh
./agentcfg --machine workstation rollback
./agentcfg --machine workstation doctor
```

只保留一个备份：A 改为 B 后备份 A；再成功改为 C 后备份 B。没有变化或部署失败不会轮换。恢复成功后该备份被消费，不能反复向更早版本回退。

**恢复的是已部署的受管配置，不会改回 Git 源文件或本地 TOML。** 恢复后需要在来源中修正刚才的问题，否则再次 apply 会重新部署那些错误设置。账号、会话、软件版本和含密钥的机器文件都不属于这份备份。

如提示冲突，先保留现场，用 `plan` 和 `doctor` 查看受影响项；不要删除备份或整个 DSH home 来解决。首次部署前存在的非空同名文件不会被自动接管。

## 6. 给一个项目启用 OpenSpec（可选）

只在你确实希望该项目使用 OpenSpec 时执行。Git 项目应传工作树根目录：

```sh
./agentcfg --machine workstation project init openspec --path "/你的项目绝对路径"
./agentcfg --machine workstation run dsh --cwd "/你的项目绝对路径"
```

前提是 sync 已完成。命令会在这个项目生成 OpenSpec 配置和 `.agents/skills/openspec-*` 等文件；其他项目不受影响。相同内容重复初始化不重写，已被修改的同名产物会报冲突。详细说明见 [OpenSpec 项目操作](openspec.md)。

## 遇到问题先看这里

| 提示或现象 | 下一步 |
|---|---|
| 找不到 `./agentcfg` | 进入 rotom 仓库目录；从其他目录调用时使用入口的绝对路径 |
| 虚拟环境缺失 | 在仓库执行 `uv sync --locked` |
| 机器文件不存在 | 检查 `--machine` 名称是否与初始化一致；初始化后不要漏写它，否则默认找 `default` |
| Node/npm 版本不符 | 在当前终端选用第 1 步列出的精确版本 |
| 配置或引用错误，退出码 2 | 根据报错字段检查 TOML，对照本地配置参考；不要把 DSH 原生 YAML 填进去 |
| 所需凭据缺失，退出码 3 | 在所选机器文件的 `[secrets]` 填写对应 API key；订阅账号走 DSH 内登录 |
| 冲突、活动实例或恢复待处理，退出码 4 | 先退出 DSH，查看 plan/doctor；保留冲突文件，按日常维护文档处理 |
| 缺运行包或依赖安装失败，退出码 5 | 检查工具链及安装网络，重新执行 sync；不要自行改锁绕过 |
| Cursor 代理端口占用 | 退出重复实例；确需多实例时按 DSH 文档配置不同 `cursor_port` |

需要协助时提供失败的命令名称、退出码和脱敏报错即可。不要粘贴整个机器文件、环境变量列表或 OAuth 文件。
