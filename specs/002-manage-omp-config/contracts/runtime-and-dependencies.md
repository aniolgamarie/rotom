# OMP 运行与依赖契约

> 验收归属以[范围修订](../scope-change-20260924.md)为准：当前保留软件隔离契约与 Linux x64 无账号原生验收；其他平台实机和真实登录/usage/模型调用转独立遗留。原有产品接口、平台选择实现与安全边界保持要求，转出不等于验证通过。

固定基线、源码路径和发布摘要见 [research.md](../research.md)。本契约不表示宿主已运行通过。

## 目录与身份

```text
<instance>/
├── .agentcfg-omp-owner.json
├── .agentcfg-omp.lock
└── user-home/
    ├── .omp/
    │   └── profiles/<native_name>/agent/
    │       ├── config.yml, models.yml, keybindings.yml, mcp.json
    │       ├── RULES.md, skills/, prompts/, themes/
    │       └── 原生 auth/session/cache 等运行数据（不属于配置备份）
    ├── .config/
    ├── .local/share/
    ├── .local/state/
    └── .cache/
```

owner 文件保存完整 binding，权限0600；私人目录0700。生命周期 hook 先锁物理实例，再进入既有 state lock，统一顺序，不允许另一个 state_root 绕过活动锁。所有修改命令及 run/managed usage 使用相同顺序；子进程存活期间持有 lease。锁冲突立即失败4，不杀其他进程。sync 只操作 cache，包激活与 run 的包引用保护另由 backend 保证。

原生 profile 名只通过最前方 `--profile NAME` 传入；清除并拒绝用户提供的 OMP_PROFILE/PI_PROFILE、PI_CODING_AGENT_DIR、PI_CONFIG_DIR、profile/目录覆盖及 broker 控制。HOME 与四个 XDG 目录由管理器生成；任何 machine.environment.values/inherit 或调用者环境中的冲突身份变量在 spawn 前返回2。其他宿主身份变量不传给 OMP。不能简单复用 Pi 的 PI_CODING_AGENT_DIR。

仅支持 `profile-root` 布局。任何会使 OMP 选择 `XDG_CATEGORY/omp/profiles/NAME` 的目录出现时失败4；计划/检查解释实际路径与预期差异，不自动搬迁或删除。中性 cwd 为实例 HOME，用于 managed usage/login/信息操作；普通会话使用 manager 的 --cwd。原生 default keybindings 若被读取，只来自隔离 HOME 的 default agent 目录；管理器不修改默认文件消除继承，并报告其路径和摘要。

## 来源准入与环境

上游固定版本没有完整关闭 project 的总开关，因此选择“可关闭项明确关闭，剩余来源启动前拒绝”的设计。使用 native provider 承载受管资源，enabledProviders=[] 不视为已完全关闭发现。disabledProviders 使用固定 discovery 注册表，外部工具和插件来源默认禁用；该列表还可能影响同名模型 provider，首版能力映射避开未经适配的冲突。

源码发现清单应随适配器版本锁定为可测数据，至少覆盖以下层面：

- HOME、profile/config root、agentDir 和 cwd 的 `.env`；按固定 env.ts 识别路径，保守拒绝相邻已知 dotenv 变体，不读取/显示值。
- cwd 与祖先至文件系统根的 `.omp` 资源/配置路径，以及 `.agent`、`.agents`、AGENTS.md、CLAUDE.md 等上下文来源；不只检查 cwd 单层。
- `.claude`、`.codex`、`.gemini` 等外部目录和 direct helper 读取的 TITLE_SYSTEM.md；不能只禁用 provider 而漏掉直接读取路径。
- 活跃 profile、隔离 default profile 的 settings/rules/skills/prompts/extensions/hooks/tools/MCP 等入口；auth DB/session/cache 等已知运行文件不当作非法配置。
- auth broker/gateway 配置与保留环境变量；保护身份、原生目录和禁用来源的字段。

默认发现实际可加载的未声明来源即失败4，错误只报路径与类别。`project_resources=true` 加上 project_roots 才能允许明确来源；根内仅准入能力契约支持的只读非秘密项目 skills/MCP；项目 rules/prompts/extensions/settings 等其他来源本版仍拒绝，禁止覆盖身份、认证或保护设置。所有加载入口、链接最终目标和摘要进入非秘密来源报告；不是“一个开关接受该目录全部配置”。项目文件变化重新校验并更新本次报告，不自动修改已部署绑定；policy/根列表的变化需要重新 apply。

发现检查在 spawn 前再次执行，与文件写前检查一样防止普通检查/使用间漂移。该边界不提供 OS sandbox，也不保证抵御同用户恶意并发写入、宿主内用户主动操作或任意扩展代码；不能在文档里把 preflight 称为完全禁网/隔离执行环境。固定源码发现路径的漏项由隔离哨兵和授权 smoke 阻止支持声明；不能为通过测试而放开未知来源。

普通 launch 按已部署引用解析必要 SecretRef。managed usage/login 不需要普通会话的 MCP/API key 时完全不解析；原生自身认证仅在同一新 HOME 中使用。运行 auth broker 与 gateway 共享认证在首版拒绝，避免 discoverAuthStorage 切换到其他认证池。

## 启动门控顺序

1. 分类操作与解析参数；拒绝身份/目录/secret/不支持子命令，校验 cwd 和平台。
2. 读取已经部署的 runtime binding；获取物理实例 lease 与 state lock，核对 owner、当前 machine/local、实际根及身份。
3. 检查 pending、配置受管投影、凭据守卫、来源政策及 runtime digest；无包为5，活动/保护/恢复冲突为4。
4. 校验运行包内容和原生有效路径，执行来源 preflight，构造最小操作环境；只在这里解析实际需要的秘密。
5. 临近 spawn 复查来源/关键路径；直接 argv 启动固定二进制，继承原生流并保留退出码，持锁至退出。

run 不能触发 sync/apply/login。默认 doctor 只检查上述可离线静态判断的项，不打开 auth DB、不探测账号网络；缺登录可记“待登录/未知”，不能假定成功。doctor --live 沿公共服务探测边界，不能代替宿主或账号验收。

## 完整依赖与安装

计划新增 `schemas/omp-lock.schema.json` 与 `locks/omp/manifest.json`，并保存 `locks/omp/upstream/bun.lock`、来源/许可证清单。锁包括：

- host tag、不可变 commit、对应提交源码 URL/SHA；各支持平台官方 release asset URL/SHA。
- 上游完整 Bun lock 原文及 SHA、发布构建来源、嵌入宿主运行时与依赖的说明；不声称可以从官方二进制反推出完全可复现构建。
- 适配器 schema/version，所有本地资源/扩展/fixture 的规范文件清单、正文 SHA、执行位与树摘要。
- 所有实际需要的外部程序。首个 MCP fixture 使用私人环境中显式准备的 Python，记录精确版本、规范路径和程序内容身份；run 不去 PATH 寻找替代。

官方 standalone 运行不要求系统 Bun/Node。首版不引入宿主补丁，也不引入含未闭合第三方依赖的扩展；OMP 自带可选 ML/browser/speech 等按需安装功能不在允许启动配置内。固定 `startup.checkUpdate=false`、`marketplace.autoUpdate=off`、`autolearn.enabled=false`，普通启动加 `--no-title`；默认启动不下载仍须通过源代码调用链与授权 smoke 证实。

`lock --agent omp` 是唯一更新解析结果的入口：显式获取固定来源、核实 tag/commit、完整上游锁和 asset hashes，写入可审阅锁。`sync` 只消费锁，可联网获取缺失的指定产物，离线有缓存时不联网；不执行宿主、不读取旧 HOME、不更新锁。每个包先在私人 cache 临时目录下载/展开/校验，拒绝越界/链接/入口缺失，生成 receipt 后原子切换激活指针；失败保留上一包。读取验证不能只依赖 marker、mtime 或大小。

平台固定 Linux glibc x64/arm64、macOS x64/arm64，具体发布 SHA 以 research 表为初始审阅依据。musl/Windows 在 sync/run 前失败5。macOS 尚无实机证据；有 URL/校验和不等于平台已验证。

## 部署恢复与回滚

复用公共 deployment 的字段/文件三方比较、pending、previous 与原子单文件替换。owner 初始化也必须纳入可恢复流程：中断留下 owner/pending 时，不能误认成可自动接管的新目录。秘密分类器在历史快照、pending 与回滚路径同样执行。

配置 pending 沿既有 deployment.recover，由下一次显式 apply/rollback 在持锁后执行；plan/run/usage 遇 pending 返回4。恢复只处理自身 owner/配置事务，不迁移原生数据库。现有 `recover pi --lease ...` 是 Pi 执行租约恢复，不是公共部署恢复；本次不复用该命令、不移植 Pi 进程停止语义。操作前持续核实 instance/state 的双方归属。配置 rollback 只恢复上一配置并消费备份，不自动降级宿主、不迁移 auth DB；旧配置依赖不匹配时阻止后续 run，并提示显式准备匹配包及重新部署，不能隐式切换软件。

## 用量与遗留问题

AGENTCFG-F01 用原生 usage 薄封装实现，不引入订阅采集器。固定版 registry 有 zai、kimi-code、openai-codex，不能据此宣称支持国内 `zhipu-coding-plan` 额度。国内官方助手虽提到 usage 插件，本次专用页面不可读且未证实 OMP 集成；实施前再核实官方资料，保留“未验证/上游不支持”的原生结果，不将空结果改为0。

完成实现后才更新 `docs/follow-ups/agentcfg-usage-command.md` 和总表，链接实际测试、平台与账号限制。`docs/dsh-cursor-auth-deficiency.md` 与 secrets 同文件问题不随 OMP 计划关闭。
