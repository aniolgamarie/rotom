# Contract: Session Commands

> 本文保留宿主补丁方案的历史模型/契约。自2026-09-30起按不修改上游源码原则迁移，当前要求以[独立插件修订](../standalone-plugin.md)为准；不得继续依赖宿主bridge或私有接口。

插件提供且只提供以下四个完整命令：

```text
/permission-control smart
/permission-control manual
/permission-control status
/permission-control explain
```

命令名、子命令均大小写敏感；不提供 `guard`、`approval`、别名、缩写或无参数交互菜单。任意额外参数、缺少子命令和未知子命令都不改变状态，返回固定用法列表（只列以上四条）。命令本身不执行被审查 Bash，也不绕过原生审批。

存在受管 `/permissionControl` 时，patched 宿主保留同一命令入口：扩展健康注册时调用插件 handlers；插件 missing/unhealthy 时 minimal shim 仍允许 `status`/`explain` 报告 unavailable 或当前会话无决定，`smart` 不生效，`manual` 仍可收紧为原生人工保护。未选择本功能、因而没有 `/permissionControl` 的 profile 不提供这些命令。

## `smart`

仅切换当前主会话的 `active_mode` 为 smart。命令通过独立于 Bash 串行队列的控制路径，先原子递增 session generation、撤销未执行许可并向在途审查发出 abort，再更新模式和重新核对插件/runtime/ABI 身份、bridge 健康、原生保护基线及 reviewer 可解析性；它不得等待最长 30 秒的 Bash 判定释放串行锁。后续动作按新 generation 重新判定。

若配置、身份或 bridge 不健康，命令不得声称 smart 生效：会话保持或进入保守状态，需人工的操作交给原生 UI，无 UI 时阻止。本地fallback不可用不阻止smart。主审不可用而远程fallback已准备时，smart仍可使用该显式链；两远程审查路径均不可用时如实显示，tiny不能替代完整主审或用户。

响应包含：`mode=smart`、`source=session-command`、新 generation、保护健康摘要。不得包含 token、endpoint 凭据或模型请求内容。

## `manual`

仅切换当前会话的 `active_mode` 为 manual。命令经独立控制路径先原子递增 generation、撤销未执行许可并向在途审查发出 abort，再更新模式，不等待 Bash 串行锁。manual 不调用主审、远程fallback或 tiny；在插件/bridge/保护基线健康、属于覆盖范围且信息完整时，明确安全的原生或确定性低风险操作仍可执行，其余进入原生人工确认，无 UI 时阻止。hard deny、command prompt 和 critical safety 保持不变。

响应包含：`mode=manual`、`source=session-command`、新 generation、`reviewer=not-called-in-manual`。新建或恢复会话不会继承这次临时切换，而是重新读取 profile 的 `defaultMode`。

重复设置当前模式仍视为保护边界重确认：递增 generation 并使旧许可失效，避免调用者用旧许可跨越命令时点。

## `status`

只读，一次响应给出以下固定项目：

| 项目 | 允许值/表现 |
|---|---|
| `configuredMode` | profile 的 `smart \| manual` |
| `activeMode` / `modeSource` | 当前模式及 `profile-default \| session-command` |
| `reviewer` | 实际显式 provider/model，或 session reviewer 当前将解析的主模型；不可解析则 `unavailable` |
| `reviewerSource` | `explicit-profile \| session-default \| unavailable` |
| `remoteFallback` / `remoteFallbackHealth` | 显式配置的远程provider/model及其被动健康，或disabled；独立于reviewer选择，查询无模型或认证刷新副作用 |
| `fallback` | `disabled` 或 `local/lfm2.5-230m` |
| `fallbackLimit` | 固定为 `ask-or-deny-only; installed-only; never-allow` |
| `fallbackHealth` | `disabled \| ready \| unavailable \| unhealthy`；查询不得触发下载 |
| `coverage` | 候选范围为 `tool=bash, session=main, shell=bash, platform=linux, backend=native, execution=foreground`；同时列出当前配置与请求实际可覆盖/转人工原因，不把全部 Linux Bash 标为 smart |
| `executionLimits` | 显示 service/async/PTY、ACP terminal、direnv/devenv、prefix、useUserShell/启动脚本、环境注入及 worktree rewrite 等限制的当前状态 |
| `nativeProtection` | Bash prompt、deny/command prompt 保留情况，以及 task/eval prompt 状态 |
| `childAndHeadless` | `native-prompt-or-block; no-smart-permit-inheritance; no-yolo` |
| `bridge` | ABI、plugin/runtime 身份核对结果与 `healthy \| degraded \| unavailable` |
| `policyVersion` | 非秘密摘要 |
| `pending` | `none \| reviewing \| awaiting-human \| permitted`，不显示动作正文 |
| `unverified` | 至少列出真实模型质量、真实宿主 smoke 及尚无证据的平台 |

status 反映查询时状态，不把配置期望冒充实际健康。即使 bridge 为 healthy，只有能无副作用完整 prepare 并由同一 commit 消费的前台 native backend 请求才标为 smart eligible；启用 direnv/devenv、非空 prefix、service/async/PTY、ACP terminal、未知启动脚本或其它不能冻结的变换时，显示具体 `manual-required` 原因。系统保留这些用户配置，不为提高覆盖率静默关闭，并把产生的人工确认如实计入指标。保护基线被改为 YOLO、Bash 不再 prompt、插件缺失/损坏/未加载或身份不一致时，bridge 显示 degraded/unavailable，smart allow 被禁止。eval、MCP、task/child、子代理、非 Bash 和未验证平台必须明确标为“不在 smart 覆盖，保留原生保护”，不得暗示已防住所有绕过。

status 不输出凭据、原始命令、完整 cwd/环境、整段对话、模型响应、异常原文或审计正文。

## `explain`

只解释当前会话最近一次已完成决定，不重新调用模型、不改变模式、不创建或延长许可。若尚无决定，返回固定状态 `no-decision-in-session`。

有决定时响应包含：request/decision 的会话内关联 ID、`allow|ask|deny`、固定来源类别（hard rule、low-risk rule、reviewer、remote-fallback、fallback、human、manual boundary、native protection 或 system failure）、由代码模板映射的短原因、当时模式、policy version、实际 reviewer 及来源或 `not-called`、fallback 是否调用、健康摘要、permit 当前状态。若原 ask 后发生人工决定，必须显示 `ask → human allow|deny` 的来源链及关联 ID，不能把它归因于 reviewer。模型自由文本不能直接进入输出。

对于远程fallback，解释明确其为完整审查的故障接替，并保留上游主审状态和实际调用数；对于本地 fallback，解释必须明确“仅收紧为 ask/deny，未授予 allow”；对于 ask 且无 UI，明确“已阻止”；对于失效许可，给出固定失效类别（取消、操作/参数、上下文/目标状态、授权、模式、策略、模型、健康或身份变化）。它不输出原始命令，只能展示加盐摘要的短前缀；用户实际人工确认由宿主审批 UI 展示当次脱敏后的完整动作。

## 会话和并发语义

- 四条命令只影响发出命令的当前主会话；不写回 profile，不跨新建/恢复继承临时切换。
- 受管 Bash 判定到发起执行仍按会话串行；smart/manual 使用独立控制路径，先原子递增 generation 并 abort 在途请求，再更新模式，绝不等待该串行队列。
- status/explain 可在审查期间读取一致快照，不取得许可，也不延长 30 秒自动 deadline。
- child/headless 中若宿主允许查询，status/explain 仍为只读；smart/manual 不得让 child 获得主会话许可。没有可靠 UI 的 ask 一律阻止。
- 用户取消同样走 out-of-band 控制路径，不等待 Bash 串行队列，并在 1 秒内使操作不可执行；迟到 reviewer/tiny 或人工响应只可作为丢弃事件计数，不能改变 status 中的 permit 状态。

### 生命周期后的状态同步

模型、凭据或provider权威状态变化后，由宿主生命周期路径同步被动reviewer/health快照并使旧许可失效；status本身仍只读，首次查询无需先执行Bash或mode命令来刷新，不触发模型lookup、认证解析、联网或tiny探测。显式reviewer与已记录决定的实际模型身份分别保持其配置及当时绑定。

远程fallback的凭据/provider/模型状态变化与显式主审同样由生命周期钩子使旧许可失效，并同步被动快照；status本身不解析凭据、联网或试调用任何模型。历史决定的各层实际身份与配置选择分开保存。
