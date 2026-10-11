# OMP 支持与验证状态

当前固定版本：v18.8.6 / `f068751e2f1dbdbc195977776d47a26db8697495`，仍使用未修改的官方宿主，升级记录见[18.8.6 验收](acceptance/omp-upgrade-18.8.6.md)。下表中的早期完整验收保留原版本身份，不自动成为新版插件或环境契约通过证据。当前权限生命周期与环境修复的验证状态单独登记；不能仅凭存在配置或下载URL判断原生能力已经通过。

2026-10-11 的新审批生命周期、脱敏和普通工具环境状态见[专项验收](acceptance/omp-tool-stability-20261011.md)，与日常部署是否已更新分开记录。

| 层次 | 当前证据 | 能说明什么 |
|---|---|---|
| 固定源码 | [来源记录](../specs/002-manage-omp-config/evidence/source-provenance.md)、完整bun.lock/许可证/发布摘要 | 固定来源、发现路径与能力映射依据 |
| 管理器隔离测试 | [基础](../specs/002-manage-omp-config/evidence/foundation.md)、[资源与US1](../specs/002-manage-omp-config/evidence/us1.md)、[依赖维护](../specs/002-manage-omp-config/evidence/us5.md)、[全量回归](../specs/002-manage-omp-config/evidence/regression.md)、[提交前审查](../specs/002-manage-omp-config/evidence/precommit-review.md)（最新全量 2160 项及 7 子测试通过） | 合成配置、假进程/资产下的行为和边界 |
| 原生宿主 | [Linux x64 smoke 通过](../specs/002-manage-omp-config/evidence/linux-smoke.md) | 九行配置被真实宿主发现，本地 MCP 完成调用；未触发安装器，未请求模型 |
| 原生账号 | 早期升级验收未执行登录、真实usage或模型调用，转 OMP-F03–F05；后续 [真实 Cursor 验收](acceptance/omp-cursor-native-approval-20261004.md) 已执行限定模型调用 | 证明观察到的 Cursor 原生 Bash 与 GLM 审查路径，不扩大为登录流程、usage或其它模型路线通过 |

| 平台 | 发布资产已固定 | 平台选择隔离测试 | 真实宿主 |
|---|---|---|---|
| Linux glibc x64 | 是 | 通过 | 通过（v18.4.5 独立权限插件 smoke；v18.3.0 九行/MCP 验收保留历史身份） |
| Linux glibc arm64 | 是 | 通过 | 未验证；已转 OMP-F01 |
| macOS x64 | 是 | 通过 | 未验证；已转 OMP-F02 |
| macOS arm64 | 是 | 通过 | 未验证；已转 OMP-F02 |
| Linux musl、Windows、其他架构 | 不支持 | 拒绝规则通过 | 不属于首版支持范围 |

扩展与MCP示例仅使用仓库内无外部依赖包；Python解释器身份记入receipt。完整技能可包含脚本，配置阶段不执行它们。源码检查和Python纯函数协议测试不等价于OMP实际加载扩展或MCP成功；Linux x64 现另有真实扩展、官方 SDK MCP 调用及主题/按键证据。显式 `/rotom-health inspect`/`mcp` 自检只输出固定验收结果，不读取账号或请求模型。

真实验收使用[quickstart](../specs/002-manage-omp-config/quickstart.md)的独立临时仓库、新HOME、正式锁及真实发布字节，按平台和操作分别记录。登录、真实usage与模型生成属于独立步骤，不以无账号启动代替。

使用说明：[配置](omp.md)、[profile与来源](omp-profiles.md)、[依赖维护](omp-dependencies.md)、[usage](omp-usage.md)。

专项证据：[身份与发现](../specs/002-manage-omp-config/evidence/us2.md)、[盘点与迁入](../specs/002-manage-omp-config/evidence/us3.md)、[usage](../specs/002-manage-omp-config/evidence/us4.md)、[秘密边界](../specs/002-manage-omp-config/evidence/security.md)。

本轮自检扩展更新后受影响回归 57 项通过。宿主运行置于断网命名空间；观察到启动 DNS 尝试被阻断，不宣称原生宿主完全没有网络行为。

2026-09-24 用户确认本机无其他平台/账号验收环境，已将上述未验证项转入[OMP-F01–F05](follow-ups/omp-platform-and-live-validation.md)。当前 spec 按[修订范围](../specs/002-manage-omp-config/scope-change-20260924.md)已完成（62/62）；后续验证不阻塞当前完成状态，仍不计为通过。


Phase 14 原生 Bash 插件已完成实现、隔离验收及真实 Cursor 验收（2026-10-04），main 已快进至 `14f34a9`，仍使用未修改的官方 v18.4.5。已验证的原型同名注册、公开委托和 scoped Settings 机制见[可行性证据](acceptance/omp-bash-wrapper-feasibility-20261003.json)；保留其原型身份，高级能力和其它平台结果另行登记。

生产插件基础 335 项包级纯测试、固定 SDK、24 组官方宿主与真实人工 UI 见[Phase 14 验收](acceptance/omp-native-bash-approval-20261004.md)；后续最终 339 项/1288 assertions、25/25 隔离宿主结果见真实 Cursor 验收，保留各阶段身份。

后续[真实 Cursor 验收](acceptance/omp-cursor-native-approval-20261004.md)使用新增预算 6/6（Cursor 3、GLM 3）：无害复合命令 human=0、delegate=1；原生 deny reviewer=0、delegate=0。日常部署已完成：用户授权 SIGTERM 退出活动实例后备份、sync/plan/apply/doctor 成功，offline-ready、运行包匹配、pending=0，无漂移、冲突或恢复待处理；13 项账号数据库/WAL、会话、local 与 owner 的字节和权限不变。完整启动准入通过 launch callback，未启动新的日常宿主，部署阶段外部请求为 0。

Phase 15 在新 worktree 扩展常见 Shell 环境，并保持未修改的官方宿主。355 项 Bun、208 项
Python（另 7 项已退役材料跳过）、固定 SDK 及 36/36 官方宿主 fixture 通过。真实 zsh 配置
下 find 管道观察到 reviewer=1、human=0、nativeDelegate=1；默认 find interceptor 的 glob 提示
另有保留验证。bash/zsh/sh 有本轮宿主证据，其它 family 只有纯模块矩阵，不计作其它 OS 或
原生 Shell 语言通过。执行环境和覆盖限制见 [Shell 验收](acceptance/omp-shell-approval-20261004.md)。
本轮合入不会自动更新日常实例，新增付费请求为 0。
