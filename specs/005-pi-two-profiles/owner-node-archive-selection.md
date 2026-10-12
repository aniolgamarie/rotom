# Node 官方归档的独立字节选择接口

2026-10-07，root 为已观察的官方archive与通用extractor不兼容问题冻结独立纯组件。保持 `pi_assets.py` 原通用1024条／禁link的行为；先实现单独字节选择器，不修改资产格式、schema、recipe、lock、Full选择或factory。固定资产接线随后单独接入；本组件返回校验后的原bytes，不提供 executable路径／fd／安装或启动权限。

## 材料与实际格式

[官方v24.14.0校验表](https://nodejs.org/download/release/v24.14.0/SHASUMS256.txt) 与下载archive全文SHA一致。root源材料7输入receipt `43f2822b9d05f30de0534712e6715a82e5f445bbd8bd8fe1b11fdfef3c521034`、scout独立被动核对6输入receipt `7619d52e77c4e7be91973461f9f531a80306304d37f69747db61de1d07866b1c`；未验OpenPGP、不签发正式license／factory／native资格。当前所选原Node 122466960B SHA `e237a2839d0cbdc9a9a2adda1a184afc0f5b20306ffbe923af5686550472d8a8`，原LICENSE156926B SHA `4573185d56580da2b890ba34a85a409257640f1c5632eade4300137266194d18`；不编译、改写或修补原binary。

root另次被动header观察：5627个logical member＝4559 regular、1065目录、3 symlinks；949个GNU longname，所读最长name134，无pax。当前GNU longname的offset_data−offset为1536，普通为512；last member data padded end197963776，其后观察到全零padding。此处不是第二次Node执行／安装，不代表任意future release都同格式；新身份必须重新验证。

## 两文件与公开API

唯一可写 `src/agentcfg/pi_node_archive.py`、`tests/test_pi_node_archive.py`。其余 source、pi_assets通用guard、schema／recipe／lock、已接受window／codec mapping／owner及SDK材料保持原字节。root是文档／state唯一writer。独立设计审查、root具体授权后才实施；不据本文开始native、下载更多文件或运行Node。

`capture_node_archive_selection(value)` 仅接受exact dict的六字段：schema=1、release、platform、archive_sha256、binary_sha256、license_sha256。先tuple捕获原items，核所有key exact str再hash／比较；所有值exact native types。release为ASCII canonical `vMAJOR.MINOR.PATCH`，各component无leading zero、0..2^31−1，全文≤32char，无prerelease／控制字；platform仅linux-x86_64；三个SHA均lowercase hex64。返回原 `NodeArchiveSelection` 冻结slots独立元数据。public constructor不当权限；selection对象字段被反射改写或未初始化时下一函数仍全字段重验。

`select_node_archive(raw, selection)`：raw先exact bytes核验且非空、≤128MiB，再selection原class核验先于slots读取／独立重捕获；raw SHA必须等于snapshot archive_sha256。只经自有／stdlib字节操作，禁止传stream／callback／路径／URL／fd；不读取文件、网络、账号、proc，不启动任何process或作cleanup IO。

使用原zlib gzip解压，max_length=256MiB+1；超过256MiB、不完整、非gzip／CRC错误、unconsumed_tail或unused_data失败，不拼接第二gzip／接受raw tail。随后只用原stdlib tarfile解析自有 BytesIO，最多8192个logical member。只支持已观察的普通header和单GNU longname格式：首logical offset为0；各member.offset须等于前一个padded data end；offset_data−offset只能512或1536。512时该raw header type必须等于member.type；1536时首raw header type必须GNU longname `L`且最后regular/dir/sym header type等于member.type。额外metadata/header间隙不跳过；pax_headers非空、sparse、negative size、超范围data/offset或unsupported member type失败。此有限格式不承诺接受所有合法tar变体。

member.name exact str≤256、无backslash，拒绝C0（codepoint<32）、C1（0x7F..0x9F）及surrogate（0xD800..0xDFFF）；路径components不含空、`.`、`..`。仅核字面值，不normalize；此规则不改变原binary／LICENSE bytes，不提供UTF-8／许可正文语义验证。所有名字唯一，必须是release推导的 `node-<release>-linux-x64` 根目录，或以该根加slash为prefix。根member若有必须是dir；不创建或跟随任何archive目录/link，regular body只核范围，除下面二成员不保存内容。所有logical entry处理后，padded end之后至少1024bytes且全部为零；非零tail／第二tar／未见header失败。tarfile处理GNU扩展的内部实现不是Node／Agent私有API，不对它打补丁；选器不再造通用tar框架。

仅允许三条symlink，并要求本次archive完整观察到以下exact set（没有hardlinks／额外links）：`<root>/bin/npm`→`../lib/node_modules/npm/bin/npm-cli.js`；`<root>/bin/npx`→`../lib/node_modules/npm/bin/npx-cli.js`；`<root>/bin/corepack`→`../lib/node_modules/corepack/dist/corepack.js`。只检查字面元数据，全部不跟随／加载／安装／执行；未来发行物改变这组规则时必须新设计／审查和身份，不静默放宽。member类型只支持regular `0`、dir `5`、上述sym `2`。

只返回 `<root>/bin/node` 和 `<root>/LICENSE`：二者必须唯一regular、分别mode755／644，binary64bytes..128MiB、license1byte..1MiB。直接按已验证offset/size复制自有expanded bytes，不调用extractall，不以link/extractfile查找替代项；binary经现有自有 `binary_platform` 静态ELF头验证为linux-x86_64，二成员SHA必须精确等snapshot。保留原bytes，不标准化LICENSE／重写binary。返回原 `NodeArchiveFiles` 冻结slots，含selection、binary、license；两payload字段repr=False。不提供generic摘要日志／serialization；成功返回对象与模块cache不保留整个expanded archive或unselected内容，不承诺Python异常traceback的locals普遍不可访问。固定异常的args／cause／context要求仍按下段执行。writer_lock_verified/database_allowed/can_take_over均恒False。

供应hash、像Node的ELF、合法version／archive basename并不证明official publisher、真实Node版本或未改动运行包。本函数只能证明whole raw与所供应snapshot一致及选择/格式/members关系；正式manager必须从原已验证lock／source role取得selection和下载字节，关联toolchains版本／官方provenance／许可来源，source/object／授权／native三层仍分离。pure fixture可合成ELF字节，不宣称是Node。

所有拒绝返回新固定 `DependencyError("Pi Node发行物无效")`，实际cause/context为空，foreign异常不修改、不回传URL/成员/metadata正文；异常handler退出后抛固定错误，不接业务rollback/retry。既有binary_platform错误亦映射此固定错误。source起点为正常import的原自有/stdlib实现，不声称防任意全局monkeypatch／Python私有反射，不能据返回值开库。

## 默认与实际材料复核

默认固定 `/data/1/weixiaoxian.wxx/dev_tool/rotom/.venv/bin/python -m pytest -q tests/test_pi_node_archive.py tests/test_pi_assets.py`，保留原conftest临时HOME／断网／fakeprocessguard；不跑Node／SDK／SQL／services／proc／signal／lock。若实际旧asset测试文件名不存在，先静态找出正确文件名由root调整，禁止猜测扩大范围。

先写tests，记录缺模块仅未实现（collection error不算行为red）。fixture使用stdlib合成小gzip/tar，独立计算三个hash，不复制选择器作为oracle；常规错误独立修复和保留log。验证plain/GNU长名正例、exact declaration/class/type-first hooks0／反射字段重验、全文／binary／license hash、prefix/name/type/link set/duplicate/mode/size、截断gzip/CRC/concat/rawtail、GNU layout／pax／sparse／tail／padding、member/expanded/archive上限和固定错误隐私。大上限使用自有模块更小fixture上限模拟（只能降低，不关闭guard），不在默认suite分配数百MiB／运行真实二进制。旧assets suite尤其证明原通用limit／links／未知format保持原行为。

source/tests稳定且root与不同executor复审后，可独立对已保存并归档的官方raw bytes调用自有纯选择器进行一次只读实际材料复核（不是Node／SDK／native执行、不开库不部署），比较上述真实二payloadbytes／SHA及source文件pins。该步骤由root另给固定命令并记录memory/shape界限，默认fake通过不自动当官方archive通过。未验签继续显示false；正式资产接线与实际Nodeexe／CLOEXEC／pidfd／privatepipe资格另包、另授权。
