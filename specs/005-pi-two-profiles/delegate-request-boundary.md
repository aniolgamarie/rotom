# 委派请求的副作用前校验

状态：2026-10-06该有界输入修复已验收。最终六模块241项默认检查及三个稳定来源的独立审查通过，证据归档`model-delegate-arguments/`。对应T058/T060的一项输入边界增量，不代表US4完成。旧三个核心模块在正常属主、原隔离守卫下通过34项；外层受限UID的26通过/8环境失败另留原始记录，不能把环境失败算通过。

## 现有权威与缺口

`model_delegate.DelegationRuns`拥有持久run请求、事件和收据，启动权继续来自原manager/supervisor，没有第二个调度队列。当前`DelegateController.prepare`先闭合顶层字段，但部分可选字段直到持久意图、分配租约后的request-v2校验才拒绝。异常可以撤销尚未启动的分配，却不会自动删除已登记的意图；不能为输入校验增加自动清理或恢复猜测。此次改为在所有路径、manifest、context、意图和分配动作之前拒绝坏输入。

旧`check_resume`要求已终止及资源回收证明，随后创建新run/attempt/lease。它是既有兼容行为，与现代US4要求的同一逻辑run继续不同。本增量不改变该事务或以旧resume宣称同run能力；现代后端需另核对公开会话接口、稳定native identity、每轮执行及未知恢复。

## 已决定接口与不变量

`model_delegate.capture_delegate_arguments(value)`返回独立原生字典；`DelegateController.prepare`首先调用，随后只使用这个副本。此函数不检查用户授权、不访问文件系统、不发现账号或插件、不形成运行身份、摘要、许可、预算预留或租约。原principal、路线、策略、根和实际运行绑定仍由既有控制层验证。

输入保留现有八个必填字段：idempotency_key、backend、mode、preset、task、cwd、model、timeout_seconds。可选字段仅context_artifact、feedback_required、allow_workspace_write、worktree_root、continuation_of。未知字段拒绝，approved、role、task_id、权限等模型自报内容不能取得授权。

只接受精确原生dict、str、int、bool与规定位置的None。先界定键数量、键类型与字符串长度，禁止子类或自定义转换、迭代、深拷贝钩子；model单独校验两个字段并复制。UTF-8错误和坏输入只产生固定安全错误。任务正文原样保留，不strip后写回、不填可选缺省、不删显式None/False、不规范化路径或更改模型名，保持所有合法旧请求及arguments_digest的表示。

具体边界沿用原request-v2：backend/mode/preset的既有枚举；provider_id及可选context/continuation引用的ASCII ID格式与200字符上限；idempotency_key保留1至200字符且支持Unicode，禁止NUL。task须非空且UTF-8不超过65536字节；cwd/model_id/worktree_root的字符串同样有界且非空、无NUL，cwd须绝对路径但不resolve/stat。worktree_root允许None，实际路径及写入范围仍原策略层处理。timeout须精确int、范围1至2**53-1，配置仍决定实际最大值；两个flag若存在必须精确bool。未定义的容器、浮点、隐式类型转换与字段全部拒绝。

## 默认验收

先用原临时DelegateController、ExecutionStore和Tree取得实际坏可选字段的行为红例：feedback_required=None、context_artifact=0、continuation_of=0等应在manifest/context/allocate之前失败，零意图、零租约、零spawn；同key的后续合法请求正常准备、同请求仍幂等。模块缺失或API不存在不能替代这个副作用反例。

纯接口检查覆盖合法旧缺省与显式None/False表示、所有类型/枚举/容量边界、Unicode、未知自授权字段、拒绝时钩子零调用和副本隔离。最终一次相关检查使用test_model_delegate_arguments、contract、lifecycle、backends、test_pi_delegate和model_delegate_cli六模块；保留临时HOME、禁网、假进程及合成模型。这里只运行自有代码与进程内临时文件，不启动Pi/Codex或原生SDK，不使用真实账号。写入结束后针对稳定diff独立审查，保留红绿日志、源码SHA与未验范围。

US4整体仍须现代两宿主入口、Pi/Codex公开后端、同run消息/继续、跨重启预算、真实停止/恢复与Q4/T066矩阵。现有capabilities诊断仅从manifest及入口存在性合成，native_load/execution为not-run、authentication为unknown，不能当真实后端证明。提供者替换继续显式选择并绑定运行身份；不能继承旧grant或重派未知副作用。

## 当前验收事实

修前实际八个失败反例中，三个确认非法feedback_required=None、context_artifact=0、continuation_of=0已经留下intent；另五个确认进入manifest/IO校验。修后同key合法准备仍可用，坏输入在manifest/context/path/allocate前固定失败，零意图、零租约、零spawn。新增185个用例连同五个相关旧模块最终一次241 passed（2.05秒）；先前240项与独立34项保留为历史运行，不相加。task正文保持原合法文本，包括NUL，不新作文本清洗或据此授权；NUL禁用限于上述路径、模型和幂等键字段。

root核对保存before的两源diff，而非把HEAD中他人既有identify_git修改算入本增量。三个当前SHA与最终测试及独立scout审查一致，无本范围剩余P1/P2；本次没有改schema、原fixture/guard、锁、事务、恢复或旧resume。executor实际gpt-6.1-sol/medium，独立scout实际gpt-6-luna/high，真实SDK/host/账号/模型未运行。
