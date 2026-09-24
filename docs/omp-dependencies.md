# OMP 依赖锁与维护

OMP 使用固定官方 standalone，管理器不安装系统 Bun/Node、不运行上游安装脚本。当前固定 v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`；来源核对见 [来源证据](../specs/002-manage-omp-config/evidence/source-provenance.md)。源码及校验清单核对不代表二进制或账号已验收。

## 完整锁

`locks/omp/manifest.json` 保存不可变 commit 源码归档和四个平台官方资产的 URL/SHA256、上游材料摘要、本地资源清单、包入口/许可/兼容版本与树摘要，以及实际所需解释器要求。`locks/omp/upstream/` 保存完整 `bun.lock`、来源记录、MIT LICENSE、完整第三方说明及 NOTICE。

原样记录 Bun lock 是为了保留源码依赖解析身份；它不声称能从官方二进制反推出可重复构建结果。不同的 commit 归档、tag 归档与 release 二进制各有独立摘要，不相互代替。

本地资源按实际字节及执行位记录；锁内清单与当前来源完整比较。新增、删除、改动资源或修改入口都需要重新 lock。首版扩展不允许未闭合的第三方依赖，也不通过 `npx`/`uvx` 自动获取 MCP 程序。

## 安装、启动与修复

日常机器消费已经审阅的正式锁：

```sh
./agentcfg --local /private/local.toml --profile omp-default sync
./agentcfg --local /private/local.toml --profile omp-default apply
```

`sync` 只操作该 agent/profile 的私人 cache。按内容寻址的下载缓存通过摘要校验后，可以离线复用；缺少缓存时仅下载锁中指定来源。运行包位于 `<cache>/runtimes/<lock-and-platform-identity>`，不在实例 HOME 中，因此先 sync 再首次 apply 不会接管一个预先创建的原生环境。

所有文件先写入私人 stage，核对正文、执行位、目录形状、入口与 receipt 后激活。更新锁得到另一内容身份，已部署配置仍指向原身份，不会自动跟随新包；需要显式审阅并 apply。损坏包修复使用排他包租约，正在运行的包受共享租约保护。

receipt 记录实际平台、锁身份、来源及二进制摘要、安装路径和资源摘要。本地 Python MCP 使用已经准备的管理器 Python；receipt 固定其规范绝对路径、精确版本及可执行文件内容摘要。运行时重新核验，不从 PATH 寻找替代解释器或全局 OMP。

包激活日志位于 cache，目录更新包含 fsync；异常恢复原目录，进程中断后的日志由下一次显式 sync 恢复。发现无法核实的日志或新包时保留现场。配置 pending 属于实例部署事务，由 apply/rollback 恢复，两类恢复不混用。

## 维护更新

```sh
./agentcfg lock --agent omp
```

这是修改解析结果的显式入口。审阅变更中的完整上游材料、四平台来源/摘要、本地包正文及许可，然后 sync、plan、apply。固定宿主版本升级还需要更新适配器能力和发现清单，不能只替换下载 URL。

配置 rollback 只恢复上一配置，不降低宿主版本、不迁移认证数据库；旧配置与当前可核验运行包不匹配时，后续 run 返回 5，需显式处理依赖与部署。

## 平台和证据

目标为 Linux glibc x64/arm64 与 macOS x64/arm64；musl、Windows 和未知架构返回 5。隔离平台替身只验证选择和拒绝规则。当前没有真实 OMP smoke、真实账号或 macOS 环境通过证据，详见 [基础测试](../specs/002-manage-omp-config/evidence/foundation.md)；后续支持声明按实际平台独立记录。
