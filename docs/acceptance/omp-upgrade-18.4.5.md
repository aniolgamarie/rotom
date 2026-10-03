# OMP v18.4.5 升级验收

验收日期：2026-10-01。范围为仓库自有适配器、独立权限插件，以及本机 Linux x64 的 `omp-kernel` 部署。使用官方未修改的 standalone 二进制；没有上游源码补丁、宿主重编译或私有接口改写。本次真实模型请求为 0。

## 固定身份

| 项目 | 身份 |
|---|---|
| 官方版本 | `v18.4.5` |
| 上游提交 | `79808c3bf8f8cd9826decc63e3e18b13035f64f8` |
| 不可变源码归档 SHA-256 | `eddf7bb092dacffcfbbc1d44b1cc367e0fb9e2bf8fabd4ff97aa0ac21c401652` |
| Linux x64 二进制 SHA-256 | `42c710239b3fc30b9759424f973c6c143709935d5752be7eec8d7b011f40d864` |
| 最终依赖锁 | `14480cb8a99390aa3cc47df5fbdd4087c898d9e8e77e0eccf176bf383beb4f22` |
| 最终运行包 | `14480cb8a99390aa3cc47df5fbdd4087c898d9e8e77e0eccf176bf383beb4f22-linux-x64` |
| 独立权限插件 tree digest | `aee7cd403cb043a726a74222860654a101a0647938206d6e99033f884367f970` |

二进制来自 [官方 v18.4.5 release](https://github.com/can1357/oh-my-pi/releases/tag/v18.4.5)，同步时校验实际资产字节。固定提交归档、tag 归档与用于 SDK 验证的解压源码共 8463 个普通文件内容一致。其余三个平台使用官方校验清单更新锁定摘要，本次没有下载或启动这些平台的宿主。

## 验证结果

| 状态 | 验证 | 结果及边界 |
|---|---|---|
| 已完成 | 管理器相关离线回归 | 最终完整一轮 `228 passed, 7 skipped`；跳过项为退役的历史补丁宿主验证，不计为通过 |
| 已完成 | 独立权限插件单元测试 | 315 passed，0 failed，1152 assertions，14 files；临时 HOME、阻断网络，不启动真实宿主 |
| 已完成 | 新版 SDK 严格类型检查 | 三个 standalone 源文件对固定官方源码检查，`tsgo` 退出码 0；外部依赖使用既有缓存，无伪造 SDK 声明 |
| 已完成 | 独立插件 bundle | Bun build 成功，公共宿主 SDK 为 external；没有构建或修改宿主 |
| 已完成 | 隔离官方宿主 smoke | 最终锁身份下真实 PTY 启动成功；临时 HOME、虚构凭据、确定性 loopback provider；`permission_bash` 执行一次 `ls -la`，退出码 0 |
| 已完成 | 审批 fallback 和会话模式 | 主审 fixture 返回 503 后远程 fixture 接替一次；最终 main 请求 2 次、主审 1 次、远程 1 次；人工模式后创建新会话恢复 smart |
| 已完成 | 本机部署 | `sync → plan → apply → doctor` 成功；依赖和已部署依赖均 installed，待变更 0，无漂移、冲突和恢复待办；就绪级别为 offline-ready |
| 已完成 | 最终启动准入与版本 | 受管启动准入的无宿主回调验证通过；另通过受管 CLI 的 `--version` 实际输出 `omp/18.4.5` |
| 已完成 | 原生账号与会话保留 | 独占实例租约下完成一致备份；排除两份受管配置后，80 份原生文件与备份字节一致，不输出凭据或会话正文 |
| 环境不足未验证 | 真实 Cursor 服务及账户 catalog | 没有发真实模型请求，也没有将账户 catalog 核验记为通过；保留当前执行模型映射 |
| 环境不足未验证 | 其他平台真实运行 | macOS x64/arm64、Linux arm64 仅更新锁定资产摘要 |
| 环境不足未验证 | 跨版本数据库回退 | 未验证新数据库迁移后的旧版兼容性；不能把配置事务回滚测试视为跨版本回退证明 |

当前没有进行中或失败待决策的升级工作。真实服务、跨平台运行和数据库跨版本回退不属于已通过证据。可读机器证据见 [omp-upgrade-18.4.5-evidence.json](omp-upgrade-18.4.5-evidence.json)。历史权限质量评测与模型调用预算保持原身份，不改写成新版通过结果。

## 日常配置与恢复边界

`display.hideToolActivity=false` 已部署。执行模型保留 `cursor/kimi-k3-high:high`。权限主审仍为 `session`，远程 fallback 为 `zhipu_tf/glm-5.3-flash`；本地 tiny 的不可用边界保持不变。执行模型与审批模型选择是分别配置的。

一致备份保存在本机私人目录：`/home/weixiaoxian.wxx/.cache/agentcfg/omp/omp-kernel/upgrade-backups/before-v18.4.5-20261001T035109Z.tar`，权限 0600，共 85 个文件，包含实例和部署状态。旧运行包缓存保留，没有自动终止用户会话。

跨版本回退需要恢复匹配的仓库适配器、版本元数据、依赖锁、插件声明和部署状态。管理器按当前仓库锁核验运行包，单独回滚配置或只换回旧二进制不足以恢复旧版启动。恢复旧备份前应另行保存新版产生的会话；数据库兼容性未经验证，本文不提供自动覆盖私人数据库的回退操作。

## 本次问题与处理

升级时同步更新了严格锁 schema 中的版本和 commit 常量。回归发现两组现有测试夹具仍混用历史补丁入口与 standalone 入口，且同步夹具没有提供阻断网络下的假资产缓存；修复均限于测试夹具，不放宽生产校验。临时目录的属主/权限限制通过创建新的私有测试目录处理。

独立 scout 核验升级材料和公开 API。executor 创建和复用因会话线程总数限制不可用，修改、测试和最终部署由主代理执行；没有声称完成了独立执行代理验收。

## 能力限制

官方发布说明包含 Cursor 传输和断流恢复修复，但本次没有验证真实 Cursor 请求，不能断言此前超时或 provider 响应错误已消除。升级不自动增加 `permission_bash` 自定义渲染器、原生后台 job/reap 或本地 tiny 审查能力。

## 2026-10-02：模型名称对齐

用户后续受管启动返回退出码 4。doctor/plan 确认只有 `config.yml` 的 `/modelRoles/default` 漂移：原生当前值为 `cursor/kimi-k3:high`，私人配置仍为 `cursor/kimi-k3-high:high`；运行包与审批配置没有漂移。

固定官方源码的 `packages/catalog/src/compat/rules/taxonomy/_collapse.kdl` 将 `kimi-k3-low/high/max` 合并为逻辑模型 `kimi-k3`，high effort route 仍指向 `kimi-k3-high`；`model-thinking.ts` 按 effort 选择 wire ID。`selector-controller.ts` 持久化当前模型的 provider/逻辑 ID 与 effort，再由公开设置管理写回全局 role。证据支持模型选择操作保存 canonical 名称，不能据此断言每次普通启动都会自动改写，也没有验证真实服务请求。

已在实例租约保护下备份私人机器文件，仅将 `native_model_roles.main` 改为原生当前的 `cursor/kimi-k3:high`。局部 TOML 编辑经完整语义校验，其余字段不变；随后 `plan/apply` 成功，配置文件实际部署变更为 0，只对齐记录基线。最终 doctor 为 offline-ready、漂移/冲突/待变更均 0，无恢复待办。未修改 agent 上游源码或放宽运行保护。

在用户报错的 `/data/1/weixiaoxian.wxx/test_tool/group_commit_leader_switch` 目录执行完整受管启动准入，通过后使用不启动宿主的回调返回；剔除密钥环境绑定，不发真实模型请求。工具活动显示与审批 sidecar 保持原配置。已完成诊断、修复、部署与准入验证，无进行中或失败待决策项；真实 Cursor 推理仍为未验证。后续机器证据见 [omp-cursor-model-alignment-20261002.json](omp-cursor-model-alignment-20261002.json)，原 2026-10-01 验收 JSON 保留历史身份和当时模型字段。

## 2026-10-02：Cursor 原生 Bash 审批覆盖限制

用户报告只读命令出现 `Allow tool: bash`。只读会话取证确认，2026-10-02T15:11:37.142Z 的两次工具调用来自 `cursor/kimi-k3`，工具名都是 `bash`，其中一条与用户提供的 find pipeline 相符；后续工具调用才来自执行模型 fallback 的 `kimi_tf/k3`。用户提供的插件 status 为 smart、configuration ready、generation 1，主审/远程/插件人工调用计数均为 0。这些证据确认插件已启用，而所示命令没有经过 `permission_bash` 的审查。没有打印其他命令、会话正文或账号数据。

固定官方源码中，`packages/ai/src/providers/cursor.ts` 的原生 `shellArgs`、`shellStreamArgs` 合成工具名 `bash`，`packages/coding-agent/src/cursor.ts` 的 shell/stream/piBash 同样按该名字执行。普通 MCP 工具定义和调用保留自定义名称，故 `permission_bash` 可以通过该路径使用；这不使原生 shell 通道自动改名。Cursor bridge 使用注册工具 registry，移除模型 active tool 列表中的 bash 不足以改变原生 frame 的固定目标。未抓取 OAuth wire frame，不能把源码路径分析记为该次 frame 的直接观测。

公开 `tool_call` 结果仅提供 block、reason、input 和 additionalContext。wrapper 会在 hook 后重新运行完整原生 approval gate；返回非阻断结果不会批准 prompt，`tool_approval_requested` 也是通知事件。因此只添加 review hook 不能实现透明自动批准。注册同名 bash 会替换 registry 的执行实现；将原生 bash 改为 allow 又会削弱插件未加载时的保护，两者均未采用。没有修改上游源码、审批策略或日常执行模型，也没有发新模型请求。

本轮已完成覆盖限制诊断和文档修正，不能将 OpenAI 兼容假 provider 的宿主 smoke 解释为 Cursor 原生命令智能审批通过。当前能力是：独立 `permission_bash` 内部智能审批；Cursor 原生 bash 保持宿主审批。不能靠声明 smart 或配置 remote reviewer 达成透明覆盖。关于现有公开 API 能否安全包装原生工具的最初结论过于保守，后续复核见下一节。真实审批质量及精确 OAuth frame 仍未验证；未将能力缺口记为修复完成。

## 2026-10-02：公开 API 包装方案复核

用户追问是否无法解决后，重新核对固定官方源码，确认无需宿主补丁的改造路线，撤回“同名注册属于未明确保证的替换能力”这一判断。公开 `ExtensionContext.invokeTool()` 的文档明确支持插件重新注册同名内建工具，再委托原生实现；它保留原生副作用与内部 bookkeeping。同名包装属于公开扩展 API 的用法，不等于修改上游源码、二进制或 monkey patch。

| 接口证据 | 作用 |
|---|---|
| `extensions/types.ts:539–552` | 公开 `ctx.invokeTool()`，同名内建工具委托与递归边界 |
| `extensions/runner.ts:664–695` | 使用预先保留的同名原生实现，继承外层已通过的审批 |
| `agent/src/types.ts:1037–1048` | 公开 `ToolApprovalDecision.policyKey` |
| `tools/approval.ts:187–217` | 独立 policyKey 优先解析；未配置时回退到工具名策略 |
| `sdk.ts:3303–3345` | 先保存原生工具，再注册扩展包装器 |
| `cursor.ts:591–612` | Cursor 原生 shell 查找 registry 的 bash，可进入同名包装器 |

拟议方案为：插件注册公开的同名 `bash` 工具，外层使用独立 `policyKey: permission_bash`，执行函数在模型审查或人工确认后调用 `ctx.invokeTool()`。现有 `tools.approval.bash=prompt` 保留；插件缺失时 registry 回到内建 bash，仍受原生 prompt 保护。插件加载但配置不可用时必须阻止执行，不可仅依赖外层 allow。原生委托不重复运行外层 approval gate，所以必须保留原生 deny/prompt patterns，并在委托前完成全部必要检查。

本次状态为已确认公开接口及配置解析支持，尚未实施、尚未真实宿主验证。待实现验证项包括：Cursor 原生 frame 实际进入包装器；低风险自动执行且只执行一次；deny patterns 不被独立键绕过；审查不可用时转人工或阻止；插件缺失仍回原生 prompt；参数、cwd、取消、超时、会话/模型变化与原生后台语义正确保留。不得将静态接口复核标为修复或测试通过，也不把原始 OpenAI fixture 当作该路线的验收。

## 2026-10-03：同名包装隔离可行性验证

用户要求细化方案和确认可行性后，使用未修改的官方二进制、隔离 HOME、确定性 loopback provider 完成同名 bash 包装原型。7 项纯原型测试、固定官方 SDK 严格检查及 6 组宿主机制测试通过。允许时只委托并实际执行一次无害 ls；拒绝/不可用不执行；插件缺失时原生 prompt 阻止无 UI 执行。公开 BashTool.approval() 的五类判定、工具事件中的当前 Settings、内存 override 读取和并发 scope 隔离也已运行验证。

直接 Cursor handler 分派探针及单入口 bundle 替代尝试均因 standalone 包导入 ResolveMessage 未通过；源码路由证据保留，真实 Cursor OAuth 端到端仍未验证。bundle 尝试还证实，安全钩子独立扩展加载失败不会自动阻止另一个包装扩展执行，因此生产方案必须将检查与执行集成，并在执行时强制校验有效票据。这些失败没有计作通过。

本轮没有付费/外部推理、没有修改生产插件、锁、私人配置或部署，原审批质量历史结果保持原身份。完整方案与实施验收分包见 [Cursor 原生审批方案](../follow-ups/omp-cursor-native-approval-plan-2026-10-03.md)，安全摘要见 [机制证据](omp-bash-wrapper-feasibility-20261003.json)。上述结果确认改造路线的核心机制可用，不等于当前日常 Cursor 智能审批缺口已修复。
