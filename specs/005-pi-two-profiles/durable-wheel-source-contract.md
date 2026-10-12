# Wheel 来源与 Full 固定引用的 exact 契约

2026-10-07，root 在已接受的 wheel 锁方向上冻结数据接缝。本包先实现两份新文件中的公共数据规则；不改正式声明、schema、原生成器或 installer。随后接线必须使用同一规则，并分别验收原调用路径；不能只让新 schema 接受记录而留下 npm／安装误路由。临时七档案 IO 已接受，不提供正式 Full 来源或启动权限。

## 本包 API 与写入范围

唯一 executor 可新增 `src/agentcfg/pi_wheel_sources.py`、`tests/test_pi_wheel_sources.py`。不改现有 Python bundle core／stage／测试、schema、capabilities、vendor、dependencies、锁、资源和 profile。模块顶层仅用 stdlib，不能顶层或通用记录路径导入 bundle、ZIP、Durable 或 agent 宿主。四个 API 全为数据规则，成功不产生文件、能力、来源引用或 ready：

- `validate_wheel_source(source, *, locked) -> None`。
- `wheel_source_identity(source) -> str`：只接受 locked 记录，返回下述非秘密投影的 SHA256。
- `validate_python_bundle_reference(profile_id, piece, sources, *, locked) -> None`：检查小型引用与切片配对，不读正文。
- `validate_selected_python_bundle(declaration_bytes, piece, sources) -> dict`：只在调用者明确选中 Full 的原入口使用；检查已取得的原字节并返回 detached native JSON。它不读取档案或文件，不证明调用者真的拥有所选来源。

`locked` 必须 native bool，不能靠 truthiness；`profile_id` 只能是原两现代名称。输入须在任何哈希、序列化或外来方法调用前完成有界 native 快照／检查：仅 exact dict/list/str/int/bool/null，拒绝子类、cycle、float、非 str key、超过 signed64 的 int；深度16、总节点100000、任一字符串4096字符并须 strict UTF8（字段自身另有更短界）。先检查容器长度再遍历，不能 deepcopy／repr 外来对象。Piece 只取 source_ids、runtime_files、python_bundle 三个字段，sources 只取外层 key、每个原生记录的 kind，以及 kind=wheel 的完整记录；其它 npm／asset 内容保持由原 validator 检查，不重复实现。快照后不再读 caller。`declaration_bytes` 必须 exact bytes，1..8MiB；先核 size/SHA 再 UTF8 JSON decode，拒绝 duplicate JSON key、NaN/Infinity。原 core 保留自身完整 native 和 canonical 上限。

所有普通失败统一为新 `ValueError("pi-wheel-source")`，cause/context 清除，不修改 caller／依赖异常；控制类 BaseException 保持原对象。不得输出输入、URL 或 byte 正文。返回值不与输入共享可变对象。

## Source record

声明记录 exact 字段为 `kind, package, version, url, wheel_filename, archive_digest, size, license_files`；locked 记录再加 `vendor_path`，禁止其它字段，包括 resources、format、target、platform、archive_member、resolved、integrity、license_sources、build_record、source_path 或 commit。轮子不进入 npm 的 resources 或 asset 的单文件安装接口。

| 字段 | 规则 |
|---|---|
| kind | literal `wheel` |
| package | canonical lowercase ASCII 名称，`[a-z0-9]+(?:-[a-z0-9]+)*`，1..96 bytes |
| version | 1..3 个 dot 分隔的 canonical 十进制分量，各0..99999999，无前导0（单独0允许），总长1..64 bytes；与既有 wheel row 的稳定版本域一致，不用 npm 三段 VERSION |
| wheel_filename | 单个 ASCII basename，1..256 bytes；exact `package.replace('-', '_')+'-'+version+'-'+python+'-'+abi+'-'+platform+'.whl'`，无 build 段；三个 tag 部分均 `[a-z0-9_]+(?:\.[a-z0-9_]+)*`。完整 tags 与目标兼容仍由原 bundle core 检查 |
| archive_digest | 64 lowercase hex |
| size | native int1..2097152 |
| url | strict UTF8 字符串，1..4096 bytes，无 control/空白；标准 urlsplit 的 HTTPS、无 user/password/query/fragment/port，最后 pathname basename 等于 wheel_filename。hostname 仅用离线 ASCII DNS 语法：至少两个label、每label1..63字节、首末ASCII alnum且中间仅alnum/hyphen，总长<=253，无空label/trailingdot；任意大小写合法，只对 urlsplit.hostname 小写值作检查，不重写原URL。拒绝 ipaddress.ip_address 可解析的IP，最终label至少有一个ASCII字母，排除纯数字末label/IP简写歧义。不做DNS/IDNA/publicsuffix查询。拒绝反斜线、百分号编码、`.`／`..` 路径分量和空 pathname 分量（开头 `/` 除外）。域名/URL本身不证明 public网络可达、publisher或不可变来源 |
| license_files | nonempty sorted unique native list<=16；每个 safe ASCII 相对路径<=512 bytes，位于 exact `<package_escaped>-<version>.dist-info/licenses/` 下，非空尾部，无空/`.`/`..` 分量、反斜线、control/空白；正式 Full 的原成员对应随后核查，禁止旁包 license overlay |
| vendor_path | locked 时 exact `vendor/wheels/`+archive_digest+`/`+wheel_filename；声明时禁止 |

Identity 为 SHA256(canonical projection)，canonical 使用 stdlib `json.dumps(sort_keys=True,ensure_ascii=False,separators=(',', ':'),allow_nan=False)` UTF8 无换行。Projection exact 字段 `kind, package, version, wheel_filename, archive_digest, size, license_files`；URL 与 vendor 定位不入共享 projection，但必须先合法，原 manifest/source/ref 全文 identity 仍会检测其变化。此函数不自行修改 source_identity 旧分支；未来只为 wheel 增加显式分支，不改变旧合法投影。

## Piece reference 与全局通用配对

Piece 的 `python_bundle` 若存在，exact 对象为：

```json
{
  "schema_version": 1,
  "source": "agents/pi/runtime/durable-python-bundle.json",
  "path": "runtime/durable-python-bundle.json",
  "sha256": "<64 lowercase hex of original JSON bytes>",
  "size": 44149
}
```

size native int1..8388608；schema_version native int1。固定正文不要求展示格式 canonical，锁住原字节 SHA/size；内部 canonical declaration_digest 仍由 bundle core 定义，两者不能混用。来源／安装路径固定，不接受 overlay/path 参数。

`source_ids` 必须 native unique list<=4096、每 ID为原 safe-id ASCII域。sources 外层 native dict<=4096、key为原 safe-id域；每个来源记录必须 native dict，kind为 native str；本 API 只完整检查 wheel，不能为其它种类签发 grammar 通过。所有 wheel source key 必须 exact `durable-python-`+package；当前有限集合固定七名 attrs/jsonschema/jsonschema-specifications/pyyaml/referencing/rpds-py/typing-extensions。已有不含 wheel/ref 的合法 Base 或 Full 保持可接受，此 API不强制全仓库必须已实现 Durable。

Base 一律无 python_bundle，无所选 wheel IDs，无该固定 runtime source 或 target；整锁可有别的 Full 使用的公共 wheel 记录，这不导致 Base 读正文或导入 core。Full 若选择任何 wheel，必须恰好选七条，七名齐全且不重复 package；必须有引用与恰好一条匹配的固定 runtime_file。Full 有引用也必须满足这七条，不能只有 JSON 无档案来源。没有 ref 时也禁止该 runtime source/target；错 profile、部分集合、缺来源、错 ID/kind、混入 Base 全部拒绝。

Runtime rows 保持原 `copy` 接口：声明时 exact source/path/transform；locked 时再有 input_digest/digest/mode。本 API只完整检查与固定 source 或 target 有关的 rows（两者任一命中便必须整行匹配）；其余 rows仅 native dict及字符串 source/path，详细 grammar仍归原 runtime_files validator。locked匹配行的 input_digest与digest都等于ref.sha256，mode为native384，transform为literal copy；声明匹配行同样literal copy。runtime_files native list1..2048（沿用原现代上限），无重复固定匹配，不能拿其它 row 掩盖冲突。refs/source集合错误在任何正文 decode/core import前失败。

## 所选正文数据校验

`validate_selected_python_bundle` 对 piece/sources 取同一快照，按 literal pi-full、locked=True 检查引用；没有完整七档案/ref则拒绝。先完成ref/source集合、raw bytes size/SHA、UTF8、JSON重复key/非finite及native结构界检查，这些失败不得导入core。随后仅本API内部lazy import原公开 `validate_python_bundle_declaration` 并交它检查完整declaration，保持原profile/Target/成员/METADATA/WHEEL/依赖规则及caps；合法JSON的core声明语义失败允许此时已导入core，仍返回固定新错误，不另镜像实现core。随后逐 wheel row exact 比对来源ID、name/package、version、wheel_filename、archive_sha256/archive_digest、archive_size/size；来源 license_files 等于按 `row.dist_info+'/licenses/'+metadata.license_files` 推导后排序的完整集合，且原 core 已保证这些 member存在。返回已 decode 的 detached native JSON，不返回 plan、raw archive 或能力。API不检测 file物理来源或 archive字节；调用者后续仍须由原持有来源读取七 bytes并交现有 stage 全量preflight。

## 原 caller 下一包的必须接线

1. Schema：仅现代v2新增 exact source/ref形状，v1禁止wheel/ref；旧branch逐字/等价保留。wholelock只检查小型shape/引用/identity，Base不读取正文。现代 read_inputs显式 wheel分支，不能要求build recipe/resources。
2. Generator／resolution：预构建 bytes按固定size/hash保留到专门vendor path，不build_archive、不npm pack。npm dependency map、resources及 node_modules 对应只允许 npm/local/git；resolution中的file引用集合也只来自 npm/local/git，防wheel档案被 npm file引用。原 Base/legacy同输入结果保持；正式输入变更按原identity/recipe/binding规则重算。
3. Reader／installer：原 read_lock 全局通用来源/ref校验仍严格，selected Full才读取固定runtime正文和七vendor原bytes；不绕过recipe/runtime/许可证/binding。原 _sync只在正式source和私有stage成立后调用现有 stage组件；完整occupied_files由原所有producer和固定生成文件集合提供，不能信caller空list或plan。
4. Destinations／seal：wheel不声明npm/asset destination，固定bundle namespace必须计入全局冲突谓词；selected Full的物理inventory纳入原完整 seal/receipt。原 runtime_files.validate_files的supervisor扫描必须明确接受并检查这组producer文件，不把合法新目录当未知，也不能放宽为任意supervisor文件。尚未接线前，不允许带wheel的runtime被错误标ready。

以上 caller/schema行为本包只冻结需求，不写暂时绕过或假ready。本包默认验收新四API：合法声明/locked/sourceidentity、无wheel旧两profile、合法七row/ref/body与返回detach；unknown/错ref/错runtime行/各pairing漂移/非native/cycle/大容器/边界/错误上下文及control对象；cold模块及通用source/ref路径无IO/ZIP/coreimport，pre-core失败不导入core，selected合法JSON的core语义失败允许lazy import后拒绝，并与合法完整正文分别作对照。测试只用仓库自有合成wheel声明（可引用现有测试生成函数，禁止修改旧测试或读实际捕获wheel）；不启动宿主、不调用网络或模型、不导入新第三方bundle/native。完成新suite后只按具体受影响路径扩测，不重跑此前387/204或真实被动IO。

正式 Full owner/provider、installed origin、原 CPython/ABI、完整许可资格、source hold和独立寿命另有未完成工作。7/100、AUTO OFF和Recovery3待本组三场授权保持。
