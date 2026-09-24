# 测试、覆盖率与发布验证

[文档首页](../../README.md) · [发布摘要](../release-notes.md)

## 从Git检出后复现

在插件目录安装依赖并准备锁定适配器，再运行：

```sh
npm ci --ignore-scripts
npm run prepare:adapters
npm run typecheck
npm run test:plan
npm run test:report -- --release
```

Linux上需要bwrap及用户/PID/网络命名空间。测试用临时home、临时Git仓库和loopback；隔离不成立直接失败，不使用真实用户配置或付费API。配置/测试快照位于包内tests/plan-r2，旧计划位于tests/plan；运行已提交的测试不需要额外的规划工作区。

定向运行示例：

```sh
node scripts/test-isolated.mjs tests/review-fixes.test.ts
node scripts/test-isolated.mjs --test-name-pattern 'opinion-request-timeout' tests/r2-workflow-boundaries.test.ts
```

定向参数须指向包内真实文件；缺文件、零执行或零断言不能作为验证通过。全量报告每30秒输出进度，必须等最终退出码和摘要，不把中途计数当结果。

## 三种覆盖口径

- 测试：实际执行、断言、失败/取消/跳过和清理结果。
- 命名验收：每个AC变体须有当前source/plan、实际file/name、非零断言和observer工件；Scenario缺口由AC映射推导，不自动证明完整语义。
- 代码观测：code-coverage.json按原生产路径剔除夹具/修改副本，仅包含测试worker观测；原生Pi子进程未完整汇总，complete=false，不得引用为全产品覆盖率。

ready表示测试和映射门槛通过。发布前还需按变更内容审查实际使用路径、默认配置和失败组合；不能因数字齐全跳过语义审查。最近摘要见发布说明，原始工件只在执行机器生成。

## 工件与检查点

每次运行写入test-results下的新目录，包含report.json、tests.tap、records和代码覆盖工件。失败运行保留；不把失败文件覆盖为重跑成功。test-results默认不随Git同步，因此公开文档不把这些本机路径当作必要阅读链接。

完整、无skip的运行通过后可在同一源码目录执行：

```sh
node --experimental-strip-types scripts/evidence-checkpoint.ts test-results/<runId>/report.json
```

它核对当前源码摘要、原始发现/执行记录、TAP、验收工件和计划，再更新机器检查点。旧检查点有备份；发布摘要可记录runId和hash供追溯，但没有原始工件的读者不能仅凭摘要独立验真。

## 具体服务报告

`node --experimental-strip-types scripts/recovery-report.ts /absolute/input.json`只读取已有观测，不发请求。输入类型在src/evidence/recovery-acceptance.ts；工件须存在，记录区分注入、loopback和服务真实来源。绑定、版本、profile、请求上限和终态必须匹配；smoke成功只证明可用性，不能证明长任务恢复或实际收益。该入口没有Qwen品牌前置条件。

此目录其余带日期的审计和旧矩阵是开发历史材料，不能覆盖当前发布摘要或被当作新源码的通过证据。
