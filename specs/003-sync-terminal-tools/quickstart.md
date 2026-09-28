# termcfg 验证指南

本指南记录实施后的隔离验收路径；实际命令与结果另见 [验收记录](../../docs/termcfg-acceptance.md)。先在仓库内准备 `.venv`，所有默认验证使用临时 HOME/XDG、假进程和阻断网络。目标和状态语义见 [数据模型](data-model.md)及[命令契约](contracts/cli.md)。

## 1. 隔离环境和三命令预览

在测试 shell 中创建临时目录，并让整个验证过程的 HOME、XDG 和代理私人目录指向该目录。不要复用真实用户的 HOME 或正在运行的 mihomo。实现验收时，用测试 fixture/脚本确保子进程、网络和绝对路径都被隔离。

```bash
test_root="$(mktemp -d)"
mkdir -p "$test_root/home" "$test_root/xdg-config" "$test_root/xdg-state" "$test_root/xdg-cache"
export HOME="$test_root/home"
export XDG_CONFIG_HOME="$test_root/xdg-config"
export XDG_STATE_HOME="$test_root/xdg-state"
export XDG_CACHE_HOME="$test_root/xdg-cache"
```

创建机器选择后，在离线环境用以下三条 `termcfg` 命令取得三组件环境结论和逐文件预览：

```bash
./termcfg init-local                         # 交互 TTY 一次多选
./termcfg doctor --component zsh --component tmux --component mihomo
./termcfg plan --component zsh --component tmux --component mihomo
```

`init-local` 在一次多选中显示默认组件与检测结果；本场景明确选中 zsh、tmux、mihomo 并核对保存结果。默认只预选检测到必需程序的 zsh/tmux，mihomo 不默认启用；选错或暂时选空后用 `./termcfg init-local --edit` 调整，编辑时先显示旧值与新值，不改 HOME 文件。`doctor` 应分别显示 ready、blocked、degraded、unverified 和下一条命令，并给出整体结论；`plan` 应列出每个声明目标的来源、操作和备份安排。只读命令不创建受管 HOME 目标、不下载 core、不启动服务。缺少锁定 core 缓存时，mihomo 的 `apply` 是阻断项，zsh/tmux 仍可独立预览。若开发中的机器配置有非交互 fixture，可用 fixture 代替 `init-local`，但三命令用户路径仍须验收。

非 TTY 环境应明确调用 `./termcfg init-local --component zsh --component tmux --component mihomo`；空选择使用 `--none`，不默选。

## 2. 普通安装与维护者更新锁

仓库已有锁时，普通用户只在需要 core 或可选插件包时执行 `sync`，随后直接运行交互式 `apply`。`apply` 会现场展示预览与需接管目标，无需先复制 `plan_id`。例如代理组件：

```bash
./termcfg sync --component mihomo
./termcfg apply --component mihomo
```

只有维护者决定更换共享版本时才执行 `lock --component mihomo --version VERSION`，审阅 `locks/termcfg/` 的变化后再执行 `sync`。`lock` 会修改仓库公开锁文件；`sync` 只安装包；`apply` 只处理配置文件，三者均不自动重载服务。缺锁、缺包、缺私人凭据时，CLI 应给出当前阻断原因与下一条命令，不让用户从静默等待中猜测。

## 3. 文件同步与回滚

在隔离 HOME 中准备一个虚构、非秘密的旧 `.tmux.conf` 和自定义 `.zshenv`，并记录原内容与权限。交互式 TTY 直接运行：

```bash
./termcfg apply --component tmux --component zsh
./termcfg status --component tmux --component zsh
./termcfg rollback --component zsh
```

`apply` 现场列出预览、需接管目标及备份位置；一次总体确认涵盖所列目标接管与执行，自定义非秘密 `.zshenv` 再单独确认一次。`rollback` 现场预览后一次确认。期望：本次调用中所有选中组件的配置备份先于任一目标替换，已选目标复制为公开来源内容，未选 mihomo 目录和运行数据不变；重复 `apply` 不改写、不轮换备份；回滚恢复原 `.zshenv` 内容和必要权限，不切换 core/插件软件版本。拒绝 `.zshenv` 确认时，zsh 所有目标维持原样。

非交互脚本才使用只读预览 ID：先 `plan --component zsh`，再用该预览的 `plan_id` 和每个待接管的 `target_id` 调用 `apply --component zsh --plan-id PLAN_ID --adopt-target TARGET_ID --confirm-zshenv PLAN_ID`。回滚前单独执行 `rollback --component zsh --plan-only` 取得回滚专用 ID，再执行 `rollback --component zsh --plan-id ROLLBACK_PLAN_ID`。ID 均来自当次实际输出，目标变化后必须重新预览。

## 4. 故障、耗时与秘密边界

下表是隔离验收矩阵。现有 `tests/test_termcfg_*.py` 使用临时 HOME、虚构数据与网络阻断；每项的实际覆盖和仍缺的证据以[验收记录](../../docs/termcfg-acceptance.md)为准。

| 注入条件 | 期望证据 |
| --- | --- |
| 目标在 `plan` 后改动或变成 symlink/硬链接 | `apply` 写前停止，报告冲突；保留目标和备份。 |
| 旧目标疑似含密钥、订阅 URL 或无法判定 | 拒绝普通备份与接管；输出只给原因码和迁移建议，不含正文。 |
| 多组件调用中后一个组件备份空间不足，或来源摘要不匹配 | 本次调用的全部配置目标变更数为 0，定位到具体组件和目标。 |
| 写入中断或回滚中断 | `status` 区分已写、未写、待恢复，journal 可继续诊断，无虚假成功。 |
| 同机器 `init-local`、`sync`、`apply`、执行型 `rollback` 或服务写操作并发 | 至多一个进程持有活动锁；分别注入 `sync` 与另一 `sync/apply`、`service start/reload` 与 `sync/apply` 的竞争，后到者在写入前返回 4，给出操作和重试命令；包、状态、备份和 HOME 目标不交错。只读预览仍可报告活动操作。 |
| 同仓库两个维护者 `lock`，或维护者 `lock` 与 `sync/apply` 并发 | 第二个更新旧身份失效时返回 4，不覆盖前者；下载中锁变化使 sync 在所选版本提交前返回 4，已校验包可留缓存；apply 在持共享租约写入期间不接受换锁，HOME 与状态不基于过期锁提交。合法 machine_id 与仓库锁名称相同也仍使用不同锁文件。 |
| 交互式 `apply` 预览后等待确认时仓库锁变化 | 等待期间仅持机器锁；用户确认后再取仓库共享锁并复核锁、来源、目标和状态，快照过期返回 4 且不写 HOME。 |
| 执行型 `rollback` 与同机器 `apply/sync` 并发 | 后到的 rollback 在写入前返回 4，目标、备份和 journal 字节保持不变，不因持锁方的阶段变化误报成功。 |
| core 缓存缺失、平台无锁、必需命令缺失 | mihomo `apply` 阻断；zsh/tmux 独立操作不受影响。 |
| `sync` 完成或包缓存权限/属主/链接被篡改 | 版本化包目录 0700、可执行入口 0700、归档和非执行资源 0600，均归当前用户；异常包不得被激活或用于 `apply/service`。 |
| `sync` 选定新 core、`apply` 更新代理配置而旧服务仍运行 | US1 的私人 `EffectState` 与 sync/apply 最终摘要分别保留 core、配置待生效原因；失败或无变化不新增原因。US3 的 `status` 分别报告原因；`reload` 不能仅凭配置已加载就清除 core 待生效，重启后须核验进程可执行版本。 |
| US1 阶段写入、状态提交中断或重复更新 | 三方比较拒绝漂移；所有目标备份先于覆盖，成功变更只保留上一版配置备份；中断留下可诊断恢复记录，无变化/失败不轮换备份，也不报告整体成功。此阶段只建议已可执行的诊断命令，不建议尚未提供的服务命令。 |
| 服务 PID 复用或存在外部实例 | `service stop/restart` 不发终止信号，报告 `unknown/external`。 |
| `service start` 或需新配置的 `reload/restart` 生成私人有效 YAML | 仅在私人 0700 目录以当前用户所有的 0600 普通文件生成；`status/stop` 不读订阅，普通日志、状态、摘要和备份中无其秘密内容。 |
| 代理配置同步时假服务正在运行 | 不调用 reload/restart，标记 `pending_effect`。 |
| 可选插件/工具缺失 | 标为 `degraded`；`apply` 和配置加载不联网，只有显式 `lock`/`sync --component zsh|tmux` 可获取插件。 |
| 假下载长时间无数据、下载中断或服务健康检查超时 | 每 2 秒内有阶段或心跳；在声明时限内退出，报告已修改的包/服务状态及可直接执行的重试命令。 |
| `doctor --strict --json` 遇到必需阻断项 | stdout 为单个可解析 JSON 最终结果，包含 `overall_ready=false`、逐组件 `ready=false` 和 `next_command`；stderr 进度不混入 stdout，退出码非零。 |

默认测试入口为：

```bash
.venv/bin/pytest -q tests/test_termcfg_*.py
```

## 5. 独立的真实环境验收

真实 HOME、真实 mihomo core、订阅网络、tmux server 或插件下载属于单独显式步骤，须用户明确授权后运行。验收记录应区分文件同步成功、core 可运行、私人配置就绪和服务已生效；不能用无订阅的假 smoke 冒充真实服务证据。真实验收前先看 `doctor`/`plan` 的完整目标清单与备份位置，再选择组件操作。
