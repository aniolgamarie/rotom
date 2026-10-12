# Modern npm 固定解析输入

2026-10-07，执行03仍在原license-bundle门失败；清理前捕获的真实图与固定清单各146行、same路径/顺序，其中五行发生版本/URL/SRI漂移。既有顶层精确版本未固定间接依赖。当前方向是在自有构建适配代码使用npm公开package-lock输入，保留原许可证和完整图校验；不修改上游、缓存源码、包正文或安装行为。

## 已有材料和边界

已找到此前实际完整raw锁：`.cache/pi-two-profiles/run-20261004/retained-temporary/pi-base-candidate-4lbc4mv4/package/package-lock.json`，72820B，SHA256 `7a6ad8e47f7b165d2c35b218a72e7734cf74a8ee26044d20e993419ba9c5bee1`，精确匹配SUPPLEMENT/TRANSITIVE来源记录的base lock hash。其146行九身份与当前REGISTRY相同；八直接依赖和四本地包完整记录与执行03相同，根项目名为历史`agentcfg-pi-base-candidate`。取证只读取一个raw候选，1824项文件名索引不当1824个正文读取；其它fixtures、账号、JS或vendor树未读取。

Root准备把原raw作为明确来源，只规范化顶层name和packages空路径的name为`agentcfg-pi-base`，保存成新自有`agents/pi/build/resolutions/pi-base.package-lock.json`。两处字符串以外的完整原字节可逆；不得刷新五版本、包元数据、URI/SRI、本地依赖/peer、optional/平台字段或许可证行。新sha必须由实际新文件计算，不能从计划推定。

npm公开文档说明，当locked版本满足package.json范围时，install使用锁中版本。当前v11文档显示11.21.0，本工作仍固定实际11.19.1；文档不能代替该工具的运行验证。见[npm install](https://docs.npmjs.com/cli/v11/commands/npm-install/)及[package-lock格式](https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json/)。

## 最小接口和不变量

仅modern输入profile可选`npm_resolution_seed`，其对象精确两键`source`和`sha256`。source固定为`agents/pi/build/resolutions/<profile>.package-lock.json`，profile经过原layout/safe_id校验；sha256为小写hex64。Legacy不接受该字段，modern无字段保持原fresh resolver路径。未知字段/类型和不安全路径失败，不能fallback、跳过或自动修复。完整源码recipe_digest已覆盖build目录和声明/自有模块，新输入因此进入现有源摘要，不增加public权限或owner字段。

新自有`src/agentcfg/pi_npm_seed.py`只负责引用/文件/数据校验及漂移比较。由pi_vendor的构建输入read_inputs/resolve seed路径按需导入，不能成为module-scope/runtime启动或read_lock依赖；原完成pair、schema、license source、recipe和candidate/readback门保持，published manifest schema不增字段。它不是安装/current/sourcehold或Full资格证明。

在创建TemporaryDirectory、node/npm版本检查或其它checked调用之前，完成seed读取和当前生成package/本地归档的匹配。通过现有Tree以16MiB正文上限读取引用，摘要必须匹配，duplicate-key-safe解析，不随异常输出正文。只允许本包固定npm v3顶层字段`name/version/lockfileVersion/requires/packages`，值类型严格；requires为true，根和空路径项目的name/version匹配生成package，空路径精确字段`name/version/dependencies`。dependencies必须与本轮实际selected来源生成结果完全一致，不借ranges或其它profile挽救不匹配。所有package路径/远程URI/SRI/optional/os/cpu/libc先用原公开pure projection检查，拒绝link记录；所有file:节点必须恰好对应所选local/git的顶层node_modules路径，version/resolved精确匹配，sha512 SRI必须等于本轮实际archives字节；不接受额外file/link/workspace/absolute输入。源文件不存在、链接/摘要/形状/依赖/本地归档不匹配统一固定ConfigError `pi-build-resolution-seed-invalid`（退出码2），不含正文、秘密值或任意路径值；固定错误的cause/context也不能携带原输入，遵循原pure validator的清理模式。

原selected/dependencies/package生成逻辑需保持单一真实来源：seed分支在preflight产生本轮package数据并原样复用；未seeded及legacy的原时序和分支保持，不为此整体重构resolver。seed预检后只写该profile的原package.json和原seed字节到stage/package-lock.json，再执行完全相同npm lock-only命令与原missing-SRI补齐路径。工具依然真实运行，不拿旧图直接冒充新的candidate。

在npm结果读回及原SRI补齐后、modern摘要pair与输出写入之前，用原pure projection逐行比较seed与结果的九身份。路径、数量、顺序、版本、URL、SRI、optional和平台字段均相等；变化固定ConfigError `pi-build-resolution-seed-drift`（退出码2）。不重试、更新输入或自动采用新版本。随后走原完整验证与publish/read_lock；原proxy MIT unresolved、正式锁/安装门、所有产品gate和AUTO OFF不变。

更新本地代码导致归档身份变化、直接依赖/提供者替换、或有意升级间接依赖，都需要明确生成并审查新的完整seed及相关license材料，更新声明sha，再重新候选解析。当前scope不新增CLI命令，不提供自动重写seed；未准备的新输入会给固定失败。保留旧锁/candidate及活动/恢复引用，不能覆盖用户状态或切default。

## 实施和默认验收包

唯一executor可写五文件：`src/agentcfg/pi_vendor.py`、新`src/agentcfg/pi_npm_seed.py`、`agents/pi/dependencies-modern.json`、新`agents/pi/build/resolutions/pi-base.package-lock.json`、新`tests/test_pi_npm_seed.py`。旧tests/locks/schema/license/upstream/current/default不写；root拥有本计划/任务/state；scout只读独立审查。新增helper限producer导入；若新证据证明runtime实际需要它、需改旧fixture或扩大文件范围，先交root决定。子代理不再派生。

先默认red再实现/green；使用原conftest的临时HOME/XDG/OS账号、网络阻断、fake checked和/tmp basetemp。新tests必须验证：原raw只两name可逆/146身份相同；真实声明引用与四个纯build_archive匹配；schema/reference/摘要/duplicate/路径/link/根/direct/local URI/SRI失败发生在任何checked和锁写入之前；真实stage中seed确实先写、原npm命令被调用及输出保留candidate；path/name/version/URL/SRI/optional/平台漂移在发布前拒绝且旧manifest保持；modern无seed和legacy拒绝新字段/原路径保持；输出原schema/readback/candidate拒绝安装不绕门。使用现有generator_fixture构造合成seed/default结果，不能启动SDK/Node/npm、模拟已通过真实解析或更改原validator。

已选旧affected selectors仅运行一次，必要失败节点修后重跑：`tests/test_pi_lock_families.py`、`tests/test_pi_base_recipe.py::test_unverified_candidate_round_trips_through_generator_schema_and_reader`、`tests/test_pi_base_recipe.py::test_real_base_inputs_select_only_explicit_base_sources_and_runtime_ui`、`tests/test_pi_vendor.py::test_missing_source_is_explicitly_not_ready_before_any_download`、`tests/test_pi_vendor.py::test_lock_fills_missing_shrinkwrap_integrity_from_exact_metadata_and_reuses_it`、`tests/test_pi_dependencies.py::test_explicit_lock_generates_independent_complete_pairs_with_fake_resolver`。精确collection和XML节点/pass/fail/skip、actualargv/UID/退出与首末pins均保留；范围不因准备失败扩成全量。

实现完成STOP后root审稳定diff、旧路径和关键约束；scout独立限定review。再重新收集/冻结变更后的完整source-domain并准备相同隔离开发执行器，仅root冻结新材料后授权固定npm11.19.1实际解析，检验146身份保持和原candidate/readback。本计划本身尚不授予source写入或actual工具执行；独立review后root具体授权。真实SDK/agent/安装、Full source/controller/解释器/持有/账号组合另判，既有native授权闭合不能复用。

2026-10-07独立设计review P1为0；三项P2标注是已明确的modern-only、补齐SRI后的九身份比较及default/actual证据分离实施条件，不是已发现矛盾。root接受这些条件，并进一步明确helper可在构建输入read_inputs按需校验引用，仍无runtime/module-scope/read_lock导入。原generator_fixture已由root有限读取，使用自有合成单host声明而无seed，故旧无seed路径验收有效；不把它当实际146图证据。授权只能以随后的root冻结receipt和任务包为准。

2026-10-07 root已准备自有canonical候选输入，72800B、SHA256 c71c94ea66fc43eb8f978be2ff6094a94c58c0c528019c8d585f931d11b1b85d，仅两处root name改变且完整原字节逆回相同；原raw未写。五文件默认实施范围已冻结receipt 56545c5a16cf2254420df3d6508f7377155860b0311762ec42255df76f5b4169，此后允许executor实施和上述默认checks；实际npm/agent/native/正式锁仍未授权给子代理。

2026-10-08（本地）默认五文件已STOP后接受，root稳定receipt 8b523b5b11378c261e39035f81b9a2689b6386959b3b98a35cb53b8e5f79a3f3。helper全文/原vendor差量/新tests原版和最终delta/actual XML已核，独立阶段及最终有限review未发现P1/P2。red正控1fail→green39pass/7.53s，补强2修改4新增同次6pass/1.44s；当前collect43跨轮覆盖，旧25六批全pass，不称一次43/68pass。声明仅新ref、canonical002全bytes相同，原raw两name逆保留一次审计；永久tests按actual selected/REGISTRY计数，无历史cache或固定四/146依赖。scaled读取上界不是16MiB压力。仅默认组件完成，下一步运行OUT-only新source collector并冻结完整变化后的源码；此后root另授同边界固定npm解析。尚无actual解析/native/正式锁或product资格。

2026-10-08（本地）execution04已执行并在writer STOP后接受：root终态23输入receipt `1ff8237326fd22a761ec3dd039cef98c968b909d9aa7554d5d77cd36e485cb34`。新源码2204files/231dirs/48,522,706B由receipt `8a9dda163f0e304835cea52aed3e00dddcb7b3a6dae51f30ea864513de9a35de`固定；只对原executor替换五个材料常量，producer原字节不变。一次实际2026-10-07T16:14:44.635092Z至16:14:54.181700Z、9.546608s、UID/EUID1002/GID100、inner/wrapper0；原PiBackend.resolve_lock及read_lock返回schema2/pi-base/candidate identity `72ac0c2968ae7e1ed9ed344030defb6036f4b39c0a9593ea4949494d41a5be44`。捕获与保留pair相同，package718B/840f67ca…、lock72800B/c71c94ea…与固定seed全bytes相同；146行九字段有序与REGISTRY全同。root独立核全部29工件pins、2210复制项、35自有模块路径、manifest/piece/pair摘要、进程empty与临时根absent，未重跑resolver、validator、pytest。原checked未提供版本literal stdout，Python审计不覆盖Node内部spawn；source pins不当atomic snapshot或持续hold。正式manifest仍absent，许可安装门及Full/来源/角色/产品未通过，AUTO OFF；01–03历史失败不覆盖。此前“尚无actual解析”仅为当时阶段事实。
