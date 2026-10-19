# 旧 Pi 退役初始清单

日期：2026-10-18；候选基线 `8ac50aa`，分支 `design/pi-toolkit-reboot`。任务 T002。
依据：[spec](spec.md)、[plan](plan.md)、[退役契约](contracts/retirement-and-evidence.md)、
[新运行契约](contracts/pi-runtime-and-modules.md)。仅盘点公开仓库源码、声明及相对路径；
没有读取真实账号、认证、会话、运行日志或任务数据库，没有执行宿主、安装或删除。
这是后续逐批处置的输入，不是消费者归零、状态可清除或新组合可运行的证明。

## 1. 处置和验证约定

`replace`：撤旧入口并由明确新入口承接；`rebuild`：保留职责、按新契约重建；
`remove`：解除消费者后退出仓库发行/运行/发现；`archive`：只保留历史证据或用户状态；
`unresolved`：消费者或保护前提未闭合，阻止该项删除。archive不得继续分发旧执行平台。
分组规则适用于每个列明文件/目录；目录覆盖全部后代，不是按名字批准批量删除。
全部行均为计划处置，实际“尚未删除/替换”；不改写历史完成结论。

V1=静态引用/动态注册消费者归零；V2=全catalog、旧ID明确拒绝及DSH/OMP隔离回归；
V3=新锁/资源完整性与旧链缺席双路径重建；V4=状态/非受管/活动及未知owner哨兵与配置恢复；
V5=文档链接/历史范围。V1–V5是后续验收要求，本轮只做静态文档核查。
Python消费者从 `src/agentcfg/*.py`、`scripts/*.py`、`tests/*.py` 的AST导入取得，
包含函数内导入；AST空集合不证明无动态消费者。包目录完整边界和相对路径快照列于文末。

## 2. 公共入口和动态消费者

| 路径/入口 | 已观察用途、消费者和状态归属 | 处置、替代和前置 |
| --- | --- | --- |
| `src/agentcfg/workspace.py` | ADAPTER_TYPES登记PiAdapter；load_public_catalog全量glob profiles与shared TOML，并加载各agent的content/agent/bindings/plugins；其他工具也经过全catalog | replace Pi来源；四旧profile、defaults、bindings、plugins、content、schema同批切换，公共加载器保留，V2 |
| `src/agentcfg/config.py`、`model_defaults.py`、`model_templates.py`、`model_wizard.py`、`model_status.py`（均在src/agentcfg） | 公共模型补全/角色与Pi映射，DSH/OMP也消费 | rebuild Pi映射，保留公共模型与其他工具；不得整文件删除，V2 |
| `src/agentcfg/commands.py` | inventory函数内导入pi_inventory，fallback到pi-default；recover分发pi_recovery | replace Pi分发；新inventory与停止使用/人工归档说明替代，历史recover不得成为新运行前提，V1/V2/V4 |
| `src/agentcfg/cli.py` | 旧selector/ID/验证恢复入口 | replace旧参数，保留公共命令边界；Base/Pro与历史状态说明，V1/V2 |
| `src/agentcfg/presentation.py` | workspace_leases payload展示（约480行） | replace旧租约展示，保留通用呈现，V1/V2 |
| `src/agentcfg/runtime.py`、`backends.py`、`render.py`、`adapter.py`（均在src/agentcfg） | 公共LaunchSpec/backend/render及adapter动态分发 | rebuild Pi薄适配和backend，公共接口保留，V2/V3 |
| `src/agentcfg/deployment.py`、`native_projection.py`、`storage.py`、`lifecycle.py`（均在src/agentcfg） | 公共pending/backup/rollback/物理准入，不是Task Keeper恢复层 | rebuild中性原语，保留DSH/OMP布局与语义，V2/V4 |
| `agents/pi/agent.toml` | 默认model-delegate skill与pi-subagents/pi-permissions/model-delegate插件；resources与policies逐项动态注册 | rebuild最小严格来源；撤旧默认/权限/task_keeper/model_delegate对象后新增Base/Pro，V1/V2 |
| `agents/pi/bindings.toml` | 协议映射；oauth.codex owner=pi-native、oauth.cursor owner=pi-cursor | rebuild真实新绑定；撤旧owner不复制/删除auth，V2/V4 |
| `agents/pi/plugins.toml`、`agents/pi/content.toml` | requires/conflicts/engines闭包；kernel-orchestrate指向task-keeper技能 | replace最小无旧引用插件集合；remove旧技能注册，SpecKit继续，V1/V2/V3 |
| `agents/pi/runtime/launch.ts`、`resource-loader.ts`、`runtime-module.ts`、`plugin-storage.ts`、`tool-ownership.ts`（均在runtime目录） | SDK主循环、profile/manifest切片、动态import/reload、能力与工具注册；commands.json由构建生成 | remove旧SDK接缝，官方CLI显式已锁资源替代；检查TS/包声明/生成程序表，V1/V3 |
| `agents/pi/build/recipes.json`、`agents/pi/dependencies.json`、`src/agentcfg/pi_vendor.py` | 来源/构建/launcher_source_paths/source_files；旧recipe_digest覆盖全src Python和旧资源 | rebuild实际依赖输入摘要与完整npm锁，不绑定其他profile/退役链，不隐式重锁，V1/V3 |
| `scripts/omp-command-history.py`、OMP历史fixtures | source=pi是语料分类，不等于Pi执行消费者 | archive历史事实，保留OMP检查；不按文本命中删除，V2/V5 |

## 3. 配方、资源和状态所有者

| 项目 | 旧用途/消费者 | 处置、替代、阻断/验证 |
| --- | --- | --- |
| `profiles/pi-default.toml` | Node日常旧委托/todo/loop/footer/公共skills | replace为pi-base；旧ID明确拒绝/迁移，不静默路由；旧实例保留，V2/V4 |
| `profiles/pi-managed.toml` | Node Task Keeper/kernel-orchestrate/三角色 | replace为pi-pro基础；不复刻任务平台，协作not_ready，V2/V4 |
| `profiles/pi-cursor.toml` | Bun/旧Cursor/model-delegate | remove旧档位；Cursor新候选按需，不隐式迁移账号，V2/V4 |
| `profiles/pi-codex.toml` | Codex写委托/原生权限桥 | remove旧档位；Codex不是新adapter，不恢复旧桥，V1/V2/V4 |
| `examples/pi-workstation.toml`、`examples/pi-managed.toml`、`examples/pi-services.toml` | 旧profile/服务/权限/运行绑定示例 | replace新两档虚构示例，不保留退役工具建议，V2/V5 |
| `schemas/pi-lock.schema.json` | 旧backend/测试锁结构 | rebuild官方npm闭包与资源身份，V3 |
| `locks/pi/manifest.json`、四旧profile锁目录、`locks/pi/vendor/` | 0.84.4宿主/补丁包/多平台切片，由backend/build/sync/旧验证消费 | replace新两档锁，remove旧分发；保留必要历史身份说明，V1/V3/V5 |
| `agents/pi/migration/` | 来源/角色/caller/preset/能力/补丁manifest，inventory/迁移/验收读取 | archive必要来源历史到正式资料，remove可执行消费；不继续发行，V1/V5 |
| `agents/pi/schemas/` | options/resources、descriptor/grant/租约/恢复/证据/验证 | rebuild新options/资源/依赖校验；remove旧平台schema前解除消费者，历史定义只读资料保留，V1/V2/V5 |
| `agents/pi/templates/`、`roles/`、`prompts/`、`themes/`、`extensions/` | agent资源注册/loader投影，可能建议旧权限/任务/检查点工具 | rebuild精简公共规则/完整技能/新主题；逐项审阅引用，不整包搬运，V1/V3/V5 |
| `agents/pi/runtime/`（含types/tests） | SDK主循环/管理执行/委托/RPC/MCP/web/ReadSeek/恢复/租约，build生成mjs | remove整条旧链；先解除build/manifest/包间导入/脚本，官方CLI替代，V1/V3 |
| 旧native home账号/trust/session/history及偏好（不读取） | 旧profile/用户所有，非受管原生状态 | archive仅指原位保留与人工归档说明；不复制/删除/接管/自动登录，V4 |
| 旧instance/state/cache中的运行包、pending/backup、activity、delegate reports与任务库（不读取） | 软件、配置事务、任务执行三种恢复各有所有者 | unresolved实际活动/兼容停止与人工核实；公共pending/rollback仅配置恢复，不重放任务，V4 |
| Git工作树git-dir中`write-lease.json`（仅源码标识） | workspace_leases.py绑定worktree/git-dir，跨HOME/profile持久 | unresolved旧owner/副作用；不删marker、不靠父退出释放，V4 |

### 3.1 全部旧插件注册和包来源边界

来源为旧plugins/dependencies/migration及包manifest；每行目录包含全部内部源码、资源、测试和许可。
旧代码全部退出新发行；必要上游署名/许可/来源另作历史资料保留，不继续构建patch。
移除前先解除注册ID/requires/生成入口，V1/V3。pi-cursor只存在远程npm闭包，无本地vendor目录。

| ID | 当前包名/版本 | 来源目录 / 决定 / 替代 |
| --- | --- | --- |
| `pi-mcp` | `pi-mcp-adapter@2.32.1-agentcfg.1` | `agents/pi/packages/mcp-vendor/`；remove；原生builtin:mcp |
| `openspec` | `agentcfg-openspec@1.11.0-agentcfg.1` | `agents/pi/packages/openspec-resources/`；remove；现有SpecKit，不自动OpenSpec初始化 |
| `pi-permissions` | `@gotgenes/pi-permission-system@29.3.0-agentcfg.1` | `agents/pi/packages/permission-system-vendor/`；remove；原生/公开边界重验 |
| `pi-web` | `pi-web-access@0.27.0-agentcfg.1` | `agents/pi/packages/web-vendor/`；remove；独立网页候选 |
| `pi-readseek` | `pi-readseek@0.9.16-agentcfg.1` | `agents/pi/packages/readseek-vendor/`；remove；原生阅读/检索 |
| `pi-slopchop` | `pi-slopchop@0.10.1-agentcfg.1` | `agents/pi/packages/slopchop-vendor/`；remove；原生工具，不新增方法平台 |
| `pi-subagents` | `@tintinweb/pi-subagents@0.19.0-agentcfg.1` | `agents/pi/packages/subagents-vendor/`；remove；held候选，Pro not_ready |
| `pi-todo` | `@juicesharp/rpiv-todo@2.9.0-agentcfg.1` | `agents/pi/packages/todo-vendor/`；remove；SpecKit，不加Todo |
| `pi-smart-compact` | `pi-smart-compact@9.6.0-agentcfg.1` | `agents/pi/packages/smart-compact-vendor/`；remove；原生compaction |
| `pi-cursor` | `@rahularya01/pi-cursor@1.4.29` | 远程npm闭包；remove；1.4.39候选 selection=false |
| `pi-btw` | `@narumitw/pi-btw@0.55.3-agentcfg.1` | `agents/pi/packages/btw-vendor/`；remove；原生交互，不重建后台平台 |
| `pi-processes` | `@aliou/pi-processes@0.11.1-agentcfg.1` | `agents/pi/packages/processes-vendor/`；remove；tmux/项目日志，新processes候选 |
| `pi-rules` | `@tigorhutasuhut/pi-rules@0.6.0-agentcfg.1` | `agents/pi/packages/rules-vendor/`；remove；公共rules同源投影 |
| `task-keeper` | `starter-pi-task-keeper@0.2.0-agentcfg.1` | `agents/pi/packages/task-keeper/`；remove；不重建，主会话+SpecKit |
| `colorful-footer` | `starter-pi-colorful-footer@0.1.0` | `agents/pi/packages/colorful-footer/`；remove；原生UI与缺口，Powerline held |
| `loop-guard` | `starter-pi-loop-guard@0.1.0` | `agents/pi/packages/loop-guard/`；remove；不默认重建，原生取消/有界行为 |
| `openai-proxy` | `starter-pi-openai-proxy@0.2.0` | `agents/pi/packages/openai-proxy/`；remove；原生provider与严格模型投影 |
| `session-yolo` | `starter-pi-session-yolo@0.1.0` | `agents/pi/packages/session-yolo/`；remove；退出自动确认，不虚构保护 |
| `model-delegate` | `agentcfg-model-delegate@0.2.0-agentcfg.1` | `agents/pi/packages/model-delegate/`；remove；退出Codex/Pi桥，新调查另准入 |
| `superpowers` | `superpowers@6.3.0-agentcfg.1` | `agents/pi/packages/superpowers-vendor/`；remove；单项方法参考，不自动引导 |

额外 `agents/pi/packages/subagents-patch/` 是旧补丁输入，remove，先解除build引用，V1/V3。

## 4. 全部旧 Python 文件及直接消费者

文件路径均在 `src/agentcfg/`。remove行的状态归旧实例/任务链，前置V1/V3/V4；
rebuild行按新adapter/backend/公共准入承接，V2/V3/V4。旧验证器不得充当新证据，仍适用保护迁到新测试。

| 文件 | 处置/职责去向 | 已知直接消费者（AST） |
| --- | --- | --- |
| `activity.py` | unresolved：先解除下列消费者，落实历史状态保护；不承接旧任务平台 | `scripts/pi-delegate-codex.py`；`scripts/pi-delegate-mcp.py`；`scripts/pi-native-scenario.py`；`scripts/register-pi-evidence.py`；`scripts/smoke-pi-concurrency.py`；`src/agentcfg/model_delegate.py`；`src/agentcfg/model_delegate_batch.py`；`src/agentcfg/model_delegate_cli.py`；`src/agentcfg/model_delegate_context.py`；`src/agentcfg/pi_acceptance.py`；`src/agentcfg/pi_auxiliary.py`；`src/agentcfg/pi_checkpoints.py`；`src/agentcfg/pi_checks.py`；`src/agentcfg/pi_cold_rebuild.py`；`src/agentcfg/pi_commands.py`；`src/agentcfg/pi_control.py`；`src/agentcfg/pi_delegate.py`；`src/agentcfg/pi_delegate_commands.py`；`src/agentcfg/pi_delegate_files.py`；`src/agentcfg/pi_delegate_mcp.py`；`src/agentcfg/pi_delegate_policy.py`；`src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_diagnostics.py`；`src/agentcfg/pi_evidence.py`；`src/agentcfg/pi_guarded_files.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_lifecycle.py`；`src/agentcfg/pi_login.py`；`src/agentcfg/pi_mcp_script.py`；`src/agentcfg/pi_operations.py`；`src/agentcfg/pi_readseek.py`；`src/agentcfg/pi_readseek_mutations.py`；`src/agentcfg/pi_readseek_prepare.py`；`src/agentcfg/pi_readseek_select.py`；`src/agentcfg/pi_readseek_snapshot.py`；`src/agentcfg/pi_readseek_source.py`；`src/agentcfg/pi_recovery.py`；`src/agentcfg/pi_scope.py`；`src/agentcfg/pi_services.py`；`src/agentcfg/pi_supervisor.py`；`src/agentcfg/pi_upgrade.py`；`src/agentcfg/pi_validation_codex.py`；`src/agentcfg/pi_validation_delegate.py`；`src/agentcfg/pi_validation_live.py`；`src/agentcfg/pi_validation_live_services.py`；`src/agentcfg/pi_validation_native.py`；`src/agentcfg/pi_validation_recovery.py`；`src/agentcfg/pi_web_browser.py`；`src/agentcfg/pi_web_cli.py`；`src/agentcfg/pi_web_files.py`；`src/agentcfg/pi_web_media.py`；`src/agentcfg/pi_worker_files.py`；`src/agentcfg/pi_worker_protocol.py`；`src/agentcfg/process_tracking.py`；`src/agentcfg/workspace_leases.py`；`tests/test_model_delegate_batch.py`；`tests/test_model_delegate_cli.py`；`tests/test_model_delegate_codex_worker.py`；`tests/test_model_delegate_lifecycle.py`；`tests/test_pi_activity.py`；`tests/test_pi_checkpoints.py`；`tests/test_pi_checks.py`；`tests/test_pi_codex_endpoint.py`；`tests/test_pi_commands.py`；`tests/test_pi_delegate_commands.py`；`tests/test_pi_delegate_files.py`；`tests/test_pi_delegate_mcp.py`；`tests/test_pi_delegate_native.py`；`tests/test_pi_multirun.py`；`tests/test_pi_native_roots.py`；`tests/test_pi_readseek_results.py`；`tests/test_pi_release_gate.py`；`tests/test_pi_services.py`；`tests/test_pi_worker_files.py`；`tests/test_pi_worker_protocol.py`；`tests/test_register_pi_evidence_negative.py` |
| `activity_linux.py` | unresolved：先解除下列消费者，落实历史状态保护；不承接旧任务平台 | `scripts/smoke-pi-concurrency.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_pid_namespace.py`；`src/agentcfg/pi_recovery.py`；`src/agentcfg/pi_validation_recovery.py`；`tests/test_pi_activity_linux.py`；`tests/test_pi_pid_namespace.py` |
| `activity_macos.py` | unresolved：先解除下列消费者，落实历史状态保护；不承接旧任务平台 | `src/agentcfg/pi_host.py`；`src/agentcfg/pi_recovery.py`；`src/agentcfg/pi_validation_recovery.py`；`tests/test_pi_activity_macos.py` |
| `model_delegate.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-delegate-codex.py`；`scripts/pi-delegate-mcp.py`；`src/agentcfg/model_delegate_batch.py`；`src/agentcfg/model_delegate_cli.py`；`src/agentcfg/model_delegate_context.py`；`src/agentcfg/pi_delegate.py`；`src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_validation_delegate.py`；`src/agentcfg/pi_validation_live_delegate.py`；`tests/test_model_delegate_backends.py`；`tests/test_model_delegate_batch.py`；`tests/test_model_delegate_contract.py`；`tests/test_model_delegate_lifecycle.py`；`tests/test_pi_delegate_commands.py`；`tests/test_pi_validation_fixture.py` |
| `model_delegate_backends.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-delegate-codex.py`；`src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_login.py`；`tests/test_model_delegate_backends.py`；`tests/test_pi_codex_endpoint.py`；`tests/test_pi_delegate_native.py`；`tests/test_pi_native_roots.py` |
| `model_delegate_batch.py` | remove：旧专属执行/功能/验证链退出 | `scripts/model-delegate-batch.py` |
| `model_delegate_cli.py` | remove：旧专属执行/功能/验证链退出 | `scripts/model-delegate.py`；`src/agentcfg/model_delegate_batch.py`；`src/agentcfg/pi_validation_codex.py`；`src/agentcfg/pi_validation_delegate.py`；`src/agentcfg/pi_validation_live_delegate.py`；`tests/test_model_delegate_cli.py`；`tests/test_pi_codex_admission.py`；`tests/test_pi_delegate_native.py` |
| `model_delegate_context.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/model_delegate_cli.py`；`src/agentcfg/pi_delegate.py`；`tests/test_model_delegate_cli.py`；`tests/test_model_delegate_context.py` |
| `pi.py` | rebuild：严格CLI薄适配/资源投影 | `src/agentcfg/model_delegate_cli.py`；`src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_diagnostics.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_mcp.py`；`src/agentcfg/pi_web.py`；`src/agentcfg/workspace.py`；`tests/test_execution_environment_runtime.py`；`tests/test_local_values.py`；`tests/test_model_defaults.py`；`tests/test_pi_adapter.py`；`tests/test_pi_capture.py`；`tests/test_pi_cursor_profile.py`；`tests/test_pi_doctor.py`；`tests/test_pi_extension_bridge.py`；`tests/test_pi_multirun.py`；`tests/test_pi_optional_capabilities.py`；`tests/test_pi_pipeline.py`；`tests/test_pi_resource_discovery.py`；`tests/test_pi_web.py` |
| `pi_acceptance.py` | remove：旧专属执行/功能/验证链退出 | `scripts/register-pi-evidence.py`；`src/agentcfg/pi_scope.py`；`src/agentcfg/pi_validation_live.py`；`src/agentcfg/pi_verification.py`；`tests/test_pi_release_gate.py`；`tests/test_pi_verification_cli.py`；`tests/test_register_pi_evidence_negative.py` |
| `pi_assets.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_dependencies.py`；`src/agentcfg/pi_native_build.py`；`src/agentcfg/pi_readseek_native.py`；`src/agentcfg/pi_readseek_source.py`；`src/agentcfg/pi_vendor.py`；`tests/test_pi_data_assets.py` |
| `pi_auxiliary.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_host.py` |
| `pi_catalog.py` | remove：旧专属执行/功能/验证链退出 | `scripts/register-pi-evidence.py`；`scripts/smoke-pi-concurrency.py`；`src/agentcfg/activity.py`；`src/agentcfg/activity_linux.py`；`src/agentcfg/activity_macos.py`；`src/agentcfg/model_delegate_backends.py`；`src/agentcfg/pi.py`；`src/agentcfg/pi_acceptance.py`；`src/agentcfg/pi_control.py`；`src/agentcfg/pi_delegate_policy.py`；`src/agentcfg/pi_evidence.py`；`src/agentcfg/pi_guarded_files.py`；`src/agentcfg/pi_inventory.py`；`src/agentcfg/pi_lifecycle.py`；`src/agentcfg/pi_pid_namespace.py`；`src/agentcfg/pi_recovery.py`；`src/agentcfg/pi_runtime_packages.py`；`src/agentcfg/pi_supervisor.py`；`src/agentcfg/pi_validation_report.py`；`src/agentcfg/pi_worker_protocol.py`；`src/agentcfg/process_tracking.py`；`src/agentcfg/workspace_leases.py`；`tests/test_pi_capability_manifest.py`；`tests/test_pi_catalog_schema.py`；`tests/test_pi_commands.py`；`tests/test_pi_guarded_files.py`；`tests/test_pi_readseek_prepare.py`；`tests/test_pi_worker_protocol.py` |
| `pi_checkpoints.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py`；`tests/test_pi_checkpoints.py` |
| `pi_checks.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-readseek.py`；`src/agentcfg/pi_auxiliary.py`；`src/agentcfg/pi_commands.py`；`src/agentcfg/pi_delegate_commands.py`；`src/agentcfg/pi_mcp_script.py`；`src/agentcfg/pi_readseek_prepare.py`；`src/agentcfg/pi_readseek_select.py`；`src/agentcfg/pi_services.py`；`src/agentcfg/pi_web_cli.py`；`src/agentcfg/pi_web_media.py`；`tests/test_pi_checks.py`；`tests/test_pi_commands.py`；`tests/test_pi_git_status.py`；`tests/test_pi_mcp_script.py`；`tests/test_pi_readseek_prepare.py`；`tests/test_pi_services.py`；`tests/test_pi_web_cli.py` |
| `pi_codex_admission.py` | remove：旧专属执行/功能/验证链退出 | `scripts/model-delegate.py`；`scripts/pi-delegate-codex.py`；`src/agentcfg/model_delegate_cli.py`；`src/agentcfg/pi_delegate_policy.py`；`src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_diagnostics.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_login.py`；`src/agentcfg/pi_supervisor.py`；`tests/test_pi_codex_endpoint.py`；`tests/test_pi_delegate.py` |
| `pi_cold_rebuild.py` | remove：旧专属执行/功能/验证链退出 | `scripts/register-pi-evidence.py`；`src/agentcfg/pi_validation_native.py`；`tests/test_pi_cold_rebuild.py`；`tests/test_register_pi_evidence_negative.py` |
| `pi_cold_sandbox.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_cold_rebuild.py`；`tests/test_pi_cold_sandbox.py` |
| `pi_commands.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py` |
| `pi_control.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-checkpoint.py`；`scripts/pi-control.py`；`scripts/pi-delegate-codex.py`；`scripts/pi-delegate-mcp.py`；`scripts/pi-file-operation.py`；`scripts/pi-readseek.py`；`scripts/smoke-pi-concurrency.py`；`src/agentcfg/model_delegate_batch.py`；`src/agentcfg/model_delegate_cli.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_supervisor.py`；`src/agentcfg/pi_validation_native.py`；`src/agentcfg/pi_validation_recovery.py`；`tests/test_model_delegate_batch.py`；`tests/test_pi_control_routing.py`；`tests/test_pi_host.py` |
| `pi_delegate.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_host.py`；`tests/test_pi_delegate.py` |
| `pi_delegate_commands.py` | remove：旧专属执行/功能/验证链退出 | `tests/test_pi_delegate_commands.py` |
| `pi_delegate_files.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_delegate.py`；`src/agentcfg/pi_delegate_commands.py`；`tests/test_pi_delegate_commands.py`；`tests/test_pi_delegate_files.py` |
| `pi_delegate_mcp.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-delegate-mcp.py`；`tests/test_pi_delegate_mcp.py` |
| `pi_delegate_policy.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-delegate-codex.py`；`src/agentcfg/model_delegate.py`；`src/agentcfg/model_delegate_backends.py`；`src/agentcfg/model_delegate_cli.py`；`src/agentcfg/pi.py`；`src/agentcfg/pi_codex_admission.py`；`src/agentcfg/pi_delegate.py`；`src/agentcfg/pi_delegate_spawn.py`；`tests/test_model_delegate_backends.py`；`tests/test_pi_codex_endpoint.py`；`tests/test_pi_delegate_native.py`；`tests/test_pi_native_roots.py` |
| `pi_delegate_spawn.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_host.py`；`tests/test_pi_delegate.py`；`tests/test_pi_native_roots.py` |
| `pi_dependencies.py` | rebuild：官方npm锁/暂存激活 | `scripts/register-pi-evidence.py`；`scripts/smoke-pi-concurrency.py`；`src/agentcfg/pi.py`；`src/agentcfg/pi_cold_rebuild.py`；`src/agentcfg/pi_runtime_packages.py`；`src/agentcfg/pi_validation_native.py`；`src/agentcfg/pi_validation_runtime.py`；`src/agentcfg/pi_vendor.py`；`tests/test_pi_assets.py`；`tests/test_pi_cold_rebuild.py`；`tests/test_pi_dependencies.py`；`tests/test_pi_optional_capabilities.py`；`tests/test_pi_pipeline.py` |
| `pi_diagnostics.py` | remove：旧专属执行/功能/验证链退出 | `scripts/register-pi-evidence.py`；`src/agentcfg/pi.py`；`src/agentcfg/pi_validation_live.py`；`tests/test_pi_doctor.py`；`tests/test_register_pi_evidence_negative.py` |
| `pi_editor.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py`；`tests/test_pi_editor.py` |
| `pi_evidence.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`src/agentcfg/pi_acceptance.py`；`src/agentcfg/pi_diagnostics.py`；`src/agentcfg/pi_validation_report.py`；`tests/test_pi_doctor.py`；`tests/test_pi_release_gate.py`；`tests/test_pi_upgrade.py` |
| `pi_extension_bridge.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`tests/test_pi_extension_bridge.py` |
| `pi_git_review.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py`；`src/agentcfg/pi_readseek_select.py`；`tests/test_pi_git_review.py` |
| `pi_git_status.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`src/agentcfg/pi_git_review.py`；`src/agentcfg/pi_operations.py`；`src/agentcfg/pi_readseek_prepare.py`；`src/agentcfg/pi_readseek_select.py`；`tests/test_pi_git_status.py` |
| `pi_guarded_files.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/model_delegate_backends.py`；`src/agentcfg/pi_checkpoints.py`；`src/agentcfg/pi_commands.py`；`src/agentcfg/pi_delegate.py`；`src/agentcfg/pi_delegate_commands.py`；`src/agentcfg/pi_delegate_files.py`；`src/agentcfg/pi_mcp_script.py`；`src/agentcfg/pi_native_roots.py`；`src/agentcfg/pi_operations.py`；`src/agentcfg/pi_readseek.py`；`src/agentcfg/pi_readseek_mutations.py`；`src/agentcfg/pi_readseek_prepare.py`；`src/agentcfg/pi_readseek_snapshot.py`；`src/agentcfg/pi_services.py`；`src/agentcfg/pi_web_cli.py`；`src/agentcfg/pi_web_files.py`；`src/agentcfg/pi_web_git.py`；`src/agentcfg/pi_web_media.py`；`src/agentcfg/pi_worker_files.py`；`tests/test_pi_guarded_files.py`；`tests/test_pi_readseek_controller.py`；`tests/test_pi_readseek_mutations.py`；`tests/test_pi_worker_files.py`；`tests/test_pi_worker_protocol.py` |
| `pi_host.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-recovery.py`；`scripts/pi-native-scenario.py`；`scripts/pi-supervisor.py`；`src/agentcfg/pi.py`；`src/agentcfg/pi_validation_migration.py`；`src/agentcfg/pi_validation_parent_loss.py`；`tests/test_pi_multirun.py`；`tests/test_pi_validation_migration.py`；`tests/test_pi_validation_parent_loss.py`；`tests/test_pi_worker_protocol.py` |
| `pi_inventory.py` | rebuild：新来源/状态投影 | `src/agentcfg/commands.py`；`src/agentcfg/pi_validation_migration.py`；`tests/test_pi_inventory.py`；`tests/test_pi_migration_flow.py` |
| `pi_lifecycle.py` | rebuild：公共运行/维护准入 | `scripts/pi-native-recovery.py`；`scripts/pi-native-scenario.py`；`scripts/register-pi-evidence.py`；`src/agentcfg/pi.py`；`src/agentcfg/pi_dependencies.py`；`src/agentcfg/pi_recovery.py`；`src/agentcfg/pi_validation_codex.py`；`src/agentcfg/pi_validation_delegate.py`；`src/agentcfg/pi_validation_fixture.py`；`src/agentcfg/pi_validation_live.py`；`src/agentcfg/pi_validation_live_delegate.py`；`src/agentcfg/pi_validation_live_services.py`；`src/agentcfg/pi_validation_migration.py`；`src/agentcfg/pi_validation_native.py`；`src/agentcfg/pi_validation_recovery.py`；`tests/test_pi_recover_cli.py`；`tests/test_register_pi_evidence_negative.py` |
| `pi_live_project.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_validation_live_services.py`；`src/agentcfg/pi_verification.py`；`tests/test_pi_live_project.py`；`tests/test_pi_verification_cli.py` |
| `pi_login.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_host.py`；`tests/test_pi_login.py` |
| `pi_mcp.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`tests/test_pi_optional_capabilities.py` |
| `pi_mcp_script.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_mcp.py`；`src/agentcfg/pi_operations.py`；`tests/test_pi_mcp_script.py` |
| `pi_mcp_stdio.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py` |
| `pi_native_build.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_dependencies.py`；`tests/test_pi_native_build.py` |
| `pi_native_roots.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/model_delegate_backends.py`；`src/agentcfg/pi_delegate_policy.py`；`tests/test_pi_native_roots.py` |
| `pi_operations.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_host.py`；`tests/test_pi_commands.py`；`tests/test_pi_operations.py`；`tests/test_pi_readseek_prepare.py` |
| `pi_output.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_host.py`；`src/agentcfg/pi_validation_native.py`；`src/agentcfg/pi_validation_recovery.py`；`tests/test_pi_output.py` |
| `pi_pid_namespace.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-delegate-codex.py`；`scripts/smoke-pi-concurrency.py`；`src/agentcfg/activity_linux.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_validation_codex.py`；`src/agentcfg/pi_validation_delegate.py`；`tests/test_pi_pid_namespace.py` |
| `pi_readseek.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py` |
| `pi_readseek_mutations.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_readseek_results.py`；`tests/test_pi_readseek_mutations.py` |
| `pi_readseek_native.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_vendor.py`；`tests/test_pi_readseek_native.py` |
| `pi_readseek_prepare.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_readseek.py` |
| `pi_readseek_results.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_readseek.py`；`src/agentcfg/pi_readseek_prepare.py`；`tests/test_pi_readseek_results.py` |
| `pi_readseek_select.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_readseek_prepare.py`；`tests/test_pi_readseek_selection.py` |
| `pi_readseek_selection.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_readseek_prepare.py`；`src/agentcfg/pi_readseek_select.py`；`tests/test_pi_readseek_selection.py` |
| `pi_readseek_snapshot.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_readseek_prepare.py`；`src/agentcfg/pi_readseek_results.py`；`tests/test_pi_readseek_controller.py`；`tests/test_pi_readseek_results.py`；`tests/test_pi_readseek_snapshot.py` |
| `pi_readseek_source.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_readseek_native.py`；`tests/test_pi_readseek_source.py` |
| `pi_readseek_vision.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_assets.py`；`src/agentcfg/pi_vendor.py` |
| `pi_recovery.py` | unresolved：先解除下列消费者，落实历史状态保护；不承接旧任务平台 | `scripts/pi-native-recovery.py`；`src/agentcfg/commands.py`；`src/agentcfg/pi_validation_recovery.py` |
| `pi_resource_reads.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_diagnostics.py`；`src/agentcfg/pi_operations.py`；`tests/test_pi_operations.py` |
| `pi_rules.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`src/agentcfg/pi_operations.py`；`tests/test_pi_rules.py` |
| `pi_runtime_packages.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_dependencies.py`；`src/agentcfg/pi_validation_runtime.py`；`tests/test_pi_data_assets.py`；`tests/test_pi_dependencies.py` |
| `pi_scope.py` | remove：旧专属执行/功能/验证链退出 | `scripts/register-pi-evidence.py`；`src/agentcfg/pi_cold_rebuild.py`；`src/agentcfg/pi_cold_sandbox.py`；`src/agentcfg/pi_validation_fixture.py`；`src/agentcfg/pi_validation_runtime.py`；`tests/test_pi_release_gate.py`；`tests/test_pi_validation_live.py`；`tests/test_register_pi_evidence_negative.py` |
| `pi_services.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`src/agentcfg/pi_commands.py`；`src/agentcfg/pi_mcp_script.py`；`src/agentcfg/pi_operations.py`；`src/agentcfg/pi_web_cli.py`；`tests/test_pi_services.py` |
| `pi_supervisor.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-delegate-codex.py`；`scripts/pi-native-recovery.py`；`scripts/pi-native-scenario.py`；`scripts/pi-readseek.py`；`src/agentcfg/pi_auxiliary.py`；`src/agentcfg/pi_checkpoints.py`；`src/agentcfg/pi_commands.py`；`src/agentcfg/pi_delegate.py`；`src/agentcfg/pi_delegate_commands.py`；`src/agentcfg/pi_delegate_files.py`；`src/agentcfg/pi_delegate_mcp.py`；`src/agentcfg/pi_delegate_policy.py`；`src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_editor.py`；`src/agentcfg/pi_git_review.py`；`src/agentcfg/pi_git_status.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_login.py`；`src/agentcfg/pi_mcp_script.py`；`src/agentcfg/pi_mcp_stdio.py`；`src/agentcfg/pi_native_roots.py`；`src/agentcfg/pi_operations.py`；`src/agentcfg/pi_readseek.py`；`src/agentcfg/pi_readseek_mutations.py`；`src/agentcfg/pi_readseek_prepare.py`；`src/agentcfg/pi_readseek_results.py`；`src/agentcfg/pi_readseek_snapshot.py`；`src/agentcfg/pi_rules.py`；`src/agentcfg/pi_services.py`；`src/agentcfg/pi_web_browser.py`；`src/agentcfg/pi_web_cli.py`；`src/agentcfg/pi_web_files.py`；`src/agentcfg/pi_web_git.py`；`src/agentcfg/pi_web_media.py`；`src/agentcfg/pi_worker_files.py`；`src/agentcfg/pi_worker_protocol.py`；`tests/test_model_delegate_cli.py`；`tests/test_pi_checkpoints.py`；`tests/test_pi_codex_admission.py`；`tests/test_pi_delegate.py`；`tests/test_pi_delegate_commands.py`；`tests/test_pi_delegate_files.py`；`tests/test_pi_delegate_native.py`；`tests/test_pi_delegate_retirement.py`；`tests/test_pi_git_status.py`；`tests/test_pi_host.py`；`tests/test_pi_mcp_script.py`；`tests/test_pi_multirun.py`；`tests/test_pi_operations.py`；`tests/test_pi_readseek_controller.py`；`tests/test_pi_readseek_driver.py`；`tests/test_pi_readseek_prepare.py`；`tests/test_pi_rules.py`；`tests/test_pi_services.py`；`tests/test_pi_supervisor.py`；`tests/test_pi_terminal.py`；`tests/test_pi_web_browser.py`；`tests/test_pi_web_files.py` |
| `pi_terminal.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_commands.py`；`src/agentcfg/pi_editor.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_supervisor.py` |
| `pi_upgrade.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`tests/test_pi_upgrade.py` |
| `pi_validation.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_verification.py`；`tests/test_pi_verification_cli.py` |
| `pi_validation_codex.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py` |
| `pi_validation_codex_provider.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`tests/test_pi_validation_codex_provider.py` |
| `pi_validation_delegate.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py` |
| `pi_validation_fixture.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`scripts/smoke-pi-concurrency.py`；`src/agentcfg/pi_cold_rebuild.py`；`tests/test_pi_cursor_readseek_binding.py`；`tests/test_pi_validation_fixture.py` |
| `pi_validation_live.py` | remove：旧专属执行/功能/验证链退出 | `scripts/register-pi-evidence.py`；`src/agentcfg/pi_validation.py`；`src/agentcfg/pi_validation_report.py`；`tests/test_pi_validation_live.py` |
| `pi_validation_live_delegate.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_validation_live.py`；`tests/test_pi_validation_live_delegate.py` |
| `pi_validation_live_services.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`src/agentcfg/pi_validation_live.py`；`src/agentcfg/pi_validation_native.py`；`src/agentcfg/pi_validation_report.py`；`tests/test_pi_validation_live_services.py` |
| `pi_validation_migration.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`tests/test_pi_validation_migration.py` |
| `pi_validation_native.py` | remove：旧专属执行/功能/验证链退出 | `scripts/smoke-pi-concurrency.py`；`src/agentcfg/pi_cold_rebuild.py`；`src/agentcfg/pi_validation.py`；`src/agentcfg/pi_validation_live_services.py`；`src/agentcfg/pi_validation_report.py`；`tests/test_pi_validation_native.py`；`tests/test_register_pi_evidence_negative.py` |
| `pi_validation_parent_loss.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`tests/test_pi_validation_native.py`；`tests/test_pi_validation_parent_loss.py` |
| `pi_validation_provider.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`src/agentcfg/pi_validation_codex_provider.py`；`src/agentcfg/pi_validation_service_provider.py`；`tests/test_pi_validation_native.py`；`tests/test_pi_validation_provider.py` |
| `pi_validation_recovery.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py` |
| `pi_validation_report.py` | remove：旧专属执行/功能/验证链退出 | `scripts/register-pi-evidence.py`；`src/agentcfg/pi_validation_live.py`；`src/agentcfg/pi_verification.py`；`tests/test_pi_validation_report.py` |
| `pi_validation_runtime.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`scripts/smoke-pi-concurrency.py`；`src/agentcfg/pi_validation_live.py`；`src/agentcfg/pi_validation_native.py`；`tests/test_pi_validation_live.py`；`tests/test_pi_validation_native.py`；`tests/test_pi_validation_report.py`；`tests/test_pi_validation_runtime.py` |
| `pi_validation_sandbox.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_validation_native.py`；`tests/test_pi_validation_sandbox.py` |
| `pi_validation_service_provider.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-native-scenario.py`；`tests/test_pi_validation_service_provider.py` |
| `pi_vendor.py` | remove：旧专属执行/功能/验证链退出 | `scripts/build-pi-vendor.py`；`src/agentcfg/pi_cold_rebuild.py`；`src/agentcfg/pi_dependencies.py`；`src/agentcfg/pi_readseek_source.py`；`tests/test_pi_assets.py`；`tests/test_pi_dependencies.py`；`tests/test_pi_optional_capabilities.py`；`tests/test_pi_vendor.py` |
| `pi_verification.py` | remove：旧专属执行/功能/验证链退出 | `scripts/verify-pi.py`；`tests/test_pi_validation_report.py`；`tests/test_pi_verification_cli.py` |
| `pi_web.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi.py`；`tests/test_pi_web.py` |
| `pi_web_browser.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py`；`tests/test_pi_web_browser.py` |
| `pi_web_cli.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_commands.py`；`src/agentcfg/pi_operations.py`；`tests/test_pi_web_cli.py` |
| `pi_web_files.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py`；`tests/test_pi_web_files.py`；`tests/test_pi_web_media.py` |
| `pi_web_git.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py`；`src/agentcfg/pi_web_cli.py`；`tests/test_pi_web_cli.py` |
| `pi_web_media.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_operations.py` |
| `pi_web_relay.py` | remove：旧专属执行/功能/验证链退出 | `scripts/pi-web-cli.py`；`tests/test_pi_web_relay.py` |
| `pi_worker_files.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/model_delegate_cli.py`；`src/agentcfg/pi_delegate.py`；`src/agentcfg/pi_delegate_files.py`；`src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_supervisor.py`；`src/agentcfg/pi_validation_live_delegate.py`；`tests/test_model_delegate_cli.py`；`tests/test_pi_delegate_commands.py`；`tests/test_pi_delegate_files.py`；`tests/test_pi_worker_files.py`；`tests/test_pi_worker_protocol.py` |
| `pi_worker_protocol.py` | remove：旧专属执行/功能/验证链退出 | `src/agentcfg/pi_delegate_spawn.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_supervisor.py`；`tests/test_pi_worker_protocol.py` |
| `process_tracking.py` | unresolved：先解除下列消费者，落实历史状态保护；不承接旧任务平台 | `src/agentcfg/activity_linux.py`；`src/agentcfg/activity_macos.py` |
| `workspace_leases.py` | unresolved：先解除下列消费者，落实历史状态保护；不承接旧任务平台 | `src/agentcfg/pi.py`；`src/agentcfg/pi_host.py`；`src/agentcfg/pi_native_roots.py`；`src/agentcfg/pi_recovery.py`；`tests/test_model_delegate_lifecycle.py`；`tests/test_pi_activity.py`；`tests/test_pi_control_recovery.py`；`tests/test_pi_delegate.py`；`tests/test_pi_multirun.py`；`tests/test_pi_worker_files.py`；`tests/test_pi_workspace_leases.py` |

## 5. shared单项、测试和文档

| 来源 | 消费者与处置 | 前置/验证 |
| --- | --- | --- |
| `shared/content.toml` 中skills.model-delegate | 旧三个日常profile与agent默认；remove该单项注册，其他条目保留 | 解除默认/profile/提示，V1/V2 |
| `shared/skills/model-delegate/` | shell→Python→Pi/Codex、context/receipt/progress/重试/监督、presets/schemas/测试；remove旧分发 | 外部副本/自选消费者U1 unresolved，不能因shared名保留旧执行平台，V1/V4 |
| `shared/defaults/models.toml` | 三工具公共provider/model/role默认；rebuild仅Pi映射，保留其他工具 | 不是旧执行资源，不删除公共模型，V2 |
| `shared/models.toml`、`providers.toml`、`model-templates.toml`、`mcp.toml`（均在shared） | 公共catalog；replace必要Pi旧路由，保留公共来源 | 相同provider名不授权共享账号，V2 |
| `shared/rules/chinese.md`、`terminal.md`、`cpp-local-search.md`（均在rules） | 公共同源规则；rebuild必要旧工具建议，保留其他用途 | 逐项审阅不整组删除，V1/V2 |
| `shared/skills/repo-navigation/`、`maintain-agent-config/`、`cpp-database-kernel/`、`neovim-plugin-development/`、`safe-linux-scripting/`（均在shared/skills） | 已有完整公共技能，rebuild必要旧命令建议；保留内容/支持资源/许可 | 旧profile选择不赋予删除所有权，新选择投影重验，V1/V2 |
| `tests/test_pi*.py`、`test_model_delegate*.py`、`test_fetch_pi_assets.py`、`test_register_pi_evidence_negative.py`、`tests/fixtures/pi/` | remove旧selector/平台假设；rebuild仍适用所有权/隔离/失败保护 | 文件清单见下节；不把旧通过转新组合，V1/V2/V4 |
| 其余命中Pi的公共测试（下节清单） | config/catalog/render/native/runtime/presentation/lock/skills等；rebuild Pi案例，保留DSH/OMP断言 | 不按关键字整文件删除，V2 |
| `docs/pi*.md`、`docs/acceptance/pi*.md` | replace当前指南；archive历史验收与支持矩阵范围 | 区分实现/旧验收/当前支持，V5 |
| `specs/001-unify-pi-capabilities/` | archive旧规格/任务/契约原有含义，不改写完成状态与结果 | 不继续分发执行平台，不冒充新验收，V5 |
| `docs/design/pi-toolkit-v2/`八份临时文件 | replace有效信息到正式feature/指南后remove临时材料 | 保留固定来源/许可/限制并修链接，V5 |
| 根README/公共docs/scripts/.github命中引用（下节） | replace旧ID/命令/链接，历史事实按范围保留 | 文字引用不等于动态执行消费者，V1/V5 |

## 6. unresolved与升级

| ID | 未决事实 | 阻止范围/后续所有者 |
| --- | --- | --- |
| U1 | shared model-delegate可能有用户自选/已部署副本；未见DSH/OMP默认选择不证明仓库外无消费者 | 阻止清理外部副本/账号/任务；主代理落实迁移说明和回归，仓库注册退出无需继续发行旧平台 |
| U2 | activity/工作区marker/任务库报告/macOS helper跨目录进程身份；真实owner/活动未检查 | 阻止不安全切换/状态清除；T039/T040/T044落实未知owner保守冲突与停止使用/人工归档，不延续旧闭包 |
| U3 | CLI、生成commands.json、TS import/global/资源reload、包入口与Python导入不同图 | 删除批次查生成程序表/加载/分发/发现；T041–T048以旧链缺席重建闭合，静态初始盘点不批准删除 |
| U4 | 模型补全/catalog/展示服务多工具，本包不决定公共抽取接口 | 阻止整文件删除或任意语义重构；主代理结合T003矩阵和回归决定 |

已升级主代理，无新的人类决策请求。unknown不是空闲；不删marker、不终止进程、不重放未知工具。
配置rollback不声称软件/数据库/任务恢复。

## 7. 相对路径快照

这是初始文件集合或完整目录边界。包内vendor只记录目录及数量，不复制全部第三方内部文件。
后续变更更新清单和消费者证据；清单数量不证明内容完整性或运行支持。

### Pi声明、资源、runtime、schema、build、migration（311项）

```text
agents/pi/NOTICE.md
agents/pi/agent.toml
agents/pi/bindings.toml
agents/pi/build/btw-agentcfg.patch
agents/pi/build/licenses/codex/LICENSE
agents/pi/build/licenses/codex/NOTICE
agents/pi/build/licenses/codex/SOURCE.json
agents/pi/build/licenses/codex-bwrap/COPYING
agents/pi/build/licenses/codex-bwrap/LICENSE
agents/pi/build/licenses/codex-bwrap/SOURCE.json
agents/pi/build/licenses/pi-host/LICENSE
agents/pi/build/licenses/pi-host/SOURCE.json
agents/pi/build/licenses/readseek/LICENSE.native
agents/pi/build/licenses/readseek/SOURCE.json
agents/pi/build/licenses/readseek-vision/LICENSE
agents/pi/build/licenses/readseek-vision/SOURCE.json
agents/pi/build/mcp-agentcfg.patch
agents/pi/build/permission-system-patch.json
agents/pi/build/permission-system.patch
agents/pi/build/processes-supervisor.patch
agents/pi/build/readseek-agentcfg.patch
agents/pi/build/readseek-source.json
agents/pi/build/recipes.json
agents/pi/build/slopchop-agentcfg.patch
agents/pi/build/smart-compact-agentcfg.patch
agents/pi/build/superpowers-agentcfg.patch
agents/pi/build/web-agentcfg.patch
agents/pi/content.toml
agents/pi/dependencies.json
agents/pi/extensions/dirty-repo-guard.ts
agents/pi/extensions/exit-command.ts
agents/pi/extensions/gentle-agent-state.ts
agents/pi/extensions/git-checkpoint.ts
agents/pi/extensions/handoff.ts
agents/pi/extensions/notify.ts
agents/pi/migration/STARTER-LICENSE
agents/pi/migration/btw-manifest.json
agents/pi/migration/caller-map.json
agents/pi/migration/capabilities.toml
agents/pi/migration/local-plugins-manifest.json
agents/pi/migration/model-delegate-manifest.json
agents/pi/migration/permission-system-manifest.json
agents/pi/migration/preset-manifest.json
agents/pi/migration/processes-manifest.json
agents/pi/migration/readseek-manifest.json
agents/pi/migration/resource-manifest.json
agents/pi/migration/role-map.json
agents/pi/migration/slopchop-manifest.json
agents/pi/migration/smart-compact-manifest.json
agents/pi/migration/source-baseline.json
agents/pi/migration/subagents-manifest.json
agents/pi/migration/task-keeper-manifest.json
agents/pi/migration/web-manifest.json
agents/pi/plugins.toml
agents/pi/prompts/commit.md
agents/pi/prompts/debug.md
agents/pi/prompts/docs.md
agents/pi/prompts/explain.md
agents/pi/prompts/implement.md
agents/pi/prompts/perf.md
agents/pi/prompts/plan.md
agents/pi/prompts/pr.md
agents/pi/prompts/refactor.md
agents/pi/prompts/review.md
agents/pi/prompts/security.md
agents/pi/prompts/test.md
agents/pi/roles/reviewer.md
agents/pi/roles/scout.md
agents/pi/runtime/NOTICE.md
agents/pi/runtime/auxiliary-executor.ts
agents/pi/runtime/bunfig.locked.toml
agents/pi/runtime/capability-policy.ts
agents/pi/runtime/checkpoints.ts
agents/pi/runtime/delegate-pi-main.ts
agents/pi/runtime/delegate-pi.ts
agents/pi/runtime/delegate-response.ts
agents/pi/runtime/external-control.ts
agents/pi/runtime/external-executor.ts
agents/pi/runtime/external-rpc.ts
agents/pi/runtime/git-status.ts
agents/pi/runtime/guarded-tools.ts
agents/pi/runtime/image-mime.ts
agents/pi/runtime/launch.ts
agents/pi/runtime/managed-backend.ts
agents/pi/runtime/managed-bridge.ts
agents/pi/runtime/managed-http-transport.ts
agents/pi/runtime/managed-observation.ts
agents/pi/runtime/managed-results.ts
agents/pi/runtime/managed-rpc.ts
agents/pi/runtime/managed-store.ts
agents/pi/runtime/managed-types.ts
agents/pi/runtime/managed-validation.ts
agents/pi/runtime/managed-worker-main.ts
agents/pi/runtime/managed-worker.ts
agents/pi/runtime/manager-executor.ts
agents/pi/runtime/mcp-http.ts
agents/pi/runtime/mcp-listener.ts
agents/pi/runtime/mcp-script.ts
agents/pi/runtime/mcp-stdio.ts
agents/pi/runtime/mcp-tools.ts
agents/pi/runtime/metered-transport.ts
agents/pi/runtime/model-facade.ts
agents/pi/runtime/native-validation.ts
agents/pi/runtime/one-shot-schedule.ts
agents/pi/runtime/openspec-resources.json
agents/pi/runtime/ordinary-operations.ts
agents/pi/runtime/owned-listener.ts
agents/pi/runtime/package.json
agents/pi/runtime/permission-access.ts
agents/pi/runtime/permission-policy.ts
agents/pi/runtime/plugin-model.ts
agents/pi/runtime/plugin-settings.ts
agents/pi/runtime/plugin-storage.ts
agents/pi/runtime/readseek-artifact.ts
agents/pi/runtime/readseek-context.ts
agents/pi/runtime/readseek-controller.ts
agents/pi/runtime/readseek-git-main.ts
agents/pi/runtime/readseek-git.ts
agents/pi/runtime/readseek-process.ts
agents/pi/runtime/readseek-rg-main.ts
agents/pi/runtime/readseek-rg.ts
agents/pi/runtime/readseek-tool-contracts.json
agents/pi/runtime/readseek-worker.ts
agents/pi/runtime/regex-search.ts
agents/pi/runtime/regex-worker.ts
agents/pi/runtime/resource-loader.ts
agents/pi/runtime/review-files.ts
agents/pi/runtime/route-fetch.ts
agents/pi/runtime/runtime-module.ts
agents/pi/runtime/sandbox-macos.sb
agents/pi/runtime/service-bindings.ts
agents/pi/runtime/service-validation.ts
agents/pi/runtime/session-compatibility.ts
agents/pi/runtime/supervised-stdio.ts
agents/pi/runtime/supervisor-client.ts
agents/pi/runtime/terminal-command.ts
agents/pi/runtime/tests/agent-manager.test.ts
agents/pi/runtime/tests/auxiliary-executor.test.ts
agents/pi/runtime/tests/checkpoints.test.ts
agents/pi/runtime/tests/cursor-delegate.test.ts
agents/pi/runtime/tests/delegate-pi.test.ts
agents/pi/runtime/tests/external-control.test.ts
agents/pi/runtime/tests/external-executor.test.ts
agents/pi/runtime/tests/fixtures.ts
agents/pi/runtime/tests/git-status.test.ts
agents/pi/runtime/tests/guarded-tools.test.ts
agents/pi/runtime/tests/image-mime.test.ts
agents/pi/runtime/tests/launch.test.ts
agents/pi/runtime/tests/managed-backend.test.ts
agents/pi/runtime/tests/managed-bridge.test.ts
agents/pi/runtime/tests/managed-http-transport.test.ts
agents/pi/runtime/tests/managed-observation.test.ts
agents/pi/runtime/tests/managed-store-rpc.test.ts
agents/pi/runtime/tests/managed-validation.test.ts
agents/pi/runtime/tests/managed-worker.test.ts
agents/pi/runtime/tests/manager-config.test.ts
agents/pi/runtime/tests/manager-executor.test.ts
agents/pi/runtime/tests/mcp-elicitation.test.ts
agents/pi/runtime/tests/mcp-http.test.ts
agents/pi/runtime/tests/mcp-listener.test.ts
agents/pi/runtime/tests/mcp-oauth-binding.test.ts
agents/pi/runtime/tests/mcp-sampling.test.ts
agents/pi/runtime/tests/mcp-script.test.ts
agents/pi/runtime/tests/mcp-stdio.test.ts
agents/pi/runtime/tests/mcp-tools.test.ts
agents/pi/runtime/tests/native-validation.test.ts
agents/pi/runtime/tests/notify.test.ts
agents/pi/runtime/tests/ordinary-operations.test.ts
agents/pi/runtime/tests/permission-access.test.ts
agents/pi/runtime/tests/plugin-model.test.ts
agents/pi/runtime/tests/plugin-policy.test.ts
agents/pi/runtime/tests/plugin-storage.test.ts
agents/pi/runtime/tests/processes-bridge.test.ts
agents/pi/runtime/tests/readseek-artifact.test.ts
agents/pi/runtime/tests/readseek-context.test.ts
agents/pi/runtime/tests/readseek-controller.test.ts
agents/pi/runtime/tests/readseek-git.test.ts
agents/pi/runtime/tests/readseek-rg.test.ts
agents/pi/runtime/tests/readseek-worker.test.ts
agents/pi/runtime/tests/regex-search.test.ts
agents/pi/runtime/tests/resource-loader.test.ts
agents/pi/runtime/tests/route-fetch.test.ts
agents/pi/runtime/tests/rules.test.ts
agents/pi/runtime/tests/runtime-module.test.ts
agents/pi/runtime/tests/service-bindings.test.ts
agents/pi/runtime/tests/service-validation.test.ts
agents/pi/runtime/tests/session-compatibility.test.ts
agents/pi/runtime/tests/slopchop-read.test.ts
agents/pi/runtime/tests/smart-compact.test.ts
agents/pi/runtime/tests/superpowers.test.ts
agents/pi/runtime/tests/supervisor-client.test.ts
agents/pi/runtime/tests/terminal-command.test.ts
agents/pi/runtime/tests/todo-config.test.ts
agents/pi/runtime/tests/user-login.test.ts
agents/pi/runtime/tests/web-artifact.test.ts
agents/pi/runtime/tests/web-auth-fetch.test.ts
agents/pi/runtime/tests/web-browser.test.ts
agents/pi/runtime/tests/web-cli-proxy.test.ts
agents/pi/runtime/tests/web-cli.test.ts
agents/pi/runtime/tests/web-config.test.ts
agents/pi/runtime/tests/web-files.test.ts
agents/pi/runtime/tests/web-github-api.test.ts
agents/pi/runtime/tests/web-github-view.test.ts
agents/pi/runtime/tests/web-http.test.ts
agents/pi/runtime/tests/web-listener.test.ts
agents/pi/runtime/tests/web-media.test.ts
agents/pi/runtime/tests/web-model-auth.test.ts
agents/pi/runtime/tests/web-model.test.ts
agents/pi/runtime/tests/web-plugin.test.ts
agents/pi/runtime/tests/web-runtime.test.ts
agents/pi/runtime/tests/web-search-routing.test.ts
agents/pi/runtime/tests/web-service-dispatch.test.ts
agents/pi/runtime/tests/web-storage.test.ts
agents/pi/runtime/tests/web-tools.test.ts
agents/pi/runtime/tool-ownership.ts
agents/pi/runtime/tsconfig.locked.json
agents/pi/runtime/types/auxiliary-executor.d.ts
agents/pi/runtime/types/capability-policy.d.ts
agents/pi/runtime/types/checkpoints.d.ts
agents/pi/runtime/types/external-control.d.ts
agents/pi/runtime/types/external-executor.d.ts
agents/pi/runtime/types/external-rpc.d.ts
agents/pi/runtime/types/git-status.d.ts
agents/pi/runtime/types/guarded-tools.d.ts
agents/pi/runtime/types/managed-backend.d.ts
agents/pi/runtime/types/managed-bridge.d.ts
agents/pi/runtime/types/managed-http-transport.d.ts
agents/pi/runtime/types/managed-observation.d.ts
agents/pi/runtime/types/managed-results.d.ts
agents/pi/runtime/types/managed-rpc.d.ts
agents/pi/runtime/types/managed-store.d.ts
agents/pi/runtime/types/managed-types.d.ts
agents/pi/runtime/types/manager-executor.d.ts
agents/pi/runtime/types/mcp-http.d.ts
agents/pi/runtime/types/mcp-listener.d.ts
agents/pi/runtime/types/mcp-script.d.ts
agents/pi/runtime/types/mcp-stdio.d.ts
agents/pi/runtime/types/mcp-tools.d.ts
agents/pi/runtime/types/permission-access.d.ts
agents/pi/runtime/types/permission-policy.d.ts
agents/pi/runtime/types/plugin-model.d.ts
agents/pi/runtime/types/plugin-settings.d.ts
agents/pi/runtime/types/plugin-storage.d.ts
agents/pi/runtime/types/readseek-context.d.ts
agents/pi/runtime/types/review-files.d.ts
agents/pi/runtime/types/service-bindings.d.ts
agents/pi/runtime/types/user-login.d.ts
agents/pi/runtime/types/web-artifact.d.ts
agents/pi/runtime/types/web-binding.d.ts
agents/pi/runtime/types/web-browser.d.ts
agents/pi/runtime/types/web-cli.d.ts
agents/pi/runtime/types/web-config.d.ts
agents/pi/runtime/types/web-files.d.ts
agents/pi/runtime/types/web-listener.d.ts
agents/pi/runtime/types/web-media.d.ts
agents/pi/runtime/types/web-model-auth.d.ts
agents/pi/runtime/types/web-model.d.ts
agents/pi/runtime/types/web-tools.d.ts
agents/pi/runtime/user-login.ts
agents/pi/runtime/web-address.ts
agents/pi/runtime/web-artifact.ts
agents/pi/runtime/web-auth-fetch.ts
agents/pi/runtime/web-binding.ts
agents/pi/runtime/web-browser.ts
agents/pi/runtime/web-cli-proxy.ts
agents/pi/runtime/web-cli.ts
agents/pi/runtime/web-config.ts
agents/pi/runtime/web-files.ts
agents/pi/runtime/web-http.ts
agents/pi/runtime/web-listener.ts
agents/pi/runtime/web-media.ts
agents/pi/runtime/web-model-auth.ts
agents/pi/runtime/web-model-execution.ts
agents/pi/runtime/web-model.ts
agents/pi/runtime/web-runtime.ts
agents/pi/runtime/web-tools.ts
agents/pi/runtime/workspace-main.ts
agents/pi/schemas/acceptance-item.schema.json
agents/pi/schemas/acceptance-scope.schema.json
agents/pi/schemas/agent.schema.json
agents/pi/schemas/catalog.schema.json
agents/pi/schemas/evidence.schema.json
agents/pi/schemas/execution-lease.schema.json
agents/pi/schemas/managed-descriptor.schema.json
agents/pi/schemas/migration-proposal.schema.json
agents/pi/schemas/migration.schema.json
agents/pi/schemas/operation-grant.schema.json
agents/pi/schemas/options.schema.json
agents/pi/schemas/permission-policy.schema.json
agents/pi/schemas/process-identity.schema.json
agents/pi/schemas/resources.schema.json
agents/pi/schemas/runtime-receipt.schema.json
agents/pi/schemas/stop-recovery-plan.schema.json
agents/pi/schemas/stop-recovery.schema.json
agents/pi/schemas/termination-evidence.schema.json
agents/pi/schemas/validation-run.schema.json
agents/pi/schemas/workspace-write-lease.schema.json
agents/pi/templates/AGENTS.template.md
agents/pi/templates/APPEND_SYSTEM.template.md
agents/pi/templates/keybindings.template.jsonc
agents/pi/themes/Ayu Dark.json
agents/pi/themes/Catppuccin Mocha.json
agents/pi/themes/Dracula.json
agents/pi/themes/Everforest Dark.json
agents/pi/themes/Gruvbox Dark.json
agents/pi/themes/Kanagawa Wave.json
agents/pi/themes/Nord.json
agents/pi/themes/One Dark.json
agents/pi/themes/Rosé Pine.json
agents/pi/themes/Tokyo Night.json
agents/pi/themes/poimandres.json
```

### 本地包完整目录边界

| 目录 | 文件数（含内部测试/资源/许可） |
| --- | --- |
| `agents/pi/packages/btw-vendor/` | 16 |
| `agents/pi/packages/colorful-footer/` | 4 |
| `agents/pi/packages/loop-guard/` | 18 |
| `agents/pi/packages/mcp-vendor/` | 114 |
| `agents/pi/packages/model-delegate/` | 8 |
| `agents/pi/packages/openai-proxy/` | 10 |
| `agents/pi/packages/openspec-resources/` | 35 |
| `agents/pi/packages/permission-system-vendor/` | 178 |
| `agents/pi/packages/processes-vendor/` | 121 |
| `agents/pi/packages/readseek-vendor/` | 15 |
| `agents/pi/packages/rules-vendor/` | 21 |
| `agents/pi/packages/session-yolo/` | 3 |
| `agents/pi/packages/slopchop-vendor/` | 16 |
| `agents/pi/packages/smart-compact-vendor/` | 173 |
| `agents/pi/packages/subagents-patch/` | 2 |
| `agents/pi/packages/subagents-vendor/` | 233 |
| `agents/pi/packages/superpowers-vendor/` | 56 |
| `agents/pi/packages/task-keeper/` | 438 |
| `agents/pi/packages/todo-vendor/` | 33 |
| `agents/pi/packages/web-vendor/` | 76 |

### 旧锁与vendor文件（32项）

```text
locks/pi/manifest.json
locks/pi/pi-codex/package-lock.json
locks/pi/pi-codex/package.json
locks/pi/pi-cursor/package-lock.json
locks/pi/pi-cursor/package.json
locks/pi/pi-default/package-lock.json
locks/pi/pi-default/package.json
locks/pi/pi-managed/package-lock.json
locks/pi/pi-managed/package.json
locks/pi/vendor/colorful-footer-b0bd4754598e80853a819be5cd173357480eaaac7292ab59e94aa805a674de76.tgz
locks/pi/vendor/loop-guard-9b221ecc318c35c0156cec75d9ba6fefae00c4ba6a96719204198867457f927b.tgz
locks/pi/vendor/model-delegate-1032c0d93ebbe3e1595388a6f60231cb1bee674c8b878cd69cfcc6091ca2edc3.tgz
locks/pi/vendor/openai-proxy-7661e72b70b6b1f7dd22b43ea1617f913942ff1c260fccfcbb016d60d18696c5.tgz
locks/pi/vendor/openspec-6df10895e8319e8264168f69cf9b0da80802be7e93bc548d49670707a3e0705f.tgz
locks/pi/vendor/pi-btw-0bba5bffb8c2ed51498611a87b8d001c416bad03437b4eef9c61e8a6814ddfd2.tgz
locks/pi/vendor/pi-mcp-fce107fa31a14aff60ffc3ef9e406eff58e5c8605aa799b0719501c8ca72f8ec.tgz
locks/pi/vendor/pi-permissions-281d8c932a87f577499bb7019bf73db38a9f6684e896cd9b202424b3b21c03da.tgz
locks/pi/vendor/pi-processes-dd3d9b14c59dc7e76db876c4fa6d4b9cfee0fe809c45e15b4523d0a824c11635.tgz
locks/pi/vendor/pi-readseek-80045f8479799243e86f6f1fe515dd0a36cbc197483841d2789d02fce6fd8759.tgz
locks/pi/vendor/pi-rules-3a7ccbadfe20fc92130c9ed4196380f1782ec0f7d867553cdda8abdb870cbbf0.tgz
locks/pi/vendor/pi-runtime-13a0e48c609dcbb7ecfb8852793c4f51ae807821899f09a2882d143482eedbfb.tgz
locks/pi/vendor/pi-runtime-5b328ca60b7f95f0622044cd2e18622df058614182bbd02588c08b9abd71b05a.tgz
locks/pi/vendor/pi-runtime-679915faf4e3bdd730e7429d811c3549fdd054cfb71d2db886b382edcc8c2e4c.tgz
locks/pi/vendor/pi-runtime-bd4e8127ad4bc7faa76cc09f66550176143a4ae3df205e172b4ae2d2168f8e42.tgz
locks/pi/vendor/pi-slopchop-5da54bd8b01c15cc4b639331c9c38751ce5a70cc9960e42b36f5097825594e15.tgz
locks/pi/vendor/pi-smart-compact-96a992cf87c30ca5ae6e69f4fedd124f4ae0010d180f91d37e6343b8a03e09a4.tgz
locks/pi/vendor/pi-subagents-9857d7e5afb34d2506477d6e87082fe08c04d8065ba33677b4760ffd77d6e2f1.tgz
locks/pi/vendor/pi-todo-2398861cc66fae8f3a545c53704ff8ffde1f63aa2022baa44083d56400bdb698.tgz
locks/pi/vendor/pi-web-3fc4ba56da8e32862579d4d86e57d82996eb432c96f4c5f3cc31042e05777566.tgz
locks/pi/vendor/session-yolo-3a66b383d00fc98f0386a38f27b9e5fed36d52bc831a51f7ac9193f5622d8b4f.tgz
locks/pi/vendor/superpowers-25387ec48e1dd1bf7a57b0f08723f3320e3edfa2a82aa7e7a6a96e52b42e0fe2.tgz
locks/pi/vendor/task-keeper-50251a3685ed8c1f9317bcf96d2f3ef980850e67bd5ea58900c8556bb76efd1c.tgz
```

### shared逐项文件（91项）

```text
shared/content.toml
shared/defaults/models.toml
shared/mcp.toml
shared/model-templates.toml
shared/models.toml
shared/providers.toml
shared/rules/chinese.md
shared/rules/cpp-local-search.md
shared/rules/terminal.md
shared/skills/cpp-database-kernel/LICENSE
shared/skills/cpp-database-kernel/SKILL.md
shared/skills/maintain-agent-config/SKILL.md
shared/skills/model-delegate/API.md
shared/skills/model-delegate/LICENSE
shared/skills/model-delegate/NOTICE.md
shared/skills/model-delegate/README.md
shared/skills/model-delegate/SKILL.md
shared/skills/model-delegate/USAGE.md
shared/skills/model-delegate/presets/challenge.md
shared/skills/model-delegate/presets/context.md
shared/skills/model-delegate/presets/general.md
shared/skills/model-delegate/presets/plan.md
shared/skills/model-delegate/presets/research.md
shared/skills/model-delegate/presets/review.md
shared/skills/model-delegate/presets/scout.md
shared/skills/model-delegate/references/codex-0154-interface.md
shared/skills/model-delegate/references/progress-protocol.md
shared/skills/model-delegate/schemas/context-v2.json
shared/skills/model-delegate/schemas/event-v1.json
shared/skills/model-delegate/schemas/event-v2.json
shared/skills/model-delegate/schemas/feedback-v2.json
shared/skills/model-delegate/schemas/receipt-v1.json
shared/skills/model-delegate/schemas/receipt-v2.json
shared/skills/model-delegate/schemas/request-v2.json
shared/skills/model-delegate/scripts/backends/codex-normalize.jq
shared/skills/model-delegate/scripts/backends/codex.sh
shared/skills/model-delegate/scripts/backends/pi-normalize.jq
shared/skills/model-delegate/scripts/backends/pi.sh
shared/skills/model-delegate/scripts/backends/test-fake.sh
shared/skills/model-delegate/scripts/codex-probe.sh
shared/skills/model-delegate/scripts/lib/context.sh
shared/skills/model-delegate/scripts/lib/contract.sh
shared/skills/model-delegate/scripts/lib/control.sh
shared/skills/model-delegate/scripts/lib/credentials.sh
shared/skills/model-delegate/scripts/lib/feedback.sh
shared/skills/model-delegate/scripts/lib/memory.sh
shared/skills/model-delegate/scripts/lib/progress.sh
shared/skills/model-delegate/scripts/lib/receipt.sh
shared/skills/model-delegate/scripts/lib/retry.sh
shared/skills/model-delegate/scripts/lib/routing.sh
shared/skills/model-delegate/scripts/lib/supervisor.sh
shared/skills/model-delegate/scripts/lib/workspace.sh
shared/skills/model-delegate/scripts/run-model-fanout.sh
shared/skills/model-delegate/scripts/run-model.py
shared/skills/model-delegate/scripts/run-model.sh
shared/skills/model-delegate/tests/fixtures/codex/empty-final.jsonl
shared/skills/model-delegate/tests/fixtures/codex/malformed.jsonl
shared/skills/model-delegate/tests/fixtures/codex/thread-started.jsonl
shared/skills/model-delegate/tests/fixtures/codex/turn-completed.jsonl
shared/skills/model-delegate/tests/fixtures/codex/turn-failed.jsonl
shared/skills/model-delegate/tests/fixtures/codex/usage.jsonl
shared/skills/model-delegate/tests/fixtures/fake-backend.sh
shared/skills/model-delegate/tests/test-backend-security.sh
shared/skills/model-delegate/tests/test-codex-backend.sh
shared/skills/model-delegate/tests/test-codex-e2e.sh
shared/skills/model-delegate/tests/test-concurrency.sh
shared/skills/model-delegate/tests/test-contract-v2.sh
shared/skills/model-delegate/tests/test-contract.sh
shared/skills/model-delegate/tests/test-enhancement.sh
shared/skills/model-delegate/tests/test-fanout.sh
shared/skills/model-delegate/tests/test-host-interop.sh
shared/skills/model-delegate/tests/test-input-safety.sh
shared/skills/model-delegate/tests/test-jsonl-boundary.sh
shared/skills/model-delegate/tests/test-lifecycle-v2.sh
shared/skills/model-delegate/tests/test-memory.sh
shared/skills/model-delegate/tests/test-parallel-policy.sh
shared/skills/model-delegate/tests/test-pi-backend.sh
shared/skills/model-delegate/tests/test-process-group.sh
shared/skills/model-delegate/tests/test-progress-boundary.sh
shared/skills/model-delegate/tests/test-resources.sh
shared/skills/model-delegate/tests/test-retry-matrix.sh
shared/skills/model-delegate/tests/test-routing.sh
shared/skills/model-delegate/tests/test-schema.sh
shared/skills/model-delegate/tests/test-supervisor-crash.sh
shared/skills/model-delegate/tests/test-supervisor.sh
shared/skills/neovim-plugin-development/LICENSE
shared/skills/neovim-plugin-development/SKILL.md
shared/skills/repo-navigation/SKILL.md
shared/skills/repo-navigation/references/cpp-local-context.md
shared/skills/safe-linux-scripting/LICENSE
shared/skills/safe-linux-scripting/SKILL.md
```

### 测试/fixture消费者（专属与公共）（159项）

```text
tests/conftest.py
tests/fixtures/framework/local.toml
tests/fixtures/framework/registry.toml
tests/fixtures/omp/command-scenarios/grammar-parse-upgrade-20261009.json
tests/fixtures/omp/registry.toml
tests/fixtures/pi/fake-host.mjs
tests/fixtures/pi/helper-host-stub.mjs
tests/fixtures/pi/macos/include/libproc.h
tests/fixtures/pi/macos/include/mach/message.h
tests/fixtures/pi/macos/include/sys/sysctl.h
tests/fixtures/pi/macos/include/sys/un.h
tests/fixtures/pi/macos/include/uuid/uuid.h
tests/fixtures/pi/macos/scope-harness.c
tests/fixtures/pi/mcp-elicitation-stub.mjs
tests/fixtures/pi/mock-boundaries.test.mjs
tests/fixtures/pi/mock-entry.mjs
tests/fixtures/pi/mock-guard.mjs
tests/fixtures/pi/tooling/package-lock.json
tests/fixtures/pi/tooling/package.json
tests/fixtures/pi/web-host-stub.mjs
tests/omp_permission_harness.py
tests/omp_permission_official_wrapper_fixture.ts
tests/test_audit_regressions.py
tests/test_config_examples.py
tests/test_config_policy.py
tests/test_config_resolution.py
tests/test_dsh_auto_review_experience.py
tests/test_dsh_pipeline.py
tests/test_dsh_tf.py
tests/test_dsh_upgrade.py
tests/test_execution_environment_runtime.py
tests/test_fetch_pi_assets.py
tests/test_init_local.py
tests/test_local_values.py
tests/test_model_defaults.py
tests/test_model_delegate_backends.py
tests/test_model_delegate_batch.py
tests/test_model_delegate_cli.py
tests/test_model_delegate_codex_worker.py
tests/test_model_delegate_context.py
tests/test_model_delegate_contract.py
tests/test_model_delegate_lifecycle.py
tests/test_model_templates.py
tests/test_model_urls.py
tests/test_model_wizard.py
tests/test_omp_adapter.py
tests/test_omp_command_history.py
tests/test_omp_discovery.py
tests/test_omp_execution_contract.py
tests/test_omp_foundation.py
tests/test_omp_input_diagnostics.py
tests/test_omp_permission_control.py
tests/test_omp_profiles.py
tests/test_omp_public_corpus.py
tests/test_omp_runtime_foundation.py
tests/test_omp_source_gate.py
tests/test_omp_standalone.py
tests/test_omp_usage_managed.py
tests/test_pi_activity.py
tests/test_pi_activity_linux.py
tests/test_pi_activity_macos.py
tests/test_pi_adapter.py
tests/test_pi_assets.py
tests/test_pi_capability_manifest.py
tests/test_pi_capture.py
tests/test_pi_catalog_schema.py
tests/test_pi_checkpoints.py
tests/test_pi_checks.py
tests/test_pi_codex_admission.py
tests/test_pi_codex_endpoint.py
tests/test_pi_cold_rebuild.py
tests/test_pi_cold_sandbox.py
tests/test_pi_commands.py
tests/test_pi_control_anchor.py
tests/test_pi_control_recovery.py
tests/test_pi_control_routing.py
tests/test_pi_cursor_profile.py
tests/test_pi_cursor_readseek_binding.py
tests/test_pi_data_assets.py
tests/test_pi_delegate.py
tests/test_pi_delegate_commands.py
tests/test_pi_delegate_files.py
tests/test_pi_delegate_mcp.py
tests/test_pi_delegate_native.py
tests/test_pi_delegate_retirement.py
tests/test_pi_dependencies.py
tests/test_pi_doctor.py
tests/test_pi_editor.py
tests/test_pi_evidence_schema.py
tests/test_pi_extension_bridge.py
tests/test_pi_git_review.py
tests/test_pi_git_status.py
tests/test_pi_guarded_files.py
tests/test_pi_host.py
tests/test_pi_inventory.py
tests/test_pi_live_project.py
tests/test_pi_login.py
tests/test_pi_mcp_script.py
tests/test_pi_mcp_stdio.py
tests/test_pi_migration_flow.py
tests/test_pi_multirun.py
tests/test_pi_native_build.py
tests/test_pi_native_roots.py
tests/test_pi_operations.py
tests/test_pi_optional_capabilities.py
tests/test_pi_output.py
tests/test_pi_pid_namespace.py
tests/test_pi_pipeline.py
tests/test_pi_readseek_controller.py
tests/test_pi_readseek_driver.py
tests/test_pi_readseek_mutations.py
tests/test_pi_readseek_native.py
tests/test_pi_readseek_prepare.py
tests/test_pi_readseek_results.py
tests/test_pi_readseek_selection.py
tests/test_pi_readseek_snapshot.py
tests/test_pi_readseek_source.py
tests/test_pi_readseek_vision.py
tests/test_pi_recover_cli.py
tests/test_pi_recovery.py
tests/test_pi_recovery_protocol_surrogate.py
tests/test_pi_release_gate.py
tests/test_pi_resource_discovery.py
tests/test_pi_rules.py
tests/test_pi_services.py
tests/test_pi_supervisor.py
tests/test_pi_terminal.py
tests/test_pi_upgrade.py
tests/test_pi_validation_codex_provider.py
tests/test_pi_validation_fixture.py
tests/test_pi_validation_live.py
tests/test_pi_validation_live_delegate.py
tests/test_pi_validation_live_services.py
tests/test_pi_validation_migration.py
tests/test_pi_validation_native.py
tests/test_pi_validation_parent_loss.py
tests/test_pi_validation_provider.py
tests/test_pi_validation_recovery.py
tests/test_pi_validation_report.py
tests/test_pi_validation_runtime.py
tests/test_pi_validation_sandbox.py
tests/test_pi_validation_service_provider.py
tests/test_pi_vendor.py
tests/test_pi_verification_cli.py
tests/test_pi_web.py
tests/test_pi_web_browser.py
tests/test_pi_web_cli.py
tests/test_pi_web_files.py
tests/test_pi_web_media.py
tests/test_pi_web_relay.py
tests/test_pi_worker_files.py
tests/test_pi_worker_protocol.py
tests/test_pi_workspace_leases.py
tests/test_presentation.py
tests/test_project.py
tests/test_register_pi_evidence_negative.py
tests/test_render.py
tests/test_runtime.py
tests/test_shared_model_keys.py
```

### 脚本、指南、示例、schema、profile等消费者（86项）

```text
AGENTS.md
README.md
README.zh-CN.md
docs/README.md
docs/acceptance/pi-managed-mock.md
docs/acceptance/pi-support-matrix.md
docs/acceptance.md
docs/architecture.md
docs/design/pi-toolkit-v2/README.md
docs/design/pi-toolkit-v2/capabilities.md
docs/design/pi-toolkit-v2/community-research.md
docs/design/pi-toolkit-v2/design.md
docs/design/pi-toolkit-v2/migration-and-validation.md
docs/design/pi-toolkit-v2/plugin-selection.md
docs/design/pi-toolkit-v2/progress.md
docs/design/pi-toolkit-v2/upstream-and-portable-tools.md
docs/design/project-refactoring.md
docs/dsh.md
docs/known-issues.md
docs/local-config.md
docs/model-catalog.md
docs/openspec.md
docs/operations.md
docs/pi-agent-state.md
docs/pi-checkpoints.md
docs/pi-codex-admission.md
docs/pi-diagnostics.md
docs/pi-dirty-repo-guard.md
docs/pi-mcp.md
docs/pi-migration.md
docs/pi-readseek.md
docs/pi-review.md
docs/pi-web.md
docs/pi.md
docs/release-verification.md
docs/releases.md
docs/roadmap.md
docs/testing.md
examples/local.example.toml
examples/multi-profile.example.toml
examples/pi-managed.toml
examples/pi-services.toml
examples/pi-workstation.toml
examples/private-gateway.example.toml
profiles/pi-codex.toml
profiles/pi-cursor.toml
profiles/pi-default.toml
profiles/pi-managed.toml
schemas/omp-native.schema.json
schemas/pi-lock.schema.json
scripts/build-pi-vendor.py
scripts/fetch-pi-assets.py
scripts/model-delegate-batch.py
scripts/model-delegate.py
scripts/omp-history-scenarios.py
scripts/pi-checkpoint.py
scripts/pi-control.py
scripts/pi-delegate-codex.py
scripts/pi-delegate-mcp.py
scripts/pi-file-operation.py
scripts/pi-native-recovery.py
scripts/pi-native-scenario.py
scripts/pi-project-check
scripts/pi-readseek.py
scripts/pi-supervisor.py
scripts/pi-web-cli.py
scripts/rebuild-omp-test-corpus.py
scripts/register-pi-evidence.py
scripts/smoke-dsh-auth-panel.py
scripts/smoke-dsh-auto-review-ui.py
scripts/smoke-dsh-auto-review.py
scripts/smoke-dsh-codex-auth.py
scripts/smoke-dsh-codex-browser.py
scripts/smoke-dsh-codex-device.py
scripts/smoke-dsh-concurrency.py
scripts/smoke-dsh-environment.py
scripts/smoke-dsh-formal-review.py
scripts/smoke-dsh-tf.py
scripts/smoke-dsh-ui.py
scripts/smoke-dsh.mjs
scripts/smoke-dsh.py
scripts/smoke-pi-concurrency.py
scripts/smoke-pi-public-api.mjs
scripts/test-pi-mock.mjs
scripts/update-pi-subagents-patch.py
scripts/verify-pi.py
```

### 公共Python接缝（不可按文本命中删除）（16项）

```text
src/agentcfg/cli.py
src/agentcfg/commands.py
src/agentcfg/config.py
src/agentcfg/dsh.py
src/agentcfg/model_defaults.py
src/agentcfg/model_keys.py
src/agentcfg/model_status.py
src/agentcfg/model_urls.py
src/agentcfg/model_wizard.py
src/agentcfg/native_projection.py
src/agentcfg/omp.py
src/agentcfg/omp_discovery.py
src/agentcfg/presentation.py
src/agentcfg/schema.py
src/agentcfg/usage.py
src/agentcfg/workspace.py
```

### 旧规格历史文件（21项）

```text
specs/001-unify-pi-capabilities/checklists/requirements.md
specs/001-unify-pi-capabilities/codex-config-admission.md
specs/001-unify-pi-capabilities/codex-execution-reassessment.md
specs/001-unify-pi-capabilities/contracts/capability-matrix.md
specs/001-unify-pi-capabilities/contracts/cli-and-configuration.md
specs/001-unify-pi-capabilities/contracts/evidence-and-release.md
specs/001-unify-pi-capabilities/contracts/managed-execution.md
specs/001-unify-pi-capabilities/contracts/model-delegation.md
specs/001-unify-pi-capabilities/contracts/permission-policy.md
specs/001-unify-pi-capabilities/contracts/recovery-and-workspaces.md
specs/001-unify-pi-capabilities/contracts/runtime-and-dependencies.md
specs/001-unify-pi-capabilities/data-model.md
specs/001-unify-pi-capabilities/implementation-progress.md
specs/001-unify-pi-capabilities/plan.md
specs/001-unify-pi-capabilities/quickstart.md
specs/001-unify-pi-capabilities/research.md
specs/001-unify-pi-capabilities/scope-change-20260924.md
specs/001-unify-pi-capabilities/source-inventory.md
specs/001-unify-pi-capabilities/spec.md
specs/001-unify-pi-capabilities/tasks.md
specs/001-unify-pi-capabilities/validation-matrix.md
```

## 8. 本轮证据与任务状态

已完成：公开源码/注册/来源目录/状态字段初始盘点。进行中：实际消费者解除、替换和删除尚未开始。
失败待决策：U1–U4须在后续批次闭合，不是删除批准或宪章豁免请求。
环境不足未验证：未观察环境缺失；隔离、原生、账号检查均not_run，本包禁止执行。

实际只读调查：`rg --files`、`rg -n/-l`、Python 3.11 `-B` AST/TOML及路径枚举、
`git rev-parse --short HEAD`、`git branch --show-current`。只输出公开相对路径/符号/数量，
不读取真实认证/session。AST列表不声称完整动态调用图；具体文档核查命令和退出码另交主代理记录。

## 8. 实施收口（2026-10-19）

以上第1–7节是删除前的历史盘点，表中旧消费者/“尚未”描述保留其当时含义。
当前处置以本节和[逐路径执行记录](retirement-execution.md)为准，不能将旧消费者当作仍然存在。

| 初始组 | 实际处置 / 验证 |
| --- | --- |
| 公共配置/模型/render/deployment/lifecycle/秘密/依赖管理 | 保留并共用；Pi专属角色补全移除，中性准入共享；DSH/OMP受影响回归通过 |
| 新Pi adapter、官方npm backend、收据/薄生命周期、metadata inventory | rebuild已完成；五活动Pi模块及PiAdapter保留，无旧SDK/task/委托回退 |
| 91旧Python模块及26专属脚本 | 精确remove；生产静态及literal动态导入0，无有效CLI/构建/发现消费者 |
| Task Keeper/AgentManager/model-delegate、旧permissions/MCP/web/ReadSeek/补丁等资源 | 精确remove，30目录边界及71显式文件见执行清单；不另改名分发平台 |
| 四旧profile/锁/vendor/旧示例 | 退出；旧ID明确不支持，Base/Pro新锁独立；pi-services示例重建为合法Base未选模块 |
| 102旧专属测试/旧fixtures | 删除旧平台假设；capture/core/recovery/boundaries保留，合成新保护接续；全collection exit0 |
| 法律/上游署名/必要来源说明 | 保留build/licenses、migration STARTER-LICENSE/source-baseline，新增官方固定许可正文；无可执行旧平台归档 |
| 用户home/auth/session/trust/history/任务库/旧运行包/Git所有权 | 原位保留；archive指人工处置边界，不读取正文、不删除、不claim空闲；unknown仍阻断 |
| 旧指南/验收与临时研究 | 历史指南标明原范围；正式入口迁到新Pi指南；临时材料承接/删除及链接检查见T090，不外推旧通过 |

T048同一新Pi锁和两recipe在旧链缺席后仍有效，两个干净路径显式准备/部署通过，
受影响900例回归通过，公开来源没有未决消费者。真实状态归属未核实是刻意保留的阻断，
不是待删除源码的unresolved消费者；不提供清除owner或自动停止的旁路。
T049关闭的是仓库处置与消费者门，不关闭Base原生/账号、状态栏、Pro、模块或完整feature门。
