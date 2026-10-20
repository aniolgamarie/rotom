# Herdr implementation and native acceptance evidence

2026-10-20最终验收：当前66/66项完成。候选工作树仍为`feat/herdr-native-workspaces`，HEAD `93e4f7899725336c1180e53b4ec239eea5f984ce`，本轮目标main引用`b18da6d1df885a81400d721cb46eafdd5c34bb1e`。严格完整首基线通过，独立canary及回退门禁完成，四个空cpuacct委派子组已由管理员脚本清理。原校准唯一预热偏差、三份短验收失败及后续补验分别保存，未改原始结论或计数。结果适用于冻结feature候选与本机声明组合，不是A/B升级比较、合入新main后的集成验收或生产入口切换。下文先给最终结果，其后的Earlier/Previous段落均保留各自阶段状态。

原生终端与受管实例使用私人临时HOME、合成Git checkout和本轮命名server。模型交接探针由官方Codex CLI原地使用已有认证；代理不读取或复制认证文件，操作对象仍为合成checkout和明确选定的导出。实际argv/环境/原始响应/驱动及错误保存在仓库外0700目录、0600文件；公开文档只保留normalized动作和原件SHA256。没有读取真实会话正文或改变生产默认入口、账号选择、旧tmux/Herdr任务、全局alias。

## Final completed acceptance on 2026-10-20

公开派生摘要为[acceptance-summary.json](acceptance-summary.json)，它独立标注derived summary，不冒充改写后的原生report。严格首基线实际20370秒（约5小时39分30秒）、run exit0、comparison pass/valid、baseline_digest=null：完整三batch、33个CPU窗口，每窗口301个内核快照及前后成员原件通过；45/45正确性、1338条producer（669 warmup/669 measure）以及426条输出phase精确计数通过。必需未验证0；可选未验证267，未将其记作通过。scout（gpt-6-luna/high）在管理员清理前独立重验schema/references、report.source与manifest及全部私人原件；清理后Root又离线重验已存schema和引用，不依赖已删除的活体计量组。report raw SHA `bb3159617dcb2230eb7139e5245b2b31e30aa75e3263797fde20e152a1de800f`；comparison `405a15f4241f3a859d8651af787c730b1be2f216edb909893f3a058330b51888`；finished `6b5606a932949f8b5cf63e5f8b937f6e00c832ff64f6808ffa84f9ab3844e817`；postflight `73a644705ef3823b3b30f2dd525368db5cde70feaf252684e50d944e13d4f507`。本次严格候选没有沿用预热例外；原校准仍按其唯一明确例外用于噪声校准。

自动链在首基线通过后执行短canary，但原验收脚本错误假设headless server自带一个pane，停于`fresh_initial_pane_required`；12条CLI均0，Root fresh确认原专用server的workspace/pane皆空、PID/starttime/asset/socket匹配后正常停服，收据`559138a933ebfaefba8965ed8632d7cbabf54d3c292e10cd6fd58001e9a859f6`。原失败`ba8b0da40ce245bf787d794b0f9f6de03fc2f86353216683e1ef6c205bf7c373`不改。

executor（gpt-6.1-sol/medium）仅在仓库外新版本增加独立合成Git bootstrap checkout：新server必须workspace/pane同时为空，再在既有operation_lock中调用冻结enter_project，fresh核对唯一返回workspace/pane身份后登记；68项隔离检查通过。脚本`83ea30a18598fc41bbee385258b1211dad1a26cbcba75007c2f493ca3b1ef231`、测试`bbd2e8db8683af46bda5e65d167f59f3bb95d0eb3e755cda41e057413f31814a`。其首个真实work enter返回4，固定`work_other_server_context`错误的stderr摘要与原件相同，证明私有脚本错误地向work传procfd别名，而产品要求已核验canonical socket；没有修改产品门禁。原失败`4c85474fedf115a9a68cdb310a0178320f2141ebe5d4568a8409846524937545`保留；Root核对唯一bootstrap pane和子进程后协作退出并正常停服，收据`0492af5b5888933334123e90910e8e8125e32a240a0b0b9304b916b88d0fa294`。

第三版私有脚本仅修work参数为已核验canonical socket，原生Herdr CLI仍用pinned FD；69项隔离检查（0.24秒、exit0）通过，脚本`ea8ad6af1b9306920044d94955c7191b7b4db4a837e2fc00e2d055d3a1508182`、launcher `9e401529a9502604024ed545b36d262d924c91b4b56a0a69cf23e7220fb76a0f`、测试`b817817fc51177266d03b910d96d83ab5d090d87dbfefedce14de1b0d66d507b`。normalized native argv为`.venv/bin/python -B PRIVATE_OFFLINE_CANARY --baseline-decision-sha ACCEPTED_DECISION_SHA --baseline-postflight-sha ACCEPTED_POSTFLIGHT_SHA`。实际完成bootstrap、目标work enter/build/debug与重复复用、配置rollback/reapply、旧0.8在独立HOME仅schema能力拒绝、四子任务身份持续和协作exit0；29条CLI全0。随后在state-copy前出现泛化异常，原失败`8e15162facbc5ddf9146016b8b1cb3f4072bda3d0a4f00f2c8164b5390371047`保留。当前自有session.json后来存在、version3且mtime晚于失败；异常类型未保存，不能断言当时一定是FileNotFound或确定为上游缺陷。

Root不重放已成功操作，重新核对同一实例的PID/starttime、官方asset、socket、两个workspace和全部四pane三元组、四wrapper存活及子任务exit0收据，继续在冻结离线filter下仅补状态保护副本、fresh完整对象核验、一次official server stop、PID/start及discovery退出、最终source/input复核。派生完成证据`21177019fdc39ccf2e24d925522546778ed074ed98f9b56982a04483cb0b32ff`明确引用原partial失败，不改原success=false；合并的30条CLI均0。Root独立接受收据`633d6ca6497ffda14e9550fdb7905a5f92cad089b1cca1ebae44bc5993863acd`确认T052本轮范围完成。状态副本逐字节/摘要及复制前后原件身份匹配；native_state_compatibility_verified=false，明确执行compatibility_unproven_stop，没有让旧binary打开原状态/副本，没有声称降级兼容、进程迁移或生产入口切换。

全部需要读取委派身份的验收结束后，Root最后fresh确认driver/server/client/producer四组均0，再执行一次`sudo -n /usr/bin/python3 REVIEWED_CPUACCT_ADMIN cleanup --token PRIVATE_ADMIN_TOKEN`；实际exit0，管理员脚本核对原root收据/boot/scope/四组inode后删除四空组及本轮root收据，Root确认scope与root收据均消失。清理收据`242b9f73a891e542c5c0ece06a206431fb246eca796f1c13468a61a91576b50d`。没有密码输入、PID迁移、kill、配额或重挂载，所有本轮登记测试server/任务已收尾。

最终私有证据归档在用户现有private state目录，109个文件含79个冻结源快照、接受/失败/清理收据及自有合成状态副本；目录0700、文件0600，全部复制摘要核对、原件未改。inventory SHA `352e64d9f9194893fadfe1fe9266713f3a87fb91b271a23ece91012ff6c5c1c8`；基准原manifest/report/records仍保留于原私人持久目录。公共仓库只保存摘要/结果及SHA，不发布实际argv路径、主机元数据或管理员token。合入main和切换生产默认入口仍是后续操作；本轮没有commit/merge、替换全局binary或影响旧tmux/Herdr长任务。

## Earlier T066 acceptance and strict first-baseline execution

T066已完成。executor（gpt-6.1-sol/medium）只在仓库外实现固定例外审阅器，60项默认隔离检查通过（7.47秒、exit0）；覆盖缺批准、错摘要/身份、额外或正式输出缺口、重叠窗口、缺样、预算、候选invalid以及末次原件变化。保留RED（59通过/1失败）后修复末次原件变化未拒绝问题，再对稳定文件GREEN。normalized argv为`.venv/bin/python -B -m pytest -q PRIVATE_TEST --confcutdir=PRIVATE_TEST_ROOT`。审阅器SHA256 `d84c0fb46a09e9bcb506ef999d02b5b77b5c647f0e77bdf260c62ecbabc0b3d5`，测试文件`2b348c8907ca54d63891ceebb7547a6f3225c78025893706c5642db4db2ef984`。Root审阅稳定实现并运行实际只读复核exit0：原报告严格valid=false、baseline=false，仅原producer_complete/report_valid/calibration_references三门禁为false，其余全部true；固定原件证明同run/pane/PID及预热结束早于正式CPU窗口。不是将模拟测试冒充实际复核。

Root按用户已接受的明确例外和继续授权审阅实际噪声/预算，仅新建独立接受收据及冻结policy；所有metrics、regression、calibration_refs与原pending完全相等。原校准raw SHA `c1b846a32c3064824f4ef320bc68cd86581bbe6133c66ccd50589167e661f7bc`及invalid/计数不变。接受review `9f3dec114abac000a58af66ec3626e89e9b301dcbae8adeb0854a391ab2ca117`；冻结policy `4113a5e3760edc21fb9b99d3f979110c429d4b25af4c12c094262ccb536405ec`；Root批准收据 `cae3787d805ebed369cde270cb0b1dea8393b1a5038fca338d0cbfa8cb24ec25`。这不是脚本自动批准，也不是用户亲自逐项审阅全部噪声数字的声明。

四组fresh为空且原驱动退出后，Root对完整已登记校准树执行同文件系统原子不覆盖归档；14752个目录/文件条目的inode/metadata保持，原路径消失且记录原件再验通过，未删除任何内容。归档收据`d4ad9fda022481ef38a313effbbb44fcaedefb69d5f240518ec3985982d7ac00`；脚本`a3d3aaaebce763ec7f813fe01ee04a56d9541a20186a7820071922398744fb11`。隔离文件原语检查证明不覆盖、同inode归档及拒绝symlink；首版probe误要求唯一拒绝类别，修正断言后3项通过，原安全拒绝行为未改。

首基线第一次真实入口退出2，原生日志明确`actual_source_commit_or_target_main_mismatch`，没有进入测量，四组为空。开始收据`2c55624497354de6535a9e79d83ee840ba54cc00d404ab1a5af9d4eb15eabf60`、结束后复核`2a627da42374ef60537c7ed1d40ddc6f1edf0203511e0d4e16d6c2661b9aeb3c`均保留。共享main在长校准期间从`93e4f78`经`3d41dab`前进至`b18da6d`；feature工作树没有合并、rebase或切换HEAD。scout（gpt-6-luna/high）只读盘点确认主线Pi重建没有提交改动Herdr专属路径或uv.lock；通用agentcfg模块有Pi相关变化，但本轮执行仍读取未改的feature工作树，不能据此宣称合入新版main后的Agent集成通过。

Root明确细化引用契约，而非利用`verify_calibrations`缺少manifest绑定的实现空隙：原校准始终按原manifest复核；另建首基线manifest，深拷贝相等性仅允许`manifest_id`后缀、`source.target_main`和自身digest三个位置变化。候选HEAD、source/lock/asset、subjects、配置/规则/集成、工作负载、采样、隔离root/records/sentinel和policy完全不变；新候选必须严格绑定新manifest及其全部原件。跨manifest复核脚本`5dea94c6c20941f7792aba4becee5aeac930167853faea3aad961d20832f8781`，6项纯数据检查证明唯一引用刷新接受、候选/资产/窗口/root改变拒绝、原对象不变。新manifest raw SHA`58110ba09cd354359fc45e956be89a13e2a2e0dc65c2f9b919797cc3306df47a`，显式引用复核收据`2842a89f2fe1650457c63d5d83820abab247ccce3e405c6d4dc2dc8d919eb22c`。未改原manifest、报告、测量引擎、schema或Git引用；这是原feature候选的首基线，不是已合并main的验收。

新首基线normalized argv为`.venv/bin/python -B tools/bench/herdr_upgrade.py run --manifest REFRESHED_PRIVATE_MANIFEST --policy REVIEWED_PRIVATE_POLICY --subject candidate --scope first-baseline --allow-native --authorization native-full-bench-20261019 --offline-sockets --cpuacct-delegation PRIVATE_RECEIPT --output NEW_PRIVATE_REPORT`。协调脚本`626b2e9f3fc5469fb0fd63a05922bf89a89609e310f0398b877d844a1f01d023`和实际开始收据`efb7aac945d5be72a3c4104497afa74c608f3891c663cbe70f516ac3b1bed98c`已保存。完整首基线已启动，结束后自动重验固定校准例外、原件与跨manifest相等性，再用原公开Python compare参数生成schema合法comparison和独立provenance；任何候选输出缺口/预算/正确性/证据缺失仍不得PASS。当前没有最终报告或比较结论。canary只准备，不与性能窗口并行执行；管理员组清理保留到全部测量结束。

## Earlier armed finite continuation after the running baseline

Root已审阅并启动一次性收尾链，当前只等待首基线，并未执行新canary。首基线严格PASS后，按可信decision/postflight摘要串行启动全新HOME、session及合成checkout的canary；不会与性能窗口并行。canary覆盖enter/build/debug、重复复用、长任务子进程在配置rollback/reapply及未来binary选择期间持续同PID/starttime、旧0.8仅在独立空HOME执行官方schema能力拒绝、受保护状态结构副本及compatibility_unproven_stop。子任务协作exit0后，pane wrapper保持存活；仅在fresh完整pane三元组和双路由身份核验一致时一次official server stop。未给旧binary打开原状态或副本，不改变生产入口、不宣称状态兼容或任务迁移。

executor（gpt-6.1-sol/medium）实现的固定canary经过51项隔离探针（0.17秒、exit0），脚本`050e9b97e9214ccb5287710755e4a78fe4e34e1a1b99d8b6787fbc630ca60289`、测试`fd16b400dc0beef864bb2f561ef7094c74312568ac06d19959e06f585da2de86`。只使用既有冻结离线filter，缺证明不创建新对象；实际native尚未执行。Root的固定离线launcher `b4f56b28b33316a1248d3a6e237ef51e491410845cd9a277c28c9beb3b9824de`。normalized探针argv为`.venv/bin/python -B -m pytest -q PRIVATE_CANARY_TEST --confcutdir=PRIVATE_CANARY_TEST_ROOT`。

Root编写收尾链，executor独立审查发现records空列表可使all([])通过、canary等待缺少硬上界两项问题；Root修订为非空CLI记录且exit_code精确int0、canary等待30分钟上界，超时只保留PID/对象，不kill/retry或进入清理。随后49项隔离探针通过（0.12秒、exit0、无xfail），测试`5612f2d35eda6723eb934ffad62d4a14065b2679d2859509821a445dbbab547c`，收尾脚本`34f0d2068d99654b97533015ee8475866f1804ed528c4e1f00c48c5ba7ac4439`。normalized探针argv为`.venv/bin/python -B -m pytest -q PRIVATE_CONTINUATION_TEST --confcutdir=PRIVATE_CONTINUATION_TEST_ROOT`。真实normalized启动argv为`.venv/bin/python -B PRIVATE_FINITE_CONTINUATION`，已armed收据`f17b4f035137f82ceaf29beae38ffb8d4e6707be9421c5e77728813e32bda2b7`；这是启动和等待证据，不是native canary/最终验收通过。

链只在strict baseline、canary、回退及全部原件门禁通过后，最后fresh确认四组为空，才尝试一次无交互`sudo -n /usr/bin/python3 REVIEWED_CPUACCT_ADMIN cleanup --token PRIVATE_ADMIN_TOKEN`。源摘要`4129297b0eac9fd04e390c4d9e8e860cb6136a81f978b5572c69265aa298fb0d`匹配，管理员脚本按原root收据核对scope/四组inode且拒绝非空/未知子组。没有密码提示、PID迁移、kill、配额或重挂载；若管理员认证不可用则保留清理待办。canary需在清理前读取原委派身份，因此T052执行依赖T051性能PASS，T051最后的空组清理统一在后面；该行政收尾不制造性能与canary的循环依赖。公开任务状态仍64/66，T051/T052都没有被启动记录自动勾选，最终结果待原件审阅。

## Earlier interactive and managed-runtime continuation

本阶段新增证据与下面的上一轮检查点分开记录，尚未完成的交互不得算通过。

- 实体客户端为macOS 26.6.2、Ghostty 1.3.1 stable，服务端仍为本机Linux。八步记录全部完成：中文输入法、中文两行粘贴、字面Ctrl+x、Shift+Enter、固定中文多行OSC52写入后本机人工核对、20轮分屏/缩放/焦点画面核对、detach重接、退出SSH后重接。普通Enter为CR、Shift+Enter为CSI-u；重接确认为不同SSH连接且同一记录器PID/starttime，最后仅停止本轮server。监控收据SHA256 `f39faf7fa829b38e4c16d816e313b7897d7b9688615bda51cd18314626dcc300`；脱敏版本收据 `9c21c1db5d85726728faa119692c5eb468536c98eedc88cb73d160000173c75c`。Avalon内部Ctrl+w和显式+寄存器已单独补验，不能由通用记录器代替；详见下方续验收记录。
- 记录器在开启扩展键盘协议后仅接受旧式Ctrl+x，导致第3步等待；保留原始fixture摘要与原状态，仅在该阶段向自有PTY输出键盘模式切换，未注入按键或读取任意输入。用户实际按键后推进，随即恢复扩展协议。当前运行绑定原fixture，不能冒充修订版fixture的完整复验。修订版同时接受旧式及CSI-u按下事件，拒绝释放/其他组合，16项隔离检查通过。
- `CODEX-MODEL-REVIEW`：官方Codex0.163.0 `--no-daemon`，`exec --ignore-user-config --ignore-rules --ephemeral --sandbox read-only --cd SYNTHETIC_CHECKOUT`，关闭shell_tool/plugins/multi_agent；仅把明确选定的合成`prompt.md`传入stdin，120秒上限。实际6.34秒、退出0、约定回复匹配、合成fixture文件字节不变。官方CLI正常使用已有认证，未复制凭据或整个Review状态；私人收据SHA256 `b1195232cfc6e45ad578392a406be24013f3f45a9dbe68239c1e0608164842c9`。这补充模型/选定交接证据，不代替受管Pi启动。
- 用户授权继续完成Pi准备后，正式锁生成保持38个source及原有直接来源不变，四个profile的传递依赖`typebox`从1.3.37更新至1.4.2。仅允许正式生成五个Pi锁文件，不手改recipe摘要；新增inventory优化和原生重验单列，不能继续把公共依赖锁描述为未改。
- 用户在普通SSH shell通过sudo执行只读检查，确认v1 cpuacct挂载和superblock均可写、user/system纳秒文件齐全、有效及bounding CAP_SYS_ADMIN可用、未设置no_new_privileges。早先工具沙箱的只读挂载/capability结果只代表该沙箱。准备脚本仅在当前cpuacct源组下创建driver/server/client/producer四个空子组，保留现有资源约束，不重挂载、不设置配额、不迁移已有PID；用户已执行准备；私有收据权限0600、boot/source/mount及五个目录inode全部匹配。随后真实统计挑战通过：8个短命子进程、4线程、双fork后代分别与wait4/rusage聚合核对，预冻结容差为各user/system分量及总和均不超过0.05秒+5%；每轮CPU信号大于0.1秒，driver顺序恢复，组间无CPU污染。挑战收据SHA256 `8cdf64efb9c49897aa2e1e7e8ea7a07b870d00b539b9f8b902ee90141689645f`。这验证统计原语，尚不代表Herdr完整300秒窗口或首基线通过。公共脚本为 `tools/bench/cpuacct_admin.py`，SHA256 `4129297b0eac9fd04e390c4d9e8e860cb6136a81f978b5572c69265aa298fb0d`；9项隔离检查通过，完整Herdr CPU覆盖仍须后续采样窗口的成员及端点证据。
- `REGRESSION-07`：在安全HOME专用临时根运行前轮排序去重关联命令集，新增客户端解码与Pi inventory检查，**830 passed，221.85秒，退出0**；66个源码/fixture/测试/锁文件执行前后一致，摘要 `f668a89161927a7ed606f88c65736d5d3539da67f62c09c8ae92c36b7d42daef`，私人执行收据 `3ce33618ba2497f2032dc78866e7da0f2ccd46c8719b50124405588e93df1191`。该快照仍使用统一30秒总期限；后续仅pi/dsh预算修订须单列受影响回归，不能把830项结果绑定为修后源码。
- Pi首次正式受管入口27.9秒返回0、Node实际cwd/profile/HOME正确；第二次开extra在30秒后返回4，launcher尚未exec Pi、原primary PID/starttime保持不变。T061把受管pi/dsh总期限改为60秒，保留父子同一绝对期限、锁10/connect2/request5及完整校验；相关141项隔离检查通过。全新专用server复验primary 29.263秒、extra 25.094秒，均退出0；实际Node均有独立running租约及持续20秒的PID/starttime/cwd证明，primary未被替换，extra未提升为primary。双实例收据SHA256 `1fc550067642166ec4d61a32d238d00b1a942a90cfa8fdc1f00e43a1465ad38d`，启动交接 `ad4a6266ee0ba21245f0df7e2e15067c9b96d2ffcaa01167061170a38d18f75d`。随后仅向这两个已固定身份的闲置测试Node发正常终止信号，supervisor自然回收两份租约，再核对唯一剩余测试shell并停止专用server；清理收据 `e24734b2df7779771e8344ff54c5f5f840135c023c3d4083703d397ce9e068f5`。没有发送模型Prompt，模型交接证据由独立Codex探针提供。
- Pi正式锁身份为 `07274df7b881600f2d736af2023c03547075b7b8ec80c52b04a6ec149c0249b6`，运行包身份为 `9b3b7a03098a30a7bd30f8e074eda8488f76879d88641f311477937841c10953`。库存包含55,306条目/50,220文件，完整inventory 4.094秒，完整status首次15.28秒、热态9.349秒；这只说明本机测量，不新增跨机器精确性能保证。此前旧测试租约通过官方recover计划核对并回收；一次私有存活探针误把线程显示名当node程序名，保留探针失败后改用实际exe核验，未据此改动宿主或重新启动primary。

## Previous sole-host checkpoint

| 范围 | 当前状态 | 观察与限制 |
| --- | --- | --- |
| 核心代码与termcfg | 已完成 | 原生发现的umask、linked source、adapter schema三项修复已验证；新增bench入口/fixture后全关联796 passed，源码前后稳定 |
| T027 Linux原生核心 | 已完成 | 配置诊断、9checkout/27终端、100重复/2和10并发、100用途复用/10新增、37实际cwd/存活、PTY连续性、冷恢复 |
| T028 SSH/真实客户端 | 部分完成；实体交互环境不足未验证 | 本机OpenSSH8.0回环双客户端20轮、精确输入、强杀客户端/全detach/重接同PID通过；无可操控桌面/手机/IME/本机剪贴板接口，视觉及真实网络故障未验证 |
| T042 Avalon/Agent | 部分完成 | Avalon独立入口、Review冻结/显式刷新/校验导出/关闭保留、Codex --no-daemon/cwd及受管DSH实际启动已验证；Pi缺有效锁/部署，账号模型与目标Agent交接尚未验证 |
| T051 性能/校准/首基线 | partial观察已完成；完整基线环境不足未验证 | 本机offline-sockets/output-1完整60+300秒计数达标；原run清理门禁退出4、报告invalid，完整CPU/三batch/批准校准缺证，不建立基线 |
| T052 canary/未来入口/回退 | 部分完成 | 隔离配置rollback/reapply、旧binary能力拒绝和状态保护副本已验证；真实客户端/性能前置不足，不冒险生产切换 |
| T056 状态增强 | 已完成（最终选择全关） | SC-010隔离路径通过；不安装扩展/控制skill/新增profile，不声称启用或双实例关联通过 |

## Native asset and core receipts

2026-10-19显式核对[官方latest](https://github.com/herdrdev/herdr/releases/latest)，候选仍为[v0.9.5](https://github.com/herdrdev/herdr/releases/tag/v0.9.5)。使用官方 `herdr-linux-x86_64` 资产，SHA256 `14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d`，tag commit `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`；实际client/server均0.9.5、protocol22。既有PATH中的0.8.0未替换，不视为已接受性能基线。资产原件收据SHA256 `d4810cfde5407ca778ca278bfa10bbb462ef437e7faac27bbc06643a4955dd42`。

| ID | normalized action | Result / private receipt SHA256 |
| --- | --- | --- |
| NATIVE-CONFIG | termcfg --machine SYNTHETIC init-local/plan/apply --component zsh --component herdr; HERDR config check | 均0；apply `37c568bb2c8eef88e05ae46e5a19924bae4efc827c16baeca907991a3369d733`；加载诊断 `98192a9ca751073617f0cdc52255c9464d0efdfaad04c2e34cf4845d63652420` |
| NATIVE-SCHEMA | HERDR api schema --json; fixed endpoint ping | protocol22；schema `a52c9599e8f945ae9e507fbba7020af080222daaefe56ad43428af20d70bae0f` |
| NATIVE-CORE-MATRIX | work --local TEST enter CHECKOUT; open build/debug; enter×100; concurrent enter×2/10; reuse×100; --new×10 | 288命令全部0；9工作区、先27后37终端、primary/epoch不变、切branch/外置cwd不改归属；`5b20976a4e9e22fcff819a8784c10e5439a1bc8304a9a4ee87f54fa4d6e8c0f3` |
| NATIVE-PROCESSES | HERDR --session TEST pane process-info --pane ID; selected /proc PID cwd/starttime | 37个实际shell存活且cwd均为正确checkout；`20b127b274e271f13285d25b2866fd621e2c0f8d9457367346a0d2e9559af9cc` |
| NATIVE-BOUND-PROOF | read_settings/connected/enter_project direct calls, new TEST server, main/linked/symlink under Unicode+space roots | 调用者umask022，父目录0700/socket0600；合法adapter配置无凭据加载；两个checkout唯一归属；前后核心source_digest均 `d61c1b0e4b852c6fa4704150dceab08e4d0018c83fb07556c34bc02b52db45c8`；`e4b09b912bb7d058e70fb7ce9cd71272d6a21f31de034d34381aff2fc3189e86` |
| NATIVE-PTY | own 120x40/80x24 PTYs; known input recorder; native C-x+d; close client; reattach | 中文/宽字符/多行57bytes精确；C-x C-x传入单0x18；双client20轮resize/focus、detach/客户端退出/重接均同PID/starttime；`dc83e1ac5f7ecbbf6461c8888fe9042ea5148ee68ae468991fe3ac24480246a8` |
| NATIVE-SSH | temporary loopback sshd; OpenSSH clients -tt; native split/zoom/focus; force-kill one SSH client; detach all; reconnect | 全新合成host/client key与空HOME，无PAM/密码/转发；中文多行49bytes与C-x精确；双SSH客户端20轮，原producer PID/starttime持续不变；所有预期命令0，故障注入client=-9；`3f2361b5cdaf61c62f531e91aa5df3bd349febadccef3c2f710a9a6d8e74a5e6` |
| NATIVE-COLD | HERDR --session TEST server stop; explicit same-asset server start; work enter/open | 9workspace/40pane布局恢复，原producer未重放；7role unknown，普通open退出4；`26864f59d85c37c04061144b41ad9d0ea96ac7883ebe571b8bac2f2d77686432` |
| NATIVE-ZSH | zsh -i -c FIXED_METADATA under test HOME, existing locked public plugins | zsh5.5.1、non-login、ys、autosuggestions/compdef/zinit加载；加入公开示例shim后0；`418f233eba7da2ccc6d972008f90ea9244fde43117c426bbbe472c86c10eb556` |
| NATIVE-AVALON | work open edit --new -> existing independent profile; fixed metadata request then qa | 0；正确cwd，NVIM_APPNAME=avalon、独立XDG目录、Review Start/Refresh/Export命令存在；candidate ready但release_qualified=false；原件digest在最终索引，不冒充完整Review/UI合格 |
| NATIVE-AVALON-REVIEW | actual profile in synthetic PTY; documented DiffviewOpenEnhanced worktree alias; AIReviewExport/Refresh/Close | 退出0；三个独立导出包，未刷新时snapshot ID/blob摘要不变，刷新后与外部改动摘要匹配，三个manifest逐文件长度/SHA256通过，Close后字节不变；`122da9bee366ee497520897faf83f4e79ea318fa31ac4b0cf9f9fe2d8d75e912` |
| NATIVE-CODEX | work open codex --new -> installed Codex0.163.0 under private HOME | 0；实际argv含--no-daemon，实际cwd正确；无账号/模型调用；`61d620cadea03efd11fec005bd12a0efbda1c3165be859c865e5f88809607cb4` |
| NATIVE-DSH | existing dsh-default/public lock; isolated agentcfg plan/sync/plan/apply; work open dsh --new; owned process inspection | 准备/启动命令均0；实际node launch.mjs、正确checkout/独立HOME/DSH_HOME和已安装runtime身份，3秒存活；未发模型请求；apply `eea3831c1850ff56c764dc86cb2f9fcc1ce306951b0278602fc59f721783f628`；native `7acc248f7eba4467be3407c30747f28ecef1f953234158abe1744bb22ce9617c` |
| NATIVE-CONFIG-ROLLBACK | termcfg rollback --component herdr --plan-id REVIEWED; plan/apply same static file | 0；受管文件移除/原字节重装、同server socket未变；`911c4a373ecb7c50f45a500f55635266629d5313b04c8f35ed1276a72b736b12` |
| NATIVE-ROLLBACK-GUARDS | private old-binary choice; protected copy of synthetic persisted files | 旧0.8能力门禁5；恢复0.9.5选择、运行server仍0.9.5；复制3个合成状态文件而不在旧程序上打开原件；`173896b8ca9742a8ba6c75a845dba4f685b22309aa3e68c5a41d384b6702f076` |

Shift+Enter的合成CSI-u输入实际记录为CR，只记observed，不判真实终端组合通过。PTY/SSH尺寸观察为共享协调后的pane尺寸，不能写成两个独立TUI尺寸。SSH客户端强杀测试只证明本机OpenSSH回环链路的断开存活；真实网络中断、实体输入法、视觉重绘和OSC52仍缺证。

## Native findings and fixes

首次新server沿用022导致socket父目录0755被正确拒绝；修复为Popen umask077，保留安全检查。首次linked checkout从自身发起open得到明确 `linked_worktree_source` 拒绝；修复为先查公开source后从主仓库发起open，目标身份不变。已有机器合法adapter-specific options被普通读取错误拒绝；修复为传入公开adapter schemas，仍load_credentials=False。三项均保留RED/GREEN与原生失败原件，最终绑定源码的独立复验证明结果。

原生zsh首次缺少本机兼容shim导致补全错误；使用现有公开examples/zshenv.local.example的兼容段后复测，不修改系统shell或复制私人hook。冷恢复驱动前两次分别漏start_headless参数、在停服前后heartbeat取样存在竞态；均为验收驱动错误，保留原件，修正后干净复测通过，不计作产品失败或环境缺失。

回环SSH首轮未等待第二客户端UI就绪，20轮中的两个输入nonce缺失；保留失败后加入实际画面标记就绪屏障，在干净记录器上重跑全部20轮及断连测试通过。中断的重试也独立保留，未合并输入原件。DSH首次验收驱动把官方process-info外层JSON误作内部对象；启动实际成功，但脚本KeyError，保留失败收据后按官方包装结构重跑并核验实际node进程。两者均未修改产品逻辑或隐去失败。

Avalon Review只操作新合成checkout的canonical-root hash命名空间，未读其他项目状态。首轮picker纯字节标记等待失败；第二轮已用公开worktree alias成功导出，但脚本误假设导出直接包含原始blob文本。修正为核验公开review.json的current_snapshot_id/文件blob_digest和manifest后，新项目完整复跑通过。没有调用私有session API、修改Avalon代码或提升release_qualified；合成PTY不响应DSR的启动提示仅属该终端仿真限制，实体界面仍未验收。

## Measurement limits and delivery decision

本机cgroup不可委派，procfs轮询无法覆盖短命CPU。两组自有进程树实验包含线程、短命子进程和doublefork/setsid；perf task-clock与完整SELF+CHILDREN的rusage user+system仍有7.4–11.6%差异，不能冒充冻结CPU指标，也不事后放宽预算。完整矩阵固定窗口加屏障下限18492秒/subject（5h08m12），不含Git和操作；A/B至少加倍。在必需测量条件不成立时不盲跑长矩阵。

新增明确单case诊断、预计耗时、实际内建rules/禁用integration来源fingerprint及同UID网络namespace helper，均有隔离测试。只有显式case+allow-incomplete-cpu允许pending-policy诊断，报告必须partial/invalid，不能比较晋升或接受为baseline；完整run/calibrate仍需冻结预算。早期两个原生诊断均在warm/measure前失败，当时0有效测量。过程中发现Linux Unix socket路径过长，已缩短case/session并增加启动前字节长度检查。

默认沙箱的EPERM不能归因上游；受控新namespace内官方server能启动，但同UID映射令宿主root祖先显示为overflow UID，现有核心socket保护拒绝连接。未放宽检查或新增隔离服务，probe已安全停止。能力证明原件 `e4861ed5db659980a0f77c634c8b7727629f62b9a8cd8b3ff258d684e06ea50a`；早期基准原件索引 `7f3a2c1124c79a9f6367e2d7e2de223112df97e2bb902d9a5d8f9e34215360c6`。后续仅用本机恢复测试路线，不要求其他机器，结果如下。

本机`--offline-sockets`采用已有libseccomp/no_new_privs；真实IPv4/IPv6 socket/socketpair与io_uring拒绝、AF_UNIX往返、无额外FD/网络stdio、root UID可见均通过。实际官方agent-manifests/integration-status原件匹配builtin/disabled来源fingerprint。共享/tmp不足256MiB时guard停止于宿主启动前，未降门槛或清他人文件；改用本机安全root-sticky的/dev/shm短case根，先核验AF_UNIX/O_PATH/目录fsync，证据留安全HOME，manifest/pending policy同时明确`linux-local-shared-tmpfs-case-root-diagnostic`，不与磁盘根混比。

真实normalized argv：`.venv/bin/python tools/bench/herdr_upgrade.py run --manifest PRIVATE_MANIFEST --policy PRIVATE_PENDING_POLICY --subject candidate --scope first-baseline --allow-native --authorization AUTHORIZED_DIAGNOSTIC --offline-sockets --allow-incomplete-cpu --case output-1:output --batch 1 --output PRIVATE_REPORT`。预热**30720行/3932160字节/60.000070535秒**；正式**153600行/19660800字节/300.000039216秒**，精确达到512行/秒目标，8项观察保留。该原run最终退出4：关闭最后owned pane后Herdr自动创建新pane，严格陌生对象门禁保留server；人工核验仅本轮合成对象后stop0/discoverNone。报告原件 `92d22dee97cabd4ffd9109b1380b39db9e9d1a1760a454421eda423a9f643c68`，清理原件 `5dad0f82ff7e831a433b81c6c6656c3539333d82b748b14aa857fdf0886e2e8f`。

测量绑定当时冻结runner `e8e24d7bf456bc754a5631d94d367a2ebac72a95fbc8093421b803dbe5f02ca0`，不能重标为后续修订源码。保留pane token拒绝、producer时钟边界失败、UI错误路由、tmp空间guard及私有manifest/policy环境标签不匹配的各轮原件。修复均先RED/GREEN；实际计数不改写原run的exit4/partial/invalid，也不补造缺失batch。CPU完整性、client-ready/dimensions、批准policy与A/A仍缺证，T051不通过；T052生产推广前置不足。

后续稳定修订：UI成功spawn即登记子进程/PTY，spawn前后失败均正确释放已拥有FD；清理关闭其余owned pane后保留最后一个已登记pane，严格确认当前对象恰好与其pane/terminal/workspace身份一致，再停止专用server；出现陌生对象仍退出4并保留。FD三类与cleanup两类故障先RED后GREEN，最终bench/policy/API **94 passed，4.97秒**，offline validate0。短原生复验以实际offline-sockets、新合成Git工作区和两个普通pane验证该顺序，stop0/discoverNone，无fallback遗留；原件 `2fd8e8078d2c70ce6e5c46f4f21334e563301452ae16b81d736d38a5444ceec9`。首次短驱动假设headless已有工作区的失败另保留，未混记为cleanup通过。

最终runner `a85d95832e91c37e739c88f77b935faf06a1ccadb072d6cf3f2f26fa76b63a3b`，fixture `c0a2df9b676c3c9b8ac1fb3330a181345ac5310f57f788593b70f2b54b8c3ecd`；本轮bench全部原件SHA索引 `6ee9ee3f2bebdc76e77e73fc2bb1c2aba8b737162c3b482aebc17ba933ca6bde`。新源码只做受影响故障与短原生复验，不把旧窗口计数冒充该源码的性能基线。所有本轮自有server/producer/临时sshd均已停止，私人原件及准备好的隔离运行包保留。

本轮稳定diff复核：57个运行/测试/fixture等文件的有序内容与mode摘要 `b88718728e6158d8ddecdba69a7b857540f61702eed09158989ad734cb81de9f`；87个公开候选文件的私人身份/路径扫描无命中，git diff --check0，无公共依赖锁改动。审计原件 `47da9c38b9585f03d978572b8fd7cffe5339c9fc938ec35f05281dc995fcc21a`。HEAD/main仍为起点，主工作树三个既有文档改动保留。未提交、合并、发布或切换生产入口；最终Speckit只读分析结论见implementation-review.md。

模型执行保持executor gpt-6.1-sol/medium与scout gpt-6-luna/high；主代理负责并发/恢复及最终验收。以下旧阶段的54/60状态、767项检查和摘要均为历史快照，本轮最终结果另附，不混用。

## Final verification after native remediation

本机唯一环境续验收的关联回归HERDR-FINAL-REGRESSION-06：与下述REGRESSION-05相同的排序去重命令集，改用安全HOME专用0700临时根，退出0，**796 passed，199.92秒**；私人执行结果收据 `fafe74b364c300cbb2decc1cf354d14bd46756d00303a16c240d24347d5444bf`；执行前后57个运行/测试等文件内容与mode一致，source manifest摘要 `ba60ced24bdf5436c2157ef8c96e6d741e26c7f7b9e6e4fb2ad24dddb25a1a10`。临时测试树已删除，仅保留私人log/argv/源清单/结果原件。该快照包含offline-sockets、官方pane token、单次时钟读取和UI session路由；后续最终故障分支修订/相关检查另列，不把重叠检查数量相加。

HERDR-FINAL-REGRESSION-05：`.venv/bin/python -m pytest -q --basetemp SAFE_TEMP tests/test_work_*.py tests/test_herdr_api.py tests/test_termcfg_*.py tests/test_herdr_benchmark.py tests/test_herdr_upgrade_policy.py tests/test_config_*.py`（执行前排序去重），退出0，**784 passed，294.18秒**；实际执行收据 `045aa117cd3b3be1e824ad7ad23878aa45790062c04e851b6482d0d444940434`。生产源码在执行前已稳定。随后只补环境边界合成哨兵并整理两处测试格式，受影响四文件检查47 passed/退出0；收据 `a28d4e29e38e388d8acdd72309197f73472955ebd43b95f8f157e5870e8db0c1`。不把两次重叠测试的数量相加。

此前REGRESSION-03退出1：579 passed/205 setup errors（248.18秒），收据 `4933a66f72f34253ac063b438aba082b454b2434c36af771925a21ed95bf4924`；共享/tmp被安装暂存消耗至ENOSPC，随后临时目录创建错误级联。仅清理本任务DSH未激活缓存，释放约846MiB。REGRESSION-04换data临时根后退出1：582 passed/178 failed/24 errors（47.46秒），收据 `6d5ae752f89d95d405c06d8dba3228b414d4ec8e56d47e6ff309d93dfaa2ab05`；data共享祖先0777非sticky，既有private guards正确拒绝。未放宽保护或改共享权限，保留小原件后删除本轮data测试树；恢复空间后在安全/tmp新根完成REGRESSION-05。失败记录保留，均非测试通过。

DSH历史准备尝试仅用现有dsh-default/public lock新建隔离selector，plan0/sync5，未激活。安装期间出现ENOSPC，具体installer退出码未完整保存，不能归因包缺陷；data替代因共享祖先权限不满足而停止。失败原件索引 `ebc50585f4479be342a51e8e68ec05d830b546a1a03d723e009b0347dab426b0` 保留。后续只读存储审计发现本机HOME所在安全ext4约156GiB可用，在专用0700目录重新准备，plan/sync/apply及真实启动通过，见上表；没有放宽保护或改共享权限。公共依赖锁未改。T042仍因Pi、账号模型和完整Review交接缺证保持部分完成，不能用无账号启动勾选。

Pi只读调用链复核：recipe_digest纳入全部src/agentcfg/*.py，既有通用模块变更使当前manifest的recipe摘要过期，manifest自身identity仍有效。已有完整部署可按已保存contract启动，work/agentcfg run不重解析当前锁；本机却没有该部署，不能用于准备新的隔离实例。正式lock命令会重建全部四个profile slices、重新执行npm解析并写vendor/package-lock/manifest，没有受支持的仅刷新recipe摘要命令。本轮不手改摘要、跳过门禁或把独立上游Pi冒充受管Pi；四套依赖的重新解析和资格验收另属公共依赖升级范围。此为仓库准备限制，不是Python补丁版本要求，也不以另一台机器解决。调用链见src/agentcfg/pi_dependencies.py、pi_vendor.py、runtime.py、pi_runtime_packages.py。

前轮56个变更source/schema/fixture/test/terminal/tool文件的有序内容与mode清单摘要 `29b67709c06d0c992dc63542d368b0306ccecf1f045120c9a5db217aab3d039f`；uv.lock仍为 `faf915d1bc6cf452fb0ecbc102996fecbbf2d33b9a3a844f7b2020eff81be3bc`。HEAD/main均未前进。前轮125项私有原件的执行后索引 `dafb1e61e82d70e7611b48513b51205259080ec24ef5768affa7da7493258460`；这是收据索引，不伪称执行前冻结manifest。

前轮原生清理：只停止当轮已核对空闲的初次诊断server、绑定proof server、benchmark probe及当前合成server（41pane，未发build/model任务），同名endpoint/cwd均复核。当前server清理原件 `04fb35bbf5c24c56e46ef4b8c96c0bffd9365885a6209e0286ed7c83c2ceb720`。既有Herdr0.8/tmux/账号/用户文件保留，官方候选资产与小型原件留在私人验收存储，没有生产安装/入口切换。

前轮实施后续分析第1轮3项（环境边界说明、plan旧状态、跨切面映射），在只读阶段结束后修订：普通终端保留开发环境，受管Agent重新过滤；没有引入会改变普通终端语义的server whitelist。第二轮0实际一致性问题，44需求/60任务均映射，56完成/4条件验收保留。最终状态同步后只读元数据复核已完成；quickstart旧授权语句修正后再次复核剩余问题0，报告见implementation-review.md。已读取implement/analyze skills，无extensions.yml，before/after hooks均无。

## Earlier isolated implementation stage (historical)


Candidate branch: `feat/herdr-native-workspaces`; starting HEAD/target main: `93e4f7899725336c1180e53b4ec239eea5f984ce`.

本记录只保存normalized_argv、逻辑路径、退出码和脱敏引用；私人原始argv不得进入公开文档。实施按[任务](tasks.md)推进，不把代码/替身测试当成原生通过。

| 范围 | 状态 | 证据 / 下一步 |
| --- | --- | --- |
| 实现前门禁 | 已完成 | requirements checklist 16/16；无extensions hook；现有Python/Node ignore规则足够，无发布根package需要npmignore |
| 仓库环境 | 已完成 | worktree使用已准备的仓库.venv链接，无下载或锁变更；Python范围>=3.11，不要求本机补丁精确相等 |
| Native schema/client/fake | 已完成（隔离实现） | 官方tag fixture/许可、每连接一请求、端点固定、mutation不重试；25项API检查 |
| 普通配置/入口/锁/生命周期 | 已完成（隔离实现） | enter/open/新pane握手与恢复分支已实现，分阶段检查通过；最终稳定关联回归767 passed，退出0；初轮一项bench摘要失败已修复 |
| termcfg opt-in组件/恢复 | 已完成（隔离实现） | executor完成可选单文件组件；既有termcfg完整隔离回归320通过，新增routing检查通过 |
| 基准runner/fixture/schema/文档 | 已完成（隔离实现） | executor稳定交回；63项专项检查和离线validate通过，完整原生循环未执行 |
| 原生Herdr/SSH/真实客户端 | 环境不足未验证 | T027/T028，需实现与相应独立明确授权；未连接真实server |
| Avalon/Agent/账号/模型 | 环境不足未验证 | T042，逐工具独立验收；未读取账号、会话或认证文件 |
| 原生基准/校准/canary/回退 | 环境不足未验证 | T051/T052；未设虚构预算或性能基线，未切换入口或迁移进程 |

模型委派采用角色固定配置：executor为gpt-6.1-sol/medium；scout为gpt-6-luna/high。主代理负责关键并发/恢复语义与最终稳定差异验收。

## Checks

| ID | normalized_argv / method | Exit | Result |
| --- | --- | --- | --- |
| PRE-01 | .specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks | 0 | 现有feature正确，所有设计材料可用 |
| PRE-02 | checklist只读计数 / hook存在性 / git状态 / ignore检查 | 0 | checklist全部通过；现有用户/设计改动保留，不提交或丢弃 |

实际失败必须记失败待决策；修复后附证据，不删除失败记录。每阶段完成时更新对应任务；未授权原生任务保持未勾选，不阻塞无关实现。

## Implementation checkpoints

| ID | normalized_argv / method | Exit | Observed result |
| --- | --- | --- | --- |
| CORE-API | .venv/bin/python -m pytest -q tests/test_herdr_api.py | 0 | 25 passed；官方公开响应/schema，固定端点与错误处理，未启动Herdr |
| CORE-TERM | .venv/bin/python -m pytest -q tests/test_termcfg_*.py | 0 | executor报告320 passed；新增sync/lock路由检查另通过，零插件安装调用 |
| CORE-WORK | .venv/bin/python -m pytest -q tests/test_work_*.py | 0 | 75 passed（该阶段文件集）；27终端、重复100/10并发、复用100/新增10、Review哨兵和全关增强 |
| CORE-02 | .venv/bin/python -m pytest -q tests/test_work_*.py tests/test_herdr_api.py tests/test_termcfg_herdr.py | 0 | 119 passed（该阶段文件集）；其后新增edge检查由最终回归覆盖 |
| EDGE-01 | .venv/bin/python -m pytest -q tests/test_work_roles.py tests/test_work_tools.py tests/test_work_context.py | 0 | 29 passed；ID复用/成员移动/重复primary/准备不足前置失败 |
| REVIEW-RED | .venv/bin/python -m pytest -q tests/test_work_context.py tests/test_work_launch.py | 1 | 预期RED：selector缺失和accepted丢响应的2项真实缺口；随后修复 |
| REVIEW-GREEN | .venv/bin/python -m pytest -q tests/test_work_context.py tests/test_work_launch.py tests/test_work_recovery.py tests/test_work_client_contract.py | 0 | 30 passed；修复selector绑定、caller复查及accepted失败窗口 |
| ENTRY-RED | .venv/bin/python -m pytest -q tests/test_work_entry.py | 1 | 预期RED：两个入口缺准备返回2；修正为5，随后包含于CORE-02 |

上述为分阶段normalized命令与观察，不冒充私人实际argv原件。最终关联回归另生成0700/0600执行原件、日志摘要和evidence_ref，作为可核验收据。

首次在受限文件系统运行私人路径检查时出现 unsupported-root-owner；同环境既有私人路径测试也有该表现。未放宽任何路径所有权/权限检查，改在自动审批通过的受控执行环境运行同样临时HOME/fake/网络阻断测试，通过结果如上。没有启动第三方宿主、读取真实凭据或以环境缺失掩盖代码失败。

独立scout审查发现的两项问题已修正：handoff恰好一个selector，并摘要绑定local配置路径；复用前后重新核对caller terminal/workspace/epoch。主代理另修复accepted请求已应用丢响应的失败窗口：不能确认failed tombstone时退出launcher，避免普通shell假冒已交接工具。失败上报最多额外2秒，不延长业务exec期限。

primary内部标记细化为 `p:<op>:<pane_id>`，仍<=80字符，用权威全量pane查询区分已关闭和metadata擦除；data-model/contract/tasks已同步。Herdr新server启动前新增文件存在/私有路径/三项意图核验与官方config check；该只读命令不会启动server，默认测试只替换该命令，不实际执行。

2026-10-19 再次显式核对 [official latest](https://github.com/herdrdev/herdr/releases/latest)，仍跳转 [v0.9.5](https://github.com/herdrdev/herdr/releases/tag/v0.9.5)。它是研究候选，不是永久版本门槛；未下载或安装该资产，未核验运行server。Python使用>=3.11范围，系统3.8只负责转交，不锁定3.11.11；Node继续沿用各工具既有兼容/锁收据。

Pi/DSH/Codex状态增强均未新增安装/资源/锁/控制skill。隔离检查证明既有Agent环境不会自动继承HERDR变量，状态/子任务/迟到会话提示不会触发任务操作或改变用途目标。仅全关路径有隔离通过证据；实例级真实状态启用仍未验证且关闭。

## Associated regression

HERDR-REGRESSION-01: `.venv/bin/python -m pytest -q tests/test_work_*.py tests/test_herdr_api.py tests/test_termcfg_*.py tests/test_herdr_benchmark.py tests/test_herdr_upgrade_policy.py tests/test_config_*.py`（glob在执行前展开、去重并排序）。退出1，746 passed / 1 failed，215.41秒；原件SHA256 `94be9b7bcf53816a0c18b6f0e162cdbe60f8654a45d5a0dd6cdb8a2d792ca5b5`，evidence_ref=`HERDR-REGRESSION-01`。实际argv/cwd/起止/退出及日志摘要保存在仓库外0700/0600原件中。

失败待决策（已定位到本轮并行修改范围）：test_report_roundtrip_and_cli_compare_requires_private_proof，交由基准executor修复；已由HERDR-FINAL-REGRESSION-02确认修复。其余核心/termcfg/config范围通过；随后新增Agent准备失败的脱敏StateError映射与专项测试，已单测通过，最终核心回归再覆盖。此记录保留原失败，不改记环境不足。

最终scout只读复核（gpt-6-luna/high）确认selector/caller/环境声明/caller_paths修复，无新核心代码阻断；公开隐私有限扫描无私人路径/邮箱/凭据模式命中，catalog Herdr静态SHA一致。未运行原生宿主，也不将静态审查记为平台/并发验收通过。主代理对stable核心差异验收，基准最终写入及受影响检查继续推进。

HERDR-CORE-FINAL-01: `.venv/bin/python -m pytest -q tests/test_work_*.py tests/test_herdr_api.py tests/test_termcfg_herdr.py`（执行前展开排序），退出0，131 passed，2.23秒；私人执行原件SHA256 `b31ad2f9737e8c29e8972f2f0aa66d6088142a5924061e851bb2e07591da4dbc`。覆盖最终环境声明/caller_paths与脱敏修复；核心代码写入结束后的受影响回归通过。Review读取/扫描哨兵补强另有17项组合检查通过。

## Stable US6 handoff

executor（gpt-6.1-sol/medium）已停止写入；`.venv/bin/python -m pytest -q tests/test_herdr_benchmark.py tests/test_herdr_upgrade_policy.py tests/test_herdr_api.py`：63 passed，4.02秒；离线fixture validate退出0，py_compile/diff检查通过。完整负载、配对调度、producer时钟/barrier、policy判定路径已有隔离实现；没有实际执行完整原生循环。

主代理审查修复的判定边界包括：producer实例/两阶段/3batch完整性、partial矩阵不得完整通过、样本统计不得与原样本矛盾、client就绪/尺寸/有效规则身份/CPU完整性显式缺证门禁；先前已接受baseline收据与本次A测量分开，避免循环要求；runtime/full-stack一次采集AB/BA配对，共享paired_run_id/paired_schedule并核对冻结顺序与单调窗口；CLI/manifest/report授权审计标签必须一致。均不把标签当实际用户授权。

本后端明确限制：procfs轮询无法证明短命进程CPU完整性；PTY关闭/resize不等于原生detach/共享尺寸行为证明；规则/集成digest尚为声明值，未取得公开接口的有效身份导出。相应coverage保持false、必要证据unverified，不能输出性能/升级PASS；未扩权、未修改宿主，不用终端标题或最近日志猜会话。原生故障/上下文/冷恢复的完整正确性还需T027/T028/T051真实证据。

关联回归首轮的一项失败来自bench持续写入时固定runner摘要与fixture暂时不一致，门禁正确失败。executor在停止写入后已重新固定摘要，并在63项专项中确认原失败项通过；最终全关联回归另行记录，保留REGRESSION-01原失败收据。

最终核心源码delta（入口X_OK/execv失败固定5，新tab ready后commit前与focus后复查caller）已由scout只读复核，无新阻断；对应默认测试通过。额外controller/launcher并发测试关闭auto_ready/auto_accept后仅执行一次，不以自动fake握手代替双方逻辑；仍不证明原生PTY行为。

## Final acceptance of implementation scope

HERDR-FINAL-REGRESSION-02: `.venv/bin/python -m pytest -q tests/test_work_*.py tests/test_herdr_api.py tests/test_termcfg_*.py tests/test_herdr_benchmark.py tests/test_herdr_upgrade_policy.py tests/test_config_*.py`（执行前展开、去重排序）。**退出0，767 passed，249.58秒**。私人执行原件SHA256 `4dca550570c70b844816464d8f5f0aaff9bc86f4fd4e9f934f4e5cd85d607ea2`；包含实际argv/cwd/单调起止/退出及日志摘要，仓库外0700/0600存储。稳定源码后执行，未启动第三方宿主。原REGRESSION-01失败原件保留并标记已修复，不删除历史。

54个变更源码/schema/fixture/test文件的有序内容清单摘要：`283781529d552a0db29971f4c45617f2c059aedbe13d56e21e46d0ee9fde9714`；基础HEAD与target main仍为`93e4f7899725336c1180e53b4ec239eea5f984ce`。依赖uv.lock原始SHA256 `faf915d1bc6cf452fb0ecbc102996fecbbf2d33b9a3a844f7b2020eff81be3bc`，本次未改依赖锁/安装包。该摘要针对变更运行与测试文件，不对自身文档作循环摘要。

写入结束后的稳定检查：主代理审查核心恢复/端点/交接与bench判定，scout分别只读复核核心/最终delta/US6隐私和权限门禁，无新代码阻断；本地Markdown链接目标均存在；83个候选文件的有限私人账户/路径扫描无命中，scout凭据/邮箱模式扫描无命中；`git diff --check`退出0。保留上游Apache-2.0许可和tag/API来源；无宿主补丁、新daemon、终端库存、自动任务操作或新依赖。主工作树已有用户改动未触碰，未提交/合并/更新远端。

`speckit-analyze`实施后只读第1轮发现1项Medium：work-cli的对账接口名称与计划/任务/实现不一致。分析结束后按既有用户授权修订为workspace.list/get原生provenance；第2轮0问题，44需求/60唯一任务、覆盖100%、无宪章冲突/歧义/重复/遗漏。后续仅更新任务与证据元数据；最终只读复核仍为0问题，54完成/6保留且checklist无未勾项；正式收敛记录见implementation-review.md。`.specify/extensions.yml`不存在，before/after implement与analyze均无hooks。

| 未执行范围 | 授权/环境状态 | 任务状态 |
| --- | --- | --- |
| 原生Linux Herdr与配置/进程存活 | 未取得独立真实smoke授权，候选资产未安装；未连接真实server | T027 环境不足未验证 |
| SSH/桌面/手机/输入法/剪贴板 | 逐客户端组合待独立授权和人工行为证据 | T028 环境不足未验证 |
| Avalon/Pi/DSH/Codex/账号/模型 | 逐工具与账号调用待独立授权，未读取真实账号或会话 | T042 环境不足未验证 |
| 原生校准/首基线/AB | 未冻结已批准预算，缺必要测量身份/统计能力，未授权执行 | T051 环境不足未验证，无性能/升级PASS |
| canary/未来入口/三类回退 | 独立推广与回退授权未取得，未改变现有实例 | T052 环境不足未验证 |
| 可选状态启用 | 评估后全部关闭；全关核心隔离路径已通过 | T056隔离子范围完成，启用子范围环境不足未验证 |

实施范围已完成，不等于服务器主力入口迁移完成；54/60项已勾选，其余6项保留未执行/部分完成。默认测试、静态分析和有限扫描不能替代真实平台/客户端/账号/资源验收，也不宣称历史从无隐私信息。

## CPU backend continuation checks

`tests/test_herdr*.py`在CPU后端、固定50ms窗口、原件核验及六点斜率判据修订后188 passed（5.70秒，退出0）。运行前后runner/module/producer/report-schema摘要保持稳定；该快照runner SHA256 `36f7e8ef87b33793f18f28eebcb8a943337085f9681b66985b53d8268872fe02`。后续客户端reader和实际wall-second分母修订另行检查，不能复用该快照作为最终源码证据。完整user+system统计来自本轮kernel cpuacct，perf task-clock仍不替代CPU预算。

原生客户端尺寸核验发现0.9.5没有公开client list/outer-size查询；API focus不代表某个UI client已经接管tab geometry。新版固定record fixture从barrier等待期起响应严格nonce，回报实际PTY尺寸与阶段，不接收任意命令或保存任意输入；runner关联及原件核验实施中。Avalon初次180秒观察器未见分窗而超时，记录为人工等待超时，未据此判键位错误；保留原收据，在同一pane/同一buffer上仅恢复观察，未重新打开编辑器或发送按键。


## 实体 Avalon 补验完成（2026-10-19）

仅声明本机Linux服务端、官方Herdr0.9.5及macOS26.6.2/Ghostty1.3.1 stable客户端组合。原180秒观察和恢复观察的等待超时原件均保留，不改写成键位失败或通过。最终在同一固定无文件缓冲观察到两个Neovim普通窗口；用户按Ctrl+w h停留后按Ctrl+w l，后台只读RPC记录左窗、再右窗，未发送按键。显式执行`:normal! "+2yy`后，TextYankPost的operator_y/register_plus/linewise/fixed_two_lines四项均为true，用户确认本机可粘贴两行。普通clipboard选项仍为空、provider仍为Avalon copy-only，未读取本机或远端剪贴板，也未发送OSC52读取查询。直接输入双引号会触发当前Avalon寄存器提示，成功命令绕过了该映射，不宣称两种输入路径都通过。

固定样本及导航收据SHA256 `ebca2c6f8a8a20c53760721b7f77d76b3fc3577ec63b9d3b2a2d0a3282c9ad74`；完成后重新核对原Herdr端点、owned edit pane、固定缓冲与RPC socket身份，仅关闭本轮Avalon，清理收据 `5bb33d706a6a75a5b07b65caa21d20ae15bc7579d0df83330578187ffacce3a5`。后来出现的额外pane未分类，两个剩余pane和该测试server均保留，未自动关闭。T028按本轮声明组合完成，不扩展到手机或其他客户端。

## 基准工具续验收快照（2026-10-19）

executor按配置模型gpt-6.1-sol/medium完成CPU每MiB成本派生和私有原件重算：只使用同workload/mode/batch的measure实际字节，缺分母或不完整区间为null，不把标称输出量当分母。对应稳定快照runner为`d2733baef46bcdd163db9d8eead4f829f04134dced94753a51a01ece6bd2c18b`，measurement_tool为`af3fb2036d7bafe17d713084154fff9f9ca8fe3a157a461cc18977494b7b0d61`，全部Herdr默认隔离回归287 passed（7.65秒、退出0）。后续UI就绪和固定FD修订另行绑定新快照，不能沿用本次通过数。

用户已批准文档中的绝对预算及完整三批校准/首基线成本，审批记录摘要`26d43617164c87dd92955f3961f2626aec912495465f4c6c7ebb0fb9a319d25e`。新output-1诊断在CPU计量前被离线socket证明拒绝，未创建新性能基线；发现重复零额外FD检查与已登记cpuacct固定描述符存在冲突，修订保留首次零继承门禁与未知描述符拒绝。

双UI短探针保留初始空server假设、启动输入过早及异步resize旧尺寸的失败原件。诊断证明客户端raw mode之前发输入可能被初始化清空；resize之后立即采样可能仍得到上一尺寸。等待启动并排空resize事件后，四帧几何与两尺寸原生输入通过，收据`85a2245709ad520834a906134e71a5b31db548df1b40d769f7afaaa958d4beea`；该诊断未计CPU，也不代替完整三批矩阵。新等待条件正在进入受管工具，最终快照须重新原生验证。


修订后稳定源的全部Herdr默认隔离回归为306 passed（7.40秒，退出0）；runner `5eb79433987cf823329dd2c0d94a1bac58364d880f3f974086666b936fef00b6`、cpuacct `9d517e6465ee9e697772e487335c51e9ad0b554aba2cfab1fee21dee3aba90f9`、geometry `4619c4a2003b45e4abbcbbf1fb9b0c3239fa79f096f0cd775e30a5c0eedc7719`，measurement_tool `57baf92784e078dfa02a9cd1061d0bef0a5c2beb36c0771bcf716c468128e615`；四个源文件前后摘要一致。短原生双UI最终复验100轮、200帧全部严格核对，两种outer/producer/native layout精确对应，官方server及自有对象完成清理；收据`a693cc0e168f42f0992d1549148525866e001bc72503a023465e8cace50a01d9`，源仍匹配。这是无CPU/无barrier的短探针，不能替代三batch完整窗口或attach 600样本矩阵。

排空后的长短探针曾观察到刚O_EXCL创建、尚未首次写入的安全0字节原件，引发JSONDecodeError；异常类别与长度记录保留。修订仅使该状态继续有界等待，不把非空坏JSON、权限变化或身份变化放行。T062的单窗口进程清理与T051全部长测后的管理员空组清理已明确分开，消除“前置任务须等后置长测结束”的依赖循环。


## 独立 CPU 窗口原语完成（2026-10-19）

绑定上述306项回归快照的新output-1:output/batch1完成60秒预热和300秒测量：301个内核快照、300区间、各端点及成员核验通过，`verify_cpu_original`与原件字节摘要均true。实际measure为153600行、19660800字节（18.75MiB）；server+helpers为20.251150719 core-seconds、按实际端点间隔约0.0675038291 cores，每MiB约1.08006137168 core-seconds。这只是一终端合成刷屏观察，不是30终端结果或合格基线。

操作退出0，CLI因明确partial报告返回5；报告保留invalid，`coverage.cpu_complete=false`表示缺完整矩阵，并不推翻其单独`cpu_windows[0].complete=true`。CPU原语收据SHA256 `c2de8eef6e68dd5dc51ef9b61281e11217912a62265c7ed7b45c37414743b7e6`；只读核对四个计量组均已空，不删除管理员组，留给T051长测。T062完成。

完整报告原件总核验仍为false：独立scout定位到`native-client`原件退出1与配方预期0不符，其他steps/socket/churn/client/origin门禁均通过。原因是测试直接关闭PTY或停止server时UI尚未正常detach。T063修订成功路径为先使用已验证managed C-x原生detach，确认UI退出0后才关闭PTY；不把预期改1、不篡改旧原件。此修订完成前不启动长校准。CPU原件单独通过不宣称整份报告或性能通过。


正常detach修订的隔离回归322 passed（8.58秒、退出0），runner `b85902ba39248daee1b0fa6ba9706cddca75925406d2833e5f8f41f96897448b`，geometry `f934f1a15d289a277b57cbbf4fb753fdd1c8825eaef26d3c78b385f033500adc`。随后原生v10短探针的60帧双UI及两个C-x+d均通过、UI退出均0；第一fresh attach在raw mode后立即发nonce仍超时，旧收据`4fa58a4b770405adcf6930a3d6306f4e376a73f8600e6b0e900ea84757b84eef`保留，不记整体通过。raw不等于完成初始化；正在增加与run绑定的固定首帧marker等待，首次nonce仍须成功，不重试或放宽计时。尚未核实“首帧后上游不再query”的内部因果，不将其记为上游确认缺陷；以新受控原生首次输入为验收依据。长校准未启动，marker修订须重新冻结fixture身份。


## 固定首帧与正常detach最终短原生复验（2026-10-19）

修订后源冻结：runner `fa672d505749b20c4dbe31396f78277ecc096e5560b3af30b8a362c1b0aa0c4c`、geometry `1059f21905075e5fffa0e89eb70d8dd5d9724587e22c70ecbd9b8787e70e8d4a`、producer `aaaeeeb6061e05d06339016a2d7b094883e227061137d135b7ff9d4f92fc3bda`，cpuacct仍为`9d517e6465ee9e697772e487335c51e9ad0b554aba2cfab1fee21dee3aba90f9`。executor默认隔离回归351 passed（7.47秒、退出0），四源前后稳定。fixture摘要更新为`15a7d5bd2adf69fe49bd6e41b83287a2b0c5ccc910db43679eb15441e5282bd4`，measurement_tool为`0de5bfe709b1e8c1005be0ad77ed620b444412eddb23908b55f82b16e6a87670`；公共policy仍未批准/null，没有改expected_exit或任何验收门禁。

新隔离实例双UI30轮共60帧严格匹配，随后10次fresh attach均在首帧marker后首个nonce成功；12次marker等待及12个原生C-x+d退出码均0。server及全部本轮对象完成正常清理，源仍匹配。收据SHA256 `af2435b70db8b62122417c133a58888a9bfc3a576d33ad1822447c66316290be`。marker匹配仅是启动条件，nonce仍为端到端输入证明；不依据本结果断言上游初始化内部因果。T063完成，完整三batch、600 attach样本与长静置仍归T051。

新完整校准清单按上述源与已批准绝对预算重新准备，准备收据`b5ed22f5208c9f2b18f60ddce48c4851d3aca5753f31ed64ec75e0ef7aa77dec`，尚未开始其固定性能窗口。当前61/63完成，仅T051校准/首基线/管理员最终清理及T052后续canary/入口/回退保留。旧失败探针的测试server清理正在只读分类；默认工具沙箱PID视图不能替代host视图，未根据沙箱中PID不可见就声称host已退出。


## 完整三批校准首次启动（历史启动状态，随后提前失败）

按用户已批准预算，使用新的私有HOME、独立server、固定offline-sockets门禁及本轮cpuacct委派运行完整校准，无case/batch缩减。开始收据SHA256 `afbe2d999445f9bd7653257a19b616b66ac9fbc51c0c5eb96615c168114e33b4`，绑定准备收据`b5ed22f5208c9f2b18f60ddce48c4851d3aca5753f31ed64ec75e0ef7aa77dec`。host视图只读核对父PID/starttime仍匹配，driver/server/client/producer各有1名活跃成员，已写12份私有执行原件；这确认测试开始，不代表完整CPU矩阵或通过。固定窗口下限18492秒（5小时8分12秒），另加准备和操作采样；A/A报告与pending policy尚未生成。此前“仅准备”的段落是该启动之前的状态，不用于判断当前运行。

T051保持未勾选：校准完毕仍须核对全部原件和三batch覆盖、审阅并批准独立噪声policy，再执行首基线和compare；管理员组在全部基准结束后清理。T052须在前置结果成立后继续独立canary及回退/未来入口选择，不因长测启动而完成。既有tmux/Herdr任务及生产入口未改变。

## 完整校准首轮提前失败与诊断边界（2026-10-19）

该完整命令约368.359秒后提前退出，CLI与operation均为5，A/A报告保持invalid/measured，不能作为完整校准或基线。报告字节SHA256 `784610671014dfc47099dde8805510c47435f5dc694a419e4cc11a4d2649871c`，生成的pending policy摘要`779bd48a65bdc4629d9cd6e4e8a236bc8dd2d751c525cfa931caf53440291625`未批准、未冻结，不采用其噪声值。

batch1 idle-1完成60秒预热与300秒测量，12条执行原件均exit0，301快照CPU原件核验通过，正常detach/server退出0。idle-10仅完成offline-sockets proof，在首个version/新UI/producer/CPU步骤前失败。冻结runner/measurement_tool/fixture与准备收据全部匹配。原catch没有保存具体异常类别/reason，现存原件无法区分成员身份竞态与discovery路径错误；不据猜测增加重试或放宽身份。私有只读诊断摘要`a7003428362fffd5cd888c9166d470a053fe2882f0e1dab8eb74587fc8e918ab`。host视图随后按原收据身份核对四组均0，不把工具默认“环境不足未验证”标签当作已证实的环境原因；当前为失败待定位。

Root另清理此前六个失败短探针留下的空server：scout按固定PID/exe/原argv及private socket权限只读核对，官方CLI的result.workspaces与result.panes确为各0，未读取pane正文。Root再次固定O_PATH socket与PID/starttime，确认零对象后仅调用官方server stop，六个均停止；清理收据`61ae8275c5d06c962a82827af525bd68902ee06d015faaa10880dd7f91486b31`。前两次前置拒绝因多传CLI不支持的--json参数，0停止，原收据保留；修正为已核实参数后成功。未知pane所在的人机Avalon测试server仍保留，不在此清理范围。

随后给本仓库benchmark增加固定阶段/异常类别及严格白名单reason的私有诊断，不记录异常正文/环境/终端内容；测量、预算、退出码与不确定结果保留语义不变。修订后重新冻结并复现边界，T051/T052继续未勾选。

## 失败诊断封印与第二轮完整复测（随后复现边界失败）

executor（gpt-6.1-sol/medium）仅修改本仓库runner及关联测试，Root审阅固定phase、有限reason白名单、私有新文件原子落盘、摘要引用及诊断写入失败不掩盖原exit的路径。默认Herdr隔离回归368 passed（7.91秒，exit0），四源前后稳定；runner为`e0c3679632826a8319d96c4a2bb850da254ddd338e38c18ba9d4b25a32fa17a2`，measurement_tool为`6717abf2660e29cd55fc7245a5e134ab7f814024739fcfb7eb7e39e3e7b06f89`，manifest为`c4c635f047aa2a5f2a3d3b7ad1f58eec72055407ae10e9f90906635a3cc0fbfb`；fixture/policy及绝对预算未变。旧7项fixture身份失败保留，更新必要封印后回归通过，不把旧失败记作功能通过。

首轮pointer及所有原件保留；新HOME和新合成case根重新准备，准备收据`f5237f3db0cc170af8f5aa6c8aedd798d1d7f6fd58a1304c63f85abfc9a00548`、启动收据`18650d982d92d0410daf2134c1715c291fc576d58367f0d562fc933ec6848fba`。新命令仍为完整三batch，没有case/batch过滤或缩短固定窗口；其启动不证明首轮故障已修复，也不作为校准或首基线通过。等待边界复现及全部原件结果，T051/T052继续未勾选。

第二轮同样在idle-1→idle-10边界退出5，报告invalid原件`2a21c50a6d951982e5c4894b97ea1176a16e347fa3e472fb9fbbd4921da3aba3`，pending policy `e29a5cb43d51ee62bc4e5f10bdad5196803af50febbd24ae557ce67cb389279e`仍未批准。新私有失败原件摘要`9742d89b16717eb737390d3897096e59f6416372299d8df9eb1e6432ca647f44`与引用一致，phase=cpuacct-members、category=cpuacct、reason_code=cpuacct_member_identity；发生于下一case启动前。Root据此修订自有case正常停止后的等空顺序，不再以猜测discover错误作为当前诊断。

当时拟新增的等待只在前一case server.wait已正常返回之后执行，最多5秒等待server/client/producer为空，异常立即失败，保留下一case严格成员核验。初版仍使用原固定cgroup.procs读取；随后的原生探针发现旧FD缓存，因而不能把初版等待当作有效修复。最终fresh读取及原语复验单列如下。

## 成员快照缓存修订、原生原语复验及第三轮完整校准（2026-10-19）

Root两个原生等空探针在driver身份断言失败，观察到驱动已迁入driver组但旧FD仍读到空列表。独立新鲜度探针摘要`aae3140d6c424415194c1553456c67714840f565094682efda59cd1a61f1f6fe`：当前cgroup身份正确，旧FD pread及lseek/read均0，新开相同dev/ino只读FD为1，随后旧FD也更新为1。scout（gpt-6-luna/high）只读核对[Linux 5.10.134 cgroup-v1 pidlist实现](https://github.com/gregkh/linux/blob/v5.10.134/kernel/cgroup/cgroup-v1.c)，per-open context可重用共享pidlist，新open首次读取会重新加载；[seq_file读取/seek](https://github.com/torvalds/linux/blob/v5.10/fs/seq_file.c)只重置迭代器，不清该context。实际probe与该机制吻合，不以upstream tag替代供应商内核验证。

executor（gpt-6.1-sol/medium）统一members/wait为每次受检fresh只读FD，原18持久FD、计数路径、自迁移及descriptor白名单不变；完整读至EOF、总量上限、读前后身份/权限/文件系统、finally关闭及随后逐PID/starttime核验均有反例覆盖。Root审阅后原生12轮fork后代自然退出/driver保持/目标归零通过，短超时仍拒绝；逐轮18FD审计亦通过，原件摘要`401fd34c175b32f7d45b9cfc4a4d260ab31fe705ac348497a11955e45e48a699`（前一次未加逐轮FD审计的成功原件`fd4ddfc217cee6795073c9e5e99dd0fc86a8933d14995b8e0e75ec9e2bd21c24`保留）。没有终止或迁移外部进程，这只是统计/清理原语验证，不是完整Herdr基线。

当前冻结源：runner `87f1b0ef5485091df0f38cb09d808b525c2571bddabd8a432fcf0860f4796f03`、cpuacct `f119d650d7d73ff2bc09b62cf189e2e79c7fc92e6b55029845dff3d4cea1b5df`，geometry/producer保持`1059f21905075e5fffa0e89eb70d8dd5d9724587e22c70ecbd9b8787e70e8d4a`/`aaaeeeb6061e05d06339016a2d7b094883e227061137d135b7ff9d4f92fc3bda`。全部Herdr默认隔离回归401 passed（9.78秒，exit0），四源前后稳定；measurement_tool `8cd0209bec9fa0e07369b4ea8897e24fcc12d23890a600e8873b1d1af279e9f0`、manifest `9dea000156320880726fdc0930d591ed507b01c7f18b3e2a9de697cfdfbcdb14`，fixture/policy/预算未变。旧失败/RED与身份封印失败均保留。

前两轮pointer与原件保留；第三轮新HOME/新case根准备收据`c89efbbebf47309925e6268bdd76486fb13db0cf4311ee42f014c850fe749532`，完整启动收据`789f014159293ef105683751fc73534fadca2b2d589417793ae62a791c5f2584`。没有case/batch过滤或缩短固定窗口；启动时仍须实际越过旧边界并完成全部三batch、原件核验及policy审阅，不能把401项fake和12轮原语PASS当作完整性能通过。T051/T052继续未勾选。

约399.9秒时，host只读复核原启动PID/starttime仍匹配：idle-1已具有完整warmup/measure控制结果；idle-10已有10份producer ready及warmup阶段文件，证明第三轮实际越过前两轮失败的首个case边界。进度原件摘要`ff8a5b8d0d25da2307a32ecb441a950fa7498475110ecc88ce730df782d3da7b`；没有最终A/A报告。这只确认该边界已过，完整校准、噪声policy批准、首基线/compare及最终管理员空组清理仍由T051跟踪。

## 继续执行时的原件抽查与首基线衔接准备（2026-10-19）

用户要求继续。Root按speckit-implement前提检查单次成功，requirements checklist 16/16，未配置extensions/hooks；未重跑已通过的401项隔离检查，也未修改冻结源码。scout（gpt-6-luna/high）在host视图只读核对原parent PID/starttime与manifest/fixture/runner/measurement-tool/source/prepared六类摘要匹配。首次续执行快照前五个case的ready/warmup/measure逐实例标记齐全；output-30的30实例就绪，但采样期间阶段推进，未据此宣称该case完成。进度收据`23f882a9e697def0eea97d8c3017224e895e1dca94c0cd1e3fa0d53e351d7ef5`，当时无最终A/A报告。

Root另对当时已落盘的前五个CPU窗口做只读抽查：各有301快照，首尾固定窗口与成员身份匹配，模块/subject摘要一致；以下只列server+helpers，均在原1核/300 core-seconds绝对预算内。该抽查没有最终report的测量行、RSS/延迟/完整三批核验，不能代替verify_originals或性能接受。私有抽查收据`223d635b067d22bc7b0d23855496d1e541a8cdade8841bbb03cef1c90abbe212`。

| batch 1 case | core-seconds | 平均cores |
| --- | --- | --- |
| idle-1 | 0.4053 | 0.00135 |
| idle-10 | 1.9605 | 0.00654 |
| idle-30 | 5.6255 | 0.01875 |
| output-1 | 18.8545 | 0.06285 |
| output-10 | 47.9149 | 0.15972 |

executor（gpt-6.1-sol/medium）只读核对首基线衔接：preflight要求isolation.root不存在；verify_calibrations重算保存的report/policy并从private_record_root核验执行/CPU/client/churn/origin原件，不读取旧checkout/control/socket；argv归一化只按冻结manifest字符串映射，records允许非空。Root选择同manifest衔接，待校准结束且全部自有进程/四组归零后完整归档owned合成树，保持manifest目录、records/sentinel/argv不变，重验校准原件，再以同冻结路径新树运行首基线。实际归档、policy批准、首基线及compare均尚未执行，不能提前记PASS。文档已补该条件流程，不新增manifest桥或放宽核验。

## 第三轮output-30失败与原子发布修订（2026-10-19）

第三轮完整校准已经结束，CLI及operation退出4，报告invalid/measured；报告SHA256 `5233f8bfcb9d07d817eb12210c4f8891ec055f885b6a3d988d93ac19f6fd41a5`。195个步骤、6个CPU窗口、零完整batch，不能作为校准或首基线。output-30最初30实例就绪，测量前后仅29个producer、29份measure计数；缺失实例的固定failure为measure/unsafe_file。完整性失败不是Herdr性能结论，也未归因为环境不足。前五个已结束窗口的局部观察不改变整轮invalid。

源级复核发现runner通过hard link发布后才删除临时名，在此间final的nlink为2，严格fixture reader会拒绝；fixture自己的直接O_EXCL写入也可能暴露未完成JSON。当前修订方向为临时文件完整写入/fsync后以Linux renameat2(RENAME_NOREPLACE)发布，首次可见即完整单链接；保留uid/mode/nlink及形状检查，缺公开原子能力直接失败，不fallback、不覆盖已有目标。修复和测试结果另行绑定新source/fixture快照。

scout在登记server PID/starttime仍匹配时保全唯一failure及顶层measure barrier，源均当前uid、0600、nlink1、run_id匹配：副本SHA256分别`1172710001f3f5d262cddb504c60945f7dac59f8a05cbaf968a9756aef989743`、`799b2ab2380819a798ca1ac1832ce544e489fed2dea932a2ff2adaab8579351f`，保全收据`22c5f1df24592136818a04289975718808bac767c0cd00cd8abbd0955f506174`。四份旧source在修改前保全，收据`c7f3dc648b7fd40fa741e720f8a946e31d9dab59903adeae20c445b191cd6d6f`。

本轮专用postflight仅生成eligible_for_policy_review=false、approval_granted=false、baseline_established=false的私有审阅包（SHA256 `3c2ea0060859dabb804cccb3a0025d12302a332608703c2d7765e22ac61a160b`），没有批准policy、启动首基线或归档隔离根。此前准备的postflight和首基线衔接argv绑定旧快照，后续新source不得复用为有效执行授权。T051/T052仍未勾选，生产入口未改变。

原子发布修订的executor（gpt-6.1-sol/medium）先复现两项旧竞态RED，再以34项针对性检查验证首次可见完整/单链接、并发仅一胜、已有文件及symlink不覆盖、不支持拒绝、fsync失败后final保留、FD关闭及固定原因映射。更新合成fixture封印后，`.venv/bin/python -m pytest -q tests/test_herdr_*.py` **435 passed，10.00秒，退出0**；四源前后一致。此前合跑123通过/7旧封印失败保留日志，不把跳过结果当最终通过。

新source SHA256：runner `581f86c498f6464afeda6b03be94423a90a555df4620c8af578a13608d5e7806`、producer `fa06f6b9f17dc89a2a4622cc1fa20830723716f525eeb2adcbca5b0e1ec6dfd5`；cpuacct `f119d650d7d73ff2bc09b62cf189e2e79c7fc92e6b55029845dff3d4cea1b5df`、geometry `1059f21905075e5fffa0e89eb70d8dd5d9724587e22c70ecbd9b8787e70e8d4a`未改。fixture摘要`6fd245f716d9ee703746597c1207c839cc516a89a6520137820b990bba6bc3de`、measurement_tool摘要`1c90cfdc82727e90f294a69e3eb33aab3bbb3581d14541ba3b191fc1de4864e1`。公开合成manifest/policy sealed digest分别`71659487668b2fe3a0641b5fd8a7c7fbcf5d33a88574ed46c1cb135d2dc0236e`、`ce0c6a92f5f6a8b10771e21f7ac01cad88f92997e7ca6be571eaa154e9a2267a`；公开policy仍未批准、未冻结、校准引用为空。

Root另在本机实际tmpfs case与private-record文件系统上分别对两writer执行32次完整发布及EEXIST不覆盖，共128次，严格reader均读到完整0600/nlink1文件；只清理新建自有探针目录，没有启动Herdr。收据SHA256 `2d8ed98716f69d95da8577979d9801be0506ece8fe01bdfd91a7980f26d41c32`。该能力检查和435项隔离回归不能替代output-30及完整矩阵复验。

第三轮受管清理前，scout确认27个现有pane均为原30条ID三元组的subset。Root进一步逐一核对27个实际producer的PID/starttime、exe/固定argv及synthetic cwd，专属socket固定、1个workspace、无未知对象，且cgroup成员集合完全一致；清单收据`1c42a12a0e9c640ab41fa30c265d5ae0b709a8bc42d27d5ed01e9b3446bcc4b6`。随后官方server stop退出0，但一次性清理记录器把纯文本成功输出按JSON解码而失败；该错误保留，不据其缺少final receipt声称自动清理通过。独立后验确认原server及30个producer身份全已消失，下一轮冻结启动器的四组fresh members为空门禁也通过；后验收据`cf1748f4dcd3a532a6d5315989309d69872d5fa9df9c5ea74f7563c20d9449e9`。没有触碰另一个带未知人工pane的Avalon测试server或旧工作会话。

新的output-30诊断使用新HOME/server/root和修后source，仍执行完整60秒warmup+300秒measure，固定batch1与offline-sockets/cpuacct门禁；它是显式partial，不能成为首基线。准备/开始收据分别`1d1ff88ed94e20a16090d2c872310aadd056e93664fe01cccd56ccc532c9a4ca`、`91b3d0664c12bb160a085469e6f60cad43d3260bf00d3b42a31f0f98ac419394`。全量三batch新清单已另外准备，收据`e9698a6954355b52b5f385dec33454ca0447ce87816585ef3e5aa410317d955a`；不与当前诊断同时运行，后续须先核对诊断完整结果及四组为空。

冻结source后的公开审计覆盖109文件，隐私扫描零命中、git diff检查0，只有此前正式再生的5个Pi锁变化，uv.lock未改；79文件source清单摘要`1450571a38c18fcbefa911e57565cfcb0a5024bae0f6bae032847046797df787`，审计收据`263ba6676a888ab4fe1e5dac67e75a8f73b8961beac9e13dd455bd9db7a35714`。该审计早于本段状态元数据写入，source清单保持一致。

## 原子发布修后output-30复验结束与完整校准重启

诊断已结束：70步骤全部退出0，operation=0，CLI=5，report仍invalid，明确包含explicit_partial_measurement、shared_dimensions_not_proven、client_ready_not_proven。这个output-only场景没有执行专门UI证明，不删除这些缺证，也不提升为基线。Root第一次一次性后验断言仅预期partial理由、漏列未测UI理由而失败；纠正诊断范围预期后重新核对，报告内容和门槛未改。报告SHA256 `d9cada72dc200555a2a3f5224751210b7e1e5b20bd875265b63bb9c030a01b47`，结束收据`11bbe09309cb5223f8150d00448ebeb5c005e6d047ef40ff6a14c8d640a1c865`。

30份warmup及30份measure计数全部精确：各实例每秒512行、每行128字节，完整60/300秒；CPU单窗口complete、301快照，测量前后30个producer PID/start身份一致。全部私有原件verify_originals=true，client正常退出0，source与冻结输入前后一致，结束后四组fresh members均为空。后验收据`b09e471bc20d83ac4e29f1fdeeda8064f742c8dc352b0bc7e0709d2fb3ed6c82`。这证明本次output-30发布路径和窗口计量复验完成，不证明完整矩阵、校准噪声、首基线或新fixture全套UI通过。

随后按原已批准预算启动新的完整三batch校准，无case/batch缩减、无incomplete CPU选项；使用新私有HOME/root、同一稳定Herdr0.9.5与修后四源快照，保留此前所有失败轮。准备/开始收据SHA256分别`e9698a6954355b52b5f385dec33454ca0447ce87816585ef3e5aa410317d955a`、`3ec9e6e1001d22a0c41140a7725b7ecd60ef5174203d29fc0fe766f3e7c591ea`。启动器先拒绝已有log/started/finished，再核对四组为空；Popen成功后即使started写入失败仍等待原Popen，不发信号或重试覆盖；该生命周期由executor只读复核。当前完整报告尚未生成，固定窗口下限仍18492秒，首基线没有开始。

仅供这轮使用的有限postflight已通过--check：source/prepared/started/manifest/policy/delegation与driver身份均匹配，并已实际启动等待该固定PID结束；之后只读校验完整性和原件，生成新的私有审阅包。postflight源SHA256 `eed2ee18f9f0266efb81497103f7f2663b263847cdb8f027080e64fa1f082418`，启动器`87621e981a43b2c69faaca87ba035569a2cf2720aecc9156d2b18d93e972c831`。等待器不批准policy、不归档根、不运行首基线、不控制server；尚无审阅包结果。T051/T052继续未勾选，生产入口与旧任务保持原状态。

## 完整校准早期进度与后续执行准备

本次继续仅进行只读证据核验和新私有执行计划准备，不修改冻结source、不并行启动其他宿主或回归负载。calibration及有限postflight均仍运行，尚无完整报告或审阅包。scout（gpt-6-luna/high）核对登记driver PID/starttime匹配，首批idle-1、idle-10的ready/warmup/measure/failure分别为1/1/1/0、10/10/10/0；当前idle-30为30/30/0/0。前两份cpuacct-v1原件各301快照、约300秒窗口，producer before/after分别1/1、10/10，与control的预期数量及run_id匹配。新私有进度收据0600、SHA256 `4f5219b9b0c9c555c961d9704c2995a460f41e584be47a30e73fbfcbd10ab4e4`；这只是已结束窗口的结构进度，不是完整校准或预算通过。

Root通过本轮postflight的严格load_context/recheck再次核对完整prepared/started、source与manifest/policy绑定，并把首基线run（20项argv）及compare（12项argv）写入全新私有计划；收据SHA256 `b35d58df26b752d6b0bea86cb982b7fa925fa7bde2091bc2600ca275e96a82b8`。计划保持相同冻结manifest目录，要求有效完整校准及原件、独立噪声policy审阅批准、driver结束/四空组、整个已知自有隔离根同文件系统无覆盖归档、归档后原件再验及冻结身份不变。它没有批准policy、归档根或启动基线；旧失败epoch的衔接计划不得复用。

executor（gpt-6.1-sol/medium）只读盘点T052：配置rollback/reapply与同socket保持收据`911c4a373ecb7c50f45a500f55635266629d5313b04c8f35ed1276a72b736b12`、旧0.8能力拒绝/恢复候选选择及合成状态保护复制收据`173896b8ca9742a8ba6c75a845dba4f685b22309aa3e68c5a41d384b6702f076`可在身份仍适用时复用。复制三份状态文件不证明旧程序能读新版state；独立新工作canary、状态兼容或不兼容停止结论、SC-009联审及未来入口仍待T051完整首基线/compare后执行。常规隔离操作沿用用户已给授权，不以缺少重复授权为停工理由。T051/T052仍未勾选，61/63状态不变。

## 完整校准越过output-30旧失败边界

本次继续保持四源/fixture冻结，未并行运行其他宿主或默认回归；沿当前完整命令观察到首批idle-1、idle-10、idle-30、output-1、output-10、output-30的control结果依次写齐且无固定failure。该进度不代表全部33 CPU窗口、三batch、长静置、原生UI或性能预算完成；完整报告和postflight审阅包尚未生成。

scout（gpt-6-luna/high）先独立核对output-1/batch1：cpuacct-v1原件301快照、producer before/after各1且PID/start一致，ready/control run_id及phase匹配；warmup为30,720行/3,932,160字节，measure为153,600行/19,660,800字节。新私有收据0600、SHA256 `996e228137b502a9886e457b7c23f53731780cbf29e1d7bc88dd7b6687ff7a9b`，未检查完整性能预算。executor（gpt-6.1-sol/medium）独立只读审阅本轮首基线计划，确认prepared/started/manifest绑定、20/12项argv、同清单路径、无case/batch/incomplete CPU缩减、7前提门禁、新输出及未执行状态，0问题/source无漂移；没有执行该计划。

旧故障场景output-30/batch1在完整矩阵内结束后，scout核对control ready/warmup/measure/failure为30/30/30/0，全部30份warmup及30份measure均满足上述60/300秒计数，run_id、phase barrier及pane集合一致。CPU原件为cpuacct-v1、301快照，producer before/after均30且PID/start集合与ready匹配，300秒窗口和50ms端点容差通过；CPU原件SHA256 `1019c14861c246981b5d6bf16267471d047b48f12cc9bae6ed533fdaf1721da7`。只按原登记PID/start确认server及30个producer身份均已退出，未验证项0；收据SHA256 `03469ab1d31ddb4f1314fd2c1d4fcfaf816c6730252e912e275cf0045bf5c320`、0600。收据字段next_manifest_case_started列出已启动case集合，不能把该字段全部称为“下一项”；Root和scout的实际下一项均确认是projects-27/record，27个ready、尚未写warmup/measure结果。

该结果证明修订后完整校准已越过旧发布竞态及受管清理失败边界，没有复现unsafe_file；它不等于当前四组为空（下一case已经运行），也不等于整个校准、噪声policy批准或首基线通过。T051仍进行中，T052等待前置，61/63状态不变。

## 完整轮入口延迟超预算、受管停止与T064

projects-27的27份warmup/measure写齐后，运行器仍有各200次warm enter/reuse及重复/并发正确性步骤，不能仅据control不变判断挂起。scout只读核验最近5份warm_reuse执行原件结束时间持续前进、均退出0，耗时约2.21–3.52秒；projects-27 CPU原件301快照、27个producer before/after身份匹配，进度收据`22459e7dbd1c99cad928863979ababbb9e32082f87d755fe0432be1b8033fee5`。

Root按被冻结的1000ms绝对预算核对严格匹配配方的原件：warm enter 200/200均超预算，原件CLI时长p95=3714.818ms；当时warm reuse已47/47超预算，超过完整200样本p95允许的10个超额样本，后续补样也不可能达标。预算审计收据SHA256 `024802bfa164a9156c9166441c45727f4ff09d3ff3cf38908e4b9db9c34accf8`；没有放宽预算、删样本或归因为环境不足。

为修复真实性能失败，Root重新按CPU/producer原件、socket pin、27个pane/terminal/workspace及各PID/start/cwd/固定argv逐一分类，确认无未知pane后，仅用官方server stop停止本轮专用合成server。该操作使正在执行的CLI按失败退出，运行器正常保存partial report/pending policy；其中native-command-exit及native_operation_incomplete_objects_preserved是这次有意停止后的通用结果，不将其归因为Herdr自发故障。server与27个producer原身份全部退出、driver结束、四组fresh成员均0；受管停止收据`b74678efd14956bbda775e197f5a58f4265dbd97c4abb0e55fddd54c4a830b21`，结束收据`21e47b9c62f3c7cffde0c55ad88e22572462941d583712c134ec8f73e9d697a8`。未控制其他会话。

最终本轮报告invalid/failure、operation及CLI=5，零完整batch、7 CPU窗口、608步骤；报告SHA256 `53b7899016599f891d85ddacebad6a396fb24fae82e871b9d0aac4c02cb430a3`，其中已完成warm enter含焦点核验的200样本p95=3717.457ms。pending policy SHA256 `292832bb9b4bd7e72a18ff4162e4c2faeed722b30b8bb5278fc5083ee73d2ac1`保持未批准；postflight实际结束，审阅包`b3c7317b3f3175713ca26c9141ee220eb1fcd072b300a46915abf2eaa9e8d857`明确eligible_for_policy_review=false、approval=false、baseline=false。旧14份公开源码已在修改前保全为私有0600文件/0700目录，收据`4ee51e5ec4bf2cceca2ebf978e528628689d786748df26e7808de7e55217f35c`。

executor（gpt-6.1-sol/medium）仅作默认隔离纯Python profiling：work --help三次约0.214秒，首次load_public_catalog为1.745/2.056/2.902秒；cProfile指向完整sources/schema加载，CLI导入仅毫秒级。该合成read_settings在默认沙箱最终触及既有私有路径门禁而拒绝4，未放宽；catalog已在此之前完整执行，所以这是热点证据而非成功原生配置读取证明。Root据此批准T064最小改动：普通local沿同一严格load_local校验；仅明确需要adapter-schema的原生选项覆盖延迟加载原完整上下文，其余失败不转成功，秘密仍deferred，不新增缓存/daemon。新源码须先隔离回归、再做各200样本的projects-27原生复验，随后新epoch完整校准；此前435项及旧原生证据不能绑定成性能修后通过。

## T064严格配置延迟加载修订与新原生诊断

executor（gpt-6.1-sol/medium）完成两文件改动，Root审阅仅对明确adapter-schema错误延迟加载原完整catalog的分支；普通路径及回退均使用原严格load_local，回退重新执行私有权限校验，load_credentials=False不变。六项RED复现旧行为；默认工具视图中已有私有祖先owner门禁导致9项拒绝、10项通过，单独保留环境观察，没有放宽门禁或记为通过。随后在用户已授权的host文件系统视图执行相同离线、临时HOME/XDG、网络阻断/假宿主范围：配置27 passed（3.75秒），`tests/test_work_*.py tests/test_herdr_api.py tests/test_config_*.py`关联445 passed（265.48秒），均exit0。未运行真实Agent或读取认证。

源与测试执行前后固定：work_config SHA256 `447346a3c090f4ccbb72919978af2703bc930879760e0a70d3a0cecd8ec650a7`，test_work_config `fb72ee5e9d76de906a6720ab8f1d0cb4b9008e86ff0434ab300d385709ff5852`。五个fresh Python进程在新私有合成配置下成功，分别约503/412/525/519/506ms；收据`1d7162b2ec7e5bb92b9ed488cf355898d479d8f8074f1807fa83438ea98852d7`。该纯配置读数不作为原生完整命令p95。

新projects-27/record单batch诊断已在独立HOME/server/root启动，准备/开始收据`93f8c7f1970ef6fb2434166449877e2a5e448d703d6a5095270171c829ca3338`、`f151db407046bcc86b35bf0bc471dca0fd61e730c602b817537f5f9772429605`；measurement四源、fixture及原1000ms预算不变，启动前四组fresh为空。它将完整执行60秒warmup、300秒measure、各200次warm enter/reuse与重复/并发正确性，最终仍须保持partial invalid，不作校准/基线。当前未结束，T064/T051/T052均未勾选，61/64不变。此前完整轮及旧首基线计划绑定修前source，不能复用为新source性能通过。

## T064修后延迟达标、跨workspace收尾失败与T065

新projects-27单batch诊断已结束，400个入口样本全部exit0：含焦点核验的warm enter/reuse p95分别625.297594/695.189820ms，均低于原1000ms预算；CLI原件400/400无超额。100次重复和2/10并发的pane集合/零额外输入检查通过。但收尾先成功关闭同一workspace两个登记pane，第三个pane close退出1，报告operation=5、invalid/failure，零完整batch；不能把局部延迟通过记作T064完整原生通过。报告SHA256 `c03cc1bcdb72e698872f5e85a610136fdf2e74261719a4fa05589821f9115779`、结束收据`28738ebb63d265487af4834c9c3bf5aba1c67d78e4ec1588116d4225e25f817f`；固定failure原件SHA256 `939991e61c4881cc5293913a7a452ae0c27cb01928c302cc41fdb2926e0e6ca7`。Root的后验在operation=0/正常partial门禁处拒绝，未写通过收据。

scout（gpt-6-luna/high）核对固定v0.9.5官方源码：[最后pane关闭处理](https://github.com/herdrdev/herdr/blob/v0.9.5/src/app/api/panes.rs#L1966-L1987)在隐式workspace/group关闭需确认时返回confirmation_required；[CLI错误处理](https://github.com/herdrdev/herdr/blob/v0.9.5/src/cli.rs#L745-L752)据API error退出1。布局和观察相符，但本轮未保留该命令error body，不能断定实际错误码。Root不重试close、不关闭confirm_close；按新鲜pane/terminal/workspace、实际PID/start/cwd/固定argv及CPU组逐一分类，确认25个剩余对象均为原27集合、其余两个有成功close原件且无未知对象后，仅用官方server stop停止专用server。28个原登记server/producer身份均退出，四组fresh成员均0；收据`f50c0bbee37e5a2140d36f66ce82ac51c118cb189e816be5cd315cfda1b3883e`。其他会话未触碰。

新增T065采用更小的专用server收尾：重新核对全部owned三元组集合，无未知/缺失/替换/重复后一次官方server stop；不逐pane清空workspace，不放宽关闭确认或真实对象门禁。当前五源修改前保全收据`a9371b1acd1b5f0c26061c412a9bd8fbae74f4ea5ff5e4e1b7e8c8abb72bd874`。此前已准备但未启动的fastwork完整校准清单绑定旧runner，后续不能复用；须修后隔离回归、新source完整projects诊断，再新epoch全矩阵。T065/T064/T051/T052未完成，61/65。

## T065专用server收尾实现与新诊断启动

executor（gpt-6.1-sol/medium）只修改runner、关联测试和合成manifest的正式source/tool/seal字段；Root审阅后确认两个route fence之间fresh pane.list、全部owned三元组精确相等且非空、缺字段/空值/非字符串/重复pane或三元组均拒绝，仅一次官方server stop。其他case中的显式close生命周期不变；没有降低confirm_close或原件门禁。两项RED复现旧行为，聚焦32 passed；全部Herdr默认离线fake回归465 passed（11.59秒，exit0），无native/network，源前后一致。

runner SHA256 `f0171d00c55bedf50131751433f5280eb757c86ba426cd8151466bda2d6b3215`，test_herdr_benchmark `7785fceb4f02cd5750396cdcede264f63aafe164cf0084ec98a8a08e34a7b754`；measurement_tool `86b4ed730d432f1f166bb3dd5d78d90048e2a0c5b1a5b164ef8cdf6013179de4`，公开合成manifest seal `4e08406d9494d4e62e6c943e4e7aae20341a0641d65df22948ffd96a2d341712`。cpuacct/geometry/producer/fixture、T064 work_config和policy/预算未变。旧失败原件与旧私有执行清单均保留，不用于新source接受。

新owned-stop epoch的projects-27/record单batch准备/开始收据SHA256为`dae04e7c6a8fd90bfddc7b1ac633bd154181a7deb9099f03c093e19635a961f0`、`1e9a9f91274141ec85da4586106415740fcb472a8eb13e4abb7adc82ad0a4633`，启动前四组fresh为空；新HOME/root/server执行相同60+300秒及各200warm样本，当前仍运行，不视作正常收尾通过或完整基线。61/65、T065/T064/T051/T052未完成。

## T064/T065原生复验完成与新完整校准启动

新owned-stop projects-27/record单batch完整结束：各200个暖样本，warm enter p95=702.600337ms、warm reuse p95=700.565620ms，均低于被冻结的1000ms预算。各保留1个超1000ms样本，端到端max为1472.703/1161.424ms，没有删除或用最好批次代替；这符合预定p95评价而非逐样本上限。100次重复及2/10并发的pane集合/零额外输入检查通过。27份ready/warmup/measure齐全、failure=0，60/300秒完整；CPU单窗口complete、301快照，27个producer before/after PID/start相同。

全部原件verify_originals=true；client及server正常退出0，server与27producer原身份均退出、诊断结束时四组fresh members为0，source和冻结输入前后一致。报告SHA256 `b7ec47480973ae6f945ea6ed29f4263db28372f9cb34449c33efb7fa375511af`，结束收据`8abb15cc601c13e4165a55e2038b8c65ff241d8215eb8186f13c9ed1326c6c24`，CPU原件`04f5b550e4b91a2963265131ff731775385021cefffdf8c931f386814ad4765c`；严格后验收据`1b10c938281b3a519a6cc6fe514a32da0b27f78e1d38bb0c7664fda181dcdf94`。operation=0、CLI=5、report仍partial invalid，保留explicit_partial_measurement及未执行UI矩阵理由，不作为完整校准或基线。T064/T065据此完成，当前63/65；前两份性能/收尾失败报告仍保留。

之后启动新owned-stop epoch完整三batch校准，无case/batch过滤或incomplete CPU选项，未缩短固定窗口；准备/启动收据`11b2236002313e59a34e7d288f5f9ca50b4f88b81beec1f1402c596823192b0c`、`4a9b24349b99ba27fb18319cefa0fe0784755bd2fdb6605074b373b8360ac9cd`。使用新私有HOME/root，固定Herdr0.9.5及T064/T065修后source/measurement封印，原预算不变。启动器再次核对四组为空，当前新轮运行时计量组可活跃，不能把诊断结束的归零状态当作此刻空组。

专用于本轮的有限postflight已通过host --check并实际启动，固定prepared/started/源码/manifest/policy/delegation和driver PID/starttime；源SHA256 `6d5b6aac1d189aabf93d4a3a5240ff3cbe39936cb4a2de197719f1d495c51362`。完整校准结束后只核对33 CPU窗口、三batch、原生UI/producer/原件/绝对预算/四空组和proposal，生成新的私有审阅包；不批准policy、不归档根、不启动首基线或控制server。当前没有最终A/A报告，完整校准固定窗口下限仍18492秒；首基线/compare、canary及完整三类回退仍由T051/T052跟踪。

## 完整校准继续运行与T052执行准备

本次续执行先完成speckit-implement前提检查，requirements checklist为16/16，未配置extensions/hooks。Root以本轮固定context核对prepared/started、源码、manifest/policy、委派和uv.lock，登记driver PID/starttime仍匹配；完整A/A report及待审policy尚未生成。scout（gpt-6-luna/high）独立只读确认idle-1、idle-10、idle-30/batch1各有301个CPU快照及预期ready数量；后续Root合成control快照显示output-1的ready/warmup/measure写齐且failure=0，已进入output-10。这个进度不代表完整correctness/UI/33窗口/三batch或预算通过，T051/T052仍未完成，63/65保持。

executor（gpt-6.1-sol/medium）仅只读准备T052，使用原合成配置rollback与binary/state guard收据，不读取真实认证或会话，不运行宿主/测试/网络。新私有O_EXCL0600计划SHA256 `2b8c48c08abf5d573329e3822b731813d5690dc85b4d455c48912a0a2a0a792a`，Root已审阅5步：新工作身份与有效配置/规则、仅未来显式选择及binary guard、fresh plan-ID配置rollback/reapply、受保护状态回退停止、SC-009联审。计划绑定本epoch、首基线衔接计划与官方固定源码SHA/行号，所有执行/切换/完成状态仍false；不复用旧plan ID到新目标。

Root选择SC-009明确允许的compatibility_unproven_stop分支：逐项核对已登记合成结构状态原件/新副本的owner/mode/link/dev/inode及SHA前后不变，旧binary不在原件或副本上启动，记录compatibility_verified=false、rollback_stopped=true；这既不证明成功降级，也不声称已确认格式不兼容。snapshot version及拷贝成功本身均不能替代兼容证明。该计划须待T051完整校准、噪声policy审阅冻结、首基线/compare及四空组后再绑定新canary输入；没有提前试用、生产默认选择或状态恢复。真正未来默认入口仍在具体可逆选择的审阅范围内，本准备不修改全局入口或旧任务。

## 2026-10-20完整校准结束：单条预热输出少1行

完整owned-stop epoch已经结束，operation=0、CLI=5；结束收据SHA256 `3a0cd3c67abf29129cb29cd3ef4d184dd5592bd3b25f7b5530b29a368ccdcd82`，报告`c1b846a32c3064824f4ef320bc68cd86581bbe6133c66ccd50589167e661f7bc`，pending policy `4efc794af9324800f723bd16d01919b2867f4748dd44611ea5002f6d496c619d`。source与冻结输入均未变。3个batch、33个CPU窗口均完整，8661步骤全部exit0，所有correctness与required evidence通过；client ready/尺寸/版本、effective inputs、CPU覆盖及原件核验均通过，结束时四组fresh成员均0。

唯一报告invalid原因是producer_shortfall：1338条producer阶段记录中，detached-30/output/batch1的一个warmup实例为30,719行/3,932,032字节，比固定30,720行/3,932,160字节少1行/128字节；其余输出记录含全部measure均达标。没有修改、删去该记录或降低原定门槛，不能把本次报告作为合格校准。该缺口是实际测试负载完整性失败，不归因为环境不足；报告原reason=cpuacct_server_group_windows_pending、task_status=环境不足未验证是未更新的占位分类，33完整CPU窗口的实际证据不能被该旧文字否定，公开任务状态按真实producer_shortfall记为失败待决策。

有限postflight实际结束并输出新审阅包SHA256 `1df983ffc823fdfc0cd3fb38fb332bfe9bb5da321cd19bdcd19f8c181c4e66c9`，无脚本错误；complete windows/三batch/CPU/UI/isolation/correctness/原件/绝对预算/空组等门禁通过，但producer_complete/report_valid/calibration_references为false，eligible_for_policy_review=false、approval=false、baseline=false。全部绝对预算的over_limit_count为0；三个batch的warm enter/reuse p95最大分别582.705/662.051ms，new role p95最大1171.116ms，attach p95最大313.127ms，server+helpers平均核数最大0.508619，RSS slope最大46.802bytes/s。局部预算结果不覆盖整份invalid。

首基线和canary没有启动；T051/T052继续未勾选，当前63/65。保留全部原件和此前准备计划，不自动批准policy或把准备计划记作执行，不为消除此1行记录而改写结果。下一步须先判断预热输出不足的机制及可接受修订范围；本次状态核验没有修改受测源码或启动新一轮长测。

## 用户接受明确预热例外，T066开始复核

用户在获知一个预热实例少计1行/128字节（单实例目标约0.0033%）、正式测量计数完整且正式CPU窗口在预热结束约2.013秒后才开始后，回复继续，接受所建议的“保留原invalid、明确记录本次预热例外并继续后续”的范围。授权只覆盖该原报告和该实例；Root不修改冻结引擎/schema，不改变任何原计数或正式测量标准。新增T066仓库外一次性审阅器与隔离反例测试，先核对显式批准、原件/身份/非重叠窗口及其他全部门禁，再生成独立接受和冻结policy；目前尚未完成，63/66。

scout（gpt-6-luna/high）只读确认原run不验证calibration_refs即可执行已冻结policy的首基线测量；裸CLI compare仍会通过verify_calibrations拒绝该invalid校准引用。独立审阅器可以在严格核对明确例外后调用原公开Python compare的校准验证参数，无需monkeypatch或修改候选report；返回的schema合法comparison才可用于未来baseline acceptance，自定义review说明不能代替它。后续原生/归档/状态事务由Root处理，未提前启动首基线。
