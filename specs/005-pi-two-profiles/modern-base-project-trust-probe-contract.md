# 当前 Base 项目信任加载：最小探针实现范围

2026-10-08实施结论：实际公开loader两控制已由trust03完成，资源和正文0／1符合原oracle。原冻结的.mjs文件后缀不符合官方默认发现规则，按同边界修复为.js，正文不变、不添加显式路径；原冻结材料和trust01／02失败保留。见[native实际结果](native-modern-base-project-trust-probe.md)，root receipt `40bdbb0bc86c6752d62c50d4dced589b2690e1d9ec929fac22125cadc63cd03c`。下面冻结时间的未写／未执行描述为历史，不改写原设计前像，也不扩大reload资格。

2026-10-08 root实现包定义。公开接口的有限证据见 `modern-base-project-trust-api-evidence-review01/`，与已纠正Q1映射一并接受的11输入receipt为 `24a828dab1258e14a6826c8c7019c2c1a2fe86abf7f2c3dce2e6788e83310835`。本稿冻结下一自有探针的两项正反控制和可写范围；尚未写探针或运行官方SDK，不授予原生执行、产品或来源资格。

输入为 install01 已保存的官方Pi1.0.1／Pi AI1.0.2 Base树，16,653条目，原 inventory SHA `4456d8b746f35694d272a4980021490c5299cb277bf1d497da24eca930f882f3`。SDK6的六个场景已实际观察；旧RPC5使用另一候选，两个缺口分别验收。

## 两个控制

使用包根公开 exports 的 `DefaultResourceLoader`、`SettingsManager.inMemory` 和公开 `reload({resolveProjectTrust})`。两场使用各自全新的临时project、agentDir和合成设置，放入相同的一个project extension、一个skill和一个prompt。不用真实HOME、信任数据库、凭据或模型，不创建ModelRuntime、会话或工具执行。

公开声明及security文档的独立有限复核无P1/P2。固定fixture位置为project内的`.pi/extensions/project-trust-fixture.mjs`、`.pi/skills/project-trust-fixture/SKILL.md`及`.pi/prompts/project-trust-fixture.md`；agentDir不放额外资源。每场新建`SettingsManager.inMemory`，不传`projectTrusted`，全局`defaultProjectTrust`明确为`ask`，以实际reload回调决定本场。不能沿用SDK6预设的`projectTrusted:false`而绕过本次回调，也不预写saved trust。Getter只通过公开`getExtensions`／`getSkills`／`getPrompts`取实际结果。

1. `deny-project-resources`：本次自有受信resolver明确返回false；protected project extension／skill／prompt均不进入公开资源集合，extension factory的自有标记正文零次。project extension内即使声明一个返回yes的`project_trust` handler，也不能靠自身代码被加载来推翻拒绝。若实际SDK不满足该前提，报告失败而不改oracle。
2. `allow-project-resources`：独立受信resolver明确返回true；精确三个project资源加载，extension factory的固定标记恰一次，错误为0。它是相同fixture的正控制，排除拒绝场景只是路径错误或未发现资源。

resolver调用次数和回调来源按实际公开路径记录；若公开设置导致resolver不调用，保留这一实际失败或限制，再由root决定能否在同公开接口下调整准备。不能直接把固定布尔写到报告来替代实际集合和正文计数。资源输出只保存固定case ID、数量、预先固定的资源名称、允许／拒绝与错误计数；不保存原SDK异常或项目正文。extension标记只能写自己的临时case目录，不能触碰业务根。

本包只证明公开loader的reload信任控制。CLI首次启动、扩展信任事件的优先级、saved trust继承及print／JSON／RPC默认ask行为不从这两场推定；仍按它们各自真实入口验收。官方文档说明context文件及project sessionDir有不同读取时点，两场protected资源断言不包含这些类别。项目加载信任与工具沙箱分别判断。

2026-10-08实施更新：本稿冻结时尚未写探针；现自有driver／fixtures及外层Python执行器已稳定准备，具体材料、跨轮默认23＋11覆盖及资格边界见[native-modern-base-project-trust-probe.md](native-modern-base-project-trust-probe.md)。root完成写后审查；新实现独立子代理审查因agent thread limit不可用，公开契约的既有scout审查仍仅是契约证据。两个原生守卫false，官方SDK未加载，本稿不授予原生执行。

## 实现与默认验证边界

唯一实现目录为新独占 `.cache/pi-two-profiles/run-20261004/modern-base-project-trust-probe-preparation-review01/`，包括自有driver.mjs、有限fixture、只读输入pins、准备计划、默认fake测试和说明；不修改正式源码、既有SDK6、上游包、默认入口、profile或锁。driver的原生守卫固定false，并在任何官方SDK动态import、临时目录、标记或模型接口之前拒绝。不能用参数、环境或消息绕过守卫；未来开启须用户针对稳定材料明确授权。

默认验证只运行自有driver纯逻辑及fake公开loader：守卫拒绝零SDK／目录／模型调用；相同fixture正负控制、缺失marker、错误集合、重复正文、foreign／未知结果及坏版本保持失败；成功状态不能由exit0单独推定。所有这些是默认组件测试，不能登记为官方SDK observed。

外层Python对固定fixture、实际marker和结果执行本次固定字节上限、原目录FD逐段nofollow、末级身份核、严格JSON及失败保留；可复用已接受的仓库自有边界，不复制未闭合的reader。Node没有公开的逐级dir_fd接口，本包不要求或宣称它具备该能力。driver只通过公开fs观察自己的全新0700 case目录下固定marker，使用小字节上限、末级nofollow、regular／single-link及前后原fd身份检查；不读宿主业务或共享目录。项目extension的固定正文只能在该case写固定marker，实际marker由外层Python再次有界读取并与driver报告核对，零次／一次断言不能只由报告布尔推定。该组合不签任意敌对文件系统或原目录持续sourcehold。

原生runner另由root准备与审查：bwrap断网，固定官方树、driver、fixture及Node单文件只读，只有新私有work可写；不启动Pi TUI／Codex／MCP，不读账号或联网／部署。沿用已接受SDK6的整个树有界前后核对和work永远保留原则，但不得继承它已闭合的原生授权。稳定材料、具体命令、有限截止和失败路径就绪后再请求授权。

生产原binding、SourceHold、FullSourceView、controller、初始化或DB都不在此包；不使用私有API、宿主monkey patch、输出文字推断授权或补丁上游。发生公开接口前提被推翻、需新增场景／源或两次有效尝试仍失败时交root重新决策。T006、正式7/100及产品gate保持未完成，严格计量前AUTO OFF。
