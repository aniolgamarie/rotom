# 受管运行包校验读取与遍历边界

2026-10-09 Root。发现原 _validated_receipt 无界读取receipt和inventory、_package_graph无界遍历使后置B4 caps无法保护前置读取。先修仓库自有公共校验链；不改上游/vendor、不重做SDK、不开放来源资格、不改变state/activation/锁/事务/exception catchtuple语义。所有签名维持现状，无public limits/DI/callback或可由model放宽的参数。

## 固定策略与顺序

唯一生产writer src/agentcfg/pi_runtime_packages.py。复用B4既有量级：MAX_RECEIPT=16MiB、MAX_ENTRIES=65536、MAX_FILE=256MiB、MAX_TOTAL=2GiB；新增 MAX_PACKAGE_DOCUMENT=1MiB（Full原owner-origin已同量级）、MAX_DEPTH=128（运行包静态目录深度）、MAX_PATH=4096 UTF8 bytes、MAX_GRAPH_VISITS=2*(MAX_ENTRIES+len(MARKERS))。这是每次固定源校验的资源上限，不是运行配额或来源身份；缺失/超限拒绝，不截断成功。

_validated_receipt 在原Tree.read('.agentcfg-receipt.json',max_bytes=MAX_RECEIPT)前分配界限，未知/超limit仍沿原status catchtuple变damaged，直接validator依旧原异常类别。inventory树walk在读取/scandir条目append或sorted之前检查全局累计nonmarker entry budget（两个root MARKERS跳过），每文件原stat尺寸在open/hash前检查<=MAX_FILE、累计size<=MAX_TOTAL，Tree.open_read也max_bytes=MAX_FILE，实际chunk增量确认不超所预留尺寸/预算；遇增长/短读仍拒绝。rootmarkers原路径/处理语义保留，未知类型/link escape/owner/mode/nlink规则不放宽。

目录枚举不能先 sorted(os.scandir) 或 list(iterdir) 再检查数量。用原scandir context iterator逐个消费，检查预算后收集有限本目录entry，再按原规则sort；原iterator负责关闭，不泄漏directory FD。每层递归检查depth<=128、relative path UTF8 bytes<=4096再递归/入结果，合法目录mutable size/time不作identity，不使用LOCK_UN或新增真实process。等于cap允许、下一条/一个字节拒绝，source文件body不进错误日志。

_package_graph 同样bounded枚举；原walk、modules、scope枚举都累计graph visits（可能同一目录项因模块与walk访问两次，采用2倍界限），每次先预算再append/sort；深度/path界限同上。保留原graph语义（scope/.bin/.package-lock、node_modules link拒绝、任何夹带包检测）及排序，不用忽略extras或只walk锁路径。validate_installed 对原package/lock以及每个installed package.json所有Tree.read都MAX_PACKAGE_DOCUMENT；其它validator原封闭读取算法维持，inventory先保护完整树的文件尺寸/条目总量，单个descriptor/helper的已有caps不放宽。

## 默认测试与scope

可写上述module及新增 tests/test_pi_runtime_validation_bounds.py，及最多旧test中与新增caps直接冲突的fixture适配（若真需改必须先Root，不自行扩大）。不改Tree/source capture/schema/lock/recipes/其他CLI/manifest/guards/OMP/state/tasks/docs。你不是唯一作者不回退他人编辑。证据 runtime-installed-validation-bounds-implementation-review01，先Root保存生产preimage；有意义RED再实现，保存完整exitJSON/logs/pins/稳定diff/report STOP。

默认真实自有/tmp文件和Tree+旧fake installer，无Popen/SDK/Node/native/账号/网络，原conftest保持。上限故障用私有测试常量monkeypatch到可测小边界，不写256MiB/2GiB大文件；测试接缝不是生产选项。核超receipt在JSON解码前、超file/total在首open/hash前、scandir预算在超条目append/sort前且iterator关闭、目录depth/path拒绝、graph每种枚举拒绝、cap等于正控+1反例，既有sourcegraph/alias/scope/optional/marker行为保持。合法全原fixture状态installed，cap故障statusdamaged、不把环境不安全祖先拒绝当cap证据。

固定默认验收仅新增pytest模块+最少受影响旧installed inventory/graph/status用例（先从 tests/test_pi_dependencies.py 和 tests/test_pi_owner_origin.py/installed_source 选具体必要test；不要跑全suite），test selection写report。真实owner问题使用require_escalated/fresh/tmp basetemp，不放宽权限；默认只自有合成源码无真实宿主，按原session已授权默认测试自行进展。

若存在旧Graph返回顺序/类型或B4 count边界无法保持、上限需要改变/模块ownership扩大、两有效修复仍失败升级Root。此fixed读取资源边界不保证wall-clock deadline或外部malicious concurrent修改下全原子快照，不为future SourceHold背书。formal8/100，AUTO OFF；之前SDK grant不重开，不新增实际探针。

## Root 增长读取裁定

每次原stream.read最多min(1MiB, reserved-size+1)，额外1字节只作EOF/增长哨兵，超出立即拒绝且不hash多余正文。成功读取<=原reserved/累计MAX_TOTAL，失败增长探测最多比累计预留多1byte；不是零超读或任意memory/OOM证明。真实自有文件在原open/stat后append32bytes的反例记录原stream实际返回字节，旧实现读35bytes>reserved3+1，修后<=4bytes拒绝；不靠违背read(count)契约的fake验证这个上界。
