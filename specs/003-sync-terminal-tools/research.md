# Phase 0 Research: termcfg

## 调查基线

- `starter` 来源固定为本机只读调查快照 `cc5b08bbdacd506192ef9ee08d7c64ef68274be9`；后续迁入须再核对每个文件摘要、许可和运行资源。该目录只是迁移来源，部署后不得依赖其路径。
- `starter/shell_config/install.sh` 对 `.zshrc`、`.tmux.conf` 和 tmux 脚本部署链接，给旧目标留时间戳备份；对 `.zshenv` 只改 marker 或首次写入机器路径；补全文件直接覆盖。它不是满足本规格的整文件复制、统一备份和事务恢复实现。
- `starter/skill/mihomo-mgr/scripts/mihomo-mgr.py` 没有 mihomo core 的固定版本安装器；默认 `start` 可能下载数据库、改写配置并启动统计 daemon。其 `config.yaml` 同时可含 `sub_url`、controller `secret` 和非秘密设置。旧脚本的服务调用必须经过适配，不能直接用作 `termcfg apply`。

## R1. 命令及部署边界

**Decision**: 增加独立的 `./termcfg`，沿用仓库 `.venv`、退出码含义与安全文件操作约定。普通用户使用已提交的锁；交互式 `apply/rollback` 内预览并确认，脚本模式才传预览 ID。`lock` 面向维护者显式解析完整远程依赖，`sync` 只准备既有锁中的版本化二进制和可选插件；`service` 是独立显式操作。同机器的 `init-local`、`sync`、`apply`、执行型 `rollback` 和服务写操作共用非阻塞独占活动锁；共享依赖锁另用按仓库规范路径定位的读写租约，维护者更新独占、`sync/apply` 以共享锁复核完整快照，冲突在写入前返回 4。`agentcfg setup/run` 不触发这些命令。

**Rationale**: 现有 Agent 实例配置的目标是隔离实例相对路径、0600/0700 文件和特定宿主字段；真实 HOME 下的普通文件、链接迁移、不同权限和用户服务需要另一套目标投影。直接放宽 Agent 的部署契约会扩大其所有权边界。日常操作不应要求用户复制多个快照 ID；机器可读参数只用于自动化。同机串行化覆盖读取状态、备份和提交，避免并发操作各自基于过期状态写入；但仓库锁跨所有机器共享，机器锁不能阻止两个维护者更新同一文件。独立仓库租约配合旧身份复查避免丢失更新，`sync` 下载后复查并持共享锁提交选择，避免选用过期版本；现有 OMP 运行包锁采用非阻塞 `flock`，可沿用其安全文件检查思路。

**Alternatives considered**: 直接调用 starter 安装脚本（无统一回滚、默认链接、目标覆盖方式不符）；将终端组件做成 agentcfg adapter（会把非 AI HOME 管理耦合到模型 profile）；复制现有 `deployment.py` 而不审查（其状态可能内嵌文件字节，不适用于未知敏感 HOME 文件）。

## R2. 来源及 mihomo core

**Decision**: 冻结经审查的 starter shell/mihomo mgr 源文件、测试和许可证到本仓库，并维护来源提交与内容摘要。mihomo core 使用官方发布资产的显式平台条目：版本、精确资产名、URL、长度和 SHA-256 必须进入锁；`termcfg lock` 显式联网解析完整锁，`termcfg sync` 只消费既有锁，暂存、校验后安装到版本化私人包路径。包目录为当前用户所有的 0700，清单声明的可执行入口为 0700，归档、元数据及非执行资源为 0600；激活前后复核属主、权限、链接和摘要。`apply` 只离线复制公开配置并核验 core 包已就绪，不下载、不搜索 PATH 中的任意 core；配置 rollback 不回退 core 软件版本。第一验收平台为 Linux x86_64；其他 OS/架构只有具备固定资产与独立证据才标为支持。

**Rationale**: starter 只把 core 当预装依赖，没有可复现版本。官方 [mihomo v1.19.31 发布页](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.31)展示稳定版本；官方 [资产命名说明](https://github.com/MetaCubeX/mihomo/wiki/FAQ)区分 OS、架构和 AMD64 指令等级。`v1.19.31` 可作为首个锁候选，但必须在制作锁时核对选中资产的真实字节与摘要，不能把发布页或“latest”当作安装成功证据。运行入口需要执行位，不能把私人配置文件的 0600 规则直接用于二进制；现有 OMP 包实现也区分 0700 执行入口与 0600 非执行资源。

**Alternatives considered**: 使用系统 PATH 中预装 core（无法保证版本或复刻）；运行时下载 latest（不可复现，且会把网络副作用引入 apply/service）；把大型二进制直接提交 Git（不利于审查与更新）。

## R3. 代理公开配置与私人运行配置

**Decision**: `termcfg` 只复制受管、非秘密的代理基础配置和 mihomo mgr 代码。私人 `mihomo-mgr/config.yaml`、订阅原文、生成的运行 `config.yaml`、controller secret、路由状态、日志、PID 与统计继续在当前用户独占的 0700 私人目录，由适配后的 mihomo mgr 管理。显式服务操作在私人目录中组合公开基础配置与私人值，以结构化 YAML 序列化器生成并校验仅供运行使用的 0600 私人有效配置；未填私人数据时仍可部署并诊断，但无法启动依赖它的服务。组合与验证不得写入通用渲染、摘要、同步记录、日志或备份。

**Rationale**: starter 现有 manager 设置和生成配置含混合字段，直接复制或备份整目录会违反项目秘密边界。官方 [mihomo 通用配置](https://wiki.metacubex.one/en/config/general/)包含 controller `secret`；[控制 API 文档](https://wiki.metacubex.one/en/api/)要求请求携带该值。公开基础配置不能假装为可直接启动的完整私人配置。

**Alternatives considered**: 对混合 YAML 作文本替换（易遗漏秘密或损坏结构）；把私人配置加密后放入普通备份（仍不符合“秘密不进入配置备份”的宪章）；不管理任何代理配置（不满足规格）。

## R4. mihomo 服务所有权和配置生效

**Decision**: `termcfg service start/stop/reload/restart/status` 只操作由本管理器明确启动并记录身份的用户态 core；未知进程或系统级服务只报告“外部管理”，不接管、不停止。启动前校验锁定 core、私人有效配置和运行条件；禁用 starter `start` 的隐式数据库下载、配置改写及统计 daemon 副作用，额外资源通过独立显式命令准备。`sync` 选定新 core 与 `apply` 更新配置分别记录待生效原因，均不重载服务；只有进程可执行版本、配置身份与健康检查均匹配才分别清除原因并报告“已生效”，否则为“未确认”。

**Rationale**: starter 的 PID 文件单独不足以证明进程仍属于同一个启动实例。官方 [控制 API](https://wiki.metacubex.one/en/api/)提供 `/configs` 重载及 `/version` 状态查询，但 API 204 不能单独证明服务加载了预期字节。官方文档还说明 Unix socket 控制端不验证 secret，因此若使用 socket，必须先验证其目录与 socket 的所有权/权限；默认可先采用 loopback 控制端与私人 secret。

**Alternatives considered**: 直接将 `mm stop` 用于任何同名 PID（可能误停用户进程）；apply 自动重启（与已澄清的用户要求冲突）；把 API 成功响应当作完整配置生效证据（会误报）。

## R5. HOME 文件覆盖、敏感内容与恢复

**Decision**: `termcfg plan` 为每个目标生成受限的非秘密投影和预期身份；已有未受管目标必须显式接管。`.zshenv` 是完整文件目标，按用户要求在覆盖前备份，旧文件有可辨识的非秘密自定义内容时展示脱敏影响类别并等待确认；拒绝则整个 zsh 组件零写入。源内容、目标快照和所有备份先通过非秘密准入检查；未知或疑似含秘密的目标在普通内容摘要与备份前阻断，要求用户先迁移秘密。单次 `apply` 中所有选中组件的配置目标备份必须在第一笔目标写入前完成，任一备份失败则整次调用零覆盖。使用同目录原子替换、写前复查、组件级所有权记录、pending 恢复日志和仅上一版配置备份；目标漂移时拒绝更新和恢复。

**Rationale**: 任意 shell 文件无法通过“未命中若干敏感关键词”证明无秘密。准入采用受限的非秘密文件类别与用户显式审阅；不能安全分类时拒绝。现有 `src/agentcfg/storage.py` 的 fd/no-follow、expected identity、原子替换思路可复用，但真实 HOME 的权限和链接类型不同，须有独立目标层。现有 `deployment.py` 的三方比较、pending/recover/rollback 语义可参考，不直接复用可能保存正文的状态格式。

**Alternatives considered**: 一律自动备份并覆盖（可能复制秘密/破坏用户内容）；对 `.zshenv` 仅改 marker（与澄清后的整文件覆盖要求冲突）；用时间戳 `.bak` 散落在 HOME（无法可靠判断所有权与最新备份）。

## R6. 插件、平台与验证

**Decision**: 迁入的 zsh/tmux 配置去除配置加载时的自动 `git clone`/插件安装。可选 zinit/TPM 等远程资料由显式 `lock --component zsh|tmux` 固定完整依赖，再由 `sync --component zsh|tmux` 安装；缺失时配置安全降级。同步不重载或关闭现有 zsh/tmux 会话。默认测试只在临时 HOME/XDG、假进程和阻断网络下运行；语法检查不得启动真实 tmux server 或代理。真实 core、网络订阅、真实 HOME 切换和 macOS 运行验证分别为显式步骤，未执行时报告未验证。

**Rationale**: starter `zshrc.zsh` 在初始化时可下载 zinit，`tmux.conf` 首次加载可后台下载 TPM 并重载；若原样复制，就算 `termcfg apply` 离线也会在下一次启动产生隐式网络副作用。旧安装脚本的 `STARTER_SHELL_TARGET_HOME` 隔离路径仍部署链接，不能证明新复制同步正确。

**Alternatives considered**: 保留隐式下载并仅文档提醒（失败进度和完整性无从保证）；默认运行真实 zsh/tmux/mihomo smoke（违反隔离测试约定）。
