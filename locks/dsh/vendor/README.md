# DSH 归档范围

`rotom-dsh-ssh-subscription-auth-0.1.0.tgz` 为仓库自有 SSH 订阅认证适配器，复用锁定 TUI 的公开 OAuth 导出及 Cursor 的公开认证和 Provider 类。`package.json`、`index.mjs`、`cli.mjs` 与源码逐文件核对后进入 recipe digest。认证入口只启动发起端最小凭据服务，不连接 SSH 或运行模型；helper 手动安装见 [SSH 文档](../../../docs/dsh-ssh.md#manual-helper-installation)。

当前配方消费 lock-policy 声明的 pnpm 11.19.0 原包、仓库自有 Cursor terminal、review-context 和 execution-environment 归档，以及固定上游提交的 TUI 源码构建归档。Core/Cursor/Perry 来自完整锁的原始 npm integrity，未经修改。

`rotom-dsh-ssh-shell-env-0.1.0.tgz` 为仓库自有公开 API 适配器，只继承官方 `ShellEnvRegistry.collect()` 并过滤宿主 `DSH_HOME`、`DSH_PROFILE_DIR` 路径事实；不修改上游实现。归档与 `agents/dsh/packages/ssh-shell-env` 的三个源码文件逐项核对后进入 recipe digest。SSH helper 可执行发行包不在此归档中，须单独准备可信上游产物；当前配方不自动部署远端 helper。

`dsh-tui-0.15.0-e709863.tgz` 来自未修改的 `ccch1mneyyy/dsh-TUI` 提交 `e709863019d56897e64495699c3a945cce194d00`，支持 Core `0.2.1-rc.2`。上游仍将版本字段保留为 `0.15.0`，不能替换成同版本号的旧 npm 归档。`tui-main-provenance.json` 记录固定子模块、工具链、实际构建/打包命令、退出码、完整性和验证限制；解析时同时核对收据与归档。官方发布包装器按其设计转换包清单并恢复源码；未应用补丁。上游打包规则没有包含根 `THIRD_PARTY_LICENSES`，该文件与根 MIT 另存为 `tui-main-THIRD_PARTY_LICENSES`、`tui-main-LICENSE`，保留原文。

`dsh-tui-0.10.1-agentcfg.1.tgz`、`oauth-subs-0.0.88-agentcfg.1.tgz` 及其 patch/provenance 是旧栈的历史材料；不参与新 recipe digest，不得继续构建或移植。对应构建器已删除。恢复旧部署应使用原 worktree、旧锁、原 HOME，不将新会话交给旧宿主。它们的存在不表示新旧会话可安全降级。
