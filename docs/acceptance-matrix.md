# 需求与验收映射

> 当前已按维护者要求改为官方宿主与独立插件，仓库实现及隔离验收完成；本机日常实例已按后续明确授权完成独立插件迁移（见验收 Phase 13）。下文 patched runtime/bridge 的构建和验收为历史记录，不继续构建发布，也不作为新插件通过证据。当前需求见[独立插件修订](../specs/004-omp-permission-control/standalone-plugin.md)。本机部署是否切换须单独登记。

实现要求的编号来自 OpenSpec；测试总结果见 acceptance.md。一个文件可覆盖多个场景，账号及平台证据单独记录，不能从文件存在推断通过。

审查修复补充映射：R1/R2/R3/R4/R5/R6 与 capture/诊断的具体回归位于 `tests/test_review_hardening.py`；非 npm 后端完整命令路径位于 `tests/test_extensibility.py::test_non_npm_backend_drives_public_commands_and_launch`；损坏虚拟环境有限重启位于 `tests/test_entry.py::EntryTests::test_existing_python_without_venv_metadata_does_not_exec_loop`。维护技能独立 A 场景的实际证据见 acceptance.md，其余行为场景见 improvement-plan.md。

## 当前 OMP 独立权限插件

| 场景 | 当前证据 |
|---|---|
| Linux glibc x64 官方 OMP + 独立插件 | 临时 HOME、loopback固定provider真实执行通过；Bun 24 pass / SDK strict 类型检查通过；最终 kernel+三方迁移 14 pass |
| 实际 Cursor OAuth、真实新主审质量 | 尚未执行；不借用旧 patched 模型结果 |
| 本地 tiny fallback | 官方无公开 installed-only 推理接口，当前明确 unavailable |
| 日常 omp-kernel、其它平台 | 本机官方运行包部署与无宿主启动的完整准入已通过；其它平台尚未验收 |

完整身份、命令和故障修复见[Phase 12 验收](acceptance/omp-permission-control.md#phase-12官方-omp-与独立插件2026-09-30当前交付)。

## 历史 OMP permission-control 补丁候选支持矩阵

该矩阵描述`omp-kernel`的限定范围。当前Phase 11分离Cursor模型/资源开关并添加远程审批fallback；Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。

T080冻结240条模型评测保留原始runtime身份：safe免问99/100、risk危险allow0/100、fault allow0/40，只支持该冻结范围SC-001/002。本轮没有重新请求真实模型，102/102账本和模型响应原字节不变。见[最新宿主报告](acceptance/omp-permission-control-host-smoke.md)、[模型评测报告](acceptance/omp-permission-control-model-evaluation.md)及[机器可读结果](acceptance/omp-permission-control-model-results.json)。

| 场景 | 候选行为 | 当前证据边界 |
| --- | --- | --- |
| Linux glibc x64、主 OMP 会话、native Bash 前台 | 在完整 prepare、策略和最终同步 revalidate 后，宿主私有 permit 只允许同一冻结计划启动一次 | 当前 06e422… runtime 真实隔离 standalone 通过 new/resume、单次 pwd fixture review permit 消费、missing-plugin pre-spawn exit 5 与 rollback；外部模型 0 |
| 纯 interceptor | 未命中可继续候选判断；命中保留原无执行引导，不把 interceptor 整体视为不支持 | mock interceptor 与 wrapper 路径；未执行真实扩展链 |
| Bash snapshot | 冷 Shell 第一次仍走人工原生路径；只有 snapshot 内容、生成输入、实际 Shell 生命周期、相关命令名解析/options 和后续连续性都可证明时才可复用证明。未知 mutation 永久撤销该连续性 | 合成 Shell 与状态漂移反例；不把 cache 路径或摘要本身当证明 |
| 默认 auto-background | 审批后才 stage artifact/job；在最终同步 revalidate 与 permit consume 后启动，保留取消、tail、artifact 和后台结果语义 | fake manager/native start 边界；真实长任务未执行 |
| direnv `auto` 且完整搜索链证明没有有效配置 | 可继续候选判断；搜索不完整、发现配置或状态漂移转人工 | 假文件系统边界；未执行 direnv |
| 实际 direnv/devenv、prefix、内部 URL、service、显式 async、PTY、ACP、`useUserShell`、未知启动脚本、确实改变命令的 worktree rewrite | 保留原生保护并要求人工；无 UI 时阻止 | 不在 smart 自动许可范围，未做真实宿主验证；worktree no-op 保留原命令并可继续候选判断 |
| 非 Bash、eval、MCP、task/child/子代理 | 不取得 smart permit；沿用相应原生保护、人工或无 UI 阻止 | 未验证这些路径的端到端行为 |
| reviewer transport | 主审和远程备用仅支持标准API-key anthropic-messages/openai-completions；显式主审优先，有效决定终止，故障才接替；两层都失败转tiny/人工 | 实际补丁函数隔离测试与新standalone loopback主审故障→remote allow通过；真实GLM备用质量未验证 |
| Cursor模型与资源来源 | patched profile单独管理disabledModelProviders，Cursor模型可发现；disabledProviders继续关闭Cursor用户/项目资源 | 实际ModelRegistry/model hub/capability函数隔离反例通过；真实OAuth模型目录未验证 |
| tiny fallback | 只加载已安装且身份匹配的本地资源，不下载；资源缺失时 unavailable | fake installed loader；真实模型加载和质量未验证 |
| WSL、macOS、Windows、Linux arm64、musl | 没有本候选资产或验收；平台/资产不匹配在管理器层失败关闭 | 不从 Linux glibc x64 隔离证据推定支持 |

该机制是同一进程可信边界内的应用级审批，不是 OS 沙箱，不能隔离同用户恶意代码，也不承诺消除
批准到系统调用之间的外部文件竞态。配置/manifest 错误返回 2，活动实例或租约冲突返回 4，运行包、
平台、ABI、插件或资产身份失败返回 5；这些管理器退出码与工具层 ask/deny 分开。

持续更新的隔离组和 T071 状态只引用
[permission-control 验收记录](acceptance/omp-permission-control.md)，不在本矩阵复制易过期的计数。
隔离证据已覆盖管理器 candidate/apply 生成的同一 `config.yml` 对象与 patched Settings/Bash 的严格
schema、身份、冷态及 fake 暖机互通；它证明合成资产消费、事务、故障关闭和 fake
transport/installed loader 契约。当前Phase 11正式资产SHA-256为`0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86`，combined runtime为`06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2`。T072 使用历史 combined runtime
`bf6f18b45fc80c177f6644e96366b978bb3d524b0d476664d228e4a7de48bc08` 的正式 standalone 和
固定响应本地 provider 完成宿主自动许可链：最后一轮 2 次 main、1 次 review，外部请求 0，`pwd` 只执行
一次并消费 permit。累计两轮成功为 4 main、2 review；这些 review 是脚本固定响应，即使模型 ID 为
`kimi-for-coding` 也不是实际 reviewer。获准的 3 个真实模型请求均为主模型请求，未触发 reviewer；真实
reviewer provider 的冻结样本结果已记录；102/102 请求额度已用尽且 relay 已停止。真实 tiny 推理、Linux x64 以外平台及冻结集外质量仍未验证；独立 scout 全量语义审计已完成。

| 要求 | 证据入口 | 验收边界 |
|---|---|---|
| EXT-01 — Common core owns portable management behavior | tests/test_adapter.py、test_extensibility.py | 测试专用非 DSH 适配器；不宣称支持 Pi/Codex |
| EXT-02 — Capabilities and native bindings remain explicit | tests/test_adapter.py、test_extensibility.py | 测试专用非 DSH 适配器；不宣称支持 Pi/Codex |
| EXT-03 — Only implemented adapters are exposed as supported | tests/test_adapter.py、test_extensibility.py | 测试专用非 DSH 适配器；不宣称支持 Pi/Codex |
| EXT-04 — Multi-tool state and local overrides are independently scoped | tests/test_adapter.py、test_extensibility.py | 测试专用非 DSH 适配器；不宣称支持 Pi/Codex |
| CLI-01 — Public selectors and command contracts are consistent | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CLI-02 — Init-local creates a private non-overwriting file | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CLI-03 — Offline commands have bounded writes | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CLI-04 — Run uses the deployed launch contract and caller cwd | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CLI-05 — Child environments contain only allowed and required values | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CLI-06 — Doctor separates offline status from live checks | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CLI-07 — Capture produces a scoped private proposal | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CLI-08 — Exit codes distinguish failure classes | tests/test_cli.py、test_dsh_pipeline.py、test_runtime.py、test_init_local.py | 离线命令/假子进程；真实 CLI 临时环境验收 |
| CFG-01 — Versioned schemas and stable entity references | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-02 — Local machine format covers explicit machine differences | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-03 — Local paths and environment values have literal semantics | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-04 — Layer merge preserves explicit values and provenance | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-05 — Missing values and removal are distinct | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-06 — Secret values stay outside compilation and identifiers | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-07 — Rendering is deterministic and text-safe | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-08 — Skills are complete attributed packages | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| CFG-09 — Local examples are executable framework documentation | tests/test_config_schema.py、test_config_resolution.py、test_config_policy.py、test_config_examples.py、test_audit_regressions.py、test_render.py、test_skills.py | 离线测试；CLI 流程 |
| SKILL-01 — A complete maintenance skill is delivered and discoverable | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/流程/发现及独立 A 场景已检查；B–E 行为待验证 |
| SKILL-02 — Local configuration authoring follows the actual schema | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/流程/发现及独立 A 场景已检查；B–E 行为待验证 |
| SKILL-03 — Local edits preserve unrelated private content | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/流程/发现及独立 A 场景已检查；B–E 行为待验证 |
| SKILL-04 — Maintenance follows source and version boundaries | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/流程/发现及独立 A 场景已检查；B–E 行为待验证 |
| SKILL-05 — Generation and deployment follow user authorization | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/流程/发现及独立 A 场景已检查；B–E 行为待验证 |
| SKILL-06 — Skill validation checks realistic behavior and outcomes | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/流程/发现及独立 A 场景已检查；B–E 行为待验证 |
| DSH-01 — Native interfaces are verified against locked sources | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-02 — Native configuration respects complete row replacement and safe tags | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-03 — Default recipe retains native permissions and low-noise behavior | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-04 — Subscription authentication has one owner per provider | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-05 — Cursor integration is native to the selected DSH instance | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-06 — API and private models use verified metadata and environment references | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-07 — MCP conversion is explicit and defaults to disabled | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-08 — Optional plugins require evidence and prohibited suites stay absent | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-09 — Preferences outside DSH_HOME are accounted for | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| DSH-10 — Acceptance evidence is separated by execution level | tests/test_dsh_pipeline.py；scripts/smoke-dsh.py；锁定原生 schema 检查 | Linux 无账号通过；账号调用及 macOS 待验证 |
| LOCK-01 — Manager dependencies are locked and offline entry is passive | tests/test_dependencies.py、test_entry.py；CLI sync / npm ci / npm ls | 离线测试与 Linux 实际安装；macOS 待验证 |
| LOCK-02 — Tool locks include the actual transitive resolution | tests/test_dependencies.py、test_entry.py；CLI sync / npm ci / npm ls | 离线测试与 Linux 实际安装；macOS 待验证 |
| LOCK-03 — Missing or stale locks fail before implicit resolution | tests/test_dependencies.py、test_entry.py；CLI sync / npm ci / npm ls | 离线测试与 Linux 实际安装；macOS 待验证 |
| LOCK-04 — Sync stages and consumes locks without activating failures | tests/test_dependencies.py、test_entry.py；CLI sync / npm ci / npm ls | 离线测试与 Linux 实际安装；macOS 待验证 |
| LOCK-05 — Native installer limits and platforms are explicit | tests/test_dependencies.py、test_entry.py；CLI sync / npm ci / npm ls | 离线测试与 Linux 实际安装；macOS 待验证 |
| DEP-01 — Instances and sensitive directories are isolated | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| DEP-02 — Ownership and first adoption are explicit | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| DEP-03 — Three-way merge preserves drift without adopting it | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| DEP-04 — Previous backup rotates only after successful change | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| DEP-05 — Journals recover interrupted multi-file operations | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| DEP-06 — Rollback restores and consumes the previous managed state | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| DEP-07 — Mutations are mutually exclusive and recheck targets | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| DEP-08 — Paths and cleanup remain within owned boundaries | tests/test_deployment.py、test_paths.py、test_init_local.py、test_runtime.py | 真实临时文件；故障与锁测试 |
| OS-01 — OpenSpec uses its locked installed CLI | tests/test_project.py；实际 CLI project init；scripts/smoke-dsh.py --with-openspec | 指定临时 Git 项目；10 产物；重复零变化；原生发现通过 |
| OS-02 — Project initialization is explicit and bounded | tests/test_project.py；实际 CLI project init；scripts/smoke-dsh.py --with-openspec | 指定临时 Git 项目；10 产物；重复零变化；原生发现通过 |
| OS-03 — Native or custom integration is verified by DSH loading | tests/test_project.py；实际 CLI project init；scripts/smoke-dsh.py --with-openspec | 指定临时 Git 项目；10 产物；重复零变化；原生发现通过 |
| OS-04 — Repeated initialization preserves project work | tests/test_project.py；实际 CLI project init；scripts/smoke-dsh.py --with-openspec | 指定临时 Git 项目；10 产物；重复零变化；原生发现通过 |
