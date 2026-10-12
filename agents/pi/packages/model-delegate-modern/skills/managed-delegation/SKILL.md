---
name: managed-delegation
description: 使用已选择的 Pi Full model_delegate 工具提交只读 review/investigate，或控制已有逻辑运行；不用于普通主会话编辑或申请写权限。
---

# 受管只读委派

仅在 Full 已选择 unified-delegate 并提供 `model_delegate` 时使用。模型工具只允许 `review`、`investigate`；来源、角色上限和累计预算由当前受信配置/控制面取得，参数不能授予权限。普通主会话编辑仍使用普通文件工具。

当前 strict 输入 token 上界未 qualified 时，生产委派在发送前 unavailable/blocked；不要用字节估算、模型自报 token、改 backend 或重试规避。Pi/Codex 来源或计量不可用也不意味着可退回未受管发送。

## 提交与跟进

以下是 schema 3 参数形状示例。先将 provider/model、cwd 换成当前明确配置且已授权的选择；request_id 在同一动作的重查中保持不变，不代表后端已接受。

```json
{"schema_version":3,"action":"submit","request_id":"review-001","backend":"pi","mode":"review","preset":"review","task":"检查恢复路径并报告证据，不修改业务文件。","model":{"provider_id":"configured-provider","model_id":"configured-reader"},"cwd":"/workspace/project","timeout_seconds":30,"allow_workspace_write":false,"worktree_root":null}
```

取得实际逻辑 run_id 后替换下列 actual-run-id。message 只向已确认 ready/running 的当前 attempt steer；idle 不能靠 message 启动。continue 要求旧 physical attempt 的终止/回收与原私有恢复资格验证，保持逻辑 ID/来源/累计预算，创建新的 physical attempt。

```json
{"schema_version":3,"action":"message","request_id":"message-001","run_id":"actual-run-id","text":"优先核对恢复边界，仍不修改文件。"}
```

```json
{"schema_version":3,"action":"continue","request_id":"continue-001","run_id":"actual-run-id","text":"基于已保存证据继续检查兼容性。","timeout_seconds":30}
```

```json
{"schema_version":3,"action":"cancel","request_id":"cancel-001","run_id":"actual-run-id"}
```

## 结果边界

- 注册/逻辑 action 完成不等于物理启动被接受，更不等于模型或任务成功；检查返回的实际状态、错误与原证据。
- ACK 丢失或 unknown 时不补发、不新建 request_id 伪装同一动作、不自行退款；使用已有受管状态查询入口或交回用户，工具没有 query action。
- cancel 是请求停止，不是业务回滚或已确认死亡。迟到回复不能恢复 grant；资源释放须依赖原终止/回收证明。
- 参数中不得加入 source_ref、origin、角色或预算标签；不得申请 implement、allow_workspace_write=true 或 worktree_root。写任务需要另一个已建立的受信入口，本 Skill 不提供它。
