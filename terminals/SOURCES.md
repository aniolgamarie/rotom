# 公开来源与迁移审查

调查基线：`/root/gitLocal/starter` 提交 `cc5b08bbdacd506192ef9ee08d7c64ef68274be9`。此绝对路径仅标识调查来源，不是部署依赖。mihomo mgr 的原许可为 MIT，见 `mihomo/LICENSE`；shell 配置没有独立许可证声明，按本仓库自有配置迁移。

| 旧文件 | 旧 SHA-256 | 决策 |
| --- | --- | --- |
| `shell_config/zshrc.zsh` | `afac35d41450165f8dd4847c1f18ed671729beb1f7ff75c2116aff670b8f706d` | 改写为精简的公开 `zsh/zshrc.zsh`；移除 Zinit 自动 clone、自动插件下载、starter 路径和机器专属设置。 |
| `shell_config/tmux.conf` | `f997a38c46ba231bec9a72769938985fe4f5670b631c8d1385f3a42e7442ce77` | 纳入 `tmux/tmux.conf`，移除 TPM 自动 clone/安装；已有插件仅有条件加载。 |
| `shell_config/scripts/fzf-window.sh` | `ee2e4cdf5aa12e612a5f61ed3aa8589bc845c25df178cd8ece3db6ef91e5412b` | 原样纳入公开辅助脚本。 |
| `shell_config/install.sh` | `864bf94fbfe70b9e88ba07c19699ed2c32ebd41ddc886b54482423de607719ca` | 排除运行时；旧脚本创建链接、逐文件时间戳备份、局部编辑 `.zshenv`、覆写补全，缺少统一事务。 |
| `skill/mihomo-mgr/scripts/mihomo-mgr.py` | `ab24db8c27103a3d1fd0a1944cb19f2545d94c820f87b87e83f342de21016430` | 纳入公开代码，仅保留私人配置编辑和静态补全入口；旧进程/API/订阅命令禁用，新服务操作由 termcfg 管理。旧启动可隐式下载数据库、改写运行配置、启动统计守护。配置写入改为私人 0700 目录、0600 原子文件。 |
| `skill/mihomo-mgr/LICENSE` | `54a890936235fe1a084154e39beefaa39a33ee7935ce03a9c6f7187f0bddd3fc` | 原样保留 MIT 许可。 |
| `skill/mihomo-mgr/README.md` | `7c14166e489532a0925e44394ed04ff0bfdd3fd5e391ce0191a0519041ab5575` | 排除部署；旧命令和目录与新所有权契约不同，迁移说明见 `docs/termcfg.md`。 |
| `skill/mihomo-mgr/SKILL.md` | `c8755d131181594ac87bf1e3e192190b3995d1b422f7cca1f82c20492411edd6` | 排除部署；旧交互包含隐式服务/订阅副作用。 |
| `skill/mihomo-mgr/docs/local-routing.md` | `c0cb19076d51de709a06cbbec68565357b33d8e6ed255e27fb6227e7432f7a83` | 排除部署；旧私人路由状态不属于公开同步目标。 |
| `skill/mihomo-mgr/docs/traffic-stats-design.md` | `06a287fa4be7c5242a113bdd73239746b38367a43672b698bde3890592fbb0df` | 排除部署；统计数据和守护逻辑不在首版服务范围。 |
| `skill/mihomo-mgr/scripts/test_gfwlist.py` | `a5eca40d1c9651f883c505b6311c528ec32aa6e56d9e92beb871263b5fb8b1e4` | 排除部署；旧网络功能未接入。 |
| `skill/mihomo-mgr/scripts/test_doc_sync.py` | `691f4eadff704f8e79b544098bbb809d24e5b7c17499baf49bbab3ff8bcdd78a` | 排除部署；校验旧文档。 |
| `skill/mihomo-mgr/scripts/test_mihomo_mgr.py` | `8a95cc3db57c1664325b58f8b41443b64492fb74e8308187335ce183bee3b94a` | 排除部署；新隔离测试独立编写。 |
| `skill/mihomo-mgr/scripts/test_mihomo_mgr_enhanced.py` | `dfd4820ca3c87738a61fba5d592c0a6aca4844c964b95690bd7f041d3bf50a5f` | 排除部署；包含旧服务语义。 |
| `skill/mihomo-mgr/scripts/test_routing_policy.py` | `c9d318dfd0680c1fed5a82c7078994acd7210c94d24fea37adb5109448733f80` | 排除部署；旧路由私有状态未接入。 |

旧 mgr 的 `config.yaml`、订阅缓存、有效代理配置、路由状态、日志、PID、统计库均排除；它们可能含订阅 URL、凭据或私人流量信息。shell 启动和 tmux 加载均不得自动安装远程插件。公开目标的最终来源摘要固定在 `terminals/catalog.json`。
