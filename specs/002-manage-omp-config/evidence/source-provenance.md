# 固定上游来源材料

日期：2026-09-24。执行者：scout（gpt-5.6-luna / medium）。范围：实施所需公开来源下载与静态核对；没有运行宿主、登录、查询账号 usage 或调用模型。

- 上游：[can1357/oh-my-pi v18.3.0](https://github.com/can1357/oh-my-pi/releases/tag/v18.3.0)。源码 commit：`62bc57be1b03ef0802a33cf7f5f530e534527531`。
- [不可变 commit 归档](https://codeload.github.com/can1357/oh-my-pi/tar.gz/62bc57be1b03ef0802a33cf7f5f530e534527531) SHA256：`edcc0f93a0ab0c0223d0651bba3624c55a32d25494a43b0257ea626be1dff97d`。本次临时文件 `/tmp/rotom-omp-plan/commit.tar.gz`。
- 归档内完整 `bun.lock` SHA256：`eaf18ef55ef20a21991d66417054d44528ad7767df294e710a5c24c4ce2b5c87`。与此前 tag 解包中的 `bun.lock`、`package.json` 分别执行 `cmp` 成功；源码包版本为 18.3.0。
- tag 归档独立摘要 `a17689ba611355ddc7225541673268b2d1ff1527523cc028b3fbd6ea5b069533` 不能用于 commit URL。
- 许可证：commit 归档根目录 `LICENSE`（MIT）及完整 `THIRD-PARTY-NOTICES.txt`。拷贝主题/schema 时同时保留适用许可说明。

## 官方发布资产

来源：[SHA256SUMS.txt](https://github.com/can1357/oh-my-pi/releases/download/v18.3.0/SHA256SUMS.txt)。这里只下载校验清单，未下载或运行这些二进制作验证。

| 支持矩阵目标 | asset | SHA256 |
|---|---|---|
| Linux glibc x64 | omp-linux-x64 | d2fdaa29affe96e596eb9c78d42f548f1f291df28608631bcc00750a84b94bc3 |
| Linux glibc arm64 | omp-linux-arm64 | bdfb9c494e17a2fee1956dae16a010a1953574ce4172c4db8efe06fbe477c637 |
| macOS arm64 | omp-darwin-arm64 | d61fb411f24146bed48dd901b13b5912a297d899ee691dda69c4b5b7ab8c35dc |
| macOS x64 | omp-darwin-x64 | be74498e0edcde7e018247b925f0e0ebf00a7748a1006b3a02eb62ca9e021baf |

上游清单另含 musl 和 Windows 产物，本次适配范围仍明确拒绝这些平台。存在资产 URL 与摘要不等于平台通过。解包目录无 Git object database，未另做 commit object 验证；记录的是 HTTPS commit 归档的实际内容身份。

## 原生接口依据

- 完整主题 schema：`packages/tui/src/theme/theme-schema.json`；完整模板：`packages/tui/src/theme/defaults/titanium.json`。入口验证见同目录 `loader.ts`。
- 原生扩展：`packages/coding-agent/src/extensibility/extensions/types.ts` 的 `registerCommand`，及 `docs/extensions.md` 的默认导出 factory 示例。`/rotom-health` 使用 `handler` 与 `ctx.ui.notify`，不假定 Pi 扩展兼容。
- MCP 配置：`packages/coding-agent/src/mcp/types.ts`；发现：`src/discovery/builtin.ts`；调用：`src/mcp/client.ts`。stdio command/args 为字面 argv，HTTP 类型为 `http`。
- 参数解析：`packages/coding-agent/src/cli/args.ts`。原生 `--` 后均为提示文本；`--trusted-extension` 与 `--extension` 均可添加执行来源，必须在受管入口拒绝。
- 会话恢复：`packages/coding-agent/src/main.ts` 在 `resumedProject.cwd` 分支重设 cwd，发生于原生启动内部。首版拒绝外部来源、追加目录和可改变 cwd 的恢复参数，防止管理器只检查初始 cwd 后原生切换未经检查的来源；限制同步入 CLI 契约。

这些是实现依据，不能替代 schema/行为测试、完整运行包校验或真实宿主验收。
