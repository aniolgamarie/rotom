# 合成运行包测试材料

本目录只验证管理器对 manifest、receipt、插件树、构建来源和资产身份的消费。所有材料都是可读的惰性文本，不能作为 OMP、Bun、依赖归档或发布产物执行。

`tests/generate_omp_permission_fixture.py` 从确定的文本字节生成本目录。所有 SHA256、资产大小及合成 commit 均由这些字节计算；版本字段只是虚构 fixture 元数据。`inputs/` 保留每个工具、依赖、源归档、管理器和 upstream identity 的原始材料，`source/` 保留用于身份核验的最小仓库树。

测试将 `source/` 和锁复制到临时仓库，再通过正式 `read_permission_runtime` 验证；不会运行构建器、启动宿主、下载资源或调用模型。这些结果不能证明真实二进制兼容性或模型质量，也不能写入正式 `locks/omp/permission-control/`。

本目录不属于冻结的 240 条审批样本。重生成不得修改相邻的 `fixture-schema.json`、`cases.jsonl`、`labels.json` 或 `FROZEN.md`。
