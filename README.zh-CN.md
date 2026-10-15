# Rotom

**为编程 Agent 提供可复现配置与隔离实例。**

[English（正式文档）](README.md) · [文档索引](docs/README.md) · [路线图](docs/roadmap.md) · [已知问题](docs/known-issues.md)

Rotom 使用 `agentcfg` 管理 DSH、Pi 和 OMP 的配置、完整依赖、部署与启动。公共模型、规则、完整 Skills 和配方进入 Git；机器覆盖、密钥、原生登录与会话保留在私人目录。`termcfg` 独立管理 zsh/tmux 配置及锁定插件；代理服务不再由它管理，旧元数据通过显式命令迁移。

## 当前状态

- DSH：一套 `dsh-default` 配方，Core `0.2.0-rc.2`（预发布）、TUI `0.15.0`、Cursor `0.6.12`、Perry auto-review `0.12.17`。自动审批默认开启，但存在已接受且尚未解决的上游限制；详见[已知问题](docs/known-issues.md)。
- OMP：未修改的官方 `18.8.6`，通过独立插件实现 Rotom 的权限功能。
- Pi：适配器已实现；当前锁与源码不匹配，新的安装部署需先完成正式锁重建和对应验收，不能沿用历史结论。
- 项目正在准备首次公开发布，尚不以包版本号代替正式发布标签。

## 开始使用

准备 Python 3.11+、uv 和所选 Agent 的工具链后：

```sh
uv sync --locked
./agentcfg profiles
./agentcfg init-local --machine workstation --profile dsh-default
./agentcfg --machine workstation --profile dsh-default model status
./agentcfg --machine workstation --profile dsh-default setup
./agentcfg --machine workstation --profile dsh-default run --cwd /path/to/workspace
```

`init-local` 由工具创建私人文件与缺失占位符，保留已有值。共享密钥使用 `model key kimi-code|glm-code|deepseek` 隐藏输入；OAuth 在对应原生实例内登录。缺少模型密钥不阻止宿主启动。

`sync` 安装锁定依赖，`apply` 部署配置，`run` 只启动已有部署。配置回滚不等于软件降级或会话数据库回滚。所有集成只使用官方配置、公开扩展 API 和 CLI，不修改 Agent 上游源码。

完整配置、支持范围、测试与恢复说明以[英文文档](docs/README.md)为准。本页是简要中文入口，不是全部技术文档的逐页翻译。
