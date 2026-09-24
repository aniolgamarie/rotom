# 验证覆盖与交付门槛

本表定义验收要求，不承载当前执行状态。实际结果见 [实施记录](implementation-progress.md)、
[支持矩阵](../../docs/acceptance/pi-support-matrix.md) 及其引用的候选证据；没有匹配证据的项目仍为未验证。
mock 是默认隔离验证；native/live 为独立明确授权步骤。

**2026-09-24 验收边界**：V01—V24 软件行为覆盖保留，本 spec 仅要求 Linux x86_64 四配方的 mock/native 和双路径冷重建。下表中账号 live 与其他平台验证为转出后的后续要求，不参与本 spec 关闭门槛；见 [范围修订](scope-change-20260924.md)。原始跨平台/真实服务状态仍如实保留。

| 编号 | 场景与通过条件 | 要求 | 层级 |
|---|---|---|---|
| V01 | 联合清单覆盖来源、选择、磁盘及证据；全部资源处置/依赖链无悬空；current-only implement保留 | FR-001—FR-004、FR-006、SC-001 | mock；实际发现另native |
| V02 | 公共schema严格；只选中profile检查必需绑定；未选pi-managed不阻塞DSH；所有catalog引用闭合 | FR-005、FR-011—FR-012、SC-009—SC-010 | mock |
| V03 | 四配方锁切片各自完整npm ci；源/补丁/执行位/原生包/许可核验；sync不改锁 | FR-007—FR-009、SC-002 | mock+native安装 |
| V04 | render/plan/apply/run不下载；agent参数不匹配无副作用；原生透传不能覆盖受管参数 | FR-010、SC-006 | mock+native |
| V05 | 完整技能/角色/提示/主题；factory加载前过滤；project覆盖和重复管理者拒绝 | FR-013—FR-016、SC-003、SC-008 | mock+native |
| V06 | 字面secret/命令型apiKey在投影前拒绝；不同版本allowlist支持合法引用轮换/回滚；auth不读取 | FR-017—FR-018、SC-006 | mock哨兵 |
| V07 | 旧home/starter仅只读；提案可审阅；冲突、漂移、空数组false、源删除、未知文件保留 | FR-019—FR-020、SC-006—SC-007 | mock |
| V08 | 每个声明故障点pending可恢复；无变化不轮换；旧runtime身份启动不受新profile切片影响 | FR-021、FR-042、SC-007 | mock+native |
| V09 | supervisor先登记后spawn；重复dispatch只启动一次；孤儿/父退出/PID复用/未知子活动阻止变更；新监督者只读核对旧owner；另有用户显式stop-only恢复，旧控制者存活/PID复用/过期计划拒绝、恢复中再崩溃幂等；allocating/第1及第N项预留/journal追加/starting提交各故障点可按证据恢复，提交后未知不能清锁 | FR-022、FR-028、SC-005—SC-006 | mock+两平台native |
| V10 | 新管理者唯一；实际vendor/Pi/role身份精确；旧0.63不可加载；未认证transport执行前拒绝 | FR-023—FR-024、SC-003 | mock+native |
| V11 | inspect/fix候选、真实check、required review及有界second_view；候选改动使旧通过失效 | FR-025、SC-004 | mock+native；服务另live |
| V12 | 首次/重试/schema retry/压缩/handoff/父helper/proxy每次请求门控；未知发送不退款；费用未知不填0 | FR-026—FR-027、SC-005 | mock+native虚构provider |
| V13 | Permission Policy v1 exact/subtree/deny优先与父路径重绑定；未知regex/glob拒绝；父deny/动态工具/同名角色/symlink/rename/readseek/shell/MCP/nested越权拒绝；YOLO不解除上限；ordinary授权业务根可编辑且无需task grant，managed写源checkout仍拒绝 | FR-029、FR-034、SC-005 | mock+native |
| V14 | cancel≠reclaimed；进程组/外部工作清零才终态；resume fresh保留任务/预算；GC旧空结果不通过 | FR-028、SC-004—SC-005 | mock+native |
| V15 | 定时原子准入、取消/过期/重启missed不重发；统计分组不清预算；缺模型/检查绑定不能启动managed | FR-030—FR-031、SC-004 | mock+native |
| V16 | 7个旧角色转model-delegate用途模板；两backend假receipt/旧run/空结果/错cwd-model/partial/假stopped均失败 | FR-032—FR-033、SC-008、SC-011 | mock；宿主native，账号live |
| V17 | Cursor只在Bun配方；OpenSpec不凭无pi清单当已发现；权限/压缩/通知/进程/恢复每域单一责任 | FR-034、SC-003、SC-008 | mock+native+所选服务live |
| V18 | doctor分层证据/待登录/缺依赖；零证据和部分失败仍出报告；capture仅allowlist；错误脱敏/退出码兼容；维护/显式恢复有指南 | FR-035—FR-037、SC-010 | mock+native |
| V19 | 完整DSH默认回归，原有效配置零强制修改；DSH/Pi和多profile状态、锁、账号、依赖隔离 | FR-038、SC-009 | mock；原生DSH另授权 |
| V20 | 每个目标格子两种路径冷构建；无旧HOME/cache/starter依赖；固定scope分必需/已选/未选，报告生成不等于批准；live只等待匹配native与授权 | FR-039—FR-041、SC-002—SC-003 | mock+native+live分开 |
| V21 | 升级角色/运行时/策略/路线或scope使旧证据/批准失效；未选可选账号不阻塞、已选缺证据阻塞；损坏证据报错，回退限制提前显示 | FR-042、SC-010 | mock+native |
| V22 | model-delegate保留Pi/Codex只读与resume/cancel；Codex显式worktree写入；跨profile/不同HOME/路径别名争同worktree恰一个成功，unknown持久租约不能绕过；未授权/自动写重试拒绝，Pi不支持写入时拒绝 | FR-043、SC-012 | mock+native；账号live |
| V23 | detach/readiness/unknown、cursor poll/wait、observe进度、上下文预算/反馈关联、单run重试责任与上层batch去重；不绕过managed gate | FR-044—FR-045、SC-012 | mock+native |
| V24 | 无旧skill/runner/tool/七角色环境仍跑通所有旧用途；工具/提示/规则/配置/锁/文档映射无活动旧引用；新环境零隐藏fallback，旧HOME不删除 | FR-045—FR-046、SC-011 | mock+native冷构建 |

## Platform/Capability Certificate

证书键包含 OS、architecture、工具链、Pi runtime identity、slice、manager patch、角色、策略、transport。
Linux x86_64、Linux arm64、macOS arm64、macOS x86_64 分开记录；
pi-default、pi-managed、pi-codex、pi-cursor 也各自独立，不跨引擎或平台继承通过。

每条证据包含命令、时间、源码/产物身份、预期、实际、结果和局限。
不能将允许安装、测试代码存在、历史release notes或退出0单独计为功能通过。

## 完成判定

- 汇总可在零证据时完成，持续显示passed/failed/not-run/stale/not-selected；不要求执行任务先全部勾选。
- 本 spec 最终 check-release 使用 `001-unify-pi-capabilities-linux-software` revision 1，81 项全部须匹配通过；原完整范围报告保留为后续基线，不豁免本轮两 backend 替换、四配方和双路径冷重建。
- 每个声称完整支持的平台必须通过该平台的pi-managed；base-only不能称完整迁移。
- 未获native/live授权时标not-run；不得关闭控制获取通过，也不把等待账号包装成已完成。
- spec质量检查和本计划结构检查只评价文档，不勾选这里的工程/原生验收状态。

## 本轮设计复核

三项初始独立研究完成；用户确认替换目标后补查model-delegate源码与旧迁移路线，并完成全部相关文档复审；额外交叉审查修正了全profile绑定校验、独立npm锁切片、历史runtime身份、
初始化模型登记、closed catalog来源、凭据轮换版本上下文、attempt/owner准入身份、监督者重启后只读核对旧lease等一致性问题。
用户授权后，U1/U2/U3/I1修订进一步补齐显式stop-only恢复、跨实例worktree仲裁、Permission Policy v1及持续报告/条件批准；该段记录描述设计复核时点，相应测试的当前执行结果见实施记录。
这证明设计已复核，不替代上表的实现验证。


## Codex原生边界补充（V13/V16/V22/V24）

- mock：执行边界与策略摘要伪造/缺失、native_execution未声明、native shell关闭、部分写权限不能扩为原生目录读写。
- mock：原生候选编辑不依赖MCP日志，但授权缺失/错run/错policy/候选变化/未物理终止不能认证；原型MCP入口与包闭包退出默认路线。
- mock：策略失配触发整次停止、停止窗口写锁保持、跨边界受控文件RPC拒绝、旧V2不自动补授权、resume不得更换授权身份。
- native独立授权后：实际CLI参数、原生命令与apply_patch、只读/源checkout/越界拒绝、全部子工作终止及配置发现验证。
- 未闭合：系统/企业云配置和附加MCP/插件来源发现、原生权限各平台行为；mock不能关闭这些门槛。


### 原生机器根投影补充（V09/V13/V22）

mock验证：只读/禁止根从源项目重绑定到linked worktree；全项目只读拒绝implement但允许readonly；
无关项目不重绑定；readonly不新增读取权；嵌套allow不重开限制；非project file deny仍生效；
源目录替换/删除、候选符号链接、缺失候选限制目标、未知根与exact目录歧义均明确拒绝。
实际resolver输出和启动授权必须包含同一权限投影；根变化后停止请求与写锁保护分别检查。
目录别名采用替身身份验证转换算法，不能冒充真实bind mount/macOS文件系统的native通过证据。
