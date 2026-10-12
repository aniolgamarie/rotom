# B4：已安装 Full 材料的只读观察候选

2026-10-07 root修订接口，接续B3默认材料验收86输入receipt28d18a7c与七源实际reader接口证据。它补齐未来FullSourceView的installed部分，不实现current投影、不构造完整FullSourceView／source_identity／RegisteredReference，不签来源、initializer、执行或DB权限。有限独立设计审查P1=0、候选P2=4，root按末段决策修正后授权以下三文件的默认实现与受影响验证；授权不涵盖真实宿主或原生探针。

## 目标与范围

B3可以验证固定origin及所选材料，原status可以验证完整receipt/inventory，却只返回字符串。未来两个actor需要各自得到本地实际物理观察，不能把status=installed、receipt自身数据或合法JSON当来源能力。新增一个只读数据入口，保留原status所有语义和原完整安装校验，不复制另一个弱化版validator。

观察仅供本次可信启动/来源actor的私有上下文使用；不得进入通用摘要、日志、异常或公开status。调用者给出的root/context与合法观察数据没有权限外观。该API不证明root来自原Workspace、实际manager、发行来源或正式Full选择；只有后续完整caller／manager producer和私有资格核可以证明这些条件。不得把观察可成功当新Full gate。

唯一候选写入范围：NEW `src/agentcfg/pi_installed_source.py`、NEW `tests/test_pi_installed_source.py`，以及 `src/agentcfg/pi_runtime_packages.py` 的原status核最小提取。原identity/inventory/validate_installed/seal/activate、origin schema/声明、安装caller与全部旧tests保持。正式lock/recipe/provider/上游及缓存不写，不改paths/storage安全规则。没有initializer token、FD传递、子进程、SQLite、账户控制锚或sourcehold IO。

## 复用原status核

把当前status的实际receipt/schema/binding/identity/inventory/validate_installed/profile检查按原顺序提取为自有 `_validated_receipt(root, identity)`。原逻辑检查的damaged早返对应内部None；原installed完成对应 `(receipt, raw[0])`，第二项是该次实际解析的receipt原字节；原异常保持传播，不新增catch或新的异常类别。新观察必须将自己有界读取的marker原字节与共享核的rawbytes相等核对，不能只假定返回dict来自同一次marker读取。不新增schema/算法/路径fallback，不改变旧v1/v2合法域或未知字段失败。`status(root,identity)`保留原missing判定、原owned检查位置、原异常类型集合及damaged返回；在原try中以 `_validated_receipt(root, identity) is not None` 返回installed，否则damaged。原owned为false的行为与异常映射须逐行对应，不能靠函数整文件hash约束以后的演进。

新helper模块不进入runtime_packages模块顶层import；Base/noowner的原status不读取新模块或新可选资源。新观察入口自身只支持Linux x86_64、v2 pi-full、显式durable_owner和B3完整expected context。它不改变candidate的旧material/status语义，也不把candidate观察当正式来源。后续真实启动gate仍须拒绝candidate/unqualified。

默认源提取审计只在修改前真实快照上保存共享核与旧wrapper顺序证据，不增加永久pytest整文件hash。原receipt/profile/node/bundle验证方法原调用，不注入accepted布尔、callback、任意validator/schema loader或生成器。

## 唯一新入口与输入捕获

`capture_installed_full_source(root, piece, *, identity, lock_identity, platform, toolchains, binding_identity)` 返回下述detached native JSON观察；没有factory、permit、RegisteredReference、source_identity或资格字段。

输入域沿B3的数据规则，但新root入口仅exact native str，不接受Path/native Path实例/pathlike/subclass。先核exact type及最多4096字符，再strict UTF-8编码并核最多4096bytes，拒NUL、非绝对路径、根目录与含`..`段，最后才构造本次自有Path。不检查Path私有slot或补丁标准库，B3原installer持有的内部Path路线不变。piece/toolchains/binding使用现有有界native graph捕获，合法alias保留并沿原展开成本计费，cycle或超预算展开拒绝。所有调用者字段在Tree／材料／schema字段IO前捕获一次；type/key检查前不hash/lookup/调用foreign方法。这里只限制新入口的输入工作，不声称Python导入或通用堆分配硬上限。

expected identity、platform、toolchains、closed十字段binding及其原digest关系沿原B3 `_context` 与原identity payload规则，不重新发明版本／身份算法。新入口先核已捕获piece是显式Full owner，缺owner/Base先于可选owner导入固定失败；已拥有graph可复用原 `_owner_rows(..., locked=True)` 的closed role/ref/最低row数据核，核piece identity、binding slice和原base runtime digest关系。foreign或错误expected context在材料IO前固定失败。完整source声明与实际源字节只由后续原origin reader核；纯数据最小row检查不能冒充来源。调用者的迟到字段替换不参与后续lookup，后续内部copy只处理已拥有graph；单次捕获不宣称atomic或原来源能力。

普通错误统一新的 `ValueError("pi-installed-source")`，新对象且cause/context清除，包括在ambient except内；控制BaseException保留原对象。错误不含path、正文、stat值或摘要。输入不存在资格布尔，任何自称verified/approved/source_kind/principal字段都不支持。

## 返回exact shape

顶层恰好七字段：`schema_version` native int1、`profile` literal pi-full、`lock_identity`、`runtime_identity`、`root`、`markers`、`entries`。两身份来自已核expected context，不从receipt/origin自行声明取得资格。

`root`为目录物理投影，exact四native str字段device/inode/uid/mode；`markers`恰好receipt/ready两slot；每slot恰好physical/sha256，physical为下述file投影，digest为实际读取字节SHA256。marker路径固定 `.agentcfg-receipt.json`／`.agentcfg-ready`，mode0600／regular单link/euid；ready必须等于本次identity加单个LF的65bytes。新reader强化自己的观察域，不能悄悄改变原status对ready的历史判断。

`entries`是完整actual sealed inventory的exact路径映射，必须与原receipt.files的全部键及kind/content/mode深对应，不包含两marker。每path使用原relative_path规则且严格UTF-8，来自actual tree／已核receipt集合，不接受调用者补路径。目录row exact kind=directory/physical；file row exact kind=file/physical/sha256；link row exact kind=link/physical/target。每row中的kind只是完整actual inventory固定slot的数据，不独立授予读取权。未知kind/rowkey/文件夹夹带/缺失一律拒绝；不能只列B3的35个最低模块。

file及link的physical恰好device/inode/uid/mode/size/mtime_ns/ctime_ns/nlink八字段native str。device/inode/size/nlink为canonical uint64，uid/mode为uint32（mode含完整类型位），两个时间为canonical signed64。目录只有前述四字段，不带mtime/ctime/size/nlink，不因本次目录合法写入而把同一对象判stale。所有十进制字段先type/长度，再canonical语法与精确范围，拒bool/int/float/+/-0/空白/前导零/指数，不截断。physical只为观察数据，不证明所有权策略或连续持有。

link沿原完整inventory允许的in-tree npm链接，不能全禁链接来减少复杂度。link物理tuple保留S_IFLNK类型事实，不声称Tree.open_read读取了link；target保留原实际字面内容并与receipt匹配，非秘密性依赖固定公共producer。regular/file的type/mode与原inventory及每文件原规则相符；目录/file/link均为本次euid，regular/link单link，目录nlink不作为恒定身份。

返回不附origin原metadata、receipt正文、源文件正文、private current/generation/preimage、private policy/manifest/auth值或它们的digest。origin/pair/body/wheel/role仍通过共享核及B3原reader完整实际读取校验；对应entries记录实际公共installed文件的byte SHA及物理身份。没有因只返回摘要而省略原材料读取的许可。原public installed源的byte digest属于私有观察，不能替代固定公共producer证明或被直接放入公开诊断。

## 实际IO及稳定性边界

全程只读，Tree(create=False,private=True)，保留原unsafe ancestor规则。新观察先持root Tree及实际根fd，有界读取两个marker；通过共享原status核取得合法receipt/rawbytes，核actual receipt marker原字节、slice及全部expected context对应，再通过原owner reader同次expected context验证全部B3材料。新增marker读取与完整inventory观察在此受控根下，末尾重核named root与原held根的device/inode/uid/mode。

共享旧validator仍包含按路径重新打开的多个Tree、原inventory和未设新cap的读取；它们没有因为外层持一个fd就变为全链FDhold或受新读取预算约束。复用并保留这些原语义，最后的对象／marker核对只发现本次可观察漂移，不消除同UID替换后恢复等竞争窗口。此组件不得作为对抗任意并发篡改的来源能力或硬资源隔离证明。

每regular file使用原Tree.open_read的pre named stat→opened fstat→有界流hash／实际byte count→post fstat→post named stat，另核完整physical字段（含uid/nlink）及实际模式。不能只取entry.stat或把原receipt的sha复制为actual观察；actual hash与已核receipt对应，并保留原零/大文件合法性。读取后保存detached stat数据，不长期保留文件FD。

目录使用原受控根的无follow目录FD／原Tree.parent接口获取actual fstat，核实际type/euid/mode和named关系；若使用parent接口定位固定内部检查basename，它仅作父目录定位，不创建或读取该basename。link使用同一受控parent FD的no-follow named stat/readlink和首末完整physical比较；必要时可用Linux O_PATH|O_NOFOLLOW fd核actual同一link，不通过跟随link读取外部字节。仍保留原in-tree解析与literal target匹配，不接受caller新target。

完整遍历前后核目录/文件/link的actual named对象与记录投影，发现变化固定拒绝。目录集合/entry集合都须与receipt完整对应。相关“末核”只证明有界观测窗口的对象/字节事实，不称跨多文件atomic snapshot、持续FDhold、防inode复用/任意同UID篡改、sourcehold或初始化权。真正维护保护／持有／原引用最后核仍由完整Full包另实现。

新观察自己的显式Linux支持域：完整entries最多65536（含目录/file/link），regular单文件最多256MiB、累计实际entries regular bytes最多2GiB；两个marker另计，receipt原字节最多16MiB、ready固定65bytes，link target strict UTF-8最多4096bytes。新增遍历逐entry计数，达到上限后不继续收集或排序整个目录；新增regular/marker读在stream分配正文前核opened size与剩余预算，以有限chunk读取并对实际量复核。link从actual no-follow readlink取得字符串，UTF-8编码前核字符长度、编码后核4096byte合法域；不能声称readlink syscall返回前已限制内核字符串分配。可选有界预检不替代原完整validator，也不使后续旧路径读取获得对竞争有效的资源预算。不因十进制uint64表示扩大新增IO支持域。

32MiB是新观察canonical结果的合法域：使用原 `json_bytes` 完整编码后核实际长度，未证明编码过程的内存峰值不超过32MiB或通用Python heap硬限。输入／entry／字段域提供有限数据范围，不等同于全链分配／读取／解析硬上限；旧validator保留未设这些新cap的行为。需要更强全链资源或流式编码保证时另冻接口，不使用近似编码或保守估算替代原canonical合法域。超域仅新观察unavailable，不改变旧status或ordinary editing合法域；不能把新结果cap塞进原metadata capture或receipt生成。

所有directory/file/link类型和projection数值从actual stat_result取得，不接受caller supplied stat对象/FD/path列表。实际读取cap、entry集合和全根末核用于发现普通漂移；没有断言它已覆盖完整controller/Python loader/import闭包。

## 默认验收与后续资格

默认只用临时完整合成受管Full、原installer/seal/activate/status/origin读者与fake子进程，独占安全/tmp及临时HOME/断网。至少一个完整正控制必须真实遍历带nested dirs／regular／合法in-tree link／marker的已安装根，逐path对照receipt并验证实际物理值及byte SHA；返回detached/固定键/十进制边界、source正文及私有哨兵不进入结果/错误。不得用inert fake validator/accepted=True代替原材料校验。

反例包括：输入foreign/native Path/pathlike/subclass/cycle/非法bool或unknown字段／超预算alias展开零foreign方法与材料IO，Base/noowner零可选owner访问；合法alias是detached与一次捕获正控。迟到caller替换后仍用已捕获值，不能误称任何late mutation都必须拒绝。origin/receipt/ready/Node/license/pair/body/wheel/role漂移、额外/缺失/kind混淆、同字节同名替换、根/子目录同名替换、hardlink/symlink越界/错target、mode/owner/nlink变化；读取中/遍历后变化固定失败。每cap边界/超界测试按其真实范围区分前置size/count检查、实际stream计量、readlink／canonical结果的后置域检查；不声称未实现的分配硬限。原controls同对象与ambient普通错误清链。纯编码测试不当actual IO或来源资格。

原status wrapper在真实preimage上的等价提取、v1/v2/Base noowner及damaged/missing与所有原异常映射要有针对性证据。实际默认测试新增malformed receipt JSON→damaged、完整inventory相等后validate_installed抛原caught类型→damaged、catch tuple外异常仍传播、显式v2断言，以及旧ready空白合法／新65LF域拒绝对照。一次提取AST顺序审计留在固定preimage工件，不变成永久源码hash测试。

最小旧包沿静态选择receipt5789eacc的八个function selector：legacy receipt同长漂移、failed installer missing、legacy install/repair、B2原producer/hook/seal/status、B3 Base noowner冷状态、B3 Full原writer/seal/activate/status、B3材料漂移、B3新identity失败保留真实旧installed。材料漂移只选body与wheel两个参数，Full正控保留两种Node大小，其余函数按原selector执行；collection需实际确认参数ID，不能把静态选择算通过。不重复无关387/204/248或535/83全部suite，不跑宿主/SDK/native/account/model/deploy。新默认临时树在每test结束及时关闭并清理自己exclusive/tmp；旧节点分小批保留每批log/XML/真实source pins与退出码，不移到unsafe Data或改guard。

当前接口观察不接入真实startup caller/manager，也不保存持久资格记录。新的完整FullSourceView／current公开与物理投影／解释器来源／initializer principal／sourcehold／guardian activation另冻；不得从此数据或hash构造原能力。Linux以外未测，无自动平台fallback。正式7/100、所有产品gate、Recovery3已闭合和严格计量前AUTO OFF保持。

## 本次有限审查的root决策

原候选11545B／4e829a0b的四项P2是文本边界：旧校验全链cap、canonical编码峰值、exact PosixPath含可变实例的foreign方法风险、合法alias误作负例。独立executor未发现额外P1，root保留真实候选／来源preimage于18输入receipt5e5c9d2d，并采用上述精确修改。本次文档修订没有写B3原11target；后续生产实现仅以已列明的pi_runtime_packages原status核最小提取为一个显式例外，另十target不写。exact Path风险有自有纯标准库无目标IO探针记录，不是上游／标准库补丁，也不追改原B3内部Path路线。

cap历史样本8输入receiptc31793d3记录cache-inclusive candidate18498entries／223155286regular bytes与七wheel临时stage203entries／4942283展开bytes；分别低于候选数值，但不是sealed Full。完整ActualFull receipt16MiB与结果32MiB的覆盖仍未知，必须在后续实际Full材料成立后测量，不能用package count、selected pins或样本外推来签通过。当前只授权可持续的三文件默认组件实现、必要修复和受影响验证，不授予原生／部署／产品资格。

## 稳定默认实施结果

2026-10-07：executor 三target STOP 后，root按稳定最终字节、原status顺序AST证据、完整初版源码/测试及后续delta验收。93输入实际receipt `7c7e365d3adec97598e45c02bcfe3488c1ddef5e7fa6c3f9e7971c5aa8f456bd` 保存原设计16574B/e906e498、代码/测试、失败和修后原节点、各批命令/日志/XML/cleanup/source pins及审计。final source63d2d68e/11576B、test2141475f/16527B、原status唯一提取050ef8c6/12810B。

新suite实际collect93nodes；首轮92pass/1fixturefail/183.65s，wheel参数选择了目录而在产品调用前IsADirectoryError。仅fixture一行改为inventory kind=file，生产字节不变；原失败node另次1pass/2.51s。受影响原八function实际collect10nodes，八小批全部inner0/10pass/零fail/error/skip。精确XML节点覆盖无未成功或未运行项，不能称一次93pass或把不同轮次相加。每次原exclusive /tmp context结束后目录已清理，临时HOME/DSH/XDG/OS-account/断网/fake child边界保持。

root阶段发现两代码P2：`//`、`///`、`/./`等语义根未拒，以及重复scandir条目覆盖记录；最终增加owned Path语义根检查和逐entry seen拒绝。实际默认用例已覆盖这些补充、读取中真实hardlink/size/content变化、完整字段/marker以及迟到caller捕获。duplicate entry和错误UID测试是明确合成支路，scaled caps不是实测65536entries/256MiB/2GiB或actualFull容量。原status完整文件逆变换与12771B/d6475e8e旧像逐字节相等，final pin与此前root AST审计408ea099匹配；没有永久源码hash测试。

此次仅默认观察组件完成：完整Full来源、实际current producer/receiver、35minimum之外的helper/解释器闭包、initializer principal、持有/guardian/服务激活和产品native gate仍未签。下一包先处理原Pi modern launch contract阻塞；本结果不生成source_identity/RegisteredReference或任何授权，formal7/100、所有产品gate和严格计量前AUTO OFF不变。
