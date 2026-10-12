# 独立来源 latch 的默认底层原语

2026-10-09 root。caller 分类已区分 source mutators 与 activity-only recovery；长期SourceHold仍未实现。本包只实现已有私有实例中的固定source.lock上下文锁，不接CLI/部署/runtime/controller/SDK，不能把这个底层原语当作实际FullSourceView或初始化资格。

API为src/agentcfg/pi_source_latch.py的contextmanager source_latch(workspace, *, shared=False, create=False)。仅受信调用者传实际workspace，固定workspace.instance/source.lock，不接受options/model/path参数或其他文件名。exact bool shared/create，instance是绝对Path。既有Tree私有根no-follow/owner/0700安全打开，缺instance拒绝且不mkdir；create只允许在已安全打开的现有实例首次创建anchor，不新建实例目录。anchor必须regular/owner/singlelink/0600/空文件，O_RDWR|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK，相同named/file原对象核对；不replace/unlink/写内容或转换锁模式。

以非阻塞fcntl.flock取得原fd SH(reader)/EX(mutator)，EAGAIN/EACCES为固定Conflict，不无限等、不改已有lifecycle/state锁。取得后及context退出前，通过Tree.parent重核原根和named anchor的device/inode/type/owner/mode/nlink/size与持有fd；替换/链接/修改/未知拒绝成功。退出只close一次，不LOCK_UN后重新acquire/不retryclose，也不返回或序列化fd/tuple/guard对象。本包yield None，只在当前context作用域持有，故没有对外借用/交接/初始化端点。FD/metadata校验只属于端点检查，不声称抵抗任意同UID外部破坏或提供持续SourceHold。

唯一写范围新src/agentcfg/pi_source_latch.py与tests/test_pi_source_latch.py；不改storage/paths/现有callers/state/tasks/docs/锁manifest/实例、上游/vendor。新自有证据source-latch-primitive-implementation-review01。测试全部临时private实例/假Workspace，仅当前pytest进程真实内核flock/普通文件操作，不fork/第三方SDK/host/nativehelper；默认网络/子进程守卫保持。两个独立open SH并存，任一持SH时EX冲突，EX持有时其他SH/EX冲突，正常退出再次取得；断言anchor原inode不变、flags CLOEXEC、oldlifecycle/state untouched、yield None、无Root读取/Full探测/目录创建。错误flag/path/link/owner/mode/nlink/非空/缺失、acquisition异常、body异常close-once、退出named/root替换、close失败不重试保持固定错误且不输出路径/body要覆盖。fakeclose bookkeeping不能关闭不属于本context的fd或为cleanup补假的成功。

先即时前像/有意义RED，固定pytest仅新模块，private0700/data TMPDIR/basetemp和同默认命令require_escalated正常owner可用（根盘/tmp环境不足）。不新增真实子进程opt-in，不重跑nativeSDK/FD6。复杂FD归属/错误收尾/原Tree安全能力不足/两有效修复失败交root；不能由executor接source模式到recovery或现有caller，也不自行SourceHold-handoff设计。完成稳定diff/pins/logs/观察模型与STOP，root验收后再冻结真实参与者接线。正式8/100、AUTO OFF，实际reader/mutator/holder/CrossPID关系与长生命周期仍未验证。

2026-10-09 root稳定P2审查决定：普通metadata/first binding创建会改变目录size/nlink，不能使用regular-file投影校验root。root原目录对象用dev/ino/mode/uid/gid五字段，anchor regular用dev/ino/mode/uid/gid/nlink/size；正常metadata文件/目录增加删除在SH/EX低层context内必须有正控制，权限/owner/named/root对象漂移仍拒绝。原29绿属阶段证据，需有效RED及修复后同新module重验；不接现callers或改变原Tree/持有链权限。

2026-10-09 root组合异常优先级决定：body异常仅在endpoint/close全部正常时原样保留；保护端点漂移/检查失败及close未知优先固定Conflict。现finally层级保留（sourceclose高于endpoint，rootclose最终更高），不重试/不签释放。新增body+endpoint与body+close错误正反，所有fd仅本contextclose一次。如果保护固定错误的Python rendered trace串出body合成sentinel，endpoint边界同OSError用from None抑制该链；body单独错误仍原样。只补受影响测试和必要自有固定错误表达，不改锁/handoff/caller/Tree资格。34绿保持阶段证据，不凭组合未知签SourceHold。
