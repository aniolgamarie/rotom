# Pi 只读迁移盘点

当前已实现盘点、提案和 Pi 配置/依赖管线，公共 CLI 已登记 Pi 及四个配方。
四配方真实锁、Task Keeper 与 model-delegate 改造已进入仓库；完整冷重建、最终候选和真实账号验收仍在实施。
隔离验证范围见 [Pi 管线记录](acceptance/pi-pipeline-mock.md)。

## 使用

先准备一份可通过现有管理器校验的机器文件。迁移预览的目标 profile 可以指定 Pi 配方，
此预览不要求安装 Pi 或执行原生宿主：

```sh
./agentcfg --machine workstation --profile pi-default plan --from-pi-home /absolute/old/pi-home --from-starter /absolute/starter
```

`--from-starter`可省略，不能单独使用。该命令在有效机器配置的私人缓存中保存`inventory.json`，
输出条目数、待处理项数、提案位置及`ready_to_deploy=false`。
退出0只表示盘点完成，不代表迁移或认证通过。

## 如何解读

- `source_state`与`source_matches_baseline`：声明源是否存在，已观察正文是否与冻结Git对象相同。
- `selected`：显式包/主题选择。不能从配置确定的自动发现资源使用null，不推定未选择或已加载。
- `disk_state`：当前目录中的资源是否存在；不因此判断实际加载或功能可用。
- `load_evidence`/`execution_evidence`：本命令不执行宿主，两者保持not-run。
- `disposition`：keep/adapt/merge/replace/optional/exclude，附目标和理由。
- `blockers`：源漂移、旧管理者、未知包引用、包过滤器、未支持模型字段、重复模型与待填凭据等。
- `private_locations`：只在私人提案中保存原始定位；不要将整份文件公开。

基本provider/model只投影框架可表达的字段；apiKey字面值及命令不会复制或执行，
提案只给出需要另行填写的secret引用。不能表达的字段明确列为待映射，不静默转换成默认值。
支持的主题选择可生成Pi非秘密覆盖。提案不是完整本地文件或可直接部署的原生JSON。

## 原环境边界

盘点不读取auth/trust/会话正文，不启动Pi/DSH/Codex，不调用网络，不运行旧生成器，
不修改旧home或starter，不复制运行缓存。未知用户资源列为unmanaged-preserved，不自动删除或接管。
符号链接、不安全目标或格式无效会明确失败。原模型/服务信息只出现在私人非秘密提案中。

七个旧Codex角色的用途映射记录在`agents/pi/migration/role-map.json`，目标为model_delegate的七种preset。
旧codex-delegate/codex-agents属于替换来源，不能成为最终执行依赖。

## 采用新实例与停止旧同步目标

1. 保留盘点生成的私人提案，逐项查看 blockers 和 private_locations。
   `.starter-sync-manifest.json` 只标为旧管理者提示；不会继承其所有权或执行旧 Lua 同步器。
2. 将需要的 provider/model、主题与资源选择整理到 agentcfg 的私人 `local.toml`。
   领域技能和派生包使用仓库内唯一来源；未知定制文件先保留在旧目录，显式登记后才能选用。
   不把 auth.json、trust、session、任务库或完整 models.json 复制进公共来源。
3. 为 Pi 选择新的隔离实例根。新实例目录不能指向旧 Pi home；首次遇到已有原生文件会报告所有权冲突。
   在 starter/编辑器的旧同步设置中停止以新实例为目标。旧环境与旧目录保留，切换不自动删除它们。
4. 执行 validate → plan → apply；依赖需要显式 lock/sync。真实源、锁、平台认证尚未齐备时不得将源码检查当作可部署结论。
   apply 不执行模型，也不会复制登录状态；原生登录在最终运行实例中单独完成。

## 漂移、秘密轮换和回滚

- 原生 UI 只改动一侧时，apply 保留漂移，并继续沿用旧基线；双方改动同一受管字段返回 4。
- `capture` 只提取已选主题和可唯一反解的主模型，写入私人 `proposals/capture.json`。
  提案会重新走完整配置/渲染校验，不自动改机器文件。未知模型、重复映射不自动新增条目。
- 修改私人 secrets 后，账号值仍通过运行环境注入。原生 models.json 的受管 apiKey 只能是声明的 `$AGENTCFG_PI_CREDENTIAL_*` 引用。
  原生写入字面秘密会阻止 plan/apply/capture；不要把字面值当作可捕获漂移。
- 多文件更新先写 pending；中途失败回到旧配置。无法证明安全恢复时保留 pending 并返回 4。
  current/previous/pending 中的非法凭据或缺失保护声明均拒绝，不自动修补未知旧记录。
- 无变化 apply 的 changes=0，不轮换 previous。成功 rollback 消耗唯一 previous；保留 auth、会话、Task Keeper 数据库、运行时新增文件及用户 keybindings。
  回滚只恢复配置及保存的 runtime 引用，不降级软件包或迁移数据库。

## 活动阻塞与显式停止恢复

apply/sync/rollback 共用 Pi 实例准入。父 Pi 已退出、仍有 worker/check/Codex/external
或 unknown lease 时，变更仍返回 4；换 HOME/state_root 不能绕过实例归属或共享 worktree 写租约。

```sh
./agentcfg --local /private/local.toml --profile pi-managed recover pi --lease LEASE_ID
./agentcfg --local /private/local.toml --profile pi-managed recover pi --lease LEASE_ID --stop --expect-plan PLAN_DIGEST
```

第一步只核对并生成 300 秒内有效的停止计划；第二步是用户明确停止。
只有旧控制者已被证明失效、目标身份一致，才能撤销 generation 并停止其受控执行。
未知身份、复用 PID、尚存外部活动或过期计划保留保护。此操作不恢复旧任务执行权；
Task Keeper 的用户 resume 在核实终止后创建同 task 的 fresh attempt，继续使用原候选与预算。
