# OMP 实施记录

日期：2026-09-24。Feature：`002-manage-omp-config`；实际 Git 分支：`main`。

当前 spec **已完成，62/62 项**（T001–T061、T066）。按用户[范围修订](scope-change-20260924.md)，原 T062–T065 和 T061 的 Linux arm64 部分转入[OMP-F01–F05](../../docs/follow-ups/omp-platform-and-live-validation.md)，不计当前待办。软件隔离验收及 Linux x64 九行原生 smoke 通过；其他平台或账号验证仍未执行，未计为通过。

## 已完成

- 前置检查通过，requirements checklist 16/16，检查标记保持只读；现有 Python `.venv`、忽略规则和无扩展 hooks 的状态已核实。
- 基础与 US1：严格配置、九行资源映射、秘密守卫、所有权、依赖锁、生命周期与 capture 完成，见[基础](evidence/foundation.md)、[US1](evidence/us1.md)。
- US2：稳定原生 profile、独立 HOME/XDG、运行参数、固定发现清单及项目来源门控完成；补充拒绝 bootstrap 新增扩展路径/provider，见[US2](evidence/us2.md)。
- US3：只读 inventory、私人候选提案、手工审阅后新环境部署、pending 恢复和显式登录入口完成，见[US3](evidence/us3.md)。旧认证和会话不复制。
- US4：原生与受管 usage、完整字节流/退出码透传和身份隔离完成；固定源码与官方资料复核完成，见[US4](evidence/us4.md)、[来源](evidence/usage-sources.md)。AGENTCFG-F01 的软件范围关闭，真实账号 usage 未验证。
- US5：完整正式锁最终重新解析并 read_lock 校验；101 项资源、2 个包、15 项配方输入、4 个平台资产。发现清单纳入配方锁，见[US5](evidence/us5.md)。缓存维护、失败恢复和平台替身测试通过。
- 秘密边界、跨工具/双 profile 哨兵、DSH/Pi 兼容性和最终全量回归通过：**2151 passed, 7 subtests passed in 124.04s**，退出 0；其中 OMP 测试 281 项。见[回归](evidence/regression.md)、[安全](evidence/security.md)。
- README、配置/profile/迁入/usage/依赖/支持文档、quickstart、FR/SC 追踪和任务状态已更新；相对链接与 diff 空白检查通过。
- 执行分工：主代理负责设计取舍、依赖后端、资源、usage、inventory、集成测试与最终验收；executor 实际模型 **gpt-5.6-sol / medium**，负责适配器、身份、发现与操作门控；scout 实际模型 **gpt-5.6-luna / medium**，负责固定源码及来源证据复核。额外 executor 因线程上限未启动，其工作由主代理承接，没有计为多模型完成。

- T061：用户回复“下一步”授权后，Linux x64 真实九行 smoke 通过，双轮 TUI 正常退出 0；规则/技能标记、角色切换、主题、按键、prompt、扩展和官方 SDK MCP tools/list + tools/call 均有实际证据，见[Linux smoke](evidence/linux-smoke.md)。新增显式自检扩展后，正式锁及样例摘要同步；受影响回归 **57 passed in 10.30s**，最终 doctor 无漂移、运行包完整。未登录/查询 usage/调用模型。

- 提交前审查：修复 schema 严格性及两项 OMP 来源/身份门禁遗漏，正式锁同步；最终全量 **2160 passed, 7 subtests passed in 126.29s**，退出 0；暂存区范围、链接、秘密模式和空白检查通过，见[提交前审查](evidence/precommit-review.md)。

## 进行中

- 无；当前 spec 范围内工作已完成。

## 失败待决策

- 无。首轮全量回归的通用 lock 命令兼容失败已修复，针对性测试和最终全量均通过；实际发现的来源门控、数据库旁文件和 rollback 秘密投影问题均已修复并验证。

## 环境不足未验证（已转独立遗留，不阻塞本 spec）

- OMP-F01：Linux arm64 实机未提供环境，原 T061 的未覆盖部分已转出。
- OMP-F02（原 T062）：macOS 两架构实机未提供，已转出，未验证。
- OMP-F03/F04/F05（原 T063/T064/T065）：真实登录、账号 usage、指定 provider/model 调用环境未具备，用户明确转出，均未验证。未来恢复时再确认所需环境与对应授权，当前无需提供账号或测试机。
- 以上不影响隔离测试通过的事实，也不能由隔离测试推定原生加载、真实账号、服务或其他平台通过。本轮已运行真实 Linux x64 发布二进制，其他平台和账号范围不据此判为通过。

范围修订仅调整验收归属；软件功能、已有测试和原生证据不变，没有把转出任务勾选为通过。
