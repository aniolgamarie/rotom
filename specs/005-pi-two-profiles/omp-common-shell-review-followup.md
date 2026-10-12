# OMP 常见静态 shell 语法的模型审核修复

2026-10-09 用户实际反馈：smart/ready、原生 Bash delegate 可用，`ls ~/bin /usr/local/bin 2>/dev/null | grep -i ob; command -v ob; type ob 2>&1` 却显示 `Allow bash? / UNSUPPORTED_SYNTAX / STANDARD_CONTEXT`。主仓库当前提交 `25a5b1c136c888dc7a3850b018c7d5546aa5d197` 的独立插件能静态解释该提示；Pi 升级工作树中的旧副本不能代表当前部署。当前 parser 已支持管道、分号和这些重定向，真正拒绝点是未引号 `~` 以及统一禁用的 `command` 包装器。

只在 `/tmp/rotom-omp-shell-risk-review-20261009` 的最新源码隔离副本实施；主仓库与实际部署暂时只读。允许修改自有 `standalone-shell-analysis.ts`、相关 `standalone.test.ts`/已有 native fake 测试、插件 README，不能改官方 OMP/SDK/vendor 或宿主。所有待审命令是数据，绝不真正执行它们；fetch、UI、native delegate/exec、models/settings 都是假实现。

## 已决定的最小语法

- 支持普通参数位置的未引号 `~`、`~/...`，保留原文，不读取/解析真实 HOME、不扩展路径。解析结果单独记录 `homeExpansions` 参数索引，不能当成已解析的固定路径。quoted/escaped tilde 是普通字面量；命令头、重定向目标、`~user`、`~+`、`~-`、动态插值等仍 unsupported。
- 原生 pattern 匹配的潜在不确定性必须同时涵盖 glob 和 HOME 参数。只要配置的 deny/prompt 对该命令及具体参数可能适用、无法证明不相交，就保守拒绝/人工，模型不能解除该下限。宽泛 deny、raw deny、可见前缀 deny 和其他既有保护不变。
- 支持确切 shell builtin `command -v NAME...`、`command -V NAME...` 的静态查询形式，可接受固定的可选 `--`；至少一个名字，不把执行型 `command CMD...`、`-p`、混合/未知 flags 或类似名称的自定义路径程序当成查询。每个复合子命令仍独立检查原生限制。`type ob` 已有支持，无需为它增加执行白名单。
- 不增加自动允许规则。符合该语法、无 native deny/prompt、具有有效用户来源且未含凭据的 smart 请求才进入原有模型审核，只有原有严格 low-risk/sufficient-authority allow 才消费原票据执行；原始 command/cwd/params 与 source/settings/session/generation recheck 保持不变。

## 验收与边界

先在最新隔离副本中保存实际 red，覆盖用户原命令及第二条 Git 管道命令作为数据。修复后证明 smart 分支调用一次假模型、无人工提示、仅一次假 delegate/exec、原命令未改。另测查询包装器负例、quoted/escaped tilde、HOME 位于命令头/重定向的拒绝、带 HOME/glob 的配置 deny/prompt 不被模型绕过，以及既有 native setting/epoch/cancel/credentials保护回归。

复用已固定 Bun 1.4.0 与 `run_typescript` 的离线 fake runner/preload；不调用历史 `prepare_materials`、不应用宿主补丁、不启动 OMP/TUI/worker、不读取账号或调用真实模型。默认环境不足单列，不算功能通过。生产 native/runtime/helper 不变，只修改语法和测试；两次有效失败或前提变化升级 root。

写入结束后针对稳定 diff/pins 做独立复核。主仓库源码回填、构建锁/运行包更新和实际会话验收分别处理，不自动替换/终止当前活动会话；真实 OMP smoke 仍需单独明确授权。本修复不替代正在进行的 Pi Base/Full 长期任务，Pi SDK4 和默认功能已完成的有限证据保留，正式 8/100、Pi AUTO OFF。

## 当前默认结果与固定语法差量

最新隔离副本实现已停止写入，正式两模块一次 73 passed / 0 failed、53,651 assertions；稳定独立源码差量 0P1/0P2。两条用户命令作为数据分别走一次假模型和一次假原生 delegate，原对象/command 未改，没有真正执行 shell。原 native/settings/session/ticket 实现和官方 OMP/SDK 均未改。

原语料 11,473 条的 gzip、parse 结构和旧 gate 标签保持冻结。历史 parser 仍与全部原 parse 相符；新测试仅从 root 审核的固定 583 ID+原行摘要差量取得升级期望（HOME501/query74/两者8），其余10,890条保留旧门，含12条语法完整但隐私层人工案例。实际 fake 循环记录10,013条审核/1,460条人工边界，无差异；root另有限核对全部保存 gate rows。`review` 只代表可进入假模型审核，不是风险低或真实用户已授权。此前 raw/corpus/schema 失败及没有逐行实际门的分析历史全部保留，不重新标为通过。

独立审查有一次单行 shard 输出超出其输入预算，报告已记录并停止追加读取；它不声称全量逐行复核。root另按固定 shard 哈希、512KiB/份和16MiB解压上限完成所有保存 gate rows 核对，没有重跑测试。主仓库与部署仍未改；后续使用现有原 official OMP 生成器更新本地插件树摘要和锁，不调用退休宿主补丁构建器。
