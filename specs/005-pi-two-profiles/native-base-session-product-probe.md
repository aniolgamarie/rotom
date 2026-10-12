# Base 正式安装 CLI 会话组合验收

2026-10-11，按用户允许自主判断低风险真实测试的授权执行。使用原正常安装的 Base、固定官方 SDK 1.0.1、原 `agentcfg run` → Host/Socket → official launcher → 原 RPC mode；未替换 SDK 工厂、ModelRuntime、Host 或准入方法。

固定运行身份是 lock `1c138ac06ba91fbb676341ca848cf01af9b8bb322e2dbace1a6f8c22df9e2d7d`、runtime `302840f90d1b00ed059dfd79117ef02433762807df71ec030f3576d90e9081ed`。对应完整来源、运行包与安装证据在 `base-formal-install-review01/final-stable/`。仓库后续两 profile 锁已变为 `0231d0a9f6a1aee642413c9ac10f3b05bbf56e29fa2f49e2ef71b80152521a2f`，本测试不签发该新身份资格。

## 隔离与实际入口

外层 bwrap `--unshare-all`、只读系统/候选源码/运行包、`env={}`，仅已准备的自有临时 Base 账号/项目目录可写。passwd/group 指向该合成账号。模型服务器只在外层网络 namespace 的 localhost 监听，使用固定合成 key/模型；不读取真实账号、不外发网络、不调用真实模型或部署用户环境。

自有 guest 从原管理入口启动两个先后独立 CLI：

```text
agentcfg --local <自有临时 local.toml> --profile pi-base run --cwd <自有项目> -- --mode rpc --thinking off
```

通过原公开 JSON RPC 发送 `get_state`、`prompt`、`get_messages`、`get_entries`、`fork`、`compact`、`switch_session`、`get_session_stats`；不加载或改写 SDK 私有接口。stdin EOF 后等待原 CLI 自然退出，原监督者按自己的终止证据回收租约。

## 观察与结果

最终材料为 `.cache/pi-two-profiles/run-20261004/base-native-session-product-review04/`。outer exit0、stderr0、capture_failed=false；两个原 CLI 均 exit0。合成 HTTP 边界共7次真实请求、max_inflight=1：两次原会话提示、分支提示及拒绝工具后响应两次、一次真正压缩、重开提示及拒绝工具后响应两次。

| 场景 | 独立观察 |
| --- | --- |
| 状态/历史查询 | 原 RPC success，模型计数不增加 |
| 两轮历史 | 原 native entries 与 messages 保留两次用户/模型消息 |
| 公开分支 | native ID 与文件不同，原文件存在；分支请求包含首轮 marker，不含被分出去的第二轮 marker，分支动作零模型发送 |
| 手动压缩 | 原 SDK 发出 compaction_start/end，公开 compact success；真实 session JSONL 恰有一条 compaction entry |
| 完全关闭/新 CLI 重开 | 原进程自然 exit0，新 CLI 公开 switch_session 恢复同一分支 native ID 和所选模型，切换零模型发送 |
| 压缩恢复后的提示 | 原模型请求包含重开 marker 和固定 task/artifact/failed 引用 |
| 分支/重开后的权限 | 两次真实 SDK read 调用均 `isError=true`、固定 `PERMISSION_DENIED`；自有 `.env` 哨兵不变，Provider 请求不含哨兵内容。工具反馈跨请求重复出现不算新执行 |
| 原生命周期 | 最后两条原 Host lease 为 reclaimed，原 termination_evidence.verified=true；所有原记录 protected_count=0 |

原 session 文件按公开 session header ID 验证并保存独立副本与 SHA。只读 observer 通过原 `PiBackend.read_lock/runtime_identity` 与 sealed `inspect_runtime` 重验固定安装身份，不刷新账号或启动后端。

第一轮失败保存在 review01：合成历史太短，原 SDK 明确返回 `Nothing to compact (session too small)`，outer exit1。review02 增长合成输入后真实压缩/重开通过；review03 补固定任务/产物/失败引用保持断言后通过；review04 补恢复后的真实权限负例后通过，各轮计数不相加。没有修改 SDK 阈值或将失败样本覆盖成通过。

摘要内容由固定 synthetic Provider 返回；这里验证原生持久化和恢复，不证明真实模型的语义摘要质量。尚未覆盖终端历史搜索、导出/交接、真实摘要质量、完整错误/保留清理矩阵或最新两 profile 锁安装身份，因此 T023 整体和产品 gate 保持开放。
