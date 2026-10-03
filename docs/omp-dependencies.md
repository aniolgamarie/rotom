# OMP 依赖锁与维护

> 当前已按维护者要求改为官方宿主与独立插件，仓库实现及隔离验收完成；本机日常实例已按后续明确授权完成独立插件迁移（见验收 Phase 13）。下文 patched runtime/bridge 的构建和验收为历史记录，不继续构建发布，也不作为新插件通过证据。当前需求见[独立插件修订](../specs/004-omp-permission-control/standalone-plugin.md)。本机部署是否切换须单独登记。

OMP official 路径使用固定官方 standalone，管理器不安装系统 Bun/Node、不运行上游安装脚本。当前固定 v18.4.5 / `79808c3bf8f8cd9826decc63e3e18b13035f64f8`；来源和当前升级验收见 [v18.4.5 升级记录](acceptance/omp-upgrade-18.4.5.md)，v18.3.0 来源记录保留为历史证据。源码及校验清单核对不代表二进制或账号已验收。`omp-kernel` 同样使用 official，独立权限插件通过公开 API 加载。

## 完整锁

`locks/omp/manifest.json` 保存不可变 commit 源码归档和四个平台官方资产的 URL/SHA256、上游材料摘要、本地资源清单、包入口/许可/兼容版本与树摘要，以及实际所需解释器要求。`locks/omp/upstream/` 保存完整 `bun.lock`、来源记录、MIT LICENSE、完整第三方说明及 NOTICE。

原样记录 Bun lock 是为了保留源码依赖解析身份；它不声称能从官方二进制反推出可重复构建结果。不同的 commit 归档、tag 归档与 release 二进制各有独立摘要，不相互代替。

本地资源按实际字节及执行位记录；锁内清单与当前来源完整比较。新增、删除、改动资源或修改入口都需要重新 lock。首版扩展不允许未闭合的第三方依赖，也不通过 `npx`/`uvx` 自动获取 MCP 程序。

## 安装、启动与修复

### 当前：官方运行包与独立插件

`omp-kernel` 使用普通 `locks/omp/manifest.json` 的官方二进制和本地插件 `standalone.ts`；`sync` 不读取旧 patched manifest、构建材料或 patched asset。审批 sidecar 为 `permission-control.json`，原生 config 保持官方字段。`runtime_variant` 只接受 official，旧 patched CLI 参数与 builder 入口已退休。

主审显式 reviewer 优先，省略跟随当前执行模型；失败时显式 remote fallback 接替一次完整审查。本地 tiny 当前无公开接口，显示 unavailable。当前能力、日常迁移步骤与真实通过范围见[独立插件指南](../specs/004-omp-permission-control/quickstart.md)和[Phase 12 验收](acceptance/omp-permission-control.md#phase-12官方-omp-与独立插件2026-09-30当前交付)。

### 历史：Permission-control 补丁运行包（已退休）

以下身份与命令仅保存历史取证，不再执行或用于当前锁。

`omp-kernel`选择本地TypeScript扩展`omp-permission-control`和`permission-control-v1`运行包，默认smart。主审优先显式`reviewer_model`，省略才跟随会话；远程`remote_fallback_model`缺省GLM5.3Flash，只在主审运行故障/不支持时接替完整审批；最后installed-only tiny只ask/deny。有效allow/ask/deny不复审。这与执行模型重试及生成session title的tiny角色分别管理。

| 身份 | 本轮实际值 |
|---|---|
| official recipe | `60d399dd4b0a2f2265d117d17b9e566669b64ca1413d4dc0fac66487165b9521` |
| plugin tree | `4511e7cdb9efb312029acfff93f0f6fe73cc5c3c018325c25756f9fd7eea040d` |
| 0001 patch | `45a0fcbdd4092161cbc3c14ac8b40a323928cd4dc915538e2cbee7f6ead8e51f` |
| 0002 patch | `c34d02d19941e09ca507e67164f5b8d37a67e991b6ed96ab51dca2b67ece33da` |
| standalone SHA-256 | `0fe58d4af126d162979efe3188b0a11d3f35b4a52f01049d7c4ac8871b63fa86` |
| standalone size | 367318216 bytes |
| patched manifest | `dce490890453ccff4165ece76a460fb9cbf23756cdb553c3fd7fe8d72bbb815e` |
| build receipt | `f0716c84316192f349253d68247ba4bcfc455f41218816efe79675952df4a0ac` |
| combined runtime | `06e42249ac791b39fd66d7a5d30c5988742eea876fa38ba19178d6adf018ebe2` |

Phase 11 新资产已完成正式离线构建、锁/receipt核验和266项材料化及相关OMP回归（96.59s，无跳过）；core 291 pass / 1085 assertions，宿主检查见本轮记录。Linux glibc x64临时HOME真实standalone通过主审503一次→远程Anthropic完整审批一次→pwd成功结果一次，primary1/remote1/tiny0/human0，permit pending→consumed；new/resume、missing-plugin pre-spawn exit5及rollback通过。固定服务main2/primary-failure1/remote-review1，外部模型0，服务已停止。 见[宿主报告](acceptance/omp-permission-control-host-smoke.md)与[验收记录](acceptance/omp-permission-control.md)。T080历史240样本质量safe99/100、risk0/100危险allow、fault0/40allow仅绑定旧runtime；102/102额度已用尽，本轮不新增请求，GLM备用质量与真实Cursor目录未验证。

维护者先在独立目录准备并逐字节核验源码、Bun 和完整依赖缓存。准备缓存可能需要网络，但这是
单独显式维护步骤，不属于 build、sync、apply 或默认测试。构建入口的实际参数为：

```sh
.venv/bin/python agents/omp/build-permission-control.py \
  --build-inputs-lock agents/omp/patches/permission-control/build-inputs.lock.json \
  --source /prepared/commit.tar.gz \
  --tool-cache /prepared/tools \
  --dependency-cache /prepared/dependencies \
  --artifact-cache /private/permission-artifacts \
  --platform linux-x64 \
  --offline
```

`--source`、三类 cache、`--platform linux-x64` 和必写的 `--offline` 均由 CLI 强制；
`--build-inputs-lock` 缺省为上列仓库文件。构建器只接受 Linux glibc x64，核对 Bun 版本和摘要、
完整 cache 闭包、上游 archive/bun.lock、两份 patch 及共享 core 源码，再在 seccomp 禁止 INET 的
临时 HOME/XDG/OMP 环境中编译。它不运行产出的 OMP。`build-inputs.lock.json` 只记录原始上游、
工具和依赖材料，不引用 official recipe identity、receipt 或输出，因而没有摘要循环。

构建成功后，维护者用已有 receipt 和内容寻址资产发布独立 variant manifest：

```sh
./agentcfg lock --agent omp \
  --runtime-variant permission-control-v1 \
  --artifact-cache /private/permission-artifacts
```

该命令严格要求三个参数同时出现。它交叉核对实际资产、receipt、输入锁、patch、构建脚本、插件树、
ABI 和 official OMP identity；发布 manifest 失败时恢复旧 receipt。variant manifest 独立于官方
manifest，combined runtime identity 在 manifest 外由 official identity、patched identity、平台与
插件树计算。任何受锁 recipe/package/resource、插件、patch 或构建脚本字节变化都使后续 receipt、
patched manifest 和 combined identity 过期，必须按固定顺序重新生成。

日常机器消费已经审阅的正式锁：

```sh
./agentcfg --local /private/local.toml --profile omp-kernel sync
./agentcfg --local /private/local.toml --profile omp-kernel apply
```

`sync` 只操作该 agent/profile 的私人 cache。按内容寻址的下载缓存通过摘要校验后，可以离线复用；缺少缓存时仅下载锁中指定来源。下载流先进入同一 cache 的 `.part`，对瞬态超时、连接错误、HTTP 408/429/5xx 和短读最多尝试三次；严格核对 206 `Content-Range`，遇 200 安全地从零重写。完整长度及 SHA256 匹配后才原子发布。运行包位于 `<cache>/runtimes/<lock-and-platform-identity>`，不在实例 HOME 中，因此先 sync 再首次 apply 不会接管一个预先创建的原生环境。

对 `permission-control-v1`，日常 `sync` 只消费当前 profile 私人
`cache/artifacts/sha256/<digest>` 中已准备且与独立 manifest 匹配的资产；缺失或损坏时返回 5，
不会现场编译、下载 official fallback、安装或下载 tiny。`apply` 只部署配置和已验证运行包引用，
`sync`/`apply` 均不启动宿主。`run` 的启动前静态检查只核验已部署入口和字节、receipt、ABI 声明、
plugin/runtime identity 与平台资产；不匹配时返回 5，且不会启动二进制。插件是否实际注册或加载只能
由宿主启动后的 bridge 健康状态确认，不能由管理器静态预检或文档冒充真实握手；注册/加载缺失时
smart 不可用，转人工或在无 UI 时阻止，不降成 official 放行。
主审 transport 当前只支持标准 API-key 的 `anthropic-messages` 与 `openai-completions`；其它服务
返回unsupported；配置远程fallback时尝试该明确选择的模型，否则走人工或无UI阻止，不宣称已由真实 provider 验证。主审认证只接受可证明不运行
辅助命令的 runtime/config API-key 来源；仓库 models.yml 的环境变量引用属于 config 来源。
`!command` 密钥/请求头、未知 header resolver、OAuth 和未纳入被动解析的存储凭据路径保留人工。
专用请求头解析只同步读取环境变量或字面量，不能调用通用命令 resolver。tiny 仅使用已安装资源，
缺资源保持 unavailable。

更新和恢复继续使用既有事务：stage 完整验证后才激活，活动会话持共享租约，维护/替换需要排他
租约；冲突或活动实例返回 4。配置或锁结构错误返回 2，依赖/平台/ABI/资产/插件身份失败返回 5，
文件系统或内部事务失败返回 6。发布中断保留可恢复记录或回滚到旧目录；`rollback` 恢复上一配置，
不降级二进制、不下载 tiny，也不把旧许可带入新会话。工具层 ask/deny 不是管理器退出码。

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

`setup` / `sync` 的 stderr 会先标明锁定 OMP 版本、目标平台和资产名，例如 `OMP v18.4.5 / linux-x64 / omp-linux-x64（来源：GitHub Releases）`。随后按真实步骤报告：

| 当前提示 | 正在做什么 |
| --- | --- |
| 等待下载缓存锁 | 等待同一摘要资产的其他同步释放缓存锁；此时尚未发起本次 HTTP 请求。 |
| 检查完整缓存 / 检查断点文件 | 读取本地缓存并计算 SHA-256；完整命中则无需联网。 |
| 第 N/3 次请求：等待连接/响应头 | 建立请求并等待响应头；同时显示已有断点量以及本次从零下载或续传。 |
| 第 N/3 次下载正文 | 显示已下载 MiB、可获得时的总量及百分比、本次传输均速和用时；无总长度时明确显示“总量未知”。 |
| 下载失败 category=… | 显示失败次数、已保留的断点量及下一次请求的等待时间；不回显底层异常。 |
| 校验 SHA-256 / 发布下载缓存 | 正文接收完成后校验摘要并发布，随后才暂存和激活运行包。 |

正文进度约每 1.5 秒更新一次，阶段变化和完成立即报告。无新进度时保留最近的阶段/字节快照，心跳标明“距上次进度更新已等待 N 秒”，不会把持续打印心跳当作下载正在前进。单次连接/读取超时为 60 秒，最多尝试三次；**60 秒不是整个下载的总时限**。服务器忽略 Range 返回 200 时会明确提示从零重新下载。不会输出下载重定向 URL、代理凭据、私人缓存路径或模型 key。

下载中断后，保持同一个 local/profile 和 cache 路径，再次执行同一 `sync`。安全 partial 会保留；服务端支持正确 Range 时从现有进度续传。已完整且摘要正确的 cache 不访问网络；损坏的完整 cache 会移除并重新获取一次。

错误信息只包含 `category`、`attempt` 和 `progress`，不回显可能含凭据的 URL。可按以下顺序处理：

1. 检查私人 cache 所在 Linux 文件系统的可用空间、目录属主和 0700 权限；WSL 不要默认使用 `/mnt/c`。
2. 对 `timeout`、`connection`、`http-408`、`http-429`、`http-5xx` 或 `short-read`，保留 `.part` 并重跑 `sync`。单次命令已有三次有限尝试，不会无限重试。
3. `content-range` 或 `range-reset` 表示响应与请求的安全续传边界不一致；记录错误类别、平台和网络/代理环境，再排查中间代理或服务端。不要手工拼接 partial。
4. `integrity`、`size-limit` 或 `cache-write` 需要检查锁定资产、磁盘和权限。不要手工改摘要、替换锁定 URL 或把 `.part` 重命名为完成文件。

下一次 `sync` 复用同一内容寻址 cache；删除 cache 会失去续传进度，通常不应作为第一步。

这里的下载诊断针对正式锁中的 OMP standalone 和锁维护输入。`omp-kernel` 模型会话访问的是公共 catalog 登记的企业 TokensFlow 网关；该网关不可达、key 无效或 provider 返回错误时，不应归类为 `sync` 下载故障。网关端点需要变更时，应通过私人 local 的 provider `base_url` override 明确审阅兼容性，不能把当前模型 ID 和协议暗自换到厂商官方端点。

## 启动前模型声明不一致

`run` 会比较实例的原生 `models.yml` 与当前所选配方生成的 provider/模型定义；本地或公共来源改变但尚未部署，也会触发该保护。错误现在区分 `models-missing`、`models-link`、`models-read-or-parse`、`models-shape`、`models-provider-set` 和 `models-provider-fields`。集合差异只显示缺少/额外数量，定义差异只显示受影响 provider 数量，不输出 provider ID、字段值或文件正文。

先使用与启动相同的机器/profile 选择器运行 `plan`，确认差异后再 `apply`；需要同时安装新运行包时用 `setup`。发现漂移或冲突时先处理。`setup` 只有完成同步和计划复核后才部署，因此仍在下载阶段时，旧 `models.yml` 尚未更新。不要手工覆盖原生文件或跳过来源门禁。

2026-09-28 诊断改进回归：`.venv/bin/python -m pytest -q tests/test_omp*.py tests/test_setup_cli.py tests/test_runtime.py tests/test_cli.py tests/test_dsh_pipeline.py tests/test_pi_pipeline.py --tb=short` 为 **495 passed**（78.19 秒）。使用临时 HOME、假 HTTP/进程，覆盖连接前提示、读取进度及节流、未知总量、续传与 HTTP 200 回退、重试分类、缓存命中、心跳快照和模型差异脱敏。本轮未探测真实下载链路或读取本机私人模型配置，不作为网络连通性或真实宿主验证。

## 平台和证据

official 路径的目标为 Linux glibc x64/arm64 与 macOS x64/arm64；musl、Windows 和未知架构返回 5。permission-control 正式锁目前只包含 Linux glibc x64 资产，其它平台支持与真实验收见[候选矩阵](acceptance-matrix.md)。隔离平台替身只验证选择和拒绝规则。Linux glibc x64 permission-control 的限定范围 T072 smoke 已通过，具体范围见宿主报告；此前的[真实无账号 smoke](../specs/002-manage-omp-config/evidence/linux-smoke.md)仍是 official 路径历史证据。WSL、Linux arm64、macOS 与 T073 reviewer 质量不能由这些证据推定通过，后续支持声明按实际平台独立记录。
