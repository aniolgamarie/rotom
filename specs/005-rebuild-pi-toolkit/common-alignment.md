# 公共治理差异与验收矩阵

日期：2026-10-18。源码基点见 [实施记录](implementation-status.md)。这是当前源码盘点，
不是新 Pi 或三宿主本轮测试已通过的证据。文件路径以下均相对于仓库根。

| 场景 | 当前共同实现 | 原生差异 | 缺口及处理 | 验证入口 |
| --- | --- | --- | --- | --- |
| 配置/覆盖 | `workspace.load_public_catalog/load_workspace` → `config.resolve_config` → `merge_layers` | 各 adapter schema、validate、原生投影 | 已共用；保留严格未知字段、数组替换、空值和引用校验，不复制 Pi 管线；新旧 catalog 切换须完整校验 | `tests/test_config_schema.py`、`tests/test_config_resolution.py`；T009/T013/T022 |
| 完整依赖 | `backends.DependencyBackend`、commands lock/sync 编排、`storage.Tree` | DSH pnpm；OMP 资产/Bun；Pi 将重建 npm backend | 复用接口及真正相同的身份/文件安全/暂存原语；保持各自锁、目录和安装行为 | `tests/test_dependencies.py`、`test_lock_publication.py`、`test_omp_dependencies*.py`；T011/T015/T023 |
| 部署冲突 | `commands.current_plan/apply_candidate` → `deployment.plan/apply/write_changes` | adapter 的文件与 selector、凭据叶子保护 | 已共用三方比较；Pi 只提供受管投影，不另建事务引擎 | `tests/test_deployment.py`、`test_dsh_pipeline.py`、`test_omp_adapter.py`；T010/T014 |
| 配置恢复 | `deployment.recover/transact`、公共 pending journal | DSH 历史路径 state_guard；OMP/Pi 认证引用保护 | 区分公共配置恢复与旧 Pi 任务恢复；后者不迁入公共核心 | `tests/test_deployment.py`、`test_runtime_preparation_recovery.py`；T010/T014/T039 |
| rollback | `deployment.rollback` 的写前检查、逆变更与备份消费 | 各原生字段和引用 guard | 保留用户新增内容；不回滚软件、账号、会话或任务库；无变化不轮换 | `tests/test_deployment.py`；T010/T014/T048 |
| 活动保护 | `runtime.run` 持物理、state、运行包租约，并向直接宿主传递 FD | DSH/Pi 锁实例目录及 `.agentcfg-instance.json`；OMP 独立 `.agentcfg-omp.lock` 与 owner nonce | 共享中性 flock 操作，保留 marker 与布局；不能把直接进程继承 FD 推断为全部后代空闲 | `tests/test_omp_runtime_foundation.py`、运行集成测试；T012/T016–T018 |
| 多主会话/维护竞争 | DSH/OMP shared 运行锁、exclusive 维护锁 | Pi 旧 `activity`/ExecutionStore/lease 属于专属执行平台 | 新中性逐运行 owner 须独立设计：登记/退出只改自身，未知后代保留保护，维护检查受同一排他协议保护；不搬运旧任务账本 | `tests/test_omp_runtime_foundation.py` 的双运行/维护阻断；T012/T016/T021/T037 |

## 文件和责任边界

公共解析/合并/渲染、部署、存储已有共享实现；先补足行为证据，再决定必要修改。
DSH/OMP/Pi 薄适配保留原生格式、账号 home、凭据引用与包管理；公共配置模型不增加宿主专用键。
`shared/defaults/models.toml` 和共享 registry 不能当作 Pi 独占资源整文件移除。

物理生命周期锁与 `state_root/instance.lock` 是不同层。运行入口按 adapter hook 取得锁，
`runtime.run` 将实际物理/state/package FD 传给直接宿主；不移动 OMP marker 或 DSH 实例目录。
现有证据不能证明守护化、脱组或主动关闭 FD 的后代都被覆盖；未确认状态必须保持 unknown，
不能靠超时、父退出或进程组为空自动清除归属。新的逐运行协议由主代理评审后实施。

## 来源与结果限制

上述映射经 scout 只读源码调查：`workspace.py`、`config.py`、`backends.py`、`deployment.py`、
`runtime.py`、`lifecycle.py`、`storage.py`、`omp_identity.py`、`pi_lifecycle.py`，以及表中测试源码。
调查未运行宿主、测试、服务或账号。旧 Pi 测试只证明旧协议，不能抵扣重建后的运行验收。
