# 增加第二个 Agent

当前注册 DSH、Pi 和 OMP；各自的支持声明以对应证据为准，OMP见[支持状态](omp-support.md)。增加工具时复用配置合并、SecretStore、确定性产物、Tree、部署事务、上一版备份和活动锁。

## 适配接口

`src/agentcfg/adapter.py` 定义七个无副作用钩子和声明：

| 钩子 | 返回或职责 |
|---|---|
| declaration | 工具 ID、数据 schema 版本、adapter 版本 |
| validate | 选中配置的能力、引用及原生映射校验 |
| managed_targets | 文件/字段/初始化/运行时/包管理器所有权 |
| render | Artifact 字节；字段 Artifact 只编码期望字段，不带当前整文件 |
| render_with_context | 需要绝对锁定资源路径时消费显式RenderContext；默认委托render，不将运行目录混入公共配置 |
| dependency_plan | 明确依赖需求，不安装或隐式解析 |
| launch_spec | argv、cwd、环境字面值/SecretRef、lock identity |
| capture | 允许的原生投影转为合法本地覆盖提案 |
| doctor | 非秘密状态投影转为诊断说明 |

实际工具还提供 schemas（含已校验文档的 policy/authentication_claims）、capture_projection（安全读取 allowlist）、prepare_runtime（原生包拥有的启动准备）和可选 launch_preflight。参见 `src/agentcfg/dsh.py`；不要把 DSH 原生路径和字段塞回公共 registry。

`Adapter` 为 shared_files、launch_preflight、prepare_runtime 提供空默认实现，capture_configuration 默认委托 capture；需要依赖安装或捕获文件时，应实现 dependency_backend、capture_projection。launch_preflight 返回包含 argv 和 version 的检查项；当前 Node/npm 使用工具链兼容检查（Node 24 另要求至少 24.2.0），其他命令保留精确输出比较，失败时不回显原生输出。

OMP的RenderContext由公共锁推导锁身份和绝对运行目录；首次validate/render/plan不要求该包已经安装。其身份/lifecycle hook绑定物理实例与管理状态，运行时按物理实例→状态→运行包顺序持锁。来源与操作环境在spawn前复查，秘密只由实际需要的操作解析；login/usage/信息操作不要求普通会话的API/MCP秘密。

OMP原生秘密字段使用裸环境变量名，不能套用DSH/Pi的`$VAR`格式。`omp-env-name`守卫按adapter、路径和selector独立分类，并覆盖当前/基线/备份/pending/rollback；删除历史guard不能取消秘密分类。

## 接入步骤

1. 读取目标工具的固定版本文档/源码，记录配置、认证、profile、技能、规则、权限、环境变量和持久化路径。尤其核实真实 home 之外的写入，默认建立新的隔离实例。
2. 新建 `agents/<id>/agent.toml`、bindings/plugins 和有实际内容的模板；为其定义严格 schema。通用 provider/model 的稳定 ID 与原生路由分开，未知能力不编造。
3. 实现 adapter 类，加入 `workspace.ADAPTER_TYPES`。只有真实实现才加入 CLI 支持集合，未支持操作明确失败。
4. 实现 `backends.DependencyBackend`，由 adapter 的 `dependency_backend()` 返回。后端提供 read_lock、resolve_lock、sync、root、status、executable_paths、toolchain；命令和 run 已通过 `workspace.backend` 调用，不再假定 npm 目录。`dependencies.py` 和 `runtime_packages.py` 是 DSH 后端实现；非 npm 工具应实现自己的包收据和恢复。可选 `openspec_argv` 只在后端提供锁定 CLI 时实现，否则项目命令明确拒绝。
5. 全文件 TOML 等可作为 bytes 产物。需要字段管理的新格式时，通过 `deployment.register_codec` 提供安全 reader/writer；不能把未知格式当 YAML。未知字段保留，秘密/运行时数据不得进入投影或备份。
6. 使用自己的原生环境和启动准备钩子，不 source/eval 本地文件。用户已部署的 argv/凭据引用固定，密钥值在启动时才解析。
7. 复用契约与部署测试，再补原生无账号 smoke 和平台证据；账户调用仍需用户独立授权。

## 必须保留的边界

- 工具/profile 各有实例、状态、上一版备份和锁；更新 DSH 不影响其他工具。
- root manifest/字段基线与 previous 备份不同，不能通过更新 generation 偷偷接纳漂移。
- 整文件与字段所有权冲突、重叠 selector、未接管非空文件都必须失败。
- 命令实现负责执行，adapter 不得绕过 Tree/事务去覆盖用户文件。
- `shared_files` 是首次空实例部署时声明的未来原生共享文件范围，只允许后来新增的空字段，不接管已存在非空字段。
- 非秘密定位变量 AGENTCFG_REPOSITORY/LOCAL_FILE/PROFILE 可帮助维护 skill 找到来源；它们不是秘密 resolver，也不代表业务 cwd。
- 共享规则统一用户维护的文字，不统一内置提示、权限或工具能力。

测试适配器仅位于 tests 中；其通过表示公共流程可复用，不表示 Pi/Codex 已安装或可调用。

`test_non_npm_backend_drives_public_commands_and_launch` 使用不同目录布局的假后端，通过 validate/plan/lock/sync/apply/doctor/run/rollback，检查启动路径和 PATH 不包含 node_modules。增加第二个工具仍需实现自己的原生适配、CLI 支持声明及账号/平台验收，不需要改写上述公共命令的依赖逻辑。
