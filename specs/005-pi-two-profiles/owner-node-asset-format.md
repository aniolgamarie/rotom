# 固定 Node 资产的显式格式接线候选

2026-10-07，root 基于四源 schema／声明证据（6输入receipt `07f682b314838a98d3d3e5629aa624ab992d53459adbf8c6482e66fb4d3d4aea`）及原 `pi_assets.py` 冻结下一包设计候选。纯选择器仍在实施，本候选尚未审查／授权代码。只增加显式格式支持，暂不新增真实source row、许可正文文件、recipe／正式lock、角色声明或factory启用。正式默认仍是旧组合；source、安装、原生资格分开完成。

## 新格式与原来源

source 的 `kind=asset`、`format=node.tar.gz` 是唯一分派条件。新增闭合 `node_archive` 字段采用 [纯选择器](owner-node-archive-selection.md) 的原六字段snapshot；不把Node归档交给通用extractor，不改变其1024条／禁link规则。此格式只支持当前Linux x86_64；不增加zip或隐式识别basename／ELF的方法。

source 必需且仅允许九字段 `kind, format, url, platform, archive_digest, archive_member, target, license_files, node_archive`，仅允许再加可选 `vendor_path`。先exact dict／key native type，再独立捕获；顶层值也须exact native types。不得有 `build_record`、`size`、npm／git字段或额外属性。`node_archive` 由原capture函数校验、独立冻结，再与以下派生值交叉比较：

- `platform` 恒为 `linux-x86_64`，与snapshot一致；`archive_digest` 与snapshot.archive_sha256一致。
- `url` 精确为 `https://nodejs.org/download/release/<release>/node-<release>-linux-x64.tar.gz`；没有query、fragment、userinfo、自定义源或镜像回退。
- `archive_member` 精确为 `node-<release>-linux-x64/bin/node`；`target` 恒为 `bin/pi-node`。
- `license_files` 是exact list且恰有一个exact str：`agents/pi/build/licenses/node-<release>/LICENSE`。该路径来源的原bytes必须与所选archive LICENSE全文一致，不能用概括文本／估计MIT正文替代Node发行物内完整许可与通知。
- 若有 `vendor_path`，精确为 `vendor/node-<release>-linux-x64-<archive_sha256>.tar.gz`，只在调用方已选择的lock family下读取；缺失／坏摘要不借另一家族或网络补齐。

这些字段保证声明内一致，不独立证明official publisher／Node实际版本／许可法律范围。hash与供应版本仍非授权；未来真实source row仅在已存官方字节通过纯选择器后另行固定，OpenPGP未验证保持false。此候选不修改既有Node工具链声明或探针runtime。

## 闭合 schema 与版本关联

`schemas/pi-lock.schema.json` source全局properties仅增加 `node_archive` 与format enum项；新metadata用内联闭合object，不使用会令现有局部source validator丢失根定义的 `$ref`。asset条件分支增加 `node.tar.gz` 的明确required／const／禁size/build_record约束；全局条件同时要求 `node_archive` 只能存在于asset+node.tar.gz，且新format必须有该字段。npm/git/local及旧raw/tar分支均不能夹带它；未知字段继续失败。原分支结构不重写或统一。

JSON Schema只校验字面shape和常量；release component的int31范围、推导url/member/license路径、摘要相等由专用validator复核，不能假定Schema证明跨字段相等。对selected Node source，原 `validate_asset_platforms(piece, manifest)` 还须比对原 `manifest.toolchains.node` 的exact str与snapshot.release；与已锁实际toolchain版本不一致即失败，不以解出的ELF宣称版本。原平台完整覆盖与target碰撞规则保持，Linux source不自动让多平台slice通过。原read_lock对共享manifest全部sources及全部profile_slices作schema／metadata／关联校验，包括Node snapshot；这不构成Node正文或可执行资格。Base未选Node时零可选访问限于不读其归档／许可正文、不调用选择器、不创建Node／Durable IO；不承诺共享metadata零校验。

当前 `read_inputs` 通过source schema和asset validator，`resolve_lock` 对asset source作dict复制；vendor预校验仅验证普通asset归档大小／SHA。因此此包不宣称锁生成已经执行Node归档选择或原生资格。未来正式发布步骤必须补齐真实Node成员复核；不能据此候选生成正式modern manifest。

## 安装切点

原 `install_assets` 在明确sync的暂存Tree内、选定platform/family下安装。source属于新format时，独立捕获完整source并核toolchain，作为原metadata解析结果传递；不要把selection dataclass当authority或给client新路径参数。Node分支在触及下载／归档／许可写入之前完成声明与版本检查；未选新format不调用它。

Node下载采用独立opener：只请求已捕获的精确官方URL，关闭ambient proxy，不附账号认证；redirect仅允许同一精确URL，跨host／path／query／scheme变化均固定拒绝。旧open_download／HTTPSRedirects行为不改；精确初始URL本身不证明最终origin，本分支明确检查redirect而不宣称OpenPGP验签。有界临时归档流程与完整archive_digest核验沿用原限额；vendor仍从原家族读，缺失零fallback。Node仅将已核完整raw bytes交给原纯选择器；不能调用通用extract_binary／verify_archive、执行Node或增加host补丁。读取repo许可原文时保留原1MiB上限并核与selector.license字节完全一致。所有选择／许可正文检查完成后，才发布原selector.binary到固定 `bin/pi-node`，文件mode700；原LICENSE作为原 `licenses/<source_id>/0-LICENSE` mode600分发。成员mode755／644验证属于归档元数据，安装权限按原资产惯例私有化；不重编译／改写正文。

发布前检查固定binary与LICENSE目标不存在，不覆盖已有stage产物。binary和license两次写入不是跨文件事务：后项IO失败可留下未ready的暂存文件，不能签发installed receipt／激活／启动。继续由现有完整stage/seal/activate边界处理，不引入私自重试、补偿或删除未知活动runtime的cleanup。Tree物理身份和原子replace保持现有语义，不声称抵抗任意同UID恶意写入或kernel原子exec。

拒绝新格式元数据／选择／许可／安装时不回传URL、source payload或许可正文。专用边界输出固定 `DependencyError("Pi Node资产无效")`，实际cause/context为空；先退出foreign exception handler再抛，不修改foreign异常。旧格式错误语义与现有helpers不改。全局patch／私有反射不在该纯输入保证范围；新分支不能赋予writer_lock_verified/database_allowed/can_take_over。

## 下一包与验收候选

拟唯一writer范围：新增 `src/agentcfg/pi_node_asset.py`、`tests/test_pi_node_asset.py`，最小修改 `src/agentcfg/pi_assets.py` 和 `schemas/pi-lock.schema.json`。纯selector、codec、window、owner及其tests均保持已接受字节；agents声明／recipe／locks／license源不改。具体helper名字、原分支插入位置、错误映射与固定命令仍在独立审查后由root冻结，本文件不授权实现。

默认只使用小合成gzip/tar、合成ELF、原Tree临时HOME和内存fake download；原conftest断网／fakeprocess守卫保留。验证source/schema闭合与cross-field/type/hook、toolchain mismatch、未选零可选访问、同原family/vendor零fallback、原binary/LICENSE精确安装/mode/nlink、两种格式不混用、repo许可缺失／坏全文、target/license冲突与写入后故障不能产出ready；旧asset/builtasset/dependency schema相关回归由root固定最小同次集合。真实archive材料纯复核另记，默认fixtures不当上游Node／native／Full通过。不同executor仅在稳定diff后最终审查。
