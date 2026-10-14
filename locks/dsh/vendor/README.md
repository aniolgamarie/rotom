# DSH 归档范围

当前配方只消费 lock-policy 声明的 pnpm 11.19.0 原包与仓库自有 Cursor terminal 薄适配及 review-context 常量工具归档。Core/TUI/Cursor 第三方代码来自完整锁的原始 npm integrity，未经修改。

`dsh-tui-0.10.1-agentcfg.1.tgz`、`oauth-subs-0.0.88-agentcfg.1.tgz` 及其 patch/provenance 是旧栈的历史材料；不参与新 recipe digest，不得继续构建或移植。对应构建器已删除。恢复旧部署应使用原 worktree、旧锁、原 HOME，不将新会话交给旧宿主。它们的存在不表示新旧会话可安全降级。
