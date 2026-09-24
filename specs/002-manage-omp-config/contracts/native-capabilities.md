# OMP 原生能力契约

> 验收归属以[范围修订](../scope-change-20260924.md)为准：当前保留软件隔离契约与 Linux x64 无账号原生验收；其他平台实机和真实登录/usage/模型调用转独立遗留。原有产品接口、平台选择实现与安全边界保持要求，转出不等于验证通过。

基线：OMP v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`。固定版本来源索引见 [research.md](../research.md)。以下为实现契约，契约文本本身不作为通过证据；实际结果见验证矩阵。

`A` 表示 `<instance>/user-home/.omp/profiles/<native_name>/agent`，`R` 表示已验证运行包。所有目标必须使用实例相对路径，字段 selector 为 JSON Pointer，字段意图用 JSON 编码、最终文件按对应 JSON/YAML codec 合成。

## 首版能力矩阵

| 能力 | 公共输入与原生映射 | 所有权与最低成功样例 | 必测失败 |
|---|---|---|---|
| 模型/provider | registry providers/models；`openai-compatible → openai-completions`，`openai-responses → openai-responses`；`models.yml#/providers/<id>` 下按叶子管理 baseUrl/api/apiKey/models | 选择一个虚构网关及精确 remote_id，配置被原生识别；真实调用仅在授权阶段 | 未知 protocol、冲突 native ID、含密钥 URL、未声明 model、缺失必要容量字段 |
| 模型角色 | profile.roles 的 main→modelRoles.default，smol→smol，slow→slow，vision→vision，plan→plan，advisor→advisor | `config.yml#/modelRoles/<role>`，选择至少 main+smol 两个已声明模型并验证角色选择 | 未知角色、引用未选模型、vision 非图像模型、模糊 ID |
| 规则 | profile.rules → shared rules 内容，按既有模板许可渲染后汇总 | `A/RULES.md` 文件所有权，验证两个规则都成为原生 always-apply 内容 | 模板未授权、路径越界、来源冲突、任意脚本求值 |
| 完整技能 | profile.skills → 完整技能包 | `A/skills/<id>/` 下逐文件所有权；样例包含 SKILL.md、相对资源和带执行位脚本 | 链接越界、缺引用、丢执行位、与原生同名资源冲突；复制不执行脚本 |
| 提示词 | agent_options.resources.prompts 引用 OMP 本地资源目录 | `A/prompts/<id>.md` 文件所有权；`/rotom-review` 成功展开一个已声明提示词 | 未声明资源、目录越界、原生同名覆盖冲突 |
| 主题 | agent_options.resources.themes 与 ui.theme_dark/theme_light | `A/themes/<id>.json` 完整 schema 校验/文件所有权；config.yml 的 `/theme/dark`、`/theme/light` 字段所有权；样例 custom rotom-dark | 非完整主题、未知色值/字段、选择未部署主题；不能仅换名字算验证 |
| 快捷键 | agent_options.ui.keybindings 的 action→string或string[] | `A/keybindings.yml` 每个 action 字段所有权；样例 app.model.cycleForward→Ctrl+P，app.history.search→[] | 旧嵌套 keybindings 对象、未知 action、不合法 chord；空数组必须保留 |
| 扩展 | profile.plugins 选择 agents/omp/plugins.toml 的明确包与入口 | 无第三方依赖的本地 TS 扩展包放 R/packages/<id>；config.yml `/extensions` 为显式绝对入口列表；`/rotom-health` 返回固定非秘密标记 | 未锁包、缺入口、引用未打包依赖、加载错误、Pi API 不兼容 |
| MCP | profile.mcp 选择 registry 服务，transport stdio→type stdio；streamable-http→type http | `A/mcp.json#/mcpServers/<id>/<leaf>` 字段所有权；锁定的本地 stdio echo 服务通过 tools/list 与一次受控工具调用；无认证 HTTP 映射另做隔离验证 | 不支持 transport、隐式 npx/uvx 安装、声明外可执行程序、秘密字面值、缺必需 env、未知 server 字段 |

八类中主题/快捷键拆成两行验收；任何一行不能以“原生保留”或“不支持”替代成功样例。实例中至少有一个完整验收 profile 覆盖九行。示例服务/model 全部使用虚构数据，不能把 fixture ID 当作真实平台支持。

## Provider 与模型约束

- 首版自定义静态模型支持 text/image input、context_window、max_output_tokens；写原生 name=公共 model ID、id=remote_id、contextWindow/maxTokens/input/api。自定义模型必须声明 context_window/max_output_tokens，这是管理器的严格输入政策，原生 schema 本身将容量和 cost 设为 optional；不凭经验编造容量、价格、reasoning 能力。无计费依据时不生成 cost，不声称能准确统计费用。
- 角色值采用精确 `<native-provider>/<remote-id>`，不是 OMP 模糊匹配。公共 `main` 只在适配器内映射为原生 default。
- 首版订阅登录映射：公共 `codex` 的 `oauth-dynamic/oauth` → 原生 `openai-codex`。其他 OAuth owner 尚未独立适配时明确失败；不复制 Pi 的 Cursor owner 或假定其扩展可用。Kimi/Z.AI/国内智谱的 native usage 透传不限于 rotom 配置清单，但不等于管理器已适配其模型配置。
- 无静态模型的 bootstrap profile 可以完成 validate/sync/apply/login；模型选择交给新身份登录后的原生目录。原生交互产生的角色值是漂移，不自动成为公共模型定义；capture 不能唯一反查到已声明模型时拒绝。
- 同一 profile 多个公共 provider ID 映射到同一原生 provider key 时拒绝，防止认证和模型覆盖歧义。
- provider.apiKey 只写 `AGENTCFG_OMP_PROVIDER_<完整ID哈希前24hex>_KEY` 这样的整值变量名；由部署契约记录 SecretRef→env，不写值。注入前检查完整 ID 防截断碰撞。

## Settings 最小白名单

用户可设置：本矩阵模型角色、主题、快捷键。首版不开放任意 raw-native/settings 表，也不继承 Pi 的 ui 字段。

管理器负责的保护设置：`skills.enablePiUser=true`、`skills.enablePiProject=false`、`mcp.enableProjectConfig=false`、`enabledProviders=[]`、外部 `disabledProviders` 清单、`startup.checkUpdate=false`、`marketplace.autoUpdate="off"`、`autolearn.enabled=false`。使用原生字段的实际嵌套结构，禁止把 `theme.dark` 错当作必须字面带点的 YAML key；编码与样例由固定 schema 校验。

固定禁用清单：agent-plugins、agents-md、claude-md、claude、claude-plugins、cline、agents、codex、cursor、gemini、opencode、github、mcp-json、omp-plugins、skillshare、ssh-json、vscode、windsurf；保留 native、builtin-defaults。模型 provider 与 discovery 共用命名空间，自定义 native provider ID 命中禁用清单时 validate 失败2。此列表不能替代项目/direct helper 的逐次来源检查。

`agent_options.discovery.project_resources=true` 仅可在声明完整项目来源后放开必要的项目 skill/MCP 开关，不能自行解除模型/认证/根目录守卫。外部来源与 dotenv 的规则见 [runtime contract](runtime-and-dependencies.md)。

默认启动禁用自动 title 和本地模型相关的可选功能；首版不暴露需要未锁按需包的 memory/tiny/speech/browser/eval 配置或子命令。必须用固定源码路径加授权 smoke 验证“启动本身不触发包安装”，而不是只根据设置文件推定。用户在宿主会话内主动安装工具不属于配置纳管保证，后续受管入口发现运行包/资源漂移应拒绝。

## MCP 细化

- `stdio` 的 command 必须解析为已锁依赖中的可执行入口；registry.args 保持 argv 字面值，不经 shell。OMP `npx`/`uvx` 等自动安装路径不作为入口。首个可交付 fixture 是仓库本地 Python stdio 服务，解释器绝对路径和精确版本进入 runtime receipt。
- `agent_options.mcp.<id>.environment_refs` 将必要 env 名映射到 SecretRef；写入 mcp.json 对应 env 叶子的是管理器生成的整值 env 名。名称与保留环境变量冲突时失败；不支持 !command 或自动 dotenv。
- `streamable-http` 首版支持无认证 HTTPS endpoint，以及 registry.credential_ref 表示**完整 Authorization header**的模式。原生 header.Authorization 写管理器生成的整值 env 名，运行时注入完整 header；不进行字符串拼接、Cookie 获取或 OAuth credential export。该语义必须在 examples 中注明。
- transport=sse、MCP OAuth/自动 reauth、外部任意 header 表首版明确失败，不影响已要求的 MCP 类别交付。用户主动采用这些原生能力不被宣称为 rotom 已支持。
- 与模型运行无关的 MCP secret 不注入 managed usage/login；普通启动只解析选中服务的必要引用，缺失在启动前由管理器退出 3。OMP 本身在 bare env 未设置时会回退为字面值，不能把该失败语义交给宿主。

## 所有权、捕获与非秘密导入

- 对 config.yml/models.yml/keybindings.yml/mcp.json 使用互不重叠的字段 selector，不能声明整个 providers/mcpServers 对象后又声明其凭据叶子。实际每个受管 provider/server 分解为叶子；模型列表是一个数组值，逐对象扫描保证无秘密字段或执行表达式。
- config.yml 原生 auth、session、usage 状态不纳管。运行时若出现 broker/根覆盖/危险发现设置，准入失败；不静默删除用户字段。
- `capture` 首版 allowlist：theme.dark/light、已声明快捷键 action、能唯一反查的 modelRoles。其他类别仍能部署/更新/回滚；不承诺把扩展代码或所有原生文件反向导入。
- `inventory omp --source` 是一次只读来源盘点：只读取已知 config/models/keybindings/MCP 的允许非秘密字段与选定资源路径，认证键仅输出“未导入”状态，不回显值；拒绝整库、整 home 递归归档。
- inventory 输出私有 cache 内的资源处置表、允许的 local override 提案和候选资源包；不自动写 shared、profiles、来源目录或受管目标。执行路径/敏感字段/已知秘密扫描，无法证明可安全复制的资源标为 review-required。用户审阅后手工合并提案、复制批准的包到 agents/omp/resources 或 shared/skills 并声明，再走 validate/render/plan/apply；不新增 import 子命令，不执行资源脚本。
- 旧环境始终非受管；来源只读、目标必须是新建身份。目标非空且无同一归属证明时退出 4，不提供“强制接管”。

## 证据要求

各行需一份隔离正向、相关负向和原生生效证据。隔离测试只证明管理器行为，native smoke 证明加载，账号模型调用已转独立遗留，未来恢复时另需授权和实际结果。未执行项保留未验证，详见 [validation matrix](../validation-matrix.md)。
