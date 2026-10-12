# Full 来源的物理投影：候选数据边界

2026-10-07 root候选。本稿接续current公开五字段与installed-origin方向，只决定后续FullSourceView里物理元数据的表示和隐私边界，不授权实现codec/IO/registered reference/hold，也未冻结完整FullSourceView。原B2默认接线已接受77输入receipt cde031；它不证明这里的真实actor、持续持有或初始化权。Linux为本次支持范围。

## 与内容投影分开

原deployment/current及其generation可能受私有endpoint影响。文件stat事实与公开五字段可以分别参与新的非秘密关联；原state bytes、generation/preimage、未选择字段值及它们的digest均不能进入共享身份。不能先hash整文件再声明输出只有hex所以非秘密。

对可能含私有内容的current、实例manifest或policy，下一读取包必须先逐文件确认分类。未确认固定公共producer与完整字段白名单时，一律只允许物理投影及已明确的公共字段；不允许raw SHA进入共享身份。原actor可在自己私有状态保存其原验证引用和必须的本地比较，不能把这些私有值打包为新的public token。这里没有证明实际manifest/policy已公开、已有合适的本地validator，或以物理tuple取代内容语义校验。

完整固定公共producer生成的installed origin、npm锁对、sealed运行文件、角色/自有source、发行资产可另用实际原字节SHA；这须以它们各自正式来源、schema和完整物理核为前提。body名称、JSON合法、同UID或一个旧hash不是公共producer证明。

## 候选 exact 数据表示

所有跨Python/Node的物理数值用exact native str的canonical十进制表示，避免JSON number精度损失。unsigned只接受`0`或无前导零的正数字串；signed只额外接受负号加非零数字，不接受`-0`、`+`、空白、小数、指数、hex、bool/int替代。以下范围是**新Linux入口的支持域**，不声称通用stat或其它平台都满足；原producer实际值超域即unavailable，不截断、取模或自动改域。

后续完整接口须在十进制parse/BigInt转换前先核exact str及长度：uint64至多20字符，uint32至多10字符，signed64至多20字符（计入负号），之后再核canonical语法及精确范围。不得先解析无界字符串或经Node Number中转。本稿仍不授权单独codec。

| 投影 | exact keys | 域 |
| --- | --- | --- |
| directory | device, inode, uid, mode | device/inode为uint64；uid为uint32；mode为uint32的完整st_mode，包括类型位 |
| file | device, inode, uid, mode, size, mtime_ns, ctime_ns, nlink | device/inode/size/nlink为uint64；uid/mode为uint32；mtime_ns/ctime_ns为signed int64 |

只接受两种exact native dict及其固定exact native str键和值，所有键先单遍typed捕获再lookup/哈希；未知/缺失字段固定失败。file和directory种类由完整FullSourceView的固定slot决定，不接收一个caller自称kind字段。此表没有路径、FD、raw内容hash、owner权限布尔或能力外观；public文件的实际byte digest也不擅加到这个file形状，应在完整slot schema中另明确。

codec只能检查数据域，不能核fstat、文件类型、uid是否本次账户、link/mode准入或named关系。实际source reader须在取得原对象时检查完整类型位、原账户/policy允许模式、同设备边界、单link文件、size与该文件具体读取cap，并用同一原FD读回后复核原named对象和文件元数据。目录投影不包含nlink、size、mtime、ctime或内容清单；合法创建文件不因此使目录对象身份stale。目录下面的文件、角色和精确集合仍须各自校验，不能因目录tuple不变跳过它们。

不同文件slot可有不同size cap，uint64编码域不放宽任何实际读取上限。物理投影只是原观察的detached数据，不是atomic snapshot、open许可或持有证据。目录/文件同名替换须由原held FD及named关系检查发现；tuple本身不解决inode重用、读取间竞态、任意同UID攻击或不受控制的系统维护。

物理size/timing也可能透露文件变化关联，不能把排除原secret值/hash称为隐私不干扰证明。完整材料及数值投影仅交付本次受信actor的私有启动/来源上下文，不进入通用配置、日志、错误或公开诊断；后续完整slot schema须明确最少必需披露，未选择的stat字段不自动加入。共享非秘密关联仍要遵守上述内容排除与原producer限定。

## 两类共享关联的分工

未来`R.initial_deployment_identity`应使用明确的新domain加已接受的current公开五字段、原actual current文件物理投影和必要的固定目录slot关联；不用旧私有generation或whole state SHA。未来`source_identity`则覆盖完整FullSourceView：上述关联、正式installed来源及锁对/完整receipt与inventory、固定角色和源映射、原解释器资格等。两者的exact整体schema、slot集合与hash preimage仍未冻结，不能据本表开始签发或持久保存新的身份。

一旦冻结，digest应复用仓库原非秘密canonical数据算法，并明确Python/Node相同UTF-8字节；不为这几个字段另造与现有算法相似的实现。public数据相等不是原startup actor/manager activation/oncegrant/匿名channel相等；原私有validator必须独立核原调用上下文、实际来源及同一私有引用。manager不能从这个数据反推另进程的Workspace，child也不能由它选择新root或得到storage/Node/DB权。

替换写入后必须实际readback取得新file投影；`Tree.write_state`的旧expected tuple不是发布后的身份。原受管mutator在启动/活动/unknown阶段与PersistentSourceHold的排他语义、guardian的独立寿命、原账户/instance/state_root/runtime保护及最后核仍由完整持有包冻结。活动服务保留原SID/storage/runtime/budget，不能因新current或同public projection而重建原能力。

## 后续有限验收

完整包默认测试须分别覆盖十进制边界/非法编码/unknown/foreign零方法、所有字段detached；目录mtime/size变化不改变目录对象投影、文件原inode/owner/mode/size/times漂移拒绝；同公开五字段但不同actual file或原上下文零grant；虚构私有state哨兵值与其digest不进入输出/错误/公开摘要。纯codec测试不能代表这些真实IO或准入已执行。

实际读取需临时完整受管Full正控制；source-only序列化、假original context、旧receipt或B2安装成功不能签发资格。未来解释器/FD/owner/长期hold组合另准备独立材料与授权，不复用已闭合Harness8/FD6。正式7/100、产品gate未通过、严格计量前AUTO OFF保持；Recovery3 d61799精确三场已执行验收并闭合，不授此组合权限。当前仅候选文档，先作独立有限审查，再与完整接口一并决定实现范围。
