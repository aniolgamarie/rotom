# OMP 研究与决策

> 本文为历史设计依据；当前验收范围以[2026-09-24 范围修订](scope-change-20260924.md)为准。其他平台与真实账号验收已转独立遗留，不再属于本 spec 完成前提。

日期：2026-09-24。依据：[spec.md](spec.md) 的两项澄清。本文记录设计结论，未运行 OMP 或访问真实认证；代码路径均为只读证据。

## R01 — 固定宿主与交付形式

**Decision**：以 OMP `v18.3.0`、提交 `62bc57be1b03ef0802a33cf7f5f530e534527531` 为首版基线，使用官方 standalone 发布文件；受管运行禁止退回 PATH 上其他 OMP。Python 管理器沿用现有依赖，不安装 Bun/Node 来启动 OMP。选定本地扩展不含第三方依赖，MCP 样例使用锁定的仓库本地服务包。

**Rationale**：官方二进制嵌入运行时和主要宿主依赖，避免重复搭建上游整个编译链；公共 backend 仍需验证实际字节、平台、资源和依赖身份。源码根 `packageManager` 与安装脚本最低 Bun 版本并不相同，不能照搬一条笼统 Bun 安装命令。

**Alternatives considered**：PATH 宿主无法保障受管身份；执行上游安装脚本会全局安装并启动宿主；源码补丁构建增加完整工具链维护成本。本设计用明确的来源拒绝规则兑现首版边界，不需要宿主补丁。

证据：[release](https://github.com/can1357/oh-my-pi/releases/tag/v18.3.0)、[commit](https://github.com/can1357/oh-my-pi/commit/62bc57be1b03ef0802a33cf7f5f530e534527531)、[compile-binary.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/scripts/compile-binary.ts)、[checksums](https://github.com/can1357/oh-my-pi/releases/download/v18.3.0/SHA256SUMS.txt)。编译器关闭 Bun 自动 dotenv/bunfig/tsconfig/package.json 加载，但 OMP 自己仍读取 dotenv，见 R04。

| 平台 | asset | 发布 SHA-256 |
|---|---|---|
| Linux glibc x64 | omp-linux-x64 | d2fdaa29affe96e596eb9c78d42f548f1f291df28608631bcc00750a84b94bc3 |
| Linux glibc arm64 | omp-linux-arm64 | bdfb9c494e17a2fee1956dae16a010a1953574ce4172c4db8efe06fbe477c637 |
| macOS arm64 | omp-darwin-arm64 | d61fb411f24146bed48dd901b13b5912a297d899ee691dda69c4b5b7ab8c35dc |
| macOS x64 | omp-darwin-x64 | be74498e0edcde7e018247b925f0e0ebf00a7748a1006b3a02eb62ca9e021baf |

这些是已读取的官方校验声明，未下载并验证各平台二进制，更未运行。首版排除 Windows/musl，匹配不到声明平台退出 5，不猜测兼容。只读研究下载的 tag 源码归档 SHA-256 为 `a17689ba611355ddc7225541673268b2d1ff1527523cc028b3fbd6ea5b069533`，归档内容中的 package 版本为 18.3.0；tag 的提交关系由发布页确认。实施 lock 时使用不可变提交归档并重新记录其摘要，不把 tag 归档摘要套用给另一 URL。

## R02 — 复用公共生命周期，独立适配 OMP

**Decision**：新增 OmpAdapter/OmpDependencyBackend/OMP schemas 与 `agents/omp`、`locks/omp`，沿用 Workspace、Artifact、ManagedTarget、deployment、runtime 的事务和锁；不继承 PiAdapter 的原生路径、包切片或能力结论。

**Rationale**：现有工作区按 tool/profile 分隔，字段三方比较、pending/previous、安全投影已经提供基础能力。OMP YAML、profile、二进制包身份和发现规则需要独立表达。

**Alternatives considered**：直接将 Pi 名称替换为 OMP 会遗漏原生 discovery、profile 和角色差异；再建一套部署器会复制恢复/所有权风险。

仓库证据：`src/agentcfg/workspace.py:14,38-52,62-82`，`adapter.py:25-176,184-258`，`deployment.py:35-181`，`runtime.py:25-107`，`process.py:10-49`。公共扩展只涉及显式操作上下文、OMP 选择入口和精确环境引用语法，必须保留 DSH/Pi 回归。

## R03 — 原生 profile 与实例身份

**Decision**：`native_name = "rotom-" + sha256(profile.id UTF-8).hexdigest()[:24]`，HOME 固定为 `<instance>/user-home`。原生配置根为 HOME 内 `.omp/profiles/<native_name>/agent`。绑定保存完整 profile ID/hash、规范化 instance/HOME/native path、machine/local 归属及 runtime identity，不能只用短名字作为身份。每个配方独立 HOME，即便 OMP 内部有 profile-independent 服务也不共享原始用户 HOME。

**Rationale**：命名 profile 忽略 `PI_CODING_AGENT_DIR`；仅设置该变量不能改变其原生目录。新建身份符合用户接受重新登录的决定。原生 profile 与公共配方不是同一字符串，更不是共享账号池。

**Alternatives considered**：接管默认目录或复用已有命名 profile 不在本次范围；多个配方共享同一个 OMP 身份违反独占归属。

XDG 采用固定的 `profile-root` 布局：HOME 内设置各 XDG base，但不创建 `<XDG_*>/omp/profiles/<native_name>`。这些目录一旦出现就可能改变 OMP 实际路径，启动/usage/login 前检测并拒绝，要求显式恢复既定布局，不自动搬迁。默认快捷键只可能继承隔离 HOME 中的默认文件；如需旧快捷键，以显式非秘密导入形成受管投影，不挂接旧账号 home。

固定版本证据：[dirs.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/utils/src/dirs.ts) 的 profile 解析、DirResolver 和 setProfile，约 59–117、328–381、538–578 行；[keybindings.md](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/docs/keybindings.md)。

## R04 — 发现与环境边界：原生设置加启动准入

**Decision**：默认只允许受管 native 用户资源和宿主内置资源。关闭项目 skills/MCP、外部发现和更新；对仍会被直接读取的项目/祖先/默认目录输入做预检查。显式来源配置不合法报参数/配置错误 2；运行时发现未声明来源或受管身份、目录布局、关键部署守卫被改变报冲突 4。未知发现路径/格式不猜测，拒绝。

**Rationale**：原生 native provider 同时扫描项目和用户来源，没有完整的 user-only 总开关；禁 native 会连受管规则/提示词等一起关闭。OMP 还会 eager 读取 HOME、profile root、agent dir、cwd 的 `.env` 并刷新目录；单靠父环境白名单不够。

**Alternatives considered**：通过 `disabledProviders=[native]` 会丢失必交类别；`--no-rules` 也会关闭受管规则；改 cwd 后偷偷用另一个工作区会改变用户行为。本版保留用户 cwd，遇到不能隔离的输入明确失败。暂不采用宿主补丁或 OS 沙箱。

来源检查规则及允许清单见 [runtime contract](contracts/runtime-and-dependencies.md)。它是启动/显式重新进入时的配置准入，不宣称对同用户恶意并发修改或任意扩展代码提供 OS 级隔离。原生会话中主动加载新来源不属于已验证启动配置；由受管说明要求结束会话后重新声明和验证，不声称能强制阻断原生所有交互操作。

证据：[builtin.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/discovery/builtin.ts) 58–73、277–457；[env.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/utils/src/env.ts) 261–313；[settings.md](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/docs/settings.md) 的 discovery namespace。`disabledProviders` 同时控制模型与发现来源：首版 OAuth 映射只开放 `codex → openai-codex`，不会把 cursor 的发现禁用误报为 cursor 模型已支持；其他映射须显式声明并检查 ID 冲突。

## R05 — 八类映射与最低交付基线

**Decision**：按 [native-capabilities.md](contracts/native-capabilities.md) 固定九个验证行（主题和快捷键分开），每行都有实际原生目标、字段边界、成功样例和失败样例。settings/models/keybindings/MCP 用字段所有权；文本与资源包用明确文件所有权。

**Rationale**：OMP 与 Pi 的模型配置、角色和快捷键格式不同。未知公共字段失败、原生非受管字段保留，不能把原生整个目录当作配置备份。

**Alternatives considered**：以空清单或全部“不支持”满足范围已被用户明确否决；复制全部 Pi 插件或原生 home 会混入不兼容资源与认证。

固定字段证据：[models](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/docs/models.md)、[settings](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/docs/settings.md)、[theme](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/docs/theme.md)、[extension-loading](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/docs/extension-loading.md)、[MCP](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/docs/mcp-config.md)。这是源码/文档映射证据，不是本机运行结果。

## R06 — 秘密引用与认证作用域

**Decision**：认证保留原生存储；受管首版禁止 auth broker/gateway 连接，防止一个 profile 看到远端全账号池。API key 和 MCP secret 仅保留 SecretRef，运行时注入声明的环境变量。原生文件写入整值环境变量名，禁止 `!command`、字面 token 和动态配置表达式。

**Rationale**：OMP 的 provider.apiKey、MCP env/header 支持整值环境变量名；现有 rotom 仅认可 `$VAR` 的引用守卫，必须扩展为显式声明的精确变量引用，并校验历史/pending/回滚状态。不能为了 YAML 适配放宽任意凭据字符串。

**Alternatives considered**：整库复制/直读 auth DB、Cookie 抓取、把密钥写入 models/MCP 均不采用。利用 MCP OAuth 自动登录不作为本次认证扩展。

证据：仓库 `adapter.py:51-66`、`native_projection.py:10-78`；固定版本 [auth-broker-config.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/session/auth-broker-config.ts) 与 [discover.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/ai/src/auth-broker/discover.ts) 表明 broker 会替换本地 credential store，本地走 active agent 的数据库。

## R07 — usage 的两个入口

**Decision**：无显式 `--profile` 的 `agentcfg usage` 直接执行 PATH 上 `omp usage`，不创建 workspace、不读 local/secrets、不改环境或 cwd、不额外汇总账号。显式 `--profile` 时复用已部署运行契约，argv 为 `<locked-omp> --profile <native_name> usage <tail>`，cwd 使用实例内中性目录，保留 stdout/stderr 和原生退出码。

**Rationale**：`extractProfileFlags` 在遇到拥有自身参数的子命令后停止提取；把 `--profile` 放在 usage 后面不能用作可靠的全局选择。受管 mode 的 credentials 必须来自同一原生身份，但不能让未登录模型或不相关 MCP 密钥缺失阻塞用量查询。

**Alternatives considered**：无条件加载 workspace 破坏已批准的轻量使用方式；`omp usage --profile ...` 不符合固定版本 bootstrap；对原生输出重新排序/聚合会改变薄封装语义。

证据：[profile-bootstrap.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/cli/profile-bootstrap.ts) 及 [commands/usage.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/commands/usage.ts)，[usage-cli.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/coding-agent/src/cli/usage-cli.ts) 的 Settings.loadReadOnly/discoverAuthStorage 路径。操作参数见 CLI contract。

## R08 — 智谱遗留结论的处置

**Decision**：本版只封装 OMP 的实际输出，不新增智谱采集器。v18.3.0 原生 usage registry 有 `zai`、`kimi-code`、`openai-codex` 等，但没有 `zhipu-coding-plan`；zai 的 supports 明确限定 provider===zai，不能用于冒充国内智谱支持。

**Rationale**：旧文档的“唯一途径是控制台”过强；[智谱官方助手](https://docs.bigmodel.cn/cn/coding-plan/extension/coding-tool-helper) 已提及用量插件。但插件详细页获取失败，不能推导公开接口/套餐范围，亦不影响薄封装实现。

**Alternatives considered**：独立直连接口和 Cookie 抓取仍排除。作为外部能力限制记录在文档，原生输出无该数据不等于零用量。

固定证据：[usage/registry.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/ai/src/usage/registry.ts)、[usage/zai.ts](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/ai/src/usage/zai.ts)。未来上游版本变动须更新证据，不能把在线最新文档混作此版本行为。

## R09 — 实施顺序与验证边界

**Decision**：先建立身份/lock/字段引用守卫和隔离 fixture，再交付八类映射、公共生命周期、inventory/login/usage，最后文档及 native/live 验收。完整覆盖矩阵见 [validation-matrix.md](validation-matrix.md)。实际 task 拆分交由 speckit-tasks。

**Rationale**：先固定安全边界避免把后来发现的 profile/秘密问题分散修补到各命令。默认测试继承 `tests/conftest.py` 的临时 HOME、断网、禁止真实进程规则；真宿主验收独立授权。

**Alternatives considered**：通过宿主启动成功或二进制存在宣称全部能力可用不满足 spec；为了快速验证而使用真实 home 不允许。

## 研究状态

设计选择已全部确定，无需要继续向用户澄清的方案分叉。固定版本源码和 checksums 已读取；GitHub API 直接请求触发 403 rate limit，改用发布页和公开源码归档完成版本核实。尚未执行宿主、安装包、平台 smoke、登录、订阅查询或模型调用；它们是实现验收项，不能标通过。智谱详细插件接口属于不在本次实现范围内的外部信息不足，保留限制而不阻塞独立薄封装。
