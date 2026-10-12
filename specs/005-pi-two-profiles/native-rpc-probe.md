# 官方 1.0.1 RPC 探针准备

## 当前review02：五场景已执行并验收归档，授权闭合

2026-10-06：用户明确授权当前外层plan及同边界必要修复重跑。root执行下列固定命令exit0，五场景均observed；正文次数为0/0/0/0/1，abort-late观察原signal已aborted且迟到确认不重新执行。五个进程各有RPC idle处理屏障、session_shutdown和exit0，实际stderr均0字节；这不改变父脚本允许有界stderr的规则。正常属主运行前后完整7源/18,498候选/3系统身份核对均成功，独立root post inventory观察产生的私有目录700、普通单链接文件600、无额外非普通工件；父脚本仍未强制封闭post树。运行目录为 `.cache/pi-two-profiles/run-20261004/rpc-native-20261006-review02/`，日志及后核为 `/tmp/pi-rpc5-authorized-before.log`、`/tmp/pi-rpc5-authorized-run.log`、`/tmp/pi-rpc5-authorized-after.log/.json`。独立executor复核5场景、原88项目录/文件stat/hash、原JSONL/oracle与7源/3系统/选定候选通过，无具体P1/P2；未重复18498扫描或重跑SDK。root已验收并归档 `.cache/pi-two-profiles/run-20261004/rpc-native-observed-review02/`，结果SHA `5af4650e9a25e8efb625c9fd3962020310eadb799fe0dac20754fc6e4610ccd6`。本五场景授权闭合，不宣称产品passed、真人身份或整体namespace终止。

2026-10-06：独立executor（gpt-6.1-sol/medium）确认原八份来源/fixture/测试/本文与旧记录逐字匹配，旧52项默认离线通过可保留为同源码历史证据，本次未重跑测试。没有执行旧命令或RPC宿主，旧SDK6/11/13授权不覆盖本RPC五场景。当前新增root外层静态清单 `.cache/pi-two-profiles/run-20261004/rpc-current-material-review02/plan.json`，SHA256 `b3fec3bdd20af1b3ecac0905b924d80e12deb017d3057a3894c20f3ebc173911`；固定7份执行/测试/fixture来源完整身份/SHA、18,498条候选和3个系统二进制，以及下面准确命令。这里只校正解释器与新输出目录，没有修改原探针源码、oracle或五场景。

父脚本自身只检查worker/extension SHA及lock，**不强制完整来源/候选/系统前后清单或封闭post目录**。新外层清单是root准备证据，不是新增运行检查器；执行者未来须在执行前后复核此清单并独立检查产生的私有工件。stdout使用严格JSONL限额，stderr只按总字节限额私有保存，不要求为空；不能套用SDK11/13零stderr的结论。cacheWarming在合成SettingsManager中已显式off。原脚本的工作边界及限制保持下文事实，不称为完整namespace终止、真人确认、业务权限、账单或产品验收。

静态准备首次在完整清单及副本写完后因摘要计数字段KeyError退出，未启动任何进程或SDK；随后只读复核原已写清单、完整候选、系统、7份来源及固定argv成功（exit0），没有改写材料或掩盖准备失败。记录为 `/tmp/pi-rpc5-current-preparation.log`、`/tmp/pi-rpc5-current-verification.log`，稳定只读调查为 `/tmp/pi-rpc5-current-material-review.md/.json`。

本次获准实际执行命令：

```bash
/usr/bin/timeout --signal=TERM --kill-after=5s 60s \
  /data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -I \
  /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/scripts/pi-probe-official-rpc.py \
  --run-native-rpc-probe \
  --output-dir /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/.cache/pi-two-profiles/run-20261004/rpc-native-20261006-review02
```

本目录现已记录五场景，禁止原目录重跑覆盖。必要修复必须保留首次材料、先完成受影响默认验证和稳定复核、再固定新来源和新输出目录，不能放宽oracle、读取账号、调用真实模型或联网/部署。仓库[AGENTS.md](../../AGENTS.md)明确要求“真实 smoke 为独立显式步骤，需用户明确授权”；本次公开SDK的RPC mode已获该独立授权。

## 原准备材料：同源码历史，以下旧命令不执行

当前只完成准备，**未执行官方 SDK/RPC 宿主**。须主代理提交具体边界后单独核对用户授权；显式运行参数本身不是授权。

入口仅使用两包根公开 exports：coding-agent 的 createAgentSessionRuntime、createAgentSessionServices、createAgentSessionFromServices、runRpcMode、SettingsManager、SessionManager、ModelRuntime，以及 pi-ai 的内存 credential/model stores、Type、合成事件流。没有私有 import、宿主 monkeypatch 或上游修改。本探针检查公开 SDK 的 RPC mode，不代表 CLI 参数、所有自动 factory 或产品权限验收。

固定 Pi 1.0.1 / pi-ai 1.0.2 / Node 24.14.0；候选 lock SHA256 为 `f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac`。顶层 expected_versions 是冻结输入；成功案例 observations.versions 来自实际 worker 读取并核对的版本。

## 独立五案例

| 案例 | RPC 输入 | 必须观察 |
|---|---|---|
| timeout | confirm 后不响应 | 正文0、无哨兵、confirm false、工具 error |
| cancelled | 原ID cancelled:true | 正文0、无哨兵、confirm false、工具 error |
| wrong-id | 错ID confirmed:true | 默认超时后正文0、无哨兵、工具 error |
| abort-late | confirm 后abort，等tool end/agent_settled/abort回执，再发原ID确认 | signal实际aborted、正文0、迟到确认不重启正文 |
| confirmed | 原ID confirmed:true | signal未aborted、正文恰1、唯一合成哨兵、工具非error |

公开 session_start 上下文应为 hasUI=true / mode=rpc；hasUI不能自动许可。唯一自有工具的正文 guard 是 `confirmed === true && !signal.aborted`，只写 `/work/body-sentinel` 的固定合成文本。confirm 传入公开 signal 与1000ms timeout。

每案例独立内存session/进程/work。父进程先等 get_state 的 idle 状态才发prompt；prompt disposition=started只表示接收。Oracle同时核验真实RPC工具start/end/error、agent_settled、idle回执、事件与发送命令索引、内存credential/工具白名单、状态文件与独立哨兵。迟到确认只在abort真实回执及settle后发送，并以get_state响应作处理屏障。最后关闭stdin，观察公开session_shutdown和正常退出0；runRpcMode公开EOF路径await runtime.dispose后退出。生命周期缺证或意外错误均失败。

## 拟运行命令（尚未执行）

目标目录必须尚不存在，父目录须安全存在并属于当前用户：

```bash
/usr/bin/timeout --signal=TERM --kill-after=5s 60s \
  /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/.venv/bin/python -I \
  /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/scripts/pi-probe-official-rpc.py \
  --run-native-rpc-probe \
  --output-dir /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/.cache/pi-two-profiles/run-20261004/rpc-native-01
```

Python总预算60s、每案例10s，就绪5s/协议步骤3s/关闭2s deadline；worker另有10s硬截止。异常先关闭stdin，再只对保存且仍存活的自有bwrap句柄有界terminate/kill，不操作其他PID。外层timeout最终限制墙钟；die-with-parent关闭自己的隔离进程。中断/超时/不完整结果保持failed或not-run，不从exit0推定通过。

每案例固定argv：

```text
/bin/bwrap --die-with-parent --unshare-all --new-session --cap-drop ALL
  --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64
  --proc /proc --dev /dev --tmpfs /tmp
  --ro-bind <repo>/.cache/pi-two-profiles/candidates/pi-1.0.1/closure /candidate
  --ro-bind /home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0 /node
  --dir /probe
  --ro-bind <repo>/scripts/pi-probe-official-rpc.mjs /probe/worker.mjs
  --ro-bind <repo>/tests/fixtures/pi/official-rpc-probe /probe/fixture
  --symlink /candidate/node_modules /probe/node_modules
  --bind <新0700案例work> /work
  --setenv <以下每项闭合环境> --chdir /work
  /node/bin/node --max-old-space-size=512 /probe/worker.mjs --native-rpc-worker <固定案例>
```

父Popen为shell=False/env={}；不继承认证、代理或npm配置。本机bwrap无--clearenv，采用空父环境和显式setenv。完整Node环境只含HOME=/work/home、PWD=/work、PATH=/work/empty-bin、PI_PROBE_NATIVE=1、PI_OFFLINE=1、OTEL_SDK_DISABLED=true、TMPDIR=/work/tmp、XDG_CONFIG_HOME=/work/config、XDG_DATA_HOME=/work/data、XDG_CACHE_HOME=/work/cache、XDG_STATE_HOME=/work/state、LC_ALL=C.UTF-8；worker逐项核验。

candidate、Node、自有代码与系统库只读；只写新/work、独立/tmp与namespace内/proc、/dev。无真实HOME/Pi/Codex账号或凭据挂载，network/PID namespace独立。SettingsManager全部资源/packages为空、projectTrusted=false，loader关闭发现，只绑定显式自有extension，不调用安装器或外部工具。ModelRuntime采用两种内存stores、modelsPath:null、allowModelNetwork:false、refreshOnCreate:false；固定synthetic.invalid地址不被调用，streamSimple仅产生内存响应，不解析环境认证。

这些代码/argv表达预定零账号与模型外发边界；实际namespace和挂载需执行者独立核验，脚本自报不证明OS隔离，也不提供防同UID篡改的密码学承诺。

## 准备证据和工件

运行目录0700，原始stdout/stderr/commands、invocation、state和结果均在私有案例目录（文件0600）。每案例stdout/stderr合计≤1MiB，JSONL单行≤64KiB，仅按LF拆分，拒重复key/非object/无效UTF-8/非有限JSON。公共结果只含闭合身份、观察、退出/超时状态和固定限制，不输出原始异常、环境、模型正文或账号。已有输出或哨兵拒绝覆盖。

结果只有observed/failed/not-run，无passed/accepted。默认fake-process/oracle测试不是O或产品通过证据。RPC原文均为合成模型和自有工具，仍只存于私有目录。

已执行准备检查（不启动bwrap或SDK）：

```bash
/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node --check scripts/pi-probe-official-rpc.mjs
/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node --check tests/fixtures/pi/official-rpc-probe/extension.mjs
.venv/bin/python -m pytest -q tests/test_pi_official_rpc_probe.py
.venv/bin/python -m compileall -q scripts/pi-probe-official-rpc.py tests/test_pi_official_rpc_probe.py
git diff --check
```

Node --check不解析/import官方包；pytest仅纯协议/fixture/负向oracle与固定fakeprocess。实际结果日志 `/tmp/pi-official-rpc-probe-final.log`；全文hash `/tmp/pi-official-rpc-probe-final-hashes.json`。准备内容身份：

| 文件 | SHA256 |
|---|---|
| worker mjs | a57ae7440da298a15d1f040704cb5b6bfecef63d40bc1b432f0e8d8be3067779 |
| extension mjs | efd0c116d31f4d6b6ee12de84140049880db3107bc7c7b8772034afa0836539b |
| plan JSON | 583d09cfcd29682793ca92cc83d39bc8f1e9898e06faaf137e73628999808835 |

授权需覆盖这五个自有合成案例、官方公开SDK RPC宿主执行与同边界必要修复重跑，不含账号登录、真实模型调用、联网、安装脚本或产品预算/验收更新。
