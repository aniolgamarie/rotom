# Base 扩展公共 SDK 生命周期与观测探针准备

2026-10-09 root，默认准备包，不是执行授权。SDK4加载/注册已获准执行并闭合；其范围没有生命周期/UI/实际session业务。当前公开证据确认 DefaultResourceLoader.getExtensions() 的 LoadExtensionsResult 包含原共享 runtime，公开 ExtensionRunner 可用该原 runtime/原extensions组合，不需要私有import或替换runtime。原证据两次人工读取预算偏离保持，事实仅capture静态，不是实际行为或SourceHold证明。

## 原生实验边界与固定case

新材料只有 footer、loop、todo、combined 四case，分别仅加载install01中真实归档入口，每case独立Node和私有新work。追加一个已声明的自有inline witness factory，用官方公共extension event捕获真实ExtensionContext并计数；它不注册工具、不执行模型/命令、不赋予manager资格。保留SDK4相同自有合成manager标记边界，承认仅为扩展配置读取fixture，不能当作真实owner/许可。候选SDK1.0.1/AI1.0.2/Node24.14.0，不改上游、vendor或安装树。

仅 import 两个官方包根公开export；DefaultResourceLoader/SettingsManager.inMemory限定显式路径，packages空、discovery关闭。ModelRuntime.create 只用官方内存Credential/Models Store、modelsPath:null、allowModelNetwork:false、refreshOnCreate:false，不注册真实账号、不调用getAvailable或模型服务。需要ModelRegistry则用其公开constructor和这个原ModelRuntime；SessionManager.create/open/append 等仅临时根。使用loaded.extensions及loaded.runtime的原对象构造公共ExtensionRunner，并以bindCore、setUIContext和公开emit/emitToolCall/emitToolResult等准确声明方法驱动。不得私有import/createContext或复制模拟上下文替代实际SDK上下文；若需要ctx，通过witness公共callback保留原ctx。

合成UI实现官方ExtensionUIContext声明的完整可表达方法并记录有限callback/render调用；禁止启动TUI、编辑器、Shell、浏览器、Codex、MCP或服务。未知UI/核心动作固定拒绝，不能假装实现业务。该UI只验证官方ctx路由和自有扩展callback，不证明真实TTY/SSH绘制或真人交互。公共session/tool对象不被改写。仅直接调用公开Extension.tools中的Todo定义并使用实际SDK回调ctx，固定合成参数和signal；这不是主模型工具调度证明。

footer case：实际session_start/turn_start/turn_end/shutdown公共事件触发Header/Footer等已定义UI回调，调用取得的真实组件render于固定宽度，固定哨兵秘密不得出现；shutdown后清理自身listener/global token，旧callback不得产生新UI更新。loop case：实际公共session/input/tool-call/result/message/context事件路径，固定无推理重复额度与checkpoint写入；通过公开SessionManager临时文件及fresh open/runner验证重放；不发模型、不执行真实工具、不制造checkpoint TTL。todo case：真实公开tool定义create/update及错误结果，实际SDKctx/session id与临时SessionManager公开persist/reopen接线，session_tree/session_compact/shutdown事件与session分离；原2秒prewarm只允许late import，不能声称取消timer或重新绑定UI。

combined case验证原共享runtime/ctx与三个提供者共存、无重复tool/command，公共错误计数0；并用当前已验收自有official-resources.ts/resource-selection.ts精确只读副本核实际SDK加载观测的id/scope、非加载roles与失败后不返回匹配。该观测只为直接resource闭包，不扩大成尚未实测的runtime facade/session envelope或持久doctor资格。root验收时再决定有限行为证据，不自动写verified/current/accepted。

每case输出关闭schema的固定case/provider/callback事件ID、有限计数/布尔、版本、observed/failed/not-run与固定错误码；不输出路径、正文、任意SDK异常、SDK对象/handler/凭据或其摘要。real stdout/file逐字一致及原材料/完整树首末由外层runner核对；output<=64KiB，guard拒绝无SDK import/marker/mkdir。原生全部未授权，driver与runner可执行守卫均literal false，参数/环境不能打开；不得复用旧SDK4的true守卫或授权记录。

## 唯一写范围和准备验收

执行者仅可写新 .cache/pi-two-profiles/run-20261004/base-provider-sdk-lifecycle-preparation-review01/ 自有driver、精确plan、官方公开结构fixture、fake tests、当前两自有resource模块只读copy及pins；以及该目录内新的runner.py/material-pins默认测试。可将旧SDK4外层executor已校验的自有过程结构作为参考，但创建全新false guards、固定材料/调用路径/case schema并保留原始内容前像；不import旧executor授权入口，不改已授权脚本/flags/旧材料，不改生产代码/锁/provider/其他实例/OMP/state/tasks。与另一个执行者不共享写文件，你不独自工作，不回退他人。

默认使用固定test-pi-mock.mjs脚本跑新目录显式fake .test.mjs和pytest临时HOME/假进程/断网跑runner test；既有允许路径不足需报root，不为测试放开harness。默认可运行仓库自有Node/Python测试，禁止第三方SDK import/native实际probe。先有意义RED，fake公开SDK记录实际参数/共享runtime/捕获ctx/事件/业务与schema验证，guard零调用、case错路径/版本/同数量错集合、事件故障/secret sentinel、超限、首末材料变化、runner收尾未知不签通过；不要重跑旧SDK4/native或全量。SDK源码读取仅精确已知公开类型/方法文件，可一次读并缓存必要小文件，不递归扫描node_modules，不重复hash大SDK/Node树。

如果某case不能通过公开API准确表达或持久reopen需更改宿主调用策略，报告root，不私有补缝；如果scope/流程/来源需要扩大或同失败两种有效修复无解升级root。完成STOP并交稳定diff/pins、默认日志、可审阅命令和执行计划供独立复核；原生必须之后另按AGENTS.md明确授权，本次绝不执行。真实TUI、真实工具调度、账号/模型/账单、Full/controller/SourceHold/整体隔离仍未验证，正式8/100、AUTO OFF。

2026-10-09 root后续决定：根盘/tmp ENOSPC时默认准备使用新包自有0700 TMPDIR（位于/data）和同一断网fake runner的require_escalated路线，原sandbox mount marker环境失败不记测试通过，不删除旧证据/SDK/他人数据。第一实现fake10项9pass/combined1fail须保留；shutdown已退役factory不可与fresh SM复用。重新打开临时SessionManager后，通过同一配置的公共loader.reload创建新一代factory，读取它自己的原getExtensions().runtime/extensions，再构造新runner绑定fresh SM/UI；witness ctx分代，新旧Footer注册/清理分开观察，旧Todo迟到import仍不得复绑UI。只是合成公共生命周期接线，不授予真实mode恢复/SourceHold资格；四case和所有false守卫保持。

2026-10-09 root稳定审查P2决定：Todo直接definition必须来自与实际SDK callback ctx同代的原loaded结果；reopen后的初代tool不得复用。第二个会话需独立公共DefaultResourceLoader取得独立原runtime/extensions/UI，再绑定其SM；不得以同runtime第二次bindCore模拟独立会话。主/子会话各自definition/ctx/core保持绑定，shutdown与迟到UI分别观察。默认fake加入ctx->runtime私有WeakMap与工具definition捕获runtime不符的有效拒绝；仍是原todo-only会话隔离范围，无新case/账号/模型/realmode。首稳定默认driver11/runner11及独立0P1/P2只属前像阶段证据，新差异须验证/复核后才请求新原生授权，全部false守卫保持。
