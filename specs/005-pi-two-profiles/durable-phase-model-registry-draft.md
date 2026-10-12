# phase Models 工厂接线草稿

此稿保存主代理的后续接线决定，尚未冻结完整内部接口，不能据此开始修改 registry／provider。独立 phase Task 组件已通过默认验收，固定 phase Reader 设计已复审；它们都没有证明实际 Harness／全部模型路径资格。

计划新增 `createDurableReadonlyPhaseModelRegistry`，使用与已有 Models 工厂相同的七个配置字段和 `{registry, models, check, close}` 输出形状。新入口显式选择 phase 路线，旧六字段无 Models 工厂和旧 hook Models 工厂保留原含义；不新增客户端可控的 mode／token／snapshot 参数，不热换旧实例。新路线的 sourceIdentity／registryIdentity 必须描述实际选定 phase task／Reader 及源码，不能把旧 registry 身份原样贴到新路线。

原 readonly registry 仍仅安装自有 RootTask 与两个工具；公开配置选用新的 Reader 来替代 generation／compaction 的 task 查询结果。不尝试在原 registry 安装重复 builtin 名称，不 patch builtin 或 SDK。内部 readonly execute 逻辑需在新构造期捕获实际 front snapshot，所有原 ToolExecutionApi.registry 检查核该引用；原 base snapshot 的完整来源另核，保留原 api／Context／参数。

准备复用共同的内部 readonly 验证与 Models 门面，避免复制一套授权／账本算法。新分支不安装用于身份登记的旧 beforeRequest／beforeCompact hooks，Models 用唯一私有 phase bridge；原 task 自带 hooks 仍原样转发。如何把 front snapshot 和最后纯源核交给共同内部构造器，仍需冻结最小私有接口。

检查调用图必须明确分层。原 base 的完整检查只调用原 base 方法，不能调用 front 方法；共同的 origin 只做纯来源核验，不能递归执行 reader.check。phase verify 核原外部当前权限及随后纯来源，不调用其 Reader 或 phase.check。Reader verify 可进入工厂的内部来源检查，内部来源检查可核 phase.check，但该 phase verify 不再回到 Reader。导出的完整 check 按顺序调用内部检查与 Reader 检查；同步外来重入必须固定拒绝，不能用允许任意重入的标志绕过。

phase 构造期可以调用其初始 verify，但在完整工厂 ready 前不得进入原 phase handler。若某个构造回调从 defineTask 得到 token 并提前执行，必须零原 handler／零模型入口，最终构造也不能忽略已关闭的 phase 组件。完整工厂返回前核原输入／SDK 选定方法／两 task／Root／extension／工具／Models／store／budget，再发布 ready。

Models bridge 门面在原 take／check 前做完整来源核；原 phase bridge 会读取 Context 的公开 getter，故其返回后还必须做覆盖 readonly、Models、store 和原配置的最后纯核，再把 identity／true 交给 provider。只在 bridge 前核一次会留下 Context getter 改变 RootTask／control／模型来源的窗口。最后纯核不得再次执行 getter、snapshot、verifyCurrent 或其他外来回调；没有这项保证，不能签最后模型入口资格。

普通 signal 取消、旧 identity、重复消费和错误 operation 保持 phase 的局部范围，不因这些拒绝把其他合法任务一并关闭。结构／来源完整性失败导致 phase 永久关闭后，后续所有保护入口必须失败并关闭对应工厂资格。具体错误分层仍需与已有 provider 的固定错误边界核对，不靠捕获任意异常就全局关闭。

close 只撤销自有新的准入与选择资格，不冒充 Harness seal、物理进程终止或 owner 释放。已经发生的结果仍可沿原 factsOrigin 核原 collector／recordResult／settle 并有限结算；不重新调用活性 check 授权，不恢复成功发布，不退款未知占用。ledger prepare→sending→result→settled、发送恰一次和 unknown 禁止该任务后续付费发送的语义不变。

完整默认组合至少要覆盖真实 front API 引用、原两 token 选择、初次／重试／恢复／压缩的合成调用、同 signal 顺序 lease、跨任务局部取消、最后 Context getter／verify／snapshot 回调改源后零底层入口、提前 phase、关闭后迟到事实与无新权限、source／registry 身份不混用。实际公开 SDK 全路径合成探针需另准备稳定材料与单独授权；此草稿不提供授权或默认通过证据。owner／业务根／真实模型／严格计量及 Full 仍开放。
