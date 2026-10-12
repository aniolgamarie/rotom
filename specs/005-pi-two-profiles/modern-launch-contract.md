# 现代 Pi 启动契约接线

2026-10-07 root 实施候选。B4 installed 观察代码 STOP 后已由 root 验收默认组件，93 输入 receipt `7c7e365d3adec97598e45c02bcfe3488c1ddef5e7fa6c3f9e7971c5aa8f456bd`。原 `PiAdapter.launch_spec` 对 `pi-base`／`pi-full` 明确抛 `pi-modern-launch-unavailable`，因此原 `runtime.record` 不能生产现代 current.launch。先补齐这一实际 producer 接缝；不从手写 launch 或 DSH fixture 推导 Full 来源资格。

本包形成可验证的启动契约，不切换默认 profile、不安装或部署、不启动宿主、不把 candidate 改为 current/accepted，也不打开 reviewer AUTO。当前 `agents/pi/dependencies-modern.json` 声明只有 Base candidate，不能称完整正式锁；固定 backend 读取路径 `locks/pi-modern/manifest.json` 未提供，正式 Full profile/锁同样尚缺。真实运行、账号、权限与隔离组合、完整来源和最终产品 gate 分别验收。

## 复用的实际接口

`runtime.record` 继续调用原 adapter.launch_spec，并由原 backend 计算 lock/runtime 身份。原部署 producer、state schema、generation、binding、环境和 credential reference 语义不变。`runtime.run` 保留原 lifecycle／state lease／instance／package guard、current binding、installed status、资源漂移、精确 preflight、环境解析和 launch_executor 顺序。

现代声明已有 `runtime/official-launch.mjs` 行，对应自有源码只通过官方 SDK 根公开 exports 创建模型／文件 runtime，读取固定实例 manifest 和 `runtime/profile.json`。声明行不是实际 sealed 运行包证明。该入口要求 Node 的 `--experimental-import-meta-resolve`，且 CLI 以 `--manifest <instance>/pi-home/agentcfg-manifest.json` 开始。installed.entrypoint 仍是所选 SDK 的公开入口，不能改成自有 CLI 文件以绕过 SDK package 解析。先前 SDK 探针只保留原有限结论，本包不执行它们或复用已闭合 native 授权。

scout 窄证据已确认 pi-supervisor 将收到的 argv 与 bootstrap config.argv 比较后转交，Linux namespace 将原 command.argv 放在末级 gate 的 `--` 后；root 另读末级 `scripts/pi-namespace-exec.py`，host 分支在原 G 门控后以 `os.execvpe(sys.argv[4], sys.argv[4:], os.environ)` 转交，不另解析 Node flags。这只闭合静态接口，没有执行或证明 namespace/exec 实际资格，不新增任意 argv 执行入口。现代健康包只有沿原整体 installed gate 后才进入 existing supervisor 路线；Durable 的 unavailable 不应变成 ordinary editing 的初始化等待。

## 唯一写入范围

拟实现范围为 `src/agentcfg/pi.py`、`src/agentcfg/runtime.py`、新增 `tests/test_pi_modern_launch_contract.py`，以及 `tests/test_pi_profile_projection.py` 中唯一函数 `test_modern_profile_cannot_fall_through_to_legacy_launcher`。该函数原 5 行期待 modern unavailable；保存实际前像后，只把这个已过期断言改为现代固定 argv/flag 且不含 legacy launch.mjs 的正控。保留原函数名、其它所有旧代码和覆盖，不修改原 fixture 以回避实际 gate。

不改官方 SDK／第三方源码／cache、modern 完整锁或 recipe、provider/catalog/bindings、默认 profile、runtime/profile producer、HostSupervisor schema/角色、initializer carrier、source 身份或服务 IO。若 supervisor 的封闭 argv 规则需要新生产接口，交 root 重新冻结范围；不得用 permissive fake 消掉旧规则。

## 现代 spec 与环境

`PiAdapter.launch_spec` 首先保留原 `validate_selected(data)`。仅当原解析 profile 为 `pi-base` 或 `pi-full` 时选择现代分支；选定 engine 必须是 `node`，Bun 不能默默改成 Node，也不能落回旧 runtime/launch.mjs。

现代 argv 精确为：`node`、`--experimental-import-meta-resolve`、所选 runtime_root 下的 `runtime/official-launch.mjs`、`--manifest`、原 instance_root 下的 `pi-home/agentcfg-manifest.json`。业务参数仍由原 runtime.decode 加在这个固定尾部；不允许参数选择入口、manifest、SDK、agentDir、sessionDir 或 provider 替代。runtime_root/instance_root 来自原 caller，不由新公开 JSON 提供。

环境继续由原 Pi 环境 producer 生成并由原 launch_environment 解析，HOME／PI_CODING_AGENT_DIR／PI_CODING_AGENT_SESSION_DIR 必须是同一原实例的 user-home／pi-home／pi-home/sessions。没有新增 credential value 读取、token 文件、PATH fallback、初始化 cap 或 Full 探测。CODEX_HOME 和其它可选环境仍受原所选能力条件约束；Base 的声明与加载不能借本分支引入 Full 资源。现代 main 现有 PI_OFFLINE／PI_SKIP_VERSION_CHECK 仅禁后台探测，不能称网络沙箱。

legacy 分支保留原 engine／Bun flags／runtime/launch.mjs 与环境语义。不要为复用现代代码改变旧 argv 或宿主路由。完整上游工具限制仍由各原 package/权限/隔离控制执行，本包不自行改变授权。

## 业务参数的原调用接缝

新增可选 adapter hook `validate_arguments_for(data, arguments)`。`runtime.run` 在原最早参数检查处优先使用这个 hook，未提供时仍调用原 `validate_arguments(arguments)`；检查之后的既有顺序不改。Pi hook 在 legacy profile 上直接委托原 validate_arguments 并返回 None；modern 返回已验证的自有 exact native tuple[str]。新 hook 返回域仅为 None 或 exact native tuple 且所有元素为 exact native str；未知返回类型以新的固定 `ConfigError("runtime-arguments")` 清 cause/context 拒绝，零 foreign 方法，不能静默忽略。非 None 结果替换 run 的局部 arguments，之后原 operation_cwd／guard、decode、environment、before_spawn 和 executor 所用参数均沿这个捕获值；不改后续 operation_arguments 自身既有语义。None/未提供 hook 保留 legacy 与其它 adapter 的原路径。

现代分支与已存在的 `parseOfficialArguments` 语法一致：默认 TUI；`--print`；`--mode rpc`；`--thinking` 后接 off/minimal/low/medium/high/xhigh/max；`--help`／`-h`；`--` 之后均作消息正文。只能选择一次 print/rpc mode；thinking 只能出现一次；rpc 不接消息；未知或缺值的 flag 固定拒绝。当前现代 parser 没有 `-p` alias，不能借 legacy validator 接受后进入不同语义。后续若扩展 CLI 须同时更新这条接缝与公开 SDK 入口。

本次现代 hook 只接受 exact native tuple/list 的有限原业务参数及 exact native str 元素，单次捕获为自有 tuple，完成校验后返回该同一 tuple；拒 NUL 和 surrogate。不得调用 foreign iterator/string 方法、序列化消息或在错误中带 argv/正文/私有配置。普通错误使用本模块自有固定 `ConfigError("pi-arguments")` 并清 cause/context，控制 BaseException 保留原对象。参数捕获不是原子快照；原 argv 域没有新消息长度预算，不添加未经定义的限制或通用 heap 保证。迟到 callback 改变原 caller list 后，后续 run 仍必须使用已捕获参数；不能再次迭代或验证原 list 的新值。

## 默认验收

默认沿现有临时 HOME/DSH/XDG/OS-account、断网、fake 子进程 guard。测试需要实际调用原 runtime.record 和 deployment.apply/read_state 或固定生产接缝；现代正控制允许使用独立合成临时 Workspace/backend 资料，实际 PiAdapter 的 validate_selected/launch_spec 不能换成 fake validator=True。原 record/apply/readback 的执行与合成 backend 身份/材料分别记录，不声称完成原 PiBackend 的实际 Full 正控；正式来源闭合后还须沿实际 backend 再验。不能借 fixture 开启服务或改 candidate gate。

分别覆盖固定 argv/Node flag、实例环境、SDK entrypoint 与 own CLI 分工、legacy 原行为、错误 engine、未知 profile／flag、重复/缺值 mode/thinking、rpc 消息、separator 后正文、foreign 参数零方法、错误正文与 ambient exception 不泄漏。至少一条原 runtime.run 测试证明新 hook 在 lease/credential/child activity 前检查，迟到 caller list 被替换为 foreign 或未验证 flag 后所有后续用途仍沿原 tuple，未知 hook 返回域固定拒绝；其它 adapter 的旧参数路径仍工作。

原 modern candidate 的安装／准入反例、missing/damaged installed runtime、旧 binding 与资源漂移、原 runtime_identity 两种保存编码不能因这个分支通过。只运行新 suite 及确切受影响旧 selector；collection、实际退出码和 XML、源码前后摘要分别记录，不重跑 B4/B3 全套。固定 SDK mock 或 fake child 仅证明本仓库组合算法，不是 SDK/TUI/RPC/账号或 bwrap 产品实测。

root 在默认证据和停止写入后的稳定 diff 验收后，继续正式 Base 来源／公开 SDK 组合及 Full 原 producer/current 来源接线。真实宿主、FD／namespace／账号组合另准备明确材料和必要授权；本包不消费已闭合 Recovery3／Harness8／FD6 授权。正式任务状态与产品 gate 由实际证据决定，不因本有限组件提前勾选。

## 2026-10-07 稳定默认实现结果

四文件 STOP 后 root 审查完整新测试与三个原文件稳定 diff，并核对原 runtime 后续顺序逐字节不变、旧 profile 唯一函数逆变换、实际 collection/XML/log/UID/首末 pin/临时目录回收。197 输入 receipt `9665b731cdd863c544f9c7d8b6ac7e6ec035376b1ca1e5a4ed7647915bcf7e02` 接受这一有限默认组件；没有重跑其它已接受套件。生产 pi.py 为 35485d596b9a41e365fdccac85651827ea966ece504d07687f531c3e09bbb45d/41321B，runtime.py 为 633799e3e08b52ebc443eb085f334de81ad1de1ed64cd074d99bc2776ce45591/10006B。

首轮 new01 实录 45fail/27pass：34 个断言把原 ConfigError 的中文前缀错误当作裸 code、一个合成 Full 配置缺独立投影声明、十个 IO case 遇默认 wrapper 的祖先属主守卫。修正新夹具并沿正常属主执行原离线守卫后，new02 同次 73pass/36.71s；仅追加 SDK entrypoint/own CLI 合成资料不改写一项，另次 1pass/2.98s。当前 collection74 的成功覆盖是 73+单项1，不称一次74pass。旧六函数实际12nodes分六批全部pass/零skip/error，首轮失败工件原样保留。legacy 显式调用原 validator 后返回 None，opaque 返回值零 callback 反例在 new02 内通过。

unknown profile 的拒绝由实际 load_workspace 选择域验；合法自定义 legacy ID 保留旧解析路径。本包原 record/apply/readback 的正控使用明确的 SyntheticBackend 身份、材料和 lease stub，SDK entrypoint 单项也只为不执行的合成资料分工；实际 PiAdapter.validate_selected/launch_spec 和原部署 producer 确实执行，不能外推为原 PiBackend 正式 Full 或已安装 SDK 正控。原 PiBackend candidate sync 拒绝另有实际默认反例。完整来源、实际安装/backend/current、SDK/native/角色/持有链和产品 gate 均待分别验收，AUTO OFF 保持。
