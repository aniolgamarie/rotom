# Quickstart：官方 OMP 与独立权限插件

当前按[独立插件修订](standalone-plugin.md)迁移，不修改 OMP 上游源码。本指南描述新方案，实际通过与未验证范围以[验收记录](../../docs/acceptance/omp-permission-control.md)为准；旧补丁构建、资产与启用命令保存在[历史指南](historical-patched-quickstart.md)，不继续使用。

## 1. 工具与配置

`omp-kernel` 选择官方未改动 OMP 与本地 `omp-permission-control` 插件。插件注册独立 `permission_bash`，在自己的执行函数中先完成审查或人工确认，再调用公开执行 API。原生 Bash 保持 prompt。模型通过工具说明选择受管工具；插件缺失或失败时不能让原生 Bash 自动放行。

审批配置位于受管原生 profile 的 `permission-control.json`；官方 `config.yml` 不含 `permissionControl`、`disabledModelProviders` 等专用补丁字段。手工修改 sidecar 会由正常漂移/冲突与启动前完整性检查处理，不把原生账号文件纳入管理。

## 2. 模型顺序

显式 `reviewer_model` 优先；省略时绑定当前会话执行模型。显式 `remote_fallback_model` 只在主审不可用、transport 不支持、超时、服务失败或响应无效时接替一次完整审查。有效 allow/ask/deny 终止，不以备用复审用户或模型拒绝。同一实际 provider/model 去重；引用错误在配置期失败。

主动指定 GLM 主审、Kimi 远程备用的私人覆盖示例：

```toml
[overrides.profiles.omp-kernel.agent_options.permission_control]
reviewer_model = "omp-zhipu_tf-glm-5.3-flash"
remote_fallback_model = "omp-kimi_tf-kimi-for-coding"
fallback_model = "local/lfm2.5-230m"
```

原版没有公开的 installed-only tiny 推理 API，本地 fallback 暂时显示 unavailable，插件不调用内部 worker、不下载模型。两条远程路径都失败时人工或无 UI 阻止。标题 tiny 角色与权限 fallback 相互独立。

## 3. 会话命令

```text
/permission-control status
/permission-control smart
/permission-control manual
/permission-control explain
```

命令只作用于当前会话，不写回配方；新建或恢复会话按默认模式初始化。status/explain 不发送模型请求或刷新认证，不输出原始命令、对话、凭据或自由文本模型解释。

## 4. 执行范围

模型审查完整命令与真实用户上下文。普通 `ls -la` 进入主审，不再因旧读取证明只支持部分选项而直接人工。明确配置的 deny/prompt 是模型不能放宽的边界；无法可靠识别这些边界、缺上下文、取消或决定无效时保持询问/阻止。

独立工具执行非交互 Bash，不加载 profile/rc。不继承原生 service/job/PTY、direnv、interceptor 或 worktree 改写，也不接管所有 eval/MCP/子代理操作。这是应用层审批，不是 OS 沙箱，无法消除文件系统外部竞态。

## 5. 验证与日常迁移

默认测试使用临时 HOME、假 UI/provider/exec 和网络阻断；不启动宿主、不执行危险样本或调用付费模型。重点检查独立工具故障关闭、模型选择、主审故障接替、有效拒绝不复审、明确规则、取消、无 UI 以及 sidecar/旧字段迁移。

日常本机仍需在退出活动 OMP 后，用同一 local/profile 检查并启用：

```sh
./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel sync
./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel plan
./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel apply
./agentcfg --local /home/weixiaoxian.wxx/.config/agentcfg/machines/workstation.toml --profile omp-kernel run
```

这是启用步骤，不是本轮已经执行日常部署的证明。管理器不得自动终止活动实例；旧账号、会话、凭据和恢复边界必须保留。

新实现不能沿用旧 patched runtime 的宿主或模型质量结果。真实 Cursor OAuth、新审批模型质量及其它平台无新证据时保持未验证，历史 102/102 模型请求账本不变。

## 6. Cursor 动态模型的默认角色

原生 UI 改动受管默认模型后，保留漂移仍会被启动资源守卫阻止。动态Cursor模型可通过显式私人意图持久化，不把OAuth传输伪装成API-key模型。需要声明并在profile的现有providers列表中追加cursor；以下providers数组示例基于公共kernel默认列表，私人已有其它provider时必须一并保留。

```toml
[overrides.providers.cursor]
protocol = "oauth-dynamic"
auth_kind = "oauth"

[overrides.profiles.omp-kernel]
providers = ["kimi_tf", "zhipu_tf", "cursor"]

[overrides.profiles.omp-kernel.agent_options.native_model_roles]
main = "cursor/kimi-k3-high:high"
```

绑定只影响相应执行角色，不改变reviewer_model和remote_fallback_model的优先级；不自动登录或发现账号模型。本机已按2026-09-30后续授权完成上述窄配置与部署，默认Cursor选择保留，最终doctor为offline-ready、无漂移/冲突，完整启动准入通过；见验收Phase13。前文sync/plan/apply仍适用于其它机器或下一次更新，不是要求本机重复迁移。
