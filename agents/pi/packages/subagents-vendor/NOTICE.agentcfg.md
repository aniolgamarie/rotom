# agentcfg 派生构建说明

来源：`https://github.com/tintinweb/pi-subagents`，固定提交
`e955e29c51b7a6cce37e1108cd2d6c57a77e151c`，MIT 许可证见 LICENSE。
派生版本 `0.19.0-agentcfg.1`，固定 Pi 0.84.4。

- 普通 session、managed-process、短期 external 任务使用同一 AgentManager，执行并发上限 2。
- 同进程 listener 和专用准入的长期 MCP stdio 服务作为 resource，由该 manager 持有生命周期；最多 16 个活动资源。
  resource 只能通过内部 executor 入口登记，普通 Agent/RPC 无法指定此分类；MCP 服务仍受同一 supervisor 监督并独立限额，关闭未知仍阻止会话切换。
- 已知普通 IO 与同进程资源不被误判为 Task Keeper 模型工作；managed、未知执行及未知取消继续阻止普通辅助模型调用。
- 禁用上游 scheduling、workflows、nesting、bypassQueue 和自建 worktree；配置由 agentcfg 管理。
- 只加载 launcher 编译的明确角色清单；受管角色不进入普通 Agent/RPC 注册表。
- 模型必须精确匹配 provider/model；不支持模糊匹配或 provider fallback。
- managed-executor-v1 通道为 `agentcfg:subagents:managed:*`；协议及私人事务存储由
  `@agentcfg/pi-runtime` 提供。worker/transport 不可用时能力检查失败，不按版本号假定就绪。
- 受管结果只能经 owner 对应的 get_result/consume；取消应答不视为物理终止，未知工作占位保留。
- 默认 test 只运行隔离 mock。上游真实宿主测试必须独立授权并传入 --allow-host。

原始 README/docs/test 作为来源说明与待适配用例保留；其中上游安装命令和默认行为
不适用于 agentcfg 运行包。统一部署入口为仓库根目录的 agentcfg。
补丁和逐文件身份位于相邻 subagents-patch/；没有原生或账号通过证据。

The external executor v2 adapter uses the same manager and durable owner checks; its source is in @agentcfg/pi-runtime. Native/backend certification remains separate.

普通 Web 辅助模型可绑定所属资源操作；该关联仅允许同一操作继续其已授权 IO。
模型仍占任务槽，不允许其他操作、managed/session 执行或取消未知记录借用该关联绕过 helper 门控。
