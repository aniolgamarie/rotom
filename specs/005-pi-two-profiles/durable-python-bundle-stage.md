# Python bundle 的私有 stage 写入组件

2026-10-07，root在纯数据组件和当前七原档案数据编译通过后冻结下一限定包。仅在仓库／临时HOME中的合成stage实施默认验证；不运行已捕获的第三方包、宿主或native扩展。正式Full声明、原来源producer、生命周期和产品安装接线继续保持未资格化。

## 接口和唯一写入者

唯一实现者新增 `src/agentcfg/pi_python_bundle_stage.py`、`tests/test_pi_python_bundle_stage.py`；不改已接受的纯数据内核、旧测试、stage调用链、schema、声明、lock、vendor、launcher、controller或Base入口。公开IO接口为：

`install_python_bundle_stage(stage_fd, declaration, artifact_bytes, *, occupied_files) -> None`

stage_fd是原installer已打开的私有scratch stage目录的借用FD，必须exact native int、非bool、在0..2147483647内；函数仅持有自己的dup，不关闭caller的FD。不接收路径、外来plan、callback、Workspace/PiLock、accepted布尔或权限工厂。返回None只是这次scratch写入及readback成功；FD、JSON或函数结果不构成Full来源、初始化或执行授权。未来产品caller仍须先满足原正式selection／source／stage所有权与锁，再自行供给固定来源数据；本包不添加这个caller。

先以有界exact-native递归copier复制declaration和occupied_files为本地快照，不调用deepcopy或先对caller容器运行validator；每份分别保持原generic walk的100000 nodes／depth16／string4096字符及strict UTF8／signed64界，active容器ID检测cycle，容器只逐项复制、累积前限量。只接受原JSON native类型，无getter、foreign iter／repr／hash／deepcopy调用；并发变更中遇到foreign或遍历失败即固定错误，不解释外来对象。artifacts先exact dict／len7、native string keys和native bytes检查，每archive最多2MiB、总量8MiB，复制有界map且共享不可变bytes。然后对这三个本地快照调用原public planner完整重核，之后不再读取caller容器。不承诺三容器的原子一致捕获或来源持有；这些仍不是authority。物理prefix检查不能用占用数据代替。所有档案、RECORD、marker、caps及sha校验完成后才可能创建bundle输出。新模块只依赖stdlib和已接受的自有纯数据内核。

## 固定物理边界

dup后的stage目录须真实directory、本euid所有、精确0700、无特殊mode位。不从FD猜测或拼接绝对路径。所有后续IO均以held目录FD的openat／mkdirat等公开stdlib操作执行，O_NOFOLLOW／O_DIRECTORY／O_CLOEXEC；创建文件另加O_CREAT／O_EXCL。目录不检查会因自有写入而变化的mtime／ctime／nlink作为恒定来源身份。

固定`supervisor`必须已存在，真实目录且本euid所有、无group/world write／特殊mode；不创建或chmod它。stage直接子项对supervisor作大小写唯一检查；supervisor直接子项中任意casefold等于`python-bundle`的项均拒绝。两处扫描有固定4096项上限，在累积前限量。其余stage树不递归读取或修改；完整外层seal属于原caller。随后只以mkdir排他创建`supervisor/python-bundle`，已经存在／link／case别名／部分旧输出全部失败，不复用、不覆盖、不自动修复。

仅在新prefix内按计划创建0700目录与0600普通单链接文件。路径来自该次内部planner，借用FD和每层held目录FD保持在各自with作用域；不得通过Path.resolve、chdir、字符串绝对路径、任意输出路径或ZipFile.extract实现写入。目录遍历最多原path_components界；新prefix及所有新目录保持原device／本euid／精确0700。已有supervisor模式保持原值。

## 原字节写入与完成条件

planner已对不可变archive bytes逐成员完成自己的有界ZIP/framing／decode／CRC／sha检查；复制可以使用未改动stdlib `zipfile.ZipFile(io.BytesIO(raw))`的公开read接口，固定读块最多65536字节。不执行extract/install/pip/import/sys.path操作，不生成脚本或pyc，也不复制archive到运行树。全部163类计划成员包括原RECORD、dist-info、schema/resource/license和native bytes按原字节保留；不能对native成员借用仅1MiB的metadata capture通道。

每个文件的写循环正确处理short write，零进展失败。创建文件后只调整自己的FD至0600；记录其dev/ino并核普通／本euid／单link／mode，逐块核长度／sha、fsync并明确close。with helper必须在其__enter__中取得FD后立即进入try/finally，避免先取得FD再分配contextmanager／ExitStack callback的泄漏窗口；不使用会在enter后追加登记的动态ExitStack。借用FD始终保持；每个owned FD只尝试close一次，失败不能重试一个可能已被复用的整数。

内部path→(dev,ino)表记录排他创建的prefix、每个新目录、每个成员和inventory；目录记录在创建／首次held FD核后保存，文件记录在原created FD上保存，已有stage／supervisor原identity另记。不接受caller提供的identity表。所有成员关闭后，只扫描新prefix并有界验证其精确文件／目录集合、大小写唯一、类型／mode／单link／uid／device和这套created身份。重新O_NOFOLLOW打开每文件，核same-fd前后dev／ino／type+mode／uid／gid／nlink／size／mtime_ns／ctime_ns、长度和sha；不只信写时的hash或inventory对象。目录检查只含稳定dev／ino／type+mode／uid／device，不将自有写入改变的time／nlink当不变量。扫描上限由当前内部plan推导且不超过原set_entries／planned_directories界。目录集合与origin不靠运行时filesystem推导改写。

在成员与目录readback成功后，才以0600／排他创建固定inventory.json，内容是同一内部plan的inventory_template。用本模块stdlib按原canonical契约序列化：UTF8strict、keys排序、compact逗号／冒号、ensure_ascii=False、allow_nan=False、无尾newline、编码前后有界累计最多16MiB，不调用纯内核private helper。fsync／close后再核原字节／mode／inode，随后自下而上fsync新目录及supervisor。inventory是完整外层seal中的待接入文件，本身没有ready／authority语义。仅全部close、readback、fsync返回后才正常返回None。

任何普通错误返回新的固定`ValueError("pi-python-bundle-stage")`、自身cause/context清空且无输入／路径／payload正文；调用方外层异常不被修改。清理优先级明确如下：原body已经active的BaseException原对象最高优先；否则清理中首次BaseException优先于普通body／cleanup错误；全部普通错误统一上述固定ValueError。无论优先保留什么错误，所有已取得owned FD均继续各一次close尝试，然后才按优先级透传；不以close异常覆盖原KeyboardInterrupt／SystemExit，不重试任何可能已复用的FD整数。BaseException不被替换为普通错误。已创建的prefix可能部分保留，函数不递归删除／回滚／覆盖，caller须丢弃整个scratch stage；没有fallback、ready或发布。close/fsync失败不称物理成功，不因部分inventory存在而继续seal。

## 必要默认验证

使用完整自有七wheel合成fixture和真正临时FD／stage，不借FakeWorkspace／PiLock／acceptance状态制造来源资格。正例覆盖stored／deflate、超过1MiB的native合成成员、原RECORD／许可证／资源／marker与byte-by-byte readback、0600／0700、目录集合、inventory／canonical、caller FD仍可用、stage和supervisor原文件／mode不变、无包执行和网络。不得读原wheel或导入其native bytes。

负例包括数据不合法／hash／RECORD错时零新prefix、foreign callbacks零触发、坏FD／fileFD／bool／wrong owner／unsafe root／缺或link supervisor、case别名、已存在prefix、occupied冲突、不允许字段／路径。注入short write／zero write、open／mkdir／dup／fchmod／readback drift／fsync／close异常，核固定错误、已有文件不变、caller FD保持、可观察的owned acquisition各一次close和无正常返回；collector按获取事件而非可复用FD整数计数。必须配对body BaseException+close普通错误、body普通错误+close BaseException和多FD清理继续的优先级；outer异常不修改。还须在本地快照后变更caller容器的合法对照、foreign／cycle／cap拒绝和全部目录／file／inventory身份漂移负例。模拟close异常不伪称kernel已经关闭。真实private stage生命周期不在本包授予。

验收命令为原测试Python执行`pytest -q tests/test_pi_python_bundle_stage.py`；原offline／temporary HOME／owner guards完整保留，必要时按已有授权在normal-owner执行。内核387默认及当前七数据证据不因新IO组件无源变更而重跑；只有新证据揭示其问题才扩大检查。唯一writer STOP后针对稳定diff独立审查，再由root验收组件。

本稿待有限设计审查后实施。没有实际stage hook、正式Full来源／声明／schema、CPython／ABI／真实import／原生／产品通过；正式7/100、AUTO OFF和Recovery3待本组三场明确授权保持。
