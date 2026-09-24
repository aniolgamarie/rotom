# 委托进度协议 V2

进度用于观察执行，最终结果以当前请求的 receipt 和物理终止证据为准。

## 事件与游标

`event-v2.json` 定义封闭事件字段：schema_version、run_id、seq、timestamp、kind、phase、artifact_id。
seq 从 1 连续递增；同序号的相同事件可重复读取，内容冲突或序号跳跃被拒绝。
控制层只发布固定阶段名和私人产物引用，不把模型推理、命令输出、账号信息或原始错误写入事件。

`poll --run-id ID --after ID:SEQ` 从已处理位置继续读取。游标包含 run_id，不能跨任务使用，
也不能指向尚未存在的事件。返回 `next_cursor` 和 `has_more`；只有消费返回的事件后才推进本地游标。
无新事件的心跳保持游标不变。控制信封上限为 4096 UTF-8 字节；长结果通过 `result` 分页读取，
不得将结果截成一段后声称它是完整产物。

## 启动、等待和停止

- starting：启动意图已持久化，尚未确认后端 ready。
- start_unknown：ready 未确认，不能推断没有启动；相同请求不得重发。
- running：ready 与 run、lease、request_digest 一致。
- completed/failed/canceled/timeout：控制者已核验终止与资源回收；completed 还要求非空最终产物及关联证据。
- unknown：没有足够证据确认执行状态，保持活动保护。

`wait` 一次最多等待 60 秒，返回 timed_out 不代表已取消任务。需要停止时显式调用 `cancel`；
accepted 仅表示已接受停止请求，termination_confirmed 才表示资源已安全回收。
resume 创建新 run/attempt/lease，先核验旧执行已终止，并关联 continuation_of。

## 结果接受

重新查询结果时，核对候选、产物摘要、模型身份和物理终止证据；required feedback 还须重新核对反馈文件。
`verified-execution` 仅表示执行证据完整，不表示审查结论正确或业务验收通过。
模型身份和费用没有可靠观测时保持 null。V1 历史记录不能作为 V2 恢复或结果接受凭证。
