# Full wheel 的正式锁来源路线

2026-10-07，root 根据 `durable-full-wheel-source-representation-static-review02` 的限定事实选择下一条表示路线。本稿只记录设计决定，不授权 schema、生成器、声明、正式锁或安装接线实施。私有 stage 组件正在闭合独立审查问题；数据编译和临时 IO 都不签发 Full 来源或运行权。

## 区分档案来源与安装映射

现代锁应新增专门的预构建 wheel 来源种类，拟名 `wheel`，保持 v1 不接受此种类。它表达固定发布档案的公共来源、原字节摘要、大小、版本及 vendor 定位；不能把 wheel 当 npm/local/git 包、单文件 raw asset、Node 档案或需要重新构建的 helper。现有七个固定发行物和有限 wheel 数据契约保持，不解析最新版本，不运行 pip/uv 或发行脚本，不改上游字节。

来源记录与 WheelRow 有不同职责。记录须有 exact 字段和大小界，并保留原包版本、固定 URL、文件名、archive SHA/size 与正式 vendor 路径；许可成员属于对应档案原成员，不能填一个不在发行物中的旁包正文。WheelRow 中的完整成员、METADATA/WHEEL/RECORD、目标与安装规则由独立固定声明承载。所选 Full 必须逐行对应来源记录的 ID、版本、档案名、SHA 与大小；公共数据自洽不能替代发布来源、许可、ABI 或实际安装资格。

## 让 Base 保持可选闭包之外

完整 WheelRow 正文不直接塞进所有 profile 共同解析的 manifest。拟采用 Full 切片中的小型锁定引用，指向该切片明确声明的固定自有 JSON 资源；来源记录与引用的通用 grammar、identity、全局 catalog/provider/reference 检查仍保持严格。该资源以原 runtime_files 的 copy 方式保留原字节，拟固定来源 `agents/pi/runtime/durable-python-bundle.json`、安装目标 `runtime/durable-python-bundle.json`。不能由 overlay、扩展 callback 或用户指定任意路径替代。

Base 切片不出现 wheel source_ids、bundle 引用或该 runtime_file，不读取其正文、不导入 wheel parser 或 Durable 可选模块。whole-lock 通用公共记录校验与 selected Full 的实际档案／声明语义检查须分开。Full 专用解释器只在原已选 Full 入口 lazy 调用；不能因整锁存在七个公共记录，就在 Base cold 路径解 ZIP 或读取可选正文。原 `read_lock` 的 recipe、shape、引用、binding、所选来源字节和 license 检查都不能因此跳过。

## 下一包需要冻结的实际接线

exact 声明／锁 source record 字段、种类分支、引用 schema、canonical/caps、声明 JSON 的来源与锁定摘要，以及四类原 generator/caller 的行为尚未冻结。须检查哪些循环生成 npm dependency map、哪些复制或核 vendor archive、哪些检查安装 destination 与完整 seal，逐项排除把 wheel 送进 npm 或 generic asset 安装通道。同一原输入的合法 Base／legacy 输出保持；正式声明内容变化的 identity／binding／context 按原规则重算，不因新增 Full 记录而绕过旧证据失效规则。合法 Full 声明与所选来源成对验证；unknown、缺引用、错 slice、ID／摘要／版本漂移及交叉混入必须拒绝。

产品 installer 仍先满足原正式 selection/source/stage 所有权和锁，再从原正式 vendor 取得固定字节，向 stage 组件提供内部声明与完整占用文件集合；小型引用、合法 JSON、PiLock 或组件返回 None 都没有来源工厂或初始化权限。完整外层 inventory、receipt 与 ready 由原 seal 发布路径处理，不能把 bundle inventory 当 ready。正式 Full provider／owner 角色、installed origin、原 CPython／ABI、source hold 和独立寿命保持各自资格边界。

下一设计核必须针对上述记录／引用和原四类循环给出具体 API、唯一写入范围及有效合法对照；之后才能实施。默认只用临时受管数据、自有合成 wheel、原断网／进程保护，不启动第三方宿主。正式7/100、AUTO OFF、未解决 proxy 包级MIT正文和 Recovery3待本组三场明确授权保持。
