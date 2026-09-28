# 工作区提交计划（2026-09-28）

基线为 `8bd0e55`。当前工作区的修改分为两条主线，建议只生成 **2 个 commit**。本计划不执行暂存、提交或回滚。

## 1. agentcfg 与 OMP 改进

建议标题：`feat(agentcfg): simplify setup and improve model and OMP workflows`

合并提交下列已配套的改动：

- 公共 DeepSeek、Kimi、GLM 双协议模型预设、来源与价格快照、schema、模型向导和私人 key 状态检查；缺少可选模型 key 时允许 DSH/Pi/OMP 启动，并提示受影响模型。
- `profiles`、`setup`、可省略工具名的 `run`、阶段进度、失败诊断；后端进度回调和部署前计划复核。
- OMP 同实例并行运行的共享租约、Vim 状态栏、`doctor --input` 的终端与阻塞事件诊断，以及存储目录并发创建修复。
- 对应的 `src/agentcfg/`、`shared/`、`schemas/local.schema.json`、`schemas/registry.schema.json`、`profiles/omp-kernel.toml`、相关 `tests/`、README 和 `docs/` 改动。`docs/agentcfg-ux-plan.md` 与 `docs/omp-parallel-smoke-2026-09-27.md` 同组审阅后加入。
- `locks/omp/manifest.json`、`locks/pi/manifest.json` 与最终公共模型和 OMP kernel 配方 **同时提交**；OMP 锁的 recipe 摘要同时覆盖共享模型文件、Vim 状态栏和 kernel fixture，不能拆开提交。
- `tests/test_pi_cursor_readseek_binding.py` 中的测试导入修正若在当前 pytest 路径下确有必要，也归入本组，并在提交说明注明是测试兼容修正；若只是本机偶发现象，暂缓纳入。

验收：运行模型向导、setup、OMP 输入与并行运行、运行时 key、schema/适配器及相关 Pi 测试；核对两个现有锁与最终配方一致。检查提示和诊断不含密钥或按键。提交前看暂存区的完整补丁，确认没有带入 termcfg 文件。

## 2. termcfg 终端与代理管理

建议标题：`feat(termcfg): manage terminal and proxy configuration`

提交 `specs/003-sync-terminal-tools/`、根目录 `termcfg`、`src/termcfg/`、`terminals/`、`locks/termcfg/`、`schemas/termcfg/`、`examples/termcfg-machine.toml`、全部 `tests/test_termcfg_*.py`、`tests/conftest.py` 新增的假终端命令 fixture，以及 `docs/termcfg*.md`。README 中仅介绍 termcfg 的段落也归本组。内容覆盖公开来源、选择性同步、备份与恢复、机器和仓库锁、mihomo 运行包及显式服务操作、进度诊断、规格和隔离验收记录。本提交计划文档可随本组归档。

验收：`tests/test_termcfg_*.py` 当前为 **106 passed**；提交前重新运行，并检查 `./termcfg --help`、来源/锁摘要、权限、许可清单及文档链接。默认测试必须使用临时 HOME/XDG、阻断网络、假进程；真实 HOME、mihomo、订阅和 tmux smoke 仍需单独明确授权，不作为这两个提交的默认门槛。

## 提交时的检查

1. 第一组只暂存 agentcfg/OMP 相关文件与 README、文档的对应段落；第二组再暂存 termcfg。README 两种语言和 `tests/conftest.py` 是交叉文件，核对 `git diff --cached` 后再提交。不要使用 `git add -A`。
2. 每组运行对应测试和 `git diff --cached --check`，确认暂存区没有私人配置、凭据、缓存或 `__pycache__`。提交后查看 `git show --stat --oneline HEAD` 和剩余工作区差异。
3. 两组完成前已运行全量 pytest：**2349 passed、2 skipped、6 failed**。6 项 Pi Unix socket 测试在默认沙箱被 `EPERM` 拒绝，单独授予测试权限后为 **6 passed**；其他全项目测试通过。

这两次提交各自覆盖一条完整功能线，数量少；代价是第一组补丁较大。因此第一组必须重点检查锁摘要、交叉文件的暂存范围，以及模型密钥和 OMP 并发回归。
