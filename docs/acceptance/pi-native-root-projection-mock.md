# Codex 机器根权限投影：隔离验证记录

日期：2026-09-17。层级：mock。真实Codex、账号、模型及操作系统沙箱：not-run。

## 本次交付

`pi_native_roots.py`冻结机器根路径、目录身份与project的Git锚点。
`execution_policy.root_limits`进入请求身份；实际spawn resolver重新核对快照，将机器限制编入原生权限配置，并保存到本次启动授权记录。

限制同时保留原路径，并按同一Git common-dir映射到候选worktree的对应路径。
目录别名辅助按文件系统身份处理；其他Git项目的限制不错误映射到本次候选。

- readonly仅收紧已有write，不赋予额外read。
- deny优先；更具体的allow不能重开被禁止/只读的子树。
- 已声明非project根的file deny使用同一映射；未知根拒绝。
- 源根被替换/删除、Git锚点变化使旧快照失效，监督者请求停止并继续保护写租约。
- 候选符号链接、缺失限制路径、exact目录等无法可靠表达的情况仍在启动前拒绝；不创建占位文件或目录。

## 证据

- 定向native-root/native-boundary组合：17 passed，9.94s；其中真实resolver用例确认输出permissions与启动授权相同，根变化后拒绝复用。
- 最终完整默认Python回归：1117 passed，7 subtests passed，201.71s；覆盖本轮全部用例、既有委托、部署与DSH回归。
- Python compileall、git diff --check通过；修改的契约文档相对链接有效；任务仍112项、76项勾选。
- 首次全量命令因自动权限审核超时而未启动；按工具提示重试一次后运行并得到上述结果。超时不是测试失败或不安全判定。

所有测试使用临时HOME、Git目录形状、假进程和虚构账号哨兵；没有执行Git/CLI/模型或真实bind mount。
目录别名用替身身份模拟，因此仅证明转换算法，不能称macOS或Linux内核权限已经认证。

## 代表性结果

| 输入 | 输出/处理 |
|---|---|
| 原项目library只读，候选有对应目录 | 候选library为read，显式子路径write也被收紧 |
| 原项目private禁止访问 | 原路径与候选对应路径均deny |
| 项目外部目录仅声明readonly、没有allow | 不添加read权限 |
| 整个项目readonly，申请implement | 拒绝；相同范围的readonly请求可以编译 |
| 非project根file deny | 原路径及候选对应路径均受限 |
| 其他Git项目的deny | 保留该项目deny，不封禁本次候选 |
| 根inode改变或目录被移走 | 旧投影失效，活动执行进入停止流程，写锁保留 |
| 候选限制路径缺失/换成symlink | 明确失败，不跳过限制、不创建路径 |
| 权限allow经过symlink父目录指向范围外 | 明确拒绝，不能开放外部文件 |

## 仍未闭合

- 原生CLI实际接受并执行这些权限配置，各平台的路径/沙箱/终止行为。
- 系统、MDM、企业云配置和附加资源的最终生效状态验证。
- 不将额外app-server的config/read结果当作实际exec的同一配置快照：固定版本两入口的加载选项不同，等价性尚未证明。

本记录不宣布T074、整个Pi迁移或release gate完成。
