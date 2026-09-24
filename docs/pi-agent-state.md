# Pi 终端状态通知

`gentle-agent-state` 只在父会话运行，提供两种显式模式。没有配置时拒绝加载，不会自动查找全局 `~/.config/agent-state/scripts/agent-report.sh`。

## 终端标题模式

用于支持 OSC 标题的终端，包括原生 Ghostty。标题来源明确，无需终端查询或后台脚本。

```toml
[overrides.profiles.pi-default.agent_options.resources]
extensions = ["gentle-agent-state"]

[overrides.profiles.pi-default.agent_options.agent_state]
mode = "osc"
title = "Pi — my project"
```

数组会整体替换，请合并已有扩展选择。工作时标题追加 working，等待明确的用户输入工具时追加 blocked，空闲和退出时恢复配置的标题。无 UI 时不写终端控制序列。不读取或猜测原来的 shell 标题。

## 外部报告服务

保留 `agent-report.sh PANE STATE` 的调用约定，适用于显式配置的 tmux/Zellij 集成。下面只是绑定格式，路径、版本、脚本闭包和 socket 必须按机器填写：

```toml
[overrides.profiles.pi-default.agent_options.agent_state]
mode = "service"
executable = "/usr/bin/bash"
version = "YOUR_BASH_VERSION"
args = ["/absolute/agent-state/scripts/agent-report.sh"]
files = [
  "/absolute/agent-state/scripts/agent-report.sh",
  "/absolute/agent-state/scripts/tmux-agent-report.sh",
]
socket_paths = ["/absolute/tmux/server.sock"]
pane_env = "TMUX_PANE"
timeout_seconds = 5

[overrides.profiles.pi-default.agent_options.agent_state.environment]
TMUX = "/absolute/tmux/server.sock,0,0"
```

- 需要选择已有 `pi-subagents`；服务使用同一 manager、supervisor、超时、取消和独立终止证明。
- `pane_env` 仅支持 `TMUX_PANE`、`ZELLIJ_PANE_ID`；也可以改用字面 `pane`，两者只能选一个。缺少所选环境变量明确失败。
- `executable` 必须是实际可执行文件，不接受符号链接。脚本及它加载的相邻脚本必须列入 `files`，启动前重新核验正文和文件身份。缺少依赖不会回退到全局 HOME。
- 只挂载声明的脚本、socket 和系统运行库，不挂载业务项目。TCP 网络禁用，Unix socket 仅开放明确端点；socket 不能是链接且必须属于当前用户。
- 可写状态只在本实例 `pi-home/service-state/agent-report/`。`XDG_RUNTIME_DIR` 指向该目录，HOME 为单次执行临时目录；不把真实用户 HOME 交给脚本。
- `environment` 仅允许终端相关的封闭字段，禁止 `BASH_ENV`、`PATH` 或凭据注入。需要额外依赖时修改明确绑定，不依赖安装或启动时的隐式发现。
- 旧脚本中读取终端、全局声音服务或全局配置的行为可能被拒绝。不要据脚本退出 0 推断终端实际呈现已通过验证；原生测试需要另行确认。

通知串行执行，并把等待中的重复状态合并为最新状态。多个用户输入请求同时存在时，完成其中一个不会提前显示 working。退出最多等待通知 500ms，未结束的受管进程继续由正常 supervisor 关闭流程处理，不再排入新的通知。

状态通知是可选界面能力。失败会显示一次固定警告，不包含脚本原始错误、凭据或终端私有信息。目前只有隔离 mock 和类型检查证据，未连接真实 tmux/Zellij 或播放声音。
