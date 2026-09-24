# 证据登记器检查点复核：尚未通过

2026-09-22；复核对象为本轮修改后的`scripts/register-pi-evidence.py`。仅调用报告读取/校验函数，全部变异材料位于自动清理的临时目录。未启动宿主或网络、未改原始报告、未运行正式证据登记主入口。

## 已确认的进展

从仓库32da4799归档读取的mock、native host-resources及default cold报告，三个正常样本均被接受。上一轮字段层级不匹配和空results的部分问题已修复。

## 仍被错误接受的8个样本

基线为真实生产报告的复制品，以下材料都应拒绝或不能产生passed。本轮调用实际verify函数的结果全部为ACCEPTED。

| 输入变化 | 当前结果 |
|---|---|
| mock case=all，但删掉node runner，仅保留pytest | ACCEPTED |
| mock所有runner的artifact_refs改为空数组 | ACCEPTED |
| native场景ID改为invented-scenario，其余保持不变 | ACCEPTED |
| native的profile改为pi-cursor、platform改为darwin-arm64，但保留原runtime身份 | ACCEPTED |
| native execution增加timed_out=true，同时保留exit_code=0与termination_confirmed=true | ACCEPTED |
| native场景facts改为空对象 | ACCEPTED |
| cold两个目标都命名first，且steps/native_cases全部清空 | ACCEPTED |
| cold摘要仍写passed，但其引用的host-resources报告及子场景改为failed、termination_confirmed=false | ACCEPTED |

最后一项在临时目录保留了完整cold报告及所有被引用native文件，随后只破坏其中一个native文件。登记器仍接受了该cold报告，不是由于缺文件提前失败。

## 对应实现缺口

1. mock只检查runner非空/不重复，没有核对预期集合或要求产物引用完整；未使用完整schema校验。
2. native没有校验预期case/profile/platform/scenario集合、重复场景、timed_out/interrupted及必需facts。仅核验传入的锁/runtime/source字符串不足以解决这些问题。
3. cold未要求规定目标名称、完整安装步骤和完整native case集合，空列表令for循环全部跳过。
4. cold读取引用native文件后只对比lock/source，没有复用完整native语义校验；也没有核对该文件实际对应case和runtime。
5. 候选source基准仍从首个报告建立，需要明确来自已核验候选的信任依据。

## 其他未满足的检查点要求

- 当前8个测试未包含缺runner、越界引用、场景缺失/重复、platform错误、多case聚合、无live被计通过，以及主入口错误输入后的输出状态等关键回归。应添加实际函数/主入口测试，不能以现有8个passed代表此前全部验收条件。
- 原生/cold证据仍使用文件mtime作为起止时间，并构造`--case a+b`及`<installed-runtime>`命令；这些不能冒充实际执行记录。
- scope输出仍使用`out.write_text(...)`直接覆盖相同revision文件。需拒绝不同内容的既有快照，或显式产生新revision，保留历史。
- `write_record()`已有文件分支会跟随symlink读取；应复用安全证据存储与路径校验，不能只在新建时使用O_NOFOLLOW。
- 归档mock的artifact_refs被原地修改：需核对原始字节/摘要是否保留；若需要搬迁映射或派生归档版本，应另存并记录来源，不能把修改后的文件当作未经改变的原始报告。

## 通过条件

1. 用完整生产schema和调用方提供的预期候选、平台、case、场景集合做校验。
2. cold递归核验每个实际引用的native报告，不只核对摘要行或身份标签。
3. 将上述8类漏洞拆成可重复的负向回归，保留真实格式正例；尤其覆盖空集合和缺字段不能绕过检查。
4. 在临时输出根运行登记器主入口和正式报告器：合法输入、混候选、缺case、冲突、重复执行、未执行live均有可核验结果。
5. 输出保留实际执行来源与历史快照，不通过修改旧报告获得通过。

达到这些条件前，登记器检查点保持未完成，不据此推进发布批准或磁盘清理。
