# OMP 配方、身份和来源

本说明随 [OMP 实施](../specs/002-manage-omp-config/implementation-progress.md) 推进；隔离测试与原生验收分别记录。

## 两层 profile

| 项目 | rotom 配方 | OMP 原生 profile |
|---|---|---|
| 名称 | 公共 profile ID，例如 `omp-default` | `rotom-` 加配方 ID 的 SHA256 前 24 位 |
| 管理内容 | 所选公共资源及本机覆盖 | 原生配置、该环境的登录、会话和缓存 |
| 选择入口 | `agentcfg --profile ID` | 由受管启动 argv 的前置 `--profile NAME` 传入 |
| 所有权 | machine/local/state 绑定到物理实例 | 位于该实例独立 HOME 内 |
| 切换影响 | 选择另一独立实例 | 账号、会话和配置跟随实例；旧数据不搬迁 |

名称截断仅用于可读目录名；完整 ID、完整哈希及实际目录都参与归属核对。重命名公共配方会得到新身份，不能靠手工改 native name 接续旧账号。OMP 原生 default 与旧命名 profile 不会被收编。

## 目录和继承

```text
<instance>/
  .agentcfg-omp-owner.json
  .agentcfg-omp.lock
  user-home/
    .omp/profiles/<native-name>/agent/
    .config/
    .local/share/
    .local/state/
    .cache/
```

OMP 部分功能不只读取命名 profile，因此独立 HOME 与命名 profile 同时使用。原生默认快捷键继承若发生，只能来自该 HOME 的 `.omp/agent/keybindings.yml`；来源报告列出该路径与摘要，管理器不通过删改默认文件消除继承。

OMP 对 XDG 目录有存在性选择：若出现 `<XDG_CATEGORY>/omp/profiles/<name>`，有效路径可能改变。管理器只创建自身所需 HOME/XDG 基础目录，不创建这些重定向目录；发现此类布局变化返回 4，保留现场供用户处理。

原生选择优先级为显式`--profile`，随后`OMP_PROFILE`/`PI_PROFILE`；命名profile不等于`PI_CODING_AGENT_DIR`重定位。受管入口固定前置argv并拒绝冲突环境。原生default实际位于`.omp/agent`，不在`.omp/profiles/default/agent`。

不要在调用环境或 machine.environment 中声明 OMP_PROFILE、PI_PROFILE、PI_CODING_AGENT_DIR、PI_CONFIG_DIR、会话目录及 broker/gateway 控制变量。管理器生成受管身份环境，并拒绝会冲突的调用者覆盖。其他宿主的账号目录不会传给 OMP。

## 来源政策

默认禁止自动加载未声明的项目/外部配置。检查范围包含 cwd 的所有祖先；把工作目录移到含 `.omp`、`.agents` 或 dotenv 的目录下仍可能触发冲突。错误只显示来源类型与非秘密路径，处理方式是审阅并通过正式声明纳入允许资源，或选择没有冲突来源的工作目录。

需要项目技能或项目 MCP 时，在私人 local 的既有配方覆盖中设置：

```toml
[overrides.profiles.omp-default.agent_options.discovery]
project_resources = true
project_roots = ["/absolute/project"]
```

这仅允许声明根内经校验的技能/MCP，并持续检查最终链接目标、内容和秘密边界。项目规则、扩展、prompt、settings、认证及身份覆盖仍拒绝。来源政策或根列表变化需重新 apply；每次 spawn 前重新检查实际来源。若项目 MCP 要求凭据或未锁可执行程序，应使用受管声明处理，不能借项目来源绕过依赖和秘密要求。

原生技能从cwd向祖先发现`.omp/skills`；native MCP只读取cwd的`.omp/mcp.json`或`.omp/.mcp.json`。声明根不截断其上方的来源检查，两个MCP文件同时出现视为歧义。MCP仅允许无凭据HTTPS，或精确锁定Python和echo脚本的绝对命令；不接受env/header/auth/oauth/cwd覆盖或环境占位符。项目资源保持只读，报告只有路径和摘要。

例如先在公共`profiles/`登记`omp-work`和`omp-personal`两份OMP配方后，分别使用`--profile omp-work`和`--profile omp-personal`选择。它们得到不同实例和native name；用另一local或state_root指向已有物理实例会返回4。local只覆盖已登记ID，不能临时创建同名环境绕过归属。

## 生命周期和互斥

validate/render 只构造候选身份与配置意图；首次 plan 可比较空状态，不要求运行包或已部署 binding。首次 apply 创建并持久化新身份。run、capture、rollback 和受管 usage 必须使用已部署身份。

同一物理实例先取得实例锁，再取得管理状态锁。运行期间持锁到子进程退出；活动实例返回 4，管理器不终止进程抢占。换一个 state_root、local 或 machine 不能绕过归属接管同一目录。

出现 pending 后，先处理报告的冲突，再由显式 apply/rollback 恢复该实例自己的配置事务。`recover pi` 属于 Pi 专用运行租约恢复，不用于 OMP。
