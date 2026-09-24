# dirty-repo-guard 隔离验证记录

日期：2026-09-17。对应 T086 的 Git 状态检查子项；T086 整体尚未完成。

## 已验证

- 专用状态入口要求所选扩展、manager 身份、显式只读 Git 绑定和 `tool:ID` 命令授权；任意参数、交互绑定、写根、worker 调用在分配前拒绝。
- checkout 和 linked worktree 的业务根、专属 Git 目录和 common directory 只读挂载；启动前检查身份，不能覆盖用户同名根；其他普通命令仍拒绝 `.git`。
- 状态检查与受管 writer 共用工作区租约。取消或 finish 请求不能代替物理终止证明；范围/策略变更在启动前拒绝。
- 有 file deny 或 machine denied root 的不完整范围不能报告干净。独立夹具区分非仓库与损坏 Git 标记。
- 实际 AgentManager + OrdinaryOperations 在假 supervisor 下完成单次执行；核验退出身份、完整输出摘要和独立终止证明后收取消费结果，无额外 manager。
- 扩展不调用原生 `pi.exec`；新建/切换/fork 检查失败取消；脏仓库无 UI 默认取消，UI 需明确选择。
- NUL 格式解析覆盖换行/中文路径、rename、冲突、缺字段、协议损坏、非零退出、截断、stderr 警告与缺少终止证明。

## 验证结果

- Python 全量隔离回归：**1145 passed，7 subtests passed**，226.92s。
- 全量收集后追加根名碰撞修复与用例，最终 Git 状态 + PiAdapter 定向回归：**33 passed**，11.10s。
- 最终 Node 运行时、Task Keeper、model-delegate、代理组合：**156 passed**，2235.68ms。
- 扩展临时副本 `tsc --noEmit`、Python compileall、`git diff --check` 通过。

主要测试：`tests/test_pi_git_status.py`、`tests/test_pi_commands.py`、`tests/test_pi_adapter.py`、`agents/pi/runtime/tests/git-status.test.ts`。

默认测试阻断网络和真实子进程；Git 仓库由临时文件构造，没有启动真实 Git、Pi、Codex、DSH、tmux、Zellij 或音效程序。类型检查使用既有临时工具链。

## 尚未验证

- 目标平台的真实 Pi 事件顺序、Git 沙箱启动和物理终止。
- 实际 Git filter、子模块、稀疏工作区等组合。
- `gentle-agent-state` 外部终端服务及其完整依赖/派生进程适配。
- 最终依赖锁、冷重建和整套迁移 native/live 验收。

这些 mock 结果不构成原生能力或最终发布批准。
