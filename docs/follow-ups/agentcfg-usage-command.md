# AGENTCFG-F01：agentcfg usage薄封装已实现

状态：2026-09-24完成已批准的薄封装软件范围和隔离验收；真实账号usage未验证，已转独立遗留 [OMP-F04](omp-platform-and-live-validation.md)（原 T064），不再属于 spec 002 完成范围。此次不宣称国内智谱额度、任何真实账号或任一平台宿主已经通过。

`agentcfg usage`无前置选择器时，调用PATH上的`omp usage`，保留cwd、完整环境、参数、二进制stdout/stderr和原生退出码，不加载rotom机器文件或SecretStore。前置显式OMP `--profile`时，使用已部署独立HOME/native profile和锁定二进制，经过相同实例/状态/包门控。local/machine未配显式profile以及非OMP配方返回2；找不到程序/缺包返回5。

两种模式至多剥离一层前导`--`。原生无账号、不支持、部分失败、缓存和窗口含义不被重写，不补零、不自创provider别名、不跨profile聚合。受管查询不解析普通会话的无关API/MCP secret。查询可能发生原生网络、缓存写入和认证刷新，不自动安装、登录或生成模型。

实现与验收入口：

- [usage使用说明](../omp-usage.md)：两模式、命令、副作用及错误处理。
- [隔离测试证据](../../specs/002-manage-omp-config/evidence/us4.md)：CLI选择、完整参数/流/退出码透传、活动锁与秘密边界。
- [支持状态](../omp-support.md)：软件、宿主与账号证据分别列示。

固定OMP v18.3.0 usage registry有20个provider，其中包括`kimi-code`、`zai`和`openai-codex`。`zai`是国际Z.AI，固定registry没有国内`zhipu-coding-plan`，两者不能混同。[固定源码与官方资料复核](../../specs/002-manage-omp-config/evidence/usage-sources.md)

智谱官方[Coding Tool Helper](https://docs.bigmodel.cn/cn/coding-plan/extension/coding-tool-helper)列出用量查询插件，不能因为网页失败或索引缺项断言没有API。该插件接口及OMP集成尚未核实。本次不抓Cookie、不新增独立采集器；后续优先核实上游支持并透传实际结果。

原始决策为2026-09-24批准的方案A：给OMP现有usage提供统一入口。该软件范围已完成，未执行的真实账号验证不能被隔离假输出或无账号smoke替代；DSH Cursor认证和secrets同文件缺陷保持原状态。
