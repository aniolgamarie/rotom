# 从旧OMP配置迁入新环境

迁入采用新环境：旧OMP的账号、会话、缓存和配置留在原位，新受管profile重新登录。管理器不提供原地接管或自动import命令。

先选择已经登记的OMP配方，并明确指定旧原生agent目录，例如原生default的`/absolute/old-home/.omp/agent`，或某个命名profile下的`agent`目录。不要传整个HOME。

```sh
./agentcfg --local /private/local.toml --profile omp-default inventory omp --source /absolute/old-agent
```

inventory只读明确来源，在所选配方私人cache的`inventory/<id>/`生成：

- `disposition.json`：每项设置/资源的纳入、原生保留、替代或排除，以及理由、目标、是否需审阅和候选包摘要。
- `local-overrides.toml`：仅包含已经声明且可映射的非秘密主题、快捷键和模型角色；不自动创建公共provider/model/resource ID。
- `resources/`：允许范围内经过路径、敏感模式和已知秘密扫描的候选规则、prompt、theme、完整技能包；所有候选都需要人工审阅。

候选文件为0600，目录0700；源脚本的执行位记录在处置清单，复制到获准公共技能目录后按该记录恢复。技能包作为整体检查，有敏感或不安全文件就不复制整个包，避免生成丢失相对依赖的半个技能。盘点不执行任何脚本或扩展。

认证库、trust、sessions、logs、cache和历史备份仅记录保留理由，不读取正文或复制。混合config/models/MCP文档只投影允许偏好；apiKey/auth等值不输出、不进入摘要。原生provider/model/MCP定义需要手工映射到严格公共声明，不能通过local偷建ID。未核实的旧扩展、Pi扩展和包依赖一律标记替代/需审阅，不因语法相似就认定兼容OMP。

自动扫描不能证明任意文本或脚本没有秘密。审阅候选正文、依赖和来源许可后，只将批准资源复制到`agents/omp/resources`、`shared/rules`或`shared/skills`，补充公共声明，再手工合并允许的TOML提案到私人local。

资源/配方变更后显式更新并审阅完整锁，然后安装包、预览和部署：

```sh
./agentcfg lock --agent omp
./agentcfg --local /private/local.toml --profile omp-default validate
./agentcfg --local /private/local.toml --profile omp-default render
./agentcfg --local /private/local.toml --profile omp-default sync
./agentcfg --local /private/local.toml --profile omp-default plan
./agentcfg --local /private/local.toml --profile omp-default apply
```

首次目标必须为空且可建立新所有权。非空未知目录或另一machine/local/state的归属返回4，不通过删除owner/锁或移动旧账号绕过。新旧管理器只写各自目标；出现pending时检查冲突，再由显式apply/rollback恢复本实例事务。rollback只恢复配置，不迁移认证数据库或降级宿主。

部署后，通过同一新身份显式登录：

```sh
./agentcfg --local /private/local.toml --profile omp-default run omp -- login openai-codex
```

该操作使用实例HOME、中性cwd和已锁定程序，不依赖无关MCP/API key，也不借用旧登录。日常运行选择该配方；需要回到旧环境时退出受管进程后，沿原来的原生启动方式使用旧HOME。旧环境从未由inventory改写。

相关说明：[配置](omp.md)、[profile身份](omp-profiles.md)、[依赖](omp-dependencies.md)、[验证范围](omp-support.md)。真实登录需要独立执行和记录，当前隔离测试不证明账号成功。
