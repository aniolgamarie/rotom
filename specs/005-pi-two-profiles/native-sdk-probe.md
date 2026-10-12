# 官方 Pi SDK 隔离接口探针

状态：用户已明确授权本隔离探针及同边界内必要修复重跑。2026-10-04第05次执行的六项原生断言全部observed，退出0，扩展错误0；结果schema、用例集合、版本、stdout与结果文件一致性已复核。主代理及独立scout审查未发现阻断问题，产品gate未通过。默认离线协议检查14 passed另属准备工件验证。

入口为仓库自有`scripts/pi-probe-official-sdk.mjs`，SHA-256 `76ede8ec15e1f06696548fac7cd609587dfe6e9a9accc8b09a8ebc9607874e4c`。显式扩展factory为`tests/fixtures/pi/official-sdk-probe/approved-extension.mjs`，SHA-256 `fde29a779b3e70e2ff80d619dc07ab63be618dd2efcf5c60c5ef1ff305512ca0`。其余诱饵和允许资源的内容身份见同目录`plan.json`。官方候选package-lock身份见research.md的T006记录。

只使用官方包根公开exports：Pi coding-agent 1.0.1及其闭包pi-ai 1.0.2。设置和认证存储均在内存，Provider返回合成响应；模型发现联网和自动refresh关闭。不会挂载真实HOME或认证目录，不读取共享模型密钥，不进行付费或外部模型请求。

六项原生断言：

1. 显式extension/skill/prompt精确加载，全局、项目与祖先目录的诱饵不加载；SYSTEM/APPEND输入准确。
2. 顶层工具通过公开`ctx.executeTool`调用子工具，实际事件包含父调用身份。
3. 公开`tool_call`拒绝子工具时，子工具正文计数不增加，调用结果及宿主错误事件一致。
4. `session.abort()`使父子调用继承的signal取消。
5. SDK JSON模式的`hasUI=false`，自有需要人工操作的工具明确拒绝并产生宿主错误结果。
6. `session.reload()`后仍保持同一资源白名单，观察新的session_start。

运行使用新建0700目录（位于私密运行记录目录内）挂载为`/work`。下面的`REPO`、`WORK`和`NODE`仅表示执行器替换的固定绝对路径，不是shell环境变量；实际以argv列表调用，无shell插值，父subprocess传入空环境`env={}`。本机bwrap不支持`--clearenv`，因此由父启动器清空环境，再仅使用下列`--setenv`白名单；探针核对每个环境键和值。

```text
/usr/bin/timeout --signal=TERM --kill-after=5s 60s
/bin/bwrap --die-with-parent --unshare-all --new-session --cap-drop ALL
  --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64
  --proc /proc --dev /dev --tmpfs /tmp
  --ro-bind REPO/.cache/pi-two-profiles/candidates/pi-1.0.1/closure /candidate
  --ro-bind NODE /node
  --dir /probe
  --ro-bind REPO/scripts/pi-probe-official-sdk.mjs /probe/pi-probe-official-sdk.mjs
  --ro-bind REPO/tests/fixtures/pi/official-sdk-probe /probe/fixture
  --symlink /candidate/node_modules /probe/node_modules
  --bind WORK /work
  --setenv HOME /work/home --setenv PATH /work/empty-bin
  --setenv PI_PROBE_NATIVE 1 --setenv PI_OFFLINE 1
  --setenv OTEL_SDK_DISABLED true --setenv TMPDIR /work/tmp
  --setenv XDG_CONFIG_HOME /work/config --setenv XDG_DATA_HOME /work/data
  --setenv XDG_CACHE_HOME /work/cache --setenv XDG_STATE_HOME /work/state
  --setenv LC_ALL C.UTF-8 --setenv PWD /work --chdir /work
  /node/bin/node --max-old-space-size=512
  /probe/pi-probe-official-sdk.mjs --native-sdk-probe
```

`NODE`固定为已准备的Node 24.14.0安装目录。所有程序、依赖与fixture只读，仅`/work`及沙箱私有`/tmp`可写。网络和PID等namespace隔离，宿主账户目录不可见。脚本自身30秒硬截止，每项异步操作5秒截止，外层60秒截止；日志和结果仅保存到本次私密运行目录。

结果以`observed/failed/not-run`和具体观察表示，并由退出码及schema检查复核。该探针不签发产品passed，不包含RPC前端测试、真实模型质量、账号就绪或生产文件/网络沙箱验收。空packages和无安装产物是本次观察，没有进程跟踪时不扩大为“宿主绝无任何安装路径”。

授权范围只涉及上述隔离SDK接口探针及同边界内必要修复后的重跑；正式部署、默认profile切换、真实模型、Codex账号、源码外发均不属于本次动作。

实际记录位于私密目录`.cache/pi-two-profiles/run-20261004/sdk-native-05/`，保存invocation、execution、stdout/stderr、结果及独立schema复核摘要。第01次在bwrap参数检查退出，第02次在SDK导入前的环境白名单检查退出；第03/04次前五项通过，reload后的资源白名单也通过，但没有收到第二次session_start。静态核对公开`ExtensionBindings`后，增加有实际错误计数用途的`onError` binding；第05次观察到两次JSON模式、hasUI=false的session_start，错误计数为0。修复未减弱原六项断言。启动器曾误选系统旧Python并在import阶段失败，未建立该次运行目录或执行SDK，随后改用已准备的Python 3。

稳定审查结论：隔离判断来自记录的bwrap argv、父环境清空、成功执行及脚本内闭合断言；未采集独立syscall/mount审计。真实账号目录不可见，但未用读取跟踪证明临时auth诱饵从未被读取；onError计数只覆盖ExtensionRunner报告的错误。第二次session_start与reload的对应由调用顺序及公开实现支撑，结果不含event.reason。上述限制不影响本六项接口观察，也不能据此扩大支持声明。
