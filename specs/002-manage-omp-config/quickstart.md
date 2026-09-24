# OMP 纳管验证指南

本文是分层验证运行手册；当前完成范围见[实施记录](implementation-progress.md)。
`omp-default`是bootstrap配方，`omp-validation`是九行验收配方。只有执行后保存的命令、
环境、退出码和断言结果才是证据。当前 Linux x64 真实无账号 smoke 已通过，见[证据](evidence/linux-smoke.md)；登录、真实用量与模型调用仍未执行。

接口和边界以 [CLI 与配置契约](contracts/cli-and-configuration.md)、
[原生能力契约](contracts/native-capabilities.md)、
[运行与依赖契约](contracts/runtime-and-dependencies.md)、
[数据模型](data-model.md)及[研究结论](research.md)为准。需求到场景的完整映射见
[验证矩阵](validation-matrix.md)。

当前 spec 的收口范围为隔离验证与已通过的 Linux x64 无账号 smoke；下文保留其他平台、登录、真实 usage、模型调用步骤作为[独立遗留恢复手册](../../docs/follow-ups/omp-platform-and-live-validation.md)，这些步骤不再属于当前待办，也无需现在准备环境或账号。详见[范围修订](scope-change-20260924.md)。

## 1. 验证层级和授权边界

| 层级 | 运行内容 | 默认可运行 | 可证明 | 不可证明 |
|---|---|---:|---|---|
| 静态检查 | 文档链接、格式、空白及矩阵完整性 | 是 | 文档内部一致性 | 任一功能已实现 |
| 隔离自动化 | 临时 HOME/XDG、断网、假 OMP、虚构 provider/model、文件哨兵 | 是 | 配置转换、身份门控、部署恢复、usage 透传等管理器行为 | 真实 OMP 能加载配置或访问账号 |
| 真实宿主 smoke | 锁定 OMP 二进制、无真实账号或服务调用 | 否，需单独明确授权 | 固定版本宿主能启动并发现部署资源 | 登录、真实用量、模型可用性 |
| 真实账号登录 | 新建的受管原生 profile 执行显式登录 | 否，需独立授权 | 该 profile 自己建立认证状态 | 其他账号、provider 或模型可用性 |
| 真实 usage | 允许原生网络、缓存及认证刷新 | 否，需独立授权 | 选中原生上下文当次返回的额度/窗口 | 上游未提供的数据或跨 profile 汇总 |
| 真实模型调用 | 明确 provider/model 的生成请求 | 否，需独立授权 | 当次账号、模型和路线可用 | 其他平台或服务可用性 |

普通 quickstart 到隔离自动化为止。不得为了让指南“通过”而启动真实 OMP；真实 smoke、
登录、usage 和模型调用是四项分别授权、分别记录的操作。Linux 结果不能推定 macOS；
macOS 实机验证已转 OMP-F02，当前仍未验证。

## 2. 默认隔离测试

### 2.1 前提

- Python 3.11+，依赖已按仓库锁准备到 `.venv`。
- 从仓库根目录调用 `.venv/bin/python`，不使用 `uv run`。
- 测试遵循 `tests/conftest.py`：临时 `HOME`、`DSH_HOME`、`PI_CODING_AGENT_DIR`、
  `CODEX_HOME` 和全部 XDG 目录；父环境清空；网络与未登记子进程默认拒绝。
- OMP 样本只能使用虚构账号、provider、model 和假子进程。秘密哨兵不得出现在失败输出。

执行 OMP 隔离测试：

```sh
.venv/bin/python -m pytest -q tests/test_omp_*.py
```

预期结果：测试全部通过；输出记录用例数和耗时。它只构成隔离自动化证据。若 glob 尚无
匹配文件、pytest 未收集用例或依赖缺失，应记录为“未执行/环境不足”，不能记为通过。

实现后还应运行现有回归，证明 OMP 没有改写 DSH/Pi 契约：

```sh
.venv/bin/python -m pytest -q
```

### 2.2 隔离套件必须观察的哨兵

每个场景应在执行前后比较字节、权限、链接目标和存在性，至少覆盖：

- 非受管原生 default profile、一个已有命名 profile及其认证、会话和缓存；
- 第二个受管 OMP 配方的实例 HOME、原生 profile、XDG、状态、备份和锁；
- DSH_HOME、Pi home/Codex home、公共源及仓库外路径；
- rotom 实例、部署记录和受管 profile 目录（原生 usage 模式应零变化）；
- 秘密标记在渲染、plan、摘要、异常、capture 提案和备份中的出现次数。

## 3. 临时机器配置和环境

以下步骤只建立仓库外的临时机器配置，不使用现有 HOME，不填写真实 secret。字段格式参考
`examples/local.example.toml`；不要复制其中的示例 profile 覆盖或把真实凭据放入仓库。
从仓库根记录源目录，进入隔离子 shell 后本章命令仍使用该工作树：

```sh
export OMP_REPO_SRC="$PWD"
export OMP_CASE_ROOT="$(mktemp -d)"
export OMP_CASE_HOME="$OMP_CASE_ROOT/home"
export OMP_CASE_XDG_CONFIG="$OMP_CASE_HOME/.config"
export OMP_CASE_XDG_DATA="$OMP_CASE_HOME/.local/share"
export OMP_CASE_XDG_STATE="$OMP_CASE_HOME/.local/state"
export OMP_CASE_XDG_CACHE="$OMP_CASE_HOME/.cache"
export OMP_LOCAL="$OMP_CASE_XDG_CONFIG/agentcfg/machines/omp-validation.toml"
export OMP_WORKSPACE="$OMP_CASE_ROOT/workspace"
install -d -m 700 "$OMP_CASE_HOME" "$(dirname "$OMP_LOCAL")" "$OMP_WORKSPACE"
install -m 600 /dev/null "$OMP_LOCAL"
env HOME="$OMP_CASE_HOME" \
  XDG_CONFIG_HOME="$OMP_CASE_XDG_CONFIG" \
  XDG_DATA_HOME="$OMP_CASE_XDG_DATA" \
  XDG_STATE_HOME="$OMP_CASE_XDG_STATE" \
  XDG_CACHE_HOME="$OMP_CASE_XDG_CACHE" \
  OMP_CASE_ROOT="$OMP_CASE_ROOT" OMP_CASE_HOME="$OMP_CASE_HOME" \
  OMP_LOCAL="$OMP_LOCAL" OMP_WORKSPACE="$OMP_WORKSPACE" /bin/sh
${EDITOR:-vi} "$OMP_LOCAL"
```

`env ... /bin/sh` 打开隔离子 shell；本节之后的命令均在其中执行，结束时 `exit`。调用者 shell
的 `HOME` 没有被覆盖，所有 HOME/XDG 写入只落在 `OMP_CASE_ROOT` 下。
若父环境来自其他Agent会话，在这个子shell内清除会冲突的调用者身份变量：

```sh
unset OMP_PROFILE PI_PROFILE PI_CODING_AGENT_DIR PI_SESSION_DIR PI_CODING_AGENT_SESSION_DIR
unset OMP_AUTH_BROKER_URL OMP_AUTH_BROKER_TOKEN
```

写入最小的机器文件；`omp-default` 必须已经由公共 profile 登记，local 文件不能偷建 profile：

```toml
schema_version = 1

[machine]
id = "omp-validation"
default_profile = "omp-default"

[machine.environment]
inherit = []

[machine.environment.values]
LANG = "zh_CN.UTF-8"
```

本例没有 `[secrets]`。需要 API key 的后续授权场景只在该 0600 私人文件里保存引用对应的值，
不得把值复制到命令、测试夹具、公共配置或验收日志。

## 4. 选择配方与生命周期验收

### 4.0 配方准备

`omp-default` 是供用户重新登录的 bootstrap 配方，不等于八类九行验收样例。仅验证
bootstrap 生命周期时，在当前仓库执行：

```sh
export OMP_CASE_PROFILE="omp-default"
```

T061/T062 的真实九行 smoke 必须使用以下单独准备步骤；仅在对应宿主 smoke 已获授权、
T026 已生成完整样例及首轮锁后执行。以下步骤复制公开管理源，不复制现有用户 HOME、
认证、session、部署状态、运行缓存或 `.git`。临时仓库使用实际管理器和真实锁定二进制，
不能使用 pytest 的假下载器、假 OMP 或 synthetic receipt。

```sh
export OMP_SMOKE_REPO="$OMP_CASE_ROOT/smoke-repository"
export OMP_CASE_PROFILE="omp-validation"
export PYTHONDONTWRITEBYTECODE=1
install -d -m 700 "$OMP_SMOKE_REPO" "$OMP_SMOKE_REPO/tests/fixtures"
cp "$OMP_REPO_SRC/agentcfg" "$OMP_REPO_SRC/pyproject.toml" \
  "$OMP_REPO_SRC/uv.lock" "$OMP_SMOKE_REPO/"
cp -R "$OMP_REPO_SRC/src" "$OMP_REPO_SRC/schemas" \
  "$OMP_REPO_SRC/shared" "$OMP_REPO_SRC/agents" \
  "$OMP_REPO_SRC/profiles" "$OMP_REPO_SRC/locks" "$OMP_SMOKE_REPO/"
ln -s "$OMP_REPO_SRC/.venv" "$OMP_SMOKE_REPO/.venv"
cp -R "$OMP_REPO_SRC/tests/fixtures/omp" "$OMP_SMOKE_REPO/tests/fixtures/omp"
cp "$OMP_SMOKE_REPO/tests/fixtures/omp/registry.toml" \
  "$OMP_SMOKE_REPO/shared/omp-validation.toml"
cp "$OMP_SMOKE_REPO/tests/fixtures/omp/profiles/omp-validation.toml" \
  "$OMP_SMOKE_REPO/profiles/omp-validation.toml"
cd "$OMP_SMOKE_REPO"
```

这里 `.venv` 只复用已准备的解释器/依赖，不运行 uv、不安装或修改它；管理器源码使用复制的
`src/`。fixture registry 中的完整技能路径必须指向已复制的
`tests/fixtures/omp/skills/full-package/`，保留脚本执行位和相对资源；其他选定资源位于
复制后的 `shared/` 或 `agents/omp/` 内。T026 必须验证这些精确路径、唯一 ID、main+smol、
两份规则以及九行选项齐全。缺文件或缺声明时停止，不以空配置继续验收。

fixture 使用已支持的 `openai-compatible`/`api-key` 组合，provider/model为虚构值，
base_url固定 `https://omp-validation.invalid/v1`，credential_ref固定
`secret:omp_smoke_placeholder`。在第3节新建且尚无secrets表的临时0600文件中追加以下
公开测试占位值；该字符串不是真实凭据，不应替换成真实账号密钥：

```sh
cat >> "$OMP_LOCAL" <<'TOML'

[secrets]
omp_smoke_placeholder = "rotom-smoke-not-a-secret"
TOML
```

该引用仍走正常的SecretStore与运行时注入路径，不写入生成原生文件。smoke只验证模型发现/
角色解析，不发起生成请求；MCP只运行声明的本地echo fixture。真实账号登录与模型调用
使用第5节单独说明的配方和授权，不能用该测试值证明账号可用。

此后第4节所有命令使用 `$OMP_CASE_PROFILE`。local 文件仍只选择/覆盖已登记的配方，
不会创建配方。第5/6节显式写出的 `omp-default` 是单独的 bootstrap/login/usage 操作，
不承担九行验收。需要回到原工作树时显式 `cd "$OMP_REPO_SRC"`。

### 4.1 完整锁与生命周期

全局选项始终放在子命令之前。维护者在更新 OMP 版本或锁时，先显式生成并审阅锁：

```sh
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" lock --agent omp
```

`lock --agent omp`在加载机器文件之前分发，也可以省略所有local/profile选择器。
普通机器若已有审阅过且与输入一致的`locks/omp`，无需重复生成锁，直接消费它执行`sync`。
`lock`可能访问发布来源，但不得安装、部署或启动宿主。
首轮锁必须同时具备 `locks/omp/manifest.json`、`locks/omp/upstream/bun.lock`、
`locks/omp/upstream/provenance.json`、`locks/omp/upstream/NOTICE.md`，不能等到US5才补齐。
第4.0节复制fixture registry/profile到公共目录会新增配方输入，因此须在临时仓库显式执行上述lock并审阅
完整文件组，再sync；它仍锁定相同官方版本和真实发布摘要。无网络且缺必要
真实产物时记录环境不足，不将假二进制摘要/receipt写入真实 smoke 的锁或缓存。

随后按顺序执行并分别保存 stdout、stderr 和退出码：

```sh
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" validate
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" render
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" plan
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" sync
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" apply
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" doctor
```

预期：

1. `validate`、`render`、`plan` 和默认 `doctor` 离线，不安装、不部署、不登录、不加载扩展；
   未知字段、无效引用和超出能力范围输入以退出码 2 失败。
2. `plan` 显示受管目标、唯一原生 profile、有效 HOME/XDG、归属、字段/文件差异、漂移与冲突。
3. `sync` 只消费锁定的、无宿主补丁的官方 OMP v18.3.0 standalone binary（提交
   `62bc57be1b03ef0802a33cf7f5f530e534527531`）及其 SHA/包摘要，验证成功后才激活；
   不使用全局安装。失败时上一运行包仍可用。受管配置固定
   `startup.checkUpdate=false`、`marketplace.autoUpdate=off`，不能绕过锁自行更新。
4. `apply` 使用三方比较和 pending 恢复记录；首次成功部署后生成基线，第二次执行应为无变化，
   不重写目标、不轮换备份。apply不要求先安装运行包；后续run遇运行包缺失返回5，归属/活动/恢复冲突返回4。
5. 实例原生 HOME 固定为 `<instance>/user-home`；其 `.omp` profile、配置、认证、会话、缓存
   和 XDG 均留在实例内。参数或继承环境试图另选身份时在启动前以 2 拒绝；已部署目录布局、
   identity 或关键守卫被改动时按所有权冲突以 4 拒绝。

部署完成后，受管启动的目标命令为：

```sh
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" run omp --cwd "$OMP_WORKSPACE"
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" run omp -- --help
```

默认不发现外部资源。由于原生设置无法完全禁用 project 发现，preflight 必须按固定发现清单
检查 cwd 及祖先的 `.omp`、generic/direct 上下文来源与 `.env` 来源，并在启动 OMP 前拒绝；
只有用户显式声明后，才允许其中已声明、只读、非秘密的项目 skills/MCP。opt-in 仍禁止覆盖
auth broker、目录和 discovery guard。受管 auth broker 必须禁用，因为其认证作用域不能满足
profile 隔离。该门控定义配置来源边界，不宣称是 OS 沙箱，也不防御同用户恶意并发改写文件。
启动不隐式 sync、apply 或登录。

### 4.2 八类必交能力

隔离测试为每类使用一个支持范围内的样例，先检查渲染/部署，再由单独授权的真实宿主验收
确认原生生效。主题和快捷键是两个独立样例，不能只验证其中之一。
真实验收前应从plan/doctor确认当前配方确为 `omp-validation` 且九行资源已部署；
若是bootstrap `omp-default`，本表不能判为通过。

| 类别 | 最小样例 | 隔离观察点 | 真实宿主观察点 |
|---|---|---|---|
| 模型/provider | 虚构 OpenAI-compatible provider、精确 remote model ID 与明确容量字段 | 引用、凭据引用和原生映射正确，secret 值不落盘 | 原生列表/有效配置指向所选模型；生成调用另需授权 |
| 模型角色 | main 与 smol 绑定已选逻辑模型 | 角色只引用已选模型，未知角色失败 | 原生角色解析为预期模型 |
| 规则 | 两份公共规则 | 内容、顺序和来源可解释 | 新会话发现两份规则 |
| 完整技能包 | 含 `SKILL.md`、相对资源和脚本的技能 | 包结构、相对引用和执行位保留，配置阶段不执行脚本 | 原生发现技能及资源 |
| 提示词 | 一份命名提示词 | 确定性渲染且无秘密 | 原生可选择/加载提示词 |
| 主题 | 一份命名主题 | 主题文件和选择项部署 | 原生显示选中主题 |
| 快捷键 | cycleForward=Ctrl+P、history.search=[] | 不修改 default profile；继承来源可报告 | 命名 profile 中按键行为生效 |
| 扩展 | 一项已核实 OMP 兼容的扩展 | 锁定来源，validate/render 不加载代码 | 原生加载扩展，`/rotom-health` 返回固定非秘密标记 |
| MCP | 锁定本地 Python stdio echo fixture，另测无认证 HTTP 映射 | transport、argv/URL 和 secret 引用校验，不连接服务 | 授权 smoke 完成 stdio tools/list 和一次受控工具调用；外部真实服务另授权 |

表中“主题/快捷键”对应 FR-002 的一个配置大类，但必须分别取证，因此列为两个验收行。
任一必交行只有“不支持”或失败证据时，八类覆盖率不能记为 100%。

授权真实 smoke 时，首次原生 onboarding 可逐步按 Esc 跳过，不能误选登录或改写受管模型/主题。进入 TUI 后使用以下本地观察入口：

```text
/rotom-health
/rotom-health inspect
/hotkeys
/settings
/mcp test echo-stdio
/rotom-health mcp
/context
```

`inspect` 只输出规则/技能存在性、固定 fixture 模型与主题和 MCP 工具来源；`mcp` 只用当前 profile 的受管 echo-stdio，通过固定宿主官方 SDK 执行初始化、tools/list、一次固定回声 tools/call 并关闭连接。它们不调用模型；异常只输出固定错误标记。可在命令补全中观察 `/rotom-review` 和 `/skill:full-package`，不要提交展开后的生成请求。Ctrl+P 实际切换角色后再切回；空输入 Ctrl+D 正常退出。宿主 smoke 与下载步骤分开，建议运行宿主时隔离外网，并记录 DNS 尝试与实际进程，不能把断网等同于没有网络行为。

### 4.3 漂移、capture 和 rollback

在没有 pending 的假原生目标中，分别制造单方漂移、双方冲突和活动锁，按各场景执行并断言相应结果：

```sh
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" plan
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" capture
./agentcfg --local "$OMP_LOCAL" --profile "$OMP_CASE_PROFILE" rollback
```

预期：单方漂移可见且未被吞并；双方冲突阻止覆盖；capture 只生成 allowlist 内的非秘密提案，
不捕获认证、trust、会话、日志或缓存；rollback 只恢复上一版受管配置、消费备份，并保留新增
的非受管数据。OMP capture 复用现有命令语法，只能提出 theme、keybindings 和 modelRoles
中的 allowlist 非秘密修改；提案仍需用户审阅后手工合并，不直接改写公共源。

另外独立注入中断 pending：先断言 plan/run/managed usage 返回4，再在两个独立测试中分别显式执行 apply 和 rollback，验证持锁后通过公共 deployment.recover 恢复且非受管数据保留。损坏的恢复记录必须失败，不扩展或调用 `recover pi`。

## 5. Profile、项目来源和登录

用两个受管配方以及非受管 default/命名 profile 验证：每个配方的原生命名 profile 为
`rotom-` + `sha256(UTF-8 profile.id)` 的前 24 个十六进制字符；重新运行得到同一身份，并对
完整 identity 做碰撞校验。重命名或状态根变化不能绕过原绑定、锁或所有权。有效来源报告
必须能回答配方、原生 profile、HOME、XDG、账号/会话作用域以及显式项目资源的来源。

旧 OMP 环境仅可作为用户明确选择的非秘密配置来源。迁入清单通过以下只读命令生成到私人
cache；命令不写来源目录或仓库：

```sh
export OMP_SOURCE="$OMP_CASE_ROOT/synthetic-existing-omp"
./agentcfg --local "$OMP_LOCAL" --profile omp-default inventory omp --source "$OMP_SOURCE"
```

命令在私人 cache 中生成三类结果：逐项处置及理由的 `disposition.json`、allowlist 内的
`local-overrides.toml`，以及经过路径、敏感字段和已知秘密扫描的候选资源包。脚本或文本若
含无法证明安全的内容，必须标为 `review-required`，不得自动导入。

用户审阅后手工合并获准的 TOML 提案，将批准的资源包复制到 `agents/omp/resources` 或
`shared/skills` 并在公共配置中显式声明；资源身份或选定依赖改变时，先显式
`lock --agent omp` 并审阅完整锁，再 `sync`。随后重新执行：

```sh
./agentcfg --local "$OMP_LOCAL" --profile omp-default validate
./agentcfg --local "$OMP_LOCAL" --profile omp-default render
./agentcfg --local "$OMP_LOCAL" --profile omp-default plan
./agentcfg --local "$OMP_LOCAL" --profile omp-default apply
```

本流程没有额外的 import 子命令。目标必须是空的、新建的受管环境；旧账号、认证和历史会话
不复制，旧环境所有哨兵保持不变。登录是部署后的独立动作，且本命令只在用户另行授权后运行：

如果此前只部署了第4节的 `omp-validation`，必须先显式完成 `omp-default` 的
validate/render/plan/sync/apply，再执行下面的登录命令；不能把另一配方的部署或认证当作前置。

```sh
./agentcfg --local "$OMP_LOCAL" --profile omp-default run omp -- login openai-codex
```

这是受管身份的安全登录入口，不是配置生命周期的一部分。未执行时记录“待登录”，不得借用
default profile 或其他 profile 的认证，也不得把未登录报告成失败的配置验收。

## 6. Usage 透传

原生模式无需受管配置，从调用者 PATH 查找 `omp`，保留原 cwd、继承环境、stdout、
stderr 以及子进程退出码：

```sh
./agentcfg usage -- --json
```

它不得读取 workspace 或 rotom secrets，不得扫描其他 profile，不得创建/修改 rotom 状态或
受管 profile。找不到程序时由管理器返回 5；只要原生进程已启动，无账号、不支持、部分失败
或其他非零结果都原样保留，机器可读 stdout 不混入管理器说明。

受管模式复用 `run` 的 runtime gate 和已部署身份，仅注入运行所需环境，并从 neutral cwd
执行以排除项目配置、`.env` 和 workspace 发现：

```sh
./agentcfg --local "$OMP_LOCAL" --profile omp-default usage -- --json
```

底层 argv 必须形如 `omp --profile NAME usage --json`。透传参数、继承的 `OMP_PROFILE`、
`PI_PROFILE` 或受保护目录覆盖一旦由用户提供，应在启动前以 2 拒绝。usage 仅在用户显式调用时允许
原生网络、缓存和认证刷新；不自动安装、部署、登录或发起模型生成。国内智谱、国际 Z.AI、
Kimi、OpenAI 分别报告上游实际结果，缺失数据不写成零，也不抓取浏览器 Cookie。

## 7. 平台范围

设计矩阵覆盖 Linux glibc x64/arm64 与 macOS x64/arm64；每个平台只有完成对应隔离和真实
宿主证据后才能标为通过。当前 macOS 尚未实测。musl Linux 与 Windows 在首版须于 sync/run
前以退出码 5 明确拒绝，不能回退到全局 OMP 或尝试不受管安装。

## 8. 证据记录模板

每次验收至少保存以下字段：

```text
场景 ID：
提交/工作树：
平台与架构：
OMP 版本、提交、二进制 SHA、包摘要：
命令与隔离环境（秘密值删去）：
开始/结束时间：
stdout/stderr 证据路径：
实际退出码与断言：
结果：通过 / 失败 / 未执行 / 环境不足
授权范围：隔离 / 宿主 smoke / 登录 / usage / 模型调用
未覆盖范围：
```

只有结果为“通过”且命令实际执行，才能填入验证矩阵的证据列。文档存在、任务勾选、假进程
退出 0、无账号 smoke 或其他平台结果均不能替代对应真实证据。
