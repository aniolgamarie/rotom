# Node 引导器 fd3／匿名管道合成探针

## 当前实际结果：单场正控制已观察并有限验收

2026-10-08 用户明确授权三套当前材料及同边界必要修复重跑。本场原始false plan `5191bb…febc`已在授权前像中保存，开启三个自有guard及依赖SHA后执行。第一次 `retained-native-work-b6ap61uo` 因固定bwrap不支持`--clearenv`，outer1／wrapper2、stderr33B、helper未启动；原失败保留。只移除该flag并将Popen父env改成空dict，原四项显式setenv、只读挂载、断网、工具和产品不变；新单项fake Popen测试真实red／green，旧29／59＋6不重跑。

第二次 `retained-native-work-u70y68su` 得到`positive_observed`：Node／outer／tool均0，helper stdout1,737B／stderr0，三帧hello／bound／closed。原child PID3／parent2／UID1002、boot／pid namespace及真实stat字段一致，最后WNOWAIT五字段与原pidfd reap全等；父fd3和原锁九字段相同，原锁在child wait后稳定，材料before／after一致。scout对保存报告和锁lstat作独立复核，没有重跑或读取原帧。

root稳定验收14输入receipt **`59d9e52877fb7db79f3e63dc4a46820f25e396190917e2dab2c1d53495694eee`**，本单场授权已满足并闭合。child flags仍只属于自身检查的间接证据，不独立签child flags／OFD／EX、namespace全后代、正式controller cleanup／SourceHold／DB或真实锁释放。正式7/100和AUTO OFF保持。下面准备状态及false摘要为历史授权材料，不覆盖此次实际结果。

2026-10-08（本地），review01：自有准备包已封口，独立初审及受影响修复增量已完成，最终0 P1／0 P2。root稳定验收15输入receipt为 `ec858c04fd15f77777d493f9f885cab1b7bf29613a1ca0d97fecc93c67cc8452`；尚未授权或执行原生场景。材料在 `.cache/pi-two-profiles/run-20261004/controller-node-bootstrap-native-preparation-review01/`。runner.py、helper.py、plan.json 三个 `EXECUTION_AUTHORIZED` 均为 false，默认入口在创建 work、进程或锁之前返回2。

本次是一个固定正控制，使用已接受的零 SDK Node bootstrap 和消息 codec 原字节。它补充 mock59／Python临时映射6未覆盖的实际CLI、fd3、proc及原匿名pipe路径；不启动 Pi、Codex、MCP、Durable SDK 或真实服务，不读取账号、调用模型、联网或部署。

## 唯一场景与通过条件

自有 Python peer 在新私有 work 中创建600／single-link的临时 `storage/instance.lock`，取得 EX／NB flock。任何已有 fd3 都先拒绝，绝不覆盖。peer 保留本次原OFD，用 `dup2(..., 3, inheritable=False)` 设置父方保留槽，通过公开 `Popen(close_fds=True, pass_fds=(3,))` 将原OFD传给固定 Node，并建立原stdin／stdout／stderr匿名pipe。

Node执行固定六个合成CLI值，首次自有fd IO是fstat3；随后自行检查regular／600／single-link／UID、CLI dev／ino、RDWR及CLOEXEC。peer 不修改 exec 后 child flags，不使用 agent 私有API、monkey patch 或上游补丁。hello 的字段只能间接反映 child 自检通过，不能独立证明 child flags、OFD／EX锁或后代继承已全部验证。

唯一正常序列为 `hello → bind → bound → close → closed`。peer检查闭合字段、真实原child的pid／ppid／pgid／start_time、UID／boot_id／pid namespace、锁与storage dev／ino，以及同一合成record各阶段。frame 为4字节BE、payload1–4096，重复键、非有限值、乱序或窗口尾数据拒绝。原帧、外来异常和stderr内容不写报告，只保存有限计数与固定公共错误。

positive 必须同时满足三帧准确、stdout／stderr EOF、stderr0、原held pidfd观察及reap得到Node exit0、原父锁物理记录稳定、固定工具／产品前后pins相同。若零hello且Node exit2，记录 `unsupported_observed_zero_hello_exit2`，positive=false；不修 flags、换宿主、降级协议或把该情况写为通过。合成临时锁不授予真实storage、来源或DB权限。

## 隔离与停止边界

当前外层固定 `/usr/bin/timeout --signal=TERM --kill-after=5s 60s /usr/bin/bwrap --unshare-all --die-with-parent --new-session`，Popen父环境为空、四项环境显式setenv；原准备中的`--clearenv`已按上述实际失败定向移除。只读挂载 `/usr`、`/lib`、`/lib64`、固定Node单文件、helper／plan／bootstrap／codec四个输入；proc／dev是新namespace的只读特殊挂载。仅新自有 `retained-native-work-*` 为普通可写目录，包含临时HOME，所有结果永久保留；无账户HOME、仓库根、socket或真实业务目录挂载。

`/usr`等运行时只读不是逐文件闭包资格；仅四个固定可执行工具和产品输入单独pin。这次实际观测也不签Python manager、loader、完整系统源或FullSourceView资格。

peer软截止10秒，stdout／stderr各64KiB。在自己的原Node任何TERM／KILL／reap之前，先对原held pidfd做 `waitid(P_PIDFD, WEXITED|WNOWAIT|WNOHANG)`，核对pid／uid／signo／code／status；真正reap仍用原pidfd，返回五字段须与WNOWAIT全等。`Popen.returncode`仅赋缓存避免destructor另行wait。缺childwatch或原wait证据时保留强child引用与父OFD，不按PID重建或关闭保护。

外层60秒加5秒kill-after只为这个无业务资源的合成环境提供最后期限，不是正式controller的安全释放语义。触发它时记录unknown、positive未验证；不声称Node／namespace全后代已停止、真实锁已安全释放或controller cleanup合格。peer自身收尾在获原child wait证据后只关闭自有两份OFD，不发LOCK_UN、不签released。工具／材料的有界前后检查和证据保存未计入外层期限，整个操作不承诺65秒硬截止。

## 固定材料与默认验证

false计划为3,618B，SHA **`5191bb333b33198cbc077ec609a5c34f5897e534350f1fcfd8051ff20321febc`**；runner13,181B／`3dccb07933d3682a3b9c1fd3b8cf1165bcda62197d085336e4b14f890ec87871`；helper23,594B／`5dad2ddad081b400611ef0b4d576e26cbfb88870f62d82c3096a2148c69cd2c3`。exact sibling mjs副本与已接受产品字节相同：bootstrap16,734B／`45528f1497ad6d6df47102f474d7edaa19706267d01659507caba2fc25cfe728`，codec8,790B／`ae51f5ab739a80006639feead7b22822c5f135430e41926f59420ec2127a1238`。

| 工具 | bytes | SHA256 |
|---|---:|---|
| 固定Node文件 `/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node` | 122466960 | `e237a2839d0cbdc9a9a2adda1a184afc0f5b20306ffbe923af5686550472d8a8` |
| `/usr/bin/python3.11` | 15344 | `f0f1292a7e92f235336306d453222b1706a1c820ceeadf2e6cb2cc572f090fab` |
| `/usr/bin/bwrap` | 75344 | `6f8fe506c26367ebdd0027247e47e0725d4594cc952565cd23f810725d8082f2` |
| `/usr/bin/timeout` | 46872 | `4e0102f22f4017f2b7b75d95e180896ffaa7cc82160ed4994e18563fb00a6bc2` |

reader修复只涉及自有准备包：native str／exact PosixPath、exact int cap、绝对路径逐级原目录FD／nofollow打开与末级核验、regular／single-link／限长、分片cap+1、九字段before／open／endFD／named一致、known exactbytes／SHA同时接受。目录仅核其物理身份字段，普通目录条目修改不冒充源漂移。Node128MiB ceiling，每slot进一步按exactbytes限读；文本64KiB，JSON拒duplicate／nonfinite，缺失或非object／坏helper报告为unknown。

原目录FD取得至登记的失败按原owned链和当地close-only分工；构造、提交前和提交后控制异常保留原对象。清理逐个尝试所有自有FD，本函数自身pending control优先；否则传播首个cleanup control，不能把caller正在处理的异常混入本次清理。普通close错误保持固定拒绝。该语义不宣称解释器／kernel任意内部OOM无泄漏。

最后一轮新2个反例的真实红日志为8项subtest failures，修后全受影响默认测试一次29/29（原27＋新2），0.204s。先前reader／ancestor／registration／control每轮失败、成功日志与exclusive即时前像完整保留，跨轮不相加；59＋6不重跑。原初审发现及每轮P2均有独立稳定增量报告，最后报告SHA `645129d9398907d2ef30f9b2e48ec0fbb4b06b835264c41904044b25019389fc`。默认临时regular文件测试没有运行Node／bwrap／proc／fd3探针或signal，不能替代本原生场景。

## 授权后的唯一执行形状

用户针对稳定review01明确授权后，root先保存runner／helper／plan／package-pins变更前像，只将三个自有执行守卫false改为true，更新这三项对应package pins，冻结新的精确摘要；其它工具／产品／场景／挂载保持本边界。同边界必要修复重跑需各保留独立work和原失败，越界变更不沿用授权。

```text
/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8
  /usr/bin/python3.11 -I -B
  /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/.cache/pi-two-profiles/run-20261004/controller-node-bootstrap-native-preparation-review01/runner.py
```

输出需保留outer-start、outer-report、helper-report或helper-error，以及全部work；即使失败、unsupported或环境不足也不能写passed。该探针不激活正式controller／guardian，不接来源、初始化或DB，不改变正式7/100或产品gate，不启用自动审核。

本次独立授权要求来自 [AGENTS.md](../../AGENTS.md)：“真实 smoke 为独立显式步骤，需用户明确授权”。旧FD6、Base SDK6和其它SDK授权的固定材料及场景不同，不能覆盖这个新组合。当前具体材料审查已完成，可针对上述单场和同边界必要修复重跑请求一次授权。
