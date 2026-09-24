# 通过 agentcfg 查看 OMP 用量

原生与受管两种入口已实现并通过隔离验收。本页说明命令模式及固定版本上游能力，实际证据见[usage隔离验收](../specs/002-manage-omp-config/evidence/us4.md)；真实账号结果尚未验证。

## 原生模式

不提供管理器 `--profile`、`--local`、`--machine` 时，使用 PATH 上的 OMP，保留调用者环境和工作目录。此模式不加载 rotom 的机器配置、SecretStore 或部署状态。

```sh
./agentcfg usage --json
./agentcfg usage -- --provider openai-codex --json
```

命令后的参数原样传给 `omp usage`，最多剥离一个起始 `--`。例如 `usage --profile ...` 是否有效由原生 usage 语法决定，管理器不会把它重排成全局 profile 参数。原生环境中的 OMP_PROFILE 等选择也由 OMP 解释。

## 受管模式

提供管理器 `--profile ID` 时，使用该 OMP 配方已部署的独立身份和锁定二进制。全局选择参数须放在 `usage` 之前。

```sh
./agentcfg --local /private/local.toml --profile omp-default usage -- --json
```

底层 argv 为 `<locked-omp> --profile <native-name> usage <tail>`，cwd 为实例 HOME。它沿受管 run 的所有权、pending、配置引用、来源与运行包门禁，持有相同实例锁；与同实例 run 互斥。查询只使用该身份所需环境及原生保存的认证，不因无关 provider/MCP secret 缺失而阻塞。

只给 `--local` 或 `--machine` 而不给 `--profile` 返回 2；显式选择 DSH/Pi 配方也返回 2。管理器不猜测目标配方、不自动选择 OMP，也不跨受管 profile 聚合。

## 输出和副作用

两种模式直接继承原生 stdout/stderr，机器输出前后不附加管理器说明；原生退出码保留，信号沿 `128 + signal` 约定。无账号、不支持、部分失败、窗口与缓存含义由 OMP 定义，缺失数据不改写成零。

显式查询可能产生原生网络请求、缓存写入和认证刷新；不自动安装、部署、交互登录或调用模型。原生模式保留上游自身的认证共享行为；受管模式则禁用 broker/gateway 并使用独立 HOME。

| 情况 | 处理 |
|---|---|
| PATH 没有 OMP | 原生模式返回 5；显式准备程序后再查询 |
| 受管运行包缺失或损坏 | 返回 5；显式 sync 修复，并按需要 apply 匹配配置 |
| 实例活动、归属不符或 pending | 返回 4；等待实例退出或处理报告后执行 apply/rollback 恢复 |
| tail 尝试覆盖受管身份、来源 | 返回 2；使用管理器前置 profile/cwd 选择 |
| 原生未登录或 provider 不支持 | 保留原生输出与退出码；不将它改写成成功额度 |

## Provider 范围（2026-09-24 复核）

固定 OMP v18.3.0 usage registry 注册 20 个 provider。本需求关注的 `openai-codex`、`kimi-code`、`zai` 都在其中；这不是 rotom 对这些服务的真实账号通过声明。[固定 registry 源码](https://github.com/can1357/oh-my-pi/blob/62bc57be1b03ef0802a33cf7f5f530e534527531/packages/ai/src/usage/registry.ts)

`zai` 使用国际 Z.AI 服务，不能代表国内 `zhipu-coding-plan`；固定 OMP registry 没有后者。智谱官方 [Coding Tool Helper](https://docs.bigmodel.cn/cn/coding-plan/extension/coding-tool-helper) 列出了用量查询插件，因此不能断言国内方案没有用量 API。本次尚未核实该插件接口和 OMP 集成；agentcfg 不抓取 Cookie，也不新增独立采集器。

来源、路径和限制详见 [usage 来源复核](../specs/002-manage-omp-config/evidence/usage-sources.md)。真实账号窗口/缓存/部分失败属于独立授权验证，当前未执行。
