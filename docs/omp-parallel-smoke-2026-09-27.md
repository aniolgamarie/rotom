# OMP 同配方并行受管会话验证

日期：2026-09-27。固定宿主 OMP v18.3.0，官方 standalone SHA256 为 `d2fdaa29affe96e596eb9c78d42f548f1f291df28608631bcc00750a84b94bc3`。本次验证使用当前工作树的共享运行租约改动和 `omp-default` 配方。

验证目录为 `/tmp/rotom-omp-shared-20260927`。真实宿主通过 bubblewrap `--unshare-net` 运行；仓库只读，只有临时目录可写，现有 `/root`、`/home` 被遮蔽。local 文件只含虚构机器 ID 和临时路径；没有登录、模型请求或现有账号数据。

1. `validate`、从已校验本地缓存执行 `sync`、首次 `apply` 均退出 0。
2. 在同一受管 `omp-default` 身份下，分别以 `workspace1`、`workspace2` 为 cwd 启动两个独立 PTY 中的 `agentcfg run omp`。两个宿主同时进入输入界面，分别回显 `managed_first_probe`、`managed_second_probe`，没有串入对方输入。
3. 两个会话活动时另执行 `apply`，收到 `OMP实例已有活动进程`，退出码 4。
4. 两个会话清空输入后使用 Ctrl+D 退出，退出码均为 0。再次执行 `apply`，退出码 0、`changes=0`。

这证明当前管理器路径允许同配方的两个独立前台会话，并保留配置修改互斥。验证不涵盖真实账号、模型请求、长时间并发或两个进程同时恢复/编辑同一原生会话；受管入口仍拒绝原生 `--resume` 等恢复参数。
