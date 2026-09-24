# US3 只读盘点、审阅迁入和显式登录

日期：2026-09-24。盘点/CLI/迁入由主代理实现，login hook由executor gpt-5.6-sol / medium实现，scout gpt-5.6-luna / medium只读复核。

盘点先行4个行为断言全部失败；实现和schema上下文修正后4项通过。后续补CLI及数据库旁文件：WAL/SHM/sqlite的4个先行用例实际失败，修复后整个inventory **9 passed in 0.42s**。来源root和包内链接、运行数据、敏感字段/已知秘密均排除；秘密出现在完整技能任一文件时整个候选包不复制。所有输出0700/0600，脚本执行位只存清单供审阅后恢复。

迁入初次端到端 **3 passed in 5.34s**：合成旧source→私人三类提案→测试替代人工审阅仅批准技能→公共声明→独立合成完整锁/sync→新身份apply；技能正文和脚本执行位保留，认证和会话未复制，旧源字节/权限/mtime/链接哨兵不变。完整fixture另走synthetic sync/apply/noop/run/capture，退出27及三层租约匹配；非空异主目标不能因inventory而接管。后续补双配方和迁入pending哨兵，由最终组合回归计数。

合成资产有自己的SHA及可信来源常量替身，始终经过真实read_lock/receipt/目录/正文校验；没有让假字节匹配正式发布SHA，也没有覆盖正式锁。

login只接受显式`login openai-codex`，使用独立HOME、中性cwd和相同已部署门控，不加会话参数。runtime自动按操作移除无关SecretRef，测试不依赖调用者手工传过滤器。真实登录、旧账号可用性未执行；不存在账号/会话迁移。
