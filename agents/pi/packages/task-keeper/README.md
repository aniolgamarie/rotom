# Task Keeper · agentcfg 集成版

本目录的执行入口由 agentcfg 的 `pi-managed` 配方加载，版本 `0.2.0-agentcfg.1`。
源自冻结的 starter；出处见 [NOTICE.md](NOTICE.md)。以下原始文档保留业务语义和背景，
其中全局配置、独立安装、旧 subagents 补丁及原生测试命令不适用于当前部署入口。

当前使用 Pi 0.84.4、`@tintinweb/pi-subagents` 0.19.0-agentcfg.1 的唯一管理者、
独立 supervisor 与 fresh worker。`/orch init` 仅说明如何修改 agentcfg 配置。
参见仓库 `examples/pi-managed.toml`；模型、项目根、前台检查、第二视角必须显式绑定。

默认 `npm test` 只运行仓库隔离 mock，不启动 Pi、Codex 或真实模型。
`npm run typecheck` 检查生产源码；保留的旧宿主测试不计为新版通过证据。
原生与账号验证需另行明确授权，mock 不能证明平台支持。

---

# Pi Task Keeper

Task Keeper 是 Pi 的长任务扩展：按供应商/模型处理限流等待，记录整项任务的 token、轮次和费用，并提供带真实检查的候选工作树、可选第二视角和 Pi 内一次性定时。

插件默认禁用。加入 Pi 的包清单只表示可加载；启用及模型、项目检查绑定需要单独配置。普通统计分组、受管任务和预算是不同概念，不能用新建统计任务清空预算。

## 从这里开始

| 你的目的 | 阅读入口 |
|---|---|
| 安装、启用并跑通第一项任务 | [上手指南](docs/getting-started.md) |
| 理解 begin / fix、等待恢复、工作树和验收 | [工作原理](docs/architecture.md) |
| 日常命令、统计、定时和状态操作 | [使用手册](docs/usage.md) |
| 主 agent 规划、多模型分工及执行边界 | [多模型指南](docs/multi-model.md) |
| 配置字段、默认值、模型策略和套餐价格 | [配置参考](docs/configuration.md) |
| 没启动、BLOCKED、unknown、升级失败 | [排障指南](docs/troubleshooting.md) |
| 当前支持范围与验证结果 | [发布说明](docs/release-notes.md) |
| 文档覆盖哪些主题 | [文档地图](docs/documentation-map.md) |

这些文档和示例都位于插件包内，随 Git 源码一起维护，不需要本地规划目录或原始测试工件。

## 选择合适的入口

```text
/orch begin --group parser-fix -- 修复解析器
```

上面的命令只建立统计分组。下一条自然语言指令才让当前 Pi agent 做事；结束后用 `/orch usage <taskId>` 查看累计消耗，`/orch accept <taskId>` 记录用户认可。

```text
/orch fix --second-opinion -- 修复解析器并验证边界情况
```

受管 `fix` 自动建立统计记录，在候选工作树中实现、运行绑定的构建/测试和必要审查。开启第二视角后，B 独立读取证据并质疑；A 可以修改或举证，修改后重新检查。超过限额或仍有分歧时明确阻塞。

`/orch status <jobId>` 查看候选、检查与当前验收。插件不会自动把候选合并回原 checkout；暂停、停止、审批和采用候选的区别见[使用手册](docs/usage.md)。

## 运行条件

当前已验证组合：Linux、Node 24.1.0、Pi 0.84.4、固定补丁的 pi-subagents 0.63.0、direct 网络的 `openai-completions`。恢复/受管执行使用受控启动器；其他扩展、协议或执行模式需通过能力检查。具体供应商账号的实网认证独立于软件测试，没有必须使用 Qwen 的要求。

从插件目录安装锁定依赖：

```sh
npm ci --ignore-scripts
npm run prepare:adapters
```

然后按[上手指南](docs/getting-started.md)选择普通会话或受管配置。不要把新生成的示例覆盖到已有用户配置。

## 开发与验证

```sh
npm run typecheck
npm run test:plan
npm run test:report -- --release
```

测试需要 bubblewrap 和可用的用户/PID/网络命名空间。测试入口使用私有 home 与 loopback，不回退到真实用户环境。测试报告和本机状态不随发布文档分发；可复现命令、最近验证摘要及覆盖率口径见[测试说明](docs/testing/README.md)。
