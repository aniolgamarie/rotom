# omp-permission-control

这是 OMP 的独立权限控制插件源码目录。默认入口为 `standalone.ts`，只使用
官方扩展 API 注册 `permission_bash`、可选原生 `bash` 包装和 `/permission-control` 命令，不修改或
monkey patch 宿主源码。同名包装与 `ctx.invokeTool` 委托属于官方文档支持的扩展接口。旧 `index.ts` 及 core 文件只通过 `./legacy` 导出保留历史记录，
不是当前交付入口。

`permission_bash` 覆盖模型发起的 raw non-interactive Bash：它在自身 `execute` 内完成
原生 pattern 下限、模型审查或人工确认，然后调用公开的 `omp.exec("bash",
["--noprofile", "--norc", "-c", command], ...)`。它不改变 command，不读取 shell
startup 或 direnv。raw 入口不继承服务、后台 job、PTY 或原生执行上下文。
启用 `nativeBash` 时，普通原生 Bash 先审查，再通过公开 `ctx.invokeTool` 委托；首批只接受
command/cwd/timeout，未知 async/service/PTY 字段显式阻止，不剥离参数换成另一后端。插件缺失、配置无效、审查故障、无 UI、取消或会话/模型
变化都会阻止 `permission_bash` 执行，原生 Bash 的 prompt 策略保持可恢复。

插件在注册及 session start/switch/branch 边界从公开 `getAgentDir()/permission-control.json` 读取
schemaVersion 2 的封闭配置；它不监视会话中途的文件变化，也不声称等价于宿主动态 policy、
credential 或版本管理。
插件拒绝未知字段和符号链接。配置包含默认 session-only 模式、可选 nativeBash 布尔开关、主审/远程 fallback、
installed-only tiny 声明、插件与 policy 摘要及原生 patterns。当前公开 API 没有可靠的
installed-only 本地模型查询，因此 tiny 状态固定为 unavailable，不下载也不调用内部 worker。

主审只支持 `anthropic-messages` 和 `openai-completions`，共用 30 秒期限，不重试、不跟随
重定向。Anthropic 响应可包含标准 thinking/redacted_thinking 元数据，审批只读取唯一 text 块；未知块、tool_use、多个或缺失 text 仍失败，严格决策 JSON 不变。只有 transport、unsupported 或严格 JSON 无效才尝试一次不同实际模型的 remote
fallback；有效 allow/ask/deny 立即终止模型链。自动 allow 必须同时是 low risk、sufficient
authorization 和 `LOW_RISK_AUTHORIZED`。完整 command、cwd 与真实 user 消息合计超过 24 KiB、
疑似包含凭据、缺少真实 user 来源或无法保守解析 shell 语法时转人工；无 UI 则阻止。

## 默认隔离边界

- 测试必须使用临时 HOME、XDG、OMP home、cache 与 local config。
- provider、model、Settings、UI、subprocess 与 execute 全部使用虚构或假实现。
- 默认阻断网络，并为下载、安装、mkdir、direnv、service/job、backend 和秘密值设置哨兵。
- 测试只导入纯模块或补丁集成函数，不启动 OMP CLI/TUI、真实 worker、宿主或模型。
- 固定样本是数据，测试和生成过程不得执行其中的命令或事件。
- 真实宿主 smoke 与真实模型评测分别等待明确授权，不能由假模型或文件存在代替。

## 目录职责

- `package.json`：包名、独立入口与 OMP 兼容范围；不含安装脚本或运行时下载。
- `standalone.ts`：公开扩展 API 接线、session-only 状态、命令、工具和公开 `omp.exec` 执行。
- `standalone-reviewer.ts`：有界模型输入、严格结果协议和一次远程 fallback。
- `native-bash.ts`：公开原生审批与 Setting 句柄、scoped/global 设置同源检查及上下文核验。
- `native-bash.test.ts`：虚构原生适配器下的下限、设置变更与执行上下文验证。
- `standalone-shell-analysis.ts`：用于 native patterns 的保守通用简单命令解析。
- `standalone.test.ts`：临时假上下文、假 transport 和假 backend 的独立插件测试。
- `tests/`：扩展纯逻辑测试，由独立 build-inputs 锁校验后的 Bun 运行。
- `shell-analysis.ts` / `policy.ts`：完整受限命令分析及固定风险下限。
- `controller.ts`：由宿主私有持有的单次许可账本与会话状态；扩展不能取得宿主实例。
- `reviewer.ts`：有界完整输入、严格 JSON/逐效果证据，以及主审、远程 fallback、installed-only tiny 的预算逻辑。
- `session-commands.ts` / `audit.ts`：固定状态输出和不含原始命令的最小审计。
- `evaluation/`：只读消费冻结样本的评测入口；不得执行待审命令。
- `agents/omp/patches/permission-control/tests/`：旧 bridge 方案的历史测试，不属于独立插件交付。
- `tests/fixtures/omp/permission-control/`：规则实现前冻结的样本、标签和摘要。
- `docs/acceptance/omp-permission-control.md`：命令、隔离环境、结果和未覆盖范围。

包声明兼容 Bun `>=1.4.0`；该范围不是构建身份，精确版本、插件树和入口摘要由独立
build-inputs lock 记录并校验。旧 core、patch 和历史验收不构成独立插件的通过证据。

## 配置与会话命令

显式 `reviewer: {provider, model}` 优先；`reviewer: "session"` 在每次审查开始时绑定会话
当前模型。可选 `remoteFallback` 只在主审运行故障或输出无效时调用一次，并跳过与主审
解析为同一实际 provider/model 的配置。

- `/permission-control smart`：启用本会话智能审批，前提是插件、宿主和审查服务可用。
- `/permission-control manual`：撤销待处理许可并切回人工审批。
- `/permission-control status`：查看模式、主审身份及 `reviewerHealth`、远程 fallback 身份及
  `remoteFallbackHealth`、tiny 状态、最近一次覆盖判断和原生保护；状态读取本身不解析模型或发起请求。
- `/permission-control explain`：查看最近决定、固定理由及人工批准链；不显示原命令或模型正文。

模式切换只保留在当前会话内。新会话或恢复会话重新读取 profile 默认模式；恢复/导入的
历史若不能证明完整真实用户来源，仍需人工确认。裸命令或未知子命令显示上述四种用法。

`status` 和 `explain` 只读取内存状态，不解析凭据、不联网，也不显示命令、对话、秘密、
模型自由文本或异常原文。模式切换会取消 pending 审查并增加 generation；执行前再次核对
session、generation 和当前模型。新建、恢复、切换和分支会话都重新读取默认模式。
并行 `permission_bash` 调用由插件队列串行执行；正常的后续调用不会取消前一调用，模式切换、
会话切换、shutdown 或各调用自身 signal 才会撤销对应 pending 工作。

## 自动审批边界

智能模式先保守解析完整的简单或复合命令，对每个 simple argv 匹配配置 patterns。
任一 deny 直接阻止，任一 prompt 只走人工；模型不能覆盖它们。普通选项（例如 `ls -la`）
直接交给模型判断，插件没有固定只读命令白名单。动态或不支持的 shell 语法转人工确认。
人工选择只有完全匹配 `Approve` 才允许；无 UI、undefined、取消和异常都阻止执行。

这是应用内审批，不是操作系统沙箱。安装和运行以管理器的受管交付流程为准，详见
[OMP 依赖说明](../../../../docs/omp-dependencies.md) 与
[本特性验收记录](../../../../docs/acceptance/omp-permission-control.md)。仓库隔离测试、
离线编译、真实宿主 smoke 和真实模型评测是不同证据，不能互相替代。


## 原生 Bash 包装（Phase 14）

公开 `agent_options.permission_control.native_bash` 渲染为 sidecar `nativeBash`，缺省 false；
kernel 配方明确开启。注册时决定是否包装，不在活动会话中通过手工改 sidecar 切换入口。
启用后保留原生 active bash，使 Cursor 按固定工具名发起的 shell 调用可进入插件。

包装与 tool_call 安全钩子位于同一闭包；execute 必须具有钩子捕获的一次性调用票据，不能把
缺钩子视为通过。票据绑定完整参数、cwd、会话、generation、当前执行模型和真实设置指纹。
审批后改参、取消、切模式/模型/会话或改变相关设置均使票据失效，最多原生委托一次。

原生 per-tool deny、pattern deny/prompt 和 critical prompt 不被外层 permission_bash=allow
或模型结果覆盖。普通 exec/native allow 仍进入模型审查；默认 bash=prompt 保留插件缺失保护。
执行端与会话设置不同源时人工或阻止；不靠 cwd 相同猜测设置实例。startup/.envrc/worktree
重写等未知上下文不能自动批准，也不在审批前运行 shell snapshot 或 direnv preflight。
默认 interceptor/auto-background 的开关本身不是强制人工的理由，实际结果通过原生委托保留。

Phase 14 生产插件已通过纯测试、固定 SDK 类型检查及隔离官方宿主（含真实人工 UI）；
真实 Cursor 服务调用与日常部署尚未执行。status 区分配置与覆盖；
公开元数据不足以证明最终注册来源时不报告完整 coverage ready。真实 Cursor、模型质量、
高级执行和其它平台分别登记，原型或历史 patch 通过不能转移为本次通过。


官方宿主会删除封闭工具 schema 的未知键再重试，因此工具参数 schema 保留未知字段，
由插件在 hook/execute 两边精确拒绝；配置与 sidecar 仍封闭。传输层可另行转换 strict
schema，本地拒绝保证不能由 wire schema 或 TypeScript strict 类型检查替代。

Shell snapshot 私有缓存无法查询加载前历史；首批支持从新 CLI 进程启动时加载插件。
观察到 startup、不同 HOME 或继承 shell 函数后，未知缓存状态在插件生命周期内保持人工，
即使删除 rc 也不会恢复自动批准；热加载到已有执行进程尚未支持。

## 常见 Shell 环境（Phase 15）

受管启动保留调用者或机器配置选定的 `SHELL`。开启 `native_bash` 时，管理器在启动契约
绑定非秘密的本地执行路线标记；机器覆盖和调用者预置该标记均被拒绝。插件每次捕获和
执行前检查标记、公开 CLI 形状以及真实 scoped Settings，环境或参数变更会撤销票据。
这项契约只适用于 `agentcfg run` 启动的官方 CLI；标记是配置边界，不是来源认证或防止
同 UID 进程伪造的凭据。第三方自行嵌入 SDK 或热加载到已有宿主不属于这项覆盖范围。

支持识别 bash、sh、zsh、dash、ash、ksh、mksh、fish、pwsh、powershell 和 cmd 的标准
调用形状，包括 Windows 路径及 `.exe` 名称。普通本地原生 Bash 使用 OMP 的内置 Brush；
这项兼容表示上述 Shell 环境可以进入智能审批，命令仍使用 Brush 支持的语法，不表示
fish、PowerShell 或 cmd 的原生语言已经适配。已确认本地执行路线时，非 Bash 的启动脚本
和已知同族 custom shellPath 不参与普通 Bash 执行；Bash 的 snapshot/startup、继承函数、
HOME 不一致、direnv、prefix、未知 Shell/args/path 和 worktree 重写继续保守处理。

无受管标记的普通旧 Bash/sh 启动维持原有保守行为。标记错误、ACP、rpc-ui、未知 CLI
选项或模式不自动批准；PTY、async、service 等参数仍在现有边界之外。可以使用
`/permission-control explain` 查看固定的 `shellFamily`、`executionRoute` 和 `contextReason`；
人工询问会显示固定原因码，不输出环境变量内容或启动文件路径。

验收与实际平台范围见 [Shell 兼容记录](../../../../docs/acceptance/omp-shell-approval-20261004.md)。

## 静态 Shell 词法与公开场景回归（Phase 18）

普通命令现支持边界后的注释、LF 多行分隔/续行、空参数和引号拼接、参数中的未引用
通配符，以及 `>`、`>>`、`<`、`>|`、`>&`、`<&` 的静态目标/0—9 描述符。
解析结果保留 glob 参数位置、重定向顺序、源 fd、操作符和目标；不做路径扩展或执行。
原始 command 原样交给模型和原生委托。通配符在命令名中、重定向目标中的 glob、动态
替换、控制结构、heredoc、brace/tilde 展开、CR、truncated 输入和未解析执行脚本仍走
人工边界（无 UI 阻止）。`unsupported-syntax` 表示超出静态合同，不等于 Shell 本身非法。

当前命令/参数规则的 deny 优先于语法 fallback：原文匹配、每个可见简单命令及静态
重定向效果都检查；通配符可能作用于同一命令的 deny 参数时保守拒绝，prompt 时人工。
不存在先求值或展开通配符来完成审批的过程。已识别但未展开的 wrapper、代码选项、执行型 find/awk/sed
以及 shell 状态/事件处理脚本保守人工；这些规则不是进程级沙箱，不保证禁止所有外部
程序的间接行为。没有命中固定 deny 时，人工可以明确批准未解析的命令。

`tests/fixtures/omp/command-scenarios/corpus.json.gz` 是公开虚构数据：由授权私有场景的
词法形状重建，替换普通值、名称和代码数据，去掉原始指纹、来源与会话信息。
独立 Python oracle 借助 shlex 解码单词，生成确定性预期；79 条硬编码语义 anchors 另行
验证，包含原来3个注释错误和12个常见语法缺口。所有公开场景还通过 fake Settings、
模型 transport 和 backend 验证 native hook/review/委托或 headless 人工边界。
该结果证明声明语法合同与插件接线，不代替真实 Shell、真实 OMP 或模型风险质量评测。

仓库默认验证（不执行测试命令、不启动第三方 agent、无真实模型请求）：

```sh
bun test ./tests/omp_shell_scenarios.test.ts ./tests/omp_command_history.test.ts \
  ./agents/omp/packages/omp-permission-control/standalone.test.ts \
  ./agents/omp/packages/omp-permission-control/native-bash.test.ts
```

生产源码和本目录测试变化后，须同时刷新官方普通锁中的插件树与 recipe 身份。
不构建、刷新或扩展已退休的 patched-host 运行包。

语法失败时，已知前缀可在 24 KiB / 256 token 上限内额外加强 deny；这条路径从不据部分
分析批准。原文 wildcard 匹配覆盖换行，避免动态后缀遮住已知被禁止的直接命令。
凭据字段/长选项、自定义 token 名、Basic/Bearer、URL userinfo 与 curl 认证参数会阻止
送入审查模型；人工预览遮盖其值，含短选项粘连、字段名/值的引号拼接与续行。公开重建保留这些信号并替换真实名称/值，
因此“静态解析成功”仍可能按凭据边界人工。

## 常见静态 shell 参数的审核边界

普通参数中的未引号 `~`、`~/...` 保留原文并标记 HOME expansion，不读取真实 HOME，
不把它当已解析路径。HOME 与 glob 的具体参数可能命中 native deny/prompt 时仍保守
转人工；宽泛、raw 与可见前缀 deny 不变。命令头、重定向目标、`~user`、`~+`、`~-`
及动态插值仍拒绝；quoted/escaped tilde 保持字面量。

仅确切 `command -v NAME...` 与 `command -V NAME...` 的静态查询形式进入普通审核，
可有固定 `--`，至少一个静态名字。不开放执行型 command、`-p`、组合/未知 flags
或路径同名程序。没有新增自动允许：smart 仍须原严格模型审查及 native/settings/
session/generation/ticket 复核；待审 command 原文和全部调用参数不改写。

默认 corpus 保留原 gzip 与 gate 标签。`tests/fixtures/omp/command-scenarios/` 中的
`parser-before-home-query.ts` 是本仓库自有 parser 的精确历史快照（SHA-256
`9a9d9e7208b66be04f61801d8b3af35339d313d838c243d20b3c40c113586f8b`），
`grammar-upgrade-20261009.json` 是 root 审定、SHA 绑定的 583 个静态语法 ID overlay
（501 HOME、74 query、8 两者兼有）。测试先回读原 parser/fixture，再仅按固定 map
升级机械假模型 eligibility，其余 10890 行门控不变；不重生成原标签，不证明风险
allow、真人授权或真实宿主。逐行观测只保存 ID/门控与计数，命令样本不执行。

冻结原 corpus SHA-256 为
`d6e5dc5d68c685d44949a0487f7ff71bd60b28daad228c20ec8070d39a710699`；
overlay SHA-256 为
`92211b188ca473c31ebdf431bee5c7bae661d4d6306a5e7ebfdaa9b0ed18815b`。
每个 overlay ID 还绑定原 row 的递归排序 canonical JSON SHA，原 gzip 永不重写。
