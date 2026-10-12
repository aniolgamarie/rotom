# Durable controller 的封闭 Python 依赖路线

2026-10-07，root 基于两个限定静态报告补充 controller Python 来源和 installed origin 路线。本稿记录初始方向边界，路线方向随后已接受；各项资格仍须以对应实现和验收记录单列。原运行包、上游包、默认环境不变。

当前增量：共享 header／resolution／selection 数据校验已分别完成限定默认验收；[Python bundle 纯数据契约](durable-python-bundle-data-api.md)在原三P2修复273pass后，再修合法Dynamic误拒和Metadata2.4双许可约束，完整新套件一次387pass、稳定0新/openP1P2，25输入receipt `f43e4cf29f88c91d670ab30700668358149529ede2cfe7c999ad93deff290fff`。同七原档案及同declaration数据编译inner0、163files／40dirs／25rules8active17inactive，13输入receipt `c18ae514b853d1226adbf6c6c0545281a5f1ad70e4d8fdfdab559a0055758af2`闭合此前f3243数据失败并保留历史；不是实际安装／import／ABI资格。[私有stage组件](durable-python-bundle-stage.md)两NEW默认组件已闭合：无关既有大小写别名P2原源2fail/3pass→修后5pass，受影响27pass，完整一次204pass/18.30s；稳定增量0新/openP1P2，32输入receipt `f62dee9e792ee77e2daa5fe54da0b1545bbd72ec255da142e5fdc3e96ace5538`，原199测试字节不动、五新增，初始失败分别保留。七原档案被动临时IO材料正在准备，没有实际hook或产品caller。[正式wheel锁方向](durable-wheel-lock-direction.md)已有限设计核，exactsource/ref/schema/API与四类生成/安装循环仍待冻。实际 Full 声明／安装／controller 来源、原 interpreter／ABI／加载、source hold与独立寿命仍未实现或资格化；无 upstream 源码修改。以下“下一包”文字保留原路线与尚未完成边界，组件或数据通过不能把这些项自动升级。

后续已验收七固定档案的临时被动IO，21输入receipt `1bd87e9d95564214a40e4489d929ef62bdeb8748bcd07050b2c8106ccf319f73`：inner0，163原成员加canonical inventory共164文件、40目录，原字节逐项读回与c18 plan一致。首次旧cache预检失败原样保留，修后仅复制三份自有模块原字节到全新私人目录，标准import且无默认cache；第三方输出不进入import path。此结果补齐组件实际档案可写性，仍不是Full产品安装、真实controller、ABI或原来源持有资格。正式source/ref与原调用链接线继续独立实施。

## 选择和边界

保留现有严格 schema/source/binding/selection 校验的语义，通过新的 Full-only、固定发行物、完整 seal 的 Python 依赖闭包供独立 controller 使用。不另写一个省略现有不变量的“差不多”验证器，也不把通用 `uv.lock` 或 `PiLock` 数据对象当 installed 来源资格。

controller 仍使用原受管 manager 同一实际且已资格化的 CPython 安装，固定 `-I -S -B`。第三方库来自本次正式 Full 声明的独立 sealed bundle，不从 manager 的虚拟环境、用户 site、PATH、环境变量或临时下载目录借包；缺包、资源、原安装资格或 Full 源绑定即零 Durable launch。库不是新的 Python interpreter，也不改变原安装的 loader/stdlib/extension 资格前提。

Python 的 [isolated 参数](https://docs.python.org/3.11/using/cmdline.html#cmdoption-I) 排除脚本目录和用户 site，并忽略 Python 环境变量；[`-S`](https://docs.python.org/3.11/using/cmdline.html#cmdoption-S) 禁用 site 及其路径处理。公开 `sys.path` 接口允许自有入口选择固定的已核 source 目录。这支持下面的路线推断，文档当次为 3.11.17，不代替本机 3.11.11 的行为证据。

## 发行物与导入

通用 uv.lock 只作为精确版本与 artifact 候选来源。当前所选 slice 已确认 jsonschema、referencing 及传递依赖，且原现代 validation invoked 路径需要 PyYAML；Jinja2／其他包是否还需加入仍由最终 controller 的完整 eager/invoked 闭包决定，不把 pytest/dev 包或整个 uv 环境自动加入 Full。锁中的 rpds-py 和 PyYAML 有平台/ABI wheel；原七档案的成员、hash、资源与许可元数据已有被动记录，不以这些记录或 filename tag 宣称 native／许可充分性／publisher／actual loading 兼容。精确数据规则及固定 flat 映射见新的纯数据契约，正式 Full source producer与资格仍须另包冻结。

正式声明须显式列定轮子及目标集合，安装仅消费已核本地 archive；产品启动不运行 pip/uv、不访问网络或现场解析“最新兼容版本”。原 wheel 及所选上游文件字节不打补丁。独立安装映射和完整文件清单包括 `.dist-info`、许可、schema/resource 和 native extension，不靠只复制几个 `.py`。wheel 格式及安装映射以 [PyPA 的发行物规范](https://packaging.python.org/en/latest/specifications/binary-distribution-format/) 为参考；RECORD 的摘要只是包内一致性，不能替代固定发布 artifact 的来源与全字节核验。具体 archive cap、成员规则、spread/RECORD 策略未冻，不能先调用通用 extract 放宽已有禁 link/上限。

固定入口预留 fd3 后，先只用已资格化 stdlib 验证自身完整 source、两个固定导入根和 bundle 清单，再设置公开 import path。自有 source 根与第三方根只能相对自己已核 sealed entry/role 得到；不接受 caller path、callback、模块对象或“已验证”布尔。不能 import `site`/执行 `.pth`/sitecustomize，不扫描机器 site，不添加未知目录或外来 hook，不通过修改上游/stdlib loader 或 package 全局变量补齐来源。

入口必须先排除自有 sealed source/bundle 中残留 `.pyc` 和未知模块来源，并以固定 import 顺序、名字和真实 loaded-source/extension/resource 核验关闭 shadowing 与 package-data 缺失边界；`-B` 仅防写新 pyc，不能据它假定旧 pyc 不会被读取。原 CPython/stdlib 的既有 bytecode 则属于原安装完整资格，不能由“own bundle 无 pyc”外推已核。具体名字集合与 importer 资格须跟真实闭包冻结。此处不承诺文件核验和加载间面对任意同 UID 修改内存/上游文件仍原子安全，也不把 imported.__file__ 单独当执行字节证明。

## 严格 validator 的接线

当前 `pi_capabilities→schema.ConfigError`、pi_catalog 和 pi_dependencies 都在 import 时需要 jsonschema/referencing；当前 modern 声明缺 pi_capabilities 和 `ROOT/schemas/pi-lock.schema.json`，selected slice/profile/receipt 又缺完整 metadata。应一次补齐实际 Full 闭包的 own code、固定 formal schema、package data 与第三方依赖，而不是只补 origin JSON 后就宣称成功。

安装端保留原 repository `read_lock`、recipe 重算、archive/build/license/runtime source 校验。controller 不把 installed 树伪装成完整 repository，也不 monkey patch `ROOT` 或构造假的 repository/Workspace 去调用 read_lock。下一设计包须提供新的仓库自有公开 installed-origin API；可从原 read_lock 提取共享严格的纯 metadata/resolution/source/binding 校验，并保留原 repository IO 层的所有校验和有效旧输出。新接口不是公开 capability factory，合法 metadata、hash、PiLock 或选定状态不能授予初始化。

installed collector 还必须实际只读核完整固定 origin、selected pair、sealed inventory、角色、原 runtime/instance/current 关联和原 issuer/channel；不能以 metadata 自检代替来源。recipe 原始输入在安装端验证，child 针对实际 installed 源完整核验，不从未分发的原 repo 重新编造 recipe。哪些原校验归公共 metadata kernel、哪些只属于完整 repo 构建、哪些由真实 installed 文件映射替代，必须逐条有明确证据和实现接口，未解决项保持不可用。私有 generation/auth/本地 endpoint 仍不进入 shared source_identity 或摘要。

所有新增 package/source/generated 声明只在 exact Full owner contract 内。Base 不解析或导入 Full Python bundle、Full resolver、Durable 角色和可选数据；未选代码保持 lazy，不扩大当前已核 Base 调用闭包。不因可选 Durable 依赖缺失阻塞健康的普通编辑，也不绕过整包 damaged-runtime gate。

## 验收与未完成项

下一包先冻结实际公开 API、唯一写入范围和所选发行物成员，再实施。默认临时 fixture 检查完整闭包、缺 resource/native/tag/unknown/重复成员/shadow/旧 pyc 拒绝、许可与原字节、strict metadata 不变量与原有效结果一致，以及 Base 的零可选访问；严格校验必须有真实合法对照，不用固定拒绝 fake 掩盖无实现。默认仅使用当前仓库测试依赖和自有 fake，不加载新捕获的第三方 bundle/native 扩展或实际 controller/宿主。

实际 wheel import、native extension、原 CPython loading、fd3/pipe/controller/current/principal/持有链组合另准备公开源和原生资格材料；旧 Harness8/FD6/SDK/RPC 授权不覆盖新增组合。安装组件或 serialization 默认通过不记原生/产品通过。前端正常退出后的后台运行与重连、manager 崩溃后的原来源保护、全部维护入口的保护仍由独立持有链包冻结，不能以新增 bundle 消掉这些问题。formal7/100、产品 gate 与 strict metering 前 AUTO OFF 保持。
