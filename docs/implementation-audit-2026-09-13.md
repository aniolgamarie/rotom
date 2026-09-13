# Spec 实现检查：2026-09-13

> 本文是继续实施之前的检查快照。后续已完成修复与实现，当前测试、平台和 live 状态见 [acceptance.md](acceptance.md)；不要将本文的 14/71 或 717/1 作为当前结果。

检查对象：`build-agent-config-framework`（spec-driven）。本次按用户要求检查实现情况，不继续实现功能，不调整任务勾选，不安装 DSH、不读取用户登录文件或调用模型服务。

## 结论

已有可测试的配置核心和开发基础设施，尚未形成可供日常使用的管理器。OpenSpec 规划产物 4/4 完整；实施清单标记 14/71 完成、57 项未完成。这是任务清单计数，不是产品功能或工程工作量的完成百分比。

`init-local` 已连接实际实现；validate、render、plan、lock、sync、apply、run、doctor、capture、rollback、project 的 CLI handler 均仍返回“尚未实现”与退出码 2。因此当前不能通过统一入口完成配置生成、部署、备份或启动流程。

## 能力与证据

| 范围 | 清单 | 检查所见 |
|---|---:|---|
| 上游调查 | 1/7 | 有固定源码候选、链接及合成 fixture；文档明确未完成安装/依赖树验证/smoke |
| 管理器基础 | 5/5 | Python 项目、uv.lock、被动虚拟环境入口、CLI 解析、隔离测试及 adapter 声明接口已存在 |
| 本地格式与合并 | 7/7 | 严格 schema、provider/model/MCP/profile 覆盖、来源、秘密存储和初始化已有模块与测试；仍有下面列出的适配要求偏差和文档缺项 |
| 渲染与计划 | 1/5 | 有原文规则、StrictUndefined、结构化序列化、候选 generation、技能包收集；CLI/cache/plan 未接通 |
| 部署与上一版备份 | 0/9 | 未实现三方部署、current/previous/pending、事务恢复、rollback 和实例活动互斥 |
| 依赖锁与 sync | 0/5 | Python uv.lock 存在；DSH/TUI/插件/OpenSpec 的完整产品锁及暂存安装未实现 |
| run/doctor/capture | 0/7 | 仅有接口与测试适配器，不是实际宿主启动/诊断/捕获 |
| DSH 配方和认证 | 0/8 | agents/dsh、profiles、locks/dsh 尚不存在，未接入真实 DSH/Codex/Cursor |
| OpenSpec 项目集成 | 0/4 | 开发本仓库使用的 OpenSpec 不等于产品 project init 功能；产品命令仍占位 |
| 扩展与维护 skill | 0/7 | 公共 adapter 契约存在；maintain-agent-config 包及第二工具接入文档未交付 |
| CI 与用户文档 | 0/6 | 无 Linux/macOS CI；README 仍为简短仓库描述 |
| live 验收准备 | 0/1 | 尚未交付独立的用户验收操作流程；本次未执行 live |

## 需要优先处理的偏差

### 0. 当前仓库位置触发技能来源目录的安全拒绝

沙箱外完整复测仍有一项失败：`tests/test_skills.py::test_repository_navigation_package_relative_links_survive_collection`（第 301 行）。对内部收集流程作只读复现确认，失败原因是 `src/agentcfg/paths.py` 第 69 行拒绝可被其他用户写入且无 sticky 位的祖先目录。

本机真实 `/data`、`/data/1` 均属于 root、模式 0777；仓库及用户目录属于当前用户、模式 0755。技能收集从 `/` 遍历并复用部署路径的祖先信任检查，因此无法从当前仓库收集 repo-navigation 包。这是当前环境与安全策略的实际不兼容，不是技能资源相对链接本身已经证明损坏。

需明确可信配置源与部署目标各自的安全策略，或在符合策略的私人目录中验证仓库副本。不能通过取消符号链接/祖先检查或修改共享系统目录权限来掩盖失败。本次未修改这些权限、未放宽保护，也未把该测试标为通过。

### 1. OAuth provider 被通用 schema 强制要求静态地址

`schemas/registry.schema.json` 的 provider `required` 包含 `base_url`。这与 DSH-04、DSH-06 和设计中“动态 OAuth provider 不要求编造静态 endpoint”的要求不符。

已用纯合成数据直接调用 `validate_document` 复现：同一个 `auth_kind="oauth"` provider 不带 base_url 时拒绝，补入 example.invalid 静态 URL 后接受。这是通用 schema 的限制，后续 DSH adapter 无法在完成公共 registry 校验之前解决。

建议按 provider 认证/协议及适配能力要求判断地址是否必需，增加无静态地址 OAuth 的正向测试和 API provider 缺必要地址的反向测试。不能通过填虚构地址满足 schema。

### 2. 已有核心函数不等于命令验收完成

`src/agentcfg/commands.py` 除 init-local 外仍为明确失败的占位 handler。`tests/test_config_examples.py` 也明确断言 validate/render CLI 尚未实现；示例通过的是注入虚构 adapter 的 API 流程。因此不能用示例测试通过宣称 README 首次使用流程可运行，也不能把基础 canary 测试延伸为 apply/sync/run/备份的密钥隔离已通过。

### 3. 部分勾选与交付边界需要细化

- 任务 3.6 包含“本地格式字段文档”，已勾选，但检查前用户文档只有上游调查记录；schema、例子和 OpenSpec 设计材料不能替代实际日常字段参考。
- 任务 3.4 的解析层已表示取消选择后的缺失，但受管删除计划与 manifest 条件仍未实现。对应测试 `test_deselection_represents_absence_without_deletion` 明确只证明解析后不写目标。
- 任务 4.2、4.3 尚未勾选，但技能收集模块、局部导航技能和三份规则已存在，属于已开展但尚未完成端到端验收的内容，不能简单当成完全没做。

本次未自行改变任何勾选。后续应按任务的完整验收边界补齐或拆分状态，而不是为了提高数字直接勾选。

### 4. 上游调查记录中的接入难点仍待解决

以下来自当前 `docs/upstream-verification.md`，本次未重新访问上游或独立验证源码事实：

- Cursor 社区插件的自动凭据导入与 macOS keychain 隔离问题。
- DSH 启动读取 cwd/.env，净化启动环境与保持工作目录之间需要明确处理方式。
- 整块可执行 Cordis config 与窄 JS 白名单之间的安全合成问题。
- OpenSpec 初始化/更新可能覆盖产物，必须先实现项目预检查和冲突保护。

这些问题不妨碍继续实现离线公共核心，但阻止当前组合被报告为真实接入完成。

## 本次检查与测试

- OpenSpec：`openspec validate build-agent-config-framework --strict` 通过；status 显示 4/4 规划产物完整。
- 管理器依赖：在临时 HOME/cache 下执行 `uv lock --check --offline` 通过（19 个包）。这证明锁与项目声明的检查通过，不等于重新安装了所有依赖，也不证明 DSH 产品锁存在。
- Python：使用已准备的仓库 `.venv`，Python 3.11.11，Linux。没有执行自动依赖安装。
- 默认测试：清空父环境，仅构造临时 HOME/DSH_HOME/XDG/TMPDIR；禁用自动加载额外 pytest 插件，使用仓库 conftest 的网络/进程阻断和假进程。命令主体为 `.venv/bin/python -m pytest -q -p no:cacheprovider`。
- 初轮沙箱结果：635 passed、83 failed、7 subtests passed，耗时 197.14 秒。大量失败在路径祖先检查前置条件上：沙箱中 `/` 和 `/tmp` 的属主呈现 UID 65534，`_check_ancestor` 只接受 root 或当前 UID 1002；对新建私人临时目录的最小复现同样被拒绝。不能将这些失败直接解释为 83 个独立功能缺陷。
- 已按执行权限流程完成沙箱外复核，仍保持相同临时环境、离线及假宿主约束：**717 passed、1 failed、7 subtests passed，耗时 204.48 秒**。剩余失败为从当前仓库收集导航技能，已通过只读路径权限/内部收集复现定位到 `/data` 与 `/data/1` 的 0777 祖先。没有跳过或伪造通过；默认测试在当前机器上尚未全绿。
- 无账号真实 DSH smoke、macOS CI、真实 Codex/Cursor 调用：本次均未执行。

## 建议的后续顺序

1. 处理配置源安全策略与当前仓库路径的不兼容，完成剩余失败验收；调整 OAuth provider schema 并补行为测试。
2. 接通 validate/render/plan 的完整来源加载、缓存与脱敏报告，补本地格式字段说明。
3. 完成用户最关心的上一版备份、三方部署与失败恢复，再允许实际 apply。
4. 解决上游隔离问题，补 DSH 完整锁、sync/run 与认证/OpenSpec 实际配方。
5. 交付维护 skill、跨工具契约验收、CI 和日常文档，分别记录 smoke/live 证据。

工作区已有实现、测试及规划文件多数仍为 Git 未跟踪内容。本次检查保留原有工作，不提交、不 push、不归档 change。
