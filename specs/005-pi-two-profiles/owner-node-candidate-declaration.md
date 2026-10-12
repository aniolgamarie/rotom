# 固定 Node 的公共候选来源声明

2026-10-07，root 根据已接受的官方来源、原字节暂存、Node 专用 schema／parser／身份接线及候选声明静态证据，决定先将 Node 纳入现代 Base 的 session-runtime 来源闭包。Node 是运行 Pi 的公共工具链，不是 Durable 能力。未来 Full 要显式引用相同资产并另声明 owner 角色，不以 Base 的 Node 行或候选验收取得 owner／bootstrap／数据库资格。本包不创建不存在的 Full selector，不更新正式 manifest，也不改变已部署的 legacy 包。

## 已接受输入与边界

官方来源材料收据为 `43f2822b9d05f30de0534712e6715a82e5f445bbd8bd8fe1b11fdfef3c521034`。现代 stage 一次原字节比较和私有 source-only 导入收据为 `ce8d1e3c02514ef777476a47b689a44eb847c58cb0b1f19561d4549a9fa5960e`。LICENSE 独立公共资源复制收据为 `e20596dc98a3e7e44a67c5353cb046620d0e94c17f9dfcffdacd9ed97344f6f2`，Node identity 稳定默认191及独立审查收据为 `12e48393892352682712bc863100cf0e16dc7bfa5c036a0b310860bd6d75d844`。这些证据分别覆盖来源／字节／纯身份，不作 OpenPGP、法律范围、运行版本或 kernel exec 证明。

当前 `agents/pi/dependencies-modern.json` 只声明 Base；catalog 与 provider 均为 candidate，verified_host_versions 是空数组。已有 `resolve_lock` 不把 asset 放入 npm package dependencies，保持这一行为。资产行不增加 package recipe，不修改通用 extractor 或 asset 规则。本包只允许唯一 writer 修改该 JSON 和新增 `tests/test_pi_node_candidate_declaration.py`；root 管理设计／计划／状态。配方、所有源模块、schema、旧测试、真实 vendor、正式 lock、account／deployment 与 gate 不在 writer 范围内。

## exact 来源及闭包变更

新增来源 ID 固定为 `pi-node-linux-x86_64`，exact 十字段如下，不增加 version、size、build_record、resources、Node argv 或任意路径参数：

```json
{
  "kind": "asset",
  "format": "node.tar.gz",
  "url": "https://nodejs.org/download/release/v24.14.0/node-v24.14.0-linux-x64.tar.gz",
  "platform": "linux-x86_64",
  "archive_digest": "dbf5b8665dec15e59e6359a517fefb47b23fdb9152d8def975b9bca3dfc6d355",
  "archive_member": "node-v24.14.0-linux-x64/bin/node",
  "target": "bin/pi-node",
  "license_files": ["agents/pi/build/licenses/node-v24.14.0/LICENSE"],
  "vendor_path": "vendor/node-v24.14.0-linux-x64-dbf5b8665dec15e59e6359a517fefb47b23fdb9152d8def975b9bca3dfc6d355.tar.gz",
  "node_archive": {
    "schema": 1,
    "release": "v24.14.0",
    "platform": "linux-x86_64",
    "archive_sha256": "dbf5b8665dec15e59e6359a517fefb47b23fdb9152d8def975b9bca3dfc6d355",
    "binary_sha256": "e237a2839d0cbdc9a9a2adda1a184afc0f5b20306ffbe923af5686550472d8a8",
    "license_sha256": "4573185d56580da2b890ba34a85a409257640f1c5632eade4300137266194d18"
  }
}
```

同时且仅作以下关联变更，保留全部原行／顺序／未知字段失败规则：

- 在 Base 的 source_ids 和 catalog 的 session-runtime.source_ids 末尾各加一次此 ID。
- catalog.source_profiles 新增此 ID，仅关联 `pi-base`。
- provider `pi-native-session-v1` 的 support_sources 末尾加 exact 三字段行：source_id 为此 ID，source_version 为 None，source_identity 为原七字段 Node projection 的摘要。
- catalog.revision、Base selection.revision、Base selection.source_revision 均从 1 改为 2；selection.state 保持 candidate，原 bindings 不改，全部 provider 的 verified/candidate host versions 不改。

source_identity 使用已接受的完整六项 Node metadata 投影；发布的值必须同时经独立构造 canonical JSON（sorted keys、原 digest separators/ensure_ascii 规则）计算核对，不从调用者 hash、文件名、本机 `node --version` 或临时 runtime 路径推断。当前 toolchains 三项完全不改，Node release 与固定工具链关联由已有 helper 校验。任何遗漏上述闭包关联必须被验证拒绝，不能只让 schema 合法就接受。

## vendor 与中间状态

候选声明只引用 locks/pi-modern 下的上述 exact vendor 路径。本包不复制大文件、不运行 resolve_lock、不下载或启动工具。原 archive 的后续自有缓存复制要独立冻结固定原来源／目标、目录身份、禁止覆盖、原字节首末 hash／目标读回和失败保留；不能用新增 JSON 行宣称 vendor 已存在或 installed。若目标缺失，原 asset 输入检查继续拒绝 lock 构建；不省略 vendor_path、不回退镜像或网络，也不放宽限制以掩盖缺失。正式锁仍要等完整依赖／许可范围、构建与 runtime 验收闭合。

## 默认验证与稳定接受

新测试加载唯一仓库候选 JSON 和已接受 LICENSE 的小字节；不读大 archive／Node binary、不调用 Node／npm／SDK／网络／实际 vendor 或 resolve_lock。检查 exact 原来源、schema 的 asset 分支、原公开 Node helper／toolchain／identity，以及 JSON 的全组闭包。独立期望使用固定官方 metadata 和七字段投影，不能调用被测函数生成期望。用自有纯虚构 PiLock metadata 和完整所选 resource/source closure 调用原公开 validate_manifest_bindings／validate_selection：剩余旧来源的 archive／integrity／树身份为虚构且与测试 provider 同步；Node 行及其 provider identity 保留真实候选值，不能把错误 Node 身份在 fixture 中重新计算为合法。合成 selection 保持 candidate，不能伪造 current／accepted／verified 或 installed receipt。

针对这一包，新增控制至少覆盖：来源缺失、profile 漏 Node、capability 不允许 Node、source_profiles 不关联 Base、provider 漏 Node、provider Node identity 或 source_version 错误、重复来源、revision 失配，以及仅修改 archive／binary／license digest 后原绑定失配。错误声明的 derived 字段要保持一致，避免将互不相关的 metadata 结构失败当成 identity 反例。测试仍在临时 HOME／默认 guards 内，无宿主 smoke。有效旧 metadata 的整体逆去新增行／数组项／revision 增量须逐字节恢复原 JSON，而不只比较一个缩减 dict。

先保存原声明及首末 pins，再对同一最终测试在原完整声明上取得真实 red；缺新文件的 collection error 只记未实现。修后只跑新 suite 与未改 capability_manifest／node_source_identity／profile_projection 的相关检查；结果按同次运行记录，不与历史191／196累加。源与测试写入完成后由 root 和独立 executor 审稳定 diff、逆还原、日志及输入 pins。若需修改 source 模块、扩大 source ownership、创建 Full／角色／manifest、跑工具或实际 vendor，交回 root 决策。本包不会勾完 T006／T012／T079，也不改变正式7/100／产品 gate／AUTO OFF。
