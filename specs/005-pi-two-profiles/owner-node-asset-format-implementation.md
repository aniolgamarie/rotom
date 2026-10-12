# Node 资产格式的四文件实现包候选

2026-10-07，root将 [格式设计](owner-node-asset-format.md) 的具体API、原分支插入点和默认命令冻结为可审查包。格式稿 `8ae6813b753c07b3e4ebc47ad6971a9f7d10ccb22ca040e6ceb63bc8820f123f`／7692B 已两段增量复核；纯selector35输入receipt `237be3655cce3cd8018cb4b223e168cb07a86f23cceacc9e92c6a01b307d202f` 已接受默认98（新74／原24）。本包候选尚未授权实现；真实官方字节选择复核与此包分层记录，正式source／lock／factory仍不启用。

## 写入范围与接口

唯一writer可写四文件：新增 `src/agentcfg/pi_node_asset.py`、`tests/test_pi_node_asset.py`，最小修改原 `src/agentcfg/pi_assets.py` 和 `schemas/pi-lock.schema.json`。禁止修改已接受selector/source/tests、原asset/builtasset/dependency/vendor测试、conftest、声明／recipe／locks／license文件和启动角色。root保有spec／plan／state写入权。

`capture_node_asset(source)`：按格式稿exact九字段加可选vendor_path、先捕获tuple(items)／核所有key exact str／再独立dict，全字段native／闭合集合和推导值复核；node_archive调用原capture接口，license_files先exact list／元素exact str再比较。返回自有冻结slots `NodeAssetReference(selection, url, vendor_path, license_file)`，vendor_path未声明时为None；不是授权、安装／执行／来源资格，无secret解析或IO。公开constructor不是能力。除受信manager内部工具链／安装调用外，不把该引用交给client作为launch参数。

`validate_node_asset_toolchain(source, toolchains)`：重新capture原source；toolchains必须exact dict，tuple捕获后key exact str，再独立dict核恰 `node,npm,bun` 三字段及exact str值，node精确等于snapshot.release。返回该次捕获引用；不执行任何版本命令。此函数不验证npm／bun实际运行版本，原完整锁／安装toolchain路径仍负责那些检查。

`open_node_download(reference)`：仅接受原NodeAssetReference类，selection原class先于其slots读取，再从捕获字段重捕获／复核selection和推导url、vendor_path、license_file；未初始化／反射坏字段失败。使用原stdlib urllib的 `ProxyHandler({})`、自有 `NodeHTTPSRedirects(expected_url)`、固定User-Agent／60s timeout；Request只含已捕获精确官方URL。redirect_request先URL exact str并精确等expected_url才交原父类，不读取环境proxy／账号、不附Authorization。不修改stdlib或旧opener。未知全局monkeypatch／私有反射不在来源保证内；继承原urllib有限redirect次数，不做业务重试。默认opener测试仅fake opener/request/redirect对象，不能发真实网络。

`install_node_asset(checkout, target, source_id, source, toolchains, layout)`：仅由原install_assets已打开的原Tree与dependency_layout返回对象调用，source_id来自原闭合锁source key；此内部适配入口不提供client路径／fd／callback／shell。函数先source_id exact str且匹配原schema `[a-z][a-z0-9_-]{0,63}`，再capture与toolchain关联，才读Node归档／许可。原Tree、已验证lock与原layout的来源属于可信manager职责；调用方自造字符串／dataclass不签发资格。

Node归档下载／vendor读取在本函数独立完成，压缩byte上限128MiB、临时原file不跨family；用原stdlibTemporaryFile(dir=target.root)（不建可执行目标），逐块≤1MiB读，whole SHA一致后seek/read完整raw给原selector。vendor路径仅 `layout.lock_directory + '/' + reference.vendor_path`；缺失立即失败，不能再调用网络opener。新模块自己的MAX_ARCHIVE为128MiB，selector原limit仍独立生效；测试只降低本模块limit，不改变原资产guard。release／摘要／许可／目标关系不通过basename猜测。

从原checkout读reference.license_file，原1MiB上限；exact bytes且与selector.license全文相等。检查固定 `bin/pi-node` 和 `licenses/<source_id>/0-LICENSE` 两目标缺失后，原target.replace("bin/pi-node", binary, mode=0o700, expected=None)、target.write_new("licenses/<source_id>/0-LICENSE", license)；write_new自身使用原600模式，不传其不存在的mode参数。所有选择／许可校验先于首次目标写入；没有extractall、Node执行、SDK／Db／signal／lock。后项IO失败不删除未知文件、不发ready／activate；暂存残留与跨文件非事务限制沿格式稿执行。

capture／toolchain／opener／install各新边界拒绝均新造固定 `DependencyError('Pi Node资产无效')`，实际context/cause为空，foreign异常不修改、不携正文；退出handler后抛固定错误，并处理ambient caller exception的上下文切点。默认source仍使用工程双引号／2空格；上面的单引号只是文中示意。repr不含binary／LICENSE payload；reference只含公开来源meta而非凭据。

## 原代码插入点

1. validate_asset仅在显式format=node.tar.gz时lazy import/capture并return；其他format原bytes逻辑保留。lazy import避免selector从pi_assets取得binary_platform时出现循环import。未知format不因此进入Node。
2. validate_asset_platforms仍按原source_ids过滤kind asset；显式Node行先lazy调用validate_node_asset_toolchain(source, manifest.toolchains)，再进入原target／platform collision／coverage逻辑。全局read_lock仍校验全部metadata和profile关联；未选profile正文/selector/Node/Durable IO零访问与格式稿一致。
3. install_assets保留先dependency_layout校验、原平台/source_ids选择、原Tree打开和旧try结构。for内显式Node分支lazy调用新install_node_asset(checkout,target,key,source,manifest.toolchains,layout)，成功后continue；原build/raw/tar/download/extract/许可路径不重写。传toolchains值的读取必须在新Node固定错误边界内（如使用manifest原dict的安全get，缺失传None交helper拒绝），不能让缺toolchain先抛KeyError绕过新错误语义。旧节点未选时不调用Nodehelper或读取Node许可正文。

Schema按格式稿增加明确内联properties／enum／双向约束和asset分支，不新建通用format registry。Node字段进入任何旧raw/tar/npm/git/local source均失败；built_record不得与Node共存；局部source schema截取仍可校验此字段。原recipe/lock身份含完整source，变更不会热换现有runtime或任务。

## 同次默认验收与历史

固定 `/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -m pytest -q tests/test_pi_node_asset.py tests/test_pi_assets.py tests/test_pi_built_assets.py tests/test_pi_dependencies.py tests/test_pi_vendor.py`。保留原临时HOME／offline／fakeprocess守卫，必要时原正常owner执行，不弱化UID/PID守卫。scope仅默认fixture；不得import／运行Pi/Codex/公开SDK／实际Node或真实账号网络。不得改旧tests以适应新实现。

先tests，缺新module的collection error仅未实现，不虚称behavior red。首个完整实现／接线之前可保留真实原integration/schema对新fixtures拒绝的阶段结果；不为追求红色计数故意改oracle或导入路径。fixture独立使用小stdlibgzip/tar、合成ELF与原字节hash；所有声明引用fake source／license均在临时checkout，不写真实声明。snapshot/source type/key/hooks、推导字段、摘要／toolchain关联、schema全部old-kind与新字段交叉负例、未选零正文/opener/selector、opener redirect exact与no proxy/auth、vendor同family／缺失零fallback、两目标原bytes/mode/nlink、所有license mismatch/目标冲突前零目标写入、后项IO故障不ready／不cleanup、固定error及foreign不改均有独立断言。

后项IO不ready只证明本函数没有资格产出、caller传播失败及暂存状态；不冒充全sync原子性或真实seal/activate故障恢复通过。原asset/builtasset/dependencies/vendor全套在同次执行验证共有schema／平台／family／输入和旧format行为，passes分新旧记录、不累计历史。实际退出码、elapsed、全部log和首末selected pins在/tmp排他600保存；对四文件稳定diff由root与不同executor最终审查。真实Node材料／原生／正式Full角色与资格继续另包，不因本模块默认通过而勾选整体任务。
