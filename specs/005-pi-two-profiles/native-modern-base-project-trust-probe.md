# 当前 Base 项目信任公开 loader 探针

## 当前实际结果：允许／拒绝两场已观察并有限验收

2026-10-08 用户明确授权三套材料和同边界必要修复重跑。原false计划e688…0354及开启guard前像保留。trust01／trust02均child／wrapper2；第二轮固定诊断证实拒绝场全0，允许场skill／prompt各1、extension／marker0、errors0。读取固定公开loader发现默认扩展发现仅支持.ts／.js，原.mjs fixture被忽略。只将自有扩展生成位置及精确期望改为.js，正文、单资源、回调和全部oracle保持；对应paired fake反例真实red／green，未使用显式additional path绕过project trust，未改上游或调用私有API。

trust03一次两场observed，child／wrapper／tool0，合法结果686B／SHA **`f59e4203bda9e02da4bb769357290613f2b6c4ded0b1bd94a8a2556206e44455`**。拒绝resolver1、三资源0、正文0；允许resolver1、三资源各1、正文1；error／diagnostic0。Python原目录链读取得到实际allow marker5B，deny不存在，两场相同fixture正文；结果root／work原字节相同，执行时stdout逐字核对、stderr0／EOF，保存的16,653项树与材料before／after一致。

scout独立只读保存小工件／目录元数据与marker，结果和首末pins一致，无P1／P2；没有重跑SDK或扫描树，未假称重新取得未落盘的stdout。root16输入验收receipt **`40bdbb0bc86c6752d62c50d4dced589b2690e1d9ec929fac22125cadc63cd03c`**，本两场授权已满足并闭合，trust01／02失败全部保留。本结果仅public reload；CLI首次启动、保存信任继承、默认RPC ask、工具沙箱、持续SourceHold、namespace全后代／controller／真实模型／产品未资格。Q1完整性另由T006验收判定。下面未执行、false guard和.mjs描述均为原准备历史。

2026-10-08（本地），review01。准备包：`.cache/pi-two-profiles/run-20261004/modern-base-project-trust-probe-preparation-review01/`。两个执行守卫为false；尚未加载官方SDK或执行bwrap。公开API与设计契约经scout有限复核，无P1/P2；新的driver／执行器组合由root在写入完成后审查。子代理复用与新建均返回`agent thread limit reached`，因此没有新实现的独立子代理审查，不能沿用旧组件审查冒充这一项。

false plan SHA：**`e6880104029b9c1f6fc2fcf8190f9ed7aa8728e7b0fcdcb74d5152dc5b170354`**。精确driver、fixture、executor与工具pins在该plan及`material-pins.json`；安装树为已保存的Base install01，Pi1.0.1／PiAI1.0.2，16,653条目／124,615,286 regular bytes，inventory SHA `4456d8b746f35694d272a4980021490c5299cb277bf1d497da24eca930f882f3`。未新跑Node版本或重hash整棵树；每次未来真实运行须重新做有界前后核对。

## 两个固定控制

两场各在全新私有目录放入相同的`.pi` project extension、skill和prompt，使用独立空agentDir及新的公开`SettingsManager.inMemory`，不预设`projectTrusted`，`defaultProjectTrust=ask`。仅通过包根公开`DefaultResourceLoader`、`reload({resolveProjectTrust})`和资源getters，不创建会话、ModelRuntime、工具或模型。

- 拒绝：自有resolver实际调用并返回false；extension／skill／prompt均0，扩展正文marker不存在。扩展中声明yes的`project_trust` handler不能靠自身先加载来批准自己。
- 允许：相同fixture正控制，resolver实际调用并返回true；三个资源各精确1、错误／diagnostic0、正文marker固定字节恰一次。固定扩展用独占创建，重复正文写入失败；fake计数2亦拒绝。

回调缺失、在信任前已经加载项目扩展、wrong collection、marker缺失／重复、坏版本、foreign／未知结果均失败。不能把requested boolean写成observed。Node公开fs只在自有全新0700 case目录观察固定marker，采用限长、末级nofollow、regular／single-link及原fd首末身份检查。Python另外用已接受的原目录FD逐级nofollow reader读取实际marker，并与严格结果字段核对；不声明Node拥有私有dir_fd接口。

## 实际执行与边界

授权后唯一命令形状：

```text
/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8
  /usr/bin/python3.11 -I -S -B
  /data/1/weixiaoxian.wxx/dev_tool/rotom/.cache/worktrees/pi-toolkit-upgrade/.cache/pi-two-profiles/run-20261004/modern-base-project-trust-probe-preparation-review01/executor.py
  --execute-after-new-project-trust-authorization --run-name trust01
```

root须先保存两个守卫及对应material/executor摘要的即时前像；仅开启自有`executor.py`和`driver.mjs`守卫，更新对应material SHA及executor内预期SHA并冻结。不能使用环境或参数绕过，也不继承SDK6已闭合授权。必要同边界修复重跑每轮使用新的run-name及work，保留原失败；新场景或改变资源／账号／模型边界不沿用授权。

外层`timeout --signal=TERM --kill-after=5s 60s`加`bwrap --unshare-all --die-with-parent --new-session --cap-drop ALL`。固定安装包、Node单文件、自有driver及fixture模块只读；`/usr /lib /lib64`只读，新proc／dev／tmp。仅新work及其临时HOME/XDG可写，父环境为空，内部PATH为空目录。不挂真实账户HOME、仓库业务根或socket；断网，不启动Pi TUI／Codex／MCP、不读账号、不调用真实或合成模型、不部署。

Node事件循环soft timer20秒、GNU60＋5秒、wrapper执行70秒、独立原group收尾最多30秒及最后pipe drain2秒。有限preflight／postflight／证据保存不计入执行deadline，没有整个操作硬截止保证。stdout、stderr各64KiB，仅计数；stdout短暂留内存用于与合法结果逐字核对，不保存任一原输出或外来异常。实际结果最多64KiB，marker16B；树每文件64MiB、总512MiB、65,536条目、深度128，Node单文件另有128MiB ceiling及精确大小SHA。

进程收尾沿用已接受SDK6的原leader未reap观察后TERM／KILL及最终wait；14个原函数AST相同。结果为positive必须两场严格JSON／schema／版本／计数和真实marker核对、file／stdout逐字一致、stderr0、pipe EOF、child／wrapper0、整树及工具前后一致。unknown、缺结果或异常均不能签通过。全部work在所有结果下保留，无rmtree。

## 已有默认证据与资格限制

Node自有默认层：最初仅file级失败未取得各用例诊断；改为test isolation none后，stub状态真实15fail。实现后23tests中22pass／1测试预期错误；固定fixture独占创建的预期修正后，仅该原节点1pass，当前23个不同用例跨轮覆盖，不能称同次23pass。Python自有层：11tests中8pass／3错误，遗漏的reader上限常量补齐后，仅受影响3pass，当前11个不同用例跨轮覆盖。原日志、前像及失败报告均保存，三JS模块syntax和Pythoncompile通过；未跑官方SDK、bwrap、proc／fd3或真实signal。

公开contract只支持loader reload，不推定CLI首次启动、saved trust继承、RPC默认ask、上下文／sessionDir时点或工具沙箱。只读`/usr`不是逐文件运行时闭包资格；安装端点核对不是持续SourceHold，group empty／EOF不是namespace所有后代物理退出证明。Full、controller、来源／角色／初始化／DB及产品gate未资格，T006和正式7/100不变，严格计量前AUTO OFF。

新的独立原生授权要求来自 [AGENTS.md](../../AGENTS.md)：“真实 smoke 为独立显式步骤，需用户明确授权”。本稿仅提供具体可审查材料，不表示授权已取得；现阶段保留守卫false。
