# OMP 原生 worktree clone 审查验收

本次保留官方 `worktree.clone`，让可静态分析的原生 `git worktree add` 命令把
clone 的可能效果交给权限审查模型。原始命令和参数仍由公开 `ctx.invokeTool` 委托给
官方 OMP 执行。没有修改上游源码、官方二进制或宿主内部接口。

## 验收标准

- 静态支持的 clone 命令进入模型审查，原始参数对象保持不变；不新增自动允许规则。
- 审查同时披露分支创建/重置、可能复制本地和 ignored 数据、backend 回退、子 CLI
  重新解析配置，以及 post-checkout hook 执行。文件集合、hook 和子配置未被核验。
- 原生 deny/prompt、未知语法、取消、会话/设置/入口漂移保持原有拒绝或人工边界。
- legacy `permission_bash` 只执行 raw shell，不借用原生 clone 的效果或覆盖声明。
- 官方编译版加载、真实临时 worktree 创建和原生 deny 必须单独验证。

## 已观察到的结果

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| 初版独立插件及实际公开 helper 合成测试 | 513 passed，56,577 assertions | 离线、临时 HOME，模型与委派为假实现 |
| 最终插件及公开 helper 合成测试 | 518 passed，56,629 assertions，19 files | 增加编译版入口与纯改写探测的回归 |
| 最终官方 SDK 类型检查 | exit 0 | 使用固定 v18.8.6 声明；不代替编译版实际加载 |
| 冻结历史场景与严格语法验收 | 71 passed，11,784 assertions | 不执行样本命令，保留冻结预期 |
| kernel 与权限管理器回归 | 117 passed，7 skipped | 临时 HOME、假子进程；7 项为已退休宿主补丁测试 |
| 初版真实官方编译宿主 | 失败：`native-runtime-load` | 启动后即保守退回人工；无模型请求、命令或 hook 执行 |
| 编译宿主逐项 literal import 诊断 | 原有五个模块及三个新增 tools 模块通过；`subprocess/worker-client` 失败 | 正常公开扩展加载；无模型、helper 或命令调用 |
| 最终官方 v18.8.6 宿主 allow | exit 0；审查/原生委派/执行各 1，人工 0 | 真实临时 worktree、分支、Git log 和无害 post-checkout hook |
| 最终官方 v18.8.6 宿主 deny | exit 0；审查/委派/执行各 0 | 返回 `NATIVE_DENY`，worktree 与 hook 均未发生 |

初版失败揭示源码包 exports 与编译版可加载模块并不完全相同，不能用源码测试或
SDK 类型检查替代官方编译宿主验收。修复已移除不支持的入口模块，使用公开
`pi-utils.isCompiledBinary()` 和仓库自有的当前入口核验。它只支持受管 compiled CLI，
不实现源码/SDK 入口或 PATH/unlink fallback。可选 clone 模块加载失败只降低 clone
覆盖，普通原生工具审批继续可用。

入口路径及文件身份进入 capture/recheck。入口不可用时，公开 rewrite helper 的空 argv
调用只用于比较是否可能改写，其输出不形成实际执行命令或 plan，也不交给审查模型。
普通动态命令保留原语法门控，后置 clone 候选保留人工及未知效果披露。该分支经独立
复核发现并修复后，本范围无未闭合 P1/P2。最终宿主加载、模型接线和两条执行路径均通过。

宿主 fixture 使用临时 HOME、私有网络命名空间和本地假模型服务；编译版保持官方
SHA-256 `877acdc48384b80fe4c083b1e610433d28922dd9fccde9ea430aaace8765b19b`。
allow 的真实模型输入包含原命令、实际入口 argv、七个文件身份字段、改写效果及未知
范围。`/permission-control status` 为 smart/configuration ready/coverage ready，主审 1、
人工 0。deny 没有 reviewer 请求或原生执行。外部模型请求总计 0。

内存文件系统的真实 clone 尝试返回 `FICLONE` errno 95，官方回退普通 checkout；
ignored 哨兵未复制。仓库磁盘上的两个自有小文件也经独立 ioctl 探测返回 errno 95。
这证明预先披露的回退路径，不能记成快速复制或 ignored 数据复制成功。复制成功路径
因文件系统能力不足未验证；未修改官方实现或本机 backend 配置来掩盖限制。

完整隔离证据保留在仓库忽略目录 `.cache/omp-worktree-context-20261009/host/` 的
`results.json`、`run-final.log`、`artifacts/` 和 `cleanup-final.json`。测试临时树及自身
进程已清理；这些含合成配置的运行文件未加入 Git。验收记录及生产测试纳入 Git。

公共官方锁严格回读 193 项资源通过：`04b20a97bf521983ebf2f166ddb4a02053a0ee9f965156b3cf8ff0df6027bcb3`；
插件树摘要：`f3d9fcb5281a6dec32ddf91d20bede9d95edcb96e38d8a96e4a2c9b339ab453f`。

## 不构成通过的范围

本次模型服务是私有网络命名空间内的本地假服务；固定 allow 只验证接线，不证明真实
审查模型一定允许 worktree 命令。真实账号、密钥文件、会话日志和付费模型均未读取
或调用。文件检查到执行之间的竞态，以及子进程重新读取配置、hook 和复制文件变化，
不由父设置指纹完整保护。Cursor K3 备用链警告是独立问题，本次没有修改该策略。

## 任务状态

- 已完成：静态 dispatch plan、效果披露、既有边界回归、编译版入口兼容修复、独立复核、锁回读及两项真实隔离宿主验收。
- 已完成：本机部署；公共修复已提交 `4f0fc3a` 并从 worktree 快进合入本地 main。
- 进行中：无本轮必需工作。
- 失败待决策：无；初版加载失败及复核问题已有修复，仍保留失败记录。
- 环境未验证：快速复制/ignored 复制成功路径、真实 reviewer 风险质量、其它平台、用户真实项目中的 clone 行为。

本机 manager 的 `sync` 安装新身份 `04b20…bcb3-linux-x64`。`plan` 为 2 处更新、
0 漂移、0 冲突；第一次 `apply` 因活动实例退出码 4 拒绝，未自动终止该实例。
中途 `doctor` 的已部署依赖 damaged 由当前锁与旧部署 identity 不匹配触发：
`OmpBackend.status` 在该分支未检查旧包文件内容，不能据此判断旧包自身损坏。

用户明确回复已退出后，再次 `apply` 退出码 0、完成 2 处更新。最终 `doctor` 退出码 0、
基础部署离线就绪，当前和已部署依赖均 installed，漂移/冲突/待变更/待恢复均为 0。
账号登录及真实模型服务未验证；离线就绪不能替代在线通过证据。

本机操作仅由 manager 在内部按已有授权加载配置与凭据；代理未查看、打印、复制或
哈希密钥正文，未读取真实账号数据库或会话日志。实现与宿主验证分配给 executor，
独立证据与稳定 diff 复核分配给 scout；角色配置分别为 gpt-6.1-sol/medium 与
gpt-6-luna/high，工具未另行披露底层实际执行模型身份。
