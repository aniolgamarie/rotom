# 需求与验收映射

实现要求的编号来自 OpenSpec；测试总结果见 acceptance.md。一个文件可覆盖多个场景，账号及平台证据单独记录，不能从文件存在推断通过。

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
| SKILL-01 — A complete maintenance skill is delivered and discoverable | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/配置流程/原生发现已检查；独立 Agent 行为未评估 |
| SKILL-02 — Local configuration authoring follows the actual schema | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/配置流程/原生发现已检查；独立 Agent 行为未评估 |
| SKILL-03 — Local edits preserve unrelated private content | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/配置流程/原生发现已检查；独立 Agent 行为未评估 |
| SKILL-04 — Maintenance follows source and version boundaries | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/配置流程/原生发现已检查；独立 Agent 行为未评估 |
| SKILL-05 — Generation and deployment follow user authorization | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/配置流程/原生发现已检查；独立 Agent 行为未评估 |
| SKILL-06 — Skill validation checks realistic behavior and outcomes | Skill Creator 结构校验；test_config_examples.py、test_dsh_pipeline.py、test_runtime.py | 结构/配置流程/原生发现已检查；独立 Agent 行为未评估 |
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
