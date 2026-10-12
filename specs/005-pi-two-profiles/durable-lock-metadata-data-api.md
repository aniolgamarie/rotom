# 完整 Pi 锁数据核：installed-origin 的前置接口

2026-10-07 root候选。B2八target默认接线已稳定接受cde031，尚无完整repo-free metadata组合入口。本包拟抽出原read_lock的数据规则，并给将来的installed-origin提供完整数据入口；不实现origin文件、安装声明、source reader、角色、activation/hold或资格工厂。此稿先有限复审，复审后才授权唯一writer。

## 原IO与数据职责

原`read_lock`顺序仍为：manifest读取/固定schema及identity → 原repo recipe重算 → v2全bindings → accepted digests/选择 → 每source的license路径/类型元数据与所选archive/build IO → 每slice元数据与所选runtime/body/archive/npm pair/license IO → build-step元数据 → 原PiLock及所选selection。原repo recipe、全部原档案/构建/许可/runtime输入、选中zip规划等检查保留，不把metadata validator替代它们。

原local/git的vendor bytes检查先于git commit/local source_path规则；本包用source prefix/suffix两个共享内核保持这个切点。不能把全部metadata提前到recipe之前或一次性移到原IO之前，从而改变原失败顺序。来源元数据JSON、`PiLock`或成功验证都不产生初始化/运行/IO/DB权。

已有source数据、header/resolution、bindings、selection和B2物理校验继续复用。public header读取自身固定`schemas/pi-lock.schema.json`，因此本包不是“零文件IO”的纯组件：新增入口只允许这一固定自有schema资源读取，不接受schema/path/loader/callback，不读repository、vendor、实际installed/current/账号。完整Full后续须实际分发并核这份固定schema及完整代码/依赖闭包，不monkey patch ROOT或假造repo/Workspace。

## 唯一写入范围与接口

新增`src/agentcfg/pi_lock_metadata.py`、`tests/test_pi_lock_metadata.py`；仅修改`src/agentcfg/pi_dependencies.py`里read_lock的数据规则调用点。原header/resolution、capabilities、assets/build/vendor/runtimeFiles/wheel/core/stage模块及全部旧测试/guard、schema/正式锁/provider/catalog/运行声明不改。B2实现已STOP后才能开始，不与其它writer共享文件。

共享的内部数据内核保留原body语义与顺序：

- `_validate_source_prefix(source)`：原license_sources检查，然后npm字段/version/HTTPS/credential/SRI、wheel固定source校验、asset固定校验、local/git共有package/version/vendor/digest检查。无archive IO。
- `_validate_source_suffix(source)`：原git commit与local source_path/source_tree_digest检查，置于原所选archive IO之后。无其它条件变化。
- `_validate_slice(name, piece, manifest)`：原source IDs、asset平台闭包、v2 bundle ref及destinations、原slice/resource identities和resource capability关联，逐项原顺序。无runtime/body/archive/pair/license IO。
- `_validate_build_step(step, sources)`：原source IDs、expected_outputs/output_digests集合及input/output路径规则。

这四个underscore函数是仓库自己的内部复用核，只由原已JSON解码且完整header已核的read_lock或下面已捕获的入口调用；不是面向foreign对象的独立public边界。不得修改agent上游私有接口。旧read_lock不新增完整native snapshot/cap，不因新public支持域收窄旧有效输入；其固定ConfigError及控制异常、PiLock/pair/validated输出继续原语义。

新增public入口：

```text
capture_pi_lock_metadata_data(
  manifest, profile_inputs, *, schema_version,
  accepted_binding_digests=None
) -> {"metadata": detached native JSON, "profile_inputs": detached dict of immutable bytes}
```

输出严格两键，无selection/来源cap、private引用、资格布尔、注册外观或路径解析器。它是本次新捕获图的副本，不声称来源可信或非秘密；未来固定public producer、实际文件读取/来源重核与同一原私有引用分别负责这些前提。输出修改不能回写caller输入，后续调用不能从caller再次lookup旧capture。

## 新入口支持域与捕获

新public入口不是通用JSON validator的兼容声明，支持域显式限定如下；它不改变原read_lock的合法域。manifest/accepted maps仅支持exact native dict/list/str/int/float/bool/None，键必须exact str；拒dict/list/str/int subclass、bytes或foreign值作为JSON叶子、非str键、cycle、不合法UTF-8 surrogate、非finite float。int限signed64；finite float仅保留JSON数据类型，不转成int，不扩大后续schema/source/ref的精确整数语义。

单图节点上限100000、深度16、字符串上限4096**字符**且有效UTF-8；所有键和值字符串的实际UTF-8总字节合计不超过8MiB。每个原dict只单遍捕获typed键和值引用，全部键类型先核再建立自有map；所有后续递归/lookup/计算只用已捕获图，不对原图重复读取。list同样单次捕获引用再walk；不要把此过程称原子快照。超域在固定schema读取前拒绝，不能repr/str/hash/eq/调用foreign方法。

同一原容器的alias必须复用首次完成的capture，active中再次引用为cycle拒绝。memo保留原exact容器引用与detached结果，不能仅凭可能被复用的id关联；每个完成子图记录其展开node/UTF-8成本及高度。后续alias每次按其完整展开成本收费，并按本次depth加子图高度检查，不因memo共享绕过JSON展开预算。输出允许只在新自有图内保留alias；绝不保留caller可变容器。profile blob record也只捕获一次，raw bytes总量按每次profile/字段出现收费，不因相同对象或memo免计。manifest与accepted map共享一次调用的node/UTF-8预算；每份decoded JSON单独按相同图域核，不从JSON decoder直接把未核对象交给下游。

`schema_version`必须exact int 1或2。`accepted_binding_digests`缺省None保留原语义；存在则exact dict、typed key与lower hex64 value，keys须属于原全部profiles，不能把这份caller数据当真实accepted grant。

`profile_inputs`为exact dict，1至64个exact str profile keys；每个值为exact dict，required `package_json`、`package_lock_json`，optional `python_bundle_json`，无其它字段。全体键与blob引用在任何schema/validator调用前捕获并核型；每blob须exact immutable bytes，两份npm JSON各1MiB，bundle JSON各8MiB，所有blob总量16MiB。blob不可由path、bytearray、memoryview、callable、foreign容器代替。返回重建map，immutable bytes可保留原引用，不造fake文件。所有profile都须真实存在于已捕获manifest；不静默忽略多余profile或blob。

manifest/native maps、全部profile-input records、版本和accepted map必须在首个固定schema读取/validator/import回调前完整捕获。这里不承诺消除模块自身必要的stdlib导入，也不对原JSON解码器进行patch。普通错误统一fresh `ValueError("pi-lock-metadata")`并清cause/context；控制BaseException保留原对象。不能把source值、原错误、caller活跃异常或私有材料附加到错误链。

## 完整数据验证顺序

1. 复用原header完整schema/version/identity；不从caller接schema，不改schema cache/Registry。
2. 对v2复用全manifest bindings；校验accepted keys和所选profiles。
3. 对所有sources运行共享prefix/suffix，对所有slices运行共享slice内核；未选source/slice仍须数据自洽。
4. 对每个所选profile，实际 supplied package/lock bytes的SHA须恰等原slice digests；strict UTF-8 JSON解码，拒所有层decoded重复键、NaN/Infinity/overflow、非法surrogate/foreign或超native图域。不要求npm原bytes重新canonical，不能静默rewrite。复用原resolution规则。
5. 有python_bundle ref必须给该profile的python_bundle_json，复用原validate_selected_python_bundle核body/ref/source对应；无ref却给该blob拒绝。不读/展开/执行archive，不用它假称原zip/install规划已重核。
6. 复用build-step数据核；对v2每所选profile使用原validate_selection_data，lock_identity/host_version/engine来自同一原捕获manifest，accepted对应值来自已捕获map。pi-host仍须在该slice且有原version。candidate/current/accepted各原数据规则保留，成功不是运行资格。
7. 返回两字段detached数据。不能再读取caller图或调用foreign callback补结果。

recipe_digest只作为已核header里的数据字段，不在此重新计算；原archive/build/license/runtime输入、安装内容及任何角色/当前/解释器/principal/持有事实未验证。将来installed-origin原producer只使用该次真正read_lock及实际runtime算法的材料；任意调用本入口不准生成有能力reference。固定schema合法也不能证明每个字符串非秘密，来源资格和公开producer不得由regex/hex/数据成功替代。

## 默认验收与升级条件

先保存四共享核对应的完整旧read_lock片段、最终新tests和全部初始pins。默认仅原隔离HOME/网络/假process/虚构provider，schema读取为自有固定文件，不运行第三方宿主/SDK/新捕获wheel/native/模型。新入口没有旧实现，不伪造behavior red；提取旧核须逆回原read_lock片段并比较完整原文件，不能调整旧tests适应改错的语义。

正控制包括原合法v1数据、v2 Base及Full、真实生成的合法raw package/lock字节、wheel refs有/无body、两profile完整未选记录、local/git/npm/raw/Node/built source与原build-step规则。original read_lock保留recipe→bindings、source prefix→archive/build→suffix、slice metadata→runtime/body/archives→pair/license→build→selection的可观察顺序；用已有fake Tree/producer及明确事件证据验证，不能mock掉data kernel或seal/status来通过。

反例覆盖未选source/slice/资源/build错误、rawpair hash/图错误/所有层duplicate/UTF-8/非finite、缺/额外blob、错profile、selected host/ref/body、candidate数据不得冒资格、foreign键/值/容器/路径/数字零hook且零schema读取、capture后caller迟到变更不触foreign、固定错误/ambient context/控制异常、输出detached。数字schema保持原标准integer/finite float语义；后续精确native source/ref规则仍由其原validator负责，不新增全局checker。

新suite通过后一次运行确有变更的原read_lock/resolution/header/capability/runtimeFiles/wheel integration测试，再按新失败定向修复；core387/stage204/source-data248及未改vendor/license suites不无故全量重跑。writer STOP后root验稳定diff/正确性/实际元数据；独立scout只作有限一致性/逆变换证据，若executor线程仍不可用则明确记录。任何校验顺序/旧有效域/来源边界变化或两种有效修法仍失败都交root，不扩scope、不把环境不足算通过。此包不能勾整个正式任务或产品gate；formal7/100、AUTO OFF和Recovery3待独立授权保持。
