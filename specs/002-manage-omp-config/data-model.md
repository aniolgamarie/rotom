# OMP 数据模型

本文件定义待实现的数据关系，原生格式见 [能力契约](contracts/native-capabilities.md)，命令见 [CLI 契约](contracts/cli-and-configuration.md)。继续使用现有 TOML 公共源和 JSON 部署状态，不引入数据库。

## 配方与原生身份

| 实体 | 字段 | 约束与关系 |
|---|---|---|
| OmpProfile | 既有 schema_version/id/agent、providers/models/rules/skills/plugins/mcp/roles、agent_options | agent=omp；公共 ID 保持现有严格校验；未知字段失败；对象合并、数组替换、false/空数组不丢失 |
| NativeIdentity | profile_id、完整 profile_sha256、native_name、instance_realpath、home、agent_dir、四个 XDG 根、layout_version | native_name=`rotom-`+完整哈希前24hex；完整 ID/hash 一起比较，碰撞失败；不允许用户覆盖 native_name |
| InstanceOwnership | identity、machine_id、local_path、state_realpath、owner_nonce、schema_version | `<instance>/.agentcfg-omp-owner.json`；绑定物理实例和管理状态；第二 state_root 或配方不得接管同一目录 |
| RuntimeBinding | identity_digest、deployed_runtime_digest、完整 argv/env 引用、source_policy、package_receipt_digest | 纳入既有 runtime record；validate/plan/apply/doctor/run/capture/rollback/managed usage 使用同一绑定 |

`instance`、state、cache 按既有 workspace 的 agent/profile 层级分配。HOME 固定 `<instance>/user-home`；原生目录固定为其 `.omp/profiles/<native_name>/agent`。XDG 基目录均在此 HOME 下，但不创建会触发原生切换的 `XDG_*/omp/profiles/<native_name>`。OMP 的 profile-independent 服务与 installation ID 因 HOME 不同而分离。

只在首次 apply 创建新身份。非空且无同一 owner 的实例、越界链接、身份或目录布局变化是冲突；不提供覆盖接管。改名生成新身份，旧身份保留并报告需要显式迁移，本版不迁移账号/会话。运行时原生生成的 auth/session/cache 不进入所有权快照。

## 配置、资源和秘密引用

| 实体 | 字段 | 验证 |
|---|---|---|
| Provider/Model | 复用 registry 中 protocol/auth_kind/base_url/credential_ref、provider/remote_id/input/context_window/max_output_tokens | 支持组合和精确映射由能力契约限制；不添加任意 native 设置；禁止 URL 中的凭据 |
| OmpResource | id、kind(prompt/theme)、path、scope(global) | agents/omp/agent.toml resources catalog；路径为仓库内普通文件；主题使用固定 schema |
| PluginPackage | id、source、entrypoints、tree_digest、license、compatibility | agents/omp/plugins.toml；首个本地无外部依赖的 OMP 扩展；入口位于锁定包内，不在 render 时导入 |
| McpBinding | registry 服务引用、environment_refs、锁定 command 身份 | stdio/http；args 字面传递；禁止隐式下载程序与执行式 secret |
| SecretBinding | ref_id、generated_env_name、target_path、selector、operation_set | 仅存引用；env 名使用完整 ID 哈希的前24hex 并检测碰撞；值只在实际需要的启动操作解析 |
| ManagedIntent | 相对 path、ownership_kind、codec、selector、非秘密 content、reference_guard | 复用 Artifact/ManagedTarget；字段 selector 不重叠；秘密叶子必须有强制守卫 |

OMP 原生 auth DB、trust、会话、日志、usage 缓存均是运行数据，既不导入也不备份到 rotom 配置状态。SecretStore 的既有私人 TOML 存储问题不在本次修复范围；新适配器不增加值的读取/输出面。

### 引用守卫

现有 `$VAR` 引用守卫保留兼容。增加版本化 `omp-env-name` 守卫，只接受部署契约明确登记的 `AGENTCFG_OMP_*` 整值变量名，不能将任意普通字符串都认作引用。模型 apiKey、MCP env/认证 header 使用字段叶子意图。

独立的 adapter/path/selector 分类器判定 OMP 凭据叶子必须有守卫；验证覆盖当前意图、已存基线、backup、pending 与 rollback。删除/伪造状态里的 guard 不能绕过分类器。原生把引用改成 secret 字面值时只报告“敏感字段漂移”，不把旧值加入异常、diff、备份或 capture。DSH/Pi 的现有分类与状态兼容路径不改变。

## 来源策略与迁入提案

SourcePolicy 保存固定版本发现清单摘要、project_resources 布尔值、project_roots 规范绝对路径，以及允许的非秘密项目 skills/MCP 类型。启用时根必须显式列出且与 cwd/祖先发现路径匹配；默认空列表。记录路径及摘要，不存 .env/auth 内容。每次进程创建前复核实际来源，不能凭上次检查跳过。

InventoryProposal 保存 source_root、source_identity（可读非秘密元数据）、每项 kind/path/disposition/reason/target、非秘密 override 和候选包摘要。disposition 取纳入/原生保留/替代/排除，另有 review_required 状态。来源只读；私人 cache 权限 0700、文件0600；不自动合并仓库，不复制运行数据。任意文本/脚本含秘密的判定不是可完全自动化的问题，扫描不能取代用户对候选资源的审阅。

## 依赖与运行状态

OmpLock 保存 schema/adapter version、OMP tag/commit、平台 asset URL/SHA256、上游依赖锁与许可证摘要、资源和插件树摘要、入口、外部解释器要求。RuntimeReceipt 保存实际平台、每个产物摘要、精确解释器身份、安装路径和 lock 摘要；无 secret。包激活只在所有项验证通过后发生。

| 转换 | 前提与效果 | 失败后状态 |
|---|---|---|
| 未准备 → synced | 显式 sync 暂存、验证、原子激活运行包 | 上一包仍有效；临时目录可诊断清理 |
| 未归属 → applied | 显式 apply 先检查独占新目标，创建 owner、pending、受管配置、基线 | 沿既有恢复事务；owner/pending 必须可识别，不自动接管 |
| applied → applied | 三方比较后更新；完全无变化时不写入、不轮换备份 | 冲突阻止写入；保留基线/原生数据 |
| applied → running | runtime gate + instance lease，持锁运行 | 子进程退出释放运行锁；不撤销已部署配置 |
| applied → captured | allowlist 非秘密差异成为私人提案 | 不修改公共源及运行数据 |
| applied → rolled back | 验证 backup/守卫后恢复上一配置并消费备份 | 中断保留 pending；不恢复/删除 auth/session |
| 任意 → recovery-required | 发现 pending/身份不一致 | run、usage、plan 失败4；pending 由下一次显式 apply/rollback 在持锁校验后恢复，身份冲突仍阻止写入 |

sync 改变已激活包后，旧 deployment 的 runtime digest 不再匹配时必须重新 plan/apply，run 不自动跟随新包。rollback 只恢复配置；若所需旧包不可用，后续 run 退出5，不能用不同依赖执行旧配置或隐式降级软件。
