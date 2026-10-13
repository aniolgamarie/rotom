# 使用 Pi 为指定项目集成 OpenSpec

Pi 的可选 `openspec` 能力使用锁定的 OpenSpec 1.11.0 CLI 与 12 个完整技能，与维护 rotom 仓库时使用的全局开发 CLI 分开。先在所选 Pi 配方的 `plugins` 中明确选择 `openspec`；本机数组覆盖须保留仍需启用的其他插件，配置方式见 [Pi 操作说明](pi.md)。DSH 不再提供 OpenSpec 初始化能力，DSH 依赖与自动注入已移除；新版证据和未完成门槛见 [DSH 升级验收](acceptance/dsh-upgrade-20261012.md)。

```sh
./agentcfg --local /private/pi-local.toml --profile pi-default sync
./agentcfg --local /private/pi-local.toml --profile pi-default project init openspec --path /path/to/worktree
```

命令在私人暂存目录用上游 `init --tools agents --profile core --no-animation` 生成，再检查指定项目的同名文件、清单和写前变化。不会扫描/初始化其他项目，apply/sync 不自动执行项目初始化。重复执行且内容一致时没有非必要写入；用户修改的同名产物会报冲突。

本实现采用上游支持的 `agents` 集成，生成 `.agents/skills/openspec-*`。上游 marker 的位置是 `.agents/skills/.openspec-target`；Pi 将管理器的 `.agentcfg-openspec.json` 摘要清单存放在所选工作树的受保护 Git 元数据 `agentcfg-project/` 中，不含账号或本地密钥。Pi 项目资源发现须按所选配方和权限策略显式配置，生成文件本身不代表已加载。

**必须在可核验的 Git 工作树根初始化**，包括 `.git` 为文件的 worktree。指向已有仓库的子目录会在写入前失败。Pi 的工作区写入保护要求真实 Git 工作树；管理器不自动替业务项目 git init。

生成与目标写入不是整个目录的原子事务；失败时已有产物保留用于检查。升级不自动删除旧版项目文件。撤下 DSH 能力也不会清理业务项目的 `openspec/`、`.specify/`、`specs/` 或 `.agents/skills/`。依赖锁失效、能力未选择或 CLI 未安装时明确失败，不借用用户全局 OpenSpec，不临时下载无版本包。

初始化命令由 Pi 后端核验能力选择、运行包和 OpenSpec 1.11.0 入口，并直接调用该锁定 CLI。DSH 后端未提供此能力时拒绝执行。首次加载和重复初始化的证据须对应所选 Pi 配方与当前锁，不能只以“OpenSpec 已安装”或历史 DSH 验收代替项目集成验收。
