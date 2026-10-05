# 历史命令形状回归样本

`cases.json` 是人工重建的固定集合，不是原始日志导出。路径、项目名和数据参数均为虚构值；危险命令只作为字符串，不会执行。`basis` 区分重建形状、策略反例、边界控制和独立注释 oracle，不能用它证明命令实际成功或获得授权。

预期结果独立填写 argv 和连接符。`supported` 检查当前完整拆分；`conservative-boundary` 检查动态或无效语法仍拒绝；`coverage-gap` 记录通配符、重定向和多行等尚未支持的常见语法，不能计作解析覆盖成功；`known-semantic-gap` 保存注释行为的正确预期，评测会明确报告当前不一致。

默认 Bun 测试只读本集合，不读取 HOME。历史全集必须先由 `scripts/omp-command-history.py` 显式提取到私有缓存，再用 `scripts/check-omp-command-history.ts --corpus …` 做纯函数评测。自动候选产物仍须人工审核，禁止直接复制进这个目录。

评测的退出码 0 表示没有新增基线偏离或解析崩溃。必须同时看 `knownSemanticFailures`、`semanticConformancePassed` 和 `coverage-gap` 数量；退出码 0 不表示所有 Shell 语法已正确解析。历史接受率是描述性指标，不是解析准确率或审批正确率。

已知注释错误只豁免明确观察过的错误结果；出现另一个错误结果仍会让基线失败，修复成正确预期则记为已解决。自动构建不会读取私有历史。提取选项、静态 JS 载体限制和分层证据见[本轮记录](../../../../docs/follow-ups/omp-command-history-corpus.md)。
