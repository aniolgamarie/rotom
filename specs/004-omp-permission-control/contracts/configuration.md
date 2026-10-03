# Contract: Configuration and Managed Identity

> 本文保留宿主补丁方案的历史模型/契约。自2026-09-30起按不修改上游源码原则迁移，当前要求以[独立插件修订](../standalone-plugin.md)为准；不得继续依赖宿主bridge或私有接口。

本契约定义 rotom profile 输入、原生 `config.yml` 输出和 patched runtime 锁之间的封闭关系。引用 [data-model.md](../data-model.md) 和 [research.md](../research.md)。

## Profile 输入

启用功能时，profile 必须同时满足：

```toml
plugins = ["omp-permission-control"]

[agent_options]
runtime_variant = "permission-control-v1"

[agent_options.permission_control]
default_mode = "smart"
```

可选独立主审、远程 fallback 和本地 fallback：

```toml
plugins = ["omp-permission-control"]
models = ["omp-kimi_tf-kimi-for-coding", "omp-zhipu_tf-glm-5.3-flash"]

[agent_options]
runtime_variant = "permission-control-v1"

[agent_options.permission_control]
default_mode = "smart"
reviewer_model = "omp-kimi_tf-kimi-for-coding"
remote_fallback_model = "omp-zhipu_tf-glm-5.3-flash"
fallback_model = "local/lfm2.5-230m"
```

`permission_control` 是封闭对象：只允许必填 `default_mode` 和可选 `reviewer_model`、`remote_fallback_model`、`fallback_model`。`default_mode` 仅允许 `smart`、`manual`；`fallback_model` 仅允许 `local/lfm2.5-230m`。`reviewer_model` 与 `remote_fallback_model` 都是 rotom model ID，必须在同一 profile 的 `models` 中，并在渲染时解析为恰好一个 provider/model；无效、歧义或未选择均为配置错误，不回退到会话模型或其它fallback来掩盖引用错误。显式reviewer优先；远程fallback不随执行模型切换，也不取代主审。

`omp-kernel` 的规定值为：选择 `omp-permission-control`，`runtime_variant="permission-control-v1"`，`default_mode="smart"`，省略 `reviewer_model`，设置 `remote_fallback_model="omp-zhipu_tf-glm-5.3-flash"`，显式设置 `fallback_model="local/lfm2.5-230m"`。这与现有标题 tiny 配置相互独立。

## 三方一致性与原生保护前置条件

启用 smart 的 profile 必须满足以下全部条件，否则配置或启动检查失败：

- profile 的 `plugins` 选择 `omp-permission-control`；
- `agent_options.runtime_variant` 是 `permission-control-v1`；
- `permission_control` 存在且可生成 ABI 为 `permission-control/v1` 的原生对象；
- `runtime.tools.approval.bash="prompt"`，`approvalMode` 不得为 `yolo`；
- deny 与命令级 prompt 规则继续由原生审批解析，不得为插件删除或降级；
- `omp-kernel` 对原生 `task` 与 `eval` 显式设为 `prompt`。`eval` 只加入现有封闭 approval 工具白名单，不属于 smart 覆盖；
- 不支持的 child/headless 入口不能继承主会话 smart 许可或 YOLO；遇到原生 prompt 而无 UI 时阻止。

运行期间切换 YOLO、审批模式、Bash 规则或其它保护基线，会使 bridge 降级为人工/阻止并撤销未执行许可，不能扩大旧许可。

适配器不得为扩大 smart 覆盖而静默关闭或改写用户已有的 direnv/devenv、shell prefix、service/name/ready/env、async、PTY、ACP terminal、useUserShell、启动脚本或其它 Bash 执行配置。这些配置保持原生语义；若宿主不能在无副作用 prepare 阶段冻结其最终 command、环境效果和 backend 调用，相关请求标记为不在首版智能覆盖，转原生人工确认且计入固定样本的询问率，无 UI 时阻止。

## 原生 `config.yml` 对象

适配器新增字段所有权 `/permissionControl`，值为封闭对象。缺省 reviewer 使用字面量 `session`：

```yaml
permissionControl:
  schemaVersion: 1
  defaultMode: smart
  reviewer: session
  remoteFallback:
    provider: zhipu_tf
    model: glm-5.3-flash
  fallback:
    provider: local
    model: lfm2.5-230m
    installedOnly: true
  bridgeAbi: permission-control/v1
  pluginId: omp-permission-control
  pluginDigest: "1111111111111111111111111111111111111111111111111111111111111111"
  runtimeIdentity: "omp-v18.3.0-permission-control-v1-linux-x64-test"
  policyVersion: "2222222222222222222222222222222222222222222222222222222222222222"
```

显式 reviewer 被解析为原生 provider/model 对象：

```yaml
permissionControl:
  schemaVersion: 1
  defaultMode: smart
  reviewer:
    provider: zhipu_tf
    model: glm-5.3-flash
  bridgeAbi: permission-control/v1
  pluginId: omp-permission-control
  pluginDigest: "1111111111111111111111111111111111111111111111111111111111111111"
  runtimeIdentity: "omp-v18.3.0-permission-control-v1-linux-x64-test"
  policyVersion: "2222222222222222222222222222222222222222222222222222222222222222"
```

示例中的 digest 和 runtime identity 是明确的测试值，不是发布资产身份。`fallback` 省略表示 disabled，不能写 `null`、`false`、其它 local 模型或远程模型。`reviewer` 的 `session` 表示每次审查开始时冻结实际会话主模型；它不是固定模型名。显式 reviewer 对象只允许 `provider`、`model`。fallback 对象只允许示例中的三个字段和值。

`pluginDigest` 来自插件锁定 tree digest；`runtimeIdentity` 来自独立 patched manifest；`policyVersion` 对固定策略、相关 profile 意图和原生保护配置做规范化摘要。这三个字段生成且不可由 profile/local override 手填。适配器不接受 `permissionControl` 或任意 runtime 原生片段透传。

## 宿主设置 schema

宿主 v18.3.0 的 patched settings schema 必须显式声明 `/permissionControl`，并对对象及嵌套对象设置 `additionalProperties: false`。字段集合、必填性和 const/enum 必须与上节一致。未选择功能的 profile 不生成该对象，继续使用官方 runtime；选择功能却缺少对象、字段或身份则失败关闭。

原生发现/捕获把 `/permissionControl` 识别为 rotom 精确受管字段。捕获可还原 `default_mode`、显式 reviewer 和 fallback 意图；生成身份字段只用于校验，不能反向成为用户可编辑配置。

## 锁与 manifest

patched runtime 使用独立文件：

```text
locks/omp/permission-control/manifest.json
```

它锁定 OMP v18.3.0 上游 commit/archive、完整依赖锁、补丁有序摘要、构建脚本摘要、精确工具链、native 依赖、目标平台、输出资产摘要、runtime identity 和 `permission-control/v1` ABI。官方 `locks/omp/manifest.json` 及其资产来源语义保持不变。`sync` 只验证和消费已构建资产，不编译、不安装工具链，也不下载 tiny。

profile 未选择插件时不得生成 `/permissionControl`、不得要求 patched manifest、不得加载插件，也不得改变原生权限配置。

## 失败契约

下列情况为配置或锁校验错误（退出码 2）：未知字段或枚举、reviewer model 未选择/歧义、fallback 值不精确、对象/plugin/variant 不一致、Bash approval 不是 prompt、approvalMode 为 yolo，以及 patched manifest 损坏、结构无效或不符合严格 schema。

受管字段已由 rotom 拥有却与非受管写入冲突，属于所有权冲突（退出码 4），不得覆盖或静默合并。

结构有效的锁缺少目标平台资产，或实际资产/插件摘要、runtime identity、bridge ABI 与运行宿主不兼容，属于依赖/原生检查失败（退出码 5）；插件未加载或 bridge 不健康同样退出 5。已经运行的会话同时撤销旧许可并保留原生保护。

所有错误只能包含字段路径、固定原因码和非秘密身份摘要；不得回显凭据、原始命令、完整环境或 provider 响应。

## 独立模型provider禁用设置

patched profile生成精确受管`/disabledModelProviders`，模型manager、registry可用模型和model hub使用该模型专用列表；未配置该字段时沿用上游disabledProviders旧行为。资源来源仍使用原disabledProviders，保留Cursor项目及用户配置加载禁用。enabledProviders=[]仅约束foreign用户目录，不替代资源denylist。官方profile不生成新字段。

`permissionControl.remoteFallback` 可省略；存在时恰有provider/model两个字段，来自严格remote_fallback_model引用。省略远程配置保留旧协议行为；远程与主审实际身份相同则跳过该层，不重复付费推理。
