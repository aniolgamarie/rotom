# 增加第二个 Agent

首版仅注册 DSH。Pi、Codex CLI 是后续适配目标，没有空实现占位。增加工具时复用配置合并、SecretStore、确定性产物、Tree、部署事务、上一版备份和活动锁。

## 适配接口

`src/agentcfg/adapter.py` 定义七个无副作用钩子和声明：

| 钩子 | 返回或职责 |
|---|---|
| declaration | 工具 ID、数据 schema 版本、adapter 版本 |
| validate | 选中配置的能力、引用及原生映射校验 |
| managed_targets | 文件/字段/初始化/运行时/包管理器所有权 |
| render | Artifact 字节；字段 Artifact 只编码期望字段，不带当前整文件 |
| dependency_plan | 明确依赖需求，不安装或隐式解析 |
| launch_spec | argv、cwd、环境字面值/SecretRef、lock identity |
| capture | 允许的原生投影转为合法本地覆盖提案 |
| doctor | 非秘密状态投影转为诊断说明 |

实际工具还提供 schemas（含已校验文档的 policy/authentication_claims）、capture_projection（安全读取 allowlist）、prepare_runtime（原生包拥有的启动准备）和可选 launch_preflight。参见 `src/agentcfg/dsh.py`；不要把 DSH 原生路径和字段塞回公共 registry。

## 接入步骤

1. 读取目标工具的固定版本文档/源码，记录配置、认证、profile、技能、规则、权限、环境变量和持久化路径。尤其核实真实 home 之外的写入，默认建立新的隔离实例。
2. 新建 `agents/<id>/agent.toml`、bindings/plugins 和有实际内容的模板；为其定义严格 schema。通用 provider/model 的稳定 ID 与原生路由分开，未知能力不编造。
3. 实现 adapter 类，加入 `workspace.ADAPTER_TYPES`。只有真实实现才加入 CLI 支持集合，未支持操作明确失败。
4. 实现该工具自己的完整依赖锁及安装后端。当前 `dependencies.py` 是 DSH 的 npm 锁消费实现；不要把非 npm 工具强行套入它。接入时在命令层选择对应后端，并保留相同的暂存、验证、失败不激活约束。
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
