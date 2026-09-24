# Pi 迁移 Git 交付核验（2026-09-24）

本记录覆盖源码与证据的版本归档，不扩展 spec 001 的平台/live 验收范围。
候选仍为 `9d6a927093f066c9428a5c193a636c4d73c5e64c946d24dc6a08185cf3f0dbf0`，recipe 为 `85fc15c3babf58e768e2b09c25f7eac031644cac220c60c16d093c87cbb9257b`。

## 提交组织

1. 实现与固定依赖：公共适配接口、Pi 监督与恢复、Task Keeper、model-delegate、完整技能/插件、四配方、锁与对应测试。
2. 验收证据：保留各候选历史、当前原生与冷重建证据、修订后的批准范围，以及本次交付检查。
3. 规格与使用文档：Spec Kit 工作流、已完成的 spec、操作指南和独立后续验证清单。

采用精确文件清单提交，不使用 `git add .` 或 `git add -A`。原有 post-commit 钩子调用 Qoder；本次仅对提交命令指定空 hooks 目录，避免额外启动第三方工具，不修改原钩子或全局 Git 配置。

## 凭据、临时文件和大型工件检查

- 对待提交文本及20个当前源码 vendor 包的归档成员扫描私钥、常见 provider token、JWT、带密码 URL 和字面凭据赋值；初次共检查4755个文本单元，166个规则命中经复核为文档占位、测试输入或代码字符串，未发现真实凭据。提交前新增报告亦纳入复扫。
- 未收录本机登录文件、私有配置、`node_modules`、运行包或误落到仓库 `~/` 下的本机数据库。Qoder 私人设置和该数据库目录通过忽略规则排除，原文件保留。
- 六个固定 URL 的 Codex/GGUF 资产共1,681,985,119字节，不进入Git；获取与完整性校验见[资产交付说明](../pi-vendor-deliverability.md)。
- 当前锁引用的20个本地/git源码 vendor 包入库，最大单文件为锁定 subagents 包9,383,755字节。其媒体、许可和资源仍是固定来源的一部分，未为缩减体积修改已验收源码。
- 13个不再被当前锁引用的历史 vendor 包留在原目录，未提交、未删除；无关 OpenSpec 工具集成与两份独立缺陷笔记保留原工作区状态。
- 补齐71个被通用 `dist/` 规则漏收的固定分发输入，分别属于MCP、pi-rules和OpenSpec生成器；候选正文未变。

## 待提交快照检查

以Git原有HEAD为底，只覆盖明确计划提交的文件，构建独立临时源码快照。
六个外部资产在确认不属于Git内容后，仅为离线锁检查复制到临时快照；没有联网下载或重建运行包。

- 生产 `PiBackend.read_lock()` 通过，证明快照中的recipe、锁与必要源码闭包一致。
- 原生归档349个文件、关闭归档9个文件摘要通过。
- 当前81项软件范围的生产报告复算通过，与归档批准结果一致；未把测试报告登记为live通过。

## 测试结果与首次失败

首次运行：[snapshot-mock.json](snapshot-mock.json)。Python结果为1869 passed、1 failed、7 subtests；Node因专用测试依赖尚未安装而未能启动。

Python失败重现了恢复替身helper直接写入标记文件的竞态：生产读取保护在文件尚未完整写入时正确拒绝。仅修改 `tests/test_pi_recovery_protocol_surrogate.py` 的替身发布方式：临时文件完整写入后原子替换；未修改生产恢复逻辑、存储保护或候选锁。

测试工具使用现有机器已准备、与Git中测试package-lock一致的依赖复制到临时快照；这不是新机依赖下载或原生冷重建证明。新克隆的显式测试依赖安装步骤已补入[验证指南](../../../specs/001-unify-pi-capabilities/quickstart.md)。

- 定向恢复替身：[6轮记录](recovery-targeted.json)，每轮6项通过，共36次通过。
- 修复及依赖准备后完整隔离回归：[snapshot-mock-final.json](snapshot-mock-final.json)，**1870 pytest passed + 7 subtests、325 Node passed、0 failed/skipped**。
- 默认回归使用临时HOME、假网络/模型/宿主，没有真实账号调用。
- 原始失败报告保留，不将复验结果追认为首次零失败。

本次不推送，不删除历史运行目录，也不将其他平台或真实服务声明为通过。
