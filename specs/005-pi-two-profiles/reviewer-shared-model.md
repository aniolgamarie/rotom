# Reviewer 与共享模型的保真接线

当前共享Pi main声明选择`deepseek_flash_openai`，配置包含真实名称、reasoning=true、text/image能力、contextWindow=1000000、maxTokens=384000、DeepSeek兼容参数及thinkingLevelMap。这里描述仓库声明，不宣称已经由实际账号发现或校验模型可用性。现有公开describe与完整Model私有基线是可信选择入口，不能把凭据、headers或credential_ref复制到模型投影、身份或日志。

原合成reviewer传输构造name=id、reasoning=false、text-only和裁到reviewer输出上限的SDK Model，worker模型协议及wire只支持该简化completions模型。官方SDK会依endpoint/compat决定DeepSeek thinking参数；直接把这套合成构造与共享模型身份等同会丢失原生能力，并可能把实际请求拒绝。后续新增bound模式保留完整Model，原分支作为独立legacy路径保留。API/owner声明匹配不等于实际wire支持，authority协议允许的Responses/OAuth声明也不表示当前T已支持这些路径。原问题证据固定12个源码SHA，见私有记录中的`pi-risk-actual-model-transport-seam.md/json`。

root选择保留完整安全base Model描述，再显式绑定reviewer的固定请求策略。首次接线只实现公开API-key/completions；不支持的API、OAuth或compat在构造账本、解析认证或建立SDK进程前报告不支持，不换源或猜endpoint。这样扩展其他API/provider时增加明确的契约与探针，不扩大既有通用validator。

新的纯准备协议`shared-model.ts`已通过104项默认纯Node测试及稳定独立审查：base_model保留公开name/reasoning/input/cost/contextWindow/maxTokens/thinkingLevelMap/native compat；sdk_model只追加固定reviewer请求所需的四个兼容开关，保留这些原字段。实际Model的maxTokens是能力，authority的output_tokens是本次请求上限，二者分别验证。单条text输入、reasoning off、零retry、temperature=0、stream/usage及input/output上限形成独立request_policy；关闭推理通过固定请求参数表达，不把Model.reasoning改成false。模型身份覆盖安全base/SDK描述、声明route/configuration identity和此请求策略，质量冻结必须绑定这一reviewer变体。SDK cost字段仅作为原公开描述，不作为费用授权；收费仍来自独立账户price。

准备协议本身不执行request_policy。纯SDK契约编译器`shared-sdk-contract.ts`已通过72项默认纯Node测试和稳定独立审查，在跨边界后重新计算并比较全部prepared字段，输出固定SDK options与明确wire shape。首次支持non-reasoning模型的普通文本请求，以及原模型显式thinkingFormat=deepseek、reasoning=true且off映射不为null的disabled请求；不能依endpoint检测猜格式，也不能把off=null时省略参数误记为明确关闭。实际body还须在最终发送边界精确核验；上述纯编译证据不是官方SDK执行证据。

独立的`shared-request-wire.ts`最终请求校验组件现已验收：根据完整重新编译的prepared/route/configuration绑定选择分支；普通文本复用原闭合validator，DeepSeek仅额外接受根级精确`thinking:{type:"disabled"}`。专用有界JSON读取保留每个数字的原词法，核验后只删除thinking再交原validator；不会把浮点/指数/舍入输入变成获准整数，也不删除工具、未知字段或变更的绑定。完整URL按固定SDK的baseURL拼接规则生成，不合并多个尾斜杠。新增63项、原request98项和contract72项在一次默认运行中共233项通过，独立稳定审查无剩余P1/P2；原validator拒绝合法DeepSeek体的行为红单独保留。源码、原静态SDK快照及报告归档在`risk-shared-request-wire`。组件原独立验收没有调用SDK或HTTP；后续T接线证据分别记录。

Worker的bound模式已通过174项默认组合检查（新增55加相关119），独立稳定审查无剩余P1/P2。构造时编译全部packet再复制冻结；WorkerData的模型身份和run消息中的packet在SDK导入前重新核验。实际Model保留name/reasoning/input/native caps/compat/map，options单独要求请求cap和reasoning off；删除或篡改packet/marker不会自动回退到legacy。自有Node Worker只加载临时fake SDK，没有执行官方SDK。归档为 `risk-shared-sdk-worker`。

输入预算还有独立的发送前资格要求。固定PiAI公开的 `estimateTextTokens` 使用字符数除以4，图片使用固定估算，`estimateContextTokens` 和4096余量只帮助裁减输出；它们没有精确或保守输入上界保证。`maxTokens` 限制输出，response usage出现得太晚，不能证明发送前输入在authority的 `input_tokens` 内。计量必须覆盖system和user两段prompt，不能把字节数当成真实token数。静态13来源报告及其原字节归档在 `risk-shared-input-bound`，其中旧T/W是历史快照。[DeepSeek官方token文档](https://api-docs.deepseek.com/quick_start/token_usage/)也将离线demo标为估算，实际计数以response usage为准；[Chat Completions接口](https://api-docs.deepseek.com/api/create-chat-completion/)的usage属于响应字段。已查公共合同未证明demo与当前 `deepseek-flash` 的服务端预处理和完整消息计量一致，不能据此启用strict输入预算。具体声明、源码及官方链接在 `risk-shared-input-method`。root已咨询是否保留严格规则或显式改成估算政策；2026-10-06 用户明确选择保留严格上限，计量未验证前关闭自动审核，继续完成其他接线。不接受估算政策，不把关闭态算成 Full 启用态完成。

共享T现已要求私有同步 `inputQualification`：可信调用者对完整模型、request_policy、两段prompt和配置/模型身份给出严格true，才允许后续SDK调用；缺失、非true、异常或Promise均在normalizeContext/streamSimple前停止，零发送。回调仅取得私有复制，不取得key或headers，且通过后再次核验取消/配置/截止状态。此组件不认证回调来源；真实产品还需固定并验收提供者相符的输入计量方法。自有fake资格回调不能作为实际模型预算证明，当前尚无合格真实计量入口。

T的完整接线已通过一次228项默认组合检查（新增57、原T53、shared wire63、shared Worker55），独立稳定审查无剩余P1/P2；它关联prepared身份、route、binding和请求cap，保留完整Model并使用已验收final wire分支。旧Model重建丢字段的真实行为红单独保留；两项冻结fixture错误另记，不当作生产缺陷红。取消、双时钟、usage、raw metadata、一次fetch和固定错误沿用原行为。归档为 `risk-shared-transport`；各阶段测试数属于各次运行，不求和冒充一次全量验收。

独立进程桥现已通过一次271项默认组合检查（新增29加相关242），独立三文件稳定审查无剩余P1/P2。可信launcher以固定额外argv绑定模型identity；父、子run边界重新编译完整packet并检查Model/options，再传给Worker。marker和packet缺失/漂移不能自行选择legacy；其他frames、限额、raw ACK背压和终止exact true语义未扩大。它的默认测试用paired fake FD；marker不是来源签名。归档为 `risk-shared-sdk-process`。

后续自有fake SDK进程探针已实际执行八场景并由父检查器和独立工件复核通过，exit0、探针stdout72字节/stderr0。legacy allow与共享DeepSeek/text allow各一个真实自有child和Worker、一次fake send，共三次；Base/off/hard/human和共享缺input资格均零child/send。三份Worker观测与原结果副本一致：完整安全Model的native maxTokens384000及request cap4096/off保留，DeepSeek请求thinking disabled，外层合成环境key/environmentData未进入Worker。固定13模块、三fixture、完整bundle与前后工作清单核验通过；默认父检查器另为49项fake测试，不能与八场景混算。归档 `risk-shared-self-process-review01`。观测文件只保存模型/options与选定wire字段，没有保存完整body transcript；完整synthetic body由固定替身构造并走T校验。替身没有加载官方SDK，child close不证明整个namespace终止，scope_termination仍unknown，假输入资格不签真实预算或产品gate。

上述离线和自有fake证据不证明调用者可信或真实输入预算。用户已明确授权官方SDK共享组合review02，11场景实际观察到8项各一次child/send、3项零child/零send；固定来源、闭合结果和稳定独立审查范围内通过，见 [native-reviewer-sdk-process-probe.md](native-reviewer-sdk-process-probe.md)。confirmed-intent 的异步13场景首轮暴露父post清单遗漏；修复、默认97及稳定复核后，按同边界授权在新review02重跑13场景，完整post清单及计数通过且稳定工件复核无开放P1/P2。首轮及P2保留为历史观察，见 [native-intent-scope-probe.md](native-intent-scope-probe.md)。默认测试与SDK场景各自记录，不相加；严格计量尚未取得资格，实际自动审核继续关闭，Full产品gate未通过。

可选发送提交gate的当前窄增量已通过346项一次默认组合，另见[reviewer-send-boundary.md](reviewer-send-boundary.md)。它区分提交尝试/成功回执/本地平台入口，并在提交之后零入口时保持usage unknown；账户ticket/RPC未组合。来源改变使共享SDK11 review01失效；review02已授权执行且完成上述范围内验收，仍不传gate、不证明持久提交。intent SDK13的scope及MJS来源未变，父检查器的post清单修复需要新目录和新plan，用户的同边界必要修复重跑授权继续适用。

既有九case Worker仅覆盖其旧字节，新进程组合旧review02已因T/W/process变化失效；旧十case意图review01也因自有scope source pin改变失效。它们保留历史、不执行，不以不可变SDK静态证据替代新组合验证。私有持久scope接线的服务端已另完成130项默认组合，nonce退役145项与JS适配属于独立阶段，见 [reviewer-private-scope-rpc.md](reviewer-private-scope-rpc.md)；这些默认组件不表示Host factory或产品Full通过。正式任务仍为7/100。

## 后续组合与严格上限审查（2026-10-06）

原ticket/账户结算252项及共享Model/进程桥/父侧gate202项已分别完成默认组合与稳定审查，详见[reviewer-send-boundary.md](reviewer-send-boundary.md)。后者只新增21项测试、不改生产源码，真实自有进程及旧SDK证据不自动覆盖它；child fetch frame计数与父侧平台send入口计数分别断言。上述旧段落的“账户ticket/RPC未组合”保留其历史阶段边界；当前已闭合Python内部原ticket/账本归并，实际Node/Python私有RPC和可信factory仍待完成。

[DeepSeek List Models文档](https://api-docs.deepseek.com/api/list-models/)的示例给出deepseek-flash总context容量1048576，定义包含输入和输出；[Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)描述context限制和响应usage。从这些资料只能推导实际在context内处理请求的输入不超过总容量，不能推导所有尝试请求的实际计费输入上界。[价格说明](https://api-docs.deepseek.com/quick_start/pricing/)按输入和输出计费，已查原始文档没有保证超限prompt在处理前零计费拒绝。这个有限结论不把离线tokenizer估算升级为严格证明。

本地共享声明context_window=1000000、native max_output_tokens=384000保持不变；这两个值比文档示例1048576/393216小，本轮不把保守声明差异当成必须修改的错误。现有request_policy也不能表达超过本地contextWindow的input_tokens。报告只读公开metadata/官方资料，没有读取凭据、调用账号API或模型；直接页面读取超时，来源证据来自官方页面搜索摘录。严格发送前上界仍未验证，inputQualification不启用；2026-10-06 用户已选择保留严格上限，计量未验证前关闭自动审核，其他实现继续。归档`risk-context-cap-feasibility/`不构成运行测试通过、费用授权或产品gate。
