# 产品 Shell 合成路径探针

状态：review02 已按用户明确授权执行，三个固定场景均 observed，命令退出0；结果与限制见下文“review02 实际执行”。此前`native-shell-probe.md`的run08只证明固定helper组件，本次另外验证产品启动链。默认factory不启用，不部署、不签发Base/Full通过。

## 目标与真实路径

本探针调用自有真实`ShellOperationAdmissions → SupervisorService → ExecutionStore/WorkspaceLeases → HostSupervisor.spawn/activate/poll → ShellStart → pi-shell.py → adopt_handoff → exec_prepared`。父控制器当前进程的真实出生身份仅用于合成manager存活，不启动Pi、Codex、SDK、模型、Git、登录或RPC服务器，也不验收真实会话前端。

可信控制器为固定的三条合成命令作出授权；没有模型输入或任意用户脚本参数。产品worker不获得控制端点或capability，脚本只经父侧密封FD传递。真实许可消费、Writer reserved/active、starting/running、出生身份登记、产品授权handoff及G放行必须保持生产顺序。后台取消经真实service.cancel与Host.poll完成，不能用probe直接stop替代正常产品取消。

`source_rows`只复制Base显式裁剪文件。runtime目录身份为`digest({probe_id, helper_identity, source_rows})`，lock/slice使用明确的合成标签摘要，均不表示正式锁晋级。包内生成profile/commands和逐文件收据，完整收据字节另由外层plan.files绑定。父控制器所用自有Python辅助代码另经保守静态import闭包哈希固定，含函数内条件导入及包初始化；这只是探针来源指纹，不导入或复制未选功能，也不扩大Base实际加载集合。父侧额外读取的options.schema亦显式绑定。

## 工件、边界与启动差异

- 准备入口：`scripts/pi-probe-shell-product.py --prepare`，只读取声明、固定build记录/归档/源码和本机可信系统来源，复制到全新的`/tmp`后代目录；没有子进程。
- 实际控制器：`src/agentcfg/pi_shell_product_probe.py`。bundle准备/预检由`pi_shell_product_probe_bundle.py`负责。
- helper仍是已构建并静态核验的modern Linux bwrap：SHA-256 `c2ef9427eddbed90e2f52aa6cb3bf08ba514e456d520d19cfbe43af125d79997`。模板payload/heartbeat复用旧固定探针，不新增外部程序。
- **与run08的执行边界差异**：run08先由系统`/usr/bin/bwrap`包围可信worker，再由worker执行新helper；本探针走实际产品路径，父进程直接通过已核验helper FD启动这个helper作为外层namespace launcher。新helper因此在完成自身隔离设置前先在父进程的宿主权限下执行。不得把旧探针的包围层当成本次已经存在。
- helper外层启用unshare-all/as-pid-1/new-session/die-with-parent/cap-drop ALL；来源均用`--bind-fd`/`--ro-bind-fd`，不绑定整个`/`、真实HOME、整个`/tmp`、账户或完整checkout。
- 仅本case已批准project可写；只读根、系统根、裁剪runtime与Python依赖以最小声明挂载。runtime/deps固定在`/.rotom-shell-bootstrap/`，临时HOME/tmp独立；内层仍有网络/syscall限制及Git/deny遮罩。
- 父侧写入限于新bundle内的case state、instance、observations、合成private-account-home协调锚和project/.git Writer标记。读取真实系统身份、Python依赖和helper来源，不读取密钥/token/账号会话内容。账户协调器显式传入合成account_home，不能由真实passwd HOME派生。
- 父进程`Popen`使用`env={}`，固定基础环境由argv设置。秘密脚本及脚本内容摘要不落盘；错误只保留固定类别和白名单代码，未知底层文本用统一代码替代。

目录要求0700，普通文件0600、helper0700。预检从当前独立来源重新计算闭包、精确工件集合、固定模板与收据；额外文件/目录、链接、模式/来源漂移、篡改或重复运行均拒绝。每次实际运行先不可覆盖地写`execution-started.json`，源码或参数修复后必须新建另一目录，旧结果保留。

## 三场景与通过证据

| 场景 | 动作 | 必需证据 |
| --- | --- | --- |
| allowed | 真实准入并启动固定Bash/Python payload | 放行前lease running且Writer active；payload 19项严格bool全部true、六namespace与父观察outer PID1分离；nonce正控制、canary不变；完整stdout、空stderr、退出0；整个登记namespace terminated、lease reclaimed、Writer released |
| denied | 同一Bash绑定由明确hard deny拒绝 | 固定PERMISSION_DENIED、0 external lease、0 child、未创建.git/agentcfg Writer标记、没有正控制写入；checks为0，不虚增隔离断言 |
| background | 固定心跳后台+payload+wait，经service.cancel取消 | 实际心跳和payload后才取消；立即观察grant+1、cancel_requested且Writer仍保护；从放行准备起10秒内确认整个namespace终止；非零退出、终止后心跳稳定；输出完成后才reclaimed/released |

每次成功还核对handoff目的为shell-execution、原operation/lease/context/allocation/runtime/lock/slice/profile及grant绑定。密封摘要不替代授权，合成manager证明不替代真实Pi输入来源。

每case输出最多1MiB、单JSON最多64KiB，allowed仅1条payload，background仅payload+heartbeat两条且内层namespace一致。总收集45秒，后台主动终止上限10秒；信息/就绪握手沿用产品各10秒上限。捕获完成或wrapper退出不能单独算终止。

失败关闭未放行gate，仅对本次children表中的登记identity请求stop。不得终止合成manager/controller、未知或无关进程；不能按包装进程退出自动abort/释放Writer。未确认终止标为termination-unknown，保留原始lease/Writer。正常路径必须先完成终止/输出回收，才记录observed；汇总始终带synthetic_manager=true、frontend_verified=false、default_factory_enabled=false、product_gate=false。

## 具体准备与运行

2026-10-05首先在review01目录仅执行`--prepare`，退出0。目录内`plan.json` SHA-256为`63e51b87c15532d909139d49d0e1f627fb0112a14cb854f782d8d215b093038c`；runtime identity为`3f5b0dcb0ee5938ba2db2b651a81c47c70ee317a5e42ab3aa8248d613d5b1a5c`。计划固定137条父控制器/数据来源指纹、69条Base supervisor来源、94个工件文件、54个目录；没有execution-started标记。默认合并测试为82 passed（4.34秒），命令为`python -m pytest -q tests/test_pi_shell_product_probe.py tests/test_pi_shell_product_probe_bundle.py tests/test_pi_shell_product_probe_lifecycle.py`，仅假子进程与临时数据。独立scout（gpt-6-luna/high）复核7个文件没有剩余P1/P2，主代理核对7个文件指纹、Python AST和空白检查；executor（gpt-6.1-sol/medium）完成bundle与生命周期测试。

随后前端接入修复了共享观察响应中的`spawn_committed`缺失，并添加只读Shell输出查询。review01保留为历史静态工件，由于来源改变已stale，不能执行。当前重新准备的目录为`/tmp/rotom-shell-product-probe-20261005-review02`，plan SHA-256为`a6fbfeca1198d9eae430a3803235ad79a3ff5047b3043a9e27dcf76fc73cf2ba`，runtime identity为`7cfd989e7b93d61ba43e3a0675a0c6dd6048db03ab817cecce9fefc659633079`。helper身份、三条固定命令与执行边界不变，计数仍为137/69/94/54；只执行静态准备，没有启动helper。此版受影响Python合并回归385 passed（其中包含探针三模块），前端隔离Node回归347 passed，不能相加为原生断言数。

`--run-native-shell-product-probe`是显式行为开关，本身不构成人工授权；尤其须独立核对上文新增helper直接作为外层launcher的边界。修复后重新准备必须保留旧目录，且新工件只能继续相同的三条固定命令、临时路径、无账号/模型/宿主范围；扩大范围另行确认。

```sh
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-shell-product.py --prepare --directory /tmp/rotom-shell-product-probe-20261005-review02
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-shell-product.py --run-native-shell-product-probe --directory /tmp/rotom-shell-product-probe-20261005-review02
```

本探针不覆盖真实前端RPC/TUI、live模型质量/认证、默认backend可用性证书、部署、C++/Neovim全部工作流或整进程恶意扩展隔离。相关目标继续单独实施与验收；不能用本探针替换T033/US2完整gate。

## review02 实际执行（2026-10-05）

用户明确答复“授权执行及必要重跑”，范围为上述三项固定临时场景及同边界修复重跑。随后执行review02的`--run-native-shell-product-probe`命令，退出0，无修复或重跑。plan SHA及137条父侧来源指纹与准备时一致；helper身份不变。原始计划、94项静态输入、执行标记、监督状态、capture和观察数据共138个普通文件归档于`.cache/pi-two-profiles/run-20261004/shell-product-native-review02/raw/`，逐文件SHA另存`raw-hashes.json`，原`/tmp`目录保留且不可再次执行。

| 场景 | 实际观察 |
| --- | --- |
| allowed | 19/19严格bool，退出0，stdout 731字节、stderr空；nonce正控制与canary成立，完整出生/namespace身份及handoff绑定一致；最后namespace terminated，lease reclaimed、Writer released |
| denied | PERMISSION_DENIED，0 external lease、0 child、未创建Writer，0隔离断言；只有合成manager租约，不执行候选命令 |
| background | 19/19，stdout 990字节、stderr空、退出137；取消前后grant 1→2，cancel-before-poll仍为cancel_requested且Writer active；最终namespace terminated、lease reclaimed、Writer released，heartbeat 1→1 |

background的`stop_elapsed_ms=8474`按现有控制器从放行准备计至终止，符合本探针10秒总窗；**不是独立取消延迟测量**。取消请求及终止证据墙钟时间相隔约73毫秒，只是附属记录，不能代替未来性能基准的单调时钟测量。快照证明取消时Writer保护和最终终止/释放；capture完成后回收的精确顺序仍依赖稳定实现控制流，工件没有独立时序戳证明这一顺序。

结束后在原supervisor观察者PID namespace中只读复核两个登记leader均已不存在；该附属事实不替代完整namespace终止记录。默认执行工具位于另一个PID namespace，那里看不到PID不能用作死亡证据；有效核验见`post-run.json`。

executor（gpt-6.1-sol/medium）独立只读审查24项原始证据SHA、capture、handoff/完整出生身份及取消/Writer快照，无P1/P2；root复核稳定指纹和适用边界。审查文件及root验收归档于同一阶段目录。结果仍明确synthetic_manager=true、frontend_verified=false、default_factory_enabled=false、product_gate=false，T033及Base/Full完整gate不据此完成。
