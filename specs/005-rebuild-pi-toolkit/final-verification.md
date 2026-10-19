# 稳定候选最终验证

前述检查按时间保留；当前稳定候选见文末“用户决定后的当前交付检查”，旧检查点不代表后续源码摘要。

日期2026-10-19；分支design/pi-toolkit-reboot。
HEAD `8ac50aaa8168b8a377c59736eaa1aebeb83a48c6`、目标main `93e4f7899725336c1180e53b4ec239eea5f984ce`均未移动。
未提交候选最终公开管理源码/测试输入SHA256为
`7ce2ea686ff9999c208d9eafc9df46330d4fd7039dcfc62e699f1b7590b6266e`，514文件，同acceptance记录的算法/范围。
报告/任务状态更新不进入这个摘要；将来提交/合入须重新绑定已准备commit。

Pi锁`522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7`，
OMP锁`7afccd2beff673e94eb5e2fdc276f0488e2b70d0a8a424d4b795660aaee694af`，
DSH锁`f9da5fd8538eeee6d3526ac5cb160095f0c3d1ff36e3bde072f04441ce208d15`。
环境为Linux x86_64、CPython3.11.11/pytest9.1.1；所有pytest保留临时HOME/XDG、阻网、假进程与虚构模型。
外层执行只用于可信系统目录属主；没有放宽生产路径/权限检查或启动第三方宿主。

## T093第一组：首轮完整受影响集合

真实argv（工作目录为reboot工作树；相对解释器来自主仓库已准备环境）：

```sh
../../../.venv/bin/python -B -m pytest tests/test_config_schema.py tests/test_config_resolution.py tests/test_config_policy.py tests/test_config_examples.py tests/test_config_secret_loading.py tests/test_deployment.py tests/test_runtime_preparation_recovery.py tests/test_dependencies.py tests/test_omp_dependencies.py tests/test_omp_dependencies_foundation.py tests/test_omp_runtime_foundation.py tests/test_omp_secret_boundaries.py tests/test_omp_capture.py tests/test_runtime.py tests/test_dependency_backend_contract.py tests/test_instance_admission.py tests/test_lifecycle_leases.py tests/test_run_owner_integration.py tests/test_runtime_toolchains.py tests/test_readiness_evidence.py tests/test_isolation.py tests/test_cli.py tests/test_presentation.py tests/test_cli_presentation.py tests/test_model_defaults.py tests/test_pi_retirement.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_dependencies.py tests/test_pi_reboot_runtime.py tests/test_pi_reboot_pipeline.py tests/test_pi_inventory.py tests/test_pi_migration_flow.py tests/test_pi_capture.py tests/test_pi_core_contracts.py tests/test_pi_recovery.py tests/test_pi_test_boundaries.py tests/test_pi_status_admission.py tests/test_pi_collaboration_admission.py tests/test_pi_collaboration_contract.py tests/test_pi_optional_modules.py -q --tb=short -x
```

结果exit1，490 passed/1 failed，446.85s。失败在OMP秘密测试的full_workspace夹具初始化：
缺Pi schema导致全catalog拒绝。仅补两行测试来源复制；生产源码/锁没有变化。
已通过前段不消费该fixture，证据保留适用于最终候选；不是将失败整体命令改写为exit0。

## T093第二组：全部受影响fixture消费者

```sh
../../../.venv/bin/python -B -m pytest tests/test_omp_secret_boundaries.py tests/test_omp_capture.py tests/test_omp_pipeline.py tests/test_omp_migration_flow.py tests/test_omp_kernel.py tests/test_omp_permission_runtime.py -q --tb=short -x
```

结果exit0，96 passed，140.97s。原失败单例另已先红再绿，1 passed/6.08s。
全测试静态扫描确认直接/间接消费者均覆盖；唯一fixture变更SHA256为
`44a3eb3a94a696fa7b14bcfbc83194b481e4302387ba51fbf8b647f9ba6ea6f4`。

## T093第三组：首轮尚未执行的公共和Pi部分

```sh
../../../.venv/bin/python -B -m pytest tests/test_runtime.py tests/test_dependency_backend_contract.py tests/test_instance_admission.py tests/test_lifecycle_leases.py tests/test_run_owner_integration.py tests/test_runtime_toolchains.py tests/test_readiness_evidence.py tests/test_isolation.py tests/test_cli.py tests/test_presentation.py tests/test_cli_presentation.py tests/test_model_defaults.py tests/test_pi_retirement.py tests/test_pi_reboot_configuration.py tests/test_pi_reboot_dependencies.py tests/test_pi_reboot_runtime.py tests/test_pi_reboot_pipeline.py tests/test_pi_inventory.py tests/test_pi_migration_flow.py tests/test_pi_capture.py tests/test_pi_core_contracts.py tests/test_pi_recovery.py tests/test_pi_test_boundaries.py tests/test_pi_status_admission.py tests/test_pi_collaboration_admission.py tests/test_pi_collaboration_contract.py tests/test_pi_optional_modules.py -q --tb=short -x
```

结果exit0，578 passed，224.66s。三个通过范围共1164例，不将早期重叠回归重复加入总数；
这是按影响范围选择的最终验证，不声称整个仓库所有测试或CI已运行。

## 稳定差异、来源与未运行范围

主代理审阅公共锁/FD继承、独立run owner、原生CLI/配置/资源发现、秘密、锁发布与暂存激活的稳定差异；
scout独立读取新Pi锁/脚本/许可到激活链，没有发现可复核绕过，并提出已补验的伪造PiLock拒绝边界。
唯一最终修复是测试schema复制，最终已审差异与消费者重验一致。来源/法律材料/当前公开扫描见acceptance T091。

旧91模块/26脚本/102专属测试及明确资源清单退出，旧静态与literal动态消费者0，原生用户状态未动。
八临时设计材料退出、160来源承接、十历史指南明确原范围；正式入口/Quickstart/支持矩阵匹配当前CLI与限制。

没有新commit/作者/提交者/身份配置/分支移动/远端更新；没有将旧谱系合入main。
未获提交授权，不读取/沿用全局身份，不执行提交前身份配置，也不移除仅供提交前处理的宪章Sync Impact Report。
用户先前宪章/设计编辑已在来源承接中保留其有效内容，不丢弃其他工作树内容。

原生宿主/TUI、真实服务、账号和模型均not_run，原因是缺独立授权；macOS/其他架构未宣称支持。
Powerline与Pro继续held；T075选中外部模块接入未开放；没有生产完整后代释放observer，unknown继续阻断维护。
没有选中US6外部交付模块，不作性能主张。以上使T096与相关交付任务保持开放，完整feature未完成、不归档。

after_implement：项目没有.specify/extensions.yml，无需派发后置hook。

## 继续实施中间检查点（浏览器/Cursor之前）

分支仍design/pi-toolkit-reboot，HEAD8ac50aaa8168b8a377c59736eaa1aebeb83a48c6，
目标main93e4f7899725336c1180e53b4ec239eea5f984ce，均未移动；候选仍含未提交实现。
该检查点源输入摘要`f1de277c8c2bcf06d02177b1f993269473cc623ecedee21814c8a25eaf258c42`，524文件，
范围src/agents/shared/schemas/profiles/locks/tests、pyproject.toml、uv.lock、当前workflow；
算法为相对路径、mode、正文SHA256排序数组的compact JSON SHA256，排除node_modules/pycache。
原生/账号/真实服务/托管CI仍未执行；本摘要不升级这些证据层级。

写入结束后的专项实际结果：

- 公共部署/引用保护、可选Pi、OMP秘密、锁发布5文件160 passed/exit0/88.77s，
  包含pending恢复前拒绝所有原生literal凭据及跨代空容器来源。此前ENOSPC失败明确保留。
- 状态栏/后代3文件30 passed/exit0/15.34s；自有observer Node 5/5、exit0。
- DSH/OMP/Pi完整公共消费者7文件97 passed/exit0/172.09s，无新代码变更。
- 先前增量UI全8文件267 passed，US6全6文件254 passed，Linux归属/部署等118 passed；
  确切argv见acceptance。上述范围重叠，不累计为唯一用例总数或全仓库通过。
- 两个真实npm组合均显式lock/sync/apply，120/245包，ignore-scripts和重复apply均通过，
  host/service/model为0次。来源摘要6cae2868…b24a对应这些准备时的288文件范围；
  后续公共recover预检变更由上述160/97项覆盖，未假称准备命令使用了未来代码。
- 当前默认Pi完整锁仍522bed3a9815e84ad88235956fa0da8bd21625d59c9126af262659a0288396e7；
  新的未选模块不使默认slice失效，临时所选组合锁未导入默认仓库。

稳定差异重点：只有本次内核完整覆盖能释放active owner，旧unknown/其他run不能借新proof清除；
所有参考叶子在pending/rollback写任何文件前统一预检；created_parents只剪自建空祖先；
community包/官方宿主未修改；MCP launcher仅环境清理exec；footer只有社区布局所有者，
自有observer无进程、网络、持久状态或私有宿主成员访问。独立scout指出的pending顺序缺口已修订，
对应两条多文件回归现包含于160项通过。

公开文档检查PASS/findings0，git diff --check exit0；feature及Pi正式页本地Markdown链接缺失0。
源输入审计脚本最后一步首次因未设PYTHONPATH导入agentcfg失败exit1，已加PYTHONPATH=src
重做默认锁读取exit0；之前生成的524文件SHA256不受该导入失败影响，未把失败命令整体记为通过。
checklists/requirements.md只读16/16；.specify/extensions.yml不存在，无after_implement hook可执行。
没有提交/合并/推送、读取真实auth/session、发送上游issue或删除未知owner。

当时73/96。A/B/C无账号原生授权问题待明确答复；未因默认选项或等待而执行。
Pro私有接口阻断、候选浏览器/Cursor等的准入与未实现接线、所选服务/性能/账号证据
仍分别开放，不宣称完整feature完成。

## 浏览器/Cursor与方法资源完成后的稳定检查（原生授权前历史）

当前任务80/96，开放16项均为原生/账号/已选模块性能或Pro上游准入及依赖交付门，
详见tasks和implementation-status。生产/测试写入结束后，544个输入文件SHA256为
`6c16bd33b3c1fb417b36e8054750b20f339b0615923cc0dc1568475de4cf5e9c`。
范围为src/agents/shared/schemas/profiles/locks/tests、pyproject.toml、uv.lock和当前workflow，
排除node_modules/pycache；相对路径、mode、正文SHA256排序数组的compact JSON再取SHA256。
报告/任务结果更新不进入该摘要。HEAD、目标main和默认Pi锁仍为前述身份，无提交/分支移动。

写入结束后的实际证据：

- 12文件定向396 passed/exit0/184.49s，覆盖Browser/Cursor/固定可选模块/状态/锁/配置完整入口；
  collection之后仅测试增加的六路取消6 passed/exit0/11.35s，逐模块unknown与EX维护拒绝。
- DSH/OMP入口和方法资源3文件20 passed/exit0/53.65s；自有observer再次本地5/5、exit0。
  完整实际argv与重叠限制见acceptance，不汇总为唯一测试总数或全仓库通过。
- 私有全可选组合250包、23条固定manifest生命周期审计，真实lock/validate/sync/apply/doctor/重复apply
  全exit0，ignore-scripts；loading/runtime not_run，重复apply 0变化。源码305文件摘要
  `086ad4b0d9a956d2c3f20cb502770ffaf18f09c5466e995782a31f07c945f183`
  与当时src/agents/shared/schemas/profiles现场复核一致，npm准备没有使用旧源码冒充新候选。
  所选临时锁b606b1c0…94d6、recipe94adc9b6…2d4与精确闭包见acceptance，没有替换默认锁。
- 新增模块不改变未选slice；完整上游Skill/支持文件/许可保留，未修改社区包/宿主/vendor。
  Cursor只准本实例Pi OAuth，拒绝其他owner和route，固定关闭系统凭据、清除继承token/route；
  浏览器只用私有会话，自动config存在即拒绝，缺二进制不安装；主会话Bash不被称为OS沙箱。
- 公共文档检查PASS/findings0、diffcheck exit0，checklist只读16/16；项目无extensions.yml，
  没有before/after_implement hook。首次误用系统旧Python的文档检查exit1、直接导入缺PYTHONPATH
  的来源复核exit1均已更正为项目3.11/显式PYTHONPATH并通过，没有改生产保护掩盖环境错误。

本轮没有真实宿主/浏览器/服务/账号/模型调用，没有发送上游消息、清理用户状态或修改Git身份。
原生授权仍待明确答复；Pro仍有无法由公开参数避开的非公开宿主成员访问。
T037/T038、T058/T059、T064–T071、T085–T087、T096保持开放，完整feature未完成。

scout对稳定新增Browser/Cursor/方法文件进行了独立静态终审，无critical/high发现；核对默认两档
只有host/theme、未选module/audit不入默认身份、完整上游Skill/10指南/LICENSE原字节一致、
Cursor严格OAuth owner与继承环境过滤、浏览器私有/参数/config边界。有限隐私扫描只命中保留域名
示例、说明路径和合成归档名误报，未发现本轮新增真实凭据或私人工作区绝对路径；不证明旧历史已清理。
报告保存在私人临时证据，该历史检查点的公开文档与本地链接检查缺失0。
旧记录的文档总数不作当前范围依据；当前固定清单为39份/189个本地链接，见文末复核。

## A/B/C原生修订后的稳定检查

用户对具体A/B/C无账号原生范围答复“授权”，随后要求继续；该范围已执行结束，
实际步骤、各组合完整锁及限制见[native-acceptance](native-acceptance.md)。
HEAD、目标main和默认Pi锁仍为前述身份，候选未提交，任务80/96，不把部分原生结果勾成完整交付。
当前544文件输入SHA256为
`e35c65143baf7605773f618bb20fbb5a4c7c0423c5443280188b6d75aa925da5`，
范围/排序/mode/正文SHA256及compact JSON算法沿用前节；只有报告更新不改变该摘要。
当前305个生产输入摘要为
`39fa875a0cd6edc63f035515d8933032134afe2b92cdd6f0af24b76c20d70c1b`。

本轮生产修订只涉及自有status-observer.mjs；测试在pi_status_observer.test.mjs中。
紧凑标签仅去显示前缀，详细身份完整保留；ui_prompt_end仅凭公开isIdle()确认恢复queued/idle，
不借turn_end、时间或缺事件推断空闲。没有新timer、进程、IO或私有宿主接口。

写入后实际验证：

- `node tests/pi_status_observer.test.mjs`：最终7 tests/7 pass、exit0，Node24.14.0；
  两条新行为先红后绿，未导入第三方宿主。托管CI未运行。
- `../../../.venv/bin/python -B -m pytest tests/test_pi_status_contract.py tests/test_pi_status_admission.py -q --tb=short`：
  13 passed、exit0、11.30s；外层执行仍保留临时HOME/XDG、阻网、假进程。
- 修订B明确lock/sync/apply全部exit0、ignore-scripts；footer偏好SHA逐字节保持，
  最终锁e67e22a8…3ec6，三宽度、菜单、reload、完整身份和未知统计实际复验通过。
  先前250包组合来源086ad4b0…不是修订后B来源；默认锁不选择observer，仍有效且未替换。
- 全部A/B/C共13次官方CLI运行均exit0，原始B两项语义失败已另记并修订；
  最终A6/B4/C3均idle_confirmed/complete。真实双主维护4/4/0，三组末次apply各0。
- 27次Node入口新网络namespace、lo-only、IPv4路由0；无登录/模型请求。
  私有tmux所有窗格退出0后关闭server；裸PTY退出0并恢复终端模式，不清理未知owner。

scout核对固定Pi1.3.0公开类型、observer稳定增量、namespace/owner/界面记录，无critical/high发现。
审阅不声称覆盖全分支历史或第三方全部能力；主代理核对最终源摘要、锁及文档一致性。
汇总脚本先误把stale socket存在当server存活，改为外层连接核查后ECONNREFUSED、exit0，
未删socket伪造清理，不将沙箱EPERM记成通过。

SSH/macOS缺环境；真实账号/模型、D–G、实际usage/cache/费用、性能与会话继续/分支/压缩not_run。
窄屏第二行仍会截短，T059完整信息对齐/差异接受开放；Pro非公开接口阻断不变。
没有扩大A/B/C授权、发送上游消息、修改Git身份、提交/合并/推送或删除用户数据。

最后只读复核：544/305文件摘要与默认锁读取全部exit0；任务checkbox为80/96，开放16项身份不变。
项目Python执行scripts/check-public-docs.py为PASS/findings0，git diff --check exit0；
本次额外检查feature/Pi正式页及两种方法资源共39份Markdown、189个本地链接，缺失/空白/私人路径问题0。
checklists/requirements.md只读16/16；.specify/extensions.yml不存在，无after_implement hook可执行。

## 共享模型与可选模块修订后的稳定检查

候选基点8ac50aaa…9c6、目标main93e4f789…84ce及默认Pi锁522bed3a…396e7均未移动。
当前544个生产/测试输入SHA256为
`20e57fb8410d61c53a021f176cdd0866bf787118035669024a0ff8d981d58742`；
305个生产输入SHA256为`44be2fa6fb13714ad2cf54a7e1e704fdb35fe988f728a3fcaab124f63cf635e4`。
范围为src/agents/shared/schemas/profiles/locks/tests、pyproject.toml、uv.lock和tests workflow，
排除node_modules/pycache/pyc，按相对路径/mode/正文SHA256排序compact JSON再取SHA256。
文档报告不在摘要内，旧e35c6514…与39fa875a…不代表本轮生产修订。

写入结束后的相关实际回归一次通过：

```sh
../../../.venv/bin/python -B -m pytest tests/test_pi_reboot_runtime.py tests/test_pi_reboot_dependencies.py tests/test_lock_publication.py tests/test_pi_reboot_pipeline.py tests/test_pi_browser_module.py tests/test_pi_optional_modules.py tests/test_pi_mcp_reference_guard.py tests/test_pi_core_contracts.py -q --tb=short -x
node tests/pi_status_observer.test.mjs
```

八文件324 passed、exit0、101.73s；Node自有观察器7/7、exit0。执行者未改源码；所有默认测试
仍隔离临时HOME/XDG、阻网、假进程，不启动第三方宿主或读取凭据。此前依赖155/runtime64/
browser39为重叠定向证据，不相加成新唯一总数；没有无新证据反复全仓库测试。

本轮生产差异限于：官方--no-tools透传、Pi1.3带ID的--fork及实例内会话边界；浏览器open
固定公开Chromium选项；精确包名/版本限定源审计映射到真实锁路径。旧三字段审计逐路径保留，
限定成对/未知字段/冲突失败，实际manifest正文与lifecycle检查未改，默认两档锁仍可严格读取。
没有修改宿主、社区插件、vendor、缓存源码或官方二进制。未新增调度器、任务库或执行平台。

真实验收与回归分开。用户要求共享默认模型可用于新实例、密钥不能进入模型；真实请求均
--no-tools，正常启动解析SecretRef，准备程序不读/复制正文，不导入其他工具账号/旧会话。
首次/继续/分支/模型切换/压缩、B/C真实input/output、Context7连接及独立查询、固定Chromium
合成DOM操作与退出、Brave/Cursor无账号加载的限定证据见[补充验收](remaining-native-acceptance.md)。
旧fork参数、提升路径审计、缺Chrome与file URL拒绝均保留失败记录，已修订项对应复验通过；
未解决的真实账号/模型工具/性能范围不通过。18次CLI样本不作更快或省token主张。

scout对本轮稳定生产差异的有限审阅无可核实阻断；随后独立核对新记录的305文件来源、
各临时锁、运行退出码、用量/owner、服务与性能元数据，未发现可复核差异或过度声明。
所有核对只取允许的公开文件和私人元数据，未将raw终端、认证、密钥或会话正文送入模型。
这是本轮增量审查，不代表全分支历史、托管CI、其它平台或服务账单通过。

用户明确选择继续只用社区插件、Pro等待上游。T064–T071保持等待，不实施SDK替代、自有调查
执行插件或降低原约束；精确后台/resume旁路见[候选复核](pro-candidate-refresh.md)。
T038/T059/T085–T087/T096以及SSH/其它平台完整门仍开放，任务80/96，完整feature未完成。
没有提交、合并、推送、归档、发送上游消息、变更Git身份或清理未知owner。

后置hook只读复核：requirements checklist 16/16、未改marker；.specify/extensions.yml不存在，
没有after_implement hook可派发。公开文档、链接和差异检查在最终报告写入结束后再核。

回环SSH及统计补充结束：A/B/C各90列中文交互/reload/CtrlD的client及manager均0，
sshd非root inetd各255及PAM/login-record限制如实保留，不外推真实远端或SSH三宽度。
A实际来源086ad4b0…f183，B/C为44be2fa6…，各锁见补充记录，不将A追认为未来源码。
B另以零新增请求续开/打开分支，两次0，reload前后input1395/output12稳定、不重复计数。
全部工作结束后再次只读核对A13/B14/C11/D2/E1/F4/G3/R6，共54个owner均完整空闲，
无active/unknown；所有SSH client/listener/sshd/manager均已结束，端口拒绝连接。
scout独立核对SSH安全摘要的来源/锁、client/manager/server退出码、owner及范围，无事实矛盾；
未读任何key、认证、会话或raw SSH/TTY。回环和单样本统计是补充范围，不关闭完整任务。

最终文档写入后的只读复核：公开checker PASS/findings0，544公开输入加feature/公开文档的
本机路径检查PASS/findings0；feature全Markdown与四份Pi正式入口共29份、161个本地链接
全部有效，git diff --check exit0。该29份范围与历史39份/189链接不同，不混用计数。
544文件摘要再次逐条重算与冻结20e57fb8…完全一致，HEAD/main及默认锁未移动。
任务仍80/96；checklist只读16/16，after_implement配置不存在；无新代码或原生执行待收尾。

## 用户决定后的当前交付检查

候选HEAD和目标main未移动，默认Pi锁522bed3a…不变。当前544个生产/测试输入SHA256为
`ef4c0fbe77f7d5893f362a49f3234f4a6f954b118942aabb4902f7823727adee`，
305个生产输入为`f1c83e6a2dc4a16b32c82de832df75a791d7f9beab5f8ea461560d581a934dad`。
路径集合/算法沿用前节，文档报告不在该摘要内；旧20e57fb8…/44be2fa6…仅表示前一检查点。

本轮初段生产变更：状态详情新增中文说明“宿主未提供可查询的权限状态；此项不代表权限保护。”
后续组合测试另发现并修复公共部署的动态共享文件来源缺口，见下段；社区包、宿主、vendor和缓存源码未改。用户明确接受该说明、分支输出
均速和窄屏详情三处差异；接受记录写入spec的Clarifications，不修改FR成功条件或清单marker。

写入后的受影响验证：

```sh
node tests/pi_status_observer.test.mjs
../../../.venv/bin/python -B -m pytest tests/test_pi_status_contract.py tests/test_pi_status_admission.py -q --tb=short -x
```

Node7/7、exit0（33.49ms）；Python13 passed、exit0（9.15s），仍使用临时HOME/XDG/阻网/
假宿主。无新增行为或失败证据，不重复全量324/1164例；旧结果保留对应身份，不充作新文本的运行结果。
新B显式重锁与部署后真实界面布尔确认中文说明存在，所有维护exit0、偏好字节未改、依赖闭包未变。

[本轮交付验收](current-delivery-acceptance.md)记录真实工具五调用、原生中断/恢复/压缩统计、
正缓存、服务失败、性能及组合验收的实际范围。工具首拒没有执行；用户明确补充授权后仅一次
有界任务完成，验证保护器不改变生产权限。R owner9→10完整空闲，未泄露真实密钥正文。
本轮一次辅助元数据脚本误用系统python而ImportError，未进入宿主或读取秘密；改用既有venv后
投影成功，不改变生产环境/校验。任何后续原生环境/审批不足按实际状态保留。

该阶段T037/T038/T058/T059已完成，四模块组合/禁用恢复与fresh测量当时仍在执行；
最终计数、稳定文档审阅和后置检查已在文末记录。Pro T064–T071、T096保持开放，
Brave/Cursor真实账号按用户决定延后。未提交、合并、推送、发布或改Git身份。

组合验收暴露MCP禁用重选的真实apply4。公共apply在成功计划后积累实际管理过的字段文件路径，
与owner/current同事务提交；无变化补录不轮换备份，不预认领从未管理文件，不覆盖现存字段。
详情见[本轮交付验收](current-delivery-acceptance.md)。这是共同部署语义的窄修复，不是Pi私有接管。
新增五个参数化公共case及一个Pi组合case；首轮定向3 failed/2 passed，其中一个复现断言误以为
首次退役就立即清除ABSENT项，改为正常重复apply完成记录退役；其余失败直接暴露来源补录缺失。
修订后test_deployment.py 31 passed/exit0/1.08s；七文件跨公共事务/DSH/OMP/Pi回归171 passed、exit0、107.08s。
只读终审建议再精确覆盖历史owner下的现存字段拒绝，补一次空apply并断言旧item完全退役；
仅该测试文件随后最终31 passed、exit0、0.93s。无新的生产修改，不重跑无关全量。
原生F先保留冲突状态和备份，不删除原生mcp.json或手改所有权；通过正常rollback恢复后重验。

中性来源修复的跨工具实际argv：

```sh
../../../.venv/bin/python -B -m pytest tests/test_deployment.py tests/test_runtime_preparation_recovery.py tests/test_runtime.py tests/test_omp_runtime_foundation.py tests/test_pi_optional_modules.py tests/test_pi_mcp_reference_guard.py tests/test_pi_status_contract.py -q --tb=short -x
../../../.venv/bin/python -B -m pytest tests/test_deployment.py -q --tb=short -x
```

最终公共精度用例不影响生产源码。独立只读explorer核对成功计划后累积、首次拒绝、事务/无变更
补录、回滚和保护边界，无critical/high遗漏；仅精度建议已处理。已存在字段被拒绝的逻辑保留。
此前13状态项和Node7项对应观察器未变，不与171/31重叠相加为唯一测试总数。

按speckit-analyze再次只读分析：先发现plan摘要仍称状态栏信息门未完成这一MEDIUM矛盾，
修正为Powerline held、pi-footer交付/三处接受及US6/Pro独立门。第二轮0发现；34FR/10SC
共44/44有任务、未映射要求0、未映射任务0（T094对应宪章VII/VIII），未解决歧义/重复/宪章
冲突均0。该时点任务84/96；后续仅验收checkbox/状态收口，不改变任务语义。
分析前置检查每轮仅一次，扩展配置不存在，不运行分析hooks；分析自身不写文件，修订由主代理
依用户既有“发现问题再修订”授权完成。未读秘密或真实会话。

## 所有写入与运行结束后的交付结论

最终所选模块六场景、F正常rollback/零正文变化补录/禁用重选与原配置恢复通过；匹配fresh
四场也全部0，来源f1c…，Base锁522…、实际组合锁14f845…，原模板标签误留30d5…由三方
锁/部署/收据证据透明修正，不改写原始日志。各新fixture已持锁回收可再生依赖，重用须sync。
主代理只读汇总全部12个实例，84条owner complete/idle，active/unknown0，未读auth/key/session正文。

任务87/96，开放仅T064–T071、T096；Brave/Cursor真实账号按用户明确决定延后，不声称全feature
或Pro完成。T085–T087当前四模块门均完成，不用性能门误判SC-007六场景。独立证据复核无
critical/high；发现一处旧段与当前SC-007矩阵表述混用的MEDIUM，已标明历史并修正当前矩阵。
最终公开/链接/差异及checkbox/hook检查在下段记录。

最终写入后的实际静态检查：公开checker PASS/findings0；544公开输入加feature/公开文档的
隐私检查PASS/findings0；30份feature/Pi入口文档182个本地链接全有效；git diff --check exit0。
逐条重算544输入仍ef4c0fbe…，与冻结清单相同，默认Pi完整锁严格读取522bed3a…。
checkbox87/96，开放064–071/096；requirements checklist只读16/16，extensions.yml不存在，
无after_implement hook可执行。测试模型分工按executor gpt-6.1-sol/medium、scout gpt-6-luna/high
配置执行；另有只读代码explorer核对关键恢复语义，主代理负责公共修复及最终验收；不冒充后端
模型的额外执行回执。没有新的生产修改、运行、部署或提交待执行。

最后增量文档复核确认匹配源/实际锁与模板标签更正、测量值、四模块范围和84条归属一致，
无critical/high；发现两处中途状态措辞与若干字面补丁前缀，已改为最终状态并清除前缀。
仅文档修改，生产/测试摘要不变；随后重跑公开/隐私/链接/差异检查，不重复无关原生或全量测试。
