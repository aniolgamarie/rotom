# Cursor 原生 Bash 智能审批：真实验收与交付

2026-10-04。基础实现 `96d4fe2`，固定官方 OMP v18.4.5。用户新增授权最多六次推理请求，已使用六次：Cursor 三次、GLM 远程审查三次；历史 102/102 账本未改写。机器证据见 [JSON](omp-cursor-native-approval-20261004.json)，先前纯模块和隔离宿主身份见 [基础验收](omp-native-bash-approval-20261004.md)。

## 真实路径与发现

通过官方 RPC 模式启动独立 HOME，先检查 bootstrap ready、状态和命令注册，再发送任务。Cursor OAuth 来自原库只读文件快照，实际 SQLite 运行库是临时副本；原账号与日常配置在每轮测试前后均保持原字节。`--no-title --no-skills`，关闭重试、模型自动备用、记忆和压缩。外部推理在 provider payload hook 或 reviewer fetch 前共享持久计数，第七次会同步停止自建测试进程；五个假环境测试验证跨进程续计、超限与账本故障关闭。没有终止日常实例。

第一轮：Cursor 原生 Bash 实际进入插件，主审=session 为 unsupported、零主审调用，GLM 备用调用一次，返回 thinking+text。旧代码拒绝多内容块，于是转人工并 Deny，原生委托零次。另用一次生产 reviewCommand 诊断，确认唯一 text 为有效低风险、授权充分的 allow JSON。首次失败保留，未算通过。

修复：Anthropic 传输仅忽略 thinking/redacted_thinking 元数据，要求恰好一个 text，再走原有严格决策 JSON。多个 text、未知块、tool_use、缺失 text 仍失败；有效 ask/deny 仍终止备用链，不增加网络重试。标准内容块定义可参考 [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create)，本次行为由实际响应和固定源码共同核对。

修复后：Cursor Kimi K3 high 通过原生 Bash 运行一次临时目录 `pwd && ls -la && pwd | head -1`，GLM 自动审批一次，human=0、delegate=1、coverage=ready。服务把旧 K3-high 别名规范为 K3，保留 high 思考级别；执行模型与 reviewer 选择没有混用。最后一轮为临时 pwd deny 规则，真实 Cursor 调用被阻止，remote=0、human=0、delegate=0、没有执行。

## 稳定代码验收

| 检查 | 实际结果 |
|---|---|
| 定向 Bun | 48 pass / 203 assertions |
| 包级 Bun | 339 pass / 1288 assertions |
| pristine SDK tsgo | 退出 0 |
| 最终普通锁 kernel/dependencies | 31 pass / 25.74s |
| 官方隔离宿主 | 25/25 pass，新增 Anthropic thinking fixture |
| 真实 Cursor | 自动批准执行、原生禁止、初次无效审查转人工拒绝 |

兼容修复先有三个红测试，再通过定向和包级测试。由 executor 角色 gpt-6.1-sol/medium 实现，scout 角色 gpt-6-luna/high 独立核对协议与窄 diff；主代理执行真实调用、验收与部署决策。缓存、原始响应、账号副本与测试日志不提交。普通锁和插件身份在 JSON 中，官方源码、二进制和历史补丁未修改。

## 部署状态与限制

日常部署已完成，功能与兼容修复 `14f34a9` 已快进合入本地 main。备份时实例锁拦住首次尝试，未发生修改；用户随后明确要求终止，核验持锁的官方 omp-kernel 进程后用 SIGTERM 正常退出，锁释放，无需 SIGKILL，也没有终止其它实例。

独占实例和状态锁内创建完整 0600 备份（169 成员，路径见 JSON），包含实例、部署状态与本机配置，不跟随符号链接。退出后 default 仍缺失、smol 保存为 `cursor/kimi-k3:low`；按用户已确认的声明恢复 default=`cursor/kimi-k3:high`、smol=`zhipu_tf/glm-5.3-flash:low`。原子替换只改变这两个字段的语义，保留其它原生字段；备份辅助脚本的证据目录改为机器私有缓存，并用完整备份重新核对恢复结果，没有改动原生会话目录权限。

正常 sync 校验缓存的官方发布资产，无下载；plan/apply 更新两项、漂移零、冲突零。doctor 为 offline-ready，依赖 installed、运行包匹配、待变更零、无恢复。完整 `run` 路径在用户的 `group_commit_leader_switch` 目录通过，以 launch callback 验证准入，没有启动日常宿主或增加模型请求。部署前后的 13 个账号 DB/WAL/SHM、会话、本机 TOML 和所有权文件字节与权限保持不变；新运行包的官方二进制 SHA256 与固定上游一致。

当前模式 smart、nativeBash=true；主审未显式配置时跟随会话，Cursor 不支持标准审查传输时转 GLM flash 远程备用。用户设置显式 reviewer 后它仍优先，smol 角色不等于 reviewer。本地 tiny 配置为 installed-only，但无公开推理 API，仍记录 unavailable 并转人工。新启动时 coverage 可能为 limited，取得实际 scoped Settings 和委托能力后才能变为 ready；本次真实 Cursor 自动执行已观察到 ready，部署准入本身不冒充运行覆盖验证。

临时测试 HOME、账号副本和原始模型响应已清理，安全预算计数保留为 6/6；备份与本机证据放在私人缓存，未提交账号、原始日志或本机 TOML。恢复角色、同步、部署与启动准入均未新增外部推理请求。

本次只证明观察到的真实 native Bash 路径，没有独立穷举所有 Cursor frame。其它平台、高级 async/service/PTY、本地 tiny 和冻结质量样本不因本次通过而视为新增通过。审批仍为应用层能力，未知 startup/direnv 和敏感上下文继续人工；必须从新进程启动加载插件。
