# 独立插件修订：官方 OMP 与公开扩展接口

2026-09-30，维护者要求移除宿主补丁并把权限管控改为独立本地插件，同时确立所有 agent 上游源码不修改的项目原则。本修订是当前实现与验收依据；此前 spec/plan 中的 bridge、patched standalone、read-proof、installed-only host tiny 和一次性宿主许可要求属于历史架构，不能继续作为当前交付要求。

## 当前需求

- FR-040：使用未修改的官方 OMP 运行包。插件只使用公开扩展 API，禁止宿主源码补丁、私有模块或运行时 monkey patch。允许按官方接口文档使用 `registerTool()` 注册同名 `bash` 包装，并通过公开 `ctx.invokeTool()` 委托保留的原生实现；不得改写宿主对象或调用私有执行函数。
- FR-041：注册独立工具 `permission_bash`。工具的执行函数在模型/人工决定完成后调用公开 `omp.exec`，每次请求最多发起一次实际 Bash 执行；插件缺失或执行函数异常不能把原生 Bash 改成默认允许。可显式启用原生 `bash` 包装，两入口共用审批与会话状态。配方保留原生 `bash=prompt` 与 `permission_bash=allow`；插件缺失时回到原生保护，包装缺少配置、可信调用票据或委托能力时必须阻止。
- FR-042：模型审查完整命令、cwd 和真实用户消息，承担语义风险与授权判断。普通 `ls -la` 不得因为旧读取证明不支持隐藏项或长格式而直接人工。可完整解析的简单与复合命令都审查完整操作；无法可靠核对明确禁止/必须人工规则时保守询问，不按只读命令名允许表冒充智能。
- FR-043：明确配置的 deny/prompt 规则仍是模型不可覆盖的边界，从同一 profile 的 `runtime.bash.patterns` 派生，不维护第二套用户规则来源。无 UI、取消、超时、输出无效或缺少真实用户来源时不能获得默许。
- FR-044：主审优先显式 `reviewer_model`，省略时绑定当前执行模型。主审运行故障/不支持/无效输出才尝试一次显式远程备用；相同实际模型去重，有效 allow/ask/deny 终止链。引用错误在配置期失败。输出必须严格校验；allow 仅限低风险且授权充分。
- FR-045：保留本地 fallback 配置身份，但原版没有公开的 installed-only tiny 推理接口时显示 `unavailable`，不通过私有模块或隐式下载补齐。最终转人工或在无 UI 时阻止；不能声称本地模型实际可用。
- FR-046：保留四条 `/permission-control smart|manual|status|explain` 命令。模式只影响当前会话，新建/恢复重置。status/explain 无推理、认证刷新和下载副作用；显示独立工具覆盖范围及真实来源。模式切换/取消后在途批准不得继续执行。
- FR-047：配置放在受管 `permission-control.json`，不向官方 `config.yml` 注入专用宿主字段。整文件所有权、封闭 schema、普通文件/符号链接边界、plugin tree digest 和 policy digest 均验证；部署通过正常三方比较移除旧受管字段，不改账号、会话或凭据。
- FR-048：Cursor 模型发现只使用官方配置与公开接口。启用模型不得放宽私人 HOME 或外来项目资源来源限制；管理器前置检查必须拒绝不受管 Cursor 项目资源。真实 OAuth 发现和模型质量无新证据时保留未验证。
- FR-049：`permission_bash` 执行非交互 `bash --noprofile --norc -c`，不继承原生 startup/direnv/interceptor/job/PTY/worktree 语义。启用后的原生 `bash` 通过公开委托保留宿主执行路径，首批只支持完整 `command/cwd/timeout` 参数。async、service、PTY 或未知参数显式阻止，不剥离后执行。默认 interceptor 与自动后台配置不因开关本身强制人工；可变 startup、实际 `.envrc` 和 worktree 重写等不可核实上下文须人工或阻止。不提供 OS 沙箱、不消除外部竞态，也不接管 eval/MCP/所有子代理。

## 接口与交付

`getAgentDir()/permission-control.json` 为封闭 JSON：

```json
{
  "schemaVersion": 2,
  "defaultMode": "smart",
  "nativeBash": true,
  "reviewer": "session",
  "remoteFallback": {"provider": "zhipu_tf", "model": "glm-5.3-flash"},
  "fallback": {"provider": "local", "model": "lfm2.5-230m", "installedOnly": true},
  "pluginId": "omp-permission-control",
  "pluginDigest": "<verified-tree-sha256>",
  "policyVersion": "<generated-policy-sha256>",
  "nativePatterns": []
}
```

摘要占位仅说明字段，不能作为生产配置。`nativePatterns` 的每项只含 `match` 与 `approval`。插件入口为 `standalone.ts`，不调用历史 `registerPermissionController`。可选 `nativeBash` 缺省为 false，公开配置为 `agent_options.permission_control.native_bash`，kernel 明确开启。原生包装以 `permission_bash` 为外层 policyKey；执行函数必须独立检查真实原生 deny/prompt 下限，不能被外层 allow 覆盖。原生 Bash 配置保持 prompt，插件未注册时保护仍在。

## 计划与验证

1. 工程约定、宪章和架构记录“不修改 agent 上游”及历史偏离。
2. 独立插件与模型链用 fake UI/provider/exec 测试；重点验证 `ls -la`、模型优先级、故障接替、有效拒绝不复审、取消、无 UI 和明确禁止规则。
3. 管理器切换官方运行包、sidecar、工具配置与资源守卫；隔离验证旧字段迁移与账号/配置所有权保护。
4. 稳定插件字节后刷新普通官方依赖锁；不构建或刷新补丁 standalone。历史 patched receipt/模型原始结果保持原身份，不作为新插件通过证据。
5. 默认回归不启动宿主、不联网或调用付费模型。独立真实宿主步骤只在已有明确授权范围内使用临时 HOME 和固定本地 provider；日常部署需单独核对活动实例和迁移 plan。

## 当前状态

| 状态 | 项目 |
|---|---|
| 完成 | T088—T092：基本原则、公开 API、独立工具、sidecar/官方运行包、锁与限定验收 |
| 进行中 | Phase 14：原生 Bash 包装、配置、锁与分层验证；开发分支 `feat/omp-native-bash-approval`，基线 `7558475` |
| 失败待决策 | 无 |
| 环境不足未验证 | 本轮尚未出现环境阻塞；真实 Cursor、模型质量及其它平台未执行 |

本机已按后续明确授权切换为官方运行包与独立插件，具体部署证据见验收 Phase 13。原则不授权自动终止会话、访问账号库或新增付费模型请求。

实际结果与未验证范围见[Phase 12 验收](../../docs/acceptance/omp-permission-control.md#phase-12官方-omp-与独立插件2026-09-30当前交付)。

## 本机启用补充：Cursor 原生角色的明确意图

- FR-050：用户在官方 UI 选择的 Cursor 动态模型可通过显式 `agent_options.native_model_roles` 持久化为本机非秘密意图；当前仅支持官方启用的 `cursor/model[:thinking]`。按公开角色键渲染原有 `modelRoles` 字段，优先于该角色的静态公共模型映射。未知角色、无效标识、思考级别或未启用的 Cursor 必须失败。不得伪造 Cursor API-key/static model、绕过原生登录、删除启动资源守卫或直接修改部署基线。主审显式配置及远程备用策略独立。

本机迁移原生默认选择时采用窄字段编辑与正常三方比较；仅改变明确的私人角色意图，账号、秘密、其它覆盖保持不变。真实模型调用不属于本次启用检查。


## 2026-10-03：Cursor 原生 Bash 接入

- FR-051：原生包装按显式布尔开关注册，缺省 false，kernel 配方 true；开关参与受管 policy 身份。配置读取与执行安全检查位于同一插件闭包，不拆成可独立加载的安全扩展与执行扩展。
- FR-052：在公开 `tool_call` 事件内捕获真实 scoped Settings 及调用 ID；执行必须匹配一次性票据中的完整参数、cwd、会话、generation、模型和相关设置指纹。缺失、重放、参数改写、模式/会话/模型/策略变更或取消均不能沿用许可，最多委托一次。
- FR-053：使用公开 `BashTool.approval()` 与 Setting 句柄核对实际原生策略。per-tool deny 与原生 deny 直接阻止；显式 pattern prompt、critical prompt 必须人工。普通 exec/allow 仍进入审查，默认 bash=prompt 是插件缺失保护，不能导致所有包装调用跳过审查直接人工。执行前再核验下限与上下文。
- FR-054：审查输入包含完整命令、真实用户授权、参数、cwd 和影响执行的已知上下文。实际执行端读取全局 Settings，首批要求其已初始化且与捕获的会话 Settings 同一实例，并在执行前重核；不满足时人工或阻止，不能以 cwd 相同代替实例身份。未知可变资源保守处理，不在审批前运行 startup、direnv 或 shell snapshot 生成；不把环境秘密发送到远程模型。公开接口无法证明的高级执行与调度能力明确标注，不能换成权限更弱的后端。
- FR-055：status 将配置就绪与覆盖就绪分开，显示实际入口、原生委托和 scoped Settings 可用性、各审查层调用数与健康。explain 使用固定原因码区分原生下限、主审传输不支持、备用决定、故障、票据失效和执行范围不支持，不显示原始命令、环境或模型自由文本。
- FR-056：默认验收使用临时 HOME、假模型/执行器和网络阻断；固定官方 SDK 类型检查不得伪造声明。官方宿主 fixture 与真实 Cursor OAuth 分别登记；既有 102/102 模型预算已用尽，新收费请求必须有新授权。真实 Cursor、高级能力和其它平台未运行时不得计作通过。

实施分包与固定版本可行性证据见[原生 Bash 改造计划](../../docs/follow-ups/omp-cursor-native-approval-plan-2026-10-03.md)。T088—T094 为旧独立入口及日常迁移历史，不改写为本次包装已验收。


2026-10-04 参数保留补充：官方校验会对封闭工具 schema 的未知键错误进行 coercion，删除后才发出 tool_call。工具参数 schema 因此保留未知字段，由插件在 hook 和 execute 两边精确拒绝；配置/sidecar schema 仍封闭。OpenAI 的 model-facing schema 可由宿主转换为 strict 形式，但本地输入边界不可依赖 wire schema 或 TypeScript strict 检查替代。首轮 async 被删除问题已作为真实宿主回归记录，不删除失败证据。

Shell snapshot 的缓存只以 shell 为键，公开接口无法查询加载前的历史内容；首批支持新 CLI 进程从启动就加载插件。插件观察到 startup/不同 HOME/继承函数的不确定性后保持生命周期内粘性人工状态，删除 rc 文件不恢复自动批准。热加载至已执行命令的旧进程不在已验证范围。

## 2026-10-04：常见 Shell 环境兼容

- FR-057：保留用户选择的 Shell，不通过覆盖 SHELL 或 shellPath 规避兼容问题。识别 bash、sh、zsh、dash、ash、ksh、mksh、fish、pwsh、powershell、cmd 的标准官方调用形状（含 .exe 名称及 Windows 路径）。支持范围是这些配置环境下普通原生 Bash 的智能审批，不承诺把 Brush 命令语言变成 fish/PowerShell/cmd 原生语言；未知壳或额外启动参数仍人工。
- FR-058：固定官方 v18.4.5 的本地普通 BashTool 委托不传 useUserShell，使用内嵌 Brush；只有 Bash 配置会生成 Shell snapshot。ACP 客户端终端可能实际执行外部 Shell，但公开 ExtensionContext 不能辨别客户端 bridge，不能仅凭 Shell 名称假定执行路径。受管本地启动契约应提供 `ROTOM_PERMISSION_CONTROL_EXECUTION_ROUTE=local-native-bash-v1`；管理器严格拒绝 ACP、rpc-ui、外部终端和未知模式参数，禁止私人 machine 配置伪造或覆盖该标记。插件还须拒绝带 ACP/未知模式的标记复用。缺少可核实的本地路径时，新扩展 Shell 不自动批准，保留旧 Bash/sh 保守边界；标记变化参与执行指纹并使旧票据失效。
- FR-059：已确认的本地普通 Brush 路径不因非 Bash 的用户启动文件或非 Bash 已知 shellPath 单独转人工，因为这些文件/壳不被此路径执行。Bash snapshot 的既有 startup、继承函数、HOME 和历史缓存保护保留；自定义 Bash snapshot 路径仍人工。前缀、实际 direnv、cwd 不确定、scoped/global 设置不同源、显式原生 prompt/deny 和未知高级参数的门槛不变，审查模型链不变。不得读取/执行秘密环境或启动脚本来制造兼容。
- FR-060：审查材料与 explain/status 输出受控 Shell family、执行路径分类及固定上下文原因码；不输出原始环境、配置目录、任意文件路径或模型自由文本。人工弹窗至少显示转人工的固定原因；有效模型 ask/deny 仍不走复审链。
- FR-061：覆盖 zsh 父终端下标准登录参数与无害 find 管道，验证审查调用、人工计数、原生委托和实际结果；覆盖所有 family/参数的隔离模拟矩阵、标记缺失/伪造模式/改变、Bash startup、未知壳与前缀等反例。固定 SDK strict 与无账号官方宿主 smoke 单列，真实模型预算不增加。未安装的 Shell 或其它 OS 不计作真实环境验证；写入稳定后审查、提交、再快进合入 main，不自动部署活动实例。
