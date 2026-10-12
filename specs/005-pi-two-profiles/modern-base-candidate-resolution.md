# Modern Base 原生产候选解析

2026-10-07，长期实施的开发依赖材料步骤。现代启动默认组件与 Base 唯一共享解析模块声明已分别验收；这一步要让原 `PiBackend(profile="pi-base").resolve_lock(repository)` 在独立源码副本中实际生成并读回 modern candidate。它使用未经修改的原 validator、resolver、npm lock-only 路径，不以合成 backend 代替本次实际解析。

## 输入与范围

当前声明是 `agents/pi/dependencies-modern.json`，38822B，SHA-256 `bd0b05262187390764af92b858e380eddc6ae2e57b1e867d6612bb64ccb40857`，只声明 `pi-base`。固定 `locks/pi-modern/manifest.json` 仍不存在。本次写入只发生在自有临时副本及私有证据目录，产物保留 candidate 状态；正式锁发布、部署、默认切换、Full 声明、原生 SDK/agent 启动各自另行实施和验收。

输入清单冻结 receipt 为 `.cache/pi-two-profiles/run-20261004/modern-base-source-input-pins-root-frozen-review01/root-review.json`，SHA-256 `24f4a297277b833cb78e812378dc9c88167fd8a3c932dca8eb08319ffdb194a2`。它记录2202个源码文件、230目录、48443604B，以及六份固定资产57611422B。root 在 writer STOP 后复核各源码的完整 hash/bytes/执行位、目录端点 stat、资产和固定 Node 完整 hash；这是本次候选输入集合，不签原子快照、恶意同 UID 防护或持续 sourcehold。

源码副本必须涵盖原 `recipe_digest` 的完整来源域：Pi声明/资源与原约定的树、所有所选 `src/agentcfg/*.py`/Pi脚本、profile、公共内容与五个所选 skill、原 schema、四个 local recipe。原顶层 `tests` 排除按相对路径执行；不能递归排除树内所有同名目录。缺失的可选 `agents/pi/profiles` 不创建。临时副本的 regular 文件使用0600/有执行位则0700，目录0700；保留原 `source_files` 判断执行位后规范化为0644/0755的摘要语义。无 live 源软硬链接。

固定 Node 原文件为 `/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node`，122466960B，SHA-256 `e237a2839d0cbdc9a9a2adda1a184afc0f5b20306ffbe923af5686550472d8a8`，复制到自有工具目录后再执行。npm11.19.1使用已接受的完整官方1943文件/460目录材料，receipt `b31b4f6226dcce8259e8bf91a8659d78e38af8de8e4782ce90bc086cf9414e57`；原 JS 字节保持，npm CLI 的 `../lib/cli.js` 相对位置保持。已核官方metadata/tar SHA1与SRI，不声称独立验证registry signatures。实际工具版本仍由这次原 resolver 的 `--version` 检查确认；nvm中11.9.0不能代替声明要求。

六份资产只按清单复制到副本的原固定位置：bwrap tar、build-record、Node tar、Meson wheel、bubblewrap source xz、libcap source xz。不执行或构建这些材料。原候选许可证路径允许 unresolved，这一步不能将尚未证明的 `proxy-agent-negotiate` 包级 MIT 正文或其它缺口记为已接受。

## 执行边界

执行器由唯一 executor 准备，另一 scout 独立审查边界，root 负责关键取舍与最终停止后的验收。执行前绑定最终执行器、全部输入和计划 pins；当前文档记录准备范围，实际执行尚未授权给子代理。开发工具的公开元数据获取与锁解析属于既有长期实施范围；它不启动 Pi、Codex 或其它第三方 agent 宿主，不读取真实账号、调用模型或部署，不复用此前原生 smoke 授权。

外层新建独占 `/tmp` 0700目录，在其中放源码、工具、HOME、XDG和缓存。producer 用固定仓库开发 venv 的依赖，从副本 `src` fresh import 原 PiBackend；记录自有模块的真实文件来源，不能 fallback live agentcfg。开发 venv/stdlib 是本步骤的开发环境，未因此取得已安装 controller/独立解释器闭包资格。

环境从显式 allowlist构建：PATH仅自有tools/bin（固定node与指向完整npm package/bin/npm-cli.js的内部相对入口链接）、自有HOME/XDG/TMPDIR；不添加系统Git/shell搜索目录，不继承NODE_OPTIONS、NODE_PATH、SSH代理、TMUX、账号/provider/model或npmrc配置。必要代理只有原公开网络校验接受的无凭据值。原 `npm_environment` 继续生成自有install-home和不存在的user/global rc位置、私有cache与IGNORE_SCRIPTS。该环境整理不等于OS沙箱或完整网络隔离，npm内部spawn不能由Python外层audit完全观察。

实际npm路径保留 `node --version`、`npm --version`、`npm install --package-lock-only --ignore-scripts --no-audit --no-fund`，以及仅缺SRI时的 `npm view <name>@<version> dist --json`。不执行 `npm ci`、安装脚本、SDK、agent或服务。不得替换原 `checked`/subprocess/validator为fixture；需要时只用审计观察器记录原subprocess argv和环境字段名，保留真实执行。原checked会隐藏成功命令输出并清理错误细节，完整外层stdout/stderr不冒充完整npm内部输出。

设置600s执行期限，另有明确有界shutdown grace，自有新进程组。空间以实际statvfs观测，至少保留384MiB，既知约240.7MB的源/工具/资产之外还需容纳output/cache；不承诺尚未测出的通用上界。超时/空间不足只终止自有组，等待确认；若不能确认退出，不清理活动树，保留证据并交root。不能终止其它活动实例或清理未知临时目录。

阶段审查发现leader已退出时原控制会跳过仍在同PGID的child。root选择Linux `waitid(P_PID, pid, WEXITED|WNOHANG|WNOWAIT)`观察终态，信号阶段之前不poll/wait/communicate回收leader；发送自有组TERM、有界grace/KILL后才回收。WNOWAIT保留可等待记录，尚未回收的zombie保留PID及退出信息；据此本执行器把向PGID发信号限制在leader仍未回收的阶段。启动前核SIGCHLD默认/兼容并无其它reaper，异常ECHILD按unknown处理。参见[Linux wait(2)](https://man7.org/linux/man-pages/man2/wait.2.html)。

回收后只有限观察该组是否不存在，不再向可能已复用的数字PGID发信号。zombie本身仍可使组存在；signal返回成功只表示至少一个成员接收，不能当整个组退出证明。非空/权限错误/未知状态保留临时树并交root；逃离原组的后代没有本包停止资格。参见[Linux kill(2)](https://man7.org/linux/man-pages/man2/kill.2.html)。

## 验收与记录

原recipe摘要、runtime声明、schema/分辨率/资源与binding校验、candidate写入、manifest最后发布和read_lock必须真正运行并分别观察。候选状态和原门保持；这不代替正式发布事务、并发、崩溃恢复、安装/current、来源/授权或产品资格。

每次记录实际argv、环境字段名、UTC、UID/EUID/GID、退出码、deadline/空间观测、来源/工具首末pins、完整外层日志和实际候选产物。失败和部分产物也保存，不改成not-run或删除历史。自有进程结束后先复制证据到新私有目录，核对完整源/目的产物字节和metadata，再仅清理该次自有临时树，保存清理结果。

当前阶段：输入pin集已冻结，执行器与独立审查准备中，实际resolver未执行。完成后root验最终稳定脚本/diff、命令观察、原readback与产物pins，决定后续正式锁/安装步骤。任务四状态持续分列；formal7/100、所有产品gate以及strict输入计量未验前AUTO OFF保持。

## 首轮实际材料准备与工具入口增量

execution01在2026-10-07T13:42:35.544–13:42:37.555 UTC实际wrapper1，child_exit=null，producer/Node/npm/resolver尚未启动。官方包原有package/bin/npm（2073B、bash安装shim），执行器再次O_EXCL创建同路径触FileExistsError；这是自有工具准备错误。冲突前复制的六份锁输入及其清单已保留，保存标记先于清理标记，自有临时根实际已删除；该部分材料不是resolver产物。35输入原冻结与脚本首末pins保持，原失败永久保留。

root限定修复：完整1943官方树不覆盖或删除任何行，另建tools/bin/node与自有tools/bin/npm相对链接../package/bin/npm-cli.js；目标严格解析、字节/hash/执行位核验，原CLI的../lib位置保持。这个自有alias不签nofollow，源码和资产nofollow读取保持。只改执行器工具布局block，逆回完整旧20419B/ed779相等；producer、WNOWAIT/保存/清理和七项fake控制保持，不重跑无关控制。新20959B/f11a90f08667f2c282a69ee820611f2774a9394325fd072b2c9e4dc2935c9939已STOP，AST/compile通过，执行02待root最终限定确认。

## 第二轮实际失败与有界诊断增量

execution02于2026-10-07T13:53:13.039343–13:54:03.090022 UTC实际运行，inner/wrapper均1。原Node/npm版本检查由执行到lock-only的控制流确认通过，原成功stdout未暴露；实际audit仅三次Popen：node --version、npm --version与npm install --package-lock-only --ignore-scripts --no-audit --no-fund。随后原pi_license_bundle.validate_source在allow_unresolved=True下返回pi-license-bundle-invalid，没有成功candidate、原read_lock或producer-result。上文的尚未执行/待确认属于当时准备状态。

自有组在leader仍未回收阶段发送TERM/KILL，随后回收并观察empty，保存先于自有TMP清理；最小空间991395840B，高于384MiB预留。源2202+六资产和固定Node委派后验pins一致，不签完整其它锁树、原子快照或sourcehold。原TemporaryDirectory已清理生成lock，外层保存543个Node compile-cache节点（541文件/1398828B）；旧provisional文档把TMP称空的描述由final-agent-result纠正，原工件保留。

八份固定license文件与28条引用存在且摘要匹配，目前不能归因为材料缺失或graph drift。本轮失败root有限记录receipt为79d57cc587f5373a63f10aa7d98255496699aca9d0efc0bcfd509f5edc6cc408。

root已限定下一诊断：只改自有producer/新诊断helper，在公开sys.addaudithook的shutil.rmtree(path, dir_fd)事件中，于原清理前捕获本次私有TMPDIR直接子目录agentcfg-pi-lock-*中的pi-base/package.json及package-lock.json。锚定目录fd、O_NOFOLLOW、regular单link、16MiB单文件/32MiB总量、独占0600证据文件/hash读回；拒绝其它目录与所有链接，不递归读取缓存。诊断异常不得替代原ConfigError或阻止清理。原resolver/validator/checked及executor保持，先默认有界测试、STOP稳定独立审查与root冻结，再只运行有明确诊断目标的execution03；本记录时未授予子代理实际执行。原基础pair与最终摘要pair的字节关系另按原调用点核对，不把path关系冒充byte证据。公开事件定义见[Python3.11 shutil.rmtree](https://docs.python.org/3.11/library/shutil.html#shutil.rmtree)。

2026-10-07 诊断增量STOP稳定验收：producer10163B/a777812c，executor20959B/f11a不变；root完整逆回原2581B/7ed相等，exact diff相等，完整实现/测试已读。原conftest显式plugin默认21项由public audit与真实rmtree执行，tests02一次21pass/0.31s，tests01原14fail/7pass因fixture的Path与原str接口差异保留，collect21不计pass；只修fixture调用，不放宽捕获，旧七控制不重跑。独立稳定scout P1/P2均0。单一自有/tmp起草范围偏差已保留原字节/端点后仅回收该精确文件；不是生产失败。root冻结receipt 4ec9f9f80b9fcf33f238d7c612fb5ff373c84de1b2ff9b6443507500bb5ba487 后授权同开发边界单次execution03，原source/validator/清理及正式产品门保持。报告全失败只能判unknown，scaled cap tests不冒充32MiB压力测试。

## 第三轮实际诊断结果与可复现输入缺口

execution03按4ec9f9f8冻结于2026-10-07T14:41:40.415430–14:42:26.757983 UTC一次实际运行，46.342553s，inner/wrapper1，原pi-license-bundle-invalid保持。public rmtree前真实捕获718B package.json（840f67ca417895f39ce28ab51bcd0cdbd585b2ee14b2b79ba894d853a3e05265）及72802B package-lock.json（97f1eff30a2b8f6a2c5c35550e35881fd64ce885a7e9ef0ed2236d1d459d255e），完整hash/readback核验。自有组empty/TMP已清理，最低空间959901696B高于预留；复制2202+六资产匹配原冻结，这轮未另做whole live源码后验扫描，脚本首末pins相同；不据此签sourcehold。

原自有pure projection成功：固定/生成各146行、same路径集合与顺序，141行九身份字段完全相同；五行version/resolved/integrity不同：@babel/runtime 7.29.7→7.29.10，@earendil-works/chord、pi-codemode、pi-mcp、pi-telemetry各1.0.2→1.0.4。若前置manifest/unique registry/platform/document门通过，首个行身份拒绝在index21 Babel；pure比较没有运行这些前门或full validate_source，不能把这一充分不匹配条件记为唯一原失败原因。本次有限root receipt 1aef15d032352dcfba94740e9bd20180061f3cb52e011b222b21bd52c97b5c74。

现有resolver只固定顶层版本，缺可复现transitive解析输入，限定搜索未找到自有license生成器或生产full lock骨架。root下一方向是保留已审查固定146图，先查历史完整raw lock及原own接口，再冻结公开npm锁输入的最小设计；不自动把五新版本写入registry、修改上游或放宽身份门。npm公开说明install在locked versions满足package.json范围时使用锁中版本；当前v11文档为11.21.0，仍需用固定11.19.1的实际开发解析验证，参见[npm install文档](https://docs.npmjs.com/cli/v11/commands/npm-install/)。本记录时只授权只读取证，不授权新seed代码或另次实际解析。

2026-10-08（本地）execution04已执行并在writer STOP后接受：root终态23输入receipt `1ff8237326fd22a761ec3dd039cef98c968b909d9aa7554d5d77cd36e485cb34`。新源码2204files/231dirs/48,522,706B由receipt `8a9dda163f0e304835cea52aed3e00dddcb7b3a6dae51f30ea864513de9a35de`固定；只对原executor替换五个材料常量，producer原字节不变。一次实际2026-10-07T16:14:44.635092Z至16:14:54.181700Z、9.546608s、UID/EUID1002/GID100、inner/wrapper0；原PiBackend.resolve_lock及read_lock返回schema2/pi-base/candidate identity `72ac0c2968ae7e1ed9ed344030defb6036f4b39c0a9593ea4949494d41a5be44`。捕获与保留pair相同，package718B/840f67ca…、lock72800B/c71c94ea…与固定seed全bytes相同；146行九字段有序与REGISTRY全同。root独立核全部29工件pins、2210复制项、35自有模块路径、manifest/piece/pair摘要、进程empty与临时根absent，未重跑resolver、validator、pytest。原checked未提供版本literal stdout，Python审计不覆盖Node内部spawn；source pins不当atomic snapshot或持续hold。正式manifest仍absent，许可安装门及Full/来源/角色/产品未通过，AUTO OFF；01–03历史失败不覆盖。此前“尚无actual解析”仅为当时阶段事实。

2026-10-08（本地）execution05 原候选解析已执行并接受，38输入 root receipt `7a31bff152192cd72a4a1d404653126ed7359eb4f1108316cf4af071a5abbfa1`。实际 UTC 2026-10-07T17:47:37.806281Z–17:47:47.740486Z、9.934205s、session84684、UID/EUID1002/GID100、inner/wrapper0；原 PiBackend.resolve_lock→read_lock 返回唯一 schema2/pi-base/candidate identity `2f99a9e46a4eff58d917a15a49063515d14510aa12203bbcfb023b125b763b3d`。原 captured/retained package831B/6e9c9b…与lock72246B/d30083…分别全bytes相同，lock等于新seed；145远程节点九身份字段有序匹配新profile registry，无unresolved记录，gaxios HTTPS7.0.6保持。Root独立核canonical manifest/slice/resource/pair身份，executor有限核20输出条目（13regular/7dirs）、2212完整复制记录及35原module来源记录；原副本已清理，不声称重开模块或持续hold。最低观测空间1,090,895,872B，groupempty/TMPabsent，保存先于清理；成功checked内部stdout与Node内部spawn仍未观察。原validator/readback真实运行，但installed许可检查尚未执行，正式manifest仍absent，Full/来源/角色/产品未签，AUTO OFF。01–04历史按原事实保留，不重复resolver/validator/pytest。

原 PiBackend.sync/_sync 在创建stage前都拒candidate，现有API不能直接安装candidate而不激活。Root决定后续独立开发安装子步骤：固定锁对/本地归档布局、官方Node/npm及临时HOME运行 npm ci --ignore-scripts --no-audit --no-fund，再由原copy runtime_files和installed-license validator核实际解包材料；不调用sync/_sync，不seal/activate/status/current，也不把开发结果升级为正式runtime资格。新的SDK/host组合仍须材料准备完后独立授权。当前仅脚本准备，未实际安装。

2026-10-08（本地）install01 独立开发安装已执行并接受，37输入 root receipt `3749a2962388ee5236231b47196537b023b1dd871beb8fff1782ec8575f2feb2`。session15143、UTC 18:35:25.499171–18:35:44.214203、18.715032s、UID/EUID1002/GID100、producer/wrapper0；raw版本确认为 Node v24.14.0／npm11.19.1。npm ci exit0并报告added124packages；原 source allow_unresolved=False 与 installed-license validator 均真正运行，registry145行检查通过，无source unresolved。固定pair保持831B／6e9c9b…与72246B／d30083…，binding仍candidate，public install_files107完成。只读保存树16653条（15184regular／1460目录／9contained relative .bin链接）、124615286 regular字节经独立scout逐项全SHA/type/member集核对无差异；2212源／资产复制记录与34原module来源记录匹配冻结。原副本已清理，module核对不冒称重开；首个比较器字段误用的13假不匹配输出保留，修正比较结果零差异。

本次采用env -i且无proxy继承，raw日志仅有deprecated与npm update notice，不据notice升级工具。最小观测空间1004605440B，自有组empty、保存先于TMP清理、源脚本首末pin相同。没有sync/_sync/seal/activate/current、SDK/agent或正式manifest发布，未取得sourcehold／运行包／Full／产品资格。后续当前保存闭包的SDK6另准备实际runner与授权，旧SDK6授权已闭合；bwrap --new-session使外层groupempty不能证明namespace全部后代退出，因此新work在成功/失败都保留为私密证据，不自动回收。


2026-10-08（本地）当前 Base Q1 摘要：execution05的145远程节点候选及 install01 原 source／installed-license validator 已实际通过，无source unresolved。早期两项MIT未解按各自阶段保留：standardwebhooks已取得固定提交的库范围正文；当前定向官方9.0覆盖图已移除proxy-agent-negotiate1.1.0。它们不再作为当前145图的同一未解项，也不作许可法律充分性结论。

当前安装树 SDK6 sdk01 在明确授权后一次六场observed、child／wrapper／tool outer均0，root receipt `cd3624dcfa90984031df7ed70d694c7e81cf1c3fc549df9977a2fcb3e5495684`，详细材料见[native-modern-base-installed-sdk-probe.md](native-modern-base-installed-sdk-probe.md)。新16,653条目／124,615,286B树与固定材料前后核对一致。先前RPC5是旧18,498条目候选、lock `f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac`的公开协议历史观察；尚无当前新安装闭包的RPC5执行记录。SDK6白名单也不自动等于独立project_trust行为验收。当前正限定核对公开信任加载接口及所需场景，T006仍未勾选；它本身不要求发布正式锁，candidate identity不等于sealed runtime或产品资格。旧授权按原固定场景闭合，当前缺口不改变已接受的历史观察。
