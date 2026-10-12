# 服务索引的固定账户只读发现

2026-10-07，root 冻结索引后续的第一处实际文件接口。它只发现本机原账户下的固定索引，不实现首次创建、锁协调、controller、恢复或产品 endpoint。必须先通过独立设计审查，再实现两份新增文件；纯 codec 的两个容量 P2须先修复并接受。默认测试只读写自己的临时 HOME／fixture，不读取真实账户索引，也不启动第三方宿主。

## 输入来源与可观察事实

公开入口仅 `inspect_service_index()`，不接受 path、UID、HOME、manager、callback、approved、DirectoryIdentity 或期望摘要参数。Linux 上从原 `os.geteuid()` 和 `pwd.getpwuid(uid)`取得账户目录；账户条目应为原 `pwd.struct_passwd`、pw_uid 为相同 exact int，pw_dir 是原 native canonical absolute 字符串。不使用环境 HOME／XDG／Pi profile HOME、不扫描 state_root／storage，不退回任意调用方路径。其他平台在账户及文件读取前固定失败。

账户物理目录须属于该原 UID，不能 group/world writable。原账户路径按已接受字面约束验证（非 `/`、UTF-8至4096B、无空／`.`／`..` 段、反斜杠、C0／C1／surrogate），不能先用 Path/resolve 正规化非法值。使用本包自有、不创建对象的 stdlib fd逐段opener；不是private=False的Tree，因为它仅核最终目录并有意允许共享祖先。每个祖先（包括 `/`）须真实目录、UID为0或原UID、禁止022，系统sticky目录沿现有policy允许022且有sticky位；最终账户仍须原UID并禁止022，不借sticky放宽HOME。账户可以0755／0750，不改用户权限。账户引用只描述这次打开的对象，不产生初始化授权。

账户控制目录固定 `.agentcfg-pi-durable`，文件固定 `index.json`。全操作不调用 Tree、ensure_private、mkdir、write/replace/write_new、flock、proc、subprocess、SQLite、SDK、模型或网络；不触碰 workspace／deployment／认证／会话。仅本包自有 stdlib 只读fd操作和原纯codec，不给旧 helper 打补丁或调用其私有接口，也不用 constructor／哈希造原授权。

## 三种结果与错误

新增自有 frozen/slots `ServiceIndexInspection`，只含五字段：`account_home`、原纯 DirectoryIdentity `account_identity`、`state`、`index_identity`、`snapshot`。其三个外观 writer_lock_verified/database_allowed/can_take_over 始终False。它是过去切点的只读观察；公开构造器及真实文件读取均不签发 capability，不保证返回后仍 current。

- `state="absent"`：在原 account fd 下固定控制 basename 未存在；index_identity/snapshot 均None。账户自身缺失／不安全是错误，不是absent。
- `state="incomplete"`：原控制目录安全、已捕获其 identity，但固定 index 文件不存在；snapshot None。旧空目录、初始化中断和并发尚未发布都可能产生这一事实，不能区分或重建其历史，绝不能据此创建 fresh 服务。
- `state="present"`：安全控制目录和固定索引完整读取，原 public decode_service_index 成功，snapshot 的 account_home／account_identity／index_identity 逐值等于此次真实对象；两个 identity.uid 都等于原账户UID。snapshot 保留所有reserved／registered／初始化请求和关联，读取不修改 generation／排序文件或状态。

任意 basename 对象存在但不是所需目录／普通单链接文件、链接、错误属主或权限、空／畸形／超限 JSON、身份漂移、路径消失、读取或 close 错误，均映射为新自有 `Conflict("Durable服务索引无法安全读取")`，实际cause/context None；不修改外来异常、不输出原内容或路径。仅下述mandatory首次no-follow stat切点明确缺失的控制basename或index basename产生正常分支；存在后的任何open/read/reopen/close失败均是错误，不能用通用FileNotFoundError handler降成absent/incomplete。异常正文不含输入／模型token，traceback locals不承诺全局清理。

## 固定目录与读取切点

先验证 native 账户来源及UID范围。自有opener从固定 `/` 的 `O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC` fd开始，用原canonical字符串逐段打开；每段先no-follow stat拒非目录，再按原parentfd相对open并比较原stat与新fstat的device/inode/UID/mode，核祖先policy后关闭上一自有fd。每次open后的校验失败也须关闭该新fd。取得原accountfd后核最终账户policy和DirectoryIdentity；返回前用同一只读算法重新打开路径并比原accountidentity及policy。

在原accountfd下 mandatory no-follow stat控制basename。仅该首次stat的FileNotFoundError进入absent候选：不open该basename，最终再stat仍缺失并核原账户／路径／pwd才返回。存在则必须原UID的exact0700目录，再以固定flags相对open并将fstat与首次stat比较；保留原account/index两个fd到结束，路径消失／替换／open失败均拒绝，不退回缺失分支。

在原indexfd下另有 mandatory首次no-follow stat(`index.json`)。仅该stat的FileNotFoundError进入incomplete候选；此分支不open或read文件，最终再stat仍缺失且原目录／账户/pwd复核通过才返回。首次存在则立即核exact0600、普通单链接、原UID和0<size≤16MiB，再相对原indexfd以`O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK`打开；比较原stat与fstat八项device/inode/mode/uid/nlink/size/mtime_ns/ctime_ns。用有界原os.read循环（每次至64KiB、总至16MiB＋1、EOF停止）取完整bytes，超限或任何读错误拒绝；decode前后再核原fd/固定basename八项完整identity，不从文件内容构造物理身份。存在bytes按固定原codec解码，不修复畸形。

返回前再核：原账户fd及重新逐段打开的账户identity/UID/禁止022；原account basename仍对应原控制fd、UID和0700；present的文件原fd／固定basename仍有八项完整identity；incomplete的文件仍缺失；最后重取原账户条目核pw_uid/pw_dir相同。复核只比较原native数据，数据对象没有许可属性。目录mtime／子目录内容不当服务身份；路径即刻重核也不是内核原子多对象快照或阻断任意同UID外部改写。所有自有handle均CLOEXEC、无继承，在返回前各自尝试一次close；一个close错误不能跳过其他handle的关闭。close失败固定拒绝，不声称fd已物理关闭，不重试可能复用的raw fd或宣称kernel恢复。只关闭本次实际新开的handle，不关闭外来fd3或其他进程对象。

absent/incomplete只陈述有限读取切点；即使两次检查缺失，中间是否存在／曾发布仍未知，不用于首次初始化或自动接管。present没有打开storage/SQLite或检查writer死活，不能据其stage推断ready／released。任何后续写者仍必须从原初始化producer、current Full引用、原协调锁及新的物理对象重新捕获写入前提，禁止把Inspection当旧expected文件身份或授权重用。

## 两文件实现与默认验收

唯一writer只新增 `src/agentcfg/pi_durable_service_index_readonly.py`、`tests/test_pi_durable_service_index_readonly.py`。旧codec／registration／Tree／paths／guard、清单及文档不改。复用public DirectoryIdentity/ServiceIndexSnapshot/decode_service_index；路径与fd访问为本包固定、只读stdlib算法，不调用旧模块私有helper，也不伪造十三字段record校验账户来源。新模块可为字面native路径和原os.stat结果做本包小校验，所有新class均仅自有slots。系统函数测试别名仅本模块名，不全局monkey patch os/pwd或上游对象。

默认临时账户由测试原 `pwd.struct_passwd` fixture 提供，仅替换本模块账户查询方法；它不是产品原引用或初始化capability。真实临时目录和文件构成读取正例，分别覆盖absent无创建、incomplete不修复、present reserved／registered／多关联和字节不变。设置与fixture账户不同的HOME/XDG证明不读环境账户；用写方法／进程／锁／模型哨兵保证拒绝路径零相关调用。全部默认 guard 保留，不能对真实账户执行inspect作smoke。

负例从合法原目录／索引开始，仅改变一个约束：错误账户UID／路径／平台、不安全祖先、控制目录链接／错误mode/owner/type、文件链接／多硬链接／mode/owner/type、空/畸形/超限JSON、snapshot错账户/indexidentity、原目录/文件替换／读取中消失、mandatory首次present后stat/open间消失、返回前current账户变化、close异常和foreign异常未改。捕获本模块open/read调用可证明首次missing分支没有打开正文；祖先共享非sticky022应独立拒绝，安全系统sticky临时目录和0755账户保留合法控制。无法由默认环境产生的非本UID对象用受限stat结果替身注明事实层，不以其证明内核UID攻击防护。FD泄漏检查在临时目录自有对象边界，不能为了观察打开真实proc或第三方宿主。

验收同次新只读suite＋已接受索引与registration原suite；正常属主 `/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -m pytest -q tests/test_pi_durable_service_index_readonly.py tests/test_pi_durable_service_index.py tests/test_pi_durable_registration_record.py`。新模块不存在的collection error仅未实现；新反例发现实际错误需保留同旧完整实现red与修后green。稳定源码停止后root和独立executor最终审查。需要扩大到创建／锁／服务／真实账户或原生时交root重决策，不因已有八场授权执行。本包不解除正式7/100、产品gate或严格计量前AUTO OFF。
