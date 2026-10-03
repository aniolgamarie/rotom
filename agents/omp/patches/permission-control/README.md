# 已退役的 OMP 宿主补丁历史材料

此目录保存 2026-09-30 独立插件迁移之前已存在的补丁、固定输入来源和集成测试，供历史验收追溯。它不属于当前官方 OMP 运行包或 Cursor 原生 Bash 包装插件的实现。

当前治理以 [项目宪章 VI](../../../../.specify/memory/constitution.md) 为准：禁止新增或扩展宿主补丁，禁止继续构建发布此方案，禁止修改 agent 上游源码、缓存副本或官方二进制。`agents/omp/build-permission-control.py` 的历史实现只用于取证，管理器已拒绝该构建/运行 variant。

这里的源码、series、build-inputs 与 `locks/omp/permission-control/` 的旧 manifest/receipt 只记录历史身份。`SOURCES.md`、测试说明及旧规格中的构建步骤均是当时方案描述，不是现行操作指南。当前启用方式见 [独立插件指南](../../../../specs/004-omp-permission-control/quickstart.md)。

此次纳入 Git 保存既有历史文件，没有修改补丁内容、应用补丁、构建宿主或启用旧运行包。后续实现只使用官方配置、公开扩展 API 和仓库自有适配代码。
