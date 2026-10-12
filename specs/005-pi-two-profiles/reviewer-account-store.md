# Reviewer 累计账号账本的存储边界

这是宿主接线的实现决定，落实跨 profile 累计预算要求，不冻结真实路线、价目或数值上限，也不启用 reviewer。审批许可与会话状态仍由各 profile 的激活实例管理。

受信宿主使用`ReviewerAccountLedger(authority_identity=..., scope_required=True, account_home=None)`绑定已有账户授权并取得唯一累计额度；旧`limits=...`接口只保留独立组件用途，与绑定态互斥。默认account_home来自当前OS账户的passwd记录，不取HOME、XDG、local配置或profile运行根。显式account_home仅供受信构造者和临时测试，不是模型/RPC参数。复用已有RegisteredRoots的账户身份核验和短排他锁，将预算保存在固定`.agentcfg-workspaces/reviewer-budget/`子目录；已有工作区协调记录和预算由不同文件拥有，不合并会话、凭据或许可。

账户锁始终在子账本的 instance_lock 之前取得。每次账本方法都核对账户、协调目录、预算目录身份及固定目录成员，随后调用原 ReviewerLedger 的单文件事务。该门面不返回可绕开核验的底层 ledger。额度收紧沿用原规则；货币变化、额度增加、重置、另建周期没有自动入口。不同路线在同一累计总额内收费，币种不一致拒绝；按路线分项来自原账本的 pricing/binding，不按凭据或其散列创建目录。

绑定态在同一账户短锁内校验authority文件live identity/有效窗口，再执行reserve/claim/commit；price/token上限也必须精确来自该工件，profile不能独立决定。显式update与持久commit共用此锁；commit后的更新不保证该次已提交发送停止。迟到facts只使用已核验持久账本额度，旧price、unknown预留和deny锁保留；`for_settlement()`只重开既有ready账本，不读取当前authority、不初始化或提供新发送权。此组件仍不代替宿主scope/quality/实际模型及factory接线。

显式`scope_required=True`是已验收的私有绑定模式，严格bool且必须同时提供authority_identity；构造在创建预算之前核验既有合法scope表，缺失或损坏不补建。reserve从原request提取session_scope/intent_ref/request_id，claim/commit从已核验ready账本的原持久行提取相同三引用；在同一account排他flock下由私有`_check_scope_binding`校验其存在且session/intent未退役，随后才进入updating/ledger/ready事务。该helper不调用公开ScopeStore、不二次开flock或引入外部回调。scope退役和durable commit共用锁，commit是此路径的线性化点；commit后退役不承诺停止已经提交的发送，unknown请求与预留继续保留。迟到mark_sent/finish/usage和`for_settlement`不要求live scope，也不恢复发送权。

默认`scope_required=False`保留旧独立离线组件兼容，不表示产品可以省略scope核验；未来生产factory必须显式选择True，当前factory尚未接入。新增原子scope模式在safe-error修复前一次默认运行新增34项加关联188项共222项通过；异常渲染窄修后泄漏单例1项及新增模块35项分别通过，222日志作为历史证据保留，未在窄修后重跑关联188项。未知底层异常固定`Conflict("REVIEW_ACCOUNT_INVALID") from None`仅抑制默认traceback链；Python内部`__context__`仍存在，不能序列化原错误链。这些临时账户测试没有执行真实账户、SDK或OS子进程，不替代真实用户意图、产品与跨进程scope竞态证据。

监督者的 protected_roots 必须从已核验的 `store.workspaces.claims.registry.anchor` 自动纳入整个账户协调根，不能仅依赖bootstrap/profile恰好列出它。相同冻结路径交给handshake、文件策略、普通命令和Shell编译。控制根尚未创建时仍保留未来拒绝路径，不把缺失解释为允许创建业务文件；控制根位于挂载范围内而无法表达deny时，命令/Shell准备拒绝，不创建占位。这样覆盖Git父项目包含账户根的场景，非Git登记的重叠检查不是唯一保护。

初始化按以下不可逆顺序执行：

1. 在账户锁内核验/初始化已有协调登记；固定 `reviewer-budget.json` 哨兵与子目录都缺失时才允许首次初始化。只有其中一项存在属于恢复待处理，不能猜测为空。
2. 先原子写入并 fsync preparing 哨兵，再创建私有子目录并 fsync 父目录，初始化空账本。此时不能发送任何请求。
3. 空账本初始化成功并持久化后，写 ready 哨兵，包含账户、协调根及预算目录的 dev/inode/uid，以及账本文件完整 `storage.identity` 六项投影和 SHA-256。该摘要只绑定原账本的非秘密引用、用量和价目，不是用户正文/凭据摘要。ready 返回前的异常可能留下 preparing，也可能已写 ready 而丢失回执；前者拒绝自动初始化，后者只能核对后观察持久状态，不能假定前次成功返回。
4. ready 重新打开要求目录物理身份、账本完整身份/摘要匹配，文件存在且私有。原 ReviewerLedger 新增显式 `create=False`，禁止因 ready 账本缺失而补空文件。有效但已清空的同schema文件、原地修改和同名替换也拒绝。每个方法在同一账户锁内重复核验；身份丢失、未知文件、损坏、链接、权限变化均拒绝自动审批。
5. 账本文件的合法事务会原子替换文件，因此固定初始 inode 不足。每次方法先持久化 updating 哨兵，保留旧绑定；再构造 `ReviewerLedger(create=False)` 并执行方法。构造者可能收紧 limits 写文件，也只能在 updating 之后进行。成功后重新核对私有账本、绑定当前文件身份/摘要，持久化 ready 并 fsync 后才返回。门面重开后的额度核验也走此流程，不能先构造底层账本。
6. 正常方法异常仅在账本完整身份及摘要与旧绑定完全不变时，才可持久化恢复原 ready 并抛出原异常；文件已变或读取未知则保留 updating，返回固定待恢复错误。不得回滚账本、重置、重发或补写成功回执。重启看到 preparing/updating 一律待独立恢复；最终 ready 写入失回执不能返回成功。若 ready 实际已落盘，重开只能观察原账本，其 attempt/send 墓碑继续防重放。

目录0700、普通单链接文件0600，哨兵为封闭有界JSON，不保存秘密、正文或其摘要。首次初始化失败时不自动删除哨兵或目录，也不提供“清理后重试”路径。主机OS账户自身可修改受信控制文件属于既有信任边界；该协议不提供外部签名或抵御同权限管理员抹除全部控制根。

验收使用临时账户与默认网络/进程守卫，覆盖重建控制器仍保留一次attempt、unknown预留、deny意图锁、额度收紧与增加拒绝；准备/ready写入失回执、准备途中中断、子目录/账本丢失或替换、符号/硬链接、重复字段、未知目录成员和不安全模式必须失败。补充 updating 写入在账本修改之前、账本replace后失回执、最终ready的replace前/后失回执，逐项核对没有send许可或清零。现有登记与工作区claim回归须保持通过。真实跨进程崩溃恢复及宿主安装/保护根闭包仍需单独验证；该组件通过不表示默认产品已启用。
