# Linux Shell helper 行为探针

状态（2026-10-05）：在用户已授权的固定Linux范围内，**run08三项原生场景全部observed，命令退出0**；新的固定helper和Bash已实际执行。最终14模块默认回归 **842 passed、0 failed（6.14秒）**。此前run03–07的拒绝与诊断原样保留，不改写为通过。本探针只完成T033的Linux helper组件验证，不签发产品gate，不完成T033；产品操作/租约与前端接线仍未验收。独立RPC探针仍按自己的授权范围处理。

## 固定入口与来源

入口为 `scripts/pi-probe-shell.py`，父编排为 `src/agentcfg/pi_shell_probe.py`，结果判定为 `src/agentcfg/pi_shell_probe_protocol.py`。三个自有 fixture 位于 `tests/fixtures/pi/shell-helper-probe/`。组合现有 `prepare_shell_execution`、FD-exec、`LinuxProcesses` 与探针专用 `pi_shell_probe_binding`/`pi_shell_handoff` 接口，未修改上游源码，也不向产品运行目录部署任何文件。

实际执行 helper 来自 modern 的 `pi-bwrap-linux-x86_64` 固定源，通过 `load_record` / `verify_archive` 静态核验构建记录、归档、二进制和许可证清单，取出 `bin/pi-bwrap`：

- helper SHA-256：`c2ef9427eddbed90e2f52aa6cb3bf08ba514e456d520d19cfbe43af125d79997`，128368 字节。
- vendor：`locks/pi-modern/vendor/pi-bwrap-9672205cfff3f07f1fa9a81a2085a3fc617054c37df5a5cb9fce262a74325068.tar.gz`。
- 构建记录：`locks/pi-modern/build-records/5308fbf91bf839b3559f157e0552382a8d3dd93c29a275cb85b17ef31a3f00b7.json`。
- 外层固定 bootstrap：`/usr/bin/bwrap`，SHA-256 `6f8fe506c26367ebdd0027247e47e0725d4594cc952565cd23f810725d8082f2`，须与构建记录一致。

每次修复后使用新的 `/tmp/rotom-shell-helper-probe-20261005-reviewNN` 私密目录，最终身份与结果登记于 `.cache/pi-two-profiles/run-20261004/state.json`。旧目录保留原始事实，不重写成新结果。run08历史快照有88个输入文件，当时handoff由探针显式追加。后续产品父侧阶段已将handoff/start/identity/probe_info加入Base声明，当前探针直接使用Base闭包，不再重复追加；这不追溯改变run08来源或结果。目录/普通文件分别为0700/0600，helper为0700。

run06 的准备后worker源码发生变化，运行前摘要核验拒绝；没有 `execution-started.json`，未启动进程。run07 进入父侧准备，但因本机无关路径的合法叠挂被全局 mountinfo 解析器拒绝，未启动外层引导或helper。修复保留歧义路径失败关闭与来源子挂载拒绝，不能按文件顺序猜可见挂载。 后续只读父侧准备发现系统子目录EACCES和活动Unix socket。最终对不可打开的系统目录整体遮罩；遇系统特殊对象则遮罩其最近父目录，不使用普通文件遮罩覆盖socket/device。仅明确EACCES/EPERM可走目录遮罩，其他错误、工作区对象/权限失败、整个来源根或cwd/executable被覆盖仍拒绝；未遍历的子树不算已检查。

run08目录为 `/tmp/rotom-shell-helper-probe-20261005-review08`，`plan.json` SHA-256 `781deea9c74e1f8e0785a9ad90e22cb4119a896912be1fc1d35017b72fc06bc1`。原始JSON、canary、正控制和心跳文件的42份证据归档于 `.cache/pi-two-profiles/run-20261004/shell-native-08/`，逐文件摘要在 `artifact-hashes.json`。

| run08场景 | 实际结果 |
| --- | --- |
| boundary | 19/19为真，退出0，正控制匹配nonce，canary完整、越界文件不存在 |
| helper-mismatch | 固定交接拒绝，无正控制文件，worker退出0；此项checks=0，不累计成隔离断言 |
| descendants | 19/19为真，108ms完成主动停止，退出137，心跳停止后1→1 |

三个case持久记录均`terminated=true`；运行结束后父侧只读复核保存出生身份，leader/wrapper均dead，termination_status均terminated。父读map均为`1002 1002 1`，worker自读仍为`1002 0 1`，两者坐标区别在本机已实际观察到。PID namespace inode在顺序运行后复用不构成同一进程，登记同时绑定出生时间、boot、UID、PID与nonce。

运行前重新核验当前来源、父控制源码、工件模式及固定文件/目录集合。集合由 runtime 显式来源行和探针契约独立推导，不能仅改写包内清单加入额外文件。已启动目录不能重放；修复后使用新的私密目录重新准备。工件清单约束当前准备内容，不承诺防御同用户在校验后修改可信代码、系统库或文件树。

## 父侧来源与跨命名空间FD交接

run05 本机事实已证实严格属主检查与单UID映射的兼容性缺口。worker自读 map 为 `1002 0 1`，不能把其中第二列当成父侧 UID；父侧独立读取 `/proc/<已登记host-pid>/uid_map`，第二列才相对于读取者 user namespace。读取前后复核worker出生身份与双方user namespace，并检查映射语法、范围、重叠及内核overflow UID。这里的“父侧”是读取者自身坐标，不预设其处于initial namespace；依据 [Linux user_namespaces(7)](https://man7.org/linux/man-pages/man7/user_namespaces.7.html) 的两种reader语义。

父侧在启动前调用原来源/挂载检查器，以宿主可见身份固定helper、来源目录、脚本、seccomp及遮罩FD，并生成唯一权威plan摘要。外层只在同一绝对路径绑定本case合成work目录，避免来源FD的路径坐标变化；不挂整个临时目录。worker发出bootstrap并等待G，父侧随后捕获稳定出生身份并持久登记，避免把bwrap执行setsid前的PGID用于登记。

父侧对每个已固定FD的原UID建立明确投影；grant绑定nonce、helper摘要、实际父plan摘要、worker出生/PID namespace/user namespace及UID投影。最初为空的继承memfd只由可信父侧写入，添加WRITE/GROW/SHRINK/SEAL后才发送G。子侧检查封闭schema、同FD的dev/inode/mode/nlink/size/mtime/ctime、经投影的唯一UID字段、helper字节摘要、密封/偏移及本地出生身份，重设CLOEXEC后进入原exec白名单。子侧不重开来源、不重编译挂载计划，也不把65534加入通用可信属主。

交接只接受原作用域内准备对象，一次export消耗父对象资格；consumer每进程一次尝试，失败也耗尽，adopt对象不能再export。密封memfd不是抵御同UID攻击者的密码学认证，本接口仅供可信父进程启动的干净exec worker，不能从RPC接收任意grant。后续产品父侧代码已整合实际操作/租约/代际及运行包收据并通过默认隔离测试；当前probe仍仅用shell-probe目的，不能替代shell-execution产品路径的独立原生证明。

只有登记、映射、交接均通过才允许以下场景：

| 场景 | 实际动作 | 必须观察到的证据 |
| --- | --- | --- |
| `boundary` | 正确 helper、固定 Bash 脚本和 Python payload | 正常退出，19 项严格布尔断言全部为真；父侧读到匹配 nonce 的写入文件，原始 canary 完整、越界文件不存在，登记的 namespace 完整终止 |
| `helper-mismatch` | 同一FD交接链路传入故意错误的预期 helper 摘要 | 正确正例先通过；拒绝事件、无正控制文件、正常 worker 退出和完整终止。通用交接错误码仅证明拒绝，不能单独归因具体内核行为 |
| `descendants` | 固定后台心跳与同一 payload | 心跳已实际写入；父侧在发送 `G` 起算的 10 秒内完成身份核验的 stop；最终非零退出、namespace 完整终止、停止后心跳计数稳定 |

19 项断言分别为项目读/写、只读根读取/拒写、不可见外部根拒读/拒写、deny 子树拒读/拒写、嵌套 `.git` 拒读/拒写、私有 HOME/tmp 可写、环境白名单、仅 stdio FD、INET/INET6/UNIX socket 创建拒绝、匿名 socketpair 可用、系统 `/usr` 挂载只读。

父侧在执行前独立准备和重验只读、外部、deny、`.git` 四处 canary，避免把原本不存在算成拒读成功。worker 在 FD-exec 前故意留下可继承的外部 canary FD 和合成环境诱饵，内层须清理。payload 的六种 namespace 身份均须区别于 worker 的外层身份，heartbeat 与 payload 必须处在同一组内层 namespace。

心跳固定写 600 次，每次睡眠 0.05 秒，自然完成至少需 30 秒；父侧必须在放行后 10 秒内完成 stop，并验证 `stop_elapsed_ms < 10000`。这排除自然完成被误判为主动停止。计数稳定的基线在 stop 确认后读取，容许信号送达期间的最后一次写入。任何 stderr 数据都使本项拒绝接受，避免隐藏后台异常退出。

## 隔离与父侧生命周期

父进程仅启动固定 `/usr/bin/bwrap`，`shell=False`、`env={}`、`close_fds=True`、独立 session。外层启用 `--unshare-all --as-pid-1 --new-session --die-with-parent --cap-drop ALL`，只读挂载 `/usr /bin /lib /lib64`、裁剪的自有 supervisor、固定 helper、Rotom Python 依赖、合成 passwd/group。仅本项合成work目录以相同绝对路径绑定可写；`/proc /dev /tmp` 为独立实例。不会挂载真实 HOME、凭据目录或完整仓库，也不会启动 Pi、Codex、模型或登录流程。

Python 用 `-I -B -S`，显式引导只读 `/probe/supervisor/src` 与 `/python-deps`，不处理 `.pth`。原始 Python 环境只含固定基础键和合成 endpoint/capability/poison。系统依赖和 venv 目录是当前机器的可信引导来源；其内容没有完整可复现冻结，本探针也不声称具备这种证据。

启动信息pipe只传递namespace事实，采用专用有界解析器接受 `--unshare-all` 的已知字段，原产品PID-only协议保持严格。stdin pipe是唯一放行通道；worker要求自己为PID1，EOF或非G拒绝。收到G后把stdin换成 `/dev/null`，消费密封交接并执行新helper。普通继承FD由 `exec_prepared` 白名单清理，不依赖bootstrap自动关闭。父侧保留原FD作用域直至清理结束。

父侧限制放行后的每项总输出 1 MiB、单行 64 KiB、最多四条 JSON 事件，JSON 重复键/非有限数拒绝，放行后的收集截止为 45 秒。namespace 信息读取和放行前 bootstrap 握手各有 10 秒上限，后者限一条 16 KiB JSON；清理使用现有有界 TERM/KILL 和 wrapper wait。后代场景提前触发停止，不等待 45 秒截止。准备/登记失败关闭 gate；已登记的进程走 `LinuxProcesses.stop`，仅核验过的 PID 身份用于信号。登记后复核失败保留可能已写入的记录，记为 `termination-unknown`，不能删除后声称完成。只终止 wrapper 不等于整个 namespace 已终止。

stdout 只接受闭合 JSON；内容限合成结果及明确允许的 namespace/属主事实，stderr 不回显内容。`observations/<case>/` 保存固定 invocation、bootstrap、父读映射及出生身份事实、通过协议核验的执行事件/父侧事实和结果；根目录保存一次性 `execution-started.json` 和汇总 `result.json`。失败区分 `unavailable`、`failed`、`interrupted`、`termination-unknown`，在首个未 observed 的场景停止后续执行，不回退宿主 Shell。每个汇总的 `product_gate` 固定为 false。

## 默认测试与执行命令

最终14个直接相关默认模块通过 **842 passed、0 failed（6.14秒）**，日志 `.cache/pi-two-profiles/run-20261004/pi-shell-handoff-final-green.log`。该计数包含此前815及局部233等重叠子集，不相加。覆盖真实memfd、假PID1/exec、父prepare到worker adopt、拒绝重放/FD复用/映射或出生变化/源身份漂移，以及无关叠挂、隐藏祖先、系统子树遮罩和别名投影；临时HOME、禁网与假子进程守卫保持，不以这些测试替代上述内核执行证据。

executor使用gpt-6.1-sol/medium实现交接、worker和有界挂载修复；scout使用gpt-6-luna/high只读审查冻结变更与证据。root负责身份/生命周期/挂载取舍、父侧编排和原生执行。静态审查未发现剩余P1/P2，但结论仅覆盖当前组件。

入口仍为以下两个明确分离的动作，`NN`取本次新目录；真实运行已在上述固定范围获准，源码或输入变化必须重新准备。

```sh
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-shell.py --prepare --directory /tmp/rotom-shell-helper-probe-20261005-reviewNN
/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python scripts/pi-probe-shell.py --run-native-shell-probe --directory /tmp/rotom-shell-helper-probe-20261005-reviewNN
```

授权不包含产品部署、默认配置切换、扩大可写根、真实账号/模型、RPC探针或源码外发。失败只能在同一隔离边界内修复重跑，不得放宽属主或伪造映射来取得通过。

三项observed只证明当前Linux、固定helper和固定合成场景；没有系统调用追踪或对所有动态库/系统树的可复现冻结。完整私有 RPC 到 Shell 工具的接线、真实租约/Writer 回收、正式运行包闭包、前端超时/取消/输出、默认 factory/backend_preflight 以及 Base/Full 产品 gate 仍须独立验收。当前正式完成数保持 7/100。
