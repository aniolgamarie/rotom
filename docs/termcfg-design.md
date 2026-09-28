# 终端程序管理器设计草案

> 历史调查与初步方案。正式范围以 [termcfg 功能规格](../specs/003-sync-terminal-tools/spec.md) 为准：代理组件现包含 mihomo core、非秘密配置和显式服务管理；`~/.zshenv` 按确认后整文件备份与覆盖处理。下文与规格冲突时须在 `$speckit-plan` 阶段更新设计。

## 目标与命令边界

新增仓库入口 `./termcfg`，管理非 AI 终端程序的**安装来源和用户配置**。首批组件为 `zsh`、`tmux`、`mihomo-mgr`，由用户显式选择；运行中的 shell、tmux server、mihomo core 仍由其原生命令控制。`termcfg` 不读取 `agentcfg` 的模型、profile 或 API key，也不在 `agentcfg setup/run` 中隐式执行。

```text
./termcfg components
./termcfg init-local [--machine NAME]
./termcfg [--machine NAME] plan [--component zsh|tmux|mihomo-mgr]
./termcfg [--machine NAME] apply [--component zsh|tmux|mihomo-mgr]
./termcfg [--machine NAME] status
./termcfg [--machine NAME] doctor
./termcfg [--machine NAME] rollback [--component zsh|tmux|mihomo-mgr]
```

选择机器与目标 HOME 应在独立的私人 TOML 中声明。默认目标为当前用户 HOME；测试显式指定临时 HOME。`plan/status/doctor` 只读，`apply` 写入受管文件，`rollback` 只撤销本管理器最近一次成功部署。组件可以分别部署；没有必要要求每台机器都安装 mihomo 或 zsh。

## starter 来源盘点

| 组件 | starter 来源 | 当前部署/运行行为 | 新管理器的边界 |
| --- | --- | --- | --- |
| zsh | `shell_config/zshrc.zsh`、`install.sh` | 链接 `~/.zshrc`，修改 `~/.zshenv`；加载时可能下载 zinit/插件 | 管理 `.zshrc` 和一个有精确 marker 的 `.zshenv` 片段；插件安装须显式同步 |
| tmux | `shell_config/tmux.conf`、`scripts/fzf-window.sh` | 链接配置与脚本；加载时可能下载 TPM/插件，continuum 自动保存/恢复会话 | 管理配置与脚本；插件安装须显式同步，现有会话不自动重载 |
| mihomo-mgr | `skill/mihomo-mgr/scripts/mihomo-mgr.py`、`LICENSE` | shell 中 `mm` 函数指向 starter；脚本管理订阅、凭据、核心进程、日志、统计与路由 | 管理 CLI 程序、`mm` 入口和静态补全；保留用户运行状态原位 |

`starter/shell_config/install.sh` 不能直接作为 `apply`：它对已有文件自动创建时间戳备份、直接覆盖 `_mm`，对 `.zshenv` 只有局部修改且没有统一恢复记录。更重要的是，zsh/tmux 的网络下载发生在**加载配置时**，不受安装器进度、依赖锁和失败诊断控制。迁入时把需要的源码和许可证固定到本仓库，配置不再依赖 `/root/gitLocal/starter` 的位置；保留来源版本记录。

## 配置与所有权

- 公共清单记录组件版本、源摘要、目标清单、可选依赖和平台条件。机器 TOML 只记录所选组件、目标 HOME、可执行程序路径及明确的功能开关；不记录订阅 URL、controller secret 或代理账号。
- 默认遇到已有非本管理器文件、旧 starter symlink 或未知 marker 时报告冲突。`plan --adopt` 仅预览明确接管；`apply --adopt` 在逐项目标核对并建立私有备份后接管，不能把旧安装脚本的 `.bak.*` 当作所有权证明。
- `~/.zshenv` 只管理一个新 marker 区间；marker 外的机器变量和权限保持原样。旧 starter marker 必须以独立迁移步骤处理。路径为 symlink、marker 重复或内容漂移时停止，不做模糊文本替换。
- mihomo 的 `~/.config/mihomo-mgr/`、mihomo `config.yaml`、订阅缓存、路由草稿/发布状态、日志、PID、SQLite 统计与凭据属于运行数据。`apply/rollback` 不删除、不备份到通用配置状态，也不自动运行 `start/stop/sub-pull/routing apply`。
- 保存每个受管目标的类型、来源摘要、应用前状态、应用后摘要和所属组件。`rollback` 只在应用后目标仍匹配时恢复上一版；用户修改后报告冲突。临时文件、恢复日志和备份留在私人 state；不在 HOME 下散落时间戳备份。

现有 `agentcfg` 的配置产物限定为实例相对路径、0600/0700 的非秘密字节，不能直接拿来部署 HOME 下的 `.zshrc`/`.tmux.conf`、普通脚本和 symlink。可复用安全路径检查、原子写、冲突与恢复思路；终端目标的投影、权限及 symlink 处理需要独立实现，不能放宽 Agent 部署契约。

## 可诊断性与实施顺序

`plan` 逐项目标显示 `add/update/adopt/conflict/unchanged` 和备份/回滚范围；`apply` 显示验证、备份、写入、复核四个阶段，失败指出组件、目标和下一条命令。`doctor` 区分“已安装”“配置可解析”“插件已准备”“运行服务可用”，不会把未执行的联网或 mihomo 模型外服务检查报成通过。基础配置缺少 zsh、tmux、fzf 或 mihomo core 时按组件给出具体降级结果。

1. **源码冻结与拆分**：复制经过审查的 starter 源码和许可证，移除加载配置时的自动 Git 下载与 starter 路径依赖；锁定或显式管理 zinit/TPM 等可选插件来源。
2. **只读规划**：实现 `components/init-local/plan/status/doctor`，覆盖旧 symlink、已有普通文件、marker 冲突、不同 HOME、macOS/Linux 与无依赖场景。
3. **受管部署**：加入逐组件 `apply/rollback`、私有备份、崩溃恢复和漂移拒绝；测试仅用临时 HOME、网络阻断和假进程。
4. **显式原生验证**：在用户允许的隔离环境中验证 zsh/tmux 加载和 mihomo-mgr CLI；真实 mihomo core、订阅网络和当前 HOME 迁移分别审阅。

验收前不修改实际 `~/.zshrc`、`~/.tmux.conf`、`~/.zshenv`、tmux 会话或 mihomo 运行状态。
