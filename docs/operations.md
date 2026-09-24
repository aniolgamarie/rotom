# 日常维护

第一次使用先读 [新手使用教程](getting-started.md)。本文用于已经完成安装后的配置修改。

## 请 Agent 帮忙维护

默认 DSH 配方已包含 `maintain-agent-config` 技能。可以在 DSH 中这样描述任务：

> 使用 maintain-agent-config 技能，帮我修改这台机器的配置：终端图片预览保持关闭，编辑器使用 nvim。保留其他配置和密钥，执行 validate 和 plan，解释改动。

也可以要求增加共享规则或完整技能包，说明适用范围是“所有机器”还是“只在这台机器”。技能会指导 Agent 定位来源、编写合法 TOML 和校验结果。DSH 运行期间不能部署它自己的活动实例；退出后在终端执行 `apply`，再启动查看效果。不要把密钥粘贴到对话中。

## 修改配置

编辑 Git 中的公共来源或仓库外的本地覆盖，然后：

```sh
./agentcfg --machine workstation validate
./agentcfg --machine workstation plan
./agentcfg --machine workstation apply
```

只有依赖变化才需要显式 lock/sync。配置生成不安装软件，依赖安装不启动 Agent。共享规则不能消除工具内置系统提示差异。

当前锁的 sync 接受 Node 24.2.0 起的 24.x 和 npm 11.x，run 使用相同 Node 下限；lock 仍要求精确 Node 24.14.0 / npm 11.19.1。Node 24.1.0 无法执行所用入口，需先切换版本。版本选择与原生验证范围见 [准备工具链](getting-started.md)。

## 添加共享 rule

新建 `shared/rules/project-style.md`，写普通 Markdown。文件里的 `{{example}}` 保持原文，不会当 Jinja 求值。在 `shared/content.toml` 登记：

```toml
[rules.project-style]
path = "shared/rules/project-style.md"
```

在 profile 的 rules 数组中按需要选择。数组整体替换，想保留原有三条就写完整顺序：

```toml
rules = ["chinese", "terminal", "cpp-local-search", "project-style"]
```

仅明确 `template = true` 的文本使用 StrictUndefined 模板；结构化 JSON/YAML 使用序列化器。

## 添加完整 skill

在 `shared/skills/build-context/` 放入真正的 SKILL.md 以及需要的 scripts/references/assets，维护相对引用，脚本用 `chmod +x` 保留执行意图。frontmatter 至少提供合法 name 和 description；记录原创来源或上游 URL/版本及定制说明。

```toml
[skills.build-context]
path = "shared/skills/build-context"
```

profile 的 skills 数组选择完整包。复制不执行脚本，不跟随源符号链接。DSH 专属包要替换同名共享包时，在 `agents/dsh/content.toml` 使用明确的旧路径：

```toml
[skills.build-context]
path = "agents/dsh/skills/build-context"
override = "shared/skills/build-context"
```

未声明覆盖、旧来源不符或重复覆盖都失败，不会静默替换。

## 添加 provider/model

公共 provider/model 可在 shared registry 登记，私有项使用本地 overrides，字段相同。以下是虚构的框架格式：

```toml
# shared/providers.toml 中的实体
[providers.team_gateway]
protocol = "openai-compatible"
base_url = "https://api.example.invalid/v1"
auth_kind = "api-key"
credential_ref = "secret:team_gateway_key"
```

```toml
# shared/models.toml 中的实体
[models.team_chat]
provider = "team_gateway"
remote_id = "fictional-chat"
input = ["text"]
```

替换为已核实的服务值，并在 profile 选择 provider/model、将 roles.main 指向逻辑模型 ID。未知 context_window/max_output_tokens 不填。实际 key 只由用户填写本地 secrets；不要把 OpenAI API key 当作 Codex 订阅登录。

## 原生 UI 改动与 capture

```sh
./agentcfg --machine workstation capture
```

当前 allowlist 捕获原生 `dsh-tui.terminalImages`、隔离 user-home 中 `.dsh-tui/theme.json` 的主题及 `model.json` 的模型选择，生成缓存中的 `capture.json` 覆盖提案。主题允许 `rotom-poimandres`、`auto`、`dark`、`dark-ansi`、`light`。模型必须唯一对应当前 profile 已声明且选中的逻辑模型；未知动态模型或未支持主题会明确报错，原有提案保留。

提案经过 schema 和完整合并/适配/渲染校验。它是局部提案，不是完整机器文件，也不是可直接复制的 DSH YAML。审阅后将相关非秘密字段局部合并进本地 TOML，再 validate/plan/apply。不会捕获 auth、会话或动态 OAuth 模型目录，不自动修改 Git。原生保存的偏好只是待采纳的 UI 选择，部署配置及环境变量仍可能覆盖其运行效果。

## 冲突和凭据定位

plan 的每个差异、漂移和冲突会带 `target-…` 编号。输出中的 `diagnostics` 指向私人缓存的 `locations.json`；用本地编辑器打开，按相同编号查找具体产物路径和字段 selector。文件不保存字段值，但路径可能包含私有模型名称，不要公开整份文件。

缺密钥报错带 `credential-…` 编号。执行同一机器/profile 的 doctor，再在其 `diagnostics` 文件查对应 `secret:` 引用，然后只填写本地 `[secrets]` 中那一项。定位信息包含当前来源和已部署契约引用，因此未 apply 的改选不会让你找错实际启动所需的 key。文件中不含密钥值，也不读取 OAuth。

## 审查修复后的升级

1. 拉取代码后执行 `uv sync --locked`。validate 若报告本地文件权限问题，检查你选择的文件是普通文件、属主为当前用户、无符号链接；用户自行用 `chmod 600 /本地文件路径` 和 `chmod 700 /其私人父目录` 修正。不要对整个 HOME 或系统目录执行 chmod；管理器不会自动放宽或修改权限。
2. 退出当前 DSH，执行 `sync`。旧运行包缺少文件收据会被识别为 `damaged`，sync 按相同依赖锁暂存重建，保留固定账号 home。无需执行 lock，也没有升级模型依赖版本。
3. 执行 `plan`、`apply`、`doctor`，再启动。doctor 的 `dependencies` 对应当前仓库锁，`deployed_dependencies` 对应实际部署的版本；回滚后两者可能不同。

运行文件缺失或关键入口摘要不符时，doctor 报 `damaged`，run 拒绝启动，sync 可修复有管理器所有权标记的包。没有所有权标记的非空目录不会被自动接管。检查覆盖安装清单和必要入口，不是对全部传递依赖每个文件的安全审计。

每次检查都会重新核验完整目录形状、链接目标、各包 package.json 和必要入口。不使用磁盘 marker 或进程内元数据缓存跳过正文校验：同长度修改可能保留相同文件时间戳，元数据相同不足以证明内容未变。

修复先暂存安装，成功后替换旧包；中断后重新 sync 会处理 `.repair-<锁身份>` 恢复槽。该槽属于包修复，不是配置上一版备份，不包含账号和会话。若配置 pending 尚未解决，sync 会在安装前拒绝；先按 doctor 提示执行 apply/rollback 恢复。

## 备份、漂移与恢复

三方比较基线 B、当前 C、期望 D：C=B 时更新；D=B 时保留原生变化并报告漂移；C=D 不重写；双方都改且不同则冲突。保留的漂移不自动变成新基线。

每次真正变更成功后只保留上一版受管内容。重复 apply 无变化不轮换备份；失败时先恢复已写的受管项，遇到后续修改则保留 pending 记录并阻止继续操作。解决冲突后重试 apply/rollback，doctor 可报告恢复待处理。

```sh
./agentcfg --machine workstation rollback
```

成功恢复后消费备份，下一次成功 apply 再建立新的上一版。首次部署的恢复只移除本次新增且未漂移的受管文件，不删除后来新增的会话或未知文件。配置 rollback 不恢复旧软件/数据库，旧锁对应运行包缺失时需要单独准备依赖。

运行中的实例会阻止修改配置或依赖，退出后重试。不要关闭路径检查、复制整个 home 或直接改运行包来绕过冲突。

## 升级依赖

1. 核实目标提交、原生字段和实际打包布局，更新适配器/模板与 `agents/dsh/dependencies.json`、plugins.toml、lock-policy.json。lock-policy 保存工具链、包输入、完整源码 SHA 和平台支持；更换包版本时必须重新核实来源，不能只沿用旧 SHA。
2. 需要 vendor 修复时用 scripts 中的构建器重新生成，审阅 diff、源码 SHA、归档 integrity。不可只改文件名或版本标签。
3. 执行 `lock --agent dsh`；它在新临时目录解析完整锁，不使用浮动 main 或无版本 npx。
4. 运行默认测试和独立无账号 smoke；检查 Node/npm 和各平台证据，再 sync/apply。

Memento、ModLens、MCPLens 和 ModSearch 均不在默认安装中。新增插件必须有实际适配和验证；未实现映射时明确失败，不通过收录清单假装支持。

## Pi 实例维护

Pi 的来源采用、原生字段漂移、凭据引用轮换、配置回滚及活动恢复见
[Pi 迁移与维护](pi-migration.md)。Task Keeper 本机绑定示例见
[pi-managed.toml](../examples/pi-managed.toml)。

默认项目策略保持拒绝。需要受管候选写入时，在私人机器配置中显式选择
`permissions.policy_ref = "task-keeper-candidate"`；此策略只开放 tk_* 读取及 write，
不能跳过角色根、task grant、秘密路径或 supervisor 写租约检查。

Pi 候选 `9d6a9270` 的完整依赖锁、Linux x86_64 四配方原生与双路径冷重建已通过验收；当前软件 spec 已完成。其他平台和真实账号/服务验证见[独立后续清单](follow-ups/pi-platform-and-live-validation.md)，本节不扩大到未经验证的平台或服务。

### Pi 普通文件工具

普通 read/write/edit/rename/ls/find/grep 通过实例监督者处理；写入和重命名在实际动作前取得公共工作区租约。
交互批准绑定当前会话、目录和输入；未使用的操作授权五分钟后到期。重命名必须同时允许源、目标，且不覆盖现有目标。
Linux 使用内核 `renameat2(RENAME_NOREPLACE)`，macOS 使用 `renameatx_np(RENAME_EXCL)`；不支持的平台或文件系统明确失败。
接口依据：[Linux 头文件](https://github.com/torvalds/linux/blob/master/include/uapi/linux/fs.h)、[Apple 头文件](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h)。
目录查找只扫描授权路径并排除 Git 元数据和链接；本地 ignore 规则目前支持基础模式，不宣称与完整 Git 忽略规则完全一致。

普通命令和外部 editor 还须绑定精确命令。例如在机器覆盖的 `agent_options.external_tools.build` 中声明
`executable`、`version`、固定 `args`、`project_root`、`read_roots`、`write_roots` 和 `timeout_seconds`。
工具使用 `agentcfg:build` 选择该绑定；当前选中 policy 须另外允许 bash 的 execute/command_ref=build。
原始 shell 片段、附加参数、超出配置的超时和只读角色发起命令均被拒绝。默认 policy 没有自动放开命令。
这些前台命令使用私人临时目录和无网络沙箱；项目读写根与秘密拒绝投影到实际命名空间。
原生沙箱执行和交互式 editor 行为仍需要独立平台验证。

会话切换、fork、reload、handoff 在还有保护中的子执行或尚未消费的受控结果时拒绝。
请先查看结果或通过显式取消/恢复流程证明执行已终止，再切换会话；不会通过清空 UI 解除工作区保护。

`agent_options.ui.notifications` 可选择 `auto`、`osc99`、`osc777`、`bell` 或 `off`。
自动模式对 Kitty 使用 OSC 99，对 Windows Terminal 使用终端铃声，其他终端使用 OSC 777；不再启动脱离监督的 PowerShell toast。
终端协议是否实际呈现通知属于独立终端验收，发送字节不代表已收到桌面通知。
