# 上游接口核实记录

本文件记录 DSH/TUI/插件/OpenSpec 的版本调查与兼容性核实结果。
所有条目须追溯到选定版本的源码/文档或 smoke 证据。

> 2026-09-13 实施状态：完整锁、CLI 锁消费、原生无账号 TUI 与 OpenSpec 技能发现已验证。真实订阅登录/调用及 macOS 实测尚未执行。下方“初始调查记录”保留当时的阻塞描述，解决方式见最新实施记录；最新测试结果统一在 acceptance.md。

## 核实范围

| 组件 | 仓库/来源 | 选定版本/SHA | 核实状态 |
|------|-----------|-------------|---------|
| DSH host | `deepseek-ai/deepseek-harness` | CLI `0.1.5-rc.1` / `183f08e9c6dde7e36cd2318eaee70b0da08fb35e` | 实际安装及 host smoke 通过 |
| dsh-TUI | `ccch1mneyyy/dsh-TUI` | `0.10.1` / `78081cebde1ee1b47a561ef57c04f128c5623476` | bundled 元数据修复，运行代码不变；原生 Agent 已创建 |
| dsh-auth (Codex) | `ccch1mneyyy/dsh-auth` | `0.1.0` / `cc6ec5224b62b6e6508c0109ef19e93b0a5c0a0e` | 随 TUI 提供，auth 命令已注册，真实登录未执行 |
| oauth-subs (Cursor) | `xxww0098/dsh-plugin-oauth-subs` | Git `793978ee3b72a1c81d8b769b269ac2fa3bc90654`，源版本 `0.0.88`，本地包 `0.0.88-agentcfg.1` | 固定源归档与补丁；proxy health/终端入口通过，账号未实测 |
| OpenSpec CLI | `Fission-AI/OpenSpec` | `@fission-ai/openspec@1.13.0` / `9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461` | 指定项目初始化与重复执行通过，DSH 识别 6 个生成技能 |
| ModSearch | 可选，未选用 | 未冻结版本 | 未做兼容 smoke，不安装/启用 |

## 最新实施记录

- npm 11.3.0 解析所需 peer 图失败；改用经发布 integrity 核验的 npm 11.19.1。host 组件全部显式固定 `0.1.5-rc.1`，没有用 force/legacy-peer-deps 绕过冲突。完整锁包含 755 条 package 记录，实际 frozen 安装及 npm ls 无 problems。
- TUI tarball 中的 bundled manifests 带 `workspace:*`，导致 npm ci 失败。`scripts/vendor-tui.py` 仅将这些引用替换为同一归档中已有的精确版本，记录逐文件 diff/摘要，JS 运行代码保持不变。
- Cursor 使用固定 Git 源中已提交的 lib，源/lib 同步应用可审查补丁：关闭四类自动导入、后台更新和包 stamp，增加基于原生 commands 的 `/cursor-login`。因此无需临时 Web 宿主即可启动 Cursor 浏览器轮询登录；实际账号步骤仍待用户授权。
- Cursor dataDir 显式固定在实例 dsh-home/oauth-subs；端口可用框架 agent_options.cursor_port 覆盖。独立 smoke 用临时端口验证 `/health` 服务身份，不发送模型请求。
- Node 24.1 对该发布入口的 `import.meta.main` 返回空行为：退出 0 但无 dump。已改为官方 Node 24.14.0，记录 Linux 归档 SHA256、可执行文件摘要和其他平台官方分发校验值。
- `env-guard.mjs` 在 host 导入前阻止锁定版本的 cwd/.env、DSH_HOME/.env 隐式读取，保持业务 cwd；不是 OS 沙箱。TUI 用户偏好通过实例独立 user-home 隔离，不接管真实 ~/.dsh-tui。
- 管理器只处理自有 TUI 数据行和审核过的标量 JS；复杂 bundle IIFE 保持包拥有，不读取后求值。API/MCP 输出已通过锁定包的原生 schema 检查。
- OpenSpec 真实 marker 位于 `.agents/skills/.openspec-target`。初始化先在空暂存目录生成，再检查项目冲突。DSH 寻找最近 Git 根，所以拒绝在已有工作树子目录伪报成功；真实临时 Git 项目中已发现 6 个 OpenSpec 技能与 2 个框架技能。
- 默认测试与独立无账号 smoke、真实订阅调用分开记录。所有可执行验证均在临时 HOME/项目内完成；没有读取用户现存 OAuth、没有模型调用、没有推送或发布。

## 初始调查记录

以下保留实施前的取证过程和当时未完成状态；不代表当前交付仍使用未冻结的候选包。当前实现及限制以本页最新实施记录和 [acceptance.md](acceptance.md) 为准。

### Host/TUI 启动与包管理
以下均为固定源码/公开包元数据证据，不是已执行的安装命令或 smoke 结果。

- [host 发布页](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.5-rc.1)链接上述完整提交；[CLI manifest](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/apps/cli/package.json)确认包名 `@deepseek-ai/dsh`、版本 `0.1.5-rc.1`、bin `dsh: lib/bin.js`。不把私有 monorepo 根包当作 CLI。
- [host 根 manifest](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/package.json)要求 Node `^22.19.0 || >=24.0.0`、源码包管理器 `pnpm@11.7.0`；[TUI manifest](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/package.json)要求 Node `^22.19 || >=24`、`pnpm@11.21.0`。Node 24 是共同允许的主版本，不是已冻结的可执行版本。
- TUI 的 `dsh-agent` peer 包含精确 `0.1.5-rc.1`，但 [host dsh-base 发布元数据](https://registry.npmjs.org/@deepseek-ai%2fdsh-base/0.1.5-rc.1)使用 `^0.1.5-rc.1` 等依赖范围，可能解析到后续版本。因此只 pin CLI 不足以证明完整兼容性；须逐项核对实际 host/profile 依赖树与全部 peer，不修改上游 peer 来绕过。
- [host README](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/README.md)提供 npm 路线；原文无版本 npx 示例不能直接成为产品安装命令。拟采用隔离本地安装前缀及已验证发布包，不需要全局安装或未知 bootstrap 安装器。
- [plugin.ts](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/apps/cli/src/plugin.ts)将 `dsh plugin --profile dsh-tui add …` 参数交给 pnpm，以 profile 为 cwd；未构造净化环境。配置初始化及包管理写入与实际 profile 启动不同，不能混为 smoke。
- [profile.ts](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/boot/app-boot/src/profile.ts)初始化缺失的 `package.json`、`cordis.patch.yml`、`pnpm-workspace.yaml`；模块修复涉及 `$DSH_HOME/profiles/node_modules`、profile 的 `node_modules` 和 `.dsh-module-fallback/node_modules`。这些包括原生拥有的代理/符号链接，不交给普通渲染器管理。
- [profile-boot.ts](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/apps/cli/src/profile-boot.ts)启动准备会重写 profile 的 `cordis.yml`；`dsh --profile dsh-tui` 不是只读操作。模块解析还受 host 安装位置影响，host 与 profile 两棵依赖树都需要锁定。
- [TUI launcher](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/bin/dsh-tui.js)提供 `dsh-tui`/`dst`，可能自动 bootstrap profile；受控流程不依赖该隐式安装路径。[路径源码](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/src/utils/paths.ts)使用 HOME 下 `.dsh-tui`，故仅设置 DSH_HOME 不足以隔离。npm/pnpm 配置、store/cache、临时目录与本地 host 前缀也必须独立设置。
- [TUI 固定树](https://github.com/ccch1mneyyy/dsh-TUI/tree/78081cebde1ee1b47a561ef57c04f128c5623476)记录 dsh-auth gitlink；[auth manifest](https://github.com/ccch1mneyyy/dsh-auth/blob/cc6ec5224b62b6e6508c0109ef19e93b0a5c0a0e/package.json)版本是 `0.1.0`，不是 TUI 的 `0.10.1`。发布包内实际 bundled 内容仍需解包核对。

#### 未完成与取证限制

- 发布源码身份已找到；npm tarball SRI、源码与发布字节的对应关系、完整传递锁、原生构建脚本及逐平台安装尚未验证。源码 workflow 存在不等于对应 CI 已通过。
- 下一步在临时环境检查精确发布 tarball、bundled 包和实际 peer 关系，再进行完整解析及锁消费验证；安装与无账号宿主 smoke 分开执行，绝不读取既有 OAuth 或复制真实配置。
- 曾遇 GitHub API 限流和 raw/blob 获取失败；通过实际 release 页面及固定源码补回 rc.1 身份。先前猜测 tag URL 失败不证明发布不存在。旧 rc.2 调查候选不作为选定配方，也不据此声称 rc.2 必然不兼容。
- 可选 standalone/global updater 的完整写入图尚未审计，不纳入拟采用的本地 npm 包路线；不宣称全部上游运行时写入已穷尽。

### 配置接口（1.3 固定源码证据与合成 fixtures）

以下结论来自上述 host/TUI 固定提交；fixture 测试只验证持久化数据，不运行原生算法，不证明插件 schema 或宿主接受这些样本。

#### Cordis 与 settings 是两种机制

- host 使用本树 vendored include/loader，不能用其他 Cordis 分支的行为代替。[`applyEntryPatches`](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/vendor/include/src/index.ts)对提供的行属性执行 `target[key] = value`：提供 `config` 就替换整个 config；省略的 `disabled` 等行元数据仍保留。因此不是任意整行删除/替换，也不是 config 深合并。提供的非空 `name` 是匹配守卫，不是重命名；缺失 ID/名称不符在原生中警告跳过，不等于框架可以静默忽略错误。省略 patch ID 不删除该行。
- [settings `mergeLayers`/`replace`/`publish`](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/settings/settings/src/index.ts)则递归合并普通对象，数组/标量替换；用户 section 覆盖 composition base，`replace({})` 清除用户覆盖以重新继承。未注册 section 保留于原始文档，但注册 schema 不保证接受未知字段。不得用脱敏或 resolved section 全量替换原始 section，否则会删除隐藏字段。
- [settings-file](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/settings/settings-file/src/index.ts)默认路径是 `$DSH_HOME/settings.yaml`，不是 profile 内的文件；其 YAML 走 `yaml.parseDocument`，不是 Cordis `!!js` 方言。持久化 section diff 时对象递归、被移除键删除、数组/标量替换，同时保留无关文档节点。框架仍须执行自己的字段所有权和三方冲突检查，不能整文件接管或备份混合 settings。

#### 原生 JS 与尚未实现的安全策略

- include 定义标量 `!!js` 为 `__jsExpr` 载体；[loader `evaluate`/`isJsExpr`](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/vendor/loader/src/config/utils.ts)通过 `new Function`/`eval` 执行，且未标记的 `{__jsExpr: ...}` 对象也被识别为可执行载体。不能把这种对象当作普通未知字段安全传递。
- 拟议的 rotom 策略必须按**精确目标节点和原样标量**白名单、保持惰性，不执行表达式。样本只记录 `storage-json/config/root` 上的 `dshHomePath('storages')` 候选，来源为 [base bundle](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/bundle/base/cordis.patch.yml)。拒绝未知标签、非标量 JS 和未标记 `__jsExpr` 是未来策略要求，**本次未实现生产 loader、序列化器或拒绝策略**。
- [TUI bundle](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/cordis.patch.yml)包含任意 IIFE 及整块 `config: !!js`，不能声称它能通过上述窄白名单。依赖拥有的 bundle 保持不改；若需要管理整块可执行 config 内的字段，安全合成策略尚未解决，不可执行 JS、丢字段或伪报支持。未知可执行载体的安全边界优先于未知数据保留。

#### 实际生效的规则、技能与所有权

- TUI bundle 禁用 host 全局 `agent-instructions`/`skill-filesystem`；实际 [standard preset](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/preset/agent-presets/presets/standard/agent.cordis.yml)在 preset scope 内重新挂载规则、技能及 tool-skill。仅修改被禁用的全局行不能证明 TUI 会加载结果。
- [`discoverInstructionFiles`](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/context/agent-instructions/src/files.ts)先读 `$DSH_HOME/AGENTS.md`，再按项目根到 session cwd 的目录链加载各目录所有存在的 base candidates、local candidates；同目录 trimmed 重复可去重，不是只选 AGENTS/CLAUDE 其中一个。拟在新建独立 home 托管 AGENTS.md；不接管业务项目文件，不将普通 `{{example}}` 当模板。原生字节上限、去重及 prompt 包装仍可能改变最终上下文。
- [`FileSystemSkillProvider`](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/skill/skill-filesystem/src/index.ts)默认同 scope 内 rank：项目 `.dsh/skills` 100、`.agents/skills` 200、customSkillDirs 300、`$DSH_HOME/skills` 400、agentsHome/skills 500、bundledSkillDir 600；agentsHome 默认 HOME/.agents，可受 DSH_AGENTS_HOME 影响。默认根关闭或可选路径未配置时不应把全部 rank 当实际加载目录。[`collectFresh`](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/skill/skill/src/index.ts)跨 scope 以较近 scope 优先，rank 只在同 scope 内比较。原生重复项优先级不是 rotom 同名源技能的显式覆盖授权。
- 技能目录需要 SKILL.md frontmatter 的 name/description，并以 directory resourceBase 提供资源。拟托管 `$DSH_HOME/skills/<name>/` 完整包、相对资源及执行位；加载/复制不执行脚本。项目技能可以遮蔽用户技能；本次小包仅是合成资源测试，不是产品大 C++ 导航技能。
- [profile composition](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/apps/cli/src/profile-boot.ts)顺序是 bundle 列表→profile patch→home patch→`--patch` argv 顺序→telemetry disable override。profile `cordis.yml` 由启动准备重写为空根，属于原生运行时，不是框架编译产物。package.json/node_modules 属包管理范围。settings 为混合字段所有权；会话、存储内容和 HOME/.dsh-tui 不进入普通受管备份。
- [`agent-presets.default`](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/preset/agent-presets/src/index.ts)用户 settings 优先于 composition default，影响新 session；可作为初始化候选，不自动持续强制。shipped preset root 默认早于用户 root，用户同名 standard 目录不能据此覆盖 shipped standard。

#### 已落盘证据与测试边界

- `tests/fixtures/native-config/provenance.json` 逐文件记录固定来源 URL/SHA、合成归属、修改说明、期望行为和 `not-run` 原生状态。`cordis-cases.yaml` 含有损 config、完整 config、仅元数据、空 patch 的输入/期望值；`settings-case.yaml` 记录清除用户覆盖并保留未注册 sibling 的期望。未知 `x-rotom-fixture`/namespace 是合成数据，不是已验证的插件字段。
- `js-cases.json` 保存拟允许值及负例；`tests/test_native_fixtures.py` 只用 SafeLoader 的 **compose 语法节点**检查所有样本。标准 safe_load 拒绝包括候选允许值在内的未知标签，却能把未标记 `__jsExpr` 读成普通字典；这个区别不代表生产策略已实现或原生不会执行。
- `discovery.json` 只记录带条件的发现期望与符号路径，不展开路径或调用宿主；`rule.md` 保留普通文本；完整合成技能的资源和执行位通过数据复制检查。仓库模式校验限于 Git 可保留的执行位，未验证生产部署的 0700/0600 权限。
- 这些测试不重写上游 patch/settings 算法、不执行 JS、不调用 native discovery、不运行脚本。完整依赖闭包、发布字节对应关系、动态 provider 保留、生产安全 loader、实际 preset 装载与 Linux/macOS 原生 smoke 均未验收；任务 1.3 不因 fixtures 完整而自动视为全部完成。
- 本次 Linux 隔离验证：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_native_fixtures.py` 为 11 passed；相同临时 HOME/净化环境下全套为 282 passed、7 subtests passed。现有 `tests/conftest.py` 网络/进程防护未修改。TDD 初次因 fixtures 缺失而 11 failed；中间发现测试把隔离设施创建的 tmp_path 误认为空目录，改用现有文件哨兵比较前后状态后通过。
- MCP、认证、偏好和 OpenSpec 的后续源码调查见下文，未计入本节 fixture 验证。

### 认证入口（1.4 源码证据，阻塞）

- [bundled auth](https://github.com/ccch1mneyyy/dsh-auth/blob/cc6ec5224b62b6e6508c0109ef19e93b0a5c0a0e/src/index.ts)支持 `providers: [openai-codex]`；原生 `/auth login openai-codex` 入口无需社区插件，也不等于已授权登录。凭据文件由原生管理，不纳入 capture/previous。
- [社区模型注册](https://github.com/xxww0098/dsh-plugin-oauth-subs/blob/793978ee3b72a1c81d8b769b269ac2fa3bc90654/src/oauth/models.ts)默认前缀 oauth，Cursor route 为 `oauth-cursor`，社区 Codex 为登录后条件生成的 `oauth-codex`，不是无条件重复注册 `openai-codex`。模型筛选不是永久关闭其他认证能力：新增普通目录项默认开启。不得使用 openai 前缀造成同 ID 冲突。
- [公开 Config](https://github.com/xxww0098/dsh-plugin-oauth-subs/blob/793978ee3b72a1c81d8b769b269ac2fa3bc90654/src/index.ts)仅 port/provider/dataDir/grokLogin；provider 是路由前缀，不是 Cursor 选择器。[controller](https://github.com/xxww0098/dsh-plugin-oauth-subs/blob/793978ee3b72a1c81d8b769b269ac2fa3bc90654/src/oauth/controller.ts)默认自动导入本机凭据，未暴露关闭配置；NODE_TEST_CONTEXT 是测试入口，不作为生产关闭机制。[Cursor import](https://github.com/xxww0098/dsh-plugin-oauth-subs/blob/793978ee3b72a1c81d8b769b269ac2fa3bc90654/src/oauth/cursor/import.ts)调用 macOS security 且未指定隔离 keychain，已由父任务独立读取源码确认；仅 HOME 隔离不足，禁止当前用户环境启动。Linux/WSL 也不能把 HOME 当作 OS 沙箱。
- proxy 默认端口 8318 可配置、绑定 127.0.0.1；它不是 Web 登录端口。Cursor 使用远程登录轮询，不是本地 OAuth callback；同一隔离 TUI profile 临时挂载 Web 的精确启动方式仍待核实。全部入口均未执行。
- [社区 manifest](https://github.com/xxww0098/dsh-plugin-oauth-subs/blob/793978ee3b72a1c81d8b769b269ac2fa3bc90654/package.json)版本为 0.0.88，但 npm 同名根路径与版本端点返回 404，不能生成已验证 npm 安装配方。Git 分发 src/lib 对应、完整闭包、客户端 stamp 写入与原生加载仍待验证。

### 偏好、环境与 MCP（1.5 源码证据）

- [ThemeProvider](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/src/components/design-system/ThemeProvider.tsx)启动时 prop → DSH_TUI_THEME → HOME/.dsh-tui/theme.json；选中的无效环境主题进入探测，不回退到持久化主题。运行中 /theme 可改变选择，环境值不是持续锁。[静态主题](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/src/customTheme.ts)来自 HOME/.dsh-tui/themes/*.json，base 为 light/dark/dark-ansi；Poimandres 风格需要自有静态配色，不能假称内置。
- [effort 默认](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/src/effortPrefs.ts)为 settings 的 dsh-tui.effortDefault → config.effort → effort.json → 模型默认；auto 递延，不必然直达模型默认。具体档位须与模型能力核对。[preset](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/src/dsh-adapter/plugin.ts)新会话按 config.preset → 文件偏好 → roster default；DSH_TUI_PRESET 通过 shipped Cordis 表达式接入，而非插件直接读取。恢复会话使用记录的 preset；[不存在的 preset](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/src/dsh-adapter/presets.ts)可警告后无 preset 继续，非零错误检查不足以证明 standard 已装载。
- [终端图像探测](https://github.com/ccch1mneyyy/dsh-TUI/blob/78081cebde1ee1b47a561ef57c04f128c5623476/src/ink/ink.tsx)支持 DSH_TUI_DISABLE_TERMINAL_IMAGES=1 强制关闭；与模型视觉能力独立。原生字段 terminalImages 保存值可优先于 config 且有进程 latch；不得声称 reload 即生效。HOME/.dsh-tui 无已确认专用环境重定向，不接管真实偏好目录。
- [credentials-local](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/credentials/credentials-local/src/index.ts)引用解析为继承环境 → managed store → cwd/.env → DSH_HOME/.env；apiKeyEnv 是变量名，不是密钥或 env:NAME。框架必须提前确认显式 secret 引用，不能依赖隐式发现；不把该链泛化为所有 OAuth/provider 优先级。
- **启动隔离阻塞：**[loadLayeredEnv](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/boot/app-boot/src/index.ts)还会在启动时读取 cwd/.env 与 DSH_HOME/.env，将允许项写入 process.env。未找到公开禁用入口；仅净化 env 不足，不能静默更换 cwd 来绕过并破坏工作区语义。原生 reserved-name 黑名单也不能代替框架环境白名单。
- [MCP schema](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/mcp/mcp-client/src/index.ts)支持 stdio（serverName/command/args/env/cwd）和 streamable-http（serverName/url/headers），没有独立 legacy sse 配置类型。[transport](https://github.com/deepseek-ai/deepseek-harness/blob/183f08e9c6dde7e36cd2318eaee70b0da08fb35e/packages/mcp/mcp-client/src/transport.ts)不解析 env:NAME 或 ${NAME}；秘密字段需要精确生成的 !!js process.env.<变量名> 标量叶节点与运行时注入。安全惰性白名单尚未实现，不能接受任意 JS。原生 stdio 环境只做启发式 secret-name 清理，显式 env 随后覆盖，不是完整沙箱；启动可连接远端，failOnStartupError=false 也不代表连接成功。

### OpenSpec 项目集成（1.6 源码证据）

- [版本元数据](https://registry.npmjs.org/@fission-ai%2fopenspec/1.13.0)与[固定 manifest](https://github.com/Fission-AI/OpenSpec/blob/9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461/package.json)确认发布候选；Node >=20.19.0、源码 pnpm@10.34.5，不代表全部传递包引擎或产品锁已验证。bin 依赖完整 dist 与运行时 node_modules，不能只复制脚本。声明 SRI/provenance payload 不是签名或下载字节验证。
- [官方 agents 路线](https://github.com/Fission-AI/OpenSpec/blob/9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461/docs/supported-tools.md)支持未列出的、读取 .agents/skills 的工具；[实际工具表](https://github.com/Fission-AI/OpenSpec/blob/9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461/src/core/config.ts)没有 dsh/custom ID。使用 agents 不是 DSH 原生适配已通过。core 生成 propose/explore/apply-change/update-change/sync-specs/archive-change 六个 openspec-* 技能和 .openspec-target（agents 加换行）；不创建 DSH slash-command 或 AGENTS.md。
- [CLI](https://github.com/Fission-AI/OpenSpec/blob/9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461/src/cli/index.ts)的 init --tools agents --profile core --no-animation 是待验证非交互候选；update 无 --tools 限定。skills/both delivery 才适用 agents，隔离全局配置；生成内容内的裸 openspec 命令还须由受控 PATH 解析到产品固定 CLI，不能借用开发者全局安装。
- **项目保护阻塞：**[init](https://github.com/Fission-AI/OpenSpec/blob/9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461/src/core/init.ts)/[update](https://github.com/Fission-AI/OpenSpec/blob/9d4e5974e5c0d9a09b9c6c1e1eb0975e80ec4461/src/core/update.ts)会覆盖所生成技能、清理旧产物或被取消选择的目录；非交互 init 也可能做 legacy cleanup，不能直接透传到已有项目。未来 wrapper 必须库存比对、同字节 no-op、用户修改冲突、符号链接边界和部分失败记录；暂存生成只是待验证方案。
- 将来仅在授权的空临时项目、独立 HOME/XDG、非 TTY 和网络限制下执行，设置 OPENSPEC_TELEMETRY=0、DO_NOT_TRACK=1、OPENSPEC_NO_UPDATE_CHECK=1；环境变量不等于 OS 沙箱。尚未安装、初始化项目或证明 DSH 实际读取六个技能。

### 验收分级（最新）

| 级别 | 描述 | 状态 |
|------|------|------|
| 离线测试 | schema/合并/render/部署/备份/启动契约/项目保护 | 最终数量与命令见 acceptance.md |
| 无账号 smoke | 锁定 DSH/TUI/Cursor/OpenSpec，临时 home | Linux 已通过，非真实模型调用 |
| 授权 live | 用户授权后真实 Codex/Cursor 调用 | 待授权 |

## 平台记录

| 平台 | 离线测试 | 无账号 smoke | 授权 live |
|------|---------|-------------|----------|
| Linux | 最终数量见 acceptance.md | 已执行通过 | 未执行 |
| macOS | 待验证 | 待验证 | 待验证 |

## Superpowers 缺席检查

- [x] 完整锁与实际安装树中未发现 Superpowers；读锁校验会拒绝对应包名。
