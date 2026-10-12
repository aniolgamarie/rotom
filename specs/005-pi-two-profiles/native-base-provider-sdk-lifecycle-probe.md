# Base 本地扩展的公开 SDK 生命周期探针

状态：review02 默认准备及 Todo 代际/独立会话 P2 修复已稳定复核；用户已明确授权四场及同边界必要修复重跑。root已保存前像、开启两个自有 executable guards并同步授权元数据，四场已取得限定通过并完成稳定复核，Loop首次wrapper失败保留；两版本分别记录，native_qualified=false。旧 SDK4 授权已执行并闭合，不包含本材料。

## 固定范围

仅当前 Linux x86_64，固定 install01 官方 Pi1.0.1 / AI1.0.2 与 Node24.14.0；实际三提供者归档入口。四场分别为 Footer、Loop Guard、Todo、组合，各新私有0700 work及独立 Node。只通过包根公开 DefaultResourceLoader、ModelRuntime、ModelRegistry、SessionManager、ExtensionRunner，使用每次实际 loaded.extensions/runtime 和官方 callback ctx，不私有import或修改上游。

Footer观察合成UI callback/render及关闭后的自身UI更新；Loop观察重复额度、公开checkpoint写入及临时会话真正open/reload重放；Todo直接调用公开tool definition，观察临时详情持久/重开、两个独立loader/runtime/session/UI的隔离、关闭和迟到UI。组合仅共享ctx/共存注册、直接resource观测、roles selection-only及失败闭合，Loop/Todo业务字段null不算通过。

UI是合成公开接口对象，没有启动TUI/TTY/编辑器。direct tool定义调用不是主模型调度。SM初始user anchor和manager marker均为测试fixture，不能自授真实用户/manager权限。凭据与models存储仅官方内存对象，关闭模型联网与refresh，无真实账号/密钥/模型/账单。不启动Codex/MCP/服务，不部署、不切换默认profile、不写真实provider支持声明。

## 隔离与保存

自有 runner在bwrap外核固定只读候选完整16653树与Node/timeout/bwrap/本材料。父Popen env={}；bwrap unshare-all/new-session/cap-drop ALL，仅固定候选、Node单文件、driver/plan/两自有resource模块及系统库只读。HOME/XDG、cwd与临时session均为私有work，网络断开，真实HOME/业务根不可见。每场driver20秒soft timeout、timeout60秒kill-after5秒、wrapper70秒及有界group/pipe收尾；首末校验不计入执行截止。

每场只有child/wrapper0、stderr0、pipe EOF、原group empty和首末材料/树相等才保存实际SDK结果；文件关闭shape且<=64KiB，与stdout逐字相等，exclusive600/fsync/readback。失败work/报告均保留，不rmtree。normal outer group/EOF不证明namespace全部后代或SourceHold，native_qualified始终false。

新目录为 .cache/pi-two-profiles/run-20261004/base-provider-sdk-lifecycle-preparation-review01/。未来独立命令使用其中runner.py、--case footer-only/loop-only/todo-only/combined与新run-name；不复用旧SDK4 executor或true守卫。最终计划SHA和root稳定复核将在修复后追加，本状态不得执行。

默认根盘/tmp ENOSPC已按root决定绕至/data的自有临时目录，未删除旧材料。默认fake测试与真实SDK结果分开；P2前首driver11/runner11、后续有效RED及受影响测试均保留，不拼为单轮总数。

## 授权依据与限制

仓库 [AGENTS.md](../../AGENTS.md) 要求：“真实 smoke 为独立显式步骤，需用户明确授权”。本次新接口、生命周期/direct Todo业务/持久重开范围没有在旧加载注册SDK4授权中；完整材料与修复稳定复核后才请求新的具体授权，同范围必要修复可包含在该授权中。

目前实际SDK生命周期、真实TUI/SSH、宿主工具调度/mode恢复、SourceHold/Full/controller、整体隔离与产品支持均未通过；正式8/100，严格输入计量未验证前AUTO OFF。

## 当前修复后 review02 固定材料

root 已接受默认准备及修复后稳定独立差量（无具体P1/P2），receipt 3ea05caff33b5e91d6e4d875134756ecfceaed2cfbbd55abeac5232c19b2d44f。初阶段driver11/runner11通过；Root P2新WeakMap oracle真实RED后，受影响Todo完整流程与旧代/跨runtime/rebind负例一次1/1通过，未重跑或伪造单轮12/12。修复前报告/原失败/环境失败与全部前像已保留。

当前 false plan SHA：48b3dffce5fab29f0746008d22d2e2c45e83f301e84a32426008053dac99234f（4162B）；driver 25183B / bad7530bf53dc59aead1a0ef12f7bdd5537b56eeb44eb7135599699a43c17695；runner 29719B / 132226c0f21e71c503b832938fbe64f8ac01ecf84ded5b3b2439daa6cbcb0789；material-pins 1679B / 801c4f3648a251feb5c4f784fc91a12caa139825840ac6cad6e5c46e980dda80。SDK完整树/工具沿既有install01证据，不把默认small pins宣称native首末核对。

未来授权后的固定命令形状（CASE为上述4固定值，RUN-NAME为新私有名称）：

    /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8
      /usr/bin/python3.11 -I -S -B
      /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/.cache/pi-two-profiles/run-20261004/base-provider-sdk-lifecycle-preparation-review01/runner.py
      --case CASE --run-name RUN-NAME

这是待授权命令；当前运行必在新字面false守卫拒绝，未执行。用户批准本具体计划及同边界必要修复重跑后，root先保存即时前像，再仅开启两自有guard、同步plan授权元数据及依赖SHA，冻结授权后材料，qualification仍false；不得改变官方包、安装树、原授权材料或生产配置。每case首次名称为footer01/loop01/todo01/combined01，成功和失败work均保留。

## 用户授权执行记录

用户明确回复：我授权，你继续吧。授权对应上述false plan48b3dffce...四场及同边界必要修复重跑。root保存前像receipt ec7bad88f2105c7d03f78ede6fb057f647b5666ff18ce56ad558216569ba3f73，仅打开两自有executable guard、同步plan授权及ready元数据并刷新依赖SHA；授权后冻结receipt 8f3f334e8cd0a055ee3f86a9ca9c0e72be25b750ecdd7820329aec31e8ba1f0f。这些metadata不是额外可执行守卫，也不是资格。固定官方包/安装树及qualification=false保持。授权后小文件pins：{"driver.mjs": {"bytes": 25182, "sha256": "2cea1f2313432d47f35743c1a3d792223c01af5830b5fdd1dbe91d16c863b906"}, "runner.py": {"bytes": 29718, "sha256": "e53803eab7a7653116ad8a8e3dd4c96752be350007b59241eeab304901bad361"}, "plan.json": {"bytes": 4161, "sha256": "efe837fdf1fdbbc4e742d4e2262ee070835ef355dd795cf551877b6b425937f5"}, "material-pins.json": {"bytes": 1678, "sha256": "b7b7e4ddfea83a4da11d165db8d9030c4b52c7f5a7e12ca582452ca0488f81b6"}}。

## 实际完成与限界

原材料版本：footer01结果1335B/SHA85f8f97aceb83bcaada7f68cc6470cd4734f26c7412b1720a7e39cae73fb15a7；todo01结果1331B/SHA6d25ae984803fdb5ed0ebf96d0d478a6941bf7305ad27cea907b18ff7559c1f6；combined01结果1370B/SHAddd2e7fc83b2020099f6f4b4a6f9b47162662ced087e18ab198b4eed951c7b96。loop01 SDK业务条件true但wrapper oracle错误要求witness4而实际只2，wrapper退出1、不计通过、work及失败报告保留。

root按已授权同边界修正loop-only计数：明确公开调用requests4、SDK前置block短路后的witness恰2，quota/replay及拒绝return继续验证；不重排扩展/不改SDK/不加其他case字段。default有效RED后受影响driver1/1与严格schema4/4，另一次pytest名字collection失败保留。仅loop02重跑，通过结果1365B/SHAca54d2d57be07adcd3b9019b123602f687b7624792f8b78070beeea69702be21，绑定修复后单独材料版本（plan a5beb3e9f7d7ce5ce34877952c4719374739d30f2669fcd218d156a3da344009）。

四通过场均child/wrapper0、SDKerrors0、stderr0、group empty/pipe EOF、固定16653树和Node/tool/probe首末相等，实际result文件与stdout当时逐字相等；stdout BytesIO已丢弃，没有另存raw，root/scout只能复核保存结果及执行记录，不能宣称独立重取stdout。没有补跑来弥补此限界，也不将两版本拼为同最终源码四场批次。独立保存文件复核无具体P1/P2，root归档35个输入，实际receipt 56fba8c372c96982e688ef3e572f38d34b6c7f1c335323e104436dfd10848a20，输入数 35。

本批grant已满足并闭合，没有后续计划SDK调用；两个开启守卫作为历史执行材料保留。未改实际SDK/vendor/安装树/provider/lock/生产配置、未调用账号/真实模型或外网/realTTY/服务/部署，资格false、正式8/100与AUTO OFF。
