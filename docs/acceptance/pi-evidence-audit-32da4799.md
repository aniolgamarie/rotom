# 证据登记逐 V 项覆盖审计（锁 32da4799）

本文件记录 scope 逐项登记时的覆盖判定依据：每个 V 项映射到哪些真实执行证据，以及为什么这些映射成立。原则：不把 native 汇总复制给所有 V 项；每个映射都对应具体 case 的具体验证内容。

## 身份口径

- 每配方 identity = `identity_for(lock, runtime, policy, resources, machine_contract)`，取自**第一目标**部署工作区投影（`load_workspace` + `diagnostic_identity`）。已验证 identity 随目标特异（端口/路径进入机器契约），故登记统一采用第一目标口径，第二目标的同候选通过证据由冷重建报告承载但不重复登记为 scope 证据。
- linux-x86_64 之外的格子身份保持空（无机器），live 项身份同配方冻结。

## pi-host（四配方 × 10 V 项，mock+native）

| V 项 | mock 依据 | native 依据（case → 验证内容） |
|---|---|---|
| V01-inventory | 全量 mock 覆盖清单/来源/依赖链检查 | host-resources：manifest 资源/模型/工具/角色清点与身份核对 |
| V03-dependencies | 锁/vendor/来源核对测试 | host-resources + 冷目标 installation=verified（真实锁 sync/npm ci） |
| V04-launch | 启动/渲染测试 | host-resources：真实 SDK 会话启动与模型往返 |
| V05-resources | 资源/技能/提示/主题加载测试 | host-resources（Todo 全往返）+ **readseek-tools（九工具真实流程）** |
| V08-recovery | 恢复/租约故障点测试 | termination-recovery：recovery-grants 真实第一方进程恢复授权链 |
| V09-supervision | 监督/命名空间/门控测试 | termination-recovery（parent-loss 真实杀宿主+worker撤权）+ 宿主命名空间 smoke |
| V10-manager | manager 唯一性/加载测试 | host-resources：manager_limit=2 核验 + taskkeeper-lifecycle（managed） |
| V13-permissions | 权限策略/越权拒绝测试 | budget-permissions（guarded_denial+no_file_admission）+ readseek-tools（越界写拒） |
| V17-optional-software | 可选软件处置测试 | host-resources（插件加载清单）+ codex-receipts（codex 配方 CLI 资产）+ readseek-tools（default/codex 的 readseek 启用） |
| V20-cold-rebuild | 冷重建契约测试 | 冷目标本体：双新 HOME/checkout 完整安装+原生通过（报告+SHA索引） |

## agentcfg-pi（四配方 × 6 V 项，mock）

V02-schema、V06-credentials、V07-migration、V18-diagnostics、V19-dsh-compatibility、V21-upgrade：完整 mock 套件对应测试族（schema 严格/凭据哨兵/迁移冲突/doctor 分层/DSH 回归/升级失效），登记 mock 级 passed；native 层不适用（层级声明为 mock）。

## model-delegate（default/codex/cursor × 4 V 项，mock+native）

V16-delegate、V22-control、V23-batch-progress、V24-retirement ← model-delegate-replacement case：七个 preset 实跑、独立 CLI 控制八操作（cancel/poll/probe/result/resume/start/status/wait）、batch 有界并发、旧七角色缺席与工具命名核验；codex 配方另由 codex-receipts 承载官方 CLI 只读/写入/控制。

## task-keeper（managed × 5 V 项 + 4 live 项，mock+native；live 未登记）

V10/V11/V12/V14/V15 ← taskkeeper-lifecycle：11 项生命周期场景（inspect/fix/second-view/budget/quota/missing-result/pause-resume/stop/schedule + 两项 proxy）实跑。live-direct/proxy 四项无真实模型前提，保持 not-run。

## 不登记为 passed 的项（真实缺口）

- 全部 live 项（6 服务 + 4 Task Keeper live）：等用户 local 配置/项目/账号绑定。
- linux-arm64、darwin-arm64、darwin-x86_64 全部格子：无机器。
- pi-cursor 的 ReadSeek：Bun 宿主下 worker 的锁定 node 解释器绑定未设计（场景级排除，配置依据见实施记录（三））。
- pi-managed 的 model-delegate 普通委托：managed 按能力矩阵使用 Task Keeper 工具， ordinary 委托不在 managed 配方声明。
