# Task Keeper 类型检查的独立开发依赖

日期：2026-09-28。状态：待实现；不是已通过的 CI 检查。

本次 review 修复已把 `node agents/pi/packages/task-keeper/scripts/test-mock.mjs` 加入独立 CI job。它只执行显式 mock 文件，通过 `tests/fixtures/pi/mock-guard.mjs` 从 `tests/fixtures/pi/tooling` 的完整锁加载依赖，并将 runtime 映射到仓库源码，不启动 Pi/Codex 宿主。

`npm run typecheck` 是另一条检查路径。目前 `agents/pi/packages/task-keeper/package-lock.json` 保留旧开发环境的 `pi-subagents: 0.63.0`，与当前 package.json 的 `@tintinweb/pi-subagents: 0.19.0-agentcfg.1` 和 `@agentcfg/pi-runtime: 1.0.0` 不一致；tooling fixture 也没有 TypeScript、Node 类型及 Pi SDK。不能直接把该目录的 `npm ci` 加入 CI 或把 mock 通过写成类型检查通过。

后续需要建立与当前源码接口匹配的独立、完整锁定的开发依赖环境，使用真实 SDK 类型执行 `tsc --noEmit`。所需本地 runtime/subagents 包应来自声明的受信路径，不能以空类型声明掩盖接口错误。包内文件变化可能影响 vendor/recipe 摘要，应同时核对运行锁而不直接改写历史验收产物。

验收条件：新 checkout 中可消费锁安装开发依赖；不运行生命周期脚本或原生宿主；类型检查和现有隔离 mock 均通过，安装后锁无变化。类型检查本身不替代 native/cold 或 live 验收。
