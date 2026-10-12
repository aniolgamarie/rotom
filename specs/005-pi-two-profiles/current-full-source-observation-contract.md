# 从实际 deployed current 导出的 Full 来源观察

2026-10-09 Root。前述六源调查确认 installed Full capture 只有 caller root/piece/context API，未见 actual Workspace current producer。Root另核 PiBackend.status 直接接 pi_runtime_packages.status；owner context会校验Full材料和binding，但不排除合法sealed candidate。此包补唯一自有只读数据producer；不是FullSourceView、SourceHold、issuer/principal/角色或初始化资格，无launcher/SDK/持久IO。

## 固定入口与实际来源

新增 src/agentcfg/pi_current_full_source.py，observe_current_full_source(workspace) 只接实际 exact Workspace 且exact PiAdapter，不接 root/piece/current/seed/context/callback/资格参数。源码绑定原Workspace getters和PiBackend.root等自有方法，参数是仓库对象而非model DTO；公开制造Workspace仍不获得authority。先核Pi/profile=pi-full，否则零Full可选导入/Tree/source-latch/账号。不调用resolved模型字段/secret_store/provider认证/新版repository lock，不把render candidate当current。

对同一Workspace实际instance的既有private .agentcfg-instance.json先只读有界并比当前state_root/binding固定json_bytes，再取得source_latch(shared=True,create=False)，全程没有mkdir/新anchor；该SH只持当前观察，不持续移交。marker最多其expected bytes，并以600/单link/原Tree核读；missing/错binding先拒绝。后续以原state Tree固定只读deployment.json、pending.json存在即拒绝（不读body）。deployment cap 8MiB，在分配/解析前检查，缺current/错binding拒绝；复用原deployment.read_state校验的own内存reader只提供这次原Tree读出的deployment bytes及mode，不重开无界文件、不复制另一套saved-state schema。

必须用 current['launch'] 的 lock_identity 和显式runtime_identity（modern无fallback）两个hex64；current['generation']只作本地私有末核，不返回或散列。由原PiBackend.root(workspace,runtime_identity)推导runtime root，不能由current里的任意path/repository/argv/env选择。不读current launch environment/machine/secret正文，不运行prepare_runtime/preflight。对root持原Tree、保存directory dev/ino/mode/uid/gid，读固定receipt至多16MiB，复用原_validated_receipt(root,identity)并核它回的raw与本Tree第一次原raw完全一致；identity/lock/platform=linux-x86_64/context/binding/piece必须相符。完整receipt原算法负责seal/inventory，不用ready布尔跳过。缺/损坏root失败无来源结果。

由上述actual receipt中的原piece/toolchains/binding调用原 validate_installed_owner_origin 获得完整非秘密metadata，强制selected pi-full state恰为current，candidate/accepted拒绝（它们可作为已安装材料验证，不用于此current producer）。来源锁和schema仍由原validators核，不编造verified_host_versions，不从repo重选。再原 capture_installed_full_source(root,piece,actualcontext) 取得完整detached观察，仅返回其原schema/profile/lock/runtime/root/markers/entries数据；不添加generation/current文件digest/secret/token/hash/cap字段。

最后在sourceSH仍持有时，用原stateTree再 bounded read_state 核current的binding/generation/launch lock/runtime未变，pending仍无；核原runtime Tree directory物理对象仍dev/ino/mode/uid/gid一致、receipt原bytes保持，并重读固定namedroot的目录identity防同名替换；最后source_latch本来端点检查仍执行。允许目录size/nlink/time及activity/heartbeat/预算日志变化，不以它们自我失效。结果离开context时Tree与SH已关闭，明确点时观察而非连续hold/实际加载/身份认证。

错误为固定 PI_CURRENT_FULL_SOURCE_INVALID /exit4，包含bad参数绑定和外来异常链抑制，不回显Workspace/private generation/路径/原JSON/secret。source/Tree失败不增加来源result或资格；unknown关闭不装成功。捕获原方法/receiver不能对任意同进程恶意Python或TCB外同UID修改作绝对保证。实际并发/handoff另验。

## 验收与ownership

executor唯一新增 module和 tests/test_pi_current_full_source.py，证据 current-full-source-observation-implementation-review01。你不是唯一作者，不回退他人改动。不得改既有source_latch/Workspace/PiBackend/validators/read_state/CLI/manifest/上游/OMP/state/tasks/docs。Source getters/validators参数与资源生命周期不确定或需要改既有代码先Root。

默认测试复用 test_pi_owner_origin._install 真实自有temp pipeline（fake installer/合成不执行Node与角色，仍非actual Full）+实际Workspace/PiAdapter、真实Tree/source latch、原read_state/capture/owner validators；构造正确受管 deployment 文件、既有marker/anchor，不能以validator=True fake形成positive来源。可复用旧fixture私有test helper但不修改；记录fixture的synthetic来源与无实际资格。只在自有/tmp HOME等原conftest guards下，无网络/Popen/SDK/Node实际角色。/data不安全祖先正控要真实owner require_escalated及fresh/tmp basetemp，不放宽Tree保护。只固定pytest新模块。

有意义RED->GREEN覆盖实际current->原root/piece/context链、Base零可选IO、错binding/missing/pending/candidate/accepted/不显式runtime/私密generation变化/末核runtime同名替换/错receipt与原raw/ sourceEX在场拒绝，合法mutable目录metadata/活动观测变化不自我失效；近cap预分配与超cap拒绝；不读secret_store/auth/model、不加载新repo锁；errors/repr输出不含私密sentinel，current generation与其hash不进入result。保存完整run起止/exitJSON/日志，稳定diff/pins/report STOP后Root独立review。两有效修复无解升级，子代理不再派生。正式8/100、AUTO OFF，未接actual issuer/Full/SourceHold/角色。

## Root 可行性修订（替代上述两处）

独立审查发现 _validated_receipt 原本无cap重读并inventory无界；先完成 runtime-installed-validation-bounds-contract.md，保持已有source/receipt validator算法和fixed Source API不改写为验证True。source observer须依赖该新默认边界，原有“不能改validator”指本observer包ownership，不阻止Root为独立证据先冻结另一修复包。

selection允许 current 或 accepted，candidate仍拒绝；accepted必须由原validate_selection_data和原accepted-binding digest全验。actual current来自受管deployment原指针/实例binding/推导的final runtime root以及末核，不来自selection state；accepted数据不授予激活或SourceHold/principal。数据观察与真正来源资格继续分开。新增observer无任何grant/issuer或实际加载证明。

## Root 原saved-state校验与隐私边界

原read_state会在当次私有有界内存中解析完整保存state/launch并验证schema；这是复用原校验所需，不能跳过未知字段或改成局部宽松schema。上述“不读environment/machine/secret正文”指observer不选择/使用这些字段发现运行包、认证/模型/账户、执行或产生公开身份输出；原schema校验可处理其中已保存literal和secret引用，不调用secret_store、不读取真实认证文件或刷新。完整state/rawbytes/私密generation及其hash不返回、不日志/摘要/通用异常。固定root来源仍只用当前launch的两个非秘密锁/runtime ID和原backend.root。

## Root 原validator实际能力与自有消费层

read_state原校验封闭顶层并检查native credential guards，不宣称它存在完整launch schema。新observer仍复用原完整函数的实际行为，generation只exact str本地比较，无新hex策略。observer自己消费的current exact dict keys={generation,binding,launch,items}；launch exact dict必含lock_identity/runtime_identity，允许字段仅原runtime.record的argv,lock_identity,runtime_identity,shared_files,preflight,runtime_guards,machine,adapter_binding,environment。未知current/launch键拒绝；其它未消费launch字段及items/previous guards沿原校验，不复制新执行schema、不作为完整配置/执行资格。marker原bytes/namedinstance末核属于本包，held/named目录仅dev/ino/mode/uid/gid，不以size/nlink/time拒绝自有活动变化。
