# 用户授权后的订阅验收

这是独立的 live 验收步骤，不属于默认 pytest，也不能从无账号 smoke 推断通过。先确认用户明确授权本次登录/模型调用，并仅使用目标受管实例；不要读取或复制现有 `~/.codex`、Cursor keychain 或其他 Agent OAuth 文件。

## 前置检查

运行 validate/plan/sync/apply/doctor，记录选中的机器、profile、锁身份和实际平台。确认 default standard preset、workspace-write 权限、独立 home、Cursor 端口无冲突。不要以“长任务”推断完全访问。

## Codex

1. 启动受管 DSH，在原生 TUI `/auth login openai-codex` 完成订阅登录。
2. 用 `/auth status` 和 `/model` 确认 provider/模型可见；只记录公开路由与成功/失败，不导出账号令牌。
3. 用户明确授权调用后发送一条最小文本请求，确认返回来自 openai-codex 路由。记录是否成功、所选模型与时间，不记录凭据。

## Cursor

1. 在同一受管实例使用 `/cursor-login`，在浏览器完成授权并等待插件轮询结束。
2. `/model` 中确认 oauth-cursor provider 及目录可见；这一步不是调用 Cursor CLI。
3. 用户明确授权调用后发送最小文本请求，确认走 oauth-cursor。失败要区分登录、目录、proxy、协议或模型访问问题。

## 保留与复刻

退出实例后做一次不改配置的 apply，确认无变化且不轮换上一版备份；重新启动确认原生登录仍在。另一个新实例应重新登录，不迁移 OAuth。配置 rollback 不回退账号/会话/数据库。

| 平台/实例 | 锁身份 | Codex 登录 | Codex 调用 | Cursor 登录 | Cursor 调用 | 备注 |
|---|---|---|---|---|---|---|
| 用户目标环境 | 待填写 | 未执行 | 未执行 | 未执行 | 未执行 | 需用户明确授权与账号 |

当前实现交付不包含上述真实订阅调用成功的声明。
