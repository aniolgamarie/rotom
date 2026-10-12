# Pi 双 Profile 长期任务状态

更新时间：2026-10-12。工作区：`/data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade`。

本文件用于续接当前工作，详细验收仍以 `specs/005-pi-two-profiles/{spec,plan,tasks,acceptance}.md` 为准。用户本次要求只写本文件；主实现子代理已中断，未执行新的生产变更或测试。恢复工作前，应确认后台进程和候选目录的实际状态。

## 开发分支与跨机器续接

用户随后要求将当前工作以开发分支 push，以便在其他机器继续。当前分支为 `feat/pi-toolkit-upgrade`，远程为 `https://github.com/aniolgamarie/rotom.git`。这是未完成的开发检查点，不是发布、部署或产品验收通过。

跨机器操作见 [续接说明](specs/005-pi-two-profiles/DEVELOPMENT.md)。本分支保存源码、测试、规格、依赖锁、固定 Linux 运行资产及许可；没有迁移登录数据、实例、会话或本机临时 HOME。下文绝对路径只描述原机器历史，不能在新机器直接执行。

主干同步：已核对旧分支23个历史提交的patch与整理后的主干等价，只将真正新增的开发检查点重放到本地主干 `e1a9b1355d11a0d5f56c2b58536caff798435e7e`。主干本地比 `origin/main` 多12提交，本分支包含该本地主干基础；没有修改或推送main。新增提交作者与提交者使用用户确认的、与主干一致的仓库级身份。原分支保存在本地备份 `backup/pi-toolkit-upgrade-pre-main-sync-ea011bd`，不将旧身份链带进开发分支。

同步的唯一冲突是测试参数注册：保留主干 `--omp-standalone-bun`，同时保留 Pi 的 `--run-pi-lease-os` 及默认隔离守卫。共享配置/运行入口采用三方合并，历史原生资格仍绑定原来源；不能因为主干同步而自动升级为当前源码通过。

被忽略的 `.cache/` 原始日志和 Root 归档仍仅存在原机器。本文中的收据是历史验收引用，不是新 checkout 已带这些原件或通过当前机器验证的声明。临时 overlay 的已中断候选差量已单独保存到 [候选检查点](specs/005-pi-two-profiles/checkpoints/temporary-overlay/README.md)，尚未应用；`tests/test_pi_temporary_overlay.py` 是对应未完成实现的 RED 测试，不能当作绿色默认基线。

## 当前总状态

- 正式完成 **32/100**，剩余 **68 项**。该数字只计整项验收，不代表代码工作量百分比。
- 已完成：T001–T004、T006–T008、T010–T015、T017–T022、T024–T025、T029–T032、T035–T036、T038、T068、T071–T072、T097。
- Base、Full 和总交付尚未完成，八项产品 gate 均为 false。T073 整项仍开放。
- 严格发送前输入 token 上界未验证，**AUTO OFF**。不得以估算、假零计量或合成资格冒充真实发送资格。
- 当前重点：完成显式 `temporary-overlay` 检查模式，解除真实检查因缺失秘密拒绝路径而不能启动的限制；随后补成功检查和真实当前性接受证据。
- OMP 权限问题已由用户交给别人，不继续处理。Linux 是本次必须实测的平台，Mac 等按需。

## 本轮已完成并接受

### T073 证据生产与消费默认闭环

已接通原始执行结果 → 不可变 raw artifact → EvidenceRecord → 工件读取 → 新输入观察 → 有效性归约 → 最终接受。默认组合使用实际 TaskService、Artifacts、SQLite Store、Scheduler，以及明确的假 Provider/进程端口。

- 完整正控制经过 Worker、构建与测试、独立 Reviewer、证据保存和重新观察，最终为 `COMPLETED`。
- 负控制覆盖非零退出、零测试、全跳过、语义断言和必需 ID 失败；这些是 current 的失败证据，保留原结果、计数和历史分母。
- 显式未知进程证明与缺失/损坏身份分开；配置和版本变化为 stale，工件删除、字节变化和范围错配为 invalid。
- 暂停、停止、所有者变化、配置变化发生在最终异步观察期间时，不接受迟到结果；旧版本和缺记录结果不能恢复或采纳。
- 真实 reviewer 证据引用必须先保存，再等待输入观察并重读原所有者/代次围栏；不得提前保存成功判定。
- 独审发现工件读取失败时 not-sent/no-artifact 记录可能误报 current，已用有效 RED 修复：强制 invalid，保留原事实、计数和分母。合法独立 not-sent 的纯归约语义保持。

默认证据分轮为 Node86、Python14、状态消费者3、P2 修复受影响74，存在重叠，不能累加。

冻结材料：

- `.cache/pi-two-profiles/run-20261004/taskkeeper-evidence-producer-implementation-review01/final01/`：17 个源码/测试文件，45 项输入，内嵌收据 `0ad20b96112032a5fa351de787bbf2c84f76fead08664f7f71e8afcc13be0c7e`。
- 同目录 `fix01/`：唯一 P2 修复，8 项输入，收据 `3c883b158a8713fa7476ac87904c314f19ccaa7c31d8ccf379682f00f1d96b42`。
- 独审：`taskkeeper-evidence-producer-independent-review01/`、`…review02/`，最后无剩余 P1/P2。
- Root77输入验收：`taskkeeper-evidence-producer-root-canonical-accept-review01/`，收据 `e497b0c6658a346b5a52c04e758c394925a7a61b92cdbcd173e00d3fe8ffa569`。

### 新正常生成与安装

正常 builder 生成67个自有来源绑定文件，新增 `producer.mjs`、`records.mjs`；5个生成输出发生变化，实际安装文件逐字节一致。Full seed 仅更新 TaskKeeper 和根依赖引用两行；Base145行 seed 完整字节、Full150行有序远程依赖、其他本地包及 T025 Skills 保持。共享 Python 变化会改变运行身份，不能宣称 Base 整个运行包字节不变。

- 新私有工作目录：`/home/weixiaoxian.wxx/.cache/rotom-evidence-native-4nmhp1qx`。
- 运行身份：`54ba4c4bcdb6773e2ba8723ad63f7b630a42d42fcbca025359c6b72631e84a01`。
- 锁身份：`9759b39fee90caa03da42d44a6d195b6960594b77c5455ed809dd4e4cb58639f`。
- Base121 / Full176 选择集合保持；公共 Base=current、Full=candidate 未晋级或部署到用户默认实例。
- generated79/79、实际安装 adapter/status17/17、Python14/14；`validate`、`sync`、`apply`、`doctor` 均 exit0。
- 6个安装后的 Python 模块通过 fresh import 和源字节核对。

冻结材料：`taskkeeper-evidence-producer-normal-native-review01/generation-final01/`，68输入内嵌收据 `635582dee0aa8c0aac5cdd7a1a458c5f6b9a1788de363e312474f8f31e2af4ab`；独审 `taskkeeper-evidence-producer-normal-independent-review01/` 无新增 P1/P2。

Root71输入验收：`taskkeeper-evidence-producer-normal-root-component-accept-review01/`，收据 `0a5faa7dae4b02e48505fdc7ac5623abbb7dded2e9a13ad949b8c7a166d2b52b`。

### 两场真实原生局部验证

官方 Pi1.0.1 / Node24.14.0 保持上游原样，断外网、合成本地 Provider、自有私有目录，无真实账号或付费模型。

1. **SDK 只读准备与状态消费**：实际 CLI RPC 提交、两次状态查询、EOF，exit0；3809B真实 initialInputSnapshot，摘要 `e17874518b68ba683c8fa803fd707b1663b221204f7c431c4dfa34d2fde084cd`，双 Host 契约和计划落库，安装后的 Python DTO 相同。6次本地 main POST，其他模型/付费为0。新状态查询真实增加快照执行，本场4租约均 valid/reclaimed/protected=false。
2. **原 Host 失败事实记录**：新 Host activation/manager 核原 SDK 已登记候选、物理根、来源和契约；两个真实 helper 启动后均 exit5，raw=`failed`、`nonzero_exit`、`notSent=false`、counts=null，有匹配的进程和终止证明。实际 raw → Record → Artifacts.read → reducer 保留失败，每条分母1，supportsPassed=false。本场4租约回收，累计状态8包含 SDK4，不得混合计数。

Host 场的配置身份来自已关闭 SDK 的原观察，只能说明 recorded tuple；它不能证明后来使用时的实时 private getter/config/provider 当前性。没有成功检查器、真实 reviewer 物理投影、严格计量或整个 US5 资格。

原 stderr 仅通用错误。期待详细拒绝字符串的后置断言失败已保留；只读检查同一编译输入时 `verify_check` 通过，`linux_verifier_argv` 返回 `pi-check-denial-not-representable`。这是后置输入诊断，不是原 stderr 的详细错误证明；未为了取绿重跑或放宽策略。

材料：`…normal-native-review01/sdk-final01/`（18输入，收据 `b275ff89cce51d4ce097ca325cf1e18214229a510ba5d1f34393e2f89ed95a11`）、`host-record-final01/`（27输入，收据 `1bad790044eee930f659b8c50c1a7b50d9557ae4ad0f8095edaad714b19cb95f`）。独审 `taskkeeper-evidence-producer-native-independent-review01/` 无新增 P1/P2。

Root49输入局部验收：`taskkeeper-evidence-producer-native-root-component-accept-review01/`，收据 `a9cb910624ee88398871777bf370aa06ed3d0b177b9520a72f95c5ccac26b858`。

### 审核隐私与旧桥接夹具

- 原 `ReviewerDecisionControl` ticket 保存每次新的四个随机 wire 别名、闭合能力事实、私有 source binding；所有结论入口统一复核并映回原一次许可。provider 启用但没有合格 wire 时禁止发送；模式从 begin 固定，不能清空 provider 或跳过准备来绕过。
- 私有输入无 getter，不消费许可来取正文；路径、正文、内部摘要、route identity 和秘密散列不外发。没有生产语义分类器时保持不可发送，AUTO OFF。
- 两处独审 P2 有效红绿后修复；最后五模块251通过。Root20输入收据 `cc258b4f796cf3f1e6e1eeaefdd0c738d55a9ca3347bc7bf3b4b46c494a4a165`，材料 `reviewer-private-wire-projection-root-component-accept-review01/`。
- 旧桥接6个失败在冻结原像中同样复现，原因是上层 monkeypatch reviewer、原底层策略仍 human。仅修两测试夹具：显式合成策略、原 mount compiler 核计划、删除上层结果补丁，默认 human 负例保持。两模块62通过，Root13输入收据 `96064f335b0d870133503dde5a6321d9360a5d8573c403388586daa7380b3988`。生产审批保护未放宽。

## 正在进行：临时覆盖层检查模式

当前生产变更**尚未应用**。自动审批明确拒绝首轮多文件编辑：实现不完整、可能引用不存在的 `_overlay_argv`、涉及持久安全边界且材料不足。被拒动作未执行，不能拆命令、间接 apply 或绕过审核。

已决定的安全替代：先在独立候选树完成全部 helper、接口、默认测试和固定完整 diff，Root/独审验收后，再提交一次完整 apply 审核。若仍被明确拒绝且没有更安全方式，再向用户说明具体动作和理由寻求处理。

- 候选目录：`.cache/pi-two-profiles/run-20261004/next-checker-temporary-overlay-implementation-review01/proposed/`。
- 拒绝记录：同目录 `auto-review-rejection.json`；原像、有效 RED 已保存。
- 当前方案、源码和测试仍在候选中实施，尚未冻结、尚未默认整包通过、尚未正常生成或部署。
- 实现子代理 `/root/base_performance_execution` 刚被本次用户指令中断；它此前因 `failed to load workspace requirements` 出错，已续接过，当前停止。
- scout `/root/t011_final_evidence` 最近完成系统可见范围证据，处于空闲/完成状态。

候选唯一写范围：

- `agents/pi/schemas/options.schema.json`；
- `src/agentcfg/{pi.py,pi_checks.py,pi_trusted_checks.py,pi_auxiliary.py}`，必要自有 overlay helper；
- `scripts/pi-project-check`；
- TaskKeeper `src/{config.ts,agentcfg-config.ts,verification/supervisor.ts,verification/inputs.ts}`；
- 新增有意义默认测试和必要夹具修正。

本阶段不改生成包、归档、依赖 seed、公共 profile、SDK/vendor、已密封运行包；源集合变化后必须重新正常生成。

## 关键决策与不变量

1. 不修改任何 agent 上游源码、缓存副本或官方二进制；只用官方公开 API/CLI、配置和自有适配。
2. 用户已总授权自主执行低风险真实合成测试及同边界修复重跑，不逐探针再问。工具的明确自动审核拒绝仍需遵守；当前采用完整候选树的安全替代。
3. 可选 `checks.execution_mode="temporary-overlay"` 仅允许 Full、enabled且 selected 的 TaskKeeper check、Linux和原已核 fixed helper。模型/任务参数不能选择模式；未知字段拒绝。未声明时原行为和 argv 保持；其他平台/入口不回退宿主。
4. 使用公开 bwrap `--overlay-src /proc/self/fd/N` + `--tmp-overlay`；原候选只读 lower，临时 upper 支持构建，写入不持久化为候选修改或缓存。stdout/stderr 沿原捕获和工件保存。临时写效果必须进入检查契约。
5. 长期 contract 包含 mode/effect、原 lower 物理身份和可信检查器来源。候选动态目录 metadata **不进入长期 contract**，避免合法 Worker edits 使 T071 自失效；每次派发的语义输入仍由 T072 单独绑定。
6. 动态 `overlay_scope` 只由原 Host resolve 在核当前 manifest/mode/root/trusted check 后生成，写原 immutable auxiliary input。它不是 caller 参数、grant、SourceAuthority 或新队列/事务；模型不能提供。
7. `overlay_scope` 为有界、metadata-only、nofollow 的 candidate/声明只读根清单与 deny 物理坐标。deny 先分类，只 stat，不读取秘密正文或散列、不过度遍历秘密子树。脚本持有源 FD 后重核路径 dev/inode/uid、mtime/ctime和清单，固定 helper FD exec 前最终比对；变化拒绝 inner checker 启动。
8. 首版只支持候选内 missing leaf，父目录已存在且 canonical。missing parent、链接、特殊对象、硬链接或无法闭合的别名、其他可见只读根内缺失 deny 继续拒绝。不得在宿主候选建立占位、复制秘密或删除策略。
9. 实际可见固定 system roots 做有界 metadata 检查，不扫描整个 HOME。旧 Shell inventory 跳过内部系统 symlink、未对 system regular hardlink 全拒，不能直接宣称别名闭合。内部链接仅允许解析到已选可信可见根、无 protected/deny/cycle/ambiguity；不确定时遮安全父目录或拒绝，不能跳过。硬链接秘密别名无法排除时同样拒绝/遮蔽。
10. Host 的 root tuple 来自原持有 FD；guest overlay inode 或 namespace UID 不能代替宿主身份。映射必须由原 namespace/mapping 事实核验，不能把0或父 euid猜成 owner，不能放宽共同祖先/Tree权限。
11. 结果和有效性分开：known failed 永远保留；stale 不隐藏失败；invalid 不抹分母。只有 current、原 independent oracle 和匹配进程证明支持 passed。
12. raw artifact、origin、历史 attempts 不事后重写。发送未知、进程未知或回执未知不退款、不释放 Writer；已有旧 unknown/protected lease 不杀、不清、不改日志。
13. 正式任务与产品 gate 分别判断；无账号 smoke、默认关闭、合成 SDK 或局部 exit0不能代替启用态质量、真实计量或完整产品通过。

原型证据在 `missing-deny-overlay-feasibility-review01/`：只读覆盖、临时可写覆盖和 held directory FD 都已在固定 helper 下实际验证；普通输入可读、合成 `.env` 读写删除拒绝、原候选不变。原型不等于产品资格。设计定位见 `next-checker-temporary-overlay-seam-review01/`、`next-checker-system-visible-scope-evidence-review01/`。

## 下一步执行顺序

1. 确认被中断子代理与后台命令状态，检查候选树实际已写内容；不要从头重复已接受组件。
2. 完成候选模式的声明 → Host 契约/动态 scope → fixed script FD/argv → TS current binding → 原假端口完整默认链路。
3. 默认反例取得真实 RED，再修复；覆盖 missing leaf、root/source/config/UID/entry/mode漂移、别名/submount/link/hardlink、FD异常回收、普通临时构建与原失败计数。无关旧全量套件不重复。
4. 写入完成后冻结完整可执行候选 diff、所有引用、日志和 pins；Root审锁/身份/别名关键边界，scout限定稳定差量独审。
5. 以具体闭合候选和测试证据提交一次完整生产 apply 自动审核；拒绝不绕过。
6. 通过后一次正常生成、安装来源闭包核验，再执行原 Host 的真实成功检查器、取消/超时、秘密拒绝与来源漂移。
7. 补真实 SDK 在使用时的 fresh 配置 getter/输入身份链，以及真实 reviewer/委派物理证明消费；不能把关闭 SDK 后固定身份叫作 current。
8. 根据 spec/tasks 实际覆盖决定 T073 整项是否可关闭，继续 T067/T069/T070/T074/T075 的 TaskKeeper完整产品流程与生命周期。

## 其余未完成目标

- Base稳定最终锁与冷安装：T009/T028；会话、日常任务、终端/SSH体验：T023/T026/T027/T094。
- 受管 Shell/文件各入口完整 OS 边界和覆盖矩阵：T033/T034/T037/T040，Base产品 gate T041。
- WorkspaceLease 并发、崩溃、恢复及旧实例迁移：T016；提供者替换/数据恢复与维护：T042–T048/T095。
- 性能：T005/T047/T093。纯 Pi 基线已冻结，Base r7完整采样有效，但启动、RSS、idle CPU、FD四预算失败；优化后的正式预算未验证，不改阈值取绿。
- 审批 T049–T057：生产安全语义 projector/factory、一次准入集成、动态依赖绑定、严格发送计量、启用态质量与语料预算。pi-jev0.3.0是完整 Pi 权限扩展候选，原样复用优先比较；固定材料确认 fail-open、预算和 Rotom permit 接缝缺口，不能单独替代硬准入。未安装/启用。
- 委派 T058–T066：现大量默认与局部原生组件，真实发送/严格计量/官方 Codex矩阵、同run继续及两宿主组合尚未全部资格化。
- Durable T076–T092：已有持久化/发送边界/公开 SDK/恢复局部证据，原产品 controller/service、owner、存储恢复、查询零发送与完整生命周期仍需闭环。
- 最终性能/真实账号/Linux体验/维护/手册和稳定最终审查：T093–T096/T098–T100。只有全部必需 gate 通过才总完成；默认切换、部署、推送/合并不在当前授权动作中。
- Docker/podman当前环境缺失；整进程隔离为环境不足未验证，不冒称 Pi 全进程隔离，也不自动阻塞独立受管工具工作。

## 环境与续接注意

- `/tmp` 和 `/run/user/1002` 曾 ENOSPC；默认 exec 的 `/tmp` mount marker 和 heredoc也会失败。
- Root shell 临时目录：工作区 `.cache/pi-two-profiles/run-20261004/root-shell-temp`（0700）。仅 shell元命令使用；工程祖先 group-writable，不能把该目录当私有 StateRoot。
- 私有状态/完整安装目录使用全新 `/home/weixiaoxian.wxx/.cache/rotom-evidence-native-*` 0700，原祖先权限检查不放宽，需工具 escalation；不读现有账号。
- 只清理过本次失败运行自有未sealed partial source/npm-cache；旧 sealed、未知活动、他人目录和历史证据保持。
- 新路径必须重新核物理身份、来源/登记/manifest；不得借旧 root identity。
- Node：`/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node`；Python：`.venv/bin/python`，禁字节码。Node默认测试使用原 `scripts/test-pi-mock.mjs` 与明确文件，网络/子进程守卫不可绕过。
- 批量归档 helper：`runpy.run_path('/tmp/pi-upgrade-archive-root.py')`，`archive` 先核全输入，`update_state`原子保存。pins 的内嵌 receipt 是 compact sorted inputs-array摘要，与整个 pins 文件摘要不同。
- 常规实现角色 executor=`gpt-6.1-sol/medium`，scout=`gpt-6-luna/high`；Root处理复杂锁/事务/权限和最终验收。最多两子任务，子代理不派生。线程额度曾拒绝 executor续接，Root接手过权限小修复，不能静默声称子代理完成。
- 长期交接详细历史：`.cache/pi-two-profiles/run-20261004/root-current-next.md`（只需最新末段）、`state.json`、`specs/005-pi-two-profiles/implementation-status.md`。历史组件数量与正式32/100不能混用。
- 保持已完成、进行中、失败待决策、环境不足未验证四态；不要把环境失败或未知当测试通过，不以剩余困难自动停止独立工作。
