# T025 Base 领域资源离线闭合

本轮完成 Base 适用资源与纯渲染检查；不勾选 T025。T025 全文包含 Full 调度隔离和实际资源发现，现代 Full 尚未绑定，实际宿主加载由 T028/T095 验收；这些不因本次离线资源检查而通过。001 历史、starter 和用户项目工作流不修改，不运行迁入脚本。

## 已完成的差量

现有 C++ SKILL 的领域检查与已修改的项目自选流程段落完整保留，只追加相对 `references/database-contracts.md` 入口。新增参考由本仓库原创，按目标项目已有协议检查锁/内存序、MVCC 可见性/回收、WAL/提交/checkpoint/故障恢复、所有权/关闭、持久格式兼容与最小修改/验证，不把某种引擎的规则套用于所有项目，不引入执行平台或脚本。

| 资源 | 来源/处置 | Base 绑定及证据 |
| --- | --- | --- |
| cpp-database-kernel/SKILL.md、LICENSE | migration manifest 的 starter 基线；原内容及许可保留，新增参考链接 | shared/content.toml 注册；agent.toml 的 pi-base 默认 skill，真实 render_candidate 完整复制 |
| cpp-database-kernel/references/database-contracts.md | 本仓库新原创相对资源，补足可核对的 MVCC/WAL/恢复细则 | 随同一已选包复制为 pi-home/skills/cpp-database-kernel/references/database-contracts.md，无新选择权限 |
| repo-navigation/SKILL.md、references/cpp-local-context.md | 本仓库原创局部导航资源，原文件/相对引用不变 | shared registry 可用，但不冒称 Base 默认已选；Base 当前由已选 cpp-local-search 短规则承接局部导航 |
| cpp-local-search.md | 本仓库原创短规则，不改 | pi-base 默认 rules 已选；不自动索引、不修改项目流程 |
| neovim-plugin-development、safe-linux-scripting | D16/migration 基线引用，不重迁或删减 | 与 C++ 一起 Base 默认选用；新契约检查全部包文件/内容/许可与执行位 |
| ordinary implement/plan/review | 既有父会话直接处理模板，不改 | Base 默认只选这三项 |
| ordinary commit/debug/docs/explain/perf/pr/refactor/security/test | 既有工程正文及相对内容完整保留，原来源 blob/mode 与 legacy 对照；普通执行路由不变 | Base 显式可选而非默认注入；真实选择逐项渲染，不调用不存在的工具 |

完整包复制遵循原 collect_skills 的安全权限：非执行文件 0600，执行文件 0700，保留执行位而不放宽 group/world 权限。此次新增文件为 Markdown，无迁入执行脚本。没有为验证而扫描或执行 model-delegate 巨大 scripts。

Cpp migration `files[0]` 的目标 SKILL 内容身份由 Root 更新为 `f38d4cc5a4f674de66c57fa56f91cbd0eee2a1a1d46f5f2a522bb3f523eebc19`（1887B）；原 source_path/git_blob/source_mode/adaptation 不变。新参考身份 `5cc3152dcfc05d64b736cae220690953a732dd5354498b3d6181e204b7cb7046`（5542B）；这是本仓库差量，不冒称来自 starter。

## 能力与流程边界

Base 解析/完整候选中没有 model-delegate、kernel-orchestrate、Task Keeper 或 Durable 调度；十二个普通 prompts 不引导 `model_delegate`/`kernel_task`。原九个 legacy prompt 条件分支及工程正文不重写，Base 只选择对应普通模板。共享 registry 表示可选择资源，不表示全局注入；默认 domain/rules/prompts 中不含整套 superpowers/openspec。用户项目 AGENTS 与已有流程仍由当前项目/原生入口处理，不删除、不安装外部平台，不把普通模板当写入授权。

Full 调度知识保留在既有 model-delegate 与 Task Keeper/kernel-orchestrate 专用入口，不进入 Base；现代 Full 默认/显式选择尚未建立，不能写成“Full 已验收加载”。新增 Full 配置不在本包范围。实际项目规则/宿主资源发现与用户工作流运行未执行，仍归 T028/T095。

## 验证与交回

新 `tests/test_pi_base_domain_resources.py` 验实际 catalog/resolver/render_candidate 的 C++ 相对参考、所有已选包文件/内容/许可/执行位以及默认和显式普通 prompt 能力隔离，不启动宿主或迁入脚本。最小旧契约使用 ordinary prompts 的工程正文/来源/目标 SHA 对照及完整默认 skill 候选展开。

结果及不可变日志、最终 source/map pins、稳定差量放在 `.cache/pi-two-profiles/run-20261004/base-domain-resources-implementation-review01/`。Base 资源离线子项闭合，整体 T025 尚待 Full 选择及 T028/T095 实际加载独立验收；由 Root 决定最终任务状态，本文件不提升完成计数。
