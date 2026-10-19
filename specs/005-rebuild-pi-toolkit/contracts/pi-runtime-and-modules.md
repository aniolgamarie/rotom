# Contract: Pi 1.3 资源、启动与模块

适用：FR-004–011、FR-015–017、FR-027–031。版本与准入理由见 [research](../research.md)。
这是未来 adapter/backend 的公开契约设计，不是可直接部署的当前配置。

## 1. 两档与配置形状

公共 TOML `schema_version=1` 和既有 providers/models/rules/skills/plugins/mcp/roles 保持不变。
新增配方 `pi-base`、`pi-pro`，均引用同一宿主、主题和公共资源来源；不同锁身份绑定各自最终选择。
不以 Cursor/模型/服务组合创建新的公开产品档位。

重建 `agents/pi/schemas/options.schema.json` 时只声明以下 Pi 专属域；域内字段逐项固定，
未知字段拒绝，不能保留旧 task_keeper/model_delegate/permissions 对象兼容新运行路径。

| 域 | 新语义 | 对应原生/适配职责 |
| --- | --- | --- |
| runtime | engine 固定 node | 已验证运行时与官方 CLI 入口，不嵌入 SDK 主循环 |
| resources | 显式选中 prompts/themes/skills/extensions 的来源引用 | 由 sync 准备的本地固定资源；不接受任意远程加载声明 |
| discovery | project_resources 固定 false，指项目可执行/可加载资源；外部资源须登记 | `--no-approve` 与各类发现关闭参数；不包含 AGENTS.md 上下文发现 |
| ui | 初始主题与终端偏好，受管策略逐项声明 | 初始 `catppuccin-mocha` 可由合法机器覆盖改选同一来源的 flavor |
| settings | 固定 Pi 1.3 原生设置的已校验子集 | 严格字段映射；不是任意 settings.json 透传 |
| collaboration | enabled 初始 false；true 需准入组合 | 未满足强制边界时拒绝启用，不加载候选包 |

以上表格定义 schema 重建边界，不承诺当前旧 adapter 已接受这些新域。
公共 profile 的 skills 选择不另复制到 resources.skills；其他重叠选择也必须有单一来源。
`project_resources=false` 不表示关闭项目上下文；主会话保留原生上下文发现，
调查子任务是否使用 `--no-context-files` 必须按其明确范围单独选择并验证。
机器覆盖只能选已登记来源与合法字段，不能更改宿主身份、安装来源或所有权边界。
插件设置只有所选精确版本通过准入时才增加其真实 schema；禁用的命名空间不被默默保留生效。

## 2. 原生配置基线

配置基线对应[官方固定 settings/schema](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/schemas/settings.schema.json)。
下表为新配方建议，不是参数性能已经验证。每项须分别定义 selector/初始化策略。

| 原生字段 | 初始值 | 归属与依据 |
| --- | --- | --- |
| defaultThinkingLevel | medium | 可被精确模型绑定覆盖，不要求所有任务最高强度 |
| steeringMode / followUpMode | one-at-a-time | 逐条协作偏好，不复制旧 queueMode |
| compaction.enabled | true | 原生压缩，旧压缩插件退出 |
| compaction.reserveTokens / keepRecentTokens | 16384 / 20000 | 初始沿用上游；后续按模型验证，不盲目放大 |
| retry.enabled / maxRetries | true / 3 | 有界 provider 瞬态重试，不授权工具副作用重放 |
| retry.provider.maxRetries | 0 | 避免嵌套 provider 重试层 |
| codemode.mode / inlineBudget | on / 3000 | 仅在选中相应 builtin 时生效，不默认 only 隐藏全部工具 |
| quietStartup | header | 日常偏好；首次验收使用 --verbose |
| tuiMode | fullscreen | 1.3 基线；regular 作为 SSH/tmux 对照回退，未实测不声称更好 |
| editorPaddingX / outputPad / autocompleteMaxVisible | 0 / 1 / 5 | 必须测试中文、窄屏、粘贴和重绘 |
| terminal.hyperlinks / images / trueColor | auto | 机器必要时覆盖，不固定个人终端协议 |
| cacheWarming | streaming | 上游起点；off/idle 比较费用与延迟后再改，idle 不等于免费 |
| theme | catppuccin-mocha | 静态包 0.1.6 已核实真实 name，来自 ui 的单一选择 |

provider/modelID、enabledModels、modelOverrides、外部 editor 路径按机器绑定生成；
不为公共配方预置真实账号或虚构可运行模型。旧 deprecated 字段不搬迁为新默认。
UI 偏好优先只初始化，必须纳入公共所有权策略；持续强制管理需要显式声明。

## 3. 依赖和资源形状

选中 npm 宿主与主题后，由 Pi backend 生成完整锁、资源清单及校验后的本地安装目录。
目录具体布局沿用公共实例与 backend 规则，不能拼接 starter 或本机绝对路径。
需要保留完整 Skill 包、主题 JSON、提示支持文件、许可证和来源清单；复制不执行脚本。

沿用内部锁生成身份 `recipe_digest`，不新增公共配置键；其输入仅为规范化的固定宿主/模块
声明、当前 profile 的依赖选择投影、被选资源的清单/内容身份、必要构建与工具链条件。
不纳入全体 `src/agentcfg/*.py`、其他 profile 或退役资源，也不纳入自身、由其生成的完整锁
或 closure_digest；完整闭包由完整锁、closure_digest 与 integrity 独立证明。
实际依赖输入变化必须明确报锁失配（exit 2）并要求显式重锁，render/apply/run 不得隐式重锁；
不相关旧链删除不得使新锁失效。候选源码身份仍须记录于验收证据，后端语义变化即使摘要不变
也须审查并重验受影响行为。

运行时有效资源由已部署契约生成，每项含类型、来源身份、内容身份、顺序与唯一所有者。
`settings.json.packages` 不写远程 npm/git 声明；优先完全不依赖 package 自动发现，
而从已锁本地入口显式加载。原生新增的未受管字段继续保留，危险加载漂移由启动 preflight 拒绝，
不能为了通过检查自动删除用户内容。

## 4. 公开 CLI 启动契约

来源为[Pi v1.3 CLI](https://github.com/earendil-works/pi/blob/v1.3.0/packages/coding-agent/docs/cli.md)。
以下是 argv 元素及生成规则，不是本轮执行命令；路径值由安全的已部署身份解析，不用 shell 拼串。

```text
<locked-official-pi-entry>
--session-dir <instance-session-root>
--no-approve
--no-extensions --no-skills --no-prompt-templates --no-themes
[--skill <locked-skill-path>]...
[--prompt-template <locked-template-path>]...
[--theme <locked-theme-json>]...
--use-theme <validated-theme-name>
[-e builtin:mcp] [-e builtin:codemode] [-e builtin:tool-search]
[-e <admitted-local-extension-entry>]...
```

- 设置 `PI_CODING_AGENT_DIR` 与 `PI_CODING_AGENT_SESSION_DIR` 为稳定实例位置，并显式
  `--session-dir` 防止项目 sessionDir 改写归属；不得继承任意外部值覆盖管理器路径。
- Base 默认无外部 MCP；不需要时不加载 builtin:mcp，并使用公开 `--no-mcp` 排除连接。
  若已显式选择 MCP，则加载 builtin:mcp 并去掉 --no-mcp；两者不能混用成矛盾意图。
- Codemode/tool-search 只随明确选择加载。`--no-extensions` 会关闭 builtin，显式 -e 是必要恢复，
  不是额外复制上游扩展代码。
- `--no-approve` 忽略信任门控的项目设置/可执行资源，仍保留原生 AGENTS.md 等上下文发现。
  不承诺恶意上下文隔离；调查子任务需要更窄上下文时另核对 --no-context-files 与显式角色资料。
- 显式 --skill / --prompt-template / --theme 在关闭自动发现后仍可加载，必须逐项与资源清单核对。
- 运行前拒绝未准入远程 package、越界本地入口、选择漂移、锁与部署身份失配；不读取真实
  认证或会话正文做资源盘点。仅检查有关非秘密声明和受管元数据。
- 允许原生登录交互按用户操作执行；doctor 不登录。需模型/服务的实际验收仍有独立授权。
- `--offline` 不是网络隔离，不能用于证明 provider 不被调用；默认测试靠阻网与假进程。

子执行不要求照抄父 argv，但必须证明等效的实例、会话、资源及禁止安装边界。
父子的认证可以属于同一 profile 原生 home，不为形式隔离复制 auth；子结果须有独立归属。

## 5. 按需模块选择

模块不是新常驻运行服务或新的公开配置语言，实际启用由公共 plugins/mcp/skills 选择和
adapter 严格选项表达。配置改变后经过 lock/sync/apply，再在下一次运行加载；不承诺任意热加载。

| 模块 | 首轮状态 | 启用约束 |
| --- | --- | --- |
| 静态主题 | Base/Pro 共用已选候选 | 完整锁、真实 theme ID、许可与原生渲染 |
| 协作委派 | held，默认不选择 | 按协作契约；不能只有提示约定 |
| Powerline | held，不进入锁 | 公开接口修复并重新审包，不以隐藏替代 |
| 文档/搜索/浏览器/web | candidate，默认不选择 | 每类单一所有者、账号/外发边界、固定工具与退出 |
| Cursor | candidate，显式订阅模块 | 非官方桥；使用 `PI_CURSOR_SYSTEM_CREDENTIALS=0` 关闭系统凭据复用 |
| cache-hit-monitor / pi-tool | candidate，各自按需 | 实际资源选择；隐藏 widget 不等于不加载或零成本 |
| AST/语义/会话内进程 | candidate，按项目选择 | 路径/输出/取消/数据归属；不承诺跨重启进程恢复 |

MCP 默认原生接入，不再同时加载 pi-mcp-adapter。stdio 用已安装固定可执行文件与 argv，
不用无版本 npx/uvx；HTTP 服务按机器绑定和所需 SecretRef 注入。
延迟工具暴露不等于延迟服务连接，每个会话可能启动自己的服务；不新建跨会话中转层。

模块启用须展示数据接收方、费用路线、凭据来源、本地 journal/cache 与退出方式；
不自动发送项目代码/内部名称/日志做外部搜索，不接管个人浏览器。
关闭模块停止后续加载和连接，不自动删除历史缓存或终止用户已有进程。

## 6. 必须验证的组合

原生资源首次加载（含 --verbose）、项目/父目录资源哨兵、settings packages 漂移、
显式 sessionDir、继续会话 active tools、无扩展后的 builtin 选择、中文 UI 与 shell 退出、
缺依赖/凭据的错误、禁用模块无加载和连接。纯静态 argv 正确不等于这些组合已通过。
