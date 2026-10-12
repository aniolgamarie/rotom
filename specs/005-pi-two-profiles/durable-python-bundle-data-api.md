# Python bundle 的纯数据接口

2026-10-07，root 将已接受的七 wheel 元数据材料收敛为有限实现包。本稿冻结下面的精确数据契约，实施还须通过独立设计核；不能据此签发安装或启动资格。

当前合成默认组件已在三P2修复后以273pass及稳定增量审查验收。随后真实七档案数据编译失败，限域诊断确认七档案framing及十四个METADATA/WHEEL的声明size/hash匹配，首拒绝为PyYAML METADATA的`Dynamic: author`；完整payload/RECORD编译仍未通过。以下root补充冻结此新证据的最小规则修订，原失败不删除，不改上游字节。

## 本次实现范围

只新增 `src/agentcfg/pi_python_bundle.py` 与 `tests/test_pi_python_bundle.py`，使用 stdlib，提供声明数据校验、ZIP／元数据／RECORD／依赖关系编译为确定计划、inventory 数据校验。接口接收数据和 archive bytes；不读文件、环境、账号、网络，不写 stage，不设置 import path，不执行包，不产生安装或启动能力。

公开接口只有：

- `validate_python_bundle_declaration(declaration) -> None`
- `plan_python_bundle_install(declaration, artifact_bytes, *, occupied_files) -> dict`
- `validate_python_bundle_inventory(declaration, inventory) -> None`

声明内的 `profile_id`、`target`、占用文件和相互一致的 metadata 都是未受信任的数据。不另接收重复的 profile／target 参数。合成合法数据可以通过这些函数；真实 Full 安装器必须另从原固定来源读取并核实声明与全部 archive 字节，调用方提交的 hash 或 plan 不构成权限。

## 固定策略

首版 `flat-wheel-subset-v1` 保留原 archive 成员路径、全部字节和 RECORD；不支持 `.data` spread、entrypoint wrapper、字节码或包执行。原 archive 只保留在 vendor，不新增运行时 archive 副本。库固定为 `supervisor/python-bundle/site-packages`，inventory 固定为 `supervisor/python-bundle/inventory.json`；计划文件模式为 0600，目录为 0700，实际 ABI 与加载资格仍单列。

ZIP 只支持已观察到的 classic version 20、flags 0、stored/deflate；拒绝 descriptor、ZIP64、extra、comment 和未定义 framing。逐成员检查 local/central header 一致、范围与总量、精确解压长度、CRC、SHA256、deflate eof 和 trailing compressed data，不能仅依赖 ZipExtFile 的 CRC／size 检查。路径与成员规则同时拒绝未知、重复、case collision、特殊文件、link、危险路径、旧 pyc、`.pth`、sitecustomize/usercustomize；显式与隐式目录去重排序。

`occupied_files` 代表已占用的 **文件** 记录，不把共享父目录 `supervisor` 当成占用文件。新输出及固定 reserved prefix 与这些文件之间的相等、祖先、后代和大小写冲突均失败。计划仅返回 detached plain JSON 数据，完全不含 payload bytes／正文；没有需要展示或隐藏的 payload repr。返回值可以被调用方修改，但不得成为原安装器接受的权限对象；未来实际 writer 从自己已核来源重新编译和核验，不消费外来 plan。

依赖只支持已观察到的 bare／`>`／`>=` 稳定数字 release，以及 `extra == format/format-nongpl` 和 `python_version < 3.13`。保留原 Requires-Dist 的逐行 typed ledger 和 inactive extras；wheel 的 `python_version` 与 lock 的 `python_full_version` 原串和决策分别保存。未知语法失败，不导入 ambient packaging 或引入第八个 evaluator。目标数据只支持稳定 CPython 3.11／Linux x86_64 的有限兼容判断；tag、版本与数据一致不证明原 interpreter、glibc、native extension 或 publisher 来源资格。

三接口对普通异常只产生新的固定 `ValueError("pi-python-bundle")`，清理自身 cause/context，包括调用方已有异常上下文；不吞 `BaseException`。使用 exact native 类型、字段集合和上限，拒绝 bool 冒充 integer、surrogate／float／非有限值；不修改输入，返回结果与输入无可变引用共享，重复调用确定相等。错误的 Python 参数数量／关键字由普通 signature TypeError 处理，数据函数 body 不回显输入。

## 验证和实施门槛

下面精确字段、顺序、caps、metadata/header/typed ledger 和 inventory 契约先作独立设计核。唯一 writer 随后完成两文件与有意义的合成合法／错误对照；不读取当前捕获的原 wheel，不 import native 或第三方包，不运行宿主。

默认验收命令为原 Python 执行 `pytest -q tests/test_pi_python_bundle.py tests/test_pi_lock_header.py tests/test_pi_lock_resolution.py tests/test_pi_selection_data.py`，保持仓库原 offline／临时 HOME／owner guard。在已知 sandbox UID 环境不足时按既有授权使用 normal-owner，不改 guard，不把环境不足记成通过。受影响错误修复后只重跑有必要的范围；独立审查针对 writer STOP 后的稳定 diff。

本包不修改 profile／formal schema／正式 declaration／lock／vendor、实际 stage/source/Full collector/controller 或 source hold；实际写入 readback、来源身份、许可充分性、ABI／加载／原生与部署仍未验。formal 7/100、产品 gate false、strict metering 未验证前 AUTO OFF 保持。

## root 的精确补充

采用以下 18 个数据对象、全部 caps、required／nullable 字段、顺序和固定错误，不留本包字段选择。`license_expression` 与 `legacy_license` 分别 nullable，但不得同时非null，原字符串不相互改名；这是[Metadata 2.4的互斥约束](https://packaging.python.org/en/latest/specifications/core-metadata/#license)，不引入SPDX或法律判断。`entry_points` 只允许下面已知 jsonschema 原文本或 null。

已构建wheel中的`Dynamic`是信息标记，值已在wheel构建时计算；按[PEP 643](https://peps.python.org/pep-0643/#specification)不由它触发安装时构建或补全。仅在METADATA接受多次单行`Dynamic`；值按ASCII大小写不敏感精确匹配下列2.4字段名：`Author`、`Author-email`、`Classifier`、`Description`、`Description-Content-Type`、`Download-URL`、`Home-page`、`Keywords`、`License`、`License-Expression`、`License-File`、`Maintainer`、`Maintainer-email`、`Obsoletes-Dist`、`Platform`、`Project-URL`、`Provides-Dist`、`Provides-Extra`、`Requires-Dist`、`Requires-External`、`Requires-Python`、`Summary`、`Supported-Platform`。重复同名信息标记可接受；每行仍受原header caps约束。不接受空值、折行、带空白或逗号的值、未知字段名、自身`Dynamic`、`Name`／`Version`／`Metadata-Version`或2.5新增Import字段；WHEEL中的Dynamic也失败。无新的声明字段或输出列表，原字节由Member.sha256和RECORD绑定；即便标记Requires-Dist／Requires-Python／License，实际字段仍须完全匹配声明并走原规则，缺失／错误／未知依赖不被豁免。其它原forbidden headers及所有caps、图、文件与错误边界保留。

Dynamic沿用所有header原有的`:[ \t]*`分隔符；冒号后的这些分隔空白不属于captured value，因此`:author`、`: author`、`:  author`和冒号后的tab均可解析。上文“不接受空白”针对captured value的内部或末尾空白；不新增一空格专用header规则。

本增量仅由唯一writer修改同两文件，先保存前像并用自有完整七wheel fixture验证旧源拒绝合法Dynamic、旧源接受双许可字段的真实反例，再最小修复、相关范围和完整新套件验证。不得读取或导入真实档案；root在稳定diff审查后另以新输出目录重跑同一真实档案纯数据编译。此前273与新轮次分列，旧三suite无新影响时不重复。

允许的顶级包路径按 **所属 wheel** 核验：jsonschema→jsonschema；jsonschema-specifications→jsonschema_specifications；referencing→referencing；attrs→attr／attrs；typing-extensions→typing_extensions.py；rpds-py→rpds；pyyaml→_yaml／yaml。每 row 另允许自己的 exact dist_info；不能把其他 row 的允许根当成自己的根。模块型顶级 `typing_extensions.py` 必须是文件，不能成为目录。RECORD.jws／RECORD.p7s 禁止；原七档案中未观察到，不增加签名解释。

Unix external attributes 只允许低 16 位为 0（普通文件）或 0／0x10（目录），高 16 位只含 0777 permissions 与 regular／directory／无 type；不允许 suid／sgid／sticky、link 或 special 类型，trailing slash 与目录 type／DOS directory 位保持一致。internal attributes 只允许 0 或 ASCII text bit 1。这些是新解析策略，仍须未来实际七档案的数据编译证明，不借当前 header 事实签通过。

occupied 文件集合自身须满足无大小写、相等、文件祖先／后代冲突；不接受目录记录。reserved prefix 规则独立于具体映射文件，因此该 prefix 下未知 sibling 文件也失败。路径冲突检查使用有界集合／排序／逐级 parent 关系，避免按最大两集合做逐对乘积扫描。目录、origin、对象和 canonical 大小上限在构造过程中执行。

typed wheel 规则是按原串解析生成的数据；lock 原 `python_full_version` 只保留在独立来源报告，不向本包声明增加未定义字段，也不作为可用 wheel marker。声明校验可在没有 archive 的情况下检查这套图的数据一致性；planner 随后用真实 archive 内容再核 metadata／RECORD。不宣称数据 API 独立验证了原 uv.lock 或 publisher。

每 wheel 的 expanded tag 必须至少有一项兼容 Target：`py3-none-any` 对本契约 CPython 3.11 兼容；`cp311-cp311-P` 只有 `P` 属于 `target.platform_tags` 才兼容。filename／WHEEL 仍必须完整集合一致，多个合法 platform alternative 中存在一项即可，不要求全部匹配。declaration／inventory 共享这条规则，测试须有合法交集及无交集负对照。这修复独立设计 review01 的唯一 P2；不推断实际 glibc／native 来源资格。

每 row 的 member 数据必须包含自己的 exact METADATA／WHEEL／RECORD，以及每个声明 License-File 对应的 exact license member。entry_points 非 null 时其 exact member 必须存在；null 时不得包含 entry_points.txt。显式目录不能替代这些文件；无需 archive 也能拒绝这些声明内部缺项。Requires-Dist 的 extra marker 必须引用所属 row 已列定的 Provides-Extra；原串与原顺序保持。这是元数据／完整成员检查的明确实施规则，不以 caller 声明充当真实 archive 读取证明。

稳定代码 review01 的三项 P2 必须按最小修订闭合：raw metadata Name 允许首末 ASCII alnum、中间 ASCII alnum／`-_.` 的连续 runs，然后 lower／collapse；Requires-Dist head 仍保持本包已观察的窄 grammar。artifact_bytes 必须先检查 exact native dict 和长度恰为 7，才逐 key 类型检查及集合化。generic native walk 对 integer 先限制在 signed 64-bit 范围，全部合法字段原有更小上限仍照用；不借环境 int-to-string 设置保证分配边界，恶意 inventory 大整数须在 canonical encoder 前拒绝。这些修复不新增来源或权限接口，须有合法变体、上下越界及无 callback／无 bad-inventory 编码的配对测试。

原契约报告两次数据组装／生成错误（成员列表误作 map、OS argument limit，另一次 JS ReferenceError）均发生在报告写入前，未写仓库、未执行包或测试；保留记录。有限 local header 读取属于前已授权的任务补充，后续确认没有倒记为先行批准。精确 local 读取时刻未保留，post-read clock／pins 是 00:33:46.591644Z，首末一致 hash 不构成原子来源证明。

## 精确字段与解析契约

以下为 root 采用的契约；与上面的 root 补充冲突时以上面的精确补充为准。

## Constants

```json
{
  "schema_version": 1,
  "layout": "flat-wheel-subset-v1",
  "profile_id": "pi-full",
  "library_root": "supervisor/python-bundle/site-packages",
  "inventory_path": "supervisor/python-bundle/inventory.json",
  "bundle_parent": "supervisor/python-bundle",
  "file_mode": 384,
  "directory_mode": 448,
  "roots": [
    "jsonschema",
    "pyyaml"
  ],
  "extras": [],
  "names": [
    "attrs",
    "jsonschema",
    "jsonschema-specifications",
    "pyyaml",
    "referencing",
    "rpds-py",
    "typing-extensions"
  ],
  "flags": 0,
  "extract_version": 20,
  "create_version": 20,
  "create_system": 3,
  "compression_methods": [
    0,
    8
  ],
  "target_platform_tags": [
    "manylinux2014_x86_64",
    "manylinux_2_17_x86_64",
    "manylinux_2_28_x86_64"
  ]
}
```

## Caps

```json
{
  "archive_bytes": 2097152,
  "archive_set_bytes": 8388608,
  "member_expanded_bytes": 16777216,
  "wheel_expanded_bytes": 67108864,
  "wheel_entries": 20000,
  "compression_ratio": 200,
  "set_entries": 4096,
  "set_expanded_bytes": 16777216,
  "metadata_member_bytes": 1048576,
  "metadata_wheel_total_bytes": 2097152,
  "archive_member_path_bytes": 512,
  "target_path_bytes": 1024,
  "name_bytes": 128,
  "version_bytes": 64,
  "wheel_filename_bytes": 256,
  "source_id_bytes": 96,
  "requirement_raw_bytes": 512,
  "requires_dist_per_wheel": 64,
  "requires_dist_set": 256,
  "license_files_per_wheel": 16,
  "occupied_files": 16384,
  "canonical_declaration_bytes": 8388608,
  "canonical_plan_or_inventory_bytes": 16777216,
  "data_depth": 16,
  "data_nodes": 100000,
  "planned_directories": 16384,
  "path_components": 64,
  "header_lines": 2048,
  "header_line_bytes": 4096
}
```

全部18类型exact native dict/unknownfields拒绝，所有字段required/nullable明确，int拒bool/float，container拒foreign/cycles，str拒surrogates。

## Declaration

| Field | Type / constraint |
|---|---|
| schema_version | native int exactly1 |
| layout | literal flat-wheel-subset-v1 |
| profile_id | literal pi-full (data label, no selector authority) |
| library_root | literal supervisor/python-bundle/site-packages |
| inventory_path | literal supervisor/python-bundle/inventory.json |
| file_mode | native int384 (0o600) |
| directory_mode | native int448 (0o700) |
| roots | native list exactly [jsonschema,pyyaml] |
| extras | native empty list |
| target | Target |
| wheels | native list exactly7 WheelRows, unique and sorted by canonical name; exact names C.names |

## Target

| Field | Type / constraint |
|---|---|
| implementation | literal cpython |
| python_release | native list exactly [3,11,patch], native int patch0..999999; no prerelease/dev/local form |
| abi | literal cp311 |
| sys_platform | literal linux |
| machine | literal x86_64 |
| platform_tags | native nonempty sorted unique list, subset of C.target_platform_tags; compatibility data only |

## WheelRow

| Field | Type / constraint |
|---|---|
| source_id | literal durable-python- plus canonical name |
| name | one of seven C.names |
| version | ASCII numeric stable release, 1..3 dot-separated canonical decimal components, each<=99999999; <=64 bytes |
| wheel_filename | original ASCII single basename <=256; distribution/version/python/abi/platform components, no build; exact version, normalized distribution=name, expanded filename tag set equals wheel.tags |
| archive_size | native int1..2MiB |
| archive_sha256 | 64 lowercase hex |
| dist_info | exact escaped canonical name (hyphen->underscore) + '-' + version + '.dist-info' |
| metadata | MetadataHeaders |
| wheel | WheelHeaders |
| entry_points | null or KnownEntryPoints |
| members | sorted unique list Member, nonempty; regular files only, total counts/sizes caps; exact complete ZIP file set |
| explicit_directories | sorted unique native list of safe relative paths without trailing slash; exact explicit ZIP directory entries after stripping one slash |

## MetadataHeaders

| Field | Type / constraint |
|---|---|
| metadata_version | literal2.4 |
| name | raw observed Name scalar<=128; normalize lower/-_. collapse to wheelrow.name |
| version | raw scalar exactly wheelrow.version |
| requires_python | raw observed >= numeric stable release string <=64; required exactly one header |
| requires_dist | original ordered native list of raw strings<=512 each, <=64/wheel; parsed by narrow rules, no row removed |
| provides_extra | ordered unique native list of format/format-nongpl only; preserve original; empty except observed jsonschema pair |
| license_expression | null or raw scalar<=256, no SPDX evaluator/qualification |
| legacy_license | null or raw scalar<=256; PyYAML MIT retained, not renamed |
| license_files | ordered nonempty unique list of safe paths<=512, <=16; exact raw License-File values and matching dist_info/licenses/<path> member |

## WheelHeaders

| Field | Type / constraint |
|---|---|
| wheel_version | literal1.0 |
| root_is_purelib | raw literal true or false string |
| tags | ordered unique list of expanded tags; py3-none-any or cp311-cp311-<allowedplatform>; complete actual Tag headers |
| build | null only; actual Build header must be absent |

## KnownEntryPoints

| Field | Type / constraint |
|---|---|
| member | exact <dist_info>/entry_points.txt |
| text | exact [console_scripts]\njsonschema = jsonschema.cli:main\n (51 UTF8 bytes); only jsonschema allowed; must exist in members and bytes match |

## Member

| Field | Type / constraint |
|---|---|
| path | safe ASCII relative path<=512, no trailing slash; first component within known package root or exact dist_info |
| size | native int0..16MiB |
| sha256 | 64 lowercase hex |
| role | derived enum: license if dist_info/licenses/, else metadata if dist_info/, else native if .so, else python if .py/.pyi, else resource |

## OccupiedFile

| Field | Type / constraint |
|---|---|
| kind | literal file |
| path | safe relative complete runtime target<=1024; no trailing slash; original producer filters directories, not authority |

## RequirementRule

| Field | Type / constraint |
|---|---|
| source_id | row source_id |
| ordinal | native int original Requires-Dist index |
| raw | exact original string |
| name | normalized dependency name |
| operator | null, > or >= |
| raw_release | null or exact original version spelling |
| release | null or native int list1..3 normalized numerical components |
| marker | null or Marker |
| active | native bool computed for target/extras |
| selected_version | raw selected version if active else null |
| satisfied | true if active else null |

## Marker

| Field | Type / constraint |
|---|---|
| variable | extra or python_version |
| operator | == for extra; < for python_version |
| value | format/format-nongpl for extra; literal3.13 for python_version |

## PythonRequirement

| Field | Type / constraint |
|---|---|
| source_id | row source_id |
| raw | exact Requires-Python |
| operator | literal >= |
| raw_release | exact version spelling |
| release | native int list1..3 |
| satisfied | literal true for target compatibility data |

## PlannedFile

| Field | Type / constraint |
|---|---|
| source_id | row source_id |
| member | Member.path |
| target | library_root+'/'+Member.path |
| size | Member.size |
| sha256 | Member.sha256 |
| mode | 384 |
| role | Member.role |

## DirectoryOrigin

| Field | Type / constraint |
|---|---|
| source_id | row source_id |
| member | safe relative directory path |
| explicit | native bool true iff listed in row.explicit_directories |

## PlannedDirectory

| Field | Type / constraint |
|---|---|
| target | safe target under bundle_parent |
| mode | 448 |
| kind | bundle-root/library-root/wheel-parent |
| origins | sorted unique list DirectoryOrigin; empty for two fixed roots; deduplicate cross-wheel targets |

## ArchiveSummary

| Field | Type / constraint |
|---|---|
| source_id | row source_id |
| name | row name |
| version | row version |
| archive_size | row archive_size |
| archive_sha256 | row hash |
| entry_count | members+explicit_dirs |
| expanded_bytes | sum members size |

## Plan

| Field | Type / constraint |
|---|---|
| schema_version | 1 |
| declaration_digest | sha256 canonical Declaration |
| plan_digest | sha256 canonical Plan without plan_digest |
| layout | flat-wheel-subset-v1 |
| profile_id | pi-full |
| target | detached Target |
| library_root | fixed literal |
| inventory_path | fixed literal |
| file_mode | 384 |
| directory_mode | 448 |
| roots | detached fixed roots |
| extras | empty list |
| archives | ArchiveSummary list sorted source_id |
| files | PlannedFile sorted target |
| directories | PlannedDirectory sorted target |
| requirements | RequirementRule list ordered source_id then ordinal |
| python_requirements | PythonRequirement ordered source_id |
| stats | Stats |
| inventory_template | Inventory only; not authority/readback proof. No plan_digest inside Inventory, no self hash; Plan digest covers inventory_template. |

## Stats

| Field | Type / constraint |
|---|---|
| raw_bytes | sum archive_size |
| file_bytes | sum Member.size |
| archive_entries | members+explicit_dirs sum |
| file_count | files count |
| directory_count | planned bundle dirs count |

## Inventory

| Field | Type / constraint |
|---|---|
| schema_version | 1 |
| declaration_digest | canonical Declaration hash |
| layout | flat-wheel-subset-v1 |
| profile_id | pi-full |
| target | detached target |
| library_root | fixed literal |
| inventory_path | fixed literal |
| file_mode | 384 |
| directory_mode | 448 |
| files | same exact PlannedFile ordered list (claimed observed data, no IO proof) |
| directories | same exact PlannedDirectory ordered list |
| requirements | same exact requirement decision list |
| python_requirements | same exact python requirement list |
| stats | same Stats |

## Metadata matching

Use bounded UTF8strict raw email-style headers. Required relevant singletons exactly one: Metadata-Version/Name/Version/Requires-Python, Wheel-Version/Root-Is-Purelib. License-Expression/License each at most one and mutually exclusive; Build absent. Operative fields single-line no foldedvalue; repeatedRequires-Dist/License-File/Provides-Extra/Tag ordered complete lists. Dynamic follows the exact root supplement above, informational in METADATA only; it never exempts a declared field from matching. Unknown nonoperative standardheaders/body preserved as original bytes under Member.sha256, not emitted or interpreted. Legacy/foreign requirement/import/build headers such as Requires-External/Requires/Provides/Obsoletes/Provides-Dist/Obsoletes-Dist/Import-Name/Import-Namespace fail v1; no general standard evaluator. Entry_points only knownjsonschema literal51 bytes or absent; no script generation.

## Paths

ASCIIsafe [A-Za-z0-9_.-]+ slashseparated components, no empty/dot/dotdot/leading/trailing slash/backslash/NUL/control/colon; comparecasefolded forduplicate/collisions. Forbid .data components/.pth/pyc/pyo/__pycache__/sitecustomize/usercustomize atanycase. Exact permitted package top roots: jsonschema,jsonschema_specifications,referencing,attr+attrs,typing_extensions.py,rpds,_yaml+yaml plus each row's own dist_info. No stdlib-shadowing foreigntoproot.

## Grammar

- distribution_version: ASCII [0-9]+(?:\.[0-9]+){0,2}, canonical decimal each; artifact version must equal raw metadata+filename, no prerelease/dev/local/epoch/wildcard.
- requirement_head: observed bare name or name(>=|>)numeric-release; release1..3 components with leading-zero spelling permitted in constraint (2023.03.6), retained raw and numericalized.
- requires_python: only >= numeric release, no marker
- markers: extra == 'format'; extra == 'format-nongpl'; python_version < '3.13'
- evaluation: extras=[] =>17observed extra rows inactive. python_version uses [3,11] < [3,13] =>active. Active numeric comparisons zero-pad release tuples; bare active name merely selected membership. requires_python uses full stable target. All active edges must be present and satisfy; no optional implicit fallback.
- lock_marker: uv.lock python_full_version<'3.13' retained as separate original evidence; evaluate full stable [3,11,patch] versus [3,13,0], not rewritten into wheel marker or accepted as arbitrary new wheel variable.
- counts: Actual selected current rows total25:8active17inactive; contract example preserves every raw row. A synthetic declaration may have self-consistent in-grammar rows for seven names, without an actual artifact allowlist; source authentication is not done here.
- unsupported: OR/AND, direct URLs, extras-on-dependency, ~= == != < <= for dependency heads, prerelease/local/dev/epoch/wildcards or any new marker variable/value =>fixed error + root review; do not import packaging/eighthwheel.

## ZIP framing

- scope: Classic single-disk ZIP2.0 subset only for current seven candidate data; not arbitrary wheel support.
- fixed: central+local general flags exactly0 (whitelist allowed bitmask0), create_system3/create_version20/extract_version20, method0stored or8rawdeflate, ASCII filename; no extra/comment. No data descriptor flag3 or encryption/UTF8/unknownbits. Reject ZIP64 and multidisk, comments, prepended/selfextracting/trailing data or unsupported headers/versions.
- framing: Own bounded classic framing checks use only fixed EOCD22/CD46/local30 byte layouts; no genericZIP interpreter/private zipfile APIs. EOCD single disk and exact count/CDoffset/CDsize, no FFFF/FFFFFFFF sentinels or ZIP64 locator/end records; classic central region complete, exactly counted, no extra/comment. Local header/name, flags/method/version/CRC/compressed+uncompressed sizes agree exactly with central; boundaries in raw bytes, no overlapping/aliased/gapped ranges, all local records then CD then EOCD. Filename raw bytes ASCII and exact local/central match. Validate counts/caps before allocating ZipInfo lists or payloads. Future broader ZIP support needs separate contract. Strict rawdeflate payload framing is a proposed next implementation requirement only; current report did not decode/reread payload to test eof/trailing-data. Actual central/local header facts are separately recorded and do not pass this new framing check.
- streaming: Method0 compressed_size==file_size and bounded payload exactlen. Method8 raw zlib.decompressobj(-MAX_WBITS) over exactly bounded compressed range: cap each chunk/output allocation and aggregate; require complete eof, unused_data==b'', no final unconsumed_tail, exact compressed-range consumption, no trailing compressed stream/data. Do not use ZipExtFile CRC/size alone as proof. Check final exact file_size, incremental CRC32 equals local+central and SHA256 equals Member+RECORD. Metadata capture only <=1MiB each/2MiB wheel; all other content hashed incrementally then discarded; do not retain/return payload.
- directories: Explicit directory names path+'/' with zero file_size/CRC and zero decompressed content; stored0zero payload or strict empty deflate8 as declared headers. Included in archive-entry caps; excluded RECORD regularfile set. No directory hash needed, but exact central explicit directory set matches declaration.
- types: Reject links/special/inconsistent Unix type or name trailing-slash, unsupported external attributes. Regularfiles permit original regular/no-type convention only if safe; finalplanned permissions fixed600/700, not copied fromarchive.

## RECORD

- csv: UTF8 strict bounded CSV, exactly3columns/row, no duplicate/unsafe path, exact regular member set; original csv order need not be sorted but bytes/hash unchanged.
- hash: nonself sha256=<canonical URLsafe-base64 withoutpadding>, decoded length32; canonical decimal size equals streamed bytes/Member.size; no blank digest/size except own RECORD both blank. No signature-extra support; jws/p7s absent current, unknown requiresreview.
- identity: RECORD is itself a Member with independent sha256 in declaration/plan. No recursive self hash; .dist-info raw RECORD bytes do not change. It is internal consistency, not publisher signature or authority.

## Occupied files

- input: native list of exact OccupiedFile records; <=16384, unique sorted paths. Directory record/kind directory or trailing slash is invalid input; future producer must filter real directories before collecting occupied_files.
- comparison: Compare complete proposed file targets (all163mapped files plus fixed generatedinventory_path) with occupied file paths by casefolded exact/ancestor/descendant component relation. Compare proposed directory paths to occupied files only for file-blocking-directory cases; do not treat proposed or existing directories as occupied files. Shared legitimate supervisor directory is allowed because it is not supplied as a file.
- namespace: Because bundle_parent is exclusively reserved for this producer, any occupied file under that prefix is a mixed-producer conflict even if sibling to mappedfiles; this separate prefix-policy uses only file targets, never invents a directory-as-file. Unknown/proposed file-directory and interwheel collisions rejected.
- authority: Caller may supply empty/self-consistent list: result remains data. Actual original fixed installer must later provide truthful complete file targets plus its stage/source ownership; this package neither probes nor proves that.

## Canonical/determinism

- scheme: UTF8 json.dumps(sort_keys=True, ensure_ascii=False, separators=(',',':'), allow_nan=False) after exact native type/cap checks; no floats/surrogates/cycles/depth>16/unknown fields.
- arrays: wheels/name, members/path, explicitdirs/path, platformtags/path sorted and unique; raw Requires-Dist/License-File/Provides-Extra/WHEELTag original order retained and checked. Planfiles/dirs targets sorted, archives/source_id sorted, rules source_id+ordinal sorted.
- digests: declaration_digest=SHA256(canonical(declaration)); inventory has no plan_digest/self hash. plan_digest=SHA256(canonical(plan_without_plan_digest)), includes inventory_template. External full-runtime inventory may later hash inventory file, outside this package.
- determinism: same native declaration+artifact bytes+occupied_files =>deep-equal detached plainJSON plan. Inputs unchanged. No caches/IO/capability/objectreceiver; plan contains no bytes/buffers/content and no repr/log payload.

## Error boundary

- public_fixed: ValueError('pi-python-bundle') for ordinary validation/planning errors in documented calls, __cause__/__context__ None even with caller active exception; catch only Exception, new own ValueError clear+bare-reraise.
- BaseException: KeyboardInterrupt/SystemExit propagate; never mutate/clear original caller/input error; no rawargs/doc/ZIPname/metadata/input/foreign chain/log.
- signature: Python argument binding TypeError for wrong arity/unsupported keyword is separate from body data-validation boundary; no catch-all callback interface.
- plan_payload: No byte payload returned in Plan/Inventory at all; no logging; stdlib internal buffers stay private to bounded processing.

## Directory mapping

Union every explicitdir + every proper file/explicitdir parent, dedup/sort, prefixlibrary_root; add library_root and bundle_parent only. Explicit4 alreadyamong38. Fixed rootsorigins=[], kindbundle/library; mappeddirsorigins source_id/member/explicit flag. No supervisor chmod/write/authority.
Enforce <=16384 directories while adding each parent/origin, not after building an unbounded union; <=64path components and512byte member path.
163files+4explicitdirs；explicit/implicit去重38包内dirs，加固定libraryroot/bundleparent共40。共享supervisor不是occupiedfile/计划chmod对象。原163memberinventory仅引用accepted材料，完整38目录在JSON。700dirs/600files只mode数据，不证明physical权限/ABI。

## Validation order

1. Exact native container/types, depth/count/string/mode/literal/declaration graph+Target syntax; canonical declaration cap; no archive/file IO.
2. OccupiedFile shape and complete declared file/directory/namespace collisions; directories are not occupiedfiles; failure before payload decoding.
3. artifact_bytes exact native dict keys7 source_ids and native bytes values; raw caps/setcaps then actual archive len/SHA256 matches declaration (data coherence only).
4. Classic EOCD/CD/local fixed headers/caps/flags0/version20/method0or8/name/CRC/sizes/ranges/noZIP64/descriptor/comment/extra. Match complete declared member+explicitdir sets.
5. Strict bounded stored/rawdeflate decode; all members exactsize/CRC/SHA, metadata capture bounded, otherpayloaddiscard; RECORD validation uses real streamed bytes. No extraction.
6. METADATA/WHEEL/known entrypoint operative singleton/list raw values match declaration; whole raw member hashes preserve nonoperative headers/body. Relevant duplicate/folded/defect/unsupported operational header fails.
7. Requires-Python, Requires-Dist grammar and deterministic target/extras closure; preserve raw25 current25decisions and separate lockmarker evidence; missingactive refs or unmet releases fail.
8. Construct detached normalized files/dirs/rules/stats/Inventory template; canonical sizes and plan_digest. No payload/context/authority; return only on full data success.
9. Inventory validator revalidates Declaration, derives same data template without ZIP or IO, checks exact fields/count/order/digests/modes/rules/files/dirs/stats. Equality is claimed-data consistency only, not actual readback.

## Synthetic tests (not run)

- Construct seven synthetic wheelbytes with same valid rawName/version/header/namespace forms; publicfake .py/license/schema/native text; complete METADATA/WHEEL/knownentrypoint, compute actualsha perfile and RECORD-selfblank, then zipclassicflags0/version20/noextras/comments, hashes ofwholebytearchives, self-consistent Declaration. Do not hardcode realartifacthashes as authority.
- Legal stored0 and deflate8 pairs, pure and native-tag rows, Unicode metadata body but ASCIIfilenames, preserved harmless nonoperative standardheader, exactsource rawName variants typing_extensions/PyYAML; outputs identical bytefree data and input unchanged.
- Full real-current declaration example built from accepted163file inventory is data illustration, not executable fixture or registeredcandidate. Synthetic may use fewer files but every declared/actual file and requiredmetadata/license must match; fake qualification not minted.
- Corruptlocalflags/name/CRC/sizes whilecentral staysvalid, unknowncentralflag, descriptor bit, ZIP64sentinel/extra/locator, comments/preamble/suffix/overlap/gap, methodunsupported =>fixederror. Keep artifacthash updated in syntheticdecl so test truly exercises framing, not always early digest reject.
- Rawdeflate truncated/noeof/unused trailing compressed bytes/additional stream/oversizedoutput, method0size mismatch/CRC/hash/RECORD faults with lawful framing =>reject; legitimate counterpart passes. Caps boundary and +1, streaming allocation assertion.
- METADATA singleton duplicates/folding/invalidUTF8/unknownoperative requirement, WHEELtagsets/Name/version/rootPure mismatch, unknownentrypoint or.data/.pth/sitecustomize/oldpyc; literalknownentrypoint kept but no wrappers/no imports.
- 25current requirement ledger8active17inactive, numeric2023.03.6rawpreserved, python_version3.11true and lockfullmarkerkeptseparate; missing typing_extensions or incorrectversion rejects. UnknownPEPgrammar no packaging/site import.
- Sharedsupervisor directory excluded fromoccupiedfiles succeeds; genuinely occupiedfile atsupervisor blocks descendants; exact/ancestor/descendant/case and mixedbundleprefixfile conflicts fail. Directorykind passed asoccupiedfile rejectsinput rather than masquerading physicalfile.
- Inventory template exact pass and each mode/hash/size/target/directoryorigin/rule/stats/digest/count/order/unknownfield tamper fail; selfconsistent fabricatedinventory stillreturnsdataonly, no readback/source claim.
- All3public API ordinaryerrors underoutersecretcause/contextclear; BaseException propagates; nofilesystem/process/environment/project/thirdpartyimports orlogging. Deep walk Plan/Inventory finds no bytes/buffers/payload strings orauthority/ready/capability fields.
- No tests run now; nextwriteronly newpi_python_bundle.py/test_pi_python_bundle.py. Actualstageinstaller/source/Fullselector/current/issuer/native/roles/sys.path/locks/schema/runtimearchives unchanged and unqualified.
- At limits, directory-union and object/canonical caps enforced incrementally before unbounded construction; not merely checked after allocating plan.
Rootselects dedicatedsynthetic plus header/resolution/selection regressions; default doesnot read existingrawwheels or executethirdparty. Coherent syntheticdatadoesnot mintauthority.


依据报告：`/tmp/pi-durable-python-bundle-data-contract-review01.md`（c2645cd581253e4d97ff183889d648ba9a91eefb8388ab1546ee0f221e1b52f8，30414B）及 companion JSON。原成员 inventory 和 typed 当前原串只引用已接受材料，未在本包重复下载、执行或复制 raw archives。
