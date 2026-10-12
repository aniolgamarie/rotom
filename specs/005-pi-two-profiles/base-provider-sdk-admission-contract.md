# Base 本地提供者的公开 SDK 加载／注册契约

2026-10-08 root 实现包。T006已完成当前Linux隔离候选Q1；三个本地提供者的Pi1.0.1支持仍为candidate。入口及副作用有界证据在`current-base-local-provider-api-evidence-review01/`和`current-base-provider-sideeffects-evidence-review01/`，已接受的next boundary receipt为`2f377752192c6e7219854aaae938f5532023e8908ec35324c84719e66eadad8c`。

本包先实现可执行的加载／注册验证，独立于正式状态转换。成功不写`verified_host_versions`、不发布current／accepted、不安装或部署；生命周期、UI、checkpoint／重放和Todo业务行为另有后续功能控制，不能由此四场推定。

## 四个固定场景

从当前install01只读包中选取真实归档的入口，不从工作区活源码或字符串合成替代。三个provider为`rotom-footer-v1`、`rotom-loop-guard-v1`、`rotom-todo-v1`，入口分别在`node_modules/starter-pi-colorful-footer/index.ts`、`node_modules/starter-pi-loop-guard/index.ts`、`node_modules/@juicesharp/rpiv-todo/index.ts`。四场各独立Node进程和临时case root：footer-only、loop-only、todo-only、combined。

仅用官方包根公开`DefaultResourceLoader`及`SettingsManager.inMemory`，关闭自动extension／skill／prompt／theme／context发现，packages为空，只传该case明确选定的additional extension路径。不创建会话／ModelRuntime、不发prompt、不执行工具或命令、不加载真实账号。对公开`getExtensions()`返回的公开`Extension`类型，观察path、commands、tools、handlers、shortcuts及renderer keys；不得访问私有runner、伪造getter集合或输出文件内容／异常原文。

固定期望：footer有`colorful-footer`与`ui-calm`命令，无工具，含session_start／turn_start／turn_end／session_shutdown；loop有`loop-guard`命令，无工具，含session_start／session_tree／input／tool_call／tool_result／message_end／context；todo有`todos`命令和`todo`工具，含session_start／session_compact／session_tree／session_shutdown／tool_execution_end／agent_start。其他公开注册项按真实固定入口列为明确有限允许集合，不自行猜测忽略；集合差异保留实际失败再由root决定。所有case必须真实loader errors0、预定入口全部出现且没有未选资源；combined不能重复单owner工具／命令。

单场采用自有临时cwd和agentDir。只为仓库自有扩展读取的`Symbol.for("agentcfg.pi.runtime.v1")`提供明确合成fixture，owner role为manager、manifest plugins为本case所选本地能力，options仅固定loop_guard默认设置与todo的locale=en/collapseKey=off，instanceRoot为本case root。此标记只为自有helper配置读接口，不改任何官方SDK对象／原型，也不构成真实manager、SourceHold、授权、预算或initializer资格。不得把合成标记写成正式身份或接受证明。

## 默认实现与验证

唯一可写新目录`.cache/pi-two-profiles/run-20261004/base-provider-sdk-admission-preparation-review01/`，包含driver.mjs、自有场景plan、fake SDK tests、源材料pins及报告。原始SDK／第三方／安装树／生产配置、锁、声明、默认入口不修改。原生guard字面false，在官方SDK import、case目录及合成marker安装前拒绝，参数／环境不能绕过。

默认仅运行自有纯函数和fake公开loader，验证四case选集、实际getter集合检查、错误／缺项／多项／重复owner／错误版本失败，guard零SDK／mkdir／model调用。fake成功结果只能标default，不标官方SDK observed。使用临时HOME和网络阻断，不执行SDK／Pi／Codex／MCP或外部命令。先真实red再修复受影响green，保留失败日志及即时前像；测试不重复已有SDK6／RPC5／trust2或全部23用例。

结果只含固定case／provider IDs、公开名称列表与计数、实际SDK版本、错误计数和有限固定错误码。字段／类型／数量均有限，未知字段或外来getter拒绝；不得保存原SDK异常、path或项目／模型正文。诊断允许null表示某项尚未测得，不能合成observed。单case soft20秒，外层未来独立runner沿已接受SDK工具／整树有界核对、断网bwrap／固定Node只读／新私有work全部保留；runner和真实材料由root另准备与稳定审查。

## 后续边界

首次原生四场属于新的组合，旧三套授权已经满足并闭合，本包不继承它们。待脚本／固定inputs／oracle／隔离命令完成后按AGENTS.md独立请求具体授权；这不阻止现在默认实现及Base状态转换设计。公开接口前提推翻、需新增资源／真实配置／流程，或两次有效尝试仍失败时交root决策。保持正式8/100、产品gate未通过、AUTO OFF。
