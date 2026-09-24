# 最终隔离回归

> 本文保留软件隔离阶段的原始结果与当时限制；后续已授权的 Linux x64 真实验证见 [Linux smoke](linux-smoke.md)，不能将本文历史“未执行”理解为当前平台状态。

日期：2026-09-24。执行者：主代理。范围：T059/T066、V01–V21/V24 的隔离部分、FR-001–FR-028 的软件行为和文档部分；真实宿主/账号部分另列未执行。

环境：Linux x86_64 / glibc 2.32，Python 3.11.11。管理器基线提交 `e208e2df50c7f21095d2ec7eb081dfc4df4f7156` 加本次未提交工作树；OMP v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`。该次全量对应正式锁身份 `2227b4e7de27f28f2963e33facdf6d977d4d6924e72bbed35690e884bb3c74c2`，详细来源及 SHA 见[来源证据](source-provenance.md)和[依赖维护](us5.md)。

授权：用户实施请求覆盖默认隔离测试；全程使用临时 HOME/XDG、网络阻断、假子进程和合成账号/资产。因执行工具默认沙箱的目录所有者视图与当前 uid 不一致，文件系统测试经自动审批在正常权限视图运行；仍保留测试内隔离保护，没有放宽生产权限检查。没有真实宿主或账号操作。

```sh
.venv/bin/python -m pytest -q --tb=short
.venv/bin/python -m pytest --collect-only -q tests/test_omp_*.py
```

最终全量退出 **0**：**2151 passed, 7 subtests passed in 124.04s**，无失败、无跳过；OMP 范围静态收集 **281 tests collected in 0.60s**，这些测试均已在全量实际执行通过，收集本身不充当通过证据。其余 1870 项为既有测试（包括 DSH/Pi 与公共管理器路径）。

首轮全量退出 1：2 failed, 2138 passed, 7 subtests passed in 125.02s。两项失败来自通用 cmd_lock 对直接调用的 Namespace 强行读取 agent；改为可选属性读取后，受影响 extensibility 与新增迁入场景组合 **9 passed in 9.46s**。随后补齐来源门控测试与固定清单，再执行上述最终全量；没有在无新变更时反复重跑。

关键断言包括九行配置的隔离生命周期、两个受管 profile/旧 default/两个原生命名 profile/DSH/Pi 哨兵零意外变化，审阅迁入的非空冲突与 pending 恢复，usage 两模式的二进制流及任意退出码透传，0/2/3/4/5/6 错误契约，秘密字段与历史 guard、缓存正文/目录/解释器及包租约验证。具体测试入口与 FR/SC/V 对照见[矩阵](../validation-matrix.md)和各故事证据；[安全证据](security.md)记录实际 rollback 失败及修复。

静态收尾：修改文档的本地 Markdown 链接检查通过，`git diff --check` 通过；检查清单保持原标记；`.specify/extensions.yml` 不存在，无实施后 hook。

限制：T061–T065 均未执行。九行原生加载、真实启动零自动安装、登录、真实 usage、模型生成以及所有平台实机表现不能由上述结果推断；macOS 环境未提供。无 SIGKILL/物理断电实验。

后续新增显式 inspect/mcp 自检后，正式锁更新为 `0387bc982c13d768c77cf1be42b0243ebd0fabb0aa0a7ca9048e903d1d1134eb`；受影响隔离回归 57 项通过，真实命令与边界见[Linux smoke](linux-smoke.md)。

后续提交前审查补齐 PERSONALITY 来源与 PI_CONFIG_DIR 门禁，清单和正式锁再次更新；最新结果见[提交前审查](precommit-review.md)。上述测试计数及摘要保留为各阶段历史证据。
