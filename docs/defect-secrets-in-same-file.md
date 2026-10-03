# Secrets 与配置同文件：已实现分离存储

发现于 2026-09-17；2026-09-28 实现共享密钥文件与隐藏输入命令。当前使用说明见[本地配置](local-config.md)。

## 原问题

旧机器文件 `~/.config/agentcfg/machines/<machine>.toml` 同时包含普通配置和 `[secrets]`。即使文件为 0600、父目录为 0700，以同一用户身份工作的 Agent 在读取配置时仍可能顺带读取密钥；整份配置的分享、备份也容易夹带秘密。

## 当前行为

- 新建机器文件不含密钥，所有工具/profile 默认共享 `$XDG_CONFIG_HOME/agentcfg/secrets.toml`，XDG 未设置时为 `~/.config/agentcfg/secrets.toml`。
- `model key deepseek|kimi|glm` 通过终端隐藏输入填写官方 key；额外 provider 使用 `model key <provider-id>`。命令行不接收明文 key。
- `model add`、`model enable` 新输入的 key 同样进入共享文件，普通配置只保存 `secret:<name>` 引用。配置提交失败时只尝试回滚本次共享凭据版本，不覆盖并发修改。
- 共享文件要求当前用户所有、0600、普通单链接文件，父目录要求 0700；拒绝链接、不安全权限和读取竞态。
- 新 key 按 `[shared]`（官方默认）和 `[providers.<id>]`（额外 provider）分类，状态页显示密钥名与分组；组名不改变 `secret:<name>` 的全局唯一引用，跨组重复声明一律拒绝。
- 旧共享文件的平铺 `[secrets]` 可继续读取、更新并标记旧格式；已有 key 不自动搬迁。
- 旧机器文件 `[secrets]` 继续兼容，空占位符不会遮蔽共享值。同一个引用若在两个来源均有非空值则报错，防止悄悄使用错误账号。
- 旧内联 key 的更新仍写回原位置并给出提示；没有自动迁移、删除或批量读取用户真实密钥。

可在机器文件**顶层**指定另一份共享文件：

```toml
schema_version = 1
secrets_file = "~/private/agentcfg/secrets.toml"

[machine]
id = "workstation"
```

共享文件结构如下，实际值由隐藏输入命令写入：

```toml
schema_version = 1
[shared]
deepseek_key = ""
kimi_key = ""
glm_key = ""
```

缺失文件表示尚未配置；只更新 key 后重新 `run`，无需重新部署。模型选择或角色变化仍需 `plan`、`apply`。`model status` 只显示是否填写，不证明 key 有效。

## 安全边界与未实现内容

分文件降低普通配置编辑中的误读、误分享风险，**不隔离同用户进程**。当前宿主仍通过子进程环境变量接收所需凭据，宿主启动的工具进程可能继承它们。若目标是阻止 Agent 主动读取或继承凭据，还需要独立权限/沙箱或凭据代理设计。

未实现自动迁移旧内联 key、`credential_ref = "env:..."`、系统钥匙串或 Vault 等外部后端。不要把这些草案语法写入当前配置。

处理旧配置时，使用独立、无秘密的配置提案，只合并明确的非秘密字段；不要截断原文件、复制整份含密钥文件到仓库、将备份改成 0644，或让 Agent 整体读取旧机器文件。

## 实现位置

- `src/agentcfg/secret_files.py`：共享来源、权限检查与写入/回滚。
- `src/agentcfg/model_keys.py`：隐藏输入入口。
- `src/agentcfg/model_status.py`：状态与填写指引。
- `tests/test_shared_model_keys.py`：临时 HOME 下的共享、权限、脱敏和回滚验证。
