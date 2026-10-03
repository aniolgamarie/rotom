# 独立插件修订：官方 OMP 与公开扩展接口

2026-09-30，维护者要求移除宿主补丁并把权限管控改为独立本地插件，同时确立所有 agent 上游源码不修改的项目原则。本修订是当前实现与验收依据；此前 spec/plan 中的 bridge、patched standalone、read-proof、installed-only host tiny 和一次性宿主许可要求属于历史架构，不能继续作为当前交付要求。

## 当前需求

- FR-040：使用未修改的官方 OMP 运行包。插件只使用公开扩展 API，禁止宿主源码补丁、同名原生工具替换、私有模块或运行时 monkey patch。
- FR-041：注册独立工具 `permission_bash`。工具的执行函数在模型/人工决定完成后调用公开 `omp.exec`，每次请求最多发起一次实际 Bash 执行；插件缺失或执行函数异常不能把原生 Bash 改成默认允许。原生 `bash` 保持人工保护。
- FR-042：模型审查完整命令、cwd 和真实用户消息，承担语义风险与授权判断。普通 `ls -la` 不得因为旧读取证明不支持隐藏项或长格式而直接人工。可完整解析的简单与复合命令都审查完整操作；无法可靠核对明确禁止/必须人工规则时保守询问，不按只读命令名允许表冒充智能。
- FR-043：明确配置的 deny/prompt 规则仍是模型不可覆盖的边界，从同一 profile 的 `runtime.bash.patterns` 派生，不维护第二套用户规则来源。无 UI、取消、超时、输出无效或缺少真实用户来源时不能获得默许。
- FR-044：主审优先显式 `reviewer_model`，省略时绑定当前执行模型。主审运行故障/不支持/无效输出才尝试一次显式远程备用；相同实际模型去重，有效 allow/ask/deny 终止链。引用错误在配置期失败。输出必须严格校验；allow 仅限低风险且授权充分。
- FR-045：保留本地 fallback 配置身份，但原版没有公开的 installed-only tiny 推理接口时显示 `unavailable`，不通过私有模块或隐式下载补齐。最终转人工或在无 UI 时阻止；不能声称本地模型实际可用。
- FR-046：保留四条 `/permission-control smart|manual|status|explain` 命令。模式只影响当前会话，新建/恢复重置。status/explain 无推理、认证刷新和下载副作用；显示独立工具覆盖范围及真实来源。模式切换/取消后在途批准不得继续执行。
- FR-047：配置放在受管 `permission-control.json`，不向官方 `config.yml` 注入专用宿主字段。整文件所有权、封闭 schema、普通文件/符号链接边界、plugin tree digest 和 policy digest 均验证；部署通过正常三方比较移除旧受管字段，不改账号、会话或凭据。
- FR-048：Cursor 模型发现只使用官方配置与公开接口。启用模型不得放宽私人 HOME 或外来项目资源来源限制；管理器前置检查必须拒绝不受管 Cursor 项目资源。真实 OAuth 发现和模型质量无新证据时保留未验证。
- FR-049：新插件当前执行非交互 `bash --noprofile --norc -c`，不声称继承原生 service/job/PTY、direnv、interceptor、worktree 重写及后台管理语义。不提供 OS 沙箱、不消除外部竞态，也不宣称接管 eval/MCP/所有子代理。

## 接口与交付

`getAgentDir()/permission-control.json` 为封闭 JSON：

```json
{
  "schemaVersion": 2,
  "defaultMode": "smart",
  "reviewer": "session",
  "remoteFallback": {"provider": "zhipu_tf", "model": "glm-5.3-flash"},
  "fallback": {"provider": "local", "model": "lfm2.5-230m", "installedOnly": true},
  "pluginId": "omp-permission-control",
  "pluginDigest": "<verified-tree-sha256>",
  "policyVersion": "<generated-policy-sha256>",
  "nativePatterns": []
}
```

摘要占位仅说明字段，不能作为生产配置。`nativePatterns` 的每项只含 `match` 与 `approval`。插件入口为 `standalone.ts`，不调用历史 `registerPermissionController`。工具外层仅 `permission_bash` 配置允许，审批责任在其真实执行函数内；原生 Bash 保持 prompt，插件未注册时原生保护仍在。

## 计划与验证

1. 工程约定、宪章和架构记录“不修改 agent 上游”及历史偏离。
2. 独立插件与模型链用 fake UI/provider/exec 测试；重点验证 `ls -la`、模型优先级、故障接替、有效拒绝不复审、取消、无 UI 和明确禁止规则。
3. 管理器切换官方运行包、sidecar、工具配置与资源守卫；隔离验证旧字段迁移与账号/配置所有权保护。
4. 稳定插件字节后刷新普通官方依赖锁；不构建或刷新补丁 standalone。历史 patched receipt/模型原始结果保持原身份，不作为新插件通过证据。
5. 默认回归不启动宿主、不联网或调用付费模型。独立真实宿主步骤只在已有明确授权范围内使用临时 HOME 和固定本地 provider；日常部署需单独核对活动实例和迁移 plan。

## 当前状态

| 状态 | 项目 |
|---|---|
| 完成 | T088—T092：基本原则、公开 API、独立工具、sidecar/官方运行包、锁与限定验收 |
| 进行中 | 无当前实现任务；本机日常迁移已按后续授权完成 |
| 失败待决策 | 无 |
| 环境不足未验证 | 本轮尚未出现环境阻塞；真实 Cursor、模型质量及其它平台未执行 |

本机已按后续明确授权切换为官方运行包与独立插件，具体部署证据见验收 Phase 13。原则不授权自动终止会话、访问账号库或新增付费模型请求。

实际结果与未验证范围见[Phase 12 验收](../../docs/acceptance/omp-permission-control.md#phase-12官方-omp-与独立插件2026-09-30当前交付)。

## 本机启用补充：Cursor 原生角色的明确意图

- FR-050：用户在官方 UI 选择的 Cursor 动态模型可通过显式 `agent_options.native_model_roles` 持久化为本机非秘密意图；当前仅支持官方启用的 `cursor/model[:thinking]`。按公开角色键渲染原有 `modelRoles` 字段，优先于该角色的静态公共模型映射。未知角色、无效标识、思考级别或未启用的 Cursor 必须失败。不得伪造 Cursor API-key/static model、绕过原生登录、删除启动资源守卫或直接修改部署基线。主审显式配置及远程备用策略独立。

本机迁移原生默认选择时采用窄字段编辑与正常三方比较；仅改变明确的私人角色意图，账号、秘密、其它覆盖保持不变。真实模型调用不属于本次启用检查。
