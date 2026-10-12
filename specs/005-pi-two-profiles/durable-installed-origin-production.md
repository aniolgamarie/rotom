# B3：显式 Full owner 材料的生成、封存与读回

2026-10-07 root 实施冻结；本包已授权以下唯一范围的默认实现，实际结果仍待稳定验收。metadata 数据入口及原 read_lock 四核已验收，整文件逆变换留在本次迁移审计、常规测试不冻结未来整个 dependencies 文件。本文把下一次安装修改作为一个完整包：声明、生成、精确文件集合、原 seal/status 和读回共同完成，不先发布独立资格编码器。固定角色路线沿用 [owner launch 来源](durable-owner-launch-registration.md)，origin 五字段方向沿用 [材料方向](durable-installed-origin-materials.md)。

本包只实现默认临时安装中的材料契约。合法 role 声明、origin 或 installed 状态都不签发初始化角色、RegisteredReference、lease、sourcehold、Python/Node 执行或数据库权限。正式 Full、controller 代码、解释器完整来源、许可证和原生组合仍分别缺验收；不生成正式现代锁、启用现代 launch/factory 或部署。

## 新的显式声明

仅 v2 `pi-full` 可在输入 profile 与 locked slice 中声明可选 `durable_owner`，闭合三键：exact native int `schema_version=1`、exact native int `protocol_version=1`、`roles`。roles 恰含四键，映射如下；没有可选角色、callback、命令、路径覆盖或资格布尔。

| role | 闭合字段与固定值 |
| --- | --- |
| owner_node | `source_id` 为该 slice 中已声明的 Node source ID，`path` 恰为 `bin/pi-node` |
| owner_bootstrap | `source=agents/pi/runtime/durable-owner-bootstrap.ts`、`path=runtime/durable-owner-bootstrap.mjs`、`transform=ts-module` |
| owner_codec | `source=agents/pi/packages/durable-service/src/owner-message.ts`、`path=runtime/durable-owner-message.mjs`、`transform=ts-module` |
| owner_controller | `source=scripts/pi-durable-owner-controller.py`、`path=supervisor/scripts/pi-durable-owner-controller.py`、`transform=copy` |

有声明必须有原有效 Full `python_bundle` ref、七个固定 wheel 源和配套 body row，engine=node。Node source 必须已选、kind=asset、format=node.tar.gz、target=bin/pi-node；复用原 Node/source/platform/toolchain/version 校验，不从 PATH 选择替代。三个自有代码 role 必须与 runtime_files 的唯一 source/path/transform 完全对应，locked rows 原 input/output digests 和 mode600 继续核。不凭文件名判角色；全量来源核验还是原 read_lock/install/seal 的职责。此包不创作或运行尚未完成的 bootstrap/controller；合成默认正控制中的固定路径代码字节只是非执行 fixture，不计真实 role 可运行资格。

公开角色数据规则统一放现有modern launcher，接口 `validate_owner_declaration(name, piece, sources, *, toolchains, locked)`；不把它放新origin resolver以致Base全局metadata核提前导入可选IO模块。vendor input带真实name/未锁rows调用，locked `validate_destinations`只在声明存在时对manifest的实际Full piece调用，必须对应同一pi-full slice；schema同时禁止其它任意profile（包括自定义profile名）携带声明，不能只特判pi-base。Node toolchain规则复用现有public validate_node_asset_toolchain，原validate_asset_platforms流程保持。metadata32节点必要paths是显式literal集合，加新origin helper/两个固定schema；这是材料必需集合，不宣称已核整个未来controller闭包。

这是一组公开数据规则，不是初始化 principal。正式能力/provider 选择仍经原完整 bindings 与 selection 核，candidate 仍不能 sync。插件替换改变来源/绑定/runtime 身份，不能在活动任务上换 source 或 reset SID/budget。任何未来市场插件也不能覆盖三个固定自有 role 或把数据声明当专用 principal。

无 durable_owner 的既有 v1/v2 输入、生成文件集合、状态和合法 domain 保持；v1 或 Base 出现声明拒绝。Base 普通入口不声明、生成、读取 origin，不 import 新 origin resolver。Base 读取包含未选 Full 的整份锁仍按原要求核全部公开元数据；这种 metadata 校验不读取未选正文/vendor/optional origin，不把全局数据校验误称零所有 Full metadata 访问。

## 完整材料与固定资源

Full producer 必须实际分发固定 schema `supervisor/schemas/pi-lock.schema.json`，不能用八个 `supervisor/agents/pi/schemas/*` 管理 schema 替代。当前 metadata 入口及所读 module-scope 静态图为32个自有模块、直接第三方 roots jsonschema/referencing/yaml，有限证据 receipt `377c28e0bb1e7169c5d1d0d73dd85909440769329ee17778a97785fc3122785e`。按该证据列显式必要 runtime rows，另加本包自己的 origin helper 和固定 envelope schema；不在运行时扫描源码或自动扩展 manifest。


metadata必要模块的冻结literal集合如下（每名对应source `src/agentcfg/<name>.py`、target `supervisor/src/agentcfg/<name>.py`、transform copy）；从377收据归档的JSON逐项取得，不能在运行时扫描或自行加条目：

```text
activity, adapter, config, deployment, local_values, merge, model_defaults, native_projection, paths, pi_assets, pi_built_assets, pi_bwrap_build, pi_bwrap_source, pi_capabilities, pi_catalog, pi_lock_header, pi_lock_layout, pi_lock_metadata, pi_lock_resolution, pi_modern_launcher, pi_node_archive, pi_node_asset, pi_python_bundle, pi_readseek_vision, pi_runtime_files, pi_vendor, pi_wheel_sources, process, schema, secret_files, secrets, storage
```

此外固定新增 `pi_owner_origin` 自有模块行、root `schemas/pi-lock.schema.json` 行、`agents/pi/schemas/durable-owner-origin.schema.json` 行，以及上面三个角色行。任何新helper实际导入确须超出该集合，先交root作增量选择，不凭这份集合叫动态/整个controller完整闭包。

该32节点图不是第三方/stdlib/动态 controller 的完整闭包证明。校验器以固定公开 API 消费已选材料，本包实际默认 fixture 证明声明集合、字节复制与资源路径；真正 `-I -S -B` installed 导入、所有 controller 自有调用路径、第三方 wheel 依赖/ABI 与解释器来源在原生/来源包另验收。本包不得用“32行齐了”把该 gate 置 true，也不得 fallback 仓库或 venv。最终实施新增 import 后，实际所用闭包须再记录增量，不能仍称原32节点为新完整闭包。

已选 package_json/package_lock 原 bytes、bundle 原 body、七 wheel vendor bytes按原固定路径留存，全部纳入完整 sealed inventory。origin 不内嵌它们，读回必须实际读这些原材料；需要 repo recipe/archive/build/license 的职责仍保留在原 read_lock，不以新 data API 替代。

## envelope 格式

固定 `runtime/durable-owner-origin.json`，600/单 link，exact 五键：schema_version exact int1；profile exact str pi-full；lock_identity/runtime_identity exact str lowerhex64；metadata 是完整 detached v2 lock metadata。metadata.identity 与同次真正 PiLock.identity 相同，runtime_identity 是同次原 backend 算法结果。未知字段或错绑定失败，不能默默 strip、修复或构造小型 selected manifest。

新固定 `agents/pi/schemas/durable-owner-origin.schema.json` 只声明五键 envelope 与 metadata object；完整 metadata 继续由原固定锁 schema/data API 验。schema 不引用远端、不接 caller schema/registry/loader，不把 schema success 当可信来源。JSONSchema 的 integer 域不替代 exact native 版本检查。安装目标固定为 `supervisor/agents/pi/schemas/durable-owner-origin.schema.json`。

raw 上限16MiB。strict UTF-8 JSON，拒所有层 duplicate keys、非 finite、非法 surrogate、未知/超域；metadata 单独使用原数据 API 的 signed64/finitefloat、depth16、100000 nodes、4096字符、8MiB UTF-8与 expanded alias 预算，不能因为外加 envelope 两层收窄原 metadata 深度域。envelope scalar 和 expected 参数先 exact native 捕获，随后只读自有值；不能 repr/hash foreign、附加原异常/JSON doc。生成与读回都用原 json_bytes canonical UTF-8 算法，raw 必须逐字节等 canonical 结果；不改 npm/body 原 bytes 的 canonical 规则。

16MiB是新origin编码的独立支持域：就算metadata本身通过图域，转义及envelope开销使canonical raw超限也必须明确失败，不能截断或扩大cap；不声称所有旧合法metadata都必然可编码成这个新envelope。无owner声明的旧合法路径不受该新增cap影响。实现须测试canonical边界和合法graph但origin编码超域，不能混淆两个预算。

不能把整个16MiB JSON直接丢给下游：JSON decoder 前以有限 lexical 预检把同时打开的 object/array 容器上限定为18；metadata 原 capture根depth0，最深合法空容器depth16对应17个嵌套容器，外加envelope一个恰为18。字符串里的 escaped delimiter不计，所有JSON grammar仍由原decoder核，预检不是第二套宽松parser；decoder duplicate/nonfinite hook和decoded native捕获仍必须全部执行。metadata单独从depth0核，不能对整个envelope套原depth16 graph而无意减掉一层。UTF8文本至多 raw cap，token数量受实际有限图核；普通解码错误统一fresh `ValueError("pi-owner-origin")`，清cause/context，不留输入链，control BaseException保留原对象。

没有 source_identity、自己的 rawhash/inventory/receipt、generation/private preimage/state hash、路径/fd、accepted/qualified/capability 字段。origin 写入后才形成 inventory，原 runtime identity 算法仍不包含 origin/inventory；不得改变 identity 算法去吸收 envelope，再反写同一 identity。未来 source identity 不能写进自身 preimage。

## 原 producer 的写入窗口

新 `pi_owner_origin` 的接口固定为内部 writer `_write_owner_origin(stage, metadata, *, identity, lock_identity, platform, toolchains, binding_identity)` 与只读材料入口 `validate_installed_owner_origin(root, piece, *, identity, lock_identity, platform, toolchains, binding_identity)`。writer返回None，reader返回五键detached envelope；两者都不是配置/CLI/extension注册接口。root/stage仅由原受管installer或其原验证调用点传入，不能扩成任意source picker；actualcurrent/role/principal资格在本包之外。

writer先用现有metadata模块自己的内部native捕获核取得独立metadata，再从其已核固定Full slice路径读取selected pair/body；后续完整验证必须消费同一个capture。预先捕获expected scalar/toolchain/binding的exact native值，任何caller图二次lookup/foreign callback都不补结果。reader先捕获expected piece与context，在固定原root读取envelope并严格decode，再从该次已capt获完整metadata取得固定pair/body。调用公开capture_pi_lock_metadata_data完成同图对应，不能把stage/repo伪造成Workspace或给数据核新的loader参数。

现有 `pi_runtime_packages.validate_installed` 新增仅供owner材料组合的keyword context（identity、lock_identity、platform、toolchains、binding_identity；无声明的旧调用缺省保持），有durable_owner时缺context失败。seal在原validate_installed调用前传它已有的同次context；status在原receipt/schema/identity/inventory核后传它已有的actual receipt context。两处不能从origin自己的值填expected来绕过外部对应。

原 `_sync` 取得真正 lock、原 runtime identity，原 candidate 拒绝、runtime package保护与工具链检查保持。在原 asset/launcher/helper 安装和 optional bundle 物化后、seal 前，只有已选 v2 pi-full 且存在已核 durable_owner 声明才调用新固定 writer；不能仅因 profile 名、bundle ref、caller bool 或 runtime JSON同名启用。

writer 从该次 lock 与实际 stage 取得完整 metadata、所选 pair/body，把原 cached selection 的 binding_context 仅用于数据对应，不能重建/伪造 accepted grant。先用 capture_pi_lock_metadata_data 及公开 selection/runtime_identity_payload 重核材料和全部绑定，逐项对应同次原 lock/runtime/piece/toolchains/platform。所有必要材料/声明核完才写 origin，随后读回同一 canonical 原 bytes；失败不调用 seal/activate，旧 runtime 保持。

原 launcher 写 profile/commands 时 origin 尚不存在；不提前创建空占位以过其文件检查。origin 写入后，必须调用 Full 限定精确 expected 集合再进入原 seal。角色声明不允许任意生成文件列表：origin 路径是唯一额外生成项，不能追加通用 GENERATED、允许任意 runtime JSON 或通过 caller set(generated) 获得它。存在显式 runtime row 与 origin 固定路径冲突时拒绝，不能覆盖已有源文件；无声明时原 runtime_files 合法域保持。

所有新增 IO是原 stage事务中的普通材料写读，不是来源资格读者，也不保留长期fd。没有当前实例/storage mkdir、owner lock、Node/SDK/DB、模型或账号访问。Tree 的既有安全祖先/所有权/原子文件原语保持，不为 /data unsafe ancestor 放宽规则。

## seal、status 与完整读回

原 receipt/inventory 算法保持；锁和 receipt 的 slice schema增加同一闭合 optional声明，v1禁止，出现时绑定 v2/Full。header/global metadata data检查新增数据规则仍在原 metadata 切点，不提前 archive IO或读未选 Full 材料。

`validate_files`的额外 Full输入是该 slice的 closed durable_owner 声明，结合原 bundle ref与原 rows核精确角色对应，再允许唯一 origin；没有通用bool/callback/权限对象。正常调用仍用原 GENERATED tuple。不能只改 writer；`validate_installed`、seal、activate、status的全部受影响调用必须一致传递该声明和实际 runtime/lock/toolchain/platform/binding context，禁止单独漏接status后再宽化guard。

新增固定读回 helper 从既有 stage/runtime根的固定 origin路径与捕获 metadata里的固定 selected pair/body路径读材料。校验 envelope/version/profile/full metadata、声明/row/schema对应、metadata/piece/lock/toolchain/platform，重新计算原 base runtime与 selection runtime payload，逐字段恰等原 binding_identity 与 runtime identity。accepted binding_context 只来自原调用已持有的 cached binding 或 actual receipt字段，作为自洽数据检查，不称独立授权。

读回仅返回五字段 detached envelope或固定错误，不返回角色引用、权限flag、validator factory或可注册对象。schema合格/同UID/完整hash/receipt成功都不是 initializer资格。原 status 的 actual inventory逐项比较仍完整执行，任何 origin/rawpair/body/schema/helper/vendor漂移均为 damaged；不以只核selected少数files替代 inventory。

reader/writer共享的材料核须实际取得固定角色文件与必要helper/schema，按该次捕获locked rows核目标字节digest/mode600，不能仅检查rows里出现相同名字。Node本体在固定bin/pi-node用原Tree.open_read、64KiB流式散列，长度1..原MAX_BINARY=128MiB、mode700，恰等同一source.node_archive.binary_sha256；固定licenses/<source_id>/0-LICENSE最多原1MiB，恰等license_sha256。沿用原Tree窗口前后身份/安全规则，新增stream读后核实际总长度与opened size/cap，不持长期fd、不声称原子exec/sourcehold。expected platform首版仅linux-x86_64并与所选Node/source及bundle平台对应；Mac按需另验，不为未测平台fallback。这些有限实际材料核仍不证明ABI、执行来源或整个controller闭包。

读取/资源缺失按原 damaged/固定错误处理，不从别的 repo/当前新版 runtime/系统PATH/venv 查替代。真实 FullSourceView、current/lease/最后核与长期hold仍须下一包明确原 actor来源；本包不能把 public输入或良好 envelope 注册为有能力reference。

## 唯一写入范围与默认验收

唯一 executor 写：NEW `src/agentcfg/pi_owner_origin.py`、NEW对应测试、NEW envelope schema；修改 `pi_vendor.py`（输入声明与锁透传）、`pi_modern_launcher.py`（公开角色数据规则和调用顺序）、`pi_runtime_files.py`（Full精确额外集合）、`pi_dependencies.py`（固定producer hook）、`pi_runtime_packages.py`（seal/status实际上下文读回），及 `schemas/pi-lock.schema.json`、`agents/pi/schemas/runtime-receipt.schema.json`。原 metadata模块、旧 tests、路径/进程/账号guards、正式 dependencies-modern/locks/providers/roles、第三方宿主/源码缓存不可写。若需要改任何额外生产文件，root重新决定。

schema增量逆去须与完整实际pre-edit JSON深相等；optional接线的旧规则/切点/metadata有效域证据保留。新整个 dependencies 修改不得被旧本轮整文件迁移审计误拒；迁移审计读取其原冻结源快照、永久测试只保留行为与边界。

新默认测试用真实原生成锁/read_lock/_sync/installer/expected集合/seal/activate/status及实际临时文件；原 NPM/工具进程和网络为fake，角色代码/Node为未执行合成材料。不能 mock掉 metadata API、roles规则、bundle核心、seal/status或 inventory；文件缺项/内容漂移应从真实调用失败。正控制必须由原 pipeline生成，不能手写receipt/ready冒充完整安装。

覆盖无声明v1/v2/Base不变、Full完整材料成功、未知/缺角色/错映射/重复row/错Node来源/version/platform/body/漏schema/helper/explicit-origin碰撞、schema与raw边界、原stage生成后完整读回、实际activate/status、修改关键已封存内容为damaged。Base对新的writer/reader/module spy零调用/零origin读取；metadata/data成功或candidate声明不能产生初始化/IO/DB资格。错误文案固定、ambient context清理、control BaseException保留原对象。

运行新增套件后，仅一次跑确有影响的原 deps/runtime-files/runtime-packages/modern-launcher/wheel-integration/vendor/profile/lock-header/lock-family/schema相关组；具体列表先以实际调用与旧test归属冻结，不无故重跑core387/stage204/source-data248。测试 reports在工作区，basetemp是独占安全/tmp，HOME/offline/fakeprocess原guard；自己的测试临时根按 runner TemporaryDirectory生命期清理，失败相关fixture可单独保留，不能无限堆积到ENOSPC后改guard。成功/失败/环境不足逐轮单列。

实施前保存所有真实preimages，root冻结exact接口、lexical深度及实际写范围。STOP后root验稳定diff、实际证据与关键不变量；独立scout仅作限定一致性证据，不冒充全实现安全审查。若独立executor不可用明确记录。两次有效修法仍失败、顺序/transaction/identity不明确或需扩大范围交root；缺原生/账号只阻依赖项。formal7/100、产品gate和strict metering前AUTO OFF保持；旧closed Harness8/FD6不覆盖新增组合；Recovery3已收到d61799精确授权，作为独立固定探针执行，不扩本包默认测试边界。


## 实施范围唯一增量：旧一次schema审计的可持续迁移

root在实施前发现原 `tests/test_pi_wheel_lock_integration.py` 最后一函数 `test_b2_receipt_schema_inverse_exact_old_json_and_same_b1_reference` 固定整个历史schema并依赖anyOf/allOf末项位置；这与本包可选声明的合法schema演进冲突，不能作为新字段的行为失败。实际完整原test及两个schema已另存排他preimage，原逆去python_bundle后c6ce848253e40378636ba915d3d440ddc5b578a1b1a26740a6aeb5770782a015审计移到这些不可变快照的独立verifier，保留可复现证据。

因此唯一写入范围增加该旧test一个文件，总11file；只允许把上述函数的五行整schema逆/hash审计移出永久pytest，保留两个固定schema读取及python_bundle与sameB1reference一致断言，函数更名为 `test_b2_receipt_schema_uses_same_b1_reference`。除此之外完整旧test prefix及所有其它旧tests逐字节不变。这是对前文“旧tests不可写”的明确唯一例外，不排除node、不mock行为或人为制造red；原B2一次审计与永久跨schema行为检查各自保留。B3新增schema增量仍须对本包7实际preimages逆去后深相等，但审计不锁未来整个文件。所有接口/domain/order/产品边界与冻结a21fb0cf/19149B合同不变。


## 材料清单唯一调用路径增量

五个稳定自有文件的限定AST证据另核了selected bundle与installed读回路径：原32已含 `pi_lock_metadata`、`pi_lock_resolution`、`pi_python_bundle` 和 `pi_wheel_sources`，安装/读回公开函数的 `pi_python_bundle_runtime` 不在32，其实际install分支条件导入的 `pi_python_bundle_stage` 也不在32。root因此明确追加两个copy材料row：`src/agentcfg/pi_python_bundle_runtime.py` → `supervisor/src/agentcfg/pi_python_bundle_runtime.py`，及 `src/agentcfg/pi_python_bundle_stage.py` → `supervisor/src/agentcfg/pi_python_bundle_stage.py`。原32literal保持，材料必要module集合现为32+2+新origin helper，不能仍称32为所有新调用闭包。

这不增加11个可写文件、不开运行时扫描或自动补清单。该次collector只读五文件与旧归档，源码端点一致、零import/运行；不存在的 `pi_python_bundle_core.py` 是root任务包命名错误，实际core在原 `pi_python_bundle.py`，没有第六替代源码。这两个row是有限调用路径材料增量，不证明动态/stdlib/第三方/controller整体闭包、真实installed导入、来源/principal/native资格。主体精确schema/capture/order/旧test唯一例外均不变。


## 第二项已观察的旧schema整文件审计例外

唯一affected01真实结果为479pass/2fail/54setup error：integration行335的另一项永久whole lock schema a9a357…审计不能容纳无关的新durable_owner字段；另外metadata git fixture及随后setup是真实Errno28空间不足。失败完整保留，不把unknown、未执行的尾部断言或环境不足记通过。root限定同一旧test文件的第二个函数：只将 `test_schema_inverse_preserves_full_old_source_and_provider_definitions` 内11行 `old=deepcopy(schema)` 至历史a9a3575144ef036f8a1850b6f2466ac5bc1e6670e088dc8f5d16be950c5bb384 hash移至本包真实修改前锁schema的不可变标准JSON审计；保留schema读取、wheel与raw asset的两条standalone.is_valid正控字节，可更名 `test_schema_accepts_wheel_and_raw_asset_sources`。总范围仍11file；与第一末receipt函数例外之外整个旧test逐字节逆回40713B。原provider/source格式行为检查保留，不能扩大为删除其它测试或永久整文件hash。

生产83pass对应源码没有因此修改；已通过479节点不无故重跑。未成功的精确XML节点按schema1、metadata10、codec25、Base2、resolution12、selection6各自独占/tmp小批补验，共56；记录原fail/setup身份与空间恢复。不能删未知/tmp、改祖先guard或把第一个ENOSPC重命名为行为失败。必要新测试改动由root另指明，不从此条推断需要重跑全量。


## 当前稳定验收：2026-10-07

11个生产／测试target停止写入后，root验收86输入receipt `28d18a7ca53fcb3f451d7897d9204e0c8dc0bde8f8c778361094190cf0094491`。默认材料接线完成；它只接受显式v2 Full owner声明下的固定origin、所选原锁对／bundle／七wheel、固定32+2+owner模块／两schema／三code角色、Node二进制／许可读回及原seal／activate／status同次上下文。Base无owner的旧路线保留，正式Full锁未写入。

新suite `new02` 一次83pass／0skip／84.72s。随后只追加真正旧installed runtime保留检查并独立执行 `preservation01`：1pass／4.50s；原25113B测试前缀完整保留，当前84case没有作为一次全suite重跑。该新增case先用原installer完成旧runtime的seal／activate／status，原完整inventory／receipt／ready实值保存；通过原read_lock取得不同新lock/runtime身份，再修改新stage的Node字节调用原writer，验证拒绝且seal／activate计数0，旧实际runtime及完整材料不变、新identity无ready。它是合成临时运行包／fake子进程的产品代码IO验证，不是正式运行包或Node原生资格。原八个negative case只签stage／哨兵／seal0，不再外推旧installed保留。

旧受影响包 `affected01` 首次479pass／2fail／54setup errors／113.90s保留：一个历史整lock schema audit不适用，一项fixture复制与54项后续mkdir因临时空间不足未成功。只把这56个具体节点分成六个独占/tmp小批补验：54pass／2个旧v1-no-binding-state不适用skip。root从实际XML逐node核对无遗漏／重复，不声称一次535pass；已通过479与新83未重复跑。初次新suite17fail／49pass及2fail诊断也保留，原catalog不支持新固定schema的错误仅在新helper修为固定有界资源＋公开validator／空Registry，超大编码fixture缺原build id仅修fixture，没有放宽原schema／source／path安全规则。

两个schema按限定B3增量逆去后与实际旧JSON深相等。旧integration仅两获准函数改名及移除11+5行迁移审计，可精确逆插回40713B/e200da原文件，永久wheel/raw-asset正控制与跨schema相同bundle定义继续保留。迁移期whole hash分别在原冻结快照上actualexit0，不作为今后永久pytest演进约束。最终scout首末pins稳定，限定schema／测试结构证据；两次采集器字符串匹配失败保留、root核实际源码后仅授权第三次机械修正并成功，不当产品失败或测试通过。

root完整审owner模块／新83case及原caller／schema diff，再审稳定未变生产pins和追加旧runtime检查；scout只签上述限定逆变换／前缀。executor配置gpt-6.1-sol/medium、scout配置gpt-6-luna/high，未独立attest执行后端模型；没有额外独立executor全实现安全审查。默认证据不签完整controller／stdlib／第三方import闭包、解释器、原startup／initializer principal、FullSourceView／长期sourcehold、Node／SDK／DB资格或产品gate。

Recovery3 d61799精确三场另有46输入receipt8059bd7f已执行验收并闭合，namespace物理终止仍unknown；不外推B3或新source组合。正式7/100、全部产品gate与严格计量前AUTO OFF保持。下一包沿实际startup caller→接收manager双actor重核设计完成完整Full来源接口及私有引用，不由origin/status/JSON成功生成初始化能力。
