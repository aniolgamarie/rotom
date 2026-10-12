# 独立持续 SourceSH reader 资源

2026-10-09 Root。已查到supervisor只有bootstrap/life/state继承，长期复制现有EX与普通启动目标冲突。本包提供独立source SH资源生命周期；尚不提供SourceHold/FullSourceView/principal、不启动holder/controller/SDK，不把数据观察等同来源资格。

## API / 共享原语

新增 src/agentcfg/pi_source_reader.py：hold_source_reader(workspace) 无其他参数，只exact Workspace/PiAdapter且pi-base/pi-full。固定已有instance/source.lock，SH且create=False，绝不mkdir/创建anchor/重新从DTO取得FD。先按当前state_root/binding用bounded原Tree.read核已有private .agentcfg-instance.json 0600/singlelink与expected json_bytes；legacy/Base早gate不做Full服务/owner/capture可选读取。Base可有普通source reader，但不引入Full任何能力。

允许在 src/agentcfg/pi_source_latch.py 仅提取共用私有 acquisition/cleanup/held-check helpers：原bool/path验证、Tree原取得、固定flags/open创建策略、flock一次、_check与yieldNone/finally端点核/close→Treeclose错误优先级保持。所有原public/private被旧测试使用的入口签名保持；旧 source_latch 仍yield None、不暴露FD/Reader。新holder不能用generator frame/私有宿主API取locals，不复制另一套flock acquisition。共用helper只被own代码调用，不接受FD/权限DTO；未完整返回资源前的失败cleanup每自有FD与Tree一次。source_latch原现有after-body monkeypatch故障测试仍有效（不得把老endpoint观察改成永久冻结global而悄悄消除测试）。

新reader工厂对完整返回的自有Tree/sourcefd保存原objects及方法/receiver（Tree.parent/close、os.fstat/stat/close/geteuid、fcntl.fcntl、threading.current_thread/main_thread，必要原helperfunction）。主线程创建；检查发生前先capture方法，非main零acquisition。保存source physical dev/ino/mode/uid/gid/nlink/size（既有anchor0B/600/单link）、root dev/ino/mode/uid/gid以及status/fd flags，确认RW/NONBLOCK/CLOEXEC；不反复flock/LOCK_UN/dup。源码源状态不是由mode或FD数字认证的，resource所有权非来源/actor权限。

返回registered原 SourceReader，不可公开构造/copy/pickle/DTO/fileno；只check()、close()。private强registry原receiver/thread/workspace/held对象；工厂registration部分成功后捕获异常也必须先retire再cleanup。check按原方法核held/named anchor、held/named root及marker原bytes、source flags、原Workspace当前profile/agent/paths/binding与初次相符。源码/运行包内容未由此重验，不导入Full观察器、不声称源资格。目录size/nlink/time不作为identity，自有activity写入不使reader失效。

close先核原object/ownerthread/活性，永久retire，再逐项清理：最后完整端点/marker/context核失败应报告固定failure；其中仍能以原fstat确认held source tuple/flags属于原记录的sourcefd允许close-only一次（named对象stale不自动视heldfd foreign），已观察held改变/关闭/未知则零close该fd。原Tree held directory tuple仍相符才调用其原bound close一次；未知/foreign则跳过，不因一个资源失败阻断另一仍自有资源一次清理。close异常不retry，没有released/child exit/storage proof。wrongthread/foreign不retire合法record；重复close/check拒绝。无contextmanager/destructor/finalizer自动释放，reader仅保留sourceSH和原Tree，不保存life/stateEX。任意同进程篡改和同一物理对象reopened OFD不可区分不由本包证明。

自有固定PI_SOURCE_READER_INVALID /exit4，无raw path/Workspace/marker/body/foreign exception cause/context，bad参数binding也固定；资格仍false。

## 默认真实验收 / ownership

唯一executor可写 source_latch.py私有提取、新source_reader.py、新tests/test_pi_source_reader.py；原tests/test_pi_source_latch.py不改。root archive先保存旧生产。你不是唯一作者，不回退他人改动。证据 persistent-source-reader-implementation-review01。其余lifecycle/runtime/host/Workspace/guards/profile/locks/schema/OMP/state/tasks/docs/vendor不写。

默认真实自有/tmp Tree与flock、actual Workspace/PiAdapter、fixture无模型/账号/SDK/第三方宿主/进程/新线程。thread观察用模块fake函数，不触发真实线程或fd3；原conftest断网/假进程保持。真实owner require_escalated+fresh/tmp basetemp，日志/data，不放宽祖先。只有Root必要默认测试：新module + 原source_latch完整（37不同现有cases数量由实际collection报告，别照旧数猜）+source_lifecycle必要一例，绝不全suite/native。

有效RED先测持续持有：新reader已握SH，原foreground source_guard+真实state instance_lock退出后reader仍阻止mutatorEX（零写入）；旧life/stateEX已释放则新source_guard(SH)+stateEX可以成功，普通启动准入不借偷释放SourceSH通过。两reader共存/EX冲突、无Full可选读取、missing/unsafe/binding拒绝不创建、mutable dirs/activity不stale、原tuple/flags/named/marker/context漂移、capturedmethods/callbackreceiver、wrongthread/foreign/copy/registration-after-insert故障、close原Tree/source各一次/失败不retry/对namedstale仍清known-owned、不关闭已观察foreignheld；fixed errors与链抑制。旧context yieldNone/cleanup组合优先级/after-bodygid捕获等原控制保持。

资源顺序或抽取影响旧错误语义/ownership须Root裁定，同失败两有效修复仍无解升级；不要自行做handoff/Popen/额外FD继承来补测试。稳定diff/pins/RED-GREEN真实exitJSON/report后STOP，Root再独立复核。下一包再冻结privateresource交接及原父子继承，未授权新actual smoke；旧Native grants全部保持closed，formal8/100/AUTO OFF。

## Root acquisition / context 裁定

legacy source_latch 原exit仍动态global fstat（body内gid故障仍能观察），Tree-close可能覆盖source-close/endpoint/body，保持原嵌套finally优先级，不重新定义。新reader的capture methods独立于旧context。reader只快照source相关profile/agent、instance/state_root、binding、原adapter receiver；cache/repository变化不是当前installed source替换，不让reader自行stale也不读取它们。

## Root registry保留裁定

永久retired不要求永久墓碑：明确已核自有source与Tree、两次原close都成功的记录，从registry删除（即使最后named/context核失败也可删），原receiver后续因缺登记永拒绝；插入后异常且cleanup明确成功同样删除。任何held未知/foreign跳过或close异常仍留原retired对象/引用，绝不retry或假released。固定资源上限64（starting reservations + live/unknown retained registry），新增工厂在任何marker/Tree/acquisition IO前预留一个starting slot，finally仅一次返还；正常registration期间可保守双计，不能超过上限后另create。quota是资源上限，不是资格/授权；测试私有常量缩小允许而生产无新参数。加入重复成功close后registry不增长/Workspace weakref可释放、失败未知保留且封顶前零IO、insert后cleanup移除、迟到旧receiver永拒绝、reentrant acquisition计starting等有意义反例。
