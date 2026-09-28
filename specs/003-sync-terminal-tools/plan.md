# Implementation Plan: 同步代理与终端工具配置

**Branch**: 未创建（feature path: `003-sync-terminal-tools`） | **Date**: 2026-09-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-sync-terminal-tools/spec.md`

## Summary

新增独立 `./termcfg`，按组件同步 zsh、tmux 与代理能力。zsh/tmux/代理管理器的公开配置文件采用**备份目标旧文件后复制覆盖**；mihomo core 由显式 `lock`/`sync` 安装为版本化运行包，代理组件还包含非秘密基础配置与显式服务命令。私人订阅、密钥和运行状态留在独立私人目录。一次 `apply` 中所有选中组件的配置目标先完成备份再写入；写入有冲突检测、恢复日志和上一版**配置**回滚，软件版本不随配置回滚。配置同步不会重载现有服务或会话。

## Technical Context

**Language/Version**: Python 3.11+；shell 与 tmux 原生配置保持其各自格式

**Primary Dependencies**: 仓库现有 PyYAML、jsonschema、pytest；Python 标准库文件/进程接口；锁定的 mihomo core 官方发布资产。zinit/TPM 等远程插件使用完整锁与显式准备；fzf 为可选本地能力。

**Storage**: 私人机器配置、状态、机器级活动锁、按规范仓库路径共享的依赖锁读写租约及版本化运行包位于 XDG 目录；受管目标在选定用户 HOME；公开源与依赖锁在仓库；代理订阅/密钥/日志/统计留在 mihomo mgr 私人运行目录。运行包不含秘密，目录 0700、非执行资源 0600、执行入口 0700，区别于始终 0600 的私人配置文件。

**Testing**: pytest、临时 HOME/XDG、假 core/API/子进程、网络阻断与文件哨兵；真实 core、真实 HOME、tmux server 和订阅网络只在独立授权 smoke 中验证。

**Target Platform**: 第一验收目标 Linux x86_64 用户态环境；其他 OS/架构通过明确平台锁与独立证据扩展，未验收时报告 unsupported/未验证。

**Project Type**: 仓库内独立 CLI；可复用 agentcfg 的通用安全文件原语，但不扩展 Agent profile/adapter 的目标所有权。

**Performance Goals**: 典型三组件少量文件的只读 plan/doctor 在本地离线环境完成；网络下载不在 plan/apply/service status 中发生。首次预览不超过 3 条命令，交互式 apply 不手抄 ID；联网与服务等待每 2 秒内有阶段/心跳，按契约超时后退出并报告副作用与下一条命令。上述均由 quickstart 和隔离测试验证。

**Constraints**: 私人值不进入 Git、公开来源、普通配置备份/状态/日志；旧目标先通过非秘密准入才可计算普通内容摘要；不以未知文件自动接管；没有锁定 core 时 apply 不退回 PATH/latest；不自动重启服务、shell 或 tmux；多文件只保证可恢复，不宣称绝对原子。

**Scale/Scope**: 单用户、多个机器配置；首版 3 个组件，预期每组件数个到数十个受管目标，不接管整棵 HOME 或代理运行目录。

## Constitution Check

*GATE: 设计在 Phase 0 前检查，Phase 1 后复核。以下均为必须满足的实施约束；没有申请宪章豁免。*

| 原则 | 设计落实 | Gate |
| --- | --- | --- |
| I. 公共核心与真实原生适配 | `termcfg` 独立处理非 AI HOME 目标，不放宽 agentcfg 的实例/适配器契约；输入字段未知即拒绝。 | PASS |
| II. 秘密隔离与明确所有权 | 公开基础配置与私人订阅/密钥拆分；任意待覆盖旧目标若不能归类为非秘密则拒绝自动备份；首次接管需明确选择；私人配置/状态 0600、目录 0700，非秘密运行包执行入口按必要的 0700 执行模式核验。 | PASS（实施前须验证准入与拒绝路径） |
| III. 确定性部署与可恢复状态 | 同一机器的写操作先取得独占活动锁；维护者更新共享依赖锁另取仓库级独占租约并复核旧身份，sync/apply 持共享租约复核快照；一次 apply 的所有配置备份先完成，写前复查，单文件原子替换，多文件 pending 恢复，已受管目标三方比较；仅保留上一版有效配置备份，漂移拒绝覆盖/恢复，配置 rollback 不降级 core。 | PASS |
| IV. 显式副作用与可复现依赖 | `lock` 显式解析并固定 core/插件完整依赖；`sync` 只安装现有锁的版本化包；`apply` 只离线复制配置；`service` 才显式启停/重载，禁止旧脚本默认下载 DB 或自安装插件。 | PASS |
| V. 默认隔离测试与证据 | 临时 HOME/XDG、假进程与网络阻断；真实 core/订阅/用户 HOME/macOS 单独标注授权与证据。 | PASS |
| 技术与退出码 | 使用仓库 `.venv`、现有 Python 风格和 0/2/3/4/5/6 退出码；真实服务进程退出状态不冒充配置同步成功。 | PASS |

**适用性说明**: 宪章中 DSH/Pi 的模型转换、原生 OAuth、完整 npm 锁与 Pi 专用迁移条款不适用于非 AI 终端组件；秘密隔离、路径所有权、依赖锁、事务恢复、默认隔离测试和错误语义适用。旧 starter 不被修改，也不作为运行时路径。

**Phase 1 复核**: [research.md](research.md) 已明确旧安装脚本不可直接复用、mihomo core 必须单独锁定、公开/私人配置分离及 shell/tmux 隐式联网必须移除。[data-model.md](data-model.md)、[命令契约](contracts/cli.md)和 [同步契约](contracts/sync-state.md)将这些边界编码为状态与接口。当前设计无已知宪章冲突；若实施发现无法在不备份秘密的前提下接管某个旧文件，该目标必须停在冲突状态，不能用用户确认代替宪章约束。私人有效 YAML 仅在显式服务操作的 0700 私人运行目录内使用结构化序列化器生成、校验并以 0600 保存，不进入普通渲染或状态产物；core 与配置待生效原因分别记录。

## Project Structure

### Documentation (this feature)

```text
specs/003-sync-terminal-tools/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── contracts/
│   ├── cli.md
│   └── sync-state.md
├── quickstart.md
└── tasks.md                  # 后续由 $speckit-tasks 生成
```

### Source Code (repository root)

```text
termcfg                        # 使用仓库 .venv 的独立入口
src/termcfg/
├── __init__.py                # 独立包入口
├── cli.py                     # 命令解析、阶段进度与退出码
├── config.py                  # 私人机器选择与严格加载
├── catalog.py                 # 组件选择、来源和目标清单
├── environment.py             # OS/架构、程序、权限和目标准入
├── home_targets.py            # HOME 目标的 fd/no-follow 读写与链接迁移
├── lease.py                   # 机器独占锁与共享依赖锁的仓库级读写租约
├── secret_boundary.py         # 旧目标的非秘密准入
├── preview.py                 # 只读预览与快照身份
├── transaction.py             # 备份、pending、恢复、回滚
├── state.py                   # 待生效原因、基线与事务状态模型
├── packages.py                # 显式 lock、固定 core/插件锁及 sync 安装
├── mihomo.py                  # 公开基础与私人有效配置、服务身份
└── diagnostics.py             # 脱敏状态与下一步
terminals/
├── zsh/                       # 公开配置、zshenv 模板、来源说明
├── tmux/                      # 公开配置、fzf 脚本、来源说明
└── mihomo/                    # mgr 代码/许可、非秘密基础配置
locks/termcfg/                 # core 与插件的完整版本/来源/摘要锁；无私人值
schemas/termcfg/              # 机器配置、目录清单和状态 schema
tests/test_termcfg_*.py        # 临时 HOME/假进程/中断恢复
docs/termcfg.md                # 用户操作与迁移说明
```

**Structure Decision**: 新模块只管理非 AI 组件；`src/agentcfg/storage.py` 等现有原语可抽出复用，但 HOME 目标采用独立安全投影，不把 Agent 配置状态/备份格式直接用于用户 HOME。公开 shell 源和 mihomo mgr 必须附来源提交、摘要、许可与改动记录。目标清单逐文件声明 mode、来源与组件；未知路径不自动遍历。

## Phase 0: Outline & Research

见 [research.md](research.md)。已经解决 core 来源/锁模式、代理公开与私人配置、服务身份、`.zshenv` 整文件覆盖、插件显式同步和隔离验证的架构决策。制作真实锁时仍须选择并核验官方资产字节；未取得校验材料的平台不发布为已支持。

## Phase 1: Design & Contracts

- [data-model.md](data-model.md)：组件、目标、备份、同步记录、依赖资产、服务租约及状态转换。
- [contracts/cli.md](contracts/cli.md)：首次选择、交互/脚本路径、命令参数、副作用、耗时进度、超时、脱敏输出和退出码。
- [contracts/sync-state.md](contracts/sync-state.md)：预览快照、接管确认、备份顺序、恢复日志、私人数据边界。
- [quickstart.md](quickstart.md)：离线隔离验收、故障注入和独立 live 验收边界。

**Post-design Constitution Check**: 通过；Phase 1 未引入自动联网、自动服务重启、未知文件接管或秘密备份。Linux x86_64 以外的平台以及真实订阅/运行连接仍需单独证据，不能据文档产出宣称通过。
