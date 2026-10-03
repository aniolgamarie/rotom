# omp-permission-control

这是 OMP 的独立权限控制插件源码目录。默认入口为 `standalone.ts`，只使用
官方扩展 API 注册 `permission_bash` 工具和 `/permission-control` 命令，不修改、替换或
monkey patch 宿主源码。旧 `index.ts` 及 core 文件只通过 `./legacy` 导出保留历史记录，
不是当前交付入口。

`permission_bash` 覆盖模型发起的 raw non-interactive Bash：它在自身 `execute` 内完成
原生 pattern 下限、模型审查或人工确认，然后调用公开的 `omp.exec("bash",
["--noprofile", "--norc", "-c", command], ...)`。它不改变 command，不读取 shell
startup 或 direnv。服务、后台 job、PTY 和用户直接调用原生 Bash 仍遵循宿主自己的行为；
插件不宣称继承或统一这些路径。插件缺失、配置无效、审查故障、无 UI、取消或会话/模型
变化都会阻止 `permission_bash` 执行，原生 Bash 的 prompt 策略保持可恢复。

插件在 session start/switch/branch 边界从公开 `getAgentDir()/permission-control.json` 读取
schemaVersion 2 的封闭配置；它不监视会话中途的文件变化，也不声称等价于宿主动态 policy、
credential 或版本管理。
插件拒绝未知字段和符号链接。配置包含默认 session-only 模式、主审/远程 fallback、
installed-only tiny 声明、插件与 policy 摘要及原生 patterns。当前公开 API 没有可靠的
installed-only 本地模型查询，因此 tiny 状态固定为 unavailable，不下载也不调用内部 worker。

主审只支持 `anthropic-messages` 和 `openai-completions`，共用 30 秒期限，不重试、不跟随
重定向。只有 transport、unsupported 或严格 JSON 无效才尝试一次不同实际模型的 remote
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
