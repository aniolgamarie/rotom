# rotom 工程约定

个人 Agent 配置管理仓库。通过 `./agentcfg` 管理公共配置来源、机器覆盖、原生转换、完整依赖、部署与启动。
首版真实支持 DSH + `ccch1mneyyy/dsh-TUI`，保留公共适配接口供未来 Pi/Codex 接入。

## 技术栈

- Python 3.11+，使用 `uv` 管理依赖
- 依赖：PyYAML、jsonschema、Jinja2、pytest
- 入口：`./agentcfg`（直接使用仓库 `.venv`，不走 `uv run`）
- 配置格式：TOML（registry/profiles/local），YAML（原生 DSH 产物）

## 目录结构

```
src/agentcfg/       # Python 模块
shared/             # 公共 rules/skills
profiles/           # profile 定义 (TOML)
agents/dsh/         # DSH 适配器（agent.toml, bindings.toml, plugins.toml, templates/）
locks/dsh/          # DSH 依赖锁
schemas/            # JSON Schema 定义
examples/           # 本地配置示例
tests/              # pytest 测试
docs/               # 文档
```

## 测试边界（DSH-10）

- **默认测试只允许仓库内和临时 HOME 目录**
- 默认测试使用临时 HOME/DSH_HOME/XDG、网络阻断、假子进程、虚构 provider/model 和文件哨兵
- **默认测试不启动第三方宿主**（DSH、Pi、Codex 等）
- 真实 smoke 为独立显式步骤，需用户明确授权
- 不以无账号 smoke 或 CI 文件代替通过证据

## 开发规范

- 双引号字符串，2 空格缩进
- 中文注释
- 原子提交，conventional commit 格式
- 不提交 secrets 或凭据
- 未知字段失败，不静默丢弃或修复
- 秘密值不进入通用配置/摘要/日志/异常

## 退出码

- 0: 成功（可有漂移/待登录提示）
- 2: 参数或配置/锁校验错误
- 3: 所需凭据缺失
- 4: 所有权冲突、活动实例或恢复待处理
- 5: 依赖/原生检查失败或缺必要运行包
- 6: 文件系统/内部操作失败
