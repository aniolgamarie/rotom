# 指定项目集成 OpenSpec

产品使用锁定的 OpenSpec 1.13.0，与维护 rotom 仓库时使用的全局开发 CLI 分开。

```sh
./agentcfg --machine workstation sync
./agentcfg --machine workstation project init openspec --path /path/to/worktree
```

命令在私人暂存目录用上游 `init --tools agents --profile core --no-animation` 生成，再检查指定项目的同名文件、清单和写前变化。不会扫描/初始化其他项目，apply/sync 不自动执行项目初始化。重复执行且内容一致时没有非必要写入；用户修改的同名产物会报冲突。

当前版本没有 DSH 原生目标。本实现采用上游支持的 `agents` 自定义集成，生成 `.agents/skills/openspec-*`，并由 DSH 原生技能发现机制读取。marker 的实际位置是 `.agents/skills/.openspec-target`；项目中的 `.agentcfg-openspec.json` 记录管理器生成文件的摘要，不含账号或本地密钥。

DSH 从最近 Git 根发现项目技能，故 **Git 项目必须在工作树根初始化**，包括 `.git` 为文件的 worktree。指向已有仓库的子目录会在写入前失败，避免出现“初始化完成却没有加载”的情况。非 Git 项目可初始化，但需从该目录启动 DSH；子目录不会自动成为同一个项目根。管理器不自动替业务项目 git init。

生成与目标写入不是整个目录的原子事务；失败时已有产物保留用于检查。升级不自动删除旧版项目文件。依赖锁失效或 CLI 未安装时明确失败，不借用用户全局 OpenSpec，不临时下载无版本包。

由 `agentcfg run` 启动的 DSH 会把当前锁定运行包的 `.bin` 放在子进程 PATH 前面，让生成技能里的 `openspec` 命令使用产品固定 CLI。首次加载和重复初始化的证据见验收记录，不能只以“OpenSpec 已安装”代替项目集成验收。
