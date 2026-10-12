# T002 来源与资源差量审计

日期：2026-10-04。此表是现有公开来源的静态审计及新组合的候选处置，不是运行锁或已通过安装清单。当前运行包仍为0.84.4；Q1正式发行物、许可/依赖闭包、实际加载由T006/T028/T095完成。旧活动和恢复引用继续保护，不改写001或starter。

## 输入身份

| 文件 | SHA-256 |
|---|---|
| `agents/pi/migration/capabilities.toml` | `b28566f20141db317b465f3c0a15e4221ba67171b6434aea0693d270117c3827` |
| `agents/pi/migration/resource-manifest.json` | `370ca3571849b61aa284a440302e6da5b12150ca3add5c082106e372b0fde2bb` |
| `agents/pi/migration/local-plugins-manifest.json` | `fa208c9bdeecfbe8d376694f34cebc2ab37ea7bd20da08519a2be920204a87c7` |
| `agents/pi/migration/preset-manifest.json` | `30c576d4f3dc23cc19fa8b2c60fb2c0c340b3cfca629eb14e4d7c1353004e922` |
| `agents/pi/migration/role-map.json` | `93016030cb6dc0f66173a4ae5840ddf2b5566b44f7afa1ba1f2d978f1d327337` |
| `agents/pi/dependencies.json` | `427e58c7a480b50e2f96f58259637db606c102e14c6a7e6860263685f5209dde` |
| `agents/pi/plugins.toml` | `5c4d664b6f5b7359206a613e87ba0d943061931cfed1f70a26121482ddf2d86b` |
| `profiles/pi-default.toml` | `ba46c9f42a026bfda2079042fd2ed6b25a15e4fc7a4e39391592effd07f4c039` |
| `shared/defaults/models.toml` | `2f274df3be37a2c5c02114db55930466b29810270ef78910ad3a6c6bdf230451` |

## 既有能力与关联资源（82项）

| ID / 类型 | 原目标 | Base候选处置 | Full候选处置 | 理由与任务 |
|---|---|---|---|---|
| `pi-host` / tool | `locks/pi` | 升级候选 | 升级候选 | 官方1.0.1公开API；T006/T009，发行物未验 |
| `pi-mcp` / plugin | `locks/pi` | 原生替代 | 原生替代 | 原生MCP/Code Mode；T024，不携带旧包 |
| `openspec` / plugin | `locks/pi` | 初始排除 | 初始排除 | 不进入首批默认组合；项目按需选择须另验，T002/T025 |
| `pi-permissions` / plugin | `locks/pi` | 独立扩展替代 | 独立扩展替代 | 统一权限；T032，退出旧subagents耦合 |
| `pi-web` / plugin | `locks/pi` | 初始排除 | 初始排除 | 不进入首批默认组合；项目按需选择须另验，T002/T025 |
| `pi-readseek` / plugin | `locks/pi` | 初始排除 | 初始排除 | 不进入首批默认组合；项目按需选择须另验，T002/T025 |
| `pi-slopchop` / plugin | `locks/pi` | 初始排除 | 初始排除 | 不进入首批默认组合；项目按需选择须另验，T002/T025 |
| `pi-subagents` / plugin | `locks/pi` | 排除 | 统一delegate替代 | T060–T066单执行核心，不保留第二调度器 |
| `pi-todo` / plugin | `locks/pi` | 轻量保留候选 | 轻量保留候选 | T026真实状态；Q1/性能不满足则原生替代 |
| `pi-smart-compact` / plugin | `locks/pi` | 原生替代 | 原生替代 | T023仅一个压缩owner |
| `pi-cursor` / plugin | `locks/pi` | 初始排除 | 初始排除 | 不进入首批默认组合；项目按需选择须另验，T002/T025 |
| `pi-btw` / plugin | `locks/pi` | 初始排除 | 初始排除 | 不进入首批默认组合；项目按需选择须另验，T002/T025 |
| `pi-processes` / plugin | `locks/pi` | 受管监督替代/适配 | 受管监督替代/适配 | T020仅公开复用，否则自有监督；不改vendor |
| `pi-rules` / plugin | `locks/pi` | 短规则替代 | 短规则替代 | T025共享工程知识和项目规则，退出全局注入器 |
| `superpowers` / skill | `shared/skills` | 初始排除 | 初始排除 | 不进入首批默认组合；项目按需选择须另验，T002/T025 |
| `legacy-subagents` / plugin | `无受管目标` | 继续排除 | 继续排除 | 继承001最终处置，未纳入本次目标 |
| `task-keeper` / plugin | `agents/pi/packages/task-keeper` | 排除 | 适配保留 | T069–T075固定Inspect/Fix，改接统一delegate |
| `colorful-footer` / plugin | `agents/pi/packages/colorful-footer` | 适配保留 | 适配保留 | T026无隐式模型/服务，低干扰状态 |
| `loop-guard` / plugin | `agents/pi/packages/loop-guard` | 适配保留 | 适配保留 | T026只作无推理提醒，不拥有执行队列 |
| `openai-proxy` / plugin | `agents/pi/packages/openai-proxy` | 公开Provider替代 | 公开Provider替代 | T022退出global fetch/dispatcher包装，国内路线保留 |
| `session-yolo` / plugin | `agents/pi/packages/session-yolo` | 排除 | 排除 | T032单一审批权威，退出第二权限模式 |
| `model-delegate` / skill | `shared/skills/model-delegate` | 排除 | 适配保留 | T060–T066同一CLI核心与共享Skill |
| `model-delegate-bridge` / plugin | `agents/pi/packages/model-delegate` | 排除 | 适配保留 | T063调用同一核心 |
| `legacy-codex-agents` / plugin | `agents/pi/packages/model-delegate` | 排除 | 统一delegate替代 | T063不恢复旧入口 |
| `legacy-codex-delegate` / skill | `shared/skills/model-delegate` | 排除 | 统一delegate替代 | T063不恢复旧入口 |
| `skill-cpp-database-kernel` / skill | `shared/skills/cpp-database-kernel` | 完整保留 | 完整保留 | T025领域知识、脚本、资源、相对引用和权限完整迁移 |
| `skill-neovim-plugin-development` / skill | `shared/skills/neovim-plugin-development` | 完整保留 | 完整保留 | T025领域知识、脚本、资源、相对引用和权限完整迁移 |
| `skill-safe-linux-scripting` / skill | `shared/skills/safe-linux-scripting` | 完整保留 | 完整保留 | T025领域知识、脚本、资源、相对引用和权限完整迁移 |
| `role-scout` / role | `agents/pi/roles/scout.md` | 排除 | 按统一delegate/TK角色适配 | T063/T069可信角色与模型绑定，非旧subagents注册 |
| `role-reviewer` / role | `agents/pi/roles/reviewer.md` | 排除 | 按统一delegate/TK角色适配 | T063/T069可信角色与模型绑定，非旧subagents注册 |
| `role-task-keeper-reader` / role | `agents/pi/packages/task-keeper/agents/task-keeper-reader.md` | 排除 | 按统一delegate/TK角色适配 | T063/T069可信角色与模型绑定，非旧subagents注册 |
| `role-task-keeper-writer` / role | `agents/pi/packages/task-keeper/agents/task-keeper-writer.md` | 排除 | 按统一delegate/TK角色适配 | T063/T069可信角色与模型绑定，非旧subagents注册 |
| `role-task-keeper-reviewer` / role | `agents/pi/packages/task-keeper/agents/task-keeper-reviewer.md` | 排除 | 按统一delegate/TK角色适配 | T063/T069可信角色与模型绑定，非旧subagents注册 |
| `kernel-orchestrate` / skill | `agents/pi/packages/task-keeper/skills/kernel-orchestrate` | 排除 | 适配保留 | T069–T075 Full受管流程Skill |
| `legacy-role-codex-context-builder` / role | `shared/skills/model-delegate/presets/context.md` | 排除 | 仅保留映射后的preset | T063复用role-map，不注册旧角色或独立队列 |
| `legacy-role-codex-delegate` / role | `shared/skills/model-delegate/presets/general.md` | 排除 | 仅保留映射后的preset | T063复用role-map，不注册旧角色或独立队列 |
| `legacy-role-codex-oracle` / role | `shared/skills/model-delegate/presets/challenge.md` | 排除 | 仅保留映射后的preset | T063复用role-map，不注册旧角色或独立队列 |
| `legacy-role-codex-planner` / role | `shared/skills/model-delegate/presets/plan.md` | 排除 | 仅保留映射后的preset | T063复用role-map，不注册旧角色或独立队列 |
| `legacy-role-codex-researcher` / role | `shared/skills/model-delegate/presets/research.md` | 排除 | 仅保留映射后的preset | T063复用role-map，不注册旧角色或独立队列 |
| `legacy-role-codex-reviewer` / role | `shared/skills/model-delegate/presets/review.md` | 排除 | 仅保留映射后的preset | T063复用role-map，不注册旧角色或独立队列 |
| `legacy-role-codex-scout` / role | `shared/skills/model-delegate/presets/scout.md` | 排除 | 仅保留映射后的preset | T063复用role-map，不注册旧角色或独立队列 |
| `prompt-commit` / prompt | `agents/pi/prompts/commit.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-debug` / prompt | `agents/pi/prompts/debug.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-docs` / prompt | `agents/pi/prompts/docs.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-explain` / prompt | `agents/pi/prompts/explain.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-implement` / prompt | `agents/pi/prompts/implement.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-perf` / prompt | `agents/pi/prompts/perf.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-plan` / prompt | `agents/pi/prompts/plan.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-pr` / prompt | `agents/pi/prompts/pr.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-refactor` / prompt | `agents/pi/prompts/refactor.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-review` / prompt | `agents/pi/prompts/review.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-security` / prompt | `agents/pi/prompts/security.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `prompt-test` / prompt | `agents/pi/prompts/test.md` | 保留按需模板 | 保留按需模板 | T009/T025审查模板；T028/T095核实际发现，无隐式委派 |
| `theme-ayu-dark` / theme | `agents/pi/themes/Ayu Dark.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-catppuccin-mocha` / theme | `agents/pi/themes/Catppuccin Mocha.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-dracula` / theme | `agents/pi/themes/Dracula.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-everforest-dark` / theme | `agents/pi/themes/Everforest Dark.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-gruvbox-dark` / theme | `agents/pi/themes/Gruvbox Dark.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-kanagawa-wave` / theme | `agents/pi/themes/Kanagawa Wave.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-nord` / theme | `agents/pi/themes/Nord.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-one-dark` / theme | `agents/pi/themes/One Dark.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-rose-pine` / theme | `agents/pi/themes/Rosé Pine.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-tokyo-night` / theme | `agents/pi/themes/Tokyo Night.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `theme-poimandres` / theme | `agents/pi/themes/poimandres.json` | 仅everforest-dark默认，其余不加载 | 仅everforest-dark默认，其余不加载 | T026低干扰终端；其它主题保留来源，按需选择另验 |
| `extension-dirty-repo-guard` / plugin | `agents/pi/extensions/dirty-repo-guard.ts` | 初始排除 | 初始排除 | 旧默认profile未选择；不隐式加载，必要行为由原生/受管入口承担 |
| `extension-exit-command` / plugin | `agents/pi/extensions/exit-command.ts` | 初始排除 | 初始排除 | 旧默认profile未选择；不隐式加载，必要行为由原生/受管入口承担 |
| `extension-gentle-agent-state` / plugin | `agents/pi/extensions/gentle-agent-state.ts` | 初始排除 | 初始排除 | 旧默认profile未选择；不隐式加载，必要行为由原生/受管入口承担 |
| `extension-git-checkpoint` / plugin | `agents/pi/extensions/git-checkpoint.ts` | 初始排除 | 初始排除 | 旧默认profile未选择；不隐式加载，必要行为由原生/受管入口承担 |
| `extension-handoff` / plugin | `agents/pi/extensions/handoff.ts` | 原生会话替代 | 原生会话替代 | T023会话/分支/交接保留约束；旧扩展不隐式加载 |
| `extension-notify` / plugin | `agents/pi/extensions/notify.ts` | 初始排除 | 初始排除 | 旧默认profile未选择；不隐式加载，必要行为由原生/受管入口承担 |
| `config-settings` / configuration | `agents/pi/templates` | 原生字段适配 | 原生字段适配 | T009/T012严格schema及三方部署 |
| `config-models` / configuration | `agents/pi/templates` | 共享默认值适配 | 共享默认值适配 | shared/defaults/models.toml及本机覆盖；T021/T022 |
| `config-keybindings` / configuration | `agents/pi/templates` | 保留/原生适配 | 保留/原生适配 | T026按CLI/SSH真实体验选择 |
| `config-subagents-config` / configuration | `agents/pi/templates` | 排除 | delegate配置替代 | T009/T063不注册旧subagents调度器 |
| `config-global-rules` / configuration | `agents/pi/templates` | 短规则替代 | 短规则替代 | T025不叠加全局工作流 |
| `config-append-system` / configuration | `agents/pi/templates` | 显式短规则适配 | 显式短规则适配 | T023/T025显式输入，不发现祖先SYSTEM/APPEND |
| `config-mcp` / configuration | `agents/pi/templates` | 原生MCP配置替代 | 原生MCP配置替代 | T024公开配置链与项目信任 |
| `legacy-plan-mode` / plugin | `无受管目标` | 继续排除 | 继续排除 | 继承001最终处置，未纳入本次目标 |
| `legacy-spark` / configuration | `无受管目标` | 继续排除 | 继续排除 | 继承001最终处置，未纳入本次目标 |
| `external-herdr` / plugin | `无受管目标` | 继续排除 | 继续排除 | 继承001最终处置，未纳入本次目标 |
| `legacy-rpiv-mirror` / plugin | `无受管目标` | 继续排除 | 继续排除 | 继承001最终处置，未纳入本次目标 |
| `legacy-subagent-config` / configuration | `无受管目标` | 继续排除 | 继续排除 | 继承001最终处置，未纳入本次目标 |

## 现有依赖来源（38项）

| source ID | 类型 / 版本或固定资产 | Base | Full | 原声明许可证文件 |
|---|---|---|---|---|
| `pi-host` | npm / `0.84.4` | 升级候选 | 升级候选 | `LICENSE` |
| `pi-subagents` | git / `0.19.0-agentcfg.1` | 排除 | 统一delegate替代 | `LICENSE` |
| `pi-permissions` | local / `29.3.0-agentcfg.1` | 独立扩展替代 | 独立扩展替代 | `LICENSE` |
| `task-keeper` | local / `0.2.0-agentcfg.1` | 排除 | 适配保留 | `LICENSE` |
| `model-delegate` | local / `0.2.0-agentcfg.1` | 排除 | 适配保留 | `LICENSE` |
| `pi-cursor` | npm / `1.4.29` | 初始排除 | 初始排除 | `LICENSE` |
| `pi-runtime` | local / `1.0.0` | 适配保留 | 适配保留 | `NOTICE.md` |
| `pi-processes` | local / `0.11.1-agentcfg.1` | 受管监督替代/适配 | 受管监督替代/适配 | `package.json`, `README.md`, `NOTICE.agentcfg.md` |
| `openspec` | local / `1.11.0-agentcfg.1` | 初始排除 | 初始排除 | `LICENSE`, `NOTICE.md` |
| `pi-rules` | local / `0.6.0-agentcfg.1` | 短规则替代 | 短规则替代 | `LICENSE`, `NOTICE.agentcfg.md` |
| `codex-darwin-arm64` | asset / `344310a0a591c1b192e04feff304321a69907c9498baaac331ca7e16ebcef9d7` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-linux-arm64` | asset / `583b48df32804213bdcd338c2e5adb06b34340821fa757a726cc0a524fa33c27` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-darwin-x86_64` | asset / `1219c837d8f813b493a424c125c0038b5d9ca16279bc6d3fe6ce037a3e18a6e7` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-linux-x86_64` | asset / `d7e18b2597ae8f242f5f31ee9e90deef48dbc9edd634d9868fb6435d08c07f02` | 排除 | Linux所需资产按需保留 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `superpowers` | git / `6.3.0-agentcfg.1` | 初始排除 | 初始排除 | `LICENSE`, `NOTICE.agentcfg.md` |
| `session-yolo` | local / `0.1.0` | 排除 | 排除 | `LICENSE` |
| `colorful-footer` | local / `0.1.0` | 适配保留 | 适配保留 | `LICENSE` |
| `loop-guard` | local / `0.1.0` | 适配保留 | 适配保留 | `LICENSE` |
| `openai-proxy` | local / `0.2.0` | 公开Provider替代 | 公开Provider替代 | `LICENSE` |
| `pi-btw` | local / `0.55.3-agentcfg.1` | 初始排除 | 初始排除 | `LICENSE`, `NOTICE.agentcfg.md` |
| `pi-smart-compact` | local / `9.6.0-agentcfg.1` | 原生替代 | 原生替代 | `LICENSE`, `NOTICE.agentcfg.md` |
| `pi-slopchop` | local / `0.10.1-agentcfg.1` | 初始排除 | 初始排除 | `LICENSE`, `NOTICE.agentcfg.md` |
| `pi-mcp` | local / `2.32.1-agentcfg.1` | 原生替代 | 原生替代 | `LICENSE`, `NOTICE.agentcfg.md` |
| `pi-readseek` | local / `0.9.16-agentcfg.1` | 初始排除 | 初始排除 | `LICENSE`, `NOTICE.agentcfg.md` |
| `readseek-vision-model` | asset / `089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae` | 初始排除 | 初始排除 | `agents/pi/build/licenses/readseek-vision/LICENSE`, `agents/pi/build/licenses/readseek-vision/SOURCE.json` |
| `readseek-vision-projector` | asset / `f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82` | 初始排除 | 初始排除 | `agents/pi/build/licenses/readseek-vision/LICENSE`, `agents/pi/build/licenses/readseek-vision/SOURCE.json` |
| `pi-web` | local / `0.27.0-agentcfg.1` | 初始排除 | 初始排除 | `LICENSE`, `NOTICE.agentcfg.md` |
| `codex-bwrap-linux-arm64` | asset / `37c89f161e8a42f9ca51dc4b9f83029579143ca54fcffc54e865f27968b4e01a` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE`, `agents/pi/build/licenses/codex-bwrap/LICENSE`, `agents/pi/build/licenses/codex-bwrap/COPYING`, `agents/pi/build/licenses/codex-bwrap/SOURCE.json` |
| `codex-bwrap-linux-x86_64` | asset / `1e6a0f2802c4199f81e1d3d9a962d64dc274693d8391f02d1f4ab457e57c4c38` | 排除 | Linux所需资产按需保留 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE`, `agents/pi/build/licenses/codex-bwrap/LICENSE`, `agents/pi/build/licenses/codex-bwrap/COPYING`, `agents/pi/build/licenses/codex-bwrap/SOURCE.json` |
| `codex-code-mode-host-linux-x86_64` | asset / `a68df7cca23c6da7cde175677df7de61c73a234add1333a1254b86d641af01f7` | 排除 | Linux所需资产按需保留 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-code-mode-host-linux-arm64` | asset / `20aefa302c2022b496e32911bf954a5f76c7fd749c6bdb9fbd711e32b66dcbfa` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-code-mode-host-darwin-x86_64` | asset / `a0fa6141e591f44dc2d86a589cfe797212317bfb9fa3a6c73131e4dbb93387fe` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-code-mode-host-darwin-arm64` | asset / `500ee2a02ea598ae519052e7d7d8e201d1db01986f30c214ef4143645dc86fad` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-responses-api-proxy-linux-x86_64` | asset / `48ef0c02b6c81480399def382d9ee27f00fdb1b7598f13e2777e49881ec3a0f4` | 排除 | Linux所需资产按需保留 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-responses-api-proxy-linux-arm64` | asset / `442529846abc18269a97ab55e6961efb554a40d6389587540a1b1fa54b110f13` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-responses-api-proxy-darwin-x86_64` | asset / `18088240f41c105d06b43779d77649010e185427f59c4cebcd84a4c5b156a541` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `codex-responses-api-proxy-darwin-arm64` | asset / `8c39490849013988e66098385f79105c597c6bbbe223f839211eb525f1420418` | 排除 | 当前平台排除 | `agents/pi/build/licenses/codex/LICENSE`, `agents/pi/build/licenses/codex/NOTICE` |
| `pi-todo` | local / `2.9.0-agentcfg.1` | 轻量保留候选 | 轻量保留候选 | `LICENSE`, `AGENTCFG-NOTICE.md` |

新来源：独立权限适配属于现有pi-runtime；risk-review与durable-service为Full新增自有包，后者候选官方pi-durable 1.0.1；本轮未创建假source/版本或提前写入正式锁。许可证声明不代替正式发行物及完整传递依赖许可证复核。

## 行为与所有权差量

| 行为 | 决定及验收 |
|---|---|
| 配置合并 | 保留递归对象合并、数组语义与原生漂移三方处理；共享model default继续由既有resolver投影，T009/T012 |
| 资源删除 | 只删除受管且无活动/恢复引用的退出资源，排除项不可残留加载；T045/T046 |
| 备份/恢复 | 配置上一版、运行包选择、持久数据分别处理；失败不轮换备份；T012/T043/T091 |
| 安装 | 仅显式lock/sync；render/apply/run无安装；候选与正式锁分开，T006/T009/T012 |
| 私密状态 | 每profile独立home、会话、审批和服务状态；无原生token复制；T012/T021 |
| 加载来源 | 退出resource-loader的SDK prototype改写；仅公开loader/settings API与已锁本地路径；T023/T032及Q1 |

静态核对：能力表与最终catalog ID集合、source表与依赖声明ID集合完整相等，未以旧文档数量替代清单。源文件安装/加载行为尚须各任务以正反用例证明；所有产品验收仍为not-run。

## 官方 1.0.1 普通工具接口核对

本次只读核对使用已校验候选闭包内`@earendil-works/pi-coding-agent/dist`，没有运行宿主或修改候选内容。`index.d.ts:26`公开导出六个`create*ToolDefinition`，不需要访问内部AgentTool实现或改写SDK。

read/write/edit分别公开readFile/access、writeFile/mkdir、readFile/writeFile/access操作接口。现有`ordinary-operations.ts`为每次执行重建官方definition并注入受监督操作，保留schema、prepareArguments及edit精确替换语义；mkdir在SDK侧无操作，由安全文件worker在实际提交时逐级核验并建立目录。新入口的图像MIME检测仍需使用自有或公开接口，不能沿用旧启动器对发行包内部utils的依赖。

ls/find/grep目前只复用definition声明，execute由仓库受监督列表/读取/搜索覆盖。官方find默认可调用fd；grep即使提供isDirectory/readFile操作仍会ensureTool并spawn ripgrep（`core/tools/find.js:117`、`core/tools/grep.js:52`起）。局部operations注入不能被当作完整I/O接管，恢复默认execute会重新引入未准入的程序执行路径。现有自有搜索的匹配、忽略规则及输出格式尚未证明满足原生兼容目标，T019继续未完成；安全执行反例通过不能替代该项兼容验收，也不因此放宽原规格。

## Provider 配置身份的后续接入证据

`PiAdapter._fields`现在与新增model_configuration投影共用pi_model_config.py，API/baseUrl/models保持同源，apiKey只输出环境引用。official-models.ts将原生文件和公开Model绑定到部署投影，official-session把该摘要与实际非秘密Model描述纳入ConfigIdentity；单次会话仍以私有完整Model基线发现headers等后续漂移。正式初始化/Provider实现/认证来源绑定及许可接入仍留给T010，不据此宣布产品有效配置已经完整闭合。

官方1.0.1公开ModelRuntime.getProvider/getModel/getProviders及Provider/Model数据类型足以核对路由和声明模型行为，无须访问私有SDK对象。后续投影须由部署来源生成，并与实际公开Model逐字段核对；API、经过秘密边界验证的endpoint、模型兼容参数及账号/凭证的非秘密引用才可纳入身份。raw key、Provider/Model headers、auth回调/结果、环境秘密与OAuth内容均不能序列化或散列为身份。getAuth/model auth可涉及请求时秘密，只能在受信内存路径中处理；CredentialStore.read也不是非秘密身份接口。

公开扩展API允许注册/移除Provider，公开Session允许setModel；不能仅凭provider/id或每次重建基线就宣称动态路由始终受控。提供者stream函数、凭据驱动endpoint和动态注册仍须绑定受验收的提供者代码及可信宿主边界，正式发送/权限入口接入前不能据此签发执行许可。上述结论来自只读源码核对，未读取真实凭据或调用模型。


本阶段另外核对官方1.0.1的`provider-composer.js:71–102,137–168`：自定义models[]仅从候选默认模型继承api/baseUrl，其他缺省由modelFromJson决定；不会继承同名catalog的compat。`model-runtime.js:159–167,330–340`表明组合失败可回落基础Provider，同时由公开getError报告，故消费端必须拒绝任何非undefined错误状态。

`pi-ai/dist/types.d.ts:624–690`没有reasoningEffortMap，官方JS/d.ts无旧字段消费者；`models.js:681–690`及`api/openai-completions.js:625–719`读取顶层thinkingLevelMap。保留未知compat键不等于它生效，故新profile投影执行显式字段迁移。OAuth bindings当前为codex→openai-codex/pi-native与cursor→cursor/pi-cursor，后者初始配方排除；Codex官方catalog的compat仅见四类boolean能力，未知不透明参数没有通过默认支持。

上述证据来自已校验候选包的只读源码。新增Python/TS共同合成协议fixture用于防止两端字段与credential reference语法漂移；假SDK测试不等同于实际Provider请求、账号路线或新入口验收。

环境引用语法另经只读核对：`resolve-config-value.js:21–95`原生支持`$NAME`/`${NAME}`，`!`才触发命令；`provider-composer.js:208–210,227–291`和`model-runtime.js:447–475`在请求认证路径解析apiKey。仓库确定性`$AGENTCFG_PI_CREDENTIAL_<SHA16>`与该版本一致，不需替换为明文、不需自定义私有resolver。本阶段未执行解析或读取环境。

## 官方 ModelRuntime 初始化与账号来源

本次静态依据为候选闭包内 coding-agent **1.0.1** 与 pi-ai **1.0.2**，不是把整个闭包统称为1.0.1。coding-agent根入口公开导出ModelRuntime；`core/model-runtime.d.ts:4–20`允许显式credentials/authPath、modelsPath、modelsStore、allowModelNetwork与refreshOnCreate。实现`:78–106`在缺credentials时调用内部原生AuthStorage.create；AuthStorage本身不是公开根导出，不能deep import或复制其锁协议。原生工厂可能建立账号目录/文件，因此只准用于经授权的实例启动，不能用于render或只读诊断。

`refreshOnCreate:false`跳过初始化时整次refresh；单设allowModelNetwork:false不能阻止本地缓存和认证可用性探测。显式InMemoryModelsStore避免因modelsPath位置推导出模型缓存文件。SDK仍装载完整内建Provider目录，没有公开的Provider子集构造参数；unregisterProvider只撤销扩展注册，不能用于移除内建目录。此项不与Base排除Full包混淆，也不宣称运行时目录被过滤。

`ModelConfig.load`会重新打开modelsPath，私有config没有公开文件摘要。仅先验证models.json再传同一路径不能证明SDK消费相同字节。本仓库从已验证且冻结的非秘密部署声明生成配置，Linux下通过自有0700目录/0600文件建立只读FD，unlink后传`/proc/self/fd/<fd>`，同时继续检查原部署文件是否漂移。FD保留至宿主退出；SDK后续refresh可以重读相同inode。此原语不是kernel seal，同进程或同UID仍可能通过proc路径重新写入，测试只证明检测该变化，不把它冒充沙箱。平台无此能力时明确不可用。

另一公开选择`modelsPath:null`加registerProvider不用于本方案：`provider-composer.js:111–135`的扩展模型不补models.json的完整默认值，且`model-runtime.js:656–673`注册后执行不等待的全量refresh。`getRegisteredProviderConfig`返回内部可变对象引用，也不能作为冻结配置证明。当前实现没有覆写SDK方法、注册私有Provider或执行原生command resolver。

认证优先级见pi-ai `auth/resolve.js:14–38`和coding-agent `provider-composer.js:243–281`：已存Credential可优先于models.json的环境引用。API-key-only实例因此显式使用空InMemoryCredentialStore，不读默认或实例auth.json；含原生OAuth的实例显式传自己的authPath，由官方SDK持有文件锁、刷新和持久化。调用方以有界私有文件读取校验原生格式，再用公开listCredentials核对provider/type元数据；选定环境路线出现任何原生/运行时Credential均冲突，选定OAuth路线出现api_key也冲突。缺OAuth登录允许留给后续显式登录，不能改走另一账号。

原生AuthStorage可在读失败时保留缓存，且ModelRuntime.getError不包含其全部错误；因此元数据检查前后都复读当前私有文件，不只依赖getError。账号正文仅用于内存格式校验，不进入日志、身份或散列；正常token轮换不改变配置身份。此检查不证明同一类型token内容一致、不锁定后续请求、不取代正式发送准入或控制目录隔离。上述新增模块只有模拟测试证据，旧六项SDK探针不能自动算作它们的原生验收。

## 官方工具执行与会话来源接点

候选公开`extensions/types.d.ts:870–883`把InputSource定义为interactive/rpc/extension，但`agent-session.d.ts:165–175`的公开prompt options允许调用方传source。`sendUserMessage`实现`:1805–1839`固定标记extension，也可投递steer/followUp；streaming输入先经input handlers再入队（`:1501–1525`）。before_agent_start只含展开后的prompt/images，不含可证明某次人类操作的凭证。input handler抛错会被runner捕获并继续，不能用异常作为fail-closed授权门槛。来源标签和消息文本都不能单独签发许可。

公开ToolDefinition.execute的id、params、signal与ExtensionToolContext见`types.d.ts:491–492`；ctx提供cwd和只读sessionManager，后者公开getSessionId。tool_call发生于schema初验后，但其input可被后续handler原地修改，SDK明确不再次校验（`types.d.ts:894–947`、pi-agent-core `agent-loop.js:481–538,559–587`）。因此最终准入选择自有execute wrapper：先捕获最终参数，再经真实硬策略准备、决定、一次消费，不能把前置hook审批的参数当作之后不变。嵌套executeTool产生parent-id/n并携带parentToolCallId，但这些ID没有跨会话/重试全局唯一的公开保证；它们是绑定输入，不是授权令牌。

`agent-session-runtime.js:78–112,128–249`按before_switch/before_fork显式cancel结果决定是否切换，随后abort旧session、等待session_shutdown，再失效/销毁并创建新runtime。runner对事件异常只记录并继续；shutdown/agent_end/turn_end是通知，没有veto。宿主须用自己的取消代际和退役状态阻止迟到决定；AbortSignal仅描述当前执行取消。可信UI/控制面产生用户意图引用，通过宿主闭包绑定给wrapper；不能让工具参数或任意source标签自授这些字段。

以上只读证据决定接线方向，没有运行SDK。Python文件准入桥已接真实OrdinaryOperations/ExecutionStore；后续自有文件runtime组合把会话上下文、UI决定、execute wrapper和退役接入同一控制协议，但正式profile安装及CLI启用、原生组合验收仍未完成。

## 公开 UI 确认、原生 runtime 与退役组合

公开`ToolDefinition.execute`在AgentSession的工具包装中收到ExtensionToolContext（`extensions/wrapper.js:12–14`、`agent-session.js:2778–2827`），其中ctx.hasUI与ui.confirm属于公开接口；直接包装工具却未提供ctx factory时可能没有context，不能默认补成获准。`types.d.ts:39–45,72–80`声明`confirm(title,message,{signal?,timeout?}) -> Promise<boolean>`。noOp UI恒false；TUI仅Yes为true，No、取消、超时、abort为false（`runner.js:132–140,355–405`、`interactive-mode.js:2077–2120`）。RPC根据pending请求ID接收confirmed应答（`rpc-mode.js:47–86,612–623`），没有独立真人认证。因此实现要求受信前端、严格true、实际取消signal及await后重验；不能把hasUI或RPC应答宣传成真人身份校验。

公开`AgentSessionRuntime`及`createAgentSessionRuntime`由SDK根`index.d.ts:20`导出。工厂接cwd/agentDir/sessionManager/sessionStartEvent/projectTrustContext（`core/agent-session-runtime.d.ts:23–29`）；原生创建只保存session/services/diagnostics/modelFallbackMessage（`.js:311–315`），额外configurationSnapshot不会自动保留。自有组合必须用闭包持有快照，并在每个新session重建文件准入实例。

`setBeforeSessionInvalidate`是单个同步回调槽（`.d.ts:58–67`、`.js:75–76`）。切换中它在abort、session_shutdown之后，dispose之前执行；退出dispose路径则没有先abort（`.js:102–113,296–303`）。回调异常会阻止后续原生dispose。官方TUI构造又会设置自己的resetExtensionUI回调（`modes/interactive/interactive-mode.js:360–362`），直接预先安装一个准入回调会被覆盖。

据此，`official-file-runtime.ts`返回仓库自有公开facade，原始runtime保留在闭包，只转发公开属性/方法；facade的回调注册与唯一原生回调组合，先退役文件准入，再执行TUI清理。没有替换SDK方法、原型或访问私有字段。dispose先同步退役、调用公开session.abort，再调用runtime.dispose；失败保留，不靠再次dispose把未完成变成成功。现有假SDK被Object.freeze以验证不改写原生对象，并覆盖公开替换、取消、迟到确认、cleanup失败及配置变化。

此处证据为候选源码和隔离替身测试；新facade与原生TUI/RPC尚未共同执行，公开属性转发不等于真实终端兼容证明。CLI安装、完整输入/发送权限、自动策略与风险reviewer、所有入口隔离继续单列，不能由文件确认链替代。

独立最终审查补充：AgentSession公开dispose（`core/agent-session.d.ts:368`、`.js:977–996`）不经runtime回调，且没有公开disposed状态。当前官方TUI shutdown调用runtimeHost.dispose（`interactive-mode.js:3441,3455`），Print同样走runtimeHost.dispose（`print-mode.js:23–29`）；未找到本仓产品调用链直接绕过。保留公开AgentSession的facade不能阻止任意受信调用者主动直接dispose；合同要求前端生命周期通过runtime facade，后续新前端必须核对这个边界，不用SDK monkey patch补它。

### T009：Base 配置与资源投影差量

`profiles/pi-base.toml` 现在进入正式配置目录，独立默认值位于 `agents/pi/agent.toml` 的 `profile_defaults.pi-base`。共享 Provider／模型仍由 `shared/defaults/models.toml` 及本机覆盖解析，没有新建账户或读取密钥。`profile_plugins.pi-base` 只声明现有 todo、loop-guard、footer 来源；这些版本尚未获得现代 Pi 安装与兼容性验收，不能因配置可解析而声称已安装。

Base 不继承旧 defaults 中关闭态的 TK/delegate 结构。新普通模板及 `agents/pi/prompts/ordinary/{implement,plan,review}.md` 保留父会话直接实施、授权、验证和配置来源约束；旧 AGENTS/提示词继续供旧 profile 使用。其它九个旧提示词仍需在 T025 审查后接入现代组合，本次三项投影不改变原先保留全部按需模板的目标。

共享 `cpp-database-kernel/SKILL.md` 改为按项目明确配置的流程工作，去除强制 OpenSpec／旧受管工具依赖；保留十项领域检查和五项完成检查。**这是所有选择该共享 Skill 的 profile 共同接受的指导语义变更**，不承诺旧 Skill 字节或强制工作流要求不变。项目及旧 profile 的路由规则继续生效。迁移清单保留原始 source revision、git blob 和许可证，只更新当前目标摘要与 adaptation，不能把改后的目标内容当成原始上游内容。

Full 尚未注册正式 profile。现有 delegate/TK 包仍连接旧 SubagentsAdapter；risk-review 没有正式来源；Durable 仍是候选 SDK。它们应按实际的扩展、核心或独立服务登记能力提供者，不把每种能力都强制包装成 Pi 插件，也不捏造新版包身份。T009、T063、T069、T078 等对应实现与新锁仍待完成。

当前现代 profile 的启动明确返回 `pi-modern-launch-unavailable`，禁止落入旧 launcher。Base 渲染去掉 subagents.json、旧 runtime bridge 及 TK/Codex/Cursor 所有权路径；严格配置验证拒绝混入 Full/legacy 选项、角色和资源。新安装闭包、v2 正式锁、真实 CLI/宿主验证、可扩展提供者替换仍未交付，不能由这组配置/渲染证据外推。

### 后续普通提示词投影（2026-10-06）

此前只投影implement/plan/review的阶段边界已补充：commit/debug/docs/explain/perf/pr/refactor/security/test九项新增ordinary版本，保留执行路由之前的完整工程正文、示例、frontmatter及原source revision/blob/mode；只把受管Full指引改为父会话直接处理与实际能力/授权核验。九个旧模板字节及legacy渲染保持，迁移清单新增适配后目标SHA，不把改写目标标为原始上游字节。

Base的默认三项与可选项现在由不同声明表达。`profile_available_resources.pi-base.prompts`显式列12项ordinary资源，`profile_defaults`仍仅三项默认选择。schema与投影只接受已有prompt/global/canonical普通目录直接子项.md，不按名称前缀授权；未知ID、旧模板、其他kind、非规范/越界路径均失败，roles/themes/extensions不扩大。九项逐个显式选择可渲染，未选不加载。两模块一次48项默认测试（23既有、25新增）与稳定15文件审查无P1/P2，归档`ordinary-prompts/`。此前9项真实选择失败是默认等同可选的接口缺口，夹具/外层UID失败独立分类，不求和历史测试数。

本段只闭合普通提示词的声明/渲染组件，不闭合领域Skill全部迁移、native实际发现、正式锁/安装树或T025整体。新模板未执行脚本、命令、SDK或模型，Base/Full产品gate与正式任务7/100保持。

### T009：普通快照与 worker 安装边界

`pi_workspace_snapshot.py`承接原`pi_worker_files.snapshot`的完整算法，旧导入位置保留同函数引用；受保护路径、Git元数据、文件模式、符号链接文本和指定来源集合的行为不变。`HostSupervisor`只有在冻结manifest.plugins选择task-keeper时才导入并构造WorkerFiles/source_scope；worker协议也在选择检查后导入。普通workspace_snapshot不再导入高级worker实现。插件选择是该旧worker适配器的构造权威，options.task_keeper.enabled不能单独启用它。

监督层通过已注入worker_operation判断worker执行器是否存在，未选时拒绝worker_admission、worker分配、启动及授权；检查早于相应模块导入或新执行落盘。委派使用相同worker通道角色，但实际lease种类为external/codex，委派命令为check，因此不能按角色统一禁用。既有inspect/cancel/abort/recovery路径保持：没有spawn的分配不能用普通cancel释放预留，应使用已有abort_allocation；运行中cancel仍不把停止请求当作物理退出。

上一阶段静态扫描的official-file-runtime和official-model-runtime两组成入口合计18个TS文件，另须安装通过URL引用的regex-worker.ts。该扫描未包含后续新增的CLI、SupervisorClient、image-mime或调用方注入的extensionFactories。安装器必须按明确清单核对这些额外入口，不能仅把旧import扫描结果当完整可启动包。

现代普通文件runtime现已接入自有纯Buffer MIME检测，CLI提供冻结的仓库runtime上下文。剩余UI安装依赖仍须闭合：loop-guard从`@agentcfg/pi-runtime/capability-policy`导入，todo-vendor从`@agentcfg/pi-runtime/plugin-settings`导入，并分别依赖公开SDK/UI包；不能把旧全量runtime包带入Base来消除缺包错误。尚未运行这组现代来源的真实SDK组合；T009/T019/T026及产品gate不因此通过。

## 现代运行文件与公开CLI接线阶段

v2 slice现在必需声明`runtime_files`和`ai_package`。每个自有文件固定仓库source、安装path、转换方式、原始及安装字节摘要和0600模式；条目进入slice身份。生成前后、读取所选锁及安装时核对源内容，现代安装器只复制声明文件，不沿用旧全量TS/Python复制。`runtime/`和`supervisor/`精确核对文件与目录集合，拒绝额外文件、链接、缺失、模式或摘要漂移；资产不能占用这两个命名空间。运行描述和命令表另外生成并核对，避免把包含自身slice/runtime身份的描述循环散列到slice中。npm完整包图、完整运行树inventory与所选文件核对共同使用。

现代`profile.json`为schema2，带明确package_path/profile_id、宿主及AI包名/版本。AI从SDK包到slice根的Node查找层级中选择实际安装且有完整锁记录的包，不要求额外伪造能力source，也不查全局安装。描述中的runtime身份使用能力绑定后的实际身份；seal/status另核对lock、slice、profile、toolchain及描述。测试中的虚构七文件清单用于证明精确安装机制，不代表真实Base传递导入闭包；真实dependencies-modern/recipes-modern及完整来源许可仍未生成。

`official-launch.ts`提供实际main，使用SDK根公开导出与显式slice package.json解析SDK/AI；实例私有路径、平台/Node版本、manager握手身份通过后才初始化模型/会话。支持TUI、print、RPC、thinking和普通提示，拒绝未知或受保护的资源/模型/会话路径参数、RPC附带初始提示。运行中以私有原始manifest字节比较发现部署漂移，不散列整个秘密承载文档；只有已选非秘密权限/路径投影进入策略摘要。入口不传任意extensionFactories，runtime全局只安装自身冻结上下文并只清理自身引用。

独立静态审查发现TUI在初始化之后仍会执行catalog/version后台探测，单独设置ModelRuntime初始不刷新不足。入口在导入SDK前及初始化前强制官方`PI_OFFLINE=1`、`PI_SKIP_VERSION_CHECK=1`，移除触发tmux探测的`TMUX`；help不改变环境，运行后不恢复异步任务仍可能读取的开关。这只限制启动后台探测，不是模型请求断网或OS沙箱。

正常Print/RPC/TUI关闭会调用公开facade.dispose，launcher返回/抛错也清理；官方RPC重入shutdown、TUI致命错误/死终端/未捕获异常可直接process.exit。没有patch SDK或process.exit，也不声称finally覆盖硬退出；外层manager死亡观察、执行租约保留与恢复仍须后续原生验收。独立RPC探针授权仍未到达。

图片识别只消费已受监管读取的Buffer，支持JPEG/PNG/GIF/WebP/BMP，拒绝JPEG2000及动画PNG；PNG遍历至末尾且限制4096个chunk，拒绝截断与异常长度。不打开额外文件，不依赖SDK内部utils，不证明CRC/完整解码有效性；原生图片和搜索兼容验收仍未完成。

## 所选 UI 与独立 Linux helper 来源准备

仓库新增 `agents/pi/packages/runtime-ui`，包身份为自有 `@agentcfg/pi-runtime@2.0.0`，只有 `capability-policy` 的 `mayTransformHistory` 和 `plugin-settings` 的 `pluginSettings` 两个公开入口。它不导入 SDK、IO、控制器或其它依赖；旧完整 runtime 与 Full 额外接口不因此获得兼容性承诺。实际 loop-guard/todo 调用所需函数与公开导出由离线测试核对，尚未将这组 UI 在真实现代 SDK 中加载。

独立审查发现现代 launcher 原先没有建立这两个接口沿用的管理请求异步作用域。现在由自有入口创建 `AsyncLocalStorage`、放入自身冻结上下文并在退出时清理；实际 main 到所选 helper 的测试验证跨 await 暂停历史变换、退出作用域后恢复。未来内部请求仍须显式进入该作用域，此修复不等于 Full 派生请求接线完成。当前实际 CLI 的静态闭包为21个相对静态导入文件，加 `regex-worker.ts` URL资源，共22个自有运行文件；UI npm包和Python监督器集合另列，不能计入这22项而声称整个Base依赖闭合。

现代 Linux 宿主选择固定 `bin/pi-bwrap`，按 profile/runtime/lock/slice 和本地收据重验 helper、门控脚本及描述。缺失或漂移拒绝，不回退 Codex 专属资产或系统安装；旧 Codex 路线未改。该局部检查不是对同UID可同时改写收据和二进制者的外部证明。宿主仍使用保留原文件视图的PID生命周期范围，不能称已完成文件/网络沙箱。

独立 helper 选择原样 bubblewrap 0.13.0 源码，而不是把旧 Codex 发行辅助程序改名。其源码、libcap 2.77 和 Meson 1.9.0 已按固定摘要下载到私人候选缓存；未写入正式锁。源码准备器保留完整相对路径、仅物化两个原版许可证链接，拒绝越界/冲突/超限。原先人工缓存中 basename 导致的根 `meson.build` 覆盖已纠正，源归档未改变。构建、分发、真实进程与沙箱验收分别记录在 [Linux helper 构建边界](native-helper-build.md)，当前仍不能签发 T009 或 Base gate。


## 自建资产导入与 UI 依赖声明

独立helper现以build_record引用固定配方，输入归档、来源记录、产物归档和两份许可已显式导入现代家族工作区；没有伪造远程二进制URL。真实七文件只读复核通过，尚未执行helper或生成完整Base锁。详细来源、摘要、导入命令和信任边界见[Linux helper构建边界](native-helper-build.md)。提供者support_sources将辅助包/资产纳入同一来源和验收身份，切片不得漏项或夹带未声明来源。

Base所选colorful-footer/loop-guard/todo-vendor的SDK/TUI导入均来自官方包根公开导出，未发现SDK私有路径。footer补pi-tui peer；loop补pi-agent-core及自有runtime peer并把开发依赖固定为coding-agent1.0.1、agent-core/tui1.0.2；loop/todo的runtime范围为^1.0.0 || ^2.0.0，以容纳显式旧配方和现代最小包。现代依赖解析仍必须明确选择runtime-ui2，不能让通配peer隐式拉入宽runtime1；没有运行这组三UI，声明与静态符号存在不代替兼容验收。

Python来源闭包静态候选为53条声明：既有38项加Linux动态helper依赖、子进程脚本、六份生命周期schema及共用lazy路径。每条source/path/transform已对当前映射白名单和文件存在性核对，但当前REQUIRED只验证入口子集，仍须补必须项并在裁剪后的安装目录验证；静态清单不是已安装或实际恢复证明。22个JS文件另计，UI npm包/完整Python第三方依赖也不能由此推断已闭合。

## 真实 Base 候选声明与裁剪目录

`dependencies-modern.json`及`recipes-modern.json`现已登记初始Base候选：官方coding-agent1.0.1、ai/agent-core/tui1.0.2、最小自有runtime-ui2、footer/loop-guard/todo和独立Linux helper，共9个直接来源。SDK入口使用公开包根导出的dist/index.js。六个能力提供者明确主/辅助来源；全部以candidate_host_versions记录1.0.1待验证状态，verified_host_versions为空。该声明尚不是完整npm解析、正式modern manifest或Full配方。

四个直接官方Pi包共用的许可正文已从各自精确gitHead对应的源码证据补入`agents/pi/build/licenses/pi-modern/`，SOURCE.json保留包版本、发布SRI、提交、原文URL及正文摘要。另五个传递包的正文/版本对应仍不足：三个AWS包尚缺精确发布对应；proxy-agent-negotiate精确发布来源缺正文；standardwebhooks的JS包声明MIT而仓库根正文为Apache-2.0，不能直接替代。这些缺口仍阻止Q1完整来源验收，不能用SPDX字段当正文。

真实文件声明为22个JS加55条Python/脚本/schema，共77条。裁剪检查补出permission-policy和operation-grant两份先前静态清单遗漏的schema；现代入口现在强制八份运行schema，在含Linux平台时另强制namespace脚本和两个动态模块。该检查仍只是必要入口子集。离线测试实际安装声明文件、隔离Python包命名空间并导入自有模块及加载schema；删除真实传递模块后明确失败，不能从原checkout补齐。JS使用Node公开临时resolve hook限制所选源码导入，每次给整张图独立URL世代，删项反例不会被已加载缓存掩盖；21项静态导入和regex-worker URL资源分别核对。不调用launcher main、SDK或UI，不把源码导入证据当成生产转换、动态操作、真实安装或恢复验证。

完整npm候选现已在私人目录解析/安装，150包锁由官方146包原样版本/来源/SRI加四个自有包构成；当前Linux125包已安装并核对可用归档SRI，25个其他平台optional归档未下载未验。四个local安装文件逐字节匹配归档，三个真实UI源码通过独立侧车TypeScript5.9.3的strict/noEmit检查。侧车和开发工具不进入Base图，类型检查不执行SDK或UI；实际UI加载及todo等扩展工具的可用性仍待原生验证。npm11.19.1按官方SRI准备到私人目录，未将原随Node安装的11.9.0冒充为声明版本。未更新正式manifest或切换用户环境。

## 传递许可证补充来源（2026-10-05）

`agents/pi/build/licenses/pi-modern/TRANSITIVE-SOURCE.json`现保存五个传递包的精确发布URL/SRI、registry与package.json摘要、声明、正文来源种类和范围限制。三个AWS包附[Apache官方标准正文](https://www.apache.org/licenses/LICENSE-2.0.txt)，自有文件`APACHE-2.0.txt` SHA-256为`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`；不声称该正文来自AWS精确提交，不补造版权/NOTICE。两个MIT包仍待包范围正文，详情见research.md后续决定。

Q1与真实Base候选的五项version/resolved/integrity及已安装manifest摘要一致，旁车分别保存两张候选lock身份。scout核对静态依赖均为必需边，不因没有使用对应模型provider就当作未安装。旁车目前只作来源证据，现有直接source许可安装路径不会自动携带它；完整发行物的补充许可装配/收据绑定仍需实现，不能用新增文件冒充正式发布已闭合。所有第三方归档、vendor与安装包均保持原样。
