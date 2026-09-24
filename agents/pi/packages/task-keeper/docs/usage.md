# 日常使用手册

[文档首页](../README.md) · [初次配置](getting-started.md) · [多模型](multi-model.md) · [排障](troubleshooting.md)

## 选入口

| 需求 | 入口 | 完成含义 |
|---|---|---|
| 普通对话，统计整项工作 | begin后正常聊天 | 用户accept记录认可 |
| 只读调查 | inspect | 必要证据审查通过 |
| 实现并检查候选 | fix | 当前真实检查和必要审查通过 |
| 增加第二视角 | fix/inspect加--second-opinion | 无阻断分歧且根验收通过 |
| 以后开始 | schedule fix/inspect | 到点仍须满足窗口、期限、权限和资源 |

受管任务自动建立统计，不必先begin。主agent通过kernel_task提交的子job可以计入父统计任务；taskId和jobId不要混用。

## 统计普通会话

```text
/orch begin --group parser-fix -- 修复空字段解析
/orch usage <taskId>
/orch finish <taskId>
/orch accept <taskId>
/orch models --group parser-fix
```

`/orch task begin`、`/orch task finish <taskId> --accept`是对应的长形式。多轮补充、继续和手动换模累计到活动统计任务。打开另一项工作时重新begin；这不清空执行预算。未明确分组的数据标为临时任务，不制造成功排名。

`finish`表示结束，`accept`表示用户认可，两者都不运行检查。已有受管任务缺少required时不能靠统计accept使它通过。

`usage`无ID时按默认最近30天任务开始时间查询。未知费用/usage表示缺少观察，不是免费；actual、estimated、unknown及币种分别展示。模型比较有任务组、工作合同、输入规模和模型版本限制，失败投入保留，零成功时单位成功成本不可计算。

纠正归属或按当前价目重估：

```text
/orch reassign <generationId> <taskId>
/orch usage <taskId> --reprice-at <带时区偏移的ISO时间>
```

纠正有审计，原始用量和预算不变；重估是独立视图，不覆盖历史费用。

## 调查与修复

```text
/orch inspect 调查解析器边界，给出代码证据
/orch fix 修复空字段解析并保持已有修改
/orch fix --model provider/model --second-opinion -- 修复目标
/orch status <jobId>
```

选项只解析显式`--`分隔符之前的部分。模型也可以使用已配置路线ID，例如`--model primary`。`--model`与`--auto-model`互斥。目标文字不能替换可信验证命令、角色权限或预算。

status输出包括状态/reason、候选目录、检查、失败历史、路线、预算和验收有效性。即使曾经COMPLETED，候选、验收输入或工件变化也会使当前回执失效。采用候选前应重新查看status并审查差异；没有自动apply/commit/push/merge命令。

## 暂停、恢复与停止

```text
/orch pause <jobId>
/orch resume <jobId>
/orch stop <jobId>
/throttle status
/throttle pause
/throttle resume
```

有jobId时控制受管任务；throttle控制普通会话恢复。暂停撤销后续自动派发，已有执行可能仍需结束；stop另外请求终止。只有确认结束才显示CANCELLED，unknown不会提前释放资源。停止保留候选，不回滚文件。

临时限流按策略自动等候。永久错误、配置不匹配、未知终止或预算耗尽不会被普通resume绕过。先读reason，不通过重复创建job规避上限。

## 定时与选择模型

```text
/orch schedule fix --not-before 2027-01-01T02:00:00+08:00 --deadline 2027-01-01T06:00:00+08:00 -- 修复目标
/orch schedule fix --not-before 2027-01-01T02:00:00+08:00 --model primary -- 修复目标
/orch fix --auto-model --group parser-fix -- 修复目标
```

替换示例日期为将来的实际时间。必须带Z或时区偏移，不接受“明天两点”。Pi须保持运行；退出后不会唤醒。重开时未来计划继续排队，错过的未启动计划暂停，显式resume仍遵守原deadline。任务跨出窗口后继续执行，不能据此承诺所有请求都享受低谷价格。

自动选模默认关闭，配置时段/候选本身不启用它。开启后仅在可信候选内选择，开始后固定主模型；历史数据不合格会解释回退原因。

## 更改验收输入与环境绑定

```text
/orch refresh-bindings <pausedJobId>
/orch approve-bindings <jobId> <digest>
/orch approve-checks <jobId> <digest>
/orch resume <jobId>
```

先停止并检查正在执行的工作，再审阅status提供的变化和digest。refresh只重读模型绑定；approve命令是显式授权新的验收版本，保留历史和预算，不能清除未知执行。任意policy变化并非都能由这些命令自动迁移；若提示需要对账，先核实当前配置与原授权。

高级固定步骤提议用`/orch decisions <jobId>`取得当前packet，再`/orch propose <jobId> <JSON>`。允许动作和target以返回值为准，不能提交任意shell或新执行图；普通使用无需调用。
