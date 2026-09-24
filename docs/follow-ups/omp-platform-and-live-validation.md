# OMP 后续平台与真实账号验证（不属于 spec 002）

2026-09-24，用户明确将 macOS 验收、Linux arm64 实机、真实登录、真实 usage 和指定模型调用移出
`002-manage-omp-config`。这些项目均为 **未验证 / 待环境 / not-run**，不阻塞 spec 002 关闭，
也不计入该 spec 的通过范围。Linux x64 无账号真实 smoke 已完成，但不能替代下列任何项目。

## 后续条目

| 后续编号 | 原任务 | 状态 | 内容 | 执行前提与独立授权 | 通过条件 |
|---|---|---|---|---|---|
| OMP-F01 | T061 未覆盖部分 | 未验证 / 待环境 | Linux glibc arm64 实机九行宿主 smoke | 提供 arm64 机器；单独授权真实宿主执行和必要的官方资产获取；使用新建临时仓库、HOME 与受管 `omp-validation` | 锁定 arm64 发布字节及 SHA/receipt 一致；validate/render/plan/sync/apply 成功；真实宿主发现九行配置，本地 MCP 完成受控调用；不登录、不查 usage、不调用模型；记录退出码、平台和脱敏证据 |
| OMP-F02 | T062 | 未验证 / 待环境 | macOS x64 与 arm64 分架构实机九行宿主 smoke | 分别提供对应 macOS 机器；每个架构单独授权真实宿主执行和必要资产获取；不能用另一架构或 Linux 结果替代 | 每个架构分别满足 F01 的锁、部署、九行发现、本地 MCP、零自动安装和证据要求；未执行的架构继续保持未验证 |
| OMP-F03 | T063 | 未验证 / 待环境 | 新受管 profile 显式登录 `openai-codex` | 对应平台宿主已通过；提供可用账号和新 profile；单独授权登录及其认证副作用 | 仅执行受管 `run omp -- login openai-codex`；认证只写新隔离 HOME；旧 profile 哨兵不变；记录脱敏身份、命令与退出码，不复制或提交认证内容 |
| OMP-F04 | T064 | 未验证 / 待环境 | 原生与受管模式的真实账号 usage | 对应客户端、账号和 provider 可用；单独授权网络、认证刷新、缓存副作用和 usage 查询 | 原生与受管命令分别保留真实 stdout/stderr/退出码；核对选中 profile、窗口、缓存、不支持和部分失败语义；不跨 profile 汇总，不把无账号输出算通过 |
| OMP-F05 | T065 | 未验证 / 待环境 | 指定 provider/model 的最小真实生成调用 | 用户明确指定 provider/model、账号、平台和预算；单独授权模型请求 | 通过已验证受管身份完成一次最小请求；记录实际路线、精确模型、退出码和脱敏结果；不记录 secret，不推定其他模型、provider 或平台通过 |

每项授权彼此独立。授权宿主 smoke 不包含登录、usage 或模型请求；登录授权也不自动包含 usage 或模型调用。
缺机器、账号、预算或授权时保持 `未验证 / 待环境`，不得以隔离测试、源码检查、假进程、其他架构
或退出 0 代替真实证据。

## 恢复入口

- [OMP quickstart 的真实原生证据流程](../../specs/002-manage-omp-config/quickstart.md)规定临时仓库、隔离
  HOME、正式锁、真实发布字节、授权边界和证据模板。未来执行时应从该流程重新核对当时源码、锁、
  平台、profile 与资产，不直接沿用旧临时目录。
- [Linux x64 已通过证据](../../specs/002-manage-omp-config/evidence/linux-smoke.md)及其
  [结构化观察](../../specs/002-manage-omp-config/evidence/linux-smoke-observations.json)只证明
  2026-09-24 的 Linux glibc x64、固定 OMP v18.3.0 和无账号九行 smoke。它是未来证据格式参考，
  不是 F01–F05 的通过证据。
- [OMP 支持状态](../omp-support.md)记录当前平台与账号边界；后续完成任一项目后，再按其职责同步支持矩阵和新证据文件。

恢复执行时为对应项目建立独立证据记录，写明日期、平台/架构、锁和二进制摘要、授权范围、命令、
退出码与断言。失败、重试和环境不足分别保留；秘密与完整认证输出不得进入仓库。
