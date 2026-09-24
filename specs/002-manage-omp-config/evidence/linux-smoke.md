# Linux x64 真实 OMP 无账号 smoke

日期：2026-09-24。结果：**通过（Linux glibc x64）**，对应 T061、V02/V09/V10/V22 的九行能力验收。Linux arm64、macOS x64/arm64 未执行，不能由本记录推定通过。

## 授权、环境与来源

用户在“是否授权 Linux 无账号 smoke”的具体范围询问后回复“下一步”，本轮据此执行。未登录、未查询真实 usage、未提交模型请求。执行者为主代理；gpt-5.6-luna / medium 只读核对固定源码 API，gpt-5.6-sol / medium 补充受审自检扩展，真实命令全部由主代理执行。

- OS：Linux x86_64，glibc 2.32；Python 3.11.11，复用原有 `.venv`，未安装 Python/Bun/Node 依赖。
- 管理器：基线 `e208e2df50c7f21095d2ec7eb081dfc4df4f7156` 加本次工作树；当前公开源复制到独立临时仓库，仅 `.venv` 链接回原工作树。
- 临时根：`/tmp/rotom-omp-smoke-nzudu7uu`；仓库 `repository/`、新 HOME `home/`、空工作目录 `workspace/`、证据 `logs/`。
- 配方：已在临时公共目录登记的 `omp-validation`，0600 local 只使用公开假值；未接触已有用户账号或会话。
- OMP：v18.3.0 / `62bc57be1b03ef0802a33cf7f5f530e534527531`；真实官方 standalone 文件 275801568 字节，实际 SHA256 **`d2fdaa29affe96e596eb9c78d42f548f1f291df28608631bcc00750a84b94bc3`**，与正式锁一致。
- 首轮临时锁 `64e715e7a4fe12742ed5252805a0e1a75f50034f2cc603a6606381e737bc0e43`；补充诊断后的正式锁 `0387bc982c13d768c77cf1be42b0243ebd0fabb0aa0a7ca9048e903d1d1134eb`，最终临时锁 `67abdc96435ffc99a0a2977ca7bf911f194080cf5995e89f3e32abed88509223`。差异来自临时配方登记，未豁免完整性检查。
- 最终 rotom-health 包摘要 `a382040f693dc402fdca39134a02e4c6ca158b8f23f6a8d495de486b840067ca`；echo-mcp 包保持 `c10617b101717ec6ce399da846e165d7a6f1cfb5c2aad02d2f6c405cd187faf4`。

宿主阶段使用 bubblewrap 最小根文件系统与 `--unshare-net`；系统/源码只读，只有本次临时根可写，原有 `/home`、`/root` 不挂载真实内容。使用 `strace -f -e trace=process,network` 保存实际进程/网络证据。隔离工具最初映射根目录属主为 nobody，管理器正确拒绝启动（4）；调整验收命名空间的挂载后运行成功，未放宽生产权限检查。

## 实际命令与结果

命令均在临时仓库执行，全局参数为 `--local <case>/local.toml --profile omp-validation`，父 HOME/XDG 仅指向临时目录。

1. 显式调用真实 `OmpBackend.resolve_lock`，输入此前下载的不可变 commit 归档和官方 SHA256SUMS，再 `read_lock` 复核；退出 0。
2. `validate`、`render`、`plan`：退出 0，28 个配置产物。
3. `sync`：真实官方下载/SHA/receipt 校验后 installed，退出 0。最初清空环境未带代理，直连等待 225.84 秒后主动终止本次子进程；仅下载步骤补入环境代理，11.56 秒完成。未给宿主继承代理。
4. `apply`：首次 28 项变化；第二次 0 项变化，两次退出 0。
5. `run omp -- --help`：在断网空间执行真实二进制，退出 0。
6. `run omp --cwd <case>/workspace`：真实 PTY 启动。首次原生 onboarding 五步均按 Esc 跳过，未登录或更换模型/主题；随后执行下表操作。两轮 TUI 均用空输入 Ctrl+D 正常退出，退出 0。
7. 自检扩展更新后显式刷新包摘要/正式锁与临时锁，再 `sync`、`apply`；使用已有 SHA 匹配的真实下载缓存，部署仅更新两处运行包路径，退出 0。
8. 最终 `doctor`：退出 0，`dependencies=installed`、`deployed_dependencies=installed`、`drift=false`、`changes_pending=0`、`recovery_pending=false`。

| 能力行 | 实际原生观察 | 结果 |
|---|---|---|
| provider/model | 原生模型选择器列出 omp-smoke/large-v1、omp-smoke/small-v1，容量 100k/32k；自检精确匹配 | 通过；未请求生成 |
| 模型角色 | Ctrl+P 从 default 的 omp-large 切到 smol 的 omp-small，再切回；自检精确解析 @default/@smol | 通过 |
| 两份规则 | `/rotom-health inspect` 从真实 ctx.getSystemPrompt 检查 rule-one、rule-two，两个布尔均 true | 通过；不输出系统提示正文 |
| 完整技能 | 原生补全发现 `skill:full-package`；系统提示包含技能标记；部署保留完整文件/相对资源/执行位 | 通过；未执行技能脚本 |
| 提示词 | 原生补全列出 `/rotom-review` 和预期中文描述，来源 user | 通过发现/可选择；未提交展开后的生成请求 |
| 主题 | `/settings` 显示 Dark Theme 与 Light Theme 均为 rotom-dark；真实主题 API 查找成功 | 通过 |
| 快捷键 | `/hotkeys` 显示 Ctrl+P=Cycle role models、Search prompt history=Disabled；Ctrl+P 实际切换角色 | 通过 |
| 扩展 | `/rotom-health` 输出 ROTOM_OMP_HEALTH_OK；后续 inspect 返回固定模型/主题和布尔值 | 通过 |
| MCP | `/mcp test echo-stdio` 连接 rotom-echo-mcp v1.0.0 并列出 echo；`/rotom-health mcp` 通过官方 SDK initialize/listTools/callTool 得到固定回声并断开，输出 ROTOM_OMP_MCP_OK | 通过；仅本地 stdio |

诊断扩展的 `inspect` 与 `mcp` 都是显式子命令。默认 health 行为保留；`mcp` 动态导入固定宿主提供的官方 `@oh-my-pi/pi-coding-agent/mcp`，没有自写协议替身或安装额外包。只接受当前原生 agent 目录内唯一的受管 echo-stdio 配置，固定回声与错误标记，不输出未知配置、系统提示正文或异常内容。最后 `/context` 显示 **Messages: 0 tokens**。

## 副作用与验证限度

- 进程证据仅包含管理器 Python、正式 OMP 和已锁本地 Python MCP；没有安装器进程，最终运行包完整性复核通过。上游动态 SDK 子路径已在真实 standalone 中成功解析。
- 宿主启动尝试 DNS，网络命名空间返回 ENETUNREACH；因此结论是“外网不可达且未执行模型请求”，不能写成“宿主没有任何网络行为”。日志还包含本地 netlink/Unix socket 查询及隔离命名空间内的 loopback 模型服务探测（首轮 10 次、第二轮见结构化记录），它们无法访问宿主网络中的真实本地服务。
- 原生首次设置、空认证存储/会话容器等运行状态仅位于本次新实例。没有从旧环境复制认证或会话，没有检查真实账号内容。
- 本轮只验证固定 Linux x64/版本/样例；不证明旧账号可用、真实 usage、模型服务、外部 HTTP MCP、Linux arm64 或 macOS。跨工具/旧 profile 的合成哨兵证据仍见隔离回归；此处不伪造真实旧账号哨兵。

## 证据与受影响回归

[结构化观察与原始文件摘要](linux-smoke-observations.json)保存原生命令输出的必要片段、逐项断言、二进制/锁身份及本地原始 PTY/trace/退出码文件的 SHA256。原始文件留在上述临时目录，未把完整会话或认证文件提交到仓库。

自检扩展刷新后资源/适配器/依赖/迁入组合先出现 1 项固定包摘要过期（其余 56 项通过），同步测试的精确包摘要后运行：

```sh
.venv/bin/python -m pytest -q tests/test_omp_resources.py tests/test_omp_adapter.py tests/test_omp_dependencies.py tests/test_omp_dependencies_foundation.py tests/test_omp_migration_flow.py --tb=short
```

结果 **57 passed in 10.30s**，退出 0。上轮全量 **2151 项及 7 子测试通过**是自检扩展新增前的证据，本轮未重复全量；新扩展由上述受影响回归及两轮真实宿主结果补充验收。
