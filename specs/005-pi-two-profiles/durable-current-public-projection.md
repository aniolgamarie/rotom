# Current 的公开投影：后续来源 API 的有限设计

2026-10-07 root草案。仅定义共享FullSourceView中current公开部分的候选字段，不授权实现或授予初始化权。完整FullSourceView、原私有validator/issuer、physical hold与调用顺序仍须一起冻结；不为这几个字段另建提前签发资格的模块。已有原producer/嵌套validator静态证据分别归档d6dd26/52f5aa。

## 原材料与隐私边界

原deployment producer的current有generation/binding/launch/items；Workspace.binding只有machine/local/profile。launch由runtime.record生成，含argv、lock_identity、shared_files、preflight、machine、environment，以及条件加入的runtime_identity/runtime_guards/adapter_binding。现有validate_saved_state只核item基线及凭据引用，不核整个current或launch的公开shape，不能用它作为投影filter。

原generation及其preimage、items的内容/摘要、binding.machine/local、launch.argv/shared_files/preflight/machine/environment/runtime_guards/adapter_binding均不进入本投影。公开投影只选原binding.profile与原launch中的两个身份；非秘密性取决于未来原caller从正式公共lock及原backend取得并逐项重核的producer，任意JSON的同名字段和合法hex本身不能证明值无秘密或来源可信。不得把caller的整个current对象、原state bytes或private字段hash纳入公开摘要。

## 候选 exact shape

下列literal profile与hex64是本次**新Full入口的显式支持前提**，不是从通用Workspace.profile或runtime.record/safe_id推导出的全局属性。原Workspace的profile仍来自resolved profile ID，通用backend身份也不因此被收窄。未来来源API须从正式Pi现代profile/所选Full契约确认本次profile确为pi-full，并从原Pi完整lock/该次backend算法重核两个身份符合本域；其它agent、自定义profile或未匹配本域的旧运行路径不能进入此新Full入口。当前没有据此接受任何实际Full来源。

| 字段 | 类型和值 | 原producer与含义 |
| --- | --- | --- |
| schema_version | exact native int 1，拒bool | 新投影版本，不能暗示原deployment已有此schema |
| profile | exact native str，literal pi-full | 新入口只支持该固定Full选择，再核原Workspace.binding.profile；Base不捕获/导入Full投影入口 |
| lock_identity | lower hex64 | 新入口要求的Pi锁域；原runtime.record仅提供lock.identity，未来必须与该次实际已核完整正式lock相等 |
| runtime_identity | lower hex64 | 新入口要求的Pi运行域；从原launch.runtime_identity或明示缺省编码取得，须另核实际backend而非依赖通用safe_id |
| runtime_identity_encoding | literal explicit 或 lock_identity_fallback | 保留原记录是否显式存储runtime identity，避免悄悄补齐材料 |

原runtime.record只在原backend实际runtime_identity不同于lock.identity时写runtime_identity，缺省表示二者相等。因此缺字段时，投影按这个原编码规则赋runtime_identity=lock_identity、encoding=lock_identity_fallback；存在则必须合法hex64且encoding=explicit，不能因非法/null/空值而fallback。未来原actor必须另外调用原backend并重核编码关系、实际runtime、Full selection及角色资格。缺省数据不能当“旧运行包符合现代Full”；若真正Full来源缺其他材料仍拒绝。这里不改变原runtime.record，也不从公共字段推导runtime root。

输出严格五字段、detached JSON，无private对象、路径、FD、布尔qualification或来源cap。此小投影的hash不能独立用作source_identity或R.initial_deployment_identity；完整身份还要绑定原账户/instance/state_root/runtime目录对象、该次actual current文件、installed origin/所选锁对/receipt/完整inventory及固定角色和私有原调用上下文。

## 后续实现须维持的不变量

未来新Full来源入口仅在正式Full选择后捕获：对current/binding/launch各个exact native dict，仅单遍有界捕获typed键与值引用，在验证键类型/固定键集合后使用自有浅层映射；不深拷贝整current、不重复操作caller可变字典、不在验证key类型前hash/lookup，也不调用foreign对象方法。未知current/binding/launch**字段名**固定失败；private/动态字段值仅为不透明引用占位，不检查类型/长度/内容，不递归、不转换、不序列化、不hash、不日志化，也不对它们应用公开字段的type/size cap。之后只从自有捕获映射读取profile及两个identity并作exact native值校验。限制须在完整来源API包给出，不将原item大正文与新小投影字符串上限混同，或因未选择的private值大小/类型触发隐式repr。浅层捕获不是原子快照或来源cap。

普通错误统一新固定消息并清cause/context；控制BaseException保留原对象。public结果仅为数据；manager/private validator必须独立重核原实际来源及调用者，不能从这个JSON、profile名、同UID、hex、路径、先验verified标志构造registered reference。child先按原协议预留fd3并核自身固定角色；读取JSON不是storage/Node/DB许可。

原文件替换后必须实际readback取得新文件身份，不能把write_state传入的旧expected tuple当发布后身份。文件tuple与目录(dev,ino,owner,mode)分开，目录不使用会因合法自有写入改变的mtime/content。跨语言字段的数字编码、文件内容与named关系的读回、hold及最后核须在完整FullSourceView包定义；本稿不把静态端点SHA称连续持有或原子快照。

## 设计验收和后续真实检查

后续完整来源包默认测试需要覆盖：五字段exact shape、unknown字段/bool/nonhex/null/missing拒绝；两个原runtime identity编码分支及原actor实值不一致；ignored private值与foreign对象零方法/零输出/零摘要；迟到caller键变化不触foreign方法；原Base零Full可选访问；相同public投影但不同actual current文件/角色/source/原调用上下文不能取得grant。完整raw state中插入虚构private哨兵，所有公开输出和错误中不得出现其值或摘要；不读取实际账号。

单独投影数据测试不能替代实际current文件/原backend/原installed Full重核、同一私有引用最后核、原caller/channel/grant、长期sourcehold、独立guardian及正式启动验收。B2与B3默认安装材料已分别验收，仍未签Full来源资格；formal7/100、产品gate未通过、AUTO OFF保持。Recovery3 d61799精确三场已执行验收并闭合，不授当前source/native组合权限。
