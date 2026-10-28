# Rotom

**为编程 Agent 提供可复现配置与隔离实例。**

[English（正式文档）](README.md) · [文档索引](docs/README.md) · [路线图](docs/roadmap.md) · [已知问题](docs/known-issues.md)

Rotom 提供 `rotom` 统一入口，保留 `agentcfg` 管理 DSH、Pi 和 OMP 的配置、完整依赖、部署与启动。公共模型、规则、完整 Skills 和配方进入 Git；机器覆盖、密钥、原生登录与会话保留在私人目录。`termcfg` 独立管理 zsh/tmux 配置及锁定插件；代理服务不再由它管理，旧元数据通过显式命令迁移。

## 当前状态

- DSH：一套 `dsh-default` 配方，Core `0.2.1-rc.2`（预发布）、TUI `0.16.1`、Cursor `0.6.12`、Perry auto-review `0.13.7`。自动审批默认开启，但存在已接受且尚未解决的上游限制；详见[已知问题](docs/known-issues.md)。
- OMP：未修改的官方 `18.12.6`，通过独立插件实现 Rotom 的权限功能。
- Pi：`pi-base` / `pi-pro` 使用未修改的官方 `1.3.0` CLI 和完整 npm 锁；Linux 界面、模型/会话及所选模块的有界证据按源码快照分列。状态信息已按三处获接受的显示差异交付；Pro 调查协作等待上游，Brave/Cursor 账号验收延后。见[支持边界](docs/pi-support.md)及[集成检查](specs/005-rebuild-pi-toolkit/integration-candidate.md)。
- 三工具维护候选提供“精确停止 → 独立批准 setup → 逐项当前终端恢复”，有交互选择、help 和补全。完整 workflow 的驻留原 pane/新 tab 与 --all 批量位置候选已实现，最终十二组无 trace 原生验收已通过，准入限定六个精确 Linux managed 组合的两种位置；普通 --session 位置恢复未开放，普通 rotom run 不驻留。DSH/Pi 的 Herdr V1/V2 四个 work Agent 入口已正式通过；OMP 无默认 work type，通过已准入新 tab 建立 resident 后可原位恢复。精确支持见[六组合、两位置矩阵](docs/rotom-pane-capabilities.md#本轮精确组合验收清单)。此前完整隔离快照为14,153 passed / 13 skipped；本轮共享准备预算修正的受影响组为3,740 passed / 4 skipped，另通过官方Pi Base双会话流程。位置恢复支持整批共用 `--wait-seconds 1..300`（默认30），不限制交接后的Agent运行时长。加载仍待人工核对，不发送继续；Pi 只保护 Rotom 合作实例，OMP 写入冲突可能分叉。候选仍在任务分支，尚未合入 main，T125 待人工批准；见[维护流程](docs/tool-maintenance-workflows.md)与[验收范围](specs/008-rotom-command-experience/tool-workflow-validation.md)。
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

两个 CLI 裸跑只显示静态任务导航并返回 2，不检查配置或自动操作；`--help` 查看索引，子命令 `--help` 查看参数、示例和副作用。先确认目标，再用 `doctor` 查原因、`plan` 看变化；终端受管状态使用 `termcfg status`。结果会区分阻塞、可选降级、待恢复及本次影响，下一步提示保留所选范围。`agentcfg` 的结构化命令用 `--format json`，`termcfg` 用显式 `--json`；二者不会因显示优化而省略接管或确认检查。

完整配置、支持范围、测试与恢复说明以[英文文档](docs/README.md)为准。本页是简要中文入口，不是全部技术文档的逐页翻译。
