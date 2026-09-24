# 多模型规划与执行

[文档首页](../README.md) · [上手示例](getting-started.md) · [配置参考](configuration.md)

## 先配置分工

主Pi agent负责与你讨论、规划、提交和汇总。受管角色由可信配置决定：scout只读调查，worker执行实现，reviewer进行必要审查。secondOpinion另外指定可选B；默认采用reviewer的模型和profile。

[managed-demo.json](examples/managed-demo.json)配置A为primary、必要审查和B为review。不开启第二视角的fix仍有必要审查；开启后增加有界质疑/回应，符合精确复用条件时不重复调用必要审查。也可以将B配置为不同于必要reviewer的第三个模型，但会增加实际调用与预算需求。

```text
/orch fix --model primary --second-opinion -- 修复解析器，并检查错误处理
/orch inspect --second-opinion -- 调查锁顺序并给出证据
```

B的模型、reviewTask和focus在配置中设置，没有`--B-model`参数。`--no-second-opinion`只影响新提交的任务，不能解除旧任务的required。首次明确选择不需要开启故障切换。

## A与B如何协作

1. A在自己的受管上下文中调查或实现。
2. 插件运行真实检查，B在新的只读上下文读取当前候选、A输出、检查与失败证据。
3. B发现可处理的问题后，A可以修改或提供无需修改的证据；有修改要重验。
4. B复核当前快照。默认最多两次回应/复核，且受原修复、步骤、请求和时间预算约束。
5. 没有阻断分歧并满足所有required才完成；分歧、不可用、超时或预算不足会明确上报。

不存在“A认为自己改好了就删除B意见”的捷径。同意旧快照不能用于新代码。模型一致也不取代真实测试。

## 让主agent先规划

启动器使用`--tools kernel_task`；若同时启用普通恢复，对应interactive profile也应使用kernel_task，避免父端直接write/edit绕过受管工作树。可向主agent这样描述：

> 先分析目标和依赖，拆成能独立验收的小任务。通过kernel_task提交inspect或fix；有依赖的工作按顺序推进。遇到BLOCKED先解释原因，保留原job。最终汇总候选目录、检查结果和消耗，不自动合并。

主agent能够调用的工具形式是：

```json
{"action":"fix","goal":"修复明确的行为并验证边界"}
```

随后用status查询同一job；pause/resume/stop按用户指令操作。它不能在工具参数中自由指定模型、扩大预算、开启第二视角或创建定时计划。用户命令与配置负责这些选择。统计usage/models是只读查询。

多个job按已有队列和资源准入执行。同仓库默认活动job上限为1；即使拆成多个任务，也不意味着自动并行。不同job的候选工作树不会自动合并，后续依赖任务也不会自动包含前一job的补丁；依赖成果应由用户审查采用后再作为下一任务输入，或把紧密依赖的改动放在同一个fix目标中。

## 当前“规划”的边界

插件提供固定inspect/fix模板，不把模型自由描述的计划直接编译为任意执行图。decisions/propose只能引用已有且获准的固定步骤。可选semanticReplanning在确认的实现错误后加入受限只读诊断，默认最多一次，再继续同路线修复。

按时段或history-cost选择是另外的显式策略：候选已配置、硬准入通过、只在任务开始时选定。不会因为某模型“修得不好”自动质量升级，也不付费探索其他模型。可用性故障切换由crossProviderFailover及恢复链控制，与首次选择和B分工分开。
