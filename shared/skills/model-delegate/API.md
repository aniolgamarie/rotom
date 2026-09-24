# V2 API

## 请求与凭证

见 schemas/request-v2.json、receipt-v2.json。schema_version=2，未知字段失败。
run/attempt、backend/model、cwd/worktree、runtime/policy、owner、lease/grant 与结果严格关联。
observed_model 未由服务或宿主事件报告时为 null；费用未知为 null。

状态：starting/running/start_unknown/completed/failed/canceled/timeout/unknown。
ready 未确认不表示未启动，不自动重发。get_delegate_result 重新核验本次结果；
verified-execution 与 review-pass/任务验收分开。

## 观察与控制

cursor 为 run_id:seq，不能跨 run 或超过已存在语义事件。poll 返回 next_cursor 与 has_more。
心跳不产生语义 seq。默认控制/观察信封上限4096 UTF-8字节，长结果用 result 的字节分页读取。
wait 超时不取消；cancel 只确认接受，直到 supervisor 证明进程与外部工作清零才释放保护。

resume 是用户显式操作，建立新 run/attempt，并保留 continuation_of。
核验旧执行终止、backend/model/cwd/worktree/runtime/policy 一致及合法 native resume token。
V1 历史不能被当作 V2 可恢复任务。

## 管理者接口

同一 AgentManager 的 external v2 通道提供 submit_delegate/get_delegate_result/cancel_delegate/submit_batch。
提交使用实例身份、policy/request digest 和幂等键；相同键内容变化失败。
managed 上下文执行前拒绝；不新建队列，不以脚本退出码代替凭证。

## Context 与反馈

context-v2 保留 task/scope/constraints、workspace、带来源和状态的事实/决策/假设、references、turn 和 budget。
预算投影保留权威字段；记录被裁掉的材料，无法容纳权威字段时失败。
旧 entries/revision 的 claim/evidence 可转换，旧 confirmed 只作 provisional。

required feedback 的模型正文仅包含 facts/conflicts/summary；控制者添加当前 run/turn/candidate/artifact 关联，
并生成 feedback-v2。模型新增论断保持 unverified，旧候选事实为 stale，争议为 disputed。
缺反馈、格式错误或关联错误不能通过本次 required-feedback 验收。


## 只读重试与离线探测

`agent_options.model_delegate.readonly_retries` 为 0–3，默认 0。只有独立用户 CLI 的 review/investigate 请求使用它；
由 Pi 管理者提交的委托保持后端零重试，上层不与 runner 重复接管恢复。implement 禁止自动重试。
仅重试已明确失败的 HTTP 建连/请求阶段；流中断不会被当成完整结果，start_unknown 不重发，重试不创建新的 run。
所有发送仍受原始截止时间、精确模型和显式路线约束。Pi 后端支持 openai-completions 和 openai-responses 的 API-key 模型；
Pi 原生 openai-codex OAuth 委托只使用所选实例未过期的 access token，不复制 refresh token、不后台刷新；到期须由用户在父会话登录/更新后重试。
Cursor OAuth 委托要求 Bun、明确 direct 路线和零重试，只使用所选实例短期凭据。上述原生协议及 Codex 重试参数仍待独立 native/live 验证。

`probe --backend pi|codex` 只核对所选配方和冻结入口，不运行宿主或模型、不读取账号正文。
输出明确保留 native_load/execution=not-run、authentication=unknown；installed 不代表登录或执行通过。
不同动作不接受的参数直接报错，例如 status 不接受 --allow-workspace-write。


## 批次产物

fanout 的 submit/status/cancel 只请求当前实例已存在的管理者端点，不自行创建进程队列。
混合 completed/canceled 为 partial；只有全部已验证完成才为 completed。
大批次控制摘要保留 `batch-result-<sha256(batch_id)>` 引用；完整JSON位于显式实例的
`pi-home/model-delegate/batch-results/<sha256(batch_id)>.json`（私人0600文件）。
该文件是观察快照，接受结果仍须重新获取对应单run的当前receipt，不能把缓存批次JSON当成新验收证据。


## 执行边界与原生授权

请求/收据V2新增必填execution_boundary与execution_policy_digest。Pi固定agentcfg-tools，
Codex固定native-sandbox，由supervisor决定；CLI/模型输入不能覆盖它们。
缺字段的早期未发布V2记录保留，不能自动补授权后认证或resume。

Codex配置示例：

```toml
[agent_options.model_delegate.codex.native_execution]
allow_shell = true
tool_network = "none"
```

Codex原生命令在整次沙箱授权内执行，不逐条要求tool:ID；文件范围和父deny仍必须可准确映射，
不能将write/create自动扩大成delete/rename。该声明不授予implement，写入仍需三项显式准入。
结果使用冻结原生授权、候选结果和独立终止证明，不要求MCP变更日志。
取消到实际终止之间写租约继续保持；Task Keeper仍拒绝未经认证的外部委托。
真实CLI参数、沙箱与配置发现仍待独立native验证。


原生execution_policy还冻结root_limits：机器根路径/目录身份、项目Git锚点、readonly_roots和denied_roots。
限制保留原路径并映射同一Git项目的候选对应路径；readonly不会额外开放未授权目录，具体allow不能重开父限制。
根被替换/删除或策略变化会请求停止旧运行。限制目标在候选中缺失、链接歧义或规则不可表达时拒绝启动，不自动创建目录。
目录别名与权限字典转换已有mock覆盖；实际原生沙箱行为仍需各平台验证。

Codex 执行策略还绑定 `configuration_admission="official-cli-restricted-v1"`。官方 CLI 路线只接受系统 Codex 目录不存在／为空、macOS 受管偏好不存在，以及可识别个人 OAuth 或明确 API-key 实例账号。组织、未知、混合或无法核验的身份拒绝；不自动换账号或修改管理员配置。稳定受信机器和账号是运行前提，启动预检不提供同进程原子保证。缺少认证文件仍为退出码 3，配置准入拒绝为 5，并仅公开固定 `CODEX_*` 原因码。默认 doctor/probe 不读取认证正文；start/resume 启动路径才检查账号类别。
