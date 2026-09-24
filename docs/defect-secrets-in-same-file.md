# 缺陷：Secrets 与配置在同一文件中

## 问题描述

当前 rotom 的 secrets（API keys）存储在 `~/.config/agentcfg/machines/<machine>.toml` 文件中，与配置信息在同一个文件。虽然文件权限设置为 0600（仅所有者可读写），但 AI 以当前用户身份运行时可以读取该文件，存在 secrets 泄露风险。

## 安全分析

### 当前防护

1. **文件权限**：0600（仅所有者可读写）
2. **目录权限**：0700（仅所有者可访问）
3. **SecretStore 类**：
   - `__repr__` 返回 `"SecretStore()"`，不显示内容
   - 不允许序列化
   - 只在运行时通过 `resolve()` 返回值

### 防护失效场景

- **AI 助手访问**：AI 以当前用户身份运行，可以读取 secrets 文件
- **代码审查**：当 AI 帮助修改配置时，可能意外读取或泄露 secrets
- **上下文泄露**：AI 可能在对话中意外暴露 secrets

### 风险等级

**中等**：
- 防止了其他系统用户访问
- 无法防止 AI 访问
- 在 AI 辅助开发场景下存在泄露风险

## 影响范围

所有使用 rotom 管理配置的用户，特别是：
- 使用 AI 助手辅助开发的用户
- 在共享环境中使用 AI 的用户
- 需要代码审查的场景

## 建议修复方案

### 方案 1：分离 secrets 文件（推荐）

将 secrets 存储在独立的文件中，通过引用方式访问：

```toml
# ~/.config/agentcfg/machines/workstation.toml
[secrets]
# 引用外部 secrets 文件
secrets_file = "~/.config/agentcfg/secrets.toml"
```

```toml
# ~/.config/agentcfg/secrets.toml（独立文件，0600 权限）
bailian_coding_api_key = "sk-xxx"
bailian_api_key = "sk-yyy"
```

**优点**：
- AI 可以安全地修改主配置文件
- secrets 文件可以独立备份和恢复
- 可以设置更严格的访问控制

**缺点**：
- 需要修改 rotom 代码支持 secrets_file 引用
- 增加配置复杂度

### 方案 2：环境变量注入

通过环境变量传递 secrets，不存储在文件中：

```bash
# 在 shell 配置中
export BAILIAN_CODING_API_KEY="sk-xxx"
export BAILIAN_API_KEY="sk-yyy"
```

```toml
# 配置文件中引用环境变量
[overrides.providers.bailian_coding]
credential_ref = "env:BAILIAN_CODING_API_KEY"
```

**优点**：
- secrets 不存储在磁盘上
- 可以通过 shell 配置管理
- 支持密钥管理工具（如 1password、vault）

**缺点**：
- 需要修改 rotom 代码支持 env: 引用
- 环境变量可能在进程列表中暴露
- 不适合长期运行的服务

### 方案 3：临时移除 secrets（当前可用）

在 AI 帮助修改配置时，临时移除 secrets 段：

```bash
# 1. 备份 secrets
grep -A 100 '^\[secrets\]' workstation.toml > secrets-backup.toml

# 2. 删除 secrets 段
sed -i '/^\[secrets\]/,$d' workstation.toml

# 3. 让 AI 修改配置
# ...

# 4. 恢复 secrets
cat secrets-backup.toml >> workstation.toml
rm secrets-backup.toml
```

**优点**：
- 无需修改 rotom 代码
- 立即可用

**缺点**：
- 手动操作繁琐
- 容易遗忘恢复
- 不适合自动化流程

### 方案 4：加密 secrets

使用加密存储 secrets，运行时解密：

```bash
# 使用 gpg 加密
gpg -c secrets.toml
# 生成 secrets.toml.gpg
```

**优点**：
- secrets 加密存储
- 需要密码才能解密

**缺点**：
- 需要修改 rotom 代码支持解密
- 需要交互式输入密码
- 不适合自动化

## 推荐实施路径

1. **短期**（立即可用）：
   - 使用方案 3（临时移除 secrets）
   - 在文档中添加安全警告

2. **中期**（1-2 周）：
   - 实现方案 1（分离 secrets 文件）
   - 添加 `secrets_file` 引用支持

3. **长期**（可选）：
   - 实现方案 2（环境变量注入）
   - 支持多种 secrets 后端（文件、环境变量、vault）

## 相关文件

- `src/agentcfg/secrets.py`：SecretStore 实现
- `src/agentcfg/config.py`：配置加载
- `src/agentcfg/schema.py`：separate_local 函数
- `~/.config/agentcfg/machines/*.toml`：用户配置文件

## 发现时间

2026-09-17

## 状态

**待修复**：当前使用方案 3 作为临时 workaround
