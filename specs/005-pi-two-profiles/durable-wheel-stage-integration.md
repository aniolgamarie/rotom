# Wheel 物理安装与运行文件校验 B2

2026-10-07 root冻结设计并授权下述唯一writer范围的默认合成实现。B1锁数据接线已由41输入receipt2991ae稳定接受；本包只接仓库自有安装器与既有公开数据/stage API，不启动宿主或第三方包。已有204项stage组件、七固定档案被动IO与248项来源数据组件的证据继续各自成立，不能升级为此产品接线通过。

本包随后已完成有限默认验收，77输入receipt `cde031bb1fd6dc04c9214c7560b5427a169e11d8d67b9fa0b1dff1e75097f839`。首轮runtime69通过不重跑，原seal后旧receipt shape引起3fail/175pass；必要schema定向旧源3fail/18pass至25pass，再原deps/runtimeFiles/完整integration同次261pass/54.04s，inner0，无skip，各轮不相加。root审STOP后的八target，scout独立仅核回执逆变换/测试；当前开放P1/P2=0，原失败、旧稿与722B阶段测试迁移分别保留。原seal/activate/status/readback实际执行，npm/外部进程为fake；这不是正式Full来源、loader/ABI、sourcehold、真实宿主或产品资格。以下正文保留已验收的实现边界。

## 接口与写入范围

唯一writer新增 `src/agentcfg/pi_python_bundle_runtime.py`、`tests/test_pi_python_bundle_runtime.py`；修改 `src/agentcfg/pi_dependencies.py`、`src/agentcfg/pi_runtime_files.py`、`src/agentcfg/pi_runtime_packages.py`、`src/agentcfg/pi_modern_launcher.py`、`agents/pi/schemas/runtime-receipt.schema.json`，向B1新增的 `tests/test_pi_wheel_lock_integration.py` 追加集成用例，并仅迁移下述一项B1临时早拒测试。原source-data/core/stage及其测试、其它旧测试、正式声明/vendor/provider/catalog、私有sourcehold/activation/lifetime均不改。B1已停止写入并完成稳定验收，本包是下一独立范围，禁止两writer并行修改共享文件。

历史 `test_b1_sync_ref_barrier_before_any_state_write_or_process` 明确要求任何ref直接返回“安装尚未支持”，与本包接线后有效ref安装矛盾。仅授权删除该完整临时函数及相邻多余空行，以追加的实际原_sync→hook→seal/readback成功/漂移拒绝用例取代；其实际26870B/101项事前像及通过历史保留，其它100项正文逐字保持，不能声称新B2仍保留完整101项前缀或隐藏skip/xfail。candidate拒绝沿原runtime_identity/既有candidate guard，不为了旧临时测试增加特殊unsupported分支。

新模块仅两个数据/物理IO接口：

- `install_locked_python_bundle_stage(stage, piece, sources) -> None`：仅原安装器在其自有scratch stage调用；自行读取所选固定正文和staged vendor原bytes、编译/安装/回读，不能消费外来plan或“已验证”布尔。成功不签来源、发布或加载资格。
- `validate_installed_python_bundle(root, reference) -> dict`：读取固定已安装声明与inventory，核严格数据及实际文件，返回detached exact `files` / `directories`数据，供原完整expected-set扫描使用；不是authority/来源引用。没有reference的原路径不调用或导入本模块/core/ZIP。

`files`是按路径排序的exact行 `{path, sha256, size, mode}`，包括全部原映射文件及生成inventory；`directories`是全部实际bundle目录的sorted unique路径，保留声明支持的空目录。全部路径只在固定 `supervisor/python-bundle` 下，files模式600、dirs700。返回值无payload/FD/private proof，可变对象不共享。ordinary错误统一新 `ValueError("pi-python-bundle-runtime")`、清cause/context；control BaseException保留原对象，FD逐acquisition一次清理，body control优先于cleanup control，规则与已接受stage一致。

任何字段选择、caller dictionary lookup或IO前，先捕获有界exact native数据副本，此后只使用副本：signed64、depth16、nodes100000、UTF-8 string4096、拒subclass/cycle/foreign/non-string keys。接口收到的piece/sources是原锁中的公开JSON数据；该物理入口要求其整个传入JSON满足这些界限，不复用caller可变字典或先验“已验证”标志。stage/root仅接受native str或当前OS的exact concrete pathlib.Path类，UTF-8路径<=4096；拒自定义PathLike方法。JSON body/inventory校验与布局读取同样从自有detached数据出发。

## 原scratch与所选来源

原 `_sync` 自己在final.parent中创建TemporaryDirectory，stage仍在其上下文内；静态证据只证明mkdir请求700，实际有效owner/mode须本次fstat核。hook位置仍是最后原producer、install-home删除之后、seal之前。新入口以 `O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` 打开原stage，fstat要求EUID同owner、目录且exact700；lstat同名目录与heldFD同device/inode，不能接受替换入口、外来路径或自行构造Full source对象。此FD由新入口持有，借给原stage组件，返回后核同名引用并关闭；stage组件只关闭自己的dup，不关闭borrowedFD。原TemporaryDirectory仍负责失败回收整stage，不在失败时发布ready/receipt。

正文从原stage内fixed `runtime/durable-python-bundle.json`读取，参考B1所选piece的ref/copy行。七vendor直接从原stage根相对 `source.vendor_path` 读取，完全对应原 `_sync` 的 `tree.write_state(source["vendor_path"], archive[0])`；不添加package.parent，不套用npm file引用的相对解析。新入口以自有held root FD相对读取：每层目录NOFOLLOW，文件用NOFOLLOW/CLOEXEC/NONBLOCK、实际类型及同device/原同名身份核，逐archive2MiB/size/hash与原locked记录一致，集合必须恰好七条。通过 `validate_selected_python_bundle` 配对后交原 `install_python_bundle_stage`，不导入第三方、pip/uv、运行native或访问来源网络；原URL只是锁定公开来源数据。原stage中存放raw归档不等于installed source资格，也不进入npm file引用。

所有新入口FD由自有acquisition-immediate try/finally管理，不使用原Tree构造器/parent/fdopen内部清理来承诺新FD强保证：其constructor在返回前内部close异常可能尚未交出dup，属于旧依赖语义，不能仅在外层捕获修复。本包不改storage/paths；原_sync及旧producer继续原Tree语义，不声称硬化其内部异常清理。新自有boundedread复用相同safe-relative/大小/原字节规则，父目录与文件持有链在读取后核同名关系；新测试的清理故障覆盖新ownedFD和原stage借用边界，不扩成所有旧Tree的保证。

固定数据JSON读取上限：正文8MiB、inventory16MiB；strict UTF-8、重复键/非有限数失败，结构仍按现有核心caps校验。reference是原5字段exact native shape；不能调用foreign方法或把路径/版本漂移悄悄修复。其SHA/size锁住正文原bytes，与core canonical declaration_digest不同。

## 完整冲突检查

原inventory略过ready/receipt标记且包含目录/内链，不能直接转换为occupied list。新collector从heldstage FD扫描完整可见命名空间；不跟随任何symlink。普通文件和symlink entry都作为**非目录占位**，`OccupiedFile.kind="file"`仅表示目标占位，不声称该节点是physical regular file或link target已证明在stage内；目录不伪装file。link target的原完整收据校验仍由原seal执行，不用本次no-follow扫描替代。读到其它节点类型失败。原marker也不能略过。

交planner的列表是扫描所得**全部可能与固定bundle输出冲突的非目录路径**：其casefold组件与reserved prefix存在exact/祖先/后代关系。所有输出都在该prefix下，因此排除其它路径不丢冲突；不是外来空list或漏扫。无关A/a别名不传给planner而误拒，保持已接受stage的合法对照。scanner明确拒绝已存在的casefold reserved prefix目录，包括空目录和祖先大小写变体；随后原stage仍核实际prefix的排他创建。scanner必须覆盖root marker/祖先阻塞/内链占位/未知prefix sibling，记录真实caps：最多262144节点、深度256；planner相关list仍<=16384，超限固定失败，不作逐对乘积。collector不核来源权限或读取文件正文。

递归打开目录用held父FD相对NOFOLLOW并核原lstat身份，过程后核持有目录与原父同名引用，close逐一执行。这只保证本次scratch扫描/写入的检查，不宣称跨整个产品寿命sourcehold或对任意并发变动的原子快照。late prefix替换仍交原stage的身份/readback拒绝和原seal检查，不以ACK或一次扫完证明不可变。

相关路径逐条满足原OccupiedFile的safe-relative语法、UTF-8字节<=1024、components<=64；过长或非法的相关冲突路径必须固定失败，不能因不符合目标语法而过滤掉。filtered records按原path字符串排序且唯一；重复观测也失败，不能去重掩盖变动。目录扫描深度256是全部可见树的遍历上界，不扩大传给planner的path64组件界。列表exact `{kind:"file", path}`，始终交原planner再次检查原cap/grammar/碰撞规则。

## 严格物理集合与原seal

新验证器核ref SHA/size与安装正文，公开核心校验declaration；读取canonical inventory并用 `validate_python_bundle_inventory` 核它与声明逐项相等，不能只相信inventory自身hash。inventory原bytes须与其canonical JSON表达完全一致；固定inventory自身也作为生成file进入返回集合，不能允许额外schema字段或任意producer文件。

随后对bundle持有NOFOLLOW目录链：root仍按原私有目录检查，所有新bundle目录要求同owner/device、exact700；共享supervisor父目录沿用stage既有同owner/device且无group/world-write规则，合法750不能误拒。所有新regular files要求singlelink/600/size/SHA原bytes；准确files/directories集合包含空目录，禁止symlink/额外文件/额外目录/改hash/硬链/owner/mode漂移。每个成员读取有既有declared cap，stream<=64KiB，不执行archive/member或依赖代码。验证器所读文件名与heldFD同device/inode且在读回后仍对应；失败固定拒绝，不返回部分成功layout。

原 `validate_files(root, rows, *, generated=GENERATED)` 增加可选 `python_bundle=None`。无ref保留原默认行为及manifest validator；有ref lazy调用新物理验证器，合并其exact路径/显式空目录到原expected集合，不能把新路径加入任意runtime manifest白名单或接受外来generated list。原runtime/许可文件的digest/mode/集合检查不删，完整supervisor扫描仍精确相等。bundle成员的mode/size/hash已由物理验证器核，完整扫描再拒额外节点；generated原两个文件仍保持原校验。

现代launcher在bundle hook之前调用原无ref `validate_files`，是尚未完成的producer阶段；hook之后原_sync显式调用带ref完整校验。原 `pi_runtime_packages.validate_installed` 在seal及后续已安装校验时传所选piece.ref，所以缺失bundle或任意成员漂移不能保持ready。只由原seal/activate发布；原seal完整inventory纳入所有新文件。B1临时早拒guard仅在本包完成接线后移除，失败不得fallback到早前无bundle树。

第一轮真实合成检查new01为175pass/3fail（runtime组件69pass，integration106pass/3fail），三个Full集成已到原seal/activate/status；receipt原closed slice未允许python_bundle，status加载原schema后拒damaged。原失败和七源终点保留在40输入open receipt5818a898，本包因此限定增加上述一个receipt schema，不跳过原status或伪造ready。slice新增可选exact5field ref，inline与B1锁schema同形（schema_version整数1、固定source/path、lowerhex64 sha256、size整数1..8MiB、closed）。v1显式禁止ref；有ref的receipt必须为v2且原binding_identity.profile=pi-full，Base不得带ref；旧v2无ref Base/Full与旧v1不受影响。仅逆去新增property及对应两处condition pieces后，完整JSON深相等于原实际schema事前像；不放宽其它字段/旧required/unknown/绑定条件。

JSON schema的整数shape与自有native强边界分开报告：现有Draft202012Validator对1.0等整数值float也可满足integer，B1相同inline本来如此；不更换全局typechecker或偷改schema来假称词法/native严格。schema cases核bool、非整float、字段/path/hash/cap等；runtime入口自身exact native capture/reference仍在FD/IO前拒绝所有float（包括1.0及整值size float），原后续status/物理验核不能仅凭schema通过保留ready。复用已通过的native负例或只追加缺少的定向检查，不重复整个69组件。

原modern launcher的许可补充循环用 `kind not in ("asset", "npm")` 选择仓库来源，会把新增wheel错误交给旧 `install_source_licenses` 的node_modules许可路径。本包将条件明确为 `kind in ("local", "git")`；这两类仍使用原补充来源及严格检查，npm/asset原路径保留。wheel包内许可由公开wheel数据/stage的成员集合与安装后物理校验核，不提供旧仓库overlay或node_modules许可证路径。加wheel overlay调用哨兵零次及合法local/git仍调用的控制；这个安装分支归B2，不倒写B1锁数据接线通过，也不扩大许可来源或法律充分性结论。

## 验收与尚未完成目标

默认合成测试使用临时HOME/仓库、自有七wheel与fake npm/process，不启动第三方宿主。覆盖真实scratchFD借用/close/失败清理、七档案→已安装物理集合、原emptydirs/原字节、大于1MiB native字节只被复制、canonical inventory、late entry替换与identity拒绝、所有JSON/reference/file/mode/owner/类型/链接/hash/size/extra集合拒绝、control/cleanup优先；确保无第三方import、loader/site/PATH/.pth/执行。

独立集成测试走原_sync producer→hook→seal/readback的合成路径，证明ref Full必须实际包含bundle，缺文件/漂移不能seal/后来validate_installed通过；旧无ref Base/Full不导入新模块、不读wheelvendor/selectedbody。recipe阶段仍按B1接受的全局公共bytes扫描，不能声称Base绝对零body IO。occupied正负包括无关大小写别名允许、prefix emptydir/内链/marker/祖先阻塞/晚到替换拒绝，不能只测helper实现的同构镜像。

至少一个合法fixture的package.parent不是 `.`，归档仅存在于stage根的原locked vendor路径；新入口必须成功并保持原归档bytes，不能只在package位于根的fixture上掩盖路径混淆。错误package-relative替代归档不得fallback选择。

完成新suite后仅一次受影响旧test_pi_dependencies.py、test_pi_runtime_files.py，前者的原安装/收据路径也覆盖pi_runtime_packages；receipt schema的既有针对用例由有限测试映射证据确认后另核，不据文件名扩大整个catalog套件。若writer发现独立必要旧suite再提供具体调用证据给root决定，再B1新增suite受影响范围。test_pi_vendor.py的旧许可helper没改，不因搜索命中重复无关旧套件。保存每轮实际counts/skips/UID/inner状态，不重跑未改core387/stage204/source-data248或已有七档案被动IO。稳定diff由独立证据加root最终正确性审查决定，独立executor若因线程额度不可用如实记录；新实际产品stage七档案组合若准备运行，应另记录边界和已授权被动IO能否覆盖，不能沿用任何SDK/native smoke授权。

正式Full声明/provider、原installer完整来源、受管CPython/stdlib/loader/native ABI、许可充分性、private sourcehold/activation/独立寿命、真实Pi/Codex/模型与质量预算仍另验收；B2组件通过不提前勾完成整个任务。当前formal7/100、全部产品gate false、AUTO OFF保持。
