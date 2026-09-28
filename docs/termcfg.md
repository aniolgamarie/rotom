# termcfg：终端和代理公开配置

`./termcfg` 与 `./agentcfg` 是独立入口。前者管理 zsh、tmux、mihomo 的公开 HOME 文件、固定运行包及自身启动的 mihomo 用户进程；不读取 Agent profile。使用 Python 3.11+ 和仓库 `.venv`，先执行 `uv sync --locked`。

## 日常流程

```sh
./termcfg components
./termcfg init-local                         # 终端中一次多选
./termcfg doctor
./termcfg plan
./termcfg sync --component zsh               # 按需准备固定插件
./termcfg sync --component tmux              # 按需准备固定插件
./termcfg sync --component mihomo            # 需要代理时准备固定 core
./termcfg apply                              # 现场预览、一次总确认
./termcfg status
```

首次初始化默认预选检测到本地程序的 zsh/tmux，mihomo 默认不选。`init-local --edit` 修改选择，显示旧值→新值；非交互环境须显式 `--component zsh`（可重复）或 `--none`。机器文件位于 `${XDG_CONFIG_HOME:-~/.config}/termcfg/machines/default.toml`，只保存机器 ID、目标 HOME、私人状态根和组件集合，文件 0600、管理目录 0700；[虚构格式示例](../examples/termcfg-machine.toml)不能直接用于真实 HOME。

`plan` 和 `doctor` 不下载或改 HOME 目标。`sync` 只消费已提交的 [mihomo core 锁](../locks/termcfg/mihomo.json)与 [插件锁](../locks/termcfg/plugins.json)，把运行包放到私人 XDG data 目录；目录 0700，归档/非执行资源 0600，需要执行的入口 0700。`apply` 只复制 [逐文件公开来源清单](../terminals/catalog.json)中的非秘密文件，不安装依赖，不启动或重载代理，也不切换现有 shell/tmux 会话。缺少某个 API key、订阅或私人代理配置，不阻止其它组件的 `plan`/`apply`。

维护者升级官方 core 时显式运行 `./termcfg lock --component mihomo --version v1.19.31`。升级单个插件时提供固定 40 位提交，例如 `./termcfg lock --component tmux --plugin tpm --version <完整提交>`；zsh 可省略 `--plugin zinit`。`lock` 会联网、校验完整归档并原子更新仓库锁，须审阅并提交锁差异；普通用户无需执行。`sync` 下载有阶段进度，默认 10 秒连接超时和 300 秒总时限，`--timeout` 接受 10–3600 秒。长等待每 1.5 秒报告阶段心跳。

## 首次接管、备份与恢复

现有未受管文件即使内容等于公开来源，也需明确接管。交互式 `apply` 会列出每个目标 ID、操作及备份安排，确认一次即可接管全部列出的目标并执行；自定义非秘密 `.zshenv` 因整文件覆盖另需一次确认。疑似包含 secret、订阅或无法分类的旧目标在计算普通摘要和备份前停止；先把私人值迁入独立 0600 文件，再重新 `plan`。旧 starter 链接仅按声明目标接管，备份保存链接本身。

脚本模式分两步，ID 必须来自当次预览，目标变化后重新预览：

```sh
./termcfg plan --component zsh --json
./termcfg apply --component zsh --plan-id <当前计划ID> --adopt-target <目标ID> --confirm-zshenv <当前计划ID>
```

如果没有旧目标，可省略 `--adopt-target`；如果无需覆盖自定义 `.zshenv`，可省略专门确认。`apply` 在整次调用的旧配置备份完成并校验后才覆盖第一份目标，逐文件原子替换并记录私人 journal。成功且有实际变更时只保留上一版配置备份；重复无变化调用不轮换。目标被用户改动后拒绝静默覆盖。中断后执行 `./termcfg status` 看待恢复事实，再执行 `./termcfg recover`；恢复再次复核文件身份，外部改动会阻止自动恢复。

```sh
./termcfg rollback --component zsh              # 交互预览并确认
./termcfg rollback --component zsh --plan-only --json
./termcfg rollback --component zsh --plan-id <回滚专用ID>
```

回滚只恢复最近一次成功同步前的**公开配置**；若原目标不存在，则在确认仍归管理器且未漂移后移除。它不降级 mihomo core 或插件。回滚期间断电同样留下 journal，使用 `recover` 恢复写入前版本。

## 私人代理配置与服务

公开 `base.yaml` 只定义本地端口和安全默认值。显式 `service start/reload/restart` 才读取 `${XDG_STATE_HOME:-~/.local/state}/termcfg/machines/default/mihomo/private.yaml`，用结构化 YAML 合并并在同一私人 0700 目录写入 0600 的 `effective.yaml`。`service status/stop` 不读取订阅正文。私人 YAML 可以有 `proxies` 或 `proxy-providers`、`proxy-groups`、`rules`、`rule-providers`、`dns` 和 `secret`；需非空 controller secret，以及 `proxies` 或 `proxy-providers` 至少一个。不要把含密钥的配置提交到 Git。旧 `mihomo-mgr/config.yaml` 与 termcfg 私人运行文件独立，旧 mgr 的进程/API/订阅入口已禁用；迁移时手工审阅后把需要的私人值放入 termcfg 私人 YAML。

```sh
./termcfg service status
./termcfg service start
./termcfg service reload
./termcfg service restart
./termcfg service stop
```

服务命令只接受本管理器的租约，核对 UID、PID、进程开始身份和可执行文件。外部服务、PID 复用或控制端口被占用时拒绝接管。`sync` 新 core 与 `apply` 新公开代理配置分别持久记录 `pending_core_effect` / `pending_config_effect`；文件同步不向运行进程发信号。显式服务操作检查进程与控制 API 后，仅在证据充分时清除对应原因；证据不足显示 `unverified`。启动健康失败会尝试终止刚启动且身份仍匹配的子进程，保留可诊断状态。

## 诊断与退出码

`doctor` 默认逐组件显示 `ready/blocked/degraded/unverified`，并返回 0；`doctor --strict` 对必需阻断返回非零。`status` 分开显示文件、备份/恢复、运行包、两种待生效原因和服务租约。阶段进度输出到 stderr，最终摘要输出到 stdout；`--json` 的 stdout 只有一个最终 JSON 对象，不含私人 YAML、URL、密钥、文件正文或原始子进程 stderr。网络与服务等待显示阶段和心跳，失败包含原因码与下一条命令。

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功；只读诊断可能同时显示降级或待生效。 |
| 2 | 参数、机器文件、来源清单或锁格式错误。 |
| 3 | 显式服务操作缺私人配置或必需凭据。 |
| 4 | 所有权、漂移、并发活动、快照过期或待恢复冲突。 |
| 5 | 必需环境、依赖资产或服务健康检查失败。 |
| 6 | 文件系统/内部失败或受控中断；先看 `status`。 |

默认验证使用临时 HOME/XDG、假 core/API/子进程及网络阻断，命令与结果见 [隔离验收记录](termcfg-acceptance.md)；规格逐项核对见 [实现复核](termcfg-review.md)。真实 HOME、core 运行、订阅和 tmux server smoke 须另行明确授权，当前不在默认测试中。
