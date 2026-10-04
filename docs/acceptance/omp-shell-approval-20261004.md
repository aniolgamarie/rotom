# 常见 Shell 环境智能审批验收

2026-10-04。基线 `93a3341`，在独立 worktree 分支 `feat/omp-shell-approval` 实现 Phase 15。
本轮保留用户的 Shell，修改仓库自有插件与受管启动契约，不修改官方 OMP 源码、二进制或历史补丁。
固定官方版本仍为 v18.4.5 / `79808c3bf8f8cd9826decc63e3e18b13035f64f8`；机器证据见 [JSON](omp-shell-approval-20261004.json)。

## 问题与范围

日常会话的 `SHELL=/bin/zsh`，普通 find 管道在调用审查模型之前因
`UNSUPPORTED_EXECUTION_CONTEXT` 转人工。实现前的纯模块红测试保留了该失败。
固定官方源码的普通 BashTool 不传 `useUserShell`，实际由内置 Brush 执行；Bash 配置才会
加载 snapshot。ACP 客户端终端另有真实外部 Shell 路径，公开扩展 context 不提供 bridge 查询。

受管 LaunchSpec 只在 `native_bash=true` 时绑定
`ROTOM_PERMISSION_CONTROL_EXECUTION_ROUTE=local-native-bash-v1`。机器配置不能覆盖或继承
此标记，调用者预置也被拒；最终环境重核。插件每次捕获/执行检查当前 marker、公开 CLI
形状及 scoped Settings，并将 marker/argv 的摘要加入执行指纹。默认、text、json、rpc
属于本地路径；ACP、rpc-ui 和未知 CLI 不能自动批准，也不能退回旧 Bash/sh 兼容路径。

该标记是受管配置契约，不是防同 UID 伪造的凭据；只覆盖 `agentcfg run` 的新官方 CLI
进程，不承诺任意第三方 SDK 嵌入或热加载。保留机器显式选择或调用者继承的 SHELL，未强制
切换 Bash。支持的是普通 Bash 工具在常见 Shell 配置环境中的审批，命令仍使用 Brush 语法。

非 Bash 启动脚本和已知同族 custom shellPath 不参与已确认的普通本地执行，因此不再单独
导致人工。Bash startup/snapshot、custom Bash path、继承函数、HOME 不一致、direnv、prefix、
未知 Shell/args/path、原生 deny/prompt、高级参数与票据校验继续保留。主动 reviewer、session
主审、远程 fallback 和本地 unavailable fallback 的选择顺序没有改变。

## 稳定代码验证

| 检查 | 结果与实际范围 |
|---|---|
| Bun 定向 | 64 pass，543 assertions |
| Bun 包级 | 355 pass，1628 assertions，15 files |
| 固定 pristine SDK tsgo | 退出 0，无诊断 |
| 受影响 Python | 208 pass，7 skip，29.28s；跳过的是已退役宿主补丁材料，不是本次独立插件 |
| 未修改官方宿主 | 36/36 pass；临时 HOME、固定 loopback 响应，源文件及官方二进制前后摘要一致 |
| zsh find 管道 | 审查 1、human 0、nativeDelegate 1，返回临时文件结果；此例明确关闭 interceptor |
| 默认 find interceptor | 仍提示使用 glob；审查 1、human 0，原生拦截行为保留 |
| 原生禁止与未知路线 | deny 零审查/零委托；缺失或错误 marker 的 zsh、未知参数等不自动执行 |

官方宿主测试通过自有公开 API facade 捕获生产插件命令注册，再调用同一 `/permission-control`
handler 读取固定状态；不改写宿主对象或私有接口。首次宿主样本因默认 find interceptor
返回 glob 提示而未执行，修正的是 fixture 的预期与显式设置；该失败另行保留。测试 facade
曾因对象展开未转发原型方法而加载失败，修正为公开方法转发后通过；未把此失败算作产品通过。

人工弹窗增加固定原因，explain/status 包含安全的 `nativeContext`。审查发现失败分支残留
旧诊断，以及 raw 预捕获可能覆盖另一待审调用；均增加红测试并修复。raw 预捕获仅保存票据，
串行执行时更新诊断。重复或无效参数会发布自身拒绝结果并清空上下文；单个 explain 表示
最近发布的结果或当前串行审查，不展示所有并行 pending。不会混入原始环境、启动文件路径
或模型自由文本。

Python 回归还发现基线发现清单及固定断言过时：按现有来源规则重新生成清单，保持 Cursor
模型 provider 可用和 permission sidecar 的来源边界，修正仓库名称固定为 rotom 的断言以适配
worktree。没有调整上游发现实现。稳定后用已有官方离线材料刷新普通目录摘要和锁；历史
patch、receipt、冻结评测材料没有刷新。

实现由 executor `gpt-6.1-sol/medium` 完成插件与回归；scout `gpt-6-luna/high` 独立核对
源码路线和最终稳定 diff。主代理负责规格、启动契约、上下文决策、官方宿主验收及合入。

## 实际覆盖与交付边界

| Shell 环境 | 纯模块支持 | 本轮真实官方宿主 |
|---|---|---|
| bash | 标准参数、startup、函数、HOME、custom path 保护 | 通过既有正反例 |
| zsh | 标准登录参数、startup 不执行、custom path、路线校验 | 通过；含 find 管道和原生拦截 |
| sh | 标准参数、legacy 保守保护、本地 custom path | 通过 `/bin/sh` 配置路径；不是另一套命令语言验收 |
| dash、ash、ksh、mksh、fish | family 与标准参数、未知参数拒绝 | 未单独安装/运行对应环境，不计作真实验证 |
| pwsh、powershell、cmd | Windows 名称/路径和官方参数形状 | 未真实运行；不扩大运行包的 Windows 支持范围 |

本轮付费请求为 0，没有借用新预算；真实 Cursor 新版 zsh 服务调用未执行，旧 Phase 14 真实
Cursor 结果保留原身份。其它 OS、PTY/async/service、本地 tiny 推理仍未新增验证。

T105—T109 已完成，在 worktree 开发验收后本地快进合入 main。本轮不部署或终止日常实例；使用新兼容能力需要
退出旧 OMP，再从 main 按正常 `sync`、`plan`、`apply` 更新并启动新进程。只提交源码、测试、
规格、普通锁和安全验收记录，不提交 worktree 缓存、机器配置、账号、原始会话或宿主日志。
