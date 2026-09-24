# Implementation Plan: OMP 配置纳入统一管理

**Feature context**: `002-manage-omp-config` | **实际 Git branch**: `main` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

**Input**: `specs/002-manage-omp-config/spec.md`，含两项已确认澄清：仅新建独立环境并允许重新登录；首版八类配置全部交付。

> 2026-09-24 范围修订：当前实施及验收已完成，当前真实验收仅本机 Linux x64 无账号 smoke；Linux arm64/macOS、真实登录/usage/模型调用见[独立遗留](../../docs/follow-ups/omp-platform-and-live-validation.md)，不再作为本 spec 完成前提。历史设计阶段描述不代表当前实施状态。

## Summary

新增独立 OMP 适配器和依赖后端，复用 agentcfg 的配置分层、字段/文件所有权、三方部署、备份、恢复和运行门控。固定 OMP v18.3.0 官方 standalone 发布包及不可变提交，不继承 Pi 的原生目录/扩展兼容结论，不修改宿主源码。

每个 rotom 配方确定性绑定一个新原生命名 profile，同时提供独立 HOME/XDG，保留 OMP profile 原生能力并隔离其共享设施。模型/provider、角色、规则、完整技能、提示词、主题与快捷键、扩展、MCP 各有明确字段和可用样例。迁入先只读盘点、审阅非秘密提案再部署；旧账号和会话保留原位。

补齐 AGENTCFG-F01 的 `agentcfg usage`：无显式 profile 时直接透传 PATH 上原生 OMP；显式 profile 时复用已部署身份和依赖，保留原生参数、输出、退出码及窗口/缓存语义。用量不扩展为独立订阅认证或采集系统。

## Technical Context

**Language/Version**: Python 3.11+；OMP v18.3.0，commit `62bc57be1b03ef0802a33cf7f5f530e534527531`；首个扩展为无外部依赖的 TypeScript 原生包。

**Primary Dependencies**: 沿用 PyYAML、jsonschema、Jinja2、pytest 与仓库 `.venv`；官方 OMP standalone 内嵌运行时，管理器不另装 Bun/Node；完整上游依赖锁与本地资源身份进入 OMP lock。

**Storage**: 公共 registry/profiles/local 为 TOML；OMP config/models/keybindings 为 YAML，MCP/theme 为 JSON；公共部署状态、owner、runtime receipt 为非秘密 JSON；原生认证/会话不进入配置备份。

**Testing**: pytest 临时 HOME/XDG、断网、假进程、虚构 provider/model 与跨实例哨兵；DSH/Pi 回归；本机 Linux x64 宿主 smoke 已授权并通过；其他平台与真实登录/usage/模型验证转独立遗留。

**Target Platform**: 设计覆盖 Linux glibc x64/arm64、macOS x64/arm64；musl/Windows 明确拒绝。平台通过声明以实际验证为准；当前 Linux x64 已通过，arm64/macOS 实机及账号验证转独立遗留。

**Project Type**: 现有 Python CLI 的新原生适配器，不新增服务、数据库或独立管理器。

**Performance Goals**: 不新增无依据的延迟指标；离线配置命令零宿主启动、零网络，未变化 apply 零目标重写/备份轮换；usage 直接继承输出流，不聚合或缓存结果。

**Constraints**: 未知输入失败；秘密值不进入通用数据/日志/备份；两层 profile 稳定可解释；新建而不接管；run 不隐式安装/部署/登录；不执行技能或加载扩展来验证配置；无法关闭的原生来源由 preflight 阻止未声明加载。

**Scale/Scope**: 个人管理仓库，多工具和多配方；28 FR、7 SC、5 用户故事；八类能力拆九行验收；独立 usage 两模式。首版不覆盖所有原生字段/扩展，不修复无关 DSH 或全仓秘密存储缺陷。

## Constitution Check

Phase 0 预检查完成；Phase 1 设计复核通过，无需要豁免的偏离。通过指设计满足约束，不代表实现或原生验收已通过。

| 宪章门禁 | Phase 0 | Phase 1 决策与证据 |
|---|---|---|
| I 公共核心与真实适配 | 适用 | OmpAdapter/OmpDependencyBackend 复用公共生命周期；严格独立能力映射，不以 Pi 兼容代替证据；见能力契约 |
| II 秘密与所有权 | 适用 | 独立 HOME、稳定身份、物理实例 owner/lease；字段级引用守卫覆盖当前与历史状态；auth/session 不导入；见数据模型 |
| III 确定性与恢复 | 适用 | 确定性渲染，三方比较/pending/previous 沿既有部署器；配置 rollback 不降级软件；见运行契约 |
| IV 显式副作用与依赖 | 适用 | lock/sync/apply/run 分离，完整锁及正文校验，暂存成功再激活；默认检查离线；见依赖契约 |
| V 隔离测试与证据 | 适用 | 24 验收场景映射全部 FR/SC，九行能力必须实际成功；未执行不算通过；见验证矩阵 |
| Pi 特定迁移来源/实现要求 | 本次不适用 | 本需求为 OMP，新环境不绑定 starter 或 Pi 原生 home；现有 Pi 行为作为回归保护 |
| 文档中的历史支持声明 | 需区分 | 宪章保留历史 DSH/Pi 状态；本计划不修改宪章、不宣称 OMP 已受支持；实现验收后更新支持文档 |

## Project Structure

### Documentation (this feature)

```text
specs/002-manage-omp-config/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── validation-matrix.md
├── contracts/
│   ├── cli-and-configuration.md
│   ├── native-capabilities.md
│   └── runtime-and-dependencies.md
├── specification-progress.md
└── checklists/requirements.md
```

tasks.md 由下一步 `$speckit-tasks` 生成，本次不生成实施任务或产品代码。

### Source Code (repository root，计划修改范围)

```text
src/agentcfg/
├── omp.py                    # OmpAdapter、能力映射与字段意图
├── omp_dependencies.py       # standalone 与完整运行包后端
├── omp_identity.py           # profile/HOME/XDG/owner/lease
├── omp_discovery.py          # 固定版本来源检查及非秘密报告
├── omp_inventory.py          # 只读盘点与安全候选资源
├── usage.py                  # 两种透传模式及参数边界
├── cli.py, commands.py       # omp 选择、inventory 与 usage 分发
├── workspace.py, config.py   # 注册适配器与严格配置校验
├── adapter.py                # 必要的引用守卫元数据
├── native_projection.py      # 精确 bare-env guard 与强制分类
└── runtime.py, process.py    # 复用门控的操作上下文和环境构造
agents/omp/
├── agent.toml, bindings.toml, plugins.toml, content.toml
├── resources/                # prompt/theme/完整资源
└── packages/                 # OMP 原生示例扩展与本地 MCP fixture
locks/omp/
├── manifest.json
└── upstream/                 # 完整 bun.lock、来源及许可证
profiles/omp-default.toml
schemas/                     # omp 配置/锁 schema 与现有 agent 枚举扩展
examples/                    # 纯虚构、可独立验收的 OMP 示例
tests/test_omp_*.py          # 默认隔离契约与失败场景
docs/                        # OMP、迁入、usage、支持与遗留事项
```

**Structure Decision**: 保持单仓库现有职责分层。OMP 事实留在适配器模块，公共改动仅用于适配器注册、精确引用守卫和可复用运行操作；不抽象整个 Pi 特有监督/恢复系统。公共 schema 只增加真实需要的枚举/严格能力入口，prompt/theme 留在 adapter resources catalog。

## 设计交接与实施顺序

1. 固定 schemas、原生 identity 和参考样例，再实现八类转换及确定性 render；同时补充 OMP 凭据叶子守卫，避免先产生可泄密的状态格式。
2. 形成完整 OMP lock 与原子 sync 后端；runtime receipt 必须能与 deployment 对应，运行包缺失不能回退 PATH。
3. 接入 owner/lifecycle gate、来源 preflight、apply/rollback/pending 恢复、doctor/capture；先验证两配方与默认环境哨兵。
4. 接入只读 inventory、原生/受管 usage 两分支和显式 login；native usage 必须在加载 workspace 前分发。
5. 完成隔离验收与 DSH/Pi 回归，更新文档；完成本机 Linux x64 无账号真实宿主验收，依实际证据更新 AGENTCFG-F01 状态；其他平台/账号验证单独登记遗留。

这只定义设计依赖顺序；任务切分、编号及实施进度交给 tasks 阶段。实施中若固定源码行为推翻八类能力或隔离前提，应回到本计划调整设计，不能默默删减类别或放宽边界。

## 风险与验证限制

- 上游原生 profile 不隔离所有服务；独立 HOME 是本设计必要条件。XDG 存在性会改变路径，需守卫而非猜测。
- 原生 project/direct/dotenv 发现无法完全用一个配置关闭；preflight 按固定源码路径检查，属于配置准入，不能宣称 OS 沙箱。启用项目来源仍必须逐项校验。
- bare-env 未设置时原生可能当 literal，管理器必须在 spawn 前解析并检查 SecretRef。guard 丢失/历史快照篡改同样不能绕过敏感叶子分类。
- 官方校验和和源码只证明设计依据；本机 Linux x64 二进制、扩展/MCP 已实际验收；其他平台二进制与真实账号流程由独立遗留补齐，不阻塞当前 spec。国内智谱专用用量插件页面尚未取到，不宣称 OMP 支持其额度接口。

## Complexity Tracking

无宪章违规或豁免。独立 identity/source-policy 模块是为了兑现 OMP 原生差异；不新增部署框架、数据库、宿主补丁或订阅采集服务。

## Phase 0/1 产物索引

- [研究与来源](research.md)：R01–R09 的决策、依据和替代方案。
- [数据模型](data-model.md)：身份、资源、秘密引用、状态转换。
- [CLI 与配置](contracts/cli-and-configuration.md)、[原生能力](contracts/native-capabilities.md)、[运行与依赖](contracts/runtime-and-dependencies.md)：实现接口和不变量。
- [验证指南](quickstart.md)与[覆盖矩阵](validation-matrix.md)：隔离运行步骤、真实验证边界及需求映射。
- [任务记录](specification-progress.md)：本轮完成项、执行分工和未验证范围。
