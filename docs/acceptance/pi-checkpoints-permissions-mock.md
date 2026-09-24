# 普通代码恢复点与权限接口：隔离验证

日期：2026-09-17。层级：mock；真实Pi/Codex/DSH、账号与模型：not-run。

## 已实现

- git-checkpoint改为按会话、工作区、策略、运行包和显式文件范围保存的私有代码快照。元数据与正文分开，agent_end不清空；增加手动捕获/恢复命令。
- 捕获和恢复进入既有AgentManager同一队列，supervisor为它们预留跨实例worktree租约；一次性helper调用监督者执行真实文件IO。
- 恢复先预览写入/删除数量，确认后重新取得租约并校验预览摘要；先检查所有修改权限，再保存恢复前备份，随后逐文件CAS。部分失败返回partial并取消fork。
- 秘密名称与父侧拒绝在正文读取前处理；数据大小/文件数超限明确失败。满额不自动删除历史。quota/theme调整不使相同文件范围失效。
- 配置启用前检查范围和pi-subagents前提；运行包包含固定helper及runtime模块导出，扩展不依赖仓库相对runtime路径。

这项处置保留“按历史恢复代码”的用途，但不是Git stash格式或合并算法兼容层，不操作Git分支/索引。说明见[使用指南](../pi-checkpoints.md)。

## T084复核与收尾

| 要求 | 当前证据 |
|---|---|
| 缺/坏策略拒绝，不返回空deny | PermissionAccess与实际permission-system适配器负向测试 |
| 父策略显式桥接 | Task Keeper实际ManagedExecution.require父快照；缺桥、错摘要、遗漏deny在分配前拒绝 |
| /yolo只改交互覆盖 | session-yolo实际命令测试；策略摘要不变，managed上下文不能改变覆盖 |
| 固定文件/命令转换 | canonical/absolute-file/argv转换；未知语言、glob、歧义根或不匹配argv拒绝 |
| 策略收紧使旧ticket失效 | 会话/cwd/输入绑定与generation测试；旧ticket不能跨上下文使用 |
| ordinary真实业务根写入 | Python实际临时文件IO与跨实例工作区租约测试；不要求Task Keeper任务 |
| 角色/task更窄上限 | managed worker与readonly委托负向用例 |
| 引用不能静默略过 | 所选policy根/command_ref与机器限制引用校验；Python FilePolicy拒绝未绑定根 |
| Pi委托继承机器禁止根 | project-wide allow不能读到同项目的denied子根；额外根身份不增加角色read/write roots |

T084属于源码与隔离测试层面的任务；原生宿主加载、完整插件组合与平台认证继续在后续任务验证。

## 已运行测试

- 代码恢复点、配置与目录权限定向组合：50 passed。
- 补充权限引用、Pi委托与机器根后的组合：71 passed。
- 完整Node runtime/Task Keeper/model-delegate/proxy组合：152 passed。
- Task Keeper与扩展的临时源码副本TypeScript检查、Python compileall、git diff --check通过。

最终完整默认Python回归：1132 passed，7 subtests passed，232.02s。
以上组合有重叠，不累计为独立测试总数。T084源码与mock复核完成，任务已勾选；不代表真实宿主验收。

## 未完成

T086还包含dirty-repo-guard、gentle-agent-state、slopchop/readseek及其他操作适配。本报告不将它们、整个Pi迁移或release gate标为完成。代码快照原生事件时序、真实恢复交互也没有用mock替代。
