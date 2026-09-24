# OMP 支持与验证状态

固定版本：v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`。实施状态和未完成项见[实施记录](../specs/002-manage-omp-config/implementation-progress.md)，不能仅凭存在配置或下载URL判断原生能力已经通过。

| 层次 | 当前证据 | 能说明什么 |
|---|---|---|
| 固定源码 | [来源记录](../specs/002-manage-omp-config/evidence/source-provenance.md)、完整bun.lock/许可证/发布摘要 | 固定来源、发现路径与能力映射依据 |
| 管理器隔离测试 | [基础](../specs/002-manage-omp-config/evidence/foundation.md)、[资源与US1](../specs/002-manage-omp-config/evidence/us1.md)、[依赖维护](../specs/002-manage-omp-config/evidence/us5.md)、[全量回归](../specs/002-manage-omp-config/evidence/regression.md)、[提交前审查](../specs/002-manage-omp-config/evidence/precommit-review.md)（最新全量 2160 项及 7 子测试通过） | 合成配置、假进程/资产下的行为和边界 |
| 原生宿主 | [Linux x64 smoke 通过](../specs/002-manage-omp-config/evidence/linux-smoke.md) | 九行配置被真实宿主发现，本地 MCP 完成调用；未触发安装器，未请求模型 |
| 原生账号 | 登录、真实usage、模型调用均未执行，已转 OMP-F03–F05 | 不宣称服务、账号、额度窗口或模型路线通过 |

| 平台 | 发布资产已固定 | 平台选择隔离测试 | 真实宿主 |
|---|---|---|---|
| Linux glibc x64 | 是 | 通过 | 通过（v18.3.0，无账号 smoke） |
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
