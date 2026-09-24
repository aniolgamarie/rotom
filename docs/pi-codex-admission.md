# 官方 Codex CLI 的受限配置准入

agentcfg 固定使用官方 Codex 0.154.0，由 model-delegate 管理原生工具、沙箱和物理生命周期。按用户选择，配置来源无法核验时拒绝运行，保留兼容性缺口。

Linux 运行包同时锁定官方同版本 bwrap，安装到 `bin/codex-resources/bwrap`，并保留原许可证。
四个平台也锁定官方 primary 清单中的 `codex-code-mode-host` 和 `codex-responses-api-proxy`；它们是 CLI 内部依赖，不是新增的外部委托入口。
只安装 Codex 单程序归档不构成完整沙箱依赖；旧系统 bwrap 可能缺少 CLI 要求的选项。
官方 CLI 会核验随包 bwrap 的编译期摘要，agentcfg 的安装器也核验发行归档摘要和本机架构。
参见[官方 bwrap 加载与摘要核验实现](https://raw.githubusercontent.com/openai/codex/rust-v0.154.0/codex-rs/linux-sandbox/src/bundled_bwrap.rs)。

## 可准入条件

- `/etc/codex` 不存在或为空，且目录身份／权限可核验。任何内容都会拒绝，包括空配置文件、规则、技能和损坏链接。
- macOS 的 `com.openai.codex` 域中不存在 `config_toml_base64` 和 `requirements_toml_base64`。查询与官方 CLI 使用同一个 CoreFoundation API；仅检查磁盘 plist 不足以准入。
- 所选实例的 `codex-home/auth.json` 为 0600、当前用户所有、普通单链接文件。明确 API key 模式，或可识别的个人 OAuth `free/go/plus/pro/prolite`，可以继续；账号认证仍由官方 CLI 完成。
- 组织账号、未知 plan、混合身份、Agent Identity、PAT、Bedrock 等当前无法完整核验的组合拒绝，不自动更换账号。
- 机器管理配置和账号归属／类型在运行期间保持稳定。父监督者和 worker 启动前各检查一次；这不是同进程原子配置保证，也不涵盖管理员并发修改或账号刷新后改变类型。

每次 start/resume 都重新检查。准入策略 `official-cli-restricted-v1` 纳入执行身份；旧策略不能用于新的运行。

## 显式 API 服务地址

七种用途模板不增加授权，包括 `research`。Codex 的 `native_execution.web_search` 默认 `disabled`，
只有机器配置明确选择 `cached` 或 `live` 才开放对应官方搜索能力；该选项纳入冻结执行策略。
`tool_network = "none"` 继续禁止本地工具联网，官方服务端搜索通过已选择的模型服务路线执行。

默认使用官方 CLI 的 OpenAI 服务地址。API key 模式可以在本机覆盖中显式设置
`agent_options.model_delegate.codex.api_base_url`，用于兼容的 Responses 服务；不读取 `OPENAI_BASE_URL` 或原生用户配置作为回退。
地址须为不带用户名、密码、查询参数或片段的 HTTPS URL；隔离测试可使用数字回环地址的 HTTP URL。
地址进入冻结的执行策略和摘要，改动后不能复用旧准入身份。

自定义地址只接受明确 API key 账号，父监督者和 worker 都检查一次；个人 OAuth 与未知账号类型在启动官方 CLI 前拒绝，
避免把个人登录令牌发送给自定义服务。API key 仍保存在该实例的原生 `codex-home/auth.json`，不能写进服务 URL。

原生验收使用合成 API key 和网络隔离内的回环 Responses 服务，并通过正式 model-delegate CLI 启动官方 Codex。
`codex-native-readonly` 检查原生读取和写入拒绝；`codex-native-write` 在独立 Git worktree 中验证显式写授权、收据和原项目保持。
这些场景的实现或离线回归不代表它们已在最终候选上执行通过。

## 拒绝原因

| 原因码 | 含义与处理 |
| --- | --- |
| `CODEX_SYSTEM_CONFIG_PRESENT` | 系统 Codex 目录存在内容。保留管理员配置，选择符合上述条件的运行环境；不自动删文件。 |
| `CODEX_SYSTEM_CONFIG_UNVERIFIED` | 系统目录身份、权限或访问失败；先由机器管理员确认。 |
| `CODEX_MANAGED_PREFERENCES_PRESENT` | macOS 受管偏好存在，当前环境不支持这条委托路线。 |
| `CODEX_MANAGED_PREFERENCES_UNVERIFIED` | CoreFoundation 查询失败或不可用，不能当作“没有配置”。 |
| `CODEX_ORGANIZATION_ACCOUNT_UNSUPPORTED` | 当前所选组织账号不在受限支持范围；保留已选验收项及兼容性缺口。 |
| `CODEX_ACCOUNT_CONFIG_UNVERIFIED` | 实例认证文件不安全、格式未知或账号类型无法判定。使用该实例的明确登录流程建立受支持账号；不要把令牌粘贴到通用配置或日志。 |
| `CODEX_LOGIN_CONFIG_UNVERIFIED` | 登录命令无法忽略实例现有 config.toml；使用干净实例，不由程序删除该配置。 |
| `CODEX_CUSTOM_ENDPOINT_REQUIRES_API_KEY` | 自定义 API 地址要求明确 API key 账号；个人 OAuth 保留官方地址。 |
| `CODEX_CONFIG_PLATFORM_UNSUPPORTED` | 当前操作系统没有对应准入实现。 |

这些准入失败返回退出码 5；缺少认证文件仍属于凭据缺失（3）。拒绝发生在目标 CLI 启动前，不会调用模型或把结果记录为通过。

`doctor` 展示 `configuration_admission` 支持条件和 `not-inspected` 状态，继续保持不读取认证文件。启动检查只输出上表固定原因码；不会输出配置正文、令牌、邮箱或账号 ID。

## 验收界限

目前只有隔离测试通过。官方 CLI 原生行为、macOS 偏好 API、沙箱、退出和真实服务仍待验证。所有选择的 Codex 验收保留；受限环境中的拒绝不能代替模型执行通过。

设计依据和未采用方案见 [配置准入决定](../specs/001-unify-pi-capabilities/codex-config-admission.md)。


## Linux 委托进程范围

官方 CLI 的整次委托使用固定发行物自带的 bwrap 创建独立 PID 命名空间。第一方 PID 1 入口先等待监督者的启动字节，
监督者验证并记录初始化进程和包装进程的身份后才允许执行；输入关闭不放行。模型文件权限仍由冻结的 Codex 原生策略约束。

停止时通过 pidfd 操作已确认的 PID 1。Linux 内核在该初始化进程退出时终止命名空间中的所有进程，
因此独立进程组、重新托管的孙进程也处于同一停止范围。依据见 [Linux PID namespace 文档](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)。
运行包需要支持这些能力的 Linux 内核；握手或身份无法确认时拒绝执行，不退回较弱的进程组模式。

v3 记录的正常退出同时核验初始化进程和 bwrap 包装进程。已确认终止的命名空间不能复活；后续无关 PID 复用不撤销原终止证明。
旧 v1/v2 或 escaped/unknown 记录保持原保护，不会因为安装新版执行器而自动清除。
此变化不增加 MCP 工具桥或另一个任务队列。macOS 仍使用独立的 libproc/helper 路径，并保持未验证。
