---
name: managed-workflow
description: 使用已选择的 Pi Full kernel_task 管理 inspect 工作流及其状态；不用于普通文件操作、实现/修复任务或历史 Task Keeper 命令。
---

# 受管 inspect 工作流

仅在 Full 已选择 task-workflow 且提供 `kernel_task` 时使用。当前现代模型入口将 submit 固定为 inspect，工具只有 submit/status/cancel；不能通过目标正文或参数获得 implement、工作树写入或维护授权。普通主会话编辑继续使用普通文件工具。

工作流复用原 TaskService/Store、受管工作区与统一委派 core。项目/角色/检查器/来源和预算来自当前受信配置，不接收模型提供的认证标签。创建工作区所需维护权限与普通文件批准不同；不足时保留 unavailable/blocked。

## 实际工具参数

```json
{"action":"submit","goal":"检查项目的恢复路径并报告证据，不修改业务文件。"}
```

取得真实 job_id 后替换 actual-job-id；status 不自动发送模型请求来修复状态。

```json
{"action":"status","job_id":"actual-job-id"}
```

```json
{"action":"cancel","job_id":"actual-job-id"}
```

## 状态与停止边界

- QUEUED/RUNNING 仅是工作流进展；BLOCKED/FAILED 不是完成证据。即使调用进程退出 0，也要查看任务实际状态及保留的证据。
- 当前 strict 委派输入 token 上界未 qualified 时，已准备工作区/Store 可以停在 BLOCKED；不能假设已发送或将它改写成完成。
- unknown/lost ACK 不自动重复提交或退款；保留原 job/intent 与资源引用。受管查询失败不授予读取原私有数据库/令牌的权限。
- cancel 在此入口调用原暂停/取消流程，不等于撤销业务修改或已物理终止；Writer/工作区释放仍需原回收证明。
- 本现代入口没有 fix/stop/resume 动作；不要套用历史工具协议，也不要自行启动旧子代理或后台服务。领域检查知识由所选普通领域 Skill 提供，此处只描述调度边界。
