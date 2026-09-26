# OMP 依赖锁与维护

OMP 使用固定官方 standalone，管理器不安装系统 Bun/Node、不运行上游安装脚本。当前固定 v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`；来源核对见 [来源证据](../specs/002-manage-omp-config/evidence/source-provenance.md)。源码及校验清单核对不代表二进制或账号已验收。

## 完整锁

`locks/omp/manifest.json` 保存不可变 commit 源码归档和四个平台官方资产的 URL/SHA256、上游材料摘要、本地资源清单、包入口/许可/兼容版本与树摘要，以及实际所需解释器要求。`locks/omp/upstream/` 保存完整 `bun.lock`、来源记录、MIT LICENSE、完整第三方说明及 NOTICE。

原样记录 Bun lock 是为了保留源码依赖解析身份；它不声称能从官方二进制反推出可重复构建结果。不同的 commit 归档、tag 归档与 release 二进制各有独立摘要，不相互代替。

本地资源按实际字节及执行位记录；锁内清单与当前来源完整比较。新增、删除、改动资源或修改入口都需要重新 lock。首版扩展不允许未闭合的第三方依赖，也不通过 `npx`/`uvx` 自动获取 MCP 程序。

## 安装、启动与修复

日常机器消费已经审阅的正式锁：

```sh
./agentcfg --local /private/local.toml --profile omp-kernel sync
./agentcfg --local /private/local.toml --profile omp-kernel apply
```

`sync` 只操作该 agent/profile 的私人 cache。按内容寻址的下载缓存通过摘要校验后，可以离线复用；缺少缓存时仅下载锁中指定来源。下载流先进入同一 cache 的 `.part`，对瞬态超时、连接错误、HTTP 408/429/5xx 和短读最多尝试三次；严格核对 206 `Content-Range`，遇 200 安全地从零重写。完整长度及 SHA256 匹配后才原子发布。运行包位于 `<cache>/runtimes/<lock-and-platform-identity>`，不在实例 HOME 中，因此先 sync 再首次 apply 不会接管一个预先创建的原生环境。

所有文件先写入私人 stage，核对正文、执行位、目录形状、入口与 receipt 后激活。更新锁得到另一内容身份，已部署配置仍指向原身份，不会自动跟随新包；需要显式审阅并 apply。损坏包修复使用排他包租约，正在运行的包受共享租约保护。

receipt 记录实际平台、锁身份、来源及二进制摘要、安装路径和资源摘要。本地 Python MCP 使用已经准备的管理器 Python；receipt 固定其规范绝对路径、精确版本及可执行文件内容摘要。运行时重新核验，不从 PATH 寻找替代解释器或全局 OMP。

包激活日志位于 cache，目录更新包含 fsync；异常恢复原目录，进程中断后的日志由下一次显式 sync 恢复。发现无法核实的日志或新包时保留现场。配置 pending 属于实例部署事务，由 apply/rollback 恢复，两类恢复不混用。

## 维护更新

```sh
./agentcfg lock --agent omp
```

这是修改解析结果的显式入口。审阅变更中的完整上游材料、四平台来源/摘要、本地包正文及许可，然后 sync、plan、apply。固定宿主版本升级还需要更新适配器能力和发现清单，不能只替换下载 URL。

配置 rollback 只恢复上一配置，不降低宿主版本、不迁移认证数据库；旧配置与当前可核验运行包不匹配时，后续 run 返回 5，需显式处理依赖与部署。

## 下载中断诊断

下载中断后，保持同一个 local/profile 和 cache 路径，再次执行同一 `sync`。安全 partial 会保留；服务端支持正确 Range 时从现有进度续传。已完整且摘要正确的 cache 不访问网络；损坏的完整 cache 会移除并重新获取一次。

错误信息只包含 `category`、`attempt` 和 `progress`，不回显可能含凭据的 URL。可按以下顺序处理：

1. 检查私人 cache 所在 Linux 文件系统的可用空间、目录属主和 0700 权限；WSL 不要默认使用 `/mnt/c`。
2. 对 `timeout`、`connection`、`http-408`、`http-429`、`http-5xx` 或 `short-read`，保留 `.part` 并重跑 `sync`。单次命令已有三次有限尝试，不会无限重试。
3. `content-range` 或 `range-reset` 表示响应与请求的安全续传边界不一致；记录错误类别、平台和网络/代理环境，再排查中间代理或服务端。不要手工拼接 partial。
4. `integrity`、`size-limit` 或 `cache-write` 需要检查锁定资产、磁盘和权限。不要手工改摘要、替换锁定 URL 或把 `.part` 重命名为完成文件。

下一次 `sync` 复用同一内容寻址 cache；删除 cache 会失去续传进度，通常不应作为第一步。

这里的下载诊断针对正式锁中的 OMP standalone 和锁维护输入。`omp-kernel` 模型会话访问的是公共 catalog 登记的企业 TokensFlow 网关；该网关不可达、key 无效或 provider 返回错误时，不应归类为 `sync` 下载故障。网关端点需要变更时，应通过私人 local 的 provider `base_url` override 明确审阅兼容性，不能把当前模型 ID 和协议暗自换到厂商官方端点。

## 平台和证据

目标为 Linux glibc x64/arm64 与 macOS x64/arm64；musl、Windows 和未知架构返回 5。隔离平台替身只验证选择和拒绝规则。Linux glibc x64 已有[真实无账号 smoke](../specs/002-manage-omp-config/evidence/linux-smoke.md)；WSL、Linux arm64、macOS、真实账号和真实模型调用不能由该证据推定通过，后续支持声明按实际平台独立记录。
