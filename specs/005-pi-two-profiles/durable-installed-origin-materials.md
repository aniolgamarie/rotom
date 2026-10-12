# Installed origin：安装材料与身份分工候选

2026-10-07 root根据有界producer证据整理下一包候选。它接续[来源路线](durable-installed-origin-contract.md)和[锁metadata数据接口](durable-lock-metadata-data-api.md)，尚未授权新增生成文件、runtime row、schema、producer/reader或正式锁。数据接口正在实施，未做最终稳定验收；这里不重复其输入捕获算法。

## 原producer观察与缺项

原现代`_sync`持有真正`read_lock`的完整metadata和所选npm原bytes；npm pair已按slice固定路径写入stage。launcher只复制声明的runtime rows。原bundle hook从stage的`runtime/durable-python-bundle.json`读取声明体，不替caller寻找或生成正文。当前正式`dependencies-modern.json`未声明该row，也未完整分发锁metadata、固定根schema和数据接口/helper闭包。B1强制ref配套row、B2有限合成Full正例提供row；当前正式缺项与该正例不矛盾，不推导实际Full已安装。

有界source观察为scout的`/tmp/pi-durable-installed-origin-producer-seam-review01`报告；其中dependencies是writer实施中的阶段源，不是最终稳定diff审查。其它source首末pin仅为端点检查，不是连续持有或实际导入证明。报告列举的缺helper是最小缺项，不是完整import closure。下一正式生产包必须另核全部stdlib/自有module/第三方依赖、固定schema及所有数据文件，不能补几项row后称closure完整。

## 候选文件格式与实际绑定

保留固定Full-only文件`runtime/durable-owner-origin.json`。候选内容为下面五键；所有字符串和metadata必须来自该次原installer的已核材料，而非callback、用户overlay、另一次lookup或caller数据声明。

| 字段 | 候选数据规则 |
| --- | --- |
| schema_version | exact native int 1；仅origin envelope版本，独立于锁schema版本 |
| profile | exact native str `pi-full` |
| lock_identity | exact native str lowerhex64，与metadata.identity及该次原lock完全相同 |
| runtime_identity | exact native str lowerhex64，与该次原backend算法得到的runtime identity完全相同 |
| metadata | 完整detached原v2锁metadata；不得只留selected slice或重建不完整sources/catalog/providers/selections/build map |

envelope不含source_identity、origin自己的rawhash、sealed inventory/receipt、generation、private preimage、state rawhash、路径/FD、role token、accepted/qualified布尔或可调用引用。它是数据而非资格证明。正式schema还须绑定闭合字段、canonical原UTF-8算法、raw读取cap与graph cap、错identity/profile/版本/未知字段错误，并逐项证明公共producer及秘密排除；未完成这些不能开始写文件。

后续完整producer须把所选npm pair、bundle正文和七原vendor bytes按原固定路径物化并纳入sealed inventory。这是下一包的目标条件：当前正式配置尚缺bundle row，本轮没有核actual Full安装或完整closure；所选wheel原vendor留存只引用此前限定证据。origin metadata仍通过新data API与实际取得的pair/body组合核，完整源archive/build/license/runtime物理核不由此替代。原完整receipt/inventory、正式provider选择、固定四角色、解释器资格和当前来源仍需各自实际重核；不能从envelope合法生成RegisteredReference。

## 避免身份循环

原runtime identity在stage创建前计算，现有摘要输入为原lock/slice/platform/toolchain和v2 selection等数据，不含生成文件或sealed inventory。候选origin可携带这个已经算定的值，再由原seal把文件纳入inventory；不重新定义runtime算法。此判断只对应观察到的原算法，最终producer修改后还须复验输入没有改变。

未来source_identity覆盖来源view时，origin及其完整inventory可以作为输入，但不能把该source_identity再写回origin或同一preimage中的inventory/receipt，从而形成自引用。共享source identity只能在实际材料核完之后由各actor独立计算并置于其私有引用/受控启动关联，不能在stage写一个“将来的来源资格”字段。完整FullSourceView与其hash domain仍待单独冻结。

## 写入窗口与Base边界

候选落点是原optional bundle物化之后、原seal之前；新文件必须进入原inventory及`validate_files`精确expected集合。不能把同名文件加入所有profile的通用GENERATED、允许额外任意runtime JSON或跳过原seal。具体Full owner选择谓词、声明角色、来源row、固定schema路径与分发、生成/读回/最后核流程仍需下一完整包批准；仅有`profile==pi-full`或bundle ref不是来源资格。

Base普通路径不声明/读取origin，不import可选数据resolver或探测Full服务。正式尚未接入的Full不启用origin writer/reader；未来缺材料/角色/来源资格必须明确unavailable，不fallback旧repo、系统Python、任意provider或当前另一个runtime。插件替换产生新的锁/绑定/runtime来源，活动服务保留其原来源与budget，不能靠同格式JSON把旧provider状态自动迁移。

## 下一包验收

默认完整临时Full正控制须实际经过原read_lock、producer、seal、activate、status与原内容读取；NPM/过程仍可按默认边界fake，但不能mock掉data核、expected集合或seal/status。验证完整metadata逐项一致、所选pair/body配套、原schema与helper实际留存、origin字节/inventory/runtime身份独立对应、任何关键内容漂移成为damaged，以及Base零可选读取/导入。default data成功不计正式Full/CPython/ABI/许可证/来源hold/initializer资格。真实组合仍需新的独立授权，不复用旧Harness8或FD6；Recovery3待原精确新授权，formal7/100和AUTO OFF保持。
