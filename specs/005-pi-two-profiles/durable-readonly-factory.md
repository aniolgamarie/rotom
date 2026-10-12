# Durable 只读 registry 有限工厂设计

状态：有限工厂实现已完成，当前140项守卫默认测试、root全文关键审查及独立稳定增量复审通过；仅验收自有替身中的调用与数据边界。依赖[公开registry及原始输入接缝](durable-readonly-registry.md)的固定来源，不运行SDK、不接真实文件IO。任务授权控制面、owner、RootTask正文及真实受限backend分别保持未资格；没有control时不提供可执行降级路线。

## 工厂与受信输入

`createDurableReadonlyRegistry({durable, rootTask, control, verifyCurrent, sourceIdentity, registryIdentity})`仅返回冻结的`{registry, check(), close()}`。registry供受信Harness工厂使用，不能交给业务客户端做install/uninstall。模块不静态导入SDK；调用方必须显式注入固定公开createRegistry、defineTool、defineExtension、AssistantEntry和自有RootTask token。没有账号、Models、scheduler、Shell、业务写入或动态插件发现。

sourceIdentity/registryIdentity是受信控制面提供的64位小写SHA标识，不由模型参数补齐。verifyCurrent必须同步返回字面true；Promise/未知/异常/false均失败关闭。捕获原公开方法及receiver，检查漂移；只能冻结自有结构，不能冻结或修改SDK snapshot/内部数组/原builtin Task。关闭或来源/registry漂移永久封闭该工厂，不在检查时重新安装或修复。

同步检查误返回普通原生Promise时仍立即拒绝，并以捕获的原then附两个只返回undefined的handler，观察其原拒绝；不读取该对象的own then或未知thenable的getter，不等待Promise结果授准。观察限定同一捕获realm、已核原prototype/constructor/species/then descriptor的普通Promise。未知subclass/自定义constructor或species不能通过公开API安全观察，固定拒绝且不触发不安全getter；它们仍可能产生独立后台异常，属于不合格受信检查器，组件不宣称普遍恶意回调隔离。合格verifyCurrent/control.check始终必须同步返回boolean，不修改Promise/SDK原型、不安装全局unhandled handler。

构造只安装一个自有extension `rotom.durable.readonly`，含自有RootTask以及两个工具`rotom_read`、`rotom_search`。registry内必须恰为原三builtin Task及这个原RootTask，工具恰为这两个原对象；不安装CodingTools、hooks、wraps、handoff、sections或额外task。固定snapshot对象、公开方法、installed/tools/tasks内容及原对象身份在每个准入点检查；不只比较name/version，也不把freeze(Map)当限制。api.registry必须是该原snapshot，而不是旧phase snapshot或另一个同名registry。

## 固定参数与输出

普通标准JSON schema明确object/properties/required/additionalProperties:false；两个工具固定replay="unsafe"，不提供prepareArguments。read只有rootRef/path，search多一个query。业务参数校验使用自有闭合数据校验，拒绝Proxy、accessor、继承字段、Symbol、未知字段、循环、toJSON、非法Unicode和隐式类型转换。

rootRef采用非秘密引用`[A-Za-z0-9][A-Za-z0-9._:-]{0,199}`，不接受绝对根或grant。path最多4096 UTF-8 bytes，采用相对POSIX路径，禁止绝对路径、反斜杠、空段、`.`/`..`段及control/format字符；search允许独立`.`表示所授权搜索根，read不允许。query是1–4096 UTF-8 bytes的单行字面文本，禁止control/format字符，不解析regex/glob/命令。所有实际根、路径解析、别名/链接和快照保护仍由已资格backend决定，参数形状不授予读取根。

control.execute只返回闭合`{text:string}`；有效Unicode、无NUL、最多256KiB UTF-8 bytes。工厂复制成自有冻结`{content:[{type:"text",text}]}`，不转发control/details/diagnostics/usage/工具注册字段。所有失败只返回固定`isError:true`和固定文字，不转发原SDK/control/backend异常、路径或参数。返回isError不禁止generation后续发送，仍由Models门控制。

## 三份输入绑定与公开只读观察

一次execute捕获原api/taskId/conversationId/callId/getTask/commit/registry和原opaque Context。Context可使用公开getter，但只读取abortSignal；通过捕获原生AbortSignal.aborted getter核真实原signal，拒Proxy或已取消，不把instanceof或标签当证据。原api/Context及其宽方法不会传给control.execute或业务backend。

1. 自有最终args立即闭合复制冻结，等待之后不能重新接受变更后的引用。
2. public getTask(self,原Context)核原pi.tool v1、相同conversationId、owner原generation ID、background=false、abortRequested=false、running状态及闭合execute checkpoint `{phase:"execute",arguments,replay:"unsafe"}`；input恰为`{assistant,callId}`。另以原getTask(owner)核pi.generation v1、相同conversationId、foreground、未取消及pending/running/waiting；completing/terminal拒绝。数字ID均为正safe integer，call ID为最多200 UTF-8 bytes的非空无control/format字符字符串。
3. 在独立public api.commit只读callback中读取`Tx.entry(原AssistantEntry token,原assistant ID)`。不在该callback里嵌套commit，不写Doc/Task/表。callback必须实际执行恰一次，在私有本次live窗口内捕获原Tx.entry及receiver，读取前后核当前工厂/来源/api/signal/args及entry方法身份；核原entry ID/conversation/kind及byTaskId为原generation ID、model[0]的assistant message，并要求所选call ID在该message的toolCall中恰好出现一次，name恰为当前工具。只复制这个原call的arguments，生成原私有冻结回执；不把整条模型消息或原Entry交给control。外层observed结果必须===这个实际完成callback的原回执，字段相等不能替代身份。skip/replace/duplicate/reject/过早resolve均零control.prepare/execute；外层settle/失败finally永久关闭read窗口，迟到callback/entry resolve/reject不能补签回执或进入control，不自动重试。这个回执只证明所选公开读取路径，不签真实权限或SDK来源。
4. 原call arguments、原checkpoint arguments、传给execute的最终args必须各自通过同一个闭合参数校验并拥有相同完整规范值；任何SDK转换、optional null删除、beforeTool替换、未知字段或缺记录都不进入control/backend。再次public getTask(self及owner)核同一input/owner/完整checkpoint、tool仍running、generation仍非completing/terminal、均未取消；原对象共享值不能在await期间改变已捕获事实。

原Entry外层仅允许固定公开id/conversationId/kind/model/data/head/edits/byTaskId；optional data/head/edits不遍历。AssistantMessage允许固定pi-ai1.0.2的role/content/api/provider/model/responseModel/responseId/providerThinkingLevel/thinkingLevel/diagnostics/usage/stopReason/deferred/errorMessage/rawStopReason/endTurn/timestamp，读取仅role/content，不复制其余值或当授权。以上对象拒未知字段、Symbol、accessor及Proxy。content最多4096项，扫描只own读取type及toolCall的id；非所选text/thinking正文和其他call arguments不遍历。所选toolCall闭合字段type/id/name/arguments，可含own string thoughtSignature（最多256KiB，不记录或转发）；已知optional namespace首批显式unsupported，存在即拒绝，因为固定两个工具没有动态namespace能力。这不是把真实合法message误当只有role/content的结构，也不把无关账单/正文搬入控制面。

每次await后核工厂、原api所捕获字段/方法、原Context/signal、原输入和来源仍有效。原api对象是公开结构，身份检查不是任意caller已经获用户授权的证明；真实授权必须由下面独立control核原持久受理及整个ownership链。

## 控制面和单次派发

control是受信服务注入的闭合原方法对象`{prepare, check, execute}`，保留原receiver及方法身份；客户端不提供它。

- `prepare(invocation)`异步返回不透明非Proxy对象ticket，仅准备授权，不进行业务IO、模型发送或另建任务。invocation是自有冻结记录：schema、operation（恰为原工具名rotom_read或rotom_search，无字符串别名）、闭合parameters、sourceIdentity、registryIdentity、nativeToolTaskId、nativeGenerationTaskId、nativeConversationId、nativeAssistantEntryId、nativeCallId；不包含SDK对象、账号、grant补齐或任意回调。
- `check(ticket, invocation)`同步必须返回字面true，独立核当前RootTask/受理记录、原完整grant/读取能力/产物/快照/预算、owner、任务状态和ticket品牌/用途。模型数字ID和工厂metadata只是查找线索。未知、漂移或scope不一致拒绝，不能凭同名恢复或自动重发。
- `execute(ticket, invocation,原signal)`是已资格控制面到受限backend的唯一派发方法。工厂在最后一次当前检查后先不可逆消费该ticket，再以原receiver同步进入这个方法；同一原ticket任何第二次执行（含并发、不同factory、关闭后新factory）都拒绝。模块私有WeakSet由所有本模块factory共享，close不重置、没有reset接口，不在globalThis/Symbol或SDK上打补丁。ticket未知执行结果保持已消费，不退票或自动重试。

最后调用之间无await；execute内的真正IO入口仍必须沿共同权限/隔离契约再次核能力与取消。工厂的同步入口检查不证明异步backend一直满足authority，不证明signal取消已停止IO。prepare/check/execute必须来自同一合格control，不能把假control的true当真实授权。成功输出也在await返回后核当前工厂、调用、signal和control票据，再复制有界结果；取消、漂移、未知或结果不合格只发布固定错误。工厂不关闭共享SDK/DB、取消别的任务或释放未知资源。

control.check在派发前和结果发布时都只核本次原ticket的当前权威及用途；结果核验不重新发票、消费或恢复执行权，允许核原已消费ticket的结果。工厂模块WeakSet单次消费与真实control持久状态分别判断，不能把内存集合当不同process/worker/loader实例、重启或真实once证明；control也不能另发对象绕过原任务unknown。新的独立原ticket不因其他factory的旧票据被阻断。

## 默认验收及独立限制

新增`src/registry.ts`及`tests/registry.test.ts`，默认自有mock registry/publicapi/control，复用原test-pi-mock守卫；不import实际SDK或读真实业务根/账户。验证：精确4task/2tool/单extension，空/漂移/跨extension同名覆盖与snapshot内部引用修改失败，schema不授予权限，原call/intent/final转换拒绝，缺/重复call或错误owner/state/abort/context拒绝，每次异步间隙的来源/字段/方法/参数/取消变化，未授权零execute，原ticket并发仅一次execute，失回执无复用，结果未知字段/超界/异常无泄漏，close后零新派发。

固定命令：`/home/weixiaoxian.wxx/.nvm/versions/node/v24.14.0/bin/node scripts/test-pi-mock.mjs agents/pi/packages/durable-service/tests/registry.test.ts`。测试只证明有限工厂调用次序和自有数据边界；control返回true、fake native IDs、fake signal、mock只读callback均不授予真实SDK/owner/根保护、恢复或T084资格。真实组合必须另备固定公开SDK和合格backend材料，并按独立授权验收。

当前稳定源为registry `c6a7400d32cf1112fc045316da5f5c5170ac5c9836bc1b08c3696a829800c855`、tests `e084210ee481bd091a3569f7d62e81e3bea645e045b058758ddc0c50d72c1768`。最终140 passed、0 failed、281.724605ms；旧134绿在独立审查发现同步Promise拒绝未观察的P2后保持未验收。真实旧源配新增138项测试135 passed、3个unhandled rejection failed；最终再加两项边界测试共140项，计数不相加，也不把旧138红称为同一完整140套件。原publication和callback-window旧红、各版本材料均保留。root全文读当前两文件，独立增量复审无剩余P1/P2；结果发布阶段使用相同检查helper，未单列post-only rejectedPromise运行反例，不能扩称独立覆盖。

此有限工厂不安装generation/compaction身份hooks。T084/T086的完整Harness组合仍需将已实现原call-identity桥、Models准入和受限工具在同一个固定registry/来源下组合后封闭；不能热加hooks或把本工厂当完整发送覆盖。内存ticket集合不代替owner/持久unknown对账。
