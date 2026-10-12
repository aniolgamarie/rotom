# 专用 controller 的 fd3 预留原语

2026-10-09 root，Durable controller 实现前置小包。当前controller生产脚本缺失，source-latch只持foreground，完整FullSourceView/initializer/原Popen child/长期holder未实现。本包只实现自己的进程fd3预留，不创建脚本launcher、不启动controller/Node/SDK/storage、不签发任何初始化资格。

新增src/agentcfg/pi_durable_controller_slot.py：reserve_controller_slot() 不接受fd/path/DTO/回调/kwargs，只用于专用controller主线程。捕获本次原os.fstat/open/close和fcntl.fcntl/线程身份；不是用调用参数提供syscalls。只有当前thread为main且自身fd3原fstat明确errnoEBADF，才允许一次打开固定/dev/null（O_RDONLY|O_CLOEXEC|O_NONBLOCK），并保存本次原open返回的实际fd。fd3未知已占用或fstat其他错误直接固定失败，不关闭3、不打开任何其他文件。open返回非3（竞态新fd）只close本次open返回fd一次，未知foreign3不动，然后固定失败；close异常不重试。正常返回3后核heldfd是/dev/null character device（Linux rdev major1/minor3）、原flags readonly和CLOEXEC，并保存原fstat/dev/ino/mode/uid/gid/rdev与原方法对象、receiver及thread。失败只close本次拥有的open结果一次，没有fdopen/dup2/LOCK_UN/额外source IO。

成功返回不可序列化的自有ControllerSlot，构造入口私有且仅reserve登记的原对象有效，不允许从tuple/hash/整数/公开constructor重建。接口check()和close()只使用本记录原fd3/原方法；不提供fileno或pid/source角色/dict输出，不是SourceHold。check验证原线程、原对象、未退休、heldmetadata/flags仍相符，遇替换/关闭/未知固定失败。close永久退休本对象后只调用原close一次；重复close/check固定拒绝，close失败不重试、不发released/storage退出证据。scope不允许由普通worker/模型提供启动权限；这项resource ownership不代表授权专用actor的来源、fd3原OFD保留资格或主线程principal已完整证明。不声称抵抗任意同进程恶意Python篡改或同样/dev/null再open的OFD替换，此资格另由独立实际actor闭包证明。

不contextmanager自动finally释放，因为将来storage dup_to3/Node alive/unknown有自己的原持有生命周期；本包不实现移交/dup/storage绑定。原始slot若只预留且不用于后续阶段，唯一创建caller显式check/close，不默认为controller已停止。错误为固定自有controller-slot code和exit4，不输出原exception/path/body、不给自有错误foreign exception链。只有普通Python import和固定self-fstat在firstreserve之前；Root未来controller入口必须将reserve安排在source/path/storage/index业务IO前，当前不添加入口或把import称零文件IO。

唯一writer拥有新增module+tests/test_pi_durable_controller_slot.py，自有证据durable-controller-slot-prelude-implementation-review01。默认只临时HOME/假syscalls/假thread，pytestmonkeypatch测试接缝不作为生产输入；不实际改本pytestfd3/close真实3、不fork/Popen/Node/SDK/signal或真实主线程全局设置。覆盖已占用3/非EBADF/非main零openclose；合法open3/错误返回高fd只关owned；readonly/CLOEXEC/char/rdev/身份漂移；wrong/foreign/proxy/手工构造或copy对象不registered；check不open新路径、source不可访问；closeonce/重入/失败不重试、已退休不恢复、错误固定且rendered chain无sentinel。先有意义RED然后实现固定只新pytestmodule，原conftest网络/子进程禁用保持。new/tmp basetemp/true-owner可用，若仅fakes无需弱化Root保护；/data own日志TMPDIR避免根盘临时问题。

若原对象/线程/资源失败顺序需扩大scope或两有效修复无解交root，不能实现controller main/pipe/Popen/资格/SourceHold来补本包。不改既有fd6探针或已关闭授权，不跑native、不改SDK/来源/locks/state/tasks/doc/OMP。完成稳定diff/pins/testlogs/report STOP，Root再独立review。正式8/100、AUTO OFF、FullSourceView及controller来源资格仍未提供。

## Root close 边界裁定

close() 先核登记原对象、原线程、未退休；wrongthread/foreignobject不能退休合法记录。通过后先永久退休，再以保存的原fstat/fcntl核held identity与原flags；核失败（关闭、metadata/flags漂移或未知）零close，固定失败且永久退休。核成功才原close(3)一次，异常不重试。此顺序避免关闭已观察为foreign的3，不声称能抵抗核与close之间任意同进程竞态，亦不证明同一/dev/null重开后的OFD同一性。默认补close漂移/EBADF零close及退休覆盖。
