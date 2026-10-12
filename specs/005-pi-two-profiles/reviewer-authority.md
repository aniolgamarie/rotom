# Reviewer 账户级授权来源

账户协议、私有存储及显式CLI已完成默认验收，宿主模型接线继续实现；目前不批准真实路线或费用。共享模型声明提供当前模型身份；独立账户工件提供用户批准的路线、价目和累计额度。profile只选择关闭/启用及已批准的风险类别，不能携带额度、账号根、凭据或审批来源来覆盖该工件。

工件固定在passwd账户的 `.agentcfg-workspaces/reviewer-authority.json`，由自有CLI显式创建或更新，普通工具和项目代码不可读写该控制根。复用RegisteredRoots账户短锁与Tree；白名单仅增加这个精确文件名。读取有界、普通单链接0600、重复键/未知字段/非法数值拒绝。文件丢失或损坏时关闭自动审批，不自动从profile补默认授权，也不清空budget。

封闭版本1记录包含随机authority引用、递增generation、非秘密route声明、独立价目revision、累计limits、input/output token上限、已批准类别、有效时段。route只使用已验证的逻辑provider、原生route、auth_kind/owner、协议、无认证信息的endpoint及remote model ID；由现有部署manifest的main role或显式已声明role选择，比对当前model_configuration。凭据正文、headers、credential_ref、真实账号文件路径与其散列均不属于工件或review输入。

纯协议字段固定为`schema_version=1/authority_ref/generation/route/pricing/limits/token_limits/categories/valid_from/valid_until`，最大16KiB。route包含`logical_provider/native_route/model_id/auth_kind/owner/api/base_url`；当前公开协议仅`openai-completions/openai-responses/openai-codex-responses`，API-key仅前两项。OAuth必须先取得公开实际model descriptor的endpoint与API才能形成可用授权，不能从config=null猜测。categories为排序唯一的`file-read/file-write/shell`子集，这些只是进一步限制review范围，不能放宽硬策略、角色或human门。有效时段使用精确整数Unix秒，左闭右开；未知字段、bool冒充int、重复键、未核验日期、含认证信息URL均拒绝。

price沿用原ledger整数货币十亿分之一单位，包含currency、input/output/cache-read/cache-write每百万token上界、非秘密官方来源与核对日期；不得把SDK默认零cost或未知价目转换成免费。price identity、authority identity仅覆盖非秘密封闭字段。费用是provider自报usage与固定价目的估计，不承诺真实账单上限；实际未知用量继续占预留。数值与有效期须在授权/评测前固定，当前没有默认真实价格或额度。

创建与更新只改授权工件，不删除/换根/另建budget周期。更新要求expected旧identity和generation+1，货币不变、累计calls/cost额度相同或更低；增加、换币、reset另需独立行政流程，本版拒绝。route/price/类别/时段更新使authority identity变化，所有未消费旧许可和review候选必须失效，旧账本事实、deny意图锁、unknown预留和旧pricing继续保留。写入失回执只读对账，不自动重复提交或增加generation。

显式CLI更新代表新的用户授权动作，可调整token上限、类别、route、price与有效期；模型工具和reviewer没有该写能力。每次变更都需新的配置身份及对应质量冻结匹配，未通过新资格检查仍不能发送。累计费用/次数上限只许相同或降低，token或价目提高只会提高后续保守预留，不增加累计可用余额；旧请求按原记录价目记账。存储可接受声明形状，不凭source URL、owner字符串或工件存在宣称价目真实、插件受信或模型合格。

文件存储的live identity同时绑定非秘密canonical文档、账户/协调目录物理身份与该文件完整stat身份，替换成相同字节也使旧候选失效；price identity只绑定价目，不因generation变动重算历史费用。首次创建generation必须为1；若授权已丢失而budget目录或其sentinel已存在，本版创建拒绝并报告待恢复，不借“新建授权”开启另一周期。读取及更新都不构造账本；额度收紧由后续启用边界从新授权传给原账本。纯协议校验和私有文件存储是组件层，未接线前不把工件当实际发送许可。

关闭态在选择检查前不读取授权、构造账户账本、解析凭据、启动SDK/进程或调用模型。启用态先读取并核验工件，再与当前部署的非秘密route/模型逐项比对，才向ReviewerAccountLedger提供单一limits/currency来源。每次begin、发送边界、issue、consume复核live authority identity、时段及当前scope/config/policy；不得缓存授权文件而把外部收紧遗漏。发送提交后可能已产生费用，更新/取消不将历史请求归零，也不宣称即时停止已运行进程。

CLI只管理用户提供的非秘密授权工件，不加载共享配置或认证。后续可信宿主适配器从共享配置选择已声明模型，认证只经官方公开ModelRuntime/API解析并留在私有传输边界。模型输出只提供绑定的候选决定，不能创建/更新该工件、选择source或调用issue。真实质量评测仍须单独获得本会话执行授权，文件格式/代码实现不等于Codex可以调用真实模型。

验收先用临时账户和假model manifest验证：不同profile读取同一authority/budget、没有profile限额覆写、未知/缺失price不发送、任何credential字段拒绝、价目精确整数、错误模型/endpoint/owner/config拒绝、更新不清账本/不增加额度、旧许可及迟到候选失效、off/Base零构造/调用。跨进程变更与回执丢失单列OS证据，SDK/真实价格/账号/质量不由这些默认检查代替。

已完成组件证据：纯协议102项通过并稳定独立审查，私有存储及其协议/账户/registry/workspace_overlap五模块257项通过，其中存储47个变体。覆盖精确白名单、私有权限/no-follow/单链接、有界解析、账户/HOME/XDG边界、gen+1与expected-live-identity、同字节替换失效、registry及授权文件写入前/后失回执、两控制器同expected仅一写入、budget残留拒新建授权、schema2真实临时claims与未来生效工件的被动共存。三存储来源及两未变协议来源完成稳定审查，无该组件新增P1/P2；私有记录`risk-reviewer-authority-store/`。宿主真实模型路由、额度授权或Full gate仍未通过；off/Base工厂零初始化、current-model与issue/consume接线、跨进程授权更新证据仍待实现。

显式管理入口为`./agentcfg pi-reviewer-authority show|create|update`，无机器/local/profile/账户根选择器，不调用配置解析器、秘密存储或SDK。`show --format json`取得当前非秘密live identity；`create --document PATH`读取用户自有、普通单链接0600、最多16KiB的JSON；`update --document PATH --expected-identity HEX64`使用观察身份作条件更新。JSON重复键/秘密字段、FIFO/链接/权限/属主/来源替换或expected无效在账户查询前拒绝；授权失回执只返回固定unconfirmed，不重试。human输出使用精确九位小数货币金额及更新所需当前标识。创建工件不启用自动审批或发送模型请求，不支持删除/reset/增加累计额度。CLI加原CLI和存储回归190项通过；human格式窄修后已有对应检查1项通过，两个集合分别记录，稳定三来源完成独立审查，私有证据`risk-reviewer-authority-cli/`。

模型接线使用已有公开`getModel/getError/checkRuntime/describe`与自有完整Model私有基线比较；不复制/散列headers或token。API-key声明包含api/baseUrl与所选模型能力，可逐项核对；OAuth的config/credential_ref为null，endpoint/API不能从声明推断。必须从受信公开SDK实际描述取得并与用户明确授权匹配，未解析时不发送。纯匹配器已完成69项默认测试；与协议及模型配置回归合计217项通过，稳定两来源独立审查无P1/P2，证据`risk-reviewer-route/`。它只接安全八字段投影与完整非秘密configuration identity，显式选择main或已声明role，逐项核对允许模型、provider/auth owner、route和token能力；不构造SDK、解析认证或签许可。真实私有适配器、时段与live authority/质量冻结复核仍须后续实现。

账户账本新增受信绑定入口`ReviewerAccountLedger(authority_identity=..., now=...)`，与旧离线组件的`limits=...`接口互斥。绑定态在同一账户短锁内读取实际工件、校验live identity/有效窗口并取得唯一累计limits，再执行reserve、claim或commit；reserve还要求原账本严格验证后的price/token上限与工件完全一致。复用锁内snapshot函数，不嵌套取得第二把账户锁。显式授权更新与持久发送提交串行化；成功commit代表一次发送权已持久提交，随后发生的更新不保证这次已提交发送停止。实际HTTP边界还须复核scope/config/quality，不能持短锁等待网络。

reviewer许可issue/consume新增受信live qualifier入口，缺失默认拒绝，只有exact True放行；消费失败会永久烧掉许可。默认实际临时AuthorityStore组合证明：原context不变时授权更新、相同字节替换、丢失、损坏、过期、权限错误和账户busy均拒绝，不把已缓存的文件identity当live授权；human/规则路径没有该读取。真实账户账本的unknown行在Admission→account→ledger顺序下仍保留一次提交与320预留。20组合加40hook和36账户授权测试共96项通过，独立审查无P1/P2；证据`risk-reviewer-authority-permit/`。真实用户scope、SDK实际模型/质量工件与factory仍未接线。

绑定对象记录mark_sent/finish/usage时使用已核验账本中保存的额度，允许收紧后记录旧请求，保留原价目、deny锁、unknown预留。重启后可由可信观察者使用`ReviewerAccountLedger.for_settlement()`只重开既有ready账本：构造不读当前authority、不写入或初始化，永远拒绝reserve/claim/commit；授权过期、丢失或损坏不能让已发送事实丢失。missing/updating或身份不明仍待恢复，不用该入口修复/清空。最终默认账户组合36项及原账户/存储回归共136项通过，三稳定来源独立审查无P1/P2，私有证据`risk-reviewer-account-authority/`。早期239项属于加入只对账入口前的受影响范围，单独保留；它们均不证明跨进程授权更新、断电、官方SDK或宿主factory已通过。
