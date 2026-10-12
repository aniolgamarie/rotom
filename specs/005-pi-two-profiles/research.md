# 研究依据、决定与有界验证

日期：2026-10-04。区分资料事实、设计决定和实施假设；上游main不是发行承诺，运行结论以正式锁定版本和目标平台证据为准。

## D01 产品与执行保护分离

决定：Base/Full定义产品能力；审批与隔离独立选择。Base无高级包或默认review，Full普通使用不隐式启动高级系统。
理由：兼顾低开销、共享维护与高级能力。替代方案“Full关几个开关就是Base”不保证冷安装和隐式资源隔离；另写两套配置会漂移。复用 `src/agentcfg/pi_vendor.py` 的独立source_ids/slice与资源清单。

## D02 默认无沙箱，公开扩展不形成插件隔离

事实：[Pi安全文档](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/security.md)说明默认使用启动账户权限，扩展处于同进程。项目trust不限制所有工具访问。
决定：受管工具模式信任宿主/已选扩展；恶意扩展保护由整进程外部边界承担。不把cwd、工具名称或只读角色当沙箱。
验证：Q1核对正式包的工具/嵌套工具、加载顺序、RPC和reload。只用公开注册/operations，不用原型替换、私有模块或源码补丁。

## D03 沙箱由开发场景与负向事实共同选型

事实：`pi_commands.py`/`pi_checks.py`已对固定命令使用bwrap/sandbox-exec；任意Shell受ORDINARY_COMMAND_UNBOUND限制。验收sandbox不能充当产品；PID命名空间主要解决进程收束。
决定：复用策略和生命周期经验，Q2验证可组合Shell及文件保护，不退化为逐命令预注册。
候选：现有OS封装；[独立Sandbox Runtime](https://github.com/anthropic-experimental/sandbox-runtime)；既有整环境隔离。只比较相关候选，核对许可证、维护、依赖、安装副作用和退出方式；该runtime标为研究预览，不能当作安全认证。
验证：文件/网络/socket/env/后代、失败不降级、缓存/增量构建/Neovim/终端。每个必需平台独立实测，生成policy不算OS事实。

## D04 整进程隔离必须形成结论，不自造云平台

事实：[Pi隔离说明](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/containerization.md)区分整进程与工具隔离；工具VM不覆盖其他扩展。
决定：Q3用可获得且维护中的容器/VM验证。若认证/体验/平台不满足，记录准确限制；受管工具与整进程模式分别验收。若已冻结为必需能力，不支持结论不能替代通过。
替代：自建通用安全内核、刷新代理、远程网关超出职责。挂载全部HOME/认证并开放网络不满足凭据保护；保持受支持的原生登录和所有权，不复制token。

## D05 模型审批只参与需要判断的操作

事实：[Codex Auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review)保留边界，由独立reviewer判断；不保证每次正确。[Pi扩展文档](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/extensions.md)提供tool_call和嵌套模型入口。
决定：可选本地扩展，硬规则先行，单次请求、明确路线/模型、严格结果、取消/失效、无UI退路；无自动换模型或等价重审。已授权编辑/测试不简单按write/bash归为必须人工。
复用：`specs/004-omp-permission-control/standalone-plugin.md`的协议/边界，不能复用退休宿主桥。历史评测中位约4.1秒且82次有3次格式失败，只说明需单独评测，不是Pi结果。
验证：冻结样本+保留集，分别记规则、模型、协议故障和最终执行。仓库/工具输出不是授权来源；共享模型服务不意味着共享认证写入权。

## D06 统一委派核心与有限工作流

事实：model-delegate已有核心但主要为review/investigate；TK走SubagentsAdapter。不能靠删除UNMETERED_EXTERNAL_DELEGATE完成整合。
决定：核心拥有执行事实，TK拥有阶段与验收；Pi/Codex按能力协商。Writer仅在真实准入/生命周期/停止可证明后开放，租约跨profile。
验证：Q4真实公开协议，mock与native不混。Pi调用provider与官方Codex CLI分别列模型/账号/参数。无公开暂停审批通道时不抓屏代答，不能执行就明确报告。

## D07 Durable只读任务为Full必需

事实：[Pi Durable](https://raw.githubusercontent.com/earendil-works/pi/main/packages/durable/README.md)为实验性组件；安全重放、取消等待与停止任务语义不同。
决定：单服务/单存储，稳定requestId，状态/消息/取消/结果；只读工具和私有产物；TK、delegate与Durable不抢恢复权。
验证：Q5固定存储/registry版本；commit/派发/应答窗口、冲突ID、取消、模型未知结果和预算不清零。读取可重放不意味着所有模型调用可重发。

## D08 验收绑定输入与检查器

决定：检查器在Worker写边界之外；检查计划、源码/未跟踪输入、配置、依赖、权限、检查器版本共同标识证据。进程结束、测试语义、物理终止和人工接受分别记录。
替代：只看HEAD、exit0、Worker打印passed或模型总结不足。大仓库使用冻结的相关输入闭包与明确排除规则；闭包无法确定则扩大校验或标stale，不默认全库索引。

## D09 持续工作靠恢复记录与有限重试

决定：plan.md唯一动态主入口，tasks.md工作分解，acceptance.md检查定义；运行器产出事实，避免多份手填结果。unknown先对账；两种有效尝试无进展交主代理。
Stop hook仅可选、公开、用户信任；不作产品门槛。尊重停止和环境限制，不承诺CLI进程永不结束。

## D10 维护与质量

决定：不按工期删必需目标，按职责消除无收益复杂度。固定版本完成周期，后续候选更新带完整锁、故障测试、兼容矩阵、恢复。数据迁移另验，配置rollback不等于数据恢复。
性能/质量阈值在候选结果之前冻结；保留失败及变更理由。有限零错误样本不等于安全证明，硬边界也需真实系统测试。

## D11 插件选型状态与未来替换

用户于本轮明确指出Pi插件市场不稳定，要求保留替换空间。决定：将R37可替换性作为产品要求，具体包是能力提供者；复用当前清单与各能力适配器，不建设通用插件框架。提供者变化要验证用户行为、权限、身份及维护契约，不能把更改包名视作替换完成。

以下是specify阶段的方向记录；本轮plan的初始选择以D12–D15为准，仍不是已验收安装清单。现有 `pi-default` 锁（Pi 0.84.4）是调查基线；不表示新Base/Full目标已经冻结，更不表示这些组件天然兼容。正式来源和完整锁在T002/T006及各集成阶段决定，不能从表中直接生成安装指令。

| 能力 | 已确定的方向 | 尚未冻结或必须验证 |
|---|---|---|
| Pi宿主及基础搜索/编辑 | 未修改的正式上游；优先恢复/适配原生日常能力 | 正式目标版本、公开接口覆盖及是否还需特定增强插件，T006/T019 |
| 压缩、会话、分支/交接 | 仅一个自动压缩所有者，恢复保留用户约束与任务引用 | 原生能力与压缩插件的具体保留/退出名单、格式兼容，T023 |
| MCP / Code Mode | 按需加载、认证/资源/取消及内层错误正确传播 | 最终实现提供者及兼容版本，不预定必须升级某个市场包，T024 |
| 普通长命令 | 复用现有processes相关适配，提供可观察与可停止的日常命令 | 最终processes提供者、版本与隔离整合，T020/T033 |
| model-delegate | 统一Pi/Codex调用入口与两种执行后端，保留同一执行核心 | 公开协议实证、正式依赖及写任务生命周期，T016、T060–T066 |
| Task Keeper | Inspect/Fix使用统一delegate；退出重复委派权威状态 | 替换现有SubagentsAdapter连接方式并验可信准入，不以删除保护完成，T069–T075 |
| 持久只读任务 | Full必需；单服务/单存储所有者、独立恢复职责 | Durable正式可用组合、存储/registry、认证及恢复兼容，T079、T083–T084、T087–T092 |
| 模型风险审批 | Full可选启用的独立本地扩展；复用成熟约束，不复用宿主补丁 | `risk-review`仅拟议包名，最终传输/模型路线/公开接入与真实质量，T049、T051–T057 |
| 受管工具隔离 | 当前Linux实际隔离必需，后端不可用不降级 | 现有OS封装、独立Sandbox Runtime或既有整环境等候选经Q2比较后选定；不是都装，T033/T034 |
| 整进程隔离 | Q3必须得出实证结论，支持声明与受管工具隔离分开 | 具体容器/VM路径、账号与终端可用性；未选定提供者，T039 |
| 主题、状态显示及领域Skill | 低干扰终端与共享工程知识保留，Full调度知识独立 | 当前各资源逐项保留/替换/退出清单，不能按插件类别整批认定通过，T002/T025/T026 |

选型记录最少包含能力、当前/候选提供者、来源及固定版本、宿主兼容条件、重复注册/单owner冲突、配置和状态归属、维护与许可证判断、验证结果、卸载残留与迁移回退。能力缺失或不兼容明确失败，不将市场弃维护事件当作自动换源授权。

测试先以同一能力的正常、拒绝、取消、故障场景约束原提供者与候选，再验替换中断和恢复。至少一组等价替换及失败恢复纳入M07；替身验证替换机制，真实组合另验。旧活动任务和恢复引用保留原身份，状态不兼容时阻塞或走已验证迁移，相关旧证据stale。维护仅保留必要旧引用，不因此建立第三条长期产品线。

## D12 本轮初始提供者选择

**决定**：把官方Pi v1.0.1系列作为首轮升级候选，保留Node v24.14.0工具链；宿主入口依据官方包的bin/exports重建。标签包清单的CLI bin为`dist/bundle/cli.js`，`dist/index.js`仍是公开模块入口，不能将两者混用；正式tarball仍须核验。主机日常工具、压缩、MCP/Code Mode优先原生。Full选择统一delegate、TK、持久服务和可选审批；独立subagents调度器不进入新默认组合。

**理由**：官方标签的宿主依赖包含MCP/Code Mode，公开扩展文档提供嵌套工具事件、模型调用和MCP注册；能减少重复提供者。当前仓库0.84.4加旧扩展不是等价基线，仍须做兼容和加载验证。[宿主v1.0.1包清单](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/coding-agent/package.json)、[公开扩展接口](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/coding-agent/docs/extensions.md)、[原生MCP说明](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/coding-agent/docs/mcp.md)。这是规划选型，不是“最新版”或通过声明。

**替代与触发**：若正式包接口/行为未达Q1，优先适配其公开接口；确有缺口才记录重选版本，不能默默回到带私有接缝的旧组合。旧0.84.4仅保留已存在实例及恢复引用。无需仅为市场有新版本就重选已冻结组合。

本地事实：旧pi-default slice有24个source ID，但profile只选6个plugin。`agents/pi/runtime/resource-loader.ts`根据资源manifest选实际注册项，安装与加载需分别核对。旧`pi-permissions`不仅在catalog依赖subagents，入口还创建子任务检测并监听生命周期事件；`openai-proxy`是网络路由扩展而非provider注册器。依据`agents/pi/dependencies.json`、`agents/pi/plugins.toml`、`profiles/pi-default.toml`及对应包入口。

| 当前source / 当前版本 | 新组合的初始选择 | 原因与验证责任 |
|---|---|---|
| pi-host / 0.84.4 | Base+Full候选升级官方1.0.1 | 以正式包公开入口/API为准，T006核对完整锁与Q1 |
| pi-runtime / 1.0.0 | 两者保留并适配新宿主 | 本仓库代码身份随实现固定，不带旧私有宿主入口 |
| pi-permissions / 29.3.0-agentcfg.1 | 两者退出旧整包；用仓库独立权限扩展接现有策略/监督核心 | 真实subagents事件耦合不能只删requires；只复用已证实公开、许可允许的接口或规则语义，不导入私有内部模块 |
| session-yolo / 0.1.0 | 两者退出 | 避免第二权限模式入口，审批模式由统一策略管理 |
| pi-subagents / 0.19.0-agentcfg.1 | 两者退出独立调度器 | Full角色协作由model-delegate承接；既有能力迁移后验收，不双队列 |
| model-delegate / 0.2.0-agentcfg.1 | Full必需，继续仓库核心 | 两宿主/两后端及Writer生命周期；Base不安装 |
| task-keeper / 0.2.0-agentcfg.1 | Full必需，替换SubagentsAdapter连接 | 固定Inspect/Fix和可信准入，不能只删除拦截器 |
| pi-smart-compact / 9.6.0-agentcfg.1 | 两者退出默认包，选原生压缩 | 一个owner，恢复上下文约束仍须实际验证 |
| pi-mcp / 2.32.1-agentcfg.1 | 两者用原生MCP/Code Mode替换旧适配包 | 原生服务器发现/配置优先级、取消、错误与权限按T024验；不携带catalog的subagents依赖 |
| pi-processes / 0.11.1-agentcfg.1 | 以现有ProcessManager为首选复用候选，两者普通命令需独立适配 | 观察到catalog耦合，未证明可直接删依赖；工具必须接同一监督/隔离，不能保留裸spawn旁路。若不可拆，直接复用仓库命令监督实现相同行为 |
| pi-todo / 2.9.0-agentcfg.1 | 两者轻量任务显示候选 | 保持会话分支恢复；不是TK或Durable权威队列，Q1/性能门槛不满足可用原生展示替代 |
| colorful-footer / 0.1.0 | 两者保留低干扰显示并适配 | 不启动模型/服务，真实状态而非自造结果 |
| loop-guard / 0.1.0 | 两者保留无推理循环提醒，验冲突 | 提醒不变成自主继续/重试所有者 |
| pi-rules / 0.6.0-agentcfg.1 | 两者退出默认注入器 | 共享短规则+原生项目规则+按需领域Skill；保留知识与优先级语义 |
| openspec / 1.11.0-agentcfg.1；superpowers / 6.3.0-agentcfg.1 | 不进入两者全局默认套装 | 项目按需选流程；共享领域知识保留，Full调度Skill独立，避免叠加主管 |
| openai-proxy / 0.2.0 | 两者退出当前全局fetch包装 | 全局行为替换有宪章VI风险，路线需求改用官方原生配置或公开Provider适配；既有国内路线不因此删目标，认证/网络路径另验 |
| pi-btw / 0.55.3-agentcfg.1；pi-slopchop / 0.10.1-agentcfg.1 | 两者初始不装，保留后续可选入口 | 用原生会话/终端diff先满足场景，不以它们作为必需协作依赖 |
| pi-readseek / 0.9.16-agentcfg.1及视觉模型/projector资产 | 两者初始不装 | 原生范围搜索为必需路径；不自动索引/下载约1.55GB资产，额外语义/视觉搜索按需独立选型 |
| pi-web / 0.27.0-agentcfg.1 | 两者初始不装该包，外部工具按需 | 既有工具需要通过选定原生MCP/公开扩展接入及权限验证，不默认浏览器服务 |
| pi-cursor / 1.4.29 | 不进入新两profile | 独立旧profile保留恢复边界；Cursor不在首批必需后端，不引入Bun特化 |
| 官方Codex资产 / rust-v0.154.0 | Full首批必需后端，执行按需 | 复用已锁Linux资产基线核对公开协议；不是给Base安装Codex |
| codex-bwrap及Code Mode/proxy平台资产 | 不作为Base隔离或原生Code Mode依赖 | Codex声明需要的资源只跟Full后端安装；Base使用独立受管系统bwrap，不借用私有Codex实现 |
| risk-review / 尚未实现 | Full拟新增仓库独立扩展 | 无市场包前提，公共Pi模型接口、单次审查，默认为关闭 |
| durable-service / 尚未实现 | Full拟新增服务，SDK初始候选1.0.1 | 版本/API实验性通过边界隔离，不向主工作流暴露私有对象 |

表中旧版本是精确调查基线，不能作为升级后版本或兼容证据。第三方包复用前核对维护、许可证、正式宿主peer和原生入口；源文件没有直接import并不证明无运行依赖。当前实际加载、候选初始清单、最终通过清单分别保存，安装树与注册集合分别验收。

## D13 Durable存储、模型发送与恢复

**决定**：选择官方`@earendil-works/pi-durable@1.0.1`独立服务及SQLite。服务以本地Unix socket连接、单owner持有存储，显式固定registry和受限工具；不注册完整CodingTools，不在工作中热换registry。公共接口隔离在[服务契约](contracts/durable-service.md)。

**依据与理由**：官方标签提供该包及SQLite入口，文档标记实验性；内存backend不满足持久需求。自动resume与提交/等待可能推进工作，因此只读查询不能走wait。[Durable包清单](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/durable/package.json)、[Durable公开说明](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/durable/README.md)。

默认SQLite设置不能直接当强持久承诺。main的公开`openNodeSqliteDatabase`/`NodeSqliteDatabase.exec`与`SqliteStorage.open`给出可配置适配路径，先设置并核实WAL/FULL后再开放副作用；正式1.0.1包需核对对应exports。[Node适配源码](https://raw.githubusercontent.com/earendil-works/pi/main/packages/durable/src/storage/sqlite/node.ts)、[公开SQLite入口](https://raw.githubusercontent.com/earendil-works/pi/main/packages/durable/src/storage/sqlite/index.ts)。不访问私有database字段，不修改SDK。

**替代与触发**：若发行包不支持该公开组合，优先按公开SqliteDatabase/Storage契约提供仓库适配；JSONL仅在其公开fsync能力及恢复验收通过后作替代；MemoryStorage仅用于测试。没有能满足身份、持久化和未知请求限制的公开路径时，Q5保持阻断，由主代理重选，不伪称Full完成。

**恢复决定**：SDK任务恢复与外部模型付费重放分别判断。通过公开模型适配统一发送准入，先持久保留预算及sending事实，未知发送阻止自动重发；固定发行包的具体接缝为注入的 `Models`，不是一个名为 Provider 的导出类。正常重启能恢复已确认的任务；未知调用显示blocked并保留预留。凭据只按用户已获准的原生路线解析，不复制主会话token；新服务认证未验不算通过。TK SQLite、执行文件记录和Durable数据库各自只掌握本领域权威状态。

2026-10-06 Q5 固定发行材料增量：从官方 npm registry 获取已选择的 `@earendil-works/pi-durable@1.0.1` metadata 与发行归档，核对发布身份及 SHA512 SRI。归档为 474225 字节，SHA256 `c4bc1ea49653ee972045a5de755756b633e3be0e1528ae32f5f32d82e012db7d`，发布 `gitHead` 为 `a7229ddc21810d6245105978033b7df645ecc2f7`；243 个普通文件有独立字节摘要并逐项复核。候选位于私有 cache 的 `candidates/pi-durable-1.0.1/`，原 metadata、归档、取得脚本及 root 核对记录保存在 `run-20261004/pi-durable-fixed-published-source/`。仅取得和读取公开文件，没有安装、导入、执行、构建 SDK 或读取账号；公开 API、SQLite WAL/FULL、发送覆盖、恢复及真实服务资格仍在静态核对和后续验收范围，T078 未完成。

固定发行包的 21 个 API/实现文件及 2 个项目输入摘要经 root 核对，静态报告保存在 `pi-durable-public-api-evidence/`。实际公开发送接缝名为注入的 `HarnessOptions.models: Models`，没有独立 `Provider` 导出；所见 generation、compaction 及 deferred 路径调用 `streamSimple`、`completeSimple`、`fetchDeferred`、`cancelDeferred`。这些方法参数没有直接包含 task/conversation/phase/attempt，身份承接需继续定点核对，不能用可变全局“当前任务”或未匹配发送冒充计量。默认 durable 重试 3 次，需要显式关闭并另验下层 Provider 路径。

root 已决定 SQLite 使用公开 `openNodeSqliteDatabase` 返回的 facade，显式执行 FULL 并通过 `get` 读回 journal/synchronous，再交给公开 `SqliteStorage.open`；内置 helper 的 WAL/NORMAL 不作 FULL 证据，后续仍需运行观察及故障测试。已打开服务的公开 inspect/getTask/status/watch 可用于只读查询，但 `Harness.open` 本身会将 running 改为 pending 并排队 reconcile，所以不为查询启动或打开 Harness，启动恢复准入放在它之前。包的 MIT 声明存在，发行归档无 LICENSE/NOTICE 正文，正式 Full 来源还需要明确补充分发。上述均是静态事实和实施决定，T078、存储/发送/恢复及产品 gate 未通过。

后续 6 个固定 hook 源摘要确认 generation hook 返回的数组在 Models 调用前浅复制，compaction 新建请求对象，deferred poll/cancel 缺 `beforeRequest`；不能用 hook 数组 WeakMap 或可变全局任务补齐身份。SubmissionId 与 generation TaskId 分开，提交返回时序未作运行证明。实际 Base Chord 1.0.2 归档/SRI 及五个 regular 条目与安装字节一致，结合 durable 的 withoutAbortSignal/withAbortSignal 构造链，20 个固定摘要支持 generation/compaction hook 的公开 Context.abortSignal 与 Models options.signal 静态为同一对象；一般嵌套 Context 或恢复后的新 invocation 不继承这个对象身份。15 个 pi-ai 文件的公开协议/SSE/retry 静态材料另存：streamSimple 同步返回流，完整异步 gate 必须保持此协议；所见内建 DeepSeek 普通 SSE 无 deferred，maxRetries=0 仅关闭所见两层重试配置，不证明真实网络资格。普通 hook 错误被 SDK 捕获后继续，身份组件必须退役并在 Models 侧另验，见[身份决定](durable-call-identity.md)。

存储组合补入受信 `closeContext`：公开 storage.close 需要它，清理沿用公开 storage 队列的读取收尾，不绕过该层直接关闭底层 handle。惰性、单次初始化及 WAL/FULL 两次读回已通过 101 项 fake SDK 测试和稳定独立复审；最终环境为既有临时 HOME/XDG、bwrap 断网、网络/子进程守卫。通用 Object/Function prototype 方法误认及派生错误 descriptor 污染的真实失败均已修复，历史记录保留，不累加测试数。真实 Context/SQLite/owner、持久发送/恢复及 Full 尚未验收，决定见[组合边界](durable-storage-composition.md)，归档 `durable-public-storage-composition/`。身份组件最初74项，新增消费后原身份/current signal复核后最终82项默认检查及稳定复审通过；它不授予发送权。独立[存储决定](durable-model-attempt-store.md)的非发送attempt账本已通过76项自有SQLite默认隔离测试及稳定复审，永久墓碑/累计BigInt预算、lostack发送unknown与既存损坏不重建均闭合；不算官方adapter或T085整体通过。[Models派发](durable-model-dispatch.md)最终119项默认检查及稳定复审通过；两次失败审查、真实旧源12项与6项失败分别保留，不累加旧绿测试。公开终态立即resolve、complete原receiver以及persist await之后publication前重验已纳入组合；真实网络/owner/严格输入资格仍未验收。

受理关联的25份、公开Task/Doc的20份和Storage/Db的16份选定静态来源分别归档。普通Conversation.submit仅按会话和类型去重，返回SubmissionId；LiveDoc当前run和continuation task不能证明永久原任务。root因此选择自有session singleton Doc与自有RootTask的同一公开Session.commit，不增加另一SQL受理表或Db事务拦截。文档只保存完整输入和原ID/receipt，执行状态仍读SDK权威任务；丢回执后只非创建snapshot并精确getTask，不自动重新提交。公开Chord.copyJson用于可信Tx Draft提取，业务Proxy/getter仍在提取之前拒绝。初始化旧哨兵反例由公开initial本次调用标记与外部snapshot共同拒绝；callback内嵌套snapshot可能排队死锁，不使用。边界见[受理决定](durable-request-admission.md)，有限组件最终69项自有默认隔离检查、独立稳定复审及root验收通过；缓存初始化绕过close/authority/method漂移的真实旧65 pass/4 fail已修复，原阶段绿/红及source保留。必填opaque Context使用原引用，未知ack封闭新submit，查询不推导可以重提。不算原生同批、owner、崩溃恢复或T083资格。

18份readonly registry选定来源已另归档；空registry不自动安装CodingTools，但跨extension同名可覆盖，safe重放跳过beforeTool/参数处理，工具报错后generation可继续。首批自有工具replay unsafe，execute独立核验可信原任务、registry、读根和当前准入；公开数字ID/callId不授予权限。见[registry决定](durable-readonly-registry.md)，真实受限IO尚未验收。

## D14 Linux隔离首选及整进程实验

**决定**：首选独立系统Bubblewrap，经仓库现有监督与policy构造封装支持可组合Shell。最小挂载包括只读运行时与显式资源、授权工作区写区、受限临时/缓存目录；默认禁网，不挂管理端/凭据目录和未获准socket。按操作请求明确网络能力，不能默认读挂载整个HOME或根目录来换取“兼容”。[Bubblewrap官方说明](https://github.com/containers/bubblewrap/blob/main/README.md)。

**理由**：复用已存在产品路径，范围可观察，不新增内核安全机制。系统可执行文件身份和版本在部署/doctor可核对；Base不依赖Codex带的bwrap资源。

**替代与触发**：目标Linux userns/挂载/网络能力不满足或允许/越界对照及开发场景失败，先明确unavailable，再评估独立sandbox-runtime或已有容器；不得运行时偷偷切换。网络禁用仍须检查本地socket、环境泄漏和后代，不把namespace创建成功当安全验收。

**整进程选择**：Q3先验证目标Linux可用的标准Docker受限容器路径（独立原生Pi home、最小工作区挂载、非特权用户、不开宿主docker socket），原生登录在隔离账号目录完成，不复制宿主token。Docker Sandboxes作为次选，先核对Linux支持、认证与外部依赖；不因其官方示例存在就选择安装或假定本机可用。自建认证代理排除。Gondolin属于工具VM候选，不能作为整进程扩展隔离的证明。[Pi官方容器化说明](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/containerization.md)。

整进程候选在本机未安装或未获准真实登录时保持未测；只在完成实际调查后得出有证据的支持/限制结论，不把环境缺失写成技术不支持。

标准容器不承诺对容器内恶意扩展隐藏同进程可访问的原生认证。若某项支持声明要求真实凭据始终留宿主，该候选不能通过该声明，须验证有该边界的既有产品或保留不支持；不能自行补一个token刷新代理填平差异。

## D15 协调存储与非Git工作区

**决定**：保留`src/agentcfg/activity.py`的执行记录与`workspace_leases.py`的Git目录inode锁，不因为插件替换重建通用事务引擎。TK已有`node:sqlite`存储、WAL/FULL和同步事务，继续管理其步骤、预算及接受；它不能取代跨profile执行租约。

**理由**：现有Git工作树身份、持久占用及终止证据已有适配基础，重写会扩大风险；但代码明确拒绝非Git根，不能误称覆盖所有Shell/Neovim场景。

**非Git选择**：扩展显式受管根登记，绑定真实目录文件系统身份及与profile HOME无关的本机协调锚；未知/未登记根拒绝写入，不自动git init、不绕过锁。登记、跨profile锚一致、目录别名和根被替换都需独立双进程正反检查，再开放写能力。

**替代与触发**：不为每个profile各建独立Writer数据库。若文件系统不能提供所需跨进程互斥或根身份不可靠，该根保持unsupported/blocked，不能放宽排他承诺。跨进程事务两种有效修复仍失败时交主代理选择新机制，不能由子任务私改语义。

## D16 迁移来源基线与本次升级差量

**事实与范围**：宪章中的starter来源条款对应既有Pi迁移；本次在agentcfg现有Pi之上升级。001的 [初始来源调查](../001-unify-pi-capabilities/source-inventory.md) 明言不是完整逐文件清单；其 [T016/T103](../001-unify-pi-capabilities/tasks.md) 和 [关闭报告](../../docs/acceptance/pi-spec-closure-20260924/README.md) 已记录最终资源映射与修订范围。复用这些来源事实，不重开001、不修改starter、不把旧通过外推为新profile通过。

**基线与差量责任**：T002以 [resource-manifest.json](../../agents/pi/migration/resource-manifest.json)、[capabilities.toml](../../agents/pi/migration/capabilities.toml)、[local-plugins-manifest.json](../../agents/pi/migration/local-plugins-manifest.json)、[preset-manifest.json](../../agents/pi/migration/preset-manifest.json)、[role-map.json](../../agents/pi/migration/role-map.json) 及各能力关联清单为来源到目标基线，核对当前源码、声明与内容身份。每个既有或新增资源记录来源、目标、Base/Full选择、保留/替代/排除理由和受影响的验收入口；未变项可以引用基线，不能用包数量或初始调查代替逐项处置。

| 资源/行为 | 本次升级的核对与落实 |
|---|---|
| Pi配置同步、预设、AGENTS/APPEND/keybindings等模板 | 新宿主公开配置映射及profile选择由T009/T012落实；不恢复旧Neovim同步器或starter绝对路径依赖 |
| skills及其脚本/相对资源 | T025保留完整领域知识、脚本、资源、引用和权限；Full专属调度按profile隔离，复制不执行脚本 |
| 本地extensions/packages与远程包声明 | 按D12逐项处置；T006/Q1核公开接口，T009/T010绑定完整依赖与来源；替换不修改宿主 |
| prompts、themes、agents/roles及其他关联资源 | T002逐项核对选用与排除，T009/T023–T026按声明实现加载；发现变化进入差量表，不默默丢弃，也不把旧资源全部强塞Base |
| 旧字段合并、资源删除、备份与安装行为 | T002明确是否改变及理由；T012/T044–T046保持agentcfg三方合并、受管删除、pending恢复和显式lock/sync/apply边界，不覆盖原生用户数据 |

**验收**：T028从Base实际入口核对声明资源与宿主发现，T095闭合两profile最终组合和受影响行为；排除资源不残留，不因旧迁移已完成而省略新运行身份的验证。来源缺失或身份无法核实时明确阻塞对应项，不自动复制旧本机目录或删减目标。本节只定义差量核对责任，尚未完成T002的产品来源审计。

## D17 pi-jev 权限控制扩展复用候选（2026-10-10 更新）

**用户方向**：用户明确提醒可以直接使用 pi-jev，不必自行重造，并要求到具体选型时仔细衡量。评估顺序改为：固定版完整权限扩展原样复用 → 仅必要的公开接口薄适配 → 确有无法满足的要求才保留自有权限控制实现。已有自有代码和测试不构成继续自研的理由。

**已核来源事实**：只读审查 [配置](https://raw.githubusercontent.com/y0usaf/pi-jev/main/src/config.ts)、[扩展入口](https://raw.githubusercontent.com/y0usaf/pi-jev/main/src/index.ts) 和 [client](https://raw.githubusercontent.com/y0usaf/pi-jev/main/src/client.ts)。gate mode、工具名单、阈值、headless block、输出审核、endpoint/model/timeout/retries 均有配置；retries 可以设为0，output可以关闭。之前只根据默认 shadow/重试就倾向排除直接复用，判断过早。固定当前来源仍是只读观察，不声明 Pi1.0.1 实际兼容、API可用或模型质量。

**能力定位**：pi-jev 是权限控制扩展，包含执行前工具调用拦截、模型风险判断、人工确认/允许/拒绝与输出观察。此次按完整权限控制提供者比较，不先把它缩成后台判定器，再自建其拦截/确认/UI。既有文档中的 risk reviewer 指权限风险判断子能力，不是代码review。

**衡量事项**：按实际验收比较直接扩展、薄适配与自有方案的维护负担、版本/公开接口、实测质量/延迟/费用、模型及数据路线、预算/取消/错误语义、重复确认/判断与替换退出；同一调用应只有一套审批流程，不能叠加两个确认框或两次模型调用。可配置的默认值优先通过配置解决；剩余具体缺口分别记录，不能扩大成通用网关或重新造一套框架。可配置 endpoint 不代表其 Jev 请求/响应协议直接兼容普通 OpenAI/国内模型接口，路线复用须单独核实。

**接入原则**：pi-jev 可以作为可选完整权限控制提供者原样接入，不预先排除它进入最终选择。统一硬策略、ExecutionPermit、真实确认和隔离仍归 rotom；不能把无verdict自动合成allow。若原样扩展能满足实际需要就直接使用，薄适配只补已证明必要且可通过公开接口实现的边界，不导入未公开内部模块或修改上游/vendor。当前仍未安装、默认启用或调用TypeSafe；到T049–T057权限控制选型时形成固定来源/同条件比较记录，再决定提供者。

**保留约束**：此前已确定的严格输入上界与 AUTO OFF 不因复用偏好默默改变；真实路线/数据发送和费用按具体授权处理。缓存不能成为执行许可或恢复取消后的权限。本次只修正选型倾向，不开新服务、不扩原生探针范围，不阻塞Base主线。历史只读事实及原判断保留在 `.cache/pi-two-profiles/run-20261004/pi-jev-reference-review01/`；此次直接复用核对另存 `pi-jev-direct-reuse-review01/`。

**2026-10-11 固定版复核**：已核实 `@y0usaf/pi-jev@0.3.0`、tag `v0.3.0` 对应 commit `cbbc35dacee9337e575f7de913ef2757ad64a198`，干净源码快照、MIT LICENSE 与扩展入口 `./src/index.ts`；这是固定候选，未声明当前最新版或现代Pi兼容通过。原样模式可以配置 `enforce`、`blockWithoutUI=true`、`retries=0`、`cacheSeconds=0`，因此不因默认shadow/重试/缓存排除它。固定证据位于 `pi-jev-immutable-candidate-review01/`，主来源为 [v0.3.0](https://github.com/y0usaf/pi-jev/releases/tag/v0.3.0) 及 [固定入口](https://github.com/y0usaf/pi-jev/blob/cbbc35dacee9337e575f7de913ef2757ad64a198/src/index.ts)。

实际差距是：该完整扩展的模型clear在Pi hook中直接放行；服务缺失、异常及取消仍fail-open；当前未提供受支持的决策/传输接缝，无法直接绑定Rotom准备对象与一次许可，也不能从配置保证发送前总输入上限。缓存键缺少用户请求/cwd/配置代次，可用 `cacheSeconds=0` 禁用普通复用，但不能因此取得permit绑定。故它仍可作为独立权限扩展候选，不能仅靠上述配置成为当前硬准入契约的唯一权威；后续比较需保留Rotom authority gate，或使用上游受支持的接缝。此结论来自固定源码实际控制流，不把它缩称review backend、不改上游、不安装/启用、不新增模型请求，也不以“暂时关闭”签发Full风险功能完成。

## 研究结论与实施验证的区别

本轮只研究官方资料和源码，无宿主或账号调用。设计选择由D12–D15给出；下面列出的剩余工作是对选择的实证，不是尚未决定的产品范围。用户已冻结当前Linux x86_64，其他平台不阻塞。

- 正式发行物：已核对官方v1.0.1标签的宿主/SDK清单及公开文档，npm元数据读取失败，精确tarball完整性、全依赖锁和安装脚本仍须T006核验；不能据Git标签声称包安装已通过。
- 主分支源码事实：SQLite公开适配可配置连接的事实来自main源文件，标签对应源文件读取失败；正式候选包必须确认同等公开API。若不同，按公共Storage接口适配或有记录地重选，不能访问私有连接。
- 环境：只确认当前Linux x86_64和PATH有bwrap；namespace、容器、账号、终端体验尚未执行。缺环境是not-run/blocked，不是技术不支持。
- 质量：预算与模型路线按已有冻结程序和实际授权确定；没有借用历史结果或捏造数值。
- 本轮研究前/后宪章设计gate满足；没有以宿主补丁解决接口缺口。plan阶段保留旧74任务未勾选；后续speckit-tasks已细化为100项并同步本文引用，仍无产品执行证据。

## 实施来源审计与Q1静态准入（2026-10-04）

T002逐项结果见 [source-audit.md](source-audit.md)：82项既有能力/关联资源、38项当前依赖来源及9个输入文件身份。表中两profile处置是候选选择，不修改001历史与正式锁；所有尚未核验的发行物或运行结果显式留给Q1及各故事。

Q1官方v1.0.1标签的包清单/公开文档已核对：MIT、Node >=22.19.0，源码scripts没有preinstall/install/postinstall，正式依赖包含同系列pi-agent-core/pi-ai/pi-mcp/pi-codemode；未据此宣称传递安装脚本不存在。公开工具/Provider/MCP注册、嵌套tool_call/tool_result与父调用身份、ctx.signal、RPC无UI边界、reload和project_trust均有文档。默认网络禁止获取npm元数据，受控读取官方registry时TLS EOF；尚无正式tarball、integrity和完整依赖闭包，因此T006仍未完成，不更新正式锁。

新确认的历史偏离：`agents/pi/runtime/resource-loader.ts`的`installPackagePolicy`改写上游DefaultPackageManager/DefaultResourceLoader原型，不能直接带入新组合；与旧openai-proxy全局fetch包装一起列为退出项。仅移除包依赖或事后过滤显示列表不能解决。T023/T032须删除原型改写，T009/T028/T095验证安装与加载边界。

公开替代路径由 [v1.0.1 SDK文档](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/coding-agent/docs/sdk.md)、[公开导出](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/coding-agent/src/index.ts)、[ResourceLoader公开选项](https://raw.githubusercontent.com/earendil-works/pi/v1.0.1/packages/coding-agent/src/core/resource-loader.ts) 支撑：向createAgentSession显式注入DefaultResourceLoader和SettingsManager.inMemory；使用noExtensions/noSkills/noPromptTemplates/noThemes/noContextFiles抑制发现，再仅传入经锁和安装树验证的本地绝对additional路径。全局和项目packages列表为空，禁止npm/git/URL资源在run时触发解析安装。空数组只控制所选列表，不替代no*开关；noContextFiles也不关闭SYSTEM/APPEND发现，须显式指定对应输入。已授权项目规则经受管选择显式加入，不以关闭自动发现为由丢失R08的项目规则。extensionsOverride在扩展执行后才发生，不能作为保护边界。

该方案是公开API准入选择，尚未证明发行包行为。Q1候选必须用合成全局/项目/祖先诱饵验证：显式路径准确加载；其余资源零执行/零注册；空配置零隐式安装/联网；Base不构造Full factory；SYSTEM/APPEND与项目规则来源可核对。SDK默认不附加CLI的MCP/Code Mode factory，选定内置能力须通过公开factory/入口显式注册并另验嵌套权限，不通过私有import补齐。


T006取包更新：官方npm精确1.0.1元数据和tarball已通过无代理的直接TLS读取获得；旧代理路线的TLS EOF未被算作技术不可行。tarball按官方元数据sha512 SRI验证后，仅安全静态解包至隔离候选，归档SHA-256为`99c2e1958ac6d4c6a36e7f1c3690ae38778bb397c63e9d611d2c09521be735c5`（7,465,267字节、1243文件）。完整依赖与正式包公开类型/实现正在复核；未执行Pi、安装脚本或模型请求，未更新正式锁。元数据内容摘要和只读证据保存在私密运行记录。另发现本机PATH中的现存全局Pi package.json版本为0.85.1，仅作静态事实，不改动也不执行它。

T006完整闭包静态结果：隔离npm安装固定官方`@earendil-works/pi-coding-agent@1.0.1`，启用`--ignore-scripts --no-audit --no-fund`，使用独立HOME/npm配置与缓存。候选package-lock SHA-256为`f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac`；146个锁条目中120个必需、26个optional，当前Linux x64 glibc实际安装121个，其余25个为其他平台optional。所有已下载归档按锁SRI校验，安装manifest逐字对应归档；未发现夹带或当前平台缺包。静态engines/必需依赖/peer检查无冲突，7项optional peer未安装。`@google/genai`、`esbuild`和`protobufjs`的生命周期脚本均未运行，相关运行能力仍须实测。15个包没有根目录许可证正文，正在从对应上游版本补核来源；锁中的license字段不能替代正文来源。

正式发行包更正了早期“RPC无UI”的简写：`docs/rpc-extension-ui.md`明确RPC的`ctx.hasUI`为true，不能用它证明存在可用的人类审批前端。Q1须分别验证SDK无UI，以及RPC前端缺失、不响应、取消；后者应由受信审批通道的实际响应决定，不能因hasUI=true放行。SDK候选采用两包根公开入口：coding-agent的`ModelRuntime.create`，及实际闭包pi-ai 1.0.2公开的`InMemoryCredentialStore`/`InMemoryModelsStore`；不依赖旧版AuthStorage/ModelRegistry的假定形状。`allowModelNetwork:false`与`refreshOnCreate:false`固定关闭模型发现联网，合成Provider只用于接口探针，不计为模型质量证据。

本机bwrap已仅用系统`/usr/bin/true`验证user/PID/network namespace可创建，退出0；该预检没有挂载用户HOME、执行Pi或调用模型，也未验证产品文件/网络隔离。完整SDK探针准备后按仓库真实smoke边界另行核对明确授权。上述静态结果及namespace预检不签发Q1或产品gate通过。

T006许可证补核：已读取全部15个缺根目录正文包的精确npm元数据。Pi宿主1.0.1对应`a7229ddc21810d6245105978033b7df645ecc2f7`，其余7个Pi系列/Chord包1.0.2对应`cd32f7725fdbddbaecdff5b1e68491563394e0ca`；两提交MIT正文实际下载一致，SHA-256为`0457f5bcec3b3b211605dfb5d1a49042fd638f3686a410fe099c24a25af13c48`。esbuild 0.28.2对应`609683d892977362a0f99026cb74b96263d728a9`，MIT正文SHA-256为`b40ec5baec7bb34fa5b1c09521fa3cd52d5fad7adafed74932a2010d3612a681`。data-uri-to-buffer 4.0.1的已校验归档README含完整MIT正文，不能把“根目录缺LICENSE文件”误记为缺正文。

剩余5项只有声明或未完成正文映射：3个AWS包精确registry元数据没有gitHead；proxy-agent-negotiate 1.1.0的精确发布tag可核但未取得正文；standardwebhooks 1.1.1精确gitHead为`b4d2c14fc5b4ccff3ff271e3b087dff812254c59`，JS子包明确声明MIT，同提交仓库根正文为Apache-2.0。后者是不同范围的来源差异，不能直接说元数据错误，也不能用仓库根正文替代JS包正文。候选`license-provenance.json`保留每项来源及未知，未修改任何上游包文件，也未据此作法律充分性或运行验收结论。

T006原生SDK更新：用户明确授权断网bwrap探针和同边界修复重跑；第05次官方1.0.1 SDK及pi-ai 1.0.2实际执行中，资源白名单、嵌套身份、子调用阻止、父子取消、SDK无UI拒绝和reload白名单六项全部observed，退出0。reload需要保留公开`ExtensionBindings.onError`等实际binding，只有`mode`时当前版本不会在reload重发session_start；探针用错误计数handler保留绑定并断言0错误，没有访问私有runner或修改上游。实际调用、内容身份、失败历史、断言和限制见[native-sdk-probe.md](native-sdk-probe.md)。本结果不证明RPC审批通道、整进程隔离、真实账号模型或产品准入；T006仍有RPC接口和许可证来源工作，正式锁未更新。

T006许可证来源补充（2026-10-05）：三个AWS精确包的registry/归档manifest均声明Apache-2.0，已由[Apache官方](https://www.apache.org/licenses/LICENSE-2.0.txt)只读取得标准正文11358字节，SHA-256为`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`。自有`agents/pi/build/licenses/pi-modern/TRANSITIVE-SOURCE.json`将其明确记为`declared-license-with-canonical-supplement`：这是发行包声明对应的标准文本补充，不是从AWS精确提交恢复的LICENSE、版权或NOTICE。缺gitHead不妨碍记录这个有限事实，也不因此虚构提交映射。归档未发现独立LICENSE/NOTICE文件的观察范围仍保留。

两项MIT包继续为`body-scope-unresolved`：proxy-agent-negotiate未取得包范围正文；standardwebhooks的JS MIT声明和根Apache正文不可互换。后续正式候选晋级前须取得包范围证据或选择有可核来源且兼容的官方替代版本；不修改依赖包内容或许可声明，不反复查询已经失败的相同路径。旁车同时绑定Q1 lock与实际Base候选lock `7a6ad8e47f7b165d2c35b218a72e7734cf74a8ee26044d20e993419ba9c5bee1`，五项版本、URL、SRI和已安装manifest摘要逐项一致。2026-10-05 时安装器只处理显式直接source的license文件，旁车尚未接入发行物收据/安装清单。2026-10-06 自有现代 license bundle 已关闭离线分发缺口：310 项替身默认测试及稳定独立审查通过，正文由 `licenses/pi-modern/` 原样复制并收入既有收据，完整 registry 图核验与 unresolved active 拒绝已实施；未执行原生安装、未证明法律充分性，Q1及正式锁仍未晋级。归档 `modern-license-bundle/` 保留原分发反例和修复证据。

2026-10-07固定来源补充：上述两个MIT未解是早期阶段状态。当前从standardwebhooks发行metadata的原gitHead `b4d2c14fc5b4ccff3ff271e3b087dff812254c59` 枚举完整未截断树，取得[库父目录原LICENSE](https://github.com/standard-webhooks/standard-webhooks/blob/b4d2c14fc5b4ccff3ff271e3b087dff812254c59/libraries/LICENSE)、[JS package.json](https://github.com/standard-webhooks/standard-webhooks/blob/b4d2c14fc5b4ccff3ff271e3b087dff812254c59/libraries/javascript/package.json)及同提交README的三个固定blob。MIT正文含原2023 Svix版权，1088B／SHA256 `5ec8c7b26b64d881a6706617bed25c049f97f2f35de034c756de8546fd6dbe27`，Gitblob SHA `55b14b3a3ce649a2f1b05428dcc9c6db95b37c04`；JS manifest全文摘要与已钉npm发行manifest相同，version1.1.1声明MIT，README明确列出JS/NPM库。root与独立executor只接受这个固定源／父目录范围，允许原字节自有旁车和单行`fixed-source-body`；不补进npm归档、不替换根Apache正文、不作法律充分性结论。27输入来源收据 `a9f7f077231bb078db73b437ac90b5da1b76e948ab308a399174f232d7226cd5` 已接受，候选数据接线在该来源阶段待稳定默认验收。proxy-agent-negotiate@1.1.0仍无正文和完整来源关联：full packument的gitHead为空，固定tag树只列其它包LICENSE，没有根或negotiate目录正文，其API sha与0.0.0旧gitHead相同。两包当次full packument的latest仍等当前所选版；没有因此选择未验旧版、新源或修改依赖图。公开GET研究不运行包／SDK／模型／账号或部署，正式锁与产品gate继续关闭。

Q4固定公开协议增量（2026-10-06）：Codex官方rust-v0.154.0 tag对象36eab01061df3cde5f95ec20a526777b430091ba指向commit6b9826e3aa83b1a5947db50f4332cb9c65f1b340；固定源码归档SHA256848c7ffac62e21b14edc2048d2e5b7c82b31c556afa4b0d305da0f7d5aa794f4，20个公开参数/schema/CLI普通文件及追加11个app-server调用链文件已复核。LICENSE/NOTICE匹配既有登记；不提取无关链接、不执行/构建源码、不下载CLI。固定源码确认便利exec resume在未解析ID时可新建thread，现代组合选ID-only app-server恢复；turn/start可能steer既有turn，turn/steer需要expectedTurnId，interrupt lifecycle响应不证明OS后代停止。线程响应model/modelProvider与每turn实际服务模型分列。静态材料与默认13项纯编码分别归档，native运行仍unverified，T059未闭合。

Pi公开派发研究增量：coding-agent1.0.1闭包的agent-core/pi-ai为1.0.2；公开AgentOptions.streamFn可由自有工厂构造，before_provider_request异常被捕获后继续且prepareRequest不是最终归一化之后的提交点，故不作为故障关闭的执行许可。自有StreamFn13项及Agent组合21项默认验证和稳定审查分别通过，不替换SDK对象方法、不加载独立cache warmer。SessionManager公开append不幂等且先改内存再写文件，open缺失/空文件会创建或重写；精确native恢复及持久append未知边界仍待实现。详见[现代生命周期](modern-delegate-lifecycle.md)，静态源码、默认组件、授权native及产品四层证据分列，严格输入计量未因此合格。

2026-10-07候选接线补充：固定MIT原文已收入仓库自有 `licenses/pi-modern/STANDARDWEBHOOKS-1.1.1-LICENSE.txt` 副本、候选exact copy声明与registry；七文件稳定包30输入receipt `94ec16f1bf57cb147902bede27e25d6de7e7455dae6a739c0f0ad5707c8b7066` 已接受，最终四组86项默认测试通过。完整原三JSON在同最终测试上8fail／78pass保留，正文旁车已存在但旧数据未选择，不用删除正文制造反例。146条npm fixture来自原固定解析身份，三JSON逆去精确复原原bytes，未改npm归档／依赖图／Full来源／正式锁。当前默认发行路径接受该固定源正文的自有副本，proxy-agent-negotiate正文及当前源关联仍未解，实际原生安装和法律充分性未验证。

2026-10-07 proxy发布声明增量：已保留packument的dist.attestations给出新的[精确 npm 证明端点](https://registry.npmjs.org/-/npm/v1/attestations/proxy-agent-negotiate@1.1.0)。一次固定公开GET原始14529B／e109fa69…，root直接观察退出0；两个原DSSE payload的subject名称／版本和SHA512均匹配原精确SRI声明，SLSA payload声明workflow release.yml、main和固定gitCommit `b7e5f7ccce1a3ac5b339cc4c587974e8989cbc16`，没有新的提交。14输入稳定来源receipt `283c9934793c7cae9cb2fae5d4d4423a52ef83783b8c63053a38049097bd010e` 已接受这项未验签声明关联；DSSE／X509／Sigstore／tlog未验证，此步骤未获取或核新tar、没有取得包范围MIT正文，不提升法律、安装或正式锁资格。先前树正文缺口保留，不把其它包LICENSE当当前包正文；此次是新pointer的取证，不重复已失败的路径。


2026-10-08（本地）当前 Base Q1 摘要：execution05的145远程节点候选及 install01 原 source／installed-license validator 已实际通过，无source unresolved。早期两项MIT未解按各自阶段保留：standardwebhooks已取得固定提交的库范围正文；当前定向官方9.0覆盖图已移除proxy-agent-negotiate1.1.0。它们不再作为当前145图的同一未解项，也不作许可法律充分性结论。

当前安装树 SDK6 sdk01 在明确授权后一次六场observed、child／wrapper／tool outer均0，root receipt `cd3624dcfa90984031df7ed70d694c7e81cf1c3fc549df9977a2fcb3e5495684`，详细材料见[native-modern-base-installed-sdk-probe.md](native-modern-base-installed-sdk-probe.md)。新16,653条目／124,615,286B树与固定材料前后核对一致。先前RPC5是旧18,498条目候选、lock `f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac`的公开协议历史观察；尚无当前新安装闭包的RPC5执行记录。SDK6白名单也不自动等于独立project_trust行为验收。当前正限定核对公开信任加载接口及所需场景，T006仍未勾选；它本身不要求发布正式锁，candidate identity不等于sealed runtime或产品资格。旧授权按原固定场景闭合，当前缺口不改变已接受的历史观察。


2026-10-08（本地）Q1/T006完成：当前install01（16,653条目，145远程依赖图）的既有发行物／bin／exports／peer／engines／脚本及严格source／installed-license记录，与sdk01六场、rpc01五场、trust03公开reload两场构成本次隔离候选完整证据。RPC5的真实正文0/0/0/0/1与实际事件／状态／哨兵符合原oracle；trust拒绝全0、允许三资源和正文各1。此前公开接口剩余缺口为新安装树RPC与独立项目信任，现已补齐。默认发现不支持.mjs，通过只改自有fixture后缀.js修复；Node探针不支持clearenv的首次失败也保留，未改上游或调用私有API。

root Q1完整性receipt `6b474761df16cd0a4b467ec873705769fb9f7870dc8d746eadf6e6b9c60db5be`，T006已勾选，当前正式8/100。当前RPC12输入receipt `3a5587f46dd9f7591266df53c65b1925a851c1816b90c5b0ea7df3491e1f7bb1`；trust16输入receipt `40bdbb0bc86c6752d62c50d4dced589b2690e1d9ec929fac22125cadc63cd03c`。三个本轮原生授权（Node1/RPC5/trust2）均满足并闭合，旧失败／历史候选／默认测试分层保存。T006只要求固定隔离candidate，不要求此步发布正式锁或激活runtime；CLI首启／保存信任／真人前端、各故事高级接口、真实模型与账单、整体sandbox／sourcehold／controller／Full和产品gate仍分别未验或未完成。严格计量前AUTO OFF，正式manifest／seal／current／deploy未变化。
