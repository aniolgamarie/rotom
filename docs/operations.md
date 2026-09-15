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
