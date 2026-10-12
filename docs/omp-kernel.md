# 在 WSL 使用 omp-kernel

`omp-kernel` 是日常使用配方；`omp-default` 是继承八个官方可选型号的基础配方（Kimi Code 四个、GLM Coding Plan 两个、DeepSeek 两个），初始主模型为 Kimi Code。本文给出从私人机器文件到受管启动的完整步骤。当前仓库已验证 Linux glibc x64 的通用 OMP 能力，但没有可用的 WSL 远程环境，因此本文步骤不能算作 WSL 实机通过证据。

## 配方内容

公共配方 [`profiles/omp-kernel.toml`](../profiles/omp-kernel.toml) 选择三个 TF provider 和十一条 TF 模型绑定，包含 `anthropic-messages`、provider compatibility、模型成本、thinking 等级和 fallback chain 的原生映射。它还部署：

- 76 条 Bash 审批 pattern；保留 5 条 interceptor 配置但默认关闭，避免普通已审查命令因工具偏好失败；
- 5 个 agent、4 个完整 skill，以及作为受管原生 `RULES.md` 原文部署的确认规则；
- Kanagawa 主题、状态栏及其他受支持的界面设置；
- `default/smol/slow/plan/task` 五个模型角色；
- 公共 `agent_options.tiny_model` 选择 `local/lfm2.5-230m`，渲染为原生 `modelRoles.tiny`。

这是按当前 adapter 支持字段重新表达的配置，不是原有 HOME 的逐字复制。迁入时已删除与 `mdLink` 重复且不符合固定 schema 的 Kanagawa `link`，排除 skill 中的 `.bak` 备份，把 codex skill 的 runner 示例改为相对已安装 skill 目录解析，并把验收 fixture 的假 token 标成明确的 `SYNTHETIC` 哨兵。

旧原生 kernel 配置、账号和会话保持原位。首次 `apply` 创建新的受管实例 HOME 和由 `omp-kernel` 完整 ID 哈希得到的原生命名 profile；管理器不会复制旧账号、会话或认证存储。

## 独立权限插件与模型选择

当前仓库使用官方未改动 OMP 与本地 `omp-permission-control` 插件，遵守[不修改 agent 上游源码的原则](architecture.md#基本原则上游宿主保持原样)。插件提供独立 `permission_bash`，在工具执行函数内部完成审批后才调用公开执行 API；原生 Bash 保持 prompt。模型审查命令语义，普通 `ls -la` 不再受到旧宿主读取证明的选项限制。明确配置的禁止/人工规则仍保留。

当前固定官方 OMP v18.8.6，升级验证见[当前验收](acceptance/omp-upgrade-18.8.6.md)；v18.4.5 的历史升级验证见[验收记录](acceptance/omp-upgrade-18.4.5.md)。公共 kernel 配方设置 `display.hideToolActivity=false`，显示工具活动；在界面切换工具可见性会持久化该字段，长期调整应写回公共配方或私人机器覆盖后部署。

执行模型在 OMP 会话中选择。权限主审优先使用显式 `reviewer_model`；kernel 公开默认固定为 `omp-zhipu_tf-glm-5.3-flash`，私人覆盖优先。未配置主审时仍绑定当前会话执行模型；私人覆盖可显式设 `reviewer_model="session"` 恢复跟随会话。默认远程 `remote_fallback_model="omp-kimi_tf-kimi-for-coding"` 仅在主审运行故障、transport不支持或不可用时接替；有效 allow/ask/deny 终止，不复审。模型引用错误在配置期失败。这与执行模型的 `retry.modelFallback` 分开管理。

例如主动选择 GLM 主审、Kimi 作为远程备用，在私人 local 设置：

```toml
[overrides.profiles.omp-kernel.agent_options.permission_control]
reviewer_model = "omp-zhipu_tf-glm-5.3-flash"
remote_fallback_model = "omp-kimi_tf-kimi-for-coding"
fallback_model = "local/lfm2.5-230m"

[overrides.profiles.omp-kernel.agent_options.permission_control.review_timeouts]
primary_ms = 30000
remote_ms = 30000
total_ms = 60000
```

审查预算默认主审 30 秒、备用 30 秒、合计最多 60 秒。备用仅在主审不可用或返回无效结果时
开始自己的计时；有效 ask/deny 不会换模型。`review_timeouts` 可省略；提供时三项均须填写，
主审/备用各为 1000–120000 ms，总计为 1000–240000 ms，存在备用时总计至少为两者之和。
`/permission-control status` 显示实际预算，人工弹窗与审计显示阶段、耗时和哪个预算耗尽。
`TIMEOUT` 表示插件的本地截止时间到达，不能仅凭它断言远程模型服务超时。

原版 OMP 没有公开的 installed-only tiny 推理 API。本地 fallback 保留配置身份，但当前显示 unavailable，插件不调用私有 worker 或下载资源。远程两层均失败时询问用户，无 UI 时阻止。原生标题 tiny 与权限 fallback 相互独立。

配置部署到受管 `permission-control.json`，不向官方 `config.yml` 注入宿主专用字段。独立工具运行非交互 Bash，不继承原生 service/job/PTY、direnv、interceptor、worktree 重写或自动后台管理。原生工具及其它操作保持各自的保护范围；不能把此插件宣称为 OS 沙箱。

当前仓库实施与验收见[独立插件修订](../specs/004-omp-permission-control/standalone-plugin.md)、[启用指南](../specs/004-omp-permission-control/quickstart.md)及[验收记录](acceptance/omp-permission-control.md)。先前 patched runtime 的构建、宿主 smoke 和模型质量均为历史证据；本机切回官方包仍须检查 plan、活动实例及部署差异，不自动终止会话。

## WSL 前提

- WSL 发行版须是受支持架构上的 Linux glibc 环境，并有 Python 3.11+ 和仓库已准备好的 `.venv`。musl、Windows 原生环境和未知架构会返回 5。
- 仓库、私人 local、实例、状态和 cache 应放在 WSL 的 Linux 文件系统。不要把 `/mnt/c` 作为默认位置；其权限和原子文件行为不适合作为 0600/0700 私人状态的基础。
- 私人文件的父目录须为 0700，local 文件须为 0600。真实密钥不能写进仓库、命令行或公共 profile。
- 使用 TF 模型时，WSL 还须能访问用户在私人机器文件中填写的企业网关，并有对应 key。公共 catalog 不保存企业地址。该连通性独立于 GitHub 上的 OMP standalone 下载。

先在仓库根目录创建或补齐私人机器文件与共享密钥占位：

```sh
./agentcfg init-local --machine omp-kernel --profile omp-kernel
OMP_LOCAL="${XDG_CONFIG_HOME:-$HOME/.config}/agentcfg/machines/omp-kernel.toml"
```

先用 `model url kimi_tf` 和 `model url zhipu_tf` 隐藏输入企业服务地址，真实地址只保存到私人机器文件。

所有 profile 继承包含 Kimi Code、GLM Coding Plan 与 DeepSeek 按量 API 的公共可选池，公共初始主模型仍是 Kimi Code。`omp-kernel` 在其基础上追加 TF provider、模型和角色，现有 main/plan 等角色仍使用 TF，不会因模型进入池子而自动切换服务。TF 定义属于 OMP 专用目录，包含 Kimi 四个、GLM 五个和 DeepSeek 两个型号，加上公共池共十九条静态模型绑定。核心规格复用公共模板，协议兼容和计费保留在各绑定中；网关可用性仍需实际账号确认。该配方提供五套原生模型预设，见[模型套件](omp-model-presets.md)。详见[模型目录](model-catalog.md)。先查看状态，再按实际使用情况填写共享 key：

```sh
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model status
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model url kimi_tf
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model url zhipu_tf
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model key kimi_tf
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel model key zhipu_tf
```

密钥使用隐藏输入，默认保存在 `~/.config/agentcfg/secrets.toml`（遵循 XDG_CONFIG_HOME），TF 对应引用为 `omp_kimi_tf_key`、`omp_zhipu_tf_key`、`omp_deepseek_tf_key`。官方订阅用 `model key kimi-code|glm-code`，对应 `kimi_code_key`、`glm_coding_key`；官方按量 DeepSeek 用 `model key deepseek`，对应 `deepseek_key`。各服务分别管理，不自动复用或迁移旧 key。缺少 key 时仍能进入界面，对应模型及 fallback 未就绪；只修改 key 无需 apply，但需要重新 run。共享文件与旧配置的兼容规则见[本地配置](local-config.md)。

TF provider 使用 `base_url_ref = "local:tf_openai_url"` 和 `base_url_ref = "local:tf_anthropic_url"`，由机器文件 `[local_values]` 提供实际地址。DeepSeek TF 与 Kimi TF 共用 OpenAI 地址引用，使用独立密钥；可用 `model key deepseek_tf` 填写。`model url` 负责隐藏输入、校验并原子保存，不回显已有地址。缺少选中 provider 的地址时，`model status` 仍可列出缺项，`setup/apply/run` 会明确失败；未选择 TF 的其他 profile 不受缺值影响。私人 URL 必须与 TF 模型 ID 和协议匹配，不能直接换成同名厂商官方端点。

## 部署和启动

所有全局选择参数都放在子命令前。新建机器时 `default_profile` 为 `omp-kernel`；已有机器补齐时保留其原默认值，因此下面显式写出目标 profile：

```sh
OMP_WORKSPACE="$HOME/src/your-project"

./agentcfg --local "$OMP_LOCAL" --profile omp-kernel setup
./agentcfg --local "$OMP_LOCAL" --profile omp-kernel run --cwd "$OMP_WORKSPACE"
```

`setup` 先脱敏预览，再获取正式锁指定的 standalone（缺失时可能联网），重新检查后部署。需要分步审阅时使用 `validate`、`plan`、`sync`、`apply`、`doctor`；`render` 是可选的缓存生成步骤。`run` 不隐式下载、部署或读取 PATH 中的全局 OMP。普通受管会话自动加入 `--no-title`，因此不会启动自动标题模型请求。

`setup` 也用于更新已经部署过的配置，可以重复执行。使用同一机器和 profile 更新原受管实例，不需要删除实例目录或重新初始化原生 OMP。更新前先退出正在运行的 OMP，回到 Shell；管理器会拒绝修改活动实例。

已有 `workstation/omp-kernel` 可以按以下流程更新：

```sh
# 配置声明增加字段后，先检查并补齐私人占位；已有值保持不变
./agentcfg init-local --machine workstation --profile omp-kernel
./agentcfg --machine workstation --profile omp-kernel model status
# 按状态提示填写缺少的 URL/key，然后更新部署
./agentcfg --machine workstation --profile omp-kernel setup
./agentcfg --machine workstation --profile omp-kernel run omp --cwd "$PWD"
```

日常修改规则、模型、URL 或其他配置后直接执行 `setup`，随后重新 `run`。只有 key 值改变时，退出并重新 `run` 即可。依赖已就绪且只想离线应用配置时，可用 `plan` 查看差异后执行 `apply`；本次仓库配方或锁也有变化时，优先使用 `setup`。它消费仓库当前锁，不会自行拉取 Git 更新或升级到上游最新版本。发现冲突、漂移或待恢复状态会停止，此时先用同一选择器运行 `plan` 查看原因。

`omp-kernel` 启用 Vim 输入模式，状态栏左侧显示 `INSERT` 或 `NORMAL`。按 `Esc` 进入 `NORMAL` 后，普通字符不会进入输入框；按 `i` 返回 `INSERT`。状态栏中的 `mode` 段表示其他会话模式，Vim 输入状态由新增的 `vim` 段显示。

若在 `INSERT` 状态仍感觉输入卡顿，可从另一个终端运行 `./agentcfg --local "$OMP_LOCAL" --profile omp-kernel doctor --input`。`input_diagnostics.diagnostic_terminal` 只描述运行诊断命令的终端是否为 TTY、规范/回显标志，不代表卡顿的 OMP 终端；`input_diagnostics.readiness` 是所有工具共用的离线就绪检查；`input_diagnostics.host_events` 中的 OMP 事件来自受管日志，仅包含最近的 `ui.loop-blocked` 时间、PID、阻塞时长、CPU 时长和阶段，不读取或输出按键内容与日志正文。若状态为 `NORMAL`，先按 `i`；若为 `INSERT` 且有同时间阻塞事件，可据事件阶段继续定位；无事件也不能据此断定终端没有收到按键。

仅当私人 local 的 `default_profile` 已设为 `omp-kernel` 时，日常可以省略显式 `--profile omp-kernel`；故障排查和变更审阅时建议继续显式写出。

## 项目来源边界

新启动契约保留用户的 HOME、XDG 和运行目录，OMP 账号与会话继续存放在原受管 state-home。旧部署不会自动变更，详见[目录和环境契约](omp-profiles.md#目录和继承)。来源门禁额外核对实际 HOME、受管配置根、活动 profile 配置根、agent 根和项目中的 dotenv，包括有效 `NODE_ENV` 的 mode.local；只检查存在性与链接，不读正文。检测到未声明来源时会在启动前停止。

在普通仓库内启动是允许的。`.agents/`、`.agent/`、`.claude/`、`.codex/`、`.gemini/` 以及顶层 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 属于已禁用兼容 provider 的容器或上下文，受管 OMP 不自动加载其正文，单纯存在不会导致拒绝。

真正可被原生 OMP 消费的来源仍严格检查，包括 `.omp` 下的 settings、agents、tools、hooks、skills、MCP，dotenv、SYSTEM/TITLE/APPEND_SYSTEM 等 direct helper。`omp-kernel` 默认没有开启项目资源；需要项目 skill 或 MCP 时，应按[来源政策](omp-profiles.md#来源政策)声明根并接受逐项校验，不能用目录级放行引入额外配置或凭据。来源检查是启动前配置边界，不是操作系统沙箱。

## codex-delegate 和 tiny model

`codex-delegate` 只在用户显式要求使用 Codex 时调用。在带 Pi 集成的宿主中使用 `codex_delegate` 工具；OMP 没有该工具时，skill 使用随包安装的 `scripts/run-codex.sh`。后者需要 Linux Bash、`jq`、util-linux `setsid`、`/proc` 和 `codex` 命令。Codex 使用独立 `CODEX_HOME` 认证，runner 不负责安装这些程序或登录账号。

runner 默认让 Codex child 直接连接，不继承调用者的 proxy 变量。需要机器代理时，在私人 local 的 `[machine.environment.values]` 设置不含 userinfo、token、query 或 fragment 的 `CODEX_DELEGATE_PROXY_URL`；该值只传给 Codex child，不导出到调用者，也不写入 receipt/stdout。是否需要代理和代理地址由机器自行决定，配方不再假定 `127.0.0.1:10808` 可用。跨机器缺少上述 Bash、`jq`、`setsid`、`/proc`、`codex` 或独立认证时，该 skill 不可执行；部署不会自动补装这些环境依赖。

`local/lfm2.5-230m` 只由公共 `agent_options.tiny_model` 选择并生成原生 `modelRoles.tiny`，不作为已验证主模型。显式触发 tiny model 的首次使用可能需要本机已有模型 cache，或需要网络获取模型；这与正式 OMP standalone 的 `sync` 缓存是两件事。

## 下载中断与复用

运行资产写入 profile 私人 cache 的内容寻址 `.part` 文件。管理器对瞬态超时、连接重置、HTTP 408/429/5xx 和短读最多尝试三次；服务端正确返回 206 与 `Content-Range` 时从安全偏移续传，返回 200 时从零重写。只有完整长度和 SHA256 都匹配才原子发布为可用缓存。

中断后保持同一个 local/profile 再执行 `sync`，会继续使用同一 cache 和安全 partial。不要手工把 `.part` 改名为完成文件，也不要绕过锁摘要。错误只报告类别、尝试次数和进度；诊断步骤见[依赖维护](omp-dependencies.md#下载中断诊断)。`sync` 下载失败与会话访问企业模型网关失败是两条独立路径，不能因模型网关公网不可达就归因于 OMP 下载器。

Linux x64 的既有宿主证据见[真实 smoke](../specs/002-manage-omp-config/evidence/linux-smoke.md)。它不证明 WSL、Linux arm64、macOS、真实账号或这些 API provider 的模型调用已经通过。

本机2026-09-30后续授权已完成官方运行包与独立插件部署，默认 `cursor/kimi-k3-high:high` 通过私人 `native_model_roles.main` 明确绑定；无需恢复公共Kimi默认模型。该字段要求选用Cursor OAuth provider，不构造静态模型或API-key传输。审批有显式主审时使用它，未指定时才跟随会话模型；主审失败时由远程备用接替。最终部署与启动准入证据见[验收Phase13](acceptance/omp-permission-control.md#phase-13本机迁移与-cursor-默认模型后续明确授权2026-09-30)。

2026-10-02 已将本机默认模型对齐为 `cursor/kimi-k3:high`。官方 v18.4.5 将 K3 effort variants 合并为逻辑模型 `kimi-k3`，high 请求仍路由到 `kimi-k3-high`；模型选择器保存逻辑 ID 与 effort。旧私人配置仍指定成员 ID 时，原生选择器持久化的逻辑 ID 会造成 `/modelRoles/default` 漂移并阻止后续受管启动。此次只修改私人 `native_model_roles.main`，再执行 `plan/apply` 对齐部署基线，未放宽漂移检查；审批模型独立配置。见[后续验证](acceptance/omp-upgrade-18.4.5.md#2026-10-02模型名称对齐)及[机器证据](acceptance/omp-cursor-model-alignment-20261002.json)。

**历史 Cursor 原生命令审批限制（2026-10-02 确认）：** 当时 `/permission-control status` 显示 smart 和 ready，只说明插件已启用，不保证 Cursor 原生 terminal 调用经过智能审查。v18.4.5 的 Cursor shell/stream/piBash 通道固定调用 `bash`；当时插件审查的工具名是 `permission_bash`。独立 MCP 工具调用可保留 `permission_bash` 名称，但原生通道仍使用宿主审批。公开 `tool_call` hook 能阻断或改写输入，不能自动批准后续原生 prompt。因此当时 Cursor 执行模型可能继续出现 `Allow tool: bash`；远程 reviewer fallback 无法改变这条执行通道。后续已确认公开 API 支持同名工具包装、独立 approval policyKey 与 `ctx.invokeTool()` 原生委托，2026-10-03 完成隔离原型与官方宿主机制验证。详见[覆盖限制取证](acceptance/omp-upgrade-18.4.5.md#2026-10-02cursor原生-bash-审批覆盖限制)及[完整方案与可行性证据](follow-ups/omp-cursor-native-approval-plan-2026-10-03.md)。


2026-10-03 Phase 14 将公共配方增加 `agent_options.permission_control.native_bash=true`，以公开同名工具包装接入原生 Bash；旧配置缺省关闭。仓库实现与本机已部署版本分别登记，合入 main 不会自动更新日常实例。原生 `bash=prompt` 保留插件缺失保护，明确 deny/pattern prompt/critical prompt 仍生效；主动主审和备用模型选择不变。

2026-10-04 Phase 15 保留用户的 `SHELL`，扩展 zsh 等常见 Shell 环境的原生智能审批。
受管启动提供本地执行路线契约，插件结合公开 CLI 与真实 Settings 核验；无契约的新 Shell
或 ACP/未知模式仍人工。普通本地工具使用 Brush，不承诺各 Shell 的原生语言。
`/permission-control explain` 的 `nativeContext` 可以区分 Shell family、执行路线和固定上下文原因。
历史默认 find interceptor 曾提示改用 glob，这与审批弹窗是不同步骤；当前配方默认关闭此硬拦截，
用户显式启用时仍保留宿主行为。实现、验证及平台范围
见 [Shell 验收](acceptance/omp-shell-approval-20261004.md)；使用时需退出旧进程并正常 sync/plan/apply。

Phase 14 基础隔离验收为 335 项包级纯测试、官方 SDK、24 组宿主及真实人工 UI 通过，见[生产插件验收](acceptance/omp-native-bash-approval-20261004.md)。2026-10-04 后续真实 Cursor 验收通过，main 已快进至 `14f34a9`，宿主仍为未修改的官方 v18.4.5。新增预算已使用 6/6（Cursor 3、GLM 3）：无害复合命令自动批准，human=0、delegate=1；原生 deny 阻止执行，reviewer=0、delegate=0。最终包级 339 项/1288 assertions、隔离宿主 25/25 及部署证据见[真实 Cursor 验收](acceptance/omp-cursor-native-approval-20261004.md)。

日常部署已完成。活动实例经用户明确授权以 SIGTERM 正常退出、释放锁，未使用 SIGKILL；先完成 0600 备份，再从已安装缓存校验运行包，无新增下载。仅恢复 default=`cursor/kimi-k3:high`、smol=`zhipu_tf/glm-5.3-flash:low` 两个模型角色；plan 漂移/冲突均为 0，apply 两项更新成功。doctor 显示 offline-ready、installed、运行包匹配、pending=0，无漂移、冲突或恢复待处理。完整 run 启动准入已通过 launch callback，但未启动新的日常宿主，也未新增外部模型请求；13 项账号数据库/WAL、会话、local 与 owner 的字节和权限保持不变。下一次日常启动加载已部署插件。
