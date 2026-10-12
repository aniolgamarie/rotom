# controller Python 来源与 Linux 资格

2026-10-07，root 根据原观察环境静态摘录 receipt `2bf6a07f370691c097134c148ede3a0d6499a8bcfafc132de21f18217360a73f` 和独立 scout 的 ELF/RPM 限定证据选择首版路线。本文冻结来源策略，尚未实现 producer、动态闭包采集、资格检查或 controller launch，不修改系统／venv、运行包声明和正式锁。报告生成使用过 Python，不对整段会话宣称“没有执行 Python”；本次静态 collector 没有执行被调查程序。

## 已观察的安装

原 EUID1002 观察者确认 `.venv/bin/python` 和 `python3` 最终解析到 `/usr/bin/python3.11`。系统 ELF 的原 UID/GID 为0/0，mode755、nlink1、15344B，SHA256为 `f0f1292a7e92f235336306d453222b1706a1c820ceeadf2e6cb2cc572f090fab`；这些是当前文件的事实，不是独立发行验证。venv 配置的 CPython3.11.11 仅为配置声明。

scout（gpt-6-luna/high）仅用 shell、readelf、RPM、stat、readlink和hash调查。ELF声明 `libpython3.11.so.1.0`、pthread/dl/util/m/libc，PT_INTERP为 `/lib64/ld-linux-x86-64.so.2`，未见RPATH/RUNPATH。RPM将解释器归到 `python3.11-3.11.11-1.0.1.al8.x86_64`，libpython和stdlib归到同版 `python3.11-libs`，定位 `/usr/lib64/libpython3.11.so.1.0` 与 `/usr/lib64/python3.11`。正常观察环境中两个包校验退出0且无输出；默认隔离UID/GID视图的UG差异保留为观测差异，不判成包篡改或来源通过。

这些查询没有递归解析每条动态依赖，没有记录实际import闭包或独立验发行签名／源码构建对应关系。RPM数据库和source-RPM名称只是本机安装记录与定位；二进制、包列表、零校验差异、root owner都不能各自签发运行资格。不能将15344B ELF复制到runtime并宣称已经打包Python。

## 首版来源选择

Linux首版使用**与原受管manager同一实际解释器安装**的固定资格，不另引入未经核实的Python发行资产，不在初始化时发现PATH或选择替代系统Python。controller以该安装的已核固定物理入口运行 `-I -S -B`；本仓库Python源来自同一正式Full sealed runtime的固定owner_controller角色。它不依赖venv的第三方site-packages，不启动 `uv run` 或安装器，也不将管理器的环境或site配置带入child。

“同一”必须由原启动producer实际捕获该manager的解释器安装、源和过程关联，并由接收manager本地重核；不是client提交 `sys.executable`、任意路径＋摘要或另一个进程宣称“same manager”。producer与validator的精确API仍在current-startup-origin后续包冻结。manager可受管理venv启动，但symlink链只是其来源记录；controller执行已核物理入口，不能依赖venv重新解释prefix或注入包。接收manager的真实执行对象必须对应本次已核安装；运行过程的解释器／loader来源不符时不能靠文件当前合法继续。

本机安装的固定 qualification 是独立的受管本地来源记录，纳入原startup私有引用；不当作跨机器公共资产，不嵌入普通配置或将一张host-supplied“verified”布尔表作为能力。记录绑定资格schema、实际Linux平台／架构／kernel前提、原解释器安装与发布来源、依赖闭包字节和隔离导入策略、相关自有controller源码身份及必要行为证据。资格的生成／持久化、签名source验证、源变化检测仍未实现；当前观测不能生成这张有效记录。

选择此路线是为复用已受管理器控制的实际安装及其维护渠道。以后可新增官方Python资产路线，但它需独立来源、许可、平台loader、闭包、producer契约和真实资格；不能在原路线失败时自动切换。当前Python版本不作为面向所有机器的强制版本声明；新patch／发行包／平台触发重新资格，不能拿3.11公共API文档或旧探针结果代表新二进制。

发行授权与key信任起点按[已接受的官方HTTPS-bootstrap标准](durable-controller-publisher-trust.md)判断。两份固定RPM的发行/签名对应已有限接受；没有独立指纹公告不单独阻塞此路线。完整运行来源和行为资格仍须下述证据，不将该接受外推为已安装或本次manager资格。

## 必须闭合的源与加载边界

资格至少覆盖物理ELF及其受控祖先／symlink链、PT_INTERP实际对象、递归解析后的libpython和系统共享库、loader选择机制与搜索配置、该Python实际stdlib／zipimport和将使用的原生extension依赖、固定入口和所有自有import源。只读ELF NEEDED、RPM filelist或一次module.__file__日志不是这份完整闭包；不能把正常启动未碰到的可到达替代路径当已排除。

实际loader route要绑定当前平台来源和配置；若动态cache／搜索目录或其他机制可选择资格外库，该qualification失败，不在运行时遍历任意fallback。这是安装验证与持续源检查，不声称path/hash复核是kernel atomic exec固定或防同UID任意改写的屏障。被核源码与系统来源变化让引用stale，不用当前同名新文件补成等价引用。闭包采集只读且有界，不能动态扫描账户／账号目录；其精确文件集与读取上界须在独立API包冻结。

`-I -S -B`只是固定参数。必须实际验证它在选定安装下的prefix、sys.path、用户／system site、pyc、环境忽略和本仓库受控导入行为。隔离模式下自有入口只能在预留原3并核固定自身源后，通过冻结的确切source入口装入自有包；不得为了找到模块补任意cwd／PYTHONPATH／用户site／vendor路径。Python自身启动需要的文件读取不在“预留3之前零文件IO”保证内；原3的要求针对自有source/path/storage活动，不能倒推解释器初始化完全不打开fd。

固定child环境必须排除Python和动态loader注入变量、agent／initializer capability、账号和provider值，允许项由后续launcher API逐项冻结。系统安装的权限与无外来可写搜索目录是来源前提；它们不证明拥有无限同UID内存／文件权限的外部程序被协议阻断。受限worker仍不能继承初始化端点／cap，也不能挂载控制锚和startup私有材料。

## 过程与行为资格

选定Python需要实际支持原pipe2、F_DUPFD_CLOEXEC、固定pass_fds、held pidfd_open、P_PIDFD waitid和pidfd_send_signal；公开方法存在或版本文本不足以证明本机kernel路径。父manager与child controller是两个独立actor，都需自己的主线程SIGCHLD disposition、无SA_NOCLDWAIT／reaper、原child先绑定held pidfd再等待，以及SIGPIPE前提。controller管理Node的证据不能补足manager创建controller的前提。

本机libpython的signal实现与相关构建来源须固定，再用独立原生资格观察所要求的SIGCHLD／真实退出行为；现有v3.11.0源码tag不能证明这个3.11.11分发包的C实现。资格使用原syscalls与真实对象，不改Popen、signal、importlib或SDK的实现，不monkey patch原生对象。默认fake只检查本仓库算法顺序和未知状态，不验这些kernel/解释器事实。

新的实际解释器＋controller＋两pipe／fd3＋Node组合另准备材料并明确授权。旧FD6与fbfea八场授权已闭合，已执行验收并闭合的Recovery3 d61799三场也不是这组资格；不执行新native，不把默认pytest执行器视为controller已资格。不能用只验证版本和一次成功退出的smoke替代源／inheritance／锁／pidfd／失败持有链分别需要的证据。

## 关闭条件与后续范围

缺实际同一manager来源、完整loader/import闭包、发行证据、必要行为、当前Full固定四角色或完整sealed inventory之一时，Durable初始化入口固定unavailable，零controller launch／目录／Node／DB；Base未选Durable零可选读取。健康Full ordinary editing不等待资格采集或初始化job；已有整个运行包gate不为可选服务放宽。活动服务保留原source/runtime/SID/storage和预算，不能因升级Python自动换root／epoch或接管。

后续仅在root冻结sourceproducer／validator和资格schema、读取者、限额、持久记录与source最后核之后，才授权唯一writer实现。此设计并未解决trusted initializer principal、current.launch真实捕获或私有handoff，也不准许permissive fake开启IO。默认验证分别覆盖外来path/hash/记录拒绝、同manager对象漂移、加载路径和包／controller变化stale、Base零可选读、无secret/env泄漏及所有未资格场景零launch；真实行为验收单列。formal7/100、全部产品gate和严格计量前AUTO OFF保持。

2026-10-08（本地）有界静态采集已经实际完成并接受，root receipt `91206c137aaa397498b3296d2769bd76e19d8c745485f2e395714ca8711a696b`。固定两个已验签 RPM 的 filelist、Python/stdlib/pyc/sysconfig、有限 loader 配置和 ELF 候选共 2,513 files；2,433 个有匹配的 RPM SHA256，1,779 个为已声明 pyc。139 次固定 rpm/readelf 元数据命令全部 exit0，137 个节点具有 ELF 解析字段；工具自身字节属于采集来源记录，不纳入 controller 运行闭包。文件首末 SHA/元数据一致，203,107,220 累计读取字节；仅 source 端点观察，不能声称 atomic snapshot 或持续 hold。ld.so.cache 只记录 opaque hash，actual cache/hwcaps/search precedence、prefix/sys.path/pycache 读取、未列出的可到达导入及原 manager 关联仍 unknown；此次没有专门目标运行、import 或 native 资格探针，报告 Python 使用同安装执行本身单独记录。之前“尚无采集”仅代表当时阶段。

2026-10-08（本地）Source RPM 静态证据补齐，51 输入 root receipt `38dac03a297fa699bf329358d8bbec95f078a1b5b11641e230927134562a8840`。官方固定 `python3.11-3.11.11-1.0.1.al8.src.rpm` 为 20,159,884B，SHA256 `241053719ef980ea14b0ed437e6d47bc65050414004e7b74a6b3400fb2a79b9f`；fresh 私有 DB 下三个签名／元数据命令均 exit0，沿用已接受 vendor HTTPS key 起点。被动解包的20个成员逐项匹配 signed RPM file records，原始 Python 3.11.11 档案内7份选定源码／许可已保存。第一次归档名过滤把 `.asc` 也选中而失败；旧输出保留，仅改精确档案名后一次被动重跑成功，1.917s。

独立 scout 对11补丁与spec做字面映射，四份相关 signal／lifecycle／posix／subprocess 源无直接 patch target；configure.ac、自动生成 configure／pyconfig.h.in、条件宏与构建命令存在，未执行或复现，不能排除间接影响。root核对该版 `PyOS_setsig` 的 HAVE_SIGACTION 分支、pidfd syscall、waitid错误传播，以及 Popen ECHILD 合成退出值。安装的 `_sysconfigdata` 仅 AST literal 读取，58,387B／`cbfcbc917b64f66bd7f125040d36472704f876a6216ab203560a90626d4e094b` 匹配 signed libs RPM，声明 HAVE_SIGACTION／HAVE_WAITID 等为1；声明与源码均不能替代实际二进制／kernel资格。尚无专门 native、完整 loader／import closure、同一 manager producer、持续 source hold 或 Full 资格。

35个未归属签名包记录的系统 ELF 物理端点，下一步仅对固定 RPM SQLite main 的自有副本查询包归属；source WAL 前后必须为空，source DB 不进入 RPM argv。复制采用只读源、字节摘要和首末端点／目录项检查，仍不是原子快照。准备脚本的复制后目录复查与结构化失败记录已修复，实际查询尚未执行；包归属元数据不能外推为发行验签或 actual loader selection。

2026-10-08（本地）35物理system ELF包归属查询已完成，76输入 root receipt `a884de31f1d7fe68fa79845c046f935fc4c200abf1a5ca8903298b6530bfd56d`，session44836／outer0。源main75,157,504B／`f2f0c199588852f64d24cc7128a8722ce3c5730853fcee97d5d98eead80546ea`，复制／读回字节摘要相等、source WAL和目录项复制前后检查通过；RPM35次只获自有db-snapshot路径，全部exit0，目标与工具首末记录一致，raw输出3032B，归到21个exact发行包header。仅包归属元数据通过；sourcecopy并非原子快照，没有RPM全部读取／副作用跟踪，私有DB可有side files。21包发行验签、实际loader/import/manager/sourcehold/Full仍未资格，旧静态375unknown是当时报告计数，不把包归属补齐算成整体运行通过。

2026-10-08（本地）21个固定系统库包的公开位置和正文采集已完成。42个固定HEAD（os／updates各21）观察到21个200与21个404，root receipt `b2a63e67c561c9e15f29d9c53dc907abbfd82722f17c1933363ee092b5993f8c`；默认环境42次DNS失败记录保留，正常网络同边界重试成功。随后只GET选定的21个200位置，session41300／outer0、21.442s，共8,958,480B，保存和完整读回SHA、HEAD长度均匹配；25输入 root receipt `d0af138279f6ca1c29a5cbfb07a31aeb0a192376d69858065f6cf48f1d82c0e5`。无redirect、retry、auth、proxy、安装、解包或RPM／native执行。单文件／总量／请求数有界，IO timeout与步骤间monotonic检查不等于整体硬截止。正文身份尚未验签，也尚未逐项绑定35个物理system ELF；下一步仅在自有信任DB对这21份已保存正文做验签与filelist查询。loader／import／manager／sourcehold／Full资格仍未通过。

2026-10-08（本地）上述21包验签与filelist对应已有限接受，99输入 root receipt `a1b6b4ec91d681145c98170dd31f8b87089d4cc49f47c99d3f740bebfc426560`。实际43命令于19:33:04.972Z至19:33:05.340Z执行，outer0、无session ID，86份raw stdout／stderr共102,922B全部与执行报告SHA／bytes相符；24个RPM／key／工具首末pins一致，全部命令显式使用同一私有DB，没有安装／脚本／payload执行。root逐21核原verbose输出，均为固定key cac33616的Header V3与V3 RSA/SHA256及全部摘要OK；沿用已接受vendor HTTPS-bootstrap发行标准，不称独立指纹公告已证实。

21组exact header与已接受归属map相同，digestalgo8；35份此前接受的物理文件bytes／SHA均对应一份signed regular file record、empty link target。25路径逐字相同，10条只使用新观察的 `/lib64`→`usr/lib64`固定parent alias及相同完整suffix；root-owned祖先、实际解析dev／inode和首末元数据关系已保存。不使用其它隐式prefix替换，不重复计算逻辑alias为额外ELF。首次map误选归档内旧冻结receipt，旧工件保留并明确superseded，新map绑定实际a884归属查询与91206静态inventory接受链。此次没有重新读取／hash35目标，也不更新旧采集时间；它接受记录的字节与signed包清单对应，不能代表目前所有文件、完整加载闭包或持续持有。actual loader／import／manager／kernel／controller／Full仍未资格。下一来源工作定位同版glibc Source RPM，以核对loader cache／搜索规则的实现和发行补丁；不运行构建或发行程序。

2026-10-08（本地）同版 glibc Source RPM 定位与正文身份已接受。固定两个HEAD观察404／200，8输入receipt `8292d15dbcb067b173b68347b6c96f8eaf96f16d45f98652fca67a4bc059a38b`；原collector将atime纳入identity的P2已修为九字段排除atime，首版和增量审查历史保留。第一次固定GET为403／0落盘字节、outer2，报告未读response body；0B不能证明没发GET或服务端没发送body。只加与HEAD相同的固定User-Agent，独立增量复核后第二次显式GET为200，17,388,972B／`0553c0593565944fa390e8ee4b4c676a9c9303302622dc2394530b36ce5aaa70`，magic、HEAD／GET长度、stream／完整读回摘要相符，22.856831s、inner0。session33757最后工具块未含outerexit，后续poll已无该进程，不合成outer0或退出资格。6输入receipt `647c94e950ddc27ee16531c256071316577c7915237c5b9d70b72c80a403388e`只接受完整body字节，旧403保留且未证明因果。下一步自有私有DB固定3命令验签／source filelist，然后被动源码提取；尚未验签／运行spec或patch／构建／native／完整loader和Full资格。

2026-10-08（本地）glibc Source RPM 签名与source filelist已经有限接受，18输入receipt `f78136fc7eb20733125b0a0e029c3890dd8b82bb1a72b6cfc50a1e211028a475`。实际3命令于20:34:06.467Z至20:34:06.640Z执行，chunk43ba29／outer0／无session，6raw共30,211B与报告bytes／SHA相同；6输入首末pins一致，使用新自有保留DB。root采用既有vendor HTTPS-bootstrap标准接受固定b8f79完整key对应的两个RSA/SHA256签名及摘要OK；没有独立指纹公告的新证据。header为同版glibc2.32／1.20.al8／x86_64，cpio／gzip／digestalgo8；228唯一regular file records（226 mode100644、2 mode100755），empty links，总声明成员18,902,581B，220补丁。upstream glibc-2.32.tar.xz声明16,744,512B／`1627ea54f5a1a8467032563393e0901077626dc66f37f10ee6363bb722222836`。当前仅查询signed metadata，尚未展开payload或逐228成员对比；下一步被动提取和加载器相关patch／spec字面检查。源构建、实际loader／import／manager／kernel／sourcehold／Full资格仍未通过。

2026-10-08（本地）glibc被动payload提取和独立完整读回已有限接受，33输入receipt `350a2ca46cfe26c3b1e345cf32fab50c5d4f4cda3d8c3668519a3db1029a860d`。actual inner0／root观察outer0（chunk512a39→session4579→bdf32d），20:59:52.442Z至20:59:55.286Z／2.844478s；scout对228保存source members和19选定upstream源码重新open/hash，所有source成员name／原mode／size／SHA与signed file records一致；保存副本全部600、目录700，247输出共19,450,603B。两个可选header `sysdeps/unix/sysv/linux/dl-cache.h`、`sysdeps/x86/dl-cache.h`未在该档案找到，不补其它来源。gzip展开18,940,288B；tar展开226,877,440B／18,277members，均在固定上限内。

220已签patch逐个对应spec声明；spec还有Lifsea条件Patch2001，未在签名payload记录中出现。首次要求两个set全等的collector错误保留，修为保留有条件差集；没有运行RPM宏、spec、patch或build。19selected中8个有literal patch targets，38个patch带selected或loader/cache/hwcaps/search词法线索；这是原始upstream字节与补丁文本，未生成最终patched源码。root开始检查cache布局／搜索优先级；发行源码内容、包签名和source审查仍不能单独签实际loader／kernel／manager／sourcehold／Full。

固定 `/etc/ld.so.cache` 当前有界保存与独立readback41193B／`4d0a591a65733883c5bd952b15ca7493f0e5fad58f9fe6694cdec7bc809c5c56`，与旧inventory byte digest完全一致，3输入receipt `26e5f878916a3d77e7a67691fd98cfe403511ec1f513c61c8d88b8af22e8ecf9`。root第一次line16断言包含hash和错误19byte magic两个条件，失败read没有落盘；过早归因成hash漂移的诊断被撤回，失败记录保留，不能反推该次失败read字节。第二次provisional格式判断仍用了19而错误写unknown；确切magic为20byte的glibc-ld.so.cache1.1，后续独立保存数据解析修正，不覆盖该错误工件。cache paths没有follow／执行，actual选择／来源闭包仍待验证。

2026-10-08（本地）cache保存数据解析与旧NEEDED候选关系已有限接受，9输入receipt `506b2e2798e40438a1f25a5e66db12936003fad01e49f4aad749e7cafdc8ca1a`。精确20byte magic、48byte header、639×24byte entries、25,809byte字符串表恰至41,193byte末尾，reserved28–47本样本全0；7合成invalid被拒、1minimal valid接受，不是glibc测试。旧137ELF记录366NEEDED引用／36unique名称各对应1候选，36缓存路径与旧inventory已记录的/lib64请求和/usr/lib64物理端点对应，未匹配和inventory外候选均0；全部candidate hwcap字段为0，flags为771，osversion见0或197120，仅值事实而未作kernel／CPU最佳选择。没有访问cache paths或重新读取physical targets。root正处理先于cache的preload／RPATH／env／sysdep hook来源边界，完整actual loader仍未资格。

2026-10-08（本地）precache限定静态证据有限接受：137旧ELF记录的RPATH_RUNPATH全空，含slash的NEEDED为0，5记录有PT_INTERP；readelf／rpm两工具的ELF_magic未解析保留，但不作为controller runtime node。默认隔离观察/etc UID65534不满足原root-owner前提，leaf ENOENT只记unsupported；随后root原UID／EUID1002视图只lstat固定/etc及leaf，chunk446d93／exit0，/etc uid0／gid0／mode755及dev／ino首末相等，/etc/ld.so.preload首末ENOENT，零内容读取或条目follow。保存端点absence不是持续hold或原子保证。源码显示条件RPATH、env、RUNPATH、sysdep hook、cache、default顺序；19selected只有sysdep hook调用点，定义尚缺。仅针对固定档案准备最多4header的被动增量，必需generic dl-sysdep-open.h；不动态取新源、不跑spec／patch／build／loader。接受receipt见state，不改变正式资格和gate。

2026-10-08（本地）上述generic路径前提被实际档案推翻。修复后的提取器经3项临时合成归档验证（成功、末尾身份漂移、末尾pin读取失败）和独立plan正负检查后冻结，14输入receipt `84fd0c781f9305bd49d7b4ee6b1ee3da74ff3823a96316535358261e9cfb22e3`。实际执行chunk0f16aa／session1616／b54112，outer2；21:39:05.063Z至21:39:07.345Z／2.321287s，18,277成员完整扫描，输入首末pins相等。必需的 `sysdeps/generic/dl-sysdep-open.h` 不存在，故按原计划失败，保留全部输出，不降级门槛或重跑来制造通过。report的 `optional_missing: []` 在required失败前尚未计算，不能视作其它候选存在的证据。

唯一保存的固定可选候选是 `elf/dl-sysdep-open.h`，1879B／`15cecbe86ca0522ee0cd6361007af634a43753795b32df64cceab946805f3015`，独立读回确认regular600／single link／UID1002、父目录700。root全文读到stub函数断言初始fd为-1并返回NULL；这只说明保存的原始源码。220保存补丁的字面搜索没有该头名或函数名；未执行或应用补丁，不证明最终构建选择。header事实可单独接受，整次提取仍保持失败。原准备曾读并hash档案，旧“未打开archive”表述已在保留原件后纠正；没有借用真实运行资格。precache root receipt为 `c89c066e66cb6d8039ec12165b9c2981a5d4579a4a8bb49c0a0baa53ed383af7`；完整loader、import、manager、kernel、sourcehold和Full仍未资格。
